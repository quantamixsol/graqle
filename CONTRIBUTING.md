# Contributing to Graqle

Thanks for your interest in contributing to Graqle. Here's how to get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/quantamixsol/graqle.git
cd graqle

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install in development mode
pip install -e ".[dev,api]"
```

**Requirements:** Python 3.10+ | Works on Windows, macOS, Linux

## Running Tests

```bash
# Full test suite (2,009+ tests)
python -m pytest tests/ -x -q

# With coverage
python -m pytest tests/ --cov=graqle --cov-report=term-missing

# Single test file
python -m pytest tests/test_activation.py -v
```

All 2,009+ tests must pass before submitting a PR.

## Code Style

We use **ruff** for linting and formatting:

```bash
# Check
ruff check graqle/
ruff format --check graqle/

# Auto-fix
ruff check --fix graqle/
ruff format graqle/
```

All PRs must pass `ruff check` and `ruff format --check` with zero errors.

## Pull Request Process

1. **Fork** the repo and create a feature branch from `main`
2. **Write tests** for any new functionality
3. **Run the full test suite** — all tests must pass
4. **Run ruff** — zero lint errors, zero format issues
5. **Write a clear PR description** — what changed, why, and how to test
6. Submit the PR and wait for review

## What We're Looking For

- **Bug fixes** with regression tests
- **New backend integrations** (LLM providers, graph stores)
- **Performance improvements** with benchmarks
- **Documentation improvements** (README, docstrings, examples)
- **New language support** (extractors for additional languages)

## What We Won't Accept

- Changes that break existing tests
- Features without tests
- PRs that modify patent-protected innovation modules without prior discussion

## Licensing

All contributions are licensed under the Apache 2.0 license. By submitting a PR, you agree that your contribution will be licensed under the same terms.

## Security

If you find a security vulnerability, please report it privately — see [SECURITY.md](SECURITY.md) for details. Do not open a public issue for security bugs.

## Questions?

Open an issue on [GitHub](https://github.com/quantamixsol/graqle/issues). We respond within a few days.
