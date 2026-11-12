from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from tests.test_phase1_security import bootstrap_and_login_owner


def test_inventory_ledger_ageing_transfers_concurrency_and_cycle_counts(client, isolated_env):
    owner = bootstrap_and_login_owner(client)
    oh = owner["headers"]

    wh = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "WH-1", "name": "Main WH", "location_type": "WAREHOUSE"}).json()
    fc = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "AMZ-BOM5", "name": "Amazon BOM5 FC", "location_type": "AMAZON_FC", "fc_receiving_delay_days": 4}).json()
    transit = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "IN-TRANSIT", "name": "In Transit", "location_type": "IN_TRANSIT"}).json()

    sku = client.post(
        "/api/v1/inventory/skus",
        headers=oh,
        json={
            "sku_code": "PUMP-05HP",
            "name": "0.5HP Self Priming Pump",
            "category": "WATER_PUMP",
            "item_type": "FINISHED_GOOD",
            "purchase_cost": "1800.00",
            "selling_price": "2600.00",
            "mrp": "3200.00",
            "gst_rate": "18.00",
        },
    ).json()

    today = date.today()
    d_normal = (today - timedelta(days=10)).isoformat()
    d_red = (today - timedelta(days=35)).isoformat()
    d_crit = (today - timedelta(days=50)).isoformat()

    # Receive 3 batches + duplicate idempotency check
    r1 = client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": sku["id"], "location_id": wh["id"], "qty": 5, "unit_cost": "1800", "inbound_date": d_normal, "idempotency_key": "R-NORM"})
    assert r1.status_code == 200 and r1.json()["idempotent_replay"] is False
    r1_dup = client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": sku["id"], "location_id": wh["id"], "qty": 5, "unit_cost": "1800", "inbound_date": d_normal, "idempotency_key": "R-NORM"})
    assert r1_dup.status_code == 200 and r1_dup.json()["idempotent_replay"] is True

    client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": sku["id"], "location_id": wh["id"], "qty": 4, "unit_cost": "1800", "inbound_date": d_red, "idempotency_key": "R-RED"})
    client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": sku["id"], "location_id": wh["id"], "qty": 3, "unit_cost": "1800", "inbound_date": d_crit, "idempotency_key": "R-CRIT"})
    # Receive in IN_TRANSIT — must NOT count as available_qty
    client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": sku["id"], "location_id": transit["id"], "qty": 20, "unit_cost": "1800", "inbound_date": d_normal, "idempotency_key": "R-TR"})

    avail = client.get(f"/api/v1/inventory/availability?sku_id={sku['id']}", headers=oh).json()[0]
    assert avail["physical_qty"] == 12
    assert avail["available_qty"] == 12
    assert avail["in_transit_qty"] == 20

    # Transfer 2 units (FIFO takes from oldest critical batch!) to Amazon FC — must preserve d_crit!
    tr = client.post(
        "/api/v1/inventory/transfer",
        headers=oh,
        json={"sku_id": sku["id"], "from_location_id": wh["id"], "to_location_id": fc["id"], "qty": 2, "idempotency_key": "TR-FC-1"},
    )
    assert tr.status_code == 200

    ageing = client.get("/api/v1/inventory/ageing", headers=oh).json()
    assert ageing["thresholds"]["red_age_days"] == 31
    assert ageing["thresholds"]["critical_age_days"] == 46
    # Check transferred batch at AMZ-BOM5 retained age 50 (CRITICAL)
    fc_batches = [b for b in ageing["batches"] if b["location_code"] == "AMZ-BOM5"]
    assert len(fc_batches) == 1
    assert fc_batches[0]["inbound_date"] == d_crit
    assert fc_batches[0]["classification"] == "CRITICAL"

    # Configurable threshold test: change red_age_days to 36 -> 35-day batch becomes NORMAL
    client.put("/api/v1/settings", headers=oh, json={"red_age_days": 36})
    ageing_updated = client.get("/api/v1/inventory/ageing", headers=oh).json()
    red_batch_now = [b for b in ageing_updated["batches"] if b["inbound_date"] == d_red][0]
    assert red_batch_now["classification"] == "NORMAL"
    client.put("/api/v1/settings", headers=oh, json={"red_age_days": 31})  # restore default

    # Cycle count variance -> owner approval adjusts stock
    cc = client.post("/api/v1/inventory/cycle-counts", headers=oh, json={"location_id": wh["id"]}).json()
    # WH-1 currently has 10 units (12 - 2 transferred). Suppose physical count finds 9 (-1 discrepancy)
    sub = client.post(f"/api/v1/inventory/cycle-counts/{cc['id']}/submit", headers=oh, json={"counts": [{"sku_id": sku["id"], "counted_qty": 9}]}).json()
    assert len(sub["approval_requests_created"]) == 1
    apr_id = sub["approval_requests_created"][0]
    client.post(f"/api/v1/approvals/{apr_id}/review", headers=oh, json={"decision": "APPROVED", "review_notes": "Verified missing unit"})

    avail_after_adj = client.get(f"/api/v1/inventory/availability?sku_id={sku['id']}", headers=oh).json()[0]
    assert avail_after_adj["available_qty"] == 11  # 9 in WH-1 + 2 in AMZ-BOM5

    # Concurrent dispatch test: WH-1 has 9 available; launch 5 concurrent dispatches of 3 each (max 3 can succeed = 9, never negative)
    def _try_dispatch(idx: int):
        return client.post(
            "/api/v1/inventory/dispatch",
            headers=oh,
            json={"sku_id": sku["id"], "location_id": wh["id"], "qty": 3, "reference_id": f"CONC-{idx}", "idempotency_key": f"CONC-D-{idx}"},
        ).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(_try_dispatch, range(5)))

    avail_final = client.get(f"/api/v1/inventory/availability?sku_id={sku['id']}&location_id={wh['id']}", headers=oh).json()[0]
    assert avail_final["available_qty"] >= 0
    assert statuses.count(200) <= 3
    assert avail_final["available_qty"] == 9 - (statuses.count(200) * 3)


