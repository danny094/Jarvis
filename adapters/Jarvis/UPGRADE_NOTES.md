# Jarvis WebUI - Upgrade Documentation

## 🎉 Was wurde verbessert?

### ✅ Phase 1 Implementation - Komplett!

Die Jarvis WebUI wurde vollständig überarbeitet mit modernem Design und erweiterten Features.

---

## 🚀 Neue Features

### 1. **Enhanced Header**

**Layer Status Ampeln** (Live-Feedback)
- 🟢 **Thinking Layer** - Zeigt Intent-Analyse-Status
- 🟡 **Control Layer** - Zeigt Fact-Checking-Status  
- 🔴 **Output Layer** - Zeigt Response-Generierung-Status

**Quick Mode Switcher**
- ⚡ **Fast** - Skip Control, light models
- ⚖️ **Balanced** - Current settings (default)
- 🎯 **Accurate** - All layers, heavy models
- ⚙️ **Custom** - Link zu Settings

### 2. **Tab-basiertes Settings Modal**

Statt einer langen Liste gibt es jetzt **4 organisierte Tabs**:

#### Tab 1: Basic Settings
- Chat History Length (Slider)
- API Endpoint (Input)
- Auto-Save Memory (Toggle)
- Verbose Logging (Toggle)

#### Tab 2: Layer Settings

**Thinking Layer**
- Enable/Disable Toggle
- Model Selection (DeepSeek-R1:8b, :14b, Qwen-QwQ)
- Temperature Slider (0.0 - 1.0)
- Show Reasoning Checkbox

**Control Layer**
- Enable/Disable Toggle
- Skip on Low Risk (SPEED BOOST!) ⚡
- Model Selection (Qwen3:4b, Qwen2.5:0.5b, Llama3.1:8b)
- Temperature Slider (0.0 - 0.5)

**Output Layer**
- Enable/Disable Toggle
- Model Selection (Llama3.1:8b, Qwen2.5:7b, DeepSeek-V3)
- Temperature Slider (0.0 - 1.0)
- Persona Selection (Professional, Technical, Creative, Custom)

#### Tab 3: Memory Settings

**Retrieval Settings**
- Semantic Search Top-K (1-10)
- Min Similarity Threshold (0.0 - 1.0)
- Include Graph Walk (Checkbox)

**Auto-Save**
- Save Facts Automatically
- Generate Embeddings
- Update Knowledge Graph

**Cleanup**
- STM → MTM after X days (Slider)
- Run Maintenance Now (Button)

#### Tab 4: Advanced Settings

**Validation** (Collapsible)
- Enable Validation Toggle
- Threshold Slider
- Hard Fail Mode Toggle

**Performance** (Collapsible)
- Max Tokens (Input)
- Timeout (Input)
- Verbose Timing Logs

**Network** (Collapsible)
- Retry Count
- Connection Pool Size
- Enable HTTP/2

**Experimental** (Collapsible)
- Multi-hop Graph Reasoning
- Adaptive Layer Skipping
- Response Caching

### 3. **Quick Actions Toolbar**

Über dem Input-Feld - schneller Zugriff auf häufige Actions:

- 🗑️ **Clear Memory** - Löscht Memory für Conversation
- 🔄 **Regenerate** - Generiert letzte Antwort neu
- 📋 **Copy** - Kopiert Response als Markdown
- 💾 **Export** - Exportiert Chat (JSON/MD)
- ⋯ **More** - Dropdown mit weiteren Optionen
  - Import Chat
  - Search History
  - View Stats

### 4. **Settings Import/Export**

Footer-Buttons im Settings Modal:
- **Import** - Lädt Settings aus JSON
- **Export** - Speichert Settings als JSON
- **Reset** - Zurück zu Defaults
- **Save** - Speichert Änderungen

---

## 📁 Dateien

### Geändert
- `index.html` - Komplett neu strukturiert

### Backup
- `index-backup.html` - Original-Version als Backup

### Neu
- `UPGRADE_NOTES.md` - Diese Datei

---

## 🎨 Design-Änderungen

### Farben
Alle bestehenden Dark-Theme-Farben wurden beibehalten:
- `dark-bg`: #0a0a0a
- `dark-card`: #1a1a1a
- `dark-border`: #2a2a2a
- `dark-hover`: #333333
- `accent-primary`: #3b82f6 (Blau)
- `accent-secondary`: #8b5cf6 (Lila)

### Neue Animationen
- `pulse-glow` - Für Status-Dots
- Tab-Transitions
- Collapsible Details

### Responsive
- Header komprimiert auf Mobile
- Status-Ampeln versteckt auf < md
- Model-Selector versteckt auf < sm
- Quick Actions kompakt

---

## 🔧 JavaScript-Integration

### Neue IDs & Classes

**Header**
- `#status-thinking`, `#status-thinking-dot`, `#status-thinking-text`
- `#status-control`, `#status-control-dot`, `#status-control-text`
- `#status-output`, `#status-output-dot`, `#status-output-text`
- `#quick-mode-btn`, `#quick-mode-dropdown`, `#quick-mode-name`

