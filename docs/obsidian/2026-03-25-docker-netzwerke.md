# Docker Netzwerke — Übersicht

Stand: 2026-03-26
Host: `<HOST_LAN_IP>` (redacted for public repo)

> Update 2026-03-27:
> Die fruehere Annahme "`gaming-station` published Sunshine-Ports direkt aus dem Container" ist veraltet.
> Im aktuellen Host-Bridge-Pfad liegen die Sunshine-Ports hostseitig am Host-Companion/`sunshine-host.service`, nicht mehr am Container selbst.
> Die Container-Eintraege fuer `47984` bis `48002` in dieser Notiz sind deshalb als historischer `primary`-Stand zu lesen.
>
> Archivhinweis 2026-04-01:
> Der fruehere `gaming-station`-/Gaming-Container-Zweig ist gestoppt und archiviert.
> Alle Container- und Portangaben dazu bleiben nur noch als historische Referenz erhalten.

Gesamt: **9 Netzwerke** (3 Docker-intern, 6 anwendungsspezifisch)

---

## Übersicht

| Netzwerk | Treiber | Subnetz | Zweck |
|---|---|---|---|
| `bridge` | bridge | `172.17.0.0/16` | Docker-Default — Container ohne explizites Netz |
| `host` | host | — | Host-Netzwerk-Modus (kein NAT) |
| `none` | null | — | Kein Netzwerk |
| `big-bear-lobe-chat_default` | bridge | `172.18.0.0/16` | Jarvis-Stack (alle Core-Services) |
| `jarvis_default` | bridge | — | Docker-Compose-Default (aktuell leer) |
| `trion-sandbox` | bridge | `172.21.0.0/16` | TRION Container-Sandbox |
| `romm_romm-network` | bridge | `172.22.0.0/16` | RomM + RomM-DB |
| `big-bear-n8n_default` | bridge | — | n8n (aktuell leer, n8n hängt im bridge-Netz) |
| `umbrel_main_network` | bridge | `10.21.0.0/16` | Umbrel (aktuell keine aktiven Container) |

---

## bridge (172.17.0.0/16) — Docker-Default

Gateway: `172.17.0.1` (docker0)

| Container | IP | Host-Ports |
|---|---|---|
| `big-bear-portainer` | 172.17.0.2 | `9000/tcp`, `9443/tcp`, `8500→8000/tcp` |
| `n8n` | 172.17.0.3 | `5678/tcp` |
| `nginxproxymanager` | 172.17.0.4 | `81/tcp`, `8081→80/tcp`, `4043→443/tcp` |
| `trion_gaming-station_*` (historisch, gestoppt/archiviert) | 172.17.0.5 | `47984/tcp`, `47989/tcp`, `47990/tcp`, `48010/tcp`, `47998-48000/udp`, `48002/udp` |

---

## big-bear-lobe-chat_default (172.18.0.0/16) — Jarvis-Stack

Gateway: `172.18.0.1`
Alle Jarvis-Core-Services teilen dieses Netzwerk.

| Container | IP | Host-Ports |
|---|---|---|
| `big-bear-lobe-chat` | 172.18.0.2 | `3210/tcp` |
| `validator-service` | 172.18.0.3 | `8300→8000/tcp` |
| `cim-server` | 172.18.0.4 | `8086/tcp` |
| `document-processor` | 172.18.0.5 | `8087/tcp` |
| `mcp-sql-memory` | 172.18.0.6 | `8082→8081/tcp` |
| `tool-executor` | 172.18.0.7 | `8000/tcp` |
| `storage-host-helper` | 172.18.0.8 | `8090/tcp` (intern, kein Host-Binding) |
| `trion-runtime` | 172.18.0.9 | `8401/tcp` |
| `lobechat-adapter` | 172.18.0.10 | `8100/tcp` |
| `trion-skill-server` | 172.18.0.11 | `8088/tcp` |
| `sequential-thinking` | 172.18.0.12 | `8085/tcp` |
| `jarvis-admin-api` | 172.18.0.13 | `8200/tcp` |
| `ollama` | 172.18.0.14 | `11434/tcp` |
| `jarvis-webui` | 172.18.0.15 | `8400→80/tcp` |
| `storage-broker` | 172.18.0.16 | `8089/tcp` |
| `runtime-hardware` | aktiv im Jarvis-Stack | `8420/tcp` (v0, deployed) |

---

## trion-sandbox (172.21.0.0/16) — TRION Container-Sandbox

Gateway: `172.21.0.1`
Isoliertes Netz für TRION-verwaltete Container (kein direkter Stack-Zugang).

| Container | IP | Host-Ports |
|---|---|---|
| `trion_trion-home_*` | 172.21.0.2 | — (kein Port-Binding) |

---

