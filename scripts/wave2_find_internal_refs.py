"""Find the 4 internal-reference hits in wave-2 src that break test_advisory_package_wide_leakage."""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAQLE_PKG = REPO_ROOT / "graqle"

# Same patterns as tests/test_distribution/test_no_internal_strings.py
PATTERNS = [
    r"\bTS-[1-4]\b",
    r"\bcrawlq\b",
    r"\btracegov\b",
    r"\bgraqle-studio\b",
    r"\bgraqle-vscode\b",
    r"\bADR-[0-9]+\b",
    r"\bTB-[A-Z][0-9]+\b",
    r"\bOT-[0-9]{3}\b",
    r"\bCG-[A-Z]+(?:-[0-9]+)?\b",
    r"\bBLOCKER-[0-9]+\b",
    r"\$10/month",
    r"pytest-xdist workers",
]
COMBINED = re.compile("|".join(PATTERNS))

SHIPPED = {".py", ".md", ".json", ".yaml", ".yml", ".toml"}

EXEMPT_PREFIXES = {
    "graqle/benchmarks/",
    "graqle/cli/commands/link.py",
    "graqle/connectors/neptune.py",
    "graqle/connectors/neptune_connector.py",
    "graqle/cli/main.py",
    "graqle/workflow/diff_applicator.py",
    "graqle/ontology/domains/coding.py",
    "graqle/ontology/domains/mcp.py",
    "graqle/plugins/mcp_dev_server.py",
}


def iter_shipped():
    for p in sorted(GRAQLE_PKG.rglob("*")):
        if not p.is_file() or p.suffix not in SHIPPED:
            continue
        rel = p.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(ex) for ex in EXEMPT_PREFIXES):
            continue
        yield p, rel


def main() -> int:
    total = 0
    hits: list[str] = []
    for path, rel in iter_shipped():
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for m in COMBINED.finditer(content):
            total += 1
            line_num = content[: m.start()].count("\n") + 1
            hits.append(f"{rel}:{line_num}: '{m.group()}'")
    print(f"TOTAL_HITS: {total}")
    for h in hits:
        print(f"  {h}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
