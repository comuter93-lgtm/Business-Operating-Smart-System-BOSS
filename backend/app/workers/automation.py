import uuid
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models.auth import User
from app.models.finance import AutomationRule, AutomationRun
from app.models.operations import EmployeeTask
from app.services.intelligence_service import generate_intelligence_recommendations
from app.services.returns_warranty_service import get_overdue_return_inspections


DEFAULT_RULES = [
    {
        "rule_code": "RULE_AGEING_MONITOR",
        "name": "Inventory Ageing 30/45/46+ Day Monitor & BI Refresh",
        "trigger_type": "SCHEDULED_OR_MANUAL",
        "conditions_json": {"red_days": 31, "critical_days": 46},
        "action_type": "GENERATE_RECOMMENDATIONS",
        "requires_owner_approval": False,
    },
    {
        "rule_code": "RULE_RETURN_SLA_TASK",
        "name": "Create Urgent Return Inspection Tasks (>48h SLA)",
        "trigger_type": "SCHEDULED_OR_MANUAL",
        "conditions_json": {"sla_hours": 48},
        "action_type": "CREATE_INSPECTION_TASK",
        "requires_owner_approval": False,
    },
]


def seed_default_automation_rules(db: Session) -> None:
    for r in DEFAULT_RULES:
        if not db.query(AutomationRule).filter(AutomationRule.rule_code == r["rule_code"]).first():
            db.add(AutomationRule(**r))
    db.commit()


def run_automation_cycle(db: Session, trigger_source: str = "MANUAL") -> dict:
    seed_default_automation_rules(db)
    owner = db.query(User).filter(User.role == "OWNER").first()
    first_emp = db.query(User).filter(User.role == "EMPLOYEE", User.is_active.is_(True)).first()
    rules = db.query(AutomationRule).filter(AutomationRule.is_enabled.is_(True)).all()
    results = []

    for rule in rules:
        try:
            affected = 0
            details: dict = {}
            if rule.action_type == "GENERATE_RECOMMENDATIONS":
                recs = generate_intelligence_recommendations(db)
                affected = len(recs)
                details = {"total_recommendations": affected}

            elif rule.action_type == "CREATE_INSPECTION_TASK":
                overdue = get_overdue_return_inspections(db)
                assignee = first_emp or owner
                if assignee and owner:
                    for rc in overdue:
                        ref_key = f"RET-SLA-{rc.id}"
                        # Idempotency: do not create duplicate tasks for the same overdue return
                        existing_task = db.query(EmployeeTask).filter(EmployeeTask.reference_id == ref_key).first()
                        if not existing_task:
                            db.add(
                                EmployeeTask(
                                    task_code=f"TSK-{uuid.uuid4().hex[:8].upper()}",
                                    task_type="RETURN_INSPECTION",
                                    title=f"URGENT: Inspect overdue return {rc.return_code}",
                                    instructions="Inspect physical condition, compare bundle parts with BOM, and attach photo evidence.",
                                    assigned_to_id=assignee.id,
                                    assigned_by_id=owner.id,
                                    location_id=rc.location_id,
                                    reference_type="RETURN_SLA",
                                    reference_id=ref_key,
                                    evidence_required=True,
                                )
                            )
                            affected += 1
                details = {"overdue_returns": len(overdue), "tasks_created": affected}

            rule.last_run_at = utcnow()
            run = AutomationRun(
                rule_id=rule.id,
                trigger_source=trigger_source,
                data_source="INTERNAL_LEDGER",
                status="SUCCESS",
                affected_count=affected,
                details_json=details,
            )
            db.add(run)
            db.commit()
            results.append({"rule_code": rule.rule_code, "status": "SUCCESS", "affected_count": affected, "details": details})
        except Exception as exc:
            db.rollback()
            run = AutomationRun(
                rule_id=rule.id,
                trigger_source=trigger_source,
                data_source="INTERNAL_LEDGER",
                status="ERROR",
                affected_count=0,
                error_message=str(exc),
            )
            db.add(run)
            db.commit()
            results.append({"rule_code": rule.rule_code, "status": "ERROR", "error": str(exc)})

    return {"runs": results}