def test_bom_assembly_genealogy_incomplete_returns_and_warranty_reserve(client, isolated_env):
    owner = bootstrap_and_login_owner(client)
    oh = owner["headers"]

    wh = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "WH-MAIN", "name": "Main WH", "location_type": "WAREHOUSE"}).json()
    ret_loc = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "RET-AREA", "name": "Returns Inspection", "location_type": "RETURNS_AREA"}).json()
    dmg_loc = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "DMG-BIN", "name": "Damaged Stock", "location_type": "DAMAGED"}).json()

    pump = client.post("/api/v1/inventory/skus", headers=oh, json={"sku_code": "PUMP-1HP", "name": "1HP Pump", "category": "WATER_PUMP", "item_type": "FINISHED_GOOD", "purchase_cost": "3000", "selling_price": "4200", "mrp": "5000", "warranty_eligible": True}).json()
    pipe = client.post("/api/v1/inventory/skus", headers=oh, json={"sku_code": "SUCT-PIPE", "name": "Suction Pipe 10m", "category": "ACCESSORY", "item_type": "COMPONENT", "purchase_cost": "400", "selling_price": "650", "mrp": "800", "warranty_eligible": False}).json()
    valve = client.post("/api/v1/inventory/skus", headers=oh, json={"sku_code": "FOOT-VLV", "name": "Brass Foot Valve", "category": "SPARE_PART", "item_type": "COMPONENT", "purchase_cost": "150", "selling_price": "250", "mrp": "300", "warranty_eligible": False}).json()
    bundle = client.post("/api/v1/inventory/skus", headers=oh, json={"sku_code": "KIT-1HP", "name": "1HP Pump Installation Bundle", "category": "BUNDLE", "item_type": "BUNDLE", "purchase_cost": "3550", "selling_price": "4950", "mrp": "5900", "warranty_eligible": True}).json()

    # Receive components: valve is 38 days old (RED)! Assembly must NOT mask its age!
    old_date = (date.today() - timedelta(days=38)).isoformat()
    recent_date = (date.today() - timedelta(days=5)).isoformat()
    client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": pump["id"], "location_id": wh["id"], "qty": 60, "unit_cost": "3000", "inbound_date": recent_date, "idempotency_key": "CMP-P1"})
    client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": pipe["id"], "location_id": wh["id"], "qty": 20, "unit_cost": "400", "inbound_date": recent_date, "idempotency_key": "CMP-S1"})
    client.post("/api/v1/inventory/receive", headers=oh, json={"sku_id": valve["id"], "location_id": wh["id"], "qty": 20, "unit_cost": "150", "inbound_date": old_date, "idempotency_key": "CMP-V1"})

    # Check 2% warranty reserve rule: 60 units of PUMP-1HP -> ceil(2% of 60) = ceil(1.2) = 2 units required
    w_res = client.get("/api/v1/warranty/reserves", headers=oh).json()
    pump_w = [w for w in w_res if w["sku_code"] == "PUMP-1HP"][0]
    assert pump_w["required_reserve"] == 2
    assert pump_w["shortage"] == 2

    # Request BOM & approve
    bom_req = client.post(
        "/api/v1/boms/request",
        headers=oh,
        json={
            "bundle_sku_id": bundle["id"],
            "items": [
                {"component_sku_id": pump["id"], "qty_required": 1},
                {"component_sku_id": pipe["id"], "qty_required": 1},
                {"component_sku_id": valve["id"], "qty_required": 1},
            ],
            "notes": "Standard 1HP kit BOM",
        },
    ).json()
    assert bom_req["status"] == "DRAFT_PENDING_APPROVAL"
    client.post(f"/api/v1/approvals/{bom_req['approval_request_id']}/review", headers=oh, json={"decision": "APPROVED"})

    # Reserve and complete assembly of 5 bundles
    asm = client.post(
        "/api/v1/assembly/orders",
        headers=oh,
        json={"bundle_sku_id": bundle["id"], "component_location_id": wh["id"], "target_location_id": wh["id"], "planned_qty": 5, "idempotency_key": "ASM-1"},
    ).json()
    comp = client.post(f"/api/v1/assembly/orders/{asm['id']}/complete", headers=oh, json={"actual_produced_qty": 5, "wastage_qty": 0}).json()
    assert comp["effective_inbound_date"] == old_date  # Inherits oldest component inbound date!

    # Replay completion MUST NOT double-consume components
    comp_dup = client.post(f"/api/v1/assembly/orders/{asm['id']}/complete", headers=oh, json={"actual_produced_qty": 5, "wastage_qty": 0}).json()
    assert comp_dup["idempotent_replay"] is True

    # Verify bundle ageing reflects 38 days (RED)
    ageing = client.get("/api/v1/inventory/ageing", headers=oh).json()
    bundle_batch = [b for b in ageing["batches"] if b["sku_code"] == "KIT-1HP"][0]
    assert bundle_batch["classification"] == "RED"
    assert bundle_batch["age_days"] == 38

    # Incomplete bundle return: customer returns pump only, missing suction pipe & foot valve!
    ret = client.post("/api/v1/returns", headers=oh, json={"channel": "AMAZON", "sku_id": bundle["id"], "location_id": ret_loc["id"], "qty": 1, "external_order_id": "AMZ-ORD-99", "received_now": True}).json()
    insp = client.post(
        f"/api/v1/returns/{ret['id']}/inspect",
        headers=oh,
        json={
            "classification": "RESALABLE",  # System must override to INCOMPLETE due to BOM mismatch!
            "returned_component_qtys": {str(pump["id"]): 1, str(pipe["id"]): 0, str(valve["id"]): 0},
            "restock_location_id": wh["id"],
            "damaged_location_id": dmg_loc["id"],
            "notes": "Pipe and foot valve missing from box",
        },
    ).json()
    assert insp["classification"] == "INCOMPLETE"
    assert len(insp["missing_components"]) == 2
    assert insp["estimated_loss_inr"] == "550.00"  # 400 + 150

    # Warranty replacement requires Owner approval before fulfillment
    w_claim = client.post(
        "/api/v1/warranty/claims/request",
        headers=oh,
        json={"sku_id": pump["id"], "customer_ref": "CUST-441", "issue_description": "Motor winding burnt within warranty", "replacement_qty": 1},
    ).json()
    # Fulfill before approval -> 409
    assert client.post(f"/api/v1/warranty/claims/{w_claim['claim_id']}/fulfill?warehouse_location_id={wh['id']}", headers=oh).status_code == 409
    # Owner approves -> fulfill succeeds
    client.post(f"/api/v1/approvals/{w_claim['approval_request_id']}/review", headers=oh, json={"decision": "APPROVED"})
    ful = client.post(f"/api/v1/warranty/claims/{w_claim['claim_id']}/fulfill?warehouse_location_id={wh['id']}", headers=oh)
    assert ful.status_code == 200
    assert ful.json()["status"] == "FULFILLED"

