# Contributing to CogniGraph

Thanks for your interest in contributing. Here's how to get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/quantamixsol/cognigraph.git
cd cognigraph

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"
```

## Running Tests

```bash
# Full test suite
pytest tests/ -v

# With coverage
pytest tests/ --cov=cognigraph --cov-report=term-missing

# Single test file
pytest tests/test_activation.py -v
```

## Code Style

We use **ruff** for linting and formatting:

```bash
# Check
ruff check cognigraph/
ruff format --check cognigraph/

# Auto-fix
ruff check --fix cognigraph/
ruff format cognigraph/
```

All PRs must pass `ruff check` and `ruff format --check` with zero errors.

## Pull Request Process

1. **Fork** the repo and create a feature branch from `main`
2. **Write tests** for any new functionality
3. **Run the full test suite** — all 332 tests must pass
4. **Run ruff** — zero lint errors, zero format issues
5. **Write a clear PR description** — what changed and why
6. Submit the PR and wait for review

## What We're Looking For

- Bug fixes with regression tests
- New backend integrations
- Performance improvements with benchmarks
- Documentation improvements

## What We Won't Accept

- Changes that break existing tests
- Features without tests
- PRs that modify patent-protected innovation modules without prior discussion

## Questions?

Open an issue on GitHub. We'll respond within a few days.
