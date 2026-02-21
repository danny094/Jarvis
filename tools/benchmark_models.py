#!/usr/bin/env python3
"""
TRION Model Benchmark
Vergleicht aktuelle Multi-Model Architektur vs. Single-Model (ministral-3:14b)

Misst:
- Latenz pro Layer (ThinkingLayer JSON, ControlLayer JSON, OutputLayer Text)
- JSON-Zuverlässigkeit (valid JSON Ausgabe?)
- Tokens/Sekunde
- VRAM-Verhalten (Swapping erkennbar durch Ladezeit)

Verwendung:
  python3 tools/benchmark_models.py          # 2 Runs pro Test
  python3 tools/benchmark_models.py 3        # 3 Runs pro Test
"""

import json
import time
import httpx
import statistics
import sys
from datetime import datetime

OLLAMA_BASE = "http://localhost:11434"

# ─── Modell-Konfigurationen ───────────────────────────────────────────────────

CONFIGS = {
    "constrained_multi": {
        "label": "Multi-Model + Constraints (format:json, temp:0.1)",
        "thinking": "ministral-3:8b",
        "control":  "qwen3:4b",
        "output":   "ministral-3:3b",
        "think_options": {"format": "json", "temperature": 0.1, "num_predict": 800},
        "ctrl_options":  {"format": "json", "temperature": 0.1, "num_predict": 600},
    },
    "single_14b_constrained": {
        "label": "Ministral-3:14B + Constraints (format:json, temp:0.1)",
        "thinking": "ministral-3:14b",
        "control":  "ministral-3:14b",
        "output":   "ministral-3:3b",  # Output bleibt klein!
        "think_options": {"format": "json", "temperature": 0.1, "num_predict": 800},
        "ctrl_options":  {"format": "json", "temperature": 0.1, "num_predict": 600},
    },
}

# ─── Test-Prompts ─────────────────────────────────────────────────────────────

THINKING_PROMPT_TEMPLATE = """Du bist der THINKING-Layer. Analysiere die Anfrage und antworte NUR mit JSON:
{{"intent": "...", "needs_memory": true/false, "suggested_tools": [], "sequential_complexity": 0}}

USER-ANFRAGE: {query}
Deine Ausgabe (nur JSON):"""

CONTROL_PROMPT_TEMPLATE = """Du bist der CONTROL-Layer. Verifiziere den Plan und antworte NUR mit JSON:
{{"approved": true, "corrections": {{}}, "warnings": [], "final_instruction": "..."}}

PLAN: {plan}
Deine Ausgabe (nur JSON):"""

OUTPUT_PROMPT_TEMPLATE = """Du bist TRION, ein freundlicher AI-Assistent. Beantworte kurz und präzise.

AUFGABE: {task}
ANTWORT:"""

TEST_CASES = [
    {
        "name": "Einfache Frage",
        "query": "Was ist die Hauptstadt von Deutschland?",
    },
    {
        "name": "Tool-Planung (Skill)",
        "query": "Erstelle einen Skill der den Bitcoin-Kurs abruft",
    },
    {
        "name": "System-Hardware",
        "query": "Wie viel VRAM habe ich noch frei?",
    },
    {
        "name": "Komplexe Aufgabe",
        "query": "Erkläre kurz den Unterschied zwischen Python und Go für Microservices",
    },
]


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def generate(model: str, prompt: str, timeout: float = 90.0, extra_options: dict = None) -> dict:
    """Ruft Ollama /api/generate auf und misst Latenz + Tokens."""
    t0 = time.time()
    first_token_time = None
    full_response = ""
    token_count = 0

    base_options = {"num_ctx": 2048, "num_predict": 512}
    if extra_options:
        # format ist top-level, nicht in options
        base_options.update({k: v for k, v in extra_options.items() if k != "format"})

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": "5m",
        "options": base_options,
    }
    if extra_options and "format" in extra_options:
        payload["format"] = extra_options["format"]

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST",
                f"{OLLAMA_BASE}/api/generate",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        chunk = data.get("response", "")
                        if chunk:
                            if first_token_time is None:
                                first_token_time = time.time() - t0
                            full_response += chunk
                            token_count += 1
                        if data.get("done"):
                            break
                    except Exception:
                        continue
    except httpx.TimeoutException:
        return {"error": "TIMEOUT", "duration": round(time.time() - t0, 2)}
    except Exception as e:
        return {"error": str(e)[:80], "duration": round(time.time() - t0, 2)}

    total_time = time.time() - t0
    tps = token_count / total_time if total_time > 0 else 0

    return {
        "response": full_response,
        "duration": round(total_time, 2),
        "first_token": round(first_token_time or 0, 2),
        "tokens": token_count,
        "tps": round(tps, 1),
        "error": None,
    }


