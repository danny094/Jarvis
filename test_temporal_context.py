"""
Testsuite: Temporal Context Pipeline
Prüft jeden Schritt ob das Tagesprotokoll korrekt durchläuft.
"""
import asyncio
import sys
import os
sys.path.insert(0, "/app")
os.environ.setdefault("PYTHONPATH", "/app")

# ─── Test 1: Protokoll-Datei direkt ───────────────────────────────────────────
def test_protocol_file():
    from pathlib import Path
    from datetime import date
    protocol_dir = Path(os.environ.get("PROTOCOL_DIR", "/app/memory"))
    today = date.today().isoformat()
    f = protocol_dir / f"{today}.md"
    exists = f.exists()
    size = f.stat().st_size if exists else 0
    content_preview = f.read_text()[:500] if exists else "(LEER)"
    print(f"\n[TEST 1] Protokoll-Datei: {f}")
    print(f"  Existiert: {exists}, Größe: {size} bytes")
    print(f"  Vorschau:\n{content_preview}")
    assert exists and size > 100, f"FAIL: Protokoll fehlt oder leer ({size} bytes)"
    print("  ✓ PASS")
    return content_preview

# ─── Test 2: ContextManager.get_context() mit time_reference=today ────────────
def test_context_manager():
    from core.context_manager import ContextManager
    cm = ContextManager()
    thinking_plan = {
        "needs_memory": True,
        "is_fact_query": True,
        "memory_keys": ["today_topic"],
        "time_reference": "today",
        "suggested_tools": ["memory_graph_search"],
    }
    result = cm.get_context(
        query="was haben wir heute besprochen",
        thinking_plan=thinking_plan,
        conversation_id="test-conv-123"
    )
    print(f"\n[TEST 2] ContextManager.get_context()")
    print(f"  sources: {result.sources}")
    print(f"  memory_used: {result.memory_used}")
    print(f"  memory_data Länge: {len(result.memory_data)} chars")
    print(f"  memory_data Vorschau:\n{result.memory_data[:800]}")

    # Guard prüfen: kein graph/fact in sources
    assert "memory:today_topic" not in result.sources, \
        f"FAIL: Graph/Fact-Suche wurde NICHT geblockt! sources={result.sources}"
    # Protokoll muss drin sein
    assert "daily_protocol" in result.sources, \
        f"FAIL: Protokoll fehlt in sources! sources={result.sources}"
    assert len(result.memory_data) > 200, \
        f"FAIL: memory_data zu kurz ({len(result.memory_data)} chars)"
    print("  ✓ PASS — Temporal Guard aktiv, Protokoll geladen")
    return result.memory_data

# ─── Test 3: Orchestrator-Guard (time_reference blockiert memory_graph_search) ─
def test_orchestrator_guard():
    """Prüft dass _execute_tools_sync memory_graph_search überspringt."""
    from core.orchestrator import PipelineOrchestrator
    orch = PipelineOrchestrator()

    tools = ["memory_graph_search"]
    result = orch._execute_tools_sync(
        suggested_tools=tools,
        user_text="was haben wir heute besprochen",
        control_tool_decisions={},
        time_reference="today"
    )
    print(f"\n[TEST 3] Orchestrator Guard")
    print(f"  tool_context: '{result[:200] if result else '(LEER)'}'")

    assert result == "" or "memory_graph_search" not in result.lower(), \
        f"FAIL: memory_graph_search wurde ausgeführt! result='{result[:200]}'"
    print("  ✓ PASS — memory_graph_search geblockt")

# ─── Test 4: OutputLayer sieht Protokoll im Prompt ───────────────────────────
async def test_output_layer_context(memory_data: str):
    """Prüft ob OutputLayer mit Protokoll-Kontext korrekte Antwort gibt."""
    from core.layers.output import OutputLayer
    layer = OutputLayer()

    test_prompt = f"""Du bist TRION.

TAGESPROTOKOLL:
{memory_data[:2000]}

Beantworte die Frage NUR basierend auf dem Tagesprotokoll oben.
Falls du die Antwort nicht im Protokoll findest, sage: "Ich finde es nicht im Protokoll."
Halluziniere NICHT.

User: was haben wir heute am meisten besprochen?
TRION:"""

    print(f"\n[TEST 4] OutputLayer Antwort mit Protokoll-Kontext")
    response = ""
    async for chunk in layer.generate_stream(test_prompt):
        response += chunk

    print(f"  Antwort: {response[:500]}")

    hallucination_keywords = ["arbeitswelt", "automatisierung", "berufsfelder", "nachhaltigkeit", "midjourney"]
    found_hallucination = any(kw in response.lower() for kw in hallucination_keywords)

    assert not found_hallucination, \
        f"FAIL: OutputLayer halluziniert! Antwort enthält generische KI-Themen."
    print("  ✓ PASS — Keine Halluzination")

# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("TRION Temporal Context Testsuite")
    print("=" * 60)

    failed = []

    try:
        test_protocol_file()
    except AssertionError as e:
        print(f"  ✗ {e}")
        failed.append("test_protocol_file")

    memory_data = ""
    try:
        memory_data = test_context_manager()
    except AssertionError as e:
        print(f"  ✗ {e}")
        failed.append("test_context_manager")

    try:
        test_orchestrator_guard()
    except AssertionError as e:
        print(f"  ✗ {e}")
        failed.append("test_orchestrator_guard")

    if memory_data:
        try:
            await test_output_layer_context(memory_data)
        except AssertionError as e:
            print(f"  ✗ {e}")
            failed.append("test_output_layer_context")

    print("\n" + "=" * 60)
    if failed:
        print(f"ERGEBNIS: {len(failed)} Test(s) FEHLGESCHLAGEN: {failed}")
    else:
        print("ERGEBNIS: Alle Tests bestanden ✓")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
