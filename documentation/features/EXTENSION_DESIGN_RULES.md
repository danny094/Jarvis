# EXTENSION DESIGN RULES

**Purpose:** Guard rails for extending the Persona Management System  
**Version:** 1.0  
**Date:** 2026-01-06  
**Status:** Living Document

---

## 📖 WHY THESE RULES EXIST

From architecture review:
> "Du hast ein System gebaut, das man erweitern kann, ohne es neu zu verstehen."

These 5 rules keep it that way.

**Follow these rules → Extensions stay clean**  
**Break these rules → Architectural debt**

---

## 🎯 THE 5 GOLDEN RULES

### RULE #1: Metadata ≠ Behavior 🚨

**Principle:**
```
Persona behavior (.txt) NEVER depends on metadata (.meta.json)
```

**Why:**
- Prevents mixing concerns
- Keeps personas predictable
- Avoids hidden dependencies
- Maintains core principle: State ≠ Logic

**✅ CORRECT:**
```python
# Metadata for organization only
def filter_personas_by_tag(tag: str):
    personas = load_all_personas()
    metadata = load_all_metadata()
    return [p for p in personas if tag in metadata[p].tags]

# Display purposes
def show_persona_rating(name: str):
    metadata = get_metadata(name)
    return f"Rating: {metadata.rating}/5"
```

**❌ WRONG:**
```python
# NEVER let metadata influence behavior!
def load_persona_with_behavior(name: str):
    persona = load_persona(name)
    metadata = get_metadata(name)
    
    # ❌ BAD: Behavior depends on metadata
    if metadata.tag == "secure":
        persona += "\n[EXTRA SECURITY RULES]"
    
    if metadata.rating < 80:
        raise Exception("Low quality persona blocked")
    
    return persona
```

**Test Your Extension:**
```
Ask: "If I delete all .meta.json files, does the system still work?"
Answer should be: "Yes, just without tags/stats/organization"
```

---

### RULE #2: Use Stable IDs Internally

**Principle:**
```
Internal: UUID/Hash (stable)
External: Filename (user-friendly)
```

**Why:**
- Makes renames safe
- Enables DB migration
- Supports version tracking
- Prevents reference breaks

**✅ CORRECT:**
```python
# Generate stable ID
import hashlib

def get_persona_id(name: str) -> str:
    """Stable ID from name"""
    return hashlib.sha256(name.encode()).hexdigest()[:16]

# Store in metadata
{
  "id": "a3b7f8e9c2d1f4e5",  # ← Stable
  "name": "default",         # ← User sees this
  "filename": "default.txt"  # ← Can change
}

# Reference by ID internally
def track_usage(persona_id: str):
    stats[persona_id].increment()

# Show name to user
def display_persona(persona_id: str):
    meta = get_metadata_by_id(persona_id)
    return meta.name
```

**❌ WRONG:**
```python
# ❌ BAD: Using filename as ID
def track_usage(filename: str):
    stats[filename].increment()  # Breaks on rename!

# ❌ BAD: Direct filename references
def load_persona(filename: str):
    return open(f"personas/{filename}.txt")  # Fragile!
```

**Migration Path:**
```
Phase 3: Filenames only (OK for now)
Phase 4: Add stable IDs to metadata
Phase 5: Use IDs internally, keep filenames for display
```

---

### RULE #3: State in Files, Logic in Code

**Principle:**
```
Files = Data (State)
Code = Decisions (Logic)

Never mix!
```

**Why:**
- Separation of concerns
- Testable logic
- Versionable state
- Clear responsibility

**✅ CORRECT:**
```python
# State: Files
personas/default.txt          # ← Persona content
personas/default.meta.json    # ← Metadata

# Logic: Code
core/persona.py              # ← Load/Save/Validate
core/health_check.py         # ← Semantic validation
core/switch.py               # ← Activation logic

# Clear separation
def load_persona(name: str) -> str:
    """Read state from file"""
    return Path(f"personas/{name}.txt").read_text()

def validate_persona(content: str) -> dict:
    """Apply logic to state"""
    return check_rules(content)
```

