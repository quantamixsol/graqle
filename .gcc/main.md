# Graqle SDK — Global Roadmap

## Vision
Dev Intelligence Layer — Graph + Quality Gate for development.
The Q in Graqle = Quality Gate that every code change passes through.

## Current Version: v0.26.0

## Strategic Shift: ADR-105
Transform from passive MCP tool (70-80% bypass) to 3-layer intelligence system (1-2% bypass):
- **Layer B**: Embedded intelligence in source files (0% bypass)
- **Layer A**: Deep reasoning via graq_gate MCP tool (<500ms)
- **Layer C**: Enforcement via git hooks + CI (0% bypass at commit)

## Active Work
- [ ] **Phase 1**: Streaming Intelligence Pipeline + 60-second first value (v0.27)
- [ ] Phase 2: Intelligence Layer injection (v0.27 continued)
- [ ] Phase 3: Quality Gate enforcement (v0.28)
- [ ] Phase 4: Transparency Layer — TAMR+ patterns (v0.28)
- [ ] Phase 5: Dev Governance Protocol specification (v0.29)

## Completed (v0.24-v0.26)
- [x] JS/TS full coverage (JSAnalyzer rewrite)
- [x] Chunk inheritance 3-tier fallback (_inherit_chunks)
- [x] Property-based activation fallback
- [x] graq link infer (cross-project edge inference)
- [x] max_nodes scaling for multi-repo graphs
- [x] 14 backend providers
- [x] 22 MCP tools
- [x] ADR-103 (Content-Aware PCST), ADR-104 (Query Reformulator)
- [x] ADR-105 (Streaming Intelligence & Quality Gate) — ACCEPTED
