# maintenance/worker.py
"""
Memory Maintenance Worker

Führt intelligente Aufräumarbeiten im Memory durch:
- Duplikat-Erkennung und Merging
- STM → MTM → LTM Promotion
- Zusammenfassungen erstellen
- Graph-Optimierung
- Veraltete Einträge bereinigen
"""

import asyncio
import httpx
from typing import Dict, Any, List, Optional, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from config import OLLAMA_BASE, THINKING_MODEL
from utils.logger import log_info, log_error, log_warning
from mcp.client import call_tool


def unwrap_mcp_result(result: Any) -> Any:
    """
    Unwraps MCP Hub result from nested structure.
    
    MCP Hub returns: {
        "result": {
            "content": [...],
            "structuredContent": { <actual data> },
            "isError": False
        }
    }
    
    This function extracts the actual data from structuredContent.
    """
    if not isinstance(result, dict):
        return result
    
    # Level 1: result wrapper
    inner = result.get("result", result)
    if not isinstance(inner, dict):
        return inner
    
    # Level 2: structuredContent
    structured = inner.get("structuredContent")
    if structured is not None:
        return structured
    
    # Fallback: return inner as-is
    return inner


class MaintenanceState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class MaintenanceStats:
    """Statistiken einer Maintenance-Session."""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Gefundene Items
    stm_entries: int = 0
    mtm_entries: int = 0
    ltm_entries: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0
    
    # Aktionen
    duplicates_found: int = 0
    duplicates_merged: int = 0
    promoted_to_mtm: int = 0
    promoted_to_ltm: int = 0
    entries_deleted: int = 0
    summaries_created: int = 0
    edges_pruned: int = 0
    
    # Fehler
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "counts": {
                "stm_entries": self.stm_entries,
                "mtm_entries": self.mtm_entries,
                "ltm_entries": self.ltm_entries,
                "graph_nodes": self.graph_nodes,
                "graph_edges": self.graph_edges,
            },
            "actions": {
                "duplicates_found": self.duplicates_found,
                "duplicates_merged": self.duplicates_merged,
                "promoted_to_mtm": self.promoted_to_mtm,
                "promoted_to_ltm": self.promoted_to_ltm,
                "entries_deleted": self.entries_deleted,
                "summaries_created": self.summaries_created,
                "edges_pruned": self.edges_pruned,
            },
            "errors": self.errors,
        }


