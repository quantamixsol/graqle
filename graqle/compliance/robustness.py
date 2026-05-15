"""EU AI Act Article 15 robustness attestation surfaces.

Article 15 paragraph 1 (Regulation (EU) 2024/1689):

> "High-risk AI systems shall be designed and developed in such a way
> that they achieve an appropriate level of accuracy, robustness, and
> cybersecurity, and that they perform consistently in those respects
> throughout their lifecycle."

GraQle is NOT itself a high-risk AI system (no Annex III category
applies to a developer-side reasoning SDK), so Article 15 does not
apply to GraQle *as a direct obligation*. But integrators who embed
GraQle in their own high-risk AI system need the SDK to surface the
specific defences it provides so they can quote them in *their*
Article 15 file. This module is the machine-readable counterpart to
``docs/compliance/eu-ai-act/article-15-robustness.md``.

The attestation is **static** — it lists what defences ship with the
SDK at this version. The on-disk article-15-robustness.md doc remains
the source of truth for the human-readable narrative + the
defence-by-defence "Where in the codebase" pointers; this module is
the machine-parseable summary for compliance pipelines.

No runtime probing happens here. Adding "did the CI gate pass on this
machine right now" would be a different module (and a different
compliance question — that's about deployment, not the SDK).
"""

# ── graqle:intelligence ──
# module: graqle.compliance.robustness
# risk: LOW (impact radius: 1 module — compliance/__init__.py re-exports)
# consumers: (future) graqle.cli.commands.compliance for --include robustness
# dependencies: __future__, dataclasses, typing
# constraints: side-effect-free, read-only
# ── /graqle:intelligence ──

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Each defence is a triple of (id, threat-class-addressed, code-pointer).
# The ids are stable identifiers that a customer's compliance pipeline
# can reference; the threat-class is the kind of attack/failure mode
# the defence prevents; the code-pointer is a relative path into the
# SDK source so the customer's auditor can read the actual code.
_DEFENCES: tuple[tuple[str, str, str], ...] = (
    (
        "cr-003-edge-loss-shrink-guard",
        "silent_data_corruption",
        "graqle/core/graph.py:_write_with_lock",
    ),
    (
        "cr-008-savestatus-disambiguation",
        "error_classification",
        "graqle/plugins/mcp_dev_server.py:_save_graph",
    ),
    (
        "secret-patterns-scan",
        "confidentiality_output_leak",
        "graqle/core/secret_patterns.py",
    ),
    (
        "cr-004-graph-health-never-raises-probe",
        "probe_failure_cascade",
        "graqle/activation/health_probe.py",
    ),
    (
        "cr-005a-stdout-path-toctou-safe",
        "path_traversal_subprocess_capture",
        "graqle/plugins/mcp_dev_server.py:_handle_bash",
    ),
    (
        "ip-content-gate-pre-commit",
        "trade_secret_leakage",
        "graqle/plugins/mcp_dev_server.py:_handle_git_commit",
    ),
    (
        "governance-gates-cg-01-to-cg-20",
        "native_tool_bypass",
        "graqle/governance/",
    ),
    (
        "ip-protection-gate-ci",
        "trade_secret_leakage_ci",
        ".github/workflows/ip-content-gate.yml",
    ),
    (
        "pip-audit-cve-scan-ci",
        "known_vulnerable_dependency",
        ".github/workflows/ci.yml",
    ),
    (
        "atomic-file-writes",
        "mid_write_corruption",
        "graqle/core/graph.py:_write_with_lock",
    ),
    (
        "frozen-dataclass-result-types",
        "post_construction_mutation",
        "graqle/core/graph_health.py + graqle/plugins/mcp_dev_server.py",
    ),
    (
        "type-name-only-exception-messages",
        "path_credential_leak_via_exception",
        "graqle/plugins/mcp_dev_server.py:_save_graph",
    ),
    (
        "pypi-trusted-publishing-oidc",
        "supply_chain_token_compromise",
        ".github/workflows/ci.yml + SECURITY.md",
    ),
    (
        "sigstore-signatures-on-releases",
        "release_artifact_tampering",
        "graq trustctl verify + SECURITY.md",
    ),
    (
        "cyclonedx-sbom-per-release",
        "dependency_provenance_opacity",
        "GitHub Releases attachments + SECURITY.md",
    ),
    (
        "pth-file-guard-publish-pipeline",
        "litellm_class_supply_chain_attack",
        ".github/workflows/ci.yml publish step + SECURITY.md",
    ),
    (
        "reproducible-builds-source-date-epoch",
        "non_reproducible_artifact_class",
        "SECURITY.md + ci.yml build step",
    ),
)

# Measurable claims — each a triple of (metric_id, claim_value,
# evidence_pointer). The evidence pointer is the test or CI surface
# that enforces the claim continuously.
#
# IMPORTANT: claim values are written with COMPARATIVE operators ("< 5",
# ">= 5000", "0") rather than absolute snapshots ("5,547") to avoid
# staleness drift between releases. The CI evidence pointer is the
# truth-grounding for each claim; the value here is the floor / ceiling
# the SDK commits to maintaining.
_MEASURABLE_CLAIMS: tuple[tuple[str, str, str], ...] = (
    (
        "graph_health_probe_p95_latency_ms",
        "< 5",
        "tests/test_activation/test_graph_health_probe.py::test_p95_under_5ms",
    ),
    (
        "test_suite_size",
        ">= 5000",
        "pytest tests/ + CI run record per release",
    ),
    (
        "test_pass_rate_on_master",
        "100%",
        "CI status badge + GitHub Actions history",
    ),
    (
        "cve_vulnerable_dependencies_on_master",
        "0",
        "pip-audit CI check (every PR)",
    ),
    (
        "trade_secret_leak_rate_on_public_master",
        "0",
        "ip-protection-gate CI check (every PR)",
    ),
    (
        "phantom_write_collision_rate_neo4j_sessions",
        "0",
        "CR-008 SaveStatus disambiguation",
    ),
    (
        "silent_edge_loss_rate_graphs_over_100_edges",
        "0",
        "CR-003 shrink guard",
    ),
)

