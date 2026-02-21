// ═══════════════════════════════════════════════════════════════
// SETTINGS MANAGEMENT
// ═══════════════════════════════════════════════════════════════

const SETTINGS_KEY = 'jarvis_settings';

// Default settings
const DEFAULT_SETTINGS = {
    historyLength: 10,
    apiBase: window.location.protocol + '//' + window.location.hostname + ':8200',  // Updated: admin-api port
    verboseLogging: false,
    models: {
        thinking: 'deepseek-r1:8b',
        control: 'qwen3:4b',
        output: 'llama3.1:8b'
    }
};

// Current settings (loaded from localStorage)
let currentSettings = { ...DEFAULT_SETTINGS };

// Persona state
let personas = [];
let activePersona = 'default';

// ═══════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════

export function initSettings() {
    console.log('[Settings] Initializing...');
    
    // Load settings from localStorage
    loadSettings();
    
    // Setup tab switching
    setupTabs();
    
    // Setup controls
    setupBasicSettings();
    setupModelSettings();
    setupPersonaTab();  // ⭐ NEW: Persona management
    
    // Setup modal buttons
    setupModalButtons();
    
    console.log('[Settings] Initialized', currentSettings);
}

// ═══════════════════════════════════════════════════════════════
// TAB SWITCHING
// ═══════════════════════════════════════════════════════════════

function setupTabs() {
    const tabs = document.querySelectorAll('.settings-tab');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;
            switchTab(targetTab);
        });
    });
}

function switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.settings-tab').forEach(tab => {
        if (tab.dataset.tab === tabName) {
            tab.classList.remove('border-transparent', 'text-gray-400');
            tab.classList.add('border-accent-primary', 'text-white');
        } else {
            tab.classList.remove('border-accent-primary', 'text-white');
            tab.classList.add('border-transparent', 'text-gray-400');
        }
    });
    
    // Update tab content
    document.querySelectorAll('.settings-tab-content').forEach(content => {
        if (content.id === `tab-${tabName}`) {
            content.classList.remove('hidden');
            
            // ⭐ Load personas when persona tab is shown
            if (tabName === 'personas') {
                loadPersonas();
            }
        } else {
            content.classList.add('hidden');
        }
    });
}

// ═══════════════════════════════════════════════════════════════
// BASIC SETTINGS
// ═══════════════════════════════════════════════════════════════

function setupBasicSettings() {
    // History Length Slider
    const historySlider = document.getElementById('history-length');
    const historyValue = document.getElementById('history-length-value');
    
    if (!historySlider || !historyValue) {
        console.log('[Settings] History slider not found - skipping basic settings');
        return;
    }
    
    historySlider.value = currentSettings.historyLength;
    historyValue.textContent = currentSettings.historyLength;
    
    historySlider.addEventListener('input', (e) => {
        const value = parseInt(e.target.value);
        historyValue.textContent = value;
        currentSettings.historyLength = value;
        saveSettings();
    });
    
    // API Base Input
    const apiInput = document.getElementById('api-base-input');
    apiInput.value = currentSettings.apiBase;
    
    apiInput.addEventListener('change', (e) => {
        currentSettings.apiBase = e.target.value;
        saveSettings();
    });
    
    // Verbose Toggle
    const verboseToggle = document.getElementById('verbose-toggle');
    updateToggle(verboseToggle, currentSettings.verboseLogging);
    
    verboseToggle.addEventListener('click', () => {
        currentSettings.verboseLogging = !currentSettings.verboseLogging;
        updateToggle(verboseToggle, currentSettings.verboseLogging);
        saveSettings();
    });
}

function updateToggle(toggle, isOn) {
    if (!toggle) return;
    const slider = toggle.querySelector('span');
    if (!slider) return;
    
    if (isOn) {
        toggle.classList.remove('bg-dark-border');
        toggle.classList.add('bg-accent-primary');
        slider.classList.remove('bg-gray-400');
        slider.classList.add('bg-white', 'translate-x-6');
    } else {
        toggle.classList.remove('bg-accent-primary');
        toggle.classList.add('bg-dark-border');
        slider.classList.remove('bg-white', 'translate-x-6');
        slider.classList.add('bg-gray-400');
    }
}

// ═══════════════════════════════════════════════════════════════
// MODEL SETTINGS
// ═══════════════════════════════════════════════════════════════

