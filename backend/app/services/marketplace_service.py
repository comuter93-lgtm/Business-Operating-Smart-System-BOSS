import csv
import io
import json
from datetime import datetime
from decimal import Decimal
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import record_audit
from app.core.security import utcnow
from app.integrations.marketplaces import AmazonSPAPIAdapter, FlipkartSellerAdapter
from app.models.auth import User
from app.models.inventory import Location, SKU
from app.models.operations import DiscrepancyCase, MarketplaceIntegration, MarketplaceTransaction, ReturnCase
from app.services.inventory_service import _money, compute_stock_availability


def get_marketplace_statuses(db: Session) -> list[dict]:
    adapters = [AmazonSPAPIAdapter(), FlipkartSellerAdapter()]
    results = []
    for ad in adapters:
        st = ad.status()
        row = db.query(MarketplaceIntegration).filter(MarketplaceIntegration.channel == ad.channel).first()
        if not row:
            row = MarketplaceIntegration(channel=ad.channel, connection_status=st.connection_status)
            db.add(row)
            db.commit()
            db.refresh(row)
        else:
            row.connection_status = st.connection_status
            db.commit()
        results.append(
            {
                "channel": ad.channel,
                "configured": st.configured,
                "connection_status": st.connection_status,
                "message": st.message,
                "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
                "last_cursor": row.last_cursor,
                "last_error": row.last_error,
            }
        )
    return results


def import_marketplace_report(
    db: Session,
    actor: User,
    *,
    channel: str,
    records: list[dict],
    cursor: str | None = None,
) -> dict:
    """Controlled report importer. Always labels records as IMPORTED_REPORT and enforces idempotency."""
    if channel not in ("AMAZON_IN", "FLIPKART"):
        raise HTTPException(status_code=400, detail="Channel must be AMAZON_IN or FLIPKART")

    inserted = 0
    skipped_duplicates = 0
    errors = []

    for idx, rec in enumerate(records):
        ext_id = str(rec.get("external_tx_id", "")).strip()
        if not ext_id:
            errors.append({"row": idx, "error": "Missing external_tx_id"})
            continue
        if db.query(MarketplaceTransaction).filter(MarketplaceTransaction.external_tx_id == ext_id).first():
            skipped_duplicates += 1
            continue

        ext_sku = rec.get("external_sku")
        sku = None
        if ext_sku:
            sku = (
                db.query(SKU)
                .filter(
                    (SKU.sku_code == ext_sku)
                    | (SKU.amazon_sku == ext_sku)
                    | (SKU.flipkart_sku == ext_sku)
                    | (SKU.amazon_asin == ext_sku)
                    | (SKU.flipkart_fsn == ext_sku)
                )
                .first()
            )

        tx = MarketplaceTransaction(
            channel=channel,
            data_source="IMPORTED_REPORT",
            external_tx_id=ext_id,
            tx_type=rec.get("tx_type", "ORDER"),
            sku_id=sku.id if sku else None,
            external_sku=ext_sku,
            qty=int(rec.get("qty", 0)),
            gross_amount=_money(rec.get("gross_amount", 0)),
            marketplace_fee=_money(rec.get("marketplace_fee", 0)),
            gst_on_fee=_money(rec.get("gst_on_fee", 0)),
            net_settlement=_money(rec.get("net_settlement", 0)),
            raw_payload_json=rec,
        )
        db.add(tx)
        inserted += 1

    integ = db.query(MarketplaceIntegration).filter(MarketplaceIntegration.channel == channel).first()
    if not integ:
        integ = MarketplaceIntegration(channel=channel, connection_status="NOT_CONFIGURED")
        db.add(integ)
    integ.last_sync_at = utcnow()
    if cursor:
        integ.last_cursor = cursor

    db.commit()
    record_audit(
        db,
        actor=actor,
        action="marketplace.import_report",
        resource_type="marketplace_integration",
        resource_id=channel,
        outcome="SUCCESS",
        details={"inserted": inserted, "skipped_duplicates": skipped_duplicates, "data_source": "IMPORTED_REPORT"},
    )
    return {
        "channel": channel,
        "data_source": "IMPORTED_REPORT",
        "inserted": inserted,
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
        "last_cursor": integ.last_cursor,
    }


def parse_csv_report(csv_text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_text))
    return [dict(row) for row in reader]


