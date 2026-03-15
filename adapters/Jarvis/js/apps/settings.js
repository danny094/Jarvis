/**
 * settings.js - Settings App Logic (Ubuntu Style)
 * Manages Personas, Models, and System Config
 */

import { getApiBase } from "../../static/js/api.js";
import { log } from "../../static/js/debug.js";

const els = {
    pages: {
        memory: document.getElementById('page-memory'),
        models: document.getElementById('page-models'),
    }
};

/**
 * Initialize Settings
 */
export async function initSettingsApp() {
    log('info', 'Initializing Settings App...');

    const switchCategory = async (category) => {
        if (!category) return;
        const navItems = document.querySelectorAll('.settings-category');
        navItems.forEach((item) => {
            const isActive = String(item.dataset.category || '') === category;
            item.classList.toggle('active', isActive);
        });
        document.querySelectorAll('.settings-page').forEach((page) => page.classList.add('hidden'));
        const page = document.getElementById(`page-${category}`);
        if (page) page.classList.remove('hidden');

        if (category === 'plugins') await loadPlugins();
        if (category === 'models') await loadModels();
    };

    // Own robust nav wiring (independent from shell.js)
    const navItems = document.querySelectorAll('.settings-category');
    navItems.forEach((item) => {
        if (item.dataset.settingsBound === '1') return;
        item.dataset.settingsBound = '1';
        item.addEventListener('click', () => {
            const category = String(item.dataset.category || '').trim();
            switchCategory(category).catch((e) => {
                log('error', `[Settings] category switch failed (${category}): ${e.message}`);
                showToast(`Failed to open ${category}: ${e.message}`, 'error');
            });
        });
    });

    // Initial load check
    const activeCat = document.querySelector('.settings-category.active');
    const initialCategory = String(activeCat?.dataset?.category || 'memory');
    await switchCategory(initialCategory);
}

/**
 * Setup Persona Button Handlers
 */
function setupPersonaHandlers() {
    log('info', '[Personas] Setting up button handlers...');

    // Edit Button (use event delegation since button is dynamically created)
    document.addEventListener('click', (e) => {
        const editBtn = e.target.closest('button');
        if (editBtn && editBtn.querySelector('[data-lucide="edit-3"]')) {
            handleEditPersona();
        }
    });

    // Upload Button
    const uploadBtn = document.getElementById('upload-persona-btn');
    if (uploadBtn) {
        uploadBtn.addEventListener('click', handleUploadPersona);
        log('info', '[Personas] Upload button listener attached');
    }

    // Switch Button  
    const switchBtn = document.getElementById('switch-persona-btn');
    if (switchBtn) {
        switchBtn.addEventListener('click', handleSwitchPersona);
        log('info', '[Personas] Switch button listener attached');
    }

    // File Input
    const fileInput = document.getElementById('persona-file-input');
    if (fileInput) {
        fileInput.addEventListener('change', handleFileInputChange);
        log('info', '[Personas] File input listener attached');
    }
}

// Track current active persona for editing
let currentActivePersona = null;

function handleEditPersona() {
    log('info', '[Personas] 🎯 Edit Persona clicked!');
    if (currentActivePersona) {
        openPersonaEditor(currentActivePersona);
    } else {
        showToast('No active persona to edit', 'error');
    }
}

/**
 * Open Persona Editor Modal
 */
