import {
  Ban,
  CircleHelp,
  Fingerprint,
  FlaskConical,
  History,
  LayoutDashboard,
  Menu,
  Radio,
  Shield,
  Wifi,
  X,
} from "lucide-react";
import { useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { ManagementPage } from "./pages/ManagementPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NetworkLabPage } from "./pages/NetworkLabPage";
import { SecurityPage } from "./pages/SecurityPage";
import { WatermarkPage } from "./pages/WatermarkPage";
import { useDashboardData } from "./hooks/useDashboardData";

export function App() {
  const data = useDashboardData();
  const [notice, setNotice] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mode, setMode] = useState<"orchestration" | "gamification">(() => {
    try {
      return window.localStorage.getItem("cdn-sentinel:mode") === "gamification"
        ? "gamification"
        : "orchestration";
    } catch {
      return "orchestration";
    }
  });
  const onRefresh = async () => {
    await data.refresh();
  };
  function changeMode(nextMode: "orchestration" | "gamification") {
    setMode(nextMode);
    try {
      window.localStorage.setItem("cdn-sentinel:mode", nextMode);
    } catch {
      // Local storage is optional; the selector still works for this session.
    }
  }
  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">
            <Radio size={18} />
          </span>
          <span>
            <strong>CDN//SECURITY</strong>
            <small>control room</small>
          </span>
          <button
            className="mobile-close"
            onClick={() => setSidebarOpen(false)}
            aria-label="Fechar menu"
          >
            <X size={18} />
          </button>
        </div>
        <div className="sidebar-section">
          <p className="eyebrow">OPERATIONS</p>
          <NavItem to="/" icon={LayoutDashboard} label="Command center" />
          <NavItem to="/dashboard" icon={History} label="Simulation history" />
          <NavItem to="/network-lab" icon={FlaskConical} label="Network lab" />
          <NavItem to="/security" icon={Shield} label="Security observatory" />
          <NavItem
            to="/watermark"
            icon={Fingerprint}
            label="Watermark studio"
          />
        </div>
        <div className="sidebar-section">
          <p className="eyebrow">SIGNALS</p>
          <div className="sidebar-signal">
            <span
              className={`status-dot ${data.connected ? "status-live" : "status-offline"}`}
            />
            <span>
              <strong>Global mesh</strong>
              <small>{data.overview.servers.length || 0} nós observados</small>
            </span>
          </div>
        </div>
        <div className="sidebar-footer">
          <CircleHelp size={15} />
          <span>
            API docs em <code>/docs</code>
          </span>
        </div>
      </aside>
      <div className="main-shell">
        {data.loading && <div className="app-loading-strip" role="status">Conectando ao control plane…</div>}
        <header className="topbar">
          <button
            className="mobile-menu"
            onClick={() => setSidebarOpen(true)}
            aria-label="Abrir menu"
          >
            <Menu size={19} />
          </button>
          <Link to="/" className="breadcrumb">
            <span>PROJECT</span>
            <strong>forensic-cdn /</strong>
            <em>operations</em>
          </Link>
          <div className="topbar-actions">
            <div className="mode-switch" aria-label="Modo de operação">
              <button
                className={mode === "orchestration" ? "mode-switch__active" : ""}
                aria-pressed={mode === "orchestration"}
                onClick={() => changeMode("orchestration")}
              >
                Orquestração
              </button>
              <button
                className={mode === "gamification" ? "mode-switch__active" : ""}
                aria-pressed={mode === "gamification"}
                onClick={() => changeMode("gamification")}
              >
                Gamificação
              </button>
            </div>
            <span
              className={`connection-chip ${data.freshness.toLowerCase()}`}
              title={data.error ?? "Última atualização da API"}
            >
              <Wifi size={14} /> {data.freshness}
            </span>
            <span className="environment-chip">LOCAL SIMULATION</span>
          </div>
        </header>
        {notice && (
          <button className="toast" onClick={() => setNotice(null)}>
            {notice}
            <X size={14} />
          </button>
        )}
        <Routes>
          <Route
            path="/"
            element={
              mode === "gamification" ? (
                <ManagementPage
                  overview={data.overview}
                  connected={data.connected}
                  onRefresh={onRefresh}
                  onError={setNotice}
                />
              ) : (
                <DashboardPage
                  overview={data.overview}
                  connected={data.connected}
                  onRefresh={onRefresh}
                  onAction={onRefresh}
                  onError={setNotice}
                />
              )
            }
          />
          <Route path="/dashboard" element={<HistoryPage />} />
          <Route
            path="/network-lab"
            element={
              <NetworkLabPage
                overview={data.overview}
                onRefresh={onRefresh}
                onError={setNotice}
              />
            }
          />
          <Route
            path="/security"
            element={
              <SecurityPage
                overview={data.overview}
                onRefresh={onRefresh}
                onError={setNotice}
              />
            }
          />
          <Route
            path="/watermark"
            element={
              <WatermarkPage overview={data.overview} onError={setNotice} />
            }
          />
        </Routes>
      </div>
    </div>
  );
}

function NavItem({
  to,
  icon: Icon,
  label,
}: {
  to: string;
  icon: LucideIcon;
  label: string;
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `nav-item ${isActive ? "nav-item-active" : ""}`
      }
    >
      <Icon size={16} />
      <span>{label}</span>
      {to === "/security" && <Ban size={13} className="nav-hint" />}
    </NavLink>
  );
}

