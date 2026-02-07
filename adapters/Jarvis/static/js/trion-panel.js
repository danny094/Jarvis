/**
 * ╔═══════════════════════════════════════════════════════════════╗
 * ║           TRION SIDE-PANEL - Universal Tab System            ║
 * ║                    Core Architecture v1.0                     ║
 * ╚═══════════════════════════════════════════════════════════════╝
 * 
 * Purpose: Observability Surface for AI Planning & Execution
 * 
 * Features:
 * - Tab-based system (like browser tabs)
 * - Multiple renderers (Markdown, Code, SVG, Custom)
 * - 3-state panel (closed/half/full)
 * - Extension API for MCPs
 * - Live content streaming
 * - Download support
 * 
 * Architecture:
 * ┌─────────────────────────────────────────┐
 * │   TRIONPanel (window.TRIONPanel)       │
 * ├─────────────────────────────────────────┤
 * │  - Tab Management                       │
 * │  - Content Rendering                    │
 * │  - State Management (closed/half/full)  │
 * │  - Event System                         │
 * │  - Extension Registry                   │
 * └─────────────────────────────────────────┘
 */

class TRIONPanel {
    constructor() {
        // DOM Elements
        this.panel = null;
        this.tabBar = null;
        this.contentArea = null;
        this.handle = null;

        // State
        this.state = 'closed'; // closed, half, full
        this.tabs = new Map(); // tabId -> {id, title, type, content, element, renderer}
        this.activeTabId = null;

        // Drag State
        this.isDragging = false;
        this.startX = 0;
        this.startWidth = 0;
        this.dragStartTime = 0;

        // Renderer Registry
        this.renderers = new Map(); // type -> {render, update, fileExtension}

        // Extension Registry
        this.extensions = new Map(); // name -> {tabConfig, renderer, onActivate, onDeactivate}

        // Event Emitter
        this.listeners = new Map(); // event -> [callbacks]

        // Pending updates for race condition handling
        this.pendingUpdates = new Map(); // tabId -> content

        this.init();
    }

    /**
     * Initialize panel and register default renderers
     */
    init() {
        console.log('[TRIONPanel] Initializing Universal Side-Panel...');

        // Create DOM structure
        this.createPanelDOM();

        // Register default renderers
        this.registerDefaultRenderers();

        // Attach event listeners
        this.attachEventListeners();

        // Expose globally
        window.TRIONPanel = this;

        console.log('[TRIONPanel] ✅ Initialized successfully');
    }

