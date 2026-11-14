import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FlaskConical,
  RefreshCw,
  RotateCcw,
  Server,
  WifiOff,
} from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { Overview, ServerNode } from "../types";

export function NetworkLabPage({
  overview,
  onRefresh,
  onError,
}: {
  overview: Overview;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [latency, setLatency] = useState("250");
  const [dropRate, setDropRate] = useState("0.25");
  const events = overview.recent_events
    .filter((event) =>
      [
        "fault_injected",
        "client_request",
        "server_message",
        "blacklist_propagated",
      ].includes(event.type),
    )
    .slice(-16)
    .reverse();

  async function applyFault(
    serverId: string,
    fault: Record<string, unknown>,
    label: string,
  ) {
    for (const [field, minimum, maximum] of [
      ["extra_latency_ms", 0, 30_000],
      ["drop_rate", 0, 1],
    ] as const) {
      if (!(field in fault)) continue;
      const value = fault[field];
      if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
        onError(
          field === "drop_rate"
            ? "A perda deve ser um número entre 0 e 1."
            : "O atraso deve ser um número entre 0 e 30.000 ms.",
        );
        return;
      }
    }
    setBusy(`${serverId}:${label}`);
    try {
      await api.injectFault(serverId, fault);
      await onRefresh();
    } catch (cause) {
      onError(
        cause instanceof Error ? cause.message : "Falha ao aplicar cenário",
      );
    } finally {
      setBusy(null);
    }
  }

  async function resetMetrics() {
    setBusy("reset");
    try {
      await api.resetMetrics();
      await onRefresh();
    } catch (cause) {
      onError(
        cause instanceof Error ? cause.message : "Falha ao resetar métricas",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="page-content">
      <header className="page-header">
        <div>
          <p className="eyebrow">CONTROL PLANE / EXPERIMENTS</p>
          <h1>Network lab</h1>
          <p className="page-lead">
            Cenários executáveis sobre os processos locais. Cada botão chama uma
            API real e os efeitos aparecem no health, no roteamento e na trilha
            de eventos.
          </p>
        </div>
        <div className="header-signal">
          <span className="status-dot status-live" />
          sem serviços externos
        </div>
      </header>
      <section className="lab-notice">
        <FlaskConical size={17} />
        <span>
          <strong>Escopo honesto:</strong> coordenadas e atraso geográfico são
          simulados; os processos CDN são reais e locais.
        </span>
      </section>
      <section className="panel lab-controls">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">FAILURE INJECTION</p>
            <h2>Aplicar, observar, recuperar</h2>
          </div>
          <WifiOff size={18} className="danger" />
        </div>
        <div className="lab-form">
          <label>
            Atraso extra (ms)
            <input
              type="text"
              inputMode="decimal"
              value={latency}
              onChange={(event) => setLatency(event.target.value)}
            />
          </label>
          <label>
            Perda de mensagens
            <input
              type="text"
              inputMode="decimal"
              value={dropRate}
              onChange={(event) => setDropRate(event.target.value)}
            />
          </label>
          <button
            className="secondary-button"
            onClick={() => void resetMetrics()}
            disabled={busy !== null}
          >
            <RotateCcw size={14} /> resetar métricas
          </button>
        </div>
        <div className="lab-node-list">
          {overview.servers.map((server) => (
            <NodeCard
              key={server.server_id}
              server={server}
              latency={latency}
              dropRate={dropRate}
              busy={busy !== null}
              onFault={applyFault}
            />
          ))}
        </div>
      </section>
      <section className="lab-grid">
        <div className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">OBSERVED ROUTING</p>
              <h2>Últimas decisões</h2>
            </div>
            <RefreshCw size={17} className="accent" />
          </div>
          <div className="lab-routing-list">
            {overview.recent_traffic
              .slice(-8)
              .reverse()
              .map((item) => (
                <div
                  className="lab-routing-row"
                  key={`${item.trace_id ?? item.chunk_id}-${item.at}`}
                >
                  <Server size={14} />
                  <div>
                    <strong>
                      {item.client_id} → {item.server_id}
                    </strong>
                    <small>
                      {item.routing_reason ?? "rota observada"} · trace{" "}
                      {item.trace_id ?? "—"}
                    </small>
                  </div>
                  <span>
                    {Math.round(item.end_to_end_ms ?? item.latency_ms)} ms
                    <small>e2e real</small>
                  </span>
                </div>
              ))}
            {overview.recent_traffic.length === 0 && (
              <p className="empty-state">
                Ainda não há requisições observadas.
              </p>
            )}
          </div>
        </div>
        <div className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">EVIDENCE TIMELINE</p>
              <h2>Eventos correlacionados</h2>
            </div>
            <AlertTriangle size={17} className="accent" />
          </div>
          <div className="lab-event-list">
            {events.map((event, index) => (
              <div
                className="lab-event-row"
                key={event.event_id ?? `${event.type}-${event.at}-${index}`}
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
                      "control"}{" "}
                    · trace {event.trace_id ?? "—"}
                  </small>
                </div>
                <time>
                  {new Date(event.at * 1000).toLocaleTimeString("pt-BR")}
                </time>
              </div>
            ))}
            {events.length === 0 && (
              <p className="empty-state">
                A linha do tempo será preenchida pelos experimentos.
              </p>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

function NodeCard({
  server,
  latency,
  dropRate,
  busy,
  onFault,
}: {
  server: ServerNode;
  latency: string;
  dropRate: string;
  busy: boolean;
  onFault: (
    serverId: string,
    fault: Record<string, unknown>,
    label: string,
  ) => Promise<void>;
}) {
  const health = server.health_status ?? server.status;
  const offline =
    health === "offline" ||
    health === "stopped" ||
    server.fault?.offline;
  const degraded = health === "degraded";
  const overloaded = health === "overloaded";
  const tone = offline
    ? "status-offline"
    : overloaded
      ? "status-offline"
      : degraded
      ? "status-degraded"
      : "status-live";
  const label = offline ? "OFFLINE" : overloaded ? "OVERLOADED" : degraded ? "DEGRADED" : "HEALTHY";
  return (
    <article className="lab-node">
      <div className="lab-node-title">
        <span className={`status-dot ${tone}`} />
        <div>
          <strong>{server.server_id}</strong>
          <small>
            {server.city} · porta {server.port} · PID {server.process_id ?? "—"}
          </small>
        </div>
        <span className="lab-node-state">{label}</span>
      </div>
      <div className="lab-node-metrics">
        <span>
          in-flight <b>{server.requests_in_flight ?? server.load}</b>
        </span>
        <span>
          requests <b>{server.requests_total ?? 0}</b>
          <small>sim. {server.simulated_requests_total ?? 0} · HTTP {server.http_requests_total ?? 0}</small>
        </span>
        <span>
          erros <b>{server.errors_total ?? 0}</b>
        </span>
        <span>
          uptime <b>{Math.round(server.uptime_seconds ?? 0)}s</b>
        </span>
        <span>
          pressão <b>{Math.round((server.utilization ?? 0) * 100)}%</b>
        </span>
        <span>
          P95 <b>{Math.round(server.latency_p95_ms ?? 0)} ms</b>
        </span>
      </div>
      <div className="lab-actions">
        <button
          onClick={() =>
            void onFault(server.server_id, { offline: true }, "offline")
          }
          disabled={busy}
        >
          <WifiOff size={13} /> desligar
        </button>
        <button
          onClick={() =>
            void onFault(
              server.server_id,
              { offline: false, extra_latency_ms: 0, drop_rate: 0 },
              "online",
            )
          }
          disabled={busy}
        >
          <CheckCircle2 size={13} /> recuperar
        </button>
        <button
          onClick={() =>
            void onFault(
              server.server_id,
              {
                offline: false,
                extra_latency_ms: Number(latency),
                drop_rate: 0,
              },
              "latency",
            )
          }
          disabled={busy}
        >
          <Clock3 size={13} /> latência
        </button>
        <button
          onClick={() =>
            void onFault(
              server.server_id,
              {
                offline: false,
                extra_latency_ms: 0,
                drop_rate: Number(dropRate),
              },
              "loss",
            )
          }
          disabled={busy}
        >
          <AlertTriangle size={13} /> perda
        </button>
      </div>
    </article>
  );
}
