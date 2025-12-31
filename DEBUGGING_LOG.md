# Debugging Log

Chronological log of debugging sessions, issues, and their resolutions.

---

## 2025-12-31: WebUI + Maintenance Fixes

### Summary
- **Duration**: ~2 hours  
- **Files Changed**: app.js, tools.py, documentation
- **Status**: ✅ WebUI Fixed, ⚠️ Maintenance Partial

### Problem 1: WebUI Won't Load
**Root Cause**: Initialization order bug - settings loaded before API ready  
**Solution**: Reordered initApp() - API first, then settings  
**Result**: ✅ WebUI fully functional

### Problem 2: Maintenance Reports 0 Entries
**Root Cause**: Missing MCP tool memory_list_conversations  
**Solution**: Implemented tool in tools.py  
**Result**: ⚠️ Partial - finds data but merging incomplete

### Key Learnings
1. Documentation-driven debugging = 20min vs hours
2. Initialization order is critical
3. Missing MCP tools fail silently
4. Container restart needs stop→start for Python reload

### Files Modified
- /adapters/Jarvis/static/js/app.js
- /sql-memory/memory_mcp/tools.py  
- /assistant-proxy/DEBUGGING_LOG.md

See maintenance/README.md for detailed troubleshooting.