function setupModelSettings() {
    // Setup model selects
    const thinkingSelect = document.getElementById('thinking-model');
    const controlSelect = document.getElementById('control-model');
    const outputSelect = document.getElementById('output-model');
    
    if (!thinkingSelect || !controlSelect || !outputSelect) {
        console.log('[Settings] Model select elements not found - skipping model settings');
        return;
    }
    
    // Load models from Ollama
    loadModelsFromOllama();
    
    thinkingSelect.addEventListener('change', (e) => {
        currentSettings.models.thinking = e.target.value;
        saveSettings();
        console.log('[Settings] Thinking model changed:', e.target.value);
    });
    
    controlSelect.addEventListener('change', (e) => {
        currentSettings.models.control = e.target.value;
        saveSettings();
        console.log('[Settings] Control model changed:', e.target.value);
    });
    
    outputSelect.addEventListener('change', (e) => {
        currentSettings.models.output = e.target.value;
        saveSettings();
        console.log('[Settings] Output model changed:', e.target.value);
    });
    
    // Test Ollama Button
    const testBtn = document.getElementById('test-ollama-btn');
    testBtn.addEventListener('click', () => {
        testOllamaConnection();
    });
}

async function loadModelsFromOllama() {
    const thinkingSelect = document.getElementById('thinking-model');
    const controlSelect = document.getElementById('control-model');
    const outputSelect = document.getElementById('output-model');
    
    if (!thinkingSelect || !controlSelect || !outputSelect) {
        console.log('[Settings] Model selects not found - skipping model load');
        return;
    }
    
    try {
        const response = await fetch(`${currentSettings.apiBase}/api/tags`);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        const models = data.models || [];
        
        console.log('[Settings] Loaded models from Ollama:', models.length);
        
        // Clear and populate dropdowns
        [thinkingSelect, controlSelect, outputSelect].forEach(select => {
            select.innerHTML = '';
            
            if (models.length === 0) {
                select.innerHTML = '<option value="">No models found</option>';
                return;
            }
            
            models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.name;
                option.textContent = model.name;
                select.appendChild(option);
            });
        });
        
        // Set current selections
        thinkingSelect.value = currentSettings.models.thinking;
        controlSelect.value = currentSettings.models.control;
        outputSelect.value = currentSettings.models.output;
        
    } catch (error) {
        console.error('[Settings] Failed to load models:', error);
        
        [thinkingSelect, controlSelect, outputSelect].forEach(select => {
            select.innerHTML = '<option value="">Failed to load models</option>';
        });
    }
}

async function testOllamaConnection() {
    const btn = document.getElementById('test-ollama-btn');
    const originalText = btn.textContent;
    
    btn.textContent = 'Testing...';
    btn.disabled = true;
    
    try {
        const response = await fetch(`${currentSettings.apiBase}/api/tags`);
        
        if (response.ok) {
            btn.textContent = '✅ Connected';
            btn.classList.add('bg-green-600');
            btn.classList.remove('bg-accent-primary');
            
            // Reload models
            await loadModelsFromOllama();
            
            setTimeout(() => {
                btn.textContent = originalText;
                btn.classList.remove('bg-green-600');
                btn.classList.add('bg-accent-primary');
                btn.disabled = false;
            }, 2000);
        } else {
            throw new Error('Connection failed');
        }
    } catch (error) {
        btn.textContent = '❌ Failed';
        btn.classList.add('bg-red-600');
        btn.classList.remove('bg-accent-primary');
        
        setTimeout(() => {
            btn.textContent = originalText;
            btn.classList.remove('bg-red-600');
            btn.classList.add('bg-accent-primary');
            btn.disabled = false;
        }, 2000);
    }
}

// ═══════════════════════════════════════════════════════════════
// PERSONA MANAGEMENT (⭐ NEW)
// ═══════════════════════════════════════════════════════════════

function setupPersonaTab() {
    console.log('[Personas] Setting up persona tab...');
    
    // Switch persona button
    const switchBtn = document.getElementById('switch-persona-btn');
    if (switchBtn) {
        switchBtn.addEventListener('click', handleSwitchPersona);
    }
    
    // Edit persona button
    const editBtn = document.getElementById('edit-persona-btn');
    if (editBtn) {
        editBtn.addEventListener('click', handleEditPersona);
    }
    
    // Upload persona button
    const uploadBtn = document.getElementById('upload-persona-btn');
    if (uploadBtn) {
        uploadBtn.addEventListener('click', handleUploadPersona);
    }
    
    // File input change
    const fileInput = document.getElementById('persona-file-input');
    if (fileInput) {
        fileInput.addEventListener('change', handleFileInputChange);
    }
    
    console.log('[Personas] Persona tab setup complete');
    
    // Load personas immediately (don't wait for tab switch)
    loadPersonas();
}

