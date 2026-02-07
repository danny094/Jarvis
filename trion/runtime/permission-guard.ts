/**
 * TRION Permission Guard
 * Enforces security boundaries for plugins
 */

import { PluginManifest, PluginTier, PluginPermissions } from '../manifests/schema.ts';

const VAULT_BASE = '/DATA/AppData/MCP/Jarvis/vault';

export class PermissionGuard {
  private manifest: PluginManifest;
  
  constructor(manifest: PluginManifest) {
    this.manifest = manifest;
  }
  
  /**
   * Get Deno permission flags for this plugin
   */
  getDenoFlags(): string[] {
    const flags: string[] = [];
    
    // Tier 1: Deny everything
    if (this.manifest.tier === PluginTier.COMMUNITY) {
      flags.push('--deny-read', '--deny-write', '--deny-net', '--deny-env', '--deny-run');
      return flags;
    }
    
    const perms = this.manifest.permissions;
    if (!perms) {
      flags.push('--deny-read', '--deny-write', '--deny-net', '--deny-env', '--deny-run');
      return flags;
    }
    
    // Read permissions
    if (perms.read && perms.read.length > 0) {
      const paths = perms.read.map(p => this.resolvePath(p)).join(',');
      flags.push(`--allow-read=${paths}`);
    } else {
      flags.push('--deny-read');
    }
    
    // Write permissions
    if (perms.write && perms.write.length > 0) {
      const paths = perms.write.map(p => this.resolvePath(p)).join(',');
      flags.push(`--allow-write=${paths}`);
    } else {
      flags.push('--deny-write');
    }
    
    // Network permissions
    if (perms.net && perms.net.length > 0) {
      flags.push(`--allow-net=${perms.net.join(',')}`);
    } else {
      flags.push('--deny-net');
    }
    
    // Environment variables
    if (perms.env) {
      flags.push('--allow-env');
    } else {
      flags.push('--deny-env');
    }
    
    // Never allow run (subprocess) for non-system
    if (this.manifest.tier !== PluginTier.SYSTEM) {
      flags.push('--deny-run');
    }
    
    return flags;
  }
  
  /**
   * Resolve vault path to absolute path
   */
  private resolvePath(vaultPath: string): string {
    // Handle plugin-specific paths
    if (vaultPath.startsWith('plugins/')) {
      return `${VAULT_BASE}/${vaultPath}`;
    }
    return `${VAULT_BASE}/${vaultPath}`;
  }
  
  /**
   * Check if plugin can access a path
   */
  canAccess(path: string, mode: 'read' | 'write'): boolean {
    if (this.manifest.tier === PluginTier.COMMUNITY) {
      return false;
    }
    
    const perms = this.manifest.permissions;
    if (!perms) return false;
    
    const allowedPaths = mode === 'read' ? perms.read : perms.write;
    if (!allowedPaths) return false;
    
    return allowedPaths.some(allowed => {
      const fullPath = this.resolvePath(allowed);
      return path.startsWith(fullPath);
    });
  }
  
  /**
   * Check if plugin can access a network host
   */
  canAccessNetwork(host: string): boolean {
    if (this.manifest.tier === PluginTier.COMMUNITY) {
      return false;
    }
    
    const perms = this.manifest.permissions;
    if (!perms || !perms.net) return false;
    
    return perms.net.includes(host) || perms.net.includes('*');
  }
  
  /**
   * Generate human-readable permission summary
   */
  getPermissionSummary(): string[] {
    const summary: string[] = [];
    
    if (this.manifest.tier === PluginTier.COMMUNITY) {
      summary.push('🔒 No permissions (UI only)');
      return summary;
    }
    
    const perms = this.manifest.permissions;
    if (!perms) return summary;
    
    if (perms.read && perms.read.length > 0) {
      summary.push(`📖 Read: ${perms.read.join(', ')}`);
    }
    
    if (perms.write && perms.write.length > 0) {
      summary.push(`✏️ Write: ${perms.write.join(', ')}`);
    }
    
    if (perms.net && perms.net.length > 0) {
      summary.push(`🌐 Network: ${perms.net.join(', ')}`);
    }
    
    if (perms.env) {
      summary.push('🔑 Environment variables');
    }
    
    return summary;
  }
}

console.log('[TRION] Permission guard loaded');
