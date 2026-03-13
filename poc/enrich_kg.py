"""Enrich cognigraph.json nodes with descriptions from source files.

Reads the actual content from engineering-kg.md, lessons-distilled.md,
and other sources to populate node descriptions so CogniGraph agents
have real knowledge to reason from.
"""

import json
import os
import re
import sys


def load_file(path):
    """Load a file, return empty string if not found."""
    full = os.path.join(os.path.dirname(__file__), "..", "..", path)
    full = os.path.abspath(full)
    if os.path.exists(full):
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return ""


def extract_lessons(text):
    """Extract lesson descriptions from lessons-distilled.md."""
    lessons = {}
    # Pattern: ### LESSON-NNN or - LESSON-NNN: description
    for match in re.finditer(
        r"(?:###?\s*)?(?:LESSON[- ])(\d+)[:\s—-]+(.+?)(?:\n|$)", text, re.IGNORECASE
    ):
        num = match.group(1).zfill(3)
        desc = match.group(2).strip()
        lessons[f"lesson::lesson-{num}"] = desc
    return lessons


def extract_mistakes(text):
    """Extract mistake descriptions from engineering-kg.md."""
    mistakes = {}
    for match in re.finditer(
        r"(?:###?\s*)?(?:MISTAKE[- ])(\d+)[:\s—-]+(.+?)(?:\n|$)", text, re.IGNORECASE
    ):
        num = match.group(1).zfill(3)
        desc = match.group(2).strip()
        mistakes[f"mistake::mistake-{num}"] = desc
    return mistakes


def extract_adrs(text):
    """Extract ADR descriptions from text."""
    adrs = {}
    for match in re.finditer(
        r"(?:###?\s*)?ADR[- ](\d+)[:\s—-]+(.+?)(?:\n|$)", text, re.IGNORECASE
    ):
        num = match.group(1).zfill(3)
        desc = match.group(2).strip()
        adrs[f"adr::adr-{num}"] = desc
    return adrs


def extract_services(text):
    """Extract service descriptions from engineering-kg.md."""
    services = {}
    # Look for service blocks with handler info
    blocks = re.split(r"\n(?=###?\s)", text)
    for block in blocks:
        # Match service IDs like L01, L02, etc.
        svc_match = re.search(r"(L\d+)[:\s—-]+(\w+)", block)
        if svc_match:
            svc_id = svc_match.group(1).lower()
            svc_name = svc_match.group(2)
            # Get the full block as description (first 500 chars)
            desc = block.strip()[:500]
            services[f"svc::{svc_id}"] = desc
    return services


