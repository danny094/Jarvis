// ═══════════════════════════════════════════════════════════════
// SETTINGS MANAGEMENT
// ═══════════════════════════════════════════════════════════════

const SETTINGS_KEY = 'jarvis_settings';

// Default settings
const DEFAULT_SETTINGS = {
    historyLength: 10,
    apiBase: 'http://192.168.0.226:8100',
    verboseLogging: false,
    models: {
        thinking: 'deepseek-r1:8b',
        control: 'qwen3:4b',
        output: 'llama3.1:8b'
    }
};

// Current settings (loaded from localStorage)
let currentSettings = { ...DEFAULT_SETTINGS };

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
    const slider = toggle.querySelector('span');
    
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
    // Load models from Ollama
    loadModelsFromOllama();
    
    // Setup model selects
    const thinkingSelect = document.getElementById('thinking-model');
    const controlSelect = document.getElementById('control-model');
    const outputSelect = document.getElementById('output-model');
    
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
// MODAL BUTTONS
// ═══════════════════════════════════════════════════════════════

function setupModalButtons() {
    // Close buttons
    document.getElementById('close-settings-btn').addEventListener('click', closeSettings);
    document.getElementById('close-settings-btn-footer').addEventListener('click', closeSettings);
    
    // Reset button
    document.getElementById('reset-settings-btn').addEventListener('click', () => {
        if (confirm('Reset all settings to defaults?')) {
            currentSettings = { ...DEFAULT_SETTINGS };
            saveSettings();
            location.reload(); // Reload to apply defaults
        }
    });
}

function closeSettings() {
    document.getElementById('settings-modal').classList.add('hidden');
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
