import { Activity, Filter, MessageSquare, Server, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Client, ServerNode, SimulationEvent } from "../types";

interface EventLogPanelProps {
  events: SimulationEvent[];
  servers: ServerNode[];
  clients: Client[];
  selected?: { kind: "server" | "client"; id: string } | null;
}

export function EventLogPanel({ events, servers, clients, selected = null }: EventLogPanelProps) {
  const [filter, setFilter] = useState(selected ? `${selected.kind}:${selected.id}` : "all");
  useEffect(() => { if (selected) setFilter(`${selected.kind}:${selected.id}`); }, [selected]);
  const filtered = useMemo(() => events.filter((event) => matchesFilter(event, filter)), [events, filter]);
  const filterLabel = filter === "all" ? "Todos os eventos" : filter.split(":")[1] ?? "Filtro";

  return <section className="panel event-log-panel">
    <div className="panel-heading"><div><p className="eyebrow">OBSERVABILITY / LOG CENTRAL</p><h2>{filter === "all" ? "Logs gerais" : `Logs de ${filterLabel}`}</h2></div><div className="log-filter-control"><label htmlFor="event-log-scope"><span><Filter size={12} /> Escopo</span><select id="event-log-scope" aria-label="Escopo dos logs" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">Todos os eventos</option><optgroup label="Servidores">{servers.map((server) => <option key={server.server_id} value={`server:${server.server_id}`}>{server.server_id} · porta {server.port}</option>)}</optgroup><optgroup label="Clientes">{clients.map((client) => <option key={client.client_id} value={`client:${client.client_id}`}>{client.client_id}</option>)}</optgroup></select></label>{filter !== "all" && <button type="button" className="log-filter-clear" onClick={() => setFilter("all")} aria-label="Limpar filtro"><X size={13} /></button>}</div></div>
    <div className="log-subtitle"><Activity size={13} /> {filter === "all" ? "Visão consolidada de processos, ticks, streaming, monitoramento e mensagens entre CDN." : `Acompanhando somente eventos relacionados a ${filterLabel}.`}<span className="log-count">{filtered.length} eventos</span></div>
    <div className="event-log-list">{filtered.slice(-24).reverse().map((event, index) => <LogRow key={`${event.at}-${event.type}-${index}`} event={event} />)}{filtered.length === 0 && <div className="empty-state"><MessageSquare size={22} /><span>Nenhum evento para este filtro.</span></div>}</div>
  </section>;
}

function matchesFilter(event: SimulationEvent, filter: string) {
  if (filter === "all") return true;
  const [kind, id] = filter.split(":");
  return kind === "server" ? event.server_id === id || event.monitor_server_id === id || event.from_server === id || event.to_server === id : event.client_id === id;
}

function LogRow({ event }: { event: SimulationEvent }) {
  const isMessage = event.type === "server_message";
  const Icon = isMessage ? MessageSquare : event.server_id ? Server : UserRound;
  const title = isMessage ? `${event.message_type ?? "Mensagem"} · ${event.from_server ?? "origem"} → ${event.to_server ?? "destino"}` : event.type.replace(/_/g, " ");
  const detail = isMessage ? `${event.status ?? "observado"} · ${event.payload_summary ?? "payload operacional"}` : [event.client_id, event.server_id, event.chunk_id, event.reason].filter((value): value is string => Boolean(value)).join(" · ");
  return <div className={`log-row ${event.status === "failed" ? "log-row-failed" : ""}`}><span className="log-icon"><Icon size={14} /></span><div><strong>{title}</strong><small>{detail || "sem detalhes adicionais"}</small></div><time>{Number.isFinite(event.at) ? new Date(event.at * 1000).toLocaleTimeString("pt-BR") : "—"}</time></div>;
}
