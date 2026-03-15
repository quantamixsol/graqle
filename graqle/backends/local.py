"""Local model backend — runs SLMs on local hardware via transformers or llama.cpp."""

# ── graqle:intelligence ──
# module: graqle.backends.local
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, base
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

from graqle.backends.base import BaseBackend


class LocalModel(BaseBackend):
    """Local SLM backend using HuggingFace Transformers.

    Supports any model from HuggingFace Hub. For GPU inference, use
    with vLLM backend (separate module). For CPU, this uses the
    transformers pipeline directly.

    Examples:
        backend = LocalModel("Qwen/Qwen2.5-0.5B-Instruct")
        backend = LocalModel("microsoft/Phi-4-mini-instruct")
        backend = LocalModel("meta-llama/Llama-3.2-3B-Instruct")
    """

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-0.5B-Instruct",
        device: str = "auto",
        quantization: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._quantization = quantization
        self._pipeline = None
        self._loaded = False

    def _load_model(self) -> None:
        """Lazily load the model on first use."""
        if self._loaded:
            return

        try:
            from transformers import pipeline

            kwargs: dict = {
                "model": self._model_name,
                "device_map": self._device,
                "trust_remote_code": True,
            }

            if self._quantization == "4bit":
                from transformers import BitsAndBytesConfig
                kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True)
            elif self._quantization == "8bit":
                from transformers import BitsAndBytesConfig
                kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)

            self._pipeline = pipeline("text-generation", **kwargs)
            self._loaded = True
        except ImportError:
            raise ImportError(
                "Local model backend requires 'transformers' and 'torch'. "
                "Install with: pip install graqle[gpu]"
            )

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        self._load_model()

        result = self._pipeline(
            prompt,
            max_new_tokens=max_tokens,
            temperature=max(temperature, 0.01),  # avoid 0
            do_sample=temperature > 0,
            return_full_text=False,
        )
        text = result[0]["generated_text"]

        # Apply stop sequences
        if stop:
            for s in stop:
                idx = text.find(s)
                if idx != -1:
                    text = text[:idx]

        return text.strip()

    @property
    def name(self) -> str:
        return f"local:{self._model_name}"

    @property
    def cost_per_1k_tokens(self) -> float:
        # Local inference — electricity cost only
        return 0.0001
