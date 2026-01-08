# PHASE 3: FRONTEND UI - ARBEITSPLAN (EXTENDED)

**Status:** 📋 PLANNED  
**Start Date:** TBD  
**Estimated Duration:** 10-11 hours  
**Approach:** Hybrid (Dropdown + Modal)  
**Extensions:** ✅ Diff Preview + ✅ Health Check

---

## 🎯 ZIELE PHASE 3

### ✅ MUST HAVE (Phase 3)
1. **Persona wechseln** (Dropdown im Header)
2. **Persona hochladen** (File Upload)
3. **Persona bearbeiten** (Inline Editor)
4. **Persona löschen** (mit Bestätigung)
5. **Persona exportieren/downloaden** (Backup)
6. **Validation Preview** (Feedback beim Upload/Edit)
7. **How-To Erklärung** (Hilfe-Section)
8. **🆕 Diff Preview** (Änderungen vor Save anzeigen) ← NEU!
9. **🆕 Health Check** (Semantische Validation) ← NEU!

### 🔮 NICE TO HAVE (Phase 4)
10. **Duplicate Persona** (Kopie erstellen)
11. **Preview Mode** (Test-Chat ohne Aktivierung)

---

## 🆕 NEUE FEATURES ERKLÄRT

### FEATURE 8: Diff Preview 📊

**Problem:** User weiß nicht was sich ändert beim Edit
**Lösung:** Zeige Diff (alt vs neu) vor dem Speichern

**UI:**
```
┌─────────────────────────────────────────┐
│ Changes Preview:                        │
├─────────────────────────────────────────┤
│ --- Original                            │
│ +++ Your Changes                        │
│                                         │
│ - tone: formal                          │
│ + tone: technical                       │
│                                         │
│ - verbosity: detailed                   │
│ + verbosity: concise                    │
│                                         │
│ + [NEW] 3. Focus on code quality        │
└─────────────────────────────────────────┘
[Cancel] [Apply Changes]
```

**Value:**
- ✅ Verhindert "warum verhält sich Jarvis anders"
- ✅ Transparenz bei Änderungen
- ✅ Impliziter Backup-Schutz
- ✅ Confidence-Boost beim Edit

**Implementation:**
```javascript
// Use diff library (e.g., diff-match-patch)
import * as Diff from 'diff';

function showDiffPreview(oldContent, newContent) {
  const diff = Diff.diffLines(oldContent, newContent);
  
  let html = '<div class="diff-preview">';
  diff.forEach(part => {
    const color = part.added ? 'green' : 
                  part.removed ? 'red' : 'gray';
    const prefix = part.added ? '+' :
                   part.removed ? '-' : ' ';
    html += `<div class="text-${color}">${prefix} ${part.value}</div>`;
  });
  html += '</div>';
  
  return html;
}
```

**When to show:**
- Before saving edited persona
- When uploading file with existing name

---

### FEATURE 9: Health Check ✅

**Problem:** User kann syntaktisch valide, aber semantisch schlechte Personas erstellen
**Lösung:** Backend prüft semantische Qualität + gibt Warnings/Errors

**Backend Changes:**
```python
# core/persona.py - NEW FUNCTION
def validate_persona_health(content: str) -> dict:
    """
    Semantic validation of persona content.
    Returns warnings and errors.
    """
    warnings = []
    errors = []
    
    # Check for recommended sections
    if "[RULES]" not in content:
        warnings.append("No [RULES] section found - behavior may be unpredictable")
    
    if "[PERSONALITY]" not in content:
        warnings.append("No [PERSONALITY] section - responses may be generic")
    
    if "[STYLE]" not in content:
        warnings.append("No [STYLE] section - tone may be inconsistent")
    
    # Check for dangerous patterns (jailbreak attempts)
    dangerous_patterns = [
        "ignore previous",
        "disregard instructions",
        "forget your rules"
    ]
    
    for pattern in dangerous_patterns:
        if pattern.lower() in content.lower():
            errors.append(f"Dangerous pattern detected: '{pattern}'")
    
    # Check name field format
    name_match = re.search(r'name:\s*(\w+)', content)
    if name_match:
        name = name_match.group(1)
        if len(name) < 2:
            warnings.append("Persona name is very short")
        if len(name) > 50:
            errors.append("Persona name too long (max 50 chars)")
    
    # Check for empty sections
    sections = ["[IDENTITY]", "[PERSONALITY]", "[STYLE]", "[RULES]"]
    for i, section in enumerate(sections):
        if section in content:
            # Check if next section is immediately after (empty section)
            next_section = sections[i+1] if i+1 < len(sections) else None
            if next_section and content.find(next_section) - content.find(section) < 20:
                warnings.append(f"{section} section appears empty")
    
    return {
        "valid": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "score": calculate_health_score(warnings, errors)
    }

def calculate_health_score(warnings, errors):
    """Calculate health score 0-100"""
    score = 100
    score -= len(errors) * 25  # Each error -25
    score -= len(warnings) * 10  # Each warning -10
    return max(0, score)
```

