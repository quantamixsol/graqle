from graqle.adapters.config import AdapterConfig
from graqle.adapters.registry import AdapterRegistry
from graqle.adapters.auto_select import AdapterAutoSelector, SelectionResult

__all__ = ["AdapterConfig", "AdapterRegistry", "AdapterAutoSelector", "SelectionResult"]

def __getattr__(name: str):
    if name == "AdapterLoader":
        from graqle.adapters.loader import AdapterLoader
        return AdapterLoader
    if name == "AdapterHub":
        from graqle.adapters.hub import AdapterHub
        return AdapterHub
    raise AttributeError(f"module 'graqle.adapters' has no attribute {name!r}")