class MaintenanceWorker:
    """
    Memory Maintenance Worker.
    
    Führt KI-gestützte Aufräumarbeiten durch.
    Streamt Progress-Updates für UI.
    """
    
    def __init__(self):
        self.state = MaintenanceState.IDLE
        self.progress = 0.0
        self.current_task = ""
        self.stats = MaintenanceStats()
        self._cancel_requested = False
    
    def get_status(self) -> Dict[str, Any]:
        """Aktueller Status für API."""
        return {
            "state": self.state.value,
            "progress": self.progress,
            "current_task": self.current_task,
            "stats": self.stats.to_dict(),
        }
    
    def cancel(self):
        """Bricht laufende Maintenance ab."""
        if self.state == MaintenanceState.RUNNING:
            self._cancel_requested = True
            log_info("[Maintenance] Cancel requested")
    
    async def get_memory_status(self) -> Dict[str, Any]:
        """Holt aktuellen Memory-Status vom MCP."""
        try:
            # Alle Conversations listen
            conv_result = unwrap_mcp_result(call_tool("memory_list_conversations", {
                "limit": 100
            }, timeout=10))
            
            conversations = conv_result.get("conversations", []) if isinstance(conv_result, dict) else []
            total_entries = sum(c.get("entry_count", 0) for c in conversations)
            
            log_info(f"[Maintenance] Found {len(conversations)} conversations, {total_entries} entries")
            
            # Graph Stats
            graph_data = unwrap_mcp_result(call_tool("memory_graph_stats", {}, timeout=10))
            
            return {
                "conversations": len(conversations),
                "stm_entries": total_entries,
                "mtm_entries": 0,
                "ltm_entries": 0,
                "graph_nodes": graph_data.get("nodes", 0) if isinstance(graph_data, dict) else 0,
                "graph_edges": graph_data.get("edges", 0) if isinstance(graph_data, dict) else 0,
            }
        except Exception as e:
            log_error(f"[Maintenance] Failed to get memory status: {e}")
            return {
                "conversations": 0,
                "stm_entries": 0,
                "mtm_entries": 0,
                "ltm_entries": 0,
                "graph_nodes": 0,
                "graph_edges": 0,
                "error": str(e)
            }
    
    async def run_maintenance(
        self,
        tasks: List[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Führt Maintenance durch und streamt Progress.
        
        Args:
            tasks: Liste der Tasks ["duplicates", "promote", "summarize", "graph", "embeddings"]
        
        Yields:
            Progress-Updates als Dict
        """
        if self.state == MaintenanceState.RUNNING:
            yield {"type": "error", "message": "Maintenance already running"}
            return
        
        # Default: Alle Tasks
        if not tasks:
            tasks = ["duplicates", "promote", "summarize", "graph"]
        
        self.state = MaintenanceState.RUNNING
        self.progress = 0.0
        self._cancel_requested = False
        self.stats = MaintenanceStats()
        self.stats.started_at = datetime.now()
        
        yield {"type": "started", "tasks": tasks}
        
        try:
            # Initial Status holen
            status = await self.get_memory_status()
            self.stats.stm_entries = status.get("stm_entries", 0)
            self.stats.ltm_entries = status.get("ltm_entries", 0)
            self.stats.graph_nodes = status.get("graph_nodes", 0)
            self.stats.graph_edges = status.get("graph_edges", 0)
            
            yield {
                "type": "status",
                "message": "Memory-Status geladen",
                "data": status
            }
            
            total_tasks = len(tasks)
            
            for i, task in enumerate(tasks):
                if self._cancel_requested:
                    self.state = MaintenanceState.CANCELLED
                    yield {"type": "cancelled", "message": "Maintenance abgebrochen"}
                    return
                
                base_progress = (i / total_tasks) * 100
                
                if task == "duplicates":
                    async for update in self._find_duplicates():
                        update["progress"] = base_progress + (update.get("sub_progress", 0) / total_tasks)
                        yield update
                
                elif task == "promote":
                    async for update in self._promote_entries():
                        update["progress"] = base_progress + (update.get("sub_progress", 0) / total_tasks)
                        yield update
                
                elif task == "summarize":
                    async for update in self._create_summaries():
                        update["progress"] = base_progress + (update.get("sub_progress", 0) / total_tasks)
                        yield update
                
                elif task == "graph":
                    async for update in self._optimize_graph():
                        update["progress"] = base_progress + (update.get("sub_progress", 0) / total_tasks)
                        yield update
                
                self.progress = ((i + 1) / total_tasks) * 100
            
            self.state = MaintenanceState.COMPLETED
            self.stats.completed_at = datetime.now()
            
            yield {
                "type": "completed",
                "message": "Maintenance abgeschlossen",
                "stats": self.stats.to_dict()
            }
            
        except Exception as e:
            self.state = MaintenanceState.ERROR
            self.stats.errors.append(str(e))
            log_error(f"[Maintenance] Error: {e}")
            yield {"type": "error", "message": str(e)}
        
        finally:
            self.current_task = ""
    
    async def _find_duplicates(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Findet und merged Duplikate."""
        self.current_task = "Duplikate suchen..."
        yield {"type": "task_start", "task": "duplicates", "message": "Suche Duplikate..."}
        
        try:
            # Alle Einträge aus ALLEN Conversations laden
            all_entries = unwrap_mcp_result(call_tool("memory_all_recent", {
                "limit": 500
            }, timeout=30))
            
            entries = all_entries.get("entries", []) if isinstance(all_entries, dict) else []
            total = len(entries)
            
            if total == 0:
                yield {"type": "task_progress", "message": "Keine Einträge gefunden", "sub_progress": 100}
                return
            
            yield {"type": "task_progress", "message": f"Analysiere {total} Einträge...", "sub_progress": 10}
            
            # KI analysieren lassen
            if total > 5:
                try:
                    duplicates = await self._ai_find_duplicates(entries[:50])  # Max 50 für KI
                    self.stats.duplicates_found = len(duplicates)
                except Exception as e:
                    log_error(f"AI duplicate check failed: {e}")
                    duplicates = []
                    self.stats.errors.append(f"Duplicate check: {e}")
                
                yield {
                    "type": "task_progress",
                    "message": f"{len(duplicates)} potentielle Duplikate gefunden",
                    "sub_progress": 50
                }
                
                log_info(f"[Maintenance] About to merge {len(duplicates)} duplicate groups")
                log_info(f"[Maintenance] Duplicates data: {duplicates}")
                
                # Duplikate TATSÄCHLICH mergen
                for dup in duplicates:
                    if self._cancel_requested:
                        return
                    
                    try:
                        indices = dup.get("indices", [])
                        log_info(f"[Maintenance] Processing dup with indices: {indices}")
                        if len(indices) >= 2:
                            # Get IDs of duplicate entries
                            entry_ids = [entries[idx]["id"] for idx in indices if idx < len(entries)]
                            
                            # Keep first, delete rest
                            ids_to_delete = entry_ids[1:]
                            
                            # Delete duplicates
                            result = unwrap_mcp_result(call_tool("memory_delete_bulk", {
                                "ids": ids_to_delete
                            }, timeout=10))
                            
                            if isinstance(result, dict):
                                deleted = result.get("deleted", 0)
                                self.stats.duplicates_merged += deleted
                    
                    except Exception as e:
                        log_error(f"Failed to merge duplicate: {e}")
                        self.stats.errors.append(f"Merge failed: {e}")
                
                yield {
                    "type": "task_progress",
                    "message": f"{self.stats.duplicates_merged} Duplikate gemerged",
                    "sub_progress": 100
                }
            else:
                yield {"type": "task_progress", "message": "Zu wenig Einträge für Duplikat-Check", "sub_progress": 100}
            
            # BONUS: Graph duplicate merging
            try:
                graph_dups = unwrap_mcp_result(call_tool("graph_find_duplicate_nodes", {}, timeout=10))
                
                if isinstance(graph_dups, dict):
                    dup_groups = graph_dups.get("duplicate_groups", [])
                    
                    for group in dup_groups:
                        if self._cancel_requested:
                            return
                        
                        node_ids = group.get("node_ids", [])
                        if len(node_ids) >= 2:
                            # Merge graph nodes
                            unwrap_mcp_result(call_tool("graph_merge_nodes", {
                                "node_ids": node_ids
                            }, timeout=10))
            except Exception as e:
                log_error(f"Graph duplicate merge failed: {e}")
            
        except Exception as e:
            yield {"type": "task_error", "task": "duplicates", "message": str(e)}

    async def _ai_find_duplicates(self, entries: List[Dict]) -> List[Dict]:
        """Lässt KI Duplikate identifizieren."""
        if not entries:
            return []
        
        # Entries für Prompt formatieren
        entries_text = "\n".join([
            f"[{i}] {e.get('content', '')[:200]}"
            for i, e in enumerate(entries)
        ])
        
        prompt = f"""Analysiere diese Memory-Einträge und finde DUPLIKATE oder SEHR ÄHNLICHE Inhalte.

Einträge:
{entries_text}

Antworte NUR mit JSON - keine Erklärung:
{{
    "duplicates": [
        {{"indices": [0, 3], "reason": "Gleicher Inhalt über Alter"}},
        {{"indices": [5, 7, 12], "reason": "Alle über Geburtstag"}}
    ]
}}

Wenn keine Duplikate: {{"duplicates": []}}"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={
                        "model": THINKING_MODEL,
                        "prompt": prompt,
                        "stream": False
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    text = result.get("response", "")
                    
                    # JSON extrahieren
                    import json
                    import re
                    
                    match = re.search(r'\{[\s\S]*\}', text)
                    if match:
                        data = json.loads(match.group())
                        return data.get("duplicates", [])
            
            return []
            
        except Exception as e:
            log_error(f"[Maintenance] AI duplicate check failed: {e}")
            return []
    
    async def _promote_entries(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Promotet wichtige STM-Einträge zu MTM/LTM."""
        self.current_task = "Einträge kategorisieren..."
        yield {"type": "task_start", "task": "promote", "message": "Analysiere wichtige Einträge..."}
        
        try:
            # Alle STM Einträge aus ALLEN Conversations
            stm_entries = unwrap_mcp_result(call_tool("memory_all_recent", {
                "limit": 100
            }, timeout=30))
            
            entries = stm_entries.get("entries", []) if isinstance(stm_entries, dict) else []
            
            if not entries:
                yield {"type": "task_progress", "message": "Keine STM-Einträge", "sub_progress": 100}
                return
            
            yield {"type": "task_progress", "message": f"Analysiere {len(entries)} Einträge...", "sub_progress": 20}
            
            # KI entscheiden lassen was wichtig ist
            try:
                promotions = await self._ai_categorize_entries(entries[:30])
            except Exception as e:
                log_error(f"AI categorize failed: {e}")
                promotions = {"to_ltm": [], "to_delete": []}
                self.stats.errors.append(f"Categorize: {e}")
            
            # Promote to LTM
            for promo in promotions.get("to_ltm", []):
                if self._cancel_requested:
                    return
                
                # Als Fakt speichern
                entry = entries[promo["index"]] if promo["index"] < len(entries) else None
                if entry:
                    call_tool("memory_fact_save", {
                        "conversation_id": "global",
                        "key": promo.get("key", f"fact_{promo['index']}"),
                        "value": entry.get("content", "")[:500]
                    }, timeout=10)
                    self.stats.promoted_to_ltm += 1
            
            # DELETE unwanted entries
            to_delete_indices = promotions.get("to_delete", [])
            if to_delete_indices:
                try:
                    # Get IDs of entries to delete
                    ids_to_delete = [entries[idx]["id"] for idx in to_delete_indices if idx < len(entries)]
                    
                    # Delete them
                    result = unwrap_mcp_result(call_tool("memory_delete_bulk", {
                        "ids": ids_to_delete
                    }, timeout=10))
                    
                    if isinstance(result, dict):
                        deleted = result.get("deleted", 0)
                        self.stats.entries_deleted += deleted
                
                except Exception as e:
                    log_error(f"Failed to delete entries: {e}")
                    self.stats.errors.append(f"Delete failed: {e}")
            
            yield {
                "type": "task_progress",
                "message": f"{self.stats.promoted_to_ltm} zu LTM promotet, {self.stats.entries_deleted} gelöscht",
                "sub_progress": 100
            }
            
        except Exception as e:
            yield {"type": "task_error", "task": "promote", "message": str(e)}

    async def _ai_categorize_entries(self, entries: List[Dict]) -> Dict:
        """Lässt KI Einträge kategorisieren."""
        if not entries:
            return {"to_ltm": [], "to_delete": []}
        
        entries_text = "\n".join([
            f"[{i}] {e.get('content', '')[:150]}"
            for i, e in enumerate(entries)
        ])
        
        prompt = f"""Analysiere diese Gesprächs-Einträge und kategorisiere sie:

{entries_text}

Entscheide für jeden Eintrag:
- WICHTIGER FAKT (Name, Alter, Beruf, Präferenzen) → zu LTM
- UNWICHTIG (Smalltalk, Wiederholungen) → löschen
- BEHALTEN (normale Konversation) → nichts tun

Antworte NUR mit JSON:
{{
    "to_ltm": [
        {{"index": 0, "key": "user_name", "reason": "Name des Users"}}
    ],
    "to_delete": [1, 5, 7]
}}"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={
                        "model": THINKING_MODEL,
                        "prompt": prompt,
                        "stream": False
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    text = result.get("response", "")
                    
                    import json
                    import re
                    
                    match = re.search(r'\{[\s\S]*\}', text)
                    if match:
                        return json.loads(match.group())
            
            return {"to_ltm": [], "to_delete": []}
            
        except Exception as e:
            log_error(f"[Maintenance] AI categorize failed: {e}")
            return {"to_ltm": [], "to_delete": []}
    
    async def _create_summaries(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Erstellt Zusammenfassungen von alten Einträgen."""
        self.current_task = "Zusammenfassungen erstellen..."
        yield {"type": "task_start", "task": "summarize", "message": "Erstelle Zusammenfassungen..."}
        
        try:
            # Alte Einträge aus ALLEN Conversations laden
            old_entries = unwrap_mcp_result(call_tool("memory_all_recent", {
                "limit": 100
            }, timeout=30))
            
            entries = old_entries.get("entries", []) if isinstance(old_entries, dict) else []
            
            if len(entries) < 10:
                yield {"type": "task_progress", "message": "Zu wenig Einträge für Zusammenfassung", "sub_progress": 100}
                return
            
            yield {"type": "task_progress", "message": f"Fasse {len(entries)} Einträge zusammen...", "sub_progress": 30}
            
            # KI Zusammenfassung erstellen lassen
            try:
                summary = await self._ai_create_summary(entries[:50])
            except Exception as e:
                log_error(f"AI summary failed: {e}")
                summary = None
                self.stats.errors.append(f"Summary: {e}")
            
            if summary:
                # Summary speichern
                call_tool("memory_fact_save", {
                    "conversation_id": "system",
                    "key": f"conversation_summary_{datetime.now().strftime('%Y%m%d')}",
                    "value": summary
                }, timeout=10)
                self.stats.summaries_created += 1
                
                yield {
                    "type": "task_progress",
                    "message": f"Zusammenfassung erstellt ({len(summary)} Zeichen)",
                    "sub_progress": 100
                }
            else:
                yield {"type": "task_progress", "message": "Keine Zusammenfassung möglich", "sub_progress": 100}
            
        except Exception as e:
            yield {"type": "task_error", "task": "summarize", "message": str(e)}
    
    async def _ai_create_summary(self, entries: List[Dict]) -> Optional[str]:
        """Lässt KI eine Zusammenfassung erstellen."""
        if not entries:
            return None
        
        entries_text = "\n".join([
            e.get('content', '')[:200]
            for e in entries
        ])
        
        prompt = f"""Erstelle eine KURZE Zusammenfassung dieser Konversationen.
Fokussiere auf: Wichtige Fakten über den User, besprochene Themen, getroffene Entscheidungen.

Konversationen:
{entries_text}

Zusammenfassung (max 500 Zeichen):"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={
                        "model": THINKING_MODEL,
                        "prompt": prompt,
                        "stream": False
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("response", "")[:500]
            
            return None
            
        except Exception as e:
            log_error(f"[Maintenance] AI summary failed: {e}")
            return None
    
    async def _optimize_graph(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Optimiert den Knowledge Graph."""
        self.current_task = "Graph optimieren..."
        yield {"type": "task_start", "task": "graph", "message": "Optimiere Knowledge Graph..."}
        
        try:
            # Graph-Statistiken mit dediziertem Tool
            graph_stats = unwrap_mcp_result(call_tool("memory_graph_stats", {}, timeout=10))
            
            nodes = graph_stats.get("nodes", 0) if isinstance(graph_stats, dict) else 0
            edges = graph_stats.get("edges", 0) if isinstance(graph_stats, dict) else 0
            
            yield {
                "type": "task_progress",
                "message": f"Graph: {nodes} Nodes, {edges} Edges",
                "sub_progress": 20
            }
            
            # 1. Find and merge duplicate nodes
            try:
                duplicates = unwrap_mcp_result(call_tool("graph_find_duplicate_nodes", {}, timeout=10))
                
                if isinstance(duplicates, dict):
                    dup_groups = duplicates.get("duplicate_groups", [])
                    
                    yield {
                        "type": "task_progress",
                        "message": f"Fand {len(dup_groups)} Duplikat-Gruppen",
                        "sub_progress": 40
                    }
                    
                    for group in dup_groups:
                        if self._cancel_requested:
                            return
                        
                        node_ids = group.get("node_ids", [])
                        if len(node_ids) >= 2:
                            # Merge nodes
                            unwrap_mcp_result(call_tool("graph_merge_nodes", {
                                "node_ids": node_ids
                            }, timeout=10))
            
            except Exception as e:
                log_error(f"Graph duplicate merge failed: {e}")
                self.stats.errors.append(f"Graph merge: {e}")
            
            # 2. Delete orphaned nodes
            try:
                orphans = unwrap_mcp_result(call_tool("graph_delete_orphan_nodes", {}, timeout=10))
                
                if isinstance(orphans, dict):
                    deleted = orphans.get("deleted", 0)
                    
                    yield {
                        "type": "task_progress",
                        "message": f"{deleted} verwaiste Nodes entfernt",
                        "sub_progress": 70
                    }
            
            except Exception as e:
                log_error(f"Orphan deletion failed: {e}")
                self.stats.errors.append(f"Orphan delete: {e}")
            
            # 3. Prune weak edges
            try:
                pruned = unwrap_mcp_result(call_tool("graph_prune_weak_edges", {
                    "threshold": 0.3
                }, timeout=10))
                
                if isinstance(pruned, dict):
                    count = pruned.get("pruned", 0)
                    self.stats.edges_pruned = count
                    
                    yield {
                        "type": "task_progress",
                        "message": f"{count} schwache Edges entfernt",
                        "sub_progress": 90
                    }
            
            except Exception as e:
                log_error(f"Edge pruning failed: {e}")
                self.stats.errors.append(f"Edge prune: {e}")
            
            # Final stats
            final_stats = unwrap_mcp_result(call_tool("memory_graph_stats", {}, timeout=10))
            final_nodes = final_stats.get("nodes", 0) if isinstance(final_stats, dict) else 0
            final_edges = final_stats.get("edges", 0) if isinstance(final_stats, dict) else 0
            
            yield {
                "type": "task_progress",
                "message": f"Optimiert: {nodes}→{final_nodes} Nodes, {edges}→{final_edges} Edges",
                "sub_progress": 100
            }
            
        except Exception as e:
            yield {"type": "task_error", "task": "graph", "message": str(e)}


# Singleton
_worker_instance: Optional[MaintenanceWorker] = None

def get_worker() -> MaintenanceWorker:
    """Gibt die Worker-Singleton-Instanz zurück."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = MaintenanceWorker()
    return _worker_instance
