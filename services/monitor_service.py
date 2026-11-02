from __future__ import annotations

import time
from typing import Any, Dict, List

from repositories.in_memory import SimulationRepository
from services.blacklist_service import BlacklistService
from services.watermark_service import WatermarkService
from utils.video import extract_watermark_token


class MonitorService:
    def __init__(self, repository: SimulationRepository, watermark_service: WatermarkService, blacklist_service: BlacklistService) -> None:
        self._repository = repository
        self._watermark_service = watermark_service
        self._blacklist_service = blacklist_service

    def scan(self) -> Dict[str, Any]:
        state = self._repository.snapshot()
        detected: List[dict] = []
        rejected: List[dict] = []
        for leak in list(state.leaks):
            if leak.get("processed"):
                continue
            # The monitor intentionally extracts the prefix from the leaked
            # bytes, rather than trusting platform metadata.
            token = extract_watermark_token(leak.get("content", ""))
            try:
                claim = self._watermark_service.verify(token)
                entry = self._blacklist_service.report(token)
                leak["processed"] = True
                leak["detected_at"] = time.time()
                detected.append({"leak_id": leak["leak_id"], "claim": claim.to_dict(), "blacklist": entry.to_dict()})
            except (ValueError, KeyError, TypeError) as exc:
                leak["processed"] = True
                leak["error"] = str(exc)
                rejected.append({"leak_id": leak.get("leak_id"), "error": str(exc)})
        result = {
            "scanned": len(state.leaks),
            "detected": detected,
            "rejected": rejected,
            "blacklisted_total": len(state.blacklist),
            "scanned_at": time.time(),
        }
        state.scan_history.append(result)
        self._repository.append_event({
            "type": "monitor_scan",
            "at": result["scanned_at"],
            "detected": len(detected),
            "rejected": len(rejected),
            "proof_algorithm": "HMAC-SHA256",
            "source": "embedded chunk bytes",
        })
        return result

    def verify_token(self, token: str) -> dict:
        return self._watermark_service.verify(token).to_dict()

