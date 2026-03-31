"""R9 KG Registry — thread-safe registration and health monitoring."""

# ── graqle:intelligence ──
# module: graqle.federation.registry
# risk: MEDIUM (impact radius: 3 modules)
# consumers: federation.activator, federation.reasoning
# dependencies: __future__, asyncio, logging, threading, time, typing
# constraints: thread-safe, heartbeat timeout configurable
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from graqle.federation.types import KGRegistration, KGStatus

logger = logging.getLogger("graqle.federation.registry")


def _now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso8601(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


class KGRegistry:
    """Thread-safe registry of knowledge graphs participating in federation."""

    def __init__(self, heartbeat_timeout_ms: int = 30000) -> None:
        self._registry: Dict[str, KGRegistration] = {}
        self._sync_lock = threading.Lock()
        self._async_lock: Optional[asyncio.Lock] = None
        self._heartbeat_timeout_ms = heartbeat_timeout_ms

    def _get_async_lock(self) -> asyncio.Lock:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def register(self, kg: KGRegistration) -> None:
        """Register a KG for federation. Idempotent — re-registration updates."""
        with self._sync_lock:
            kg.last_heartbeat = _now_iso8601()
            kg.status = KGStatus.ACTIVE
            self._registry[kg.kg_id] = kg
            logger.info("Registered KG: %s (%s, %d nodes)", kg.kg_id, kg.language, kg.node_count)

    def deregister(self, kg_id: str, graceful: bool = True) -> None:
        """Remove a KG from federation."""
        with self._sync_lock:
            if kg_id not in self._registry:
                return
            if graceful:
                self._registry[kg_id].status = KGStatus.DRAINING
                logger.info("KG %s set to DRAINING", kg_id)
            else:
                del self._registry[kg_id]
                logger.info("KG %s removed immediately", kg_id)

    def heartbeat(self, kg_id: str, response_ms: float = 0.0) -> None:
        """Update heartbeat timestamp and rolling metrics."""
        with self._sync_lock:
            if kg_id not in self._registry:
                return
            kg = self._registry[kg_id]
            kg.last_heartbeat = _now_iso8601()
            # Exponential moving average (alpha from config — TS-2 safe default)
            alpha = 0.3
            kg.avg_response_ms = alpha * response_ms + (1 - alpha) * kg.avg_response_ms
            if kg.status == KGStatus.DEGRADED and response_ms < 1000:
                kg.status = KGStatus.ACTIVE

    def get_active(self) -> List[KGRegistration]:
        """Return all KGs eligible for query routing (ACTIVE or DEGRADED)."""
        with self._sync_lock:
            now = time.time()
            active: list[KGRegistration] = []
            for kg in self._registry.values():
                if kg.status in (KGStatus.ACTIVE, KGStatus.DEGRADED):
                    if kg.last_heartbeat:
                        heartbeat_age_ms = (now - _parse_iso8601(kg.last_heartbeat)) * 1000
                        if heartbeat_age_ms > self._heartbeat_timeout_ms:
                            kg.status = KGStatus.OFFLINE
                            logger.warning("KG %s heartbeat expired — marked OFFLINE", kg.kg_id)
                            continue
                    active.append(kg)
            return active

    def mark_degraded(self, kg_id: str, reason: str) -> None:
        """Mark a KG as degraded (still queryable but with warnings)."""
        with self._sync_lock:
            if kg_id in self._registry:
                self._registry[kg_id].status = KGStatus.DEGRADED
                logger.warning("KG %s marked DEGRADED: %s", kg_id, reason)

    def get(self, kg_id: str) -> Optional[KGRegistration]:
        """Get a specific KG registration."""
        with self._sync_lock:
            return self._registry.get(kg_id)

    def list_all(self) -> List[KGRegistration]:
        """List all registered KGs regardless of status."""
        with self._sync_lock:
            return list(self._registry.values())

    def __len__(self) -> int:
        with self._sync_lock:
            return len(self._registry)
