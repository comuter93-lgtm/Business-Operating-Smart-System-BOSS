from datetime import date
from decimal import Decimal
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import record_audit
from app.core.security import utcnow
from app.models.auth import User
from app.models.inventory import (
    ApprovalRequest,
    AssemblyOrder,
    BOM,
    BOMItem,
    BatchGenealogy,
    InventoryBatch,
    InventoryLedger,
    SKU,
)
from app.services.inventory_service import _money, _sellable_batch_available


def create_bom_request(
    db: Session,
    actor: User,
    *,
    bundle_sku_id: int,
    items: list[dict],
    notes: str | None = None,
) -> dict:
    bundle = db.query(SKU).filter(SKU.id == bundle_sku_id).first()
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle SKU not found")
    if not items:
        raise HTTPException(status_code=400, detail="BOM must contain at least one component")

    latest = db.query(BOM).filter(BOM.bundle_sku_id == bundle_sku_id).order_by(BOM.version.desc()).first()
    next_ver = (latest.version + 1) if latest else 1

    bom = BOM(
        bundle_sku_id=bundle_sku_id,
        version=next_ver,
        status="DRAFT_PENDING_APPROVAL",
        notes=notes,
    )
    db.add(bom)
    db.flush()

    for it in items:
        comp = db.query(SKU).filter(SKU.id == it["component_sku_id"]).first()
        if not comp:
            raise HTTPException(status_code=404, detail=f"Component SKU {it['component_sku_id']} not found")
        db.add(
            BOMItem(
                bom_id=bom.id,
                component_sku_id=comp.id,
                qty_required=int(it["qty_required"]),
                allow_substitution=bool(it.get("allow_substitution", False)),
                substitute_sku_id=it.get("substitute_sku_id"),
            )
        )

    approval = ApprovalRequest(
        request_type="BOM_CHANGE",
        status="PENDING",
        title=f"Approve BOM v{next_ver} for {bundle.sku_code}",
        problem_summary=notes or f"New BOM version v{next_ver} submitted for {bundle.name}",
        evidence_json={"bom_id": bom.id, "items": items},
        financial_impact_inr=Decimal("0.00"),
        proposed_action_json={"bom_id": bom.id, "bundle_sku_id": bundle_sku_id},
        responsible_person=actor.full_name,
        verification_method="Owner review of component ratios and substitutions",
        target_entity_type="bom",
        target_entity_id=str(bom.id),
        requested_by_id=actor.id,
    )
    db.add(approval)
    db.commit()
    db.refresh(bom)
    db.refresh(approval)
    return {"bom": bom, "approval_request": approval}


