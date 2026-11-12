from datetime import datetime
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import OWNER_ONLY_ACTIONS, get_current_user, record_audit, require_action, require_owner
from app.core.security import utcnow
from app.models.auth import AuditLog, PermissionProfile, User, UserSession
from app.models.operations import EmployeeTask
from app.services.auth_service import build_access_preview, create_employee

router = APIRouter(prefix="/api/v1", tags=["employees-permissions"])


class CreateEmployeeIn(BaseModel):
    employee_code: str
    full_name: str
    pin: str
    mobile: str | None = None
    department: str = "Warehouse"
    preferred_language: str = "en"
    visible_pages: list[str] = ["warehouse", "inventory"]
    accessible_location_ids: list[int] = []
    editable_fields: dict[str, list[str]] = {"warehouse": ["counted_qty", "condition", "notes"]}
    allowed_actions: list[str] = ["inventory.view", "task.view_own", "task.complete"]
    can_export: bool = False


class UpdatePermissionsIn(BaseModel):
    visible_pages: list[str]
    accessible_location_ids: list[int]
    editable_fields: dict[str, list[str]]
    allowed_actions: list[str]
    can_export: bool = False
    is_active: bool = True
    preferred_language: str | None = None


class CreateTaskIn(BaseModel):
    task_type: str
    title: str
    instructions: str = ""
    assigned_to_id: int
    location_id: int | None = None
    deadline_at: datetime | None = None
    evidence_required: bool = False


class CompleteTaskIn(BaseModel):
    completion_notes: str = ""
    evidence_storage_key: str | None = None


@router.get("/permissions/employees")
def list_employees(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    emps = db.query(User).filter(User.role == "EMPLOYEE").order_by(User.id.asc()).all()
    return [
        {
            "id": e.id,
            "employee_code": e.employee_code,
            "full_name": e.full_name,
            "department": e.department,
            "preferred_language": e.preferred_language,
            "is_active": e.is_active,
        }
        for e in emps
    ]


@router.post("/permissions/employees")
def api_create_employee(payload: CreateEmployeeIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    # Reject attempts to grant owner-only actions
    bad_actions = set(payload.allowed_actions) & OWNER_ONLY_ACTIONS
    if bad_actions:
        raise HTTPException(status_code=400, detail=f"Owner-only actions cannot be granted to employees: {sorted(bad_actions)}")
    emp = create_employee(db, owner, **payload.model_dump())
    return build_access_preview(db, emp.id)


@router.get("/permissions/employees/{employee_id}/preview")
def api_access_preview(employee_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    return build_access_preview(db, employee_id)


@router.put("/permissions/employees/{employee_id}")
def api_update_permissions(
    employee_id: int,
    payload: UpdatePermissionsIn,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    emp = db.query(User).filter(User.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if emp.role == "OWNER":
        raise HTTPException(status_code=403, detail="Owner permissions cannot be modified via employee permission endpoint")

    bad_actions = set(payload.allowed_actions) & OWNER_ONLY_ACTIONS
    if bad_actions:
        raise HTTPException(status_code=400, detail=f"Owner-only actions cannot be assigned: {sorted(bad_actions)}")

    profile = db.query(PermissionProfile).filter(PermissionProfile.user_id == emp.id).first()
    if not profile:
        profile = PermissionProfile(user_id=emp.id)
        db.add(profile)

    profile.visible_pages_json = payload.visible_pages
    profile.accessible_location_ids_json = payload.accessible_location_ids
    profile.editable_fields_json = payload.editable_fields
    profile.allowed_actions_json = payload.allowed_actions
    profile.can_export = payload.can_export
    profile.updated_by_id = owner.id

    emp.is_active = payload.is_active
    if payload.preferred_language in ("en", "hi", "pa"):
        emp.preferred_language = payload.preferred_language
    if not emp.is_active:
        db.query(UserSession).filter(UserSession.user_id == emp.id, UserSession.revoked_at.is_(None)).update(
            {"revoked_at": utcnow()}
        )

    db.commit()
    record_audit(
        db,
        actor=owner,
        action="permissions.update",
        resource_type="user",
        resource_id=str(emp.id),
        outcome="SUCCESS",
        details={"allowed_actions": payload.allowed_actions, "locations": payload.accessible_location_ids, "is_active": payload.is_active},
    )
    return build_access_preview(db, emp.id)


@router.get("/audit-logs")
def api_audit_logs(limit: int = 100, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "actor_id": r.actor_id,
            "actor_role": r.actor_role,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "outcome": r.outcome,
            "details_json": r.details_json,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/tasks")
def api_create_task(payload: CreateTaskIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    emp = db.query(User).filter(User.id == payload.assigned_to_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Assigned employee not found")
    task = EmployeeTask(
        task_code=f"TSK-{uuid.uuid4().hex[:8].upper()}",
        task_type=payload.task_type,
        title=payload.title,
        instructions=payload.instructions,
        assigned_to_id=payload.assigned_to_id,
        assigned_by_id=owner.id,
        location_id=payload.location_id,
        deadline_at=payload.deadline_at,
        evidence_required=payload.evidence_required,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    record_audit(db, actor=owner, action="task.assign", resource_type="employee_task", resource_id=str(task.id), outcome="SUCCESS")
    return task


@router.get("/tasks")
def api_list_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(EmployeeTask)
    if user.role != "OWNER":
        q = q.filter(EmployeeTask.assigned_to_id == user.id)
    rows = q.order_by(EmployeeTask.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "task_code": t.task_code,
            "task_type": t.task_type,
            "title": t.title,
            "instructions": t.instructions,
            "status": t.status,
            "assigned_to_id": t.assigned_to_id,
            "location_id": t.location_id,
            "evidence_required": t.evidence_required,
            "evidence_storage_key": t.evidence_storage_key,
            "completion_notes": t.completion_notes,
            "deadline_at": t.deadline_at.isoformat() if t.deadline_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in rows
    ]


@router.post("/tasks/{task_id}/submit")
def api_submit_task(
    task_id: int,
    payload: CompleteTaskIn,
    user: User = Depends(require_action("task.complete")),
    db: Session = Depends(get_db),
):
    task = db.query(EmployeeTask).filter(EmployeeTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if user.role != "OWNER" and task.assigned_to_id != user.id:
        raise HTTPException(status_code=403, detail="Cannot submit another employee's task")
    if task.status == "VERIFIED":
        raise HTTPException(status_code=409, detail="Verified task records cannot be silently modified")
    if task.evidence_required and not payload.evidence_storage_key:
        raise HTTPException(status_code=400, detail="Photo/document evidence is required for this task")

    task.status = "SUBMITTED"
    task.completion_notes = payload.completion_notes
    task.evidence_storage_key = payload.evidence_storage_key
    task.completed_at = utcnow()
    db.commit()
    record_audit(db, actor=user, action="task.submit", resource_type="employee_task", resource_id=str(task.id), outcome="SUCCESS")
    return {"id": task.id, "status": task.status}


@router.post("/tasks/{task_id}/verify")
def api_verify_task(task_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    task = db.query(EmployeeTask).filter(EmployeeTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = "VERIFIED"
    task.verified_by_id = owner.id
    db.commit()
    record_audit(db, actor=owner, action="task.verify", resource_type="employee_task", resource_id=str(task.id), outcome="SUCCESS")
    return {"id": task.id, "status": task.status}

