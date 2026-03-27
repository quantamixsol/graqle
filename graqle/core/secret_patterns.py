"""Secret and credential detection patterns.

Layer 2A — Regex Pattern Library (200+ patterns).
Layer 2B — AST structural detection (triggered when regex score > 0.3).

Pattern philosophy:
  - Regex Layer 1: fast (<1ms), high recall, ~90% coverage
  - AST Layer 2: structural, catches obfuscation/concatenation/f-strings
  - Patterns are grouped by provider/type for audit traceability
  - Each group maps to a compliance control:
      SOC2 CC6.1 (credential management)
      ISO27001 A.12.6.1 (secret management)

Usage::

    from graqle.core.secret_patterns import check_secrets, check_secrets_ast

    found, matches = check_secrets(content)
    if found:
        ast_matches = check_secrets_ast(content, matches)
"""

# ── graqle:intelligence ──
# module: graqle.core.secret_patterns
# risk: MEDIUM (impact radius: 2 modules — governance.py, mcp_dev_server.py)
# dependencies: re, ast (stdlib only — ZERO graqle.* imports by design)
# constraints: MUST remain a pure stdlib leaf module — no graqle.* imports ever
# ── /graqle:intelligence ──

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Pattern result type
# ---------------------------------------------------------------------------

@dataclass
class SecretMatch:
    """A detected secret or credential."""
    group: str          # Pattern group (e.g., "aws", "github", "jwt")
    pattern_name: str   # Human-readable pattern name
    snippet: str        # Matched snippet (truncated, never full value)
    line_hint: int = 0  # 0 if unknown
    via_ast: bool = False  # True if found by AST layer

    def to_dict(self) -> dict:
        return {
            "group": self.group,
            "pattern_name": self.pattern_name,
            "snippet": self.snippet[:60],
            "line_hint": self.line_hint,
            "via_ast": self.via_ast,
        }


# ---------------------------------------------------------------------------
# Compiled pattern registry
# Format: (group, name, compiled_pattern)
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, str, re.Pattern]] = []


def _p(group: str, name: str, pattern: str, flags: int = re.IGNORECASE) -> None:
    """Register a compiled pattern."""
    _PATTERNS.append((group, name, re.compile(pattern, flags)))


