import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import type { NavKey } from "../App";
import { IconBox, IconLayers, IconRupee, IconSpark } from "../components/Icons";
import { Lang, TRANSLATIONS } from "../i18n/translations";
import { formatINR } from "../utils/format";

interface CommandCentreData {
  sales_and_profitability: {
    order_count: number;
    revenue_ex_gst_inr: string;
    gross_profit_inr: string;
    contribution_profit_inr: string;
    net_profit_inr: string;
    gst: { output_gst_inr: string; input_gst_credit_inr: string; net_gst_payable_inr: string };
    by_channel: Record<string, { orders: number; revenue_inr: string; contribution_profit_inr: string }>;
  };
  inventory: {
    total_skus: number;
    stockout_risk_count: number;
    ageing_summary: Record<string, { units: number; value_inr: string }>;
  };
  financial_health: {
    cash_available_inr: string;
    inventory_valuation_inr: string;
    supplier_payables_inr: string;
    marketplace_claim_receivables_inr: string;
    cc_od_utilized_inr: string;
    cash_conversion_cycle: { dio_days: number; dso_days: number; dpo_days: number; ccc_days: number };
  };
  operations: {
    pending_tasks: number;
    delayed_or_lost_shipments: number;
    overdue_return_inspections: number;
    open_marketplace_discrepancies: number;
    warranty_reserve_shortages: number;
    pending_purchase_orders: number;
    open_ai_recommendations: number;
  };
  owner_approvals: Array<{
    id: number;
    request_type: string;
    title: string;
    problem_summary: string;
    financial_impact_inr: string;
    responsible_person: string | null;
    verification_method: string | null;
    created_at: string;
  }>;
}

