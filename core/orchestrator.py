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

# Legacy source-inspection contract markers:
# Commit 2 stream parity
# Commit 2 stream parity: Card
# _build_tool_result_card
# _build_tool_result_card
# _build_tool_result_card
# _build_tool_result_card
# _compute_retrieval_policy
# budget exhausted
# budget exhausted

import asyncio
import json
import os
import time
import threading
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Tuple, Dict, Any, Optional, List

from core.models import CoreChatRequest, CoreChatResponse
from core.context_manager import ContextManager, ContextResult
from core.layers.thinking import ThinkingLayer
from core.layers.control import ControlLayer
from core.layers.output import OutputLayer
from core.tone_hybrid import ToneHybridClassifier
from core.query_budget_hybrid import QueryBudgetHybridClassifier
from core.domain_router_hybrid import DomainRouterHybridClassifier
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
from core.tool_intelligence import ToolIntelligenceManager, detect_tool_error
from core.grounding_policy import load_grounding_policy
from core.tool_execution_policy import load_tool_execution_policy
from core.control_decision_utils import (
    build_control_workspace_summary,
    build_done_workspace_summary,
    is_control_hard_block_decision,
    soften_control_deny,
)
from core.control_contract import (
    ControlDecision,
    control_decision_from_plan,
    execution_result_from_plan,
    persist_control_decision,
    persist_execution_result,
    tool_allowed_by_control_decision,
)
from core.plan_runtime_bridge import (
    get_runtime_grounding_evidence,
    get_runtime_grounding_value,
    get_runtime_tool_failure,
    get_runtime_tool_results,
)
from core.plan_cache import make_plan_cache, SqlitePlanCache as _SqlitePlanCache
from core.workspace_event_utils import (
    build_sequential_workspace_summary,
    persist_sequential_workspace_event,
)
from core.archive_embedding_queue import (
    _ArchiveEmbeddingJobQueue,
    get_archive_embedding_queue as _get_archive_embedding_queue,
)
from core.master_settings import get_master_settings
from core.container_state_utils import (
    merge_container_state_from_tool_result,
    normalize_container_entries as util_normalize_container_entries,
    select_preferred_container_id as util_select_preferred_container_id,
    tool_requires_container_id as util_tool_requires_container_id,
)
from core.host_runtime_policy import enforce_host_runtime_exec_first
from core.orchestrator_prompt_utils import (
    expected_home_blueprint_id as util_expected_home_blueprint_id,
    is_rollout_enabled as util_is_rollout_enabled,
    last_assistant_message as util_last_assistant_message,
    looks_like_short_confirmation_followup as util_looks_like_short_confirmation_followup,
    looks_like_short_confirmation_followup_state_only as util_looks_like_short_confirmation_followup_state_only,
    looks_like_short_fact_followup as util_looks_like_short_fact_followup,
    message_content_value as util_message_content_value,
    message_role_value as util_message_role_value,
    normalize_trace_id as util_normalize_trace_id,
    recent_user_messages as util_recent_user_messages,
    safe_str as util_safe_str,
    sanitize_tool_args_for_state as util_sanitize_tool_args_for_state,
)
from core.orchestrator_runtime_utils import (
    build_followup_tool_reuse_specs as util_build_followup_tool_reuse_specs,
    parse_container_list_result_for_selection as util_parse_container_list_result_for_selection,
    should_attempt_followup_tool_reuse as util_should_attempt_followup_tool_reuse,
    stringify_reuse_tool_names as util_stringify_reuse_tool_names,
)
from core.grounding_state_utils import (
    build_grounding_state_payload as util_build_grounding_state_payload,
    count_successful_grounding_evidence as util_count_successful_grounding_evidence,
    extract_recent_grounding_state as util_extract_recent_grounding_state,
    grounding_evidence_has_content as util_grounding_evidence_has_content,
    has_usable_grounding_evidence as util_has_usable_grounding_evidence,
    inject_carryover_grounding_evidence as util_inject_carryover_grounding_evidence,
    select_first_whitelisted_tool_run as util_select_first_whitelisted_tool_run,
)
from core.orchestrator_temporal_utils import (
    infer_time_reference_from_user_text as util_infer_time_reference_from_user_text,
    looks_like_temporal_context_query as util_looks_like_temporal_context_query,
)
from core.orchestrator_policy_signal_utils import (
    ensure_dialogue_controls as util_ensure_dialogue_controls,
    apply_query_budget_to_plan as util_apply_query_budget_to_plan,
    has_memory_recall_signal as util_has_memory_recall_signal,
    has_non_memory_tool_runtime_signal as util_has_non_memory_tool_runtime_signal,
    sanitize_tone_signal as util_sanitize_tone_signal,
    should_force_query_budget_factual_memory as util_should_force_query_budget_factual_memory,
    should_skip_thinking_from_query_budget as util_should_skip_thinking_from_query_budget,
)
from core.orchestrator_precontrol_policy_utils import (
    resolve_precontrol_policy_conflicts as util_resolve_precontrol_policy_conflicts,
)
from core.orchestrator_query_budget_tool_policy_utils import (
    apply_query_budget_tool_policy as util_apply_query_budget_tool_policy,
)
from core.autosave_dedupe import get_autosave_dedupe_guard
from core.embedding_client import embed_text as embed_text_runtime
from core.conversation_consistency_policy import load_conversation_consistency_policy
from core.conversation_consistency import (
    detect_conflicts as util_detect_consistency_conflicts,
    extract_stance_signals as util_extract_stance_signals,
    make_entries as util_make_stance_entries,
    prune_entries as util_prune_stance_entries,
)
from core.orchestrator_plan_schema_utils import (
    coerce_thinking_plan_schema as util_coerce_thinking_plan_schema,
)
from core.orchestrator_control_skip_utils import (
    should_skip_control_layer as util_should_skip_control_layer,
)
from core.orchestrator_grounding_evidence_utils import (
    build_grounding_evidence_entry as util_build_grounding_evidence_entry,
)
from core.orchestrator_hardware_gate_utils import (
    check_hardware_gate_early as util_check_hardware_gate_early,
)
from core.orchestrator_skill_task_utils import (
    sanitize_intent_thinking_plan_for_skill_task as util_sanitize_intent_thinking_plan_for_skill_task,
)
from core.orchestrator_conversation_guard_utils import (
    should_suppress_conversational_tools as util_should_suppress_conversational_tools,
)
from core.orchestrator_tool_args_utils import (
    build_tool_args as util_build_tool_args,
)
from core.orchestrator_tool_validation_utils import (
    validate_tool_args as util_validate_tool_args,
)
from core.orchestrator_tool_execution_sync_utils import (
    execute_tools_sync as util_execute_tools_sync,
)
from core.orchestrator_flow_utils import (
    initialize_pipeline_orchestrator as util_initialize_pipeline_orchestrator,
    build_effective_context as util_build_effective_context,
    check_pending_confirmation as util_check_pending_confirmation,
    process_chunked_stream as util_process_chunked_stream,
    execute_control_layer as util_execute_control_layer,
)
from core.orchestrator_sync_flow_utils import (
    process_request as util_process_request,
)
from core.orchestrator_stream_flow_utils import (
    process_stream_with_events as util_process_stream_with_events,
)
from utils.role_endpoint_resolver import resolve_role_endpoint
from utils.model_runtime_resolver import resolve_runtime_chat_model

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


# Module-level Cache-Instanzen (leben bis Container neugestartet wird)
_thinking_plan_cache = make_plan_cache(ttl_seconds=300, namespace="thinking_plan")      # 5 min
_sequential_result_cache = make_plan_cache(ttl_seconds=600, namespace="sequential_result")  # 10 min


