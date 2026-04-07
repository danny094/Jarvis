# TRION — Dienste, Ports & Netzwerke

Stand: 2026-03-26
Host: `<HOST_LAN_IP>` | Tailscale: `<HOST_TAILSCALE_IP>`

> Update 2026-03-27:
> Die `gaming-station`-Porttabellen in dieser Notiz spiegeln noch den alten `primary`-Containerpfad.
> Der aktuelle operative Stand ist wieder Host-Bridge:
> - `gaming-station` selbst published keine Sunshine-Ports mehr
> - die Streaming-Ports liegen hostseitig am Host-Companion/`sunshine-host.service`

---

## Netzwerk-Übersicht (TRION-relevant)

| Netzwerk | Subnetz | Zweck |
|---|---|---|
| `big-bear-lobe-chat_default` | `172.18.0.0/16` | Internes Stack-Netz — alle Core-Services kommunizieren hier |
| `bridge` (Docker-Default) | `172.17.0.0/16` | TRION-verwaltete Container (gaming-station, trion-home) |
| `trion-sandbox` | `172.21.0.0/16` | Isoliertes Netz für TRION-Sandbox-Container |

---

## Core-Stack (docker-compose)

Alle Services im Netz `big-bear-lobe-chat_default` (`172.18.0.0/16`).

### Frontend & Gateway

| Service | Container | Intern (172.18.x) | Host-Port | Zweck |
|---|---|---|---|---|
| Jarvis Web UI | `jarvis-webui` | 172.18.0.15 | `8400/tcp` | TRION Frontend (Nginx, Commander UI) |
| Lobechat Adapter | `lobechat-adapter` | 172.18.0.10 | `8100/tcp` | LobeChat ↔ TRION Bridge |

### Runtime & API

| Service | Container | Intern (172.18.x) | Host-Port | Zweck |
|---|---|---|---|---|
| TRION Runtime | `trion-runtime` | 172.18.0.9 | `8401/tcp` | Core Runtime (Orchestrator, Layers) |
| Admin API | `jarvis-admin-api` | 172.18.0.13 | `8200/tcp` | Container Commander API (FastAPI) |
| Runtime Hardware | `runtime-hardware` | aktiv im Stack | `8420/tcp` | Hardware-, Capability- und Attachment-Planungsdienst (v0, deployed) |
| Tool Executor | `tool-executor` | 172.18.0.7 | `8000/tcp` | MCP Tool Executor |
| Skill Server | `trion-skill-server` | 172.18.0.11 | `8088/tcp` | TRION Skill-Server |
| Validator | `validator-service` | 172.18.0.3 | `8300/tcp` | Schema Validator |

### MCP-Server

| Service | Container | Intern (172.18.x) | Host-Port | Zweck |
|---|---|---|---|---|
| Storage Broker | `storage-broker` | 172.18.0.16 | `8089/tcp` | Storage Broker MCP (Disk-Management) |
| SQL Memory | `mcp-sql-memory` | 172.18.0.6 | `8082/tcp` | SQL-basiertes Memory MCP |
| Sequential Thinking | `sequential-thinking` | 172.18.0.12 | `8085/tcp` | Sequential Thinking MCP |
| CIM Server | `cim-server` | 172.18.0.4 | `8086/tcp` | CIM MCP Server |
| Document Processor | `document-processor` | 172.18.0.5 | `8087/tcp` | Document Processor MCP |

### Interne Dienste (kein Host-Binding)

| Service | Container | Intern (172.18.x) | Intern-Port | Zweck |
|---|---|---|---|---|
| Storage Host Helper | `storage-host-helper` | 172.18.0.8 | `8090/tcp` | Host-Operationen für Storage Broker (nur intern) |

> `storage-host-helper` hat kein Host-Binding — wird ausschließlich vom Stack intern aufgerufen.
> Port `8090` ist damit intern belegt und **nicht** als nächster freier Port verfügbar.

### Ollama (Host + Stack)

| Service | Container | Intern (172.18.x) | Host-Port | Zweck |
|---|---|---|---|---|
| Ollama | `ollama` | 172.18.0.14 | `11434/tcp` | LLM Inference — vom Stack und direkt vom Host erreichbar |

---

## TRION-verwaltete Container (Commander-deployed)

Im Docker-Default-Netz `bridge` (`172.17.0.0/16`) oder `trion-sandbox`.

### gaming-station

