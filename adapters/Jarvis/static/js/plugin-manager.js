/**
 * ═══════════════════════════════════════════════════════════════
 * JARVIS PLUGIN MANAGER v1.0
 * Dynamic Plugin System with Registry, Loader & Settings
 * ═══════════════════════════════════════════════════════════════
 * 
 * Features:
 * - Plugin Registry with localStorage persistence
 * - Dynamic script loading
 * - Enable/Disable lifecycle management
 * - Settings integration
 * - Event-based communication
 * 
 * Plugin Interface:
 * {
 *   id: 'unique-id',
 *   name: 'Display Name',
 *   version: '1.0.0',
 *   description: 'What it does',
 *   author: 'Author Name',
 *   icon: 'lucide-icon-name',
 *   init: () => {},
 *   destroy: () => {},
 *   getSettings?: () => [...],
 *   onSettingChange?: (key, value) => {}
 * }
 */

class PluginManager {
    constructor() {
        this.STORAGE_KEY = 'jarvis_plugins';
        this.registry = new Map();
        this.builtInPlugins = new Map();
        this.listeners = new Map();
        this.loadState();
        console.log('[PluginManager] Initialized');
    }
    
    loadState() {
        try {
            const saved = localStorage.getItem(this.STORAGE_KEY);
            if (saved) {
                const state = JSON.parse(saved);
                this.enabledPlugins = new Set(state.enabled || []);
                this.pluginSettings = state.settings || {};
            } else {
                this.enabledPlugins = new Set();
                this.pluginSettings = {};
            }
        } catch (e) {
            console.error('[PluginManager] Failed to load state:', e);
            this.enabledPlugins = new Set();
            this.pluginSettings = {};
        }
    }
    
