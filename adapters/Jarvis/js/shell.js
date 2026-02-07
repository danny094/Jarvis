/**
 * shell.js - App Shell Architecture
 * Manages Sidebar, Viewports, and Global State
 */

import { initApp } from "../static/js/app.js";
import { initToolsApp } from "./apps/tools.js";

// Global State
const state = {
    activeApp: 'chat',
    debugOpen: false,
    maintenanceOpen: false,
    toolsLoaded: false,
    protocolLoaded: false,
    terminalLoaded: false
};

// DOM Elements
const els = {
    launcher: document.getElementById('launcher'),
    viewport: document.getElementById('app-viewport'),
    windows: {
        chat: document.getElementById('app-chat'),
        tools: document.getElementById('app-tools'),
        settings: document.getElementById('app-settings'),
        protocol: document.getElementById('app-protocol'),
        terminal: document.getElementById('app-terminal')
    },
    debugBtn: document.getElementById('debug-toggle-btn'),
    maintenanceBtn: document.getElementById('maintenance-trigger'),
    debugPanel: document.getElementById('debug-panel')
};

/**
 * Initialize the Shell
 */
function initShell() {
    console.log("🖥️ TR/ON Shell Initializing V4 (Race Condition Fix)...");

    try {
        // 1. Setup Navigation
        setupLauncher();
        console.log("✅ Launcher Setup Complete");

        // 2. Setup Global Overlays
        setupOverlays();
        console.log("✅ Overlays Setup Complete");

        // 4. Setup Launchpad
        setupLaunchpad();
        console.log("✅ Launchpad Setup Complete");

        // 5. Setup Settings Navigation
        setupSettingsNav();
        console.log("✅ Settings Nav Setup Complete");

        // Show Boot Toast
        showToast("System Online", "success");

        // Protocol badge polling (every 60s)
        startProtocolBadgePolling();

    } catch (e) {
        console.error("CRITICAL SHELL ERROR:", e);
        alert("Shell Error: " + e.message);
    }

    // 3. Initialize Core App Logic (Legacy Chat)
    // Note: initApp handles chat, models, connection check
    initApp().then(() => {
        console.log("✅ Core System Ready");
    }).catch(e => console.error("Core Init Failed:", e));
}

// Simple Toast Helper (Duplicate from tools.js for now to ensure availability)
function showToast(msg, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        console.warn("Toast container missing");
        return;
    }
    const toast = document.createElement('div');
    const colors = {
        info: 'border-accent-primary text-gray-200 bg-dark-card',
        success: 'border-green-500 text-green-400 bg-dark-card',
        error: 'border-red-500 text-red-400 bg-dark-card'
    };
    toast.className = `px-4 py-3 rounded-lg border-l-4 shadow-xl flex items-center gap-3 transform transition-all duration-300 translate-y-2 opacity-0 ${colors[type] || colors.info}`;
    toast.innerHTML = `<span class="font-mono text-sm">${msg}</span>`;
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.remove('translate-y-2', 'opacity-0'));
    setTimeout(() => {
        toast.classList.add('translate-y-2', 'opacity-0');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/**
 * Setup Sidebar Launcher Click Handlers
 */
function setupLauncher() {
    const buttons = els.launcher.querySelectorAll('.launcher-icon[data-app]');

    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            const appName = btn.dataset.app;
            if (appName) {
                switchApp(appName);
            }
        });
    });

    // Launchpad Trigger
    const lpBtn = document.getElementById('launchpad-trigger');
    if (lpBtn) {
        lpBtn.addEventListener('click', () => {
            toggleLaunchpad(true);
        });
    }

    // Launchpad Search Close (Escape key)
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            toggleLaunchpad(false);
            const settingsModal = document.getElementById('settings-panel');
            if (settingsModal && !settingsModal.classList.contains('hidden')) {
                settingsModal.classList.add('hidden');
            }
        }
    });
}


/**
 * Launchpad Logic
 */
