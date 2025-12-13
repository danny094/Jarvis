import json

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from classifier.classifier import classify_message
from config import OLLAMA_BASE
from utils.logger import log_debug, log_error, log_info
from mcp.client import autosave_assistant


def sanitize_ollama_payload(data: dict) -> dict:
    """
    Entfernt Felder, die Ollama nicht akzeptiert.
    LobeChat sendet manchmal Dinge wie 'format', 'raw', 'options', die 400 verursachen.
    """
    allowed = {
        "model",
        "messages",
        "prompt",
        "stream",
        "temperature",
        "top_p",
        "max_tokens",
    }

    safe = {}
    for k, v in data.items():
        if k in allowed:
            safe[k] = v

    return safe


router = APIRouter()


@router.get("/api/tags")
def list_tags():
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        return JSONResponse(resp.json())
    except Exception as e:
        log_error(f"[Ollama/tags] Fehler: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/generate")
async def generate(request: Request):
    data = await request.json()
    stream = bool(data.get("stream"))
    conversation_id = data.get("conversation_id", "global")

    log_debug(f"[/api/generate] stream={stream} conv={conversation_id}")

    # -------------------------------------------------------
    #  NON-STREAMING
    # -------------------------------------------------------
    if not stream:
        try:
            clean_data = sanitize_ollama_payload(data)

            resp = requests.post(
                f"{OLLAMA_BASE}/api/generate",
                json=clean_data,
                timeout=60
            )
            result = resp.json()
        except Exception as e:
            log_error(f"[Ollama/generate] Fehler: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

        result.pop("thinking", None)
        content = result.get("response") or result.get("text") or ""

        # Klassifikation
        decision = classify_message(content, conversation_id)

        if decision["save"]:
            autosave_assistant(
                conversation_id,
                content,
                layer=decision["layer"]
            )

        return JSONResponse(result)

    # -------------------------------------------------------
    #  STREAMING
    # -------------------------------------------------------
    def iter_generate():
        parts = []

        try:
            clean_data = sanitize_ollama_payload(data)

            with requests.post(
                f"{OLLAMA_BASE}/api/generate",
                json=clean_data,
                stream=True,
                timeout=300
            ) as r:
                r.raise_for_status()

                for raw_line in r.iter_lines():
                    if not raw_line:
                        continue

                    try:
                        obj = json.loads(raw_line.decode("utf-8"))
                    except Exception:
                        continue

                    obj.pop("thinking", None)

                    delta = obj.get("response") or obj.get("text") or ""
                    if delta:
                        parts.append(delta)

                    yield (json.dumps(obj) + "\n").encode("utf-8")

                    if obj.get("done"):
                        full_output = "".join(parts)

                        # Nachdem alles da ist → Klassifikation
                        decision = classify_message(full_output, conversation_id)

                        if decision["save"]:
                            autosave_assistant(
                                conversation_id,
                                full_output,
                                layer=decision["layer"]
                            )

                        return

        except Exception as e:
            log_error(f"[Ollama/generate/stream] Fehler: {e}")
            yield json.dumps({"error": str(e)}).encode("utf-8") + b"\n"

    return StreamingResponse(iter_generate(), media_type="application/x-ndjson")