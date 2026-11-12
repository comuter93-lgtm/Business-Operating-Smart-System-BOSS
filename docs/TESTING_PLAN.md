# BOSS — Testing & Acceptance Verification Plan

Every feature is verified via automated `pytest` integration tests (against real transactional DB sessions and FastAPI endpoints) plus frontend TypeScript strict compilation and UI build checks.

## Acceptance Test Matrix
1. **Auth, Session Security & Privilege Escalation**:
   - Owner login + TOTP MFA + session revocation + account recovery.
   - Employee PIN rate-limiting & lockout.
   - Employee blocked (`403`) from Owner endpoints, financial data, PO/payment approvals, permission edits, self-promotion, and IDOR access to unauthorized locations.
   - **Owner Access Preview Parity**: preview matches actual API allow/deny behavior across pages, locations, fields, actions, tasks, and exports.
2. **Inventory Ledger, Duplicate Prevention & Concurrency**:
   - Goods receipt -> location putaway -> dispatch reservation -> dispatch commit.
   - Duplicate `idempotency_key` returns original transaction without double-counting stock.
   - Concurrent stock dispatch / assembly respects available balance and prevents negative available stock.
   - `IN_TRANSIT` stock is excluded from `available_qty`.
3. **Batch-Level Inventory Ageing & Bundle Genealogy**:
   - 0–30 (`NORMAL`), 31–45 (`RED`), 46+ (`CRITICAL`) classification and 15-day sell-through calculation.
   - Transfers and partial sales preserve original `inbound_date`.
   - Assembled bundles inherit earliest component `inbound_date` via `batch_genealogy`.
   - Configurable ageing thresholds in `business_settings`.
4. **BOM, Assembly & Incomplete Returns**:
   - Shared components across bundles; BOM change requires Owner approval.
   - Atomic assembly deducts components and creates finished bundle; duplicate consumption blocked.
   - Partial/incomplete bundle return logs missing components against BOM and enforces 2-day inspection SLA alert.
   - 2% (`max(1, ceil(0.02 * S))`) warranty reserve calculation, shortage detection, and Owner-approved warranty replacement.
5. **Marketplace Integration & Reconciliation**:
   - Unconfigured live APIs report `NOT_CONFIGURED` (never fake live).
   - Controlled report imports tagged `IMPORTED_REPORT`; idempotent re-import prevention; interrupted sync recovery.
   - Detects missing FC stock, unreceived returns, unexplained fee deductions, settlement variances, and creates `DiscrepancyCase` with ₹ impact.
6. **Procurement, Profitability, GST, BUSY & Working Capital**:
   - PO and supplier payment require Owner approval; duplicate payment/PO prevented.
   - 75% supplier credit target payment alerts.
   - Accurate Gross, Contribution, and Net Profit with CGST+SGST vs IGST slabs (`0/5/12/18/28%`), distinguishing High-Vol/Low-Margin and Low-Vol/High-Margin SKUs.
   - BUSY export/import bridge & ROWC / CCC calculation.
7. **Logistics, AI Intelligence & Automation**:
   - FC receiving delay reflected in reorder lead time.
   - AI recommendations contain all 7 mandatory fields backed strictly by DB numbers.
   - Automation creates low-risk tasks/alerts with idempotency and never auto-commits financial/destructive actions.
8. **Zero SaaS Dependencies & Backup Restoration**:
   - Full suite runs offline/locally with zero external SaaS dependencies.
   - Database backup & restore helper verified with round-trip data integrity check.