function toggleLaunchpad(show) {
    const lp = document.getElementById('launchpad-panel');
    if (!lp) return;

    if (show) {
        lp.classList.remove('hidden');
        document.getElementById('launchpad-search').focus();
    } else {
        lp.classList.add('hidden');
    }
}

function setupLaunchpad() {
    const apps = document.querySelectorAll('.launchpad-app');

    apps.forEach(app => {
        app.addEventListener('click', () => {
            const action = app.dataset.action;
            if (!action) return;

            const [type, target] = action.split(':');

            // Close Launchpad
            toggleLaunchpad(false);

            // Routing
            if (type === 'app') {
                switchApp(target);
            } else if (type === 'modal') {
                if (target === 'maintenance') {
                    const modal = document.getElementById('maintenance-modal');
                    modal.classList.remove('hidden');
                    // Dynamic Import to load logic on demand
                    import('./apps/maintenance.js')
                        .then(module => {
                            if (module.initMaintenanceApp) {
                                module.initMaintenanceApp();
                            }
                        })
                        .catch(err => console.error("Failed to load Maintenance App:", err));
                } else if (target === 'skills') {
                    const modal = document.getElementById('skills-modal');
                    modal.classList.remove('hidden');
                    // Dynamic Import to load Skills App
                    import('./apps/skills.js')
                        .then(module => {
                            if (module.initSkillsApp) {
                                module.initSkillsApp();
                            }
                        })
                        .catch(err => console.error("Failed to load Skills App:", err));
                }
            } else if (type === 'toggle') {
                if (target === 'debug') {
                    // Trigger debug toggle
                    document.getElementById('debug-toggle-btn').click();
                }
            } else if (type === 'toast') {
                // Assuming showToast is globally available or we can access it via tools.js?
                // Creating a simplified local toast for now or just log
                console.log(`Action: ${target}`);
                alert(`App "${target}" is coming soon!`);
            }
        });
    });
}

/**
 * Settings Logic
 */
function setupOverlays() {
    // OLD Debug and Maintenance triggers moved to setupLaunchpad or remaining as fallbacks
    // Profile Button -> Settings
    const profileBtn = document.getElementById('profile-btn');
    if (profileBtn) {
        profileBtn.addEventListener('click', () => {
            document.getElementById('settings-panel').classList.remove('hidden');
            // Lazy Load Settings App
            import('./apps/settings.js')
                .then(module => {
                    if (module.initSettingsApp) {
                        module.initSettingsApp();
                    }
                })
                .catch(err => console.error("Failed to load Settings App:", err));
        });
    }

    const closeSettings = document.getElementById('close-settings-btn');
    if (closeSettings) {
        closeSettings.addEventListener('click', () => {
            document.getElementById('settings-panel').classList.add('hidden');
        });
    }

    // Wire up simple Debug Panel Close
    const closeDebug = document.getElementById('close-debug-btn');
    if (closeDebug) {
        closeDebug.addEventListener('click', () => {
            document.getElementById('debug-panel').classList.add('translate-x-full');
        });
    }

    // Wire up simple Maintenance Panel Close
    const closeMaint = document.getElementById('close-maintenance-btn');
    if (closeMaint) {
        closeMaint.addEventListener('click', () => {
            document.getElementById('maintenance-modal').classList.add('hidden');
        });
    }

    // Wire up Skills Panel Close
    const closeSkills = document.getElementById('close-skills-btn');
    if (closeSkills) {
        closeSkills.addEventListener('click', () => {
            document.getElementById('skills-modal').classList.add('hidden');
        });
    }
}

function setupSettingsNav() {
    const navItems = document.querySelectorAll('.settings-category');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            // UI Update
            navItems.forEach(n => n.classList.remove('active'));
            item.classList.add('active');

            // Page Switch
            const category = item.dataset.category;
            document.querySelectorAll('.settings-page').forEach(page => page.classList.add('hidden'));

            const targetPage = document.getElementById(`page-${category}`);
            if (targetPage) {
                targetPage.classList.remove('hidden');

                // Plugin Tab: Initialize UI
                if (category === 'plugins' && window.PluginSettingsUI) {
                    const container = document.getElementById('plugins-container');
                    if (container) window.PluginSettingsUI.render(container);
                }
            } else {
                // Fallback for empty pages
                // Create temp page if doesn't exist just to show title
                let container = document.getElementById('settings-content-area');
                // Remove any temp pages? No, simpler to just have them in HTML or create placeholders
                console.warn(`Page for ${category} not found`);
            }
        });
    });
}

