"""
ContextCompressor — Rolling Summary (2-Phase)

Phase 1 (>100K Token):
  Protokoll-Einträge älter als die letzten 20 Nachrichten werden mit
  ministral-3:3b komprimiert → rolling_summary.md (überschreibt sich selbst)
  Das Protokoll wird auf die letzten 20 Nachrichten reduziert.

Phase 2 (>150K Token):
  rolling_summary.md wird nochmals komprimiert.
  Extrahierte Fakten gehen per graph_add_node ins Langzeitgedächtnis.
  rolling_summary.md wird danach geleert.

Token-Schätzung: len(text) / 4 (1 Token ≈ 4 Zeichen) — schnell, kein LLM nötig.
"""

import os
import re
import json
import asyncio
import httpx
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple
from utils.logger import log_info, log_warn, log_error, log_debug


# ─── Config ───────────────────────────────────────────────────────────────────

PROTOCOL_DIR     = Path(os.getenv("PROTOCOL_DIR", "/app/memory"))
OLLAMA_BASE      = os.getenv("OLLAMA_BASE", "http://host.docker.internal:11434")
COMPRESS_MODEL   = os.getenv("COMPRESS_MODEL", "ministral-3:3b")
MEMORY_URL       = os.getenv("MCP_BASE", "http://mcp-sql-memory:8081")

PHASE1_THRESHOLD   = int(os.getenv("COMPRESSION_THRESHOLD",       "20000"))
PHASE2_THRESHOLD   = int(os.getenv("COMPRESSION_PHASE2_THRESHOLD","40000"))
KEEP_MESSAGES      = int(os.getenv("COMPRESSION_KEEP_MESSAGES",   "20"))
DAILY_SUMMARY_HOUR = int(os.getenv("DAILY_SUMMARY_HOUR",          "4"))

ROLLING_SUMMARY_FILE = PROTOCOL_DIR / "rolling_summary.md"


# ─── Token Estimate ───────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Schnelle Token-Schätzung: 1 Token ≈ 4 Zeichen."""
    return len(text) // 4


def estimate_protocol_tokens() -> int:
    """Schätzt Token-Verbrauch der aktuellen Protokoll-Dateien + Rolling Summary."""
    total_chars = 0
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    for date_str in [today, yesterday]:
        f = PROTOCOL_DIR / f"{date_str}.md"
        if f.exists():
            total_chars += f.stat().st_size

    if ROLLING_SUMMARY_FILE.exists():
        total_chars += ROLLING_SUMMARY_FILE.stat().st_size

    return total_chars // 4


# ─── Protocol Parser ──────────────────────────────────────────────────────────

def parse_protocol_messages(content: str) -> List[dict]:
    """
    Parst Protokoll-Markdown in eine Liste von Nachrichten.
    Format: '### HH:MM - User\n...' oder '### HH:MM - TRION\n...'
    Jede Nachricht = {time, role, text}
    """
    messages = []

    # Format A: ## HH:MM + **User:** / **Jarvis:** Blöcke (älteres Format)
    if re.search(r'\n## \d{1,2}:\d{2}', content):
        blocks = re.split(r'\n(?=## \d{1,2}:\d{2})', content)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            m_time = re.match(r'## (\d{1,2}:\d{2})', block)
            if not m_time:
                continue
            time_str = m_time.group(1)
            # User und Jarvis aus dem Block extrahieren
            user_m = re.search(r'\*\*User:\*\*\s*(.*?)(?=\n\*\*|$)', block, re.DOTALL)
            jarvis_m = re.search(r'\*\*Jarvis:\*\*\s*(.*?)(?=\n---|$)', block, re.DOTALL)
            if user_m:
                messages.append({"time": time_str, "role": "User", "text": user_m.group(1).strip()[:600]})
            if jarvis_m:
                messages.append({"time": time_str, "role": "TRION", "text": jarvis_m.group(1).strip()[:600]})
        return messages

    # Format B: ### HH:MM - Role (neueres Format)
    blocks = re.split(r'\n(?=### )', content)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split('\n', 1)
        header = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        m = re.match(r'###\s+(\d{1,2}:\d{2})\s*[-–]\s*(.+)', header)
        if m:
            messages.append({"time": m.group(1), "role": m.group(2).strip(), "text": body})
    return messages


def rebuild_protocol(messages: List[dict]) -> str:
    """Baut Protokoll aus Message-Liste wieder auf."""
    lines = []
    today = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"## {today}\n")
    for msg in messages:
        lines.append(f"### {msg['time']} - {msg['role']}")
        if msg['text']:
            lines.append(msg['text'])
        lines.append("")
    return "\n".join(lines)


# ─── LLM Calls ────────────────────────────────────────────────────────────────

async def _llm_call(prompt: str, max_tokens: int = 1200) -> str:
    """Einfacher synchroner LLM-Call via Ollama."""
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                f"{OLLAMA_BASE}/api/generate",
                json={
                    "model": COMPRESS_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": "2m",
                    "options": {"temperature": 0.1, "num_predict": max_tokens},
                },
            )
            r.raise_for_status()
            return r.json().get("response", "").strip()
    except Exception as e:
        log_error(f"[ContextCompressor] LLM call failed: {e}")
        return ""


