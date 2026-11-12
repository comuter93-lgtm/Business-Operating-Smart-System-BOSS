from sqlalchemy.orm import Session

from app.models.finance import AIRecommendation, PurchaseOrder
from app.models.inventory import ApprovalRequest
from app.models.operations import DiscrepancyCase, EmployeeTask, Shipment
from app.services.finance_service import compute_profitability_summary, compute_working_capital_metrics
from app.services.inventory_service import compute_inventory_ageing_report, compute_stock_availability
from app.services.marketplace_service import get_marketplace_statuses
from app.services.returns_warranty_service import compute_warranty_reserve_status, get_overdue_return_inspections


def build_owner_command_centre(db: Session) -> dict:
    profitability = compute_profitability_summary(db)
    working_capital = compute_working_capital_metrics(db)
    ageing = compute_inventory_ageing_report(db)
    stock = compute_stock_availability(db)
    warranty = compute_warranty_reserve_status(db)
    overdue_returns = get_overdue_return_inspections(db)
    pending_approvals = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.status == "PENDING")
        .order_by(ApprovalRequest.created_at.desc())
        .all()
    )
    pending_tasks = db.query(EmployeeTask).filter(EmployeeTask.status.in_(["ASSIGNED", "IN_PROGRESS", "SUBMITTED"])).count()
    delayed_shipments = db.query(Shipment).filter(Shipment.status.in_(["DELAYED", "LOST_INVESTIGATION"])).count()
    open_discrepancies = db.query(DiscrepancyCase).filter(DiscrepancyCase.status == "OPEN").count()
    open_ai_recs = db.query(AIRecommendation).filter(AIRecommendation.status == "OPEN").count()
    pending_pos = db.query(PurchaseOrder).filter(PurchaseOrder.status == "PENDING_APPROVAL").count()

    stockout_risks = [s for s in stock if s["available_qty"] <= 5]

    return {
        "sales_and_profitability": profitability,
        "inventory": {
            "total_skus": len(stock),
            "stockout_risk_count": len(stockout_risks),
            "stockout_risks": stockout_risks,
            "ageing_summary": ageing["summary"],
            "thresholds": ageing["thresholds"],
        },
        "financial_health": working_capital,
        "operations": {
            "pending_tasks": pending_tasks,
            "delayed_or_lost_shipments": delayed_shipments,
            "overdue_return_inspections": len(overdue_returns),
            "open_marketplace_discrepancies": open_discrepancies,
            "warranty_reserve_shortages": len([w for w in warranty if w["shortage"] > 0]),
            "pending_purchase_orders": pending_pos,
            "open_ai_recommendations": open_ai_recs,
            "marketplace_statuses": get_marketplace_statuses(db),
        },
        "owner_approvals": [
            {
                "id": a.id,
                "request_type": a.request_type,
                "title": a.title,
                "problem_summary": a.problem_summary,
                "evidence_json": a.evidence_json,
                "financial_impact_inr": str(a.financial_impact_inr),
                "proposed_action_json": a.proposed_action_json,
                "responsible_person": a.responsible_person,
                "verification_method": a.verification_method,
                "created_at": a.created_at.isoformat(),
            }
            for a in pending_approvals
        ],
    }

