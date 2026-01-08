# 🎭 PERSONA MANAGEMENT - IMPLEMENTATION GUIDE

**Feature:** Multi-Persona System mit WebUI Management  
**Version:** 1.0.0  
**Status:** 🚧 In Progress  
**Start Date:** 2026-01-04  
**Estimated Effort:** 12-16h

---

## 📋 QUICK OVERVIEW

**Was wird gebaut:**
- Multi-Persona Support (statt single persona.yaml)
- Persona Upload via WebUI
- Dynamisches Persona-Switching (Hot-Reload)
- Protected Base Persona (default.txt)
- Später: Classifier Integration

**Architektur-Änderungen:**
```
ALT: config/persona.yaml (single)
NEU: personas/*.txt (multiple) + API + UI
```

---

## ⚙️ TECHNISCHE ENTSCHEIDUNGEN

### ✅ Format: `.txt` (Plain Text)
**Begründung:**
- Einfacher für Non-Devs
- Keine YAML-Syntax-Errors
- Copy-Paste freundlich
- Trotzdem strukturiert via Sections

### ✅ Storage: `/personas/`
**Location:** `/DATA/AppData/MCP/Jarvis/Jarvis/personas/`
**Reason:** Neben config/, core/ → konsistent

### ✅ Hot-Reload: JA
**Method:** Bestehende `reload_persona()` Funktion erweitern
**Benefit:** Kein Container-Restart nötig

### ✅ Base Protection: JA
**File:** `default.txt` ist read-only
**Fallback:** Bei Persona-Error → default.txt laden

---

## 📐 PERSONA.TXT FORMAT

```txt
# Persona: [NAME]
# Description: [OPTIONAL]
# Version: 1.0

[IDENTITY]
name: Jarvis
role: Personal Assistant
language: deutsch
user_name: Danny

[PERSONALITY]
- freundlich
- hilfsbereit
- technisch versiert

[STYLE]
tone: locker aber respektvoll
verbosity: mittel

[RULES]
1. Keine persönlichen Daten erfinden
2. Ehrlich bei Unwissenheit
3. Memory nutzen für persönliche Fragen
4. Kurze Fragen = kurze Antworten

[PRIVACY]
- Keine sensiblen Daten in Beispielen
- Nur Danny's Daten verwenden
```

**Parser-Logic:** Simple Section-Based (kein komplexes YAML)

---

## 🏗️ IMPLEMENTATION PHASES

---

### 🟢 PHASE 1: Backend Foundation
**Duration:** 4-6h  
**Goal:** Core Persona System refactoring

#### 1.1 Ordner-Struktur erstellen ✅
```bash
/DATA/AppData/MCP/Jarvis/Jarvis/
├── personas/
│   ├── README.md          # Format Documentation
│   ├── default.txt        # Base Persona (protected)
│   └── .gitkeep
```

**Status:** ✅ ERLEDIGT (2026-01-04)

---

#### 1.2 README.md für personas/ schreiben
**File:** `/personas/README.md`

**Content:**
```markdown
# Persona Directory

This directory stores all available persona configurations.

## File Format
See default.txt for reference structure.

## Protected Files
- default.txt (cannot be deleted)

## Custom Personas
You can add custom .txt files here or upload via WebUI.
```

**Tasks:**
- [ ] README.md schreiben
- [ ] In Git committen

---

#### 1.3 default.txt migrieren
**Source:** `config/persona.yaml`  
**Target:** `personas/default.txt`

**Tasks:**
- [ ] YAML → .txt Format konvertieren
- [ ] default.txt erstellen
- [ ] Kompatibilität mit alter persona.py testen

**Script:**
```python
# Migration Helper (einmalig)
import yaml

# Load old YAML
with open('config/persona.yaml') as f:
    data = yaml.safe_load(f)

# Write new .txt
with open('personas/default.txt', 'w') as f:
    f.write(f"# Persona: {data['name']}\n")
    f.write(f"# Base persona for Jarvis\n\n")
    f.write("[IDENTITY]\n")
    f.write(f"name: {data['name']}\n")
    # ... etc
```

---

#### 1.4 core/persona.py erweitern
**File:** `core/persona.py`

**Neue Funktionen:**

