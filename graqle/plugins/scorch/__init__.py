"""SCORCH — Surface Control & Optical Review for Crafted HTML.

AI-powered Visual + Behavioral + Journey Psychology audit engine.
A first-party Graqle SDK plugin.

Usage:
    from graqle.plugins.scorch import ScorchEngine, ScorchConfig

    engine = ScorchEngine(ScorchConfig(base_url="http://localhost:3000"))
    report = await engine.run()
"""

from graqle.plugins.scorch.config import ScorchConfig
from graqle.plugins.scorch.engine import ScorchEngine
from graqle.plugins.scorch.archetypes import ARCHETYPES, ARCHETYPE_BY_CODE, ARCHETYPE_BY_ID

__all__ = [
    "ScorchEngine",
    "ScorchConfig",
    "ARCHETYPES",
    "ARCHETYPE_BY_CODE",
    "ARCHETYPE_BY_ID",
]
