"""Autonomous alpha-validation harness for SDK v0.52.0a1.

13 items — one per Wave 1 gap closed. Each test feeds a demo payload to
the production code surface (via existing gate-demos fixtures), captures
a verdict, and appends to a session-scoped alpha_report.json.

Run:
    pytest tests/test_alpha_validation/ -v --no-header

Report is written to tests/test_alpha_validation/alpha_report.json at
the end of the session (see conftest.py::pytest_sessionfinish).

The harness is intentionally strict: every item must PASS before the
v0.52.0a1 alpha is cleared for public squash-merge and PyPI publish.
"""
