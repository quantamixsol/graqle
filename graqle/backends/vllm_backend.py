"""vLLM backend — high-throughput GPU inference with multi-LoRA support.

Uses vLLM's AsyncLLMEngine for batched inference with concurrent
LoRA adapter serving (S-LoRA pattern: 50+ adapters on single GPU).
"""

from __future__ import annotations

import logging
from typing import Any

from graqle.backends.base import BaseBackend

logger = logging.getLogger("graqle.backends.vllm")


class VLLMBackend(BaseBackend):
    """vLLM-powered inference backend.

    Features:
    - Continuous batching (PagedAttention)
    - Multi-LoRA serving (adapter hot-swap per request)
    - Async generation (non-blocking)
    - Quantization support (AWQ, GPTQ, FP8)

    Requires: pip install graqle[gpu] (which includes vllm)
    """

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-0.5B-Instruct",
        *,
        tensor_parallel_size: int = 1,
        max_model_len: int = 4096,
        gpu_memory_utilization: float = 0.85,
        enable_lora: bool = False,
        max_lora_rank: int = 64,
        quantization: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.tensor_parallel_size = tensor_parallel_size
        self.max_model_len = max_model_len
        self.gpu_memory_utilization = gpu_memory_utilization
        self.enable_lora = enable_lora
        self.max_lora_rank = max_lora_rank
        self.quantization = quantization
        self._engine: Any = None
        self._tokenizer: Any = None

    def _ensure_engine(self) -> None:
        """Lazily initialize vLLM engine."""
        if self._engine is not None:
            return

        try:
            from vllm import AsyncLLMEngine
            from vllm.engine.arg_utils import AsyncEngineArgs
        except ImportError:
            raise ImportError(
                "vLLM not installed. Install with: pip install graqle[gpu]"
            )

        args = AsyncEngineArgs(
            model=self.model_name,
            tensor_parallel_size=self.tensor_parallel_size,
            max_model_len=self.max_model_len,
            gpu_memory_utilization=self.gpu_memory_utilization,
            enable_lora=self.enable_lora,
            max_lora_rank=self.max_lora_rank,
            quantization=self.quantization,
        )
        self._engine = AsyncLLMEngine.from_engine_args(args)

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> str:
        """Generate text using vLLM engine."""
        self._ensure_engine()

        from vllm import SamplingParams

        sampling_params = SamplingParams(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=kwargs.get("top_p", 0.95),
        )

        # LoRA adapter request
        lora_request = None
        adapter_name = kwargs.get("adapter")
        if adapter_name and self.enable_lora:
            from vllm.lora.request import LoRARequest
            lora_request = LoRARequest(
                lora_name=adapter_name,
                lora_int_id=hash(adapter_name) % (2**31),
                lora_local_path=adapter_name,
            )

        import uuid
        request_id = str(uuid.uuid4())

        results = self._engine.generate(
            prompt,
            sampling_params,
            request_id=request_id,
            lora_request=lora_request,
        )

        final_output = None
        async for output in results:
            final_output = output

        if final_output and final_output.outputs:
            return final_output.outputs[0].text
        return ""

    @property
    def name(self) -> str:
        return f"vllm:{self.model_name}"

    @property
    def cost_per_1k_tokens(self) -> float:
        return 0.001  # Local GPU inference cost estimate
