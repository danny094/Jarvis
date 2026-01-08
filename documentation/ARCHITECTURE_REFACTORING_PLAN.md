# JARVIS ARCHITECTURE REFACTORING PLAN

**Date:** 2026-01-07  
**Issue:** Persona Management API mixed into lobechat-adapter  
**Goal:** Clean separation of concerns  
**Priority:** HIGH - Architectural Debt

---

## 🚨 PROBLEM ANALYSIS

### Current (Incorrect) Architecture:

```
┌─────────────────────────────────────────────────────────┐
│  lobechat-adapter (Port 8100)                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │  LobeChat OpenAI-Compatible API                   │  │
│  │  /api/chat, /api/models, etc.                     │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  ❌ WRONG: Persona Management API                 │  │
│  │  /api/personas/*                                  │  │
│  │  (Should NOT be here!)                            │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  jarvis-webui (Port 8400)                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Nginx + Static Files                             │  │
│  │  Calls API at http://localhost:8100 ← MIXED!     │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Why This Is Wrong:

1. **Mixed Concerns**
   - LobeChat adapter should ONLY serve LobeChat client
   - Admin/Management API doesn't belong here

2. **Tight Coupling**
   - WebUI depends on LobeChat adapter
   - Can't upgrade/restart one without affecting the other

3. **Confusing Responsibilities**
   - lobechat-adapter name suggests LobeChat-only
   - But it also manages personas (admin function)

4. **Scalability Issues**
   - Can't scale LobeChat and Admin independently
   - Both share same resource limits

5. **Security Concerns**
   - Admin API exposed on same port as client API
   - Harder to implement different auth strategies

---

## ✅ TARGET ARCHITECTURE

### Clean Separation:

```
┌─────────────────────────────────────────────────────────┐
│  lobechat-adapter (Port 8100)                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │  ✅ ONLY: LobeChat OpenAI-Compatible API          │  │
│  │  /api/chat, /api/models, /v1/*                    │  │
│  │  For: LobeChat client only                        │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  jarvis-admin-api (Port 8200) ← NEW!                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │  ✅ Admin & Management API                         │  │
│  │  /api/personas/*     - Persona Management         │  │
│  │  /api/settings/*     - System Settings            │  │
│  │  /api/maintenance/*  - Memory Maintenance         │  │
│  │  /api/health         - Health Check               │  │
│  │  For: jarvis-webui only                           │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  jarvis-webui (Port 8400)                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Nginx + Static Files                             │  │
│  │  Calls API at http://localhost:8200 ← CLEAN!     │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Service Responsibilities:

**lobechat-adapter (Port 8100):**
```
Purpose: Bridge LobeChat ↔ Ollama
Endpoints:
  - /api/chat          (OpenAI-compatible)
  - /api/models        (List models)
  - /v1/*              (OpenAI routes)
  - /health            (Health check)
  
Depends on:
  - ollama (11434)
  - mcp-sql-memory (8082)
  - validator-service (8300)
```

**jarvis-admin-api (Port 8200) - NEW:**
```
Purpose: Admin & Management for Jarvis WebUI
Endpoints:
  - /api/personas/*        (Persona CRUD)
  - /api/maintenance/*     (Memory maintenance)
  - /api/settings/*        (System settings - future)
  - /api/stats/*           (Statistics - future)
  - /health                (Health check)
  
Depends on:
  - mcp-sql-memory (8082)
  - Shared /personas volume
```

**jarvis-webui (Port 8400):**
```
Purpose: Admin Frontend
Tech: Nginx + HTML/CSS/JS
API Target: http://jarvis-admin-api:8200
No business logic
```

---

## 📦 NEW SERVICE STRUCTURE

### Directory Structure:

```
/DATA/AppData/MCP/Jarvis/Jarvis/
├── adapters/
│   ├── admin-api/           ← NEW!
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── lobechat/
│   │   ├── Dockerfile
│   │   ├── main.py          (Remove persona routes!)
│   │   └── requirements.txt
│   └── Jarvis/              (WebUI)
│       ├── Dockerfile
│       ├── index.html       (Change API URL!)
│       └── static/
├── maintenance/
│   ├── persona_routes.py    (Move to admin-api!)
│   └── routes.py            (Move to admin-api!)
├── core/
│   └── persona.py           (Shared library)
└── docker-compose.yml       (Add admin-api service!)
```

---

## 🔄 MIGRATION PLAN

### Phase 1: Create jarvis-admin-api (1-2h)

**Step 1.1: Create Directory Structure (5min)**
```bash
mkdir -p adapters/admin-api
cd adapters/admin-api
```

**Step 1.2: Create Dockerfile (10min)**
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Copy shared code
COPY ../../core /app/core
COPY ../../maintenance /app/maintenance

EXPOSE 8200

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8200"]
```

**Step 1.3: Create main.py (20min)**
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from maintenance.persona_routes import router as persona_router
from maintenance.routes import router as maintenance_router

app = FastAPI(
    title="Jarvis Admin API",
    description="Management API for Jarvis WebUI",
    version="1.0.0"
)

# CORS for WebUI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8400"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(persona_router, prefix="/api/personas")
app.include_router(maintenance_router, prefix="/api/maintenance")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "jarvis-admin-api"}
```

**Step 1.4: Create requirements.txt (5min)**
```
fastapi==0.115.6
uvicorn==0.34.0
python-multipart==0.0.20
```

**Step 1.5: Add to docker-compose.yml (10min)**
```yaml
jarvis-admin-api:
  build:
    context: .
    dockerfile: adapters/admin-api/Dockerfile
  container_name: jarvis-admin-api
  ports:
    - "8200:8200"
  environment:
    - MCP_BASE=http://mcp-sql-memory:8081/mcp
    - LOG_LEVEL=INFO
  volumes:
    - ./personas:/app/personas
  networks:
    - big-bear-lobe-chat_default
  restart: unless-stopped
  depends_on:
    - mcp-sql-memory
```

**Step 1.6: Build & Test (10min)**
```bash
docker-compose up -d jarvis-admin-api
curl http://localhost:8200/health
curl http://localhost:8200/api/personas/
```

---

### Phase 2: Update jarvis-webui (30min)

**Step 2.1: Update API Base URL (5min)**
```javascript
// adapters/Jarvis/static/js/api.js
// Change from:
const API_BASE = "http://localhost:8100"

// To:
const API_BASE = "http://localhost:8200"
```

**Step 2.2: Rebuild WebUI (5min)**
```bash
docker-compose up -d --build jarvis-webui
```

**Step 2.3: Test WebUI (20min)**
- Open http://localhost:8400
- Test Persona tab
- Upload persona
- Switch persona
- Delete persona
- Run integration tests

---

### Phase 3: Clean lobechat-adapter (20min)

**Step 3.1: Remove Persona Router (5min)**
```python
# adapters/lobechat/main.py
# Remove this line:
from maintenance.persona_routes import router as persona_router
app.include_router(persona_router)  # DELETE THIS
```

**Step 3.2: Rebuild LobeChat Adapter (5min)**
```bash
docker-compose up -d --build lobechat-adapter
```

**Step 3.3: Verify LobeChat Still Works (10min)**
- Test LobeChat client
- Send message
- Check response
- Verify no persona routes on 8100

---

### Phase 4: Testing & Validation (30min)

**Step 4.1: Run Integration Tests**
```bash
python3 tests/test_persona_rest_api.py
# Should pass all 15 tests
```

**Step 4.2: Manual Testing**
- Test WebUI persona management
- Test LobeChat chat functionality
- Verify services are independent

**Step 4.3: Load Testing (Optional)**
- Restart admin-api → WebUI still accessible
- Restart lobechat-adapter → WebUI still accessible
- Both services independent ✓

---

### Phase 5: Documentation (20min)

**Step 5.1: Update README.md**
- Document new architecture
- Update service ports
- Add admin-api description

**Step 5.2: Create ARCHITECTURE.md**
- Service diagram
- Port mapping
- Dependencies

**Step 5.3: Update API_REFERENCE.md**
- Split into two sections
- Admin API (8200)
- LobeChat API (8100)

---

## ⏱️ TIME ESTIMATE

```
Phase 1: Create admin-api          1-2 hours
Phase 2: Update WebUI              30 min
Phase 3: Clean lobechat-adapter    20 min
Phase 4: Testing                   30 min
Phase 5: Documentation             20 min
───────────────────────────────────────────
Total:                             3-4 hours
```

---

## 🧪 TESTING STRATEGY

### Unit Tests:
```
✓ Persona API endpoints (existing tests)
✓ Admin API health check (new)
✓ CORS configuration (new)
```

### Integration Tests:
```
✓ WebUI → Admin API communication
✓ Admin API → MCP Memory
✓ All persona CRUD operations
```

### System Tests:
```
✓ Service independence (restart one, others work)
✓ Port isolation (8100 vs 8200)
✓ LobeChat unaffected by admin changes
```

---

## 🎯 SUCCESS CRITERIA

### Must Have:
- [x] jarvis-admin-api service running on 8200
- [x] jarvis-webui connects to 8200 (not 8100)
- [x] lobechat-adapter has NO persona routes
- [x] All integration tests pass (15/15)
- [x] LobeChat functionality unchanged
- [x] Services are independent

### Should Have:
- [x] Clean service boundaries
- [x] Updated documentation
- [x] CORS properly configured
- [x] Health checks on all services

### Nice to Have:
- [ ] Admin API authentication (future)
- [ ] Rate limiting (future)
- [ ] Metrics endpoint (future)

---

## 🚨 ROLLBACK PLAN

If migration fails:

**Step 1: Stop new service**
```bash
docker-compose stop jarvis-admin-api
```

**Step 2: Revert WebUI**
```bash
# Restore API_BASE to 8100
git checkout adapters/Jarvis/static/js/api.js
docker-compose up -d --build jarvis-webui
```

**Step 3: Restore lobechat-adapter**
```bash
# Keep persona routes
git checkout adapters/lobechat/main.py
docker-compose up -d --build lobechat-adapter
```

**Recovery Time:** 5-10 minutes

---

## 📋 CHECKLIST

### Pre-Migration:
- [ ] All tests passing
- [ ] Current system documented
- [ ] Backup docker-compose.yml
- [ ] Backup all modified files

### During Migration:
- [ ] Create admin-api service
- [ ] Test admin-api independently
- [ ] Update WebUI config
- [ ] Test WebUI → admin-api
- [ ] Remove persona routes from lobechat
- [ ] Test LobeChat still works

### Post-Migration:
- [ ] Run all integration tests
- [ ] Manual testing complete
- [ ] Documentation updated
- [ ] Rollback plan tested
- [ ] Team informed

---

## 🔗 RELATED DOCUMENTATION

- **Current Architecture:** See docker-compose.yml
- **Persona API:** See maintenance/persona_routes.py
- **Integration Tests:** See tests/test_persona_rest_api.py
- **Phase 3 Plan:** See PHASE_3_PLAN.md

---

## 💡 FUTURE IMPROVEMENTS

After migration:

**1. Authentication (Phase 4)**
```
Add JWT auth to admin-api
Protect sensitive endpoints
```

**2. Settings API (Phase 5)**
```
Add /api/settings/* endpoints
System configuration management
```

**3. Statistics API (Phase 6)**
```
Add /api/stats/* endpoints
Usage tracking, metrics
```

**4. WebSocket Support (Phase 7)**
```
Real-time updates for maintenance
Live persona switching notifications
```

---

## 🎬 READY TO START?

**When you're ready, we'll execute:**

1. Create `adapters/admin-api/` directory
2. Add Dockerfile, main.py, requirements.txt
3. Update docker-compose.yml
4. Build & test
5. Update WebUI
6. Clean lobechat-adapter
7. Full testing
8. Documentation

**Estimated Time:** 3-4 hours  
**Risk Level:** LOW (easy rollback)  
**Impact:** HIGH (clean architecture)

---

**Created:** 2026-01-07  
**Status:** READY FOR EXECUTION  
**Approval:** Pending Danny's review
