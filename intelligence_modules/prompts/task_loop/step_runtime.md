---
scope: task_loop_step_runtime
target: task_loop
variables: ["current_step_index", "total_steps", "objective", "step_title", "step_type", "goal", "done_criteria", "completed_text", "verified_context_block", "system_addon_block", "next_step_guard_block", "auto_clarify_block", "claim_guard_block", "focus_block", "output_shape_block", "response_style"]
status: active
---

Task-Loop Schritt {current_step_index}/{total_steps}

Aufgabe: {objective}
Aktueller Schritt: {step_title}
Schritt-Typ: {step_type}
Ziel dieses Schritts: {goal}
Erfolgskriterium: {done_criteria}
Bisherige Schritte: {completed_text}

{verified_context_block}{system_addon_block}{next_step_guard_block}{auto_clarify_block}{claim_guard_block}{focus_block}{output_shape_block}{response_style}Bleibe knapp und beim aktuellen Schritt.
