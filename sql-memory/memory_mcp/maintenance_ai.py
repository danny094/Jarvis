"""
AI-Powered Memory Maintenance
Intelligentes Sorting mit Ollama Models + Optional Dual Validation
"""

import sqlite3
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Callable
import sys
import os

# Import helpers
sys.path.insert(0, os.path.dirname(__file__))
from ai_helpers import call_ollama, parse_ai_decision, write_conflict_log
from ai_prompts import PROMOTION_PROMPT, DUPLICATE_PROMPT, VALIDATION_PROMPT


def maintenance_run_ai(
    db_path: str,
    model: str = "qwen3:4b",
    validator_model: Optional[str] = None,
    ollama_url: str = "http://ollama:11434",
    stream_callback: Optional[Callable] = None
) -> Dict:
    """
    AI-gestütztes Memory Maintenance.
    
    Args:
        db_path: Path zur SQLite DB
        model: Primary Ollama Model
        validator_model: Optional Validator für Slow Mode
        ollama_url: Ollama Endpoint
        stream_callback: Optional Callback für Live Updates
        
    Returns:
        Results Dict mit Stats und Conflict Log
    """
    
    def emit(msg_type: str, data: Dict):
        """Helper zum Senden von Stream Events."""
        if stream_callback:
            stream_callback({"type": msg_type, **data})
    
    slow_mode = validator_model and validator_model != ""
    conflicts = []
    
    emit("info", {"message": f"Mode: {'Slow (Dual Validation)' if slow_mode else 'Normal'}"})
    emit("info", {"message": f"Primary Model: {model}"})
    if slow_mode:
        emit("info", {"message": f"Validator Model: {validator_model}"})
    
    # DB Connect mit Retry
    max_retries = 5
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(db_path, timeout=30.0)
            conn.execute("PRAGMA busy_timeout = 30000")
            cursor = conn.cursor()
            break
        except sqlite3.OperationalError:
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            else:
                return {"status": "error", "error": "Database locked"}
    
    results = {
        "duplicates_merged": 0,
        "promoted_to_ltm": 0,
        "summaries_created": 0,
        "graph_optimized": 0,
        "conflicts_count": 0,
        "ai_decisions": 0
    }
    
    try:
        # ==========================================
        # PHASE 1: AI-BASED STM → LTM PROMOTION
        # ==========================================
        emit("task_start", {"message": "Analysiere STM Entries für LTM Promotion..."})
        
        # Hole STM Entries
        cursor.execute("""
            SELECT id, content, created_at, layer
            FROM memory
            WHERE layer = 'stm'
            ORDER BY created_at ASC
        """)
        stm_entries = cursor.fetchall()
        
        emit("info", {"message": f"Gefunden: {len(stm_entries)} STM Entries"})
        
        promoted_count = 0
        for idx, (entry_id, content, created_at, layer) in enumerate(stm_entries):
            # Progress
            progress = int((idx / max(len(stm_entries), 1)) * 40)  # 0-40%
            emit("progress", {"progress": progress})
            
            # Berechne Alter
            try:
                entry_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                age_days = (datetime.now() - entry_date).days
            except:
                age_days = 0
            
            # AI Analyse
            emit("thinking", {"message": f"🤔 Analysiere Entry #{entry_id}..."})
            
            prompt = PROMOTION_PROMPT.format(
                entry_id=entry_id,
                content=content[:200],  # Limit für Performance
                created_at=created_at,
                age_days=age_days
            )
            
            # Primary Model
            ai_response = call_ollama(model, prompt, ollama_url)
            if not ai_response["success"]:
                emit("warning", {"message": f"AI Error für Entry #{entry_id}"})
                continue
            
            primary_decision = parse_ai_decision(ai_response["response"])
            results["ai_decisions"] += 1
            
            emit("thinking", {
                "message": f"💭 {primary_decision.get('reasoning', 'No reasoning')[:100]}..."
            })
            
            # Slow Mode: Validation
            if slow_mode and primary_decision.get("decision") == "PROMOTE":
                emit("thinking", {"message": f"🔍 Validator prüft Entry #{entry_id}..."})
                
                val_prompt = VALIDATION_PROMPT.format(
                    content=content[:200],
                    action="STM → LTM",
                    reasoning=primary_decision.get('reasoning', ''),
                    confidence=primary_decision.get('confidence', 0)
                )
                
                val_response = call_ollama(validator_model, val_prompt, ollama_url)
                if val_response["success"]:
                    validator_decision = parse_ai_decision(val_response["response"])
                    
                    # Check Consensus
                    if validator_decision.get("decision") == "REJECT":
                        # CONFLICT!
                        emit("warning", {"message": f"⚠️ Conflict bei Entry #{entry_id}"})
                        
                        conflicts.append({
                            "entry_id": entry_id,
                            "content": content,
                            "timestamp": created_at,
                            "layer": layer,
                            "primary_model": model,
                            "primary_action": "PROMOTE",
                            "primary_reasoning": primary_decision.get('reasoning', ''),
                            "primary_confidence": primary_decision.get('confidence', 0),
                            "validator_model": validator_model,
                            "validator_action": "REJECT",
                            "validator_reasoning": validator_decision.get('reasoning', ''),
                            "validator_confidence": validator_decision.get('confidence', 0)
                        })
                        results["conflicts_count"] += 1
                        continue  # Skip bei Conflict
                    else:
                        emit("success", {"message": f"✅✅ Double-Approved: Entry #{entry_id}"})
            
            # Execute Decision
            if primary_decision.get("decision") == "PROMOTE":
                cursor.execute("""
                    UPDATE memory SET layer = 'ltm' WHERE id = ?
                """, (entry_id,))
                promoted_count += 1
                emit("success", {"message": f"✅ Entry #{entry_id} → LTM"})
        
        results["promoted_to_ltm"] = promoted_count
        conn.commit()
        
        # ==========================================
        # PHASE 2: SIMPLE DUPLICATE DETECTION
        # ==========================================
        emit("task_start", {"message": "Suche Duplikate..."})
        emit("progress", {"progress": 50})
        
        # Einfache SQL-basierte Duplikatserkennung (AI wäre zu langsam für alle Paare)
        cursor.execute("""
            SELECT content, COUNT(*), GROUP_CONCAT(id) as ids
            FROM memory 
            WHERE layer = 'stm'
            GROUP BY content 
            HAVING COUNT(*) > 1
        """)
        duplicates = cursor.fetchall()
        
        for content, count, ids_str in duplicates:
            ids = [int(x) for x in ids_str.split(',')]
            keep_id = ids[0]
            delete_ids = ids[1:]
            
            cursor.execute(f"DELETE FROM memory WHERE id IN ({','.join(map(str, delete_ids))})")
            results["duplicates_merged"] += len(delete_ids)
            emit("success", {"message": f"🔀 {len(delete_ids)} Duplikate gemerged"})
        
        conn.commit()
        
        # ==========================================
        # PHASE 3: GRAPH OPTIMIERUNG
        # ==========================================
        emit("task_start", {"message": "Optimiere Knowledge Graph..."})
        emit("progress", {"progress": 80})
        
        cursor.execute("""
            DELETE FROM graph_nodes 
            WHERE id NOT IN (SELECT DISTINCT src_node_id FROM graph_edges)
            AND id NOT IN (SELECT DISTINCT dst_node_id FROM graph_edges)
        """)
        results["graph_optimized"] = cursor.rowcount
        conn.commit()
        
        emit("progress", {"progress": 100})
        
        # ==========================================
        # FINAL STATS
        # ==========================================
        cursor.execute("SELECT COUNT(*) FROM memory WHERE layer='stm'")
        stm_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM memory WHERE layer='mtm'")
        mtm_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM memory WHERE layer='ltm'")
        ltm_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM graph_nodes")
        nodes_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM graph_edges")
        edges_count = cursor.fetchone()[0]
        
        # Write Conflict Log
        conflict_log_path = None
        if conflicts:
            conflict_log_path = write_conflict_log(conflicts)
            emit("warning", {"message": f"📝 Conflict Log: {conflict_log_path}"})
        
        return {
            "status": "completed",
            "actions": results,
            "stats": {
                "stm": stm_count,
                "mtm": mtm_count,
                "ltm": ltm_count,
                "nodes": nodes_count,
                "edges": edges_count
            },
            "conflict_log": conflict_log_path,
            "models_used": {
                "primary": model,
                "validator": validator_model,
                "slow_mode": slow_mode
            }
        }
        
    finally:
        conn.close()
