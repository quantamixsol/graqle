"""Phantom — GraQle Computer Skill Plugin.

AI-powered browser automation + visual audit engine.
A first-party GraQle SDK plugin.

Usage:
    from graqle.plugins.phantom import PhantomEngine, PhantomConfig

    engine = PhantomEngine(PhantomConfig())
    result = await engine.browse("https://example.com")
    result = await engine.audit(session_id, dimensions=["all"])
"""

from graqle.plugins.phantom.config import PhantomConfig
from graqle.plugins.phantom.engine import PhantomEngine

__all__ = [
    "PhantomEngine",
    "PhantomConfig",
]
