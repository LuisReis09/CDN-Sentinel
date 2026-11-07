import { Activity, Ban, HeartPulse, Server } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TelemetrySample } from "../types";

const colors = ["#45d9ff", "#9eff6c", "#ffb86b", "#ff6177", "#b99cff"];

export function TelemetryCharts({ samples }: { samples: TelemetrySample[] }) {
  const serverIds = Array.from(
    new Set(samples.flatMap((sample) => Object.keys(sample.server_requests ?? {}))),
  );
  const data = samples.map((sample) => ({
    ...sample,
    time: `${Math.round(sample.elapsed_seconds)}s`,
    ...sample.server_requests,
  }));

  return (
    <section className="telemetry-section">
      <div className="section-heading-inline">
        <div>
          <p className="eyebrow">SIMULATION EVOLUTION / CUMULATIVE TELEMETRY</p>
          <h2>Como a CDN mudou ao longo da execução</h2>
        </div>
        <span className="telemetry-count">{samples.length} amostras</span>
      </div>
      {samples.length === 0 ? (
        <div className="panel telemetry-empty">
          <Activity size={18} /> Inicie a simulação para preencher as séries temporais.
        </div>
      ) : (
        <div className="telemetry-chart-grid">
          <ChartPanel icon={<Ban size={15} />} title="Blacklist acumulada" tone="red">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data}>
                <ChartGrid />
                <ChartAxis />
                <YAxis allowDecimals={false} />
                <ChartTip />
                <Area type="monotone" dataKey="blacklist_total" stroke="#ff6177" fill="#ff6177" fillOpacity={0.14} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartPanel>

          <ChartPanel icon={<Server size={15} />} title="Requisições por servidor" tone="cyan">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data}>
                <ChartGrid />
                <ChartAxis />
                <YAxis allowDecimals={false} />
                <ChartTip />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                {serverIds.map((serverId, index) => (
                  <Line key={serverId} type="monotone" dataKey={serverId} name={serverId} stroke={colors[index % colors.length]} dot={false} strokeWidth={2} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </ChartPanel>

          <ChartPanel icon={<Activity size={15} />} title="Tempo de resposta" tone="orange">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data}>
                <ChartGrid />
                <ChartAxis />
                <YAxis unit=" ms" />
                <ChartTip />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <Line type="monotone" dataKey="average_latency_ms" name="média" stroke="#ffb86b" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="p95_latency_ms" name="p95" stroke="#ff6177" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </ChartPanel>

          <ChartPanel icon={<HeartPulse size={15} />} title="Saúde geral da CDN" tone="green">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data}>
                <ChartGrid />
                <ChartAxis />
                <YAxis domain={[0, 100]} unit="%" />
                <ChartTip />
                <Area type="monotone" dataKey="health_score_pct" name="saúde" stroke="#9eff6c" fill="#9eff6c" fillOpacity={0.14} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartPanel>
        </div>
      )}
    </section>
  );
}

function ChartPanel({
  icon,
  title,
  tone,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  tone: "red" | "cyan" | "orange" | "green";
  children: React.ReactNode;
}) {
  return (
    <article className={`panel telemetry-chart telemetry-chart--${tone}`}>
      <div className="telemetry-chart-heading">
        <span>{icon}</span>
        <strong>{title}</strong>
      </div>
      <div className="telemetry-chart-canvas">{children}</div>
    </article>
  );
}

function ChartGrid() {
  return <CartesianGrid stroke="rgba(165,202,238,.12)" vertical={false} />;
}

function ChartAxis() {
  return <XAxis dataKey="time" tick={{ fill: "#7890a7", fontSize: 9 }} />;
}

function ChartTip() {
  return (
    <Tooltip
      contentStyle={{
        background: "#0b1727",
        border: "1px solid rgba(165,202,238,.2)",
        fontSize: 10,
      }}
    />
  );
}
