import {
  Pause,
  Play,
  Power,
  RefreshCw,
  SlidersHorizontal,
  Telescope,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { MonitorStatus, SimulationStatus } from "../types";

interface ControlPanelProps {
  status: SimulationStatus;
  monitor: MonitorStatus;
  onRefresh: () => Promise<void>;
  onAction: () => Promise<void>;
  onError: (message: string) => void;
  onEnded?: (simulationId?: string) => void;
}

export function ControlPanel({
  status,
  monitor,
  onRefresh,
  onAction,
  onError,
  onEnded,
}: ControlPanelProps) {
  const config = status.configuration;
  const [form, setForm] = useState({
    num_servers: config.num_servers > 0 ? config.num_servers : 4,
    num_clients: config.num_clients > 0 ? config.num_clients : 32,
    malicious_probability: config.malicious_probability ?? 0.25,
    latency_factor: config.latency_factor ?? 1,
    tick_interval_seconds: config.tick_interval_seconds ?? 2.5,
    monthly_client_price_usd: config.monthly_client_price_usd ?? 25,
    monthly_server_cost_usd: config.monthly_server_cost_usd ?? 100,
    monthly_fixed_cost_usd: config.monthly_fixed_cost_usd ?? 150,
  });
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [initProgress, setInitProgress] = useState({
    in_progress: false,
    progress_pct: 0,
    phase: "idle",
    detail: "",
  });

  useEffect(() => {
    setForm((current) => ({
      ...current,
      num_servers: config.num_servers > 0 ? config.num_servers : 4,
      num_clients: config.num_clients > 0 ? config.num_clients : 32,
      malicious_probability: config.malicious_probability ?? 0.25,
      latency_factor: config.latency_factor ?? 1,
      tick_interval_seconds: config.tick_interval_seconds ?? 2.5,
      monthly_client_price_usd: config.monthly_client_price_usd ?? 25,
      monthly_server_cost_usd: config.monthly_server_cost_usd ?? 100,
      monthly_fixed_cost_usd: config.monthly_fixed_cost_usd ?? 150,
    }));
  }, [
    config.num_servers,
    config.num_clients,
    config.malicious_probability,
    config.latency_factor,
    config.tick_interval_seconds,
    config.monthly_client_price_usd,
    config.monthly_server_cost_usd,
    config.monthly_fixed_cost_usd,
  ]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await onRefresh();
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Falha no controle");
    } finally {
      setBusy(false);
    }
  }

  async function initializeSimulation() {
    const errors = validateForm(form);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;
    setBusy(true);
    setInitProgress({
      in_progress: true,
      progress_pct: 1,
      phase: "starting",
      detail: "Enviando configuração ao backend",
    });
    const poller = window.setInterval(() => {
      void api.status()
        .then((next) => {
          if (next.initialization) setInitProgress(next.initialization);
        })
        .catch(() => undefined);
    }, 500);
    try {
      await api.initialize({
        ...form,
        tick_interval_seconds: tickInterval,
        base_node_port: status.configuration.base_node_port || 5101,
        base_client_port: status.configuration.base_client_port || 6101,
      });
      setInitProgress({
        in_progress: false,
        progress_pct: 100,
        phase: "ready",
        detail: "Simulação pronta",
      });
      await onRefresh();
    } catch (cause) {
      setInitProgress((current) => ({ ...current, in_progress: false }));
      onError(
        cause instanceof Error
          ? cause.message
          : "Não foi possível iniciar. Revise os parâmetros e tente novamente.",
      );
    } finally {
      window.clearInterval(poller);
      setBusy(false);
    }
  }

  async function endSimulation() {
    setBusy(true);
    try {
      const result = await api.end();
      // Do not persist the complete archive in browser storage: a large
      // client sample can exceed the sessionStorage quota. The backend
      // archives the run and the dashboard reads that authoritative snapshot.
      try {
        window.sessionStorage.removeItem("cdn-sentinel:last-ended-simulation");
      } catch {
        // Storage can be disabled by the browser; the redirect still works.
      }
      await onRefresh();
      if (onEnded) onEnded(result.simulation_id);
      else
        window.location.assign(
          `/dashboard?simulation_id=${encodeURIComponent(result.simulation_id)}`,
        );
    } catch (cause) {
      onError(
        cause instanceof Error
          ? cause.message
          : "Falha ao encerrar a simulação",
      );
    } finally {
      setBusy(false);
    }
  }

  function update(name: keyof typeof form, value: number) {
    setForm((current) => ({ ...current, [name]: value }));
    setFieldErrors((current) => {
      if (!current[name]) return current;
      const next = { ...current };
      delete next[name];
      return next;
    });
  }

  const monitorCount = Object.values(monitor.per_server ?? {}).filter(
    (item) => item.automatic,
  ).length;
  const tickInterval = Math.max(
    0.5,
    Math.min(5, form.tick_interval_seconds || 2.5),
  );
  const activeSimulation =
    status.initialized &&
    !["idle", "ended", "error"].includes(status.lifecycle);

  return (
    <aside className="control-panel panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">CONTROL PLANE</p>
          <h2>Orquestração</h2>
        </div>
        <SlidersHorizontal size={18} className="muted" />
      </div>
      <div className="control-status">
        <span
          className={`status-dot ${status.paused ? "status-paused" : status.lifecycle === "ended" ? "status-stopped" : status.lifecycle === "error" ? "status-offline" : "status-live"}`}
        />{" "}
        {status.paused
          ? "Simulação pausada"
          : status.lifecycle === "ended"
            ? "Simulação encerrada"
            : status.initialized
              ? `Simulação ${status.lifecycle}`
              : "Aguardando inicialização"}
      </div>
      <div className="monitor-status">
        <Telescope size={14} />
        <span>
          <strong>{monitorCount} monitores de servidor ativos</strong>
          <small>
            próximo ciclo em {tickInterval.toFixed(1)}s ·{" "}
            {monitor.pending_leaks ?? 0} pendência(s)
          </small>
        </span>
      </div>
      <div className="form-grid">
        <NumericField
          label="Servidores"
          value={form.num_servers}
          integer
          min={1}
          max={500}
          error={fieldErrors.num_servers}
          onValueChange={(value) => update("num_servers", value)}
        />
        <NumericField
          label="Clientes"
          value={form.num_clients}
          integer
          min={1}
          max={100000}
          error={fieldErrors.num_clients}
          onValueChange={(value) => update("num_clients", value)}
        />
        <NumericField
          label="Prob. malícia"
          value={form.malicious_probability}
          onValueChange={(value) => update("malicious_probability", value)}
        />
        <NumericField
          label="Fator de latência"
          value={form.latency_factor}
          onValueChange={(value) => update("latency_factor", value)}
        />
        <label className="range-field">
          <span>
            Intervalo do tick <b>{tickInterval.toFixed(1)} s</b>
          </span>
          <input
            type="range"
            min="0.5"
            max="5"
            step="0.5"
            value={tickInterval}
            onChange={(event) =>
              update("tick_interval_seconds", Number(event.target.value))
            }
          />
          <small>0,5 a 5,0 segundos</small>
        </label>
        <small className="tick-hint">
          O tick é o relógio do sistema. A cada tick, cada cliente tem 20% de
          chance de alternar login/logout.
        </small>
      </div>
      {initProgress.in_progress && (
        <div className="initialization-progress" role="status" aria-live="polite">
          <div className="initialization-progress__heading">
            <span>{initProgress.detail || "Preparando simulação"}</span>
            <b>{Math.round(initProgress.progress_pct)}%</b>
          </div>
          <div className="initialization-progress__track">
            <i style={{ width: `${Math.min(100, Math.max(2, initProgress.progress_pct))}%` }} />
          </div>
          <small>O dashboard será atualizado quando a malha estiver pronta.</small>
        </div>
      )}
      <details className="advanced-economics">
        <summary>Custos e precificação da infraestrutura (USD)</summary>
        <div className="form-grid">
          <NumericField
            label="Preço cliente/mês"
            value={form.monthly_client_price_usd}
            onValueChange={(value) => update("monthly_client_price_usd", value)}
          />
          <NumericField
            label="Custo por servidor/mês"
            value={form.monthly_server_cost_usd}
            onValueChange={(value) => update("monthly_server_cost_usd", value)}
          />
          <NumericField
            label="Custo fixo/mês"
            value={form.monthly_fixed_cost_usd}
            onValueChange={(value) => update("monthly_fixed_cost_usd", value)}
          />
        </div>
      </details>
      <div className="control-actions">
        {activeSimulation ? (
          <button
            className="button button-danger"
            disabled={busy}
            onClick={() => void endSimulation()}
          >
            <Power size={15} /> Encerrar
          </button>
        ) : (
          <button
            className="button button-primary"
            disabled={busy}
            onClick={() => void initializeSimulation()}
          >
            <RefreshCw size={15} /> Inicializar
          </button>
        )}
        {status.paused ? (
          <button
            className="button button-secondary"
            disabled={busy}
            onClick={() => void run(api.resume)}
          >
            <Play size={15} /> Retomar
          </button>
        ) : (
          <button
            className="button button-secondary"
            disabled={busy || !activeSimulation}
            onClick={() => void run(api.pause)}
          >
            <Pause size={15} /> Pausar
          </button>
        )}
      </div>
      <p className="control-feedback">
        <Telescope size={13} /> Cada CDN monitora sua própria fila; a blacklist
        só fica distribuída após gossip. Ao encerrar, o histórico abre em
        /dashboard.
      </p>
    </aside>
  );
}

