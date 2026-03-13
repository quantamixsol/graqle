"""llama.cpp backend — CPU inference via GGUF quantized models.

Enables Graqle reasoning on machines without GPUs. Uses
llama-cpp-python bindings for efficient CPU inference with
GGUF quantization (Q4_K_M: 15-25 tok/s on modern CPUs).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from graqle.backends.base import BaseBackend

logger = logging.getLogger("graqle.backends.llamacpp")


class LlamaCppBackend(BaseBackend):
    """llama.cpp-powered CPU inference backend.

    Features:
    - GGUF model loading (any HuggingFace GGUF model)
    - Quantization levels (Q4_K_M, Q5_K_M, Q8_0, F16)
    - CPU-optimized (AVX2/AVX512, Apple Metal support)
    - Low memory footprint (~280MB for Qwen 0.5B Q4)

    Requires: pip install graqle[cpu] (which includes llama-cpp-python)
    """

    def __init__(
        self,
        model_path: str,
        *,
        n_ctx: int = 2048,
        n_threads: int | None = None,
        n_gpu_layers: int = 0,
        verbose: bool = False,
    ) -> None:
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        self._model: Any = None

    def _ensure_model(self) -> None:
        """Lazily initialize llama.cpp model."""
        if self._model is not None:
            return

        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError(
                "llama-cpp-python not installed. "
                "Install with: pip install graqle[cpu]"
            )

        if not Path(self.model_path).exists():
            raise FileNotFoundError(
                f"Model file not found: {self.model_path}. "
                "Download a GGUF model first."
            )

        self._model = Llama(
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            n_gpu_layers=self.n_gpu_layers,
            verbose=self.verbose,
        )
        logger.info(f"Loaded llama.cpp model: {self.model_path}")

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> str:
        """Generate text using llama.cpp.

        Note: llama.cpp is synchronous, so this runs in a thread executor.
        """
        import asyncio

        self._ensure_model()

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._generate_sync(prompt, max_tokens, temperature),
        )
        return result

    def _generate_sync(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        """Synchronous generation."""
        output = self._model(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            echo=False,
        )
        if output and "choices" in output and output["choices"]:
            return output["choices"][0].get("text", "")
        return ""

    @property
    def name(self) -> str:
        return f"llamacpp:{Path(self.model_path).stem}"

    @property
    def cost_per_1k_tokens(self) -> float:
        return 0.0005  # CPU inference is nearly free
