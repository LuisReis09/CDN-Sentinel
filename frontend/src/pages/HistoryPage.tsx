import { Activity, BarChart3, Clock3, Database, GitBranch, Server, ShieldCheck } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { TelemetryCharts } from "../components/TelemetryCharts";
import type { SimulationHistory } from "../types";

export function HistoryPage() {
  const [searchParams] = useSearchParams();
  const [histories, setHistories] = useState<SimulationHistory[]>([]);
  const [selectedId, setSelectedId] = useState(searchParams.get("simulation_id") ?? "");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.history()
      .then((result) => {
        if (cancelled) return;
        const remote = result.histories ?? [];
        setHistories(remote);
        if (!selectedId && remote.length) {
          setSelectedId(remote[remote.length - 1].simulation_id);
        }
        setError(null);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Falha ao carregar o histórico");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedId]);

  const history = histories.find((item) => item.simulation_id === selectedId) ?? histories[histories.length - 1];
  const duration = history?.started_at && history.ended_at ? Math.max(0, history.ended_at - history.started_at) : 0;
  const latencies = (history?.traffic ?? [])
    .map((item) => item.end_to_end_ms ?? item.http_rtt_ms ?? item.latency_ms ?? 0)
    .sort((a, b) => a - b);
  const p95 = latencies.length ? latencies[Math.min(latencies.length - 1, Math.ceil(latencies.length * 0.95) - 1)] : 0;
  const requestCount = history?.traffic.reduce((total, item) => total + (item.request_count ?? 1), 0) ?? 0;

  return (
    <main className="page-content history-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">OBSERVABILITY / ARCHIVED RUNS</p>
          <h1>Simulation history</h1>
          <p className="page-lead">Cada encerramento arquiva a topologia e as séries temporais observadas naquela execução.</p>
        </div>
        <div className="history-toolbar">
          <span className="lifecycle-chip"><Database size={13} /> {histories.length} execução(ões)</span>
          {histories.length > 0 && (
            <select value={history?.simulation_id ?? ""} onChange={(event) => setSelectedId(event.target.value)} aria-label="Selecionar simulação">
              {histories.map((item) => <option key={item.simulation_id} value={item.simulation_id}>{item.simulation_id} · {formatDate(item.ended_at)}</option>)}
            </select>
          )}
        </div>
      </header>
      {loading && <section className="panel history-empty">Carregando históricos arquivados...</section>}
      {error && <section className="panel history-empty">Não foi possível carregar o histórico: {error}</section>}
      {!loading && !error && !history && (
        <section className="panel history-empty"><BarChart3 size={22} /> Nenhuma simulação encerrada ainda.</section>
      )}
      {history && (
        <>
          <section className="history-cards">
            <HistoryCard icon={<Clock3 size={15} />} label="Duração" value={formatDuration(duration)} />
            <HistoryCard icon={<Activity size={15} />} label="Requisições" value={String(requestCount)} />
            <HistoryCard icon={<GitBranch size={15} />} label="Eventos" value={String(history.events.length)} />
            <HistoryCard icon={<ShieldCheck size={15} />} label="Blacklist" value={String(history.blacklist.length)} />
            <HistoryCard icon={<Server size={15} />} label="Nós / clientes" value={`${history.servers.length} / ${history.clients_total ?? history.clients.length}`} />
            <HistoryCard icon={<Activity size={15} />} label="P95 e2e" value={`${Number(p95).toFixed(1)} ms`} />
          </section>
          <TelemetryCharts samples={history.metrics_history ?? []} />
          <section className="panel history-final-topology">
            <div className="panel-heading">
              <div><p className="eyebrow">FINAL TOPOLOGY</p><h2>Estado final dos processos</h2></div>
              <Server size={17} className="accent" />
            </div>
            <div className="history-table-wrap">
              <table className="history-table">
                <thead><tr><th>Nó</th><th>Estado</th><th>Req.</th><th>Erros</th><th>Blacklist local</th></tr></thead>
                <tbody>
                  {history.servers.map((server) => (
                    <tr key={server.server_id}>
                      <td>{server.server_id}</td>
                      <td><span className={`status-dot ${(server.health_status ?? server.status) === "healthy" ? "status-live" : (server.health_status ?? server.status) === "degraded" ? "status-degraded" : "status-stopped"}`} /> {server.health_status ?? server.status}</td>
                      <td>{server.requests_total ?? 0}</td>
                      <td>{server.errors_total ?? 0}</td>
                      <td>{server.blacklist_size}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="history-note">Eventos e evidências detalhadas continuam disponíveis no snapshot JSON da API; o histórico visual prioriza evolução e leitura rápida. {history.clients_truncated ? "A lista visual de clientes foi amostrada para manter a consulta leve." : ""}</p>
          </section>
        </>
      )}
    </main>
  );
}

function HistoryCard({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <article className="history-card"><span>{icon} {label}</span><strong>{value}</strong></article>;
}

function formatDate(value: number | null) {
  return value ? new Date(value * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "sem data";
}

function formatDuration(seconds: number) {
  if (!seconds) return "0s";
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return minutes ? `${minutes}m ${remaining}s` : `${remaining}s`;
}
