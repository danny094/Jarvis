"""
Container Commander — Blueprint Marketplace
═══════════════════════════════════════════════════
Share, export, and import blueprint bundles.

Bundle format (.trion-bundle.tar.gz):
  blueprint.yaml      — Blueprint definition
  Dockerfile          — Optional embedded Dockerfile
  README.md           — Description, usage, examples
  meta.json           — Author, version, tags, checksum

Features:
  - Export blueprint as shareable bundle
  - Import bundle from file
  - Built-in blueprint library (starter templates)
  - Bundle validation + checksum
"""

import os
import io
import json
import tarfile
import hashlib
import logging
import re
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
from datetime import datetime
from typing import Optional, List, Dict

import yaml

logger = logging.getLogger(__name__)

MARKETPLACE_DIR = os.environ.get("MARKETPLACE_DIR", "/app/data/marketplace")
MARKETPLACE_CATALOG_CACHE = os.environ.get(
    "MARKETPLACE_CATALOG_CACHE",
    os.path.join(MARKETPLACE_DIR, "catalog_cache.json"),
)
MARKETPLACE_DEFAULT_CATALOG_REPO = os.environ.get("TRION_BLUEPRINT_CATALOG_REPO", "")
MARKETPLACE_DEFAULT_CATALOG_BRANCH = os.environ.get("TRION_BLUEPRINT_CATALOG_BRANCH", "main")


# ── Built-in Starter Blueprints ──────────────────────────

STARTER_BLUEPRINTS = [
    {
        "id": "python-sandbox",
        "name": "Python Sandbox",
        "description": "Python 3.12 with pip, numpy, pandas. Ideal for data analysis and scripting.",
        "icon": "🐍",
        "tags": ["python", "data", "starter"],
        "network": "none",
        "dockerfile": "FROM python:3.12-slim\nRUN pip install --no-cache-dir numpy pandas matplotlib requests\nWORKDIR /workspace\nCMD [\"python3\", \"-i\"]",
        "resources": {"cpu_limit": "1.0", "memory_limit": "512m", "timeout_seconds": 600},
    },
    {
        "id": "node-sandbox",
        "name": "Node.js Sandbox",
        "description": "Node.js 20 LTS with npm. For JS/TS development and scripting.",
        "icon": "🟢",
        "tags": ["node", "javascript", "starter"],
        "network": "none",
        "dockerfile": "FROM node:20-slim\nWORKDIR /workspace\nCMD [\"node\"]",
        "resources": {"cpu_limit": "1.0", "memory_limit": "512m", "timeout_seconds": 600},
    },
    {
        "id": "web-scraper",
        "name": "Web Scraper",
        "description": "Python with BeautifulSoup, Selenium, playwright. Needs internet (approval required).",
        "icon": "🕷️",
        "tags": ["python", "web", "scraping"],
        "network": "full",
        "allowed_domains": ["*.github.com", "*.stackoverflow.com"],
        "dockerfile": "FROM python:3.12-slim\nRUN pip install --no-cache-dir beautifulsoup4 requests lxml httpx\nWORKDIR /workspace\nCMD [\"python3\", \"-i\"]",
        "resources": {"cpu_limit": "0.5", "memory_limit": "256m", "timeout_seconds": 300},
    },
    {
        "id": "db-sandbox",
        "name": "Database Sandbox",
        "description": "SQLite + PostgreSQL client tools for database work.",
        "icon": "🗄️",
        "tags": ["database", "sql", "starter"],
        "network": "internal",
        "dockerfile": "FROM python:3.12-slim\nRUN pip install --no-cache-dir sqlalchemy psycopg2-binary sqlite-utils\nRUN apt-get update && apt-get install -y --no-install-recommends postgresql-client sqlite3 && rm -rf /var/lib/apt/lists/*\nWORKDIR /workspace\nCMD [\"python3\", \"-i\"]",
        "resources": {"cpu_limit": "0.5", "memory_limit": "256m", "timeout_seconds": 300},
    },
    {
        "id": "latex-builder",
        "name": "LaTeX Builder",
        "description": "Full TeX Live for PDF document generation.",
        "icon": "📄",
        "tags": ["latex", "pdf", "documents"],
        "network": "none",
        "dockerfile": "FROM texlive/texlive:latest-minimal\nRUN tlmgr install collection-basic collection-latex collection-fontsrecommended\nWORKDIR /workspace\nCMD [\"/bin/sh\"]",
        "resources": {"cpu_limit": "2.0", "memory_limit": "1g", "timeout_seconds": 900},
    },
]


