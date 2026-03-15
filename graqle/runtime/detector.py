"""Auto-detect runtime environment: AWS, Azure, GCP, or local dev."""

# ── graqle:intelligence ──
# module: graqle.runtime.detector
# risk: LOW (impact radius: 1 modules)
# consumers: __init__
# dependencies: __future__, logging, os, shutil, dataclasses
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger("graqle.runtime.detector")


@dataclass
class EnvironmentInfo:
    """Detected runtime environment details."""

    provider: str  # "aws", "azure", "gcp", "local"
    confidence: float  # 0.0-1.0
    details: dict[str, str] = field(default_factory=dict)
    # AWS-specific
    region: str | None = None
    account_id: str | None = None
    # Azure-specific
    subscription_id: str | None = None
    resource_group: str | None = None
    # GCP-specific
    project_id: str | None = None
    # Available log sources detected
    log_sources: list[str] = field(default_factory=list)

    @property
    def is_cloud(self) -> bool:
        return self.provider in ("aws", "azure", "gcp")


def detect_environment() -> EnvironmentInfo:
    """Auto-detect the runtime environment by checking credentials and CLI tools.

    Detection order (first confident match wins):
    1. AWS — boto3 credentials + region
    2. Azure — azure CLI or AZURE_* env vars
    3. GCP — gcloud CLI or GOOGLE_* env vars
    4. Local — fallback (always available)
    """
    # Try AWS first (most common for Graqle users)
    aws = _detect_aws()
    if aws and aws.confidence >= 0.7:
        return aws

    # Try Azure
    azure = _detect_azure()
    if azure and azure.confidence >= 0.7:
        return azure

    # Try GCP
    gcp = _detect_gcp()
    if gcp and gcp.confidence >= 0.7:
        return gcp

    # Return best partial match or local
    candidates = [c for c in [aws, azure, gcp] if c and c.confidence > 0]
    if candidates:
        best = max(candidates, key=lambda c: c.confidence)
        if best.confidence >= 0.4:
            return best

    return _detect_local()


def _detect_aws() -> EnvironmentInfo | None:
    """Detect AWS environment via boto3 or env vars."""
    confidence = 0.0
    details: dict[str, str] = {}
    region = None
    account_id = None
    log_sources: list[str] = []

    # Check env vars
    if os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"):
        confidence += 0.3
        details["auth"] = "env_vars" if os.environ.get("AWS_ACCESS_KEY_ID") else "profile"

    if os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION"):
        region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
        confidence += 0.2
        details["region_source"] = "env_var"

    # Check for AWS CLI
    if shutil.which("aws"):
        confidence += 0.1
        details["cli"] = "aws"

    # Try boto3 for deeper validation
    try:
        import boto3

        session = boto3.Session()
        creds = session.get_credentials()
        if creds:
            confidence += 0.3
            details["boto3"] = "credentials_found"

            if not region:
                region = session.region_name
                if region:
                    details["region_source"] = "boto3_session"

            # Try STS for account ID (non-blocking)
            try:
                sts = session.client("sts", region_name=region or "us-east-1")
                identity = sts.get_caller_identity()
                account_id = identity.get("Account")
                details["account"] = account_id or "unknown"
                confidence = min(confidence + 0.2, 1.0)
            except Exception as e:
                details["sts_error"] = str(e)[:100]

            # Detect available log sources
            log_sources.append("cloudwatch")
            try:
                session.client("xray", region_name=region or "us-east-1")
                log_sources.append("xray")
            except Exception:
                pass

    except ImportError:
        details["boto3"] = "not_installed"

    if confidence <= 0:
        return None

    return EnvironmentInfo(
        provider="aws",
        confidence=min(confidence, 1.0),
        details=details,
        region=region,
        account_id=account_id,
        log_sources=log_sources,
    )


def _detect_azure() -> EnvironmentInfo | None:
    """Detect Azure environment via env vars or CLI."""
    confidence = 0.0
    details: dict[str, str] = {}
    subscription_id = None
    resource_group = None
    log_sources: list[str] = []

    # Check env vars
    if os.environ.get("AZURE_SUBSCRIPTION_ID"):
        subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
        confidence += 0.4
        details["auth"] = "env_vars"

    if os.environ.get("AZURE_RESOURCE_GROUP"):
        resource_group = os.environ["AZURE_RESOURCE_GROUP"]
        confidence += 0.1

    if os.environ.get("AZURE_CLIENT_ID") and os.environ.get("AZURE_TENANT_ID"):
        confidence += 0.3
        details["service_principal"] = "configured"

    # Check for Azure CLI
    if shutil.which("az"):
        confidence += 0.2
        details["cli"] = "az"

    # Try azure SDK
    try:
        from azure.identity import DefaultAzureCredential

        cred = DefaultAzureCredential()
        confidence += 0.2
        details["sdk"] = "azure-identity"
        log_sources.append("azure_monitor")
        log_sources.append("log_analytics")
    except ImportError:
        details["sdk"] = "not_installed"
    except Exception:
        pass

    if confidence <= 0:
        return None

    return EnvironmentInfo(
        provider="azure",
        confidence=min(confidence, 1.0),
        details=details,
        subscription_id=subscription_id,
        resource_group=resource_group,
        log_sources=log_sources,
    )


def _detect_gcp() -> EnvironmentInfo | None:
    """Detect GCP environment via env vars or CLI."""
    confidence = 0.0
    details: dict[str, str] = {}
    project_id = None
    log_sources: list[str] = []

    # Check env vars
    if os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT"):
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
        confidence += 0.4
        details["auth"] = "env_vars"

    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        confidence += 0.3
        details["credentials"] = "service_account_file"

    # Check for gcloud CLI
    if shutil.which("gcloud"):
        confidence += 0.2
        details["cli"] = "gcloud"

    # Try google SDK
    try:
        from google.cloud import logging as gcp_logging  # noqa: F811

        confidence += 0.2
        details["sdk"] = "google-cloud-logging"
        log_sources.append("cloud_logging")
    except ImportError:
        details["sdk"] = "not_installed"

    if confidence <= 0:
        return None

    return EnvironmentInfo(
        provider="gcp",
        confidence=min(confidence, 1.0),
        details=details,
        project_id=project_id,
        log_sources=log_sources,
    )


def _detect_local() -> EnvironmentInfo:
    """Local dev environment — always available."""
    log_sources = ["file"]

    # Check for Docker
    if shutil.which("docker"):
        log_sources.append("docker")

    # Check for common local log paths
    for log_dir in ["/var/log", "logs", "./logs", ".logs"]:
        if os.path.isdir(log_dir):
            log_sources.append(f"directory:{log_dir}")
            break

    return EnvironmentInfo(
        provider="local",
        confidence=1.0,
        details={"type": "local_development"},
        log_sources=log_sources,
    )
