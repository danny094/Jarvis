# Zentralisierung des Prompt-Managements

## Ziel

Das eigentliche Problem ist nicht ein einzelner schlechter Prompt, sondern dass viele Prompt-Texte und harte Antwortregeln aktuell ueber den Code verstreut sind.

Heute liegen Formulierungen, Stilvorgaben, Contracts und Task-Loop-Hinweise in vielen Dateien als harte Python-Strings vor:

- `parts.append("...")`
- Inline-Listen mit Regeln
- grosse System-Prompt-Konstanten
- verstreute Recovery-/Fallback-/Status-Texte

Das fuehrt zu vier konkreten Problemen:

1. Aenderungen am Ton oder an Regeln muessen an vielen Stellen parallel gemacht werden.
2. Prompt-Verhalten driftet zwischen Layern und Sonderpfaden auseinander.
3. Es ist schwer zu sehen, welche Formulierung aktuell wirklich die Source of Truth ist.
4. Kleine Text-Fixes enden schnell in inkonsistenten Teil-Patches statt in einem klaren Prompt-System.

Das Ziel dieser Arbeit ist deshalb:

- Hardcoded Prompt-Texte zentral sammeln
- Prompt-Text von Ausfuehrungslogik trennen
- eine klare Source of Truth fuer Formulierungen schaffen
- Textanpassungen kuenftig an einer Stelle pflegbar machen

Nicht das Ziel:

- Control-, Orchestrator- oder Policy-Logik in Templates zu verschieben
- Entscheidungslogik in Markdown zu verstecken
- die komplette Architektur in einem Schritt umzubauen

## Zielbild

Alle relevanten Prompt-Texte werden an einer zentralen Stelle abgelegt und von dort geladen.

Der Code soll dann moeglichst nur noch:

- den passenden Prompt auswaehlen
- Variablen injizieren
- den gerenderten Text an den bestehenden Flow uebergeben

Die inhaltliche Entscheidung bleibt im Code.
Die Formulierung wandert in zentrale Prompt-Dateien.

## Zielarchitektur

Die Zielarchitektur trennt sauber zwischen Text, Rendering und Verhalten.

### 1. Prompt-Dateien als Source of Truth

Unter `intelligence_modules/prompts/` liegen die eigentlichen Prompt-Texte.

Dort liegen:

- Layer-Prompts
- textuelle Contracts
- Task-Loop-Formulierungen
- Persona- und Stilbausteine

Dort liegt nicht:

- Routing-Logik
- Policy-Logik
- Layer-Entscheidungslogik
- Orchestrator-Verhalten

### 2. Prompt Loader als zentrale Leseschicht

Der Loader ist die einzige technische Stelle, die Prompt-Dateien direkt liest und rendert.

Seine Verantwortung:

- Frontmatter lesen
- Prompt-Text laden
- Variablen einsetzen
- Rendering-Fehler klar melden

Der Loader soll keine Logik uebernehmen, welcher Prompt fachlich richtig ist.
Er ist nur Infrastruktur.

### 3. Code entscheidet, Prompt-Dateien formulieren

Die aufrufenden Module entscheiden weiterhin:

- welcher Prompt benoetigt wird
- welche Variablen uebergeben werden
- wann welcher Contract gilt
- welcher Layer welchen Text bekommt

Die Prompt-Datei entscheidet nur:

- wie etwas formuliert ist
- welche statischen Regeln oder Textbausteine mitgegeben werden

Faustregel:

- Auswahl und Verhalten im Code
- Wortlaut im Prompt-System

### 4. Schmale Integrationspunkte pro Layer

Jeder betroffene Layer soll moeglichst ueber wenige Integrationspunkte an das Prompt-System angebunden sein.

Beispiel Zielzustand:

- Output Layer hat wenige Builder/Resolver, die zentrale Prompt-Dateien laden
- Task-Loop hat klar benannte Text-Bausteine fuer Status, Recovery und Rueckfragen
- Thinking und Control laden spaeter ihre grossen System-Prompts ebenfalls zentral