# ── Export ────────────────────────────────────────────────

def export_bundle(blueprint_id: str) -> Optional[str]:
    """
    Export a blueprint as a .trion-bundle.tar.gz file.
    Returns the filepath or None.
    """
    from .blueprint_store import resolve_blueprint

    bp = resolve_blueprint(blueprint_id)
    if not bp:
        return None

    os.makedirs(MARKETPLACE_DIR, exist_ok=True)

    # Build YAML
    bp_dict = bp.model_dump()
    bp_yaml = yaml.dump(bp_dict, default_flow_style=False, allow_unicode=True)

    # Meta
    meta = {
        "id": bp.id,
        "name": bp.name,
        "version": "1.0.0",
        "author": "TRION",
        "exported_at": datetime.utcnow().isoformat(),
        "tags": bp.tags,
        "checksum": hashlib.sha256(bp_yaml.encode()).hexdigest(),
    }

    # Build tarball
    filename = f"{blueprint_id}.trion-bundle.tar.gz"
    filepath = os.path.join(MARKETPLACE_DIR, filename)

    with tarfile.open(filepath, "w:gz") as tar:
        # blueprint.yaml
        _add_string_to_tar(tar, "blueprint.yaml", bp_yaml)
        # meta.json
        _add_string_to_tar(tar, "meta.json", json.dumps(meta, indent=2))
        # Dockerfile
        if bp.dockerfile:
            _add_string_to_tar(tar, "Dockerfile", bp.dockerfile)
        # README
        readme = f"# {bp.name}\n\n{bp.description}\n\n## Tags\n{', '.join(bp.tags)}\n"
        _add_string_to_tar(tar, "README.md", readme)

    logger.info(f"[Marketplace] Exported: {filename}")
    return filename


def import_bundle(filepath_or_bytes, filename: str = "") -> Optional[Dict]:
    """
    Import a .trion-bundle.tar.gz and create the blueprint.
    Accepts a filepath (str) or bytes.
    Returns the created blueprint dict or None.
    """
    from .blueprint_store import create_blueprint, get_blueprint
    from .models import Blueprint, ResourceLimits, NetworkMode

    try:
        if isinstance(filepath_or_bytes, str):
            tar = tarfile.open(filepath_or_bytes, "r:gz")
        else:
            tar = tarfile.open(fileobj=io.BytesIO(filepath_or_bytes), mode="r:gz")

        # Read blueprint.yaml
        bp_yaml = tar.extractfile("blueprint.yaml").read().decode("utf-8")
        bp_data = yaml.safe_load(bp_yaml)

        # Read meta
        try:
            meta_raw = tar.extractfile("meta.json").read().decode("utf-8")
            meta = json.loads(meta_raw)
        except Exception:
            meta = {}

        # Verify checksum
        if meta.get("checksum"):
            actual = hashlib.sha256(bp_yaml.encode()).hexdigest()
            if actual != meta["checksum"]:
                logger.warning(f"[Marketplace] Checksum mismatch for {filename}")

        tar.close()

        # Create blueprint
        resources = ResourceLimits(**(bp_data.pop("resources", {})))
        network = NetworkMode(bp_data.pop("network", "internal"))

        # Clean fields
        for key in list(bp_data.keys()):
            if key not in Blueprint.model_fields:
                bp_data.pop(key)

        bp = Blueprint(resources=resources, network=network, **bp_data)

        # Check if exists
        existing = get_blueprint(bp.id)
        if existing:
            return {"error": f"Blueprint '{bp.id}' already exists", "blueprint": existing.model_dump()}

        created = create_blueprint(bp)
        logger.info(f"[Marketplace] Imported: {bp.id}")
        return {"imported": True, "blueprint": created.model_dump(), "meta": meta}

    except Exception as e:
        logger.error(f"[Marketplace] Import failed: {e}")
        return {"error": str(e)}


# ── Bundle Listing ────────────────────────────────────────

def list_bundles() -> List[Dict]:
    """List all available bundles in the marketplace directory."""
    if not os.path.exists(MARKETPLACE_DIR):
        return []

    result = []
    for f in sorted(os.listdir(MARKETPLACE_DIR)):
        if not f.endswith(".trion-bundle.tar.gz"):
            continue
        filepath = os.path.join(MARKETPLACE_DIR, f)
        stat = os.stat(filepath)

        # Try to read meta
        meta = {}
        try:
            with tarfile.open(filepath, "r:gz") as tar:
                meta_raw = tar.extractfile("meta.json").read().decode("utf-8")
                meta = json.loads(meta_raw)
        except Exception:
            pass

        result.append({
            "filename": f,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "id": meta.get("id", f.replace(".trion-bundle.tar.gz", "")),
            "name": meta.get("name", ""),
            "version": meta.get("version", ""),
            "tags": meta.get("tags", []),
            "exported_at": meta.get("exported_at", ""),
        })

    return result


