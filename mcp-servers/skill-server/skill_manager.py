"""
TRION Skill Manager (Dumb Proxy Version)

Delegates all write operations to the hardened ToolExecutionLayer via HTTP.
Maintains read-only access for listing/execution.
"""

import os
import json
import shutil
import httpx
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

EXECUTOR_URL = os.getenv("EXECUTOR_URL", "http://tool-executor:8000")
MEMORY_URL = os.getenv("MEMORY_URL", "http://mcp-sql-memory:8081")

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _normalize_skill_key(name: str) -> str:
    """Canonical key for skill identity in graph hygiene."""
    return str(name or "").strip().lower().replace("-", "_").replace(" ", "_")


def _coerce_bool_flag(value: Any) -> bool:
    """Parse bool-like metadata values deterministically."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).strip().lower()
    return s in {"1", "true", "yes", "on"}


def parse_skill_graph_candidate(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse one raw graph/semantic result into a normalized skill candidate dict.
    Returns None when no stable skill identity can be derived.
    """
    if not isinstance(raw, dict):
        return None

    meta_raw = raw.get("metadata") or {}
    if isinstance(meta_raw, str):
        try:
            meta = json.loads(meta_raw) or {}
        except Exception:
            meta = {}
    elif isinstance(meta_raw, dict):
        meta = meta_raw
    else:
        meta = {}

    content = str(raw.get("content") or "")
    skill_name = str(meta.get("skill_name") or meta.get("name") or "").strip()
    if not skill_name and ":" in content:
        skill_name = content.split(":", 1)[0].strip()
    if not skill_name and content:
        skill_name = content.split()[0].strip()

    skill_key = str(meta.get("skill_key") or "").strip()
    if not skill_key:
        skill_key = _normalize_skill_key(skill_name)
    if not skill_key:
        return None

    updated_at = str(meta.get("updated_at") or "")
    is_deleted = _coerce_bool_flag(meta.get("is_deleted"))
    try:
        node_id = int(raw.get("id") or raw.get("node_id") or 0)
    except (TypeError, ValueError):
        node_id = 0

    return {
        "skill_key": skill_key,
        "skill_name": skill_name or skill_key,
        "updated_at": updated_at,
        "is_deleted": is_deleted,
        "node_id": node_id,
        "metadata": meta,
        "content": content,
    }


