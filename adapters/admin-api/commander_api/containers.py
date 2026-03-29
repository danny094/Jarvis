import json
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

from .common import exception_response, logger

router = APIRouter()
_TRION_SHELL_SESSIONS: Dict[str, Dict[str, Any]] = {}
_TRION_SHELL_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_german(text: str, ui_language: str = "") -> bool:
    lang = str(ui_language or "").strip().lower()
    if lang.startswith("de"):
        return True
    sample = f"{text} {ui_language}".lower()
    if any(token in sample for token in ("ä", "ö", "ü", "ß")):
        return True
    markers = (
        " bitte ",
        " warum ",
        " wieso ",
        " prüf",
        " ueberpr",
        " überpr",
        " läuft",
        " laeuft",
        " fehler",
        " ursache",
        " nächste",
        " naechste",
        " erkenntnisse",
        " container",
        " nicht ",
        # häufige deutsche Kurzwörter die keine Sonderzeichen haben
        " du ",
        " ich ",
        " mir ",
        " mich ",
        " dich ",
        " dir ",
        " wir ",
        " ihr ",
        " mein",
        " dein",
        " sein",
        " kennst",
        " weißt",
        " kannst",
        " machst",
        " hast ",
        " bist ",
        " gibt ",
        " geht ",
        " noch ",
        " auch ",
        " dass ",
        " aber ",
        " oder ",
        " wenn ",
        " dann ",
        " jetzt",
        " schon",
        " immer",
        " alles",
    )
    padded = f" {sample} "
    return any(marker in padded for marker in markers)


def _reply_language(user_text: str, ui_language: str = "") -> str:
    return "de" if _looks_german(user_text, ui_language=ui_language) else "en"


def _localized_labels(language: str) -> Dict[str, str]:
    if language == "de":
        return {
            "findings": "Erkenntnisse",
            "likely_cause": "Wahrscheinliche Ursache",
            "next_checks": "Nächste Prüfungen",
            "shell_started": "TRION steuert jetzt die Shell. Beschreibe das Ziel. Mit /exit bekommst du die direkte Shell-Kontrolle zurück.",
            "shell_stopped": "TRION-Shellmodus beendet. Die direkte Shell-Kontrolle ist wieder beim User.",
            "empty_reply": "Erkenntnisse: Keine Analyse erhalten.\nWahrscheinliche Ursache: Das Modell hat leer geantwortet.\nNächste Prüfungen: Anfrage wiederholen oder Provider prüfen.",
        }
    return {
        "findings": "Findings",
        "likely_cause": "Likely cause",
        "next_checks": "Next checks",
        "shell_started": "TRION now controls the shell. Describe the goal. Use /exit to return direct shell control to the user.",
        "shell_stopped": "TRION shell mode ended. Direct shell control has returned to the user.",
        "empty_reply": "Findings: No analysis text returned.\nLikely cause: The debug model returned an empty response.\nNext checks: Retry the request or inspect provider health.",
    }


def _shell_session_key(conversation_id: str, container_id: str) -> str:
    return f"{conversation_id.strip() or 'global'}::{container_id.strip()}"


