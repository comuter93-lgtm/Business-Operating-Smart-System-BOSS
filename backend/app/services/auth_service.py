from datetime import timedelta
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import ALL_ACTIONS, ALL_PAGES, evaluate_employee_access, record_audit
from app.core.security import (
    ensure_utc,
    generate_recovery_codes,
    generate_session_token,
    generate_totp_secret,
    hash_secret,
    session_expiry,
    totp_provisioning_uri,
    utcnow,
    verify_secret,
    verify_totp,
)
from app.models.auth import BusinessSettings, PermissionProfile, User, UserSession
from app.models.inventory import Location


def ensure_default_settings(db: Session) -> BusinessSettings:
    bs = db.query(BusinessSettings).first()
    if not bs:
        bs = BusinessSettings(
            business_name=settings.boss_business_name,
            gstin=settings.boss_gstin,
            home_state=settings.boss_home_state,
        )
        db.add(bs)
        db.commit()
        db.refresh(bs)
    return bs


def bootstrap_owner(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    mobile: str | None = None,
    enable_mfa: bool = True,
) -> dict:
    existing_owner = db.query(User).filter(User.role == "OWNER").first()
    if existing_owner:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An Owner account already exists. Single-business deployment allows only one Owner.",
        )
    if len(password) < 10:
        raise HTTPException(status_code=400, detail="Owner password must be at least 10 characters")

    ensure_default_settings(db)
    totp_secret = generate_totp_secret() if enable_mfa else None
    plain_recovery, hashed_recovery = generate_recovery_codes(6)

    owner = User(
        role="OWNER",
        email=email.strip().lower(),
        mobile=mobile,
        full_name=full_name.strip(),
        preferred_language="en",
        department="Executive",
        password_hash=hash_secret(password),
        totp_secret=totp_secret,
        mfa_enabled=enable_mfa,
        recovery_codes_json=hashed_recovery,
        is_active=True,
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)

    record_audit(
        db,
        actor=owner,
        action="owner.bootstrap",
        resource_type="user",
        resource_id=str(owner.id),
        outcome="SUCCESS",
        details={"email": owner.email, "mfa_enabled": enable_mfa},
    )
    return {
        "owner": owner,
        "totp_secret": totp_secret,
        "totp_uri": totp_provisioning_uri(totp_secret, owner.email) if totp_secret else None,
        "recovery_codes": plain_recovery,
    }


def _check_lockout(user: User) -> None:
    locked_until = ensure_utc(user.locked_until)
    if locked_until and locked_until > utcnow():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account temporarily locked until {locked_until.isoformat()} due to failed attempts",
        )


def _record_failed_attempt(db: Session, user: User, ip_address: str | None) -> None:
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= settings.login_max_attempts:
        user.locked_until = utcnow() + timedelta(minutes=settings.login_lockout_minutes)
    db.commit()
    record_audit(
        db,
        actor=user,
        action="auth.login_failed",
        resource_type="user",
        resource_id=str(user.id),
        outcome="DENIED",
        details={"attempts": user.failed_login_attempts},
        ip_address=ip_address,
    )


def _create_session(db: Session, user: User, ip_address: str | None, user_agent: str | None) -> tuple[str, UserSession]:
    raw_token, token_hash = generate_session_token()
    sess = UserSession(
        user_id=user.id,
        token_hash=token_hash,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:250],
        expires_at=session_expiry(settings.boss_session_ttl_hours),
    )
    user.failed_login_attempts = 0
    user.locked_until = None
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return raw_token, sess