# Patterns für frühes Hardware-Gate (vor Sequential Thinking)
_HARDWARE_GATE_PATTERNS = [
    "30b", "70b", "34b", "65b", "40b",
    "large model", "großes modell", "großes sprachmodell",
    "ollama pull", "modell laden", "modell aktivieren",
    "modell herunterladen", "model load", "model pull",
]
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
        self._log_info_for_utils = log_info
        self._log_warn_for_utils = log_warn
        util_initialize_pipeline_orchestrator(
            self,
            context_manager,
            context_manager_cls=ContextManager,
            thinking_layer_cls=ThinkingLayer,
            control_layer_cls=ControlLayer,
            output_layer_cls=OutputLayer,
            tool_selector_cls=ToolSelector,
            tone_hybrid_cls=ToneHybridClassifier,
            query_budget_hybrid_cls=QueryBudgetHybridClassifier,
            domain_router_hybrid_cls=DomainRouterHybridClassifier,
            get_registry_fn=get_registry,
            task_lifecycle_manager_cls=TaskLifecycleManager,
            get_archive_manager_fn=get_archive_manager,
            tool_intelligence_manager_cls=ToolIntelligenceManager,
            load_tool_execution_policy_fn=load_tool_execution_policy,
            get_master_orchestrator_fn=get_master_orchestrator,
            get_hub_fn=get_hub,
            ollama_base=OLLAMA_BASE,
            lock_factory=threading.Lock,
            log_info_fn=log_info,
        )

    _CONTROL_SKIP_BLOCK_TOOLS = {
        "create_skill",
        "autonomous_skill_task",
        "request_container",
        "exec_in_container",
        "home_write",
        "autonomy_cron_create_job",
        "autonomy_cron_update_job",
        "autonomy_cron_delete_job",
        "autonomy_cron_run_now",
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
    _CONTROL_SKIP_HARD_SAFETY_KEYWORDS = (
        "rm -rf",
        "sudo rm",
        "virus",
        "malware",
        "trojan",
        "ransomware",
        "keylogger",
        "botnet",
        "hack",
        "exploit",
        "passwort auslies",
        "passwörter auslies",
        "passwoerter auslies",
        "delete all files",
        "alle dateien loesch",
        "alle dateien lösch",
    )
    _TOOL_INTENT_KEYWORDS = (
        "tool",
        "tools",
        "skill",
        "skills",
        "cron",
        "cronjob",
        "speicher",
        "speichern",
        "erinner",
        "container",
        "blueprint",
        "run_skill",
        "list_skills",
        "get_system_info",
        "logs",
        "storage",
        "disk",
        "disks",
        "festplatte",
        "festplatten",
        "laufwerk",
        "mount",
    )
    _TOOL_INTENT_WORD_KEYWORDS = frozenset({
        "tool",
        "tools",
        "skill",
        "skills",
        "cron",
        "cronjob",
        "container",
        "blueprint",
        "logs",
        "run_skill",
        "list_skills",
        "get_system_info",
        "storage",
        "disk",
        "disks",
        "mount",
    })
    _TOOL_DOMAIN_TAG_RE = re.compile(
        r"\{(?:tool|domain)\s*[:=]\s*(cronjob|skill|container|mcp_call)\s*\}",
        re.IGNORECASE,
    )
    _TOOL_DOMAIN_TAG_SHORT_RE = re.compile(
        r"\{(cronjob|skill|container|mcp_call)\}",
        re.IGNORECASE,
    )
    _CRON_META_GUARD_MARKERS = (
        "wie fühlst du",
        "wie fuehlst du",
        "wie geht es dir",
        "wie geht's",
        "wie gehts",
        "jetzt wo du",
        "nun da du",
        "was denkst du",
        "was hältst du",
        "was haeltst du",
    )
    _FOLLOWUP_FACT_PREFIXES = (
        "und",
        "und was",
        "und welche",
        "und welcher",
        "und welches",
        "welche",
        "welcher",
        "welches",
        "was sagt",
        "was bedeutet das",
        "was sagt das",
        "davon",
        "darüber",
        "darauf",
    )
    _FOLLOWUP_FACT_MARKERS = (
        "das",
        "diese",
        "dieser",
        "dieses",
        "davon",
        "darüber",
        "darauf",
        "oben",
        "vorhin",
    )
    _FOLLOWUP_CONFIRM_PREFIXES = (
        "ja",
        "ja bitte",
        "bitte",
        "ok",
        "okay",
        "mach",
        "mach mal",
        "gern",
        "gerne",
    )
    _FOLLOWUP_CONFIRM_MARKERS = (
        "ja",
        "bitte testen",
        "teste es",
        "mach weiter",
        "weiter",
        "go",
    )
    _FOLLOWUP_CONFIRM_STATE_ONLY_MARKERS = (
        "mach das",
        "mach bitte",
        "bitte mach",
        "mach weiter",
        "weiter",
        "bitte testen",
        "teste es",
        "testen",
        "leg los",
        "go",
        "ausführen",
        "ausfuehren",
        "starte",
        "mach",
    )
    _FOLLOWUP_ASSISTANT_ACTION_MARKERS = (
        "testen",
        "teste",
        "prüfen",
        "pruefen",
        "ausführen",
        "ausfuehren",
        "ausführen soll",
        "tool",
        "container",
        "ip",
        "gateway",
        "host",
        "exec_in_container",
        "methode",
    )
    _TEMPORAL_CONTEXT_MARKERS = (
        "heute",
        "gestern",
        "vorgestern",
        "protokoll",
        "tagebuch",
        "was haben wir",
        "was hatten wir",
        "was war",
        "besprochen",
        "gesagt",
        "chatverlauf",
    )
    _HOME_CONTAINER_QUERY_MARKERS = (
        "trion home",
        "trion-home",
        "home container",
        "home-container",
        "trion_home",
        "trion home container",
    )
    _HOME_CONTAINER_PURPOSE_MARKERS = (
        "wofür",
        "wofuer",
        "zweck",
        "wozu",
        "was macht",
        "was ist",
        "was weißt du",
        "was weist du",
    )
    # RECALL-Tools (lesen) dürfen NIE supprimiert werden — nur ACTION-Tools (schreiben/ausführen).
    _LOW_SIGNAL_ACTION_TOOLS = frozenset({
        "memory_save",
        "memory_fact_save",
        "analyze",
        "think",
        "think_simple",
    })
    _QUERY_BUDGET_HEAVY_TOOLS = frozenset({
        "analyze",
        "query_skill_knowledge",
        "run_skill",
        "create_skill",
        "autonomous_skill_task",
        "think",
        "think_simple",
    })
    _SKILL_INTENT_KEYWORDS = frozenset({
        "skill",
        "skills",
        "run_skill",
        "create_skill",
        "autonomous_skill_task",
    })
    _SKILL_INTENT_WORD_KEYWORDS = frozenset({
        "skill",
        "skills",
        "run_skill",
        "create_skill",
        "autonomous_skill_task",
    })
    _DOMAIN_CRON_TOOLS = frozenset({
        "autonomy_cron_status",
        "autonomy_cron_list_jobs",
        "autonomy_cron_validate",
        "autonomy_cron_create_job",
        "autonomy_cron_update_job",
        "autonomy_cron_pause_job",
        "autonomy_cron_resume_job",
        "autonomy_cron_run_now",
        "autonomy_cron_delete_job",
        "autonomy_cron_queue",
        "cron_reference_links_list",
    })
    _DOMAIN_SKILL_TOOLS = frozenset({
        "autonomous_skill_task",
        "run_skill",
        "create_skill",
        "list_skills",
        "get_skill_info",
        "validate_skill_code",
        "query_skill_knowledge",
    })
    _DOMAIN_CONTAINER_TOOLS = frozenset({
        "request_container",
        "stop_container",
        "exec_in_container",
        "container_logs",
        "container_stats",
        "container_list",
        "container_inspect",
        "blueprint_list",
        "blueprint_get",
        "blueprint_create",
        "storage_scope_list",
        "storage_scope_upsert",
        "storage_scope_delete",
        "storage_list_disks",
        "storage_get_disk",
        "storage_list_mounts",
        "storage_get_summary",
        "storage_get_policy",
        "storage_set_disk_zone",
        "storage_set_disk_policy",
        "storage_validate_path",
        "storage_list_blocked_paths",
        "storage_add_blacklist_path",
        "storage_remove_blacklist_path",
        "storage_create_service_dir",
        "storage_list_managed_paths",
        "storage_mount_device",
        "storage_format_device",
        "storage_audit_log",
        "list_used_ports",
        "find_free_port",
        "check_port",
        "list_blueprint_ports",
    })
    _CONTAINER_ID_REQUIRED_TOOLS = frozenset({
        "exec_in_container",
        "container_stats",
        "container_logs",
        "container_inspect",
        "stop_container",
    })
    _DOMAIN_CRON_OP_TO_TOOL = {
        "create": "autonomy_cron_create_job",
        "update": "autonomy_cron_update_job",
        "delete": "autonomy_cron_delete_job",
        "run_now": "autonomy_cron_run_now",
        "pause": "autonomy_cron_pause_job",
        "resume": "autonomy_cron_resume_job",
        "queue": "autonomy_cron_queue",
        "status": "autonomy_cron_status",
        "list": "autonomy_cron_list_jobs",
        "validate": "autonomy_cron_validate",
    }
    _DOMAIN_CONTAINER_OP_TO_TOOL = {
        "deploy": "request_container",
        "create_blueprint": "blueprint_create",
        "stop": "stop_container",
        "status": "container_stats",
        "logs": "container_logs",
        "list": "container_list",
        "exec": "exec_in_container",
        "inspect": "container_inspect",
        "ports": "list_used_ports",
    }
    # Backward-compat alias — Referenzen auf _LOW_SIGNAL_TOOLS bleiben stabil.
    _LOW_SIGNAL_TOOLS = _LOW_SIGNAL_ACTION_TOOLS

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
        return util_normalize_trace_id(value)

    @staticmethod
    def _safe_str(value: Any, *, max_len: int = 3000) -> str:
        return util_safe_str(value, max_len=max_len)

    @staticmethod
    def _is_rollout_enabled(rollout_pct: int, seed: str) -> bool:
        return util_is_rollout_enabled(rollout_pct, seed)

    @staticmethod
    def _message_role_value(msg: Any) -> str:
        return util_message_role_value(msg)

    @staticmethod
    def _message_content_value(msg: Any) -> str:
        return util_message_content_value(msg)

    @classmethod
    def _last_assistant_message(cls, chat_history: Optional[list]) -> str:
        return util_last_assistant_message(chat_history)

    @classmethod
    def _recent_user_messages(cls, chat_history: Optional[list], limit: int = 3) -> List[str]:
        return util_recent_user_messages(chat_history, limit=limit)

    @classmethod
    def _looks_like_short_fact_followup(
        cls,
        user_text: str,
        chat_history: Optional[list],
    ) -> bool:
        return util_looks_like_short_fact_followup(
            user_text,
            chat_history,
            prefixes=cls._FOLLOWUP_FACT_PREFIXES,
            markers=cls._FOLLOWUP_FACT_MARKERS,
        )

    @classmethod
    def _looks_like_short_confirmation_followup(
        cls,
        user_text: str,
        chat_history: Optional[list],
    ) -> bool:
        return util_looks_like_short_confirmation_followup(
            user_text,
            chat_history,
            prefixes=cls._FOLLOWUP_CONFIRM_PREFIXES,
            markers=cls._FOLLOWUP_CONFIRM_MARKERS,
            assistant_action_markers=cls._FOLLOWUP_ASSISTANT_ACTION_MARKERS,
        )

    @classmethod
    def _looks_like_short_confirmation_followup_state_only(
        cls,
        user_text: str,
    ) -> bool:
        return util_looks_like_short_confirmation_followup_state_only(
            user_text,
            action_markers=cls._FOLLOWUP_CONFIRM_STATE_ONLY_MARKERS,
        )

    @classmethod
    def _sanitize_tool_args_for_state(cls, value: Any) -> Dict[str, Any]:
        return util_sanitize_tool_args_for_state(value, non_serialized_max_len=200)

    @staticmethod
    def _expected_home_blueprint_id() -> str:
        return util_expected_home_blueprint_id("trion-home")

    def _get_recent_container_state(
        self,
        conversation_id: str,
        history_len: int = 0,
    ) -> Optional[Dict[str, Any]]:
        from config import (
            get_followup_tool_reuse_ttl_s,
            get_followup_tool_reuse_ttl_turns,
        )

        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            return None
        ttl_s = int(get_followup_tool_reuse_ttl_s())
        ttl_turns = int(get_followup_tool_reuse_ttl_turns())
        with self._conversation_container_lock:
            state = self._conversation_container_state.get(conv_id)
            if not isinstance(state, dict):
                return None
            age_s = time.time() - float(state.get("updated_at", 0.0) or 0.0)
            if age_s > ttl_s:
                self._conversation_container_state.pop(conv_id, None)
                return None
            state_history_len = int(state.get("history_len", 0) or 0)
            if history_len > 0 and state_history_len > 0 and history_len >= state_history_len:
                max_delta = max(2, ttl_turns * 2)
                if (history_len - state_history_len) > max_delta:
                    self._conversation_container_state.pop(conv_id, None)
                    return None
            return {
                "last_active_container_id": str(state.get("last_active_container_id", "") or ""),
                "home_container_id": str(state.get("home_container_id", "") or ""),
                "known_containers": list(state.get("known_containers") or []),
                "history_len": state_history_len,
                "updated_at": float(state.get("updated_at", 0.0) or 0.0),
            }

    @staticmethod
    def _normalize_container_entries(rows: Any) -> List[Dict[str, str]]:
        return util_normalize_container_entries(rows, limit=64)

    def _remember_container_state(
        self,
        conversation_id: str,
        *,
        last_active_container_id: str = "",
        home_container_id: str = "",
        known_containers: Optional[List[Dict[str, str]]] = None,
        history_len: int = 0,
    ) -> None:
        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            return
        with self._conversation_container_lock:
            prev = self._conversation_container_state.get(conv_id, {})
            merged_last_active = str(last_active_container_id or prev.get("last_active_container_id", "")).strip()
            merged_home = str(home_container_id or prev.get("home_container_id", "")).strip()
            merged_known = known_containers if isinstance(known_containers, list) else list(prev.get("known_containers") or [])
            self._conversation_container_state[conv_id] = {
                "updated_at": time.time(),
                "history_len": int(history_len or 0),
                "last_active_container_id": merged_last_active,
                "home_container_id": merged_home,
                "known_containers": merged_known[:64],
            }

    def _update_container_state_from_tool_result(
        self,
        conversation_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        *,
        history_len: int = 0,
    ) -> None:
        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            return

        state = self._get_recent_container_state(conv_id, history_len=history_len) or {}
        merged = merge_container_state_from_tool_result(
            state,
            tool_name=tool_name,
            tool_args=tool_args,
            result=result,
            expected_home_blueprint_id=self._expected_home_blueprint_id(),
        )
        self._remember_container_state(
            conv_id,
            last_active_container_id=str(merged.get("last_active_container_id", "")).strip(),
            home_container_id=str(merged.get("home_container_id", "")).strip(),
            known_containers=merged.get("known_containers", []),
            history_len=history_len,
        )

    @classmethod
    def _tool_requires_container_id(cls, tool_name: str) -> bool:
        return util_tool_requires_container_id(tool_name, cls._CONTAINER_ID_REQUIRED_TOOLS)

    @classmethod
    def _select_preferred_container_id(
        cls,
        rows: Any,
        *,
        preferred_ids: Optional[List[str]] = None,
    ) -> str:
        return util_select_preferred_container_id(
            rows,
            expected_home_blueprint_id=cls._expected_home_blueprint_id(),
            preferred_ids=preferred_ids,
        )

    def _resolve_pending_container_id_sync(
        self,
        tool_hub: Any,
        conversation_id: str,
        *,
        preferred_ids: Optional[List[str]] = None,
        history_len: int = 0,
    ) -> Tuple[str, str]:
        try:
            list_result = tool_hub.call_tool("container_list", {})
        except Exception as e:
            return "", f"container_list_failed:{self._safe_str(e, max_len=160)}"

        self._update_container_state_from_tool_result(
            conversation_id,
            "container_list",
            {},
            list_result,
            history_len=history_len,
        )
        selected, parse_err = util_parse_container_list_result_for_selection(
            list_result,
            expected_home_blueprint_id=self._expected_home_blueprint_id(),
            preferred_ids=preferred_ids,
        )
        if parse_err:
            return "", f"container_list_error:{self._safe_str(parse_err, max_len=160)}"
        if selected:
            return selected, ""
        return "", "no_active_container_found"

    async def _resolve_pending_container_id_async(
        self,
        tool_hub: Any,
        conversation_id: str,
        *,
        preferred_ids: Optional[List[str]] = None,
        history_len: int = 0,
    ) -> Tuple[str, str]:
        try:
            if hasattr(tool_hub, "call_tool_async"):
                list_result = await tool_hub.call_tool_async("container_list", {})
            else:
                list_result = await asyncio.to_thread(tool_hub.call_tool, "container_list", {})
        except Exception as e:
            return "", f"container_list_failed:{self._safe_str(e, max_len=160)}"

        self._update_container_state_from_tool_result(
            conversation_id,
            "container_list",
            {},
            list_result,
            history_len=history_len,
        )
        selected, parse_err = util_parse_container_list_result_for_selection(
            list_result,
            expected_home_blueprint_id=self._expected_home_blueprint_id(),
            preferred_ids=preferred_ids,
        )
        if parse_err:
            return "", f"container_list_error:{self._safe_str(parse_err, max_len=160)}"
        if selected:
            return selected, ""
        return "", "no_active_container_found"

    @staticmethod
    def _grounding_evidence_has_content(item: Dict[str, Any]) -> bool:
        return util_grounding_evidence_has_content(item)

    def _get_recent_grounding_state(
        self,
        conversation_id: str,
        history_len: int = 0,
    ) -> Optional[Dict[str, Any]]:
        from config import (
            get_followup_tool_reuse_ttl_s,
            get_followup_tool_reuse_ttl_turns,
        )

        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            return None
        ttl_s = int(get_followup_tool_reuse_ttl_s())
        ttl_turns = int(get_followup_tool_reuse_ttl_turns())
        with self._conversation_grounding_lock:
            state = self._conversation_grounding_state.get(conv_id)
            snapshot, should_drop = util_extract_recent_grounding_state(
                state,
                now_ts=time.time(),
                ttl_s=ttl_s,
                ttl_turns=ttl_turns,
                history_len=history_len,
            )
            if should_drop:
                self._conversation_grounding_state.pop(conv_id, None)
            return snapshot

    def _remember_conversation_grounding_state(
        self,
        conversation_id: str,
        verified_plan: Dict[str, Any],
        *,
        history_len: int = 0,
    ) -> None:
        conv_id = str(conversation_id or "").strip()
        if not conv_id or not isinstance(verified_plan, dict):
            return
        payload = util_build_grounding_state_payload(
            verified_plan,
            sanitize_tool_args=self._sanitize_tool_args_for_state,
            evidence_has_content=self._grounding_evidence_has_content,
            max_evidence=8,
            max_tool_runs=6,
            max_fallback_tool_runs=4,
        )
        if not payload:
            return

        with self._conversation_grounding_lock:
            self._conversation_grounding_state[conv_id] = {
                "updated_at": time.time(),
                "history_len": int(history_len or 0),
                "tool_runs": payload.get("tool_runs", []),
                "evidence": payload.get("evidence", []),
            }

    def _inject_carryover_grounding_evidence(
        self,
        conversation_id: str,
        verified_plan: Dict[str, Any],
        *,
        history_len: int = 0,
    ) -> None:
        if not isinstance(verified_plan, dict):
            return
        state = self._get_recent_grounding_state(conversation_id, history_len=history_len)
        injected = util_inject_carryover_grounding_evidence(
            verified_plan,
            state,
            evidence_has_content=self._grounding_evidence_has_content,
            max_carry_evidence=8,
            max_selected_tools=4,
        )
        if injected:
            log_info("[Orchestrator] Carry-over grounding evidence injected from recent turn")

    def _get_recent_consistency_entries(self, conversation_id: str) -> List[Dict[str, Any]]:
        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            return []
        policy = load_conversation_consistency_policy()
        ttl_s = int(policy.get("history_ttl_s", 3600) or 3600)
        max_entries = int(policy.get("max_entries_per_conversation", 24) or 24)
        with self._conversation_consistency_lock:
            existing = self._conversation_consistency_state.get(conv_id, [])
            pruned = util_prune_stance_entries(
                existing,
                now_ts=time.time(),
                ttl_s=ttl_s,
                max_entries=max_entries,
            )
            if pruned:
                self._conversation_consistency_state[conv_id] = pruned
            else:
                self._conversation_consistency_state.pop(conv_id, None)
            return [dict(x) for x in pruned]

    def _remember_consistency_entries(
        self,
        conversation_id: str,
        entries: List[Dict[str, Any]],
    ) -> None:
        conv_id = str(conversation_id or "").strip()
        if not conv_id or not entries:
            return
        policy = load_conversation_consistency_policy()
        ttl_s = int(policy.get("history_ttl_s", 3600) or 3600)
        max_entries = int(policy.get("max_entries_per_conversation", 24) or 24)
        with self._conversation_consistency_lock:
            merged = list(self._conversation_consistency_state.get(conv_id, [])) + list(entries)
            self._conversation_consistency_state[conv_id] = util_prune_stance_entries(
                merged,
                now_ts=time.time(),
                ttl_s=ttl_s,
                max_entries=max_entries,
            )

    async def _apply_conversation_consistency_guard(
        self,
        *,
        conversation_id: str,
        verified_plan: Dict[str, Any],
        answer: str,
    ) -> str:
        policy = load_conversation_consistency_policy()
        if not bool(policy.get("enabled", True)):
            return answer
        answer_text = str(answer or "")
        if not answer_text.strip():
            return answer_text

        current_signals = util_extract_stance_signals(answer_text)
        if not current_signals:
            return answer_text

        prior_entries = self._get_recent_consistency_entries(conversation_id)
        current_embedding: Optional[List[float]] = None
        if bool(policy.get("embedding_enable", True)):
            try:
                current_embedding = await embed_text_runtime(answer_text, timeout_s=2.4)
            except Exception:
                current_embedding = None

        conflicts = util_detect_consistency_conflicts(
            prior_entries=prior_entries,
            current_signals=current_signals,
            current_embedding=current_embedding,
            similarity_threshold=float(policy.get("embedding_similarity_threshold", 0.78) or 0.78),
        )
        if not conflicts:
            entries = util_make_stance_entries(
                signals=current_signals,
                embedding=current_embedding,
                now_ts=time.time(),
            )
            self._remember_consistency_entries(conversation_id, entries)
            return answer_text

        evidence_count = int(
            get_runtime_grounding_value(
                verified_plan,
                key="successful_evidence",
                legacy_key="_grounding_successful_evidence",
                default=0,
            )
            or 0
        )
        min_evidence = int(policy.get("min_successful_evidence_on_stance_change", 1) or 1)
        requires_evidence = bool(policy.get("require_evidence_on_stance_change", True))
        if requires_evidence and evidence_count < min_evidence:
            evidence = get_runtime_grounding_evidence(verified_plan)
            fallback_mode = str(policy.get("fallback_mode", "explicit_uncertainty") or "explicit_uncertainty")
            fallback = self.output._build_grounding_fallback(
                evidence if isinstance(evidence, list) else [],
                mode=fallback_mode,
            )
            repaired = str(fallback or "").strip()
            if repaired:
                verified_plan["_consistency_conflict_detected"] = True
                verified_plan["_consistency_conflicts"] = conflicts[:4]
                verified_plan["_grounding_violation_detected"] = True
                verified_plan["_grounded_fallback_used"] = True
                log_warn(
                    "[Orchestrator] Consistency guard fallback: "
                    f"conflicts={len(conflicts)} evidence={evidence_count}<{min_evidence}"
                )
                repaired_signals = util_extract_stance_signals(repaired)
                repaired_embedding: Optional[List[float]] = None
                if bool(policy.get("embedding_enable", True)):
                    try:
                        repaired_embedding = await embed_text_runtime(repaired, timeout_s=2.4)
                    except Exception:
                        repaired_embedding = None
                entries = util_make_stance_entries(
                    signals=repaired_signals,
                    embedding=repaired_embedding,
                    now_ts=time.time(),
                )
                self._remember_consistency_entries(conversation_id, entries)
                return repaired

        entries = util_make_stance_entries(
            signals=current_signals,
            embedding=current_embedding,
            now_ts=time.time(),
        )
        self._remember_consistency_entries(conversation_id, entries)
        return answer_text

    def _has_usable_grounding_evidence(self, verified_plan: Dict[str, Any]) -> bool:
        return util_has_usable_grounding_evidence(
            verified_plan,
            evidence_has_content=self._grounding_evidence_has_content,
        )

    async def _maybe_auto_recover_grounding_once(
        self,
        *,
        conversation_id: str,
        user_text: str,
        verified_plan: Dict[str, Any],
        thinking_plan: Dict[str, Any],
        history_len: int,
        session_id: str = "",
    ) -> str:
        from config import (
            get_grounding_auto_recovery_enable,
            get_grounding_auto_recovery_timeout_s,
            get_grounding_auto_recovery_whitelist,
        )

        if not get_grounding_auto_recovery_enable():
            return ""
        if not isinstance(verified_plan, dict):
            return ""
        if verified_plan.get("_grounding_auto_recovery_attempted"):
            return ""
        if not bool(verified_plan.get("is_fact_query", False)):
            return ""
        if self._has_usable_grounding_evidence(verified_plan):
            return ""

        state = self._get_recent_grounding_state(conversation_id, history_len=history_len)
        if not state:
            return ""
        whitelist = {str(x).strip() for x in get_grounding_auto_recovery_whitelist() if str(x).strip()}
        if not whitelist:
            return ""

        candidate = util_select_first_whitelisted_tool_run(state, whitelist)
        if not candidate:
            return ""

        tool_name = str(candidate.get("tool_name", "")).strip()
        tool_args = self._sanitize_tool_args_for_state(candidate.get("args") or {})
        if not tool_name:
            return ""

        spec = {"tool": tool_name, "args": tool_args}
        verified_plan["_grounding_auto_recovery_attempted"] = True
        verified_plan["needs_chat_history"] = True
        log_info(f"[Orchestrator] Auto-recovery grounding re-run: tool={tool_name}")
        timeout_s = float(get_grounding_auto_recovery_timeout_s())
        try:
            recovery_ctx = await asyncio.wait_for(
                asyncio.to_thread(
                    self._execute_tools_sync,
                    [spec],
                    user_text,
                    {},
                    control_decision=control_decision_from_plan(
                        verified_plan,
                        default_approved=False,
                    ),
                    time_reference=thinking_plan.get("time_reference"),
                    thinking_suggested_tools=thinking_plan.get("suggested_tools", []),
                    blueprint_gate_blocked=False,
                    blueprint_router_id=None,
                    blueprint_suggest_msg="",
                    session_id=session_id or "",
                    verified_plan=verified_plan,
                ),
                timeout=timeout_s,
            )
            if recovery_ctx:
                verified_plan["_grounding_auto_recovery_used"] = True
                return str(recovery_ctx)
        except asyncio.TimeoutError:
            log_warn(
                f"[Orchestrator] Auto-recovery skipped (timeout after {timeout_s:.1f}s) tool={tool_name}"
            )
        except Exception as e:
            log_warn(f"[Orchestrator] Auto-recovery failed tool={tool_name}: {e}")
        return ""

    def _resolve_followup_tool_reuse(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        *,
        conversation_id: str = "",
        chat_history: Optional[list] = None,
    ) -> List[Any]:
        from config import get_followup_tool_reuse_enable

        explicit_tool_intent = self._contains_explicit_tool_intent(user_text)
        short_fact_followup = self._looks_like_short_fact_followup(user_text, chat_history)
        short_confirmation_followup = self._looks_like_short_confirmation_followup(
            user_text, chat_history
        )
        should_attempt = util_should_attempt_followup_tool_reuse(
            followup_enabled=get_followup_tool_reuse_enable(),
            verified_plan=verified_plan,
            explicit_tool_intent=explicit_tool_intent,
            short_fact_followup=short_fact_followup,
            short_confirmation_followup=short_confirmation_followup,
        )
        history_len = len(chat_history) if isinstance(chat_history, list) else 0
        state = None
        if not should_attempt and not explicit_tool_intent:
            if self._looks_like_short_confirmation_followup_state_only(user_text):
                state = self._get_recent_grounding_state(conversation_id, history_len=history_len)
                if isinstance(state, dict) and list(state.get("tool_runs") or []):
                    should_attempt = True
                    verified_plan["_followup_tool_reuse_state_fallback"] = True
                    log_info(
                        "[Orchestrator] Follow-up tool reuse fallback active "
                        "(state-only confirmation)"
                    )
        if not should_attempt:
            return []

        if state is None:
            state = self._get_recent_grounding_state(conversation_id, history_len=history_len)
        if not state:
            return []

        out = util_build_followup_tool_reuse_specs(
            state,
            sanitize_tool_args=self._sanitize_tool_args_for_state,
            max_tools=2,
        )

        if out:
            verified_plan["needs_chat_history"] = True
            verified_plan["_followup_tool_reuse_active"] = True
            log_info(
                f"[Orchestrator] Follow-up tool reuse active: "
                f"{util_stringify_reuse_tool_names(out)}"
            )
        return out

    @classmethod
    def _looks_like_temporal_context_query(
        cls,
        user_text: str,
        chat_history: Optional[list] = None,
    ) -> bool:
        return util_looks_like_temporal_context_query(
            user_text,
            chat_history,
            temporal_markers=cls._TEMPORAL_CONTEXT_MARKERS,
            short_followup_checker=lambda text, history: cls._looks_like_short_fact_followup(text, history),
            recent_user_messages_getter=lambda history, limit: cls._recent_user_messages(history, limit=limit),
        )

    @staticmethod
    def _infer_time_reference_from_user_text(user_text: str) -> Optional[str]:
        return util_infer_time_reference_from_user_text(user_text)

    def _apply_temporal_context_fallback(
        self,
        user_text: str,
        thinking_plan: Dict[str, Any],
        chat_history: Optional[list] = None,
    ) -> None:
        from config import get_daily_context_followup_enable

        if not get_daily_context_followup_enable():
            return
        if not isinstance(thinking_plan, dict):
            return
        if thinking_plan.get("time_reference"):
            return
        if not self._looks_like_temporal_context_query(user_text, chat_history):
            return

        inferred = self._infer_time_reference_from_user_text(user_text) or "today"
        thinking_plan["time_reference"] = inferred
        thinking_plan["needs_chat_history"] = True
        log_info(f"[Orchestrator] temporal context fallback: time_reference={inferred}")

    @staticmethod
    def _sanitize_tone_signal(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return util_sanitize_tone_signal(raw)

    async def _classify_tone_signal(
        self,
        user_text: str,
        messages: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        try:
            signal = await self.tone_hybrid.classify(user_text, messages=messages)
            return self._sanitize_tone_signal(signal)
        except Exception as e:
            log_warn(f"[Orchestrator] ToneHybrid fallback: {e}")
            return self._sanitize_tone_signal(None)

    async def _classify_query_budget_signal(
        self,
        user_text: str,
        *,
        selected_tools: Optional[List[Any]] = None,
        tone_signal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from config import get_query_budget_enable

        if not get_query_budget_enable():
            return {}
        try:
            signal = await self.query_budget.classify(
                user_text,
                selected_tools=selected_tools,
                tone_signal=tone_signal,
            )
            if isinstance(signal, dict) and signal:
                log_info(
                    "[Orchestrator] query_budget "
                    f"type={signal.get('query_type')} "
                    f"intent={signal.get('intent_hint')} "
                    f"complexity={signal.get('complexity_signal')} "
                    f"budget={signal.get('response_budget')} "
                    f"tool_hint={signal.get('tool_hint') or '-'} "
                    f"skip_candidate={bool(signal.get('skip_thinking_candidate'))} "
                    f"conf={signal.get('confidence')} src={signal.get('source')}"
                )
            return signal if isinstance(signal, dict) else {}
        except Exception as e:
            log_warn(f"[Orchestrator] QueryBudget fallback: {e}")
            return {}

    async def _classify_domain_signal(
        self,
        user_text: str,
        *,
        selected_tools: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        from config import get_domain_router_enable

        if not get_domain_router_enable():
            return {}
        try:
            signal = await self.domain_router.classify(
                user_text,
                selected_tools=selected_tools,
            )
            if isinstance(signal, dict) and signal:
                signal = self._maybe_downgrade_cron_create_signal(user_text, signal)
                log_info(
                    "[Orchestrator] domain_router "
                    f"tag={signal.get('domain_tag')} "
                    f"locked={bool(signal.get('domain_locked'))} "
                    f"operation={signal.get('operation')} "
                    f"conf={signal.get('confidence')} src={signal.get('source')}"
                )
                if bool(signal.get("cron_create_downgraded")):
                    log_info("[Orchestrator] domain_router cron create downgraded to status (meta/no-schedule guard)")
            return signal if isinstance(signal, dict) else {}
        except Exception as e:
            log_warn(f"[Orchestrator] DomainRouter fallback: {e}")
            return {}

    def _seed_tool_for_domain_route(
        self,
        route: Optional[Dict[str, Any]],
        *,
        user_text: str = "",
        suggested_tools: Optional[List[Any]] = None,
    ) -> str:
        if not isinstance(route, dict):
            return ""
        tag = str(route.get("domain_tag") or "").strip().upper()
        if tag == "CRONJOB":
            op = str(route.get("operation") or "").strip().lower()
            return self._DOMAIN_CRON_OP_TO_TOOL.get(op, "autonomy_cron_status")
        if tag == "SKILL":
            return "autonomous_skill_task"
        if tag == "CONTAINER":
            op = str(route.get("operation") or "").strip().lower()
            if op == "unknown" and self._looks_like_host_runtime_lookup(user_text):
                return "exec_in_container"
            if op == "unknown":
                for tool in suggested_tools or []:
                    name = self._extract_tool_name(tool).strip().lower()
                    if name in self._DOMAIN_CONTAINER_TOOLS:
                        return name
            return self._DOMAIN_CONTAINER_OP_TO_TOOL.get(op, "container_list")
        return ""

    @staticmethod
    def _looks_like_host_runtime_lookup(user_text: str) -> bool:
        lower = str(user_text or "").strip().lower()
        if not lower:
            return False
        has_target = any(
            token in lower
            for token in (
                "host server",
                "host-server",
                "server",
                "host",
                "ip adresse",
                "ip-adresse",
                "ip address",
            )
        )
        if not has_target:
            return False
        return any(
            token in lower
            for token in (
                "find",
                "finden",
                "ermittel",
                "heraus",
                "auslesen",
                "check",
                "prüf",
                "pruef",
                "zeige",
                "gib",
            )
        )

    def _apply_domain_route_to_plan(
        self,
        thinking_plan: Dict[str, Any],
        signal: Optional[Dict[str, Any]],
        *,
        user_text: str = "",
    ) -> Dict[str, Any]:
        plan = thinking_plan if isinstance(thinking_plan, dict) else {}
        if not isinstance(signal, dict) or not signal:
            return plan

        route = dict(signal)
        plan["_domain_route"] = route

        domain_locked = bool(route.get("domain_locked"))
        domain_tag = str(route.get("domain_tag") or "").strip().upper()
        if not domain_locked or domain_tag not in {"CRONJOB", "SKILL", "CONTAINER"}:
            return plan

        if domain_tag == "CRONJOB":
            allowed = self._DOMAIN_CRON_TOOLS
        elif domain_tag == "SKILL":
            allowed = self._DOMAIN_SKILL_TOOLS
        else:
            allowed = self._DOMAIN_CONTAINER_TOOLS

        existing = plan.get("suggested_tools", [])
        existing_list = existing if isinstance(existing, list) else []
        existing_allowed = [
            tool
            for tool in existing_list
            if self._extract_tool_name(tool).strip().lower() in allowed
        ]
        if existing_allowed:
            plan["suggested_tools"] = existing_allowed
            plan["_domain_tool_seeded"] = False
        else:
            seed_tool = self._seed_tool_for_domain_route(
                route,
                user_text=user_text,
                suggested_tools=existing_list,
            )
            if seed_tool:
                plan["suggested_tools"] = [seed_tool]
                plan["_domain_tool_seeded"] = True

        if domain_tag == "CRONJOB":
            # Hard guard for ControlLayer skill-confirmation fallback.
            plan["_domain_skill_confirmation_disabled"] = True
        return plan

    def _apply_domain_tool_policy(
        self,
        verified_plan: Dict[str, Any],
        suggested_tools: List[Any],
        *,
        user_text: str = "",
        prefix: str = "[Orchestrator]",
    ) -> List[Any]:
        if not isinstance(verified_plan, dict):
            return suggested_tools

        route = verified_plan.get("_domain_route")
        if not isinstance(route, dict):
            return suggested_tools
        if not bool(route.get("domain_locked")):
            return suggested_tools

        domain_tag = str(route.get("domain_tag") or "").strip().upper()
        if domain_tag == "CRONJOB":
            allowed = self._DOMAIN_CRON_TOOLS
        elif domain_tag == "SKILL":
            allowed = self._DOMAIN_SKILL_TOOLS
        elif domain_tag == "CONTAINER":
            allowed = self._DOMAIN_CONTAINER_TOOLS
        else:
            return suggested_tools

        before = len(suggested_tools or [])
        filtered = [
            tool
            for tool in (suggested_tools or [])
            if self._extract_tool_name(tool).strip().lower() in allowed
        ]
        dropped = max(0, before - len(filtered))

        if not filtered:
            if domain_tag == "SKILL" and bool(verified_plan.get("_skill_gate_blocked")):
                log_info(
                    f"{prefix} Domain gate skipped SKILL reseed: "
                    f"reason={verified_plan.get('_skill_gate_reason') or 'skill_gate_blocked'}"
                )
            else:
                seed_tool = self._seed_tool_for_domain_route(
                    route,
                    user_text=user_text,
                    suggested_tools=suggested_tools,
                )
                if seed_tool and seed_tool in allowed:
                    filtered = [seed_tool]

        if dropped or before == 0:
            verified_plan["_domain_gate"] = {
                "domain_tag": domain_tag,
                "dropped": dropped,
                "kept": [self._extract_tool_name(t) for t in filtered],
            }
            log_info(
                f"{prefix} Domain gate applied: tag={domain_tag} dropped={dropped} "
                f"kept={verified_plan['_domain_gate']['kept']}"
            )

        if domain_tag == "CONTAINER" and self._looks_like_host_runtime_lookup(user_text):
            has_exec = any(
                self._extract_tool_name(tool).strip().lower() == "exec_in_container"
                for tool in filtered
            )
            has_request = any(
                self._extract_tool_name(tool).strip().lower() == "request_container"
                for tool in filtered
            )
            if has_exec and has_request:
                filtered = [
                    tool
                    for tool in filtered
                    if self._extract_tool_name(tool).strip().lower() != "request_container"
                ]
                log_info(f"{prefix} Container runtime fast-path: dropped request_container (exec already present)")
            elif has_request and not has_exec:
                filtered = [
                    tool
                    for tool in filtered
                    if self._extract_tool_name(tool).strip().lower() != "request_container"
                ]
                filtered.insert(0, "exec_in_container")
                log_info(f"{prefix} Container runtime fast-path: replaced request_container with exec_in_container")
        return filtered

    def _should_skip_thinking_from_query_budget(
        self,
        signal: Optional[Dict[str, Any]],
        *,
        user_text: str,
        forced_mode: str = "",
    ) -> bool:
        from config import (
            get_query_budget_skip_thinking_enable,
            get_query_budget_skip_thinking_min_confidence,
        )
        return util_should_skip_thinking_from_query_budget(
            signal,
            user_text=user_text,
            forced_mode=forced_mode,
            skip_enabled=bool(get_query_budget_skip_thinking_enable()),
            min_confidence=float(get_query_budget_skip_thinking_min_confidence()),
            is_explicit_deep_request=self._is_explicit_deep_request,
            contains_explicit_tool_intent=self._contains_explicit_tool_intent,
        )

    def _apply_query_budget_to_plan(
        self,
        thinking_plan: Dict[str, Any],
        signal: Optional[Dict[str, Any]],
        *,
        user_text: str = "",
    ) -> Dict[str, Any]:
        from config import get_query_budget_enable
        return util_apply_query_budget_to_plan(
            thinking_plan,
            signal,
            user_text=user_text,
            query_budget_enabled=bool(get_query_budget_enable()),
            should_force_factual_memory=lambda text, plan, sig: self._should_force_query_budget_factual_memory(
                user_text=text,
                thinking_plan=plan,
                signal=sig,
            ),
        )

    def _should_force_query_budget_factual_memory(
        self,
        *,
        user_text: str,
        thinking_plan: Dict[str, Any],
        signal: Dict[str, Any],
    ) -> bool:
        return util_should_force_query_budget_factual_memory(
            user_text=user_text,
            thinking_plan=thinking_plan,
            signal=signal,
            tool_domain_tag=self._extract_tool_domain_tag(user_text),
            has_non_memory_tool_runtime_signal_fn=self._has_non_memory_tool_runtime_signal,
            has_memory_recall_signal_fn=self._has_memory_recall_signal,
        )

    @staticmethod
    def _has_memory_recall_signal(text: str) -> bool:
        return util_has_memory_recall_signal(text)

    @staticmethod
    def _has_non_memory_tool_runtime_signal(text: str) -> bool:
        return util_has_non_memory_tool_runtime_signal(text)

    def _resolve_precontrol_policy_conflicts(
        self,
        user_text: str,
        thinking_plan: Dict[str, Any],
        *,
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        """
        Resolve deterministic conflicts after QueryBudget+DomainRouter mutation.

        Priority:
          domain-locked tool execution > query-budget factual memory force.
        """
        from config import (
            get_policy_conflict_resolver_enable,
            get_policy_conflict_resolver_rollout_pct,
        )

        rollout_enabled = self._is_rollout_enabled(
            get_policy_conflict_resolver_rollout_pct(),
            conversation_id or user_text,
        )
        out, meta = util_resolve_precontrol_policy_conflicts(
            user_text,
            thinking_plan,
            resolver_enabled=bool(get_policy_conflict_resolver_enable()),
            rollout_enabled=bool(rollout_enabled),
            has_memory_recall_signal_fn=self._has_memory_recall_signal,
            contains_explicit_tool_intent_fn=self._contains_explicit_tool_intent,
            looks_like_host_runtime_lookup_fn=self._looks_like_host_runtime_lookup,
            has_non_memory_tool_runtime_signal_fn=self._has_non_memory_tool_runtime_signal,
            extract_tool_name_fn=self._extract_tool_name,
        )
        if bool(meta.get("resolved")):
            log_info(
                "[Orchestrator] Policy conflict resolved: "
                f"domain={meta.get('domain_tag') or '-'} reason={meta.get('reason') or '-'}"
            )
        return out

    def _apply_query_budget_tool_policy(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        suggested_tools: List[Any],
        *,
        prefix: str = "[Orchestrator]",
    ) -> List[Any]:
        from config import (
            get_query_budget_enable,
            get_query_budget_max_tools_factual_low,
        )
        filtered, policy = util_apply_query_budget_tool_policy(
            user_text,
            verified_plan,
            suggested_tools,
            query_budget_enabled=bool(get_query_budget_enable()),
            max_tools_factual_low=int(get_query_budget_max_tools_factual_low()),
            heavy_tools=self._QUERY_BUDGET_HEAVY_TOOLS,
            contains_explicit_tool_intent_fn=self._contains_explicit_tool_intent,
            is_explicit_deep_request_fn=self._is_explicit_deep_request,
            is_explicit_think_request_fn=self._is_explicit_think_request,
            extract_tool_name_fn=self._extract_tool_name,
        )
        if isinstance(policy, dict):
            verified_plan["_query_budget_policy"] = dict(policy)
            query_type = str(policy.get("query_type") or "")
            complexity = str(policy.get("complexity_signal") or "")
            confidence = float(policy.get("confidence", 0.0) or 0.0)
            dropped = int(policy.get("dropped", 0) or 0)
            reasons = list(policy.get("reasons") or [])
            log_info(
                f"{prefix} QueryBudget policy applied: "
                f"type={query_type} complexity={complexity} conf={confidence:.2f} "
                f"dropped={dropped} reasons={reasons}"
            )
        return filtered

    def _ensure_dialogue_controls(
        self,
        thinking_plan: Dict[str, Any],
        tone_signal: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        try:
            from config import get_tone_signal_override_confidence
            override_threshold = float(get_tone_signal_override_confidence())
        except Exception:
            override_threshold = 0.82
        return util_ensure_dialogue_controls(
            thinking_plan,
            tone_signal,
            override_threshold=override_threshold,
        )

    def _coerce_thinking_plan_schema(
        self,
        thinking_plan: Dict[str, Any],
        *,
        user_text: str = "",
    ) -> Dict[str, Any]:
        from config import get_memory_keys_max_per_request

        return util_coerce_thinking_plan_schema(
            thinking_plan,
            user_text=user_text,
            max_memory_keys_per_request=int(get_memory_keys_max_per_request()),
            contains_explicit_tool_intent_fn=self._contains_explicit_tool_intent,
            has_memory_recall_signal_fn=self._has_memory_recall_signal,
        )

    @staticmethod
    def _contains_keyword_intent(
        text: str,
        keyword: str,
        *,
        whole_word: bool = False,
    ) -> bool:
        if not text or not keyword:
            return False
        if not whole_word:
            return keyword in text
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(keyword)}(?![A-Za-z0-9_])"
        return re.search(pattern, text) is not None

    def _contains_explicit_tool_intent(self, user_text: str) -> bool:
        lower = (user_text or "").lower()
        if self._extract_tool_domain_tag(lower):
            return True
        for tok in self._TOOL_INTENT_KEYWORDS:
            if self._contains_keyword_intent(
                lower,
                tok,
                whole_word=tok in self._TOOL_INTENT_WORD_KEYWORDS,
            ):
                return True
        return False

    def _contains_explicit_skill_intent(self, user_text: str) -> bool:
        lower = (user_text or "").lower()
        if self._extract_tool_domain_tag(lower) == "SKILL":
            return True
        for tok in self._SKILL_INTENT_KEYWORDS:
            if self._contains_keyword_intent(
                lower,
                tok,
                whole_word=tok in self._SKILL_INTENT_WORD_KEYWORDS,
            ):
                return True
        return False

    @classmethod
    def _extract_tool_domain_tag(cls, text: str) -> str:
        raw = str(text or "")
        m = cls._TOOL_DOMAIN_TAG_RE.search(raw)
        if not m:
            m = cls._TOOL_DOMAIN_TAG_SHORT_RE.search(raw)
        if not m:
            return ""
        return str(m.group(1) or "").strip().upper()

    @classmethod
    def _has_cron_schedule_signal(
        cls,
        user_text: str,
        route: Optional[Dict[str, Any]] = None,
    ) -> bool:
        text = str(user_text or "").lower()
        route = route if isinstance(route, dict) else {}
        if str(route.get("cron_expression_hint") or "").strip():
            return True
        if str(route.get("one_shot_at_hint") or "").strip():
            return True
        if str(route.get("schedule_mode_hint") or "").strip().lower() in {"one_shot", "recurring"}:
            return True
        if re.search(
            r"(?:in|nach|um|at)\s+\d{1,4}\s*(?:sek|sekunden|s|min|minuten|minute|h|std|stunden|stunde)\b",
            text,
        ):
            return True
        return False

    @classmethod
    def _is_explicit_cron_create_intent(
        cls,
        user_text: str,
        route: Optional[Dict[str, Any]] = None,
    ) -> bool:
        text = str(user_text or "").lower()
        if not text:
            return False
        if any(marker in text for marker in cls._CRON_META_GUARD_MARKERS):
            return False
        create_markers = (
            "erstelle",
            "erstell",
            "anlege",
            "anleg",
            "create",
            "setze auf",
            "schedule",
            "richte ein",
            "einrichten",
        )
        if not any(marker in text for marker in create_markers):
            return False
        return cls._has_cron_schedule_signal(text, route)

    def _maybe_downgrade_cron_create_signal(
        self,
        user_text: str,
        signal: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(signal, dict):
            return signal
        tag = str(signal.get("domain_tag") or "").strip().upper()
        op = str(signal.get("operation") or "").strip().lower()
        if tag != "CRONJOB" or op != "create":
            return signal
        if self._is_explicit_cron_create_intent(user_text, signal):
            return signal
        patched = dict(signal)
        patched["operation"] = "status"
        patched["cron_create_downgraded"] = True
        patched["reason"] = (
            f"{str(signal.get('reason') or '').strip()}, cron:create->status_guard"
        ).strip(", ")
        return patched

    def _should_suppress_conversational_tools(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
    ) -> bool:
        return util_should_suppress_conversational_tools(
            user_text,
            verified_plan,
            tool_execution_policy=self.tool_execution_policy or {},
            contains_explicit_tool_intent_fn=self._contains_explicit_tool_intent,
        )

    def _sanitize_intent_thinking_plan_for_skill_task(self, thinking_plan: Any) -> Dict[str, Any]:
        return util_sanitize_intent_thinking_plan_for_skill_task(
            thinking_plan,
            safe_str_fn=lambda value, max_len: self._safe_str(value, max_len=max_len),
            extract_suggested_tool_names_fn=self._extract_suggested_tool_names,
        )

    def _should_skip_control_layer(self, user_text: str, thinking_plan: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Unified skip policy for sync + stream to avoid drift.

        Returns:
            (skip_control, reason)
        """
        try:
            policy = load_grounding_policy()
            force_verify_fact = bool(
                ((policy or {}).get("control") or {}).get("force_verify_for_fact_query", True)
            )
        except Exception:
            force_verify_fact = True
        return util_should_skip_control_layer(
            user_text,
            thinking_plan,
            enable_control_layer=bool(ENABLE_CONTROL_LAYER),
            skip_control_on_low_risk=bool(SKIP_CONTROL_ON_LOW_RISK),
            force_verify_fact=bool(force_verify_fact),
            suggested_tool_names=self._extract_suggested_tool_names(thinking_plan),
            control_skip_block_tools=tuple(self._CONTROL_SKIP_BLOCK_TOOLS),
            control_skip_block_keywords=self._CONTROL_SKIP_BLOCK_KEYWORDS,
            control_skip_hard_safety_keywords=self._CONTROL_SKIP_HARD_SAFETY_KEYWORDS,
        )

    @staticmethod
    def _build_grounding_evidence_entry(
        tool_name: str,
        raw_result: str,
        status: str,
        ref_id: str,
    ) -> Dict[str, Any]:
        return util_build_grounding_evidence_entry(
            tool_name,
            raw_result,
            status,
            ref_id,
        )

    @staticmethod
    def _count_successful_grounding_evidence(
        verified_plan: Dict[str, Any],
        allowed_statuses: Optional[List[str]] = None,
    ) -> int:
        return util_count_successful_grounding_evidence(
            verified_plan,
            allowed_statuses=allowed_statuses,
        )

    # ===============================================================
    # HARDWARE GATE EARLY CHECK
    # ===============================================================

    def _check_hardware_gate_early(self, user_text: str, thinking_plan: Dict) -> Optional[str]:
        """
        Schneller Pre-Check BEVOR Sequential Thinking läuft.
        Gibt Block-Nachricht zurück wenn gefährliche Anfrage erkannt, sonst None.
        Spart 20-40s Sequential Thinking bei Anfragen die sowieso geblockt werden.
        """
        def _get_gpu_status() -> str:
            hub = get_hub()
            hub.initialize()
            gpu_result = hub.call_tool("get_system_info", {"type": "gpu"})
            if isinstance(gpu_result, dict):
                return str(gpu_result.get("output", gpu_result))
            if isinstance(gpu_result, str):
                return gpu_result
            return str(gpu_result or "")

        return util_check_hardware_gate_early(
            user_text,
            thinking_plan,
            hardware_gate_patterns=_HARDWARE_GATE_PATTERNS,
            get_gpu_status_fn=_get_gpu_status,
            required_tool="autonomous_skill_task",
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

    @classmethod
    def _is_home_container_info_query(cls, user_text: str) -> bool:
        text = str(user_text or "").strip().lower()
        if not text:
            return False
        has_home_marker = any(marker in text for marker in cls._HOME_CONTAINER_QUERY_MARKERS)
        if not has_home_marker:
            return False
        return any(marker in text for marker in cls._HOME_CONTAINER_PURPOSE_MARKERS) or "container" in text

    def _prioritize_home_container_tools(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        suggested_tools: List[Any],
        *,
        prefix: str = "[Orchestrator]",
    ) -> List[Any]:
        """
        Harden tool strategy for questions about TRION home containers.
        If the plan only suggests home_read/home_list-like tools, prepend container discovery.
        """
        if not isinstance(verified_plan, dict):
            return suggested_tools
        if not bool(verified_plan.get("is_fact_query", False)):
            return suggested_tools
        if not self._is_home_container_info_query(user_text):
            return suggested_tools

        tool_names = [self._extract_tool_name(t).lower() for t in (suggested_tools or [])]
        has_container_discovery = any(name in {"container_list", "container_inspect"} for name in tool_names)
        if has_container_discovery:
            return suggested_tools

        adjusted: List[Any] = ["container_list"]
        seen = {"container_list"}
        has_home_reader = False
        for tool in suggested_tools or []:
            name = self._extract_tool_name(tool).strip().lower()
            if not name or name in seen:
                continue
            if name == "query_skill_knowledge":
                # Skill-template retrieval is low-value noise for container-purpose questions.
                continue
            if name == "home_read":
                has_home_reader = True
                if isinstance(tool, dict):
                    args = dict(tool.get("args", {}) or {})
                    if not str(args.get("path", "")).strip():
                        args["path"] = "."
                    adjusted.append({"tool": "home_read", "args": args})
                else:
                    adjusted.append({"tool": "home_read", "args": {"path": "."}})
                seen.add(name)
                continue
            adjusted.append(tool)
            seen.add(name)

        if not has_home_reader:
            adjusted.append({"tool": "home_read", "args": {"path": "."}})

        log_info(
            f"{prefix} Home-container routing override: "
            f"{[self._extract_tool_name(t) for t in adjusted]}"
        )
        verified_plan["needs_chat_history"] = True
        return adjusted

    @staticmethod
    def _recover_home_read_directory_with_fast_lane(
        dir_path: str,
        *,
        max_files: int = 5,
    ) -> Tuple[bool, str]:
        """
        home_read fallback when a directory path was provided.
        Returns (success, recovered_payload_text).
        """
        path = str(dir_path or ".").strip() or "."
        try:
            from core.tools.fast_lane.executor import FastLaneExecutor
            fl = FastLaneExecutor()
            sub_result = fl.execute("home_list", {"path": path})
            sub_items = sub_result.content if hasattr(sub_result, "content") else sub_result
            if not isinstance(sub_items, list):
                return False, ""

            files_read = 0
            parts: List[str] = [
                f"home_read recovery for directory '{path}'",
                "listing: " + json.dumps(sub_items, ensure_ascii=False),
            ]
            for sub_item in sub_items:
                if files_read >= max_files:
                    break
                item = str(sub_item or "").strip()
                if not item or item.endswith("/"):
                    continue
                fp = item if path in (".", "") else f"{path}/{item}"
                try:
                    fc = fl.execute("home_read", {"path": fp})
                    fc_content = fc.content if hasattr(fc, "content") else fc
                    text = str(fc_content or "").strip()
                    if not text:
                        continue
                    parts.append(f"file[{fp}]: {text}")
                    files_read += 1
                except Exception:
                    continue

            if files_read <= 0:
                return True, "\n".join(parts)
            parts.append(f"files_read: {files_read}")
            return True, "\n".join(parts)
        except Exception:
            return False, ""

    @staticmethod
    def _sanitize_skill_name_candidate(raw_name: Any) -> str:
        candidate = str(raw_name or "").strip().strip("`\"'.,:;!?()[]{}")
        if not candidate:
            return ""
        candidate = candidate.replace("-", "_")
        candidate = re.sub(r"[^A-Za-z0-9_]", "_", candidate)
        candidate = re.sub(r"_+", "_", candidate).strip("_")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,63}", candidate):
            return ""
        return candidate.lower()

    def _extract_requested_skill_name(self, user_text: str) -> str:
        text = str(user_text or "").strip()
        if not text:
            return ""

        patterns = [
            r"(?i)\brun_skill\s+([A-Za-z][A-Za-z0-9_-]{2,63})\b",
            r"(?i)\b(?:führe|fuehre|run|execute|starte|start)\s+(?:den\s+|die\s+|das\s+)?skill\s+([A-Za-z][A-Za-z0-9_-]{2,63})\b",
            r"(?i)\bskill\s+([A-Za-z][A-Za-z0-9_-]{2,63})\s+(?:aus|ausführen|ausfuehren|run|starten|execute)\b",
            r"(?i)\b(?:skill|funktion)\s+(?:namens|name|named|called)\s+[`\"']?([A-Za-z][A-Za-z0-9_-]{2,63})[`\"']?",
        ]
        stopwords = {
            "skill",
            "run_skill",
            "ausfuehren",
            "ausführen",
            "execute",
            "run",
            "start",
            "starte",
            "fuehre",
            "führe",
            "bitte",
        }
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
            if not match:
                continue
            candidate = self._sanitize_skill_name_candidate(match.group(1))
            if candidate and candidate not in stopwords:
                return candidate
        return ""

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
            if self._extract_tool_name(t) in {"think", "think_simple"}:
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

    def _resolve_runtime_output_model(self, requested_model: str) -> Tuple[str, Dict[str, Any]]:
        """
        Resolve a runtime-safe output model against the effective output endpoint.
        Keeps adapter input unchanged, but prevents invalid model identifiers from
        causing avoidable /api/chat 404 responses.
        """
        from config import get_output_model, get_output_provider

        requested = str(requested_model or "").strip()
        fallback = str(get_output_model() or "").strip()
        provider = str(get_output_provider() or "ollama").strip().lower()

        # Only local Ollama provider should be normalized against /api/tags.
        # Cloud providers must keep the selected provider-model pair unchanged.
        if provider != "ollama":
            resolved = requested or fallback
            resolution = {
                "requested_model": requested,
                "resolved_model": resolved,
                "fallback_model": fallback,
                "endpoint": "cloud",
                "tags_ok": False,
                "available_count": 0,
                "used_fallback": bool(resolved and resolved != requested),
                "reason": "provider_passthrough_non_ollama",
                "provider": provider,
            }
            if resolved != requested:
                log_warn(
                    f"[ModelResolver] output model fallback requested='{requested or '<empty>'}' "
                    f"resolved='{resolved or '<empty>'}' reason={resolution['reason']} provider={provider}"
                )
            else:
                log_info(
                    f"[ModelResolver] output model accepted requested='{requested or '<empty>'}' "
                    f"reason={resolution['reason']} provider={provider}"
                )
            return resolved, resolution

        try:
            route = resolve_role_endpoint("output", default_endpoint=self.ollama_base)
            endpoint = str(route.get("endpoint") or self.ollama_base or "").strip()
        except Exception as e:
            log_warn(f"[ModelResolver] role endpoint resolution failed: {e}")
            endpoint = str(self.ollama_base or "").strip()

        resolution = resolve_runtime_chat_model(
            requested_model=requested,
            endpoint=endpoint,
            fallback_model=fallback,
        )
        resolved = str(resolution.get("resolved_model") or "").strip()
        if not resolved:
            resolved = fallback or requested
            resolution["resolved_model"] = resolved
            resolution["reason"] = "resolver_empty_fallback_applied"

        if resolved != requested:
            log_warn(
                f"[ModelResolver] output model adjusted requested='{requested or '<empty>'}' "
                f"resolved='{resolved or '<empty>'}' reason={resolution.get('reason')} "
                f"endpoint={resolution.get('endpoint') or 'unknown'} "
                f"available_count={resolution.get('available_count', 0)}"
            )
        else:
            log_info(
                f"[ModelResolver] output model accepted requested='{requested or '<empty>'}' "
                f"endpoint={resolution.get('endpoint') or 'unknown'} "
                f"available_count={resolution.get('available_count', 0)}"
            )
        return resolved, resolution

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
        control_decision: Optional[ControlDecision] = None,
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
                if not tool_allowed_by_control_decision(control_decision, tool_name):
                    log_warn(f"{prefix} Gate override tool blocked by control_decision: {tool_name}")
                    continue
                decisions[tool_name] = self._build_tool_args(tool_name, user_text, verified_plan=verified_plan)
            return decisions

        try:
            raw_decisions = await self.control.decide_tools(user_text, verified_plan)
            for item in raw_decisions or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                if not tool_allowed_by_control_decision(control_decision, name):
                    log_warn(f"{prefix} decide_tools emitted non-allowed tool; dropped: {name}")
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
        control_decision: Optional[ControlDecision] = None,
        stream: bool = False,
        enable_skill_trigger_router: bool = False,
        conversation_id: str = "",
        chat_history: Optional[list] = None,
    ) -> List[Any]:
        """
        Build final suggested_tools list with parity across sync and stream:
        ControlLayer authority -> Thinking fallback -> keyword fallback (+ optional trigger router).
        """
        prefix = "[Orchestrator-Stream]" if stream else "[Orchestrator]"
        decisions = control_tool_decisions or {}
        has_control_decisions = bool(decisions)
        if isinstance(control_decision, ControlDecision) and not control_decision.approved:
            verified_plan["_selected_tools_for_prompt"] = []
            log_info(f"{prefix} Tool execution suppressed (control_decision.approved=false)")
            return []
        suppress_low_signal_tools = self._should_suppress_conversational_tools(
            user_text, verified_plan
        )

        if decisions:
            suggested_tools = list(decisions.keys())
            log_info(f"{prefix} ControlLayer tools (authoritative): {suggested_tools}")
        else:
            suggested_tools = verified_plan.get("suggested_tools", [])
            if suggested_tools:
                log_info(f"{prefix} Fallback: ThinkingLayer suggested_tools: {suggested_tools}")

            # Confirmation follow-up override: prefer recent successful tool reuse
            # over fresh weak routing for short confirmations like "ja bitte testen".
            if self._looks_like_short_confirmation_followup(user_text, chat_history):
                followup_tools = self._resolve_followup_tool_reuse(
                    user_text,
                    verified_plan,
                    conversation_id=conversation_id,
                    chat_history=chat_history,
                )
                if followup_tools:
                    suggested_tools = self._normalize_tools(followup_tools)
                    if isinstance(control_decision, ControlDecision):
                        suggested_tools = [
                            t for t in suggested_tools
                            if tool_allowed_by_control_decision(control_decision, self._extract_tool_name(t))
                        ]
                    log_info(f"{prefix} Confirmation follow-up reuse: {suggested_tools}")
                    verified_plan["needs_chat_history"] = True
                    verified_plan["_selected_tools_for_prompt"] = [
                        t["tool"] if isinstance(t, dict) and "tool" in t else str(t)
                        for t in suggested_tools
                    ]
                    return suggested_tools

        # Validate + Normalize: filters invalid tools, maps skill names -> run_skill.
        suggested_tools = self._normalize_tools(suggested_tools)
        if isinstance(control_decision, ControlDecision):
            suggested_tools = [
                t for t in suggested_tools
                if tool_allowed_by_control_decision(control_decision, self._extract_tool_name(t))
            ]
        suggested_tools = self._prioritize_home_container_tools(
            user_text,
            verified_plan,
            suggested_tools,
            prefix=prefix,
        )
        if has_control_decisions:
            log_info(f"{prefix} Post-control tool policies bypassed (Control authority)")
        else:
            suggested_tools = self._apply_query_budget_tool_policy(
                user_text,
                verified_plan,
                suggested_tools,
                prefix=prefix,
            )
            suggested_tools = self._apply_domain_tool_policy(
                verified_plan,
                suggested_tools,
                user_text=user_text,
                prefix=prefix,
            )

        if suppress_low_signal_tools and suggested_tools and not has_control_decisions:
            policy = self.tool_execution_policy or {}
            conv_cfg = policy.get("conversational_guard", {}) if isinstance(policy, dict) else {}
            suppressed_exec_tools = {
                str(name).strip().lower()
                for name in conv_cfg.get("suppress_tools", [])
                if str(name).strip()
            }
            suppressed_tools = {str(t).strip().lower() for t in self._LOW_SIGNAL_ACTION_TOOLS}.union(suppressed_exec_tools)
            before = len(suggested_tools)
            suggested_tools = [
                tool
                for tool in suggested_tools
                if self._extract_tool_name(tool).lower() not in suppressed_tools
            ]
            dropped = before - len(suggested_tools)
            if dropped:
                log_info(
                    f"{prefix} Suppressed conversational tools for turn: dropped={dropped}"
                )
        elif suppress_low_signal_tools and suggested_tools and has_control_decisions:
            log_info(f"{prefix} Conversational suppress bypassed (Control authority)")

        if not suggested_tools:
            followup_tools = self._resolve_followup_tool_reuse(
                user_text,
                verified_plan,
                conversation_id=conversation_id,
                chat_history=chat_history,
            )
            if followup_tools:
                suggested_tools = self._normalize_tools(followup_tools)
                if isinstance(control_decision, ControlDecision):
                    suggested_tools = [
                        t for t in suggested_tools
                        if tool_allowed_by_control_decision(control_decision, self._extract_tool_name(t))
                    ]
                log_info(f"{prefix} Follow-up tool reuse: {suggested_tools}")
                verified_plan["needs_chat_history"] = True
                verified_plan["_selected_tools_for_prompt"] = [
                    t["tool"] if isinstance(t, dict) and "tool" in t else str(t)
                    for t in suggested_tools
                ]
                return suggested_tools
            if suppress_low_signal_tools:
                verified_plan["_selected_tools_for_prompt"] = []
                log_info(f"{prefix} Tool fallback suppressed for conversational turn")
                return []
            suggested_tools = self._detect_tools_by_keyword(user_text)
            if suggested_tools:
                suggested_tools = self._normalize_tools(suggested_tools)
                if isinstance(control_decision, ControlDecision):
                    suggested_tools = [
                        t for t in suggested_tools
                        if tool_allowed_by_control_decision(control_decision, self._extract_tool_name(t))
                    ]
                log_info(f"{prefix} Last-resort keyword fallback: {suggested_tools}")

        if enable_skill_trigger_router and not suggested_tools:
            if self._contains_explicit_skill_intent(user_text):
                trigger_matches = self._detect_skill_by_trigger(user_text)
                if trigger_matches:
                    suggested_tools = self._normalize_tools(trigger_matches)
                    if isinstance(control_decision, ControlDecision):
                        suggested_tools = [
                            t for t in suggested_tools
                            if tool_allowed_by_control_decision(control_decision, self._extract_tool_name(t))
                        ]
                    log_info(f"[Orchestrator] Skill Trigger Router: {trigger_matches}")
            else:
                log_info("[Orchestrator] Skill Trigger Router skipped (no explicit skill intent)")

        if not has_control_decisions:
            suggested_tools = self._apply_domain_tool_policy(
                verified_plan,
                suggested_tools,
                user_text=user_text,
                prefix=prefix,
            )

        _host_runtime_requested = self._looks_like_host_runtime_lookup(user_text)
        if not has_control_decisions:
            _host_tools = enforce_host_runtime_exec_first(
                user_text=user_text,
                suggested_tools=suggested_tools,
                looks_like_host_runtime_lookup_fn=self._looks_like_host_runtime_lookup,
                extract_tool_name_fn=self._extract_tool_name,
            )
            if _host_runtime_requested:
                verified_plan["_host_runtime_chain_applied"] = True
            if _host_tools != list(suggested_tools or []):
                log_info(
                    f"{prefix} Host-runtime deterministic chain applied: "
                    f"{[self._extract_tool_name(t) for t in _host_tools]}"
                )
                suggested_tools = _host_tools

        # OutputLayer prompt hygiene: pass only request-scoped selected tools.
        verified_plan["_selected_tools_for_prompt"] = [
            t["tool"] if isinstance(t, dict) and "tool" in t else str(t)
            for t in suggested_tools
        ]
        return suggested_tools

    def _detect_tools_by_keyword(self, user_text: str) -> list:
        """Keyword-based tool detection fallback when Thinking suggests none."""
        user_lower = user_text.lower()
        if any(kw in user_lower for kw in [
            "festplatte", "festplatten", "laufwerk", "laufwerke",
            "storage", "disk", "disks", "mount", "mounts", "speicherplatz",
        ]):
            if any(kw in user_lower for kw in ["summary", "übersicht", "uebersicht", "kapazität", "kapazitaet", "frei", "belegt"]):
                return ["storage_get_summary"]
            if any(kw in user_lower for kw in ["mount", "mounts", "eingehängt", "eingehaengt"]):
                return ["storage_list_mounts"]
            if any(kw in user_lower for kw in ["policy", "richtlinie", "zone"]):
                return ["storage_get_policy"]
            if any(kw in user_lower for kw in ["blacklist", "blocked paths", "gesperrt", "blockiert"]):
                return ["storage_list_blocked_paths"]
            if any(kw in user_lower for kw in ["managed paths", "verwaltete pfade", "managed"]):
                return ["storage_list_managed_paths"]
            if any(kw in user_lower for kw in ["audit", "änderungen", "aenderungen", "verlauf", "log"]):
                return ["storage_audit_log"]
            return ["storage_list_disks"]
        if any(kw in user_lower for kw in [
            "grafikkarte", "gpu", "vram", "hardware", "systemhardware", "welche karte"
        ]):
            return [{"tool": "run_skill", "args": {"name": "system_hardware_info", "action": "run", "args": {}}}]
        if any(kw in user_lower for kw in ["skill", "skills", "fähigkeit"]):
            if any(kw in user_lower for kw in ["zeig", "list", "welche", "hast du", "installiert", "verfügbar"]):
                return ["list_skills"]
            elif any(kw in user_lower for kw in ["erstell", "create", "bau", "mach"]):
                return ["autonomous_skill_task"]
        elif self._is_home_container_info_query(user_lower):
            return ["container_list", {"tool": "home_read", "args": {"path": "."}}]
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
            "container_list", "container_inspect",
            "home_read", "home_write", "home_list",
            # Skill-Tools: immer durchlassen (MCP via skill-server)
            "autonomous_skill_task", "run_skill", "create_skill",
            "list_skills", "get_skill_info", "validate_skill_code",
            # Cron-Tools: deterministic domain routing
            "autonomy_cron_status", "autonomy_cron_list_jobs", "autonomy_cron_validate",
            "autonomy_cron_create_job", "autonomy_cron_update_job",
            "autonomy_cron_pause_job", "autonomy_cron_resume_job",
            "autonomy_cron_run_now", "autonomy_cron_delete_job",
            "autonomy_cron_queue", "cron_reference_links_list",
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

    @staticmethod
    def _extract_cron_job_id_from_text(user_text: str, verified_plan: Optional[Dict[str, Any]]) -> str:
        route = (verified_plan or {}).get("_domain_route", {}) if isinstance(verified_plan, dict) else {}
        hinted = str((route or {}).get("cron_job_id_hint") or "").strip().lower()
        if re.fullmatch(r"[a-f0-9]{12}", hinted):
            return hinted
        m = re.search(r"\b([a-f0-9]{12})\b", str(user_text or "").lower())
        return str(m.group(1)).lower() if m else ""

    @staticmethod
    def _extract_cron_expression_from_text(user_text: str, verified_plan: Optional[Dict[str, Any]]) -> str:
        route = (verified_plan or {}).get("_domain_route", {}) if isinstance(verified_plan, dict) else {}
        hinted = str((route or {}).get("cron_expression_hint") or "").strip()
        if hinted:
            return hinted

        lower = str(user_text or "").lower()
        m = re.search(r"(?<!\S)([\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+)(?!\S)", lower)
        if m:
            return str(m.group(1) or "").strip()
        m = re.search(r"(?:jede|alle)\s+(\d{1,3})\s*(?:min|minuten|minute)\b", lower)
        if m:
            n = max(1, min(59, int(m.group(1))))
            return f"*/{n} * * * *"
        m = re.search(r"(?:in|nach)\s+(\d{1,3})\s*(?:min|minuten|minute)\b", lower)
        if m:
            n = max(1, min(59, int(m.group(1))))
            return f"*/{n} * * * *"
        m = re.search(r"(?:einmal|once)\s+in\s+(\d{1,3})\s*(?:min|minuten|minute)\b", lower)
        if m:
            n = max(1, min(59, int(m.group(1))))
            return f"*/{n} * * * *"
        if "jede minute" in lower or "every minute" in lower:
            return "*/1 * * * *"
        if "jede stunde" in lower or "every hour" in lower:
            return "0 * * * *"
        return "*/15 * * * *"

    @staticmethod
    def _extract_one_shot_run_at_from_text(user_text: str, verified_plan: Optional[Dict[str, Any]]) -> str:
        route = (verified_plan or {}).get("_domain_route", {}) if isinstance(verified_plan, dict) else {}
        hinted = str((route or {}).get("one_shot_at_hint") or "").strip()
        if hinted:
            return hinted

        lower = str(user_text or "").lower()
        now = datetime.utcnow()
        m = re.search(
            r"(?:in|nach)\s+(\d{1,4}|einer|einem|ein|one)\s*"
            r"(sek|sekunde|sekunden|seconds?|s|min|minute|minuten|minutes?|h|std|stunde|stunden|hours?|tage?|days?)\b",
            lower,
        )
        if m:
            raw_n = str(m.group(1) or "").strip()
            if raw_n in {"einer", "einem", "ein", "one"}:
                amount = 1
            else:
                amount = max(1, int(raw_n))
            unit = str(m.group(2) or "").strip().lower()
            if unit.startswith(("sek", "s")):
                run_at = now + timedelta(seconds=amount)
            elif unit.startswith(("h", "std", "stun")):
                run_at = now + timedelta(hours=amount)
            elif unit.startswith(("tag", "day")):
                run_at = now + timedelta(days=amount)
            else:
                run_at = now + timedelta(minutes=amount)
            # Minute-granular scheduler: always round up to next minute boundary.
            # Avoids near-past one-shot timestamps when request latency is high.
            run_at = (run_at + timedelta(minutes=1)).replace(second=0, microsecond=0)
            return run_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        m = re.search(r"(?:heute|today)\s*(?:um|at)?\s*(\d{1,2})[:.](\d{2})\b", lower)
        if m:
            hour = max(0, min(23, int(m.group(1))))
            minute = max(0, min(59, int(m.group(2))))
            run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if run_at <= now:
                run_at = run_at + timedelta(days=1)
            return run_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        return ""

    def _extract_cron_schedule_from_text(
        self,
        user_text: str,
        verified_plan: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        route = (verified_plan or {}).get("_domain_route", {}) if isinstance(verified_plan, dict) else {}
        mode_hint = str((route or {}).get("schedule_mode_hint") or "").strip().lower()
        lower = str(user_text or "").lower()

        schedule_mode = "unknown"
        if mode_hint in {"one_shot", "recurring"}:
            schedule_mode = mode_hint
        else:
            one_shot_markers = ("einmalig", "nur einmal", "einmal", "one-time", "once")
            recurring_markers = ("jede ", "alle ", "täglich", "taeglich", "wöchentlich", "woechentlich", "every ")
            has_one_shot = any(marker in lower for marker in one_shot_markers)
            has_recurring = any(marker in lower for marker in recurring_markers)
            if has_one_shot and not has_recurring:
                schedule_mode = "one_shot"
            elif has_recurring and not has_one_shot:
                schedule_mode = "recurring"

        cron_expr = self._extract_cron_expression_from_text(user_text, verified_plan)
        run_at = self._extract_one_shot_run_at_from_text(user_text, verified_plan)

        if schedule_mode == "one_shot" and not run_at:
            # deterministic fallback for explicit one-shot wording without parseable datetime.
            fallback = (datetime.utcnow().replace(second=0, microsecond=0) + timedelta(minutes=1))
            run_at = fallback.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        if schedule_mode == "unknown":
            schedule_mode = "one_shot" if run_at else "recurring"

        if schedule_mode == "one_shot":
            # keep cron field for backward compatibility / schema compatibility.
            cron_expr = cron_expr or "*/15 * * * *"
        else:
            cron_expr = cron_expr or "*/15 * * * *"
            run_at = ""

        return {
            "schedule_mode": schedule_mode,
            "cron": cron_expr,
            "run_at": run_at,
        }

    @staticmethod
    def _build_cron_name(user_text: str) -> str:
        lower = str(user_text or "").strip().lower()
        if not lower:
            return "trion-cron-job"
        cleaned = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
        if not cleaned:
            cleaned = "trion-cron-job"
        return f"cron-{cleaned[:40]}"

    @staticmethod
    def _looks_like_self_state_request(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        low = raw.lower()
        if "wie dein tag war" in low or "wie dein tag ist" in low:
            return True
        if "wie es dir geht" in low:
            return True
        if "wie du dich" in low and ("fühl" in low or "fuehl" in low or "feel" in low):
            return True
        return False

    @staticmethod
    def _build_cron_objective(user_text: str) -> str:
        text = str(user_text or "").strip()
        lower = text.lower()
        if PipelineOrchestrator._looks_like_self_state_request(text):
            return f"self_state_report::{text[:220]}"
        if any(tok in lower for tok in ("erinner", "remind", "erinnerung")):
            reminder_text = ""
            m = re.search(r"mir\s+zu\s+sagen[:,]?\s*(.+)$", text, flags=re.IGNORECASE)
            if m:
                reminder_text = str(m.group(1) or "").strip()
            if not reminder_text:
                m = re.search(
                    r"(?:erinnere?\s+(?:mich|mir)|remind\s+me)\s*(?:daran)?[:,]?\s*(.+)$",
                    text,
                    flags=re.IGNORECASE,
                )
                if m:
                    reminder_text = str(m.group(1) or "").strip()
            reminder_text = reminder_text.strip(" .,!:;")
            if not reminder_text:
                reminder_text = "Cronjob funktioniert?"
            return f"user_reminder::{reminder_text[:220]}"
        if any(tok in lower for tok in ("cleanup", "bereinigen", "aufräumen", "aufraeumen")):
            return "cleanup status summary"
        if any(tok in lower for tok in ("backup", "sichern", "archiv")):
            return "backup status summary"
        if text:
            return f"user_request::{text[:220]}"
        return ""

    @staticmethod
    def _extract_direct_cron_reminder_text(objective: str) -> str:
        txt = str(objective or "").strip()
        low = txt.lower()
        if low.startswith("user_reminder::"):
            rem = txt.split("::", 1)[1].strip()
            return rem[:180] if rem else "Cronjob funktioniert?"
        return ""

    @staticmethod
    def _extract_cron_ack_message_from_objective(objective: str) -> str:
        txt = str(objective or "").strip()
        low = txt.lower()
        if low.startswith("user_reminder::"):
            rem = txt.split("::", 1)[1].strip()
            return rem[:180] if rem else "Cronjob funktioniert?"
        if low.startswith("self_state_report::"):
            return "Selbststatus beim Trigger ausgeben."
        if low.startswith("user_request::"):
            req = txt.split("::", 1)[1].strip()
            if PipelineOrchestrator._looks_like_self_state_request(req):
                return "Selbststatus beim Trigger ausgeben."
            return req[:180] if req else "Autonomes Ziel ausführen."
        return "Autonomes Ziel ausführen."

    @staticmethod
    def _format_utc_compact(raw_iso: str) -> str:
        raw = str(raw_iso or "").strip()
        if not raw:
            return ""
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_utc = dt.astimezone(timezone.utc)
            return dt_utc.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return raw

    def _build_direct_cron_create_response(
        self,
        result: Any,
        tool_args: Dict[str, Any],
        conversation_id: str,
    ) -> str:
        payload = result.content if isinstance(result, ToolResult) else result
        if not isinstance(payload, dict):
            return ""
        is_err, _ = detect_tool_error(payload)
        if is_err:
            return ""

        job_id = str(payload.get("id") or payload.get("cron_job_id") or "").strip()
        name = str(payload.get("name") or tool_args.get("name") or "cron-job").strip() or "cron-job"
        mode = str(payload.get("schedule_mode") or tool_args.get("schedule_mode") or "recurring").strip().lower()
        run_at = str(payload.get("run_at") or tool_args.get("run_at") or "").strip()
        cron_expr = str(payload.get("cron") or tool_args.get("cron") or "").strip()
        objective = str(payload.get("objective") or tool_args.get("objective") or "").strip()
        effective_conv = str(
            payload.get("conversation_id") or tool_args.get("conversation_id") or conversation_id or ""
        ).strip()

        id_part = f" `{job_id}`" if job_id else ""
        if mode == "one_shot":
            run_at_label = self._format_utc_compact(run_at) or "bald (UTC)"
            reminder = self._extract_cron_ack_message_from_objective(objective)
            return (
                f"Cronjob erstellt{id_part}: `{name}`. "
                f"Einmalige Ausführung um {run_at_label}. "
                f"Rückmeldung: \"{reminder}\"."
            )

        cron_label = cron_expr or "*/15 * * * *"
        if effective_conv:
            return (
                f"Cronjob erstellt{id_part}: `{name}`. "
                f"Wiederholend mit `{cron_label}` für Chat `{effective_conv}`."
            )
        return f"Cronjob erstellt{id_part}: `{name}`. Wiederholend mit `{cron_label}`."

    def _bind_cron_conversation_id(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        conversation_id: str,
    ) -> None:
        if str(tool_name or "").strip() != "autonomy_cron_create_job":
            return
        if not isinstance(tool_args, dict):
            return
        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            return
        prev = str(tool_args.get("conversation_id") or "").strip()
        if prev != conv_id:
            tool_args["conversation_id"] = conv_id
            if prev:
                log_info(
                    "[Orchestrator] cron conversation_id override: "
                    f"{prev} -> {conv_id}"
                )

    @staticmethod
    def _suggest_cron_expression_for_min_interval(min_interval_s: int) -> str:
        min_s = max(60, int(min_interval_s or 60))
        # Prefer minute granularity when possible.
        if min_s <= 59 * 60:
            minutes = max(1, (min_s + 59) // 60)
            return f"*/{minutes} * * * *"
        # Fall back to hour step.
        if min_s <= 23 * 3600:
            hours = max(1, (min_s + 3599) // 3600)
            return f"0 */{hours} * * *"
        # Last fallback: day step.
        days = max(1, (min_s + 86399) // 86400)
        return f"0 0 */{days} * *"

    @staticmethod
    def _extract_interval_hint_from_cron(expr: str) -> Dict[str, int]:
        raw = str(expr or "").strip()
        if not raw:
            return {"minutes": 0}
        m = re.match(r"^\*/(\d{1,3})\s+\*\s+\*\s+\*\s+\*$", raw)
        if m:
            return {"minutes": max(1, int(m.group(1)))}
        m = re.match(r"^0\s+\*/(\d{1,2})\s+\*\s+\*\s+\*$", raw)
        if m:
            return {"minutes": max(1, int(m.group(1))) * 60}
        m = re.match(r"^0\s+0\s+\*/(\d{1,2})\s+\*\s+\*$", raw)
        if m:
            return {"minutes": max(1, int(m.group(1))) * 24 * 60}
        return {"minutes": 0}

    def _prevalidate_cron_policy_args(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Tuple[bool, str]:
        if tool_name not in {"autonomy_cron_create_job", "autonomy_cron_update_job"}:
            return True, ""

        schedule_mode = str((args or {}).get("schedule_mode") or "recurring").strip().lower()
        if schedule_mode == "one_shot":
            run_at_raw = str((args or {}).get("run_at") or "").strip()
            if not run_at_raw:
                return False, "one_shot_run_at_missing_precheck"
            try:
                run_at = datetime.fromisoformat(run_at_raw.replace("Z", "+00:00"))
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=timezone.utc)
                now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
                if run_at <= now_utc:
                    # Auto-heal near-past one-shot values produced from relative phrases
                    # when generation/verification latency consumed remaining seconds.
                    drift_s = max(0.0, (now_utc - run_at).total_seconds())
                    if drift_s <= 120.0:
                        suggested = (now_utc + timedelta(minutes=1)).replace(second=0, microsecond=0)
                        args["run_at"] = suggested.isoformat().replace("+00:00", "Z")
                        return True, ""
                    suggested = (now_utc + timedelta(minutes=1)).replace(second=0, microsecond=0)
                    return (
                        False,
                        "one_shot_run_at_in_past_precheck: "
                        f"run_at={run_at.isoformat()} suggested_run_at={suggested.isoformat().replace('+00:00','Z')}",
                    )
            except Exception as exc:
                return False, f"invalid_one_shot_run_at_precheck: {exc}"
            return True, ""

        cron_expr = str((args or {}).get("cron") or "").strip()
        if not cron_expr:
            return True, ""

        try:
            from core.autonomy.cron_scheduler import (
                parse_cron_expression,
                estimate_min_interval_seconds,
            )
            parsed = parse_cron_expression(cron_expr)
            interval_s = int(estimate_min_interval_seconds(parsed))
        except Exception as exc:
            return False, f"invalid_cron_expression_precheck: {exc}"

        try:
            from config import (
                get_autonomy_cron_min_interval_s,
                get_autonomy_cron_trion_min_interval_s,
            )
            min_interval_s = int(get_autonomy_cron_min_interval_s())
            created_by = str((args or {}).get("created_by") or "").strip().lower()
            if created_by == "trion":
                min_interval_s = max(min_interval_s, int(get_autonomy_cron_trion_min_interval_s()))
        except Exception:
            min_interval_s = 300

        if interval_s < min_interval_s:
            suggested = self._suggest_cron_expression_for_min_interval(min_interval_s)
            suggested_minutes = self._extract_interval_hint_from_cron(suggested).get("minutes", 0)
            return (
                False,
                "cron_min_interval_violation_precheck: "
                f"requested={interval_s}s minimum={min_interval_s}s "
                f"suggested_every_minutes={suggested_minutes or max(1, (min_interval_s + 59)//60)} "
                f"suggested_cron={suggested} confirm_required=true",
            )

        return True, ""

    def _build_tool_args(self, tool_name: str, user_text: str, verified_plan: Dict = None) -> dict:
        """
        Emergency-Fallback: Minimale Standard-Args für bekannte Tools.
        Wird nur aufgerufen wenn ControlLayer.decide_tools() keine Args liefert.
        Kein komplexes Keyword-Parsing — ControlLayer übernimmt das via Function Calling.

        Legacy contract markers (implementation moved to `core/orchestrator_tool_args_utils.py`):
        if any(tok in lower for tok in ("steam-headless", "sunshine", "gaming station", "gaming-station", "zocken", "moonlight")):
            return {"blueprint_id": "gaming-station"}
        elif tool_name == "blueprint_create":
            {"id": "gaming-station", "image": "josh5/steam-headless:latest"}
        """
        return util_build_tool_args(
            tool_name,
            user_text,
            verified_plan=verified_plan,
            extract_requested_skill_name_fn=self._extract_requested_skill_name,
            looks_like_host_runtime_lookup_fn=self._looks_like_host_runtime_lookup,
            extract_cron_schedule_from_text_fn=self._extract_cron_schedule_from_text,
            build_cron_objective_fn=self._build_cron_objective,
            build_cron_name_fn=self._build_cron_name,
            extract_cron_job_id_from_text_fn=self._extract_cron_job_id_from_text,
            extract_cron_expression_from_text_fn=self._extract_cron_expression_from_text,
        )

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
        return util_validate_tool_args(
            tool_hub,
            tool_name,
            tool_args,
            user_text,
            extract_requested_skill_name_fn=self._extract_requested_skill_name,
            sanitize_skill_name_candidate_fn=self._sanitize_skill_name_candidate,
            extract_cron_schedule_from_text_fn=self._extract_cron_schedule_from_text,
            prevalidate_cron_policy_args_fn=self._prevalidate_cron_policy_args,
        )

    def _execute_tools_sync(
        self,
        suggested_tools: list,
        user_text: str,
        control_tool_decisions: dict = None,
        control_decision: Optional[ControlDecision] = None,
        time_reference: str = None,
        thinking_suggested_tools: list = None,
        blueprint_gate_blocked: bool = False,
        blueprint_router_id: str = None,
        blueprint_suggest_msg: str = "",
        session_id: str = "",
        verified_plan: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute tools and return combined context string."""
        return util_execute_tools_sync(
            suggested_tools,
            user_text,
            control_tool_decisions=control_tool_decisions,
            control_decision=control_decision,
            time_reference=time_reference,
            thinking_suggested_tools=thinking_suggested_tools,
            blueprint_gate_blocked=blueprint_gate_blocked,
            blueprint_router_id=blueprint_router_id,
            blueprint_suggest_msg=blueprint_suggest_msg,
            session_id=session_id,
            verified_plan=verified_plan,
            get_hub_fn=get_hub,
            get_recent_container_state_fn=self._get_recent_container_state,
            build_tool_args_fn=self._build_tool_args,
            route_blueprint_request_fn=self._route_blueprint_request,
            tool_requires_container_id_fn=self._tool_requires_container_id,
            resolve_pending_container_id_sync_fn=self._resolve_pending_container_id_sync,
            validate_tool_args_fn=self._validate_tool_args,
            bind_cron_conversation_id_fn=self._bind_cron_conversation_id,
            format_tool_result_fn=self._format_tool_result,
            build_tool_result_card_fn=self._build_tool_result_card,
            build_grounding_evidence_entry_fn=self._build_grounding_evidence_entry,
            sanitize_tool_args_for_state_fn=self._sanitize_tool_args_for_state,
            verify_container_running_fn=self._verify_container_running,
            save_workspace_entry_fn=self._save_workspace_entry,
            update_container_state_from_tool_result_fn=self._update_container_state_from_tool_result,
            tool_intelligence_handle_tool_result_fn=self.tool_intelligence.handle_tool_result,
            build_direct_cron_create_response_fn=self._build_direct_cron_create_response,
            recover_home_read_directory_with_fast_lane_fn=self._recover_home_read_directory_with_fast_lane,
            build_container_event_content_fn=self._build_container_event_content,
            save_container_event_fn=self._save_container_event,
            log_info_fn=log_info,
            log_warn_fn=log_warn,
            log_error_fn=log_error,
            log_warning_fn=log_warn,
        )


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
            _is_error, _err_msg = detect_tool_error(result)
            
            if len(result_str) > 3000:
                result_str = result_str[:3000] + "... (gekürzt)"
            
            if _is_error:
                formatted = f"\n### FEHLER ({tool_name}): {_err_msg or result_str}\n"
            else:
                formatted = f"\n### TOOL-ERGEBNIS ({tool_name}):\n{result_str}\n"
            
            metadata = {
                "execution_mode": "mcp",
                "tool_name": tool_name
            }
            if _is_error:
                metadata["error"] = _err_msg or result_str
            
            return (formatted, not _is_error, metadata)

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

    @staticmethod
    def _build_control_workspace_summary(
        verification: Dict[str, Any],
        *,
        skipped: bool,
        skip_reason: str = "",
    ) -> str:
        return build_control_workspace_summary(
            verification,
            skipped=skipped,
            skip_reason=skip_reason,
        )

    @classmethod
    def _is_control_hard_block_decision(cls, verification: Dict[str, Any]) -> bool:
        _ = cls
        return is_control_hard_block_decision(verification)

    @staticmethod
    def _build_done_workspace_summary(
        done_reason: str,
        *,
        response_mode: str = "",
        model: str = "",
        memory_used: Optional[bool] = None,
    ) -> str:
        return build_done_workspace_summary(
            done_reason,
            response_mode=response_mode,
            model=model,
            memory_used=memory_used,
        )

    @staticmethod
    def _build_sequential_workspace_summary(event: Dict[str, Any]) -> Tuple[str, str]:
        return build_sequential_workspace_summary(event)

    def _persist_sequential_workspace_event(
        self,
        conversation_id: str,
        event: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return persist_sequential_workspace_event(
            self._save_workspace_entry,
            conversation_id,
            event,
        )

    @staticmethod
    def _build_master_workspace_summary(event_type: str, payload: Dict[str, Any]) -> str:
        """Build compact text summary for master-autonomy planning events."""
        data = payload if isinstance(payload, dict) else {}
        kind = str(event_type or "").strip() or "planning_event"

        if kind == "planning_start":
            objective = str(data.get("objective", "") or "").strip()
            max_loops = data.get("max_loops")
            state = str(data.get("state", "") or "").strip()
            planning_mode = str(data.get("planning_mode", "") or "").strip()
            parts = [f"objective={objective[:140]}" if objective else "objective=unknown"]
            if max_loops is not None:
                parts.append(f"max_loops={max_loops}")
            if state:
                parts.append(f"state={state}")
            if planning_mode:
                parts.append(f"planning_mode={planning_mode}")
            return " | ".join(parts)

        if kind == "planning_step":
            parts: List[str] = []
            phase = str(data.get("phase", "") or "").strip()
            if phase:
                parts.append(f"phase={phase}")
            if data.get("loop") is not None:
                parts.append(f"loop={data.get('loop')}")
            state = str(data.get("state", "") or "").strip()
            if state:
                parts.append(f"state={state}")
            decision = str(data.get("decision", "") or "").strip()
            if decision:
                parts.append(f"decision={decision}")
            next_action = str(data.get("next_action", "") or "").strip()
            if next_action:
                parts.append(f"next_action={next_action[:140]}")
            action = str(data.get("action", "") or "").strip()
            if action:
                parts.append(f"action={action[:140]}")
            reason = str(data.get("reason", "") or "").strip()
            if reason:
                parts.append(f"reason={reason[:120]}")
            return " | ".join(parts) if parts else "planning_step"

        if kind == "planning_done":
            loops = data.get("loops_executed")
            steps = data.get("steps_completed")
            final_state = str(data.get("final_state", "") or "").strip()
            stop_reason = str(data.get("stop_reason", "") or "").strip()
            parts = []
            if loops is not None:
                parts.append(f"loops={loops}")
            if steps is not None:
                parts.append(f"steps={steps}")
            if final_state:
                parts.append(f"final_state={final_state}")
            if stop_reason:
                parts.append(f"stop_reason={stop_reason}")
            return " | ".join(parts) if parts else "planning_done"

        if kind == "planning_error":
            phase = str(data.get("phase", "") or "").strip()
            error = str(data.get("error", "") or "").strip() or "unknown_error"
            error_code = str(data.get("error_code", "") or "").strip()
            action = str(data.get("action", "") or "").strip()
            stop_reason = str(data.get("stop_reason", "") or "").strip()
            parts = [f"error={error[:180]}"]
            if error_code:
                parts.append(f"error_code={error_code[:80]}")
            if phase:
                parts.append(f"phase={phase}")
            if action:
                parts.append(f"action={action[:120]}")
            if stop_reason:
                parts.append(f"stop_reason={stop_reason[:80]}")
            return " | ".join(parts)

        return json.dumps(data, ensure_ascii=False)[:240] if data else kind

    def _persist_master_workspace_event(
        self,
        conversation_id: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Persist master-autonomy events to workspace_events for Planmode visibility."""
        conv_id = str(conversation_id or "").strip()
        kind = str(event_type or "").strip()
        if not conv_id or kind not in {"planning_start", "planning_step", "planning_done", "planning_error"}:
            return None
        content = self._build_master_workspace_summary(kind, payload if isinstance(payload, dict) else {})
        return self._save_workspace_entry(
            conversation_id=conv_id,
            content=content,
            entry_type=kind,
            source_layer="master",
        )

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
        return util_build_effective_context(
            self,
            user_text,
            conv_id,
            small_model_mode=small_model_mode,
            cleanup_payload=cleanup_payload,
            include_blocks=include_blocks,
            debug_flags=debug_flags,
            request_cache=request_cache,
        )

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
        return await util_check_pending_confirmation(
            self,
            user_text,
            conversation_id,
            intent_system_available=bool(INTENT_SYSTEM_AVAILABLE),
            get_intent_store_fn=get_intent_store if INTENT_SYSTEM_AVAILABLE else (lambda: None),
            get_hub_fn=get_hub,
            intent_state_cls=IntentState if INTENT_SYSTEM_AVAILABLE else None,
            core_chat_response_cls=CoreChatResponse,
            log_info_fn=log_info,
            log_warn_fn=log_warn,
            log_error_fn=log_error,
        )
    
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
        return await util_process_request(
            self,
            request,
            core_chat_response_cls=CoreChatResponse,
            intent_system_available=bool(INTENT_SYSTEM_AVAILABLE),
            get_master_settings_fn=get_master_settings,
            thinking_plan_cache=_thinking_plan_cache,
            soften_control_deny_fn=soften_control_deny,
            log_info_fn=log_info,
            log_warn_fn=log_warn,
            log_warning_fn=log_warn,
        )
    
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
        async for item in util_process_stream_with_events(
            self,
            request,
            intent_system_available=bool(INTENT_SYSTEM_AVAILABLE),
            enable_chunking=bool(ENABLE_CHUNKING),
            chunking_threshold=int(CHUNKING_THRESHOLD),
            get_master_settings_fn=get_master_settings,
            thinking_plan_cache=_thinking_plan_cache,
            sequential_result_cache=_sequential_result_cache,
            soften_control_deny_fn=soften_control_deny,
            skill_creation_intent_cls=SkillCreationIntent if INTENT_SYSTEM_AVAILABLE else None,
            intent_origin_cls=IntentOrigin if INTENT_SYSTEM_AVAILABLE else None,
            get_intent_store_fn=get_intent_store if INTENT_SYSTEM_AVAILABLE else (lambda: None),
            log_info_fn=log_info,
            log_warn_fn=log_warn,
            log_error_fn=log_error,
            log_debug_fn=log_debug,
            log_warning_fn=log_warn,
        ):
            yield item

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
        async for chunk in util_process_chunked_stream(
            self,
            user_text,
            conversation_id,
            request,
            get_hub_fn=get_hub,
            log_info_fn=log_info,
            log_error_fn=log_error,
        ):
            yield chunk

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
        conversation_id: str,
        response_mode: str = "interactive",
    ) -> Tuple[Dict, Dict]:
        """Execute Control Layer (Step 2)."""
        return await util_execute_control_layer(
            self,
            user_text,
            thinking_plan,
            memory_data,
            conversation_id,
            response_mode=response_mode,
            intent_system_available=bool(INTENT_SYSTEM_AVAILABLE),
            skill_creation_intent_cls=SkillCreationIntent if INTENT_SYSTEM_AVAILABLE else None,
            intent_origin_cls=IntentOrigin if INTENT_SYSTEM_AVAILABLE else None,
            get_intent_store_fn=get_intent_store if INTENT_SYSTEM_AVAILABLE else (lambda: None),
            log_info_fn=log_info,
            log_warn_fn=log_warn,
        )
    
    async def _execute_output_layer(
        self,
        user_text: str,
        verified_plan: Dict,
        memory_data: str,
        model: str,
        chat_history: list,
        control_decision: Optional[ControlDecision] = None,
        execution_result: Optional[Dict[str, Any]] = None,
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
            chat_history=chat_history,
            control_decision=control_decision,
            execution_result=execution_result,
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
        tool_ctx = str(get_runtime_tool_results(verified_plan) or "")
        grounding_policy = load_grounding_policy()
        output_grounding = (grounding_policy or {}).get("output") or {}
        memory_grounding = (grounding_policy or {}).get("memory") or {}
        allowed_statuses = output_grounding.get("allowed_evidence_statuses", ["ok"])
        min_successful_evidence = int(output_grounding.get("min_successful_evidence", 1) or 1)
        successful_evidence = self._count_successful_grounding_evidence(
            verified_plan, allowed_statuses=allowed_statuses
        )
        is_fact_query = bool(verified_plan.get("is_fact_query", False))
        has_tool_usage = bool(tool_ctx.strip())
        has_tool_suggestions = bool(self._extract_suggested_tool_names(verified_plan))
        require_evidence_for_autosave = bool(
            memory_grounding.get("autosave_requires_evidence_for_fact_query", True)
            and is_fact_query
            and (
                (
                    bool(output_grounding.get("enforce_evidence_for_fact_query", True))
                    and (has_tool_usage or has_tool_suggestions)
                )
                or (bool(output_grounding.get("enforce_evidence_when_tools_used", True)) and has_tool_usage)
                or (
                    bool(output_grounding.get("enforce_evidence_when_tools_suggested", True))
                    and has_tool_suggestions
                )
            )
        )
        skip_autosave = False
        skip_reason = ""
        if verified_plan.get("_pending_intent"):
            skip_autosave = True
            skip_reason = "pending_intent_confirmation"
        elif (
            (get_runtime_tool_failure(verified_plan) or self._tool_context_has_failures_or_skips(tool_ctx))
            and not (answer or "").strip()
        ):
            skip_autosave = True
            skip_reason = "tool_failure_with_empty_answer"
        elif bool(
            get_runtime_grounding_value(
                verified_plan,
                key="missing_evidence",
                legacy_key="_grounding_missing_evidence",
                default=False,
            )
        ):
            skip_autosave = True
            skip_reason = "grounding_missing_evidence"
        elif bool(
            get_runtime_grounding_value(
                verified_plan,
                key="violation_detected",
                legacy_key="_grounding_violation_detected",
                default=False,
            )
        ):
            skip_autosave = True
            skip_reason = "grounding_violation_detected"
        elif require_evidence_for_autosave and successful_evidence < min_successful_evidence:
            skip_autosave = True
            skip_reason = "insufficient_grounding_evidence"

        if skip_autosave:
            log_warn(f"[Orchestrator-Autosave] Skipped assistant autosave ({skip_reason})")
            return

        dedupe_guard = get_autosave_dedupe_guard()
        if dedupe_guard is not None:
            try:
                if dedupe_guard.should_skip(conversation_id=conversation_id, content=answer):
                    log_warn("[Orchestrator-Autosave] Skipped assistant autosave (duplicate_window)")
                    return
            except Exception as dedupe_err:
                log_warn(f"[Orchestrator-Autosave] Dedupe guard fallback: {dedupe_err}")

        try:
            autosave_assistant(
                conversation_id=conversation_id,
                content=answer,
                layer="stm",
            )
        except Exception as e:
            log_error(f"[Orchestrator-Autosave] Error: {e}")
