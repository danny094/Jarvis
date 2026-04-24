---
scope: task_loop_chat_answer
target: implementation_step_3
variables: ["prior_context"]
status: active
---

Gate-Bewertung: {prior_context} Automatisch weiter geht nur, solange der Schritt safe ist. Bei User-Entscheidung, riskantem Tool, Write, Shell, Wiederholung oder Fehlerlimit wird pausiert.
