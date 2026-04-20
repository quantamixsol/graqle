#!/bin/bash
# GraQle Release Gate — GitHub Action entrypoint.
# Composes the diff from the event context and invokes `graq release-gate`.
set -euo pipefail

# Parse flags passed by action.yml
TARGET=""
GITHUB_TOKEN_INPUT=""
GRAQLE_LICENSE=""
MIN_CONFIDENCE=""
STRICT="false"
DIFF_BASE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)            TARGET="$2"; shift 2 ;;
    --github-token)      GITHUB_TOKEN_INPUT="$2"; shift 2 ;;
    --graqle-license)    GRAQLE_LICENSE="$2"; shift 2 ;;
    --min-confidence)    MIN_CONFIDENCE="$2"; shift 2 ;;
    --strict)            STRICT="$2"; shift 2 ;;
    --diff-base)         DIFF_BASE="$2"; shift 2 ;;
    *)                   shift ;;
  esac
done

# Validate target
if [[ "$TARGET" != "pypi" && "$TARGET" != "vscode-marketplace" ]]; then
  echo "ERROR: --target must be 'pypi' or 'vscode-marketplace' (got '$TARGET')" >&2
  exit 1
fi

# Authenticate gh CLI if token provided (for PR comments)
if [[ -n "$GITHUB_TOKEN_INPUT" ]]; then
  export GITHUB_TOKEN="$GITHUB_TOKEN_INPUT"
fi

# Wire GraQle license if provided
if [[ -n "$GRAQLE_LICENSE" ]]; then
  export GRAQLE_LICENSE_KEY="$GRAQLE_LICENSE"
fi

# Compute diff based on event context
EVENT_NAME="${GITHUB_EVENT_NAME:-}"
BASE_REF=""
HEAD_REF="HEAD"

if [[ -n "$DIFF_BASE" ]]; then
  BASE_REF="$DIFF_BASE"
elif [[ "$EVENT_NAME" == "pull_request" ]]; then
  BASE_REF="${GITHUB_BASE_REF:-main}"
  git fetch origin "$BASE_REF" --depth=50 || true
  BASE_REF="origin/$BASE_REF"
elif [[ "$EVENT_NAME" == "release" ]]; then
  # Diff against the previous tag
  BASE_REF="$(git describe --tags --abbrev=0 "HEAD^" 2>/dev/null || echo '')"
  if [[ -z "$BASE_REF" ]]; then
    echo "WARNING: no previous tag found; diffing against empty tree" >&2
    BASE_REF="$(git hash-object -t tree /dev/null)"
  fi
else
  # Fallback: diff last commit
  BASE_REF="HEAD~1"
fi

DIFF_TEXT="$(git diff "$BASE_REF...$HEAD_REF" 2>/dev/null || echo '')"

if [[ -z "$DIFF_TEXT" ]]; then
  echo "No diff found between $BASE_REF and $HEAD_REF — exiting CLEAR."
  {
    echo "verdict=CLEAR"
    echo "risk-score=0.0"
    echo "confidence=1.0"
    echo "target=$TARGET"
    echo 'blockers=[]'
    echo 'majors=[]'
  } >> "${GITHUB_OUTPUT:-/dev/stdout}"
  exit 0
fi

# Build CLI args
CLI_ARGS=("--target" "$TARGET" "--diff" "-" "--json")
if [[ -n "$MIN_CONFIDENCE" ]]; then
  CLI_ARGS+=("--min-confidence" "$MIN_CONFIDENCE")
fi
if [[ "$STRICT" == "true" ]]; then
  CLI_ARGS+=("--strict")
fi

# Run the gate — stdin = diff, stdout = JSON
VERDICT_JSON="$(echo "$DIFF_TEXT" | graq release-gate "${CLI_ARGS[@]}" 2>/dev/null || true)"

if [[ -z "$VERDICT_JSON" ]]; then
  # CLI didn't return JSON (could be BLOCK exit 1; verdict info still desired)
  # Re-run without exit-on-block to capture output
  VERDICT_JSON="$(echo "$DIFF_TEXT" | graq release-gate --target "$TARGET" --diff - --json || echo '{"verdict":"WARN","target":"'"$TARGET"'","blockers":[],"majors":[],"risk_score":0.5,"confidence":0.0,"review_summary":"gate cli error","prediction_reasons":["cli_error"]}')"
fi

# Extract fields for GITHUB_OUTPUT
VERDICT=$(echo "$VERDICT_JSON" | jq -r '.verdict // "WARN"')
RISK=$(echo "$VERDICT_JSON" | jq -r '.risk_score // 0.5')
CONF=$(echo "$VERDICT_JSON" | jq -r '.confidence // 0.0')
BLOCKERS=$(echo "$VERDICT_JSON" | jq -c '.blockers // []')
MAJORS=$(echo "$VERDICT_JSON" | jq -c '.majors // []')

{
  echo "verdict=$VERDICT"
  echo "risk-score=$RISK"
  echo "confidence=$CONF"
  echo "target=$TARGET"
  echo "blockers=$BLOCKERS"
  echo "majors=$MAJORS"
} >> "${GITHUB_OUTPUT:-/dev/stdout}"

# Post PR comment if this is a pull_request event
PR_NUMBER="${GITHUB_EVENT_NUMBER:-}"
REPO="${GITHUB_REPOSITORY:-}"
if [[ "$EVENT_NAME" == "pull_request" && -n "$PR_NUMBER" && -n "$REPO" ]]; then
  EMOJI="⚠️"
  [[ "$VERDICT" == "CLEAR" ]] && EMOJI="✅"
  [[ "$VERDICT" == "BLOCK" ]] && EMOJI="⛔"
  COMMENT_BODY="## $EMOJI GraQle Release Gate — **$VERDICT**\nTarget: \`$TARGET\`\n\n"
  BLOCKER_LINES=$(echo "$VERDICT_JSON" | jq -r '.blockers[]? // empty | "- 🛑 **BLOCKER:** \(. )"')
  MAJOR_LINES=$(echo "$VERDICT_JSON" | jq -r '.majors[]? // empty | "- ⚠️ **MAJOR:** \(. )"')
  COMMENT_BODY="${COMMENT_BODY}${BLOCKER_LINES}\n${MAJOR_LINES}"
  echo -e "$COMMENT_BODY" | gh pr comment "$PR_NUMBER" --repo "$REPO" --body-file - || true
fi

# Exit code
case "$VERDICT" in
  BLOCK) exit 1 ;;
  WARN)  [[ "$STRICT" == "true" ]] && exit 2 || exit 0 ;;
  *)     exit 0 ;;
esac
