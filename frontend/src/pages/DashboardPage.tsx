import { Activity, Ban, Globe2, Network, Server, ShieldCheck, Users } from "lucide-react";
import { useState } from "react";
import { ActivityFeed } from "../components/ActivityFeed";
import { ControlPanel } from "../components/ControlPanel";
import { DistributedEvidencePanel } from "../components/DistributedEvidencePanel";
import { ScalabilityPanel } from "../components/ScalabilityPanel";
import { MapView } from "../components/MapView";
import { MapBrushToolbar, type MapEditMode } from "../components/MapBrushToolbar";
import { MapPlacementDialog } from "../components/MapPlacementDialog";
import { MetricCard } from "../components/MetricCard";
import { WatermarkLab } from "../components/WatermarkLab";
import { api } from "../api";
import type { Overview } from "../types";

interface DashboardPageProps {
  overview: Overview;
  connected: boolean;
  onRefresh: () => Promise<void>;
  onAction: () => Promise<void>;
  onError: (message: string) => void;
}

export function DashboardPage({ overview, connected, onRefresh, onAction, onError }: DashboardPageProps) {
  const { status } = overview;
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [editMode, setEditMode] = useState<MapEditMode>(null);
  const [placement, setPlacement] = useState<{ mode: Exclude<MapEditMode, null>; latitude: number; longitude: number } | null>(null);
  const [placementBusy, setPlacementBusy] = useState(false);
  const avgLatency = overview.recent_traffic.length
    ? Math.round(overview.recent_traffic.reduce((sum, item) => sum + item.latency_ms, 0) / overview.recent_traffic.length)
    : 0;
  const visibleServers = activeNode ? overview.servers.filter((server) => server.server_id === activeNode) : overview.servers;
  const clients = overview.clients.map((client) => overview.blacklist.some((entry) => entry.client_id === client.client_id) ? { ...client, active: false } : client);

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
      onError(cause instanceof Error ? cause.message : "Falha ao criar elemento no mapa");
    } finally {
      setPlacementBusy(false);
    }
  }

  return (
    <main className="page-content">
      <header className="page-header">
        <div><p className="eyebrow">GLOBAL DELIVERY FABRIC / LIVE TELEMETRY</p><h1>Command center</h1><p className="page-lead">Observe a cadeia completa: cliente → nó CDN → watermark → monitor → governança.</p></div>
        <div className="header-signal"><span className={`status-dot ${connected ? "status-live" : "status-offline"}`} />{connected ? "control plane online" : "backend desconectado"}</div>
      </header>
      <section className="metric-grid">
        <MetricCard label="NÓS CDN" value={status.servers_total} caption={`${overview.servers.filter((server) => server.status === "healthy").length} saudáveis`} icon={Server} tone="green" />
        <MetricCard label="CLIENTES" value={status.clients_total} caption={`${status.malicious_clients} em risco`} icon={Users} tone="cyan" />
        <MetricCard label="LATÊNCIA MÉDIA" value={`${avgLatency} ms`} caption={`fator x${status.configuration.latency_factor}`} icon={Activity} tone="orange" />
        <MetricCard label="BLACKLIST" value={status.blacklisted_total} caption="propagada via gossip" icon={Ban} tone="red" />
      </section>
      <section className="topology-layout">
        <div className="panel map-panel">
          <div className="panel-heading panel-heading-map"><div><p className="eyebrow">LIVE TOPOLOGY</p><h2>Mapa da rede mundial</h2></div><div className="map-heading-actions"><div className="panel-stat"><Globe2 size={15} /> {overview.recent_traffic.length} rotas recentes</div><MapBrushToolbar mode={editMode} onChange={setEditMode} /></div></div>
          <MapView clients={clients} servers={overview.servers} traffic={overview.recent_traffic} events={overview.recent_events} editMode={editMode} onMapPick={(latitude, longitude) => editMode && setPlacement({ mode: editMode, latitude, longitude })} />
        </div>
        <ControlPanel status={status} onRefresh={onRefresh} onAction={onAction} onError={onError} />
      </section>
      <DistributedEvidencePanel overview={overview} />
      <ScalabilityPanel status={status} />
      <section className="lower-grid">
        <div className="panel">
          <div className="panel-heading"><div><p className="eyebrow">NODE HEALTH</p><h2>Servidores em campo</h2></div><Network size={18} className="accent" /></div>
          <div className="node-list">{visibleServers.map((server) => <button className={`node-row ${activeNode === server.server_id ? "node-row-active" : ""}`} key={server.server_id} onClick={() => setActiveNode(activeNode === server.server_id ? null : server.server_id)}><span className={`status-dot ${server.status === "healthy" ? "status-live" : "status-offline"}`} /><span className="node-name"><strong>{server.server_id}</strong><small>{server.city} · :{server.port}</small></span><span className="node-load"><small>{server.load} req</small><i><b style={{ width: `${Math.min(100, 12 + server.load * 12)}%` }} /></i></span><span className="node-blacklist">{server.blacklist_size} ban</span></button>)}{visibleServers.length === 0 && <EmptyState text="Inicialize uma topologia para povoar os nós." />}</div>
        </div>
        <div className="panel">
          <div className="panel-heading"><div><p className="eyebrow">EVENT STREAM</p><h2>Atividade recente</h2></div><ShieldCheck size={18} className="accent" /></div>
          <ActivityFeed events={overview.recent_events} />
        </div>
      </section>
      <WatermarkLab onError={onError} />
      {placement && <MapPlacementDialog mode={placement.mode} latitude={placement.latitude} longitude={placement.longitude} busy={placementBusy} onClose={() => setPlacement(null)} onSubmit={createPlacement} />}
    </main>
  );
}

function EmptyState({ text }: { text: string }) { return <div className="empty-state"><Network size={24} /><span>{text}</span></div>; }