Nicht das Ziel ist, ueberall im Code kleine Einzel-Loads zu verstreuen.
Die zentrale Bueendelung soll auch im Code sichtbar bleiben.

### 5. Deterministisches Verhalten

Der Umstieg auf zentrale Prompt-Dateien darf Formulierungen aendern, aber nicht still Verhalten verbiegen.

Deshalb gilt fuer die Zielarchitektur:

- Prompt-Dateien beeinflussen Text
- Policy-Dateien beeinflussen Verhalten
- Control entscheidet Freigaben
- Orchestrator entscheidet Ausfuehrungsfluss
- Output formuliert das Endergebnis

Wenn eine Aenderung nur durch einen Prompt-Text eine fachliche Entscheidung verschiebt, ist das ein Architekturfehler.

## Vorschlag fuer die Struktur

### [NEW] `intelligence_modules/prompts/`

- `layers/`
  Enthält die grossen Layer-Prompts wie Thinking, Control und Output.
- `contracts/`
  Enthält textuelle Contracts fuer Output-/Antwortregeln.
- `task_loop/`
  Enthält Task-Loop-spezifische Hinweistexte, Recovery-Texte und Schrittformulierungen.
- `personas/`
  Enthält Stil- und Rollenbausteine.

Beispiel:

```md
---
scope: container_contract
target: output_layer
variables: ["required_tools", "truth_mode"]
---

Containerantworten muessen Runtime-Inventar, Blueprint-Katalog und Session-Binding sichtbar getrennt halten.

Verbindlicher Container-Contract fuer diesen Turn: Aussagen nur auf {required_tools} stuetzen.
truth_mode fuer diesen Turn: {truth_mode}.
```

## Prompt Loader

### [NEW] `intelligence_modules/prompt_manager/loader.py`

Der Loader soll bewusst klein und deterministisch bleiben.

Er soll:

- Frontmatter parsen
- Prompt-Body laden
- Variablen injizieren
- bei fehlenden Variablen oder kaputtem Frontmatter klar fehlschlagen

Ziel-API:

```python
load_prompt(category: str, template_name: str, **kwargs) -> str
```

Wichtige Randbedingungen fuer Phase 1:

- kein `jinja2`
- kein Template-Branching
- keine versteckte Logik im Prompt
- nur einfache Platzhalter wie `{required_tools}`

Fuer den Anfang reicht bewusst simples Python-Formatting.
Wenn spaeter echte Template-Komplexitaet noetig ist, kann das separat entschieden werden.

## Umsetzungsstrategie

### Phase 1: Output Layer als Proof of Concept

Wir starten dort, wo der Nutzen hoch und das Risiko kontrollierbar ist:

- `core/layers/output/layer.py`
- `core/layers/output/contracts/container.py`
- optional danach `core/layers/output/prompt/system_prompt.py`

In dieser Phase geht es nicht darum, das ganze System sofort umzubauen.
Es geht darum zu beweisen, dass zentrale Prompt-Dateien sauber funktionieren und der Code dadurch einfacher wird.

### Phase 2: Task-Loop-Texte nachziehen

Wenn der Output-Layer sauber funktioniert, ziehen wir die verteilten Task-Loop-Texte nach:

- `core/task_loop/step_runtime/prompting.py`
- `core/task_loop/step_answers.py`
- `core/task_loop/runner/messages.py`
- `core/task_loop/capabilities/container/parameter_policy.py`

### Phase 3: Grosse Layer-Prompts

Erst danach folgen die grossen System-Prompts:

- `core/layers/thinking.py`
- `core/layers/control/prompting/constants.py`
- `core/persona.py`

Diese Phase spaeter anzugehen ist wichtig, weil dort der Umbau tiefer in bestehende Flows eingreift.

## Was explizit im Code bleiben muss

Diese Dinge sollen nicht in Prompt-Dateien verschoben werden:

- Tool- oder Layer-Entscheidungen
- Recovery-/Routing-Logik
- Policy-Gates
- Control-Entscheidungen
- Orchestrator-Rewrites
- echte Conditionals mit Verhaltenswirkung

Faustregel:

- Text und Formulierung nach `prompts/`
- Verhalten und Entscheidung im Python-Code

