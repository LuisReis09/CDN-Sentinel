import { AlertTriangle, Ban, CheckCircle2, GitBranch, KeyRound, MessageSquare, Radio, ScanSearch, Server, Settings2, UserPlus } from "lucide-react";
import type { SimulationEvent } from "../types";

const iconByType = { client_request: Radio, client_connected: Radio, client_disconnected: Radio, blacklist_propagated: Ban, monitor_scan: ScanSearch, simulation_config_updated: Settings2, simulation_initialized: CheckCircle2, watermark_verified: KeyRound, server_added: Server, client_added: UserPlus, simulation_paused: Settings2, simulation_resumed: GitBranch, server_message: MessageSquare } as const;

function labelFor(event: SimulationEvent) {
  if (event.type === "client_request") return `${event.client_id} requisitou chunk via ${event.server_id}`;
  if (event.type === "client_connected") return `${event.client_id} conectou-se novamente`;
  if (event.type === "client_disconnected") return `${event.client_id} saiu após consumir ${event.videos_consumed ?? 0} vídeo(s)`;
  if (event.type === "blacklist_propagated") return `${event.client_id} banido e propagado por ${event.propagated_to?.length ?? 0} nós`;
  if (event.type === "monitor_scan") return `Monitor encontrou ${event.detected ?? 0} vazamento(s) automaticamente`;
  if (event.type === "server_message") return `${event.message_type ?? "Mensagem"}: ${event.from_server ?? "origem"} → ${event.to_server ?? "destino"} (${event.status ?? "observada"})`;
  if (event.type === "simulation_tick") return `Tick ${event.tick ?? "?"}: intervalo ${event.tick_interval_seconds ?? "—"}s · churn de sessão 20%`;
  if (event.type === "watermark_verified") return `${event.client_id} validado com HMAC-SHA256`;
  if (event.type === "server_added") return `${event.server_id} entrou na malha distribuída`;
  if (event.type === "client_added") return `${event.client_id} adicionado ao mapa operacional`;
  if (event.type === "simulation_paused") return "Simulação pausada pelo operador";
  if (event.type === "simulation_resumed") return "Simulação retomada pelo operador";
  if (event.type === "simulation_config_updated") return "Parâmetros da simulação atualizados";
  return "Topologia distribuída inicializada";
}

export function ActivityFeed({ events }: { events: SimulationEvent[] }) {
  return <div className="activity-list">{events.slice(-10).reverse().map((event, index) => { const Icon = iconByType[event.type as keyof typeof iconByType] ?? AlertTriangle; return <div className="activity-row" key={`${event.at}-${index}`}><span className="activity-icon"><Icon size={14} /></span><div><strong>{labelFor(event)}</strong><small>{new Date(event.at * 1000).toLocaleTimeString("pt-BR")}{event.payload_summary ? ` · ${event.payload_summary}` : ""}</small></div></div>; })}</div>;
}
