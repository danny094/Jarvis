/**
 * session.js - Session Insights Dashboard
 */

function getApiBase() {
    if (typeof window.getApiBase === "function" && window.getApiBase !== getApiBase) {
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

function fmtInt(value) {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return "0";
    return Math.round(n).toLocaleString();
}

function fmtMaybeInt(value) {
    if (value === null || value === undefined || value === "") return "-";
    return fmtInt(value);
}

function fmtFloat(value, digits = 2) {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return "0";
    return n.toFixed(digits);
}

function fmtMs(value) {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return "0 ms";
    if (n >= 1000) return `${(n / 1000).toFixed(2)} s`;
    return `${n.toFixed(0)} ms`;
}

function fmtTime(value) {
    if (!value) return "-";
    try {
        return new Date(value).toLocaleTimeString();
    } catch {
        return String(value);
    }
}

function ratioPercent(ratio) {
    const n = Number(ratio);
    if (!Number.isFinite(n)) return null;
    return Math.max(0, Math.min(100, n * 100));
}

const state = {
    payload: null,
    instances: null,
};

let refreshTimer = null;

async function fetchJson(path) {
    const res = await fetch(`${getApiBase()}${path}`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const msg = data?.error || data?.detail || `HTTP ${res.status}`;
        throw new Error(String(msg));
    }
    return data;
}

function renderLayout(root) {
    root.innerHTML = `
        <div class="session-app">
            <header class="session-head">
                <h2><i data-lucide="activity"></i> Session Insights</h2>
                <div class="session-actions">
                    <button id="session-refresh-btn" class="session-btn"><i data-lucide="refresh-cw"></i> Refresh</button>
                    <button id="session-autorefresh-btn" class="session-btn primary">Auto: on</button>
                </div>
            </header>

            <section class="session-grid-top">
                <article class="session-card">
                    <h3>Session KPIs</h3>
                    <div id="session-kpis" class="session-kpis"></div>
                </article>
                <article class="session-card">
                    <h3>Cloud Budgets / Rate Limits</h3>
                    <div id="session-cloud" class="session-list"></div>
                </article>
            </section>

            <section class="session-grid-mid">
                <article class="session-card">
                    <h3>Provider Mix</h3>
                    <div id="session-providers" class="session-list"></div>
                </article>
                <article class="session-card">
                    <h3>Model Mix</h3>
                    <div id="session-models" class="session-list"></div>
                </article>
            </section>

            <section class="session-grid-bottom">
                <article class="session-card">
                    <h3>Status & Errors</h3>
                    <div id="session-status" class="session-mini-grid"></div>
                </article>
                <article class="session-card">
                    <h3>Local Runtime (Ollama)</h3>
                    <div id="session-local" class="session-list"></div>
                </article>
            </section>

            <footer id="session-feedback" class="session-feedback"></footer>
        </div>
    `;
    if (window.lucide) window.lucide.createIcons();
}

function setFeedback(msg, type = "ok") {
    const el = document.getElementById("session-feedback");
    if (!el) return;
    el.textContent = msg || "";
    el.className = `session-feedback ${type}`;
}

function renderKpis() {
    const target = document.getElementById("session-kpis");
    if (!target) return;
    const s = state.payload?.session || {};
    target.innerHTML = `
        <div class="session-kpi"><span>Requests</span><strong>${esc(fmtInt(s.requests_total))}</strong></div>
        <div class="session-kpi"><span>Tokens est.</span><strong>${esc(fmtInt(s.tokens_total_est))}</strong></div>
        <div class="session-kpi"><span>Avg Tokens/Req</span><strong>${esc(fmtFloat(s.avg_tokens_per_request_est, 1))}</strong></div>
        <div class="session-kpi"><span>Tokens/min</span><strong>${esc(fmtFloat(s.tokens_per_min_est, 1))}</strong></div>
        <div class="session-kpi"><span>Avg Latency</span><strong>${esc(fmtMs(s.avg_latency_ms))}</strong></div>
        <div class="session-kpi"><span>P95 Latency</span><strong>${esc(fmtMs(s.p95_latency_ms))}</strong></div>
        <div class="session-kpi"><span>Last Request</span><strong>${esc(fmtTime(s.last_request_at))}</strong></div>
        <div class="session-kpi"><span>Last Error</span><strong>${esc(fmtTime(s.last_error_at))}</strong></div>
    `;
}

function renderCloudBudget() {
    const target = document.getElementById("session-cloud");
    if (!target) return;
    const cloud = state.payload?.cloud_budget || {};
    const providers = ["openai", "anthropic", "ollama_cloud"];
    const cards = providers.map((provider) => {
        const item = cloud[provider] || {};
        const req = item.requests || {};
        const tok = item.tokens || {};
        const observed = item.observed || {};
        const hasLimitHeaders = Boolean(item.has_limit_headers);
        const reqPct = ratioPercent(req.used_ratio);
        const tokPct = ratioPercent(tok.used_ratio);
        const hasSignal = reqPct !== null || tokPct !== null || item.updated_at || item.status_code;
        if (!hasSignal) {
            return `
                <div class="session-item">
                    <div class="session-item-head">
                        <strong>${esc(provider)}</strong>
                        <span>No limit headers yet</span>
                    </div>
                </div>
            `;
        }
        const reqBar = reqPct === null ? "" : `<div class="session-progress"><span style="width:${reqPct.toFixed(2)}%"></span></div>`;
        const tokBar = tokPct === null ? "" : `<div class="session-progress"><span style="width:${tokPct.toFixed(2)}%"></span></div>`;
        const fallbackNote = (!hasLimitHeaders && (Number(observed.requests || 0) > 0 || Number(observed.tokens_in_est || 0) > 0 || Number(observed.tokens_out_est || 0) > 0))
            ? `
                <div class="session-sub">
                    <span>Session usage: req=${esc(fmtInt(observed.requests))}</span>
                    <span>tok in/out ${esc(fmtInt(observed.tokens_in_est))}/${esc(fmtInt(observed.tokens_out_est))}</span>
                </div>
              `
            : (!hasLimitHeaders ? `<div class="session-sub"><span>Provider sends no limit headers</span><span>Showing transport status only</span></div>` : "");
        return `
            <div class="session-item">
                <div class="session-item-head">
                    <strong>${esc(provider)}</strong>
                    <span>${esc(item.status_code || "-")} · ${esc(fmtTime(item.updated_at))}</span>
                </div>
                <div class="session-sub">
                    <span>Requests: ${esc(fmtMaybeInt(req.remaining))} / ${esc(fmtMaybeInt(req.limit))}</span>
                    <span>Reset: ${esc(req.reset || "-")}</span>
                </div>
                ${reqBar}
                <div class="session-sub">
                    <span>Tokens: ${esc(fmtMaybeInt(tok.remaining))} / ${esc(fmtMaybeInt(tok.limit))}</span>
                    <span>Reset: ${esc(tok.reset || "-")}</span>
                </div>
                ${tokBar}
                ${fallbackNote}
            </div>
        `;
    });
    target.innerHTML = cards.join("");
}

function renderProviders() {
    const target = document.getElementById("session-providers");
    if (!target) return;
    const rows = Array.isArray(state.payload?.providers) ? state.payload.providers : [];
    if (!rows.length) {
        target.innerHTML = `<div class="session-empty">No requests in this session yet.</div>`;
        return;
    }
    target.innerHTML = rows.slice(0, 8).map((row) => `
        <div class="session-item">
            <div class="session-item-head">
                <strong>${esc(row.provider || "unknown")}</strong>
                <span>req=${esc(fmtInt(row.requests))} · err=${esc(fmtInt(row.errors))}</span>
            </div>
            <div class="session-sub">
                <span>Tokens in/out: ${esc(fmtInt(row.tokens_in_est))} / ${esc(fmtInt(row.tokens_out_est))}</span>
                <span>Last: ${esc(row.last_model || "-")}</span>
            </div>
        </div>
    `).join("");
}

function renderModels() {
    const target = document.getElementById("session-models");
    if (!target) return;
    const rows = Array.isArray(state.payload?.models) ? state.payload.models : [];
    if (!rows.length) {
        target.innerHTML = `<div class="session-empty">No model usage yet.</div>`;
        return;
    }
    target.innerHTML = rows.slice(0, 10).map((row) => `
        <div class="session-item">
            <div class="session-item-head">
                <strong>${esc(row.model || "unknown")}</strong>
                <span>${esc(row.provider || "unknown")}</span>
            </div>
            <div class="session-sub">
                <span>req=${esc(fmtInt(row.requests))} · err=${esc(fmtInt(row.errors))}</span>
                <span>tok in/out ${esc(fmtInt(row.tokens_in_est))}/${esc(fmtInt(row.tokens_out_est))}</span>
            </div>
        </div>
    `).join("");
}

function renderStatus() {
    const target = document.getElementById("session-status");
    if (!target) return;
    const s = state.payload?.session || {};
    const codes = s.status_codes || {};
    target.innerHTML = `
        <div class="session-mini"><span>Errors</span><strong>${esc(fmtInt(s.errors_total))}</strong></div>
        <div class="session-mini"><span>Rate Limit Events</span><strong>${esc(fmtInt(s.rate_limit_events))}</strong></div>
        <div class="session-mini"><span>Stream / Non-Stream</span><strong>${esc(fmtInt(s.requests_stream))} / ${esc(fmtInt(s.requests_non_stream))}</strong></div>
        <div class="session-mini"><span>Status 200</span><strong>${esc(fmtInt(codes["200"]))}</strong></div>
        <div class="session-mini"><span>Status 429</span><strong>${esc(fmtInt(codes["429"]))}</strong></div>
        <div class="session-mini"><span>Status 500</span><strong>${esc(fmtInt(codes["500"]))}</strong></div>
    `;
}

function renderLocalRuntime() {
    const target = document.getElementById("session-local");
    if (!target) return;
    const providers = Array.isArray(state.payload?.providers) ? state.payload.providers : [];
    const ollama = providers.find((p) => String(p.provider || "").toLowerCase() === "ollama");
    const instances = Array.isArray(state.instances?.instances) ? state.instances.instances : [];
    const healthy = instances.filter((it) => Boolean(it?.running) && Boolean(it?.health?.ok)).length;
    const running = instances.filter((it) => Boolean(it?.running)).length;

    const usage = ollama
        ? `
            <div class="session-item">
                <div class="session-item-head"><strong>Ollama Usage</strong><span>local</span></div>
                <div class="session-sub"><span>requests=${esc(fmtInt(ollama.requests))}</span><span>errors=${esc(fmtInt(ollama.errors))}</span></div>
                <div class="session-sub"><span>tokens in/out ${esc(fmtInt(ollama.tokens_in_est))}/${esc(fmtInt(ollama.tokens_out_est))}</span><span>last=${esc(ollama.last_model || "-")}</span></div>
            </div>
        `
        : `<div class="session-empty">No local Ollama requests yet.</div>`;

    const infra = `
        <div class="session-item">
            <div class="session-item-head"><strong>Compute Instances</strong><span>${esc(fmtInt(instances.length))} total</span></div>
            <div class="session-sub"><span>running=${esc(fmtInt(running))}</span><span>healthy=${esc(fmtInt(healthy))}</span></div>
        </div>
    `;

    target.innerHTML = `${usage}${infra}`;
}

function renderAll() {
    renderKpis();
    renderCloudBudget();
    renderProviders();
    renderModels();
    renderStatus();
    renderLocalRuntime();
}

async function refreshAll() {
    try {
        const [sessionPayload, instancesPayload] = await Promise.all([
            fetchJson("/api/runtime/session"),
            fetchJson("/api/runtime/compute/instances"),
        ]);
        state.payload = sessionPayload || {};
        state.instances = instancesPayload || {};
        renderAll();
        setFeedback(`Updated ${new Date().toLocaleTimeString()}`, "ok");
    } catch (err) {
        console.error("[SessionApp] refresh failed:", err);
        setFeedback(`Refresh failed: ${err.message || err}`, "err");
    }
}

function bindEvents(root) {
    const refreshBtn = root.querySelector("#session-refresh-btn");
    const autoBtn = root.querySelector("#session-autorefresh-btn");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
            void refreshAll();
        });
    }
    if (autoBtn) {
        autoBtn.addEventListener("click", () => {
            if (refreshTimer) {
                clearInterval(refreshTimer);
                refreshTimer = null;
                autoBtn.textContent = "Auto: off";
                autoBtn.classList.remove("primary");
                return;
            }
            refreshTimer = setInterval(() => void refreshAll(), 5000);
            autoBtn.textContent = "Auto: on";
            autoBtn.classList.add("primary");
        });
    }
}

export async function initSessionApp() {
    const root = document.getElementById("app-session");
    if (!root) return;

    if (!root.dataset.sessionInit) {
        renderLayout(root);
        bindEvents(root);
        root.dataset.sessionInit = "1";
    }

    await refreshAll();
    if (!refreshTimer) {
        refreshTimer = setInterval(() => {
            void refreshAll();
        }, 5000);
    }
}
