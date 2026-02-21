/**
 * settings.js - Settings App Logic (Ubuntu Style)
 * Manages Personas, Models, and System Config
 */

import { getApiBase } from "../../static/js/api.js";
import { log } from "../../static/js/debug.js";

const els = {
    pages: {
        personas: document.getElementById('page-personas'),
        models: document.getElementById('page-models'),
        memory: document.getElementById('page-memory')
    }
};

// ── Init guard — listeners must be registered exactly once ────────────────────
let _settingsInitialized = false;

/**
 * Initialize Settings
 * Safe to call multiple times: listeners register only once, data always refreshes.
 */
export async function initSettingsApp() {
    if (!_settingsInitialized) {
        _settingsInitialized = true;
        log('info', 'Initializing Settings App (first call — registering listeners)...');

        // Setup Persona Button Handlers (once)
        setupPersonaHandlers();

        // Setup Navigation Listeners (once)
        const navItems = document.querySelectorAll('.settings-category');
        navItems.forEach(item => {
            item.addEventListener('click', () => {
                const category = item.dataset.category;
                if (category === 'personas') loadPersonas();
                if (category === 'models') loadModels();
                if (category === 'plugins') loadPlugins();
            });
        });

        // Initial load check for active category
        const activeCat = document.querySelector('.settings-category.active');
        if (activeCat && activeCat.dataset.category === 'plugins') {
            loadPlugins();
        }
    } else {
        log('info', 'Settings App already initialized — skipping listener setup.');
    }

    // Always refresh persona list on (re-)open so data is current
    await loadPersonas();
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
    const safeName = escapeHtml(name);

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
                        <h3 class="text-xl font-bold text-white">Edit Persona: ${safeName}</h3>
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
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

function encodeForOnclickArg(text) {
    return encodeURIComponent(text == null ? '' : String(text));
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
        container.innerHTML = `<div class="text-red-400">Error: ${escapeHtml(e.message)}</div>`;
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
                <span class="text-gray-300 text-sm font-medium">${escapeHtml(activeIdentity[field])}</span>
            </div>
        `).join('');

    const safeActive = escapeHtml(active || 'default');

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
                        <h3 class="text-2xl font-bold text-white">${safeActive}</h3>
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
                ${(() => {
                    const safeDisplay = escapeHtml(p);
                    const encoded = encodeForOnclickArg(p);
                    return `
                <div class="bg-[#0a0a0a] border border-[#222] hover:border-gray-600 rounded-lg p-4 cursor-pointer transition-all hover:translate-x-1 group"
                     onclick="switchPersona(decodeURIComponent('${encoded}'))">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-3">
                            <i data-lucide="user" class="w-5 h-5 text-gray-600 group-hover:text-white transition-colors"></i>
                            <span class="text-gray-300 font-medium group-hover:text-white">${safeDisplay}</span>
                        </div>
                        <div class="flex items-center gap-2">
                            ${p !== 'default' ? `<button onclick="event.stopPropagation(); window.deletePersona(decodeURIComponent('${encoded}'))" class="p-1.5 rounded hover:bg-red-500/20 text-gray-500 hover:text-red-400 transition-colors" title="Delete Persona"><i data-lucide="trash-2" class="w-4 h-4"></i></button>` : ''}
                            <i data-lucide="chevron-right" class="w-4 h-4 text-[#333] group-hover:text-white"></i>
                        </div>
                    </div>
                </div>
                    `;
                })()}
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
        const res = await fetch(`${getApiBase()}/api/personas/${encodeURIComponent(name)}/switch`, {
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
    const page = els.pages.models;
    // Inject Structure if empty
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

    try {
        const res = await fetch(`${getApiBase()}/api/tags`);
        if (!res.ok) throw new Error("Failed to fetch models");
        const data = await res.json(); // { models: [ {name, ...} ] }

        renderModels(data.models || [], page.querySelector('.model-grid'));

    } catch (e) {
        log('error', `Models Load Error: ${e.message}`);
    }
}

window.testModel = (name) => alert(`Testing capability for ${name} coming soon!`);

// Bind global save
window.saveModelSettings = saveModelSettings;

function renderModels(models, container) {
    if (models.length === 0) {
        container.innerHTML = `<div class="p-4 text-gray-500">No models found in Ollama.</div>`;
        return;
    }

    const encodedModelName = (name) => encodeURIComponent(name || '');

    // Helper to create options
    const createOptions = (current) =>
        models
            .map(m => `<option value="${encodedModelName(m.name)}" ${m.name === current ? 'selected' : ''}>${escapeHtml(m.name)} (${(m.size / 1e9).toFixed(1)}GB)</option>`)
            .join('');

    // Grid Layout for Settings
    const html = `
        <div class="space-y-8 max-w-4xl">
            
            <!-- Model Layers Configuration -->
            <div class="bg-[#111] border border-dark-border rounded-xl p-6">
                <h3 class="text-xl font-bold text-gray-200 mb-6 flex items-center gap-2">
                    <i data-lucide="layers" class="text-accent-primary"></i>
                    Cognitive Layers
                </h3>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <!-- Thinking Layer -->
                    <div class="space-y-2">
                        <label class="text-sm text-gray-400 font-mono uppercase">Thinking Model (System 2)</label>
                        <select id="setting-thinking-model" class="w-full bg-dark-bg border border-dark-border rounded-lg p-3 text-gray-200 focus:border-accent-primary outline-none">
                            <option value="">(Disabled)</option>
                            ${createOptions('deepseek-r1:8b')} <!-- TODO: Fetch actual current setting -->
                        </select>
                        <p class="text-xs text-gray-500">Handles deep reasoning and planning.</p>
                    </div>

                    <!-- Control Layer -->
                    <div class="space-y-2">
                        <label class="text-sm text-gray-400 font-mono uppercase">Control Model (System 1)</label>
                        <select id="setting-control-model" class="w-full bg-dark-bg border border-dark-border rounded-lg p-3 text-gray-200 focus:border-accent-primary outline-none">
                            ${createOptions('qwen3:4b')}
                        </select>
                        <p class="text-xs text-gray-500">Orchestrates tools and memory access.</p>
                    </div>

                    <!-- Output Layer -->
                    <div class="space-y-2">
                        <label class="text-sm text-gray-400 font-mono uppercase">Output Model (Generator)</label>
                        <select id="setting-output-model" class="w-full bg-dark-bg border border-dark-border rounded-lg p-3 text-gray-200 focus:border-accent-primary outline-none">
                             ${createOptions('llama3.2:3b')}
                        </select>
                        <p class="text-xs text-gray-500">Generates the final user response.</p>
                    </div>
                </div>

                <div class="mt-8 flex justify-end">
                    <button onclick="saveModelSettings()" 
                            class="px-6 py-2 bg-accent-primary hover:bg-orange-500 text-black font-bold rounded-lg transition-colors flex items-center gap-2">
                        <i data-lucide="save" class="w-4 h-4"></i>
                        Save Configuration
                    </button>
                </div>
            </div>

            <!-- Model List (Read Only) -->
            <div>
                 <h4 class="text-gray-500 font-medium mb-4">Installed Models</h4>
                 <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    ${models.map(m => `
                        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex justify-between items-center opacity-70 hover:opacity-100 transition-opacity">
                            <span class="font-mono text-sm text-gray-300">${escapeHtml(m.name)}</span>
                            <span class="text-xs text-gray-500">${(m.size / 1e9).toFixed(1)} GB</span>
                        </div>
                    `).join('')}
                 </div>
            </div>
        </div>
    `;

    container.innerHTML = html;
    lucide.createIcons();

    // TODO: We should fetch current settings to pre-select!
    // fetchSettings().then(applyToSelectors)
}

async function saveModelSettings() {
    const decode = (id) => {
        const el = document.getElementById(id);
        return el && el.value ? decodeURIComponent(el.value) : '';
    };
    const changes = {
        THINKING_MODEL: decode('setting-thinking-model'),
        CONTROL_MODEL: decode('setting-control-model'),
        OUTPUT_MODEL: decode('setting-output-model')
    };

    showToast("Saving settings...", "info");

    try {
        const res = await fetch(`${getApiBase()}/api/settings/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(changes)
        });

        if (!res.ok) throw new Error("Save failed");

        showToast("Configuration saved!", "success");
    } catch (e) {
        showToast(`Error: ${e.message}`, "error");
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
        container.innerHTML = `<div class="p-4 text-red-400">Failed to load plugins: ${escapeHtml(e.message)}</div>`;
    }
}

