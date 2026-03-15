"""Log fetchers for each cloud provider and local dev environments.

Each fetcher implements the LogFetcher protocol and returns structured
RuntimeEvent objects ready for KG ingestion.
"""

# ── graqle:intelligence ──
# module: graqle.runtime.fetcher
# risk: MEDIUM (impact radius: 2 modules)
# consumers: kg_builder, __init__
# dependencies: __future__, hashlib, logging, re, time +4 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import hashlib
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("graqle.runtime.fetcher")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RuntimeEvent:
    """A single runtime event extracted from logs/metrics."""

    id: str  # Unique content-hash ID (e.g., "rt_cw_abc123")
    category: str  # LAMBDA_TIMEOUT, AUTH_FAILURE, BEDROCK_THROTTLE, ERROR, WARNING, etc.
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    source: str  # "cloudwatch", "azure_monitor", "cloud_logging", "docker", "file"
    service_name: str  # Lambda name, container name, or service identifier
    timestamp: str  # ISO 8601
    hit_count: int  # How many times this error occurred in the window
    message: str  # The actual log message (truncated to 500 chars)
    raw_pattern: str = ""  # The regex pattern that matched
    region: str = ""  # Cloud region where the event occurred
    log_group: str = ""  # Log group / stream identifier
    extra: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        """Deterministic hash for deduplication."""
        key = f"{self.category}:{self.service_name}:{self.message[:200]}"
        return hashlib.sha256(key.encode()).hexdigest()[:12]


@dataclass
class FetchResult:
    """Result of a log fetch operation."""

    events: list[RuntimeEvent]
    source: str
    provider: str
    fetch_duration_ms: float
    time_range_hours: float
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def critical_count(self) -> int:
        return sum(1 for e in self.events if e.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for e in self.events if e.severity == "HIGH")


# ---------------------------------------------------------------------------
# Error patterns — shared classification rules
# ---------------------------------------------------------------------------

# Each pattern: (regex, category, severity)
DEFAULT_ERROR_PATTERNS: list[tuple[str, str, str]] = [
    # Lambda / serverless
    (r"Task timed out after \d+ seconds", "LAMBDA_TIMEOUT", "CRITICAL"),
    (r"Duration: 900000", "LAMBDA_TIMEOUT", "CRITICAL"),
    (r"Runtime\.HandlerNotFound", "LAMBDA_CONFIG_ERROR", "CRITICAL"),
    (r"Runtime\.ImportModuleError", "LAMBDA_IMPORT_ERROR", "CRITICAL"),
    (r"MemorySize: \d+ MB.*Max Memory Used: \d+ MB", "LAMBDA_MEMORY", "HIGH"),
    (r"REPORT.*Duration:\s*(\d{4,})\.\d+\s*ms", "LAMBDA_SLOW", "HIGH"),
    # Auth
    (r"JWT verification failed", "AUTH_FAILURE", "HIGH"),
    (r"Token expired", "AUTH_EXPIRED", "HIGH"),
    (r"Unauthorized|403 Forbidden", "AUTH_UNAUTHORIZED", "HIGH"),
    (r"CORS.*blocked|Access-Control-Allow-Origin", "CORS_ERROR", "HIGH"),
    # AWS services
    (r"ThrottlingException|Rate exceeded", "THROTTLE", "HIGH"),
    (r"Bedrock.*throttl|ModelTimeoutException", "BEDROCK_THROTTLE", "CRITICAL"),
    (r"NoCredentialsError|Unable to locate credentials", "CREDENTIALS_MISSING", "CRITICAL"),
    (r"EndpointConnectionError|ConnectTimeoutError", "CONNECTION_ERROR", "HIGH"),
    (r"Neptune.*timeout|NeptuneColdStart", "NEPTUNE_TIMEOUT", "CRITICAL"),
    # Database
    (r"Connection refused.*:5432|:3306|:27017|:6379", "DB_CONNECTION_REFUSED", "CRITICAL"),
    (r"deadlock detected", "DB_DEADLOCK", "CRITICAL"),
    (r"too many connections", "DB_CONNECTION_POOL", "HIGH"),
    # Generic
    (r"ERROR\s", "ERROR", "MEDIUM"),
    (r"WARN(?:ING)?\s", "WARNING", "LOW"),
    (r"Exception|Traceback", "EXCEPTION", "HIGH"),
    (r"OutOfMemory|MemoryError", "OOM", "CRITICAL"),
    (r"SIGKILL|SIGTERM|killed", "PROCESS_KILLED", "CRITICAL"),
]


