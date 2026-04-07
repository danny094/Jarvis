# TRION Shell — xterm.js Remount-Bug (Eingabe tot nach Tab-Wechsel)

Erstellt am: 2026-03-31
Zuletzt aktualisiert: 2026-04-01
Status: **Fix umgesetzt**
Bezieht sich auf:

- [[2026-03-31-control-layer-audit]] — parallele Bug-Session
- [[2026-03-29-trion-codeatlas-und-konsolidierungsanalyse]] — Systemüberblick

---

## Symptom

1. Shell-Tab wird erstmals geöffnet — WebSocket verbindet, xterm rendert, Eingabe funktioniert
2. User wechselt zu einem anderen App-Tab (z.B. Chat, Vault)
3. User wechselt zurück zum Shell-Tab
4. Terminal sieht visuell intakt aus (Container-Badge sichtbar, WS zeigt connected) —
   aber Tastatureingabe ist vollständig tot: keine Zeichen, keine Befehle

---

## Externe Analyse (Claude Desktop, Bildbasis)

> xterm.js loses focus or its DOM event listeners get detached when the component is hidden/unmounted
> and re-mounted during tab navigation.
> Fix: `terminal.focus()` beim Tab-Aktivieren aufrufen, ggf. FitAddon neu anhängen.

**Bewertung: Symptom korrekt erkannt, Root Cause falsch / zu oberflächlich.**

---

## Echter Root Cause

### 1. `remount()` baut den kompletten DOM neu auf

`terminal.js:263`:
```js
root.innerHTML = buildTerminalHTML();
```

Damit wird `#xterm-container` durch einen **neuen, leeren** Node ersetzt.
Die alte xterm-Instanz referenziert aber noch den alten, jetzt toten Node.

### 2. `initXterm()` hat einen blinden Guard

`xterm.js:16`:
```js
if (!container || xterm) return;
```

`xterm` ist nach dem ersten Init **nicht null** — Guard greift, kein Re-Init,
neuer Container bleibt leer.

### 3. `focusTerminal()` fokussiert ein detached Element

`xterm.js:252`:
```js
function focusTerminal() {
    if (xterm) xterm.focus();
}
```

`xterm` zeigt auf die alte Instanz, die auf einem toten DOM-Node sitzt.
Focus landet im Void — Tastatur reagiert nicht.

### 4. `trion:app-activated`-Listener hilft nicht

`xterm.js:94–100`:
```js
window.addEventListener('trion:app-activated', (event) => {
    if (event?.detail?.appName === 'terminal') {
        scheduleXtermFit();
        if (deps.getLogPanelMode() === 'shell' && xterm) xterm.focus();
    }
});
```

`bindEvents()` in `remount()` ruft `setLogPanelMode('logs')` auf (`terminal.js:632`).
Damit ist `logPanelMode` immer `'logs'` nach einem Remount →
`xterm.focus()` wird nie ausgeführt, selbst wenn der Listener feuert.

### 5. ResizeObserver beobachtet toten Container

`xterm.js:109–116`: `xtermResizeObserver` wird mit Guard `if (xtermResizeObserver) return`
nur einmal angelegt — danach beobachtet er den alten, entfernten `#xterm-container`.

---

## Ablauf im Detail

```
Erstaufruf:
  initXterm()
    → xterm = new Terminal(...)
    → xterm.open(#xterm-container_alt)          ← auf altem Node
    → xtermResizeObserver beobachtet _alt
    → xtermAppActivationBound = true

User wechselt Tab weg → switchApp('vault')
  → app-terminal bekommt class="hidden"

User kommt zurück → switchApp('terminal')
  → remount() wird aufgerufen:
      root.innerHTML = buildTerminalHTML()        ← #xterm-container_alt wird zerstört
                                                    #xterm-container_neu ist leer
      bindEvents()
        → setLogPanelMode('logs')                 ← logPanelMode reset
      switchTab(activeTab)

  → trion:app-activated dispatcht:
      scheduleXtermFit()                          ← fitAddon auf totem Node → no-op
      logPanelMode === 'shell'? NEIN              ← wurde zu 'logs' resettet
      → xterm.focus() wird nicht aufgerufen

User klickt Shell-Tab:
  setLogPanelMode('shell')
    → initXterm()
        if (xterm) return                         ← GUARD GREIFT, kein Re-Init
    → focusTerminal()
        xterm.focus()                             ← fokussiert toten Node → dead input
```

