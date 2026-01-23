# TASK 2: JARVISWEBUI INTEGRATION - DETAILED ROADMAP

**Date:** 2026-01-16  
**Estimated Duration:** 2 hours  
**Risk Level:** Medium (touching production UI)  
**Dependencies:** Task 1 Complete ✅

---

## 🎯 OBJECTIVE

Integrate Sequential Thinking MCP Server with JarvisWebUI to provide:
1. **Sequential Mode Toggle** - Enable/disable in UI
2. **Live Progress Tracking** - Real-time step visualization
3. **CIM Validation Display** - Show Frank's 40+25+20 modules at work
4. **Graceful Degradation** - Works even if MCP server is down

---

## 📁 FILES TO MODIFY

### **Frontend (4 files):**
```
✅ adapters/Jarvis/index.html              (Add Sequential UI section)
✅ adapters/Jarvis/static/js/sequential.js (NEW - Sequential logic)
✅ adapters/Jarvis/static/js/app.js        (Integrate sequential mode)
✅ adapters/Jarvis/static/js/chat.js       (Handle sequential responses)
```

### **Backend (2 files):**
```
✅ adapters/Jarvis/main.py                 (Add /chat/sequential endpoint)
✅ adapters/Jarvis/adapter.py              (Transform sequential requests)
```

### **Testing (1 file):**
```
✅ /tmp/test_task2_integration.py          (NEW - Integration tests)
```

**Total:** 7 files (5 modified, 2 new)

---

## 🗺️ STEP-BY-STEP ROADMAP

### **PHASE 1: PREPARATION (10 min)**

#### **Step 1.1: Backup Everything**
```bash
cd /DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis

# Backup all files we'll modify
sudo cp index.html index.html.backup_task2_$(date +%Y%m%d_%H%M%S)
sudo cp main.py main.py.backup_task2
sudo cp adapter.py adapter.py.backup_task2
sudo cp static/js/app.js static/js/app.js.backup_task2
sudo cp static/js/chat.js static/js/chat.js.backup_task2
```

**Checkpoint 1:** ✅ All backups created

---

#### **Step 1.2: Verify MCP Server Running**
```bash
# Check MCP server is up
curl http://localhost:8001/
# Should return: {"name":"sequential-thinking","version":"1.0.0","status":"healthy"}

# Check tools available
curl http://localhost:8001/tools
# Should list sequential_thinking and sequential_workflow
```

**Checkpoint 2:** ✅ MCP Server healthy

---

#### **Step 1.3: Review Current UI Structure**
```bash
# Check if UI is already using tabs/sections
grep -i "tab\|section" index.html | head -10

# Check chat flow
grep -i "sendMessage\|handleResponse" static/js/chat.js | head -5
```

**Checkpoint 3:** ✅ UI structure understood

---

### **PHASE 2: FRONTEND - NEW SEQUENTIAL UI (45 min)**

#### **Step 2.1: Create sequential.js (NEW FILE - 15 min)**

**Location:** `adapters/Jarvis/static/js/sequential.js`

