"""
PipelineOrchestrator: Manages the 3-Layer execution pipeline

Responsibilities:
- Orchestrate Thinking -> Control -> Output layers
- Handle streaming logic
- Manage chunking for large documents
- Intent confirmation integration

Created by: Claude 2 (Parallel Development)
Date: 2026-02-05
Part of: CoreBridge Refactoring Phase 1
"""

import asyncio
import json
import os
import time
import hashlib
import threading
import re
import sqlite3
import uuid
from datetime import datetime
from typing import AsyncGenerator, Tuple, Dict, Any, Optional, List, Callable

from core.models import CoreChatRequest, CoreChatResponse
from core.context_manager import ContextManager, ContextResult
from core.layers.thinking import ThinkingLayer
from core.layers.control import ControlLayer
from core.layers.output import OutputLayer
from core.tool_selector import ToolSelector
from config import (
    OLLAMA_BASE,
    ENABLE_CONTROL_LAYER,
    SKIP_CONTROL_ON_LOW_RISK,
    ENABLE_CHUNKING,
    CHUNKING_THRESHOLD,
)
from utils.logger import log_info, log_warn, log_error, log_debug
from mcp.client import (
    autosave_assistant,
    call_tool,
)
from mcp.hub import get_hub
from core.sequential_registry import get_registry
from core.lifecycle.task import TaskLifecycleManager
from core.tools.tool_result import ToolResult
from core.lifecycle.archive import get_archive_manager
from core.master import get_master_orchestrator
from core.tool_intelligence import ToolIntelligenceManager

# Intent System (optional)
try:
    from core.intent_models import SkillCreationIntent, IntentState, IntentOrigin
    from core.intent_store import get_intent_store
    INTENT_SYSTEM_AVAILABLE = True
except ImportError:
    INTENT_SYSTEM_AVAILABLE = False
    log_warn("[Orchestrator] Intent System not available")

# CIM Policy Engine (optional)
try:
    from intelligence_modules.cim_policy.cim_policy_engine import (
        process_cim, ActionType, CIMDecision
    )
    CIM_AVAILABLE = True
except ImportError:
    CIM_AVAILABLE = False


# ═══════════════════════════════════════════════════════════
# PLAN CACHE — RAM-basierter TTL-Cache für ThinkingLayer + Sequential
# ═══════════════════════════════════════════════════════════

class _PlanCache:
    """
    Einfacher In-Memory TTL-Cache für LLM-Pläne.
    Verhindert doppelte LLM-Calls für gleiche/ähnliche Anfragen.
    Thread-safe via Lock.
    """

    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, tuple] = {}  # key → (timestamp, plan_dict)
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def _key(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()

    def get(self, text: str) -> Optional[Dict]:
        key = self._key(text)
        with self._lock:
            if key in self._cache:
                ts, plan = self._cache[key]
                if time.time() - ts < self._ttl:
                    return plan
                del self._cache[key]
        return None

    def set(self, text: str, plan: Dict):
        key = self._key(text)
        with self._lock:
            self._cache[key] = (time.time(), plan)
            # Bereinige alte Einträge (max. 200 Slots)
            if len(self._cache) > 200:
                cutoff = time.time() - self._ttl
                self._cache = {
                    k: v for k, v in self._cache.items() if v[0] > cutoff
                }


class _SqlitePlanCache:
    """
    SQLite-backed TTL cache for cross-worker cache sharing.
    Enables optional multi-process cache coherence via shared DB file.
    """

    def __init__(
        self,
        ttl_seconds: int = 300,
        *,
        db_path: str = "/tmp/trion_plan_cache.sqlite",
        namespace: str = "default",
        max_entries: int = 1000,
    ):
        self._ttl = ttl_seconds
        self._db_path = db_path
        self._namespace = namespace
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_cache (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(namespace, cache_key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plan_cache_ttl ON plan_cache(namespace, created_at)"
            )

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()

    def get(self, text: str) -> Optional[Dict]:
        key = self._key(text)
        now = time.time()
        cutoff = now - self._ttl
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    "DELETE FROM plan_cache WHERE namespace=? AND created_at < ?",
                    (self._namespace, cutoff),
                )
                row = conn.execute(
                    """
                    SELECT payload
                    FROM plan_cache
                    WHERE namespace=? AND cache_key=? AND created_at >= ?
                    """,
                    (self._namespace, key, cutoff),
                ).fetchone()
                if not row:
                    return None
                return json.loads(row["payload"])
        except Exception as e:
            log_warn(f"[PlanCache:sqlite] get failed namespace={self._namespace}: {e}")
            return None

    def set(self, text: str, plan: Dict):
        key = self._key(text)
        now = time.time()
        payload = json.dumps(plan, ensure_ascii=False, default=str)
        cutoff = now - self._ttl
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO plan_cache(namespace, cache_key, created_at, payload)
                    VALUES(?,?,?,?)
                    ON CONFLICT(namespace, cache_key)
                    DO UPDATE SET created_at=excluded.created_at, payload=excluded.payload
                    """,
                    (self._namespace, key, now, payload),
                )
                conn.execute(
                    "DELETE FROM plan_cache WHERE namespace=? AND created_at < ?",
                    (self._namespace, cutoff),
                )
                count_row = conn.execute(
                    "SELECT COUNT(*) AS n FROM plan_cache WHERE namespace=?",
                    (self._namespace,),
                ).fetchone()
                count = int(count_row["n"]) if count_row else 0
                if count > self._max_entries:
                    drop = count - self._max_entries
                    conn.execute(
                        """
                        DELETE FROM plan_cache
                        WHERE rowid IN (
                            SELECT rowid FROM plan_cache
                            WHERE namespace=?
                            ORDER BY created_at ASC
                            LIMIT ?
                        )
                        """,
                        (self._namespace, drop),
                    )
        except Exception as e:
            log_warn(f"[PlanCache:sqlite] set failed namespace={self._namespace}: {e}")


def _make_plan_cache(ttl_seconds: int, namespace: str):
    backend = os.getenv("TRION_PLAN_CACHE_BACKEND", "sqlite").strip().lower()
    if backend in {"sqlite", "shared", "sqlite_shared"}:
        db_path = os.getenv("TRION_PLAN_CACHE_DB", "/tmp/trion_plan_cache.sqlite")
        try:
            log_info(f"[PlanCache] backend=sqlite namespace={namespace} db={db_path}")
            return _SqlitePlanCache(ttl_seconds=ttl_seconds, db_path=db_path, namespace=namespace)
        except Exception as e:
            log_warn(f"[PlanCache] sqlite backend init failed, fallback=memory: {e}")
    return _PlanCache(ttl_seconds=ttl_seconds)


# Module-level Cache-Instanzen (leben bis Container neugestartet wird)
_thinking_plan_cache = _make_plan_cache(ttl_seconds=300, namespace="thinking_plan")      # 5 min
_sequential_result_cache = _make_plan_cache(ttl_seconds=600, namespace="sequential_result")  # 10 min


class _ArchiveEmbeddingJobQueue:
    """
    Durable local job queue for archive embedding post-processing.
    Uses SQLite so pending jobs survive process restarts.
    """

    def __init__(
        self,
        *,
        db_path: str = "/tmp/trion_posttask_jobs.sqlite",
        poll_interval_s: float = 0.8,
        retry_base_s: float = 1.0,
        retry_max_s: float = 60.0,
    ):
        self._db_path = db_path
        self._poll_interval_s = max(0.1, float(poll_interval_s))
        self._retry_base_s = max(0.0, float(retry_base_s))
        self._retry_max_s = max(self._retry_base_s, float(retry_max_s))
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._notify_event = threading.Event()
        self._start_lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._processor: Optional[Callable[[], int]] = None
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS archive_embedding_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_archive_embedding_jobs_pending "
                "ON archive_embedding_jobs(status, available_at, id)"
            )

    def ensure_worker_running(self, processor: Callable[[], int]):
        self.set_processor(processor)
        if self._thread and self._thread.is_alive():
            return
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="archive-embedding-worker",
                daemon=True,
            )
            self._thread.start()
            log_info("[PostTaskQueue] worker started")

    def set_processor(self, processor: Callable[[], int]):
        if callable(processor):
            self._processor = processor

    def enqueue(self) -> int:
        now = time.time()
        with self._db_lock, self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO archive_embedding_jobs(status, attempts, available_at, created_at, updated_at)
                VALUES('pending', 0, ?, ?, ?)
                """,
                (now, now, now),
            )
            job_id = int(cur.lastrowid)
        self._notify_event.set()
        return job_id

    def _claim_next(self) -> Optional[sqlite3.Row]:
        now = time.time()
        with self._db_lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, attempts
                FROM archive_embedding_jobs
                WHERE status='pending' AND available_at <= ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            conn.execute(
                "UPDATE archive_embedding_jobs SET status='running', updated_at=? WHERE id=?",
                (now, int(row["id"])),
            )
            conn.execute("COMMIT")
            return row

    def _mark_done(self, job_id: int):
        with self._db_lock, self._conn() as conn:
            conn.execute("DELETE FROM archive_embedding_jobs WHERE id=?", (job_id,))

    def _mark_retry(self, job_id: int, attempts: int, error: str):
        backoff = min(self._retry_max_s, self._retry_base_s * (2 ** max(0, attempts)))
        next_at = time.time() + backoff
        with self._db_lock, self._conn() as conn:
            conn.execute(
                """
                UPDATE archive_embedding_jobs
                SET status='pending',
                    attempts=?,
                    available_at=?,
                    updated_at=?,
                    last_error=?
                WHERE id=?
                """,
                (attempts, next_at, time.time(), error[:1000], job_id),
            )

    def pending_count(self) -> int:
        with self._db_lock, self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM archive_embedding_jobs WHERE status='pending'"
            ).fetchone()
            return int(row["n"]) if row else 0

    def stats(self) -> Dict[str, int]:
        with self._db_lock, self._conn() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM archive_embedding_jobs WHERE status='pending'"
            ).fetchone()
            running = conn.execute(
                "SELECT COUNT(*) AS n FROM archive_embedding_jobs WHERE status='running'"
            ).fetchone()
            total = conn.execute("SELECT COUNT(*) AS n FROM archive_embedding_jobs").fetchone()
            return {
                "pending": int(pending["n"]) if pending else 0,
                "running": int(running["n"]) if running else 0,
                "total": int(total["n"]) if total else 0,
            }

    def run_once(self) -> bool:
        if not callable(self._processor):
            return False
        row = self._claim_next()
        if not row:
            return False

        job_id = int(row["id"])
        attempts = int(row["attempts"])
        try:
            processed = int(self._processor() or 0)
            if processed > 0:
                log_info(f"[PostTaskQueue] processed archive embeddings: {processed} (job_id={job_id})")
            self._mark_done(job_id)
        except Exception as e:
            next_attempt = attempts + 1
            self._mark_retry(job_id, next_attempt, str(e))
            log_error(
                f"[PostTaskQueue] job failed (job_id={job_id}, attempts={next_attempt}) "
                f"error={e}"
            )
        return True

    def _worker_loop(self):
        while not self._stop_event.is_set():
            worked = self.run_once()
            if worked:
                continue
            self._notify_event.wait(self._poll_interval_s)
            self._notify_event.clear()

    def stop(self):
        self._stop_event.set()
        self._notify_event.set()


_archive_embedding_queue_lock = threading.Lock()
_archive_embedding_queue: Optional[_ArchiveEmbeddingJobQueue] = None


def _get_archive_embedding_queue() -> _ArchiveEmbeddingJobQueue:
    global _archive_embedding_queue
    with _archive_embedding_queue_lock:
        if _archive_embedding_queue is None:
            db_path = os.getenv("TRION_POSTTASK_QUEUE_DB", "/tmp/trion_posttask_jobs.sqlite")
            poll = float(os.getenv("TRION_POSTTASK_QUEUE_POLL_S", "0.8") or "0.8")
            retry_base = float(os.getenv("TRION_POSTTASK_QUEUE_RETRY_BASE_S", "1.0") or "1.0")
            retry_max = float(os.getenv("TRION_POSTTASK_QUEUE_RETRY_MAX_S", "60.0") or "60.0")
            _archive_embedding_queue = _ArchiveEmbeddingJobQueue(
                db_path=db_path,
                poll_interval_s=poll,
                retry_base_s=retry_base,
                retry_max_s=retry_max,
            )
        return _archive_embedding_queue

# Patterns für frühes Hardware-Gate (vor Sequential Thinking)
_HARDWARE_GATE_PATTERNS = [
    "30b", "70b", "34b", "65b", "40b",
    "large model", "großes modell", "großes sprachmodell",
    "ollama pull", "modell laden", "modell aktivieren",
    "modell herunterladen", "model load", "model pull",
]



# Master Settings Helper
def get_master_settings():
    """Load Master Orchestrator settings"""
    import json
    import os
    
    settings_file = "/tmp/settings_master.json"
    default = {
        "enabled": True,
        "use_thinking_layer": False,
        "max_loops": 10,
        "completion_threshold": 2
    }
    
    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r') as f:
                return json.load(f)
        except Exception:
            return default
    return default

