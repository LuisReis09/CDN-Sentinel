export type ServerStatus =
  | "healthy"
  | "degraded"
  | "overloaded"
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
  process_mode?: "http" | "virtual";
  role?: "origin" | "regional" | "edge" | string;
  region?: string;
  peer_ids?: string[];
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
  watch_history?: Array<{
    at: number;
    video_id: string;
    chunk_number: number;
    chunk_id: string;
    server_id: string;
    latency_ms: number;
    network_latency_ms?: number;
    queue_wait_ms?: number;
    liked?: boolean | null;
  }>;
  feedback_history?: Array<{
    at: number;
    video_id: string;
    chunk_number?: number | null;
    liked: boolean;
    rating: number;
    comment?: string;
    latency_ms: number;
    latency_related: boolean;
  }>;
  likes?: number;
  dislikes?: number;
  feedback_score?: number;
  feedback_latency_avg_ms?: number;
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
  route_kind?: "delivery" | "failover" | string;
  request_count?: number;
  virtual?: boolean;
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
    | "failover"
    | "capacity"
    | "health"
    | string;
  emission_probability?: number;
  from_server?: string;
  to_server?: string;
  status?: string;
  encryption?: string;
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
  initialization?: {
    in_progress: boolean;
    progress_pct: number;
    phase: string;
    detail: string;
  };
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
  management?: ManagementState | null;
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
  clients_total?: number;
  clients_truncated?: boolean;
  blacklist: BlacklistEntry[];
  leaks: LeakRecord[];
  events: SimulationEvent[];
  traffic: Traffic[];
  metrics_history?: TelemetrySample[];
  scan_history: Array<Record<string, unknown>>;
}

export interface LeakRecord {
  leak_id: string;
  client_id?: string;
  server_id: string;
  origin_server_id?: string;
  platform: string;
  platform_id?: string;
  platform_kind?: string;
  external_url?: string;
  created_at: number;
  processed: boolean;
  analyzed?: boolean;
  attributed?: boolean;
  needs_reanalysis?: boolean;
  analysis_count?: number;
  next_analysis_at?: number;
  review_status?: string;
  detected_at?: number;
  detected_by_server_id?: string;
  error?: string;
  trace_id?: string;
  request_id?: string;
  forensic_status?: string;
  investigation_id?: string;
}

export interface VideoChunk {
  chunk_id: string;
  content_type: string;
  payload: string;
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

export interface ForensicInvestigation {
  investigation_id: string;
  media_sha256: string;
  forensic_status: string;
  decision: "NOT_FOUND" | "INCONCLUSIVE" | "CANDIDATE" | "PENDING_REVIEW" | "REVIEWED" | "ERROR";
  attribution: "AUTHENTICATED_SESSION" | "NONE";
  content_id?: string | null;
  session_id?: string | null;
  watermark_id?: string | null;
  claim?: Record<string, unknown> | null;
  content_match?: { status: string; matched_frames?: number; fraction?: number } | null;
  evidence: Record<string, unknown>;
  administrative_action: string;
  blacklist_changed: boolean;
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
    fps?: number;
    source: string;
    visual_transform: string;
  };
  chunk_number: number;
  original_payload_base64: string;
  watermarked_payload_base64: string;
  payload_is_preview?: boolean;
  watermark_token: string;
  noise_hex: string;
  noise_source: string;
  cryptographic_process: {
    algorithm: string;
    key_material: string;
    encryption_parameters?: string;
    key_derivation?: string;
    signed_payload: string;
    token_format: string;
    embedding: string;
    transport_encoding: string;
    verification: string;
    reversible_encryption: boolean;
    robust_channel: string;
    visual_parameters?: string;
    robustness_limit: string;
  };
  extracted_token: string;
  claim: Record<string, unknown>;
  round_trip_verified: boolean;
  verification?: {
    transport_token: string;
    visual_embedded: boolean;
    visual_detection?: string;
    visual_authentication?: string;
    forensic_status: string;
  };
  visual_detection?: {
    status?: string;
    confidence?: number;
    frame_support?: number;
    frames_sampled?: number;
    authentication?: string;
    reason?: string;
  };
  payload_sha256: string;
  generated_at: number;
  key_fingerprint: string;
  claim_before_encoding: Record<string, unknown>;
  encoded_claim: string;
  signature: string;
  payload_prefix: string;
  decryption_process: {
    version?: string;
    algorithm: string;
    encrypted: boolean;
    aad?: string;
    nonce_base64url?: string;
    ciphertext_base64url?: string;
    authentication_tag_base64url?: string;
    steps: string[];
    decrypted_payload: Record<string, unknown>;
  };
  robustness_checks: Array<{
    filter: string;
    filter_id: string;
    intensity?: string;
    sample_generated?: boolean;
    sample_method?: string;
    marker: string;
    recovered_marker: string;
    confidence: number;
    bits_correct?: number;
    bits_total?: number;
    confidence_method?: string;
    survives: boolean;
  }>;
}