**Settings Tabs**
- `.settings-tab` - Tab-Buttons
- `.settings-tab-content` - Tab-Content-Divs
- `#tab-basic`, `#tab-layers`, `#tab-memory`, `#tab-advanced`

**Layer Controls**
- `#thinking-layer-toggle`, `#thinking-model`, `#thinking-temp`
- `#control-layer-toggle`, `#control-model`, `#control-temp`
- `#output-layer-toggle`, `#output-model`, `#output-temp`
- `#skip-on-low-risk`, `#show-reasoning`, `#persona-select`

**Memory Controls**
- `#topk-slider`, `#topk-value`
- `#similarity-slider`, `#similarity-value`
- `#include-graph-walk`
- `#autosave-facts`, `#autosave-embeddings`, `#autosave-graph`
- `#stm-days-slider`, `#stm-days-value`

**Quick Actions**
- `#action-clear-memory`
- `#action-regenerate`
- `#action-copy`
- `#action-export`
- `#more-actions-btn`, `#more-actions-dropdown`

### Event-Listener

Alle Event-Listener sind inline im `<script>` Tag implementiert:
- Tab-Switching
- Quick Mode Selection
- Slider Value Updates
- Toggle Button States
- Dropdown Management
- Quick Actions

---

## ⚡ Performance

### Optimierungen
- CSS-Transitions statt JavaScript-Animationen
- Lazy-Loading für Tooltips (hover)
- Collapsible Sections in Advanced Tab
- Minimal Re-Renders bei Slider-Updates

### Bundle Size
- Keine zusätzlichen Dependencies
- Tailwind CDN (wie vorher)
- Lucide Icons CDN (wie vorher)
- Gesamt-HTML: ~600 Zeilen (+78 Zeilen vs Original)

---

## 🔄 Migration

### Von alter UI zu neuer UI

**Settings werden beibehalten:**
- localStorage-Keys bleiben gleich
- Bestehende Settings funktionieren
- Neue Settings haben Smart Defaults

**Neue Settings Default-Werte:**
```js
{
  // Layers
  thinkingEnabled: true,
  thinkingModel: "deepseek-r1:8b",
  thinkingTemp: 0.7,
  showReasoning: false,
  
  controlEnabled: true,
  controlModel: "qwen3:4b",
  controlTemp: 0.1,
  skipOnLowRisk: true,  // ← SPEED BOOST
  
  outputEnabled: true,
  outputModel: "llama3.1:8b",
  outputTemp: 0.8,
  persona: "professional",
  
  // Memory
  topK: 5,
  minSimilarity: 0.5,
  includeGraphWalk: true,
  autosaveFacts: true,
  autosaveEmbeddings: true,
  autosaveGraph: true,
  stmToMtmDays: 7,
  
  // Advanced
  enableValidation: true,
  validationThreshold: 0.70,
  hardFailMode: true,
  maxTokens: 2000,
  timeout: 60,
  verboseTiming: false,
  retryCount: 3,
  connectionPool: 10,
  enableHttp2: false,
  multiHopReasoning: false,
  adaptiveLayerSkip: false,
  responseCaching: false
}
```

---

## 🐛 Bekannte Issues & TODOs

### Phase 1 ✅ Komplett
- [x] Header mit Status-Ampeln
- [x] Quick Mode Switcher
- [x] Tab-basiertes Settings Modal
- [x] Layer Controls
- [x] Memory Settings
- [x] Advanced Settings
- [x] Quick Actions Toolbar

### Phase 2 (Zukünftig)
- [ ] Status-Ampeln Live-Update (braucht Backend-Integration)
- [ ] Quick Mode Backend-Kommunikation
- [ ] Settings Import/Export Funktionalität
- [ ] Quick Actions Implementierung (Clear, Regenerate, etc.)
- [ ] Layer-Model-Auswahl Backend-Sync
- [ ] Memory-Settings Backend-Sync

### Phase 3 (Optional)
- [ ] Performance Panel (collapsible sidebar)
- [ ] Graph Visualization (D3.js)
- [ ] Multi-Conversation Tabs
- [ ] Theme Switcher (Light Mode)

---

## 📞 Support

Bei Fragen oder Problemen:
1. Prüfe `index-backup.html` (Original-Version)
2. Check Browser Console für JS-Errors
3. Öffne Issue mit Screenshot

---

## 🎯 Nächste Schritte

1. **Testen** - UI in Browser öffnen: `http://192.168.0.224:8400`
2. **Backend-Integration** - app.js erweitern für neue Features
3. **Feedback sammeln** - Was funktioniert gut? Was fehlt?
4. **Phase 2 planen** - Welche Features als nächstes?

---

**Erstellt:** 2024-12-28  
**Version:** 2.0.0  
**Author:** Claude (Anthropic)