def _extract_json_object(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    decoder = json.JSONDecoder()
    for candidate in (fenced, text):
        for idx, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                obj, _end = decoder.raw_decode(candidate[idx:])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
    return {}


async def _complete_commander_chat(
    *,
    messages: list[Dict[str, str]],
    fallback_text: str,
) -> Dict[str, Any]:
    from config import get_output_model
    from core.llm_provider_client import complete_chat, resolve_role_provider
    from utils.role_endpoint_resolver import resolve_role_endpoint

    provider = resolve_role_provider("output", default="ollama")
    requested_provider = provider
    model = str(get_output_model() or "").strip()
    endpoint = ""
    if provider == "ollama":
        route = resolve_role_endpoint("output")
        if route.get("hard_error"):
            raise RuntimeError("output_compute_unavailable")
        endpoint = str(route.get("endpoint") or "").strip()

    try:
        response = await complete_chat(
            provider=provider,
            model=model,
            messages=messages,
            timeout_s=45,
            ollama_endpoint=endpoint,
        )
    except Exception as llm_err:
        if provider != "ollama" and "missing_api_key" in str(llm_err).lower():
            provider = "ollama"
            route = resolve_role_endpoint("output")
            if route.get("hard_error"):
                raise llm_err
            endpoint = str(route.get("endpoint") or "").strip()
            response = await complete_chat(
                provider=provider,
                model=model,
                messages=messages,
                timeout_s=45,
                ollama_endpoint=endpoint,
            )
        else:
            raise

    content = str(response.get("content", "") or "").strip() or fallback_text
    return {
        "content": content,
        "provider": provider,
        "requested_provider": requested_provider,
        "model": model,
    }


def _remember_container_state(conversation_id: str, container_id: str, blueprint_id: str, status: str, name: str) -> None:
    from core.bridge import get_bridge

    bridge = get_bridge()
    try:
        bridge.orchestrator._remember_container_state(  # noqa: SLF001
            conversation_id,
            last_active_container_id=container_id,
            known_containers=[{
                "container_id": container_id,
                "blueprint_id": blueprint_id,
                "status": status or "running",
                "name": name,
            }],
            history_len=1,
        )
    except Exception as state_err:
        logger.debug("[Commander] Container state seed failed: %s", state_err)


def _save_shell_summary_event(
    *,
    conversation_id: str,
    container_id: str,
    blueprint_id: str,
    container_name: str,
    summary: str,
    commands: list[str],
    user_requests: list[str],
    final_stop_reason: str = "",
    summary_parts: Dict[str, Any] | None = None,
) -> None:
    try:
        from mcp.hub import get_hub

        hub = get_hub()
        hub.initialize()
        hub.call_tool("workspace_event_save", {
            "conversation_id": conversation_id,
            "event_type": "trion_shell_summary",
            "event_data": {
                "container_id": container_id,
                "blueprint_id": blueprint_id,
                "container_name": container_name,
                "summary": summary,
                "commands": list(commands or [])[:12],
                "user_requests": list(user_requests or [])[:12],
                "final_stop_reason": str(final_stop_reason or "").strip(),
                "summary_parts": dict(summary_parts or {}),
                "saved_at": _utc_now(),
                "content": summary,
            },
        })
    except Exception as save_err:
        logger.error("[Commander] Failed to save TRION shell summary: %s", save_err)


def _shell_command_fingerprint(command: str) -> str:
    return re.sub(r"\s+", " ", str(command or "").strip().lower())


def _classify_shell_action(command: str) -> str:
    cmd = str(command or "").strip()
    if not cmd:
        return "analysis_only"
    low = cmd.lower()
    if low.startswith("xdotool ") or " windowactivate " in low or " key --clearmodifiers " in low:
        return "gui_interaction"
    if any(token in low for token in ("apt-get install", "apt install", "apk add", "dnf install", "yum install", "pacman -s", "flatpak install")):
        return "package_install"
    if re.search(r"(^|\s)(kill|pkill|killall|systemctl|service|supervisorctl)\b", low):
        return "process_control"
    if (
        " >" in cmd
        or ">>" in cmd
        or re.search(r"(^|\s)(sed\s+-i|tee\b|chmod\b|chown\b|mv\b|cp\b|rm\b|mkdir\b|touch\b|ln\b)\b", low)
    ):
        return "write_change"
    if re.search(r"(^|\s)(ps\b|grep\b|cat\b|tail\b|less\b|head\b|ls\b|find\b|netstat\b|ss\b|lsof\b|pgrep\b|env\b|printenv\b|whoami\b|pwd\b|id\b|journalctl\b|curl\b|wget\b)\b", low):
        return "read_check"
    return "shell_command"


def _is_short_followup(text: str) -> bool:
    norm = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return norm in {"und", "und?", "weiter", "weiter?", "nochmal", "noch?", "erneut", "erneut?", "and", "and?", "what now", "now?"}


def _action_verification_focus(action_type: str, language: str) -> str:
    if language == "de":
        mapping = {
            "gui_interaction": "Prüfe Fenster/Dialog-Zustand vor jeder Wiederholung. Keine zweite GUI-Bestätigung ohne klaren Zustandswechsel.",
            "package_install": "Prüfe Paket- oder Installer-Status. Wiederhole keine Installationsbestätigung ohne neuen Fortschritt.",
            "process_control": "Prüfe PID-, Dienst- oder Supervisor-Status nach dem Befehl.",
            "write_change": "Prüfe, ob die Datei- oder Konfigurationsänderung wirklich sichtbar geworden ist.",
            "read_check": "Fasse Erkenntnisse zusammen; erneute Checks nur bei neuer Hypothese.",
            "shell_command": "Prüfe den direkt beobachtbaren Zustand vor einer Wiederholung.",
            "analysis_only": "Kein Shell-Befehl nötig, wenn der nächste sichere Schritt unklar ist.",
        }
    else:
        mapping = {
            "gui_interaction": "Verify the window or dialog state before any repeat. Do not confirm the same GUI prompt twice without a visible state change.",
            "package_install": "Verify package or installer state before repeating any confirmation step.",
            "process_control": "Verify PID, service, or supervisor state after the command.",
            "write_change": "Verify that the file or configuration change is actually visible before continuing.",
            "read_check": "Summarize the findings; repeat checks only when a new hypothesis appears.",
            "shell_command": "Verify an observable state change before repeating the command.",
            "analysis_only": "No shell command is needed when the next safe step is unclear.",
        }
    return mapping.get(action_type, mapping.get("shell_command", ""))


def _detect_shell_blocker(shell_tail: str, language: str) -> Dict[str, Any]:
    tail_text = str(shell_tail or "").strip()
    if not tail_text:
        return {}
    lower_tail = tail_text.lower()
    blockers = [
        (
            ("steam installer", "zenity --question"),
            {
                "code": "gui_dialog_still_open",
                "status": "manual_confirmation_needed",
                "category": "gui_dialog",
                "detail_de": "Der Installationsdialog ist weiterhin offen; dieselbe GUI-Aktion würde nur im Kreis laufen.",
                "detail_en": "The installer dialog is still open; repeating the same GUI action would only loop.",
                "evidence": "steam installer / zenity still present",
            },
        ),
        (
            ("do you want to continue", "[y/n]", "[y/n]", "[yes/no]", "[sudo] password", "password for ", "enter passphrase"),
            {
                "code": "interactive_prompt_waiting",
                "status": "manual_confirmation_needed",
                "category": "interactive_prompt",
                "detail_de": "Die Shell wartet weiterhin auf interaktive Eingabe oder Bestätigung.",
                "detail_en": "The shell is still waiting for interactive input or confirmation.",
                "evidence": "interactive prompt still visible",
            },
        ),
    ]
    for signatures, data in blockers:
        if any(signature in lower_tail for signature in signatures):
            detail = data["detail_de"] if language == "de" else data["detail_en"]
            return {
                "code": data["code"],
                "status": data["status"],
                "category": data["category"],
                "reason": detail,
                "evidence": data["evidence"],
            }
    return {}


def _build_shell_stop_reason_text(reason_code: str, language: str, *, detail: str = "") -> str:
    if language == "de":
        mapping = {
            "loop_guard_repeat": "Ich stoppe hier, weil derselbe Shell-Befehl ohne erkennbaren Zustandswechsel erneut ausgeführt würde.",
            "manual_confirmation_needed": "Ich stoppe hier, weil weiterhin manuelle Bestätigung oder eine andere Prüfstrategie nötig ist.",
            "gui_dialog_still_open": "Ich stoppe hier, weil derselbe GUI-Dialog noch offen ist und eine Wiederholung nur eine Schleife wäre.",
            "interactive_prompt_waiting": "Ich stoppe hier, weil die Shell noch auf interaktive Eingabe oder Bestätigung wartet.",
            "no_state_change": "Ich stoppe hier, weil nach der letzten Aktion kein klarer Zustandswechsel erkennbar ist.",
            "command_failed": "Ich stoppe hier, weil die letzte Aktion fehlgeschlagen ist und erst genauer geprüft werden sollte.",
            "no_safe_next_step": "Ich stoppe hier, weil aus dem aktuellen Zustand kein sicherer nächster Shell-Schritt ableitbar ist.",
        }
    else:
        mapping = {
            "loop_guard_repeat": "I am stopping here because the same shell command would be repeated without a visible state change.",
            "manual_confirmation_needed": "I am stopping here because manual confirmation or a different verification strategy is still required.",
            "gui_dialog_still_open": "I am stopping here because the same GUI dialog is still open and repeating the action would only loop.",
            "interactive_prompt_waiting": "I am stopping here because the shell is still waiting for interactive input or confirmation.",
            "no_state_change": "I am stopping here because the last action did not produce a clear state change.",
            "command_failed": "I am stopping here because the last action appears to have failed and should be inspected first.",
            "no_safe_next_step": "I am stopping here because no safe next shell step can be derived from the current state.",
        }
    base = mapping.get(reason_code, mapping.get("no_state_change", ""))
    detail_txt = str(detail or "").strip()
    return f"{base} {detail_txt}".strip() if detail_txt else base


async def _verify_previous_shell_action(
    *,
    session: Dict[str, Any],
    shell_tail: str,
    language: str,
    container_id: str,
    container_name: str,
    blueprint_id: str,
) -> Dict[str, Any]:
    history = list(session.get("step_history") or [])
    if not history:
        return {}
    last_step = history[-1] if isinstance(history[-1], dict) else {}
    if not last_step or last_step.get("verification"):
        return dict(last_step.get("verification") or {})

    last_command = str(last_step.get("command") or "").strip()
    if not last_command:
        return {}

    tail_text = str(shell_tail or "").strip()
    prev_tail = str(session.get("last_shell_tail") or "").strip()
    action_type = str(last_step.get("action_type") or _classify_shell_action(last_command)).strip() or "shell_command"
    lower_tail = tail_text.lower()
    blocker = _detect_shell_blocker(tail_text, language)

    if not tail_text or tail_text == prev_tail:
        verification = {
            "status": "unknown",
            "state_changed": False,
            "reason": (
                "Noch kein neuer Shell-Output seit dem letzten Schritt." if language == "de"
                else "No new shell output since the previous step."
            ),
            "evidence": "",
            "should_retry_same_command": False,
        }
    elif blocker and action_type in {"gui_interaction", "package_install", "process_control", "write_change"}:
        verification = {
            "status": str(blocker.get("status") or "manual_confirmation_needed"),
            "state_changed": False,
            "reason": str(blocker.get("reason") or ""),
            "evidence": str(blocker.get("evidence") or ""),
            "should_retry_same_command": False,
        }
    elif any(marker in lower_tail for marker in ("permission denied", "command not found", "no such file", "not found")):
        verification = {
            "status": "failed",
            "state_changed": False,
            "reason": (
                "Die letzte Aktion ist laut Shell-Ausgabe fehlgeschlagen." if language == "de"
                else "The previous action appears to have failed according to shell output."
            ),
            "evidence": tail_text[-400:],
            "should_retry_same_command": False,
        }
    else:
        messages = [
            {
                "role": "system",
                "content": (
                    f"You verify the outcome of a previously executed container shell action. Reply in {'German' if language == 'de' else 'English'} only. "
                    "Return exactly one JSON object and no markdown. "
                    'Schema: {"status":"changed|unchanged|manual_confirmation_needed|failed|unknown","state_changed":false,"reason":"short text","evidence":"short text","should_retry_same_command":false}. '
                    "Judge only from the previous command, action type, and current shell output."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Container:\n- id: {container_id}\n- name: {container_name or '(unknown)'}\n- blueprint_id: {blueprint_id or '(unknown)'}\n\n"
                    f"Previous command: {last_command}\n"
                    f"Action type: {action_type}\n\n"
                    f"Verification focus: {_action_verification_focus(action_type, language)}\n\n"
                    f"Current shell output tail:\n{tail_text[-8000:]}\n"
                ),
            },
        ]
        verification_response = await _complete_commander_chat(messages=messages, fallback_text="{}")
        payload = _extract_json_object(str(verification_response.get("content", "") or ""))
        verification = {
            "status": str(payload.get("status", "") or "unknown").strip() or "unknown",
            "state_changed": bool(payload.get("state_changed", False)),
            "reason": str(payload.get("reason", "") or "").strip(),
            "evidence": str(payload.get("evidence", "") or "").strip(),
            "should_retry_same_command": bool(payload.get("should_retry_same_command", False)),
        }

    history[-1] = {
        **last_step,
        "verification": verification,
    }
    session["step_history"] = history[-12:]
    session["last_verification"] = verification
    session["last_stop_reason"] = ""
    return verification


def _build_structured_shell_summary(summary_payload: Dict[str, Any], language: str) -> str:
    def _as_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        return [text] if text else []

    if language == "de":
        labels = {
            "goal": "Ziel",
            "findings": "Wichtige Erkenntnisse",
            "actions_taken": "Ausgeführte Schritte",
            "changes_made": "Änderungen",
            "blocker": "Stop-Grund / Blocker",
            "next_step": "Nächster Schritt",
        }
    else:
        labels = {
            "goal": "Goal",
            "findings": "Key findings",
            "actions_taken": "Actions taken",
            "changes_made": "Changes made",
            "blocker": "Stop reason / blocker",
            "next_step": "Next step",
        }

    sections = []
    for key in ("goal", "findings", "actions_taken", "changes_made", "blocker", "next_step"):
        lines = _as_lines(summary_payload.get(key))
        if not lines:
            continue
        if len(lines) == 1:
            sections.append(f"{labels[key]}: {lines[0]}")
            continue
        sections.append(f"{labels[key]}:")
        sections.extend(f"- {line}" for line in lines)
    return "\n".join(sections).strip()


def _build_shell_runtime_context(container, attrs: Dict[str, Any], language: str) -> str:
    config = (attrs or {}).get("Config") or {}
    env_values = [str(item).strip() for item in list(config.get("Env") or []) if str(item).strip()]
    env_map: Dict[str, str] = {}
    for item in env_values:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        env_map[str(key).strip()] = str(value).strip()
    networks = (((attrs or {}).get("NetworkSettings") or {}).get("Networks") or {})
    ports_obj = (((attrs or {}).get("NetworkSettings") or {}).get("Ports") or {})
    published_ports = sorted(str(port or "") for port, bindings in dict(ports_obj).items() if bindings)
    network_names = [str(name).strip() for name in dict(networks).keys() if str(name).strip()]
    lines = [
        f"- image: {str(config.get('Image') or '').strip() or '(unknown)'}",
        f"- status: {str(getattr(container, 'status', '') or '').strip() or '(unknown)'}",
        f"- display: {env_map.get('DISPLAY', '(unset)')}",
        f"- web_ui_mode: {env_map.get('WEB_UI_MODE', '(unset)')}",
        f"- desktop_size: {env_map.get('DISPLAY_SIZEW', '?')}x{env_map.get('DISPLAY_SIZEH', '?')}",
        f"- published_ports: {', '.join(published_ports[:12]) or '(none)'}",
        f"- networks: {', '.join(network_names) or '(none)'}",
        f"- notable_env: NVIDIA_VISIBLE_DEVICES={env_map.get('NVIDIA_VISIBLE_DEVICES', '(unset)')}, NVIDIA_DRIVER_CAPABILITIES={env_map.get('NVIDIA_DRIVER_CAPABILITIES', '(unset)')}, ENABLE_SUNSHINE={env_map.get('ENABLE_SUNSHINE', '(unset)')}, ENABLE_STEAM={env_map.get('ENABLE_STEAM', '(unset)')}",
    ]
    header = "Structured container runtime facts:" if language != "de" else "Strukturierte Container-Runtime-Fakten:"
    return f"{header}\n" + "\n".join(lines)


def _infer_container_addon_tags(blueprint_id: str, container_name: str, image_ref: str, attrs: Dict[str, Any]) -> List[str]:
    config = (attrs or {}).get("Config") or {}
    env_values = [str(item).strip() for item in list(config.get("Env") or []) if str(item).strip()]
    env_map: Dict[str, str] = {}
    for item in env_values:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        env_map[str(key).strip()] = str(value).strip()
    ports_obj = (((attrs or {}).get("NetworkSettings") or {}).get("Ports") or {})
    published_ports = {str(port or "").strip().lower() for port, bindings in dict(ports_obj).items() if bindings}
    tags = {
        "container-shell",
        str(blueprint_id or "").strip().lower(),
        str(container_name or "").strip().lower(),
    }
    lower_image = str(image_ref or "").strip().lower()
    if lower_image:
        tags.update(part for part in re.split(r"[^a-z0-9]+", lower_image) if len(part) >= 3)
    if "steam-headless" in lower_image:
        tags.update({"gaming", "steam", "steam-headless", "headless-gui"})
    if env_map.get("WEB_UI_MODE", "").strip().lower() == "vnc" or "8083/tcp" in published_ports:
        tags.update({"novnc", "vnc", "headless-gui"})
    if env_map.get("DISPLAY"):
        tags.update({"x11", "display"})
    if env_map.get("ENABLE_SUNSHINE", "").strip().lower() == "true" or any(port in published_ports for port in {"47989/tcp", "47990/tcp", "48010/tcp"}):
        tags.update({"sunshine", "streaming"})
    if env_map.get("ENABLE_STEAM", "").strip().lower() == "true":
        tags.add("steam")
    if env_map.get("NVIDIA_VISIBLE_DEVICES", "").strip():
        tags.update({"nvidia", "gpu"})
    if env_map.get("XDG_SESSION_TYPE", "").strip().lower() == "x11":
        tags.add("x11")
    if env_map.get("PORT_NOVNC_WEB", "").strip():
        tags.add("novnc")
    if str((attrs or {}).get("State", {}).get("Running", False)).lower() == "true":
        tags.add("running")
    # Commander-managed gaming/headless containers currently use supervisord.
    if lower_image and any(token in lower_image for token in ("steam-headless",)):
        tags.add("supervisord")
    return sorted(tag for tag in tags if tag and tag != "(none)")


@router.get("/containers")
async def api_list_containers():
    """List all TRION-managed containers with live status."""
    try:
        from container_commander.engine import list_containers

        cts = list_containers()
        return {"containers": [c.model_dump() for c in cts], "count": len(cts)}
    except Exception as e:
        logger.error(f"[Commander] List containers: {e}")
        return exception_response(e, details={"containers": [], "count": 0})


@router.get("/home/status")
async def api_home_status():
    """Return TRION home identity + runtime health status."""
    try:
        from container_commander.engine import list_containers
        from utils.trion_home_identity import evaluate_home_status

        containers = list_containers()
        return evaluate_home_status(containers)
    except Exception as e:
        return exception_response(e, details={"status": "offline"})


@router.post("/containers/{container_id}/exec")
async def api_exec_in_container(container_id: str, request: Request):
    """Execute a command inside a running container."""
    try:
        from container_commander.engine import exec_in_container

        data = await request.json()
        command = data.get("command", "")
        if not command:
            return exception_response(
                HTTPException(400, "'command' is required"),
                error_code="bad_request",
                details={"executed": False, "container_id": container_id},
            )
        timeout = data.get("timeout", 30)
        exit_code, output = exec_in_container(container_id, command, timeout)
        return {"executed": True, "exit_code": exit_code, "output": output}
    except Exception as e:
        return exception_response(e, details={"executed": False})


@router.post("/containers/{container_id}/trion-debug")
async def api_trion_debug_container(container_id: str, request: Request):
    """Run a focused TRION debugging pass for the selected container."""
    try:
        from container_commander.engine import (
            exec_in_container_detailed,
            get_client,
            get_container_logs,
            get_container_stats,
        )

        data = await request.json()
        task = str(data.get("task", "") or "").strip()
        if not task:
            return exception_response(
                HTTPException(400, "'task' is required"),
                error_code="bad_request",
                details={"analyzed": False, "container_id": container_id},
            )

        conversation_id = str(data.get("conversation_id", "") or "").strip() or "global"
        ui_language = str(data.get("ui_language", "") or "").strip()
        language = _reply_language(task, ui_language=ui_language)
        labels = _localized_labels(language)

        client = get_client()
        container = client.containers.get(container_id)
        container.reload()

        blueprint_id = str(container.labels.get("trion.blueprint", "") or "").strip()
        container_name = str(getattr(container, "name", "") or "").strip()
        status = str(getattr(container, "status", "") or "").strip()

        stats = get_container_stats(container_id)
        logs = str(get_container_logs(container_id, 120) or "")[-12000:]

        diagnostics = {
            "executed": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "policy_denied": False,
        }
        try:
            diag = exec_in_container_detailed(
                container_id,
                (
                    "sh -lc 'pwd 2>/dev/null || true; printf \"\\n\"; "
                    "(id -un 2>/dev/null || whoami 2>/dev/null || true); printf \"\\n\"; "
                    "if command -v ps >/dev/null 2>&1; then "
                    "(ps -ef 2>/dev/null || ps 2>/dev/null || true) | tail -n 20; "
                    "fi'"
                ),
                timeout=12,
            )
            diagnostics = {
                "executed": True,
                "exit_code": diag.get("exit_code"),
                "stdout": str(diag.get("stdout", "") or "")[:4000],
                "stderr": str(diag.get("stderr", "") or "")[:2500],
                "policy_denied": False,
            }
        except Exception as e:
            diagnostics = {
                "executed": False,
                "exit_code": None,
                "stdout": "",
                "stderr": str(e),
                "policy_denied": "policy_denied" in str(e).lower(),
            }

        compact_stats = {
            "status": status,
            "cpu_percent": stats.get("cpu_percent"),
            "memory_mb": stats.get("memory_mb"),
            "memory_limit_mb": stats.get("memory_limit_mb"),
            "ip_address": stats.get("ip_address"),
            "efficiency": stats.get("efficiency", {}),
            "ports": stats.get("ports", [])[:8],
        }

        _remember_container_state(conversation_id, container_id, blueprint_id, status, container_name)

        messages = [
            {
                "role": "system",
                "content": (
                    f"You are TRION in Container Commander debug mode. Reply in {'German' if language == 'de' else 'English'}. "
                    "Analyze only the provided container context. "
                    "Do not use tools. Do not invent host facts. "
                    "Do not ask to choose another container. "
                    "Do not suggest a restart unless the evidence clearly supports it. "
                    "Return a concise operational answer with exactly three section headings: "
                    f"{labels['findings']}, {labels['likely_cause']}, {labels['next_checks']}."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User task:\n{task}\n\n"
                    "Attached container:\n"
                    f"- container_id: {container_id}\n"
                    f"- name: {container_name or '(unknown)'}\n"
                    f"- blueprint_id: {blueprint_id or '(unknown)'}\n"
                    f"- status: {status or '(unknown)'}\n\n"
                    f"Stats snapshot:\n{json.dumps(compact_stats, ensure_ascii=True, indent=2)}\n\n"
                    f"Recent logs (trimmed):\n{logs or '(no logs)'}\n\n"
                    f"Diagnostic exec snapshot:\n{json.dumps(diagnostics, ensure_ascii=True, indent=2)}\n"
                ),
            },
        ]
        llm_response = await _complete_commander_chat(messages=messages, fallback_text=labels["empty_reply"])
        reply = str(llm_response.get("content", "") or "").strip()

        return {
            "analyzed": True,
            "container_id": container_id,
            "conversation_id": conversation_id,
            "model": llm_response["model"],
            "provider": llm_response["provider"],
            "requested_provider": llm_response["requested_provider"],
            "language": language,
            "reply": reply,
            "context": {
                "name": container_name,
                "blueprint_id": blueprint_id,
                "status": status,
                "diag_executed": diagnostics.get("executed", False),
                "diag_exit_code": diagnostics.get("exit_code"),
                "diag_policy_denied": diagnostics.get("policy_denied", False),
            },
        }
    except Exception as e:
        logger.error("[Commander] TRION debug error for %s: %s", container_id, e)
        return exception_response(e, details={"analyzed": False, "container_id": container_id})


@router.post("/containers/{container_id}/trion-shell/start")
async def api_trion_shell_start(container_id: str, request: Request):
    """Enter TRION shell-control mode for the attached container."""
    try:
        from container_commander.engine import get_client
        from container_commander.ws_stream import emit_activity

        data = await request.json()
        conversation_id = str(data.get("conversation_id", "") or "").strip() or "global"
        ui_language = str(data.get("ui_language", "") or "").strip()
        initial_goal = str(data.get("goal", "") or "").strip()
        language = _reply_language(initial_goal, ui_language=ui_language)
        labels = _localized_labels(language)

        client = get_client()
        container = client.containers.get(container_id)
        container.reload()
        blueprint_id = str(container.labels.get("trion.blueprint", "") or "").strip()
        container_name = str(getattr(container, "name", "") or "").strip()
        status = str(getattr(container, "status", "") or "").strip()
        _remember_container_state(conversation_id, container_id, blueprint_id, status, container_name)

        key = _shell_session_key(conversation_id, container_id)
        from container_commander.shell_context_bridge import build_mission_state
        mission_state = await build_mission_state(conversation_id)
        session = {
            "conversation_id": conversation_id,
            "container_id": container_id,
            "container_name": container_name,
            "blueprint_id": blueprint_id,
            "language": language,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "step_count": 0,
            "commands": [],
            "user_requests": [initial_goal] if initial_goal else [],
            "last_reply": "",
            "last_command": "",
            "last_shell_tail": "",
            "last_verification": {},
            "last_stop_reason": "",
            "step_history": [],
            "mission_state": mission_state,
        }
        with _TRION_SHELL_LOCK:
            _TRION_SHELL_SESSIONS[key] = session

        emit_activity(
            "trion_shell_mode_started",
            level="info",
            message=labels["shell_started"],
            container_id=container_id,
            blueprint_id=blueprint_id,
            conversation_id=conversation_id,
        )
        return {
            "ok": True,
            "active": True,
            "conversation_id": conversation_id,
            "container_id": container_id,
            "language": language,
            "message": labels["shell_started"],
        }
    except Exception as e:
        logger.error("[Commander] TRION shell start error for %s: %s", container_id, e)
        return exception_response(e, details={"active": False, "container_id": container_id})


@router.post("/containers/{container_id}/trion-shell/step")
async def api_trion_shell_step(container_id: str, request: Request):
    """Generate the next shell action for an active TRION shell session."""
    try:
        from container_commander.engine import get_client
        from intelligence_modules.container_addons.loader import load_container_addon_context

        data = await request.json()
        conversation_id = str(data.get("conversation_id", "") or "").strip() or "global"
        instruction = str(data.get("instruction", "") or "").strip()
        shell_tail = str(data.get("shell_tail", "") or "")
        ui_language = str(data.get("ui_language", "") or "").strip()
        if not instruction:
            return exception_response(
                HTTPException(400, "'instruction' is required"),
                error_code="bad_request",
                details={"active": False, "container_id": container_id},
            )

        key = _shell_session_key(conversation_id, container_id)
        with _TRION_SHELL_LOCK:
            session = dict(_TRION_SHELL_SESSIONS.get(key) or {})

        client = get_client()
        container = client.containers.get(container_id)
        container.reload()
        attrs = container.attrs or {}
        blueprint_id = str(container.labels.get("trion.blueprint", "") or "").strip()
        container_name = str(getattr(container, "name", "") or "").strip()
        status = str(getattr(container, "status", "") or "").strip()
        image_ref = str(((attrs or {}).get("Config") or {}).get("Image") or "").strip()
        # Re-detect language per step: if current instruction is German, use German
        # regardless of session default (session may have been started with empty/English goal)
        _detected = _reply_language(instruction, ui_language=ui_language)
        language = "de" if _detected == "de" else str(session.get("language") or "en").strip() or "en"

        if not session:
            session = {
                "conversation_id": conversation_id,
                "container_id": container_id,
                "container_name": container_name,
                "blueprint_id": blueprint_id,
                "language": language,
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "step_count": 0,
                "commands": [],
                "user_requests": [],
                "last_reply": "",
                "last_command": "",
                "last_shell_tail": "",
                "last_verification": {},
                "last_stop_reason": "",
                "step_history": [],
            }
        session.setdefault("step_history", [])
        session.setdefault("commands", [])
        session.setdefault("user_requests", [])
        session.setdefault("last_verification", {})
        session.setdefault("last_stop_reason", "")

        _remember_container_state(conversation_id, container_id, blueprint_id, status, container_name)

        prior_tail = str(session.get("last_shell_tail") or "").strip()
        effective_tail = (shell_tail or prior_tail or "")[-12000:]

        verification = await _verify_previous_shell_action(
            session=session,
            shell_tail=effective_tail,
            language=language,
            container_id=container_id,
            container_name=container_name,
            blueprint_id=blueprint_id,
        )

        recent_commands = [str(item) for item in list(session.get("commands") or [])[-6:] if str(item).strip()]
        recent_requests = [str(item) for item in list(session.get("user_requests") or [])[-6:] if str(item).strip()]
        prior_reply = str(session.get("last_reply") or "").strip()
        verification_summary = json.dumps(verification or {}, ensure_ascii=True, indent=2)
        runtime_context = _build_shell_runtime_context(container, attrs, language)
        addon_tags = _infer_container_addon_tags(blueprint_id, container_name, image_ref, attrs)
        addon_context = await load_container_addon_context(
            blueprint_id=blueprint_id,
            image_ref=image_ref,
            instruction=instruction,
            shell_tail=effective_tail,
            container_tags=addon_tags,
        )
        addon_context_text = str(addon_context.get("context_text") or "").strip()
        last_step = {}
        if isinstance(session.get("step_history"), list) and session["step_history"]:
            maybe_last_step = session["step_history"][-1]
            if isinstance(maybe_last_step, dict):
                last_step = maybe_last_step
        blocker = _detect_shell_blocker(effective_tail, language)
        if (
            _is_short_followup(instruction)
            and str(last_step.get("action_type") or "") in {"gui_interaction", "package_install"}
            and blocker
        ):
            stop_reason = str(blocker.get("code") or "manual_confirmation_needed")
            verification = verification or {
                "status": str(blocker.get("status") or "manual_confirmation_needed"),
                "state_changed": False,
                "reason": str(blocker.get("reason") or ""),
                "evidence": str(blocker.get("evidence") or effective_tail[-400:]),
                "should_retry_same_command": False,
            }
            assistant_text = _build_shell_stop_reason_text(
                stop_reason,
                language,
                detail=str((verification or {}).get("reason") or "").strip(),
            )
            session["updated_at"] = _utc_now()
            session["step_count"] = int(session.get("step_count", 0) or 0) + 1
            session["language"] = language
            session["container_name"] = container_name
            session["blueprint_id"] = blueprint_id
            session["last_reply"] = assistant_text
            session["last_command"] = ""
            session["last_shell_tail"] = effective_tail
            session["last_stop_reason"] = stop_reason
            session["last_verification"] = verification
            session.setdefault("user_requests", []).append(instruction)
            session["user_requests"] = list(session["user_requests"])[-12:]
            session.setdefault("step_history", []).append({
                "user_instruction": instruction,
                "assistant": assistant_text,
                "command": "",
                "action_type": "analysis_only",
                "stop_reason": stop_reason,
                "verification": verification,
                "created_at": _utc_now(),
            })
            session["step_history"] = list(session["step_history"])[-12:]
            with _TRION_SHELL_LOCK:
                _TRION_SHELL_SESSIONS[key] = session
            return {
                "ok": True,
                "active": True,
                "container_id": container_id,
                "conversation_id": conversation_id,
                "language": language,
                "assistant": assistant_text,
                "command": "",
                "action_type": "analysis_only",
                "verification": verification,
                "stop_reason": stop_reason,
                "exit_shell": False,
                "addon_docs": list(addon_context.get("selected_docs") or []),
                "model": "",
                "provider": "",
                "requested_provider": "",
            }

        mission_state = str(session.get("mission_state") or "").strip()
        mission_state_block = (
            f"\nUser & chat context:\n{mission_state}\n"
            if mission_state else ""
        )
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are TRION controlling an attached interactive container shell. Reply in {'German' if language == 'de' else 'English'} only. "
                    "You do not execute commands yourself. You must return exactly one JSON object and no markdown. "
                    'Schema: {"assistant":"short user-facing explanation","command":"single shell command or empty string","exit_shell":false,"stop_reason":""}. '
                    f'The value of "assistant" must be written only in {"German" if language == "de" else "English"}. '
                    "Never repeat the same command if the previous verification says unchanged, failed, or manual confirmation is still needed. "
                    "If no safe next command exists, leave command empty and explain why. "
                    "Prefer short safe diagnostic commands. Avoid destructive or multi-line commands unless the user explicitly asks for changes. "
                    "Treat the structured runtime facts and container addon excerpts as higher-priority guidance than generic Linux assumptions. "
                    "If the runtime facts or addon context indicate supervisord, do not use systemctl. "
                    "If a 'User & chat context' block is present: greet the user by name if their name is given, reply in their language, and use their context to understand goals. Do not repeat the block verbatim. "
                    "Base your decision on the user instruction, recent shell output, recent command history, and the user & chat context if available."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Container:\n- id: {container_id}\n- name: {container_name or '(unknown)'}\n- blueprint_id: {blueprint_id or '(unknown)'}\n- status: {status or '(unknown)'}\n{mission_state_block}"
                    f"{runtime_context}\n\n"
                    f"Inferred container addon tags:\n{json.dumps(addon_tags, ensure_ascii=True)}\n\n"
                    f"Relevant container addon context:\n{addon_context_text or '(none)'}\n\n"
                    f"Recent user requests:\n{json.dumps(recent_requests, ensure_ascii=True)}\n\n"
                    f"Recent TRION commands:\n{json.dumps(recent_commands, ensure_ascii=True)}\n\n"
                    f"Previous TRION reply:\n{prior_reply or '(none)'}\n\n"
                    f"Verification of previous action:\n{verification_summary}\n\n"
                    f"Verification focus for the next step: {_action_verification_focus(str(last_step.get('action_type') or _classify_shell_action(str(session.get('last_command') or ''))), language)}\n\n"
                    f"Recent shell output tail:\n{effective_tail or '(no shell output yet)'}\n\n"
                    f"Current user instruction:\n{instruction}\n\n"
                    f"Remember: write the assistant text only in {'German' if language == 'de' else 'English'}."
                ),
            },
        ]
        llm_response = await _complete_commander_chat(messages=messages, fallback_text="{}")
        payload = _extract_json_object(str(llm_response.get("content", "") or ""))
        assistant_text = str(payload.get("assistant", "") or "").strip()
        command = str(payload.get("command", "") or "").strip()
        exit_shell = bool(payload.get("exit_shell", False))
        stop_reason = str(payload.get("stop_reason", "") or "").strip()
        action_type = _classify_shell_action(command)

        if not assistant_text:
            assistant_text = (
                "Ich habe keinen nächsten Shell-Schritt formulieren können." if language == "de"
                else "I could not formulate the next shell step."
            )

        if "\n" in command:
            command = command.splitlines()[0].strip()
            action_type = _classify_shell_action(command)

        recent_fingerprints = [_shell_command_fingerprint(item) for item in recent_commands[-3:]]
        current_fingerprint = _shell_command_fingerprint(command)
        verification_status = str((verification or {}).get("status", "") or "").strip()
        state_changed = bool((verification or {}).get("state_changed", False))
        verification_reason = str((verification or {}).get("reason", "") or "").strip()
        last_action_type = str(last_step.get("action_type") or "").strip()
        semantic_gui_repeat = (
            bool(command)
            and _is_short_followup(instruction)
            and blocker
            and action_type in {"gui_interaction", "package_install"}
            and last_action_type == action_type
            and verification_status in {"manual_confirmation_needed", "unchanged", "unknown"}
        )

        if command and current_fingerprint and recent_fingerprints and current_fingerprint == recent_fingerprints[-1]:
            if verification_status in {"unchanged", "manual_confirmation_needed", "failed"} or not state_changed:
                stop_reason = "loop_guard_repeat"
                command = ""
                action_type = "analysis_only"
                assistant_text = _build_shell_stop_reason_text(
                    "loop_guard_repeat",
                    language,
                    detail=verification_reason,
                )

        if command and semantic_gui_repeat:
            stop_reason = str(blocker.get("code") or "manual_confirmation_needed")
            command = ""
            action_type = "analysis_only"
            assistant_text = _build_shell_stop_reason_text(
                stop_reason,
                language,
                detail=str(blocker.get("reason") or verification_reason),
            )

        if not command and not stop_reason and verification_status in {"manual_confirmation_needed", "failed"} and _is_short_followup(instruction):
            stop_reason = "manual_confirmation_needed" if verification_status == "manual_confirmation_needed" else "command_failed"
            assistant_text = _build_shell_stop_reason_text(stop_reason, language, detail=verification_reason)
            action_type = "analysis_only"

        if not command and not stop_reason and verification_status == "unchanged" and _is_short_followup(instruction):
            stop_reason = "no_state_change"
            assistant_text = _build_shell_stop_reason_text(stop_reason, language, detail=verification_reason)
            action_type = "analysis_only"

        if not command and not stop_reason and _is_short_followup(instruction) and verification_status in {"unknown", ""} and blocker:
            stop_reason = str(blocker.get("code") or "manual_confirmation_needed")
            assistant_text = _build_shell_stop_reason_text(stop_reason, language, detail=str(blocker.get("reason") or ""))
            action_type = "analysis_only"

        if not command and not stop_reason and _is_short_followup(instruction):
            stop_reason = "no_safe_next_step"
            assistant_text = _build_shell_stop_reason_text(stop_reason, language)
            action_type = "analysis_only"

        session["updated_at"] = _utc_now()
        session["step_count"] = int(session.get("step_count", 0) or 0) + 1
        session["language"] = language
        session["container_name"] = container_name
        session["blueprint_id"] = blueprint_id
        session["last_reply"] = assistant_text
        session["last_command"] = command
        session["last_shell_tail"] = effective_tail
        session["last_stop_reason"] = stop_reason
        if instruction:
            session.setdefault("user_requests", []).append(instruction)
            session["user_requests"] = list(session["user_requests"])[-12:]
        if command:
            session.setdefault("commands", []).append(command)
            session["commands"] = list(session["commands"])[-12:]
        session.setdefault("step_history", []).append({
            "user_instruction": instruction,
            "assistant": assistant_text,
            "command": command,
            "action_type": action_type,
            "stop_reason": stop_reason,
            "created_at": _utc_now(),
        })
        session["step_history"] = list(session["step_history"])[-12:]

        with _TRION_SHELL_LOCK:
            _TRION_SHELL_SESSIONS[key] = session

        return {
            "ok": True,
            "active": not exit_shell,
            "container_id": container_id,
            "conversation_id": conversation_id,
            "language": language,
            "assistant": assistant_text,
            "command": command,
            "action_type": action_type,
            "verification": verification,
            "stop_reason": stop_reason,
            "exit_shell": exit_shell,
            "addon_docs": list(addon_context.get("selected_docs") or []),
            "model": llm_response["model"],
            "provider": llm_response["provider"],
            "requested_provider": llm_response["requested_provider"],
        }
    except Exception as e:
        logger.error("[Commander] TRION shell step error for %s: %s", container_id, e)
        return exception_response(e, details={"active": False, "container_id": container_id})