**Content:**
```javascript
/**
 * Sequential Thinking Mode - Frontend Controller
 * Manages Sequential Mode UI and MCP Server integration
 */

class SequentialThinking {
    constructor() {
        this.enabled = false;
        this.currentTask = null;
        this.pollInterval = null;
    }

    // Initialize UI elements
    initUI() {
        const toggleHTML = `
            <div id="sequential-mode-container" class="settings-section">
                <h3>🧠 Sequential Thinking Mode</h3>
                <div class="toggle-container">
                    <label class="switch">
                        <input type="checkbox" id="sequential-mode-toggle">
                        <span class="slider"></span>
                    </label>
                    <span>Enable step-by-step reasoning with CIM validation</span>
                </div>
            </div>
        `;
        
        const progressHTML = `
            <div id="sequential-progress" style="display:none;">
                <h4>Progress</h4>
                <div class="progress-bar">
                    <div id="progress-fill" style="width:0%"></div>
                    <span id="progress-text">0%</span>
                </div>
                
                <h4>Steps</h4>
                <div id="sequential-steps"></div>
                
                <div class="sequential-controls">
                    <button id="stop-sequential" class="btn-danger">Stop Task</button>
                    <button id="download-state" class="btn-secondary">Download State</button>
                </div>
            </div>
        `;
        
        // Insert into settings panel
        document.querySelector('#settings-panel')?.insertAdjacentHTML('beforeend', toggleHTML);
        
        // Insert into chat area
        document.querySelector('#chat-container')?.insertAdjacentHTML('afterbegin', progressHTML);
        
        this.attachEventListeners();
    }

    // Attach event handlers
    attachEventListeners() {
        document.getElementById('sequential-mode-toggle')?.addEventListener('change', (e) => {
            this.toggle(e.target.checked);
        });
        
        document.getElementById('stop-sequential')?.addEventListener('click', () => {
            this.stopTask();
        });
        
        document.getElementById('download-state')?.addEventListener('click', () => {
            this.downloadState();
        });
    }

    // Toggle sequential mode
    toggle(enabled) {
        this.enabled = enabled;
        console.log(`Sequential Thinking Mode: ${enabled ? 'ENABLED' : 'DISABLED'}`);
        
        // Show/hide progress UI
        const progressEl = document.getElementById('sequential-progress');
        if (progressEl) {
            progressEl.style.display = enabled ? 'block' : 'none';
        }
        
        // Update chat placeholder if enabled
        if (enabled) {
            const inputEl = document.querySelector('#message-input');
            if (inputEl) {
                inputEl.placeholder = "Ask a complex question for step-by-step analysis...";
            }
        }
    }

    // Execute task in sequential mode
    async executeTask(message) {
        if (!this.enabled) {
            return null; // Not in sequential mode
        }
        
        try {
            const response = await fetch('/chat/sequential', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: message,
                    sequential_mode: true
                })
            });
            
            const data = await response.json();
            
            if (data.task_id) {
                this.currentTask = data.task_id;
                this.startPolling();
            }
            
            return data;
        } catch (error) {
            console.error('Sequential execution failed:', error);
            this.showError('Failed to start sequential task. Using regular mode.');
            return null;
        }
    }

    // Start polling for progress
    startPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }
        
        this.pollInterval = setInterval(async () => {
            if (!this.currentTask) return;
            
            try {
                const response = await fetch(`/sequential/status/${this.currentTask}`);
                const data = await response.json();
                
                this.updateProgress(data);
                
                // Stop polling if task complete
                if (data.progress >= 1.0 || data.status === 'complete') {
                    clearInterval(this.pollInterval);
                    this.pollInterval = null;
                }
            } catch (error) {
                console.error('Failed to poll status:', error);
            }
        }, 500); // Poll every 500ms
    }

    // Update progress UI
    updateProgress(data) {
        // Update progress bar
        const progress = Math.round(data.progress * 100);
        document.getElementById('progress-fill').style.width = `${progress}%`;
        document.getElementById('progress-text').textContent = `${progress}%`;
        
        // Update steps
        this.displaySteps(data.steps);
    }

    // Display steps with status icons
    displaySteps(steps) {
        const stepsContainer = document.getElementById('sequential-steps');
        if (!stepsContainer) return;
        
        const icons = {
            'verified': '✅',
            'executing': '⚙️',
            'failed': '❌',
            'pending': '⏸️'
        };
        
        const stepsHTML = steps.map(step => {
            const icon = icons[step.status] || '⏸️';
            return `
                <div class="step-item status-${step.status}">
                    <span class="step-icon">${icon}</span>
                    <span class="step-description">${step.description}</span>
                    ${step.cim_validation ? `
                        <div class="cim-badge">
                            CIM: ${step.cim_validation.priors_checked || 0} priors
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
        
        stepsContainer.innerHTML = stepsHTML;
    }

    // Stop current task
    async stopTask() {
        if (!this.currentTask) return;
        
        try {
            await fetch(`/sequential/stop/${this.currentTask}`, {
                method: 'POST'
            });
            
            clearInterval(this.pollInterval);
            this.currentTask = null;
            this.showMessage('Task stopped');
        } catch (error) {
            console.error('Failed to stop task:', error);
        }
    }

    // Download current state
    downloadState() {
        if (!this.currentTask) return;
        
        window.open(`/sequential/state/${this.currentTask}`, '_blank');
    }

    // Show error message
    showError(message) {
        // Use existing notification system
        if (window.showNotification) {
            window.showNotification(message, 'error');
        } else {
            console.error(message);
        }
    }

    // Show info message
    showMessage(message) {
        if (window.showNotification) {
            window.showNotification(message, 'info');
        } else {
            console.log(message);
        }
    }
}

// Initialize when DOM ready
document.addEventListener('DOMContentLoaded', () => {
    window.sequentialThinking = new SequentialThinking();
    window.sequentialThinking.initUI();
});
```

**Checkpoint 4:** ✅ sequential.js created with full logic

---

#### **Step 2.2: Modify index.html (10 min)**

**Add to `<head>` section:**
```html
<!-- Sequential Thinking CSS -->
<style>
    #sequential-mode-container {
        margin: 20px 0;
        padding: 15px;
        background: #f5f5f5;
        border-radius: 8px;
    }
    
    .toggle-container {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    
    .switch {
        position: relative;
        display: inline-block;
        width: 50px;
        height: 24px;
    }
    
    .switch input {
        opacity: 0;
        width: 0;
        height: 0;
    }
    
    .slider {
        position: absolute;
        cursor: pointer;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: #ccc;
        transition: .4s;
        border-radius: 24px;
    }
    
    .slider:before {
        position: absolute;
        content: "";
        height: 16px;
        width: 16px;
        left: 4px;
        bottom: 4px;
        background-color: white;
        transition: .4s;
        border-radius: 50%;
    }
    
    input:checked + .slider {
        background-color: #4CAF50;
    }
    
    input:checked + .slider:before {
        transform: translateX(26px);
    }
    
    #sequential-progress {
        margin: 20px 0;
        padding: 15px;
        background: #fff;
        border: 1px solid #ddd;
        border-radius: 8px;
    }
    
    .progress-bar {
        position: relative;
        width: 100%;
        height: 30px;
        background: #f0f0f0;
        border-radius: 15px;
        overflow: hidden;
        margin: 10px 0;
    }
    
    #progress-fill {
        height: 100%;
        background: linear-gradient(90deg, #4CAF50, #45a049);
        transition: width 0.3s ease;
    }
    
    #progress-text {
        position: absolute;
        width: 100%;
        text-align: center;
        line-height: 30px;
        font-weight: bold;
    }
    
    .step-item {
        padding: 10px;
        margin: 5px 0;
        background: #fafafa;
        border-left: 3px solid #ddd;
        border-radius: 4px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    
    .step-item.status-verified {
        border-left-color: #4CAF50;
    }
    
    .step-item.status-executing {
        border-left-color: #2196F3;
        animation: pulse 1.5s infinite;
    }
    
    .step-item.status-failed {
        border-left-color: #f44336;
    }
    
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
    }
    
    .step-icon {
        font-size: 20px;
    }
    
    .step-description {
        flex: 1;
    }
    
    .cim-badge {
        background: #e3f2fd;
        color: #1976d2;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
    }
    
    .sequential-controls {
        margin-top: 15px;
        display: flex;
        gap: 10px;
    }
    
    .btn-danger {
        background: #f44336;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        cursor: pointer;
    }
    
    .btn-secondary {
        background: #757575;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        cursor: pointer;
    }
</style>

<!-- Sequential Thinking Script -->
<script src="/static/js/sequential.js"></script>
```

**Checkpoint 5:** ✅ index.html updated with CSS and script tag

---

#### **Step 2.3: Modify chat.js (10 min)**

**Find the `sendMessage()` function and modify:**

```javascript
// In chat.js - modify sendMessage function
async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message) return;
    
    // Check if Sequential Mode is enabled
    if (window.sequentialThinking && window.sequentialThinking.enabled) {
        // Use sequential execution
        const result = await window.sequentialThinking.executeTask(message);
        
        if (result) {
            // Sequential mode handled it
            displayMessage('user', message);
            displayMessage('assistant', 'Processing in Sequential Mode...');
            return;
        }
        // Fall through to regular mode if sequential failed
    }
    
    // Regular chat flow continues...
    // ... existing code ...
}
```

**Checkpoint 6:** ✅ chat.js integrates sequential mode

---

#### **Step 2.4: Modify app.js (10 min)**

**Add initialization check:**

```javascript
// In app.js - add to initialization
document.addEventListener('DOMContentLoaded', function() {
    // ... existing initialization ...
    
    // Initialize Sequential Thinking
    if (window.sequentialThinking) {
        console.log('✅ Sequential Thinking Mode initialized');
    } else {
        console.warn('⚠️ Sequential Thinking Mode not available');
    }
});
```

**Checkpoint 7:** ✅ app.js initialization updated

---

### **PHASE 3: BACKEND INTEGRATION (45 min)**

#### **Step 3.1: Modify main.py - Add Sequential Endpoints (20 min)**

**Add after existing endpoints:**

```python
# Sequential Thinking Endpoints
@app.post("/chat/sequential")
async def chat_sequential(request: Request):
    """
    Handle sequential thinking requests
    Routes to MCP Server sequential_thinking tool
    """
    try:
        data = await request.json()
        message = data.get("message", "")
        
        # Call MCP Server
        import requests
        mcp_response = requests.post(
            "http://localhost:8001/tools/call",
            json={
                "name": "sequential_thinking",
                "arguments": {
                    "task_description": message
                }
            },
            timeout=60
        )
        
        result = mcp_response.json()
        
        return JSONResponse({
            "task_id": result.get("task_id"),
            "success": result.get("success", False),
            "message": "Sequential task started",
            "initial_data": result
        })
        
    except Exception as e:
        logger.error(f"Sequential chat error: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.get("/sequential/status/{task_id}")
async def sequential_status(task_id: str):
    """
    Get status of sequential task
    Currently returns cached status (polling MCP server would be better)
    """
    # TODO: Implement actual status polling from MCP server
    # For now, return mock data
    return JSONResponse({
        "task_id": task_id,
        "progress": 0.75,
        "status": "executing",
        "steps": [
            {
                "id": "step1",
                "description": "Analysis phase",
                "status": "verified",
                "cim_validation": {"priors_checked": 40}
            },
            {
                "id": "step2",
                "description": "Synthesis phase",
                "status": "executing",
                "cim_validation": {"patterns_matched": 25}
            }
        ]
    })


@app.post("/sequential/stop/{task_id}")
async def sequential_stop(task_id: str):
    """Stop sequential task"""
    # TODO: Implement actual stop mechanism
    return JSONResponse({"success": True, "message": "Task stopped"})


@app.get("/sequential/state/{task_id}")
async def sequential_state(task_id: str):
    """Download task state"""
    # TODO: Implement state download
    return JSONResponse({"task_id": task_id, "state": {}})
```

**Checkpoint 8:** ✅ main.py endpoints added

---

#### **Step 3.2: Modify adapter.py (15 min)**

**Add sequential mode detection:**

```python
# In adapter.py

def transform_request(self, raw_request: dict) -> dict:
    """Transform incoming request to TRION format"""
    
    # Check for sequential mode
    sequential_mode = raw_request.get("sequential_mode", False)
    
    if sequential_mode:
        # Add system message for sequential context
        messages = raw_request.get("messages", [])
        messages.insert(0, {
            "role": "system",
            "content": "User has enabled Sequential Thinking Mode. "
                      "Use step-by-step reasoning with CIM validation."
        })
        raw_request["messages"] = messages
    
    # Continue with existing transformation
    # ... existing code ...
    
    return transformed_request
```

**Checkpoint 9:** ✅ adapter.py handles sequential mode

---

#### **Step 3.3: Test Backend (10 min)**

**Create test script:**

```bash
# Test sequential endpoint
curl -X POST http://localhost:8000/chat/sequential \
  -H "Content-Type: application/json" \
  -d '{"message": "Analyze Q4 sales trends"}'

# Should return task_id and success
```

**Checkpoint 10:** ✅ Backend endpoints working

---

### **PHASE 4: INTEGRATION TESTING (20 min)**

#### **Step 4.1: Create Integration Test (10 min)**

**File:** `/tmp/test_task2_integration.py`

```python
#!/usr/bin/env python3
"""
Integration Test for Task 2: JarvisWebUI Sequential Integration
"""

import requests
import time

BASE_URL = "http://localhost:8000"

def test_sequential_endpoint():
    """Test /chat/sequential endpoint"""
    print("TEST 1: Sequential Chat Endpoint")
    
    response = requests.post(
        f"{BASE_URL}/chat/sequential",
        json={"message": "Test sequential thinking"}
    )
    
    assert response.status_code == 200, f"Got {response.status_code}"
    data = response.json()
    assert "task_id" in data, "No task_id in response"
    print("✅ PASS: Sequential endpoint working")
    return data["task_id"]

def test_status_endpoint(task_id):
    """Test /sequential/status endpoint"""
    print(f"TEST 2: Status Endpoint (task: {task_id})")
    
    response = requests.get(f"{BASE_URL}/sequential/status/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert "progress" in data
    assert "steps" in data
    print("✅ PASS: Status endpoint working")

def test_ui_files():
    """Test UI files are accessible"""
    print("TEST 3: UI Files Accessible")
    
    # Test sequential.js
    response = requests.get(f"{BASE_URL}/static/js/sequential.js")
    assert response.status_code == 200
    print("✅ PASS: sequential.js accessible")

if __name__ == "__main__":
    print("=" * 60)
    print("TASK 2 INTEGRATION TESTS")
    print("=" * 60)
    
    task_id = test_sequential_endpoint()
    test_status_endpoint(task_id)
    test_ui_files()
    
    print("\n🎉 ALL TESTS PASSED!")
```

**Checkpoint 11:** ✅ Test suite created

---

#### **Step 4.2: Run Integration Tests (5 min)**

```bash
python3 /tmp/test_task2_integration.py
```

**Expected:**
```
TEST 1: Sequential Chat Endpoint
✅ PASS: Sequential endpoint working
TEST 2: Status Endpoint
✅ PASS: Status endpoint working
TEST 3: UI Files Accessible
✅ PASS: sequential.js accessible

🎉 ALL TESTS PASSED!
```

**Checkpoint 12:** ✅ All integration tests passing

---

#### **Step 4.3: Manual UI Test (5 min)**

**Steps:**
1. Open browser: http://localhost:8000
2. Open Settings panel
3. Find "Sequential Thinking Mode" toggle
4. Enable it ✅
5. Send a message: "Analyze sales trends"
6. Verify progress UI appears
7. Check steps display correctly

**Checkpoint 13:** ✅ UI working in browser

---

### **PHASE 5: DOCUMENTATION & CLEANUP (10 min)**

#### **Step 5.1: Document Changes**

Create: `documentation/features/TASK_2_COMPLETE.md`

**Checkpoint 14:** ✅ Documentation created

---

#### **Step 5.2: Update Roadmap**

Mark Task 2 as complete in PHASE2_ROADMAP.md

**Checkpoint 15:** ✅ Roadmap updated

---

## 📊 CHECKPOINTS SUMMARY

```
Phase 1: Preparation
✅ Checkpoint 1:  Backups created
✅ Checkpoint 2:  MCP Server verified
✅ Checkpoint 3:  UI structure reviewed

Phase 2: Frontend
✅ Checkpoint 4:  sequential.js created
✅ Checkpoint 5:  index.html updated
✅ Checkpoint 6:  chat.js modified
✅ Checkpoint 7:  app.js initialized

Phase 3: Backend
✅ Checkpoint 8:  main.py endpoints added
✅ Checkpoint 9:  adapter.py updated
✅ Checkpoint 10: Backend tested

Phase 4: Testing
✅ Checkpoint 11: Test suite created
✅ Checkpoint 12: Integration tests pass
✅ Checkpoint 13: UI manual test pass

Phase 5: Documentation
✅ Checkpoint 14: Docs created
✅ Checkpoint 15: Roadmap updated
```

---

## ⚠️ RISK MITIGATION

### **Risk 1: UI Breaks**
**Mitigation:** All backups created in Step 1.1  
**Rollback:** `sudo cp index.html.backup_task2_* index.html`

### **Risk 2: MCP Server Down**
**Mitigation:** Graceful degradation - falls back to regular chat  
**Detection:** Try-catch in sequential.js

### **Risk 3: Performance Issues**
**Mitigation:** Polling at 500ms intervals (adjustable)  
**Monitoring:** Check browser console for errors

### **Risk 4: Integration Conflicts**
**Mitigation:** Test in isolation before full integration  
**Rollback:** Restore from backups

---

## 🔄 ROLLBACK PLAN

**If something goes wrong:**

```bash
cd /DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis

# Rollback all changes
sudo cp index.html.backup_task2_* index.html
sudo cp main.py.backup_task2 main.py
sudo cp adapter.py.backup_task2 adapter.py
sudo cp static/js/app.js.backup_task2 static/js/app.js
sudo cp static/js/chat.js.backup_task2 static/js/chat.js

# Remove new file
sudo rm static/js/sequential.js

# Restart service
sudo systemctl restart jarvis-webui
```

---

## ✅ SUCCESS CRITERIA

**Task 2 is complete when:**

1. ✅ Toggle appears in UI
2. ✅ Enabling toggle shows progress section
3. ✅ Sending message in sequential mode calls /chat/sequential
4. ✅ Progress bar updates in real-time
5. ✅ Steps display with correct icons
6. ✅ CIM validation info shows
7. ✅ Stop button works
8. ✅ Falls back to regular chat if MCP down
9. ✅ All integration tests pass
10. ✅ Documentation complete

---

## 📈 PROGRESS TRACKING

**Estimated Times:**
```
Phase 1: Preparation        10 min  ██░░░░░░░░░░░░░░░░░░
Phase 2: Frontend           45 min  █████████░░░░░░░░░░░
Phase 3: Backend            45 min  █████████░░░░░░░░░░░
Phase 4: Testing            20 min  ████░░░░░░░░░░░░░░░░
Phase 5: Documentation      10 min  ██░░░░░░░░░░░░░░░░░░

Total: 2 hours 10 minutes (with buffer)
```

---

## 🎯 NEXT STEPS AFTER TASK 2

**When Task 2 is complete:**

```
Progress: 70% (7/10 hours) ██████████████░░░░░░

Next: Task 3 - Workflow Engine (4h)
Then: Task 4 - Production Deploy (2h)
```

---

**Ready to execute Danny?** 🚀

This roadmap gives us:
- ✅ Clear steps
- ✅ Checkpoints at every stage
- ✅ Rollback plan
- ✅ Risk mitigation
- ✅ Success criteria
- ✅ Time estimates

**We won't get lost!** 😊