**API Endpoint:**
```python
# maintenance/persona_routes.py - NEW ENDPOINT

@router.post("/validate")
async def validate_persona_health(file: UploadFile):
    """
    Validate persona health without saving.
    Returns semantic validation results.
    """
    try:
        content = await file.read()
        content_str = content.decode('utf-8')
        
        # Basic validation first
        if not content_str or len(content_str) > 10240:
            raise HTTPException(400, "Invalid file size")
        
        # Health check
        from core.persona import validate_persona_health
        health = validate_persona_health(content_str)
        
        return {
            "valid": health["valid"],
            "warnings": health["warnings"],
            "errors": health["errors"],
            "score": health["score"]
        }
        
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 encoded")
    except Exception as e:
        log_error(f"[PersonaAPI] Health check error: {e}")
        raise HTTPException(500, "Health check failed")
```

**Frontend UI:**
```
Health Check Results:
┌─────────────────────────────────────────┐
│ Score: 70/100 ⚠️                         │
├─────────────────────────────────────────┤
│ ✅ Contains [IDENTITY] section          │
│ ✅ Has 'name' field                     │
│ ⚠️  No [RULES] section found            │
│ ⚠️  No [PERSONALITY] section            │
│ ✅ No dangerous patterns                │
├─────────────────────────────────────────┤
│ Recommendation:                         │
│ Add [RULES] and [PERSONALITY] sections  │
│ for better behavior consistency.        │
└─────────────────────────────────────────┘
[Fix Issues] [Upload Anyway]
```

**Value:**
- ✅ Prevents poor personas early
- ✅ Educates user on best practices
- ✅ Security: Detects jailbreak attempts
- ✅ Quality: Ensures complete personas

**Implementation:**
```javascript
async function validatePersonaHealth(file) {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch('/api/personas/validate', {
    method: 'POST',
    body: formData
  });
  
  const health = await response.json();
  showHealthCheck(health);
  return health;
}

function showHealthCheck(health) {
  let html = `
    <div class="health-check">
      <h4>Health Check Results: ${health.score}/100</h4>
      ${health.valid ? '✅' : '❌'} Overall: ${health.valid ? 'Valid' : 'Invalid'}
      
      ${health.errors.map(e => `<div class="error">❌ ${e}</div>`).join('')}
      ${health.warnings.map(w => `<div class="warning">⚠️  ${w}</div>`).join('')}
    </div>
  `;
  
  document.getElementById('health-output').innerHTML = html;
}
```

---

## 📐 UI STRUCTURE PLAN

