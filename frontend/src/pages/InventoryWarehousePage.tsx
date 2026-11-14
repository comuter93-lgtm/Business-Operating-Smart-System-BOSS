import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { IconBox, IconDispatch, IconReceive, IconSpark, IconTransfer } from "../components/Icons";
import { Lang, TRANSLATIONS } from "../i18n/translations";
import { formatINR } from "../utils/format";

type SkuRow = Record<string, unknown>;
type TextField = "sku_code" | "name" | "barcode" | "brand" | "category" | "item_type" | "strategic_role";
type NumberField = "purchase_cost" | "selling_price" | "mrp" | "gst_rate" | "reorder_point";
type SkuEditForm = Record<TextField | NumberField, string> & { warranty_eligible: boolean };

const textFields: Array<{ key: TextField; label: string; required?: boolean }> = [
  { key: "sku_code", label: "SKU Code", required: true },
  { key: "name", label: "Product Name", required: true },
  { key: "barcode", label: "Barcode" },
  { key: "brand", label: "Brand" },
  { key: "category", label: "Category" },
  { key: "item_type", label: "Item Type" },
  { key: "strategic_role", label: "Strategic Role" },
];

const numberFields: Array<{ key: NumberField; label: string }> = [
  { key: "purchase_cost", label: "Purchase Cost (₹)" },
  { key: "selling_price", label: "Selling Price (₹)" },
  { key: "mrp", label: "MRP (₹)" },
  { key: "gst_rate", label: "GST Rate (%)" },
  { key: "reorder_point", label: "Reorder Point" },
];

