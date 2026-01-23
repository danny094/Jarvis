# 🗺️ PHASE 2: CORE INTEGRATION ROADMAP

**Duration:** 13 hours total (2-3 days)  
**Status:** Ready to Start  
**Date:** 2025-01-14

---

## 📊 OVERVIEW

Phase 2 integriert Sequential Thinking (Phase 1) in das Jarvis Core System:

```
┌──────────────────────────────────────────────────────────┐
│  Phase 2: Integration into Core                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Task 1: MCP Server + Light CIM (5h)              │  │
│  │  Task 2: JarvisWebUI Integration (2h)             │  │
│  │  Task 3: Workflow Engine (4h)                     │  │
│  │  Task 4: Production Deploy (2h)                   │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## 🎯 TASK 1: MCP SERVER + LIGHT CIM

**Duration:** 5 hours  
**Priority:** High  
**Dependencies:** Phase 1 Complete ✅

### **1.1: MCP Server Setup (2h)**

**Location:** `mcp-servers/sequential-thinking/`

**Deliverables:**
```
mcp-servers/sequential-thinking/
├─ server.py              ← MCP Server main
├─ tools.py               ← Tool definitions
├─ requirements.txt
└─ README.md
```

**Tools to Implement:**
1. `sequential_thinking` - Execute step-by-step tasks
2. `sequential_workflow` - Use predefined workflows

**Integration:**
- Register in `mcp/hub.py`
- Add route in `mcp/endpoint.py`
- Connect to Sequential Engine from Phase 1

**Testing:**
- Health check endpoint
- Simple 3-step task
- Auto step generation
- Error handling

**Reference:** `documentation/features/PHASE2_TASK1_MCP_SERVER.md`

---

### **1.2: Light CIM Integration (2h)** ⭐ NEW!

**Location:** `core/safety/light_cim.py`

**Purpose:** Quick safety checks for ALL requests (not just Sequential)

**Components:**
```python
class LightCIM:
    def validate_intent()         # Intent safety check
    def check_logic_basic()       # Quick consistency
    def safety_guard_lite()       # PII & sensitive topics
```

**Integration Point:**
```python
# core/layers/control.py
class ControlLayer:
    def __init__(self):
        self.light_cim = LightCIM()  # NEW!
    
    async def verify(self, user_text, thinking_plan, memory):
        # Existing Qwen validation
        qwen_result = await self._qwen_verify(...)
        
        # NEW: Light CIM validation
        cim_result = self.light_cim.validate_basic(...)
        
        # Merge and return
        return self._merge_validations(qwen_result, cim_result)
```

**Performance Target:**
- < 50ms overhead per request
- Non-blocking (async)
- Graceful degradation

**Escalation Logic:**
```python
# When to use Full CIM (Sequential Engine)?
if hallucination_risk == "high" or
   multi_step_task or
   light_cim_confidence < 0.7:
    → Use Sequential Engine (Full CIM)
else:
    → Continue with Light CIM only
