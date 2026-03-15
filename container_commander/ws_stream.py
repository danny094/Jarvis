"""
Container Commander — WebSocket Stream Handler
═══════════════════════════════════════════════════
Provides WebSocket endpoints for:
  - Live container log streaming
  - Interactive shell PTY (stdin/stdout + resize)
  - Event broadcast fanout for TRION activity

Protocol (JSON messages over WebSocket):
  Client → Server:
    {"type": "attach", "container_id": "abc123"}
    {"type": "exec", "container_id": "abc123", "command": "ls -la"}  # one-shot command
    {"type": "stdin", "container_id": "abc123", "data": "hello\\n"}
    {"type": "resize", "container_id": "abc123", "cols": 80, "rows": 24}
    {"type": "detach"}

  Server → Client:
    {"type": "output", "container_id": "abc123", "stream": "logs"|"shell", "data": "..."}
    {"type": "error", "message": "..."}
    {"type": "event", "event": "...", "...": "..."}
    {"type": "exit", "container_id": "abc123", "exit_code": 0}
"""

import json
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple

from fastapi import WebSocket, WebSocketDisconnect
import docker

logger = logging.getLogger(__name__)

StreamName = str
SessionKey = Tuple[int, str]  # (ws_id, container_id)

_connections: Set[WebSocket] = set()
_attached: Dict[WebSocket, str] = {}  # ws → container_id
_log_tasks: Dict[WebSocket, asyncio.Task] = {}


@dataclass
class ExecSession:
    """Interactive PTY exec session bound to one websocket + container."""

    exec_id: str
    sock: Any
    read_task: asyncio.Task


_exec_sessions: Dict[SessionKey, ExecSession] = {}
_ws_exec_index: Dict[WebSocket, Set[SessionKey]] = {}


# ── WebSocket Handler ─────────────────────────────────────

