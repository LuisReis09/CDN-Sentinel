import type { Overview, SimulationHistory, SimulationStatus, VideoChunk, WatermarkDemo } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");
const CONTROL_TOKEN = import.meta.env.VITE_CONTROL_TOKEN ?? "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(CONTROL_TOKEN ? { "X-CDN-Control-Token": CONTROL_TOKEN } : {}), ...(options?.headers ?? {}) },
      ...options,
    });
  } catch {
    throw new Error("Não foi possível conectar ao backend. Inicie o Flask com `python app.py` na porta 5000.");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}`);
  return body as T;
}

export const api = {
  overview: () => request<Overview>("/observability/overview"),
  status: () => request<SimulationStatus>("/control/simulation/status"),
  initialize: (payload: Record<string, unknown>) => request<Record<string, unknown>>("/control/simulation/init", { method: "POST", body: JSON.stringify(payload) }),
  updateConfig: (payload: Record<string, unknown>) => request<SimulationStatus>("/control/simulation/config", { method: "PATCH", body: JSON.stringify(payload) }),
  pause: () => request<SimulationStatus>("/control/simulation/pause", { method: "POST" }),
  resume: () => request<SimulationStatus>("/control/simulation/resume", { method: "POST" }),
  end: () => request<{ simulation_id: string; lifecycle: string; ended_at?: number; history: SimulationHistory }>("/control/simulation/end", { method: "POST" }),
  history: (simulationId?: string) => request<{ histories: SimulationHistory[] }>(`/observability/history${simulationId ? `?simulation_id=${encodeURIComponent(simulationId)}` : ""}`),
  scan: () => request<{ detected: unknown[]; rejected: unknown[]; blacklisted_total: number }>("/monitor/scan", { method: "POST" }),
  stream: (clientId: string, chunk = 0) => request<VideoChunk>(`/clients/${clientId}/stream?chunk=${chunk}`),
  createClient: (payload: Record<string, unknown>) => request<Record<string, unknown>>("/clients", { method: "POST", body: JSON.stringify(payload) }),
  createServer: (payload: Record<string, unknown>) => request<Record<string, unknown>>("/topology/servers", { method: "POST", body: JSON.stringify(payload) }),
  injectFault: (serverId: string, fault: Record<string, unknown>) => request<Record<string, unknown>>(`/control/fault/${encodeURIComponent(serverId)}`, { method: "POST", body: JSON.stringify(fault) }),
  resetMetrics: () => request<Record<string, unknown>>("/control/metrics/reset", { method: "POST" }),
  verifyWatermark: (token: string) => request<{ valid: boolean; claim?: Record<string, unknown>; error?: string }>("/security/watermark/verify", { method: "POST", body: JSON.stringify({ token }) }),
  watermarkDemo: (payload: Record<string, unknown> = {}) => request<WatermarkDemo>("/security/watermark/demo", { method: "POST", body: JSON.stringify(payload) }),
  watermarkVideoUrl: (videoId = "bigbuckbunny") => `${API_BASE}/security/watermark/demo/video?video_id=${encodeURIComponent(videoId)}`,
};