```
┌─────────────────────────────────────────────────────────────┐
│ Header                                                      │
│ [Logo] Jarvis        [Maint] [Tools] [Debug] [⚙️] [Model▼] │
│                                              └─► HIER!      │
└─────────────────────────────────────────────────────────────┘
                                                 │
                                                 ▼
                              ┌─────────────────────────────┐
                              │ 👤 Persona Management       │ ◄─ Click
                              │ 🔐 API Keys (disabled)      │
                              │ ℹ️  About Jarvis            │
                              └─────────────────────────────┘
                                                 │
                                                 ▼ Click "Persona Management"
┌─────────────────────────────────────────────────────────────────────┐
│  👤 Persona Management                                          [❌] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  📍 Active Persona: [Default ▼]  [Switch]                          │
│                                                                     │
│  ─────────────────────────────────────────────────────────────────│
│                                                                     │
│  📋 Available Personas (2)                                          │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ ✓ Default (Active) [Health: 85/100 ✅]                      │  │
│  │   Created: 2026-01-04  Size: 1.4 KB                         │  │
│  │   [✏️ Edit] [💾 Download] [❌ Protected]                     │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │   DevBot [Health: 70/100 ⚠️]                                │  │
│  │   Created: 2026-01-06  Size: 380 B                          │  │
│  │   [✅ Activate] [✏️ Edit] [💾 Download] [🗑️ Delete]          │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ─────────────────────────────────────────────────────────────────│
│                                                                     │
│  📤 Upload New Persona                                              │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ [Choose File: my_persona.txt]           [✅ Validate]       │  │
│  │                                                              │  │
│  │ Health Check: 85/100 ✅                                      │  │
│  │ ✅ All required sections present                            │  │
│  │ ⚠️  Tone might be too permissive                            │  │
│  │                                                              │  │
│  │                                       [📤 Upload]            │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ❓ How to create a Persona? [Show Guide]                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 IMPLEMENTATION STEPS (UPDATED)

### STEP 1: Settings Dropdown (30 min)
[Same as before]

### STEP 2: Modal Shell (30 min)
[Same as before]

### STEP 3: PersonaManager Class (45 min)
[Same as before]

### STEP 4: Persona List Display (45 min)
**UPDATED:** Add health score display
- [ ] Show health score badge on each card
- [ ] Color code: Green (80+), Yellow (60-79), Red (<60)

### STEP 5: Switch Persona (30 min)
[Same as before]

### STEP 6: Upload New Persona (60 min)
[Same as before]

### STEP 7: Download Persona (20 min)
[Same as before]

### STEP 8: Delete Persona (30 min)
[Same as before]

### STEP 9: Edit Persona (60 min)
[Same as before]

---

### 🆕 STEP 9.5: Diff Preview (45 min)

**NEW STEP!**

**Tasks:**
- [ ] Install diff library (or use CDN)
- [ ] Create diff preview component
- [ ] Hook into edit save flow
- [ ] Show "Changes Preview" before save
- [ ] Add "Apply Changes" button
- [ ] Style diff (red/green highlighting)

**Files:**
- `index.html` (diff preview template)
- `static/js/persona-manager.js` (diff logic)

**Dependencies:**
```html
<!-- Add to index.html -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/diff_match_patch/20121119/diff_match_patch.js"></script>
```

**Implementation:**
```javascript
function showDiffPreview(oldContent, newContent, onConfirm) {
  const dmp = new diff_match_patch();
  const diff = dmp.diff_main(oldContent, newContent);
  dmp.diff_cleanupSemantic(diff);
  
  // Create HTML
  const diffHtml = diff.map(part => {
    const [op, text] = part;
    const className = op === 1 ? 'diff-add' :
                     op === -1 ? 'diff-remove' : 'diff-same';
    return `<span class="${className}">${escapeHtml(text)}</span>`;
  }).join('');
  
  // Show modal with diff
  showModal('Changes Preview', diffHtml, [
    { text: 'Cancel', onClick: closeModal },
    { text: 'Apply Changes', onClick: () => {
      onConfirm();
      closeModal();
    }}
  ]);
}

