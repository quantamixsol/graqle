"""Analyzer — Claude Vision analysis pipeline via Bedrock."""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.phantom.analyzer")

_DEFAULT_UX_PROMPT = (
    "Analyze this UI screenshot as an expert UX researcher. Identify: "
    "(1) Visual hierarchy issues, (2) Friction points a user would encounter, "
    "(3) Accessibility concerns visible in the design, (4) Missing affordances "
    "(buttons that don't look clickable, unclear CTAs), (5) Information overload "
    "or cognitive load issues, (6) Brand consistency problems."
)


class VisionAnalyzer:
    """Claude Vision analysis pipeline for screenshots.

    Uses AWS Bedrock to send screenshots to Claude for UX/UI analysis.
    Product-agnostic — works on any website screenshot.
    """

    def __init__(self, config: Any = None):
        self.config = config
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-load Bedrock client."""
        if self._client is None:
            import boto3
            if self.config:
                region = self.config.bedrock.region
            else:
                from graqle.plugins.phantom.config import _detect_region
                region = _detect_region()
            self._client = boto3.client("bedrock-runtime", region_name=region)
        return self._client

    def _get_model_id(self, model: str = "sonnet") -> str:
        """Resolve model shortname to Bedrock model ID."""
        if not self.config:
            from graqle.plugins.phantom.config import _detect_region, _resolve_vision_model
            return _resolve_vision_model(_detect_region(), model)
        if model == "opus":
            return self.config.bedrock.opus_model_id
        elif model == "haiku":
            return self.config.bedrock.haiku_model_id
        return self.config.bedrock.model_id

    async def analyze_screenshot(
        self,
        screenshot_path: Path | str,
        prompt: str | None = None,
        model: str = "sonnet",
    ) -> dict[str, Any]:
        """Send screenshot to Claude Vision for analysis."""
        import json

        screenshot_path = Path(screenshot_path)
        if not screenshot_path.exists():
            return {"error": f"Screenshot not found: {screenshot_path}"}

        image_data = base64.b64encode(screenshot_path.read_bytes()).decode("utf-8")
        analysis_prompt = prompt or _DEFAULT_UX_PROMPT

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": analysis_prompt,
                        },
                    ],
                }
            ],
        })

        try:
            import asyncio
            client = self._get_client()
            model_id = self._get_model_id(model)

            # Run synchronous Bedrock call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.invoke_model(
                    modelId=model_id,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                ),
            )

            result = json.loads(response["body"].read())
            text = result["content"][0]["text"]
            usage = result.get("usage", {})

            # Parse findings from the Vision response
            findings = self._parse_findings(text)

            return {
                "model": model_id.split("/")[-1] if "/" in model_id else model_id,
                "findings": findings,
                "overall_impression": text[:500],
                "raw_analysis": text,
                "cost_usd": self._estimate_cost(usage, model),
                "tokens": {
                    "input": usage.get("input_tokens", 0),
                    "output": usage.get("output_tokens", 0),
                },
            }

        except Exception as exc:
            logger.error("Vision analysis failed: %s", exc)
            return {"error": str(exc)}

    def _parse_findings(self, text: str) -> list[dict[str, Any]]:
        """Extract structured findings from free-text Vision response."""
        findings = []
        categories = [
            "visual_hierarchy", "friction", "accessibility",
            "missing_affordance", "cognitive_load", "brand_consistency",
        ]
        severity_keywords = {
            "critical": ["critical", "severe", "broken", "unusable"],
            "high": ["significant", "major", "important", "confusing"],
            "medium": ["moderate", "could improve", "unclear", "inconsistent"],
            "low": ["minor", "subtle", "cosmetic", "nitpick"],
        }

        lines = text.split("\n")
        current_category = "general"

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                # Detect category headers
                lower = line_stripped.lower()
                for cat in categories:
                    if cat.replace("_", " ") in lower:
                        current_category = cat
                continue

            if len(line_stripped) > 20:
                severity = "medium"
                lower = line_stripped.lower()
                for sev, keywords in severity_keywords.items():
                    if any(kw in lower for kw in keywords):
                        severity = sev
                        break

                findings.append({
                    "category": current_category,
                    "severity": severity,
                    "description": line_stripped[:300],
                })

        return findings

    @staticmethod
    def _estimate_cost(usage: dict, model: str) -> float:
        """Estimate USD cost based on token usage."""
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        # Approximate Bedrock pricing per 1M tokens
        rates = {
            "sonnet": {"input": 3.0, "output": 15.0},
            "opus": {"input": 15.0, "output": 75.0},
            "haiku": {"input": 0.25, "output": 1.25},
        }
        rate = rates.get(model, rates["sonnet"])
        return round(
            (input_tokens * rate["input"] + output_tokens * rate["output"]) / 1_000_000,
            4,
        )