```

**Reference:** `documentation/architecture/DESIGN_CIM_INTEGRATION.md`

---

### **1.3: Testing & Documentation (1h)**

**Unit Tests:**
- Light CIM functions
- Escalation logic
- ControlLayer integration

**Integration Tests:**
- Simple query (Light CIM only)
- Complex task (Light → Full escalation)
- MCP Server health checks

**Performance Tests:**
- Light CIM overhead < 100ms
- Full system latency

**Documentation:**
- Update ControlLayer docs
- Light CIM usage guide
- Escalation examples

---

## 🎨 TASK 2: JARVISWEBUI INTEGRATION

**Duration:** 2 hours  
**Priority:** High  
**Dependencies:** Task 1 Complete

### **2.1: Sequential Mode Toggle (30 min)**

**Location:** `adapters/Jarvis/static/js/sequential.js`

**Features:**
- Toggle "Sequential Thinking Mode" in settings
- Enable/disable with checkbox
- Show/hide progress UI

**UI Components:**
```javascript
class SequentialThinking {
    initUI()              // Setup toggle & progress UI
    toggle(enabled)       // Enable/disable mode
    executeTask()         // Call MCP endpoint
    displaySteps()        // Show live progress
    updateProgress()      // Update progress bar
}
```

---

### **2.2: Progress Visualization (30 min)**

**Location:** `adapters/Jarvis/static/css/sequential.css`

**UI Elements:**
- Progress bar (0-100%)
- Step list with icons:
  - ✅ Completed
  - ⚙️ Executing
  - ❌ Failed
  - ⏸️ Pending
- State file download link
- Stop button

**Design:**
- Clean, minimal UI
- Real-time updates
- Responsive layout
- Error states

---

### **2.3: Adapter Integration (1h)**

**Modify:** `adapters/Jarvis/adapter.py`
```python
def transform_request(self, raw_request):
    sequential_mode = raw_request.get("sequential_mode", False)
    
    if sequential_mode:
        # Add Sequential Mode context
        messages.insert(0, Message(
            role=MessageRole.SYSTEM,
            content="User has Sequential Thinking enabled"
        ))
```

**Add Endpoint:** `adapters/Jarvis/main.py`
```python
@app.post("/chat/sequential")
async def chat_sequential(request: Request):
    data = await request.json()
    data["sequential_mode"] = True
    
    # Call MCP Sequential endpoint
    response = await mcp_client.call_tool(...)
    return JSONResponse(response)
```

**Reference:** `documentation/features/PHASE2_TASK2_JARVISWEBUI.md`

---

## 🔄 TASK 3: WORKFLOW ENGINE

**Duration:** 4 hours  
**Priority:** Medium  
**Dependencies:** Task 1 & 2 Complete

### **3.1: Workflow Templates (2h)**

**Location:** `modules/workflows/`

**Structure:**
```
modules/workflows/
├─ __init__.py
├─ engine.py              ← Workflow execution
├─ templates/
│  ├─ data_analysis.yaml
│  ├─ research.yaml
│  ├─ code_review.yaml
│  └─ decision_making.yaml
└─ README.md
```

**Template Format:**
```yaml
# data_analysis.yaml
id: data_analysis
name: "Data Analysis Workflow"
description: "Analyze datasets step-by-step"
variables:
  - name: dataset_path
    type: string
    required: true
  - name: analysis_type
    type: enum
    values: [statistical, exploratory, predictive]
steps:
  - id: load
    description: "Load dataset from {dataset_path}"
    dependencies: []
  - id: clean
    description: "Clean and validate data"
    dependencies: [load]
  - id: analyze
    description: "Perform {analysis_type} analysis"
    dependencies: [clean]
  - id: visualize
    description: "Create visualizations"
    dependencies: [analyze]
  - id: report
    description: "Generate analysis report"
    dependencies: [visualize]
```

---

### **3.2: Template Engine (2h)**

**Features:**
- Load templates from YAML
- Variable substitution
- Conditional steps
- Loop support

**API:**
```python
class WorkflowEngine:
    def load_template(template_id: str) -> Workflow
    def instantiate(workflow: Workflow, variables: Dict) -> Task
    def validate(workflow: Workflow) -> List[Error]
```

**Integration:**
- MCP tool `sequential_workflow`
- JarvisWebUI workflow selector
- Sequential Engine execution

---

## 🚀 TASK 4: PRODUCTION DEPLOY

**Duration:** 2 hours  
**Priority:** High  
**Dependencies:** All Tasks Complete

### **4.1: Docker Configuration (1h)**

**Files:**
```
docker/
├─ docker-compose.yml     ← Update with Sequential server
├─ Dockerfile.sequential  ← NEW! Sequential server image
└─ .env.example           ← Environment variables
```

**Services:**
```yaml
services:
  jarvis-main:
    # existing...
  
  sequential-thinking:  # NEW!
    build:
      context: .
      dockerfile: docker/Dockerfile.sequential
    ports:
      - "8001:8001"
    environment:
      - OLLAMA_BASE=${OLLAMA_BASE}
      - FRANK_CIM_ENABLED=true
    volumes:
      - ./modules/sequential_thinking:/app/modules/sequential_thinking
      - ./state:/app/state
