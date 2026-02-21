"""
Tool Intelligence - Auto-Search Module

Searches for past solutions in Workspace and Archive.
"""

import threading
import sqlite3
import json
from typing import List, Dict, Any
from utils.logger import log_info, log_warn, log_error, log_debug


class AutoSearch:
    """
    Dual-source search for past solutions.
    Searches both Workspace Events and Archive.
    """
    
    def __init__(self, archive_manager):
        self.archive_manager = archive_manager
        # User specified path: /app/memory_data/memory.db
        self.workspace_db_path = '/app/memory_data/memory.db'
    
    def search_past_solutions(self, tool_name: str, error_msg: str) -> str:
        """
        Search for past solutions to similar tool errors.
        
        Args:
            tool_name: Name of the failed tool
            error_msg: Error message from tool
            
        Returns:
            Formatted string with past solutions, or empty string
        """
        log_info(f"[AutoSearch] Searching for tool:{tool_name} error:{error_msg[:50]}...")
        
        try:
            # Extract key error terms
            error_summary = error_msg[:50].lower() if error_msg else "unknown"
            query = f"tool:{tool_name} error {error_summary}"
            
            # Parallel search in both sources
            archive_results = []
            workspace_results = []
            archive_complete = threading.Event()
            workspace_complete = threading.Event()
            
            def search_archive():
                nonlocal archive_results
                try:
                    if self.archive_manager:
                        results = self.archive_manager.search_archive(query, limit=2)
                        if results:
                            # Normalize archive results if needed
                            processed = []
                            for r in results:
                                # Start with existing dict or convert object
                                if isinstance(r, dict):
                                    item = r
                                else:
                                    item = {'content': getattr(r, 'page_content', str(r))}
                                item['source'] = 'archive'
                                processed.append(item)
                            archive_results = processed
                            log_info(f"[AutoSearch-Archive] Found {len(results)} results")
                except Exception as e:
                    log_debug(f"[AutoSearch-Archive] Failed: {e}")
                finally:
                    archive_complete.set()
            
            def search_workspace():
                nonlocal workspace_results
                try:
                    results = self._search_workspace_events(tool_name, error_msg)
                    if results:
                        workspace_results = results
                        log_info(f"[AutoSearch-Workspace] Found {len(results)} results")
                except Exception as e:
                    log_debug(f"[AutoSearch-Workspace] Failed: {e}")
                finally:
                    workspace_complete.set()
            
            # Run both searches in parallel
            archive_thread = threading.Thread(target=search_archive, daemon=True)
            workspace_thread = threading.Thread(target=search_workspace, daemon=True)
            
            archive_thread.start()
            workspace_thread.start()
            
            # Wait for both (max 2s each)
            archive_complete.wait(timeout=2.0)
            workspace_complete.wait(timeout=2.0)
            
            # Merge results (workspace first - more recent)
            all_results = workspace_results + archive_results
            
            if not all_results:
                log_info(f"[AutoSearch] No results found for: {tool_name}")
                return ""
            
            # Format results
            formatted = self._format_results(all_results)
            log_info(f"[AutoSearch] Found {len(all_results)} solutions for {tool_name}")
            
            return formatted
            
        except Exception as e:
            log_error(f"[AutoSearch] Exception: {e}")
            return ""
    
    def _search_workspace_events(self, tool_name: str, error_msg: str) -> List[Dict]:
        """Search workspace_events table for relevant entries."""
        results = []
        
        try:
            conn = sqlite3.connect(self.workspace_db_path, timeout=1.0)
            conn.row_factory = sqlite3.Row
            
            # Search pattern
            search_pattern = f"%{tool_name}%{error_msg[:30]}%"
            
            # Note: User prompt used 'workspace_events', but some code (FastLane) might use 'workspace_entries'.
            # Orchestrator raw used 'workspace_events' (line 597).
            # We stick to 'workspace_events' as per user spec and orchestrator.py
            cursor = conn.execute("""
                SELECT id, event_data, event_type, created_at 
                FROM workspace_events 
                WHERE event_data LIKE ? 
                ORDER BY created_at DESC 
                LIMIT 3
            """, (search_pattern,))
            
            for row in cursor:
                # Parse JSON event_data
                try:
                    event_json = json.loads(row['event_data'])
                    content_text = event_json.get('content', row['event_data'])
                except:
                    content_text = row['event_data']
                
                results.append({
                    'id': f"workspace_{row['id']}",
                    'content': content_text,
                    'source': 'workspace',
                    'type': row['event_type']
                })
            
            conn.close()
            
        except Exception as e:
            log_debug(f"[AutoSearch-Workspace] DB error: {e}")
        
        return results
    
    def _format_results(self, results: List[Dict]) -> str:
        """Format search results for display."""
        formatted = "\n\n💡 **Mögliche Lösungen (Workspace + Archiv):**\n"
        
        for idx, res in enumerate(results[:4], 1):
            source = res.get('source', 'archive')
            res_content = str(res.get('content') or '')[:200]
            
            source_emoji = "📝" if source == 'workspace' else "🗂️"
            formatted += f"  {idx}. {source_emoji} [{source}] {res_content}...\n"
        
        return formatted
