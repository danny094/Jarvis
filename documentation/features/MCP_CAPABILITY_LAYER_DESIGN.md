# MCP CAPABILITY LAYER - DESIGN DOCUMENT

**Created:** 2026-01-12  
**Authors:** Danny (TRION Lead) + Frank (CIM Architect) + ChatGPT  
**Status:** DESIGN - To be implemented in Phase 2  
**Priority:** HIGH - Core architecture improvement

---

## 🎯 EXECUTIVE SUMMARY

**Problem:** Current MCP integration is too low-level and requires code changes for each new server.

**Solution:** Capability Layer that combines:
- Frank's Intent-based thinking (Capabilities, not Tools)
- Danny's Auto-discovery pragmatism (Drop-in registration)
- Hard rule system for WHEN/HOW tools can be called

**Result:** User-friendly, secure, scalable MCP integration where:
- Users don't need to know about tools
- Developers drop in new MCP servers without code changes
- Frank's rules control tool access
- System thinks in Capabilities, not Tools

---

## 🔥 THE KEY INSIGHT

**Frank's Quote:**
> "MCP ist Ausführung.  
> Frank ist Urteil.  
> Capabilities sind Verantwortung."

**Danny's Addition:**
> "Frank's hartes Regelsystem = perfekt für MCP Tool Call Control!"

**Combined Result:**
- Intent-based interface (high-level)
- Auto-registration (pragmatic)
- Rule-based execution (safe)

---

## ❌ CURRENT STATE - THE PROBLEM

### **Low-Level Tool Thinking:**

```json
// Current approach - User/AI calls tools directly:
{
  "tool": "memory_search",
  "arguments": { "query": "Wohnort" }
}
```

**Problems:**
- ❌ User must know MCP exists
- ❌ User must know which tools exist
- ❌ User must know how to call them
- ❌ No safety validation
- ❌ Not explainable
- ❌ Not controllable

### **Hardcoded Registration:**

```python
# Current - requires code changes:
mcp_hub.register_server("memory_server", config)
mcp_hub.register_server("causal_server", config)
# ... manual registration for each server
```

**Problems:**
- ❌ New MCP server = code change
- ❌ Not scalable
- ❌ Error-prone
- ❌ Requires TRION knowledge

---

## ✅ PROPOSED SOLUTION - CAPABILITY LAYER

### **High-Level Intent Thinking:**

```json
// Proposed - User/AI expresses intent:
{
  "intent": "recall_user_fact",
  "subject": "Danny",
  "confidence_required": "high"
}
```

