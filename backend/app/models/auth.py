from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.security import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # OWNER | EMPLOYEE
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    mobile: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    employee_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(5), default="en", nullable=False)  # en | hi | pa
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)

    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recovery_codes_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PermissionProfile(Base):
    __tablename__ = "permission_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    visible_pages_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    accessible_location_ids_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    editable_fields_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    allowed_actions_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    can_export: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # SUCCESS | DENIED | ERROR
    details_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class BusinessSettings(Base):
    __tablename__ = "business_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_name: Mapped[str] = mapped_column(String(150), nullable=False)
    gstin: Mapped[str] = mapped_column(String(20), nullable=False)
    home_state: Mapped[str] = mapped_column(String(10), nullable=False)

    # Ageing thresholds (defaults: 0-30 Normal, 31-45 Red, 46+ Critical)
    target_selling_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    red_age_days: Mapped[int] = mapped_column(Integer, default=31, nullable=False)
    critical_age_days: Mapped[int] = mapped_column(Integer, default=46, nullable=False)
    early_sell_through_days: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    bundle_ageing_policy: Mapped[str] = mapped_column(String(32), default="OLDEST_COMPONENT", nullable=False)

    # Warranty & returns policy
    warranty_reserve_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("2.00"), nullable=False)
    warranty_min_units: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    return_inspection_sla_hours: Mapped[int] = mapped_column(Integer, default=48, nullable=False)
    supplier_payment_target_pct: Mapped[int] = mapped_column(Integer, default=75, nullable=False)

    # Working capital & borrowing
    cash_available: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    cc_od_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    cc_od_utilized: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    cc_od_annual_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10.50"), nullable=False)
    monthly_fixed_overhead_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)

    ai_mode: Mapped[str] = mapped_column(String(32), default="RECOMMENDATION_ONLY", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

