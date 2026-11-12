# BOSS — Business Operating Smart System: System Architecture

## 1. Purpose & Scope (Phases 1–6)
BOSS is a private, single-business, mobile-first web application built for an Indian e-commerce & distribution business selling **water pumps, accessories, spare parts, and assembled bundles** across **Amazon India, Flipkart, and offline sales**, integrated with **BUSY Accounting**.

- **Architecture Pattern**: Maintainable Modular Monolith (single transactional database, strict service-layer boundaries, server-enforced RBAC, deterministic financial/inventory engines).
- **Phase 7 Exclusion**: Commercial multi-tenancy, subscription billing, and tenant onboarding are explicitly deferred to Phase 7 and omitted from Phases 1–6. Service interfaces remain clean and configuration-driven (`business_settings`) so future commercialization does not require rewriting core ledgers.

## 2. Technology Stack
| Layer | Choice | Rationale |
|---|---|---|
| Backend API | FastAPI (Python 3.11+) | Typed Pydantic v2 validation, async support, OpenAPI docs, `Decimal` precision for GST/INR finance |
| Database | PostgreSQL 16 (prod) / SQLite WAL (dev/test) | Transactional ACID compliance, strict FK constraints, immutable ledger patterns |
| ORM & Migrations | SQLAlchemy 2.0 + Alembic-compatible models | Single source of truth for schema across PostgreSQL and automated test suites |
| Frontend | React 19 + TypeScript + Vite | Mobile-first responsive UI, large touch targets, fast low-bandwidth bundle, `en`/`hi`/`pa` i18n |
| Security | `scrypt` password/PIN hashing, RFC 6238 TOTP MFA, HMAC-SHA256 revocable sessions, server-side RBAC | Zero external auth SaaS dependencies, full owner authority |
| Background Jobs | Modular Automation Engine (`workers/automation.py`) | Rules-based scheduling, idempotency keys, full `automation_runs` audit trail |
| Object Storage | Abstracted `StorageAdapter` (local encrypted/private disk + S3-compatible ready) | Safe evidence uploads (receipts, damaged returns, invoices) with path traversal protection |

## 3. Module Dependency Map (14 Operational Modules)
1. **Security, Permissions & Audit (`core/security.py`, `core/permissions.py`, `api/auth.py`, `api/permissions.py`)** — Foundation for all modules; enforces single Owner authority, Employee least privilege, Access Preview, and append-only `audit_logs`.
2. **Business Settings & Integrations (`api/settings.py`)** — Configurable thresholds (30/45/46d ageing, 75% supplier credit target, 2% warranty reserve, GSTIN/state, integration credentials status).
3. **Owner Command Centre (`services/command_centre.py`, `api/command_centre.py`)** — Aggregates live verified sales, profitability, stock health, financial obligations, operations queue, and unified Owner Approval Inbox.
4. **Inventory Management (`services/inventory.py`, `api/inventory.py`)** — Product master (individual, component, bundle, packaging), append-only `inventory_ledger`, stock availability breakdown, FIFO batch tracking, batch-level ageing.
5. **Warehouse Management (`services/warehouse.py`, `api/warehouse.py`)** — Mobile-first Goods Receipt, Putaway, Pick/Pack/Dispatch, Transfers, Cycle Counts, barcode/QR verification.
6. **Bill of Materials & Assembly (`services/assembly.py`, `api/assembly.py`)** — Versioned BOMs, owner-approved BOM changes/substitutions, atomic component reservation & consumption, wastage tracking, batch genealogy.
7. **Employee & Task Management (`services/employees.py`, `api/employees.py`)** — Individual employee accounts, smartphone task queues, evidence requirements, completion verification, `en`/`hi`/`pa` localization.
8. **Returns, Warranty & Claims (`services/returns.py`, `api/returns.py`)** — 2-day inspection SLA, BOM-verified bundle returns, condition classification, 2% warranty reserve tracking, owner-approved warranty replacements, marketplace/supplier recovery claims.
9. **Amazon & Flipkart Operations (`integrations/marketplaces.py`, `services/marketplace_reconciliation.py`)** — Authorized API adapter pattern + explicitly labeled CSV/JSON report imports, idempotent ingestion, discrepancy & missing-reimbursement detection.
10. **Procurement & Supplier Management (`services/procurement.py`, `api/procurement.py`)** — Supplier master, landed cost comparison, ROWC-aware purchase recommendations, owner-approved POs, 75% credit-period tracking.
11. **Financial Management & BUSY Accounting (`services/finance.py`, `integrations/busy.py`)** — Gross vs Contribution vs Net Profit, GST (CGST+SGST / IGST) accounting, BUSY XML/JSON export & ledger import bridge, owner-approved supplier payments.
12. **Working-Capital Optimization (`services/working_capital.py`)** — CCC (DIO + DSO - DPO), CC/OD interest tracking, blocked capital by ageing tier, ROWC opportunity ranking.
13. **Logistics & Shipment Management (`services/logistics.py`)** — Inbound/FC/outbound shipments, carrier tracking, freight cost comparison, FC receiving delay integration into planning, lost-shipment investigations.
14. **AI Business Intelligence & Automation Engine (`services/intelligence.py`, `workers/automation.py`)** — Deterministic rules + evidence-backed 7-field recommendations (recommendation-only start), non-destructive low-risk task automation, duplicate-prevention.

## 4. Phased Implementation Plan
- **Phase 1**: Core foundation, DB schema, Owner auth + MFA, Employee auth + rate limiting, server RBAC, Owner Access Preview, Audit log.
- **Phase 2**: SKU Master, Locations, Immutable Inventory Ledger, Stock Availability, Receipts, Dispatches, Transfers, Cycle Counts, Batch Ageing (0–30 / 31–45 / 46+ days).
- **Phase 3**: Versioned BOMs, Atomic Assembly & Genealogy, Employee Tasks & Multilingual UI, Returns Inspection (2-day SLA), 2% Warranty Reserve, Claims.
- **Phase 4**: Amazon India & Flipkart Adapters, Controlled Report Importer (`IMPORTED_REPORT` vs `LIVE_API`), Marketplace Reconciliation & Discrepancy Cases.
- **Phase 5**: Suppliers & Landed Cost, Owner-Approved POs, Deterministic GST/Profitability Engine, BUSY Accounting Bridge, 75% Supplier Credit Payments, Working Capital & ROWC.
- **Phase 6**: Logistics & FC Delay Planning, AI Business Intelligence (7-field structured recommendations), Automation Engine, Full E2E + Security + Concurrency Verification.