async function openPersonaEditor(name) {
    log('info', `[Personas] Opening editor for: ${name}`);

    try {
        // Fetch persona content
        const res = await fetch(`${getApiBase()}/api/personas/${encodeURIComponent(name)}`);
        if (!res.ok) throw new Error('Failed to load persona');
        const data = await res.json();

        log('info', `[Personas] Loaded persona content (${data.content.length} chars)`);

        // Create modal
        const modal = document.createElement('div');
        modal.id = 'persona-editor-modal';
        modal.className = 'fixed inset-0 bg-black/80 flex items-center justify-center z-[9999] p-4';
        modal.innerHTML = `
            <div class="bg-[#0a0a0a] border border-[#333] rounded-xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl">
                <!-- Header -->
                <div class="flex items-center justify-between p-4 border-b border-[#333]">
                    <div class="flex items-center gap-3">
                        <i data-lucide="edit-3" class="w-5 h-5 text-accent-primary"></i>
                        <h3 class="text-xl font-bold text-white">Edit Persona: ${name}</h3>
                    </div>
                    <button onclick="closePersonaEditor()" class="p-2 hover:bg-[#222] rounded-lg transition-colors">
                        <i data-lucide="x" class="w-5 h-5 text-gray-400"></i>
                    </button>
                </div>
                
                <!-- Editor -->
                <div class="flex-1 p-4 overflow-hidden">
                    <textarea 
                        id="persona-editor-content"
                        class="w-full h-full min-h-[400px] bg-[#111] border border-[#333] rounded-lg p-4 text-gray-200 font-mono text-sm resize-none focus:border-accent-primary focus:outline-none"
                        spellcheck="false"
                    ></textarea>
                </div>
                
                <!-- Footer -->
                <div class="flex items-center justify-between p-4 border-t border-[#333]">
                    <p class="text-xs text-gray-500">
                        <i data-lucide="info" class="w-3 h-3 inline mr-1"></i>
                        Requires [IDENTITY] section with name: field
                    </p>
                    <div class="flex gap-3">
                        <button onclick="closePersonaEditor()" class="px-4 py-2 bg-[#222] text-gray-300 rounded-lg hover:bg-[#333] transition-colors">
                            Cancel
                        </button>
                        <button onclick="savePersonaEdit('${name}')" class="px-4 py-2 bg-accent-primary text-black font-bold rounded-lg hover:bg-orange-500 transition-colors flex items-center gap-2">
                            <i data-lucide="save" class="w-4 h-4"></i>
                            Save Changes
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Set content AFTER appending (avoids template literal issues with special chars)
        const textarea = document.getElementById('persona-editor-content');
        textarea.value = data.content;

        lucide.createIcons();

        // Focus textarea
        textarea.focus();

        log('info', '[Personas] Editor modal opened successfully');

        // Close on escape
        modal.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closePersonaEditor();
        });

        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closePersonaEditor();
        });

        // Trap focus (simple version)

    } catch (err) {
        log('error', `[Personas] Failed to open editor: ${err.message}`);
        showToast(`Failed to load persona: ${err.message}`, 'error');
    }
}

/**
 * Close Persona Editor Modal
 */
function closePersonaEditor() {
    const modal = document.getElementById('persona-editor-modal');
    if (modal) modal.remove();
}

/**
 * Save Persona Edit
 */
async function savePersonaEdit(name) {
    const content = document.getElementById('persona-editor-content').value;

    log('info', `[Personas] Saving changes to: ${name}`);

    try {
        showToast('Saving...', 'info');

        // Create a blob/file from the content
        const blob = new Blob([content], { type: 'text/plain' });
        const file = new File([blob], `${name}.txt`, { type: 'text/plain' });

        const formData = new FormData();
        formData.append('file', file);

        const res = await fetch(`${getApiBase()}/api/personas/${encodeURIComponent(name)}`, {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const errorData = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(errorData.detail || `HTTP ${res.status}`);
        }

        log('info', `[Personas] Save successful for: ${name}`);
        showToast(`Persona "${name}" saved successfully!`, 'success');

        closePersonaEditor();
        await loadPersonas();

    } catch (err) {
        log('error', `[Personas] Save failed: ${err.message}`);
        showToast(`Save failed: ${err.message}`, 'error');
    }
}

/**
 * Escape HTML for safe display in textarea
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function handleUploadPersona() {
    log('info', '[Personas] 🎯 Upload Persona clicked!');
    const fileInput = document.getElementById('persona-file-input');
    if (fileInput) {
        fileInput.click();
    }
}

async function handleSwitchPersona() {
    log('info', '[Personas] 🎯 Switch Persona clicked!');
    alert('Switch Persona functionality coming soon!');
}

async function handleFileInputChange(e) {
    const file = e.target.files[0];
    if (!file) return;

    log('info', `[Personas] File selected: ${file.name}`);

    // Create FormData for upload
    const formData = new FormData();
    formData.append('file', file);

    try {
        showToast(`Uploading ${file.name}...`, 'info');

        const personaName = file.name.replace(/.txt$/i, '');
        const res = await fetch(`${getApiBase()}/api/personas/${encodeURIComponent(personaName)}`, {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const errorText = await res.text();
            throw new Error(`HTTP ${res.status}: ${errorText}`);
        }

        const data = await res.json();
        log('info', `[Personas] Upload successful: ${JSON.stringify(data)}`);

        showToast(`Persona "${data.name || file.name}" uploaded successfully!`, 'success');

        // Reload personas to show new one
        await loadPersonas();

        // Clear file input
        e.target.value = '';

    } catch (err) {
        log('error', `[Personas] Upload failed: ${err.message}`);
        showToast(`Upload failed: ${err.message}`, 'error');
    }
}

/**
 * ═══════════════════════════════════════════════════════════
 * PERSONAS
 * ═══════════════════════════════════════════════════════════
 */

/**
 * Parse [IDENTITY] section from persona content
 */
function parseIdentitySection(content) {
    const identity = {};

    // Find [IDENTITY] section
    const identityMatch = content.match(/\[IDENTITY\]([\s\S]*?)(?=\[|$)/);
    if (!identityMatch) return identity;

    const section = identityMatch[1];

    // Parse key: value pairs
    const lines = section.split('\n');
    for (const line of lines) {
        const match = line.match(/^\s*(\w+):\s*(.+)$/i);
        if (match) {
            const key = match[1].toLowerCase();
            const value = match[2].trim();
            identity[key] = value;
        }
    }

    return identity;
}

async function loadPersonas() {
    if (!els.pages.personas) return;
    const container = els.pages.personas.querySelector('.grid');
    if (!container) return;

    try {
        const res = await fetch(`${getApiBase()}/api/personas/`);
        if (!res.ok) throw new Error("Failed to load personas");
        const data = await res.json();

        // Fetch active persona content for [IDENTITY] preview
        let activeIdentity = {};
        if (data.active) {
            try {
                const activeRes = await fetch(`${getApiBase()}/api/personas/${encodeURIComponent(data.active)}?_=${Date.now()}`);
                if (activeRes.ok) {
                    const activeData = await activeRes.json();
                    activeIdentity = parseIdentitySection(activeData.content);
                    log('info', `[Personas] Parsed identity: ${JSON.stringify(activeIdentity)}`);
                }
            } catch (e) {
                log('warn', `[Personas] Could not load active persona content: ${e.message}`);
            }
        }

        // data = { personas: [], active: "name" }
        renderPersonas(data.personas, data.active, activeIdentity, container);

    } catch (e) {
        log('error', `Personas Load Error: ${e.message}`);
        container.innerHTML = `<div class="text-red-400">Error: ${e.message}</div>`;
    }
}

function renderPersonas(list, activeName, activeIdentity, container) {
    // Separate Active vs Others
    const active = list.find(p => p === activeName) || list[0];
    const others = list.filter(p => p !== activeName);

    // Store active persona for edit functionality
    currentActivePersona = active;

    // Build identity preview HTML
    const identityFields = ['name', 'role', 'language', 'user_name'];
    const identityHtml = identityFields
        .filter(field => activeIdentity[field])
        .map(field => `
            <div class="flex items-center gap-2">
                <span class="text-gray-500 text-sm w-24">${field.charAt(0).toUpperCase() + field.slice(1).replace('_', ' ')}:</span>
                <span class="text-gray-300 text-sm font-medium">${activeIdentity[field]}</span>
            </div>
        `).join('');

    const html = `
        <!-- Active Persona (Featured) -->
        <div class="col-span-12 md:col-span-8 bg-[#111] border border-accent-primary/30 rounded-xl p-6 shadow-[0_0_15px_rgba(255,179,2,0.1)] relative overflow-hidden group">
            <div class="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                <i data-lucide="bot" class="w-32 h-32 text-accent-primary"></i>
            </div>
            
            <div class="relative z-10">
                <div class="flex items-center gap-4 mb-4">
                    <div class="w-16 h-16 rounded-full bg-accent-primary/20 flex items-center justify-center text-accent-primary border border-accent-primary/50">
                        <i data-lucide="zap" class="w-8 h-8"></i>
                    </div>
                    <div>
                        <h3 class="text-2xl font-bold text-white">${active}</h3>
                        <p class="text-accent-primary text-sm font-mono uppercase tracking-wider">Active System Persona</p>
                    </div>
                </div>
                
                <!-- Identity Preview -->
                ${identityHtml ? `
                <div class="bg-black/30 rounded-lg p-4 mb-6 border border-[#222]">
                    <div class="flex items-center gap-2 mb-3">
                        <i data-lucide="fingerprint" class="w-4 h-4 text-accent-primary"></i>
                        <span class="text-xs text-accent-primary font-mono uppercase">Identity</span>
                    </div>
                    <div class="space-y-1.5">
                        ${identityHtml}
                    </div>
                </div>
                ` : `
                <p class="text-gray-400 mb-6 max-w-lg">
                    This persona is currently controlling the system's responses, tone, and capabilities.
                </p>
                `}

                <div class="flex gap-3">
                    <button class="px-5 py-2.5 bg-accent-primary text-black font-bold rounded-lg hover:bg-orange-500 transition-colors flex items-center gap-2">
                        <i data-lucide="edit-3" class="w-4 h-4"></i> Edit
                    </button>
                    <!-- <button class="px-5 py-2.5 bg-[#222] text-white rounded-lg hover:bg-[#333] border border-[#333]">Export</button> -->
                </div>
            </div>
        </div>

        <!-- LIST OF OTHERS -->
        <div class="col-span-12 md:col-span-4 space-y-4 max-h-[60vh] overflow-y-auto pr-2">
            <h4 class="text-gray-500 font-medium px-1">Available Personas</h4>
            ${others.map(p => `
                <div class="bg-[#0a0a0a] border border-[#222] hover:border-gray-600 rounded-lg p-4 cursor-pointer transition-all hover:translate-x-1 group"
                     onclick="switchPersona('${p}')">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-3">
                            <i data-lucide="user" class="w-5 h-5 text-gray-600 group-hover:text-white transition-colors"></i>
                            <span class="text-gray-300 font-medium group-hover:text-white">${p}</span>
                        </div>
                        <div class="flex items-center gap-2">
                            ${p !== 'default' ? `<button onclick="event.stopPropagation(); window.deletePersona('${p}')" class="p-1.5 rounded hover:bg-red-500/20 text-gray-500 hover:text-red-400 transition-colors" title="Delete Persona"><i data-lucide="trash-2" class="w-4 h-4"></i></button>` : ''}
                            <i data-lucide="chevron-right" class="w-4 h-4 text-[#333] group-hover:text-white"></i>
                        </div>
                    </div>
                </div>
            `).join('')}
             
             <!-- Add New -->
             <div class="border border-dashed border-[#333] hover:border-accent-primary/50 rounded-lg p-4 flex items-center justify-center cursor-pointer text-gray-600 hover:text-accent-primary transition-colors gap-2" onclick="window.triggerPersonaUpload()">
                <i data-lucide="upload" class="w-4 h-4"></i>
                <span class="text-sm font-medium">Upload Persona</span>
             </div>
        </div>
    `;

    // Add hidden file input for upload

    container.innerHTML = html;

    // Create and append file input element
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.id = 'persona-file-input';
    fileInput.accept = '.md,.txt,.json';
    fileInput.className = 'hidden';
    fileInput.addEventListener('change', handleFileInputChange);
    container.appendChild(fileInput);

    log('info', '[Personas] File input element created and listener attached');

    lucide.createIcons();

    // bind global for onclick
    window.switchPersona = switchPersona;
    window.deletePersona = deletePersona;
    window.closePersonaEditor = closePersonaEditor;
    window.savePersonaEdit = savePersonaEdit;
    window.triggerPersonaUpload = () => {
        const input = document.getElementById('persona-file-input');
        if (input) {
            input.click();
        } else {
            log('error', '[Personas] File input not found!');
        }
    };
}

async function switchPersona(name) {
    if (!confirm(`Switch to persona '${name}'?`)) return;

    try {
        const res = await fetch(`${getApiBase()}/api/personas/${name}/switch`, {
            method: 'PUT'
        });

        if (!res.ok) throw new Error("Switch failed");

        // Reload
        await loadPersonas();

        // Show Toast (Using global helper if available or local)
        // Check if showToast exists in window (from tools.js/shell.js?) 
        // We'll trust shell.js usually logging it or implement simple alert
        // Actually, let's look for toast container
        showToast(`Activated ${name}`, "success");

    } catch (e) {
        alert(e.message);
    }
}

/**
 * Delete a persona
 * Protected: Cannot delete 'default' or currently active persona
 */
async function deletePersona(name) {
    log('info', `[Personas] 🗑️ Delete requested for: ${name}`);

    // Safety checks
    if (name === 'default') {
        showToast("Cannot delete the default persona", "error");
        return;
    }

    if (!confirm(`Are you sure you want to delete persona "${name}"?\n\nThis action cannot be undone.`)) {
        return;
    }

    try {
        showToast(`Deleting "${name}"...`, 'info');

        const res = await fetch(`${getApiBase()}/api/personas/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });

        if (!res.ok) {
            const errorData = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(errorData.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();
        log('info', `[Personas] Delete successful: ${JSON.stringify(data)}`);

        showToast(`Persona "${name}" deleted successfully!`, 'success');

        // Reload personas list
        await loadPersonas();

    } catch (err) {
        log('error', `[Personas] Delete failed: ${err.message}`);
        showToast(`Delete failed: ${err.message}`, 'error');
    }
}

/**
 * ═══════════════════════════════════════════════════════════
 * MODELS
 * ═══════════════════════════════════════════════════════════
 */
