"""
Multi-Governance Knowledge Graph — EU AI Act + GDPR + DORA + NIS2.

A dense, interconnected regulatory KG with THICK nodes containing actual
article text AND supporting evidence chunks. Each node carries 3-5 chunks
for deep multi-angle reasoning — mirroring TAMR+'s chunk-level scoring.

Nodes: ~32 entities with full article text (500-1500 chars each)
Chunks: ~4 per node (Q&A, enforcement, implementation, cross-references)
Edges: ~40 relationships with typed connections
Frameworks: EU AI Act, GDPR, DORA, NIS2
"""

# ── graqle:intelligence ──
# module: graqle.benchmarks.multi_governance_kg
# risk: LOW (impact radius: 3 modules)
# consumers: run_multigov, run_multigov_v2, run_multigov_v3
# dependencies: __future__, json, networkx, pathlib, typing
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import networkx as nx
from pathlib import Path
from typing import Any


def build_multi_governance_kg() -> nx.Graph:
    """Build a dense multi-governance KG with thick nodes and evidence chunks.

    Each node contains:
    - label: human-readable name
    - type: entity type (Regulation, Article, Concept, Actor, Penalty, Process)
    - framework: source framework (EU_AI_Act, GDPR, DORA, NIS2, etc.)
    - description: FULL article text or detailed explanation (500-1500 chars)
    - articles: list of article references
    - keywords: searchable terms
    - chunks: list of evidence chunks (Q&A, enforcement, implementation, cross-refs)
              each chunk is a dict with 'type' and 'text' — these feed the node agent
              for multi-angle reasoning, just like TAMR+ document chunks
    """
    G = nx.Graph()

    # =====================================================================
    # EU AI ACT — Core Articles (with full text + evidence chunks)
    # =====================================================================

    G.add_node("aiact_art5_prohibited", **{
        "label": "Prohibited AI Practices",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 5"],
        "keywords": ["prohibited", "subliminal", "manipulation", "social scoring", "biometric"],
        "description": (
            "Article 5 — Prohibited AI Practices. The following AI practices shall be prohibited: "
            "(a) the placing on the market, the putting into service or the use of an AI system that "
            "deploys subliminal techniques beyond a person's consciousness or purposefully manipulative "
            "or deceptive techniques, with the objective or the effect of materially distorting the "
            "behaviour of a person or a group of persons by appreciably impairing their ability to make "
            "an informed decision, thereby causing that person to take a decision that they would not "
            "have otherwise taken in a manner that causes or is reasonably likely to cause significant harm. "
            "(b) AI systems that exploit vulnerabilities of a specific group of persons due to their age, "
            "disability, or a specific social or economic situation. "
            "(c) Social scoring by public authorities or on their behalf. "
            "(d) Real-time remote biometric identification in publicly accessible spaces for law enforcement "
            "purposes, unless strictly necessary for: targeted search for victims of abduction/trafficking, "
            "prevention of imminent threat to life, or genuine terrorist threat. "
            "(e) Untargeted scraping of facial images from internet or CCTV for facial recognition databases. "
            "(f) Emotion recognition in workplace and educational institutions. "
            "(g) Biometric categorisation using sensitive characteristics."
        ),
        "chunks": [
            {"type": "enforcement", "text": (
                "Penalty for prohibited AI: Up to EUR 35 million or 7% of worldwide annual turnover, "
                "whichever is higher (Art. 99(3)). This is the highest tier of penalties under the AI Act, "
                "reflecting the severity of deploying banned practices. Enforcement begins 2 February 2025 "
                "(6 months after entry into force). National market surveillance authorities are responsible "
                "for enforcement, with the AI Office coordinating at EU level."
            )},
            {"type": "qa", "text": (
                "Q: Can a private company use social scoring? A: Article 5(1)(c) specifically prohibits social "
                "scoring 'by or on behalf of public authorities.' Private companies using social scoring for "
                "commercial purposes (e.g., loyalty programs) may not be caught by Art. 5 directly but could "
                "violate GDPR Art. 22 (automated decision-making) and Art. 5 (data processing principles). "
                "The prohibition targets governmental social credit systems similar to China's model."
            )},
            {"type": "implementation", "text": (
                "Implementation timeline: Prohibitions apply from 2 February 2025. Organizations must audit "
                "existing AI systems for prohibited practices. Key compliance steps: (1) inventory all AI systems, "
                "(2) classify against Art. 5 categories, (3) identify any emotion recognition in workplace/education, "
                "(4) review biometric processing activities, (5) check for dark pattern/manipulative AI. "
                "Systems found to violate Art. 5 must be decommissioned immediately — no transition period."
            )},
            {"type": "cross_reference", "text": (
                "Cross-regulation: Art. 5 prohibited practices intersect with GDPR Art. 9 (special categories "
                "of data — biometric data is a special category), GDPR Art. 22 (right not to be subject to "
                "solely automated decisions), and the Charter of Fundamental Rights Art. 1 (human dignity), "
                "Art. 7 (private life), Art. 8 (data protection). A system violating AI Act Art. 5 likely "
                "also violates multiple GDPR provisions, creating cumulative liability exposure."
            )},
        ],
    })

    G.add_node("aiact_art6_highrisk_class", **{
        "label": "High-Risk AI Classification",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 6", "Annex I", "Annex III"],
        "keywords": ["high-risk", "classification", "safety component", "annex"],
        "description": (
            "Article 6 — Classification Rules for High-Risk AI Systems. "
            "An AI system that is a safety component of a product, or the AI system is itself a product, "
            "covered by the Union harmonisation legislation listed in Annex I Section A, shall be considered "
            "as high-risk where both conditions are fulfilled: (a) the AI system is intended to be used as a "
            "safety component of a product covered by Annex I legislation; (b) the product is required to "
            "undergo a third-party conformity assessment. For AI systems in Annex III (stand-alone high-risk "
            "use cases), they are high-risk regardless of product integration. Annex III covers: biometric "
            "identification, critical infrastructure, education, employment, essential services, law enforcement, "
            "migration, administration of justice, and democratic processes. Article 6(3) provides exemption "
            "where the AI system does not pose a significant risk of harm."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: Is a credit scoring AI high-risk? A: Yes. Credit scoring falls under Annex III Category 5(b) "
                "'AI systems intended to be used to evaluate the creditworthiness of natural persons or establish "
                "their credit score.' This applies regardless of whether the AI is embedded in a product. Banks, "
                "fintechs, and credit bureaus deploying AI for lending decisions must comply with all high-risk "
                "requirements (Art. 9-15). Additionally, credit scoring AI in financial institutions also falls "
                "under DORA's ICT risk management requirements."
            )},
            {"type": "qa", "text": (
                "Q: What Annex III categories exist? A: Eight categories of stand-alone high-risk AI: "
                "(1) Biometric identification and categorisation of natural persons; "
                "(2) Management and operation of critical infrastructure (energy, transport, water, digital); "
                "(3) Education and vocational training (determining access, evaluating outcomes); "
                "(4) Employment, workers management, access to self-employment (recruitment, performance evaluation); "
                "(5) Access to essential private/public services (credit scoring, emergency services, health insurance); "
                "(6) Law enforcement (risk assessment, polygraph, evidence evaluation); "
                "(7) Migration, asylum, border control (risk assessment, document authenticity); "
                "(8) Administration of justice and democratic processes."
            )},
            {"type": "enforcement", "text": (
                "Incorrect classification consequences: If a provider fails to classify a system as high-risk "
                "when it should be, they face penalties under Art. 99(4): up to EUR 15 million or 3% of worldwide "
                "annual turnover. Additionally, deploying an unclassified high-risk system means none of the "
                "Art. 9-15 requirements have been met, potentially leading to further violations. National authorities "
                "can order immediate withdrawal from the market."
            )},
            {"type": "implementation", "text": (
                "Classification process: Step 1 — Check if AI system is a safety component of an Annex I product "
                "(e.g., medical device, machinery, toy). If yes AND product requires third-party conformity assessment, "
                "it is high-risk. Step 2 — Check if the intended use falls within any Annex III category. If yes, "
                "it is high-risk unless Art. 6(3) exemption applies (system does not pose significant risk to health, "
                "safety, or fundamental rights). Step 3 — Document the classification decision with reasoning. "
                "The AI Office will publish guidelines on the application of Art. 6(3) exemption."
            )},
        ],
    })

    G.add_node("aiact_art9_risk_mgmt", **{
        "label": "Risk Management System",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 9"],
        "keywords": ["risk management", "lifecycle", "iterative", "residual risk", "mitigation"],
        "description": (
            "Article 9 — Risk Management System. A risk management system shall be established, implemented, "
            "documented and maintained in relation to high-risk AI systems. The risk management system shall "
            "be a continuous iterative process planned and run throughout the entire lifecycle of a high-risk "
            "AI system, requiring regular systematic review and updating. It shall: (1) identify and analyse "
            "known and reasonably foreseeable risks to health, safety or fundamental rights when used in "
            "accordance with intended purpose; (2) estimate and evaluate risks from intended use and "
            "reasonably foreseeable misuse; (3) evaluate risks from analysis of post-market monitoring data; "
            "(4) adopt appropriate and targeted risk management measures. Risk mitigation measures shall ensure "
            "that the residual risk associated with each hazard, as well as the overall residual risk, is "
            "judged to be acceptable."
        ),
        "chunks": [
            {"type": "implementation", "text": (
                "Risk management system components: (1) Risk identification — catalog all foreseeable risks "
                "including misuse scenarios. Use techniques from ISO 31000, ISO 14971. (2) Risk analysis — "
                "estimate probability and severity using qualitative or quantitative methods. (3) Risk evaluation — "
                "determine acceptability using risk matrices. Residual risk after mitigation must be acceptable. "
                "(4) Risk treatment — implement technical measures (accuracy thresholds, human oversight triggers), "
                "informational measures (user instructions, limitations disclosure), organizational measures "
                "(training, operational procedures). (5) Monitoring — integrate post-market monitoring data. "
                "The entire system must be documented as part of technical documentation (Art. 11)."
            )},
            {"type": "cross_reference", "text": (
                "Cross-regulation alignment: Art. 9 risk management closely parallels DORA Art. 5-6 ICT risk "
                "management framework for financial entities. Organizations deploying AI in financial services "
                "must maintain BOTH an AI Act risk management system AND a DORA ICT risk management framework. "
                "Practical approach: create an integrated risk management framework that satisfies both. "
                "Additionally, Art. 9 risk assessment should feed into GDPR Art. 35 DPIA when personal data "
                "is processed. The GDPR DPIA focuses on data protection risks while Art. 9 covers broader "
                "health, safety, and fundamental rights risks."
            )},
            {"type": "qa", "text": (
                "Q: What constitutes 'reasonably foreseeable misuse'? A: The provider must consider uses that "
                "are not intended but that can reasonably be expected given human behavior and common usage patterns. "
                "Example: A facial recognition system designed for access control (intended use) being used to "
                "monitor employee movements (foreseeable misuse). The provider must document these scenarios and "
                "implement safeguards. Recital 67 clarifies this includes uses that may stem from 'reasonably "
                "foreseeable human behaviour' and interaction with other systems."
            )},
            {"type": "enforcement", "text": (
                "Non-compliance with Art. 9: Failure to establish or maintain a risk management system for a "
                "high-risk AI system constitutes a violation under Art. 99(4), punishable by fines up to EUR 15 "
                "million or 3% of worldwide annual turnover. Importantly, risk management is a continuous obligation — "
                "a system that was compliant at launch but not updated after discovering new risks through "
                "post-market monitoring is non-compliant. National authorities can suspend the system's "
                "market presence until the risk management system is updated."
            )},
        ],
    })

    G.add_node("aiact_art10_data_gov", **{
        "label": "Data Governance for Training",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 10"],
        "keywords": ["data governance", "training data", "bias", "representativeness", "data quality"],
        "description": (
            "Article 10 — Data and Data Governance. High-risk AI systems using machine learning shall be "
            "developed on the basis of training, validation and testing data sets that meet quality criteria. "
            "Data governance and management practices shall include: (a) design choices; (b) data collection "
            "processes and origin; (c) relevant data preparation operations (annotation, labelling, cleaning, "
            "enrichment); (d) formulation of assumptions regarding intended purpose; (e) assessment of availability, "
            "quantity and suitability; (f) examination of possible biases likely to affect health and safety or "
            "fundamental rights; (g) identification of relevant data gaps or shortcomings. Training, validation "
            "and testing data shall be relevant, sufficiently representative, and to the best extent possible "
            "free of errors and complete in view of the intended purpose."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: Can special category data (Art. 9 GDPR) be used for AI bias detection? A: Yes, under Art. 10(5) "
                "of the AI Act. Providers of high-risk AI systems may process special categories of personal data "
                "(race, health, biometrics, etc.) strictly for the purpose of bias monitoring, detection, and correction. "
                "This creates a specific legal basis that supplements GDPR Art. 9(2)(g) — substantial public interest. "
                "However, strict conditions apply: processing must be strictly necessary, subject to appropriate "
                "safeguards, data must be in a protected environment, and cannot be used for any other purpose."
            )},
            {"type": "implementation", "text": (
                "Data governance implementation: (1) Establish data governance policy covering the entire AI lifecycle. "
                "(2) Document data provenance — where did training data come from? What were collection methods? "
                "(3) Perform bias audit — test for demographic disparities across protected groups. Use statistical "
                "measures like disparate impact ratio, equalized odds, demographic parity. (4) Data quality metrics — "
                "measure completeness, accuracy, timeliness, consistency. (5) Version control for datasets — "
                "track changes, maintain reproducibility. (6) For NLP/language models: assess linguistic representation "
                "across EU languages and dialects. (7) Document all assumptions and known limitations."
            )},
            {"type": "cross_reference", "text": (
                "GDPR intersection: Art. 10 data governance must be reconciled with GDPR data minimization "
                "(Art. 5(1)(c)) — you need enough data for representativeness but not more than necessary. "
                "GDPR purpose limitation (Art. 5(1)(b)) — data collected for one purpose may need re-purposing "
                "for AI training; ensure legal basis exists. GDPR storage limitation (Art. 5(1)(e)) — training "
                "data cannot be kept indefinitely. Art. 25 GDPR (data protection by design) requires privacy-preserving "
                "training techniques where feasible (federated learning, differential privacy, synthetic data)."
            )},
            {"type": "enforcement", "text": (
                "Penalties for Art. 10 violations: Up to EUR 15 million or 3% of worldwide annual turnover under "
                "Art. 99(4). Additionally, data governance failures often compound with GDPR violations — if training "
                "data processing violates GDPR, separate fines under GDPR Art. 83 apply (up to EUR 20 million or 4%). "
                "In practice, a data governance failure could trigger both AI Act AND GDPR enforcement simultaneously."
            )},
        ],
    })

    G.add_node("aiact_art13_transparency", **{
        "label": "Transparency Requirements",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 13"],
        "keywords": ["transparency", "interpretability", "instructions for use", "documentation"],
        "description": (
            "Article 13 — Transparency and Provision of Information to Deployers. High-risk AI systems shall be "
            "designed and developed in such a way as to ensure that their operation is sufficiently transparent to "
            "enable deployers to interpret a system's output and use it appropriately. Instructions for use shall "
            "include: (a) identity and contact details of the provider; (b) characteristics, capabilities and "
            "limitations of performance including intended purpose, level of accuracy, robustness and cybersecurity, "
            "known foreseeable circumstances that may lead to risks; (c) changes to the system pre-determined by the "
            "provider; (d) human oversight measures; (e) expected lifetime and maintenance measures; (f) technical "
            "capabilities and characteristics enabling deployers to interpret output; (g) specifications for input "
            "data. Transparency must enable deployers to comply with their obligations under Art. 26."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: What level of explainability is required? A: Art. 13 requires 'sufficient transparency to enable "
                "deployers to interpret output and use it appropriately.' This is not full algorithmic explainability — "
                "it is operational transparency. The deployer must understand: what the system does, what its limitations "
                "are, when it might fail, how to interpret its outputs, and what human oversight is needed. Recital 72 "
                "clarifies that the level of transparency should be proportionate to the risk and context of use. "
                "For critical decisions (healthcare, justice), higher interpretability is expected."
            )},
            {"type": "implementation", "text": (
                "Instructions for use must be delivered BEFORE the system is placed on the market. They must be: "
                "(1) In clear and understandable language for the target deployer (not just developers). "
                "(2) Include performance metrics with confidence intervals, tested on representative data. "
                "(3) Document all known failure modes and edge cases. (4) Provide guidance on input data requirements — "
                "what format, quality, and type of data the system expects. (5) Include model cards or datasheets. "
                "(6) Provide information on how to report issues (Art. 26(5) deployer obligation). "
                "Deployers who modify or fine-tune the system take on provider obligations per Art. 25."
            )},
            {"type": "cross_reference", "text": (
                "Transparency chain: Provider transparency (Art. 13) enables Deployer compliance (Art. 26), "
                "which enables End-user transparency. Additionally, Art. 50 requires specific transparency "
                "obligations for AI systems interacting with persons (chatbots must disclose they are AI), "
                "and Art. 50(4) requires labeling of AI-generated content (deepfakes, synthetic media). "
                "GDPR Art. 13-14 (information obligations) and Art. 22(3) (meaningful information about automated "
                "decisions) create parallel transparency obligations. A comprehensive transparency program must "
                "address BOTH AI Act and GDPR transparency requirements."
            )},
        ],
    })

    G.add_node("aiact_art14_human_oversight", **{
        "label": "Human Oversight Requirements",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 14"],
        "keywords": ["human oversight", "human-in-the-loop", "override", "intervention", "automation bias"],
        "description": (
            "Article 14 — Human Oversight. High-risk AI systems shall be designed and developed in such a way "
            "as to be effectively overseen by natural persons during the period in which they are in use. Human "
            "oversight shall aim to prevent or minimise risks to health, safety or fundamental rights that may "
            "emerge when a high-risk AI system is used in accordance with its intended purpose or under conditions "
            "of reasonably foreseeable misuse. Human oversight measures shall be identified by the provider and "
            "built into the system, or identified by the provider as appropriate to be implemented by the deployer. "
            "The system shall be provided with: tools to interpret outputs, ability to decide not to use or override, "
            "ability to intervene and halt the system. Measures must guard against automation bias, particularly "
            "where the system makes recommendations for decisions relating to natural persons."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: What is automation bias and how must it be addressed? A: Automation bias is the tendency to "
                "over-rely on AI system outputs without sufficient critical evaluation. Art. 14(4)(b) specifically "
                "requires that human oversight measures be designed to prevent automation bias, especially for "
                "decisions affecting natural persons. This means: (1) the system must NOT present its output as "
                "the definitive answer — it should present it as a recommendation; (2) the interface must encourage "
                "independent human judgment; (3) training must cover when and how to override the system; "
                "(4) the system should flag cases with high uncertainty for mandatory human review."
            )},
            {"type": "implementation", "text": (
                "Human oversight implementation patterns: (1) Human-in-the-loop: human makes every final decision — "
                "required for high-stakes decisions (criminal justice, immigration). (2) Human-on-the-loop: system "
                "acts autonomously but human monitors and can intervene — suitable for repetitive decisions with "
                "moderate risk (content moderation, fraud screening). (3) Human-in-command: human can take control "
                "at any time and halt the system — required for autonomous systems. The choice depends on risk level, "
                "decision frequency, and reversibility. Art. 14 does NOT mandate human-in-the-loop for all cases, "
                "but the oversight must be 'effective' given the risk context."
            )},
            {"type": "cross_reference", "text": (
                "Intersection with GDPR Art. 22: GDPR grants individuals the right not to be subject to decisions "
                "based solely on automated processing that produce legal or similarly significant effects. This means "
                "any AI Act high-risk system making such decisions MUST have meaningful human involvement (not just "
                "rubber-stamping). The combination of AI Act Art. 14 + GDPR Art. 22 creates a strong requirement: "
                "the human must have genuine authority and competence to override the AI decision. "
                "EDPB Guidelines on Art. 22 clarify that 'meaningful' means the human must have actual discretion "
                "and cannot merely confirm the AI output without independent evaluation."
            )},
            {"type": "enforcement", "text": (
                "Failure to provide adequate human oversight: Fines under Art. 99(4) up to EUR 15 million or 3% "
                "of turnover. But the real risk is harm-based liability — if a poorly overseen AI system causes "
                "damage to an individual, the AI Liability Directive (proposed) would create a presumption of "
                "causation. Combined with existing product liability, insufficient human oversight can result in "
                "both administrative penalties AND civil liability for damages caused."
            )},
        ],
    })

    G.add_node("aiact_art15_accuracy", **{
        "label": "Accuracy, Robustness & Cybersecurity",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 15"],
        "keywords": ["accuracy", "robustness", "cybersecurity", "adversarial", "resilience"],
        "description": (
            "Article 15 — Accuracy, Robustness and Cybersecurity. High-risk AI systems shall be designed and "
            "developed in such a way that they achieve an appropriate level of accuracy, robustness, and "
            "cybersecurity, and that they perform consistently in those respects throughout their lifecycle. "
            "Levels of accuracy and relevant metrics shall be declared in the instructions for use. High-risk AI "
            "systems shall be as resilient as possible regarding errors, faults or inconsistencies that may occur "
            "within the system or the environment. Technical redundancy solutions, including backup or fail-safe "
            "plans, may be appropriate. High-risk AI systems shall be resilient against attempts by unauthorised "
            "third parties to alter their use, outputs or performance by exploiting system vulnerabilities."
        ),
        "chunks": [
            {"type": "implementation", "text": (
                "Accuracy requirements implementation: (1) Define appropriate accuracy metrics for the use case — "
                "sensitivity/specificity for medical AI, precision/recall for fraud detection, fairness-adjusted "
                "accuracy for HR decisions. (2) Test on representative populations — not just benchmark datasets. "
                "(3) Declare accuracy levels in instructions for use with confidence intervals. (4) Implement "
                "performance monitoring to detect accuracy degradation over time (data drift, concept drift). "
                "(5) Set degradation thresholds that trigger re-training or alert to deployer."
            )},
            {"type": "qa", "text": (
                "Q: What cybersecurity measures are required for AI systems? A: Art. 15(4) requires resilience "
                "against adversarial attacks including: data poisoning (corrupting training data), model evasion "
                "(crafting inputs that fool the model), model inversion (extracting training data from model), "
                "and model theft (stealing the model itself). Specific technical measures include: input validation, "
                "adversarial training, output monitoring for anomalies, access controls, audit logging. "
                "For AI systems deployed in critical infrastructure (Annex III Cat. 2), cybersecurity requirements "
                "also align with NIS2 Directive Art. 21 security measures."
            )},
            {"type": "cross_reference", "text": (
                "NIS2 alignment: For AI systems in essential/important entities, Art. 15 cybersecurity requirements "
                "must be integrated with NIS2 Art. 21 cybersecurity risk management measures. This includes: "
                "supply chain security (NIS2 Art. 21(2)(d)), incident handling (NIS2 Art. 21(2)(b)), and "
                "vulnerability handling (NIS2 Art. 21(2)(e)). DORA alignment: For AI in financial services, "
                "Art. 15 must also satisfy DORA Art. 3-6 ICT risk management including digital operational "
                "resilience testing (DORA Art. 24-27). Three-way requirement: AI Act + NIS2 + DORA for "
                "financial critical infrastructure."
            )},
        ],
    })

    G.add_node("aiact_art17_qms", **{
        "label": "Quality Management System",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 17"],
        "keywords": ["quality management", "QMS", "ISO", "procedures", "documentation"],
        "description": (
            "Article 17 — Quality Management System. Providers of high-risk AI systems shall put in place a quality "
            "management system that ensures compliance with the AI Act in a systematic and orderly manner. The QMS "
            "shall be documented in a systematic and orderly manner in the form of written policies, procedures and "
            "instructions. It shall include at least: strategy for regulatory compliance; techniques, procedures "
            "and systematic actions for design, development, quality control and quality assurance; examination, "
            "test and validation procedures; data management including data collection, analysis and labelling; "
            "risk management system (Art. 9); post-market monitoring (Art. 72); incident reporting procedures; "
            "communication with competent authorities; record-keeping; resource management; accountability framework."
        ),
        "chunks": [
            {"type": "implementation", "text": (
                "QMS framework alignment: ISO 9001 (quality management) provides a strong foundation but must be "
                "extended for AI-specific requirements. Key additions: (1) AI lifecycle management — from data "
                "collection through deployment and monitoring. (2) Bias and fairness testing procedures. "
                "(3) Model versioning and change management. (4) Automated testing pipelines for accuracy drift. "
                "(5) Incident response procedures specific to AI failures. For medical AI: ISO 13485 (medical devices). "
                "For financial AI: integrate with DORA ICT governance framework. Documentation must be maintained "
                "for at least 10 years after the AI system has been placed on the market (Art. 18)."
            )},
            {"type": "qa", "text": (
                "Q: How does the QMS interact with conformity assessment? A: The QMS is evaluated during conformity "
                "assessment (Art. 43). For Annex I products, the QMS assessment may be part of existing notified body "
                "procedures. For Annex III systems, self-assessment is possible for some categories (except biometric "
                "identification which requires third-party), but the QMS must still be fully documented. "
                "The notified body reviews the QMS for adequacy, including review of procedures, competency records, "
                "test results, and post-market monitoring plans."
            )},
            {"type": "cross_reference", "text": (
                "Multi-framework QMS integration: Organizations under DORA must maintain ICT governance (DORA Art. 5) "
                "alongside AI Act QMS. Organizations under NIS2 must maintain cybersecurity risk management (NIS2 Art. 21) "
                "alongside AI Act QMS. The efficient approach: build a unified management system covering AI Act Art. 17, "
                "DORA ICT governance, and NIS2 cybersecurity management. Use ISO 27001 as cybersecurity backbone, "
                "extend with AI-specific and financial-specific modules."
            )},
        ],
    })

    G.add_node("aiact_art26_deployer", **{
        "label": "Deployer Obligations",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 26"],
        "keywords": ["deployer", "user", "obligations", "monitoring", "FRIA"],
        "description": (
            "Article 26 — Obligations of Deployers. Deployers of high-risk AI systems shall: (a) take appropriate "
            "technical and organisational measures to ensure they use such systems in accordance with the instructions "
            "for use; (b) assign human oversight to competent natural persons; (c) ensure that input data is relevant "
            "and sufficiently representative in view of the intended purpose; (d) monitor the operation of the "
            "high-risk AI system on the basis of the instructions for use; (e) inform the provider or distributor "
            "and the relevant market surveillance authority when they have identified a serious incident; "
            "(f) keep logs automatically generated by the system for the period prescribed by law or at least "
            "6 months; (g) use the information provided under Art. 13 to carry out a data protection impact "
            "assessment pursuant to GDPR Art. 35, where applicable."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: When does a deployer become a provider? A: Under Art. 25, a deployer becomes a provider when: "
                "(1) they put their name or trademark on a high-risk AI system already placed on the market; "
                "(2) they make a substantial modification to a high-risk AI system already placed on the market; "
                "(3) they modify the intended purpose of an AI system not classified as high-risk, making it high-risk. "
                "This is critical for fine-tuning scenarios — if a deployer fine-tunes a model and the modification "
                "is 'substantial,' they take on full provider obligations including conformity assessment."
            )},
            {"type": "implementation", "text": (
                "Deployer FRIA requirement: Art. 26(1a) mandates that deployers who are bodies governed by public law "
                "or private entities providing public services, AND deployers of high-risk AI in Annex III Categories "
                "5(b) (credit scoring) and 5(c) (risk assessment for life/health insurance) MUST carry out a "
                "Fundamental Rights Impact Assessment (FRIA) before putting the system into use. The FRIA must "
                "identify: (1) specific risks to fundamental rights; (2) affected groups; (3) measures to mitigate "
                "risks; (4) frequency and extent of use; (5) specific risks from the deployment context."
            )},
            {"type": "cross_reference", "text": (
                "Deployer Art. 26(g) explicitly connects AI Act to GDPR: deployers must use the provider's Art. 13 "
                "transparency information to carry out GDPR Art. 35 DPIA. This creates a mandatory information flow: "
                "Provider (Art. 13 documentation) → Deployer (Art. 26(g) DPIA obligation) → DPA (if DPIA shows high risk). "
                "If the provider's documentation is insufficient for the deployer to complete a DPIA, the deployer "
                "should request additional information from the provider. GDPR Art. 28 processor obligations may also "
                "apply if the provider processes personal data on behalf of the deployer."
            )},
            {"type": "enforcement", "text": (
                "Deployer non-compliance penalties: Art. 99(4) — up to EUR 15 million or 3% of turnover. "
                "Note: deployers who are SMEs or startups face proportionately lower penalties. However, deployers "
                "who are public bodies face additional accountability under national administrative law. "
                "The FRIA requirement failure (Art. 26(1a)) is separately enforceable. Deployers who fail to report "
                "serious incidents (Art. 26(e)) face penalties under Art. 99(4) PLUS potential liability if delayed "
                "reporting contributed to harm."
            )},
        ],
    })

    G.add_node("aiact_art43_conformity", **{
        "label": "Conformity Assessment",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 43", "Art. 40", "Annex VI", "Annex VII"],
        "keywords": ["conformity assessment", "notified body", "CE marking", "self-assessment", "standards"],
        "description": (
            "Article 43 — Conformity Assessment. The provider shall follow the conformity assessment procedure "
            "for high-risk AI systems. For systems referred to in Annex III points 2-8 (stand-alone high-risk "
            "use cases except biometric identification), the provider may choose self-assessment under Annex VI "
            "(internal control) when harmonised standards or common specifications are applied. For biometric "
            "identification systems (Annex III point 1) and systems that are safety components of Annex I products, "
            "third-party assessment by a notified body is required (Annex VII). Where no harmonised standards exist "
            "and common specifications are not available, third-party assessment is required even for Annex III "
            "systems. Conformity assessment evaluates the entire AI system lifecycle."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: When is third-party assessment mandatory vs self-assessment? A: Third-party (notified body) "
                "is MANDATORY for: (1) biometric identification AI (Annex III point 1 — always); (2) safety "
                "component AI systems in Annex I products where the product itself requires third-party; "
                "(3) any Annex III system where NO harmonised standards or common specifications are applied. "
                "Self-assessment (internal control, Annex VI) is allowed for: Annex III points 2-8 "
                "WHEN harmonised standards or common specifications are fully applied AND the AI system is not "
                "a biometric identification system. Most first-generation high-risk AI systems will likely need "
                "third-party assessment because harmonised standards are still being developed."
            )},
            {"type": "implementation", "text": (
                "Conformity assessment process (Annex VII — Third Party): (1) Provider submits application to "
                "notified body with technical documentation per Art. 11. (2) Notified body audits the QMS (Art. 17). "
                "(3) Notified body examines technical documentation including: risk management system, data governance, "
                "test results, accuracy metrics, cybersecurity assessment. (4) If conformity demonstrated, notified "
                "body issues certificate valid for max 5 years. (5) Provider issues EU declaration of conformity "
                "(Art. 47) and affixes CE marking (Art. 48). (6) Ongoing surveillance — notified body may audit "
                "post-market monitoring and require updates. Cost estimate: EUR 50,000-200,000 for notified body "
                "assessment depending on system complexity."
            )},
            {"type": "cross_reference", "text": (
                "CE marking chain: Conformity assessment → EU Declaration of Conformity (Art. 47) → CE Marking "
                "(Art. 48) → Registration in EU Database (Art. 49) → Market placement. For Annex I products "
                "(medical devices, machinery), the AI conformity assessment must be integrated with existing "
                "product conformity assessment. Example: AI diagnostic system must satisfy BOTH AI Act and MDR "
                "(Medical Device Regulation) conformity requirements. The notified body for AI assessment may be "
                "different from the medical device notified body — coordination is essential."
            )},
        ],
    })

    G.add_node("aiact_art50_transparency_gen", **{
        "label": "Transparency for AI Interaction & Deepfakes",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 50"],
        "keywords": ["transparency", "chatbot", "deepfake", "synthetic content", "watermark", "disclosure"],
        "description": (
            "Article 50 — Transparency Obligations for Certain AI Systems. (1) Providers shall ensure that AI "
            "systems intended to interact directly with natural persons are designed so that the natural person is "
            "informed that they are interacting with an AI system, unless this is obvious from the circumstances. "
            "(2) Providers of AI systems that generate synthetic audio, image, video or text content shall ensure "
            "that outputs are marked in a machine-readable format as artificially generated or manipulated. "
            "(3) Deployers of emotion recognition or biometric categorisation systems shall inform natural persons "
            "that they are being exposed to such a system. (4) Deployers that generate or manipulate image, audio "
            "or video constituting a deep fake shall disclose that the content has been artificially generated."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: When is AI disclosure not required? A: Art. 50(1) exempts disclosure 'when obvious from "
                "circumstances and context of use.' Recital 132 gives examples: automated phone menus where AI "
                "nature is clearly communicated. Also, Art. 50(4) exempts deepfake disclosure for: content used "
                "for law enforcement/national security, manifestly artistic/satirical work (parody, caricature), "
                "and content that constitutes part of a media freedom exercise with editorial safeguards. "
                "However, the exemptions are narrow — most commercial chatbots and generated content require "
                "disclosure."
            )},
            {"type": "implementation", "text": (
                "Technical implementation for Art. 50(2) watermarking: AI-generated content must include "
                "machine-readable markers. Current technical approaches: (1) C2PA (Coalition for Content "
                "Provenance and Authenticity) metadata standard — embeds provenance in image/video files. "
                "(2) Invisible watermarking — SynthID, StableSignature for images; AudioSeal for audio. "
                "(3) Text watermarking — statistical patterns in LLM output. The AI Office will publish "
                "technical standards for watermarking. GPAI model providers (Art. 51-53) must implement "
                "watermarking at the model level so that downstream deployers inherit the capability."
            )},
            {"type": "enforcement", "text": (
                "Timeline: Art. 50 transparency obligations apply from 2 August 2025 (12 months after entry "
                "into force). Non-compliance fines: Art. 99(5) — up to EUR 7.5 million or 1% of worldwide "
                "annual turnover for transparency violations. This is the lowest fine tier, but reputational "
                "damage from undisclosed AI use can be far more costly. Note: deepfake transparency failures "
                "may also trigger national criminal law provisions on fraud or defamation."
            )},
        ],
    })

    G.add_node("aiact_art51_gpai_systemic", **{
        "label": "GPAI Models with Systemic Risk",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 51", "Art. 52", "Art. 55"],
        "keywords": ["GPAI", "general purpose", "systemic risk", "foundation model", "10^25 FLOP"],
        "description": (
            "Article 51 — Classification of GPAI Models as Having Systemic Risk. A GPAI model shall be classified "
            "as a GPAI model with systemic risk if: (a) it has high impact capabilities evaluated on the basis of "
            "appropriate technical tools and methodologies, including indicators and benchmarks; (b) based on a "
            "Commission decision, the model has capabilities or an impact equivalent to those of models meeting "
            "criterion (a). A GPAI model shall be presumed to have high impact capabilities where the cumulative "
            "amount of computation used for its training measured in FLOPs is greater than 10^25. Obligations for "
            "systemic risk GPAI: model evaluation, adversarial testing, incident tracking and reporting to AI Office, "
            "ensure adequate cybersecurity protections, document and report energy consumption."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: Which models are considered systemic risk? A: The 10^25 FLOP threshold captures models like "
                "GPT-4 (~10^25-10^26 FLOP), Gemini Ultra, Claude 3 Opus. Smaller models like Llama-70B (~10^24) "
                "and Mistral-7B (~10^22) are below the threshold. However, the Commission can designate models "
                "below the threshold if they demonstrate high impact capabilities. The threshold will be updated "
                "as computing efficiency improves. As of 2025, ~5-10 models from major labs are likely classified "
                "as systemic risk. The AI Office published the first list in early 2025."
            )},
            {"type": "implementation", "text": (
                "GPAI systemic risk obligations (Art. 55): (1) Perform model evaluation using state-of-art "
                "protocols — including red teaming. (2) Assess and mitigate systemic risks, including risks of "
                "misuse for CBRN threats, cyber-attacks, and large-scale disinformation. (3) Track, document and "
                "report serious incidents and possible corrective measures to the AI Office and national authorities. "
                "(4) Ensure adequate cybersecurity protection. (5) Document energy consumption. Compliance through "
                "codes of practice (Art. 56) — EU AI Office coordinates industry codes of practice that, if followed, "
                "create a presumption of compliance. First codes of practice due by August 2025."
            )},
            {"type": "cross_reference", "text": (
                "GPAI + downstream high-risk: When a GPAI model is integrated into a high-risk AI system (Art. 25), "
                "the GPAI provider must make available sufficient technical documentation for the downstream provider "
                "to comply with Art. 9-15. This creates an information supply chain obligation. GPAI cybersecurity "
                "requirements (Art. 55(1)(d)) must align with NIS2 for essential service providers using the GPAI. "
                "If the GPAI model processes personal data during training, GDPR obligations apply to the GPAI "
                "provider — including lawful basis for training data (ongoing regulatory debate)."
            )},
        ],
    })

    G.add_node("aiact_art73_incidents", **{
        "label": "Serious Incident Reporting",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 73"],
        "keywords": ["incident", "reporting", "serious incident", "death", "harm", "notification"],
        "description": (
            "Article 73 — Reporting of Serious Incidents. Providers of high-risk AI systems placed on the Union "
            "market shall report any serious incident to the market surveillance authorities of the Member States "
            "where that incident occurred. A serious incident means any incident or malfunctioning of an AI system "
            "that directly or indirectly leads to: (a) the death of a person or serious damage to a person's health; "
            "(b) a serious and irreversible disruption of the management and operation of critical infrastructure; "
            "(c) breach of obligations under Union law intended to protect fundamental rights; (d) serious damage "
            "to property or the environment. Reporting deadline: immediately and no later than 15 days after the "
            "provider or deployer becomes aware of the serious incident."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: What qualifies as a 'serious incident' requiring reporting? A: Four triggers: (1) Death or "
                "serious health damage — includes physical injury and serious psychological harm. (2) Critical "
                "infrastructure disruption — must be 'serious and irreversible,' not minor outages. (3) Fundamental "
                "rights breach — discrimination in hiring, wrongful arrest from facial recognition, denial of "
                "essential services. (4) Serious property/environmental damage — environmental contamination, "
                "significant financial loss from erroneous AI decisions. Near-misses where serious harm was narrowly "
                "avoided should also be documented internally even if not reportable under Art. 73."
            )},
            {"type": "implementation", "text": (
                "Incident response timeline: T+0: Incident detected. Immediately initiate internal investigation. "
                "T+0-24h: Classify severity — is this a 'serious incident' under Art. 73 definition? "
                "T+0-72h: If yes, submit initial report to market surveillance authority of the Member State where "
                "incident occurred. Include: system identification, description of incident, initial assessment of "
                "severity, corrective measures taken. T+15 days: Submit complete report with root cause analysis. "
                "Ongoing: Cooperate with authority investigation. Report must be in the language of the Member State. "
                "For multi-state incidents, report to each affected Member State's authority."
            )},
            {"type": "cross_reference", "text": (
                "TRIPLE REPORTING RISK: A single AI incident in financial services may trigger: "
                "(1) AI Act Art. 73 — report to market surveillance authority (15 days). "
                "(2) DORA Art. 19 — report major ICT-related incident to financial competent authority (initial: "
                "4 hours, intermediate: 72 hours, final: 1 month). "
                "(3) NIS2 Art. 23 — report significant incident to CSIRT/competent authority (early warning: "
                "24 hours, full notification: 72 hours, final report: 1 month). "
                "(4) GDPR Art. 33 — report personal data breach to DPA (72 hours) + Art. 34 to affected individuals. "
                "FOUR separate reports with FOUR different deadlines to potentially FOUR different authorities. "
                "Organizations MUST have a unified incident response process that triggers all applicable reports."
            )},
            {"type": "enforcement", "text": (
                "Failure to report: Art. 99(4) — up to EUR 15 million or 3% of turnover for providers. "
                "For deployers who fail to report (Art. 26(5)): same penalty tier. Additionally, DORA Art. 48 "
                "imposes separate financial penalties for failure to report ICT incidents. GDPR Art. 83(4)(a) "
                "imposes up to EUR 10 million or 2% for breach notification failures. Cumulative penalty exposure "
                "for a single unreported incident: potentially 3%+2%+NIS2 penalties = 5%+ of turnover."
            )},
        ],
    })

    G.add_node("aiact_art99_penalties", **{
        "label": "AI Act Penalties",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 99", "Art. 100", "Art. 101"],
        "keywords": ["penalties", "fines", "enforcement", "sanctions", "administrative"],
        "description": (
            "Article 99 — Fines. (1) Non-compliance with the prohibition of AI practices under Art. 5: up to "
            "EUR 35 million or 7% of worldwide annual turnover, whichever is higher. (2) Non-compliance with "
            "requirements for high-risk AI systems (Art. 9-17, 26, 43): up to EUR 15 million or 3% of worldwide "
            "annual turnover. (3) Supplying incorrect, incomplete or misleading information to authorities: "
            "up to EUR 7.5 million or 1% of worldwide annual turnover. For SMEs and startups, the lower amount "
            "applies. Member States shall lay down rules on penalties applicable to infringements and shall "
            "ensure they are implemented effectively. Penalties shall be effective, proportionate and dissuasive."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: How do AI Act fines compare to GDPR fines? A: AI Act fines are HIGHER than GDPR for the most "
                "serious violations. Comparison: Prohibited AI practices: EUR 35M/7% (vs GDPR max EUR 20M/4%). "
                "High-risk non-compliance: EUR 15M/3% (vs GDPR EUR 20M/4%). Information supply: EUR 7.5M/1% "
                "(vs GDPR EUR 10M/2%). Critically, these fines are CUMULATIVE — a single AI system can violate "
                "BOTH the AI Act AND GDPR, leading to combined fines. For financial institutions, DORA and NIS2 "
                "penalties stack additionally. Total theoretical maximum for prohibited financial AI: "
                "7% (AI Act) + 4% (GDPR) + DORA fines + NIS2 fines = potentially 16%+ of global turnover."
            )},
            {"type": "enforcement", "text": (
                "Enforcement timeline by violation type: Prohibited practices (Art. 5): enforceable from 2 February "
                "2025. GPAI obligations (Art. 51-56): enforceable from 2 August 2025. High-risk obligations (Art. 9-17): "
                "enforceable from 2 August 2026. Full Act (all provisions): enforceable from 2 August 2027. "
                "National authorities must be designated and operational before enforcement dates. The AI Office "
                "coordinates enforcement for GPAI models. Each Member State establishes one or more market surveillance "
                "authorities. Art. 100 provides for GDPR coordination — AI Act authorities must consult data "
                "protection authorities when processing personal data."
            )},
            {"type": "implementation", "text": (
                "Fine calculation factors (Art. 99(2)): nature, gravity and duration of the infringement; "
                "intentional or negligent character; actions taken to mitigate damage; degree of responsibility "
                "(considering technical and organisational measures); previous infringements; degree of cooperation "
                "with authorities; manner in which the infringement became known (self-reporting vs. complaint); "
                "size and market share of the operator. SME reduction: the monetary cap (not %) applies — "
                "i.e., a startup faces max EUR 35M not 7% if 7% would be higher. EU institutions, agencies, "
                "and bodies: EDPS handles complaints, max fine EUR 1.5M."
            )},
            {"type": "cross_reference", "text": (
                "CUMULATIVE PENALTY CALCULATION for multi-regulation violations: "
                "Scenario: Bank deploys prohibited AI (social scoring for loan decisions) that also processes "
                "personal data unlawfully, fails ICT risk management, and misses incident report. "
                "AI Act Art. 99(3): 7% of turnover (prohibited practice). "
                "GDPR Art. 83(5): 4% of turnover (unlawful processing). "
                "DORA Art. 48: Financial supervisory penalties (varies by MS). "
                "NIS2 Art. 34: Up to EUR 10M or 2% of turnover if essential entity. "
                "Total: up to 7% + 4% + 2% + DORA = potentially 13-16% of global annual turnover. "
                "This cumulative exposure is a KEY differentiator of the EU regulatory landscape vs other jurisdictions."
            )},
        ],
    })

    # ── EU AI Act — Actors, Concepts, Processes ──

    G.add_node("aiact_provider", **{
        "label": "Provider Obligations Overview",
        "type": "Actor",
        "framework": "EU_AI_Act",
        "articles": ["Art. 16", "Art. 17", "Art. 25"],
        "keywords": ["provider", "developer", "manufacturer", "obligations", "responsible party"],
        "description": (
            "Provider of a high-risk AI system: any natural or legal person, public authority, agency or other body "
            "that develops an AI system or GPAI model or has an AI system or GPAI model developed with a view to "
            "placing it on the market or putting it into service under its own name or trademark, whether for payment "
            "or free of charge. Provider obligations: ensure conformity with Art. 8 (compliance), establish QMS (Art. 17), "
            "prepare technical documentation (Art. 11), undergo conformity assessment (Art. 43), affix CE marking "
            "(Art. 48), register in EU database (Art. 49), implement post-market monitoring (Art. 72), report "
            "serious incidents (Art. 73), correct non-conformity (Art. 20)."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: What happens when an open-source model is deployed commercially? A: The entity that integrates "
                "the open-source model into a product/service and places it on the EU market becomes the provider. "
                "Open-source GPAI models have reduced obligations under Art. 53(2) — they need only publish training "
                "data summaries and maintain a policy for copyright compliance. However, once integrated into a "
                "high-risk AI system, full provider obligations apply to whoever places the integrated system on "
                "the market. Open-source exemption does NOT apply to GPAI models with systemic risk (Art. 51)."
            )},
            {"type": "implementation", "text": (
                "Provider compliance checklist: (1) Classify your AI system per Art. 6. (2) If high-risk: "
                "establish risk management (Art. 9), data governance (Art. 10), technical documentation (Art. 11), "
                "record-keeping (Art. 12), transparency/instructions (Art. 13), human oversight design (Art. 14), "
                "accuracy/robustness/cybersecurity (Art. 15), QMS (Art. 17). (3) Undergo conformity assessment "
                "(Art. 43). (4) Register system (Art. 49). (5) Affix CE marking (Art. 48). (6) Declare conformity "
                "(Art. 47). (7) Maintain post-market monitoring (Art. 72). (8) Designate authorized rep if non-EU."
            )},
        ],
    })

    G.add_node("aiact_art2_scope", **{
        "label": "AI Act Scope & Territorial Application",
        "type": "Article",
        "framework": "EU_AI_Act",
        "articles": ["Art. 2", "Art. 3"],
        "keywords": ["scope", "territorial", "exemptions", "military", "third country"],
        "description": (
            "Article 2 — Scope. This Regulation applies to: (a) providers placing on the market or putting into "
            "service AI systems or GPAI models in the Union, irrespective of whether those providers are established "
            "within the Union or in a third country; (b) deployers of AI systems that have their place of "
            "establishment or are located within the Union; (c) providers and deployers of AI systems established "
            "in a third country, where the output produced by the system is used in the Union. Exclusions: AI systems "
            "developed exclusively for military purposes; AI systems used solely for scientific R&D purposes; "
            "persons using AI systems for purely personal, non-professional activities. Third countries' "
            "access must designate an authorised representative established in the Union."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: Does the AI Act apply to non-EU companies? A: Yes — extraterritorial scope. If a US or Chinese "
                "company's AI system output is 'used in the Union,' the AI Act applies. This covers: US SaaS AI "
                "tools with EU customers, Chinese surveillance AI deployed by EU entities, third-country GPAI "
                "models accessed by EU users. Non-EU providers must designate an EU authorized representative "
                "(Art. 22) before placing systems on the market. This mirrors GDPR's extraterritorial approach. "
                "Penalties apply even to non-EU entities through their authorized representatives."
            )},
            {"type": "implementation", "text": (
                "Scope determination flowchart: Step 1: Is the system exclusively military or R&D? → Exempt. "
                "Step 2: Is the provider established in the EU? → AI Act applies. Step 3: Is the deployer in the EU? "
                "→ AI Act applies. Step 4: Is the system output used in the EU? → AI Act applies. Step 5: Is it "
                "purely personal use? → Exempt. If ANY of Steps 2-4 are yes, full AI Act obligations apply. "
                "For multinational organizations: each deployment context must be evaluated separately. A system "
                "deployed in both EU and non-EU markets — EU-facing deployment must comply with AI Act."
            )},
        ],
    })

    G.add_node("aiact_regulatory_sandbox", **{
        "label": "AI Regulatory Sandboxes",
        "type": "Process",
        "framework": "EU_AI_Act",
        "articles": ["Art. 57", "Art. 58", "Art. 59", "Art. 60"],
        "keywords": ["sandbox", "testing", "innovation", "real-world testing", "controlled environment"],
        "description": (
            "Articles 57-60 — AI Regulatory Sandboxes and Real-World Testing. Member States shall establish at "
            "least one AI regulatory sandbox at national level by 2 August 2026. Sandboxes provide a controlled "
            "environment that facilitates the development, testing and validation of innovative AI systems for a "
            "limited time before their placement on the market. They operate under the direct supervision and "
            "guidance of the competent authorities. Participants may test high-risk AI systems in real-world "
            "conditions under specific safeguards: informed consent of subjects, ability to halt at any time, "
            "monitoring and oversight. Special provisions for SMEs and startups: priority access, reduced fees."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: Can prohibited AI be tested in a sandbox? A: No. Art. 57(1) explicitly states that AI "
                "regulatory sandboxes shall not affect the supervisory and corrective powers of competent "
                "authorities, and Art. 5 prohibited practices remain prohibited even within a sandbox. "
                "However, AI systems that are close to the prohibited/permitted boundary can benefit from "
                "sandbox guidance to determine classification. Real-world testing (Art. 60) has additional "
                "safeguards: testing plan approved by authority, informed consent, no more than what is necessary, "
                "and can be halted immediately if safety concerns arise."
            )},
            {"type": "implementation", "text": (
                "Sandbox participation benefits: (1) Direct regulatory guidance during development. (2) Legal "
                "certainty on classification and compliance requirements. (3) Streamlined conformity assessment "
                "for systems developed within the sandbox. (4) Access to high-quality data under controlled conditions. "
                "(5) Evidence gathered in sandbox can support conformity assessment. For startups: Art. 62 provides "
                "free access to sandbox, dedicated communication channels, and awareness-raising activities. "
                "Duration: typically 6-24 months depending on Member State and complexity of AI system."
            )},
        ],
    })

    # =====================================================================
    # GDPR — Key Articles for AI Intersection
    # =====================================================================

    G.add_node("gdpr_art22_automated", **{
        "label": "GDPR: Automated Individual Decision-Making",
        "type": "Article",
        "framework": "GDPR",
        "articles": ["Art. 22"],
        "keywords": ["automated decision", "profiling", "right to explanation", "human intervention", "opt-out"],
        "description": (
            "GDPR Article 22 — Automated Individual Decision-Making, Including Profiling. The data subject shall "
            "have the right not to be subject to a decision based solely on automated processing, including profiling, "
            "which produces legal effects concerning him or her or similarly significantly affects him or her. "
            "Exceptions: (a) necessary for entering into or performance of a contract; (b) authorised by Union or "
            "Member State law with suitable safeguards; (c) based on explicit consent. When decisions are based on "
            "exceptions (a) or (c), the controller shall implement suitable measures to safeguard the data subject's "
            "rights and freedoms and legitimate interests, at least the right to obtain human intervention, to "
            "express their point of view and to contest the decision."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: What constitutes a 'legal or similarly significant effect'? A: EDPB Guidelines on Art. 22 "
                "(WP251rev.01) clarify: Legal effects include decisions that affect legal status or legal rights "
                "(contract approval/denial, benefit eligibility, tax assessment). Similarly significant effects "
                "include: loan denial, employment rejection, insurance premium adjustment, targeted advertising "
                "exploiting vulnerabilities. The key test is whether the decision significantly impacts the "
                "individual's circumstances, behavior, or choices. Trivially personalized content (news feed) "
                "typically does not qualify, but content that exploits psychological vulnerabilities may."
            )},
            {"type": "cross_reference", "text": (
                "AI Act intersection: Every high-risk AI system under the AI Act that makes decisions about natural "
                "persons likely triggers GDPR Art. 22. The AI Act's human oversight requirement (Art. 14) reinforces "
                "Art. 22's human intervention right — creating a double mandate for meaningful human involvement. "
                "Credit scoring (AI Act Annex III Cat. 5b) + GDPR Art. 22 = the individual has the right to: "
                "(1) not be subject to fully automated credit decisions; (2) obtain human intervention; "
                "(3) express their point of view; (4) contest the decision; (5) receive meaningful information "
                "about the logic involved (Art. 13/14 GDPR). All while the AI system must comply with Art. 9-15 "
                "of the AI Act."
            )},
            {"type": "enforcement", "text": (
                "Art. 22 violations: Fined under GDPR Art. 83(5) — up to EUR 20 million or 4% of worldwide annual "
                "turnover. Notable precedents: Italian Garante fined food delivery platform for algorithmic "
                "discrimination in worker ratings. Dutch DPA investigated algorithmic risk profiling by tax "
                "authority (SyRI case) — ruled fundamental rights violation. French CNIL fined online platform "
                "for profiling without adequate safeguards. When combined with AI Act Art. 14 violations: "
                "GDPR fine (4%) + AI Act fine (3%) = 7% cumulative turnover exposure."
            )},
            {"type": "implementation", "text": (
                "Compliance pattern for Art. 22: (1) Map all automated decisions in your organization. "
                "(2) For each: does it produce legal/similarly significant effects? (3) If yes: which exception "
                "applies (contract necessity, legal authorization, consent)? (4) Implement safeguards: "
                "human-in-the-loop for contested decisions, right to explanation mechanism, opt-out process. "
                "(5) Provide 'meaningful information about the logic involved' — this means explaining HOW the "
                "model reaches decisions in terms the individual can understand, not source code disclosure. "
                "(6) Regularly audit for discrimination — test across protected characteristics."
            )},
        ],
    })

    G.add_node("gdpr_art35_dpia", **{
        "label": "GDPR: Data Protection Impact Assessment",
        "type": "Article",
        "framework": "GDPR",
        "articles": ["Art. 35", "Art. 36"],
        "keywords": ["DPIA", "impact assessment", "high risk processing", "prior consultation"],
        "description": (
            "GDPR Article 35 — Data Protection Impact Assessment (DPIA). Where a type of processing, in particular "
            "using new technologies including AI, is likely to result in a high risk to the rights and freedoms of "
            "natural persons, the controller shall carry out an assessment of the impact of the envisaged processing "
            "operations on the protection of personal data. A DPIA is required when: (a) systematic and extensive "
            "evaluation of personal aspects based on automated processing, including profiling; (b) processing of "
            "special categories of data on a large scale; (c) systematic monitoring of a publicly accessible area "
            "on a large scale. The DPIA shall contain: description of processing operations, assessment of necessity "
            "and proportionality, assessment of risks, and measures to address risks."
        ),
        "chunks": [
            {"type": "cross_reference", "text": (
                "AI Act connection: Art. 26(g) of the AI Act EXPLICITLY requires deployers to use provider's Art. 13 "
                "transparency documentation to carry out a GDPR Art. 35 DPIA. This creates a legal pipeline: "
                "Provider documentation (AI Act Art. 13) → Deployer DPIA (GDPR Art. 35) → DPA consultation if needed "
                "(GDPR Art. 36). For high-risk AI processing special categories (e.g., biometric AI, health AI), "
                "BOTH a DPIA AND a FRIA (AI Act Art. 26(1a)) may be required. The DPIA focuses on data protection "
                "risks while the FRIA covers broader fundamental rights. Best practice: conduct them jointly."
            )},
            {"type": "implementation", "text": (
                "DPIA for AI systems — required elements: (1) Systematic description of the AI processing: what data "
                "is collected, how it's processed, what decisions are made. (2) Purpose and legal basis assessment — "
                "which GDPR Art. 6 ground applies. (3) Necessity and proportionality — is AI processing necessary "
                "or would less intrusive means suffice? (4) Risk assessment — identify risks to data subjects: "
                "discrimination, loss of autonomy, data breaches, re-identification from anonymized data, function "
                "creep. (5) Mitigation measures — technical (pseudonymization, encryption, access controls) and "
                "organizational (training, DPO involvement, regular auditing). (6) DPA consultation: if DPIA shows "
                "high residual risk after mitigation, must consult national DPA BEFORE processing begins."
            )},
            {"type": "qa", "text": (
                "Q: When must a DPIA be updated? A: GDPR Art. 35(11) requires review when there is a change in risk. "
                "For AI systems, this means: (1) model retraining or update; (2) expansion to new data sources; "
                "(3) deployment in new contexts or populations; (4) discovery of bias or fairness issues; "
                "(5) changes in the legal landscape (new guidance from DPA or EDPB). AI Act Art. 72 post-market "
                "monitoring may surface new risks that trigger DPIA review. Best practice: review DPIA at least "
                "annually for live AI systems and after any significant model update."
            )},
        ],
    })

    G.add_node("gdpr_art5_principles", **{
        "label": "GDPR: Core Data Protection Principles",
        "type": "Article",
        "framework": "GDPR",
        "articles": ["Art. 5"],
        "keywords": ["principles", "lawfulness", "fairness", "transparency", "purpose limitation", "minimization"],
        "description": (
            "GDPR Article 5 — Principles Relating to Processing of Personal Data. Personal data shall be: "
            "(a) processed lawfully, fairly and in a transparent manner (lawfulness, fairness, transparency); "
            "(b) collected for specified, explicit and legitimate purposes and not further processed in a manner "
            "incompatible (purpose limitation); (c) adequate, relevant and limited to what is necessary (data minimisation); "
            "(d) accurate and kept up to date (accuracy); (e) kept in a form which permits identification for no longer "
            "than necessary (storage limitation); (f) processed in a manner that ensures appropriate security "
            "(integrity and confidentiality). The controller shall be responsible for, and be able to demonstrate "
            "compliance with the above (accountability)."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: How does data minimization (Art. 5(1)(c)) conflict with AI training needs? A: Fundamental tension: "
                "AI models generally perform better with MORE data, but GDPR requires data to be 'limited to what is "
                "necessary.' Resolution approaches: (1) Purpose specification — define clearly what the AI needs to "
                "achieve, then collect only data necessary for that purpose. (2) Synthetic data — augment training "
                "data with synthetic samples instead of collecting more personal data. (3) Federated learning — "
                "train on distributed data without centralizing it. (4) Differential privacy — add noise to protect "
                "individuals while maintaining statistical utility. (5) Regular review — delete training data once "
                "model is trained if the data is no longer needed."
            )},
            {"type": "cross_reference", "text": (
                "AI Act Art. 10 data governance must reconcile with GDPR Art. 5 principles: Purpose limitation — "
                "training data collected for one purpose may need legal basis for AI training (compatible purpose "
                "assessment under Art. 6(4)). Accuracy — AI Act requires representative and error-free data; "
                "GDPR requires accuracy of personal data. Storage limitation — training datasets may need indefinite "
                "retention for model reproducibility, but GDPR limits retention. Art. 10(5) AI Act provides "
                "specific basis for processing special categories for bias detection — this partially overrides "
                "GDPR Art. 9 restrictions but with strict safeguards."
            )},
            {"type": "enforcement", "text": (
                "GDPR Art. 5 violations: Maximum penalties under Art. 83(5) — EUR 20 million or 4% of worldwide "
                "annual turnover. Data minimization failures are among the most commonly cited GDPR violations "
                "in DPA enforcement actions. For AI: collecting excessive training data, failing to delete data "
                "after training, or repurposing data without compatible purpose assessment are typical violations. "
                "Accountability principle requires documented evidence of compliance — AI developers must maintain "
                "records of data processing activities (Art. 30) showing how each GDPR principle is satisfied."
            )},
        ],
    })

    G.add_node("gdpr_art25_by_design", **{
        "label": "GDPR: Data Protection by Design and Default",
        "type": "Article",
        "framework": "GDPR",
        "articles": ["Art. 25"],
        "keywords": ["by design", "by default", "privacy", "technical measures", "pseudonymization"],
        "description": (
            "GDPR Article 25 — Data Protection by Design and by Default. The controller shall implement appropriate "
            "technical and organisational measures, such as pseudonymisation, which are designed to implement data-"
            "protection principles, such as data minimisation, in an effective manner. The controller shall implement "
            "appropriate technical and organisational measures for ensuring that, by default, only personal data "
            "necessary for each specific purpose is processed. That obligation applies to the amount of personal data "
            "collected, the extent of processing, the period of storage and accessibility. Such measures shall ensure "
            "that by default personal data is not made accessible to an indefinite number of natural persons."
        ),
        "chunks": [
            {"type": "implementation", "text": (
                "Privacy by design for AI systems: (1) Architecture-level: build data protection into the AI system "
                "architecture from inception — not as an afterthought. (2) Pseudonymization: replace identifiers "
                "with pseudonyms in training and inference data. (3) Encryption: encrypt data at rest and in transit. "
                "(4) Access controls: limit who can access training data, model weights, and inference inputs/outputs. "
                "(5) Purpose-specific models: train purpose-specific models rather than general models that process "
                "excessive data. (6) Output controls: prevent the AI from revealing personal data in outputs "
                "(inference-time data leakage). (7) Audit trails: log all data access and processing for accountability."
            )},
            {"type": "cross_reference", "text": (
                "AI Act alignment: Art. 25 GDPR by-design principles map directly to several AI Act requirements: "
                "Data governance (Art. 10) should implement GDPR Art. 25 measures. Accuracy/robustness (Art. 15) "
                "overlaps with GDPR's accuracy and integrity principles. Transparency (Art. 13) supports GDPR's "
                "transparency by design. Risk management (Art. 9) should integrate data protection risks. "
                "Practical approach: use a unified 'responsible AI' framework that satisfies BOTH AI Act technical "
                "requirements AND GDPR by-design obligations simultaneously."
            )},
        ],
    })

    G.add_node("gdpr_art83_penalties", **{
        "label": "GDPR: Administrative Fines",
        "type": "Article",
        "framework": "GDPR",
        "articles": ["Art. 83", "Art. 84"],
        "keywords": ["fines", "penalties", "administrative", "enforcement", "sanctions", "DPA"],
        "description": (
            "GDPR Article 83 — General Conditions for Administrative Fines. Fines shall be effective, proportionate "
            "and dissuasive. Two tiers: (1) Up to EUR 10 million or 2% of worldwide annual turnover for violations of: "
            "controller/processor obligations (Art. 8, 11, 25-39), certification body obligations, monitoring body "
            "obligations. (2) Up to EUR 20 million or 4% of worldwide annual turnover for violations of: basic "
            "principles (Art. 5-9), data subject rights (Art. 12-22), international transfer rules (Art. 44-49), "
            "Member State law provisions. Factors: nature, gravity, duration, intentional/negligent, mitigation "
            "measures, categories of data, history, cooperation, data protection officer involvement."
        ),
        "chunks": [
            {"type": "enforcement", "text": (
                "Major AI-related GDPR enforcement actions (2022-2026): Meta fined EUR 1.2 billion for US data "
                "transfers (2023). Clearview AI fined EUR 20 million by French CNIL (2022) for biometric data "
                "processing without consent. Amazon fined EUR 746 million by Luxembourg CNPD (2021) for "
                "advertising targeting. OpenAI investigation by Italian Garante (2023-2024) for ChatGPT data "
                "processing — temporary ban lifted after remedial measures. These cases demonstrate DPAs' "
                "willingness to enforce against AI companies and set precedents for AI Act era enforcement."
            )},
            {"type": "cross_reference", "text": (
                "CUMULATIVE LIABILITY MAP: For an AI system processing personal data: "
                "Layer 1 — GDPR Art. 83: max 4% of turnover. "
                "Layer 2 — AI Act Art. 99: max 7% (prohibited), 3% (high-risk), or 1% (transparency). "
                "Layer 3 — DORA penalties: financial supervisory penalties (varies by Member State). "
                "Layer 4 — NIS2 Art. 34: max EUR 10M or 2% of turnover. "
                "AI Act Art. 99(7) explicitly states: 'Where an operator has already been subject to a penalty "
                "under GDPR for the same conduct, the AI Act penalty shall take the GDPR penalty into account.' "
                "This means fines are coordinated but NOT necessarily deduplicated — both can apply."
            )},
            {"type": "qa", "text": (
                "Q: Can GDPR fines be combined with AI Act fines for the same violation? A: Yes, but with coordination. "
                "AI Act Art. 99(7) and Art. 100 require coordination between AI Act authorities and DPAs. When the "
                "same conduct violates both laws, authorities must coordinate to ensure proportionality. However, "
                "different aspects can be penalized separately: GDPR fine for unlawful data processing + AI Act fine "
                "for inadequate risk management = two separate violations of two separate laws. The principle of "
                "'ne bis in idem' (not twice for the same) does not apply across different regulatory frameworks. "
                "EDPB and AI Board will establish coordination mechanisms."
            )},
        ],
    })

    # =====================================================================
    # DORA — Digital Operational Resilience Act
    # =====================================================================

    G.add_node("dora_art3_ict_risk", **{
        "label": "DORA: ICT Risk Management",
        "type": "Article",
        "framework": "DORA",
        "articles": ["Art. 5", "Art. 6", "Art. 7"],
        "keywords": ["ICT risk", "digital resilience", "financial entity", "operational risk"],
        "description": (
            "DORA Articles 5-7 — ICT Risk Management Framework. Financial entities shall have in place an internal "
            "governance and control framework that ensures an effective and prudent management of all ICT risks. "
            "The management body shall: define, approve, oversee and be responsible for the implementation of all "
            "arrangements related to the ICT risk management framework. The ICT risk management framework shall "
            "include strategies, policies, procedures, ICT protocols and tools necessary to duly and adequately "
            "protect all information assets and ICT assets. Financial entities shall minimise the impact of ICT risk "
            "by deploying appropriate strategies, policies, procedures, ICT protocols and tools. They shall use and "
            "maintain updated ICT systems, protocols and tools that are appropriate to the nature, variety, complexity "
            "and magnitude of operations supporting their activities."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: Which entities are subject to DORA? A: DORA applies to virtually all regulated financial entities: "
                "credit institutions, payment institutions, electronic money institutions, investment firms, crypto-asset "
                "service providers, central securities depositories, insurance/reinsurance undertakings, pension funds, "
                "credit rating agencies, crowdfunding service providers, and third-party ICT service providers "
                "designated as critical. In scope: approximately 22,000+ financial entities across the EU. "
                "Entry into application: 17 January 2025. This means ALL financial entities deploying AI must comply "
                "with DORA ICT risk management IN ADDITION TO AI Act requirements."
            )},
            {"type": "cross_reference", "text": (
                "AI + DORA integration: When a financial entity deploys an AI system for credit scoring (AI Act Annex III "
                "Cat. 5b), it must satisfy: (1) AI Act Art. 9 risk management for AI-specific risks. (2) DORA Art. 5-7 "
                "ICT risk management covering the AI infrastructure. (3) GDPR Art. 35 DPIA for data protection risks. "
                "Three separate but overlapping risk frameworks. Practical approach: create a unified risk register "
                "that maps each risk to its regulatory source(s) and demonstrates compliance with all three frameworks. "
                "DORA Art. 3(4) mandates that the ICT risk management framework is integrated into the entity's "
                "overall risk management system — AI risk management should be a sub-framework."
            )},
            {"type": "implementation", "text": (
                "DORA ICT risk management for AI systems: (1) Identify and classify all AI systems as ICT assets. "
                "(2) Map dependencies — which business processes depend on which AI systems? (3) Risk assessment — "
                "what happens if the AI system fails, produces incorrect output, or is compromised? (4) Business "
                "continuity — manual fallback procedures for AI system failures. (5) ICT change management — "
                "model updates, retraining must follow change management procedures. (6) Regular testing — "
                "DORA Art. 24-27 requires digital operational resilience testing including threat-led penetration "
                "testing (TLPT) for significant entities. AI systems within scope must be tested."
            )},
        ],
    })

    G.add_node("dora_art11_incident_reporting", **{
        "label": "DORA: ICT-Related Incident Reporting",
        "type": "Article",
        "framework": "DORA",
        "articles": ["Art. 17", "Art. 18", "Art. 19"],
        "keywords": ["incident", "reporting", "classification", "notification", "financial authority"],
        "description": (
            "DORA Articles 17-19 — ICT-Related Incident Management, Classification and Reporting. Financial entities "
            "shall define, establish and implement an ICT-related incident management process to detect, manage and "
            "notify ICT-related incidents. They shall classify ICT-related incidents according to criteria including: "
            "number of clients/counterparts affected, duration, geographical spread, data losses, criticality of "
            "services affected, economic impact. Major ICT-related incidents shall be reported to the relevant "
            "competent authority: initial notification within 4 hours of classification, intermediate report within "
            "72 hours, final report within 1 month. The competent authority shall assess the incident and may "
            "require additional information."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: What constitutes a 'major' ICT incident under DORA? A: Classification criteria (DORA Art. 18 "
                "and RTS): An incident is major if it meets thresholds on: (1) Number of clients affected — "
                ">10% of total clients or >100,000 clients; (2) Duration — >24 hours or recovery >4 hours for critical "
                "service; (3) Geographical spread — affects operations in >2 Member States; (4) Data losses — any loss "
                "of confidentiality, integrity or availability of data critical to core business; (5) Criticality — "
                "affects critical or important function; (6) Economic impact — direct costs >€100,000 or revenue "
                "impact >0.1%. An AI system failure causing incorrect credit decisions for >10% of customers "
                "would likely qualify as a major incident."
            )},
            {"type": "cross_reference", "text": (
                "QUADRUPLE REPORTING SCENARIO for AI incident in financial services: "
                "1. DORA Art. 19: Report to financial competent authority (ECB, BaFin, etc.) — 4 hours initial. "
                "2. AI Act Art. 73: Report to market surveillance authority — within 15 days. "
                "3. NIS2 Art. 23: If entity is essential/important, report to CSIRT — 24 hours early warning. "
                "4. GDPR Art. 33: If personal data breach, report to DPA — within 72 hours. "
                "Each report goes to a DIFFERENT authority with DIFFERENT timelines, DIFFERENT formats, and "
                "DIFFERENT classification criteria. A unified incident response platform is essential. "
                "Timeline compression: initial DORA report must be sent WITHIN 4 HOURS, while GDPR allows 72 hours."
            )},
            {"type": "implementation", "text": (
                "Incident response for AI systems under DORA: T+0: AI system anomaly detected (monitoring systems "
                "flag unexpected output, performance degradation, or data integrity issue). T+1h: Incident classified — "
                "is it major? Check DORA classification criteria. T+2h: If major — begin drafting reports for ALL "
                "applicable frameworks. T+4h: DORA initial notification submitted to competent authority. "
                "T+24h: NIS2 early warning submitted (if applicable). T+72h: GDPR breach notification (if personal "
                "data involved). DORA intermediate report submitted. T+15 days: AI Act serious incident report. "
                "T+1 month: DORA final report and NIS2 final report. Throughout: preserve logs, containment, "
                "root cause analysis, corrective actions."
            )},
        ],
    })

    G.add_node("dora_art28_tpsp", **{
        "label": "DORA: Third-Party ICT Service Providers",
        "type": "Article",
        "framework": "DORA",
        "articles": ["Art. 28", "Art. 29", "Art. 30"],
        "keywords": ["third party", "outsourcing", "TPSP", "critical", "concentration risk", "cloud"],
        "description": (
            "DORA Articles 28-30 — ICT Third-Party Risk. Financial entities shall manage ICT third-party risk as an "
            "integral component of ICT risk within their ICT risk management framework. Contractual arrangements with "
            "ICT third-party service providers shall include: clear description of functions/services, data processing "
            "locations, service level agreements, notice periods, data portability and interoperability obligations, "
            "access and audit rights, exit strategies. Critical or important functions outsourced to ICT third-party "
            "providers require enhanced due diligence, ongoing monitoring, and contractual safeguards. The ESAs "
            "designate critical third-party ICT service providers subject to direct oversight framework."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: How does DORA affect AI-as-a-service contracts? A: AI model providers (OpenAI, Anthropic, Google "
                "DeepMind) providing AI services to financial entities are ICT third-party service providers under "
                "DORA. Contracts must include: (1) clear SLAs for AI model performance, availability, and accuracy; "
                "(2) data processing location restrictions (data residency); (3) audit rights — the financial entity "
                "must be able to audit the AI provider; (4) exit strategy — ability to migrate to another AI provider; "
                "(5) incident notification — AI provider must notify the financial entity of incidents affecting the "
                "AI service. If the AI provider is designated as 'critical TPSP' by ESAs, direct oversight applies."
            )},
            {"type": "cross_reference", "text": (
                "AI supply chain: AI Act Art. 25 (provider obligations shifting to deployers) + DORA Art. 28-30 "
                "(third-party ICT risk) create a comprehensive AI supply chain governance framework for financial "
                "services. The AI Act requires the deployer (bank) to ensure the AI system complies with Art. 9-15. "
                "DORA requires the bank to manage the AI provider as an ICT third party with full contractual "
                "safeguards. Together: the bank must ensure both regulatory compliance of the AI system AND "
                "operational resilience of the AI service delivery. Concentration risk: if multiple banks use "
                "the same AI model (e.g., GPT-4 for credit scoring), this creates systemic concentration risk "
                "that DORA Art. 29 and ESA oversight framework address."
            )},
            {"type": "implementation", "text": (
                "DORA compliance for AI outsourcing: (1) Pre-contract: risk assessment of the AI provider "
                "(financial stability, security posture, compliance track record). (2) Contract requirements: "
                "Include all DORA Art. 30 mandatory clauses — SLAs, data location, audit rights, exit strategy, "
                "sub-contracting controls. (3) Ongoing monitoring: regular assessment of AI service performance, "
                "accuracy metrics, incident reports, security certifications. (4) Exit strategy: maintain ability "
                "to transition to alternative AI solution — avoid vendor lock-in. (5) Register of outsourcing: "
                "maintain a register of all AI third-party arrangements. (6) Board reporting: regular updates to "
                "management body on AI third-party risk."
            )},
        ],
    })

    # =====================================================================
    # NIS2 — Network and Information Security Directive
    # =====================================================================

    G.add_node("nis2_art21_security", **{
        "label": "NIS2: Cybersecurity Risk Management Measures",
        "type": "Article",
        "framework": "NIS2",
        "articles": ["Art. 21"],
        "keywords": ["cybersecurity", "risk management", "supply chain", "encryption", "access control"],
        "description": (
            "NIS2 Article 21 — Cybersecurity Risk-Management Measures. Essential and important entities shall take "
            "appropriate and proportionate technical, operational and organisational measures to manage the risks "
            "posed to the security of network and information systems. Measures shall include at least: (a) policies "
            "on risk analysis and information system security; (b) incident handling; (c) business continuity and "
            "crisis management; (d) supply chain security; (e) security in network and information systems acquisition, "
            "development and maintenance including vulnerability handling and disclosure; (f) policies and procedures "
            "to assess effectiveness of cybersecurity risk-management measures; (g) basic cyber hygiene and training; "
            "(h) policies regarding use of cryptography and encryption; (i) human resources security; (j) use of "
            "multi-factor authentication."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: Which entities are 'essential' vs 'important' under NIS2? A: Essential entities: energy (electricity, "
                "district heating, oil, gas, hydrogen), transport (air, rail, water, road), banking, financial market "
                "infrastructure, health, drinking water, waste water, digital infrastructure (DNS, TLD registries, "
                "cloud computing, data centres, CDNs), ICT service management (B2B), public administration, space. "
                "Important entities: postal services, waste management, chemicals manufacturing, food, medical devices, "
                "computers/electronics, machinery, motor vehicles, digital providers (online marketplaces, search "
                "engines, social networks). All with >50 employees or >€10M turnover."
            )},
            {"type": "cross_reference", "text": (
                "NIS2 + AI Act for critical infrastructure: An AI system managing electricity grid operations is "
                "both: (1) High-risk AI under AI Act Annex III Cat. 2 (critical infrastructure) — must comply with "
                "Art. 9-15 including cybersecurity (Art. 15). (2) An ICT system of an essential entity under NIS2 — "
                "must comply with Art. 21 cybersecurity measures. PLUS: if the energy company is publicly listed, "
                "corporate governance requirements apply. AI system supply chain security must satisfy both "
                "AI Act Art. 15(4) (adversarial resilience) AND NIS2 Art. 21(2)(d) (supply chain security). "
                "The national competent authority for NIS2 may differ from the AI Act market surveillance authority — "
                "organizations must comply with both simultaneously."
            )},
            {"type": "implementation", "text": (
                "NIS2 cybersecurity for AI systems: (1) Risk analysis: include AI-specific threats in risk assessment — "
                "model poisoning, adversarial inputs, model extraction, training data leakage. (2) Incident handling: "
                "AI-specific incident response procedures — model rollback, output monitoring, user notification. "
                "(3) Supply chain: vet AI model providers, verify training data provenance, assess open-source model "
                "security. (4) Vulnerability management: include ML/AI vulnerabilities in vulnerability scanning — "
                "OWASP ML Top 10. (5) Encryption: encrypt model weights in transit and at rest, encrypt inference "
                "inputs/outputs. (6) Access control: MFA for model management interfaces, role-based access to "
                "training pipelines. (7) Testing: include adversarial ML testing in security testing program."
            )},
        ],
    })

    G.add_node("nis2_art23_incident", **{
        "label": "NIS2: Incident Notification",
        "type": "Article",
        "framework": "NIS2",
        "articles": ["Art. 23"],
        "keywords": ["incident notification", "CSIRT", "early warning", "significant incident", "24 hours"],
        "description": (
            "NIS2 Article 23 — Reporting Obligations. Essential and important entities shall notify their CSIRT or "
            "competent authority without undue delay of any significant incident. Notification stages: (a) early "
            "warning within 24 hours of becoming aware — shall indicate whether the incident is suspected of being "
            "caused by unlawful or malicious acts; (b) incident notification within 72 hours — updating the early "
            "warning and providing initial assessment of severity and impact; (c) final report within one month "
            "after incident notification — including detailed description, root cause analysis, mitigation measures, "
            "and cross-border impact where applicable. The CSIRT or competent authority shall provide a response "
            "within 24 hours of receiving the early warning."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: What qualifies as a 'significant incident' under NIS2? A: An incident is significant if: "
                "(1) it has caused or is capable of causing severe operational disruption of the services or financial "
                "loss for the entity; (2) it has affected or is capable of affecting other natural or legal persons "
                "by causing considerable material or non-material damage. For AI systems: a significant incident "
                "could be an adversarial attack compromising an AI model, a data breach exposing training data, "
                "or an AI system failure causing cascading disruption of critical services. Note: the threshold "
                "for NIS2 'significant' is LOWER than DORA 'major' — more incidents will require NIS2 reporting."
            )},
            {"type": "cross_reference", "text": (
                "Incident timeline comparison across regulations: "
                "NIS2: 24h early warning → 72h notification → 1 month final report → CSIRT/competent authority. "
                "DORA: 4h initial → 72h intermediate → 1 month final → financial competent authority. "
                "GDPR: 72h notification → to DPA + affected individuals if high risk. "
                "AI Act: 'immediately, not later than 15 days' → market surveillance authority. "
                "FASTEST DEADLINE: DORA at 4 hours. MOST AUTHORITIES: all four if financial entity with AI system "
                "processing personal data in critical infrastructure. Recommendation: build one incident response "
                "process that triggers ALL applicable notifications from a single assessment."
            )},
            {"type": "enforcement", "text": (
                "NIS2 non-compliance penalties: Art. 34 — essential entities: max EUR 10 million or 2% of worldwide "
                "annual turnover. Important entities: max EUR 7 million or 1.4% of turnover. Management body "
                "liability: Art. 20(2) requires natural persons at management body level to be held personally "
                "liable for failure to comply. This includes CISO/CTO-level individuals. Failure to notify: "
                "separate violation from the incident itself — you can be fined for the security failure AND "
                "separately for failing to report it."
            )},
        ],
    })

    G.add_node("nis2_art34_penalties", **{
        "label": "NIS2: Penalties and Enforcement",
        "type": "Article",
        "framework": "NIS2",
        "articles": ["Art. 34", "Art. 35", "Art. 36"],
        "keywords": ["penalties", "fines", "enforcement", "essential entity", "important entity", "management liability"],
        "description": (
            "NIS2 Article 34 — General Conditions for Administrative Fines. Essential entities: fines up to EUR 10 "
            "million or 2% of worldwide annual turnover, whichever is higher. Important entities: fines up to EUR 7 "
            "million or 1.4% of worldwide annual turnover. Member States shall ensure that natural persons at management "
            "body level can be held personally liable for violations. Article 35 provides for periodic penalty payments "
            "to compel compliance. Article 36 allows Member States to provide for criminal penalties. Member States "
            "shall bring into force national implementing measures by 17 October 2024."
        ),
        "chunks": [
            {"type": "cross_reference", "text": (
                "MAXIMUM CUMULATIVE PENALTY for AI system in essential financial entity processing personal data: "
                "AI Act Art. 99: 7% of turnover (if prohibited practice, or 3% for high-risk violation). "
                "GDPR Art. 83: 4% of turnover. "
                "DORA: financial supervisory penalty (varies, typically EUR 5M-20M). "
                "NIS2 Art. 34: 2% of turnover. "
                "THEORETICAL MAXIMUM: 7% + 4% + 2% + DORA = ~16% of global annual turnover + personal "
                "liability for management (NIS2 Art. 34, DORA Art. 50). For a bank with €100B revenue: "
                "~€16B in potential fines. While actual enforcement would likely be lower due to proportionality, "
                "this cumulative exposure is unique to the EU regulatory landscape."
            )},
            {"type": "enforcement", "text": (
                "NIS2 enforcement tools beyond fines: (1) Binding instructions requiring specific security measures. "
                "(2) Implementation audits and security scans — authorities can mandate and supervise. (3) Temporary "
                "suspension of certifications or authorizations. (4) Temporary prohibition of management functions "
                "for responsible natural persons — personal ban from managing the entity. (5) Public disclosure "
                "of non-compliance ('naming and shaming'). For essential entities: supervisory authorities have "
                "proactive powers (regular inspections). For important entities: ex-post supervision (investigate "
                "after incident or complaint)."
            )},
            {"type": "qa", "text": (
                "Q: Can individuals (not just companies) be held liable under NIS2? A: Yes. Art. 20(2) explicitly "
                "provides for personal liability of natural persons at management body level who fail to ensure "
                "compliance. This means CISOs, CTOs, CIOs, and board members can face personal consequences. "
                "Additionally, Art. 36 allows Member States to impose criminal penalties. In practice, this means "
                "a board member who approved deploying an AI system without adequate cybersecurity measures could "
                "face personal fines and potentially criminal prosecution if the system is compromised. This "
                "personal liability is a key differentiator from GDPR where penalties typically target entities."
            )},
        ],
    })

    # =====================================================================
    # Cross-Framework Concepts
    # =====================================================================

    G.add_node("concept_fundamental_rights", **{
        "label": "Fundamental Rights Impact Assessment",
        "type": "Concept",
        "framework": "Cross_Framework",
        "articles": ["AI Act Art. 26(1a)", "EU Charter", "GDPR Art. 35"],
        "keywords": ["fundamental rights", "FRIA", "dignity", "non-discrimination", "proportionality"],
        "description": (
            "Fundamental Rights Impact Assessment (FRIA) — required under AI Act Art. 26(1a) for deployers that are "
            "public bodies or provide public services, AND for deployers of credit scoring AI and insurance risk "
            "assessment AI. The FRIA evaluates the impact of the AI system on fundamental rights enshrined in the "
            "EU Charter of Fundamental Rights: human dignity (Art. 1), right to life (Art. 2), integrity of the "
            "person (Art. 3), freedom of thought (Art. 10), non-discrimination (Art. 21), gender equality (Art. 23), "
            "rights of the child (Art. 24), rights of the elderly (Art. 25), integration of persons with disabilities "
            "(Art. 26), right to effective remedy (Art. 47)."
        ),
        "chunks": [
            {"type": "implementation", "text": (
                "FRIA methodology: (1) Identify all fundamental rights potentially affected by the AI system. "
                "(2) Map affected groups — who are the data subjects? Who are the decision subjects? Are there "
                "vulnerable groups? (3) Assess the AI system's potential negative impact on each right for each group. "
                "(4) Evaluate the severity (minor, significant, severe) and likelihood (rare, possible, likely). "
                "(5) Identify mitigation measures — technical (bias testing, explainability), organizational "
                "(human oversight, appeal processes), legal (redress mechanisms). (6) Assess proportionality — "
                "do the benefits of the AI system outweigh the rights impact? (7) Document and publish results. "
                "FRIA should be conducted BEFORE deployment, not after."
            )},
            {"type": "cross_reference", "text": (
                "FRIA vs DPIA: FRIA (AI Act) covers ALL fundamental rights — broader scope. DPIA (GDPR Art. 35) "
                "covers data protection risks — narrower but deeper on privacy. When BOTH are required (common for "
                "high-risk AI processing personal data), conduct them jointly but ensure EACH requirement is fully "
                "addressed. Key difference: FRIA considers rights beyond data protection — discrimination, access "
                "to services, labor rights, environmental rights. DPIA focuses on data processing risks — breach, "
                "re-identification, function creep. Combined assessment provides comprehensive rights coverage."
            )},
            {"type": "qa", "text": (
                "Q: Who must conduct a FRIA? A: AI Act Art. 26(1a) mandates FRIA for: (1) Bodies governed by public law "
                "(government agencies, public schools, public hospitals). (2) Private entities providing public services "
                "(utilities, public transport, social housing). (3) Deployers of credit scoring AI (Annex III Cat. 5b). "
                "(4) Deployers of insurance risk assessment AI (Annex III Cat. 5c). Other deployers of high-risk AI "
                "should also consider conducting a FRIA as best practice, even if not legally mandated, to demonstrate "
                "due diligence and support compliance with the proportionality principle."
            )},
        ],
    })

    G.add_node("concept_supply_chain", **{
        "label": "AI Supply Chain Liability",
        "type": "Concept",
        "framework": "Cross_Framework",
        "articles": ["AI Act Art. 25", "AI Act Art. 43", "DORA Art. 28-30"],
        "keywords": ["supply chain", "liability", "provider", "deployer", "downstream", "upstream"],
        "description": (
            "AI Supply Chain Liability — The AI Act creates a chain of responsibility: (1) GPAI model provider "
            "→ supplies model + documentation. (2) AI system provider → integrates model, ensures compliance with "
            "Art. 9-15, conducts conformity assessment. (3) Deployer → uses the system, ensures human oversight, "
            "monitors performance, reports incidents. Art. 25 defines when a deployer becomes a provider: "
            "putting name/trademark on system, making substantial modification, or changing intended purpose. "
            "DORA Art. 28-30 adds financial sector requirements: third-party ICT risk management, contractual "
            "safeguards, exit strategies. The combination creates end-to-end supply chain governance."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: When does fine-tuning make a deployer into a provider? A: Art. 25 triggers 'substantial "
                "modification' — but the Act does not define a bright line. Recital 98 suggests modifications "
                "are 'substantial' if they affect compliance with requirements or change the intended purpose. "
                "Practical guidance: (1) Prompt engineering / few-shot — NOT substantial, deployer stays deployer. "
                "(2) Fine-tuning on small dataset without changing capabilities — likely not substantial. "
                "(3) Fine-tuning that changes output characteristics or extends to new domains — likely substantial. "
                "(4) Retraining the model on new data — substantial. (5) Changing the intended purpose — always "
                "triggers provider status regardless of technical modification."
            )},
            {"type": "cross_reference", "text": (
                "Supply chain under DORA: When a bank (deployer) uses an AI credit scoring model from a fintech "
                "(AI system provider) built on a foundation model (GPAI provider): "
                "GPAI provider: Art. 53 obligations (model card, copyright compliance, training data summary). "
                "AI system provider (fintech): Full Art. 9-15 compliance, conformity assessment. "
                "Bank (deployer): Art. 26 obligations + DORA Art. 28-30 third-party risk management. "
                "The bank must contractually ensure: access to audit the AI system, incident notification, "
                "data localization, exit strategy. If the GPAI provider is designated 'critical TPSP' under "
                "DORA Art. 31, direct ESA oversight applies."
            )},
            {"type": "enforcement", "text": (
                "Supply chain enforcement: Each actor in the chain faces separate penalties for their obligations. "
                "GPAI provider non-compliance: AI Act EUR 15M/3%. AI system provider non-compliance: AI Act EUR 15M/3%. "
                "Deployer non-compliance: AI Act EUR 15M/3% + potential DORA penalties. In a failure cascade: "
                "if the GPAI model has a bias that the AI system provider fails to detect and the deployer deploys "
                "resulting in discrimination — ALL three actors could face penalties. The deployer cannot simply blame "
                "the upstream provider — they have independent monitoring and incident reporting obligations."
            )},
        ],
    })

    G.add_node("concept_ce_marking", **{
        "label": "CE Marking for AI Systems",
        "type": "Concept",
        "framework": "EU_AI_Act",
        "articles": ["Art. 48", "Art. 47", "Art. 49"],
        "keywords": ["CE marking", "declaration of conformity", "registration", "EU database", "market access"],
        "description": (
            "CE Marking for AI Systems — Article 48 requires that the CE marking be affixed visibly, legibly and "
            "indelibly to the high-risk AI system or, where that is not possible, on its packaging or accompanying "
            "documents. The CE marking indicates that the AI system conforms with the requirements of the AI Act "
            "(Chapter III, Section 2). Before the CE marking can be affixed: (1) conformity assessment completed "
            "(Art. 43); (2) EU declaration of conformity drawn up (Art. 47); (3) system registered in the EU "
            "database (Art. 49). The EU declaration of conformity states that the provider takes responsibility "
            "for compliance. Registration provides public transparency about high-risk AI systems in use."
        ),
        "chunks": [
            {"type": "implementation", "text": (
                "CE marking process for AI: Step 1: Complete conformity assessment (Art. 43). For self-assessment: "
                "verify compliance with all Art. 9-15 requirements internally. For third-party: obtain certificate "
                "from notified body. Step 2: Draft EU declaration of conformity (Art. 47) containing: provider "
                "identity, system name and description, applicable harmonised standards, notified body details "
                "(if applicable), signed by authorized person. Step 3: Register in EU database for high-risk AI "
                "systems (Art. 49) — publicly accessible, contains: system description, intended purpose, conformity "
                "status, Member States where placed on market. Step 4: Affix CE marking. Step 5: Maintain "
                "compliance — CE marking is a continuous obligation, not one-time."
            )},
            {"type": "qa", "text": (
                "Q: What happens if a CE-marked AI system is found non-compliant? A: Art. 79-82 corrective actions: "
                "(1) Market surveillance authority notifies provider of non-compliance. (2) Provider must take "
                "corrective action within a reasonable period (set by authority). (3) If not corrected: authority "
                "can restrict or prohibit the system on national market. (4) Safeguard procedure: other Member "
                "States are notified, Commission evaluates. (5) If non-compliance confirmed: provider must ensure "
                "corrective action across all Member States. (6) Penalties under Art. 99 apply additionally. "
                "For safety-critical systems: immediate market withdrawal pending investigation."
            )},
        ],
    })

    G.add_node("concept_annex3_usecases", **{
        "label": "Annex III High-Risk Use Cases",
        "type": "Concept",
        "framework": "EU_AI_Act",
        "articles": ["Art. 6", "Annex III"],
        "keywords": ["biometric", "critical infrastructure", "employment", "education", "law enforcement",
                      "credit scoring", "insurance", "migration"],
        "description": (
            "Annex III — High-Risk AI Systems (Stand-Alone). Eight categories of AI use cases deemed high-risk: "
            "(1) Biometric identification and categorisation. (2) Management and operation of critical infrastructure. "
            "(3) Education and vocational training. (4) Employment, workers management and access to self-employment. "
            "(5) Access to and enjoyment of essential private and public services: (a) determining eligibility for "
            "public assistance, (b) credit scoring, (c) risk assessment for life/health insurance, (d) emergency "
            "services dispatching. (6) Law enforcement. (7) Migration, asylum and border control management. "
            "(8) Administration of justice and democratic processes."
        ),
        "chunks": [
            {"type": "qa", "text": (
                "Q: Which Annex III categories most commonly intersect with other regulations? A: "
                "Category 2 (critical infrastructure) → intersects with NIS2 (essential entities), DORA (if financial). "
                "Category 4 (employment) → intersects with GDPR Art. 22 (automated decisions), EU employment law. "
                "Category 5 (essential services) → intersects with DORA (credit scoring), GDPR (Art. 22, Art. 35). "
                "Category 1 (biometric) → intersects with GDPR Art. 9 (special categories), national biometric laws. "
                "Category 6 (law enforcement) → intersects with LED (Law Enforcement Directive), national police law. "
                "Most compliance complexity arises in Categories 2, 4, and 5 due to multi-regulation overlap."
            )},
            {"type": "cross_reference", "text": (
                "Annex III Category 5(b) — Credit Scoring case study: An AI credit scoring system must comply with: "
                "(1) AI Act: full high-risk requirements (Art. 9-15) + conformity assessment + CE marking. "
                "(2) GDPR: Art. 22 (right not to be subject to automated decisions), Art. 35 (DPIA mandatory), "
                "Art. 13-14 (transparency). (3) DORA: ICT risk management (Art. 5-7), third-party risk (Art. 28-30), "
                "incident reporting (Art. 17-19), resilience testing (Art. 24-27). (4) EBA Guidelines: on creditworthiness "
                "assessment, on use of ML in internal models. (5) National consumer protection law. "
                "FIVE distinct regulatory layers for ONE AI system. This is why multi-governance compliance analysis "
                "requires graph-based reasoning — no single regulatory expert covers all layers."
            )},
            {"type": "implementation", "text": (
                "Compliance matrix for Annex III systems: For each high-risk AI system, document: "
                "(1) Which Annex III category applies. (2) Which additional EU regulations apply (GDPR, DORA, NIS2, "
                "sector-specific). (3) Which national laws apply (in each deployment Member State). (4) Map each "
                "requirement from each regulation to specific compliance measures. (5) Identify overlaps — where one "
                "measure satisfies multiple regulatory requirements. (6) Identify gaps — where requirements from "
                "different regulations conflict or create additional burden. (7) Establish unified governance "
                "process covering all regulatory layers. Recommended: use a multi-dimensional compliance graph."
            )},
        ],
    })

    # =====================================================================
    # EDGES — Cross-framework relationships
    # =====================================================================

    edges = [
        # EU AI Act internal structure
        ("aiact_art5_prohibited", "aiact_art99_penalties", "ENFORCED_BY", "Prohibited AI → highest penalty tier (7%/35M)"),
        ("aiact_art6_highrisk_class", "aiact_art9_risk_mgmt", "TRIGGERS", "High-risk classification triggers risk management"),
        ("aiact_art6_highrisk_class", "aiact_art10_data_gov", "TRIGGERS", "High-risk triggers data governance"),
        ("aiact_art6_highrisk_class", "aiact_art13_transparency", "TRIGGERS", "High-risk triggers transparency"),
        ("aiact_art6_highrisk_class", "aiact_art14_human_oversight", "TRIGGERS", "High-risk triggers human oversight"),
        ("aiact_art6_highrisk_class", "aiact_art15_accuracy", "TRIGGERS", "High-risk triggers accuracy/robustness"),
        ("aiact_art6_highrisk_class", "aiact_art43_conformity", "TRIGGERS", "High-risk triggers conformity assessment"),
        ("aiact_art6_highrisk_class", "concept_annex3_usecases", "DEFINED_BY", "High-risk categories from Annex III"),
        ("aiact_art17_qms", "aiact_art43_conformity", "SUPPORTS", "QMS evaluated during conformity assessment"),
        ("aiact_art43_conformity", "concept_ce_marking", "ENABLES", "Conformity assessment enables CE marking"),
        ("aiact_provider", "aiact_art17_qms", "MUST_ESTABLISH", "Provider must establish QMS"),
        ("aiact_provider", "aiact_art73_incidents", "MUST_REPORT", "Provider must report serious incidents"),
        ("aiact_art26_deployer", "aiact_art14_human_oversight", "IMPLEMENTS", "Deployer implements human oversight"),
        ("aiact_art26_deployer", "aiact_art73_incidents", "MUST_REPORT", "Deployer must report serious incidents"),
        ("aiact_art50_transparency_gen", "aiact_art51_gpai_systemic", "APPLIES_TO", "Transparency for GPAI systems"),
        ("aiact_art2_scope", "aiact_art6_highrisk_class", "SCOPES", "Scope defines where classification applies"),
        ("aiact_regulatory_sandbox", "aiact_art6_highrisk_class", "TESTS", "Sandbox helps test high-risk classification"),

        # EU AI Act ↔ GDPR cross-references
        ("aiact_art10_data_gov", "gdpr_art5_principles", "MUST_COMPLY_WITH", "AI training data must follow GDPR principles"),
        ("aiact_art10_data_gov", "gdpr_art25_by_design", "MUST_COMPLY_WITH", "Data governance must implement privacy by design"),
        ("aiact_art14_human_oversight", "gdpr_art22_automated", "REINFORCES", "AI oversight reinforces GDPR automated decision rights"),
        ("aiact_art13_transparency", "gdpr_art22_automated", "PARALLEL_OBLIGATION", "AI + GDPR transparency requirements"),
        ("aiact_art26_deployer", "gdpr_art35_dpia", "REQUIRES", "Deployers must use AI info for GDPR DPIA"),
        ("aiact_art9_risk_mgmt", "gdpr_art25_by_design", "ALIGNS_WITH", "AI risk management aligns with GDPR by-design"),
        ("aiact_art99_penalties", "gdpr_art83_penalties", "CUMULATIVE_WITH", "AI Act + GDPR fines can be cumulative"),
        ("concept_fundamental_rights", "gdpr_art35_dpia", "COMBINES_WITH", "FRIA can combine with GDPR DPIA"),

        # AI Act ↔ DORA cross-references
        ("aiact_art9_risk_mgmt", "dora_art3_ict_risk", "INTEGRATES_WITH", "AI risk management integrates with DORA ICT risk"),
        ("aiact_art73_incidents", "dora_art11_incident_reporting", "PARALLEL_OBLIGATION", "Dual reporting: AI Act + DORA"),
        ("concept_supply_chain", "dora_art28_tpsp", "INTERACTS_WITH", "AI supply chain + DORA third-party provisions"),
        ("concept_annex3_usecases", "dora_art3_ict_risk", "APPLIES_TO", "Credit scoring AI is both Annex III and DORA scope"),

        # AI Act ↔ NIS2 cross-references
        ("aiact_art15_accuracy", "nis2_art21_security", "ALIGNS_WITH", "AI cybersecurity aligns with NIS2 measures"),
        ("aiact_art73_incidents", "nis2_art23_incident", "PARALLEL_OBLIGATION", "Dual notification: AI Act + NIS2"),
        ("aiact_art99_penalties", "nis2_art34_penalties", "CUMULATIVE_WITH", "Triple liability: AI Act + NIS2 + GDPR"),
        ("concept_annex3_usecases", "nis2_art21_security", "APPLIES_TO", "Critical infrastructure AI under both AI Act and NIS2"),

        # GDPR ↔ DORA/NIS2 connections
        ("gdpr_art83_penalties", "nis2_art34_penalties", "CUMULATIVE_WITH", "GDPR + NIS2 fines cumulative"),
        ("gdpr_art35_dpia", "dora_art3_ict_risk", "COMPLEMENTS", "DPIA + DORA ICT risk assessment for financial AI"),

        # Cross-cutting concept connections
        ("concept_fundamental_rights", "aiact_art5_prohibited", "PROTECTS_AGAINST", "FRIA protects fundamental rights from prohibited AI"),
        ("concept_fundamental_rights", "aiact_art14_human_oversight", "ENSURED_BY", "Human oversight ensures fundamental rights"),
        ("concept_supply_chain", "aiact_art43_conformity", "REQUIRES_VERIFICATION", "Supply chain parties must verify conformity"),
        ("concept_ce_marking", "aiact_art2_scope", "REQUIRED_WITHIN", "CE marking required for Union market placement"),
    ]

    for source, target, rel_type, description in edges:
        G.add_edge(source, target, relationship=rel_type, description=description, weight=1.0)

    return G