## romm_romm-network (172.22.0.0/16) — RomM

Gateway: `172.22.0.1`

| Container | IP | Host-Ports |
|---|---|---|
| `romm-db` | 172.22.0.2 | `3306/tcp` (intern, kein Host-Binding) |
| `romm` | 172.22.0.3 | `8285→8080/tcp` |

---

## Leere / Spezial-Netzwerke

| Netzwerk | Status | Notiz |
|---|---|---|
| `jarvis_default` | leer | Docker-Compose-Artefakt, keine aktiven Container |
| `big-bear-n8n_default` | leer | n8n läuft im bridge-Netz, nicht hier |
| `umbrel_main_network` | leer | Umbrel-Stack aktuell nicht aktiv |
| `host` | Docker-intern | Kein NAT, Container teilt Host-Netz |
| `none` | Docker-intern | Isolierter Container ohne jedes Netz |

---

## Port-Schnellreferenz (alle gebundenen Host-Ports)

| Port | Protokoll | Container | Dienst |
|---|---|---|---|
| 81 | TCP | `nginxproxymanager` | NPM Web UI |
| 3210 | TCP | `big-bear-lobe-chat` | LobeChat Web UI |
| 4043 | TCP | `nginxproxymanager` | NPM HTTPS Proxy |
| 5678 | TCP | `n8n` | n8n Workflow Automation |
| 8000 | TCP | `tool-executor` | MCP Tool Executor |
| 8081 | TCP | `nginxproxymanager` | NPM HTTP Proxy |
| 8082 | TCP | `mcp-sql-memory` | SQL Memory MCP |
| 8085 | TCP | `sequential-thinking` | Sequential Thinking MCP |
| 8086 | TCP | `cim-server` | CIM MCP Server |
| 8087 | TCP | `document-processor` | Document Processor MCP |
| 8088 | TCP | `trion-skill-server` | TRION Skill-Server |
| 8089 | TCP | `storage-broker` | Storage Broker MCP |
| 8100 | TCP | `lobechat-adapter` | LobeChat Adapter |
| 8200 | TCP | `jarvis-admin-api` | Admin API |
| 8285 | TCP | `romm` | RomM Web UI |
| 8300 | TCP | `validator-service` | Schema Validator |
| 8400 | TCP | `jarvis-webui` | Jarvis Frontend (TRION UI) |
| 8401 | TCP | `trion-runtime` | TRION Core Runtime |
| 8420 | TCP | `runtime-hardware` | Runtime Hardware API (v0, deployed) |
| 8500 | TCP | `big-bear-portainer` | Portainer Agent |
| 9000 | TCP | `big-bear-portainer` | Portainer HTTP |
| 9443 | TCP | `big-bear-portainer` | Portainer HTTPS |
| 11434 | TCP | `ollama` | Ollama LLM API |
| 47984 | TCP | `trion_gaming-station_*` (historisch, gestoppt/archiviert) | Sunshine RTSP (legacy) |
| 47989 | TCP | `trion_gaming-station_*` (historisch, gestoppt/archiviert) | Sunshine HTTPS API |
| 47990 | TCP | `trion_gaming-station_*` (historisch, gestoppt/archiviert) | Sunshine HTTP WebUI |
| 48010 | TCP | `trion_gaming-station_*` (historisch, gestoppt/archiviert) | Sunshine RTSP (modern) |
| 47998 | UDP | `trion_gaming-station_*` (historisch, gestoppt/archiviert) | Sunshine Video |
| 47999 | UDP | `trion_gaming-station_*` (historisch, gestoppt/archiviert) | Sunshine Control |
| 48000 | UDP | `trion_gaming-station_*` (historisch, gestoppt/archiviert) | Sunshine Audio |
| 48002 | UDP | `trion_gaming-station_*` (historisch, gestoppt/archiviert) | Sunshine Mic |

---

## Notizen

- Publish-Hinweis 2026-04-07: echte Host-/Client-IP-Adressen wurden aus dieser Notiz entfernt. Subnetze, Docker-Bridge-Adressen und exemplarische Container-IPs bleiben als technische Architekturinfo bewusst erhalten.
- `storage-host-helper` ist intern auf Port `8090` erreichbar, hat aber kein Host-Binding — wird nur vom Jarvis-Stack intern aufgerufen.
- `runtime-hardware` verwendet fuer den neuen v0-Service Port `8420/tcp`; die Bindung ist im laufenden Commander-Deploy aktiv und fuer den Service reserviert.
- `romm-db` (MySQL) ist nur intern erreichbar, kein Host-Binding.
- Der gaming-station Container-Name enthielt einen Timestamp und änderte sich bei jedem Redeploy. Dieser Containerzweig ist inzwischen gestoppt und archiviert.
