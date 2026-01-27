from fastapi import APIRouter
from config import OLLAMA_BASE
import requests

router = APIRouter()

@router.get("/tags")
def get_tags():
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"models": [], "error": str(e)}