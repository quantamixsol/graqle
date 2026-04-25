"""graqle.embeddings — R23 GSEFT scaffold (ADR-206).

Governance-Supervised Embedding Fine-Tuning (GSEFT) infrastructure.
Training pipeline deferred pending dataset curation (R24 milestone).

B2 (FB-006): This package contains NO Bedrock calls, boto3 imports, or AWS
credentials. If Bedrock inference is added in R24, every call must explicitly
pass aws_region and aws_profile — never infer from environment alone.
"""

from graqle.embeddings.model_registry import EmbeddingModelRegistry

__all__ = ["EmbeddingModelRegistry"]
