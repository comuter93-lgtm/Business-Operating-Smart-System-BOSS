from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import threading
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

_STOCK_LOCK = threading.RLock()

from app.core.permissions import record_audit
from app.core.security import utcnow
from app.models.auth import BusinessSettings, User
from app.models.inventory import (
    ApprovalRequest,
    BatchGenealogy,
    CycleCount,
    CycleCountLine,
    InventoryBatch,
    InventoryLedger,
    Location,
    SKU,
)


def _money(val: Decimal | str | float | int) -> Decimal:
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def create_location(
    db: Session,
    owner: User,
    *,
    code: str,
    name: str,
    location_type: str,
    zone: str | None = None,
    rack: str | None = None,
    shelf: str | None = None,
    bin_code: str | None = None,
    fc_receiving_delay_days: int = 0,
    is_sellable: bool | None = None,
) -> Location:
    norm_code = code.strip().upper()
    if db.query(Location).filter(Location.code == norm_code).first():
        raise HTTPException(status_code=409, detail=f"Location {norm_code} already exists")
    if is_sellable is None:
        is_sellable = location_type in ("WAREHOUSE", "AMAZON_FC", "FLIPKART_FC")
    loc = Location(
        code=norm_code,
        name=name.strip(),
        location_type=location_type,
        zone=zone,
        rack=rack,
        shelf=shelf,
        bin_code=bin_code,
        fc_receiving_delay_days=fc_receiving_delay_days,
        is_sellable=is_sellable,
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    record_audit(db, actor=owner, action="location.create", resource_type="location", resource_id=str(loc.id), outcome="SUCCESS")
    return loc


def create_sku(db: Session, actor: User, data: dict) -> SKU:
    sku_code = data["sku_code"].strip().upper()
    if db.query(SKU).filter(SKU.sku_code == sku_code).first():
        raise HTTPException(status_code=409, detail=f"SKU {sku_code} already exists")
    gst_rate = Decimal(str(data.get("gst_rate", "18")))
    if gst_rate not in (Decimal("0"), Decimal("5"), Decimal("12"), Decimal("18"), Decimal("28")):
        raise HTTPException(status_code=400, detail="GST rate must be one of 0, 5, 12, 18, 28")

    sku = SKU(
        sku_code=sku_code,
        barcode=data.get("barcode"),
        name=data["name"].strip(),
        brand=data.get("brand", ""),
        category=data["category"],
        item_type=data["item_type"],
        specifications_json=data.get("specifications_json", {}),
        variant_label=data.get("variant_label"),
        purchase_cost=_money(data["purchase_cost"]),
        selling_price=_money(data["selling_price"]),
        mrp=_money(data["mrp"]),
        hsn_code=data.get("hsn_code", "8413"),
        gst_rate=gst_rate,
        dimensions_cm=data.get("dimensions_cm"),
        weight_grams=data.get("weight_grams", 0),
        warranty_eligible=data.get("warranty_eligible", True),
        reorder_point=data.get("reorder_point", 10),
        safety_stock=data.get("safety_stock", 5),
        lead_time_days=data.get("lead_time_days", 7),
        primary_supplier_id=data.get("primary_supplier_id"),
        amazon_asin=data.get("amazon_asin"),
        amazon_sku=data.get("amazon_sku"),
        flipkart_fsn=data.get("flipkart_fsn"),
        flipkart_sku=data.get("flipkart_sku"),
        strategic_role=data.get("strategic_role", "CORE"),
    )
    db.add(sku)
    db.commit()
    db.refresh(sku)
    record_audit(db, actor=actor, action="sku.create", resource_type="sku", resource_id=str(sku.id), outcome="SUCCESS")
    return sku


def receive_stock(
    db: Session,
    actor: User,
    *,
    sku_id: int,
    location_id: int,
    qty: int,
    unit_cost: Decimal,
    inbound_date: date | None = None,
    source_type: str = "PO_RECEIPT",
    source_ref_id: str | None = None,
    idempotency_key: str,
    evidence_storage_key: str | None = None,
    notes: str | None = None,
) -> dict:
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Receipt quantity must be positive")
    existing = db.query(InventoryLedger).filter(InventoryLedger.idempotency_key == idempotency_key).first()
    if existing:
        batch = db.query(InventoryBatch).filter(InventoryBatch.id == existing.batch_id).first()
        return {"ledger": existing, "batch": batch, "idempotent_replay": True}

    sku = db.query(SKU).filter(SKU.id == sku_id).first()
    loc = db.query(Location).filter(Location.id == location_id).first()
    if not sku or not loc:
        raise HTTPException(status_code=404, detail="SKU or Location not found")

    actual_inbound = inbound_date or date.today()
    cost = _money(unit_cost)
    batch_code = f"B-{sku.sku_code}-{actual_inbound.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    batch = InventoryBatch(
        batch_code=batch_code,
        sku_id=sku.id,
        location_id=loc.id,
        inbound_date=actual_inbound,
        initial_qty=qty,
        remaining_qty=qty,
        unit_cost=cost,
        source_type=source_type,
        source_ref_id=source_ref_id,
    )
    db.add(batch)
    db.flush()

    tx_type = "OPENING" if source_type == "OPENING" else "RECEIPT"
    ledger = InventoryLedger(
        idempotency_key=idempotency_key,
        tx_type=tx_type,
        sku_id=sku.id,
        location_id=loc.id,
        batch_id=batch.id,
        qty_delta=qty,
        unit_cost=cost,
        actor_id=actor.id,
        reference_type=source_type,
        reference_id=source_ref_id or batch_code,
        evidence_storage_key=evidence_storage_key,
        notes=notes,
    )
    db.add(ledger)
    db.commit()
    db.refresh(batch)
    db.refresh(ledger)
    record_audit(
        db,
        actor=actor,
        action="inventory.receive",
        resource_type="inventory_batch",
        resource_id=str(batch.id),
        outcome="SUCCESS",
        details={"sku_id": sku.id, "location_id": loc.id, "qty": qty},
    )
    return {"ledger": ledger, "batch": batch, "idempotent_replay": False}


