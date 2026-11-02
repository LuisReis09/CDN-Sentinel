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
    load: int = 0
    blacklist_size: int = 0
    process_id: int | None = None
    last_error: str | None = None

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
    propagated_to: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WatermarkClaim:
    client_id: str
    server_id: str
    issued_at: float
    chunk_id: str
    signature: str

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
    events: List[Dict[str, Any]] = field(default_factory=list)
    traffic: List[Dict[str, Any]] = field(default_factory=list)

