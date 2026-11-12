import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { Lang, TRANSLATIONS } from "../i18n/translations";
import { formatINR } from "../utils/format";

export function IntelligenceLogisticsPage({ lang }: { lang: Lang }) {
  const t = TRANSLATIONS[lang];
  const [recs, setRecs] = useState<Array<Record<string, unknown>>>([]);
  const [shipments, setShipments] = useState<Array<Record<string, unknown>>>([]);
  const [runs, setRuns] = useState<Array<Record<string, unknown>>>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      const [r, s, ar] = await Promise.all([
        api.request<Array<Record<string, unknown>>>("/api/v1/intelligence/recommendations"),
        api.request<Array<Record<string, unknown>>>("/api/v1/logistics/shipments"),
        api.request<Array<Record<string, unknown>>>("/api/v1/automation/runs"),
      ]);
      setRecs(r);
      setShipments(s);
      setRuns(ar);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function runAutomation() {
    setErr(null);
    try {
      const res = await api.request<{ runs: Array<{ rule_code: string; status: string }> }>("/api/v1/automation/run", { method: "POST" });
      setMsg(`Automation cycle executed (${res.runs.length} rules).`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function triggerBackup() {
    setErr(null);
    try {
      const res = await api.request<{ backup_file: string }>("/api/v1/system/backup", { method: "POST" });
      setMsg(`Database backup created: ${res.backup_file}`);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div>
      <header className="page-hero">
        <div>
          <div className="eyebrow">Deterministic BI & Rules Engine</div>
          <h2 className="page-title">{t.intelligenceLogistics}</h2>
          <p className="page-subtitle">
            Recommendation-only AI intelligence backed strictly by verified ledger figures, plus shipment & backup controls.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
          <button type="button" className="btn btn-primary" onClick={runAutomation}>Run AI & Automation Cycle</button>
          <button type="button" className="btn btn-secondary" onClick={triggerBackup}>Create DB Backup</button>
        </div>
      </header>
      {err && <div className="status-banner status-error">{err}</div>}
      {msg && <div className="status-banner status-ok">{msg}</div>}

      <section className="card" style={{ marginBlockEnd: "1rem" }}>
        <div className="eyebrow">7-Field Structured Recommendations</div>
        <h3>AI Business Intelligence ({recs.length})</h3>
        {recs.length === 0 ? (
          <p className="metric-foot">Run AI & Automation Cycle to evaluate live business records.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {recs.map((r) => (
              <article key={String(r.id)} className="card" style={{ background: "var(--surface-tint)", boxShadow: "none" }}>
                <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
                  <span className="badge badge-red">{String(r.category)}</span>
                  <strong>Est. Impact: {formatINR(String(r.estimated_financial_impact_inr))} • Confidence: {Math.round(Number(r.confidence_score) * 100)}%</strong>
                </div>
                <p style={{ marginBlock: "0.45rem" }}><strong>Problem:</strong> {String(r.problem_identified)}</p>
                <p style={{ marginBlock: "0.35rem" }}><strong>Recommended Action:</strong> {String(r.recommended_action)}</p>
                <div className="metric-foot">
                  <strong>Expected Outcome:</strong> {String(r.expected_outcome)} •{" "}
                  <strong>Approval:</strong> {r.approval_required ? `Owner Required (${String(r.approval_type)})` : "Advisory / Low-Risk"}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="card-grid">
        <section className="card">
          <div className="eyebrow">Hub Logistics</div>
          <h3>Shipments ({shipments.length})</h3>
          {shipments.length === 0 ? (
            <p className="metric-foot">No active shipments recorded.</p>
          ) : (
            <div style={{ display: "grid", gap: "0.5rem" }}>
              {shipments.map((sh) => (
                <div key={String(sh.id)} className="card" style={{ background: "var(--surface-tint)", boxShadow: "none", padding: "0.75rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong>{String(sh.shipment_code)} ({String(sh.carrier)})</strong>
                    <span className="badge badge-normal">{String(sh.status)}</span>
                  </div>
                  <div className="metric-foot">Freight: {formatINR(String(sh.freight_cost))} • {String(sh.direction)}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <div className="eyebrow">Auditability</div>
          <h3>Automation Run History ({runs.length})</h3>
          {runs.length === 0 ? (
            <p className="metric-foot">No automation runs yet.</p>
          ) : (
            <div style={{ display: "grid", gap: "0.5rem" }}>
              {runs.map((rn) => (
                <div key={String(rn.id)} className="card" style={{ background: "var(--surface-tint)", boxShadow: "none", padding: "0.75rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong>Rule #{String(rn.rule_id)}</strong>
                    <span className={`badge ${rn.status === "SUCCESS" ? "badge-normal" : "badge-critical"}`}>{String(rn.status)}</span>
                  </div>
                  <div className="metric-foot">Trigger: {String(rn.trigger_source)} • Affected: {String(rn.affected_count)}</div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