def get_starters() -> List[Dict]:
    """Get the built-in starter blueprints."""
    return STARTER_BLUEPRINTS


def install_starter(starter_id: str) -> Optional[Dict]:
    """Install a starter blueprint from the built-in library."""
    from .blueprint_store import create_blueprint, get_blueprint
    from .models import Blueprint, ResourceLimits, NetworkMode

    starter = next((s for s in STARTER_BLUEPRINTS if s["id"] == starter_id), None)
    if not starter:
        return {"error": f"Starter '{starter_id}' not found"}

    existing = get_blueprint(starter_id)
    if existing:
        return {"exists": True, "blueprint": existing.model_dump()}

    data = dict(starter)
    resources = ResourceLimits(**(data.pop("resources", {})))
    network = NetworkMode(data.pop("network", "internal"))
    data.pop("allowed_domains", None)

    bp = Blueprint(resources=resources, network=network, **data)
    created = create_blueprint(bp)
    return {"installed": True, "blueprint": created.model_dump()}


# ── Helpers ───────────────────────────────────────────────

def _add_string_to_tar(tar: tarfile.TarFile, name: str, content: str):
    data = content.encode("utf-8")
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


# ── Remote Catalog (GitHub) ───────────────────────────────

_SECRET_REF_RE = re.compile(r"^\{\{\s*SECRET\s*:\s*([A-Za-z0-9_]+)\s*\}\}$")


def _ensure_marketplace_dir() -> None:
    os.makedirs(MARKETPLACE_DIR, exist_ok=True)


