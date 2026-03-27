# ADR-111: New Generation Types in Separate Module
**Date:** 2026-03-26 | **Status:** ACCEPTED
**Branch:** feature-coding-assistant | **Phase:** T1.1

## Context
graq_generate and graq_edit need new result types: `GenerationRequest`, `CodeGenerationResult`, `DiffPatch`. The obvious place is `graqle/core/types.py`, which already holds `ReasoningResult`.

## Decision
Create `graqle/core/generation.py` as a new standalone module. Do NOT add to or modify `types.py`.

## Rationale
- `types.py` is imported by 257 modules across the SDK
- Any dataclass field addition/removal triggers mypy strict checks on all 257 consumers
- A new file has blast radius = 0 (no existing consumers until explicitly imported)
- `CodeGenerationResult` mirrors `ReasoningResult` scalar fields without inheriting from it — avoids coupling the two result type hierarchies

## Consequences
- **Positive:** Zero regression risk on existing 927 tests from the type change alone
- **Positive:** `generation.py` can evolve independently (add streaming fields, patch metadata, etc.)
- **Negative:** Some scalar field duplication between `ReasoningResult` and `CodeGenerationResult` — acceptable given blast radius savings
- **Rule:** If a future task requires sharing fields, introduce a `BaseResult` protocol in `types.py` only after full impact analysis

## Enforcement
Patent scan must include `graqle/core/generation.py` from this point forward.
