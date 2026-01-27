/**
 * ═══════════════════════════════════════════════════════════════
 * PLUGIN SETTINGS UI
 * Settings page integration for PluginManager
 * ═══════════════════════════════════════════════════════════════
 */

class PluginSettingsUI {
    constructor() {
        this.container = null;
        this.expandedPlugin = null;
    }
    
    init() {
        console.log('[PluginSettingsUI] Initializing...');
        
        // Listen for PluginManager events
        if (window.PluginManager) {
            window.PluginManager.on('plugin-enabled', () => this.refresh());
            window.PluginManager.on('plugin-disabled', () => this.refresh());
            window.PluginManager.on('plugin-registered', () => this.refresh());
        }
    }
    
    /**
     * Render plugins tab content
     * @param {HTMLElement} container - Container element
     */
    render(container) {
        this.container = container;
        
        if (!window.PluginManager) {
            container.innerHTML = `
                <div class="text-center py-8 text-gray-400">
                    <i data-lucide="alert-triangle" class="w-12 h-12 mx-auto mb-4"></i>
                    <p>Plugin Manager not loaded</p>
                </div>
            `;
            if (window.lucide) window.lucide.createIcons();
            return;
        }
        
        const plugins = window.PluginManager.getAll();
        
        if (plugins.length === 0) {
            container.innerHTML = `
                <div class="text-center py-8 text-gray-400">
                    <i data-lucide="puzzle" class="w-12 h-12 mx-auto mb-4"></i>
                    <p>No plugins available</p>
                    <p class="text-sm mt-2">Plugins will appear here when loaded</p>
                </div>
            `;
            if (window.lucide) window.lucide.createIcons();
            return;
        }
        
        container.innerHTML = `
            <div class="plugins-header mb-6">
                <h3 class="text-lg font-semibold text-white mb-2">Plugins</h3>
                <p class="text-sm text-gray-400">Enable or disable plugins and configure their settings</p>
            </div>
            <div class="plugins-list space-y-3" id="plugins-list"></div>
        `;
        
        const list = container.querySelector('#plugins-list');
        
        for (const plugin of plugins) {
            list.appendChild(this.createPluginCard(plugin));
        }
        
        if (window.lucide) window.lucide.createIcons();
    }
    
