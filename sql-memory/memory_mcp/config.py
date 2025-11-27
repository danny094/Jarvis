import os

DB_PATH = os.getenv("DB_PATH", "/app/data/memory.db")

# Keywords zur Auto-Layer-Klassifikation:
MTM_KEYWORDS = [
    "project", "plan", "todo", "setup", "docker", "compose",
    "path", "config", "mcp", "bridge", "server", "agent",
    "qdrant", "ai", "llm", "architecture"
]

LTM_KEYWORDS = [
    "hardware", "preferences", "i like", "i prefer",
    "mein system", "meine karte", "mein server",
    "family", "kids", "always", "grundsätzlich"
]
