#!/bin/bash
# MCP Server Startup Script (FIX 1: Portable paths)

# FIX 1: Use environment variable with fallback
# Priority: 1) JARVIS_PROJECT_ROOT env var, 2) Calculate from script location
if [ -z "$JARVIS_PROJECT_ROOT" ]; then
    # Calculate relative to this script
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
    echo "📍 PROJECT_ROOT calculated: $PROJECT_ROOT"
else
    PROJECT_ROOT="$JARVIS_PROJECT_ROOT"
    echo "📍 PROJECT_ROOT from env: $PROJECT_ROOT"
fi

MCP_DIR="$PROJECT_ROOT/mcp-servers/sequential-thinking"

# Export for Python
export JARVIS_PROJECT_ROOT="$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT:$MCP_DIR:$PYTHONPATH"

echo "🚀 Starting Sequential MCP Server..."
echo "PROJECT_ROOT: $PROJECT_ROOT"
echo "MCP_DIR: $MCP_DIR"
echo "PYTHONPATH: $PYTHONPATH"

cd "$MCP_DIR"
python3 -m sequential_mcp.server