## Erste Zielliste

Die folgenden Dateien enthalten aktuell harte Prompt-Texte oder stark verteilte Formulierungen und sind mittelfristig Kandidaten fuer die Zentralisierung:

### Output

- `core/layers/output/layer.py`
- `core/layers/output/prompt/system_prompt.py`
- `core/layers/output/contracts/container.py`
- `core/layers/output/contracts/skill_catalog/evaluation.py`

### Task Loop

- `core/task_loop/step_runtime/prompting.py`
- `core/task_loop/step_answers.py`
- `core/task_loop/runner/messages.py`
- `core/task_loop/capabilities/container/parameter_policy.py`

### Spaeter

- `core/layers/thinking.py`
- `core/layers/control/prompting/constants.py`
- `core/persona.py`
- `core/context_compressor.py`

## Verification

### Automated

- Loader-Unit-Tests fuer Frontmatter, Platzhalter und Fehlerfaelle
- Snapshot-Tests fuer gerenderte Prompt-Texte
- bestehende Layer-/Output-Tests weiterlaufen lassen

### Manual

- gezielte Testanfragen an Output- und Task-Loop-Pfade
- pruefen, ob die Formulierung weiterhin korrekt ist
- pruefen, ob sich nur Text aendert und nicht unbeabsichtigt Verhalten

## Ergebnis, das wir erreichen wollen

Am Ende soll nicht mehr unklar sein, welcher Prompt an welcher Stelle gilt.

Statt vieler verstreuter Hardcoded-Strings soll es ein zentrales Prompt-System geben, das:

- einfacher wartbar ist
- Ton und Regeln konsistent haelt
- neue Textanpassungen billiger macht
- Architektur-Drift durch verstreute Formulierungen reduziert

## Aktueller Handoff-Stand 2026-04-24

Dieser Abschnitt dokumentiert den Stand nach dem ersten grossen Auslagerungsblock, damit die Arbeit spaeter ohne Chat-Verlauf fortgesetzt werden kann.

### Fertig umgesetzt

- `intelligence_modules/prompt_manager/` ist angelegt.
  - zentrale API: `load_prompt(category, template_name, **kwargs)`
  - Frontmatter-Pflicht mit `---`
  - Variablen werden gegen `variables` validiert
  - einfache `{variable}`-Formatierung
  - klare Fehler fuer fehlende Dateien, kaputtes Frontmatter, fehlende oder nicht deklarierte Variablen
- `intelligence_modules/prompts/` ist als Prompt-Root angelegt.
  - `contracts/`
  - `task_loop/`
  - `layers/`
  - `personas/`
- Output-Contracts sind ausgelagert.
  - Container-Contracts:
    - `container_inventory.md`
    - `container_blueprint_catalog.md`
    - `container_state_binding.md`
  - Skill-Catalog-Contract:
    - `skill_catalog.md`
  - Output-Guards:
    - `output_grounding.md`
    - `output_analysis_guard.md`
    - `output_anti_hallucination.md`
    - `output_chat_history.md`
- Output-Dialog/Budget/Legacy-Labels:
    - `output_budget_*.md`
    - `output_dialogue_*.md`
    - `output_tone_*.md`
    - `output_length_*.md`
    - `output_legacy_*.md`
- Output-Fallbacks und Stream-Hinweise:
    - `grounding_fallback_*.md`
    - `tool_failure_fallback_*.md`
    - `output_error_*.md`
    - `output_sync_cloud_provider.md`
    - `output_truncation_*.md`
    - `output_grounding_correction_marker.md`
- Task-Loop-Texte sind in grossen Teilen ausgelagert.
  - `step_runtime.md`
  - `status.md`
  - `clarification.md`
  - Runner-Nachrichten:
    - `risk_gate.md`
    - `control_soft_block.md`
    - `hard_block.md`
    - `waiting.md`
    - `verify_before_complete.md`
  - Chat-Step-Antworten:
    - `chat_default_*.md`
    - `chat_analysis_*.md`
    - `chat_validation_*.md`
    - `chat_implementation_*.md`
  - Container-Request-Wartetexte:
    - `container_python_missing_parameters.md`
    - `container_generic_missing_parameters.md`
    - `container_recognized_parameters.md`
    - `container_blueprint_choice.md`
    - `container_single_blueprint_choice.md`
