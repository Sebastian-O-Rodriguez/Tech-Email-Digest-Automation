# Agent Protocol

## Dispatch Format

Robo dispatches agents using:

```bash
claude -p "<prompt>" --agent <agent-name> --output-format json
```

Prompts are built from `.gorp/prompts/dispatch.md.tmpl` with these fields:
- `TASK_ID` — from current-sprint.md
- `TASK_TITLE` — human-readable task name
- `AGENT` — agent name
- `SPRINT` — sprint name
- `SCOPE` — files to create/modify
- `CRITERIA` — acceptance criteria

## Report Format

Every agent writes a journal entry on task completion:

**File**: `.gorp/journal/<agent>-YYYY-MM-DD.md`

**Required sections**:
- Task ID and title
- Status: `done` | `in-progress` | `blocked`
- Files modified
- Summary of work done
- Quality gate results (if applicable)
- Blockers (if any)

## Blocker Escalation

When blocked, agents must:

1. Write a journal entry with status `blocked`
2. Include:
   - What is blocked
   - Why it is blocked
   - What is needed to unblock
   - Severity: `low` (can work around) | `medium` (task delayed) | `high` (sprint at risk)

Robo reviews blockers and escalates `high` severity to CTO.

## Communication Rules

- Agents communicate only via files (journals, sprint doc, code)
- No agent modifies another agent's journal
- No agent modifies `CLAUDE.md` or `roadmap.md`
- Robo is the only agent that updates `current-sprint.md` status
