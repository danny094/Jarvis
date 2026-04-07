import { createBlueprintEditorController } from "./blueprint-editor.js";
import { createPreflightController } from "./preflight.js";

function createBlueprintsController(deps) {
    const editorController = createBlueprintEditorController({
        apiRequest: (...args) => deps.apiRequest(...args),
        esc: deps.esc,
        getApiBase: () => deps.getApiBase?.(),
        loadBlueprints: () => loadBlueprints(),
        logOutput: (...args) => deps.logOutput(...args),
    });

    const preflightController = createPreflightController({
        apiRequest: (...args) => deps.apiRequest(...args),
        autoFocusContainer: (containerId) => deps.autoFocusContainer(containerId),
        esc: deps.esc,
        getActiveTab: () => deps.getActiveTab(),
        getApiBase: () => deps.getApiBase?.(),
        loadContainers: () => deps.loadContainers(),
        loadDashboard: () => deps.loadDashboard(),
        logOutput: (...args) => deps.logOutput(...args),
        rememberRecent: (key, value) => deps.rememberRecent(key, value),
        showApprovalBanner: (...args) => deps.showApprovalBanner(...args),
        showToast: (...args) => deps.showToast(...args),
        suggestFix: (message) => deps.suggestFix(message),
    });

    async function loadBlueprints() {
        try {
            const data = await deps.apiRequest('/blueprints', {}, 'Could not load blueprints');
            deps.setBlueprints(data.blueprints || []);
            const count = document.getElementById('bp-count');
            if (count) count.textContent = String(deps.getBlueprints().length);
            renderBlueprints();
            deps.updateConnectionStatus(true);
        } catch (_) {
            deps.updateConnectionStatus(false);
            const list = document.getElementById('bp-list');
            if (list) list.innerHTML = deps.renderEmpty('📦', 'Could not load blueprints', 'Check if admin-api is running');
        }
    }

    function renderBlueprints() {
        const list = document.getElementById('bp-list');
        if (!list) return;
        const blueprints = deps.getBlueprints();
        if (!blueprints.length) {
            list.innerHTML = deps.renderEmpty('📦', 'No blueprints yet', 'Create one or import a YAML file');
            return;
        }
        const quickStatus = (bp) => {
            if (bp.network === 'full') return { tone: 'pending_approval', icon: '⚠', label: 'Approval likely', cls: 'bps-warn' };
            if (bp.image && !bp.image_digest) return { tone: 'warn', icon: '⚠', label: 'Unpinned', cls: 'bps-info' };
            return { tone: 'running', icon: '●', label: 'Ready', cls: 'bps-ok' };
        };
        list.innerHTML = blueprints.map(bp => {
            const status = quickStatus(bp);
            const cpu = bp.resources?.cpu_limit || '1.0';
            const ram = bp.resources?.memory_limit || '512m';
            const network = bp.network || 'internal';
            const tags = (bp.tags || []).map(tag => `<span class="bp-tag">${deps.esc(tag)}</span>`).join('');
            return `
                <div class="bp-card-new ${status.tone === 'pending_approval' ? 'bp-card-warn' : ''}" data-id="${bp.id}">
                    <div class="bp-card-new-main">
                        <div class="bp-card-new-icon">${bp.icon || '📦'}</div>
                        <div class="bp-card-new-info">
                            <div class="bp-card-new-top">
                                <div class="bp-card-new-name">${deps.esc(bp.name)}</div>
                                <span class="bp-status-pill-new ${status.cls}">${status.icon} ${status.label}</span>
                            </div>
                            <div class="bp-card-new-slug">${deps.esc(bp.id)}</div>
                            <div class="bp-card-new-desc">${deps.esc(bp.description || 'No description')}</div>
                            <div class="bp-card-new-meta">
                                <span class="bp-res-badge">&#9889; ${deps.esc(cpu)} CPU</span>
                                <span class="bp-res-badge">&#128190; ${deps.esc(ram)}</span>
                                <span class="bp-res-badge">&#127760; ${deps.esc(network)}</span>
                                ${tags}
                            </div>
                        </div>
                    </div>
                    <div class="bp-card-new-actions">
                        <button class="bp-act-new bp-act-edit" onclick="termEditBp('${bp.id}')">&#9999; Bearbeiten</button>
                        <button class="bp-act-new" onclick="termCloneBp('${bp.id}')">&#10063; Klonen</button>
                        <button class="bp-act-new" onclick="termExportBp('${bp.id}')">&#8675; YAML</button>
                        <button class="bp-act-new bp-act-danger" onclick="termDeleteBp('${bp.id}')">&#128465; Löschen</button>
                        <button class="bp-act-new" onclick="termDeployBpWithOverrides('${bp.id}')">&#9655; Dry Deploy</button>
                        <button class="bp-act-new bp-act-deploy" onclick="termDeployBp('${bp.id}')">&#9654; Deploy</button>
                    </div>
                </div>`;
        }).join('');
    }

    async function deleteBlueprint(id) {
        if (!confirm(`Delete blueprint "${id}"?`)) return;
        try {
            await deps.apiRequest(`/blueprints/${id}`, { method: 'DELETE' }, 'Could not delete blueprint');
            deps.logOutput(`🗑️ "${id}" deleted`, 'ansi-yellow');
            await loadBlueprints();
        } catch (error) {
            deps.showToast(error.message || 'Delete failed', 'error');
            deps.logOutput(`❌ ${error.message}`, 'ansi-red');
        }
    }

    async function editBlueprint(id) {
        const blueprint = deps.getBlueprints().find(item => item.id === id);
        if (blueprint) editorController.showBlueprintEditor(blueprint);
    }

    async function cloneBlueprint(id) {
        const source = deps.getBlueprints().find(item => item.id === id);
        if (!source) {
            deps.showToast(`Blueprint "${id}" not found`, 'error');
            return;
        }
        const cloned = JSON.parse(JSON.stringify(source));
        cloned.id = `${source.id}-copy`;
        cloned.name = `${source.name || source.id} (Copy)`;
        editorController.showBlueprintEditor(cloned, { forceCreate: true });
        deps.showToast(`Clone prepared: ${cloned.id}`, 'success');
    }

    async function exportBlueprint(id) {
        try {
            const data = await deps.apiRequest(`/blueprints/${id}/yaml`, {}, 'Could not export blueprint');
            const yaml = String(data.yaml || '');
            if (!yaml.trim()) {
                deps.showToast('No YAML content returned', 'warn');
                return;
            }
            deps.downloadText(`${id}.yaml`, yaml);
            if (navigator.clipboard?.writeText) {
                try {
                    await navigator.clipboard.writeText(yaml);
                    deps.showToast(`YAML exported + copied: ${id}.yaml`, 'success');
                } catch (_) {
                    deps.showToast(`YAML exported: ${id}.yaml`, 'success');
                }
            } else {
                deps.showToast(`YAML exported: ${id}.yaml`, 'success');
            }
            deps.logOutput(`📤 YAML export ready for ${id}\n${yaml.slice(0, 4000)}`, 'ansi-cyan');
            deps.switchTab('logs');
        } catch (error) {
            deps.showToast(error.message || 'Export failed', 'error');
            deps.logOutput(`❌ ${error.message}`, 'ansi-red');
        }
    }

    function registerWindowHandlers() {
        window.termSaveBp = async function() {
            await editorController.saveBlueprint();
        };
        window.termDeleteBp = async function(id) {
            await deleteBlueprint(id);
        };
        window.termEditBp = async function(id) {
            await editBlueprint(id);
        };
        window.termCloneBp = async function(id) {
            await cloneBlueprint(id);
        };
        window.termExportBp = async function(id) {
            await exportBlueprint(id);
        };
        window.termDeployBpWithOverrides = async function(id) {
            await preflightController.deployBlueprintWithOverrides(id);
        };
        window.termDeployBp = async function(id) {
            await preflightController.deployBlueprint(id);
        };
    }

    return {
        loadBlueprints,
        openDeployPreflight: (blueprintId, options = {}) => preflightController.openDeployPreflight(blueprintId, options),
        registerWindowHandlers,
        renderBlueprints,
        showBlueprintEditor: (bp, options = {}) => editorController.showBlueprintEditor(bp, options),
    };
}

export { createBlueprintsController };
