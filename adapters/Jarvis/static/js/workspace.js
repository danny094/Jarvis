/**
 * workspace.js - Agent Workspace for TRION Side Panel
 *
 * Renders workspace entries (observations, tasks, notes) as Markdown cards.
 * Listens for SSE workspace_update events and supports CRUD via REST API.
 */

(function () {
    "use strict";

    const TAB_ID = "workspace";
    const TAB_TITLE = "Workspace";
    let initialized = false;
    let entries = []; // local cache

    // ═══════════════════════════════════════════════════════════
    // API BASE (same detection as api.js)
    // ═══════════════════════════════════════════════════════════

    function getApiBase() {
        if (window.location.port === "3000" || window.location.port === "80" || window.location.port === "") {
            return "";
        }
        return `http://${window.location.hostname}:8200`;
    }

    // ═══════════════════════════════════════════════════════════
    // REST API CALLS
    // ═══════════════════════════════════════════════════════════

    async function fetchEntries(conversationId) {
        const base = getApiBase();
        let url = `${base}/api/workspace?limit=50`;
        if (conversationId) url += `&conversation_id=${encodeURIComponent(conversationId)}`;
        try {
            const res = await fetch(url);
            const data = await res.json();
            // Handle structuredContent wrapper from MCP
            const raw = data.structuredContent || data;
            return raw.entries || [];
        } catch (e) {
            console.error("[Workspace] Fetch error:", e);
            return [];
        }
    }

    async function updateEntry(entryId, content) {
        const base = getApiBase();
        try {
            const res = await fetch(`${base}/api/workspace/${entryId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content })
            });
            return await res.json();
        } catch (e) {
            console.error("[Workspace] Update error:", e);
            return { updated: false };
        }
    }

    async function deleteEntry(entryId) {
        const base = getApiBase();
        try {
            const res = await fetch(`${base}/api/workspace/${entryId}`, { method: "DELETE" });
            return await res.json();
        } catch (e) {
            console.error("[Workspace] Delete error:", e);
            return { deleted: false };
        }
    }

    // ═══════════════════════════════════════════════════════════
    // RENDERING
    // ═══════════════════════════════════════════════════════════

    function renderMarkdown(text) {
        if (window.marked) {
            return marked.parse(text || "");
        }
        // Fallback: escape HTML and convert newlines
        const esc = (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        return esc.replace(/\n/g, "<br>");
    }

    function typeBadgeClass(entryType) {
        switch (entryType) {
            case "observation": return "ws-badge-observation";
            case "task": return "ws-badge-task";
            case "note": return "ws-badge-note";
            default: return "ws-badge-observation";
        }
    }

    function renderEntryCard(entry) {
        const card = document.createElement("div");
        card.className = "ws-card";
        card.setAttribute("data-entry-id", entry.id);

        const headerHtml = `
            <div class="ws-card-header">
                <span class="ws-badge ${typeBadgeClass(entry.entry_type)}">${entry.entry_type}</span>
                <span class="ws-card-layer">${entry.source_layer || ""}</span>
                <span class="ws-card-date">${formatDate(entry.created_at)}</span>
                <div class="ws-card-actions">
                    <button class="ws-btn-edit" title="Edit"><i data-lucide="pencil" class="w-3 h-3"></i></button>
                    <button class="ws-btn-delete" title="Delete"><i data-lucide="trash-2" class="w-3 h-3"></i></button>
                </div>
            </div>
        `;

        const bodyHtml = `
            <div class="ws-card-body">${renderMarkdown(entry.content)}</div>
        `;

        card.innerHTML = headerHtml + bodyHtml;

        // Edit handler
        card.querySelector(".ws-btn-edit").addEventListener("click", () => startEdit(card, entry));

        // Delete handler
        card.querySelector(".ws-btn-delete").addEventListener("click", async () => {
            if (!confirm("Delete this workspace entry?")) return;
            const result = await deleteEntry(entry.id);
            const r = result.structuredContent || result;
            if (r.deleted) {
                card.remove();
                entries = entries.filter(e => e.id !== entry.id);
                updateEmptyState();
            }
        });

        // Lucide icons
        if (window.lucide) lucide.createIcons({ nodes: [card] });

        return card;
    }

    function startEdit(card, entry) {
        const body = card.querySelector(".ws-card-body");
        const original = entry.content;

        body.innerHTML = `
            <textarea class="ws-edit-area">${escapeHtml(original)}</textarea>
            <div class="ws-edit-actions">
                <button class="ws-btn-save">Save</button>
                <button class="ws-btn-cancel">Cancel</button>
            </div>
        `;

        const textarea = body.querySelector(".ws-edit-area");
        textarea.focus();

        body.querySelector(".ws-btn-cancel").addEventListener("click", () => {
            body.innerHTML = renderMarkdown(original);
        });

        body.querySelector(".ws-btn-save").addEventListener("click", async () => {
            const newContent = textarea.value.trim();
            if (!newContent || newContent === original) {
                body.innerHTML = renderMarkdown(original);
                return;
            }
            const result = await updateEntry(entry.id, newContent);
            const r = result.structuredContent || result;
            if (r.updated) {
                entry.content = newContent;
                body.innerHTML = renderMarkdown(newContent);
            } else {
                body.innerHTML = renderMarkdown(original);
            }
        });
    }

    function formatDate(isoStr) {
        if (!isoStr) return "";
        try {
            const d = new Date(isoStr);
            return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) +
                " " + d.toLocaleDateString([], { day: "2-digit", month: "short" });
        } catch {
            return isoStr;
        }
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function updateEmptyState() {
        const container = getContainer();
        if (!container) return;
        const empty = container.querySelector(".ws-empty");
        if (entries.length === 0) {
            if (!empty) {
                const el = document.createElement("div");
                el.className = "ws-empty";
                el.innerHTML = '<p>No workspace entries yet.</p><small>The AI will add observations during conversations.</small>';
                container.appendChild(el);
            }
        } else if (empty) {
            empty.remove();
        }
    }

    // ═══════════════════════════════════════════════════════════
    // TAB + CONTAINER
    // ═══════════════════════════════════════════════════════════

    function getContainer() {
        if (!window.TRIONPanel) return null;
        const tab = window.TRIONPanel.tabs.get(TAB_ID);
        return tab ? tab.element : null;
    }

    function ensureTab() {
        if (!window.TRIONPanel) return;
        if (window.TRIONPanel.tabs.has(TAB_ID)) return;

        // Register custom renderer
        window.TRIONPanel.registerRenderer("workspace", {
            render: (content, container) => { /* managed manually */ },
            update: (content, container, append) => { /* managed manually */ },
            fileExtension: ".md"
        });

        window.TRIONPanel.createTab(TAB_ID, TAB_TITLE, "workspace", { autoOpen: false });

        const container = getContainer();
        if (container) {
            container.classList.add("ws-container");
            container.innerHTML = '<div class="ws-entries"></div>';
        }
    }

    async function loadEntries() {
        ensureTab();
        const container = getContainer();
        if (!container) {
            console.warn("[Workspace] loadEntries: no container found");
            return;
        }

        // Load all entries (no conversation filter for now)
        console.log("[Workspace] Loading entries...");
        entries = await fetchEntries(null);
        console.log(`[Workspace] Fetched ${entries.length} entries`);

        const list = container.querySelector(".ws-entries");
        if (list) {
            list.innerHTML = "";
            entries.forEach(entry => list.appendChild(renderEntryCard(entry)));
        }
        updateEmptyState();
    }

    // ═══════════════════════════════════════════════════════════
    // SSE EVENT HANDLER
    // ═══════════════════════════════════════════════════════════

    function handleWorkspaceUpdate(event) {
        const data = event.detail;
        if (!data || data.type !== "workspace_update") return;

        console.log("[Workspace] SSE workspace_update:", data);

        ensureTab();

        // Add to local cache
        const entry = {
            id: data.entry_id,
            conversation_id: data.conversation_id,
            content: data.content,
            entry_type: data.entry_type || "observation",
            source_layer: data.source_layer || "thinking",
            created_at: data.timestamp || new Date().toISOString(),
            updated_at: null,
            promoted: false,
            promoted_at: null
        };

        // Avoid duplicates
        if (entries.find(e => e.id === entry.id)) return;

        entries.unshift(entry);

        const container = getContainer();
        if (container) {
            const list = container.querySelector(".ws-entries");
            if (list) {
                const card = renderEntryCard(entry);
                list.prepend(card);
            }
            updateEmptyState();
        }

        // Open panel if closed and auto-open preference
        if (window.TRIONPanel && window.TRIONPanel.state === "closed") {
            window.TRIONPanel.open("half");
            window.TRIONPanel.switchTab(TAB_ID);
        }
    }

    // ═══════════════════════════════════════════════════════════
    // INITIALIZATION
    // ═══════════════════════════════════════════════════════════

    function init() {
        if (initialized) return;
        initialized = true;

        console.log("[Workspace] Initializing...");

        // Listen for SSE events
        window.addEventListener("sse-event", handleWorkspaceUpdate);

        // Create tab when TRIONPanel is ready
        function setupPanel() {
            if (!window.TRIONPanel) {
                console.warn("[Workspace] TRIONPanel not ready, retrying...");
                setTimeout(setupPanel, 500);
                return;
            }

            ensureTab();
            console.log("[Workspace] Tab created, registering tab-change listener");

            // Load entries when tab is activated
            window.TRIONPanel.on("tab-change", (data) => {
                if (data.id === TAB_ID) {
                    loadEntries();
                }
            });

            // Also pre-load entries so SSE events have context
            loadEntries();
        }

        setupPanel();
        console.log("[Workspace] Initialized");
    }

    // Auto-init when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        // Delay to ensure TRIONPanel is initialized first
        setTimeout(init, 300);
    }
})();
