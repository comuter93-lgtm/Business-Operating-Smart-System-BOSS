import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { Lang, TRANSLATIONS } from "../i18n/translations";
import { formatINR } from "../utils/format";

export function MarketplacesFinancePage({ lang }: { lang: Lang }) {
  const t = TRANSLATIONS[lang];
  const [statuses, setStatuses] = useState<Array<Record<string, unknown>>>([]);
  const [discrepancies, setDiscrepancies] = useState<Array<Record<string, unknown>>>([]);
  const [profitability, setProfitability] = useState<Record<string, unknown> | null>(null);
  const [procRecs, setProcRecs] = useState<Array<Record<string, unknown>>>([]);
  const [busyExport, setBusyExport] = useState<string | null>(null);
  const [csvText, setCsvText] = useState("external_tx_id,tx_type,external_sku,qty,gross_amount,marketplace_fee,gst_on_fee,net_settlement\n");
  const [channel, setChannel] = useState<"AMAZON_IN" | "FLIPKART">("AMAZON_IN");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      const [st, dc, pr, recs] = await Promise.all([
        api.request<Array<Record<string, unknown>>>("/api/v1/marketplaces/status"),
        api.request<Array<Record<string, unknown>>>("/api/v1/marketplaces/discrepancies"),
        api.request<Record<string, unknown>>("/api/v1/finance/profitability"),
        api.request<Array<Record<string, unknown>>>("/api/v1/procurement/recommendations"),
      ]);
      setStatuses(st);
      setDiscrepancies(dc);
      setProfitability(pr);
      setProcRecs(recs);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function importCsv(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    try {
      const res = await api.request<{ inserted: number; skipped_duplicates: number; data_source: string }>("/api/v1/marketplaces/import-report", {
        method: "POST",
        body: JSON.stringify({ channel, csv_text: csvText }),
      });
      const rec = await api.request<{ cases_created: number }>(`/api/v1/marketplaces/reconcile?channel=${channel}`, { method: "POST" });
      setMsg(`Imported ${res.inserted} (${res.data_source}), skipped ${res.skipped_duplicates} duplicates; created ${rec.cases_created} discrepancy case(s).`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function runBusyExport() {
    setErr(null);
    try {
      const res = await api.request<{ export_ref: string; record_count: number; xml: string }>("/api/v1/finance/busy/export", { method: "POST" });
      setBusyExport(`Ref ${res.export_ref} (${res.record_count} vouchers):\n${res.xml}`);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div>
      <header className="page-hero">
        <div>
          <div className="eyebrow">Channels, GST & Procurement ROWC</div>
          <h2 className="page-title">{t.marketplacesFinance}</h2>
          <p className="page-subtitle">
            Reconciliation across Amazon India & Flipkart, deterministic GST profit tracking, and BUSY Accounting export.
          </p>
        </div>
      </header>
      {err && <div className="status-banner status-error">{err}</div>}
      {msg && <div className="status-banner status-ok">{msg}</div>}

      <div className="card-grid">
        {profitability && (
          <div className="card-hero">
            <div className="metric-label">Contribution Profit</div>
            <div className="metric-value">{formatINR(String(profitability.contribution_profit_inr))}</div>
            <div className="metric-foot" style={{ color: "#cfe5da" }}>
              Rev ex-GST: {formatINR(String(profitability.revenue_ex_gst_inr))} • Gross: {formatINR(String(profitability.gross_profit_inr))}
            </div>
          </div>
        )}
        {statuses.map((s) => (
          <div className="card" key={String(s.channel)}>
            <div className="metric-label">{String(s.channel)} Adapter</div>
            <div style={{ marginBlock: "0.45rem" }}>
              <span className={`badge ${s.configured ? "badge-normal" : "badge-red"}`}>{String(s.connection_status)}</span>
            </div>
            <div className="metric-foot">{String(s.message)}</div>
          </div>
        ))}
      </div>

      <section className="card" style={{ marginBlockEnd: "1rem" }}>
        <div className="eyebrow">Controlled Ingestion</div>
        <h3>Marketplace Report Import (Tagged IMPORTED_REPORT)</h3>
        <form onSubmit={importCsv}>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="mkt-ch">Marketplace Channel</label>
              <select id="mkt-ch" value={channel} onChange={(e) => setChannel(e.target.value as "AMAZON_IN" | "FLIPKART")}>
                <option value="AMAZON_IN">Amazon India</option>
                <option value="FLIPKART">Flipkart</option>
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor="mkt-csv">CSV Report Rows</label>
            <textarea id="mkt-csv" rows={4} value={csvText} onChange={(e) => setCsvText(e.target.value)} />
          </div>
          <button type="submit" className="btn btn-primary">Import & Reconcile</button>
        </form>
      </section>

      <div className="card-grid">
        <section className="card">
          <div className="eyebrow">Financial Leakage Protection</div>
          <h3>Marketplace Discrepancy Cases ({discrepancies.length})</h3>
          {discrepancies.length === 0 ? (
            <p className="metric-foot">No discrepancies detected.</p>
          ) : (
            <div style={{ display: "grid", gap: "0.6rem" }}>
              {discrepancies.map((d) => (
                <div key={String(d.id)} className="card" style={{ background: "var(--surface-tint)", boxShadow: "none", padding: "0.75rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong>{String(d.case_code)} • {String(d.discrepancy_type)}</strong>
                    <span className="badge badge-critical">{formatINR(String(d.estimated_impact_inr))}</span>
                  </div>
                  <div className="metric-foot" style={{ marginTop: "0.25rem" }}>
                    Channel: {String(d.channel)} • Status: {String(d.status)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <div className="eyebrow">Capital Productivity</div>
          <h3>ROWC Procurement Recommendations ({procRecs.length})</h3>
          {procRecs.length === 0 ? (
            <p className="metric-foot">All SKUs adequately stocked.</p>
          ) : (
            <div style={{ display: "grid", gap: "0.6rem" }}>
              {procRecs.map((r) => (
                <div key={String(r.sku_id)} className="card" style={{ background: "var(--surface-tint)", boxShadow: "none", padding: "0.75rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong>{String(r.sku_code)} — Order {String(r.recommended_order_qty)}u</strong>
                    <span className="badge badge-normal">ROWC {String(r.annualized_rowc_pct)}%</span>
                  </div>
                  <div className="metric-foot" style={{ marginTop: "0.25rem" }}>
                    Capital: {formatINR(String(r.capital_required_inr))} • Lead (incl. FC): {String(r.effective_lead_days_incl_fc_delay)}d
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="card">
        <div className="eyebrow">Accounting Separation</div>
        <h3>BUSY Accounting Bridge</h3>
        <button type="button" className="btn btn-secondary" onClick={runBusyExport}>Export Unsynced Sales Vouchers (BUSY XML)</button>
        {busyExport && (
          <pre style={{ background: "var(--surface-alt)", padding: "0.85rem", borderRadius: "10px", overflowX: "auto", fontSize: "0.8rem", marginTop: "0.75rem" }}>
            {busyExport}
          </pre>
        )}
      </section>
    </div>
  );
}
