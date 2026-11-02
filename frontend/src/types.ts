export type ServerStatus = "healthy" | "starting" | "offline";

export interface ServerNode {
  server_id: string;
  host: string;
  port: number;
  latitude: number;
  longitude: number;
  city: string;
  status: ServerStatus;
  load: number;
  blacklist_size: number;
  url: string;
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
}

export interface Traffic {
  at: number;
  client_id: string;
  server_id: string;
  distance_km: number;
  latency_ms: number;
  chunk_id: string;
}

export interface SimulationEvent {
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
  gossip_protocol?: string;
  watermark_algorithm?: string;
  proof_algorithm?: string;
  source?: string;
  chunk_id?: string;
}

export interface BlacklistEntry {
  client_id: string;
  reason: string;
  detected_at: number;
  watermark_issued_at: number;
  server_id: string;
  proof_signature: string;
  propagated_to: string[];
}

export interface SimulationStatus {
  initialized: boolean;
  paused: boolean;
  started_at: number | null;
  updated_at: number | null;
  configuration: {
    num_servers: number;
    num_clients: number;
    malicious_probability: number;
    latency_factor: number;
    base_node_port: number;
    video_id: string;
  };
  servers_total: number;
  clients_total: number;
  malicious_clients: number;
  blacklisted_total: number;
  scalability: {
    online_clients: number;
    healthy_servers: number;
    capacity_per_server: number;
    total_capacity: number;
    utilization: number;
    profile: string;
    message: string;
    estimated_cost_units: number;
    estimated_queue_latency_ms: number;
  };
}

export interface Overview {
  status: SimulationStatus;
  servers: ServerNode[];
  clients: Client[];
  blacklist: BlacklistEntry[];
  recent_events: SimulationEvent[];
  recent_traffic: Traffic[];
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
}

export interface WatermarkDemo {
  demo: boolean;
  content_type: string;
  video_id: string;
  video_label: string;
  video_source: string;
  video_asset_url: string;
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
  };
  extracted_token: string;
  claim: Record<string, unknown>;
  round_trip_verified: boolean;
  payload_sha256: string;
  generated_at: number;
}

