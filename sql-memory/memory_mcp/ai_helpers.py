"""
AI Helper Functions für Memory Maintenance
Kommuniziert mit Ollama für intelligentes Sorting
"""

import json
import requests
from datetime import datetime
from typing import Dict, Optional, List
import os


def call_ollama(model: str, prompt: str, ollama_url: str = "http://ollama:11434") -> Dict:
    """
    Ruft Ollama Model auf und gibt Response zurück.
    
    Args:
        model: Model name (z.B. "qwen3:4b")
        prompt: Der Prompt
        ollama_url: Ollama Base URL
        
    Returns:
        {"response": "...", "success": True/False}
    """
    try:
        response = requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,  # Deterministisch
                    "top_p": 0.9
                }
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                "response": data.get("response", ""),
                "success": True
            }
        else:
            return {
                "response": f"Error: HTTP {response.status_code}",
                "success": False
            }
            
    except Exception as e:
        return {
            "response": f"Error: {str(e)}",
            "success": False
        }


def parse_ai_decision(response: str) -> Dict:
    """
    Parst AI Response in strukturiertes Format.
    
    Erwartet Format:
    Decision: PROMOTE/KEEP/DUPLICATE/etc
    Confidence: 85%
    Reasoning: ...
    
    Returns:
        {"decision": "...", "confidence": 85, "reasoning": "..."}
    """
    result = {
        "decision": None,
        "confidence": 0,
        "reasoning": ""
    }
    
    lines = response.strip().split('\n')
    for line in lines:
        if line.startswith("Decision:"):
            result["decision"] = line.split(":", 1)[1].strip()
        elif line.startswith("Confidence:"):
            conf_str = line.split(":", 1)[1].strip().replace("%", "")
            try:
                result["confidence"] = int(conf_str)
            except:
                pass
        elif line.startswith("Reasoning:"):
            result["reasoning"] = line.split(":", 1)[1].strip()
    
    return result


def write_conflict_log(conflicts: List[Dict], log_dir: str = "/app/data/maintenance_logs"):
    """
    Schreibt Conflicts in TXT File.
    
    Args:
        conflicts: Liste von Conflict Dicts
        log_dir: Verzeichnis für Logs
        
    Returns:
        Log file path
    """
    # Erstelle Verzeichnis falls nicht vorhanden
    os.makedirs(log_dir, exist_ok=True)
    
    # Dateiname mit Timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"maintenance_conflicts_{timestamp}.txt")
    
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("MEMORY MAINTENANCE CONFLICTS\n")
        f.write(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")
        
        for i, conflict in enumerate(conflicts, 1):
            f.write(f"CONFLICT #{i}\n")
            f.write("-" * 60 + "\n")
            f.write(f"Entry ID: {conflict.get('entry_id')}\n")
            f.write(f"Content: \"{conflict.get('content')}\"\n")
            f.write(f"Timestamp: {conflict.get('timestamp')}\n")
            f.write(f"Layer: {conflict.get('layer')}\n\n")
            
            f.write(f"PRIMARY DECISION ({conflict.get('primary_model')}):\n")
            f.write(f"→ Action: {conflict.get('primary_action')}\n")
            f.write(f"→ Reasoning: {conflict.get('primary_reasoning')}\n")
            f.write(f"→ Confidence: {conflict.get('primary_confidence')}%\n\n")
            
            f.write(f"VALIDATOR DECISION ({conflict.get('validator_model')}):\n")
            f.write(f"→ Action: {conflict.get('validator_action')}\n")
            f.write(f"→ Reasoning: {conflict.get('validator_reasoning')}\n")
            f.write(f"→ Confidence: {conflict.get('validator_confidence')}%\n\n")
            
            f.write("RESOLUTION: SKIPPED (No consensus)\n")
            f.write("\n" + "=" * 60 + "\n\n")
    
    return log_file
