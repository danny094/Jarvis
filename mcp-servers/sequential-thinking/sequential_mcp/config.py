"""
Configuration for Sequential Thinking MCP Server
"""

# Server settings
HOST = "0.0.0.0"
PORT = 8001

# Sequential Engine settings
MAX_STEPS_DEFAULT = 100
MAX_DURATION_DEFAULT = 3600  # seconds

# Paths
import os
JARVIS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