@router.post("/containers/{container_id}/trion-shell/stop")
async def api_trion_shell_stop(container_id: str, request: Request):
    """Stop TRION shell-control mode and persist a compact session summary."""
    try:
        from container_commander.ws_stream import emit_activity

        data = await request.json()
        conversation_id = str(data.get("conversation_id", "") or "").strip() or "global"
        shell_tail = str(data.get("shell_tail", "") or "")
        ui_language = str(data.get("ui_language", "") or "").strip()
        key = _shell_session_key(conversation_id, container_id)

        with _TRION_SHELL_LOCK:
            session = dict(_TRION_SHELL_SESSIONS.pop(key, {}) or {})

        language = str(session.get("language") or _reply_language("", ui_language=ui_language)).strip() or "en"
        labels = _localized_labels(language)
        container_name = str(session.get("container_name") or "")
        blueprint_id = str(session.get("blueprint_id") or "")
        effective_tail = (shell_tail or str(session.get("last_shell_tail") or ""))[-9000:]

        summary = ""
        if session:
            action_history = list(session.get("step_history") or [])[-8:]
            final_stop_reason = str(session.get("last_stop_reason") or "").strip()
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"You summarize a completed container shell debugging session. Reply in {'German' if language == 'de' else 'English'} only. "
                        "Return exactly one JSON object and no markdown. "
                        'Schema: {"goal":"short text","findings":["..."],"actions_taken":["..."],"changes_made":["..."],"blocker":"short text","next_step":"short text"}. '
                        "Clearly distinguish between checks performed and changes actually made. "
                        "If nothing was changed, set changes_made to an empty list."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Container: {container_name or container_id} ({blueprint_id or 'unknown'})\n"
                        f"User requests: {json.dumps(list(session.get('user_requests') or [])[-8:], ensure_ascii=True)}\n"
                        f"TRION commands: {json.dumps(list(session.get('commands') or [])[-8:], ensure_ascii=True)}\n"
                        f"Action history: {json.dumps(action_history, ensure_ascii=True)}\n"
                        f"Final stop reason: {final_stop_reason or '(none)'}\n"
                        f"Recent shell output tail:\n{effective_tail or '(none)'}\n"
                    ),
                },
            ]
            summary_response = await _complete_commander_chat(
                messages=messages,
                fallback_text="{}",
            )
            payload = _extract_json_object(str(summary_response.get("content", "") or ""))
            summary_parts = {
                "goal": str(payload.get("goal", "") or "").strip(),
                "findings": [str(item).strip() for item in list(payload.get("findings") or []) if str(item).strip()],
                "actions_taken": [str(item).strip() for item in list(payload.get("actions_taken") or []) if str(item).strip()],
                "changes_made": [str(item).strip() for item in list(payload.get("changes_made") or []) if str(item).strip()],
                "blocker": str(payload.get("blocker", "") or final_stop_reason).strip(),
                "next_step": str(payload.get("next_step", "") or "").strip(),
            }
            summary = _build_structured_shell_summary(summary_parts, language)
            if not summary:
                summary = (
                    "Shell-Sitzung beendet. Es wurde keine Zusammenfassung erzeugt." if language == "de"
                    else "Shell session ended. No summary could be generated."
                )

            if summary:
                from container_commander.shell_context_bridge import save_shell_session_summary
                save_shell_session_summary(
                    conversation_id=conversation_id,
                    container_id=container_id,
                    blueprint_id=blueprint_id,
                    container_name=container_name,
                    goal=summary_parts.get("goal", ""),
                    findings="; ".join(summary_parts.get("findings") or []),
                    changes_applied="; ".join(summary_parts.get("changes_made") or []),
                    open_blocker=summary_parts.get("blocker", ""),
                    step_count=int(session.get("step_count", 0) or 0),
                    commands=list(session.get("commands") or []),
                    user_requests=list(session.get("user_requests") or []),
                    final_stop_reason=final_stop_reason,
                    summary_parts=summary_parts,
                    raw_summary=summary,
                )

        emit_activity(
            "trion_shell_mode_stopped",
            level="info",
            message=labels["shell_stopped"],
            container_id=container_id,
            blueprint_id=blueprint_id,
            conversation_id=conversation_id,
        )
        return {
            "ok": True,
            "active": False,
            "container_id": container_id,
            "conversation_id": conversation_id,
            "language": language,
            "message": labels["shell_stopped"],
            "summary": summary,
        }
    except Exception as e:
        logger.error("[Commander] TRION shell stop error for %s: %s", container_id, e)
        return exception_response(e, details={"active": False, "container_id": container_id})


