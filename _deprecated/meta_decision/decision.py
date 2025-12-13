import json
from pathlib import Path
from utils.ollama import query_model
from config import THINKING_MODEL

PROMPT_PATH = Path(__file__).parent / "decision_prompt.txt"
DECISION_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")


async def run_decision_layer(payload: dict):

    user_text = payload.get("user", "")
    memory_text = payload.get("memory", "")

    # ⚠️ KEIN format() mehr – nur replace()
    prompt = DECISION_PROMPT \
        .replace("<<<MEMORY>>>", memory_text) \
        .replace("<<<USER>>>", user_text)

    model = THINKING_MODEL

    raw = await query_model(
        model=model,
        messages=[{"role": "system", "content": prompt}],
        stream=False,
    )

    # JSON extrahieren
    try:
        json_str = raw[raw.index("{"): raw.rindex("}") + 1]
        response = json.loads(json_str)
    except Exception as e:
        raise ValueError(
            f"[MetaDecision] Kein gültiges JSON.\nRAW:\n{raw}"
        ) from e

    return response