#!/bin/bash
set -euo pipefail

# ── Parse action inputs passed as args ──
GITHUB_TOKEN=""
API_KEY=""
FAIL_ON="fail"
MAX_DEPTH="3"
CUSTOM_SHACL=""
SARIF_OUTPUT="true"
BADGE_PATH=".graqle/guardian-badge.svg"

while [[ $# -gt 0 ]]; do
  case $1 in
    --github-token)  GITHUB_TOKEN="$2";  shift 2 ;;
    --api-key)       API_KEY="$2";       shift 2 ;;
    --fail-on)       FAIL_ON="$2";       shift 2 ;;
    --max-depth)     MAX_DEPTH="$2";     shift 2 ;;
    --custom-shacl)  CUSTOM_SHACL="$2";  shift 2 ;;
    --sarif-output)  SARIF_OUTPUT="$2";  shift 2 ;;
    --badge-path)    BADGE_PATH="$2";    shift 2 ;;
    *) shift ;;
  esac
done

# ── Extract PR context from GitHub event ──
PR_NUMBER=$(jq -r '.pull_request.number // empty' "$GITHUB_EVENT_PATH" 2>/dev/null || echo "")
BASE_SHA=$(jq -r '.pull_request.base.sha // empty' "$GITHUB_EVENT_PATH" 2>/dev/null || echo "")
HEAD_SHA=$(jq -r '.pull_request.head.sha // empty' "$GITHUB_EVENT_PATH" 2>/dev/null || echo "")

if [ -z "$PR_NUMBER" ]; then
  echo "::notice::Not a pull_request event — skipping PR Guardian."
  exit 0
fi

echo "::group::GraQle PR Guardian — Analyzing PR #${PR_NUMBER}"

# ── Generate diff ──
DIFF_FILE="/tmp/pr.diff"
if [ -n "$BASE_SHA" ] && [ -n "$HEAD_SHA" ]; then
  git diff "${BASE_SHA}...${HEAD_SHA}" > "$DIFF_FILE" 2>/dev/null || \
    curl -sL -H "Authorization: token ${GITHUB_TOKEN}" \
      "https://api.github.com/repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}" \
      -H "Accept: application/vnd.github.v3.diff" > "$DIFF_FILE"
else
  curl -sL -H "Authorization: token ${GITHUB_TOKEN}" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}" \
    -H "Accept: application/vnd.github.v3.diff" > "$DIFF_FILE"
fi

# ── Build CLI args ──
CLI_ARGS=(
  "pr-guardian"
  "--diff" "$DIFF_FILE"
  "--repo" "${GITHUB_REPOSITORY}"
  "--pr-number" "${PR_NUMBER}"
  "--fail-on" "${FAIL_ON}"
  "--max-depth" "${MAX_DEPTH}"
  "--output-format" "github-action"
  "--badge-path" "${BADGE_PATH}"
)

if [ -n "$API_KEY" ]; then
  CLI_ARGS+=("--api-key" "${API_KEY}")
fi

if [ -n "$CUSTOM_SHACL" ]; then
  CLI_ARGS+=("--custom-shacl" "${CUSTOM_SHACL}")
fi

if [ "$SARIF_OUTPUT" = "true" ]; then
  CLI_ARGS+=("--sarif" "/tmp/guardian.sarif")
fi

export GITHUB_TOKEN

# ── Execute PR Guardian ──
graq "${CLI_ARGS[@]}" | tee /tmp/guardian_report.json

EXIT_CODE=${PIPESTATUS[0]}

# ── Set GitHub Action outputs ──
if [ -f /tmp/guardian_report.json ]; then
  VERDICT=$(python3 -c "import json; r=json.load(open('/tmp/guardian_report.json')); print(r.get('verdict','WARN'))" 2>/dev/null || echo "WARN")
  BLAST=$(python3 -c "import json; r=json.load(open('/tmp/guardian_report.json')); print(r.get('blast_radius',0))" 2>/dev/null || echo "0")
  BREAKING=$(python3 -c "import json; r=json.load(open('/tmp/guardian_report.json')); print(r.get('breaking_count',0))" 2>/dev/null || echo "0")

  echo "verdict=${VERDICT}" >> "$GITHUB_OUTPUT"
  echo "blast-radius=${BLAST}" >> "$GITHUB_OUTPUT"
  echo "breaking-changes=${BREAKING}" >> "$GITHUB_OUTPUT"

  if [ -f /tmp/guardian.sarif ]; then
    echo "sarif-path=/tmp/guardian.sarif" >> "$GITHUB_OUTPUT"
  fi
fi

echo "::endgroup::"

exit $EXIT_CODE
