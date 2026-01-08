# PHASE 3.5: CHAT MIGRATION TO ADMIN-API

**Date:** 2026-01-07  
**Status:** PLANNING  
**Goal:** Move /api/chat endpoint from lobechat-adapter to admin-api  
**Reason:** Complete separation - WebUI should only use admin-api  
**Time Estimate:** 45 minutes  

---

## 🎯 PROBLEM ANALYSIS

### Current Broken State:
```
jarvis-webui (8400)
├── JavaScript: API_BASE = "http://localhost:8200"
├── Persona calls: /api/personas/* → 8200 (admin-api) ✅ Works
└── Chat calls: /api/chat → 8200 (admin-api) ❌ 404 Not Found

admin-api (8200)
├── Has: /api/personas/*
└── Missing: /api/chat ← Problem!

lobechat-adapter (8100)
└── Has: /api/chat (unused by WebUI now)
```

### Why It Broke:
```
Step 1: We changed ALL API calls to port 8200
Step 2: But admin-api doesn't have /api/chat endpoint
Step 3: Chat requests fail with 404
Step 4: No connection to Ollama
```

---

## ✅ TARGET ARCHITECTURE

### After Migration:
```
jarvis-webui (8400)
├── JavaScript: API_BASE = "http://localhost:8200"
├── Persona calls: /api/personas/* → admin-api ✅
└── Chat calls: /api/chat → admin-api ✅

admin-api (8200)
├── /api/personas/* (Persona Management)
├── /api/chat (Chat Functionality) ← NEW!
├── /api/maintenance/* (Maintenance)
└── /health

lobechat-adapter (8100)
├── /api/chat (OpenAI-compatible for LobeChat)
└── ONLY for LobeChat client
```

### Clear Separation:
```
LobeChat Client     → lobechat-adapter (8100)
Jarvis WebUI        → admin-api (8200)
No mixing!
```

---

## 🔧 IMPLEMENTATION PLAN

### Step 1: Understand Current Chat Implementation (10min)

**Files to Check:**
```
/adapters/lobechat/main.py
  └── Find /api/chat endpoint implementation
  
/adapters/Jarvis/static/js/api.js
  └── Understand chat request format
  
/core/bridge.py
  └── Understand CoreBridge interface
```

**Questions to Answer:**
- What does /api/chat endpoint do?
- Does it use CoreBridge?
- What's the request/response format?
- Any dependencies we need to copy?

---

### Step 2: Create Chat Route in admin-api (20min)

**File:** `/adapters/admin-api/main.py`

**What to Add:**
```python
# After persona_router include:

# Chat endpoint for Jarvis WebUI
@app.post("/api/chat")
async def chat_endpoint(request: Request):
    """
    Chat endpoint for Jarvis WebUI
    
    Accepts custom Jarvis format:
    {
        "query": "Hello",
        "conversation_id": "user_1",
        "stream": true
    }
    
    Returns:
    {
        "response": "Hi there!",
        "done": true,
        "metadata": {...}
    }
    """
    # TODO: Implementation
    pass
```

**Options:**

**Option 2A: Copy Logic from lobechat-adapter** (Simple)
```python
# Copy the chat handling code from lobechat/main.py
# Pros: Quick, known to work
# Cons: Code duplication
```

**Option 2B: Import from lobechat adapter** (Clean but complex)
```python
# Import chat handler from lobechat
from adapters.lobechat.main import handle_chat
# Pros: No duplication
# Cons: Dependency on lobechat adapter
```

**Option 2C: Use CoreBridge directly** (Cleanest)
```python
from core.bridge import get_bridge
from core.models import CoreChatRequest

# Pros: Direct, no dependency on adapters
# Cons: Need to understand CoreBridge interface
```

**RECOMMENDED: Option 2C** - Use CoreBridge directly
- Clean separation
- No adapter dependencies
- Future-proof

---

### Step 3: Add Required Dependencies (5min)

**Check what admin-api needs:**
```python
# In /adapters/admin-api/main.py:
from core.bridge import get_bridge  # May need to add
from core.models import CoreChatRequest, Message  # May need
```

**Update Dockerfile if needed:**
```dockerfile
# Already copies /core, should be fine
COPY core /app/core
```

---

### Step 4: Test Chat Endpoint (5min)

**Manual Test:**
```bash
curl -X POST http://localhost:8200/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test",
    "conversation_id": "test_1",
    "stream": false
  }'
```

**Expected Response:**
```json
{
  "response": "...",
  "done": true,
  "metadata": {...}
}
```

---

### Step 5: Verify WebUI Chat Works (5min)

**Browser Test:**
1. Open http://192.168.0.226:8400
2. Type message in chat
3. Verify response appears
4. Check browser console for errors
5. Verify no 404 errors

**Check admin-api logs:**
```bash
sudo docker logs jarvis-admin-api -f
# Should see: POST /api/chat - 200 OK
```

