# MCP SERVER STARTUP FIX

**Date:** 2026-01-17  
**Issue:** ModuleNotFoundError when starting Sequential Thinking MCP Server  
**Status:** ✅ FIXED

---

## 🐛 PROBLEM

MCP Server failed to start with error:
```
ModuleNotFoundError: No module named 'modules'
ModuleNotFoundError: No module named 'sequential_mcp'
```

## 🔍 ROOT CAUSE

Python couldn't find:
- `/DATA/AppData/MCP/Jarvis/Jarvis/modules/` (for sequential_thinking.engine)
- `/DATA/AppData/MCP/Jarvis/Jarvis/mcp-servers/sequential-thinking/` (for sequential_mcp package)

## ✅ SOLUTION

Created startup script with correct PYTHONPATH:

**File:** `/DATA/AppData/MCP/Jarvis/Jarvis/mcp-servers/sequential-thinking/start_mcp_server.sh`

```bash
#!/bin/bash
# Start MCP Sequential Thinking Server

PROJECT_ROOT="/DATA/AppData/MCP/Jarvis/Jarvis"
MCP_DIR="$PROJECT_ROOT/mcp-servers/sequential-thinking"

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT:$MCP_DIR:$PYTHONPATH"

pkill -f "sequential_mcp.server" 2>/dev/null
sleep 1

cd "$MCP_DIR"
python3 -m sequential_mcp.server
```

## 🚀 USAGE

**Start Server:**
```bash
cd /DATA/AppData/MCP/Jarvis/Jarvis/mcp-servers/sequential-thinking
nohup ./start_mcp_server.sh > /tmp/mcp_server.log 2>&1 &
```

**Check Status:**
```bash
curl http://localhost:8001/
# Should return: {"name":"sequential-thinking","version":"1.0.0","status":"healthy"}
```

**View Logs:**
```bash
tail -f /tmp/mcp_server.log
```

## 📝 NOTES

- Script must be executable: `chmod +x start_mcp_server.sh`
- Kills old instances automatically
- Sets PYTHONPATH for both project root and MCP directory
- Logs to /tmp/mcp_server.log when run with nohup

---

**Fixed by:** Claude  
**Date:** 2026-01-17
