from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, require_action, require_owner
from app.models.auth import User
from app.models.inventory import ApprovalRequest, AssemblyOrder, BOM, BOMItem
from app.models.operations import DiscrepancyCase, ReturnCase, Shipment, WarrantyClaim
from app.services.approval_service import review_approval_request
from app.services.assembly_service import complete_assembly_order, create_assembly_order, create_bom_request
from app.services.logistics_service import carrier_performance_summary, create_shipment, update_shipment_status
from app.services.marketplace_service import (
    get_marketplace_statuses,
    import_marketplace_report,
    parse_csv_report,
    run_marketplace_reconciliation,
)
from app.services.returns_warranty_service import (
    compute_warranty_reserve_status,
    create_return_case,
    create_warranty_replacement_request,
    fulfill_warranty_claim,
    get_overdue_return_inspections,
    inspect_return_case,
    mark_return_received,
)

router = APIRouter(prefix="/api/v1", tags=["assembly-returns-marketplaces-logistics"])


# --- Approvals ---
class ReviewApprovalIn(BaseModel):
    decision: str  # APPROVED | REJECTED
    review_notes: str | None = None


@router.get("/approvals")
def api_list_approvals(status: str = "PENDING", owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    rows = db.query(ApprovalRequest).filter(ApprovalRequest.status == status).order_by(ApprovalRequest.created_at.desc()).all()
    return [
        {
            "id": a.id,
            "request_type": a.request_type,
            "status": a.status,
            "title": a.title,
            "problem_summary": a.problem_summary,
            "evidence_json": a.evidence_json,
            "financial_impact_inr": str(a.financial_impact_inr),
            "proposed_action_json": a.proposed_action_json,
            "responsible_person": a.responsible_person,
            "verification_method": a.verification_method,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.post("/approvals/{approval_id}/review")
def api_review_approval(
    approval_id: int,
    payload: ReviewApprovalIn,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    req = review_approval_request(db, owner, approval_id=approval_id, decision=payload.decision, review_notes=payload.review_notes)
    return {"id": req.id, "status": req.status, "request_type": req.request_type}


# --- BOM & Assembly ---
class BOMCreateIn(BaseModel):
    bundle_sku_id: int
    items: list[dict]
    notes: str | None = None


class AssemblyReserveIn(BaseModel):
    bundle_sku_id: int
    component_location_id: int
    target_location_id: int
    planned_qty: int
    idempotency_key: str
    assigned_to_id: int | None = None


class AssemblyCompleteIn(BaseModel):
    actual_produced_qty: int
    wastage_qty: int = 0


@router.get("/boms")
def api_list_boms(user: User = Depends(require_action("inventory.view")), db: Session = Depends(get_db)):
    boms = db.query(BOM).order_by(BOM.id.desc()).all()
    out = []
    for b in boms:
        items = db.query(BOMItem).filter(BOMItem.bom_id == b.id).all()
        out.append(
            {
                "id": b.id,
                "bundle_sku_id": b.bundle_sku_id,
                "version": b.version,
                "status": b.status,
                "notes": b.notes,
                "items": [
                    {
                        "component_sku_id": it.component_sku_id,
                        "qty_required": it.qty_required,
                        "allow_substitution": it.allow_substitution,
                        "substitute_sku_id": it.substitute_sku_id,
                    }
                    for it in items
                ],
            }
        )
    return out


@router.post("/boms/request")
def api_request_bom(payload: BOMCreateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    res = create_bom_request(db, user, **payload.model_dump())
    return {"bom_id": res["bom"].id, "version": res["bom"].version, "status": res["bom"].status, "approval_request_id": res["approval_request"].id}


@router.get("/assembly/orders")
def api_list_assembly_orders(user: User = Depends(require_action("inventory.view")), db: Session = Depends(get_db)):
    return db.query(AssemblyOrder).order_by(AssemblyOrder.id.desc()).all()


@router.post("/assembly/orders")
def api_create_assembly_order(payload: AssemblyReserveIn, user: User = Depends(require_action("assembly.execute")), db: Session = Depends(get_db)):
    return create_assembly_order(db, user, **payload.model_dump())


@router.post("/assembly/orders/{order_id}/complete")
def api_complete_assembly_order(
    order_id: int,
    payload: AssemblyCompleteIn,
    user: User = Depends(require_action("assembly.execute")),
    db: Session = Depends(get_db),
):
    res = complete_assembly_order(db, user, assembly_order_id=order_id, **payload.model_dump())
    return {
        "order_id": res["assembly_order"].id,
        "status": res["assembly_order"].status,
        "bundle_batch_code": res["bundle_batch"].batch_code if res["bundle_batch"] else None,
        "effective_inbound_date": res["bundle_batch"].inbound_date.isoformat() if res["bundle_batch"] else None,
        "idempotent_replay": res["idempotent_replay"],
    }


# --- Returns & Warranty ---
class ReturnCreateIn(BaseModel):
    channel: str
    sku_id: int
    location_id: int
    qty: int = 1
    external_order_id: str | None = None
    received_now: bool = False


class ReturnInspectIn(BaseModel):
    classification: str
    returned_component_qtys: dict[int, int] | None = None
    restock_location_id: int | None = None
    damaged_location_id: int | None = None
    evidence_storage_key: str | None = None
    notes: str | None = None


class WarrantyReqIn(BaseModel):
    sku_id: int
    customer_ref: str
    issue_description: str
    replacement_qty: int = 1
    serial_or_batch: str | None = None


@router.get("/returns")
def api_list_returns(user: User = Depends(require_action("inventory.view")), db: Session = Depends(get_db)):
    return db.query(ReturnCase).order_by(ReturnCase.id.desc()).all()


@router.post("/returns")
def api_create_return(payload: ReturnCreateIn, user: User = Depends(require_action("return.receive")), db: Session = Depends(get_db)):
    return create_return_case(db, user, **payload.model_dump())


@router.post("/returns/{return_id}/receive")
def api_receive_return(return_id: int, user: User = Depends(require_action("return.receive")), db: Session = Depends(get_db)):
    return mark_return_received(db, user, return_id)


@router.post("/returns/{return_id}/inspect")
def api_inspect_return(return_id: int, payload: ReturnInspectIn, user: User = Depends(require_action("return.inspect")), db: Session = Depends(get_db)):
    res = inspect_return_case(db, user, return_id=return_id, **payload.model_dump())
    return {
        "return_code": res["return_case"].return_code,
        "status": res["return_case"].status,
        "classification": res["return_case"].classification,
        "missing_components": res["missing_components"],
        "estimated_loss_inr": str(res["return_case"].estimated_loss_inr),
    }


@router.get("/returns/overdue")
def api_overdue_returns(user: User = Depends(require_action("inventory.view")), db: Session = Depends(get_db)):
    return get_overdue_return_inspections(db)


@router.get("/warranty/reserves")
def api_warranty_reserves(user: User = Depends(require_action("inventory.view")), db: Session = Depends(get_db)):
    return compute_warranty_reserve_status(db)


@router.get("/warranty/claims")
def api_list_warranty_claims(user: User = Depends(require_action("inventory.view")), db: Session = Depends(get_db)):
    return db.query(WarrantyClaim).order_by(WarrantyClaim.id.desc()).all()


@router.post("/warranty/claims/request")
def api_request_warranty(payload: WarrantyReqIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    res = create_warranty_replacement_request(db, user, **payload.model_dump())
    return {"claim_id": res["claim"].id, "claim_code": res["claim"].claim_code, "approval_request_id": res["approval_request"].id}


@router.post("/warranty/claims/{claim_id}/fulfill")
def api_fulfill_warranty(claim_id: int, warehouse_location_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return fulfill_warranty_claim(db, owner, claim_id, warehouse_location_id)


# --- Marketplaces ---
class MarketplaceImportIn(BaseModel):
    channel: str
    records: list[dict] | None = None
    csv_text: str | None = None
    cursor: str | None = None


@router.get("/marketplaces/status")
def api_marketplace_status(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return get_marketplace_statuses(db)


@router.post("/marketplaces/import-report")
def api_marketplace_import(payload: MarketplaceImportIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    recs = payload.records or ([] if not payload.csv_text else parse_csv_report(payload.csv_text))
    return import_marketplace_report(db, owner, channel=payload.channel, records=recs, cursor=payload.cursor)


@router.post("/marketplaces/reconcile")
def api_marketplace_reconcile(channel: str | None = None, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return run_marketplace_reconciliation(db, owner, channel=channel)


@router.get("/marketplaces/discrepancies")
def api_list_discrepancies(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return db.query(DiscrepancyCase).order_by(DiscrepancyCase.id.desc()).all()


# --- Logistics ---
class ShipmentIn(BaseModel):
    direction: str
    channel: str = "OFFLINE"
    carrier: str
    tracking_number: str | None = None
    origin_location_id: int | None = None
    destination_location_id: int | None = None
    freight_cost: Decimal = Decimal("0.00")
    packaging_cost: Decimal = Decimal("0.00")
    expected_delivery_at: datetime | None = None
    notes: str | None = None


@router.get("/logistics/shipments")
def api_list_shipments(user: User = Depends(require_action("inventory.view")), db: Session = Depends(get_db)):
    return db.query(Shipment).order_by(Shipment.id.desc()).all()


@router.post("/logistics/shipments")
def api_create_shipment(payload: ShipmentIn, user: User = Depends(require_action("shipment.update")), db: Session = Depends(get_db)):
    return create_shipment(db, user, **payload.model_dump())


@router.post("/logistics/shipments/{shipment_id}/status")
def api_update_shipment(shipment_id: int, status: str, notes: str | None = None, user: User = Depends(require_action("shipment.update")), db: Session = Depends(get_db)):
    return update_shipment_status(db, user, shipment_id, status, notes)


@router.get("/logistics/carriers")
def api_carrier_summary(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return carrier_performance_summary(db)

