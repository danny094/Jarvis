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
from datetime import datetime
from typing import Optional, List, Dict

import yaml

logger = logging.getLogger(__name__)

MARKETPLACE_DIR = os.environ.get("MARKETPLACE_DIR", "/app/data/marketplace")


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