**❌ WRONG:**
```python
# ❌ BAD: Logic in files
personas/default.txt:
  [IDENTITY]
  name: default
  if_user_is_admin: apply_extra_rules  # ← Logic in file!

# ❌ BAD: State in code
PERSONA_CONTENT = """
[IDENTITY]
name: hardcoded
"""  # ← State in code!
```

**Rule of Thumb:**
```
If it's data → File
If it's a decision → Code
If it configures behavior → File
If it validates/processes → Code
```

---

### RULE #4: New Features = New Endpoints

**Principle:**
```
Don't modify existing endpoints
Add new ones
```

**Why:**
- Backwards compatibility
- No breaking changes
- Versioning possible
- Clear API evolution

**✅ CORRECT:**
```python
# Existing endpoints stay unchanged
@router.get("/")
async def list_personas():
    # Don't modify this!
    return {"personas": list_all()}

# New feature = New endpoint
@router.get("/templates")  # ← NEW
async def list_templates():
    return {"templates": list_templates()}

@router.get("/{name}/history")  # ← NEW
async def get_history(name: str):
    return {"versions": get_versions(name)}

# Or version the API
@router.get("/v2/personas/")  # ← NEW VERSION
async def list_personas_v2():
    return {"personas": list_with_metadata()}
```

**❌ WRONG:**
```python
# ❌ BAD: Modifying existing endpoint
@router.get("/")
async def list_personas():
    # Changed response format!
    return {
        "data": list_all(),      # ← Was "personas"
        "metadata": load_meta()  # ← NEW field, breaks clients!
    }
```

**API Evolution:**
```
Phase 1: GET /api/personas/
Phase 2: GET /api/personas/validate (NEW)
Phase 3: GET /api/personas/templates (NEW)
Phase 4: GET /api/personas/{name}/history (NEW)

Old endpoints never break!
```

---

### RULE #5: UI is Pure Client

**Principle:**
```
No policy decisions in UI
No security logic in frontend
UI reads, backend decides
```

**Why:**
- Security
- Consistency
- Easier to test
- Single source of truth

**✅ CORRECT:**
```javascript
// Frontend: Display only
async function showPersona(name) {
  const persona = await api.getPersona(name);
  
  // Just display
  if (persona.protected) {
    showProtectedBadge();
  }
  
  if (persona.active) {
    highlightActive();
  }
}

// Backend decides
@router.delete("/{name}")
async def delete_persona(name: str):
    # ✅ Backend enforces protection
    if name == "default":
        raise HTTPException(400, "Protected")
    
    delete_file(name)
```

**❌ WRONG:**
```javascript
// ❌ BAD: Policy in frontend
async function deletePersona(name) {
  // ❌ Frontend decides protection
  if (name === 'default') {
    alert('Cannot delete default');
    return;  // ← Client-side only!
  }
  
  // ❌ Frontend decides security
  if (!user.isAdmin) {
    alert('No permission');
    return;  // ← Can be bypassed!
  }
  
  await api.delete(name);
}
```

**Security Example:**
```javascript
// ❌ WRONG: Validation in UI only
if (file.size > 10000) {
  alert('File too large');
  return;  // ← Can be bypassed!
}

// ✅ CORRECT: Backend validates
// Frontend just shows preview
if (file.size > 10000) {
  showWarning('File may be too large');
}
// Backend enforces the actual limit
```

**Rule of Thumb:**
```
UI should:
✅ Display data
✅ Collect input
✅ Show feedback
✅ Improve UX

UI should NOT:
❌ Enforce security
❌ Make policy decisions
❌ Validate business rules (backend does)
❌ Be single point of enforcement
```

---

## 🧪 HOW TO TEST YOUR EXTENSION

### Checklist for New Features:

**Before implementing, ask:**

1. **Metadata Rule:**
   - [ ] Does behavior depend on metadata? → ❌ Redesign
   - [ ] Is metadata purely organizational? → ✅ Good

2. **Stable IDs:**
   - [ ] Do I use filename as ID? → ⚠️ Add stable ID
   - [ ] Can persona be renamed safely? → ✅ Good

