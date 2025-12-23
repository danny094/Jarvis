# utils/code_formatter.py
"""
Code-Formatierung für Python-Code.

Wird verwendet von:
- CoreBridge (für Code aus Chat-Nachrichten)
- /api/execute (für Code aus WebUI Run-Button)

Die Formatierung nutzt das Code-Model (Ollama) um schlecht 
formatierten Code (einzeilig, ohne Einrückungen) zu korrigieren.
"""

import re
import httpx
from typing import Optional

from config import OLLAMA_BASE, CODE_MODEL
from utils.logger import log_info, log_warning


def needs_formatting(code: str) -> bool:
    """
    Prüft ob Code formatiert werden muss.
    
    Code braucht Formatierung wenn:
    - Er keine Newlines hat (einzeilig)
    - Er Newlines hat aber keine Einrückungen
    
    Args:
        code: Der zu prüfende Code
        
    Returns:
        True wenn Formatierung nötig, False wenn Code okay ist
    """
    if not code or len(code) < 20:
        return False
    
    has_newlines = '\n' in code
    # Prüft: Newline gefolgt von Whitespace gefolgt von Non-Whitespace
    has_indentation = bool(re.search(r'\n[ \t]+\S', code))
    
    # Braucht Formatierung wenn:
    # - Keine Newlines (einzeilig) UND länger als 50 Zeichen
    # - Oder: Hat Newlines aber keine Einrückungen
    if not has_newlines and len(code) > 50:
        return True
    if has_newlines and not has_indentation:
        return True
    
    return False


async def format_code_with_model(code: str) -> str:
    """
    Nutzt das Code-Model um schlecht formatierten Code zu korrigieren.
    
    WICHTIG: Das Model darf den Code NUR formatieren, nicht inhaltlich ändern!
    
    Args:
        code: Der zu formatierende Code
        
    Returns:
        Formatierter Code (oder Original bei Fehler)
    """
    prompt = f"""Du bist ein Code-Formatierer. Formatiere den folgenden Python-Code korrekt.

REGELN:
- Füge korrekte Einrückungen hinzu (4 Spaces pro Level)
- Füge Newlines zwischen Statements ein
- Ändere den Code NICHT inhaltlich
- Korrigiere KEINE logischen Fehler
- Füge KEINE Kommentare hinzu
- Gib NUR den formatierten Code zurück, keine Erklärung

CODE:
{code}

FORMATIERTER CODE:"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{OLLAMA_BASE}/api/generate",
                json={
                    "model": CODE_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0}  # Deterministic
                }
            )
            response.raise_for_status()
            result = response.json()
            formatted = result.get("response", "").strip()
            
            # Bereinigen: Manchmal gibt das Model Markdown-Blöcke zurück
            if formatted.startswith("```"):
                match = re.search(r'```(?:\w+)?\n?(.*?)```', formatted, re.DOTALL)
                if match:
                    formatted = match.group(1).strip()
            
            log_info(f"[CodeFormatter] Formatted code: {len(code)} → {len(formatted)} chars")
            return formatted if formatted else code
            
    except Exception as e:
        log_warning(f"[CodeFormatter] Format failed: {e}, using original")
        return code


async def ensure_formatted(code: str) -> str:
    """
    Stellt sicher dass Code korrekt formatiert ist.
    
    Prüft erst ob Formatierung nötig ist, formatiert dann wenn nötig.
    
    Args:
        code: Der Code
        
    Returns:
        Formatierter Code (oder Original wenn keine Formatierung nötig)
    """
    if needs_formatting(code):
        log_info(f"[CodeFormatter] Code needs formatting, calling model...")
        return await format_code_with_model(code)
    else:
        log_info(f"[CodeFormatter] Code is well-formatted, no changes needed")
        return code