---

## 🔍 INVESTIGATION NEEDED

Before implementing, we need to check:

### 1. Current /api/chat in lobechat-adapter:
```bash
# Find the endpoint implementation
grep -A 50 "@app.post.*chat" /DATA/.../adapters/lobechat/main.py
```

**Questions:**
- Does it use CoreBridge?
- What's the exact request format?
- What response format does WebUI expect?
- Any special headers or handling?

### 2. WebUI Chat Request Format:
```bash
# Check api.js
cat /DATA/.../adapters/Jarvis/static/js/api.js
# Find the chat function
```

**Questions:**
- What JSON structure does it send?
- Stream vs non-stream handling?
- Error handling expectations?

### 3. CoreBridge Interface:
```bash
# Check bridge.py
cat /DATA/.../core/bridge.py | grep -A 20 "def process"
```

**Questions:**
- What's the input format?
- How to get bridge instance?
- Stream support?

---

## ⚠️ RISKS & MITIGATION

### Risk 1: Chat Format Mismatch
```
Problem: WebUI expects specific JSON format
Mitigation: Copy exact format from lobechat-adapter
Rollback: Easy - just revert API_BASE to 8100
```

### Risk 2: CoreBridge Initialization
```
Problem: admin-api might not have CoreBridge configured
Mitigation: Check config.py, add if missing
Rollback: Revert changes to main.py
```

### Risk 3: Streaming Support
```
Problem: WebUI might use streaming chat
Mitigation: Implement both stream and non-stream
Rollback: Revert to lobechat-adapter
```

### Risk 4: Missing Dependencies
```
Problem: admin-api missing required imports
Mitigation: Update requirements.txt, rebuild
Rollback: Use old container image
```

---

## 🔄 ROLLBACK PLAN

If migration fails:

**Step 1: Revert JavaScript (2min)**
```bash
# Restore backup
cp /DATA/.../adapters/Jarvis/static/js/api.js.backup \
   /DATA/.../adapters/Jarvis/static/js/api.js

# Change API_BASE back to 8100
sed -i 's/8200/8100/g' .../static/js/*.js
```

**Step 2: Rebuild WebUI (3min)**
```bash
docker compose build jarvis-webui
docker compose up -d jarvis-webui
```

**Step 3: Verify (1min)**
```bash
curl http://localhost:8400
# Chat should work again
```

**Total Rollback Time:** 6 minutes

---

## 📊 TIME BREAKDOWN

```
Step 1: Investigation           10 min
Step 2: Implementation          20 min
Step 3: Dependencies            5 min
Step 4: Testing                 5 min
Step 5: Verification            5 min
─────────────────────────────────────
Total:                          45 min

If problems occur:
+ Debugging:                    15 min
+ Rollback:                     6 min
─────────────────────────────────────
Worst case total:               66 min (~1h)
```

---

## ✅ SUCCESS CRITERIA

Migration complete when:
- [ ] admin-api has /api/chat endpoint
- [ ] WebUI chat sends to port 8200
- [ ] Chat responses appear in WebUI
- [ ] No 404 errors in browser console
- [ ] admin-api logs show successful requests
- [ ] Ollama connection working
- [ ] All tests pass

---

## 📝 DOCUMENTATION TODO

After completion:
- [ ] Update REFACTORING_PROGRESS.md
- [ ] Update admin-api README
- [ ] Document /api/chat endpoint
- [ ] Update architecture diagrams
- [ ] Add to Phase 3.5 complete

---

## 🚀 NEXT STEPS

### Before Starting:
1. **Review this plan** ✅ (Danny reviewing now)
2. **Get approval** ⏳ (Waiting for Danny)
3. **Create backup points** ⏳
4. **Document current state** ⏳

### Then Execute:
1. Investigation (10min)
2. Implementation (20min)
3. Testing (10min)
4. Documentation (5min)

---

## 💡 ALTERNATIVE: QUICK FIX (Option A)

If we decide Option B is too much work right now:

**Quick Fix (15min):**
```javascript
// In api.js:
const ADMIN_API = "http://localhost:8200";  // Personas
const CHAT_API = "http://localhost:8100";   // Chat

// Use ADMIN_API for personas
// Use CHAT_API for chat
```

**Pros:** Fast, works immediately  
**Cons:** Mixed architecture, tech debt

---

## 🎯 RECOMMENDATION

**Proceed with Option B** because:
1. We've already invested 2+ hours in clean separation
2. 45min more is worth it for clean architecture
3. No tech debt
4. Future-proof solution
5. Matches our refactoring goal

**BUT:** Do investigation first (Step 1) to verify feasibility!

---

**Status:** AWAITING APPROVAL  
**Next:** Danny reviews → Approve → Start investigation  
**Created:** 2026-01-07 08:30  
**Estimated Start:** After approval (~5min)
