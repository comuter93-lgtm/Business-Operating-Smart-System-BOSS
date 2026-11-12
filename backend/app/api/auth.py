from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import evaluate_employee_access, get_current_user
from app.models.auth import User, UserSession
from app.services.auth_service import (
    bootstrap_owner,
    login_employee,
    login_owner,
    recover_owner_account,
    revoke_session,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class OwnerBootstrapIn(BaseModel):
    email: str
    password: str
    full_name: str
    mobile: str | None = None
    enable_mfa: bool = True


class OwnerLoginIn(BaseModel):
    email: str
    password: str
    totp_code: str | None = None


class EmployeeLoginIn(BaseModel):
    employee_code: str
    pin: str


class OwnerRecoverIn(BaseModel):
    email: str
    recovery_code: str
    new_password: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="boss_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=(settings.boss_env == "production"),
        max_age=settings.boss_session_ttl_hours * 3600,
    )


@router.get("/bootstrap-status")
def bootstrap_status(db: Session = Depends(get_db)):
    owner = db.query(User).filter(User.role == "OWNER").first()
    return {
        "owner_initialized": owner is not None,
        "owner_mfa_enabled": bool(owner.mfa_enabled) if owner else True,
    }


@router.post("/bootstrap-owner")
def api_bootstrap_owner(payload: OwnerBootstrapIn, db: Session = Depends(get_db)):
    res = bootstrap_owner(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        mobile=payload.mobile,
        enable_mfa=payload.enable_mfa,
    )
    return {
        "owner_id": res["owner"].id,
        "email": res["owner"].email,
        "mfa_enabled": res["owner"].mfa_enabled,
        "totp_secret": res["totp_secret"],
        "totp_uri": res["totp_uri"],
        "recovery_codes": res["recovery_codes"],
    }


@router.post("/owner/login")
def api_owner_login(payload: OwnerLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    res = login_owner(
        db,
        email=payload.email,
        password=payload.password,
        totp_code=payload.totp_code,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(response, res["token"])
    return {
        "access_token": res["token"],
        "token_type": "bearer",
        "expires_at": res["expires_at"].isoformat(),
        "user": {
            "id": res["user"].id,
            "role": res["user"].role,
            "full_name": res["user"].full_name,
            "email": res["user"].email,
            "preferred_language": res["user"].preferred_language,
        },
    }


@router.post("/employee/login")
def api_employee_login(payload: EmployeeLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    res = login_employee(
        db,
        employee_code=payload.employee_code,
        pin=payload.pin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(response, res["token"])
    access = evaluate_employee_access(db, res["user"])
    return {
        "access_token": res["token"],
        "token_type": "bearer",
        "expires_at": res["expires_at"].isoformat(),
        "user": {
            "id": res["user"].id,
            "role": res["user"].role,
            "employee_code": res["user"].employee_code,
            "full_name": res["user"].full_name,
            "department": res["user"].department,
            "preferred_language": res["user"].preferred_language,
        },
        "effective_access": access.__dict__,
    }


@router.post("/owner/recover")
def api_owner_recover(payload: OwnerRecoverIn, request: Request, db: Session = Depends(get_db)):
    return recover_owner_account(
        db,
        email=payload.email,
        recovery_code=payload.recovery_code,
        new_password=payload.new_password,
        ip_address=request.client.host if request.client else None,
    )


@router.get("/me")
def api_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access = evaluate_employee_access(db, user)
    return {
        "auth_mode": "enforced" if (settings.boss_require_auth or settings.boss_env != "development") else "local_preview_no_auth",
        "user": {
            "id": user.id,
            "role": user.role,
            "email": user.email,
            "employee_code": user.employee_code,
            "full_name": user.full_name,
            "department": user.department,
            "preferred_language": user.preferred_language,
        },
        "effective_access": access.__dict__,
    }


@router.post("/logout")
def api_logout(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sess_id = getattr(request.state, "session_id", None)
    revoke_session(db, user, session_id=sess_id, revoke_all=False)
    response.delete_cookie("boss_session")
    return {"status": "logged_out"}


@router.post("/revoke-all-sessions")
def api_revoke_all(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = revoke_session(db, user, revoke_all=True)
    response.delete_cookie("boss_session")
    return {"revoked_sessions": count}


@router.get("/sessions")
def api_list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = db.query(UserSession).filter(UserSession.user_id == user.id).order_by(UserSession.created_at.desc()).limit(20).all()
    return [
        {
            "id": s.id,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "expires_at": s.expires_at.isoformat(),
            "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
            "created_at": s.created_at.isoformat(),
        }
        for s in sessions
    ]

