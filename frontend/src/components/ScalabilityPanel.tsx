import { Gauge, Landmark, Server, TrendingUp, Users } from "lucide-react";
import type { SimulationStatus } from "../types";

export function ScalabilityPanel({ status }: { status: SimulationStatus }) {
  const scale = status.scalability;
  const economics = scale.cost_model;
  const percent = Math.max(0, Math.round(scale.utilization * 100));
  const sloHealth = Math.max(0, Math.round(scale.health_score_pct ?? 0));
  const capacityTone = percent >= 100 ? "danger" : percent >= 75 ? "warning" : "good";
  const sloTone = sloHealth < 70 ? "danger" : sloHealth < 95 ? "warning" : "good";
  const tone =
    scale.profile === "gargalo" || scale.profile === "alerta" || scale.profile === "critica"
      ? "scale-danger"
      : scale.profile === "sobredimensionada"
        ? "scale-warning"
        : "scale-good";
  return (
    <section className={`panel scalability-panel ${tone}`}>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">CAPACITY ECONOMICS / DIAGNÓSTICO</p>
          <h2>Escalabilidade em tempo real</h2>
        </div>
        <Gauge size={19} />
      </div>
      <div className="scale-summary">
        <div>
          <strong>{scale.profile === "alerta" ? "ALERTA" : scale.profile}</strong>
          <span>{scale.message}</span>
        </div>
        <div className="scale-percentage">
          <strong className={`scale-value-${capacityTone}`}>{percent}%</strong>
          <small>utilização de capacidade</small>
          <small className={`slo-health scale-value-${sloTone}`}>saúde do serviço (SLO): {sloHealth}%</small>
        </div>
      </div>
      <div className="scale-bar">
        <i style={{ width: `${Math.min(100, percent)}%` }} />
        <b style={{ left: "75%" }} />
      </div>
      <div className="scale-stats">
        <div>
          <Users size={14} />
          <span>
            clientes ativos<strong>{scale.active_clients}</strong>
          </span>
        </div>
        <div>
          <Server size={14} />
          <span>
            capacidade<strong>{scale.capacity_rps ?? scale.total_capacity} req/s</strong>
            <small>
              {scale.available_servers ?? scale.healthy_servers} nós disponíveis · demanda virtual {scale.demand_rps ?? 0} req/s
            </small>
          </span>
        </div>
        <div>
          <TrendingUp size={14} />
          <span>
            latência média / p95
            <strong>
              {scale.average_latency_ms} / {scale.p95_latency_ms} ms
            </strong>
          </span>
        </div>
        <div>
          <Gauge size={14} />
          <span>
            espera de fila<strong>{scale.estimated_queue_latency_ms} ms</strong>
          </span>
        </div>
      </div>
      <div className="observed-metrics">
        <span>
          observado: <b>{scale.observed_rps ?? 0} req/s</b>
        </span>
        <span>
          p50/p99:{" "}
          <b>
            {scale.p50_latency_ms ?? 0}/{scale.p99_latency_ms ?? 0} ms
          </b>
        </span>
        <span>
          janela: <b>{scale.metrics_window_seconds ?? 60}s</b>
        </span>
        <span>
          erros: <b>{scale.observed_errors ?? 0}</b>
        </span>
        <span>
          SLO: <b>{scale.slo_compliant === undefined ? "sem dados" : scale.slo_compliant ? "atendido" : "violado"}</b>
        </span>
        <span>
          saúde: <b>{scale.health_score_pct === undefined ? "sem dados" : `${Math.round(scale.health_score_pct)}%`}</b>
        </span>
      </div>
      <div className="economics-grid">
        <div>
          <span>Custo mensal total</span>
          <strong>{formatUsd(economics.total_monthly_cost_usd)}</strong>
          <small>
            {formatUsd(economics.server_cost_usd)} servidores +{" "}
            {formatUsd(economics.fixed_cost_usd)} fixo +{" "}
            {formatUsd(economics.variable_cost_usd)} variável
          </small>
        </div>
        <div>
          <span>Preço mínimo de equilíbrio</span>
          <strong>
            {formatUsd(economics.break_even_price_per_client_usd)}/cliente
          </strong>
          <small>sem margem, diluído em {status.clients_total} clientes</small>
        </div>
        <div>
          <span>Preço recomendado</span>
          <strong>
            {formatUsd(economics.minimum_price_with_margin_per_client_usd)}
            /cliente
          </strong>
          <small>inclui margem didática de 20%</small>
        </div>
        <div>
          <span>Receita / margem projetada</span>
          <strong>
            {formatUsd(economics.projected_revenue_usd)} /{" "}
            {formatUsd(economics.projected_margin_usd)}
          </strong>
          <small>
            no preço configurado de{" "}
            {formatUsd(economics.configured_client_price_usd)}
          </small>
        </div>
      </div>
      <p className="economics-note">
        <Landmark size={13} /> Capacidade por nó é estimada pelo gargalo de CPU/rede;
        demanda e custos são didáticos. RTT, fila e E2E vêm dos processos locais.
      </p>
    </section>
  );
}

function formatUsd(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}