def is_valid_json(text: str) -> bool:
    """Prüft ob der Text valides JSON enthält (auch wenn in Markdown-Block)."""
    import re
    text = text.strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        json.loads(text[start:end])
        return True
    except (ValueError, json.JSONDecodeError):
        return False


def warmup_model(model: str):
    """Wärmt das Modell auf (erster Call lädt es in VRAM)."""
    print(f"  ♻️  Aufwärmen: {model}...", end=" ", flush=True)
    result = generate(model, "Sag nur: bereit", timeout=120.0)
    if result.get("error"):
        print(f"FEHLER: {result['error']}")
    else:
        print(f"OK  (Ladezeit: {result['first_token']}s, {result['tps']} t/s)")


def run_benchmark_for_config(config_key: str, config: dict, runs: int = 2) -> dict:
    """Führt den kompletten Benchmark für eine Config aus."""
    print(f"\n{'═'*62}")
    print(f"  {config['label']}")
    print(f"{'═'*62}")

    # Modelle aufwärmen (Duplikate vermeiden)
    warmed = set()
    for layer in ["thinking", "control", "output"]:
        m = config[layer]
        if m not in warmed:
            warmup_model(m)
            warmed.add(m)

    results = []

    for tc in TEST_CASES:
        print(f"\n  📋 {tc['name']}")
        case_results = {"name": tc["name"], "runs": []}

        for run in range(runs):
            run_result = {}

            # Layer 1: Thinking (JSON)
            r1 = generate(
                config["thinking"],
                THINKING_PROMPT_TEMPLATE.format(query=tc["query"]),
                extra_options=config.get("think_options"),
            )
            run_result["thinking"] = {k: v for k, v in r1.items() if k != "response"}
            run_result["thinking_json_ok"] = is_valid_json(r1.get("response", ""))
            run_result["thinking_response"] = r1.get("response", "")[:200]

            # Layer 2: Control (JSON)
            r2 = generate(
                config["control"],
                CONTROL_PROMPT_TEMPLATE.format(plan=r1.get("response", "{}")[: 300]),
                extra_options=config.get("ctrl_options"),
            )
            run_result["control"] = {k: v for k, v in r2.items() if k != "response"}
            run_result["control_json_ok"] = is_valid_json(r2.get("response", ""))

            # Layer 3: Output (Text) — keine Constraints, freier Text
            r3 = generate(config["output"], OUTPUT_PROMPT_TEMPLATE.format(task=tc["query"]))
            run_result["output"] = {k: v for k, v in r3.items() if k != "response"}
            run_result["output_preview"] = r3.get("response", "")[:100]

            total = round(
                r1.get("duration", 0) + r2.get("duration", 0) + r3.get("duration", 0), 2
            )
            run_result["total"] = total

            # Fehler?
            errors = [r for r in [r1, r2, r3] if r.get("error")]
            t_ok = "✓" if run_result["thinking_json_ok"] else "✗"
            c_ok = "✓" if run_result["control_json_ok"] else "✗"
            err_str = f"  ⚠️ {errors[0]['error']}" if errors else ""

            print(
                f"    [{run+1}] Gesamt: {total:.1f}s | "
                f"Think: {r1.get('duration','?')}s (JSON{t_ok}, {r1.get('tps','?')}t/s) | "
                f"Ctrl: {r2.get('duration','?')}s (JSON{c_ok}) | "
                f"Out: {r3.get('duration','?')}s"
                f"{err_str}"
            )

            case_results["runs"].append(run_result)

        results.append(case_results)

    return {"config": config, "results": results}


