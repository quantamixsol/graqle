"""RFC 6962 Merkle tree over canonicalized governed-trace records (R25-EU01 PR-2).

This module implements the cryptographic heart of Layer 5: a custom RFC 6962
(Certificate Transparency) Merkle tree built directly on the Python standard
library ``hashlib.sha256``. It is deliberately NOT backed by a third-party
Merkle library:

* **Supply-chain hardening** — the tamper-evidence root of trust must not depend
  on an unaudited transitive dependency that could itself be the tampering
  vector. ``hashlib`` ships with CPython and is FIPS-tracked.
* **Exact CT-spec compliance** — RFC 6962 §2.1 fixes domain-separation prefixes
  and odd-node padding precisely. Any deviation silently breaks interop with
  Certificate Transparency verifiers and the cross-implementation golden corpus
  (R25-EU01 AC-10: Python/JS/Go reference verifiers must agree). Owning the few
  lines that matter is safer than trusting a library to match the spec forever.

RFC 6962 domain separation (the load-bearing detail):

* leaf hash  = ``SHA256(0x00 || canon_leaf(record))``
* node hash  = ``SHA256(0x01 || left || right)``

The single-byte prefixes make a leaf hash and an interior-node hash live in
disjoint preimage spaces, which is what prevents a second-preimage attack where
an attacker reshapes the tree by presenting an interior node as if it were a
leaf. Dropping the prefixes is a silent security regression, not a style choice.

Padding (RFC 6962 §2.1): for a level with an odd number of nodes, the last node
is **duplicated** (paired with itself) to form the parent. This is the CT
convention; deviating from it (e.g. promoting the lone node unchanged) produces
roots that no CT verifier will accept and breaks interop forever.

The leaf bytes come from PR-1's :func:`canon_leaf`, which projects a record onto
the frozen ``LEAF_HASH_FIELDS`` allowlist and RFC 8785-canonicalizes it. Wrapper
fields therefore can never enter the leaf hash (C-P1-2), and
``proof_format_version`` is required inside the leaf to defeat replay across
proof-format versions (R25-EU08 Q1).

Scope (PR-2 / Phase M1): ``MerkleTree`` and ``InclusionProof`` only.
``ConsistencyProof`` (RFC 6962 §2.1.2) is deferred to M2 (R25-EU01 Task 2.4).
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

from graqle.governance.tamper_evidence.canonicalize import canon_leaf
from graqle.governance.tamper_evidence.errors import TamperEvidenceError

# RFC 6962 §2.1 domain-separation prefixes. FROZEN — part of the interop
# contract verified by the cross-implementation golden corpus (AC-10).
LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"

# Upper bound on leaves in a single tree. This is a DoS / caller-bug guard, not
# the batch-size policy: the real batch contract is AttestationConfig
# .batch_max_records (default 1000, PR-0). A single batch should never approach
# this ceiling; a tree this large almost certainly means a caller fed unbounded
# input. Set generously (2**20) so legitimate large batches are never refused
# while a runaway allocation is still capped.
MAX_TREE_SIZE = 1 << 20  # 1,048,576 leaves

# Direction encoding for inclusion-proof path entries (R25-EU01 §358 Proof
# Bundle Schema). The spec serializes directions as integers, NOT booleans:
# RFC 8785 / JCS canonicalization treats ``true``/``false`` as distinct from
# ``1``/``0``, so a JS or Go verifier round-tripping the bundle through JSON
# could disagree with a Python ``bool`` encoding. Integers are unambiguous.
#
#   SIBLING_LEFT  (0): the sibling sits to the LEFT of the running hash, so we
#                      concatenate ``sibling || running``.
#   SIBLING_RIGHT (1): the sibling sits to the RIGHT, so ``running || sibling``.
SIBLING_LEFT = 0
SIBLING_RIGHT = 1


class MerkleError(TamperEvidenceError):
    """Raised for invalid Merkle operations (e.g. building an empty tree)."""


def _hash_leaf(leaf_bytes: bytes) -> bytes:
    """RFC 6962 leaf hash: ``SHA256(0x00 || leaf_bytes)``."""
    return hashlib.sha256(LEAF_PREFIX + leaf_bytes).digest()


def _hash_node(left: bytes, right: bytes) -> bytes:
    """RFC 6962 interior-node hash: ``SHA256(0x01 || left || right)``."""
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


def leaf_hash_for_record(record: dict[str, Any]) -> bytes:
    """Compute the RFC 6962 leaf hash for a governed-trace ``record``.

    The record is first projected + canonicalized by PR-1's
    :func:`canon_leaf` (frozen ``LEAF_HASH_FIELDS`` allowlist, RFC 8785 JCS),
    then domain-separated with the leaf prefix. This is the single entry point
    callers should use to turn a record into a leaf; it guarantees the leaf
    bytes match the canonicalization contract exactly.
    """
    return _hash_leaf(canon_leaf(record))


@dataclass(frozen=True)
class InclusionProof:
    """An RFC 6962 inclusion (audit) proof for one leaf in a fixed tree.

    Serializes to the R25-EU01 §358 Proof Bundle Schema fields:

    * ``merkle_path`` — sibling hashes bottom-up, as lowercase hex strings.
    * ``merkle_path_directions`` — for each sibling, ``SIBLING_LEFT`` (0) or
      ``SIBLING_RIGHT`` (1), giving the concatenation order needed to recompute
      the parent. Integers, never booleans (JCS interop — see module docstring).

    ``leaf_index`` and ``tree_size`` are retained so a verifier can sanity-check
    the proof shape, but the recomputation in :meth:`verify` depends only on the
    path + directions + the leaf hash.
    """

    leaf_index: int
    tree_size: int
    leaf_hash: bytes
    merkle_path: list[bytes] = field(default_factory=list)
    merkle_path_directions: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.merkle_path) != len(self.merkle_path_directions):
            raise MerkleError(
                "merkle_path and merkle_path_directions must have equal length "
                f"(got {len(self.merkle_path)} and "
                f"{len(self.merkle_path_directions)})"
            )
        for d in self.merkle_path_directions:
            if d not in (SIBLING_LEFT, SIBLING_RIGHT):
                raise MerkleError(
                    f"invalid direction {d!r}; must be {SIBLING_LEFT} "
                    f"(sibling left) or {SIBLING_RIGHT} (sibling right)"
                )

    def compute_root(self) -> bytes:
        """Recompute the tree root from this leaf + sibling path.

        Deterministic and dependency-free — this is exactly the arithmetic an
        offline third-party verifier runs (R25-EU01 AC-7). Starts at the leaf
        hash and folds in each sibling using its recorded direction.
        """
        running = self.leaf_hash
        for sibling, direction in zip(self.merkle_path, self.merkle_path_directions):
            if direction == SIBLING_LEFT:
                running = _hash_node(sibling, running)
            else:  # SIBLING_RIGHT
                running = _hash_node(running, sibling)
        return running

    def verify(self, expected_root: bytes) -> bool:
        """Return ``True`` iff recomputing the root from the path equals
        ``expected_root``. Constant-time comparison resists timing oracles."""
        return hmac_compare(self.compute_root(), expected_root)

    def to_bundle(self) -> dict[str, Any]:
        """Serialize to the R25-EU01 §358 Proof Bundle Schema (partial).

        Emits only the Merkle-tree-owned fields; the batcher/committer (PR-3/5)
        wrap these with ``record_id``, ``batch_id``, Rekor anchor fields, etc.
        Hashes are lowercase hex; directions are integers.
        """
        return {
            "leaf_index": self.leaf_index,
            "tree_size": self.tree_size,
            "merkle_path": [h.hex() for h in self.merkle_path],
            "merkle_path_directions": list(self.merkle_path_directions),
        }


def hmac_compare(a: bytes, b: bytes) -> bool:
    """Constant-time bytes equality (delegates to :func:`hmac.compare_digest`)."""
    return hmac.compare_digest(a, b)


class MerkleTree:
    """An immutable RFC 6962 Merkle tree over a fixed list of leaf hashes.

    Construct with :meth:`from_records` (records -> leaf hashes via
    :func:`leaf_hash_for_record`) or :meth:`from_leaf_hashes` (precomputed
    leaves, e.g. when the batcher already hashed them). The tree is built once
    at construction; ``root`` and inclusion proofs are then pure reads.

    An empty tree is rejected: RFC 6962 leaves the empty-tree root as the hash
    of the empty string, but Layer 5 never commits an empty batch, so an empty
    build almost certainly indicates a caller bug and is surfaced loudly.

    Thread safety: a constructed tree is **immutable** — all levels are built in
    ``__init__`` and every public accessor (``root``, ``inclusion_proof``, ...)
    is a pure read with no shared mutable state. Concurrent reads from multiple
    threads are therefore safe WITHOUT external locking. (The PR-3 batcher and
    PR-5 committer rely on this: they build a tree once per batch and may hand
    it to concurrent proof-generation calls.) The defensive copy of the input
    list in ``__init__`` also means later mutation of the caller's list cannot
    alter an already-built tree.
    """

    def __init__(self, leaf_hashes: list[bytes]) -> None:
        if not leaf_hashes:
            raise MerkleError("cannot build a Merkle tree from zero leaves")
        if len(leaf_hashes) > MAX_TREE_SIZE:
            raise MerkleError(
                f"refusing to build a Merkle tree with {len(leaf_hashes)} leaves; "
                f"exceeds MAX_TREE_SIZE ({MAX_TREE_SIZE}). A batch this large "
                f"indicates a caller bug or unbounded input — the batch contract "
                f"is AttestationConfig.batch_max_records, not this hard ceiling."
            )
        # Defensive copy so the tree is immutable w.r.t. caller mutation.
        self._leaves: list[bytes] = list(leaf_hashes)
        # _levels[0] = leaves; _levels[-1] = [root]. Built bottom-up once.
        self._levels: list[list[bytes]] = self._build_levels(self._leaves)

    @classmethod
    def from_leaf_hashes(cls, leaf_hashes: list[bytes]) -> "MerkleTree":
        """Build from precomputed RFC 6962 leaf hashes (each already 0x00-prefixed)."""
        return cls(leaf_hashes)

    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> "MerkleTree":
        """Build from governed-trace records, hashing each via :func:`leaf_hash_for_record`."""
        return cls([leaf_hash_for_record(r) for r in records])

    @staticmethod
    def _build_levels(leaves: list[bytes]) -> list[list[bytes]]:
        """Build all tree levels bottom-up with RFC 6962 §2.1 odd-node padding.

        For each level with an odd count, the last node is duplicated (paired
        with itself) to form its parent. Iterates until a single root remains.
        """
        levels: list[list[bytes]] = [list(leaves)]
        current = leaves
        while len(current) > 1:
            nxt: list[bytes] = []
            for i in range(0, len(current), 2):
                left = current[i]
                # §2.1: duplicate the last node when the count is odd.
                right = current[i + 1] if i + 1 < len(current) else current[i]
                nxt.append(_hash_node(left, right))
            levels.append(nxt)
            current = nxt
        return levels

    @property
    def root(self) -> bytes:
        """The Merkle root (32 raw bytes)."""
        return self._levels[-1][0]

    @property
    def root_hex(self) -> str:
        """The Merkle root as a lowercase hex string (Proof Bundle Schema form)."""
        return self.root.hex()

    @property
    def size(self) -> int:
        """Number of leaves in the tree."""
        return len(self._leaves)

    def leaf_hash_at(self, index: int) -> bytes:
        """Return the leaf hash at ``index`` (raises ``IndexError`` if out of range)."""
        if not 0 <= index < self.size:
            raise IndexError(
                f"leaf index {index} out of range for tree of size {self.size}"
            )
        return self._leaves[index]

    def inclusion_proof(self, index: int) -> InclusionProof:
        """Build the RFC 6962 inclusion proof for the leaf at ``index``.

        Walks bottom-up: at each level the node's sibling is recorded together
        with its direction. When a node is the duplicated last node of an odd
        level, its sibling is itself (``SIBLING_RIGHT``) — the same padding the
        tree was built with, so the verifier recomputes the identical parent.
        """
        if not 0 <= index < self.size:
            raise IndexError(
                f"leaf index {index} out of range for tree of size {self.size}"
            )

        path: list[bytes] = []
        directions: list[int] = []
        idx = index
        # Walk every level except the root level.
        for level in self._levels[:-1]:
            if idx % 2 == 0:
                # Even position -> sibling is to the right (or self, if padded).
                sibling_idx = idx + 1
                if sibling_idx < len(level):
                    path.append(level[sibling_idx])
                else:
                    path.append(level[idx])  # §2.1 duplicated-self padding
                directions.append(SIBLING_RIGHT)
            else:
                # Odd position -> sibling is to the left (always exists).
                path.append(level[idx - 1])
                directions.append(SIBLING_LEFT)
            idx //= 2

        return InclusionProof(
            leaf_index=index,
            tree_size=self.size,
            leaf_hash=self._leaves[index],
            merkle_path=path,
            merkle_path_directions=directions,
        )
