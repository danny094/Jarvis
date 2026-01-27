/**
 * tools.js - MCP Tools Management App
 * Features: Grid View, Drag & Drop Install, Context Menus, Details Modal
 */

import { getApiBase } from "../../static/js/api.js"; // Reuse core API logic
import { log } from "../../static/js/debug.js";

const els = {
    container: document.getElementById('app-tools'),
    dragOverlay: document.getElementById('drag-overlay')
};

/**
 * Initialize Tools App
 */
export async function initToolsApp() {
    log('info', 'Starting Tools App...');

    // Initial Render Skeleton
    renderSkeleton();

    // Setup Drag & Drop
    setupDragAndDrop();

    // Fetch & Render
    await loadMCPs();
}

/**
 * Load MCPs from Backend
 */
async function loadMCPs() {
    try {
        const res = await fetch(`${getApiBase()}/api/mcp/list`);
        if (!res.ok) throw new Error("Failed to load MCPs");

        const data = await res.json();
        renderGrid(data.mcps || []);

    } catch (e) {
        log('error', `Tools Load Error: ${e.message}`);
        els.container.innerHTML = `
            <div class="flex flex-col items-center justify-center h-full text-red-400">
                <i data-lucide="alert-circle" class="w-12 h-12 mb-4"></i>
                <h2 class="text-xl">Connection Failed</h2>
                <p class="text-sm opacity-70">${e.message}</p>
                <button onclick="initToolsApp()" class="mt-4 px-4 py-2 bg-dark-card border border-dark-border rounded hover:bg-dark-hover">Retry</button>
            </div>
        `;
        lucide.createIcons();
    }
}

/**
 * Setup Drag & Drop for MCP Installation
 */
function setupDragAndDrop() {
    const body = document.body;
    const overlay = els.dragOverlay;
    
    if (!overlay) {
        console.warn('[Tools] Drag overlay element not found');
        return;
    }

    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // Show overlay on drag enter
    ['dragenter', 'dragover'].forEach(eventName => {
        body.addEventListener(eventName, () => {
            if (overlay) overlay.classList.remove('hidden');
        }, false);
    });

    // Hide overlay on drag leave/drop
    ['dragleave', 'drop'].forEach(eventName => {
        body.addEventListener(eventName, () => {
            if (overlay) overlay.classList.add('hidden');
        }, false);
    });

    // Handle file drop
    body.addEventListener('drop', handleDrop, false);
    
    function handleDrop(e) {
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileUpload(files[0]);
        }
    }
}


/**
 * Render Skeleton Loading State
 */
function renderSkeleton() {
    els.container.innerHTML = `
        <div class="p-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 animate-pulse">
            ${Array(4).fill(0).map(() => `
                <div class="h-48 bg-dark-card border border-dark-border rounded-xl"></div>
            `).join('')}
        </div>
    `;
}

/**
 * Render MCP Grid
 * @param {Array} mcps 
 */
