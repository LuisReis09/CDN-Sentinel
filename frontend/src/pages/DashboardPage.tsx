import { Activity, Ban, Globe2, HeartPulse, Network, Server, Users } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { ControlPanel } from "../components/ControlPanel";
import {
  MapBrushToolbar,
  type MapEditMode,
} from "../components/MapBrushToolbar";
import { MapPlacementDialog } from "../components/MapPlacementDialog";
import { MapView } from "../components/MapView";
import { MetricCard } from "../components/MetricCard";
import { ScalabilityPanel } from "../components/ScalabilityPanel";
import type { Overview, ServerNode } from "../types";

interface DashboardPageProps {
  overview: Overview;
  connected: boolean;
  onRefresh: () => Promise<void>;
  onAction: () => Promise<void>;
  onError: (message: string) => void;
}

export function DashboardPage({
  overview,
  connected,
  onRefresh,
  onAction,
  onError,
}: DashboardPageProps) {
  const { status } = overview;
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [activeClient, setActiveClient] = useState<string | null>(null);
  const [editMode, setEditMode] = useState<MapEditMode>(null);
  const [placement, setPlacement] = useState<{
    mode: Exclude<MapEditMode, null>;
    latitude: number;
    longitude: number;
  } | null>(null);
  const [placementBusy, setPlacementBusy] = useState(false);
  const observedLatencies = overview.recent_traffic
    .map((item) => item.end_to_end_ms)
    .filter((value): value is number => typeof value === "number");
  const avgLatency = observedLatencies.length
    ? Math.round(
        observedLatencies.reduce((sum, value) => sum + value, 0) /
          observedLatencies.length,
      )
    : null;
  const latencyTone =
    avgLatency === null
      ? "warning"
      : status.scalability.slo_compliant
        ? "green"
        : "red";
  const clients = overview.clients.map((client) =>
    overview.blacklist.some((entry) => entry.client_id === client.client_id)
      ? { ...client, active: false }
      : client,
  );
  const visibleServers = activeNode
    ? overview.servers.filter((server) => server.server_id === activeNode)
    : overview.servers;
  const selectedClient = activeClient
    ? clients.find((client) => client.client_id === activeClient)
    : undefined;
  const selectedClientHistory = selectedClient?.watch_history ?? [];
  const selectedClientWatch = selectedClientHistory[selectedClientHistory.length - 1];
  const selectedClientTraffic = selectedClient
    ? [...overview.recent_traffic].reverse().find((entry) => entry.client_id === selectedClient.client_id)
    : undefined;
  const selectedClientServerId = selectedClientWatch?.server_id ?? selectedClientTraffic?.server_id ?? null;
  const selectedClientServer = selectedClientServerId
    ? overview.servers.find((server) => server.server_id === selectedClientServerId)
    : undefined;
  const healthOf = (server: ServerNode) => server.health_status ?? server.status;
  const available = overview.servers.filter(
    (server) => ["healthy", "degraded", "overloaded"].includes(healthOf(server)),
  ).length;
  const healthy = overview.servers.filter(
    (server) => healthOf(server) === "healthy",
  ).length;
  const degraded = overview.servers.filter(
    (server) => healthOf(server) === "degraded",
  ).length;
  const overloaded = overview.servers.filter(
    (server) => healthOf(server) === "overloaded",
  ).length;
  const healthScore = status.scalability.health_score_pct ?? 0;
  const healthTone = healthScore >= 85 ? "green" : healthScore >= 60 ? "warning" : "red";

  async function createPlacement(payload: Record<string, unknown>) {
    if (!placement) return;
    setPlacementBusy(true);
    try {
      if (placement.mode === "client") await api.createClient(payload);
      else await api.createServer(payload);
      await onRefresh();
      setPlacement(null);
      setEditMode(null);
    } catch (cause) {
      onError(
        cause instanceof Error
          ? cause.message
          : "Falha ao criar elemento no mapa",
      );
    } finally {
      setPlacementBusy(false);
    }
  }

  return (
    <main className="page-content">
      <header className="page-header">
        <div>
          <p className="eyebrow">GLOBAL DELIVERY FABRIC / LIVE TELEMETRY</p>
          <h1>Command center</h1>
          <p className="page-lead">
            Observe o cliente, a CDN, o watermark, o monitor e a governança com
            processos e mensagens visíveis.
          </p>
        </div>
        <div className="header-signal">
          <span
            className={`status-dot ${connected ? "status-live" : "status-offline"}`}
          />
          {connected ? "control plane online" : "backend desconectado"}
        </div>
      </header>
      <section className="metric-grid">
        <MetricCard
          label="NÓS CDN"
          value={status.servers_total}
          caption={`${healthy} saudáveis · ${degraded} degradados · ${overloaded} sobrecarregados · ${available} disponíveis`}
          icon={Server}
          tone="green"
        />
        <MetricCard
          label="CLIENTES"
          value={status.clients_total}
          caption={`${status.malicious_clients} em risco`}
          icon={Users}
          tone="cyan"
        />
        <MetricCard
          label="LATÊNCIA MÉDIA"
          value={avgLatency === null ? "—" : `${avgLatency} ms`}
          caption={
            avgLatency === null
              ? "sem amostras na janela"
              : `p95 ${status.scalability.p95_latency_ms} ms · limiar ${status.scalability.slo_p95_ms ?? 250} ms`
          }
          icon={Activity}
          tone={latencyTone}
        />
        <MetricCard
          label="SAÚDE DA CDN"
          value={`${healthScore.toFixed(0)}%`}
          caption={status.scalability.message}
          icon={HeartPulse}
          tone={healthTone}
        />
        <MetricCard
          label="BLACKLIST"
          value={status.blacklisted_total}
          caption={
            status.forensic_pending_total
              ? `${status.forensic_pending_total} em anÃ¡lise forense`
              : "propagada via gossip"
          }
          icon={Ban}
          tone="red"
        />
      </section>
      <section className="topology-layout">
        <div className="panel map-panel">
          <div className="panel-heading panel-heading-map">
            <div>
              <p className="eyebrow">LIVE TOPOLOGY</p>
              <h2>Mapa da rede mundial</h2>
            </div>
            <div className="map-heading-actions">
              <div className="panel-stat">
                <Globe2 size={15} /> {overview.recent_traffic.length} rotas
                recentes
              </div>
              <div className="panel-stat">
                {overview.clients.length < status.clients_total
                  ? `amostra ${overview.clients.length}/${status.clients_total} clientes`
                  : `${overview.clients.length} clientes visíveis`}
              </div>
              <MapBrushToolbar mode={editMode} onChange={setEditMode} />
            </div>
          </div>
          <MapView
            clients={clients}
            servers={overview.servers}
            traffic={overview.recent_traffic}
            events={overview.recent_events}
            editMode={editMode}
            tickIntervalSeconds={status.tick_interval_seconds}
            onMapPick={(latitude, longitude) =>
              editMode && setPlacement({ mode: editMode, latitude, longitude })
            }
            onNodeSelect={(kind, id) => {
              if (kind === "server") {
                setActiveNode(id);
                setActiveClient(null);
              } else {
                setActiveClient(id);
                setActiveNode(null);
              }
            }}
            highlightedClientId={activeClient}
            highlightedServerId={selectedClientServerId}
          />
          {selectedClient && (
            <div className="selected-client-route">
              <div>
                <small>CLIENTE SELECIONADO</small>
                <strong>{selectedClient.client_id} · {selectedClient.city}</strong>
              </div>
              <span>servido por</span>
              <b>{selectedClientServerId ?? "sem entrega recente"}</b>
              {selectedClientServer && <small>{selectedClientServer.city} · linha destacada no mapa</small>}
            </div>
          )}
          <p className="map-performance-note">
            <Network size={13} /> Visualização otimizada: o backbone usa uma árvore geradora mínima; linhas de failover e comunicações ativas aparecem por cima. O protocolo real continua enviando HTTP diretamente ao servidor de destino.
          </p>
        </div>
        <ControlPanel
          status={status}
          monitor={overview.monitor}
          onRefresh={onRefresh}
          onAction={onAction}
          onError={onError}
        />
      </section>
      <NodeHealthPanel
        servers={visibleServers}
        selected={activeNode}
        onSelect={setActiveNode}
      />
      <ScalabilityPanel status={status} />
      {placement && (
        <MapPlacementDialog
          mode={placement.mode}
          latitude={placement.latitude}
          longitude={placement.longitude}
          busy={placementBusy}
          onClose={() => setPlacement(null)}
          onSubmit={createPlacement}
        />
      )}
    </main>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <Network size={24} />
      <span>{text}</span>
    </div>
  );
}

