"""Public-API smoke tests — `from graqle import *` and named imports.

Regression guard for CG-API-01 (v0.50.1): the v0.50.0 __all__ list had
"GraQle" (incorrect camel case) which caused `from graqle import *` to
raise AttributeError because the real class name is "Graqle".
"""
from __future__ import annotations


def test_star_import_works():
    """`from graqle import *` must not raise."""
    ns: dict = {}
    exec("from graqle import *", ns)
    assert "Graqle" in ns
    assert ns["Graqle"] is not None


def test_graqle_class_importable():
    """The public Graqle class must be importable under its canonical name."""
    from graqle import Graqle

    assert Graqle is not None
    assert Graqle.__name__ == "Graqle"


def test_cogni_aliases_still_work():
    """Legacy CogniGraph / CogniNode / CogniEdge aliases remain importable."""
    from graqle import CogniEdge, CogniGraph, CogniNode

    assert CogniGraph is not None
    assert CogniNode is not None
    assert CogniEdge is not None
