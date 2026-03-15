/**
 * marketplace.js - Blueprint Marketplace App (Launchpad)
 * V1: curated catalog sync/list/install with quick filters.
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
    category: "all",
    trustedOnly: false,
    search: "",
    catalog: [],
    categories: {},
    source: {},
    syncedAt: "",
    count: 0,
    installedIds: new Set(),
    installing: new Set(),
    loading: false,
};

function apiRoot(path) {
    return `${getApiBase()}/api/commander${path}`;
}

async function fetchJson(path, options = {}) {
    const res = await fetch(apiRoot(path), options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data?.ok === false || data?.error) {
        const err = new Error(String(data?.error || data?.error_code || `HTTP ${res.status}`));
        err.status = res.status;
        err.code = data?.error_code || "";
        err.details = data?.details || null;
        throw err;
    }
    return data;
}

function formatTime(iso) {
    if (!iso) return "-";
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return String(iso);
    }
}

function matchesSearch(row, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return true;
    const hay = [
        row.id,
        row.name,
        row.description,
        row.category,
        row.author,
        ...(Array.isArray(row.tags) ? row.tags : []),
    ]
        .map((v) => String(v || "").toLowerCase())
        .join(" ");
    return hay.includes(q);
}

function renderLayout(root) {
    root.innerHTML = `
        <div class="market-app">
            <header class="market-head">
                <h2><i data-lucide="store"></i> Blueprint Marketplace</h2>
                <div class="market-head-actions">
                    <button id="market-refresh-btn" class="market-btn ghost"><i data-lucide="refresh-ccw"></i> Refresh</button>
                </div>
            </header>

            <section class="market-grid-top">
                <article class="market-card">
                    <h3>Catalog Source</h3>
                    <div class="market-form">
                        <input id="market-repo-input" type="text" placeholder="GitHub Repo URL (optional override)" />
                        <div class="market-row">
                            <input id="market-branch-input" type="text" value="main" placeholder="Branch" />
                            <button id="market-sync-btn" class="market-btn primary"><i data-lucide="cloud-download"></i> Sync Catalog</button>
                        </div>
                    </div>
                    <small id="market-source-label" class="market-help">Using configured catalog source.</small>
                </article>

                <article class="market-card">
                    <h3>Overview</h3>
                    <div id="market-kpis" class="market-kpis"></div>
                </article>
            </section>

            <section class="market-card">
                <div class="market-filters">
                    <input id="market-search" type="text" placeholder="Search by name, tag, category..." />
                    <select id="market-category"></select>
                    <label class="market-checkbox">
                        <input type="checkbox" id="market-trusted-only" />
                        <span>Trusted only</span>
                    </label>
                </div>
            </section>

            <section class="market-grid" id="market-grid"></section>

            <footer id="market-feedback" class="market-feedback"></footer>
        </div>
    `;

    if (window.lucide) window.lucide.createIcons();
}

function setFeedback(msg, level = "info") {
    const el = document.getElementById("market-feedback");
    if (!el) return;
    el.textContent = msg || "";
    el.className = `market-feedback ${level}`;
}

function renderCategoryOptions() {
    const sel = document.getElementById("market-category");
    if (!sel) return;
    const previous = state.category || "all";
    const options = ["all", ...Object.keys(state.categories || {}).sort((a, b) => a.localeCompare(b))];
    sel.innerHTML = options
        .map((c) => `<option value="${esc(c)}">${esc(c === "all" ? "All categories" : c)}</option>`)
        .join("");
    sel.value = options.includes(previous) ? previous : "all";
    state.category = sel.value;
}

function renderKpis() {
    const el = document.getElementById("market-kpis");
    if (!el) return;

    const repoUrl = String(state.source?.repo_url || "").trim();
    const branch = String(state.source?.branch || "").trim() || "main";

    el.innerHTML = `
        <div class="market-kpi"><span>Catalog items</span><strong>${esc(state.count || 0)}</strong></div>
        <div class="market-kpi"><span>Installed local</span><strong>${esc(state.installedIds.size)}</strong></div>
        <div class="market-kpi"><span>Last sync</span><strong>${esc(formatTime(state.syncedAt))}</strong></div>
        <div class="market-kpi"><span>Branch</span><strong>${esc(branch)}</strong></div>
    `;

    const sourceLabel = document.getElementById("market-source-label");
    if (sourceLabel) {
        if (repoUrl) {
            sourceLabel.innerHTML = `Source: <code>${esc(repoUrl)}</code>`;
        } else {
            sourceLabel.textContent = "Source: configured default (settings/env).";
        }
    }

    const repoInput = document.getElementById("market-repo-input");
    if (repoInput && !repoInput.value && repoUrl) {
        repoInput.value = repoUrl;
    }
    const branchInput = document.getElementById("market-branch-input");
    if (branchInput && !branchInput.value) {
        branchInput.value = branch;
    }
}

function renderGrid() {
    const el = document.getElementById("market-grid");
    if (!el) return;

    const rows = state.catalog.filter((row) => matchesSearch(row, state.search));
    if (!rows.length) {
        el.innerHTML = `<div class="market-empty">No blueprints found for the current filters.</div>`;
        return;
    }

    el.innerHTML = rows
        .map((row) => {
            const installed = state.installedIds.has(String(row.id || ""));
            const busy = state.installing.has(String(row.id || ""));
            const tags = Array.isArray(row.tags) ? row.tags : [];
            const health = row.health_profile || {};
            const trust = String(row.trusted_level || "unknown");
            const runtime = String(row.requires_runtime || "none");
            const needsApproval = Boolean(row.requires_approval);
            const yamlUrl = String(row.yaml_url || "").trim();

            return `
                <article class="market-item">
                    <div class="market-item-head">
                        <div class="market-item-icon">${esc(row.icon || "📦")}</div>
                        <div class="market-item-main">
                            <h4>${esc(row.name || row.id || "unnamed")}</h4>
                            <small>${esc(row.id || "")}</small>
                        </div>
                        <span class="market-pill">${esc(row.category || "uncategorized")}</span>
                    </div>

                    <p class="market-item-desc">${esc(row.description || "No description")}</p>

                    <div class="market-meta-row">
                        <span class="market-meta-chip">trust:${esc(trust)}</span>
                        <span class="market-meta-chip">runtime:${esc(runtime)}</span>
                        <span class="market-meta-chip">approval:${needsApproval ? "yes" : "no"}</span>
                    </div>

                    <div class="market-meta-row">
                        <span class="market-meta-chip">health timeout:${esc(health.ready_timeout_seconds ?? "-")}s</span>
                        <span class="market-meta-chip">retries:${esc(health.retries ?? "-")}</span>
                    </div>

                    <div class="market-tags">
                        ${tags.slice(0, 6).map((t) => `<span class="market-tag">${esc(t)}</span>`).join("")}
                    </div>

                    <div class="market-actions">
                        <button class="market-btn ${installed ? "ok" : "primary"}" data-action="install" data-id="${esc(row.id || "")}" ${(busy || installed) ? "disabled" : ""}>
                            ${busy ? "Installing..." : installed ? "Installed" : "Install"}
                        </button>
                        ${yamlUrl ? `<a class="market-btn ghost" href="${esc(yamlUrl)}" target="_blank" rel="noopener">YAML</a>` : ""}
                    </div>
                </article>
            `;
        })
        .join("");
}

function renderAll() {
    renderCategoryOptions();
    renderKpis();
    renderGrid();
}

async function refreshInstalledBlueprints() {
    const data = await fetchJson("/blueprints");
    const rows = Array.isArray(data?.blueprints) ? data.blueprints : [];
    state.installedIds = new Set(rows.map((r) => String(r.id || "")).filter(Boolean));
}

function buildCatalogQuery() {
    const params = new URLSearchParams();
    const category = String(state.category || "all").trim().toLowerCase();
    if (category && category !== "all") {
        params.set("category", category);
    }
    if (state.trustedOnly) {
        params.set("trusted_only", "true");
    }
    const q = params.toString();
    return q ? `?${q}` : "";
}

async function refreshCatalog() {
    state.loading = true;
    try {
        const data = await fetchJson(`/marketplace/catalog${buildCatalogQuery()}`);
        state.catalog = Array.isArray(data?.blueprints) ? data.blueprints : [];
        state.categories = data?.categories || {};
        state.source = data?.source || {};
        state.syncedAt = String(data?.synced_at || "");
        state.count = Number(data?.count || state.catalog.length || 0);
        renderAll();
    } finally {
        state.loading = false;
    }
}

async function syncCatalog() {
    const repoInput = document.getElementById("market-repo-input");
    const branchInput = document.getElementById("market-branch-input");
    const payload = {
        repo_url: String(repoInput?.value || "").trim(),
        branch: String(branchInput?.value || "main").trim() || "main",
    };

    const btn = document.getElementById("market-sync-btn");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "Syncing...";
    }

    try {
        const data = await fetchJson("/marketplace/catalog/sync", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        setFeedback(`Catalog synced: ${Number(data?.count || 0)} items`, "ok");
        await refreshCatalog();
    } catch (err) {
        setFeedback(`Sync failed: ${err.message || err}`, "err");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="cloud-download"></i> Sync Catalog';
            if (window.lucide) window.lucide.createIcons();
        }
    }
}

async function installBlueprint(blueprintId) {
    const id = String(blueprintId || "").trim();
    if (!id) return;
    state.installing.add(id);
    renderGrid();

    try {
        const data = await fetchJson(`/marketplace/catalog/install/${encodeURIComponent(id)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ overwrite: false }),
        });

        if (data?.exists) {
            state.installedIds.add(id);
            setFeedback(`Blueprint already installed: ${id}`, "warn");
        } else if (data?.installed || data?.updated) {
            state.installedIds.add(id);
            setFeedback(`Blueprint installed: ${id}`, "ok");
        } else {
            setFeedback(`Install result received for ${id}`, "info");
        }
    } catch (err) {
        setFeedback(`Install failed for ${id}: ${err.message || err}`, "err");
    } finally {
        state.installing.delete(id);
        renderKpis();
        renderGrid();
    }
}

function bindEvents(root) {
    const refreshBtn = document.getElementById("market-refresh-btn");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", async () => {
            try {
                await Promise.all([refreshInstalledBlueprints(), refreshCatalog()]);
                setFeedback("Marketplace refreshed", "ok");
            } catch (err) {
                setFeedback(`Refresh failed: ${err.message || err}`, "err");
            }
        });
    }

    const syncBtn = document.getElementById("market-sync-btn");
    if (syncBtn) {
        syncBtn.addEventListener("click", syncCatalog);
    }

    const search = document.getElementById("market-search");
    if (search) {
        search.addEventListener("input", (e) => {
            state.search = String(e.target?.value || "");
            renderGrid();
        });
    }

    const category = document.getElementById("market-category");
    if (category) {
        category.addEventListener("change", async (e) => {
            state.category = String(e.target?.value || "all");
            try {
                await refreshCatalog();
            } catch (err) {
                setFeedback(`Category refresh failed: ${err.message || err}`, "err");
            }
        });
    }

    const trustedOnly = document.getElementById("market-trusted-only");
    if (trustedOnly) {
        trustedOnly.addEventListener("change", async (e) => {
            state.trustedOnly = Boolean(e.target?.checked);
            try {
                await refreshCatalog();
            } catch (err) {
                setFeedback(`Filter refresh failed: ${err.message || err}`, "err");
            }
        });
    }

    root.addEventListener("click", (e) => {
        const btn = e.target?.closest?.("[data-action='install']");
        if (!btn) return;
        const id = btn.getAttribute("data-id") || "";
        if (!id) return;
        installBlueprint(id);
    });
}

export async function initMarketplaceApp() {
    const root = document.getElementById("app-marketplace");
    if (!root) return;

    renderLayout(root);
    bindEvents(root);

    try {
        setFeedback("Loading marketplace catalog...", "info");
        await Promise.all([refreshInstalledBlueprints(), refreshCatalog()]);

        if (!state.catalog.length) {
            setFeedback("No catalog items cached yet. Click Sync Catalog.", "warn");
        } else {
            setFeedback(`Loaded ${state.catalog.length} catalog items`, "ok");
        }
    } catch (err) {
        setFeedback(`Marketplace init failed: ${err.message || err}`, "err");
    }
}
