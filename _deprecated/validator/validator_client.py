import os
import httpx
from config import VALIDATOR_URL, VALIDATION_THRESHOLD

# Hinweis:
# VALIDATOR_URL z.B.: "http://validator-service:8000"


async def validate_embedding(question: str, answer: str) -> dict:
    """
    Alter Embedding-Validator (falls du ihn noch irgendwo nutzen willst).
    """
    payload = {
        "question": question,
        "answer": answer,
        "threshold": VALIDATION_THRESHOLD,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{VALIDATOR_URL}/validate", json=payload)

    resp.raise_for_status()
    return resp.json()


async def validate_instruction(question: str, answer: str,
                               instruction: str = "",
                               rules: str = "") -> dict:
    """
    Neuer LLM-basierter Instruction-Following-Validator.

    Antwort-Form:
    {
      "final_result": "pass" | "fail",
      "relevance": "...",
      "instruction_following": "...",
      "truthfulness": "...",
      "hallucination": "...",
      "raw_model_output": "..."
    }

    Wir mappen das auf ein generisches Schema, das der Retry-Loop versteht.
    """
    payload = {
        "question": question,
        "answer": answer,
        "instruction": instruction or "",
        "rules": rules or "",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{VALIDATOR_URL}/validate_llm", json=payload)

    resp.raise_for_status()
    data = resp.json()

    passed = data.get("final_result", "fail") == "pass"

    return {
        "passed": passed,
        "similarity": None,   # hier nicht relevant, aber fürs Logging gelassen
        "threshold": None,
        "reason": f"llm-validator: {data.get('final_result')}",
        "details": data,
    }