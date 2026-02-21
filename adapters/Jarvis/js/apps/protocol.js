/**
 * protocol.js - Daily Protocol (Agenten Arbeitsbereich)
 * Launchpad full-page app for viewing/editing daily conversation logs.
 */

// Dynamic base — avoids hardcoded :8200; falls back identically to api.js logic.
function _protocolBase() {
    const h = typeof window.getApiBase === 'function' ? window.getApiBase()
        : (window.location.port === '3000' || window.location.port === '80' || window.location.port === ''
            ? '' : `${window.location.protocol}//${window.location.hostname}:8200`);
    return `${h}/api/protocol`;
}

let currentDate = null;
let dates = [];
let entries = [];
let isMerged = false;
let initialized = false;

// ═══════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════

export function initProtocolApp() {
    if (initialized) {
        loadDates();
        return;
    }
    initialized = true;

    const container = document.getElementById("app-protocol");
    if (!container) return;

    container.innerHTML = buildHTML();
    bindEvents();
    loadDates();
}

function buildHTML() {
    return `
    <div class="proto-container">
        <!-- Header -->
        <div class="proto-header">
            <h2>
                <span class="proto-icon">&#128214;</span>
                Agenten Arbeitsbereich
            </h2>
            <button class="proto-refresh-btn" id="proto-refresh">
                <i data-lucide="refresh-cw" class="w-4 h-4"></i>
                Refresh
            </button>
        </div>

        <!-- Date Tabs -->
        <div class="proto-tabs" id="proto-tabs"></div>

        <!-- Entries -->
        <div class="proto-entries" id="proto-entries">
            <div class="proto-empty">
                <p>Keine Eintr&auml;ge</p>
                <small>Starte einen Chat um Eintr&auml;ge zu generieren</small>
            </div>
        </div>

        <!-- Add Entry Form (hidden by default) -->
        <div class="proto-add-form" id="proto-add-form">
            <label>User Nachricht</label>
            <textarea id="proto-add-user" placeholder="Was hast du gefragt?"></textarea>
            <label>Jarvis Antwort</label>
            <textarea id="proto-add-ai" placeholder="Was hat Jarvis geantwortet?"></textarea>
            <div class="proto-edit-actions">
                <button class="proto-btn-cancel" id="proto-add-cancel">Abbrechen</button>
                <button class="proto-btn-save" id="proto-add-save">Hinzuf&uuml;gen</button>
            </div>
        </div>

        <!-- Footer -->
        <div class="proto-footer">
            <div class="proto-footer-left">
                <button class="proto-add-btn" id="proto-add-trigger">
                    + Eintrag hinzuf&uuml;gen
                </button>
                <span class="proto-status" id="proto-status"></span>
            </div>
            <button class="proto-merge-btn" id="proto-merge-btn" disabled>
                &#128256; Merge to Maintenance
            </button>
        </div>
    </div>`;
}

function bindEvents() {
    document.getElementById("proto-refresh")?.addEventListener("click", () => loadDates());

    document.getElementById("proto-add-trigger")?.addEventListener("click", () => {
        const form = document.getElementById("proto-add-form");
        form.classList.toggle("visible");
    });

    document.getElementById("proto-add-cancel")?.addEventListener("click", () => {
        document.getElementById("proto-add-form").classList.remove("visible");
    });

    document.getElementById("proto-add-save")?.addEventListener("click", addEntry);
    document.getElementById("proto-merge-btn")?.addEventListener("click", mergeToGraph);

    // Re-render lucide icons
    if (window.lucide) lucide.createIcons();
}

// ═══════════════════════════════════════════════════════════
// DATA LOADING
// ═══════════════════════════════════════════════════════════

async function loadDates() {
    try {
        const resp = await fetch(`${_protocolBase()}/list`);
        const data = await resp.json();
        dates = data.dates || [];

        renderTabs();

        // Select today or first available
        const today = new Date().toISOString().slice(0, 10);
        const hasToday = dates.some(d => d.date === today);

        if (hasToday) {
            selectDate(today);
        } else if (dates.length > 0) {
            selectDate(dates[0].date);
        } else {
            currentDate = today;
            entries = [];
            renderEntries();
        }

        updateBadge(data.unmerged_count || 0);
    } catch (err) {
        console.error("[Protocol] Failed to load dates:", err);
    }
}

async function selectDate(date) {
    currentDate = date;

    // Update tab UI
    document.querySelectorAll(".proto-tab").forEach(tab => {
        tab.classList.toggle("active", tab.dataset.date === date);
    });

    try {
        const resp = await fetch(`${_protocolBase()}/${date}`);
        const data = await resp.json();
        entries = data.entries || [];
        isMerged = data.merged || false;
        renderEntries();
        updateMergeButton();
    } catch (err) {
        console.error("[Protocol] Failed to load date:", err);
    }
}

// ═══════════════════════════════════════════════════════════
// RENDERING
// ═══════════════════════════════════════════════════════════

