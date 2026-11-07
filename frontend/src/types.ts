export type ServerStatus =
  | "healthy"
  | "degraded"
  | "starting"
  | "stopping"
  | "stopped"
  | "offline"
  | "error"
  | "unknown";

export interface ServerNode {
  server_id: string;
  host: string;
  port: number;
  latitude: number;
  longitude: number;
  city: string;
  status: ServerStatus;
  lifecycle_status?: string;
  health_status?: string;
  capacity_tier?: string;
  load: number;
  blacklist_size: number;
  url: string;
  process_id: number | null;
  last_error: string | null;
  messages_received: number;
  uptime_seconds?: number;
  requests_total?: number;
  errors_total?: number;
  requests_in_flight?: number;
  last_request_at?: number | null;
  capacity_rps?: number;
  utilization?: number;
  queue_depth?: number;
  queue_rejected?: number;
  queue_wait_ms?: number;
  capacity_pressure?: number;
  slo_breached?: boolean;
  fault?: { offline?: boolean; extra_latency_ms?: number; drop_rate?: number };
}

export interface Client {
  client_id: string;
  latitude: number;
  longitude: number;
  city: string;
  malicious: boolean;
  active: boolean;
  online: boolean;
  videos_consumed: number;
  last_activity_at: number | null;
  process_id: number | null;
  process_status: string;
}

export interface Traffic {
  at: number;
  client_id: string;
  server_id: string;
  distance_km: number;
  latency_ms: number;
  chunk_id: string;
  request_id?: string;
  trace_id?: string;
  artificial_latency_ms?: number;
  http_rtt_ms?: number;
  queue_wait_ms?: number;
  end_to_end_ms?: number;
  routing_reason?: string;
}

export interface SimulationEvent {
  event_id?: string;
  type: string;
  at: number;
  client_id?: string;
  server_id?: string;
  propagated_to?: string[];
  detected?: number;
  rejected?: number;
  videos_consumed?: number;
  protocol?: string;
  node_protocol?: string;
  routing_algorithm?: string;
  routing?: string;
  routing_reason?: string;
  gossip_protocol?: string;
  watermark_algorithm?: string;
  proof_algorithm?: string;
  source?: string;
  chunk_id?: string;
  tick?: number;
  tick_interval_seconds?: number;
  probability?: number;
  reason?: string;
  monitor_server_id?: string;
  content_id?: string;
  content_title?: string;
  message_id?: string;
  message_type?: string;
  communication_kind?:
    | "blacklist"
    | "new_content"
    | "update"
    | "client_content"
    | string;
  emission_probability?: number;
  from_server?: string;
  to_server?: string;
  status?: string;
  payload_summary?: string;
  ack_server_id?: string;
  error?: string;
  trace_id?: string;
}

export interface BlacklistEntry {
  client_id: string;
  reason: string;
  detected_at: number;
  watermark_issued_at: number;
  server_id: string;
  watermark_server_id: string | null;
  proof_signature: string;
  propagated_to: string[];
}

export interface SimulationStatus {
  initialized: boolean;
  paused: boolean;
  lifecycle: string;
  simulation_id: string;
  ended_at?: number | null;
  end_reason?: string | null;
  started_at: number | null;
  updated_at: number | null;
  tick_interval_seconds: number;
  configuration: {
    num_servers: number;
    num_clients: number;
    malicious_probability: number;
    latency_factor: number;
    base_node_port: number;
    video_id: string;
    tick_interval_seconds: number;
    base_client_port: number;
    monthly_client_price_usd: number;
    monthly_server_cost_usd: number;
    monthly_fixed_cost_usd: number;
    node_tier?: string;
    demand_rps_per_client?: number;
    slo_p95_ms?: number;
    slo_success_rate_pct?: number;
  };
  servers_total: number;
  clients_total: number;
  malicious_clients: number;
  blacklisted_total: number;
  scalability: {
    online_clients: number;
    healthy_servers: number;
    degraded_servers?: number;
    available_servers?: number;
    capacity_per_server: number;
    total_capacity: number;
    capacity_rps?: number;
    demand_rps?: number;
    served_rps?: number;
    utilization: number;
    profile: string;
    message: string;
    estimated_monthly_cost_usd: number;
    estimated_queue_latency_ms: number;
    queue_depth?: number;
    queue_rejected?: number;
    average_latency_ms: number;
    p95_latency_ms: number;
    p50_latency_ms?: number;
    p99_latency_ms?: number;
    metrics_window_seconds?: number;
    observed_request_count?: number;
    observed_rps?: number;
    observed_errors?: number;
    success_rate_pct?: number | null;
    slo_p95_ms?: number;
    slo_success_rate_pct?: number;
    slo_compliant?: boolean;
    metrics_provenance?: string;
    latency_semantics?: string;
    cost_model: {
      currency: string;
      server_cost_usd: number;
      fixed_cost_usd: number;
      variable_cost_usd: number;
      total_monthly_cost_usd: number;
      configured_client_price_usd: number;
      break_even_price_per_client_usd: number;
      minimum_price_with_margin_per_client_usd: number;
      projected_revenue_usd: number;
      projected_margin_usd: number;
    };
  };
}