def _http_get_text(url: str, timeout: int = 20) -> str:
    req = Request(
        url=url,
        headers={
            "User-Agent": "TRION-Blueprint-Catalog/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _resolve_github_raw(repo_url: str, branch: str = "main") -> Dict[str, str]:
    raw_input = str(repo_url or "").strip()
    if not raw_input:
        raise ValueError("repo_url is required")
    if not raw_input.startswith("http://") and not raw_input.startswith("https://"):
        raw_input = f"https://{raw_input}"

    parsed = urlparse(raw_input)
    host = (parsed.netloc or "").lower()
    path_parts = [p for p in (parsed.path or "").split("/") if p]
    target_branch = str(branch or "main").strip() or "main"

    if host in {"github.com", "www.github.com"}:
        if len(path_parts) < 2:
            raise ValueError("repo_url must be like https://github.com/<owner>/<repo>")
        owner = path_parts[0]
        repo = path_parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
    elif host == "raw.githubusercontent.com":
        if len(path_parts) < 3:
            raise ValueError("raw github url must contain owner/repo/branch")
        owner = path_parts[0]
        repo = path_parts[1]
        target_branch = path_parts[2]
    else:
        raise ValueError("only github.com or raw.githubusercontent.com are supported")

    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{target_branch}/"
    index_url = urljoin(raw_base, "index.json")
    canonical_repo_url = f"https://github.com/{owner}/{repo}"
    return {
        "repo_url": canonical_repo_url,
        "branch": target_branch,
        "raw_base": raw_base,
        "index_url": index_url,
    }


def _default_catalog_repo_from_settings() -> str:
    try:
        from utils.settings import settings as runtime_settings

        collections = runtime_settings.get("TRION_REFERENCE_LINK_COLLECTIONS", {})
        if not isinstance(collections, dict):
            return ""
        rows = collections.get("blueprints", [])
        if not isinstance(rows, list):
            return ""
        for row in rows:
            item = row if isinstance(row, dict) else {}
            if not bool(item.get("enabled", True)):
                continue
            url = str(item.get("url", "")).strip()
            if url:
                return url
    except Exception:
        return ""
    return ""


def _normalize_health_profile(raw: Dict) -> Dict[str, int]:
    data = raw if isinstance(raw, dict) else {}

    def _to_int(key: str, fallback: int) -> int:
        try:
            value = int(float(data.get(key, fallback)))
        except Exception:
            value = fallback
        return max(1, min(3600, value))

    ready_timeout = _to_int("ready_timeout_seconds", _to_int("timeout", 60))
    interval = _to_int("interval_seconds", _to_int("check_interval", 15))
    timeout = _to_int("timeout_seconds", 5)
    retries = _to_int("retries", 3)
    return {
        "ready_timeout_seconds": ready_timeout,
        "interval_seconds": interval,
        "timeout_seconds": timeout,
        "retries": retries,
    }


def _normalize_catalog_entry(raw: Dict, raw_base: str) -> Dict:
    item = raw if isinstance(raw, dict) else {}
    bp_id = str(item.get("id", "")).strip()
    name = str(item.get("name", "")).strip()
    yaml_url = str(item.get("yaml_url", "")).strip()
    if not bp_id or not name or not yaml_url:
        raise ValueError("blueprint entry requires id, name, yaml_url")

    parsed_yaml = urlparse(yaml_url)
    resolved_yaml_url = yaml_url if parsed_yaml.scheme in {"http", "https"} else urljoin(raw_base, yaml_url)
    bundle_url = str(item.get("bundle_url", "")).strip()
    if bundle_url and not urlparse(bundle_url).scheme:
        bundle_url = urljoin(raw_base, bundle_url)

    tags = [str(t).strip() for t in (item.get("tags") or []) if str(t).strip()]
    profile = _normalize_health_profile(item.get("health_profile") or {})
    network = str(item.get("network", "internal")).strip().lower() or "internal"
    requires_approval = bool(item.get("requires_approval", False) or network == "full")

    return {
        "id": bp_id,
        "name": name,
        "description": str(item.get("description", "")).strip(),
        "category": str(item.get("category", "uncategorized")).strip().lower() or "uncategorized",
        "tags": tags,
        "icon": str(item.get("icon", "📦")).strip() or "📦",
        "difficulty": str(item.get("difficulty", "")).strip().lower(),
        "network": network,
        "requires_secrets": bool(item.get("requires_secrets", False)),
        "requires_runtime": str(item.get("requires_runtime", "none")).strip().lower() or "none",
        "requires_approval": requires_approval,
        "requires_gpu": bool(item.get("requires_gpu", False)),
        "trusted_level": str(item.get("trusted_level", "unverified")).strip().lower() or "unverified",
        "author": str(item.get("author", "")).strip(),
        "version": str(item.get("version", "1.0.0")).strip() or "1.0.0",
        "yaml_url": resolved_yaml_url,
        "bundle_url": bundle_url,
        "downloads": int(item.get("downloads", 0) or 0),
        "stars": int(item.get("stars", 0) or 0),
        "health_profile": profile,
    }


def _load_catalog_cache() -> Dict:
    try:
        if not os.path.exists(MARKETPLACE_CATALOG_CACHE):
            return {}
        with open(MARKETPLACE_CATALOG_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_catalog_cache(payload: Dict) -> None:
    _ensure_marketplace_dir()
    with open(MARKETPLACE_CATALOG_CACHE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def sync_remote_catalog(repo_url: str = "", branch: str = "main") -> Dict:
    source_url = str(repo_url or "").strip() or _default_catalog_repo_from_settings() or MARKETPLACE_DEFAULT_CATALOG_REPO
    if not source_url:
        raise ValueError("repo_url missing: pass repo_url or configure settings reference-links (blueprints)")

    resolved = _resolve_github_raw(source_url, branch=branch or MARKETPLACE_DEFAULT_CATALOG_BRANCH)
    raw_index = _http_get_text(resolved["index_url"], timeout=20)
    payload = json.loads(raw_index)
    if not isinstance(payload, dict):
        raise ValueError("index.json must be an object")

    raw_blueprints = payload.get("blueprints") or []
    if not isinstance(raw_blueprints, list):
        raise ValueError("index.json: 'blueprints' must be a list")

    normalized: List[Dict] = []
    categories: Dict[str, int] = {}
    for entry in raw_blueprints:
        row = _normalize_catalog_entry(entry if isinstance(entry, dict) else {}, resolved["raw_base"])
        normalized.append(row)
        categories[row["category"]] = int(categories.get(row["category"], 0)) + 1

    now = datetime.utcnow().isoformat() + "Z"
    cache = {
        "schema_version": str(payload.get("schema_version", "1.0.0")),
        "trion_compat": payload.get("trion_compat") if isinstance(payload.get("trion_compat"), dict) else {},
        "synced_at": now,
        "source": {
            "repo_url": resolved["repo_url"],
            "branch": resolved["branch"],
            "index_url": resolved["index_url"],
            "raw_base": resolved["raw_base"],
        },
        "categories": categories,
        "blueprints": normalized,
    }
    _save_catalog_cache(cache)
    return {
        "synced": True,
        "count": len(normalized),
        "categories": categories,
        "synced_at": now,
        "source": cache["source"],
        "schema_version": cache["schema_version"],
        "trion_compat": cache["trion_compat"],
    }


def get_catalog_cache() -> Dict:
    return _load_catalog_cache()


def list_catalog(category: str = "", trusted_only: bool = False) -> Dict:
    cache = _load_catalog_cache()
    rows = cache.get("blueprints") if isinstance(cache.get("blueprints"), list) else []
    requested_category = str(category or "").strip().lower()
    if requested_category:
        rows = [r for r in rows if str(r.get("category", "")).lower() == requested_category]
    if trusted_only:
        rows = [r for r in rows if str(r.get("trusted_level", "")).lower() in {"verified", "trusted"}]
    return {
        "source": cache.get("source", {}),
        "schema_version": cache.get("schema_version", ""),
        "trion_compat": cache.get("trion_compat", {}),
        "synced_at": cache.get("synced_at", ""),
        "categories": cache.get("categories", {}),
        "blueprints": rows,
        "count": len(rows),
        "category": requested_category or "all",
        "trusted_only": bool(trusted_only),
    }


def _convert_env_secrets(env: Dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    source = env if isinstance(env, dict) else {}
    for k, v in source.items():
        key = str(k).strip()
        if not key:
            continue
        value = str(v)
        m = _SECRET_REF_RE.match(value.strip())
        if m:
            out[key] = f"vault://{m.group(1).upper()}"
        else:
            out[key] = value
    return out


def install_catalog_blueprint(blueprint_id: str, overwrite: bool = False) -> Dict:
    from .blueprint_store import create_blueprint, get_blueprint, update_blueprint
    from .models import Blueprint

    catalog = _load_catalog_cache()
    rows = catalog.get("blueprints") if isinstance(catalog.get("blueprints"), list) else []
    target = next((r for r in rows if str(r.get("id", "")).strip() == str(blueprint_id).strip()), None)
    if not target:
        return {"error": f"catalog_blueprint_not_found: {blueprint_id}"}

    yaml_url = str(target.get("yaml_url", "")).strip()
    if not yaml_url:
        return {"error": f"catalog_blueprint_missing_yaml_url: {blueprint_id}"}

    raw_yaml = _http_get_text(yaml_url, timeout=20)
    data = yaml.safe_load(raw_yaml)
    if not isinstance(data, dict):
        return {"error": f"invalid_blueprint_yaml: {blueprint_id}"}

    payload = dict(data)
    payload["id"] = str(payload.get("id") or target["id"]).strip()
    payload["name"] = str(payload.get("name") or target["name"]).strip()
    payload["description"] = str(payload.get("description") or target.get("description", "")).strip()
    payload["icon"] = str(payload.get("icon") or target.get("icon", "📦")).strip() or "📦"
    payload["tags"] = payload.get("tags") if isinstance(payload.get("tags"), list) else target.get("tags", [])
    payload["network"] = str(payload.get("network") or target.get("network", "internal")).strip().lower() or "internal"

    payload["environment"] = _convert_env_secrets(payload.get("environment") or {})

    profile = target.get("health_profile") if isinstance(target.get("health_profile"), dict) else {}
    health_cfg = payload.get("healthcheck") if isinstance(payload.get("healthcheck"), dict) else {}
    if profile:
        if "interval_seconds" not in health_cfg and "interval_seconds" in profile:
            health_cfg["interval_seconds"] = profile["interval_seconds"]
        if "timeout_seconds" not in health_cfg and "timeout_seconds" in profile:
            health_cfg["timeout_seconds"] = profile["timeout_seconds"]
        if "retries" not in health_cfg and "retries" in profile:
            health_cfg["retries"] = profile["retries"]
        if "ready_timeout_seconds" not in health_cfg and "ready_timeout_seconds" in profile:
            health_cfg["ready_timeout_seconds"] = profile["ready_timeout_seconds"]
    payload["healthcheck"] = health_cfg

    safe_payload = {k: v for k, v in payload.items() if k in Blueprint.model_fields}
    bp = Blueprint(**safe_payload)

    existing = get_blueprint(bp.id)
    if existing and not overwrite:
        return {"exists": True, "blueprint": existing.model_dump(), "source": target}

    if existing and overwrite:
        updated = update_blueprint(bp.id, bp.model_dump())
        return {"updated": True, "blueprint": updated.model_dump() if updated else bp.model_dump(), "source": target}

    created = create_blueprint(bp)
    return {"installed": True, "blueprint": created.model_dump(), "source": target}
