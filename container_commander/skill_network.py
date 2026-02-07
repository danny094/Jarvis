"""
Container Commander — Skill-Aware Networking
═══════════════════════════════════════════════════
Automatically configures network access based on the skill
a container is serving.

Integration with Skill Server:
  - When KI needs to execute a skill that requires a container,
    the skill definition includes network requirements
  - Skill-aware networking auto-resolves the right network mode
  - Skills can declare required domains for whitelist proxy

Skill Metadata (from skill-server):
  {
    "skill_id": "web-research",
    "requires_network": true,
    "allowed_domains": ["api.google.com", "*.wikipedia.org"],
    "network_level": "proxy",  // none | internal | proxy | full
    "blueprint_id": "web-scraper"
  }

Network Levels:
  none     → No network (default for code execution skills)
  internal → Can talk to other TRION services (DB, cache)
  proxy    → Internet via Squid whitelist proxy (most web skills)
  full     → Direct internet (requires Human-in-the-Loop)
"""

import logging
from typing import Optional, Dict, List

from .models import NetworkMode

logger = logging.getLogger(__name__)


# ── Skill Network Resolution ─────────────────────────────

def resolve_skill_network(skill_meta: Dict) -> Dict:
    """
    Given skill metadata, determine the network config for the container.

    Returns:
      {
        "network_mode": NetworkMode,
        "proxy_domains": [...],     # domains for whitelist proxy
        "env_inject": {...},        # extra env vars to inject
        "requires_approval": bool,  # needs Human-in-the-Loop?
      }
    """
    requires_network = skill_meta.get("requires_network", False)
    network_level = skill_meta.get("network_level", "none")
    allowed_domains = skill_meta.get("allowed_domains", [])
    skill_id = skill_meta.get("skill_id", "unknown")

    if not requires_network or network_level == "none":
        return {
            "network_mode": NetworkMode.NONE,
            "proxy_domains": [],
            "env_inject": {},
            "requires_approval": False,
        }

    if network_level == "internal":
        return {
            "network_mode": NetworkMode.INTERNAL,
            "proxy_domains": [],
            "env_inject": {},
            "requires_approval": False,
        }

    if network_level == "proxy":
        # Use whitelist proxy
        from .proxy import get_proxy_env, ensure_proxy_running, set_whitelist

        blueprint_id = skill_meta.get("blueprint_id", skill_id)
        ensure_proxy_running()
        set_whitelist(blueprint_id, allowed_domains)
        proxy_env = get_proxy_env(blueprint_id)

        logger.info(f"[SkillNet] Proxy mode for skill '{skill_id}': {len(allowed_domains)} domains")

        return {
            "network_mode": NetworkMode.INTERNAL,  # Internal + proxy
            "proxy_domains": allowed_domains,
            "env_inject": proxy_env,
            "requires_approval": False,
        }

    if network_level == "full":
        return {
            "network_mode": NetworkMode.FULL,
            "proxy_domains": [],
            "env_inject": {},
            "requires_approval": True,
        }

    # Fallback
    return {
        "network_mode": NetworkMode.NONE,
        "proxy_domains": [],
        "env_inject": {},
        "requires_approval": False,
    }


def get_skill_network_summary(skill_meta: Dict) -> str:
    """Human-readable summary of network config for a skill."""
    level = skill_meta.get("network_level", "none")
    domains = skill_meta.get("allowed_domains", [])

    if level == "none":
        return "🔒 Kein Netzwerk — reine Code-Ausführung"
    elif level == "internal":
        return "🔗 Internes TRION-Netzwerk — nur andere Services"
    elif level == "proxy":
        d = ", ".join(domains[:3])
        more = f" +{len(domains)-3}" if len(domains) > 3 else ""
        return f"🌐 Proxy-Zugang: {d}{more}"
    elif level == "full":
        return "⚠️ Voller Internet-Zugang — benötigt Genehmigung"
    return "❓ Unbekannt"


# ── Skill Registry Integration ────────────────────────────

_skill_network_cache: Dict[str, Dict] = {}


def register_skill_network(skill_id: str, network_config: Dict):
    """Cache a skill's network config for quick lookup."""
    _skill_network_cache[skill_id] = network_config
    logger.debug(f"[SkillNet] Registered: {skill_id} → {network_config.get('network_level', 'none')}")


def get_cached_config(skill_id: str) -> Optional[Dict]:
    """Get cached network config for a skill."""
    return _skill_network_cache.get(skill_id)


def list_skill_networks() -> List[Dict]:
    """List all registered skill network configs."""
    return [
        {"skill_id": sid, **config}
        for sid, config in _skill_network_cache.items()
    ]