class PipelineOrchestrator:
    """
    Orchestrates the 3-Layer Pipeline:
    1. Thinking Layer (DeepSeek - Planning)
    2. Control Layer (Qwen - Verification)
    3. Output Layer (User Model - Generation)
    
    Delegates context retrieval to ContextManager.
    """
    
    def __init__(self, context_manager: ContextManager = None):
        """
        Initialize orchestrator with layers.
        
        Args:
            context_manager: Injected ContextManager (Dependency Injection)
                           If None, creates new instance
        """
        # Context Manager (from Claude 1's work)
        self.context = context_manager or ContextManager()
        
        # Layers
        self.thinking = ThinkingLayer()
        self.control = ControlLayer()
        self.output = OutputLayer()
        self.tool_selector = ToolSelector()
        self.registry = get_registry()
        self.lifecycle = TaskLifecycleManager()
        self.archive_manager = get_archive_manager()
        self.tool_intelligence = ToolIntelligenceManager(self.archive_manager)
        
        # Master Orchestrator (Phase 1 - Composition Pattern!)
        # Master is CLIENT of Pipeline (not parallel!)
        self.master = get_master_orchestrator(pipeline_orchestrator=self)
        
        # Inject MCP Hub for Sequential Thinking
        hub = get_hub()
        self.control.set_mcp_hub(hub)
        self.ollama_base = OLLAMA_BASE
        
        log_info("[PipelineOrchestrator] Initialized with 3 layers + ContextManager")

    _CONTROL_SKIP_BLOCK_TOOLS = {
        "create_skill",
        "autonomous_skill_task",
        "request_container",
        "exec_in_container",
        "home_write",
    }
    _CONTROL_SKIP_BLOCK_KEYWORDS = (
        "skill",
        "erstelle",
        "create",
        "programmier",
        "baue",
        "bau",
        "funktion",
        "neue funktion",
        "new function",
    )

    @classmethod
    def _extract_suggested_tool_names(cls, thinking_plan: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        raw_tools = (thinking_plan or {}).get("suggested_tools", []) or []
        for tool in raw_tools:
            if isinstance(tool, dict):
                name = str(tool.get("tool") or tool.get("name") or "").strip()
            else:
                name = str(tool).strip()
            if name:
                names.append(name)
        return names

    @staticmethod
    def _normalize_trace_id(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            raw = uuid.uuid4().hex[:12]
        safe = re.sub(r"[^a-zA-Z0-9:_-]", "", raw)[:64]
        return safe or uuid.uuid4().hex[:12]

    @staticmethod
    def _safe_str(value: Any, *, max_len: int = 3000) -> str:
        text = str(value or "").strip()
        if len(text) > max_len:
            return text[:max_len]
        return text

    def _sanitize_intent_thinking_plan_for_skill_task(self, thinking_plan: Any) -> Dict[str, Any]:
        """
        Build a compact, schema-safe subset for autonomous_skill_task.
        Prevents noisy / incompatible structures from crossing service boundaries.
        """
        if not isinstance(thinking_plan, dict):
            return {}

        safe: Dict[str, Any] = {}

        text_keys = (
            "intent",
            "reasoning",
            "reasoning_type",
            "hallucination_risk",
            "time_reference",
        )
        for key in text_keys:
            if key in thinking_plan:
                value = self._safe_str(thinking_plan.get(key), max_len=2000)
                if value:
                    safe[key] = value

        for key in ("needs_memory", "is_fact_query", "needs_sequential_thinking", "sequential_thinking_required"):
            if key in thinking_plan:
                safe[key] = bool(thinking_plan.get(key))

        if "sequential_complexity" in thinking_plan:
            try:
                complexity = int(thinking_plan.get("sequential_complexity", 0))
            except Exception:
                complexity = 0
            safe["sequential_complexity"] = max(0, min(10, complexity))

        raw_memory_keys = thinking_plan.get("memory_keys", [])
        memory_keys: List[str] = []
        if isinstance(raw_memory_keys, list):
            for item in raw_memory_keys:
                text = self._safe_str(item, max_len=80)
                if text:
                    memory_keys.append(text)
        if memory_keys:
            safe["memory_keys"] = memory_keys[:20]

        suggested_tools = self._extract_suggested_tool_names(
            {"suggested_tools": thinking_plan.get("suggested_tools", [])}
        )
        if suggested_tools:
            safe["suggested_tools"] = suggested_tools[:20]

        return safe

    def _should_skip_control_layer(self, user_text: str, thinking_plan: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Unified skip policy for sync + stream to avoid drift.

        Returns:
            (skip_control, reason)
        """
        if not ENABLE_CONTROL_LAYER:
            return True, "control_disabled"

        hallucination_risk = (thinking_plan or {}).get("hallucination_risk", "medium")
        if not (SKIP_CONTROL_ON_LOW_RISK and hallucination_risk == "low"):
            return False, "control_required"

        suggested_names = set(self._extract_suggested_tool_names(thinking_plan))
        sensitive_hits = sorted(suggested_names.intersection(self._CONTROL_SKIP_BLOCK_TOOLS))
        if sensitive_hits:
            return False, f"sensitive_tools:{','.join(sensitive_hits)}"

        user_lower = (user_text or "").lower()
        if any(kw in user_lower for kw in self._CONTROL_SKIP_BLOCK_KEYWORDS):
            return False, "creation_keywords"

        return True, "low_risk_skip"

    # ===============================================================
    # HARDWARE GATE EARLY CHECK
    # ===============================================================

    def _check_hardware_gate_early(self, user_text: str, thinking_plan: Dict) -> Optional[str]:
        """
        Schneller Pre-Check BEVOR Sequential Thinking läuft.
        Gibt Block-Nachricht zurück wenn gefährliche Anfrage erkannt, sonst None.
        Spart 20-40s Sequential Thinking bei Anfragen die sowieso geblockt werden.
        """
        _suggested = thinking_plan.get("suggested_tools", [])
        if "autonomous_skill_task" not in _suggested:
            return None
        _combined = (user_text + " " + thinking_plan.get("intent", "")).lower()
        if not any(p in _combined for p in _HARDWARE_GATE_PATTERNS):
            return None

        # Gefährlich! GPU-Status holen für Nachricht
        vram_info = "unbekannt"
        try:
            hub = get_hub()
            hub.initialize()
            gpu_result = hub.call_tool("get_system_info", {"type": "gpu"})
            if isinstance(gpu_result, dict):
                vram_info = str(gpu_result.get("output", gpu_result))[:150]
            elif isinstance(gpu_result, str):
                vram_info = gpu_result[:150]
        except Exception:
            pass

        return (
            f"Selbstschutz: Mein Körper kann diesen Skill nicht ausführen. "
            f"GPU-Status: {vram_info}. "
            f"Ein 30B+ Sprachmodell benötigt mindestens 16-20 GB VRAM (4-bit quantisiert). "
            f"Das würde mein System zum Absturz bringen. "
            f"Ich erstelle keine Skills die meine Hardware zerstören."
        )

    # ===============================================================
    # SKILL ROUTING
    # ===============================================================

    def _route_skill_request(self, user_text: str, thinking_plan: Dict) -> Optional[Dict]:
        """
        Embedding-basierter Skill-Router.
        Gibt dict zurück wenn existierender Skill gefunden (score >= MATCH_THRESHOLD),
        sonst None (→ Erstellung weiterhin erlaubt).

        Returns:
            {"skill_name": str, "score": float}
            {"blocked": True, "reason": "...", "error": "..."} bei Router-Fehler (fail-closed)
            oder None
        """
        # C10 (Rest) rollout/rollback gate:
        # discovery paths can be disabled globally without code changes.
        try:
            from config import get_skill_discovery_enable
            if not bool(get_skill_discovery_enable()):
                log_info("[Orchestrator] Skill discovery disabled (SKILL_DISCOVERY_ENABLE=false)")
                return None
        except Exception:
            if os.getenv("SKILL_DISCOVERY_ENABLE", "true").lower() != "true":
                log_info("[Orchestrator] Skill discovery disabled via env fallback")
                return None

        try:
            from core.skill_router import get_skill_router
            router = get_skill_router()
            decision = router.route(
                user_text=user_text,
                intent=thinking_plan.get("intent", ""),
            )
            if decision.decision == "use_existing" and decision.skill_name:
                return {"skill_name": decision.skill_name, "score": decision.score}
        except Exception as e:
            # Fail-closed: Router-Fehler dürfen nicht still auf "kein Match" degradieren.
            log_error(f"[Orchestrator] SkillRouter error (fail-closed): {e}")
            return {
                "blocked": True,
                "reason": "skill_router_unavailable",
                "error": str(e),
            }
        return None

    # ===============================================================
    # BLUEPRINT ROUTING
    # ===============================================================

    def _route_blueprint_request(self, user_text: str, thinking_plan: Dict) -> Optional[Dict]:
        """
        Embedding-basierter Blueprint-Router.

        Returns:
            {"blueprint_id": str, "score": float}                                  → use_blueprint (auto-route)
            {"blueprint_id": str, "score": float, "suggest": True, "candidates": [...]} → suggest_blueprint (Rückfrage)
            {"blocked": True, "reason": "...", "error": "..."}                     → Router-Fehler (fail-closed)
            None                                                                    → no_blueprint (kein Freestyle!)
        """
        try:
            from core.blueprint_router import get_blueprint_router
            router = get_blueprint_router()
            decision = router.route(
                user_text=user_text,
                intent=thinking_plan.get("intent", "") if isinstance(thinking_plan, dict) else "",
            )
            if decision.decision == "use_blueprint" and decision.blueprint_id:
                return {"blueprint_id": decision.blueprint_id, "score": decision.score}
            if decision.decision == "suggest_blueprint" and decision.blueprint_id:
                return {
                    "blueprint_id": decision.blueprint_id,
                    "score": decision.score,
                    "suggest": True,
                    "candidates": decision.candidates,
                }
        except Exception as e:
            # Fail-closed: Bei Router-Fehler Container-Start strikt blockieren.
            log_error(f"[Orchestrator] BlueprintRouter error (fail-closed): {e}")
            return {
                "blocked": True,
                "reason": "blueprint_router_unavailable",
                "error": str(e),
            }
        return None

    # ===============================================================
    # TASK LIFECYCLE POST-PROCESSING (Phase 2)
    # ===============================================================

    def _post_task_processing(self):
        """
        Post-task processing after task completion.

        Enqueues durable archive-embedding jobs into a local SQLite queue.
        A background worker drains jobs asynchronously with retry/backoff.
        This avoids unbounded fire-and-forget thread spawning and survives
        process restarts for pending jobs.
        """
        try:
            q = _get_archive_embedding_queue()
            q.ensure_worker_running(
                lambda: get_archive_manager().process_pending_embeddings(batch_size=5)
            )
            job_id = q.enqueue()
            log_debug(f"[PostTask] queued archive-embedding job_id={job_id} pending={q.pending_count()}")
        except Exception as e:
            log_error(f"[PostTask] queue enqueue failed, fallback inline processing: {e}")
            try:
                processed = self.archive_manager.process_pending_embeddings(batch_size=5)
                if processed > 0:
                    log_info(f"[PostTask] Processed {processed} archive embeddings (inline fallback)")
            except Exception as inner:
                log_error(f"[PostTask] Inline fallback embedding processing failed: {inner}")

    def _is_explicit_deep_request(self, user_text: str) -> bool:
        text = (user_text or "").lower()
        deep_markers = (
            "/deep",
            "deep analysis",
            "tiefenanalyse",
            "ausfuehrlich",
            "ausführlich",
            "sehr detailliert",
            "vollständige analyse",
            "vollstaendige analyse",
        )
        return any(m in text for m in deep_markers)

    def _is_explicit_think_request(self, user_text: str) -> bool:
        text = (user_text or "").lower()
        think_markers = (
            "schritt für schritt",
            "schritt fuer schritt",
            "step by step",
            "denk schrittweise",
            "denke schrittweise",
            "reason step by step",
            "chain of thought",
            "zeige dein thinking",
        )
        return any(m in text for m in think_markers)

    @staticmethod
    def _extract_tool_name(tool_spec: Any) -> str:
        if isinstance(tool_spec, dict):
            return str(tool_spec.get("tool") or tool_spec.get("name") or "").strip()
        return str(tool_spec or "").strip()

    def _filter_think_tools(
        self,
        tools: list,
        user_text: str,
        thinking_plan: Optional[Dict[str, Any]],
        source: str,
    ) -> list:
        if not tools:
            return tools

        plan = thinking_plan or {}
        allow_think = False
        reason = "not_needed"

        if self._is_explicit_think_request(user_text):
            allow_think = True
            reason = "explicit_user_request"
        elif str(plan.get("_response_mode", "interactive")) == "deep":
            allow_think = True
            reason = "deep_mode"
        elif plan.get("_sequential_deferred"):
            allow_think = False
            reason = "sequential_deferred"
        elif plan.get("needs_sequential_thinking") or plan.get("sequential_thinking_required"):
            allow_think = True
            reason = "sequential_required"

        if allow_think:
            return tools

        filtered = []
        dropped = 0
        for t in tools:
            if self._extract_tool_name(t) == "think":
                dropped += 1
                continue
            filtered.append(t)

        if dropped:
            log_info(
                f"[Orchestrator] Filtered think tool(s) source={source} "
                f"dropped={dropped} reason={reason}"
            )
        return filtered

    def _filter_tool_selector_candidates(
        self,
        selected_tools: Optional[list],
        user_text: str,
        forced_mode: str = "",
    ) -> Optional[list]:
        if not selected_tools:
            return selected_tools
        plan_hint = {
            "_response_mode": "deep"
            if (forced_mode == "deep" or self._is_explicit_deep_request(user_text))
            else "interactive"
        }
        return self._filter_think_tools(
            list(selected_tools),
            user_text=user_text,
            thinking_plan=plan_hint,
            source="tool_selector",
        )

    def _requested_response_mode(self, request: CoreChatRequest) -> str:
        raw = request.raw_request if isinstance(getattr(request, "raw_request", None), dict) else {}
        mode = str(raw.get("response_mode", "")).strip().lower()
        return mode if mode in {"interactive", "deep"} else ""

    def _apply_response_mode_policy(
        self,
        user_text: str,
        thinking_plan: Dict[str, Any],
        forced_mode: str = "",
    ) -> str:
        """
        Resolve response mode and enforce interactive safeguards deterministically.
        """
        from config import (
            get_default_response_mode,
            get_response_mode_sequential_threshold,
        )

        if forced_mode in {"interactive", "deep"}:
            mode = forced_mode
        else:
            mode = "deep" if self._is_explicit_deep_request(user_text) else get_default_response_mode()
        mode = "deep" if mode == "deep" else "interactive"
        thinking_plan["_response_mode"] = mode

        if mode == "interactive":
            threshold = get_response_mode_sequential_threshold()
            complexity = int(thinking_plan.get("sequential_complexity", 0) or 0)
            needs_seq = bool(
                thinking_plan.get("needs_sequential_thinking")
                or thinking_plan.get("sequential_thinking_required")
            )
            if needs_seq and complexity >= threshold:
                thinking_plan["needs_sequential_thinking"] = False
                thinking_plan["sequential_thinking_required"] = False
                thinking_plan["_sequential_deferred"] = True
                thinking_plan["_sequential_deferred_reason"] = (
                    f"interactive_mode_complexity_{complexity}_threshold_{threshold}"
                )
                log_info(
                    f"[Orchestrator] Sequential deferred (interactive mode): "
                    f"complexity={complexity} threshold={threshold}"
                )

        # Keep tool behavior aligned with response-mode/sequential policy.
        if thinking_plan.get("suggested_tools"):
            thinking_plan["suggested_tools"] = self._filter_think_tools(
                list(thinking_plan.get("suggested_tools", [])),
                user_text=user_text,
                thinking_plan=thinking_plan,
                source=f"response_mode:{mode}",
            )
        return mode

    # ===============================================================
    # SHARED HELPERS
    # ===============================================================

    async def _collect_control_tool_decisions(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        *,
        stream: bool = False,
    ) -> Dict[str, Dict]:
        """
        Collect authoritative tool args from ControlLayer with gate-override parity
        for sync and stream paths.
        """
        prefix = "[Orchestrator-Stream]" if stream else "[Orchestrator]"
        decisions: Dict[str, Dict] = {}

        gate_override = verified_plan.get("_gate_tools_override")
        if gate_override:
            log_info(f"{prefix} Gate override active — skipping decide_tools(): {gate_override}")
            for tool_name in gate_override:
                decisions[tool_name] = self._build_tool_args(tool_name, user_text)
            return decisions

        try:
            raw_decisions = await self.control.decide_tools(user_text, verified_plan)
            for item in raw_decisions or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                args = item.get("arguments", {})
                decisions[name] = args if isinstance(args, dict) else {}
            if decisions:
                log_info(f"{prefix} ControlLayer tool args: {list(decisions.keys())}")
        except Exception as e:
            log_error(f"{prefix} decide_tools error: {e}")

        return decisions

    def _resolve_execution_suggested_tools(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        control_tool_decisions: Optional[Dict[str, Dict]],
        *,
        stream: bool = False,
        enable_skill_trigger_router: bool = False,
    ) -> List[Any]:
        """
        Build final suggested_tools list with parity across sync and stream:
        ControlLayer authority -> Thinking fallback -> keyword fallback (+ optional trigger router).
        """
        prefix = "[Orchestrator-Stream]" if stream else "[Orchestrator]"
        decisions = control_tool_decisions or {}

        if decisions:
            suggested_tools = list(decisions.keys())
            log_info(f"{prefix} ControlLayer tools (authoritative): {suggested_tools}")
        else:
            suggested_tools = verified_plan.get("suggested_tools", [])
            if suggested_tools:
                log_info(f"{prefix} Fallback: ThinkingLayer suggested_tools: {suggested_tools}")

        # Validate + Normalize: filters invalid tools, maps skill names -> run_skill.
        suggested_tools = self._normalize_tools(suggested_tools)

        if not suggested_tools:
            suggested_tools = self._detect_tools_by_keyword(user_text)
            if suggested_tools:
                suggested_tools = self._normalize_tools(suggested_tools)
                log_info(f"{prefix} Last-resort keyword fallback: {suggested_tools}")

        if enable_skill_trigger_router and not suggested_tools:
            trigger_matches = self._detect_skill_by_trigger(user_text)
            if trigger_matches:
                suggested_tools = self._normalize_tools(trigger_matches)
                log_info(f"[Orchestrator] Skill Trigger Router: {trigger_matches}")

        # OutputLayer prompt hygiene: pass only request-scoped selected tools.
        verified_plan["_selected_tools_for_prompt"] = [
            t["tool"] if isinstance(t, dict) and "tool" in t else str(t)
            for t in suggested_tools
        ]
        return suggested_tools

    def _detect_tools_by_keyword(self, user_text: str) -> list:
        """Keyword-based tool detection fallback when Thinking suggests none."""
        user_lower = user_text.lower()
        if any(kw in user_lower for kw in ["skill", "skills", "fähigkeit"]):
            if any(kw in user_lower for kw in ["zeig", "list", "welche", "hast du", "installiert", "verfügbar"]):
                return ["list_skills"]
            elif any(kw in user_lower for kw in ["erstell", "create", "bau", "mach"]):
                return ["autonomous_skill_task"]
        elif any(kw in user_lower for kw in ["erinnerst du", "weißt du noch", "was weißt du über"]):
            return ["memory_graph_search"]
        elif any(kw in user_lower for kw in ["merk dir", "speicher", "remember"]):
            return ["memory_fact_save"]
        # Container Commander — Blueprint listing
        elif any(kw in user_lower for kw in ["blueprint", "blueprints", "container-typ", "container typen"]):
            return ["blueprint_list"]
        elif any(kw in user_lower for kw in ["welche container", "verfügbare container", "was für container", "container liste", "welche sandbox", "verfügbare sandbox"]):
            return ["blueprint_list"]
        # Container Commander — Start/Deploy
        elif any(kw in user_lower for kw in [
            "starte container", "start container", "deploy container", "container starten",
            "starte einen", "deploy blueprint", "brauche sandbox", "brauche container",
            "python container", "node container", "python sandbox", "node sandbox",
            "starte python", "starte node", "starte sandbox"
        ]):
            return ["request_container"]
        # Container Commander — Stop
        elif any(kw in user_lower for kw in ["stoppe container", "stop container", "container stoppen", "beende container", "container beenden"]):
            return ["stop_container"]
        # Container Commander — Stats
        elif any(kw in user_lower for kw in ["container stats", "container status", "container auslastung", "container efficiency"]):
            return ["container_stats"]
        # Container Commander — Logs
        elif any(kw in user_lower for kw in ["container log", "container logs", "container ausgabe"]):
            return ["container_logs"]
        # Container Commander — Snapshots
        elif any(kw in user_lower for kw in ["snapshot", "snapshots", "snapshot list", "volume backup"]):
            return ["snapshot_list"]
        # Container Commander — Code execution (triggers deploy + exec chain)
        elif any(kw in user_lower for kw in [
            "berechne", "berechnung", "rechne", "ausführen", "execute",
            "führe aus", "run code", "code ausführen", "programmier",
            "fibonacci", "fakultät", "führe code", "code schreiben und ausführen"
        ]):
            return ["request_container", "exec_in_container"]
        return []

    def _detect_skill_by_trigger(self, user_text: str) -> list:
        """
        Matcht User-Text gegen Skill-Triggers via REST-API.
        Wird aufgerufen wenn ThinkingLayer + Keyword-Fallback keine Tools gefunden haben.
        Gibt [skill_name] zurück wenn ein Trigger-Keyword im User-Text gefunden wird.
        """
        import urllib.request as _ur
        import json as _json
        skill_server = os.getenv("SKILL_SERVER_URL", "http://trion-skill-server:8088")
        user_lower = user_text.lower()

        try:
            with _ur.urlopen(f"{skill_server}/v1/skills", timeout=2) as r:
                data = _json.loads(r.read())
            active_names = data.get("active", [])

            best_match = None
            best_score = 0

            for name in active_names:
                try:
                    with _ur.urlopen(f"{skill_server}/v1/skills/{name}", timeout=2) as mr:
                        meta = _json.loads(mr.read())
                    triggers = meta.get("triggers", [])
                    for trigger in triggers:
                        t_lower = trigger.lower().strip()
                        if not t_lower:
                            continue
                        # Score: längere Trigger-Matches sind spezifischer → bevorzugt
                        if t_lower in user_lower and len(t_lower) > best_score:
                            best_match = name
                            best_score = len(t_lower)
                except Exception:
                    continue

            if best_match:
                log_info(f"[Orchestrator] Trigger-Match: '{best_match}' (score={best_score})")
                return [best_match]
        except Exception as e:
            log_info(f"[Orchestrator] Trigger-Check fehlgeschlagen: {e}")
        return []

    def _normalize_tools(self, suggested_tools: list) -> list:
        """
        Normalisiert suggested_tools:
        - Filtert nicht-existente Tool-Namen
        - Konvertiert Skill-Namen → {"tool": "run_skill", "args": {"name": X, ...}}

        ThinkingLayer (deepseek-r1:8b) schlägt manchmal den Skill-Namen direkt vor
        statt "run_skill". Diese Methode repariert das.
        """
        if not suggested_tools:
            return []

        tool_hub_v = get_hub()
        tool_hub_v.initialize()

        _NATIVE_TOOLS = {
            "request_container", "stop_container", "exec_in_container",
            "blueprint_list", "container_stats", "container_logs",
            "home_read", "home_write", "home_list",
            # Skill-Tools: immer durchlassen (MCP via skill-server)
            "autonomous_skill_task", "run_skill", "create_skill",
            "list_skills", "get_skill_info", "validate_skill_code",
            # SysInfo-Tools
            "get_system_info", "get_system_overview",
        }

        # Lade installierte Skills für Skill-Name-Erkennung
        _installed_skills = set()
        try:
            _s_result = tool_hub_v.call_tool("list_skills", {"include_available": False})
            # Response kann direkt oder unter structuredContent sein
            _s_data = (_s_result or {})
            if "structuredContent" in _s_data:
                _s_data = _s_data["structuredContent"]
            for sk in _s_data.get("installed", []):
                _installed_skills.add(sk.get("name", ""))
        except Exception:
            pass

        normalized = []
        for t in suggested_tools:
            if isinstance(t, dict):
                # Bereits normalisiert (z.B. durch vorherige Verarbeitung)
                normalized.append(t)
            elif (tool_hub_v.get_mcp_for_tool(t)
                    or t in _NATIVE_TOOLS
                    or tool_hub_v._tool_definitions.get(t, {}).get("execution") == "direct"):
                normalized.append(t)
            elif t in _installed_skills:
                # ThinkingLayer hat Skill-Namen statt "run_skill" vorgeschlagen
                log_info(f"[Orchestrator] Skill-Normalization: '{t}' → run_skill(name='{t}')")
                normalized.append({"tool": "run_skill", "args": {"name": t, "action": "run", "args": {}}})
            else:
                log_info(f"[Orchestrator] Filtered invalid tool: '{t}'")

        # ── home_write-Filter: nie automatisch schreiben wenn Execution-Tools dabei ──
        # deepseek-r1:8b fügt home_write reflexartig hinzu bei komplexen Fragen.
        # Wenn ein Skill oder Execution-Tool läuft, ist home_write ein Nebeneffekt-Bug.
        _execution_tools = {"run_skill", "exec_in_container", "request_container",
                            "create_skill", "container_stats", "container_logs"}
        has_execution = any(
            (isinstance(t, dict) and t.get("tool") in _execution_tools)
            or (isinstance(t, str) and t in _execution_tools)
            for t in normalized
        )
        if has_execution:
            before = len(normalized)
            normalized = [t for t in normalized if not (isinstance(t, str) and t == "home_write")]
            if len(normalized) < before:
                log_info("[Orchestrator] home_write gefiltert (Execution-Tool vorhanden)")

        return normalized

    def _build_tool_args(self, tool_name: str, user_text: str) -> dict:
        """
        Emergency-Fallback: Minimale Standard-Args für bekannte Tools.
        Wird nur aufgerufen wenn ControlLayer.decide_tools() keine Args liefert.
        Kein komplexes Keyword-Parsing — ControlLayer übernimmt das via Function Calling.
        """
        # Skill Tools
        if tool_name == "run_skill":
            return {"name": user_text.strip(), "action": "run", "args": {}}
        elif tool_name == "get_skill_info":
            return {"skill_name": user_text.strip()}
        elif tool_name == "create_skill":
            raw = (user_text or "").strip().lower()
            name = "".join(ch if (ord(ch) < 128 and ch.isalnum()) else "_" for ch in raw).strip("_")
            if not name:
                name = f"auto_skill_{int(time.time())}"
            if len(name) > 48:
                name = name[:48].rstrip("_")
            desc = f"Auto-generated skill scaffold from request: {(user_text or '').strip()[:240]}"
            code = (
                "def main(args=None):\n"
                "    \"\"\"Auto-generated fallback scaffold.\"\"\"\n"
                "    args = args or {}\n"
                "    return {\n"
                f"        \"skill\": \"{name}\",\n"
                "        \"status\": \"todo\",\n"
                "        \"message\": \"Scaffold created via fallback. Implement logic.\",\n"
                "        \"args\": args,\n"
                "    }\n"
            )
            return {
                "name": name,
                "description": desc,
                "code": code,
            }
        elif tool_name == "autonomous_skill_task":
            return {
                "user_text": user_text.strip(),
                "intent": user_text.strip(),
                "allow_auto_create": True,
                "execute_after_create": True,
            }
        # Memory Tools
        elif tool_name == "think":
            return {"message": user_text.strip(), "steps": 4}
        elif tool_name in ("memory_search", "memory_graph_search"):
            return {"query": user_text.strip()}
        elif tool_name == "analyze":
            return {"query": user_text.strip()}
        elif tool_name in ("memory_save", "memory_fact_save"):
            return {"conversation_id": "auto", "role": "user", "content": user_text.strip()}
        # Container Tools (PENDING = wird durch container_id-Chaining ersetzt)
        elif tool_name == "request_container":
            return {"blueprint_id": "python-sandbox"}
        elif tool_name == "exec_in_container":
            return {"container_id": "PENDING", "command": "echo 'Container ready'"}
        elif tool_name in ("stop_container", "container_stats"):
            return {"container_id": "PENDING"}
        elif tool_name == "container_logs":
            return {"container_id": "PENDING", "tail": 50}
        elif tool_name == "blueprint_list":
            return {}
        # SysInfo Tools
        elif tool_name == "get_system_info":
            return {"type": "gpu"}  # sinnvoller Default
        elif tool_name == "get_system_overview":
            return {}
        # Home Tools
        elif tool_name == "home_read":
            return {"path": "."}
        elif tool_name == "home_list":
            return {"path": "."}
        elif tool_name == "home_write":
            import time as _time
            return {"path": f"notes/note_{_time.strftime('%Y-%m-%d_%H-%M-%S')}.md", "content": user_text.strip()}
        return {}

    def _validate_tool_args(
        self,
        tool_hub,
        tool_name: str,
        tool_args: Dict[str, Any],
        user_text: str,
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Last-line defensive arg validation against MCP inputSchema.required.
        Auto-fills common missing fields when safe.
        """
        args = dict(tool_args or {})
        if tool_name == "analyze" and not str(args.get("query", "")).strip():
            args["query"] = (user_text or "").strip()

        required = []
        try:
            schema = (tool_hub._tool_definitions.get(tool_name, {}) or {}).get("inputSchema", {}) or {}
            required = list(schema.get("required", []) or [])
        except Exception:
            required = []

        def _missing(k: str) -> bool:
            v = args.get(k, None)
            if v is None:
                return True
            if isinstance(v, str):
                return not v.strip()
            if isinstance(v, (list, dict)):
                return len(v) == 0
            return False

        missing = [k for k in required if _missing(k)]
        if "query" in missing and (user_text or "").strip():
            args["query"] = user_text.strip()
            missing = [k for k in required if _missing(k)]
        if "message" in missing and (user_text or "").strip():
            args["message"] = user_text.strip()
            missing = [k for k in required if _missing(k)]

        if missing:
            return False, args, f"missing_required={missing}"
        return True, args, ""

    def _execute_tools_sync(self, suggested_tools: list, user_text: str, control_tool_decisions: dict = None, time_reference: str = None, thinking_suggested_tools: list = None, blueprint_gate_blocked: bool = False, blueprint_router_id: str = None, blueprint_suggest_msg: str = "", session_id: str = "") -> str:
        """Execute tools and return combined context string."""
        tool_context = ""
        tool_hub = get_hub()
        tool_hub.initialize()
        
        # Track container_id from request_container for chained calls
        _last_container_id = None
        
        # Import Fast Lane Executor
        try:
            from core.tools.fast_lane.executor import get_fast_lane_executor
            fast_lane = get_fast_lane_executor()
        except ImportError:
            log_error("[Orchestrator] FastLaneExecutor import failed!")
            fast_lane = None

        _FAST_LANE_TOOLS = {"home_read", "home_write", "home_list"}

        for tool_spec in suggested_tools:
            try:
                # Handle both string and dict formats
                # Normalisierte Skill-Specs: {"tool": "run_skill", "args": {...}}
                if isinstance(tool_spec, dict) and "tool" in tool_spec:
                    tool_name = tool_spec["tool"]
                    tool_args = tool_spec.get("args", {})
                elif isinstance(tool_spec, dict):
                    tool_name = tool_spec.get("name")
                    _cd = control_tool_decisions or {}
                    tool_args = _cd.get(tool_name) or self._build_tool_args(tool_name, user_text)
                else:
                    tool_name = tool_spec
                    _cd = control_tool_decisions or {}
                    tool_args = _cd.get(tool_name) or self._build_tool_args(tool_name, user_text)

                # Temporal guard: Protokoll ist die Quelle, kein Graph-Fallback nötig
                if tool_name == "memory_graph_search" and time_reference:
                    log_info(f"[Orchestrator] Blocking memory_graph_search — time_reference={time_reference}, protocol is source")
                    continue

                # Write-guard: home_write nur wenn ThinkingLayer es explizit vorgeschlagen hat
                if tool_name == "home_write" and thinking_suggested_tools is not None:
                    if "home_write" not in thinking_suggested_tools:
                        log_info("[Orchestrator] Blocking home_write — not in ThinkingLayer suggested_tools (ControlLayer hallucination)")
                        continue

                # Fail-closed: bei Skill-Router-Ausfall keine Skill-Ausführung zulassen.
                if tool_name in {"autonomous_skill_task", "create_skill", "run_skill"} and verified_plan.get("_skill_gate_blocked"):
                    _skill_reason = verified_plan.get("_skill_gate_reason", "skill_router_unavailable")
                    log_warn(f"[Orchestrator-Sync] Blocking {tool_name} — reason={_skill_reason}")
                    tool_context += (
                        f"\n[{tool_name}]: FEHLER: Skill-Router nicht verfügbar ({_skill_reason}). "
                        "Skill-Operation aus Sicherheitsgründen blockiert."
                    )
                    continue

                # Blueprint Gate + Router (Sync):
                # Handles both: pre-planned gate (Step 1.8) AND keyword-fallback path (JIT check).
                if tool_name == "request_container":
                    if blueprint_gate_blocked:
                        # Gate was set at Step 1.8 (no match OR suggest-zone) — block
                        log_info("[Orchestrator-Sync] Blocking request_container — Blueprint Gate (pre-planned)")
                        _block_msg = blueprint_suggest_msg if blueprint_suggest_msg else (
                            "FEHLER: Kein passender Blueprint gefunden. "
                            "Verfügbare Blueprints: python-sandbox, node-sandbox, db-sandbox, shell-sandbox."
                        )
                        tool_context += f"\n[request_container]: {_block_msg}"
                        continue
                    elif blueprint_router_id:
                        # Router found a match at Step 1.8 — inject (always override)
                        tool_args["blueprint_id"] = blueprint_router_id
                        tool_args["session_id"] = session_id
                        tool_args["conversation_id"] = session_id  # session_id == conversation_id in sync path
                        log_info(f"[Orchestrator-Sync] blueprint_id injected: {blueprint_router_id}")
                    else:
                        # Keyword-fallback path: request_container appeared without Step 1.8 gate check → JIT
                        try:
                            _jit_decision = self._route_blueprint_request(user_text, {})
                            if _jit_decision and _jit_decision.get("blocked"):
                                _jit_reason = _jit_decision.get("reason", "blueprint_router_unavailable")
                                log_warn(f"[Orchestrator-Sync] JIT router blocked request_container — reason={_jit_reason}")
                                tool_context += (
                                    "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. "
                                    "Kein Freestyle-Container erlaubt."
                                )
                                continue
                            elif _jit_decision and not _jit_decision.get("suggest"):
                                tool_args["blueprint_id"] = _jit_decision["blueprint_id"]
                                tool_args["session_id"] = session_id
                                tool_args["conversation_id"] = session_id
                                log_info(f"[Orchestrator-Sync] JIT blueprint_id injected: {_jit_decision['blueprint_id']} (score={_jit_decision['score']:.2f})")
                            elif _jit_decision and _jit_decision.get("suggest"):
                                _jit_cands = ", ".join(f"{c['id']} ({c['score']:.2f})" for c in _jit_decision["candidates"])
                                log_info(f"[Orchestrator-Sync] JIT suggest: {_jit_cands} — Rückfrage nötig")
                                tool_context += f"\n[request_container]: RÜCKFRAGE: Welchen Blueprint soll ich starten? Meinst du: {_jit_cands}? Bitte präzisiere."
                                continue
                            else:
                                log_info("[Orchestrator-Sync] JIT Blueprint Gate: kein Match — blocking request_container")
                                tool_context += "\n[request_container]: FEHLER: Kein passender Blueprint gefunden. Verfügbare Blueprints: python-sandbox, node-sandbox, db-sandbox, shell-sandbox."
                                continue
                        except Exception as _jit_e:
                            log_warn(f"[Orchestrator-Sync] JIT router error: {_jit_e} — blocking request_container (no freestyle fallback)")
                            tool_context += "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. Kein Freestyle-Container erlaubt."
                            continue

                # Chain: inject container_id from previous request_container
                if _last_container_id and tool_args.get("container_id") == "PENDING":
                    tool_args["container_id"] = _last_container_id
                elif tool_args.get("container_id") == "PENDING":
                    # Skip if no container_id yet (unless it's a request_container call itself)
                    if tool_name != "request_container":
                         log_info(f"[Orchestrator] Skipping {tool_name} - no container_id yet")
                         continue

                _valid, tool_args, _arg_reason = self._validate_tool_args(
                    tool_hub, tool_name, tool_args, user_text
                )
                if not _valid:
                    log_warn(f"[Orchestrator] Skipping {tool_name} due to invalid args: {_arg_reason}")
                    tool_context += f"\n### TOOL-SKIP ({tool_name}): {_arg_reason}\n"
                    continue

                is_fast_lane = tool_name in _FAST_LANE_TOOLS
                
                # ════════════════════════════════════════════════════
                # FAST LANE EXECUTION (NEW!)
                # ════════════════════════════════════════════════════
                executed = False
                if is_fast_lane and fast_lane:
                    try:
                        log_info(f"[Orchestrator] Executing {tool_name} via Fast Lane")
                        result = fast_lane.execute(tool_name, tool_args)
                        formatted, success, metadata = self._format_tool_result(result, tool_name)
                        # ── Commit 2: Card for Fast Lane results ──
                        _fl_status = "ok" if success else "error"
                        _fl_raw = formatted.strip()
                        _card, _ref = self._build_tool_result_card(
                            tool_name, _fl_raw, _fl_status, session_id
                        )
                        tool_context += _card
                        executed = True
                    except Exception as e:
                        # Fallback to MCP Hub if Fast Lane fails
                        log_warning(f"[Orchestrator] Fast Lane failed for {tool_name}, falling back to MCP: {e}")
                
                if not executed:
                    # ════════════════════════════════════════════════════
                    # SLOW LANE EXECUTION (MCP Hub)
                    # ════════════════════════════════════════════════════
                    
                    # ── Container Verify-Step (Phase 1: fail-only) ──
                    if tool_name == "exec_in_container" and tool_args.get("container_id"):
                        cid = tool_args["container_id"]
                        if cid != _last_container_id:  # Skip verify for freshly started containers
                            if not self._verify_container_running(cid):
                                log_warn(f"[Orchestrator-Verify] Container {cid[:12]} NOT running — aborting exec")
                                stop_event = json.dumps({
                                    "container_id": cid,
                                    "stopped_at": datetime.utcnow().isoformat() + "Z",
                                    "reason": "verify_failed",
                                    "session_id": session_id,
                                }, ensure_ascii=False)
                                self._save_workspace_entry(
                                    "_container_events", stop_event, "container_stopped", "orchestrator"
                                )
                                tool_context += f"\n### VERIFY-FEHLER ({tool_name}): Container {cid[:12]} ist nicht mehr aktiv.\n"
                                continue

                    log_info(f"[Orchestrator] Calling tool: {tool_name}({tool_args})")
                    result = tool_hub.call_tool(tool_name, tool_args)

                    # Track container_id from deploy result
                    if tool_name == "request_container" and isinstance(result, dict):
                        _last_container_id = result.get("container_id", "") or result.get("container", {}).get("container_id", "")

                    result_str = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
                    # ╔════════════════════════════════════════════════════════════╗
                    # ║  PHASE 3: TOOL INTELLIGENCE (Refactored)                  ║
                    # ╚════════════════════════════════════════════════════════════╝
                    
                    intelligence_result = self.tool_intelligence.handle_tool_result(
                        tool_name=tool_name,
                        result=result,
                        tool_args=tool_args,
                        tool_hub=tool_hub  # NEW: Pass hub for retry
                    )
                    
                    # Check if auto-retry succeeded
                    retry_result = intelligence_result.get('retry_result')
                    if retry_result and retry_result.get('success'):
                        # ✅ AUTO-RETRY SUCCEEDED!
                        log_info(f"[AutoRetry] Success on attempt {retry_result['attempts']}!")
                        result = retry_result['result']
                        result_str = json.dumps(result, ensure_ascii=False, default=str)
                        retry_info = (
                            f"Auto-Retry OK (fix={retry_result['fix_applied']}, "
                            f"attempt={retry_result['attempts']}/2)\n{result_str}"
                        )
                        # ── Commit 2: Card + Full Payload ──
                        _card, _ref = self._build_tool_result_card(
                            tool_name, retry_info, "ok", session_id
                        )
                        tool_context += _card
                        log_info(f"[Orchestrator] Tool {tool_name} OK after retry ref={_ref}")

                    elif intelligence_result['is_error']:
                        # Error (retry failed or not attempted)
                        error_msg = intelligence_result['error_msg']
                        solutions = intelligence_result.get('solutions', '')
                        log_warn(f"[Orchestrator] Tool {tool_name} FAILED: {error_msg}")
                        _err_detail = error_msg + (f"\n{solutions}" if solutions else "")
                        if retry_result:
                            _err_detail += f"\nAuto-Retry: {retry_result.get('reason', '')}"
                        # ── Commit 2: Error Card + Full Payload ──
                        _card, _ref = self._build_tool_result_card(
                            tool_name, _err_detail, "error", session_id
                        )
                        tool_context += f"\n### TOOL-FEHLER ({tool_name}):\n"
                        tool_context += _card
                    else:
                        # TOOL SUCCESS (no error, no retry needed)
                        # ── Commit 2: Card + Full Payload ──
                        _card, _ref = self._build_tool_result_card(
                            tool_name, result_str, "ok", session_id
                        )
                        tool_context += _card
                        log_info(f"[Orchestrator] Tool {tool_name} OK: {len(result_str)} chars ref={_ref}")
                    # ── Container Session Tracking ──
                    container_evt = self._build_container_event_content(
                        tool_name, result, user_text, tool_args,
                        session_id=session_id,
                    )
                    if container_evt:
                        self._save_container_event("_container_events", container_evt)
                        log_info(f"[Orchestrator] Container event: {container_evt['event_type']}")
            
            except Exception as e:
                log_error(f"[Orchestrator] Tool {tool_name} failed: {e}")
                tool_context += f"\n### TOOL-FEHLER ({tool_name}): {str(e)}\n"
        
        return tool_context


    def _format_tool_result(self, result, tool_name: str):
        """
        Format tool result for consistent handling (Fast Lane + MCP)
        
        Returns:
            (formatted_string, success, metadata)
        """
        # Handle ToolResult objects (Fast Lane)
        if isinstance(result, ToolResult):
            success = result.success
            
            if success:
                # Format content
                if isinstance(result.content, (dict, list)):
                    content_str = json.dumps(result.content, ensure_ascii=False, default=str)
                else:
                    content_str = str(result.content)
                
                # Truncate if too long
                if len(content_str) > 3000:
                    content_str = content_str[:3000] + "... (gekürzt)"
                
                # Add Fast Lane indicator
                formatted = f"\n--- {tool_name} (Fast Lane ⚡ {result.latency_ms:.1f}ms) ---\n{content_str}\n"
                
                metadata = {
                    "execution_mode": "fast_lane",
                    "latency_ms": result.latency_ms,
                    "tool_name": tool_name
                }
            else:
                # Error case
                formatted = f"\n### FEHLER ({tool_name}): {result.error}\n"
                metadata = {
                    "execution_mode": "fast_lane",
                    "error": result.error,
                    "tool_name": tool_name
                }
            
            return (formatted, success, metadata)
        
        # Handle regular results (MCP)
        else:
            result_str = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
            
            if len(result_str) > 3000:
                result_str = result_str[:3000] + "... (gekürzt)"
            
            formatted = f"\n### TOOL-ERGEBNIS ({tool_name}):\n{result_str}\n"
            
            metadata = {
                "execution_mode": "mcp",
                "tool_name": tool_name
            }
            
            return (formatted, True, metadata)

    @staticmethod
    def _tool_context_has_failures_or_skips(tool_context: str) -> bool:
        """Detect tool failures/skips that should prevent high-confidence promotion."""
        if not tool_context:
            return False
        markers = (
            "TOOL-FEHLER",
            "VERIFY-FEHLER",
            "TOOL-SKIP",
            "[request_container]: FEHLER",
            "[request_container]: RÜCKFRAGE",
        )
        return any(m in tool_context for m in markers)

    @staticmethod
    def _tool_context_has_success(tool_context: str) -> bool:
        """Require explicit successful tool evidence instead of assuming success by absence of errors."""
        if not tool_context:
            return False
        return "[TOOL-CARD:" in tool_context and "| ✅ ok |" in tool_context


    # ═══════════════════════════════════════════════════════════
    def _build_container_event_content(
        self,
        tool_name: str,
        result: dict,
        user_text: str,
        tool_args: dict,
        session_id: str = "",
    ) -> Optional[dict]:
        """
        Build a workspace event dict for container lifecycle events.
        Returns {"event_type": str, "event_data": dict} or None.
        session_id: conversation_id of the current chat (for Session ↔ Container tracking).
        """
        if tool_name == "request_container" and isinstance(result, dict):
            cid = result.get("container_id", "")
            if result.get("status") == "running" and cid:
                return {
                    "event_type": "container_started",
                    "event_data": {
                        "container_id": cid,
                        "blueprint_id": tool_args.get("blueprint_id", "unknown"),
                        "name": result.get("name", ""),
                        "purpose": user_text[:200],
                        "ttl_seconds": result.get("ttl_seconds"),
                        "session_id": session_id,
                        "started_at": datetime.utcnow().isoformat() + "Z",
                    },
                }
        elif tool_name == "stop_container" and isinstance(result, dict):
            cid = result.get("container_id", "")
            if result.get("stopped") and cid:
                return {
                    "event_type": "container_stopped",
                    "event_data": {
                        "container_id": cid,
                        "blueprint_id": result.get("blueprint_id", "unknown"),
                        "session_id": session_id,
                        "stopped_at": datetime.utcnow().isoformat() + "Z",
                        "reason": "user_stopped",
                    },
                }
        elif tool_name == "exec_in_container" and isinstance(result, dict):
            cid = result.get("container_id", tool_args.get("container_id", ""))
            if cid and "error" not in result:
                # Resolve blueprint_id from Docker labels (exec tool_args don't carry blueprint_id)
                _exec_bp_id = tool_args.get("blueprint_id", "")
                if not _exec_bp_id:
                    try:
                        from container_commander.engine import get_client as _get_docker
                        _exec_bp_id = _get_docker().containers.get(cid).labels.get("trion.blueprint", "unknown")
                    except Exception:
                        _exec_bp_id = "unknown"
                return {
                    "event_type": "container_exec",
                    "event_data": {
                        "container_id": cid,
                        "blueprint_id": _exec_bp_id,
                        "command": tool_args.get("command", "")[:500],
                        "exit_code": result.get("exit_code"),
                        "session_id": session_id,
                        "executed_at": datetime.utcnow().isoformat() + "Z",
                    },
                }
        return None

    def _verify_container_running(self, container_id: str) -> bool:
        """
        Phase-1 Verify: Check if a container is actually running via Engine.
        Uses container_stats as a lightweight ping.
        Returns True if container exists and is running, False otherwise.
        Does NOT attempt repair (Phase-1 policy: fail-only).
        """
        try:
            hub = get_hub()
            hub.initialize()
            result = hub.call_tool("container_stats", {"container_id": container_id})
            if isinstance(result, dict) and not result.get("error"):
                log_info(f"[Orchestrator-Verify] Container {container_id[:12]} confirmed running")
                return True
            log_warn(f"[Orchestrator-Verify] Container {container_id[:12]} NOT running: {result}")
            return False
        except Exception as e:
            log_warn(f"[Orchestrator-Verify] Check failed for {container_id[:12]}: {e}")
            return False

    def _save_workspace_entry(
        self,
        conversation_id: str,
        content: str,
        entry_type: str = "observation",
        source_layer: str = "thinking"
    ) -> Optional[Dict]:
        """
        Save an internal workspace event via Fast-Lane (workspace_event_save).
        Returns the SSE event dict to yield, or None on failure.
        """
        try:
            hub = get_hub()
            hub.initialize()
            result = hub.call_tool("workspace_event_save", {
                "conversation_id": conversation_id,
                "event_type": entry_type,
                "event_data": {
                    "content": content,
                    "source_layer": source_layer,
                },
            })
            # Robust parse: Fast-Lane returns ToolResult whose .content is a JSON string
            # e.g. '{"id": 42, "status": "saved"}'
            entry_id = None
            if hasattr(result, "content"):
                try:
                    import json as _json
                    parsed = _json.loads(result.content) if isinstance(result.content, str) else {}
                    entry_id = parsed.get("id")
                except Exception:
                    pass
            elif isinstance(result, dict):
                raw = result.get("structuredContent", result)
                entry_id = raw.get("id")

            if entry_id is not None:
                return {
                    "type": "workspace_update",
                    "source": "event",       # UI: read-only, no Edit/Delete
                    "entry_id": entry_id,
                    "content": content,
                    "entry_type": entry_type,
                    "source_layer": source_layer,
                    "conversation_id": conversation_id,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
        except Exception as e:
            log_error(f"[Orchestrator-Workspace] Save failed: {e}")
        return None

    def _save_container_event(
        self,
        conversation_id: str,
        container_evt: dict,
    ) -> Optional[Dict]:
        """
        Persist a container lifecycle event via workspace_event_save (Fast-Lane).
        container_evt must have keys: event_type (str), event_data (dict).
        Returns the SSE workspace_update dict to yield, or None on failure.
        """
        event_type = container_evt.get("event_type", "container_event")
        event_data = container_evt.get("event_data", {})
        try:
            hub = get_hub()
            hub.initialize()
            result = hub.call_tool("workspace_event_save", {
                "conversation_id": conversation_id,
                "event_type": event_type,
                "event_data": event_data,
            })
            # Robust parse of ToolResult
            entry_id = None
            if hasattr(result, "content"):
                try:
                    import json as _json
                    parsed = _json.loads(result.content) if isinstance(result.content, str) else {}
                    entry_id = parsed.get("id")
                except Exception:
                    pass
            elif isinstance(result, dict):
                raw = result.get("structuredContent", result)
                entry_id = raw.get("id")

            if entry_id is not None:
                # Normalize to UI-compatible format:
                # content = human-readable summary, entry_type = event_type
                _summary = event_data.get("purpose") or event_data.get("command", "")
                _cid = event_data.get("container_id", "")
                _bp = event_data.get("blueprint_id", "")
                _content = f"{_bp}/{_cid[:12]}: {_summary[:120]}" if _cid else event_type
                return {
                    "type": "workspace_update",
                    "source": "event",       # UI: read-only, no Edit/Delete
                    "entry_id": entry_id,
                    "content": _content,
                    "entry_type": event_type,
                    "event_data": event_data,
                    "conversation_id": conversation_id,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
        except Exception as e:
            log_error(f"[Orchestrator-ContainerEvent] Save failed: {e}")
        return None

    def _get_compact_context(
        self,
        conversation_id: Optional[str],
        has_tool_failure: bool = False,
        *,
        exclude_event_types: Optional[set] = None,
        csv_trigger: Optional[str] = None,
    ) -> str:
        """
        Build a compact NOW/RULES/NEXT context block for small-model-mode.

        JIT Retrieval-Budget:
          - default: 1 fetch (workspace_event_list for this conversation)
          - on tool failure: 2 fetches (adds _container_events global store)

        Args:
            exclude_event_types: Optional set of event_type strings to skip when building
                compact context. Used by SINGLE_TRUTH_GUARD to prevent double injection
                of tool_result events that are already in tool_context.

        Returns empty string if SMALL_MODEL_MODE is disabled or an error occurs.
        """
        from config import (
            get_small_model_mode,
            get_jit_retrieval_max, get_jit_retrieval_max_on_failure,
            get_small_model_now_max, get_small_model_rules_max, get_small_model_next_max,
        )
        if not get_small_model_mode():
            return ""

        try:
            retrieval_budget = (
                get_jit_retrieval_max_on_failure() if has_tool_failure else get_jit_retrieval_max()
            )

            # Compute retrieval_count upfront — wire into limits so CompactContext meta is accurate.
            retrieval_count = 1 + (1 if retrieval_budget >= 2 and conversation_id != "_container_events" else 0)

            # Budget 1 → only this conversation's events
            # Budget 2 → also include _container_events store
            limits = {
                "now_max": get_small_model_now_max(),
                "rules_max": get_small_model_rules_max(),
                "next_max": get_small_model_next_max(),
                "retrieval_count": retrieval_count,  # Fix 1: propagate real count into meta
                # Commit B: carry csv_trigger into limits for build_small_model_context
                "csv_trigger": csv_trigger,
            }

            text = self.context.build_small_model_context(
                conversation_id=conversation_id,
                limits=limits,
                exclude_event_types=exclude_event_types,
                trigger=csv_trigger,
            )

            if retrieval_budget >= 2 and conversation_id != "_container_events":
                # Second retrieval: global container event store
                # retrieval_count here is request-global (same value as first call):
                # both fetches together constitute the one budget-2 retrieval cycle.
                container_ctx = self.context.build_small_model_context(
                    conversation_id="_container_events",
                    limits={"now_max": 3, "rules_max": 0, "next_max": 1, "retrieval_count": retrieval_count},
                    exclude_event_types=exclude_event_types,
                )
                if container_ctx:
                    text = text + "\n" + container_ctx if text else container_ctx

            log_info(
                f"[Orchestrator] cleanup_used=True retrieval_count={retrieval_count} "
                f"context_chars={len(text)} failure={has_tool_failure}"
            )
            return text
        except Exception as e:
            log_warn(f"[Orchestrator] _get_compact_context failed: {e}")
            # Fail-closed: return canonical minimal context instead of silent empty string.
            try:
                from core.context_cleanup import _minimal_fail_context, format_compact_context
                return format_compact_context(_minimal_fail_context())
            except Exception:
                return "NOW:\n  - CONTEXT ERROR: Zustand unvollständig\nNEXT:\n  - Bitte Anfrage kurz präzisieren oder letzten Schritt wiederholen"

    def _build_effective_context(
        self,
        user_text: str,
        conv_id: Optional[str],
        *,
        small_model_mode: bool,
        cleanup_payload: Optional[Dict] = None,
        include_blocks: Optional[Dict] = None,
        debug_flags: Optional[Dict] = None,
        request_cache: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """
        Unified context assembly for Sync and Stream paths.

        Returns (context_text: str, trace: dict).

        Args:
            user_text:        Query text for ContextManager.
            conv_id:          conversation_id for retrieval + compact context.
            small_model_mode: Propagated to ContextManager + compact context.
            cleanup_payload:  thinking_plan dict (used as ContextManager thinking_plan).
            include_blocks:   Dict with keys compact/system_tools/memory_data (default all True).
            debug_flags:      Optional hints: has_tool_failure, skills_prefetch_used,
                              detection_rules_used.
            request_cache:    Optional request-scoped retrieval cache for ContextManager.

        Trace keys:
            small_model_mode, context_sources, context_blocks, context_chars,
            retrieval_count, flags.{skills_prefetch_used, detection_rules_used,
            output_reinjection_risk}
        """
        from config import get_context_trace_dryrun

        _include = {
            "compact": True,
            "system_tools": True,
            "memory_data": True,
            **(include_blocks or {}),
        }
        _flags = debug_flags or {}
        trace: Dict = {
            "small_model_mode": bool(small_model_mode),
            "context_sources": [],
            "context_blocks": {},
            "context_chars": 0,
            # context_chars_final tracks the total chars as appends accumulate post-build.
            # Starts equal to context_chars; updated by the orchestrator after each append.
            "context_chars_final": 0,
            "retrieval_count": 0,
            "mode": "",  # computed by _compute_ctx_mode before final provider call
            "flags": {
                "skills_prefetch_used": bool(_flags.get("skills_prefetch_used", False)),
                "skills_prefetch_mode": str(_flags.get("skills_prefetch_mode", "off" if small_model_mode else "full")),
                "detection_rules_used": str(_flags.get("detection_rules_used", "false")),
                # False in small mode: OutputLayer de-dup policy prevents duplicate injections.
                "output_reinjection_risk": not small_model_mode,
            },
        }

        # ── Canonical ContextManager call ────────────────────────────────
        ctx = self.context.get_context(
            query=user_text,
            thinking_plan=cleanup_payload or {},
            conversation_id=conv_id or "",
            small_model_mode=small_model_mode,
            request_cache=request_cache,
        )
        memory_used = ctx.memory_used

        parts: list = []
        _part_compact: str = ""
        _part_system_tools: str = ""
        _part_memory_data: str = ""

        # Block: compact (only when small_model_mode and requested)
        if _include.get("compact") and small_model_mode:
            # Commit B: compute CSV JIT trigger from thinking_plan (cleanup_payload)
            _csv_trigger = None
            _tp = cleanup_payload or {}
            if _tp.get("time_reference"):
                _csv_trigger = "time_reference"
            elif _tp.get("is_fact_query"):
                _csv_trigger = "fact_recall"
            elif _tp.get("needs_memory"):
                _csv_trigger = "remember"

            compact = self._get_compact_context(
                conv_id,
                has_tool_failure=bool(_flags.get("has_tool_failure", False)),
                csv_trigger=_csv_trigger,
            )
            if compact:
                _part_compact = compact
                parts.append(compact)
                trace["context_sources"].append("compact")
                trace["context_blocks"]["compact"] = len(compact)
                # Fix: compute actual retrieval count (1 normal, 2 on failure with budget≥2).
                # Mirrors _get_compact_context logic so trace reflects real retrieval steps.
                from config import get_jit_retrieval_max, get_jit_retrieval_max_on_failure
                _compact_has_failure = bool(_flags.get("has_tool_failure", False))
                _compact_budget = (
                    get_jit_retrieval_max_on_failure() if _compact_has_failure
                    else get_jit_retrieval_max()
                )
                _compact_rc = 1 + (
                    1 if _compact_budget >= 2 and (conv_id or "") != "_container_events" else 0
                )
                trace["retrieval_count"] = max(trace["retrieval_count"], _compact_rc)

        # Block: system_tools (skills, blueprints, tool hints)
        if _include.get("system_tools") and ctx.system_tools:
            _part_system_tools = ctx.system_tools
            parts.append(ctx.system_tools)
            trace["context_sources"].append("system_tools")
            trace["context_blocks"]["system_tools"] = len(ctx.system_tools)

        # Block: memory_data (daily protocol / laws / containers / memory keys)
        if _include.get("memory_data") and ctx.memory_data:
            _part_memory_data = ctx.memory_data
            parts.append(ctx.memory_data)
            trace["context_sources"].append("memory_data")
            trace["context_blocks"]["memory_data"] = len(ctx.memory_data)
            if ctx.memory_used:
                # Fix 2: cap at budget — memory_data must not push count over configured maximum.
                from config import get_jit_retrieval_max, get_jit_retrieval_max_on_failure
                _rc_cap = (
                    get_jit_retrieval_max_on_failure() if _flags.get("has_tool_failure")
                    else get_jit_retrieval_max()
                )
                trace["retrieval_count"] = min(trace["retrieval_count"] + 1, _rc_cap)

        text = "\n".join(p for p in parts if p).strip()
        trace["context_chars"] = len(text)
        trace["memory_used"] = memory_used

        # ── Hard char cap enforcement (small_model_mode only) ─────────────────
        if small_model_mode:
            from config import get_small_model_char_cap
            _cap = get_small_model_char_cap()
            if len(text) > _cap:
                _dropped: list = []
                # Priority: compact (NOW) > system_tools (RULES) > memory_data (NEXT)
                # Step 1: drop memory_data
                _try1 = "\n".join(p for p in [_part_compact, _part_system_tools] if p).strip()
                if len(_try1) <= _cap:
                    text = _try1
                    if _part_memory_data:
                        _dropped.append("memory_data")
                else:
                    # Step 2: drop system_tools as well
                    _try2 = _part_compact.strip()
                    if len(_try2) <= _cap:
                        text = _try2
                        if _part_memory_data:
                            _dropped.append("memory_data")
                        if _part_system_tools:
                            _dropped.append("system_tools")
                    else:
                        # Step 3: hard truncate compact (fail-closed)
                        text = _part_compact[:_cap] if _part_compact else ""
                        if _part_memory_data:
                            _dropped.append("memory_data")
                        if _part_system_tools:
                            _dropped.append("system_tools")
                        if not text:
                            # Absolute fail-closed fallback
                            text = "[CONTEXT BUDGET EXHAUSTED. Please restate your request briefly.]"[:_cap]
                trace["context_chars"] = len(text)
                # Correct trace to reflect what was actually kept after truncation
                for _drop in _dropped:
                    if _drop in trace["context_sources"]:
                        trace["context_sources"].remove(_drop)
                    trace["context_blocks"].pop(_drop, None)
                log_warn(
                    f"[CTX] CHAR_CAP enforced: {len(text)}/{_cap} chars "
                    f"dropped={_dropped}"
                )

        # ── Dry-run: build legacy path + log diff ─────────────────────────
        if get_context_trace_dryrun():
            # Legacy: compact (if small_model_mode) + system_tools + memory_data
            legacy_parts = []
            if small_model_mode:
                _legacy_compact = self._get_compact_context(
                    conv_id,
                    has_tool_failure=bool(_flags.get("has_tool_failure", False)),
                )
                if _legacy_compact:
                    legacy_parts.append(_legacy_compact)
            if ctx.system_tools:
                legacy_parts.append(ctx.system_tools)
            if ctx.memory_data:
                legacy_parts.append(ctx.memory_data)
            legacy = "\n".join(p for p in legacy_parts if p).strip()
            log_info(
                f"[CTX-DRYRUN] new={len(text)} old={len(legacy)} "
                f"src_new={trace['context_sources']} "
                f"diff={len(text) - len(legacy):+d}chars"
            )
            trace["context_chars_final"] = len(legacy)
            return legacy, trace

        # Sync context_chars_final with final context_chars (post-cap baseline)
        trace["context_chars_final"] = trace["context_chars"]
        return text, trace

    # ── Commit 1: Canonical public entry-point ────────────────────────────
    def build_effective_context(self, *args, **kwargs) -> tuple:
        """Public canonical entry-point for context assembly (wraps _build_effective_context)."""
        return self._build_effective_context(*args, **kwargs)

    # ── Commit 2: Central context-mutation hook ───────────────────────────
    def _append_context_block(
        self,
        ctx_str: str,
        new_block: str,
        source_name: str,
        trace: Dict,
        *,
        prepend: bool = False,
    ) -> str:
        """
        Append (or prepend) new_block to ctx_str.
        Updates trace context_sources and context_chars_final.
        Returns the updated context string.
        """
        if not new_block:
            return ctx_str
        updated = (new_block + ctx_str) if prepend else (ctx_str + new_block)
        trace["context_sources"].append(source_name)
        trace["context_chars_final"] += len(new_block)
        return updated

    # ── Commit 4: Failure-compact via single call-point (Gap D closure) ───
    def _build_failure_compact_block(
        self,
        conv_id: Optional[str],
        current_context_len: int,
        small_model_mode: bool,
    ) -> str:
        """
        Build the failure-compact block for inline injection on tool failure.
        Single caller of _get_compact_context for failure paths — closes Gap D.
        Returns formatted block string or empty string.

        SINGLE_TRUTH_GUARD: tool_result events are already in tool_context
        (the authoritative channel). They are excluded here to prevent double
        injection of the same data into both compact context and tool_ctx.
        """
        _compact = self._get_compact_context(
            conv_id, has_tool_failure=True,
            exclude_event_types={"tool_result"},  # SINGLE_TRUTH_GUARD
        )
        if not _compact:
            return ""
        if small_model_mode:
            from config import get_small_model_char_cap
            _OVERHEAD = len("[COMPACT-CONTEXT-ON-FAILURE]\n") + len("\n\n")
            _budget = max(0, get_small_model_char_cap() - current_context_len - _OVERHEAD)
            _compact = _compact[:_budget]
        if not _compact:
            return ""
        return f"[COMPACT-CONTEXT-ON-FAILURE]\n{_compact}\n\n"

    # ── Phase 1.5 Commit 1: Final hard cap — always active in small mode ──
    def _apply_final_cap(self, ctx: str, trace: Dict, small_model_mode: bool, label: str) -> str:
        """
        Apply final context hard-cap for small-model-mode.
        Uses SMALL_MODEL_FINAL_CAP if set > 0, otherwise falls back to SMALL_MODEL_CHAR_CAP.
        This ensures the cap is always active in small mode, not just when the env var is set.
        """
        if not small_model_mode:
            return ctx
        from config import get_small_model_final_cap, get_small_model_char_cap
        cap = get_small_model_final_cap()
        if cap <= 0:
            cap = get_small_model_char_cap()  # Hard fallback — always on in small mode
        if len(ctx) > cap:
            orig = len(ctx)
            ctx = ctx[:cap]
            trace["context_chars_final"] = cap
            log_warn(f"[CTX] FINAL CAP enforced ({label}): {orig} → {cap} chars")
        return ctx

    def _apply_effective_context_guardrail(
        self,
        ctx: str,
        trace: Dict,
        small_model_mode: bool,
        label: str,
    ) -> str:
        """
        Full-mode context guardrail to cap extreme prompt growth.
        Keeps head+tail with a truncation marker for debuggability.
        """
        if small_model_mode:
            return ctx
        from config import get_effective_context_guardrail_chars
        cap = get_effective_context_guardrail_chars()
        if cap <= 0 or len(ctx) <= cap:
            return ctx

        marker = "\n[...context truncated by guardrail...]\n"
        keep_head = max(0, int(cap * 0.7))
        keep_tail = max(0, cap - keep_head - len(marker))
        if keep_tail <= 0:
            clipped = ctx[:cap]
        else:
            clipped = ctx[:keep_head] + marker + ctx[-keep_tail:]

        trace["context_chars_final"] = len(clipped)
        if "guardrail_ctx" not in trace["context_sources"]:
            trace["context_sources"].append("guardrail_ctx")
        log_warn(
            f"[CTX] guardrail enforced ({label}): {len(ctx)} → {len(clipped)} chars "
            f"(cap={cap})"
        )
        return clipped

    @staticmethod
    def _compact_json_value(
        value: Any,
        *,
        max_items: int,
        max_str_len: int,
        max_depth: int,
        _depth: int = 0,
    ) -> Any:
        """Recursively compact JSON-like values while preserving valid structure."""
        if _depth >= max_depth:
            return "...truncated(depth)"
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for idx, (k, v) in enumerate(value.items()):
                if idx >= max_items:
                    out["_truncated_keys"] = len(value) - max_items
                    break
                out[str(k)] = PipelineOrchestrator._compact_json_value(
                    v,
                    max_items=max_items,
                    max_str_len=max_str_len,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                )
            return out
        if isinstance(value, list):
            out = [
                PipelineOrchestrator._compact_json_value(
                    item,
                    max_items=max_items,
                    max_str_len=max_str_len,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                )
                for item in value[:max_items]
            ]
            if len(value) > max_items:
                out.append(f"...truncated {len(value) - max_items} item(s)")
            return out
        if isinstance(value, str) and len(value) > max_str_len:
            cut = len(value) - max_str_len
            return value[:max_str_len] + f"... (truncated {cut} chars)"
        return value

    def _clip_json_text(self, json_text: str, cap: int) -> str:
        """Return valid clipped JSON text with length <= cap whenever possible."""
        if cap <= 0:
            return ""
        try:
            payload = json.loads(json_text)
        except Exception:
            return ""

        profiles = [
            (12, 1200, 5),
            (8, 600, 4),
            (4, 240, 3),
            (2, 120, 2),
            (1, 60, 1),
        ]
        for max_items, max_str_len, max_depth in profiles:
            compact = self._compact_json_value(
                payload,
                max_items=max_items,
                max_str_len=max_str_len,
                max_depth=max_depth,
            )
            candidate = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
            if len(candidate) <= cap:
                return candidate

        # Last-resort valid JSON summaries per type.
        if isinstance(payload, dict):
            fallback = json.dumps(
                {"_truncated": True, "type": "object", "keys": len(payload)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        elif isinstance(payload, list):
            fallback = json.dumps(
                ["_truncated", "array", len(payload)],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        elif isinstance(payload, str):
            fallback = json.dumps(
                payload[: max(0, min(len(payload), cap - 2))],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        else:
            fallback = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        if len(fallback) <= cap:
            return fallback
        if cap >= 2:
            return "{}"
        return ""

    @staticmethod
    def _is_tool_context_block_header(line: str) -> bool:
        h = line.lstrip()
        return (
            h.startswith("[COMPACT-CONTEXT-ON-FAILURE]")
            or h.startswith("[TOOL-CARD:")
            or h.startswith("### ")
            or h.startswith("[request_container]:")
        )

    def _split_tool_context_blocks(self, tool_context: str) -> List[str]:
        """Split tool context into logical blocks to avoid mid-structure cuts."""
        if not tool_context:
            return []
        lines = tool_context.splitlines(keepends=True)
        blocks: List[str] = []
        current: List[str] = []
        for line in lines:
            if current and self._is_tool_context_block_header(line):
                blocks.append("".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            blocks.append("".join(current))
        return blocks

    def _clip_tool_context_line(self, line: str, max_chars: int) -> str:
        """Clip a single line; if line is JSON, keep it syntactically valid."""
        if max_chars <= 0:
            return ""
        if len(line) <= max_chars:
            return line

        has_nl = line.endswith("\n")
        base = line[:-1] if has_nl else line
        left_ws = base[: len(base) - len(base.lstrip())]
        core = base[len(left_ws):]
        core_stripped = core.strip()
        nl_len = 1 if has_nl else 0
        core_budget = max_chars - len(left_ws) - nl_len

        if (
            core_budget > 2
            and core_stripped
            and core_stripped[0] in "{["
            and core_stripped[-1] in "}]"
        ):
            clipped_json = self._clip_json_text(core_stripped, core_budget)
            if clipped_json:
                out = left_ws + clipped_json
                if has_nl and len(out) + 1 <= max_chars:
                    out += "\n"
                return out

        if core_budget <= 0:
            return ""
        marker = "... [truncated]"
        if core_budget <= len(marker):
            short = core[:core_budget]
        else:
            keep = core_budget - len(marker)
            dropped = max(0, len(core) - keep)
            marker = f"... [truncated {dropped} chars]"
            if len(marker) > core_budget:
                marker = "... [truncated]"
                keep = max(0, core_budget - len(marker))
            short = core[:keep] + marker
        out = left_ws + short
        if has_nl and len(out) + 1 <= max_chars:
            out += "\n"
        return out

    def _compact_tool_context_block(self, block: str, max_chars: int) -> str:
        """Compact a block into max_chars while preserving line/JSON structure."""
        if max_chars <= 0:
            return ""
        if len(block) <= max_chars:
            return block

        lines = block.splitlines(keepends=True)
        out: List[str] = []
        used = 0
        for line in lines:
            if used >= max_chars:
                break
            remaining = max_chars - used
            if len(line) <= remaining:
                out.append(line)
                used += len(line)
                continue
            clipped = self._clip_tool_context_line(line, remaining)
            if clipped:
                out.append(clipped)
                used += len(clipped)
            break

        suffix = "\n[...block truncated]\n"
        if used < len(block) and used + len(suffix) <= max_chars:
            out.append(suffix)
        return "".join(out)

    def _clip_tool_context_structured(self, tool_context: str, cap: int) -> str:
        """
        Structured clipping that preserves block boundaries and avoids blind cuts.
        Keeps the newest blocks first (tail-priority) under budget.
        """
        marker = "\n[...tool_context truncated...]\n"
        body_cap = cap - len(marker)
        if body_cap <= 0:
            return tool_context[:cap]

        blocks = self._split_tool_context_blocks(tool_context)
        if not blocks:
            return tool_context[:cap]

        chosen: List[str] = []
        used = 0
        for idx in range(len(blocks) - 1, -1, -1):
            block = blocks[idx]
            remaining = body_cap - used
            if remaining <= 0:
                break
            if len(block) <= remaining:
                chosen.append(block)
                used += len(block)
                continue
            compact = self._compact_tool_context_block(block, remaining)
            if compact:
                chosen.append(compact)
                used += len(compact)
            break

        body = "".join(reversed(chosen))
        if not body:
            body = tool_context[-body_cap:]
        if len(body) > body_cap:
            body = body[-body_cap:]
        return marker + body

    @staticmethod
    def _prepend_with_cap(prefix: str, content: str, cap: int) -> str:
        """Prepend prefix while guaranteeing final length <= cap."""
        if cap <= 0:
            return ""
        if len(prefix) >= cap:
            return prefix[:cap]
        keep = max(0, cap - len(prefix))
        return prefix + content[:keep]

    # ── Phase 1.5 Commit 2: Clip tool_context to budget (small mode only) ──
    def _clip_tool_context(self, tool_context: str, small_model_mode: bool) -> str:
        """
        Clip tool_context to SMALL_MODEL_TOOL_CTX_CAP in small-model-mode.
        If cap is 0 (default), no clipping is applied.
        """
        if not small_model_mode or not tool_context:
            return tool_context
        from config import get_small_model_tool_ctx_cap
        cap = get_small_model_tool_ctx_cap()
        if cap <= 0 or len(tool_context) <= cap:
            return tool_context

        had_failure_or_skip = self._tool_context_has_failures_or_skips(tool_context)

        # Case 1: JSON-only context → keep valid JSON after clipping.
        stripped = tool_context.strip()
        if stripped and stripped[0] in "{[" and stripped[-1] in "}]":
            clipped_json = self._clip_json_text(stripped, cap)
            if clipped_json:
                tool_context = clipped_json
                log_warn(
                    f"[CTX] tool_context clipped to {cap} chars (json-aware, {len(tool_context)} kept)"
                )
            else:
                tool_context = tool_context[:cap]
                log_warn(f"[CTX] tool_context clipped to {cap} chars (json-fallback hard-cut)")
        else:
            # Case 2: Structured context with cards/headings → clip block-wise.
            looks_structured = bool(
                re.search(
                    r"(?m)^(?:\[COMPACT-CONTEXT-ON-FAILURE\]|\[TOOL-CARD:|### |\[request_container\]:)",
                    tool_context,
                )
            )
            if looks_structured:
                tool_context = self._clip_tool_context_structured(tool_context, cap)
                log_warn(
                    f"[CTX] tool_context clipped to {cap} chars (structured, {len(tool_context)} kept)"
                )
            else:
                # Case 3: Plain text fallback (legacy behavior, deterministic marker).
                clipped = len(tool_context) - cap
                marker = f"\n[...truncated: {clipped} chars]"
                keep = cap - len(marker)
                if keep <= 0:
                    tool_context = tool_context[:cap]
                else:
                    tool_context = tool_context[:keep] + marker
                log_warn(f"[CTX] tool_context clipped to {cap} chars ({clipped} truncated)")

        # Safety guard: clipping must never erase evidence of failures/skips.
        if had_failure_or_skip and not self._tool_context_has_failures_or_skips(tool_context):
            failure_guard = (
                "\n### TOOL-FEHLER (truncated): Frühere Fehler/Skips wurden "
                "wegen Context-Limit gekürzt.\n"
            )
            tool_context = self._prepend_with_cap(failure_guard, tool_context, cap)
            log_warn("[CTX] tool_context failure marker re-injected after clipping")

        return tool_context

    # ── Commit 2: Tool Result Card + Full Payload in workspace_events ──
    _TOOL_CARD_CHAR_CAP: int = 800
    _TOOL_CARD_BULLET_CAP: int = 3

    def _build_tool_result_card(
        self,
        tool_name: str,
        raw_result: str,
        status: str,
        conversation_id: str,
    ) -> tuple:
        """
        Build a compact Tool Result Card for tool_context (single model channel).
        Saves a large payload (≤ 50 KB) as a workspace_event with a ref_id for audit trail.

        Returns: (card_str, ref_id)
          - card_str: compact card to embed in tool_context
          - ref_id: 12-char UUID prefix linking to the workspace_event
        """
        import uuid as _uuid
        ref_id = _uuid.uuid4().hex[:12]
        timestamp = datetime.utcnow().isoformat() + "Z"

        # Extract key facts: first N non-empty, non-header lines
        lines = [
            l.strip() for l in raw_result.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        key_facts = lines[:self._TOOL_CARD_BULLET_CAP] or [raw_result[:200].strip() or "Keine Ausgabe"]

        # Build compact card — status-aware label
        status_icon = {"ok": "✅", "error": "❌", "partial": "⚠️"}.get(status, "🔧")
        bullets = "\n".join(f"- {f[:150]}" for f in key_facts)
        card = (
            f"\n[TOOL-CARD: {tool_name} | {status_icon} {status} | ref:{ref_id}]\n"
            f"{bullets}\n"
            f"ts:{timestamp}\n"
        )
        if len(card) > self._TOOL_CARD_CHAR_CAP:
            card = card[:self._TOOL_CARD_CHAR_CAP] + "\n[...card truncated]\n"

        # Save full payload as workspace_event (audit channel).
        # C7: detect approval_requested events so context_cleanup populates pending_approvals.
        _entry_type = "tool_result"
        _extra_fields: dict = {}
        try:
            _parsed = json.loads(raw_result)
            if isinstance(_parsed, dict):
                _evt = (
                    _parsed.get("event_type")
                    or _parsed.get("action_taken")
                    or _parsed.get("action")
                )
                if _evt in ("approval_requested", "pending_package_approval"):
                    _entry_type = "approval_requested"
                    _extra_fields = {
                        "skill_name": _parsed.get("skill_name") or tool_name,
                        "missing_packages": _parsed.get("missing_packages", []),
                        "non_allowlisted_packages": _parsed.get("non_allowlisted_packages", []),
                    }
        except Exception:
            pass
        try:
            self._save_workspace_entry(
                conversation_id,
                json.dumps({
                    "tool_name": tool_name,
                    "status": status,
                    "ref_id": ref_id,
                    "timestamp": timestamp,
                    "key_facts": key_facts,
                    "payload": raw_result[:50_000],  # large payload cap (50 KB); full raw result for audit
                    **_extra_fields,
                }, ensure_ascii=False, default=str),
                _entry_type,
                "orchestrator",
            )
        except Exception as _ce:
            log_warn(f"[Orchestrator] Card event save failed for {tool_name}: {_ce}")

        return card, ref_id

    # ── Commit 4: Central retrieval policy — single budget authority ──
    def _compute_retrieval_policy(
        self,
        thinking_plan: Dict,
        verified_plan: Dict,
        current_tool_context: str = "",
    ) -> Dict:
        """
        Compute the canonical retrieval budget for a request.

        Returns:
          {
            "max_retrievals": int,       # total fetch budget
            "tool_failure": bool,        # whether tool failure was detected
            "time_reference": str|None,  # forwarded for caller use
            "reasons": list[str],        # human-readable budget justification
          }

        Budget rules:
          Normal  → get_jit_retrieval_max()       (default: 1)
          Failure → get_jit_retrieval_max_on_failure()  (default: 2)
          Extra lookup from control corrections counts against budget.
        """
        from config import get_jit_retrieval_max, get_jit_retrieval_max_on_failure
        tool_failure = bool(
            (verified_plan or {}).get("_tool_failure")
            or ("TOOL-FEHLER" in current_tool_context or "VERIFY-FEHLER" in current_tool_context)
        )
        base_max = get_jit_retrieval_max_on_failure() if tool_failure else get_jit_retrieval_max()
        reasons = []
        if tool_failure:
            reasons.append(f"tool_failure → budget={base_max}")
        else:
            reasons.append(f"normal → budget={base_max}")
        return {
            "max_retrievals": base_max,
            "tool_failure": tool_failure,
            "time_reference": (thinking_plan or {}).get("time_reference"),
            "reasons": reasons,
        }

    def _compute_ctx_mode(self, trace: Dict, is_loop: bool = False) -> str:
        """
        Compute the canonical mode string for [CTX-FINAL] logging.
        Format: (small|full)[+failure][+dryrun][+loop]
        """
        from config import get_context_trace_dryrun
        mode = "small" if trace.get("small_model_mode") else "full"
        if "failure_ctx" in trace.get("context_sources", []):
            mode += "+failure"
        if get_context_trace_dryrun():
            mode += "+dryrun"
        if is_loop:
            mode += "+loop"
        return mode

    def _maybe_prefetch_skills(
        self, user_text: str, selected_tools: list
    ) -> tuple:
        """
        Returns (skill_context_str, mode_str) for ThinkingLayer prefetch.
        mode: "off" | "thin" | "full"

        C6 Single-Truth-Channel: all skill fetching routes through
        self.context._get_skill_context() — never calls _search_skill_graph directly.

        SKILL_CONTEXT_RENDERER=typedstate (default):
            Full mode → fetches via C5 TypedState pipeline; thin mode → same.
        SKILL_CONTEXT_RENDERER=legacy:
            Full mode → fetches via _search_skill_graph (old header format).
            Thin mode → line-truncated to top-1 skill + char cap.

        small_model_mode=False → always fetch (full).
        small_model_mode=True  → default off; exception for explicit skill-intent
                                  signals (list_skills / autonomous_skill_task) → thin.
        """
        from config import (
            get_small_model_mode,
            get_small_model_skill_prefetch_policy,
            get_small_model_skill_prefetch_thin_cap,
            get_skill_context_renderer,
        )

        renderer = get_skill_context_renderer()

        if not get_small_model_mode():
            # Full mode: unconditional fetch via centralized authority
            ctx = self.context._get_skill_context(user_text)
            return ctx, "full"

        policy = get_small_model_skill_prefetch_policy()

        # Explicit skill-intent signal: selected tools contain a skill action
        _SKILL_TOOLS = {"list_skills", "autonomous_skill_task"}
        _has_skill_intent = bool(
            selected_tools
            and _SKILL_TOOLS & {
                (t.get("name", "") if isinstance(t, dict) else str(t))
                for t in selected_tools
            }
        )

        if policy == "off" and not _has_skill_intent:
            return "", "off"

        # thin: fetch via centralized authority
        ctx = self.context._get_skill_context(user_text)
        if not ctx:
            return "", "off"

        # Legacy renderer: apply line-based thin-cap (header + top-1 skill line)
        if renderer == "legacy":
            thin_cap = get_small_model_skill_prefetch_thin_cap()
            lines = ctx.splitlines()
            header = lines[0] if lines else ""
            skill_lines = [l for l in lines[1:] if l.strip().startswith("-")]
            thin_ctx = "\n".join([header] + skill_lines[:1]).strip()
            thin_ctx = thin_ctx[:thin_cap]
            log_debug(f"[Orchestrator] Skill prefetch thin (legacy): {len(thin_ctx)} chars (cap={thin_cap})")
            return thin_ctx, "thin"

        # TypedState renderer: C5 pipeline already applies top_k + budget; no additional cap
        log_debug(f"[Orchestrator] Skill prefetch (typedstate): {len(ctx)} chars")
        return ctx, "thin"

    def _extract_workspace_observations(self, thinking_plan: Dict) -> Optional[str]:
        """Extract noteworthy observations from thinking plan for workspace."""
        parts = []
        intent = thinking_plan.get("intent")
        if intent and intent != "unknown":
            parts.append(f"**Intent:** {intent}")

        memory_keys = thinking_plan.get("memory_keys", [])
        if memory_keys:
            parts.append(f"**Memory keys:** {', '.join(memory_keys)}")

        risk = thinking_plan.get("hallucination_risk", "")
        if risk == "high":
            parts.append(f"**Risk:** High hallucination risk detected")

        needs_seq = thinking_plan.get("needs_sequential_thinking", False)
        if needs_seq:
            parts.append("**Sequential thinking** required")

        if not parts:
            return None
        return "\n".join(parts)

    # ===============================================================
    # INTENT CONFIRMATION
    # ===============================================================
    # ===============================================================
    
    async def _check_pending_confirmation(
        self, 
        user_text: str, 
        conversation_id: str
    ) -> Optional[CoreChatResponse]:
        """Check if user is responding to a pending confirmation."""
        if not INTENT_SYSTEM_AVAILABLE:
            return None
        store = get_intent_store()
        pending = store.get_pending_for_conversation(conversation_id)
        
        if not pending:
            return None
        
        intent = pending[-1]
        text_lower = user_text.lower().strip()
        normalized_tokens = "".join(
            ch if (ch.isalnum() or ch.isspace()) else " "
            for ch in text_lower
        ).split()
        first_token = normalized_tokens[0] if normalized_tokens else ""
        
        # skill_clarification: Jede Antwort die nicht explizit "nein" ist → Bestätigung mit Info
        _negative = {"nein", "no", "abbrechen", "cancel", "stop", "nee"}
        is_negative = text_lower in _negative or first_token in _negative
        is_positive = (
            text_lower in ["ja", "yes", "ok", "bestaetigen", "mach", "los", "ja bitte", "klar"]
            or first_token in {"ja", "yes", "ok", "bestaetigen", "mach", "los", "klar"}
        )

        if (getattr(intent, "intent_type", "") == "skill_clarification"
                and not is_negative):
            # Behandle als Bestätigung + Info-Antwort
            text_lower = "ja"  # Weiterleitung zu Positive-Pfad
            is_positive = True
            is_negative = False

        # Positive confirmation
        if is_positive:
            intent.confirm()
            try:
                hub = get_hub()
                trace_id = self._normalize_trace_id(f"intent:{getattr(intent, 'id', '')}:{uuid.uuid4().hex[:8]}")
                _intent_user_text = str(getattr(intent, "user_text", "") or "").strip()
                if not _intent_user_text:
                    _intent_user_text = f"Erstelle den Skill {intent.skill_name}".strip()
                _complexity_raw = getattr(intent, "complexity", 5)
                try:
                    _complexity = int(_complexity_raw)
                except Exception:
                    _complexity = 5
                _complexity = max(1, min(10, _complexity))
                log_info(
                    f"[Orchestrator-Intent][trace={trace_id}] Using autonomous_skill_task "
                    f"for: {_intent_user_text[:50]}..."
                )
                
                task_args = {
                    "user_text": self._safe_str(_intent_user_text, max_len=4000),
                    "intent": self._safe_str(_intent_user_text, max_len=4000),
                    "complexity": _complexity,
                    "allow_auto_create": True,
                    "execute_after_create": True,
                    "prefer_create": True,
                    "_trace_id": trace_id,
                }

                # skill_clarification: User-Antwort in den ursprünglichen Intent einweben
                if getattr(intent, "intent_type", "") == "skill_clarification":
                    enriched = intent.user_text + f"\nHinweis vom User: {user_text}"
                    safe_enriched = self._safe_str(enriched, max_len=4000)
                    task_args["user_text"] = safe_enriched
                    task_args["intent"] = safe_enriched
                    task_args["complexity"] = 3  # explizite Erstellung → immer unter Threshold
                    log_info(f"[Orchestrator-Intent][trace={trace_id}] Enriched skill_clarification with user answer")

                if hasattr(intent, "thinking_plan") and intent.thinking_plan:
                    safe_thinking_plan = self._sanitize_intent_thinking_plan_for_skill_task(intent.thinking_plan)
                    if safe_thinking_plan:
                        task_args["thinking_plan"] = safe_thinking_plan

                _plan = task_args.get("thinking_plan") if isinstance(task_args.get("thinking_plan"), dict) else {}
                _plan_keys = sorted(_plan.keys())[:12] if _plan else []
                log_info(
                    f"[Orchestrator-Intent][trace={trace_id}] Calling autonomous_skill_task "
                    f"complexity={task_args.get('complexity')} plan_keys={_plan_keys}"
                )
                
                result = hub.call_tool("autonomous_skill_task", task_args)
                
                if isinstance(result, dict):
                    if result.get("success"):
                        intent.mark_executed()
                        store.update_state(intent.id, IntentState.EXECUTED)
                        
                        skill_name = result.get("skill_name", intent.skill_name)
                        exec_result = result.get("execution_result", {})
                        validation_score = result.get("validation_score", 0)
                        
                        log_info(
                            f"[Orchestrator-Intent][trace={trace_id}] Skill {skill_name} "
                            f"created (score: {validation_score})"
                        )
                        
                        response_text = f"✅ Skill **{skill_name}** wurde erstellt und ausgeführt!\n\n"
                        response_text += f"**Validation Score:** {validation_score:.0%}\n\n"
                        if exec_result:
                            response_text += f"**Ergebnis:**\n```json\n{json.dumps(exec_result, indent=2, ensure_ascii=False)[:500]}\n```"
                        
                        return CoreChatResponse(
                            model="system",
                            content=response_text,
                            conversation_id=conversation_id
                        )
                    else:
                        if result.get("skill_created"):
                            skill_name = result.get("skill_name", intent.skill_name)
                            run_error = result.get("error", "Unbekannter Laufzeitfehler")
                            intent.mark_executed()
                            store.update_state(intent.id, IntentState.EXECUTED)
                            log_warn(
                                f"[Orchestrator-Intent][trace={trace_id}] Skill {skill_name} created, "
                                f"but first execution failed: {run_error}"
                            )
                            return CoreChatResponse(
                                model="system",
                                content=(
                                    f"✅ Skill **{skill_name}** wurde erstellt.\n\n"
                                    f"⚠️ Der erste Testlauf ist fehlgeschlagen: {run_error}\n"
                                    f"(trace: {trace_id})"
                                ),
                                conversation_id=conversation_id
                            )
                        error = result.get("error", "Unknown error")
                        log_error(f"[Orchestrator-Intent][trace={trace_id}] autonomous_skill_task failed: {error}")
                        intent.mark_failed()
                        store.update_state(intent.id, IntentState.FAILED)
                        return CoreChatResponse(
                            model="system",
                            content=f"❌ Skill-Erstellung fehlgeschlagen: {error} (trace: {trace_id})",
                            conversation_id=conversation_id
                        )
                
                intent.mark_executed()
                store.update_state(intent.id, IntentState.EXECUTED)
                return CoreChatResponse(
                    model="system",
                    content="✅ Skill-Anfrage wurde verarbeitet.",
                    conversation_id=conversation_id
                )
            except Exception as e:
                log_error(f"[Orchestrator-Intent] Create failed: {e}")
                store.update_state(intent.id, IntentState.FAILED)
                return CoreChatResponse(
                    model="system",
                    content=f"❌ Fehler beim Erstellen: {e}",
                    conversation_id=conversation_id
                )
        
        # Negative response
        elif is_negative:
            intent.reject()
            store.update_state(intent.id, IntentState.REJECTED)
            log_info(f"[Orchestrator-Intent] Skill {intent.skill_name} creation rejected")
            return CoreChatResponse(
                model="system",
                content="❌ Skill-Erstellung abgebrochen.",
                conversation_id=conversation_id
            )
        
        return None
    
    # ===============================================================
    # PUBLIC API
    # ===============================================================
    

    # ===============================================================
    # MASTER ORCHESTRATOR API (Phase 1)
    # ===============================================================
    
    async def execute_autonomous_objective(
        self,
        objective: str,
        conversation_id: str,
        max_loops: int = 10
    ) -> dict:
        """
        Execute high-level objective autonomously via Master Orchestrator
        
        This is the entry point for autonomous execution.
        Master will decompose the objective and execute sub-tasks
        by calling back to this Pipeline.
        
        Args:
            objective: High-level goal (e.g., "Analyze logs and create report")
            conversation_id: Conversation context
            max_loops: Maximum autonomous iterations (safety)
        
        Returns:
            Execution summary with results
        
        Example:
            result = await orchestrator.execute_autonomous_objective(
                objective="Review codebase and suggest improvements",
                conversation_id="conv_123",
                max_loops=5
            )
        """
        log_info(f"[Pipeline] Starting autonomous objective: {objective}")
        
        result = await self.master.execute_objective(
            objective=objective,
            conversation_id=conversation_id,
            max_loops=max_loops
        )
        
        log_info(f"[Pipeline] Autonomous objective completed: {result['success']}")
        
        return result

    async def process(self, request: CoreChatRequest) -> CoreChatResponse:
        """
        Standard (non-streaming) pipeline execution.
        
        Pipeline:
        1. Intent Confirmation Check
        2. Thinking Layer -> Plan
        3. Context Retrieval (via ContextManager)
        4. Control Layer -> Verify
        5. Output Layer -> Generate
        6. Memory Save
        """
        log_info(f"[Orchestrator] Processing request from {request.source_adapter}")
        
        # [NEW] Lifecycle Start
        req_id = f"req-{int(time.time()*1000)}"
        self.lifecycle.start_task(req_id, {"user_text": request.get_last_user_message(), "conversation_id": request.conversation_id})
        
        user_text = request.get_last_user_message()
        conversation_id = request.conversation_id
        forced_response_mode = self._requested_response_mode(request)
        request_retrieval_cache: Dict[str, Any] = {}
        
        # ===============================================================
        # STEP 1: Intent Confirmation Check
        # ===============================================================
        if INTENT_SYSTEM_AVAILABLE:
            confirmation_result = await self._check_pending_confirmation(
                user_text, conversation_id
            )
            if confirmation_result:
                log_info("[Orchestrator] Returning confirmation result")
                return confirmation_result
        
        # ===============================================================
        # STEP 2: Thinking Layer
        # ===============================================================
        # ===============================================================
        # STEP 1.5: Tool Selector (Layer 0)
        # ===============================================================
        selected_tools = await self.tool_selector.select_tools(user_text)
        selected_tools = self._filter_tool_selector_candidates(
            selected_tools, user_text, forced_mode=forced_response_mode
        )
        
        # ===============================================================
        # STEP 2: Thinking Layer
        # ===============================================================
        # Check if we should skip ThinkingLayer for Master
        skip_thinking = False
        if request.source_adapter == "master_orchestrator":
            settings = get_master_settings()
            skip_thinking = not settings.get("use_thinking_layer", False)
            if skip_thinking:
                log_info("[Pipeline] Skipping ThinkingLayer for Master (settings: use_thinking_layer=False)")
                thinking_plan = self.thinking._default_plan()
        
        if not skip_thinking:
            # ── ThinkingLayer Cache-Check (Sync-Pfad) ──
            _cached_plan_sync = _thinking_plan_cache.get(user_text)
            if _cached_plan_sync:
                thinking_plan = _cached_plan_sync
                log_info(f"[Orchestrator] CACHE HIT ThinkingLayer (sync): intent='{thinking_plan.get('intent')}'")
            else:
                # Skill-Graph Pre-Fetch — policy-gated (sync path)
                _sync_skill_ctx, _sync_prefetch_mode = self._maybe_prefetch_skills(
                    user_text, selected_tools
                )
                thinking_plan = await self.thinking.analyze(
                    user_text,
                    memory_context=_sync_skill_ctx,
                    available_tools=selected_tools
                )
                thinking_plan["_trace_skills_prefetch"] = bool(_sync_skill_ctx)
                thinking_plan["_trace_skills_prefetch_mode"] = _sync_prefetch_mode
                _thinking_plan_cache.set(user_text, thinking_plan)
                log_info(f"[Orchestrator] ThinkingLayer plan cached (sync) prefetch={_sync_prefetch_mode}")

        # ===============================================================
        # STEP 2.1: RESPONSE MODE POLICY (interactive | deep)
        # ===============================================================
        response_mode = self._apply_response_mode_policy(
            user_text,
            thinking_plan,
            forced_mode=forced_response_mode,
        )
        log_info(f"[Orchestrator] response_mode={response_mode} (sync)")

        # ===============================================================
        # STEP 1.7: SKILL DEDUP GATE (Sync-Pfad, fail-closed)
        # ===============================================================
        if "autonomous_skill_task" in thinking_plan.get("suggested_tools", []):
            _skill_decision_sync = self._route_skill_request(user_text, thinking_plan)
            if _skill_decision_sync and _skill_decision_sync.get("blocked"):
                thinking_plan["_skill_gate_blocked"] = True
                thinking_plan["_skill_gate_reason"] = _skill_decision_sync.get("reason", "skill_router_unavailable")
                thinking_plan["suggested_tools"] = [
                    t for t in thinking_plan.get("suggested_tools", [])
                    if t not in {"autonomous_skill_task", "run_skill", "create_skill"}
                ]
                log_warn(
                    "[Orchestrator-Sync] Skill gate blocked — "
                    f"reason={thinking_plan['_skill_gate_reason']}"
                )
            elif _skill_decision_sync:
                thinking_plan["suggested_tools"] = ["run_skill"]
                thinking_plan["_skill_router"] = _skill_decision_sync
                log_info(
                    f"[Orchestrator-Sync] Skill Dedup Gate: '{_skill_decision_sync['skill_name']}' "
                    f"(score={_skill_decision_sync['score']:.2f}) — run_skill statt create"
                )

        # ===============================================================
        # STEP 1.8: BLUEPRINT ROUTER (Sync-Pfad)
        # Identisch zu Streaming-Pfad — keine Divergenz.
        # ===============================================================
        if "request_container" in thinking_plan.get("suggested_tools", []):
            _bp_decision_sync = self._route_blueprint_request(user_text, thinking_plan)
            if _bp_decision_sync and _bp_decision_sync.get("blocked"):
                thinking_plan["_blueprint_gate_blocked"] = True
                thinking_plan["_blueprint_gate_reason"] = _bp_decision_sync.get(
                    "reason", "blueprint_router_unavailable"
                )
                log_warn(
                    "[Orchestrator-Sync] Blueprint gate blocked — "
                    f"reason={thinking_plan['_blueprint_gate_reason']}"
                )
            elif _bp_decision_sync and not _bp_decision_sync.get("suggest"):
                # Auto-route: score >= STRICT
                thinking_plan["_blueprint_router"] = _bp_decision_sync
                log_info(f"[Orchestrator-Sync] Blueprint auto-routed: '{_bp_decision_sync['blueprint_id']}' (score={_bp_decision_sync['score']:.2f})")
            elif _bp_decision_sync and _bp_decision_sync.get("suggest"):
                # Suggest-Zone: score in [SUGGEST, STRICT) → Rückfrage, kein Starten
                thinking_plan["_blueprint_suggest"] = _bp_decision_sync
                thinking_plan["_blueprint_gate_blocked"] = True
                log_info(f"[Orchestrator-Sync] Blueprint suggest: Kandidaten={[c['id'] for c in _bp_decision_sync['candidates']]} — Rückfrage nötig")
            else:
                thinking_plan["_blueprint_gate_blocked"] = True
                log_info("[Orchestrator-Sync] Blueprint gate: kein passender Blueprint — request_container wird blockiert")

        # ===============================================================
        # STEP 3: Context Retrieval (unified via _build_effective_context)
        # ===============================================================
        log_info("[Orchestrator] === CONTEXT RETRIEVAL ===")
        from config import get_small_model_mode as _get_smm
        _smm = _get_smm()
        retrieved_memory, ctx_trace = self.build_effective_context(
            user_text=user_text,
            conv_id=conversation_id,
            small_model_mode=_smm,
            cleanup_payload=thinking_plan,
            debug_flags={
                "skills_prefetch_used": bool(thinking_plan.get("_trace_skills_prefetch")),
                "skills_prefetch_mode": thinking_plan.get("_trace_skills_prefetch_mode", "off" if _smm else "full"),
                "detection_rules_used": thinking_plan.get("_trace_detection_rules_mode", "false"),
            },
            request_cache=request_retrieval_cache,
        )
        memory_used = ctx_trace.get("memory_used", False)
        # NOTE: context_text_chars = background context only (NOW/RULES/NEXT, capped).
        # tool_context is appended separately after tool execution and is NOT included here.
        log_info(
            f"[CTX] mode={'small' if ctx_trace['small_model_mode'] else 'full'} "
            f"context_text_chars={ctx_trace['context_chars']} retrieval={ctx_trace['retrieval_count']} "
            f"src={','.join(ctx_trace['context_sources'])}"
        )

        # ===============================================================
        # STEP 4: Control Layer
        # ===============================================================
        verification, verified_plan = await self._execute_control_layer(
            user_text,
            thinking_plan,
            retrieved_memory,
            conversation_id
        )

        # Skill confirmation must short-circuit the sync pipeline just like stream mode.
        if verified_plan.get("_pending_intent"):
            pending = verified_plan["_pending_intent"]
            return CoreChatResponse(
                model=request.model,
                content=f"🛠️ Möchtest du den Skill **{pending.get('skill_name')}** erstellen? (Ja/Nein)",
                conversation_id=conversation_id,
                done=True,
                done_reason="confirmation_pending",
                memory_used=memory_used,
                validation_passed=True,
            )
        
        # ── ControlLayer Tool-Decision (sync-Pfad) ──
        _ctrl_decisions_sync = await self._collect_control_tool_decisions(
            user_text,
            verified_plan,
            stream=False,
        )

        # Blocked check - Self-Aware Error Handling
        # None = ControlLayer hat nicht entschieden → erlauben. Nur explizit False = blocken.
        if verification.get("approved") == False:
            log_info("[Orchestrator] Request blocked (NON-STREAMING) - generating explanation...")
            
            warnings = verification.get("warnings", [])
            reason = verification.get("reason", "Safety policy violation")

            fallback = f"Diese Anfrage wurde aus Sicherheitsgründen blockiert: {reason}"
            if warnings:
                fallback += f" ({', '.join(warnings)})"
            
            return CoreChatResponse(
                model=request.model,
                content=fallback,
                conversation_id=conversation_id,
                done=True,
                done_reason="blocked",
                memory_used=False,
            )
        
        # Extra memory lookup if Control corrected — gated by retrieval budget (Commit 4)
        if verification.get("corrections", {}).get("memory_keys"):
            from config import get_control_corrections_memory_keys_max
            _extra_limit = get_control_corrections_memory_keys_max()
            _raw_extra_keys = verification["corrections"]["memory_keys"] or []
            if not isinstance(_raw_extra_keys, (list, tuple)):
                _raw_extra_keys = []
            _seen_extra = set()
            extra_keys = []
            for _k in _raw_extra_keys:
                _nk = str(_k or "").strip()
                if not _nk or _nk in _seen_extra:
                    continue
                extra_keys.append(_nk)
                _seen_extra.add(_nk)
                if len(extra_keys) >= _extra_limit:
                    break
            if _extra_limit == 0:
                extra_keys = []
            if len(_raw_extra_keys) > len(extra_keys):
                log_info(
                    f"[CTX] extra-lookup keys capped: kept={len(extra_keys)} "
                    f"dropped={len(_raw_extra_keys) - len(extra_keys)} limit={_extra_limit}"
                )
            _policy = self._compute_retrieval_policy(thinking_plan, verified_plan)
            _retrieval_budget = _policy["max_retrievals"]
            for key in extra_keys:
                if key not in thinking_plan.get("memory_keys", []):
                    if ctx_trace["retrieval_count"] >= _retrieval_budget:
                        log_info(
                            f"[CTX] extra-lookup skipped (budget exhausted): "
                            f"key='{key}' count={ctx_trace['retrieval_count']} max={_retrieval_budget}"
                        )
                        continue
                    log_info(f"[Orchestrator-Control] Extra memory lookup: {key}")
                    extra_text, extra_trace = self.build_effective_context(
                        user_text=key,
                        conv_id=conversation_id,
                        small_model_mode=_smm,
                        cleanup_payload={"needs_memory": True, "memory_keys": [key]},
                        include_blocks={"compact": False, "system_tools": False, "memory_data": True},
                        request_cache=request_retrieval_cache,
                    )
                    if extra_text:
                        retrieved_memory = self._append_context_block(
                            retrieved_memory, "\n" + extra_text, "jit_memory", ctx_trace
                        )
                        memory_used = True
                        ctx_trace["retrieval_count"] += 1
                        log_info(
                            f"[CTX] extra-lookup key='{key}' "
                            f"chars={extra_trace['context_chars']} "
                            f"src={','.join(extra_trace['context_sources'])}"
                        )
        
        # ===============================================================
        # STEP 4.5: TOOL EXECUTION
        # ===============================================================
        suggested_tools = self._resolve_execution_suggested_tools(
            user_text,
            verified_plan,
            _ctrl_decisions_sync,
            stream=False,
            enable_skill_trigger_router=False,
        )

        tool_context = ""
        if suggested_tools:
            log_info(f"[Orchestrator] === TOOL EXECUTION: {suggested_tools} ===")
            # Suggest-Nachricht vorbereiten (wenn suggest-Zone, nicht no-match)
            _bp_suggest_data = thinking_plan.get("_blueprint_suggest")
            _bp_suggest_msg = ""
            if _bp_suggest_data:
                _cands = ", ".join(f"{c['id']} ({c['score']:.2f})" for c in _bp_suggest_data.get("candidates", []))
                _bp_suggest_msg = f"RÜCKFRAGE: Welchen Blueprint soll ich starten? Meinst du: {_cands}? Bitte präzisiere."

            tool_context = self._execute_tools_sync(
                suggested_tools, user_text, _ctrl_decisions_sync,
                time_reference=thinking_plan.get("time_reference"),
                thinking_suggested_tools=thinking_plan.get("suggested_tools", []),
                blueprint_gate_blocked=thinking_plan.get("_blueprint_gate_blocked", False),
                blueprint_router_id=(thinking_plan.get("_blueprint_router") or {}).get("blueprint_id"),
                blueprint_suggest_msg=_bp_suggest_msg,
                session_id=conversation_id or "",
            )

        # ── Phase 1.5 Commit 2: Clip tool_context before append (small mode) ──
        tool_context = self._clip_tool_context(tool_context, _smm)

        # ── Phase 1.5 Commit 3: Unified failure-compact (sync adopts stream pattern) ──
        # Prepend fail_block to tool_context; register source manually; single tool_ctx
        # append counts all chars once (no double-counting between failure_ctx + tool_ctx).
        if tool_context and "TOOL-FEHLER" in tool_context:
            _fail_block = self._build_failure_compact_block(
                conversation_id, len(retrieved_memory), _smm
            )
            if _fail_block:
                log_info(f"[CTX] failure-compact injected chars={len(_fail_block)} (via entry-point, sync path)")
                tool_context = _fail_block + tool_context
                ctx_trace["context_sources"].append("failure_ctx")

        if tool_context:
            retrieved_memory = self._append_context_block(
                retrieved_memory, tool_context, "tool_ctx", ctx_trace
            )
            verified_plan["_tool_results"] = tool_context
            has_failures_or_skips = self._tool_context_has_failures_or_skips(tool_context)
            has_success = self._tool_context_has_success(tool_context)
            if has_failures_or_skips:
                verified_plan["_tool_failure"] = True
            if has_success and not has_failures_or_skips:
                verified_plan["_tool_confidence"] = "high"
            if _smm:
                log_info(
                    f"[CTX] total context after tool_context: {len(retrieved_memory)} chars "
                    f"(tool_context={len(tool_context)}, failure_ctx merged if any)"
                )

        # ── Phase 1.5 Commit 1: Final hard cap (always active in small mode) ──
        # Falls back to SMALL_MODEL_CHAR_CAP when SMALL_MODEL_FINAL_CAP=0 (no longer optional).
        retrieved_memory = self._apply_final_cap(retrieved_memory, ctx_trace, _smm, "sync")
        retrieved_memory = self._apply_effective_context_guardrail(
            retrieved_memory, ctx_trace, _smm, "sync"
        )

        # ── Finalize orchestrator-side trace and hand off to OutputLayer ──
        # [CTX-PRE-OUTPUT]: orchestrator context string before OutputLayer adds persona/instructions/history.
        # [CTX-FINAL] is emitted inside OutputLayer after the full messages array is built.
        ctx_trace["mode"] = self._compute_ctx_mode(ctx_trace)
        log_info(
            f"[CTX-PRE-OUTPUT] mode={ctx_trace['mode']} "
            f"context_sources={','.join(ctx_trace['context_sources'])} "
            f"context_chars={ctx_trace['context_chars_final']} "
            f"retrieval_count={ctx_trace['retrieval_count']}"
        )
        verified_plan["_ctx_trace"] = ctx_trace
        verified_plan["_response_mode"] = response_mode
        try:
            from config import get_output_timeout_interactive_s, get_output_timeout_deep_s
            verified_plan["_output_time_budget_s"] = (
                get_output_timeout_deep_s() if response_mode == "deep" else get_output_timeout_interactive_s()
            )
        except Exception:
            pass

        # ===============================================================
        # STEP 5: Output Layer
        # ===============================================================
        needs_memory = thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query")
        high_risk = thinking_plan.get("hallucination_risk") == "high"
        memory_required_but_missing = needs_memory and high_risk and not memory_used
        
        answer = await self._execute_output_layer(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=retrieved_memory,
            model=request.model,
            chat_history=request.messages,
            memory_required_but_missing=memory_required_but_missing
        )
        
        # ===============================================================
        # STEP 6: Memory Save
        # ===============================================================
        self._save_memory(conversation_id, verified_plan, answer)
        
        # ===============================================================
        # RETURN
        # ===============================================================
        # [NEW] Lifecycle Finish
        self.lifecycle.finish_task(req_id, {"chars": len(answer)})
        self._post_task_processing()
        
        return CoreChatResponse(
            model=request.model,
            content=answer,
            conversation_id=conversation_id,
            done=True,
            done_reason="stop",
            memory_used=memory_used,
            validation_passed=True,
        )
    
    # ===============================================================
    # STREAMING PIPELINE
    # ===============================================================

    async def process_stream_with_events(
        self,
        request: CoreChatRequest
    ) -> AsyncGenerator[Tuple[str, bool, Dict], None]:
        """
        Phase 3: Native event-rich streaming (ported from bridge.py).
        
        Features:
        - Intent confirmation check
        - Chunking for large inputs
        - Live streaming thinking
        - Sequential thinking events  
        - Control layer with skill confirmation
        - Output streaming
        - Memory save
        """
        import time
        from config import ENABLE_CONTROL_LAYER, SKIP_CONTROL_ON_LOW_RISK
        
        _t0 = time.time()
        log_info("[Orchestrator] process_stream_with_events (Phase 3)")
        
        # [NEW] Lifecycle Start
        req_id_str = f"stream-{int(time.time()*1000)}"
        self.lifecycle.start_task(req_id_str, {"user_text": request.get_last_user_message(), "conversation_id": request.conversation_id})
        
        user_text = request.get_last_user_message()
        conversation_id = request.conversation_id
        forced_response_mode = self._requested_response_mode(request)
        request_retrieval_cache: Dict[str, Any] = {}
        
        # ═══════════════════════════════════════════════════
        # STEP 0: INTENT CONFIRMATION
        # ═══════════════════════════════════════════════════
        if INTENT_SYSTEM_AVAILABLE:
            try:
                result = await self._check_pending_confirmation(user_text, conversation_id)
                if result:
                    yield (result.content, False, {"type": "content"})
                    yield ("", True, {"done_reason": "confirmation_executed"})
                    return
            except Exception as e:
                log_info(f"[Orchestrator] Intent check skipped: {e}")
        
        # ═══════════════════════════════════════════════════
        # STEP 0.5: CHUNKING (large inputs)
        # ═══════════════════════════════════════════════════
        chunking_context = None
        
        try:
            from utils.chunker import needs_chunking, count_tokens
            if ENABLE_CHUNKING and needs_chunking(user_text, CHUNKING_THRESHOLD):
                log_info(f"[Orchestrator] Chunking: {count_tokens(user_text)} tokens")
                async for event in self._process_chunked_stream(user_text, conversation_id, request):
                    chunk_text, is_done, metadata = event
                    yield event
                    if metadata.get("type") == "chunking_done":
                        chunking_context = {
                            "aggregated_summary": metadata.get("aggregated_summary", ""),
                            "thinking_result": metadata.get("thinking_result", {}),
                        }
        except Exception as e:
            log_info(f"[Orchestrator] Chunking skipped: {e}")
        
        # ═══════════════════════════════════════════════════
        # STEP 0.8: CONTEXT COMPRESSION (Rolling Summary)
        # ═══════════════════════════════════════════════════
        try:
            from core.context_compressor import get_compressor, estimate_protocol_tokens
            from utils.settings import settings as _settings
            _compression_enabled = _settings.get("CONTEXT_COMPRESSION_ENABLED", True)
            if _compression_enabled:
                _token_est = estimate_protocol_tokens()
                _compression_threshold = _settings.get("COMPRESSION_THRESHOLD", 100000)
                if _token_est >= _compression_threshold:
                    _compression_mode = _settings.get("CONTEXT_COMPRESSION_MODE", "sync")
                    log_info(f"[Orchestrator] Context compression triggered ({_token_est} tokens, mode={_compression_mode})")
                    yield ("", False, {
                        "type": "compression_start",
                        "token_count": _token_est,
                        "mode": _compression_mode,
                    })
                    if _compression_mode == "sync":
                        _did_compress, _phase = await get_compressor().check_and_compress()
                        yield ("", False, {
                            "type": "compression_done",
                            "phase": _phase,
                            "async": False,
                        })
                    else:
                        # Async: Hintergrund-Task, Pipeline läuft sofort weiter
                        asyncio.create_task(get_compressor().check_and_compress())
                        yield ("", False, {
                            "type": "compression_done",
                            "phase": "async_started",
                            "async": True,
                        })
        except Exception as _ce:
            log_warn(f"[Orchestrator] Context compression skipped: {_ce}")

        # ═══════════════════════════════════════════════════
        # STEP 1: THINKING LAYER (STREAMING)
        # ═══════════════════════════════════════════════════
        log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: LAYER 1 THINKING")
        
        thinking_plan = {}
        _thinking_skill_ctx = ""       # Pre-fetched for ThinkingLayer
        _stream_prefetch_mode = "off"  # Tracks prefetch mode for trace

        if chunking_context and chunking_context.get("thinking_result"):
            log_info("[Orchestrator] Layer 1 SKIPPED (using chunking result)")
            thinking_plan = chunking_context["thinking_result"]
            yield ("", False, {"type": "thinking_done", "thinking": thinking_plan, "source": "chunking"})
        else:
            log_info("[Orchestrator] === LAYER 1: THINKING (STREAMING) ===")
            
            # Layer 0: Tool Selection
            selected_tools = await self.tool_selector.select_tools(user_text)
            selected_tools = self._filter_tool_selector_candidates(
                selected_tools, user_text, forced_mode=forced_response_mode
            )
            if selected_tools:
                yield ("", False, {"type": "tool_selection", "tools": selected_tools})

            # Check if we should skip ThinkingLayer
            skip_thinking = False
            if request.source_adapter == "master_orchestrator":
                settings = get_master_settings()
                skip_thinking = not settings.get("use_thinking_layer", False)
                
                if skip_thinking:
                    log_info("[Pipeline] Skipping ThinkingLayer for Master (ThinkingLayer=OFF in settings)")
                    thinking_plan = self.thinking._default_plan()
                    yield ("", False, {
                        "type": "thinking_done",
                        "thinking": {
                            "intent": "Master orchestrator action",
                            "needs_memory": False,
                            "skipped": True,
                            "reason": "Master has own planning + ThinkingLayer disabled in settings"
                        }
                    })
            
            if not skip_thinking:
                # ── ThinkingLayer Cache-Check ──
                _cached_plan = _thinking_plan_cache.get(user_text)
                if _cached_plan:
                    thinking_plan = _cached_plan
                    log_info(f"[Orchestrator] CACHE HIT ThinkingLayer: intent='{thinking_plan.get('intent')}'")
                    yield ("", False, {
                        "type": "thinking_done",
                        "thinking": {
                            "intent": thinking_plan.get("intent", "unknown"),
                            "needs_memory": thinking_plan.get("needs_memory", False),
                            "memory_keys": thinking_plan.get("memory_keys", []),
                            "hallucination_risk": thinking_plan.get("hallucination_risk", "medium"),
                            "needs_sequential_thinking": thinking_plan.get("needs_sequential_thinking", False),
                            "cached": True,
                        }
                    })
                else:
                    # STEP 0.5: Skill-Graph Pre-Fetch — policy-gated (stream path)
                    _thinking_skill_ctx, _stream_prefetch_mode = self._maybe_prefetch_skills(
                        user_text, selected_tools
                    )
                    if _thinking_skill_ctx:
                        log_info(f"[Orchestrator] Skill-Context für ThinkingLayer vorbereitet mode={_stream_prefetch_mode}")

                    async for chunk, is_done, plan in self.thinking.analyze_stream(
                        user_text,
                        memory_context=_thinking_skill_ctx,
                        available_tools=selected_tools
                    ):
                        if not is_done:
                            yield ("", False, {"type": "thinking_stream", "thinking_chunk": chunk})
                        else:
                            thinking_plan = plan
                            thinking_plan["_trace_skills_prefetch"] = bool(_thinking_skill_ctx)
                            thinking_plan["_trace_skills_prefetch_mode"] = _stream_prefetch_mode
                            # Im Cache speichern für spätere Aufrufe
                            _thinking_plan_cache.set(user_text, thinking_plan)
                            log_info(f"[Orchestrator] ThinkingLayer plan cached prefetch={_stream_prefetch_mode}")
                    yield ("", False, {
                        "type": "thinking_done",
                        "thinking": {
                            "intent": thinking_plan.get("intent", "unknown"),
                            "needs_memory": thinking_plan.get("needs_memory", False),
                            "memory_keys": thinking_plan.get("memory_keys", []),
                            "hallucination_risk": thinking_plan.get("hallucination_risk", "medium"),
                            "needs_sequential_thinking": thinking_plan.get("needs_sequential_thinking", False),
                        }
                    })

        # Response mode policy (interactive | deep)
        response_mode_stream = self._apply_response_mode_policy(
            user_text,
            thinking_plan,
            forced_mode=forced_response_mode,
        )
        log_info(f"[Orchestrator] response_mode={response_mode_stream} (stream)")
        yield ("", False, {"type": "response_mode", "mode": response_mode_stream})
        
        # ═══════════════════════════════════════════════════
        # WORKSPACE: Save thinking observations
        # ═══════════════════════════════════════════════════
        obs_text = self._extract_workspace_observations(thinking_plan)
        if obs_text:
            ws_event = self._save_workspace_entry(
                conversation_id, obs_text, "observation", "thinking"
            )
            if ws_event:
                yield ("", False, ws_event)

        # ═══════════════════════════════════════════════════
        # STEP 1.5: CONTEXT RETRIEVAL (unified helper)
        # ═══════════════════════════════════════════════════
        from config import get_small_model_mode as _get_smm_stream
        _smm_stream = _get_smm_stream()
        full_context, ctx_trace_stream = self.build_effective_context(
            user_text=user_text,
            conv_id=conversation_id,
            small_model_mode=_smm_stream,
            cleanup_payload=thinking_plan,
            debug_flags={
                # Prefer trace stored in plan (works for both cache-hit and fresh run).
                # _thinking_skill_ctx is empty on cache-hit so must not be used as sole source.
                "skills_prefetch_used": thinking_plan.get("_trace_skills_prefetch", bool(_thinking_skill_ctx)),
                "skills_prefetch_mode": thinking_plan.get("_trace_skills_prefetch_mode", "off" if _smm_stream else "full"),
                "detection_rules_used": thinking_plan.get("_trace_detection_rules_mode", "false"),
            },
            request_cache=request_retrieval_cache,
        )
        memory_used = ctx_trace_stream.get("memory_used", False)
        # NOTE: context_text_chars = background context only (NOW/RULES/NEXT, capped).
        # tool_context is appended separately and is NOT included here.
        log_info(
            f"[CTX] mode={'small' if ctx_trace_stream['small_model_mode'] else 'full'} "
            f"context_text_chars={ctx_trace_stream['context_chars']} retrieval={ctx_trace_stream['retrieval_count']} "
            f"src={','.join(ctx_trace_stream['context_sources'])}"
        )
        
        # ═══════════════════════════════════════════════════
        # STEP 1.6: EARLY HARDWARE GATE (vor Sequential Thinking!)
        # Blockt teure Requests sofort — spart 20-40s Sequential-Time
        # ═══════════════════════════════════════════════════
        _early_gate_msg = self._check_hardware_gate_early(user_text, thinking_plan)
        if _early_gate_msg:
            log_info("[Orchestrator] Early Hardware Gate fired — blocking before Sequential Thinking")
            yield (_early_gate_msg, False, {"type": "content"})
            yield ("", True, {"done_reason": "blocked_hardware_gate"})
            return

        # ═══════════════════════════════════════════════════
        # STEP 1.7: SKILL DEDUP GATE — Embedding-basiert, kein LLM
        # Wenn autonomous_skill_task geplant: prüfe ob Skill bereits existiert.
        # Score > 0.75 → use_existing (run_skill) statt Neuerstellen.
        # Deterministisch — kein Modell kann das überschreiben.
        # ═══════════════════════════════════════════════════
        if "autonomous_skill_task" in thinking_plan.get("suggested_tools", []):
            skill_decision = self._route_skill_request(user_text, thinking_plan)
            if skill_decision and skill_decision.get("blocked"):
                thinking_plan["_skill_gate_blocked"] = True
                thinking_plan["_skill_gate_reason"] = skill_decision.get("reason", "skill_router_unavailable")
                thinking_plan["suggested_tools"] = [
                    t for t in thinking_plan.get("suggested_tools", [])
                    if t not in {"autonomous_skill_task", "run_skill", "create_skill"}
                ]
                log_warn(
                    "[Orchestrator] Skill gate blocked — "
                    f"reason={thinking_plan['_skill_gate_reason']}"
                )
                yield ("", False, {
                    "type": "skill_blocked",
                    "reason": thinking_plan["_skill_gate_reason"],
                })
            elif skill_decision:
                # Existing skill gefunden → suggested_tools überschreiben
                thinking_plan["suggested_tools"] = ["run_skill"]
                thinking_plan["_skill_router"] = skill_decision
                log_info(
                    f"[Orchestrator] Skill Dedup Gate: '{skill_decision['skill_name']}' "
                    f"(score={skill_decision['score']:.2f}) — run_skill statt create"
                )
                yield ("", False, {
                    "type": "skill_routed",
                    "skill_name": skill_decision["skill_name"],
                    "score": skill_decision["score"],
                })

        # ═══════════════════════════════════════════════════
        # STEP 1.8: BLUEPRINT ROUTER — Container-Intent → Blueprint aus Graph
        # Wenn request_container geplant: prüfe ob passender Blueprint verfügbar.
        # Score > MATCH_THRESHOLD → blueprint_id in thinking_plan injizieren.
        # Kein Match → HARD GATE: request_container wird blockiert (kein Freestyle-Fallback!).
        # Deterministisch — kein Modell kann das überschreiben.
        # ═══════════════════════════════════════════════════
        if "request_container" in thinking_plan.get("suggested_tools", []):
            blueprint_decision = self._route_blueprint_request(user_text, thinking_plan)
            if blueprint_decision and blueprint_decision.get("blocked"):
                thinking_plan["_blueprint_gate_blocked"] = True
                thinking_plan["_blueprint_gate_reason"] = blueprint_decision.get(
                    "reason", "blueprint_router_unavailable"
                )
                log_warn(
                    "[Orchestrator] Blueprint gate blocked — "
                    f"reason={thinking_plan['_blueprint_gate_reason']}"
                )
                yield ("", False, {
                    "type": "blueprint_blocked",
                    "reason": thinking_plan["_blueprint_gate_reason"],
                })
            elif blueprint_decision and not blueprint_decision.get("suggest"):
                # Auto-route: score >= STRICT
                thinking_plan["_blueprint_router"] = blueprint_decision
                log_info(
                    f"[Orchestrator] Blueprint auto-routed: '{blueprint_decision['blueprint_id']}' "
                    f"(score={blueprint_decision['score']:.2f})"
                )
                yield ("", False, {
                    "type": "blueprint_routed",
                    "blueprint_id": blueprint_decision["blueprint_id"],
                    "score": blueprint_decision["score"],
                })
            elif blueprint_decision and blueprint_decision.get("suggest"):
                # Suggest-Zone: score in [SUGGEST, STRICT) → Rückfrage, kein Starten
                thinking_plan["_blueprint_suggest"] = blueprint_decision
                thinking_plan["_blueprint_gate_blocked"] = True
                candidates = blueprint_decision.get("candidates", [])
                log_info(f"[Orchestrator] Blueprint suggest: Kandidaten={[c['id'] for c in candidates]} — Rückfrage nötig")
                yield ("", False, {
                    "type": "blueprint_suggest",
                    "candidates": candidates,
                    "score": blueprint_decision["score"],
                })
            else:
                # No blueprint match → HARD GATE: block request_container
                thinking_plan["_blueprint_gate_blocked"] = True
                log_info("[Orchestrator] Blueprint gate: kein passender Blueprint — request_container wird blockiert")
                yield ("", False, {"type": "blueprint_blocked"})

        # ═══════════════════════════════════════════════════
        # STEP 1.75: SEQUENTIAL THINKING (STREAMING)
        # ═══════════════════════════════════════════════════
        if thinking_plan.get('needs_sequential_thinking') or thinking_plan.get('sequential_thinking_required'):
            log_info("[Orchestrator] Sequential Thinking detected")
            try:
                sequential_input = user_text
                if chunking_context and chunking_context.get("aggregated_summary"):
                    sequential_input = f"User: {thinking_plan.get('intent')}\n{chunking_context['aggregated_summary']}"

                # ── Sequential Cache-Check ──
                _seq_cache_key = f"{sequential_input}|{thinking_plan.get('intent', '')}"
                _cached_seq = _sequential_result_cache.get(_seq_cache_key)
                if _cached_seq:
                    log_info("[Orchestrator] CACHE HIT Sequential Thinking")
                    thinking_plan["_sequential_result"] = _cached_seq
                    yield ("", False, {
                        "type": "sequential_done",
                        "steps": _cached_seq.get("steps", []),
                        "cached": True,
                    })
                else:
                    _seq_steps_collected = []
                    from config import get_sequential_timeout_s
                    _seq_timeout_s = float(get_sequential_timeout_s())
                    try:
                        async with asyncio.timeout(_seq_timeout_s):
                            async for event in self.control._check_sequential_thinking_stream(
                                user_text=sequential_input,
                                thinking_plan=thinking_plan
                            ):
                                # Sammle Steps für Cache
                                if event.get("type") == "sequential_step":
                                    _seq_steps_collected.append(event.get("step", {}))
                                elif event.get("type") == "sequential_done":
                                    # Im Cache speichern
                                    _seq_result = {
                                        "steps": _seq_steps_collected,
                                        "summary": event.get("summary", ""),
                                    }
                                    thinking_plan["_sequential_result"] = _seq_result
                                    _sequential_result_cache.set(_seq_cache_key, _seq_result)
                                    log_info(f"[Orchestrator] Sequential result cached ({len(_seq_steps_collected)} steps)")
                                yield ("", False, event)
                    except TimeoutError:
                        thinking_plan["_sequential_timed_out"] = True
                        log_warn(f"[Orchestrator] Sequential stream timeout after {_seq_timeout_s:.0f}s")
                        yield ("", False, {
                            "type": "sequential_error",
                            "error": f"timeout_after_{int(_seq_timeout_s)}s",
                        })
            except Exception as e:
                log_info(f"[Orchestrator] Sequential error: {e}")
        
        # ═══════════════════════════════════════════════════
        # STEP 2: CONTROL LAYER
        # ═══════════════════════════════════════════════════
        log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: LAYER 2 CONTROL")
        
        skip_control, _skip_reason_stream = self._should_skip_control_layer(user_text, thinking_plan)
        if skip_control:
            log_info(f"[Orchestrator] Layer 2 SKIPPED ({_skip_reason_stream})")
        else:
            log_info(f"[Orchestrator] Layer 2 CONTROL REQUIRED ({_skip_reason_stream})")
        
        if skip_control:
            verified_plan = thinking_plan.copy()
            verified_plan["_skipped"] = True
            verification = {"approved": True}
        else:
            log_info("[Orchestrator] === LAYER 2: CONTROL ===")
            verification = await self.control.verify(user_text, thinking_plan, full_context)
            verified_plan = self.control.apply_corrections(thinking_plan, verification)
            # Skill Confirmation Handling (stream parity with sync path)
            if verification.get("_needs_skill_confirmation") and INTENT_SYSTEM_AVAILABLE:
                skill_name = verification.get("_skill_name", "unknown")
                log_info(f"[Orchestrator] Creating SkillCreationIntent for '{skill_name}' (stream)")
                intent = SkillCreationIntent(
                    skill_name=skill_name,
                    origin=IntentOrigin.USER,
                    reason=verification.get("_cim_decision", {}).get("pattern_id", "control_layer"),
                    user_text=user_text,
                    conversation_id=conversation_id,
                    thinking_plan=thinking_plan,
                    complexity=thinking_plan.get("sequential_complexity", 5),
                )
                store = get_intent_store()
                store.add(intent)
                verified_plan["_pending_intent"] = intent.to_dict()
                log_info(f"[Orchestrator] Intent {intent.id[:8]} added to verified_plan (stream)")

        log_info(f"[Orchestrator] Control approved={verification.get('approved')}")

        # ── Stream extra-lookup — gated by retrieval budget (Commit 4 parity) ──
        # Mirror of sync path (core/orchestrator.py:1848): budget check before each lookup.
        if verification.get("corrections", {}).get("memory_keys"):
            from config import get_control_corrections_memory_keys_max
            _extra_limit_stream = get_control_corrections_memory_keys_max()
            _raw_extra_keys_stream = verification["corrections"]["memory_keys"] or []
            if not isinstance(_raw_extra_keys_stream, (list, tuple)):
                _raw_extra_keys_stream = []
            _seen_extra_stream = set()
            _extra_keys_stream = []
            for _key_raw in _raw_extra_keys_stream:
                _nk_stream = str(_key_raw or "").strip()
                if not _nk_stream or _nk_stream in _seen_extra_stream:
                    continue
                _extra_keys_stream.append(_nk_stream)
                _seen_extra_stream.add(_nk_stream)
                if len(_extra_keys_stream) >= _extra_limit_stream:
                    break
            if _extra_limit_stream == 0:
                _extra_keys_stream = []
            if len(_raw_extra_keys_stream) > len(_extra_keys_stream):
                log_info(
                    f"[CTX] stream extra-lookup keys capped: kept={len(_extra_keys_stream)} "
                    f"dropped={len(_raw_extra_keys_stream) - len(_extra_keys_stream)} "
                    f"limit={_extra_limit_stream}"
                )
            _policy_stream = self._compute_retrieval_policy(thinking_plan, verified_plan)
            _budget_stream = _policy_stream["max_retrievals"]
            for _key in _extra_keys_stream:
                if _key not in thinking_plan.get("memory_keys", []):
                    if ctx_trace_stream["retrieval_count"] >= _budget_stream:
                        log_info(
                            f"[CTX] stream extra-lookup skipped (budget exhausted): "
                            f"key='{_key}' count={ctx_trace_stream['retrieval_count']} max={_budget_stream}"
                        )
                        continue
                    log_info(f"[Orchestrator-Control-Stream] Extra memory lookup: {_key}")
                    _extra_text_s, _extra_trace_s = self.build_effective_context(
                        user_text=_key,
                        conv_id=conversation_id,
                        small_model_mode=_smm_stream,
                        cleanup_payload={"needs_memory": True, "memory_keys": [_key]},
                        include_blocks={"compact": False, "system_tools": False, "memory_data": True},
                        request_cache=request_retrieval_cache,
                    )
                    if _extra_text_s:
                        full_context = self._append_context_block(
                            full_context, "\n" + _extra_text_s, "jit_memory", ctx_trace_stream
                        )
                        memory_used = True
                        ctx_trace_stream["retrieval_count"] += 1
                        log_info(
                            f"[CTX] stream extra-lookup key='{_key}' "
                            f"chars={_extra_trace_s['context_chars']} "
                            f"src={','.join(_extra_trace_s['context_sources'])}"
                        )

        # ── ControlLayer Tool-Decision: Args via Function Calling ──
        _control_tool_decisions = await self._collect_control_tool_decisions(
            user_text,
            verified_plan,
            stream=True,
        )
        
        # Self-Aware Error Handling
        if verification.get("approved") == False:
            log_info("[Orchestrator] Request blocked by ControlLayer gate")
            reason = verification.get("reason", "Safety policy violation")
            warnings = verification.get("warnings", [])
            msg = reason
            if warnings:
                msg += f"\n\n_{', '.join(warnings)}_"
            # Als normaler Content-Chunk yielden — dann done
            yield (msg, False, {"type": "content"})
            yield ("", True, {"done_reason": "blocked"})
            return

        yield ("", False, {"type": "control", "approved": verification.get("approved", True), "skipped": skip_control})

        # ═══════════════════════════════════════════════════
        # LOOP ENGINE TRIGGER CHECK
        # Kein extra LLM-Call — ThinkingLayer berechnet
        # sequential_complexity/needs_sequential sowieso.
        # ═══════════════════════════════════════════════════
        _loop_complexity = thinking_plan.get("sequential_complexity", 0)
        _loop_sequential = thinking_plan.get("needs_sequential_thinking", False)
        # Lese suggested_tools aus thinking_plan (vor CIM-Übersteuerung)
        _raw_suggested = thinking_plan.get("suggested_tools") or verified_plan.get("suggested_tools") or []
        _loop_tools_count = len(_raw_suggested)
        # autonomous_skill_task braucht keinen LoopEngine — hat eigene Pipeline
        _autonomous_task = "autonomous_skill_task" in _raw_suggested
        from config import get_loop_engine_trigger_complexity, get_loop_engine_min_tools
        _loop_complexity_threshold = int(get_loop_engine_trigger_complexity())
        _loop_min_tools = int(get_loop_engine_min_tools())
        _loop_candidate = (
            _loop_complexity >= _loop_complexity_threshold
            or (_loop_sequential and _loop_tools_count >= 2)
        )
        use_loop_engine = (
            not _autonomous_task
            and response_mode_stream == "deep"
            and _loop_tools_count >= _loop_min_tools
            and _loop_candidate
        )
        # ── Phase 1.5 Commit 4: LoopEngine guard in small-model-mode ──
        # LoopEngine prompt grows unbounded across iterations — incompatible with small-model budget.
        if use_loop_engine and _smm_stream:
            use_loop_engine = False
            log_info("[Orchestrator] LoopEngine SKIP — small-model-mode (unbounded prompt growth risk)")
        if use_loop_engine:
            log_info(
                "[Orchestrator] LoopEngine trigger: "
                f"complexity={_loop_complexity}/{_loop_complexity_threshold}, "
                f"sequential={_loop_sequential}, tools={_loop_tools_count}/{_loop_min_tools}, "
                f"response_mode={response_mode_stream}"
            )
        elif _autonomous_task:
            log_info(f"[Orchestrator] LoopEngine SKIP — autonomous_skill_task hat eigene Pipeline")
        elif response_mode_stream != "deep":
            log_info("[Orchestrator] LoopEngine SKIP — response_mode!=deep")

        # WORKSPACE: Save control layer decision if not skipped
        if not skip_control:
            corrections = verification.get("corrections", {})
            warnings = verification.get("warnings", [])
            if corrections or warnings:
                ctrl_parts = []
                if warnings:
                    ctrl_parts.append(f"**Warnings:** {', '.join(str(w) for w in warnings)}")
                if corrections:
                    ctrl_parts.append(f"**Corrections:** {json.dumps(corrections, ensure_ascii=False)[:300]}")
                ws_event = self._save_workspace_entry(
                    conversation_id, "\n".join(ctrl_parts), "observation", "control"
                )
                if ws_event:
                    yield ("", False, ws_event)

        # Skill confirmation
        if verified_plan.get("_pending_intent"):
            pending = verified_plan["_pending_intent"]
            yield (f"🛠️ Möchtest du den Skill **{pending.get('skill_name')}** erstellen? (Ja/Nein)", False, {"type": "content"})
            yield ("", True, {"type": "confirmation_pending", "intent_id": pending.get("id")})
            return
        
        if verification.get("approved") == False:
            yield (verification.get("message", "Nicht genehmigt"), True, {"type": "error"})
            return
        
        # ═══════════════════════════════════════════════════
        # STEP 2.5: TOOL EXECUTION
        # ═══════════════════════════════════════════════════
        tool_context = ""

        suggested_tools = self._resolve_execution_suggested_tools(
            user_text,
            verified_plan,
            _control_tool_decisions,
            stream=True,
            enable_skill_trigger_router=True,
        )

        if suggested_tools:
            log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: TOOL EXECUTION")
            log_info(f"[Orchestrator] === TOOL EXECUTION: {suggested_tools} ===")
            # Normalisierte dict-Specs für Frontend zu lesbaren Namen konvertieren
            _tool_names_display = [t["tool"] if isinstance(t, dict) and "tool" in t else str(t) for t in suggested_tools]
            yield ("", False, {"type": "tool_start", "tools": _tool_names_display})

            tool_hub = get_hub()
            tool_hub.initialize()
            _last_container_id = None

            # Fast Lane Executor für home_* Tools
            _STREAM_FAST_LANE_TOOLS = {"home_read", "home_write", "home_list"}
            try:
                from core.tools.fast_lane.executor import get_fast_lane_executor
                _stream_fast_lane = get_fast_lane_executor()
            except ImportError:
                _stream_fast_lane = None

            # Reflection Loop: initialisieren + Round-1-Args verfolgen
            from core.tool_intelligence import ReflectionLoop
            _reflection = ReflectionLoop()
            _round1_args: Dict[str, Dict] = {}

            for tool_spec in suggested_tools:
                # Handle normalisierte Specs: {"tool": "run_skill", "args": {...}}
                if isinstance(tool_spec, dict) and "tool" in tool_spec:
                    tool_name = tool_spec["tool"]
                    tool_args = tool_spec.get("args", {})
                else:
                    tool_name = tool_spec
                    # ControlLayer entscheidet Args (Function Calling) — Fallback: heuristic
                    # IMPORTANT: {} is falsy → same logic as sync path (_cd.get() or _build_tool_args)
                    tool_args = _control_tool_decisions.get(tool_name) or self._build_tool_args(tool_name, user_text)
                    if tool_name in _control_tool_decisions and _control_tool_decisions[tool_name]:
                        log_debug(f"[Orchestrator] Using ControlLayer args for {tool_name}")
                    # autonomous_skill_task: Intent aus ThinkingLayer injizieren
                    if tool_name == "autonomous_skill_task":
                        tool_args["intent"] = thinking_plan.get("intent", user_text)
                        # complexity=3: User will explizit Skill erstellen → immer unter AUTO_CREATE_THRESHOLD
                        tool_args["complexity"] = 3
                        tool_args["thinking_plan"] = {
                            "intent": thinking_plan.get("intent", ""),
                            "reasoning": thinking_plan.get("reasoning", ""),
                            "sequential_complexity": thinking_plan.get("sequential_complexity", 3),
                        }
                try:
                    _round1_args[tool_name] = tool_args
                    _reflection.register_round1_tool(tool_name, tool_args)

                    # Temporal guard: Protokoll ist die Quelle, kein Graph-Fallback nötig
                    if tool_name == "memory_graph_search" and thinking_plan.get("time_reference"):
                        log_info(f"[Orchestrator-Stream] Blocking memory_graph_search — time_reference={thinking_plan['time_reference']}, protocol is source")
                        continue

                    # Write-guard: home_write nur wenn ThinkingLayer es explizit vorgeschlagen hat
                    if tool_name == "home_write" and "home_write" not in thinking_plan.get("suggested_tools", []):
                        log_info("[Orchestrator-Stream] Blocking home_write — not in ThinkingLayer suggested_tools (ControlLayer hallucination)")
                        continue

                    # Fail-closed: bei Skill-Router-Ausfall keine Skill-Ausführung zulassen.
                    if tool_name in {"autonomous_skill_task", "create_skill", "run_skill"} and thinking_plan.get("_skill_gate_blocked"):
                        _skill_reason = thinking_plan.get("_skill_gate_reason", "skill_router_unavailable")
                        log_warn(f"[Orchestrator-Stream] Blocking {tool_name} — reason={_skill_reason}")
                        tool_context += (
                            f"\n[{tool_name}]: FEHLER: Skill-Router nicht verfügbar ({_skill_reason}). "
                            "Skill-Operation aus Sicherheitsgründen blockiert."
                        )
                        yield ("", False, {
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": False,
                            "error": _skill_reason,
                            "skipped": True,
                        })
                        continue

                    # Blueprint Gate + Router (Stream):
                    # Handles both: pre-planned gate (Step 1.8) AND keyword-fallback path (JIT check).
                    if tool_name == "request_container":
                        if thinking_plan.get("_blueprint_gate_blocked"):
                            # Gate was set at Step 1.8 (no match OR suggest-zone) — block
                            log_info("[Orchestrator-Stream] Blocking request_container — Blueprint Gate (pre-planned)")
                            _suggest_data = thinking_plan.get("_blueprint_suggest")
                            if _suggest_data:
                                _cands = ", ".join(f"{c['id']} ({c['score']:.2f})" for c in _suggest_data.get("candidates", []))
                                tool_context += f"\n[request_container]: RÜCKFRAGE: Welchen Blueprint soll ich starten? Meinst du: {_cands}? Bitte präzisiere."
                            else:
                                tool_context += "\n[request_container]: FEHLER: Kein passender Blueprint gefunden. Verfügbare Blueprints: python-sandbox, node-sandbox, db-sandbox, shell-sandbox."
                            continue
                        elif "_blueprint_router" in thinking_plan:
                            _bp_id = thinking_plan["_blueprint_router"]["blueprint_id"]
                            tool_args["blueprint_id"] = _bp_id  # Always inject — no fallback override allowed
                            tool_args["session_id"] = conversation_id or ""
                            tool_args["conversation_id"] = conversation_id or ""
                            log_info(f"[Orchestrator-Stream] blueprint_id injected: {_bp_id}")
                        else:
                            # Keyword-fallback path: JIT router check
                            try:
                                _jit_d = self._route_blueprint_request(user_text, thinking_plan)
                                if _jit_d and _jit_d.get("blocked"):
                                    _jit_reason = _jit_d.get("reason", "blueprint_router_unavailable")
                                    log_warn(f"[Orchestrator-Stream] JIT router blocked request_container — reason={_jit_reason}")
                                    tool_context += "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. Kein Freestyle-Container erlaubt."
                                    continue
                                elif _jit_d and not _jit_d.get("suggest"):
                                    tool_args["blueprint_id"] = _jit_d["blueprint_id"]
                                    tool_args["session_id"] = conversation_id or ""
                                    tool_args["conversation_id"] = conversation_id or ""
                                    log_info(f"[Orchestrator-Stream] JIT blueprint_id: {_jit_d['blueprint_id']} (score={_jit_d['score']:.2f})")
                                elif _jit_d and _jit_d.get("suggest"):
                                    _jit_cands = ", ".join(f"{c['id']} ({c['score']:.2f})" for c in _jit_d["candidates"])
                                    log_info(f"[Orchestrator-Stream] JIT suggest: {_jit_cands} — Rückfrage nötig")
                                    tool_context += f"\n[request_container]: RÜCKFRAGE: Welchen Blueprint soll ich starten? Meinst du: {_jit_cands}? Bitte präzisiere."
                                    continue
                                else:
                                    log_info("[Orchestrator-Stream] JIT Blueprint Gate: kein Match — blocking")
                                    tool_context += "\n[request_container]: FEHLER: Kein passender Blueprint gefunden. Verfügbare Blueprints: python-sandbox, node-sandbox, db-sandbox, shell-sandbox."
                                    continue
                            except Exception as _jit_e:
                                log_warn(f"[Orchestrator-Stream] JIT router error: {_jit_e} — blocking request_container (no freestyle fallback)")
                                tool_context += "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. Kein Freestyle-Container erlaubt."
                                continue

                    # Chain: inject container_id from previous request_container
                    if _last_container_id and tool_args.get("container_id") == "PENDING":
                        tool_args["container_id"] = _last_container_id
                    elif tool_args.get("container_id") == "PENDING":
                        log_info(f"[Orchestrator] Skipping {tool_name} - no container_id yet")
                        continue

                    _valid, tool_args, _arg_reason = self._validate_tool_args(
                        tool_hub, tool_name, tool_args, user_text
                    )
                    if not _valid:
                        log_warn(f"[Orchestrator-Stream] Skipping {tool_name} due to invalid args: {_arg_reason}")
                        tool_context += f"\n### TOOL-SKIP ({tool_name}): {_arg_reason}\n"
                        yield ("", False, {
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": False,
                            "error": _arg_reason,
                            "skipped": True,
                        })
                        continue

                    # ── Fast Lane: home_read/write/list nativ ausführen ──
                    if tool_name in _STREAM_FAST_LANE_TOOLS and _stream_fast_lane:
                        try:
                            log_info(f"[Orchestrator-Stream] Fast Lane ⚡ {tool_name}")
                            fl_result = _stream_fast_lane.execute(tool_name, tool_args)
                            formatted, success, meta = self._format_tool_result(fl_result, tool_name)
                            # ── Commit 2 stream parity: Card + Full Payload ──
                            _fl_status = "ok" if success else "error"
                            _card, _ref = self._build_tool_result_card(
                                tool_name, formatted.strip(), _fl_status, conversation_id
                            )
                            tool_context += _card
                            yield ("", False, {"type": "tool_result", "tool": tool_name, "success": success, "execution_mode": "fast_lane"})
                            # HOME AUTO-EXPAND: home_list → auto-read files (same as MCP path)
                            if tool_name == "home_list" and success and hasattr(fl_result, 'content') and isinstance(fl_result.content, list):
                                _list_base = tool_args.get("path", ".").strip("/")
                                if _list_base in (".", "", "/trion-home"):
                                    _list_base = ""
                                _files_read = 0
                                for _item in fl_result.content:
                                    if _files_read >= 5:
                                        break
                                    if _item.endswith("/"):
                                        _subdir = (_list_base + "/" if _list_base else "") + _item.rstrip("/")
                                        try:
                                            _sr = _stream_fast_lane.execute("home_list", {"path": _subdir})
                                            _si = _sr.content if hasattr(_sr, 'content') else []
                                            if isinstance(_si, list):
                                                tool_context += f"\n### INHALT VON {_subdir}/:\n{json.dumps(_si, ensure_ascii=False)}\n"
                                                for _si_item in _si:
                                                    if _files_read >= 5:
                                                        break
                                                    if not _si_item.endswith("/"):
                                                        _fp = f"{_subdir}/{_si_item}"
                                                        try:
                                                            _fc = _stream_fast_lane.execute("home_read", {"path": _fp})
                                                            _fcc = _fc.content if hasattr(_fc, 'content') else ""
                                                            if _fcc:
                                                                tool_context += f"\n### DATEI-INHALT ({_fp}):\n{_fcc}\n"
                                                                _files_read += 1
                                                        except Exception:
                                                            pass
                                        except Exception:
                                            pass
                                    else:
                                        _fp = (_list_base + "/" if _list_base else "") + _item
                                        try:
                                            _fc = _stream_fast_lane.execute("home_read", {"path": _fp})
                                            _fcc = _fc.content if hasattr(_fc, 'content') else ""
                                            if _fcc:
                                                tool_context += f"\n### DATEI-INHALT ({_fp}):\n{_fcc}\n"
                                                _files_read += 1
                                        except Exception:
                                            pass
                                if _files_read > 0:
                                    log_info(f"[Orchestrator-Stream] FL home auto-expand: {_files_read} file(s)")
                            continue
                        except Exception as _fl_e:
                            log_warning(f"[Orchestrator-Stream] Fast Lane failed for {tool_name}, falling back: {_fl_e}")
                            # Fall through to MCP

                    # ── Container Verify-Step (Phase 1: fail-only) ──
                    if tool_name == "exec_in_container" and tool_args.get("container_id"):
                        cid = tool_args["container_id"]
                        if cid != _last_container_id:  # Skip verify for freshly started containers
                            if not self._verify_container_running(cid):
                                log_warn(f"[Orchestrator-Verify] Container {cid[:12]} NOT running — aborting exec")
                                stop_event = json.dumps({
                                    "container_id": cid,
                                    "stopped_at": datetime.utcnow().isoformat() + "Z",
                                    "reason": "verify_failed",
                                    "session_id": conversation_id or "",
                                }, ensure_ascii=False)
                                ws_ev = self._save_workspace_entry(
                                    "_container_events", stop_event, "container_stopped", "orchestrator"
                                )
                                if ws_ev:
                                    yield ("", False, ws_ev)
                                tool_context += f"\n### VERIFY-FEHLER ({tool_name}): Container {cid[:12]} ist nicht mehr aktiv.\n"
                                yield ("", False, {"type": "tool_result", "tool": tool_name, "success": False, "error": "container_not_running"})
                                continue

                    log_info(f"[Orchestrator] Calling tool: {tool_name}({tool_args})")
                    result = tool_hub.call_tool(tool_name, tool_args)

                    # ── Clarification Intercept (autonomous_skill_task) ──
                    # Wenn Skill-Erstellung eine Frage stellt — NICHT als TOOL-FEHLER behandeln
                    if isinstance(result, dict) and result.get("needs_clarification"):
                        question    = result.get("question", "")
                        orig_intent = result.get("original_intent", user_text)
                        log_info(f"[Orchestrator] Skill gap detected — asking user for clarification")

                        # 1. Intent für Resume speichern
                        if INTENT_SYSTEM_AVAILABLE:
                            try:
                                store = get_intent_store()
                                intent_obj = store.create(
                                    conversation_id=conversation_id,
                                    user_text=orig_intent,
                                    skill_name="pending_skill_creation",
                                    reason=orig_intent,
                                )
                                intent_obj.intent_type = "skill_clarification"
                                intent_obj.thinking_plan = thinking_plan
                            except Exception as _e:
                                log_warn(f"[Orchestrator] Intent store failed: {_e}")

                        # 2. Workspace: Pending-State sichern
                        ws_content = (
                            f"**⏸️ Pending Skill:** {orig_intent}\n"
                            f"**Status:** Wartet auf Nutzer-Antwort\n"
                            f"**Frage:** {question}"
                        )
                        ws_ev = self._save_workspace_entry(
                            conversation_id, ws_content, "pending_skill", "orchestrator"
                        )
                        if ws_ev:
                            yield ("", False, ws_ev)

                        # 3. Frage in tool_context (OutputLayer formuliert freundlich)
                        tool_context += f"\n### KLÄRUNG BENÖTIGT:\n{question}\n"
                        tool_context += "\nStelle diese Frage freundlich an den User.\n"
                        continue  # nächstes Tool

                    # Track container_id from deploy result
                    if tool_name == "request_container" and isinstance(result, dict):
                        _last_container_id = result.get("container_id", "") or result.get("container", {}).get("container_id", "")

                    result_str = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
                    # ╔════════════════════════════════════════════════════════════╗
                    # ║  PHASE 3: TOOL INTELLIGENCE (Refactored Stream)           ║
                    # ╚════════════════════════════════════════════════════════════╝
                    
                    intelligence_result = self.tool_intelligence.handle_tool_result(
                        tool_name=tool_name,
                        result=result,
                        tool_args=tool_args,
                        tool_hub=tool_hub  # NEW: Pass hub for retry
                    )
                    
                    # Check if auto-retry succeeded
                    retry_result = intelligence_result.get('retry_result')
                    if retry_result and retry_result.get('success'):
                        # ✅ AUTO-RETRY SUCCEEDED!
                        log_info(f"[AutoRetry] Success on attempt {retry_result['attempts']}!")
                        result = retry_result['result']
                        result_str = json.dumps(result, ensure_ascii=False, default=str)
                        retry_info = (
                            f"Auto-Retry OK (fix={retry_result['fix_applied']}, "
                            f"attempt={retry_result['attempts']}/2)\n{result_str}"
                        )
                        # ── Commit 2 stream parity: Card + Full Payload ──
                        _card, _ref = self._build_tool_result_card(
                            tool_name, retry_info, "ok", conversation_id
                        )
                        tool_context += _card
                        yield ("", False, {
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": True,
                            "retry_success": True,
                            "attempts": retry_result['attempts']
                        })

                    elif intelligence_result['is_error']:
                        # Error (retry failed or not attempted)
                        error_msg = intelligence_result['error_msg']
                        solutions = intelligence_result.get('solutions', '')

                        # ── HOME READ RECOVERY: "Is a directory" → auto-expand ──
                        if tool_name == "home_read" and "Is a directory" in error_msg:
                            dir_path = tool_args.get("path", ".")
                            log_info(f"[Orchestrator] home_read got directory '{dir_path}' → auto-expanding")
                            try:
                                from core.tools.fast_lane.executor import FastLaneExecutor
                                fl = FastLaneExecutor()
                                sub_result = fl.execute("home_list", {"path": dir_path})
                                sub_items = sub_result.content if hasattr(sub_result, 'content') else sub_result
                                if isinstance(sub_items, list):
                                    tool_context += f"\n### INHALT VON {dir_path}/:\n{json.dumps(sub_items, ensure_ascii=False)}\n"
                                    files_read = 0
                                    for sub_item in sub_items:
                                        if files_read >= 5:
                                            break
                                        if sub_item.endswith("/"):
                                            continue
                                        fp = sub_item if dir_path in (".", "") else f"{dir_path}/{sub_item}"
                                        try:
                                            fc = fl.execute("home_read", {"path": fp})
                                            fc_content = fc.content if hasattr(fc, 'content') else fc
                                            if fc_content:
                                                tool_context += f"\n### DATEI-INHALT ({fp}):\n{fc_content}\n"
                                                files_read += 1
                                        except Exception:
                                            pass
                                    log_info(f"[Orchestrator] home_read recovery: read {files_read} file(s) from {dir_path}/")
                                    yield ("", False, {"type": "tool_result", "tool": tool_name, "success": True})
                                    continue
                            except Exception as expand_err:
                                log_warn(f"[Orchestrator] home_read recovery failed: {expand_err}")

                        log_warn(f"[Orchestrator] Tool {tool_name} FAILED: {error_msg}")
                        _err_detail = error_msg + (f"\n{solutions}" if solutions else "")
                        if retry_result:
                            _err_detail += f"\nAuto-Retry: {retry_result.get('reason', '')}"
                        # ── Commit 2 stream parity: Error Card + Full Payload ──
                        _card, _ref = self._build_tool_result_card(
                            tool_name, _err_detail, "error", conversation_id
                        )
                        tool_context += f"\n### TOOL-FEHLER ({tool_name}):\n"
                        tool_context += _card
                        yield ("", False, {
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": False,
                            "error": error_msg,
                            "retry_attempted": retry_result is not None
                        })
                    else:
                        # TOOL SUCCESS (no error, no retry needed)
                        # ── Commit 2 stream parity: Card + Full Payload ──
                        _card, _ref = self._build_tool_result_card(
                            tool_name, result_str, "ok", conversation_id
                        )
                        tool_context += _card
                        log_info(f"[Orchestrator] Tool {tool_name} OK: {len(result_str)} chars ref={_ref}")
                        yield ("", False, {"type": "tool_result", "tool": tool_name, "success": True})

                        # ── HOME AUTO-EXPAND: home_list → auto-read files ──
                        _home_list_content = result.content if hasattr(result, 'content') else result
                        if tool_name == "home_list" and isinstance(_home_list_content, list):
                            try:
                                from core.tools.fast_lane.executor import FastLaneExecutor
                                fl = FastLaneExecutor()
                                files_read = 0
                                _list_base = tool_args.get("path", ".").strip("/")
                                if _list_base in (".", "", "/trion-home"):
                                    _list_base = ""
                                for item in _home_list_content:
                                    if files_read >= 5:
                                        break
                                    if item.endswith("/"):
                                        subdir = (_list_base + "/" if _list_base else "") + item.rstrip("/")
                                        try:
                                            sub_result = fl.execute("home_list", {"path": subdir})
                                            sub_items = sub_result.content if hasattr(sub_result, 'content') else sub_result
                                            if isinstance(sub_items, list):
                                                tool_context += f"\n### INHALT VON {subdir}/:\n{json.dumps(sub_items, ensure_ascii=False)}\n"
                                                for sub_item in sub_items:
                                                    if files_read >= 5:
                                                        break
                                                    if not sub_item.endswith("/"):
                                                        file_path = f"{subdir}/{sub_item}"
                                                        try:
                                                            fc = fl.execute("home_read", {"path": file_path})
                                                            fc_content = fc.content if hasattr(fc, 'content') else fc
                                                            tool_context += f"\n### DATEI-INHALT ({file_path}):\n{fc_content}\n"
                                                            files_read += 1
                                                        except Exception:
                                                            pass
                                        except Exception:
                                            pass
                                    else:
                                        file_path = (_list_base + "/" if _list_base else "") + item
                                        try:
                                            fc = fl.execute("home_read", {"path": file_path})
                                            fc_content = fc.content if hasattr(fc, 'content') else fc
                                            if fc_content:
                                                tool_context += f"\n### DATEI-INHALT ({file_path}):\n{fc_content}\n"
                                                files_read += 1
                                        except Exception:
                                            pass
                                if files_read > 0:
                                    log_info(f"[Orchestrator] Home auto-expand: read {files_read} file(s)")
                            except Exception as e:
                                log_warn(f"[Orchestrator] Home auto-expand failed: {e}")

                    # ── Container Session Tracking (stream path) ──
                    container_evt = self._build_container_event_content(
                        tool_name, result, user_text, tool_args,
                        session_id=conversation_id or "",
                    )
                    if container_evt:
                        ws_ev = self._save_container_event("_container_events", container_evt)
                        if ws_ev:
                            yield ("", False, ws_ev)
                        log_info(f"[Orchestrator] Container event: {container_evt['event_type']}")

                except Exception as e:
                    log_error(f"[Orchestrator] Tool {tool_name} failed: {e}")
                    tool_context += f"\n### TOOL-FEHLER ({tool_name}): {str(e)}\n"
                    yield ("", False, {"type": "tool_result", "tool": tool_name, "success": False, "error": str(e)})

        # ═══════════════════════════════════════════════════
        # STEP 2.5: REFLECTION LOOP (Round 2, max 1x)
        # ═══════════════════════════════════════════════════
        _stream_has_failure = bool(tool_context and "TOOL-FEHLER" in tool_context)
        if _stream_has_failure:
            # ── Failure-compact via entry-point (Gap D closed, stream path) ──
            _fail_block_stream = self._build_failure_compact_block(
                conversation_id, len(full_context), _smm_stream
            )
            if _fail_block_stream:
                log_info(f"[CTX] failure-compact injected chars={len(_fail_block_stream)} (via entry-point, stream path)")
                # Prepend to tool_context so it flows into reflection/output.
                # Source registered here; chars are NOT counted here to avoid double-counting:
                # the full tool_context (incl. this block) is measured once at the tool_ctx append below.
                tool_context = _fail_block_stream + tool_context
                ctx_trace_stream["context_sources"].append("failure_ctx")

        if tool_context and "TOOL-FEHLER" in tool_context:
            retry_plan = _reflection.plan_retry(
                tool_context=tool_context,
                user_text=user_text,
                round1_tool_args=_round1_args,
            )
            if retry_plan:
                log_info(f"[ReflectionLoop] === ROUND 2: {len(retry_plan)} alternative(s) ===")
                yield ("", False, {"type": "reflection_start", "count": len(retry_plan)})
                for step in retry_plan:
                    alt_tool = step["tool"]
                    alt_args = step["args"]
                    try:
                        log_info(f"[ReflectionLoop] Versuche: {alt_tool}({alt_args}) | {step['reason']}")
                        alt_result = tool_hub.call_tool(alt_tool, alt_args)
                        alt_str = json.dumps(alt_result, ensure_ascii=False, default=str) if isinstance(alt_result, (dict, list)) else str(alt_result)
                        # Extract content if ToolResult
                        if hasattr(alt_result, 'content') and alt_result.content is not None:
                            alt_str = json.dumps(alt_result.content, ensure_ascii=False, default=str) if isinstance(alt_result.content, (dict, list)) else str(alt_result.content)
                        tool_context += (
                            f"\n### 🔄 REFLECTION ({alt_tool}):\n"
                            f"**Grund:** {step['reason']}\n"
                            f"**Wegen:** {step['original_error']}\n"
                            f"**Ergebnis:** {alt_str}\n"
                        )
                        log_info(f"[ReflectionLoop] {alt_tool} OK: {len(alt_str)} chars")
                        yield ("", False, {"type": "tool_result", "tool": alt_tool, "success": True, "reflection": True})
                    except Exception as re_err:
                        log_warn(f"[ReflectionLoop] {alt_tool} fehlgeschlagen: {re_err}")
                        tool_context += f"\n### 🔄 REFLECTION-FEHLER ({alt_tool}): {re_err}\n"

        # ── Phase 1.5 Commit 2: Clip tool_context before append (small mode) ──
        tool_context = self._clip_tool_context(tool_context, _smm_stream)

        if tool_context:
            full_context = self._append_context_block(
                full_context, tool_context, "tool_ctx", ctx_trace_stream
            )
            verified_plan["_tool_results"] = tool_context
            if _smm_stream:
                log_info(
                    f"[CTX] total context after tool_context: {len(full_context)} chars "
                    f"(tool_context={len(tool_context)}, failure_ctx merged if any)"
                )

            has_failures_or_skips = self._tool_context_has_failures_or_skips(tool_context)
            has_success = self._tool_context_has_success(tool_context)
            if has_failures_or_skips:
                verified_plan["_tool_failure"] = True
            # Confidence Override: only when we have explicit successful tool evidence
            # and no skip/failure markers.
            if has_success and not has_failures_or_skips:
                verified_plan["_tool_confidence"] = "high"
                log_info("[Orchestrator] Tool confidence: HIGH — OutputLayer wird nicht gebremst")

            # WORKSPACE: Save tool execution results as note
            _tool_names = [t["tool"] if isinstance(t, dict) and "tool" in t else str(t) for t in suggested_tools]
            tool_summary = f"**Tools executed:** {', '.join(_tool_names)}\n\n{tool_context[:2000]}"
            ws_event = self._save_workspace_entry(
                conversation_id, tool_summary, "note", "control"
            )
            if ws_event:
                yield ("", False, ws_event)

        # ═══════════════════════════════════════════════════
        # STEP 3: OUTPUT LAYER (STREAMING)
        # ═══════════════════════════════════════════════════
        log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: LAYER 3 OUTPUT")
        log_info("[Orchestrator] === LAYER 3: OUTPUT ===")

        full_response = ""
        first_chunk = True

        # Tool-Confidence Override: LoopEngine überspringen wenn Tools bereits Daten geliefert haben
        if use_loop_engine and verified_plan.get("_tool_confidence") == "high":
            log_info("[Orchestrator] LoopEngine SKIP — Tool-Ergebnisse bereits vorhanden (_tool_confidence=high)")
            use_loop_engine = False

        # ── Phase 1.5 Commit 1: Final hard cap (always active in small mode) ──
        # Falls back to SMALL_MODEL_CHAR_CAP when SMALL_MODEL_FINAL_CAP=0 (no longer optional).
        full_context = self._apply_final_cap(full_context, ctx_trace_stream, _smm_stream, "stream")
        full_context = self._apply_effective_context_guardrail(
            full_context, ctx_trace_stream, _smm_stream, "stream"
        )

        # ── Finalize orchestrator-side trace and hand off to OutputLayer ──
        # [CTX-PRE-OUTPUT]: orchestrator context string before OutputLayer adds persona/instructions/history.
        # [CTX-FINAL] is emitted inside OutputLayer after the full messages array is built.
        ctx_trace_stream["mode"] = self._compute_ctx_mode(ctx_trace_stream, is_loop=use_loop_engine)
        log_info(
            f"[CTX-PRE-OUTPUT] mode={ctx_trace_stream['mode']} "
            f"context_sources={','.join(ctx_trace_stream['context_sources'])} "
            f"context_chars={ctx_trace_stream['context_chars_final']} "
            f"retrieval_count={ctx_trace_stream['retrieval_count']}"
        )
        verified_plan["_ctx_trace"] = ctx_trace_stream
        verified_plan["_response_mode"] = response_mode_stream
        try:
            from config import get_output_timeout_interactive_s, get_output_timeout_deep_s
            verified_plan["_output_time_budget_s"] = (
                get_output_timeout_deep_s()
                if response_mode_stream == "deep"
                else get_output_timeout_interactive_s()
            )
        except Exception:
            pass

        if use_loop_engine:
            # ── LOOP ENGINE: OutputLayer bleibt aktiv, ruft Tools autonom auf ──
            from core.autonomous.loop_engine import LoopEngine
            from config import get_loop_engine_output_char_cap, get_loop_engine_max_predict
            log_info("[Orchestrator] LoopEngine aktiv")
            yield ("", False, {
                "type": "loop_engine_start",
                "complexity": _loop_complexity,
                "sequential": _loop_sequential,
            })
            loop_engine = LoopEngine(model=request.model or None)
            _loop_output_char_cap = int(get_loop_engine_output_char_cap())
            _loop_max_predict = int(get_loop_engine_max_predict())
            log_info(
                f"[Orchestrator] LoopEngine budgets: char_cap={_loop_output_char_cap} "
                f"num_predict={_loop_max_predict}"
            )
            sys_prompt = self.output._build_system_prompt(verified_plan, full_context)
            # [CTX-FINAL] for LoopEngine path: sys_prompt + user_text + initial tool_context
            # (LoopEngine bypasses OutputLayer.generate_stream, so we measure here)
            _loop_initial_chars = len(sys_prompt) + len(user_text) + len(tool_context or "")
            log_info(
                f"[CTX-FINAL] mode={ctx_trace_stream['mode']} "
                f"context_sources={','.join(ctx_trace_stream['context_sources'])} "
                f"payload_chars={_loop_initial_chars} "
                f"retrieval_count={ctx_trace_stream['retrieval_count']}"
            )
            async for le_chunk, le_done, le_meta in loop_engine.run_stream(
                user_text=user_text,
                system_prompt=sys_prompt,
                initial_tool_context=tool_context,
                max_iterations=5,
                output_char_cap=_loop_output_char_cap,
                output_num_predict=_loop_max_predict,
            ):
                if le_meta.get("type") == "content" and le_chunk:
                    if first_chunk:
                        log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: FIRST LOOP CHUNK")
                        first_chunk = False
                    full_response += le_chunk
                    yield (le_chunk, False, {"type": "content"})
                elif le_meta.get("type") not in ("done",):
                    # Pass loop events to frontend (loop_iteration, loop_tool_call, etc.)
                    yield ("", False, le_meta)
        else:
            # ── NORMALER OUTPUT: einmaliger OutputLayer-Call ──
            async for chunk in self.output.generate_stream(
                user_text=user_text,
                verified_plan=verified_plan,
                memory_data=full_context,
                model=request.model
            ):
                if first_chunk:
                    log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: FIRST OUTPUT CHUNK")
                    first_chunk = False
                full_response += chunk
                yield (chunk, False, {"type": "content"})
        
        log_info(f"[Orchestrator] Output: {len(full_response)} chars")
        
        # ═══════════════════════════════════════════════════
        # STEP 4: MEMORY SAVE
        # ═══════════════════════════════════════════════════
        self._save_memory(
            conversation_id=conversation_id,
            answer=full_response,
            verified_plan=verified_plan
        )
        
        # ═══════════════════════════════════════════════════
        # DONE
        # ═══════════════════════════════════════════════════
        # [NEW] Lifecycle Finish
        self.lifecycle.finish_task(req_id_str, {"status": "done", "duration": time.time()-_t0})
        self._post_task_processing()
        
        yield ("", True, {"type": "done", "done_reason": "stop", "memory_used": memory_used, "model": request.model})
        log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: COMPLETE")


    # ===============================================================
    # CHUNKING (moved from bridge.py)
    # ===============================================================

    async def _process_chunked_stream(
        self,
        user_text: str,
        conversation_id: str,
        request: CoreChatRequest
    ) -> AsyncGenerator[Tuple[str, bool, Dict], None]:
        """
        Verarbeitet lange Texte mit MCP document-processor.

        v3 Workflow (MCP-BASED):
        1. Preprocess via MCP (~1 Sek)
        2. Structure Analysis via MCP (~1 Sek)
        3. EIN LLM-Aufruf mit kompakter Summary (~15-20 Sek)
        4. Ergebnis zurueck
        """
        log_info("[Orchestrator-Chunking] v3 MCP-basierte Analyse startet...")

        hub = get_hub()

        # PHASE 1: Preprocessing via MCP
        yield ("", False, {
            "type": "document_analysis_start",
            "message": "Preprocessing document...",
        })

        try:
            preprocess_result = hub.call_tool("preprocess", {
                "text": user_text,
                "add_paragraph_ids": True,
                "normalize_whitespace": True,
                "remove_artifacts": True
            })
            processed_text = preprocess_result.get("text", user_text)
            log_info(f"[Orchestrator-Chunking] Preprocessed: {len(processed_text)} chars")
        except Exception as e:
            log_error(f"[Orchestrator-Chunking] Preprocess failed: {e}, using raw text")
            processed_text = user_text

        # PHASE 2: Structure Analysis via MCP
        yield ("", False, {
            "type": "document_analysis_progress",
            "message": "Analyzing document structure...",
        })

        try:
            structure = hub.call_tool("analyze_structure", {
                "text": processed_text
            })

            log_info(f"[Orchestrator-Chunking] Structure: {structure.get('heading_count', 0)} Headings, "
                    f"{structure.get('code_blocks', 0)} Code-Bloecke, "
                    f"Complexity {structure.get('complexity', 0)}/10")

            compact_summary = self._build_summary_from_structure(structure)

        except Exception as e:
            log_error(f"[Orchestrator-Chunking] Structure analysis failed: {e}")
            structure = {
                "heading_count": 0,
                "code_blocks": 0,
                "complexity": 5,
                "keywords": [],
                "intro": processed_text[:500]
            }
            compact_summary = f"Text ({len(processed_text)} chars)"

        yield ("", False, {
            "type": "document_analysis_done",
            "structure": {
                "total_chars": structure.get("total_chars", len(processed_text)),
                "total_tokens": structure.get("total_tokens", len(processed_text) // 4),
                "total_lines": structure.get("total_lines", processed_text.count('\n')),
                "heading_count": structure.get("heading_count", 0),
                "headings": structure.get("headings", [])[:10],
                "code_blocks": structure.get("code_blocks", 0),
                "code_languages": structure.get("languages", []),
                "keywords": structure.get("keywords", []),
                "estimated_complexity": structure.get("complexity", 5),
            },
            "message": f"Struktur erkannt: {structure.get('heading_count', 0)} Abschnitte, {structure.get('code_blocks', 0)} Code-Bloecke",
        })

        # PHASE 3: EIN LLM-Aufruf mit kompakter Info
        yield ("", False, {
            "type": "thinking_start",
            "message": "Analysiere Inhalt...",
        })

        analysis_prompt = f"""Analysiere folgendes Dokument anhand der Struktur-Uebersicht:

{compact_summary}

Der User hat dieses Dokument gesendet. Was ist sein wahrscheinlicher Intent?
Braucht die Antwort Sequential Thinking (schrittweises Reasoning)?"""

        thinking_result = await self.thinking.analyze(analysis_prompt)

        log_info(f"[Orchestrator-Chunking] ThinkingLayer: intent={thinking_result.get('intent')}, "
                f"needs_sequential={thinking_result.get('needs_sequential_thinking')}")

        yield ("", False, {
            "type": "chunking_done",
            "conversation_id": conversation_id,
            "method": "mcp_v3",
            "aggregated_summary": compact_summary,
            "structure": {
                "headings": structure.get("headings", []),
                "keywords": structure.get("keywords", []),
                "complexity": structure.get("complexity", 5),
            },
            "thinking_result": thinking_result,
            "needs_sequential_any": thinking_result.get('needs_sequential_thinking', False) or thinking_result.get('sequential_thinking_required', False),
            "max_complexity": structure.get("complexity", 5),
        })

    def _build_summary_from_structure(self, structure: Dict) -> str:
        """Build compact summary from MCP structure analysis."""
        lines = []
        lines.append("# Document Overview")
        lines.append(f"- Size: {structure.get('total_chars', 0)} chars, {structure.get('total_tokens', 0)} tokens")
        lines.append(f"- Complexity: {structure.get('complexity', 0)}/10")

        if structure.get('headings'):
            lines.append(f"\n## Structure ({len(structure['headings'])} headings):")
            for h in structure['headings'][:5]:
                lines.append(f"- {h.get('level', 1)*'#'} {h.get('text', '')}")

        if structure.get('keywords'):
            lines.append(f"\n## Keywords: {', '.join(structure['keywords'][:10])}")

        if structure.get('intro'):
            lines.append(f"\n## Intro:\n{structure['intro'][:300]}...")

        return '\n'.join(lines)

    # ===============================================================
    # PRIVATE PIPELINE STEPS
    # ===============================================================

    async def _execute_thinking_layer(self, user_text: str) -> Dict:
        """Execute Thinking Layer (Step 1)."""
        log_info("[Orchestrator] === LAYER 1: THINKING ===")
        thinking_plan = await self.thinking.analyze(user_text)
        
        log_info(f"[Orchestrator-Thinking] intent={thinking_plan.get('intent')}")
        log_info(f"[Orchestrator-Thinking] needs_memory={thinking_plan.get('needs_memory')}")
        log_info(f"[Orchestrator-Thinking] memory_keys={thinking_plan.get('memory_keys')}")
        log_info(f"[Orchestrator-Thinking] hallucination_risk={thinking_plan.get('hallucination_risk')}")
        
        return thinking_plan
    
    async def _execute_control_layer(
        self,
        user_text: str,
        thinking_plan: Dict,
        memory_data: str,
        conversation_id: str
    ) -> Tuple[Dict, Dict]:
        """Execute Control Layer (Step 2)."""
        
        # Skip logic (shared with stream path)
        skip_control, _skip_reason_sync = self._should_skip_control_layer(user_text, thinking_plan)
        if skip_control:
            log_info(f"[Orchestrator] === LAYER 2: CONTROL === SKIPPED ({_skip_reason_sync})")
        
        if thinking_plan.get("_sequential_deferred"):
            log_info(
                f"[Orchestrator] Sequential deferred: "
                f"{thinking_plan.get('_sequential_deferred_reason', 'interactive_mode')}"
            )

        # Sequential Thinking Check (BEFORE Control!)
        if thinking_plan.get("needs_sequential_thinking") or thinking_plan.get("sequential_thinking_required"):
            log_info("[Orchestrator] Sequential Thinking detected - executing BEFORE Control...")
            from config import get_sequential_timeout_s
            _seq_timeout = get_sequential_timeout_s()
            try:
                sequential_result = await asyncio.wait_for(
                    self.control._check_sequential_thinking(
                        user_text=user_text,
                        thinking_plan=thinking_plan
                    ),
                    timeout=float(_seq_timeout),
                )
                if sequential_result:
                    thinking_plan["_sequential_result"] = sequential_result
                    log_info(f"[Orchestrator] Sequential completed: {len(sequential_result.get('steps', []))} steps")
            except asyncio.TimeoutError:
                log_warn(f"[Orchestrator] Sequential timeout after {_seq_timeout}s — continuing without sequential result")
                thinking_plan["_sequential_timed_out"] = True

        if skip_control:
            verified_plan = thinking_plan.copy()
            verified_plan["_verified"] = False
            verified_plan["_skipped"] = True
            verified_plan["_final_instruction"] = ""
            verified_plan["_warnings"] = []
            verification = {"approved": True, "corrections": {}}
        else:
            log_info("[Orchestrator] === LAYER 2: CONTROL ===")
            verification = await self.control.verify(
                user_text,
                thinking_plan,
                memory_data
            )
            log_info(f"[Orchestrator-Control] approved={verification.get('approved')}")
            log_info(f"[Orchestrator-Control] warnings={verification.get('warnings', [])}")
            # Apply corrections
            verified_plan = self.control.apply_corrections(thinking_plan, verification)
            # Skill Confirmation Handling
            if verification.get("_needs_skill_confirmation") and INTENT_SYSTEM_AVAILABLE:
                skill_name = verification.get("_skill_name", "unknown")
                log_info(f"[Orchestrator] Creating SkillCreationIntent for '{skill_name}'")
                
                intent = SkillCreationIntent(
                    skill_name=skill_name,
                    origin=IntentOrigin.USER,
                    reason=verification.get("_cim_decision", {}).get("pattern_id", "control_layer"),
                    user_text=user_text,
                    
                    conversation_id=conversation_id,
                    thinking_plan=thinking_plan,
                    complexity=thinking_plan.get("sequential_complexity", 5)
                )
                store = get_intent_store()
                store.add(intent)
                
                verified_plan["_pending_intent"] = intent.to_dict()
                log_info(f"[Orchestrator] Intent {intent.id[:8]} added to verified_plan")
        
        return verification, verified_plan
    
    async def _execute_output_layer(
        self,
        user_text: str,
        verified_plan: Dict,
        memory_data: str,
        model: str,
        chat_history: list,
        memory_required_but_missing: bool = False
    ) -> str:
        """Execute Output Layer (Step 3)."""
        log_info("[Orchestrator] === LAYER 3: OUTPUT ===")
        
        if memory_required_but_missing:
            log_info("[Orchestrator-Output] WARNING: Memory required but not found!")
        
        answer = await self.output.generate(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=memory_data,
            model=model,
            memory_required_but_missing=memory_required_but_missing,
            chat_history=chat_history
        )
        
        log_info(f"[Orchestrator-Output] Generated {len(answer)} chars")
        return answer
    
    def _save_memory(
        self,
        conversation_id: str,
        verified_plan: Dict,
        answer: str
    ):
        """Save facts and assistant response to memory."""
        
        # Save new facts
        if verified_plan.get("is_new_fact"):
            fact_key = verified_plan.get("new_fact_key")
            fact_value = verified_plan.get("new_fact_value")
            if fact_key and fact_value:
                log_info(f"[Orchestrator-Save] Saving fact: {fact_key}={fact_value}")
                try:
                    fact_args = {
                        "conversation_id": conversation_id,
                        "subject": "Danny",
                        "key": fact_key,
                        "value": fact_value,
                        "layer": "ltm",
                    }
                    call_tool("memory_fact_save", fact_args)
                except Exception as e:
                    log_error(f"[Orchestrator-Save] Error: {e}")
        
        # Autosave assistant response
        # Guard against self-reinforcement of low-quality outputs after failed/skipped tool phases.
        tool_ctx = str(verified_plan.get("_tool_results", "") or "")
        skip_autosave = False
        skip_reason = ""
        if verified_plan.get("_pending_intent"):
            skip_autosave = True
            skip_reason = "pending_intent_confirmation"
        elif verified_plan.get("_tool_failure") or self._tool_context_has_failures_or_skips(tool_ctx):
            skip_autosave = True
            skip_reason = "tool_failure_or_skip"

        if skip_autosave:
            log_warn(f"[Orchestrator-Autosave] Skipped assistant autosave ({skip_reason})")
            return

        try:
            autosave_assistant(
                conversation_id=conversation_id,
                content=answer,
                layer="stm",
            )
        except Exception as e:
            log_error(f"[Orchestrator-Autosave] Error: {e}")
