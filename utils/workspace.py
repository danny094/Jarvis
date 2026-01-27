# utils/workspace.py
"""
Workspace Manager für Chunked Processing Sessions.

Verwaltet temporäre Arbeitsverzeichnisse für lange Inputs die
in Chunks verarbeitet werden müssen.

Struktur:
/tmp/trion/jarvis/workspace/{conversation_id}/
├── meta.json       # Session-Metadaten, Locking, Status
├── input.txt       # Original-Input (für Debug)
├── chunks/
│   ├── 001.json    # Chunk + Summary + Status
│   ├── 002.json
│   └── ...
└── final.json      # Aggregierte Meta-Summary
"""

import os
import json
import time
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

from utils.logger import log_debug, log_error, log_info, log_warn


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

WORKSPACE_BASE = Path(os.getenv("WORKSPACE_BASE", "/tmp/trion/jarvis/workspace"))

WORKSPACE_CONFIG = {
    "max_age_hours": 24,        # Sessions älter als 24h → löschen
    "max_total_size_mb": 500,   # Wenn > 500MB → älteste löschen
    "max_sessions": 50,         # Max 50 Sessions gleichzeitig
    "lock_timeout_seconds": 300, # Lock expires nach 5 Minuten
}


# ═══════════════════════════════════════════════════════════════
# ENUMS & DATA CLASSES
# ═══════════════════════════════════════════════════════════════

class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class ChunkStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ChunkData:
    """Daten für einen einzelnen Chunk."""
    chunk_num: int
    status: str = ChunkStatus.PENDING
    tokens: int = 0
    content: str = ""
    summary: str = ""
    needs_sequential: bool = False
    thinking_result: Optional[Dict] = None
    retry_count: int = 0
    last_error: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ChunkData":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionMeta:
    """Metadaten für eine Workspace-Session."""
    conversation_id: str
    status: str = SessionStatus.ACTIVE
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    locked_by: Optional[str] = None
    locked_at: Optional[str] = None
    total_tokens: int = 0
    total_chunks: int = 0
    processed_chunks: int = 0
    failed_chunks: int = 0
    original_input_length: int = 0
    config: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict) -> "SessionMeta":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ═══════════════════════════════════════════════════════════════
# WORKSPACE MANAGER
# ═══════════════════════════════════════════════════════════════

