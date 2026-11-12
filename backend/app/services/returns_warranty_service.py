from datetime import timedelta
from decimal import Decimal
import math
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import record_audit
from app.core.security import ensure_utc, utcnow
from app.models.auth import BusinessSettings, User
from app.models.inventory import ApprovalRequest, BOM, BOMItem, InventoryBatch, Location, SKU
from app.models.operations import ReturnCase, WarrantyClaim
from app.services.inventory_service import _money, dispatch_stock, receive_stock


def create_return_case(
    db: Session,
    actor: User,
    *,
    channel: str,
    sku_id: int,
    location_id: int,
    qty: int = 1,
    external_order_id: str | None = None,
    received_now: bool = False,
) -> ReturnCase:
    sku = db.query(SKU).filter(SKU.id == sku_id).first()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    bs = db.query(BusinessSettings).first()
    sla_hours = bs.return_inspection_sla_hours if bs else 48
    now = utcnow()
    rc = ReturnCase(
        return_code=f"RET-{uuid.uuid4().hex[:8].upper()}",
        channel=channel,
        external_order_id=external_order_id,
        sku_id=sku_id,
        qty=qty,
        location_id=location_id,
        status="RECEIVED" if received_now else "EXPECTED",
        received_at=now if received_now else None,
        inspection_due_at=(now + timedelta(hours=sla_hours)) if received_now else None,
    )
    db.add(rc)
    db.commit()
    db.refresh(rc)
    record_audit(db, actor=actor, action="return.create", resource_type="return_case", resource_id=str(rc.id), outcome="SUCCESS")
    return rc


def mark_return_received(db: Session, actor: User, return_id: int) -> ReturnCase:
    rc = db.query(ReturnCase).filter(ReturnCase.id == return_id).first()
    if not rc:
        raise HTTPException(status_code=404, detail="Return case not found")
    bs = db.query(BusinessSettings).first()
    sla_hours = bs.return_inspection_sla_hours if bs else 48
    now = utcnow()
    rc.status = "RECEIVED"
    rc.received_at = now
    rc.inspection_due_at = now + timedelta(hours=sla_hours)
    db.commit()
    db.refresh(rc)
    return rc


def inspect_return_case(
    db: Session,
    actor: User,
    *,
    return_id: int,
    classification: str,
    returned_component_qtys: dict[int, int] | None = None,
    restock_location_id: int | None = None,
    damaged_location_id: int | None = None,
    evidence_storage_key: str | None = None,
    notes: str | None = None,
) -> dict:
    rc = db.query(ReturnCase).filter(ReturnCase.id == return_id).first()
    if not rc:
        raise HTTPException(status_code=404, detail="Return case not found")
    if classification not in ("RESALABLE", "USED", "DAMAGED", "INCOMPLETE", "UNDER_INVESTIGATION"):
        raise HTTPException(status_code=400, detail="Invalid return classification")

    sku = db.query(SKU).filter(SKU.id == rc.sku_id).first()
    missing_components = []
    estimated_loss = Decimal("0.00")

    # Compare returned bundle parts against approved active BOM
    if sku and sku.item_type == "BUNDLE":
        bom = db.query(BOM).filter(BOM.bundle_sku_id == sku.id, BOM.status == "ACTIVE").first()
        if bom:
            bom_items = db.query(BOMItem).filter(BOMItem.bom_id == bom.id).all()
            provided = returned_component_qtys or {}
            for item in bom_items:
                expected_qty = item.qty_required * rc.qty
                actual_qty = int(provided.get(item.component_sku_id, 0))
                if actual_qty < expected_qty:
                    missing_qty = expected_qty - actual_qty
                    comp_sku = db.query(SKU).filter(SKU.id == item.component_sku_id).first()
                    comp_cost = comp_sku.purchase_cost if comp_sku else Decimal("0.00")
                    comp_loss = _money(Decimal(missing_qty) * comp_cost)
                    estimated_loss += comp_loss
                    missing_components.append(
                        {
                            "component_sku_id": item.component_sku_id,
                            "component_sku_code": comp_sku.sku_code if comp_sku else str(item.component_sku_id),
                            "expected_qty": expected_qty,
                            "received_qty": actual_qty,
                            "missing_qty": missing_qty,
                            "estimated_cost_inr": str(comp_loss),
                        }
                    )
            if missing_components and classification == "RESALABLE":
                classification = "INCOMPLETE"

    if classification in ("DAMAGED", "USED") and estimated_loss == Decimal("0.00") and sku:
        estimated_loss = _money(Decimal(rc.qty) * sku.purchase_cost)

    rc.status = "CLASSIFIED"
    rc.inspected_at = utcnow()
    rc.inspected_by_id = actor.id
    rc.classification = classification
    rc.missing_components_json = missing_components
    rc.estimated_loss_inr = estimated_loss
    rc.evidence_storage_key = evidence_storage_key
    rc.notes = notes
    if missing_components or classification == "DAMAGED":
        rc.recovery_status = "CLAIM_FILED"

    # Update physical inventory ledger based on classification
    if classification == "RESALABLE" and restock_location_id and sku:
        receive_stock(
            db,
            actor,
            sku_id=sku.id,
            location_id=restock_location_id,
            qty=rc.qty,
            unit_cost=sku.purchase_cost,
            source_type="RETURN",
            source_ref_id=rc.return_code,
            idempotency_key=f"RET-RESTOCK-{rc.id}",
            evidence_storage_key=evidence_storage_key,
            notes=f"Resalable return {rc.return_code}",
        )
    elif classification in ("DAMAGED", "INCOMPLETE") and damaged_location_id and sku:
        receive_stock(
            db,
            actor,
            sku_id=sku.id,
            location_id=damaged_location_id,
            qty=rc.qty,
            unit_cost=sku.purchase_cost,
            source_type="RETURN",
            source_ref_id=rc.return_code,
            idempotency_key=f"RET-DMG-{rc.id}",
            evidence_storage_key=evidence_storage_key,
            notes=f"{classification} return {rc.return_code}",
        )

    db.commit()
    db.refresh(rc)
    record_audit(
        db,
        actor=actor,
        action="return.inspect",
        resource_type="return_case",
        resource_id=str(rc.id),
        outcome="SUCCESS",
        details={"classification": classification, "missing_components": len(missing_components)},
    )
    return {"return_case": rc, "missing_components": missing_components}


