import {
  Activity,
  BarChart3,
  Clock3,
  Database,
  GitBranch,
  Server,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import type { SimulationHistory } from "../types";

export function HistoryPage() {
  const [searchParams] = useSearchParams();
  const [histories, setHistories] = useState<SimulationHistory[]>([]);
  const [selectedId, setSelectedId] = useState(
    searchParams.get("simulation_id") ?? "",
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .history()
      .then((result) => {
        if (cancelled) return;
        setHistories(result.histories ?? []);
        if (!selectedId && result.histories?.length)
          setSelectedId(
            result.histories[result.histories.length - 1].simulation_id,
          );
        setError(null);
      })
      .catch((cause) => {
        if (!cancelled)
          setError(
            cause instanceof Error
              ? cause.message
              : "Falha ao carregar o histórico",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const history =
    histories.find((item) => item.simulation_id === selectedId) ??
    histories[histories.length - 1];
  const chartData = useMemo(
    () =>
      (history?.traffic ?? []).map((item, index) => ({
        sample: index + 1,
        latency: Number(
          (
            item.end_to_end_ms ??
            item.http_rtt_ms ??
            item.latency_ms ??
            0
          ).toFixed(1),
        ),
        requests: 1,
      })),
    [history],
  );
  const duration =
    history?.started_at && history.ended_at
      ? Math.max(0, history.ended_at - history.started_at)
      : 0;
  const latencies = (history?.traffic ?? [])
    .map(
      (item) => item.end_to_end_ms ?? item.http_rtt_ms ?? item.latency_ms ?? 0,
    )
    .sort((a, b) => a - b);
  const p95 = latencies.length
    ? latencies[
        Math.min(latencies.length - 1, Math.ceil(latencies.length * 0.95) - 1)
      ]
    : 0;
  const failedEvents = (history?.events ?? []).filter(
    (event) => event.status === "failed" || event.type.includes("failed"),
  ).length;

  return (
    <main className="page-content history-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">OBSERVABILITY / ARCHIVED RUNS</p>
          <h1>Simulation history</h1>
          <p className="page-lead">
            Cada encerramento arquiva a topologia, o tráfego, os eventos, os
            vazamentos e a propagação de blacklist observados naquela execução.
          </p>
        </div>
        <div className="history-toolbar">
          <span className="lifecycle-chip">
            <Database size={13} /> {histories.length} execução(oes)
          </span>
          {histories.length > 0 && (
            <select
              value={history?.simulation_id ?? ""}
              onChange={(event) => setSelectedId(event.target.value)}
              aria-label="Selecionar simulação"
            >
              {histories.map((item) => (
                <option key={item.simulation_id} value={item.simulation_id}>
                  {item.simulation_id} · {formatDate(item.ended_at)}
                </option>
              ))}
            </select>
          )}
        </div>
      </header>
      {loading && (
        <section className="panel history-empty">
          Carregando históricos arquivados...
        </section>
      )}
      {error && (
        <section className="panel history-empty">
          Não foi possível carregar o histórico: {error}
        </section>
      )}
      {!loading && !error && !history && (
        <section className="panel history-empty">
          <BarChart3 size={22} /> Nenhuma simulação encerrada ainda. Execute uma
          simulação e use Encerrar para gerar o primeiro snapshot.
        </section>
      )}
      {history && (
        <>
          <section className="history-cards">
            <HistoryCard
              icon={<Clock3 size={15} />}
              label="Duração"
              value={formatDuration(duration)}
            />
            <HistoryCard
              icon={<Activity size={15} />}
              label="Requisições"
              value={String(history.traffic.length)}
            />
            <HistoryCard
              icon={<GitBranch size={15} />}
              label="Eventos"
              value={String(history.events.length)}
            />
            <HistoryCard
              icon={<ShieldCheck size={15} />}
              label="Blacklist"
              value={String(history.blacklist.length)}
            />
            <HistoryCard
              icon={<Server size={15} />}
              label="Nós / clientes"
              value={`${history.servers.length} / ${history.clients.length}`}
            />
            <HistoryCard
              icon={<Activity size={15} />}
              label="P95 e2e"
              value={`${Number(p95).toFixed(1)} ms`}
            />
          </section>
          <section className="history-grid">
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">REQUEST TELEMETRY</p>
                  <h2>Latência por requisição</h2>
                </div>
                <Activity size={17} className="accent" />
              </div>
              {chartData.length ? (
                <div className="history-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData}>
                      <CartesianGrid
                        stroke="rgba(165,202,238,.12)"
                        vertical={false}
                      />
                      <XAxis
                        dataKey="sample"
                        tick={{ fill: "#7890a7", fontSize: 9 }}
                      />
                      <YAxis
                        tick={{ fill: "#7890a7", fontSize: 9 }}
                        unit=" ms"
                      />
                      <Tooltip
                        contentStyle={{
                          background: "#0b1727",
                          border: "1px solid rgba(165,202,238,.2)",
                          fontSize: 10,
                        }}
                      />
                      <Bar
                        dataKey="latency"
                        fill="#45d9ff"
                        radius={[3, 3, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="history-empty">
                  Nenhuma requisição registrada nesta execução.
                </div>
              )}
            </div>
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">FINAL TOPOLOGY</p>
                  <h2>Estado dos processos</h2>
                </div>
                <Server size={17} className="accent" />
              </div>
              <div className="history-table-wrap">
                <table className="history-table">
                  <thead>
                    <tr>
                      <th>Nó</th>
                      <th>Estado</th>
                      <th>Req.</th>
                      <th>Erros</th>
                      <th>Blacklist local</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.servers.map((server) => (
                      <tr key={server.server_id}>
                        <td>{server.server_id}</td>
                        <td>
                          <span
                            className={`status-dot ${server.status === "healthy" ? "status-live" : server.status === "degraded" ? "status-degraded" : "status-stopped"}`}
                          />{" "}
                          {server.status}
                        </td>
                        <td>{server.requests_total ?? 0}</td>
                        <td>{server.errors_total ?? 0}</td>
                        <td>{server.blacklist_size}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
          <section className="history-grid">
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">EVENT TIMELINE</p>
                  <h2>Como a simulação aconteceu</h2>
                </div>
                <GitBranch size={17} className="accent" />
              </div>
              <div className="history-event-list">
                {history.events
                  .slice()
                  .reverse()
                  .map((event, index) => (
                    <div
                      className="history-event"
                      key={
                        event.event_id ?? `${event.type}-${event.at}-${index}`
                      }
                    >
                      <span
                        className={`status-dot ${event.status === "failed" ? "status-offline" : "status-live"}`}
                      />
                      <div>
                        <strong>{event.type}</strong>
                        <small>
                          {event.server_id ??
                            event.client_id ??
                            event.from_server ??
                            "control"}
                          {event.routing_reason
                            ? ` · ${event.routing_reason}`
                            : ""}
                        </small>
                      </div>
                      <time>{formatTime(event.at)}</time>
                    </div>
                  ))}
              </div>
            </div>
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">BLACKLIST PROPAGATION</p>
                  <h2>Evidencias resumidas</h2>
                </div>
                <ShieldCheck size={17} className="accent" />
              </div>
              <div className="history-table-wrap">
                <table className="history-table">
                  <thead>
                    <tr>
                      <th>Cliente</th>
                      <th>Detectado por</th>
                      <th>Propagado para</th>
                      <th>Motivo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.blacklist.map((entry) => (
                      <tr key={`${entry.client_id}-${entry.detected_at}`}>
                        <td>{entry.client_id}</td>
                        <td>{entry.server_id}</td>
                        <td>{entry.propagated_to.length} nós</td>
                        <td>{entry.reason}</td>
                      </tr>
                    ))}
                    {history.blacklist.length === 0 && (
                      <tr>
                        <td colSpan={4}>Nenhum bloqueio registrado.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="history-note">
                Falhas/eventos marcados: {failedEvents}. O histórico e mantido
                em memória (até 20 execuções).
              </p>
            </div>
          </section>
        </>
      )}
    </main>
  );
}

function HistoryCard({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <article className="history-card">
      <span>
        {icon} {label}
      </span>
      <strong>{value}</strong>
    </article>
  );
}

function formatDate(value: number | null) {
  return value
    ? new Date(value * 1000).toLocaleString("pt-BR", {
        dateStyle: "short",
        timeStyle: "short",
      })
    : "sem data";
}

function formatTime(value: number) {
  return new Date(value * 1000).toLocaleTimeString("pt-BR");
}

function formatDuration(seconds: number) {
  if (!seconds) return "0s";
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return minutes ? `${minutes}m ${remaining}s` : `${remaining}s`;
}
