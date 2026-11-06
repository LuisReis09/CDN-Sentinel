import { Fragment, useEffect, useState } from "react";
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

interface MapViewProps {
  clients: Client[];
  servers: ServerNode[];
  traffic: Traffic[];
  events: SimulationEvent[];
  editMode: "client" | "server" | null;
  onMapPick: (latitude: number, longitude: number) => void;
  tickIntervalSeconds: number;
  onNodeSelect: (kind: "server" | "client", id: string) => void;
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
}: MapViewProps) {
  const clientsById = new Map(
    clients.map((client) => [client.client_id, client]),
  );
  const serversById = new Map(
    servers.map((server) => [server.server_id, server]),
  );
  const trafficLines = traffic.slice(-30).flatMap((entry) => {
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
  const serverLinks: Array<[[number, number], [number, number]]> =
    servers.flatMap((server, index) =>
      servers.slice(index + 1).map(
        (peer) =>
          [
            [server.latitude, server.longitude],
            [peer.latitude, peer.longitude],
          ] as [[number, number], [number, number]],
      ),
    );
  const messageEvents = events.filter(
    (event) =>
      event.type === "server_message" && event.from_server && event.to_server,
  );
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
          attribution='Dados cartográficos © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> e colaboradores'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <CommunicationOverlay
          clients={clients}
          servers={servers}
          traffic={traffic}
          events={messageEvents}
          tickIntervalSeconds={tickIntervalSeconds}
        />
        {serverLinks.map((line, index) => (
          <Polyline
            key={`gossip-pair-${index}`}
            positions={line}
            pathOptions={{
              className: "map-gossip-path",
              color: "#438fe8",
              weight: messageEvents.length ? 3.5 : 2.2,
              opacity: messageEvents.length ? 0.55 : 0.34,
              dashArray: "7 12",
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
        {servers.map((server) => (
          <ServerMarker
            key={server.server_id}
            server={server}
            onSelect={() => onNodeSelect("server", server.server_id)}
          />
        ))}
        {clients.map((client) => (
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

function ServerMarker({
  server,
  onSelect,
}: {
  server: ServerNode;
  onSelect: () => void;
}) {
  const available = !["offline", "stopped", "error"].includes(server.status);
  const overloaded =
    server.health_status === "overloaded" || (server.utilization ?? 0) >= 0.95;
  const state = !available
    ? "offline"
    : overloaded
      ? "overloaded"
      : server.health_status === "degraded" || server.status === "degraded"
        ? "degraded"
        : "active";
  const colors = {
    active: { color: "#9eff6c", fillColor: "#2f8d52" },
    degraded: { color: "#ffb86b", fillColor: "#9b5c25" },
    overloaded: { color: "#ffe06b", fillColor: "#b58a2e" },
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
        carga {server.load} · {overloaded ? "sobrecarregado" : server.status}
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
  const offline =
    !banned &&
    !dangerous &&
    (!client.online || client.process_status === "offline");
  const state = banned
    ? "banned"
    : dangerous
      ? "dangerous"
      : offline
        ? "inactive"
        : "active";
  const colors = {
    active: { color: "#8fc8ff", fillColor: "#1763a1" },
    inactive: { color: "#b0b7be", fillColor: "#59636d" },
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
            : offline
              ? "cliente inativo"
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
  const serverPackets = events.slice(-16).flatMap((event) => {
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
  const clientPackets = traffic.slice(-18).flatMap((entry) => {
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
): "blacklist" | "new_content" | "update" {
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
  return "update";
}

function communicationLabel(event: SimulationEvent) {
  if (communicationKind(event) === "blacklist")
    return `aviso de blacklist · ${event.from_server} → ${event.to_server}`;
  if (communicationKind(event) === "new_content")
    return `novo conteúdo · ${event.from_server} → ${event.to_server}`;
  return `atualização/metadados · ${event.from_server} → ${event.to_server}`;
}

function communicationIcon(
  kind: "blacklist" | "new_content" | "update" | "client_content",
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
    <div className="map-legends" aria-label="Legendas do mapa">
      <section className="map-legend-card">
        <strong>ENTIDADES E TRAÇADOS</strong>
        <div className="map-legend-grid">
          <LegendItem symbol="server-active" label="servidor ativo e estável" />
          <LegendItem
            symbol="server-overloaded"
            label="servidor sobrecarregado"
          />
          <LegendItem symbol="client-active" label="cliente" />
          <LegendItem symbol="client-inactive" label="cliente inativo" />
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
            symbol="diamond-blacklist"
            label="aviso de banimento / blacklist"
          />
          <LegendItem
            symbol="diamond-content"
            label="entrega de novos conteúdos"
          />
          <LegendItem
            symbol="diamond-update"
            label="atualizações e metadados"
          />
          <LegendItem
            symbol="diamond-client"
            label="entrega de conteúdo ao cliente"
          />
        </div>
      </section>
    </div>
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
