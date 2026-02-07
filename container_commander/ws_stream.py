"""
Container Commander — WebSocket Stream Handler
═══════════════════════════════════════════════════
Provides WebSocket endpoints for:
  - Live container log streaming
  - Container exec with PTY (stdin/stdout)
  - SSE events (container_started, container_stopped, approval_needed)

Protocol (JSON messages over WebSocket):
  Client → Server:
    {"type": "attach", "container_id": "abc123"}
    {"type": "exec", "container_id": "abc123", "command": "ls -la"}
    {"type": "stdin", "container_id": "abc123", "data": "hello\\n"}
    {"type": "resize", "container_id": "abc123", "cols": 80, "rows": 24}
    {"type": "detach"}

  Server → Client:
    {"type": "output", "container_id": "abc123", "data": "..."}
    {"type": "error", "message": "..."}
    {"type": "event", "event": "container_started", "container_id": "abc123", "blueprint_id": "..."}
    {"type": "event", "event": "container_stopped", "container_id": "abc123"}
    {"type": "event", "event": "approval_needed", "approval_id": "...", "reason": "..."}
    {"type": "exit", "container_id": "abc123", "exit_code": 0}
"""

import json
import asyncio
import logging
import threading
from typing import Optional, Dict, Set

from fastapi import WebSocket, WebSocketDisconnect
import docker

logger = logging.getLogger(__name__)

TRION_LABEL = "trion.managed"


# ── Active Connections ────────────────────────────────────

_connections: Set[WebSocket] = set()
_attached: Dict[WebSocket, str] = {}  # ws → container_id
_log_tasks: Dict[str, asyncio.Task] = {}


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
                await _handle_resize(container_id, cols, rows)

            elif msg_type == "detach":
                await _handle_detach(websocket)

            else:
                await _send(websocket, {"type": "error", "message": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
    finally:
        await _handle_detach(websocket)
        _connections.discard(websocket)


# ── Attach / Detach ───────────────────────────────────────

async def _handle_attach(ws: WebSocket, container_id: str):
    """Attach to a container's log stream."""
    if not container_id:
        await _send(ws, {"type": "error", "message": "container_id required"})
        return

    # Detach from previous if any
    await _handle_detach(ws)

    _attached[ws] = container_id
    logger.info(f"[WS] Attached to {container_id[:12]}")

    # Start log streaming task
    task = asyncio.create_task(_stream_logs(ws, container_id))
    _log_tasks[container_id] = task

    await _send(ws, {
        "type": "event",
        "event": "attached",
        "container_id": container_id,
    })


async def _handle_detach(ws: WebSocket):
    """Detach from current container."""
    container_id = _attached.pop(ws, None)
    if container_id:
        task = _log_tasks.pop(container_id, None)
        if task and not task.done():
            task.cancel()
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

# Active exec sessions for stdin forwarding
_exec_sockets: Dict[str, any] = {}


async def _handle_stdin(ws: WebSocket, container_id: str, data: str):
    """Forward stdin data to a container's PTY session."""
    if not container_id or not data:
        return

    try:
        sock = _exec_sockets.get(container_id)
        if not sock:
            # Create an interactive exec session with PTY
            from .engine import get_client
            client = get_client()
            container = client.containers.get(container_id)

            exec_id = client.api.exec_create(
                container.id,
                "/bin/sh",
                stdin=True,
                tty=True,
                stdout=True,
                stderr=True,
            )
            sock = client.api.exec_start(
                exec_id, socket=True, tty=True
            )
            _exec_sockets[container_id] = sock

            # Start reading output in background
            asyncio.create_task(_read_pty_output(ws, container_id, sock))

        # Write stdin data
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: sock._sock.send(data.encode("utf-8")))

    except Exception as e:
        logger.error(f"[WS] Stdin error: {e}")
        await _send(ws, {"type": "error", "message": f"Stdin failed: {e}"})


async def _read_pty_output(ws: WebSocket, container_id: str, sock):
    """Read PTY output and forward to WebSocket."""
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
                "data": text,
            })
    except Exception as e:
        logger.debug(f"[WS] PTY read ended: {e}")
    finally:
        _exec_sockets.pop(container_id, None)


# ── Resize ────────────────────────────────────────────────

async def _handle_resize(container_id: str, cols: int, rows: int):
    """Resize the PTY for a container."""
    try:
        from .engine import get_client
        client = get_client()
        container = client.containers.get(container_id)
        # Resize all exec instances
        container.resize(height=rows, width=cols)
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


# ── Helper ────────────────────────────────────────────────

async def _send(ws: WebSocket, data: dict):
    """Send JSON message to a WebSocket client."""
    try:
        await ws.send_text(json.dumps(data))
    except Exception:
        pass