- `core/layers/output/layer.py` ist stark bereinigt.
  - Container-/Skill-Catalog-Helfer werden nicht mehr dort dupliziert.
  - `_build_messages` delegiert auf `core.layers.output.prompt.system_prompt.build_messages`.
  - `_build_full_prompt` delegiert auf `core.layers.output.prompt.system_prompt.build_full_prompt`.
- `core/layers/output/prompt/system_prompt.py` bleibt der Integrationspunkt fuer den Output-Systemprompt.
  - Entscheidungen bleiben im Code.
  - Wortlaut kommt zunehmend aus `intelligence_modules/prompts/contracts/`.
- `core/task_loop/step_answers.py` ist jetzt matrixartig klein.
  - Es entscheidet nur noch nach `task_kind` und `step_index`.
  - Die sichtbaren Antworttexte liegen in Markdown.
- Control-Layer-Prompts sind im ersten Schnitt ausgelagert.
  - `layers/control.md` enthält den Haupt-`CONTROL_PROMPT`.
  - `layers/control_sequential.md` enthält die alte `SEQUENTIAL_SYSTEM_PROMPT`-Konstante.
  - `core/layers/control/prompting/constants.py` behält die bestehenden Konstantennamen, lädt aber per Prompt-Manager.
- Thinking-Layer-Prompts sind im ersten Schnitt ausgelagert.
  - `layers/thinking.md` enthält den Haupt-`THINKING_PROMPT`.
  - `layers/thinking_memory_context.md`, `thinking_available_tools.md`, `thinking_tone_signal.md`
    und `thinking_user_request.md` enthalten die dynamischen Prompt-Abschnittslabels.
  - `core/layers/thinking.py` behält die bestehende `THINKING_PROMPT`-Konstante, lädt aber per Prompt-Manager.
- Persona-Systemprompt-Bausteine sind ausgelagert.
  - `personas/persona_*.md` enthält Identität, User-Profil, Onboarding, Stil, Tool-Hinweise,
    Container-/Home-/Cron-Hinweise sowie Regeln/Sicherheit.
  - `core/persona.py` behält Parser, Persona-Datenmodell und Auswahlverhalten im Code.

### Wichtige geaenderte Python-Dateien

- `core/layers/output/contracts/container.py`
- `core/layers/output/contracts/skill_catalog/evaluation.py`
- `core/layers/output/layer.py`
- `core/layers/output/prompt/system_prompt.py`
- `core/task_loop/chat_runtime.py`
- `core/task_loop/completion_policy.py`
- `core/task_loop/runner/chat_stream.py`
- `core/task_loop/runner/messages.py`
- `core/task_loop/step_answers.py`
- `core/task_loop/step_runtime/prompting.py`
- `core/task_loop/capabilities/container/parameter_policy.py`
- `core/task_loop/capabilities/container/request_policy.py`
- `core/layers/control/prompting/constants.py`
- `core/layers/thinking.py`
- `core/persona.py`

### Neue/erweiterte Tests

- `tests/unit/test_prompt_manager_loader.py`
- `tests/unit/test_output_prompt_templates_contract.py`
- `tests/unit/test_task_loop_prompt_templates_contract.py`
- `tests/unit/test_task_loop_step_answers_templates.py`
- `tests/unit/test_control_prompt_templates_contract.py`
- `tests/unit/test_thinking_prompt_templates_contract.py`
- `tests/unit/test_persona_prompt_templates_contract.py`

Diese Tests sichern vor allem:

- Prompt-Dateien existieren
- Loader wird genutzt
- alte Inline-Texte wandern nicht zurueck in Python
- gerenderte Chat-Step-Antworten bleiben stabil
- Output-Contracts bleiben an die bestehenden Pfade angebunden

### Zuletzt verifizierte Testlaeufe

Am 2026-04-24 liefen erfolgreich:

