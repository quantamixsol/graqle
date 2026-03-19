"""SCORCH configuration — Pydantic model for type-safe config."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ViewportConfig(BaseModel):
    name: str
    width: int
    height: int
    device_scale_factor: int = 1


class BedrockConfig(BaseModel):
    region: str = "us-east-1"
    model_id: str = "us.anthropic.claude-sonnet-4-6-20250514-v1:0"


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


class ScorchConfig(BaseModel):
    """Configuration for a SCORCH audit run."""

    base_url: str = "http://localhost:3000"
    pages: list[str] = ["/"]
    viewports: list[ViewportConfig] = Field(default_factory=lambda: [
        ViewportConfig(name="mobile", width=390, height=844, device_scale_factor=3),
        ViewportConfig(name="tablet", width=768, height=1024, device_scale_factor=2),
        ViewportConfig(name="desktop", width=1440, height=900, device_scale_factor=1),
    ])
    output_dir: str = "./scorch-output"
    bedrock: BedrockConfig = Field(default_factory=BedrockConfig)
    brand_rules: BrandRules = Field(default_factory=BrandRules)
    wait_after_load: int = 2000
    full_page: bool = True
    skip_behavioral: bool = False
    skip_vision: bool = False
    auth_state: str | None = None  # Path to Playwright storage state for auth

    @classmethod
    def from_json(cls, path: str) -> ScorchConfig:
        """Load config from a JSON file."""
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**_normalize_keys(data))

    def to_json(self, path: str) -> None:
        """Write config to a JSON file."""
        import json
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
