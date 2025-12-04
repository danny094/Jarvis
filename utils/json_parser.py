# utils/json_parser.py
"""
Robuster JSON-Parser für LLM-Outputs.

LLMs geben oft "fast-JSON" zurück mit:
- Text vor/nach dem JSON
- JSON in Markdown-Codeblocks
- Trailing commas
- Fehlende Quotes

Dieser Parser versucht mehrere Strategien.
"""

import json
import re
from typing import Any, Dict, Optional
from utils.logger import log_warning, log_error, log_debug


def safe_parse_json(
    raw: str, 
    default: Optional[Dict] = None,
    context: str = "unknown"
) -> Dict[str, Any]:
    """
    Robustes JSON-Parsing mit mehreren Fallback-Strategien.
    
    Args:
        raw: Der rohe String (möglicherweise mit Text drum herum)
        default: Fallback-Wert wenn alles fehlschlägt
        context: Für Logging (z.B. "ThinkingLayer", "ControlLayer")
    
    Returns:
        Geparstes Dict oder default
    """
    if not raw or not raw.strip():
        log_warning(f"[JSON:{context}] Empty input, using default")
        return default or {}
    
    # Strategie 1: Direktes Parsing
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    
    # Strategie 2: JSON aus Text extrahieren (erste { bis letzte })
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        extracted = raw[start:end]
        return json.loads(extracted)
    except (ValueError, json.JSONDecodeError):
        pass
    
    # Strategie 3: JSON aus Markdown-Codeblock extrahieren
    # Matches: ```json {...} ``` oder ``` {...} ```
    codeblock_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
    match = re.search(codeblock_pattern, raw)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Strategie 4: Versuche JSON mit Fixes zu reparieren
    try:
        fixed = _attempt_json_repair(raw)
        if fixed:
            return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # Strategie 5: Regex für einfache Key-Value Extraktion
    try:
        extracted = _extract_key_values(raw)
        if extracted:
            log_warning(f"[JSON:{context}] Used regex extraction fallback")
            return extracted
    except Exception:
        pass
    
    # Alles fehlgeschlagen
    log_error(f"[JSON:{context}] All parsing strategies failed")
    log_debug(f"[JSON:{context}] Raw input was: {raw[:200]}...")
    
    return default or {}


def _attempt_json_repair(raw: str) -> Optional[str]:
    """
    Versucht häufige JSON-Fehler zu reparieren.
    """
    # Extrahiere erst den JSON-Teil
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        json_str = raw[start:end]
    except ValueError:
        return None
    
    # Fix 1: Trailing commas entfernen
    # ,} oder ,] → } oder ]
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)
    
    # Fix 2: Single quotes → Double quotes (vorsichtig)
    # Nur wenn keine double quotes vorhanden
    if '"' not in json_str and "'" in json_str:
        json_str = json_str.replace("'", '"')
    
    # Fix 3: Unquoted keys → Quoted keys
    # key: value → "key": value
    json_str = re.sub(r'(\s*)(\w+)(\s*):', r'\1"\2"\3:', json_str)
    
    # Fix 4: True/False/None normalisieren
    json_str = re.sub(r'\bTrue\b', 'true', json_str)
    json_str = re.sub(r'\bFalse\b', 'false', json_str)
    json_str = re.sub(r'\bNone\b', 'null', json_str)
    
    return json_str


def _extract_key_values(raw: str) -> Optional[Dict[str, Any]]:
    """
    Letzte Rettung: Extrahiert Key-Value-Paare via Regex.
    
    Funktioniert für einfache Strukturen wie:
    intent: "User fragt nach X"
    needs_memory: true
    """
    result = {}
    
    # Pattern für "key": "value" oder "key": true/false/number
    patterns = [
        r'"(\w+)"\s*:\s*"([^"]*)"',           # "key": "string"
        r'"(\w+)"\s*:\s*(true|false)',         # "key": bool
        r'"(\w+)"\s*:\s*(\d+(?:\.\d+)?)',      # "key": number
        r'(\w+)\s*:\s*"([^"]*)"',              # key: "string" (unquoted key)
        r'(\w+)\s*:\s*(true|false)',           # key: bool (unquoted)
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, raw, re.IGNORECASE)
        for key, value in matches:
            # Type conversion
            if value.lower() == 'true':
                result[key] = True
            elif value.lower() == 'false':
                result[key] = False
            elif value.replace('.', '').isdigit():
                result[key] = float(value) if '.' in value else int(value)
            else:
                result[key] = value
    
    return result if result else None


def extract_json_array(raw: str, default: list = None) -> list:
    """
    Extrahiert ein JSON-Array aus Text.
    
    Nützlich für Listen wie memory_keys: ["key1", "key2"]
    """
    if not raw:
        return default or []
    
    # Strategie 1: Direktes Parsing
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except:
        pass
    
    # Strategie 2: Array aus Text extrahieren
    try:
        start = raw.index("[")
        end = raw.rindex("]") + 1
        return json.loads(raw[start:end])
    except:
        pass
    
    # Strategie 3: Comma-separated values
    # "key1, key2, key3" → ["key1", "key2", "key3"]
    if "," in raw and "[" not in raw:
        items = [item.strip().strip('"\'') for item in raw.split(",")]
        return [item for item in items if item]
    
    return default or []
