function createContainersController(deps) {
    let containerDetailState = {
        open: false,
        containerId: '',
        tab: 'logs',
        pollTimer: null,
        hostCompanionResult: null,
    };
    let volumeManagerState = {
        open: false,
        filter: '',
        volumes: [],
        snapshots: [],
        compareA: '',
        compareB: '',
    };

    async function loadContainers() {
        try {
            const data = await deps.apiRequest('/containers', {}, 'Could not load containers');
            deps.setContainers(data.containers || []);
            const count = document.getElementById('ct-count');
            if (count) count.textContent = String(deps.getContainers().length);
            renderContainers();
            if (containerDetailState.open) {
                const stillExists = deps.getContainers().some(container => container.container_id === containerDetailState.containerId);
                if (!stillExists) closeContainerDrawer();
            }
        } catch (_) {
            const list = document.getElementById('ct-list');
            if (list) list.innerHTML = deps.renderEmpty('🔄', 'No containers running', 'Deploy a blueprint');
        }
    }

    function renderContainers() {
        const list = document.getElementById('ct-list');
        if (!list) return;
        const containers = deps.getContainers();
        if (!containers.length) {
            list.innerHTML = deps.renderEmpty('🔄', 'No containers running', 'Deploy a blueprint');
            return;
        }
        const iconForStatus = (status) => {
            if (status === 'running') return '🟢';
            if (status === 'error') return '🔴';
            if (status === 'stopped') return '🟠';
            return '⚪';
        };
        list.innerHTML = containers.map(container => `
            <div class="ct-row glass ct-${deps.esc(container.status || 'unknown')}" onclick="termOpenCtDetails('${container.container_id}')">
                <div class="ct-row-status"><span class="bp-status-dot ${container.status}"></span></div>
                <div class="ct-row-info">
                    <div class="ct-row-name">${iconForStatus(container.status)} ${deps.esc(container.name)}</div>
                    <div class="ct-row-detail">${container.container_id?.slice(0, 12)} · ${container.blueprint_id}</div>
                </div>
                <div class="ct-row-stats">
                    <div class="ct-stat"><div class="ct-stat-val">${container.cpu_percent?.toFixed(1)}%</div><div class="ct-stat-label">CPU</div></div>
                    <div class="ct-stat"><div class="ct-stat-val">${container.memory_mb?.toFixed(0)}M</div><div class="ct-stat-label">RAM</div></div>
                </div>
                <div class="ct-row-actions">
                    <button class="term-btn-sm" onclick="event.stopPropagation();termOpenCtDetails('${container.container_id}')">🔎</button>
                    <button class="term-btn-sm" onclick="event.stopPropagation();termAttachCt('${container.container_id}')">🔗</button>
                    <button class="term-btn-sm" onclick="event.stopPropagation();${container.status === 'stopped' ? `termStartCt('${container.container_id}')` : `termStopCt('${container.container_id}')`}">${container.status === 'stopped' ? '▶' : '⏹'}</button>
                </div>
            </div>
        `).join('');
    }

    async function loadQuota() {
        try {
            const quota = await deps.apiRequest('/quota', {}, 'Could not load quota');
            const pct = (quota.containers_used / quota.max_containers) * 100;
            const fill = document.getElementById('quota-fill');
            if (fill) fill.style.width = `${pct}%`;
            const text = document.getElementById('ct-quota-text');
            if (text) text.textContent = `${quota.containers_used}/${quota.max_containers} Container · ${quota.memory_used_mb}/${quota.max_total_memory_mb} MB`;
        } catch (_) {
            // Silent quota refresh.
        }
    }

    async function stopContainer(id) {
        try {
            await deps.apiRequest(`/containers/${id}/stop`, { method: 'POST' }, 'Could not stop container');
            deps.logOutput(`⏹ Stopped ${id.slice(0, 12)}`, 'ansi-yellow');
            await loadContainers();
            if (deps.getActiveTab() === 'dashboard') await deps.loadDashboard();
        } catch (error) {
            deps.logOutput(`❌ ${error.message}`, 'ansi-red');
        }
    }

    async function startContainer(id) {
        try {
            await deps.apiRequest(`/containers/${id}/start`, { method: 'POST' }, 'Could not start container');
            deps.logOutput(`▶ Started ${id.slice(0, 12)}`, 'ansi-green');
            await loadContainers();
            if (deps.getActiveTab() === 'dashboard') await deps.loadDashboard();
        } catch (error) {
            deps.logOutput(`❌ ${error.message}`, 'ansi-red');
        }
    }

    function formatHostCompanionResult(payload, fallbackLabel) {
        const result = payload?.result || payload || {};
        const lines = [];
        if (fallbackLabel) lines.push(String(fallbackLabel));
        const removed = typeof result.removed === 'boolean'
            ? result.removed
            : (typeof payload?.removed === 'boolean' ? payload.removed : null);
        if (typeof removed === 'boolean') lines.push(`container removed: ${removed}`);
        if (typeof result.ok === 'boolean') lines.push(`ok: ${result.ok}`);
        if (typeof result.repaired === 'boolean') lines.push(`repaired: ${result.repaired}`);
        if (typeof result.uninstalled === 'boolean') lines.push(`uninstalled: ${result.uninstalled}`);
        const hostCompanionUninstalled = typeof result.host_companion_uninstalled === 'boolean'
            ? result.host_companion_uninstalled
            : (typeof payload?.host_companion?.uninstalled === 'boolean' ? payload.host_companion.uninstalled : null);
        if (typeof hostCompanionUninstalled === 'boolean') lines.push(`host companion removed: ${hostCompanionUninstalled}`);
        const checks = Array.isArray(result?.postchecks?.checks) ? result.postchecks.checks : Array.isArray(result?.checks) ? result.checks : [];
        if (checks.length) {
            const summary = checks.map(item => `${item.name}:${item.ok ? 'ok' : 'fail'}`).join(' | ');
            lines.push(`checks: ${summary}`);
        }
        const removedPaths = Array.isArray(result?.removed_paths) ? result.removed_paths : [];
        if (removedPaths.length) lines.push(`removed: ${removedPaths.length} file(s)`);
        if (Array.isArray(result?.notes) && result.notes.length) lines.push(...result.notes.slice(0, 2));
        if (!lines.length) lines.push('No result details returned.');
        return lines.join('\n');
    }

    function renderHostCompanionResult() {
        const el = document.getElementById('ct-host-companion-result');
        if (!el) return;
        const state = containerDetailState.hostCompanionResult;
        if (!state) {
            el.textContent = 'No host-companion or uninstall action run yet.';
            return;
        }
        el.textContent = state.text || 'No host-companion or uninstall action run yet.';
        el.dataset.state = state.state || 'info';
    }

    async function checkHostCompanion(id) {
        try {
            const data = await deps.apiRequest(`/containers/${id}/host-companion/check`, {}, 'Could not check host companion');
            containerDetailState.hostCompanionResult = {
                state: data?.result?.ok ? 'success' : 'warn',
                text: formatHostCompanionResult(data, 'Host companion check completed.'),
            };
            renderHostCompanionResult();
            deps.showToast(data?.result?.ok ? 'Host companion check passed' : 'Host companion check found issues', data?.result?.ok ? 'success' : 'warn');
            return data;
        } catch (error) {
            containerDetailState.hostCompanionResult = {
                state: 'error',
                text: error.message || 'Could not check host companion',
            };
            renderHostCompanionResult();
            deps.showToast(error.message || 'Could not check host companion', 'error');
            throw error;
        }
    }

    async function repairHostCompanion(id) {
        try {
            const data = await deps.apiRequest(`/containers/${id}/host-companion/repair`, { method: 'POST' }, 'Could not repair host companion');
            containerDetailState.hostCompanionResult = {
                state: data?.repaired ? 'success' : 'warn',
                text: formatHostCompanionResult(data, 'Host companion repair completed.'),
            };
            renderHostCompanionResult();
            deps.showToast(data?.repaired ? 'Host companion repaired' : 'Host companion repair needs attention', data?.repaired ? 'success' : 'warn');
            await refreshContainerDetail();
            return data;
        } catch (error) {
            containerDetailState.hostCompanionResult = {
                state: 'error',
                text: error.message || 'Could not repair host companion',
            };
            renderHostCompanionResult();
            deps.showToast(error.message || 'Could not repair host companion', 'error');
            throw error;
        }
    }

    async function uninstallContainer(id) {
        const current = deps.getContainers().find(container => container.container_id === id);
        if (current?.status !== 'stopped') {
            const msg = 'Stop the container before uninstalling it.';
            containerDetailState.hostCompanionResult = { state: 'warn', text: msg };
            renderHostCompanionResult();
            deps.showToast(msg, 'warn');
            return null;
        }
        if (!confirm('Uninstall this stopped container? For packages with a host companion, the host service will also be removed. Storage under /data will be preserved.')) {
            return null;
        }
        try {
            const data = await deps.apiRequest(`/containers/${id}/uninstall`, { method: 'POST' }, 'Could not uninstall container');
            containerDetailState.hostCompanionResult = {
                state: data?.removed ? 'success' : 'warn',
                text: formatHostCompanionResult(data, 'Container uninstall completed.'),
            };
            renderHostCompanionResult();
            deps.showToast(data?.removed ? 'Container uninstalled' : 'Container uninstall incomplete', data?.removed ? 'success' : 'warn');
            await loadContainers();
            return data;
        } catch (error) {
            containerDetailState.hostCompanionResult = {
                state: 'error',
                text: error.message || 'Could not uninstall container',
            };
            renderHostCompanionResult();
            deps.showToast(error.message || 'Could not uninstall container', 'error');
            throw error;
        }
    }

    function attachContainer(id) {
        deps.autoFocusContainer(id);
        deps.rememberRecent('containers', id);
        deps.logOutput(`🔗 Attached to ${id.slice(0, 12)}`, 'ansi-cyan');
    }

    function stopContainerDetailPolling() {
        if (!containerDetailState.pollTimer) return;
        clearInterval(containerDetailState.pollTimer);
        containerDetailState.pollTimer = null;
    }

    function setContainerDetailTab(tab) {
        containerDetailState.tab = ['logs', 'stats', 'events'].includes(tab) ? tab : 'logs';
        document.querySelectorAll('.ct-drawer-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.ctTab === containerDetailState.tab);
        });
        document.querySelectorAll('.ct-drawer-pane').forEach(pane => {
            pane.classList.toggle('active', pane.dataset.ctPane === containerDetailState.tab);
        });
    }

    function renderContainerDrawerShell(containerId) {
        const drawer = document.getElementById('ct-drawer');
        if (!drawer) return;
        containerDetailState.hostCompanionResult = null;
        drawer.innerHTML = `
            <div class="ct-drawer-head">
                <div>
                    <h3>Container Detail</h3>
                    <div class="ct-drawer-sub">${deps.esc(containerId.slice(0, 12))}</div>
                </div>
                <div class="ct-drawer-head-actions">
                    <button class="ct-drawer-back" id="ct-drawer-back">← Back</button>
                    <button class="ct-drawer-close" id="ct-drawer-close">✕</button>
                </div>
            </div>
            <div class="ct-drawer-toolbar">
                <span id="ct-drawer-refresh-status">Auto refresh every 7s</span>
                <span id="ct-drawer-last-update">Last update: -</span>
            </div>
            <div class="ct-control-grid">
                <section class="ct-control-col">
                    <h4>Logs</h4>
                    <pre id="ct-drawer-logs">Loading logs...</pre>
                    <div id="ct-drawer-log-hint" class="ct-drawer-hint"></div>
                </section>
                <section class="ct-control-col">
                    <h4>Stats</h4>
                    <div id="ct-drawer-stats">Loading stats...</div>
                    <div id="ct-drawer-stat-hint" class="ct-drawer-hint"></div>
                </section>
                <section class="ct-control-col">
                    <h4>Events</h4>
                    <div id="ct-drawer-events">Loading events...</div>
                </section>
            </div>
            <div class="ct-drawer-actions">
                <button class="term-btn-sm" id="ct-drawer-refresh">↻ Refresh</button>
                <button class="term-btn-sm" id="ct-drawer-attach">🔗 Attach</button>
                <button class="term-btn-sm" id="ct-drawer-restart">⟳ Restart</button>
                <button class="term-btn-sm" id="ct-drawer-snapshot">📸 Snapshot</button>
                <button class="term-btn-sm danger" id="ct-drawer-stop">⏹ Stop</button>
            </div>
            <div class="ct-drawer-actions" id="ct-host-companion-actions">
                <button class="term-btn-sm" id="ct-host-check">🩺 Check Host</button>
                <button class="term-btn-sm" id="ct-host-repair">🛠 Repair Host</button>
                <button class="term-btn-sm danger" id="ct-host-uninstall">🧹 Uninstall</button>
            </div>
            <div class="ct-drawer-hint">
                <strong>Host Companion & Uninstall</strong>
                <pre id="ct-host-companion-result">No host-companion or uninstall action run yet.</pre>
            </div>
        `;
        drawer.classList.add('visible');
        document.getElementById('ct-drawer-back')?.addEventListener('click', closeContainerDrawer);
        document.getElementById('ct-drawer-close')?.addEventListener('click', closeContainerDrawer);
        document.getElementById('ct-drawer-refresh')?.addEventListener('click', refreshContainerDetail);
        document.getElementById('ct-drawer-attach')?.addEventListener('click', () => {
            if (!containerDetailState.containerId) return;
            attachContainer(containerDetailState.containerId);
        });
        document.getElementById('ct-drawer-stop')?.addEventListener('click', async () => {
            if (!containerDetailState.containerId) return;
            const current = deps.getContainers().find(container => container.container_id === containerDetailState.containerId);
            if (current?.status === 'stopped') {
                await startContainer(containerDetailState.containerId);
            } else {
                await stopContainer(containerDetailState.containerId);
            }
            await loadContainers();
            await refreshContainerDetail();
        });
        document.getElementById('ct-drawer-restart')?.addEventListener('click', async () => {
            const current = deps.getContainers().find(container => container.container_id === containerDetailState.containerId);
            if (!current) return;
            if (current.status === 'stopped') {
                await startContainer(current.container_id);
                await loadContainers();
                await refreshContainerDetail();
                return;
            }
            if (!confirm(`Restart container from blueprint "${current.blueprint_id}"?`)) return;
            await stopContainer(current.container_id);
            await deps.deployBlueprint(current.blueprint_id);
        });
        document.getElementById('ct-drawer-snapshot')?.addEventListener('click', async () => {
            const current = deps.getContainers().find(container => container.container_id === containerDetailState.containerId);
            const volumeName = current?.volume_name || '';
            if (!volumeName) {
                deps.showToast('No workspace volume attached', 'warn');
                return;
            }
            await snapshotVolume(volumeName);
        });
        document.getElementById('ct-host-check')?.addEventListener('click', async () => {
            if (!containerDetailState.containerId) return;
            await checkHostCompanion(containerDetailState.containerId);
        });
        document.getElementById('ct-host-repair')?.addEventListener('click', async () => {
            if (!containerDetailState.containerId) return;
            await repairHostCompanion(containerDetailState.containerId);
        });
        document.getElementById('ct-host-uninstall')?.addEventListener('click', async () => {
            if (!containerDetailState.containerId) return;
            await uninstallContainer(containerDetailState.containerId);
        });
        renderHostCompanionResult();
    }

    function closeContainerDrawer() {
        containerDetailState.open = false;
        containerDetailState.containerId = '';
        stopContainerDetailPolling();
        const drawer = document.getElementById('ct-drawer');
        if (!drawer) return;
        drawer.classList.remove('visible');
        drawer.innerHTML = '';
    }

    function renderContainerDetailStats(stats) {
        if (!stats || stats.error) {
            return `<div class="ct-drawer-empty">${deps.esc(stats?.error || 'No stats available')}</div>`;
        }
        const browserHost = String(window.location.hostname || '127.0.0.1').trim() || '127.0.0.1';
        const genericHostIp = (value) => ['', '0.0.0.0', '::'].includes(String(value || '').trim());
        const resolveAccessUrl = (link) => {
            const scheme = String(link?.scheme || '').trim();
            const hostPort = String(link?.host_port || '').trim();
            if (!scheme || !hostPort) return '';
            const hostIp = String(link?.host_ip || '').trim();
            const host = genericHostIp(hostIp) ? browserHost : hostIp;
            const path = String(link?.path || '/').trim() || '/';
            return `${scheme}://${host}:${hostPort}${path}`;
        };
        const rawPorts = Array.isArray(stats.ports) ? stats.ports : [];
        const rawAccessLinks = Array.isArray(stats?.connection?.access_links) ? stats.connection.access_links : [];
        const accessLinkMap = new Map();
        rawAccessLinks.forEach((link) => {
            const key = `${String(link?.host_port || '').trim()}|${String(link?.container_port || '').trim()}`;
            if (!key || key === '|') return;
            if (!accessLinkMap.has(key)) accessLinkMap.set(key, link);
        });
        const dedupedPorts = [];
        const seenPorts = new Map();
        const isGenericIp = (value) => genericHostIp(value);
        rawPorts.forEach((port) => {
            const hostPort = String(port?.host_port || '').trim();
            const containerPort = String(port?.container_port || '').trim();
            const key = `${hostPort}|${containerPort}`;
            const previousIndex = seenPorts.get(key);
            if (previousIndex === undefined) {
                seenPorts.set(key, dedupedPorts.length);
                dedupedPorts.push(port);
                return;
            }
            const previous = dedupedPorts[previousIndex];
            if (isGenericIp(previous?.host_ip) && !isGenericIp(port?.host_ip)) {
                dedupedPorts[previousIndex] = port;
            }
        });
        const ports = dedupedPorts;
        const visiblePorts = ports.slice(0, 5);
        const hiddenPortCount = Math.max(ports.length - visiblePorts.length, 0);
        const renderPortRow = (port) => {
            const hostIp = String(port?.host_ip || '0.0.0.0');
            const hostPort = String(port?.host_port || '');
            const containerPort = String(port?.container_port || '');
            const serviceName = String(port?.service_name || '').trim();
            const [containerNumber, protoRaw] = containerPort.split('/');
            const proto = String(protoRaw || 'tcp').toUpperCase();
            const hostLabel = hostIp && hostIp !== '0.0.0.0'
                ? `${hostIp}:${hostPort}`
                : hostPort;
            const portMapping = hostLabel && containerNumber && hostLabel !== containerNumber
                ? `${hostLabel} -> ${containerNumber}`
                : (hostLabel || containerNumber || 'unmapped');
            const link = accessLinkMap.get(`${hostPort}|${containerPort}`);
            const accessUrl = resolveAccessUrl(link);
            return `
                <div class="ct-port-row">
                    <div class="ct-port-main">
                        <strong>${deps.esc(serviceName || hostLabel || 'internal')}</strong>
                        <span>${deps.esc(serviceName ? portMapping : (containerNumber || containerPort || 'unmapped'))}</span>
                    </div>
                    <div class="ct-port-side">
                        ${accessUrl ? `<a class="term-btn-sm ct-port-open" href="${deps.esc(accessUrl)}" target="_blank" rel="noreferrer noopener">${deps.esc(String(link?.label || 'Open'))}</a>` : ''}
                        <span class="ct-port-proto">${deps.esc(proto)}</span>
                    </div>
                </div>
            `;
        };
        const portsBlock = ports.length ? `
            <div class="ct-port-panel">
                <div class="ct-port-head">
                    <span>Ports</span>
                    <span>${deps.esc(String(ports.length))} mapped</span>
                </div>
                <div class="ct-port-list">
                    ${visiblePorts.map(renderPortRow).join('')}
                </div>
                ${hiddenPortCount ? `<div class="ct-port-more">+${deps.esc(String(hiddenPortCount))} more</div>` : ''}
            </div>
        ` : `
            <div class="ct-port-panel">
                <div class="ct-port-head">
                    <span>Ports</span>
                    <span>none exposed</span>
                </div>
            </div>
        `;
        const deployWarnings = Array.isArray(stats.deploy_warnings) ? stats.deploy_warnings : [];
        const noVncPort = rawPorts.find(p => String(p?.container_port || '').startsWith('8083'));
        const noVncUrl = noVncPort ? resolveAccessUrl({ scheme: 'http', host_ip: noVncPort.host_ip, host_port: noVncPort.host_port, path: '/' }) : null;
        const warningsBlock = deployWarnings.length ? `
            <div class="ct-warning-panel">
                ${deployWarnings.map(w => {
                    const msg = deps.esc(String(w?.detail?.message || w?.name || 'Advisory warning'));
                    const noVncHint = noVncUrl
                        ? ` <a class="ct-warning-link" href="${deps.esc(noVncUrl)}" target="_blank" rel="noopener">View via noVNC</a>`
                        : '';
                    return `<div class="ct-warning-row">&#9888; ${msg}${noVncHint}</div>`;
                }).join('')}
            </div>
        ` : '';

        return `
            <div class="ct-drawer-stats-stack">
                ${warningsBlock}
                <div class="ct-drawer-kpis">
                    <div class="ct-kpi"><span>CPU</span><strong>${deps.esc(String(stats.cpu_percent ?? '0'))}%</strong></div>
                    <div class="ct-kpi"><span>RAM</span><strong>${deps.esc(String(stats.memory_mb ?? '0'))} / ${deps.esc(String(stats.memory_limit_mb ?? '0'))} MB</strong></div>
                    <div class="ct-kpi"><span>RX/TX</span><strong>${deps.esc(String(stats.network_rx_bytes ?? 0))} / ${deps.esc(String(stats.network_tx_bytes ?? 0))}</strong></div>
                    <div class="ct-kpi"><span>Efficiency</span><strong>${deps.esc(String(stats.efficiency?.level || 'n/a'))}</strong></div>
                </div>
                ${portsBlock}
            </div>
        `;
    }

    function renderContainerDetailEvents(entries, containerId) {
        const rows = (entries || []).filter(entry => {
            const cid = String(entry?.container_id || '');
            return cid === containerId || cid.startsWith(containerId.slice(0, 12));
        });
        if (!rows.length) return '<div class="ct-drawer-empty">No matching events.</div>';
        return rows.slice(0, 40).map(entry => `
            <div class="ct-drawer-event">
                <div class="ct-drawer-event-top">
                    <span>${deps.esc(entry.created_at || '')}</span>
                    <span>${deps.esc(entry.action || '')}</span>
                </div>
                <div class="ct-drawer-event-msg">${deps.esc(entry.details || '')}</div>
            </div>
        `).join('');
    }

    function suggestFix(message) {
        const value = String(message || '').toLowerCase();
        if (value.includes('not found')) return 'Suggestion: verify container ID and refresh the list.';
        if (value.includes('secret')) return 'Suggestion: open Vault tab and add missing secret.';
        if (value.includes('quota')) return 'Suggestion: stop old containers or lower resource limits.';
        if (value.includes('approval')) return 'Suggestion: open Approval Center and resolve pending requests.';
        if (value.includes('healthcheck_timeout_auto_stopped') || value.includes('healthcheck timeout')) {
            return 'Suggestion: container did not become healthy in time. Check logs/healthcheck and increase readiness timeout if needed.';
        }
        if (value.includes('healthcheck_unhealthy_auto_stopped') || value.includes('reported unhealthy')) {
            return 'Suggestion: healthcheck failed. Verify ports/command/env and inspect container logs.';
        }
        if (value.includes('container_exited_before_ready_auto_stopped') || value.includes('exited before ready')) {
            return 'Suggestion: startup failed before readiness. Inspect logs and required secrets/env vars.';
        }
        return '';
    }

    async function refreshContainerDetail() {
        if (!containerDetailState.open || !containerDetailState.containerId) return;
        const containerId = containerDetailState.containerId;
        try {
            const [logsData, statsData, auditData] = await Promise.all([
                deps.apiRequest(`/containers/${containerId}/logs?tail=180`, {}, 'Could not load logs'),
                deps.apiRequest(`/containers/${containerId}/stats`, {}, 'Could not load stats'),
                deps.apiRequest('/audit?limit=120', {}, 'Could not load audit log'),
            ]);
            const logsEl = document.getElementById('ct-drawer-logs');
            if (logsEl) logsEl.textContent = String(logsData?.logs || 'No logs');
            const logHint = document.getElementById('ct-drawer-log-hint');
            if (logHint) logHint.textContent = suggestFix(logsData?.logs || '');
            const statsEl = document.getElementById('ct-drawer-stats');
            if (statsEl) statsEl.innerHTML = renderContainerDetailStats(statsData);
            const statHint = document.getElementById('ct-drawer-stat-hint');
            if (statHint) statHint.textContent = suggestFix(statsData?.error || '');
            const eventsEl = document.getElementById('ct-drawer-events');
            if (eventsEl) eventsEl.innerHTML = renderContainerDetailEvents(auditData?.entries || [], containerId);
            const current = deps.getContainers().find(container => container.container_id === containerId);
            const stopBtn = document.getElementById('ct-drawer-stop');
            if (stopBtn) stopBtn.textContent = current?.status === 'stopped' ? '▶ Start' : '⏹ Stop';
            const restartBtn = document.getElementById('ct-drawer-restart');
            if (restartBtn) restartBtn.textContent = current?.status === 'stopped' ? '↻ Start' : '⟳ Restart';
            const stamp = document.getElementById('ct-drawer-last-update');
            if (stamp) stamp.textContent = `Last update: ${new Date().toLocaleTimeString()}`;
            const uninstallBtn = document.getElementById('ct-host-uninstall');
            if (uninstallBtn) uninstallBtn.disabled = current?.status !== 'stopped';
            renderHostCompanionResult();
        } catch (error) {
            const logsEl = document.getElementById('ct-drawer-logs');
            if (logsEl) logsEl.textContent = error.message || 'Could not load details';
            const logHint = document.getElementById('ct-drawer-log-hint');
            if (logHint) logHint.textContent = suggestFix(error.message || '');
            renderHostCompanionResult();
        }
    }

    function openContainerDrawer(containerId) {
        if (!containerId) return;
        containerDetailState.open = true;
        containerDetailState.containerId = containerId;
        renderContainerDrawerShell(containerId);
        setContainerDetailTab(containerDetailState.tab || 'logs');
        refreshContainerDetail();
        stopContainerDetailPolling();
        containerDetailState.pollTimer = setInterval(refreshContainerDetail, 7000);
    }

    function getVolumeUsageMap() {
        const usage = new Map();
        deps.getContainers().forEach(container => {
            const name = String(container?.volume_name || '');
            if (!name) return;
            if (!usage.has(name)) usage.set(name, []);
            usage.get(name).push(container.container_id?.slice(0, 12) || container.name || 'container');
        });
        return usage;
    }

    function renderVolumeRows() {
        const usage = getVolumeUsageMap();
        const filtered = volumeManagerState.volumes.filter(volume => {
            if (!volumeManagerState.filter) return true;
            const query = volumeManagerState.filter.toLowerCase();
            return String(volume.name || '').toLowerCase().includes(query)
                || String(volume.blueprint_id || '').toLowerCase().includes(query);
        });
        if (!filtered.length) return '<div class="vm-empty">No volumes match this filter.</div>';
        return filtered.map(volume => {
            const usedBy = usage.get(volume.name) || [];
            return `
                <div class="vm-row vm-card">
                    <div class="vm-main">
                        <div class="vm-title">${deps.esc(volume.name)} ${usedBy.length ? '<span class="vm-badge inuse">In Use</span>' : '<span class="vm-badge idle">Idle</span>'}</div>
                        <div class="vm-meta">${deps.esc(volume.blueprint_id || 'n/a')} · ${deps.esc(volume.created_at || '')}</div>
                        <div class="vm-usage">${usedBy.length ? `Used by: ${deps.esc(usedBy.join(', '))}` : 'Not attached to container'}</div>
                    </div>
                    <div class="vm-actions">
                        <button class="term-btn-sm" onclick="termSnapshotVolume('${deps.esc(volume.name)}')">📸 Snapshot</button>
                        <button class="term-btn-sm danger" onclick="termRemoveVolume('${deps.esc(volume.name)}')">🗑️ Delete</button>
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderSnapshotRows() {
        const rows = volumeManagerState.snapshots || [];
        if (!rows.length) return '<div class="vm-empty">No snapshots available.</div>';
        return rows.slice(0, 120).map(snapshot => `
            <div class="vm-row vm-row-snapshot vm-card">
                <div class="vm-main">
                    <div class="vm-title">${deps.esc(snapshot.filename || '')}</div>
                    <div class="vm-meta">${deps.esc(snapshot.volume_name || 'volume?')} · ${deps.esc(String(snapshot.size_mb || 0))} MB · ${deps.esc(snapshot.created_at || '')}</div>
                </div>
                <div class="vm-actions">
                    <button class="term-btn-sm" onclick="termRestoreSnapshot('${deps.esc(snapshot.filename || '')}')">♻ Restore</button>
                    <button class="term-btn-sm danger" onclick="termDeleteSnapshot('${deps.esc(snapshot.filename || '')}')">🗑️ Delete</button>
                </div>
            </div>
        `).join('');
    }

    function renderSnapshotCompare() {
        const rows = volumeManagerState.snapshots || [];
        const byName = new Map(rows.map(snapshot => [snapshot.filename, snapshot]));
        const a = byName.get(volumeManagerState.compareA);
        const b = byName.get(volumeManagerState.compareB);
        if (!a || !b) return '<div class="vm-empty">Choose two snapshots to compare.</div>';
        const delta = Number((a.size_mb || 0) - (b.size_mb || 0)).toFixed(1);
        return `
            <div class="vm-compare-card">
                <div><strong>A:</strong> ${deps.esc(a.filename)} · ${deps.esc(String(a.size_mb || 0))} MB</div>
                <div><strong>B:</strong> ${deps.esc(b.filename)} · ${deps.esc(String(b.size_mb || 0))} MB</div>
                <div><strong>Δ Size:</strong> ${delta} MB</div>
                <div><strong>Source:</strong> ${deps.esc(a.volume_name || '-')} vs ${deps.esc(b.volume_name || '-')}</div>
            </div>
        `;
    }

    function renderVolumeManager() {
        const root = document.getElementById('vm-manager');
        if (!root) return;
        if (!volumeManagerState.open) {
            root.classList.remove('visible');
            root.innerHTML = '';
            return;
        }
        root.classList.add('visible');
        root.innerHTML = `
            <div class="vm-head">
                <h3>Volumes & Snapshots</h3>
                <button class="term-btn-sm" id="vm-refresh-btn">↻ Refresh</button>
            </div>
            <div class="vm-toolbar">
                <input id="vm-filter" placeholder="Filter volume or blueprint..." value="${deps.esc(volumeManagerState.filter)}" />
            </div>
            <div class="vm-columns">
                <div class="vm-column">
                    <h4>Volumes</h4>
                    <div class="vm-list" id="vm-volume-list">${renderVolumeRows()}</div>
                </div>
                <div class="vm-column">
                    <h4>Snapshots</h4>
                    <div class="vm-compare-toolbar">
                        <select id="vm-compare-a">
                            <option value="">Snapshot A</option>
                            ${(volumeManagerState.snapshots || []).map(snapshot => `<option value="${deps.esc(snapshot.filename)}" ${volumeManagerState.compareA === snapshot.filename ? 'selected' : ''}>${deps.esc(snapshot.filename)}</option>`).join('')}
                        </select>
                        <select id="vm-compare-b">
                            <option value="">Snapshot B</option>
                            ${(volumeManagerState.snapshots || []).map(snapshot => `<option value="${deps.esc(snapshot.filename)}" ${volumeManagerState.compareB === snapshot.filename ? 'selected' : ''}>${deps.esc(snapshot.filename)}</option>`).join('')}
                        </select>
                    </div>
                    <div class="vm-compare" id="vm-compare">${renderSnapshotCompare()}</div>
                    <div class="vm-list" id="vm-snapshot-list">${renderSnapshotRows()}</div>
                </div>
            </div>
        `;
        document.getElementById('vm-refresh-btn')?.addEventListener('click', refreshVolumeManager);
        document.getElementById('vm-filter')?.addEventListener('input', (event) => {
            volumeManagerState.filter = String(event.target?.value || '').trim();
            renderVolumeManager();
        });
        document.getElementById('vm-compare-a')?.addEventListener('change', (event) => {
            volumeManagerState.compareA = String(event.target?.value || '');
            renderVolumeManager();
        });
        document.getElementById('vm-compare-b')?.addEventListener('change', (event) => {
            volumeManagerState.compareB = String(event.target?.value || '');
            renderVolumeManager();
        });
    }

    async function refreshVolumeManager() {
        if (!volumeManagerState.open && deps.getActiveTab() !== 'containers') return;
        try {
            const [volData, snapData] = await Promise.all([
                deps.apiRequest('/volumes', {}, 'Could not load volumes'),
                deps.apiRequest('/snapshots', {}, 'Could not load snapshots'),
            ]);
            volumeManagerState.volumes = volData?.volumes || [];
            volumeManagerState.snapshots = snapData?.snapshots || [];
            renderVolumeManager();
        } catch (error) {
            deps.showToast(error.message || 'Could not load volume manager', 'error');
        }
    }

    function toggleVolumeManager() {
        volumeManagerState.open = !volumeManagerState.open;
        renderVolumeManager();
        if (volumeManagerState.open) refreshVolumeManager();
    }

    async function snapshotVolume(volumeName) {
        const tag = prompt(`Snapshot tag for ${volumeName} (optional):`, '') || '';
        try {
            const payload = { volume_name: volumeName };
            if (tag.trim()) payload.tag = tag.trim();
            const data = await deps.apiRequest('/snapshots/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }, 'Snapshot creation failed');
            if (data.created) {
                deps.showToast(`Snapshot created: ${data.filename}`, 'success');
                deps.rememberRecent('volumes', volumeName);
                await refreshVolumeManager();
            }
        } catch (error) {
            deps.showToast(error.message || 'Snapshot failed', 'error');
        }
    }

    async function restoreSnapshot(filename) {
        const target = prompt(`Restore target volume for ${filename}\nLeave empty to auto-create new volume:`, '') || '';
        if (target && volumeManagerState.volumes.some(volume => volume.name === target)) {
            const overwrite = confirm(`Volume "${target}" already exists. Continue restore into existing target?`);
            if (!overwrite) return;
        }
        const proceed = confirm(`Restore snapshot "${filename}" ${target ? `into "${target}"` : 'into new volume'}?`);
        if (!proceed) return;
        try {
            const payload = { filename };
            if (target.trim()) payload.target_volume = target.trim();
            const data = await deps.apiRequest('/snapshots/restore', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }, 'Snapshot restore failed');
            if (data.restored) {
                deps.showToast(`Snapshot restored to ${data.volume}`, 'success');
                deps.rememberRecent('volumes', data.volume);
                await refreshVolumeManager();
            }
        } catch (error) {
            deps.showToast(error.message || 'Restore failed', 'error');
        }
    }

    async function deleteSnapshot(filename) {
        if (!confirm(`Delete snapshot "${filename}"?`)) return;
        try {
            await deps.apiRequest(`/snapshots/${encodeURIComponent(filename)}`, { method: 'DELETE' }, 'Could not delete snapshot');
            deps.showToast(`Snapshot deleted: ${filename}`, 'warn');
            await refreshVolumeManager();
        } catch (error) {
            deps.showToast(error.message || 'Delete snapshot failed', 'error');
        }
    }

    async function removeVolume(volumeName) {
        if (!confirm(`Delete volume "${volumeName}"?`)) return;
        try {
            await deps.apiRequest(`/volumes/${encodeURIComponent(volumeName)}`, { method: 'DELETE' }, 'Could not remove volume');
            deps.showToast(`Volume removed: ${volumeName}`, 'warn');
            await refreshVolumeManager();
        } catch (error) {
            deps.showToast(error.message || 'Remove volume failed', 'error');
        }
    }

    function registerWindowHandlers() {
        window.termStopCt = async function(id) {
            await stopContainer(id);
        };
        window.termAttachCt = function(id) {
            attachContainer(id);
        };
        window.termOpenCtDetails = function(id) {
            openContainerDrawer(id);
        };
        window.termSnapshotVolume = async function(volumeName) {
            await snapshotVolume(volumeName);
        };
        window.termRestoreSnapshot = async function(filename) {
            await restoreSnapshot(filename);
        };
        window.termDeleteSnapshot = async function(filename) {
            await deleteSnapshot(filename);
        };
        window.termRemoveVolume = async function(volumeName) {
            await removeVolume(volumeName);
        };
    }

    return {
        loadContainers,
        loadQuota,
        openContainerDrawer,
        refreshContainerDetail,
        refreshVolumeManager,
        registerWindowHandlers,
        renderContainers,
        stopContainerDetailPolling,
        suggestFix,
        toggleVolumeManager,
    };
}

export { createContainersController };
