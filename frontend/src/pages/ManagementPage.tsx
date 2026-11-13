import {
  Activity,
  ArrowUpRight,
  Banknote,
  BarChart3,
  Gauge,
  GitBranch,
  Power,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  const [management, setManagement] = useState<ManagementState | null>(overview.management ?? null);
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
  const [selectedEntity, setSelectedEntity] = useState<{ kind: "server" | "client"; id: string } | null>(null);
  const navigate = useNavigate();

  async function loadManagement() {
    try {
      const [actionResponse, scenarioResponse] = await Promise.all([
        api.managementActions(),
        api.managementScenarios(),
      ]);
      setManagement(overview.management ?? null);
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
  }, []);

  useEffect(() => {
    if (overview.management) setManagement(overview.management);
  }, [overview.management]);

  const history = management?.history ?? [];
  const selectedNodeData = selectedEntity?.kind === "server"
    ? overview.servers.find((server) => server.server_id === selectedEntity.id)
    : selectedEntity === null
      ? overview.servers[0]
      : undefined;
  const selectedClientData = selectedEntity?.kind === "client"
    ? overview.clients.find((client) => client.client_id === selectedEntity.id)
    : undefined;
  const selectedClientHistory = selectedClientData?.watch_history ?? [];
  const latestClientWatch = selectedClientHistory[selectedClientHistory.length - 1];
  const selectedClientTraffic = selectedClientData
    ? [...overview.recent_traffic].reverse().find((entry) => entry.client_id === selectedClientData.client_id)
    : undefined;
  const selectedClientServerId = latestClientWatch?.server_id ?? selectedClientTraffic?.server_id ?? null;
  const selectedClientServer = selectedClientServerId
    ? overview.servers.find((server) => server.server_id === selectedClientServerId)
    : undefined;
  const nodeLogs = selectedNodeData
    ? [
        ...overview.recent_traffic
          .filter((entry) => entry.server_id === selectedNodeData.server_id)
          .map((entry) => ({
            at: entry.at,
            label: "entrega",
            detail: `${entry.client_id} · ${Math.round(entry.end_to_end_ms ?? entry.latency_ms)} ms`,
          })),
        ...overview.recent_events
          .filter((event) =>
            event.server_id === selectedNodeData.server_id ||
            event.from_server === selectedNodeData.server_id ||
            event.to_server === selectedNodeData.server_id,
          )
          .map((event) => ({
            at: event.at,
            label: event.type,
            detail: event.message_type ?? event.routing_reason ?? event.status ?? "telemetria",
          })),
      ].sort((a, b) => b.at - a.at).slice(0, 8)
    : [];
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

  async function endSimulation() {
    if (!overview.status.initialized || overview.status.lifecycle === "ended") return;
    if (!window.confirm("Encerrar a simulação e arquivar este ciclo de gamificação?")) return;
    setBusy(true);
    try {
      const result = await api.end();
      await onRefresh();
      navigate(`/dashboard?simulation_id=${encodeURIComponent(result.simulation_id)}`);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Falha ao encerrar a simulação");
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
  const selectedScenario = scenarios.find(
    (scenario) => String(scenario.scenario_id) === scenarioId,
  );
  const scenarioInitial = (selectedScenario?.initial ?? {}) as Record<string, unknown>;
  const scenarioPreviewActive = Boolean(
    state && selectedScenario && state.scenario_id !== scenarioId,
  );
  const initialCash = scenarioPreviewActive
    ? Number(scenarioInitial.cash_usd ?? state?.initial_cash_balance_usd ?? 0)
    : state?.initial_cash_balance_usd ?? 0;
  const initialClients = scenarioPreviewActive
    ? Number(scenarioInitial.clients ?? state?.base_paying_clients ?? 0)
    : state?.base_paying_clients ?? 0;
  const initialPrice = scenarioPreviewActive
    ? Number(scenarioInitial.monthly_price_usd ?? state?.monthly_price_per_client_usd ?? 0)
    : state?.monthly_price_per_client_usd ?? 0;
  const showInitialConditions = !overview.status.initialized || overview.status.lifecycle === "ended";
  const satisfaction = state?.customer_satisfaction ?? 0;
  const satisfactionTips = [
    ...(state && state.latency_p95_ms > 180
      ? ["Reduza o P95: adicione capacidade, aumente o tier ou use balanceamento híbrido antes de subir o preço."]
      : []),
    ...(state && state.error_rate_pct > 0.5
      ? ["Ataque rejeições e fila: escala horizontal ou vertical diminui erros que derrubam satisfação."]
      : []),
    ...(state && state.monthly_price_per_client_usd > 25
      ? ["O preço acima da referência reduz satisfação e aumenta churn; compense-o com SLA melhor ou revise o preço."]
      : []),
    ...(state && state.utilization >= 0.75
      ? ["A pressão está alta: cache e capacidade reduzem tempo de espera antes que clientes saiam."]
      : []),
  ];
  if (!satisfactionTips.length) satisfactionTips.push("A satisfação está estável. Preserve o SLA e evite elevar preço ou carga sem capacidade correspondente.");

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
          <button
            className="button button-danger"
            disabled={busy || !overview.status.initialized || overview.status.lifecycle === "ended"}
            onClick={() => void endSimulation()}
          >
            <Power size={14} /> Encerrar simulação
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

      {showInitialConditions && <section className="panel management-initial-state">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">INITIAL CONDITIONS / DIDACTIC WORLD</p>
            <h2>Como o modo começa</h2>
          </div>
          <span className="observed-badge">
            {scenarioPreviewActive ? "prévia do cenário selecionado" : "parâmetros fixados no reset"}
          </span>
        </div>
        <div className="management-initial-grid">
          <InitialValue label="Caixa inicial" value={formatUsd(initialCash)} />
          <InitialValue label="Clientes pagantes" value={String(initialClients)} />
          <InitialValue label="Preço mensal" value={formatUsd(initialPrice)} />
          <InitialValue label="Custo fixo mensal" value={formatUsd(state?.fixed_monthly_cost_usd ?? 0)} />
          <InitialValue label="Nós iniciais" value={String(Object.keys(state?.nodes ?? {}).length)} />
          <InitialValue label="Moeda" value="USD" />
        </div>
        <p className="management-inline-note">
          A população do jogo evolui por satisfação, reputação, preço, capacidade e cenário; ela é separada dos clientes físicos observados pela orquestração.
        </p>
      </section>}

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
          detail={`${state?.arrivals_today ?? 0} chegaram · ${state?.departures_today ?? 0} saíram`}
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
          detail={`${pressure}% pressão · alvo ${state?.client_population_target ?? 0} clientes`}
          tone={pressure >= 95 ? "red" : pressure >= 75 ? "orange" : "cyan"}
        />
      </section>

      <section className={`management-satisfaction management-satisfaction--${satisfaction >= 75 ? "good" : satisfaction >= 55 ? "watch" : "risk"}`} aria-label="Satisfação dos clientes">
        <div>
          <p className="eyebrow">PRIMARY PLAYER METRIC</p>
          <h2>Satisfação do cliente: {satisfaction.toFixed(0)}/100</h2>
          <p>Ela determina reputação, chegada de pagantes e churn. É calculada por latência P95, erros, preço e feedback real das entregas.</p>
        </div>
        <div className="management-satisfaction__signals">
          <span><small>feedback</small><b>{state?.feedback_score ?? 0}/100</b></span>
          <span><small>P95</small><b>{state?.latency_p95_ms ?? 0} ms</b></span>
          <span><small>erros</small><b>{state?.error_rate_pct ?? 0}%</b></span>
        </div>
        <ul>{satisfactionTips.map((tip) => <li key={tip}>{tip}</li>)}</ul>
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
              setSelectedEntity({ kind, id });
            }}
            highlightedClientId={selectedClientData?.client_id ?? null}
            highlightedServerId={selectedClientServerId}
          />
          {selectedNodeData && (
            <div className="node-inspector node-inspector--expanded">
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
              <div className="node-inspector__logs">
                <div className="node-inspector__logs-heading">
                  <small>últimos logs do node</small>
                  <span>{selectedNodeData.requests_total ?? 0} req · {selectedNodeData.errors_total ?? 0} erros</span>
                </div>
                {nodeLogs.length ? nodeLogs.map((log, index) => (
                  <div className="node-inspector__log" key={`${log.at}-${index}`}>
                    <time>{formatTime(log.at)}</time>
                    <b>{log.label}</b>
                    <span>{log.detail}</span>
                  </div>
                )) : <small className="node-inspector__empty">sem eventos recentes para este node</small>}
              </div>
            </div>
          )}
          {selectedClientData && (
            <ClientInspector
              client={selectedClientData}
              servingServerId={selectedClientServerId}
              servingServerCity={selectedClientServer?.city}
            />
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

      <details className="management-analytics">
        <summary>Histórico e análises</summary>
        <div className="management-bottom-grid">
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
        </div>

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
      </details>
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
  const selectedNode = state?.nodes[String(parameters.server_id)];
  const previewInvestment =
    action.action_type === "horizontal_scale" && parameters.operation === "remove"
      ? 0
      : action.action_type === "vertical_scale"
        ? action.investment_by_tier?.[String(parameters.tier)] ?? action.investment_usd
      : action.action_type === "cache_upgrade"
        ? action.investment_usd * Number(parameters.level ?? 1)
        : action.investment_usd;
  const previewRecurring =
    action.action_type === "horizontal_scale" && parameters.operation === "remove"
      ? -(selectedNode?.monthly_cost_usd ?? 0)
      : action.action_type === "cache_upgrade"
        ? action.recurring_monthly_usd * Number(parameters.level ?? 1)
        : action.recurring_monthly_usd;
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
          Investimento inicial <b>{formatUsd(previewInvestment)}</b>
        </span>
        <span>
          Impacto recorrente <b>{formatUsd(previewRecurring)}/mês</b>
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

function InitialValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="management-initial-value">
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
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

function formatTime(value: number) {
  return new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(value * 1000);
}

function ClientInspector({
  client,
  servingServerId,
  servingServerCity,
}: {
  client: Overview["clients"][number];
  servingServerId: string | null;
  servingServerCity?: string;
}) {
  const history = [...(client.watch_history ?? [])].reverse().slice(0, 6);
  const latest = history[0];
  return (
    <div className="node-inspector node-inspector--client">
      <div>
        <p className="eyebrow">CLIENT INSPECTOR</p>
        <strong>{client.client_id} · {client.city}</strong>
        <small>
          {client.online ? "online" : "offline"} · {client.likes ?? 0} likes · {client.dislikes ?? 0} dislikes
        </small>
      </div>
      <span>
        <small>ultima entrega</small>
        <b>{latest ? `${Math.round(latest.latency_ms)} ms` : "—"}</b>
      </span>
      <span>
        <small>videos assistidos</small>
        <b>{client.videos_consumed}</b>
      </span>
      <span>
        <small>feedback medio</small>
        <b>{client.feedback_score ? `${client.feedback_score}/100` : "sem nota"}</b>
      </span>
      <span>
        <small>latência média do feedback</small>
        <b>{client.feedback_latency_avg_ms ? `${Math.round(client.feedback_latency_avg_ms)} ms` : "sem dados"}</b>
      </span>
      <span>
        <small>servidor atual</small>
        <b>{servingServerId ? `${servingServerId}${servingServerCity ? ` · ${servingServerCity}` : ""}` : "sem entrega"}</b>
      </span>
      <div className="client-inspector__feedback">
        <small>
          Feedback gerado automaticamente pelo processo cliente a partir da latência observada.
        </small>
      </div>
      <div className="client-inspector__history">
        <small>historico recente de videos</small>
        {history.length ? history.map((item) => (
          <div key={`${item.chunk_id}-${item.at}`}>
            <span>{item.video_id} · chunk {item.chunk_number} · {item.liked === true ? "like" : item.liked === false ? "feedback" : "sem avaliação"}</span>
            <b>{Math.round(item.latency_ms)} ms · {formatTime(item.at)}</b>
          </div>
        )) : <em>nenhum video assistido nesta sessao</em>}
      </div>
    </div>
  );
}

