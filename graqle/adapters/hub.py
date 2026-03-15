"""AdapterHub — download/upload adapters from HuggingFace Hub."""

# ── graqle:intelligence ──
# module: graqle.adapters.hub
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, logging, pathlib, config
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from pathlib import Path

from graqle.adapters.config import AdapterConfig

logger = logging.getLogger("graqle.adapters.hub")


class AdapterHub:
    """Interface for downloading and uploading LoRA adapters.

    Supports HuggingFace Hub for community adapter sharing.
    """

    def __init__(
        self,
        cache_dir: str | Path = "./adapters",
        hub_org: str = "graqle",
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.hub_org = hub_org

    def download(
        self,
        adapter_id: str,
        revision: str = "main",
    ) -> Path:
        """Download an adapter from HuggingFace Hub.

        Args:
            adapter_id: Hub identifier, e.g., "graqle/gdpr_v1"
            revision: Git revision/branch

        Returns:
            Local path to the downloaded adapter.
        """
        try:
            from huggingface_hub import snapshot_download

            local_path = self.cache_dir / adapter_id.replace("/", "_")
            snapshot_download(
                repo_id=adapter_id,
                local_dir=str(local_path),
                revision=revision,
            )
            logger.info(f"Downloaded adapter: {adapter_id} -> {local_path}")
            return local_path
        except ImportError:
            raise ImportError(
                "Adapter Hub requires 'huggingface_hub'. "
                "Install with: pip install huggingface-hub"
            )

    def upload(
        self,
        adapter_path: str | Path,
        repo_id: str,
        config: AdapterConfig | None = None,
    ) -> str:
        """Upload an adapter to HuggingFace Hub.

        Returns the Hub URL.
        """
        try:
            from huggingface_hub import HfApi

            api = HfApi()
            api.upload_folder(
                folder_path=str(adapter_path),
                repo_id=repo_id,
                repo_type="model",
            )
            url = f"https://huggingface.co/{repo_id}"
            logger.info(f"Uploaded adapter to: {url}")
            return url
        except ImportError:
            raise ImportError(
                "Adapter Hub requires 'huggingface_hub'. "
                "Install with: pip install huggingface-hub"
            )

    def list_available(self, domain: str | None = None) -> list[str]:
        """List available adapters on HuggingFace Hub."""
        try:
            from huggingface_hub import HfApi

            api = HfApi()
            models = api.list_models(author=self.hub_org)
            adapter_ids = [m.id for m in models]
            if domain:
                adapter_ids = [a for a in adapter_ids if domain in a]
            return adapter_ids
        except ImportError:
            logger.warning("huggingface_hub not installed")
            return []
