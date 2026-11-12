import React, { useEffect, useState } from "react";
import { api, AuthUser, EffectiveAccess } from "./api/client";
import { IconBox, IconGrid, IconLayers, IconRupee, IconShield, IconSpark } from "./components/Icons";
import { Lang, TRANSLATIONS } from "./i18n/translations";
import { AssemblyReturnsPage } from "./pages/AssemblyReturnsPage";
import { AuthView } from "./pages/AuthView";
import { CommandCentrePage } from "./pages/CommandCentrePage";
import { EmployeesAccessPage } from "./pages/EmployeesAccessPage";
import { IntelligenceLogisticsPage } from "./pages/IntelligenceLogisticsPage";
import { InventoryWarehousePage } from "./pages/InventoryWarehousePage";
import { MarketplacesFinancePage } from "./pages/MarketplacesFinancePage";

export type NavKey =
  | "command_centre"
  | "inventory"
  | "assembly"
  | "marketplaces"
  | "employees"
  | "intelligence";

export function App() {
  const [lang, setLang] = useState<Lang>("en");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [access, setAccess] = useState<EffectiveAccess | null>(null);
  const [authMode, setAuthMode] = useState<"enforced" | "local_preview_no_auth">("enforced");
  const [activeNav, setActiveNav] = useState<NavKey>("command_centre");
  const [checkingSession, setCheckingSession] = useState(true);

  const t = TRANSLATIONS[lang];

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    api
      .request<{ auth_mode?: "enforced" | "local_preview_no_auth"; user: AuthUser; effective_access: EffectiveAccess }>("/api/v1/auth/me")
      .then((res) => {
        setAuthMode(res.auth_mode || "enforced");
        setUser(res.user);
        setAccess(res.effective_access);
        setLang(res.user.preferred_language || "en");
        if (res.user.role !== "OWNER") {
          setActiveNav("inventory");
        }
      })
      .catch(() => {
        setUser(null);
      })
      .finally(() => setCheckingSession(false));
  }, []);

  async function handleLogout() {
    try {
      await api.request("/api/v1/auth/logout", { method: "POST" });
    } catch {
      // ignore
    }
    api.setToken(null);
    setUser(null);
    setAccess(null);
  }

  if (checkingSession) {
    return (
      <main className="auth-wrap">
        <div className="card">Loading BOSS Workspace...</div>
      </main>
    );
  }

  if (!user || !access) {
    return (
      <AuthView
        lang={lang}
        onLangChange={setLang}
        onAuthenticated={(u, eff) => {
          setUser(u);
          setAccess(eff);
          setLang(u.preferred_language || "en");
          setActiveNav(u.role === "OWNER" ? "command_centre" : "inventory");
        }}
      />
    );
  }

  const isOwner = user.role === "OWNER";
  const allNavItems: Array<{ key: NavKey; label: string; shortLabel: string; icon: React.ReactNode; visible: boolean }> = [
    { key: "command_centre", label: t.commandCentre, shortLabel: "Overview", icon: <IconGrid />, visible: isOwner },
    {
      key: "inventory",
      label: t.inventoryWarehouse,
      shortLabel: "Inventory",
      icon: <IconBox />,
      visible: isOwner || access.visible_pages.includes("warehouse") || access.visible_pages.includes("inventory"),
    },
    {
      key: "assembly",
      label: t.assemblyReturns,
      shortLabel: "Assembly",
      icon: <IconLayers />,
      visible: isOwner || access.visible_pages.includes("assembly") || access.visible_pages.includes("returns"),
    },
    { key: "marketplaces", label: t.marketplacesFinance, shortLabel: "Finance", icon: <IconRupee />, visible: isOwner },
    { key: "employees", label: isOwner ? t.employeesAccess : t.myTasks, shortLabel: "Team", icon: <IconShield />, visible: true },
    { key: "intelligence", label: t.intelligenceLogistics, shortLabel: "AI & Ops", icon: <IconSpark />, visible: isOwner },
  ];
  const navItems = allNavItems.filter((item) => item.visible);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary Navigation">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">b.</div>
          <div>
            <h1>{t.appTitle}</h1>
            <p>Business Operating Smart System</p>
          </div>
        </div>
        {navItems.map((item) => (
          <button
            key={item.key}
            type="button"
            className="nav-btn"
            aria-current={activeNav === item.key ? "page" : undefined}
            onClick={() => setActiveNav(item.key)}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </aside>

      <header className="app-header">
        <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", minInlineSize: 0 }}>
          <div className="mobile-brand">
            <div className="brand-mark" style={{ inlineSize: "34px", blockSize: "34px", fontSize: "1rem" }} aria-hidden="true">b.</div>
            <strong style={{ letterSpacing: "0.04em" }}>{t.appTitle}</strong>
          </div>
          <span className="badge badge-dark">{user.full_name.split(" ")[0]}</span>
          {authMode === "local_preview_no_auth" && (
            <span className="badge badge-normal">● Local</span>
          )}
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <select
            aria-label={t.language}
            value={lang}
            onChange={(e) => setLang(e.target.value as Lang)}
            style={{ inlineSize: "auto", minBlockSize: "40px", paddingBlock: "0.35rem", fontSize: "0.88rem" }}
          >
            <option value="en">English</option>
            <option value="hi">हिन्दी</option>
            <option value="pa">ਪੰਜਾਬੀ</option>
          </select>
          {authMode !== "local_preview_no_auth" && (
            <button type="button" className="btn btn-secondary" style={{ minBlockSize: "40px", paddingBlock: "0.35rem" }} onClick={handleLogout}>
              {t.logout}
            </button>
          )}
        </div>
      </header>

      <main className="main-content">
        {activeNav === "command_centre" && isOwner && (
          <CommandCentrePage lang={lang} ownerName={user.full_name} onNavigate={setActiveNav} />
        )}
        {activeNav === "inventory" && <InventoryWarehousePage lang={lang} isOwner={isOwner} />}
        {activeNav === "assembly" && <AssemblyReturnsPage lang={lang} />}
        {activeNav === "marketplaces" && isOwner && <MarketplacesFinancePage lang={lang} />}
        {activeNav === "employees" && <EmployeesAccessPage lang={lang} isOwner={isOwner} />}
        {activeNav === "intelligence" && isOwner && <IntelligenceLogisticsPage lang={lang} />}
      </main>

      <nav className="mobile-nav" aria-label="Mobile Navigation">
        {navItems.map((item) => (
          <button
            key={item.key}
            type="button"
            className="nav-btn"
            aria-current={activeNav === item.key ? "page" : undefined}
            onClick={() => setActiveNav(item.key)}
          >
            {item.icon}
            <span>{item.shortLabel}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