async function loadModels() {
    // Guard: page-models is not in the DOM when the Models tab is hidden (Phase 1).
    if (!els.pages.models) return;
    const page = els.pages.models;

    // Inject skeleton structure if empty
    if (!page.querySelector('.model-grid')) {
        page.innerHTML = `
            <h2 class="text-3xl font-light mb-8 border-b border-[#333] pb-4">Models & Intelligence</h2>
            <div class="model-grid grid grid-cols-1 gap-6">
                <div class="bg-[#111] rounded-xl p-8 flex items-center justify-center">
                    <i data-lucide="loader" class="animate-spin text-accent-primary w-8 h-8"></i>
                </div>
            </div>
         `;
        lucide.createIcons();
    }

    // Fetch installed models + effective config + compute routing in parallel
    const [tagsResult, effectiveResult, routingResult, instancesResult] = await Promise.allSettled([
        fetch(`${getApiBase()}/api/tags`),
        fetch(`${getApiBase()}/api/settings/models/effective`),
        fetch(`${getApiBase()}/api/runtime/compute/routing`),
        fetch(`${getApiBase()}/api/runtime/compute/instances`),
    ]);

    let models = [];
    if (tagsResult.status === 'fulfilled' && tagsResult.value.ok) {
        try { models = (await tagsResult.value.json()).models || []; }
        catch (e) { log('error', `Models JSON parse: ${e.message}`); }
    } else {
        log('warn', 'Models Load Warning: failed to fetch /api/tags');
    }

    let effective = {};
    if (effectiveResult.status === 'fulfilled' && effectiveResult.value.ok) {
        try { effective = (await effectiveResult.value.json()).effective || {}; }
        catch (e) { log('error', `Effective config JSON parse: ${e.message}`); }
    } else {
        log('error', 'Models Load Error: failed to fetch /api/settings/models/effective');
    }

    let computeRouting = {};
    if (routingResult.status === 'fulfilled' && routingResult.value.ok) {
        try { computeRouting = await routingResult.value.json(); }
        catch (e) { log('error', `Compute routing JSON parse: ${e.message}`); }
    } else {
        log('warn', 'Models Load Warning: failed to fetch /api/runtime/compute/routing');
    }

    let computeInstances = {};
    if (instancesResult.status === 'fulfilled' && instancesResult.value.ok) {
        try { computeInstances = await instancesResult.value.json(); }
        catch (e) { log('error', `Compute instances JSON parse: ${e.message}`); }
    } else {
        log('warn', 'Models Load Warning: failed to fetch /api/runtime/compute/instances');
    }

    renderModels(models, page.querySelector('.model-grid'), effective, computeRouting, computeInstances);
}

window.testModel = (name) => alert(`Testing capability for ${name} coming soon!`);

// Bind global save
window.saveModelSettings = saveModelSettings;

/**
 * Build <option> list for a model select.
 * If the configured value is not in the installed list, prepend an extra option
 * so the user can see what is configured even if it is not currently installed.
 */
function _modelOptions(models, configuredValue) {
    const installedNames = new Set(models.map(m => m.name));
    let extra = '';
    if (configuredValue && !installedNames.has(configuredValue)) {
        extra = `<option value="${escapeHtml(configuredValue)}">${escapeHtml(configuredValue)} (configured, not installed)</option>`;
    }
    const installed = models
        .map(m => `<option value="${escapeHtml(m.name)}">${escapeHtml(m.name)} (${(m.size / 1e9).toFixed(1)}GB)</option>`)
        .join('');
    return extra + installed;
}

const _ROUTING_ROLES = [
    { key: "thinking", label: "Thinking Layer" },
    { key: "control", label: "Control Layer" },
    { key: "output", label: "Output Layer" },
    { key: "tool_selector", label: "Tool Selector" },
    { key: "embedding", label: "Embedding" },
];

const _LLM_PROVIDER_OPTIONS = ["ollama", "ollama_cloud", "openai", "anthropic"];
const _CLOUD_MODEL_PRESETS = [
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
    "claude-sonnet-4-5",
    "claude-3-7-sonnet-latest",
    "claude-3-5-haiku-latest",
];

function _formatTargetLabel(target, targetLabels = null) {
    if (targetLabels && target && targetLabels[target]) return targetLabels[target];
    if (target === "auto") return "Auto";
    if (target === "cpu") return "CPU";
    if (typeof target === "string" && target.startsWith("gpu")) return target.toUpperCase();
    return String(target || "—");
}

function _gpuSlot(inst) {
    const fromCap = inst?.capability?.gpu_device_id;
    if (fromCap !== undefined && fromCap !== null && String(fromCap).trim() !== "") {
        return String(fromCap).trim();
    }
    const id = String(inst?.id || "");
    const m = id.match(/^gpu(\d+)$/i);
    return m ? m[1] : "?";
}

function _gpuLabelFromInstance(inst) {
    const slot = _gpuSlot(inst);
    const name = String(inst?.capability?.gpu_name || "").trim();
    const backend = String(inst?.capability?.gpu_backend || "").trim().toUpperCase();
    const prefix = `GPU ${slot}`;
    if (name && backend) return `${prefix} - ${name} [${backend}]`;
    if (name) return `${prefix} - ${name}`;
    if (backend) return `${prefix} [${backend}]`;
    return prefix;
}

function _routingOptions(allowedTargets, selected, targetLabels = null) {
    const safeAllowed = Array.isArray(allowedTargets) && allowedTargets.length
        ? allowedTargets
        : ["auto", "cpu"];

    const values = [...safeAllowed];
    if (selected && !values.includes(selected)) values.unshift(selected);

    return values.map((target) => {
        const isSelected = target === selected ? "selected" : "";
        const label = _formatTargetLabel(target, targetLabels);
        return `<option value="${escapeHtml(target)}" ${isSelected}>${escapeHtml(label)}</option>`;
    }).join("");
}

function _providerOptions(selected) {
    const normalized = String(selected || "ollama").toLowerCase();
    return _LLM_PROVIDER_OPTIONS.map((name) => {
        const isSelected = name === normalized ? "selected" : "";
        const label = name === "ollama"
            ? "Ollama (Local)"
            : name === "ollama_cloud"
                ? "Ollama Cloud"
                : name === "openai"
                    ? "OpenAI (ChatGPT)"
                    : "Anthropic (Claude)";
        return `<option value="${name}" ${isSelected}>${label}</option>`;
    }).join("");
}