```python
# Global State
_active_persona_name: str = "default"
_personas_dir = Path(__file__).parent.parent / "personas"

def list_personas() -> List[str]:
    """List all available persona files."""
    return [f.stem for f in _personas_dir.glob("*.txt")]

def load_persona(name: str = "default") -> Persona:
    """Load specific persona by name."""
    # ... implementation

def save_persona(name: str, content: str) -> bool:
    """Save new persona file."""
    # Validate, sanitize, write

def delete_persona(name: str) -> bool:
    """Delete persona (except default)."""
    if name == "default":
        raise ValueError("Cannot delete default persona")
    # ... delete file

def switch_persona(name: str) -> Persona:
    """Switch active persona (hot-reload)."""
    global _active_persona_name
    _active_persona_name = name
    return load_persona(name)

def get_active_persona_name() -> str:
    """Return currently active persona name."""
    return _active_persona_name

def parse_persona_txt(content: str) -> Dict:
    """Parse .txt format into dict."""
    # Section-based parser
    # [IDENTITY] → dict["identity"]
    # [RULES] → dict["rules"]
```

**Tasks:**
- [ ] `list_personas()` implementieren
- [ ] `load_persona(name)` umschreiben (.txt statt .yaml)
- [ ] `save_persona()` implementieren
- [ ] `delete_persona()` implementieren
- [ ] `switch_persona()` implementieren
- [ ] `parse_persona_txt()` implementieren
- [ ] Unit Tests schreiben (optional)

---

#### 1.5 Backward Compatibility
**Challenge:** Altes System nutzt noch `config/persona.yaml`

**Lösung:**
```python
# In load_persona()
def load_persona(name: str = "default") -> Persona:
    # Try new .txt first
    txt_path = _personas_dir / f"{name}.txt"
    if txt_path.exists():
        return _load_from_txt(txt_path)
    
    # Fallback to old YAML (temporary)
    yaml_path = CONFIG_PATH
    if yaml_path.exists():
        log_warn("[Persona] Using legacy persona.yaml")
        return _load_from_yaml(yaml_path)
    
    # Ultimate fallback
    return Persona({})
```

**Tasks:**
- [ ] Fallback-Logic implementieren
- [ ] Legacy-Warning loggen

---

#### 1.6 Phase 1 Testing
**Test Cases:**
- [ ] `list_personas()` gibt ["default"] zurück
- [ ] `load_persona("default")` funktioniert
- [ ] `save_persona("test", content)` erstellt test.txt
- [ ] `delete_persona("test")` löscht test.txt
- [ ] `delete_persona("default")` wirft Error
- [ ] `switch_persona("default")` funktioniert

**CLI Test Script:**
```python
from core.persona import list_personas, load_persona, save_persona

print("Available:", list_personas())
p = load_persona("default")
print("Loaded:", p.name)
```

---

### 🟡 PHASE 2: WebUI API Endpoints
**Duration:** 2-3h  
**Goal:** REST API für Persona-Management

#### 2.1 Neue Datei: persona_endpoints.py
**Location:** `adapters/Jarvis/persona_endpoints.py`

**Structure:**
```python
from fastapi import APIRouter, UploadFile, HTTPException
from core.persona import (
    list_personas, 
    load_persona,
    save_persona,
    delete_persona,
    switch_persona,
    get_active_persona_name
)

router = APIRouter(prefix="/api/personas", tags=["personas"])

@router.get("/")
async def get_all_personas():
    """List all available personas."""
    return {
        "personas": list_personas(),
        "active": get_active_persona_name()
    }

@router.get("/{name}")
async def get_persona(name: str):
    """Get specific persona content."""
    # Read file, return content

@router.post("/")
async def upload_persona(file: UploadFile):
    """Upload new persona file."""
    # Validate, save, return success

@router.put("/switch")
async def switch_active_persona(name: str):
    """Switch to different persona."""
    # Call switch_persona(), return success

@router.delete("/{name}")
async def delete_persona_endpoint(name: str):
    """Delete custom persona."""
    # Call delete_persona(), return success
```

**Tasks:**
- [ ] persona_endpoints.py erstellen
- [ ] GET / implementieren
- [ ] GET /{name} implementieren
- [ ] POST / implementieren (mit UploadFile)
- [ ] PUT /switch implementieren
- [ ] DELETE /{name} implementieren
- [ ] Error Handling (404, 400, 500)
- [ ] Input Validation (filename, size, format)