def enrich_from_engineering_kg(text, descriptions):
    """Parse engineering-kg.md for all entity types."""
    # Services section
    svc_section = re.search(r"## Services(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if svc_section:
        for match in re.finditer(
            r"###?\s*(L\d+)[:\s|—-]+([^\n]+)\n(.*?)(?=\n###?\s*L\d+|\n## |\Z)",
            svc_section.group(1),
            re.DOTALL,
        ):
            svc_id = match.group(1).lower()
            title = match.group(2).strip()
            body = match.group(3).strip()[:400]
            descriptions[f"svc::{svc_id}"] = f"{title}\n{body}"

    # Lessons section
    lesson_section = re.search(r"## Lessons(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if lesson_section:
        for match in re.finditer(
            r"(?:LESSON[- ])(\d+)[:\s—-]+(.+?)(?:\n|$)",
            lesson_section.group(1),
            re.IGNORECASE,
        ):
            num = match.group(1).zfill(3)
            desc = match.group(2).strip()
            descriptions[f"lesson::lesson-{num}"] = desc

    # Infra section
    infra_section = re.search(r"## Infra(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if infra_section:
        for match in re.finditer(
            r"###?\s*(I\d+)[:\s|—-]+([^\n]+)", infra_section.group(1)
        ):
            infra_id = match.group(1).lower()
            desc = match.group(2).strip()
            descriptions[f"infra::{infra_id}"] = desc


def main():
    kg_path = os.path.join(os.path.dirname(__file__), "..", "..", "cognigraph.json")
    kg_path = os.path.abspath(kg_path)

    print(f"Loading KG from: {kg_path}")
    with open(kg_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    nodes = data.get("nodes", [])
    print(f"Total nodes: {len(nodes)}")

    # Collect descriptions from all sources
    descriptions = {}

    # 1. Engineering KG
    eng_kg = load_file(".gcc/departments/engineering-kg.md")
    if eng_kg:
        print(f"Engineering KG: {len(eng_kg)} chars")
        enrich_from_engineering_kg(eng_kg, descriptions)
        descriptions.update(extract_lessons(eng_kg))
        descriptions.update(extract_mistakes(eng_kg))
        descriptions.update(extract_adrs(eng_kg))
        descriptions.update(extract_services(eng_kg))

    # 2. Lessons distilled
    lessons_text = load_file("tasks/lessons-distilled.md")
    if lessons_text:
        print(f"Lessons distilled: {len(lessons_text)} chars")
        descriptions.update(extract_lessons(lessons_text))

    # 3. Project KG
    proj_kg = load_file(".gcc/project-kg.md")
    if proj_kg:
        print(f"Project KG: {len(proj_kg)} chars")
        descriptions.update(extract_lessons(proj_kg))
        descriptions.update(extract_mistakes(proj_kg))
        descriptions.update(extract_adrs(proj_kg))
        descriptions.update(extract_services(proj_kg))

    # 4. Research KG
    research_kg = load_file(".gcc/departments/research-kg.md")
    if research_kg:
        print(f"Research KG: {len(research_kg)} chars")
        descriptions.update(extract_lessons(research_kg))
        descriptions.update(extract_adrs(research_kg))

    # 5. Marketing KG
    marketing_kg = load_file(".gcc/departments/marketing-kg.md")
    if marketing_kg:
        print(f"Marketing KG: {len(marketing_kg)} chars")

    # 6. Read individual ADR files
    adrs_dir = os.path.join(os.path.dirname(__file__), "..", "..", "tasks", "adrs")
    adrs_dir = os.path.abspath(adrs_dir)
    if os.path.isdir(adrs_dir):
        for fname in os.listdir(adrs_dir):
            if fname.endswith(".md"):
                adr_match = re.search(r"ADR[- ]?(\d+)", fname, re.IGNORECASE)
                if adr_match:
                    num = adr_match.group(1).zfill(3)
                    adr_id = f"adr::adr-{num}"
                    if adr_id not in descriptions:
                        adr_text = load_file(f"tasks/adrs/{fname}")
                        # Extract title and first paragraph
                        title_match = re.search(r"#\s+(.+)", adr_text)
                        title = title_match.group(1) if title_match else fname
                        # Get context/decision sections
                        context = re.search(
                            r"(?:Context|Decision|Summary)[:\s]*\n(.+?)(?:\n#|\Z)",
                            adr_text,
                            re.DOTALL,
                        )
                        body = context.group(1).strip()[:300] if context else ""
                        descriptions[adr_id] = f"{title}\n{body}"
        print(f"ADR files scanned: {adrs_dir}")

    # 7. Generate descriptions from metadata for nodes that still lack them
    for node in nodes:
        nid = node.get("id", "")
        if nid not in descriptions:
            label = node.get("label", "")
            ntype = node.get("type", "")
            metadata = node.get("metadata", {})

            if ntype == "SERVICE" and metadata:
                handler = metadata.get("handler", "")
                timeout = metadata.get("timeout", "")
                memory = metadata.get("memory_mb", "")
                desc = f"Lambda service: {label}. Handler: {handler}. Timeout: {timeout}, Memory: {memory}."
                envvars = metadata.get("env_vars", [])
                if envvars:
                    desc += f" Required env vars: {', '.join(envvars)}."
                descriptions[nid] = desc

            elif ntype == "MODULE" and metadata:
                desc = f"Shared module: {label}."
                if metadata.get("path"):
                    desc += f" Path: {metadata['path']}."
                descriptions[nid] = desc

            elif ntype == "INFRA" and metadata:
                desc = f"Infrastructure: {label}. {json.dumps(metadata)[:200]}"
                descriptions[nid] = desc

            elif ntype == "ENV" or nid.startswith("env::"):
                desc = f"Environment variable: {label}. Required for Lambda configuration."
                descriptions[nid] = desc

            elif ntype == "MISTAKE" and metadata:
                desc = f"Mistake: {label}. {json.dumps(metadata)[:300]}"
                descriptions[nid] = desc

            elif label:
                descriptions[nid] = f"{ntype}: {label}"

    # Apply descriptions to nodes
    enriched = 0
    for node in nodes:
        nid = node.get("id", "")
        if nid in descriptions and descriptions[nid]:
            node["description"] = descriptions[nid]
            enriched += 1

    print(f"\nEnriched {enriched} / {len(nodes)} nodes with descriptions")

    # Save enriched KG
    out_path = kg_path  # overwrite
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Saved enriched KG to: {out_path}")

    # Show sample enriched nodes
    print("\nSample enriched nodes:")
    for node in nodes[:10]:
        nid = node.get("id", "")
        desc = node.get("description", "")
        if desc:
            print(f"  {nid}: {desc[:100]}...")


if __name__ == "__main__":
    main()