def classify_log_line(line: str, custom_patterns: list[tuple[str, str, str]] | None = None) -> tuple[str, str] | None:
    """Classify a log line into (category, severity) using pattern matching.

    Returns None if no pattern matches.
    """
    patterns = (custom_patterns or []) + DEFAULT_ERROR_PATTERNS
    for pattern, category, severity in patterns:
        if re.search(pattern, line, re.IGNORECASE):
            return category, severity
    return None


# ---------------------------------------------------------------------------
# Base fetcher
# ---------------------------------------------------------------------------


class LogFetcher(ABC):
    """Protocol for fetching logs from any source."""

    @abstractmethod
    async def fetch(
        self,
        *,
        hours: float = 6,
        service: str | None = None,
        severity_filter: str = "all",
        max_events: int = 100,
        custom_patterns: list[tuple[str, str, str]] | None = None,
    ) -> FetchResult:
        """Fetch and classify log events.

        Parameters
        ----------
        hours : float
            How far back to look (default: 6 hours).
        service : str | None
            Filter to a specific service/Lambda/container.
        severity_filter : str
            Minimum severity: "all", "low", "medium", "high", "critical".
        max_events : int
            Maximum events to return.
        custom_patterns : list
            Additional (regex, category, severity) patterns.
        """
        ...

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Verify connectivity. Returns status dict."""
        ...


# ---------------------------------------------------------------------------
# AWS CloudWatch fetcher
# ---------------------------------------------------------------------------


class CloudWatchFetcher(LogFetcher):
    """Fetch logs from AWS CloudWatch Logs."""

    def __init__(
        self,
        region: str | None = None,
        log_groups: list[str] | None = None,
        profile: str | None = None,
    ) -> None:
        import os

        self.region = region or os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
        self.log_groups = log_groups or []
        self.profile = profile
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3

            session_kwargs: dict[str, Any] = {"region_name": self.region}
            if self.profile:
                session_kwargs["profile_name"] = self.profile
            session = boto3.Session(**session_kwargs)
            self._client = session.client("logs")
        return self._client

    def health_check(self) -> dict[str, Any]:
        try:
            client = self._get_client()
            # List log groups to verify access
            resp = client.describe_log_groups(limit=1)
            groups = resp.get("logGroups", [])
            return {
                "status": "ok",
                "provider": "aws",
                "source": "cloudwatch",
                "region": self.region,
                "accessible_groups": len(groups),
            }
        except Exception as e:
            return {
                "status": "error",
                "provider": "aws",
                "source": "cloudwatch",
                "error": str(e)[:200],
                "hint": "Check AWS credentials. Run: aws sts get-caller-identity",
            }

    async def fetch(
        self,
        *,
        hours: float = 6,
        service: str | None = None,
        severity_filter: str = "all",
        max_events: int = 100,
        custom_patterns: list[tuple[str, str, str]] | None = None,
    ) -> FetchResult:
        import asyncio

        start_time = time.monotonic()
        errors: list[str] = []
        events: list[RuntimeEvent] = []

        try:
            client = self._get_client()
            end_ms = int(time.time() * 1000)
            start_ms = end_ms - int(hours * 3600 * 1000)

            # Discover log groups if not configured
            log_groups = self._resolve_log_groups(client, service)
            if not log_groups:
                return FetchResult(
                    events=[],
                    source="cloudwatch",
                    provider="aws",
                    fetch_duration_ms=(time.monotonic() - start_time) * 1000,
                    time_range_hours=hours,
                    errors=["No log groups found. Configure runtime_sources.log_groups in graqle.yaml"],
                )

            # Fetch from each log group
            for log_group in log_groups:
                try:
                    group_events = await asyncio.to_thread(
                        self._fetch_log_group,
                        client,
                        log_group,
                        start_ms,
                        end_ms,
                        max_events,
                        custom_patterns,
                    )
                    events.extend(group_events)
                except Exception as e:
                    errors.append(f"{log_group}: {e}")

            # Filter by severity
            events = _filter_severity(events, severity_filter)

            # Deduplicate by content hash
            events = _deduplicate(events)

            # Sort by severity then timestamp
            severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
            events.sort(key=lambda e: (severity_order.get(e.severity, 5), e.timestamp))

            # Limit
            events = events[:max_events]

        except Exception as e:
            errors.append(str(e))

        return FetchResult(
            events=events,
            source="cloudwatch",
            provider="aws",
            fetch_duration_ms=(time.monotonic() - start_time) * 1000,
            time_range_hours=hours,
            errors=errors,
            metadata={"region": self.region, "log_groups": self.log_groups},
        )

    def _resolve_log_groups(self, client: Any, service: str | None) -> list[str]:
        """Resolve log groups — use configured ones, or auto-discover."""
        if self.log_groups:
            # If service filter, narrow down
            if service:
                return [lg for lg in self.log_groups if service.lower() in lg.lower()]
            return self.log_groups

        # Auto-discover Lambda log groups
        groups: list[str] = []
        try:
            paginator = client.get_paginator("describe_log_groups")
            for page in paginator.paginate(logGroupNamePrefix="/aws/lambda/", PaginationConfig={"MaxItems": 50}):
                for group in page.get("logGroups", []):
                    name = group["logGroupName"]
                    if service and service.lower() not in name.lower():
                        continue
                    groups.append(name)
        except Exception:
            pass

        return groups[:20]  # Cap at 20 groups

    def _fetch_log_group(
        self,
        client: Any,
        log_group: str,
        start_ms: int,
        end_ms: int,
        max_events: int,
        custom_patterns: list[tuple[str, str, str]] | None,
    ) -> list[RuntimeEvent]:
        """Fetch and classify events from a single log group."""
        events: list[RuntimeEvent] = []
        seen_hashes: set[str] = set()

        # Use filter_log_events with ERROR pattern to reduce volume
        try:
            resp = client.filter_log_events(
                logGroupName=log_group,
                startTime=start_ms,
                endTime=end_ms,
                filterPattern="?ERROR ?WARN ?Exception ?Timeout ?CRITICAL ?ThrottlingException",
                limit=min(max_events * 2, 500),  # Over-fetch for classification
            )
        except client.exceptions.ResourceNotFoundException:
            return []

        for log_event in resp.get("events", []):
            message = log_event.get("message", "")
            classification = classify_log_line(message, custom_patterns)
            if classification is None:
                continue

            category, severity = classification

            # Extract service name from log group
            service_name = log_group.replace("/aws/lambda/", "").replace("/aws/", "")

            event = RuntimeEvent(
                id="",  # Will be set from content hash
                category=category,
                severity=severity,
                source="cloudwatch",
                service_name=service_name,
                timestamp=datetime.fromtimestamp(
                    log_event.get("timestamp", 0) / 1000, tz=timezone.utc
                ).isoformat(),
                hit_count=1,
                message=message[:500],
                region=self.region,
                log_group=log_group,
            )
            event.id = f"rt_cw_{event.content_hash()}"

            # Deduplicate within this group — aggregate hit counts
            if event.id in seen_hashes:
                for existing in events:
                    if existing.id == event.id:
                        existing.hit_count += 1
                        break
            else:
                seen_hashes.add(event.id)
                events.append(event)

        return events


# ---------------------------------------------------------------------------
# Azure Monitor fetcher
# ---------------------------------------------------------------------------


class AzureMonitorFetcher(LogFetcher):
    """Fetch logs from Azure Monitor / Log Analytics."""

    def __init__(
        self,
        workspace_id: str | None = None,
        subscription_id: str | None = None,
        resource_group: str | None = None,
    ) -> None:
        import os

        self.workspace_id = workspace_id or os.environ.get("AZURE_LOG_ANALYTICS_WORKSPACE_ID")
        self.subscription_id = subscription_id or os.environ.get("AZURE_SUBSCRIPTION_ID")
        self.resource_group = resource_group or os.environ.get("AZURE_RESOURCE_GROUP")

    def health_check(self) -> dict[str, Any]:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.monitor.query import LogsQueryClient

            credential = DefaultAzureCredential()
            client = LogsQueryClient(credential)
            return {
                "status": "ok",
                "provider": "azure",
                "source": "azure_monitor",
                "workspace_id": self.workspace_id or "not_configured",
            }
        except ImportError:
            return {
                "status": "error",
                "provider": "azure",
                "source": "azure_monitor",
                "error": "azure-monitor-query not installed",
                "hint": "pip install azure-monitor-query azure-identity",
            }
        except Exception as e:
            return {
                "status": "error",
                "provider": "azure",
                "source": "azure_monitor",
                "error": str(e)[:200],
            }

    async def fetch(
        self,
        *,
        hours: float = 6,
        service: str | None = None,
        severity_filter: str = "all",
        max_events: int = 100,
        custom_patterns: list[tuple[str, str, str]] | None = None,
    ) -> FetchResult:
        import asyncio

        start_time = time.monotonic()
        errors: list[str] = []
        events: list[RuntimeEvent] = []

        if not self.workspace_id:
            return FetchResult(
                events=[],
                source="azure_monitor",
                provider="azure",
                fetch_duration_ms=(time.monotonic() - start_time) * 1000,
                time_range_hours=hours,
                errors=["AZURE_LOG_ANALYTICS_WORKSPACE_ID not configured"],
            )

        try:
            from datetime import timedelta

            from azure.identity import DefaultAzureCredential
            from azure.monitor.query import LogsQueryClient

            credential = DefaultAzureCredential()
            client = LogsQueryClient(credential)

            # KQL query for errors/warnings
            service_filter = f'| where AppRoleName contains "{service}"' if service else ""
            query = f"""
            AppTraces
            {service_filter}
            | where SeverityLevel >= 2
            | order by TimeGenerated desc
            | take {max_events * 2}
            """

            response = await asyncio.to_thread(
                client.query_workspace,
                self.workspace_id,
                query,
                timespan=timedelta(hours=hours),
            )

            if response.tables:
                for row in response.tables[0].rows:
                    message = str(row[0]) if row else ""
                    classification = classify_log_line(message, custom_patterns)
                    if classification is None:
                        classification = ("ERROR", "MEDIUM")

                    category, severity = classification
                    event = RuntimeEvent(
                        id="",
                        category=category,
                        severity=severity,
                        source="azure_monitor",
                        service_name=service or "unknown",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        hit_count=1,
                        message=message[:500],
                    )
                    event.id = f"rt_az_{event.content_hash()}"
                    events.append(event)

        except ImportError:
            errors.append("azure-monitor-query not installed. pip install azure-monitor-query azure-identity")
        except Exception as e:
            errors.append(str(e)[:200])

        events = _filter_severity(events, severity_filter)
        events = _deduplicate(events)

        return FetchResult(
            events=events[:max_events],
            source="azure_monitor",
            provider="azure",
            fetch_duration_ms=(time.monotonic() - start_time) * 1000,
            time_range_hours=hours,
            errors=errors,
        )


# ---------------------------------------------------------------------------
# GCP Cloud Logging fetcher
# ---------------------------------------------------------------------------


class GCPLoggingFetcher(LogFetcher):
    """Fetch logs from Google Cloud Logging."""

    def __init__(self, project_id: str | None = None) -> None:
        import os

        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")

    def health_check(self) -> dict[str, Any]:
        try:
            from google.cloud import logging as gcp_logging

            client = gcp_logging.Client(project=self.project_id)
            return {
                "status": "ok",
                "provider": "gcp",
                "source": "cloud_logging",
                "project_id": self.project_id or "auto",
            }
        except ImportError:
            return {
                "status": "error",
                "provider": "gcp",
                "source": "cloud_logging",
                "error": "google-cloud-logging not installed",
                "hint": "pip install google-cloud-logging",
            }
        except Exception as e:
            return {
                "status": "error",
                "provider": "gcp",
                "source": "cloud_logging",
                "error": str(e)[:200],
            }

    async def fetch(
        self,
        *,
        hours: float = 6,
        service: str | None = None,
        severity_filter: str = "all",
        max_events: int = 100,
        custom_patterns: list[tuple[str, str, str]] | None = None,
    ) -> FetchResult:
        import asyncio

        start_time = time.monotonic()
        errors: list[str] = []
        events: list[RuntimeEvent] = []

        try:
            from google.cloud import logging as gcp_logging

            client = gcp_logging.Client(project=self.project_id)

            # Build filter
            severity_map = {"critical": "CRITICAL", "high": "ERROR", "medium": "WARNING", "low": "INFO"}
            min_sev = severity_map.get(severity_filter, "WARNING")

            filter_str = f'severity >= {min_sev} AND timestamp >= "{_hours_ago_rfc3339(hours)}"'
            if service:
                filter_str += f' AND resource.labels.function_name = "{service}"'

            entries = await asyncio.to_thread(
                lambda: list(client.list_entries(filter_=filter_str, max_results=max_events * 2))
            )

            for entry in entries:
                message = str(entry.payload) if entry.payload else ""
                classification = classify_log_line(message, custom_patterns)
                if classification is None:
                    # Use GCP severity
                    gcp_sev = getattr(entry, "severity", "DEFAULT")
                    category = "ERROR" if gcp_sev in ("ERROR", "CRITICAL") else "WARNING"
                    severity = "CRITICAL" if gcp_sev == "CRITICAL" else "HIGH" if gcp_sev == "ERROR" else "MEDIUM"
                    classification = (category, severity)

                cat, sev = classification
                event = RuntimeEvent(
                    id="",
                    category=cat,
                    severity=sev,
                    source="cloud_logging",
                    service_name=service or getattr(entry.resource, "labels", {}).get("function_name", "unknown"),
                    timestamp=entry.timestamp.isoformat() if entry.timestamp else datetime.now(timezone.utc).isoformat(),
                    hit_count=1,
                    message=message[:500],
                )
                event.id = f"rt_gcp_{event.content_hash()}"
                events.append(event)

        except ImportError:
            errors.append("google-cloud-logging not installed. pip install google-cloud-logging")
        except Exception as e:
            errors.append(str(e)[:200])

        events = _filter_severity(events, severity_filter)
        events = _deduplicate(events)

        return FetchResult(
            events=events[:max_events],
            source="cloud_logging",
            provider="gcp",
            fetch_duration_ms=(time.monotonic() - start_time) * 1000,
            time_range_hours=hours,
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Local / Docker fetcher
# ---------------------------------------------------------------------------


class LocalLogFetcher(LogFetcher):
    """Fetch logs from local files, Docker containers, or process output."""

    def __init__(self, log_paths: list[str] | None = None) -> None:
        self.log_paths = log_paths or []

    def health_check(self) -> dict[str, Any]:
        import shutil

        sources = []
        if self.log_paths:
            sources.extend(self.log_paths)
        if shutil.which("docker"):
            sources.append("docker")

        return {
            "status": "ok" if sources else "warning",
            "provider": "local",
            "source": "file/docker",
            "log_paths": self.log_paths,
            "docker_available": shutil.which("docker") is not None,
        }

    async def fetch(
        self,
        *,
        hours: float = 6,
        service: str | None = None,
        severity_filter: str = "all",
        max_events: int = 100,
        custom_patterns: list[tuple[str, str, str]] | None = None,
    ) -> FetchResult:
        import asyncio

        start_time = time.monotonic()
        errors: list[str] = []
        events: list[RuntimeEvent] = []

        # Fetch from log files
        for log_path in self.log_paths:
            try:
                file_events = await asyncio.to_thread(
                    self._read_log_file, log_path, hours, custom_patterns
                )
                events.extend(file_events)
            except Exception as e:
                errors.append(f"{log_path}: {e}")

        # Fetch from Docker if available and no specific log paths
        if not self.log_paths or service:
            try:
                docker_events = await asyncio.to_thread(
                    self._read_docker_logs, service, hours, custom_patterns
                )
                events.extend(docker_events)
            except Exception as e:
                errors.append(f"docker: {e}")

        events = _filter_severity(events, severity_filter)
        events = _deduplicate(events)

        return FetchResult(
            events=events[:max_events],
            source="local",
            provider="local",
            fetch_duration_ms=(time.monotonic() - start_time) * 1000,
            time_range_hours=hours,
            errors=errors,
        )

    def _read_log_file(
        self,
        path: str,
        hours: float,
        custom_patterns: list[tuple[str, str, str]] | None,
    ) -> list[RuntimeEvent]:
        """Read and classify a local log file (tail)."""
        from pathlib import Path

        events: list[RuntimeEvent] = []
        log_path = Path(path)
        if not log_path.exists():
            return events

        # Only read files modified within the time window
        mtime = log_path.stat().st_mtime
        if (time.time() - mtime) > hours * 3600:
            return events

        # Read last N lines (avoid loading huge files)
        try:
            content = log_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()[-2000:]  # Last 2000 lines
        except Exception:
            return events

        seen: set[str] = set()
        for line in lines:
            classification = classify_log_line(line, custom_patterns)
            if classification is None:
                continue

            category, severity = classification
            event = RuntimeEvent(
                id="",
                category=category,
                severity=severity,
                source="file",
                service_name=log_path.stem,
                timestamp=datetime.now(timezone.utc).isoformat(),
                hit_count=1,
                message=line[:500],
                log_group=str(log_path),
            )
            event.id = f"rt_file_{event.content_hash()}"
            if event.id in seen:
                for e in events:
                    if e.id == event.id:
                        e.hit_count += 1
                        break
            else:
                seen.add(event.id)
                events.append(event)

        return events

    def _read_docker_logs(
        self,
        service: str | None,
        hours: float,
        custom_patterns: list[tuple[str, str, str]] | None,
    ) -> list[RuntimeEvent]:
        """Read logs from running Docker containers."""
        import shutil
        import subprocess

        events: list[RuntimeEvent] = []
        if not shutil.which("docker"):
            return events

        try:
            # List running containers
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            containers = result.stdout.strip().splitlines()

            if service:
                containers = [c for c in containers if service.lower() in c.lower()]

            for container in containers[:10]:  # Cap at 10 containers
                try:
                    since = f"{int(hours)}h"
                    log_result = subprocess.run(
                        ["docker", "logs", "--since", since, "--tail", "500", container],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    output = log_result.stdout + log_result.stderr
                    seen: set[str] = set()
                    for line in output.splitlines():
                        classification = classify_log_line(line, custom_patterns)
                        if classification is None:
                            continue
                        category, severity = classification
                        event = RuntimeEvent(
                            id="",
                            category=category,
                            severity=severity,
                            source="docker",
                            service_name=container,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            hit_count=1,
                            message=line[:500],
                        )
                        event.id = f"rt_docker_{event.content_hash()}"
                        if event.id in seen:
                            for e in events:
                                if e.id == event.id:
                                    e.hit_count += 1
                                    break
                        else:
                            seen.add(event.id)
                            events.append(event)
                except Exception:
                    continue

        except Exception:
            pass

        return events


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_fetcher(
    provider: str,
    *,
    region: str | None = None,
    log_groups: list[str] | None = None,
    log_paths: list[str] | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    profile: str | None = None,
    **kwargs: Any,
) -> LogFetcher:
    """Create the appropriate log fetcher for the given provider.

    Parameters
    ----------
    provider : str
        One of: "aws", "azure", "gcp", "local", "auto".
        "auto" uses detect_environment() to pick.
    """
    if provider == "auto":
        from graqle.runtime.detector import detect_environment

        env = detect_environment()
        provider = env.provider
        if not region and env.region:
            region = env.region

    if provider == "aws":
        return CloudWatchFetcher(region=region, log_groups=log_groups, profile=profile)
    elif provider == "azure":
        return AzureMonitorFetcher(workspace_id=workspace_id)
    elif provider == "gcp":
        return GCPLoggingFetcher(project_id=project_id)
    else:
        return LocalLogFetcher(log_paths=log_paths)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}


def _filter_severity(events: list[RuntimeEvent], minimum: str) -> list[RuntimeEvent]:
    """Filter events by minimum severity."""
    if minimum == "all":
        return events
    min_rank = _SEVERITY_RANK.get(minimum.upper(), 0)
    return [e for e in events if _SEVERITY_RANK.get(e.severity, 0) >= min_rank]


def _deduplicate(events: list[RuntimeEvent]) -> list[RuntimeEvent]:
    """Deduplicate events by content hash, aggregating hit counts."""
    seen: dict[str, RuntimeEvent] = {}
    for event in events:
        if event.id in seen:
            seen[event.id].hit_count += event.hit_count
        else:
            seen[event.id] = event
    return list(seen.values())


def _hours_ago_rfc3339(hours: float) -> str:
    """Return RFC3339 timestamp for N hours ago."""
    ts = datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=hours)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