export interface MonitorStatus {
  automatic: boolean;
  interval_seconds: number;
  last_scan_at: number | null;
  last_scanned: number;
  last_detected: number;
  last_rejected: number;
  pending_leaks: number;
  per_server: Record<string, ServerMonitorStatus>;
}

export interface ServerMonitorStatus {
  server_id: string;
  automatic: boolean;
  interval_seconds: number;
  last_scan_at: number | null;
  last_scanned: number;
  last_detected: number;
  last_rejected: number;
  pending_leaks: number;
}

export interface Overview {
  status: SimulationStatus;
  servers: ServerNode[];
  clients: Client[];
  blacklist: BlacklistEntry[];
  leaks: LeakRecord[];
  recent_events: SimulationEvent[];
  recent_traffic: Traffic[];
  metrics_history: TelemetrySample[];
  monitor: MonitorStatus;
}

export interface TelemetrySample {
  at: number;
  elapsed_seconds: number;
  blacklist_total: number;
  total_requests: number;
  total_errors: number;
  average_latency_ms: number;
  p95_latency_ms: number;
  healthy_servers: number;
  available_servers: number;
  servers_total: number;
  health_score_pct: number;
  server_requests: Record<string, number>;
}

export interface SimulationHistory {
  simulation_id: string;
  lifecycle: string;
  started_at: number | null;
  ended_at: number | null;
  end_reason: string | null;
  configuration: Record<string, unknown>;
  servers: ServerNode[];
  clients: Client[];
  blacklist: BlacklistEntry[];
  leaks: LeakRecord[];
  events: SimulationEvent[];
  traffic: Traffic[];
  metrics_history?: TelemetrySample[];
  scan_history: Array<Record<string, unknown>>;
}

export interface LeakRecord {
  leak_id: string;
  client_id: string;
  server_id: string;
  origin_server_id?: string;
  platform: string;
  platform_id?: string;
  platform_kind?: string;
  external_url?: string;
  created_at: number;
  processed: boolean;
  detected_at?: number;
  detected_by_server_id?: string;
  error?: string;
  trace_id?: string;
  request_id?: string;
}

export interface VideoChunk {
  chunk_id: string;
  content_type: string;
  payload: string;
  watermark_token: string;
  server_id: string;
  client_id: string;
  issued_at: number;
  latency_ms: number;
  request_id?: string;
  trace_id?: string;
  artificial_latency_ms?: number;
  http_rtt_ms?: number;
  end_to_end_ms?: number;
  routing_candidates?: Array<Record<string, unknown>>;
  routing_reason?: string;
}

export interface WatermarkDemo {
  demo: boolean;
  content_type: string;
  video_id: string;
  video_label: string;
  video_source: string;
  video_asset_url: string;
  video_variants: {
    original: string;
    watermarked: string;
    difference: string;
  };
  video_metadata: {
    mime: string;
    resolution: string;
    size_bytes: number;
    source: string;
    visual_transform: string;
  };
  chunk_number: number;
  original_payload_base64: string;
  watermarked_payload_base64: string;
  watermark_token: string;
  noise_hex: string;
  noise_source: string;
  cryptographic_process: {
    algorithm: string;
    key_material: string;
    signed_payload: string;
    token_format: string;
    embedding: string;
    transport_encoding: string;
    verification: string;
    reversible_encryption: boolean;
    robust_channel: string;
    robustness_limit: string;
  };
  extracted_token: string;
  claim: Record<string, unknown>;
  round_trip_verified: boolean;
  payload_sha256: string;
  generated_at: number;
  key_fingerprint: string;
  claim_before_encoding: Record<string, unknown>;
  encoded_claim: string;
  signature: string;
  payload_prefix: string;
  robustness_checks: Array<{
    filter: string;
    filter_id: string;
    marker: string;
    recovered_marker: string;
    confidence: number;
    bits_correct?: number;
    bits_total?: number;
    confidence_method?: string;
    survives: boolean;
  }>;
}
