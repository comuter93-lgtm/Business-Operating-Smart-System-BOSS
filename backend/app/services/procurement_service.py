from datetime import date, timedelta
from decimal import Decimal
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import record_audit
from app.models.auth import BusinessSettings, User
from app.models.finance import PurchaseOrder, PurchaseOrderLine, SalesOrder, Supplier, SupplierInvoice, SupplierPayment
from app.models.inventory import ApprovalRequest, Location, SKU
from app.services.finance_service import calculate_gst_split
from app.services.inventory_service import _money, compute_stock_availability


def create_supplier(db: Session, owner: User, data: dict) -> Supplier:
    code = data["supplier_code"].strip().upper()
    if db.query(Supplier).filter(Supplier.supplier_code == code).first():
        raise HTTPException(status_code=409, detail=f"Supplier {code} already exists")
    sup = Supplier(
        supplier_code=code,
        name=data["name"].strip(),
        gstin=data.get("gstin"),
        state_code=data.get("state_code", "DL").upper(),
        contact_name=data.get("contact_name"),
        phone=data.get("phone"),
        email=data.get("email"),
        credit_days=int(data.get("credit_days", 30)),
        lead_time_days=int(data.get("lead_time_days", 7)),
        on_time_rate_pct=_money(data.get("on_time_rate_pct", 95)),
        defect_rate_pct=_money(data.get("defect_rate_pct", 1)),
    )
    db.add(sup)
    db.commit()
    db.refresh(sup)
    record_audit(db, actor=owner, action="supplier.create", resource_type="supplier", resource_id=str(sup.id), outcome="SUCCESS")
    return sup


def create_purchase_order_request(
    db: Session,
    actor: User,
    *,
    supplier_id: int,
    lines: list[dict],
    freight_cost: Decimal = Decimal("0.00"),
    idempotency_key: str,
) -> dict:
    existing = db.query(PurchaseOrder).filter(PurchaseOrder.idempotency_key == idempotency_key).first()
    if existing:
        app = db.query(ApprovalRequest).filter(ApprovalRequest.id == existing.approval_id).first()
        return {"purchase_order": existing, "approval_request": app, "idempotent_replay": True}

    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if not lines:
        raise HTTPException(status_code=400, detail="PO must contain at least one line")

    po = PurchaseOrder(
        po_number=f"PO-{uuid.uuid4().hex[:8].upper()}",
        supplier_id=supplier.id,
        status="PENDING_APPROVAL",
        freight_cost=_money(freight_cost),
        idempotency_key=idempotency_key,
        created_by_id=actor.id,
    )
    db.add(po)
    db.flush()

    total_taxable = Decimal("0.00")
    total_gst = Decimal("0.00")
    for l in lines:
        sku = db.query(SKU).filter(SKU.id == int(l["sku_id"])).first()
        if not sku:
            raise HTTPException(status_code=404, detail=f"SKU {l['sku_id']} not found")
        qty = int(l["qty_ordered"])
        unit_cost = _money(l.get("unit_cost", sku.purchase_cost))
        line_taxable = _money(Decimal(qty) * unit_cost)
        gst_amt = _money(line_taxable * (sku.gst_rate / Decimal("100")))
        line_total = _money(line_taxable + gst_amt)
        total_taxable += line_taxable
        total_gst += gst_amt
        db.add(
            PurchaseOrderLine(
                po_id=po.id,
                sku_id=sku.id,
                qty_ordered=qty,
                unit_cost=unit_cost,
                gst_rate=sku.gst_rate,
                gst_amount=gst_amt,
                line_total=line_total,
            )
        )

    po.total_taxable_inr = _money(total_taxable)
    po.total_gst_inr = _money(total_gst)
    po.total_amount_inr = _money(total_taxable + total_gst + po.freight_cost)

    approval = ApprovalRequest(
        request_type="PURCHASE_ORDER",
        status="PENDING",
        title=f"Approve PO {po.po_number} to {supplier.name} (₹{po.total_amount_inr})",
        problem_summary=f"Procurement order of {len(lines)} SKU(s) with {supplier.credit_days}-day credit and {supplier.lead_time_days}-day lead time.",
        evidence_json={"po_id": po.id, "supplier_id": supplier.id, "lines": lines},
        financial_impact_inr=po.total_amount_inr,
        proposed_action_json={"po_id": po.id},
        responsible_person=actor.full_name,
        verification_method="Owner verifies demand, ROWC, and cash availability before PO release",
        target_entity_type="purchase_order",
        target_entity_id=str(po.id),
        requested_by_id=actor.id,
    )
    db.add(approval)
    db.flush()
    po.approval_id = approval.id
    db.commit()
    db.refresh(po)
    db.refresh(approval)
    return {"purchase_order": po, "approval_request": approval, "idempotent_replay": False}


