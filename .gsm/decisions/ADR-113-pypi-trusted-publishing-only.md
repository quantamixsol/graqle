# ADR-113: PyPI Publishing via Trusted Publishing Only
**Date:** 2026-03-26 | **Status:** ACCEPTED

**Context:**
The project had both a legacy API token ("cognigraph" in ~/.pypirc) and a GitHub Actions OIDC Trusted Publisher configured. Using both caused PyPI to send warning emails on every twine upload. The cognigraph API token has now been deleted from PyPI.

**Decision:**
All PyPI uploads for graqle MUST go through GitHub Actions Trusted Publishing only. Never use twine or API tokens locally.

**Publishing process:**
1. Bump version in `graqle/__version__.py` and `pyproject.toml`
2. Update `CHANGELOG.md`
3. `git commit`, `git tag vX.Y.Z`, `git push origin master`, `git push origin vX.Y.Z`
4. CI workflow triggers automatically on the tag and publishes to PyPI via OIDC

**Consequences:**
- Positive: No more PyPI warning emails. Single source of truth for publishing.
- Positive: Publishing is auditable — every release tied to a specific GitHub Actions run.
- Negative: Cannot publish without a tag push (acceptable — all releases should be tagged anyway).
- Watch out: `~/.pypirc` may still exist with the old token. The token is deleted from PyPI so it will fail silently — but do not re-add it.
