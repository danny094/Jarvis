# Core Layers Analysis (`core/layers`)

## Übersicht

Das `core/layers` Modul implementiert die **Cognitive Architecture** von TRION. Es basiert auf einem 3-Schichten-Modell ("System 2 Thinking"), das Planung, Überprüfung und Ausführung trennt. Diese Architektur ermöglicht robustere, sicherere und komplexere Handlungen als reine LLM-Calls.

## Layer-Struktur & Module

### 1. `thinking.py` / `thinking_extended.py` (Layer 1: The Strategist)

- **Modell**: `thinking` (typischerweise DeepSeek-R1).
- **Funktion**: Analysiert die User-Intention **bevor** gehandelt wird.
- **Output**: Ein strukturierter JSON-Plan.
- **Varianten**:
  - `thinking.py`: Basis-Version (v3.0), optimiert für Geschwindigkeit.
  - `thinking_extended.py`: Erweiterte Version mit Logik für **Sequential Thinking**, CIM-Modi und Komplexitätsabschätzung.
- **Entscheidungen**:
  - Braucht es Memory-Zugriff?
  - Ist Sequential Thinking (Schritt-für-Schritt Reasoning) notwendig?
  - Halluzinations-Risiko?

### 2. `control.py` (Layer 2: The Critic)

- **Modell**: `control` (typischerweise Qwen oder Llama).
- **Funktion**: Sicherheitsinstanz und Orchestrator für komplexe Denkprozesse.
- **Hauptaufgaben**:
  - **Validierung**: Prüft den Plan gegen Sicherheitsregeln (`LightCIM`) und CIM Policies.
  - **Sequential Thinking (v5.0)**: Führt bei Bedarf tiefgehende "Live-Reasoning" Sessions aus. Es streamt den "Thinking"-Prozess des Modells live zum Frontend und parst die Schritte (`## Step N`) strukturiert.
  - **Skill-Protection**: Erkennt Versuche, Skills zu erstellen/ändern und fordert Bestätigung an (CIM Policy Engine).

### 3. `output.py` (Layer 3: The Speaker)

- **Modell**: `output` (typischerweise Llama 3.x).
- **Funktion**: Generierung der finalen Antwort und Tool-Ausführung.
- **Features**:
  - **Native Tool Calling**: Konvertiert MCP-Tools in Ollama-kompatible Funktionsdefinitionen.
  - **Persona-Injection**: Wendet die definierte Persönlichkeit an.
  - **Streaming**: Unterstützt Async-Streaming der Antwort tokens.
  - **Kontext-Integration**: Baut den finalen Prompt aus Plan, Memory, Chat-History und Sequential-Thinking-Ergebnissen zusammen.

## Wichtige Imports & Abhängigkeiten

### Infrastruktur

| Bibliothek | Zweck |
|------------|-------|
| `httpx` | Asynchrone HTTP-Calls zu Ollama und internen Services (CIM). |
| `asyncio`, `json`, `re` | Core Utilities für Ablaufsteuerung und Parsing. |

### System-Kontext

| Modul | Verwendungszweck |
|-------|------------------|
| `config` | Lädt Model-Namen (`THINKING_MODEL`, `CONTROL_MODEL`, `OUTPUT_MODEL`) und URLs. |
| `mcp.hub` | Zugriff auf Tools und MCP-Ressourcen. |
| `core.persona` | Zugriff auf die aktuelle Persona-Definition. |
| `core.safety` (`LightCIM`) | Basis-Sicherheitschecks im Control-Layer. |
| `utils.logger` | Logging. |
| `intelligence_modules.cim_policy` | (Optional) Erweiterte Policy Engine für Skill-Management. |

## Feature-Highlights

### Sequential Thinking v5.0 (`control.py`)

Ein hochentwickelter Modus für komplexe Anfragen.

- **Live Streaming**: Der "Gedankenstrom" des Modells wird direkt an das UI weitergeleitet (`seq_thinking_stream`).
- **Parsing**: Sobald das Modell fertig gedacht hat, wird der strukturierte Inhalt in "Steps" zerlegt und als JSON-Objekt (`_sequential_result`) gespeichert.

### CIM Policy Integration

Der Control-Layer prüft aktiv auf sensitive Aktionen wie "Skill erstellen". Wenn erkannt, wird die `cim_policy_engine` konsultiert, um zu entscheiden, ob eine User-Bestätigung notwendig ist oder die Aktion blockiert werden muss.

### Native Ollama Tools (`output.py`)

Der Output-Layer nutzt die native Tool-Calling API von Ollama, anstatt Tools manuell in den Prompt zu patchen. Er agiert als Brücke zwischen der standardisierten MCP-Tool-Definition und dem Ollama-Format.
