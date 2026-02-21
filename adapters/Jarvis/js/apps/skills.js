/**
 * skills.js - Skills Manager App & AI Studio
 * Manages TRION Skills via the Skill Server MCP
 */

// Use same hostname as WebUI, just different port
const SKILL_SERVER_URL = `${window.location.protocol}//${window.location.hostname}:8088`;
const TOOL_EXECUTOR_URL = `${window.location.protocol}//${window.location.hostname}:8000`;

let skillsInitialized = false;

/**
 * Initialize Skills App
 */
export function initSkillsApp() {
    if (skillsInitialized) {
        refreshSkills();
        return;
    }

    console.log("🧩 Initializing Skills Manager...");

    // Setup Tab Navigation
    setupTabs();

    // Setup Event Handlers
    setupEventHandlers();

    // Load Initial Data
    refreshSkills();

    skillsInitialized = true;
}

/**
 * Setup Tab Navigation
 */
function setupTabs() {
    const tabs = document.querySelectorAll('.skill-tab');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Update active tab
            tabs.forEach(t => {
                t.classList.remove('active', 'bg-accent-primary/20', 'text-accent-primary');
                t.classList.add('bg-dark-hover', 'text-gray-400');
            });
            tab.classList.add('active', 'bg-accent-primary/20', 'text-accent-primary');
            tab.classList.remove('bg-dark-hover', 'text-gray-400');

            // Show corresponding panel
            const targetTab = tab.dataset.tab;
            document.querySelectorAll('.skills-panel').forEach(panel => {
                panel.classList.add('hidden');
            });
            document.getElementById(`skills-tab-${targetTab}`)?.classList.remove('hidden');

            if (targetTab === 'packages') loadPackages();
        });
    });
}

/**
 * Setup Event Handlers
 */
function setupEventHandlers() {
    // Refresh Button
    const refreshBtn = document.getElementById('refresh-skills-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            refreshSkills();
        });
    }

    // Close Button
    const closeBtn = document.getElementById('close-skills-btn');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            document.getElementById('skills-modal')?.classList.add('hidden');
        });
    }

    // Studio Actions
    document.getElementById('studio-validate-btn')?.addEventListener('click', handleValidateCode);
    document.getElementById('studio-save-btn')?.addEventListener('click', () => handleSaveSkill(true)); // Draft
    document.getElementById('studio-help-btn')?.addEventListener('click', handleGetSafetyTips);
}

/**
 * Refresh Skills Data
 */

/**
 * Refresh Skills List
 */
async function refreshSkills() {
    setStatus("Refreshing...");
    const containerInstalled = document.getElementById('installed-skills-list');
    const containerDrafts = document.getElementById('drafts-skills-list');
    
    if (containerInstalled) containerInstalled.innerHTML = '<div class="col-span-2 text-center py-8 text-gray-500">Loading...</div>';
    if (containerDrafts) containerDrafts.innerHTML = '<div class="col-span-2 text-center py-8 text-gray-500">Loading...</div>';

    try {
        // Fetch from new /v1/skills endpoint on Tool Executor (Port 8000)
        const response = await fetch(`${SKILL_SERVER_URL}/v1/skills`);
        if (!response.ok) throw new Error("Failed to fetch skills");
        
        const data = await response.json();
        const activeSkills = data.active || [];
        const draftSkills = data.drafts || [];

        renderSkillsList(activeSkills, 'installed-skills-list', false);
        renderSkillsList(draftSkills, 'drafts-skills-list', true);
        
        setStatus("Ready");
    } catch (e) {
        console.error("Refresh failed", e);
        renderError('installed-skills-list', e.message);
        renderError('drafts-skills-list', e.message);
        setStatus("Error", true);
    }
}


