"""
Daily Protocol REST API
Manages daily conversation logs as Markdown files.
Supports append, edit, delete, merge-to-graph.
"""

import os
import re
import json
import threading
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

PROTOCOL_DIR = Path(os.environ.get("PROTOCOL_DIR", "/app/memory"))
STATUS_FILE = PROTOCOL_DIR / ".protocol_status.json"

# File-level locks keyed by filepath
_locks = {}
_locks_lock = threading.Lock()


def _get_lock(filepath: Path) -> threading.Lock:
    with _locks_lock:
        key = str(filepath)
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


def _load_status() -> dict:
    """Load merge status tracking."""
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_status(status: dict):
    STATUS_FILE.write_text(json.dumps(status, indent=2))


def _parse_entries(content: str) -> list:
    """Parse markdown into individual ## HH:MM entries."""
    # Split on ## patterns (time headers)
    parts = re.split(r'^(## \d{2}:\d{2})', content, flags=re.MULTILINE)
    entries = []

    # parts[0] is the header before first ##
    i = 1
    while i < len(parts) - 1:
        header = parts[i]       # "## 15:42"
        body = parts[i + 1]     # everything until next ## or end
        entries.append((header + body).strip())
        i += 2

    return entries


def _reconstruct_md(date: str, entries: list) -> str:
    """Rebuild full markdown from header + entries."""
    header = f"# Tagesprotokoll {date}\n"
    body = "\n\n".join(entries)
    return header + "\n" + body + "\n"


# ──────────────────────────────────────────────
# GET /list - All dates with merge status
# ──────────────────────────────────────────────
@router.get("/list")
async def protocol_list():
    PROTOCOL_DIR.mkdir(parents=True, exist_ok=True)
    status = _load_status()
    dates = []

    for f in sorted(PROTOCOL_DIR.glob("*.md"), reverse=True):
        date_str = f.stem  # YYYY-MM-DD
        merged = status.get(date_str, False)
        content = f.read_text()
        entry_count = len(_parse_entries(content))
        dates.append({
            "date": date_str,
            "merged": merged,
            "entry_count": entry_count
        })

    unmerged = sum(1 for d in dates if not d["merged"] and d["entry_count"] > 0)
    return JSONResponse({"dates": dates, "unmerged_count": unmerged})


# ──────────────────────────────────────────────
# GET /today - Today's protocol
# ──────────────────────────────────────────────
@router.get("/today")
async def protocol_today():
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = PROTOCOL_DIR / f"{today}.md"

    if not filepath.exists():
        return JSONResponse({"date": today, "content": "", "entries": [], "entry_count": 0})

    content = filepath.read_text()
    entries = _parse_entries(content)
    return JSONResponse({
        "date": today,
        "content": content,
        "entries": entries,
        "entry_count": len(entries)
    })


# ──────────────────────────────────────────────
# GET /unmerged-count - For badge polling
# (Must be before /{date} to avoid path conflict)
# ──────────────────────────────────────────────
@router.get("/unmerged-count")
async def protocol_unmerged_count():
    PROTOCOL_DIR.mkdir(parents=True, exist_ok=True)
    status = _load_status()
    count = 0

    for f in PROTOCOL_DIR.glob("*.md"):
        date_str = f.stem
        if not status.get(date_str, False):
            content = f.read_text()
            if _parse_entries(content):
                count += 1

    return JSONResponse({"unmerged_count": count})


# ──────────────────────────────────────────────
# GET /{date} - Specific date
# ──────────────────────────────────────────────
@router.get("/{date}")
async def protocol_get(date: str):
    filepath = PROTOCOL_DIR / f"{date}.md"

    if not filepath.exists():
        return JSONResponse({"date": date, "content": "", "entries": [], "entry_count": 0})

    content = filepath.read_text()
    entries = _parse_entries(content)
    status = _load_status()
    return JSONResponse({
        "date": date,
        "content": content,
        "entries": entries,
        "entry_count": len(entries),
        "merged": status.get(date, False)
    })