function renderGrid(mcps) {
    if (mcps.length === 0) {
        els.container.innerHTML = `
            <div class="flex flex-col items-center justify-center h-full text-gray-500">
                <i data-lucide="box" class="w-16 h-16 mb-4 opacity-50"></i>
                <h2 class="text-2xl font-light">No Tools Installed</h2>
                <p class="mt-2 text-sm">Drag & drop a .zip file here to install an MCP.</p>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    const html = `
        <div class="p-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 content-start h-full overflow-y-auto">
            ${mcps.map(mcp => {
        const initial = mcp.name.charAt(0).toUpperCase();

        return `
                <div class="mcp-card relative group bg-[#0a0a0a] border border-[#222] hover:border-accent-primary/50 transition-all rounded-xl p-6 flex flex-col justify-between shadow-lg hover:shadow-accent-primary/10 h-64 cursor-pointer"
                     onclick="openMCPDetails('${mcp.name}')"
                     oncontextmenu="handleContextMenu(event, '${mcp.name}')">
                    
                    <!-- Header -->
                    <div class="flex justify-between items-start mb-4">
                        <div class="w-10 h-10 rounded bg-[#151515] border border-[#333] flex items-center justify-center text-lg font-bold text-gray-300">
                            ${initial}
                        </div>
                        <div class="w-2 h-2 ${mcp.online ? 'bg-green-500' : 'bg-red-500'} rounded-full shadow-[0_0_8px_currentColor]"></div>
                    </div>

                    <!-- Info -->
                    <div class="flex-1">
                        <h3 class="font-bold text-lg text-gray-100 tracking-wide mb-1" title="${mcp.name}">${mcp.name}</h3>
                        <p class="text-xs text-gray-500 line-clamp-3 leading-relaxed">${mcp.description || 'No description available for this module.'}</p>
                    </div>

                    <!-- Meta -->
                    <div class="pt-4 border-t border-[#222] flex justify-between items-center text-[10px] text-gray-500 font-mono uppercase tracking-wider">
                        <span>${mcp.tools_count || 0} Tools</span>
                        <span>${mcp.transport || 'http'}</span>
                    </div>
                </div>
                `;
    }).join('')}
            
            <!-- Install Card -->
            <div class="border border-dashed border-[#333] hover:border-accent-primary/50 rounded-xl p-6 flex flex-col items-center justify-center text-gray-600 hover:text-accent-primary transition-colors cursor-pointer h-64 bg-transparent hover:bg-accent-primary/5 group"
                 onclick="document.getElementById('file-upload-hidden').click()">
                <i data-lucide="plus" class="w-8 h-8 mb-4 group-hover:scale-110 transition-transform"></i>
                <span class="text-xs font-medium uppercase tracking-widest">Install New</span>
            </div>
        </div>
        
        <!-- Hidden File Input for Click-Upload -->
        <input type="file" id="file-upload-hidden" class="hidden" accept=".zip" onchange="handleFileUpload(this.files[0])">
    `;

    els.container.innerHTML = html;
    lucide.createIcons();

    // Attach handlers to window
    window.handleContextMenu = handleContextMenu;
    window.toggleMCP = toggleMCP;
    window.handleFileUpload = handleFileUpload;
    window.openMCPDetails = openMCPDetails;
    window.closeMCPDetails = closeMCPDetails;

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // Show Overlay
    document.body.addEventListener('dragenter', () => {
        els.dragOverlay.classList.remove('hidden');
    });

    // Hide Overlay (careful with flickering)
    els.dragOverlay.addEventListener('dragleave', (e) => {
        if (e.target === els.dragOverlay) {
            els.dragOverlay.classList.add('hidden');
        }
    });

    // Drop
    document.body.addEventListener('drop', (e) => {
        els.dragOverlay.classList.add('hidden');
        const dt = e.dataTransfer;
        const files = dt.files;

        if (files.length > 0) {
            const file = files[0];
            if (file.name.endsWith('.zip')) {
                handleFileUpload(file);
            } else {
                showToast("Only .zip files are supported", "error");
            }
        }
    });
}

/**
 * Upload Logic
 */
async function handleFileUpload(file) {
    if (!file) return;

    showToast(`Installing ${file.name}...`, "info");

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch(`${getApiBase()}/api/mcp/install`, {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Install failed');
        }

        const data = await res.json();
        showToast("Installation successful!", "success");
        log('info', `Installed Data: ${JSON.stringify(data)}`);

        // Refresh Grid
        await loadMCPs();

    } catch (e) {
        showToast(`Install Failed: ${e.message}`, "error");
    }
}

/**
 * Toggle MCP Status
 */
async function toggleMCP(name) {
    showToast(`Toggling ${name}...`, "info");
    try {
        const res = await fetch(`${getApiBase()}/api/mcp/${name}/toggle`, {
            method: 'POST'
        });

        if (!res.ok) throw new Error("Toggle failed");

        const data = await res.json();
        const status = data.enabled ? "Enabled" : "Disabled";
        showToast(`${name} is now ${status}`, "success");

        // Refresh
        await loadMCPs();
    } catch (e) {
        showToast(`Toggle Error: ${e.message}`, "error");
    }
}

/**
 * Delete MCP
 */
async function deleteMCP(name) {
    if (!confirm(`Are you sure you want to delete '${name}'?`)) return;

    showToast(`Deleting ${name}...`, "info");
    try {
        const res = await fetch(`${getApiBase()}/api/mcp/${name}`, {
            method: 'DELETE'
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Delete failed");
        }

        showToast(`${name} deleted`, "success");
        await loadMCPs();
    } catch (e) {
        showToast(`Delete Error: ${e.message}`, "error");
    }
}

/**
 * Context Menu Logic
 */
let contextMenu = null;

function handleContextMenu(e, name) {
    e.preventDefault();
    e.stopPropagation();

    // Remove existing
    if (contextMenu) contextMenu.remove();

    // Create Menu
    contextMenu = document.createElement('div');
    contextMenu.className = 'fixed bg-dark-card border border-dark-border shadow-2xl rounded-lg py-2 w-48 z-[200] flex flex-col animate-in fade-in zoom-in-95 duration-100';
    contextMenu.style.left = `${e.clientX}px`;
    contextMenu.style.top = `${e.clientY}px`;

    // Actions
    const actions = [
        {
            label: 'Toggle On/Off',
            icon: 'power',
            onClick: () => toggleMCP(name)
        },
        {
            label: 'Delete',
            icon: 'trash-2',
            onClick: () => deleteMCP(name),
            danger: true
        }
    ];

    contextMenu.innerHTML = actions.map(action => `
        <button class="flex items-center gap-3 px-4 py-2 text-sm w-full text-left hover:bg-dark-hover transition-colors ${action.danger ? 'text-red-400 hover:text-red-300' : 'text-gray-200'}"
                data-action="${action.label}">
            <i data-lucide="${action.icon}" class="w-4 h-4"></i>
            <span>${action.label}</span>
        </button>
    `).join('');

    document.body.appendChild(contextMenu);
    lucide.createIcons();

    // Bind Clicks
    contextMenu.querySelectorAll('button').forEach((btn, index) => {
        btn.addEventListener('click', () => {
            actions[index].onClick();
            removeContextMenu();
        });
    });

    // Close on click outside
    document.addEventListener('click', removeContextMenu, { once: true });
}

function removeContextMenu() {
    if (contextMenu) {
        contextMenu.remove();
        contextMenu = null;
    }
}

/**
 * Open MCP Details Modal
 */
async function openMCPDetails(name) {
    log('info', `Opening details for MCP: ${name}`);
    
    // Remove existing modal
    const existing = document.getElementById('mcp-details-modal');
    if (existing) existing.remove();

    // Create modal with loading state
    const modal = document.createElement('div');
    modal.id = 'mcp-details-modal';
    modal.className = 'fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-[9999] p-4';
    modal.innerHTML = `
        <div class="bg-[#0a0a0a] border border-[#222] rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden shadow-2xl flex flex-col">
            <div class="p-6 flex items-center justify-center">
                <div class="animate-spin w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full"></div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeMCPDetails();
    });

    // Close on ESC
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            closeMCPDetails();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);

    // Fetch details
    try {
        const res = await fetch(`${getApiBase()}/api/mcp/${name}/details`);
        if (!res.ok) throw new Error("Failed to load details");

        const data = await res.json();
        const mcp = data.mcp;
        const tools = data.tools || [];

        // Render content
        const initial = mcp.name.charAt(0).toUpperCase();
        modal.innerHTML = `
            <div class="bg-[#0a0a0a] border border-[#222] rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden shadow-2xl flex flex-col">
                <!-- Header -->
                <div class="p-6 border-b border-[#222] flex items-start justify-between">
                    <div class="flex items-center gap-4">
                        <div class="w-14 h-14 rounded-xl bg-[#151515] border border-[#333] flex items-center justify-center text-2xl font-bold text-gray-300">
                            ${initial}
                        </div>
                        <div>
                            <h2 class="text-xl font-bold text-gray-100">${mcp.name}</h2>
                            <p class="text-sm text-gray-500 mt-1">${mcp.description || 'No description'}</p>
                        </div>
                    </div>
                    <button onclick="closeMCPDetails()" class="text-gray-500 hover:text-gray-300 transition-colors p-2">
                        <i data-lucide="x" class="w-5 h-5"></i>
                    </button>
                </div>

                <!-- Status Bar -->
                <div class="px-6 py-4 bg-[#080808] border-b border-[#222] flex items-center gap-6 text-xs font-mono">
                    <div class="flex items-center gap-2">
                        <div class="w-2 h-2 ${mcp.online ? 'bg-green-500' : 'bg-red-500'} rounded-full"></div>
                        <span class="text-gray-400">${mcp.online ? 'Online' : 'Offline'}</span>
                    </div>
                    <div class="text-gray-500">
                        <span class="text-gray-400">${tools.length}</span> Tools
                    </div>
                    <div class="text-gray-500">
                        Transport: <span class="text-gray-400">${mcp.transport}</span>
                    </div>
                    <div class="text-gray-500">
                        Tier: <span class="text-gray-400 uppercase">${mcp.tier}</span>
                    </div>
                    ${mcp.detected_format ? `
                    <div class="text-gray-500">
                        Format: <span class="text-gray-400">${mcp.detected_format}</span>
                    </div>
                    ` : ''}
                </div>

                <!-- Tools List -->
                <div class="flex-1 overflow-y-auto p-6">
                    <h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Available Tools</h3>
                    ${tools.length === 0 ? `
                        <div class="text-center py-8 text-gray-500">
                            <i data-lucide="package-x" class="w-12 h-12 mx-auto mb-3 opacity-50"></i>
                            <p>No tools discovered</p>
                        </div>
                    ` : `
                        <div class="space-y-3">
                            ${tools.map(tool => `
                                <div class="bg-[#111] border border-[#222] rounded-lg p-4 hover:border-[#333] transition-colors">
                                    <div class="flex items-start justify-between">
                                        <div class="flex-1">
                                            <h4 class="font-mono text-sm text-accent-primary">${tool.name}</h4>
                                            <p class="text-xs text-gray-500 mt-1 leading-relaxed">${tool.description || 'No description'}</p>
                                        </div>
                                        <i data-lucide="terminal" class="w-4 h-4 text-gray-600 flex-shrink-0 ml-4"></i>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    `}
                </div>

                <!-- Footer -->
                <div class="p-4 border-t border-[#222] bg-[#080808] flex justify-between items-center">
                    <span class="text-xs text-gray-600 font-mono">${mcp.url}</span>
                    <button onclick="closeMCPDetails()" class="px-4 py-2 text-sm bg-[#151515] hover:bg-[#1a1a1a] border border-[#333] rounded-lg text-gray-300 transition-colors">
                        Close
                    </button>
                </div>
            </div>
        `;
        lucide.createIcons();

    } catch (e) {
        log('error', `Failed to load MCP details: ${e.message}`);
        modal.innerHTML = `
            <div class="bg-[#0a0a0a] border border-[#222] rounded-2xl p-8 text-center">
                <i data-lucide="alert-circle" class="w-12 h-12 mx-auto mb-4 text-red-400"></i>
                <h2 class="text-lg font-bold text-gray-100 mb-2">Failed to Load</h2>
                <p class="text-sm text-gray-500 mb-4">${e.message}</p>
                <button onclick="closeMCPDetails()" class="px-4 py-2 bg-[#151515] hover:bg-[#1a1a1a] border border-[#333] rounded-lg text-gray-300 transition-colors">
                    Close
                </button>
            </div>
        `;
        lucide.createIcons();
    }
}

/**
 * Close MCP Details Modal
 */
function closeMCPDetails() {
    const modal = document.getElementById('mcp-details-modal');
    if (modal) modal.remove();
}

/**
 * Simple Toast Notification
 */
function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');

    const colors = {
        info: 'border-accent-primary text-gray-200 bg-dark-card',
        success: 'border-green-500 text-green-400 bg-dark-card',
        error: 'border-red-500 text-red-400 bg-dark-card'
    };

    toast.className = `px-4 py-3 rounded-lg border-l-4 shadow-xl flex items-center gap-3 transform transition-all duration-300 translate-y-2 opacity-0 ${colors[type]}`;
    toast.innerHTML = `
        <span class="font-mono text-sm">${msg}</span>
    `;

    container.appendChild(toast);

    // Animate In
    requestAnimationFrame(() => {
        toast.classList.remove('translate-y-2', 'opacity-0');
    });

    // Remove after 3s
    setTimeout(() => {
        toast.classList.add('translate-y-2', 'opacity-0');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
