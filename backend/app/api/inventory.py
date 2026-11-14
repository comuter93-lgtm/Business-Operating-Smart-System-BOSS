from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import assert_location_access, evaluate_employee_access, get_current_user, require_action, require_owner
from app.core.storage import save_evidence_file
from app.models.inventory import InventoryLedger, Location, SKU
from app.models.auth import User
from app.services.inventory_service import (
    compute_inventory_ageing_report,
    compute_stock_availability,
    create_cycle_count,
    create_location,
    create_sku,
    dispatch_stock,
    receive_stock,
    request_inventory_adjustment,
    submit_cycle_count,
    transfer_stock,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory-warehouse"])


class LocationIn(BaseModel):
    code: str
    name: str
    location_type: str
    zone: str | None = None
    rack: str | None = None
    shelf: str | None = None
    bin_code: str | None = None
    fc_receiving_delay_days: int = 0
    is_sellable: bool | None = None


class SKUIn(BaseModel):
    sku_code: str
    barcode: str | None = None
    name: str
    brand: str = ""
    category: str
    item_type: str
    specifications_json: dict = {}
    variant_label: str | None = None
    purchase_cost: Decimal
    selling_price: Decimal
    mrp: Decimal
    hsn_code: str = "8413"
    gst_rate: Decimal = Decimal("18.00")
    dimensions_cm: str | None = None
    weight_grams: int = 0
    warranty_eligible: bool = True
    reorder_point: int = 10
    safety_stock: int = 5
    lead_time_days: int = 7
    primary_supplier_id: int | None = None
    amazon_asin: str | None = None
    amazon_sku: str | None = None
    flipkart_fsn: str | None = None
    flipkart_sku: str | None = None
    strategic_role: str = "CORE"


class ReceiveStockIn(BaseModel):
    sku_id: int
    location_id: int
    qty: int
    unit_cost: Decimal
    inbound_date: date | None = None
    source_type: str = "PO_RECEIPT"
    source_ref_id: str | None = None
    idempotency_key: str
    evidence_storage_key: str | None = None
    notes: str | None = None


class DispatchStockIn(BaseModel):
    sku_id: int
    location_id: int
    qty: int
    reference_type: str = "ORDER_DISPATCH"
    reference_id: str
    idempotency_key: str
    notes: str | None = None


class TransferStockIn(BaseModel):
    sku_id: int
    from_location_id: int
    to_location_id: int
    qty: int
    idempotency_key: str
    notes: str | None = None


class AdjustmentReqIn(BaseModel):
    sku_id: int
    location_id: int
    qty_delta: int
    reason: str
    evidence_storage_key: str | None = None


class CycleCountCreateIn(BaseModel):
    location_id: int
    assigned_to_id: int | None = None


class CycleCountSubmitIn(BaseModel):
    counts: list[dict]


@router.get("/locations")
def api_list_locations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Location)
    if user.role != "OWNER":
        eff = evaluate_employee_access(db, user)
        if not eff.accessible_location_ids:
            return []
        q = q.filter(Location.id.in_(eff.accessible_location_ids))
    return [
        {
            "id": l.id,
            "code": l.code,
            "name": l.name,
            "location_type": l.location_type,
            "zone": l.zone,
            "rack": l.rack,
            "shelf": l.shelf,
            "bin_code": l.bin_code,
            "fc_receiving_delay_days": l.fc_receiving_delay_days,
            "is_sellable": l.is_sellable,
        }
        for l in q.all()
    ]


@router.post("/locations")
def api_create_location(payload: LocationIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return create_location(db, owner, **payload.model_dump())


@router.get("/skus")

Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class SKUUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_code: str | None = Field(default=None, min_length=1)
    barcode: str | None = None
    name: str | None = Field(default=None, min_length=1)
    brand: str | None = None
    category: str | None = None
    item_type: str | None = None
    purchase_cost: Amount | None = None
    selling_price: Amount | None = None
    mrp: Amount | None = None
    gst_rate: Decimal | None = Field(
        default=None, ge=0, le=100, allow_inf_nan=False
    )
    warranty_eligible: bool | None = None
    reorder_point: int | None = Field(default=None, ge=0)
    strategic_role: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("फ़ील्ड को null के बजाय छोड़ दें")
        return value


@router.patch("/skus/{sku_id}")
def api_update_sku(
    sku_id: int,
    payload: SKUUpdate,
    # यहाँ अपने ऐप की वास्तविक inventory write permission इस्तेमाल करें।
    user: User = Depends(require_action("inventory.edit")),
    db: Session = Depends(get_db),
):
    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(400, "अपडेट के लिए कोई फ़ील्ड नहीं भेजी गई")

    if "purchase_cost" in changes and user.role != "OWNER":
        raise HTTPException(403, "Purchase cost केवल OWNER बदल सकता है")

    sku = db.query(SKU).filter(SKU.id == sku_id).first()
    if sku is None:
        raise HTTPException(404, "SKU नहीं मिला")

    try:
        for field, value in changes.items():
            setattr(sku, field, value)

        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "अपडेट डेटाबेस के किसी नियम से टकराता है"
        ) from None
    except Exception:
        db.rollback()
        raise

    return {"id": sku_id, "updated_fields": list(changes)}


