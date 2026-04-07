function buildTerminalHTML() {
    return `
    <div class="term-container">
        <!-- Header -->
        <div class="term-header">
            <h2><span class="term-icon">⬡</span> Container Commander</h2>
            <div class="term-header-actions">
                <button class="term-btn-sm" id="approval-center-btn">
                    📥 Approvals <span class="term-tab-count" id="approval-center-count">0</span>
                </button>
                <div class="term-conn-status">
                    <span class="term-conn-dot disconnected" id="term-conn-dot"></span>
                    <span class="term-conn-label" id="term-conn-label">Offline</span>
                </div>
            </div>
        </div>

        <!-- Tabs -->
        <div class="term-tabs">
            <button class="term-tab active" data-tab="dashboard">
                🪟 Dashboard
            </button>
            <button class="term-tab" data-tab="blueprints">
                📦 Blueprints <span class="term-tab-count" id="bp-count">0</span>
            </button>
            <button class="term-tab" data-tab="containers">
                🔄 Container <span class="term-tab-count" id="ct-count">0</span>
            </button>
            <button class="term-tab" data-tab="vault">
                🔐 Vault <span class="term-tab-count" id="vault-count">0</span>
            </button>
            <button class="term-tab" data-tab="logs">
                📋 Logs
            </button>
        </div>

        <!-- Approval Banner (hidden by default) -->
        <div class="term-approval-banner" id="approval-banner" style="display:none">
            <div class="term-approval-icon">⚠️</div>
            <div class="term-approval-text">
                <strong id="approval-reason">Container requests internet access</strong>
                <span id="approval-bp-id"></span>
                <span class="term-approval-ttl" id="approval-ttl"></span>
            </div>
            <div class="term-approval-actions">
                <button class="term-btn-sm danger" id="approval-reject">✖ Reject</button>
                <button class="term-btn-sm bp-deploy" id="approval-approve">✔ Approve</button>
            </div>
        </div>

        <aside class="approval-center" id="approval-center">
            <div class="approval-center-head">
                <h3>Approval Center</h3>
                <button class="approval-center-close" id="approval-center-close">✕</button>
            </div>
            <div class="approval-center-tabs">
                <button class="approval-center-tab active" data-approval-tab="pending">Pending</button>
                <button class="approval-center-tab" data-approval-tab="history">History</button>
            </div>
            <div id="approval-center-context"></div>
            <div class="approval-center-body">
                <div id="approval-center-pending"></div>
                <div id="approval-center-history" style="display:none"></div>
            </div>
        </aside>

        <!-- Panels -->
        <div class="term-panel active" id="panel-dashboard">
            <div class="dash-wrap">
                <section class="dash-kpis" id="dash-kpis"></section>
                <div class="dash-meta-grid">
                    <section class="dash-section dash-section-compact" id="dash-freshness"></section>
                    <section class="dash-section dash-section-compact" id="dash-action-queue"></section>
                    <section class="dash-section dash-section-compact" id="dash-runtime-health"></section>
                </div>
                <div class="dash-row-2">
                    <section class="dash-section" id="dash-problems"></section>
                    <section class="dash-section" id="dash-crashes"></section>
                </div>
                <div class="dash-row-2">
                    <section class="dash-section" id="dash-toptalkers"></section>
                    <div class="dash-col-2">
                        <section class="dash-section" id="dash-quota-forecast"></section>
                        <section class="dash-section" id="dash-risk"></section>
                    </div>
                </div>
                <section class="dash-section">
                    <div class="dash-section-head">
                        <h3>Today Timeline</h3>
                        <button class="term-btn-sm" id="dash-refresh-btn">↻ Refresh</button>
                    </div>
                    <div class="dash-timeline" id="dash-timeline"></div>
                </section>
                <section class="dash-section">
                    <div class="dash-section-head">
                        <h3>Continue Working</h3>
                    </div>
                    <div class="dash-continue-grid">
                        <div class="dash-continue-col">
                            <h4>Recent Blueprints</h4>
                            <div id="dash-recent-blueprints"></div>
                        </div>
                        <div class="dash-continue-col">
                            <h4>Recent Volumes</h4>
                            <div id="dash-recent-volumes"></div>
                        </div>
                    </div>
                </section>
            </div>
        </div>

        <div class="term-panel" id="panel-blueprints">
            <div class="bp-preset-bar" id="bp-preset-bar">
                <button class="bp-preset-btn" data-preset="python">🐍 Python</button>
                <button class="bp-preset-btn" data-preset="node">🟢 Node</button>
                <button class="bp-preset-btn" data-preset="db">🗄 DB</button>
                <button class="bp-preset-btn" data-preset="shell">🖥 Shell</button>
                <button class="bp-preset-btn" data-preset="webscraper">🕷 Web Scraper</button>
            </div>
            <div class="bp-list" id="bp-list"></div>
            <div class="bp-editor" id="bp-editor"></div>
            <div class="bp-preflight" id="bp-preflight"></div>
            <div class="term-footer">
                <div class="term-footer-left">
                    <button class="term-btn-sm" id="bp-add-btn">+ Blueprint</button>
                    <button class="term-btn-sm term-btn-simple" id="bp-simple-btn">✦ Simple</button>
                    <button class="term-btn-sm" id="bp-import-btn">📥 Import YAML</button>
                </div>
                <div class="term-dropzone" id="bp-dropzone" style="display:none;">
                    <div class="drop-icon">📄</div>
                    <p>Drop Dockerfile or docker-compose.yml</p>
                    <small>Or click to browse</small>
                </div>
            </div>
        </div>

        <div class="term-panel" id="panel-containers">
            <div class="ct-list" id="ct-list"></div>
            <div class="ct-drawer" id="ct-drawer"></div>
            <div class="vm-manager" id="vm-manager"></div>
            <div class="term-footer">
                <div class="term-footer-left">
                    <button class="term-btn-sm" id="vm-toggle-btn">💾 Volumes</button>
                    <div class="term-quota" id="ct-quota">
                        <span>Quota:</span>
                        <div class="term-quota-bar"><div class="term-quota-fill" id="quota-fill" style="width:0%"></div></div>
                        <span id="ct-quota-text">0/2 Container</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="term-panel" id="panel-vault">
            <div class="vault-add-form" id="vault-form">
                <div class="vault-form-row">
                    <input type="text" id="vault-name" placeholder="SECRET_NAME" />
                    <select id="vault-scope">
                        <option value="global">Global</option>
                        <option value="blueprint">Blueprint</option>
                    </select>
                </div>
                <div class="vault-form-row">
                    <input type="password" id="vault-value" placeholder="Secret value..." />
                    <input type="text" id="vault-bp-id" placeholder="Blueprint ID (optional)" style="max-width:160px" />
                </div>
                <div class="bp-editor-footer">
                    <button class="proto-btn-cancel" id="vault-cancel">Cancel</button>
                    <button class="proto-btn-save" id="vault-save">🔐 Store</button>
                </div>
            </div>
            <div class="vault-list" id="vault-list"></div>
            <div class="term-footer">
                <div class="term-footer-left">
                    <button class="term-btn-sm" id="vault-add-btn">+ Secret</button>
                </div>
            </div>
        </div>

        <div class="term-panel" id="panel-logs">
            <div class="term-logs-layout">
                <div class="term-logs-main">
                    <div class="term-log-bar">
                        <button class="term-log-tab active" data-log-mode="logs">&#128203; Logs</button>
                        <button class="term-log-tab" data-log-mode="shell">&#9000; Shell</button>
                        <div class="term-log-bar-div"></div>
                        <div class="term-log-status">
                            <span class="term-log-sdot"></span>
                            <span class="term-log-stxt" id="log-status-txt">Bereit</span>
                        </div>
                        <div class="term-log-bar-right">
                            <span class="term-log-badge term-lb-err" id="log-badge-err" style="display:none">0 Err</span>
                            <span class="term-log-badge term-lb-warn" id="log-badge-warn" style="display:none">0 Warn</span>
                            <span class="term-log-badge term-lb-ok" id="log-badge-ok" style="display:none">0 OK</span>
                            <div class="term-log-bar-div"></div>
                            <div class="term-log-menu-wrap">
                                <button class="term-log-menu-btn" id="term-log-menu-btn" title="Optionen">&#8942;</button>
                                <div class="term-log-dropdown" id="term-log-dropdown">
                                    <div class="term-dd-label">Filter</div>
                                    <div class="term-dd-filter">
                                        <select class="term-dd-select" id="log-filter-container">
                                            <option value="">Alle Container</option>
                                        </select>
                                        <select class="term-dd-select" id="log-filter-level">
                                            <option value="">Level: Alle</option>
                                            <option value="error">ERROR</option>
                                            <option value="warn">WARN</option>
                                            <option value="info">INFO</option>
                                        </select>
                                    </div>
                                    <div class="term-dd-divider"></div>
                                    <div class="term-dd-label">Aktionen</div>
                                    <button class="term-dd-item" id="log-copy-btn">&#128203; Copy Clean</button>
                                    <button class="term-dd-item" id="log-download-btn">&#8675; Download Logs</button>
                                    <div class="term-dd-divider"></div>
                                    <div class="term-dd-label">Tools</div>
                                    <button class="term-dd-item" id="term-cmd-palette-btn">&#8984; Command Palette</button>
                                    <button class="term-dd-item" id="log-autoscroll-btn">&#8595; Auto-scroll <span id="log-autoscroll-state" style="margin-left:auto;color:#3fb950">AN</span></button>
                                    <button class="term-dd-item term-dd-item-danger" id="log-clear-btn">&#128465; Logs leeren</button>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="term-shell-addon-strip" id="term-shell-addon-strip" style="display:none">
                        <div class="term-shell-addon-label" id="term-shell-addon-label">TRION Sources</div>
                        <div class="term-shell-addon-list" id="term-shell-addon-list"></div>
                    </div>
                    <div class="term-log-mode-panel active" id="log-mode-logs">
                        <div class="term-output-plain" id="log-stream-output">Waiting for log stream...</div>
                    </div>
                    <div class="term-log-mode-panel" id="log-mode-shell">
                        <div class="term-shell-sessions" id="term-shell-sessions"></div>
                        <div class="term-xterm-container" id="xterm-container"></div>
                        <div class="term-output-plain" id="log-output" style="display:none">Waiting for shell data...</div>
                    </div>
                    <div class="term-input-bar">
                        <span class="term-prompt">trion&gt;</span>
                        <span class="term-shell-mode-badge" id="term-shell-mode-badge" style="display:none">TRION controls shell</span>
                        <input class="term-input" id="term-cmd-input" type="text"
                               placeholder="Type command or /quick action… (Tab for autocomplete)" autocomplete="off" />
                        <button class="term-send-btn" id="term-send-btn">↵</button>
                        <div class="term-autocomplete" id="term-autocomplete" style="display:none"></div>
                    </div>
                    <div class="term-history-strip">
                        <input id="term-history-filter" placeholder="Search command history..." />
                        <div class="term-history-list" id="term-history-list"></div>
                    </div>
                </div>
                <aside class="term-activity-feed" id="term-activity-feed">
                    <div class="term-activity-head">
                        <h4>TRION Activity</h4>
                        <button class="term-btn-sm" id="term-activity-refresh">↻</button>
                    </div>
                    <div class="term-activity-list" id="term-activity-list"></div>
                    <div class="term-memory-divider"></div>
                    <div class="term-memory-head">
                        <h4>TRION Memory</h4>
                        <button class="term-btn-sm" id="term-memory-refresh">↻</button>
                    </div>
                    <div class="term-memory-status" id="term-memory-status">Status: unknown</div>
                    <div class="term-memory-tools">
                        <textarea id="term-memory-note" placeholder="Important note..."></textarea>
                        <div class="term-memory-tools-row">
                            <select id="term-memory-category">
                                <option value="project_fact">project_fact</option>
                                <option value="user_preference">user_preference</option>
                                <option value="todo">todo</option>
                                <option value="note">note</option>
                            </select>
                            <button class="term-btn-sm" id="term-memory-remember">Remember</button>
                        </div>
                        <div class="term-memory-tools-row">
                            <input id="term-memory-query" placeholder="Search memory..." />
                            <button class="term-btn-sm" id="term-memory-search">Search</button>
                        </div>
                    </div>
                    <div class="term-memory-list" id="term-memory-list"></div>
                </aside>
            </div>
        </div>
        <div class="term-command-palette" id="term-command-palette">
            <div class="term-command-backdrop" id="term-cmd-backdrop"></div>
            <div class="term-command-dialog">
                <div class="term-command-head">
                    <h3>Command Palette</h3>
                    <button class="term-btn-sm" id="term-cmd-close">✕</button>
                </div>
                <input id="term-cmd-filter" placeholder="Type to filter commands..." />
                <div class="term-command-groups" id="term-command-groups"></div>
            </div>
        </div>
        <div class="term-activity-detail" id="term-activity-detail"></div>
        <div class="term-toast-stack" id="term-toast-stack"></div>
    </div>`;
}

export { buildTerminalHTML };
