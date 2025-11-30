import os

# CORS
ALLOW_ORIGINS = [
    "*",
]


# ---------- LLM & MCP ----------
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://ollama:11434")
MCP_BASE = os.getenv("MCP_BASE", "http://mcp-sql-memory:8081")

# ---------- Validator Service ----------
VALIDATOR_URL = os.getenv("VALIDATOR_URL", "http://validator-service:8000")

# Ob der Validator-Service benutzt wird
ENABLE_VALIDATION = os.getenv("ENABLE_VALIDATION", "true").lower() == "true"

# Mindest-Similarity
VALIDATION_THRESHOLD = float(os.getenv("VALIDATION_THRESHOLD", "0.70"))

# Hard-Mode (Antwort blockieren, wenn Similarity zu klein)
VALIDATION_HARD_FAIL = os.getenv("VALIDATION_HARD_FAIL", "true").lower() == "true"

# ---------- Logging / CORS ----------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")
ENABLE_CORS = os.getenv("ENABLE_CORS", "true").lower() == "true"