function createDashboardController(deps) {
    let dashboardState = {
        audit: [],
        quota: null,
        volumes: [],
        containerStats: {},
        lastLoadedAt: '',
    };

    async function loadDashboard() {
        try {
            const [quota, approvals, audit, vols, cts] = await Promise.all([
                deps.apiRequest('/quota', {}, 'Could not load quota'),
                deps.apiRequest('/approvals', {}, 'Could not load approvals'),
                deps.apiRequest('/audit?limit=120', {}, 'Could not load audit log'),
                deps.apiRequest('/volumes', {}, 'Could not load volumes'),
                deps.apiRequest('/containers', {}, 'Could not load containers'),
            ]);
            dashboardState.quota = quota;
            dashboardState.audit = audit?.entries || [];
            dashboardState.volumes = vols?.volumes || [];
            dashboardState.lastLoadedAt = new Date().toISOString();
            deps.setContainers(cts?.containers || deps.getContainers());
            deps.setPendingApprovals(approvals?.approvals || deps.getPendingApprovals());
            const containers = deps.getContainers() || [];
            const statsResults = await Promise.allSettled(
                containers.map(c => deps.apiRequest(`/containers/${c.container_id}/stats`, {}, '').catch(() => null))
            );
            dashboardState.containerStats = {};
            containers.forEach((c, i) => {
                if (statsResults[i]?.status === 'fulfilled' && statsResults[i]?.value) {
                    dashboardState.containerStats[c.container_id] = statsResults[i].value;
                }
            });
            renderDashboard();
        } catch (error) {
            const wrap = document.querySelector('#panel-dashboard .dash-wrap');
            if (wrap) wrap.innerHTML = deps.renderEmpty('\u{1F5AA}', 'Dashboard unavailable', error.message || 'Try refresh');
        }
    }

    function getTodayTimelineItems() {
        return (dashboardState.audit || []).filter(e =>
            String(e?.created_at || '').startsWith(new Date().toISOString().slice(0, 10))
        ).slice(0, 20);
    }

    function getRecentItems(key) {
        try {
            const parsed = JSON.parse(localStorage.getItem(`trion_recent_${key}`) || '[]');
            return Array.isArray(parsed) ? parsed : [];
        } catch (_) { return []; }
    }

    function rememberRecent(key, value) {
        if (!value) return;
        const next = [value, ...getRecentItems(key).filter(i => i !== value)].slice(0, 8);
        localStorage.setItem(`trion_recent_${key}`, JSON.stringify(next));
    }

    function _e(s) { return deps.esc ? deps.esc(String(s ?? '')) : String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
    function _ts(value) {
        const parsed = Date.parse(String(value || ''));
        return Number.isFinite(parsed) ? parsed : null;
    }
    function _fmtRelative(value) {
        const ts = _ts(value);
        if (!ts) return 'not loaded';
        const diffMs = Math.max(0, Date.now() - ts);
        const mins = Math.round(diffMs / 60000);
        if (diffMs < 15000) return 'just now';
        if (mins < 1) return '<1 min ago';
        if (mins < 60) return `${mins} min ago`;
        const hours = Math.round(mins / 60);
        if (hours < 24) return `${hours} h ago`;
        const days = Math.round(hours / 24);
        return `${days} d ago`;
    }
    function _fmtStamp(value) {
        const ts = _ts(value);
        if (!ts) return '—';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        }).format(new Date(ts));
    }
    function _latestAudit(matchFn) {
        return (dashboardState.audit || []).find(entry => matchFn(String(entry?.action || ''), entry));
    }
    function _restartCountLastHour() {
        const cutoff = Date.now() - (60 * 60 * 1000);
        return (dashboardState.audit || []).filter(entry => {
            const action = String(entry?.action || '');
            const ts = _ts(entry?.created_at);
            return action.includes('restart') && ts && ts >= cutoff;
        }).length;
    }
    function _idleVolumeCount() {
        const activeVolumes = new Set((deps.getContainers() || []).map(c => String(c?.volume_name || '')).filter(Boolean));
        return (dashboardState.volumes || []).filter(volume => !activeVolumes.has(String(volume?.name || ''))).length;
    }

    function renderFreshness() {
        const root = document.getElementById('dash-freshness');
        if (!root) return;
        const containers = deps.getContainers() || [];
        const volumes = dashboardState.volumes || [];
        const ageMs = dashboardState.lastLoadedAt ? Math.max(0, Date.now() - _ts(dashboardState.lastLoadedAt)) : Number.POSITIVE_INFINITY;
        const freshness = ageMs > 180000
            ? { label: 'Stale', cls: 'dash-badge-warn' }
            : ageMs > 60000
                ? { label: 'Aging', cls: 'dash-badge-warn' }
                : { label: 'Fresh', cls: 'dash-badge-ok' };

        root.innerHTML = `<div class="dash-sec-head"><span>Freshness</span><span class="dash-badge ${freshness.cls}">${freshness.label}</span></div>
            <div class="dash-freshness-main">
                <strong>${_e(_fmtRelative(dashboardState.lastLoadedAt))}</strong>
                <span>${_e(_fmtStamp(dashboardState.lastLoadedAt))}</span>
            </div>
            <div class="dash-inline-meta">
                <span class="dash-inline-chip">Refresh: manual</span>
                <span class="dash-inline-chip">${containers.length} containers</span>
                <span class="dash-inline-chip">${volumes.length} volumes</span>
            </div>`;
    }

    function renderActionQueue() {
        const root = document.getElementById('dash-action-queue');
        if (!root) return;
        const containers = deps.getContainers() || [];
        const approvals = deps.getPendingApprovals() || [];
        const q = dashboardState.quota || {};
        const actions = [];
        const quotaPct = Math.max(
            q.max_containers ? ((q.containers_used || 0) / q.max_containers) * 100 : 0,
            q.max_total_cpu ? (parseFloat(q.cpu_used || 0) / parseFloat(q.max_total_cpu || 1)) * 100 : 0,
            q.max_total_memory_mb ? (parseFloat(q.memory_used_mb || 0) / parseFloat(q.max_total_memory_mb || 1)) * 100 : 0,
        );

        if (approvals.length) {
            actions.push({
                tone: 'warn',
                title: `${approvals.length} approval${approvals.length === 1 ? '' : 's'} waiting`,
                meta: 'Review pending network/trust requests.',
                cta: 'Review',
                fn: 'termOpenApprovalCenter()',
            });
        }

        const unstable = containers.find(c => ['exited', 'dead', 'error'].includes(String(c?.status || '')));
        if (unstable?.container_id) {
            actions.push({
                tone: 'crit',
                title: `${_e(unstable.name || unstable.blueprint_id || unstable.container_id.slice(0, 12))} is ${_e(unstable.status)}`,
                meta: 'Inspect logs or redeploy from the owning blueprint.',
                cta: 'Inspect',
                fn: `termOpenCtDetails('${_e(unstable.container_id)}')`,
            });
        }

        const risky = containers.find(c => c.network === 'full' || (c.image && !c.image_digest));
        if (risky?.blueprint_id) {
            actions.push({
                tone: 'warn',
                title: risky.network === 'full' ? `${_e(risky.name || risky.blueprint_id)} uses full network` : `${_e(risky.name || risky.blueprint_id)} is unpinned`,
                meta: risky.network === 'full' ? 'Check trust level and approval necessity.' : 'Pin the image digest to reduce drift.',
                cta: 'Edit',
                fn: `termEditBp('${_e(risky.blueprint_id)}')`,
            });
        }

        if (quotaPct >= 85) {
            actions.push({
                tone: 'warn',
                title: 'Quota pressure is getting high',
                meta: `Current peak usage is ${Math.round(quotaPct)}% of quota.`,
                cta: 'Containers',
                fn: `document.querySelector('[data-tab="containers"]')?.click()`,
            });
        }

        root.innerHTML = `<div class="dash-sec-head"><span>Next Actions</span><span class="dash-badge ${actions.length ? 'dash-badge-warn' : 'dash-badge-ok'}">${actions.length ? `${Math.min(actions.length, 3)} open` : 'Clear'}</span></div>` +
            (actions.length
                ? actions.slice(0, 3).map(item => `<div class="dash-action-row">
                    <div class="dash-action-copy">
                        <div class="dash-action-title">${item.title}</div>
                        <div class="dash-action-meta">${item.meta}</div>
                    </div>
                    <button class="dash-inline-btn dash-inline-btn-${item.tone}" onclick="${item.fn}">${item.cta}</button>
                </div>`).join('')
                : '<div class="dash-empty-sm">No immediate action needed.</div>');
    }

    function renderRuntimeHealth() {
        const root = document.getElementById('dash-runtime-health');
        if (!root) return;
        const latestDeploy = _latestAudit(action => action === 'start');
        const restartsLastHour = _restartCountLastHour();
        const volumeTotal = (dashboardState.volumes || []).length;
        const idleVolumes = _idleVolumeCount();
        const health = restartsLastHour >= 2 || idleVolumes >= 4
            ? { label: 'Watch', cls: 'dash-badge-warn' }
            : { label: 'Stable', cls: 'dash-badge-ok' };

        root.innerHTML = `<div class="dash-sec-head"><span>Runtime &amp; Storage</span><span class="dash-badge ${health.cls}">${health.label}</span></div>
            <div class="dash-health-grid">
                <div class="dash-health-stat">
                    <span>Restarts 1h</span>
                    <strong>${restartsLastHour}</strong>
                </div>
                <div class="dash-health-stat">
                    <span>Volumes</span>
                    <strong>${volumeTotal}</strong>
                </div>
                <div class="dash-health-stat">
                    <span>Idle Volumes</span>
                    <strong>${idleVolumes}</strong>
                </div>
            </div>
            <div class="dash-health-footnote">${latestDeploy
                ? `Latest deploy: ${_e(latestDeploy.blueprint_id || latestDeploy.container_id || 'unknown')} at ${_e(_fmtStamp(latestDeploy.created_at))}`
                : 'No successful deploy recorded yet.'}</div>`;
    }

    // ── 1. PROBLEM CONTAINERS ──────────────────────────────────────
    function renderProblems() {
        const root = document.getElementById('dash-problems');
        if (!root) return;
        const problems = [];
        (deps.getContainers() || []).forEach(c => {
            const id = _e(c.blueprint_id || c.container_id || '?');
            const name = _e(c.name || c.blueprint_id || c.container_id?.slice(0, 12));
            if (c.status === 'exited' || c.status === 'dead')
                problems.push({ name, reason: `Status: ${_e(c.status)}`, sev: 'crit', action: 'Retry', fn: `termDeployBp('${id}')` });
            else if (c.image && !c.image_digest)
                problems.push({ name, reason: 'Unpinned image — kein Digest', sev: 'warn', action: 'Pin', fn: `termEditBp('${id}')` });
            else if (c.network === 'full')
                problems.push({ name, reason: 'Full network — Approval nötig', sev: 'warn', action: '', fn: '' });
        });
        if (!problems.length) {
            root.innerHTML = `<div class="dash-sec-head"><span>&#9888; Needs Attention</span><span class="dash-badge dash-badge-ok">&#10003; All clear</span></div><div class="dash-empty-sm">Alle Container stabil.</div>`;
            return;
        }
        root.innerHTML = `<div class="dash-sec-head"><span>&#9888; Needs Attention</span><span class="dash-badge dash-badge-crit">${problems.length}</span></div>` +
            problems.map(p => `<div class="dash-prob-item">
                <div class="dash-prob-dot dash-dot-${p.sev}"></div>
                <div class="dash-prob-info"><div class="dash-prob-name">${p.name}</div><div class="dash-prob-reason">${p.reason}</div></div>
                <span class="dash-pill dash-pill-${p.sev}">${p.sev === 'crit' ? 'Critical' : 'Warning'}</span>
                ${p.fn ? `<button class="dash-fix-btn" onclick="${p.fn}">${_e(p.action)}</button>` : ''}
            </div>`).join('');
    }

    // ── 5. CRASH / INSTABILITY ─────────────────────────────────────
    function renderCrashes() {
        const root = document.getElementById('dash-crashes');
        if (!root) return;
        const map = {};
        (dashboardState.audit || []).forEach(e => {
            const a = String(e?.action || '');
            if (!a.includes('deploy_failed') && !a.includes('crashed') && !a.includes('restart')) return;
            const id = e.blueprint_id || e.container_id || 'unknown';
            if (!map[id]) map[id] = { id, count: 0, last: e.created_at || '', action: a };
            map[id].count++;
            if ((e.created_at || '') > map[id].last) { map[id].last = e.created_at; map[id].action = a; }
        });
        const list = Object.values(map).sort((a, b) => b.count - a.count).slice(0, 3);
        if (!list.length) {
            root.innerHTML = `<div class="dash-sec-head"><span>&#128201; Crash History</span><span class="dash-badge dash-badge-ok">Stabil</span></div><div class="dash-empty-sm">Keine Crashes in dieser Session.</div>`;
            return;
        }
        root.innerHTML = `<div class="dash-sec-head"><span>&#128201; Crash History</span><span class="dash-badge">letzte 120</span></div>` +
            list.map(cr => {
                const stab = Math.max(5, 100 - Math.min(100, cr.count * 15));
                const sev = cr.count >= 5 ? 'crit' : 'warn';
                return `<div class="dash-crash-item">
                    <div class="dash-crash-icon dash-dot-${sev}">${_e(cr.id.slice(0,2).toUpperCase())}</div>
                    <div class="dash-crash-body">
                        <div class="dash-crash-name">${_e(cr.id)}</div>
                        <div class="dash-crash-meta">${_e(cr.last?.slice(11,16) || '—')} · ${_e(cr.action)}</div>
                        <div class="dash-stab-bar"><div class="dash-stab-fill" style="width:${stab}%"></div></div>
                    </div>
                    <div class="dash-crash-cnt-wrap"><div class="dash-crash-cnt dash-crash-${sev}">${cr.count}&times;</div><div class="dash-crash-lbl">Crashes</div></div>
                </div>`;
            }).join('');
    }

    // ── 2. TOP TALKERS ─────────────────────────────────────────────
    function renderTopTalkers() {
        const root = document.getElementById('dash-toptalkers');
        if (!root) return;
        const rows = (deps.getContainers() || []).map(c => {
            const s = dashboardState.containerStats[c.container_id] || {};
            return { name: c.name || c.blueprint_id || c.container_id?.slice(0,12),
                cpu: parseFloat(s.cpu_percent || 0),
                ram: parseFloat(s.memory_usage_mb || 0),
                net: parseInt(s.network_rx_bytes || 0) + parseInt(s.network_tx_bytes || 0) };
        }).filter(r => r.name);
        const byCpu = [...rows].sort((a,b) => b.cpu-a.cpu).slice(0,3);
        const byRam = [...rows].sort((a,b) => b.ram-a.ram).slice(0,3);
        const byNet = [...rows].sort((a,b) => b.net-a.net).slice(0,3);
        const maxCpu = Math.max(...byCpu.map(r=>r.cpu), 0.1);
        const maxRam = Math.max(...byRam.map(r=>r.ram), 1);
        const maxNet = Math.max(...byNet.map(r=>r.net), 1);
        const fmtNet = b => b>1048576 ? (b/1048576).toFixed(1)+'MB' : b>1024 ? (b/1024).toFixed(0)+'KB' : b+'B';
        const row = (name, pct, val, cls) =>
            `<div class="dash-talker-row"><span class="dash-talker-name">${_e(name)}</span><div class="dash-talker-bar"><div class="dash-talker-fill ${cls}" style="width:${Math.min(100,pct).toFixed(1)}%"></div></div><span class="dash-talker-val">${_e(val)}</span></div>`;
        const empty = '<div class="dash-empty-sm">Keine Live-Daten</div>';
        root.innerHTML = `<div class="dash-sec-head"><span>&#128200; Top-Talker</span></div>
            <div class="dash-tl-label dash-tl-cpu">CPU</div>
            ${byCpu.length ? byCpu.map(r=>row(r.name,(r.cpu/maxCpu)*100,r.cpu.toFixed(1)+'%','dash-tf-cpu')).join('') : empty}
            <div class="dash-tl-label dash-tl-ram">RAM</div>
            ${byRam.length ? byRam.map(r=>row(r.name,(r.ram/maxRam)*100,r.ram.toFixed(0)+'MB','dash-tf-ram')).join('') : empty}
            <div class="dash-tl-label dash-tl-net">Netzwerk</div>
            ${byNet.length ? byNet.map(r=>row(r.name,(r.net/maxNet)*100,fmtNet(r.net),'dash-tf-net')).join('') : empty}`;
    }

    // ── 3. QUOTA FORECAST ──────────────────────────────────────────
    function renderQuotaForecast() {
        const root = document.getElementById('dash-quota-forecast');
        if (!root) return;
        const q = dashboardState.quota || {};
        const gf = 1.4;
        const bars = [
            { name: 'Container', cur: q.containers_used||0, max: q.max_containers||3, proj: Math.min(q.max_containers||3, Math.round((q.containers_used||0)*gf)), fmt: v=>`${v}` },
            { name: 'CPU', cur: parseFloat(q.cpu_used||0), max: parseFloat(q.max_total_cpu||10), proj: Math.min(parseFloat(q.max_total_cpu||10), parseFloat(q.cpu_used||0)*gf), fmt: v=>v.toFixed(1) },
            { name: 'RAM', cur: parseFloat(q.memory_used_mb||0), max: parseFloat(q.max_total_memory_mb||27837), proj: Math.min(parseFloat(q.max_total_memory_mb||27837), parseFloat(q.memory_used_mb||0)*gf), fmt: v=>Math.round(v)+'MB' },
        ];
        root.innerHTML = `<div class="dash-sec-head"><span>&#128202; Quota-Forecast</span><span class="dash-badge">+7 Tage</span></div>` +
            bars.map(b => {
                const curPct = b.max>0 ? Math.min(100,(b.cur/b.max)*100) : 0;
                const projPct = b.max>0 ? Math.min(100,(b.proj/b.max)*100) : 0;
                const warn = b.proj >= b.max*0.8;
                const projColor = warn ? '#d29922' : '#3fb950';
                return `<div class="dash-fcast-row">
                    <div class="dash-fcast-labels"><span class="dash-fcast-name">${b.name}</span><span class="dash-fcast-val" style="color:${projColor}">${b.fmt(b.cur)} &rarr; ${b.fmt(b.proj)}</span></div>
                    <div class="dash-fcast-bar">
                        <div class="dash-fcast-cur" style="width:${curPct.toFixed(1)}%"></div>
                        <div class="dash-fcast-proj" style="left:${curPct.toFixed(1)}%;width:${Math.max(0,projPct-curPct).toFixed(1)}%;background:${projColor}"></div>
                        <div class="dash-fcast-marker" style="left:${projPct.toFixed(1)}%"></div>
                    </div>
                </div>`;
            }).join('') +
            `<div class="dash-fcast-legend"><span class="dash-fl"><span class="dash-fl-dot" style="background:#3fb950"></span>Aktuell</span><span class="dash-fl"><span class="dash-fl-dot" style="background:#d29922;opacity:.5"></span>Projektion</span></div>`;
    }

    // ── 4. RISK / APPROVAL ─────────────────────────────────────────
    function renderRisk() {
        const root = document.getElementById('dash-risk');
        if (!root) return;
        const containers = deps.getContainers() || [];
        const pending = deps.getPendingApprovals() || [];
        const risks = [];
        containers.forEach(c => {
            const name = _e(c.name || c.blueprint_id);
            if (c.network === 'full') risks.push({ lv: 'hi', text: `${name}: full network` });
            else if (c.image && !c.image_digest) risks.push({ lv: 'warn', text: `${name}: unpinned image` });
            else if (c.status === 'running') risks.push({ lv: 'ok', text: `${name}: stabil` });
        });
        const score = risks.some(r=>r.lv==='hi') ? 'hi' : risks.some(r=>r.lv==='warn') ? 'med' : 'low';
        const label = { hi:'Hohes Risiko', med:'Mittleres Risiko', low:'Niedriges Risiko' }[score];
        const color = { hi:'#f85149', med:'#d29922', low:'#3fb950' }[score];
        const arc = { hi:100, med:60, low:25 }[score];
        root.innerHTML = `<div class="dash-sec-head"><span>&#128737; Risk &amp; Approval</span></div>
            <div class="dash-risk-row">
                <svg width="48" height="48" viewBox="0 0 48 48" style="flex-shrink:0">
                    <circle cx="24" cy="24" r="19" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="5"/>
                    <circle cx="24" cy="24" r="19" fill="none" stroke="${color}" stroke-width="5"
                        stroke-dasharray="${arc} 120" stroke-dashoffset="30" transform="rotate(-90 24 24)"/>
                    <text x="24" y="28" text-anchor="middle" font-size="10" font-weight="600" fill="${color}">${score.toUpperCase()}</text>
                </svg>
                <div><div class="dash-risk-level" style="color:${color}">${label}</div>
                <div class="dash-risk-sub">${pending.length} Approvals · ${risks.filter(r=>r.lv!=='ok').length} Warnungen</div></div>
            </div>
            <div class="dash-risk-list">${risks.map(r=>`<div class="dash-risk-item"><span class="dash-rdot dash-rd-${r.lv}"></span>${r.text}</div>`).join('') || '<div class="dash-empty-sm">Keine Container</div>'}</div>
            ${pending.length ? `<div class="dash-risk-pending"><span>${pending.length} Approval wartet</span><button class="dash-rp-btn" onclick="document.querySelector('[data-tab=logs]')?.click()">Pr&#252;fen</button></div>` : ''}`;
    }

    // ── MAIN renderDashboard ───────────────────────────────────────
    function renderDashboard() {
        const kpiRoot = document.getElementById('dash-kpis');
        const freshnessRoot = document.getElementById('dash-freshness');
        const actionRoot = document.getElementById('dash-action-queue');
        const runtimeRoot = document.getElementById('dash-runtime-health');
        const timelineRoot = document.getElementById('dash-timeline');
        const recentBpRoot = document.getElementById('dash-recent-blueprints');
        const recentVolRoot = document.getElementById('dash-recent-volumes');
        if (!kpiRoot || !freshnessRoot || !actionRoot || !runtimeRoot) return;

        const q = dashboardState.quota || {};
        const containers = deps.getContainers() || [];
        const active = containers.filter(c=>c.status==='running').length;
        const pendingCount = Array.isArray(deps.getPendingApprovals()) ? deps.getPendingApprovals().length : 0;
        const errCount = (dashboardState.audit||[]).filter(e=>{ const a=String(e?.action||''); return a.includes('error')||a.includes('failed'); }).length;
        const cpuUsed = parseFloat(q.cpu_used||0);
        const ramUsed = parseFloat(q.memory_used_mb||0);
        const cpuMax = parseFloat(q.max_total_cpu||10);
        const ramMax = parseFloat(q.max_total_memory_mb||27837);
        const cpuPct = cpuMax>0 ? Math.min(100,(cpuUsed/cpuMax)*100) : 0;
        const ramPct = ramMax>0 ? Math.min(100,(ramUsed/ramMax)*100) : 0;
        const fillCls = pct => pct>80?'f-red':pct>50?'f-amber':'f-green';

        kpiRoot.innerHTML = `
            <article class="dash-kpi-card glass ${active>0?'ok':''}">
                <small>Active Containers</small>
                <strong>${active}</strong>
                <p>${q.containers_used||0}/${q.max_containers||0} quota used</p>
            </article>
            <article class="dash-kpi-card glass ${pendingCount>0?'warn':''}">
                <small>Open Approvals</small>
                <strong>${pendingCount}</strong>
                <p>${pendingCount?'Requires attention':'All clear'}</p>
            </article>
            <article class="dash-kpi-card glass">
                <small>Memory / CPU</small>
                <strong>${Math.round(ramUsed)}MB &middot; ${cpuUsed.toFixed(1)}</strong>
                <div class="dash-kpi-bars">
                    <div class="dash-kpi-bar"><div class="dash-kpi-fill ${fillCls(cpuPct)}" style="width:${cpuPct.toFixed(1)}%"></div></div>
                    <div class="dash-kpi-bar"><div class="dash-kpi-fill ${fillCls(ramPct)}" style="width:${ramPct.toFixed(1)}%"></div></div>
                </div>
            </article>
            <article class="dash-kpi-card glass ${errCount?'warn':''}">
                <small>Recent Errors</small>
                <strong>${errCount}</strong>
                <p>${errCount?'Investigate audit timeline':'No critical errors'}</p>
            </article>`;

        renderFreshness();
        renderActionQueue();
        renderRuntimeHealth();
        renderProblems();
        renderCrashes();
        renderTopTalkers();
        renderQuotaForecast();
        renderRisk();

        if (!timelineRoot || !recentBpRoot || !recentVolRoot) return;
        const timeline = getTodayTimelineItems();
        timelineRoot.innerHTML = timeline.length
            ? timeline.map(item => `
                <button class="dash-timeline-item" data-activity-id="${_e(String(item.id||item.created_at||''))}">
                    <span class="dot ${deps.toActivityLevel(item.action)}"></span>
                    <div><div class="title">${_e(item.action||'event')}</div>
                    <div class="meta">${_e(item.created_at||'')} &middot; ${_e(item.blueprint_id||'')}</div></div>
                </button>`).join('')
            : '<div class="term-activity-empty">No timeline entries for today.</div>';

        timelineRoot.querySelectorAll('.dash-timeline-item').forEach(btn => {
            btn.addEventListener('click', () => {
                const a = (dashboardState.audit||[]).find(i=>String(i.id||i.created_at)===btn.dataset.activityId);
                if (!a) return;
                deps.openActivityDetail({ created_at:a.created_at, event:a.action, message:a.details||'', blueprint_id:a.blueprint_id||'', container_id:a.container_id||'', level:deps.toActivityLevel(a.action) });
            });
        });

        recentBpRoot.innerHTML = getRecentItems('blueprints').length
            ? getRecentItems('blueprints').map(id=>`<button class="dash-chip" onclick="termDeployBp('${_e(id)}')">${_e(id)}</button>`).join('')
            : '<div class="term-history-empty">No recent blueprint yet.</div>';
        recentVolRoot.innerHTML = getRecentItems('volumes').length
            ? getRecentItems('volumes').map(n=>`<button class="dash-chip" onclick="termSnapshotVolume('${_e(n)}')">${_e(n)}</button>`).join('')
            : '<div class="term-history-empty">No recent volume yet.</div>';
    }

    return { loadDashboard, rememberRecent, renderDashboard };
}

export { createDashboardController };
