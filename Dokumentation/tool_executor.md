# Tool Executor (`tool_executor/`)

Der **Tool Executor** (Layer 4) ist die "Hand" des Systems. Er ist der einzige Service, der **Side-Effects** (Datei-Änderungen, Code-Ausführung) durchführen darf. Er agiert als strikter Gatekeeper für alle Skill-Operationen.

## Architektur

Der Service ist eine **FastAPI** Anwendung und läuft als eigenständiger Docker-Container.

### API Endpoints (`api.py`)

* `POST /v1/skills/create`: Erstellt einen neuen Skill (nach Validierung).
* `POST /v1/skills/run`: Führt einen Skill aus.
* `POST /v1/skills/install`: Installiert einen Skill aus der Registry.
* `POST /v1/skills/uninstall`: Löscht einen Skill.

### Kern-Komponenten

#### 1. Engine (`engine/`)

* **`skill_runner.py`**:
  * **Sandbox**: Führt Code in einer isolierten Umgebung aus.
  * **Restriktionen**:
    * Keine gefährlichen Builtins (`eval`, `exec`, `open`).
    * Nur gewhitelistete Imports (`json`, `math`, `datetime`, `re`...).
    * Kein direkter Netzwerkzugriff (außer via spezialisierte Libraries, falls erlaubt).
  * **Timeout**: Bricht Ausführung nach 30s ab (konfigurierbar).
* **`skill_installer.py`**:
  * Verwaltet das Dateisystem (`/skills`).
  * Unterscheidet **Drafts** (`_drafts/`) und **Active Skills**.
  * Schreibt `manifest.yaml` und updatet die lokale Registry (`installed.json`).

#### 2. Mini Control Layer (`mini_control_layer.py`)

Eine autonome Entscheidungs-Instanz, die **vor** jeder Ausführung prüft:

* **Validierung**: Nutzt `skill_cim_light.py` für statische Code-Analyse.
* **Autonomie**: Kann einfache Skills **selbstständig generieren** (via `qwen2.5-coder`), wenn kein passender Skill gefunden wird ("Make-Tool-Pattern").
* **Entscheidung**: `APPROVE`, `WARN` (Ausführung erlaubt), `BLOCK` (verboten), `ESCALATE` (Mensch muss entscheiden).

#### 3. Contracts (`contracts/`)

Definiert JSON-Schemas für Requests (z.B. `create_skill.json`), um strikte Schnittstellen zu garantieren.

---

## Sicherheits-Features

1. **Contract-First**: Jeder Request muss gegen ein JSON-Schema validieren.
2. **Sandbox Execution**: Skills können nicht aus ihrer Umgebung ausbrechen.
3. **Validation-Loop**: Kein Code wird ausgeführt, ohne den `MiniControlLayer` zu passieren.
4. **Audit Logs**: Alle Aktionen (`create`, `run`, `install`) werden via `EventLogger` protokolliert.

## Workflow: Skill Creation

1. Client sendet `CREATE` Request.
2. `api.py` validiert Payload gegen Schema.
3. `mini_control_layer` analysiert Code (Security, Best Practices).
4. Bei Erfolg: `SkillInstaller` schreibt Dateien.
    * `auto_promote=False` $\to$ Speichert in `_drafts/` (Review nötig).
    * `auto_promote=True` $\to$ Speichert direkt als nutzbaren Skill.