def print_summary(all_results: dict):
    """Druckt eine vergleichende Zusammenfassung."""
    print(f"\n\n{'═'*62}")
    print("  ERGEBNIS-VERGLEICH")
    print(f"{'═'*62}\n")

    summaries = {}

    for config_key, data in all_results.items():
        totals, think_times, ctrl_times, out_times = [], [], [], []
        json_ok = json_total = 0

        for tc_result in data["results"]:
            for run in tc_result["runs"]:
                totals.append(run["total"])
                t = run["thinking"].get("duration", 0)
                c = run["control"].get("duration", 0)
                o = run["output"].get("duration", 0)
                if t: think_times.append(t)
                if c: ctrl_times.append(c)
                if o: out_times.append(o)
                json_total += 2
                if run.get("thinking_json_ok"): json_ok += 1
                if run.get("control_json_ok"): json_ok += 1

        def avg(lst): return round(statistics.mean(lst), 1) if lst else 0

        summaries[config_key] = {
            "label": data["config"]["label"],
            "avg_total": avg(totals),
            "min_total": round(min(totals), 1) if totals else 0,
            "avg_think": avg(think_times),
            "avg_ctrl":  avg(ctrl_times),
            "avg_out":   avg(out_times),
            "json_pct":  round(json_ok / json_total * 100) if json_total else 0,
        }

    cm  = summaries.get("current_multi", {})
    s14 = summaries.get("single_14b", {})

    def w(a, b, lower=True):
        if not a or not b or a == b: return ""
        better = a < b if lower else a > b
        return "  ◄ Multi" if better else "  ◄ 14B"

    rows = [
        ("Ø Gesamtzeit",          cm.get("avg_total"), s14.get("avg_total"), True,  "s"),
        ("Schnellste Antwort",    cm.get("min_total"), s14.get("min_total"), True,  "s"),
        ("Ø ThinkingLayer",       cm.get("avg_think"), s14.get("avg_think"), True,  "s"),
        ("Ø ControlLayer",        cm.get("avg_ctrl"),  s14.get("avg_ctrl"),  True,  "s"),
        ("Ø OutputLayer",         cm.get("avg_out"),   s14.get("avg_out"),   True,  "s"),
        ("JSON-Zuverlässigkeit",  cm.get("json_pct"),  s14.get("json_pct"),  False, "%"),
    ]

    col_w = 28
    print(f"  {'Metrik':{col_w}} {'Multi-Model':>12} {'14B Single':>12}  Gewinner")
    print(f"  {'-'*col_w} {'-'*12} {'-'*12}  {'-'*10}")

    for label, a, b, lower, unit in rows:
        a_s = f"{a}{unit}" if a is not None else "—"
        b_s = f"{b}{unit}" if b is not None else "—"
        print(f"  {label:{col_w}} {a_s:>12} {b_s:>12}{w(a,b,lower)}")

    print()

    # Empfehlung
    multi_score = sum([
        1 if (cm.get("avg_total", 999) < s14.get("avg_total", 999)) else 0,
        1 if (cm.get("json_pct", 0) >= s14.get("json_pct", 0)) else 0,
    ])
    s14_score = 2 - multi_score

    print(f"  {'─'*60}")
    if multi_score > s14_score:
        print(f"  🏆 Empfehlung: Multi-Model (aktuell) bleibt vorne")
    elif s14_score > multi_score:
        print(f"  🏆 Empfehlung: Wechsel auf Ministral-3:14B lohnt sich!")
    else:
        print(f"  🤝 Unentschieden — JSON-Qualität für Entscheidung prüfen")
    print()


def save_results(all_results: dict):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/trion_benchmark_{ts}.json"
    with open(path, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"  💾 Rohdaten gespeichert: {path}\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 2

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           TRION Model Benchmark — {datetime.now().strftime('%Y-%m-%d %H:%M')}            ║
╠══════════════════════════════════════════════════════════════╣
║  Multi-Model (3x klein)  vs.  Ministral-3:14B (Single)       ║
║  Runs pro Test: {runs:<2}    Tests: {len(TEST_CASES):<2}    Layer: 3                  ║
╚══════════════════════════════════════════════════════════════╝
""")

    all_results = {}
    for config_key, config in CONFIGS.items():
        all_results[config_key] = run_benchmark_for_config(config_key, config, runs=runs)

    print_summary(all_results)
    save_results(all_results)
    print("  ✅ Fertig.\n")
