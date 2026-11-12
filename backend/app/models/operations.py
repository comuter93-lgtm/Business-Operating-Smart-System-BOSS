from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.security import utcnow


class EmployeeTask(Base):
    __tablename__ = "employee_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)  # RECEIPT | PUTAWAY | PICK_PACK | ASSEMBLY | RETURN_INSPECTION | CYCLE_COUNT | DISPATCH
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ASSIGNED", nullable=False, index=True)  # ASSIGNED | IN_PROGRESS | SUBMITTED | VERIFIED | REJECTED

    assigned_to_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    assigned_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ReturnCase(Base):
    __tablename__ = "return_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)  # AMAZON | FLIPKART | OFFLINE
    external_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(24), default="INITIATED", nullable=False, index=True)  # INITIATED | EXPECTED | RECEIVED | INSPECTED | CLASSIFIED | CLOSED
    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inspection_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inspected_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)  # RESALABLE | USED | DAMAGED | INCOMPLETE | UNDER_INVESTIGATION
    missing_components_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    recovery_status: Mapped[str] = mapped_column(String(32), default="NONE", nullable=False)  # NONE | CLAIM_FILED | REIMBURSED | SUPPLIER_CREDIT | WRITTEN_OFF
    estimated_loss_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    recovered_amount_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    evidence_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class WarrantyClaim(Base):
    __tablename__ = "warranty_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    customer_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    serial_or_batch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue_description: Mapped[str] = mapped_column(Text, nullable=False)
    replacement_qty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING_APPROVAL", nullable=False)  # PENDING_APPROVAL | APPROVED | REJECTED | FULFILLED
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approval_requests.id"), nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketplaceIntegration(Base):
    __tablename__ = "marketplace_integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # AMAZON_IN | FLIPKART
    connection_status: Mapped[str] = mapped_column(String(32), default="NOT_CONFIGURED", nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class MarketplaceTransaction(Base):
    __tablename__ = "marketplace_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # AMAZON_IN | FLIPKART
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)  # LIVE_API | IMPORTED_REPORT
    external_tx_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    tx_type: Mapped[str] = mapped_column(String(32), nullable=False)  # ORDER | SHIPMENT | RETURN | SETTLEMENT | FEE | REIMBURSEMENT | FC_INVENTORY
    sku_id: Mapped[int | None] = mapped_column(ForeignKey("skus.id"), nullable=True)
    external_sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    marketplace_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    gst_on_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    net_settlement: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    tx_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    raw_payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    reconciled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DiscrepancyCase(Base):
    __tablename__ = "discrepancy_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    discrepancy_type: Mapped[str] = mapped_column(
        String(48), nullable=False
    )  # MISSING_FC_INVENTORY | UNRECEIVED_RETURN | UNEXPLAINED_FEE | SETTLEMENT_VARIANCE | DUPLICATE_TX | UNRESOLVED_REIMBURSEMENT
    status: Mapped[str] = mapped_column(String(24), default="OPEN", nullable=False)  # OPEN | SUBMITTED | RECOVERED | WRITTEN_OFF
    estimated_impact_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    recovered_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    marketplace_tx_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_transactions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)  # INBOUND_SUPPLIER | WAREHOUSE_TO_FC | OUTBOUND_CUSTOMER | RETURN_INBOUND
    channel: Mapped[str] = mapped_column(String(32), default="OFFLINE", nullable=False)
    carrier: Mapped[str] = mapped_column(String(80), nullable=False)
    tracking_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    origin_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    destination_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    freight_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    packaging_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="IN_TRANSIT", nullable=False)  # CREATED | IN_TRANSIT | DELAYED | DELIVERED | LOST_INVESTIGATION
    expected_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