    /**
     * Create panel DOM structure
     */
    createPanelDOM() {
        // Main panel container
        this.panel = document.createElement('div');
        this.panel.id = 'trion-panel';
        this.panel.className = 'trion-panel';
        this.panel.setAttribute('data-state', 'closed');

        // Resize handle
        this.handle = document.createElement('div');
        this.handle.className = 'trion-handle';
        this.handle.innerHTML = `
            <div class="trion-handle-icon">
                <i data-lucide="panel-right"></i>
            </div>
        `;

        // Tab bar
        this.tabBar = document.createElement('div');
        this.tabBar.className = 'trion-tabs';

        // Add new tab button
        const addTabBtn = document.createElement('button');
        addTabBtn.className = 'trion-tab-add';
        addTabBtn.innerHTML = '<i data-lucide="plus"></i>';
        addTabBtn.title = 'Extension-managed tabs only';
        addTabBtn.disabled = true; // Tabs are created via API, not by user
        this.tabBar.appendChild(addTabBtn);

        // Content area
        this.contentArea = document.createElement('div');
        this.contentArea.className = 'trion-content';

        // Empty state
        const emptyState = document.createElement('div');
        this.emptyState = emptyState;
        emptyState.className = 'trion-empty-state';
        emptyState.innerHTML = `
            <i data-lucide="layers"></i>
            <p>No active tasks</p>
            <small>Tabs will appear here when AI starts planning</small>
        `;
        this.contentArea.appendChild(emptyState);

        // Assemble
        this.panel.appendChild(this.handle);
        this.panel.appendChild(this.tabBar);
        this.panel.appendChild(this.contentArea);

        // Add to DOM
        document.body.appendChild(this.panel);

        // Re-initialize Lucide icons
        if (window.lucide) {
            window.lucide.createIcons();
        }
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        // Handle interactions (Click vs Drag)
        this.handle.addEventListener('mousedown', (e) => this.startDrag(e));

        // Prevent default drag behavior
        this.handle.addEventListener('dragstart', (e) => e.preventDefault());

        // Global mouse events for dragging
        document.addEventListener('mousemove', (e) => this.onDrag(e));
        document.addEventListener('mouseup', (e) => this.stopDrag(e));

        // Keyboard shortcut: Ctrl+Shift+P
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.shiftKey && e.key === 'P') {
                e.preventDefault();
                this.toggle();
            }
        });
    }

    /**
     * Start dragging the handle
     */
    startDrag(e) {
        console.log('[TRION] startDrag', e.clientX);
        this.isDragging = true;
        this.startX = e.clientX;
        // Current width or default 400
        const rect = this.panel.getBoundingClientRect();
        this.startWidth = rect.width;
        this.dragStartTime = Date.now();

        this.panel.style.transition = 'none'; // Disable transition during drag
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        // Ensure panel is visible/flex if it was closed or hidden
        if (this.state === 'closed') {
            this.panel.style.display = 'flex';
        }
    }

    /**
     * Handle drag movement
     */
    onDrag(e) {
        if (!this.isDragging) return;

        // Calculate new width (from right edge)
        let newWidth = window.innerWidth - e.clientX;

        // Constraints
        const MIN_WIDTH = 300;
        const MAX_WIDTH = window.innerWidth - 50;

        if (newWidth < 50) { // Snap to close threshold
            newWidth = 0;
            this.handle.style.opacity = '0.5'; // Visual feedback
        } else {
            this.handle.style.opacity = '1';

            if (newWidth < MIN_WIDTH) newWidth = MIN_WIDTH;
            if (newWidth > MAX_WIDTH) newWidth = MAX_WIDTH;
        }

        // Apply width
        // If we are dragging from closed, we must manually override the transform style immediately
        if (newWidth > 0) {
            this.panel.style.width = `${newWidth}px`;
            this.panel.style.transform = 'translateX(0)';

            if (this.state !== 'custom') {
                this.state = 'custom';
                this.panel.setAttribute('data-state', 'custom');
            }
        } else {
            // Visual close preview
            this.panel.style.transform = 'translateX(calc(100% - 48px))';
        }
    }

    /**
     * Stop dragging
     */
    stopDrag(e) {
        if (!this.isDragging) return;
        console.log('[TRION] stopDrag');

        this.isDragging = false;
        this.panel.style.transition = ''; // Restore transition
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        this.handle.style.opacity = '';

        // Check if it was a click (short duration, small movement)
        const duration = Date.now() - this.dragStartTime;
        const moved = Math.abs(e.clientX - this.startX);

        if (duration < 200 && moved < 5) {
            this.toggle(); // Treat as click
            return;
        }

        // Finalize state
        const currentWidth = parseInt(this.panel.style.width || 0);
        if (currentWidth < 100) {
            this.close();
            // Clean up inline styles to let CSS take over for closed state
            this.panel.style.width = '';
            this.panel.style.transform = '';
        } else {
            this.state = 'custom';
            this.panel.setAttribute('data-state', 'open'); // Use 'open' for CSS consistency if 'custom' class doesn't exist
            this.updateHandleIcon();
            this.emit('panel-resize', { width: currentWidth });
        }
    }

    /**
     * Register default renderers
     */
    registerDefaultRenderers() {
        // Plain Text Renderer
        this.registerRenderer('text', {
            render: (content, container) => {
                const pre = document.createElement('pre');
                pre.textContent = content;
                container.appendChild(pre);
            },
            update: (content, container, append) => {
                const pre = container.querySelector('pre') || document.createElement('pre');
                if (append) {
                    pre.textContent += content;
                } else {
                    pre.textContent = content;
                }
                if (!pre.parentElement) container.appendChild(pre);
            },
            fileExtension: '.txt'
        });

        // Markdown Renderer (placeholder - will be enhanced in Phase 3)
        this.registerRenderer('markdown', {
            render: (content, container) => {
                // For now, use basic rendering
                // Phase 3 will add marked.js
                const div = document.createElement('div');
                div.className = 'markdown-content';
                div.innerHTML = this.basicMarkdownToHTML(content);
                    if (window.Prism) Prism.highlightAllUnder(container);
                container.appendChild(div);
                if (window.Prism) Prism.highlightAllUnder(container);
            },
            update: (content, container, append) => {
                let div = container.querySelector('.markdown-content');
                if (!div) {
                    div = document.createElement('div');
                    div.className = 'markdown-content';
                    container.appendChild(div);
                if (window.Prism) Prism.highlightAllUnder(container);
                }
                if (append) {
                    div.innerHTML += this.basicMarkdownToHTML(content);
                } else {
                    div.innerHTML = this.basicMarkdownToHTML(content);
                    if (window.Prism) Prism.highlightAllUnder(container);
                }
            },
            fileExtension: '.md'
        });

        // Code Renderer
        this.registerRenderer('code', {
            render: (content, container) => {
                const pre = document.createElement('pre');
                const code = document.createElement('code');
                code.textContent = content;
                pre.appendChild(code);
                container.appendChild(pre);
            },
            update: (content, container, append) => {
                let pre = container.querySelector('pre');
                let code = pre ? pre.querySelector('code') : null;

                if (!pre || !code) {
                    pre = document.createElement('pre');
                    code = document.createElement('code');
                    pre.appendChild(code);
                    container.appendChild(pre);
                }

                if (append) {
                    code.textContent += content;
                } else {
                    code.textContent = content;
                }
            },
            fileExtension: '.txt'
        });
    }

    /**
     * Basic Markdown to HTML converter (Phase 1 - minimal)
     * Phase 3 will replace with marked.js
     */
    basicMarkdownToHTML(md) {
        return md
            .replace(/^### (.*$)/gim, '<h3>$1</h3>')
            .replace(/^## (.*$)/gim, '<h2>$1</h2>')
            .replace(/^# (.*$)/gim, '<h1>$1</h1>')
            .replace(/\*\*(.*)\*\*/gim, '<strong>$1</strong>')
            .replace(/\*(.*)\*/gim, '<em>$1</em>')
            .replace(/\n/gim, '<br>');
    }

    // ═══════════════════════════════════════════════════════════
    // PUBLIC API - Tab Management
    // ═══════════════════════════════════════════════════════════

    /**
     * Create a new tab
     * @param {string} id - Unique tab identifier
     * @param {string} title - Tab title
     * @param {string} type - Content type (markdown, code, text, svg, custom)
     * @param {Object} options - {autoOpen: bool, content: string}
     * @returns {boolean} Success status
     */
    createTab(id, title, type = 'markdown', options = {}) {
        if (this.tabs.has(id)) {
            console.warn(`[TRIONPanel] Tab ${id} already exists`);
            return false;
        }

        console.log(`[TRIONPanel] Creating tab: ${id} (${type})`);

        // Create tab button
        const tabBtn = document.createElement('button');
        tabBtn.className = 'trion-tab';
        tabBtn.setAttribute('data-tab-id', id);
        tabBtn.innerHTML = `
            <span class="trion-tab-title">${this.escapeHTML(title)}</span>
            <button class="trion-tab-close" title="Close tab">
                <i data-lucide="x"></i>
            </button>
        `;

        // Insert before [+] button
        const addBtn = this.tabBar.querySelector('.trion-tab-add');
        this.tabBar.insertBefore(tabBtn, addBtn);

        // Create content container
        const contentDiv = document.createElement('div');
        contentDiv.className = 'trion-tab-content';
        contentDiv.setAttribute('data-tab-id', id);
        contentDiv.style.display = 'none';
        this.contentArea.appendChild(contentDiv);

        // Get renderer
        const renderer = this.renderers.get(type) || this.renderers.get('text');

        // Store tab data
        this.tabs.set(id, {
            id,
            title,
            type,
            content: options.content || '',
            element: contentDiv,
            tabButton: tabBtn,
            renderer
        });

        // Tab click handler
        tabBtn.addEventListener('click', (e) => {
            if (!e.target.closest('.trion-tab-close')) {
                this.switchTab(id);
            }
        });

        // Close button handler
        const closeBtn = tabBtn.querySelector('.trion-tab-close');
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.closeTab(id);
        });

        // Re-initialize Lucide icons
        if (window.lucide) {
            window.lucide.createIcons();
        }

        // Render initial content if provided
        if (options.content) {
            this.updateContent(id, options.content, false);
        }

        // Auto-open if requested
        if (options.autoOpen) {
            this.switchTab(id);
            if (this.state === 'closed') {
                this.open('half');
            }
        }

        // Apply pending updates if any
        if (this.pendingUpdates.has(id)) {
            this.updateContent(id, this.pendingUpdates.get(id), true);
            this.pendingUpdates.delete(id);
        }

        // Emit event
        this.emit('tab-created', { id, title, type });

        // Hide empty state
        const emptyState = this.contentArea.querySelector('.trion-empty-state');
        if (emptyState) {
            emptyState.style.display = 'none';
        }

        return true;
    }

    /**
     * Switch to a specific tab
     * @param {string} id - Tab ID
     */
    switchTab(id) {
        if (!this.tabs.has(id)) {
            console.warn(`[TRIONPanel] Tab ${id} not found`);
            return;
        }

        console.log(`[TRIONPanel] Switching to tab: ${id}`);

        // Deactivate current tab
        if (this.activeTabId) {
            const oldTab = this.tabs.get(this.activeTabId);
            if (oldTab) {
                oldTab.tabButton.classList.remove('active');
                oldTab.element.style.display = 'none';
            }
        }

        // Activate new tab
        const newTab = this.tabs.get(id);
        newTab.tabButton.classList.add('active');
        newTab.element.style.display = 'block';

        this.activeTabId = id;

        // Emit event
        this.emit('tab-change', { id });
    }

    /**
     * Update tab content
     * @param {string} id - Tab ID
     * @param {string} content - New content
     * @param {boolean} append - Append or replace
     */
    updateContent(id, content, append = false) {
        const tab = this.tabs.get(id);

        if (!tab) {
            // Tab doesn't exist yet - store for later
            console.warn(`[TRIONPanel] Tab ${id} not found - storing update for later`);
            this.pendingUpdates.set(id, content);
            return;
        }

        // Update stored content
        if (append) {
            tab.content += content;
        } else {
            tab.content = content;
        }

        // Render content
        if (tab.renderer.update) {
            tab.renderer.update(content, tab.element, append);
        } else {
            // Fallback: clear and re-render
            tab.element.innerHTML = '';
            tab.renderer.render(tab.content, tab.element);
        }

        // Re-initialize Lucide icons if needed
        if (window.lucide && tab.element.querySelector('[data-lucide]')) {
            window.lucide.createIcons();
        }

        // Emit event
        this.emit('content-update', { id, content, append });
    }

    /**
     * Close a tab
     * @param {string} id - Tab ID
     */
    closeTab(id) {
        const tab = this.tabs.get(id);
        if (!tab) return;

        console.log(`[TRIONPanel] Closing tab: ${id}`);

        // Remove from DOM
        tab.tabButton.remove();
        tab.element.remove();

        // Remove from map
        this.tabs.delete(id);

        // If this was the active tab, switch to another
        if (this.activeTabId === id) {
            const remainingTabs = Array.from(this.tabs.keys());
            if (remainingTabs.length > 0) {
                this.switchTab(remainingTabs[0]);
            } else {
                this.activeTabId = null;
                // Show empty state
                const emptyState = this.contentArea.querySelector('.trion-empty-state');
                if (emptyState) {
                    emptyState.style.display = 'block';
                }
            }
        }

        // Emit event
        this.emit('tab-closed', { id });
    }

    // ═══════════════════════════════════════════════════════════
    // PUBLIC API - Panel State
    // ═══════════════════════════════════════════════════════════

    /**
     * Open panel
     * @param {string} width - 'half' or 'full'
     */
    open(width = 'half') {
        if (width !== 'half' && width !== 'full') {
            width = 'half';
        }

        console.log(`[TRIONPanel] Opening panel: ${width}`);
        this.state = width;
        this.panel.setAttribute('data-state', width);
        this.updateHandleIcon();

        // Emit event
        this.emit('panel-open', { state: width });
    }

    /**
     * Close panel
     */
    close() {
        console.log('[TRIONPanel] Closing panel');
        this.state = 'closed';
        this.panel.setAttribute('data-state', 'closed');
        this.updateHandleIcon();

        // Emit event
        this.emit('panel-close', {});
    }

    /**
     * Toggle panel state
     */
    toggle() {
        if (this.state === 'closed') {
            this.open('half');
        } else if (this.state === 'half') {
            this.open('full');
        } else {
            this.close();
        }
    }

    /**
     * Update handle icon based on state
     */
    updateHandleIcon() {
        const icon = this.handle.querySelector('[data-lucide]');
        if (!icon) return;

        const iconMap = {
            'closed': 'panel-right',
            'half': 'panel-right-open',
            'full': 'panel-left',
        };

        icon.setAttribute('data-lucide', iconMap[this.state] || 'panel-right');

        if (window.lucide) {
            window.lucide.createIcons();
        }
    }

    // ═══════════════════════════════════════════════════════════
    // PUBLIC API - Renderers & Extensions
    // ═══════════════════════════════════════════════════════════

    /**
     * Register a custom renderer
     * @param {string} type - Renderer type
     * @param {Object} renderer - {render, update?, fileExtension}
     */
    registerRenderer(type, renderer) {
        console.log(`[TRIONPanel] Registering renderer: ${type}`);
        this.renderers.set(type, renderer);
    }

    /**
     * Register an extension (for MCPs)
     * @param {string} name - Extension name
     * @param {Object} config - {tabConfig, renderer, onActivate, onDeactivate}
     */
    registerExtension(name, config) {
        console.log(`[TRIONPanel] Registering extension: ${name}`);
        this.extensions.set(name, config);

        // Auto-create tab if provided
        if (config.tabConfig) {
            const { title, type, icon } = config.tabConfig;
            // Extensions can create their tabs on demand
        }

        // Call activation hook
        if (config.onActivate) {
            config.onActivate();
        }
    }

    // ═══════════════════════════════════════════════════════════
    // PUBLIC API - Downloads
    // ═══════════════════════════════════════════════════════════

    /**
     * Download tab content as file
     * @param {string} id - Tab ID
     * @param {string} filename - Optional filename
     */
    downloadTab(id, filename = null) {
        const tab = this.tabs.get(id);
        if (!tab) {
            console.warn(`[TRIONPanel] Tab ${id} not found`);
            return;
        }

        const ext = tab.renderer.fileExtension || '.txt';
        const name = filename || `${tab.title.replace(/\s+/g, '_')}${ext}`;

        const blob = new Blob([tab.content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        a.click();

        URL.revokeObjectURL(url);

        console.log(`[TRIONPanel] Downloaded: ${name}`);
        this.emit('download', { id, filename: name });
    }

    /**
     * Download all tabs as archive (future enhancement)
     */
    downloadAllTabs() {
        console.warn('[TRIONPanel] downloadAllTabs not yet implemented');
        // Phase 6: Implement ZIP creation
    }

    // ═══════════════════════════════════════════════════════════
    // PUBLIC API - Event System
    // ═══════════════════════════════════════════════════════════

    /**
     * Register event listener
     * @param {string} event - Event name
     * @param {Function} callback - Callback function
     */
    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }

    /**
     * Emit event
     * @param {string} event - Event name
     * @param {Object} data - Event data
     */
    emit(event, data) {
        const callbacks = this.listeners.get(event);
        if (callbacks) {
            callbacks.forEach(cb => cb(data));
        }
    }

    // ═══════════════════════════════════════════════════════════
    // UTILITIES
    // ═══════════════════════════════════════════════════════════

    /**
     * Escape HTML to prevent XSS
     */
    escapeHTML(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

// ═══════════════════════════════════════════════════════════════
// AUTO-INITIALIZE
// ═══════════════════════════════════════════════════════════════

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        new TRIONPanel();
    });
} else {
    new TRIONPanel();
}