```

---

### **4.2: Health Checks & Monitoring (1h)**

**Health Endpoints:**
```python
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "services": {
            "sequential_engine": check_engine(),
            "light_cim": check_cim(),
            "full_cim": check_frank(),
            "mcp_hub": check_hub()
        }
    }
```

**Monitoring:**
- Request latency metrics
- CIM escalation rates
- Step execution times
- Error rates

**Logging:**
- Structured JSON logs
- Log levels (DEBUG, INFO, WARN, ERROR)
- Request tracing
- Performance profiling

---

## 📊 PHASE 2 METRICS

### **Success Criteria:**

| Metric | Target | Method |
|--------|--------|--------|
| MCP Server Uptime | > 99% | Health checks |
| Light CIM Overhead | < 100ms | Performance tests |
| Escalation Accuracy | > 90% | Manual review |
| UI Responsiveness | < 200ms | Frontend metrics |
| Step Execution Success | > 95% | Sequential Engine logs |

---

## 🗓️ TIMELINE

**Day 1 (Morning):**
- ✅ Task 1.1: MCP Server Setup (2h)
- ✅ Task 1.2: Light CIM Integration (2h)

**Day 1 (Afternoon):**
- ✅ Task 1.3: Testing (1h)
- ✅ Task 2: JarvisWebUI (2h)

**Day 2:**
- ✅ Task 3: Workflow Engine (4h)

**Day 3:**
- ✅ Task 4: Production Deploy (2h)
- ✅ Final testing & documentation

**Total:** 13 hours (2-3 days)

---

## 📚 DOCUMENTATION

### **Created:**
- `PHASE2_TASK1_MCP_SERVER.md` (11KB) ✅
- `PHASE2_TASK2_JARVISWEBUI.md` (14KB) ✅
- `DESIGN_CIM_INTEGRATION.md` (NEW!) ⭐

### **To Create:**
- `PHASE2_TASK3_WORKFLOWS.md`
- `PHASE2_TASK4_PRODUCTION.md`
- `API_REFERENCE_SEQUENTIAL.md`

---

## ✅ PHASE 2 CHECKLIST

### **Pre-Phase:**
- [x] Phase 1 Complete & Documented
- [x] Architecture Review (Fixed LobeChat → JarvisWebUI)
- [x] CIM Integration Design (Hybrid Approach)

### **Task 1:**
- [ ] MCP Server created
- [ ] Tools registered
- [ ] Light CIM implemented
- [ ] ControlLayer integrated
- [ ] Escalation logic working
- [ ] Tests passing

### **Task 2:**
- [ ] Sequential toggle in UI
- [ ] Progress visualization
- [ ] Adapter integration
- [ ] Frontend working

### **Task 3:**
- [ ] Workflow templates created
- [ ] Template engine working
- [ ] MCP tool `sequential_workflow`
- [ ] UI workflow selector

### **Task 4:**
- [ ] Docker compose updated
- [ ] Health checks implemented
- [ ] Monitoring setup
- [ ] Production deployment

---

## 🎯 PHASE 2 COMPLETE DEFINITION

Phase 2 is complete when:

1. ✅ All tasks checked off
2. ✅ All tests passing (unit + integration)
3. ✅ Documentation updated
4. ✅ Production deployment successful
5. ✅ Metrics meet targets
6. ✅ Sequential Thinking accessible via:
   - MCP endpoint
   - JarvisWebUI
   - Workflow templates

---

**Status:** Ready to Start 🚀  
**Next:** Begin Task 1.1 (MCP Server Setup)  
**Estimated Completion:** January 17, 2025
