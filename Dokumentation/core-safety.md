# Core Safety Analysis (`core/safety`)

## Übersicht

Das `core/safety` Modul ("LightCIM") fungiert als erste Sicherheitslinie für **jeden** Request. Es ist auf extreme Geschwindigkeit (<50ms) optimiert und führt grundlegende Plausibilitäts- und Sicherheitschecks durch, bevor der Control-Layer (Qwen) eingeschaltet wird.

## Struktur & Module

### 1. `light_cim.py` (Light Causal Intelligence Module)

- **Klasse**: `LightCIM`
- **Funktion**: Schnelle Validierung von User-Anfragen.
- **Hauptmethoden**:
  - `validate_basic`: Hauptfunktion, die alle Checks orchestriert.
  - `validate_intent`: Prüft auf "gefährliche" Keywords (Gewalt, Illegalität, etc.) und Intent-Klarheit.
  - `check_logic_basic`: Prüft logische Konsistenz (z.B. "Ich will ein Fakt speichern, habe aber keinen Key/Value angegeben").
  - `safety_guard_lite`: Prüft auf PII (Email, Telefon) und sensitive Themen (Passwörter, API Keys).
  - `_should_escalate`: Entscheidung, ob die Anfrage an die "Full CIM" (Sequential Thinking Engine) eskaliert werden muss (z.B. bei komplexen Multi-Step Aufgaben oder hohem Halluzinationsrisiko).

## Wichtige Imports & Abhängigkeiten

- `re`: Reguläre Ausdrücke für Pattern-Matching (PII Detection).
- Standard Typing (`Dict`, `Any`, `List`).

## Sicherheits-Features

### Keyword Listen

Das Modul arbeitet mit statischen Keyword-Listen für maximale Performance:

- `danger_keywords`: Begriffe aus Bereichen wie Gewalt, Waffen, illegale Aktivitäten.
- `sensitive_keywords`: Finanzdaten, Authentifizierungsdaten (API Keys, Passwörter).

### Eskalations-Logik

LightCIM entscheidet nicht nur über "Sicher/Unsicher", sondern auch über die **Komplexität**. Wenn LightCIM feststellt, dass eine Anfrage zu komplex ist (z.B. "Analysiere X und vergleiche mit Y"), setzt es das `should_escalate` Flag, was dem Control-Layer signalisiert, dass Sequential Thinking oder eine tiefere Analyse notwendig sein könnte.

### Validierung

Der Output enthält nicht nur boolesche Flags, sondern detaillierte Warnungen (`warnings`) und einen `confidence` Score, den nachgelagerte Systeme nutzen können.
