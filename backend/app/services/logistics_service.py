from datetime import datetime
from decimal import Decimal
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import record_audit
from app.core.security import utcnow
from app.models.auth import User
from app.models.operations import Shipment
from app.services.inventory_service import _money


def create_shipment(
    db: Session,
    actor: User,
    *,
    direction: str,
    channel: str,
    carrier: str,
    tracking_number: str | None = None,
    origin_location_id: int | None = None,
    destination_location_id: int | None = None,
    freight_cost: Decimal = Decimal("0.00"),
    packaging_cost: Decimal = Decimal("0.00"),
    expected_delivery_at: datetime | None = None,
    notes: str | None = None,
) -> Shipment:
    sh = Shipment(
        shipment_code=f"SHP-{uuid.uuid4().hex[:8].upper()}",
        direction=direction,
        channel=channel,
        carrier=carrier,
        tracking_number=tracking_number,
        origin_location_id=origin_location_id,
        destination_location_id=destination_location_id,
        freight_cost=_money(freight_cost),
        packaging_cost=_money(packaging_cost),
        status="IN_TRANSIT",
        expected_delivery_at=expected_delivery_at,
        notes=notes,
    )
    db.add(sh)
    db.commit()
    db.refresh(sh)
    record_audit(db, actor=actor, action="shipment.create", resource_type="shipment", resource_id=str(sh.id), outcome="SUCCESS")
    return sh


def update_shipment_status(db: Session, actor: User, shipment_id: int, status: str, notes: str | None = None) -> Shipment:
    sh = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not sh:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if status not in ("CREATED", "IN_TRANSIT", "DELAYED", "DELIVERED", "LOST_INVESTIGATION"):
        raise HTTPException(status_code=400, detail="Invalid shipment status")
    sh.status = status
    if status == "DELIVERED":
        sh.delivered_at = utcnow()
    if notes:
        sh.notes = notes
    db.commit()
    db.refresh(sh)
    record_audit(db, actor=actor, action="shipment.status_update", resource_type="shipment", resource_id=str(sh.id), outcome="SUCCESS", details={"status": status})
    return sh


def carrier_performance_summary(db: Session) -> list[dict]:
    shipments = db.query(Shipment).all()
    by_carrier: dict[str, dict] = {}
    for s in shipments:
        row = by_carrier.setdefault(
            s.carrier,
            {"carrier": s.carrier, "total_shipments": 0, "delivered": 0, "delayed_or_lost": 0, "total_freight_inr": Decimal("0.00")},
        )
        row["total_shipments"] += 1
        if s.status == "DELIVERED":
            row["delivered"] += 1
        if s.status in ("DELAYED", "LOST_INVESTIGATION"):
            row["delayed_or_lost"] += 1
        row["total_freight_inr"] += s.freight_cost

    return [
        {
            "carrier": r["carrier"],
            "total_shipments": r["total_shipments"],
            "delivered": r["delivered"],
            "delayed_or_lost": r["delayed_or_lost"],
            "avg_freight_inr": str(_money(r["total_freight_inr"] / Decimal(r["total_shipments"]))),
            "reliability_pct": round(((r["total_shipments"] - r["delayed_or_lost"]) / r["total_shipments"]) * 100, 1),
        }
        for r in by_carrier.values()
    ]