function NodeHealthPanel({
  servers,
  selected,
  onSelect,
}: {
  servers: ServerNode[];
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <section className="panel node-health-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">NODE HEALTH / PROCESSES</p>
          <h2>Processos observados</h2>
        </div>
        <Network size={18} className="accent" />
      </div>
      <div className="node-health-list">
        {servers.map((server) => (
          <button
            className={`node-health-row ${selected === server.server_id ? "node-health-row-active" : ""}`}
            key={server.server_id}
            onClick={() =>
              onSelect(selected === server.server_id ? null : server.server_id)
            }
          >
            <span className={`status-dot ${serverTone(server)}`} />
            <span className="node-health-main">
              <strong>
                {server.server_id} · {server.city}
              </strong>
              <small>
                {server.role ?? "edge"} · {server.process_mode ?? "http"} · PID {server.process_id ?? "—"} · porta {server.port} · uptime{" "}
                {Math.round(server.uptime_seconds ?? 0)}s · {server.health_status ?? server.status} · {server.peer_ids?.length ?? 0} peers
              </small>
            </span>
            <span className="node-health-stat">
              <b>{server.requests_total ?? 0}</b>
              <small>requests total</small>
              <small>sim. {server.simulated_requests_total ?? 0} · HTTP {server.http_requests_total ?? 0}</small>
            </span>
            <span className="node-health-stat">
              <b>{server.errors_total ?? 0}</b>
              <small>erros</small>
            </span>
            <span className="node-health-stat">
              <b>{Math.round((server.utilization ?? 0) * 100)}%</b>
              <small>pressão</small>
            </span>
            <span className="node-health-stat">
              <b>{Math.round(server.latency_p95_ms ?? 0)} ms</b>
              <small>P95</small>
            </span>
            <span className="node-health-stat">
              <b>{server.blacklist_size}</b>
              <small>blacklist local</small>
            </span>
          </button>
        ))}
        {servers.length === 0 && (
          <EmptyState text="Inicialize uma topologia para observar os processos." />
        )}
      </div>
    </section>
  );
}

function serverTone(server: ServerNode) {
  const health = server.health_status ?? server.status;
  if (health === "healthy") return "status-live";
  if (health === "degraded") return "status-degraded";
  if (health === "overloaded") return "status-offline";
  if (health === "starting") return "status-starting";
  if (health === "stopped") return "status-stopped";
  return "status-offline";
}