    /**
     * Create a plugin card
     */
    createPluginCard(plugin) {
        const card = document.createElement('div');
        card.className = 'plugin-card bg-dark-card border border-dark-border rounded-lg overflow-hidden';
        card.setAttribute('data-plugin-id', plugin.id);
        
        const isExpanded = this.expandedPlugin === plugin.id;
        const settings = window.PluginManager.getSettingsSchema(plugin.id);
        const hasSettings = plugin.enabled && settings.length > 0;
        
        card.innerHTML = `
            <div class="plugin-header p-4 flex items-center justify-between cursor-pointer hover:bg-dark-hover transition-colors">
                <div class="flex items-center gap-3">
                    <div class="plugin-icon w-10 h-10 rounded-lg bg-dark-hover flex items-center justify-center">
                        <i data-lucide="${plugin.icon || 'puzzle'}" class="w-5 h-5 ${plugin.enabled ? 'text-accent-primary' : 'text-gray-400'}"></i>
                    </div>
                    <div>
                        <div class="flex items-center gap-2">
                            <h4 class="font-medium text-white">${this.escapeHtml(plugin.name)}</h4>
                            <span class="text-xs text-gray-500">v${plugin.version}</span>
                            ${plugin.builtIn ? '<span class="text-xs px-2 py-0.5 rounded bg-dark-hover text-gray-400">Built-in</span>' : ''}
                        </div>
                        <p class="text-sm text-gray-400">${this.escapeHtml(plugin.description || '')}</p>
                    </div>
                </div>
                <div class="flex items-center gap-3">
                    ${hasSettings ? `
                        <button class="plugin-settings-btn p-2 hover:bg-dark-hover rounded transition-colors" title="Settings">
                            <i data-lucide="settings" class="w-4 h-4 text-gray-400"></i>
                        </button>
                    ` : ''}
                    <button class="plugin-toggle w-12 h-6 rounded-full transition-colors ${plugin.enabled ? 'bg-accent-primary' : 'bg-dark-border'}" 
                            data-plugin-id="${plugin.id}">
                        <span class="block w-5 h-5 rounded-full transition-transform ${plugin.enabled ? 'bg-white translate-x-6' : 'bg-gray-400 translate-x-0.5'}"></span>
                    </button>
                </div>
            </div>
            ${hasSettings ? `
                <div class="plugin-settings-panel border-t border-dark-border ${isExpanded ? '' : 'hidden'}">
                    <div class="p-4 space-y-4" id="plugin-settings-${plugin.id}">
                        ${this.renderSettings(plugin.id, settings)}
                    </div>
                </div>
            ` : ''}
        `;
        
        // Toggle handler
        const toggle = card.querySelector('.plugin-toggle');
        toggle.addEventListener('click', async (e) => {
            e.stopPropagation();
            await window.PluginManager.toggle(plugin.id);
        });
        
        // Settings expand handler
        const settingsBtn = card.querySelector('.plugin-settings-btn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleSettings(plugin.id, card);
            });
        }
        
        // Header click to toggle settings (if has settings)
        const header = card.querySelector('.plugin-header');
        header.addEventListener('click', () => {
            if (hasSettings) {
                this.toggleSettings(plugin.id, card);
            }
        });
        
        return card;
    }
    
    /**
     * Toggle settings panel
     */
    toggleSettings(pluginId, card) {
        const panel = card.querySelector('.plugin-settings-panel');
        if (!panel) return;
        
        const isHidden = panel.classList.contains('hidden');
        
        // Close all other panels
        document.querySelectorAll('.plugin-settings-panel').forEach(p => {
            if (p !== panel) p.classList.add('hidden');
        });
        
        // Toggle this panel
        panel.classList.toggle('hidden', !isHidden);
        this.expandedPlugin = isHidden ? pluginId : null;
    }
    
    /**
     * Render settings for a plugin
     */
    renderSettings(pluginId, settings) {
        return settings.map(setting => {
            const value = window.PluginManager.getSetting(pluginId, setting.key) ?? setting.default;
            
            switch (setting.type) {
                case 'toggle':
                    return this.renderToggle(pluginId, setting, value);
                case 'number':
                    return this.renderNumber(pluginId, setting, value);
                case 'text':
                    return this.renderText(pluginId, setting, value);
                case 'select':
                    return this.renderSelect(pluginId, setting, value);
                default:
                    return '';
            }
        }).join('');
    }
    
    renderToggle(pluginId, setting, value) {
        return `
            <div class="setting-item flex items-center justify-between">
                <div>
                    <label class="text-sm font-medium text-white">${this.escapeHtml(setting.label)}</label>
                    ${setting.description ? `<p class="text-xs text-gray-500">${this.escapeHtml(setting.description)}</p>` : ''}
                </div>
                <button class="setting-toggle w-10 h-5 rounded-full transition-colors ${value ? 'bg-accent-primary' : 'bg-dark-border'}"
                        data-plugin-id="${pluginId}" data-setting-key="${setting.key}" data-setting-type="toggle">
                    <span class="block w-4 h-4 rounded-full transition-transform ${value ? 'bg-white translate-x-5' : 'bg-gray-400 translate-x-0.5'}"></span>
                </button>
            </div>
        `;
    }
    
    renderNumber(pluginId, setting, value) {
        return `
            <div class="setting-item">
                <div class="flex items-center justify-between mb-2">
                    <label class="text-sm font-medium text-white">${this.escapeHtml(setting.label)}</label>
                    <span class="text-sm text-accent-primary setting-value">${value}</span>
                </div>
                ${setting.description ? `<p class="text-xs text-gray-500 mb-2">${this.escapeHtml(setting.description)}</p>` : ''}
                <input type="range" 
                       class="w-full setting-range"
                       min="${setting.min || 0}" 
                       max="${setting.max || 100}" 
                       value="${value}"
                       data-plugin-id="${pluginId}" 
                       data-setting-key="${setting.key}" 
                       data-setting-type="number">
            </div>
        `;
    }
    
    renderText(pluginId, setting, value) {
        return `
            <div class="setting-item">
                <label class="text-sm font-medium text-white block mb-1">${this.escapeHtml(setting.label)}</label>
                ${setting.description ? `<p class="text-xs text-gray-500 mb-2">${this.escapeHtml(setting.description)}</p>` : ''}
                <input type="text" 
                       class="w-full bg-dark-hover border border-dark-border rounded px-3 py-2 text-sm text-white setting-text"
                       value="${this.escapeHtml(value || '')}"
                       placeholder="${setting.placeholder || ''}"
                       data-plugin-id="${pluginId}" 
                       data-setting-key="${setting.key}" 
                       data-setting-type="text">
            </div>
        `;
    }
    
    renderSelect(pluginId, setting, value) {
        const options = (setting.options || []).map(opt => {
            const selected = opt.value === value ? 'selected' : '';
            return `<option value="${this.escapeHtml(opt.value)}" ${selected}>${this.escapeHtml(opt.label)}</option>`;
        }).join('');
        
        return `
            <div class="setting-item">
                <label class="text-sm font-medium text-white block mb-1">${this.escapeHtml(setting.label)}</label>
                ${setting.description ? `<p class="text-xs text-gray-500 mb-2">${this.escapeHtml(setting.description)}</p>` : ''}
                <select class="w-full bg-dark-hover border border-dark-border rounded px-3 py-2 text-sm text-white setting-select"
                        data-plugin-id="${pluginId}" 
                        data-setting-key="${setting.key}" 
                        data-setting-type="select">
                    ${options}
                </select>
            </div>
        `;
    }
    
    /**
     * Attach event listeners for settings controls
     */
    attachSettingsListeners() {
        if (!this.container) return;
        
        // Toggle settings
        this.container.querySelectorAll('.setting-toggle').forEach(toggle => {
            toggle.addEventListener('click', () => {
                const pluginId = toggle.dataset.pluginId;
                const key = toggle.dataset.settingKey;
                const current = window.PluginManager.getSetting(pluginId, key);
                window.PluginManager.setSetting(pluginId, key, !current);
                this.refresh();
            });
        });
        
        // Number settings (range)
        this.container.querySelectorAll('.setting-range').forEach(range => {
            range.addEventListener('input', (e) => {
                const value = parseInt(e.target.value);
                const valueDisplay = e.target.closest('.setting-item').querySelector('.setting-value');
                if (valueDisplay) valueDisplay.textContent = value;
            });
            range.addEventListener('change', (e) => {
                const pluginId = e.target.dataset.pluginId;
                const key = e.target.dataset.settingKey;
                window.PluginManager.setSetting(pluginId, key, parseInt(e.target.value));
            });
        });
        
        // Text settings
        this.container.querySelectorAll('.setting-text').forEach(input => {
            input.addEventListener('change', (e) => {
                const pluginId = e.target.dataset.pluginId;
                const key = e.target.dataset.settingKey;
                window.PluginManager.setSetting(pluginId, key, e.target.value);
            });
        });
        
        // Select settings
        this.container.querySelectorAll('.setting-select').forEach(select => {
            select.addEventListener('change', (e) => {
                const pluginId = e.target.dataset.pluginId;
                const key = e.target.dataset.settingKey;
                window.PluginManager.setSetting(pluginId, key, e.target.value);
            });
        });
    }
    
    /**
     * Refresh the UI
     */
    refresh() {
        if (this.container) {
            this.render(this.container);
            this.attachSettingsListeners();
        }
    }
    
    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

// Global instance
window.PluginSettingsUI = new PluginSettingsUI();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { PluginSettingsUI };
}