def _sellable_batch_available(b: InventoryBatch) -> int:
    return max(0, b.remaining_qty - b.reserved_qty - b.damaged_qty - b.warranty_reserved_qty)


def dispatch_stock(
    db: Session,
    actor: User,
    *,
    sku_id: int,
    location_id: int,
    qty: int,
    reference_type: str,
    reference_id: str,
    idempotency_key: str,
    tx_type: str = "DISPATCH",
    dispatch_date: date | None = None,
    notes: str | None = None,
) -> dict:
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Dispatch quantity must be positive")
    existing = db.query(InventoryLedger).filter(InventoryLedger.idempotency_key == idempotency_key).first()
    if existing:
        return {"ledger_entries": [existing], "cogs_inr": _money(abs(existing.qty_delta) * existing.unit_cost), "idempotent_replay": True}

    loc = db.query(Location).filter(Location.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    if loc.location_type in ("IN_TRANSIT", "DAMAGED", "RETURNS_AREA", "SUPPLIER_RETURN"):
        raise HTTPException(status_code=400, detail=f"Cannot dispatch sellable stock directly from {loc.location_type}")

    with _STOCK_LOCK:
        q = (
            db.query(InventoryBatch)
            .filter(
                InventoryBatch.sku_id == sku_id,
                InventoryBatch.location_id == location_id,
                InventoryBatch.remaining_qty > 0,
            )
            .order_by(InventoryBatch.inbound_date.asc(), InventoryBatch.id.asc())
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            q = q.with_for_update()
        batches = q.all()

        total_avail = sum(_sellable_batch_available(b) for b in batches)
        if total_avail < qty:
            raise HTTPException(status_code=409, detail=f"Insufficient available stock: requested {qty}, available {total_avail}")

        remaining_to_take = qty
        total_cogs = Decimal("0.00")
        entries: list[InventoryLedger] = []
        actual_date = dispatch_date or date.today()

        for idx, b in enumerate(batches):
            if remaining_to_take <= 0:
                break
            avail = _sellable_batch_available(b)
            if avail <= 0:
                continue
            take = min(avail, remaining_to_take)
            b.remaining_qty -= take
            if (actual_date - b.inbound_date).days <= 15:
                b.sold_first_15d_qty += take
            remaining_to_take -= take
            total_cogs += Decimal(take) * b.unit_cost

            sub_key = idempotency_key if idx == 0 and remaining_to_take == 0 else f"{idempotency_key}:b{b.id}"
            entry = InventoryLedger(
                idempotency_key=sub_key,
                tx_type=tx_type,
                sku_id=sku_id,
                location_id=location_id,
                batch_id=b.id,
                qty_delta=-take,
                unit_cost=b.unit_cost,
                actor_id=actor.id,
                reference_type=reference_type,
                reference_id=reference_id,
                notes=notes,
            )
            db.add(entry)
            entries.append(entry)

        db.commit()
    record_audit(
        db,
        actor=actor,
        action=f"inventory.{tx_type.lower()}",
        resource_type="sku",
        resource_id=str(sku_id),
        outcome="SUCCESS",
        details={"location_id": location_id, "qty": qty, "reference_id": reference_id},
    )
    return {"ledger_entries": entries, "cogs_inr": _money(total_cogs), "idempotent_replay": False}


def transfer_stock(
    db: Session,
    actor: User,
    *,
    sku_id: int,
    from_location_id: int,
    to_location_id: int,
    qty: int,
    idempotency_key: str,
    notes: str | None = None,
) -> dict:
    """Transfer stock between locations while strictly preserving original inbound_date."""
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Transfer quantity must be positive")
    if from_location_id == to_location_id:
        raise HTTPException(status_code=400, detail="Source and destination locations must differ")

    existing = db.query(InventoryLedger).filter(InventoryLedger.idempotency_key == idempotency_key).first()
    if existing:
        return {"transferred_qty": abs(existing.qty_delta), "idempotent_replay": True}

    from_loc = db.query(Location).filter(Location.id == from_location_id).first()
    to_loc = db.query(Location).filter(Location.id == to_location_id).first()
    if not from_loc or not to_loc:
        raise HTTPException(status_code=404, detail="Source or destination location not found")

    with _STOCK_LOCK:
        q = (
            db.query(InventoryBatch)
            .filter(
                InventoryBatch.sku_id == sku_id,
                InventoryBatch.location_id == from_location_id,
                InventoryBatch.remaining_qty > 0,
            )
            .order_by(InventoryBatch.inbound_date.asc(), InventoryBatch.id.asc())
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            q = q.with_for_update()
        batches = q.all()
        total_avail = sum(_sellable_batch_available(b) for b in batches)
        if total_avail < qty:
            raise HTTPException(status_code=409, detail=f"Insufficient stock for transfer: requested {qty}, available {total_avail}")

        remaining = qty
        created_batches = []
        for idx, src in enumerate(batches):
            if remaining <= 0:
                break
            avail = _sellable_batch_available(src)
            if avail <= 0:
                continue
            take = min(avail, remaining)
            src.remaining_qty -= take
            remaining -= take

            dest_batch = InventoryBatch(
                batch_code=f"TR-{src.batch_code}-{uuid.uuid4().hex[:4].upper()}",
                sku_id=sku_id,
                location_id=to_location_id,
                origin_batch_id=src.origin_batch_id or src.id,
                inbound_date=src.inbound_date,  # PRESERVES original ageing date!
                initial_qty=take,
                remaining_qty=take,
                unit_cost=src.unit_cost,
                source_type="TRANSFER",
                source_ref_id=src.batch_code,
            )
            db.add(dest_batch)
            db.flush()
            created_batches.append(dest_batch)

            out_key = idempotency_key if idx == 0 and remaining == 0 else f"{idempotency_key}:out:{src.id}"
            db.add(
                InventoryLedger(
                    idempotency_key=out_key,
                    tx_type="TRANSFER_OUT",
                    sku_id=sku_id,
                    location_id=from_location_id,
                    batch_id=src.id,
                    qty_delta=-take,
                    unit_cost=src.unit_cost,
                    actor_id=actor.id,
                    reference_type="TRANSFER",
                    reference_id=dest_batch.batch_code,
                    notes=notes,
                )
            )
            db.add(
                InventoryLedger(
                    idempotency_key=f"{idempotency_key}:in:{dest_batch.id}",
                    tx_type="TRANSFER_IN",
                    sku_id=sku_id,
                    location_id=to_location_id,
                    batch_id=dest_batch.id,
                    qty_delta=take,
                    unit_cost=src.unit_cost,
                    actor_id=actor.id,
                    reference_type="TRANSFER",
                    reference_id=src.batch_code,
                    notes=notes,
                )
            )

        db.commit()
    record_audit(
        db,
        actor=actor,
        action="inventory.transfer",
        resource_type="sku",
        resource_id=str(sku_id),
        outcome="SUCCESS",
        details={"from": from_location_id, "to": to_location_id, "qty": qty},
    )
    return {"transferred_qty": qty, "destination_batches": [b.id for b in created_batches], "idempotent_replay": False}


def compute_stock_availability(db: Session, sku_id: int | None = None, location_id: int | None = None, *, location_ids=None) -> list[dict]:
    q = db.query(InventoryBatch, SKU, Location).join(SKU, InventoryBatch.sku_id == SKU.id).join(
        Location, InventoryBatch.location_id == Location.id
    )
    if sku_id is not None:
        q = q.filter(InventoryBatch.sku_id == sku_id)
    if location_id is not None:
        q = q.filter(InventoryBatch.location_id == location_id)

    if location_ids is not None:
        q = q.filter(InventoryBatch.location_id.in_(location_ids))

    agg: dict[int, dict] = {}
    for batch, sku, loc in q.all():
        row = agg.setdefault(
            sku.id,
            {
                "sku_id": sku.id,
                "sku_code": sku.sku_code,
                "name": sku.name,
                "item_type": sku.item_type,
                "physical_qty": 0,
                "reserved_qty": 0,
                "available_qty": 0,
                "damaged_qty": 0,
                "warranty_reserved_qty": 0,
                "in_transit_qty": 0,
                "marketplace_held_qty": 0,
                "stock_value_inr": Decimal("0.00"),
            },
        )
        rem = batch.remaining_qty
        if loc.location_type == "IN_TRANSIT":
            row["in_transit_qty"] += rem
        elif loc.location_type == "DAMAGED":
            row["damaged_qty"] += rem
        elif loc.location_type in ("AMAZON_FC", "FLIPKART_FC"):
            row["physical_qty"] += rem
            row["marketplace_held_qty"] += rem
            row["available_qty"] += _sellable_batch_available(batch)
        elif loc.location_type in ("WAREHOUSE", "RECEIVING"):
            row["physical_qty"] += rem
            row["reserved_qty"] += batch.reserved_qty
            row["damaged_qty"] += batch.damaged_qty
            row["warranty_reserved_qty"] += batch.warranty_reserved_qty
            if loc.is_sellable:
                row["available_qty"] += _sellable_batch_available(batch)
        else:
            # RETURNS_AREA / SUPPLIER_RETURN: physical present but not sellable
            row["physical_qty"] += rem

        row["stock_value_inr"] += Decimal(rem) * batch.unit_cost

    for r in agg.values():
        r["stock_value_inr"] = str(_money(r["stock_value_inr"]))
    return list(agg.values())


def classify_batch_age(age_days: int, settings_row: BusinessSettings) -> str:
    if age_days >= settings_row.critical_age_days:
        return "CRITICAL"
    if age_days >= settings_row.red_age_days:
        return "RED"
    return "NORMAL"


def compute_inventory_ageing_report(db: Session, as_of_date: date | None = None, *, location_ids=None) -> dict:
    ref_date = as_of_date or date.today()
    bs = db.query(BusinessSettings).first()
    if not bs:
        bs = BusinessSettings(business_name="BOSS", gstin="", home_state="DL")

    batches = (
        db.query(InventoryBatch, SKU, Location)
        .join(SKU, InventoryBatch.sku_id == SKU.id)
        .join(Location, InventoryBatch.location_id == Location.id)
        .filter(InventoryBatch.remaining_qty > 0)
    )
    if location_ids is not None:
        batches = batches.filter(InventoryBatch.location_id.in_(location_ids))

    items = []
    totals = {"NORMAL": {"units": 0, "value_inr": Decimal("0.00")}, "RED": {"units": 0, "value_inr": Decimal("0.00")}, "CRITICAL": {"units": 0, "value_inr": Decimal("0.00")}}

    for b, sku, loc in batches:
        effective_date = b.inbound_date
        if bs.bundle_ageing_policy == "OLDEST_COMPONENT" and sku.item_type == "BUNDLE":
            gens = db.query(BatchGenealogy).filter(BatchGenealogy.bundle_batch_id == b.id).all()
            if gens:
                effective_date = min([g.component_inbound_date for g in gens] + [b.inbound_date])

        age_days = max(0, (ref_date - effective_date).days)
        tier = classify_batch_age(age_days, bs)
        val = _money(Decimal(b.remaining_qty) * b.unit_cost)
        sell_through_15d_pct = (
            float((Decimal(b.sold_first_15d_qty) / Decimal(b.initial_qty)) * Decimal("100"))
            if b.initial_qty > 0
            else 0.0
        )

        totals[tier]["units"] += b.remaining_qty
        totals[tier]["value_inr"] += val

        items.append(
            {
                "batch_id": b.id,
                "batch_code": b.batch_code,
                "sku_id": sku.id,
                "sku_code": sku.sku_code,
                "sku_name": sku.name,
                "item_type": sku.item_type,
                "location_code": loc.code,
                "inbound_date": effective_date.isoformat(),
                "age_days": age_days,
                "classification": tier,
                "remaining_qty": b.remaining_qty,
                "blocked_capital_inr": str(val),
                "sell_through_15d_pct": round(sell_through_15d_pct, 2),
                "action_note": (
                    "Escalate to Owner: evaluate profit-safe bundle promo or channel redistribution"
                    if tier == "CRITICAL"
                    else ("Slow-moving alert: review pricing/visibility without forced loss" if tier == "RED" else "Normal velocity monitoring")
                ),
            }
        )

    return {
        "as_of_date": ref_date.isoformat(),
        "thresholds": {
            "target_selling_days": bs.target_selling_days,
            "red_age_days": bs.red_age_days,
            "critical_age_days": bs.critical_age_days,
            "bundle_ageing_policy": bs.bundle_ageing_policy,
        },
        "summary": {
            k: {"units": v["units"], "value_inr": str(_money(v["value_inr"]))} for k, v in totals.items()
        },
        "batches": sorted(items, key=lambda x: x["age_days"], reverse=True),
    }


def request_inventory_adjustment(
    db: Session,
    actor: User,
    *,
    sku_id: int,
    location_id: int,
    qty_delta: int,
    reason: str,
    evidence_storage_key: str | None = None,
) -> ApprovalRequest:
    sku = db.query(SKU).filter(SKU.id == sku_id).first()
    loc = db.query(Location).filter(Location.id == location_id).first()
    if not sku or not loc:
        raise HTTPException(status_code=404, detail="SKU or Location not found")
    impact = _money(Decimal(abs(qty_delta)) * sku.purchase_cost)
    req = ApprovalRequest(
        request_type="INVENTORY_ADJUSTMENT",
        status="PENDING",
        title=f"Inventory adjustment: {sku.sku_code} ({qty_delta:+d}) at {loc.code}",
        problem_summary=reason,
        evidence_json={"sku_id": sku.id, "location_id": loc.id, "qty_delta": qty_delta, "evidence": evidence_storage_key},
        financial_impact_inr=impact,
        proposed_action_json={"sku_id": sku.id, "location_id": loc.id, "qty_delta": qty_delta, "evidence_storage_key": evidence_storage_key},
        responsible_person=actor.full_name,
        verification_method="Physical re-count & ledger reconciliation",
        target_entity_type="sku",
        target_entity_id=str(sku.id),
        requested_by_id=actor.id,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def create_cycle_count(db: Session, owner: User, *, location_id: int, assigned_to_id: int | None = None) -> CycleCount:
    loc = db.query(Location).filter(Location.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    cc = CycleCount(
        count_code=f"CC-{loc.code}-{uuid.uuid4().hex[:6].upper()}",
        location_id=location_id,
        status="OPEN",
        assigned_to_id=assigned_to_id,
        created_by_id=owner.id,
    )
    db.add(cc)
    db.flush()

    avail_rows = compute_stock_availability(db, location_id=location_id)
    for r in avail_rows:
        db.add(
            CycleCountLine(
                cycle_count_id=cc.id,
                sku_id=r["sku_id"],
                system_qty=r["physical_qty"],
            )
        )
    db.commit()
    db.refresh(cc)
    return cc


def submit_cycle_count(db: Session, actor: User, *, cycle_count_id: int, counts: list[dict]) -> dict:
    cc = db.query(CycleCount).filter(CycleCount.id == cycle_count_id).first()
    if not cc:
        raise HTTPException(status_code=404, detail="Cycle count not found")
    if cc.status != "OPEN":
        raise HTTPException(status_code=409, detail="Cycle count already submitted")

    count_map = {int(c["sku_id"]): int(c["counted_qty"]) for c in counts}
    lines = db.query(CycleCountLine).filter(CycleCountLine.cycle_count_id == cc.id).all()
    approvals_created = []
    for line in lines:
        if line.sku_id in count_map:
            line.counted_qty = count_map[line.sku_id]
            line.variance_qty = line.counted_qty - line.system_qty
            if line.variance_qty != 0:
                app_req = request_inventory_adjustment(
                    db,
                    actor,
                    sku_id=line.sku_id,
                    location_id=cc.location_id,
                    qty_delta=line.variance_qty,
                    reason=f"Cycle count {cc.count_code} variance ({line.variance_qty:+d})",
                )
                line.approval_id = app_req.id
                approvals_created.append(app_req.id)

    cc.status = "SUBMITTED"
    cc.completed_at = utcnow()
    db.commit()
    return {"cycle_count_id": cc.id, "status": cc.status, "approval_requests_created": approvals_created}
