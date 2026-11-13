import { useEffect, useState } from "react";
import { divIcon } from "leaflet";
import {
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { CSSProperties } from "react";
import type { Client, ServerNode, SimulationEvent, Traffic } from "../types";

const mapTilerKey = (import.meta.env.VITE_MAPTILER_KEY ?? "").trim();
const mapTileUrl = mapTilerKey
  ? `https://api.maptiler.com/maps/streets-v4/256/{z}/{x}/{y}.png?key=${encodeURIComponent(mapTilerKey)}&language=pt`
  : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const mapAttribution = mapTilerKey
  ? 'Dados cartográficos © <a href="https://www.maptiler.com/copyright/" target="_blank" rel="noreferrer">MapTiler</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> colaboradores'
  : 'Dados cartográficos © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> colaboradores';

interface MapViewProps {
  clients: Client[];
  servers: ServerNode[];
  traffic: Traffic[];
  events: SimulationEvent[];
  editMode: "client" | "server" | null;
  onMapPick: (latitude: number, longitude: number) => void;
  tickIntervalSeconds: number;
  onNodeSelect: (kind: "server" | "client", id: string) => void;
  highlightedClientId?: string | null;
  highlightedServerId?: string | null;
}

export function MapView({
  clients,
  servers,
  traffic,
  events,
  editMode,
  onMapPick,
  tickIntervalSeconds,
  onNodeSelect,
  highlightedClientId = null,
  highlightedServerId = null,
}: MapViewProps) {
  const visibleClients = clients.slice(0, 1_200);
  const clientsById = new Map(
    visibleClients.map((client) => [client.client_id, client]),
  );
  const serversById = new Map(
    servers.map((server) => [server.server_id, server]),
  );
  const trafficLinesSeen = new Set<string>();
  const trafficLines = traffic.slice(-48).reverse().flatMap((entry) => {
    const routeKey = `${entry.client_id}:${entry.server_id}`;
    if (trafficLinesSeen.has(routeKey) || trafficLinesSeen.size >= 18) return [];
    trafficLinesSeen.add(routeKey);
    const client = clientsById.get(entry.client_id);
    const server = serversById.get(entry.server_id);
    return client && server
      ? [
          {
            entry,
            positions: [
              [client.latitude, client.longitude],
              [server.latitude, server.longitude],
            ] as [[number, number], [number, number]],
          },
        ]
      : [];
  });
  const highlightedClient = highlightedClientId
    ? clientsById.get(highlightedClientId)
    : undefined;
  const highlightedServer = highlightedServerId
    ? serversById.get(highlightedServerId)
    : undefined;
  const highlightedRoute = highlightedClient && highlightedServer
    ? [[highlightedClient.latitude, highlightedClient.longitude], [highlightedServer.latitude, highlightedServer.longitude]] as [[number, number], [number, number]]
    : null;
  const messageEvents = events.filter(
    (event) =>
      event.type === "server_message" && event.from_server && event.to_server,
  );
  const serverLinks = minimumSpanningTree(servers);
  const messageLinks = messageEvents.slice(-12).flatMap((event, index) => {
    const from = serversById.get(event.from_server ?? "");
    const to = serversById.get(event.to_server ?? "");
    return from && to
      ? [{ event, index, positions: [[from.latitude, from.longitude], [to.latitude, to.longitude]] as [[number, number], [number, number]] }]
      : [];
  });
  const mapStyle = {
    "--tick-interval": `${Math.max(0.5, tickIntervalSeconds)}s`,
  } as CSSProperties;

  return (
    <div
      className={`map-shell ${editMode ? "map-shell-editing" : ""}`}
      style={mapStyle}
    >
      <MapContainer
        center={[18, 0]}
        zoom={2}
        minZoom={2}
        maxZoom={6}
        scrollWheelZoom
        className="world-map"
      >
        <PortugueseLeafletControls />
        <MapClickHandler enabled={Boolean(editMode)} onPick={onMapPick} />
        <TileLayer
          attribution={mapAttribution}
          url={mapTileUrl}
        />
        <CommunicationOverlay
          clients={visibleClients}
          servers={servers}
          traffic={traffic}
          events={messageEvents}
          tickIntervalSeconds={tickIntervalSeconds}
        />
        {serverLinks.map((line) => (
          <Polyline
            key={`gossip-pair-${line.from}-${line.to}`}
            positions={line.positions}
            pathOptions={{
              className: "map-gossip-path",
              color: "#438fe8",
              weight: messageEvents.length ? 3.5 : 2.2,
              opacity: messageEvents.length ? 0.55 : 0.34,
              dashArray: "7 12",
            }}
          />
        ))}
        {messageLinks.map(({ event, index, positions }) => (
          <Polyline
            key={`message-link-${event.message_id ?? event.at}-${index}`}
            positions={positions}
            pathOptions={{
              className: "map-message-path",
              color: communicationColor(event),
              weight: 3.5,
              opacity: 0.8,
              dashArray: "5 7",
            }}
          />
        ))}
        {trafficLines.map(({ entry, positions }, index) => (
          <Polyline
            key={`traffic-pair-${entry.at}-${index}`}
            positions={positions}
            pathOptions={{
              className: "map-traffic-path",
              color: "#65d89b",
              weight: 2,
              opacity: 0.5,
              dashArray: "5 13",
            }}
          />
        ))}
        {highlightedRoute && (
          <Polyline
            positions={highlightedRoute}
            pathOptions={{
              className: "map-selected-route",
              color: "#ffe06b",
              weight: 5,
              opacity: 0.95,
              dashArray: "10 7",
            }}
          >
            <Tooltip sticky>
              Entrega selecionada · {highlightedClientId} → {highlightedServerId}
            </Tooltip>
          </Polyline>
        )}
        {servers.map((server) => (
          <ServerMarker
            key={server.server_id}
            server={server}
            onSelect={() => onNodeSelect("server", server.server_id)}
          />
        ))}
        {visibleClients.map((client) => (
          <ClientMarker
            key={client.client_id}
            client={client}
            onSelect={() => onNodeSelect("client", client.client_id)}
          />
        ))}
      </MapContainer>
      {editMode && (
        <div className="map-edit-hint">
          Clique para posicionar{" "}
          {editMode === "client" ? "um usuário" : "um servidor CDN"}
        </div>
      )}
      <MapLegends />
    </div>
  );
}

type ServerLink = {
  from: string;
  to: string;
  positions: [[number, number], [number, number]];
};

function minimumSpanningTree(servers: ServerNode[]): ServerLink[] {
  if (servers.length < 2) return [];
  const visited = new Set<string>([servers[0].server_id]);
  const links: ServerLink[] = [];
  while (visited.size < servers.length) {
    let best: { from: ServerNode; to: ServerNode; weight: number } | null = null;
    for (const from of servers) {
      if (!visited.has(from.server_id)) continue;
      for (const to of servers) {
        if (visited.has(to.server_id)) continue;
        const weight = mapDistance(from, to);
        if (!best || weight < best.weight) best = { from, to, weight };
      }
    }
    if (!best) break;
    visited.add(best.to.server_id);
    links.push({
      from: best.from.server_id,
      to: best.to.server_id,
      positions: [[best.from.latitude, best.from.longitude], [best.to.latitude, best.to.longitude]],
    });
  }
  return links;
}

function mapDistance(a: ServerNode, b: ServerNode) {
  const latitude = ((a.latitude + b.latitude) / 2) * Math.PI / 180;
  const longitudeScale = Math.max(0.2, Math.cos(latitude));
  return Math.hypot(a.latitude - b.latitude, (a.longitude - b.longitude) * longitudeScale);
}

function communicationColor(event: SimulationEvent) {
  const kind = communicationKind(event);
  return kind === "blacklist" ? "#ff6177" : kind === "failover" ? "#ffb86b" : kind === "capacity" ? "#ffe06b" : kind === "health" ? "#b99cff" : "#438fe8";
}

function ServerMarker({
  server,
  onSelect,
}: {
  server: ServerNode;
  onSelect: () => void;
}) {
  const health = server.health_status ?? server.status;
  const available = ["healthy", "degraded", "overloaded"].includes(health);
  const overloaded = available && health === "overloaded";
  const state = !available
    ? "offline"
    : overloaded
      ? "overloaded"
      : health === "degraded"
        ? "degraded"
        : "active";
  const colors = {
    active: { color: "#9eff6c", fillColor: "#2f8d52" },
    degraded: { color: "#ffb86b", fillColor: "#9b5c25" },
    overloaded: { color: "#ff6177", fillColor: "#a52b47" },
    offline: { color: "#a5afba", fillColor: "#5b6672" },
  }[state];
  return (
    <CircleMarker
      center={[server.latitude, server.longitude]}
      radius={9}
      eventHandlers={{ click: onSelect }}
      pathOptions={{ ...colors, fillOpacity: 0.92, weight: 2 }}
    >
      <Tooltip direction="top" offset={[0, -8]}>
        {server.server_id} · porta {server.port}
      </Tooltip>
      <Popup>
        <strong>{server.server_id}</strong>
        <br />
        {server.city}
        <br />
        porta {server.port} · PID {server.process_id ?? "—"}
        <br />
        saúde {health} · pressão {Math.round((server.utilization ?? 0) * 100)}%
        <br />
        P95 {Math.round(server.latency_p95_ms ?? 0)} ms · fila {server.queue_depth ?? 0}
        <br />
        mensagens recebidas: {server.messages_received}
      </Popup>
    </CircleMarker>
  );
}

function ClientMarker({
  client,
  onSelect,
}: {
  client: Client;
  onSelect: () => void;
}) {
  const banned = !client.active;
  const dangerous = client.malicious && !banned;
  const state = banned
    ? "banned"
    : dangerous
      ? "dangerous"
      : "active";
  const colors = {
    active: { color: "#8fc8ff", fillColor: "#1763a1" },
    dangerous: { color: "#ffd08b", fillColor: "#b5682e" },
    banned: { color: "#ff6177", fillColor: "#a52b47" },
  }[state];
  return (
    <CircleMarker
      center={[client.latitude, client.longitude]}
      radius={banned ? 7 : 5}
      eventHandlers={{ click: onSelect }}
      pathOptions={{ ...colors, fillOpacity: 0.88, weight: 1.5 }}
    >
      <Popup>
        <strong>{client.client_id}</strong>
        <br />
        {client.city}
        <br />
        {banned
          ? "BLACKLIST"
          : dangerous
            ? "cliente perigoso"
            : "cliente ativo"}
        <br />
        PID {client.process_id ?? "—"} · processo{" "}
        {client.process_status || "desconhecido"}
        <br />
        vídeos: {client.videos_consumed}
      </Popup>
    </CircleMarker>
  );
}

function CommunicationOverlay({
  clients,
  servers,
  traffic,
  events,
  tickIntervalSeconds,
}: {
  clients: Client[];
  servers: ServerNode[];
  traffic: Traffic[];
  events: SimulationEvent[];
  tickIntervalSeconds: number;
}) {
  const [clock, setClock] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now() / 1000), 140);
    return () => window.clearInterval(timer);
  }, []);
  const serversById = new Map(
    servers.map((server) => [server.server_id, server]),
  );
  const clientsById = new Map(
    clients.map((client) => [client.client_id, client]),
  );
  const duration = Math.max(1.2, Math.min(5, tickIntervalSeconds * 0.85));
  const serverPackets = events.slice(-10).flatMap((event) => {
    const from = serversById.get(event.from_server!);
    const to = serversById.get(event.to_server!);
    if (!from || !to) return [];
    const elapsed = clock - event.at;
    if (elapsed < -0.5 || elapsed > duration + 1.2) return [];
    const progress = Math.max(0, Math.min(1, elapsed / duration));
    return [
      {
        event,
        position: [
          from.latitude + (to.latitude - from.latitude) * progress,
          from.longitude + (to.longitude - from.longitude) * progress,
        ] as [number, number],
      },
    ];
  });
  const clientPackets = traffic.slice(-10).flatMap((entry) => {
    const client = clientsById.get(entry.client_id);
    const server = serversById.get(entry.server_id);
    if (!client || !server) return [];
    const elapsed = clock - entry.at;
    if (elapsed < -0.5 || elapsed > duration + 0.6) return [];
    const progress = Math.max(0, Math.min(1, elapsed / duration));
    return [
      {
        entry,
        position: [
          server.latitude + (client.latitude - server.latitude) * progress,
          server.longitude + (client.longitude - server.longitude) * progress,
        ] as [number, number],
      },
    ];
  });
  return (
    <>
      {serverPackets.map(({ event, position }, index) => {
        const kind = communicationKind(event);
        return (
          <Marker
            key={`server-message-${event.message_id ?? event.at}-${index}`}
            position={position}
            icon={communicationIcon(kind)}
          >
            <Tooltip direction="top">{communicationLabel(event)}</Tooltip>
          </Marker>
        );
      })}
      {clientPackets.map(({ entry, position }, index) => (
        <Marker
          key={`client-content-${entry.at}-${entry.client_id}-${index}`}
          position={position}
          icon={communicationIcon("client_content", true)}
        >
          <Tooltip direction="top">
            entrega de conteúdo · {entry.client_id} · {entry.server_id}
          </Tooltip>
        </Marker>
      ))}
    </>
  );
}

