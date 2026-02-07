"""
Container Commander — Full Audit Log + Dashboard API
═══════════════════════════════════════════════════════
Aggregates all system data for the dashboard view:
  - System health overview
  - Resource usage summary (total CPU, RAM, containers)
  - Audit log (container + secret + approval events)
  - Timeline (events over time)
  - Alerts (quota near limit, idle containers, expired TTL)
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def get_dashboard_overview() -> Dict:
    """
    Full system overview for the dashboard.
    Combines data from all Commander subsystems.
    """
    overview = {
        "timestamp": datetime.utcnow().isoformat(),
        "health": _get_health(),
        "resources": _get_resource_summary(),
        "containers": _get_container_summary(),
        "blueprints": _get_blueprint_summary(),
        "volumes": _get_volume_summary(),
        "alerts": _get_alerts(),
        "recent_events": _get_recent_events(limit=20),
    }
    return overview


# ── Health ────────────────────────────────────────────────

def _get_health() -> Dict:
    """System health check."""
    checks = {}

    # Docker daemon
    try:
        from .engine import get_client
        client = get_client()
        client.ping()
        checks["docker"] = {"status": "ok", "version": client.version().get("Version", "?")}
    except Exception as e:
        checks["docker"] = {"status": "error", "message": str(e)}

    # Database
    try:
        from .blueprint_store import list_blueprints
        list_blueprints()
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "message": str(e)}

    # Proxy
    try:
        from .engine import get_client
        client = get_client()
        client.containers.get("trion-proxy")
        checks["proxy"] = {"status": "ok"}
    except Exception:
        checks["proxy"] = {"status": "inactive", "message": "Not running (optional)"}

    all_ok = all(c["status"] == "ok" for c in checks.values() if c["status"] != "inactive")
    return {
        "status": "healthy" if all_ok else "degraded",
        "checks": checks,
    }


# ── Resources ─────────────────────────────────────────────

def _get_resource_summary() -> Dict:
    """Current resource usage summary."""
    try:
        from .engine import get_quota, list_containers
        q = get_quota()
        cts = list_containers()
        running = [c for c in cts if c.status.value == "running"]

        total_cpu = sum(c.cpu_percent for c in running)
        total_mem = sum(c.memory_mb for c in running)

        return {
            "quota": q.model_dump(),
            "running_count": len(running),
            "total_cpu_percent": round(total_cpu, 1),
            "total_memory_mb": round(total_mem, 1),
            "utilization_percent": round(
                (q.containers_used / max(q.max_containers, 1)) * 100, 1
            ),
        }
    except Exception as e:
        logger.error(f"[Dashboard] Resource summary: {e}")
        return {"error": str(e)}


# ── Containers ────────────────────────────────────────────

def _get_container_summary() -> Dict:
    try:
        from .engine import list_containers, get_container_stats
        cts = list_containers()
        running = [c for c in cts if c.status.value == "running"]
        stopped = [c for c in cts if c.status.value == "stopped"]

        container_details = []
        for c in running:
            try:
                stats = get_container_stats(c.container_id)
                container_details.append({
                    "id": c.container_id[:12],
                    "name": c.name,
                    "blueprint": c.blueprint_id,
                    "cpu": stats.get("cpu_percent", 0),
                    "memory_mb": stats.get("memory_mb", 0),
                    "efficiency": stats.get("efficiency", {}).get("level", "?"),
                    "runtime_sec": c.runtime_seconds,
                })
            except Exception:
                container_details.append({
                    "id": c.container_id[:12],
                    "name": c.name,
                    "blueprint": c.blueprint_id,
                })

        return {
            "running": len(running),
            "stopped": len(stopped),
            "total": len(cts),
            "details": container_details,
        }
    except Exception as e:
        return {"error": str(e)}


# ── Blueprints ────────────────────────────────────────────

def _get_blueprint_summary() -> Dict:
    try:
        from .blueprint_store import list_blueprints
        bps = list_blueprints()
        return {
            "total": len(bps),
            "by_network": _count_by(bps, lambda b: b.network.value),
            "by_tag": _count_tags(bps),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Volumes ───────────────────────────────────────────────

def _get_volume_summary() -> Dict:
    try:
        from .volumes import list_volumes, list_snapshots, cleanup_orphaned_volumes
        vols = list_volumes()
        snaps = list_snapshots()
        orphans = cleanup_orphaned_volumes(dry_run=True)
        return {
            "total_volumes": len(vols),
            "total_snapshots": len(snaps),
            "orphaned_volumes": len(orphans),
            "total_snapshot_mb": round(sum(s.get("size_mb", 0) for s in snaps), 1),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Alerts ────────────────────────────────────────────────

def _get_alerts() -> List[Dict]:
    """Generate alerts based on current system state."""
    alerts = []

    try:
        from .engine import get_quota, list_containers, get_container_stats

        q = get_quota()

        # Quota alerts
        if q.containers_used >= q.max_containers:
            alerts.append({
                "level": "critical",
                "message": f"Container-Limit erreicht: {q.containers_used}/{q.max_containers}",
                "action": "stop_container",
            })
        elif q.containers_used >= q.max_containers - 1:
            alerts.append({
                "level": "warning",
                "message": f"Nur noch 1 Container-Slot frei ({q.containers_used}/{q.max_containers})",
            })

        mem_pct = (q.memory_used_mb / q.max_total_memory_mb * 100) if q.max_total_memory_mb > 0 else 0
        if mem_pct > 90:
            alerts.append({
                "level": "critical",
                "message": f"RAM-Budget bei {mem_pct:.0f}% ({q.memory_used_mb}/{q.max_total_memory_mb} MB)",
                "action": "optimize_container",
            })
        elif mem_pct > 70:
            alerts.append({
                "level": "warning",
                "message": f"RAM-Budget bei {mem_pct:.0f}%",
            })

        # Idle container alerts
        cts = list_containers()
        for c in cts:
            if c.status.value != "running":
                continue
            try:
                stats = get_container_stats(c.container_id)
                eff = stats.get("efficiency", {})
                if eff.get("level") == "red":
                    alerts.append({
                        "level": "warning",
                        "message": f"Container '{c.name}' ist idle (Efficiency: red)",
                        "action": "stop_container",
                        "container_id": c.container_id,
                    })
            except Exception:
                pass

        # Pending approvals
        try:
            from .approval import get_pending
            pending = get_pending()
            for p in pending:
                alerts.append({
                    "level": "info",
                    "message": f"Genehmigung ausstehend: {p['reason']} ({p['blueprint_id']})",
                    "action": "approve",
                    "approval_id": p["id"],
                })
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[Dashboard] Alerts: {e}")

    return alerts


# ── Recent Events (Unified Audit) ─────────────────────────

def _get_recent_events(limit: int = 20) -> List[Dict]:
    """Merge audit logs from all sources into a unified timeline."""
    events = []

    try:
        from .blueprint_store import get_audit_log
        for entry in get_audit_log(limit=limit):
            events.append({
                "source": "container",
                "action": entry.get("action", ""),
                "target": entry.get("blueprint_id", ""),
                "details": entry.get("details", ""),
                "timestamp": entry.get("created_at", ""),
            })
    except Exception:
        pass

    try:
        from .secret_store import get_access_log
        for entry in get_access_log(limit=limit):
            events.append({
                "source": "vault",
                "action": entry.get("action", ""),
                "target": entry.get("secret_name", ""),
                "details": entry.get("accessor", ""),
                "timestamp": entry.get("created_at", ""),
            })
    except Exception:
        pass

    # Sort by timestamp, newest first
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return events[:limit]


# ── Helpers ───────────────────────────────────────────────

def _count_by(items, key_fn) -> Dict[str, int]:
    counts = {}
    for item in items:
        k = key_fn(item)
        counts[k] = counts.get(k, 0) + 1
    return counts

def _count_tags(blueprints) -> Dict[str, int]:
    counts = {}
    for bp in blueprints:
        for tag in bp.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return counts
