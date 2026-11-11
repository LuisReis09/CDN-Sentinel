from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class Client:
    client_id: str
    latitude: float
    longitude: float
    city: str
    malicious: bool = False
    active: bool = True
    online: bool = True
    videos_consumed: int = 0
    last_activity_at: float | None = None
    process_id: int | None = None
    process_status: str = "starting"
    watch_history: List[Dict[str, Any]] = field(default_factory=list)
    feedback_history: List[Dict[str, Any]] = field(default_factory=list)
    likes: int = 0
    dislikes: int = 0
    feedback_score: float = 0.0
    feedback_latency_avg_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CDNServer:
    server_id: str
    host: str
    port: int
    latitude: float
    longitude: float
    city: str
    status: str = "starting"
    lifecycle_status: str = "starting"
    health_status: str = "healthy"
    capacity_tier: str = "basic"
    capacity_rps: float = 0.0
    utilization: float = 0.0
    queue_depth: int = 0
    queue_rejected: int = 0
    queue_wait_ms: float = 0.0
    capacity_pressure: float = 0.0
    slo_breached: bool = False
    load: int = 0
    blacklist_size: int = 0
    messages_received: int = 0
    process_id: int | None = None
    last_error: str | None = None
    uptime_seconds: float = 0.0
    requests_total: int = 0
    errors_total: int = 0
    requests_in_flight: int = 0
    last_request_at: float | None = None
    fault: Dict[str, Any] = field(default_factory=dict)
    process_mode: str = "http"
    role: str = "edge"
    region: str = ""
    peer_ids: List[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"url": self.url}


@dataclass
class BlacklistEntry:
    client_id: str
    reason: str
    detected_at: float
    watermark_issued_at: float
    server_id: str
    proof_signature: str
    watermark_server_id: str | None = None
    propagated_to: List[str] = field(default_factory=list)
    proof_token: str | None = None

    def to_dict(self, include_proof: bool = False) -> Dict[str, Any]:
        result = asdict(self)
        if not include_proof:
            result.pop("proof_token", None)
        return result

    def to_internal_dict(self) -> Dict[str, Any]:
        return self.to_dict(include_proof=True)


@dataclass
class WatermarkClaim:
    client_id: str
    server_id: str
    issued_at: float
    chunk_id: str
    signature: str
    content_id: str | None = None
    version: str = "CDNWM2"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VideoChunk:
    chunk_id: str
    content_type: str
    payload: str
    watermark_token: str
    server_id: str
    client_id: str
    issued_at: float
    latency_ms: float
    request_id: str | None = None
    trace_id: str | None = None
    artificial_latency_ms: float = 0.0
    http_rtt_ms: float = 0.0
    queue_wait_ms: float = 0.0
    end_to_end_ms: float = 0.0
    routing_candidates: List[Dict[str, Any]] = field(default_factory=list)
    routing_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SimulationState:
    initialized: bool = False
    paused: bool = False
    started_at: float | None = None
    updated_at: float | None = None
    config: Dict[str, Any] = field(default_factory=dict)
    clients: Dict[str, Client] = field(default_factory=dict)
    servers: Dict[str, CDNServer] = field(default_factory=dict)
    blacklist: Dict[str, BlacklistEntry] = field(default_factory=dict)
    leaks: List[Dict[str, Any]] = field(default_factory=list)
    scan_history: List[Dict[str, Any]] = field(default_factory=list)
    metrics_history: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    traffic: List[Dict[str, Any]] = field(default_factory=list)
    simulation_id: str = ""
    lifecycle: str = "idle"
    ended_at: float | None = None
    end_reason: str | None = None

