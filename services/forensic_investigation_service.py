"""Investigation workflow for authorized external media.

Detection is evidence collection.  Administrative action is a separate,
explicit review transition and is never performed by this service.
"""

from __future__ import annotations

import hashlib
import hmac
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from services.watermark_service import WatermarkService
from services.content_provider import HybridContentProvider
from watermark.content_match import match_claimed_content


class ForensicInvestigationService:
    def __init__(self, watermark_service: WatermarkService) -> None:
        self._watermark_service = watermark_service
        self._catalog = HybridContentProvider()

    def investigate_video(self, path: str | Path, *, source: str = "authorized-upload", algorithm: str = "auto") -> dict[str, Any]:
        media_path = Path(path).resolve()
        if not media_path.is_file():
            raise FileNotFoundError(str(media_path))
        source = str(source)[:240]
        digest_obj = hashlib.sha256()
        with media_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest_obj.update(block)
        digest = digest_obj.hexdigest()
        investigation_id = f"inv-{uuid.uuid4().hex}"
        started = time.time()
        try:
            evidence = self._watermark_service.detect_forensic_video(media_path, algorithm=algorithm)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            evidence = {"status": "ERROR", "reason": "detector_failed", "error_type": type(exc).__name__}
        if not isinstance(evidence, dict):
            evidence = {"status": "ERROR", "reason": "invalid_detector_result"}
        content_match: dict[str, Any] | None = None
        if evidence.get("forensic_status") == "VALID" and evidence.get("claim"):
            try:
                reference, _type = self._catalog.resolve_asset(evidence["claim"]["content_id"])
                content_match = match_claimed_content(media_path, reference)
            except (FileNotFoundError, KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                content_match = {"status": "ERROR", "reason": "content_match_failed", "error_type": type(exc).__name__}
            if not isinstance(content_match, dict):
                content_match = {"status": "ERROR", "reason": "invalid_content_match_result"}
            if content_match.get("status") == "MATCH":
                decision = "PENDING_REVIEW"
                attribution = "AUTHENTICATED_SESSION"
            elif content_match.get("status") not in {"MATCH", "MISMATCH", "INCONCLUSIVE"}:
                decision = "ERROR"
                attribution = "NONE"
            else:
                decision = "INCONCLUSIVE"
                attribution = "NONE"
        elif evidence.get("forensic_status") == "CANDIDATE":
            decision = "CANDIDATE"
            attribution = "NONE"
        elif evidence.get("forensic_status", evidence.get("status")) == "NOT_FOUND":
            decision = "NOT_FOUND"
            attribution = "NONE"
        elif evidence.get("forensic_status", evidence.get("status")) == "INCONCLUSIVE":
            decision = "INCONCLUSIVE"
            attribution = "NONE"
        else:
            decision = "ERROR"
            attribution = "NONE"
        claim = evidence.get("claim") or {}
        event_payload = {
            "investigation_id": investigation_id, "source": source, "source_trust": "untrusted-submitter-assertion", "media_sha256": digest,
            "forensic_status": evidence.get("forensic_status", evidence.get("status")),
            "attribution": attribution, "decision": decision,
            "content_id": claim.get("content_id"), "session_id": claim.get("session_id"),
            "watermark_id": claim.get("watermark_id"), "finished_at": time.time(),
            "content_match": content_match,
            "detector_result": evidence,
        }
        self._watermark_service._registry_store.append_forensic_event(
            self._watermark_service.secret_key, "INVESTIGATION_COMPLETED", event_payload, claim.get("watermark_id")
        )
        return {
            "investigation_id": investigation_id,
            "source": source,
            "source_trust": "untrusted-submitter-assertion",
            "media_sha256": digest,
            "started_at": started,
            "finished_at": time.time(),
            "forensic_status": event_payload["forensic_status"],
            "decision": decision,
            "attribution": attribution,
            "content_id": claim.get("content_id") if decision == "PENDING_REVIEW" else None,
            "session_id": claim.get("session_id") if decision == "PENDING_REVIEW" else None,
            "watermark_id": claim.get("watermark_id") if decision == "PENDING_REVIEW" else None,
            "claim": claim if decision == "PENDING_REVIEW" else None,
            "content_match": content_match,
            "evidence": evidence,
            "administrative_action": "REVIEW_REQUIRED",
            "blacklist_changed": False,
        }

    def investigate_simulated_cdn_leak(
        self,
        path: str | Path,
        *,
        expected_media_sha256: str,
        expected_client_id: str,
        expected_server_id: str,
        expected_content_id: str | None,
        algorithm: str = "qim3",
    ) -> dict[str, Any]:
        """Authenticate an internally captured CDN leak without Studio's slow match.

        This restricted path retains the independent QIM extraction and the
        exact marker/cryptographic-claim check.  It replaces only the costly
        reference-video comparison with immutable facts from the capture that
        created the media: SHA-256 plus client, server and content bindings.
        Arbitrary uploads continue through :meth:`investigate_video`.
        """
        media_path = Path(path).resolve()
        if not media_path.is_file():
            raise FileNotFoundError(str(media_path))
        digest_obj = hashlib.sha256()
        with media_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest_obj.update(block)
        digest = digest_obj.hexdigest()
        investigation_id = f"inv-{uuid.uuid4().hex}"
        started = time.time()
        expected_digest = str(expected_media_sha256 or "").lower()
        digest_matches = bool(expected_digest) and hmac.compare_digest(digest, expected_digest)
        try:
            evidence = self._watermark_service.detect_forensic_video(media_path, algorithm=algorithm)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            evidence = {"status": "ERROR", "reason": "detector_failed", "error_type": type(exc).__name__}
        if not isinstance(evidence, dict):
            evidence = {"status": "ERROR", "reason": "invalid_detector_result"}

        claim = evidence.get("claim") or {}
        bindings = {
            "digest": digest_matches,
            "client_id": claim.get("client_id") == expected_client_id,
            "server_id": claim.get("server_id") == expected_server_id,
            "content_id": expected_content_id is None or claim.get("content_id") == expected_content_id,
        }
        content_match = {
            "status": "MATCH" if evidence.get("forensic_status") == "VALID" and all(bindings.values()) else "MISMATCH",
            "method": "simulated-cdn-capture-digest-and-bound-watermark-claim",
            "bindings": bindings,
        }
        if evidence.get("forensic_status") == "VALID" and all(bindings.values()):
            decision, attribution = "PENDING_REVIEW", "AUTHENTICATED_SESSION"
        elif evidence.get("forensic_status") == "CANDIDATE":
            decision, attribution = "CANDIDATE", "NONE"
        elif evidence.get("forensic_status", evidence.get("status")) == "NOT_FOUND":
            decision, attribution = "NOT_FOUND", "NONE"
        elif evidence.get("forensic_status", evidence.get("status")) == "INCONCLUSIVE" or evidence.get("forensic_status") == "VALID":
            # A valid marker with a capture mismatch is never attributed.
            decision, attribution = "INCONCLUSIVE", "NONE"
        else:
            decision, attribution = "ERROR", "NONE"
        event_payload = {
            "investigation_id": investigation_id,
            "source": "simulated-cdn-capture",
            "source_trust": "simulator-captured-media-with-digest-binding",
            "media_sha256": digest,
            "forensic_status": evidence.get("forensic_status", evidence.get("status")),
            "attribution": attribution,
            "decision": decision,
            "content_id": claim.get("content_id"),
            "session_id": claim.get("session_id"),
            "watermark_id": claim.get("watermark_id"),
            "finished_at": time.time(),
            "content_match": content_match,
            "detector_result": evidence,
        }
        self._watermark_service._registry_store.append_forensic_event(
            self._watermark_service.secret_key,
            "INVESTIGATION_COMPLETED",
            event_payload,
            claim.get("watermark_id"),
        )
        return {
            "investigation_id": investigation_id,
            "source": event_payload["source"],
            "source_trust": event_payload["source_trust"],
            "media_sha256": digest,
            "started_at": started,
            "finished_at": time.time(),
            "forensic_status": event_payload["forensic_status"],
            "decision": decision,
            "attribution": attribution,
            "content_id": claim.get("content_id") if decision == "PENDING_REVIEW" else None,
            "session_id": claim.get("session_id") if decision == "PENDING_REVIEW" else None,
            "watermark_id": claim.get("watermark_id") if decision == "PENDING_REVIEW" else None,
            "claim": claim if decision == "PENDING_REVIEW" else None,
            "content_match": content_match,
            "evidence": evidence,
            "administrative_action": "AUTOMATIC_BLACKLIST_ELIGIBLE",
            "blacklist_changed": False,
        }

    def review(self, investigation_id: str, decision: str, reviewer: str, notes: str = "") -> dict[str, Any]:
        normalized = str(decision).upper()
        if normalized not in {"ACCEPT", "REJECT", "INCONCLUSIVE"}:
            raise ValueError("decision deve ser ACCEPT, REJECT ou INCONCLUSIVE")
        if not investigation_id or len(investigation_id) > 80 or not reviewer or len(reviewer) > 160:
            raise ValueError("investigation_id ou reviewer inválido")
        registry = self._watermark_service._registry_store
        if not registry.verify_forensic_events(self._watermark_service.secret_key):
            raise ValueError("integridade da trilha forense inválida")
        events = registry.forensic_events(self._watermark_service.secret_key)
        original = next((event for event in events if event["event_type"] == "INVESTIGATION_COMPLETED" and event["payload"].get("investigation_id") == investigation_id), None)
        if original is None:
            raise ValueError("investigação inexistente")
        if normalized == "ACCEPT" and original["payload"].get("decision") != "PENDING_REVIEW":
            raise ValueError("investigação inconclusiva não pode ser aprovada")
        if any(event["event_type"] == "INVESTIGATION_REVIEWED" and event["payload"].get("investigation_id") == investigation_id for event in events):
            raise ValueError("investigação já revisada")
        payload = {"investigation_id": investigation_id, "decision": normalized, "reviewer": reviewer, "notes": notes[:2_000], "reviewed_at": time.time()}
        event = registry.append_forensic_event(self._watermark_service.secret_key, "INVESTIGATION_REVIEWED", payload, original["watermark_id"])
        return {**payload, "state": "REVIEWED", "event": event, "administrative_action": "NO_AUTOMATIC_BLACKLIST"}
