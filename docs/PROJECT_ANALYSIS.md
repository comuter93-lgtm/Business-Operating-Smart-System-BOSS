# BOSS project analysis

Reviewed 13 November 2026. Repository: https://github.com/comuter93-lgtm/Business-Operating-Smart-System-BOSS

Baseline: branch `main`, commit `659da96`. Local checkout: `work/BOSS` beneath this chat's workspace. Application source was not changed during this review.

## Assessment

BOSS is an early full-stack operational MVP for one Indian water-pump, accessories, and spare-parts business. It combines warehouse operations, assembled product kits, marketplace reconciliation, supplier purchasing, profitability, and owner oversight. It has meaningful backend business logic and a usable frontend structure, but the README's “implemented phases 1–6” should not be read as production readiness or complete browser workflows.

The architecture is appropriate to continue developing. The first development work should address authorization and stock correctness, then complete the operational screens. A rewrite is not justified by this review.

## Product and users

- **Owner:** business dashboard, financial information, approvals, employee accounts and access, recommendations, integrations, backups.
- **Employee:** individual PIN login, assigned tasks, and permitted warehouse operations. Intended restrictions include location access, actions, editable fields, and exports.
- **Business channels:** Amazon India, Flipkart, and offline sales. Multi-company SaaS, subscriptions, and tenant onboarding are explicitly deferred.

The central business flow is supplier procurement → goods receipt → warehouse/FC stock → optional bundle assembly → sale/dispatch → settlement and profitability. Returns, warranty, owner approvals, and employee tasks cross these stages.

## Stack and code map

| Area | Implementation | Main entry points |
|---|---|---|
| Browser | React 19, TypeScript, Vite, custom CSS | `frontend/src/App.tsx`, `frontend/src/pages/`, `frontend/src/styles/boss.css` |
| API client | Fetch wrapper, cookies and optional in-memory bearer token | `frontend/src/api/client.ts` |
| API | FastAPI, five route modules | `backend/app/main.py`, `backend/app/api/` |
| Business rules | Python service modules | `backend/app/services/` |
| Persistence | SQLAlchemy; SQLite development, PostgreSQL deployment configuration | `backend/app/models/`, `backend/app/core/database.py` |
| Authentication/access | scrypt, TOTP, hashed session tokens, shared access evaluator | `core/security.py`, `core/permissions.py`, `services/auth_service.py` |
| External systems | Marketplace/BUSY/WhatsApp adapter scaffolding | `backend/app/integrations/` |
| Automation | Two built-in rules, manually callable cycle | `backend/app/workers/automation.py` |
| Test/demo data | Six integration tests and a sample business seed | `backend/tests/`, `backend/scripts/seed_mvp.py` |

The backend is a modular monolith: route → service → SQLAlchemy → one database. The frontend switches pages with React state, without a routing library. Vite forwards `/api` calls to `127.0.0.1:8000` during development.

## What the six browser workspaces do

| Workspace | Present in the frontend | Important remaining work |
|---|---|---|
| Command Centre | Revenue/profit/stock summaries, channel breakdown, ageing exposure, approval inbox | Verify all dashboard metrics against actual business definitions and production datasets |
| Inventory & Warehouse | SKU search, SKU/location creation, receipt, dispatch, transfer, availability and batch ageing | Cycle-count workflow, adjustments, evidence UX, scan workflow refinement, employee action-specific controls |
| Assembly & Returns | BOM list, returns queue and warranty reserve monitor | Forms to request/approve BOMs, reserve/complete assembly, receive/inspect returns, request/fulfill warranty replacements |
| Marketplaces & Finance | JSON report entry/import, reconciliation/discrepancies, profitability, procurement recommendations and BUSY XML export | Real sync; complete sales, supplier, PO, invoice and payment workflows in the browser |
| Team & Access | Employee creation, permission editing, access preview, task submission, audit log | Complete task assignment/verification UX and evidence-file selection/upload |
| AI, Logistics & Settings | Recommendation list, shipment list, automation execution/history, backup action | Shipment creation/status controls, business settings editor, actual scheduled execution |

English/Hindi/Punjabi translation dictionaries exist, but many page headings, form labels, errors, and task content are still English. Localization is partial.

## Important business rules already represented

- FIFO batch dispatch and transfers that preserve original inbound dates.
- Inventory ageing defaults: normal 0–30 days, red 31–45, critical 46+.
- Bundles retain genealogy and inherit the oldest consumed component's inbound date.
- Available stock excludes reserves/damage/warranty reserves; in-transit stock is not immediately sellable.
- Returns have a 48-hour inspection SLA and bundle-component checks.
- Warranty reserve target defaults to the larger of one unit or 2% of eligible warehouse stock.
- Owner approval is required for BOM changes, inventory adjustments, POs, supplier payments and warranty replacement.
- Monetary calculations use Decimal; GST splitting and gross/contribution/net profit calculations exist. Financial accuracy and accounting compatibility still require deeper validation before real use.

## Verified baseline

| Check | Result |
|---|---|
| Backend dependency installation in a local virtual environment | Passed |
| Existing backend suite, `.venv/bin/pytest -q` | **6 passed**, one dependency deprecation warning |
| Frontend, `npm run build` | Passed TypeScript and Vite production build |
| Demo seed on an isolated temporary SQLite database | Passed |
| Health and authenticated reads for dashboard, inventory, BOMs, returns, marketplace status, profitability, employees, intelligence and shipments | All 10 returned HTTP 200 |