async def _summarize(old_messages: List[dict]) -> str:
    """Komprimiert alte Nachrichten zu einer kompakten Zusammenfassung."""
    if not old_messages:
        return ""

    conversation_text = "\n".join([
        f"[{m['time']} {m['role']}]: {m['text'][:500]}"
        for m in old_messages
    ])

    prompt = f"""Fasse diese Konversation kompakt zusammen (max. 300 Wörter).
Behalte: wichtige Fakten, getroffene Entscheidungen, erledigte Tasks, erwähnte Namen/Orte.
Verwerfe: Smalltalk, Wiederholungen, irrelevante Details.
Antworte NUR mit der Zusammenfassung, keine Einleitung.

KONVERSATION:
{conversation_text}

ZUSAMMENFASSUNG:"""

    return await _llm_call(prompt, max_tokens=400)


async def _extract_facts(summary_text: str) -> List[str]:
    """Extrahiert atomare Fakten aus einer Zusammenfassung als JSON-Liste."""
    if not summary_text.strip():
        return []

    prompt = f"""Extrahiere 5-10 atomare Fakten aus dieser Zusammenfassung.
Jeder Fakt = ein kurzer Satz (max. 20 Wörter).
Antworte NUR mit einem JSON-Array von Strings, kein anderer Text.

ZUSAMMENFASSUNG:
{summary_text}

FAKTEN (JSON-Array):"""

    raw = await _llm_call(prompt, max_tokens=300)

    # JSON aus Antwort extrahieren
    try:
        start = raw.index("[")
        end = raw.rindex("]") + 1
        facts = json.loads(raw[start:end])
        return [str(f).strip() for f in facts if str(f).strip()]
    except Exception:
        # Fallback: zeilenweise parsen
        lines = [l.strip().lstrip("-•*").strip() for l in raw.split("\n") if l.strip()]
        return [l for l in lines if 10 < len(l) < 200][:10]


async def _push_facts_to_graph(facts: List[str]):
    """Schreibt extrahierte Fakten per graph_add_node ins Langzeitgedächtnis."""
    if not facts:
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    pushed = 0

    for fact in facts:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"{MEMORY_URL}/mcp",
                    json={
                        "method": "tools/call",
                        "params": {
                            "name": "graph_add_node",
                            "arguments": {
                                "conversation_id": "_summaries",
                                "content": fact,
                                "source_type": "summary",
                                "importance": 0.7,
                                "metadata": json.dumps({
                                    "compressed_from": date_str,
                                    "type": "extracted_fact"
                                }),
                            }
                        }
                    },
                    headers={"Accept": "application/json, text/event-stream"},
                )
                if r.status_code == 200:
                    pushed += 1
        except Exception as e:
            log_warn(f"[ContextCompressor] graph_add_node failed: {e}")

    log_info(f"[ContextCompressor] Pushed {pushed}/{len(facts)} facts to graph")


# ─── Main Compressor ──────────────────────────────────────────────────────────

