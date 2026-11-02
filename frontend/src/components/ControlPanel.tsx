import { Pause, Play, Radar, RefreshCw, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { SimulationStatus } from "../types";

interface ControlPanelProps {
  status: SimulationStatus;
  onRefresh: () => Promise<void>;
  onAction: () => Promise<void>;
  onError: (message: string) => void;
}

export function ControlPanel({ status, onRefresh, onAction, onError }: ControlPanelProps) {
  const [form, setForm] = useState({
    num_servers: status.configuration.num_servers || 4,
    num_clients: status.configuration.num_clients || 32,
    malicious_probability: status.configuration.malicious_probability,
    latency_factor: status.configuration.latency_factor,
  });
  const [busy, setBusy] = useState(false);
  const [scanMessage, setScanMessage] = useState("");

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try { await action(); setScanMessage(""); await onRefresh(); await onAction(); } catch (cause) { onError(cause instanceof Error ? cause.message : "Falha no controle"); } finally { setBusy(false); }
  }

  async function runScan() {
    setBusy(true);
    try {
      const result = await api.scan();
      setScanMessage(`Varredura concluída: ${result.detected.length} detectado(s), ${result.rejected.length} rejeitado(s).`);
      await onRefresh();
      await onAction();
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Falha na varredura");
    } finally {
      setBusy(false);
    }
  }

  function update(name: keyof typeof form, value: number) { setForm((current) => ({ ...current, [name]: value })); }

  return (
    <aside className="control-panel panel">
      <div className="panel-heading"><div><p className="eyebrow">CONTROL PLANE</p><h2>Orquestração</h2></div><SlidersHorizontal size={18} className="muted" /></div>
      <div className="control-status"><span className={`status-dot ${status.paused ? "status-paused" : "status-live"}`} /> {status.paused ? "Simulação pausada" : status.initialized ? "Simulação em execução" : "Aguardando inicialização"}</div>
      <div className="form-grid">
        <label>Servidores<input type="number" min="1" max="20" value={form.num_servers} onChange={(event) => update("num_servers", Number(event.target.value))} /></label>
        <label>Clientes<input type="number" min="1" max="1000" value={form.num_clients} onChange={(event) => update("num_clients", Number(event.target.value))} /></label>
        <label>Prob. malícia<input type="number" min="0" max="1" step="0.05" value={form.malicious_probability} onChange={(event) => update("malicious_probability", Number(event.target.value))} /></label>
        <label>Fator de latência<input type="number" min="0" max="20" step="0.1" value={form.latency_factor} onChange={(event) => update("latency_factor", Number(event.target.value))} /></label>
      </div>
      <div className="control-actions">
        <button className="button button-primary" disabled={busy} onClick={() => void run(() => api.initialize({ ...form, base_node_port: status.configuration.base_node_port || 5101 }))}><RefreshCw size={15} /> Inicializar</button>
        {status.paused ? <button className="button button-secondary" disabled={busy} onClick={() => void run(api.resume)}><Play size={15} /> Retomar</button> : <button className="button button-secondary" disabled={busy || !status.initialized} onClick={() => void run(api.pause)}><Pause size={15} /> Pausar</button>}
        <button className="button button-ghost" disabled={busy || !status.initialized} onClick={() => void runScan()}><Radar size={15} /> Varredura</button>
      </div>
      {scanMessage && <p className="control-feedback"><Radar size={13} /> {scanMessage}</p>}
    </aside>
  );
}

