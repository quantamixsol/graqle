"""EU-RegQA-20 — Domain-specific regulatory QA benchmark.

20 questions across 5 EU AI Act complexity tiers:
- Tier 1 (Lookup): direct article references
- Tier 2 (Cross-reference): spanning multiple articles
- Tier 3 (Reasoning): requiring inference from provisions
- Tier 4 (Aggregation): combining multiple regulatory domains
- Tier 5 (Analysis): open-ended policy analysis

This benchmark tests CogniGraph's advantage in domain-specific
regulatory knowledge graphs where graph topology matters.
"""

from __future__ import annotations

from dataclasses import dataclass
import networkx as nx


@dataclass
class RegQAQuestion:
    """A regulatory QA question with expected answer and metadata."""

    id: str
    question: str
    expected_answer: str
    tier: int  # 1-5 complexity
    articles: list[str]  # relevant AI Act articles
    keywords: list[str]


# The 20 benchmark questions
EU_REGQA_QUESTIONS: list[RegQAQuestion] = [
    # Tier 1: Lookup
    RegQAQuestion(
        id="regqa-01", tier=1,
        question="What is the definition of an AI system under the EU AI Act?",
        expected_answer="A machine-based system designed to operate with varying levels of autonomy, that may exhibit adaptiveness after deployment and that, for explicit or implicit objectives, infers from the input it receives how to generate outputs such as predictions, content, recommendations, or decisions that can influence physical or virtual environments.",
        articles=["Art. 3(1)"],
        keywords=["definition", "AI system", "autonomy"],
    ),
    RegQAQuestion(
        id="regqa-02", tier=1,
        question="Which AI practices are prohibited under the EU AI Act?",
        expected_answer="Prohibited practices include subliminal manipulation, exploitation of vulnerabilities, social scoring by public authorities, real-time remote biometric identification in public spaces (with exceptions), emotion recognition in workplace/education, untargeted scraping for facial recognition databases, and biometric categorization using sensitive characteristics.",
        articles=["Art. 5"],
        keywords=["prohibited", "practices", "biometric"],
    ),
    RegQAQuestion(
        id="regqa-03", tier=1,
        question="What are the risk categories defined in the EU AI Act?",
        expected_answer="The EU AI Act defines four risk categories: unacceptable risk (prohibited), high risk (subject to strict obligations), limited risk (transparency obligations), and minimal risk (no specific obligations beyond voluntary codes).",
        articles=["Art. 5", "Art. 6", "Art. 50", "Art. 95"],
        keywords=["risk categories", "classification"],
    ),
    RegQAQuestion(
        id="regqa-04", tier=1,
        question="What is the role of the AI Office under the EU AI Act?",
        expected_answer="The AI Office is established within the Commission to support implementation, coordinate enforcement of general-purpose AI model obligations, develop guidelines, and facilitate cooperation between member states.",
        articles=["Art. 64"],
        keywords=["AI Office", "enforcement", "coordination"],
    ),
    # Tier 2: Cross-reference
    RegQAQuestion(
        id="regqa-05", tier=2,
        question="How do high-risk AI requirements in Article 9 relate to the conformity assessment in Article 43?",
        expected_answer="Article 9 requires high-risk AI systems to have risk management systems, and Article 43 requires conformity assessment to verify compliance with all Chapter 2 requirements including Article 9. The assessment can be internal (Annex VI) or involve a notified body (Annex VII) depending on the system type.",
        articles=["Art. 9", "Art. 43", "Annex VI", "Annex VII"],
        keywords=["risk management", "conformity assessment", "high-risk"],
    ),
    RegQAQuestion(
        id="regqa-06", tier=2,
        question="What is the relationship between transparency obligations for providers of high-risk AI systems and general-purpose AI models?",
        expected_answer="Providers of high-risk AI systems must provide clear instructions of use (Art. 13), while providers of general-purpose AI models with systemic risk have additional transparency obligations (Art. 53) including model documentation and drawing up acceptable use policies. GPAI models integrated into high-risk systems inherit both sets of obligations.",
        articles=["Art. 13", "Art. 53", "Art. 50"],
        keywords=["transparency", "high-risk", "GPAI", "systemic risk"],
    ),
    RegQAQuestion(
        id="regqa-07", tier=2,
        question="How do the data governance requirements interact with the fundamental rights impact assessment?",
        expected_answer="Data governance requirements in Art. 10 mandate training data quality, representativeness, and bias examination. The fundamental rights impact assessment in Art. 27 requires deployers to assess how the AI system's data processing affects fundamental rights. Both mechanisms aim to prevent discriminatory outcomes but operate at different stages — Art. 10 at design/training, Art. 27 at deployment.",
        articles=["Art. 10", "Art. 27"],
        keywords=["data governance", "fundamental rights", "bias"],
    ),
    RegQAQuestion(
        id="regqa-08", tier=2,
        question="What obligations connect the CE marking requirements with market surveillance?",
        expected_answer="CE marking (Art. 48) indicates conformity with requirements. Market surveillance authorities (Art. 74) verify that CE-marked systems actually comply. If non-compliance is found, authorities can require corrective action, restrict or withdraw the system from the market, with the Commission having powers to issue Union-level measures.",
        articles=["Art. 48", "Art. 74", "Art. 79"],
        keywords=["CE marking", "market surveillance", "compliance"],
    ),
    # Tier 3: Reasoning
    RegQAQuestion(
        id="regqa-09", tier=3,
        question="If a company deploys an AI system for employee emotion recognition in the workplace, what are the legal consequences under the EU AI Act?",
        expected_answer="This would violate Article 5(1)(f) which prohibits AI systems that infer emotions of natural persons in the areas of workplace and education institutions, except where the AI system is intended to be used for medical or safety reasons. The deployer could face fines up to EUR 35 million or 7% of worldwide annual turnover, whichever is higher (Art. 99).",
        articles=["Art. 5(1)(f)", "Art. 99"],
        keywords=["emotion recognition", "workplace", "prohibition", "penalties"],
    ),
    RegQAQuestion(
        id="regqa-10", tier=3,
        question="Can a provider of a general-purpose AI model claim trade secrets to avoid disclosing training data information?",
        expected_answer="Art. 53 requires GPAI model providers to provide technical documentation including a sufficiently detailed summary of training data. While trade secrets are protected, the AI Office can require more detailed information for enforcement. The balance is struck through confidentiality procedures — information disclosed to authorities is protected, but the obligation to provide information itself cannot be avoided by claiming trade secrets.",
        articles=["Art. 53", "Art. 78"],
        keywords=["trade secrets", "training data", "GPAI", "disclosure"],
    ),
    RegQAQuestion(
        id="regqa-11", tier=3,
        question="How does the EU AI Act handle AI systems that were already on the market before the regulation applies?",
        expected_answer="Under Art. 111, AI systems already placed on the market before the regulation's application date can continue to operate. However, if they are significantly modified after that date, they must comply with the new requirements. High-risk AI systems used by public authorities must comply regardless. The phased implementation gives 6 months for prohibited practices, 12 months for GPAI, 24 months for high-risk in Annex III, and 36 months for high-risk in Annex I.",
        articles=["Art. 111", "Art. 113"],
        keywords=["transitional", "existing systems", "timeline"],
    ),
    RegQAQuestion(
        id="regqa-12", tier=3,
        question="What happens if a high-risk AI system causes harm but the provider followed all compliance requirements?",
        expected_answer="The EU AI Act focuses on ex-ante obligations (before harm). Compliance with all requirements does not automatically exempt from liability. The AI Liability Directive (separate legislation) addresses civil liability. Under the AI Act, market surveillance authorities can still investigate and require corrective measures if the system presents risks despite conformity. The provider must also report serious incidents under Art. 73.",
        articles=["Art. 73", "Art. 79", "Art. 82"],
        keywords=["liability", "harm", "compliance", "incidents"],
    ),
    # Tier 4: Aggregation
    RegQAQuestion(
        id="regqa-13", tier=4,
        question="Summarize all the obligations that apply specifically to deployers (as opposed to providers) of high-risk AI systems.",
        expected_answer="Deployers must: use systems in accordance with instructions (Art. 26), ensure human oversight (Art. 26(2)), monitor operation and report malfunctions (Art. 26(5)), conduct fundamental rights impact assessment when public body (Art. 27), keep logs for at least 6 months (Art. 26(6)), inform workers when AI is used in employment (Art. 26(7)), cooperate with authorities (Art. 26(11)), and conduct data protection impact assessment where applicable (Art. 26(9)).",
        articles=["Art. 26", "Art. 27"],
        keywords=["deployer", "obligations", "human oversight", "monitoring"],
    ),
    RegQAQuestion(
        id="regqa-14", tier=4,
        question="What are all the enforcement mechanisms and penalties available under the EU AI Act?",
        expected_answer="Enforcement operates at national (market surveillance authorities) and EU level (AI Office for GPAI). Penalties: up to EUR 35M/7% for prohibited practices, EUR 15M/3% for other obligations, EUR 7.5M/1.5% for incorrect information. SMEs get proportional caps. Additional mechanisms: corrective actions, withdrawal from market, Union safeguard procedure, formal non-compliance findings, regulatory sandboxes for controlled testing.",
        articles=["Art. 99", "Art. 74-82", "Art. 57-62"],
        keywords=["penalties", "enforcement", "fines", "market surveillance"],
    ),
    RegQAQuestion(
        id="regqa-15", tier=4,
        question="Compare the documentation requirements across different roles: provider, deployer, importer, and distributor.",
        expected_answer="Providers: full technical documentation (Annex IV), quality management system (Art. 17), EU declaration of conformity (Art. 47). Deployers: keep automatically generated logs (Art. 26(6)), maintain records of use. Importers: verify CE marking and documentation completeness (Art. 23), keep declaration of conformity. Distributors: verify CE marking present (Art. 24), ensure storage/transport doesn't compromise compliance.",
        articles=["Art. 11", "Art. 17", "Art. 23", "Art. 24", "Art. 26"],
        keywords=["documentation", "provider", "deployer", "importer", "distributor"],
    ),
    RegQAQuestion(
        id="regqa-16", tier=4,
        question="How does the EU AI Act interact with GDPR, the Product Liability Directive, and sector-specific legislation?",
        expected_answer="With GDPR: AI Act complements GDPR, requiring DPIA for high-risk AI (Art. 26(9)), recognizing GDPR as lex specialis for personal data. With Product Liability: AI Act provides ex-ante compliance framework while product liability covers ex-post damage claims. With sector-specific legislation: AI Act applies unless sector-specific Union legislation achieves equivalent outcomes (Art. 2(7)), with financial services, medical devices, and aviation having specific adjustments in Annexes.",
        articles=["Art. 2", "Recital 10", "Annex I", "Annex III"],
        keywords=["GDPR", "product liability", "sectoral", "interaction"],
    ),
    # Tier 5: Analysis
    RegQAQuestion(
        id="regqa-17", tier=5,
        question="What are the potential gaps in the EU AI Act's approach to regulating general-purpose AI models with systemic risk?",
        expected_answer="Key gaps include: (1) the 10^25 FLOP threshold for systemic risk classification may quickly become outdated as compute efficiency improves, (2) the reliance on self-assessment by providers for systemic risk evaluation, (3) limited enforcement capacity of the AI Office for global companies, (4) the tension between requiring model evaluations while protecting trade secrets, (5) no clear mechanism for addressing emergent capabilities discovered post-deployment, (6) potential regulatory arbitrage through model architecture choices that reduce measured FLOP while maintaining capability.",
        articles=["Art. 51", "Art. 52", "Art. 53", "Art. 55"],
        keywords=["GPAI", "systemic risk", "gaps", "limitations"],
    ),
    RegQAQuestion(
        id="regqa-18", tier=5,
        question="How effective is the regulatory sandbox mechanism for fostering innovation while maintaining safety?",
        expected_answer="Sandboxes (Art. 57-62) provide controlled environments for testing before market entry. Strengths: reduced compliance burden for startups, real-world testing with oversight, learning for regulators. Weaknesses: limited to national implementation (fragmentation risk), no guaranteed timeline for sandbox availability, unclear criteria for sandbox graduation, potential advantage for companies in sandbox-friendly jurisdictions, and risk that sandbox conditions don't reflect real-world deployment complexity.",
        articles=["Art. 57-62"],
        keywords=["sandbox", "innovation", "testing", "startups"],
    ),
    RegQAQuestion(
        id="regqa-19", tier=5,
        question="Analyze the tension between the EU AI Act's extraterritorial reach and practical enforceability for non-EU providers.",
        expected_answer="The Act applies to providers outside the EU whose systems are used in the EU (Art. 2(1)(c)), requiring an authorized representative. Enforcement challenges: jurisdictional limits on imposing fines, difficulty accessing technical documentation from non-EU companies, potential for regulatory circumvention through intermediaries, diplomatic tensions if large tech companies resist compliance, and the need for international cooperation agreements that don't yet exist for AI governance.",
        articles=["Art. 2", "Art. 22"],
        keywords=["extraterritorial", "enforcement", "non-EU", "jurisdiction"],
    ),
    RegQAQuestion(
        id="regqa-20", tier=5,
        question="What are the implications of the EU AI Act's approach to open-source AI models?",
        expected_answer="Open-source models get partial exemptions (Art. 2(12)) — they're exempt from most provider obligations unless classified as high-risk or GPAI with systemic risk. Implications: (1) encourages open-source development by reducing compliance burden, (2) but creates regulatory gap where capable open models avoid oversight, (3) the 'making available on the market' trigger is ambiguous for community-shared models, (4) downstream deployers using open models inherit full obligations, creating an asymmetric burden, (5) risk that the exemption incentivizes open-washing where models are technically open but practically controlled.",
        articles=["Art. 2(12)", "Art. 53"],
        keywords=["open-source", "exemptions", "GPAI", "community"],
    ),
]