/**
 * Switch Active App Viewport
 * @param {string} appName
 */
function switchApp(appName) {
    if (state.activeApp === appName) return;

    console.log(`🔄 Switching to App: ${appName}`);

    // Update State
    state.activeApp = appName;

    // Update Sidebar UI
    els.launcher.querySelectorAll('.launcher-icon[data-app]').forEach(btn => {
        if (btn.dataset.app === appName) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Update Viewport UI
    Object.values(els.windows).forEach(win => {
        win.classList.add('hidden');
        win.classList.remove('active');
    });

    const targetWin = els.windows[appName];
    if (targetWin) {
        targetWin.classList.remove('hidden');
        // Slight delay for fade-in effect if we add css transitions later
        setTimeout(() => targetWin.classList.add('active'), 10);
    }

    // Lazy Load Apps
    if (appName === 'tools') {
        if (!state.toolsLoaded) {
            initToolsApp();
            state.toolsLoaded = true;
        }
    }

    if (appName === 'protocol') {
        if (!state.protocolLoaded) {
            import('./apps/protocol.js')
                .then(module => {
                    if (module.initProtocolApp) {
                        module.initProtocolApp();
                    }
                    state.protocolLoaded = true;
                })
                .catch(err => console.error("Failed to load Protocol App:", err));
        } else {
            // Refresh on re-visit
            import('./apps/protocol.js')
                .then(module => {
                    if (module.initProtocolApp) module.initProtocolApp();
                })
                .catch(() => {});
        }
    }

    if (appName === 'settings') {
        // Instead of showing placeholder, open the modal
        document.getElementById('settings-panel').classList.remove('hidden');

        // Lazy Load Settings App
        import('./apps/settings.js')
            .then(module => {
                if (module.initSettingsApp) {
                    module.initSettingsApp();
                }
            })
            .catch(err => console.error("Failed to load Settings App:", err));

        // Reset sidebar active state since settings is a modal
        els.launcher.querySelectorAll('.launcher-icon').forEach(btn => btn.classList.remove('active'));
    }

    if (appName === 'terminal') {
        if (!state.terminalLoaded) {
            import('./apps/terminal.js')
                .then(module => {
                    if (module.init) {
                        module.init();
                    }
                    state.terminalLoaded = true;
                })
                .catch(err => console.error("Failed to load Terminal App:", err));
        }
    }
}




/**
 * Protocol Badge Polling
 */
function startProtocolBadgePolling() {
    // Initial check
    pollProtocolBadge();
    // Poll every 60 seconds
    setInterval(pollProtocolBadge, 60000);
}

async function pollProtocolBadge() {
    try {
        const resp = await fetch(`http://${window.location.hostname}:8200/api/protocol/unmerged-count`);
        const data = await resp.json();
        const count = data.unmerged_count || 0;

        // Update launchpad badge
        const badge = document.getElementById("proto-badge");
        if (badge) {
            if (count > 0) {
                badge.textContent = count;
                badge.classList.remove("hidden");
            } else {
                badge.classList.add("hidden");
            }
        }

        // Update sidebar badge
        const sidebarBadge = document.getElementById("proto-sidebar-badge");
        if (sidebarBadge) {
            if (count > 0) {
                sidebarBadge.textContent = count;
                sidebarBadge.classList.remove("hidden");
            } else {
                sidebarBadge.classList.add("hidden");
            }
        }
    } catch {
        // silent
    }
}


// Start Shell (Handle Race Condition)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initShell);
} else {
    // Document already ready
    initShell();
}