# ──────────────────────────────────────────────
# POST /append - Append new entry to today
# ──────────────────────────────────────────────
@router.post("/append")
async def protocol_append(request: Request):
    data = await request.json()
    user_msg = data.get("user_message", "").strip()
    ai_response = data.get("ai_response", "").strip()
    timestamp = data.get("timestamp", datetime.now().isoformat())
    # P6-C: Accept tracking IDs — forwarded by chat.js, not silently dropped
    conversation_id = data.get("conversation_id", "")
    session_id = data.get("session_id", "")

    if not user_msg or not ai_response:
        return JSONResponse({"error": "user_message and ai_response required"}, status_code=400)

    date = timestamp[:10]  # YYYY-MM-DD
    time_str = timestamp[11:16]  # HH:MM
    filepath = PROTOCOL_DIR / f"{date}.md"
    PROTOCOL_DIR.mkdir(parents=True, exist_ok=True)

    entry = f"\n## {time_str}\n**User:** {user_msg}\n\n**Jarvis:** {ai_response}\n\n---\n"

    lock = _get_lock(filepath)
    with lock:
        if not filepath.exists():
            entry = f"# Tagesprotokoll {date}\n{entry}"
        with open(filepath, "a") as f:
            f.write(entry)

    # Mark date as unmerged
    status = _load_status()
    status[date] = False
    _save_status(status)

    return JSONResponse({
        "appended": True,
        "date": date,
        "time": time_str,
        "conversation_id": conversation_id or None,
        "session_id": session_id or None,
    })


# ──────────────────────────────────────────────
# PUT /{date} - Update full content (user edits)
# ──────────────────────────────────────────────
@router.put("/{date}")
async def protocol_update(date: str, request: Request):
    data = await request.json()
    content = data.get("content", "")
    filepath = PROTOCOL_DIR / f"{date}.md"

    if not content.strip():
        return JSONResponse({"error": "content is required"}, status_code=400)

    lock = _get_lock(filepath)
    with lock:
        filepath.write_text(content)

    # Mark as unmerged since content changed
    status = _load_status()
    status[date] = False
    _save_status(status)

    return JSONResponse({"updated": True, "date": date})


# ──────────────────────────────────────────────
# DELETE /{date}/entry/{index} - Delete single entry
# ──────────────────────────────────────────────
@router.delete("/{date}/entry/{index}")
async def protocol_delete_entry(date: str, index: int):
    filepath = PROTOCOL_DIR / f"{date}.md"

    if not filepath.exists():
        return JSONResponse({"error": "Protocol not found"}, status_code=404)

    lock = _get_lock(filepath)
    with lock:
        content = filepath.read_text()
        entries = _parse_entries(content)

        if index < 0 or index >= len(entries):
            return JSONResponse({"error": f"Index {index} out of range (0-{len(entries)-1})"}, status_code=400)

        removed = entries.pop(index)

        if entries:
            filepath.write_text(_reconstruct_md(date, entries))
        else:
            filepath.unlink()

    return JSONResponse({"deleted": True, "date": date, "index": index, "remaining": len(entries)})


# ──────────────────────────────────────────────
# POST /{date}/merge - Merge to Knowledge Graph
# ──────────────────────────────────────────────
@router.post("/{date}/merge")
async def protocol_merge(date: str):
    filepath = PROTOCOL_DIR / f"{date}.md"

    if not filepath.exists():
        return JSONResponse({"error": "Protocol not found"}, status_code=404)

    content = filepath.read_text()
    entries = _parse_entries(content)

    if not entries:
        return JSONResponse({"error": "No entries to merge"}, status_code=400)

    # Import MCP hub for graph_add_node
    from mcp.hub import get_hub

    merged_count = 0
    errors = []

    try:
        hub = get_hub()
        hub.initialize()

        for entry_text in entries:
            try:
                result = hub.call_tool("graph_add_node", {
                    "source_type": "daily-protocol",
                    "content": entry_text,
                    "conversation_id": "daily-protocol",
                    "confidence": 0.85
                })
                merged_count += 1
            except Exception as e:
                errors.append(str(e))
    except Exception as e:
        return JSONResponse({"error": f"MCP Hub error: {e}"}, status_code=500)

    # Mark as merged
    status = _load_status()
    status[date] = True
    _save_status(status)

    return JSONResponse({
        "merged": True,
        "date": date,
        "entries_merged": merged_count,
        "errors": errors
    })


@router.post("/summarize-yesterday")
async def summarize_yesterday_endpoint(request: Request):
    """Manuell: Zusammenfassung des gestrigen Protokolls in rolling_summary.md."""
    try:
        from core.context_compressor import summarize_yesterday
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        force = body.get("force", False)
        did_run = await summarize_yesterday(force=force)
        return JSONResponse({"success": True, "ran": did_run})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/rolling-summary")
async def get_rolling_summary():
    """Gibt den aktuellen Inhalt der rolling_summary.md zurück."""
    summary_file = PROTOCOL_DIR / "rolling_summary.md"
    if not summary_file.exists():
        return JSONResponse({"content": "", "exists": False})
    content = summary_file.read_text(encoding="utf-8")
    return JSONResponse({"content": content, "exists": True, "size": len(content)})