def create_assembly_order(
    db: Session,
    actor: User,
    *,
    bundle_sku_id: int,
    component_location_id: int,
    target_location_id: int,
    planned_qty: int,
    idempotency_key: str,
    assigned_to_id: int | None = None,
) -> AssemblyOrder:
    if planned_qty <= 0:
        raise HTTPException(status_code=400, detail="Planned assembly qty must be positive")
    existing = db.query(AssemblyOrder).filter(AssemblyOrder.idempotency_key == idempotency_key).first()
    if existing:
        return existing

    bom = db.query(BOM).filter(BOM.bundle_sku_id == bundle_sku_id, BOM.status == "ACTIVE").first()
    if not bom:
        raise HTTPException(status_code=404, detail="No active approved BOM found for bundle SKU")

    items = db.query(BOMItem).filter(BOMItem.bom_id == bom.id).all()
    # Verify and reserve components atomically
    for item in items:
        needed = item.qty_required * planned_qty
        batches = (
            db.query(InventoryBatch)
            .filter(
                InventoryBatch.sku_id == item.component_sku_id,
                InventoryBatch.location_id == component_location_id,
                InventoryBatch.remaining_qty > 0,
            )
            .order_by(InventoryBatch.inbound_date.asc(), InventoryBatch.id.asc())
            .all()
        )
        avail = sum(_sellable_batch_available(b) for b in batches)
        if avail < needed:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient component SKU {item.component_sku_id}: need {needed}, available {avail}",
            )
        rem = needed
        for b in batches:
            if rem <= 0:
                break
            take = min(_sellable_batch_available(b), rem)
            if take > 0:
                b.reserved_qty += take
                rem -= take

    order = AssemblyOrder(
        order_code=f"ASM-{uuid.uuid4().hex[:8].upper()}",
        bom_id=bom.id,
        bundle_sku_id=bundle_sku_id,
        component_location_id=component_location_id,
        target_location_id=target_location_id,
        planned_qty=planned_qty,
        status="RESERVED",
        assigned_to_id=assigned_to_id,
        idempotency_key=idempotency_key,
        created_by_id=actor.id,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    record_audit(
        db,
        actor=actor,
        action="assembly.reserve",
        resource_type="assembly_order",
        resource_id=str(order.id),
        outcome="SUCCESS",
        details={"bundle_sku_id": bundle_sku_id, "planned_qty": planned_qty},
    )
    return order


def complete_assembly_order(
    db: Session,
    actor: User,
    *,
    assembly_order_id: int,
    actual_produced_qty: int,
    wastage_qty: int = 0,
    completion_date: date | None = None,
) -> dict:
    order = db.query(AssemblyOrder).filter(AssemblyOrder.id == assembly_order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Assembly order not found")
    if order.status == "COMPLETED":
        # Prevent duplicate consumption on replay
        bundle_batch = db.query(InventoryBatch).filter(InventoryBatch.source_ref_id == order.order_code).first()
        return {"assembly_order": order, "bundle_batch": bundle_batch, "idempotent_replay": True}
    if order.status != "RESERVED":
        raise HTTPException(status_code=409, detail=f"Assembly order in invalid status {order.status}")
    if actual_produced_qty <= 0:
        raise HTTPException(status_code=400, detail="Produced quantity must be positive")

    items = db.query(BOMItem).filter(BOMItem.bom_id == order.bom_id).all()
    total_component_cost = Decimal("0.00")
    genealogy_records: list[dict] = []

    # Release reservation and consume actual required + wastage
    for item in items:
        reserved_total = item.qty_required * order.planned_qty
        consume_total = item.qty_required * (actual_produced_qty + wastage_qty)
        batches = (
            db.query(InventoryBatch)
            .filter(
                InventoryBatch.sku_id == item.component_sku_id,
                InventoryBatch.location_id == order.component_location_id,
            )
            .order_by(InventoryBatch.inbound_date.asc(), InventoryBatch.id.asc())
            .all()
        )
        # First unreserve previously reserved quantities
        unres = reserved_total
        for b in batches:
            if unres <= 0:
                break
            rel = min(b.reserved_qty, unres)
            b.reserved_qty -= rel
            unres -= rel

        # Now consume FIFO
        avail = sum(_sellable_batch_available(b) for b in batches)
        if avail < consume_total:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"Insufficient component {item.component_sku_id} during completion")

        rem = consume_total
        for b in batches:
            if rem <= 0:
                break
            take = min(_sellable_batch_available(b), rem)
            if take <= 0:
                continue
            b.remaining_qty -= take
            rem -= take
            total_component_cost += Decimal(take) * b.unit_cost
            genealogy_records.append(
                {
                    "component_batch_id": b.id,
                    "component_sku_id": item.component_sku_id,
                    "consumed_qty": take,
                    "component_inbound_date": b.inbound_date,
                }
            )
            db.add(
                InventoryLedger(
                    idempotency_key=f"ASM-CONSUME-{order.id}-{item.component_sku_id}-{b.id}",
                    tx_type="ASSEMBLY_CONSUME",
                    sku_id=item.component_sku_id,
                    location_id=order.component_location_id,
                    batch_id=b.id,
                    qty_delta=-take,
                    unit_cost=b.unit_cost,
                    actor_id=actor.id,
                    reference_type="ASSEMBLY_ORDER",
                    reference_id=order.order_code,
                    notes=f"Consumed for {order.order_code} (wastage={wastage_qty})",
                )
            )

    # Bundle inherits oldest component inbound_date so ageing is never masked
    oldest_component_date = min((g["component_inbound_date"] for g in genealogy_records), default=(completion_date or date.today()))
    bundle_unit_cost = _money(total_component_cost / Decimal(actual_produced_qty))

    bundle_batch = InventoryBatch(
        batch_code=f"BDL-{order.order_code}",
        sku_id=order.bundle_sku_id,
        location_id=order.target_location_id,
        inbound_date=oldest_component_date,
        initial_qty=actual_produced_qty,
        remaining_qty=actual_produced_qty,
        unit_cost=bundle_unit_cost,
        source_type="ASSEMBLY",
        source_ref_id=order.order_code,
    )
    db.add(bundle_batch)
    db.flush()

    for g in genealogy_records:
        db.add(
            BatchGenealogy(
                bundle_batch_id=bundle_batch.id,
                component_batch_id=g["component_batch_id"],
                component_sku_id=g["component_sku_id"],
                consumed_qty=g["consumed_qty"],
                component_inbound_date=g["component_inbound_date"],
            )
        )

    db.add(
        InventoryLedger(
            idempotency_key=f"ASM-PRODUCE-{order.id}",
            tx_type="ASSEMBLY_PRODUCE",
            sku_id=order.bundle_sku_id,
            location_id=order.target_location_id,
            batch_id=bundle_batch.id,
            qty_delta=actual_produced_qty,
            unit_cost=bundle_unit_cost,
            actor_id=actor.id,
            reference_type="ASSEMBLY_ORDER",
            reference_id=order.order_code,
            notes=f"Produced {actual_produced_qty} units; wastage {wastage_qty}",
        )
    )

    order.actual_produced_qty = actual_produced_qty
    order.wastage_qty = wastage_qty
    order.status = "COMPLETED"
    order.completed_at = utcnow()
    db.commit()
    db.refresh(order)
    db.refresh(bundle_batch)
    record_audit(
        db,
        actor=actor,
        action="assembly.complete",
        resource_type="assembly_order",
        resource_id=str(order.id),
        outcome="SUCCESS",
        details={"produced_qty": actual_produced_qty, "wastage_qty": wastage_qty, "effective_inbound_date": oldest_component_date.isoformat()},
    )
    return {"assembly_order": order, "bundle_batch": bundle_batch, "idempotent_replay": False}

