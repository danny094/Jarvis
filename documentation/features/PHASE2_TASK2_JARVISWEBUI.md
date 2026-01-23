# PHASE 2 - TASK 2: JARVISWEBUI (AdminUI) INTEGRATION
**Duration:** 2 hours  
**Location:** adapters/Jarvis/

---

## STEP 2.1: Sequential Mode Toggle (30 min)

### **File: adapters/Jarvis/static/js/sequential.js (NEW)**

```javascript
/**
 * Sequential Thinking Mode Management
 */

class SequentialThinking {
    constructor() {
        this.enabled = false;
        this.currentTask = null;
        this.steps = [];
        this.initUI();
    }
    
    initUI() {
        // Add toggle to UI
        const settingsPanel = document.querySelector('#settings-panel');
        if (settingsPanel) {
            const toggleHTML = `
                <div class="setting-item">
                    <label class="setting-label">
                        <input type="checkbox" id="sequential-mode-toggle">
                        Sequential Thinking Mode
                    </label>
                    <span class="setting-description">
                        Break complex tasks into validated steps
                    </span>
                </div>
            `;
            settingsPanel.insertAdjacentHTML('beforeend', toggleHTML);
            
            // Bind event
            document.getElementById('sequential-mode-toggle')
                .addEventListener('change', (e) => this.toggle(e.target.checked));
        }
        
        // Add progress UI container
        this.createProgressUI();
    }
    
    createProgressUI() {
        const container = document.createElement('div');
        container.id = 'sequential-progress';
        container.className = 'sequential-progress hidden';
        container.innerHTML = `
            <div class="progress-header">
                <h4>Sequential Thinking Progress</h4>
                <button id="sequential-stop" class="btn-stop">Stop</button>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" id="sequential-progress-fill"></div>
            </div>
            <div class="progress-text" id="sequential-progress-text">
                Preparing...
            </div>
            <div class="steps-list" id="sequential-steps-list"></div>
            <div class="state-file-link hidden" id="sequential-state-link">
                <a href="#" target="_blank">View State File</a>
            </div>
        `;
        
        document.querySelector('#chat-container').prepend(container);
    }
    
    toggle(enabled) {
        this.enabled = enabled;
        console.log(`Sequential Mode: ${enabled ? 'ON' : 'OFF'}`);
        
        // Show/hide progress UI
        const progressUI = document.getElementById('sequential-progress');
        if (enabled) {
            progressUI.classList.remove('hidden');
        } else {
            progressUI.classList.add('hidden');
        }
    }
    
    async executeTask(query, conversationId) {
        if (!this.enabled) {
            return null; // Normal mode
        }
        
        try {
            // Show progress
            this.updateProgress(0, 'Initializing...');
            
            // Call MCP endpoint
            const response = await fetch('/mcp/sequential', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    task_description: query,
                    max_steps: 100,
                    max_duration: 3600
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.currentTask = result;
                this.displaySteps(result.steps);
                this.updateProgress(result.progress, 
                    `Completed ${result.completed_steps}/${result.total_steps} steps`);
                
                if (result.state_file) {
                    this.showStateFile(result.state_file);
                }
                
                return result;
            } else {
                this.showError(result.error);
                return null;
            }
            
        } catch (error) {
            console.error('Sequential execution error:', error);
            this.showError(error.message);
            return null;
        }
    }
    
    displaySteps(steps) {
        const container = document.getElementById('sequential-steps-list');
        container.innerHTML = '';
        
        steps.forEach((step, index) => {
            const stepDiv = document.createElement('div');
            stepDiv.className = `step-item step-${step.status}`;
            
            const icon = {
                'completed': '✅',
                'executing': '⚙️',
                'failed': '❌',
                'pending': '⏸️'
            }[step.status] || '○';
            
            stepDiv.innerHTML = `
                <span class="step-icon">${icon}</span>
                <span class="step-number">${index + 1}.</span>
                <span class="step-description">${step.description}</span>
                ${step.error ? `<span class="step-error">${step.error}</span>` : ''}
            `;
            
            container.appendChild(stepDiv);
        });
    }
    
    updateProgress(progress, text) {
        const fill = document.getElementById('sequential-progress-fill');
        const textEl = document.getElementById('sequential-progress-text');
        
        fill.style.width = `${progress * 100}%`;
        textEl.textContent = text;
    }
    
    showStateFile(path) {
        const link = document.getElementById('sequential-state-link');
        link.classList.remove('hidden');
        link.querySelector('a').href = `/state/${path}`;
    }
    
    showError(message) {
        const container = document.getElementById('sequential-progress');
        container.classList.add('error');
        this.updateProgress(0, `Error: ${message}`);
    }
}

// Initialize
window.sequentialThinking = new SequentialThinking();
```

