"""Graqle Markdown KG Parser — extract structured entities from markdown KG files.

Parses real-world markdown knowledge graph files (tables, headers, bullet lists,
key-value pairs, code blocks) and produces ExtractedEntity objects with inferred
types, metadata, and edge references.

Handles:
  - Inconsistent table column counts, bold/italic in cells
  - Nested bullet lists
  - Windows paths in metadata
  - UTF-8 characters (arrows, em-dashes, etc.)
  - Section-context-aware entity type inference
"""

# ── graqle:intelligence ──
# module: graqle.ontology.markdown_parser
# risk: HIGH (impact radius: 1 modules)
# consumers: __init__
# dependencies: __future__, re, dataclasses, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ExtractedEntity:
    """A single entity extracted from a markdown file."""
    node_type: str
    id: str
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""
    source_line: int = 0
    confidence: float = 0.8

    def to_node_dict(self) -> dict[str, Any]:
        """Convert to networkx-compatible node dict."""
        d: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "type": self.node_type,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "confidence": self.confidence,
        }
        for k, v in self.metadata.items():
            if k not in d:
                d[k] = v
        return d


@dataclass
class ExtractedEdge:
    """An edge inferred from the parsed content."""
    source_id: str
    target_id: str
    relationship: str
    confidence: float = 0.7
    source_file: str = ""
    source_line: int = 0


@dataclass
class ParseResult:
    """Result of parsing a single markdown file."""
    entities: list[ExtractedEntity] = field(default_factory=list)
    edges: list[ExtractedEdge] = field(default_factory=list)
    source_file: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Section context tracker
# ---------------------------------------------------------------------------

@dataclass
class SectionContext:
    """Tracks the current heading hierarchy while parsing."""
    h1: str = ""
    h2: str = ""
    h3: str = ""
    h4: str = ""

    def update(self, level: int, text: str) -> None:
        if level == 1:
            self.h1 = text
            self.h2 = self.h3 = self.h4 = ""
        elif level == 2:
            self.h2 = text
            self.h3 = self.h4 = ""
        elif level == 3:
            self.h3 = text
            self.h4 = ""
        elif level == 4:
            self.h4 = text

    @property
    def full_path(self) -> str:
        parts = [p for p in [self.h1, self.h2, self.h3, self.h4] if p]
        return " > ".join(parts)

    @property
    def deepest(self) -> str:
        for h in [self.h4, self.h3, self.h2, self.h1]:
            if h:
                return h
        return ""


# ---------------------------------------------------------------------------
# Section-to-type mapping
# ---------------------------------------------------------------------------

# Each rule: (pattern_in_section_text, node_type, confidence)
# Checked against h2 and h3 headers (case-insensitive)
SECTION_TYPE_RULES: list[tuple[str, str, float]] = [
    # Services / Lambda
    (r"lambda\s*nodes?", "SERVICE", 0.95),
    (r"lambda\s*functions?", "SERVICE", 0.95),

    # Mistakes
    (r"mistake\s*nodes?", "MISTAKE", 0.95),
    (r"mistakes?\s*\(", "MISTAKE", 0.90),

    # Lessons (distilled)
    (r"\[critical\]", "LESSON", 0.95),
    (r"\[high\]", "LESSON", 0.95),
    (r"\[medium\]", "LESSON", 0.90),
    (r"recently\s+added", "LESSON", 0.85),

    # EnvVar requirements
    (r"envvar\s*requirements?", "ENVVAR", 0.90),

    # Invocation chain
    (r"invocation\s*chain", "_INVOCATION", 0.90),

    # Shared modules
    (r"shared\s*modules?", "MODULE", 0.90),

    # Critical parameters
    (r"critical\s*parameters?", "_CRITICAL_PARAM", 0.90),

    # Neo4j schema
    (r"neo4j\s*schema", "NEO4J_SCHEMA", 0.90),

    # Infrastructure
    (r"infrastructure\s*nodes?", "INFRA", 0.95),
    (r"infrastructure", "INFRA", 0.85),

    # Open issues
    (r"open\s*issues?", "OPEN_ISSUE", 0.90),

    # Test suites
    (r"test\s*suites?", "TEST_SUITE", 0.90),

    # SDK Package
    (r"sdk\s*package", "PACKAGE", 0.90),
    (r"tamr\+?\s*lite", "PACKAGE", 0.90),

    # Pipeline
    (r"three.stage\s*pipeline", "MODULE", 0.85),
    (r"processing\s*pipeline", "PIPELINE_STEP", 0.85),
    (r"document\s*processing\s*pipeline", "PIPELINE_STEP", 0.85),

    # Papers
    (r"research\s*papers?", "PAPER", 0.90),
    (r"paper\s*versions?", "PAPER", 0.90),

    # Publication pipeline
    (r"publication\s*pipeline", "PUBLICATION", 0.90),

    # Benchmarks
    (r"benchmarks?$", "BENCHMARK", 0.85),

    # IP / Patent
    (r"ip\s*status", "IP_ASSET", 0.90),
    (r"ip\s*/\s*patent", "IP_ASSET", 0.90),
    (r"patent\s*filing", "PATENT", 0.90),
    (r"patent\s*extension", "PATENT", 0.85),

    # Moat modules
    (r"academic\s*moat", "MOAT_MODULE", 0.90),
    (r"module\s*status", "MOAT_MODULE", 0.85),
    (r"innovation\s*modules?", "MOAT_MODULE", 0.90),

    # Open source strategy
    (r"open\s*source\s*strategy", "IP_ASSET", 0.85),

    # Competitor
    (r"competitor", "COMPETITOR", 0.85),

    # Brand
    (r"brand\s*identity", "BRAND_ASSET", 0.90),

    # Channel
    (r"channel\s*strategy", "CHANNEL", 0.90),

    # Personas
    (r"customer\s*personas?", "PERSONA", 0.90),

    # Sales funnel / campaign
    (r"sales\s*funnel", "CAMPAIGN", 0.80),

    # Stripe
    (r"stripe\s*(?:billing|products?)", "STRIPE_PRODUCT", 0.90),

    # Frontend
    (r"frontend\s*status", "FRONTEND_COMPONENT", 0.85),
    (r"plan\s*gating", "FRONTEND_COMPONENT", 0.80),

    # Dependency graph
    (r"dependency\s*graph", "_DEPENDENCY", 0.85),

    # Domains
    (r"domain\s*architecture", "DOMAIN", 0.85),

    # ADRs
    (r"key\s*(?:engineering\s*)?adrs?", "ADR", 0.85),

    # Zenodo / SSRN / OSF records
    (r"zenodo\s*record", "PUBLICATION", 0.90),
    (r"ssrn\s*record", "PUBLICATION", 0.90),
    (r"osf\s*/\s*law\s*archive", "PUBLICATION", 0.90),

    # Deployment checklist, priority actions — skip
    (r"deployment\s*checklist", "_SKIP", 0.95),
    (r"priority\s*actions?", "_SKIP", 0.95),
    (r"how\s*to\s*use", "_SKIP", 0.95),
    (r"completed$", "_SKIP", 0.95),
    (r"parked", "_SKIP", 0.90),

    # MCP Dev Server
    (r"mcp\s*dev\s*server", "MODULE", 0.80),

    # Key innovations
    (r"key\s*innovations?", "INNOVATION", 0.85),

    # Licensing
    (r"licensing", "MODULE", 0.80),

    # GPU infrastructure
    (r"gpu\s*infrastructure", "INFRA", 0.80),
]


