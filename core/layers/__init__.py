# core/layers/__init__.py
"""
Die drei Layer der AI-Orchestration:
1. ThinkingLayer - Analysiert und plant (DeepSeek)
2. ControlLayer - Verifiziert den Plan (Qwen)
3. OutputLayer - Formuliert die Antwort (beliebig)
"""

from .thinking import ThinkingLayer
from .control import ControlLayer
from .output import OutputLayer

__all__ = ["ThinkingLayer", "ControlLayer", "OutputLayer"]