async def ws_handler(websocket: WebSocket):
    """Main WebSocket handler for terminal connections."""
    await websocket.accept()
    _connections.add(websocket)
    logger.info(f"[WS] Client connected ({len(_connections)} total)")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, {"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")
            container_id = msg.get("container_id", "")

            if msg_type == "attach":
                await _handle_attach(websocket, container_id)

            elif msg_type == "exec":
                command = msg.get("command", "")
                await _handle_exec(websocket, container_id, command)

            elif msg_type == "stdin":
                data = msg.get("data", "")
                await _handle_stdin(websocket, container_id, data)

            elif msg_type == "resize":
                cols = msg.get("cols", 80)
                rows = msg.get("rows", 24)
                await _handle_resize(websocket, container_id, cols, rows)

            elif msg_type == "detach":
                await _handle_detach(websocket)

            else:
                await _send(websocket, {"type": "error", "message": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
    finally:
        await _cleanup_ws(websocket)
        _connections.discard(websocket)


# ── Attach / Detach ───────────────────────────────────────

async def _handle_attach(ws: WebSocket, container_id: str):
    """Attach to a container's log stream."""
    if not container_id:
        await _send(ws, {"type": "error", "message": "container_id required"})
        return

    # Detach from previous log stream + shell session of previous container.
    await _detach_current(ws)

    _attached[ws] = container_id
    logger.info(f"[WS] Attached to {container_id[:12]}")

    # Start log streaming task
    task = asyncio.create_task(_stream_logs(ws, container_id))
    _log_tasks[ws] = task

    await _send(ws, {
        "type": "event",
        "event": "attached",
        "container_id": container_id,
    })


async def _handle_detach(ws: WebSocket):
    """Detach from current container."""
    await _detach_current(ws)


async def _detach_current(ws: WebSocket):
    """Detach log stream and active shell session for current attached container."""
    container_id = _attached.pop(ws, None)
    if container_id:
        task = _log_tasks.pop(ws, None)
        if task and not task.done():
            task.cancel()
        await _close_exec_session(ws, container_id)
        logger.info(f"[WS] Detached from {container_id[:12]}")


async def _stream_logs(ws: WebSocket, container_id: str):
    """Stream container logs to WebSocket in real-time."""
    try:
        from .engine import get_client
        client = get_client()
        container = client.containers.get(container_id)

        # Stream logs with follow
        log_stream = container.logs(stream=True, follow=True, timestamps=False)

        for chunk in log_stream:
            if ws not in _attached or _attached.get(ws) != container_id:
                break
            text = chunk.decode("utf-8", errors="replace")
            await _send(ws, {
                "type": "output",
                "container_id": container_id,
                "stream": "logs",
                "data": text,
            })

        # Container exited
        container.reload()
        exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
        await _send(ws, {
            "type": "exit",
            "container_id": container_id,
            "exit_code": exit_code,
        })

    except asyncio.CancelledError:
        pass
    except docker.errors.NotFound:
        await _send(ws, {"type": "error", "message": f"Container {container_id[:12]} not found"})
    except Exception as e:
        logger.error(f"[WS] Stream error: {e}")
        await _send(ws, {"type": "error", "message": str(e)})


# ── Exec ──────────────────────────────────────────────────

async def _handle_exec(ws: WebSocket, container_id: str, command: str):
    """Execute a command in the container and stream output back."""
    if not container_id or not command:
        await _send(ws, {"type": "error", "message": "container_id and command required"})
        return

    try:
        from .engine import exec_in_container
        # Run in thread to not block event loop
        loop = asyncio.get_event_loop()
        exit_code, output = await loop.run_in_executor(
            None, lambda: exec_in_container(container_id, command)
        )

        await _send(ws, {
            "type": "output",
            "container_id": container_id,
            "stream": "shell",
            "data": output + "\n",
        })
        await _send(ws, {
            "type": "exec_done",
            "container_id": container_id,
            "exit_code": exit_code,
        })

    except Exception as e:
        await _send(ws, {"type": "error", "message": f"Exec failed: {e}"})


# ── Stdin (PTY) ───────────────────────────────────────────

async def _handle_stdin(ws: WebSocket, container_id: str, data: str):
    """Forward stdin data to a container's PTY session."""
    if not container_id or not data:
        return

    try:
        session = await _ensure_exec_session(ws, container_id)
        if not session:
            await _send(ws, {"type": "error", "message": f"Could not open shell for {container_id[:12]}"})
            return

        # Write stdin data
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: session.sock._sock.send(data.encode("utf-8")))

    except Exception as e:
        logger.error(f"[WS] Stdin error: {e}")
        await _send(ws, {"type": "error", "message": f"Stdin failed: {e}"})


async def _read_pty_output(ws: WebSocket, container_id: str, session_key: SessionKey):
    """Read PTY output and forward to WebSocket."""
    session = _exec_sessions.get(session_key)
    if not session:
        return
    sock = session.sock
    try:
        loop = asyncio.get_event_loop()
        while True:
            data = await loop.run_in_executor(None, lambda: sock._sock.recv(4096))
            if not data:
                break
            text = data.decode("utf-8", errors="replace")
            await _send(ws, {
                "type": "output",
                "container_id": container_id,
                "stream": "shell",
                "data": text,
            })
    except Exception as e:
        logger.debug(f"[WS] PTY read ended: {e}")
    finally:
        await _close_exec_session_by_key(session_key)


# ── Resize ────────────────────────────────────────────────

async def _handle_resize(ws: WebSocket, container_id: str, cols: int, rows: int):
    """Resize the active interactive exec PTY for this websocket + container."""
    if not container_id:
        return
    cols = int(cols or 80)
    rows = int(rows or 24)
    if cols <= 0 or rows <= 0:
        return
    key = _session_key(ws, container_id)
    session = _exec_sessions.get(key)
    if not session:
        return
    try:
        from .engine import get_client
        client = get_client()
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.api.exec_resize(session.exec_id, height=rows, width=cols),
        )
    except Exception as e:
        logger.debug(f"[WS] Resize error (non-fatal): {e}")


