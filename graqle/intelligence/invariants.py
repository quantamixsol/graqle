# ──────────────────────────────────────────────────────────────────
# PATENT NOTICE — Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Applications EP26162901.8 and EP26166054.2, owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: legal@quantamix.io
# ──────────────────────────────────────────────────────────────────

"""Compile-Time Invariant Detector — catches data flow bugs at graph level.

Runs after edge resolution in the compile pipeline (Phase 3b → 3c).
Analyzes chunk text across the entire scanned codebase to find invariant
violations: write-without-read, format mismatches, credential inconsistency,
one-way integrations, and hardcoded dynamic values.

Produces CuriosityInsight objects with category=INVARIANT that surface
alongside existing insights in the Studio Intelligence dashboard.

See ADR-114 §Compile-Time Invariant Detector.
"""

# ── graqle:intelligence ──
# module: graqle.intelligence.invariants
# risk: LOW (impact radius: 1 module)
# consumers: compile
# dependencies: __future__, logging, re, collections
# constraints: Must not break compile pipeline — fail gracefully on errors
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from graqle.intelligence.models import (
    CuriosityInsight,
    FileIntelligenceUnit,
    InsightCategory,
)

logger = logging.getLogger("graqle.intelligence.invariants")


# ─── Pattern Definitions ─────────────────────────────────────────────────

# Data store write patterns (language-agnostic)
_WRITE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("env_var", re.compile(r"""(?:os\.environ|process\.env)\s*\[?\s*['"]([\w_]+)['"]\s*\]?\s*=""", re.IGNORECASE)),
    ("localStorage", re.compile(r"""localStorage\.setItem\s*\(\s*['"]([\w._-]+)['"]""", re.IGNORECASE)),
    ("sessionStorage", re.compile(r"""sessionStorage\.setItem\s*\(\s*['"]([\w._-]+)['"]""", re.IGNORECASE)),
    ("cognito_attr", re.compile(r"""(?:AdminUpdateUserAttributes|updateUserAttributes).*?Name['":\s]+['"]([\w:._-]+)['"]""", re.IGNORECASE)),
    ("cognito_group", re.compile(r"""(?:AdminAddUserToGroup|addUserToGroup).*?GroupName['":\s]+['"]([\w._-]+)['"]""", re.IGNORECASE)),
    ("dynamodb_put", re.compile(r"""\.(?:put_item|putItem)\s*\(.*?TableName['":\s]+['"]([\w._-]+)['"]""", re.IGNORECASE | re.DOTALL)),
    ("s3_put", re.compile(r"""\.(?:put_object|putObject|upload)\s*\(.*?(?:Bucket|bucket)['":\s]+['"]([\w._-]+)['"]""", re.IGNORECASE | re.DOTALL)),
    ("state_set", re.compile(r"""(?:setState|set|useStore.*?set)\s*\(\s*\{?\s*(\w+)\s*:""", re.IGNORECASE)),
]

# Data store read patterns (language-agnostic)
_READ_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("env_var", re.compile(r"""(?:os\.environ|process\.env)\.(?:get\s*\(\s*)?['"]([\w_]+)['"]""", re.IGNORECASE)),
    ("localStorage", re.compile(r"""localStorage\.getItem\s*\(\s*['"]([\w._-]+)['"]""", re.IGNORECASE)),
    ("sessionStorage", re.compile(r"""sessionStorage\.getItem\s*\(\s*['"]([\w._-]+)['"]""", re.IGNORECASE)),
    ("cognito_attr", re.compile(r"""(?:AdminGetUser|getUserAttributes|AdminListGroupsForUser)""", re.IGNORECASE)),
    ("cognito_group", re.compile(r"""(?:AdminListGroupsForUser|listGroupsForUser).*?(?:GroupName)?""", re.IGNORECASE)),
    ("dynamodb_get", re.compile(r"""\.(?:get_item|getItem|query|scan)\s*\(.*?TableName['":\s]+['"]([\w._-]+)['"]""", re.IGNORECASE | re.DOTALL)),
    ("s3_get", re.compile(r"""\.(?:get_object|getObject|download)\s*\(.*?(?:Bucket|bucket)['":\s]+['"]([\w._-]+)['"]""", re.IGNORECASE | re.DOTALL)),
    ("state_get", re.compile(r"""(?:useStore|getState)\s*\(.*?\)\s*\.?\s*(\w+)""", re.IGNORECASE)),
]

