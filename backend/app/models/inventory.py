from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.security import utcnow


class SKU(Base):
    __tablename__ = "skus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)  # WATER_PUMP | ACCESSORY | SPARE_PART | BUNDLE | PACKAGING
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)  # FINISHED_GOOD | COMPONENT | BUNDLE | PACKAGING
    specifications_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    variant_label: Mapped[str | None] = mapped_column(String(80), nullable=True)

    purchase_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    mrp: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    hsn_code: Mapped[str] = mapped_column(String(16), default="8413", nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("18.00"), nullable=False)  # 0,5,12,18,28
    dimensions_cm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    weight_grams: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    warranty_eligible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reorder_point: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    safety_stock: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    primary_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)

    amazon_asin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amazon_sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    flipkart_fsn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    flipkart_sku: Mapped[str | None] = mapped_column(String(64), nullable=True)

    strategic_role: Mapped[str] = mapped_column(
        String(32), default="CORE", nullable=False
    )  # HIGH_VOL_LOW_MARGIN | LOW_VOL_HIGH_MARGIN | CUSTOMER_ACQUISITION | HIGH_PROFIT | CORE
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # WAREHOUSE | RECEIVING | AMAZON_FC | FLIPKART_FC | IN_TRANSIT | RETURNS_AREA | DAMAGED | SUPPLIER_RETURN
    zone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rack: Mapped[str | None] = mapped_column(String(32), nullable=True)
    shelf: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bin_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fc_receiving_delay_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_sellable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class InventoryBatch(Base):
    __tablename__ = "inventory_batches"
    __table_args__ = (
        CheckConstraint("remaining_qty >= 0", name="ck_batch_remaining_nonneg"),
        CheckConstraint("reserved_qty >= 0", name="ck_batch_reserved_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False, index=True)
    origin_batch_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_batches.id"), nullable=True)

    # Original inbound receipt date — preserved across transfers and partial sales
    inbound_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    initial_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    damaged_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warranty_reserved_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    sold_first_15d_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # OPENING | PO_RECEIPT | TRANSFER | ASSEMBLY | RETURN
    source_ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BatchGenealogy(Base):
    __tablename__ = "batch_genealogy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bundle_batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False, index=True)
    component_batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False, index=True)
    component_sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    consumed_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    component_inbound_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_type: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )  # PURCHASE_ORDER | SUPPLIER_PAYMENT | INVENTORY_ADJUSTMENT | BOM_CHANGE | SUBSTITUTION | WARRANTY_REPLACEMENT | RESTRICTED_MOVEMENT | PERMISSION_CHANGE | PRICE_CHANGE
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)  # PENDING | APPROVED | REJECTED
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    problem_summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    financial_impact_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    proposed_action_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    responsible_person: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_method: Mapped[str | None] = mapped_column(String(200), nullable=True)

    target_entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_entity_id: Mapped[str] = mapped_column(String(64), nullable=False)

    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InventoryLedger(Base):
    __tablename__ = "inventory_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    tx_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False, index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_batches.id"), nullable=True)
    qty_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(48), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approval_requests.id"), nullable=True)
    evidence_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class BOM(Base):
    __tablename__ = "boms"
    __table_args__ = (UniqueConstraint("bundle_sku_id", "version", name="uq_bom_bundle_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bundle_sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT_PENDING_APPROVAL", nullable=False)  # DRAFT_PENDING_APPROVAL | ACTIVE | ARCHIVED
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BOMItem(Base):
    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id", ondelete="CASCADE"), nullable=False, index=True)
    component_sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    qty_required: Mapped[int] = mapped_column(Integer, nullable=False)
    allow_substitution: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    substitute_sku_id: Mapped[int | None] = mapped_column(ForeignKey("skus.id"), nullable=True)


class AssemblyOrder(Base):
    __tablename__ = "assembly_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id"), nullable=False)
    bundle_sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    component_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    target_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    planned_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_produced_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wastage_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="RESERVED", nullable=False)  # RESERVED | IN_PROGRESS | COMPLETED | CANCELLED
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CycleCount(Base):
    __tablename__ = "cycle_counts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    count_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", nullable=False)  # OPEN | SUBMITTED | APPROVED | CLOSED
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CycleCountLine(Base):
    __tablename__ = "cycle_count_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_count_id: Mapped[int] = mapped_column(ForeignKey("cycle_counts.id", ondelete="CASCADE"), nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    system_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    counted_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variance_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approval_requests.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