function editFormFor(sku: SkuRow): SkuEditForm {
  return {
    sku_code: String(sku.sku_code ?? ""), name: String(sku.name ?? ""),
    barcode: String(sku.barcode ?? ""), brand: String(sku.brand ?? ""),
    category: String(sku.category ?? ""), item_type: String(sku.item_type ?? ""),
    strategic_role: String(sku.strategic_role ?? ""),
    purchase_cost: String(sku.purchase_cost ?? ""),
    selling_price: String(sku.selling_price ?? ""), mrp: String(sku.mrp ?? ""),
    gst_rate: String(sku.gst_rate ?? ""), reorder_point: String(sku.reorder_point ?? ""),
    warranty_eligible: sku.warranty_eligible === true,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

function displayText(value: unknown): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function displayMoney(value: unknown): string {
  return value === null || value === undefined || value === "" ? "—" : formatINR(String(value));
}

export function InventoryWarehousePage({ lang, isOwner }: { lang: Lang; isOwner: boolean }) {
  const t = TRANSLATIONS[lang];
  const [query, setQuery] = useState("");
  const [tierFilter, setTierFilter] = useState<"ALL" | "NORMAL" | "RED" | "CRITICAL">("ALL");
  const [skus, setSkus] = useState<Array<Record<string, unknown>>>([]);
  const [locations, setLocations] = useState<Array<{ id: number; code: string; name: string; location_type: string }>>([]);
  const [availability, setAvailability] = useState<Array<Record<string, unknown>>>([]);
  const [ageing, setAgeing] = useState<{ summary: Record<string, { units: number; value_inr: string }>; batches: Array<Record<string, unknown>> } | null>(null);
  const [status, setStatus] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const [allSkus, setAllSkus] = useState<SkuRow[]>([]);
  const [showSkuList, setShowSkuList] = useState(false);
  const [skuListLoading, setSkuListLoading] = useState(false);
  const [skuListError, setSkuListError] = useState<string | null>(null);
  const [editingSku, setEditingSku] = useState<SkuRow | null>(null);
  const [editForm, setEditForm] = useState<SkuEditForm | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [savingSku, setSavingSku] = useState(false);
  const editDialogRef = useRef<HTMLDialogElement>(null);

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

  async function refresh(searchQ = query, reportError = true) {
    try {
      const [s, l, av, ag] = await Promise.all([
        api.request<Array<Record<string, unknown>>>(`/api/v1/inventory/skus${searchQ ? `?q=${encodeURIComponent(searchQ)}` : ""}`),
        api.request<Array<{ id: number; code: string; name: string; location_type: string }>>("/api/v1/inventory/locations"),
        api.request<Array<Record<string, unknown>>>("/api/v1/inventory/availability"),
        api.request<{ summary: Record<string, { units: number; value_inr: string }>; batches: Array<Record<string, unknown>> }>("/api/v1/inventory/ageing"),
      ]);
      setSkus(s);
      if (!searchQ) setAllSkus(s);
      setLocations(l);
      setAvailability(av);
      setAgeing(ag);
      if (!skuId && s.length > 0) setSkuId(String(s[0].id));
      if (!locId && l.length > 0) setLocId(String(l[0].id));
      return true;
    } catch (e) {
      if (reportError) setStatus({ type: "err", text: errorMessage(e) });
      return false;
    }
  }

  useEffect(() => {
    refresh("");
  }, []);

  useEffect(() => {
    const dialog = editDialogRef.current;
    if (editingSku && dialog && !dialog.open) dialog.showModal();
    return () => {
      if (dialog?.open) dialog.close();
    };
  }, [editingSku]);

  async function loadAllSkus() {
    setSkuListLoading(true);
    setSkuListError(null);
    try {
      const rows = await api.request<SkuRow[]>("/api/v1/inventory/skus");
      setAllSkus(rows);
      return true;
    } catch (e) {
      setSkuListError(errorMessage(e));
      return false;
    } finally {
      setSkuListLoading(false);
    }
  }

  function openSkuList() {
    setShowSkuList(true);
    void loadAllSkus();
  }

  function openSkuEditor(sku: SkuRow) {
    setEditingSku(sku);
    setEditForm(editFormFor(sku));
    setEditError(null);
  }

  function closeSkuEditor() {
    if (savingSku) return;
    editDialogRef.current?.close();
    setEditingSku(null);
    setEditForm(null);
    setEditError(null);
  }

  async function saveSku(e: React.FormEvent) {
    e.preventDefault();
    if (!editingSku || !editForm || savingSku) return;
    setEditError(null);
    const original = editFormFor(editingSku);
    const changes: Record<string, string | number | boolean> = {};

    for (const field of textFields) {
      if (editForm[field.key] === original[field.key]) continue;
      const value = field.required ? editForm[field.key].trim() : editForm[field.key];
      if (field.required && !value) {
        setEditError(`${field.label} is required.`);
        return;
      }
      if (value !== original[field.key]) changes[field.key] = value;
    }

    for (const field of numberFields) {
      if (field.key === "purchase_cost" && !isOwner) continue;
      if (editForm[field.key] === original[field.key]) continue;
      const value = editForm[field.key].trim();
      const numericValue = Number(value);
      if (!value || !Number.isFinite(numericValue) || numericValue < 0 ||
          (field.key === "gst_rate" && numericValue > 100) ||
          (field.key === "reorder_point" && !Number.isSafeInteger(numericValue))) {
        setEditError(`Enter a valid ${field.label}.`);
        return;
      }
      // Keep decimal amounts as strings, matching the backend Decimal fields.
      changes[field.key] = field.key === "reorder_point" ? numericValue : value;
    }

    if (editForm.warranty_eligible !== original.warranty_eligible) {
      changes.warranty_eligible = editForm.warranty_eligible;
    }
    if (Object.keys(changes).length === 0) {
      setEditError("No changes to save.");
      return;
    }

    setSavingSku(true);
    try {
      await api.request(`/api/v1/inventory/skus/${encodeURIComponent(String(editingSku.id))}`, {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
    } catch (e) {
      setEditError(errorMessage(e));
      setSavingSku(false);
      return;
    }

    // PATCH returns an acknowledgement, so reload the full records after saving.
    editDialogRef.current?.close();
    setEditingSku(null);
    setEditForm(null);
    setStatus({ type: "ok", text: "SKU details saved successfully." });
    const [pageRefreshed, listRefreshed] = await Promise.all([
      refresh(query, false), loadAllSkus(),
    ]);
    if (!pageRefreshed || !listRefreshed) {
      setStatus({ type: "err", text: "SKU was saved, but some inventory data could not be refreshed. Refresh the page to load the latest data." });
    }
    setSavingSku(false);
  }

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
        <button
          type="button"
          className="card"
          aria-label="View all active SKUs"
          aria-expanded={showSkuList}
          aria-controls="active-sku-list"
          onClick={openSkuList}
          disabled={skuListLoading || savingSku}
          style={{ textAlign: "start", font: "inherit", color: "inherit", cursor: "pointer", width: "100%" }}
        >
          <div className="kpi-head">
            <div className="metric-label">Active SKUs</div>
            <div className="kpi-icon-box"><IconSpark size={15} /></div>
          </div>
          <div className="metric-value">{allSkus.length}</div>
          <div className="metric-divider">
            <span>{locations.length} locations</span>
            <span>{lowStockItems.length} low stock</span>
          </div>
        </button>
      </div>

      {lowStockItems.length > 0 && (
        <div className="card-alert" style={{ marginBlockEnd: "1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
            <strong style={{ color: "var(--crit-fg)" }}>Low Stock Alert ({lowStockItems.length} SKU)</strong>
            <span className="badge badge-critical">{lowStockItems.map((x) => String(x.sku_code)).join(", ")} ≤ 5 units</span>
          </div>
        </div>
      )}

      {showSkuList && (
        <section id="active-sku-list" className="card" aria-labelledby="active-sku-title" style={{ marginBlockEnd: "1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
            <h3 id="active-sku-title">Active SKUs ({allSkus.length})</h3>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button type="button" className="btn btn-secondary" onClick={() => void loadAllSkus()} disabled={skuListLoading || savingSku}>
                {skuListLoading ? "Loading…" : "Refresh list"}
              </button>
              <button type="button" className="btn btn-secondary" onClick={() => setShowSkuList(false)}>Close list</button>
            </div>
          </div>
          <p>All created SKUs are listed, including those with no stock received.</p>
          {skuListError && <div className="status-banner status-error" role="alert">{skuListError}</div>}
          <div className="table-wrap" aria-busy={skuListLoading}>
            <table aria-label="Active SKUs details">
              <thead>
                <tr>
                  <th>ID</th><th>SKU Code</th><th>Product Name</th><th>Barcode</th>
                  <th>Brand</th><th>Category</th><th>Item Type</th>
                  {isOwner && <th>Purchase Cost</th>}
                  <th>Selling Price</th><th>MRP</th><th>GST %</th>
                  <th>Warranty Eligible</th><th>Reorder Point</th><th>Strategic Role</th><th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {allSkus.map((sku) => (
                  <tr key={String(sku.id)}>
                    <td>{displayText(sku.id)}</td><td><strong>{displayText(sku.sku_code)}</strong></td>
                    <td>{displayText(sku.name)}</td><td>{displayText(sku.barcode)}</td>
                    <td>{displayText(sku.brand)}</td><td>{displayText(sku.category)}</td><td>{displayText(sku.item_type)}</td>
                    {isOwner && <td>{displayMoney(sku.purchase_cost)}</td>}
                    <td>{displayMoney(sku.selling_price)}</td><td>{displayMoney(sku.mrp)}</td>
                    <td>{displayText(sku.gst_rate)}</td><td>{sku.warranty_eligible ? "Yes" : "No"}</td>
                    <td>{displayText(sku.reorder_point)}</td><td>{displayText(sku.strategic_role)}</td>
                    <td>
                      <button type="button" className="btn btn-secondary" aria-label={`Edit ${String(sku.sku_code)}`} onClick={() => openSkuEditor(sku)} disabled={skuListLoading || savingSku}>
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
                {allSkus.length === 0 && (
                  <tr><td colSpan={isOwner ? 15 : 14}>{skuListLoading ? "Loading SKUs…" : "No SKUs found."}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
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

      {editingSku && editForm && (
        <dialog
          ref={editDialogRef}
          aria-labelledby="edit-sku-title"
          aria-describedby="edit-sku-note"
          onCancel={(e) => { e.preventDefault(); closeSkuEditor(); }}
          style={{ width: "min(900px, calc(100vw - 2rem))", maxHeight: "85vh", overflowY: "auto", border: 0, borderRadius: "12px", padding: 0 }}
        >
          <form onSubmit={saveSku} className="card" style={{ margin: 0 }}>
            <h3 id="edit-sku-title">Edit SKU — {displayText(editingSku.sku_code)}</h3>
            <p id="edit-sku-note">
              Update product details here. Use Record RECEIVE, DISPATCH or TRANSFER to change stock quantities.
            </p>
            {editError && <div className="status-banner status-error" role="alert">{editError}</div>}
            <fieldset disabled={savingSku} style={{ border: 0, padding: 0, margin: 0 }}>
              <legend style={{ fontWeight: 600, marginBlockEnd: "0.75rem" }}>SKU details</legend>
              <div className="form-grid">
                {textFields.map((field) => (
                  <div className="field" key={field.key}>
                    <label htmlFor={`edit-${field.key}`}>{field.label}</label>
                    <input
                      id={`edit-${field.key}`}
                      value={editForm[field.key]}
                      required={field.required}
                      autoFocus={field.key === "sku_code"}
                      onChange={(e) => setEditForm((current) => current ? { ...current, [field.key]: e.target.value } : current)}
                    />
                  </div>
                ))}
                {numberFields.filter((field) => isOwner || field.key !== "purchase_cost").map((field) => (
                  <div className="field" key={field.key}>
                    <label htmlFor={`edit-${field.key}`}>{field.label}</label>
                    <input
                      id={`edit-${field.key}`}
                      type="number"
                      inputMode={field.key === "reorder_point" ? "numeric" : "decimal"}
                      min={0}
                      max={field.key === "gst_rate" ? 100 : undefined}
                      step={field.key === "reorder_point" ? 1 : "any"}
                      value={editForm[field.key]}
                      required
                      onChange={(e) => setEditForm((current) => current ? { ...current, [field.key]: e.target.value } : current)}
                    />
                  </div>
                ))}
                <div className="field">
                  <label htmlFor="edit-warranty_eligible">Warranty Eligible</label>
                  <input
                    id="edit-warranty_eligible"
                    type="checkbox"
                    checked={editForm.warranty_eligible}
                    onChange={(e) => setEditForm((current) => current ? { ...current, warranty_eligible: e.target.checked } : current)}
                  />
                </div>
              </div>
            </fieldset>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem", marginBlockStart: "1rem" }}>
              <button type="button" className="btn btn-secondary" onClick={closeSkuEditor} disabled={savingSku}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={savingSku}>
                {savingSku ? "Saving…" : "Save changes"}
              </button>
            </div>
          </form>
        </dialog>
      )}
    </div>
  );
}