function _modelPresetOptions(models, currentValue = "") {
    const names = new Set();
    for (const m of (models || [])) {
        const n = String(m?.name || "").trim();
        if (n) names.add(n);
    }
    for (const preset of _CLOUD_MODEL_PRESETS) names.add(preset);
    if (currentValue) names.add(String(currentValue).trim());
    const sorted = [...names].filter(Boolean).sort((a, b) => a.localeCompare(b));
    return [
        `<option value="">Pick preset...</option>`,
        ...sorted.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`),
    ].join("");
}

function _routeSummary(routeInfo, targetLabels = null) {
    if (!routeInfo || typeof routeInfo !== "object") return "Effective: —";
    const eff = routeInfo.effective_target || "—";
    const reason = routeInfo.fallback_reason ? ` · fallback=${routeInfo.fallback_reason}` : "";
    return `Effective: ${_formatTargetLabel(eff, targetLabels)}${reason}`;
}

function _renderInstanceStatus(instancesPayload) {
    const instances = Array.isArray(instancesPayload?.instances) ? instancesPayload.instances : [];
    if (!instances.length) {
        return `<div class="text-xs text-gray-500">No managed compute instances available.</div>`;
    }
    return instances.map((inst) => {
        const id = inst.id || "unknown";
        const endpoint = inst.endpoint || "—";
        const running = Boolean(inst.running);
        const healthy = Boolean(inst.health?.ok);
        const isGpu = String(inst?.target || "") === "gpu";
        const friendly = isGpu ? _gpuLabelFromInstance(inst) : "CPU";
        const statusClass = running && healthy
            ? "text-green-400"
            : running
                ? "text-yellow-400"
                : "text-gray-500";
        const status = running && healthy ? "running/healthy" : running ? "running/unhealthy" : "stopped";
        const action = running ? "stop" : "start";
        const actionLabel = running ? "Stop" : "Start";
        const actionButtonClass = running
            ? "bg-red-500/20 text-red-300 hover:bg-red-500/30 border-red-500/40"
            : "bg-green-500/20 text-green-300 hover:bg-green-500/30 border-green-500/40";
        return `
            <div class="bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-xs">
                <div class="flex items-center justify-between">
                    <span class="text-gray-300">${escapeHtml(friendly)}</span>
                    <span class="${statusClass}">${status}</span>
                </div>
                <div class="text-gray-500 mt-1 font-mono">id: ${escapeHtml(id)}</div>
                <div class="text-gray-500 mt-1">${escapeHtml(endpoint)}</div>
                <div class="mt-2 flex justify-end">
                    <button
                        class="compute-instance-action px-2 py-1 text-[11px] rounded border transition-colors ${actionButtonClass}"
                        data-instance-id="${escapeHtml(id)}"
                        data-action="${escapeHtml(action)}"
                    >
                        ${actionLabel}
                    </button>
                </div>
            </div>
        `;
    }).join("");
}

function _buildTargetLabels(instancesPayload) {
    const out = { auto: "Auto", cpu: "CPU" };
    const instances = Array.isArray(instancesPayload?.instances) ? instancesPayload.instances : [];
    for (const inst of instances) {
        const id = String(inst?.id || "").trim();
        if (!id || id === "cpu") continue;
        out[id] = _gpuLabelFromInstance(inst);
    }
    return out;
}

function renderModels(models, container, effective, computeRouting = {}, computeInstances = {}) {
    if (!container) return;
    effective = effective || {};

    const thinkingVal  = effective.THINKING_MODEL ? effective.THINKING_MODEL.value : "";
    const controlVal   = effective.CONTROL_MODEL ? effective.CONTROL_MODEL.value : "";
    const outputVal    = effective.OUTPUT_MODEL ? effective.OUTPUT_MODEL.value : "";
    const embeddingVal = effective.EMBEDDING_MODEL ? effective.EMBEDDING_MODEL.value : "";
    const thinkingProvider = effective.THINKING_PROVIDER ? effective.THINKING_PROVIDER.value : "ollama";
    const controlProvider = effective.CONTROL_PROVIDER ? effective.CONTROL_PROVIDER.value : "ollama";
    const outputProvider = effective.OUTPUT_PROVIDER ? effective.OUTPUT_PROVIDER.value : "ollama";

    const allowedTargets = (
        Array.isArray(computeRouting.allowed_targets) && computeRouting.allowed_targets.length
            ? computeRouting.allowed_targets
            : (Array.isArray(computeInstances.allowed_targets) && computeInstances.allowed_targets.length
                ? computeInstances.allowed_targets
                : ["auto", "cpu"])
    );
    const layerRouting = (computeRouting.layer_routing && typeof computeRouting.layer_routing === "object")
        ? computeRouting.layer_routing
        : {};
    const effectiveRouting = (computeRouting.effective && typeof computeRouting.effective === "object")
        ? computeRouting.effective
        : {};
    const targetLabels = _buildTargetLabels(computeInstances);
    const allowedTargetsFriendly = allowedTargets.map((t) => _formatTargetLabel(t, targetLabels));

    const sourceLabel = (key) => {
        const src = effective[key] ? effective[key].source : 'default';
        const colors = { override: 'text-accent-primary', env: 'text-blue-400', default: 'text-gray-500' };
        return `<span class="text-xs ${colors[src] || 'text-gray-500'} font-mono ml-1">[${src}]</span>`;
    };

    const buildLayerCard = ({
        title,
        modelId,
        modelVal,
        modelSourceKey,
        providerId = "",
        providerVal = "",
        providerSourceKey = "",
        description = "",
        includeProvider = true,
    }) => `
        <div class="models-layer-card">
            <h4>${escapeHtml(title)}</h4>
            ${includeProvider ? `
                <label class="models-label">Provider ${sourceLabel(providerSourceKey)}</label>
                <select id="${providerId}" class="models-select">
                    ${_providerOptions(providerVal)}
                </select>
            ` : `
                <label class="models-label">Provider</label>
                <div class="models-provider-fixed">Ollama (local)</div>
            `}
            <label class="models-label">Model ${sourceLabel(modelSourceKey)}</label>
            <input
                id="${modelId}"
                class="models-input"
                type="text"
                value="${escapeHtml(modelVal || "")}"
                placeholder="Enter model id (e.g. gpt-4.1 / claude-sonnet-4-5 / ministral-3:8b)"
            />
            <select id="${modelId}-preset" class="models-select">
                ${_modelPresetOptions(models, modelVal)}
            </select>
            <p class="models-help">${escapeHtml(description)}</p>
        </div>
    `;

    const html = `
        <div class="models-admin">
            <header class="models-head">
                <h3><i data-lucide="brain-circuit"></i> Model & Provider Routing</h3>
                <button onclick="saveModelSettings()" class="models-btn primary">
                    <i data-lucide="save" class="w-4 h-4"></i>
                    Save Model Routing
                </button>
            </header>

            <section class="models-grid-top">
                <article class="models-card">
                    <h3>Cognitive Layers</h3>
                    <div class="models-layer-grid">
                        ${buildLayerCard({
                            title: "Thinking Layer",
                            modelId: "setting-thinking-model",
                            modelVal: thinkingVal,
                            modelSourceKey: "THINKING_MODEL",
                            providerId: "setting-thinking-provider",
                            providerVal: thinkingProvider,
                            providerSourceKey: "THINKING_PROVIDER",
                            description: "Planning, decomposition, long-chain reasoning.",
                            includeProvider: true,
                        })}
                        ${buildLayerCard({
                            title: "Control Layer",
                            modelId: "setting-control-model",
                            modelVal: controlVal,
                            modelSourceKey: "CONTROL_MODEL",
                            providerId: "setting-control-provider",
                            providerVal: controlProvider,
                            providerSourceKey: "CONTROL_PROVIDER",
                            description: "Safety, routing checks, policy enforcement.",
                            includeProvider: true,
                        })}
                        ${buildLayerCard({
                            title: "Output Layer",
                            modelId: "setting-output-model",
                            modelVal: outputVal,
                            modelSourceKey: "OUTPUT_MODEL",
                            providerId: "setting-output-provider",
                            providerVal: outputProvider,
                            providerSourceKey: "OUTPUT_PROVIDER",
                            description: "Final user response generation.",
                            includeProvider: true,
                        })}
                        ${buildLayerCard({
                            title: "Embedding Layer",
                            modelId: "setting-embedding-model",
                            modelVal: embeddingVal,
                            modelSourceKey: "EMBEDDING_MODEL",
                            description: "Semantic retrieval and memory indexing.",
                            includeProvider: false,
                        })}
                    </div>

                    <div class="models-note">
                        Cloud providers require API keys (<code>OPENAI_API_KEY</code> / <code>ANTHROPIC_API_KEY</code> / <code>OLLAMA_API_KEY</code> or <code>OLLAMA</code>) via env or encrypted secrets.
                    </div>
                </article>

                <article class="models-card">
                    <h3>Compute Target Routing</h3>
                    <div class="models-routing-grid">
                        ${_ROUTING_ROLES.map((role) => {
                            const requested = layerRouting[role.key] || "auto";
                            const routeInfo = effectiveRouting[role.key] || {};
                            return `
                                <div class="models-routing-item">
                                    <label class="models-label">${role.label}</label>
                                    <select id="setting-route-${role.key}" class="models-select">
                                        ${_routingOptions(allowedTargets, requested, targetLabels)}
                                    </select>
                                    <p class="models-help">${escapeHtml(_routeSummary(routeInfo, targetLabels))}</p>
                                </div>
                            `;
                        }).join("")}
                    </div>
                    <div class="models-note">
                        Allowed targets: ${escapeHtml(allowedTargetsFriendly.join(" | "))}
                    </div>
                    <div class="models-instance-grid">
                        ${_renderInstanceStatus(computeInstances)}
                    </div>
                    <div class="models-actions">
                        <button id="save-compute-routing" class="models-btn">
                            <i data-lucide="save" class="w-4 h-4"></i>
                            Save Compute Routing
                        </button>
                    </div>
                </article>
            </section>

            <section class="models-card">
                <h3>Installed Local Models (Ollama)</h3>
                <div class="models-installed-grid">
                    ${models.map(m => `
                        <div class="models-installed-item">
                            <span>${escapeHtml(m.name)}</span>
                            <small>${(m.size / 1e9).toFixed(1)} GB</small>
                        </div>
                    `).join('') || '<div class="models-note">No local models detected.</div>'}
                </div>
            </section>
        </div>
    `;

    container.innerHTML = html;
    lucide.createIcons();

    const presetToInput = {
        "setting-thinking-model-preset": "setting-thinking-model",
        "setting-control-model-preset": "setting-control-model",
        "setting-output-model-preset": "setting-output-model",
        "setting-embedding-model-preset": "setting-embedding-model",
    };
    for (const [presetId, inputId] of Object.entries(presetToInput)) {
        const preset = document.getElementById(presetId);
        const input = document.getElementById(inputId);
        if (!preset || !input) continue;
        preset.addEventListener("change", () => {
            const next = String(preset.value || "").trim();
            if (!next) return;
            input.value = next;
        });
    }

    const saveRoutingBtn = document.getElementById("save-compute-routing");
    if (saveRoutingBtn) {
        saveRoutingBtn.addEventListener("click", saveComputeRoutingSettings);
    }

    container.querySelectorAll(".compute-instance-action").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const instanceId = String(btn.dataset.instanceId || "").trim();
            const action = String(btn.dataset.action || "").trim().toLowerCase();
            if (!instanceId || !["start", "stop"].includes(action)) return;
            await controlComputeInstance(instanceId, action);
        });
    });
}

async function saveModelSettings() {
    const val = (id) => {
        const el = document.getElementById(id);
        return el ? el.value.trim() : '';
    };
    const changes = {};
    const thinking = val('setting-thinking-model');
    const control  = val('setting-control-model');
    const output   = val('setting-output-model');
    const embedding = val('setting-embedding-model');
    const thinkingProvider = val('setting-thinking-provider').toLowerCase();
    const controlProvider = val('setting-control-provider').toLowerCase();
    const outputProvider = val('setting-output-provider').toLowerCase();
    if (thinking) changes.THINKING_MODEL = thinking;
    if (control)  changes.CONTROL_MODEL  = control;
    if (output)   changes.OUTPUT_MODEL   = output;
    if (embedding) changes.EMBEDDING_MODEL = embedding;
    if (thinkingProvider) changes.THINKING_PROVIDER = thinkingProvider;
    if (controlProvider) changes.CONTROL_PROVIDER = controlProvider;
    if (outputProvider) changes.OUTPUT_PROVIDER = outputProvider;

    if (!Object.keys(changes).length) {
        showToast('Nothing to save', 'info');
        return;
    }

    showToast('Saving settings...', 'info');

    try {
        const res = await fetch(`${getApiBase()}/api/settings/models`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(changes),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        window.dispatchEvent(new CustomEvent('jarvis:model-settings-updated', {
            detail: { ...changes, source: 'settings-models' }
        }));
        showToast('Configuration saved!', 'success');
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

async function saveComputeRoutingSettings() {
    const layerRouting = {};
    for (const role of _ROUTING_ROLES) {
        const el = document.getElementById(`setting-route-${role.key}`);
        if (!el || !el.value) continue;
        layerRouting[role.key] = el.value;
    }

    if (!Object.keys(layerRouting).length) {
        showToast('Nothing to save', 'info');
        return;
    }

    showToast('Saving compute routing...', 'info');
    try {
        const res = await fetch(`${getApiBase()}/api/runtime/compute/routing`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ layer_routing: layerRouting }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        showToast('Compute routing saved!', 'success');
        await loadModels();
    } catch (e) {
        showToast(`Routing save failed: ${e.message}`, 'error');
    }
}

async function controlComputeInstance(instanceId, action) {
    const normalizedAction = action === "stop" ? "stop" : "start";
    const endpoint = `${getApiBase()}/api/runtime/compute/instances/${encodeURIComponent(instanceId)}/${normalizedAction}`;
    showToast(`${normalizedAction === "start" ? "Starting" : "Stopping"} ${instanceId}...`, "info");
    try {
        const res = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        showToast(`Instance ${instanceId} ${normalizedAction} request accepted`, "success");
        await loadModels();
    } catch (e) {
        showToast(`Instance ${instanceId} ${normalizedAction} failed: ${e.message}`, "error");
    }
}

/**
 * ═══════════════════════════════════════════════════════════
 * PLUGINS (TRION)
 * ═══════════════════════════════════════════════════════════
 */
async function loadPlugins() {
    const container = document.getElementById('plugins-container');
    if (!container) return;

    if (!window.TRIONBridge) {
        container.innerHTML = `<div class="p-4 text-red-400">TRION Bridge not connected. Plugins unavailable.</div>`;
        return;
    }

    container.innerHTML = `
        <div class="flex items-center text-gray-500">
            <i data-lucide="loader" class="animate-spin w-5 h-5 mr-3"></i>
            Fetching plugins from runtime...
        </div>
    `;
    lucide.createIcons();

    try {
        const plugins = await window.TRIONBridge.getPlugins(); // request('plugin:list')
        renderPlugins(plugins, container);
    } catch (e) {
        container.innerHTML = `<div class="p-4 text-red-400">Failed to load plugins: ${e.message}</div>`;
    }
}

function renderPlugins(plugins, container) {
    if (!plugins || plugins.length === 0) {
        container.innerHTML = `<div class="p-4 text-gray-500">No plugins installed in TRION Runtime.</div>`;
        return;
    }

    const html = plugins.map(p => `
        <div class="bg-[#111] border border-dark-border rounded-xl p-6 flex items-start justify-between">
            <div class="flex items-start gap-4">
                <div class="w-12 h-12 bg-dark-bg rounded-lg flex items-center justify-center border border-dark-border">
                    <i data-lucide="puzzle" class="w-6 h-6 text-accent-primary"></i>
                </div>
                <div>
                    <h3 class="text-lg font-bold text-gray-200">${p.manifest?.name || p.manifest?.id} <span class="text-xs text-gray-500 font-normal ml-2">v${p.manifest?.version || '1.0.0'}</span></h3>
                    <p class="text-sm text-gray-400 mt-1">${p.manifest?.description || 'No description available.'}</p>
                    <div class="flex flex-wrap gap-2 mt-3">
                        ${(p.manifest?.permissions ? Object.keys(p.manifest.permissions) : [] || []).map(c => `<span class="bg-dark-bg border border-dark-border px-2 py-1 rounded text-xs text-gray-500 font-mono">${c}</span>`).join('')}
                    </div>
                </div>
            </div>
            
            <div class="flex items-center gap-3">
                <span class="text-xs font-mono uppercase ${p.enabled ? 'text-green-500' : 'text-gray-600'}">
                    ${p.enabled ? 'Enabled' : 'Disabled'}
                </span>
                <button onclick="togglePlugin('${p.manifest?.id}', ${!p.enabled})" 
                    class="w-12 h-6 rounded-full transition-colors relative ${p.enabled ? 'bg-accent-primary' : 'bg-gray-700'}"
                    title="${p.enabled ? 'Disable' : 'Enable'}">
                    <div class="absolute top-1 left-1 bg-white w-4 h-4 rounded-full transition-transform ${p.enabled ? 'translate-x-6' : 'translate-x-0'}"></div>
                </button>
            </div>
        </div>
    `).join('');

    container.innerHTML = html;
    lucide.createIcons();
}

window.togglePlugin = async (id, shouldEnable) => {
    try {
        if (shouldEnable) {
            await window.TRIONBridge.enablePlugin(id);
            showToast(`Enabled ${id}`, 'success');
        } else {
            await window.TRIONBridge.disablePlugin(id);
            showToast(`Disabled ${id}`, 'success');
        }
        // Refresh
        loadPlugins();
    } catch (e) {
        showToast(`Operation failed: ${e.message}`, 'error');
    }
};

/**
 * Toast Helper
 */
function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    const colors = { info: 'border-accent-primary', success: 'border-green-500 text-green-400', error: 'border-red-500' };
    toast.className = `px-4 py-3 rounded-lg border-l-4 shadow-xl flex items-center gap-3 transform transition-all duration-300 translate-y-2 opacity-0 bg-dark-card ${colors[type] || colors.info} text-gray-200`;
    toast.innerHTML = `<span class="font-mono text-sm">${msg}</span>`;
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.remove('translate-y-2', 'opacity-0'));
    setTimeout(() => { toast.classList.add('translate-y-2', 'opacity-0'); setTimeout(() => toast.remove(), 300); }, 3000);
}


// =============================================================================
// MASTER ORCHESTRATOR SETTINGS
// =============================================================================

/**
 * Load Master Orchestrator Settings
 */
async function loadMasterSettings() {
    try {
        const response = await fetch(`${getApiBase()}/api/settings/master`);
        const settings = await response.json();
        
        // Update UI
        document.getElementById('master-enabled').checked = settings.enabled;
        document.getElementById('master-thinking').checked = settings.use_thinking_layer;
        document.getElementById('master-max-loops').value = settings.max_loops;
        document.getElementById('master-max-loops-value').textContent = settings.max_loops;
        document.getElementById('master-threshold').value = settings.completion_threshold;
        document.getElementById('master-threshold-value').textContent = settings.completion_threshold;
        
        log('info', 'Master settings loaded');
    } catch (error) {
        log('error', `Failed to load master settings: ${error.message}`);
    }
}

/**
 * Save Master Orchestrator Settings
 */
async function saveMasterSettings() {
    const settings = {
        enabled: document.getElementById('master-enabled').checked,
        use_thinking_layer: document.getElementById('master-thinking').checked,
        max_loops: parseInt(document.getElementById('master-max-loops').value),
        completion_threshold: parseInt(document.getElementById('master-threshold').value)
    };
    
    try {
        const response = await fetch(`${getApiBase()}/api/settings/master`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        if (response.ok) {
            showToast('Master settings saved!', 'success');
            log('info', 'Master settings saved', settings);
        } else {
            throw new Error('Failed to save');
        }
    } catch (error) {
        log('error', `Failed to save master settings: ${error.message}`);
        showToast('Failed to save settings', 'error');
    }
}

/**
 * Setup Master Settings Event Handlers
 */
function setupMasterSettingsHandlers() {
    // Range sliders update value display
    const maxLoopsSlider = document.getElementById('master-max-loops');
    const thresholdSlider = document.getElementById('master-threshold');
    
    if (maxLoopsSlider) {
        maxLoopsSlider.addEventListener('input', (e) => {
            document.getElementById('master-max-loops-value').textContent = e.target.value;
        });
    }
    
    if (thresholdSlider) {
        thresholdSlider.addEventListener('input', (e) => {
            document.getElementById('master-threshold-value').textContent = e.target.value;
        });
    }
    
    // Save button
    const saveButton = document.getElementById('save-master-settings');
    if (saveButton) {
        saveButton.addEventListener('click', saveMasterSettings);
    }
    
    // Load initial settings when Advanced page is shown
    const advancedNav = document.querySelector('.settings-category[data-category="advanced"]');
    if (advancedNav) {
        advancedNav.addEventListener('click', () => {
            // Small delay to ensure UI is rendered
            setTimeout(loadMasterSettings, 100);
        });
    }
    
    log('info', 'Master settings handlers initialized');
}

// ═══════════════════════════════════════════════════════
// CONTEXT COMPRESSION SETTINGS
// ═══════════════════════════════════════════════════════

async function loadCompressionSettings() {
    try {
        const r = await fetch(`${getApiBase()}/api/settings/compression`);
        const s = await r.json();
        const enabledEl = document.getElementById('compression-enabled');
        const modeEl = document.getElementById('compression-mode');
        if (enabledEl) enabledEl.checked = s.enabled;
        if (modeEl) modeEl.value = s.mode;
        log('info', 'Compression settings loaded', s);
    } catch (e) {
        log('error', `Failed to load compression settings: ${e.message}`);
    }
}

async function saveCompressionSettings() {
    const enabledEl = document.getElementById('compression-enabled');
    const modeEl = document.getElementById('compression-mode');
    const payload = {
        enabled: enabledEl ? enabledEl.checked : true,
        mode: modeEl ? modeEl.value : 'sync',
    };
    try {
        const r = await fetch(`${getApiBase()}/api/settings/compression`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (r.ok) {
            showToast('Compression settings saved!', 'success');
        } else {
            throw new Error('Save failed');
        }
    } catch (e) {
        showToast('Failed to save compression settings', 'error');
    }
}

function setupCompressionHandlers() {
    const saveBtn = document.getElementById('save-compression-settings');
    if (saveBtn) saveBtn.addEventListener('click', saveCompressionSettings);

    // Load when Advanced tab is opened
    const advancedNav = document.querySelector('.settings-category[data-category="advanced"]');
    if (advancedNav) {
        advancedNav.addEventListener('click', () => {
            setTimeout(loadCompressionSettings, 150);
        });
    }
}

// ═══════════════════════════════════════════════════════
// EMBEDDING RUNTIME (Phase 4 — GPU/CPU routing)
// ═══════════════════════════════════════════════════════

async function loadEmbeddingRuntime() {
    try {
        const r = await fetch(`${getApiBase()}/api/settings/embeddings/runtime`);
        if (!r.ok) return;
        const d = await r.json();
        const eff = d.effective || {};
        const modeEl = document.getElementById('embedding-runtime-policy');
        const policyEl = document.getElementById('embedding-fallback-policy');
        const policyValueEl = document.getElementById('embedding-effective-policy');
        const policySourceEl = document.getElementById('embedding-policy-source');
        const targetEl = document.getElementById('embedding-effective-target');
        const reasonEl = document.getElementById('embedding-effective-reason');
        const policyEntry = eff.embedding_runtime_policy || {};
        if (modeEl) modeEl.value = policyEntry.value || (eff.EMBEDDING_EXECUTION_MODE || {}).value || 'auto';
        if (policyEl) policyEl.value = (eff.EMBEDDING_FALLBACK_POLICY || {}).value || 'best_effort';
        if (policyValueEl) policyValueEl.textContent = (d.runtime && d.runtime.active_policy) || policyEntry.value || 'auto';
        if (policySourceEl) policySourceEl.textContent = policyEntry.source || 'default';
        if (targetEl && d.runtime) targetEl.textContent = d.runtime.target || '—';
        if (reasonEl && d.runtime) reasonEl.textContent = d.runtime.reason || '';
        log('info', '[EmbeddingRuntime] loaded', d.runtime);
    } catch (e) {
        log('error', `[EmbeddingRuntime] load failed: ${e.message}`);
    }
}

async function saveEmbeddingRuntime() {
    const modeEl = document.getElementById('embedding-runtime-policy');
    const policyEl = document.getElementById('embedding-fallback-policy');
    const payload = {
        embedding_runtime_policy: modeEl ? modeEl.value : 'auto',
        EMBEDDING_FALLBACK_POLICY: policyEl ? policyEl.value : 'best_effort',
    };
    try {
        const r = await fetch(`${getApiBase()}/api/settings/embeddings/runtime`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (r.ok) {
            showToast('Embedding settings saved!', 'success');
            await loadEmbeddingRuntime();
        } else {
            const err = await r.json().catch(() => ({}));
            showToast(`Save failed: ${err.detail || r.status}`, 'error');
        }
    } catch (e) {
        showToast('Failed to save embedding settings', 'error');
    }
}

function setupEmbeddingRuntimeHandlers() {
    const saveBtn = document.getElementById('save-embedding-runtime');
    if (saveBtn) saveBtn.addEventListener('click', saveEmbeddingRuntime);

    // Load when Advanced tab is opened
    const advancedNav = document.querySelector('.settings-category[data-category="advanced"]');
    if (advancedNav) {
        advancedNav.addEventListener('click', () => {
            setTimeout(loadEmbeddingRuntime, 150);
        });
    }
}

// ═══════════════════════════════════════════════════════
// AUTONOMY CRON GUARDRAILS
// ═══════════════════════════════════════════════════════

const CRON_POLICY_FIELDS = [
    { key: "AUTONOMY_CRON_MAX_JOBS", inputId: "cron-policy-max-jobs", sourceId: "cron-policy-max-jobs-source", type: "int" },
    { key: "AUTONOMY_CRON_MAX_JOBS_PER_CONVERSATION", inputId: "cron-policy-max-jobs-per-conversation", sourceId: "cron-policy-max-jobs-per-conversation-source", type: "int" },
    { key: "AUTONOMY_CRON_MIN_INTERVAL_S", inputId: "cron-policy-min-interval-s", sourceId: "cron-policy-min-interval-s-source", type: "int" },
    { key: "AUTONOMY_CRON_MAX_PENDING_RUNS", inputId: "cron-policy-max-pending-runs", sourceId: "cron-policy-max-pending-runs-source", type: "int" },
    { key: "AUTONOMY_CRON_MAX_PENDING_RUNS_PER_JOB", inputId: "cron-policy-max-pending-runs-per-job", sourceId: "cron-policy-max-pending-runs-per-job-source", type: "int" },
    { key: "AUTONOMY_CRON_MANUAL_RUN_COOLDOWN_S", inputId: "cron-policy-manual-run-cooldown-s", sourceId: "cron-policy-manual-run-cooldown-s-source", type: "int" },
    { key: "AUTONOMY_CRON_TRION_MIN_INTERVAL_S", inputId: "cron-policy-trion-min-interval-s", sourceId: "cron-policy-trion-min-interval-s-source", type: "int" },
    { key: "AUTONOMY_CRON_TRION_MAX_LOOPS", inputId: "cron-policy-trion-max-loops", sourceId: "cron-policy-trion-max-loops-source", type: "int" },
    { key: "AUTONOMY_CRON_TRION_SAFE_MODE", inputId: "cron-policy-trion-safe-mode", sourceId: "cron-policy-trion-safe-mode-source", type: "bool" },
    { key: "AUTONOMY_CRON_TRION_REQUIRE_APPROVAL_FOR_RISKY", inputId: "cron-policy-trion-require-approval", sourceId: "cron-policy-trion-require-approval-source", type: "bool" },
];

async function loadAutonomyCronPolicy() {
    try {
        const r = await fetch(`${getApiBase()}/api/settings/autonomy/cron-policy`);
        if (!r.ok) return;
        const d = await r.json();
        const eff = d.effective || {};
        CRON_POLICY_FIELDS.forEach(({ key, inputId, sourceId, type }) => {
            const entry = eff[key] || {};
            const input = document.getElementById(inputId);
            const source = document.getElementById(sourceId);
            if (input) {
                if (type === "bool") input.checked = Boolean(entry.value);
                else input.value = Number(entry.value ?? "");
            }
            if (source) source.textContent = entry.source || "default";
        });
        log('info', '[CronPolicy] loaded', d);
    } catch (e) {
        log('error', `[CronPolicy] load failed: ${e.message}`);
    }
}

async function saveAutonomyCronPolicy() {
    const payload = {};
    for (const { key, inputId, type } of CRON_POLICY_FIELDS) {
        const input = document.getElementById(inputId);
        if (!input) continue;
        if (type === "bool") {
            payload[key] = Boolean(input.checked);
            continue;
        }
        const value = Number(input.value);
        if (!Number.isFinite(value)) {
            showToast(`Invalid value for ${key}`, 'error');
            return;
        }
        payload[key] = Math.trunc(value);
    }

    try {
        const r = await fetch(`${getApiBase()}/api/settings/autonomy/cron-policy`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (r.ok) {
            showToast('Cron guardrails saved (restart admin-api to apply).', 'success');
            await loadAutonomyCronPolicy();
        } else {
            const err = await r.json().catch(() => ({}));
            showToast(`Save failed: ${err.detail || err.error || r.status}`, 'error');
        }
    } catch (e) {
        showToast('Failed to save cron guardrails', 'error');
    }
}

function setupAutonomyCronPolicyHandlers() {
    const saveBtn = document.getElementById('save-cron-policy-settings');
    if (saveBtn) saveBtn.addEventListener('click', saveAutonomyCronPolicy);

    const advancedNav = document.querySelector('.settings-category[data-category="advanced"]');
    if (advancedNav) {
        advancedNav.addEventListener('click', () => {
            setTimeout(loadAutonomyCronPolicy, 180);
        });
    }
}

// ═══════════════════════════════════════════════════════
// GITHUB REFERENCE COLLECTIONS (Cronjobs | Skills | Blueprints)
// ═══════════════════════════════════════════════════════

const REFERENCE_LINK_CATEGORIES = ["cronjobs", "skills", "blueprints"];
let referenceLinksState = {
    activeTab: "cronjobs",
    collections: {
        cronjobs: [],
        skills: [],
        blueprints: [],
    },
};

function escapeAttr(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function _emptyReferenceCollections() {
    return {
        cronjobs: [],
        skills: [],
        blueprints: [],
    };
}

function _normalizeReferenceCollections(raw) {
    const out = _emptyReferenceCollections();
    const input = raw && typeof raw === "object" ? raw : {};
    for (const category of REFERENCE_LINK_CATEGORIES) {
        const rows = Array.isArray(input[category]) ? input[category] : [];
        out[category] = rows.map((entry) => ({
            name: String((entry && entry.name) || "").trim(),
            url: String((entry && entry.url) || "").trim(),
            description: String((entry && entry.description) || "").trim(),
            enabled: entry && entry.enabled === false ? false : true,
            read_only: true,
        }));
    }
    return out;
}

function _referenceTabLabel(category) {
    if (category === "cronjobs") return "CRONJOBS";
    if (category === "skills") return "SKILLS";
    return "BLUEPRINTS";
}

function renderReferenceLinksTabs() {
    const tabs = document.querySelectorAll('.reference-links-tab');
    tabs.forEach((tab) => {
        const isActive = tab.dataset.tab === referenceLinksState.activeTab;
        tab.classList.toggle('bg-accent-primary/20', isActive);
        tab.classList.toggle('text-accent-primary', isActive);
        tab.classList.toggle('bg-dark-hover', !isActive);
        tab.classList.toggle('text-gray-400', !isActive);
    });
}

function updateReferenceLinkField(index, field, value) {
    const category = referenceLinksState.activeTab;
    const entries = referenceLinksState.collections[category] || [];
    if (index < 0 || index >= entries.length) return;
    entries[index][field] = value;
}

function removeReferenceLinkRow(index) {
    const category = referenceLinksState.activeTab;
    const entries = referenceLinksState.collections[category] || [];
    if (index < 0 || index >= entries.length) return;
    entries.splice(index, 1);
    renderReferenceLinksRows();
}

function renderReferenceLinksRows() {
    const rowsEl = document.getElementById('reference-links-rows');
    if (!rowsEl) return;

    const category = referenceLinksState.activeTab;
    const entries = referenceLinksState.collections[category] || [];

    if (!entries.length) {
        rowsEl.innerHTML = `<tr><td colspan="6" class="px-3 py-4 text-center text-gray-500">No ${_referenceTabLabel(category)} links yet.</td></tr>`;
        return;
    }

    rowsEl.innerHTML = entries.map((entry, idx) => `
        <tr class="border-b border-dark-border/60">
            <td class="px-3 py-2 align-top">
                <input
                    class="reference-link-input w-full bg-dark-bg border border-dark-border rounded px-2 py-1 text-sm"
                    data-index="${idx}"
                    data-field="name"
                    placeholder="Display name"
                    value="${escapeAttr(entry.name)}"
                />
            </td>
            <td class="px-3 py-2 align-top">
                <input
                    class="reference-link-input w-full bg-dark-bg border border-dark-border rounded px-2 py-1 text-xs font-mono"
                    data-index="${idx}"
                    data-field="url"
                    placeholder="https://github.com/org/repo"
                    value="${escapeAttr(entry.url)}"
                />
            </td>
            <td class="px-3 py-2 align-top">
                <input
                    class="reference-link-input w-full bg-dark-bg border border-dark-border rounded px-2 py-1 text-sm"
                    data-index="${idx}"
                    data-field="description"
                    placeholder="Optional note"
                    value="${escapeAttr(entry.description)}"
                />
            </td>
            <td class="px-3 py-2 text-center align-top">
                <input
                    type="checkbox"
                    class="reference-link-checkbox accent-accent-primary"
                    data-index="${idx}"
                    data-field="enabled"
                    ${entry.enabled ? "checked" : ""}
                />
            </td>
            <td class="px-3 py-2 align-top text-xs text-cyan-300">
                read_only
            </td>
            <td class="px-3 py-2 text-right align-top">
                <button
                    class="reference-link-remove px-2 py-1 text-xs rounded bg-red-500/15 text-red-300 hover:bg-red-500/25"
                    data-index="${idx}"
                >
                    Remove
                </button>
            </td>
        </tr>
    `).join('');

    rowsEl.querySelectorAll('.reference-link-input').forEach((el) => {
        el.addEventListener('input', (event) => {
            const index = Number(event.target.dataset.index || "-1");
            const field = String(event.target.dataset.field || "");
            updateReferenceLinkField(index, field, String(event.target.value || ""));
        });
    });

    rowsEl.querySelectorAll('.reference-link-checkbox').forEach((el) => {
        el.addEventListener('change', (event) => {
            const index = Number(event.target.dataset.index || "-1");
            const field = String(event.target.dataset.field || "");
            updateReferenceLinkField(index, field, Boolean(event.target.checked));
        });
    });

    rowsEl.querySelectorAll('.reference-link-remove').forEach((el) => {
        el.addEventListener('click', () => {
            const index = Number(el.dataset.index || "-1");
            removeReferenceLinkRow(index);
        });
    });
}

function addReferenceLinkRow() {
    const category = referenceLinksState.activeTab;
    if (!referenceLinksState.collections[category]) {
        referenceLinksState.collections[category] = [];
    }
    referenceLinksState.collections[category].push({
        name: "",
        url: "",
        description: "",
        enabled: true,
        read_only: true,
    });
    renderReferenceLinksRows();
}

async function loadReferenceLinksSettings() {
    try {
        const r = await fetch(`${getApiBase()}/api/settings/reference-links`);
        if (!r.ok) return;
        const d = await r.json();
        referenceLinksState.collections = _normalizeReferenceCollections(d.collections || {});
        if (!REFERENCE_LINK_CATEGORIES.includes(referenceLinksState.activeTab)) {
            referenceLinksState.activeTab = REFERENCE_LINK_CATEGORIES[0];
        }
        renderReferenceLinksTabs();
        renderReferenceLinksRows();
        log('info', '[ReferenceLinks] loaded');
    } catch (e) {
        log('error', `[ReferenceLinks] load failed: ${e.message}`);
    }
}

async function saveReferenceLinksSettings() {
    const payload = _normalizeReferenceCollections(referenceLinksState.collections);

    for (const category of REFERENCE_LINK_CATEGORIES) {
        const rows = payload[category] || [];
        for (let idx = 0; idx < rows.length; idx += 1) {
            const entry = rows[idx];
            if (!entry.name || !entry.url) {
                showToast(`Missing name/url in ${_referenceTabLabel(category)} row ${idx + 1}`, 'error');
                return;
            }
        }
    }

    try {
        const r = await fetch(`${getApiBase()}/api/settings/reference-links`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (r.ok) {
            const d = await r.json();
            referenceLinksState.collections = _normalizeReferenceCollections(d.collections || payload);
            renderReferenceLinksRows();
            showToast('Reference collections saved!', 'success');
        } else {
            const err = await r.json().catch(() => ({}));
            showToast(`Save failed: ${err.detail || err.error || r.status}`, 'error');
        }
    } catch (e) {
        showToast('Failed to save reference collections', 'error');
    }
}

function setupReferenceLinksSettingsHandlers() {
    const saveBtn = document.getElementById('save-reference-links-settings');
    if (saveBtn) saveBtn.addEventListener('click', saveReferenceLinksSettings);

    const addBtn = document.getElementById('reference-links-add-row');
    if (addBtn) addBtn.addEventListener('click', addReferenceLinkRow);

    const tabs = document.querySelectorAll('.reference-links-tab');
    tabs.forEach((tab) => {
        tab.addEventListener('click', () => {
            const nextTab = String(tab.dataset.tab || "").toLowerCase();
            if (!REFERENCE_LINK_CATEGORIES.includes(nextTab)) return;
            referenceLinksState.activeTab = nextTab;
            renderReferenceLinksTabs();
            renderReferenceLinksRows();
        });
    });

    const advancedNav = document.querySelector('.settings-category[data-category="advanced"]');
    if (advancedNav) {
        advancedNav.addEventListener('click', () => {
            setTimeout(loadReferenceLinksSettings, 200);
        });
    }
}

// ═══════════════════════════════════════════════════════
// DIGEST PIPELINE STATUS PANEL (Phase 8 — DIGEST_UI_ENABLE)
// ═══════════════════════════════════════════════════════

window.DigestUI = (() => {
    const STATUS_COLORS = {
        ok:      'text-green-400',
        error:   'text-red-400',
        running: 'text-yellow-400',
        skipped: 'text-gray-400',
        never:   'text-gray-500',
    };

    function _statusClass(s) {
        return STATUS_COLORS[s] || 'text-gray-400';
    }

    function _cycleCard(cycleId, data) {
        const statusEl = document.getElementById(`digest-${cycleId}-status`);
        const metaEl   = document.getElementById(`digest-${cycleId}-meta`);
        if (!statusEl || !metaEl) return;
        const s = (data && data.status) || 'never';
        statusEl.className = `text-sm font-medium ${_statusClass(s)}`;
        statusEl.textContent = s.toUpperCase();
        const parts = [];
        if (data && data.last_run) parts.push(data.last_run.slice(0, 16).replace('T', ' '));
        if (data && data.digest_written != null) parts.push(`wrote ${data.digest_written}`);
        if (data && data.duration_s != null) parts.push(`${data.duration_s}s`);
        metaEl.textContent = parts.join(' | ');
    }

    function _flagChip(label, active) {
        const color = active ? 'bg-green-900 text-green-300 border-green-700'
                             : 'bg-[#1a1a1a] text-gray-500 border-dark-border';
        return `<span class="px-2 py-0.5 rounded border text-xs ${color}">${label}</span>`;
    }

    function _lockingCard(locking) {
        const statusEl = document.getElementById('digest-lock-status');
        const metaEl   = document.getElementById('digest-lock-info');
        if (!statusEl) return;
        if (!locking || locking.status === 'FREE') {
            statusEl.textContent  = 'FREE';
            statusEl.className    = 'text-sm font-medium text-green-400';
            if (metaEl) metaEl.textContent = '';
        } else {
            const stale = locking.stale ? ' [STALE]' : '';
            statusEl.textContent  = `LOCKED${stale}`;
            statusEl.className    = locking.stale
                ? 'text-sm font-medium text-red-400'
                : 'text-sm font-medium text-yellow-400';
            if (metaEl) {
                const owner = locking.owner || '?';
                const since = locking.since ? locking.since.slice(0, 16) : '?';
                metaEl.textContent = `${owner} @ ${since}`;
            }
        }
    }

    function _catchUpCard(cu) {
        const infoEl   = document.getElementById('digest-catchup-info');
        const detailEl = document.getElementById('digest-catchup-detail');
        if (!infoEl) return;
        if (!cu || cu.status === 'never') {
            infoEl.textContent = 'Never ran';
            if (detailEl) detailEl.innerHTML = '';
            return;
        }
        const since = cu.last_run ? ` @ ${cu.last_run.slice(0, 16)}` : '';
        infoEl.textContent = `${cu.status}${since}`;
        if (detailEl) {
            const recoveredColor = cu.recovered === true  ? 'text-green-400'
                                 : cu.recovered === false ? 'text-red-400'
                                 : 'text-gray-500';
            const recoveredText  = cu.recovered === true  ? '✓ recovered'
                                 : cu.recovered === false ? '✗ partial'
                                 : '—';
            detailEl.innerHTML = [
                `<span>missed: ${cu.missed_runs ?? 0}</span>`,
                `<span>generated: ${cu.generated ?? 0}</span>`,
                `<span class="${recoveredColor}">${recoveredText}</span>`,
                `<span>mode: ${cu.mode || '—'}</span>`,
            ].join('');
        }
    }

    async function refresh() {
        try {
            const r = await fetch(`${getApiBase()}/api/runtime/digest-state`);
            if (!r.ok) return;
            const d = await r.json();
            if (!d || d.error) {
                log('error', `[DigestUI] API error: ${d && d.error ? d.error : 'unknown'}`);
                return;
            }

            // V2 flat shape: d.daily_digest, d.weekly_digest, d.archive_digest
            // V1 legacy shape: d.state.daily, d.state.weekly, d.state.archive
            const isV2  = d.daily_digest !== undefined;
            const flags = d.flags || {};

            // Flag chips
            const flagsRow = document.getElementById('digest-flags-row');
            if (flagsRow) {
                flagsRow.innerHTML = [
                    _flagChip('DIGEST_ENABLE',  flags.digest_enable),
                    _flagChip('DAILY',          flags.digest_daily_enable),
                    _flagChip('WEEKLY',         flags.digest_weekly_enable),
                    _flagChip('ARCHIVE',        flags.digest_archive_enable),
                    _flagChip('JIT_ONLY',       flags.jit_only),
                    _flagChip('FILTERS',        flags.filters_enable),
                    _flagChip(`MODE:${(flags.digest_run_mode || 'off').toUpperCase()}`, flags.digest_run_mode !== 'off'),
                ].join('');
            }

            if (isV2) {
                // V2 API: flat top-level keys
                _cycleCard('daily',   d.daily_digest);
                _cycleCard('weekly',  d.weekly_digest);
                _cycleCard('archive', d.archive_digest);
                _lockingCard(d.locking);
                _catchUpCard(d.catch_up);

                // JIT block
                const jitEl = document.getElementById('digest-jit-info');
                if (jitEl && d.jit) {
                    const trig = d.jit.trigger || '—';
                    const rows = d.jit.rows != null ? ` (${d.jit.rows} rows)` : '';
                    const ts   = d.jit.ts ? ` @ ${d.jit.ts.slice(0, 16)}` : '';
                    jitEl.textContent = `${trig}${rows}${ts}`;
                }
            } else {
                // V1 legacy fallback
                const state = d.state || {};
                _cycleCard('daily',   state.daily);
                _cycleCard('weekly',  state.weekly);
                _cycleCard('archive', state.archive);

                const lockEl = document.getElementById('digest-lock-info');
                if (lockEl) {
                    lockEl.textContent = d.lock
                        ? `LOCKED by ${d.lock.owner || '?'} @ ${(d.lock.acquired_at || '').slice(0, 16)}`
                        : 'unlocked';
                    lockEl.className = d.lock ? 'text-yellow-400' : 'text-green-400';
                }

                const jitEl = document.getElementById('digest-jit-info');
                if (jitEl) {
                    const trig = state.jit_last_trigger || '—';
                    const rows = state.jit_last_rows != null ? ` (${state.jit_last_rows} rows)` : '';
                    const ts   = state.jit_last_ts ? ` @ ${state.jit_last_ts.slice(0, 16)}` : '';
                    jitEl.textContent = `${trig}${rows}${ts}`;
                }

                const cupEl = document.getElementById('digest-catchup-info');
                if (cupEl) {
                    const cu = state.catch_up || {};
                    cupEl.textContent = cu.status === 'never'
                        ? 'Never ran'
                        : `${cu.status} — ${cu.days_processed} days, ${cu.written} written @ ${(cu.last_run || '').slice(0, 16)}`;
                }
            }
        } catch (e) {
            log('error', `[DigestUI] refresh error: ${e.message}`);
        }
    }

    async function init() {
        try {
            // Show panel only if DIGEST_UI_ENABLE=true (check via flags endpoint)
            const r = await fetch(`${getApiBase()}/api/runtime/digest-state`);
            if (!r.ok) return;
            const d = await r.json();
            const uiEnable = d.flags && d.flags.digest_ui_enable;
            if (uiEnable) {
                const panel = document.getElementById('digest-status-panel');
                if (panel) panel.classList.remove('hidden');
                await refresh();
            }
        } catch (e) {
            // fail-open: panel stays hidden on error
        }
    }

    return { refresh, init };
})();

function setupDigestUIHandlers() {
    const advancedNav = document.querySelector('.settings-category[data-category="advanced"]');
    if (advancedNav) {
        advancedNav.addEventListener('click', () => {
            setTimeout(() => window.DigestUI && window.DigestUI.init(), 200);
        });
    }
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setupMasterSettingsHandlers();
        setupCompressionHandlers();
        setupEmbeddingRuntimeHandlers();
        setupAutonomyCronPolicyHandlers();
        setupReferenceLinksSettingsHandlers();
        setupDigestUIHandlers();
    });
} else {
    setupMasterSettingsHandlers();
    setupCompressionHandlers();
    setupEmbeddingRuntimeHandlers();
    setupAutonomyCronPolicyHandlers();
    setupReferenceLinksSettingsHandlers();
    setupDigestUIHandlers();
}