function renderInstalledSkills(skills) {
    const container = document.getElementById('installed-skills-list');
    if (!container) return;

    if (skills.length === 0) {
        container.innerHTML = `
            <div class="col-span-2 text-center py-12 text-gray-500">
                <i data-lucide="package-open" class="w-12 h-12 mx-auto mb-4 opacity-50"></i>
                <p>No skills installed yet.</p>
                <p class="text-sm mt-2">Browse the "Available" tab to install skills.</p>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    container.innerHTML = skills.map(skill => `
        <div class="skill-card bg-dark-hover border border-dark-border rounded-xl p-4 hover:border-accent-primary/50 transition-colors">
            <div class="flex items-start justify-between mb-3">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center">
                        <i data-lucide="check-circle" class="w-5 h-5 text-white"></i>
                    </div>
                    <div>
                        <h3 class="font-semibold text-white">${escapeHtml(skill.name)}</h3>
                        <span class="text-xs text-gray-500">v${escapeHtml(skill.version || '1.0.0')}</span>
                    </div>
                </div>
                <span class="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400">Installed</span>
            </div>
            <p class="text-sm text-gray-400 mb-4">${escapeHtml(skill.description || 'No description')}</p>
            <div class="flex gap-2">
                <button onclick="window.SkillsApp.runSkill('${escapeHtml(skill.name)}')"
                    class="flex-1 px-3 py-2 bg-accent-primary/20 text-accent-primary rounded-lg hover:bg-accent-primary/30 transition-colors text-sm font-medium flex items-center justify-center gap-2">
                    <i data-lucide="play" class="w-4 h-4"></i>
                    Run
                </button>
                <button onclick="window.SkillsApp.uninstallSkill('${escapeHtml(skill.name)}')"
                    class="px-3 py-2 bg-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 transition-colors text-sm">
                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                </button>
            </div>
        </div>
    `).join('');

    lucide.createIcons();
}

/**
 * Render Available Skills
 */
function renderAvailableSkills(available, installed) {
    const container = document.getElementById('available-skills-list');
    if (!container) return;

    const installedNames = installed.map(s => s.name);
    const notInstalled = available.filter(s => !installedNames.includes(s.name));

    if (notInstalled.length === 0) {
        container.innerHTML = `
            <div class="col-span-2 text-center py-12 text-gray-500">
                <i data-lucide="check-circle" class="w-12 h-12 mx-auto mb-4 opacity-50"></i>
                <p>All available skills are installed!</p>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    container.innerHTML = notInstalled.map(skill => `
        <div class="skill-card bg-dark-hover border border-dark-border rounded-xl p-4 hover:border-accent-primary/50 transition-colors">
            <div class="flex items-start justify-between mb-3">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-gray-600 to-gray-700 flex items-center justify-center">
                        <i data-lucide="package" class="w-5 h-5 text-white"></i>
                    </div>
                    <div>
                        <h3 class="font-semibold text-white">${escapeHtml(skill.name)}</h3>
                        <span class="text-xs text-gray-500">v${escapeHtml(skill.version || '1.0.0')}</span>
                    </div>
                </div>
                <span class="px-2 py-1 rounded text-xs bg-gray-500/20 text-gray-400">${escapeHtml(skill.category || 'utility')}</span>
            </div>
            <p class="text-sm text-gray-400 mb-4">${escapeHtml(skill.description || 'No description')}</p>
            <button onclick="window.SkillsApp.installSkill('${escapeHtml(skill.name)}')"
                class="w-full px-3 py-2 bg-accent-primary text-black font-semibold rounded-lg hover:bg-orange-500 transition-colors text-sm flex items-center justify-center gap-2">
                <i data-lucide="download" class="w-4 h-4"></i>
                Install
            </button>
        </div>
    `).join('');

    lucide.createIcons();
}

/**
 * Render Draft Skills
 */
function renderDrafts(drafts) {
    const container = document.getElementById('skills-tab-drafts');
    if (!container) return;

    // We need to inject the grid container first if not present
    let grid = document.getElementById('drafts-list-grid');
    if (!grid) {
        container.innerHTML = `<div id="drafts-list-grid" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>`;
        grid = document.getElementById('drafts-list-grid');
    }

    if (!drafts || drafts.length === 0) {
        grid.innerHTML = `
            <div class="col-span-2 text-center py-12 text-gray-500">
                <i data-lucide="file-edit" class="w-12 h-12 mx-auto mb-4 opacity-50"></i>
                <p>No drafts yet. Create one in AI Studio!</p>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    grid.innerHTML = drafts.map(draft => `
        <div class="bg-dark-hover border border-dark-border rounded-xl p-4 border-dashed border-gray-700">
            <div class="flex items-center gap-3 mb-3">
                <i data-lucide="file-edit" class="text-yellow-500"></i>
                <h3 class="font-semibold text-white">${escapeHtml(draft.name)}</h3>
            </div>
            <p class="text-sm text-gray-400 mb-4 line-clamp-2">${escapeHtml(draft.description || '')}</p>
            <div class="flex gap-2">
                <button onclick="window.SkillsApp.loadDraft('${escapeHtml(draft.name)}')" class="flex-1 px-3 py-2 bg-gray-700 rounded hover:bg-gray-600 text-sm">Edit</button>
                <button onclick="window.SkillsApp.promoteDraft('${escapeHtml(draft.name)}')" class="px-3 py-2 bg-green-900/50 text-green-400 rounded hover:bg-green-900 text-sm">Deploy</button>
            </div>
        </div>
    `).join('');

    lucide.createIcons();
}

/**
 * Install a Skill
 */
/**
 * Render Skills List (Generic)
 * ADDED: Missing function that was called but not defined
 */
function renderSkillsList(skills, containerId, isDraft = false) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.warn(`Container ${containerId} not found`);
        return;
    }

    if (!skills || skills.length === 0) {
        const icon = isDraft ? "file-edit" : "package-open";
        const msg = isDraft ? "No drafts yet. Create one in AI Studio!" : "No skills installed yet.";
        container.innerHTML = `
            <div class="col-span-2 text-center py-12 text-gray-500">
                <i data-lucide="${icon}" class="w-12 h-12 mx-auto mb-4 opacity-50"></i>
                <p>${msg}</p>
            </div>
        `;
        if (typeof lucide !== "undefined") lucide.createIcons();
        return;
    }

    container.innerHTML = skills.map(skill => {
        const name = skill.name || skill;
        const desc = skill.description || "No description";
        const version = skill.version || "1.0.0";
        
        if (isDraft) {
            return `
                <div class="bg-dark-hover border border-dark-border rounded-xl p-4 border-dashed border-gray-700">
                    <div class="flex items-center gap-3 mb-3">
                        <i data-lucide="file-edit" class="text-yellow-500"></i>
                        <h3 class="font-semibold text-white">${escapeHtml(name)}</h3>
                    </div>
                    <p class="text-sm text-gray-400 mb-4 line-clamp-2">${escapeHtml(desc)}</p>
                    <div class="flex gap-2">
                        <button onclick="window.SkillsApp.loadDraft('${escapeHtml(name)}')" class="flex-1 px-3 py-2 bg-gray-700 rounded hover:bg-gray-600 text-sm">Edit</button>
                        <button onclick="window.SkillsApp.promoteDraft('${escapeHtml(name)}')" class="px-3 py-2 bg-green-900/50 text-green-400 rounded hover:bg-green-900 text-sm">Deploy</button>
                    </div>
                </div>
            `;
        } else {
            return `
                <div class="skill-card bg-dark-hover border border-dark-border rounded-xl p-4 hover:border-accent-primary/50 transition-colors">
                    <div class="flex items-start justify-between mb-3">
                        <div class="flex items-center gap-3">
                            <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center">
                                <i data-lucide="check-circle" class="w-5 h-5 text-white"></i>
                            </div>
                            <div>
                                <h3 class="font-semibold text-white">${escapeHtml(name)}</h3>
                                <span class="text-xs text-gray-500">v${escapeHtml(version)}</span>
                            </div>
                        </div>
                        <span class="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400">Installed</span>
                    </div>
                    <p class="text-sm text-gray-400 mb-4">${escapeHtml(desc)}</p>
                    <div class="flex gap-2">
                        <button onclick="window.SkillsApp.runSkill('${escapeHtml(name)}')"
                            class="flex-1 px-3 py-2 bg-accent-primary/20 text-accent-primary rounded-lg hover:bg-accent-primary/30 transition-colors text-sm font-medium flex items-center justify-center gap-2">
                            <i data-lucide="play" class="w-4 h-4"></i>
                            Run
                        </button>
                        <button onclick="window.SkillsApp.uninstallSkill('${escapeHtml(name)}')"
                            class="px-3 py-2 bg-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 transition-colors text-sm">
                            <i data-lucide="trash-2" class="w-4 h-4"></i>
                        </button>
                    </div>
                </div>
            `;
        }
    }).join("");

    if (typeof lucide !== "undefined") lucide.createIcons();
}


async function installSkill(name) {
    setStatus(`Installing ${name}...`);

    try {
        const result = await callSkillTool('install_skill', { name });

        if (result.success) {
            showToast(`Skill "${name}" installed!`, 'success');
            refreshSkills();
        } else {
            showToast(result.error || result.message || 'Installation failed', 'error');
            setStatus('Installation failed', true);
        }
    } catch (error) {
        console.error('Install failed:', error);
        showToast('Installation failed', 'error');
        setStatus('Error', true);
    }
}

/**
 * Uninstall a Skill
 */
async function uninstallSkill(name) {
    if (!confirm(`Uninstall skill "${name}"?`)) return;

    setStatus(`Uninstalling ${name}...`);

    try {
        const result = await callSkillTool('uninstall_skill', { name });

        if (result.success) {
            showToast(`Skill "${name}" uninstalled`, 'success');
            refreshSkills();
        } else {
            showToast(result.error || result.message || 'Uninstall failed', 'error');
        }
    } catch (error) {
        console.error('Uninstall failed:', error);
        showToast('Uninstall failed', 'error');
    }
}

/**
 * Run a Skill
 */
async function runSkill(name) {
    setStatus(`Running ${name}...`);

    try {
        const result = await callSkillTool('run_skill', { name, action: 'run', args: {} });

        if (result.success) {
            showToast(`Skill "${name}" executed`, 'success');
            console.log('Skill result:', result.result);

            // Show result in a simple alert for now
            alert(`Skill Output:\n${JSON.stringify(result.result, null, 2)}`);
        } else {
            showToast(result.error || 'Execution failed', 'error');
        }

        setStatus('Ready');
    } catch (error) {
        console.error('Run failed:', error);
        showToast('Execution failed', 'error');
        setStatus('Error', true);
    }
}

/**
 * STUDIO: Validate Code
 */
async function handleValidateCode() {
    const code = document.getElementById('studio-code-editor').value;
    const output = document.getElementById('studio-validation-output');

    output.innerHTML = '<span class="text-yellow-500">Analyzing...</span>';

    try {
        const result = await callSkillTool('validate_skill_code', { code });

        let html = '';
        if (result.passed) {
            html += `<div class="text-green-500 font-bold mb-2">✅ PASSED (Score: ${(result.score * 100).toFixed(0)}%)</div>`;
        } else {
            html += `<div class="text-red-500 font-bold mb-2">❌ FAILED (Score: ${(result.score * 100).toFixed(0)}%)</div>`;
        }

        if (result.issues && result.issues.length > 0) {
            html += `<ul class="space-y-2 mt-2">`;
            result.issues.forEach(issue => {
                const color = issue.severity === 'critical' ? 'text-red-500' : 'text-yellow-500';
                html += `<li class="${color}">• [${issue.severity.toUpperCase()}] ${escapeHtml(issue.description || issue.pattern)}</li>`;
            });
            html += `</ul>`;
        } else {
            html += `<div class="text-gray-400 mt-2">No issues found. Safe to deploy.</div>`;
        }

        output.innerHTML = html;

    } catch (e) {
        output.innerHTML = `<span class="text-red-500">Error: ${escapeHtml(e.message)}</span>`;
    }
}

/**
 * STUDIO: Save Draft
 */
async function handleSaveSkill(isDraft) {
    const name = document.getElementById('studio-skill-name').value;
    const desc = document.getElementById('studio-skill-desc').value;
    const code = document.getElementById('studio-code-editor').value;

    if (!name || !code) {
        showToast("Name and Code are required", "error");
        return;
    }

    setStatus("Saving draft...");

    try {
        const result = await callSkillTool('create_skill', {
            name,
            description: desc,
            code,
            auto_promote: !isDraft,
            draft: isDraft
        });

        const saveOk = result.success || result.installation?.success;
        if (saveOk) {
            showToast(`Draft "${name}" saved!`, "success");
            refreshSkills();
        } else {
            showToast(result.error || "Save failed", "error");
        }
    } catch (e) {
        showToast("Error saving: " + e.message, "error");
    }
    setStatus("Ready");
}

/**
 * STUDIO: Get Safety Tips (Priors)
 */
async function handleGetSafetyTips() {
    const desc = document.getElementById('studio-skill-desc').value || "general python code";
    const output = document.getElementById('studio-validation-output');

    output.innerHTML = '<span class="text-blue-400">Fetching priors...</span>';

    try {
        const result = await callSkillTool('get_safety_priors', { context: desc });

        let html = `<div class="text-blue-400 font-bold mb-2">ℹ️ Safety Priors</div>`;
        if (result.applicable_priors) {
            html += `<ul class="space-y-2 mt-2">`;
            result.applicable_priors.forEach(p => {
                html += `<li class="text-gray-400 text-xs">• <strong class="text-gray-200">${escapeHtml(p.principle)}</strong>: ${escapeHtml(p.enforcement)}</li>`;
            });
            html += `</ul>`;
        }
        output.innerHTML = html;

    } catch (e) {
        output.innerHTML = `<span class="text-red-500">Error: ${escapeHtml(e.message)}</span>`;
    }
}

/**
 * Load Draft into Studio
 */
async function loadDraft(name) {
    setStatus(`Loading ${name}...`);
    try {
        const data = await callSkillTool('get_skill_draft', { name });
        if (data.error) throw new Error(data.error);

        // Switch to Studio Tab
        document.querySelector('[data-tab="studio"]').click();

        // Fill fields
        document.getElementById('studio-skill-name').value = data.name;
        document.getElementById('studio-skill-desc').value = data.description || data.manifest?.description || "";
        document.getElementById('studio-code-editor').value = data.code || "";

        // Trigger validation automatically
        handleValidateCode();

        setStatus("Draft loaded");

    } catch (e) {
        showToast("Load failed: " + e.message, "error");
    }
}

/**
 * Promote Draft
 */
async function promoteDraft(name) {
    if (!confirm(`Deploy skill "${name}" to active system?`)) return;

    setStatus("Deploying...");
    try {
        const res = await callSkillTool('promote_skill_draft', { name });
        const deployOk = res.success || res.installation?.success;
        if (deployOk) {
            showToast(`Skill "${name}" deployed!`, "success");
            refreshSkills();
        } else {
            showToast(res.error || "Deploy failed", "error");
        }
    } catch (e) {
        showToast("Deploy failed: " + e.message, "error");
    }
}

/**
 * Call Skill Server MCP Tool
 */
async function callSkillTool(toolName, args = {}) {
    const response = await fetch(`${SKILL_SERVER_URL}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            jsonrpc: '2.0',
            id: Date.now(),
            method: 'tools/call',
            params: { name: toolName, arguments: args }
        })
    });

    const data = await response.json();

    if (data.error) {
        throw new Error(data.error.message || 'MCP Error');
    }

    // Parse the text content
    const content = data.result?.content?.[0]?.text;
    if (content) {
        return JSON.parse(content);
    }

    return data.result;
}