@router.post("/containers/{container_id}/stop")
async def api_stop_container(container_id: str):
    """Stop a container. Service containers may be preserved instead of removed."""
    try:
        from container_commander.engine import stop_container

        stopped = stop_container(container_id)
        if not stopped:
            return exception_response(
                HTTPException(404, "Container not found or already stopped"),
                error_code="not_found",
                details={"stopped": False, "container_id": container_id},
            )
        return {"stopped": True, "container_id": container_id}
    except Exception as e:
        return exception_response(e, details={"stopped": False})


@router.post("/containers/{container_id}/start")
async def api_start_existing_container(container_id: str):
    """Start a previously stopped TRION-managed container."""
    try:
        from container_commander.engine import start_stopped_container

        started = start_stopped_container(container_id)
        if not started:
            return exception_response(
                HTTPException(404, "Container not found or could not be started"),
                error_code="not_found",
                details={"started": False, "container_id": container_id},
            )
        return {"started": True, "container_id": container_id}
    except Exception as e:
        return exception_response(e, details={"started": False})


@router.get("/containers/{container_id}/host-companion/check")
async def api_check_host_companion(container_id: str):
    """Run host-companion checks for the blueprint behind a managed container."""
    try:
        from container_commander.engine import inspect_container, get_client
        from container_commander.host_companions import check_host_companion

        details = inspect_container(container_id)
        if not isinstance(details, dict) or details.get("error"):
            return exception_response(
                HTTPException(404, "Container not found"),
                error_code="not_found",
                details={"checked": False, "container_id": container_id},
            )
        blueprint_id = str(details.get("blueprint_id", "")).strip()
        if not blueprint_id or blueprint_id == "unknown":
            return exception_response(
                HTTPException(400, "Container is not linked to a TRION blueprint"),
                error_code="invalid_container",
                details={"checked": False, "container_id": container_id},
            )
        container = get_client().containers.get(container_id)
        result = check_host_companion(blueprint_id, container=container)
        return {
            "checked": True,
            "container_id": container_id,
            "blueprint_id": blueprint_id,
            "result": result,
        }
    except Exception as e:
        return exception_response(e, details={"checked": False, "container_id": container_id})