The checks ran on the host's Python 3.14 and resolved package versions allowed by the requirements; Docker specifies Python 3.12. PostgreSQL, Docker deployment, live integrations and browser visual/interaction testing were not exercised. Six broad tests do not establish complete acceptance coverage.

## Confirmed issues to fix first

### 1. Employee inventory data escapes location restrictions

Source: `backend/app/api/inventory.py`, availability/ageing endpoints; `backend/app/services/inventory_service.py`, report functions.

An explicit request for a forbidden location returns 403, but omitting `location_id` returns stock aggregated across all locations. The ageing endpoint returns batches from forbidden locations, including blocked-capital information. Availability also returns `stock_value_inr` to employees.

Reproduced with two warehouses and an employee assigned to only one. The employee received aggregate stock from both and the restricted warehouse's ageing batch. Fix by applying location restrictions inside the database queries and explicitly shaping employee response fields. Add regression tests for omitted filters and users with no assigned locations.

### 2. Multi-batch dispatch retry can consume stock twice

Source: `backend/app/services/inventory_service.py`, `dispatch_stock()`.

The initial replay lookup searches the exact request key. A dispatch split across batches writes suffixed keys, so the original request key may never be stored. A retry can pass the lookup and dispatch again.

Reproduced with batches of 2 and 8 units and a dispatch of 3: original request and identical retry both returned 200, leaving 4 units instead of the expected 7. This directly affects stock and potentially order costing. Persist a request-level idempotency record, validate its payload, and return the original full result on replay.

## Other gaps found by source inspection

- **Assembly and returns authorization:** several operations and list endpoints use action permission without location/record scoping. Assembly and returns services do not consistently validate employee location access. Audit the entire endpoint surface, beyond the confirmed inventory leak.
- **Assembly concurrency:** dispatch/transfer have locking code; assembly reservation/completion lack equivalent row locking. Current tests do not prove simultaneous assembly safety or that reservations belong to the correct order/batches.
- **Transaction boundaries:** lower-level helpers commit internally, including audit logging and stock dispatch. For example, a sales order dispatch commits before the sales-order record is saved. Refactor around operation-level transactions and test rollback on downstream failures.
- **Permission completeness:** editable-field settings are stored and previewed, but no general mutation enforcement was found. Page visibility is not sufficient authorization. Some frontend operation controls also appear regardless of the employee's allowed actions.
- **Live integrations:** Amazon/Flipkart `fetch_incremental()` return empty record lists rather than making provider API calls. Credentials alone do not enable sync. BUSY generates a custom XML structure; vendor acceptance, ledger import, and a live bridge are not demonstrated. WhatsApp has configuration/status scaffolding only.
- **Intelligence:** recommendations are deterministic rules, not an LLM integration. Several impact figures are hard-coded (for example 5000, 1500 and 1000 INR), and ageing recovery assumptions are fixed. Existing recommendations are returned unchanged, so evidence can become stale. These estimates need explicit assumptions and refresh/resolution behavior.
- **Scheduling:** automation rules are seeded and can be run via API, but no running scheduler or deployment worker is wired up.
- **Deployment and migrations:** startup uses `create_all`; no Alembic migration setup or revision history is present. Docker Compose includes database/API but no frontend hosting or reverse proxy. PostgreSQL backup/restore helpers explicitly defer to external tools.
- **Security hardening:** bootstrap accepts owner creation without out-of-band verification; MFA can be disabled by bootstrap input. TOTP secrets are plain database fields. Audit/ledger append-only behavior is a coding convention rather than a database-enforced guarantee in the inspected code. Production readiness requires validating these choices against the intended threat model.
- **Dependency reproducibility:** frontend has a committed lockfile; Python requirements use lower bounds without a lock. The README assumes dependencies and virtual environment already exist and omits a complete first-install workflow.

## Recommended development order

1. **Protect business data and stock:** endpoint/field authorization audit; fix location leakage and dispatch replay; regression tests for each.
2. **Make operations reliable:** assembly reservations/locking, returns lifecycle and replay rules, transaction boundaries, concurrent approval/payment checks, PostgreSQL verification.
3. **Finish the main warehouse journey:** receipt → assembly → dispatch → return inspection → owner approval, including evidence uploads and employee task completion.
4. **Complete procurement and finance screens:** suppliers, POs, invoices, payments, sales and reconciliation; validate with representative business records.
5. **Implement external integrations:** establish report formats and SKU/order mapping first, then provider-specific authentication, sync cursors/retries and BUSY format verification.
6. **Prepare deployment:** migrations, pinned Python dependencies, CI, secrets/bootstrap configuration, frontend hosting, job scheduling and tested backup restoration.

## Local startup for subsequent development

Dependencies were installed during this review. From the checkout:

```sh
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```sh
cd frontend
npm run dev
```

The UI is at `http://localhost:5173`; development API docs are at `http://localhost:8000/api/docs`. An empty database opens the one-time owner setup. Configuration loads `.env` relative to the backend process's working directory, so place a local configuration there when needed. The example file lives at the repository root.

`backend/scripts/seed_mvp.py` is available for a disposable demo database. It creates fixed example credentials and disables MFA for that demo owner; keep it restricted to local sample data. This review's seeded/reproduction databases were temporary and did not populate a persistent business database.

No deployment, remote push, live provider connection or application fixes were performed in this analysis pass.
