import type {
  Overview,
  ManagementActionDefinition,
  ManagementState,
  SimulationHistory,
  SimulationStatus,
  VideoChunk,
  WatermarkDemo,
  WatermarkDetection,
  ForensicInvestigation,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(
  /\/$/,
  "",
);
let csrfToken = "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      credentials: "same-origin",
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(csrfToken && options?.method && options.method !== "GET" ? { "X-CDN-CSRF": csrfToken } : {}),
        ...(options?.headers ?? {}),
      },
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
  authSession: async (): Promise<{ username: string; role: string } | null> => {
    const response = await fetch(`${API_BASE}/auth/session`, { credentials: "same-origin" });
    if (response.status === 404) return null; // Explicit local academic mode.
    if (!response.ok) throw new Error("Sessão de operador necessária.");
    const session = await response.json();
    csrfToken = session.csrf;
    return session;
  },
  login: async (username: string, password: string) => {
    const session = await request<{ username: string; role: string; csrf: string }>("/auth/login", {
      method: "POST", body: JSON.stringify({ username, password }),
    });
    csrfToken = session.csrf;
    return session;
  },
  logout: async () => {
    await request("/auth/logout", { method: "POST" });
    csrfToken = "";
  },
  overview: () => request<Overview>("/observability/overview"),
  realtimeUrl: () => `${API_BASE}/observability/realtime/stream`,
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
  detectWatermark: async (file: File): Promise<WatermarkDetection> => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${API_BASE}/security/watermark/detect`, {
      method: "POST",
      credentials: "same-origin",
      headers: csrfToken ? { "X-CDN-CSRF": csrfToken } : undefined,
      body: form,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok && !body.status) {
      throw new Error(body.error ?? `HTTP ${response.status}.`);
    }
    return body as WatermarkDetection;
  },
  investigateVideo: async (file: File): Promise<ForensicInvestigation> => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${API_BASE}/monitor/investigations`, {
      method: "POST",
      credentials: "same-origin",
      headers: csrfToken ? { "X-CDN-CSRF": csrfToken } : undefined,
      body: form,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}.`);
    return body as ForensicInvestigation;
  },
  reviewInvestigation: (id: string, decision: "ACCEPT" | "REJECT" | "INCONCLUSIVE") =>
    request<Record<string, unknown>>(`/monitor/investigations/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify({ decision }),
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