class WorkspaceManager:
    """
    Verwaltet Workspace-Sessions für chunked processing.
    
    Thread-safe durch File-Locking.
    """
    
    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = base_path or WORKSPACE_BASE
        self._ensure_base_exists()
    
    def _ensure_base_exists(self):
        """Stellt sicher dass der Base-Ordner existiert."""
        self.base_path.mkdir(parents=True, exist_ok=True)
        log_debug(f"[Workspace] Base path ready: {self.base_path}")
    
    def _get_session_path(self, conversation_id: str) -> Path:
        """Gibt den Pfad für eine Session zurück."""
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in conversation_id)
        return self.base_path / safe_id
    
    def _now_iso(self) -> str:
        """Aktueller Timestamp in ISO Format."""
        return datetime.utcnow().isoformat() + "Z"
    
    # ═══════════════════════════════════════════════════════════
    # SESSION MANAGEMENT
    # ═══════════════════════════════════════════════════════════
    
    def create_session(
        self, 
        conversation_id: str, 
        original_input: str = "",
        config: Optional[Dict] = None
    ) -> SessionMeta:
        """
        Erstellt eine neue Workspace-Session.
        """
        session_path = self._get_session_path(conversation_id)
        
        if session_path.exists():
            existing = self.load_session_meta(conversation_id)
            if existing and existing.status == SessionStatus.ACTIVE:
                if self._is_lock_expired(existing):
                    log_warn(f"[Workspace] Abandoned session found: {conversation_id}")
                    existing.status = SessionStatus.ABANDONED
                    self._save_meta(conversation_id, existing)
                else:
                    log_warn(f"[Workspace] Active session exists: {conversation_id}")
                    return existing
        
        session_path.mkdir(parents=True, exist_ok=True)
        (session_path / "chunks").mkdir(exist_ok=True)
        
        meta = SessionMeta(
            conversation_id=conversation_id,
            status=SessionStatus.ACTIVE,
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            original_input_length=len(original_input),
            config=config or {}
        )
        
        if original_input:
            input_path = session_path / "input.txt"
            input_path.write_text(original_input, encoding="utf-8")
        
        self._save_meta(conversation_id, meta)
        
        log_info(f"[Workspace] Session created: {conversation_id}")
        return meta
    
    def load_session_meta(self, conversation_id: str) -> Optional[SessionMeta]:
        """Lädt die Metadaten einer Session."""
        session_path = self._get_session_path(conversation_id)
        meta_path = session_path / "meta.json"
        
        if not meta_path.exists():
            return None
        
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return SessionMeta.from_dict(data)
        except Exception as e:
            log_error(f"[Workspace] Failed to load meta: {e}")
            return None
    
    def _save_meta(self, conversation_id: str, meta: SessionMeta):
        """Speichert die Metadaten einer Session."""
        session_path = self._get_session_path(conversation_id)
        meta_path = session_path / "meta.json"
        
        meta.updated_at = self._now_iso()
        meta_path.write_text(
            json.dumps(meta.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def session_exists(self, conversation_id: str) -> bool:
        """Prüft ob eine Session existiert."""
        session_path = self._get_session_path(conversation_id)
        return (session_path / "meta.json").exists()
    
    def update_session_status(self, conversation_id: str, status: SessionStatus):
        """Aktualisiert den Status einer Session."""
        meta = self.load_session_meta(conversation_id)
        if meta:
            meta.status = status
            self._save_meta(conversation_id, meta)
            log_info(f"[Workspace] Session {conversation_id} status → {status}")
    
    # ═══════════════════════════════════════════════════════════
    # LOCKING
    # ═══════════════════════════════════════════════════════════
    
    def acquire_lock(self, conversation_id: str, lock_id: str) -> bool:
        """Versucht ein Lock auf die Session zu bekommen."""
        meta = self.load_session_meta(conversation_id)
        if not meta:
            return False
        
        if meta.locked_by and not self._is_lock_expired(meta):
            if meta.locked_by != lock_id:
                log_warn(f"[Workspace] Session locked by: {meta.locked_by}")
                return False
        
        meta.locked_by = lock_id
        meta.locked_at = self._now_iso()
        self._save_meta(conversation_id, meta)
        
        log_debug(f"[Workspace] Lock acquired: {conversation_id} by {lock_id}")
        return True
    
    def release_lock(self, conversation_id: str, lock_id: str) -> bool:
        """Gibt ein Lock frei."""
        meta = self.load_session_meta(conversation_id)
        if not meta:
            return False
        
        if meta.locked_by != lock_id:
            log_warn(f"[Workspace] Cannot release lock - wrong lock_id")
            return False
        
        meta.locked_by = None
        meta.locked_at = None
        self._save_meta(conversation_id, meta)
        
        log_debug(f"[Workspace] Lock released: {conversation_id}")
        return True
    
    def _is_lock_expired(self, meta: SessionMeta) -> bool:
        """Prüft ob ein Lock abgelaufen ist."""
        if not meta.locked_at:
            return True
        
        try:
            locked_time = datetime.fromisoformat(meta.locked_at.replace("Z", "+00:00"))
            timeout = timedelta(seconds=WORKSPACE_CONFIG["lock_timeout_seconds"])
            return datetime.now(locked_time.tzinfo) > locked_time + timeout
        except:
            return True
    
    # ═══════════════════════════════════════════════════════════
    # CHUNK MANAGEMENT
    # ═══════════════════════════════════════════════════════════
    
    def save_chunk(
        self, 
        conversation_id: str, 
        chunk_num: int, 
        data: ChunkData
    ) -> bool:
        """Speichert einen Chunk."""
        session_path = self._get_session_path(conversation_id)
        chunks_path = session_path / "chunks"
        
        if not chunks_path.exists():
            log_error(f"[Workspace] Chunks dir not found: {conversation_id}")
            return False
        
        chunk_file = chunks_path / f"{chunk_num:03d}.json"
        
        if not data.created_at:
            data.created_at = self._now_iso()
        if data.status == ChunkStatus.DONE and not data.completed_at:
            data.completed_at = self._now_iso()
        
        chunk_file.write_text(
            json.dumps(data.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        meta = self.load_session_meta(conversation_id)
        if meta:
            meta.total_chunks = max(meta.total_chunks, chunk_num)
            if data.status == ChunkStatus.DONE:
                meta.processed_chunks = self._count_done_chunks(conversation_id)
            elif data.status == ChunkStatus.FAILED:
                meta.failed_chunks = self._count_failed_chunks(conversation_id)
            self._save_meta(conversation_id, meta)
        
        log_debug(f"[Workspace] Chunk saved: {conversation_id}/{chunk_num:03d} ({data.status})")
        return True
    
    def load_chunk(self, conversation_id: str, chunk_num: int) -> Optional[ChunkData]:
        """Lädt einen einzelnen Chunk."""
        session_path = self._get_session_path(conversation_id)
        chunk_file = session_path / "chunks" / f"{chunk_num:03d}.json"
        
        if not chunk_file.exists():
            return None
        
        try:
            data = json.loads(chunk_file.read_text(encoding="utf-8"))
            return ChunkData.from_dict(data)
        except Exception as e:
            log_error(f"[Workspace] Failed to load chunk: {e}")
            return None
    
    def load_all_chunks(self, conversation_id: str) -> List[ChunkData]:
        """Lädt alle Chunks einer Session."""
        session_path = self._get_session_path(conversation_id)
        chunks_path = session_path / "chunks"
        
        if not chunks_path.exists():
            return []
        
        chunks = []
        for chunk_file in sorted(chunks_path.glob("*.json")):
            try:
                data = json.loads(chunk_file.read_text(encoding="utf-8"))
                chunks.append(ChunkData.from_dict(data))
            except Exception as e:
                log_error(f"[Workspace] Failed to load chunk {chunk_file}: {e}")
        
        return chunks
    
    def get_pending_chunks(self, conversation_id: str) -> List[int]:
        """Gibt Liste der noch nicht verarbeiteten Chunk-Nummern."""
        chunks = self.load_all_chunks(conversation_id)
        return [
            c.chunk_num for c in chunks 
            if c.status in (ChunkStatus.PENDING, ChunkStatus.FAILED)
            and c.retry_count < 3
        ]
    
    def _count_done_chunks(self, conversation_id: str) -> int:
        """Zählt fertige Chunks."""
        chunks = self.load_all_chunks(conversation_id)
        return sum(1 for c in chunks if c.status == ChunkStatus.DONE)
    
    def _count_failed_chunks(self, conversation_id: str) -> int:
        """Zählt fehlgeschlagene Chunks."""
        chunks = self.load_all_chunks(conversation_id)
        return sum(1 for c in chunks if c.status == ChunkStatus.FAILED)
    
    # ═══════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ═══════════════════════════════════════════════════════════
    
    def save_final_summary(
        self, 
        conversation_id: str, 
        summary: str,
        aggregated_data: Optional[Dict] = None
    ) -> bool:
        """Speichert die finale aggregierte Summary."""
        session_path = self._get_session_path(conversation_id)
        final_path = session_path / "final.json"
        
        final_data = {
            "summary": summary,
            "created_at": self._now_iso(),
            "aggregated_data": aggregated_data or {},
            "chunks_processed": self._count_done_chunks(conversation_id),
            "chunks_failed": self._count_failed_chunks(conversation_id),
        }
        
        final_path.write_text(
            json.dumps(final_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        self.update_session_status(conversation_id, SessionStatus.COMPLETED)
        
        log_info(f"[Workspace] Final summary saved: {conversation_id}")
        return True
    
    def load_final_summary(self, conversation_id: str) -> Optional[Dict]:
        """Lädt die finale Summary."""
        session_path = self._get_session_path(conversation_id)
        final_path = session_path / "final.json"
        
        if not final_path.exists():
            return None
        
        try:
            return json.loads(final_path.read_text(encoding="utf-8"))
        except Exception as e:
            log_error(f"[Workspace] Failed to load final summary: {e}")
            return None
    
    # ═══════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════
    
    def cleanup(
        self, 
        max_age_hours: Optional[int] = None,
        max_sessions: Optional[int] = None,
        force: bool = False
    ) -> int:
        """Räumt alte/überzählige Sessions auf."""
        max_age = max_age_hours or WORKSPACE_CONFIG["max_age_hours"]
        max_sess = max_sessions or WORKSPACE_CONFIG["max_sessions"]
        
        deleted = 0
        cutoff = datetime.utcnow() - timedelta(hours=max_age)
        
        sessions = []
        for session_dir in self.base_path.iterdir():
            if not session_dir.is_dir():
                continue
            
            meta = self.load_session_meta(session_dir.name)
            if not meta:
                shutil.rmtree(session_dir, ignore_errors=True)
                deleted += 1
                continue
            
            sessions.append((session_dir, meta))
        
        sessions.sort(
            key=lambda x: x[1].updated_at or x[1].created_at or "",
            reverse=True
        )
        
        for session_dir, meta in sessions:
            try:
                created = datetime.fromisoformat(
                    (meta.created_at or "").replace("Z", "+00:00")
                )
                if created.replace(tzinfo=None) < cutoff:
                    if force or meta.status != SessionStatus.ACTIVE:
                        shutil.rmtree(session_dir, ignore_errors=True)
                        deleted += 1
                        log_info(f"[Workspace] Deleted old session: {meta.conversation_id}")
            except:
                pass
        
        remaining = [s for s in self.base_path.iterdir() if s.is_dir()]
        if len(remaining) > max_sess:
            remaining_with_meta = []
            for d in remaining:
                m = self.load_session_meta(d.name)
                if m:
                    remaining_with_meta.append((d, m))
            
            remaining_with_meta.sort(
                key=lambda x: x[1].updated_at or "",
                reverse=True
            )
            
            for session_dir, meta in remaining_with_meta[max_sess:]:
                if force or meta.status != SessionStatus.ACTIVE:
                    shutil.rmtree(session_dir, ignore_errors=True)
                    deleted += 1
                    log_info(f"[Workspace] Deleted excess session: {meta.conversation_id}")
        
        if deleted > 0:
            log_info(f"[Workspace] Cleanup complete: {deleted} sessions deleted")
        
        return deleted
    
    def get_total_size_mb(self) -> float:
        """Berechnet die Gesamtgröße aller Sessions in MB."""
        total = 0
        for session_dir in self.base_path.iterdir():
            if session_dir.is_dir():
                for f in session_dir.rglob("*"):
                    if f.is_file():
                        total += f.stat().st_size
        return total / (1024 * 1024)
    
    def list_sessions(self) -> List[Dict]:
        """Listet alle Sessions mit Basic-Info."""
        sessions = []
        for session_dir in self.base_path.iterdir():
            if not session_dir.is_dir():
                continue
            
            meta = self.load_session_meta(session_dir.name)
            if meta:
                sessions.append({
                    "conversation_id": meta.conversation_id,
                    "status": meta.status,
                    "created_at": meta.created_at,
                    "total_chunks": meta.total_chunks,
                    "processed_chunks": meta.processed_chunks,
                })
        
        return sessions


# ═══════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════

_workspace_manager: Optional[WorkspaceManager] = None

def get_workspace_manager() -> WorkspaceManager:
    """Gibt die Singleton-Instanz des WorkspaceManagers zurück."""
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = WorkspaceManager()
    return _workspace_manager


# ═══════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def quick_session(conversation_id: str, original_input: str = "") -> SessionMeta:
    """Schneller Weg eine Session zu erstellen."""
    return get_workspace_manager().create_session(conversation_id, original_input)

def quick_chunk_save(
    conversation_id: str, 
    chunk_num: int, 
    content: str, 
    tokens: int,
    status: str = ChunkStatus.PENDING
) -> bool:
    """Schneller Weg einen Chunk zu speichern."""
    chunk = ChunkData(
        chunk_num=chunk_num,
        content=content,
        tokens=tokens,
        status=status
    )
    return get_workspace_manager().save_chunk(conversation_id, chunk_num, chunk)