def _infer_section_type(section_text: str) -> tuple[str, float]:
    """Infer the node type from a section heading text.

    Returns (node_type, confidence). Returns ("_UNKNOWN", 0.0) if no match.
    """
    lower = section_text.lower().strip()
    for pattern, node_type, conf in SECTION_TYPE_RULES:
        if re.search(pattern, lower):
            return node_type, conf
    return "_UNKNOWN", 0.0


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    """Remove bold, italic, code, and link markdown."""
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # **bold**
    text = re.sub(r"\*([^*]+)\*", r"\1", text)       # *italic*
    text = re.sub(r"`([^`]+)`", r"\1", text)         # `code`
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [text](url)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)       # ~~strikethrough~~
    return text.strip()


def _clean_cell(cell: str) -> str:
    """Clean a markdown table cell."""
    cell = cell.strip()
    cell = _strip_markdown(cell)
    # Remove leading/trailing pipes left over
    cell = cell.strip("|").strip()
    return cell


def _normalize_id(raw: str) -> str:
    """Normalize a raw string into a valid node id."""
    # Lowercase, replace spaces/special chars with underscores
    s = raw.lower().strip()
    s = re.sub(r"[^a-z0-9_.\-]", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    return s


def _is_separator_row(row: str) -> bool:
    """Check if a table row is a header separator (|----|-----|)."""
    cells = row.strip().strip("|").split("|")
    return all(re.match(r"^\s*:?-+:?\s*$", c) for c in cells if c.strip())


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def extract_tables(content: str) -> list[dict[str, Any]]:
    """Extract all markdown tables from content.

    Returns a list of dicts, each with:
      - 'headers': list of column header strings
      - 'rows': list of dicts mapping header -> cell value
      - 'start_line': 1-based line number of the header row
    """
    lines = content.splitlines()
    tables: list[dict[str, Any]] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        # Detect table header: must contain | and the next line must be separator
        if "|" in line and i + 1 < len(lines) and _is_separator_row(lines[i + 1]):
            # Extract headers
            headers = [_clean_cell(c) for c in line.split("|") if c.strip()]
            start_line = i + 1  # 1-based

            # Skip separator
            i += 2

            # Extract data rows
            rows: list[dict[str, str]] = []
            while i < len(lines):
                row_line = lines[i].strip()
                if not row_line or "|" not in row_line:
                    break
                # Check it's not another separator
                if _is_separator_row(row_line):
                    i += 1
                    continue

                cells = [_clean_cell(c) for c in row_line.split("|") if c.strip() or row_line.count("|") > 1]
                # Re-split more carefully for edge cases
                raw_cells = row_line.strip().strip("|").split("|")
                cells = [_clean_cell(c) for c in raw_cells]

                # Build row dict, handling mismatched column counts
                row_dict: dict[str, str] = {}
                for j, header in enumerate(headers):
                    if j < len(cells):
                        row_dict[header] = cells[j]
                    else:
                        row_dict[header] = ""

                rows.append(row_dict)
                i += 1

            if rows:
                tables.append({
                    "headers": headers,
                    "rows": rows,
                    "start_line": start_line,
                })
        else:
            i += 1

    return tables


# ---------------------------------------------------------------------------
# Lesson line parser
# ---------------------------------------------------------------------------

# Pattern: - LESSON-NNN | domain | description (hits: N) | Source: ADR-XXX
_LESSON_PATTERN = re.compile(
    r"^-\s+(?P<id>LESSON-\d+)\s*\|\s*(?P<domain>\w+)\s*\|\s*"
    r"(?P<description>.+?)\s*\(hits:\s*(?P<hits>\d+)\)\s*"
    r"(?:\|\s*Source:\s*(?P<source>.+))?\s*$"
)


def _parse_lesson_line(line: str, severity: str, line_num: int,
                       source_file: str) -> ExtractedEntity | None:
    """Parse a single LESSON line into an ExtractedEntity."""
    m = _LESSON_PATTERN.match(line.strip())
    if not m:
        return None

    lesson_id = m.group("id")
    domain = m.group("domain").strip()
    description = _strip_markdown(m.group("description").strip())
    hits = int(m.group("hits"))
    source = m.group("source").strip() if m.group("source") else ""

    return ExtractedEntity(
        node_type="LESSON",
        id=f"lesson::{_normalize_id(lesson_id)}",
        label=f"{lesson_id}: {description[:80]}",
        metadata={
            "lesson_id": lesson_id,
            "severity": severity,
            "domain": domain,
            "description": description,
            "hit_count": hits,
            "source_adr": source,
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.95,
    )


# ---------------------------------------------------------------------------
# Mistake table row parser
# ---------------------------------------------------------------------------

def _parse_mistake_row(row: dict[str, str], line_num: int,
                       source_file: str) -> ExtractedEntity | None:
    """Parse a MISTAKE table row."""
    raw_id = row.get("ID", "").strip()
    if not raw_id or not re.match(r"^M\d+", raw_id):
        return None

    label = row.get("Mistake", row.get("label", "")).strip()
    severity = row.get("Severity", "").strip()
    component = row.get("Component", "").strip()
    root_cause = row.get("Root Cause", "").strip()
    fix = row.get("Fix", "").strip()
    date = row.get("Date", "").strip()

    return ExtractedEntity(
        node_type="MISTAKE",
        id=f"mistake::{_normalize_id(raw_id)}",
        label=f"{raw_id}: {label[:80]}",
        metadata={
            "mistake_id": raw_id,
            "component": component,
            "root_cause": root_cause,
            "severity": severity,
            "fix": fix,
            "date": date,
            "status": "FIXED" if "FIXED" in (row.get("Date", "") + fix) else "OPEN",
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.95,
    )


# ---------------------------------------------------------------------------
# Service table row parser
# ---------------------------------------------------------------------------

def _parse_service_row(row: dict[str, str], line_num: int,
                       source_file: str) -> ExtractedEntity | None:
    """Parse a Lambda/SERVICE table row."""
    raw_id = row.get("ID", "").strip()
    name = row.get("Name", "").strip()
    if not raw_id or not name:
        return None

    handler = row.get("Handler", "").strip()
    timeout = row.get("Timeout", "").strip()
    memory = row.get("Memory", "").strip()
    fn_url = row.get("FunctionURL", row.get("Function URL", "")).strip()
    runtime = row.get("Runtime", "").strip()

    return ExtractedEntity(
        node_type="SERVICE",
        id=f"svc::{_normalize_id(raw_id)}",
        label=name,
        metadata={
            "service_id": raw_id,
            "handler": handler,
            "timeout": timeout,
            "memory_mb": memory,
            "function_url": fn_url if fn_url and fn_url != "\u2014" else "",
            "runtime": runtime,
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.95,
    )


# ---------------------------------------------------------------------------
# Generic table row parsers for other types
# ---------------------------------------------------------------------------

def _parse_infra_row(row: dict[str, str], line_num: int,
                     source_file: str) -> ExtractedEntity | None:
    raw_id = row.get("ID", "").strip()
    infra_type = row.get("Type", "").strip()
    endpoint = row.get("Endpoint", row.get("Endpoint/ID", "")).strip()
    region = row.get("Region", "").strip()
    if not raw_id:
        return None
    return ExtractedEntity(
        node_type="INFRA",
        id=f"infra::{_normalize_id(raw_id)}",
        label=f"{infra_type}: {endpoint[:60]}" if infra_type else endpoint[:80],
        metadata={
            "infra_id": raw_id,
            "infra_type": infra_type,
            "endpoint": endpoint,
            "region": region,
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.90,
    )


def _parse_open_issue_row(row: dict[str, str], line_num: int,
                          source_file: str) -> ExtractedEntity | None:
    raw_id = row.get("ID", "").strip()
    issue = row.get("Issue", "").strip()
    if not raw_id:
        return None
    priority = row.get("Priority", "").strip()
    component = row.get("Component", "").strip()
    proposed_fix = row.get("Proposed Fix", "").strip()
    is_closed = issue.startswith("~~") or "CLOSED" in issue.upper()
    return ExtractedEntity(
        node_type="OPEN_ISSUE",
        id=f"issue::{_normalize_id(raw_id)}",
        label=f"{raw_id}: {_strip_markdown(issue)[:80]}",
        metadata={
            "issue_id": raw_id,
            "priority": priority,
            "component": component,
            "proposed_fix": proposed_fix,
            "status": "CLOSED" if is_closed else "OPEN",
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.90,
    )


def _parse_test_suite_row(row: dict[str, str], line_num: int,
                          source_file: str) -> ExtractedEntity | None:
    suite = row.get("Suite", "").strip()
    count = row.get("Count", "").strip()
    status = row.get("Status", "").strip()
    runner = row.get("Runner", "").strip()
    what = row.get("What It Tests", "").strip()
    if not suite:
        return None
    return ExtractedEntity(
        node_type="TEST_SUITE",
        id=f"test::{_normalize_id(suite)}",
        label=suite,
        metadata={
            "count": count,
            "status": status,
            "runner": runner,
            "description": what,
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.90,
    )


def _parse_neo4j_schema_row(row: dict[str, str], line_num: int,
                            source_file: str) -> ExtractedEntity | None:
    label_val = row.get("Label", "").strip()
    subgraph = row.get("Subgraph", "").strip()
    queried_by = row.get("Queried By", "").strip()
    isolation = row.get("Isolation", "").strip()
    if not label_val:
        return None
    return ExtractedEntity(
        node_type="NEO4J_SCHEMA",
        id=f"neo4j::{_normalize_id(label_val)}",
        label=label_val,
        metadata={
            "subgraph": subgraph,
            "queried_by": queried_by,
            "isolation": isolation,
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.90,
    )


def _parse_moat_module_row(row: dict[str, str], line_num: int,
                           source_file: str) -> ExtractedEntity | None:
    raw_id = row.get("ID", "").strip()
    module = row.get("Module", "").strip()
    location = row.get("Location", "").strip()
    status = row.get("Status", "").strip()
    claims = row.get("Patent Claims", "").strip()
    if not raw_id or not module:
        return None
    return ExtractedEntity(
        node_type="MOAT_MODULE",
        id=f"moat::{_normalize_id(raw_id)}",
        label=f"{raw_id}: {module}",
        metadata={
            "moat_id": raw_id,
            "module": module,
            "location": location,
            "status": status,
            "patent_claims": claims,
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.90,
    )


def _parse_publication_row(row: dict[str, str], line_num: int,
                           source_file: str) -> ExtractedEntity | None:
    venue = row.get("Venue", "").strip()
    deadline = row.get("Deadline", "").strip()
    status = row.get("Status", "").strip()
    doi = row.get("ID/DOI", row.get("DOI", "")).strip()
    if not venue:
        return None
    return ExtractedEntity(
        node_type="PUBLICATION",
        id=f"pub::{_normalize_id(venue)}",
        label=_strip_markdown(venue),
        metadata={
            "venue": _strip_markdown(venue),
            "deadline": deadline,
            "status": _strip_markdown(status),
            "doi": doi,
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.85,
    )


def _parse_paper_row(row: dict[str, str], line_num: int,
                     source_file: str) -> ExtractedEntity | None:
    version = row.get("Version", "").strip()
    file_path = row.get("File", "").strip()
    status = row.get("Status", "").strip()
    if not version:
        return None
    return ExtractedEntity(
        node_type="PAPER",
        id=f"paper::{_normalize_id(version)}",
        label=f"Paper {_strip_markdown(version)}",
        metadata={
            "version": _strip_markdown(version),
            "file_path": _strip_markdown(file_path),
            "status": _strip_markdown(status),
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.85,
    )


def _parse_ip_asset_row(row: dict[str, str], line_num: int,
                        source_file: str) -> ExtractedEntity | None:
    asset = row.get("Asset", "").strip()
    protection = row.get("Protection", row.get("License", "")).strip()
    status = row.get("Status", row.get("Moat Protection", "")).strip()
    if not asset:
        return None
    return ExtractedEntity(
        node_type="IP_ASSET",
        id=f"ip::{_normalize_id(asset)}",
        label=_strip_markdown(asset),
        metadata={
            "protection_type": _strip_markdown(protection),
            "status": _strip_markdown(status),
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.85,
    )


def _parse_benchmark_row(row: dict[str, str], line_num: int,
                         source_file: str) -> ExtractedEntity | None:
    asset = row.get("Asset", row.get("Dataset", "")).strip()
    file_path = row.get("File", "").strip()
    status = row.get("Status", "").strip()
    questions = row.get("Questions", "").strip()
    if not asset:
        return None
    return ExtractedEntity(
        node_type="BENCHMARK",
        id=f"bench::{_normalize_id(asset)}",
        label=_strip_markdown(asset),
        metadata={
            "file_path": _strip_markdown(file_path),
            "status": _strip_markdown(status),
            "question_count": questions,
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.85,
    )


def _parse_channel_row(row: dict[str, str], line_num: int,
                       source_file: str) -> ExtractedEntity | None:
    channel = row.get("Channel", "").strip()
    role = row.get("Role", "").strip()
    frequency = row.get("Frequency", "").strip()
    status = row.get("Status", "").strip()
    if not channel:
        return None
    return ExtractedEntity(
        node_type="CHANNEL",
        id=f"channel::{_normalize_id(channel)}",
        label=channel,
        metadata={"role": role, "frequency": frequency, "status": status},
        source_file=source_file,
        source_line=line_num,
        confidence=0.85,
    )


def _parse_persona_row(row: dict[str, str], line_num: int,
                       source_file: str) -> ExtractedEntity | None:
    persona = row.get("Persona", "").strip()
    priority = row.get("Priority", "").strip()
    needs = row.get("Needs", "").strip()
    if not persona:
        return None
    return ExtractedEntity(
        node_type="PERSONA",
        id=f"persona::{_normalize_id(persona)}",
        label=persona,
        metadata={"priority": priority, "needs": needs},
        source_file=source_file,
        source_line=line_num,
        confidence=0.85,
    )


def _parse_stripe_product_row(row: dict[str, str], line_num: int,
                              source_file: str) -> ExtractedEntity | None:
    tier = row.get("Tier", "").strip()
    product_id = row.get("Product ID", "").strip()
    monthly = row.get("Monthly Price ID", "").strip()
    yearly = row.get("Yearly Price ID", "").strip()
    if not tier:
        return None
    return ExtractedEntity(
        node_type="STRIPE_PRODUCT",
        id=f"stripe::{_normalize_id(tier)}",
        label=f"Stripe: {tier}",
        metadata={
            "tier": tier,
            "product_id": product_id,
            "monthly_price_id": monthly,
            "yearly_price_id": yearly,
        },
        source_file=source_file,
        source_line=line_num,
        confidence=0.90,
    )


def _parse_competitor_row(row: dict[str, str], line_num: int,
                          source_file: str) -> ExtractedEntity | None:
    dimension = row.get("Dimension", "").strip()
    if dimension:
        # This is comparison data, not a competitor node itself
        return None
    return None


def _parse_brand_row(row: dict[str, str], line_num: int,
                     source_file: str) -> ExtractedEntity | None:
    field_name = row.get("Field", "").strip()
    value = row.get("Value", "").strip()
    if not field_name:
        return None
    return ExtractedEntity(
        node_type="BRAND_ASSET",
        id=f"brand::{_normalize_id(field_name)}",
        label=f"Brand: {field_name}",
        metadata={"asset_type": field_name, "value": value},
        source_file=source_file,
        source_line=line_num,
        confidence=0.80,
    )


def _parse_domain_row(row: dict[str, str], line_num: int,
                      source_file: str) -> ExtractedEntity | None:
    domain = row.get("Domain", "").strip()
    purpose = row.get("Purpose", "").strip()
    hosting = row.get("Amplify App", row.get("Hosting", "")).strip()
    if not domain:
        return None
    return ExtractedEntity(
        node_type="DOMAIN",
        id=f"domain::{_normalize_id(domain)}",
        label=domain,
        metadata={"purpose": purpose, "hosting": hosting},
        source_file=source_file,
        source_line=line_num,
        confidence=0.85,
    )


def _parse_package_row(row: dict[str, str], line_num: int,
                       source_file: str) -> ExtractedEntity | None:
    """Parse a key-value style table into a PACKAGE entity (aggregate)."""
    field_name = row.get("Field", "").strip()
    value = row.get("Value", "").strip()
    if not field_name:
        return None
    # Individual rows of a package table are metadata, not separate entities
    return None


# ---------------------------------------------------------------------------
# Invocation chain and dependency parsers
# ---------------------------------------------------------------------------

def _parse_invocation_rows(rows: list[dict[str, str]], line_num: int,
                           source_file: str) -> list[ExtractedEdge]:
    """Parse invocation chain table rows into CALLS edges."""
    edges: list[ExtractedEdge] = []
    for row in rows:
        caller = row.get("Caller", "").strip()
        callee = row.get("Callee", "").strip()
        inv_type = row.get("Type", "").strip()
        if not caller or not callee:
            continue
        # Map to service IDs
        caller_id = _service_name_to_id(caller)
        callee_id = _service_name_to_id(callee)
        if caller_id and callee_id:
            edges.append(ExtractedEdge(
                source_id=caller_id,
                target_id=callee_id,
                relationship="CALLS",
                confidence=0.95,
                source_file=source_file,
                source_line=line_num,
            ))
    return edges


def _parse_dependency_rows(rows: list[dict[str, str]], line_num: int,
                           source_file: str) -> list[ExtractedEdge]:
    """Parse dependency graph table rows into DEPENDS_ON edges."""
    edges: list[ExtractedEdge] = []
    for row in rows:
        component = row.get("Component", "").strip()
        depends_on = row.get("Depends On", "").strip()
        if not component or not depends_on:
            continue
        source_id = _service_name_to_id(component)
        target_id = _guess_target_id(depends_on)
        if source_id and target_id:
            edges.append(ExtractedEdge(
                source_id=source_id,
                target_id=target_id,
                relationship="DEPENDS_ON",
                confidence=0.85,
                source_file=source_file,
                source_line=line_num,
            ))
    return edges


def _parse_envvar_rows(rows: list[dict[str, str]], line_num: int,
                       source_file: str) -> list[ExtractedEdge]:
    """Parse ENVVAR requirement table into REQUIRES edges."""
    edges: list[ExtractedEdge] = []
    # Headers are env var names, rows are lambdas
    for row in rows:
        lambda_ref = row.get("Lambda", "").strip()
        if not lambda_ref:
            continue
        svc_id = _service_name_to_id(lambda_ref)
        if not svc_id:
            continue
        for key, val in row.items():
            if key == "Lambda" or key == "Notes":
                continue
            if val.strip().upper() == "YES":
                env_id = f"env::{_normalize_id(key)}"
                edges.append(ExtractedEdge(
                    source_id=svc_id,
                    target_id=env_id,
                    relationship="REQUIRES",
                    confidence=0.95,
                    source_file=source_file,
                    source_line=line_num,
                ))
    return edges


def _parse_shared_module_rows(rows: list[dict[str, str]], line_num: int,
                              source_file: str) -> tuple[list[ExtractedEntity], list[ExtractedEdge]]:
    """Parse shared module table rows into MODULE entities + IMPORTS edges."""
    entities: list[ExtractedEntity] = []
    edges: list[ExtractedEdge] = []
    seen_modules: set[str] = set()

    for row in rows:
        lambda_ref = row.get("Lambda", "").strip()
        module_path = row.get("Module", "").strip()
        key_functions = row.get("Key Functions", "").strip()
        if not lambda_ref or not module_path:
            continue

        mod_id = f"mod::{_normalize_id(module_path)}"
        if mod_id not in seen_modules:
            seen_modules.add(mod_id)
            entities.append(ExtractedEntity(
                node_type="MODULE",
                id=mod_id,
                label=module_path,
                metadata={
                    "file_path": module_path,
                    "key_functions": [f.strip() for f in key_functions.split(",") if f.strip()],
                },
                source_file=source_file,
                source_line=line_num,
                confidence=0.90,
            ))

        svc_id = _service_name_to_id(lambda_ref)
        if svc_id:
            edges.append(ExtractedEdge(
                source_id=svc_id,
                target_id=mod_id,
                relationship="IMPORTS",
                confidence=0.90,
                source_file=source_file,
                source_line=line_num,
            ))

    return entities, edges


# ---------------------------------------------------------------------------
# Name-to-ID mapping helpers
# ---------------------------------------------------------------------------

# Map common Lambda short names to IDs
_LAMBDA_NAME_MAP: dict[str, str] = {
    "upload": "svc::l01", "l01": "svc::l01",
    "process": "svc::l02", "l02": "svc::l02",
    "graph_builder": "svc::l03", "graphbuilder": "svc::l03", "l03": "svc::l03",
    "insights": "svc::l04", "generate_insights": "svc::l04", "l04": "svc::l04",
    "chat_bot": "svc::l05", "chat_athena_bot": "svc::l05", "athena_bot": "svc::l05",
    "chat": "svc::l05", "l05": "svc::l05",
    "chat_worker": "svc::l06", "chat_job_worker": "svc::l06", "job_worker": "svc::l06",
    "jobworker": "svc::l06", "l06": "svc::l06",
    "kg_query": "svc::l07", "kg_query_service": "svc::l07", "l07": "svc::l07",
    "governance_eval": "svc::l08", "governance_evaluator": "svc::l08", "l08": "svc::l08",
    "governance_lib": "svc::l09", "governance_library": "svc::l09", "l09": "svc::l09",
    "compliance": "svc::l10", "compliance_engine": "svc::l10", "l10": "svc::l10",
    "consent": "svc::l11", "consent_manager": "svc::l11", "l11": "svc::l11",
    "response_kg": "svc::l12", "response_kg_ext": "svc::l12", "l12": "svc::l12",
    "trace_explainer": "svc::l13", "l13": "svc::l13",
    "get_insights": "svc::l14", "l14": "svc::l14",
    "get_documents": "svc::l15", "l15": "svc::l15",
    "web_search": "svc::l16", "l16": "svc::l16",
    "conversation_memory": "svc::l17", "conv_memory": "svc::l17", "l17": "svc::l17",
    "deep_research": "svc::l18", "l18": "svc::l18",
    "audit_trail": "svc::l19", "l19": "svc::l19",
}


def _service_name_to_id(name: str) -> str:
    """Map a Lambda/service name reference to a canonical ID."""
    # Extract L-number if present
    m = re.search(r"L(\d+)", name)
    if m:
        key = f"l{m.group(1).zfill(2)}"
        if key in _LAMBDA_NAME_MAP:
            return _LAMBDA_NAME_MAP[key]

    # Try direct lookup
    lower = _normalize_id(name)
    for key, val in _LAMBDA_NAME_MAP.items():
        if key in lower:
            return val

    # Fallback
    return f"svc::{lower}" if lower else ""


def _guess_target_id(ref: str) -> str:
    """Try to map a generic reference to an entity ID."""
    lower = ref.lower().strip()
    if "neo4j" in lower:
        return "infra::i01"
    if "s3" in lower:
        return "infra::i02"
    if "cognito" in lower:
        return "infra::i03"
    if "dynamodb" in lower:
        return "infra::i04"
    if "amplify" in lower and "app" in lower:
        return "infra::i05"
    if "amplify" in lower:
        return "infra::i06"
    if "bedrock" in lower:
        return "infra::i08"
    # Try service lookup
    svc = _service_name_to_id(ref)
    if svc:
        return svc
    # Module reference
    if "/" in ref or "." in ref:
        return f"mod::{_normalize_id(ref)}"
    return ""


# ---------------------------------------------------------------------------
# Key-value style table aggregator (for PACKAGE, PATENT sections)
# ---------------------------------------------------------------------------

def _aggregate_kv_table(table: dict[str, Any], node_type: str,
                        source_file: str) -> ExtractedEntity | None:
    """Aggregate a key-value style table (Field | Value) into a single entity."""
    rows = table.get("rows", [])
    headers = table.get("headers", [])

    if len(headers) != 2:
        return None
    if headers[0] not in ("Field", "field") and headers[1] not in ("Value", "value"):
        return None

    metadata: dict[str, str] = {}
    name = ""
    version = ""

    for row in rows:
        field_name = row.get("Field", row.get("field", "")).strip()
        value = row.get("Value", row.get("value", "")).strip()
        key = _normalize_id(field_name)
        metadata[key] = _strip_markdown(value)
        if field_name.lower() == "name":
            name = _strip_markdown(value)
        elif field_name.lower() == "version":
            version = _strip_markdown(value)

    if not name:
        name = metadata.get("name", "")
    if not name:
        return None

    entity_id = f"{node_type.lower()}::{_normalize_id(name)}"
    label = f"{name} v{version}" if version else name

    return ExtractedEntity(
        node_type=node_type,
        id=entity_id,
        label=label,
        metadata=metadata,
        source_file=source_file,
        source_line=table.get("start_line", 0),
        confidence=0.85,
    )


# ---------------------------------------------------------------------------
# ADR reference extractor
# ---------------------------------------------------------------------------

_ADR_PATTERN = re.compile(r"ADR-(\d{2,4})")


def _extract_adr_references(text: str, source_file: str, line_num: int) -> list[ExtractedEntity]:
    """Extract ADR references from a line of text."""
    entities: list[ExtractedEntity] = []
    seen: set[str] = set()
    for m in _ADR_PATTERN.finditer(text):
        adr_num = m.group(1)
        adr_id = f"adr::adr-{adr_num}"
        if adr_id not in seen:
            seen.add(adr_id)
            entities.append(ExtractedEntity(
                node_type="ADR",
                id=adr_id,
                label=f"ADR-{adr_num}",
                metadata={"number": adr_num},
                source_file=source_file,
                source_line=line_num,
                confidence=0.70,
            ))
    return entities


# ---------------------------------------------------------------------------
# Competitor section parser
# ---------------------------------------------------------------------------

def _parse_competitor_section(ctx: SectionContext, tables: list[dict[str, Any]],
                              source_file: str) -> list[ExtractedEntity]:
    """Parse a competitor comparison section."""
    entities: list[ExtractedEntity] = []
    name = ctx.h3 if ctx.h3 else ctx.h2
    name = _strip_markdown(name)

    # Extract competitor name and arxiv ID
    arxiv_match = re.search(r"arXiv:\s*(\S+)", name)
    arxiv_id = arxiv_match.group(1) if arxiv_match else ""
    comp_name = re.sub(r"\(.*?\)", "", name).strip().replace("Competitor:", "").strip()

    if comp_name:
        comparison: dict[str, dict[str, str]] = {}
        for table in tables:
            if "Dimension" in table.get("headers", []):
                for row in table.get("rows", []):
                    dim = row.get("Dimension", "").strip()
                    if dim:
                        comparison[dim] = {
                            k: v for k, v in row.items()
                            if k != "Dimension"
                        }
        entities.append(ExtractedEntity(
            node_type="COMPETITOR",
            id=f"competitor::{_normalize_id(comp_name)}",
            label=comp_name,
            metadata={
                "arxiv_id": arxiv_id,
                "comparison": comparison if comparison else {},
            },
            source_file=source_file,
            source_line=0,
            confidence=0.85,
        ))
    return entities


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

class MarkdownKGParser:
    """Parse a markdown knowledge graph file into entities and edges."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def parse_file(self, file_path: str | Path) -> ParseResult:
        """Parse a single markdown file and return entities + edges."""
        path = Path(file_path)
        result = ParseResult(source_file=str(path))

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            result.warnings.append(f"Could not read {path}: {e}")
            return result

        # Detect if this is a lessons-distilled.md file
        if "lessons-distilled" in path.name.lower() or "lessons_distilled" in path.name.lower():
            self._parse_lessons_file(content, result)
            return result

        # Parse normally using section context
        self._parse_sections(content, result)
        return result

    def _parse_lessons_file(self, content: str, result: ParseResult) -> None:
        """Parse a lessons-distilled.md file with its specific format."""
        lines = content.splitlines()
        current_severity = "MEDIUM"

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Track severity from section headers
            if stripped.startswith("## [CRITICAL]"):
                current_severity = "CRITICAL"
            elif stripped.startswith("## [HIGH]"):
                current_severity = "HIGH"
            elif stripped.startswith("## [MEDIUM]"):
                current_severity = "MEDIUM"
            elif stripped.startswith("## Recently Added"):
                current_severity = "MEDIUM"
            elif stripped.startswith("## Archived"):
                current_severity = "LOW"

            # Parse lesson lines
            if stripped.startswith("- LESSON-"):
                entity = _parse_lesson_line(stripped, current_severity, i, result.source_file)
                if entity:
                    result.entities.append(entity)

                    # Extract ADR references for edges
                    source_ref = entity.metadata.get("source_adr", "")
                    if source_ref:
                        for adr_match in _ADR_PATTERN.finditer(source_ref):
                            adr_id = f"adr::adr-{adr_match.group(1)}"
                            result.edges.append(ExtractedEdge(
                                source_id=entity.id,
                                target_id=adr_id,
                                relationship="REFERENCES",
                                confidence=0.80,
                                source_file=result.source_file,
                                source_line=i,
                            ))

    def _parse_sections(self, content: str, result: ParseResult) -> None:
        """Parse a general KG markdown file by tracking section context."""
        lines = content.splitlines()
        ctx = SectionContext()
        current_section_type = "_UNKNOWN"
        current_section_conf = 0.0

        # First pass: extract all tables
        all_tables = extract_tables(content)

        # Map tables to their line ranges
        table_line_map: dict[int, dict[str, Any]] = {}
        for table in all_tables:
            table_line_map[table["start_line"]] = table

        # Track which tables have been processed
        processed_tables: set[int] = set()

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            line_num = i + 1  # 1-based

            # Track section headers
            heading_match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                ctx.update(level, heading_text)

                # Determine section type
                sec_type, sec_conf = _infer_section_type(heading_text)
                if sec_type != "_UNKNOWN":
                    current_section_type = sec_type
                    current_section_conf = sec_conf

                # Check if heading itself is a competitor section
                if current_section_type == "COMPETITOR" and level >= 3:
                    comp_tables = [t for t_line, t in table_line_map.items()
                                   if t_line > line_num and t_line not in processed_tables]
                    comp_entities = _parse_competitor_section(ctx, comp_tables[:1], result.source_file)
                    result.entities.extend(comp_entities)

                i += 1
                continue

            # Skip types
            if current_section_type == "_SKIP":
                i += 1
                continue

            # Check if current line starts a table
            found_table = None
            for tbl_line, tbl in table_line_map.items():
                if tbl_line == line_num and tbl_line not in processed_tables:
                    found_table = tbl
                    processed_tables.add(tbl_line)
                    break

            if found_table:
                self._process_table(found_table, current_section_type,
                                    current_section_conf, ctx, result)
                # Skip past the table rows
                table_end = found_table["start_line"] + 1 + len(found_table["rows"])
                i = max(i + 1, table_end)
                continue

            # Extract inline ADR references from Key ADRs sections
            if current_section_type == "ADR" and "ADR-" in stripped:
                adrs = _extract_adr_references(stripped, result.source_file, line_num)
                for adr in adrs:
                    adr.confidence = 0.75
                    result.entities.append(adr)

            i += 1

        # Second pass: extract key-value tables that form aggregate entities
        for table in all_tables:
            start = table["start_line"]
            if start in processed_tables and self._is_kv_table(table):
                # This was processed but let's check if we need an aggregate entity
                pass

    def _is_kv_table(self, table: dict[str, Any]) -> bool:
        """Check if a table is a key-value format (Field | Value)."""
        headers = [h.lower() for h in table.get("headers", [])]
        return len(headers) == 2 and headers[0] == "field" and headers[1] == "value"

    def _process_table(self, table: dict[str, Any], section_type: str,
                       section_conf: float, ctx: SectionContext,
                       result: ParseResult) -> None:
        """Dispatch table processing based on section type."""
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        start_line = table.get("start_line", 0)

        if not rows:
            return

        # Key-value tables -> aggregate entity
        if self._is_kv_table(table):
            entity = _aggregate_kv_table(table, section_type, result.source_file)
            if entity and section_type not in ("_UNKNOWN", "_SKIP"):
                result.entities.append(entity)
            return

        # Dispatch based on section type
        dispatchers = {
            "SERVICE": _parse_service_row,
            "MISTAKE": _parse_mistake_row,
            "INFRA": _parse_infra_row,
            "OPEN_ISSUE": _parse_open_issue_row,
            "TEST_SUITE": _parse_test_suite_row,
            "NEO4J_SCHEMA": _parse_neo4j_schema_row,
            "MOAT_MODULE": _parse_moat_module_row,
            "PUBLICATION": _parse_publication_row,
            "PAPER": _parse_paper_row,
            "IP_ASSET": _parse_ip_asset_row,
            "BENCHMARK": _parse_benchmark_row,
            "CHANNEL": _parse_channel_row,
            "PERSONA": _parse_persona_row,
            "STRIPE_PRODUCT": _parse_stripe_product_row,
            "BRAND_ASSET": _parse_brand_row,
            "DOMAIN": _parse_domain_row,
        }

        # Special edge-producing sections
        if section_type == "_INVOCATION":
            edges = _parse_invocation_rows(rows, start_line, result.source_file)
            result.edges.extend(edges)
            return

        if section_type == "_DEPENDENCY":
            edges = _parse_dependency_rows(rows, start_line, result.source_file)
            result.edges.extend(edges)
            return

        if section_type == "ENVVAR":
            edges = _parse_envvar_rows(rows, start_line, result.source_file)
            result.edges.extend(edges)
            return

        if section_type == "MODULE":
            # Shared modules table
            if "Lambda" in headers and "Module" in headers:
                entities, edges = _parse_shared_module_rows(rows, start_line, result.source_file)
                result.entities.extend(entities)
                result.edges.extend(edges)
                return

        parser_fn = dispatchers.get(section_type)
        if parser_fn:
            for row in rows:
                entity = parser_fn(row, start_line, result.source_file)
                if entity:
                    result.entities.append(entity)
        elif section_type not in ("_UNKNOWN", "_SKIP", "_CRITICAL_PARAM", "_INVOCATION",
                                   "_DEPENDENCY", "ENVVAR", "MODULE"):
            # Unknown table in known section -- skip with warning
            if self.verbose:
                result.warnings.append(
                    f"Line {start_line}: Unknown table in section '{ctx.full_path}' "
                    f"(type={section_type})")


# ---------------------------------------------------------------------------
# Edge inference engine
# ---------------------------------------------------------------------------

class EdgeInferenceEngine:
    """Infer edges between extracted entities based on content references."""

    def __init__(self, entities: list[ExtractedEntity]) -> None:
        self._entities = entities
        self._entity_index: dict[str, ExtractedEntity] = {e.id: e for e in entities}
        self._service_ids: set[str] = {
            e.id for e in entities if e.node_type == "SERVICE"
        }

    def infer_edges(self) -> list[ExtractedEdge]:
        """Infer all edges from entity metadata cross-references."""
        edges: list[ExtractedEdge] = []
        seen: set[tuple[str, str, str]] = set()

        for entity in self._entities:
            new_edges = self._infer_for_entity(entity)
            for edge in new_edges:
                key = (edge.source_id, edge.target_id, edge.relationship)
                if key not in seen:
                    seen.add(key)
                    edges.append(edge)

        return edges

    def _infer_for_entity(self, entity: ExtractedEntity) -> list[ExtractedEdge]:
        edges: list[ExtractedEdge] = []

        # LESSON -> APPLIES_TO service
        if entity.node_type == "LESSON":
            desc = entity.metadata.get("description", "")
            component = self._find_service_reference(desc)
            if component:
                edges.append(ExtractedEdge(
                    source_id=entity.id,
                    target_id=component,
                    relationship="APPLIES_TO",
                    confidence=0.65,
                    source_file=entity.source_file,
                ))

        # MISTAKE -> OCCURRED_IN component
        if entity.node_type == "MISTAKE":
            component = entity.metadata.get("component", "")
            if component:
                svc = _service_name_to_id(component)
                if svc and svc in self._entity_index:
                    edges.append(ExtractedEdge(
                        source_id=entity.id,
                        target_id=svc,
                        relationship="OCCURRED_IN",
                        confidence=0.90,
                        source_file=entity.source_file,
                    ))

        # OPEN_ISSUE -> BLOCKS component
        if entity.node_type == "OPEN_ISSUE":
            component = entity.metadata.get("component", "")
            if component:
                svc = _service_name_to_id(component)
                if svc and svc in self._entity_index:
                    edges.append(ExtractedEdge(
                        source_id=entity.id,
                        target_id=svc,
                        relationship="BLOCKS",
                        confidence=0.80,
                        source_file=entity.source_file,
                    ))

        # MOAT_MODULE -> COVERED_BY patent
        if entity.node_type == "MOAT_MODULE":
            claims = entity.metadata.get("patent_claims", "")
            if claims:
                # Look for patent entity
                for e in self._entities:
                    if e.node_type == "PATENT":
                        edges.append(ExtractedEdge(
                            source_id=entity.id,
                            target_id=e.id,
                            relationship="COVERED_BY",
                            confidence=0.85,
                            source_file=entity.source_file,
                        ))
                        break

        # ADR -> GOVERNS (inferred from ADR references in other entities)
        if entity.node_type == "ADR":
            # Look for services/modules that reference this ADR
            adr_num = entity.metadata.get("number", "")
            if adr_num:
                pattern = f"ADR-{adr_num}"
                for other in self._entities:
                    if other.node_type in ("SERVICE", "MODULE", "FRONTEND_COMPONENT"):
                        meta_str = str(other.metadata)
                        if pattern in meta_str:
                            edges.append(ExtractedEdge(
                                source_id=entity.id,
                                target_id=other.id,
                                relationship="GOVERNS",
                                confidence=0.70,
                                source_file=entity.source_file,
                            ))

        return edges

    def _find_service_reference(self, text: str) -> str:
        """Find a service reference in text, return its ID or empty string."""
        # Look for L-number patterns
        m = re.search(r"L(\d{2})", text)
        if m:
            key = f"l{m.group(1)}"
            svc_id = _LAMBDA_NAME_MAP.get(key, "")
            if svc_id and svc_id in self._entity_index:
                return svc_id

        # Look for Lambda name patterns
        for name, svc_id in _LAMBDA_NAME_MAP.items():
            if len(name) > 3 and name in text.lower():
                if svc_id in self._entity_index:
                    return svc_id

        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_markdown_kg(file_path: str | Path, verbose: bool = False) -> ParseResult:
    """Parse a single markdown KG file.

    Parameters
    ----------
    file_path : str or Path
        Path to the markdown file.
    verbose : bool
        If True, include extra warnings.

    Returns
    -------
    ParseResult
        Entities and edges extracted from the file.
    """
    parser = MarkdownKGParser(verbose=verbose)
    return parser.parse_file(file_path)


def parse_and_infer(file_paths: list[str | Path],
                    verbose: bool = False) -> tuple[list[ExtractedEntity], list[ExtractedEdge]]:
    """Parse multiple files and run edge inference on the combined result.

    Parameters
    ----------
    file_paths : list
        Paths to markdown files.
    verbose : bool
        If True, include extra warnings.

    Returns
    -------
    tuple
        (entities, edges) combined from all files with inferred edges.
    """
    parser = MarkdownKGParser(verbose=verbose)
    all_entities: list[ExtractedEntity] = []
    all_edges: list[ExtractedEdge] = []

    for fp in file_paths:
        result = parser.parse_file(fp)
        all_entities.extend(result.entities)
        all_edges.extend(result.edges)

    # Deduplicate entities by ID (keep first occurrence)
    seen_ids: set[str] = set()
    unique_entities: list[ExtractedEntity] = []
    for entity in all_entities:
        if entity.id not in seen_ids:
            seen_ids.add(entity.id)
            unique_entities.append(entity)

    # Run edge inference
    engine = EdgeInferenceEngine(unique_entities)
    inferred_edges = engine.infer_edges()
    all_edges.extend(inferred_edges)

    # Deduplicate edges
    seen_edge_keys: set[tuple[str, str, str]] = set()
    unique_edges: list[ExtractedEdge] = []
    for edge in all_edges:
        key = (edge.source_id, edge.target_id, edge.relationship)
        if key not in seen_edge_keys:
            seen_edge_keys.add(key)
            unique_edges.append(edge)

    return unique_entities, unique_edges
