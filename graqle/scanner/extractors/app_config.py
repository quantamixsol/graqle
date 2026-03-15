"""Application config extractor — config/*.json, settings.json.

Produces ``Config`` nodes with ``CONSUMED_BY`` edges (linked later via
the auto-linker).
"""

# ── graqle:intelligence ──
# module: graqle.scanner.extractors.app_config
# risk: LOW (impact radius: 1 modules)
# consumers: test_app_config
# dependencies: __future__, typing, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from typing import Any

from graqle.scanner.extractors.base import (
    BaseExtractor,
    ExtractedNode,
    ExtractionResult,
)


class AppConfigExtractor(BaseExtractor):
    """Extract application configuration key-value pairs."""

    # Keys to never include (secrets, large blobs)
    _SKIP_KEYS = frozenset({
        "password", "secret", "token", "api_key", "apiKey",
        "private_key", "privateKey", "credentials",
    })

    def extract(
        self,
        data: dict[str, Any],
        file_path: str,
        *,
        rel_path: str = "",
    ) -> ExtractionResult:
        result = ExtractionResult()
        source = rel_path or file_path

        self._extract_flat(data, source, result, prefix="")
        return result

    def _extract_flat(
        self,
        data: dict,
        source: str,
        result: ExtractionResult,
        prefix: str,
        depth: int = 0,
    ) -> None:
        if depth > 3:
            return

        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key

            # Skip secrets
            if key.lower() in self._SKIP_KEYS:
                continue

            if isinstance(value, dict) and depth < 3:
                self._extract_flat(value, source, result, full_key, depth + 1)
            elif isinstance(value, (str, int, float, bool)):
                config_id = f"config::{source}::{full_key}"
                val_str = str(value)
                result.nodes.append(ExtractedNode(
                    id=config_id,
                    label=f"{full_key}={val_str[:40]}",
                    entity_type="CONFIG",
                    description=f"Config '{full_key}' = {val_str[:200]} (from {source})",
                    properties={
                        "key": full_key,
                        "value": value,
                        "value_type": type(value).__name__,
                        "source": source,
                    },
                ))
            elif isinstance(value, list) and len(value) <= 10:
                config_id = f"config::{source}::{full_key}"
                val_str = str(value)[:200]
                result.nodes.append(ExtractedNode(
                    id=config_id,
                    label=f"{full_key}=[{len(value)} items]",
                    entity_type="CONFIG",
                    description=f"Config '{full_key}' = {val_str} (from {source})",
                    properties={
                        "key": full_key,
                        "value": val_str,
                        "value_type": "list",
                        "item_count": len(value),
                        "source": source,
                    },
                ))
