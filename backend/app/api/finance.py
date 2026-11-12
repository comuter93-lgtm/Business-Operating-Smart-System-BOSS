from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import create_sqlite_backup, get_db
from app.core.permissions import record_audit, require_owner
from app.integrations.busy import BusyAccountingAdapter
from app.integrations.whatsapp_otp import WhatsAppOTPProvider
from app.models.auth import BusinessSettings, User
from app.models.finance import AIRecommendation, AutomationRun, PurchaseOrder, Supplier, SupplierInvoice, SupplierPayment
from app.services.command_centre_service import build_owner_command_centre
from app.services.finance_service import (
    compute_profitability_summary,
    compute_working_capital_metrics,
    export_busy_vouchers,
    record_sales_order,
)
from app.services.intelligence_service import generate_intelligence_recommendations
from app.services.procurement_service import (
    compute_procurement_recommendations,
    create_purchase_order_request,
    create_supplier,
    record_supplier_invoice,
    request_supplier_payment,
)
from app.workers.automation import run_automation_cycle

router = APIRouter(prefix="/api/v1", tags=["finance-procurement-intelligence"])


class SupplierIn(BaseModel):
    supplier_code: str
    name: str
    gstin: str | None = None
    state_code: str = "DL"
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    credit_days: int = 30
    lead_time_days: int = 7
    on_time_rate_pct: Decimal = Decimal("95.00")
    defect_rate_pct: Decimal = Decimal("1.00")


class PORequestIn(BaseModel):
    supplier_id: int
    lines: list[dict]
    freight_cost: Decimal = Decimal("0.00")
    idempotency_key: str


class SupplierInvoiceIn(BaseModel):
    supplier_id: int
    invoice_number: str
    taxable_amount: Decimal
    gst_rate: Decimal = Decimal("18.00")
    invoice_date: date | None = None
    po_id: int | None = None


class SupplierPaymentReqIn(BaseModel):
    invoice_id: int
    amount_inr: Decimal
    payment_mode: str = "NEFT"
    idempotency_key: str


class SalesOrderIn(BaseModel):
    order_code: str
    channel: str
    sku_id: int
    location_id: int
    qty: int
    selling_price_unit: Decimal
    customer_state: str
    marketplace_fee_inr: Decimal = Decimal("0.00")
    logistics_cost_inr: Decimal = Decimal("0.00")
    packaging_cost_inr: Decimal = Decimal("0.00")
    expected_return_warranty_cost_inr: Decimal = Decimal("0.00")
    settlement_days: int = 7
    external_order_id: str | None = None
    order_date: date | None = None
    deduct_stock: bool = True


class SettingsUpdateIn(BaseModel):
    target_selling_days: int | None = None
    red_age_days: int | None = None
    critical_age_days: int | None = None
    bundle_ageing_policy: str | None = None
    cash_available: Decimal | None = None
    cc_od_limit: Decimal | None = None
    cc_od_utilized: Decimal | None = None
    cc_od_annual_rate_pct: Decimal | None = None
    ai_mode: str | None = None


@router.get("/command-centre")
def api_command_centre(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return build_owner_command_centre(db)


# --- Procurement & Suppliers ---
@router.get("/procurement/suppliers")
def api_list_suppliers(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return db.query(Supplier).order_by(Supplier.id.asc()).all()


@router.post("/procurement/suppliers")
def api_create_supplier(payload: SupplierIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return create_supplier(db, owner, payload.model_dump())


@router.get("/procurement/purchase-orders")
def api_list_pos(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return db.query(PurchaseOrder).order_by(PurchaseOrder.id.desc()).all()


@router.post("/procurement/purchase-orders/request")
def api_request_po(payload: PORequestIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    res = create_purchase_order_request(db, owner, **payload.model_dump())
    return {
        "po_id": res["purchase_order"].id,
        "po_number": res["purchase_order"].po_number,
        "status": res["purchase_order"].status,
        "total_amount_inr": str(res["purchase_order"].total_amount_inr),
        "approval_request_id": res["approval_request"].id if res["approval_request"] else None,
        "idempotent_replay": res["idempotent_replay"],
    }


@router.get("/procurement/recommendations")
def api_procurement_recs(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return compute_procurement_recommendations(db)


@router.get("/procurement/invoices")
def api_list_invoices(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return db.query(SupplierInvoice).order_by(SupplierInvoice.due_date.asc()).all()


@router.post("/procurement/invoices")
def api_create_invoice(payload: SupplierInvoiceIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return record_supplier_invoice(db, owner, **payload.model_dump())


@router.get("/procurement/payments")
def api_list_payments(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return db.query(SupplierPayment).order_by(SupplierPayment.id.desc()).all()


@router.post("/procurement/payments/request")
def api_request_payment(payload: SupplierPaymentReqIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    res = request_supplier_payment(db, owner, **payload.model_dump())
    return {
        "payment_id": res["payment"].id,
        "payment_code": res["payment"].payment_code,
        "status": res["payment"].status,
        "approval_request_id": res["approval_request"].id if res["approval_request"] else None,
        "idempotent_replay": res["idempotent_replay"],
    }


# --- Finance, Sales & BUSY ---
@router.post("/finance/sales-orders")
def api_create_sales_order(payload: SalesOrderIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return record_sales_order(db, owner, **payload.model_dump())


@router.get("/finance/profitability")
def api_profitability(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return compute_profitability_summary(db)


@router.get("/finance/working-capital")
def api_working_capital(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return compute_working_capital_metrics(db)


@router.get("/finance/busy/status")
def api_busy_status(owner: User = Depends(require_owner)):
    return BusyAccountingAdapter().status()


@router.post("/finance/busy/export")
def api_busy_export(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return export_busy_vouchers(db, owner)


# --- AI Intelligence & Automation ---
@router.post("/intelligence/generate")
def api_generate_ai(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return generate_intelligence_recommendations(db)


@router.get("/intelligence/recommendations")
def api_list_ai_recs(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return db.query(AIRecommendation).order_by(AIRecommendation.created_at.desc()).all()


@router.post("/automation/run")
def api_run_automation(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return run_automation_cycle(db, trigger_source="OWNER_MANUAL")


@router.get("/automation/runs")
def api_list_automation_runs(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return db.query(AutomationRun).order_by(AutomationRun.id.desc()).limit(50).all()


# --- Settings & Backups ---
@router.get("/settings")
def api_get_settings(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    bs = db.query(BusinessSettings).first()
    return {
        "business": bs,
        "integrations": {
            "busy": BusyAccountingAdapter().status(),
            "whatsapp_otp": WhatsAppOTPProvider().status(),
        },
    }


@router.put("/settings")
def api_update_settings(payload: SettingsUpdateIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    bs = db.query(BusinessSettings).first()
    if not bs:
        raise HTTPException(status_code=404, detail="Business settings not initialized")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(bs, k, v)
    db.commit()
    db.refresh(bs)
    record_audit(db, actor=owner, action="settings.update", resource_type="business_settings", resource_id=str(bs.id), outcome="SUCCESS")
    return bs


@router.post("/system/backup")
def api_create_backup(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    path = create_sqlite_backup()
    record_audit(db, actor=owner, action="system.backup", resource_type="database", resource_id=path.name, outcome="SUCCESS")
    return {"backup_file": path.name, "status": "CREATED"}

