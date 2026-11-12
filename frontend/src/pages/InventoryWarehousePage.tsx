import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { IconBox, IconDispatch, IconReceive, IconSpark, IconTransfer } from "../components/Icons";
import { Lang, TRANSLATIONS } from "../i18n/translations";
import { formatINR } from "../utils/format";

export function InventoryWarehousePage({ lang, isOwner }: { lang: Lang; isOwner: boolean }) {
  const t = TRANSLATIONS[lang];
  const [query, setQuery] = useState("");
  const [tierFilter, setTierFilter] = useState<"ALL" | "NORMAL" | "RED" | "CRITICAL">("ALL");
  const [skus, setSkus] = useState<Array<Record<string, unknown>>>([]);
  const [locations, setLocations] = useState<Array<{ id: number; code: string; name: string; location_type: string }>>([]);
  const [availability, setAvailability] = useState<Array<Record<string, unknown>>>([]);
  const [ageing, setAgeing] = useState<{ summary: Record<string, { units: number; value_inr: string }>; batches: Array<Record<string, unknown>> } | null>(null);
  const [status, setStatus] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const [skuId, setSkuId] = useState("");
  const [locId, setLocId] = useState("");
  const [toLocId, setToLocId] = useState("");
  const [qty, setQty] = useState("1");
  const [unitCost, setUnitCost] = useState("1800");
  const [actionMode, setActionMode] = useState<"receive" | "dispatch" | "transfer">("receive");

  const [newSkuCode, setNewSkuCode] = useState("");
  const [newSkuName, setNewSkuName] = useState("");
  const [newLocCode, setNewLocCode] = useState("");
  const [newLocName, setNewLocName] = useState("");

  async function refresh(searchQ = query) {
    try {
      const [s, l, av, ag] = await Promise.all([
        api.request<Array<Record<string, unknown>>>(`/api/v1/inventory/skus${searchQ ? `?q=${encodeURIComponent(searchQ)}` : ""}`),
        api.request<Array<{ id: number; code: string; name: string; location_type: string }>>("/api/v1/inventory/locations"),
        api.request<Array<Record<string, unknown>>>("/api/v1/inventory/availability"),
        api.request<{ summary: Record<string, { units: number; value_inr: string }>; batches: Array<Record<string, unknown>> }>("/api/v1/inventory/ageing"),
      ]);
      setSkus(s);
      setLocations(l);
      setAvailability(av);
      setAgeing(ag);
      if (!skuId && s.length > 0) setSkuId(String(s[0].id));
      if (!locId && l.length > 0) setLocId(String(l[0].id));
    } catch (e) {
      setStatus({ type: "err", text: (e as Error).message });
    }
  }

  useEffect(() => {
    refresh("");
  }, []);

  async function submitMovement(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    const idemp = `UI-${actionMode}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    try {
      if (actionMode === "receive") {
        await api.request("/api/v1/inventory/receive", {
          method: "POST",
          body: JSON.stringify({ sku_id: Number(skuId), location_id: Number(locId), qty: Number(qty), unit_cost: unitCost, idempotency_key: idemp }),
        });
      } else if (actionMode === "dispatch") {
        await api.request("/api/v1/inventory/dispatch", {
          method: "POST",
          body: JSON.stringify({ sku_id: Number(skuId), location_id: Number(locId), qty: Number(qty), reference_id: idemp, idempotency_key: idemp }),
        });
      } else {
        await api.request("/api/v1/inventory/transfer", {
          method: "POST",
          body: JSON.stringify({ sku_id: Number(skuId), from_location_id: Number(locId), to_location_id: Number(toLocId), qty: Number(qty), idempotency_key: idemp }),
        });
      }
      setStatus({ type: "ok", text: `Recorded ${actionMode} for ${qty} unit(s).` });
      await refresh();
    } catch (e) {
      setStatus({ type: "err", text: (e as Error).message });
    }
  }

  async function handleAddLocation(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.request("/api/v1/inventory/locations", {
        method: "POST",
        body: JSON.stringify({ code: newLocCode, name: newLocName, location_type: "WAREHOUSE" }),
      });
      setNewLocCode("");
      setNewLocName("");
      await refresh();
    } catch (e) {
      setStatus({ type: "err", text: (e as Error).message });
    }
  }

  async function handleAddSku(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.request("/api/v1/inventory/skus", {
        method: "POST",
        body: JSON.stringify({
          sku_code: newSkuCode,
          name: newSkuName,
          category: "WATER_PUMP",
          item_type: "FINISHED_GOOD",
          purchase_cost: "2000",
          selling_price: "2900",
          mrp: "3500",
          gst_rate: "18.00",
        }),
      });
      setNewSkuCode("");
      setNewSkuName("");
      await refresh();
    } catch (e) {
      setStatus({ type: "err", text: (e as Error).message });
    }
  }

  const totalValuation = availability.reduce((acc, r) => acc + Number(r.stock_value_inr || 0), 0);
  const totalSellable = availability.reduce((acc, r) => acc + Number(r.available_qty || 0), 0);
  const totalTransit = availability.reduce((acc, r) => acc + Number(r.in_transit_qty || 0), 0);
  const lowStockItems = availability.filter((r) => Number(r.available_qty || 0) <= 5);

  const filteredBatches = (ageing?.batches || []).filter(
    (b) => tierFilter === "ALL" || String(b.classification) === tierFilter
  );

  return (
    <div>
      <header className="page-hero">
        <div>
          <div className="eyebrow">Real-Time Stock Intelligence</div>
          <h2 className="page-title">{t.inventoryWarehouse}</h2>
          <p className="page-subtitle">
            {locations.length} active locations • Inbound receipt dates preserved across transfers & bundles.
          </p>
        </div>
      </header>

      {status && (
        <div className={`status-banner ${status.type === "ok" ? "status-ok" : "status-error"}`} role="status">
          {status.text}
        </div>
      )}

      <div className="kpi-grid">
        <div className="card-hero">
          <div className="kpi-head">
            <div className="metric-label">Total Stock Valuation</div>
            <div className="kpi-icon-box"><IconBox size={15} /></div>
          </div>
          <div className="metric-value">{formatINR(totalValuation)}</div>
          <div className="metric-divider">
            <span>Sellable: {totalSellable}</span>
            <span>In-Transit: {totalTransit}</span>
          </div>
        </div>
        <div className="card">
          <div className="kpi-head">
            <div className="metric-label">Active SKUs</div>
            <div className="kpi-icon-box"><IconSpark size={15} /></div>
          </div>
          <div className="metric-value">{skus.length}</div>
          <div className="metric-divider">
            <span>{locations.length} locations</span>
            <span>{lowStockItems.length} low stock</span>
          </div>
        </div>
      </div>

      {lowStockItems.length > 0 && (
        <div className="card-alert" style={{ marginBlockEnd: "1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
            <strong style={{ color: "var(--crit-fg)" }}>Low Stock Alert ({lowStockItems.length} SKU)</strong>
            <span className="badge badge-critical">{lowStockItems.map((x) => String(x.sku_code)).join(", ")} ≤ 5 units</span>
          </div>
        </div>
      )}

      <section className="shortcut-grid" aria-label="Warehouse Movement Mode">
        <button type="button" className="tile-btn" aria-pressed={actionMode === "receive"} onClick={() => setActionMode("receive")}>
          <IconReceive />
          <span>{t.receiveStock}</span>
        </button>
        <button type="button" className="tile-btn" aria-pressed={actionMode === "dispatch"} onClick={() => setActionMode("dispatch")}>
          <IconDispatch />
          <span>{t.dispatchStock}</span>
        </button>
        <button type="button" className="tile-btn" aria-pressed={actionMode === "transfer"} onClick={() => setActionMode("transfer")}>
          <IconTransfer />
          <span>{t.transferStock}</span>
        </button>
      </section>

      <section className="card" style={{ marginBlockEnd: "1rem" }}>
        <div className="eyebrow">Ledger Transaction</div>
        <h3>Record {actionMode.toUpperCase()}</h3>
        <form onSubmit={submitMovement} className="form-grid">
          <div className="field">
            <label htmlFor="mov-sku">SKU</label>
            <select id="mov-sku" value={skuId} onChange={(e) => setSkuId(e.target.value)} required>
              {skus.map((s) => (
                <option key={String(s.id)} value={String(s.id)}>{String(s.sku_code)} — {String(s.name)}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="mov-loc">{actionMode === "transfer" ? "From Location" : "Location"}</label>
            <select id="mov-loc" value={locId} onChange={(e) => setLocId(e.target.value)} required>
              {locations.map((l) => (
                <option key={l.id} value={String(l.id)}>{l.code} ({l.location_type})</option>
              ))}
            </select>
          </div>
          {actionMode === "transfer" && (
            <div className="field">
              <label htmlFor="mov-toloc">To Location</label>
              <select id="mov-toloc" value={toLocId} onChange={(e) => setToLocId(e.target.value)} required>
                <option value="">Select destination</option>
                {locations.map((l) => (
                  <option key={l.id} value={String(l.id)}>{l.code} ({l.location_type})</option>
                ))}
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor="mov-qty">Quantity</label>
            <input id="mov-qty" type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} required />
          </div>
          {actionMode === "receive" && (
            <div className="field">
              <label htmlFor="mov-cost">Unit Cost (₹)</label>
              <input id="mov-cost" type="text" inputMode="decimal" value={unitCost} onChange={(e) => setUnitCost(e.target.value)} required />
            </div>
          )}
          <div className="field" style={{ justifyContent: "flex-end" }}>
            <button type="submit" className="btn btn-primary">Confirm {actionMode}</button>
          </div>
        </form>
      </section>

      <search className="card" style={{ marginBlockEnd: "1rem" }}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            refresh(query);
          }}
          style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}
        >
          <input
            type="search"
            aria-label={t.scanBarcode}
            placeholder={t.scanBarcode}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ flex: "1 1 240px" }}
          />
          <button type="submit" className="btn btn-primary">Search / Scan</button>
        </form>
      </search>

      <div className="card-grid">
        {availability.map((r) => (
          <article className="card" key={String(r.sku_id)}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem" }}>
              <div>
                <div className="eyebrow">{String(r.sku_code)} • {String(r.item_type)}</div>
                <strong style={{ fontSize: "1rem", color: "var(--primary-deep)" }}>{String(r.name)}</strong>
              </div>
              <span className={`badge ${Number(r.available_qty) <= 5 ? "badge-critical" : "badge-normal"}`}>
                {Number(r.available_qty) <= 5 ? "Low Stock" : "Healthy"}
              </span>
            </div>
            <div className="sku-mini-grid">
              <div className="sku-mini-cell">
                <span>Available</span>
                <strong>{String(r.available_qty)}</strong>
              </div>
              <div className="sku-mini-cell">
                <span>In Transit</span>
                <strong>{String(r.in_transit_qty)}</strong>
              </div>
              <div className="sku-mini-cell">
                <span>Value</span>
                <strong>{formatINR(String(r.stock_value_inr))}</strong>
              </div>
            </div>
            <div className="metric-foot">
              Physical: {String(r.physical_qty)} • Reserved: {String(r.reserved_qty)} • Damaged: {String(r.damaged_qty)} • Warranty Res: {String(r.warranty_reserved_qty)}
            </div>
          </article>
        ))}
      </div>

      {isOwner && (
        <div className="card-grid">
          <form onSubmit={handleAddLocation} className="card">
            <h3>Add Warehouse / FC Location</h3>
            <div className="field">
              <label htmlFor="new-loc-code">Location Code</label>
              <input id="new-loc-code" value={newLocCode} onChange={(e) => setNewLocCode(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="new-loc-name">Location Name</label>
              <input id="new-loc-name" value={newLocName} onChange={(e) => setNewLocName(e.target.value)} required />
            </div>
            <button type="submit" className="btn btn-secondary">Create Location</button>
          </form>

          <form onSubmit={handleAddSku} className="card">
            <h3>Quick Add Water Pump / Part SKU</h3>
            <div className="field">
              <label htmlFor="new-sku-code">SKU Code</label>
              <input id="new-sku-code" value={newSkuCode} onChange={(e) => setNewSkuCode(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="new-sku-name">Product Name</label>
              <input id="new-sku-name" value={newSkuName} onChange={(e) => setNewSkuName(e.target.value)} required />
            </div>
            <button type="submit" className="btn btn-secondary">Create SKU</button>
          </form>
        </div>
      )}

      {ageing && (
        <section className="card">
          <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem", alignItems: "center", marginBlockEnd: "0.75rem" }}>
            <div>
              <div className="eyebrow">Receipt-Batch Traceability</div>
              <h3 style={{ margin: 0 }}>Inventory Ageing ({filteredBatches.length} batches)</h3>
            </div>
            <div className="pill-row" style={{ marginBlockEnd: 0 }}>
              {(["ALL", "NORMAL", "RED", "CRITICAL"] as const).map((tier) => (
                <button
                  key={tier}
                  type="button"
                  className={`btn ${tierFilter === tier ? "btn-primary" : "btn-secondary"}`}
                  style={{ minBlockSize: "38px", padding: "0.3rem 0.8rem", fontSize: "0.8rem" }}
                  onClick={() => setTierFilter(tier)}
                >
                  {tier}
                </button>
              ))}
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Batch</th>
                  <th>SKU</th>
                  <th>Location</th>
                  <th>Inbound</th>
                  <th>Age</th>
                  <th>Tier</th>
                  <th>Qty</th>
                  <th>Blocked Capital</th>
                </tr>
              </thead>
              <tbody>
                {filteredBatches.map((b) => (
                  <tr key={String(b.batch_id)}>
                    <td><strong>{String(b.batch_code)}</strong></td>
                    <td>{String(b.sku_code)}</td>
                    <td>{String(b.location_code)}</td>
                    <td>{String(b.inbound_date)}</td>
                    <td>{String(b.age_days)}d</td>
                    <td>
                      <span className={`badge badge-${String(b.classification).toLowerCase()}`}>
                        {String(b.classification)}
                      </span>
                    </td>
                    <td>{String(b.remaining_qty)}</td>
                    <td><strong>{formatINR(String(b.blocked_capital_inr))}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
