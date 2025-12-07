# ollama/chat.py

import json
import requests
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from config import (
    OLLAMA_BASE,
    ENABLE_VALIDATION,
    VALIDATION_HARD_FAIL,
)
from utils.prompt import build_prompt
from utils.logger import log_debug, log_error, log_info, log_warn
from classifier.classifier import classify_message
from mcp.client import (
    autosave_assistant,
    get_fact_for_query,
    search_memory_fallback,
)
from modules.meta_decision.decision_client import ask_meta_decision
from modules.validator.validator_client import validate_instruction

router = APIRouter()


def sanitize_payload(payload: dict) -> dict:
    allowed = {
        "model",
        "prompt",
        "stream",
        "temperature",
        "top_p",
        "max_tokens",
    }
    return {k: v for k, v in payload.items() if v is not None and k in allowed}


async def generate_with_retry(question: str, base_payload: dict) -> str:
    """
    HARD MODE:
    - Ruft Ollama /api/generate (non-streaming) auf
    - Prüft die Antwort mit dem Embedding-Validator
    - Bei Hard-Fail: baue härteren Prompt und versuche es erneut
    - Max. 3 Versuche, danach Fallback-Text
    """

    MAX_RETRIES = 3
    attempt = 0
    last_answer = ""

    # wir arbeiten immer mit einer Kopie des Payloads
    current_payload = dict(base_payload)

    while attempt < MAX_RETRIES:
        attempt += 1
        log_info(f"[Ollama] Generating answer attempt {attempt}/{MAX_RETRIES}")

        # non-streaming für interne Verarbeitung
        current_payload["stream"] = False

        try:
            resp = requests.post(
                f"{OLLAMA_BASE}/api/generate",
                json=current_payload,
                stream=False,
                timeout=300,
            )
            resp.raise_for_status()
        except Exception as e:
            log_error(f"[Ollama] Error on attempt {attempt}: {e}")
            if attempt >= MAX_RETRIES:
                return "Interner Fehler beim LLM-Aufruf."
            continue

        try:
            data = resp.json()
        except Exception as e:
            log_error(f"[Ollama] JSON decode error on attempt {attempt}: {e}")
            if attempt >= MAX_RETRIES:
                return "Interner Fehler beim LLM-Antwortformat."
            continue

        # DeepSeek / Ollama Standardfeld
        answer = data.get("response", "") or ""
        last_answer = answer.strip()

        if not last_answer:
            log_warn("[Ollama] Empty answer received.")
            if attempt >= MAX_RETRIES:
                return "Ich konnte leider keine sinnvolle Antwort generieren."
            # nochmal versuchen
            continue

        # Wenn Validator deaktiviert → direkt zurück
        if not ENABLE_VALIDATION:
            return last_answer

        # === LLM-VALIDATOR-CHECK =======================================
        try:
            # Du kannst hier je nach Bedarf Regeln setzen:
            instruction = "Beantworte die Frage korrekt, bleib beim Thema."
            rules = (
                "Keine Halluzinationen. "
                "Nicht über Meta-Themen reden. "
                "Halte dich eng an die Frage und die gewünschte Sprache."
            )

            result = await validate_instruction(
                question=question,
                answer=last_answer,
                instruction=instruction,
                rules=rules,
            )
            log_info(f"[Validator-LLM] result={result}")
        except Exception as e:
            log_error(f"[Validator-LLM] error: {e}")
            # fail-open: wenn Validator kaputt ist, Antwort nicht blockieren
            return last_answer

        passed = bool(result.get("passed", False))

        if passed:
            log_info("[Validator-LLM] PASS – Antwort akzeptiert.")
            return last_answer

        if not VALIDATION_HARD_FAIL:
            log_warn("[Validator-LLM] SOFT FAIL – Antwort trotzdem erlaubt.")
            return last_answer

        # === HARD FAIL → neuen Prompt bauen und nochmal versuchen ========
        log_warn(f"[Validator-LLM] HARD FAIL – retry {attempt}/{MAX_RETRIES}")

        improved_prompt = f"""
Die vorige Antwort des Modells war nicht ausreichend nach den Bewertungsregeln.

### VALIDATOR-BEWERTUNG:
{result}

### AUFGABE
Beantworte die folgende Frage klar, fokussiert und regelkonform.

### FRAGE
{question}

### PROBLEM DER LETZTEN ANTWORT
{last_answer}

### ANFORDERUNGEN
- Keine Halluzinationen
- Nicht abschweifen
- Kurz, direkt, präzise
- In der Sprache der Frage antworten

NEUE, VERBESSERTE ANTWORT:
""".strip()

        current_payload = dict(base_payload)
        current_payload["prompt"] = improved_prompt
        # Loop macht weiter mit neuem Prompt

    # alle Versuche durch
    if VALIDATION_HARD_FAIL:
        return (
            "Ich konnte deine Frage nach mehreren Versuchen nicht stabil "
            "beantworten, ohne Qualitätsprobleme zu erzeugen."
        )

    return last_answer or "Ich konnte leider keine Antwort generieren."


