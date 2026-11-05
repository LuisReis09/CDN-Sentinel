import { Pause, Play, RefreshCw, SlidersHorizontal, Telescope } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { MonitorStatus, SimulationStatus } from "../types";

interface ControlPanelProps {
  status: SimulationStatus;
  monitor: MonitorStatus;
  onRefresh: () => Promise<void>;
  onAction: () => Promise<void>;
  onError: (message: string) => void;
}

export function ControlPanel({ status, monitor, onRefresh, onAction, onError }: ControlPanelProps) {
  const config = status.configuration;
  const [form, setForm] = useState({
    num_servers: config.num_servers ?? 4,
    num_clients: config.num_clients ?? 32,
    malicious_probability: config.malicious_probability ?? 0.25,
    latency_factor: config.latency_factor ?? 1,
    tick_interval_seconds: config.tick_interval_seconds ?? 2.5,
    monthly_client_price_usd: config.monthly_client_price_usd ?? 25,
    monthly_server_cost_usd: config.monthly_server_cost_usd ?? 100,
    monthly_fixed_cost_usd: config.monthly_fixed_cost_usd ?? 150,
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setForm((current) => ({
      ...current,
      num_servers: config.num_servers ?? 4,
      num_clients: config.num_clients ?? 32,
      malicious_probability: config.malicious_probability ?? 0.25,
      latency_factor: config.latency_factor ?? 1,
      tick_interval_seconds: config.tick_interval_seconds ?? 2.5,
      monthly_client_price_usd: config.monthly_client_price_usd ?? 25,
      monthly_server_cost_usd: config.monthly_server_cost_usd ?? 100,
      monthly_fixed_cost_usd: config.monthly_fixed_cost_usd ?? 150,
    }));
  }, [config.num_servers, config.num_clients, config.malicious_probability, config.latency_factor, config.tick_interval_seconds, config.monthly_client_price_usd, config.monthly_server_cost_usd, config.monthly_fixed_cost_usd]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await onRefresh();
      await onAction();
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Falha no controle");
    } finally {
      setBusy(false);
    }
  }

  function update(name: keyof typeof form, value: number) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  const monitorCount = Object.values(monitor.per_server ?? {}).filter((item) => item.automatic).length;
  const tickInterval = Math.max(0.25, form.tick_interval_seconds || 2.5);

  return (
    <aside className="control-panel panel">
      <div className="panel-heading"><div><p className="eyebrow">CONTROL PLANE</p><h2>Orquestração</h2></div><SlidersHorizontal size={18} className="muted" /></div>
      <div className="control-status"><span className={`status-dot ${status.paused ? "status-paused" : "status-live"}`} /> {status.paused ? "Simulação pausada" : status.initialized ? "Simulação em execução" : "Aguardando inicialização"}</div>
      <div className="monitor-status"><Telescope size={14} /><span><strong>{monitorCount} monitores de servidor ativos</strong><small>próximo ciclo em {tickInterval.toFixed(2)}s · {monitor.pending_leaks ?? 0} pendência(s)</small></span></div>
      <div className="form-grid">
        <NumericField label="Servidores" value={form.num_servers} integer onValueChange={(value) => update("num_servers", value)} />
        <NumericField label="Clientes" value={form.num_clients} integer onValueChange={(value) => update("num_clients", value)} />
        <NumericField label="Prob. malícia" value={form.malicious_probability} onValueChange={(value) => update("malicious_probability", value)} />
        <NumericField label="Fator de latência" value={form.latency_factor} onValueChange={(value) => update("latency_factor", value)} />
        <NumericField label="Intervalo do tick (segundos)" value={form.tick_interval_seconds} onValueChange={(value) => update("tick_interval_seconds", value)} />
        <small className="tick-hint">O tick é o relógio do sistema. A cada tick, cada cliente tem 20% de chance de alternar login/logout.</small>
        <NumericField label="Preço cliente/mês (USD)" value={form.monthly_client_price_usd} onValueChange={(value) => update("monthly_client_price_usd", value)} />
      </div>
      <details className="advanced-economics"><summary>Custos da infraestrutura (USD)</summary><div className="form-grid"><NumericField label="Custo por servidor/mês (USD)" value={form.monthly_server_cost_usd} onValueChange={(value) => update("monthly_server_cost_usd", value)} /><NumericField label="Custo fixo/mês (USD)" value={form.monthly_fixed_cost_usd} onValueChange={(value) => update("monthly_fixed_cost_usd", value)} /></div></details>
      <div className="control-actions"><button className="button button-primary" disabled={busy} onClick={() => void run(() => api.initialize({ ...form, base_node_port: status.configuration.base_node_port || 5101, base_client_port: status.configuration.base_client_port || 6101 }))}><RefreshCw size={15} /> Inicializar</button>{status.paused ? <button className="button button-secondary" disabled={busy} onClick={() => void run(api.resume)}><Play size={15} /> Retomar</button> : <button className="button button-secondary" disabled={busy || !status.initialized} onClick={() => void run(api.pause)}><Pause size={15} /> Pausar</button>}</div>
      <p className="control-feedback"><Telescope size={13} /> Cada CDN monitora sua própria fila; a blacklist só fica distribuída após gossip.</p>
    </aside>
  );
}

function NumericField({ label, value, integer = false, onValueChange }: { label: string; value: number; integer?: boolean; onValueChange: (value: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);

  function handleChange(next: string) {
    const sanitized = sanitizeNumericText(next, integer);
    setText(sanitized);
    if (sanitized !== "" && sanitized !== ".") onValueChange(Number(sanitized));
  }

  return <label>{label}<input type="text" inputMode={integer ? "numeric" : "decimal"} value={text} onChange={(event) => handleChange(event.target.value)} onKeyDown={(event) => { if (["e", "E", "+", "-"].includes(event.key)) event.preventDefault(); }} /></label>;
}

function sanitizeNumericText(value: string, integer: boolean) {
  const normalized = value.replace(",", ".").replace(/[^0-9.]/g, "");
  if (integer) return normalized.replace(/\./g, "");
  const [whole, ...fraction] = normalized.split(".");
  return fraction.length ? `${whole}.${fraction.join("")}` : whole;
}