# Format string patterns — detect the same concept with different representations
_FORMAT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("tier_prefixed", re.compile(r"""['"](graqle-(?:free|pro|team))['"]""")),
    ("tier_bare", re.compile(r"""['"](?<![.-])(free|pro|team)['"](?![-.])\s*(?:===|==|!=|!==|:|\])""")),
    ("tier_const", re.compile(r"""(?:tier|TIER|plan|PLAN)\s*(?:===|==|!=|!==)\s*['"]([\w-]+)['"]""")),
]

# Credential patterns — same SDK client, different auth approaches
_CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("explicit_creds", re.compile(r"""credentials\s*[:=]\s*\{.*?(?:accessKeyId|secretAccessKey)""", re.DOTALL)),
    ("env_creds", re.compile(r"""(?:AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|GRAQLE_S3_ACCESS_KEY)""")),
    ("default_chain", re.compile(r"""(?:new\s+\w+Client|boto3\.client)\s*\([^)]*\)(?!.*credentials)""", re.DOTALL)),
]

# API endpoint patterns — detect endpoints without callers
_API_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("api_route_next", re.compile(r"""export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH)\s*\(""")),
    ("api_route_flask", re.compile(r"""@(?:app|router|blueprint)\.(?:route|get|post|put|delete)\s*\(\s*['"]([\w/{}:-]+)['"]""")),
    ("api_route_fastapi", re.compile(r"""@(?:app|router)\.(?:get|post|put|delete)\s*\(\s*['"]([\w/{}:-]+)['"]""")),
    ("fetch_call", re.compile(r"""(?:fetch|axios\.\w+|requests\.\w+)\s*\(\s*[`'"]([\w/{}:.?&=-]+)[`'"]""")),
]

# Hardcoded value patterns — values that should be dynamic
_HARDCODE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("hardcoded_url", re.compile(r"""['"](https?://(?:localhost|127\.0\.0\.1):\d+[\w/.-]*)['"]""")),
    ("hardcoded_region", re.compile(r"""region\s*[:=]\s*['"]([\w-]+)['"]""")),
    ("hardcoded_table", re.compile(r"""TableName\s*[:=]\s*['"]([\w.-]+)['"]""")),
    ("hardcoded_bucket", re.compile(r"""(?:Bucket|bucket)\s*[:=]\s*['"]([\w.-]+)['"]""")),
]


# ─── Security Patterns ──────────────────────────────────────────────────

# Detector 7: Hardcoded secrets (API keys, passwords, tokens)
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_key", re.compile(r"""(?:AKIA|ASIA)[A-Z0-9]{16}""")),
    ("generic_secret", re.compile(
        r"""(?:api_key|apikey|api_secret|secret_key|auth_token|access_token|private_key|password|passwd|pwd)"""
        r"""\s*[:=]\s*['"]([^'"]{8,})['"]""",
        re.IGNORECASE,
    )),
    ("jwt_token", re.compile(r"""['"]eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}['"]""")),
    ("connection_string", re.compile(
        r"""['"](?:mongodb|postgres|mysql|redis|amqp)://[^'"]{10,}['"]""",
        re.IGNORECASE,
    )),
    ("private_key_block", re.compile(r"""-----BEGIN (?:RSA |EC )?PRIVATE KEY-----""")),
]

# Detector 8: SQL injection risk (string concatenation in queries)
_SQL_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sql_concat", re.compile(
        r"""(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\s+.*?['"]?\s*\+\s*(?:\w+|['"])""",
        re.IGNORECASE,
    )),
    ("sql_fstring", re.compile(
        r"""f['"](?:SELECT|INSERT|UPDATE|DELETE)\s+.*?\{[\w.]+\}""",
        re.IGNORECASE,
    )),
    ("sql_format", re.compile(
        r"""['"](?:SELECT|INSERT|UPDATE|DELETE)\s+.*?(?:%s|%d|\{[0-9]*\})['"]\.format""",
        re.IGNORECASE,
    )),
    ("sql_template_literal", re.compile(
        r"""`(?:SELECT|INSERT|UPDATE|DELETE)\s+.*?\$\{[\w.]+\}`""",
        re.IGNORECASE,
    )),
]