export function CommandCentrePage({
  lang,
  ownerName,
  onNavigate,
}: {
  lang: Lang;
  ownerName: string;
  onNavigate: (tab: NavKey) => void;
}) {
  const t = TRANSLATIONS[lang];
  const [data, setData] = useState<CommandCentreData | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      setData(await api.request<CommandCentreData>("/api/v1/command-centre"));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function review(id: number, decision: "APPROVED" | "REJECTED") {
    setErr(null);
    setMsg(null);
    try {
      await api.request(`/api/v1/approvals/${id}/review`, {
        method: "POST",
        body: JSON.stringify({ decision, review_notes: `Reviewed via Command Centre (${decision})` }),
      });
      setMsg(`Approval #${id} ${decision}`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (err) return <div className="status-banner status-error">{err}</div>;
  if (!data) return <div className="card">Loading Command Centre...</div>;

  const s = data.sales_and_profitability;
  const f = data.financial_health;
  const age = data.inventory.ageing_summary;
  const firstName = ownerName.split(" ")[0];

  const channels = Object.entries(s.by_channel || {});
  const maxRev = Math.max(1, ...channels.map(([, v]) => Number(v.revenue_inr || 0)));

  const normalVal = Number(age.NORMAL?.value_inr || 0);
  const redVal = Number(age.RED?.value_inr || 0);
  const critVal = Number(age.CRITICAL?.value_inr || 0);
  const maxAgeVal = Math.max(1, normalVal, redVal, critVal);

  return (
    <div>
      <header className="page-hero">
        <div>
          <div className="eyebrow">My Business • Overview</div>
          <h2 className="page-title">Welcome, {firstName}.</h2>
          <p className="page-subtitle">
            Live verified pulse across Amazon India, Flipkart, and own warehouse operations.
          </p>
        </div>
        <span className="badge badge-normal">● Single-Business Ledger Active</span>
      </header>

      {msg && <div className="status-banner status-ok" role="status">{msg}</div>}

      <div className="kpi-grid">
        <div className="card-hero">
          <div className="kpi-head">
            <div className="metric-label">{t.contributionProfit}</div>
            <div className="kpi-icon-box"><IconRupee size={15} /></div>
          </div>
          <div className="metric-value">{formatINR(s.contribution_profit_inr)}</div>
          <div className="metric-divider">
            <span>{s.order_count} orders</span>
            <span>Gross {formatINR(s.gross_profit_inr)}</span>
          </div>
        </div>

        <div className="card">
          <div className="kpi-head">
            <div className="metric-label">Cash Available</div>
            <div className="kpi-icon-box"><IconRupee size={15} /></div>
          </div>
          <div className="metric-value">{formatINR(f.cash_available_inr)}</div>
          <div className="metric-divider">
            <span>Payables {formatINR(f.supplier_payables_inr)}</span>
            <span>CCC {f.cash_conversion_cycle.ccc_days}d</span>
          </div>
        </div>

        <div className="card">
          <div className="kpi-head">
            <div className="metric-label">Stock Valuation</div>
            <div className="kpi-icon-box"><IconBox size={15} /></div>
          </div>
          <div className="metric-value">{formatINR(f.inventory_valuation_inr)}</div>
          <div className="metric-divider">
            <span>{data.inventory.total_skus} SKUs</span>
            <span>46d+ {formatINR(age.CRITICAL?.value_inr)}</span>
          </div>
        </div>

        <div className="card">
          <div className="kpi-head">
            <div className="metric-label">Pending Actions</div>
            <div className="kpi-icon-box"><IconSpark size={15} /></div>
          </div>
          <div className="metric-value">
            {data.operations.open_marketplace_discrepancies + data.operations.overdue_return_inspections + data.owner_approvals.length}
          </div>
          <div className="metric-divider">
            <span>{data.owner_approvals.length} approvals</span>
            <span>{data.operations.open_marketplace_discrepancies} claims</span>
          </div>
        </div>
      </div>

      <section className="shortcut-grid" aria-label="Operational Shortcuts">
        <button type="button" className="tile-btn" onClick={() => onNavigate("inventory")}>
          <IconBox />
          <span>Warehouse & Stock</span>
        </button>
        <button type="button" className="tile-btn" onClick={() => onNavigate("assembly")}>
          <IconLayers />
          <span>BOM & Returns</span>
        </button>
        <button type="button" className="tile-btn" onClick={() => onNavigate("marketplaces")}>
          <IconRupee />
          <span>Marketplaces & GST</span>
        </button>
        <button type="button" className="tile-btn" onClick={() => onNavigate("intelligence")}>
          <IconSpark />
          <span>AI & Automation ({data.operations.open_ai_recommendations})</span>
        </button>
      </section>

      <div className="card-grid">
        <section className="card">
          <div className="eyebrow">Channel Mix</div>
          <h3>Sales Revenue by Channel</h3>
          {channels.length === 0 ? (
            <p className="metric-foot">No sales orders recorded yet.</p>
          ) : (
            <div className="pulse-bars">
              {channels.map(([ch, vals]) => {
                const pct = Math.max(12, Math.round((Number(vals.revenue_inr) / maxRev) * 100));
                return (
                  <div className="pulse-col" key={ch}>
                    <div style={{ fontSize: "0.78rem", fontWeight: 700 }}>{formatINR(vals.revenue_inr)}</div>
                    <div className="pulse-track">
                      <div className={`pulse-fill ${ch === "FLIPKART" ? "amber" : ""}`} style={{ height: `${pct}%` }} />
                    </div>
                    <div style={{ fontSize: "0.74rem", fontWeight: 600, color: "var(--muted)" }}>{ch}</div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="card">
          <div className="eyebrow">Capital Ageing Pulse</div>
          <h3>30 / 45 / 46+ Day Exposure</h3>
          <div className="pulse-bars">
            {[
              { label: "0–30d Normal", val: normalVal, cls: "" },
              { label: "31–45d Red", val: redVal, cls: "amber" },
              { label: "46d+ Critical", val: critVal, cls: "crimson" },
            ].map((b) => {
              const pct = b.val === 0 ? 6 : Math.max(14, Math.round((b.val / maxAgeVal) * 100));
              return (
                <div className="pulse-col" key={b.label}>
                  <div style={{ fontSize: "0.78rem", fontWeight: 700 }}>{formatINR(b.val)}</div>
                  <div className="pulse-track">
                    <div className={`pulse-fill ${b.cls}`} style={{ height: `${pct}%` }} />
                  </div>
                  <div style={{ fontSize: "0.74rem", fontWeight: 600, color: "var(--muted)" }}>{b.label}</div>
                </div>
              );
            })}
          </div>
        </section>
      </div>

      <section className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBlockEnd: "0.75rem" }}>
          <div>
            <div className="eyebrow">Governance & Authority</div>
            <h3 style={{ margin: 0 }}>{t.pendingApprovals} ({data.owner_approvals.length})</h3>
          </div>
          <span className="badge badge-red">Owner Sign-off Required</span>
        </div>

        {data.owner_approvals.length === 0 ? (
          <p style={{ color: "var(--muted)", margin: 0 }}>All pending approvals are cleared.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {data.owner_approvals.map((a) => (
              <article key={a.id} className="card" style={{ background: "var(--surface-tint)", boxShadow: "none" }}>
                <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: "0.5rem", alignItems: "center" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                    <span className="badge badge-red">{a.request_type}</span>
                    <strong>{a.title}</strong>
                  </div>
                  <strong style={{ fontSize: "1.05rem", color: "var(--primary-deep)" }}>{formatINR(a.financial_impact_inr)}</strong>
                </div>
                <p style={{ marginBlock: "0.5rem", fontSize: "0.92rem" }}>{a.problem_summary}</p>
                <div className="metric-foot" style={{ marginBlockEnd: "0.75rem" }}>
                  Verification: {a.verification_method || "Owner check"} • Requested by: {a.responsible_person || "System"}
                </div>
                <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                  <button type="button" className="btn btn-primary" onClick={() => review(a.id, "APPROVED")}>{t.approve}</button>
                  <button type="button" className="btn btn-danger" onClick={() => review(a.id, "REJECTED")}>{t.reject}</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