**Then system decides:**
1. Is this intent allowed? (Frank's rules)
2. Which capability handles it? (Capability mapping)
3. Which tool to use? (MCP Hub routing)
4. With what constraints? (Safety validation)

### **Auto-Discovery Registration:**

```bash
# Proposed - just drop in folder:
/mcp_servers/
├─ memory_server/
│   ├─ server.py
│   └─ capabilities.json  ← Declares capabilities!
├─ causal_math_server/
│   ├─ server.py
│   └─ capabilities.json
└─ new_server/  ← Just copy here!
    ├─ server.py
    └─ capabilities.json  ← Auto-discovered!

# TRION automatically:
# 1. Finds all servers
# 2. Reads capabilities.json
# 3. Registers capabilities
# 4. Makes them available
# NO CODE CHANGES NEEDED! 🎉
```

---

## 🏗️ ARCHITECTURE OVERVIEW

### **The Layers:**

```
┌─────────────────────────────────────────────────────┐
│  USER / AI                                          │
│  "Wo wohnt Danny?" (Natural language)              │
└────────────────────┬────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────┐
│  LAYER 1: THINKING LAYER (DeepSeek)                 │
│  - Plans: "Need to recall user fact"               │
│  - Output: Intent + Context                        │
└────────────────────┬────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────┐
│  LAYER 2: CONTROL LAYER (Sequential + Frank + MCP) │
│                                                     │
│  A. Frank's RAG (Reasoning):                       │
│     ├─ Recognizes intent: "recall_user_fact"      │
│     ├─ Selects procedure                          │
│     ├─ Needs capability: CAP_MEMORY_READ          │
│     └─ Checks cognitive biases                    │
│                                                     │
│  B. Capability Resolver (NEW!):                    │
│     ├─ Maps intent → capability                   │
│     ├─ Checks Frank's rules:                      │
│     │   - Bias check required?                    │
│     │   - Prior check required?                   │
│     │   - User confirmation needed?               │
│     ├─ Checks constraints:                        │
│     │   - Read-only?                              │
│     │   - Rate limits?                            │
│     │   - Safe for user data?                     │
│     └─ Decision: ALLOWED or DENIED                │
│                                                     │
│  C. MCP Hub (Enhanced with Auto-Discovery):        │
│     ├─ Auto-discovers servers in /mcp_servers/    │
│     ├─ Registers capabilities from JSON           │
│     ├─ Routes to correct server                   │
│     ├─ Executes with constraints                  │
│     └─ Returns result                             │
└────────────────────┬────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────┐
│  MCP SERVERS (Drop-in Registration!)               │
│  /mcp_servers/                                     │
│  ├─ memory_server/                                 │
│  │   └─ capabilities.json                         │
│  ├─ causal_math_server/                            │
│  │   └─ capabilities.json                         │
│  └─ desktop_commander/                             │
│      └─ capabilities.json                         │
└─────────────────────────────────────────────────────┘
```

### **Key Principle: Separation of Concerns**

```
Frank RAG:        Thinks in INTENTS (high-level)
                  ↓
Capability Layer: Thinks in CAPABILITIES (contracts)
                  ↓
MCP Hub:          Thinks in TOOLS (low-level execution)

User never sees tools!
Developer never changes TRION code!
Frank's rules control everything!
```

---

## 📋 CAPABILITIES.JSON FORMAT

### **Standard Schema:**

```json
{
  "server_name": "memory_server",
  "server_version": "1.0.0",
  "server_description": "Persistent memory storage and retrieval",
  "capabilities": [
    {
      "capability_id": "CAP_MEMORY_READ",
      "intent": "recall_user_fact",
      "description": "Read stored user facts from memory",
      "tools": [
        {
          "tool_name": "memory_search",
          "required_args": ["query"],
          "optional_args": ["limit", "confidence_threshold"],
          "return_type": "list[UserFact]"
        }
      ],
      "constraints": {
        "read_only": true,
        "requires_confirmation": false,
        "max_calls_per_minute": 100,
        "max_calls_per_task": 50,
        "timeout_seconds": 5
      },
      "frank_rules": {
        "bias_check_required": false,
        "prior_check_required": false,
        "safe_for_user_data": true,
        "allowed_step_types": ["normal", "validation"],
        "requires_verified_input": false
      }
    },
    {
      "capability_id": "CAP_MEMORY_WRITE",
      "intent": "store_user_fact",
      "description": "Store new facts in persistent memory",
      "tools": [
        {
          "tool_name": "memory_save",
          "required_args": ["key", "value"],
          "optional_args": ["metadata", "expiry"],
          "return_type": "SaveResult"
        }
      ],
      "constraints": {
        "read_only": false,
        "requires_confirmation": true,
        "max_calls_per_minute": 10,
        "max_calls_per_task": 5,
        "timeout_seconds": 10
      },
      "frank_rules": {
        "bias_check_required": true,
        "prior_check_required": false,
        "safe_for_user_data": true,
        "allowed_step_types": ["normal"],
        "requires_verified_input": true
      }
    }
  ]
}
```

### **Key Fields Explained:**

**capability_id:**
- Unique identifier (e.g., CAP_MEMORY_READ)
- Used by Frank's RAG to request capability
- Namespaced to avoid conflicts

**intent:**
- High-level user/AI intent
- Frank recognizes these
- Maps to capability

**tools:**
- Low-level MCP tools
- Hidden from user
- Multiple tools per capability allowed

**constraints:**
- Technical limits (rate, timeout, etc.)
- System-level controls
- Enforced by MCP Hub

**frank_rules:**
- Cognitive/safety rules
- Frank's validation requirements
- Enforced by Capability Resolver

---

## 💻 IMPLEMENTATION COMPONENTS

### **1. MCPHub Enhancement (Auto-Discovery):**

```python
class MCPHub:
    """
    Enhanced MCP Hub with auto-discovery.
    
    Features:
    - Auto-discovers servers in /mcp_servers/
    - Registers capabilities from JSON
    - Routes requests to correct server
    - Enforces constraints
    """
    
    def __init__(self, mcp_servers_dir="/mcp_servers"):
        self.servers = {}
        self.capabilities = {}
        self.mcp_servers_dir = Path(mcp_servers_dir)
        
        # Auto-discover all servers!
        self._discover_servers()
    
    def _discover_servers(self):
        """
        Auto-discover MCP servers in directory.
        
        For each subdirectory:
        1. Look for capabilities.json
        2. Parse and validate
        3. Register server and capabilities
        4. Make available to system
        """
        for server_dir in self.mcp_servers_dir.iterdir():
            if not server_dir.is_dir():
                continue
            
            cap_file = server_dir / "capabilities.json"
            if cap_file.exists():
                try:
                    self._register_server(server_dir, cap_file)
                except Exception as e:
                    print(f"⚠️  Failed to register {server_dir.name}: {e}")
    
    def _register_server(self, server_dir: Path, cap_file: Path):
        """Register server and its capabilities."""
        with open(cap_file) as f:
            config = json.load(f)
        
        server_name = config["server_name"]
        
        # Validate schema
        self._validate_capabilities_schema(config)
        
        # Register server
        self.servers[server_name] = {
            "path": server_dir,
            "version": config["server_version"],
            "description": config.get("server_description", ""),
            "capabilities": []
        }
        
        # Register each capability
        for cap in config["capabilities"]:
            cap_id = cap["capability_id"]
            
            self.capabilities[cap_id] = {
                "server": server_name,
                "intent": cap["intent"],
                "description": cap["description"],
                "tools": cap["tools"],
                "constraints": cap["constraints"],
                "frank_rules": cap["frank_rules"]
            }
            
            self.servers[server_name]["capabilities"].append(cap_id)
        
        print(f"✅ Registered {server_name} v{config['server_version']}")
        print(f"   Capabilities: {len(config['capabilities'])}")
    
    def list_capabilities(self) -> List[str]:
        """List all available capabilities."""
        return list(self.capabilities.keys())
    
    def get_capability(self, cap_id: str) -> Optional[dict]:
        """Get capability details."""
        return self.capabilities.get(cap_id)
```

### **2. CapabilityResolver (Frank's Rules Integration):**

```python
class CapabilityResolver:
    """
    Resolves intents to capabilities using Frank's rules.
    
    Responsibilities:
    - Map intent → capability
    - Check Frank's cognitive rules
    - Check constraints
    - Decide ALLOWED or DENIED
    """
    
    def __init__(self, mcp_hub: MCPHub, frank_safety: FrankSafetyLayer):
        self.hub = mcp_hub
        self.frank = frank_safety
    
    def resolve(
        self, 
        intent: str, 
        step: Step,
        context: dict
    ) -> Optional[CapabilityResult]:
        """
        Resolve intent to capability.
        
        Process:
        1. Find capability by intent
        2. Check Frank's rules
        3. Check constraints
        4. Return execution plan or None
        
        Returns:
            CapabilityResult if allowed, None if denied
        """
        # Find capability
        cap_id = self._find_capability_by_intent(intent)
        if not cap_id:
            return None
        
        capability = self.hub.get_capability(cap_id)
        frank_rules = capability["frank_rules"]
        
        # === FRANK'S RULES VALIDATION ===
        
        # Check 1: Bias check required?
        if frank_rules["bias_check_required"]:
            safety_check = self.frank.validate_before(step)
            if safety_check.derailed:
                print(f"⚠️  Capability {cap_id} denied: Bias detected")
                return None
        
        # Check 2: Prior check required?
        if frank_rules["prior_check_required"]:
            prior_violations = self.frank.check_cognitive_priors(step)
            if len(prior_violations) > 0:
                print(f"⚠️  Capability {cap_id} denied: Prior violations")
                return None
        
        # Check 3: Step type allowed?
        allowed_types = frank_rules.get("allowed_step_types", ["normal"])
        if step.step_type.value not in allowed_types:
            print(f"⚠️  Capability {cap_id} denied: Step type not allowed")
            return None
        
        # Check 4: Requires verified input?
        if frank_rules["requires_verified_input"]:
            if not step.safety_passed:
                print(f"⚠️  Capability {cap_id} denied: Input not verified")
                return None
        
        # === CONSTRAINTS VALIDATION ===
        
        constraints = capability["constraints"]
        
        # Check 5: User confirmation required?
        if constraints["requires_confirmation"]:
            if not context.get("user_confirmed", False):
                print(f"⚠️  Capability {cap_id} denied: User confirmation needed")
                return None
        
        # Check 6: Rate limits (simplified - would track in production)
        # TODO: Implement rate limiting
        
        # === ALL CHECKS PASSED ===
        
        return CapabilityResult(
            capability_id=cap_id,
            server=capability["server"],
            tools=capability["tools"],
            constraints=constraints,
            approved=True
        )
    
    def _find_capability_by_intent(self, intent: str) -> Optional[str]:
        """Find capability that handles this intent."""
        for cap_id, cap in self.hub.capabilities.items():
            if cap["intent"] == intent:
                return cap_id
        return None
```

### **3. Integration with Sequential Engine:**

```python
class SequentialThinkingEngine:
    """
    Enhanced with Capability Layer support.
    """
    
    def __init__(self, mcp_servers_dir="/mcp_servers"):
        self.safety = FrankSafetyLayer()
        
        # Initialize MCP Hub (auto-discovers servers!)
        self.mcp_hub = MCPHub(mcp_servers_dir)
        
        # Initialize Capability Resolver
        self.capability_resolver = CapabilityResolver(
            self.mcp_hub, 
            self.safety
        )
    
    def _execute_step_with_capabilities(self, step: Step) -> Result:
        """
        Execute step with capability-based tool access.
        
        Flow:
        1. Step declares needed intent
        2. Capability Resolver checks Frank's rules
        3. If approved, execute via MCP Hub
        4. If denied, return error
        """
        # Extract intent from step
        intent = step.context.get("intent")
        
        if intent:
            # Resolve to capability
            cap_result = self.capability_resolver.resolve(
                intent=intent,
                step=step,
                context=step.context
            )
            
            if cap_result:
                # Execute via MCP Hub
                return self._execute_via_mcp(cap_result, step)
            else:
                # Denied by Frank's rules
                return Result(
                    output="Capability denied by safety rules",
                    reasoning="Frank's rules prevented execution",
                    confidence=0.0
                )
        
        # No capability needed - normal execution
        return self._execute_step_normal(step)
```

---

## 🎯 EXAMPLE FLOWS

### **Example 1: Memory Read (Simple, Safe)**

```
USER: "Wo wohnt Danny?"

1. ThinkingLayer (DeepSeek):
   └─ Plans: "Need to recall user fact"
   └─ Creates Step with intent: "recall_user_fact"

2. Frank's RAG:
   └─ Recognizes intent
   └─ Needs capability: CAP_MEMORY_READ
   └─ No bias detected

3. Capability Resolver:
   └─ Finds: CAP_MEMORY_READ
   └─ Checks Frank's rules:
       - bias_check_required: false ✅
       - prior_check_required: false ✅
       - safe_for_user_data: true ✅
   └─ Checks constraints:
       - read_only: true ✅
       - requires_confirmation: false ✅
   └─ APPROVED!

4. MCP Hub:
   └─ Routes to: memory_server
   └─ Executes: memory_search("Danny Wohnort")
   └─ Returns: "Paderborn"

5. User sees: "Danny wohnt in Paderborn"
   NOT: "Called memory_search tool"
```

### **Example 2: Memory Write (Requires Confirmation)**

```
USER: "Speichere dass ich jetzt in Berlin wohne"

1. ThinkingLayer:
   └─ Plans: "Need to store user fact"
   └─ Creates Step with intent: "store_user_fact"

2. Frank's RAG:
   └─ Recognizes intent
   └─ Needs capability: CAP_MEMORY_WRITE
   └─ Runs bias check

3. Capability Resolver:
   └─ Finds: CAP_MEMORY_WRITE
   └─ Checks Frank's rules:
       - bias_check_required: true ✅ (passed)
       - requires_verified_input: true ✅
   └─ Checks constraints:
       - requires_confirmation: true ⚠️
   └─ NEEDS USER CONFIRMATION

4. System asks: "Soll ich speichern: Danny wohnt in Berlin?"
   User: "Ja"

5. Capability Resolver (retry):
   └─ user_confirmed: true ✅
   └─ APPROVED!

6. MCP Hub:
   └─ Executes: memory_save("Wohnort", "Berlin")
   └─ Returns: Success

7. User sees: "Gespeichert: Du wohnst jetzt in Berlin"
```

### **Example 3: Causal Math (Requires Bias Check)**

```
USER: "Sales increased after ads, prove causation"

1. ThinkingLayer:
   └─ Plans: "Need causal validation"
   └─ Creates Step with intent: "validate_causation"

2. Frank's RAG:
   └─ Recognizes: Potential Post Hoc Fallacy!
   └─ Needs capability: CAP_CAUSAL_MATH
   └─ Runs bias check

3. Capability Resolver:
   └─ Finds: CAP_CAUSAL_MATH
   └─ Checks Frank's rules:
       - bias_check_required: true ⚠️
       - Frank detects: Post Hoc pattern!
   └─ DENIED - Bias detected

4. System responds:
   "Cannot validate causation - statement contains Post Hoc fallacy.
    Please rephrase without assuming temporal sequence implies causation."

NO TOOL CALLED - Frank prevented it!
```

---

## 🎁 BENEFITS

### **For Users:**
```
✅ Don't need to know about tools
✅ Natural language intents
✅ Safety guaranteed by Frank
✅ Explainable decisions
   "TRION can recall facts" vs "memory_search tool"
```

### **For Developers:**
```
✅ Drop-in MCP server registration
✅ No TRION code changes needed
✅ Standard capabilities.json format
✅ Auto-discovery handles registration
✅ Scales to 100+ servers easily
```

### **For System:**
```
✅ Clean separation of concerns
✅ Frank controls ALL tool access
✅ Intent-based (high-level)
✅ Testable components
✅ Explainable decisions
```

### **For Frank:**
```
✅ His CIM controls WHEN tools fire
✅ Bias checks BEFORE execution
✅ Hard rules enforced
✅ No tools bypass validation
```

---

## 📊 IMPLEMENTATION PLAN

### **Phase 2 Task 3: MCP Capability Layer (Estimated: 8-12 hours)**

**Step 1: Schema & Structure (2h)**
- Define capabilities.json schema
- Create validation logic
- Document standard

**Step 2: MCPHub Enhancement (3h)**
- Implement auto-discovery
- Add capability registration
- Add health checks

**Step 3: CapabilityResolver (3h)**
- Implement intent → capability mapping
- Integrate Frank's rules
- Add constraint checking

**Step 4: Integration (2h)**
- Connect to Sequential Engine
- Update existing MCP servers
- Add capabilities.json to each

**Step 5: Testing (2h)**
- Unit tests
- Integration tests
- Example flows

---

## 📝 TODO LIST

**Before Implementation:**
- [ ] Review design with team
- [ ] Finalize capabilities.json schema
- [ ] Document migration path for existing MCP servers
- [ ] Create example capabilities.json files

**During Implementation:**
- [ ] Build MCPHub auto-discovery
- [ ] Build CapabilityResolver
- [ ] Integrate with Frank's Safety Layer
- [ ] Update existing MCP servers
- [ ] Write tests
- [ ] Document for developers

**After Implementation:**
- [ ] Create developer guide
- [ ] Create capability registration guide
- [ ] Example MCP servers with capabilities
- [ ] Performance testing
- [ ] Security audit

---

## 🎯 SUCCESS CRITERIA

**Technical:**
- [ ] Auto-discovery finds all servers in /mcp_servers/
- [ ] Capabilities registered correctly
- [ ] Frank's rules enforced 100%
- [ ] No tool bypasses validation
- [ ] Zero code changes for new servers

**Usability:**
- [ ] Developer can add server without code changes
- [ ] User never sees tool details
- [ ] System explains decisions
- [ ] Performance acceptable (<100ms overhead)

**Safety:**
- [ ] Frank's CIM validates every capability use
- [ ] Bias checks work correctly
- [ ] Constraints enforced
- [ ] No unauthorized tool access

---

## 🔗 RELATED DOCUMENTS

- SEQUENTIAL_THINKING_WITH_CIM_v4.0.md - Main roadmap
- TRION_ARCHITECTURE_FOR_FRANK.md - Overall architecture
- Frank's original message (2026-01-12) - Capability concept
- ChatGPT brainstorm - Auto-registration idea

---

## 💡 KEY QUOTES

**Frank:**
> "MCP ist Ausführung. Frank ist Urteil. Capabilities sind Verantwortung."

**Danny:**
> "Frank's hartes Regelsystem = perfekt für MCP Tool Call Control!"

**Combined Vision:**
> "Users think in intents, Frank validates with rules, MCP executes safely."

---

## 📅 TIMELINE

**Design:** 2026-01-12 (TODAY)  
**Implementation:** Phase 2 (Week 2-3 of Jan 2026)  
**Testing:** Phase 2 (End of Week 3)  
**Deployment:** Phase 2 (Week 4)

---

*This is a design document - not yet implemented!*  
*To be refined during Phase 2 implementation.*  
*Priority: HIGH - Core architecture improvement*