/**
 * Render Error State
 */
function renderError(containerId, message) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = `
        <div class="col-span-2 text-center py-12 text-red-400">
            <i data-lucide="alert-circle" class="w-12 h-12 mx-auto mb-4 opacity-50"></i>
            <p>${escapeHtml(message)}</p>
            <button onclick="window.SkillsApp.refresh()" class="mt-4 px-4 py-2 bg-dark-hover rounded-lg hover:bg-dark-border transition-colors">
                Retry
            </button>
        </div>
    `;
    lucide.createIcons();
}

/**
 * Set Status Text
 */
function setStatus(text, isError = false) {
    const el = document.getElementById('skills-status');
    if (el) {
        el.textContent = text;
        el.className = isError ? 'text-red-400' : 'text-gray-500';
    }
}

/**
 * Show Toast Notification
 */
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    const colors = {
        info: 'border-accent-primary',
        success: 'border-green-500 text-green-400',
        error: 'border-red-500 text-red-400'
    };

    toast.className = `px-4 py-3 rounded-lg border-l-4 shadow-xl bg-dark-card transform transition-all duration-300 translate-y-2 opacity-0 ${colors[type]}`;
    toast.innerHTML = `<span class="font-mono text-sm">${escapeHtml(message)}</span>`;

    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.remove('translate-y-2', 'opacity-0'));

    setTimeout(() => {
        toast.classList.add('translate-y-2', 'opacity-0');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/**
 * Escape HTML
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

// === PACKAGES TAB ===

async function loadPackages() {
    try {
        const res = await fetch(`${TOOL_EXECUTOR_URL}/v1/packages`);
        const data = await res.json();

        // Allowlist chips
        const allowlistEl = document.getElementById('pkg-allowlist');
        if (allowlistEl && data.allowlist) {
            allowlistEl.innerHTML = data.allowlist.map(pkg =>
                `<span class="px-2 py-1 rounded-full text-xs bg-green-900/30 text-green-400 border border-green-900/50">${escapeHtml(pkg)}</span>`
            ).join('');
        }

        // Installed packages table
        const listEl = document.getElementById('pkg-installed-list');
        if (listEl && data.packages) {
            listEl.innerHTML = `
                <div class="overflow-x-auto">
                    <table class="w-full text-xs">
                        <thead>
                            <tr class="text-gray-500 border-b border-dark-border">
                                <th class="text-left py-2 pr-4">Paket</th>
                                <th class="text-left py-2">Version</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.packages.map(p => `
                                <tr class="border-b border-dark-border/50 hover:bg-dark-bg/50">
                                    <td class="py-1.5 pr-4 text-gray-200">${escapeHtml(p.name)}</td>
                                    <td class="py-1.5 text-gray-500">${escapeHtml(p.version)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>`;
        }
    } catch (e) {
        const listEl = document.getElementById('pkg-installed-list');
        if (listEl) listEl.innerHTML = `<span class="text-red-400">Fehler: ${escapeHtml(e.message)}</span>`;
    }
}

async function installPackage() {
    const input = document.getElementById('pkg-install-input');
    const resultEl = document.getElementById('pkg-install-result');
    const pkg = input?.value?.trim().toLowerCase();

    if (!pkg) { showToast('Paketname eingeben', 'error'); return; }

    if (!confirm(`Paket "${pkg}" installieren?\n\nDies installiert ein Python-Paket in die Skill-Sandbox. Nur Pakete aus der Allowlist sind erlaubt.`)) return;

    resultEl.className = 'mt-2 text-xs text-blue-400';
    resultEl.textContent = `Installiere ${pkg}...`;

    try {
        const res = await fetch(`${TOOL_EXECUTOR_URL}/v1/packages/install`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ package: pkg })
        });
        const data = await res.json();

        if (data.success) {
            resultEl.className = 'mt-2 text-xs text-green-400';
            resultEl.textContent = `✓ ${pkg} erfolgreich installiert`;
            input.value = '';
            showToast(`${pkg} installiert!`, 'success');
            setTimeout(loadPackages, 500);
        } else {
            resultEl.className = 'mt-2 text-xs text-red-400';
            resultEl.textContent = `✗ ${data.error}`;
            showToast(data.error, 'error');
        }
    } catch (e) {
        resultEl.className = 'mt-2 text-xs text-red-400';
        resultEl.textContent = `✗ Fehler: ${e.message}`;
    }
}

// Export for global access
window.SkillsApp = {
    init: initSkillsApp,
    refresh: refreshSkills,
    installSkill,
    uninstallSkill,
    runSkill,
    loadDraft,
    promoteDraft,
    installPackage,
};
