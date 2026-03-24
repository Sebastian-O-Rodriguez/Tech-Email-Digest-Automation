#!/usr/bin/env bash
set -euo pipefail

# Parallel agent dispatcher for email-ingester
# Usage: ./scripts/dispatch.sh <sprint-name>

SPRINT="${1:?Usage: dispatch.sh <sprint-name>}"
SPRINT_FILE=".gorp/plans/current-sprint.md"
VALID_AGENTS="architect backend qa"
DATE=$(date +%Y-%m-%d)

if [[ ! -f "$SPRINT_FILE" ]]; then
    echo "ERROR: $SPRINT_FILE not found" >&2
    exit 1
fi

echo "=== Dispatching Sprint: $SPRINT ==="
echo "Date: $DATE"
echo ""

# Parse pending tasks from sprint file
PIDS=()
while IFS='|' read -r _ id agent task status criteria _; do
    # Trim whitespace
    id=$(echo "$id" | xargs)
    agent=$(echo "$agent" | xargs)
    task=$(echo "$task" | xargs)
    status=$(echo "$status" | xargs)
    criteria=$(echo "$criteria" | xargs)

    # Skip non-pending tasks
    [[ "$status" != "pending" ]] && continue

    # Validate agent name
    if ! echo "$VALID_AGENTS" | grep -qw "$agent"; then
        echo "WARN: Unknown agent '$agent' for task $id, skipping" >&2
        continue
    fi

    echo "Dispatching: [$id] $task -> $agent"

    # Build dispatch prompt
    PROMPT="## Task
ID: $id
Title: $task
Agent: $agent
Sprint: $SPRINT

## Context — Read These First
- \`CLAUDE.md\` — Product spec
- \`.gorp/plans/current-sprint.md\` — Sprint breakdown

## Acceptance Criteria
$criteria

## Rules
- Only modify files within scope
- Don't touch: CLAUDE.md, .gorp/plans/roadmap.md
- Write journal entry when done: .gorp/journal/${agent}-${DATE}.md
- Run quality gates before reporting done"

    # Dispatch agent in background
    claude -p "$PROMPT" --agent "$agent" --output-format json \
        > ".gorp/journal/${agent}-${id}-dispatch.json" 2>&1 &
    PIDS+=($!)

done < <(grep '|.*|.*|.*|.*pending.*|' "$SPRINT_FILE" || true)

if [[ ${#PIDS[@]} -eq 0 ]]; then
    echo "No pending tasks found."
    exit 0
fi

echo ""
echo "Waiting for ${#PIDS[@]} agent(s)..."

FAILED=0
for pid in "${PIDS[@]}"; do
    if ! wait "$pid"; then
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "=== Dispatch Complete ==="
echo "Total: ${#PIDS[@]} | Failed: $FAILED"

exit $FAILED
