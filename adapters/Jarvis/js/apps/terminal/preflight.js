import {
    applyAdvancedOverridesPreflightChecks,
    applyManagedStoragePreflightChecks,
    deriveTrustInfo,
    evaluateDeployPreflight,
    findManagedCatalogItem,
    hasResourceOverride,
    normalizeManagedPathCatalog,
    parseDeviceOverrides,
    parseEnvOverrides,
} from "./preflight-utils.js";
import {
    displayPrimaryName,
    displaySecondaryMeta,
    kindLabel,
    loadRuntimeHardwareResources,
    resolveDisplayHardwareResource,
} from "./runtime-hardware-ui.js";

function createPreflightController(deps) {
    let deployPreflightState = null;

    function findHardwareIntent(state, resourceId) {
        const intents = Array.isArray(state?.hardwareData?.hardware_intents)
            ? state.hardwareData.hardware_intents
            : [];
        return intents.find(item => String(item?.resource_id || '').trim() === String(resourceId || '').trim()) || null;
    }

    function findRuntimeHardwareResource(state, resourceId) {
        return resolveDisplayHardwareResource(state?.runtimeHardwareResources || [], resourceId);
    }

    function buildHardwareOptInItems(state) {
        const summary = state?.hardwarePreview?.summary || {};
        const hints = Array.isArray(summary.block_apply_handoff_resource_ids_hint)
            ? summary.block_apply_handoff_resource_ids_hint
            : [];
        return hints.map(resourceId => {
            const intent = findHardwareIntent(state, resourceId) || {};
            const resource = findRuntimeHardwareResource(state, resourceId);
            const policy = intent?.policy && typeof intent.policy === 'object' ? intent.policy : {};
            const targetPath = String(policy.container_path || '').trim();
            const requestedMode = String(policy.mode || 'ro').trim().toLowerCase() === 'rw' ? 'rw' : 'ro';
            const requestedBy = String(intent?.requested_by || '').trim();
            return {
                resourceId,
                kind: resource.kind,
                kindLabel: kindLabel(resource.kind),
                primaryName: displayPrimaryName(resource),
                secondaryMeta: displaySecondaryMeta(resource),
                hostPath: String(resource?.host_path || '').trim() || resourceId,
                targetPath,
                requestedMode,
                requestedBy,
            };
        });
    }

    function defaultHardwareOptInSelection(state) {
        return buildHardwareOptInItems(state)
            .filter(item => String(item.requestedBy || '').trim() === 'simple-wizard')
            .map(item => item.resourceId);
    }

    function renderHardwareOptInSummary(state) {
        const summary = state?.hardwarePreview?.summary || {};
        const statusRow = document.getElementById('pf-hw-status-row');
        const summaryText = document.getElementById('pf-hw-summary-text');
        const warningsEl = document.getElementById('pf-hw-warnings');
        const items = buildHardwareOptInItems(state);
        const selectedCount = Array.isArray(state?.form?.block_apply_handoff_resource_ids)
            ? state.form.block_apply_handoff_resource_ids.length
            : 0;
        if (statusRow) {
            const supported = summary.supported !== false;
            const resolvedCount = parseInt(summary.resolved_count || 0, 10);
            const requiresApproval = summary.requires_approval;
            const requiresRestart = summary.requires_restart;
            statusRow.innerHTML = [
                `<span class="bp-hw-stat ${supported ? 'ok' : 'off'}"><span class="bp-hw-dot"></span>${supported ? `${resolvedCount} Ressourcen` : 'Nicht unterstuetzt'}</span>`,
                items.length ? `<span class="bp-hw-stat ok"><span class="bp-hw-dot"></span>${items.length} Handoff${items.length === 1 ? '' : 's'} verfuegbar</span>` : '',
                items.length ? `<span class="bp-hw-stat ${selectedCount > 0 ? 'ok' : 'off'}"><span class="bp-hw-dot"></span>${selectedCount} ausgewaehlt</span>` : '',
                requiresApproval ? '<span class="bp-hw-stat warn"><span class="bp-hw-dot"></span>Approval noetig</span>' : '',
                requiresRestart ? '<span class="bp-hw-stat warn"><span class="bp-hw-dot"></span>Restart noetig</span>' : '',
            ].filter(Boolean).join('');
        }
        if (summaryText) {
            if (summary.supported === false) {
                summaryText.textContent = 'Hardware-Intents vorhanden, aber derzeit nicht voll aufloesbar.';
            } else if (items.length > 0) {
                summaryText.textContent = `${items.length} explizite Hardware-Handoffs koennen fuer diesen Deploy opt-in aktiviert werden.`;
            } else if (parseInt(summary.resolved_count || 0, 10) > 0) {
                summaryText.textContent = `${summary.resolved_count} Hardware-Ressource(n) im Deploy-Kontext aufgeloest.`;
            } else {
                summaryText.textContent = 'Keine Hardware-Intents fuer dieses Blueprint konfiguriert.';
            }
        }
        const warnings = Array.isArray(summary.warnings) ? summary.warnings : [];
        if (warningsEl) {
            if (warnings.length) {
                warningsEl.innerHTML = warnings.map(w => `<div class="bp-hw-warn-item">&#9888; ${deps.esc(String(w))}</div>`).join('');
                warningsEl.style.display = '';
            } else {
                warningsEl.style.display = 'none';
                warningsEl.innerHTML = '';
            }
        }
    }

    function normalizeManagedMode(value) {
        return String(value || 'rw').trim().toLowerCase() === 'ro' ? 'ro' : 'rw';
    }

    function createEmptyManagedMount() {
        return {
            path: '',
            container: '/workspace/managed',
            mode: 'rw',
        };
    }

    function closeDeployPreflight() {
        const modal = document.getElementById('bp-preflight');
        if (!modal) return;
        modal.classList.remove('visible');
        modal.innerHTML = '';
        deployPreflightState = null;
    }

    function getPreflightFormValues(state) {
        const base = state.blueprint?.resources || {};
        const managedMounts = Array.from(document.querySelectorAll('.pf-storage-row'))
            .map(row => ({
                path: String(row.querySelector('[data-storage-field="path"]')?.value || '').trim(),
                container: String(row.querySelector('[data-storage-field="container"]')?.value || '/workspace/managed').trim(),
                mode: normalizeManagedMode(row.querySelector('[data-storage-field="mode"]')?.value || 'rw'),
            }));
        return {
            resources: {
                cpu_limit: String(document.getElementById('pf-cpu')?.value || base.cpu_limit || '1.0').trim(),
                memory_limit: String(document.getElementById('pf-memory')?.value || base.memory_limit || '512m').trim().toLowerCase(),
                memory_swap: String(document.getElementById('pf-swap')?.value || base.memory_swap || '1g').trim().toLowerCase(),
                timeout_seconds: Number.parseInt(String(document.getElementById('pf-ttl')?.value || base.timeout_seconds || 300), 10),
                pids_limit: Number.parseInt(String(document.getElementById('pf-pids')?.value || base.pids_limit || 100), 10),
            },
            env_raw: String(document.getElementById('pf-env')?.value || ''),
            devices_raw: String(document.getElementById('pf-devices')?.value || ''),
            resume_volume: String(document.getElementById('pf-resume')?.value || '').trim(),
            managed_mounts: managedMounts,
            block_apply_handoff_resource_ids: Array.from(document.querySelectorAll('.pf-hw-chk:checked'))
                .map(el => String(el.getAttribute('data-hw-id') || '').trim())
                .filter(Boolean),
        };
    }

    function renderPreflightList(items, listClass, emptyText) {
        if (!items.length) return `<div class="pf-empty">${deps.esc(emptyText)}</div>`;
        return `<ul class="${listClass}">${items.map(item => `<li>${deps.esc(item)}</li>`).join('')}</ul>`;
    }

    function getManagedMountDrafts(state) {
        const mounts = Array.isArray(state?.form?.managed_mounts) ? state.form.managed_mounts : [];
        if (!mounts.length) {
            return state?.managedCatalog?.length ? [createEmptyManagedMount()] : [];
        }
        return mounts.map(entry => ({
            path: String(entry?.path || '').trim(),
            container: String(entry?.container || '/workspace/managed').trim() || '/workspace/managed',
            mode: normalizeManagedMode(entry?.mode || 'rw'),
        }));
    }

    function getManagedCatalogForBlueprint(state) {
        const blueprintId = String(state?.blueprint?.id || '').trim();
        const catalog = Array.isArray(state?.managedCatalog) ? [...state.managedCatalog] : [];
        return catalog.sort((a, b) => {
            const aAllowed = Array.isArray(a?.allowed_for) && blueprintId && a.allowed_for.includes(blueprintId);
            const bAllowed = Array.isArray(b?.allowed_for) && blueprintId && b.allowed_for.includes(blueprintId);
            if (aAllowed !== bAllowed) return aAllowed ? -1 : 1;
            return String(a?.label || a?.path || '').localeCompare(String(b?.label || b?.path || ''));
        });
    }

    function formatManagedCatalogOption(item, blueprintId) {
        const parts = [String(item?.label || item?.path || '').trim() || String(item?.path || '').trim()];
        const defaultMode = String(item?.default_mode || 'rw').trim().toUpperCase();
        parts.push(`[${defaultMode}]`);
        if (Array.isArray(item?.allowed_for) && item.allowed_for.includes(blueprintId)) {
            parts.push('[Recommended]');
        }
        if (item?.asset_id) {
            parts.push(`[asset:${String(item.asset_id).trim()}]`);
        }
        parts.push(`- ${String(item?.path || '').trim()}`);
        return parts.join(' ');
    }

    function renderManagedStorageRows(state) {
        const host = document.getElementById('pf-storage-list');
        const empty = document.getElementById('pf-storage-empty');
        const addBtn = document.getElementById('pf-storage-add');
        if (!host || !empty || !addBtn || !state) return;

        const catalog = getManagedCatalogForBlueprint(state);
        const blueprintId = String(state?.blueprint?.id || '').trim();
        const mounts = getManagedMountDrafts(state);
        addBtn.disabled = catalog.length === 0;

        if (!catalog.length) {
            host.innerHTML = '';
            empty.style.display = 'block';
            return;
        }

        empty.style.display = 'none';
        host.innerHTML = mounts.map((mount, index) => {
            const selectedItem = findManagedCatalogItem(catalog, mount.path);
            const defaultMode = normalizeManagedMode(selectedItem?.default_mode || mount.mode || 'rw');
            const selectedMode = defaultMode === 'ro' ? 'ro' : normalizeManagedMode(mount.mode || 'rw');
            const rowPathId = `pf-storage-path-${index}`;
            const rowTargetId = `pf-storage-target-${index}`;
            const rowModeId = `pf-storage-mode-${index}`;
            const rowHint = selectedItem
                ? [
                    selectedItem.source ? `source: ${selectedItem.source}` : '',
                    selectedItem.asset_id ? `asset: ${selectedItem.asset_id}` : '',
                    Array.isArray(selectedItem.allowed_for) && selectedItem.allowed_for.length
                        ? `allowed: ${selectedItem.allowed_for.join(', ')}`
                        : 'allowed: general',
                  ].filter(Boolean).join(' · ')
                : 'Select a broker-approved path to mount into this container.';
            return `
                <div class="pf-storage-row" data-storage-index="${index}">
                    <div class="bp-field">
                        <label for="${rowPathId}">Broker Path</label>
                        <select id="${rowPathId}" data-storage-field="path">
                            <option value="">Select external path...</option>
                            ${catalog.map(item => `
                                <option value="${deps.esc(item.path)}" ${mount.path === item.path ? 'selected' : ''}>
                                    ${deps.esc(formatManagedCatalogOption(item, blueprintId))}
                                </option>
                            `).join('')}
                        </select>
                    </div>
                    <div class="bp-field">
                        <label for="${rowTargetId}">Container Target</label>
                        <input id="${rowTargetId}" data-storage-field="container" value="${deps.esc(mount.container || '/workspace/managed')}" placeholder="/workspace/data" />
                    </div>
                    <div class="bp-field">
                        <label for="${rowModeId}">Mode</label>
                        <select id="${rowModeId}" data-storage-field="mode">
                            <option value="rw" ${selectedMode === 'rw' ? 'selected' : ''} ${defaultMode === 'ro' ? 'disabled' : ''}>Read + Write (rw)</option>
                            <option value="ro" ${selectedMode === 'ro' ? 'selected' : ''}>Read-only (ro)</option>
                        </select>
                    </div>
                    <button type="button" class="term-btn-sm danger pf-storage-remove" data-storage-remove="${index}">
                        Remove
                    </button>
                    <div class="pf-storage-row-hint">${deps.esc(rowHint)}</div>
                </div>
            `;
        }).join('');

        host.querySelectorAll('[data-storage-field="path"]').forEach(select => {
            select.addEventListener('change', () => {
                if (!deployPreflightState) return;
                deployPreflightState.form = getPreflightFormValues(deployPreflightState);
                renderManagedStorageRows(deployPreflightState);
                recalcDeployPreflight();
            });
        });
        host.querySelectorAll('[data-storage-field="container"], [data-storage-field="mode"]').forEach(input => {
            input.addEventListener('input', recalcDeployPreflight);
            input.addEventListener('change', recalcDeployPreflight);
        });
        host.querySelectorAll('[data-storage-remove]').forEach(btn => {
            btn.addEventListener('click', () => {
                if (!deployPreflightState) return;
                const current = getPreflightFormValues(deployPreflightState);
                const index = Number.parseInt(String(btn.dataset.storageRemove || '-1'), 10);
                const nextMounts = Array.isArray(current.managed_mounts)
                    ? current.managed_mounts.filter((_, itemIndex) => itemIndex !== index)
                    : [];
                deployPreflightState.form = { ...current, managed_mounts: nextMounts };
                renderManagedStorageRows(deployPreflightState);
                recalcDeployPreflight();
            });
        });
    }

    function renderHardwareOptInRows(state) {
        const host = document.getElementById('pf-hw-list');
        const empty = document.getElementById('pf-hw-empty');
        if (!host || !empty || !state) return;
        const summary = state.hardwarePreview?.summary || {};
        const items = buildHardwareOptInItems(state);
        const selected = Array.isArray(state.form?.block_apply_handoff_resource_ids)
            ? state.form.block_apply_handoff_resource_ids
            : [];
        if (!summary.engine_opt_in_available || !items.length) {
            host.innerHTML = '';
            empty.style.display = 'block';
            renderHardwareOptInSummary(state);
            return;
        }
        empty.style.display = 'none';
        host.innerHTML = items.map(item => `
            <label class="bp-hw-device-row pf-hw-option">
                <input
                    type="checkbox"
                    class="pf-hw-chk"
                    data-hw-id="${deps.esc(String(item.resourceId))}"
                    ${selected.includes(item.resourceId) ? 'checked' : ''}
                />
                <span class="pf-hw-option-main">
                    <span class="bp-hw-device-name">${deps.esc(String(item.primaryName || item.hostPath))}</span>
                    <span class="bp-hw-device-type">${deps.esc(String(item.secondaryMeta || item.kindLabel))}</span>
                </span>
                <span class="pf-hw-option-meta">
                    <span class="pf-hw-meta-chip">${deps.esc(String(item.kindLabel))}</span>
                    ${item.targetPath ? `<span class="pf-hw-meta-chip">Target ${deps.esc(item.targetPath)}</span>` : ''}
                    <span class="pf-hw-meta-chip">Mode ${deps.esc(item.requestedMode.toUpperCase())}</span>
                    ${item.requestedBy ? `<span class="pf-hw-meta-chip">By ${deps.esc(item.requestedBy)}</span>` : ''}
                </span>
            </label>
        `).join('');
        host.querySelectorAll('.pf-hw-chk').forEach(chk => {
            chk.addEventListener('change', recalcDeployPreflight);
        });
        renderHardwareOptInSummary(state);
    }

    function addManagedStorageRow() {
        if (!deployPreflightState) return;
        const current = getPreflightFormValues(deployPreflightState);
        const nextMounts = Array.isArray(current.managed_mounts) ? [...current.managed_mounts] : [];
        nextMounts.push(createEmptyManagedMount());
        deployPreflightState.form = { ...current, managed_mounts: nextMounts };
        renderManagedStorageRows(deployPreflightState);
        recalcDeployPreflight();
    }

    function renderDeployPreflightModal(state) {
        const modal = document.getElementById('bp-preflight');
        if (!modal) return;
        const blueprint = state.blueprint;
        const resources = blueprint?.resources || {};
        const trust = deriveTrustInfo(blueprint);
        modal.innerHTML = `
            <div class="bp-preflight-backdrop" id="pf-backdrop"></div>
            <div class="bp-preflight-dialog" role="dialog" aria-modal="true" aria-label="Deploy Preflight">
                <div class="bp-preflight-head">
                    <div>
                        <div class="bp-preflight-title">🚀 Deploy Preflight</div>
                        <div class="bp-preflight-subtitle">${deps.esc(blueprint?.name || blueprint?.id || 'Blueprint')}</div>
                    </div>
                    <button class="bp-preflight-close" id="pf-close" aria-label="Close preflight">✕</button>
                </div>

                <div class="bp-preflight-quick">
                    <span class="pf-chip">${deps.esc(blueprint?.id || '')}</span>
                    <span class="pf-chip">Network: ${deps.esc(String(blueprint?.network || 'internal'))}</span>
                    <span class="pf-chip">Image: ${deps.esc(blueprint?.image || 'Dockerfile')}</span>
                </div>

                <div class="bp-preflight-trust">
                    <h4>Trust Panel</h4>
                    <div class="bp-preflight-trust-grid">
                        <div class="pf-trust-item"><span>Network Risk</span><strong class="risk-${deps.esc(trust.risk)}">${deps.esc(trust.risk.toUpperCase())}</strong></div>
                        <div class="pf-trust-item"><span>Digest</span><strong>${deps.esc(trust.digest)}</strong></div>
                        <div class="pf-trust-item"><span>Signature</span><strong>${deps.esc(trust.signature)}</strong></div>
                        <div class="pf-trust-item"><span>Recommendation</span><strong>${deps.esc(trust.recommendation)}</strong></div>
                    </div>
                </div>

                <details class="bp-preflight-overrides" id="pf-overrides" ${state.advanced ? 'open' : ''}>
                    <summary>Overrides & Environment</summary>
                    <div class="bp-preflight-grid">
                        <div class="bp-field">
                            <label for="pf-cpu">CPU</label>
                            <input id="pf-cpu" value="${deps.esc(resources.cpu_limit || '1.0')}" />
                        </div>
                        <div class="bp-field">
                            <label for="pf-memory">RAM</label>
                            <input id="pf-memory" value="${deps.esc(resources.memory_limit || '512m')}" />
                        </div>
                        <div class="bp-field">
                            <label for="pf-swap">Swap</label>
                            <input id="pf-swap" value="${deps.esc(resources.memory_swap || '1g')}" />
                        </div>
                        <div class="bp-field">
                            <label for="pf-ttl">TTL (s)</label>
                            <input id="pf-ttl" type="number" min="1" step="1" value="${deps.esc(String(resources.timeout_seconds || 300))}" />
                        </div>
                        <div class="bp-field">
                            <label for="pf-pids">PIDs</label>
                            <input id="pf-pids" type="number" min="1" step="1" value="${deps.esc(String(resources.pids_limit || 100))}" />
                        </div>
                    </div>
                    <div class="bp-field">
                        <label for="pf-resume">Resume Volume (optional)</label>
                        <input id="pf-resume" placeholder="trion_ws_blueprint_..." />
                    </div>
                    <div class="bp-field">
                        <label for="pf-env">Environment Variables (Overrides)</label>
                        <textarea id="pf-env" placeholder="KEY=value&#10;ANOTHER_KEY=value"></textarea>
                        <div class="bp-field-hint">One variable per line, format KEY=VALUE</div>
                    </div>
                    <div class="bp-field">
                        <label for="pf-devices">Device Overrides (optional)</label>
                        <textarea id="pf-devices" placeholder="/dev/dri:/dev/dri&#10;/dev/video0:/dev/video0"></textarea>
                        <div class="bp-field-hint">Raw Runtime device overrides. One mapping per line. Host path must start with /dev/.</div>
                    </div>
                    <div class="bp-field pf-storage-block">
                        <div class="pf-storage-head">
                            <div>
                                <label>External Storage Paths (Storage Broker)</label>
                                <div class="bp-field-hint">
                                    Select broker-approved external paths to mount into this container. This consumes broker rules but does not expose broker settings here.
                                </div>
                            </div>
                            <button type="button" class="term-btn-sm" id="pf-storage-add">+ Add Path</button>
                        </div>
                        <div class="pf-storage-list" id="pf-storage-list"></div>
                        <div class="pf-empty" id="pf-storage-empty" style="display:none;">No broker-managed paths available for selection.</div>
                    </div>
                </details>

                <div class="bp-preflight-section">
                    <h4>Hardware Opt-in</h4>
                    <div class="bp-field-hint">
                        Strukturierte Runtime-Hardware aus dem Blueprint. Nur explizit ausgewaehlte Block-Device-Handoffs werden an den Deploy-Pfad uebergeben.
                    </div>
                    <div class="bp-hw-status-row" id="pf-hw-status-row"></div>
                    <div class="bp-hw-summary-text" id="pf-hw-summary-text"></div>
                    <div class="pf-hw-list" id="pf-hw-list"></div>
                    <div class="pf-empty" id="pf-hw-empty" style="display:none;">Keine opt-in-faehigen Hardware-Handoffs verfuegbar.</div>
                    <div class="bp-hw-warnings" id="pf-hw-warnings" style="display:none"></div>
                </div>

                <div class="bp-preflight-section">
                    <h4>Blockers</h4>
                    <div id="pf-blockers"></div>
                </div>
                <div class="bp-preflight-section">
                    <h4>Warnings</h4>
                    <div id="pf-warnings"></div>
                </div>
                <div class="bp-preflight-section">
                    <h4>Checks</h4>
                    <div id="pf-checks"></div>
                </div>

                <div class="bp-preflight-footer">
                    <button class="proto-btn-cancel" id="pf-cancel">Cancel</button>
                    <button class="proto-btn-save" id="pf-deploy">Deploy</button>
                </div>
            </div>
        `;
        modal.classList.add('visible');

        document.getElementById('pf-close')?.addEventListener('click', closeDeployPreflight);
        document.getElementById('pf-cancel')?.addEventListener('click', closeDeployPreflight);
        document.getElementById('pf-backdrop')?.addEventListener('click', closeDeployPreflight);
        document.getElementById('pf-deploy')?.addEventListener('click', executeDeployPreflight);
        document.getElementById('pf-storage-add')?.addEventListener('click', addManagedStorageRow);
        renderManagedStorageRows(state);
        renderHardwareOptInRows(state);
        ['pf-cpu', 'pf-memory', 'pf-swap', 'pf-ttl', 'pf-pids', 'pf-env', 'pf-devices', 'pf-resume'].forEach(id => {
            document.getElementById(id)?.addEventListener('input', recalcDeployPreflight);
            document.getElementById(id)?.addEventListener('change', recalcDeployPreflight);
        });
    }

    function recalcDeployPreflight() {
        if (!deployPreflightState) return;
        const formValues = getPreflightFormValues(deployPreflightState);
        deployPreflightState.form = formValues;
        const report = evaluateDeployPreflight(
            deployPreflightState.blueprint,
            deployPreflightState.quota,
            deployPreflightState.secrets,
            formValues.resources,
        );
        applyManagedStoragePreflightChecks(report, deployPreflightState.blueprint, formValues, deployPreflightState.managedCatalog || []);
        applyAdvancedOverridesPreflightChecks(report, deployPreflightState.blueprint, formValues);
        deployPreflightState.report = report;

        const blockers = document.getElementById('pf-blockers');
        const warnings = document.getElementById('pf-warnings');
        const checks = document.getElementById('pf-checks');
        const deployBtn = document.getElementById('pf-deploy');
        if (blockers) blockers.innerHTML = renderPreflightList(report.blockers, 'pf-list pf-list-blockers', 'No blockers detected.');
        if (warnings) warnings.innerHTML = renderPreflightList(report.warnings, 'pf-list pf-list-warnings', 'No warnings.');
        if (checks) checks.innerHTML = renderPreflightList(report.checks, 'pf-list pf-list-checks', 'No checks available.');
        if (!deployBtn) return;
        renderHardwareOptInSummary(deployPreflightState);
        deployBtn.disabled = report.blockers.length > 0;
        deployBtn.textContent = report.blockers.length > 0 ? 'Fix blockers before deploy' : 'Deploy';
    }

    async function openDeployPreflight(blueprintId, options = {}) {
        const modal = document.getElementById('bp-preflight');
        if (!modal) return;
        modal.classList.add('visible');
        modal.innerHTML = `
            <div class="bp-preflight-backdrop"></div>
            <div class="bp-preflight-dialog bp-preflight-loading">
                <div class="term-spinner"></div>
                <p>Running preflight for <strong>${deps.esc(blueprintId)}</strong>...</p>
            </div>
        `;

        try {
            const [blueprint, quota, secretData] = await Promise.all([
                deps.apiRequest(`/blueprints/${encodeURIComponent(blueprintId)}`, {}, 'Could not load blueprint'),
                deps.apiRequest('/quota', {}, 'Could not load quota'),
                deps.apiRequest('/secrets', {}, 'Could not load secrets'),
            ]);
            let hardwareData = {};
            let runtimeHardwareResources = [];
            try {
                hardwareData = await deps.apiRequest(`/blueprints/${encodeURIComponent(blueprintId)}/hardware`, {}, 'Could not load hardware preview');
            } catch (_) {
                hardwareData = {
                    hardware_preview: {
                        summary: {
                            supported: false,
                            warnings: ['hardware_preview_unavailable'],
                        },
                    },
                };
            }
            try {
                runtimeHardwareResources = await loadRuntimeHardwareResources(deps.getApiBase);
            } catch (_) {
                runtimeHardwareResources = [];
            }
            let managedCatalog = [];
            try {
                const managedData = await deps.apiRequest('/storage/managed-paths', {}, 'Could not load managed storage paths');
                managedCatalog = normalizeManagedPathCatalog(managedData);
            } catch (_) {
                managedCatalog = [];
            }
            deployPreflightState = {
                blueprint,
                quota,
                secrets: secretData?.secrets || [],
                managedCatalog,
                hardwareData,
                hardwarePreview: hardwareData?.hardware_preview || {},
                runtimeHardwareResources,
                advanced: Boolean(options.advanced),
                form: {
                    managed_mounts: managedCatalog.length ? [createEmptyManagedMount()] : [],
                    block_apply_handoff_resource_ids: [],
                },
                report: null,
            };
            deployPreflightState.form.block_apply_handoff_resource_ids = defaultHardwareOptInSelection(deployPreflightState);
            renderDeployPreflightModal(deployPreflightState);
            recalcDeployPreflight();
        } catch (error) {
            modal.innerHTML = `
                <div class="bp-preflight-backdrop" id="pf-backdrop"></div>
                <div class="bp-preflight-dialog">
                    <div class="bp-preflight-title">Preflight failed</div>
                    <p class="bp-preflight-error">${deps.esc(error.message || 'Unknown error')}</p>
                    <div class="bp-preflight-footer">
                        <button class="proto-btn-cancel" id="pf-cancel">Close</button>
                    </div>
                </div>
            `;
            document.getElementById('pf-backdrop')?.addEventListener('click', closeDeployPreflight);
            document.getElementById('pf-cancel')?.addEventListener('click', closeDeployPreflight);
        }
    }

    async function executeDeployPreflight() {
        if (!deployPreflightState) return;
        recalcDeployPreflight();
        const state = deployPreflightState;
        if (!state?.form || !state?.report) return;
        if (state.report.blockers.length > 0) {
            deps.showToast('Preflight has blockers. Fix them before deploy.', 'error');
            return;
        }

        let environment = {};
        try {
            environment = parseEnvOverrides(state.form.env_raw);
        } catch (error) {
            deps.showToast(error.message || 'Invalid environment overrides', 'error');
            return;
        }

        let devices = [];
        try {
            devices = parseDeviceOverrides(state.form.devices_raw);
        } catch (error) {
            deps.showToast(error.message || 'Invalid device overrides', 'error');
            return;
        }

        const payload = { blueprint_id: state.blueprint.id };
        if (hasResourceOverride(state.blueprint.resources || {}, state.form.resources)) {
            payload.override_resources = state.form.resources;
        }
        if (Object.keys(environment).length > 0) payload.environment = environment;
        if (devices.length > 0) payload.device_overrides = devices;
        if (state.form.resume_volume) payload.resume_volume = state.form.resume_volume;
        if (Array.isArray(state.form.block_apply_handoff_resource_ids) && state.form.block_apply_handoff_resource_ids.length > 0) {
            payload.block_apply_handoff_resource_ids = state.form.block_apply_handoff_resource_ids;
        }
        const managedMounts = Array.isArray(state.form.managed_mounts) ? state.form.managed_mounts : [];
        if (managedMounts.length > 0) {
            payload.mount_overrides = managedMounts
                .map(mount => {
                    const selectedManaged = findManagedCatalogItem(state.managedCatalog || [], mount.path);
                    if (!selectedManaged) return null;
                    const managedMode = selectedManaged?.default_mode === 'ro'
                        ? 'ro'
                        : normalizeManagedMode(mount.mode || 'rw');
                    return {
                        host: mount.path,
                        container: mount.container || '/workspace/managed',
                        type: 'bind',
                        mode: managedMode,
                        asset_id: String(selectedManaged?.asset_id || '').trim() || undefined,
                    };
                })
                .filter(Boolean);
        }
        if (Array.isArray(payload.mount_overrides) && payload.mount_overrides.length > 0) {
            payload.storage_scope_override = '__auto__';
        }

        try {
            const data = await deps.apiRequest('/containers/deploy', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }, 'Deploy failed');
            if (data.deployed) {
                const requested = Array.isArray(data?.hardware_deploy?.block_apply_handoff_resource_ids_requested)
                    ? data.hardware_deploy.block_apply_handoff_resource_ids_requested
                    : [];
                const applied = Array.isArray(data?.hardware_deploy?.block_apply_handoff_resource_ids_applied)
                    ? data.hardware_deploy.block_apply_handoff_resource_ids_applied
                    : [];
                const missing = requested.filter(id => !applied.includes(id));
                closeDeployPreflight();
                deps.showToast(`Container started: ${data.container?.container_id?.slice(0, 12) || 'ok'}`, 'success');
                deps.logOutput(`✅ Container started: ${data.container?.container_id?.slice(0, 12)}`, 'ansi-green');
                if (requested.length > 0) {
                    deps.logOutput(`ℹ️ Hardware handoff requested: ${requested.length}, applied: ${applied.length}`, applied.length === requested.length ? 'ansi-cyan' : 'ansi-yellow');
                    if (applied.length > 0) {
                        deps.logOutput(`↳ Applied handoffs: ${applied.join(', ')}`, 'ansi-cyan');
                    }
                    if (missing.length > 0) {
                        deps.logOutput(`↳ Not applied: ${missing.join(', ')}`, 'ansi-yellow');
                    }
                }
                if (data.container?.container_id) deps.autoFocusContainer(data.container.container_id);
                deps.rememberRecent('blueprints', state.blueprint.id);
                await deps.loadContainers();
                if (deps.getActiveTab() === 'dashboard') await deps.loadDashboard();
                return;
            }
            if (data.pending_approval) {
                closeDeployPreflight();
                const reasonText = String(data.approval_reason || data.reason || 'Approval required');
                deps.showApprovalBanner(data.approval_id, reasonText, state.blueprint.id);
                deps.showToast(`Approval required: ${reasonText}`, 'warn');
                deps.logOutput(`⚠️ Approval required: ${reasonText}`, 'ansi-yellow');
                return;
            }
            deps.showToast(data.error || data.note || 'Deploy did not start', 'warn');
        } catch (error) {
            const hint = deps.suggestFix(error.message || '');
            deps.showToast(error.message || 'Deploy failed', 'error');
            if (hint) deps.showToast(`Why blocked: ${hint}`, 'warn');
            deps.logOutput(`❌ ${error.message}`, 'ansi-red');
        }
    }

    async function deployBlueprintWithOverrides(id) {
        deps.rememberRecent('blueprints', id);
        await openDeployPreflight(id, { advanced: true });
    }

    async function deployBlueprint(id) {
        deps.rememberRecent('blueprints', id);
        await openDeployPreflight(id, { advanced: false });
    }

    return {
        deployBlueprint,
        deployBlueprintWithOverrides,
        openDeployPreflight,
    };
}

export { createPreflightController };