// Usage in edit save:
async function savePersonaEdit(name, newContent) {
  // Load original
  const original = await getPersona(name);
  
  // Show diff
  showDiffPreview(original.content, newContent, async () => {
    // Actually save
    await uploadPersona(createFileFromContent(name, newContent));
  });
}
```

**CSS:**
```css
.diff-add {
  background: #065f4622;
  color: #10b981;
}
.diff-remove {
  background: #7f1d1d22;
  color: #f87171;
  text-decoration: line-through;
}
.diff-same {
  color: #9ca3af;
}
```

**Test:**
- [ ] Diff shows correctly
- [ ] Colors distinguish add/remove
- [ ] Apply saves changes
- [ ] Cancel discards

---

### STEP 10: Validation Preview (30 min)
[Same as before - basic validation]

---

### 🆕 STEP 10.5: Backend Health Check (60 min)

**NEW BACKEND STEP!**

**Tasks:**
- [ ] Add `validate_persona_health()` to `core/persona.py`
- [ ] Add semantic checks (sections, patterns)
- [ ] Add health score calculation
- [ ] Add `/validate` endpoint to `persona_routes.py`
- [ ] Test with various personas
- [ ] Document warnings/errors

**Files:**
- `core/persona.py` (new function)
- `maintenance/persona_routes.py` (new endpoint)

**Implementation:** [See FEATURE 9 above]

**Test:**
- [ ] Valid persona returns score 80+
- [ ] Missing sections add warnings
- [ ] Dangerous patterns add errors
- [ ] API endpoint returns correct JSON

---

### 🆕 STEP 10.6: Frontend Health Check UI (45 min)

**NEW FRONTEND STEP!**

**Tasks:**
- [ ] Add "Validate" button to upload section
- [ ] Call `/api/personas/validate` endpoint
- [ ] Show health check results UI
- [ ] Display score with color coding
- [ ] List warnings and errors
- [ ] Add health score badges to persona cards
- [ ] Cache health scores

**Files:**
- `index.html` (health check display)
- `static/js/persona-manager.js` (API calls)

**Implementation:**
```javascript
async function validateAndShowHealth(file) {
  // Show loading
  showLoading('Validating...');
  
  // Call API
  const health = await validatePersonaHealth(file);
  
  // Show results
  showHealthResults(health);
  
  // Enable/disable upload based on result
  document.getElementById('upload-btn').disabled = !health.valid;
}

function showHealthResults(health) {
  const scoreColor = health.score >= 80 ? 'green' :
                     health.score >= 60 ? 'yellow' : 'red';
  
  let html = `
    <div class="health-results">
      <div class="health-score ${scoreColor}">
        Score: ${health.score}/100 ${getScoreEmoji(health.score)}
      </div>
      
      ${health.errors.length > 0 ? `
        <div class="errors">
          ${health.errors.map(e => `<div>❌ ${e}</div>`).join('')}
        </div>
      ` : ''}
      
      ${health.warnings.length > 0 ? `
        <div class="warnings">
          ${health.warnings.map(w => `<div>⚠️  ${w}</div>`).join('')}
        </div>
      ` : ''}
      
      ${health.valid ? 
        '<div class="success">✅ Ready to upload</div>' :
        '<div class="error">❌ Fix errors before uploading</div>'
      }
    </div>
  `;
  
  document.getElementById('health-output').innerHTML = html;
}

function getScoreEmoji(score) {
  if (score >= 90) return '🌟';
  if (score >= 80) return '✅';
  if (score >= 60) return '⚠️';
  return '❌';
}
```

**Test:**
- [ ] Validate button works
- [ ] Health results display correctly
- [ ] Score color matches value
- [ ] Errors block upload
- [ ] Warnings allow upload

---

### STEP 11: How-To Guide (30 min)
[Same as before]

### STEP 12: Polish & Testing (60 min)
**UPDATED:** Extended testing for new features
- [ ] Test diff preview with various changes
- [ ] Test health check with good/bad personas
- [ ] Test health score display
- [ ] End-to-end flows
- [ ] Mobile responsive
- [ ] Cross-browser

---

## 📊 TIME ESTIMATION (UPDATED)

| Step | Task | Time | Total |
|------|------|------|-------|
| 1 | Settings Dropdown | 30m | 0:30 |
| 2 | Modal Shell | 30m | 1:00 |
| 3 | PersonaManager Class | 45m | 1:45 |
| 4 | Persona List + Health Badge | 45m | 2:30 |
| 5 | Switch | 30m | 3:00 |
| 6 | Upload | 60m | 4:00 |
| 7 | Download | 20m | 4:20 |
| 8 | Delete | 30m | 4:50 |
| 9 | Edit | 60m | 5:50 |
| **9.5** | **🆕 Diff Preview** | **45m** | **6:35** |
| 10 | Validation | 30m | 7:05 |
| **10.5** | **🆕 Backend Health Check** | **60m** | **8:05** |
| **10.6** | **🆕 Frontend Health UI** | **45m** | **8:50** |
| 11 | How-To | 30m | 9:20 |
| 12 | Polish & Testing | 60m | 10:20 |

**Total Estimated Time:** ~10.5 hours  
**Realistic Time:** ~11-12 hours (with breaks & debugging)

---

## ✅ TESTING CHECKLIST (EXTENDED)

### Functional Tests:
- [ ] Settings dropdown opens/closes
- [ ] Modal opens/closes
- [ ] Persona list loads
- [ ] Active persona shown
- [ ] Switch persona works
- [ ] Upload valid file works
- [ ] Upload invalid file rejected
- [ ] Download works
- [ ] Delete works (with confirmation)
- [ ] Cannot delete default
- [ ] Cannot delete active
- [ ] Edit loads content
- [ ] Edit saves changes
- [ ] **🆕 Diff preview shows before save**
- [ ] **🆕 Diff accurately shows changes**
- [ ] Validation shows correctly
- [ ] **🆕 Health check validates persona**
- [ ] **🆕 Health score displays on cards**
- [ ] **🆕 Warnings don't block upload**
- [ ] **🆕 Errors block upload**
- [ ] Help guide expands

### Edge Cases:
- [ ] Empty persona list
- [ ] Network error handling
- [ ] Large files rejected
- [ ] Invalid filenames rejected
- [ ] Duplicate names handled
- [ ] Special characters in names
- [ ] **🆕 Diff with no changes**
- [ ] **🆕 Diff with only whitespace changes**
- [ ] **🆕 Health check with empty file**
- [ ] **🆕 Health check with jailbreak attempt**

---

## 📚 BACKEND CHANGES REQUIRED

### File: `core/persona.py`

**Add new function:**
```python
def validate_persona_health(content: str) -> dict:
    """Semantic validation of persona content"""
    # [See implementation in FEATURE 9 section above]
