import {
  CheckCircle2,
  GitBranch,
  Globe2,
  KeyRound,
  Network,
  Route,
  Server,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Overview } from "../types";

export function DistributedEvidencePanel({ overview }: { overview: Overview }) {
  const healthyNodes = overview.servers.filter(
    (server) => server.status === "healthy",
  ).length;
  const requestEvents = overview.recent_events.filter(
    (event) => event.type === "client_request",
  );
  const verifiedWatermarks = overview.recent_events.filter(
    (event) =>
      event.type === "watermark_verified" || event.type === "monitor_scan",
  ).length;
  const gossipEvents = overview.recent_events.filter(
    (event) => event.type === "blacklist_propagated",
  );
  const syncedNodes = Math.max(
    0,
    ...gossipEvents.map((event) => event.propagated_to?.length ?? 0),
  );
  const avgDistance = overview.recent_traffic.length
    ? Math.round(
        overview.recent_traffic.reduce(
          (sum, item) => sum + item.distance_km,
          0,
        ) / overview.recent_traffic.length,
      )
    : 0;
  const latestRequest = requestEvents[requestEvents.length - 1];

  return (
    <section className="panel evidence-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">DISTRIBUTED SYSTEM PROOF</p>
          <h2>O que está realmente acontecendo</h2>
        </div>
        <CheckCircle2 size={19} className="evidence-ok" />
      </div>
      <div className="evidence-grid">
        <EvidenceItem
          icon={<Network size={17} />}
          label="Transporte entre nós"
          value="HTTP/1.1 real"
          detail={`${healthyNodes}/${overview.servers.length} processos saudáveis`}
          tone="cyan"
        />
        <EvidenceItem
          icon={<Globe2 size={17} />}
          label="Roteamento geográfico"
          value="Haversine"
          detail={
            avgDistance
              ? `${avgDistance.toLocaleString("pt-BR")} km médios observados`
              : "aguardando requisições"
          }
          tone="orange"
        />
        <EvidenceItem
          icon={<KeyRound size={17} />}
          label="Prova forense"
          value="AES-GCM / HMAC"
          detail={`${verifiedWatermarks} verificações registradas`}
          tone="green"
        />
        <EvidenceItem
          icon={<GitBranch size={17} />}
          label="Gossip de blacklist"
          value="gossip cifrado"
          detail={`${syncedNodes || 0} nós sincronizados`}
          tone="red"
        />
      </div>
      <div className="evidence-trace">
        <div className="trace-label">
          <Route size={15} />
          <span>última trilha observada</span>
        </div>
        <div className="trace-chain">
          <TraceStep
            icon={<Server size={14} />}
            title={latestRequest?.client_id ?? "cliente"}
            value={latestRequest ? "requisição" : "aguardando"}
          />
          <span className="trace-arrow">→</span>
          <TraceStep
            icon={<Network size={14} />}
            title={latestRequest?.server_id ?? "nó CDN"}
            value={latestRequest?.protocol ?? "HTTP/1.1"}
          />
          <span className="trace-arrow">→</span>
          <TraceStep
            icon={<KeyRound size={14} />}
            title="watermark"
            value={latestRequest?.watermark_algorithm ?? "AES-GCM + HMAC"}
          />
          <span className="trace-arrow">→</span>
          <TraceStep
            icon={<GitBranch size={14} />}
            title="governança"
            value={gossipEvents.length ? "gossip ativo" : "monitor aguardando"}
          />
        </div>
      </div>
    </section>
  );
}

function EvidenceItem({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: "cyan" | "orange" | "green" | "red";
}) {
  return (
    <div className={`evidence-item evidence-${tone}`}>
      <div className="evidence-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}
function TraceStep({
  icon,
  title,
  value,
}: {
  icon: ReactNode;
  title: string;
  value: string;
}) {
  return (
    <div className="trace-step">
      <span>{icon}</span>
      <div>
        <strong>{title}</strong>
        <small>{value}</small>
      </div>
    </div>
  );
}
