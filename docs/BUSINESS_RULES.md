# BOSS — Deterministic Business & Financial Rules

## 1. Inventory Classification & Ageing Rules
- **Inbound Date Preservation**: Every inbound batch records `inbound_date`. Transfers and partial sales preserve the original `inbound_date`.
- **Bundle Batch Genealogy Policy**: When components from multiple receipt batches are assembled into a bundle, `batch_genealogy` links the bundle batch to every consumed component batch. The bundle's effective ageing date defaults to the **earliest (`MIN`) `inbound_date` among its consumed component batches** (`bundle_ageing_policy = "OLDEST_COMPONENT"`), ensuring slow-moving component capital cannot be concealed by assembly.
- **Ageing Tiers (Configurable via `business_settings`, defaults below)**:
  - `0 – 30 days`: **Normal** — monitor velocity & expected sell-through.
  - `31 – 45 days`: **Red (High Priority)** — flag slow-moving stock, analyze causes, evaluate profit-safe corrective actions.
  - `46+ days`: **Critical** — escalate to Owner with blocked capital (₹), exposure, and prioritized recovery plan.
- **Early Indicator**: 15-day sell-through rate = `units_sold_within_15_days / initial_batch_qty`.
- **Corrective Action Guardrail**: Ageing alone MUST NEVER trigger automatic loss-making sales, forced liquidation, or price cuts. All price changes or promotional actions require expected positive cash/profit evaluation and Owner approval.

## 2. Stock Availability Invariants
- `physical_qty`: total physically present units in a location.
- `reserved_qty`: units locked for approved pending dispatches or assembly orders.
- `damaged_qty`: units classified as damaged (or in `DAMAGED` location).
- `warranty_reserved_qty`: units locked for warranty obligations.
- `in_transit_qty`: units in `IN_TRANSIT` shipments — **NEVER counted as immediately sellable (`available_qty`)**.
- `available_qty = max(0, physical_qty - reserved_qty - damaged_qty - warranty_reserved_qty)` for sellable warehouse/FC locations.

## 3. Warranty Reserve Rule
- For every active `warranty_eligible` SKU with positive eligible own-warehouse stock `S`:
  $$\text{Required Reserve} = \max\left(1,\; \lceil 0.02 \times S \rceil\right)$$
- Shortages (`actual_warranty_reserve < required_reserve`) automatically raise an operational alert.
- Every warranty replacement requires explicit **Owner Approval** (`WARRANTY_REPLACEMENT`).

## 4. Returns & Inspection SLA
- Physical receipt of a return starts a **48-hour (2-day) inspection SLA**.
- Overdue uninspected returns trigger automated escalation.
- Bundle returns are compared line-by-line against the approved active **BOM**, recording missing or damaged components individually.

## 5. Profitability, GST & Portfolio Roles
- All monetary calculations use `Decimal` (rounded `ROUND_HALF_UP` to 2 decimal places for INR).
- **GST Slabs**: `0%`, `5%`, `12%`, `18%`, `28%`.
  - Intra-state sale/purchase: split equally into `CGST` (`rate / 2`) + `SGST` (`rate / 2`).
  - Inter-state sale/purchase: `IGST` (`rate`).
- **Profit Layers**:
  - `Gross Profit = Net Revenue (ex-GST) - COGS`
  - `Contribution Profit = Gross Profit - Marketplace Fees - Outbound Logistics - Packaging Cost - Expected Return/Warranty Cost`
  - `Net Profit = Contribution Profit - Allocated Fixed Overheads - Financing/Interest Cost`
- **Strategic SKU Roles**: `HIGH_VOL_LOW_MARGIN`, `LOW_VOL_HIGH_MARGIN`, `CUSTOMER_ACQUISITION`, `HIGH_PROFIT`, `CORE`.
- **Return on Working Capital (ROWC)**:
  $$\text{Annualized ROWC} = \frac{\text{Expected Contribution Profit}}{\text{Capital Tied Up}} \times \frac{365}{\max(1, \text{Inventory Days} + \text{Settlement Days} - \text{Supplier Credit Days})}$$

## 6. Supplier Payment & Procurement Rules
- Every Purchase Order (`PO`) requires **Owner Approval** before issuance.
- Every Supplier Payment requires **Owner Approval** before release.
- **Target Payment Date**: `invoice_date + floor(0.75 * credit_days)` — alerts fire ahead of the 75% mark and escalate before contractual due date.