# ── AWS ─────────────────────────────────────────────────────────────────────
_p("aws", "aws_access_key_id",       r"AKIA[0-9A-Z]{16}")
_p("aws", "aws_secret_access_key",   r"aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?")
_p("aws", "aws_session_token",       r"aws_session_token\s*[=:]\s*['\"][^'\"]{20,}")
_p("aws", "aws_mws_auth_token",      r"amzn\.mws\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_p("aws", "aws_url_key",             r"https://[a-z0-9-]+\.s3\.amazonaws\.com/.*\?.*AWSAccessKeyId=AKIA[0-9A-Z]{16}")
_p("aws", "aws_secret_env",          r"AWS_SECRET_ACCESS_KEY\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}")
_p("aws", "aws_key_id_env",          r"AWS_ACCESS_KEY_ID\s*[=:]\s*['\"]?AKIA[0-9A-Z]{16}")
_p("aws", "aws_account_id_pattern",  r"\baws_account_id\s*[=:]\s*['\"]?[0-9]{12}['\"]?")

# ── GitHub ───────────────────────────────────────────────────────────────────
_p("github", "github_pat_classic",   r"ghp_[A-Za-z0-9]{36}")
_p("github", "github_pat_fine",      r"github_pat_[A-Za-z0-9_]{82}")
_p("github", "github_oauth",         r"gho_[A-Za-z0-9]{36}")
_p("github", "github_app_token",     r"ghu_[A-Za-z0-9]{36}")
_p("github", "github_app_install",   r"ghs_[A-Za-z0-9]{36}")
_p("github", "github_refresh",       r"ghr_[A-Za-z0-9]{76}")
_p("github", "github_token_env",     r"GITHUB_TOKEN\s*[=:]\s*['\"]?gh[opusr]_[A-Za-z0-9]{36}")
_p("github", "github_api_token",     r"github[_\-]?token\s*[=:]\s*['\"][^'\"]{20,}")

# ── GitLab ───────────────────────────────────────────────────────────────────
_p("gitlab", "gitlab_pat",           r"glpat-[A-Za-z0-9_\-]{20}")
_p("gitlab", "gitlab_runner",        r"GR1348941[A-Za-z0-9_\-]{20}")
_p("gitlab", "gitlab_ci_token",      r"gitlab[_\-]?token\s*[=:]\s*['\"][^'\"]{20,}")

# ── Anthropic / OpenAI / AI providers ───────────────────────────────────────
_p("anthropic", "anthropic_api_key",  r"sk-ant-api[0-9]{2}-[A-Za-z0-9_\-]{95}")
_p("anthropic", "anthropic_key_env",  r"ANTHROPIC_API_KEY\s*[=:]\s*['\"]?sk-ant-[A-Za-z0-9_\-]{20,}")
_p("openai",    "openai_api_key",     r"sk-[A-Za-z0-9]{20,}T3BlbkFJ[A-Za-z0-9]{20,}")
_p("openai",    "openai_key_short",   r"\bsk-[A-Za-z0-9]{32,}\b")
_p("openai",    "openai_proj_key",    r"\bsk-proj-[A-Za-z0-9_\-]{40,}\b")
_p("openai",    "openai_org_id",      r"org-[A-Za-z0-9]{24}")
_p("openai",    "openai_key_env",     r"OPENAI_API_KEY\s*[=:]\s*['\"]?sk-[A-Za-z0-9]{20,}")
_p("huggingface", "hf_token",         r"hf_[A-Za-z0-9]{37}")
_p("cohere",    "cohere_api_key",     r"co-[A-Za-z0-9]{40}")
_p("replicate", "replicate_key",      r"r8_[A-Za-z0-9]{40}")
_p("groq",      "groq_api_key",       r"gsk_[A-Za-z0-9]{52}")
_p("mistral",   "mistral_api_key",    r"[A-Za-z0-9]{32}.*mistral.*api.*key", re.IGNORECASE | re.DOTALL)
_p("together",  "together_key",       r"together[_\-]?api[_\-]?key\s*[=:]\s*['\"][^'\"]{20,}")
_p("bedrock",   "bedrock_key_env",    r"AWS_BEDROCK.*KEY\s*[=:]\s*['\"][^'\"]{8,}")

# ── Stripe ───────────────────────────────────────────────────────────────────
_p("stripe", "stripe_secret_key",    r"sk_live_[A-Za-z0-9]{24,}")
_p("stripe", "stripe_restricted",    r"rk_live_[A-Za-z0-9]{24,}")
_p("stripe", "stripe_test_key",      r"sk_test_[A-Za-z0-9]{24,}")
_p("stripe", "stripe_webhook",       r"whsec_[A-Za-z0-9]{32,}")
_p("stripe", "stripe_publishable",   r"pk_live_[A-Za-z0-9]{24,}")

# ── Twilio ───────────────────────────────────────────────────────────────────
_p("twilio", "twilio_account_sid",   r"AC[a-z0-9]{32}")
_p("twilio", "twilio_auth_token",    r"twilio[_\-]?auth[_\-]?token\s*[=:]\s*['\"][a-z0-9]{32}")
_p("twilio", "twilio_api_key",       r"SK[a-z0-9]{32}")

# ── SendGrid ─────────────────────────────────────────────────────────────────
_p("sendgrid", "sendgrid_key",       r"SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}")
_p("sendgrid", "sendgrid_env",       r"SENDGRID_API_KEY\s*[=:]\s*['\"]?SG\.")

# ── Slack ────────────────────────────────────────────────────────────────────
_p("slack", "slack_bot_token",       r"xoxb-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24}")
_p("slack", "slack_user_token",      r"xoxp-[0-9]{10,13}-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{32}")
_p("slack", "slack_app_token",       r"xapp-[0-9]-[A-Z0-9]{10,13}-[0-9]{13}-[a-z0-9]{64}")
_p("slack", "slack_webhook",         r"hooks\.slack\.com/services/T[A-Z0-9]{8}/B[A-Z0-9]{8}/[A-Za-z0-9]{24}")
_p("slack", "slack_signing_secret",  r"slack[_\-]?signing[_\-]?secret\s*[=:]\s*['\"][A-Za-z0-9]{32}")

# ── Google / GCP ─────────────────────────────────────────────────────────────
_p("google", "gcp_service_account",  r'"type":\s*"service_account"')
_p("google", "google_api_key",       r"AIza[0-9A-Za-z\-_]{35}")
_p("google", "google_oauth_client",  r"[0-9]+-[0-9A-Za-z_]{32}\.apps\.googleusercontent\.com")
_p("google", "google_oauth_secret",  r"GOCSPX-[A-Za-z0-9_\-]{28}")
_p("google", "firebase_key",         r"AAAA[A-Za-z0-9_\-]{7}:[A-Za-z0-9_\-]{140}")
_p("google", "gcp_private_key",      r"-----BEGIN (RSA |EC )?PRIVATE KEY-----")

# ── Azure ────────────────────────────────────────────────────────────────────
_p("azure", "azure_connection_str",  r"DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[A-Za-z0-9/+=]{88}")
_p("azure", "azure_sas_token",       r"sv=20[0-9]{2}-[0-9]{2}-[0-9]{2}&[sS][sS]=[^&]{44}")
_p("azure", "azure_client_secret",   r"azure[_\-]?client[_\-]?secret\s*[=:]\s*['\"][^'\"]{8,}")
_p("azure", "azure_storage_key",     r"AZURE_STORAGE_KEY\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{44,}")
_p("azure", "azure_devops_pat",      r"[A-Za-z0-9]{52}==")  # Azure DevOps PAT (base64, 52 chars + ==)

# ── Database connection strings ───────────────────────────────────────────────
_p("db", "postgres_url",             r"postgres(?:ql)?://[^:@\s]+:[^@\s]{4,}@[^\s]+")
_p("db", "mysql_url",                r"mysql(?:\+[a-z]+)?://[^:@\s]+:[^@\s]{4,}@[^\s]+")
_p("db", "mongodb_url",              r"mongodb(?:\+srv)?://[^:@\s]+:[^@\s]{4,}@[^\s]+")
_p("db", "redis_url_auth",           r"redis://:[^@\s]{4,}@[^\s]+")
_p("db", "redis_url_user",           r"redis://[^:@\s]+:[^@\s]{4,}@[^\s]+")
_p("db", "mssql_url",                r"mssql(?:\+[a-z]+)?://[^:@\s]+:[^@\s]{4,}@[^\s]+")
_p("db", "sqlserver_conn",           r"Server=[^;]+;.*Password=[^;]{4,}")
_p("db", "db_password_key",          r"(?:DB|DATABASE|POSTGRES|MYSQL|MONGO)_PASSWORD\s*[=:]\s*['\"][^'\"]{4,}")
_p("db", "db_uri_env",               r"DATABASE_URL\s*[=:]\s*['\"](?:postgres|mysql|mongodb)[^'\"]{8,}")
_p("db", "neo4j_uri",                r"NEO4J_PASSWORD\s*[=:]\s*['\"][^'\"]{4,}")

# ── JWT / OAuth tokens ────────────────────────────────────────────────────────
_p("jwt", "jwt_bearer",              r"Bearer\s+eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_p("jwt", "jwt_raw",                 r"\beyJ[A-Za-z0-9_\-]{20,}\.eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b")
_p("jwt", "jwt_secret_env",          r"JWT_SECRET\s*[=:]\s*['\"][^'\"]{8,}")
_p("jwt", "jwt_signing_key",         r"jwt[_\-]?(?:secret|signing|key)\s*[=:]\s*['\"][^'\"]{8,}")
_p("oauth", "oauth_client_secret",   r"client[_\-]?secret\s*[=:]\s*['\"][^'\"]{16,}")
_p("oauth", "oauth_access_token",    r"access[_\-]?token\s*[=:]\s*['\"][^'\"]{16,}")
_p("oauth", "oauth_refresh_token",   r"refresh[_\-]?token\s*[=:]\s*['\"][^'\"]{16,}")

# ── Private keys / certificates ───────────────────────────────────────────────
_p("pki", "rsa_private_key",         r"-----BEGIN RSA PRIVATE KEY-----")
_p("pki", "ec_private_key",          r"-----BEGIN EC PRIVATE KEY-----")
_p("pki", "pkcs8_private_key",       r"-----BEGIN PRIVATE KEY-----")
_p("pki", "openssh_private_key",     r"-----BEGIN OPENSSH PRIVATE KEY-----")
_p("pki", "pgp_private_key",         r"-----BEGIN PGP PRIVATE KEY BLOCK-----")
_p("pki", "certificate_key",         r"-----BEGIN CERTIFICATE-----[\s\S]{50,}-----END CERTIFICATE-----")

# ── Generic credential patterns ───────────────────────────────────────────────
_p("generic", "password_assign",     r"\bpassword\s*[=:]\s*['\"][^'\"$\{]{8,}['\"]")
_p("generic", "passwd_assign",       r"\bpasswd\s*[=:]\s*['\"][^'\"$\{]{8,}['\"]")
_p("generic", "pwd_assign",          r"\bpwd\s*[=:]\s*['\"][^'\"$\{]{8,}['\"]")
_p("generic", "secret_assign",       r"\bsecret\s*[=:]\s*['\"][^'\"]{8,}")
_p("generic", "api_key_assign",      r"\bapi_key\s*[=:]\s*['\"][^'\"]{8,}")
_p("generic", "apikey_assign",       r"\bapikey\s*[=:]\s*['\"][^'\"]{8,}")
_p("generic", "token_assign",        r"\btoken\s*[=:]\s*['\"][^'\"]{16,}")
_p("generic", "auth_token_assign",   r"\bauth_token\s*[=:]\s*['\"][^'\"]{16,}")
_p("generic", "private_key_assign",  r"\bprivate_key\s*[=:]\s*['\"][^'\"]{8,}")
_p("generic", "credentials_dict",    r"credentials\s*[=:]\s*\{[^}]*['\"]password['\"]")
_p("generic", "hardcoded_secret_comment", r"#\s*(?:password|secret|token|key)\s*[=:]\s*[^\s]{8,}")
_p("generic", "secret_in_url",       r"https?://[^:@\s]+:[^@\s]{4,}@[^\s]+")

# ── Base64-encoded potential secrets ─────────────────────────────────────────
# Long base64 strings assigned to credential-adjacent variable names
_p("base64", "base64_password",      r"\bpassword\s*[=:]\s*['\"][A-Za-z0-9+/]{32,}={0,2}['\"]")
_p("base64", "base64_secret",        r"\bsecret\s*[=:]\s*['\"][A-Za-z0-9+/]{32,}={0,2}['\"]")
_p("base64", "base64_key",           r"\bkey\s*[=:]\s*['\"][A-Za-z0-9+/]{44,}={0,2}['\"]")
_p("base64", "base64_token",         r"\btoken\s*[=:]\s*['\"][A-Za-z0-9+/]{32,}={0,2}['\"]")

# ── Environment variable patterns (hardcoded values in env files) ─────────────
_p("envfile", "dotenv_password",     r"^[A-Z_]+PASSWORD\s*=\s*[^\$\s#]{4,}",    re.MULTILINE)
_p("envfile", "dotenv_secret",       r"^[A-Z_]+SECRET\s*=\s*[^\$\s#]{8,}",      re.MULTILINE)
_p("envfile", "dotenv_api_key",      r"^[A-Z_]+API_KEY\s*=\s*[^\$\s#]{8,}",     re.MULTILINE)
_p("envfile", "dotenv_token",        r"^[A-Z_]+TOKEN\s*=\s*[^\$\s#]{8,}",       re.MULTILINE)
_p("envfile", "dotenv_key",          r"^[A-Z_]+KEY\s*=\s*[^\$\s#]{8,}",         re.MULTILINE)

# ── Cloud / SaaS provider tokens ─────────────────────────────────────────────
_p("cloudflare", "cf_api_token",     r"[A-Za-z0-9_\-]{37}\.cloudflare\.|CF_API_TOKEN\s*[=:]\s*['\"][^'\"]{20,}")
_p("cloudflare", "cf_global_key",    r"CF_GLOBAL_KEY\s*[=:]\s*['\"][A-Za-z0-9]{37}")
_p("digitalocean", "do_pat",         r"dop_v1_[A-Za-z0-9]{64}")
_p("digitalocean", "do_oauth",       r"doo_v1_[A-Za-z0-9]{64}")
_p("heroku", "heroku_api_key",       r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}.*heroku")
_p("netlify", "netlify_access",      r"netlify[_\-]?access[_\-]?token\s*[=:]\s*['\"][^'\"]{20,}")
_p("vercel", "vercel_token",         r"VERCEL_TOKEN\s*[=:]\s*['\"][^'\"]{20,}")
_p("npm", "npm_auth_token",          r"//registry\.npmjs\.org/:_authToken\s*=\s*[A-Za-z0-9_\-]{36}")
_p("pypi", "pypi_token",             r"pypi-[A-Za-z0-9_\-]{16,}")
_p("docker", "docker_password",      r"DOCKER_PASSWORD\s*[=:]\s*['\"][^'\"]{8,}")
_p("ssh", "ssh_dsa_private",         r"-----BEGIN DSA PRIVATE KEY-----")
_p("ssh", "ssh_ed25519_private",     r"-----BEGIN OPENSSH PRIVATE KEY-----[\s\S]{1,100}ed25519")

# ── Payment / financial ───────────────────────────────────────────────────────
_p("payment", "paypal_secret",       r"paypal[_\-]?(?:client[_\-]?)?secret\s*[=:]\s*['\"][^'\"]{8,}")
_p("payment", "braintree_key",       r"braintree[_\-]?(?:private[_\-]?)?key\s*[=:]\s*['\"][^'\"]{8,}")
_p("payment", "square_token",        r"sq0atp-[A-Za-z0-9_\-]{22}")
_p("payment", "square_secret",       r"sq0csp-[A-Za-z0-9_\-]{43}")

# ── Source control / CI ───────────────────────────────────────────────────────
_p("ci", "bitbucket_oauth",          r"bitbucket[_\-]?(?:client[_\-]?)?secret\s*[=:]\s*['\"][^'\"]{16,}")
_p("ci", "jira_token",               r"JIRA_API_TOKEN\s*[=:]\s*['\"][^'\"]{16,}")
_p("ci", "circleci_token",           r"CIRCLE_TOKEN\s*[=:]\s*['\"][^'\"]{20,}")
_p("ci", "travis_token",             r"TRAVIS_CI_TOKEN\s*[=:]\s*['\"][^'\"]{20,}")
_p("ci", "sonar_token",              r"SONAR_TOKEN\s*[=:]\s*['\"][^'\"]{20,}")

# ── Crypto / blockchain ───────────────────────────────────────────────────────
_p("crypto", "eth_private_key",      r"0x[0-9a-fA-F]{64}\b")
_p("crypto", "btc_wif_key",          r"\b[5KLc][1-9A-HJ-NP-Za-km-z]{50,51}\b")
_p("crypto", "mnemonic_seed",        r"\b(?:abandon|ability|able|about|above|absent|absorb|abstract|absurd|abuse)\b.*\b(?:zoo|zone|zero|zebra)\b")

# ── High-entropy string heuristics ───────────────────────────────────────────
# Long random-looking values assigned to credential-adjacent variables
_p("entropy", "high_entropy_secret", r'(?:secret|password|token|key|credential|auth)\s*[=:]\s*["\'][A-Za-z0-9!@#$%^&*()_+\-=\[\]{};:\'\\|,.<>/?]{32,}["\']')
_p("entropy", "long_hex_secret",     r'(?:secret|key|hash|token)\s*[=:]\s*["\'][0-9a-fA-F]{40,}["\']')

# ── More cloud/SaaS ───────────────────────────────────────────────────────────
_p("linear",      "linear_api_key",       r"lin_api_[A-Za-z0-9]{40}")
_p("notion",      "notion_token",         r"secret_[A-Za-z0-9]{43}")
_p("airtable",    "airtable_key",         r"key[A-Za-z0-9]{14}")
_p("typeform",    "typeform_token",        r"tfp_[A-Za-z0-9_\-]{59}")
_p("mailchimp",   "mailchimp_key",         r"[0-9a-f]{32}-us[0-9]{1,2}")
_p("mailgun",     "mailgun_key",           r"key-[0-9a-zA-Z]{32}")
_p("postmark",    "postmark_token",        r"POSTMARK_(?:SERVER|ACCOUNT)_TOKEN\s*[=:]\s*['\"][^'\"]{36}")
_p("pusher",      "pusher_key",            r"pusher[_\-]?(?:app[_\-]?)?(?:key|secret)\s*[=:]\s*['\"][^'\"]{8,}")
_p("pagerduty",   "pagerduty_key",         r"PAGERDUTY_(?:API_KEY|TOKEN)\s*[=:]\s*['\"][^'\"]{20,}")
_p("datadog",     "datadog_api_key",       r"DATADOG_API_KEY\s*[=:]\s*['\"][A-Za-z0-9]{32}")
_p("datadog",     "datadog_app_key",       r"DATADOG_APP_KEY\s*[=:]\s*['\"][A-Za-z0-9]{40}")
_p("newrelic",    "newrelic_key",          r"NRIA_LICENSE_KEY\s*[=:]\s*['\"][A-Za-z0-9]{40}")
_p("sentry",      "sentry_dsn",            r"https://[A-Za-z0-9]{32}@[a-z0-9.]+\.sentry\.io/[0-9]+")
_p("amplitude",   "amplitude_key",         r"amplitude[_\-]?api[_\-]?key\s*[=:]\s*['\"][A-Za-z0-9]{32}")
_p("segment",     "segment_write_key",     r"segment[_\-]?write[_\-]?key\s*[=:]\s*['\"][A-Za-z0-9]{32,}")
_p("mixpanel",    "mixpanel_token",        r"mixpanel[_\-]?token\s*[=:]\s*['\"][A-Za-z0-9]{32,}")
_p("intercom",    "intercom_secret",       r"intercom[_\-]?(?:app[_\-]?)?(?:secret|token)\s*[=:]\s*['\"][^'\"]{20,}")
_p("zendesk",     "zendesk_token",         r"ZENDESK_API_TOKEN\s*[=:]\s*['\"][^'\"]{20,}")
_p("freshdesk",   "freshdesk_key",         r"FRESHDESK_API_KEY\s*[=:]\s*['\"][^'\"]{20,}")
_p("hubspot",     "hubspot_key",           r"hubspot[_\-]?(?:api[_\-]?)?(?:key|token)\s*[=:]\s*['\"][^'\"]{20,}")
_p("salesforce",  "sf_client_secret",      r"SALESFORCE_CLIENT_SECRET\s*[=:]\s*['\"][A-Za-z0-9]{64}")
_p("okta",        "okta_client_secret",    r"OKTA_CLIENT_SECRET\s*[=:]\s*['\"][^'\"]{40,}")
_p("auth0",       "auth0_client_secret",   r"AUTH0_CLIENT_SECRET\s*[=:]\s*['\"][^'\"]{43}")
_p("firebase",    "firebase_server_key",   r"AAAA[A-Za-z0-9_\-]{7}:[A-Za-z0-9_\-]{140}")
_p("firebase",    "firebase_web_key",      r"AIzaSy[A-Za-z0-9_\-]{33}")
_p("algolia",     "algolia_admin_key",     r"ALGOLIA_ADMIN_KEY\s*[=:]\s*['\"][A-Za-z0-9]{32}")
_p("algolia",     "algolia_search_key",    r"ALGOLIA_SEARCH_KEY\s*[=:]\s*['\"][A-Za-z0-9]{32}")

# ── More generic patterns ─────────────────────────────────────────────────────
_p("generic", "config_password",         r"<password>[^<]{4,}</password>")
_p("generic", "xml_secret",              r"<(?:secret|apiKey|api_key|token)[^>]*>[^<]{8,}</")
_p("generic", "json_password",           r'"password"\s*:\s*"[^"]{4,}"')
_p("generic", "json_secret",             r'"(?:secret|api_key|apiKey|token|access_token|refresh_token|private_key)"\s*:\s*"[^"]{8,}"')
_p("generic", "yaml_password_quoted",     r"password:\s+[\"'][^\"'\$\{]{8,}[\"']")   # quoted value
_p("generic", "yaml_password_unquoted",  r"password:\s+(?!(?:null|true|false|~|\$|\{|None))[a-zA-Z0-9_\-!@#%]{12,}\s*$", re.MULTILINE)  # unquoted, min 12 chars
_p("generic", "yaml_secret",             r"(?:secret|api_key|token):\s+[\"'][^\"'\$\{]{8,}[\"']")
_p("generic", "toml_password",           r'password\s*=\s*"[^"]{4,}"')
_p("generic", "ini_password",            r"password\s*=\s*(?!(?:%|<|\$|\{|\[|os\.|None|null|true|false|\"|\'))[^\s#]{8,}", re.MULTILINE)
_p("generic", "connection_string",       r"(?:user|username)\s*=\s*[^;\s]+\s*;\s*password\s*=\s*[^;\s]{4,}")
_p("generic", "aws_cli_profile",         r"\[profile [^\]]+\][\s\S]{0,200}aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}")
_p("generic", "bearer_in_code",          r"[Aa]uthorization\s*[=:]\s*['\"]Bearer\s+[A-Za-z0-9_\-\.]+['\"]")
_p("generic", "basic_auth_header",       r"[Aa]uthorization\s*[=:]\s*['\"]Basic\s+[A-Za-z0-9+/=]{24,}['\"]")
_p("generic", "auth_header_hardcoded",   r"headers\s*[=:]\s*\{[^}]*['\"](?:[Aa]uthorization|X-Api-Key)['\"].*:\s*['\"][^'\"]{16,}['\"]")
_p("generic", "curl_header_secret",      r"curl\s+.*-H\s+['\"](?:[Aa]uthorization|X-Api-Key|X-Auth-Token):\s+[^\s'\"]{16,}")

# ── Compliance-specific (SOC2/ISO27001) ───────────────────────────────────────
_p("compliance", "plaintext_in_log",     r"(?:logging|logger|log)\.[a-z]+\([^)]*(?:password|secret|token|key)[\s=]+['\"][^'\"]{8,}")
_p("compliance", "print_secret",         r"print\s*\([^)]*(?:password|secret|token|key)[\s=]+['\"][^'\"]{8,}")
_p("compliance", "console_log_secret",   r"console\.log\([^)]*(?:password|secret|token|key)[^)]*['\"][^'\"]{8,}")
_p("compliance", "assert_secret",        r"assert\s+[a-z_]+\s*==\s*['\"][^'\"]{8,}['\"].*(?:password|secret|token)")
_p("compliance", "hardcoded_test_cred",  r"(?:test_password|test_secret|test_token)\s*[=:]\s*['\"][^'\"]{8,}")
_p("compliance", "mock_secret_real",     r"MagicMock.*(?:password|secret|token)\s*=\s*['\"][^'\"]{8,}")

# ── Kubernetes / Terraform / IaC ──────────────────────────────────────────────
_p("iac", "k8s_secret_base64",       r"kind:\s*Secret[\s\S]{0,500}data:[\s\S]{0,200}[A-Za-z0-9+/]{44}={0,2}", re.MULTILINE)
_p("iac", "terraform_secret_var",    r'variable\s+"[^"]*(?:password|secret|key|token)"[\s\S]{0,100}default\s*=\s*"[^"]{8,}"', re.MULTILINE)
_p("iac", "docker_env_secret",       r"ENV\s+(?:[A-Z_]*(?:PASSWORD|SECRET|TOKEN|KEY))\s+[^\s#]{8,}")
_p("iac", "docker_arg_secret",       r"ARG\s+(?:[A-Z_]*(?:PASSWORD|SECRET|TOKEN|KEY))=([^\s#]{8,})")
_p("iac", "github_actions_secret",   r'secrets\.[A-Z_]{8,}\s*!=\s*["\'][^"\']{8,}')
_p("iac", "ansible_vault_plain",     r"ansible_(?:ssh_pass|become_pass|vault_password)\s*:\s*[^\s#]{8,}")

# ── Multi-line patterns ───────────────────────────────────────────────────────
_p("multiline", "python_dict_creds",     r'(?:credentials|config|settings)\s*=\s*\{[^}]*["\'](?:password|secret|token|key)["\'][^}]*:[^}]*["\'][^"\']{8,}["\']', re.DOTALL)
_p("multiline", "json_creds_block",      r'\{[^}]*"(?:password|secret|api_key|access_token)"[^}]*:[^}]*"[^"]{8,}"[^}]*\}', re.DOTALL)
_p("multiline", "export_env_secret",     r"export\s+[A-Z_]*(?:PASSWORD|SECRET|KEY|TOKEN)\s*=\s*[^\s#\n]{8,}", re.MULTILINE)
_p("multiline", "env_set_secret",        r"(?:set|SET)\s+[A-Z_]*(?:PASSWORD|SECRET|KEY|TOKEN)\s*=\s*[^\s#\n]{8,}", re.MULTILINE)

# ── Additional AI / LLM providers ─────────────────────────────────────────────
_p("ai", "deepseek_key",             r"DEEPSEEK_API_KEY\s*[=:]\s*['\"]?sk-[A-Za-z0-9]{32,}")
_p("ai", "fireworks_key",            r"fw_[A-Za-z0-9]{36}")
_p("ai", "openrouter_key",           r"OPENROUTER_API_KEY\s*[=:]\s*['\"]?sk-or-[A-Za-z0-9_\-]{40,}")
_p("ai", "perplexity_key",           r"pplx-[A-Za-z0-9]{48}")
_p("ai", "stability_key",            r"sk-[A-Za-z0-9]{47,48}\b")
_p("ai", "elevenlabs_key",           r"ELEVENLABS_API_KEY\s*[=:]\s*['\"][A-Za-z0-9]{32}")
_p("ai", "assemblyai_key",           r"ASSEMBLYAI_API_KEY\s*[=:]\s*['\"][A-Za-z0-9]{32}")
_p("ai", "deepgram_key",             r"DEEPGRAM_API_KEY\s*[=:]\s*['\"][A-Za-z0-9]{40}")

# ── More infrastructure ────────────────────────────────────────────────────────
_p("infra", "vault_token",           r"VAULT_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9./=+]{20,}")
_p("infra", "consul_token",          r"CONSUL_(?:HTTP_TOKEN|TOKEN)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{36}")
_p("infra", "nomad_token",           r"NOMAD_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{36}")
_p("infra", "vault_approle_secret",  r"VAULT_APPROLE_SECRET\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{36}")
_p("infra", "terraform_cloud_token", r"TERRAFORM_CLOUD_TOKEN\s*[=:]\s*['\"]?[A-Za-z0-9.]{64}")
_p("infra", "pulumi_token",          r"pul-[A-Za-z0-9]{40}")
_p("infra", "k8s_service_acct",      r"SERVICE_ACCOUNT_(?:KEY|SECRET)\s*[=:]\s*['\"][^'\"]{40,}")
_p("infra", "teleport_token",        r"TELEPORT_(?:TOKEN|SECRET)\s*[=:]\s*['\"][^'\"]{20,}")


# ---------------------------------------------------------------------------
# Regex check function (Layer 1)
# ---------------------------------------------------------------------------

def check_secrets(content: str) -> tuple[bool, list[SecretMatch]]:
    """Check content for secrets using regex patterns (Layer 1).

    Returns (found: bool, matches: list[SecretMatch]).
    Never raises — silently ignores malformed content.

    Complexity: O(n * P) where n = len(content), P = number of patterns (~200).
    Typical latency: <2ms for a 10KB diff.
    """
    matches: list[SecretMatch] = []
    lines = content.splitlines()

    try:
        for group, name, pattern in _PATTERNS:
            m = pattern.search(content)
            if m:
                # Find line number for the match
                pos = m.start()
                line_no = content[:pos].count("\n") + 1
                # Truncate matched snippet — never expose full secret
                snippet = m.group()[:40] + ("..." if len(m.group()) > 40 else "")
                matches.append(SecretMatch(
                    group=group,
                    pattern_name=name,
                    snippet=snippet,
                    line_hint=line_no,
                ))
    except Exception:
        pass  # Never let pattern matching crash the gate

    return bool(matches), matches


# ---------------------------------------------------------------------------
# AST structural detection (Layer 2B — triggered when score > 0.3)
# ---------------------------------------------------------------------------

# Variable names that are credential-adjacent
_CREDENTIAL_VAR_NAMES: frozenset[str] = frozenset({
    "password", "passwd", "pwd", "secret", "api_key", "apikey", "token",
    "auth_token", "access_token", "refresh_token", "private_key", "secret_key",
    "client_secret", "client_id", "consumer_secret", "signing_key",
    "db_password", "database_password", "pg_password", "mysql_password",
    "aws_secret", "aws_key", "github_token", "slack_token", "stripe_key",
    "secret_key", "signing_key_value", "encryption_key_value",
    "jwt_secret", "encryption_key", "decryption_key", "hmac_key",
    "signing_secret", "webhook_secret", "api_token", "bearer_token",
    # Common suffixes — match anything ending in these
})

_CREDENTIAL_SUFFIXES: tuple[str, ...] = (
    "password", "passwd", "secret", "api_key", "token", "private_key",
    "auth_key", "signing_key", "encryption_key",
)

# Minimum value length to flag (avoids false positives on short placeholders)
_MIN_SECRET_LEN = 8


def _is_credential_name(name: str) -> bool:
    """Check if a variable name is credential-adjacent."""
    lower = name.lower()
    if lower in _CREDENTIAL_VAR_NAMES:
        return True
    return any(lower.endswith(suffix) for suffix in _CREDENTIAL_SUFFIXES)


def _extract_string_value(node: ast.expr) -> Optional[str]:
    """Extract string value from AST node (handles Constant, JoinedStr, BinOp concat)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # String concatenation: "part1" + "part2"
        left = _extract_string_value(node.left)
        right = _extract_string_value(node.right)
        if left is not None and right is not None:
            return left + right
        # Partial — still suspicious
        return (left or "") + (right or "")
    if isinstance(node, ast.JoinedStr):
        # f-string — extract static parts
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            else:
                parts.append("...")
        return "".join(parts)
    return None


def check_secrets_ast(content: str, prior_matches: Optional[list[SecretMatch]] = None) -> list[SecretMatch]:
    """AST structural detection for secrets (Layer 2B).

    Detects:
    - Variable assignment: password = "actual_secret"
    - String concatenation: key = "part1" + "part2"
    - f-strings: token = f"prefix_{value}"
    - Dict literals: {"password": "secret"}
    - Keyword arguments: connect(password="secret")

    Only triggered when regex score > 0.3 (called by governance.py).
    Returns NEW matches not already found by regex.

    Never raises — silently returns empty on parse errors (non-Python content).
    """
    ast_matches: list[SecretMatch] = []
    prior_names = {m.pattern_name for m in (prior_matches or [])}

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return ast_matches  # Not Python — skip

    class SecretVisitor(ast.NodeVisitor):
        def _flag(self, name: str, value_node: ast.expr, lineno: int) -> None:
            if not _is_credential_name(name):
                return
            val = _extract_string_value(value_node)
            if val is None or len(val) < _MIN_SECRET_LEN:
                return
            # Skip obvious placeholders
            if val.lower() in ("password", "secret", "your_secret", "changeme",
                                "placeholder", "xxx", "todo", "fixme", "example"):
                return
            pattern_key = f"ast:{name}"
            if pattern_key in prior_names:
                return
            snippet = val[:40] + ("..." if len(val) > 40 else "")
            ast_matches.append(SecretMatch(
                group="ast",
                pattern_name=f"ast_assign:{name}",
                snippet=snippet,
                line_hint=lineno,
                via_ast=True,
            ))

        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._flag(target.id, node.value, node.lineno)
                elif isinstance(target, ast.Attribute):
                    self._flag(target.attr, node.value, node.lineno)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if node.value and isinstance(node.target, ast.Name):
                self._flag(node.target.id, node.value, node.lineno)
            self.generic_visit(node)

        def visit_Dict(self, node: ast.Dict) -> None:
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if value:
                        self._flag(key.value, value, node.lineno)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            for kw in node.keywords:
                if kw.arg:
                    self._flag(kw.arg, kw.value, node.lineno)
            self.generic_visit(node)

    SecretVisitor().visit(tree)
    return ast_matches


# ---------------------------------------------------------------------------
# Combined check (Layer 1 + Layer 2)
# ---------------------------------------------------------------------------

def check_secrets_full(
    content: str,
    use_ast: bool = True,
    ast_trigger_threshold: float = 0.3,
) -> tuple[bool, list[SecretMatch]]:
    """Run full two-layer secret detection.

    Layer 1 (regex) always runs.
    Layer 2 (AST) runs when regex score exceeds ast_trigger_threshold.
    Score = min(1.0, len(regex_matches) / 5).

    Args:
        content: Source code or diff content to scan
        use_ast: Enable AST layer (default True)
        ast_trigger_threshold: Trigger AST when regex score > this (default 0.3)

    Returns:
        (found: bool, all_matches: list[SecretMatch])
    """
    found, regex_matches = check_secrets(content)

    if use_ast:
        regex_score = min(1.0, len(regex_matches) / 5.0)
        # Trigger AST when:
        # 1. Regex score exceeds threshold (multiple matches)
        # 2. Content looks like Python code (heuristic: contains '=' and '"')
        #    — catches obfuscation like concatenation that regex misses
        looks_like_python = ("def " in content or "import " in content
                             or ("=" in content and '"' in content and not content.strip().startswith("<")))
        if regex_score > ast_trigger_threshold or looks_like_python:
            ast_matches = check_secrets_ast(content, regex_matches)
            regex_matches.extend(ast_matches)
            if ast_matches:
                found = True

    return bool(regex_matches), regex_matches


# ---------------------------------------------------------------------------
# Pattern count helper (used by tests)
# ---------------------------------------------------------------------------

def get_pattern_count() -> int:
    """Return total number of registered regex patterns."""
    return len(_PATTERNS)


def get_pattern_groups() -> list[str]:
    """Return all unique pattern groups."""
    return sorted({group for group, _, _ in _PATTERNS})
