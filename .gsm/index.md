# GSM — Strategy Document Index

| Document | Type | Tags | Summary |
|----------|------|------|---------|
| decisions/ADR-116-coding-ontology-completeness.md | decision | ontology, coding-domain, roadmap | ~25% complete; roadmap to 16 skills/13 entities/12 relationships/8 output gates |
| decisions/ADR-115-phase35-file-system-tools.md | decision | tools, file-system, git, safety | 10 new tools (read/write/grep/glob/bash/git_*); _WRITE_TOOLS + routing P0 fixes |
| decisions/ADR-114-graq-generate-stream-param.md | decision | generation, streaming, backend-agnostic | stream=True on graq_generate: areason_stream() → chunks in metadata, all 14 backends work |
| decisions/ADR-113-agenerate-stream-default-impl.md | decision | streaming, BaseBackend, backward-compat | Non-abstract agenerate_stream() default on BaseBackend — never make it abstract |
| decisions/ADR-112-graq-generate-phase1.md | decision | generation, graph, areason | graq_generate routes through graph.areason() for graph context activation |
| decisions/ADR-111-generation-types-new-module.md | decision | generation, types, blast-radius | New generation.py module to avoid types.py 257-module blast radius |
| decisions/ADR-105.md | decision | strategic-shift, intelligence, quality-gate | 3-layer quality gate + streaming pipeline |
| ../docs/ADR-103-content-aware-pcst.md | decision | activation, pcst, chunks | Content richness weighting for PCST |
| ../docs/ADR-104-query-reformulator.md | decision | query, reformulation, ai-tools | Context-aware query enhancement |