- `pytest tests/unit/test_prompt_manager_loader.py`
- `pytest tests/unit/test_task_loop_prompt_templates_contract.py tests/unit/test_task_loop_step_answers_templates.py tests/unit/test_task_loop_runner.py -k 'implementation_chat_step_answers or validation_chat_step_answers or analysis_chat_step_answers or default_chat_step_answers or prompt_templates or internal_loop_analysis_prompt'`
  - Ergebnis: `14 passed, 12 deselected`
- `pytest tests/unit/test_output_prompt_templates_contract.py tests/unit/test_output_tool_injection.py tests/unit/test_output_grounding.py -k 'output_prompt_contract or output_system_prompt or interactive_mode_adds_output_budget_hint or deep_mode_includes_output_budget_hint or dialog_guidance_for_feedback_turn or smalltalk_prompt_adds_no_fabricated_experience_guard or container or skill_catalog or hallucination'`
  - Ergebnis: `30 passed, 39 deselected`
- `pytest tests/unit/test_output_prompt_templates_contract.py tests/unit/test_output_tool_injection.py tests/unit/test_single_truth_channel.py tests/unit/test_orchestrator_context_pipeline.py -k 'output_prompt_contract or output_system_prompt or interactive_mode_adds_output_budget_hint or deep_mode_includes_output_budget_hint or dialog_guidance_for_feedback_turn or smalltalk_prompt_adds_no_fabricated_experience_guard or build_full_prompt or build_messages or single_truth or context_pipeline'`
  - Ergebnis: `110 passed, 2 skipped, 8 deselected`
- `pytest tests/unit/test_output_prompt_templates_contract.py tests/unit/test_task_loop_prompt_templates_contract.py tests/unit/test_single_truth_channel.py::TestNoDoubleInjection::test_legacy_full_prompt_no_tool_injection tests/unit/test_task_loop_step_answers_templates.py`
  - Ergebnis: `17 passed`
- `pytest tests/unit/test_output_prompt_templates_contract.py tests/unit/test_output_grounding.py tests/unit/test_single_truth_channel.py::TestNoDoubleInjection::test_legacy_full_prompt_no_tool_injection tests/unit/test_drift_contracts.py -k 'output_prompt_contract or output_fallback_and_stream_notices or grounding or legacy_full_prompt_no_tool_injection or fallback'`
  - Ergebnis: `67 passed, 75 deselected`
- `pytest tests/unit/test_output_prompt_templates_contract.py`
  - Ergebnis: `4 passed`
- `pytest tests/unit/test_task_loop_prompt_templates_contract.py`
  - Ergebnis: `10 passed`
- `pytest tests/unit/test_task_loop_request_scenarios.py -k 'container_scenarios_request_step_replans_discovery_before_missing_parameter_prompt or python_container_request_uses_defaults_and_replans_blueprint_discovery or python_container_request_replans_blueprint_discovery_before_execution'`
  - Ergebnis: `10 passed, 9 deselected`
- `pytest tests/unit/test_control_prompt_templates_contract.py tests/unit/test_control_decide_tools.py::TestControlDecideTools::test_control_prompt_contains_runtime_soft_warning_rules tests/unit/test_drift_contracts.py -k 'control_prompt_contains_blueprint_gate_rule or blueprint_gate' tests/e2e/test_todays_fixes_e2e.py -k 'control_prompt or blueprint_gate'`
  - Ergebnis: `7 passed, 112 deselected`
- `pytest tests/unit/test_thinking_prompt_templates_contract.py tests/unit/test_thinking_layer_prompt.py tests/unit/test_thinking_followup_prompt.py`
  - Ergebnis: `17 passed`
- `pytest tests/unit/test_persona_prompt_templates_contract.py tests/test_persona.py tests/test_persona_v2.py tests/unit/test_output_tool_injection.py -k 'persona or build_system_prompt or selected_mode_injects_only_selected_tools or none_mode_disables_tool_injection'`
  - Ergebnis: `42 passed, 10 deselected`