@router.post("/chat")
async def chat(request: Request):
    """
    LobeChat-/Ollama-kompatibler /api/chat-Endpoint.

    Erwartete Form (NDJSON pro Zeile):
    {
      "model": "...",
      "created_at": "...",
      "message": { "role": "assistant", "content": "..." },
      "done": false|true,
      "done_reason": "stop"
    }
    """

    data = await request.json()
    model = data.get("model")
    messages = data.get("messages", [])
    conversation_id = data.get("conversation_id", "global")

    log_debug(f"[/api/chat] MODEL={model} conv={conversation_id}")

    # ----------------------------------------------------
    # 1) letzte User-Message
    # ----------------------------------------------------
    user_text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_text = m.get("content", "")
            break

    # ----------------------------------------------------
    # 2) META DECISION LAYER
    # ----------------------------------------------------
    try:
        decision = await ask_meta_decision(user_text)
    except Exception as e:
        log_error(f"[MetaDecision] Fehler: {e}")
        decision = {
            "use_memory": False,
            "rewrite": "",
        }

    log_info(f"[MetaDecision] → {decision}")

    # optionales Rewrite
    if decision.get("rewrite"):
        user_text = decision["rewrite"]
        if messages:
            messages[-1]["content"] = user_text

    # ----------------------------------------------------
    # 3) CLASSIFIER
    # ----------------------------------------------------
    classifier = {
        "save": False,
        "layer": "stm",
        "type": "irrelevant",
        "key": None,
    }
    try:
        classifier = classify_message(user_text, conversation_id)
    except Exception as e:
        log_error(f"[Classifier] Fehler: {e}")

    save_flag = classifier.get("save")
    target_layer = classifier.get("layer")
    classifier_key = classifier.get("key")

    log_info(f"[Classifier] → {classifier}")

    # ----------------------------------------------------
    # 4) MEMORY RETRIEVAL (STM / LTM über MCP)
    # ----------------------------------------------------
    retrieved_memory = ""

    if decision.get("use_memory"):
        if classifier_key:
            retrieved_memory = get_fact_for_query(conversation_id, classifier_key)
            if not retrieved_memory:
                retrieved_memory = search_memory_fallback(
                    conversation_id, classifier_key
                )

    # ----------------------------------------------------
    # 5) PROMPT AUFBAU
    # ----------------------------------------------------
    base_prompt = build_prompt(messages)

    if retrieved_memory:
        full_prompt = f"### MEMORY:\n{retrieved_memory}\n\n### USER:\n{base_prompt}"
    else:
        full_prompt = base_prompt

    # ----------------------------------------------------
    # 6) OLLAMA-PAYLOAD (intern non-streaming)
    # ----------------------------------------------------
    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,  # intern non-streaming
        "temperature": data.get("temperature"),
        "top_p": data.get("top_p"),
        "max_tokens": data.get("max_tokens"),
    }

    payload = sanitize_payload(payload)

    # ----------------------------------------------------
    # 7) Antwort via Retry + Validator holen
    # ----------------------------------------------------
    full_answer = await generate_with_retry(user_text, payload)
    full_answer = (full_answer or "").strip()

    # ----------------------------------------------------
    # 8) Memory speichern
    # ----------------------------------------------------
    if save_flag and full_answer:
        try:
            autosave_assistant(
                conversation_id,
                full_answer,
                layer=target_layer,
                classifier_result=classifier,
            )
        except Exception as e:
            log_error(f"[Memory] autosave_assistant error: {e}")

    # ----------------------------------------------------
    # 9) NDJSON-Streaming im LobeChat-/Ollama-Format
    #    → Option A: ein Chunk mit kompletter Antwort
    # ----------------------------------------------------
    created_at = datetime.utcnow().isoformat() + "Z"

    def iter_chat():
        # ein einziger "delta"-Chunk mit kompletter Antwort
        out = {
            "model": model,
            "created_at": created_at,
            "message": {"role": "assistant", "content": full_answer},
            "done": True,
            "done_reason": "stop",
        }
        yield (json.dumps(out) + "\n").encode("utf-8")

    return StreamingResponse(iter_chat(), media_type="application/x-ndjson")