def get_overdue_return_inspections(db: Session) -> list[ReturnCase]:
    now = utcnow()
    rows = db.query(ReturnCase).filter(ReturnCase.status == "RECEIVED", ReturnCase.inspection_due_at.isnot(None)).all()
    return [r for r in rows if ensure_utc(r.inspection_due_at) < now]


def compute_warranty_reserve_status(db: Session) -> list[dict]:
    """Rule: reserve >= max(1, ceil(2% of eligible own-warehouse stock)) for active warranty-eligible SKUs."""
    bs = db.query(BusinessSettings).first()
    pct = (bs.warranty_reserve_pct if bs else Decimal("2.00")) / Decimal("100")
    min_units = bs.warranty_min_units if bs else 1

    skus = db.query(SKU).filter(SKU.is_active.is_(True), SKU.warranty_eligible.is_(True)).all()
    warehouse_locs = [l.id for l in db.query(Location).filter(Location.location_type == "WAREHOUSE").all()]

    report = []
    for sku in skus:
        batches = (
            db.query(InventoryBatch)
            .filter(
                InventoryBatch.sku_id == sku.id,
                InventoryBatch.location_id.in_(warehouse_locs) if warehouse_locs else False,
                InventoryBatch.remaining_qty > 0,
            )
            .all()
            if warehouse_locs
            else []
        )
        eligible_stock = sum(b.remaining_qty for b in batches)
        actual_reserved = sum(b.warranty_reserved_qty for b in batches)
        required_reserve = max(min_units, math.ceil(float(Decimal(eligible_stock) * pct))) if eligible_stock > 0 else min_units
        shortage = max(0, required_reserve - actual_reserved)
        report.append(
            {
                "sku_id": sku.id,
                "sku_code": sku.sku_code,
                "sku_name": sku.name,
                "eligible_own_warehouse_stock": eligible_stock,
                "required_reserve": required_reserve,
                "actual_warranty_reserved": actual_reserved,
                "shortage": shortage,
                "status": "SHORTAGE" if shortage > 0 else "OK",
            }
        )
    return report


def create_warranty_replacement_request(
    db: Session,
    actor: User,
    *,
    sku_id: int,
    customer_ref: str,
    issue_description: str,
    replacement_qty: int = 1,
    serial_or_batch: str | None = None,
) -> dict:
    sku = db.query(SKU).filter(SKU.id == sku_id).first()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    claim = WarrantyClaim(
        claim_code=f"WAR-{uuid.uuid4().hex[:8].upper()}",
        sku_id=sku_id,
        customer_ref=customer_ref,
        serial_or_batch=serial_or_batch,
        issue_description=issue_description,
        replacement_qty=replacement_qty,
        status="PENDING_APPROVAL",
        created_by_id=actor.id,
    )
    db.add(claim)
    db.flush()

    approval = ApprovalRequest(
        request_type="WARRANTY_REPLACEMENT",
        status="PENDING",
        title=f"Warranty replacement: {sku.sku_code} x{replacement_qty}",
        problem_summary=f"Customer {customer_ref}: {issue_description}",
        evidence_json={"claim_id": claim.id, "serial_or_batch": serial_or_batch},
        financial_impact_inr=_money(Decimal(replacement_qty) * sku.purchase_cost),
        proposed_action_json={"claim_id": claim.id, "sku_id": sku_id, "qty": replacement_qty},
        responsible_person=actor.full_name,
        verification_method="Owner verification of defective unit / claim proof",
        target_entity_type="warranty_claim",
        target_entity_id=str(claim.id),
        requested_by_id=actor.id,
    )
    db.add(approval)
    db.flush()
    claim.approval_id = approval.id
    db.commit()
    db.refresh(claim)
    db.refresh(approval)
    return {"claim": claim, "approval_request": approval}


def fulfill_warranty_claim(db: Session, owner: User, claim_id: int, warehouse_location_id: int) -> WarrantyClaim:
    claim = db.query(WarrantyClaim).filter(WarrantyClaim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Warranty claim not found")
    if claim.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Warranty claim requires Owner approval before fulfillment")

    dispatch_stock(
        db,
        owner,
        sku_id=claim.sku_id,
        location_id=warehouse_location_id,
        qty=claim.replacement_qty,
        reference_type="WARRANTY_CLAIM",
        reference_id=claim.claim_code,
        idempotency_key=f"WAR-FULFILL-{claim.id}",
        tx_type="WARRANTY_REPLACEMENT",
        notes=f"Warranty replacement for {claim.customer_ref}",
    )
    claim.status = "FULFILLED"
    claim.fulfilled_at = utcnow()
    db.commit()
    db.refresh(claim)
    return claim

