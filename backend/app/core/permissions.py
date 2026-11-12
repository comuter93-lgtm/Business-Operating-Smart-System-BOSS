from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import ensure_utc, hash_session_token, utcnow
from app.models.auth import AuditLog, PermissionProfile, User, UserSession
from app.models.inventory import Location
from app.models.operations import EmployeeTask


ALL_PAGES = [
    "command_centre",
    "inventory",
    "warehouse",
    "assembly",
    "returns",
    "marketplaces",
    "procurement",
    "finance",
    "employees",
    "logistics",
    "intelligence",
    "settings",
]

ALL_ACTIONS = [
    "sku.view",
    "sku.create",
    "inventory.view",
    "receipt.create",
    "dispatch.reserve",
    "dispatch.commit",
    "transfer.create",
    "cycle_count.submit",
    "assembly.execute",
    "return.receive",
    "return.inspect",
    "task.view_own",
    "task.complete",
    "shipment.update",
]

OWNER_ONLY_ACTIONS = {
    "approval.review",
    "po.approve",
    "payment.approve",
    "bom.approve",
    "adjustment.approve",
    "warranty.approve",
    "permission.manage",
    "finance.view",
    "settings.manage",
    "backup.manage",
}

bearer_scheme = HTTPBearer(auto_error=False)


def record_audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    outcome: str = "SUCCESS",
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        outcome=outcome,
        details_json=details or {},
        ip_address=ip_address,
    )
    db.add(entry)
    db.commit()
    return entry


@dataclass
class EffectiveAccess:
    user_id: int
    role: str
    visible_pages: list[str]
    accessible_location_ids: list[int]
    editable_fields: dict[str, list[str]]
    allowed_actions: list[str]
    can_export: bool
    assigned_tasks: list[dict[str, Any]]


def evaluate_employee_access(db: Session, user: User) -> EffectiveAccess:
    """Single authoritative permission evaluator used by BOTH RBAC enforcement and Owner Access Preview."""
    if user.role == "OWNER":
        all_loc_ids = [loc.id for loc in db.query(Location).all()]
        return EffectiveAccess(
            user_id=user.id,
            role="OWNER",
            visible_pages=list(ALL_PAGES),
            accessible_location_ids=all_loc_ids,
            editable_fields={"*": ["*"]},
            allowed_actions=list(ALL_ACTIONS) + sorted(OWNER_ONLY_ACTIONS),
            can_export=True,
            assigned_tasks=[],
        )

    profile = db.query(PermissionProfile).filter(PermissionProfile.user_id == user.id).first()
    tasks = (
        db.query(EmployeeTask)
        .filter(EmployeeTask.assigned_to_id == user.id, EmployeeTask.status.in_(["ASSIGNED", "IN_PROGRESS", "SUBMITTED"]))
        .order_by(EmployeeTask.created_at.desc())
        .all()
    )
    task_summaries = [
        {
            "id": t.id,
            "task_code": t.task_code,
            "task_type": t.task_type,
            "title": t.title,
            "status": t.status,
            "location_id": t.location_id,
            "deadline_at": t.deadline_at.isoformat() if t.deadline_at else None,
        }
        for t in tasks
    ]
    if not profile or not user.is_active:
        return EffectiveAccess(
            user_id=user.id,
            role=user.role,
            visible_pages=[],
            accessible_location_ids=[],
            editable_fields={},
            allowed_actions=[],
            can_export=False,
            assigned_tasks=task_summaries,
        )

    # Strip any owner-only actions even if tampered with in DB
    safe_actions = [a for a in (profile.allowed_actions_json or []) if a not in OWNER_ONLY_ACTIONS]
    safe_pages = [p for p in (profile.visible_pages_json or []) if p not in {"settings", "finance"}]

    return EffectiveAccess(
        user_id=user.id,
        role=user.role,
        visible_pages=safe_pages,
        accessible_location_ids=[int(x) for x in (profile.accessible_location_ids_json or [])],
        editable_fields=dict(profile.editable_fields_json or {}),
        allowed_actions=safe_actions,
        can_export=bool(profile.can_export),
        assigned_tasks=task_summaries,
    )


def _extract_token(request: Request, creds: HTTPAuthorizationCredentials | None) -> str | None:
    if creds and creds.credentials:
        return creds.credentials
    cookie_token = request.cookies.get("boss_session")
    if cookie_token:
        return cookie_token
    return None


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    raw_token = _extract_token(request, creds)
    if not raw_token:
        if not settings.boss_require_auth and settings.boss_env == "development":
            owner = db.query(User).filter(User.role == "OWNER", User.is_active.is_(True)).first()
            if owner:
                return owner
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    token_hash = hash_session_token(raw_token)
    sess = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
    if not sess or sess.revoked_at is not None or ensure_utc(sess.expires_at) <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")

    user = db.query(User).filter(User.id == sess.user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or not found")

    request.state.session_id = sess.id
    return user


def require_owner(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if user.role != "OWNER":
        record_audit(
            db,
            actor=user,
            action="owner_endpoint_denied",
            resource_type="route",
            resource_id=str(request.url.path),
            outcome="DENIED",
            details={"reason": "Owner authority required"},
            ip_address=request.client.host if request.client else None,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner authority required")
    return user


def require_action(action: str, location_id: int | None = None, export: bool = False):
    def _checker(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user.role == "OWNER":
            return user
        access = evaluate_employee_access(db, user)
        if action not in access.allowed_actions:
            record_audit(
                db,
                actor=user,
                action=action,
                resource_type="permission",
                outcome="DENIED",
                details={"reason": f"Missing action permission: {action}"},
                ip_address=request.client.host if request.client else None,
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission denied for action: {action}")
        if export and not access.can_export:
            record_audit(
                db,
                actor=user,
                action="export_denied",
                resource_type="export",
                outcome="DENIED",
                details={"action": action},
                ip_address=request.client.host if request.client else None,
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Export permission denied")
        if location_id is not None and location_id not in access.accessible_location_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Location access denied")
        return user

    return _checker


def assert_location_access(db: Session, user: User, location_id: int, ip_address: str | None = None) -> None:
    if user.role == "OWNER":
        return
    access = evaluate_employee_access(db, user)
    if location_id not in access.accessible_location_ids:
        record_audit(
            db,
            actor=user,
            action="location_access_denied",
            resource_type="location",
            resource_id=str(location_id),
            outcome="DENIED",
            details={"allowed_locations": access.accessible_location_ids},
            ip_address=ip_address,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Location access denied")

