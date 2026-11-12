"""Seed realistic Indian water-pump business data into the local MVP database for interactive testing."""
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sys
import uuid

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal, init_db
from app.models.auth import BusinessSettings, User
from app.models.operations import EmployeeTask
from app.services.approval_service import review_approval_request
from app.services.assembly_service import complete_assembly_order, create_assembly_order, create_bom_request
from app.services.auth_service import bootstrap_owner, create_employee
from app.services.finance_service import record_sales_order
from app.services.inventory_service import create_location, create_sku, receive_stock
from app.services.logistics_service import create_shipment
from app.services.marketplace_service import import_marketplace_report, run_marketplace_reconciliation
from app.services.procurement_service import create_purchase_order_request, create_supplier, record_supplier_invoice
from app.services.returns_warranty_service import create_return_case, inspect_return_case
from app.workers.automation import run_automation_cycle


def seed_mvp():
    init_db()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.role == "OWNER").first():
            print("Database already initialized; skipping seed.")
            return

        # 1. Owner (MFA disabled ONLY for this local MVP interactive check) & Settings
        res = bootstrap_owner(
            db,
            email="owner@aquaflow.in",
            password="AquaFlowMVP!2026",
            full_name="Rajesh Sharma (Owner)",
            mobile="+919811001100",
            enable_mfa=False,
        )
        owner = res["owner"]
        bs = db.query(BusinessSettings).first()
        bs.cash_available = Decimal("340000.00")
        bs.cc_od_limit = Decimal("500000.00")
        bs.cc_od_utilized = Decimal("120000.00")
        bs.cc_od_annual_rate_pct = Decimal("10.50")
        db.commit()

        # 2. Locations
        wh = create_location(db, owner, code="WH-DEL", name="Delhi Main Warehouse", location_type="WAREHOUSE", zone="A", rack="R1", bin_code="A-R1-01")
        amz_fc = create_location(db, owner, code="AMZ-DEL4", name="Amazon DEL4 FC", location_type="AMAZON_FC", fc_receiving_delay_days=4)
        ret_loc = create_location(db, owner, code="RET-AREA", name="Returns Inspection Zone", location_type="RETURNS_AREA")
        dmg_loc = create_location(db, owner, code="DMG-BIN", name="Damaged Goods Cage", location_type="DAMAGED")
        transit_loc = create_location(db, owner, code="IN-TRANSIT", name="In-Transit Shipments", location_type="IN_TRANSIT")

        # 3. Employees + Tasks
        emp1 = create_employee(
            db,
            owner,
            employee_code="EMP01",
            full_name="Harpreet Singh",
            pin="1234",
            department="Warehouse",
            preferred_language="pa",
            visible_pages=["warehouse", "inventory"],
            accessible_location_ids=[wh.id, ret_loc.id],
            allowed_actions=["inventory.view", "receipt.create", "return.receive", "return.inspect", "task.view_own", "task.complete"],
            can_export=False,
        )
        db.add(
            EmployeeTask(
                task_code="TSK-DEMO-01",
                task_type="RETURN_INSPECTION",
                title="Inspect incoming Amazon return for 1HP Pump Kit",
                instructions="Verify pump body, 10m suction pipe, and brass foot valve against approved BOM.",
                assigned_to_id=emp1.id,
                assigned_by_id=owner.id,
                location_id=ret_loc.id,
                evidence_required=False,
            )
        )
        db.commit()

        # 4. Suppliers & SKUs
        sup = create_supplier(
            db,
            owner,
            {
                "supplier_code": "SUP-KIR",
                "name": "Kirloskar Pump Distributors",
                "state_code": "MH",
                "credit_days": 40,
                "lead_time_days": 6,
            },
        )
        pump_1hp = create_sku(db, owner, {"sku_code": "PUMP-1HP", "barcode": "8901001001", "name": "1HP Submersible Borewell Pump", "brand": "AquaFlow", "category": "WATER_PUMP", "item_type": "FINISHED_GOOD", "purchase_cost": "3200", "selling_price": "4450", "mrp": "5400", "gst_rate": "18", "primary_supplier_id": sup.id, "strategic_role": "HIGH_PROFIT", "amazon_sku": "AMZ-1HP"})
        pump_05hp = create_sku(db, owner, {"sku_code": "PUMP-05HP", "barcode": "8901001002", "name": "0.5HP Self-Priming Booster Pump", "brand": "AquaFlow", "category": "WATER_PUMP", "item_type": "FINISHED_GOOD", "purchase_cost": "1850", "selling_price": "2290", "mrp": "2899", "gst_rate": "18", "primary_supplier_id": sup.id, "strategic_role": "HIGH_VOL_LOW_MARGIN", "amazon_sku": "AMZ-05HP", "flipkart_sku": "FK-05HP"})
        pipe = create_sku(db, owner, {"sku_code": "SUCT-PIPE", "barcode": "8901002001", "name": "HDPE Suction Pipe 10m", "brand": "AquaFlow", "category": "ACCESSORY", "item_type": "COMPONENT", "purchase_cost": "380", "selling_price": "620", "mrp": "799", "gst_rate": "18", "warranty_eligible": False, "primary_supplier_id": sup.id, "strategic_role": "CUSTOMER_ACQUISITION"})
        valve = create_sku(db, owner, {"sku_code": "FOOT-VLV", "barcode": "8901003001", "name": "Heavy Brass Foot Valve 1-inch", "brand": "AquaFlow", "category": "SPARE_PART", "item_type": "COMPONENT", "purchase_cost": "160", "selling_price": "290", "mrp": "350", "gst_rate": "18", "warranty_eligible": False, "primary_supplier_id": sup.id, "strategic_role": "LOW_VOL_HIGH_MARGIN"})
        bundle = create_sku(db, owner, {"sku_code": "KIT-1HP-PRO", "barcode": "8901009001", "name": "1HP Pump + Pipe + Valve Complete Kit", "brand": "AquaFlow", "category": "BUNDLE", "item_type": "BUNDLE", "purchase_cost": "3740", "selling_price": "5190", "mrp": "6400", "gst_rate": "18", "primary_supplier_id": sup.id, "strategic_role": "HIGH_PROFIT"})

        # 5. Opening Stock Across Normal (6d), Red (37d), Critical (52d), In-Transit, and Amazon FC
        today = date.today()
        receive_stock(db, owner, sku_id=pump_1hp.id, location_id=wh.id, qty=25, unit_cost=Decimal("3200"), inbound_date=today - timedelta(days=6), idempotency_key="MVP-R1")
        receive_stock(db, owner, sku_id=pump_05hp.id, location_id=wh.id, qty=18, unit_cost=Decimal("1850"), inbound_date=today - timedelta(days=37), idempotency_key="MVP-R2")
        receive_stock(db, owner, sku_id=pump_05hp.id, location_id=amz_fc.id, qty=12, unit_cost=Decimal("1850"), inbound_date=today - timedelta(days=10), idempotency_key="MVP-R3")
        receive_stock(db, owner, sku_id=pipe.id, location_id=wh.id, qty=20, unit_cost=Decimal("380"), inbound_date=today - timedelta(days=12), idempotency_key="MVP-R4")
        receive_stock(db, owner, sku_id=valve.id, location_id=wh.id, qty=15, unit_cost=Decimal("160"), inbound_date=today - timedelta(days=52), idempotency_key="MVP-R5")
        receive_stock(db, owner, sku_id=pump_1hp.id, location_id=transit_loc.id, qty=10, unit_cost=Decimal("3200"), inbound_date=today, idempotency_key="MVP-R6")

        # 6. Approved BOM & Assembly (Bundle inherits 52d Critical component age!)
        bom_res = create_bom_request(
            db,
            owner,
            bundle_sku_id=bundle.id,
            items=[{"component_sku_id": pump_1hp.id, "qty_required": 1}, {"component_sku_id": pipe.id, "qty_required": 1}, {"component_sku_id": valve.id, "qty_required": 1}],
            notes="Standard 1HP Installation Bundle",
        )
        review_approval_request(db, owner, approval_id=bom_res["approval_request"].id, decision="APPROVED")
        asm = create_assembly_order(db, owner, bundle_sku_id=bundle.id, component_location_id=wh.id, target_location_id=wh.id, planned_qty=4, idempotency_key="MVP-ASM-1")
        complete_assembly_order(db, owner, assembly_order_id=asm.id, actual_produced_qty=4, wastage_qty=0)

        # 7. Sales Orders (Amazon, Flipkart, Offline)
        record_sales_order(db, owner, order_code="SO-AMZ-501", channel="AMAZON", sku_id=pump_05hp.id, location_id=wh.id, qty=6, selling_price_unit=Decimal("2290"), customer_state="DL", marketplace_fee_inr=Decimal("1350"), logistics_cost_inr=Decimal("320"), packaging_cost_inr=Decimal("120"), settlement_days=7)
        record_sales_order(db, owner, order_code="SO-FK-502", channel="FLIPKART", sku_id=pump_1hp.id, location_id=wh.id, qty=3, selling_price_unit=Decimal("4450"), customer_state="MH", marketplace_fee_inr=Decimal("1400"), logistics_cost_inr=Decimal("450"), packaging_cost_inr=Decimal("150"), settlement_days=10)

        # 8. Incomplete Bundle Return
        rc = create_return_case(db, owner, channel="AMAZON", sku_id=bundle.id, location_id=ret_loc.id, qty=1, external_order_id="AMZ-9001", received_now=True)
        inspect_return_case(db, owner, return_id=rc.id, classification="RESALABLE", returned_component_qtys={pump_1hp.id: 1, pipe.id: 0, valve.id: 0}, damaged_location_id=dmg_loc.id, notes="Missing HDPE suction pipe and brass foot valve")

        # 9. Marketplace Report Import & Discrepancy Detection
        import_marketplace_report(
            db,
            owner,
            channel="AMAZON_IN",
            cursor="demo_cursor_1",
            records=[
                {"external_tx_id": "AMZ-DEMO-SETTLE-1", "tx_type": "SETTLEMENT", "external_sku": "AMZ-05HP", "qty": 1, "gross_amount": "2290", "marketplace_fee": "250", "gst_on_fee": "45", "net_settlement": "1810"},
                {"external_tx_id": "AMZ-DEMO-FC-1", "tx_type": "FC_INVENTORY", "external_sku": "AMZ-05HP", "qty": 10},
            ],
        )
        run_marketplace_reconciliation(db, owner, channel="AMAZON_IN")

        # 10. Pending PO Approval + Supplier Invoice + Logistics + Automation Cycle
        create_purchase_order_request(db, owner, supplier_id=sup.id, lines=[{"sku_id": pipe.id, "qty_ordered": 30}], freight_cost=Decimal("650"), idempotency_key="MVP-PO-1")
        record_supplier_invoice(db, owner, supplier_id=sup.id, invoice_number="KIR-2026-411", taxable_amount=Decimal("42000"), gst_rate=Decimal("18"), invoice_date=today - timedelta(days=28))
        create_shipment(db, owner, direction="WAREHOUSE_TO_FC", channel="AMAZON", carrier="Delhivery Surface", tracking_number="DLV992817", origin_location_id=wh.id, destination_location_id=amz_fc.id, freight_cost=Decimal("820"))
        run_automation_cycle(db, trigger_source="MVP_SEED")

        print("Seeded local BOSS MVP database successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_mvp()

