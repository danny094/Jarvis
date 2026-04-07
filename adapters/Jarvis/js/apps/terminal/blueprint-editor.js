import {
    parseBlueprintMounts,
    parseBlueprintSecrets,
    toDeviceLines,
    toEnvLines,
    toMountLines,
    toSecretLines,
} from "./blueprint-codec.js";
import {
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

function createBlueprintEditorController(deps) {
    let editingBp = null;

    function closeBlueprintEditor() {
        const editor = document.getElementById('bp-editor');
        if (editor) editor.classList.remove('visible');
    }

    function getBlueprintFieldErrorEl(fieldId) {
        return document.getElementById(`${fieldId}-error`);
    }

    function clearBlueprintFieldError(fieldId) {
        const wrap = document.querySelector(`.bp-field[data-field="${fieldId}"]`);
        const err = getBlueprintFieldErrorEl(fieldId);
        if (wrap) wrap.classList.remove('invalid');
        if (err) err.textContent = '';
    }

    function clearBlueprintEditorErrors() {
        const summary = document.getElementById('bp-editor-errors');
        if (summary) summary.innerHTML = '';
        document.querySelectorAll('.bp-field.invalid').forEach(el => el.classList.remove('invalid'));
        document.querySelectorAll('.bp-field-error').forEach(el => {
            el.textContent = '';
        });
    }

    function setBlueprintFieldError(fieldId, message) {
        const wrap = document.querySelector(`.bp-field[data-field="${fieldId}"]`);
        const err = getBlueprintFieldErrorEl(fieldId);
        if (wrap) wrap.classList.add('invalid');
        if (err) err.textContent = message;
    }

    function renderBlueprintEditorErrorSummary(errors) {
        const summary = document.getElementById('bp-editor-errors');
        if (!summary || !errors.length) return;
        summary.innerHTML = `
            <strong>Bitte korrigiere die markierten Felder:</strong>
            <ul>${errors.map(error => `<li>${deps.esc(error.message)}</li>`).join('')}</ul>
        `;
    }

    function validateBlueprintFormAndBuildPayload() {
        clearBlueprintEditorErrors();
        const errors = [];

        const id = String(document.getElementById('bp-ed-id')?.value || '').trim();
        const name = String(document.getElementById('bp-ed-name')?.value || '').trim();
        const icon = String(document.getElementById('bp-ed-icon')?.value || '📦').trim() || '📦';
        const description = String(document.getElementById('bp-ed-desc')?.value || '').trim();
        const dockerfile = String(document.getElementById('bp-ed-dockerfile')?.value || '').trim();
        const systemPrompt = String(document.getElementById('bp-ed-prompt')?.value || '').trim();
        const image = String(document.getElementById('bp-ed-image')?.value || '').trim();
        const network = String(document.getElementById('bp-ed-network')?.value || 'internal').trim() || 'internal';
        const extendsId = String(document.getElementById('bp-ed-extends')?.value || '').trim();
        const tagsRaw = String(document.getElementById('bp-ed-tags')?.value || '');
        const allowedExecRaw = String(document.getElementById('bp-ed-allowed-exec')?.value || '');

        const cpuLimit = String(document.getElementById('bp-ed-cpu')?.value || '').trim();
        const memoryLimit = String(document.getElementById('bp-ed-ram')?.value || '').trim();
        const memorySwap = String(document.getElementById('bp-ed-swap')?.value || '').trim();
        const ttlRaw = String(document.getElementById('bp-ed-ttl')?.value || '').trim();
        const pidsRaw = String(document.getElementById('bp-ed-pids')?.value || '').trim();

        const mountsRaw = String(document.getElementById('bp-ed-mounts')?.value || '');
        const secretsRaw = String(document.getElementById('bp-ed-secrets')?.value || '');
        const environmentRaw = String(document.getElementById('bp-ed-env')?.value || '');
        const devicesRaw = String(document.getElementById('bp-ed-devices')?.value || '');

        if (!id) errors.push({ field: 'bp-ed-id', message: 'ID ist erforderlich' });
        if (!name) errors.push({ field: 'bp-ed-name', message: 'Name ist erforderlich' });
        if (id && !/^[a-z0-9][a-z0-9-]{1,63}$/.test(id)) {
            errors.push({ field: 'bp-ed-id', message: 'ID darf nur Kleinbuchstaben, Zahlen und Bindestriche enthalten' });
        }

        if (!dockerfile && !image) {
            errors.push({ field: 'bp-ed-dockerfile', message: 'Dockerfile oder Image muss gesetzt sein' });
            errors.push({ field: 'bp-ed-image', message: 'Dockerfile oder Image muss gesetzt sein' });
        }

        if (cpuLimit && !/^\d+(?:\.\d+)?$/.test(cpuLimit)) {
            errors.push({ field: 'bp-ed-cpu', message: 'CPU muss eine Zahl sein, z. B. 0.5 oder 2.0' });
        }
        if (memoryLimit && !/^\d+(?:\.\d+)?[kmg]$/i.test(memoryLimit)) {
            errors.push({ field: 'bp-ed-ram', message: 'RAM-Format: Zahl + k/m/g, z. B. 512m oder 2g' });
        }
        if (memorySwap && !/^\d+(?:\.\d+)?[kmg]$/i.test(memorySwap)) {
            errors.push({ field: 'bp-ed-swap', message: 'Swap-Format: Zahl + k/m/g, z. B. 1g' });
        }

        const ttl = parseInt(ttlRaw, 10);
        if (!Number.isFinite(ttl) || ttl <= 0) {
            errors.push({ field: 'bp-ed-ttl', message: 'TTL muss eine positive Ganzzahl sein' });
        }

        const pids = parseInt(pidsRaw, 10);
        if (!Number.isFinite(pids) || pids <= 0) {
            errors.push({ field: 'bp-ed-pids', message: 'PIDs-Limit muss eine positive Ganzzahl sein' });
        }

        if (!['none', 'internal', 'bridge', 'full'].includes(network)) {
            errors.push({ field: 'bp-ed-network', message: 'Ungültiger Netzwerkmodus' });
        }

        const mountParse = parseBlueprintMounts(mountsRaw);
        if (mountParse.errors.length) {
            errors.push({ field: 'bp-ed-mounts', message: mountParse.errors[0] });
        }

        const secretParse = parseBlueprintSecrets(secretsRaw);
        if (secretParse.errors.length) {
            errors.push({ field: 'bp-ed-secrets', message: secretParse.errors[0] });
        }

        let environment = {};
        try {
            environment = parseEnvOverrides(environmentRaw);
        } catch (error) {
            errors.push({ field: 'bp-ed-env', message: error.message || 'Ungültige Environment Variables' });
        }

        let devices = [];
        try {
            devices = parseDeviceOverrides(devicesRaw);
        } catch (error) {
            errors.push({ field: 'bp-ed-devices', message: error.message || 'Ungültige Device Mappings' });
        }

        if (errors.length) {
            errors.forEach(error => setBlueprintFieldError(error.field, error.message));
            renderBlueprintEditorErrorSummary(errors);
            deps.logOutput('⚠️ Blueprint nicht gespeichert: Formular prüfen', 'ansi-yellow');
            return null;
        }

        return {
            id,
            name,
            description,
            dockerfile,
            system_prompt: systemPrompt,
            icon,
            image: image || null,
            extends: extendsId || null,
            network,
            tags: tagsRaw.split(',').map(tag => tag.trim()).filter(Boolean),
            mounts: mountParse.mounts,
            devices,
            environment,
            secrets_required: secretParse.secrets,
            allowed_exec: allowedExecRaw
                .split(/[\n,]/)
                .map(value => value.trim())
                .filter(Boolean),
            resources: {
                cpu_limit: cpuLimit || '1.0',
                memory_limit: memoryLimit || '512m',
                memory_swap: memorySwap || '1g',
                timeout_seconds: ttl || 300,
                pids_limit: pids || 100,
            },
        };
    }

    function validateBlueprintFieldLive(fieldId) {
        if (!fieldId) return;
        const read = (id) => String(document.getElementById(id)?.value || '').trim();
        const validators = {
            'bp-ed-id': () => {
                const id = read('bp-ed-id');
                if (!id) return 'ID ist erforderlich';
                if (!/^[a-z0-9][a-z0-9-]{1,63}$/.test(id)) return 'Nur Kleinbuchstaben/Zahlen/Bindestrich';
                return '';
            },
            'bp-ed-name': () => read('bp-ed-name') ? '' : 'Name ist erforderlich',
            'bp-ed-cpu': () => (!read('bp-ed-cpu') || /^\d+(?:\.\d+)?$/.test(read('bp-ed-cpu'))) ? '' : 'CPU muss numerisch sein',
            'bp-ed-ram': () => (!read('bp-ed-ram') || /^\d+(?:\.\d+)?[kmg]$/i.test(read('bp-ed-ram'))) ? '' : 'Format z. B. 512m',
            'bp-ed-swap': () => (!read('bp-ed-swap') || /^\d+(?:\.\d+)?[kmg]$/i.test(read('bp-ed-swap'))) ? '' : 'Format z. B. 1g',
            'bp-ed-ttl': () => (Number.parseInt(read('bp-ed-ttl'), 10) > 0) ? '' : 'TTL > 0',
            'bp-ed-pids': () => (Number.parseInt(read('bp-ed-pids'), 10) > 0) ? '' : 'PIDs > 0',
            'bp-ed-dockerfile': () => {
                const dockerfile = read('bp-ed-dockerfile');
                const image = read('bp-ed-image');
                return (dockerfile || image) ? '' : 'Dockerfile oder Image erforderlich';
            },
            'bp-ed-image': () => {
                const dockerfile = read('bp-ed-dockerfile');
                const image = read('bp-ed-image');
                return (dockerfile || image) ? '' : 'Dockerfile oder Image erforderlich';
            },
        };
        const validator = validators[fieldId];
        if (!validator) return;
        const message = validator();
        if (!message) clearBlueprintFieldError(fieldId);
        else setBlueprintFieldError(fieldId, message);
    }

    function showBlueprintEditor(bp = null, options = {}) {
        editingBp = options.forceCreate ? null : bp;
        const editor = document.getElementById('bp-editor');
        if (!editor) return;

        const mountsValue = toMountLines(bp?.mounts || []);
        const environmentValue = toEnvLines(bp?.environment || {});
        const devicesValue = toDeviceLines(bp?.devices || []);
        const secretsValue = toSecretLines(bp?.secrets_required || []);
        const allowedExecValue = Array.isArray(bp?.allowed_exec) ? bp.allowed_exec.join(', ') : '';
        editor.innerHTML = `
            <form id="bp-editor-form" class="bp-editor-form" novalidate>
                <div class="bp-editor-head">
                    <div>
                        <div class="bp-editor-title">${editingBp ? '✏️ Edit Blueprint' : '📦 New Blueprint'}</div>
                        <div class="bp-editor-subtitle">Lege Container-Profil, Ressourcen und Netzwerk sauber fest.</div>
                    </div>
                    <button type="button" class="bp-editor-close" id="bp-editor-close" aria-label="Close editor">✕</button>
                </div>

                <div class="bp-editor-section">
                    <h4>Basis</h4>
                    <div class="bp-editor-grid bp-editor-grid-3">
                        <div class="bp-field" data-field="bp-ed-id">
                            <label for="bp-ed-id">ID</label>
                            <input id="bp-ed-id" value="${bp?.id || ''}" ${editingBp ? 'disabled' : ''} placeholder="python-sandbox" />
                            <div class="bp-field-hint">Kleinbuchstaben, Zahlen, Bindestriche</div>
                            <div class="bp-field-error" id="bp-ed-id-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-name">
                            <label for="bp-ed-name">Name</label>
                            <input id="bp-ed-name" value="${deps.esc(bp?.name || '')}" placeholder="Python Sandbox" />
                            <div class="bp-field-error" id="bp-ed-name-error"></div>
                        </div>
                        <div class="bp-field bp-field-icon" data-field="bp-ed-icon">
                            <label>Icon</label>
                            <input type="hidden" id="bp-ed-icon" value="${bp?.icon || '📦'}" />
                            <div class="bp-icon-picker">
                                ${['🐍', '🟢', '🗄', '💻', '🎮', '🏠', '📦', '🔬', '🤖', '📊', '🔧', '🔐'].map(icon => `<div class="bp-icon-opt${(bp?.icon || '📦') === icon ? ' selected' : ''}" data-icon="${icon}">${icon}</div>`).join('')}
                            </div>
                            <div class="bp-field-error" id="bp-ed-icon-error"></div>
                        </div>
                    </div>
                    <div class="bp-editor-grid bp-editor-grid-2">
                        <div class="bp-field" data-field="bp-ed-desc">
                            <label for="bp-ed-desc">Beschreibung</label>
                            <input id="bp-ed-desc" value="${deps.esc(bp?.description || '')}" placeholder="Kurzbeschreibung für Team und KI" />
                            <div class="bp-field-error" id="bp-ed-desc-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-extends">
                            <label for="bp-ed-extends">Extends</label>
                            <input id="bp-ed-extends" value="${bp?.extends || ''}" placeholder="optional: base-blueprint-id" />
                            <div class="bp-field-error" id="bp-ed-extends-error"></div>
                        </div>
                    </div>
                </div>

                <div class="bp-editor-section">
                    <h4>Image & Runtime</h4>
                    <div class="bp-editor-grid bp-editor-grid-2">
                        <div class="bp-field" data-field="bp-ed-image">
                            <label for="bp-ed-image">Image (optional)</label>
                            <input id="bp-ed-image" value="${deps.esc(bp?.image || '')}" placeholder="python:3.12-slim" />
                            <div class="bp-field-hint">Alternativ zu Dockerfile</div>
                            <div class="bp-field-error" id="bp-ed-image-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-network">
                            <label for="bp-ed-network">Netzwerk</label>
                            <select id="bp-ed-network">
                                <option value="none" ${bp?.network === 'none' ? 'selected' : ''}>None (isoliert)</option>
                                <option value="internal" ${(!bp?.network || bp?.network === 'internal') ? 'selected' : ''}>Internal</option>
                                <option value="bridge" ${bp?.network === 'bridge' ? 'selected' : ''}>Bridge</option>
                                <option value="full" ${bp?.network === 'full' ? 'selected' : ''}>Full (Internet)</option>
                            </select>
                            <div class="bp-field-error" id="bp-ed-network-error"></div>
                        </div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-dockerfile">
                        <label for="bp-ed-dockerfile">Dockerfile</label>
                        <textarea id="bp-ed-dockerfile" placeholder="FROM python:3.12-slim&#10;RUN pip install -r requirements.txt">${deps.esc(bp?.dockerfile || '')}</textarea>
                        <div class="bp-field-hint">Dockerfile oder Image muss gesetzt sein</div>
                        <div class="bp-field-error" id="bp-ed-dockerfile-error"></div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-prompt">
                        <label for="bp-ed-prompt">System Prompt</label>
                        <textarea id="bp-ed-prompt" placeholder="You are a focused coding agent...">${deps.esc(bp?.system_prompt || '')}</textarea>
                        <div class="bp-field-error" id="bp-ed-prompt-error"></div>
                    </div>
                </div>

                <div class="bp-editor-section">
                    <h4>Resources</h4>
                    <div class="bp-editor-grid bp-editor-grid-4">
                        <div class="bp-field" data-field="bp-ed-cpu">
                            <label for="bp-ed-cpu">CPU</label>
                            <input id="bp-ed-cpu" value="${deps.esc(bp?.resources?.cpu_limit || '1.0')}" placeholder="1.0" />
                            <div class="bp-field-error" id="bp-ed-cpu-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-ram">
                            <label for="bp-ed-ram">RAM</label>
                            <input id="bp-ed-ram" value="${deps.esc(bp?.resources?.memory_limit || '512m')}" placeholder="512m" />
                            <div class="bp-field-error" id="bp-ed-ram-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-swap">
                            <label for="bp-ed-swap">Swap</label>
                            <input id="bp-ed-swap" value="${deps.esc(bp?.resources?.memory_swap || '1g')}" placeholder="1g" />
                            <div class="bp-field-error" id="bp-ed-swap-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-pids">
                            <label for="bp-ed-pids">PIDs</label>
                            <input id="bp-ed-pids" type="number" min="1" step="1" value="${deps.esc(String(bp?.resources?.pids_limit || 100))}" />
                            <div class="bp-field-error" id="bp-ed-pids-error"></div>
                        </div>
                    </div>
                    <div class="bp-editor-grid bp-editor-grid-2">
                        <div class="bp-field" data-field="bp-ed-ttl">
                            <label for="bp-ed-ttl">TTL (s)</label>
                            <input id="bp-ed-ttl" type="number" min="1" step="1" value="${deps.esc(String(bp?.resources?.timeout_seconds || 300))}" />
                            <div class="bp-field-error" id="bp-ed-ttl-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-tags">
                            <label for="bp-ed-tags">Tags</label>
                            <input id="bp-ed-tags" value="${deps.esc((bp?.tags || []).join(', '))}" placeholder="python,agent,sandbox" />
                            <div class="bp-field-hint">Kommagetrennt</div>
                            <div class="bp-field-error" id="bp-ed-tags-error"></div>
                        </div>
                    </div>
                </div>

                <details class="bp-editor-section" open>
                    <summary>Raw Runtime</summary>
                    <div class="bp-field" data-field="bp-ed-allowed-exec">
                        <label for="bp-ed-allowed-exec">Allowed Exec</label>
                        <textarea id="bp-ed-allowed-exec" placeholder="python, bash, sh">${deps.esc(allowedExecValue)}</textarea>
                        <div class="bp-field-hint">Kommagetrennt oder pro Zeile</div>
                        <div class="bp-field-error" id="bp-ed-allowed-exec-error"></div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-mounts">
                        <label for="bp-ed-mounts">Mounts</label>
                        <textarea id="bp-ed-mounts" placeholder="/host/path:/container/path:rw&#10;volume_name:/workspace:rw">${deps.esc(mountsValue)}</textarea>
                        <div class="bp-field-hint">Pro Zeile: host:container:mode</div>
                        <div class="bp-field-error" id="bp-ed-mounts-error"></div>
                    </div>
                    <div class="bp-editor-grid bp-editor-grid-2">
                        <div class="bp-field" data-field="bp-ed-env">
                            <label for="bp-ed-env">Environment Variables</label>
                            <textarea id="bp-ed-env" placeholder="KEY=value&#10;ANOTHER_KEY=value">${deps.esc(environmentValue)}</textarea>
                            <div class="bp-field-hint">Pro Zeile: KEY=VALUE</div>
                            <div class="bp-field-error" id="bp-ed-env-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-devices">
                            <label for="bp-ed-devices">Raw Device Overrides</label>
                            <textarea id="bp-ed-devices" placeholder="/dev/dri:/dev/dri&#10;/dev/video0:/dev/video0">${deps.esc(devicesValue)}</textarea>
                            <div class="bp-field-hint">Direkte Device-Mappings ohne Runtime-Hardware-Planung. Nur fuer Sonderfaelle.</div>
                            <div class="bp-field-error" id="bp-ed-devices-error"></div>
                        </div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-secrets">
                        <label for="bp-ed-secrets">Secrets Required</label>
                        <textarea id="bp-ed-secrets" placeholder="OPENAI_API_KEY|required|Access token">${deps.esc(secretsValue)}</textarea>
                        <div class="bp-field-hint">Pro Zeile: NAME|required|Beschreibung (oder optional)</div>
                        <div class="bp-field-error" id="bp-ed-secrets-error"></div>
                    </div>
                </details>


                <details class="bp-editor-section" id="bp-hw-details">
                    <summary id="bp-hw-summary">&#128736; Hardware Preview</summary>
                    <div id="bp-hw-body">
                        ${bp?.id ? `
                        <div class="bp-hw-loading" id="bp-hw-loading">
                            <span class="bp-hw-loading-dot"></span> Lade Hardware-Informationen…
                        </div>
                        <div id="bp-hw-content" style="display:none">` : `
                        <div id="bp-hw-content">`}
                            <div class="bp-hw-status-row" id="bp-hw-status-row"></div>
                            <div class="bp-hw-summary-text" id="bp-hw-summary-text"></div>
                            <div id="bp-hw-handoff-section" style="display:none">
                                <div class="bp-hw-handoff-label">Opt-in-faehige Block-Device-Handoffs</div>
                                <div class="bp-hw-handoff-hint">
                                    Read-only Preview. Die Auswahl erfolgt spaeter im Deploy-Dialog.
                                </div>
                                <div id="bp-hw-handoff-list" class="bp-hw-handoff-list"></div>
                            </div>
                            <div class="bp-hw-warnings" id="bp-hw-warnings" style="display:none"></div>
                        </div>
                        <div class="bp-hw-error" id="bp-hw-error" style="display:none"></div>
                    </div>
                </details>

                <div id="bp-editor-errors" class="bp-editor-errors" role="alert" aria-live="assertive"></div>

                <div class="bp-editor-footer">
                    <button type="button" class="proto-btn-cancel" id="bp-editor-cancel">Cancel</button>
                    <button type="submit" class="proto-btn-save">💾 Save Blueprint</button>
                </div>
            </form>`;
        editor.classList.add('visible');

        const form = document.getElementById('bp-editor-form');
        const cancelBtn = document.getElementById('bp-editor-cancel');
        const closeBtn = document.getElementById('bp-editor-close');

        form?.addEventListener('submit', (event) => {
            event.preventDefault();
            window.termSaveBp();
        });
        form?.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                closeBlueprintEditor();
            }
        });
        cancelBtn?.addEventListener('click', closeBlueprintEditor);
        closeBtn?.addEventListener('click', closeBlueprintEditor);

        document.querySelectorAll('.bp-icon-opt').forEach(opt => {
            opt.addEventListener('click', () => {
                document.querySelectorAll('.bp-icon-opt').forEach(item => item.classList.remove('selected'));
                opt.classList.add('selected');
                const iconInput = document.getElementById('bp-ed-icon');
                if (iconInput) iconInput.value = String(opt.getAttribute('data-icon') || opt.textContent || '📦');
            });
        });


        // ── Hardware Preview lazy loader ───────────────────────────────
        const hwDetails = document.getElementById('bp-hw-details');
        let hwLoaded = false;
        if (!bp?.id) {
            const statusRow = document.getElementById('bp-hw-status-row');
            const summaryText = document.getElementById('bp-hw-summary-text');
            if (statusRow) {
                statusRow.innerHTML = '<span class="bp-hw-stat off"><span class="bp-hw-dot"></span>Nach dem ersten Speichern verfuegbar</span>';
            }
            if (summaryText) {
                summaryText.textContent = 'Diese Vorschau arbeitet gegen das gespeicherte Blueprint und steht deshalb erst nach dem ersten Speichern zur Verfuegung.';
            }
        }
        if (hwDetails && bp?.id) {
            hwDetails.addEventListener('toggle', async () => {
                if (!hwDetails.open || hwLoaded) return;
                hwLoaded = true;
                const loading = document.getElementById('bp-hw-loading');
                const content = document.getElementById('bp-hw-content');
                const errEl = document.getElementById('bp-hw-error');
                try {
                    const runtimeResourcesPromise = loadRuntimeHardwareResources(deps.getApiBase);
                    const data = await deps.apiRequest(
                        `/blueprints/${encodeURIComponent(bp.id)}/hardware`,
                        {}, 'Hardware-Info nicht verfügbar'
                    );
                    const runtimeResources = await runtimeResourcesPromise;
                    if (loading) loading.style.display = 'none';
                    const preview = data?.hardware_preview || {};
                    const summary = preview?.summary || {};
                    const statusRow = document.getElementById('bp-hw-status-row');
                    const summaryText = document.getElementById('bp-hw-summary-text');
                    const handoffSection = document.getElementById('bp-hw-handoff-section');
                    const handoffList = document.getElementById('bp-hw-handoff-list');
                    const warningsEl = document.getElementById('bp-hw-warnings');
                    if (statusRow) {
                        const supported = summary.supported !== false;
                        const resolvedCount = parseInt(summary.resolved_count || 0);
                        const requiresApproval = summary.requires_approval;
                        const requiresRestart = summary.requires_restart;
                        statusRow.innerHTML = [
                            `<span class="bp-hw-stat ${supported ? 'ok' : 'off'}">` +
                            `<span class="bp-hw-dot"></span>${supported ? resolvedCount + ' Ressourcen' : 'Nicht unterstützt'}</span>`,
                            requiresApproval ? '<span class="bp-hw-stat warn"><span class="bp-hw-dot"></span>Approval nötig</span>' : '',
                            requiresRestart  ? '<span class="bp-hw-stat warn"><span class="bp-hw-dot"></span>Restart nötig</span>' : '',
                        ].filter(Boolean).join('');
                    }
                    if (summaryText) {
                        const txt = typeof preview.summary === 'string'
                            ? preview.summary
                            : (summary.supported === false
                                ? 'Hardware-Intents vorhanden, aber derzeit nicht voll aufloesbar.'
                                : summary.resolved_count > 0
                                ? `${summary.resolved_count} Hardware-Ressource(n) aufgelöst.`
                                : 'Keine Hardware-Intents fuer dieses Blueprint konfiguriert.');
                        summaryText.textContent = txt;
                    }
                    const hints = Array.isArray(summary.block_apply_handoff_resource_ids_hint)
                        ? summary.block_apply_handoff_resource_ids_hint : [];
                    if (summary.engine_opt_in_available && hints.length > 0 && handoffSection && handoffList) {
                        handoffList.innerHTML = hints.map(id => {
                            const resource = resolveDisplayHardwareResource(runtimeResources, id);
                            const primary = displayPrimaryName(resource);
                            const secondary = displaySecondaryMeta(resource);
                            return `
                            <div class="bp-hw-device-row">
                                <span class="bp-hw-device-name">${deps.esc(String(primary || id))}</span>
                                <span class="bp-hw-device-type">${deps.esc(String(secondary || kindLabel(resource.kind)))}</span>
                            </div>`;
                        }).join('');
                        handoffSection.style.display = '';
                    }
                    const warnings = Array.isArray(summary.warnings) ? summary.warnings : [];
                    if (warnings.length && warningsEl) {
                        warningsEl.innerHTML = warnings.map(w =>
                            `<div class="bp-hw-warn-item">&#9888; ${deps.esc(String(w))}</div>`).join('');
                        warningsEl.style.display = '';
                    }
                    if (content) content.style.display = '';
                } catch (err) {
                    hwLoaded = false;
                    if (loading) loading.style.display = 'none';
                    if (errEl) {
                        errEl.textContent = String(err?.message || 'Hardware-Info nicht verfügbar');
                        errEl.style.display = '';
                    }
                }
            });
        }
        // ── End Hardware Preview ───────────────────────────────────────
        [
            'bp-ed-id',
            'bp-ed-name',
            'bp-ed-image',
            'bp-ed-dockerfile',
            'bp-ed-cpu',
            'bp-ed-ram',
            'bp-ed-swap',
            'bp-ed-ttl',
            'bp-ed-pids',
            'bp-ed-mounts',
            'bp-ed-secrets',
            'bp-ed-env',
            'bp-ed-devices',
        ].forEach(id => {
            document.getElementById(id)?.addEventListener('input', () => {
                clearBlueprintFieldError(id);
                validateBlueprintFieldLive(id);
                if (id === 'bp-ed-image') validateBlueprintFieldLive('bp-ed-dockerfile');
                if (id === 'bp-ed-dockerfile') validateBlueprintFieldLive('bp-ed-image');
            });
        });

        const focusId = editingBp ? 'bp-ed-name' : 'bp-ed-id';
        const focusEl = document.getElementById(focusId);
        if (!focusEl) return;
        focusEl.focus();
        focusEl.select?.();
    }

    async function saveBlueprint() {
        const data = validateBlueprintFormAndBuildPayload();
        if (!data) return;
        try {
            const method = editingBp ? 'PUT' : 'POST';
            const url = editingBp ? `/blueprints/${data.id}` : '/blueprints';
            const result = await deps.apiRequest(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            }, 'Could not save blueprint');
            if (result.created || result.updated) {
                deps.logOutput(`✅ Blueprint "${data.id}" ${editingBp ? 'updated' : 'created'}`, 'ansi-green');
                closeBlueprintEditor();
                await deps.loadBlueprints();
                return;
            }
            const message = result.error || 'Unknown';
            renderBlueprintEditorErrorSummary([{ field: 'bp-ed-name', message }]);
            deps.logOutput(`❌ ${message}`, 'ansi-red');
        } catch (error) {
            deps.logOutput(`❌ ${error.message}`, 'ansi-red');
        }
    }

    return {
        saveBlueprint,
        showBlueprintEditor,
    };
}

export { createBlueprintEditorController };
