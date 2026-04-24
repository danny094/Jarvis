from core.task_loop.step_answers import answer_for_chat_step


def test_default_chat_step_answers_render_from_templates():
    assert answer_for_chat_step(
        1,
        "Ziel klaeren",
        {"task_kind": "default", "objective": "sauber testen"},
        [],
    ) == (
        "Aufgabe: sauber testen. Erfolg heisst, dass der naechste Schritt konkret, "
        "sicher und fuer den User nachvollziehbar ist."
    )

    assert answer_for_chat_step(2, "Weiter", {"task_kind": "default"}, []) == (
        "Naechster sicherer Schritt: im Chat bleiben, den kleinsten sinnvollen "
        "Fortschritt benennen und externe Nebenwirkungen ausklammern."
    )

    assert answer_for_chat_step(3, "Stop pruefen", {"task_kind": "default"}, ["eins"]) == (
        "Stoppruefung: Bisher abgeschlossen: eins. Kein riskanter Pfad wird "
        "automatisch ausgefuehrt; bei Unsicherheit oder Wiederholung wird pausiert."
    )

    assert answer_for_chat_step(4, "Fertig", {"task_kind": "default"}, []) == (
        "Status: Die Aufgabe ist im sicheren Chat-Rahmen sortiert. Der naechste "
        "Pfad ist klar genug, um gezielt weiterzuplanen oder bei Bedarf nachzufragen."
    )


def test_analysis_chat_step_answers_render_from_templates():
    assert answer_for_chat_step(
        1,
        "Analyse",
        {"task_kind": "analysis", "objective": "Loop pruefen"},
        [],
    ) == (
        "Fragestellung: Loop pruefen. Die Antwort muss klaeren, was belastbar aus "
        "dem aktuellen Chat-Kontext folgt und wo der Loop stoppen oder nachfragen muss."
    )

    assert answer_for_chat_step(2, "Analyse", {"task_kind": "analysis"}, []) == (
        "Einflussfaktoren: expliziter Multistep-Start, Planqualitaet, sichtbare "
        "Zwischenstaende, Reflection, Risk-Gates, Progress-Erkennung und harte "
        "Limits fuer Steps, Errors und Wiederholung."
    )

    assert answer_for_chat_step(3, "Analyse", {"task_kind": "analysis"}, ["eins"]) == (
        "Unsicherheiten: Bisher abgeschlossen: eins. Ohne externe Pruefung bleibt "
        "der Befund auf Chat-Kontext begrenzt. Stoppen ist korrekt, wenn Kontext "
        "fehlt, Risiko entsteht oder kein konkreter naechster Schritt ableitbar ist."
    )

    assert answer_for_chat_step(4, "Analyse", {"task_kind": "analysis"}, []) == (
        "Zwischenfazit: Der sichere Analysepfad ist abgeschlossen. Der naechste "
        "sinnvolle Schritt ist, die erkannte Luecke gezielt zu beheben statt den "
        "Loop blind weiterlaufen zu lassen."
    )


def test_validation_chat_step_answers_render_from_templates():
    assert answer_for_chat_step(
        1,
        "Pruefung",
        {"task_kind": "validation", "objective": "Loop pruefen"},
        [],
    ) == (
        "Pruefziel: Loop pruefen. Erfolgskriterium: Der Loop liefert einen "
        "sichtbaren Plan, erzeugt nachvollziehbare Zwischenstaende, reflektiert "
        "Stopbedingungen und bleibt im Chat-only Rahmen ohne Tools, Shell oder Writes."
    )

    assert answer_for_chat_step(2, "Pruefung", {"task_kind": "validation"}, []) == (
        "Beobachtbare Kriterien: Planpunkte muessen zur Anfrage passen; jeder "
        "Zwischenstand muss einen konkreten Befund statt nur eine Statusfloskel "
        "enthalten; riskante Folgepfade muessen vor Ausfuehrung stoppen."
    )

    assert answer_for_chat_step(3, "Pruefung", {"task_kind": "validation"}, ["eins"]) == (
        "Befund: Der aktuelle Pfad bleibt sicher, weil keine externe Aktion "
        "ausgefuehrt wird. Bisher abgeschlossen: eins. Stop wuerde bei riskantem "
        "Tool-/Shell-/Write-Pfad, unklarem Ziel, fehlendem Fortschritt, Wiederholung "
        "oder Step-/Error-Limit greifen."
    )

    assert answer_for_chat_step(4, "Pruefung", {"task_kind": "validation"}, []) == (
        "Zusammenfassung: Die Pruefung ist als Chat-only Zwischenstand abgeschlossen. "
        "Naechster Produktpfad: die Zwischenstaende weiter von reinen Templates loesen "
        "und spaeter echte Tool-/Shell-Schritte erst hinter Risk-Gates aktivieren."
    )


def test_implementation_chat_step_answers_render_from_templates():
    assert answer_for_chat_step(
        1,
        "Umsetzung",
        {"task_kind": "implementation", "objective": "Loop bauen"},
        [],
    ) == (
        "Zielbild: Loop bauen. Der sichere erste Schnitt ist ein kleiner, "
        "beobachtbarer Chat-Loop, der Zustand, Plan, Zwischenstand und Stopgrund "
        "sauber trennt."
    )

    assert answer_for_chat_step(2, "Umsetzung", {"task_kind": "implementation"}, []) == (
        "Umsetzungsschnitt: Planer, Runner, Reflection und Gates bleiben getrennt. "
        "Der naechste sichere Schritt darf nur Chat-Zustand und sichtbare Antwort "
        "veraendern, keine Tools oder Shell ausfuehren."
    )

    assert answer_for_chat_step(3, "Umsetzung", {"task_kind": "implementation"}, ["eins"]) == (
        "Gate-Bewertung: Bisher abgeschlossen: eins. Automatisch weiter geht nur, "
        "solange der Schritt safe ist. Bei User-Entscheidung, riskantem Tool, Write, "
        "Shell, Wiederholung oder Fehlerlimit wird pausiert."
    )

    assert answer_for_chat_step(4, "Umsetzung", {"task_kind": "implementation"}, []) == (
        "Naechster Implementierungsschnitt: echte Ausfuehrungssignale und bessere "
        "Plan-Revisionen anbinden, ohne den Orchestrator-Monolithen weiter wachsen "
        "zu lassen."
    )
