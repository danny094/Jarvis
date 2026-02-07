/**
 * TRION Plugin Host
 * Manages plugin lifecycle and execution
 */

import { PluginManifest, PluginState, validateManifest } from '../manifests/schema.ts';
import { PermissionGuard } from './permission-guard.ts';
import { TRIONPlugin, PluginContext, PluginConstructor, EventAPI } from './plugin-base.ts';
import { EventEmitter } from "node:events";

const PLUGINS_DIR = '/DATA/AppData/MCP/Jarvis/trion/plugins';

class PluginEventEmitter extends EventEmitter implements EventAPI { }

export class PluginHost {
  private plugins: Map<string, PluginState> = new Map();
  private guards: Map<string, PermissionGuard> = new Map();
  private activePlugins: Map<string, TRIONPlugin> = new Map();
  private pluginEvents: Map<string, PluginEventEmitter> = new Map();

  // Callback to send messages to the bridge
  private bridgeCallback: (message: any) => void = () => { };

  constructor() {
    console.log('[PluginHost] Initializing...');
  }

  setBridgeCallback(cb: (message: any) => void) {
    this.bridgeCallback = cb;
  }

  /**
   * Load a plugin from manifest
   */
  async loadPlugin(manifestPath: string): Promise<boolean> {
    try {
      const manifestText = await Deno.readTextFile(manifestPath);
      const manifest = JSON.parse(manifestText) as PluginManifest;

      if (!validateManifest(manifest)) {
        console.error(`[PluginHost] Invalid manifest: ${manifestPath}`);
        return false;
      }

      // Check if already loaded
      if (this.plugins.has(manifest.id)) {
        console.warn(`[PluginHost] Plugin ${manifest.id} already loaded`);
        return false;
      }

      // Create permission guard
      const guard = new PermissionGuard(manifest);
      this.guards.set(manifest.id, guard);

      // Store plugin state
      this.plugins.set(manifest.id, {
        manifest,
        enabled: false,
        loaded: true
      });

      console.log(`[PluginHost] Loaded manifest: ${manifest.name} v${manifest.version}`);
      return true;
    } catch (error) {
      console.error(`[PluginHost] Failed to load ${manifestPath}:`, error);
      return false;
    }
  }

  /**
   * Enable a plugin
   */
  async enablePlugin(id: string): Promise<boolean> {
    const state = this.plugins.get(id);
    if (!state) {
      console.error(`[PluginHost] Plugin ${id} not found`);
      return false;
    }

    if (state.enabled) {
      console.warn(`[PluginHost] Plugin ${id} already enabled`);
      return true;
    }

    try {
      // 1. Dynamic Import
      // Assumption: plugin.ts is in the same directory using the ID
      // If we loaded from a different folder name, this might break.
      // But for now, we assume folder name == ID or at least standard structure.
      const modulePath = `${PLUGINS_DIR}/${id}/plugin.ts`;
      console.log(`[PluginHost] Importing plugin from ${modulePath}...`);

      const module = await import(modulePath);
      const PluginClass = module.default as PluginConstructor;

      // 2. Create Context
      const events = new PluginEventEmitter();
      this.pluginEvents.set(id, events);

      const context: PluginContext = {
        id,
        log: (...args: unknown[]) => console.log(`[${id}]`, ...args),
        events,
        panel: {
          createTab: async (tabId, title, type, options) => {
            this.bridgeCallback({ type: 'panel:create', payload: { pluginId: id, tabId, title, contentType: type, options } });
          },
          updateTab: async (tabId, content, append) => {
            this.bridgeCallback({ type: 'panel:update', payload: { tabId, content, append } });
          },
          closeTab: async (tabId) => {
            this.bridgeCallback({ type: 'panel:close', payload: { tabId } });
          },
          open: async () => { },
          close: async () => { }
        },
        getSetting: <T>(key: string) => undefined,
        setSetting: (key: string, value: unknown) => {
          console.log(`[${id}] Setting ${key} = ${value}`);
        },
        // Vault stub for now
        vault: undefined
      };

      // 3. Instantiate and Init
      console.log(`[PluginHost] Instantiating ${id}...`);
      const instance = new PluginClass(context);
      await instance.init();

      this.activePlugins.set(id, instance);

      state.enabled = true;
      console.log(`[PluginHost] Enabled: ${id}`);

      return true;
    } catch (error) {
      state.error = String(error);
      console.error(`[PluginHost] Failed to enable ${id}:`, error);
      return false;
    }
  }

  /**
   * Disable a plugin
   */
  async disablePlugin(id: string): Promise<boolean> {
    const state = this.plugins.get(id);
    if (!state || !state.enabled) return true;

    try {
      const instance = this.activePlugins.get(id);
      if (instance) {
        await instance.destroy();
        this.activePlugins.delete(id);
      }
      this.pluginEvents.delete(id);
      state.enabled = false;
      console.log(`[PluginHost] Disabled: ${id}`);
      return true;
    } catch (e) {
      console.error(`[PluginHost] Error disabling ${id}:`, e);
      return false;
    }
  }

  /**
   * Dispatch event to all enabled plugins
   */
  dispatchBackendEvent(eventType: string, data: unknown) {
    console.log(`[PluginHost] Dispatching ${eventType} to ${this.pluginEvents.size} plugins`);
    for (const [id, emitter] of this.pluginEvents) {
      try {
        emitter.emit(eventType, data);
      } catch (e) {
        console.error(`[PluginHost] Error dispatching to ${id}:`, e);
      }
    }
  }

  /**
   * Get all loaded plugins
   */
  getAll(): PluginState[] {
    return Array.from(this.plugins.values());
  }

  /**
   * Get a specific plugin
   */
  get(id: string): PluginState | undefined {
    return this.plugins.get(id);
  }

  /**
   * Discover plugins in the plugins directory
   */
  async discoverPlugins(): Promise<string[]> {
    const discovered: string[] = [];

    try {
      for await (const entry of Deno.readDir(PLUGINS_DIR)) {
        if (entry.isDirectory) {
          const manifestPath = `${PLUGINS_DIR}/${entry.name}/manifest.json`;
          try {
            await Deno.stat(manifestPath);
            discovered.push(manifestPath);
          } catch {
            // No manifest, skip
          }
        }
      }
    } catch (error) {
      console.error('[PluginHost] Failed to discover plugins:', error);
    }

    return discovered;
  }

  /**
   * Load all discovered plugins
   */
  async loadAll(): Promise<number> {
    const manifests = await this.discoverPlugins();
    let loaded = 0;

    for (const path of manifests) {
      if (await this.loadPlugin(path)) {
        loaded++;
      }
    }

    console.log(`[PluginHost] Loaded ${loaded} plugins`);

    // Auto-enable sequential-thinking for now (manual override for testing)
    // In a real system, we'd read this from a config file.
    if (this.plugins.has('sequential-thinking')) {
      await this.enablePlugin('sequential-thinking');
    }

    return loaded;
  }
}

// Export singleton
export const pluginHost = new PluginHost();

console.log('[TRION] Plugin host loaded');