@router.post("/containers/{container_id}/host-companion/repair")
async def api_repair_host_companion(container_id: str):
    """Repair host-companion files/service for the blueprint behind a managed container."""
    try:
        from container_commander.engine import inspect_container, get_client
        from container_commander.host_companions import repair_host_companion

        details = inspect_container(container_id)
        if not isinstance(details, dict) or details.get("error"):
            return exception_response(
                HTTPException(404, "Container not found"),
                error_code="not_found",
                details={"repaired": False, "container_id": container_id},
            )
        blueprint_id = str(details.get("blueprint_id", "")).strip()
        if not blueprint_id or blueprint_id == "unknown":
            return exception_response(
                HTTPException(400, "Container is not linked to a TRION blueprint"),
                error_code="invalid_container",
                details={"repaired": False, "container_id": container_id},
            )
        container = get_client().containers.get(container_id)
        result = repair_host_companion(blueprint_id, container=container)
        return {
            "repaired": bool(result.get("repaired")),
            "container_id": container_id,
            "blueprint_id": blueprint_id,
            "result": result,
        }
    except Exception as e:
        return exception_response(e, details={"repaired": False, "container_id": container_id})


@router.post("/containers/{container_id}/host-companion/uninstall")
async def api_uninstall_host_companion(container_id: str):
    """Uninstall host-companion files/service for a stopped managed container."""
    try:
        from container_commander.engine import inspect_container
        from container_commander.host_companions import uninstall_host_companion

        details = inspect_container(container_id)
        if not isinstance(details, dict) or details.get("error"):
            return exception_response(
                HTTPException(404, "Container not found"),
                error_code="not_found",
                details={"uninstalled": False, "container_id": container_id},
            )
        if bool(details.get("running")):
            return exception_response(
                HTTPException(409, "Stop the container before uninstalling its host companion"),
                error_code="conflict",
                details={"uninstalled": False, "container_id": container_id},
            )
        blueprint_id = str(details.get("blueprint_id", "")).strip()
        if not blueprint_id or blueprint_id == "unknown":
            return exception_response(
                HTTPException(400, "Container is not linked to a TRION blueprint"),
                error_code="invalid_container",
                details={"uninstalled": False, "container_id": container_id},
            )
        result = uninstall_host_companion(blueprint_id)
        return {
            "uninstalled": bool(result.get("uninstalled")),
            "container_id": container_id,
            "blueprint_id": blueprint_id,
            "result": result,
        }
    except Exception as e:
        return exception_response(e, details={"uninstalled": False, "container_id": container_id})


