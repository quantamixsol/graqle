from graqle.connectors.base import BaseConnector
from graqle.connectors.networkx import NetworkXConnector
from graqle.connectors.json_graph import JSONGraphConnector
from graqle.connectors.tamr import TAMRConnector

__all__ = ["BaseConnector", "NetworkXConnector", "JSONGraphConnector", "TAMRConnector"]

def __getattr__(name: str):
    if name == "Neo4jConnector":
        from graqle.connectors.neo4j import Neo4jConnector
        return Neo4jConnector
    raise AttributeError(f"module 'graqle.connectors' has no attribute {name!r}")