# ── Broadcast Events ─────────────────────────────────────

async def broadcast_event(event: str, data: dict):
    """Broadcast an event to all connected WebSocket clients."""
    msg = {"type": "event", "event": event, **data}
    dead = set()
    for ws in _connections:
        try:
            await _send(ws, msg)
        except Exception:
            dead.add(ws)
    _connections -= dead


def broadcast_event_sync(event: str, data: dict):
    """Synchronous wrapper for broadcasting from non-async code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast_event(event, data))
        else:
            loop.run_until_complete(broadcast_event(event, data))
    except RuntimeError:
        # No event loop — create one
        asyncio.run(broadcast_event(event, data))


def emit_activity(event: str, level: str = "info", message: str = "", **data):
    """
    Unified sync event emitter for TRION activity feed.
    Adds stable metadata used by WebUI.
    """
    payload = {
        "event": event,
        "level": level,
        "message": message or event.replace("_", " "),
        **data,
    }
    # broadcast_event_sync expects the event name separate from payload body.
    payload_without_event = dict(payload)
    payload_without_event.pop("event", None)
    broadcast_event_sync(event, payload_without_event)


# ── Helper ────────────────────────────────────────────────

async def _send(ws: WebSocket, data: dict):
    """Send JSON message to a WebSocket client."""
    try:
        await ws.send_text(json.dumps(data))
    except Exception:
        pass


def _session_key(ws: WebSocket, container_id: str) -> SessionKey:
    return (id(ws), container_id)


async def _ensure_exec_session(ws: WebSocket, container_id: str) -> Optional[ExecSession]:
    """Ensure interactive PTY session exists for websocket+container."""
    key = _session_key(ws, container_id)
    existing = _exec_sessions.get(key)
    if existing:
        return existing
    try:
        from .engine import get_client

        client = get_client()
        container = client.containers.get(container_id)
        created = client.api.exec_create(
            container.id,
            "/bin/sh",
            stdin=True,
            tty=True,
            stdout=True,
            stderr=True,
        )
        exec_id = created.get("Id") if isinstance(created, dict) else str(created)
        sock = client.api.exec_start(exec_id, socket=True, tty=True)
        read_task = asyncio.create_task(_read_pty_output(ws, container_id, key))
        session = ExecSession(exec_id=exec_id, sock=sock, read_task=read_task)
        _exec_sessions[key] = session
        _ws_exec_index.setdefault(ws, set()).add(key)
        return session
    except Exception as e:
        logger.error(f"[WS] PTY session create failed for {container_id[:12]}: {e}")
        return None


async def _close_exec_session(ws: WebSocket, container_id: str):
    await _close_exec_session_by_key(_session_key(ws, container_id))


async def _close_exec_session_by_key(key: SessionKey):
    session = _exec_sessions.pop(key, None)
    if not session:
        return
    read_task = session.read_task
    if read_task and not read_task.done():
        read_task.cancel()
    try:
        await asyncio.get_event_loop().run_in_executor(None, lambda: session.sock.close())
    except Exception:
        pass
    ws_to_cleanup = None
    for ws, keys in list(_ws_exec_index.items()):
        if key in keys:
            keys.discard(key)
            if not keys:
                ws_to_cleanup = ws
            break
    if ws_to_cleanup is not None:
        _ws_exec_index.pop(ws_to_cleanup, None)


async def _cleanup_ws(ws: WebSocket):
    """Cleanup all resources for disconnected websocket."""
    # Cancel active log stream.
    task = _log_tasks.pop(ws, None)
    if task and not task.done():
        task.cancel()
    # Close active attach.
    _attached.pop(ws, None)
    # Close all PTY sessions bound to this websocket.
    keys = list(_ws_exec_index.get(ws, set()))
    for key in keys:
        await _close_exec_session_by_key(key)
    _ws_exec_index.pop(ws, None)
