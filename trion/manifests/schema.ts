/**
 * TRION Plugin Manifest Schema
 * Defines the structure and permissions for all plugins
 */

// Security Tiers
export enum PluginTier {
  /** UI-only, no permissions needed */
  COMMUNITY = 1,
  /** Verified, limited vault access */
  VERIFIED = 2,
  /** System/Core, full access */
  SYSTEM = 3
}

// Permission Types
export interface PluginPermissions {
  /** Vault paths plugin can read from */
  read: VaultPath[];
  /** Vault paths plugin can write to */
  write: VaultPath[];
  /** Allowed network hosts */
  net: string[];
  /** Can access environment variables */
  env?: boolean;
}

// Valid Vault paths
export type VaultPath = 
  | 'memories'
  | 'images'
  | 'documents'
  | 'plugins'
  | 'mcp-servers'
  | 'audit'
  | `plugins/${string}`;

// Plugin Manifest
export interface PluginManifest {
  /** Unique plugin ID (kebab-case) */
  id: string;
  /** Display name */
  name: string;
  /** Semantic version */
  version: string;
  /** What the plugin does */
  description: string;
  /** Plugin author */
  author: string;
  /** Lucide icon name or emoji */
  icon: string;
  /** Security tier */
  tier: PluginTier;
  /** Required permissions (tier 2+) */
  permissions?: PluginPermissions;
  /** Plugin entry point */
  main: string;
  /** Minimum TRION version */
  trionVersion?: string;
}

// Runtime Plugin State
export interface PluginState {
  manifest: PluginManifest;
  enabled: boolean;
  loaded: boolean;
  instance?: unknown;
  error?: string;
}

// Validate manifest
export function validateManifest(manifest: unknown): manifest is PluginManifest {
  if (typeof manifest !== 'object' || manifest === null) return false;
  
  const m = manifest as Record<string, unknown>;
  
  // Required fields
  if (typeof m.id !== 'string') return false;
  if (typeof m.name !== 'string') return false;
  if (typeof m.version !== 'string') return false;
  if (typeof m.tier !== 'number') return false;
  if (m.tier < 1 || m.tier > 3) return false;
  
  // Tier 2+ requires permissions
  if (m.tier >= 2 && !m.permissions) return false;
  
  return true;
}

// Check if permission is valid for tier
export function isPermissionAllowed(
  tier: PluginTier,
  permission: keyof PluginPermissions,
  value: string
): boolean {
  // Tier 1: No permissions allowed
  if (tier === PluginTier.COMMUNITY) {
    return false;
  }
  
  // Tier 2: Limited permissions
  if (tier === PluginTier.VERIFIED) {
    // No mcp-servers or audit access
    if (permission === 'read' || permission === 'write') {
      if (value === 'mcp-servers' || value === 'audit') {
        return false;
      }
    }
    // Limited network (whitelist checked elsewhere)
    return true;
  }
  
  // Tier 3: Everything allowed
  return true;
}

console.log('[TRION] Manifest schema loaded');