```

### File: `maintenance/persona_routes.py`

**Add new endpoint:**
```python
@router.post("/validate")
async def validate_persona_health(file: UploadFile):
    """Validate persona health without saving"""
    # [See implementation in FEATURE 9 section above]
```

### Testing Backend:
```bash
# Test health check
curl -X POST http://localhost:8100/api/personas/validate \
  -F "file=@test_persona.txt"

# Expected response:
{
  "valid": true,
  "warnings": ["No [RULES] section found"],
  "errors": [],
  "score": 80
}
```

---

## 🎯 SUCCESS CRITERIA (UPDATED)

Phase 3 is COMPLETE when:
- [ ] All 12 steps + 3 new sub-steps implemented
- [ ] All functional tests pass (23 tests)
- [ ] All edge cases handled (10+ cases)
- [ ] Mobile responsive
- [ ] No console errors
- [ ] Documentation updated
- [ ] **🆕 Diff preview working**
- [ ] **🆕 Health check backend deployed**
- [ ] **🆕 Health scores visible**
- [ ] User can:
  - [ ] Switch personas
  - [ ] Upload new personas with validation
  - [ ] Edit existing personas with diff preview
  - [ ] Download personas
  - [ ] Delete personas
  - [ ] See validation feedback
  - [ ] See health scores
  - [ ] Read help guide

---

## 🔮 PHASE 4 PREVIEW

After Phase 3, next features:
- [ ] Duplicate Persona (use Diff + Edit)
- [ ] Preview Mode (test without activation)
- [ ] Persona Templates (pre-made personas)
- [ ] Bulk Import/Export
- [ ] Version History
- [ ] Persona Sharing (export link)

---

**Last Updated:** 2026-01-06 (Extended with Diff + Health Check)  
**Status:** Ready to Start  
**Total Time:** ~10-12 hours  
**Next Action:** Begin Step 1 (Settings Dropdown)
- `static/js/persona-manager.js` (create)

**Test:**
- Click "Persona Management" opens modal
- Click X closes modal
- ESC closes modal
- Click outside closes modal

---

### STEP 3: PersonaManager Class (45 min)

**Tasks:**
- [ ] Create PersonaManager class
- [ ] Implement API wrapper methods:
  - [ ] listAll()
  - [ ] getPersona(name)
  - [ ] upload(file)
  - [ ] switch(name)
  - [ ] delete(name)
- [ ] Add error handling
- [ ] Add loading states
- [ ] Test all API calls

**Files:**
- `static/js/persona-manager.js`

**Test:**
- All API methods work
- Errors are caught and displayed
- Loading indicators shown

---

### STEP 4: Persona List Display (45 min)

**Tasks:**
- [ ] Load persona list on modal open
- [ ] Create persona card template
- [ ] Show active indicator
- [ ] Display metadata (date, size)
- [ ] Add action buttons (disabled for now)
- [ ] Handle empty state
- [ ] Add refresh function

**Files:**
- `index.html` (persona list section)
- `static/js/persona-manager.js`

**Test:**
- Personas load and display
- Active persona highlighted
- Metadata shows correctly
- Empty state works

---

### STEP 5: Switch Persona (30 min)

**Tasks:**
- [ ] Add active persona dropdown
- [ ] Populate with persona list
- [ ] Add "Switch" button
- [ ] Implement switch logic
- [ ] Show success toast
- [ ] Refresh modal after switch
- [ ] Update active indicator

**Files:**
- `static/js/persona-manager.js`

**Test:**
- Dropdown shows all personas
- Switch works
- Toast notification appears
- Modal updates active status

---

### STEP 6: Upload New Persona (60 min)

**Tasks:**
- [ ] Add file input
- [ ] Add upload button
- [ ] Implement client validation
- [ ] Show validation preview
- [ ] Implement upload function
- [ ] Show progress (optional)
- [ ] Handle success/error
- [ ] Refresh list after upload

**Files:**
- `index.html` (upload section)
- `static/js/persona-manager.js`
- `static/js/validation.js` (create)

**Test:**
- File selection works
- Validation runs
- Invalid files rejected
- Valid files upload
- List refreshes

---

### STEP 7: Download Persona (20 min)

**Tasks:**
- [ ] Add download button to cards
- [ ] Implement download function
- [ ] Fetch persona content
- [ ] Create blob download
- [ ] Show success toast

**Files:**
- `static/js/persona-manager.js`

**Test:**
- Download button works
- File downloads with correct name
- Content is correct

---

### STEP 8: Delete Persona (30 min)

**Tasks:**
- [ ] Add delete button to cards
- [ ] Create confirmation dialog
- [ ] Implement delete logic
- [ ] Check protections (default, active)
- [ ] Show success/error
- [ ] Refresh list after delete

**Files:**
- `static/js/persona-manager.js`

**Test:**
- Cannot delete default
- Cannot delete active
- Confirmation required
- Delete works for others
- List refreshes

---

### STEP 9: Edit Persona (60 min)

**Tasks:**
- [ ] Add edit button to cards
- [ ] Create inline editor UI
- [ ] Load persona content
- [ ] Add textarea with syntax
- [ ] Implement validation on edit
- [ ] Add save function
- [ ] Add cancel function
- [ ] Show success/error

**Files:**
- `index.html` (editor template)
- `static/js/persona-manager.js`
- `static/js/validation.js`

**Test:**
- Edit opens inline
- Content loads correctly
- Validation works
- Save updates persona
- Cancel discards changes

---

### STEP 10: Validation Preview (30 min)

**Tasks:**
- [ ] Create validation UI component
- [ ] Validate on file select
- [ ] Validate on content edit
- [ ] Show check/cross for each rule
- [ ] Show overall status
- [ ] Disable upload if invalid

**Files:**
- `static/js/validation.js`

**Test:**
- Validation shows on file select
- Validation updates on edit
- Invalid content blocks upload
- Valid content allows upload

---

### STEP 11: How-To Guide (30 min)

**Tasks:**
- [ ] Add collapsible section
- [ ] Write guide content
- [ ] Add example format
- [ ] Add "Download Template" button
- [ ] Add link to README.md
- [ ] Implement expand/collapse

**Files:**
- `index.html` (help section)

**Test:**
- Section expands/collapses
- Download template works
- Links work
- Content helpful

---

### STEP 12: Polish & Testing (45 min)

**Tasks:**
- [ ] Add loading indicators
- [ ] Add toast notifications
- [ ] Test all flows end-to-end
- [ ] Test error cases
- [ ] Test edge cases
- [ ] Mobile responsive check
- [ ] Cross-browser test
- [ ] Fix bugs

**Files:**
- All files

**Test:**
- Complete user flows work
- No console errors
- Mobile works
- All browsers work

---

## 📊 TIME ESTIMATION

| Step | Task | Time | Total |
|------|------|------|-------|
| 1 | Settings Dropdown | 30m | 0:30 |
| 2 | Modal Shell | 30m | 1:00 |
| 3 | PersonaManager Class | 45m | 1:45 |
| 4 | Persona List | 45m | 2:30 |
| 5 | Switch | 30m | 3:00 |
| 6 | Upload | 60m | 4:00 |
| 7 | Download | 20m | 4:20 |
| 8 | Delete | 30m | 4:50 |
| 9 | Edit | 60m | 5:50 |
| 10 | Validation | 30m | 6:20 |
| 11 | How-To | 30m | 6:50 |
| 12 | Polish | 45m | 7:35 |

**Total Estimated Time:** ~7.5 hours
**Realistic Time:** ~8-10 hours (with breaks & debugging)

---

## ✅ TESTING CHECKLIST

### Functional Tests:
- [ ] Settings dropdown opens/closes
- [ ] Modal opens/closes
- [ ] Persona list loads
- [ ] Active persona shown
- [ ] Switch persona works
- [ ] Upload valid file works
- [ ] Upload invalid file rejected
- [ ] Download works
- [ ] Delete works (with confirmation)
- [ ] Cannot delete default
- [ ] Cannot delete active
- [ ] Edit loads content
- [ ] Edit saves changes
- [ ] Validation shows correctly
- [ ] Help guide expands

### Edge Cases:
- [ ] Empty persona list
- [ ] Network error handling
- [ ] Large files rejected
- [ ] Invalid filenames rejected
- [ ] Duplicate names handled
- [ ] Special characters in names
- [ ] Very long persona names
- [ ] Corrupted file content

### UX Tests:
- [ ] Loading indicators show
- [ ] Success toasts appear
- [ ] Error messages clear
- [ ] Buttons disabled when appropriate
- [ ] Keyboard navigation works
- [ ] ESC closes modals
- [ ] Click outside closes

### Cross-Platform:
- [ ] Desktop Chrome
- [ ] Desktop Firefox
- [ ] Desktop Safari
- [ ] Mobile Chrome
- [ ] Mobile Safari
- [ ] Tablet view

---

## 🎨 DESIGN TOKENS

**Colors (from existing theme):**
```css
--bg-dark: #0a0a0a
--card-dark: #1a1a1a
--border-dark: #2a2a2a
--hover-dark: #333333
--accent-primary: #3b82f6
--accent-secondary: #8b5cf6
--text-primary: #ffffff
--text-secondary: #9ca3af
--success: #10b981
--error: #f87171
--warning: #fbbf24
```

**Icons (Lucide):**
- Settings: `settings`
- Persona: `user`
- Edit: `edit-3`
- Download: `download`
- Delete: `trash-2`
- Upload: `upload`
- Switch: `refresh-cw`
- Check: `check`
- X: `x`
- Info: `info`

**Spacing:**
- Modal: `max-w-3xl`, `p-6`
- Cards: `p-4`, `gap-2`
- Buttons: `px-4 py-2`

---

## 🐛 KNOWN CHALLENGES

### Challenge 1: File Upload Progress
**Problem:** Large files might take time
**Solution:** Show spinner during upload
**Priority:** LOW (10KB limit makes this rare)

### Challenge 2: Content Validation
**Problem:** Need to parse persona format
**Solution:** Simple regex checks + server validation
**Priority:** MEDIUM

### Challenge 3: Edit Conflicts
**Problem:** Multiple edits at once
**Solution:** Not supported in MVP, single-user system
**Priority:** LOW (Phase 4)

### Challenge 4: Mobile UX
**Problem:** Modal might be too large on mobile
**Solution:** Responsive design, scroll if needed
**Priority:** MEDIUM

---

## 📚 DOCUMENTATION TO UPDATE

After Phase 3 completion:
- [ ] Update `/documentation/features/PHASE_3_COMPLETE.md`
- [ ] Add screenshots to docs
- [ ] Update user guide (if exists)
- [ ] Update README with UI instructions

---

## 🎯 SUCCESS CRITERIA

Phase 3 is COMPLETE when:
- [ ] All 11 steps implemented
- [ ] All functional tests pass
- [ ] All edge cases handled
- [ ] Mobile responsive
- [ ] No console errors
- [ ] Documentation updated
- [ ] User can:
  - [ ] Switch personas
  - [ ] Upload new personas
  - [ ] Edit existing personas
  - [ ] Download personas
  - [ ] Delete personas
  - [ ] See validation feedback
  - [ ] Read help guide

---

**Last Updated:** 2026-01-06  
**Status:** Ready to Start  
**Next Action:** Begin Step 1 (Settings Dropdown)
