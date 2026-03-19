"""Phase 3: Claude Vision + Journey Psychology analysis via AWS Bedrock."""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.scorch.vision")


def _build_prompt(metrics: list[dict], behavioral: list[dict], config: Any) -> str:
    """Build the Claude Vision analysis prompt."""
    brand = config.brand_rules

    behavioral_summary = ""
    if behavioral:
        for entry in behavioral:
            if "findings" in entry:
                f = entry["findings"]
                behavioral_summary += f"\n  [{entry['viewport']}] {entry['page']}:"
                behavioral_summary += f" deadClicks={len(f.get('deadClicks', []))}"
                behavioral_summary += f" silentSubs={len(f.get('silentSubmissions', []))}"
                behavioral_summary += f" jargon={len(f.get('unexplainedJargon', []))}"
                behavioral_summary += f" ghosts={len(f.get('ghostElements', []))}"
                behavioral_summary += f" missingCTA={f.get('missingNextStepCta', False)}"
                behavioral_summary += f" copyFriction={len(f.get('copyPasteFriction', []))}"

    return f"""You are SCORCH v3 — an expert UI/UX auditor analyzing web pages for friction.

Analyze the provided screenshots across these 12 dimensions:

**Visual (CSS Metrics — Phase 2):**
1. Font sizes (minimum {brand.min_caption_font_px}px caption, {brand.min_body_font_px}px body)
2. Touch targets (minimum {brand.min_touch_target_px}px on mobile)
3. WCAG contrast (minimum {brand.wcag_contrast_ratio}:1)
4. No horizontal overflow
5. Brand colors ({brand.primary_color}, {brand.secondary_color}, {brand.accent_color})
6. Font family ({brand.font_family})

**Behavioral UX (Phase 2.5 automated findings):**
{behavioral_summary if behavioral_summary else "  No behavioral data provided."}

**Journey Psychology (Phase 3 — YOUR analysis):**
7. Action->Expectation chains: For each CTA/button visible, what does user expect? Does the page deliver?
8. Stranded points: Any place where user completes an action but has no visible next step?
9. Flow breaks: Any place where user is forced off-platform or into a dead end?
10. Output usability: Can users actually USE the results shown (copy, export, act on)?
11. Next-step clarity: After every section, is it obvious what to do next?
12. Journey score: Rate 1-10 how well this page guides a user from entry to goal completion.

**6 Friction Archetypes to watch for:**
1. No Visible Response — "Is it working?"
2. Response Mismatch — "Not what I asked for"
3. Unusable Output — "Now what do I do with this?"
4. User Stranded — "Okay... now what?"
5. User Confused — "I'm lost"
6. UI Contradicts State — "That's wrong"

**Output format (JSON):**
{{
  "issues": [
    {{
      "severity": "critical|major|minor|cosmetic",
      "category": "visual|behavioral|journey",
      "archetype": 1-6 or null,
      "viewport": "mobile|tablet|desktop",
      "page": "/path",
      "description": "...",
      "recommendation": "..."
    }}
  ],
  "journeyAnalysis": {{
    "journeyScore": 1-10,
    "actionExpectationChains": [
      {{"action": "...", "expectation": "...", "delivers": true/false}}
    ],
    "strandedPoints": ["..."],
    "flowBreaks": ["..."]
  }},
  "summary": "2-3 sentence overall assessment"
}}"""


async def analyze_with_vision(
    screenshots: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    behavioral: list[dict[str, Any]],
    config: Any,
) -> dict[str, Any]:
    """Send screenshots + context to Claude Vision via Bedrock."""
    try:
        import boto3
    except ImportError:
        raise ImportError("SCORCH vision requires boto3. Install with: pip install graqle[scorch]")

    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=config.bedrock.region,
    )

    prompt = _build_prompt(metrics, behavioral, config)

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

    for ss in screenshots:
        if ss.get("path") and Path(ss["path"]).exists():
            img_data = Path(ss["path"]).read_bytes()
            img_b64 = base64.b64encode(img_data).decode()
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": img_b64,
                },
            })
            content.append({
                "type": "text",
                "text": f"[Screenshot: {ss['page']} @ {ss['viewport']}]",
            })

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 12000,
        "messages": [{"role": "user", "content": content}],
    })

    logger.info("Calling Claude Vision via Bedrock (%s)", config.bedrock.model_id)

    response = bedrock.invoke_model(
        modelId=config.bedrock.model_id,
        contentType="application/json",
        accept="application/json",
        body=body,
    )

    result = json.loads(response["body"].read())
    text = result["content"][0]["text"]

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]

    try:
        analysis = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Claude Vision returned non-JSON; wrapping as raw text")
        analysis = {"raw_text": text, "issues": [], "journeyAnalysis": {}, "summary": text[:200]}

    return analysis
