import json
from typing import Any, Dict, Optional
import requests

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import MCP_BASE
from utils.logger import (
    log_debug,
    log_error,
    log_info,
    log_warning
)

router = APIRouter()

# ------------------------------------------------------
# Low-level MCP request
# ------------------------------------------------------
def _call_mcp_raw(payload: Dict[str, Any], timeout: int = 5) -> Optional[Dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    log_debug(f"[MCP] → {MCP_BASE} payload={payload}")

    try:
        r = requests.post(
            MCP_BASE,
            json=payload,
            headers=headers,
            timeout=timeout,
            stream=True,
        )
    except Exception as e:
        log_error(f"[MCP] Request-Fehler: {e}")
        return None

    ct = r.headers.get("content-type", "")

    # SSE Mode
    if "text/event-stream" in ct:
        last = None
        for line in r.iter_lines():
            if not line:
                continue
            try:
                decoded = line.decode("utf-8")
                if decoded.startswith("data: "):
                    last = json.loads(decoded[6:])
            except Exception:
                continue
        log_debug(f"[MCP] ← SSE last={last}")
        return last

    # Normal JSON
    try:
        obj = r.json()
        log_debug(f"[MCP] ← JSON {obj}")
        return obj
    except Exception as e:
        log_error(f"[MCP] JSON-Parse Fehler: {e}")
        return None


# ------------------------------------------------------
# Wrapper für alle Tools
# ------------------------------------------------------
def call_tool(name: str, arguments: Dict[str, Any], timeout: int = 5) -> Optional[Dict[str, Any]]:
    payload = {
        "jsonrpc": "2.0",
        "id": f"call-{name}",
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
        },
    }
    return _call_mcp_raw(payload, timeout=timeout)


# ------------------------------------------------------
# Autosave (Freitext + Fakten)
# ------------------------------------------------------
def autosave_assistant(
    conversation_id: str,
    content: str,
    layer: str = "auto",
    classifier_result: dict = None
) -> None:

    if not content:
        return

    # 1) Freitext-Speicherung
    args = {
        "conversation_id": conversation_id or "global",
        "role": "assistant",
        "content": content,
        "tags": "",
        "layer": layer
    }

    log_info(f"[Autosave] → conversation={conversation_id} layer={layer} len={len(content)}")

    resp = call_tool("memory_save", args)
    if resp:
        log_info(f"[Autosave] OK: {resp.get('result')}")
    else:
        log_warning("[Autosave] MCP-Server antwortet nicht.")

    # 2) Strukturierte Fakten
    if classifier_result:
        save = classifier_result.get("save")
        ctype = classifier_result.get("type")
        key = classifier_result.get("key")
        value = classifier_result.get("value")
        subject = classifier_result.get("subject", "Danny")

        if save and ctype == "fact" and key and value:
            fact_args = {
                "conversation_id": conversation_id or "global",
                "subject": subject,
                "key": key,
                "value": value,
                "layer": "ltm",
            }

            log_info(f"[Autosave-Fact] Speichere Fact: {key} = {value}")
            fact_resp = call_tool("memory_fact_save", fact_args)

            if fact_resp:
                log_info(f"[Autosave-Fact] OK: {fact_resp.get('result')}")
            else:
                log_warning("[Autosave-Fact] Speicherfehler.")


# ------------------------------------------------------
# Structured Fact Retrieval (NEU)
# ------------------------------------------------------
def get_fact_for_query(conversation_id: str, key: str) -> Optional[str]:
    args = {
        "conversation_id": conversation_id or "global",
        "key": key
    }

    log_info(f"[Fact] → Suche Fakt key='{key}' conv='{conversation_id}'")

    resp = call_tool("memory_fact_load", args)
    log_debug(f"[Fact] Raw response: {resp}")

    if not resp:
        return None

    # MCP gibt: {"result": {"content": [...], "structuredContent": {...}}}
    result = resp.get("result")
    if not result:
        log_info(f"[Fact] Kein result in response")
        return None
    
    # structuredContent.structuredContent.value
    structured = result.get("structuredContent", {})
    if structured:
        # Kann direkt "result" haben oder nochmal "structuredContent"
        value = structured.get("result")
        if value:
            log_info(f"[Fact] Found: {value}")
            return value
        
        inner = structured.get("structuredContent", {})
        if inner:
            value = inner.get("value")
            if value:
                log_info(f"[Fact] Found via inner: {value}")
                return value
    
    # Fallback: content array parsen
    content = result.get("content", [])
    for item in content:
        if item.get("type") == "text":
            text = item.get("text", "")
            try:
                parsed = json.loads(text)
                value = parsed.get("result") or parsed.get("structuredContent", {}).get("value")
                if value:
                    log_info(f"[Fact] Found via content: {value}")
                    return value
            except:
                pass

    log_info(f"[Fact] Nichts gefunden für key='{key}'")
    return None


# ------------------------------------------------------
# Text-Fallback Memory (für ältere Einträge)
# ------------------------------------------------------
def search_memory_fallback(conversation_id: str, key: str) -> str:
    """
    Falls kein strukturierter Fakt gefunden wurde:
    → klassische Textsuche in memory_search_layered
    """
    args = {
        "conversation_id": conversation_id or "global",
        "query": key
    }

    log_info(f"[Fallback] Suche Text-Memory für '{key}'")

    resp = call_tool("memory_search_layered", args, timeout=5)
    if not resp:
        return ""

    try:
        entries = resp.get("result", [])
        if not entries:
            return ""

        # Gib nur den Content der besten Übereinstimmung zurück
        top = entries[0]
        return top.get("content", "")

    except Exception as e:
        log_error(f"[Fallback] Fehler: {e}")
        return ""

def semantic_search(conversation_id: str, query: str, limit: int = 5) -> list:
    """
    Semantische Suche im Memory.
    Findet Einträge nach BEDEUTUNG, nicht nur Keywords.
    """
    args = {
        "query": query,
        "conversation_id": conversation_id or "global",
        "limit": limit,
        "min_similarity": 0.5
    }
    
    log_info(f"[Semantic] Suche: '{query}' in conv='{conversation_id}'")
    
    resp = call_tool("memory_semantic_search", args)

    if not resp:
        return []
    
    result = resp.get("result", {})
    if isinstance(result, dict):
        if "structuredContent" in result:
            inner = result.get("structuredContent", {})
            return inner.get("results", [])
        return result.get("results", [])
    
    return []



# ------------------------------------------------------
# MCP Proxy (unverändert)
# ------------------------------------------------------
@router.post("/mcp")
async def mcp_proxy(request: Request):
    body = await request.body()

    headers = {
        "Content-Type": request.headers.get("content-type", "application/json"),
        "Accept": request.headers.get("accept", "application/json, text/event-stream"),
    }

    log_debug(f"[MCP-Proxy] → {MCP_BASE} headers={headers}")

    try:
        upstream = requests.post(
            MCP_BASE,
            data=body,
            headers=headers,
            timeout=10,
            stream=True,
        )
    except Exception as e:
        log_error(f"[MCP-Proxy] Upstream Fehler: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

    def iter_stream():
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                if chunk:
                    yield chunk
        except Exception as e:
            log_error(f"[MCP-Proxy] Stream Fehler: {e}")
            yield json.dumps({"error": str(e)}).encode("utf-8")

    return StreamingResponse(
        iter_stream(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )