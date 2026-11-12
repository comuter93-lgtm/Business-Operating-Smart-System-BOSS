# BOSS — Security, Permissions & Audit Model

## 1. Authority Hierarchy
- **Single Verified Owner (`role = OWNER`)**: Exclusive administrative, financial, configuration, and approval authority. No employee may create, modify, deactivate, or escalate to `OWNER`.
- **Employees (`role = EMPLOYEE`)**: Individual accounts (`employee_code` + PIN or password) with strictly scoped permissions evaluated server-side on every request.

## 2. Authentication & Session Security
- **Password / PIN Hashing**: `scrypt` with per-user cryptographic salt (`os.urandom(16)`), constant-time verification (`hmac.compare_digest`).
- **Owner MFA**: RFC 6238 TOTP (`6-digit`, 30s step, ±1 window) + backup recovery codes (hashed at rest).
- **WhatsApp OTP**: Abstracted via `WhatsAppOTPProvider`; disabled by default until authorized Meta/BSP credentials are configured.
- **Sessions**: Cryptographically random session tokens stored hashed (`SHA-256`) in `user_sessions` with expiry, IP/User-Agent tracking, and immediate server-side revocation (`revoked_at`).
- **Rate Limiting**: Login/PIN endpoints track failed attempts per identifier + IP and enforce temporary lockouts (`429 Too Many Requests`).
- **PIN Guardrail**: Possession of an employee PIN alone NEVER authorizes financial commitments, BOM edits, stock adjustments, or permission changes.

## 3. Server-Enforced Permissions & Owner Access Preview
Every employee has a `PermissionProfile` defining:
- `visible_pages`: allowlist of UI modules
- `accessible_location_ids`: list of warehouse/location IDs accessible (`[]` = none, `["*"]` only if explicitly granted)
- `editable_fields`: map of entity -> allowed fields
- `allowed_actions`: allowlist of operation codes (e.g., `receipt.create`, `dispatch.pick`, `return.inspect`, `cycle_count.submit`)
- `can_export`: boolean (default `False`)

The **Owner Access Preview** endpoint (`GET /api/v1/permissions/employees/{id}/preview`) executes the exact same `evaluate_employee_access()` resolver used by FastAPI route dependencies, guaranteeing 100% parity between what the Owner previews and what the server/database enforces.

## 4. Audit & Immutability Controls
- `audit_logs` is append-only: records `actor_id`, `actor_role`, `action`, `resource_type`, `resource_id`, `outcome` (`SUCCESS`/`DENIED`/`ERROR`), `details_json`, `ip_address`, `created_at`.
- `inventory_ledger` is append-only: corrections require compensating ledger entries linked to an Owner-approved `ApprovalRequest`.
- Completed employee tasks cannot be silently altered; corrections require a new corrective task/transaction.
- Secret hygiene: marketplace API keys, BUSY credentials, and session secrets live only in environment variables / encrypted settings and are masked in all API responses and logs.