async function loadPersonas() {
    console.log('[Personas] Loading personas...');
    
    const selector = document.getElementById('persona-selector');
    const listContainer = document.getElementById('persona-list');
    
    if (!selector || !listContainer) {
        console.error('[Personas] Required elements not found');
        return;
    }
    
    // Show loading state
    selector.innerHTML = '<option>Loading...</option>';
    listContainer.innerHTML = '<div class="text-gray-400 text-center py-4">Loading personas...</div>';
    
    try {
        const response = await fetch(`${currentSettings.apiBase}/api/personas/`);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        personas = data.personas || [];
        activePersona = data.active || 'default';
        
        console.log('[Personas] Loaded:', personas.length, 'personas, active:', activePersona);
        
        // Update selector dropdown
        updatePersonaSelector();
        
        // Update persona list
        updatePersonaList();
        
    } catch (error) {
        console.error('[Personas] Failed to load:', error);
        selector.innerHTML = '<option>Failed to load</option>';
        listContainer.innerHTML = `
            <div class="text-red-400 text-center py-4">
                <p>❌ Failed to load personas</p>
                <p class="text-sm text-gray-500 mt-2">${error.message}</p>
            </div>
        `;
    }
}

function updatePersonaSelector() {
    const selector = document.getElementById('persona-selector');
    if (!selector) return;
    
    selector.innerHTML = '';
    
    personas.forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        option.selected = (name === activePersona);
        selector.appendChild(option);
    });
}

