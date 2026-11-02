import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Overview } from "../types";

const demoOverview: Overview = {
  status: {
    initialized: false,
    paused: false,
    started_at: null,
    updated_at: null,
    configuration: { num_servers: 0, num_clients: 0, malicious_probability: 0.25, latency_factor: 1, base_node_port: 5101, video_id: "bigbuckbunny" },
    servers_total: 0,
    clients_total: 0,
    malicious_clients: 0,
    blacklisted_total: 0,
    scalability: { online_clients: 0, healthy_servers: 0, capacity_per_server: 8, total_capacity: 0, utilization: 0, profile: "indisponível", message: "Backend aguardando", estimated_cost_units: 0, estimated_queue_latency_ms: 12 },
  },
  servers: [],
  clients: [],
  blacklist: [],
  recent_events: [],
  recent_traffic: [],
};

export function useDashboardData() {
  const [overview, setOverview] = useState<Overview>(demoOverview);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.overview();
      setOverview(data);
      setConnected(true);
      setError(null);
    } catch (cause) {
      setConnected(false);
      setError(cause instanceof Error ? cause.message : "Backend indisponível");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return { overview, connected, loading, error, refresh, setOverview };
}

