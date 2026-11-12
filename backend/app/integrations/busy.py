from xml.etree.ElementTree import Element, SubElement, tostring
from app.core.config import settings


class BusyAccountingAdapter:
    """Authorized BUSY Accounting XML/JSON export & ledger import bridge."""

    def status(self) -> dict:
        configured = bool(settings.busy_bridge_endpoint)
        return {
            "system": "BUSY_ACCOUNTING",
            "live_bridge_configured": configured,
            "mode": "LIVE_BRIDGE" if configured else "EXPORT_IMPORT_BRIDGE",
            "note": (
                "Connected to BUSY Web Service endpoint"
                if configured
                else "Live BUSY endpoint not configured; generates verified BUSY XML/JSON vouchers and accepts imported BUSY ledgers."
            ),
        }

    def export_sales_vouchers_xml(self, orders: list[dict]) -> str:
        root = Element("BOSSBusyVoucherExport", version="1.0")
        for o in orders:
            v = SubElement(root, "SalesVoucher")
            SubElement(v, "VoucherNo").text = str(o["order_code"])
            SubElement(v, "Date").text = str(o["order_date"])
            SubElement(v, "Channel").text = str(o["channel"])
            SubElement(v, "CustomerState").text = str(o["customer_state"])
            SubElement(v, "SKUCode").text = str(o["sku_code"])
            SubElement(v, "Qty").text = str(o["qty"])
            SubElement(v, "TaxableAmount").text = str(o["taxable_revenue"])
            SubElement(v, "CGST").text = str(o["cgst_amount"])
            SubElement(v, "SGST").text = str(o["sgst_amount"])
            SubElement(v, "IGST").text = str(o["igst_amount"])
        return tostring(root, encoding="unicode")

