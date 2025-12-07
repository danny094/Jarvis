#!/bin/bash
# run_tests.sh - Einfaches Test-Script

set -e

echo "🧪 Jarvis Test Suite"
echo "===================="

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest nicht gefunden!"
    echo "   → pip install -r requirements-dev.txt"
    exit 1
fi

# Parse arguments
COVERAGE=false
VERBOSE=false
FILTER=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --cov|--coverage)
            COVERAGE=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -k)
            FILTER="-k $2"
            shift 2
            ;;
        *)
            FILTER="$1"
            shift
            ;;
    esac
done

# Build pytest command
CMD="pytest"

if [ "$VERBOSE" = true ]; then
    CMD="$CMD -vv"
fi

if [ "$COVERAGE" = true ]; then
    CMD="$CMD --cov=. --cov-report=term-missing --cov-report=html"
fi

if [ -n "$FILTER" ]; then
    CMD="$CMD $FILTER"
fi

echo "Running: $CMD"
echo ""

$CMD

echo ""
echo "✅ Tests abgeschlossen!"

if [ "$COVERAGE" = true ]; then
    echo "📊 Coverage-Report: htmlcov/index.html"
fi
