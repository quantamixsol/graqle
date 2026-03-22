"""Phantom configuration — Pydantic model for type-safe config."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ViewportPreset(BaseModel):
    name: str
    width: int
    height: int
    device_scale_factor: int = 1


VIEWPORT_PRESETS = {
    "mobile": ViewportPreset(name="mobile", width=390, height=844, device_scale_factor=3),
    "tablet": ViewportPreset(name="tablet", width=768, height=1024, device_scale_factor=2),
    "desktop": ViewportPreset(name="desktop", width=1920, height=1080, device_scale_factor=1),
}


def _resolve_region_prefix(region: str) -> str:
    """Derive Bedrock inference-profile prefix from AWS region."""
    if region.startswith("eu-"):
        return "eu"
    if region.startswith("us-"):
        return "us"
    return "us"  # default for ap-, me-, sa- (use US cross-region)


def _resolve_vision_model(region: str, tier: str = "sonnet") -> str:
    """Build region-correct Bedrock model ID from tier name.

    Never hardcode ``us.`` — always derive from the user's region.
    """
    prefix = _resolve_region_prefix(region)
    models = {
        "sonnet": f"{prefix}.anthropic.claude-sonnet-4-6",
        "opus": f"{prefix}.anthropic.claude-opus-4-6-v1",
        "haiku": f"{prefix}.anthropic.claude-haiku-4-5-20251001-v1:0",
    }
    return models.get(tier, f"{prefix}.anthropic.claude-sonnet-4-6")


def _detect_region() -> str:
    """Read region from graqle.yaml → model.region, env vars, or default."""
    import os
    # 1. graqle.yaml
    try:
        from graqle.config.settings import GraqleConfig
        for candidate in [Path("graqle.yaml"), Path.cwd() / "graqle.yaml"]:
            if candidate.exists():
                cfg = GraqleConfig.from_yaml(str(candidate))
                if cfg.model.region:
                    return cfg.model.region
    except Exception:
        pass
    # 2. Environment variables
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
    if region:
        return region
    # 3. Default
    return "us-east-1"


class BedrockConfig(BaseModel):
    region: str = ""
    model_id: str = ""
    opus_model_id: str = ""
    haiku_model_id: str = ""

    def model_post_init(self, __context: Any) -> None:
        """Resolve defaults from graqle.yaml / env if not explicitly set."""
        if not self.region:
            self.region = _detect_region()
        if not self.model_id:
            self.model_id = _resolve_vision_model(self.region, "sonnet")
        if not self.opus_model_id:
            self.opus_model_id = _resolve_vision_model(self.region, "opus")
        if not self.haiku_model_id:
            self.haiku_model_id = _resolve_vision_model(self.region, "haiku")


class BrandRules(BaseModel):
    min_body_font_px: int = 16
    min_caption_font_px: int = 14
    min_touch_target_px: int = 44
    wcag_contrast_ratio: float = 4.5
    max_content_width_px: int = 1440
    primary_color: str = "#2563EB"
    secondary_color: str = "#0F1B2D"
    accent_color: str = "#059669"
    font_family: str = "Inter"


class PhantomConfig(BaseModel):
    """Configuration for a Phantom audit/automation session."""

    output_dir: str = "./scorch-output/phantom"
    bedrock: BedrockConfig = Field(default_factory=BedrockConfig)
    brand_rules: BrandRules = Field(default_factory=BrandRules)
    headless: bool = True
    default_wait_after: int = 2000
    max_sessions: int = 5
    screenshot_quality: int = 80
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    auth_profiles_dir: str = "./scorch-output/phantom/auth_profiles"

    @classmethod
    def from_json(cls, path: str) -> PhantomConfig:
        """Load config from a JSON file."""
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**_normalize_keys(data))

    def to_json(self, path: str) -> None:
        """Write config to a JSON file."""
        import json
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)


def _normalize_keys(d: dict[str, Any]) -> dict[str, Any]:
    """Convert camelCase config keys to snake_case."""
    result = {}
    for k, v in d.items():
        snake = re.sub(r'(?<!^)(?=[A-Z])', '_', k).lower()
        if isinstance(v, dict):
            v = _normalize_keys(v)
        result[snake] = v
    return result
