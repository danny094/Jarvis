# utils/ollama.py

import requests
import json
from config import OLLAMA_BASE


async def query_model(model: str, messages: list, stream: bool = False):
    """
    Wrapper für den Meta-Decision-Layer.
    Nutzt Ollama /api/generate korrekt.
    """

    # -------------------------------
    # Prompt aus messages bauen
    # -------------------------------
    prompt = ""
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        prompt += f"{role}: {content}\n"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
    }

    url = f"{OLLAMA_BASE}/api/generate"

    try:
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
    except Exception as e:
        return json.dumps({"error": f"Ollama error: {e}"})


    # -------------------------------
    # Generate-Response korrekt parsen
    # -------------------------------
    try:
        data = r.json()

        # DeepSeek / Qwen
        if "response" in data:
            return data["response"]

        # Mistral / Dolphin Varianten
        if "output" in data:
            return data["output"]

        # Falls irgendwas anderes
        return json.dumps(data)

    except Exception:
        # Wenn Model Text liefert statt JSON
        return r.text