def login_owner(
    db: Session,
    *,
    email: str,
    password: str,
    totp_code: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    user = db.query(User).filter(User.email == email.strip().lower(), User.role == "OWNER").first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    _check_lockout(user)
    if not user.password_hash or not verify_secret(password, user.password_hash):
        _record_failed_attempt(db, user, ip_address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.mfa_enabled:
        if not totp_code or not user.totp_secret or not verify_totp(user.totp_secret, totp_code):
            _record_failed_attempt(db, user, ip_address)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid TOTP MFA code required")

    raw_token, sess = _create_session(db, user, ip_address, user_agent)
    record_audit(
        db,
        actor=user,
        action="auth.owner_login",
        resource_type="session",
        resource_id=str(sess.id),
        outcome="SUCCESS",
        ip_address=ip_address,
    )
    return {"token": raw_token, "user": user, "expires_at": sess.expires_at}


def login_employee(
    db: Session,
    *,
    employee_code: str,
    pin: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    user = db.query(User).filter(User.employee_code == employee_code.strip().upper(), User.role == "EMPLOYEE").first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid employee code or PIN")

    _check_lockout(user)
    if not user.pin_hash or not verify_secret(pin, user.pin_hash):
        _record_failed_attempt(db, user, ip_address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid employee code or PIN")

    raw_token, sess = _create_session(db, user, ip_address, user_agent)
    record_audit(
        db,
        actor=user,
        action="auth.employee_login",
        resource_type="session",
        resource_id=str(sess.id),
        outcome="SUCCESS",
        ip_address=ip_address,
    )
    return {"token": raw_token, "user": user, "expires_at": sess.expires_at}


def recover_owner_account(
    db: Session,
    *,
    email: str,
    recovery_code: str,
    new_password: str,
    ip_address: str | None = None,
) -> dict:
    user = db.query(User).filter(User.email == email.strip().lower(), User.role == "OWNER").first()
    if not user:
        raise HTTPException(status_code=404, detail="Owner account not found")
    if len(new_password) < 10:
        raise HTTPException(status_code=400, detail="New password must be at least 10 characters")

    matched_idx = None
    for idx, hashed in enumerate(user.recovery_codes_json or []):
        if verify_secret(recovery_code.strip().upper(), hashed):
            matched_idx = idx
            break
    if matched_idx is None:
        record_audit(
            db,
            actor=user,
            action="auth.recovery_failed",
            resource_type="user",
            resource_id=str(user.id),
            outcome="DENIED",
            ip_address=ip_address,
        )
        raise HTTPException(status_code=401, detail="Invalid recovery code")

    remaining = list(user.recovery_codes_json or [])
    remaining.pop(matched_idx)
    user.recovery_codes_json = remaining
    user.password_hash = hash_secret(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None

    # Revoke all active sessions on recovery
    db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).update(
        {"revoked_at": utcnow()}
    )
    db.commit()
    record_audit(
        db,
        actor=user,
        action="auth.owner_recovered",
        resource_type="user",
        resource_id=str(user.id),
        outcome="SUCCESS",
        ip_address=ip_address,
    )
    return {"status": "recovered", "remaining_recovery_codes": len(remaining)}


def revoke_session(db: Session, user: User, session_id: int | None = None, revoke_all: bool = False) -> int:
    q = db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
    if not revoke_all and session_id is not None:
        q = q.filter(UserSession.id == session_id)
    count = q.update({"revoked_at": utcnow()})
    db.commit()
    record_audit(
        db,
        actor=user,
        action="auth.session_revoked",
        resource_type="session",
        resource_id=str(session_id or "all"),
        outcome="SUCCESS",
        details={"revoked_count": count},
    )
    return count


def create_employee(
    db: Session,
    owner: User,
    *,
    employee_code: str,
    full_name: str,
    pin: str,
    mobile: str | None = None,
    department: str = "Warehouse",
    preferred_language: str = "en",
    visible_pages: list[str] | None = None,
    accessible_location_ids: list[int] | None = None,
    editable_fields: dict[str, list[str]] | None = None,
    allowed_actions: list[str] | None = None,
    can_export: bool = False,
) -> User:
    code = employee_code.strip().upper()
    if db.query(User).filter(User.employee_code == code).first():
        raise HTTPException(status_code=409, detail=f"Employee code {code} already exists")
    if len(pin) < 4 or not pin.isdigit():
        raise HTTPException(status_code=400, detail="Employee PIN must be at least 4 digits")
    if preferred_language not in ("en", "hi", "pa"):
        raise HTTPException(status_code=400, detail="Language must be en, hi, or pa")

    emp = User(
        role="EMPLOYEE",
        employee_code=code,
        full_name=full_name.strip(),
        mobile=mobile,
        department=department,
        preferred_language=preferred_language,
        pin_hash=hash_secret(pin),
        is_active=True,
    )
    db.add(emp)
    db.flush()

    profile = PermissionProfile(
        user_id=emp.id,
        visible_pages_json=visible_pages or ["warehouse", "inventory"],
        accessible_location_ids_json=accessible_location_ids or [],
        editable_fields_json=editable_fields or {"warehouse": ["counted_qty", "condition", "notes"]},
        allowed_actions_json=allowed_actions or ["inventory.view", "task.view_own", "task.complete"],
        can_export=can_export,
        updated_by_id=owner.id,
    )
    db.add(profile)
    db.commit()
    db.refresh(emp)

    record_audit(
        db,
        actor=owner,
        action="employee.create",
        resource_type="user",
        resource_id=str(emp.id),
        outcome="SUCCESS",
        details={"employee_code": code, "department": department},
    )
    return emp


def build_access_preview(db: Session, employee_id: int) -> dict:
    emp = db.query(User).filter(User.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if emp.role == "OWNER":
        raise HTTPException(status_code=400, detail="Access preview is for employee accounts")

    eff = evaluate_employee_access(db, emp)
    locs = (
        db.query(Location)
        .filter(Location.id.in_(eff.accessible_location_ids))
        .all()
        if eff.accessible_location_ids
        else []
    )
    return {
        "employee_id": emp.id,
        "employee_code": emp.employee_code,
        "full_name": emp.full_name,
        "department": emp.department,
        "is_active": emp.is_active,
        "preferred_language": emp.preferred_language,
        "visible_pages": eff.visible_pages,
        "accessible_location_ids": eff.accessible_location_ids,
        "accessible_locations": [{"id": l.id, "code": l.code, "name": l.name, "type": l.location_type} for l in locs],
        "editable_fields": eff.editable_fields,
        "allowed_actions": eff.allowed_actions,
        "assigned_tasks": eff.assigned_tasks,
        "can_export": eff.can_export,
        "available_pages_catalog": [p for p in ALL_PAGES if p not in ("settings", "finance")],
        "available_actions_catalog": ALL_ACTIONS,
    }