function renderPlugins(plugins, container) {
    if (!plugins || plugins.length === 0) {
        container.innerHTML = `<div class="p-4 text-gray-500">No plugins installed in TRION Runtime.</div>`;
        return;
    }

    const html = plugins.map(p => {
        const manifest = p.manifest || {};
        const pluginId = manifest.id || '';
        const safeId = encodeForOnclickArg(pluginId);
        const safeName = escapeHtml(manifest.name || pluginId || 'unknown');
        const safeVersion = escapeHtml(manifest.version || '1.0.0');
        const safeDescription = escapeHtml(manifest.description || 'No description available.');
        const permissionTags = (manifest.permissions ? Object.keys(manifest.permissions) : [])
            .map(c => `<span class="bg-dark-bg border border-dark-border px-2 py-1 rounded text-xs text-gray-500 font-mono">${escapeHtml(c)}</span>`)
            .join('');
        return `
        <div class="bg-[#111] border border-dark-border rounded-xl p-6 flex items-start justify-between">
            <div class="flex items-start gap-4">
                <div class="w-12 h-12 bg-dark-bg rounded-lg flex items-center justify-center border border-dark-border">
                    <i data-lucide="puzzle" class="w-6 h-6 text-accent-primary"></i>
                </div>
                <div>
                    <h3 class="text-lg font-bold text-gray-200">${safeName} <span class="text-xs text-gray-500 font-normal ml-2">v${safeVersion}</span></h3>
                    <p class="text-sm text-gray-400 mt-1">${safeDescription}</p>
                    <div class="flex flex-wrap gap-2 mt-3">
                        ${permissionTags}
                    </div>
                </div>
            </div>
            
            <div class="flex items-center gap-3">
                <span class="text-xs font-mono uppercase ${p.enabled ? 'text-green-500' : 'text-gray-600'}">
                    ${p.enabled ? 'Enabled' : 'Disabled'}
                </span>
                <button onclick="togglePlugin(decodeURIComponent('${safeId}'), ${!p.enabled})" 
                    class="w-12 h-6 rounded-full transition-colors relative ${p.enabled ? 'bg-accent-primary' : 'bg-gray-700'}"
                    title="${p.enabled ? 'Disable' : 'Enable'}">
                    <div class="absolute top-1 left-1 bg-white w-4 h-4 rounded-full transition-transform ${p.enabled ? 'translate-x-6' : 'translate-x-0'}"></div>
                </button>
            </div>
        </div>
    `;
    }).join('');

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
    const label = document.createElement("span");
    label.className = "font-mono text-sm";
    label.textContent = msg;
    toast.appendChild(label);
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
        const thresholdEl = document.getElementById('compression-threshold');
        const thresholdValueEl = document.getElementById('compression-threshold-value');
        const phase2ThresholdEl = document.getElementById('compression-phase2-threshold');
        const keepMessagesEl = document.getElementById('compression-keep-messages');
        if (enabledEl) enabledEl.checked = s.enabled;
        if (modeEl) modeEl.value = s.mode;
        if (thresholdEl && Number.isFinite(s.threshold)) thresholdEl.value = String(s.threshold);
        if (thresholdValueEl && Number.isFinite(s.threshold)) thresholdValueEl.textContent = String(s.threshold);
        if (phase2ThresholdEl && Number.isFinite(s.phase2_threshold)) phase2ThresholdEl.value = String(s.phase2_threshold);
        if (keepMessagesEl && Number.isFinite(s.keep_messages)) keepMessagesEl.value = String(s.keep_messages);
        log('info', 'Compression settings loaded', s);
    } catch (e) {
        log('error', `Failed to load compression settings: ${e.message}`);
    }
}

