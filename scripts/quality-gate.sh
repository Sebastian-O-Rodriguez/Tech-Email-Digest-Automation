#!/usr/bin/env bash
set -euo pipefail

# Quality gate runner for email-ingester
# Usage: ./scripts/quality-gate.sh [lint|format|test|syntax|all]

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Prefer project-local tools when a venv exists
if [[ -d "$REPO_ROOT/.venv/bin" ]]; then
    PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

# macOS ships python3 only; fall back if `python` is absent
if command -v python > /dev/null 2>&1; then
    PY=python
else
    PY=python3
fi

missing=()
command -v ruff > /dev/null 2>&1 || missing+=(ruff)
command -v "$PY" > /dev/null 2>&1 || missing+=(python)
"$PY" -c 'import pytest' > /dev/null 2>&1 || missing+=(pytest)

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Missing tools: ${missing[*]}" >&2
    echo "Set up a dev environment first:" >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
fi

GATE="${1:-all}"
PASS=0
FAIL=0
TOTAL=0

run_gate() {
    local name="$1"
    shift
    TOTAL=$((TOTAL + 1))
    echo -n "  $name ... "
    local output
    if output="$("$@" 2>&1)"; then
        echo "PASS"
        PASS=$((PASS + 1))
    else
        echo "FAIL"
        FAIL=$((FAIL + 1))
        sed 's/^/    /' <<< "$output"
    fi
}

echo "=== Quality Gates ==="
echo ""

case "$GATE" in
    lint)
        run_gate "ruff check" ruff check src/ tests/
        ;;
    format)
        run_gate "ruff format" ruff format --check src/ tests/
        ;;
    test)
        run_gate "pytest" "$PY" -m pytest
        ;;
    syntax)
        run_gate "py_compile" bash -c "find src/ tests/ -name '*.py' -exec $PY -m py_compile {} +"
        ;;
    all)
        run_gate "ruff check" ruff check src/ tests/
        run_gate "ruff format" ruff format --check src/ tests/
        run_gate "pytest" "$PY" -m pytest
        run_gate "py_compile" bash -c "find src/ tests/ -name '*.py' -exec $PY -m py_compile {} +"
        ;;
    *)
        echo "Usage: quality-gate.sh [lint|format|test|syntax|all]" >&2
        exit 1
        ;;
esac

echo ""
echo "=== Results: $PASS/$TOTAL passed ==="

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
