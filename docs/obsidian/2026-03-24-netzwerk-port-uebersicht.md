# Netzwerk & Port-Übersicht — Jarvis Server

Stand: 2026-03-26
Host: `<HOST_LAN_IP>` | Tailscale: `<HOST_TAILSCALE_IP>`

> Update 2026-03-27:
> `gaming-station` nutzt wieder den Host-Bridge-Pfad.
> Sunshine-/Moonlight-Ports liegen damit aktuell hostseitig am Host-Companion und nicht mehr als direkte Container-Port-Bindings am `gaming-station`-Container.
> Die Portzeilen fuer `gaming-station` in dieser Notiz sind daher historischer `primary`-Stand.
>
> Archivhinweis 2026-04-01:
> Der fruehere `gaming-station`-/Gaming-Container-Zweig ist inzwischen gestoppt und archiviert.
> Diese Portzeilen bleiben nur noch als historische Referenz erhalten.

---

## Host-native Dienste

Diese Prozesse laufen direkt auf dem Host, nicht in Docker.

| Port | Protokoll | Dienst | Notiz |
|------|-----------|--------|-------|
| 22 | TCP | SSH (sshd) | Zugang für `danny` und `claude` |
| 80 | TCP | CasaOS Gateway | casaos-gateway — App-Store / Verwaltung |
| 139 | TCP | Samba (smbd) | Filesharing im LAN |
| 445 | TCP | Samba (smbd) | Filesharing im LAN |
| 443 | TCP | Tailscaled | VPN-Endpunkt |
| 42386 | TCP | Tailscaled | VPN (dynamischer Port) |
| 61106 | TCP | Tailscaled | VPN (dynamischer Port) |
| 53 | UDP/TCP | dnsmasq | DNS für internes Docker-Netz (`<LIBVIRT_BRIDGE_IP>`) |
| 631 | TCP | CUPS | Druckerserver (nur localhost) |

---

## Docker-Container

Alle Container laufen über `docker-proxy` auf dem Host gebunden.

### Jarvis-Stack

| Port | Container | Beschreibung |
|------|-----------|--------------|
| 8400 | `jarvis-webui` | Jarvis Frontend (Nginx, TRION UI) |
| 8401 | `trion-runtime` | TRION Core Runtime |
| 8200 | `jarvis-admin-api` | Admin API (FastAPI) |
| 8000 | `tool-executor` | MCP Tool Executor |
| 8088 | `trion-skill-server` | TRION Skill-Server |
| 8300 | `validator-service` | Schema Validator |
| 8420 | `runtime-hardware` | Runtime Hardware API (v0, deployed) |
| 8089 | `storage-broker` | Storage Broker MCP (Port 8089) |
| 8082 | `mcp-sql-memory` | SQL Memory MCP |
| 47984 | `gaming-station` (historisch, gestoppt/archiviert) | Sunshine RTSP (legacy) |
| 47989 | `gaming-station` (historisch, gestoppt/archiviert) | Sunshine HTTPS API (GFE-Kompatibilität) |
| 47990 | `gaming-station` (historisch, gestoppt/archiviert) | Sunshine HTTP WebUI (Moonlight-Pairing) |
| 48010 | `gaming-station` (historisch, gestoppt/archiviert) | Sunshine RTSP (modern) |
| 47998 | `gaming-station` (historisch, gestoppt/archiviert) | Sunshine Video (UDP) |
| 47999 | `gaming-station` (historisch, gestoppt/archiviert) | Sunshine Control (UDP) |
| 48000 | `gaming-station` (historisch, gestoppt/archiviert) | Sunshine Audio (UDP) |
| 48002 | `gaming-station` (historisch, gestoppt/archiviert) | Sunshine Mic (UDP) |
| 8085 | `sequential-thinking` | Sequential Thinking MCP |
| 8086 | `cim-server` | CIM MCP Server |
| 8087 | `document-processor` | Document Processor MCP |
| 8100 | `lobechat-adapter` | LobeChat Adapter |

### Infrastruktur

| Port | Container | Beschreibung |
|------|-----------|--------------|
| 81 | `nginxproxymanager` | NPM Web UI |
| 8081 | `nginxproxymanager` | NPM HTTP Proxy |
| 4043 | `nginxproxymanager` | NPM HTTPS Proxy |
| 9000 | `big-bear-portainer` | Portainer HTTP |
| 9443 | `big-bear-portainer` | Portainer HTTPS |
| 8500 | `big-bear-portainer` | Portainer Agent |
| 11434 | `ollama` | Ollama LLM API |

### Apps

| Port | Container | Beschreibung |
|------|-----------|--------------|
| 3210 | `big-bear-lobe-chat` | LobeChat Web UI |
| 5678 | `n8n` | n8n Workflow Automation |
| 8285 | `romm` | RomM (Retro-ROM-Manager) |

---

## Netzwerk-Interfaces

| Interface | IP | Zweck |
|-----------|----|-------|
| Haupt-NIC | `<HOST_LAN_IP>` | LAN |
| tailscale0 | `<HOST_TAILSCALE_IP>` | Tailscale VPN |
| virbr0 | `<LIBVIRT_BRIDGE_IP>` | Libvirt/KVM (dnsmasq) |
| docker0 | `172.17.0.1` | Docker default bridge |

---

## Port-Vergabe-Konvention (Jarvis)

```
8000        Tool Executor
8081–8089   MCP-Dienste (8082, 8085, 8086, 8087, 8088, 8089)
8100        Adapter-Schicht
8200        Admin API
8300        Validator
8400        WebUI
8401        Runtime
8420        Runtime Hardware (deployed)
```

Nächste freie MCP-Ports: **8084**, **8090–8099**

---

## Historischer Zwischenstand

- Die Aussagen unten zu `gaming-station`-Containerports und "`Sunshine auf Host` vollstaendig deinstalliert" gehoeren zum alten `primary`-Zwischenstand.
- Der aktuelle Live-Stand ist wieder:
  - Sunshine auf dem Host
  - `gaming-station` als Host-Bridge-/`secondary`-Container
  - noVNC bleibt weiterhin kein relevanter Hauptpfad

---

## Schnell-Diagnose-Befehle

```bash
# Alle lauschenden Ports (öffentlich)
ss -tlnp | grep -v 127\. | grep -v ::1

# Welcher Container hört auf Port X?
docker ps --format '{{.Names}} {{.Ports}}' | grep ':8200->'

# Tailscale Status
tailscale status

# Samba Status
systemctl status smbd
```

Publish-Hinweis 2026-04-07: echte Host- und Tailscale-IP-Adressen wurden fuer das oeffentliche Repo redigiert. Lokale Bridge-/Virtualisierungs-Adressen bleiben als Architekturkontext erhalten.