---

### **File: adapters/Jarvis/static/css/sequential.css (NEW)**

```css
/* Sequential Thinking UI Styles */

.sequential-progress {
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 16px;
    margin: 16px 0;
    transition: all 0.3s ease;
}

.sequential-progress.hidden {
    display: none;
}

.sequential-progress.error {
    border-color: #ef4444;
    background: #fee;
}

.progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}

.progress-header h4 {
    margin: 0;
    font-size: 16px;
    color: #333;
}

.btn-stop {
    padding: 4px 12px;
    background: #ef4444;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
}

.btn-stop:hover {
    background: #dc2626;
}

.progress-bar {
    width: 100%;
    height: 8px;
    background: #e5e7eb;
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 8px;
}

.progress-fill {
    height: 100%;
    background: linear-gradient(90deg, #3b82f6, #8b5cf6);
    transition: width 0.5s ease;
    width: 0%;
}

.progress-text {
    font-size: 14px;
    color: #666;
    margin-bottom: 16px;
}

.steps-list {
    max-height: 300px;
    overflow-y: auto;
    margin-top: 12px;
}

.step-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px;
    margin: 4px 0;
    border-radius: 4px;
    transition: background 0.3s;
}

.step-item:hover {
    background: #f9fafb;
}

.step-completed {
    background: #f0fdf4;
}

.step-executing {
    background: #eff6ff;
    animation: pulse 2s infinite;
}

.step-failed {
    background: #fef2f2;
}

.step-pending {
    opacity: 0.6;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

.step-icon {
    font-size: 18px;
    min-width: 24px;
}

.step-number {
    font-weight: 600;
    color: #6b7280;
    min-width: 30px;
}

.step-description {
    flex: 1;
    font-size: 14px;
    color: #374151;
}

.step-error {
    color: #ef4444;
    font-size: 12px;
    font-style: italic;
}

.state-file-link {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid #ddd;
}

.state-file-link.hidden {
    display: none;
}

.state-file-link a {
    color: #3b82f6;
    text-decoration: none;
    font-size: 14px;
}

.state-file-link a:hover {
    text-decoration: underline;
}

/* Settings panel styling */
.setting-item {
    padding: 12px 0;
    border-bottom: 1px solid #e5e7eb;
}

.setting-label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    font-weight: 500;
}

.setting-description {
    display: block;
    font-size: 12px;
    color: #6b7280;
    margin-left: 28px;
    margin-top: 4px;
}
```

---

## STEP 2.2: Jarvis Adapter Integration (45 min)

### **Modify: adapters/Jarvis/adapter.py**

Add Sequential Mode support:

```python
# adapters/Jarvis/adapter.py (add to JarvisAdapter)

def transform_request(self, raw_request: Dict[str, Any]) -> CoreChatRequest:
    """
    Enhanced to support Sequential Mode
    """
    query = raw_request.get("query", "")
    conversation_id = raw_request.get("conversation_id", "global")
    
    # Check if Sequential Mode is enabled
    sequential_mode = raw_request.get("sequential_mode", False)
    
    messages = [Message(role=MessageRole.USER, content=query)]
    
    # Add Sequential Mode context
    if sequential_mode:
        system_msg = "User has enabled Sequential Thinking Mode. Break down complex tasks into steps."
        messages.insert(0, Message(role=MessageRole.SYSTEM, content=system_msg))
    
    return CoreChatRequest(
        model=raw_request.get("model", "llama3.1:8b"),
        messages=messages,
        conversation_id=conversation_id,
        stream=raw_request.get("stream", False),
        source_adapter=self.name,
        raw_request=raw_request,
        # Add Sequential Mode metadata
        metadata={"sequential_mode": sequential_mode}
    )
```

