from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.core.database import create_sqlite_backup, restore_sqlite_backup
from tests.test_phase1_security import bootstrap_and_login_owner


def test_marketplaces_procurement_finance_busy_ai_automation_and_backup(client, isolated_env):
    owner = bootstrap_and_login_owner(client)
    oh = owner["headers"]

    # 1. Settings & Locations
    client.put("/api/v1/settings", headers=oh, json={"cash_available": "250000.00", "cc_od_limit": "500000.00", "cc_od_utilized": "100000.00", "cc_od_annual_rate_pct": "10.00"})
    wh = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "WH-DEL", "name": "Delhi Main WH", "location_type": "WAREHOUSE"}).json()
    amz_fc = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "AMZ-DEL4", "name": "Amazon DEL4", "location_type": "AMAZON_FC", "fc_receiving_delay_days": 5}).json()

    # 2. Supplier & SKUs (High-Vol/Low-Margin vs Low-Vol/High-Margin)
    sup = client.post(
        "/api/v1/procurement/suppliers",
        headers=oh,
        json={"supplier_code": "SUP-KIR", "name": "Kirloskar Pump Distributors", "state_code": "MH", "credit_days": 40, "lead_time_days": 6},
    ).json()

    sku_hv = client.post(
        "/api/v1/inventory/skus",
        headers=oh,
        json={
            "sku_code": "PUMP-VOL",
            "name": "0.5HP Domestic Booster Pump",
            "category": "WATER_PUMP",
            "item_type": "FINISHED_GOOD",
            "purchase_cost": "1900.00",
            "selling_price": "2250.00",
            "mrp": "2800.00",
            "gst_rate": "18.00",
            "primary_supplier_id": sup["id"],
            "strategic_role": "HIGH_VOL_LOW_MARGIN",
            "amazon_sku": "AMZ-VOL-05",
        },
    ).json()
    sku_hm = client.post(
        "/api/v1/inventory/skus",
        headers=oh,
        json={
            "sku_code": "PUMP-PRO",
            "name": "3HP Industrial Borewell Pump",
            "category": "WATER_PUMP",
            "item_type": "FINISHED_GOOD",
            "purchase_cost": "11000.00",
            "selling_price": "16500.00",
            "mrp": "19500.00",
            "gst_rate": "18.00",
            "primary_supplier_id": sup["id"],
            "strategic_role": "LOW_VOL_HIGH_MARGIN",
            "flipkart_sku": "FK-PRO-3HP",
        },
    ).json()

    # Receive opening stock (one 48d critical batch to trigger AI ageing rec)
    client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": sku_hv["id"], "location_id": wh["id"], "qty": 30, "unit_cost": "1900", "inbound_date": (date.today() - timedelta(days=3)).isoformat(), "idempotency_key": "OP-HV"})
    client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": sku_hm["id"], "location_id": wh["id"], "qty": 4, "unit_cost": "11000", "inbound_date": (date.today() - timedelta(days=48)).isoformat(), "idempotency_key": "OP-HM"})
    client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": sku_hv["id"], "location_id": amz_fc["id"], "qty": 10, "unit_cost": "1900", "inbound_date": (date.today() - timedelta(days=5)).isoformat(), "idempotency_key": "OP-AMZ-FC"})

    # 3. Record Intra-State (DL -> DL: CGST+SGST) & Inter-State (DL -> MH: IGST) Sales Orders
    so1 = client.post(
        "/api/v1/finance/sales-orders",
        headers=oh,
        json={
            "order_code": "SO-AMZ-101",
            "channel": "AMAZON",
            "sku_id": sku_hv["id"],
            "location_id": wh["id"],
            "qty": 10,
            "selling_price_unit": "2250.00",
            "customer_state": "DL",
            "marketplace_fee_inr": "2000.00",
            "logistics_cost_inr": "450.00",
            "packaging_cost_inr": "150.00",
            "expected_return_warranty_cost_inr": "100.00",
            "settlement_days": 7,
        },
    ).json()
    # Taxable = 22500, 18% GST = 4050 -> CGST 2025 + SGST 2025, IGST 0
    assert Decimal(str(so1["cgst_amount"])) == Decimal("2025.00")
    assert Decimal(str(so1["sgst_amount"])) == Decimal("2025.00")
    assert Decimal(str(so1["igst_amount"])) == Decimal("0.00")
    assert Decimal(str(so1["gross_profit_inr"])) == Decimal("3500.00")  # 22500 - 19000
    assert Decimal(str(so1["contribution_profit_inr"])) == Decimal("800.00")  # 3500 - 2000 - 450 - 150 - 100

    so2 = client.post(
        "/api/v1/finance/sales-orders",
        headers=oh,
        json={
            "order_code": "SO-FK-102",
            "channel": "FLIPKART",
            "sku_id": sku_hm["id"],
            "location_id": wh["id"],
            "qty": 2,
            "selling_price_unit": "16500.00",
            "customer_state": "MH",
            "marketplace_fee_inr": "2500.00",
            "logistics_cost_inr": "600.00",
            "packaging_cost_inr": "200.00",
            "settlement_days": 10,
        },
    ).json()
    # Taxable = 33000, 18% IGST = 5940
    assert Decimal(str(so2["igst_amount"])) == Decimal("5940.00")
    assert Decimal(str(so2["cgst_amount"])) == Decimal("0.00")
    assert Decimal(str(so2["contribution_profit_inr"])) == Decimal("7700.00")  # (33000 - 22000) - 3300

    prof = client.get("/api/v1/finance/profitability", headers=oh).json()
    assert "HIGH_VOL_LOW_MARGIN" in prof["by_strategic_role"]
    assert "LOW_VOL_HIGH_MARGIN" in prof["by_strategic_role"]
    assert prof["contribution_profit_inr"] == "8500.00"

    # 4. Marketplace Status (Honest NOT_CONFIGURED) + Controlled Report Import + Interrupted Cursor + Discrepancy Detection
    m_stat = client.get("/api/v1/marketplaces/status", headers=oh).json()
    assert all(m["connection_status"] == "NOT_CONFIGURED" for m in m_stat)

    imp = client.post(
        "/api/v1/marketplaces/import-report",
        headers=oh,
        json={
            "channel": "AMAZON_IN",
            "cursor": "page_2_token",
            "records": [
                {"external_tx_id": "AMZ-TX-1", "tx_type": "SETTLEMENT", "external_sku": "AMZ-VOL-05", "qty": 1, "gross_amount": "2250", "marketplace_fee": "250", "gst_on_fee": "45", "net_settlement": "1800"},  # variance 155!
                {"external_tx_id": "AMZ-TX-2", "tx_type": "FC_INVENTORY", "external_sku": "AMZ-VOL-05", "qty": 7},  # internal FC has 10 -> 3 missing!
            ],
        },
    ).json()
    assert imp["data_source"] == "IMPORTED_REPORT"
    assert imp["inserted"] == 2
    assert imp["last_cursor"] == "page_2_token"

    # Interrupted sync replay: re-importing same external_tx_id skips duplicates idempotently
    imp_replay = client.post(
        "/api/v1/marketplaces/import-report",
        headers=oh,
        json={"channel": "AMAZON_IN", "records": [{"external_tx_id": "AMZ-TX-1", "tx_type": "SETTLEMENT", "gross_amount": "2250", "net_settlement": "1800"}]},
    ).json()
    assert imp_replay["inserted"] == 0
    assert imp_replay["skipped_duplicates"] == 1

    rec = client.post("/api/v1/marketplaces/reconcile?channel=AMAZON_IN", headers=oh).json()
    assert rec["cases_created"] == 2
    types = {c["type"] for c in rec["cases"]}
    assert "SETTLEMENT_VARIANCE" in types
    assert "MISSING_FC_INVENTORY" in types

    # 5. Procurement PO + Supplier Invoice (75% credit target) + Duplicate-Prevented Payment
    proc_recs = client.get("/api/v1/procurement/recommendations", headers=oh).json()
    assert any(r["effective_lead_days_incl_fc_delay"] == 11 for r in proc_recs)  # 6 supplier + 5 FC delay

    po = client.post(
        "/api/v1/procurement/purchase-orders/request",
        headers=oh,
        json={"supplier_id": sup["id"], "lines": [{"sku_id": sku_hm["id"], "qty_ordered": 5}], "idempotency_key": "PO-KEY-1"},
    ).json()
    assert po["status"] == "PENDING_APPROVAL"
    # Duplicate PO idempotency
    po_dup = client.post(
        "/api/v1/procurement/purchase-orders/request",
        headers=oh,
        json={"supplier_id": sup["id"], "lines": [{"sku_id": sku_hm["id"], "qty_ordered": 5}], "idempotency_key": "PO-KEY-1"},
    ).json()
    assert po_dup["idempotent_replay"] is True
    client.post(f"/api/v1/approvals/{po['approval_request_id']}/review", headers=oh, json={"decision": "APPROVED"})

    inv_date = date.today() - timedelta(days=29)
    inv = client.post(
        "/api/v1/procurement/invoices",
        headers=oh,
        json={"supplier_id": sup["id"], "invoice_number": "KIR-INV-88", "taxable_amount": "55000.00", "gst_rate": "18.00", "invoice_date": inv_date.isoformat(), "po_id": po["po_id"]},
    ).json()
    # 75% of 40 days = 30 days from inv_date
    assert inv["target_75_pay_date"] == (inv_date + timedelta(days=30)).isoformat()

    pay_req = client.post(
        "/api/v1/procurement/payments/request",
        headers=oh,
        json={"invoice_id": inv["id"], "amount_inr": inv["total_amount"], "idempotency_key": "PAY-1"},
    ).json()
    # Duplicate pending payment for same invoice blocked!
    pay_dup_inv = client.post(
        "/api/v1/procurement/payments/request",
        headers=oh,
        json={"invoice_id": inv["id"], "amount_inr": "1000.00", "idempotency_key": "PAY-2"},
    )
    assert pay_dup_inv.status_code == 409
    client.post(f"/api/v1/approvals/{pay_req['approval_request_id']}/review", headers=oh, json={"decision": "APPROVED"})

    # 6. BUSY Voucher Export & Logistics
    busy_exp = client.post("/api/v1/finance/busy/export", headers=oh).json()
    assert busy_exp["record_count"] == 2
    assert busy_exp["data_source"] == "EXPORT_BRIDGE"
    assert "<SalesVoucher>" in busy_exp["xml"]

    sh = client.post("/api/v1/logistics/shipments", headers=oh, json={"direction": "WAREHOUSE_TO_FC", "channel": "AMAZON", "carrier": "BlueDart", "freight_cost": "750.00"}).json()
    assert sh["status"] == "IN_TRANSIT"

    # 7. AI Business Intelligence (7 mandatory fields) + Automation Cycle + Command Centre
    auto = client.post("/api/v1/automation/run", headers=oh).json()
    assert all(r["status"] == "SUCCESS" for r in auto["runs"])

    ai_recs = client.get("/api/v1/intelligence/recommendations", headers=oh).json()
    assert len(ai_recs) >= 1
    sample = ai_recs[0]
    for field in ("problem_identified", "supporting_data_json", "estimated_financial_impact_inr", "recommended_action", "confidence_score", "approval_required", "expected_outcome"):
        assert field in sample

    cc = client.get("/api/v1/command-centre", headers=oh).json()
    assert cc["financial_health"]["cash_available_inr"] == "250000.00"

    # 8. Backup & Restore Verification
    backup_resp = client.post("/api/v1/system/backup", headers=oh).json()
    backup_path = isolated_env["backup_dir"] / backup_resp["backup_file"]
    assert backup_path.exists()

    # Corrupt/delete DB file and restore from verified backup
    isolated_env["engine"].dispose()
    isolated_env["db_file"].unlink()
    restore_sqlite_backup(backup_path, isolated_env["db_url"])
    assert isolated_env["db_file"].exists()
    prof_restored = client.get("/api/v1/finance/profitability", headers=oh)
    assert prof_restored.status_code == 200
    assert prof_restored.json()["order_count"] == 2
