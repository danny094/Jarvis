/**
 * TRION Plugin Base
 * Base interfaces and context for plugins
 */

// Plugin Setting Types
export interface PluginSetting {
  key: string;
  label: string;
  type: 'toggle' | 'number' | 'text' | 'select';
  default: unknown;
  description?: string;
  min?: number;
  max?: number;
  placeholder?: string;
  options?: Array<{ value: string; label: string }>;
}

// Panel API (exposed to plugins)
export interface PanelAPI {
  createTab(id: string, title: string, type: 'markdown' | 'text' | 'code', options?: {
    autoOpen?: boolean;
    content?: string;
  }): Promise<void>;
  
  updateTab(id: string, content: string, append?: boolean): Promise<void>;
  
  closeTab(id: string): Promise<void>;
  
  open(mode?: 'half' | 'full'): Promise<void>;
  
  close(): Promise<void>;
}

// Event Emitter API
export interface EventAPI {
  on(event: string, handler: (data: unknown) => void): void;
  off(event: string, handler: (data: unknown) => void): void;
  emit(event: string, data: unknown): void;
}

// Vault API (for Tier 2+ plugins)
export interface VaultAPI {
  read(path: string): Promise<string>;
  write(path: string, data: string): Promise<void>;
  list(path: string): Promise<string[]>;
  exists(path: string): Promise<boolean>;
}

// Plugin Context (passed to plugin constructor)
export interface PluginContext {
  /** Plugin ID */
  id: string;
  /** Panel API for UI */
  panel: PanelAPI;
  /** Event system */
  events: EventAPI;
  /** Vault access (Tier 2+ only) */
  vault?: VaultAPI;
  /** Get plugin setting */
  getSetting<T>(key: string): T | undefined;
  /** Set plugin setting */
  setSetting(key: string, value: unknown): void;
  /** Logger */
  log: (...args: unknown[]) => void;
}

// Plugin Interface
export interface TRIONPlugin {
  /** Called when plugin is enabled */
  init(): Promise<void>;
  
  /** Called when plugin is disabled */
  destroy(): Promise<void>;
  
  /** Return plugin settings schema */
  getSettings?(): PluginSetting[];
  
  /** Called when a setting changes */
  onSettingChange?(key: string, value: unknown): void;
}

// Plugin Constructor Type
export type PluginConstructor = new (ctx: PluginContext) => TRIONPlugin;

console.log('[TRION] Plugin base loaded');
