# BOSS — Business Operating Smart System

Full-stack, mobile-first, AI-assisted Business Operating Smart System built for a single Indian e-commerce & distribution business (water pumps, accessories, spare parts, and assembled bundles across Amazon India, Flipkart, offline sales, and BUSY Accounting).

## Implemented Scope (Phases 1–6)
- **Phase 1 — Secure Foundation**: Single verified Owner (`scrypt` + TOTP MFA + recovery codes), individual rate-limited Employee PIN accounts, revocable sessions, server-side RBAC + location IDOR protection, **Owner-Only Employee Access Preview** with exact runtime parity, and append-only `audit_logs`.
- **Phase 2 — Inventory & Warehouse**: Product master (finished goods, components, bundles, packaging), locations/bins (`IN_TRANSIT` excluded from sellable stock), idempotent append-only `inventory_ledger`, FIFO batch dispatch with concurrency locking, transfers preserving original `inbound_date`, configurable `0–30 Normal / 31–45 Red / 46+ Critical` ageing, and cycle counts with Owner approval.
- **Phase 3 — Assembly, Employees & Returns**: Versioned BOMs (Owner-approved changes), atomic assembly with component reservation & oldest-component `BatchGenealogy`, English/Hindi/Punjabi (`en`/`hi`/`pa`) mobile task workflows, returns with 48-hour SLA & BOM component checks, and `max(1, ceil(2%))` warranty reserve monitoring.
- **Phase 4 — Marketplace Operations**: Authorized Amazon SP-API & Flipkart Seller adapters (honestly reporting `NOT_CONFIGURED` until live credentials are supplied), controlled `IMPORTED_REPORT` CSV/JSON ingestion with idempotent cursor tracking, and reconciliation detecting settlement variances, unexplained fees, unreceived returns, and missing FC inventory.
- **Phase 5 — Finance, BUSY & Procurement**: Deterministic `Decimal` GST (`CGST+SGST` intra-state vs `IGST` inter-state across 0/5/12/18/28%), Gross vs Contribution vs Net Profit, BUSY XML voucher export bridge, suppliers, ROWC-ranked procurement recommendations (factoring FC receiving delays), Owner-approved POs, 75% credit-period payment targets, and duplicate-prevented Owner-approved supplier payments.
- **Phase 6 — Logistics, AI Intelligence & Automation**: Shipment & carrier reliability tracking, 7-field evidence-backed AI recommendations (`RECOMMENDATION_ONLY` start), rules-based Automation Engine with `automation_runs` logging, and verified SQLite/PostgreSQL backup & restore.
- **Phase 7 — Deferred**: Commercial SaaS multi-tenancy and billing are intentionally excluded.

## Quick Start (Local Development)

### Backend
```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm run dev
```

### Run Automated Verification
```bash
cd backend && .venv/bin/pytest -v
cd frontend && npm run build
```

## Documentation
- [ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [BUSINESS_RULES.md](docs/BUSINESS_RULES.md)
- [SECURITY_MODEL.md](docs/SECURITY_MODEL.md)
- [TESTING_PLAN.md](docs/TESTING_PLAN.md)

