# 

<!-- graqle:intelligence -->
## Graqle Quality Gate (auto-generated)

### Module Risk Map
| Module | Risk | Impact | Functions | Consumers |
|--------|------|--------|-----------|-----------|
| graph | CRITICAL | 26 | 51 | 26 |
| test_error_scenarios | CRITICAL | 34 | 33 | 34 |
| api | CRITICAL | 19 | 33 | 19 |
| mcp_dev_server | HIGH | 5 | 39 | 5 |
| api | HIGH | 19 | 15 | 19 |
| middleware | HIGH | 34 | 10 | 34 |
| scan | HIGH | 2 | 69 | 2 |
| models | HIGH | 16 | 11 | 16 |
| middleware | HIGH | 34 | 9 | 34 |
| test_manager | HIGH | 0 | 64 | 0 |
| test_middleware | HIGH | 32 | 8 | 32 |
| types | HIGH | 27 | 6 | 27 |
| test_governance_middleware | HIGH | 32 | 10 | 32 |
| init | HIGH | 2 | 33 | 2 |
| base | HIGH | 31 | 4 | 31 |

### Quality Gate Status
Coverage: 100.0% chunks | 100.0% descriptions | Health: HEALTHY
Modules: 396 | Auto-repairs: 2111

### Key Insights
- **graqle.backends.mock**: HIGH RISK — impact radius: 57 modules. Changes here affect 57 other modules.
- **graqle.backends.mock**: HUB MODULE — 57 consumers AND 4 dependencies. Central connector in the codebase.
- **graqle.cli.console**: HIGH RISK — impact radius: 22 modules. Changes here affect 22 other modules.
- **graqle.cli.console**: HUB MODULE — 22 consumers AND 4 dependencies. Central connector in the codebase.
- **graqle.core.message**: HIGH RISK — impact radius: 26 modules. Changes here affect 26 other modules.
<!-- /graqle:intelligence -->
