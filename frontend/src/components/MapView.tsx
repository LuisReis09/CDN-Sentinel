import { Fragment, useEffect } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";
import type { Client, ServerNode, SimulationEvent, Traffic } from "../types";

interface MapViewProps {
  clients: Client[];
  servers: ServerNode[];
  traffic: Traffic[];
  events: SimulationEvent[];
  editMode: "client" | "server" | null;
  onMapPick: (latitude: number, longitude: number) => void;
}

export function MapView({ clients, servers, traffic, events, editMode, onMapPick }: MapViewProps) {
  const clientsById = new Map(clients.map((client) => [client.client_id, client]));
  const serversById = new Map(servers.map((server) => [server.server_id, server]));
  const trafficLines = traffic.slice(-30).flatMap((entry) => {
    const client = clientsById.get(entry.client_id);
    const server = serversById.get(entry.server_id);
    return client && server ? [{ entry, positions: [[client.latitude, client.longitude], [server.latitude, server.longitude]] as [[number, number], [number, number]] }] : [];
  });
  const now = Date.now() / 1000;
  const gossipActive = events.some((event) => event.type === "blacklist_propagated" && event.at > now - 30);
  const serverLinks: Array<[[number, number], [number, number]]> = servers.flatMap((server, index) => servers.slice(index + 1).map((peer) => [[server.latitude, server.longitude], [peer.latitude, peer.longitude]] as [[number, number], [number, number]]));

  return (
    <div className={`map-shell ${editMode ? "map-shell-editing" : ""}`}>
      <MapContainer center={[18, 0]} zoom={2} minZoom={2} maxZoom={6} scrollWheelZoom className="world-map">
        <PortugueseLeafletControls />
        <MapClickHandler enabled={Boolean(editMode)} onPick={onMapPick} />
        <TileLayer attribution='Dados cartográficos © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> e colaboradores' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {serverLinks.map((line, index) => <Fragment key={`gossip-pair-${index}`}>
          <Polyline key={`gossip-glow-${index}`} positions={line} pathOptions={{ className: "map-gossip-path", color: gossipActive ? "#9eff6c" : "#a78bfa", weight: gossipActive ? 8 : 5, opacity: gossipActive ? 0.18 : 0.1, dashArray: "7 12" }} />
          <Polyline key={`gossip-${index}`} positions={line} pathOptions={{ className: "map-gossip-path", color: gossipActive ? "#b8ff92" : "#b59cff", weight: gossipActive ? 3 : 2, opacity: gossipActive ? 0.9 : 0.58, dashArray: "7 12" }} />
        </Fragment>)}
        {trafficLines.map(({ entry, positions }, index) => <Fragment key={`traffic-pair-${entry.at}-${index}`}>
          <Polyline key={`traffic-glow-${entry.at}-${index}`} positions={positions} pathOptions={{ className: "map-traffic-path", color: "#28d7ff", weight: 10, opacity: 0.18, dashArray: "12 8" }} />
          <Polyline key={`traffic-${entry.at}-${index}`} positions={positions} pathOptions={{ className: "map-traffic-path", color: "#62e5ff", weight: 4, opacity: 0.96, dashArray: "12 8" }} />
        </Fragment>)}
        {servers.map((server) => (
          <CircleMarker key={server.server_id} center={[server.latitude, server.longitude]} radius={9} pathOptions={{ color: "#9eff6c", fillColor: "#2f8d52", fillOpacity: 0.9, weight: 2 }}>
            <Popup><strong>{server.server_id}</strong><br />{server.city}<br />:{server.port} · carga {server.load}</Popup>
          </CircleMarker>
        ))}
        {clients.map((client) => {
          const banned = !client.active;
          const offline = !banned && !client.online;
          return (
            <CircleMarker key={client.client_id} center={[client.latitude, client.longitude]} radius={banned ? 7 : 5} pathOptions={{ color: banned ? "#ff6177" : offline ? "#7e91a6" : client.malicious ? "#ffb86b" : "#64b5ff", fillColor: banned ? "#a52b47" : offline ? "#34465a" : client.malicious ? "#b5682e" : "#1763a1", fillOpacity: 0.86, weight: 1.5 }}>
              <Popup><strong>{client.client_id}</strong><br />{client.city}<br />{banned ? "BLACKLIST" : offline ? "offline / sessão encerrada" : client.malicious ? "malicioso / online" : "normal / online"}<br />vídeos: {client.videos_consumed}</Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
      {editMode && <div className="map-edit-hint">Clique para posicionar {editMode === "client" ? "um usuário" : "um servidor CDN"}</div>}
      <div className="map-protocols"><span className="map-protocol map-protocol-client">CLIENTE → CDN <small>HTTP stream</small></span><span className="map-protocol map-protocol-gossip">CDN ⇄ CDN <small>HTTP gossip</small></span></div>
      <div className="map-legend"><span><i className="legend-dot legend-server" /> CDN</span><span><i className="legend-dot legend-gossip" /> gossip</span><span><i className="legend-dot legend-client" /> cliente</span><span><i className="legend-dot legend-risk" /> risco</span><span><i className="legend-dot legend-offline" /> offline</span><span><i className="legend-dot legend-banned" /> blacklist</span></div>
    </div>
  );
}

function PortugueseLeafletControls() {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer();
    const zoomIn = container.querySelector<HTMLElement>(".leaflet-control-zoom-in");
    const zoomOut = container.querySelector<HTMLElement>(".leaflet-control-zoom-out");
    if (zoomIn) { zoomIn.title = "Aproximar mapa"; zoomIn.setAttribute("aria-label", "Aproximar mapa"); }
    if (zoomOut) { zoomOut.title = "Afastar mapa"; zoomOut.setAttribute("aria-label", "Afastar mapa"); }
  }, [map]);
  return null;
}

function MapClickHandler({ enabled, onPick }: { enabled: boolean; onPick: (latitude: number, longitude: number) => void }) {
  useMapEvents({
    click: (event) => {
      if (enabled) onPick(event.latlng.lat, event.latlng.lng);
    },
  });
  return null;
}

