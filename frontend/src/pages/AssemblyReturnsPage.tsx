import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { Lang, TRANSLATIONS } from "../i18n/translations";
import { formatINR } from "../utils/format";

export function AssemblyReturnsPage({ lang }: { lang: Lang }) {
  const t = TRANSLATIONS[lang];
  const [boms, setBoms] = useState<Array<Record<string, unknown>>>([]);
  const [returnsList, setReturnsList] = useState<Array<Record<string, unknown>>>([]);
  const [warranty, setWarranty] = useState<Array<Record<string, unknown>>>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.request<Array<Record<string, unknown>>>("/api/v1/boms"),
      api.request<Array<Record<string, unknown>>>("/api/v1/returns"),
      api.request<Array<Record<string, unknown>>>("/api/v1/warranty/reserves"),
    ])
      .then(([b, r, w]) => {
        setBoms(b);
        setReturnsList(r);
        setWarranty(w);
      })
      .catch((e) => setErr((e as Error).message));
  }, []);

  return (
    <div>
      <header className="page-hero">
        <div>
          <div className="eyebrow">Bundles, BOM & Warranty Policy</div>
          <h2 className="page-title">{t.assemblyReturns}</h2>
          <p className="page-subtitle">
            48-hour return inspection SLA, BOM-checked bundle returns, and 2% warranty reserve tracking.
          </p>
        </div>
      </header>
      {err && <div className="status-banner status-error">{err}</div>}

      <section className="card" style={{ marginBlockEnd: "1rem" }}>
        <div className="eyebrow">Policy Compliance</div>
        <h3>Warranty Reserve Monitor (Max of 1 unit or 2% Own-WH Stock)</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Own WH Stock</th>
                <th>Required Reserve</th>
                <th>Reserved</th>
                <th>Shortage</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {warranty.map((w) => (
                <tr key={String(w.sku_id)}>
                  <td><strong>{String(w.sku_code)}</strong> — {String(w.sku_name)}</td>
                  <td>{String(w.eligible_own_warehouse_stock)}</td>
                  <td>{String(w.required_reserve)}</td>
                  <td>{String(w.actual_warranty_reserved)}</td>
                  <td><strong>{String(w.shortage)}</strong></td>
                  <td>
                    <span className={`badge ${w.status === "OK" ? "badge-normal" : "badge-critical"}`}>{String(w.status)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="card-grid">
        <section className="card">
          <div className="eyebrow">Versioned BOMs</div>
          <h3>Bills of Materials ({boms.length})</h3>
          {boms.length === 0 ? (
            <p className="metric-foot">No BOMs registered yet.</p>
          ) : (
            <div style={{ display: "grid", gap: "0.6rem" }}>
              {boms.map((b) => (
                <div key={String(b.id)} className="card" style={{ background: "var(--surface-tint)", boxShadow: "none", padding: "0.75rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong>Bundle SKU #{String(b.bundle_sku_id)} • v{String(b.version)}</strong>
                    <span className={`badge ${b.status === "ACTIVE" ? "badge-normal" : "badge-red"}`}>{String(b.status)}</span>
                  </div>
                  {b.notes ? <div className="metric-foot" style={{ marginTop: "0.25rem" }}>{String(b.notes)}</div> : null}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <div className="eyebrow">Return Inspections</div>
          <h3>Returns Queue ({returnsList.length})</h3>
          {returnsList.length === 0 ? (
            <p className="metric-foot">No return cases recorded.</p>
          ) : (
            <div style={{ display: "grid", gap: "0.6rem" }}>
              {returnsList.map((r) => (
                <div key={String(r.id)} className="card" style={{ background: "var(--surface-tint)", boxShadow: "none", padding: "0.75rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
                    <strong>{String(r.return_code)} ({String(r.channel)})</strong>
                    <span className={`badge ${r.classification === "INCOMPLETE" || r.classification === "DAMAGED" ? "badge-critical" : "badge-normal"}`}>
                      {String(r.classification || r.status)}
                    </span>
                  </div>
                  <div className="metric-foot" style={{ marginTop: "0.25rem" }}>
                    Est. Loss: <strong>{formatINR(String(r.estimated_loss_inr))}</strong> • Recovery: {String(r.recovery_status)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
