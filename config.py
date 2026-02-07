import os

# ═══════════════════════════════════════════════════════════════
# CORS
# ═══════════════════════════════════════════════════════════════
ALLOW_ORIGINS = [
    "http://localhost:8400",
    "http://localhost:8100",
]

# ═══════════════════════════════════════════════════════════════
from utils.settings import settings

# ═══════════════════════════════════════════════════════════════
# SERVICES
# ═══════════════════════════════════════════════════════════════
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://ollama:11434")
MCP_BASE = os.getenv("MCP_BASE", "http://mcp-sql-memory:8081")
VALIDATOR_URL = os.getenv("VALIDATOR_URL", "http://validator-service:8000")

# ═══════════════════════════════════════════════════════════════
# MODEL KONFIGURATION (Dynamic)
# ═══════════════════════════════════════════════════════════════

def get_thinking_model():
    return settings.get("THINKING_MODEL", os.getenv("THINKING_MODEL", "deepseek-r1:8b"))

def get_control_model():
    return settings.get("CONTROL_MODEL", os.getenv("CONTROL_MODEL", "qwen3:4b"))

def get_output_model():
    return settings.get("OUTPUT_MODEL", os.getenv("OUTPUT_MODEL", "ministral-3:3b"))

# Backward compatibility (Module level vars will be static on import, so use functions where possible)
# OR use a class/property trick. For now, we expose functions but keep vars for legacy.
THINKING_MODEL = get_thinking_model()
CONTROL_MODEL = get_control_model()
OUTPUT_MODEL = get_output_model()

# Embedding Model für Semantic Search
# Embedding Model für Semantic Search
EMBEDDING_MODEL = settings.get("EMBEDDING_MODEL", os.getenv("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16"))

# ═══════════════════════════════════════════════════════════════
# TOOL SELECTOR (Layer 0)
# ═══════════════════════════════════════════════════════════════
def get_tool_selector_model():
    return settings.get("TOOL_SELECTOR_MODEL", os.getenv("TOOL_SELECTOR_MODEL", "qwen2.5:1.5b-instruct"))

TOOL_SELECTOR_MODEL = get_tool_selector_model()
ENABLE_TOOL_SELECTOR = settings.get("ENABLE_TOOL_SELECTOR", os.getenv("ENABLE_TOOL_SELECTOR", "true").lower() == "true")

# ═══════════════════════════════════════════════════════════════
# LAYER TOGGLES & OPTIMIERUNG
# ═══════════════════════════════════════════════════════════════

# ControlLayer komplett deaktivieren
ENABLE_CONTROL_LAYER = settings.get("ENABLE_CONTROL_LAYER", os.getenv("ENABLE_CONTROL_LAYER", "true").lower() == "true")

# ControlLayer bei low-risk überspringen (Speed-Optimierung!)
SKIP_CONTROL_ON_LOW_RISK = settings.get("SKIP_CONTROL_ON_LOW_RISK", os.getenv("SKIP_CONTROL_ON_LOW_RISK", "false").lower() == "true")

# ═══════════════════════════════════════════════════════════════
# VALIDATOR SERVICE
# ═══════════════════════════════════════════════════════════════
ENABLE_VALIDATION = settings.get("ENABLE_VALIDATION", os.getenv("ENABLE_VALIDATION", "true").lower() == "true")
VALIDATION_THRESHOLD = float(settings.get("VALIDATION_THRESHOLD", os.getenv("VALIDATION_THRESHOLD", "0.70")))
VALIDATION_HARD_FAIL = settings.get("VALIDATION_HARD_FAIL", os.getenv("VALIDATION_HARD_FAIL", "true").lower() == "true")

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")
ENABLE_CORS = os.getenv("ENABLE_CORS", "true").lower() == "true"

# ═══════════════════════════════════════════════════════════════
# CHUNKING CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Ab wann wird ein Text gechunked (Token-Schätzung)
CHUNKING_THRESHOLD = int(os.getenv("CHUNKING_THRESHOLD", "6000"))

# Maximale Tokens pro Chunk
CHUNK_MAX_TOKENS = int(os.getenv("CHUNK_MAX_TOKENS", "4000"))

# Overlap zwischen Chunks für Kontexterhalt
CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "200"))

# Workspace-Pfad für Session-Daten
WORKSPACE_BASE = os.getenv("WORKSPACE_BASE", "/tmp/trion/jarvis/workspace")

# Chunking aktivieren/deaktivieren
ENABLE_CHUNKING = os.getenv("ENABLE_CHUNKING", "true").lower() == "true"
