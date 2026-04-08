# Gate Demos — CG-01 through CG-08

Standalone integration tests that prove each governance gate fires correctly.

**No mocks. Real server. Real config. Real enforcement.**

## Run all gate demos

```bash
cd graqle-sdk
python -m pytest gate-demos/ -v --tb=short
```

## Run a single gate demo

```bash
python -m pytest gate-demos/test_gate_demos.py::TestCG01SessionGate -v
```

## What each gate does

| Gate | Name | What it blocks |
|------|------|---------------|
| CG-01 | Session Gate | All tools until `session_start` |
| CG-02 | Plan Gate | Write tools until `graq_plan` called |
| CG-03 | Edit Enforcement | `graq_write` on code files (.py/.ts/.js) |
| CG-04 | Batch Edit Limit | Batch edits exceeding `edit_batch_max` |
| CG-05 | GCC Auto-Commit | Auto-records milestone after git commit |
| CG-06 | Design Review Mode | Pre-implementation spec review via `spec` param |
| CG-07 | Test Generation Mode | `graq_generate(mode="test")` produces pytest |
| CG-08 | Fixture Detection | Auto-discovers conftest.py in test mode |