@router.get("/availability")
def api_stock_availability(
    sku_id: int | None = None,
    location_id: int | None = None,
    request: Request = None,
    user: User = Depends(require_action("inventory.view")),
    db: Session = Depends(get_db),
):
    if location_id is not None:
        assert_location_access(db, user, location_id, request.client.host if request and request.client else None)
    return compute_stock_availability(db, sku_id=sku_id, location_id=location_id)


@router.post("/receive")
def api_receive_stock(
    payload: ReceiveStockIn,
    request: Request,
    user: User = Depends(require_action("receipt.create")),
    db: Session = Depends(get_db),
):
    assert_location_access(db, user, payload.location_id, request.client.host if request.client else None)
    res = receive_stock(db, user, **payload.model_dump())
    return {
        "batch_id": res["batch"].id,
        "batch_code": res["batch"].batch_code,
        "ledger_id": res["ledger"].id,
        "idempotent_replay": res["idempotent_replay"],
    }


@router.post("/dispatch")
def api_dispatch_stock(
    payload: DispatchStockIn,
    request: Request,
    user: User = Depends(require_action("dispatch.commit")),
    db: Session = Depends(get_db),
):
    assert_location_access(db, user, payload.location_id, request.client.host if request.client else None)
    res = dispatch_stock(db, user, **payload.model_dump())
    return {
        "ledger_count": len(res["ledger_entries"]),
        "cogs_inr": str(res["cogs_inr"]) if user.role == "OWNER" else None,
        "idempotent_replay": res["idempotent_replay"],
    }


@router.post("/transfer")
def api_transfer_stock(
    payload: TransferStockIn,
    request: Request,
    user: User = Depends(require_action("transfer.create")),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else None
    assert_location_access(db, user, payload.from_location_id, ip)
    assert_location_access(db, user, payload.to_location_id, ip)
    return transfer_stock(db, user, **payload.model_dump())


@router.post("/adjustments/request")
def api_request_adjustment(payload: AdjustmentReqIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assert_location_access(db, user, payload.location_id)
    req = request_inventory_adjustment(db, user, **payload.model_dump())
    return {"approval_request_id": req.id, "status": req.status}


@router.get("/ageing")
def api_ageing_report(
    as_of: date | None = None,
    user: User = Depends(require_action("inventory.view")),
    db: Session = Depends(get_db),
):
    return compute_inventory_ageing_report(db, as_of_date=as_of)


@router.get("/ledger")
def api_ledger(limit: int = 100, user: User = Depends(require_action("inventory.view")), db: Session = Depends(get_db)):
    q = db.query(InventoryLedger)
    if user.role != "OWNER":
        eff = evaluate_employee_access(db, user)
        if not eff.accessible_location_ids:
            return []
        q = q.filter(InventoryLedger.location_id.in_(eff.accessible_location_ids))
    rows = q.order_by(InventoryLedger.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "idempotency_key": r.idempotency_key,
            "tx_type": r.tx_type,
            "sku_id": r.sku_id,
            "location_id": r.location_id,
            "batch_id": r.batch_id,
            "qty_delta": r.qty_delta,
            "unit_cost": str(r.unit_cost) if user.role == "OWNER" else None,
            "reference_type": r.reference_type,
            "reference_id": r.reference_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/cycle-counts")
def api_create_cycle_count(payload: CycleCountCreateIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return create_cycle_count(db, owner, location_id=payload.location_id, assigned_to_id=payload.assigned_to_id)


@router.post("/cycle-counts/{cycle_count_id}/submit")
def api_submit_cycle_count(
    cycle_count_id: int,
    payload: CycleCountSubmitIn,
    user: User = Depends(require_action("cycle_count.submit")),
    db: Session = Depends(get_db),
):
    return submit_cycle_count(db, user, cycle_count_id=cycle_count_id, counts=payload.counts)


@router.post("/evidence")
async def api_upload_evidence(
    category: str = "warehouse",
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    content = await file.read()
    try:
        return save_evidence_file(file.filename or "evidence.jpg", content, category=category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

