#!/usr/bin/env bash
set -euo pipefail

# Quality gate runner for email-ingester
# Usage: ./scripts/quality-gate.sh [lint|format|test|syntax|all]

GATE="${1:-all}"
PASS=0
FAIL=0
TOTAL=0

run_gate() {
    local name="$1"
    shift
    TOTAL=$((TOTAL + 1))
    echo -n "  $name ... "
    if "$@" > /dev/null 2>&1; then
        echo "PASS"
        PASS=$((PASS + 1))
    else
        echo "FAIL"
        FAIL=$((FAIL + 1))
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
        run_gate "pytest" python -m pytest
        ;;
    syntax)
        run_gate "py_compile" bash -c 'find src/ tests/ -name "*.py" -exec python -m py_compile {} +'
        ;;
    all)
        run_gate "ruff check" ruff check src/ tests/
        run_gate "ruff format" ruff format --check src/ tests/
        run_gate "pytest" python -m pytest
        run_gate "py_compile" bash -c 'find src/ tests/ -name "*.py" -exec python -m py_compile {} +'
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
