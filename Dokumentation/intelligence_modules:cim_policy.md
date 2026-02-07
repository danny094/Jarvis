# CIM Policy Engine (`intelligence_modules/cim_policy/`)

## Übersicht

Die CIM Policy Engine (Cognitive Intent Mapping) ist das Sicherheits- und Steuerungssystem für die Autonomie von TRION. Sie entscheidet deterministisch (nicht per LLM), ob eine Aktion ausgeführt werden darf, ob ein neuer Skill erstellt werden soll oder ob eine Bestätigung des Users erforderlich ist.

## Hauptkomponenten

### 1. `cim_policy_engine.py`

Die zentrale Logik.

- **Workflow**: `User Input` → `Intent Matching` (Regex) → `Policy Lookup` → `Skill Name Derivation` → `Action Decision`.
- **Sicherheit**: Prüft `SafetyLevel` (LOW bis CRITICAL) und `SkillScope`. Blockiert kritische Aktionen (z.B. "Hacke Server") oder fordert Bestätigung an.
- **Fähigkeiten**:
  - **Skill Ableitung**: Generiert deterministische Skill-Namen aus dem User-Input (z.B. "Berechne Fibonacci" → `auto_calculation_fibonacci`).
  - **Auto-Coding**: Wenn `force_create_skill` aktiv ist, wird Code basierend auf Templates generiert.

### 2. `cim_policy.csv`

Das "Gehirn" der Engine. Eine Tabelle mit Regeln:
- `pattern_id`: Eindeutige ID.
- `trigger_regex`: Regex zum Erkennen der Absicht.
- `action_if_missing`: Was tun, wenn der Skill nicht existiert? (z.B. `force_create_skill`, `fallback_chat`).
- `action_if_present`: Was tun, wenn er existiert? (z.B. `run_skill`).
- `safety_level`: Wie gefährlich ist das? (`low`, `medium`, `high`, `critical`).
- `requires_confirmation`: Muss der User "Ja" sagen?

### 3. `skill_templates.csv`

Vorlagen für Auto-Coding. Wenn die Policy entscheidet "Erstelle Skill", wird hier nach passendem Code gesucht (basierend auf Keywords).

## Beispiel-Flow

1. **User**: "Lies die Datei test.txt"
2. **Engine**:
    - Matched Pattern `file_ops` (Regex: `lies datei`).
    - Policy: `safety_level` = HIGH, `requires_confirmation` = TRUE.
3. **Entscheidung**: `ActionType.REQUEST_USER_CONFIRMATION`.
4. **Bot**: "Soll ich den Skill 'auto_filesystem_read' wirklich ausführen?"
