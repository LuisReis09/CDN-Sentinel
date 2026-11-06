import {
  Activity,
  ArrowUpRight,
  Banknote,
  BarChart3,
  Gauge,
  GitBranch,
  Server,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import { MapView } from "../components/MapView";
import type {
  ManagementActionDefinition,
  ManagementState,
  Overview,
} from "../types";

interface ManagementPageProps {
  overview: Overview;
  connected: boolean;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}

export function ManagementPage({
  overview,
  connected,
  onRefresh,
  onError,
}: ManagementPageProps) {
  const [management, setManagement] = useState<ManagementState | null>(null);
  const [actions, setActions] = useState<ManagementActionDefinition[]>([]);
  const [scenarios, setScenarios] = useState<Array<Record<string, unknown>>>(
    [],
  );
  const [scenarioId, setScenarioId] = useState("free");
  const [selectedAction, setSelectedAction] =
    useState<ManagementActionDefinition | null>(null);
  const [parameters, setParameters] = useState<Record<string, unknown>>({
    operation: "add",
    latitude: -23.55,
    longitude: -46.63,
    level: 1,
    tier: "standard",
    policy: "least-utilized",
    monthly_price_usd: 25,
  });
  const [busy, setBusy] = useState(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  async function loadManagement() {
    try {
      const [state, actionResponse, scenarioResponse] = await Promise.all([
        api.managementState(),
        api.managementActions(),
        api.managementScenarios(),
      ]);
      setManagement(state);
      setActions(actionResponse.actions);
      setScenarios(scenarioResponse.scenarios);
    } catch (cause) {
      onError(
        cause instanceof Error ? cause.message : "Falha ao carregar a gestão",
      );
    }
  }

  useEffect(() => {
    void loadManagement();
    const timer = window.setInterval(
      () => void api.managementState().then(setManagement),
      3000,
    );
    return () => window.clearInterval(timer);
  }, []);

  const history = management?.history ?? [];
  const selectedNodeData = selectedNode
    ? overview.servers.find((server) => server.server_id === selectedNode)
    : overview.servers[0];
  const groupedActions = useMemo(
    () =>
      ["Infraestrutura", "Otimização", "Comercial"].map((group) => ({
        group,
        items: actions.filter((action) => action.group === group),
      })),
    [actions],
  );

  async function startScenario() {
    setBusy(true);
    try {
      setManagement(await api.startManagementScenario(scenarioId));
      await onRefresh();
    } catch (cause) {
      onError(
        cause instanceof Error ? cause.message : "Falha ao iniciar cenário",
      );
    } finally {
      setBusy(false);
    }
  }

  async function confirmAction() {
    if (!selectedAction || !management) return;
    setBusy(true);
    try {
      const result = await api.applyManagementAction({
        action_type: selectedAction.action_type,
        parameters,
        expected_version: management.version,
      });
      setManagement(result.state);
      setSelectedAction(null);
      await onRefresh();
    } catch (cause) {
      onError(
        cause instanceof Error ? cause.message : "Ação rejeitada pelo backend",
      );
    } finally {
      setBusy(false);
    }
  }

  const state = management;
  const pressure = Math.min(150, Math.round((state?.utilization ?? 0) * 100));
  const chartData = history.map((item) => ({
    day: `D${item.day ?? 0}`,
    profit: Number(item.daily_profit_usd ?? 0),
    p95: Number(item.latency_p95_ms ?? 0),
    demand: Number(item.demand_rps ?? 0),
    capacity: Number(item.capacity_rps ?? 0),
  }));

  return (
    <main className="page-content management-page">
      <header className="management-header">
        <div>
          <p className="eyebrow">CDN MANAGEMENT CENTER / DIDACTIC SIMULATOR</p>
          <h1>Centro de Gestão da CDN</h1>
          <p className="page-lead">
            Decida sobre capacidade, preço e otimização. O backend calcula
            custos, efeitos e consequências; a telemetria local mostra o que
            realmente respondeu.
          </p>
        </div>
        <div className="management-toolbar">
          <label>
            <span>Cenário</span>
            <select
              value={scenarioId}
              onChange={(event) => setScenarioId(event.target.value)}
            >
              {scenarios.map((scenario) => (
                <option
                  key={String(scenario.scenario_id)}
                  value={String(scenario.scenario_id)}
                >
                  {String(scenario.label)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button button-primary"
            disabled={busy}
            onClick={() => void startScenario()}
          >
            <Sparkles size={14} /> Iniciar cenário
          </button>
          <span
            className={`connection-chip ${connected ? "connected" : "disconnected"}`}
          >
            {connected ? "BACKEND ONLINE" : "BACKEND OFFLINE"}
          </span>
        </div>
      </header>

      <section className="management-status-strip">
        <span>
          <strong>Dia simulado {state?.day ?? 0}</strong>
          <small>1 tick = 1 dia · seed {state?.seed ?? "—"}</small>
        </span>
        <span>
          <strong>{state?.scenario_id ?? "free"}</strong>
          <small>{String(state?.objective?.days ?? 30)} dias de objetivo</small>
        </span>
        <span>
          <strong>{state?.pending_actions.length ?? 0} pendentes</strong>
          <small>efeitos aplicados pelo backend</small>
        </span>
        <span>
          <strong>{state?.load_balancing_policy ?? "nearest-healthy"}</strong>
          <small>política operacional atual</small>
        </span>
      </section>

      <section className="management-kpis">
        <Kpi
          icon={<Banknote size={16} />}
          label="Saldo acumulado"
          value={formatUsd(state?.cash_balance_usd ?? 0)}
          detail={`lucro/dia ${formatUsd(state?.daily_profit_usd ?? 0)}`}
          tone="green"
        />
        <Kpi
          icon={<Users size={16} />}
          label="Pagantes / churn"
          value={`${state?.paying_clients ?? 0}`}
          detail={`${state?.churned_clients ?? 0} churn · ${state?.active_clients ?? 0} ativos`}
          tone="cyan"
        />
        <Kpi
          icon={<ShieldCheck size={16} />}
          label="SLA / satisfação"
          value={`${state?.sla_compliance_pct ?? 0}%`}
          detail={`${state?.customer_satisfaction ?? 0}/100 satisfação`}
          tone="green"
        />
        <Kpi
          icon={<Activity size={16} />}
          label="P95 / erros"
          value={`${state?.latency_p95_ms ?? 0} ms`}
          detail={`${state?.error_rate_pct ?? 0}% rejeição/erro`}
          tone={state && state.latency_p95_ms > 250 ? "red" : "orange"}
        />
        <Kpi
          icon={<Gauge size={16} />}
          label="Demanda / capacidade"
          value={`${state?.demand_rps ?? 0} / ${state?.capacity_rps ?? 0} req/s`}
          detail={`${pressure}% pressão · backlog ${state?.backlog ?? 0}`}
          tone={pressure >= 95 ? "red" : pressure >= 75 ? "orange" : "cyan"}
        />
      </section>

      {state?.alerts.map((alert, index) => (
        <div
          className={`management-alert management-alert--${alert.severity}`}
          key={`${alert.message}-${index}`}
        >
          <ArrowUpRight size={15} /> {alert.message}
        </div>
      ))}

      <section className="management-main-grid">
        <div className="panel management-map-card">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">OPERATING FABRIC / OBSERVED NODES</p>
              <h2>Mapa e pressão da rede</h2>
            </div>
            <span className="observed-badge">OBSERVADO + SIMULADO</span>
          </div>
          <MapView
            clients={overview.clients}
            servers={overview.servers}
            traffic={overview.recent_traffic}
            events={overview.recent_events}
            editMode={
              selectedAction?.action_type === "horizontal_scale" &&
              parameters.operation === "add"
                ? "server"
                : null
            }
            tickIntervalSeconds={overview.status.tick_interval_seconds}
            onMapPick={(latitude, longitude) => {
              if (selectedAction?.action_type === "horizontal_scale") {
                setParameters((current) => ({
                  ...current,
                  latitude,
                  longitude,
                }));
              }
            }}
            onNodeSelect={(kind, id) => {
              if (kind === "server") setSelectedNode(id);
            }}
          />
          {selectedNodeData && (
            <div className="node-inspector">
              <div>
                <p className="eyebrow">NODE INSPECTOR</p>
                <strong>
                  {selectedNodeData.server_id} · {selectedNodeData.city}
                </strong>
              </div>
              <span>
                <small>tier</small>
                <b>
                  {state?.nodes[selectedNodeData.server_id]?.tier ??
                    selectedNodeData.capacity_tier ??
                    "basic"}
                </b>
              </span>
              <span>
                <small>capacidade</small>
                <b>{selectedNodeData.capacity_rps ?? 0} req/s</b>
              </span>
              <span>
                <small>fila</small>
                <b>{selectedNodeData.queue_depth ?? 0}</b>
              </span>
              <span>
                <small>saúde</small>
                <b>
                  {selectedNodeData.health_status ?? selectedNodeData.status}
                </b>
              </span>
            </div>
          )}
        </div>
        <div className="panel management-decisions">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">DECISION CONSOLE / SIX ACTION TYPES</p>
              <h2>Decisões econômicas</h2>
            </div>
            <GitBranch size={18} className="accent" />
          </div>
          {groupedActions.map(({ group, items }) => (
            <div className="action-group" key={group}>
              <span className="action-group__label">{group}</span>
              {items.map((action) => (
                <button
                  className={`action-card ${selectedAction?.action_type === action.action_type ? "action-card-active" : ""}`}
                  key={action.action_type}
                  onClick={() => {
                    setSelectedAction(action);
                    setParameters((current) => ({
                      ...current,
                      ...(action.action_type === "horizontal_scale"
                        ? { operation: "add" }
                        : {}),
                    }));
                  }}
                >
                  <span>
                    <strong>{action.label}</strong>
                    <small>{action.description}</small>
                  </span>
                  <b>
                    {action.investment_usd
                      ? formatUsd(action.investment_usd)
                      : "sem investimento"}
                  </b>
                </button>
              ))}
            </div>
          ))}
          {selectedAction && (
            <ActionForm
              action={selectedAction}
              parameters={parameters}
              setParameters={setParameters}
              onCancel={() => setSelectedAction(null)}
              onConfirm={() => void confirmAction()}
              busy={busy}
              state={state}
            />
          )}
        </div>
      </section>

      <section className="management-bottom-grid">
        <ChartPanel
          title="Saldo e lucro diário"
          icon={<Banknote size={16} />}
          data={chartData}
          dataKeys={["profit"]}
          colors={["#9eff6c"]}
          formatter={(value) => formatUsd(value)}
        />
        <ChartPanel
          title="Demanda versus capacidade"
          icon={<Gauge size={16} />}
          data={chartData}
          dataKeys={["demand", "capacity"]}
          colors={["#ffb86b", "#45d9ff"]}
          formatter={(value) => `${value} req/s`}
        />
        <ChartPanel
          title="P95 e SLA"
          icon={<BarChart3 size={16} />}
          data={chartData}
          dataKeys={["p95"]}
          colors={["#ff6177"]}
          formatter={(value) => `${value} ms`}
        />
      </section>

      <section className="panel management-timeline">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">CAUSAL TIMELINE</p>
            <h2>Intervenções e consequências</h2>
          </div>
          <Activity size={17} className="accent" />
        </div>
        <div className="management-event-list">
          {(state?.events ?? [])
            .slice(-8)
            .reverse()
            .map((event, index) => (
              <div
                className="management-event"
                key={`${String(event.event_id)}-${index}`}
              >
                <span className="status-dot status-live" />
                <div>
                  <strong>{String(event.type)}</strong>
                  <small>
                    dia {String(event.day ?? 0)} ·{" "}
                    {String(
                      event.action_type ?? event.scenario_id ?? "telemetria",
                    )}
                  </small>
                </div>
                <code>
                  {event.investment_usd
                    ? formatUsd(Number(event.investment_usd))
                    : "observação"}
                </code>
              </div>
            ))}
          {!state?.events.length && (
            <p className="empty-state">
              Inicie um cenário para construir a linha do tempo.
            </p>
          )}
        </div>
      </section>
    </main>
  );
}

function ActionForm({
  action,
  parameters,
  setParameters,
  onCancel,
  onConfirm,
  busy,
  state,
}: {
  action: ManagementActionDefinition;
  parameters: Record<string, unknown>;
  setParameters: (value: Record<string, unknown>) => void;
  onCancel: () => void;
  onConfirm: () => void;
  busy: boolean;
  state: ManagementState | null;
}) {
  const set = (name: string, value: unknown) =>
    setParameters({ ...parameters, [name]: value });
  return (
    <div className="action-form">
      <div className="action-form__heading">
        <div>
          <strong>Prévia: {action.label}</strong>
          <small>
            Lead time: {action.lead_days} dia(s) · cooldown:{" "}
            {action.cooldown_days} dia(s)
          </small>
        </div>
        <button onClick={onCancel} aria-label="Fechar prévia">
          ×
        </button>
      </div>
      <div className="action-form__fields">
        {action.action_type === "horizontal_scale" && (
          <>
            <label>
              Operação
              <select
                value={String(parameters.operation)}
                onChange={(event) => set("operation", event.target.value)}
              >
                <option value="add">Adicionar nó</option>
                <option value="remove">Retirar nó</option>
              </select>
            </label>
            {parameters.operation === "remove" ? (
              <label>
                Nó
                <select
                  value={String(parameters.server_id ?? "")}
                  onChange={(event) => set("server_id", event.target.value)}
                >
                  {Object.keys(state?.nodes ?? {}).map((id) => (
                    <option key={id}>{id}</option>
                  ))}
                </select>
              </label>
            ) : (
              <>
                <label>
                  Latitude
                  <input
                    type="number"
                    value={Number(parameters.latitude)}
                    onChange={(event) =>
                      set("latitude", Number(event.target.value))
                    }
                  />
                </label>
                <label>
                  Longitude
                  <input
                    type="number"
                    value={Number(parameters.longitude)}
                    onChange={(event) =>
                      set("longitude", Number(event.target.value))
                    }
                  />
                </label>
              </>
            )}
          </>
        )}
        {action.action_type === "vertical_scale" && (
          <>
            <label>
              Nó
              <select
                value={String(
                  parameters.server_id ??
                    Object.keys(state?.nodes ?? {})[0] ??
                    "",
                )}
                onChange={(event) => set("server_id", event.target.value)}
              >
                {Object.keys(state?.nodes ?? {}).map((id) => (
                  <option key={id}>{id}</option>
                ))}
              </select>
            </label>
            <label>
              Novo tier
              <select
                value={String(parameters.tier)}
                onChange={(event) => set("tier", event.target.value)}
              >
                {["standard", "pro", "enterprise"].map((tier) => (
                  <option key={tier}>{tier}</option>
                ))}
              </select>
            </label>
          </>
        )}
        {action.action_type === "price_adjustment" && (
          <label>
            Preço mensal (USD)
            <input
              type="number"
              min="1"
              max="200"
              value={Number(parameters.monthly_price_usd)}
              onChange={(event) =>
                set("monthly_price_usd", Number(event.target.value))
              }
            />
          </label>
        )}
        {action.action_type === "cache_upgrade" && (
          <>
            <label>
              Nó
              <select
                value={String(
                  parameters.server_id ??
                    Object.keys(state?.nodes ?? {})[0] ??
                    "",
                )}
                onChange={(event) => set("server_id", event.target.value)}
              >
                {Object.keys(state?.nodes ?? {}).map((id) => (
                  <option key={id}>{id}</option>
                ))}
              </select>
            </label>
            <label>
              Nível
              <select
                value={String(parameters.level)}
                onChange={(event) => set("level", Number(event.target.value))}
              >
                {[1, 2, 3].map((level) => (
                  <option key={level}>{level}</option>
                ))}
              </select>
            </label>
          </>
        )}
        {action.action_type === "load_balancing" && (
          <label>
            Política
            <select
              value={String(parameters.policy)}
              onChange={(event) => set("policy", event.target.value)}
            >
              <option value="nearest-healthy">nearest-healthy</option>
              <option value="least-utilized">least-utilized</option>
              <option value="hybrid-latency-capacity">
                hybrid-latency-capacity
              </option>
            </select>
          </label>
        )}
        {action.action_type === "metadata_upgrade" && (
          <label>
            Tier de metadados
            <select
              value={String(parameters.tier)}
              onChange={(event) => set("tier", event.target.value)}
            >
              <option value="linear">linear</option>
              <option value="indexed">indexed</option>
              <option value="read-replica">read-replica simulado</option>
            </select>
          </label>
        )}
      </div>
      <div className="action-form__impact">
        <span>
          Investimento inicial <b>{formatUsd(action.investment_usd)}</b>
        </span>
        <span>
          Recorrente base <b>{formatUsd(action.recurring_monthly_usd)}/mês</b>
        </span>
        <p>
          {action.effects.join(" · ")} · trade-off:{" "}
          {action.tradeoffs.join(" · ")}
        </p>
      </div>
      <button
        className="button button-primary"
        disabled={busy}
        onClick={onConfirm}
      >
        Confirmar decisão
      </button>
    </div>
  );
}

function Kpi({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: "cyan" | "orange" | "green" | "red";
}) {
  return (
    <article className={`management-kpi management-kpi--${tone}`}>
      <span>{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <em>{detail}</em>
      </div>
    </article>
  );
}

function ChartPanel({
  title,
  icon,
  data,
  dataKeys,
  colors,
  formatter,
}: {
  title: string;
  icon: React.ReactNode;
  data: Array<Record<string, number | string>>;
  dataKeys: string[];
  colors: string[];
  formatter: (value: number) => string;
}) {
  return (
    <div className="panel management-chart">
      <div className="panel-heading">
        <h2>
          {icon} {title}
        </h2>
        <span>{data.length ? "últimos dias" : "sem dados"}</span>
      </div>
      <div className="management-chart__body">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <CartesianGrid stroke="rgba(165,202,238,.12)" vertical={false} />
            <XAxis dataKey="day" hide />
            <YAxis hide />
            <Tooltip
              formatter={(value) => formatter(Number(value))}
              contentStyle={{
                background: "#0b1727",
                border: "1px solid rgba(165,202,238,.2)",
                fontSize: 10,
              }}
            />
            <Area
              type="monotone"
              dataKey={dataKeys[0]}
              stroke={colors[0]}
              fill={colors[0]}
              fillOpacity={0.08}
              strokeWidth={2}
            />
            {dataKeys[1] && (
              <Area
                type="monotone"
                dataKey={dataKeys[1]}
                stroke={colors[1]}
                fill={colors[1]}
                fillOpacity={0.04}
                strokeWidth={2}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function formatUsd(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}