function updatePersonaList() {
    const listContainer = document.getElementById('persona-list');
    if (!listContainer) return;
    
    if (personas.length === 0) {
        listContainer.innerHTML = '<div class="text-gray-400 text-center py-4">No personas found</div>';
        return;
    }
    
    listContainer.innerHTML = '';
    
    personas.forEach(name => {
        const isActive = (name === activePersona);
        const isDefault = (name === 'default');
        
        const card = document.createElement('div');
        card.className = `p-4 rounded-lg border ${
            isActive 
                ? 'border-accent-primary bg-accent-primary/10' 
                : 'border-dark-border bg-dark-bg'
        } flex items-center justify-between`;
        
        card.innerHTML = `
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-full ${
                    isActive ? 'bg-accent-primary' : 'bg-dark-border'
                } flex items-center justify-center">
                    <i data-lucide="user" class="w-5 h-5 ${isActive ? 'text-white' : 'text-gray-400'}"></i>
                </div>
                <div>
                    <div class="font-medium ${isActive ? 'text-accent-primary' : 'text-white'}">
                        ${name}
                        ${isActive ? '<span class="text-xs text-accent-primary ml-2">(Active)</span>' : ''}
                        ${isDefault ? '<span class="text-xs text-gray-500 ml-2">(Protected)</span>' : ''}
                    </div>
                </div>
            </div>
            <div class="flex gap-2">
                ${!isDefault ? `
                    <button onclick="deletePersona('${name}')" 
                            class="px-3 py-1 text-sm rounded bg-red-600/20 text-red-400 hover:bg-red-600/30 transition-colors"
                            ${isActive ? 'disabled' : ''}>
                        Delete
                    </button>
                ` : ''}
            </div>
        `;
        
        listContainer.appendChild(card);
    });
    
    // Re-initialize lucide icons
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

async function handleSwitchPersona() {
    const selector = document.getElementById('persona-selector');
    const btn = document.getElementById('switch-persona-btn');
    
    if (!selector || !btn) return;
    
    const selectedPersona = selector.value;
    
    if (selectedPersona === activePersona) {
        console.log('[Personas] Already active:', selectedPersona);
        return;
    }
    
    const originalText = btn.textContent;
    btn.textContent = 'Switching...';
    btn.disabled = true;
    
    try {
        const response = await fetch(`${currentSettings.apiBase}/api/personas/${selectedPersona}/switch`, {
            method: 'PUT'
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        console.log('[Personas] Switched to:', data.persona);
        
        activePersona = data.persona;
        
        // Update UI
        updatePersonaList();
        
        btn.textContent = '✅ Switched!';
        btn.classList.add('bg-green-600');
        btn.classList.remove('bg-accent-primary');
        
        setTimeout(() => {
            btn.textContent = originalText;
            btn.classList.remove('bg-green-600');
            btn.classList.add('bg-accent-primary');
            btn.disabled = false;
        }, 2000);
        
    } catch (error) {
        console.error('[Personas] Switch failed:', error);
        
        btn.textContent = '❌ Failed';
        btn.classList.add('bg-red-600');
        btn.classList.remove('bg-accent-primary');
        
        setTimeout(() => {
            btn.textContent = originalText;
            btn.classList.remove('bg-red-600');
            btn.classList.add('bg-accent-primary');
            btn.disabled = false;
        }, 2000);
    }
}

function handleFileInputChange(e) {
    const file = e.target.files[0];
    const validationDiv = document.getElementById('upload-validation');
    
    if (!validationDiv) return;
    
    if (!file) {
        validationDiv.innerHTML = '';
        return;
    }
    
    // Validate file
    const errors = [];
    
    if (!file.name.endsWith('.txt')) {
        errors.push('File must be .txt');
    }
    
    if (file.size > 10 * 1024) {  // 10KB limit
        errors.push('File too large (max 10KB)');
    }
    
    if (errors.length > 0) {
        validationDiv.innerHTML = `
            <div class="text-red-400 text-sm">
                ${errors.map(err => `<div>❌ ${err}</div>`).join('')}
            </div>
        `;
    } else {
        validationDiv.innerHTML = `
            <div class="text-green-400 text-sm">
                ✅ File valid: ${file.name} (${(file.size / 1024).toFixed(2)}KB)
            </div>
        `;
    }
}

async function handleEditPersona() {
    console.log('[Personas] 🎯 handleEditPersona CALLED!');
    console.log('[Personas] Edit persona clicked');
    alert('Edit Persona functionality coming soon! For now, you can upload a custom persona using the Upload button.');
}

async function handleUploadPersona() {
    console.log('[Personas] 🎯 handleUploadPersona CALLED!');
    const fileInput = document.getElementById('persona-file-input');
    const btn = document.getElementById('upload-persona-btn');
    const validationDiv = document.getElementById('upload-validation');
    
    if (!fileInput || !btn || !validationDiv) return;
    
    const file = fileInput.files[0];
    
    if (!file) {
        validationDiv.innerHTML = '<div class="text-red-400 text-sm">❌ No file selected</div>';
        return;
    }
    
    const originalText = btn.textContent;
    btn.textContent = 'Uploading...';
    btn.disabled = true;
    
    try {
        const formData = new FormData();
        formData.append('file', file);
        
        const personaName = file.name.replace('.txt', '');
        
        const response = await fetch(`${currentSettings.apiBase}/api/personas/${personaName}`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        
        const data = await response.json();
        console.log('[Personas] Uploaded:', data);
        
        // Reload personas
        await loadPersonas();
        
        // Clear file input
        fileInput.value = '';
        validationDiv.innerHTML = '<div class="text-green-400 text-sm">✅ Upload successful!</div>';
        
        btn.textContent = '✅ Uploaded!';
        btn.classList.add('bg-green-600');
        btn.classList.remove('bg-accent-primary');
        
        setTimeout(() => {
            btn.textContent = originalText;
            btn.classList.remove('bg-green-600');
            btn.classList.add('bg-accent-primary');
            btn.disabled = false;
            validationDiv.innerHTML = '';
        }, 3000);
        
    } catch (error) {
        console.error('[Personas] Upload failed:', error);
        
        validationDiv.innerHTML = `<div class="text-red-400 text-sm">❌ ${error.message}</div>`;
        
        btn.textContent = '❌ Failed';
        btn.classList.add('bg-red-600');
        btn.classList.remove('bg-accent-primary');
        
        setTimeout(() => {
            btn.textContent = originalText;
            btn.classList.remove('bg-red-600');
            btn.classList.add('bg-accent-primary');
            btn.disabled = false;
        }, 2000);
    }
}

// Global function for delete (called from HTML onclick)
window.deletePersona = async function(name) {
    if (name === activePersona) {
        alert('Cannot delete active persona. Switch to another persona first.');
        return;
    }
    
    if (!confirm(`Delete persona "${name}"?`)) {
        return;
    }
    
    try {
        const response = await fetch(`${currentSettings.apiBase}/api/personas/${name}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        
        console.log('[Personas] Deleted:', name);
        
        // Reload personas
        await loadPersonas();
        
    } catch (error) {
        console.error('[Personas] Delete failed:', error);
        alert(`Failed to delete: ${error.message}`);
    }
};

// ═══════════════════════════════════════════════════════════════
// MODAL BUTTONS
// ═══════════════════════════════════════════════════════════════

function setupModalButtons() {
    // Open button
    const settingsBtn = document.getElementById('settings-btn');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', openSettings);
    }
    
    // Close buttons
    const closeBtn = document.getElementById('close-settings-btn');
    if (closeBtn) {
        closeBtn.addEventListener('click', closeSettings);
    }
    
    const closeBtnFooter = document.getElementById('close-settings-btn-footer');
    if (closeBtnFooter) {
        closeBtnFooter.addEventListener('click', closeSettings);
    }
    
    // Reset button
    const resetBtn = document.getElementById('reset-settings-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
        if (confirm('Reset all settings to defaults?')) {
            currentSettings = { ...DEFAULT_SETTINGS };
            localStorage.removeItem("sequential_sensitivity"); // Clear sequential slider
            saveSettings();
            location.reload(); // Reload to apply defaults
        }
        });
    }
}

function openSettings() {
    const modal = document.getElementById('settings-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

function closeSettings() {
    const modal = document.getElementById('settings-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

// ═══════════════════════════════════════════════════════════════
// LOCALSTORAGE
// ═══════════════════════════════════════════════════════════════

function loadSettings() {
    try {
        const saved = localStorage.getItem(SETTINGS_KEY);
        if (saved) {
            const parsed = JSON.parse(saved);
            currentSettings = { ...DEFAULT_SETTINGS, ...parsed };
            console.log('[Settings] Loaded from localStorage');
        }
    } catch (error) {
        console.error('[Settings] Failed to load:', error);
    }
}

function saveSettings() {
    try {
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(currentSettings));
        console.log('[Settings] Saved to localStorage');
    } catch (error) {
        console.error('[Settings] Failed to save:', error);
    }
}

// ═══════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════

export function getSettings() {
    return { ...currentSettings };
}

export function getSetting(key) {
    return currentSettings[key];
}

// ═══════════════════════════════════════════════════════════════
// SEQUENTIAL THINKING SENSITIVITY SLIDER
// ═══════════════════════════════════════════════════════════════

/**
 * Initialize Sequential Thinking sensitivity slider
 */
function initSequentialSensitivitySlider() {
    const slider = document.getElementById('sequential-sensitivity-slider');
    const valueDisplay = document.getElementById('sensitivity-value');
    const feedbackDisplay = document.getElementById('sensitivity-feedback');
    
    if (!slider || !window.sequentialThinking) {
        console.log('[Settings] Sequential slider not found or Sequential not initialized');
        return;
    }
    
    // Load saved value
    const saved = localStorage.getItem('sequential_sensitivity');
    if (saved !== null) {
        slider.value = saved;
        updateSensitivityUI(parseInt(saved));
    }
    
    // Update on change
    slider.addEventListener('input', (e) => {
        const value = parseInt(e.target.value);
        window.sequentialThinking.setSensitivity(value);
        updateSensitivityUI(value);
    });
    
    console.log('[Settings] Sequential sensitivity slider initialized');
}

/**
 * Update sensitivity UI elements
 * @param {number} value - Sensitivity value (-10 to +10)
 */
function updateSensitivityUI(value) {
    const valueDisplay = document.getElementById('sensitivity-value');
    const feedbackDisplay = document.getElementById('sensitivity-feedback');
    
    if (!valueDisplay || !feedbackDisplay) return;
    
    // Update label
    const labels = {
        '-10': 'Minimal',
        '-5': 'Sehr selten',
        '0': 'Balanced',
        '5': 'Häufig',
        '10': 'Sehr häufig'
    };
    
    let label = labels[value] || 'Custom';
    if (value === 0) {
        label += ' ✓';
    }
    
    valueDisplay.textContent = label;
    
    // Update feedback text
    const feedbacks = {
        '-10': 'Sequential triggert nur bei sehr komplexen, detaillierten Anfragen',
        '-5': 'Sequential triggert bei komplexen Anfragen',
        '0': 'Sequential triggert bei komplexen Fragen',
        '5': 'Sequential triggert bei mittleren bis komplexen Fragen',
        '10': 'Sequential triggert bei fast allen Fragen'
    };
    
    const nearest = Math.round(value / 5) * 5;
    const feedbackText = feedbacks[nearest] || feedbacks['0'];
    
    feedbackDisplay.innerHTML = `<i data-lucide="info" class="w-3 h-3 mt-0.5 flex-shrink-0"></i><span>${feedbackText}</span>`;
    
    // Refresh lucide icons
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

// Initialize slider when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSequentialSensitivitySlider);
} else {
    // DOM already loaded, wait a bit for Sequential to initialize
    setTimeout(initSequentialSensitivitySlider, 500);
}