---

## Gegenüberstellung externe vs. echte Analyse

| Punkt | Externe Analyse | Realität |
|---|---|---|
| Tab-Wechsel ist Trigger | ✅ richtig | `remount()` killt DOM via `innerHTML` |
| "focus lost / listeners detached" | ⚠ zu simpel | xterm ist an totem DOM-Node gebunden |
| Fix: `terminal.focus()` aufrufen | ❌ unzureichend | Focus auf detached Node hilft nicht |
| FitAddon neu anhängen | ⚠ auch nötig, aber sekundär | ResizeObserver ebenfalls betroffen |
| Eigentlicher Guard-Bug | nicht erkannt | `if (xterm) return` verhindert Re-Init |

---

## Fix-Ansatz

**Minimal-Fix: xterm vor DOM-Rebuild disposen**

`xtermController` braucht eine neue exportierte Methode:

```js
// xterm.js — neu zu exportieren
function disposeXterm() {
    if (xtermResizeObserver) {
        xtermResizeObserver.disconnect();
        xtermResizeObserver = null;
    }
    if (xterm) {
        xterm.dispose();
        xterm = null;
    }
    fitAddon = null;
    xtermAppActivationBound = false;
}
```

In `remount()` (`terminal.js:259`) vor dem DOM-Rebuild aufrufen:

```js
export async function remount() {
    const root = document.getElementById('app-terminal');
    if (!root) return;

    xtermController.disposeXterm();             // ← NEU: alten State bereinigen
    root.innerHTML = buildTerminalHTML();
    // ... Rest unverändert
}
```

Damit:
- `xterm = null` → Guard in `initXterm()` greift nicht mehr
- `xtermResizeObserver = null` → wird neu auf neuem Container angelegt
- `xtermAppActivationBound = false` → Listener wird neu registriert

**Kein Workaround mit `focus()` alleine** — das adressiert nur das Symptom,
nicht die stale-Instance auf totem Node.

---

## Betroffene Dateien

| Datei | Zeile | Relevanz |
|---|---|---|
| `adapters/Jarvis/js/apps/terminal/xterm.js` | 16 | Guard `if (xterm) return` |
| `adapters/Jarvis/js/apps/terminal/xterm.js` | 93–101 | `trion:app-activated`-Listener |
| `adapters/Jarvis/js/apps/terminal/xterm.js` | 251–253 | `focusTerminal()` |
| `adapters/Jarvis/js/apps/terminal.js` | 259–270 | `remount()` — kein dispose vor innerHTML |
| `adapters/Jarvis/js/apps/terminal.js` | 632 | `setLogPanelMode('logs')` — reset in bindEvents |
| `adapters/Jarvis/js/shell.js` | 398–406 | `remount()` wird bei Tab-Rückkehr aufgerufen |

---

## Status

**Fix umgesetzt — 2026-04-01**

### Geänderte Dateien

| Datei | Änderung |
|---|---|
| `adapters/Jarvis/js/apps/terminal/xterm.js` | `disposeXterm()` hinzugefügt (Zeile 254), in `return`-Objekt exportiert |
| `adapters/Jarvis/js/apps/terminal.js` | `xtermController.disposeXterm()` vor `root.innerHTML` in `remount()` (Zeile 262) |

### Was der Fix bewirkt

- `xterm = null` nach dispose → Guard `if (xterm) return` in `initXterm()` greift nicht mehr
- `xtermResizeObserver` wird disconnected und auf `null` gesetzt → wird neu auf neuem Container angelegt
- `xtermAppActivationBound = false` → `trion:app-activated`-Listener wird neu registriert
- `fitAddon = null` → wird beim nächsten `initXterm()` neu geladen
