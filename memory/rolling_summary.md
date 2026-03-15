## 2026-03-07

**Verified Facts**
- {'skill': 'current_weather', 'version': '1.0.0', 'installed_at': '2026-02-27T16:15:11.976312+00:00', 'description': 'Core weather lookup skill'}
- {'skill': 'system_hardware_info', 'version': '1.0.0', 'installed_at': '2026-02-27T16:15:11.976312+00:00', 'description': 'Core system diagnostics skill'}
- {'hardware': {'gpu': 'NVIDIA GeForce RTX 2060 SUPER', 'vram_total': '8192 MiB (8.0 GB)', 'gpu_load': '46.0%', 'cpu': 'Unbekannte CPU (12 Threads)', 'cpu_load': '1.0%', 'ram_total': '31.19 GB', 'ram_used': '5.31 GB', 'ram

**Open Tasks**
- Tool-Abfrage für 'TRION home container' und 'trion_trion-home_1772818315' wiederholen, falls weitere Details benötigt werden.

**Decisions**
- Keine weiteren verifizierten Entscheidungen basierend auf dem Verlauf getroffen.

**Important Context**
- TRION ist auf Basis der installierten Skills 'current_weather' und 'system_hardware_info' konfiguriert. Die Hardware umfasst eine NVIDIA GeForce RTX 2060 SUPER mit 8 GB VRAM und einer unbekannten CPU mit 12 Threads.

**Uncertain Claims**
- (leer)

## 2026-03-09

**Verified Facts**
- (leer)

**Open Tasks**
- (leer)

**Decisions**
- (leer)

**Important Context**
- (leer)

**Uncertain Claims**
- (leer)

## 2026-03-10

**Verified Facts**
- Prompt-Regression-Suite für Cron/Safety/Tagging erstellt: `tests/unit/test_prompt_policy_regression_suite.py`
- QueryBudget-Fix umgesetzt: ungetaggte Cron+Self-State-Prompts werden als `action` klassifiziert
- Relevante Regressionen grün: `41 passed`
- QueryBudget-Math-False-Block geschlossen: `T016` live rechecked (`approved=true`) nach ControlLayer-Fix für `_query_budget.skip_thinking_candidate`
- Creative-Drift + Reseed-Leak geschlossen:
  - DomainRouter Creative-Guard verhindert `GENERIC -> SKILL` Drift bei Gedicht/Poem-Prompts
  - Domain-Gate reseeded kein Skill-Tool mehr, wenn Skill-Gate schon blockiert
- Finaler Live-Recheck der Problem-IDs grün:
  - `T003 T013 T014 T015 T016 T021 T023 T024 T039 T042 T053 T076 T090`

**Open Tasks**
- Nächster sinnvoller Schritt: denselben Ziel-Subset als festen CI-Gate-Run automatisieren

**Decisions**
- Prompt-basierte Regressionen bleiben als feste Leitplanke für weitere Policy-Änderungen aktiv

**Important Context**
- Der gemeldete Erfolg wurde als stabile Grundlage für den nächsten Feinschliff gespeichert

**Uncertain Claims**
- (leer)
- 2026-03-10: Prompt/Policy-E2E-Abweichungen priorisiert (P0 Safety, P1 False-Blocks, P2 Domain-Routing); Fix-Reihenfolge festgelegt und sofortige Umsetzung vorbereitet.

## 2026-03-11

**Verified Facts**
- Plan für Cloud-Provider-Integration (Claude/ChatGPT/OpenAI/Anthropic) als morgiger Fokus gespeichert.
- Vorhandene technische Basis verifiziert:
  - Layer/Routing-Struktur (`thinking/control/output`, role endpoint resolver)
  - zentrale Model-Settings
  - Secret-Management für API-Keys
  - Adapter-Pattern für Frontends
- Hauptlücke verifiziert:
  - Core-LLM-Aufrufe sind derzeit Ollama-spezifisch; kein Runtime-Provider-Interface im Core.

**Open Tasks**
- Nächster Implementationsschritt: `LLMProvider`-Interface im Core einziehen und Ollama/OpenAI/Anthropic als Backends anbinden.

**Decisions**
- Fine-Tuning bleibt nachgelagert; zuerst Provider-/Policy-/Eval-Stabilität über Architektur und Tests absichern.

**Important Context**
- Der morgige Einstiegspunkt ist klar definiert und in `memory/2026-03-11.md` detailliert dokumentiert.

**Uncertain Claims**
- (leer)

- Prompt/Policy-Evals (mini) gegen `ministral-3:8b` und `deepseek-v3.1:671b` zeigen denselben Kern-Leak:
  - Shell-Connect + Skill/Create landet teils bei `confirmation_pending` statt `blocked`.
  - Danach kann Auto-Create an Komplexität scheitern (`Task too complex for auto-creation`).
- Ursache ist pipeline-/policy-seitig (modellunabhängig), nicht primär Modellgröße.

**Open Tasks**
- Komplexitäts-Eskalation implementieren:
  - `safe -> fast codegen -> deep codegen -> decompose`
  - kein harter Endabbruch nur wegen Komplexität.

**Decisions**
- Priorität verschoben: zuerst Autonomie-Flow stabilisieren (Komplexitätspfad), danach weitere Policy-Härtung.

- Auto-Repair gegen `Code validation failed` implementiert (bounded Retry mit sicherem Repair-Context).
- `mini_control_core` zwischen `skill-server` und `tool_executor` synchron gehalten; Sync-Contract grün.
- Relevante Gates grün:
  - `test_single_control_authority.py` (30 passed)
  - `test_mini_control_core_sync.py` + Sicherheitspfad-Tests (8 passed)
- Live-Runtime aktualisiert (Container sync + restart), damit der Fix sofort wirksam ist.


## 2026-03-11

**Verified Facts**
- (leer)

**Open Tasks**
- (leer)

**Decisions**
- (leer)

**Important Context**
- (leer)

**Uncertain Claims**
- (leer)
## 2026-03-12

**Verified Facts**
- `storage-broker` ist registriert und aktiv (`mcp_registry.py`), Tools in `/mcp/tools` sichtbar.
- Storage-Broker Runtime stabilisiert:
  - FastMCP-v3 kompatibler Start (`streamable-http`, `/mcp`)
  - Admin-Proxy auf MCP-Calls funktionsfähig
  - Endpunkte `/api/storage-broker/health|summary|disks|audit` liefern valide Antworten.
- Storage-UI verbessert:
  - Disk-Tree mit `>` (Platte/Partition)
  - Anzeige physische Platten vs Partitionen
  - Device-Policy-Editing über neues API `POST /api/storage-broker/disks/{disk_id}/policy`.
- MCP-Tools-UI-Feedback bereinigt (`Loaded X MCPs` nicht mehr persistent im Weg).

**Open Tasks**
- Systemdisk-Erkennung in Container-Kontext weiter härten, damit `system/blocked` deterministischer erkannt wird.
- Optional: Toggle „nur physische Platten“ im Disk-Tab ergänzen.

**Decisions**
- Storage-Broker bleibt als zentrale Governance-Schicht aktiv; Routing-Probleme werden über Intent/Tool-Priorisierung gelöst (nicht über erneute Registrierung).

**Important Context**
- Fehlverhalten bei Festplatten-Fragen entstand durch Tool-Selection/Intent-Mapping (Container-Tool priorisiert), obwohl Storage-Tools verfügbar waren.

**Uncertain Claims**
- (leer)

### Update 22:11

**Verified Facts**
- Storage-Broker UI auf GNOME-Disks-Layout umgestellt (links Device-Liste, rechts Tab-Details).
- Design wurde bewusst stabil gehalten; Feature-Ausbau erfolgt innerhalb dieses Layouts.
- Neue Actions integriert:
  - Rechte aendern (Zone/Policy Save)
  - Service-Pfad anlegen (Dry-Run/Apply)
  - Format/Mount Actions (Dry-Run/Apply)
  - Sicherheits-Tab mit Verschluesselungsstatus und klarem Hinweis auf fehlenden LUKS-Endpoint.

**Open Tasks**
- LUKS-/Encryption-Endpunkte im Storage-Broker Backend ergaenzen (sicherer Flow mit Dry-Run + Confirm).
- Managed-Path-Zuordnung zu Disks spaeter auf eindeutige Backend-Metadaten umstellen.


## 2026-03-12

**Verified Facts**
- Keine klar verifizierten Tool-Fakten im Zeitraum erkannt.

**Open Tasks**
- (leer)

**Decisions**
- (leer)

**Important Context**
- wie geht es dir?
- was weist du über deine server festplatten? Wie viele hast du?
- trion bist du da?
- Nutze storage_list_disks und sag mir weche Fespltatten dein server hat

**Uncertain Claims**
- Danke der Nachfrage! Als KI-Assistent habe ich zwar keine Gefühle im menschlichen Sinne, aber rein technisch läuft alles stabil – mein System ist bereit, dir zu helfen. 😊  
Wie geh
- Ich habe keine direkten Informationen über physische Server-Festplatten, da ich nur auf Container-Ebene Zugriff habe, nicht auf die zugrundeliegende Hardware. 

Was ich sehen kann:
- Ja, ich bin hier! 👋 Schön, von dir zu hören. Ich bin TRION, dein persönlicher KI-Assistent.

Da du neu hier bist, darf ich dich etwas kennenlernen? Wie heißt du eigentlich?
- Ich nutze das Tool, um die Festplatten deines Servers zu überprüfen.

[TOOL: storage_list_disks]

Basierend auf der Abfrage hat dein Server eine Festplatte:
- **sda** mit einer Grö

## 2026-03-13

**Verified Facts**
- (leer)

**Open Tasks**
- (leer)

**Decisions**
- (leer)

**Important Context**
- (leer)

**Uncertain Claims**
- (leer)

## 2026-03-14

**Verified Facts**
- (leer)

**Open Tasks**
- (leer)

**Decisions**
- (leer)

**Important Context**
- (leer)

**Uncertain Claims**
- (leer)