function renderTabs() {
    const container = document.getElementById("proto-tabs");
    if (!container) return;

    const today = new Date().toISOString().slice(0, 10);

    container.innerHTML = dates.map(d => {
        const label = d.date === today ? "Heute" : formatDateShort(d.date);
        const dot = (!d.merged && d.entry_count > 0) ? '<span class="proto-dot"></span>' : "";
        const active = d.date === currentDate ? "active" : "";
        return `<button class="proto-tab ${active}" data-date="${d.date}">${label}${dot}</button>`;
    }).join("");

    // If today not in list, add it
    if (!dates.some(d => d.date === today)) {
        container.insertAdjacentHTML("afterbegin",
            `<button class="proto-tab ${currentDate === today ? 'active' : ''}" data-date="${today}">Heute</button>`
        );
    }

    container.querySelectorAll(".proto-tab").forEach(tab => {
        tab.addEventListener("click", () => selectDate(tab.dataset.date));
    });
}

function renderEntries() {
    const container = document.getElementById("proto-entries");
    if (!container) return;

    if (!entries.length) {
        container.innerHTML = `
            <div class="proto-empty">
                <p>Keine Eintr&auml;ge f&uuml;r ${currentDate}</p>
                <small>Starte einen Chat um Eintr&auml;ge zu generieren</small>
            </div>`;
        return;
    }

    container.innerHTML = entries.map((entry, idx) => {
        const timeMatch = entry.match(/^## (\d{2}:\d{2})/);
        const timeStr = timeMatch ? timeMatch[1] : "??:??";

        // Render entry body as markdown (everything after the ## HH:MM line)
        const bodyMd = entry.replace(/^## \d{2}:\d{2}\s*/, "").replace(/\s*---\s*$/, "").trim();
        const bodyHtml = sanitizeHtml(window.marked ? marked.parse(bodyMd) : escapeHtml(bodyMd));

        return `
        <div class="proto-entry" data-index="${idx}">
            <div class="proto-entry-header">
                <span class="proto-entry-time">${timeStr}</span>
                <div class="proto-entry-actions">
                    <button class="proto-btn-edit" data-index="${idx}" title="Bearbeiten">&#9998;</button>
                    <button class="proto-btn-delete" data-index="${idx}" title="L&ouml;schen">&#128465;</button>
                </div>
            </div>
            <div class="proto-entry-body" id="proto-body-${idx}">${bodyHtml}</div>
        </div>`;
    }).join("");

    // Bind edit/delete
    container.querySelectorAll(".proto-btn-edit").forEach(btn => {
        btn.addEventListener("click", () => editEntry(parseInt(btn.dataset.index)));
    });

    container.querySelectorAll(".proto-btn-delete").forEach(btn => {
        btn.addEventListener("click", () => deleteEntry(parseInt(btn.dataset.index)));
    });
}

function updateMergeButton() {
    const btn = document.getElementById("proto-merge-btn");
    if (!btn) return;

    if (isMerged || !entries.length) {
        btn.disabled = true;
        btn.innerHTML = isMerged
            ? "&#10003; Bereits gemerged"
            : "&#128256; Merge to Maintenance";
    } else {
        btn.disabled = false;
        btn.innerHTML = "&#128256; Merge to Maintenance";
    }
}

function updateStatus(text) {
    const el = document.getElementById("proto-status");
    if (el) el.textContent = text;
}

// ═══════════════════════════════════════════════════════════
// ACTIONS
// ═══════════════════════════════════════════════════════════

async function addEntry() {
    const userEl = document.getElementById("proto-add-user");
    const aiEl = document.getElementById("proto-add-ai");
    const userMsg = userEl?.value.trim();
    const aiMsg = aiEl?.value.trim();

    if (!userMsg || !aiMsg) return;

    try {
        const resp = await fetch(`${_protocolBase()}/append`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_message: userMsg,
                ai_response: aiMsg,
                timestamp: new Date().toISOString(),
                // Manual entry: no active chat session — send null so backend logs correctly
                conversation_id: null,
                session_id: null,
            })
        });

        if (resp.ok) {
            userEl.value = "";
            aiEl.value = "";
            document.getElementById("proto-add-form").classList.remove("visible");
            loadDates();
            updateStatus("Eintrag hinzugefuegt");
        }
    } catch (err) {
        console.error("[Protocol] Add failed:", err);
    }
}

