"""R9 KG Registry — async-safe registration and health monitoring."""

# ── graqle:intelligence ──
# module: graqle.federation.registry
# risk: MEDIUM (impact radius: 3 modules)
# consumers: federation.activator, federation.reasoning
# dependencies: __future__, asyncio, logging, time, typing
# constraints: async-safe (asyncio.Lock), no threading.Lock in async paths
# ── /graqle:intelligence ──

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from graqle.federation.types import KGRegistration, KGStatus

logger = logging.getLogger("graqle.federation.registry")


def _now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso8601(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


class KGRegistry:
    """Async-safe registry of knowledge graphs participating in federation.

    Uses ``asyncio.Lock`` for all operations to prevent deadlocks in
    async contexts. Synchronous callers should use ``asyncio.run()``
    or the sync wrapper methods.
    """

    def __init__(self, heartbeat_timeout_ms: int = 30000) -> None:
        self._registry: Dict[str, KGRegistration] = {}
        self._lock = asyncio.Lock()
        self._heartbeat_timeout_ms = heartbeat_timeout_ms

    def register(self, kg: KGRegistration) -> None:
        """Register a KG for federation (sync). Idempotent."""
        kg.last_heartbeat = _now_iso8601()
        kg.status = KGStatus.ACTIVE
        self._registry[kg.kg_id] = kg
        logger.info("Registered KG: %s (%s, %d nodes)", kg.kg_id, kg.language, kg.node_count)

    async def aregister(self, kg: KGRegistration) -> None:
        """Register a KG for federation (async). Idempotent."""
        async with self._lock:
            self.register(kg)

    def deregister(self, kg_id: str, graceful: bool = True) -> None:
        """Remove a KG from federation (sync)."""
        if kg_id not in self._registry:
            return
        if graceful:
            self._registry[kg_id].status = KGStatus.DRAINING
            logger.info("KG %s set to DRAINING", kg_id)
        else:
            del self._registry[kg_id]
            logger.info("KG %s removed immediately", kg_id)

    async def aderegister(self, kg_id: str, graceful: bool = True) -> None:
        """Remove a KG from federation (async)."""
        async with self._lock:
            self.deregister(kg_id, graceful)

    def heartbeat(self, kg_id: str, response_ms: float = 0.0) -> None:
        """Update heartbeat timestamp and rolling metrics (sync)."""
        if kg_id not in self._registry:
            return
        kg = self._registry[kg_id]
        kg.last_heartbeat = _now_iso8601()
        # EMA alpha from config (safe default — production value from private config)
        alpha = kg.avg_response_ms == 0.0 and 1.0 or 0.3  # bootstrap on first call
        kg.avg_response_ms = alpha * response_ms + (1 - alpha) * kg.avg_response_ms
        if kg.status == KGStatus.DEGRADED and response_ms < 1000:
            kg.status = KGStatus.ACTIVE

    async def aheartbeat(self, kg_id: str, response_ms: float = 0.0) -> None:
        """Update heartbeat (async)."""
        async with self._lock:
            self.heartbeat(kg_id, response_ms)

    def get_active(self) -> List[KGRegistration]:
        """Return all KGs eligible for query routing (ACTIVE or DEGRADED)."""
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

    async def aget_active(self) -> List[KGRegistration]:
        """Return active KGs (async)."""
        async with self._lock:
            return self.get_active()

    def mark_degraded(self, kg_id: str, reason: str) -> None:
        """Mark a KG as degraded (sync)."""
        if kg_id in self._registry:
            self._registry[kg_id].status = KGStatus.DEGRADED
            logger.warning("KG %s marked DEGRADED: %s", kg_id, reason)

    async def amark_degraded(self, kg_id: str, reason: str) -> None:
        """Mark degraded (async)."""
        async with self._lock:
            self.mark_degraded(kg_id, reason)

    def get(self, kg_id: str) -> Optional[KGRegistration]:
        """Get a specific KG registration."""
        return self._registry.get(kg_id)

    def list_all(self) -> List[KGRegistration]:
        """List all registered KGs regardless of status."""
        return list(self._registry.values())

    def __len__(self) -> int:
        return len(self._registry)
