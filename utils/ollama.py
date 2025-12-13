# utils/ollama.py

import httpx
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
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=payload)
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