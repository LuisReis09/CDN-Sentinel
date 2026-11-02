import { Gauge, Server, TrendingUp, Users } from "lucide-react";
import type { SimulationStatus } from "../types";

export function ScalabilityPanel({ status }: { status: SimulationStatus }) {
  const scale = status.scalability;
  const percent = Math.min(150, Math.round(scale.utilization * 100));
  const tone = scale.profile === "gargalo" ? "scale-danger" : scale.profile === "sobredimensionada" ? "scale-warning" : "scale-good";
  return <section className={`panel scalability-panel ${tone}`}><div className="panel-heading"><div><p className="eyebrow">CAPACITY ECONOMICS</p><h2>Escalabilidade em tempo real</h2></div><Gauge size={19} /></div><div className="scale-summary"><div><strong>{scale.profile}</strong><span>{scale.message}</span></div><div className="scale-percentage">{percent}%<small>utilização</small></div></div><div className="scale-bar"><i style={{ width: `${Math.min(100, percent)}%` }} /><b style={{ left: `${Math.min(100, Math.round(0.75 * 100))}%` }} /></div><div className="scale-stats"><div><Users size={14} /><span>clientes online<strong>{scale.online_clients}</strong></span></div><div><Server size={14} /><span>capacidade<strong>{scale.total_capacity}</strong></span></div><div><TrendingUp size={14} /><span>custo estimado<strong>{scale.estimated_cost_units} u.</strong></span></div><div><Gauge size={14} /><span>fila projetada<strong>{scale.estimated_queue_latency_ms} ms</strong></span></div></div></section>;
}