---

#### 2.2 Integration in main.py
**File:** `adapters/Jarvis/main.py`

**Changes:**
```python
from persona_endpoints import router as persona_router

app = FastAPI()
app.include_router(persona_router)
```

**Tasks:**
- [ ] Import hinzufügen
- [ ] Router registrieren
- [ ] Testen ob /api/personas/ erreichbar

---

#### 2.3 Phase 2 Testing
**Test mit curl/Postman:**
```bash
# List personas
curl http://localhost:8400/api/personas/

# Get default
curl http://localhost:8400/api/personas/default

# Upload new
curl -X POST http://localhost:8400/api/personas/ \
  -F "file=@my_persona.txt"

# Switch
curl -X PUT http://localhost:8400/api/personas/switch?name=default

# Delete
curl -X DELETE http://localhost:8400/api/personas/test
```

**Checklist:**
- [ ] GET / funktioniert
- [ ] GET /{name} funktioniert
- [ ] POST / (Upload) funktioniert
- [ ] PUT /switch funktioniert
- [ ] DELETE funktioniert
- [ ] Errors werden korrekt zurückgegeben

---

### 🔵 PHASE 3: Frontend UI
**Duration:** 3-4h  
**Goal:** WebUI für Persona-Management

#### 3.1 Neue Datei: personas.js
**Location:** `adapters/Jarvis/static/js/personas.js`

**Functions:**
```javascript
const PersonaManager = {
    async loadPersonas() {
        // Fetch /api/personas/
        // Populate dropdown
    },
    
    async switchPersona(name) {
        // PUT /api/personas/switch
        // Show notification
        // Reload UI
    },
    
    async uploadPersona(file) {
        // POST /api/personas/
        // Show progress
        // Reload list
    },
    
    async deletePersona(name) {
        // Confirm dialog
        // DELETE /api/personas/{name}
        // Reload list
    },
    
    async viewPersona(name) {
        // GET /api/personas/{name}
        // Show in modal/preview
    }
};
```

**Tasks:**
- [ ] personas.js erstellen
- [ ] loadPersonas() implementieren
- [ ] switchPersona() implementieren
- [ ] uploadPersona() implementieren
- [ ] deletePersona() implementieren
- [ ] viewPersona() implementieren (optional)

---

#### 3.2 UI Components in index.html
**Location:** `adapters/Jarvis/index.html`

**Widget Structure:**
```html
<!-- Persona Selector (Top Bar) -->
<div class="persona-widget">
    <label>Persona:</label>
    <select id="persona-selector">
        <option value="default">Default</option>
        <!-- Dynamisch geladen -->
    </select>
    <button id="manage-personas" title="Manage Personas">⚙️</button>
</div>

<!-- Persona Management Modal -->
<div id="persona-modal" class="modal">
    <div class="modal-content">
        <h2>Persona Management</h2>
        
        <!-- List -->
        <div id="persona-list"></div>
        
        <!-- Upload -->
        <div class="upload-section">
            <input type="file" id="persona-file" accept=".txt" hidden>
            <button id="upload-btn">📤 Upload Persona</button>
        </div>
        
        <!-- Actions -->
        <button id="close-modal">Close</button>
    </div>
</div>
```

**Tasks:**
- [ ] Widget HTML hinzufügen
- [ ] Modal HTML hinzufügen
- [ ] CSS Styling
- [ ] Event Listeners binden

---

#### 3.3 Integration in app.js
**File:** `adapters/Jarvis/static/js/app.js`

**Changes:**
```javascript
// On page load
document.addEventListener('DOMContentLoaded', () => {
    PersonaManager.loadPersonas();
    
    // Event Listeners
    document.getElementById('persona-selector')
        .addEventListener('change', (e) => {
            PersonaManager.switchPersona(e.target.value);
        });
    
    document.getElementById('upload-btn')
        .addEventListener('click', () => {
            document.getElementById('persona-file').click();
        });
    
    // ... etc
});
```

**Tasks:**
- [ ] DOMContentLoaded handler erweitern
- [ ] Event Listeners registrieren
- [ ] Integration testen

---

