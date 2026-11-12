import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { Lang, TRANSLATIONS } from "../i18n/translations";

interface AccessPreview {
  employee_id: number;
  employee_code: string;
  full_name: string;
  department: string;
  is_active: boolean;
  preferred_language: Lang;
  visible_pages: string[];
  accessible_location_ids: number[];
  accessible_locations: Array<{ id: number; code: string; name: string; type: string }>;
  editable_fields: Record<string, string[]>;
  allowed_actions: string[];
  assigned_tasks: Array<{ id: number; task_code: string; title: string; status: string }>;
  can_export: boolean;
  available_pages_catalog: string[];
  available_actions_catalog: string[];
}

export function EmployeesAccessPage({ lang, isOwner }: { lang: Lang; isOwner: boolean }) {
  const t = TRANSLATIONS[lang];
  const [employees, setEmployees] = useState<Array<{ id: number; employee_code: string; full_name: string; department: string; is_active: boolean }>>([]);
  const [preview, setPreview] = useState<AccessPreview | null>(null);
  const [tasks, setTasks] = useState<Array<Record<string, unknown>>>([]);
  const [auditLogs, setAuditLogs] = useState<Array<Record<string, unknown>>>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [pin, setPin] = useState("");
  const [empLang, setEmpLang] = useState<Lang>("hi");

  async function loadAll() {
    try {
      const taskRows = await api.request<Array<Record<string, unknown>>>("/api/v1/tasks");
      setTasks(taskRows);
      if (isOwner) {
        const [emps, logs] = await Promise.all([
          api.request<Array<{ id: number; employee_code: string; full_name: string; department: string; is_active: boolean }>>("/api/v1/permissions/employees"),
          api.request<Array<Record<string, unknown>>>("/api/v1/audit-logs?limit=30"),
        ]);
        setEmployees(emps);
        setAuditLogs(logs);
        if (emps.length > 0 && !preview) {
          setPreview(await api.request<AccessPreview>(`/api/v1/permissions/employees/${emps[0].id}/preview`));
        }
      }
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    loadAll();
  }, [isOwner]);

  async function selectEmployee(id: number) {
    try {
      setPreview(await api.request<AccessPreview>(`/api/v1/permissions/employees/${id}/preview`));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function createEmployee(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    try {
      const p = await api.request<AccessPreview>("/api/v1/permissions/employees", {
        method: "POST",
        body: JSON.stringify({
          employee_code: code,
          full_name: name,
          pin,
          preferred_language: empLang,
          visible_pages: ["warehouse", "inventory"],
          allowed_actions: ["inventory.view", "receipt.create", "task.view_own", "task.complete"],
          can_export: false,
        }),
      });
      setCode("");
      setName("");
      setPin("");
      setPreview(p);
      setMsg(`Created employee ${p.employee_code}`);
      await loadAll();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function toggleAction(actionName: string) {
    if (!preview) return;
    const nextActions = preview.allowed_actions.includes(actionName)
      ? preview.allowed_actions.filter((a) => a !== actionName)
      : [...preview.allowed_actions, actionName];
    try {
      const updated = await api.request<AccessPreview>(`/api/v1/permissions/employees/${preview.employee_id}`, {
        method: "PUT",
        body: JSON.stringify({
          visible_pages: preview.visible_pages,
          accessible_location_ids: preview.accessible_location_ids,
          editable_fields: preview.editable_fields,
          allowed_actions: nextActions,
          can_export: preview.can_export,
          is_active: preview.is_active,
        }),
      });
      setPreview(updated);
      setMsg(`Updated permissions for ${updated.employee_code}`);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function submitTask(taskId: number) {
    try {
      await api.request(`/api/v1/tasks/${taskId}/submit`, {
        method: "POST",
        body: JSON.stringify({ completion_notes: "Completed via mobile UI" }),
      });
      setMsg(`Task #${taskId} submitted`);
      await loadAll();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div>
      <header className="page-hero">
        <div>
          <div className="eyebrow">Least-Privilege RBAC & Audit</div>
          <h2 className="page-title">{isOwner ? t.employeesAccess : t.myTasks}</h2>
          <p className="page-subtitle">
            Server-enforced location & action scoping with real-time Owner Access Preview.
          </p>
        </div>
      </header>
      {err && <div className="status-banner status-error">{err}</div>}
      {msg && <div className="status-banner status-ok">{msg}</div>}

      <section className="card" style={{ marginBlockEnd: "1rem" }}>
        <div className="eyebrow">Execution Accountability</div>
        <h3>{t.myTasks} ({tasks.length})</h3>
        {tasks.length === 0 ? (
          <p className="metric-foot">No tasks assigned.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.6rem" }}>
            {tasks.map((tk) => (
              <div key={String(tk.id)} className="card" style={{ background: "var(--surface-tint)", boxShadow: "none", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
                <div>
                  <strong>{String(tk.task_code)}</strong> — {String(tk.title)}{" "}
                  <span className="badge badge-normal">{String(tk.status)}</span>
                </div>
                {tk.status === "ASSIGNED" && (
                  <button type="button" className="btn btn-primary" onClick={() => submitTask(Number(tk.id))}>
                    {t.submitTask}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {isOwner && (
        <>
          <div className="card-grid">
            <form onSubmit={createEmployee} className="card">
              <div className="eyebrow">Staff Onboarding</div>
              <h3>Add Employee Account</h3>
              <div className="field">
                <label htmlFor="new-emp-code">Employee Code</label>
                <input id="new-emp-code" value={code} onChange={(e) => setCode(e.target.value)} required autoCorrect="off" autoCapitalize="characters" />
              </div>
              <div className="field">
                <label htmlFor="new-emp-name">Full Name</label>
                <input id="new-emp-name" value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div className="field">
                <label htmlFor="new-emp-pin">Numeric PIN (4+ digits)</label>
                <input id="new-emp-pin" type="password" inputMode="numeric" minLength={4} value={pin} onChange={(e) => setPin(e.target.value)} required />
              </div>
              <div className="field">
                <label htmlFor="new-emp-lang">Language</label>
                <select id="new-emp-lang" value={empLang} onChange={(e) => setEmpLang(e.target.value as Lang)}>
                  <option value="en">English</option>
                  <option value="hi">हिन्दी</option>
                  <option value="pa">ਪੰਜਾਬੀ</option>
                </select>
              </div>
              <button type="submit" className="btn btn-primary">Create Employee</button>
            </form>

            <section className="card">
              <div className="eyebrow">Live Server Policy Parity</div>
              <h3>Owner-Only Employee Access Preview</h3>
              <div className="field">
                <label htmlFor="sel-emp">Select Employee to Preview</label>
                <select id="sel-emp" value={preview?.employee_id || ""} onChange={(e) => selectEmployee(Number(e.target.value))}>
                  {employees.map((em) => (
                    <option key={em.id} value={em.id}>{em.employee_code} — {em.full_name}</option>
                  ))}
                </select>
              </div>
              {preview && (
                <div style={{ fontSize: "0.88rem" }}>
                  <p><strong>Visible Pages:</strong> {preview.visible_pages.join(", ") || "None"}</p>
                  <p><strong>Accessible Locations:</strong> {preview.accessible_locations.map((l) => l.code).join(", ") || "None"}</p>
                  <p><strong>Export Allowed:</strong> {preview.can_export ? "Yes" : "No (Blocked)"}</p>
                  <p><strong>Assigned Active Tasks:</strong> {preview.assigned_tasks.length}</p>
                  <div>
                    <strong>Toggle Allowed Actions (Enforced on Server):</strong>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginTop: "0.5rem" }}>
                      {preview.available_actions_catalog.map((act) => {
                        const enabled = preview.allowed_actions.includes(act);
                        return (
                          <button
                            key={act}
                            type="button"
                            className={`btn ${enabled ? "btn-primary" : "btn-secondary"}`}
                            style={{ minBlockSize: "38px", padding: "0.3rem 0.75rem", fontSize: "0.78rem" }}
                            onClick={() => toggleAction(act)}
                          >
                            {enabled ? "✓ " : ""}{act}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
            </section>
          </div>

          <section className="card">
            <div className="eyebrow">Cryptographic / Immutable Trail</div>
            <h3>Security & Operations Audit Log</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((l) => (
                    <tr key={String(l.id)}>
                      <td>{String(l.created_at).slice(0, 19)}</td>
                      <td>{String(l.actor_role || "SYSTEM")} #{String(l.actor_id || "-")}</td>
                      <td>{String(l.action)}</td>
                      <td>
                        <span className={`badge ${l.outcome === "SUCCESS" ? "badge-normal" : "badge-critical"}`}>{String(l.outcome)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
