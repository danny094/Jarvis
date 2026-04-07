function createCommandInputController(deps) {
    let cmdHistory = [];
    let cmdHistoryIdx = -1;
    let cmdHistoryFilter = '';
    let commandPaletteOpen = false;

    function currentUiLanguage() {
        return String(deps.getUiLanguage?.() || '').trim().toLowerCase();
    }

    function isGermanUi() {
        return currentUiLanguage().startsWith('de');
    }

    function getQuickCommands() {
        const attachedId = deps.getAttachedContainer() ? deps.getAttachedContainer().slice(0, 12) : '';
        return [
            { cmd: '/help', expand: 'help', desc: 'Command help' },
            { cmd: '/blueprints', expand: 'list', desc: 'List blueprints' },
            { cmd: '/containers', expand: 'list containers', desc: 'Refresh containers list' },
            { cmd: '/logs', expand: attachedId ? `logs ${attachedId}` : 'logs ', desc: 'Tail logs' },
            { cmd: '/stats', expand: attachedId ? `stats ${attachedId}` : 'stats ', desc: 'Container stats' },
            { cmd: '/trion', expand: 'trion ', desc: 'TRION debug attached container' },
            { cmd: '/audit', expand: 'audit', desc: 'Show audit entries' },
            { cmd: '/quota', expand: 'quota', desc: 'Quota usage' },
            { cmd: '/market', expand: 'market list', desc: 'List marketplace catalog' },
            { cmd: '/detach', expand: 'detach', desc: 'Detach shell' },
        ];
    }

    function handleInputKeydown(event) {
        const input = event.target;
        const value = input.value;

        if (event.key === 'Enter') {
            event.preventDefault();
            hideAutocomplete();
            handleCommand(value.trim());
            cmdHistoryIdx = -1;
            input.value = '';
            return;
        }

        if (event.key === 'Tab') {
            event.preventDefault();
            applyAutocomplete(input);
            return;
        }

        if (event.key === 'ArrowUp') {
            event.preventDefault();
            if (cmdHistoryIdx < cmdHistory.length - 1) {
                cmdHistoryIdx++;
                input.value = cmdHistory[cmdHistoryIdx] || '';
            }
            return;
        }

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (cmdHistoryIdx > 0) {
                cmdHistoryIdx--;
                input.value = cmdHistory[cmdHistoryIdx] || '';
            } else {
                cmdHistoryIdx = -1;
                input.value = '';
            }
            return;
        }

        if (event.key === 'Escape') {
            hideAutocomplete();
            return;
        }

        window.setTimeout(() => showAutocomplete(input.value), 50);
    }

    function showAutocomplete(partial) {
        const dropdown = document.getElementById('term-autocomplete');
        if (!dropdown || !partial) {
            hideAutocomplete();
            return;
        }

        const parts = partial.split(/\s+/);
        const first = parts[0].toLowerCase();
        let matches = [];

        if (parts.length === 1 && first.startsWith('/')) {
            matches = getQuickCommands()
                .filter(command => command.cmd.startsWith(first))
                .map(command => ({ cmd: command.cmd, desc: command.desc, expand: command.expand }));
        } else if (parts.length === 1) {
            matches = deps.cliCommands.filter(command => command.cmd.startsWith(first) && command.cmd !== first);
        } else if (parts.length === 2 && ['deploy', 'attach', 'stop', 'restart', 'logs', 'stats', 'exec'].includes(first)) {
            const prefix = parts[1].toLowerCase();
            if (first === 'deploy') {
                matches = deps.getBlueprints()
                    .filter(bp => bp.id.toLowerCase().startsWith(prefix))
                    .map(bp => ({ cmd: bp.id, desc: bp.name }));
            } else {
                matches = deps.getContainers()
                    .filter(container => container.container_id.startsWith(prefix) || container.name?.toLowerCase().startsWith(prefix))
                    .map(container => ({ cmd: container.container_id.slice(0, 12), desc: container.name }));
            }
        }

        if (!matches.length) {
            hideAutocomplete();
            return;
        }

        dropdown.innerHTML = matches.slice(0, 6).map(match => `
            <div class="term-ac-item" data-value="${match.cmd}" data-expand="${deps.esc(match.expand || match.cmd)}">
                <span class="term-ac-cmd">${match.cmd}</span>
                <span class="term-ac-desc">${match.desc || ''}</span>
            </div>
        `).join('');
        dropdown.style.display = 'block';

        dropdown.querySelectorAll('.term-ac-item').forEach(item => {
            item.addEventListener('click', () => {
                const input = document.getElementById('term-cmd-input');
                const expand = item.dataset.expand || item.dataset.value || '';
                if (String(item.dataset.value || '').startsWith('/')) {
                    input.value = expand;
                    input.focus();
                    hideAutocomplete();
                    return;
                }
                const parts = input.value.split(/\s+/);
                if (parts.length <= 1) {
                    input.value = item.dataset.value + ' ';
                } else {
                    parts[parts.length - 1] = item.dataset.value;
                    input.value = parts.join(' ') + ' ';
                }
                input.focus();
                hideAutocomplete();
            });
        });
    }

    function applyAutocomplete(input) {
        const dropdown = document.getElementById('term-autocomplete');
        const first = dropdown?.querySelector('.term-ac-item');
        if (first) {
            const expand = first.dataset.expand || first.dataset.value || '';
            if (String(first.dataset.value || '').startsWith('/')) {
                input.value = expand;
                hideAutocomplete();
                return;
            }
            const parts = input.value.split(/\s+/);
            if (parts.length <= 1) {
                input.value = first.dataset.value + ' ';
            } else {
                parts[parts.length - 1] = first.dataset.value;
                input.value = parts.join(' ') + ' ';
            }
        }
        hideAutocomplete();
    }

    function hideAutocomplete() {
        const dropdown = document.getElementById('term-autocomplete');
        if (dropdown) dropdown.style.display = 'none';
    }

    function setHistoryFilter(value) {
        cmdHistoryFilter = String(value || '').trim().toLowerCase();
        renderHistoryList();
    }

    function renderHistoryList() {
        const root = document.getElementById('term-history-list');
        if (!root) return;
        const filtered = (cmdHistory || [])
            .filter(Boolean)
            .filter(cmd => !cmdHistoryFilter || cmd.toLowerCase().includes(cmdHistoryFilter))
            .slice(0, 8);
        if (!filtered.length) {
            root.innerHTML = '<div class="term-history-empty">No recent commands.</div>';
            return;
        }
        root.innerHTML = filtered.map(cmd => `
            <button class="term-history-item" data-cmd="${deps.esc(cmd)}">${deps.esc(cmd)}</button>
        `).join('');
        root.querySelectorAll('.term-history-item').forEach(btn => {
            btn.addEventListener('click', () => handleCommand(btn.dataset.cmd || ''));
        });
    }

    async function copyCleanLogs() {
        const raw = document.getElementById('log-stream-output')?.textContent || '';
        const clean = deps.stripAnsi(raw);
        if (!clean.trim()) {
            deps.showToast('No logs to copy', 'warn');
            return;
        }
        try {
            await navigator.clipboard.writeText(clean);
            deps.showToast('Logs copied to clipboard', 'success');
        } catch (_) {
            deps.showToast('Clipboard unavailable', 'error');
        }
    }

    function downloadLogs() {
        const raw = document.getElementById('log-stream-output')?.textContent || '';
        const clean = deps.stripAnsi(raw);
        if (!clean.trim()) {
            deps.showToast('No logs to download', 'warn');
            return;
        }
        deps.downloadText(`trion-logs-${new Date().toISOString().replace(/[:.]/g, '-')}.log`, clean);
    }

    function toggleCommandPalette(force = null) {
        const root = document.getElementById('term-command-palette');
        if (!root) return;
        commandPaletteOpen = force === null ? !commandPaletteOpen : Boolean(force);
        root.classList.toggle('visible', commandPaletteOpen);
        if (commandPaletteOpen) {
            const filter = document.getElementById('term-cmd-filter');
            if (filter) {
                filter.focus();
                filter.select?.();
            }
            renderCommandPalette();
        }
    }

    function renderCommandPalette() {
        const host = document.getElementById('term-command-groups');
        if (!host) return;
        const query = String(document.getElementById('term-cmd-filter')?.value || '').trim().toLowerCase();
        const groups = deps.commandGroups.map(group => {
            const items = group.items.filter(item => !query || item.label.toLowerCase().includes(query) || item.run.toLowerCase().includes(query));
            return { ...group, items };
        }).filter(group => group.items.length > 0);
        if (!groups.length) {
            host.innerHTML = '<div class="term-history-empty">No matching command.</div>';
            return;
        }
        host.innerHTML = groups.map(group => `
            <div class="term-command-group">
                <h4>${deps.esc(group.category)}</h4>
                ${group.items.map(item => `
                    <button class="term-command-item" data-run="${deps.esc(item.run)}">
                        <span>${deps.esc(item.label)}</span>
                        <small>${deps.esc(item.run)}</small>
                    </button>
                `).join('')}
            </div>
        `).join('');
        host.querySelectorAll('.term-command-item').forEach(btn => {
            btn.addEventListener('click', () => {
                const cmd = btn.dataset.run || '';
                toggleCommandPalette(false);
                const input = document.getElementById('term-cmd-input');
                if (cmd.endsWith(' ')) {
                    if (input) {
                        input.value = cmd;
                        input.focus();
                    }
                } else {
                    handleCommand(cmd);
                }
            });
        });
    }

    async function startTrionShellMode() {
        const attachedContainer = String(deps.getAttachedContainer() || '').trim();
        if (!attachedContainer) {
            deps.logOutput('Attach a container first, then run: trion shell', 'ansi-yellow');
            return;
        }
        deps.switchTab('logs');
        deps.setLogPanelMode('shell');
        deps.initXterm();
        deps.addShellSession(attachedContainer);
        deps.setTrionAddonDocs?.([]);
        try {
            const data = await deps.apiRequest(
                `/containers/${attachedContainer}/trion-shell/start`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        conversation_id: String(window.currentConversationId || '').trim() || 'global',
                        ui_language: String(deps.getUiLanguage?.() || '').trim() || 'en',
                    }),
                },
                'TRION shell start failed'
            );
            deps.setTrionShellMode({
                active: Boolean(data?.active),
                containerId: attachedContainer,
                language: String(data?.language || 'en'),
            });
        } catch (error) {
            deps.logOutput(`❌ ${error.message}`, 'ansi-red');
        }
    }

    async function stopTrionShellMode() {
        const shellState = deps.getTrionShellState?.() || {};
        const attachedContainer = String(shellState.containerId || deps.getAttachedContainer() || '').trim();
        if (!attachedContainer) {
            deps.setTrionShellMode({ active: false, containerId: '', language: 'en' });
            return;
        }
        try {
            const data = await deps.apiRequest(
                `/containers/${attachedContainer}/trion-shell/stop`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        conversation_id: String(window.currentConversationId || '').trim() || 'global',
                        shell_tail: deps.getShellTranscriptTail?.(12000) || '',
                        ui_language: String(deps.getUiLanguage?.() || '').trim() || 'en',
                    }),
                },
                'TRION shell stop failed'
            );
            deps.setTrionAddonDocs?.([]);
            deps.setTrionShellMode({ active: false, containerId: '', language: 'en' });
            if (String(data?.summary || '').trim()) {
                deps.logOutput(`${isGermanUi() ? 'Zusammenfassung' : 'Summary'}:\n${String(data.summary).trim()}`, 'ansi-dim');
            }
        } catch (error) {
            deps.setTrionAddonDocs?.([]);
            deps.setTrionShellMode({ active: false, containerId: '', language: 'en' });
            deps.logOutput(`❌ ${error.message}`, 'ansi-red');
        }
    }

    async function runTrionShellInstruction(instruction) {
        const shellState = deps.getTrionShellState?.() || {};
        const attachedContainer = String(shellState.containerId || deps.getAttachedContainer() || '').trim();
        if (!attachedContainer) {
            deps.logOutput('TRION shell mode has no attached container.', 'ansi-red');
            return;
        }
        deps.logOutput(
            isGermanUi()
                ? `🧠 TRION arbeitet in der Shell von ${attachedContainer.slice(0, 12)}...`
                : `🧠 TRION shell on ${attachedContainer.slice(0, 12)}...`,
            'ansi-cyan'
        );
        try {
            const data = await deps.apiRequest(
                `/containers/${attachedContainer}/trion-shell/step`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        instruction,
                        conversation_id: String(window.currentConversationId || '').trim() || 'global',
                        shell_tail: deps.getShellTranscriptTail?.(12000) || '',
                        ui_language: String(deps.getUiLanguage?.() || '').trim() || 'en',
                    }),
                },
                'TRION shell step failed'
            );
            const assistantText = String(data?.assistant || '').trim();
            const command = String(data?.command || '').trim();
            deps.setTrionAddonDocs?.(Array.isArray(data?.addon_docs) ? data.addon_docs : []);
            if (assistantText) {
                deps.logOutput(`TRION:\n${assistantText}`, 'ansi-dim');
            }
            if (command) {
                deps.logOutput(`TRION cmd> ${command}`, 'ansi-cyan');
                deps.wsSend({ type: 'stdin', container_id: attachedContainer, data: `${command}\n` });
            }
            if (data?.exit_shell) {
                await stopTrionShellMode();
            }
        } catch (error) {
            deps.logOutput(`❌ ${error.message}`, 'ansi-red');
        }
    }

    async function handleCommand(rawCmd) {
        const input = document.getElementById('term-cmd-input');
        if (!rawCmd) return;
        if (input) input.value = '';

        let cmd = normalizeQuickCommand(rawCmd);
        if (!cmd) return;
        cmdHistory.unshift(cmd);
        cmdHistory = Array.from(new Set(cmdHistory)).filter(Boolean).slice(0, 120);
        renderHistoryList();

        deps.logOutput(`trion> ${cmd}`, 'ansi-bold');

        const parts = cmd.split(/\s+/);
        const action = parts[0]?.toLowerCase();
        const shellModeActive = Boolean(deps.getTrionShellState?.().active);

        if (shellModeActive) {
            if (action === 'exit') {
                await stopTrionShellMode();
                return;
            }
            await runTrionShellInstruction(cmd);
            return;
        }

        switch (action) {
            case 'help':
                deps.logOutput('Available commands:', 'ansi-cyan');
                deps.cliCommands.forEach(item => deps.logOutput(`  ${item.cmd.padEnd(12)} ${item.desc}`, 'ansi-dim'));
                break;
            case 'list':
                if (parts[1] === 'containers') {
                    await deps.loadContainers();
                    const containers = deps.getContainers();
                    if (!containers.length) deps.logOutput('No containers running', 'ansi-dim');
                    else containers.forEach(container => deps.logOutput(`  🔄 ${container.container_id?.slice(0, 12)} — ${container.name} (${container.status})`, 'ansi-dim'));
                } else {
                    await deps.loadBlueprints();
                    deps.getBlueprints().forEach(bp => deps.logOutput(`  ${bp.icon} ${bp.id} — ${bp.name}`, 'ansi-dim'));
                }
                break;
            case 'deploy':
                if (parts[1]) await window.termDeployBp(parts[1]);
                else deps.logOutput('Usage: deploy <blueprint_id>', 'ansi-yellow');
                break;
            case 'stop':
                if (parts[1]) await window.termStopCt(parts[1]);
                else deps.logOutput('Usage: stop <container_id>', 'ansi-yellow');
                break;
            case 'restart':
                if (parts[1]) {
                    const current = deps.getContainers().find(container => String(container.container_id || '').startsWith(parts[1]));
                    if (!current) {
                        deps.logOutput('Container not found for restart', 'ansi-yellow');
                        break;
                    }
                    await window.termStopCt(current.container_id);
                    await window.termDeployBp(current.blueprint_id);
                } else deps.logOutput('Usage: restart <container_id>', 'ansi-yellow');
                break;
            case 'attach':
                if (parts[1]) {
                    deps.setAttachedContainer(parts[1]);
                    deps.wsSend({ type: 'attach', container_id: parts[1] });
                    deps.switchTab('logs');
                    deps.setLogPanelMode('shell');
                    deps.initXterm();
                    deps.addShellSession(parts[1]);
                    deps.rememberRecent('containers', parts[1]);
                } else deps.logOutput('Usage: attach <container_id>', 'ansi-yellow');
                break;
            case 'detach':
                deps.wsSend({ type: 'detach' });
                deps.removeShellSession(deps.getAttachedContainer());
                deps.setAttachedContainer(null);
                deps.logOutput('Detached', 'ansi-dim');
                break;
            case 'exec':
                if (parts[1] && parts[2]) {
                    deps.wsSend({ type: 'exec', container_id: parts[1], command: parts.slice(2).join(' ') });
                } else deps.logOutput('Usage: exec <container_id> <command>', 'ansi-yellow');
                break;
            case 'logs':
                if (parts[1]) {
                    try {
                        const data = await deps.apiRequest(`/containers/${parts[1]}/logs?tail=50`, {}, 'Could not load logs');
                        deps.logOutput(data.logs || 'No logs', '');
                    } catch (error) {
                        deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                    }
                } else deps.logOutput('Usage: logs <container_id>', 'ansi-yellow');
                break;
            case 'stats':
                if (parts[1]) {
                    try {
                        const stats = await deps.apiRequest(`/containers/${parts[1]}/stats`, {}, 'Could not load stats');
                        deps.logOutput(`CPU: ${stats.cpu_percent}% | RAM: ${stats.memory_mb}/${stats.memory_limit_mb} MB | Efficiency: ${stats.efficiency?.level}`, 'ansi-cyan');
                    } catch (error) {
                        deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                    }
                } else deps.logOutput('Usage: stats <container_id>', 'ansi-yellow');
                break;
            case 'trion': {
                const attachedContainer = String(deps.getAttachedContainer() || '').trim();
                const task = parts.slice(1).join(' ').trim();
                if (!attachedContainer) {
                    deps.logOutput('Attach a container first, then run: trion <task>', 'ansi-yellow');
                    break;
                }
                if (task.toLowerCase() === 'shell') {
                    await startTrionShellMode();
                    break;
                }
                if (!task) {
                    deps.logOutput('Usage: trion <task> | trion shell', 'ansi-yellow');
                    break;
                }
                deps.logOutput(`🧠 TRION analyzing ${attachedContainer.slice(0, 12)}...`, 'ansi-cyan');
                try {
                    const data = await deps.apiRequest(
                        `/containers/${attachedContainer}/trion-debug`,
                        {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                task,
                                conversation_id: String(window.currentConversationId || '').trim() || 'global',
                                ui_language: String(deps.getUiLanguage?.() || '').trim() || 'en',
                            }),
                        },
                        'TRION debug failed'
                    );
                    const reply = String(data?.reply || '').trim();
                    if (reply) {
                        deps.logOutput(`TRION:\n${reply}`, 'ansi-dim');
                    } else {
                        deps.logOutput('TRION returned no analysis.', 'ansi-yellow');
                    }
                } catch (error) {
                    deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                }
                break;
            }
            case 'secrets':
                await deps.loadSecrets();
                deps.getSecrets().forEach(secret => deps.logOutput(`  🔑 ${secret.name} (${secret.scope})`, 'ansi-dim'));
                break;
            case 'volumes':
                try {
                    const data = await deps.apiRequest('/volumes', {}, 'Could not load volumes');
                    if (data.volumes?.length) data.volumes.forEach(volume => deps.logOutput(`  💾 ${volume.name} (${volume.blueprint_id}) — ${volume.created_at}`, 'ansi-dim'));
                    else deps.logOutput('No volumes found', 'ansi-dim');
                } catch (error) {
                    deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                }
                break;
            case 'snapshot':
                if (parts[1]) {
                    deps.logOutput(`📸 Creating snapshot of ${parts[1]}...`, 'ansi-cyan');
                    try {
                        const data = await deps.apiRequest('/snapshots/create', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ volume_name: parts[1], tag: parts[2] || '' }),
                        }, 'Snapshot creation failed');
                        deps.logOutput(data.created ? `✅ Snapshot: ${data.filename}` : `❌ ${data.error}`, data.created ? 'ansi-green' : 'ansi-red');
                    } catch (error) {
                        deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                    }
                } else deps.logOutput('Usage: snapshot <volume_name> [tag]', 'ansi-yellow');
                break;
            case 'restore':
                if (parts[1]) {
                    try {
                        const payload = { filename: parts[1] };
                        if (parts[2]) payload.target_volume = parts[2];
                        const data = await deps.apiRequest('/snapshots/restore', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload),
                        }, 'Snapshot restore failed');
                        if (data.restored) {
                            deps.logOutput(`✅ Snapshot restored to volume ${data.volume}`, 'ansi-green');
                            await deps.refreshVolumeManager();
                        } else {
                            deps.logOutput(`❌ ${data.error || 'Restore failed'}`, 'ansi-red');
                        }
                    } catch (error) {
                        deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                    }
                } else deps.logOutput('Usage: restore <snapshot_filename> [target_volume]', 'ansi-yellow');
                break;
            case 'rmvolume':
                if (parts[1]) {
                    try {
                        await deps.apiRequest(`/volumes/${encodeURIComponent(parts[1])}`, { method: 'DELETE' }, 'Could not remove volume');
                        deps.logOutput(`🗑️ Volume removed: ${parts[1]}`, 'ansi-yellow');
                        await deps.refreshVolumeManager();
                    } catch (error) {
                        deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                    }
                } else deps.logOutput('Usage: rmvolume <volume_name>', 'ansi-yellow');
                break;
            case 'quota':
                try {
                    const quota = await deps.apiRequest('/quota', {}, 'Could not load quota');
                    deps.logOutput(`Containers: ${quota.containers_used}/${quota.max_containers} | RAM: ${quota.memory_used_mb}/${quota.max_total_memory_mb} MB | CPU: ${quota.cpu_used}/${quota.max_total_cpu}`, 'ansi-cyan');
                } catch (error) {
                    deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                }
                break;
            case 'market': {
                const sub = String(parts[1] || '').toLowerCase();
                if (sub === 'sync') {
                    const payload = {};
                    if (parts[2]) payload.repo_url = parts[2];
                    if (parts[3]) payload.branch = parts[3];
                    deps.logOutput('🔄 Syncing marketplace catalog...', 'ansi-cyan');
                    try {
                        const data = await deps.apiRequest('/marketplace/catalog/sync', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload),
                        }, 'Marketplace sync failed');
                        const categories = data.categories || {};
                        deps.logOutput(`✅ Catalog synced (${data.count || 0} blueprints) from ${data.source?.repo_url || 'source'}`, 'ansi-green');
                        Object.entries(categories).forEach(([category, count]) => {
                            deps.logOutput(`  ${category}: ${count}`, 'ansi-dim');
                        });
                    } catch (error) {
                        deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                    }
                    break;
                }
                if (sub === 'list') {
                    const category = String(parts[2] || '').trim();
                    const query = category ? `?category=${encodeURIComponent(category)}` : '';
                    try {
                        const data = await deps.apiRequest(`/marketplace/catalog${query}`, {}, 'Could not load marketplace catalog');
                        if (!data.blueprints?.length) {
                            deps.logOutput('Marketplace catalog is empty. Run: market sync', 'ansi-yellow');
                            break;
                        }
                        deps.logOutput(`🛍 Catalog (${data.count})${category ? ` [${category}]` : ''}`, 'ansi-cyan');
                        data.blueprints.slice(0, 80).forEach(bp => {
                            deps.logOutput(`  ${bp.icon || '📦'} ${bp.id} — ${bp.name} [${bp.category}] trust=${bp.trusted_level}`, 'ansi-dim');
                        });
                        if ((data.blueprints || []).length > 80) {
                            deps.logOutput('  ... truncated, use category filter', 'ansi-yellow');
                        }
                    } catch (error) {
                        deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                    }
                    break;
                }
                if (sub === 'install') {
                    const id = String(parts[2] || '').trim();
                    if (!id) {
                        deps.logOutput('Usage: market install <blueprint_id> [--overwrite]', 'ansi-yellow');
                        break;
                    }
                    const overwrite = parts.includes('--overwrite');
                    try {
                        const data = await deps.apiRequest(`/marketplace/catalog/install/${encodeURIComponent(id)}`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ overwrite }),
                        }, 'Marketplace install failed');
                        if (data.installed || data.updated || data.exists) {
                            const mode = data.installed ? 'installed' : data.updated ? 'updated' : 'already exists';
                            deps.logOutput(`✅ Marketplace blueprint ${mode}: ${data.blueprint?.id || id}`, 'ansi-green');
                            await deps.loadBlueprints();
                        } else if (data.error) {
                            deps.logOutput(`❌ ${data.error}`, 'ansi-red');
                        } else {
                            deps.logOutput('❌ Marketplace install failed', 'ansi-red');
                        }
                    } catch (error) {
                        deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                    }
                    break;
                }
                deps.logOutput('Usage: market sync [repo_url] [branch] | market list [category] | market install <id> [--overwrite]', 'ansi-yellow');
                break;
            }
            case 'audit':
                await deps.loadAuditLog();
                break;
            case 'activity':
                await deps.loadActivityFeedSnapshot();
                deps.getActivityFeed().slice(0, 25).forEach(item => {
                    deps.logOutput(`[${item.created_at}] ${item.level?.toUpperCase()} ${item.message}`, 'ansi-dim');
                });
                break;
            case 'clear':
                deps.clearTerminal();
                {
                    const output = document.getElementById('log-output');
                    if (output) output.innerHTML = '';
                }
                break;
            case 'cleanup':
                deps.logOutput('🧹 Stopping all containers...', 'ansi-yellow');
                try {
                    await deps.apiRequest('/cleanup', { method: 'POST' }, 'Cleanup failed');
                    deps.logOutput('✅ All containers stopped', 'ansi-green');
                    await deps.loadContainers();
                } catch (error) {
                    deps.logOutput(`❌ ${error.message}`, 'ansi-red');
                }
                break;
            default:
                if (deps.getAttachedContainer()) {
                    deps.wsSend({ type: 'exec', container_id: deps.getAttachedContainer(), command: cmd });
                } else {
                    deps.logOutput(`Unknown command: ${action}. Type "help" for commands.`, 'ansi-yellow');
                }
        }
    }

    function normalizeQuickCommand(cmd) {
        const clean = String(cmd || '').trim();
        if (!clean.startsWith('/')) return clean;
        const quick = getQuickCommands().find(item => item.cmd === clean.toLowerCase());
        if (quick) return quick.expand;
        return clean.slice(1);
    }

    return {
        copyCleanLogs,
        downloadLogs,
        handleCommand,
        handleInputKeydown,
        renderCommandPalette,
        renderHistoryList,
        setHistoryFilter,
        showAutocomplete,
        toggleCommandPalette,
    };
}

export { createCommandInputController };