function communicationKind(
  event: SimulationEvent,
): "blacklist" | "new_content" | "update" | "failover" | "capacity" | "health" {
  if (
    event.communication_kind === "blacklist" ||
    event.message_type === "BLACKLIST_ALERT"
  )
    return "blacklist";
  if (
    event.communication_kind === "new_content" ||
    event.message_type === "NEW_CONTENT_DELIVERY"
  )
    return "new_content";
  if (event.communication_kind === "failover" || event.message_type === "FAILOVER_ROUTE") return "failover";
  if (event.communication_kind === "capacity" || event.message_type === "CAPACITY_ALERT") return "capacity";
  if (event.communication_kind === "health" || event.message_type === "HEALTH_SIGNAL") return "health";
  return "update";
}

function communicationLabel(event: SimulationEvent) {
  if (communicationKind(event) === "blacklist")
    return `aviso de blacklist · ${event.from_server} → ${event.to_server}`;
  if (communicationKind(event) === "new_content")
    return `novo conteúdo · ${event.from_server} → ${event.to_server}`;
  if (communicationKind(event) === "failover")
    return `failover de rota · ${event.from_server} → ${event.to_server}`;
  if (communicationKind(event) === "capacity")
    return `alerta de capacidade · ${event.from_server} → ${event.to_server}`;
  if (communicationKind(event) === "health")
    return `sinal de saúde · ${event.from_server} → ${event.to_server}`;
  return `atualização/metadados · ${event.from_server} → ${event.to_server}`;
}

