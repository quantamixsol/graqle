"""graQle — Graphs that think.

Turn any knowledge graph into a reasoning network where each node
is an autonomous agent powered by a model-agnostic backend.
The Q stands for Query, Quality, and Quantified reasoning.
"""

# ── graqle:intelligence ──
# module: graqle.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: __version__, graph, node, edge, message +2 more
# constraints: none
# ── /graqle:intelligence ──

from graqle.__version__ import __version__
from graqle.core.graph import Graqle
from graqle.core.node import CogniNode
from graqle.core.edge import CogniEdge
from graqle.core.message import Message
from graqle.core.state import NodeState
from graqle.core.types import ReasoningType, NodeStatus, ReasoningResult

__all__ = [
    "__version__",
    "Graqle",
    "CogniNode",
    "CogniEdge",
    "Message",
    "NodeState",
    "ReasoningType",
    "NodeStatus",
    "ReasoningResult",
]