function editEntry(index) {
    const bodyEl = document.getElementById(`proto-body-${index}`);
    if (!bodyEl) return;

    const rawEntry = entries[index];
    const bodyText = rawEntry.replace(/^## \d{2}:\d{2}\s*/, "").replace(/\s*---\s*$/, "").trim();

    // Build cancel button safely (no inline event handler with untrusted content)
    bodyEl.innerHTML = `
        <textarea class="proto-edit-area">${escapeHtml(bodyText)}</textarea>
        <div class="proto-edit-actions">
            <button class="proto-btn-cancel">Abbrechen</button>
            <button class="proto-btn-save proto-save-edit" data-index="${index}">Speichern</button>
        </div>`;
    bodyEl.querySelector(".proto-btn-cancel").addEventListener("click", () => {
        bodyEl.innerHTML = sanitizeHtml(window.marked ? marked.parse(bodyText) : escapeHtml(bodyText));
    });

    bodyEl.querySelector(".proto-save-edit")?.addEventListener("click", async () => {
        const textarea = bodyEl.querySelector(".proto-edit-area");
        const newBody = textarea.value.trim();
        if (!newBody) return;

        // Reconstruct the entry with time header
        const timeMatch = rawEntry.match(/^## (\d{2}:\d{2})/);
        const timeStr = timeMatch ? timeMatch[1] : "00:00";
        entries[index] = `## ${timeStr}\n${newBody}\n\n---`;

        // Save full content
        const fullContent = `# Tagesprotokoll ${currentDate}\n\n${entries.join("\n\n")}\n`;

        try {
            const resp = await fetch(`${_protocolBase()}/${currentDate}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content: fullContent })
            });

            if (resp.ok) {
                selectDate(currentDate);
                updateStatus("Eintrag aktualisiert");
            }
        } catch (err) {
            console.error("[Protocol] Edit failed:", err);
        }
    });
}

async function deleteEntry(index) {
    if (!confirm(`Eintrag ${index + 1} wirklich loeschen?`)) return;

    try {
        const resp = await fetch(`${_protocolBase()}/${currentDate}/entry/${index}`, {
            method: "DELETE"
        });

        if (resp.ok) {
            loadDates();
            updateStatus("Eintrag geloescht");
        }
    } catch (err) {
        console.error("[Protocol] Delete failed:", err);
    }
}

async function mergeToGraph() {
    const btn = document.getElementById("proto-merge-btn");
    if (!btn || btn.disabled) return;

    btn.disabled = true;
    btn.innerHTML = "Merging...";
    updateStatus("Merge laeuft...");

    try {
        const resp = await fetch(`${_protocolBase()}/${currentDate}/merge`, {
            method: "POST"
        });
        const data = await resp.json();

        if (data.merged) {
            isMerged = true;
            updateMergeButton();
            updateStatus(`${data.entries_merged} Eintraege gemerged`);
            loadDates();  // Refresh tabs (remove red dots)
        } else {
            updateStatus(`Merge Fehler: ${data.error || "Unbekannt"}`);
            btn.disabled = false;
            btn.innerHTML = "&#128256; Merge to Maintenance";
        }
    } catch (err) {
        console.error("[Protocol] Merge failed:", err);
        updateStatus("Merge fehlgeschlagen");
        btn.disabled = false;
        btn.innerHTML = "&#128256; Merge to Maintenance";
    }
}

// ═══════════════════════════════════════════════════════════
// BADGE (called from shell.js)
// ═══════════════════════════════════════════════════════════

export function updateBadge(count) {
    const badge = document.getElementById("proto-badge");
    if (badge) {
        if (count > 0) {
            badge.textContent = count;
            badge.classList.remove("hidden");
        } else {
            badge.classList.add("hidden");
        }
    }

    // Also update sidebar badge
    const sidebarBadge = document.getElementById("proto-sidebar-badge");
    if (sidebarBadge) {
        if (count > 0) {
            sidebarBadge.textContent = count;
            sidebarBadge.classList.remove("hidden");
        } else {
            sidebarBadge.classList.add("hidden");
        }
    }
}

export async function pollUnmergedCount() {
    try {
        const resp = await fetch(`${_protocolBase()}/unmerged-count`);
        const data = await resp.json();
        updateBadge(data.unmerged_count || 0);
    } catch {
        // silent
    }
}

// ═══════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════

function formatDateShort(dateStr) {
    const [y, m, d] = dateStr.split("-");
    return `${d}.${m}`;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Phase 6: Sanitize HTML from marked.parse() output.
 * Uses window.TRIONSanitize (sanitize.js) if available, else DOM fallback.
 */
function sanitizeHtml(html) {
    if (!html) return "";
    // Prefer shared sanitizer (sanitize.js loaded as script-tag)
    if (window.TRIONSanitize) return window.TRIONSanitize.sanitizeHtml(html);
    // DOMPurify fallback
    if (window.DOMPurify) {
        const clean = window.DOMPurify.sanitize(html);
        const tmp = document.createElement("div");
        tmp.innerHTML = clean;
        tmp.querySelectorAll("a[target='_blank']").forEach(a => {
            a.setAttribute("rel", "noopener noreferrer");
        });
        return tmp.innerHTML;
    }
    // DOM-based fallback
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    tmp.querySelectorAll("script,iframe,object,embed,style,form,base").forEach(el => el.remove());
    tmp.querySelectorAll("*").forEach(el => {
        const toRemove = [];
        for (const attr of el.attributes) {
            if (/^on/i.test(attr.name)) {
                toRemove.push(attr.name);
            } else if (/^(href|src|action|formaction|xlink:href)$/i.test(attr.name)) {
                const val = (attr.value || "").replace(/\s/g, "").toLowerCase();
                if (/^(javascript:|vbscript:|data:text\/html)/.test(val)) {
                    el.setAttribute(attr.name, "#");
                }
            }
        }
        toRemove.forEach(n => el.removeAttribute(n));
        if (el.tagName === "A" && el.getAttribute("target") === "_blank") {
            el.setAttribute("rel", "noopener noreferrer");
        }
    });
    return tmp.innerHTML;
}
