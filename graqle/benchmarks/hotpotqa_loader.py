"""HotpotQA dataset loader — converts multi-hop QA into Graqle KG format.

Each HotpotQA question has:
- 10 context paragraphs (2 gold + 8 distractors)
- Supporting facts: (title, sentence_idx) pairs identifying evidence
- Answer: short text answer
- Type: "comparison" or "bridge"
- Level: "easy", "medium", "hard"

Conversion to Graqle KG:
- Each paragraph title → KG node (entity)
- Supporting fact links → edges between nodes
- Node description = concatenated paragraph sentences
- Entity co-occurrence across paragraphs → additional edges
"""

# ── graqle:intelligence ──
# module: graqle.benchmarks.hotpotqa_loader
# risk: LOW (impact radius: 0 modules)
# dependencies: __future__, json, random, dataclasses, pathlib +2 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx


@dataclass
class HotpotQAQuestion:
    """A single HotpotQA question with its context and answer."""

    id: str
    question: str
    answer: str
    question_type: str  # "comparison" or "bridge"
    level: str  # "easy", "medium", "hard"
    supporting_facts: list[tuple[str, int]]  # (title, sent_idx)
    context: list[tuple[str, list[str]]]  # (title, [sentences])

    @property
    def gold_titles(self) -> set[str]:
        """Titles of the gold (supporting) paragraphs."""
        return {title for title, _ in self.supporting_facts}

    def to_kg(self) -> nx.Graph:
        """Convert this question's context into a knowledge graph.

        Nodes: paragraph titles (entities)
        Node descriptions: full paragraph text
        Edges: co-reference links between paragraphs that share entities
        """
        G = nx.Graph()

        # Build nodes from context paragraphs
        for title, sentences in self.context:
            node_id = _sanitize_id(title)
            is_gold = title in self.gold_titles
            G.add_node(
                node_id,
                label=title,
                type="Document" if not is_gold else "Evidence",
                description=" ".join(sentences),
                is_gold=is_gold,
                sentence_count=len(sentences),
            )

        # Build edges from entity co-occurrence
        titles = [title for title, _ in self.context]
        texts = {title: " ".join(sents).lower() for title, sents in self.context}

        for i, t1 in enumerate(titles):
            for t2 in titles[i + 1:]:
                # Cross-reference: title appears in other paragraph
                t1_lower = t1.lower()
                t2_lower = t2.lower()
                shared = False

                if t1_lower in texts[t2] or t2_lower in texts[t1]:
                    shared = True

                # Supporting facts link gold paragraphs
                if t1 in self.gold_titles and t2 in self.gold_titles:
                    shared = True

                if shared:
                    G.add_edge(
                        _sanitize_id(t1),
                        _sanitize_id(t2),
                        relationship="CO_REFERENCES",
                        weight=1.0,
                    )

        return G


def _sanitize_id(title: str) -> str:
    """Convert title to a valid node ID."""
    return title.replace(" ", "_").replace("(", "").replace(")", "").replace("'", "")[:60]


@dataclass
class HotpotQADataset:
    """Loaded HotpotQA dataset with sampling and filtering."""

    questions: list[HotpotQAQuestion] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> HotpotQADataset:
        """Load from the HotpotQA JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        questions = []
        for item in data:
            context = [(title, sents) for title, sents in item["context"]]
            sf = [(title, idx) for title, idx in item["supporting_facts"]]
            questions.append(HotpotQAQuestion(
                id=item["_id"],
                question=item["question"],
                answer=item["answer"],
                question_type=item.get("type", "unknown"),
                level=item.get("level", "unknown"),
                supporting_facts=sf,
                context=context,
            ))
        return cls(questions=questions)

    def sample(
        self,
        n: int = 100,
        *,
        level: str | None = None,
        question_type: str | None = None,
        seed: int = 42,
    ) -> list[HotpotQAQuestion]:
        """Sample N questions with optional filtering."""
        filtered = self.questions
        if level:
            filtered = [q for q in filtered if q.level == level]
        if question_type:
            filtered = [q for q in filtered if q.question_type == question_type]

        rng = random.Random(seed)
        n = min(n, len(filtered))
        return rng.sample(filtered, n)

    def __len__(self) -> int:
        return len(self.questions)
