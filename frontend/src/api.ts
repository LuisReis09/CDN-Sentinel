import type {
  Overview,
  ManagementActionDefinition,
  ManagementState,
  SimulationHistory,
  SimulationStatus,
  VideoChunk,
  WatermarkDemo,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(
  /\/$/,
  "",
);
const CONTROL_TOKEN = import.meta.env.VITE_CONTROL_TOKEN ?? "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(CONTROL_TOKEN ? { "X-CDN-Control-Token": CONTROL_TOKEN } : {}),
        ...(options?.headers ?? {}),
      },
      ...options,
    });
  } catch {
    throw new Error(
      "Não foi possível conectar ao backend. Inicie o Flask com `python app.py` na porta 5000.",
    );
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.error ?? body.message ?? body.detail;
    const fieldDetails = body.errors && typeof body.errors === "object"
      ? ` ${Object.entries(body.errors as Record<string, unknown>).map(([field, value]) => `${field}: ${String(value)}`).join("; ")}`
      : "";
    const hint = body.hint ? ` ${body.hint}` : "";
    const prefix = response.status === 400 ? "Parâmetros inválidos." : `HTTP ${response.status}.`;
    throw new Error(`${prefix} ${detail ?? "A operação não foi aceita."}${fieldDetails}${hint}`.trim());
  }
  return body as T;
}

export const api = {
  overview: () => request<Overview>("/observability/overview"),
  status: () => request<SimulationStatus>("/control/simulation/status"),
  initialize: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>("/control/simulation/init", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateConfig: (payload: Record<string, unknown>) =>
    request<SimulationStatus>("/control/simulation/config", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  pause: () =>
    request<SimulationStatus>("/control/simulation/pause", { method: "POST" }),
  resume: () =>
    request<SimulationStatus>("/control/simulation/resume", { method: "POST" }),
  end: () =>
    request<{
      simulation_id: string;
      lifecycle: string;
      ended_at?: number;
      history: SimulationHistory;
    }>("/control/simulation/end", { method: "POST" }),
  history: (simulationId?: string) =>
    request<{ histories: SimulationHistory[] }>(
      `/observability/history${simulationId ? `?simulation_id=${encodeURIComponent(simulationId)}` : ""}`,
    ),
  scan: () =>
    request<{
      detected: unknown[];
      rejected: unknown[];
      blacklisted_total: number;
    }>("/monitor/scan", { method: "POST" }),
  stream: (clientId: string, chunk = 0) =>
    request<VideoChunk>(`/clients/${clientId}/stream?chunk=${chunk}`),
  createClient: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>("/clients", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createServer: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>("/topology/servers", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  injectFault: (serverId: string, fault: Record<string, unknown>) =>
    request<Record<string, unknown>>(
      `/control/fault/${encodeURIComponent(serverId)}`,
      { method: "POST", body: JSON.stringify(fault) },
    ),
  resetMetrics: () =>
    request<Record<string, unknown>>("/control/metrics/reset", {
      method: "POST",
    }),
  verifyWatermark: (token: string) =>
    request<{
      valid: boolean;
      claim?: Record<string, unknown>;
      error?: string;
    }>("/security/watermark/verify", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  watermarkDemo: (payload: Record<string, unknown> = {}) =>
    request<WatermarkDemo>("/security/watermark/demo", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  watermarkVideoUrl: (
    videoId = "cdn_sentinel_demo",
    variant: "original" | "watermarked" | "difference" = "original",
  ) =>
    `${API_BASE}/security/watermark/demo/video?video_id=${encodeURIComponent(videoId)}&variant=${variant}`,
  managementState: () => request<ManagementState>("/management/state"),
  managementActions: () =>
    request<{ actions: ManagementActionDefinition[] }>("/management/actions"),
  managementScenarios: () =>
    request<{ scenarios: Array<Record<string, unknown>> }>(
      "/management/scenarios",
    ),
  startManagementScenario: (scenarioId: string, seed?: number) =>
    request<ManagementState>("/management/scenarios/start", {
      method: "POST",
      body: JSON.stringify({ scenario_id: scenarioId, seed }),
    }),
  applyManagementAction: (payload: Record<string, unknown>) =>
    request<{ action: Record<string, unknown>; state: ManagementState }>(
      "/management/actions",
      { method: "POST", body: JSON.stringify(payload) },
    ),
  resetManagement: () =>
    request<ManagementState>("/management/reset", { method: "POST" }),
};
