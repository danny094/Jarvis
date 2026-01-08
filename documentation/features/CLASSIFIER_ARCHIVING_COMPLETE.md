## CLASSIFIER PROMPTS ARCHIVIERUNG - 2026-01-05

### ✅ TASK COMPLETE: Option 1 - Verschieben + Dokumentieren

**Problem identified:**
- 7 .txt files in classifier/ directory
- NOT loaded by code (unused)
- Could cause confusion about system architecture

**Decision made:**
- Move to `system-prompts/` subdirectory
- Create comprehensive documentation
- Preserve for future consideration (Phase 4)

**Reasoning:**
ChatGPT's security argument accepted:
- Classifier = critical infrastructure
- Memory decisions must be stable
- Dynamic prompts = security risk
- Persona influence could corrupt memory

**BUT with nuance:**
- Style hints COULD be safe to influence
- Core logic MUST remain static
- Future integration possible with safeguards

---

### FILES MOVED:

**From:** `/classifier/*.txt`  
**To:** `/classifier/system-prompts/`

```
✅ prompt_system.txt (6.5 KB)
✅ system_core.txt (855 bytes)
✅ system_memory.txt (1.6 KB)
✅ system_meta_guard.txt (1.3 KB)
✅ system_persona.txt (982 bytes)
✅ system_safety.txt (1.3 KB)
✅ system_style_de.txt (569 bytes)
```

---

### DOCUMENTATION CREATED:

**1. system-prompts/README.md (288 lines, 6.9 KB)**

Content:
- ⚠️ Why files are NOT in use
- 🔒 Security architecture explanation
- 🎯 Core problem definition
- 🏗️ Current architecture (hardcoded)
- 📊 Comparison: Persona vs. Classifier
- 🔮 Future considerations (Phase 4)
- 🧪 Testing guidelines if modified
- ❓ FAQ section

Key Points:
- Classifier makes CRITICAL decisions
- Dynamic prompts = attack surface
- Persona affects OUTPUT (safe)
- Classifier affects INFRASTRUCTURE (must be stable)

**2. classifier/README.md (updated, 137 lines)**

Changes:
- Added warning about archived files
- Explained architecture decision
- Added "Do NOT" list
- Added "How to modify safely" guide
- Linked related systems
- Updated file structure

---

### ARCHITECTURE CLARIFICATION:

**Two Separate Systems:**

```
┌─────────────────────────────────────────┐
│  PERSONA SYSTEM (Dynamic)               │
│  ├─ Affects: Output style/tone          │
│  ├─ Risk: Low (user-facing only)        │
│  ├─ Hot-reload: ✅ Safe                 │
│  └─ Files: personas/*.txt               │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  CLASSIFIER SYSTEM (Static)             │
│  ├─ Affects: Memory decisions           │
│  ├─ Risk: Critical (system integrity)   │
│  ├─ Hot-reload: ❌ Dangerous            │
│  └─ Code: classifier.py (hardcoded)     │
└─────────────────────────────────────────┘
```

**Key Insight:**
- Persona = "How to speak" (safe to change)
- Classifier = "What to remember" (must be stable)

---

### FUTURE PHASE 4 CONSIDERATIONS:

**Possible Safe Integration:**

✅ **Could be dynamic (low risk):**
- Style hints (tone, verbosity)
- Language preferences
- Response formatting

❌ **Must stay static (high risk):**
- Memory layer logic (STM/MTM/LTM)
- Save/don't save decisions
- Metadata extraction rules
- Safety guardrails

**Hybrid Approach Concept:**
```python
def build_classifier_prompt():
    # ALWAYS static (secure)
    core = load_static_core_logic()
    
    # OPTIONALLY influenced (safe)
    style = persona.style_hints if safe_mode else default
    
    return core + style
```

**Required safeguards:**
- Core rules override persona
- Extensive testing
- Rollback mechanism
- Monitoring for corruption

---

### DECISION LOG:

**Date:** 2026-01-05  
**By:** Danny + Claude  
**Consulted:** ChatGPT (security argument)  
**Decision:** Option 1 - Archive + Document  
**Alternative:** Delete entirely (rejected)  
**Rationale:** Preserve for future, clarify architecture  

---

### TESTING STATUS:

✅ No code changes (only file movement)  
✅ No functional impact  
✅ Documentation only  
✅ System still runs identically  

**Verification:**
- classifier.py unchanged (hardcoded prompts)
- No tests broken
- No container restart needed
- System behavior identical

---

### FILES STRUCTURE AFTER:

```
classifier/
├── README.md                 ✅ Updated
├── classifier.py             (unchanged)
├── prompts.py               (unchanged)
├── 02_CLASSIFER.md          (unchanged)
└── system-prompts/          🆕 New directory
    ├── README.md            ✅ Created (288 lines)
    └── *.txt (7 files)      ✅ Moved from parent
```

---

### STATS:

**Documentation written:** 425 lines  
**Time spent:** ~30 minutes  
**Impact:** Architecture clarity +100%  
**Breaking changes:** None (0)  

---

### NEXT ACTIONS:

**Immediate:**
- ✅ Complete (no further action needed)

**Phase 4 (future):**
- Consider safe style-hint integration
- Design safeguard system
- Test extensively before production
- Document any changes

---

**Status:** ✅ COMPLETE  
**Branch:** main (documentation only)  
**Commit message suggestion:**
```
docs: Archive unused classifier prompt files

- Move classifier/*.txt to system-prompts/ subdirectory
- Add comprehensive README explaining why static
- Update classifier/README.md with architecture decision
- Preserve for future Phase 4 consideration

Reasoning: Classifier must be static for security.
Dynamic prompts could corrupt memory system.
See system-prompts/README.md for full explanation.
```
