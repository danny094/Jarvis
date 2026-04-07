/**
 * blueprint-simple.js — Single-screen wizard with sidebar navigation
 * Sidebar: Übersicht | CPU & Netzwerk | Input | Devices | USB | Block-Devices | Mount-Refs
 */
import {
    displayBadges,
    displayPrimaryName,
    displaySecondaryMeta,
    findHardwareResource as findRuntimeHardwareResource,
    kindLabel,
    loadRuntimeHardwareResources,
    simpleGroupId,
    simpleSelectableResourceIds,
    simpleVisibility,
} from "./runtime-hardware-ui.js";

export function createSimpleWizardController(deps) {
    let wizardRoot = null;
    let hwGrouped = {};
    let hwSearch = {};
    let hwAdvancedOpen = {};
    let activeSection = 'overview';
    let form = {
        name: '', description: '', tags: '',
        dockerfile: '',
        image: 'python:3.12-slim', network: 'internal',
        cpu: 1.0, ram: 512, hardware_ids: [],
    };

    const sections = [
        { id: 'overview',   icon: '◉', label: 'Übersicht',     sub: 'Name, Beschreibung, Tags' },
        { id: 'resources',  icon: '⚙', label: 'CPU & Netzwerk', sub: 'Kerne, RAM, Netzwerk' },
        { id: 'input',      icon: '⌨', label: 'Eingabe',        sub: 'Maus, Tastatur, Gamepads' },
        { id: 'device',     icon: '⚡', label: 'Grafik & Systemzugriff', sub: 'GPU, DRI, KVM' },
        { id: 'usb',        icon: '🔌', label: 'USB-Zubehoer',   sub: 'Controller, Headset, Webcam' },
        { id: 'block_device_ref', icon: '💾', label: 'Direkte Datentraeger', sub: 'Partitionen fuer Direktzugriff' },
        { id: 'mount_ref',  icon: '📁', label: 'Speicherpfade',  sub: 'Freigegebene Host-Pfade' },
    ];
    const hwKinds = ['input', 'device', 'usb', 'block_device_ref', 'mount_ref'];

    function findHardwareResource(resourceId) {
        const resources = hwKinds.flatMap(kind => Array.isArray(hwGrouped[kind]) ? hwGrouped[kind] : []);
        return findRuntimeHardwareResource(resources, resourceId);
    }

    function visibleHardwareItems(kind) {
        const items = Array.isArray(hwGrouped[kind]) ? hwGrouped[kind] : [];
        return items.filter(item => simpleVisibility(item) !== 'hidden');
    }

    function isHardwareItemSelected(resource) {
        return simpleSelectableResourceIds(resource).some(id => form.hardware_ids.includes(id));
    }

    function selectedVisibleCount(kind) {
        return visibleHardwareItems(kind).filter(item => isHardwareItemSelected(item)).length;
    }

    function hardwareBadgeSet(resource) {
        return new Set(displayBadges(resource).map(item => String(item || '').trim().toLowerCase()).filter(Boolean));
    }

    function isSystemCriticalResource(resource) {
        return hardwareBadgeSet(resource).has('systemkritisch');
    }

    function isGpuResource(resource) {
        const hostPath = String(resource?.host_path || '').trim().toLowerCase();
        const caps = Array.isArray(resource?.capabilities) ? resource.capabilities.map(item => String(item || '').trim().toLowerCase()) : [];
        return caps.includes('gpu') || hostPath.startsWith('/dev/dri/');
    }

    function isKvmResource(resource) {
        return String(resource?.host_path || '').trim().toLowerCase() === '/dev/kvm';
    }

    function isUsbRole(resource, token) {
        return hardwareBadgeSet(resource).has(String(token || '').trim().toLowerCase());
    }

    function isAdvancedHardwareItem(resource) {
        const visibility = simpleVisibility(resource);
        if (visibility === 'advanced') return true;
        if (isSystemCriticalResource(resource)) return true;
        if (resource?.kind === 'device' && isKvmResource(resource)) return true;
        return false;
    }

    function canAssignBlockDevice(resource) {
        const allowed = Array.isArray(resource?.metadata?.allowed_operations)
            ? resource.metadata.allowed_operations.map(item => String(item || '').trim().toLowerCase())
            : [];
        const policyState = String(resource?.metadata?.policy_state || '').trim().toLowerCase();
        return allowed.includes('assign_to_container') || policyState === 'managed_rw';
    }

    function buildHardwareIntentPolicy(resource) {
        if (!resource || typeof resource !== 'object') return {};
        if (resource.kind === 'block_device_ref') {
            const policyState = String(resource?.metadata?.policy_state || '').trim().toLowerCase();
            return { mode: policyState === 'managed_rw' ? 'rw' : 'ro' };
        }
        if (resource.kind === 'mount_ref') {
            const sourceMode = String(
                resource?.metadata?.source_mode
                || resource?.metadata?.default_mode
                || resource?.metadata?.mode
                || ''
            ).trim().toLowerCase();
            const containerPath = buildDefaultContainerPath(resource);
            if (sourceMode === 'ro' || sourceMode === 'rw') {
                return { mode: sourceMode, container_path: containerPath };
            }
            return { container_path: containerPath };
        }
        return {};
    }

    function buildDefaultContainerPath(resource) {
        const explicit = String(resource?.metadata?.default_container_path || '').trim();
        if (explicit.startsWith('/')) return explicit;
        const assetId = String(resource?.metadata?.asset_id || resource?.id || '').trim().toLowerCase();
        const token = assetId
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 64) || 'storage';
        return `/storage/${token}`;
    }

    function hardwareStatus(resource) {
        if (isSystemCriticalResource(resource)) {
            return { label: 'Systemkritisch', css: 'danger' };
        }
        if (resource?.kind === 'mount_ref') {
            return { label: 'Funktioniert direkt', css: 'ok' };
        }
        if (resource?.kind === 'block_device_ref') {
            return { label: 'Nur mit Review', css: 'warn' };
        }
        if (isKvmResource(resource)) {
            return { label: 'Erweitert', css: 'warn' };
        }
        if (isGpuResource(resource)) {
            return { label: 'Funktioniert direkt', css: 'ok' };
        }
        if (String(resource?.risk_level || '').trim().toLowerCase() === 'high') {
            return { label: 'Pruefen', css: 'warn' };
        }
        return { label: 'Funktioniert direkt', css: 'ok' };
    }

    function hardwareExplainText(resource) {
        if (isGpuResource(resource)) {
            return 'GPU-Zugriff fuer Rendering oder Hardware-Encoding. Sinnvoll fuer Gaming, Streaming und Media.';
        }
        if (isKvmResource(resource)) {
            return 'Nur noetig, wenn der Container selbst VMs starten soll.';
        }
        if (resource?.kind === 'block_device_ref') {
            return 'Direktes Block-Device. Nur noetig, wenn die App das Geraet selbst sehen muss.';
        }
        if (resource?.kind === 'mount_ref') {
            return `Empfohlen fuer normale Datenpfade im Container. Standard-Ziel: ${buildDefaultContainerPath(resource)}`;
        }
        return '';
    }

    function hardwareMatchesQuery(resource, query) {
        const needle = String(query || '').trim().toLowerCase();
        if (!needle) return true;
        const haystack = [
            displayPrimaryName(resource),
            displaySecondaryMeta(resource),
            displayBadges(resource).join(' '),
            String(resource?.label || ''),
            String(resource?.host_path || ''),
        ].join(' ').toLowerCase();
        return haystack.includes(needle);
    }

    function replaceHardwareSelectionForKind(kind, nextIds) {
        const knownIds = new Set(
            (Array.isArray(hwGrouped[kind]) ? hwGrouped[kind] : [])
                .flatMap(resource => simpleSelectableResourceIds(resource))
        );
        const preserved = form.hardware_ids.filter(id => !knownIds.has(id));
        form.hardware_ids = Array.from(new Set([...preserved, ...nextIds]));
    }

    function presetResourceIds(kind, presetLabel, items) {
        const visibleItems = Array.isArray(items) ? items : [];
        const lowerLabel = String(presetLabel || '').trim().toLowerCase();
        const minStoragePresetSize = 10 * 1024 * 1024 * 1024;
        const PRESETS = {
            device: {
                'Gaming': resource => isGpuResource(resource) || isKvmResource(resource),
                'Media': resource => isGpuResource(resource),
                'Desktop-App': resource => isGpuResource(resource),
            },
            usb: {
                'Controller': resource => {
                    const text = `${displayPrimaryName(resource)} ${displaySecondaryMeta(resource)}`.toLowerCase();
                    return isUsbRole(resource, 'controller') || text.includes('controller') || text.includes('gamepad');
                },
                'Headset': resource => {
                    const text = `${displayPrimaryName(resource)} ${displaySecondaryMeta(resource)}`.toLowerCase();
                    return isUsbRole(resource, 'audio') || text.includes('headset') || text.includes('audio') || text.includes('micro');
                },
            },
            block_device_ref: {
                'NAS/Storage': resource => {
                    const sizeBytes = Number(resource?.metadata?.size_bytes || 0);
                    return String(resource?.kind || '') === 'block_device_ref'
                        && !isSystemCriticalResource(resource)
                        && canAssignBlockDevice(resource)
                        && sizeBytes >= minStoragePresetSize;
                },
            },
        };
        const matcher = PRESETS[kind]?.[Object.keys(PRESETS[kind] || {}).find(key => key.toLowerCase() === lowerLabel) || presetLabel];
        if (typeof matcher !== 'function') return [];
        return visibleItems.filter(resource => matcher(resource)).flatMap(resource => simpleSelectableResourceIds(resource));
    }

    function openWizard() {
        wizardRoot = document.getElementById('bp-editor');
        if (!wizardRoot) return;
        form = { name:'', description:'', tags:'', dockerfile:'', image:'python:3.12-slim',
                 network:'internal', cpu:1.0, ram:512, hardware_ids:[] };
        activeSection = 'overview';
        hwGrouped = {};
        hwSearch = {};
        hwAdvancedOpen = {};
        renderWizard();
        loadHardware();
        wizardRoot.classList.add('visible');
    }

    function closeWizard() {
        if (wizardRoot) { wizardRoot.classList.remove('visible'); wizardRoot.innerHTML = ''; }
    }

    function renderWizard() {
        if (!wizardRoot) return;
        const sidebarHtml = sections.map(s => {
            const hwCount = hwKinds.includes(s.id) ? visibleHardwareItems(s.id).length : 0;
            const selCount = hwKinds.includes(s.id) ? selectedVisibleCount(s.id) : 0;
            const isActive = s.id === activeSection;
            const badge = hwCount > 0
                ? `<span class="swz-nav-badge${selCount>0?' sel':''}">${selCount>0?selCount+'/':''}${hwCount}</span>` : '';
            return `<div class="swz-nav-item${isActive?' active':''}" data-sec="${s.id}">
                <span class="swz-nav-icon">${s.icon}</span>
                <div class="swz-nav-text">
                    <span class="swz-nav-label">${s.label}</span>
                    <span class="swz-nav-sub">${s.sub}</span>
                </div>
                ${badge}
            </div>`;
        }).join('');

        wizardRoot.innerHTML = `
            <div class="swz-backdrop" id="swz-backdrop"></div>
            <div class="swz-dialog" role="dialog">
                <div class="swz-head">
                    <div>
                        <div class="bp-editor-title">✦ Neues Blueprint — Simple</div>
                        <div class="bp-editor-subtitle">Konfiguriere Name, Ressourcen und Hardware</div>
                    </div>
                    <button class="bp-editor-close" id="swz-close">✕</button>
                </div>
                <div class="swz-layout">
                    <div class="swz-sidebar" id="swz-sidebar">${sidebarHtml}</div>
                    <div class="swz-content" id="swz-content"></div>
                </div>
                <div class="swz-footer">
                    <div class="swz-footer-inner">
                        <span class="swz-footer-hint" id="swz-hint"></span>
                        <button class="proto-btn-save" id="swz-create">💾 Blueprint erstellen</button>
                    </div>
                </div>
            </div>`;

        document.getElementById('swz-close')?.addEventListener('click', closeWizard);
        document.getElementById('swz-backdrop')?.addEventListener('click', closeWizard);
        document.getElementById('swz-create')?.addEventListener('click', deploySimple);
        document.querySelectorAll('.swz-nav-item').forEach(el => {
            el.addEventListener('click', () => {
                collectCurrent();
                activeSection = el.getAttribute('data-sec');
                renderNav();
                renderContent();
            });
        });
        renderContent();
    }

    function renderNav() {
        document.querySelectorAll('.swz-nav-item').forEach(el => {
            const sec = el.getAttribute('data-sec');
            el.classList.toggle('active', sec === activeSection);
            const badge = el.querySelector('.swz-nav-badge');
            if (badge && hwKinds.includes(sec)) {
                const total = visibleHardwareItems(sec).length;
                const sel = selectedVisibleCount(sec);
                badge.textContent = sel > 0 ? sel+'/'+total : total;
                badge.classList.toggle('sel', sel > 0);
            }
        });
    }

    function renderContent() {
        const content = document.getElementById('swz-content');
        if (!content) return;
        if (activeSection === 'overview') renderOverview(content);
        else if (activeSection === 'resources') renderResources(content);
        else renderHardwareSection(content, activeSection);
    }

    function renderOverview(content) {
        content.innerHTML = `
            <div class="swz-section-head">Übersicht</div>
            <div class="bp-field">
                <label for="swz-name">Name <span class="swz-required">*</span></label>
                <input id="swz-name" value="${deps.esc(form.name)}" placeholder="Mein Container" autocomplete="off" />
            </div>
            <div class="bp-field">
                <label for="swz-desc">Beschreibung</label>
                <input id="swz-desc" value="${deps.esc(form.description)}" placeholder="Kurze Beschreibung..." />
            </div>
            <div class="bp-field">
                <label for="swz-tags">Tags</label>
                <input id="swz-tags" value="${deps.esc(form.tags)}" placeholder="python, sandbox, dev" />
                <div class="bp-field-hint">Kommagetrennt</div>
            </div>
            <div class="bp-field">
                <label for="swz-image">Docker Image</label>
                <input id="swz-image" value="${deps.esc(form.image)}" placeholder="python:3.12-slim" />
                <div class="bp-field-hint">Optional, wenn du stattdessen ein Dockerfile hinterlegst</div>
            </div>
            <div class="bp-field">
                <label for="swz-dockerfile">Custom Dockerfile</label>
                <textarea id="swz-dockerfile" placeholder="FROM python:3.12-slim&#10;RUN pip install -r requirements.txt">${deps.esc(form.dockerfile)}</textarea>
                <div class="bp-field-hint">Dockerfile oder Image muss gesetzt sein. Fuer SteamOS-/Sunshine-Tests kannst du hier direkt den Build hinterlegen.</div>
            </div>
            <div class="swz-summary-divider">━━━ Ausgewählte Hardware ━━━</div>
            <div id="swz-hw-summary">${renderHwSummary()}</div>`;
        bindSummaryRemove();
        setTimeout(() => document.getElementById('swz-name')?.focus(), 60);
    }

    function renderHwSummary() {
        const selected = form.hardware_ids;
        if (!selected.length) return '<div class="swz-hw-empty-sm">Noch keine Hardware ausgewählt.</div>';
        const visibleEntries = [];
        const coveredIds = new Set();
        hwKinds.flatMap(kind => visibleHardwareItems(kind)).forEach(resource => {
            const removeIds = simpleSelectableResourceIds(resource);
            if (!removeIds.some(id => selected.includes(id))) return;
            visibleEntries.push({
                resource,
                kind: resource.kind,
                removeIds,
                key: simpleGroupId(resource) || resource.id,
            });
            removeIds.forEach(id => coveredIds.add(id));
        });
        selected.forEach(id => {
            if (coveredIds.has(id)) return;
            const resource = findHardwareResource(id);
            if (!resource) return;
            visibleEntries.push({
                resource,
                kind: resource.kind,
                removeIds: [id],
                key: id,
            });
        });
        const kindIcons = {input:'⌨',device:'⚡',usb:'🔌',block_device_ref:'💾',mount_ref:'📁'};
        return visibleEntries.map(entry => {
            const resource = entry.resource;
            const path = String(resource?.host_path || entry.removeIds[0] || '');
            const primary = resource ? displayPrimaryName(resource) : path;
            const secondary = resource ? displaySecondaryMeta(resource) : path;
            const badges = resource ? displayBadges(resource) : [];
            return `<div class="swz-summary-item" data-group="${deps.esc(entry.key)}">
                <span class="swz-summary-icon">${kindIcons[entry.kind]||'·'}</span>
                <span class="swz-summary-path">${deps.esc(primary)}</span>
                ${secondary && secondary !== primary ? `<span class="swz-summary-meta">${deps.esc(secondary)}</span>` : ''}
                ${badges.length ? `<span class="swz-summary-meta">${deps.esc(badges.join(' · '))}</span>` : ''}
                <button class="swz-summary-remove" data-remove-ids="${deps.esc(entry.removeIds.join('||'))}">✕</button>
            </div>`;
        }).join('');
    }

    function bindSummaryRemove() {
        document.querySelectorAll('.swz-summary-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const removeIds = String(btn.getAttribute('data-remove-ids') || '')
                    .split('||')
                    .map(item => item.trim())
                    .filter(Boolean);
                form.hardware_ids = form.hardware_ids.filter(x => !removeIds.includes(x));
                document.getElementById('swz-hw-summary').innerHTML = renderHwSummary();
                bindSummaryRemove();
                renderNav();
            });
        });
    }

    function renderResources(content) {
        const cpu = parseFloat(form.cpu) || 1.0;
        const ram = parseInt(form.ram) || 512;
        content.innerHTML = `
            <div class="swz-section-head">CPU & Netzwerk</div>
            <div class="bp-field">
                <label>Virtuelle CPU-Kerne <span class="swz-val-badge" id="swz-cpu-val">${cpu.toFixed(1)} vCPU</span></label>
                <input type="range" id="swz-cpu" min="0.5" max="16" step="0.5" value="${cpu}" />
                <div class="swz-range-labels"><span>0.5 — minimal</span><span>4.0 — Standard</span><span>16 — max</span></div>
                <div class="bp-field-hint">Virtuelle Kerne (vCPU) — entspricht Docker cpu_limit</div>
            </div>
            <div class="bp-field">
                <label>RAM <span class="swz-val-badge" id="swz-ram-val">${_fmtRam(ram)}</span></label>
                <input type="range" id="swz-ram" min="256" max="32768" step="256" value="${ram}" />
                <div class="swz-range-labels"><span>256m</span><span>8g</span><span>32g</span></div>
            </div>
            <div class="bp-field" style="margin-top:20px">
                <label for="swz-network">Netzwerk</label>
                <select id="swz-network">
                    <option value="none"     ${form.network==='none'    ?'selected':''}>Keine (vollständig isoliert)</option>
                    <option value="internal" ${form.network==='internal'?'selected':''}>Internal — Container-intern</option>
                    <option value="bridge"   ${form.network==='bridge'  ?'selected':''}>Bridge — lokales Netzwerk</option>
                    <option value="full"     ${form.network==='full'    ?'selected':''}>Full — vollständiger Internetzugang</option>
                </select>
                <div class="bp-field-hint">Full = höheres Sicherheitsrisiko, requires Approval wahrscheinlich</div>
            </div>`;
        document.getElementById('swz-cpu')?.addEventListener('input', e => {
            document.getElementById('swz-cpu-val').textContent = parseFloat(e.target.value).toFixed(1) + ' vCPU';
        });
        document.getElementById('swz-ram')?.addEventListener('input', e => {
            document.getElementById('swz-ram-val').textContent = _fmtRam(parseInt(e.target.value));
        });
    }

    function renderHardwareSection(content, kind) {
        const PRESET_LABELS = {
            device: ['Gaming', 'Media', 'Desktop-App'],
            usb: ['Controller', 'Headset'],
            block_device_ref: ['NAS/Storage'],
        };
        const secInfo = sections.find(s => s.id === kind);
        const query = String(hwSearch[kind] || '').trim();
        const items = visibleHardwareItems(kind);
        if (!items.length) {
            content.innerHTML = `<div class="swz-section-head">${secInfo?.label||kind}</div>
                <div class="swz-hw-empty">Keine Ressourcen in dieser Kategorie verfügbar.</div>`;
            return;
        }
        const filteredItems = items.filter(resource => hardwareMatchesQuery(resource, query));
        const recommendedItems = filteredItems.filter(resource => !isAdvancedHardwareItem(resource));
        const advancedItems = filteredItems.filter(resource => isAdvancedHardwareItem(resource));
        const presetLabels = PRESET_LABELS[kind] || [];
        const renderCards = cardItems => `<div class="swz-hw-rows">${cardItems.map(r => {
            const rid = deps.esc(r.id);
            const selectableIds = simpleSelectableResourceIds(r);
            const checked = selectableIds.some(id => form.hardware_ids.includes(id));
            const primary = displayPrimaryName(r);
            const secondary = displaySecondaryMeta(r);
            const badges = displayBadges(r);
            const status = hardwareStatus(r);
            const explain = hardwareExplainText(r);
            const typeLabel = kindLabel(kind);
            const extraBadges = [];
            if (isGpuResource(r)) {
                extraBadges.push({ label: 'GPU', css: 'info' });
            }
            if (String(r?.availability_state || '').trim().toLowerCase() === 'unavailable') {
                extraBadges.push({ label: 'Nicht verfuegbar', css: 'warn' });
            }
            return `<label class="swz-hw-card${checked?' selected':''}">
                <input type="checkbox" class="swz-hw-chk" data-id="${rid}" ${checked?'checked':''} />
                <div class="swz-hw-card-body">
                    <span class="swz-hw-name">${deps.esc(primary)}</span>
                    <div class="swz-hw-badges">
                        <span class="swz-hw-badge swz-hw-badge-${status.css}">${deps.esc(status.label)}</span>
                        ${extraBadges.map(badge => `<span class="swz-hw-badge swz-hw-badge-${badge.css}">${deps.esc(badge.label)}</span>`).join('')}
                        ${badges.slice(0, 3).map(badge => `<span class="swz-hw-badge swz-hw-badge-neutral">${deps.esc(badge)}</span>`).join('')}
                    </div>
                    <span class="swz-hw-meta">${deps.esc(`${typeLabel}${secondary ? ' · ' + secondary : ''}`)}</span>
                    ${explain ? `<span class="swz-hw-explain">${deps.esc(explain)}</span>` : ''}
                </div>
            </label>`;
        }).join('')}</div>`;
        content.innerHTML = `<div class="swz-section-head">${secInfo?.label||kind}</div>
            ${kind === 'block_device_ref' ? '<div class="bp-field-hint">Block-Devices werden als strukturierte Hardware-Intents gespeichert. Der spaetere Runtime-Opt-in erfolgt erst beim Deploy.</div>' : ''}
            ${kind === 'mount_ref' ? '<div class="bp-field-hint">Mount-Refs werden mit einem sicheren Standard-Zielpfad gespeichert und beim Deploy direkt als Docker-Bind-Mount materialisiert.</div>' : ''}
            ${presetLabels.length ? `<div class="swz-preset-row">${presetLabels.map(label => `<button type="button" class="swz-preset-btn" data-preset="${deps.esc(label)}">${deps.esc(label)}</button>`).join('')}</div>` : ''}
            <input class="swz-hw-search" id="swz-hw-search" value="${deps.esc(query)}" placeholder="Suchen in ${deps.esc(secInfo?.label || kind)}" />
            ${filteredItems.length ? '' : '<div class="swz-hw-empty">Keine Treffer fuer diese Suche.</div>'}
            ${recommendedItems.length ? `<div class="swz-hw-group"><div class="swz-hw-group-title">Empfohlen</div>${renderCards(recommendedItems)}</div>` : ''}
            ${advancedItems.length ? `<details class="swz-hw-advanced" ${hwAdvancedOpen[kind] ? 'open' : ''}>
                <summary class="swz-adv-toggle">Erweitert anzeigen (${advancedItems.length})</summary>
                <div class="swz-hw-group"><div class="swz-hw-group-title">Erweitert</div>${renderCards(advancedItems)}</div>
            </details>` : ''}`;
        content.querySelectorAll('.swz-preset-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const presetLabel = btn.getAttribute('data-preset');
                const presetIds = presetResourceIds(kind, presetLabel, items);
                replaceHardwareSelectionForKind(kind, presetIds);
                renderContent();
                renderNav();
            });
        });
        content.querySelector('#swz-hw-search')?.addEventListener('input', event => {
            hwSearch[kind] = event.target.value || '';
            renderHardwareSection(content, kind);
        });
        content.querySelector('.swz-hw-advanced')?.addEventListener('toggle', event => {
            hwAdvancedOpen[kind] = Boolean(event.target?.open);
        });
        content.querySelectorAll('.swz-hw-chk').forEach(chk => {
            chk.addEventListener('change', () => {
                const id = chk.getAttribute('data-id');
                const resource = findHardwareResource(id);
                const selectableIds = resource ? simpleSelectableResourceIds(resource) : [id];
                if (chk.checked) {
                    form.hardware_ids = Array.from(new Set([...form.hardware_ids, ...selectableIds]));
                } else {
                    form.hardware_ids = form.hardware_ids.filter(x => !selectableIds.includes(x));
                }
                chk.closest('.swz-hw-card')?.classList.toggle('selected', chk.checked);
                renderNav();
            });
        });
    }

    async function loadHardware() {
        try {
            const resources = (await loadRuntimeHardwareResources(deps.getApiBase))
                .filter(r => hwKinds.includes(r.kind));
            hwGrouped = {};
            resources.forEach(r => { (hwGrouped[r.kind] = hwGrouped[r.kind]||[]).push(r); });
            // Update sidebar badges
            document.querySelectorAll('.swz-nav-item').forEach(el => {
                const sec = el.getAttribute('data-sec');
                if (!hwKinds.includes(sec)) return;
                const count = visibleHardwareItems(sec).length;
                let badge = el.querySelector('.swz-nav-badge');
                if (!badge && count > 0) {
                    badge = document.createElement('span');
                    badge.className = 'swz-nav-badge';
                    el.appendChild(badge);
                }
                if (badge) badge.textContent = count;
            });
            // Re-render if already on a hw section
            if (hwKinds.includes(activeSection)) renderContent();
        } catch(_) {}
    }

    function collectCurrent() {
        if (activeSection === 'overview') {
            form.name = String(document.getElementById('swz-name')?.value || '').trim();
            form.description = String(document.getElementById('swz-desc')?.value || '').trim();
            form.tags = String(document.getElementById('swz-tags')?.value || '').trim();
            form.image = String(document.getElementById('swz-image')?.value || '').trim();
            form.dockerfile = String(document.getElementById('swz-dockerfile')?.value || '').trim();
        } else if (activeSection === 'resources') {
            form.cpu     = parseFloat(document.getElementById('swz-cpu')?.value) || form.cpu;
            form.ram     = parseInt(document.getElementById('swz-ram')?.value)    || form.ram;
            form.network = document.getElementById('swz-network')?.value          || form.network;
        }
    }

    async function deploySimple() {
        collectCurrent();
        if (!form.name) {
            activeSection = 'overview'; renderNav(); renderContent();
            setTimeout(() => { const el = document.getElementById('swz-name'); if(el){ el.style.borderColor='rgba(248,81,73,.6)'; el.focus(); el.placeholder='Name ist erforderlich'; setTimeout(()=>{el.style.borderColor='';el.placeholder='Mein Container';},2500); }}, 80);
            return;
        }
        if (!form.image && !form.dockerfile) {
            activeSection = 'overview'; renderNav(); renderContent();
            setTimeout(() => {
                const imageEl = document.getElementById('swz-image');
                const dockerfileEl = document.getElementById('swz-dockerfile');
                [imageEl, dockerfileEl].forEach(el => {
                    if (!el) return;
                    el.style.borderColor = 'rgba(248,81,73,.6)';
                    setTimeout(() => { el.style.borderColor = ''; }, 2500);
                });
                dockerfileEl?.focus();
            }, 80);
            deps.showToast('Dockerfile oder Image muss gesetzt sein', 'error');
            return;
        }
        const btn = document.getElementById('swz-create');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Wird erstellt…'; }

        const ramStr = form.ram >= 1024 ? Math.round(form.ram/1024)+'g' : form.ram+'m';
        const swapStr = form.ram*2 >= 1024 ? Math.round(form.ram*2/1024)+'g' : form.ram*2+'m';
        const hardwareIntents = form.hardware_ids.map(resourceId => {
            const resource = findHardwareResource(resourceId);
            return {
                resource_id: resourceId,
                target_type: 'container',
                attachment_mode: 'attach',
                policy: buildHardwareIntentPolicy(resource),
                requested_by: 'simple-wizard',
            };
        });

        const bp = {
            id: _generateId(form.name), name: form.name,
            description: form.description || undefined,
            tags: form.tags ? form.tags.split(',').map(t=>t.trim()).filter(Boolean) : undefined,
            dockerfile: form.dockerfile || undefined,
            image: form.image || undefined, network: form.network,
            resources: { cpu_limit: String(form.cpu), memory_limit: ramStr, memory_swap: swapStr, pids_limit: 100, timeout_seconds: 300 },
            hardware_intents: hardwareIntents.length ? hardwareIntents : undefined,
        };
        try {
            await deps.apiRequest('/blueprints', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(bp) }, 'Blueprint konnte nicht erstellt werden');
            deps.showToast(`"${bp.name}" erstellt!`, 'success');
            deps.logOutput(`✅ Blueprint erstellt: ${bp.id}`, 'ansi-green');
            closeWizard();
            await deps.loadBlueprints?.();
        } catch(err) {
            deps.showToast(err.message||'Fehler beim Erstellen', 'error');
            if (btn) { btn.disabled=false; btn.textContent='💾 Blueprint erstellen'; }
        }
    }

    function _generateId(name) {
        return name.toLowerCase()
            .replace(/[äöüß]/g, c=>({ä:'ae',ö:'oe',ü:'ue',ß:'ss'}[c]))
            .replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,40)||'my-blueprint';
    }
    function _fmtRam(mb) { return mb>=1024?(mb/1024).toFixed(mb%1024===0?0:1)+' GB':mb+' MB'; }

    return { openWizard, closeWizard };
}