# Cybersecurity-specific stance items — categorical NO-rather-than-claim
# negatives that an auditor would otherwise have to grep for.
_CYBERSECURITY_NEGATIVES: tuple[tuple[str, str], ...] = (
    (
        "shell_injection_surface",
        "limited to graq_bash with blocklist scan",
    ),
    (
        "deserialisation_of_untrusted_data",
        "none — no pickle.loads, no yaml.unsafe_load, no eval/exec of user input",
    ),
    (
        "ssrf_surface",
        "none — graq_web_search is the only network surface and is per-call permission gated",
    ),
    (
        "license_key_storage",
        "SecretStr with constant-time equality (graqle.config.resolver.SecretStr)",
    ),
)

# Adversarial-input boundary statement — a flat-out non-claim, surfaced
# in the attestation so integrators cannot miss it.
_ADVERSARIAL_INPUT_BOUNDARY: str = (
    "GraQle's reasoning pipeline (graq_reason / graq_predict) is NOT a "
    "security boundary for adversarial-input attacks against the underlying "
    "LLM. Integrators must treat LLM outputs as untrusted text, apply their "
    "own input/output sanitisation, and not use GraQle outputs as the sole "
    "basis for security-critical decisions."
)

# Security disclosure contact + canonical policy URL. These match the
# repository's SECURITY.md (canonical source).
_SECURITY_DISCLOSURE_EMAIL: str = "security@quantamixsolutions.com"
_SECURITY_POLICY_URL: str = (
    "https://github.com/quantamixsol/graqle/blob/master/SECURITY.md"
)


@dataclass(frozen=True)
class Defence:
    """One row of the Article 15 defence-in-depth inventory."""

    id: str
    threat_class: str
    code_pointer: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "threat_class": self.threat_class,
            "code_pointer": self.code_pointer,
        }


@dataclass(frozen=True)
class MeasurableClaim:
    """One measurable robustness/accuracy claim with its evidence pointer."""

    metric_id: str
    claim: str
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {
            "metric_id": self.metric_id,
            "claim": self.claim,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class RobustnessAttestation:
    """Machine-readable Article 15 attestation for compliance pipelines.

    Fields:
        defences          : list of named defences with threat-class +
                            code pointer.
        measurable_claims : list of metric-id + claim-value + evidence
                            pointer triples.
        cybersecurity_negatives : flat dict of categorical
                            non-presence statements (e.g. no SSRF).
        adversarial_input_boundary : free-text non-claim about LLM
                            adversarial-input risk.
        security_disclosure_email : canonical disclosure address.
        security_policy_url       : canonical disclosure policy URL.
        article_15_indirect       : Always True — GraQle is not itself
                            a high-risk AI system, but provides
                            primitives a deployer quotes in THEIR
                            Article 15 file.
        article_15_aligned        : Always True — boolean flag that
                            says "this SDK ships the defences listed
                            here". This is the marketing-claim-grade
                            field; ``article_15_compliant`` and
                            ``article_15_certified`` are deliberately
                            NEVER fields here (we don't claim either).
    """

    defences: list[dict[str, str]]
    measurable_claims: list[dict[str, str]]
    cybersecurity_negatives: dict[str, str]
    adversarial_input_boundary: str
    security_disclosure_email: str
    security_policy_url: str
    article_15_indirect: bool = True
    article_15_aligned: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "defences": self.defences,
            "measurable_claims": self.measurable_claims,
            "cybersecurity_negatives": self.cybersecurity_negatives,
            "adversarial_input_boundary": self.adversarial_input_boundary,
            "security_disclosure_email": self.security_disclosure_email,
            "security_policy_url": self.security_policy_url,
            "article_15_indirect": self.article_15_indirect,
            "article_15_aligned": self.article_15_aligned,
        }


def build_robustness_attestation() -> RobustnessAttestation:
    """Build the machine-readable Article 15 attestation.

    All values are pulled from the module-level constants above;
    nothing on the filesystem is read. The result is identical across
    runs of the same SDK version — this is a static description of the
    shipped defences, not a runtime probe.
    """
    return RobustnessAttestation(
        defences=[
            Defence(id=did, threat_class=tc, code_pointer=cp).to_dict()
            for did, tc, cp in _DEFENCES
        ],
        measurable_claims=[
            MeasurableClaim(metric_id=mid, claim=c, evidence=e).to_dict()
            for mid, c, e in _MEASURABLE_CLAIMS
        ],
        cybersecurity_negatives=dict(_CYBERSECURITY_NEGATIVES),
        adversarial_input_boundary=_ADVERSARIAL_INPUT_BOUNDARY,
        security_disclosure_email=_SECURITY_DISCLOSURE_EMAIL,
        security_policy_url=_SECURITY_POLICY_URL,
        article_15_indirect=True,
        article_15_aligned=True,
    )