---

### **Modify: adapters/Jarvis/main.py**

Add Sequential endpoint:

```python
# adapters/Jarvis/main.py (add endpoint)

@app.post("/chat/sequential")
async def chat_sequential(request: Request):
    """
    Sequential Thinking Chat Endpoint
    
    Automatically uses Sequential Thinking for the query.
    """
    data = await request.json()
    data["sequential_mode"] = True  # Force Sequential Mode
    
    # Call MCP Sequential endpoint
    response = await mcp_client.call_tool(
        server="sequential-thinking",
        tool="sequential_thinking",
        params={
            "task_description": data["query"],
            "max_steps": data.get("max_steps", 100),
            "max_duration": data.get("max_duration", 3600)
        }
    )
    
    return JSONResponse(response)
```

---

## STEP 2.3: Frontend Integration (45 min)

### **Modify: adapters/Jarvis/static/js/app.js**

Integrate Sequential Thinking:

```javascript
// adapters/Jarvis/static/js/app.js (modify sendMessage)

async function sendMessage(query) {
    // Check if Sequential Mode is enabled
    if (window.sequentialThinking && window.sequentialThinking.enabled) {
        // Use Sequential Thinking
        const result = await window.sequentialThinking.executeTask(
            query,
            currentConversationId
        );
        
        if (result && result.success) {
            // Display result in chat
            displayMessage({
                role: 'assistant',
                content: formatSequentialResult(result),
                metadata: {
                    sequential: true,
                    task_id: result.task_id,
                    steps: result.completed_steps + '/' + result.total_steps
                }
            });
        }
        
        return;
    }
    
    // Normal chat mode
    // ... existing code ...
}

function formatSequentialResult(result) {
    let content = `**Sequential Thinking Result**\n\n`;
    content += `Progress: ${(result.progress * 100).toFixed(0)}%\n`;
    content += `Completed: ${result.completed_steps}/${result.total_steps} steps\n\n`;
    
    content += `**Steps:**\n`;
    result.steps.forEach((step, i) => {
        const icon = {
            'completed': '✅',
            'failed': '❌',
            'pending': '⏸️'
        }[step.status] || '○';
        
        content += `${icon} ${i+1}. ${step.description}\n`;
        if (step.result) {
            content += `   → ${step.result}\n`;
        }
    });
    
    if (result.state_file) {
        content += `\n[View Full State File](${result.state_file})`;
    }
    
    return content;
}
```

---

### **Modify: adapters/Jarvis/index.html**

Add Sequential CSS and JS:

```html
<!-- adapters/Jarvis/index.html (add to <head>) -->

<link rel="stylesheet" href="/static/css/sequential.css">

<!-- Add before </body> -->
<script src="/static/js/sequential.js"></script>
```

---

## DELIVERABLES

```
✅ Sequential Mode Toggle in JarvisWebUI
✅ Progress visualization (bar + steps)
✅ Live step updates
✅ State file link
✅ Error handling
✅ Adapter integration
✅ Frontend integration
✅ CSS styling

Result: Beautiful Sequential Thinking UI in JarvisWebUI!
```

---

## TESTING

```bash
# Start servers
python adapters/Jarvis/main.py

# Test in browser
1. Open http://localhost:8000
2. Toggle "Sequential Thinking Mode" ON
3. Send query: "Analyze sales data from Q4"
4. Watch progress bar and steps update
5. Click state file link to see full details
```

---

**Time:** 2 hours  
**Next:** Task 3 - Workflow Engine