def build_eu_ai_act_kg() -> nx.Graph:
    """Build a knowledge graph of the EU AI Act structure.

    Nodes: Articles, Concepts, Actors, Obligations
    Edges: DEFINES, REQUIRES, APPLIES_TO, ENFORCES, EXEMPTS
    """
    G = nx.Graph()

    # Core concept nodes
    concepts = {
        "ai_system": ("AI System", "Core definition of AI system under Art. 3"),
        "high_risk": ("High-Risk AI", "AI systems classified as high-risk under Art. 6 and Annex III"),
        "prohibited": ("Prohibited Practices", "AI practices banned under Art. 5"),
        "gpai": ("General-Purpose AI", "GPAI models and systems under Chapter V"),
        "systemic_risk": ("Systemic Risk", "GPAI models with systemic risk per Art. 51"),
        "transparency": ("Transparency", "Transparency obligations under Art. 50 and Art. 53"),
        "conformity": ("Conformity Assessment", "Conformity assessment procedures under Art. 43"),
        "risk_mgmt": ("Risk Management", "Risk management system required by Art. 9"),
        "data_gov": ("Data Governance", "Data quality and governance requirements under Art. 10"),
        "human_oversight": ("Human Oversight", "Human oversight requirements under Art. 14"),
        "market_surv": ("Market Surveillance", "Market surveillance framework under Art. 74"),
        "penalties": ("Penalties", "Administrative fines and enforcement under Art. 99"),
        "sandbox": ("Regulatory Sandbox", "AI regulatory sandboxes under Art. 57-62"),
        "fundamental_rights": ("Fundamental Rights", "Fundamental rights impact assessment under Art. 27"),
        "ce_marking": ("CE Marking", "CE marking requirements under Art. 48"),
        "provider": ("Provider", "Provider obligations under Art. 16-17"),
        "deployer": ("Deployer", "Deployer obligations under Art. 26"),
        "importer": ("Importer", "Importer obligations under Art. 23"),
        "distributor": ("Distributor", "Distributor obligations under Art. 24"),
        "ai_office": ("AI Office", "EU AI Office for GPAI oversight under Art. 64"),
        "open_source": ("Open Source", "Open-source AI exemptions under Art. 2(12)"),
        "liability": ("Liability", "Liability framework interaction with AI Liability Directive"),
        "gdpr": ("GDPR Interaction", "Interaction with General Data Protection Regulation"),
    }

    for node_id, (label, desc) in concepts.items():
        G.add_node(node_id, label=label, type="Concept", description=desc)

    # Edges — regulatory relationships
    edges = [
        ("ai_system", "high_risk", "CLASSIFIES_AS"),
        ("ai_system", "prohibited", "CLASSIFIES_AS"),
        ("ai_system", "gpai", "INCLUDES"),
        ("high_risk", "risk_mgmt", "REQUIRES"),
        ("high_risk", "data_gov", "REQUIRES"),
        ("high_risk", "human_oversight", "REQUIRES"),
        ("high_risk", "transparency", "REQUIRES"),
        ("high_risk", "conformity", "REQUIRES"),
        ("high_risk", "ce_marking", "REQUIRES"),
        ("high_risk", "fundamental_rights", "SUBJECT_TO"),
        ("gpai", "systemic_risk", "MAY_HAVE"),
        ("gpai", "transparency", "REQUIRES"),
        ("systemic_risk", "ai_office", "OVERSEEN_BY"),
        ("provider", "high_risk", "OBLIGATIONS_FOR"),
        ("deployer", "high_risk", "OBLIGATIONS_FOR"),
        ("importer", "high_risk", "OBLIGATIONS_FOR"),
        ("distributor", "high_risk", "OBLIGATIONS_FOR"),
        ("market_surv", "conformity", "VERIFIES"),
        ("market_surv", "penalties", "ENFORCES"),
        ("prohibited", "penalties", "ENFORCES"),
        ("sandbox", "high_risk", "EXEMPTS"),
        ("open_source", "gpai", "PARTIALLY_EXEMPTS"),
        ("gdpr", "data_gov", "COMPLEMENTS"),
        ("liability", "penalties", "EXTENDS"),
    ]

    for src, tgt, rel in edges:
        G.add_edge(src, tgt, relationship=rel, weight=1.0)

    return G


def get_questions_for_tier(tier: int) -> list[RegQAQuestion]:
    """Get questions for a specific complexity tier."""
    return [q for q in EU_REGQA_QUESTIONS if q.tier == tier]