def run_marketplace_reconciliation(db: Session, actor: User, channel: str | None = None) -> dict:
    """Compare marketplace transactions & FC stock against internal records to detect financial leakages."""
    q = db.query(MarketplaceTransaction).filter(MarketplaceTransaction.reconciled.is_(False))
    if channel:
        q = q.filter(MarketplaceTransaction.channel == channel)
    txs = q.all()

    cases_created = []
    for tx in txs:
        # 1. Settlement variance check: gross - fee - gst_on_fee != net_settlement (for ORDER/SETTLEMENT)
        if tx.tx_type in ("ORDER", "SETTLEMENT") and tx.gross_amount > Decimal("0.00"):
            expected_net = _money(tx.gross_amount - tx.marketplace_fee - tx.gst_on_fee)
            diff = _money(expected_net - tx.net_settlement)
            if diff > Decimal("1.00"):
                case = DiscrepancyCase(
                    case_code=f"DISC-{uuid.uuid4().hex[:8].upper()}",
                    channel=tx.channel,
                    discrepancy_type="SETTLEMENT_VARIANCE",
                    estimated_impact_inr=diff,
                    evidence_json={
                        "external_tx_id": tx.external_tx_id,
                        "expected_net": str(expected_net),
                        "actual_net": str(tx.net_settlement),
                        "data_source": tx.data_source,
                    },
                    marketplace_tx_id=tx.id,
                )
                db.add(case)
                cases_created.append(case)

        # 2. Unexplained high fee check (> 30% of gross without reimbursement)
        if tx.gross_amount > Decimal("0.00") and tx.marketplace_fee > (tx.gross_amount * Decimal("0.30")):
            excess = _money(tx.marketplace_fee - (tx.gross_amount * Decimal("0.22")))
            case = DiscrepancyCase(
                case_code=f"DISC-{uuid.uuid4().hex[:8].upper()}",
                channel=tx.channel,
                discrepancy_type="UNEXPLAINED_FEE",
                estimated_impact_inr=excess,
                evidence_json={"external_tx_id": tx.external_tx_id, "gross": str(tx.gross_amount), "fee": str(tx.marketplace_fee)},
                marketplace_tx_id=tx.id,
            )
            db.add(case)
            cases_created.append(case)

        # 3. Unreceived return check: marketplace RETURN tx with no matching physical return in BOSS
        if tx.tx_type == "RETURN" and tx.sku_id:
            matching_ret = (
                db.query(ReturnCase)
                .filter(ReturnCase.sku_id == tx.sku_id, ReturnCase.external_order_id == tx.raw_payload_json.get("order_id"))
                .first()
            )
            if not matching_ret or matching_ret.status in ("INITIATED", "EXPECTED"):
                sku = db.query(SKU).filter(SKU.id == tx.sku_id).first()
                impact = _money((sku.purchase_cost if sku else Decimal("0.00")) * Decimal(max(1, abs(tx.qty))))
                case = DiscrepancyCase(
                    case_code=f"DISC-{uuid.uuid4().hex[:8].upper()}",
                    channel=tx.channel,
                    discrepancy_type="UNRECEIVED_RETURN",
                    estimated_impact_inr=impact,
                    evidence_json={"external_tx_id": tx.external_tx_id, "sku_id": tx.sku_id, "qty": tx.qty},
                    marketplace_tx_id=tx.id,
                )
                db.add(case)
                cases_created.append(case)

        # 4. FC Inventory mismatch check
        if tx.tx_type == "FC_INVENTORY" and tx.sku_id:
            loc_type = "AMAZON_FC" if tx.channel == "AMAZON_IN" else "FLIPKART_FC"
            fc_locs = [l.id for l in db.query(Location).filter(Location.location_type == loc_type).all()]
            internal_fc_qty = sum(
                sum(r["marketplace_held_qty"] for r in compute_stock_availability(db, sku_id=tx.sku_id, location_id=lid))
                for lid in fc_locs
            )
            if internal_fc_qty > tx.qty:
                missing_qty = internal_fc_qty - tx.qty
                sku = db.query(SKU).filter(SKU.id == tx.sku_id).first()
                impact = _money(Decimal(missing_qty) * (sku.purchase_cost if sku else Decimal("0.00")))
                case = DiscrepancyCase(
                    case_code=f"DISC-{uuid.uuid4().hex[:8].upper()}",
                    channel=tx.channel,
                    discrepancy_type="MISSING_FC_INVENTORY",
                    estimated_impact_inr=impact,
                    evidence_json={"internal_fc_qty": internal_fc_qty, "reported_fc_qty": tx.qty, "missing_qty": missing_qty},
                    marketplace_tx_id=tx.id,
                )
                db.add(case)
                cases_created.append(case)

        tx.reconciled = True

    db.commit()
    record_audit(
        db,
        actor=actor,
        action="marketplace.reconcile",
        resource_type="discrepancy_case",
        outcome="SUCCESS",
        details={"transactions_checked": len(txs), "cases_created": len(cases_created)},
    )
    return {
        "transactions_checked": len(txs),
        "cases_created": len(cases_created),
        "cases": [{"id": c.id, "case_code": c.case_code, "type": c.discrepancy_type, "impact_inr": str(c.estimated_impact_inr)} for c in cases_created],
    }

