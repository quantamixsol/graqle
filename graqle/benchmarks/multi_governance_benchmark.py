"""
Multi-Governance Benchmark — 3-Tier Evaluation for Graqle.

Tier A: Single-Regulation (10 questions)
    Tests basic retrieval within one regulation.
    Single-agent should perform reasonably here.

Tier B: Cross-Regulation (10 questions)
    Tests reasoning across 2 regulations (e.g., AI Act + GDPR).
    Graqle advantage: PCST activates nodes from both frameworks.

Tier C: Complex Inter-Domain (10 questions)
    Tests reasoning across 3+ regulations with conditional logic.
    Graqle should significantly outperform: requires message passing
    across distant nodes, conflict detection, and hierarchical aggregation.

This benchmark demonstrates Graqle's core thesis:
    "Graph topology-aware distributed reasoning outperforms
     single-agent approaches on multi-hop regulatory queries."
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GovernanceQuestion:
    """A multi-governance benchmark question."""

    id: str
    tier: str  # "A" (single), "B" (cross), "C" (complex)
    question: str
    expected_answer: str
    frameworks: list[str]  # which regulations are needed
    key_nodes: list[str]  # KG node IDs that contain the answer
    keywords: list[str]  # expected answer keywords for F1 scoring


# =========================================================================
# TIER A: Single-Regulation Queries (10 questions)
# =========================================================================

TIER_A_QUESTIONS = [
    GovernanceQuestion(
        id="MG-A01", tier="A",
        question="What AI practices are completely prohibited under the EU AI Act, and what are the penalties?",
        expected_answer=(
            "Article 5 prohibits: subliminal manipulation, exploitation of vulnerabilities, social scoring "
            "by public authorities, real-time remote biometric identification in public spaces (with limited "
            "exceptions for law enforcement), untargeted scraping for facial recognition databases, emotion "
            "recognition in workplace and education, and biometric categorisation using sensitive characteristics. "
            "Under Article 99, violations carry fines up to EUR 35 million or 7% of worldwide annual turnover."
        ),
        frameworks=["EU_AI_Act"],
        key_nodes=["aiact_art5_prohibited", "aiact_art99_penalties"],
        keywords=["prohibited", "subliminal", "social scoring", "biometric", "EUR 35 million", "7%"],
    ),
    GovernanceQuestion(
        id="MG-A02", tier="A",
        question="What is the complete compliance chain a provider must follow to place a high-risk AI system on the EU market?",
        expected_answer=(
            "The provider must follow this compliance chain: (1) Implement risk management system (Art. 9); "
            "(2) Ensure data governance for training data (Art. 10); (3) Draw up technical documentation (Art. 11); "
            "(4) Ensure record-keeping and logging (Art. 12); (5) Provide transparency and instructions for use (Art. 13); "
            "(6) Design for human oversight (Art. 14); (7) Achieve accuracy, robustness and cybersecurity (Art. 15); "
            "(8) Establish quality management system (Art. 17); (9) Complete conformity assessment (Art. 43); "
            "(10) Affix CE marking (Art. 48); (11) Register in EU database (Art. 49). Only after all steps "
            "can the system be lawfully placed on the market."
        ),
        frameworks=["EU_AI_Act"],
        key_nodes=["aiact_provider", "aiact_art9_risk_mgmt", "aiact_art17_qms", "aiact_art43_conformity", "concept_ce_marking"],
        keywords=["risk management", "data governance", "conformity assessment", "CE marking", "EU database"],
    ),
    GovernanceQuestion(
        id="MG-A03", tier="A",
        question="What are the obligations of deployers of high-risk AI systems regarding human oversight?",
        expected_answer=(
            "Under Article 26, deployers must assign human oversight to natural persons with necessary "
            "competence, training and authority. Under Article 14, the system must be designed to enable "
            "individuals to: fully understand system capacities and limitations, monitor operation, "
            "remain aware of automation bias, correctly interpret outputs, decide not to use the system, "
            "override or reverse outputs, and intervene through a stop button. For biometric identification "
            "(Annex III point 1(a)), at least two natural persons must verify and confirm any action."
        ),
        frameworks=["EU_AI_Act"],
        key_nodes=["aiact_art26_deployer", "aiact_art14_human_oversight"],
        keywords=["deployer", "human oversight", "competence", "training", "override", "stop button", "two natural persons"],
    ),
    GovernanceQuestion(
        id="MG-A04", tier="A",
        question="What specific requirements does the EU AI Act impose on general-purpose AI models with systemic risk?",
        expected_answer=(
            "Under Article 51, a GPAI model is classified as having systemic risk when training computation "
            "exceeds 10^25 FLOPs. Article 55 requires such providers to: perform model evaluations with "
            "standardised protocols including adversarial testing; assess and mitigate systemic risks at "
            "Union level; keep track of and report serious incidents to the AI Office; ensure adequate "
            "cybersecurity protection. Article 52 requires all GPAI providers to maintain technical "
            "documentation, provide information to downstream providers, and have a copyright policy."
        ),
        frameworks=["EU_AI_Act"],
        key_nodes=["aiact_art51_gpai_systemic"],
        keywords=["10^25 FLOPs", "systemic risk", "adversarial testing", "AI Office", "cybersecurity", "GPAI"],
    ),
    GovernanceQuestion(
        id="MG-A05", tier="A",
        question="What are the GDPR principles for processing personal data and how do they apply to AI training?",
        expected_answer=(
            "GDPR Article 5 requires personal data to be processed with: lawfulness, fairness and "
            "transparency; purpose limitation (collected for specified purposes only); data minimisation "
            "(adequate, relevant, limited to necessary); accuracy (kept up to date); storage limitation "
            "(not kept longer than necessary); integrity and confidentiality (appropriate security). "
            "For AI training data under Article 10 of the AI Act, these principles mean training data "
            "must comply with data minimisation and purpose limitation when processing personal data."
        ),
        frameworks=["GDPR"],
        key_nodes=["gdpr_art5_principles"],
        keywords=["lawfulness", "fairness", "transparency", "purpose limitation", "data minimisation", "accuracy"],
    ),
    GovernanceQuestion(
        id="MG-A06", tier="A",
        question="What transparency obligations exist for AI systems that generate deepfakes or synthetic content?",
        expected_answer=(
            "Article 50 requires providers of AI systems generating synthetic audio, image, video or text "
            "content to ensure outputs are marked in a machine-readable format as artificially generated "
            "or manipulated. Deployers of AI systems generating deep fakes must disclose that content has "
            "been artificially generated or manipulated. For AI systems interacting directly with persons, "
            "providers must design them so persons are informed they are interacting with an AI, unless "
            "obvious from context. Exception: AI used to detect or prevent criminal offences."
        ),
        frameworks=["EU_AI_Act"],
        key_nodes=["aiact_art50_transparency_gen"],
        keywords=["deepfake", "synthetic", "machine-readable", "artificially generated", "disclose"],
    ),
    GovernanceQuestion(
        id="MG-A07", tier="A",
        question="How does DORA define ICT risk management requirements for financial entities?",
        expected_answer=(
            "DORA Articles 5-16 require financial entities to have an internal governance and control "
            "framework ensuring effective and prudent management of ICT risk. The framework must include "
            "strategies, policies, procedures, ICT protocols and tools to protect all information assets "
            "and ICT assets including software, hardware and servers. Financial entities must identify, "
            "classify and adequately document all ICT-supported business functions."
        ),
        frameworks=["DORA"],
        key_nodes=["dora_art3_ict_risk"],
        keywords=["ICT risk", "governance", "financial entities", "strategies", "policies", "procedures"],
    ),
    GovernanceQuestion(
        id="MG-A08", tier="A",
        question="What incident notification timelines does NIS2 require for essential entities?",
        expected_answer=(
            "NIS2 Article 23 requires essential entities to notify CSIRT or competent authority: "
            "(a) within 24 hours — early warning indicating whether incident is suspected of being "
            "caused by unlawful or malicious acts; (b) within 72 hours — incident notification with "
            "assessment of severity and impact; (c) upon request — intermediate report; (d) within "
            "one month — final report with detailed description, root cause, and mitigation measures."
        ),
        frameworks=["NIS2"],
        key_nodes=["nis2_art23_incident"],
        keywords=["24 hours", "72 hours", "one month", "CSIRT", "early warning", "final report"],
    ),
    GovernanceQuestion(
        id="MG-A09", tier="A",
        question="What high-risk AI use cases does Annex III define for employment and workers management?",
        expected_answer=(
            "Annex III point 4 classifies as high-risk: AI systems for recruitment or selection of "
            "natural persons, particularly for placing targeted job advertisements, screening or "
            "filtering applications, evaluating candidates in interviews or tests. Also: AI for "
            "making decisions affecting terms of work-related relationships, promotion or termination, "
            "task allocation based on individual behaviour or personal traits, and monitoring and "
            "evaluating performance and behaviour of persons in work relationships."
        ),
        frameworks=["EU_AI_Act"],
        key_nodes=["concept_annex3_usecases"],
        keywords=["recruitment", "screening", "filtering", "evaluating candidates", "task allocation", "monitoring performance"],
    ),
    GovernanceQuestion(
        id="MG-A10", tier="A",
        question="What is the role and scope of AI regulatory sandboxes under the EU AI Act?",
        expected_answer=(
            "Articles 57-58 require Member States to ensure at least one AI regulatory sandbox is "
            "operational at national level by August 2026. Sandboxes provide a controlled environment "
            "for development, testing and validation of innovative AI systems under strict oversight. "
            "They include real-world testing conditions. Personal data may be processed in sandboxes "
            "for developing AI in the public interest, with specific safeguards. SMEs and startups "
            "have priority access. Sandbox results are considered by market surveillance authorities."
        ),
        frameworks=["EU_AI_Act"],
        key_nodes=["aiact_regulatory_sandbox"],
        keywords=["sandbox", "August 2026", "controlled environment", "real-world testing", "SMEs", "priority"],
    ),
]

# =========================================================================
# TIER B: Cross-Regulation Queries (10 questions)
# =========================================================================

TIER_B_QUESTIONS = [
    GovernanceQuestion(
        id="MG-B01", tier="B",
        question="How do the EU AI Act and GDPR jointly regulate automated decision-making that affects natural persons?",
        expected_answer=(
            "GDPR Article 22 gives data subjects the right not to be subject to solely automated "
            "decisions with legal effects, with rights to human intervention, express their view, "
            "and contest decisions. The AI Act complements this: Article 26(7) requires deployers of "
            "high-risk AI systems making decisions about natural persons to inform them of the AI "
            "system's use. Article 13 requires sufficient transparency for deployers to interpret outputs. "
            "Article 14 mandates human oversight with override capability. Together, these create a "
            "layered protection: GDPR provides the right to contest, AI Act ensures transparency "
            "and human control over the decision process."
        ),
        frameworks=["EU_AI_Act", "GDPR"],
        key_nodes=["aiact_art26_deployer", "gdpr_art22_automated", "aiact_art14_human_oversight", "aiact_art13_transparency"],
        keywords=["automated decision", "human intervention", "Article 22", "Article 26", "transparency", "human oversight", "contest"],
    ),
    GovernanceQuestion(
        id="MG-B02", tier="B",
        question="What are the combined penalty exposures when a high-risk AI system violates both the EU AI Act and GDPR?",
        expected_answer=(
            "Under GDPR Article 83, violations of basic principles or data subject rights face fines "
            "up to EUR 20 million or 4% of worldwide annual turnover. Under AI Act Article 99, "
            "Chapter III violations (high-risk requirements) face fines up to EUR 15 million or 3% "
            "of turnover, while Article 5 prohibited practices face EUR 35 million or 7%. These fines "
            "are cumulative — a single AI system that both violates GDPR data principles in its training "
            "data and fails AI Act high-risk requirements could face up to 7% (combined 4%+3%) of "
            "global turnover, or up to 11% if it also engages in prohibited practices (7%+4%)."
        ),
        frameworks=["EU_AI_Act", "GDPR"],
        key_nodes=["aiact_art99_penalties", "gdpr_art83_penalties"],
        keywords=["EUR 20 million", "4%", "EUR 15 million", "3%", "7%", "cumulative", "combined"],
    ),
    GovernanceQuestion(
        id="MG-B03", tier="B",
        question="How must a deployer using a high-risk AI system comply with both the AI Act's fundamental rights impact assessment and GDPR's data protection impact assessment?",
        expected_answer=(
            "The AI Act Article 27 requires public bodies and private entities providing public services "
            "to perform a Fundamental Rights Impact Assessment (FRIA) before deploying high-risk AI. "
            "GDPR Article 35 requires a DPIA when processing is likely to result in high risk to rights "
            "and freedoms. Both must identify risks, assess impact, and define mitigation measures. "
            "Deployers may combine the FRIA and DPIA to avoid duplication. The AI Act Article 26(9) "
            "specifically requires deployers to use the system's transparency documentation (Art. 13) "
            "to fulfill their GDPR DPIA obligations, creating a documented chain from provider's "
            "transparency documentation through to deployer's impact assessment."
        ),
        frameworks=["EU_AI_Act", "GDPR"],
        key_nodes=["concept_fundamental_rights", "gdpr_art35_dpia", "aiact_art26_deployer", "aiact_art13_transparency"],
        keywords=["FRIA", "DPIA", "fundamental rights", "combine", "Article 27", "Article 35", "transparency documentation"],
    ),
    GovernanceQuestion(
        id="MG-B04", tier="B",
        question="What dual obligations apply when a financial entity reports an AI-related incident under both the AI Act and DORA?",
        expected_answer=(
            "Under AI Act Article 73, providers must report serious AI incidents to market surveillance "
            "authorities within 15 days of establishing a causal link. Under DORA Articles 17-23, "
            "financial entities must report major ICT incidents to the financial supervisory authority "
            "using standardised templates, with classification based on clients affected, duration, "
            "geographical spread, data losses, service criticality, and economic impact. Both reporting "
            "obligations apply simultaneously — to different authorities with different timelines and "
            "different templates. The financial entity must report the same AI incident twice: once to "
            "the market surveillance authority (AI Act, 15 days) and once to the financial supervisor "
            "(DORA, based on incident classification timeline)."
        ),
        frameworks=["EU_AI_Act", "DORA"],
        key_nodes=["aiact_art73_incidents", "dora_art11_incident_reporting"],
        keywords=["15 days", "market surveillance", "financial supervisory", "dual", "simultaneously", "different authorities"],
    ),
    GovernanceQuestion(
        id="MG-B05", tier="B",
        question="How do the AI Act's cybersecurity requirements for high-risk AI interact with NIS2 security measures for essential entities?",
        expected_answer=(
            "AI Act Article 15 requires high-risk AI systems to be resilient against adversarial "
            "attacks including poisoning, model evasion, and confidentiality attacks, with technical "
            "measures to prevent, detect, respond to and control such attacks. NIS2 Article 21 requires "
            "essential entities to implement: risk analysis policies, incident handling, business continuity, "
            "supply chain security, vulnerability handling, cryptography and encryption, multi-factor "
            "authentication, and cybersecurity training. When a high-risk AI system is operated by an "
            "essential entity (e.g., critical infrastructure), both sets of requirements apply: the AI "
            "system must meet AI Act Art. 15 standards AND be integrated into the entity's NIS2 "
            "cybersecurity framework (Art. 21)."
        ),
        frameworks=["EU_AI_Act", "NIS2"],
        key_nodes=["aiact_art15_accuracy", "nis2_art21_security"],
        keywords=["adversarial", "resilient", "NIS2", "essential entity", "both", "integrated", "cybersecurity framework"],
    ),
    GovernanceQuestion(
        id="MG-B06", tier="B",
        question="How does the GDPR's data protection by design principle interact with the AI Act's data governance requirements?",
        expected_answer=(
            "GDPR Article 25 requires data protection by design — implementing appropriate technical "
            "and organisational measures to integrate data-protection principles like data minimisation "
            "into processing. AI Act Article 10 requires training data to meet quality criteria with "
            "appropriate governance: design choices, data collection processes, annotation, labelling, "
            "cleaning, bias detection and mitigation. When the AI processes personal data, GDPR "
            "by-design requirements and AI Act data governance must be implemented jointly: the AI "
            "system's data pipeline must simultaneously ensure GDPR data minimisation AND AI Act "
            "data quality, which can create tension since minimisation limits data while quality "
            "often requires more diverse data."
        ),
        frameworks=["EU_AI_Act", "GDPR"],
        key_nodes=["aiact_art10_data_gov", "gdpr_art25_by_design", "gdpr_art5_principles"],
        keywords=["by design", "data governance", "minimisation", "quality", "tension", "jointly"],
    ),
    GovernanceQuestion(
        id="MG-B07", tier="B",
        question="What are the supply chain implications when a financial institution uses a third-party high-risk AI system, considering both the AI Act and DORA?",
        expected_answer=(
            "Under AI Act Article 25, if the financial institution modifies the AI system substantially "
            "or changes its intended purpose, it becomes the provider and assumes ALL provider obligations. "
            "Under DORA Articles 28-44, contractual arrangements with third-party ICT providers must "
            "include: clear description of services, availability and integrity provisions, exit "
            "strategies and transition plans. Critical third-party providers are subject to Union "
            "oversight. When combined: the financial entity must maintain DORA third-party oversight "
            "AND ensure the AI system meets AI Act high-risk requirements, with the risk that any "
            "modification to fit the financial use case could trigger full provider status under "
            "the AI Act."
        ),
        frameworks=["EU_AI_Act", "DORA"],
        key_nodes=["concept_supply_chain", "dora_art28_tpsp", "aiact_provider"],
        keywords=["third-party", "modification", "provider status", "DORA", "exit strategies", "oversight"],
    ),
    GovernanceQuestion(
        id="MG-B08", tier="B",
        question="How do AI Act risk management requirements interact with DORA ICT risk management for credit scoring AI?",
        expected_answer=(
            "Credit scoring AI is classified as high-risk under Annex III point 5(b). Under AI Act "
            "Article 9, the provider must implement a continuous iterative risk management system "
            "throughout the system's lifecycle, covering known and foreseeable risks with residual "
            "risk kept to acceptable levels. Under DORA Articles 5-16, the financial entity must "
            "maintain an ICT risk management framework with strategies, policies, procedures and "
            "protocols. These two requirements must be integrated: the AI-specific risk management "
            "(bias, accuracy, fairness) must be embedded within the broader DORA ICT risk framework, "
            "with the AI risk management system feeding into DORA's systematic documentation and "
            "the DORA framework providing the organisational infrastructure for AI risk governance."
        ),
        frameworks=["EU_AI_Act", "DORA"],
        key_nodes=["aiact_art9_risk_mgmt", "dora_art3_ict_risk", "concept_annex3_usecases"],
        keywords=["credit scoring", "Annex III", "continuous iterative", "ICT risk", "integrated", "embedded"],
    ),
    GovernanceQuestion(
        id="MG-B09", tier="B",
        question="What dual incident notification requirements apply when an AI system causing a cybersecurity breach affects essential infrastructure under both the AI Act and NIS2?",
        expected_answer=(
            "Under AI Act Article 73, the provider must report the serious incident to market "
            "surveillance authorities within 15 days of establishing a causal link. Under NIS2 "
            "Article 23, the essential entity must notify the CSIRT: within 24 hours (early warning), "
            "within 72 hours (incident notification with severity assessment), and within one month "
            "(final report with root cause). The NIS2 timelines are much more aggressive than the "
            "AI Act's 15-day deadline. Both notifications go to different authorities (market "
            "surveillance vs. CSIRT) with different templates and different information requirements. "
            "The entity must coordinate both reporting streams simultaneously."
        ),
        frameworks=["EU_AI_Act", "NIS2"],
        key_nodes=["aiact_art73_incidents", "nis2_art23_incident"],
        keywords=["15 days", "24 hours", "72 hours", "CSIRT", "market surveillance", "simultaneously", "different authorities"],
    ),
    GovernanceQuestion(
        id="MG-B10", tier="B",
        question="How does the AI Act's conformity assessment interact with existing product safety legislation for AI-embedded products?",
        expected_answer=(
            "Under Article 6(1), AI systems that are safety components of products covered by "
            "Annex I Section A harmonisation legislation are subject to the same conformity assessment "
            "as the parent legislation. Under Article 43, for stand-alone high-risk AI in Annex III, "
            "providers may use internal control (Annex VI) or notified body assessment (Annex VII). "
            "For Annex I products, AI Act requirements are integrated INTO the existing product "
            "conformity assessment — not a separate process. The CE marking (Art. 48) covers both "
            "the product safety and AI compliance. Any substantial modification triggers a new "
            "conformity assessment covering both dimensions."
        ),
        frameworks=["EU_AI_Act"],
        key_nodes=["aiact_art43_conformity", "aiact_art6_highrisk_class", "concept_ce_marking"],
        keywords=["Annex I", "Annex VI", "Annex VII", "harmonisation", "integrated", "CE marking", "substantial modification"],
    ),
]

# =========================================================================
# TIER C: Complex Inter-Domain Queries (10 questions)
# =========================================================================

TIER_C_QUESTIONS = [
    GovernanceQuestion(
        id="MG-C01", tier="C",
        question="A bank deploys a credit scoring AI system that experiences a data breach affecting 50,000 customers. Map out ALL regulatory obligations, timelines, authorities, and potential penalties across every applicable framework.",
        expected_answer=(
            "This triggers obligations under four frameworks simultaneously: "
            "(1) AI Act: Report serious AI incident to market surveillance within 15 days (Art. 73). "
            "Potential penalty: EUR 15M or 3% turnover for Chapter III violations (Art. 99). "
            "(2) GDPR: Notify supervisory authority within 72 hours and affected data subjects without "
            "undue delay (Art. 33-34). Penalty: up to EUR 20M or 4% turnover (Art. 83). "
            "(3) DORA: Report major ICT incident to financial supervisory authority with classification "
            "by impact (Art. 17-23). Penalty: per national implementation. "
            "(4) NIS2: If the bank is an essential entity, notify CSIRT within 24 hours (early warning) "
            "and 72 hours (full notification) (Art. 23). Penalty: up to EUR 10M or 2% turnover (Art. 34). "
            "Maximum cumulative penalty exposure: up to 9% of global turnover (3% AI Act + 4% GDPR + 2% NIS2). "
            "Four different authorities must be notified with four different timelines and templates."
        ),
        frameworks=["EU_AI_Act", "GDPR", "DORA", "NIS2"],
        key_nodes=["aiact_art73_incidents", "aiact_art99_penalties", "gdpr_art83_penalties",
                    "dora_art11_incident_reporting", "nis2_art23_incident", "nis2_art34_penalties",
                    "concept_annex3_usecases"],
        keywords=["15 days", "72 hours", "24 hours", "9%", "four", "cumulative", "market surveillance",
                  "supervisory authority", "CSIRT", "financial supervisor"],
    ),
    GovernanceQuestion(
        id="MG-C02", tier="C",
        question="An energy utility deploys AI for grid management (critical infrastructure). A third-party provider substantially modifies the model. Who bears which obligations under the AI Act, DORA, and NIS2?",
        expected_answer=(
            "Under AI Act Article 25, the third party that substantially modifies the system becomes "
            "the provider and assumes ALL provider obligations: risk management (Art. 9), data governance "
            "(Art. 10), documentation (Art. 11), conformity assessment (Art. 43), CE marking (Art. 48). "
            "The energy utility remains the deployer with Art. 26 obligations: human oversight, monitoring, "
            "incident reporting. Under NIS2, the energy utility as essential entity must maintain "
            "cybersecurity measures (Art. 21) and incident notification (Art. 23) regardless of who is "
            "the AI provider. Under DORA (if applicable as financial-adjacent), third-party management "
            "(Art. 28-44) requires contractual arrangements covering the modification scope. "
            "Critical infrastructure AI is high-risk under Annex III point 2, so ALL Chapter III "
            "requirements apply. The modification creates a liability gap: the original provider is "
            "no longer responsible, but the modifier may not have the original's technical infrastructure."
        ),
        frameworks=["EU_AI_Act", "NIS2", "DORA"],
        key_nodes=["concept_supply_chain", "aiact_provider", "aiact_art26_deployer",
                    "nis2_art21_security", "dora_art28_tpsp", "concept_annex3_usecases"],
        keywords=["substantially modifies", "becomes provider", "ALL obligations", "deployer remains",
                  "essential entity", "liability gap", "Annex III point 2"],
    ),
    GovernanceQuestion(
        id="MG-C03", tier="C",
        question="Design a comprehensive compliance program for a hospital deploying an AI diagnostic system, addressing the AI Act, GDPR, NIS2, and fundamental rights. What are the key tensions between these frameworks?",
        expected_answer=(
            "The hospital must: (1) AI Act: The diagnostic AI is high-risk (Annex III — health). "
            "Ensure provider has completed conformity assessment (Art. 43), implement human oversight "
            "with qualified medical staff (Art. 14), monitor system operation (Art. 26), report "
            "incidents (Art. 73). (2) GDPR: Conduct DPIA (Art. 35) for health data processing, "
            "ensure lawful basis (likely explicit consent or vital interests), comply with data "
            "minimisation while ensuring sufficient training data quality. (3) NIS2: Hospital as "
            "essential entity must maintain cybersecurity framework (Art. 21), report AI-related "
            "security incidents to CSIRT (Art. 23). (4) Fundamental Rights: Conduct FRIA (Art. 27) "
            "assessing discrimination risks in diagnostic outcomes. Key tensions: GDPR data "
            "minimisation vs AI Act data quality requirements (Art. 10); human oversight (Art. 14) "
            "vs clinical workflow efficiency; transparency (Art. 13) vs medical liability if "
            "clinicians over-rely on explained AI outputs; FRIA/DPIA duplication burden. "
            "Resolution: combine FRIA and DPIA, establish clinical AI governance committee, "
            "implement tiered human oversight based on diagnostic confidence levels."
        ),
        frameworks=["EU_AI_Act", "GDPR", "NIS2", "Cross-Framework"],
        key_nodes=["aiact_art14_human_oversight", "aiact_art26_deployer", "aiact_art13_transparency",
                    "gdpr_art35_dpia", "gdpr_art5_principles", "nis2_art21_security",
                    "concept_fundamental_rights", "concept_annex3_usecases"],
        keywords=["DPIA", "FRIA", "data minimisation", "quality", "tension", "human oversight",
                  "essential entity", "combine", "governance committee"],
    ),
    GovernanceQuestion(
        id="MG-C04", tier="C",
        question="What is the total maximum fine exposure for a tech company that develops a GPAI model with systemic risk, violates prohibited AI practices, fails GDPR data protection, and breaches NIS2 cybersecurity?",
        expected_answer=(
            "Maximum cumulative fine exposure across all frameworks: "
            "AI Act prohibited practices (Art. 5/99): EUR 35M or 7% of worldwide turnover. "
            "AI Act GPAI systemic risk violations (Art. 51-55/99): EUR 15M or 3% of turnover. "
            "GDPR basic principles violation (Art. 83): EUR 20M or 4% of turnover. "
            "NIS2 essential entity (Art. 34): EUR 10M or 2% of turnover. "
            "Total maximum: 16% of worldwide annual turnover (7% + 3% + 4% + 2%), or "
            "EUR 80 million (35M + 15M + 20M + 10M), whichever is higher for each individual fine. "
            "Each fine is assessed independently by different authorities under different "
            "frameworks. The ne bis in idem principle may limit overlap within the same "
            "jurisdiction, but cross-framework fines from different regulatory regimes "
            "are generally cumulative."
        ),
        frameworks=["EU_AI_Act", "GDPR", "NIS2"],
        key_nodes=["aiact_art99_penalties", "gdpr_art83_penalties", "nis2_art34_penalties",
                    "aiact_art5_prohibited", "aiact_art51_gpai_systemic"],
        keywords=["16%", "EUR 80 million", "7%", "4%", "3%", "2%", "cumulative", "independently"],
    ),
    GovernanceQuestion(
        id="MG-C05", tier="C",
        question="How should a multinational deploy an AI recruitment system across the EU, considering the AI Act's territorial scope, GDPR's cross-border processing rules, and varying NIS2 transposition?",
        expected_answer=(
            "AI Act Article 2 applies to all deployers located in the Union, regardless of provider "
            "location. Recruitment AI is high-risk under Annex III point 4. The deployer must: "
            "ensure conformity assessment from the provider (Art. 43), implement human oversight "
            "per Art. 14 (qualified HR staff in each jurisdiction), and conduct FRIA (Art. 27) "
            "for each country's specific population. GDPR requires: identifying a lead supervisory "
            "authority for cross-border processing, conducting DPIAs per Art. 35, ensuring lawful "
            "basis (likely legitimate interest or consent), and respecting Art. 22 automated "
            "decision-making rights in each jurisdiction. NIS2 transposition varies by Member State "
            "— the company must verify whether it is classified as essential/important entity in each "
            "country where it operates. Key challenge: a recruitment decision valid under one "
            "Member State's GDPR interpretation may violate another's, and the AI Act's uniform "
            "high-risk requirements may conflict with varying national employment laws."
        ),
        frameworks=["EU_AI_Act", "GDPR", "NIS2"],
        key_nodes=["aiact_art2_scope", "concept_annex3_usecases", "gdpr_art22_automated",
                    "gdpr_art35_dpia", "concept_fundamental_rights", "nis2_art21_security"],
        keywords=["territorial", "cross-border", "lead supervisory", "transposition", "varies",
                  "Annex III point 4", "FRIA", "each jurisdiction"],
    ),
    GovernanceQuestion(
        id="MG-C06", tier="C",
        question="A law enforcement agency wants to use real-time biometric identification in a public space to prevent an imminent terrorist threat. What is the complete legal pathway, conditions, and oversight requirements across all applicable frameworks?",
        expected_answer=(
            "AI Act Article 5 generally prohibits real-time remote biometric identification in public "
            "spaces for law enforcement. Exception: strictly necessary for prevention of specific, "
            "substantial and imminent threat to life or genuine terrorist threat. Conditions: must be "
            "authorised by judicial authority or independent administrative authority; limited in "
            "time, geographic and personal scope; subject to prior fundamental rights impact assessment; "
            "registered in the EU database. Article 14 requires verification by at least two natural "
            "persons. Biometric identification is high-risk Annex III point 1 — full Chapter III "
            "requirements apply. GDPR applies: processing of biometric data (special category, Art. 9) "
            "requires explicit legal basis, likely Art. 9(2)(g) substantial public interest. GDPR "
            "Art. 35 DPIA required before deployment. If the system is embedded in essential "
            "infrastructure, NIS2 Art. 21 cybersecurity measures apply. The complete chain: "
            "judicial authorisation → FRIA → DPIA → conformity verified → human oversight (2 persons) → "
            "time-limited deployment → incident reporting to multiple authorities."
        ),
        frameworks=["EU_AI_Act", "GDPR", "NIS2", "Cross-Framework"],
        key_nodes=["aiact_art5_prohibited", "aiact_art14_human_oversight", "concept_fundamental_rights",
                    "gdpr_art35_dpia", "concept_annex3_usecases", "nis2_art21_security"],
        keywords=["judicial authority", "imminent threat", "two natural persons", "time-limited",
                  "FRIA", "DPIA", "special category", "biometric", "complete chain"],
    ),
    GovernanceQuestion(
        id="MG-C07", tier="C",
        question="An insurance company uses AI for risk assessment and a data protection authority finds the training data was biased against certain ethnic groups. Trace the full enforcement cascade across AI Act, GDPR, and potential liability.",
        expected_answer=(
            "Insurance risk assessment AI is high-risk under Annex III point 5 (essential services). "
            "Enforcement cascade: (1) AI Act Art. 10 violation — data governance failed to detect and "
            "mitigate bias in training data. Art. 9 risk management failed to identify discrimination risk. "
            "Penalties: EUR 15M or 3% turnover. (2) GDPR Art. 5 violation — fairness principle breached "
            "through discriminatory processing. Art. 22 — automated decisions with significant effects "
            "lacked adequate safeguards. Penalties: EUR 20M or 4% turnover. (3) Fundamental Rights — "
            "Art. 27 FRIA should have identified discrimination risk against ethnic groups, linked to "
            "EU Charter Art. 21 non-discrimination. (4) Product Liability — affected individuals may "
            "bring civil claims for discriminatory insurance pricing. (5) Corrective cascade: market "
            "surveillance authority can order system withdrawal (AI Act), data protection authority "
            "can order processing halt (GDPR), and the provider must conduct new conformity "
            "assessment after fixing the bias. Combined exposure: 7% turnover (3%+4%) plus "
            "civil liability."
        ),
        frameworks=["EU_AI_Act", "GDPR", "Cross-Framework"],
        key_nodes=["aiact_art10_data_gov", "aiact_art9_risk_mgmt", "aiact_art99_penalties",
                    "gdpr_art5_principles", "gdpr_art22_automated", "gdpr_art83_penalties",
                    "concept_fundamental_rights", "concept_annex3_usecases"],
        keywords=["bias", "discrimination", "ethnic", "fairness", "withdrawal", "7%",
                  "civil liability", "new conformity assessment"],
    ),
    GovernanceQuestion(
        id="MG-C08", tier="C",
        question="How does the AI Act's quality management system requirement interact with DORA's ICT governance and NIS2's cybersecurity policies for a fintech company running AI-based fraud detection?",
        expected_answer=(
            "The fintech faces three overlapping governance frameworks: "
            "AI Act Art. 17 QMS: requires documented strategies for regulatory compliance, design "
            "procedures, quality control, testing, data management, risk management, post-market "
            "monitoring, incident reporting, and resource management. "
            "DORA ICT Governance (Art. 5-16): requires internal governance framework for ICT risk "
            "with strategies, policies, procedures, and protocols covering all ICT assets. "
            "NIS2 Art. 21: requires policies on risk analysis, incident handling, business continuity, "
            "supply chain security, and cybersecurity training. "
            "Integration approach: the QMS should be the umbrella system incorporating both DORA "
            "ICT risk management and NIS2 cybersecurity measures as sub-frameworks. The AI-specific "
            "risk management (bias, accuracy, fairness for fraud detection) feeds into the broader "
            "ICT risk assessment, while NIS2 cybersecurity requirements map to AI Act Art. 15 "
            "(accuracy, robustness, cybersecurity). Duplication risk: without integration, the "
            "fintech maintains three separate but overlapping governance systems."
        ),
        frameworks=["EU_AI_Act", "DORA", "NIS2"],
        key_nodes=["aiact_art17_qms", "dora_art3_ict_risk", "nis2_art21_security",
                    "aiact_art9_risk_mgmt", "aiact_art15_accuracy"],
        keywords=["QMS", "umbrella", "ICT governance", "cybersecurity", "integration",
                  "sub-frameworks", "duplication", "overlapping"],
    ),
    GovernanceQuestion(
        id="MG-C09", tier="C",
        question="Compare and contrast the incident reporting timelines, authorities, and templates across AI Act, GDPR, DORA, and NIS2 for a single AI incident in a critical infrastructure bank.",
        expected_answer=(
            "For a single AI incident affecting a critical infrastructure bank, four parallel "
            "reporting obligations trigger: "
            "AI Act (Art. 73): Report to market surveillance authority within 15 days of establishing "
            "causal link. Content: AI system details, nature of incident, corrective measures. "
            "GDPR (Art. 33): Notify data protection authority within 72 hours of becoming aware. "
            "Content: nature of breach, categories of data subjects, likely consequences, mitigation measures. "
            "DORA (Art. 17-23): Report to financial supervisory authority per incident classification. "
            "Content: standardised template with clients affected, duration, geographic spread, data loss. "
            "NIS2 (Art. 23): Notify CSIRT within 24 hours (early warning), 72 hours (full notification), "
            "one month (final report). Content: suspected malicious cause, severity, impact, root cause. "
            "Comparison: NIS2 has fastest deadline (24h), GDPR next (72h), AI Act slowest (15 days). "
            "Four different authorities, four different templates, four different legal bases. "
            "The bank's incident response team needs a unified procedure mapping one event to four streams."
        ),
        frameworks=["EU_AI_Act", "GDPR", "DORA", "NIS2"],
        key_nodes=["aiact_art73_incidents", "dora_art11_incident_reporting",
                    "nis2_art23_incident", "gdpr_art35_dpia"],
        keywords=["15 days", "72 hours", "24 hours", "one month", "four", "parallel",
                  "market surveillance", "data protection", "CSIRT", "financial supervisor", "unified"],
    ),
    GovernanceQuestion(
        id="MG-C10", tier="C",
        question="An AI regulatory sandbox participant wants to test a novel emotion recognition system in a workplace setting. What are the legal boundaries, exceptions, and framework interactions?",
        expected_answer=(
            "This faces a direct prohibition: AI Act Article 5 prohibits emotion recognition in "
            "workplace and educational institutions. Regulatory sandboxes (Art. 57-58) provide "
            "controlled testing environments, but Article 5 prohibitions are absolute — no sandbox "
            "exception. The only permitted emotion recognition is outside workplace/education contexts. "
            "If the participant proposes a modified scope (e.g., public safety context), then: "
            "AI Act: must operate within sandbox plan agreed with competent authority; GDPR: emotion "
            "recognition processes biometric data (special category, Art. 9) requiring explicit "
            "consent or substantial public interest; GDPR Art. 35 DPIA mandatory; fundamental "
            "rights assessment required for any biometric categorisation. Even in a sandbox, "
            "GDPR protections apply fully — sandbox does not exempt from data protection law. "
            "NIS2 applies if the sandbox operator is an essential entity. "
            "Bottom line: workplace emotion recognition cannot be tested even in a sandbox. "
            "The prohibition is not a regulatory barrier that sandboxes can bypass — it's a "
            "fundamental rights protection."
        ),
        frameworks=["EU_AI_Act", "GDPR", "Cross-Framework"],
        key_nodes=["aiact_art5_prohibited", "aiact_regulatory_sandbox", "gdpr_art35_dpia",
                    "gdpr_art5_principles", "concept_fundamental_rights"],
        keywords=["prohibited", "no sandbox exception", "absolute", "emotion recognition",
                  "workplace", "biometric", "special category", "fundamental rights protection"],
    ),
]


# Combine all questions
ALL_QUESTIONS = TIER_A_QUESTIONS + TIER_B_QUESTIONS + TIER_C_QUESTIONS


def get_questions_by_tier(tier: str) -> list[GovernanceQuestion]:
    """Get questions for a specific tier (A, B, or C)."""
    return [q for q in ALL_QUESTIONS if q.tier == tier]


def get_tier_stats() -> dict:
    """Get stats about the benchmark."""
    return {
        "total": len(ALL_QUESTIONS),
        "tier_a": len(TIER_A_QUESTIONS),
        "tier_b": len(TIER_B_QUESTIONS),
        "tier_c": len(TIER_C_QUESTIONS),
        "frameworks_covered": ["EU_AI_Act", "GDPR", "DORA", "NIS2", "Cross-Framework"],
        "avg_frameworks_per_question": {
            "A": sum(len(q.frameworks) for q in TIER_A_QUESTIONS) / len(TIER_A_QUESTIONS),
            "B": sum(len(q.frameworks) for q in TIER_B_QUESTIONS) / len(TIER_B_QUESTIONS),
            "C": sum(len(q.frameworks) for q in TIER_C_QUESTIONS) / len(TIER_C_QUESTIONS),
        },
        "avg_key_nodes_per_question": {
            "A": sum(len(q.key_nodes) for q in TIER_A_QUESTIONS) / len(TIER_A_QUESTIONS),
            "B": sum(len(q.key_nodes) for q in TIER_B_QUESTIONS) / len(TIER_B_QUESTIONS),
            "C": sum(len(q.key_nodes) for q in TIER_C_QUESTIONS) / len(TIER_C_QUESTIONS),
        },
    }