export interface WatermarkDetection {
  status: "VALID" | "NOT_FOUND" | "INCONCLUSIVE" | "INVALID";
  marker?: string | null;
  confidence?: number;
  sync_confidence?: number;
  repetition_consistency?: number;
  frame_support?: number;
  frames_sampled?: number;
  reason?: string;
  error?: string;
  claim?: Record<string, unknown>;
  client_id?: string;
  server_id?: string;
  content_id?: string;
  visual_hamming_distance?: number;
  verification?: string;
}

export interface ManagementActionDefinition {
  action_type: string;
  label: string;
  group: string;
  description: string;
  investment_usd: number;
  recurring_monthly_usd: number;
  lead_days: number;
  cooldown_days: number;
  parameters: Array<Record<string, unknown>>;
  effects: string[];
  tradeoffs: string[];
  investment_by_tier?: Record<string, number>;
}

export interface ManagementActionRecord {
  action_id: string;
  action_type: string;
  parameters: Record<string, unknown>;
  status: "pending" | "applied" | "failed";
  submitted_day: number;
  apply_day: number;
  investment_usd: number;
  recurring_delta_usd: number;
  rationale: string;
  result?: Record<string, unknown>;
  error?: string | null;
}

export interface ManagementState {
  simulation_id: string;
  scenario_id: string;
  seed: number;
  day: number;
  paused: boolean;
  version: number;
  initial_cash_balance_usd: number;
  cash_balance_usd: number;
  monthly_price_per_client_usd: number;
  fixed_monthly_cost_usd: number;
  base_paying_clients: number;
  paying_clients: number;
  client_population_target: number;
  arrivals_today: number;
  departures_today: number;
  arrivals_total: number;
  departures_total: number;
  active_clients: number;
  churned_clients: number;
  reputation: number;
  customer_satisfaction: number;
  demand_rps: number;
  served_rps: number;
  capacity_rps: number;
  utilization: number;
  backlog: number;
  requests_rejected: number;
  latency_p95_ms: number;
  availability_pct: number;
  error_rate_pct: number;
  sla_compliance_pct: number;
  daily_revenue_usd: number;
  daily_opex_usd: number;
  daily_profit_usd: number;
  monthly_margin_pct: number;
  objective: Record<string, unknown>;
  nodes: Record<
    string,
    {
      server_id: string;
      tier: string;
      lifecycle_status: string;
      health_status: string;
      cache_level: number;
      cache_hit_rate: number;
      monthly_cost_usd: number;
      metadata_indexed: boolean;
    }
  >;
  pending_actions: ManagementActionRecord[];
  history: Array<Record<string, number | boolean | string>>;
  alerts: Array<{ severity: string; message: string }>;
  events: Array<Record<string, unknown>>;
  load_balancing_policy: string;
  metadata_tier: string;
  metadata_query_rps: number;
  metadata_lookup_ms: number;
  metadata_staleness_ms: number;
  feedback_score: number;
  feedback_count: number;
  feedback_latency_avg_ms: number;
}

export interface ForensicStudio {
  pipeline: "CDNWM4";
  algorithm: "qim3";
  algorithm_id: string;
  fingerprint_scheme: string;
  video_label: string;
  claim: Record<string, string | number>;
  issued_marker: string;
  visual_detection: {
    status: string;
    marker?: string;
    confidence?: number;
    ecc_status?: string;
    ecc_corrected_bits?: number;
    frames_sampled?: number;
    forensic_status?: string;
  };
  ledger_status: string;
  investigation: {
    decision: string;
    attribution: string;
    content_match?: { status: string; matched_frames?: number };
    administrative_action: string;
  };
  quality_vs_control: {
    psnr_db: number;
    ssim_windowed: number;
    ms_ssim_3scale_approx: number;
    region_mean_abs_luma_max: number;
  };
  robustness_checks: Array<{ filter: string; filter_id: string; status: string; survives: boolean; bits_correct: number; bits_total: number }>;
  forensic_envelope: {
    format: string;
    token: string;
    version: string;
    key_id: string;
    algorithm: string;
    algorithm_key: string;
    nonce_base64url: string;
    ciphertext_and_tag_base64url: string;
    hmac_sha256: string;
    metadata: Record<string, string | number>;
    claim_before_encryption: Record<string, string | number>;
    claim_after_decryption: Record<string, string | number>;
  };
  media_payloads: {
    original: { sha256: string; size_bytes: number; prefix_base64: string };
    watermarked: { sha256: string; size_bytes: number; prefix_base64: string };
    note: string;
  };
  video_variants: Record<"original" | "control" | "watermarked" | "residual" | "difference" | "detection_map", string>;
  video_alignment: { aligned: boolean; probes: Record<string, { duration_seconds: number; fps: number }> };
  diagnostics: Record<string, string>;
}