class ContextCompressor:

    async def check_and_compress(self) -> Tuple[bool, str]:
        """
        Prüft ob Kompression nötig ist und führt sie ggf. durch.
        Returns: (did_compress, phase)
        """
        token_estimate = estimate_protocol_tokens()
        log_debug(f"[ContextCompressor] Estimated tokens: {token_estimate}")

        if token_estimate >= PHASE2_THRESHOLD:
            log_info(f"[ContextCompressor] Phase 2 triggered ({token_estimate} tokens)")
            await self._run_phase2()
            return True, "phase2"

        if token_estimate >= PHASE1_THRESHOLD:
            log_info(f"[ContextCompressor] Phase 1 triggered ({token_estimate} tokens)")
            await self._run_phase1()
            return True, "phase1"

        return False, "none"

    async def _run_phase1(self):
        """
        Phase 1: Protokoll-Einträge älter als letzte N Nachrichten komprimieren.
        Ergebnis: rolling_summary.md erweitert, Protokoll-Datei gekürzt.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        protocol_file = PROTOCOL_DIR / f"{today}.md"

        if not protocol_file.exists():
            log_warn("[ContextCompressor] Phase 1: No protocol file found")
            return

        content = protocol_file.read_text(encoding="utf-8")
        messages = parse_protocol_messages(content)

        if len(messages) <= KEEP_MESSAGES:
            log_info("[ContextCompressor] Phase 1: Not enough messages to compress")
            return

        old_messages = messages[:-KEEP_MESSAGES]
        keep_messages = messages[-KEEP_MESSAGES:]

        log_info(f"[ContextCompressor] Phase 1: Compressing {len(old_messages)} messages, keeping {len(keep_messages)}")

        # Zusammenfassung erstellen
        summary = await _summarize(old_messages)
        if not summary:
            log_warn("[ContextCompressor] Phase 1: Summary generation failed")
            return

        # Rolling summary erweitern
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        existing = ROLLING_SUMMARY_FILE.read_text(encoding="utf-8") if ROLLING_SUMMARY_FILE.exists() else ""
        new_summary_block = f"\n\n## Zusammenfassung vom {timestamp}\n{summary}"
        ROLLING_SUMMARY_FILE.write_text(
            (existing + new_summary_block).strip(),
            encoding="utf-8"
        )

        # Protokoll-Datei kürzen (nur letzte N Nachrichten)
        protocol_file.write_text(
            rebuild_protocol(keep_messages),
            encoding="utf-8"
        )

        log_info(f"[ContextCompressor] Phase 1 done. Summary saved to {ROLLING_SUMMARY_FILE}")

    async def _run_phase2(self):
        """
        Phase 2: Rolling Summary zu Fakten extrahieren → Graph.
        Rolling Summary danach leeren.
        """
        # Erst Phase 1 ausführen um altes Protokoll zu komprimieren
        await self._run_phase1()

        if not ROLLING_SUMMARY_FILE.exists():
            log_warn("[ContextCompressor] Phase 2: No rolling summary found")
            return

        summary_text = ROLLING_SUMMARY_FILE.read_text(encoding="utf-8")
        if len(summary_text.strip()) < 100:
            log_info("[ContextCompressor] Phase 2: Rolling summary too short, skipping fact extraction")
            return

        log_info(f"[ContextCompressor] Phase 2: Extracting facts from rolling summary ({len(summary_text)} chars)")

        facts = await _extract_facts(summary_text)
        log_info(f"[ContextCompressor] Phase 2: Extracted {len(facts)} facts")

        if facts:
            await _push_facts_to_graph(facts)

        # Rolling Summary leeren (Fakten sind jetzt im Graph)
        ROLLING_SUMMARY_FILE.write_text("", encoding="utf-8")
        log_info("[ContextCompressor] Phase 2 done. Rolling summary cleared.")


# ─── Daily Auto-Summarize ────────────────────────────────────────────────────

async def summarize_yesterday(force: bool = False) -> bool:
    """
    Komprimiert das gestrige Protokoll in rolling_summary.md.
    Läuft täglich um DAILY_SUMMARY_HOUR Uhr (Standard: 04:00).

    Returns: True wenn Zusammenfassung erstellt wurde.
    """
    from datetime import timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    protocol_file = PROTOCOL_DIR / f"{yesterday}.md"

    # Status-Datei: verhindert doppelte Ausführung am selben Tag
    status_file = PROTOCOL_DIR / ".daily_summary_status.json"
    today_str = datetime.now().strftime("%Y-%m-%d")

    if not force:
        if status_file.exists():
            try:
                status = json.loads(status_file.read_text())
                if status.get("last_run") == today_str:
                    log_debug("[ContextCompressor] Daily summary already ran today, skipping")
                    return False
            except Exception:
                pass

    if not protocol_file.exists():
        log_warn(f"[ContextCompressor] Daily summary: no protocol for {yesterday}")
        return False

    content = protocol_file.read_text(encoding="utf-8")
    messages = parse_protocol_messages(content)

    if not messages:
        log_info(f"[ContextCompressor] Daily summary: no messages in {yesterday}")
        return False

    log_info(f"[ContextCompressor] Daily summary: summarizing {len(messages)} messages from {yesterday}")

    summary = await _summarize(messages)
    if not summary:
        log_warn("[ContextCompressor] Daily summary: summarization failed")
        return False

    # In rolling_summary.md schreiben
    existing = ROLLING_SUMMARY_FILE.read_text(encoding="utf-8") if ROLLING_SUMMARY_FILE.exists() else ""
    new_block = f"\n\n## {yesterday}\n{summary}"
    ROLLING_SUMMARY_FILE.write_text((existing + new_block).strip(), encoding="utf-8")

    # Status speichern
    status_file.write_text(json.dumps({"last_run": today_str, "summarized_date": yesterday}))

    log_info(f"[ContextCompressor] Daily summary for {yesterday} done → rolling_summary.md")
    return True


async def run_daily_summary_loop():
    """
    Background-Task: läuft täglich um DAILY_SUMMARY_HOUR Uhr.
    Wird beim API-Start gestartet.
    """
    from datetime import timedelta
    log_info(f"[ContextCompressor] Daily summary loop started (runs at {DAILY_SUMMARY_HOUR:02d}:00)")

    while True:
        now = datetime.now()
        next_run = now.replace(hour=DAILY_SUMMARY_HOUR, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)

        wait_seconds = (next_run - now).total_seconds()
        log_debug(f"[ContextCompressor] Next daily summary in {wait_seconds/3600:.1f}h")

        await asyncio.sleep(wait_seconds)

        try:
            await summarize_yesterday()
        except Exception as e:
            log_error(f"[ContextCompressor] Daily summary loop error: {e}")


# ─── Singleton ────────────────────────────────────────────────────────────────

_compressor: Optional[ContextCompressor] = None

def get_compressor() -> ContextCompressor:
    global _compressor
    if _compressor is None:
        _compressor = ContextCompressor()
    return _compressor
