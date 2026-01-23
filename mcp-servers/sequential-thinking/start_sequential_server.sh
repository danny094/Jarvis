#!/bin/bash
# Sequential Thinking MCP Server - Start Script

set -e

echo "🚀 Starting Sequential Thinking MCP Server"

# Go to server directory
cd /DATA/AppData/MCP/Jarvis/Jarvis/mcp-servers/sequential-thinking

# Kill old processes
echo "Stopping old server..."
pkill -f "uvicorn sequential_mcp" 2>/dev/null || true
sleep 2

# Clean cache
echo "Cleaning cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Set PYTHONPATH
export PYTHONPATH=/DATA/AppData/MCP/Jarvis/Jarvis:/DATA/AppData/MCP/Jarvis/Jarvis/mcp-servers/sequential-thinking
export PYTHONDONTWRITEBYTECODE=1

# Start server
echo "Starting server on port 8001..."
python3 -m uvicorn sequential_mcp.server:app \
  --host 0.0.0.0 \
  --port 8001 \
  --log-level info \
  </dev/null >/tmp/sequential_mcp.log 2>&1 &

SERVER_PID=$!
echo "Server PID: $SERVER_PID"

# Wait for startup
sleep 5

# Check if running
if ps -p $SERVER_PID > /dev/null 2>&1; then
    echo "✅ Server is running!"
    echo ""
    echo "Health check:"
    curl -s http://localhost:8001/ | python3 -m json.tool 2>/dev/null || echo "Waiting for server..."
    echo ""
    echo "Logs: /tmp/sequential_mcp.log"
    echo "Stop: pkill -f 'uvicorn sequential_mcp'"
else
    echo "❌ Server failed to start"
    echo "Log:"
    cat /tmp/sequential_mcp.log
    exit 1
fi
