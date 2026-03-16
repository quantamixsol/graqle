---
name: graqle-uiux-bridge
description: Inject Graqle's architecture data into UI UX ProMax design decisions — component dependencies inform layout, module risk informs complexity
---

# Graqle × UI UX ProMax Bridge

When both Graqle MCP tools (`graq_*`) and UI UX ProMax skill are available, architecture intelligence should inform design decisions.

## Integration Points

### 1. Before Generating Dashboards

**When UI UX ProMax generates a dashboard**, ALSO run:

```
graq_inspect()
```

Use the graph stats (node count, edge count, type distribution) to inform dashboard layout:
- High node count → use treemap or heatmap, not flat lists
- Many edge types → need relationship legend
- Module risk distribution → color-code by risk level

### 2. Before Designing Component Architecture

**When designing a multi-component UI**, ALSO run:

```
graq_reason(question="what are the main modules and their dependencies in this codebase?")
```

Use the dependency structure to inform component hierarchy:
- Highly-connected modules → should be prominent in the UI
- Isolated modules → can be in secondary navigation
- Critical-risk modules → need visual indicators (red badges, warning icons)

### 3. When Building Data Visualization Pages

**When creating pages that display code/project data**, ALSO run:

```
graq_context(query=<the data being visualized>)
```

This ensures the UI accurately represents the underlying architecture rather than inventing arbitrary groupings.

## How It Works

Claude Code reads this bridge alongside UI UX ProMax's SKILL.md. When a user asks for UI/UX work on a Graqle-aware project, Claude automatically queries the knowledge graph to inform design decisions.

The flow becomes:
```
User: "build a dashboard showing module health"
  → UI UX ProMax: activates design skill, picks style/palette
  → Bridge: runs graq_inspect → "380 modules, 17 HIGH risk, 2 CRITICAL"
  → UI UX ProMax: designs treemap colored by risk, not generic cards
  → Bridge: runs graq_reason → "auth and graph modules are most connected"
  → UI UX ProMax: places auth and graph prominently in layout
```
