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
    const AUTONOMY_CACHE_KEY = "trion-autonomy-job-ids";
    const AUTONOMY_POLL_MS = 3000;
    let initialized = false;
    let entries = []; // local cache
    let lastPlanningReplayKey = null;
    let autonomyJobIds = [];
    let autonomyJobs = [];
    let autonomyRuntime = null;
    let autonomyStats = null;
    let autonomyPollTimer = null;

    function tryParseJson(value) {
        if (typeof value !== "string") return value;
        try {
            return JSON.parse(value);
        } catch {
            return value;
        }
    }

    function toText(value) {
        if (value === null || value === undefined) return "";
        if (typeof value === "string") return value;
        try {
            return JSON.stringify(value, null, 2);
        } catch {
            return String(value);
        }
    }

    function pickEventArray(payload) {
        if (Array.isArray(payload)) return payload;
        if (!payload || typeof payload !== "object") return [];
        if (Array.isArray(payload.events)) return payload.events;
        if (Array.isArray(payload.content)) return payload.content;
        const structured = payload.structuredContent;
        if (structured && typeof structured === "object" && Array.isArray(structured.events)) {
            return structured.events;
        }
        return [];
    }

    function summarizeEvent(eventType, eventData) {
        const data = (eventData && typeof eventData === "object") ? eventData : {};
        if (typeof data.content === "string" && data.content.trim()) return data.content;

        if (eventType === "tool_result") {
            const tool = data.tool_name || "tool";
            const status = data.status || "unknown";
            const facts = Array.isArray(data.key_facts) ? data.key_facts.slice(0, 2).join(" | ") : "";
            const base = `Tool ${tool}: ${status}`;
            return facts ? `${base}\n${facts}` : base;
        }

        if (eventType && eventType.startsWith("container_")) {
            const bp = data.blueprint_id || "container";
            const cid = data.container_id ? String(data.container_id).slice(0, 12) : "";
            const detail = data.purpose || data.command || data.reason || "";
            const head = cid ? `${bp}/${cid}` : bp;
            return detail ? `${head}: ${detail}` : head;
        }

        return toText(data.message || data.error || data.reason || data);
    }

    function normalizeWorkspaceEvent(raw) {
        if (!raw || typeof raw !== "object") return null;
        const eventDataRaw = raw.event_data !== undefined ? raw.event_data : raw.data;
        const eventData = tryParseJson(eventDataRaw);
        const eventType = raw.event_type || raw.entry_type || "event";
        const content = toText(raw.content || summarizeEvent(eventType, eventData));

        return {
            id: raw.id ?? raw.entry_id ?? `${eventType}-${raw.created_at || Date.now()}`,
            conversation_id: raw.conversation_id || eventData?.conversation_id || "",
            content,
            entry_type: eventType,
            source_layer: raw.source_layer || eventData?.source_layer || "orchestrator",
            created_at: raw.created_at || raw.timestamp || new Date().toISOString(),
            _source: "event",
        };
    }

    function replayPlanningWorkspaceEvents(conversationId, allEntries) {
        const replayKey = conversationId || "__global__";
        if (lastPlanningReplayKey === replayKey) return;
        lastPlanningReplayKey = replayKey;

        if (!Array.isArray(allEntries) || allEntries.length === 0) return;
        const planningEvents = allEntries
            .filter(item =>
                item &&
                item._source === "event" &&
                typeof item.entry_type === "string" &&
                /^planning_(start|step|done|error)$/.test(item.entry_type)
            )
            .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

        planningEvents.forEach((entry) => {
            const payload = {
                type: "workspace_update",
                source: "event",
                entry_id: entry.id,
                content: entry.content || "",
                entry_type: entry.entry_type,
                source_layer: entry.source_layer || "sequential",
                conversation_id: entry.conversation_id || conversationId || "",
                timestamp: entry.created_at || new Date().toISOString(),
                replay: true,
            };
            window.dispatchEvent(new CustomEvent("sse-event", { detail: payload }));
        });
    }

    // ═══════════════════════════════════════════════════════════
    // API BASE (same detection as api.js)
    // ═══════════════════════════════════════════════════════════

    function getApiBase() {
        if (typeof window.getApiBase === "function" && window.getApiBase !== getApiBase) {
            return window.getApiBase();
        }
        if (window.location.port === "3000" || window.location.port === "80" || window.location.port === "") {
            return "";
        }
        return `${window.location.protocol}//${window.location.hostname}:8200`;
    }

    function getActiveConversationId() {
        const current = String(window.currentConversationId || "").trim();
        if (current) return current;
        try {
            const stored = String(localStorage.getItem("jarvis-conversation-id") || "").trim();
            if (stored) {
                window.currentConversationId = stored;
                return stored;
            }
        } catch {
            // localStorage may be unavailable.
        }
        const generated = `webui-${Date.now()}`;
        window.currentConversationId = generated;
        try {
            localStorage.setItem("jarvis-conversation-id", generated);
        } catch {
            // Best-effort only.
        }
        return generated;
    }

    function loadAutonomyJobIds() {
        try {
            const raw = localStorage.getItem(AUTONOMY_CACHE_KEY);
            const parsed = raw ? JSON.parse(raw) : [];
            if (!Array.isArray(parsed)) return [];
            return parsed
                .map((id) => String(id || "").trim())
                .filter(Boolean)
                .slice(0, 20);
        } catch {
            return [];
        }
    }

    function saveAutonomyJobIds() {
        try {
            localStorage.setItem(AUTONOMY_CACHE_KEY, JSON.stringify(autonomyJobIds.slice(0, 20)));
        } catch {
            // Best-effort cache only.
        }
    }

    function trackAutonomyJobId(jobId) {
        const id = String(jobId || "").trim();
        if (!id) return;
        autonomyJobIds = [id, ...autonomyJobIds.filter((x) => x !== id)].slice(0, 20);
        saveAutonomyJobIds();
    }

    function upsertAutonomyJob(job) {
        if (!job || !job.job_id) return;
        const id = String(job.job_id);
        const idx = autonomyJobs.findIndex((j) => String(j.job_id) === id);
        if (idx >= 0) {
            autonomyJobs[idx] = { ...autonomyJobs[idx], ...job };
        } else {
            autonomyJobs.unshift(job);
        }
        autonomyJobs.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
        autonomyJobs = autonomyJobs.slice(0, 20);
        trackAutonomyJobId(id);
    }

    async function fetchAutonomyRuntime() {
        const base = getApiBase();
        const res = await fetch(`${base}/api/runtime/autonomy-status`);
        if (!res.ok) {
            throw new Error(`autonomy-status HTTP ${res.status}`);
        }
        return res.json();
    }

    async function fetchAutonomyJobStats() {
        const base = getApiBase();
        const res = await fetch(`${base}/api/autonomous/jobs-stats`);
        if (!res.ok) {
            throw new Error(`autonomy-jobs-stats HTTP ${res.status}`);
        }
        return res.json();
    }

    async function submitAutonomyJob(objective, conversationId, maxLoops) {
        const base = getApiBase();
        const resolvedConversationId = String(conversationId || "").trim() || getActiveConversationId();
        const body = {
            objective: String(objective || "").trim(),
            conversation_id: resolvedConversationId,
        };
        if (Number.isFinite(maxLoops) && maxLoops > 0) {
            body.max_loops = Math.floor(maxLoops);
        }
        const res = await fetch(`${base}/api/autonomous/jobs`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = payload?.error || payload?.error_code || `HTTP ${res.status}`;
            throw new Error(`Autonomy submit failed: ${msg}`);
        }
        return payload;
    }

    async function fetchAutonomyJob(jobId) {
        const id = String(jobId || "").trim();
        if (!id) throw new Error("missing_job_id");
        const base = getApiBase();
        const res = await fetch(`${base}/api/autonomous/jobs/${encodeURIComponent(id)}`);
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = payload?.error || `HTTP ${res.status}`;
            throw new Error(`Autonomy status failed: ${msg}`);
        }
        return payload;
    }

    async function cancelAutonomyJob(jobId) {
        const id = String(jobId || "").trim();
        if (!id) throw new Error("missing_job_id");
        const base = getApiBase();
        const res = await fetch(`${base}/api/autonomous/jobs/${encodeURIComponent(id)}/cancel`, {
            method: "POST",
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = payload?.error || `HTTP ${res.status}`;
            throw new Error(`Autonomy cancel failed: ${msg}`);
        }
        return payload;
    }

    async function retryAutonomyJob(jobId) {
        const id = String(jobId || "").trim();
        if (!id) throw new Error("missing_job_id");
        const base = getApiBase();
        const res = await fetch(`${base}/api/autonomous/jobs/${encodeURIComponent(id)}/retry`, {
            method: "POST",
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = payload?.error || payload?.error_code || `HTTP ${res.status}`;
            throw new Error(`Autonomy retry failed: ${msg}`);
        }
        return payload;
    }

    // ═══════════════════════════════════════════════════════════
    // REST API CALLS
    // ═══════════════════════════════════════════════════════════

    async function fetchEntries(conversationId) {
        const base = getApiBase();
        // Fetch editable entries (sql-memory workspace_entries)
        let entryUrl = `${base}/api/workspace?limit=50`;
        if (conversationId) entryUrl += `&conversation_id=${encodeURIComponent(conversationId)}`;

        // Fetch read-only events (Fast-Lane workspace_events) for reload persistence
        let eventUrl = `${base}/api/workspace-events?limit=50`;
        if (conversationId) eventUrl += `&conversation_id=${encodeURIComponent(conversationId)}`;

        try {
            const [entryResp, eventResp] = await Promise.allSettled([fetch(entryUrl), fetch(eventUrl)]);
            const entryRes = entryResp.status === "fulfilled" ? entryResp.value : null;
            const eventRes = eventResp.status === "fulfilled" ? eventResp.value : null;

            const entryData = entryRes ? await entryRes.json().catch(() => ({})) : {};
            const eventData = eventRes ? await eventRes.json().catch(() => ({})) : {};

            const entryList = Array.isArray(entryData.entries)
                ? entryData.entries.map(e => ({ ...e, _source: "entry" }))
                : [];
            const eventList = pickEventArray(eventData)
                .map(normalizeWorkspaceEvent)
                .filter(Boolean);

            // De-duplicate by source + id for mixed endpoint responses
            const dedup = new Map();
            [...entryList, ...eventList].forEach(item => {
                const key = `${item._source}:${item.id}`;
                if (!dedup.has(key)) dedup.set(key, item);
            });

            // Merge and sort newest-first
            return [...dedup.values()].sort(
                (a, b) => new Date(b.created_at) - new Date(a.created_at)
            );
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
        const raw = text || "";
        if (window.marked) {
            const html = marked.parse(raw);
            // Phase 6: use shared TRIONSanitize if loaded (sanitize.js)
            if (window.TRIONSanitize) {
                return window.TRIONSanitize.sanitizeHtml(html);
            }
            // Fallback: DOMPurify
            if (window.DOMPurify) {
                const clean = DOMPurify.sanitize(html);
                // Add rel=noopener to _blank links
                const tmp = document.createElement("div");
                tmp.innerHTML = clean;
                tmp.querySelectorAll("a[target='_blank']").forEach(a => {
                    a.setAttribute("rel", "noopener noreferrer");
                });
                return tmp.innerHTML;
            }
            // DOM-based fallback: strip dangerous tags/attrs + neutralise bad URLs
            const tmp = document.createElement("div");
            tmp.innerHTML = html;
            tmp.querySelectorAll("script,iframe,object,embed,style,form,base").forEach(el => el.remove());
            tmp.querySelectorAll("*").forEach(el => {
                const toRemove = [];
                [...el.attributes].forEach(attr => {
                    if (/^on/i.test(attr.name)) {
                        toRemove.push(attr.name);
                    } else if (/^(href|src|action|formaction|xlink:href)$/i.test(attr.name)) {
                        const val = (attr.value || "").trim().toLowerCase().replace(/\s/g, "");
                        if (val.startsWith("javascript:") || val.startsWith("vbscript:") || val.startsWith("data:text/html")) {
                            el.setAttribute(attr.name, "#");
                        }
                    }
                });
                toRemove.forEach(n => el.removeAttribute(n));
                // rel=noopener for external links
                if (el.tagName === "A" && el.getAttribute("target") === "_blank") {
                    el.setAttribute("rel", "noopener noreferrer");
                }
            });
            return tmp.innerHTML;
        }
        // Plain text fallback: escape HTML and convert newlines
        const esc = raw.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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

        const isReadOnly = entry._source === "event";
        const actionsHtml = isReadOnly ? "" : `
            <button class="ws-btn-edit" title="Edit"><i data-lucide="pencil" class="w-3 h-3"></i></button>
            <button class="ws-btn-delete" title="Delete"><i data-lucide="trash-2" class="w-3 h-3"></i></button>
        `;
        const headerHtml = `
            <div class="ws-card-header">
                <span class="ws-badge ${typeBadgeClass((entry.entry_type || entry.event_type))}">${(entry.entry_type || entry.event_type || "event")}</span>
                <span class="ws-card-layer">${entry.source_layer || ""}</span>
                <span class="ws-card-date">${formatDate(entry.created_at)}</span>
                <div class="ws-card-actions">${actionsHtml}</div>
            </div>
        `;

        const bodyHtml = `
            <div class="ws-card-body">${renderMarkdown(entry.content || "")}</div>
        `;

        card.innerHTML = headerHtml + bodyHtml;

        // Edit/Delete only for editable workspace_entries (not read-only events)
        if (!isReadOnly) {
            card.querySelector(".ws-btn-edit").addEventListener("click", () => startEdit(card, entry));
            card.querySelector(".ws-btn-delete").addEventListener("click", async () => {
                if (!confirm("Delete this workspace entry?")) return;
                const result = await deleteEntry(entry.id);
                if (result && result.deleted) {
                    card.remove();
                    entries = entries.filter(e => e.id !== entry.id);
                    updateEmptyState();
                }
            });
        }

        // Lucide icons
        if (window.lucide) lucide.createIcons({ nodes: [card] });

        return card;
    }

    function startEdit(card, entry) {
        const body = card.querySelector(".ws-card-body");
        // content lives in entry.content for workspace_entries (sql-memory)
        const original = entry.content || entry.event_data?.content || "";

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
            if (result && result.updated) {
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

    function autonomyStatusClass(status) {
        const s = String(status || "").toLowerCase();
        if (["succeeded", "connected", "ok", "ready"].includes(s)) return "ws-pill-ok";
        if (["failed", "offline", "error"].includes(s)) return "ws-pill-err";
        return "ws-pill-warn";
    }

    function renderAutonomyPanel(container) {
        if (!container) return;
        const panel = container.querySelector(".ws-autonomy");
        if (!panel) return;

        const runtime = autonomyRuntime || {};
        const stats = autonomyStats || {};
        const master = runtime.master || {};
        const tools = runtime.planning_tools || {};
        const home = runtime.home || {};
        const allReady = Boolean(tools.all_required_available) && home.status === "connected" && master.enabled !== false;
        const convId = getActiveConversationId();

        const jobsHtml = autonomyJobs.length
            ? autonomyJobs.slice(0, 10).map((job) => {
                const status = String(job.status || "unknown");
                const canCancel = ["queued", "running", "cancel_requested"].includes(status);
                const canRetry = ["failed", "cancelled"].includes(status);
                const detail = job.error_code || job.error || "";
                const when = formatDate(job.created_at || job.finished_at || "");
                return `
                    <div class="ws-autonomy-job">
                        <div class="ws-autonomy-job-head">
                            <span class="ws-pill ${autonomyStatusClass(status)}">${status}</span>
                            <span class="ws-autonomy-job-id">${String(job.job_id || "").slice(0, 12)}</span>
                            <span class="ws-autonomy-job-date">${when}</span>
                        </div>
                        <div class="ws-autonomy-job-meta">
                            <span>loops=${job.max_loops ?? "-"}</span>
                            <span>q=${job.queue_position ?? "-"}</span>
                            <span>run=${job.running_jobs ?? "-"}</span>
                            ${job.retry_of ? `<span>retry_of=${String(job.retry_of).slice(0, 12)}</span>` : ""}
                        </div>
                        ${detail ? `<div class="ws-autonomy-job-detail">${escapeHtml(String(detail))}</div>` : ""}
                        <div class="ws-autonomy-job-actions">
                            ${canCancel ? `<button data-autonomy-action="cancel" data-job-id="${job.job_id}">Cancel</button>` : ""}
                            ${canRetry ? `<button data-autonomy-action="retry" data-job-id="${job.job_id}">Retry</button>` : ""}
                        </div>
                    </div>
                `;
            }).join("")
            : '<div class="ws-autonomy-empty">No tracked autonomy jobs yet.</div>';

        panel.innerHTML = `
            <div class="ws-autonomy-head">
                <h3>Autonomy Control</h3>
                <button class="ws-autonomy-refresh" id="ws-autonomy-refresh">Refresh</button>
            </div>
            <div class="ws-autonomy-runtime">
                <span class="ws-pill ${autonomyStatusClass(allReady ? "ok" : "warn")}">${allReady ? "ready" : "degraded"}</span>
                <span>home=${home.status || "unknown"}</span>
                <span>tools=${tools.all_required_available ? "ok" : "missing"}</span>
                <span>master=${master.enabled ? "on" : "off"}</span>
                <span>queued=${stats.queued_jobs ?? "-"}</span>
                <span>running=${stats.running_jobs ?? "-"}</span>
            </div>
            <form class="ws-autonomy-form" id="ws-autonomy-form">
                <input
                    id="ws-autonomy-objective"
                    type="text"
                    maxlength="280"
                    placeholder="Autonomous objective for current conversation"
                    required
                />
                <input id="ws-autonomy-loops" type="number" min="1" max="50" step="1" value="${master.max_loops || 10}" />
                <button type="submit">Run</button>
            </form>
            <div class="ws-autonomy-context">conversation: <code>${escapeHtml(convId)}</code></div>
            <div class="ws-autonomy-jobs">${jobsHtml}</div>
        `;

        const refreshBtn = panel.querySelector("#ws-autonomy-refresh");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", async () => {
                await refreshAutonomyData(true);
            });
        }

        const form = panel.querySelector("#ws-autonomy-form");
        if (form) {
            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                const objectiveInput = panel.querySelector("#ws-autonomy-objective");
                const loopsInput = panel.querySelector("#ws-autonomy-loops");
                const objective = String(objectiveInput?.value || "").trim();
                const maxLoops = Number(loopsInput?.value || 0);
                if (!objective) return;

                try {
                    const submit = await submitAutonomyJob(objective, convId, maxLoops);
                    trackAutonomyJobId(submit.job_id);
                    if (objectiveInput) objectiveInput.value = "";
                    await refreshAutonomyData(true);
                } catch (err) {
                    console.warn("[Workspace] autonomy submit failed:", err);
                }
            });
        }

        panel.querySelectorAll("[data-autonomy-action]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const action = btn.getAttribute("data-autonomy-action");
                const jobId = btn.getAttribute("data-job-id");
                if (!jobId) return;
                try {
                    if (action === "cancel") {
                        const updated = await cancelAutonomyJob(jobId);
                        upsertAutonomyJob(updated);
                    } else if (action === "retry") {
                        const retried = await retryAutonomyJob(jobId);
                        trackAutonomyJobId(retried.job_id);
                    }
                    await refreshAutonomyData(true);
                } catch (err) {
                    console.warn(`[Workspace] autonomy ${action} failed:`, err);
                }
            });
        });
    }

    async function refreshAutonomyData(refreshJobs = false) {
        const container = getContainer();
        if (!container) return;

        const [runtimeRes, statsRes] = await Promise.allSettled([
            fetchAutonomyRuntime(),
            fetchAutonomyJobStats(),
        ]);
        if (runtimeRes.status === "fulfilled") autonomyRuntime = runtimeRes.value;
        if (statsRes.status === "fulfilled") autonomyStats = statsRes.value;

        if (refreshJobs) {
            const ids = [...new Set(autonomyJobIds)].slice(0, 20);
            const statuses = await Promise.allSettled(ids.map((id) => fetchAutonomyJob(id)));
            statuses.forEach((st) => {
                if (st.status === "fulfilled") {
                    upsertAutonomyJob(st.value);
                }
            });
            autonomyJobIds = autonomyJobs.map((job) => String(job.job_id || "")).filter(Boolean).slice(0, 20);
            saveAutonomyJobIds();
        }

        renderAutonomyPanel(container);
    }

    function startAutonomyPolling() {
        if (autonomyPollTimer) return;
        autonomyPollTimer = setInterval(() => {
            void refreshAutonomyData(true);
        }, AUTONOMY_POLL_MS);
    }

    function stopAutonomyPolling() {
        if (!autonomyPollTimer) return;
        clearInterval(autonomyPollTimer);
        autonomyPollTimer = null;
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
            container.innerHTML = `
                <section class="ws-autonomy"></section>
                <div class="ws-entries"></div>
            `;
        }
    }

    async function loadEntries() {
        ensureTab();
        const container = getContainer();
        if (!container) {
            console.warn("[Workspace] loadEntries: no container found");
            return;
        }

        // Filter by active conversation if available; fall back to global view.
        const convId = window.currentConversationId || null;
        console.log("[Workspace] Loading entries...", convId ? `conv=${convId}` : 'global');
        entries = await fetchEntries(convId);
        replayPlanningWorkspaceEvents(convId, entries);
        console.log(`[Workspace] Fetched ${entries.length} entries`);
        await refreshAutonomyData(true);

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

        // Normalize payload: both observation events and container events
        // share content + entry_type after Commit 2 normalization.
        // source="event" means read-only (no Edit/Delete in UI).
        const entry = {
            id: data.entry_id,
            conversation_id: data.conversation_id,
            content: toText(data.content || data.event_data?.content || ""),
            entry_type: data.entry_type || data.event_type || "observation",
            source_layer: data.source_layer || data.event_data?.source_layer || "orchestrator",
            created_at: data.timestamp || new Date().toISOString(),
            _source: data.source || "entry",  // "event" = read-only, "entry" = editable
        };

        // Keep panel scoped to the active chat conversation.
        const activeConv = window.currentConversationId || null;
        if (activeConv && entry.conversation_id !== activeConv) {
            return;
        }

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
        autonomyJobIds = loadAutonomyJobIds();

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
                    startAutonomyPolling();
                    loadEntries();
                } else {
                    stopAutonomyPolling();
                }
            });

            // Also pre-load entries so SSE events have context
            loadEntries();
            startAutonomyPolling();
        }

        setupPanel();
        window.addEventListener("beforeunload", stopAutonomyPolling);
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
