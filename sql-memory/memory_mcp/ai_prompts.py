"""
AI Prompts für Memory Maintenance Sorting
"""

# STM → LTM Promotion Prompt
PROMOTION_PROMPT = """Du bist ein Memory-Klassifizierer.

Analysiere diesen Memory-Eintrag und entscheide ob er von STM (Short-Term) zu LTM (Long-Term) promoted werden soll.

EINTRAG:
ID: {entry_id}
Content: "{content}"
Erstellt: {created_at}
Alter: {age_days} Tage

KRITERIEN FÜR LTM:
✅ Dauerhafte Fakten (Name, Wohnort, Beruf, Hobbies)
✅ Wichtige Präferenzen (Lieblingsessen, Abneigungen)
✅ Beziehungen (Familie, Freunde, Kollegen)
✅ Langfristige Ziele/Pläne
✅ Wichtige Ereignisse mit Langzeitwirkung

KRITERIEN FÜR STM BLEIBEN:
❌ Temporäre Stimmungen/Gefühle
❌ Kurzfristige Pläne (heute, morgen)
❌ Aktuelle Events ohne Dauerwirkung
❌ Kontext-gebundene Infos

DENKE LAUT:
Analysiere den Inhalt und erkläre deine Entscheidung.

FORMAT:
Decision: [PROMOTE/KEEP]
Confidence: [0-100]%
Reasoning: [Deine Erklärung]"""


# Duplicate Detection Prompt
DUPLICATE_PROMPT = """Du bist ein Duplicate-Detector.

Vergleiche diese beiden Memory-Einträge:

ENTRY A:
ID: {entry_a_id}
Content: "{entry_a_content}"

ENTRY B:
ID: {entry_b_id}
Content: "{entry_b_content}"

FRAGEN:
1. Enthalten sie die GLEICHE Information?
2. Ist einer redundant?
3. Semantische Ähnlichkeit?

FORMAT:
Decision: [DUPLICATE/DIFFERENT]
Similarity: [0-100]%
Keep: [Entry A ID / Entry B ID / Both]
Reasoning: [Erklärung]"""


# Summary Creation Prompt
SUMMARY_PROMPT = """Du bist ein Memory-Zusammenfasser.

Erstelle eine kompakte MTM (Mid-Term Memory) Zusammenfassung aus diesen STM Einträgen:

EINTRÄGE:
{entries}

ANFORDERUNGEN:
✅ Kernaussagen bewahren
✅ Redundanz eliminieren
✅ Chronologischer Kontext erhalten
✅ Maximal 200 Zeichen
✅ Deutsch

FORMAT:
Summary: [Deine Zusammenfassung]
Entries_Combined: [Anzahl]
Reasoning: [Kurze Erklärung]"""


# Slow Mode Validation Prompt
VALIDATION_PROMPT = """Du bist ein Quality Validator.

Das Primary Model hat folgende Entscheidung getroffen:

ORIGINAL ENTRY:
"{content}"

PRIMARY DECISION:
Action: {action}
Reasoning: {reasoning}
Confidence: {confidence}%

DEINE AUFGABE:
Validiere diese Entscheidung kritisch.

FORMAT:
Decision: [APPROVE/REJECT]
Confidence: [0-100]%
Reasoning: [Deine Analyse]"""
