import React, { useEffect, useState } from "react";
import { api, AuthUser, EffectiveAccess } from "../api/client";
import { Lang, TRANSLATIONS } from "../i18n/translations";

interface Props {
  lang: Lang;
  onLangChange: (l: Lang) => void;
  onAuthenticated: (user: AuthUser, access: EffectiveAccess) => void;
}

export function AuthView({ lang, onLangChange, onAuthenticated }: Props) {
  const t = TRANSLATIONS[lang];
  const [ownerInit, setOwnerInit] = useState<boolean | null>(null);
  const [mfaRequired, setMfaRequired] = useState<boolean>(true);
  const [enableMfaOnSetup, setEnableMfaOnSetup] = useState<boolean>(true);
  const [mode, setMode] = useState<"owner" | "employee">("owner");
  const [error, setError] = useState<string | null>(null);
  const [setupSecrets, setSetupSecrets] = useState<{ totp_secret: string; totp_uri: string; recovery_codes: string[] } | null>(null);

  // Bootstrap fields
  const [bootEmail, setBootEmail] = useState("");
  const [bootName, setBootName] = useState("");
  const [bootPass, setBootPass] = useState("");

  // Owner login
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");

  // Employee login
  const [empCode, setEmpCode] = useState("");
  const [pin, setPin] = useState("");

  useEffect(() => {
    api
      .request<{ owner_initialized: boolean; owner_mfa_enabled: boolean }>("/api/v1/auth/bootstrap-status")
      .then((res) => {
        setOwnerInit(res.owner_initialized);
        setMfaRequired(res.owner_mfa_enabled);
      })
      .catch(() => setOwnerInit(true));
  }, []);

  async function handleBootstrap(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await api.request<{ totp_secret: string | null; totp_uri: string | null; recovery_codes: string[] }>("/api/v1/auth/bootstrap-owner", {
        method: "POST",
        body: JSON.stringify({ email: bootEmail, full_name: bootName, password: bootPass, enable_mfa: enableMfaOnSetup }),
      });
      if (res.totp_secret && res.totp_uri) {
        setSetupSecrets({ totp_secret: res.totp_secret, totp_uri: res.totp_uri, recovery_codes: res.recovery_codes });
      }
      setMfaRequired(enableMfaOnSetup);
      setOwnerInit(true);
      setEmail(bootEmail);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleOwnerLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await api.request<{ access_token: string; user: AuthUser }>("/api/v1/auth/owner/login", {
        method: "POST",
        body: JSON.stringify({ email, password, totp_code: totpCode.trim() || null }),
      });
      api.setToken(res.access_token);
      const me = await api.request<{ user: AuthUser; effective_access: EffectiveAccess }>("/api/v1/auth/me");
      onAuthenticated(me.user, me.effective_access);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleEmployeeLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await api.request<{ access_token: string; user: AuthUser; effective_access: EffectiveAccess }>("/api/v1/auth/employee/login", {
        method: "POST",
        body: JSON.stringify({ employee_code: empCode, pin }),
      });
      api.setToken(res.access_token);
      onAuthenticated(res.user, res.effective_access);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <main className="auth-wrap">
      <div className="auth-card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBlockEnd: "1rem" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{t.appTitle}</h1>
            <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)" }}>{t.appSubtitle}</p>
          </div>
          <select aria-label={t.language} value={lang} onChange={(e) => onLangChange(e.target.value as Lang)} style={{ inlineSize: "auto" }}>
            <option value="en">English</option>
            <option value="hi">हिन्दी</option>
            <option value="pa">ਪੰਜਾਬੀ</option>
          </select>
        </div>

        {error && (
          <div className="status-banner status-error" role="alert">
            {error}
          </div>
        )}

        {setupSecrets && (
          <div className="status-banner status-ok" role="status">
            <strong>Owner Account Initialized. Save MFA Secret & Recovery Codes Now:</strong>
            <div style={{ fontSize: "0.82rem", marginTop: "0.4rem", wordBreak: "break-all" }}>
              <div>TOTP Secret: <code>{setupSecrets.totp_secret}</code></div>
              <div>Recovery Codes: <code>{setupSecrets.recovery_codes.join(", ")}</code></div>
            </div>
          </div>
        )}

        {ownerInit === false ? (
          <form onSubmit={handleBootstrap}>
            <h2>Initial Owner Setup (One-Time)</h2>
            <div className="field">
              <label htmlFor="boot-name">Owner Full Name</label>
              <input id="boot-name" value={bootName} onChange={(e) => setBootName(e.target.value)} required autoComplete="name" />
            </div>
            <div className="field">
              <label htmlFor="boot-email">Verified Business Email</label>
              <input id="boot-email" type="email" value={bootEmail} onChange={(e) => setBootEmail(e.target.value)} required autoComplete="username" />
            </div>
            <div className="field">
              <label htmlFor="boot-pass">Strong Password (min 10 chars)</label>
              <input id="boot-pass" type="password" minLength={10} value={bootPass} onChange={(e) => setBootPass(e.target.value)} required autoComplete="new-password" />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBlockEnd: "1rem" }}>
              <input id="boot-mfa" type="checkbox" checked={enableMfaOnSetup} onChange={(e) => setEnableMfaOnSetup(e.target.checked)} style={{ inlineSize: "20px", minBlockSize: "20px" }} />
              <label htmlFor="boot-mfa">Enable TOTP MFA (Recommended for production)</label>
            </div>
            <button type="submit" className="btn btn-primary" style={{ inlineSize: "100%" }}>
              Initialize Verified Owner Account
            </button>
          </form>
        ) : (
          <>
            <div style={{ display: "flex", gap: "0.5rem", marginBlockEnd: "1rem" }}>
              <button type="button" className={`btn ${mode === "owner" ? "btn-primary" : "btn-secondary"}`} style={{ flex: 1 }} onClick={() => setMode("owner")}>
                {t.ownerLogin}
              </button>
              <button type="button" className={`btn ${mode === "employee" ? "btn-primary" : "btn-secondary"}`} style={{ flex: 1 }} onClick={() => setMode("employee")}>
                {t.employeeLogin}
              </button>
            </div>

            {mode === "owner" ? (
              <form onSubmit={handleOwnerLogin}>
                <div className="field">
                  <label htmlFor="owner-email">Business Email</label>
                  <input id="owner-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" autoCorrect="off" autoCapitalize="none" spellCheck={false} />
                </div>
                <div className="field">
                  <label htmlFor="owner-pass">Password</label>
                  <input id="owner-pass" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
                </div>
                {mfaRequired && (
                  <div className="field">
                    <label htmlFor="owner-totp">6-Digit Authenticator MFA Code</label>
                    <input id="owner-totp" type="text" inputMode="numeric" pattern="\d{6}" maxLength={6} value={totpCode} onChange={(e) => setTotpCode(e.target.value)} required autoComplete="one-time-code" />
                  </div>
                )}
                <button type="submit" className="btn btn-primary" style={{ inlineSize: "100%" }}>
                  {t.ownerLogin}
                </button>
              </form>
            ) : (
              <form onSubmit={handleEmployeeLogin}>
                <div className="field">
                  <label htmlFor="emp-code">Employee Code</label>
                  <input id="emp-code" type="text" value={empCode} onChange={(e) => setEmpCode(e.target.value)} required autoCorrect="off" autoCapitalize="characters" spellCheck={false} />
                </div>
                <div className="field">
                  <label htmlFor="emp-pin">Employee PIN</label>
                  <input id="emp-pin" type="password" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value)} required />
                </div>
                <button type="submit" className="btn btn-primary" style={{ inlineSize: "100%" }}>
                  {t.employeeLogin}
                </button>
              </form>
            )}
          </>
        )}
      </div>
    </main>
  );
}

