from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import httpx
import math
import os
from typing import List, Optional, Literal

app = FastAPI(title="Embedding + LLM Validator Service")

# ==== Basis-Konfiguration ====

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16")

# LLM-Validator-Modell (per ENV überschreibbar)
VALIDATOR_MODEL = os.getenv("VALIDATOR_MODEL", "qwen2.5:0.5b-instruct")


# ==== Embedding-Modelle (DEIN ALTER TEIL) ===================================

class ValidateRequest(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    threshold: float = Field(0.7, ge=0.0, le=1.0)


class ValidateResponse(BaseModel):
    similarity: float
    passed: bool
    threshold: float
    reason: str
    details: dict


class CompareRequest(BaseModel):
    text1: str = Field(..., min_length=1)
    text2: str = Field(..., min_length=1)


class CompareResponse(BaseModel):
    similarity: float


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Holt Embeddings von Ollama.

    POST /api/embed
    {
      "model": "...",
      "input": ["text1", "text2"]
    }
    Antwort: { "embeddings": [[...], [...]] }
    """
    url = f"{OLLAMA_BASE_URL}/api/embed"
    payload = {"model": EMBEDDING_MODEL, "input": texts}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, json=payload)
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error contacting Ollama at {OLLAMA_BASE_URL}: {str(e)}",
            )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama responded with status {resp.status_code}: {resp.text}",
        )

    data = resp.json()

    if "embeddings" in data:
        embeddings = data["embeddings"]
    elif "embedding" in data:
        embeddings = [data["embedding"]]
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected embedding response from Ollama: {data}",
        )

    if len(embeddings) != len(texts):
        raise HTTPException(
            status_code=500,
            detail=f"Expected {len(texts)} embeddings, got {len(embeddings)}",
        )

    return embeddings


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Embedding dimensions do not match")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "embedding_model": EMBEDDING_MODEL,
        "ollama": OLLAMA_BASE_URL,
        "validator_model": VALIDATOR_MODEL,
    }


@app.post("/compare", response_model=CompareResponse)
async def compare(req: CompareRequest):
    embeddings = await get_embeddings([req.text1, req.text2])
    sim = cosine_similarity(embeddings[0], embeddings[1])
    return CompareResponse(similarity=sim)


@app.post("/validate", response_model=ValidateResponse)
async def validate(req: ValidateRequest):
    embeddings = await get_embeddings([req.question, req.answer])
    sim = cosine_similarity(embeddings[0], embeddings[1])

    passed = sim >= req.threshold
    reason = (
        "similarity >= threshold"
        if passed
        else "similarity below threshold – possible drift/hallucination"
    )

    return ValidateResponse(
        similarity=sim,
        passed=passed,
        threshold=req.threshold,
        reason=reason,
        details={
            "question_len": len(req.question),
            "answer_len": len(req.answer),
            "embedding_model": EMBEDDING_MODEL,
            "ollama_base_url": OLLAMA_BASE_URL,
        },
    )

# ==== NEU: LLM-BASED INSTRUCTION-FOLLOWING VALIDATOR =========================


class LLMValidateRequest(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    instruction: Optional[str] = ""
    rules: Optional[str] = ""


class LLMValidateResponse(BaseModel):
    final_result: Literal["pass", "fail"]
    relevance: str
    instruction_following: str
    truthfulness: str
    hallucination: str
    raw_model_output: str


LLM_VALIDATOR_SYSTEM_PROMPT = """
Du bist ein strenger Evaluations-Agent für KI-Antworten.

Deine Aufgabe:
Bewerte die Antwort eines Modells in Bezug auf:
- inhaltliche Relevanz zur Frage
- Befolgen der Anweisungen
- offensichtliche Halluzinationen
- grundlegende Wahrheitsnähe (ohne externe Faktenabfrage)

Antworte **ausschließlich** im folgenden JSON-Format, ohne weitere Erklärungen,
ohne Text vor oder nach dem JSON, ohne Markdown, ohne ```:

{
  "relevance": "good|ok|bad",
  "instruction_following": "good|ok|bad",
  "truthfulness": "good|uncertain|bad",
  "hallucination": "no|maybe|yes",
  "final_result": "pass|fail"
}

Regeln für final_result:
- "fail", wenn:
  - relevance = "bad" ODER
  - instruction_following = "bad" ODER
  - hallucination = "yes"
- Sonst "pass".
""".strip()


def _extract_json_from_text(text: str) -> dict:
    """
    Nimmt das LLM-Output und versucht, das JSON-Objekt robust herauszufiltern.
    """
    import json

    stripped = text.strip()

    # Falls das Modell versehentlich ```json ... ``` macht
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        # grob: alles nach erster { und vor letzter }
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise ValueError(f"Kein gültiges JSON im Text gefunden: {text[:200]!r}")

    json_str = stripped[start : end + 1]

    return json.loads(json_str)


@app.post("/validate_llm", response_model=LLMValidateResponse)
async def validate_llm(req: LLMValidateRequest):
    """
    LLM-basierter Instruction-Following-Validator.

    Nutzt ein kleines Instruct-Modell (z.B. qwen2.5:0.5b-instruct) über Ollama,
    um die Antwort qualitativ zu bewerten.
    """

    user_instruction = req.instruction or ""
    extra_rules = req.rules or ""

    prompt = f"""
{LLM_VALIDATOR_SYSTEM_PROMPT}

================= FRAGE =================
{req.question}

================= MODELL-ANTWORT =================
{req.answer}

================= ANWEISUNGEN / REGELN =================
{user_instruction}

{extra_rules}
    """.strip()

    payload = {
        "model": VALIDATOR_MODEL,
        "prompt": prompt,
        "stream": False,
        "temperature": 0.1,
        "top_p": 0.9,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate", json=payload
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error contacting Ollama validator model at {OLLAMA_BASE_URL}: {str(e)}",
            )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama validator responded with status {resp.status_code}: {resp.text}",
        )

    data = resp.json()
    raw_output = (data.get("response") or "").strip()

    try:
        parsed = _extract_json_from_text(raw_output)
    except Exception as e:
        # Falls Parsing komplett scheitert → konservativ failen
        raise HTTPException(
            status_code=500,
            detail=f"Validator JSON parse error: {e}. Raw output: {raw_output[:300]}",
        )

    relevance = parsed.get("relevance", "uncertain")
    instruction_following = parsed.get("instruction_following", "uncertain")
    truthfulness = parsed.get("truthfulness", "uncertain")
    hallucination = parsed.get("hallucination", "maybe")
    final_result = parsed.get("final_result", "fail")

    # Sicherstellen, dass final_result konsistent mit den Regeln ist
    if hallucination == "yes" or relevance == "bad" or instruction_following == "bad":
        final_result = "fail"

    return LLMValidateResponse(
        final_result=final_result,
        relevance=relevance,
        instruction_following=instruction_following,
        truthfulness=truthfulness,
        hallucination=hallucination,
        raw_model_output=raw_output,
    )