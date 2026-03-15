"""
SysInfo MCP Tools — Read-only system diagnostics

Allowlist-based: TRION kann lesen, aber nichts verändern.
Nutzt native /proc-Fallbacks für Befehle die im Container fehlen.
"""
import subprocess
import logging
import json
import os
import http.client
import socket
import csv
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ══════════════════════════════════════════════════════════════

def _run(cmd: list, timeout: int = 10) -> str:
    """Führt einen Befehl aus, gibt stdout zurück oder wirft Exception."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(result.stderr.strip() or f"Exit code {result.returncode}")
    return result.stdout.strip()


def _proc_ram() -> str:
    """RAM-Info aus /proc/meminfo (kein 'free'-Binary nötig)."""
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            parts = line.split()
            info[parts[0].rstrip(":")] = int(parts[1])
    total_mb  = info["MemTotal"]     // 1024
    avail_mb  = info["MemAvailable"] // 1024
    used_mb   = total_mb - avail_mb
    buffers   = info.get("Buffers", 0) // 1024
    cached    = info.get("Cached", 0)  // 1024
    return (
        f"{'Gesamt':>10}: {total_mb:>7} MB\n"
        f"{'Genutzt':>10}: {used_mb:>7} MB\n"
        f"{'Verfügbar':>10}: {avail_mb:>7} MB\n"
        f"{'Buffers':>10}: {buffers:>7} MB\n"
        f"{'Cached':>10}: {cached:>7} MB"
    )


def _proc_uptime() -> str:
    """Uptime aus /proc/uptime (kein 'uptime'-Binary nötig)."""
    with open("/proc/uptime") as f:
        up_secs = float(f.read().split()[0])
    days, rem = divmod(int(up_secs), 86400)
    hrs, rem  = divmod(rem, 3600)
    mins      = rem // 60

    # Load average aus /proc/loadavg
    try:
        with open("/proc/loadavg") as f:
            load = f.read().split()[:3]
        load_str = f"load average: {', '.join(load)}"
    except Exception:
        load_str = ""

    return f"up {days} days, {hrs}:{mins:02d}  {load_str}"


def _proc_processes() -> str:
    """Top-Prozesse nach CPU aus /proc (kein 'ps'-Binary nötig)."""
    procs = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/stat") as f:
                stat = f.read().split()
            name = stat[1].strip("()")
            utime = int(stat[13])
            stime = int(stat[14])
            cpu_ticks = utime + stime

            with open(f"/proc/{pid}/status") as f:
                status_lines = dict(
                    line.split(":\t", 1) for line in f
                    if ":\t" in line
                )
            vmrss_kb = int(status_lines.get("VmRSS", "0 kB").split()[0])
            procs.append((cpu_ticks, pid, name, vmrss_kb))
        except Exception:
            continue

    procs.sort(reverse=True)
    lines = [f"{'PID':>7} {'NAME':<20} {'CPU-TICKS':>10} {'MEM (MB)':>9}"]
    for ticks, pid, name, rss in procs[:15]:
        lines.append(f"{pid:>7} {name:<20} {ticks:>10} {rss//1024:>8} MB")
    return "\n".join(lines)


def _proc_network() -> str:
    """Offene Ports aus /proc/net/tcp + tcp6 (kein 'ss'-Binary nötig)."""
    results = []
    for proto_file, proto in [("/proc/net/tcp", "tcp4"), ("/proc/net/tcp6", "tcp6")]:
        try:
            with open(proto_file) as f:
                lines = f.readlines()[1:]
            for line in lines:
                parts = line.split()
                state = parts[3]
                if state != "0A":  # 0A = LISTEN
                    continue
                local = parts[1]
                port_hex = local.split(":")[1]
                port = int(port_hex, 16)
                results.append(f"{proto:<6} *:{port}")
        except Exception:
            pass

    if not results:
        return "Keine lauschenden Ports gefunden"
    return "Proto  Adresse\n" + "\n".join(sorted(results, key=lambda x: int(x.split(":")[1])))


def _parse_gpu_csv_row(raw_output: str) -> Dict[str, Any]:
    """
    Parse one nvidia-smi CSV row into explicit, typed fields.
    Expected order:
      name,memory.total,memory.free,memory.used,utilization.gpu,temperature.gpu,driver_version
    """
    lines = [line.strip() for line in (raw_output or "").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Leere GPU-Ausgabe von nvidia-smi")

    row = next(csv.reader([lines[0]], skipinitialspace=True))
    if len(row) < 7:
        raise RuntimeError(f"Unerwartetes GPU-CSV-Format: {lines[0]}")

    def _to_int(value: str) -> int:
        cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch == "-")
        return int(cleaned) if cleaned and cleaned != "-" else 0

    return {
        "gpu_name": row[0].strip(),
        "vram_total_mib": _to_int(row[1]),
        "vram_free_mib": _to_int(row[2]),
        "vram_used_mib": _to_int(row[3]),
        "gpu_util_percent": _to_int(row[4]),
        "temperature_c": _to_int(row[5]),
        "driver_version": row[6].strip(),
    }


def _docker_stats() -> str:
    """Container-Stats via Docker-Socket (kein docker-CLI nötig)."""
    try:
        class _UnixConn(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect("/var/run/docker.sock")

        conn = _UnixConn("localhost")
        conn.request("GET", "/containers/json")
        resp = conn.getresponse()
        containers = json.loads(resp.read())

        if not containers:
            return "Keine laufenden Container"

        lines = [f"{'NAME':<35} {'STATUS':<10} {'IMAGE':<30}"]
        for c in containers:
            name  = c["Names"][0].lstrip("/")
            state = c["State"]
            image = c["Image"][:28]
            lines.append(f"{name:<35} {state:<10} {image:<30}")

        return "\n".join(lines)
    except Exception as e:
        return f"Docker-Socket nicht erreichbar: {e}"


def _dmesg_fallback() -> str:
    """Kernel-Log aus /var/log/dmesg oder /proc/kmsg (read)."""
    # Versuche /var/log/kern.log
    for logfile in ["/var/log/kern.log", "/var/log/dmesg", "/var/log/syslog"]:
        try:
            with open(logfile) as f:
                lines = f.readlines()
            errors = [l.rstrip() for l in lines if
                      any(kw in l.lower() for kw in ["error", "warn", "fail", "critical"])]
            return "\n".join(errors[-20:]) if errors else f"Keine Fehler in {logfile}"
        except Exception:
            continue
    return "Kein Kernel-Log zugänglich (dmesg fehlt im Container)"


# ══════════════════════════════════════════════════════════════
# TOOL-IMPLEMENTIERUNGEN
# ══════════════════════════════════════════════════════════════

def _get_info(info_type: str) -> Dict[str, Any]:
    """Führt den passenden Diagnose-Befehl aus."""

    try:
        if info_type == "gpu":
            raw_output = _run([
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free,memory.used,"
                "utilization.gpu,temperature.gpu,driver_version",
                "--format=csv,noheader",
            ])
            parsed = _parse_gpu_csv_row(raw_output)
            output = (
                f"GPU: {parsed['gpu_name']}\n"
                f"VRAM total: {parsed['vram_total_mib']} MiB\n"
                f"VRAM frei: {parsed['vram_free_mib']} MiB\n"
                f"VRAM genutzt: {parsed['vram_used_mib']} MiB\n"
                f"GPU-Auslastung: {parsed['gpu_util_percent']} %\n"
                f"Temperatur: {parsed['temperature_c']} C\n"
                f"Treiber: {parsed['driver_version']}\n"
                f"Hinweis: GPU-Auslastung ist NICHT VRAM-Auslastung."
            )
            return {
                "success": True,
                "type": info_type,
                "output": output,
                "metrics": parsed,
                "raw_output": raw_output,
                "description": _DESCRIPTIONS.get(info_type, ""),
            }
        elif info_type == "gpu_full":
            output = _run(["nvidia-smi"])
        elif info_type == "cpu":
            output = _run(["lscpu"])
        elif info_type == "ram":
            output = _proc_ram()
        elif info_type == "disk":
            output = _run(["df", "-h"])
        elif info_type == "processes":
            output = _proc_processes()
        elif info_type == "network":
            # ss bevorzugen, Fallback auf /proc
            try:
                output = _run(["ss", "-tulpn"])
            except Exception:
                output = _proc_network()
        elif info_type == "net_stats":
            try:
                output = _run(["ss", "-s"])
            except Exception:
                output = _proc_network()
        elif info_type == "docker":
            output = _docker_stats()
        elif info_type == "dmesg":
            try:
                output = _run(["dmesg", "--level=err,warn", "--time-format=reltime"])
            except Exception:
                output = _dmesg_fallback()
        elif info_type == "uptime":
            output = _proc_uptime()
        elif info_type == "kernel":
            output = _run(["uname", "-a"])
        else:
            return {
                "success": False,
                "error": f"Unbekannter Typ: '{info_type}'",
                "available_types": list(_DESCRIPTIONS.keys()),
            }

        return {
            "success": True,
            "type": info_type,
            "output": output,
            "description": _DESCRIPTIONS.get(info_type, ""),
        }

    except Exception as e:
        logger.error(f"[SysInfo] {info_type} failed: {e}")
        return {
            "success": False,
            "type": info_type,
            "error": str(e),
        }


_DESCRIPTIONS = {
    "gpu":       "GPU-Modell, VRAM gesamt/frei/genutzt, Auslastung, Temperatur, Treiber",
    "gpu_full":  "Vollständiger nvidia-smi Output",
    "cpu":       "CPU-Modell, Kerne, Architektur, Cache, Frequenz",
    "ram":       "RAM gesamt/genutzt/verfügbar (aus /proc/meminfo)",
    "disk":      "Festplatten-Nutzung aller Mounts",
    "processes": "Top-15 Prozesse nach CPU-Ticks",
    "network":   "Lauschende Ports und Dienste",
    "net_stats": "Netzwerk-Socket-Statistiken",
    "docker":    "Laufende Docker-Container mit Status",
    "dmesg":     "Kernel-Fehler und Warnungen",
    "uptime":    "System-Uptime und Load Average",
    "kernel":    "Kernel-Version und Systemarchitektur",
}


# ══════════════════════════════════════════════════════════════
# MCP TOOL DEFINITIONS
# ══════════════════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "name": "get_system_info",
        "description": (
            "Liest System-Hardware und Diagnose-Informationen (read-only, allowlist-based). "
            "Typen: gpu (GPU+VRAM+Temp), gpu_full, cpu, ram, disk, processes, "
            "network (offene Ports), net_stats, docker (Container-Status), "
            "dmesg (Kernel-Fehler), uptime, kernel. "
            "Beispiel: type='gpu' → RTX 2060 SUPER, 8GB VRAM, 45°C"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Art der Information (gpu/cpu/ram/disk/processes/network/docker/dmesg/uptime/kernel)",
                    "enum": list(_DESCRIPTIONS.keys()),
                }
            },
            "required": ["type"],
        },
    },
    {
        "name": "get_system_overview",
        "description": (
            "Kompakte System-Übersicht: GPU, CPU, RAM, Disk und Uptime auf einmal. "
            "Ideal für einen schnellen Hardware-Check."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_used_ports",
        "description": "Listet belegte Host-Ports (read-only) aus /proc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_udp": {"type": "boolean", "default": True},
            },
            "required": [],
        },
    },
    {
        "name": "check_port",
        "description": "Prüft, ob ein spezifischer Host-Port frei ist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "Host-Port"},
                "protocol": {"type": "string", "enum": ["tcp", "udp"], "default": "tcp"},
            },
            "required": ["port"],
        },
    },
    {
        "name": "find_free_port",
        "description": "Findet den ersten freien Port in einem Bereich.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_port": {"type": "integer", "default": 8000},
                "max_port": {"type": "integer", "default": 9000},
                "protocol": {"type": "string", "enum": ["tcp", "udp"], "default": "tcp"},
            },
            "required": [],
        },
    },
    {
        "name": "list_blueprint_ports",
        "description": "Zeigt Port-Reservierungen laufender TRION-Container (aus Labels/Docker-Inspect).",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def _tool_get_system_overview(_args: dict) -> dict:
    sections = {}
    for key in ["gpu", "cpu", "ram", "disk", "uptime"]:
        r = _get_info(key)
        sections[key] = r.get("output", r.get("error", "n/a"))
    return {
        "success": True,
        "overview": sections,
        "description": "Kompakte System-Übersicht",
    }


def _tool_list_used_ports(args: dict) -> dict:
    from container_commander.port_manager import list_used_ports

    rows = list_used_ports(include_udp=bool(args.get("include_udp", True)))
    return {"success": True, "ports": rows, "count": len(rows)}


def _tool_check_port(args: dict) -> dict:
    from container_commander.port_manager import check_port

    port = int(args.get("port", 0))
    protocol = str(args.get("protocol", "tcp")).lower()
    if port <= 0:
        return {"success": False, "error": "Parameter 'port' fehlt oder ist ungültig"}
    free, reason = check_port(port, protocol=protocol)
    return {
        "success": True,
        "port": port,
        "protocol": protocol,
        "free": free,
        "reason": reason,
    }


def _tool_find_free_port(args: dict) -> dict:
    from container_commander.port_manager import find_free_port

    min_port = int(args.get("min_port", 8000))
    max_port = int(args.get("max_port", 9000))
    protocol = str(args.get("protocol", "tcp")).lower()
    port = find_free_port(min_port=min_port, max_port=max_port, protocol=protocol)
    return {
        "success": True,
        "port": port,
        "protocol": protocol,
        "range": {"min_port": min_port, "max_port": max_port},
    }


def _tool_list_blueprint_ports(_args: dict) -> dict:
    from container_commander.port_manager import list_blueprint_ports

    rows = list_blueprint_ports()
    return {"success": True, "reservations": rows, "count": len(rows)}


def call_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Dispatcher für alle SysInfo-Tools."""
    try:
        if tool_name == "get_system_info":
            info_type = arguments.get("type", "")
            if not info_type:
                return {
                    "success": False,
                    "error": "Parameter 'type' fehlt",
                    "available_types": list(_DESCRIPTIONS.keys()),
                    "descriptions": _DESCRIPTIONS,
                }
            return _get_info(info_type)
        elif tool_name == "get_system_overview":
            return _tool_get_system_overview(arguments)
        elif tool_name == "list_used_ports":
            return _tool_list_used_ports(arguments)
        elif tool_name == "check_port":
            return _tool_check_port(arguments)
        elif tool_name == "find_free_port":
            return _tool_find_free_port(arguments)
        elif tool_name == "list_blueprint_ports":
            return _tool_list_blueprint_ports(arguments)
        else:
            return {"error": f"Unbekanntes Tool: {tool_name}"}
    except Exception as e:
        logger.error(f"[SysInfo] Tool '{tool_name}' failed: {e}")
        return {"error": str(e)}


def get_tool_definitions() -> List[Dict]:
    return TOOL_DEFINITIONS
