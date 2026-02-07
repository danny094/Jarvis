# TRION Frontend Apps Documentation

**Path:** `/DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/js/apps/`
**Version:** 3.0 (SPA Architecture)
**Last Updated:** 2026-02-07

## 1. Overview

This directory contains the **Single Page Application (SPA)** logic for the TRION Frontend. Each file represents a distinct "App" within the OS-like interface of Jarvis.

The frontend is built with **Vanilla JS (ES6 modules)** and uses **TailwindCSS** for styling. It communicates with the backend via REST APIs and WebSockets.

---

## 2. Modules (Apps)

### 2.1 Terminal (`terminal.js`)

The **Container Commander** interface.

* **Purpose:** Manage Docker containers and execute commands.
* **Key Features:**
  * **xterm.js Integration:** Full TTY terminal with colored output.
  * **WebSocket Stream:** Real-time bidirectional communication (`ws://.../api/commander/ws`).
  * **Tabs:** Switch between Blueprints, Active Containers, Vault (Secrets), and Logs.
  * **Confirmation Dialog:** Intercepts critical commands (like network access) for user approval.

### 2.2 Skills Studio (`skills.js`)

The **AI Skill Manager**.

* **Purpose:** Create, edit, and run AI Skills.
* **Key Features:**
  * **Monaco Editor:** Syntax-highlighted code editor for Python skills.
  * **Execution Panel:** Run skills directly and see output/logs.
  * **Skill Registry:** Browsable list of installed and draft skills.
  * **Approval Workflow:** Visualizes skills pending review (`_drafts`).

### 2.3 Tools Manager (`tools.js`)

The **MCP Hub Interface**.

* **Purpose:** Manage Model Context Protocol (MCP) servers.
* **Key Features:**
  * **Installer:** Install new MCPs via `uv pip install` or from ZIP upload.
  * **Registry View:** Shows all active tools available to the AI.
  * **Status Check:** Monitors health of connected MCP servers.

### 2.4 Settings (`settings.js`)

System Configuration (Ubuntu-style).

* **Purpose:** Configure the AI personality and system behavior.
* **Key Features:**
  * **Persona Editor:** Edit system prompts, personality traits, and user context.
  * **Model Selection:** Switch between models (e.g., DeepSeek, Qwen, Llama).
  * **Memory Management:** Wipe or view long-term memory.

### 2.5 Protocol (`protocol.js`)

The **Daily Log / Workspace**.

* **Purpose:** A chronological log of all AI activities and chats.
* **Key Features:**
  * **Daily Organization:** Tabs for each day.
  * **Merged View:** Combines Chat, Thoughts (Thinking Layer), and System Events into one timeline.
  * **Markdown Rendering:** Renders AI responses and code blocks.

### 2.6 Maintenance (`maintenance.js`)

System Health Monitor.

* **Purpose:** Visualizes internal system state.
* **Key Features:**
  * **Memory Params:** Displays Short-Term (STM), Medium-Term (MTM), and Long-Term (LTM) usage.
  * **Graph Stats:** Number of nodes and edges in the Knowledge Graph.
  * **Task Queue:** Shows pending background jobs.

---

## 3. Architecture Pattern

All apps follow a standardized lifecycle:

```javascript
// Init function exported for the main router (shell.js)
export function initAppName() {
    // 1. One-time setup
    if (initialized) return refresh();
    
    // 2. Render HTML Skeleton
    container.innerHTML = buildHTML();
    
    // 3. Bind Events (Buttons, Inputs)
    bindEvents();
    
    // 4. Connect Websockets (if needed)
    
    // 5. Load Initial Data
    loadData();
}
```

### Shared Utilities

* `../../static/js/api.js`: Wrapper for `fetch` with Error Handling.
* `../../static/js/debug.js`: Centralized logging.

---

## 4. Dependencies

* **xterm.js**: Terminal rendering (`terminal.js`).
* **Lucide Icons**: UI Icons (all apps).
* **TailwindCSS**: Utiltity-first styling (via CDN/static).
