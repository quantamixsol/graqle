# ── graqle:intelligence ──
# module: graqle.backends.__init__
# risk: LOW (impact radius: 0 modules)
# dependencies: base, mock
# constraints: none
# ── /graqle:intelligence ──

from graqle.backends.base import BaseBackend, GenerateResult, TruncationError
from graqle.backends.mock import MockBackend

__all__ = ["BaseBackend", "GenerateResult", "TruncationError", "MockBackend"]

# Lazy imports for optional backends
def __getattr__(name: str):
    if name == "LocalModel":
        from graqle.backends.local import LocalModel
        return LocalModel
    if name in ("AnthropicBackend", "OpenAIBackend", "BedrockBackend",
                "OllamaBackend", "CustomBackend"):
        from graqle.backends import api
        return getattr(api, name)
    if name == "GeminiBackend":
        from graqle.backends.gemini import GeminiBackend
        return GeminiBackend
    if name in ("create_provider_backend", "PROVIDER_PRESETS",
                "get_provider_names"):
        from graqle.backends import providers
        return getattr(providers, name)
    raise AttributeError(f"module 'graqle.backends' has no attribute {name!r}")
