/**
 * cron.js - Autonomy Cron Control App
 * Modern admin UI for user/TRION managed cron jobs.
 */

function getApiBase() {
    if (typeof window.getApiBase === "function") {
        return window.getApiBase();
    }
    if (window.location.port === "3000" || window.location.port === "80" || window.location.port === "") {
        return "";
    }
    return `${window.location.protocol}//${window.location.hostname}:8200`;
}

function esc(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
}

const state = {
    jobs: [],
    status: null,
    queue: { pending: [], running: [], recent: [] },
    filter: "all",
};

let refreshTimer = null;

function resolveConversationId(rawId = "") {
    const explicit = String(rawId || "").trim();
    if (explicit) return explicit;
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

async function fetchJson(path, options = {}) {
    const res = await fetch(`${getApiBase()}${path}`, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const err = data?.error || data?.error_code || `HTTP ${res.status}`;
        const ex = new Error(String(err));
        ex.code = data?.error_code || "";
        ex.details = data?.details || null;
        ex.status = res.status;
        throw ex;
    }
    return data;
}

function formatApiError(err) {
    const code = err?.code ? `[${err.code}] ` : "";
    const retryAfter = Number(err?.details?.retry_after_s || 0);
    if (retryAfter > 0) {
        return `${code}${err?.message || err} (retry in ${retryAfter}s)`;
    }
    return `${code}${err?.message || err}`;
}

function badgeClass(status) {
    const s = String(status || "").toLowerCase();
    if (["active", "running", "submitted", "succeeded"].includes(s)) return "cron-badge cron-badge-ok";
    if (["queued", "dispatching", "paused", "never"].includes(s)) return "cron-badge cron-badge-warn";
    return "cron-badge cron-badge-err";
}

function renderLayout(root) {
    root.innerHTML = `
        <div class="cron-app">
            <header class="cron-head">
                <h2><i data-lucide="calendar-clock"></i> Autonomy Cron</h2>
                <button id="cron-refresh-btn" class="cron-btn ghost"><i data-lucide="refresh-cw"></i> Refresh</button>
            </header>

            <section class="cron-grid-top">
                <article class="cron-card">
                    <h3>Create Cron Job</h3>
                    <form id="cron-create-form" class="cron-form">
                        <input id="cron-name" type="text" maxlength="120" placeholder="Job name" required />
                        <input id="cron-objective" type="text" maxlength="280" placeholder="Autonomous objective" required />
                        <textarea id="cron-job-note" rows="4" maxlength="6000" placeholder="Optional: Job note in Markdown (Job.md)"></textarea>
                        <div class="cron-row">
                            <input id="cron-expression" type="text" value="*/30 * * * *" placeholder="Cron (e.g. */30 * * * *)" required />
                            <input id="cron-timezone" type="text" value="UTC" placeholder="Timezone (UTC/Europe/Berlin)" />
                        </div>
                        <div class="cron-row">
                            <input id="cron-conversation" type="text" value="${esc(resolveConversationId(""))}" placeholder="Conversation ID" />
                            <input id="cron-max-loops" type="number" min="1" max="50" step="1" value="10" />
                        </div>
                        <div class="cron-row">
                            <select id="cron-created-by">
                                <option value="user">Created by user</option>
                                <option value="trion">Created by TRION</option>
                            </select>
                            <button type="submit" class="cron-btn primary"><i data-lucide="plus-circle"></i> Create</button>
                        </div>
                        <small class="cron-help">Cron format: <code>min hour day month weekday</code> (example: <code>0 4 * * *</code>)</small>
                        <div id="cron-policy-hints" class="cron-policy-hints"></div>
                    </form>
                </article>

                <article class="cron-card">
                    <h3>Scheduler Status</h3>
                    <div id="cron-kpis" class="cron-kpis"></div>
                </article>
            </section>

            <section class="cron-card">
                <div class="cron-section-head">
                    <h3>Jobs</h3>
                    <select id="cron-filter">
                        <option value="all">All</option>
                        <option value="active">Active</option>
                        <option value="paused">Paused</option>
                        <option value="queued">Queued/Running</option>
                    </select>
                </div>
                <div class="cron-table-wrap">
                    <table class="cron-table">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Cron</th>
                                <th>Status</th>
                                <th>Next run</th>
                                <th>Last result</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="cron-jobs-body"></tbody>
                    </table>
                </div>
            </section>

            <section class="cron-grid-bottom">
                <article class="cron-card">
                    <h3>Waiting Queue</h3>
                    <div id="cron-pending-list" class="cron-list"></div>
                </article>
                <article class="cron-card">
                    <h3>Running</h3>
                    <div id="cron-running-list" class="cron-list"></div>
                </article>
                <article class="cron-card">
                    <h3>Recent Dispatches</h3>
                    <div id="cron-recent-list" class="cron-list"></div>
                </article>
            </section>

            <footer id="cron-feedback" class="cron-feedback"></footer>
        </div>
    `;

    if (window.lucide) window.lucide.createIcons();
}

function setFeedback(msg, type = "info") {
    const el = document.getElementById("cron-feedback");
    if (!el) return;
    el.textContent = msg || "";
    el.className = `cron-feedback ${type}`;
}

function renderStatus() {
    const target = document.getElementById("cron-kpis");
    if (!target) return;
    const status = state.status || {};
    const scheduler = status.scheduler || {};
    const counts = status.counts || {};
    const policy = status.policy || {};

    target.innerHTML = `
        <div class="cron-kpi">
            <span>Scheduler</span>
            <strong class="${scheduler.running ? "ok" : "err"}">${scheduler.running ? "online" : "offline"}</strong>
        </div>
        <div class="cron-kpi"><span>Tick</span><strong>${esc(scheduler.tick_s ?? "-")}s</strong></div>
        <div class="cron-kpi"><span>Workers</span><strong>${esc(scheduler.max_concurrency ?? "-")}</strong></div>
        <div class="cron-kpi"><span>Active</span><strong>${esc(counts.jobs_active ?? 0)}</strong></div>
        <div class="cron-kpi"><span>Paused</span><strong>${esc(counts.jobs_paused ?? 0)}</strong></div>
        <div class="cron-kpi"><span>Queued</span><strong>${esc(counts.queued_runs ?? 0)}</strong></div>
        <div class="cron-kpi"><span>Running</span><strong>${esc(counts.running_runs ?? 0)}</strong></div>
    `;

    const hints = document.getElementById("cron-policy-hints");
    if (hints) {
        hints.innerHTML = `
            <small>
                Policy: min interval <strong>${esc(policy.min_interval_s ?? "-")}s</strong>,
                max jobs <strong>${esc(policy.max_jobs ?? "-")}</strong>,
                per conversation <strong>${esc(policy.max_jobs_per_conversation ?? "-")}</strong>,
                run-now cooldown <strong>${esc(policy.manual_run_cooldown_s ?? "-")}s</strong>.
            </small>
        `;
    }
}

function toLocal(iso) {
    if (!iso) return "-";
    try {
        const d = new Date(iso);
        return d.toLocaleString();
    } catch {
        return String(iso);
    }
}

function buildFallbackJobNoteMd(job) {
    const data = job || {};
    const name = String(data.name || "cron-job").trim() || "cron-job";
    const objective = String(data.objective || "No objective provided.").trim() || "No objective provided.";
    const scheduleMode = String(data.schedule_mode || "recurring").trim() || "recurring";
    const timezone = String(data.timezone || "UTC").trim() || "UTC";
    const createdBy = String(data.created_by || "user").trim() || "user";
    const conversationId = String(data.conversation_id || "-").trim() || "-";
    const maxLoops = Number(data.max_loops || 1) || 1;
    const lines = [
        `# Cron Job: ${name}`,
        "",
        "## Objective",
        objective,
        "",
        "## Schedule",
        `- Mode: \`${scheduleMode}\``,
    ];
    if (scheduleMode === "one_shot") {
        lines.push(`- Run at (UTC): \`${String(data.run_at || "-").trim() || "-"}\``);
    } else {
        lines.push(`- Cron: \`${String(data.cron || "-").trim() || "-"}\``);
    }
    lines.push(`- Timezone: \`${timezone}\``);
    lines.push("");
    lines.push("## Runtime");
    lines.push(`- Created by: \`${createdBy}\``);
    lines.push(`- Conversation: \`${conversationId}\``);
    lines.push(`- Max loops: \`${maxLoops}\``);
    return lines.join("\n");
}

function getJobNoteMd(job) {
    const note = String(job?.job_note_md || "").trim();
    if (note) return note;
    return buildFallbackJobNoteMd(job);
}

function renderJobs() {
    const body = document.getElementById("cron-jobs-body");
    if (!body) return;
    const filter = state.filter;

    const jobs = state.jobs.filter((job) => {
        const runtime = String(job.runtime_state || "");
        if (filter === "all") return true;
        if (filter === "active") return Boolean(job.enabled);
        if (filter === "paused") return !job.enabled;
        if (filter === "queued") return runtime === "queued" || runtime === "running";
        return true;
    });

    if (!jobs.length) {
        body.innerHTML = `<tr><td colspan="6" class="cron-empty">No cron jobs yet.</td></tr>`;
        return;
    }

    body.innerHTML = jobs.map((job) => {
        const runtimeState = String(job.runtime_state || (job.enabled ? "active" : "paused"));
        const status = job.enabled ? runtimeState : "paused";
        const last = job.last_status || "never";
        const pauseResumeLabel = job.enabled ? "Pause" : "Resume";
        const pauseResumeAction = job.enabled ? "pause" : "resume";
        const runNowBlocked = runtimeState === "queued" || runtimeState === "running";

        return `
            <tr>
                <td>
                    <div class="cron-name">${esc(job.name || "")}</div>
                    <small>${esc(job.created_by || "user")} · loops=${esc(job.max_loops ?? "-")}</small>
                    <details class="cron-job-md">
                        <summary>Job.md</summary>
                        <pre>${esc(getJobNoteMd(job))}</pre>
                    </details>
                </td>
                <td><code>${esc(job.cron || "")}</code><br><small>${esc(job.timezone || "UTC")}</small></td>
                <td><span class="${badgeClass(status)}">${esc(status)}</span></td>
                <td>${esc(toLocal(job.next_run_at || ""))}</td>
                <td>
                    <span class="${badgeClass(last)}">${esc(last)}</span>
                    ${job.last_error ? `<small class="cron-err-line">${esc(job.last_error)}</small>` : ""}
                </td>
                <td>
                    <div class="cron-actions">
                        <button data-action="run-now" data-id="${job.id}" class="cron-btn tiny" ${runNowBlocked ? "disabled" : ""}>Run now</button>
                        <button data-action="${pauseResumeAction}" data-id="${job.id}" class="cron-btn tiny">${pauseResumeLabel}</button>
                        <button data-action="delete" data-id="${job.id}" class="cron-btn tiny danger">Delete</button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
}

function renderQueue() {
    const pendingEl = document.getElementById("cron-pending-list");
    const runningEl = document.getElementById("cron-running-list");
    const recentEl = document.getElementById("cron-recent-list");
    if (!pendingEl || !runningEl || !recentEl) return;

    const queue = state.queue || { pending: [], running: [], recent: [] };

    const toItem = (item, fields) => `
        <div class="cron-list-item">
            ${fields.map((f) => `<div>${f}</div>`).join("")}
        </div>
    `;

    pendingEl.innerHTML = (queue.pending || []).length
        ? (queue.pending || []).slice(0, 20).map((item) => toItem(item, [
            `<strong>${esc(item.cron_job_id || "-")}</strong>`,
            `<span>reason=${esc(item.reason || "")}</span>`,
            `<small>${esc(toLocal(item.queued_at || ""))}</small>`,
        ])).join("")
        : `<div class="cron-list-empty">Queue is empty.</div>`;

    runningEl.innerHTML = (queue.running || []).length
        ? (queue.running || []).slice(0, 20).map((item) => toItem(item, [
            `<strong>${esc(item.cron_job_id || "-")}</strong>`,
            `<span>worker=${esc(item.worker ?? "-")}</span>`,
            `<small>${esc(toLocal(item.started_at || ""))}</small>`,
        ])).join("")
        : `<div class="cron-list-empty">Nothing running.</div>`;

    recentEl.innerHTML = (queue.recent || []).length
        ? (queue.recent || []).slice(-20).reverse().map((item) => toItem(item, [
            `<strong>${esc(item.cron_job_id || "-")}</strong>`,
            `<span class="${badgeClass(item.status || "")}">${esc(item.status || "")}</span>`,
            `<small>${esc(toLocal(item.finished_at || ""))}</small>`,
        ])).join("")
        : `<div class="cron-list-empty">No recent dispatches.</div>`;
}

async function refreshAll() {
    try {
        const [status, jobs, queue] = await Promise.all([
            fetchJson("/api/autonomy/cron/status"),
            fetchJson("/api/autonomy/cron/jobs"),
            fetchJson("/api/autonomy/cron/queue"),
        ]);
        state.status = status;
        state.jobs = Array.isArray(jobs?.jobs) ? jobs.jobs : [];
        state.queue = queue || { pending: [], running: [], recent: [] };
        renderStatus();
        renderJobs();
        renderQueue();
        setFeedback(`Updated ${new Date().toLocaleTimeString()}`, "ok");
    } catch (err) {
        console.error("[CronApp] refresh failed:", err);
        setFeedback(`Refresh failed: ${err.message || err}`, "err");
    }
}

async function onCreateSubmit(event) {
    event.preventDefault();
    const name = document.getElementById("cron-name")?.value?.trim() || "";
    const objective = document.getElementById("cron-objective")?.value?.trim() || "";
    const cron = document.getElementById("cron-expression")?.value?.trim() || "";
    const timezone = document.getElementById("cron-timezone")?.value?.trim() || "UTC";
    const conversationId = resolveConversationId(document.getElementById("cron-conversation")?.value?.trim() || "");
    const maxLoops = Number(document.getElementById("cron-max-loops")?.value || 10);
    const createdBy = document.getElementById("cron-created-by")?.value || "user";
    const jobNoteMd = document.getElementById("cron-job-note")?.value?.trim() || "";

    if (!name || !objective || !cron) {
        setFeedback("Name, objective and cron expression are required.", "err");
        return;
    }

    try {
        const createPayload = {
            name,
            objective,
            cron,
            timezone,
            conversation_id: conversationId,
            max_loops: maxLoops,
            created_by: createdBy,
            enabled: true,
        };
        if (jobNoteMd) createPayload.job_note_md = jobNoteMd;

        await fetchJson("/api/autonomy/cron/jobs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(createPayload),
        });
        (document.getElementById("cron-create-form"))?.reset();
        const tzInput = document.getElementById("cron-timezone");
        const convInput = document.getElementById("cron-conversation");
        const loopsInput = document.getElementById("cron-max-loops");
        if (tzInput) tzInput.value = "UTC";
        if (convInput) convInput.value = resolveConversationId("");
        if (loopsInput) loopsInput.value = "10";
        await refreshAll();
        setFeedback("Cron job created.", "ok");
    } catch (err) {
        setFeedback(`Create failed: ${formatApiError(err)}`, "err");
    }
}

async function onJobsAction(event) {
    const btn = event.target.closest("button[data-action][data-id]");
    if (!btn) return;
    const action = btn.getAttribute("data-action");
    const id = btn.getAttribute("data-id");
    if (!action || !id) return;

    try {
        if (action === "run-now") {
            await fetchJson(`/api/autonomy/cron/jobs/${encodeURIComponent(id)}/run-now`, { method: "POST" });
        } else if (action === "pause") {
            await fetchJson(`/api/autonomy/cron/jobs/${encodeURIComponent(id)}/pause`, { method: "POST" });
        } else if (action === "resume") {
            await fetchJson(`/api/autonomy/cron/jobs/${encodeURIComponent(id)}/resume`, { method: "POST" });
        } else if (action === "delete") {
            if (!confirm("Delete this cron job?")) return;
            await fetchJson(`/api/autonomy/cron/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
        }
        await refreshAll();
    } catch (err) {
        setFeedback(`Action failed: ${formatApiError(err)}`, "err");
    }
}

function bindEvents(root) {
    root.querySelector("#cron-refresh-btn")?.addEventListener("click", () => {
        void refreshAll();
    });
    root.querySelector("#cron-create-form")?.addEventListener("submit", onCreateSubmit);
    root.querySelector("#cron-jobs-body")?.addEventListener("click", onJobsAction);
    root.querySelector("#cron-filter")?.addEventListener("change", (e) => {
        state.filter = e.target.value || "all";
        renderJobs();
    });
}

export async function initCronApp() {
    const root = document.getElementById("app-cron");
    if (!root) return;

    if (!root.dataset.cronInit) {
        renderLayout(root);
        bindEvents(root);
        root.dataset.cronInit = "1";
    }

    await refreshAll();

    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
        void refreshAll();
    }, 5000);
}
