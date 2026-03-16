---
name: graqle-superpowers-bridge
description: Automatically inject Graqle intelligence into Superpowers workflows — preflight before plans, impact during TDD, lessons during code review
---

# Graqle × Superpowers Bridge

When both Graqle MCP tools (`graq_*`) and Superpowers skills are available in the same session, they should complement each other automatically. This bridge defines how.

## Integration Points

### 1. Before Writing Plans (writing-plans skill)

**When Superpowers' `writing-plans` skill activates**, ALSO run:

```
graq_preflight(action="implement", files=<files from the spec>)
```

This surfaces:
- Risk levels of modules being touched
- Past lessons from similar changes
- Consumer count (blast radius)

**Inject the preflight output into the plan** as a "Risk Assessment" section before task breakdown. If any module is CRITICAL risk, the plan MUST include extra test coverage for that module's consumers.

### 2. During TDD (test-driven-development skill)

**When Superpowers' `test-driven-development` skill activates**, ALSO run:

```
graq_impact(component=<module being changed>)
```

This tells the developer which OTHER modules' tests might break due to their change. Add these to the test plan:
- Direct consumers → must have tests
- 2-hop consumers → should have smoke tests

### 3. During Code Review (requesting-code-review / receiving-code-review)

**When reviewing code**, ALSO run:

```
graq_lessons(operation="modify <module name>")
```

This surfaces past mistakes related to the module being changed. The code reviewer should verify none of the past failure patterns are being repeated.

### 4. Before Completion (verification-before-completion skill)

**When Superpowers' `verification-before-completion` skill activates**, ALSO run:

```
graq_impact(component=<changed modules>)
```

Verify that ALL consumers identified by Graqle's impact analysis have been tested. If any consumer was not tested, verification FAILS — go back and add tests.

### 5. During Brainstorming (brainstorming skill)

**When exploring approaches**, ALSO run:

```
graq_context(query=<the feature being brainstormed>)
graq_reason(question="what architectural considerations apply to <feature>?")
```

This gives the brainstorming session awareness of the existing architecture, preventing designs that conflict with the codebase structure.

## How It Works

This bridge does NOT modify Superpowers' code. It works because Claude Code reads ALL skill files in the session. When Claude sees both Superpowers skills and this bridge, it knows to combine them.

The flow becomes:
```
User: "refactor the auth module"
  → Superpowers: activates writing-plans skill
  → Bridge: injects graq_preflight → "⚠️ auth has 16 consumers, CRITICAL risk"
  → Superpowers: writes plan WITH risk assessment
  → Superpowers: activates TDD skill
  → Bridge: injects graq_impact → "these 8 modules depend on auth"
  → Superpowers: TDD includes consumer tests
  → Superpowers: activates verification skill
  → Bridge: injects graq_impact check → "all 16 consumers tested? YES → PASS"
```
