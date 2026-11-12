from datetime import date, timedelta
from decimal import Decimal
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import record_audit
from app.integrations.busy import BusyAccountingAdapter
from app.models.auth import BusinessSettings, User
from app.models.finance import BusySyncLog, SalesOrder, SupplierInvoice
from app.models.inventory import InventoryBatch, SKU
from app.models.operations import DiscrepancyCase
from app.services.inventory_service import _money, compute_inventory_ageing_report, dispatch_stock


def calculate_gst_split(taxable_amount: Decimal, gst_rate: Decimal, seller_state: str, party_state: str) -> dict:
    total_gst = _money(taxable_amount * (gst_rate / Decimal("100")))
    if seller_state.strip().upper() == party_state.strip().upper():
        cgst = _money(total_gst / Decimal("2"))
        sgst = _money(total_gst - cgst)
        return {"cgst": cgst, "sgst": sgst, "igst": Decimal("0.00"), "total_gst": total_gst, "tax_type": "INTRA_STATE"}
    return {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": total_gst, "total_gst": total_gst, "tax_type": "INTER_STATE"}


def record_sales_order(
    db: Session,
    actor: User,
    *,
    order_code: str,
    channel: str,
    sku_id: int,
    location_id: int,
    qty: int,
    selling_price_unit: Decimal,
    customer_state: str,
    marketplace_fee_inr: Decimal = Decimal("0.00"),
    logistics_cost_inr: Decimal = Decimal("0.00"),
    packaging_cost_inr: Decimal = Decimal("0.00"),
    expected_return_warranty_cost_inr: Decimal = Decimal("0.00"),
    settlement_days: int = 7,
    external_order_id: str | None = None,
    order_date: date | None = None,
    deduct_stock: bool = True,
) -> SalesOrder:
    existing = db.query(SalesOrder).filter(SalesOrder.order_code == order_code).first()
    if existing:
        return existing

    sku = db.query(SKU).filter(SKU.id == sku_id).first()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    bs = db.query(BusinessSettings).first()
    home_state = bs.home_state if bs else "DL"
    actual_order_date = order_date or date.today()

    if deduct_stock:
        disp = dispatch_stock(
            db,
            actor,
            sku_id=sku_id,
            location_id=location_id,
            qty=qty,
            reference_type="SALES_ORDER",
            reference_id=order_code,
            idempotency_key=f"SO-DISP-{order_code}",
            dispatch_date=actual_order_date,
        )
        cogs = disp["cogs_inr"]
    else:
        cogs = _money(Decimal(qty) * sku.purchase_cost)

    unit_ex_gst = _money(selling_price_unit)
    taxable_rev = _money(unit_ex_gst * Decimal(qty))
    gst = calculate_gst_split(taxable_rev, sku.gst_rate, home_state, customer_state)

    m_fee = _money(marketplace_fee_inr)
    log_cost = _money(logistics_cost_inr)
    pkg_cost = _money(packaging_cost_inr)
    ret_war_cost = _money(expected_return_warranty_cost_inr)

    gross_profit = _money(taxable_rev - cogs)
    contribution_profit = _money(gross_profit - m_fee - log_cost - pkg_cost - ret_war_cost)

    # Allocate daily borrowing/overhead proxy if configured, else equal to contribution minus 0
    financing_alloc = Decimal("0.00")
    if bs and bs.cc_od_utilized > Decimal("0.00"):
        daily_rate = (bs.cc_od_annual_rate_pct / Decimal("100")) / Decimal("365")
        financing_alloc = _money(cogs * daily_rate * Decimal(max(1, settlement_days)))
    net_profit = _money(contribution_profit - financing_alloc)

    so = SalesOrder(
        order_code=order_code,
        channel=channel,
        external_order_id=external_order_id,
        customer_state=customer_state.upper(),
        order_date=actual_order_date,
        status="DISPATCHED",
        sku_id=sku_id,
        qty=qty,
        selling_price_unit=unit_ex_gst,
        gst_rate=sku.gst_rate,
        taxable_revenue=taxable_rev,
        cgst_amount=gst["cgst"],
        sgst_amount=gst["sgst"],
        igst_amount=gst["igst"],
        cogs_inr=cogs,
        marketplace_fee_inr=m_fee,
        logistics_cost_inr=log_cost,
        packaging_cost_inr=pkg_cost,
        expected_return_warranty_cost_inr=ret_war_cost,
        gross_profit_inr=gross_profit,
        contribution_profit_inr=contribution_profit,
        net_profit_inr=net_profit,
        settlement_days=settlement_days,
    )
    db.add(so)
    db.commit()
    db.refresh(so)
    record_audit(db, actor=actor, action="sales_order.create", resource_type="sales_order", resource_id=str(so.id), outcome="SUCCESS")
    return so


def compute_profitability_summary(db: Session) -> dict:
    orders = db.query(SalesOrder, SKU).join(SKU, SalesOrder.sku_id == SKU.id).all()
    total_rev = Decimal("0.00")
    total_cogs = Decimal("0.00")
    total_gross = Decimal("0.00")
    total_contrib = Decimal("0.00")
    total_net = Decimal("0.00")
    output_gst = Decimal("0.00")

    by_role: dict[str, dict] = {}
    by_channel: dict[str, dict] = {}
    by_sku: dict[int, dict] = {}

    for o, sku in orders:
        total_rev += o.taxable_revenue
        total_cogs += o.cogs_inr
        total_gross += o.gross_profit_inr
        total_contrib += o.contribution_profit_inr
        total_net += o.net_profit_inr
        output_gst += o.cgst_amount + o.sgst_amount + o.igst_amount

        role_row = by_role.setdefault(sku.strategic_role, {"units": 0, "revenue_inr": Decimal("0.00"), "contribution_profit_inr": Decimal("0.00")})
        role_row["units"] += o.qty
        role_row["revenue_inr"] += o.taxable_revenue
        role_row["contribution_profit_inr"] += o.contribution_profit_inr

        ch_row = by_channel.setdefault(o.channel, {"orders": 0, "revenue_inr": Decimal("0.00"), "contribution_profit_inr": Decimal("0.00")})
        ch_row["orders"] += 1
        ch_row["revenue_inr"] += o.taxable_revenue
        ch_row["contribution_profit_inr"] += o.contribution_profit_inr

        s_row = by_sku.setdefault(
            sku.id,
            {
                "sku_id": sku.id,
                "sku_code": sku.sku_code,
                "name": sku.name,
                "strategic_role": sku.strategic_role,
                "units": 0,
                "revenue_inr": Decimal("0.00"),
                "contribution_profit_inr": Decimal("0.00"),
                "margin_pct": 0.0,
            },
        )
        s_row["units"] += o.qty
        s_row["revenue_inr"] += o.taxable_revenue
        s_row["contribution_profit_inr"] += o.contribution_profit_inr

    # Input Tax Credit (ITC) from supplier invoices
    invoices = db.query(SupplierInvoice).all()
    input_gst_credit = sum((inv.cgst_amount + inv.sgst_amount + inv.igst_amount) for inv in invoices)
    net_gst_payable = _money(output_gst - input_gst_credit)

    s_row_list = list(by_sku.values())
    for s in s_row_list:
        s["margin_pct"] = float((s["contribution_profit_inr"] / s["revenue_inr"]) * Decimal("100")) if s["revenue_inr"] > 0 else 0.0
        s["revenue_inr"] = str(_money(s["revenue_inr"]))
        s["contribution_profit_inr"] = str(_money(s["contribution_profit_inr"]))

    return {
        "order_count": len(orders),
        "revenue_ex_gst_inr": str(_money(total_rev)),
        "cogs_inr": str(_money(total_cogs)),
        "gross_profit_inr": str(_money(total_gross)),
        "contribution_profit_inr": str(_money(total_contrib)),
        "net_profit_inr": str(_money(total_net)),
        "gst": {
            "output_gst_inr": str(_money(output_gst)),
            "input_gst_credit_inr": str(_money(input_gst_credit)),
            "net_gst_payable_inr": str(net_gst_payable),
        },
        "by_strategic_role": {
            k: {"units": v["units"], "revenue_inr": str(_money(v["revenue_inr"])), "contribution_profit_inr": str(_money(v["contribution_profit_inr"]))}
            for k, v in by_role.items()
        },
        "by_channel": {
            k: {"orders": v["orders"], "revenue_inr": str(_money(v["revenue_inr"])), "contribution_profit_inr": str(_money(v["contribution_profit_inr"]))}
            for k, v in by_channel.items()
        },
        "sku_profitability": s_row_list,
    }


def compute_working_capital_metrics(db: Session) -> dict:
    bs = db.query(BusinessSettings).first()
    ageing = compute_inventory_ageing_report(db)
    batches = db.query(InventoryBatch).filter(InventoryBatch.remaining_qty > 0).all()
    inv_value = sum((Decimal(b.remaining_qty) * b.unit_cost) for b in batches)

    invoices = db.query(SupplierInvoice).filter(SupplierInvoice.status != "PAID").all()
    payables = sum((inv.total_amount - inv.paid_amount) for inv in invoices)

    orders = db.query(SalesOrder).all()
    total_cogs = sum(o.cogs_inr for o in orders)
    total_rev = sum(o.taxable_revenue for o in orders)
    avg_settlement_days = (sum(o.settlement_days for o in orders) / len(orders)) if orders else 7.0

    # Annualized DIO & DPO using 30-day window fallback when order volume is nascent
    daily_cogs = (total_cogs / Decimal("30")) if total_cogs > 0 else Decimal("1.00")
    dio = float(min(Decimal("365"), inv_value / daily_cogs)) if inv_value > 0 else 0.0
    dso = round(avg_settlement_days, 1)
    dpo = float(sum(inv.credit_days for inv in invoices) / len(invoices)) if invoices else 30.0
    ccc = round(dio + dso - dpo, 1)

    open_claims = db.query(DiscrepancyCase).filter(DiscrepancyCase.status.in_(["OPEN", "SUBMITTED"])).all()
    receivables_claims = sum(c.estimated_impact_inr for c in open_claims)

    cc_utilized = bs.cc_od_utilized if bs else Decimal("0.00")
    cc_rate = bs.cc_od_annual_rate_pct if bs else Decimal("10.50")
    annual_interest = _money(cc_utilized * (cc_rate / Decimal("100")))

    return {
        "cash_available_inr": str(_money(bs.cash_available if bs else Decimal("0.00"))),
        "inventory_valuation_inr": str(_money(inv_value)),
        "red_blocked_capital_inr": ageing["summary"]["RED"]["value_inr"],
        "critical_blocked_capital_inr": ageing["summary"]["CRITICAL"]["value_inr"],
        "supplier_payables_inr": str(_money(payables)),
        "marketplace_claim_receivables_inr": str(_money(receivables_claims)),
        "cc_od_limit_inr": str(_money(bs.cc_od_limit if bs else Decimal("0.00"))),
        "cc_od_utilized_inr": str(_money(cc_utilized)),
        "estimated_annual_interest_inr": str(annual_interest),
        "cash_conversion_cycle": {"dio_days": round(dio, 1), "dso_days": dso, "dpo_days": round(dpo, 1), "ccc_days": ccc},
    }


def export_busy_vouchers(db: Session, owner: User) -> dict:
    adapter = BusyAccountingAdapter()
    orders = db.query(SalesOrder, SKU).join(SKU, SalesOrder.sku_id == SKU.id).filter(SalesOrder.busy_voucher_ref.is_(None)).all()
    payload = []
    export_ref = f"BUSY-EXP-{uuid.uuid4().hex[:6].upper()}"
    for o, sku in orders:
        payload.append(
            {
                "order_code": o.order_code,
                "order_date": o.order_date.isoformat(),
                "channel": o.channel,
                "customer_state": o.customer_state,
                "sku_code": sku.sku_code,
                "qty": o.qty,
                "taxable_revenue": str(o.taxable_revenue),
                "cgst_amount": str(o.cgst_amount),
                "sgst_amount": str(o.sgst_amount),
                "igst_amount": str(o.igst_amount),
            }
        )
        o.busy_voucher_ref = export_ref

    xml_str = adapter.export_sales_vouchers_xml(payload)
    log = BusySyncLog(
        direction="EXPORT_VOUCHER",
        data_source="EXPORT_BRIDGE",
        record_count=len(payload),
        status="SUCCESS",
        payload_summary_json={"export_ref": export_ref, "voucher_count": len(payload)},
    )
    db.add(log)
    db.commit()
    record_audit(db, actor=owner, action="busy.export_vouchers", resource_type="busy_sync", resource_id=export_ref, outcome="SUCCESS")
    return {"export_ref": export_ref, "data_source": "EXPORT_BRIDGE", "record_count": len(payload), "xml": xml_str, "adapter_status": adapter.status()}