async function saveCompressionSettings() {
    const enabledEl = document.getElementById('compression-enabled');
    const modeEl = document.getElementById('compression-mode');
    const thresholdEl = document.getElementById('compression-threshold');
    const phase2ThresholdEl = document.getElementById('compression-phase2-threshold');
    const keepMessagesEl = document.getElementById('compression-keep-messages');
    const payload = {
        enabled: enabledEl ? enabledEl.checked : true,
        mode: modeEl ? modeEl.value : 'sync',
    };
    if (thresholdEl) {
        const threshold = parseInt(thresholdEl.value, 10);
        if (Number.isFinite(threshold)) payload.threshold = threshold;
    }
    if (phase2ThresholdEl) {
        const phase2Threshold = parseInt(phase2ThresholdEl.value, 10);
        if (Number.isFinite(phase2Threshold)) payload.phase2_threshold = phase2Threshold;
    }
    if (keepMessagesEl) {
        const keepMessages = parseInt(keepMessagesEl.value, 10);
        if (Number.isFinite(keepMessages)) payload.keep_messages = keepMessages;
    }
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
// DIGEST PIPELINE STATUS PANEL (Phase 8 — DIGEST_UI_ENABLE)
// ═══════════════════════════════════════════════════════

window.DigestUI = (() => {
    const STATUS_COLORS = {
        ok:      'text-green-400',
        error:   'text-red-400',
        running: 'text-yellow-400',
        skip:    'text-gray-400',   // API returns "skip" (not "skipped")
        skipped: 'text-gray-400',   // legacy alias kept for safety
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
        if (data && data.input_events != null) parts.push(`in: ${data.input_events}`);
        if (data && data.duration_s != null) parts.push(`${data.duration_s}s`);
        if (data && data.reason) parts.push(`reason: ${data.reason}`);
        if (data && data.digest_key) {
            const k = String(data.digest_key);
            parts.push(`key: ${k.length > 12 ? k.slice(0, 6) + '\u2026' + k.slice(-6) : k}`);
        }
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
        setupDigestUIHandlers();
    });
} else {
    setupMasterSettingsHandlers();
    setupCompressionHandlers();
    setupDigestUIHandlers();
}