    saveState() {
        try {
            const state = {
                enabled: Array.from(this.enabledPlugins),
                settings: this.pluginSettings
            };
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(state));
        } catch (e) {
            console.error('[PluginManager] Failed to save state:', e);
        }
    }
    
    registerBuiltIn(manifest, pluginClass) {
        const id = manifest.id;
        if (this.registry.has(id)) {
            console.warn(`[PluginManager] Plugin ${id} already registered`);
            return false;
        }
        console.log(`[PluginManager] Registering built-in: ${id}`);
        this.builtInPlugins.set(id, pluginClass);
        this.registry.set(id, {
            manifest,
            instance: null,
            enabled: false,
            loaded: false,
            builtIn: true
        });
        if (!localStorage.getItem(this.STORAGE_KEY)) {
            this.enabledPlugins.add(id);
        }
        return true;
    }
    
    async registerFromURL(url) {
        try {
            console.log(`[PluginManager] Loading plugin from: ${url}`);
            await this.loadScript(url);
            return true;
        } catch (e) {
            console.error(`[PluginManager] Failed to load plugin from ${url}:`, e);
            return false;
        }
    }
    
    register(manifest, pluginClass) {
        const id = manifest.id;
        if (this.registry.has(id)) {
            console.warn(`[PluginManager] Plugin ${id} already registered`);
            return false;
        }
        console.log(`[PluginManager] Registering: ${id}`);
        this.registry.set(id, {
            manifest,
            pluginClass,
            instance: null,
            enabled: false,
            loaded: false,
            builtIn: false
        });
        this.emit('plugin-registered', { id, manifest });
        return true;
    }
    
    async initAll() {
        console.log('[PluginManager] Initializing enabled plugins...');
        for (const [id, entry] of this.registry) {
            if (this.enabledPlugins.has(id)) {
                await this.enable(id);
            }
        }
        console.log(`[PluginManager] Initialized ${this.enabledPlugins.size} plugins`);
    }
    
    async enable(id) {
        const entry = this.registry.get(id);
        if (!entry) {
            console.error(`[PluginManager] Plugin not found: ${id}`);
            return false;
        }
        if (entry.enabled) {
            console.log(`[PluginManager] Plugin already enabled: ${id}`);
            return true;
        }
        console.log(`[PluginManager] Enabling: ${id}`);
        try {
            const PluginClass = entry.builtIn 
                ? this.builtInPlugins.get(id)
                : entry.pluginClass;
            if (!PluginClass) {
                throw new Error('Plugin class not found');
            }
            entry.instance = new PluginClass(window.TRIONPanel, this);
            if (typeof entry.instance.init === 'function') {
                await entry.instance.init();
            }
            const settings = this.pluginSettings[id];
            if (settings && typeof entry.instance.onSettingChange === 'function') {
                for (const [key, value] of Object.entries(settings)) {
                    entry.instance.onSettingChange(key, value);
                }
            }
            entry.enabled = true;
            entry.loaded = true;
            this.enabledPlugins.add(id);
            this.saveState();
            this.emit('plugin-enabled', { id });
            return true;
        } catch (e) {
            console.error(`[PluginManager] Failed to enable ${id}:`, e);
            return false;
        }
    }
    
    async disable(id) {
        const entry = this.registry.get(id);
        if (!entry) {
            console.error(`[PluginManager] Plugin not found: ${id}`);
            return false;
        }
        if (!entry.enabled) {
            console.log(`[PluginManager] Plugin already disabled: ${id}`);
            return true;
        }
        console.log(`[PluginManager] Disabling: ${id}`);
        try {
            if (entry.instance && typeof entry.instance.destroy === 'function') {
                await entry.instance.destroy();
            }
            entry.instance = null;
            entry.enabled = false;
            this.enabledPlugins.delete(id);
            this.saveState();
            this.emit('plugin-disabled', { id });
            return true;
        } catch (e) {
            console.error(`[PluginManager] Failed to disable ${id}:`, e);
            return false;
        }
    }
    
    async toggle(id) {
        const entry = this.registry.get(id);
        if (!entry) return false;
        return entry.enabled ? this.disable(id) : this.enable(id);
    }
    
    getSettingsSchema(id) {
        const entry = this.registry.get(id);
        if (!entry || !entry.instance) return [];
        return typeof entry.instance.getSettings === 'function'
            ? entry.instance.getSettings()
            : [];
    }
    
    getSetting(pluginId, key) {
        return this.pluginSettings[pluginId]?.[key];
    }
    
    setSetting(pluginId, key, value) {
        if (!this.pluginSettings[pluginId]) {
            this.pluginSettings[pluginId] = {};
        }
        this.pluginSettings[pluginId][key] = value;
        this.saveState();
        const entry = this.registry.get(pluginId);
        if (entry?.instance?.onSettingChange) {
            entry.instance.onSettingChange(key, value);
        }
        this.emit('setting-changed', { pluginId, key, value });
    }
    
    getAll() {
        const plugins = [];
        for (const [id, entry] of this.registry) {
            plugins.push({
                id,
                ...entry.manifest,
                enabled: entry.enabled,
                builtIn: entry.builtIn
            });
        }
        return plugins;
    }
    
    get(id) {
        const entry = this.registry.get(id);
        if (!entry) return null;
        return {
            id,
            ...entry.manifest,
            enabled: entry.enabled,
            builtIn: entry.builtIn,
            instance: entry.instance
        };
    }
    
    isEnabled(id) {
        return this.enabledPlugins.has(id);
    }
    
    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }
    
    off(event, callback) {
        const listeners = this.listeners.get(event);
        if (listeners) {
            const idx = listeners.indexOf(callback);
            if (idx > -1) listeners.splice(idx, 1);
        }
    }
    
    emit(event, data) {
        const listeners = this.listeners.get(event) || [];
        listeners.forEach(cb => {
            try {
                cb(data);
            } catch (e) {
                console.error(`[PluginManager] Event handler error:`, e);
            }
        });
    }
    
    loadScript(url) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = url;
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
}

// Global Instance
window.PluginManager = new PluginManager();

// Plugin Base Class
class PluginBase {
    constructor(panel, manager) {
        this.panel = panel;
        this.manager = manager;
    }
    init() {}
    destroy() {}
    getSettings() { return []; }
    onSettingChange(key, value) {}
}

window.PluginBase = PluginBase;
console.log('[PluginManager] Plugin system loaded');