#### 3.4 Phase 3 Testing
**Manual UI Tests:**
- [ ] Dropdown zeigt alle Personas
- [ ] Persona-Switch funktioniert
- [ ] Upload-Dialog öffnet sich
- [ ] Upload funktioniert (Progress, Success)
- [ ] Delete mit Confirmation
- [ ] Aktive Persona ist markiert
- [ ] Mobile-responsive

---

### 🟣 PHASE 4: Polish & Documentation
**Duration:** 2h  
**Goal:** Finish touches

#### 4.1 Error Handling
**Scenarios:**
- Persona file nicht gefunden
- Parse error in .txt
- Upload fehlgeschlagen
- Switch während Chat

**Tasks:**
- [ ] Graceful Fallback zu default.txt
- [ ] User-friendly Error Messages
- [ ] Logging verbessern

---

#### 4.2 Documentation
**Files to update:**
- [ ] `personas/README.md` (Format Guide)
- [ ] `documentation/features/PERSONA_MANAGEMENT.md` (User Guide)
- [ ] Main README.md (Feature erwähnen)
- [ ] Changelog/Release Notes

---

#### 4.3 Docker Integration
**docker-compose.yml:**
```yaml
jarvis-webui:
  volumes:
    - ./personas:/app/personas  # Persist personas
```

**Tasks:**
- [ ] Volume mapping hinzufügen
- [ ] Testen ob Personas persistent sind
- [ ] Container-Restart testen

---

#### 4.4 Optional: Example Personas
**Create:**
- `personas/dev_mode.txt` (Technical, code-focused)
- `personas/creative.txt` (Creative writing style)
- `personas/security.txt` (Security-audit tone)

**Tasks:**
- [ ] 2-3 Beispiel-Personas erstellen
- [ ] In README dokumentieren

---

## 🚀 DEPLOYMENT CHECKLIST

**Before Merge:**
- [ ] Alle Tests passed
- [ ] Code reviewed
- [ ] Documentation complete
- [ ] Backward compatibility verified
- [ ] Migration guide geschrieben

**After Merge:**
- [ ] Container neu builden
- [ ] Smoke Tests in Production
- [ ] GitHub Release v0.2.0
- [ ] Reddit Update Post

---

## 📊 PROGRESS TRACKING

### Phase 1: Backend Foundation
- [x] 1.1 Ordner-Struktur ✅
- [ ] 1.2 README.md
- [ ] 1.3 default.txt Migration
- [ ] 1.4 persona.py Refactor
- [ ] 1.5 Backward Compatibility
- [ ] 1.6 Testing

### Phase 2: API Endpoints
- [ ] 2.1 persona_endpoints.py
- [ ] 2.2 main.py Integration
- [ ] 2.3 API Testing

### Phase 3: Frontend UI
- [ ] 3.1 personas.js
- [ ] 3.2 HTML Components
- [ ] 3.3 app.js Integration
- [ ] 3.4 UI Testing

### Phase 4: Polish
- [ ] 4.1 Error Handling
- [ ] 4.2 Documentation
- [ ] 4.3 Docker Integration
- [ ] 4.4 Example Personas

---

## 🎯 FUTURE PHASES (Post-v0.2.0)

### Phase 5: Classifier Integration
**Goal:** Persona auch für Classifier-Models

**Tasks:**
- Persona-basierte Classifier-Prompts
- Tool-Auswahl basierend auf Persona
- Response-Style anpassen

### Phase 6: Advanced Features
**Optional:**
- Persona Metadata (scope, tags)
- Persona Templates
- Version History (Git-like)
- Persona Marketplace (Community)

---

## 📝 NOTES & DECISIONS

**2026-01-04:**
- Entscheidung: .txt Format (nicht YAML)
- Entscheidung: Hot-Reload Support
- Entscheidung: default.txt Protected
- Ordner-Struktur erstellt ✅

---

## 🆘 TROUBLESHOOTING

**Problem:** Persona Switch funktioniert nicht
- Check: reload_persona() aufgerufen?
- Check: Cache geleert?
- Check: Container-Restart nötig?

**Problem:** Upload schlägt fehl
- Check: File size < 10KB?
- Check: .txt Extension?
- Check: Write permissions auf /personas/?

---

**END OF IMPLEMENTATION GUIDE**