@router.post("/containers/{container_id}/uninstall")
async def api_uninstall_container(container_id: str):
    """Remove a stopped managed container and uninstall its host companion when configured."""
    try:
        from container_commander.engine import inspect_container, remove_stopped_container
        from container_commander.host_companions import get_package_manifest, uninstall_host_companion

        details = inspect_container(container_id)
        if not isinstance(details, dict) or details.get("error"):
            return exception_response(
                HTTPException(404, "Container not found"),
                error_code="not_found",
                details={"uninstalled": False, "container_id": container_id},
            )
        if bool(details.get("running")):
            return exception_response(
                HTTPException(409, "Stop the container before uninstalling it"),
                error_code="conflict",
                details={"uninstalled": False, "container_id": container_id},
            )
        blueprint_id = str(details.get("blueprint_id", "")).strip()
        if not blueprint_id or blueprint_id == "unknown":
            return exception_response(
                HTTPException(400, "Container is not linked to a TRION blueprint"),
                error_code="invalid_container",
                details={"uninstalled": False, "container_id": container_id},
            )

        host_result = {"uninstalled": False, "skipped": True, "reason": "host_companion_not_configured"}
        manifest = get_package_manifest(blueprint_id)
        if isinstance(manifest, dict) and isinstance(manifest.get("host_companion"), dict):
            host_result = uninstall_host_companion(blueprint_id)

        remove_result = remove_stopped_container(container_id)
        if not bool(remove_result.get("removed")):
            reason = str(remove_result.get("reason", "")).strip()
            if reason == "running":
                return exception_response(
                    HTTPException(409, "Stop the container before uninstalling it"),
                    error_code="conflict",
                    details={"uninstalled": False, "container_id": container_id},
                )
            if reason == "not_found":
                return exception_response(
                    HTTPException(404, "Container not found"),
                    error_code="not_found",
                    details={"uninstalled": False, "container_id": container_id},
                )
            raise RuntimeError(f"container_uninstall_failed: {reason or 'unknown'}")

        notes = ["container removed"]
        if bool(host_result.get("uninstalled")):
            notes.append("host companion removed")
        else:
            notes.append("host companion unchanged or not configured")
        notes.append("storage under /data is intentionally preserved")

        return {
            "uninstalled": True,
            "removed": True,
            "container_id": container_id,
            "blueprint_id": blueprint_id,
            "host_companion": host_result,
            "result": {
                "removed": True,
                "host_companion_uninstalled": bool(host_result.get("uninstalled")),
                "removed_paths": list(host_result.get("removed_paths") or []),
                "notes": notes,
            },
        }
    except Exception as e:
        return exception_response(e, details={"uninstalled": False, "container_id": container_id})


@router.get("/containers/{container_id}/logs")
async def api_container_logs(container_id: str, tail: int = 100):
    """Get logs from a container."""
    try:
        from container_commander.engine import get_container_logs

        logs = get_container_logs(container_id, tail)
        return {"container_id": container_id, "logs": logs}
    except Exception as e:
        return exception_response(e)


@router.get("/containers/{container_id}/stats")
async def api_container_stats(container_id: str):
    """Get live resource stats + efficiency score."""
    try:
        from container_commander.engine import get_container_stats

        return get_container_stats(container_id)
    except Exception as e:
        return exception_response(e)


@router.get("/quota")
async def api_get_quota():
    """Get current session quota usage."""
    try:
        from container_commander.engine import get_quota

        q = get_quota()
        return q.model_dump()
    except Exception as e:
        return exception_response(e)


@router.post("/cleanup")
async def api_cleanup_all():
    """Emergency: stop and remove ALL TRION containers."""
    try:
        from container_commander.engine import cleanup_all

        cleanup_all()
        return {"cleaned": True}
    except Exception as e:
        return exception_response(e)
