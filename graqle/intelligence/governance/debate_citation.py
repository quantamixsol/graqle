"""Citation validator for multi-backend debate.

Validates that debate turn ``evidence_refs`` reference actual KG node IDs.

See for design rationale.
"""

from __future__ import annotations


class CitationError(Exception):
    """Raised when evidence refs are invalid."""

    def __init__(
        self,
        message: str,
        *,
        invalid_refs: list[str],
        valid_count: int,
    ) -> None:
        super().__init__(message)
        self.invalid_refs = invalid_refs
        self.valid_count = valid_count


class CitationValidator:
    """Validates debate turn evidence_refs against known KG node IDs."""

    def __init__(self, valid_node_ids: set[str]) -> None:
        self._valid_node_ids = valid_node_ids

    def validate(
        self,
        evidence_refs: list[str],
        require_citation: bool = True,
    ) -> bool:
        """Check that all *evidence_refs* exist in the KG.

        Returns ``True`` when every ref is valid.

        Raises
        ------
        CitationError
            If refs are empty (when required) or contain unknown node IDs.
        """
        if not require_citation:
            return True

        if not evidence_refs:
            raise CitationError(
                "Citation required but no evidence_refs provided",
                invalid_refs=[],
                valid_count=0,
            )

        invalid = [ref for ref in evidence_refs if ref not in self._valid_node_ids]
        if invalid:
            raise CitationError(
                f"{len(invalid)} invalid evidence ref(s): {invalid}",
                invalid_refs=invalid,
                valid_count=len(evidence_refs) - len(invalid),
            )

        return True

    @property
    def node_count(self) -> int:
        """Return the number of valid KG node IDs."""
        return len(self._valid_node_ids)
