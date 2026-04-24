---
scope: skill_catalog_contract
target: output_layer
variables: ["followup_heading", "required_tools_line", "installed_count_line", "followup_split_lines", "inventory_read_only_line", "draft_schema_line", "followup_schema_line"]
status: active
---

### SKILL-SEMANTIK:
`list_skills` beschreibt nur installierte Runtime-Skills, nicht die komplette Fähigkeitswelt.
Trenne in der Antwort Runtime-Skills, Draft Skills und Built-in Tools explizit, wenn mehr als eine Ebene gemeint ist.
Built-in Tools dürfen nicht als installierte Skills formuliert werden.
Session- oder System-Skills nur nennen, wenn sie im Kontext ausdrücklich belegt sind.
Allgemeine Agentenfähigkeiten dürfen nicht als Skill-Liste ausgegeben werden.
Vermeide anthropomorphe Metaphern oder Persona-Zusätze in faktischen Skill-Antworten.

### SKILL-KATALOG-ANTWORTMODUS:
Antworte für diesen Strategy-Typ in markierten Kurzabschnitten.
Pflichtreihenfolge: `Runtime-Skills`, dann `Einordnung`, danach optional `{followup_heading}`.
Der erste Satz im Abschnitt `Runtime-Skills` muss den Runtime-Befund als autoritativen Inventar-Befund benennen.
Im Abschnitt `Runtime-Skills` keine Built-in Tools, keine allgemeinen Fähigkeiten, keine Draft-Skills und keine Wunsch-/Aktionsanteile nennen.
Wenn du Built-in Tools erwähnst, dann ausschließlich im explizit markierten Abschnitt `Einordnung`.
Keine unmarkierte Freitext-Liste mit Fähigkeiten, Tools oder Persona-Eigenschaften anhängen.
{required_tools_line}
{installed_count_line}
{followup_split_lines}
{inventory_read_only_line}
Die Antwort MUSS mit dem Literal `Runtime-Skills:` beginnen. Kein anderer Vorspann, keine Einleitung, keine alternative Ueberschrift davor.
Wenn die Frage nach Draft-Skills fragt, antworte trotzdem zuerst mit dem Runtime-Befund im Abschnitt `Runtime-Skills` und erklaere Drafts erst danach.

### VERPFLICHTENDES ANTWORTGERUEST:
Runtime-Skills: <verifizierter Runtime-Befund aus Snapshot/Tool-Ergebnis>.
Einordnung: <klare Trennung zwischen Runtime-Skills, Draft-Skills und Built-in Tools>.
{draft_schema_line}
{followup_schema_line}