def save_multi_governance_kg(path: str | Path) -> None:
    """Build and save the multi-governance KG as JSON."""
    from networkx.readwrite import json_graph
    G = build_multi_governance_kg()
    data = json_graph.node_link_data(G, edges="links")
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_kg_stats(G: nx.Graph) -> dict:
    """Get stats for the KG."""
    frameworks = {}
    total_desc_chars = 0
    total_chunk_chars = 0
    total_chunks = 0
    for _, data in G.nodes(data=True):
        fw = data.get("framework", "unknown")
        frameworks[fw] = frameworks.get(fw, 0) + 1
        total_desc_chars += len(data.get("description", ""))
        chunks = data.get("chunks", [])
        total_chunks += len(chunks)
        total_chunk_chars += sum(len(c.get("text", "")) for c in chunks)

    n = max(G.number_of_nodes(), 1)
    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "frameworks": frameworks,
        "avg_description_chars": total_desc_chars // n,
        "total_description_chars": total_desc_chars,
        "total_chunks": total_chunks,
        "avg_chunks_per_node": total_chunks / n,
        "total_chunk_chars": total_chunk_chars,
        "avg_chunk_chars": total_chunk_chars // max(total_chunks, 1),
        "total_knowledge_chars": total_desc_chars + total_chunk_chars,
        "density": nx.density(G),
        "avg_degree": sum(d for _, d in G.degree()) / n,
    }


if __name__ == "__main__":
    G = build_multi_governance_kg()
    stats = get_kg_stats(G)
    print(f"Multi-Governance KG built:")
    print(f"  Nodes: {stats['nodes']}")
    print(f"  Edges: {stats['edges']}")
    print(f"  Frameworks: {stats['frameworks']}")
    print(f"  Avg description: {stats['avg_description_chars']} chars")
    print(f"  Total chunks: {stats['total_chunks']} ({stats['avg_chunks_per_node']:.1f}/node)")
    print(f"  Avg chunk: {stats['avg_chunk_chars']} chars")
    print(f"  Total knowledge: {stats['total_knowledge_chars']:,} chars")
    print(f"  Density: {stats['density']:.3f}")
    print(f"  Avg degree: {stats['avg_degree']:.1f}")