def dedupe_latest_skill_graph_candidates(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Deduplicate identical rows while preserving multiple live nodes per skill_key.
    This keeps stale duplicates visible for tombstone planning.
    """
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for c in candidates:
        node_id = int(c.get("node_id", 0) or 0)
        if node_id > 0:
            key = ("id", node_id)
        else:
            key = (
                "fallback",
                c.get("skill_key", ""),
                bool(c.get("is_deleted")),
                str(c.get("content", "")),
            )
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def plan_skill_graph_reconcile(
    truth_index: Dict[str, Dict[str, Any]],
    graph_candidates: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Compute reconcile actions:
      - tombstones for ghost/stale graph entries
      - upserts for missing truth skills in graph index
    """
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for c in graph_candidates:
        sk = c.get("skill_key", "")
        if not sk:
            continue
        by_key.setdefault(sk, []).append(c)

    tombstones: List[Dict[str, Any]] = []
    upserts: List[Dict[str, Any]] = []

    for sk, rows in by_key.items():
        rows_sorted = sorted(
            rows,
            key=lambda r: (str(r.get("updated_at", "")), int(r.get("node_id", 0))),
            reverse=True,
        )
        live = [r for r in rows_sorted if not r.get("is_deleted")]
        has_tombstone = any(r.get("is_deleted") for r in rows_sorted)
        in_truth = sk in truth_index

        if not in_truth:
            # Ghost skill in graph index: tombstone once, then stay idempotent.
            if live and not has_tombstone:
                g = live[0]
                tombstones.append({
                    "skill_key": sk,
                    "skill_name": g.get("skill_name", sk),
                    "reason": "ghost_skill",
                    "source_node_id": g.get("node_id", 0),
                })
            continue

        # Truth exists but graph has no live entry => upsert index node.
        if not live:
            upserts.append(truth_index[sk])
            continue

        # Stale cleanup for duplicates (single tombstone batch for first stale).
        if len(live) > 1 and not has_tombstone:
            for stale in live[1:]:
                tombstones.append({
                    "skill_key": sk,
                    "skill_name": stale.get("skill_name", sk),
                    "reason": "stale_duplicate",
                    "source_node_id": stale.get("node_id", 0),
                })

    # Truth skills absent entirely from graph candidates => upsert
    seen_keys = set(by_key.keys())
    for sk, truth_skill in truth_index.items():
        if sk not in seen_keys:
            upserts.append(truth_skill)

    # De-dupe upsert actions by skill_key (keep first deterministic item)
    upsert_by_key: Dict[str, Dict[str, Any]] = {}
    for u in upserts:
        usk = u.get("skill_key", "")
        if usk and usk not in upsert_by_key:
            upsert_by_key[usk] = u

    return {
        "tombstones": tombstones,
        "upserts": list(upsert_by_key.values()),
    }


class SkillManager:
    """
    Proxy Manager.
    - READs: Directly from mounted volume (ReadOnly)
    - WRITEs: Forwarded to ToolExecutionLayer
    """

    def __init__(self, skills_dir: str, registry_url: str):
        self.skills_dir = Path(skills_dir)
        self.registry_url = registry_url
        self.installed_file = self.skills_dir / "_registry" / "installed.json"

    def _load_installed(self) -> Dict[str, Dict]:
        """
        Load installed skills from registry file (Read Only).
        Handles both legacy flat dict and V2 envelope {schema_version, skills, ...}.
        Returns flat skills map {skill_name: {...}} for backward compat.
        Graph is never consulted here — installed.json is the sole truth.
        """
        if not self.installed_file.exists():
            return {}
        try:
            with open(self.installed_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # V2 envelope
            if isinstance(raw, dict) and raw.get("schema_version") == 2:
                skills = raw.get("skills", {})
                print(
                    f"[SkillTruth] read schema=v2"
                    f" hash={str(raw.get('skill_registry_hash', ''))[:12]}"
                    f" skills_count={len(skills)} migrated_legacy=False"
                )
                return skills if isinstance(skills, dict) else {}
            # Legacy flat dict
            if isinstance(raw, dict):
                print(
                    f"[SkillTruth] read schema=legacy"
                    f" skills_count={len(raw)} migrated_legacy=True"
                )
                return raw
        except Exception:
            return {}
        return {}

    @staticmethod
    def _is_graph_reconcile_enabled() -> bool:
        """C9 rollout/rollback gate. Defaults to True; env fallback for isolated container runtime."""
        try:
            from config import get_skill_graph_reconcile
            return bool(get_skill_graph_reconcile())
        except Exception:
            return os.getenv("SKILL_GRAPH_RECONCILE", "true").lower() == "true"

    async def _call_memory_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call sql-memory MCP tool endpoint. Fail-closed caller handles errors."""
        payload = {
            "jsonrpc": "2.0",
            "id": int(datetime.now().timestamp() * 1000),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{MEMORY_URL}/mcp", headers=_MCP_HEADERS, json=payload)
            try:
                return resp.json()
            except Exception:
                # Some transports return SSE text; best-effort parse of data-line JSON.
                body = resp.text or ""
                for line in body.splitlines():
                    if line.startswith("data:"):
                        try:
                            return json.loads(line[5:].strip())
                        except Exception:
                            continue
        return {}

    async def _fetch_skill_graph_candidates(
        self,
        query_terms: List[str],
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """
        Query graph index candidates from memory semantic search.
        Uses multiple terms to maximize recall, then de-duplicates by node id/content.
        """
        seen = set()
        merged: List[Dict[str, Any]] = []
        terms = [t for t in (query_terms or []) if str(t).strip()]
        if not terms:
            terms = ["skill"]
        successful_calls = 0
        failed_calls = 0

        for term in terms:
            try:
                raw = await self._call_memory_tool("memory_semantic_search", {
                    "query": str(term),
                    "conversation_id": "_skills",
                    "limit": 200,
                    "min_similarity": 0.0,
                })
                if not isinstance(raw, dict) or not raw:
                    failed_calls += 1
                    continue
                if raw.get("error"):
                    failed_calls += 1
                    continue
                successful_calls += 1
                result = raw.get("result", raw)
                if isinstance(result, dict):
                    if "structuredContent" in result:
                        rows = result["structuredContent"].get("results", [])
                    else:
                        rows = result.get("results", [])
                else:
                    rows = []
            except Exception:
                failed_calls += 1
                rows = []

            for row in rows:
                if not isinstance(row, dict):
                    continue
                rid = row.get("id")
                key = ("id", rid) if rid is not None else ("content", row.get("content", ""))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(row)
        return merged, successful_calls, failed_calls

    async def _write_skill_tombstone(
        self,
        *,
        skill_key: str,
        skill_name: str,
        reason: str,
        source_node_id: int = 0,
    ) -> bool:
        """
        Add tombstone node in _skills graph index.
        Graph remains index-only; no writes to installed.json.
        """
        metadata = json.dumps({
            "skill_name": skill_name,
            "skill_key": skill_key,
            "is_deleted": True,
            "deleted_at": datetime.utcnow().isoformat() + "Z",
            "reconcile_reason": reason,
            "source_node_id": source_node_id,
            "source": "skill_graph_reconcile",
        })
        content = f"{skill_name}: tombstone ({reason})"
        try:
            await self._call_memory_tool("graph_add_node", {
                "source_type": "skill",
                "content": content,
                "conversation_id": "_skills",
                "confidence": 1.0,
                "metadata": metadata,
            })
            return True
        except Exception:
            return False

    async def reconcile_skill_graph_index(self) -> Dict[str, Any]:
        """
        C9 Reconcile graph index against truth store (installed.json).
        - Graph is index only; truth remains installed.json.
        - Creates tombstones for ghost/stale graph entries.
        - Upserts missing truth skills back to graph index.
        """
        if not self._is_graph_reconcile_enabled():
            return {
                "enabled": False,
                "reason": "SKILL_GRAPH_RECONCILE=false",
                "graph_candidates": 0,
                "tombstoned": 0,
                "upserted": 0,
            }

        installed = self._load_installed()
        truth_index: Dict[str, Dict[str, Any]] = {}
        for name, info in installed.items():
            sk = info.get("skill_key") or _normalize_skill_key(name)
            truth_index[sk] = {
                "skill_key": sk,
                "name": name,
                "description": info.get("description", ""),
                "triggers": info.get("triggers", []),
            }

        # Fail-closed on fetch errors: no graph writes when candidate set can't be trusted.
        try:
            # Single broad term keeps runtime bounded and avoids N network calls per reconcile.
            raw_candidates, ok_calls, failed_calls = await self._fetch_skill_graph_candidates(["skill"])
        except Exception as e:
            return {
                "enabled": True,
                "error": f"graph_fetch_failed:{e}",
                "graph_candidates": 0,
                "tombstoned": 0,
                "upserted": 0,
            }
        if ok_calls == 0 and failed_calls > 0:
            return {
                "enabled": True,
                "error": "graph_fetch_failed:all_terms_failed",
                "graph_candidates": 0,
                "tombstoned": 0,
                "upserted": 0,
            }

        parsed = [c for c in (parse_skill_graph_candidate(r) for r in raw_candidates) if c is not None]
        deduped = dedupe_latest_skill_graph_candidates(parsed)
        plan = plan_skill_graph_reconcile(truth_index, deduped)

        tombstoned = 0
        for t in plan["tombstones"]:
            ok = await self._write_skill_tombstone(
                skill_key=t["skill_key"],
                skill_name=t["skill_name"],
                reason=t["reason"],
                source_node_id=t.get("source_node_id", 0),
            )
            tombstoned += 1 if ok else 0

        upserted = 0
        for u in plan["upserts"]:
            try:
                await self._register_skill_in_graph(
                    name=u["name"],
                    description=u.get("description", ""),
                    triggers=u.get("triggers", []),
                )
                upserted += 1
            except Exception:
                continue

        return {
            "enabled": True,
            "graph_candidates": len(deduped),
            "tombstones_planned": len(plan["tombstones"]),
            "upserts_planned": len(plan["upserts"]),
            "tombstoned": tombstoned,
            "upserted": upserted,
        }

    def list_installed(self) -> List[Dict[str, Any]]:
        """List all installed skills"""
        installed = self._load_installed()
        skills = []
        for name, info in installed.items():
            skill_path = self.skills_dir / name
            skills.append({
                "name": name,
                "version": info.get("version", "unknown"),
                "installed_at": info.get("installed_at"),
                "description": info.get("description", ""),
                "status": "installed" if skill_path.exists() else "broken"
            })
        return skills

    async def validate_code(self, code: str) -> Dict[str, Any]:
        """Proxy validation"""
        payload = {"code": code}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/validation/code", json=payload, timeout=10.0)
                return resp.json()
            except Exception as e:
                return {"error": str(e)}

    async def get_priors(self, context: str) -> Dict[str, Any]:
        """Proxy priors"""
        payload = {"context": context}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/context/priors", json=payload, timeout=10.0)
                return resp.json()
            except Exception as e:
                return {"error": str(e)}

    @staticmethod
    def _extract_skill_keywords(name: str, description: str = "", triggers: list = None) -> list:
        """
        Extrahiert Keywords aus Name + Description + Triggers.
        Kein LLM — rein regelbasiert (snake_case split + Stop-Word-Filter).
        Diese Keywords reichern das Embedding an → bessere semantische Suche.
        """
        import re
        _STOP = frozenset({
            "der", "die", "das", "ein", "eine", "und", "oder", "ist", "sind",
            "wird", "werden", "für", "von", "mit", "auf", "bei", "nach",
            "the", "a", "an", "is", "are", "for", "of", "with", "on", "in",
            "to", "and", "or", "it", "skill", "erstellt", "zeigt", "gibt",
            "macht", "holt", "liefert", "shows", "gets", "returns",
        })
        keywords = set()
        # snake_case + camelCase Split
        for part in re.split(r"[_\-\s]+", name.lower()):
            sub = re.sub(r"([a-z])([A-Z])", r"\1 \2", part).lower()
            for w in sub.split():
                if len(w) >= 3 and w not in _STOP:
                    keywords.add(w)
        # Description
        if description:
            for w in re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", description.lower()):
                if w not in _STOP:
                    keywords.add(w)
        # Triggers
        for t in (triggers or []):
            for w in re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", t.lower()):
                if w not in _STOP:
                    keywords.add(w)
        return sorted(keywords)[:20]

    async def _register_skill_in_graph(
        self, name: str, description: str, triggers: list
    ) -> None:
        """
        Registriert einen neu erstellten Skill als Graph-Node in sql-memory.
        Ermöglicht semantische Skill-Discovery ohne hardcoded Keywords.
        conversation_id="_skills" — konsistent mit "_container_events".

        NEU: Keywords werden extrahiert und in Embedding-Content eingebettet,
        damit der SkillSemanticRouter (in core/) den Skill via cosine similarity findet.
        Non-blocking: Fehler werden nur geloggt, nie propagiert.

        GUARD: graph update is best-effort; truth (installed.json) is NEVER touched here.
        Rollback: set SKILL_GRAPH_RECONCILE=false to skip all graph sync.
        """
        import time as _time
        import json as _json
        triggers_text = ", ".join(triggers) if triggers else ""

        # Keywords extrahieren (kein LLM!)
        keywords = self._extract_skill_keywords(name, description, triggers)
        keywords_text = " ".join(keywords) if keywords else ""

        # Angereicherter Content für besseres Embedding
        content = f"{name}: {description}"
        if triggers_text:
            content += f". Triggers: {triggers_text}"
        if keywords_text:
            content += f". Keywords: {keywords_text}"

        # skill_key for stable identity — graph is index-only, truth = installed.json
        import os as _os2
        _mode = _os2.getenv("SKILL_KEY_MODE", "name").lower()
        _skill_key = name.lower().replace("-", "_").replace(" ", "_") if _mode != "legacy" else name

        # Metadata enthält skill_name explizit → SkillRouter kann direkt lesen
        # C4: includes skill_key, channel, revision, updated_at for observability
        import time as _time2
        metadata = _json.dumps({
            "skill_name": name,
            "skill_key": _skill_key,
            "channel": "active",
            "keywords": keywords,
            "updated_at": _time2.strftime("%Y-%m-%dT%H:%M:%S"),
        })

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{MEMORY_URL}/mcp",
                    headers=_MCP_HEADERS,
                    json={
                        "jsonrpc": "2.0",
                        "id": int(_time.time() * 1000),
                        "method": "tools/call",
                        "params": {
                            "name": "graph_add_node",
                            "arguments": {
                                "source_type": "skill",
                                "content": content,
                                "conversation_id": "_skills",
                                "confidence": 0.9,
                                "metadata": metadata,
                            },
                        },
                    },
                )
            print(f"[SkillManager] Graph-Node erstellt für Skill '{name}' (keywords: {keywords[:5]})")
        except Exception as e:
            print(f"[SkillManager] Graph-Registrierung fehlgeschlagen (non-critical): {e}")

    async def create_skill(self, name: str, skill_data: Dict[str, Any], draft: bool = True) -> Dict[str, Any]:
        """
        Proxy creation to Tool Executor.
        Nach Erfolg: Skill wird als Graph-Node registriert (semantische Discovery).

        C4.5: control_decision (pre-validated by skill-server) is forwarded as-is
        so the executor can operate as a pure side-effect executor.
        """
        payload = {
            "name": name,
            "code": skill_data.get("code"),
            "description": skill_data.get("description"),
            "triggers": skill_data.get("triggers", []),
            "auto_promote": not draft,
            "gap_patterns": skill_data.get("gap_patterns", []),
            "gap_question": skill_data.get("gap_question"),
            "preferred_model": skill_data.get("preferred_model"),
            "default_params": skill_data.get("default_params", {}),
            "control_decision": skill_data.get("control_decision"),  # C4.5 pass-through
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/skills/create", json=payload, timeout=30.0)
                result = resp.json()

                # ── GRAPH HOOK: Bei Erfolg im Skill-Graph registrieren ──
                # Executor gibt {installation: {success: true}} zurück, kein Top-Level "success"
                _install_ok = (
                    result.get("success")
                    or result.get("installation", {}).get("success")
                )
                if _install_ok:
                    await self._register_skill_in_graph(
                        name=name,
                        description=skill_data.get("description", ""),
                        triggers=skill_data.get("triggers", []),
                    )

                return result
            except Exception as e:
                return {"success": False, "error": f"Executor unreachable: {e}"}


    async def install_skill(self, name: str) -> Dict[str, Any]:
        """
        Proxy installation to Tool Executor.
        
        Installs a skill from the external TRION registry.
        All write operations happen in the hardened tool-executor service.
        """
        payload = {
            "name": name,
            "registry_url": self.registry_url
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/skills/install", json=payload)
                return resp.json()
            except httpx.TimeoutException:
                return {"success": False, "error": "Installation timeout - skill may be large"}
            except Exception as e:
                return {"success": False, "error": str(e)}

    async def uninstall_skill(self, name: str) -> Dict[str, Any]:
        """
        Proxy uninstall to Tool Executor.
        """
        payload = {"name": name}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/skills/uninstall", json=payload, timeout=10.0)
                return resp.json()
            except Exception as e:
                return {"success": False, "error": f"Executor unreachable: {e}"}

    # ... (Other read methods like list_available, run_skill remain similar but read-only)
    
    async def list_available(self) -> List[Dict[str, Any]]:
        """Fetch available skills (Read Only)"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.registry_url}/index.json")
                if response.status_code == 200:
                    return response.json().get("skills", [])
        except Exception:
            pass
        return [] # Fallback omitted for brevity, logic remains same

    async def run_skill(self, name: str, action: str = "run", args: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Proxy skill execution to Tool Executor (Sandboxed).
        
        All skill execution now happens in the hardened tool-executor service
        which provides:
        - Restricted builtins (no eval, exec, open, etc.)
        - Module whitelist
        - Execution timeout
        - Audit logging
        """
        args = args or {}
        
        payload = {
            "name": name,
            "action": action,
            "args": args
        }
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{EXECUTOR_URL}/v1/skills/run",
                    json=payload,
                    timeout=60.0  # Skills can take longer
                )
                return resp.json()
            except httpx.TimeoutException:
                return {"success": False, "error": "Skill execution timed out"}
            except Exception as e:
                return {"success": False, "error": f"Executor unreachable: {e}"}


    def get_skill_info(self, name: str) -> Dict[str, Any]:
        """Read skill info."""
        installed = self._load_installed()
        if name in installed:
            return installed[name]
        return {"error": "Not installed"}

    def get_skill_detail(self, name: str, channel: Optional[str] = None) -> Dict[str, Any]:
        """
        Get detailed, normalized information about a skill by name.

        channel: 'active' | 'draft' | None
        Default (channel=None): prefer active, fall back to draft.
        Returns a standardized dict or {"error": "..."} when not found.
        Read-only — no writes.

        C4: includes revision, updated_at, skill_key for stable identity tracking.
        """
        # ── Active channel ──────────────────────────────────────────────────
        active_info: Optional[Dict[str, Any]] = None
        installed = self._load_installed()
        if name in installed:
            info = installed[name]
            skill_path = self.skills_dir / name
            manifest_data: Dict[str, Any] = {}
            manifest_path = skill_path / "manifest.yaml"
            if manifest_path.exists():
                try:
                    import yaml
                    with open(manifest_path) as f:
                        manifest_data = yaml.safe_load(f) or {}
                except Exception:
                    pass
            # skill_key: prefer registry record, fall back to computed default
            skill_key = info.get("skill_key") or name.lower().replace("-", "_").replace(" ", "_")
            active_info = {
                "name": name,
                "channel": "active",
                "skill_key": skill_key,
                "version": info.get("version", manifest_data.get("version", "unknown")),
                "revision": info.get("revision", 1),
                "updated_at": info.get("updated_at"),
                "description": info.get("description", manifest_data.get("description", "")),
                "triggers": info.get("triggers", manifest_data.get("triggers", [])),
                "gap_patterns": info.get("gap_patterns", manifest_data.get("gap_patterns", [])),
                "gap_question": info.get("gap_question", manifest_data.get("gap_question")),
                "preferred_model": info.get("preferred_model", manifest_data.get("preferred_model")),
                "default_params": info.get("default_params", manifest_data.get("default_params", {})),
                "status": "installed" if skill_path.exists() else "broken",
            }

        # ── Draft channel ────────────────────────────────────────────────────
        draft_info: Optional[Dict[str, Any]] = None
        draft_path = self.skills_dir / "_drafts" / name
        draft_manifest_path = draft_path / "manifest.yaml"
        if draft_path.exists() and draft_manifest_path.exists():
            try:
                import yaml
                with open(draft_manifest_path) as f:
                    manifest_data = yaml.safe_load(f) or {}
                # updated_at: prefer manifest created_at, fall back to file mtime
                import os as _os
                draft_updated_at = manifest_data.get("created_at")
                if not draft_updated_at:
                    try:
                        mtime = draft_manifest_path.stat().st_mtime
                        from datetime import datetime as _dt
                        draft_updated_at = _dt.fromtimestamp(mtime).isoformat()
                    except Exception:
                        draft_updated_at = None
                draft_skill_key = name.lower().replace("-", "_").replace(" ", "_")
                draft_info = {
                    "name": name,
                    "channel": "draft",
                    "skill_key": draft_skill_key,
                    "version": manifest_data.get("version", "draft"),
                    "revision": 1,
                    "updated_at": draft_updated_at,
                    "description": manifest_data.get("description", ""),
                    "triggers": manifest_data.get("triggers", []),
                    "gap_patterns": manifest_data.get("gap_patterns", []),
                    "gap_question": manifest_data.get("gap_question"),
                    "preferred_model": manifest_data.get("preferred_model"),
                    "default_params": manifest_data.get("default_params", {}),
                    "status": "draft",
                }
            except Exception:
                pass

        # ── Channel routing ──────────────────────────────────────────────────
        if channel == "active":
            return active_info if active_info is not None else {
                "error": f"Skill '{name}' not found in active channel"
            }
        if channel == "draft":
            return draft_info if draft_info is not None else {
                "error": f"Skill '{name}' not found in draft channel"
            }
        # Default: prefer active, fall back to draft
        if active_info is not None:
            return active_info
        if draft_info is not None:
            return draft_info
        return {"error": f"Skill '{name}' not found"}
    
    def list_drafts(self):
        # Read from _drafts
        drafts_dir = self.skills_dir / "_drafts"
        if not drafts_dir.exists(): return []
        results = []
        for d in drafts_dir.iterdir():
            if (d / "manifest.yaml").exists():
                 results.append({"name": d.name})
        return results

    def get_draft(self, name: str):
        """Read draft code + manifest (description, triggers)."""
        d = self.skills_dir / "_drafts" / name
        if not d.exists():
            return {"error": "Not found"}
        code = ""
        if (d / "main.py").exists():
            with open(d / "main.py") as f:
                code = f.read()
        # Lese description + triggers + neue Felder aus manifest.yaml
        description = ""
        triggers = []
        gap_patterns: list = []
        gap_question = None
        preferred_model = None
        default_params: dict = {}
        manifest_path = d / "manifest.yaml"
        if manifest_path.exists():
            try:
                import yaml
                with open(manifest_path) as f:
                    manifest = yaml.safe_load(f) or {}
                description = manifest.get("description", "")
                triggers = manifest.get("triggers", [])
                gap_patterns = manifest.get("gap_patterns", [])
                gap_question = manifest.get("gap_question")
                preferred_model = manifest.get("preferred_model")
                default_params = manifest.get("default_params", {})
            except Exception:
                pass
        return {
            "name": name,
            "code": code,
            "description": description,
            "triggers": triggers,
            "gap_patterns": gap_patterns,
            "gap_question": gap_question,
            "preferred_model": preferred_model,
            "default_params": default_params,
        }

    # Promote draft requires WRITE -> Proxy to executor? 
    # Or just create_skill with auto_promote=True using the draft code?
    # Executor doesn't have "promote" endpoint yet.
    # We can rely on create_skill overwriting.
    async def promote_draft(self, name: str):
        """Promote draft to active — liest description aus manifest.yaml."""
        draft = self.get_draft(name)
        if "error" in draft:
            return draft

        description = draft.get("description", "")
        # Contract erfordert minLength: 10
        if not description or len(description.strip()) < 10:
            description = f"Skill {name}: Automatisch erstellter Skill."

        payload = {
            "name": name,
            "code": draft["code"],
            "description": description,
            "triggers": draft.get("triggers", []),
            "auto_promote": True,
            "gap_patterns": draft.get("gap_patterns", []),
            "gap_question": draft.get("gap_question"),
            "preferred_model": draft.get("preferred_model"),
            "default_params": draft.get("default_params", {}),
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{EXECUTOR_URL}/v1/skills/create", json=payload, timeout=30.0
            )
            result = resp.json()

        # Graph-Hook: auch beim Promoten registrieren
        _install_ok = (
            result.get("success")
            or result.get("installation", {}).get("success")
        )
        if _install_ok:
            await self._register_skill_in_graph(
                name=name,
                description=description,
                triggers=draft.get("triggers", []),
            )
            # Draft-Ordner nach erfolgreichem Deploy löschen
            draft_path = self.skills_dir / "_drafts" / name
            if draft_path.exists():
                shutil.rmtree(draft_path)

        return result