- Grosser relevanter Testlauf:
  - `pytest tests/unit/test_prompt_manager_loader.py tests/unit/test_output_prompt_templates_contract.py tests/unit/test_output_tool_injection.py tests/unit/test_output_grounding.py tests/unit/test_task_loop_prompt_templates_contract.py tests/unit/test_task_loop_step_answers_templates.py tests/unit/test_task_loop_request_scenarios.py tests/unit/test_task_loop_runner.py tests/unit/test_control_prompt_templates_contract.py tests/unit/test_control_decide_tools.py tests/unit/test_drift_contracts.py tests/unit/test_thinking_prompt_templates_contract.py tests/unit/test_thinking_layer_prompt.py tests/unit/test_thinking_followup_prompt.py tests/unit/test_persona_prompt_templates_contract.py tests/test_persona.py tests/test_persona_v2.py tests/unit/test_single_truth_channel.py`
  - Ergebnis: `333 passed, 9 warnings`
- `python3 -m compileall` fuer die jeweils geaenderten Python-Dateien war erfolgreich.

### Grobe Reduktionszahlen

Fuer die zentral bearbeiteten Core-Dateien lag der letzte Diff bei:

- `222 insertions`
- `1252 deletions`
- netto ca. `-1030` Core-Zeilen

Einzelne wichtige Reduktionen:

- `core/layers/output/layer.py`: `45 insertions`, `978 deletions`
- `core/task_loop/step_answers.py`: `30 insertions`, `74 deletions`

Das Ziel war nicht nur Zeilenreduktion, sondern vor allem:

- Prompt-Wortlaut raus aus Python
- zentrale Source of Truth in Markdown
- Verhaltenslogik weiterhin im Code

### Aktueller Prompt-Datei-Stand

Zum Zeitpunkt dieses Handoffs gibt es `110` Dateien unter `intelligence_modules/prompts/`.

Wichtig: Viele Dateien sind neu und untracked, weil noch kein Commit erstellt wurde.
Vor einem Commit deshalb immer `git status --short` pruefen.

### Naechste sinnvolle Schritte

1. Noch offene kurze Output-/Fallback-Texte pruefen.
   - Bereits erledigt:
     - `core/layers/output/grounding/fallback.py`
     - zentrale Streaming-Fehlermeldungen in `core/layers/output/generation/*.py`
     - entsprechende Legacy-Duplikate in `core/layers/output/layer.py`
   - Weiterer Kandidat:
     - vereinzelte restliche User-sichtbare Fehlermeldungen in `core/layers/output/layer.py`, falls sie noch nicht von `generation/*` abgedeckt sind
   - Wichtig: Nur Text auslagern, nicht Postcheck-/Repair-Logik verschieben.

2. Task-Loop-Container-Parametertexte pruefen.
   - Erledigt:
     - `core/task_loop/capabilities/container/parameter_policy.py`
     - `core/task_loop/capabilities/container/request_policy.py`
   - Die User-Rueckfrage-/Choice-Texte liegen jetzt in `task_loop/container_*.md`.
   - Verhalten, Parameterauswahl und Blueprint-Auswahl bleiben im Code.

3. Danach erst groessere Layer-Prompts angehen.
   - Bereits erledigt:
     - `core/layers/control/prompting/constants.py`
     - `core/layers/thinking.py`
     - `core/persona.py`
   - Die grossen Layer-Prompts sind damit im ersten Schnitt zentralisiert.

4. Vor groesseren weiteren Schnitten einen Gesamt-Testlauf planen.
   - Mindestens Output + Task-Loop + relevante Routing-/Grounding-Tests.
   - Danach erst committen.

### Arbeitsregel fuer die Fortsetzung

Bei jedem weiteren Block gilt:

- erst harte Strings finden
- entscheiden, ob es wirklich Wortlaut ist
- Markdown-Template mit Frontmatter anlegen
- Python nur als Auswahl-/Variablenlogik behalten
- Contract-/Drift-Test ergaenzen
- gezielte Tests laufen lassen

Nicht verschieben:

- Routing
- Policy-Gates
- Tool-Auswahl
- Postcheck-/Repair-Entscheidungen
- Orchestrator-Fluss

Kurzform:

Text darf zentralisiert werden.
Verhalten bleibt explizit im Code.
