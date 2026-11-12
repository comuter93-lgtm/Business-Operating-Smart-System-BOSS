from datetime import date
from decimal import Decimal
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import record_audit
from app.core.security import utcnow
from app.models.auth import User
from app.models.finance import PurchaseOrder, SupplierInvoice, SupplierPayment
from app.models.inventory import ApprovalRequest, BOM, InventoryBatch, InventoryLedger, Location, SKU
from app.models.operations import WarrantyClaim
from app.services.inventory_service import dispatch_stock, receive_stock


def review_approval_request(
    db: Session,
    owner: User,
    *,
    approval_id: int,
    decision: str,  # APPROVED | REJECTED
    review_notes: str | None = None,
) -> ApprovalRequest:
    if owner.role != "OWNER":
        raise HTTPException(status_code=403, detail="Only the verified Owner may approve or reject requests")
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if req.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Approval request already {req.status}")
    if decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(status_code=400, detail="Decision must be APPROVED or REJECTED")

    req.status = decision
    req.reviewed_by_id = owner.id
    req.review_notes = review_notes
    req.reviewed_at = utcnow()

    action = req.proposed_action_json or {}
    if decision == "APPROVED":
        if req.request_type == "BOM_CHANGE":
            bom_id = int(action["bom_id"])
            bom = db.query(BOM).filter(BOM.id == bom_id).first()
            if bom:
                db.query(BOM).filter(BOM.bundle_sku_id == bom.bundle_sku_id, BOM.status == "ACTIVE").update({"status": "ARCHIVED"})
                bom.status = "ACTIVE"
                bom.approved_by_id = owner.id

        elif req.request_type == "INVENTORY_ADJUSTMENT":
            sku_id = int(action["sku_id"])
            location_id = int(action["location_id"])
            qty_delta = int(action["qty_delta"])
            sku = db.query(SKU).filter(SKU.id == sku_id).first()
            if qty_delta > 0 and sku:
                receive_stock(
                    db,
                    owner,
                    sku_id=sku_id,
                    location_id=location_id,
                    qty=qty_delta,
                    unit_cost=sku.purchase_cost,
                    source_type="ADJUSTMENT",
                    source_ref_id=f"APR-{req.id}",
                    idempotency_key=f"APR-ADJ-{req.id}",
                    evidence_storage_key=action.get("evidence_storage_key"),
                    notes=req.problem_summary,
                )
            elif qty_delta < 0:
                dispatch_stock(
                    db,
                    owner,
                    sku_id=sku_id,
                    location_id=location_id,
                    qty=abs(qty_delta),
                    reference_type="ADJUSTMENT",
                    reference_id=f"APR-{req.id}",
                    idempotency_key=f"APR-ADJ-{req.id}",
                    tx_type="ADJUSTMENT",
                    notes=req.problem_summary,
                )

        elif req.request_type == "WARRANTY_REPLACEMENT":
            claim_id = int(action["claim_id"])
            claim = db.query(WarrantyClaim).filter(WarrantyClaim.id == claim_id).first()
            if claim:
                claim.status = "APPROVED"

        elif req.request_type == "PURCHASE_ORDER":
            po_id = int(action["po_id"])
            po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
            if po:
                po.status = "APPROVED"

        elif req.request_type == "SUPPLIER_PAYMENT":
            pay_id = int(action["payment_id"])
            payment = db.query(SupplierPayment).filter(SupplierPayment.id == pay_id).first()
            if payment and payment.status != "PAID":
                inv = db.query(SupplierInvoice).filter(SupplierInvoice.id == payment.invoice_id).first()
                if inv:
                    new_paid = inv.paid_amount + payment.amount_inr
                    if new_paid > inv.total_amount:
                        raise HTTPException(status_code=409, detail="Payment exceeds supplier invoice total")
                    inv.paid_amount = new_paid
                    inv.status = "PAID" if new_paid == inv.total_amount else "PARTIAL"
                payment.status = "PAID"
                payment.paid_at = utcnow()

    else:  # REJECTED
        if req.request_type == "WARRANTY_REPLACEMENT" and "claim_id" in action:
            claim = db.query(WarrantyClaim).filter(WarrantyClaim.id == int(action["claim_id"])).first()
            if claim:
                claim.status = "REJECTED"
        elif req.request_type == "PURCHASE_ORDER" and "po_id" in action:
            po = db.query(PurchaseOrder).filter(PurchaseOrder.id == int(action["po_id"])).first()
            if po:
                po.status = "CANCELLED"
        elif req.request_type == "SUPPLIER_PAYMENT" and "payment_id" in action:
            payment = db.query(SupplierPayment).filter(SupplierPayment.id == int(action["payment_id"])).first()
            if payment:
                payment.status = "REJECTED"

    db.commit()
    db.refresh(req)
    record_audit(
        db,
        actor=owner,
        action=f"approval.{decision.lower()}",
        resource_type="approval_request",
        resource_id=str(req.id),
        outcome="SUCCESS",
        details={"request_type": req.request_type, "target": f"{req.target_entity_type}:{req.target_entity_id}"},
    )
    return req