function NumericField({
  label,
  value,
  integer = false,
  min,
  max,
  error,
  onValueChange,
}: {
  label: string;
  value: number;
  integer?: boolean;
  min?: number;
  max?: number;
  error?: string;
  onValueChange: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);

  function handleChange(next: string) {
    const sanitized = sanitizeNumericText(next, integer);
    setText(sanitized);
    if (sanitized !== "" && sanitized !== ".") onValueChange(Number(sanitized));
  }

  return (
    <label className={error ? "field-error" : undefined}>
      {label}
      <input
        type="text"
        inputMode={integer ? "numeric" : "decimal"}
        value={text}
        min={min}
        max={max}
        aria-invalid={Boolean(error)}
        onChange={(event) => handleChange(event.target.value)}
        onKeyDown={(event) => {
          if (["e", "E", "+", "-"].includes(event.key)) event.preventDefault();
        }}
      />
      {error && <small className="field-error-message">{error}</small>}
    </label>
  );
}

function validateForm(form: {
  num_servers: number;
  num_clients: number;
  malicious_probability: number;
  latency_factor: number;
  tick_interval_seconds: number;
  monthly_client_price_usd: number;
  monthly_server_cost_usd: number;
  monthly_fixed_cost_usd: number;
}) {
  const errors: Record<string, string> = {};
  if (!Number.isInteger(form.num_servers) || form.num_servers < 1 || form.num_servers > 500) {
    errors.num_servers = "Use de 1 a 500 servidores.";
  }
  if (!Number.isInteger(form.num_clients) || form.num_clients < 1 || form.num_clients > 100000) {
    errors.num_clients = "Use de 1 a 100.000 clientes.";
  }
  if (!Number.isFinite(form.malicious_probability) || form.malicious_probability < 0 || form.malicious_probability > 1) {
    errors.malicious_probability = "Use um valor entre 0 e 1.";
  }
  if (!Number.isFinite(form.latency_factor) || form.latency_factor < 0 || form.latency_factor > 20) {
    errors.latency_factor = "Use um valor entre 0 e 20.";
  }
  if (!Number.isFinite(form.tick_interval_seconds) || form.tick_interval_seconds < 0.5 || form.tick_interval_seconds > 5) {
    errors.tick_interval_seconds = "Use um intervalo entre 0,5 e 5 segundos.";
  }
  return errors;
}

function sanitizeNumericText(value: string, integer: boolean) {
  const normalized = value.replace(",", ".").replace(/[^0-9.]/g, "");
  if (integer) return normalized.replace(/[.]/g, "");
  const [whole, ...fraction] = normalized.split(".");
  return fraction.length ? `${whole}.${fraction.join("")}` : whole;
}