def record_supplier_invoice(
    db: Session,
    actor: User,
    *,
    supplier_id: int,
    invoice_number: str,
    taxable_amount: Decimal,
    gst_rate: Decimal = Decimal("18.00"),
    invoice_date: date | None = None,
    po_id: int | None = None,
) -> SupplierInvoice:
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    bs = db.query(BusinessSettings).first()
    home_state = bs.home_state if bs else "DL"
    target_pct = bs.supplier_payment_target_pct if bs else 75

    inv_date = invoice_date or date.today()
    target_days = int(supplier.credit_days * target_pct // 100)
    target_75_date = inv_date + timedelta(days=target_days)
    due_date = inv_date + timedelta(days=supplier.credit_days)

    taxable = _money(taxable_amount)
    gst = calculate_gst_split(taxable, gst_rate, home_state, supplier.state_code)
    total = _money(taxable + gst["total_gst"])

    inv = SupplierInvoice(
        invoice_number=invoice_number.strip(),
        supplier_id=supplier_id,
        po_id=po_id,
        invoice_date=inv_date,
        credit_days=supplier.credit_days,
        target_75_pay_date=target_75_date,
        due_date=due_date,
        taxable_amount=taxable,
        cgst_amount=gst["cgst"],
        sgst_amount=gst["sgst"],
        igst_amount=gst["igst"],
        total_amount=total,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    record_audit(db, actor=actor, action="supplier_invoice.create", resource_type="supplier_invoice", resource_id=str(inv.id), outcome="SUCCESS")
    return inv


def request_supplier_payment(
    db: Session,
    actor: User,
    *,
    invoice_id: int,
    amount_inr: Decimal,
    payment_mode: str = "NEFT",
    idempotency_key: str,
) -> dict:
    existing = db.query(SupplierPayment).filter(SupplierPayment.idempotency_key == idempotency_key).first()
    if existing:
        app = db.query(ApprovalRequest).filter(ApprovalRequest.id == existing.approval_id).first()
        return {"payment": existing, "approval_request": app, "idempotent_replay": True}

    inv = db.query(SupplierInvoice).filter(SupplierInvoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Supplier invoice not found")
    amt = _money(amount_inr)
    outstanding = _money(inv.total_amount - inv.paid_amount)
    if amt <= Decimal("0.00") or amt > outstanding:
        raise HTTPException(status_code=409, detail=f"Invalid payment amount ₹{amt}; outstanding balance is ₹{outstanding}")

    # Prevent duplicate pending payment for the same invoice
    pending_same = (
        db.query(SupplierPayment)
        .filter(SupplierPayment.invoice_id == invoice_id, SupplierPayment.status == "PENDING_APPROVAL")
        .first()
    )
    if pending_same:
        raise HTTPException(status_code=409, detail=f"Pending payment {pending_same.payment_code} already exists for this invoice")

    supplier = db.query(Supplier).filter(Supplier.id == inv.supplier_id).first()
    pay = SupplierPayment(
        payment_code=f"PAY-{uuid.uuid4().hex[:8].upper()}",
        supplier_id=inv.supplier_id,
        invoice_id=inv.id,
        amount_inr=amt,
        payment_mode=payment_mode,
        status="PENDING_APPROVAL",
        idempotency_key=idempotency_key,
        created_by_id=actor.id,
    )
    db.add(pay)
    db.flush()

    approval = ApprovalRequest(
        request_type="SUPPLIER_PAYMENT",
        status="PENDING",
        title=f"Approve Payment ₹{amt} to {supplier.name if supplier else inv.supplier_id} (Inv {inv.invoice_number})",
        problem_summary=f"75% credit target date: {inv.target_75_pay_date.isoformat()}, contractual due date: {inv.due_date.isoformat()}",
        evidence_json={"payment_id": pay.id, "invoice_id": inv.id, "outstanding": str(outstanding)},
        financial_impact_inr=amt,
        proposed_action_json={"payment_id": pay.id},
        responsible_person=actor.full_name,
        verification_method="Owner verifies invoice receipt & bank release",
        target_entity_type="supplier_payment",
        target_entity_id=str(pay.id),
        requested_by_id=actor.id,
    )
    db.add(approval)
    db.flush()
    pay.approval_id = approval.id
    db.commit()
    db.refresh(pay)
    db.refresh(approval)
    return {"payment": pay, "approval_request": approval, "idempotent_replay": False}


def compute_procurement_recommendations(db: Session) -> list[dict]:
    """Recommend replenishment ranked by ROWC, factoring FC receiving delays & supplier credit."""
    bs = db.query(BusinessSettings).first()
    annual_rate = (bs.cc_od_annual_rate_pct if bs else Decimal("10.50")) / Decimal("100")

    fc_locs = db.query(Location).filter(Location.location_type.in_(["AMAZON_FC", "FLIPKART_FC"])).all()
    max_fc_delay = max((l.fc_receiving_delay_days for l in fc_locs), default=0)

    avail_map = {r["sku_id"]: r for r in compute_stock_availability(db)}
    skus = db.query(SKU).filter(SKU.is_active.is_(True)).all()
    recs = []

    for sku in skus:
        stock = avail_map.get(sku.id, {"available_qty": 0, "in_transit_qty": 0})
        avail_plus_transit = stock["available_qty"] + stock["in_transit_qty"]
        supplier = db.query(Supplier).filter(Supplier.id == sku.primary_supplier_id).first() if sku.primary_supplier_id else None
        credit_days = supplier.credit_days if supplier else 30
        eff_lead_days = (supplier.lead_time_days if supplier else sku.lead_time_days) + max_fc_delay

        orders = db.query(SalesOrder).filter(SalesOrder.sku_id == sku.id).all()
        total_sold = sum(o.qty for o in orders)
        daily_vel = max(Decimal("0.3"), Decimal(total_sold) / Decimal("30"))
        target_cover_qty = int(daily_vel * Decimal(eff_lead_days + 21))  # lead time + 21d cycle
        suggested_qty = max(0, target_cover_qty - avail_plus_transit)

        if avail_plus_transit <= sku.reorder_point or suggested_qty > 0:
            order_qty = max(suggested_qty, sku.reorder_point)
            capital_req = _money(Decimal(order_qty) * sku.purchase_cost)
            unit_margin = max(Decimal("1.00"), sku.selling_price - sku.purchase_cost)
            expected_contrib = _money(Decimal(order_qty) * unit_margin * Decimal("0.80"))
            cycle_days = max(5, 25 + 7 - credit_days)
            financing_cost = _money(capital_req * annual_rate * (Decimal(cycle_days) / Decimal("365")))
            net_return = _money(expected_contrib - financing_cost)
            annualized_rowc_pct = float((net_return / capital_req) * (Decimal("365") / Decimal(cycle_days)) * Decimal("100")) if capital_req > 0 else 0.0

            recs.append(
                {
                    "sku_id": sku.id,
                    "sku_code": sku.sku_code,
                    "sku_name": sku.name,
                    "strategic_role": sku.strategic_role,
                    "available_qty": stock["available_qty"],
                    "in_transit_qty": stock["in_transit_qty"],
                    "reorder_point": sku.reorder_point,
                    "effective_lead_days_incl_fc_delay": eff_lead_days,
                    "recommended_order_qty": order_qty,
                    "supplier_name": supplier.name if supplier else "Unassigned",
                    "supplier_credit_days": credit_days,
                    "capital_required_inr": str(capital_req),
                    "expected_contribution_inr": str(expected_contrib),
                    "annualized_rowc_pct": round(annualized_rowc_pct, 1),
                    "approval_required": True,
                }
            )

    return sorted(recs, key=lambda x: x["annualized_rowc_pct"], reverse=True)