3. **State/Logic:**
   - [ ] Is logic in files? → ❌ Move to code
   - [ ] Is state in code? → ❌ Move to files
   - [ ] Clear separation? → ✅ Good

4. **API:**
   - [ ] Did I modify existing endpoint? → ❌ Add new one
   - [ ] Did I add new endpoint? → ✅ Good
   - [ ] Breaking change? → ❌ Version it

5. **UI/Backend:**
   - [ ] Does UI enforce policy? → ❌ Move to backend
   - [ ] Does backend decide? → ✅ Good
   - [ ] Can UI be bypassed? → ⚠️ Fix backend

---

## 🚨 RED FLAGS

If you see these patterns, STOP and reconsider:

### 🚩 Red Flag #1: Metadata in Logic
```python
if metadata.category == "admin":
    grant_permissions()  # ← RED FLAG!
```

### 🚩 Red Flag #2: Filename as Key
```python
stats[filename] = count  # ← RED FLAG! Use ID!
```

### 🚩 Red Flag #3: Logic in Files
```
personas/default.txt:
if user_type == "admin": ...  # ← RED FLAG!
```

### 🚩 Red Flag #4: Modifying Old Endpoints
```python
# Changing response format
return {"data": ...}  # ← RED FLAG! Was {"personas": ...}
```

### 🚩 Red Flag #5: Policy in Frontend
```javascript
if (!user.isAdmin) return;  # ← RED FLAG! Backend must enforce!
```

---

## 📚 EXAMPLES BY PHASE

### Phase 3 Features (Follow All Rules):
```
✅ Upload: Backend validates, UI displays
✅ Delete: Backend protects, UI shows state
✅ Edit: Files hold state, code validates
✅ Switch: Backend decides, UI reflects
✅ Health Check: Logic in code, results displayed
```

### Phase 4 Features (Add Stable IDs):
```
✅ Tags: Metadata only, no behavior impact
✅ Templates: New endpoint, files + logic separation
✅ Duplicate: Uses stable IDs, new endpoint
✅ Stats: Metadata, displayed only
```

### Phase 5+ Features (Watch for Drift):
```
✅ Version History: Files for versions, code for logic
✅ Search: Backend searches, UI displays
⚠️ AI Generate: Needs governance (complex!)
```

---

## 🔄 WHEN TO UPDATE THESE RULES

**Add new rule when:**
- Pattern causes problems in 2+ features
- Architecture principle violated repeatedly
- New pattern emerges consistently

**Don't add rule for:**
- One-off situations
- Obvious good practices
- Already covered by existing rules

**Review frequency:**
- After each major phase
- When architectural problems arise
- Before complex features (AI Generate, Multi-User)

---

## 💡 PHILOSOPHY

From external review:
> "Ein System, das man erweitern kann, ohne es neu zu verstehen."

**These rules maintain that property.**

**Key Insight:**
```
Good architecture = Constraints that enable freedom

These 5 rules are constraints.
But they give you freedom to extend safely.
```

---

## ✅ QUICK REFERENCE CARD

```
╔═══════════════════════════════════════════════╗
║  EXTENSION DESIGN RULES - QUICK REFERENCE     ║
╠═══════════════════════════════════════════════╣
║                                               ║
║  #1: Metadata ≠ Behavior                     ║
║      .txt defines, .meta.json organizes      ║
║                                               ║
║  #2: Stable IDs Internally                   ║
║      UUID inside, name outside               ║
║                                               ║
║  #3: State in Files, Logic in Code           ║
║      Files = Data, Code = Decisions          ║
║                                               ║
║  #4: New Features = New Endpoints            ║
║      Add, don't modify                       ║
║                                               ║
║  #5: UI is Pure Client                       ║
║      Display, don't decide                   ║
║                                               ║
╚═══════════════════════════════════════════════╝
```

---

## 📖 RELATED DOCUMENTATION

- **Architecture Review:** `ARCHITECTURE_REVIEW.md`
- **Phase 3 Plan:** `PHASE_3_PLAN.md`
- **API Reference:** `/documentation/API_REFERENCE.md`

---

**Last Updated:** 2026-01-06  
**Version:** 1.0  
**Status:** Active  
**Enforcement:** All phases 3+