function communicationIcon(
  kind: "blacklist" | "new_content" | "update" | "client_content" | "failover" | "capacity" | "health",
  small = false,
) {
  return divIcon({
    className: "map-communication-icon",
    html: `<span class="map-communication-diamond map-communication-diamond--${kind}${small ? " map-communication-diamond--small" : ""}"></span>`,
    iconSize: small ? [10, 10] : [14, 14],
    iconAnchor: small ? [5, 5] : [7, 7],
  });
}

function MapLegends() {
  return (
    <details className="map-legends" aria-label="Legendas do mapa">
      <summary>Legenda do mapa</summary>
      <section className="map-legend-card">
        <strong>ENTIDADES E TRAÇADOS</strong>
        <div className="map-legend-grid">
          <LegendItem symbol="server-active" label="servidor ativo e estável" />
          <LegendItem symbol="server-degraded" label="servidor degradado" />
          <LegendItem
            symbol="server-overloaded"
            label="servidor sobrecarregado"
          />
          <LegendItem symbol="client-active" label="cliente" />
          <LegendItem symbol="client-dangerous" label="cliente perigoso" />
          <LegendItem symbol="client-banned" label="cliente banido" />
          <LegendItem
            symbol="line-server"
            label="comunicação entre servidores"
          />
          <LegendItem
            symbol="line-client"
            label="comunicação servidor-cliente"
          />
        </div>
      </section>
      <section className="map-legend-card">
        <strong>COMUNICAÇÕES</strong>
        <div className="map-legend-grid">
          <LegendItem
            symbol="diamond-client"
            label="entrega de conteúdo ao cliente"
          />
          <LegendItem
            symbol="diamond-failover"
            label="failover de requisição"
          />
          <LegendItem
            symbol="diamond-capacity"
            label="alerta de capacidade"
          />
        </div>
      </section>
    </details>
  );
}

function LegendItem({ symbol, label }: { symbol: string; label: string }) {
  return (
    <span className="map-legend-item">
      <i className={`map-legend-symbol map-legend-symbol--${symbol}`} />
      {label}
    </span>
  );
}
function PortugueseLeafletControls() {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer();
    const zoomIn = container.querySelector<HTMLElement>(
      ".leaflet-control-zoom-in",
    );
    const zoomOut = container.querySelector<HTMLElement>(
      ".leaflet-control-zoom-out",
    );
    if (zoomIn) {
      zoomIn.title = "Aproximar mapa";
      zoomIn.setAttribute("aria-label", "Aproximar mapa");
    }
    if (zoomOut) {
      zoomOut.title = "Afastar mapa";
      zoomOut.setAttribute("aria-label", "Afastar mapa");
    }
  }, [map]);
  return null;
}
function MapClickHandler({
  enabled,
  onPick,
}: {
  enabled: boolean;
  onPick: (latitude: number, longitude: number) => void;
}) {
  useMapEvents({
    click: (event) => {
      if (enabled) onPick(event.latlng.lat, event.latlng.lng);
    },
  });
  return null;
}
