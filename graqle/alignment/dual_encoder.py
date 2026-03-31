"""R10 Correction Approach C — Dual-Encoder Fine-Tuning (optional torch)."""

# ── graqle:intelligence ──
# module: graqle.alignment.dual_encoder
# risk: HIGH (impact radius: 1 module)
# consumers: alignment.pipeline
# dependencies: numpy, torch (OPTIONAL), graqle.alignment.types, graqle.alignment.embedding_store
# constraints: torch must be optional — graceful ImportError when unavailable
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
from typing import Any, List, Tuple

import numpy as np

from graqle.alignment.embedding_store import EmbeddingStore
from graqle.alignment.measurement import measure_alignment
from graqle.alignment.types import AlignmentPair, AlignmentReport

logger = logging.getLogger("graqle.alignment.dual_encoder")

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    TORCH_AVAILABLE = False


def _sample_negative_pairs(
    graph: Any,
    embedding_store: EmbeddingStore,
    positive_pairs: List[AlignmentPair],
    n: int,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Sample random cross-language negative pairs NOT connected by CALLS_VIA_MCP."""
    positive_set = {
        (p.ts_node_id, p.py_node_id) for p in positive_pairs
    }

    # Collect TS and PY node IDs with embeddings
    ts_ids: list[str] = []
    py_ids: list[str] = []
    for nid, node in graph.nodes.items():
        lang = node.properties.get("language", "")
        if lang == "typescript" and embedding_store.has_embedding(nid):
            ts_ids.append(nid)
        elif lang == "python" and embedding_store.has_embedding(nid):
            py_ids.append(nid)

    if not ts_ids or not py_ids:
        return []

    rng = np.random.default_rng(42)
    negatives: list[tuple[np.ndarray, np.ndarray]] = []
    attempts = 0
    max_attempts = n * 10

    while len(negatives) < n and attempts < max_attempts:
        ts_id = rng.choice(ts_ids)
        py_id = rng.choice(py_ids)
        if (ts_id, py_id) not in positive_set:
            ts_emb = embedding_store.get(ts_id)
            py_emb = embedding_store.get(py_id)
            if ts_emb is not None and py_emb is not None:
                negatives.append((ts_emb, py_emb))
        attempts += 1

    return negatives


def apply_dual_encoder_correction(
    pairs: List[AlignmentPair],
    graph: Any,
    embedding_store: EmbeddingStore,
    epochs: int = 10,
    learning_rate: float = 1e-4,
    margin: float = 0.3,
    embedding_dim: int = 384,
) -> AlignmentReport:
    """Dual-encoder fine-tuning with contrastive loss.

    Learns lightweight projection heads (384 → 384) for each language
    to align cross-language pairs and separate non-pairs.

    Requires torch. Raises ImportError if torch is unavailable.

    Parameters
    ----------
    pairs:
        Positive alignment pairs (CALLS_VIA_MCP connected).
    graph:
        Graqle instance for node language detection.
    embedding_store:
        Store to read/write corrected embeddings.
    epochs:
        Training epochs (default 10).
    learning_rate:
        Adam learning rate (default 1e-4).
    margin:
        Contrastive loss margin (default 0.3).
    embedding_dim:
        Embedding dimensionality (default 384).
    """
    if not TORCH_AVAILABLE:
        raise ImportError(
            "torch is required for DualEncoder correction. "
            "Install with: pip install graqle[alignment-gpu]"
        )

    # Build positive pairs
    positive_data = [(p.ts_embedding, p.py_embedding) for p in pairs]

    # Build negative pairs (3x ratio)
    negative_data = _sample_negative_pairs(
        graph, embedding_store, pairs, n=len(pairs) * 3,
    )

    if not positive_data:
        logger.warning("No positive pairs for dual encoder training")
        return measure_alignment(graph, embedding_store)

    # Dataset
    class _AlignmentDataset(Dataset):
        def __init__(self, pos: list, neg: list):
            self.items = [(ts, py, 0) for ts, py in pos]  # 0 = positive
            self.items += [(ts, py, 1) for ts, py in neg]  # 1 = negative

        def __len__(self):
            return len(self.items)

        def __getitem__(self, idx):
            ts_emb, py_emb, label = self.items[idx]
            return (
                torch.tensor(ts_emb, dtype=torch.float32),
                torch.tensor(py_emb, dtype=torch.float32),
                torch.tensor(label, dtype=torch.float32),
            )

    dataset = _AlignmentDataset(positive_data, negative_data)
    loader = DataLoader(dataset, batch_size=16, shuffle=True)

    # Lightweight projection heads
    ts_projector = nn.Sequential(
        nn.Linear(embedding_dim, embedding_dim),
        nn.ReLU(),
        nn.Linear(embedding_dim, embedding_dim),
    )
    py_projector = nn.Sequential(
        nn.Linear(embedding_dim, embedding_dim),
        nn.ReLU(),
        nn.Linear(embedding_dim, embedding_dim),
    )

    optimizer = torch.optim.Adam(
        list(ts_projector.parameters()) + list(py_projector.parameters()),
        lr=learning_rate,
    )

    # Training loop
    for epoch in range(epochs):
        total_loss = 0.0
        for ts_batch, py_batch, labels in loader:
            ts_proj = ts_projector(ts_batch)
            py_proj = py_projector(py_batch)

            # Normalize to unit sphere
            ts_proj = ts_proj / (ts_proj.norm(dim=1, keepdim=True) + 1e-8)
            py_proj = py_proj / (py_proj.norm(dim=1, keepdim=True) + 1e-8)

            # Contrastive loss
            distances = 1.0 - torch.sum(ts_proj * py_proj, dim=1)
            pos_loss = (1 - labels) * distances ** 2
            neg_loss = labels * torch.clamp(margin - distances, min=0) ** 2
            loss = (pos_loss + neg_loss).mean()

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        logger.debug("Epoch %d/%d loss=%.4f", epoch + 1, epochs, total_loss)

    logger.info("Dual encoder training complete (%d epochs)", epochs)

    # Apply projectors to all embeddings
    with torch.no_grad():
        for node_id, embedding in embedding_store.items():
            node = graph.nodes.get(node_id)
            if node is None:
                continue
            lang = node.properties.get("language", "")
            emb_tensor = torch.tensor(embedding, dtype=torch.float32).unsqueeze(0)

            if lang == "typescript":
                projected = ts_projector(emb_tensor).squeeze(0).numpy()
            elif lang == "python":
                projected = py_projector(emb_tensor).squeeze(0).numpy()
            else:
                continue

            # Normalize
            norm = np.linalg.norm(projected)
            if norm > 0:
                projected = projected / norm
            embedding_store.update(node_id, projected)

    # Re-measure
    post_report = measure_alignment(graph, embedding_store)
    post_report.correction_applied = "dual_encoder"
    return post_report
