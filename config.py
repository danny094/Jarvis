import os

# ═══════════════════════════════════════════════════════════════
# CORS - Security
# ═══════════════════════════════════════════════════════════════
# WICHTIG: Passe die erlaubten Origins an deine Umgebung an!
ALLOW_ORIGINS = [
    # LobeChat
    "http://localhost:3210",
    "http://127.0.0.1:3210",
    "http://192.168.0.226:3210",
    # WebUI
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.0.226:3000",
    # Wildcard für Entwicklung (kann später eingeschränkt werden)
    "*",
]

# ═══════════════════════════════════════════════════════════════
# SERVICES
# ═══════════════════════════════════════════════════════════════
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://ollama:11434")
MCP_BASE = os.getenv("MCP_BASE", "http://mcp-sql-memory:8081")
VALIDATOR_URL = os.getenv("VALIDATOR_URL", "http://validator-service:8000")
CONTAINER_MANAGER_URL = os.getenv("CONTAINER_MANAGER_URL", "http://container-manager:8400")

# ═══════════════════════════════════════════════════════════════
# MODEL KONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Layer 1: ThinkingLayer - Analysiert Intent & Plant
# Braucht JSON-Output, kein Overthinking → kleines schnelles Model
THINKING_MODEL = os.getenv("THINKING_MODEL", "ministral-3:3b")

# Layer 2: ControlLayer - Verifiziert & Korrigiert
# Simple Ja/Nein Entscheidungen → ultra-kleines Model reicht
CONTROL_MODEL = os.getenv("CONTROL_MODEL", "qwen2.5:1.5b")

# Layer 3: OutputLayer - Generiert Antwort (Default, kann per Request überschrieben werden)
# Qualität wichtig → größeres Model okay
OUTPUT_MODEL = os.getenv("OUTPUT_MODEL", "ministral-3:8b")

# CODE MODEL - Spezialisiert auf Code-Aufgaben
# Wird NUR bei Code-Anfragen genutzt (statt OUTPUT_MODEL)
CODE_MODEL = os.getenv("CODE_MODEL", "qwen2.5-coder:3b")

# Embedding Model für Semantic Search
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16")

# ═══════════════════════════════════════════════════════════════
# LAYER TOGGLES & OPTIMIERUNG
# ═══════════════════════════════════════════════════════════════

# ControlLayer komplett deaktivieren
ENABLE_CONTROL_LAYER = os.getenv("ENABLE_CONTROL_LAYER", "true").lower() == "true"

# ControlLayer bei low-risk überspringen (Speed-Optimierung!)
# Bei "Was ist 2+2?" braucht man keine Verifikation → SKIP!
SKIP_CONTROL_ON_LOW_RISK = os.getenv("SKIP_CONTROL_ON_LOW_RISK", "true").lower() == "true"

# Container-Manager für Sandbox-Ausführung
ENABLE_CONTAINER_MANAGER = os.getenv("ENABLE_CONTAINER_MANAGER", "true").lower() == "true"

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