# Detector 9: Missing rate limits (API routes without throttling)
_RATE_LIMIT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("has_rate_limit", re.compile(
        r"""(?:rate_limit|rateLimit|throttle|Throttle|RateLimit|slowDown|express-rate-limit|@ratelimit|limiter)""",
        re.IGNORECASE,
    )),
    ("route_definition", re.compile(
        r"""(?:@(?:app|router|blueprint)\.(?:route|get|post|put|delete|patch)"""
        r"""|export\s+(?:async\s+)?function\s+(?:GET|POST|PUT|DELETE|PATCH))""",
    )),
]

# Detector 10: Open CORS wildcard
_CORS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cors_wildcard", re.compile(
        r"""(?:Access-Control-Allow-Origin|allow_origin|allowOrigin|cors.*origin)"""
        r"""['":\s]*['"]\*['"]""",
        re.IGNORECASE,
    )),
    ("cors_config_wildcard", re.compile(
        r"""(?:AllowOrigins|allow_origins|allowedOrigins)\s*[:=]\s*\[?\s*['"]\*['"]""",
        re.IGNORECASE,
    )),
]

# Detector 11: HTTP in production (non-localhost)
_INSECURE_HTTP_PATTERN = re.compile(
    r"""['"`]http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|::1|\[::1\])[\w.-]+""",
    re.IGNORECASE,
)

# Detector 12: Exposed environment variables (logging secrets)
_EXPOSED_ENV_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("log_env_js", re.compile(
        r"""console\.(?:log|info|debug|warn|error)\s*\(.*?process\.env""",
        re.IGNORECASE,
    )),
    ("log_env_py", re.compile(
        r"""(?:print|logging\.(?:info|debug|warning|error))\s*\(.*?os\.environ""",
        re.IGNORECASE,
    )),
    ("response_env", re.compile(
        r"""(?:res\.(?:json|send)|return\s+\{|jsonify)\s*\(.*?(?:process\.env|os\.environ)""",
        re.IGNORECASE | re.DOTALL,
    )),
    ("stringify_env", re.compile(
        r"""JSON\.stringify\s*\(\s*process\.env""",
        re.IGNORECASE,
    )),
]


# ─── Data Structures ────────────────────────────────────────────────────

class _DataFlowEntry:
    """A detected data flow annotation from chunk text."""

    __slots__ = ("store_type", "key", "module", "file_path", "chunk_text")

    def __init__(self, store_type: str, key: str, module: str, file_path: str, chunk_text: str) -> None:
        self.store_type = store_type
        self.key = key
        self.module = module
        self.file_path = file_path
        self.chunk_text = chunk_text


# ─── Core Detector ───────────────────────────────────────────────────────

