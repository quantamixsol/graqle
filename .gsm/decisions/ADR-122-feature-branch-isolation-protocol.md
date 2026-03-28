# ADR-122: Feature Branch Isolation Protocol — Preventing Master Branch Contamination

**Date:** 2026-03-28 | **Status:** ACCEPTED
**Triggered by:** Merge conflict during `feature/v0.38.0-governance` → `master` caused by untracked in-flight changes on master that were not committed to a branch.

---

## Context

During the `feature/v0.38.0-governance` merge, `git checkout master` was blocked by uncommitted changes to `graqle/cli/main.py`, `graqle/plugins/mcp_dev_server.py`, and `.graqle/gov_cumulative.json`. These changes had accumulated on master while work was in progress on the feature branch. The stash pop caused 3-way merge conflicts on the same files being changed by the feature branch. This required a non-trivial cleanup sequence (stash drop → restore HEAD → commit orphan changes → then merge), and **the merge to production happened without explicit user approval** because the cleanup steps blurred the boundary between "prepare to merge" and "actually merge".

**Root Causes (5 Whys):**

1. **Why did the conflict happen?**
   Files on `master` were modified directly without being committed to a branch.

2. **Why were they modified directly on master?**
   Small fixes (privacy pattern, CLI tweaks, licensing) were made between feature sessions without switching to a branch, because they felt "too small to branch."

3. **Why did small changes land unbrached on master?**
   No protocol enforced "master is read-only between releases." Commits to master outside of release merges were implicitly allowed.

4. **Why was this not caught before the merge?**
   The merge process didn't include a pre-merge step to verify `git status` on master was clean (zero uncommitted changes, zero ahead of origin).

5. **Why did the merge happen without user approval?**
   The cleanup steps required to resolve the conflict (stash drop, commit orphan changes) were low-stakes individually. Each step felt like "preparation." There was no hard stop requiring explicit confirmation before `git merge` was executed.

---

## Decision

**Establish and enforce the Feature Branch Isolation Protocol (FBIP) for all Graqle SDK work.**

### Rules

| Rule | Enforcement |
|------|-------------|
| **master is read-only between releases** | No direct commits to master except: (a) merge commits from feature branches, (b) version bump commit immediately before tag, (c) emergency hotfix via `hotfix-*` branch |
| **Pre-merge master health check** | Before any `git merge feature-X`, run: `git checkout master && git status` — must show `nothing to commit, working tree clean`. If not clean: STOP, commit/branch the orphan changes first, get user approval |
| **Merge requires explicit user approval** | Merging into master + pushing to GitHub is a release action. It requires the user to say "merge now" or equivalent. Not implied by "next steps" in a summary |
| **Tag = publish trigger** | `git tag vX.Y.Z && git push origin vX.Y.Z` triggers PyPI publish via CI. Never do this without explicit "publish to PyPI" approval |
| **Stash is a danger signal** | If `git stash` is needed during a merge workflow, STOP and surface to user. Stash → checkout → pop is a conflict-prone sequence that must not be done silently |
| **Feature branches are forward-only** | Never cherry-pick from master back to a feature branch mid-sprint. Merge conflicts during the final merge are the cost of long-lived branches; minimize by keeping feature branches short (< 2 weeks) |

### Pre-Merge Checklist (mandatory before any merge to master)

```
□ 1. git checkout master
□ 2. git status → must show "nothing to commit, working tree clean"
□ 3. git log origin/master..master → must show 0 commits (master not ahead of remote)
□ 4. Confirm with user: "Ready to merge feature/X into master?"
□ 5. Wait for explicit "yes, merge" response
□ 6. git merge feature/X --no-ff
□ 7. git push origin master
□ 8. Separately confirm: "Tag v{N} and trigger PyPI publish?"
□ 9. Wait for explicit "yes, publish"
□ 10. git tag vX.Y.Z && git push origin vX.Y.Z
```

Steps 4–5 and 8–9 are blocking confirmation gates. They cannot be skipped even when the summary says "next step is merge."

---

## Consequences

**Positive:**
- No surprise merges or publishes
- Master stays clean — every commit on master is either a merge commit or a release bump
- Conflicts caught early (pre-merge health check) rather than during the merge
- User retains full control over when production changes happen

**Negative:**
- Slightly slower release process (two explicit confirmations)
- Small fixes made mid-feature must be placed on a `hotfix-*` or `chore-*` branch rather than committed directly to master

**Trade-off accepted:** The cost of one extra confirmation is negligible compared to the risk of an unintended publish, merge conflict, or broken PyPI version.

---

## Application

This ADR applies to:
- `graqle-sdk` (quantamixsol/graqle)
- `graqle-studio` (quantamixsol/cognigraph-studio)
- Any future Graqle product repo

It does NOT apply to hotfixes that the user explicitly says to "push directly to master."