| Container | Netz | IP | Host-Ports |
|---|---|---|---|
| `trion_gaming-station_*` | bridge | 172.17.0.5 | siehe unten |

| Port | Protokoll | Zweck |
|---|---|---|
| `47984` | TCP | Sunshine RTSP (legacy) |
| `47989` | TCP | Sunshine HTTPS API (GFE-Kompatibilität) |
| `47990` | TCP | Sunshine HTTP WebUI — Moonlight-Pairing |
| `48010` | TCP | Sunshine RTSP (modern) |
| `47998` | UDP | Sunshine Video |
| `47999` | UDP | Sunshine Control |
| `48000` | UDP | Sunshine Audio |
| `48002` | UDP | Sunshine Mic |

**Historischer Zugang:** `https://<TRION_PUBLIC_HOST>:47990` (alter Container-`primary`-Pfad)
**Aktueller Modus:** Host-Bridge / `secondary` — Sunshine auf dem Host, Steam im Container

### trion-home (Sandbox)

| Container | Netz | IP | Host-Ports |
|---|---|---|---|
| `trion_trion-home_*` | trion-sandbox | 172.21.0.2 | — (kein Binding) |

---

## Nächste freie Ports

```
MCP-Bereich:    8084, 8091–8099  (8090 = storage-host-helper intern, belegt)
Adapter:        8101–8199
Runtime-Ports:  8420 aktiv belegt durch `runtime-hardware`
```

---

## Schnellreferenz: Alle TRION-Ports

| Port | Proto | Service | Host-gebunden | Kategorie |
|---|---|---|---|---|
| 8000 | TCP | Tool Executor | ja | Runtime |
| 8082 | TCP | SQL Memory MCP | ja | MCP |
| 8084 | — | — | — | **frei** |
| 8085 | TCP | Sequential Thinking MCP | ja | MCP |
| 8086 | TCP | CIM Server MCP | ja | MCP |
| 8087 | TCP | Document Processor MCP | ja | MCP |
| 8088 | TCP | Skill Server | ja | Runtime |
| 8089 | TCP | Storage Broker MCP | ja | MCP |
| 8090 | TCP | Storage Host Helper | nein (intern) | Intern |
| 8091–8099 | — | — | — | **frei** |
| 8100 | TCP | LobeChat Adapter | ja | Gateway |
| 8200 | TCP | Admin API | ja | API |
| 8300 | TCP | Validator Service | ja | Runtime |
| 8400 | TCP | Jarvis Web UI | ja | Frontend |
| 8401 | TCP | TRION Runtime | ja | Runtime |
| 8420 | TCP | Runtime Hardware API | aktiv | Runtime |
| 11434 | TCP | Ollama | ja | Inference |
| 47984 | TCP | Gaming Station — Sunshine RTSP | nein (historisch, gestoppt/archiviert) | Container |
| 47989 | TCP | Gaming Station — Sunshine HTTPS API | nein (historisch, gestoppt/archiviert) | Container |
| 47990 | TCP | Gaming Station — Sunshine WebUI | nein (historisch, gestoppt/archiviert) | Container |
| 48010 | TCP | Gaming Station — Sunshine RTSP | nein (historisch, gestoppt/archiviert) | Container |
| 47998 | UDP | Gaming Station — Sunshine Video | nein (historisch, gestoppt/archiviert) | Container |
| 47999 | UDP | Gaming Station — Sunshine Control | nein (historisch, gestoppt/archiviert) | Container |
| 48000 | UDP | Gaming Station — Sunshine Audio | nein (historisch, gestoppt/archiviert) | Container |
| 48002 | UDP | Gaming Station — Sunshine Mic | nein (historisch, gestoppt/archiviert) | Container |

**Hinweis `8083`:** Der fruehere `gaming-station`-Container exposed Port 8083 (Base-Image `josh5/steam-headless` hat ein `EXPOSE 8083` fuer noVNC eingebaut). Dieser Containerzweig ist inzwischen gestoppt und archiviert; der Port bleibt hier nur noch als historische Referenz erfasst.

**Hinweis `8420`:** Der Dienst `runtime-hardware` laeuft als eigener v0-Service und verwendet Host-Port `8420/tcp`. Die Doku fuehrt den Port deshalb jetzt als aktiv belegten Runtime-Port.

**Publish-Hinweis 2026-04-07:** Echte Host-/VPN-Adressen und direkte Host-URLs wurden fuer das oeffentliche Repo redigiert. Subnetz- und Service-Topologie bleiben absichtlich enthalten.