def detect_invariants(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Run all invariant detectors across compiled intelligence units.

    This is the main entry point called from compile.py after edge resolution.
    Fails gracefully — returns empty list on any error to avoid breaking
    the compile pipeline.

    Args:
        all_units: All FileIntelligenceUnit objects from the streaming scan.

    Returns:
        List of CuriosityInsight with category=INVARIANT.
    """
    try:
        insights: list[CuriosityInsight] = []

        # Extract all chunk text across all units
        writes, reads = _extract_data_flows(all_units)

        # Detector 1: Write-without-read
        insights.extend(_detect_write_without_read(writes, reads))

        # Detector 2: Read-without-write
        insights.extend(_detect_read_without_write(writes, reads))

        # Detector 3: Format mismatch
        insights.extend(_detect_format_mismatch(all_units))

        # Detector 4: Credential inconsistency
        insights.extend(_detect_credential_inconsistency(all_units))

        # Detector 5: One-way integration (API without caller)
        insights.extend(_detect_one_way_integration(all_units))

        # Detector 6: Hardcoded dynamic values
        insights.extend(_detect_hardcoded_dynamic(all_units))

        # ── Security Detectors ──────────────────────────────────────

        # Detector 7: Hardcoded secrets
        insights.extend(_detect_hardcoded_secrets(all_units))

        # Detector 8: SQL injection risk
        insights.extend(_detect_sql_injection_risk(all_units))

        # Detector 9: Missing rate limits
        insights.extend(_detect_missing_rate_limits(all_units))

        # Detector 10: Open CORS wildcard
        insights.extend(_detect_open_cors(all_units))

        # Detector 11: HTTP in production
        insights.extend(_detect_insecure_http(all_units))

        # Detector 12: Exposed environment variables
        insights.extend(_detect_exposed_env_vars(all_units))

        logger.info("Invariant detector found %d violations", len(insights))
        return insights

    except Exception:
        logger.warning("Invariant detector failed gracefully", exc_info=True)
        return []


# ─── Data Flow Extraction ────────────────────────────────────────────────

def _extract_data_flows(
    all_units: list[FileIntelligenceUnit],
) -> tuple[dict[str, list[_DataFlowEntry]], dict[str, list[_DataFlowEntry]]]:
    """Extract write and read annotations from all chunk text.

    Returns two dicts keyed by "{store_type}:{key}" with lists of entries.
    """
    writes: dict[str, list[_DataFlowEntry]] = defaultdict(list)
    reads: dict[str, list[_DataFlowEntry]] = defaultdict(list)

    for unit in all_units:
        module = unit.module_packet.module
        file_path = unit.file_path

        for node in unit.nodes:
            for chunk in node.chunks:
                text = chunk.get("text", "") or chunk.get("content", "")
                if not text:
                    continue

                # Detect writes
                for store_type, pattern in _WRITE_PATTERNS:
                    for match in pattern.finditer(text):
                        key = match.group(1) if match.lastindex else store_type
                        flow_key = f"{store_type}:{key}"
                        writes[flow_key].append(
                            _DataFlowEntry(store_type, key, module, file_path, text[:200])
                        )

                # Detect reads
                for store_type, pattern in _READ_PATTERNS:
                    for match in pattern.finditer(text):
                        key = match.group(1) if match.lastindex else store_type
                        flow_key = f"{store_type}:{key}"
                        reads[flow_key].append(
                            _DataFlowEntry(store_type, key, module, file_path, text[:200])
                        )

    return writes, reads


# ─── Detector Implementations ────────────────────────────────────────────

def _detect_write_without_read(
    writes: dict[str, list[_DataFlowEntry]],
    reads: dict[str, list[_DataFlowEntry]],
) -> list[CuriosityInsight]:
    """Detect data stores that are written to but never read."""
    insights: list[CuriosityInsight] = []

    for flow_key, write_entries in writes.items():
        if flow_key not in reads:
            # Aggregate by module
            modules = {e.module for e in write_entries}
            store_type, key = flow_key.split(":", 1)
            first = write_entries[0]

            insights.append(CuriosityInsight(
                category=InsightCategory.INVARIANT,
                module=first.module,
                message=f"Write-without-read: {store_type} '{key}' is written in {', '.join(sorted(modules))} but never read back",
                metric=f"{len(write_entries)} writes, 0 reads",
                severity="warn",
            ))

    return insights


def _detect_read_without_write(
    writes: dict[str, list[_DataFlowEntry]],
    reads: dict[str, list[_DataFlowEntry]],
) -> list[CuriosityInsight]:
    """Detect data stores that are read from but never written."""
    insights: list[CuriosityInsight] = []

    # Skip env vars and common config reads (they're set externally)
    skip_types = {"env_var", "cognito_attr", "cognito_group"}

    for flow_key, read_entries in reads.items():
        store_type, key = flow_key.split(":", 1)
        if store_type in skip_types:
            continue
        if flow_key not in writes:
            modules = {e.module for e in read_entries}
            first = read_entries[0]

            insights.append(CuriosityInsight(
                category=InsightCategory.INVARIANT,
                module=first.module,
                message=f"Read-without-write: {store_type} '{key}' is read in {', '.join(sorted(modules))} but never written",
                metric=f"0 writes, {len(read_entries)} reads",
                severity="warn",
            ))

    return insights


def _detect_format_mismatch(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect the same concept represented in different string formats.

    E.g., 'graqle-free' vs 'free' for tier names.
    """
    insights: list[CuriosityInsight] = []

    # Collect all tier format occurrences
    tier_formats: dict[str, list[tuple[str, str]]] = defaultdict(list)  # format → [(module, match)]

    for unit in all_units:
        module = unit.module_packet.module
        for node in unit.nodes:
            for chunk in node.chunks:
                text = chunk.get("text", "") or chunk.get("content", "")
                if not text:
                    continue

                for fmt_name, pattern in _FORMAT_PATTERNS:
                    for match in pattern.finditer(text):
                        value = match.group(1)
                        tier_formats[fmt_name].append((module, value))

    # Check for mixed prefixed/bare tier usage
    prefixed = tier_formats.get("tier_prefixed", [])
    bare = tier_formats.get("tier_bare", [])

    if prefixed and bare:
        prefixed_modules = {m for m, _ in prefixed}
        bare_modules = {m for m, _ in bare}
        prefixed_values = {v for _, v in prefixed}
        bare_values = {v for _, v in bare}

        insights.append(CuriosityInsight(
            category=InsightCategory.INVARIANT,
            module=next(iter(bare_modules)),
            message=f"Format mismatch: tier uses both prefixed ({', '.join(sorted(prefixed_values))}) and bare ({', '.join(sorted(bare_values))}) formats across modules",
            metric=f"{len(prefixed_modules)} prefixed, {len(bare_modules)} bare",
            severity="warn",
        ))

    return insights


def _detect_credential_inconsistency(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect modules using different credential approaches for the same SDK."""
    insights: list[CuriosityInsight] = []

    # Track credential approach per module
    module_cred_approach: dict[str, set[str]] = defaultdict(set)

    for unit in all_units:
        module = unit.module_packet.module
        for node in unit.nodes:
            for chunk in node.chunks:
                text = chunk.get("text", "") or chunk.get("content", "")
                if not text:
                    continue

                for cred_type, pattern in _CREDENTIAL_PATTERNS:
                    if pattern.search(text):
                        module_cred_approach[module].add(cred_type)

    # Find modules with mixed approaches
    for module, approaches in module_cred_approach.items():
        if len(approaches) > 1:
            insights.append(CuriosityInsight(
                category=InsightCategory.INVARIANT,
                module=module,
                message=f"Credential inconsistency: module uses {', '.join(sorted(approaches))} — mixed credential patterns may cause auth failures",
                metric=f"{len(approaches)} approaches",
                severity="warn",
            ))

    return insights


def _detect_one_way_integration(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect API endpoints that have no corresponding fetch/call."""
    insights: list[CuriosityInsight] = []

    # Collect all defined routes and all fetch calls
    defined_routes: dict[str, str] = {}  # route_path → module
    called_routes: set[str] = set()

    for unit in all_units:
        module = unit.module_packet.module
        for node in unit.nodes:
            for chunk in node.chunks:
                text = chunk.get("text", "") or chunk.get("content", "")
                if not text:
                    continue

                # Detect route definitions
                for route_type, pattern in _API_PATTERNS:
                    if route_type in ("api_route_flask", "api_route_fastapi"):
                        for match in pattern.finditer(text):
                            route_path = match.group(1) if match.lastindex else ""
                            if route_path:
                                defined_routes[route_path] = module
                    elif route_type == "fetch_call":
                        for match in pattern.finditer(text):
                            url = match.group(1) if match.lastindex else ""
                            if url:
                                # Normalize: extract path from URL
                                path = url.split("?")[0]
                                if path.startswith("/"):
                                    called_routes.add(path)

    # Find routes with no caller
    for route_path, module in defined_routes.items():
        # Normalize route path for comparison
        normalized = re.sub(r"\{[^}]+\}", "*", route_path)
        has_caller = any(
            _routes_match(normalized, called)
            for called in called_routes
        )
        if not has_caller:
            insights.append(CuriosityInsight(
                category=InsightCategory.INVARIANT,
                module=module,
                message=f"One-way integration: route '{route_path}' is defined but no fetch/call detected in scanned code",
                metric="0 callers",
                severity="info",
            ))

    return insights


def _routes_match(defined: str, called: str) -> bool:
    """Check if a defined route pattern matches a called URL path."""
    # Simple matching: replace wildcards with regex
    pattern = re.escape(defined).replace(r"\*", r"[^/]+")
    return bool(re.match(f"^{pattern}$", called))


def _detect_hardcoded_dynamic(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect hardcoded values where a dynamic/env-var source exists."""
    insights: list[CuriosityInsight] = []

    # Collect hardcoded values and env var reads
    hardcoded: dict[str, list[tuple[str, str]]] = defaultdict(list)  # type → [(module, value)]
    env_configured: set[str] = set()  # types that have env var config

    for unit in all_units:
        module = unit.module_packet.module
        for node in unit.nodes:
            for chunk in node.chunks:
                text = chunk.get("text", "") or chunk.get("content", "")
                if not text:
                    continue

                # Check for hardcoded values
                for hc_type, pattern in _HARDCODE_PATTERNS:
                    for match in pattern.finditer(text):
                        value = match.group(1)
                        hardcoded[hc_type].append((module, value))

                # Check if env vars exist for these types
                if re.search(r"(?:os\.environ|process\.env).*(?:REGION|AWS_REGION|AWS_DEFAULT_REGION)", text, re.IGNORECASE):
                    env_configured.add("hardcoded_region")
                if re.search(r"(?:os\.environ|process\.env).*(?:TABLE|DYNAMODB)", text, re.IGNORECASE):
                    env_configured.add("hardcoded_table")
                if re.search(r"(?:os\.environ|process\.env).*(?:BUCKET|S3)", text, re.IGNORECASE):
                    env_configured.add("hardcoded_bucket")

    # Flag hardcoded values where env vars exist
    for hc_type, entries in hardcoded.items():
        if hc_type in env_configured:
            # Group by value
            values: dict[str, set[str]] = defaultdict(set)
            for module, value in entries:
                values[value].add(module)

            for value, modules in values.items():
                if len(modules) >= 2:  # Only flag if same hardcode appears in 2+ modules
                    insights.append(CuriosityInsight(
                        category=InsightCategory.INVARIANT,
                        module=next(iter(sorted(modules))),
                        message=f"Hardcoded dynamic value: '{value}' is hardcoded in {len(modules)} modules but env var config exists elsewhere",
                        metric=f"{len(modules)} modules",
                        severity="info",
                    ))

    return insights


# ─── Security Detector Implementations ───────────────────────────────────

def _iter_chunk_texts(
    all_units: list[FileIntelligenceUnit],
) -> list[tuple[str, str, str]]:
    """Return (module, file_path, chunk_text) for every chunk across all units."""
    results: list[tuple[str, str, str]] = []
    for unit in all_units:
        module = unit.module_packet.module
        file_path = unit.file_path
        for node in unit.nodes:
            for chunk in node.chunks:
                text = chunk.get("text", "") or chunk.get("content", "")
                if text:
                    results.append((module, file_path, text))
    return results


def _is_test_file(file_path: str) -> bool:
    """Check if a file path looks like a test file."""
    return "/test" in file_path or "test_" in file_path or "_test." in file_path


def _detect_hardcoded_secrets(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect hardcoded secrets: API keys, passwords, tokens, connection strings."""
    insights: list[CuriosityInsight] = []
    seen: set[str] = set()

    for module, file_path, text in _iter_chunk_texts(all_units):
        if _is_test_file(file_path):
            continue

        for secret_type, pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                dedup_key = f"{module}:{secret_type}"
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    insights.append(CuriosityInsight(
                        category=InsightCategory.INVARIANT,
                        module=module,
                        message=f"Hardcoded secret: possible {secret_type} found in source — use environment variables or secret manager",
                        metric=secret_type,
                        severity="critical",
                    ))

    return insights


def _detect_sql_injection_risk(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect SQL injection risk from string concatenation/interpolation in queries."""
    insights: list[CuriosityInsight] = []
    seen: set[str] = set()

    for module, file_path, text in _iter_chunk_texts(all_units):
        if _is_test_file(file_path):
            continue

        for inj_type, pattern in _SQL_INJECTION_PATTERNS:
            if pattern.search(text):
                dedup_key = f"{module}:{inj_type}"
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    insights.append(CuriosityInsight(
                        category=InsightCategory.INVARIANT,
                        module=module,
                        message=f"SQL injection risk: {inj_type} — use parameterized queries instead of string interpolation",
                        metric=inj_type,
                        severity="warn",
                    ))

    return insights


def _detect_missing_rate_limits(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect API route modules that define routes but have no rate limiting."""
    insights: list[CuriosityInsight] = []
    module_has_routes: dict[str, bool] = {}
    module_has_rate_limit: dict[str, bool] = {}

    for module, file_path, text in _iter_chunk_texts(all_units):
        if _is_test_file(file_path):
            continue

        for pat_name, pattern in _RATE_LIMIT_PATTERNS:
            if pattern.search(text):
                if pat_name == "route_definition":
                    module_has_routes[module] = True
                elif pat_name == "has_rate_limit":
                    module_has_rate_limit[module] = True

    for module in module_has_routes:
        if not module_has_rate_limit.get(module, False):
            insights.append(CuriosityInsight(
                category=InsightCategory.INVARIANT,
                module=module,
                message="Missing rate limit: module defines API routes but no rate limiting detected — consider adding throttling",
                metric="0 rate limits",
                severity="info",
            ))

    return insights


def _detect_open_cors(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect wildcard CORS configuration (Access-Control-Allow-Origin: *)."""
    insights: list[CuriosityInsight] = []
    seen: set[str] = set()

    for module, file_path, text in _iter_chunk_texts(all_units):
        if _is_test_file(file_path):
            continue

        for _cors_type, pattern in _CORS_PATTERNS:
            if pattern.search(text):
                if module not in seen:
                    seen.add(module)
                    insights.append(CuriosityInsight(
                        category=InsightCategory.INVARIANT,
                        module=module,
                        message="Open CORS wildcard: allows all origins — restrict to specific domains in production",
                        metric="wildcard origin",
                        severity="warn",
                    ))

    return insights


def _detect_insecure_http(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect HTTP URLs pointing to non-localhost hosts (should be HTTPS)."""
    insights: list[CuriosityInsight] = []
    seen: set[str] = set()

    for module, file_path, text in _iter_chunk_texts(all_units):
        if _is_test_file(file_path):
            continue

        for url in _INSECURE_HTTP_PATTERN.findall(text):
            dedup_key = f"{module}:{url[:50]}"
            if dedup_key not in seen:
                seen.add(dedup_key)
                insights.append(CuriosityInsight(
                    category=InsightCategory.INVARIANT,
                    module=module,
                    message=f"Insecure HTTP: '{url}' uses HTTP instead of HTTPS — data in cleartext",
                    metric="http",
                    severity="warn",
                ))

    return insights


def _detect_exposed_env_vars(
    all_units: list[FileIntelligenceUnit],
) -> list[CuriosityInsight]:
    """Detect environment variables being logged or exposed in responses."""
    insights: list[CuriosityInsight] = []
    seen: set[str] = set()

    for module, file_path, text in _iter_chunk_texts(all_units):
        if _is_test_file(file_path):
            continue

        for exp_type, pattern in _EXPOSED_ENV_PATTERNS:
            if pattern.search(text):
                dedup_key = f"{module}:{exp_type}"
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    insights.append(CuriosityInsight(
                        category=InsightCategory.INVARIANT,
                        module=module,
                        message=f"Exposed env vars: {exp_type} — environment variables may leak via logs or responses",
                        metric=exp_type,
                        severity="critical",
                    ))

    return insights
