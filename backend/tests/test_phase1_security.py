from app.core.security import current_totp


def bootstrap_and_login_owner(client):
    boot = client.post(
        "/api/v1/auth/bootstrap-owner",
        json={
            "email": "owner@aquaflow.in",
            "password": "StrongOwnerPassword!2026",
            "full_name": "Rajesh Sharma",
            "mobile": "+919811001100",
            "enable_mfa": True,
        },
    )
    assert boot.status_code == 200, boot.text
    data = boot.json()
    totp = current_totp(data["totp_secret"])
    login = client.post(
        "/api/v1/auth/owner/login",
        json={"email": "owner@aquaflow.in", "password": "StrongOwnerPassword!2026", "totp_code": totp},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {
        "headers": {"Authorization": f"Bearer {token}"},
        "totp_secret": data["totp_secret"],
        "recovery_codes": data["recovery_codes"],
        "token": token,
    }


def test_single_owner_mfa_recovery_and_session_revocation(client):
    owner_ctx = bootstrap_and_login_owner(client)

    # Second owner bootstrap MUST be rejected (409)
    dup = client.post(
        "/api/v1/auth/bootstrap-owner",
        json={"email": "hacker@evil.com", "password": "StrongPassword!123", "full_name": "Attacker"},
    )
    assert dup.status_code == 409

    # Login without MFA code must fail
    no_mfa = client.post(
        "/api/v1/auth/owner/login",
        json={"email": "owner@aquaflow.in", "password": "StrongOwnerPassword!2026"},
    )
    assert no_mfa.status_code == 401

    # Health reports zero SaaS dependencies
    h = client.get("/api/health")
    assert h.status_code == 200
    assert h.json()["saas_multi_tenancy"] is False

    # Owner recovery revokes existing sessions and resets password
    rec = client.post(
        "/api/v1/auth/owner/recover",
        json={
            "email": "owner@aquaflow.in",
            "recovery_code": owner_ctx["recovery_codes"][0],
            "new_password": "RecoveredOwnerPassword!2026",
        },
    )
    assert rec.status_code == 200
    assert rec.json()["remaining_recovery_codes"] == 5

    # Old session token must now be revoked (401)
    me_old = client.get("/api/v1/auth/me", headers=owner_ctx["headers"])
    assert me_old.status_code == 401

    # Login with new password + TOTP succeeds
    totp = current_totp(owner_ctx["totp_secret"])
    new_login = client.post(
        "/api/v1/auth/owner/login",
        json={"email": "owner@aquaflow.in", "password": "RecoveredOwnerPassword!2026", "totp_code": totp},
    )
    assert new_login.status_code == 200


def test_employee_rbac_idor_lockout_and_access_preview_parity(client):
    owner = bootstrap_and_login_owner(client)
    oh = owner["headers"]

    # Create two warehouse locations
    l1 = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "WH-MAIN", "name": "Main Warehouse", "location_type": "WAREHOUSE"}).json()
    l2 = client.post("/api/v1/inventory/locations", headers=oh, json={"code": "WH-NORTH", "name": "North Annex", "location_type": "WAREHOUSE"}).json()

    # Create employee restricted ONLY to WH-MAIN, no export, only warehouse/inventory pages
    emp_res = client.post(
        "/api/v1/permissions/employees",
        headers=oh,
        json={
            "employee_code": "EMP01",
            "full_name": "Harpreet Singh",
            "pin": "4821",
            "department": "Warehouse",
            "preferred_language": "pa",
            "visible_pages": ["warehouse", "inventory"],
            "accessible_location_ids": [l1["id"]],
            "allowed_actions": ["inventory.view", "receipt.create", "task.view_own", "task.complete"],
            "can_export": False,
        },
    )
    assert emp_res.status_code == 200
    emp_id = emp_res.json()["employee_id"]

    # Rate limit check: 3 wrong PINs trigger 429 lockout
    for _ in range(3):
        bad = client.post("/api/v1/auth/employee/login", json={"employee_code": "EMP01", "pin": "0000"})
        assert bad.status_code == 401
    locked = client.post("/api/v1/auth/employee/login", json={"employee_code": "EMP01", "pin": "4821"})
    assert locked.status_code == 429

    # Create a second employee for functional RBAC & preview parity check
    emp2_res = client.post(
        "/api/v1/permissions/employees",
        headers=oh,
        json={
            "employee_code": "EMP02",
            "full_name": "Ramesh Kumar",
            "pin": "7744",
            "preferred_language": "hi",
            "visible_pages": ["warehouse"],
            "accessible_location_ids": [l1["id"]],
            "allowed_actions": ["inventory.view", "receipt.create", "task.view_own", "task.complete"],
            "can_export": False,
        },
    )
    assert emp2_res.status_code == 200
    emp2_id = emp2_res.json()["employee_id"]

    # Assign a task to EMP02 and check Owner Access Preview accurately reflects it
    t_res = client.post(
        "/api/v1/tasks",
        headers=oh,
        json={"task_type": "RECEIPT", "title": "Count 1HP Pump Delivery", "assigned_to_id": emp2_id, "location_id": l1["id"]},
    )
    assert t_res.status_code == 200

    preview = client.get(f"/api/v1/permissions/employees/{emp2_id}/preview", headers=oh).json()
    assert preview["visible_pages"] == ["warehouse"]
    assert preview["accessible_location_ids"] == [l1["id"]]
    assert preview["can_export"] is False
    assert len(preview["assigned_tasks"]) == 1
    assert "receipt.create" in preview["allowed_actions"]

    # Employee login
    e_login = client.post("/api/v1/auth/employee/login", json={"employee_code": "EMP02", "pin": "7744"})
    assert e_login.status_code == 200
    eh = {"Authorization": f"Bearer {e_login.json()['access_token']}"}

    # Owner creates SKU
    sku = client.post(
        "/api/v1/inventory/skus",
        headers=oh,
        json={
            "sku_code": "PUMP-1HP",
            "name": "1HP Submersible Water Pump",
            "category": "WATER_PUMP",
            "item_type": "FINISHED_GOOD",
            "purchase_cost": "3200.00",
            "selling_price": "4500.00",
            "mrp": "5500.00",
            "gst_rate": "18.00",
        },
    ).json()

    # Employee can view SKUs, and purchase_cost (sensitive owner data) MUST be masked (None)
    skus_emp = client.get("/api/v1/inventory/skus", headers=eh).json()
    assert skus_emp[0]["purchase_cost"] is None

    # Employee CAN receive stock at permitted WH-MAIN
    ok_rec = client.post(
        "/api/v1/inventory/receive",
        headers=eh,
        json={"sku_id": sku["id"], "location_id": l1["id"], "qty": 10, "unit_cost": "3200.00", "idempotency_key": "REC-EMP-1"},
    )
    assert ok_rec.status_code == 200

    # Employee CANNOT receive or view stock at unauthorized WH-NORTH (IDOR blocked 403)
    idor_rec = client.post(
        "/api/v1/inventory/receive",
        headers=eh,
        json={"sku_id": sku["id"], "location_id": l2["id"], "qty": 5, "unit_cost": "3200.00", "idempotency_key": "REC-EMP-2"},
    )
    assert idor_rec.status_code == 403

    idor_avail = client.get(f"/api/v1/inventory/availability?location_id={l2['id']}", headers=eh)
    assert idor_avail.status_code == 403

    # Employee CANNOT dispatch (not in allowed_actions), view financials, access command centre, or promote self
    assert client.post("/api/v1/inventory/dispatch", headers=eh, json={"sku_id": sku["id"], "location_id": l1["id"], "qty": 1, "reference_id": "X", "idempotency_key": "D1"}).status_code == 403
    assert client.get("/api/v1/command-centre", headers=eh).status_code == 403
    assert client.get("/api/v1/finance/profitability", headers=eh).status_code == 403
    assert client.put(
        f"/api/v1/permissions/employees/{emp2_id}",
        headers=eh,
        json={"visible_pages": ["command_centre"], "accessible_location_ids": [l1["id"], l2["id"]], "editable_fields": {}, "allowed_actions": ["approval.review"], "can_export": True},
    ).status_code == 403

    # Owner cannot grant owner-only action to employee
    bad_grant = client.put(
        f"/api/v1/permissions/employees/{emp2_id}",
        headers=oh,
        json={"visible_pages": ["warehouse"], "accessible_location_ids": [l1["id"]], "editable_fields": {}, "allowed_actions": ["po.approve"], "can_export": False},
    )
    assert bad_grant.status_code == 400

    # Denied attempts were logged in audit_logs
    logs = client.get("/api/v1/audit-logs", headers=oh).json()
    assert any(l["outcome"] == "DENIED" for l in logs)


def test_local_preview_mode_without_login_and_production_guard(client, monkeypatch):
    from app.core.config import settings

    bootstrap_and_login_owner(client)
    client.cookies.clear()

    # Without auth header or cookie, default enforced mode blocks access (401)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/command-centre").status_code == 401

    # In development with BOSS_REQUIRE_AUTH=false, app opens directly as Owner
    monkeypatch.setattr(settings, "boss_env", "development")
    monkeypatch.setattr(settings, "boss_require_auth", False)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["auth_mode"] == "local_preview_no_auth"
    assert me.json()["user"]["role"] == "OWNER"
    assert client.get("/api/v1/command-centre").status_code == 200

    # Production environment MUST ignore boss_require_auth=False and enforce auth (401)
    monkeypatch.setattr(settings, "boss_env", "production")
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/command-centre").status_code == 401

