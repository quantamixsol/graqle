"""PCT extension namespaces.

Currently ships:
    - :mod:`graqle.pct.extensions.x_ai_eu` — EU AI Act PCT extension
      namespace, Quantamix-authored per ADR-205 + ADR-RT-001.

Future namespaces (one Python module per OPSF-registered namespace)
land here as additional files. The OPSF naming convention is
``x-{framework}:{field}`` — module names mirror this with underscores:
``x-ai-eu`` → ``x_ai_eu.py``.
"""

from __future__ import annotations

from graqle.pct.extensions.x_ai_eu import XAiEuExtension, X_AI_EU_NAMESPACE

__all__ = ["XAiEuExtension", "X_AI_EU_NAMESPACE"]
