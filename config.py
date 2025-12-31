import os

# ═══════════════════════════════════════════════════════════════
# CORS
# ═══════════════════════════════════════════════════════════════
ALLOW_ORIGINS = ["*"]

# ═══════════════════════════════════════════════════════════════
# SERVICES
# ═══════════════════════════════════════════════════════════════
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://ollama:11434")
MCP_BASE = os.getenv("MCP_BASE", "http://mcp-sql-memory:8081")
VALIDATOR_URL = os.getenv("VALIDATOR_URL", "http://validator-service:8000")

# ═══════════════════════════════════════════════════════════════
# MODEL KONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Layer 1: ThinkingLayer - Analysiert Intent & Plant
THINKING_MODEL = os.getenv("THINKING_MODEL", "deepseek-r1:8b")

# Layer 2: ControlLayer - Verifiziert & Korrigiert
CONTROL_MODEL = os.getenv("CONTROL_MODEL", "qwen3:4b")

# Layer 3: OutputLayer - Generiert Antwort (Default, kann per Request überschrieben werden)
OUTPUT_MODEL = os.getenv("OUTPUT_MODEL", "llama3.1:8b")

# Embedding Model für Semantic Search
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16")

# ═══════════════════════════════════════════════════════════════
# LAYER TOGGLES & OPTIMIERUNG
# ═══════════════════════════════════════════════════════════════

# ControlLayer komplett deaktivieren
ENABLE_CONTROL_LAYER = os.getenv("ENABLE_CONTROL_LAYER", "true").lower() == "true"

# ControlLayer bei low-risk überspringen (Speed-Optimierung!)
SKIP_CONTROL_ON_LOW_RISK = os.getenv("SKIP_CONTROL_ON_LOW_RISK", "false").lower() == "true"

# ═══════════════════════════════════════════════════════════════
# VALIDATOR SERVICE
# ═══════════════════════════════════════════════════════════════
ENABLE_VALIDATION = os.getenv("ENABLE_VALIDATION", "true").lower() == "true"
VALIDATION_THRESHOLD = float(os.getenv("VALIDATION_THRESHOLD", "0.70"))
VALIDATION_HARD_FAIL = os.getenv("VALIDATION_HARD_FAIL", "true").lower() == "true"

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")
ENABLE_CORS = os.getenv("ENABLE_CORS", "true").lower() == "true"
