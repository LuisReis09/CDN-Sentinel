import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Overview } from "../types";

const demoOverview: Overview = {
  status: {
    initialized: false,
    paused: false,
    lifecycle: "idle",
    simulation_id: "",
    started_at: null,
    updated_at: null,
    tick_interval_seconds: 2.5,
    configuration: {
      num_servers: 0,
      num_clients: 0,
      malicious_probability: 0.25,
      latency_factor: 1,
      base_node_port: 5101,
      video_id: "bigbuckbunny",
      tick_interval_seconds: 2.5,
      base_client_port: 6101,
      monthly_client_price_usd: 25,
      monthly_server_cost_usd: 100,
      monthly_fixed_cost_usd: 150,
    },
    servers_total: 0,
    clients_total: 0,
    malicious_clients: 0,
    blacklisted_total: 0,
    scalability: {
      online_clients: 0,
      healthy_servers: 0,
      capacity_per_server: 0,
      total_capacity: 0,
      utilization: 0,
      profile: "indisponível",
      message: "Backend aguardando",
      estimated_monthly_cost_usd: 0,
      estimated_queue_latency_ms: 12,
      average_latency_ms: 0,
      p95_latency_ms: 0,
      cost_model: {
        currency: "USD/mês",
        server_cost_usd: 0,
        fixed_cost_usd: 0,
        variable_cost_usd: 0,
        total_monthly_cost_usd: 0,
        configured_client_price_usd: 25,
        break_even_price_per_client_usd: 0,
        minimum_price_with_margin_per_client_usd: 0,
        projected_revenue_usd: 0,
        projected_margin_usd: 0,
      },
    },
  },
  servers: [],
  clients: [],
  blacklist: [],
  leaks: [],
  recent_events: [],
  recent_traffic: [],
  monitor: {
    automatic: false,
    interval_seconds: 2.5,
    last_scan_at: null,
    last_scanned: 0,
    last_detected: 0,
    last_rejected: 0,
    pending_leaks: 0,
    per_server: {},
  },
};

function normalizeOverview(raw: Partial<Overview>): Overview {
  const status = raw.status ?? demoOverview.status;
  const configuration = {
    ...demoOverview.status.configuration,
    ...(status.configuration ?? {}),
    num_servers: status.configuration?.num_servers ?? 0,
    num_clients: status.configuration?.num_clients ?? 0,
    malicious_probability: status.configuration?.malicious_probability ?? 0.25,
    latency_factor: status.configuration?.latency_factor ?? 1,
    base_node_port: status.configuration?.base_node_port ?? 5101,
    video_id: status.configuration?.video_id ?? "bigbuckbunny",
    tick_interval_seconds: status.configuration?.tick_interval_seconds ?? 2.5,
    base_client_port: status.configuration?.base_client_port ?? 6101,
    monthly_client_price_usd:
      status.configuration?.monthly_client_price_usd ?? 25,
    monthly_server_cost_usd:
      status.configuration?.monthly_server_cost_usd ?? 100,
    monthly_fixed_cost_usd: status.configuration?.monthly_fixed_cost_usd ?? 150,
  };
  const scalability = status.scalability ?? demoOverview.status.scalability;
  const costModel = {
    ...demoOverview.status.scalability.cost_model,
    ...(scalability.cost_model ?? {}),
  };
  return {
    ...demoOverview,
    ...raw,
    status: {
      ...demoOverview.status,
      ...status,
      lifecycle: status.lifecycle ?? (status.initialized ? "running" : "idle"),
      simulation_id: status.simulation_id ?? "",
      tick_interval_seconds: status.tick_interval_seconds ?? 2.5,
      configuration,
      scalability: {
        ...demoOverview.status.scalability,
        ...scalability,
        online_clients: scalability.online_clients ?? 0,
        healthy_servers: scalability.healthy_servers ?? 0,
        utilization: scalability.utilization ?? 0,
        profile: scalability.profile ?? "indisponível",
        message: scalability.message ?? "Backend aguardando",
        cost_model: costModel,
      },
    },
    servers: (raw.servers ?? []).map((server) => ({
      ...server,
      process_id: server.process_id ?? null,
      last_error: server.last_error ?? null,
      messages_received: server.messages_received ?? 0,
    })),
    clients: (raw.clients ?? []).map((client) => ({
      ...client,
      process_id: client.process_id ?? null,
      process_status: client.process_status ?? "unknown",
      last_activity_at: client.last_activity_at ?? null,
    })),
    blacklist: raw.blacklist ?? [],
    leaks: raw.leaks ?? [],
    recent_events: raw.recent_events ?? [],
    recent_traffic: raw.recent_traffic ?? [],
    monitor: {
      ...demoOverview.monitor,
      ...(raw.monitor ?? {}),
      automatic: raw.monitor?.automatic ?? false,
      interval_seconds: raw.monitor?.interval_seconds ?? 2.5,
      last_scanned: raw.monitor?.last_scanned ?? 0,
      last_detected: raw.monitor?.last_detected ?? 0,
      last_rejected: raw.monitor?.last_rejected ?? 0,
      pending_leaks: raw.monitor?.pending_leaks ?? 0,
      per_server: raw.monitor?.per_server ?? {},
    },
  };
}

export function useDashboardData() {
  const [overview, setOverview] = useState<Overview>(demoOverview);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const inFlight = useRef<Promise<void> | null>(null);

  const refresh = useCallback(async () => {
    if (inFlight.current) return inFlight.current;
    const work = (async () => {
      try {
        const data = await api.overview();
        setOverview(normalizeOverview(data));
        setConnected(true);
        setLastSuccessAt(Date.now());
        setError(null);
      } catch (cause) {
        setConnected(false);
        setError(
          cause instanceof Error ? cause.message : "Backend indisponível",
        );
      } finally {
        setLoading(false);
      }
    })();
    inFlight.current = work;
    try {
      await work;
    } finally {
      inFlight.current = null;
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const freshness = connected ? "LIVE" : lastSuccessAt ? "STALE" : "OFFLINE";
  return {
    overview,
    connected,
    loading,
    error,
    freshness,
    lastSuccessAt,
    refresh,
    setOverview,
  };
}
