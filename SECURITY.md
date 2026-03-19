# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.29.x  | Yes       |
| 0.28.x  | Security fixes only |
| < 0.28  | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in Graqle, please report it responsibly.

**Email:** security@quantamixsolutions.com

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide an initial assessment within 5 business days.

## Security Model

### Local-First Architecture

Graqle runs entirely on your machine by default:

- **No telemetry.** Graqle does not phone home, collect usage data, or send analytics.
- **No code upload.** Your source code never leaves your machine unless you explicitly enable cloud sync.
- **Cloud sync is opt-in.** When enabled, only the knowledge graph (node/edge metadata) is uploaded — never source code.
- **API keys stay local.** LLM provider keys are stored in your local `graqle.yaml` config file.

### Knowledge Graph Privacy

The knowledge graph contains:
- File names, function names, class names, and their relationships
- Module-level descriptions and metadata
- Import chains and dependency information

The knowledge graph does **not** contain:
- Full source code
- Credentials, secrets, or environment variable values
- User data or PII

### LLM Provider Communication

When using cloud LLM backends (Anthropic, OpenAI, etc.), Graqle sends:
- The user's query
- Relevant graph context (node descriptions, relationships)
- System prompts for reasoning

Graqle does **not** send full source files to LLM providers. Only graph-level context is transmitted.

### Dependencies

We monitor dependencies for known vulnerabilities using GitHub Dependabot. All dependencies are pinned to minimum versions in `pyproject.toml`.

## Disclosure Policy

- We follow coordinated disclosure practices
- Security fixes are released as patch versions (e.g., 0.29.1)
- CVEs are published for significant vulnerabilities
- Security advisories are posted on the GitHub repository

## License

Graqle source code is fully auditable. See [LICENSE](LICENSE) for terms. The codebase is available at [github.com/quantamixsol/graqle](https://github.com/quantamixsol/graqle).
