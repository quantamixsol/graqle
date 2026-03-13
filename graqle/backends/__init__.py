from graqle.backends.base import BaseBackend
from graqle.backends.mock import MockBackend

__all__ = ["BaseBackend", "MockBackend"]

# Lazy imports for optional backends
def __getattr__(name: str):
    if name == "LocalModel":
        from graqle.backends.local import LocalModel
        return LocalModel
    if name in ("AnthropicBackend", "OpenAIBackend", "BedrockBackend",
                "OllamaBackend", "CustomBackend"):
        from graqle.backends import api
        return getattr(api, name)
    raise AttributeError(f"module 'graqle.backends' has no attribute {name!r}")
