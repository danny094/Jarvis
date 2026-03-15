#!/usr/bin/env python3
"""
Time MCP Server (line-based JSON-RPC over STDIO).

This implementation intentionally matches the hub's current STDIO transport:
- one JSON-RPC request per line on stdin
- one JSON-RPC response per line on stdout
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


CONFIG_PATH = Path(__file__).with_name("config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "name": "time-mcp",
    "description": "Simple MCP server providing current time information",
    "timezone": "UTC",
    "country": "US",
    "region": "",
    "locale": "en-US",
    "hour_cycle": "24h",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_current_time",
        "description": "Get current time with timezone/location context",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["utc", "local", "iso", "timestamp", "all"],
                    "default": "all",
                    "description": "Output format",
                },
                "timezone": {
                    "type": "string",
                    "description": "Optional IANA timezone override, e.g. Europe/Berlin",
                },
            },
        },
    },
    {
        "name": "get_timezone",
        "description": "Get timezone metadata and configured location preferences",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update(raw)
    except Exception:
        pass

    cfg["timezone"] = str(cfg.get("timezone") or "").strip() or "UTC"
    cfg["country"] = str(cfg.get("country") or "").strip()
    cfg["region"] = str(cfg.get("region") or "").strip()
    cfg["locale"] = str(cfg.get("locale") or "").strip() or "en-US"
    cycle = str(cfg.get("hour_cycle") or "").strip().lower()
    cfg["hour_cycle"] = "12h" if cycle == "12h" else "24h"
    return cfg


def _resolve_timezone(cfg: dict[str, Any], override: str = "") -> tuple[Any, str]:
    candidate = str(override or cfg.get("timezone") or "").strip()
    if candidate:
        try:
            return ZoneInfo(candidate), candidate
        except ZoneInfoNotFoundError:
            pass

    local = datetime.now().astimezone().tzinfo
    if isinstance(local, ZoneInfo):
        return local, getattr(local, "key", str(local))
    return timezone.utc, "UTC"


def _offset_label(dt: datetime) -> str:
    off = dt.utcoffset() or timedelta(0)
    total_minutes = int(off.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    abs_minutes = abs(total_minutes)
    hours = abs_minutes // 60
    minutes = abs_minutes % 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _format_local(dt: datetime, hour_cycle: str) -> str:
    if hour_cycle == "12h":
        return dt.strftime("%Y-%m-%d %I:%M:%S %p")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _json_content(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False),
            }
        ]
    }


def _tool_get_current_time(arguments: dict[str, Any]) -> dict[str, Any]:
    cfg = _load_config()
    fmt = str(arguments.get("format", "all") or "all").strip().lower()
    tz_override = str(arguments.get("timezone") or "").strip()
    tzinfo, tz_name = _resolve_timezone(cfg, tz_override)

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tzinfo)

    full = {
        "utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "local": _format_local(now_local, cfg["hour_cycle"]),
        "iso": now_local.isoformat(),
        "timestamp": int(now_utc.timestamp()),
        "timezone": tz_name,
        "utc_offset": _offset_label(now_local),
        "country": cfg.get("country", ""),
        "region": cfg.get("region", ""),
        "locale": cfg.get("locale", "en-US"),
        "hour_cycle": cfg.get("hour_cycle", "24h"),
    }

    if fmt in {"utc", "local", "iso", "timestamp"}:
        return _json_content({fmt: full[fmt], "timezone": tz_name})
    if fmt not in {"all", ""}:
        return _json_content({"error": f"Unsupported format '{fmt}'", **full})
    return _json_content(full)


def _tool_get_timezone(arguments: dict[str, Any]) -> dict[str, Any]:
    _ = arguments
    cfg = _load_config()
    tzinfo, tz_name = _resolve_timezone(cfg)
    now_local = datetime.now(timezone.utc).astimezone(tzinfo)
    offset = now_local.utcoffset() or timedelta(0)

    payload = {
        "timezone_name": tz_name,
        "utc_offset": _offset_label(now_local),
        "utc_offset_hours": offset.total_seconds() / 3600.0,
        "is_dst": bool(now_local.dst()),
        "country": cfg.get("country", ""),
        "region": cfg.get("region", ""),
        "locale": cfg.get("locale", "en-US"),
        "hour_cycle": cfg.get("hour_cycle", "24h"),
    }
    return _json_content(payload)


def _response_ok(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _response_err(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    request_id = req.get("id")
    method = str(req.get("method") or "").strip()
    params = req.get("params") if isinstance(req.get("params"), dict) else {}

    if method == "initialize":
        return _response_ok(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "time-mcp", "version": "1.1.0"},
                "capabilities": {"tools": {"listChanged": False}},
            },
        )

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return _response_ok(request_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not tool_name:
            return _response_err(request_id, -32602, "Missing tool name")
        if tool_name == "get_current_time":
            return _response_ok(request_id, _tool_get_current_time(arguments))
        if tool_name == "get_timezone":
            return _response_ok(request_id, _tool_get_timezone(arguments))
        return _response_err(request_id, -32601, f"Unknown tool: {tool_name}")

    return _response_err(request_id, -32601, f"Method not found: {method}")


def main() -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("Request must be a JSON object")
        except Exception as exc:
            err = _response_err(None, -32700, f"Invalid JSON: {exc}")
            sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue

        resp = _handle_request(req)
        if resp is None:
            continue
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
