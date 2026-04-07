function createApprovalController(deps) {
    let pendingApprovals = [];
    let approvalHistory = [];
    let approvalCenterOpen = false;
    let approvalCenterTab = 'pending';
    let approvalBannerTimer = null;
    let approvalSelection = new Set();
    let lastApprovalBannerSeverity = -1;
    let lastApprovalBannerId = '';
    let currentApprovalId = null;
    let approvalPollTimer = null;

    function showApprovalBanner(approvalId, reason, blueprintId, ttlSeconds = 300) {
        if (approvalBannerTimer) {
            clearInterval(approvalBannerTimer);
            approvalBannerTimer = null;
        }
        currentApprovalId = approvalId;
        const banner = document.getElementById('approval-banner');
        if (!banner) return;

        document.getElementById('approval-reason').textContent = reason;
        document.getElementById('approval-bp-id').textContent = blueprintId ? `(${blueprintId})` : '';
        banner.style.display = 'flex';

        let ttl = Number.isFinite(ttlSeconds) ? ttlSeconds : 300;
        const ttlEl = document.getElementById('approval-ttl');
        if (ttlEl) ttlEl.textContent = `${ttl}s`;
        approvalBannerTimer = setInterval(() => {
            ttl--;
            if (ttlEl) ttlEl.textContent = `${ttl}s`;
            if (ttl <= 0) {
                clearInterval(approvalBannerTimer);
                approvalBannerTimer = null;
                hideApprovalBanner();
                deps.logOutput('⏰ Approval expired', 'ansi-yellow');
            }
        }, 1000);
    }

    function hideApprovalBanner() {
        const banner = document.getElementById('approval-banner');
        if (banner) banner.style.display = 'none';
        if (approvalBannerTimer) {
            clearInterval(approvalBannerTimer);
            approvalBannerTimer = null;
        }
        currentApprovalId = null;
    }

    function updateApprovalBadge() {
        const badge = document.getElementById('approval-center-count');
        if (badge) badge.textContent = String(Array.isArray(pendingApprovals) ? pendingApprovals.length : 0);
    }

    function setApprovalCenterTab(tab) {
        approvalCenterTab = tab === 'history' ? 'history' : 'pending';
        document.querySelectorAll('.approval-center-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.approvalTab === approvalCenterTab);
        });
        const pendingEl = document.getElementById('approval-center-pending');
        const historyEl = document.getElementById('approval-center-history');
        if (pendingEl) pendingEl.style.display = approvalCenterTab === 'pending' ? 'block' : 'none';
        if (historyEl) historyEl.style.display = approvalCenterTab === 'history' ? 'block' : 'none';
    }

    function toggleApprovalCenter(force = null) {
        const root = document.getElementById('approval-center');
        if (!root) return;
        approvalCenterOpen = force === null ? !approvalCenterOpen : Boolean(force);
        root.classList.toggle('visible', approvalCenterOpen);
    }

    function approvalReason(item) {
        return String(item?.approval_reason || item?.reason || '').trim();
    }

    function approvalList(values) {
        return Array.isArray(values)
            ? values.map(value => String(value || '').trim()).filter(Boolean)
            : [];
    }

    function approvalRuntimeFacts(item) {
        const facts = [];
        const networkMode = String(item?.network_mode || '').trim();
        if (networkMode) facts.push(`network: ${networkMode}`);
        const storageScope = String(item?.storage_scope_override || item?.storage_scope || '').trim();
        if (storageScope) facts.push(`storage_scope: ${storageScope}`);
        const mountOverrides = Array.isArray(item?.mount_overrides) ? item.mount_overrides : [];
        const assetIds = mountOverrides
            .map(entry => String(entry?.asset_id || '').trim())
            .filter(Boolean);
        if (assetIds.length) facts.push(`storage_assets: ${assetIds.join(', ')}`);
        else if (mountOverrides.length) facts.push(`mount_overrides: ${mountOverrides.length}`);
        const capAdd = approvalList(item?.requested_cap_add);
        if (capAdd.length) facts.push(`cap_add: ${capAdd.join(', ')}`);
        const securityOpt = approvalList(item?.requested_security_opt);
        if (securityOpt.length) facts.push(`security_opt: ${securityOpt.join(', ')}`);
        const capDrop = approvalList(item?.requested_cap_drop);
        if (capDrop.length) facts.push(`cap_drop: ${capDrop.join(', ')}`);
        if (item?.read_only_rootfs === true) facts.push('rootfs: read-only');
        return facts;
    }

    function renderApprovalRiskFlags(item) {
        const flags = approvalList(item?.risk_flags);
        if (!flags.length) return '';
        return `
            <div class="approval-risk-flags">
                ${flags.map(flag => `<span class="approval-status">${deps.esc(flag)}</span>`).join('')}
            </div>
        `;
    }

    function renderApprovalRiskReasons(item) {
        const reasons = approvalList(item?.risk_reasons);
        if (!reasons.length) return '';
        return `
            <div class="approval-risk-reasons">
                ${reasons.map(reason => `<div class="approval-row-meta">${deps.esc(reason)}</div>`).join('')}
            </div>
        `;
    }

    function renderApprovalRuntimeFacts(item) {
        const facts = approvalRuntimeFacts(item);
        if (!facts.length) return '';
        return `
            <div class="approval-runtime-facts">
                ${facts.map(fact => `<div class="approval-row-meta">${deps.esc(fact)}</div>`).join('')}
            </div>
        `;
    }

    function approvalRisk(item) {
        const flags = approvalList(item?.risk_flags).map(flag => flag.toLowerCase());
        const networkMode = String(item?.network_mode || '').toLowerCase();
        if (flags.some(flag => flag.includes('security_opt') || flag.includes('dangerous_cap') || flag.includes('network_full'))) return 3;
        if (flags.some(flag => flag.includes('network_bridge')) || networkMode === 'bridge') return 2;
        const reason = approvalReason(item).toLowerCase();
        if (reason.includes('full') || reason.includes('internet') || reason.includes('trust')) return 3;
        if (reason.includes('bridge')) return 2;
        return 1;
    }

    function approvalRecommendation(item) {
        const risk = approvalRisk(item);
        if (risk >= 3) return 'Review carefully: high network/trust risk.';
        if (risk === 2) return 'Approve only if host-network access is required.';
        return 'Low risk request, usually safe.';
    }

    function renderApprovalContextCard() {
        const host = document.getElementById('approval-center-context');
        if (!host) return;
        const top = (pendingApprovals || [])[0];
        if (!top) {
            host.innerHTML = '<div class="approval-empty">No pending approval context.</div>';
            return;
        }
        host.innerHTML = `
            <div class="approval-context-card">
                <div class="approval-context-top">
                    <strong>${deps.esc(top.blueprint_id || 'unknown')}</strong>
                    <span class="approval-risk r${approvalRisk(top)}">Risk ${approvalRisk(top)}</span>
                </div>
                <p>${deps.esc(approvalReason(top))}</p>
                ${renderApprovalRiskFlags(top)}
                ${renderApprovalRiskReasons(top)}
                ${renderApprovalRuntimeFacts(top)}
                <small>${deps.esc(approvalRecommendation(top))}</small>
            </div>
        `;
    }

    function renderApprovalRows(items, historyMode = false) {
        if (!Array.isArray(items) || !items.length) {
            return `<div class="approval-empty">${historyMode ? 'No history yet.' : 'No pending approvals.'}</div>`;
        }
        return items.map(item => {
            const status = String(item?.status || 'pending');
            const ttl = Math.max(0, Number.parseInt(String(item?.ttl_remaining || 0), 10));
            const meta = historyMode
                ? `${deps.esc(status)} · by ${deps.esc(item?.resolved_by || 'n/a')}`
                : `ttl ${ttl}s`;
            const actions = historyMode
                ? ''
                : `
                    <div class="approval-row-actions">
                        <label class="approval-check-wrap"><input type="checkbox" class="approval-select" data-approval-id="${deps.esc(item?.id || '')}" ${approvalSelection.has(String(item?.id || '')) ? 'checked' : ''}/> batch</label>
                        <button class="term-btn-sm danger" onclick="termRejectRequest('${deps.esc(item?.id || '')}')">Reject</button>
                        <button class="term-btn-sm bp-deploy" onclick="termApproveRequest('${deps.esc(item?.id || '')}')">Approve</button>
                    </div>
                `;
            return `
                <div class="approval-row">
                    <div class="approval-row-main">
                        <div class="approval-row-title">${deps.esc(item?.blueprint_id || 'unknown')} <span class="approval-status">${deps.esc(status)}</span></div>
                        <div class="approval-row-reason">${deps.esc(approvalReason(item))}</div>
                        ${renderApprovalRiskFlags(item)}
                        ${renderApprovalRiskReasons(item)}
                        ${renderApprovalRuntimeFacts(item)}
                        <div class="approval-row-meta">${meta}</div>
                    </div>
                    ${actions}
                </div>
            `;
        }).join('');
    }

    function renderApprovalCenter() {
        const pendingEl = document.getElementById('approval-center-pending');
        const historyEl = document.getElementById('approval-center-history');
        if (pendingEl) {
            pendingEl.innerHTML = `
                <div class="approval-batch-actions">
                    <button class="term-btn-sm" id="approval-batch-approve">Approve Selected</button>
                    <button class="term-btn-sm danger" id="approval-batch-reject">Reject Selected</button>
                </div>
                ${renderApprovalRows(pendingApprovals, false)}
            `;
        }
        if (historyEl) historyEl.innerHTML = renderApprovalRows(approvalHistory, true);
        setApprovalCenterTab(approvalCenterTab);
        renderApprovalContextCard();
        pendingEl?.querySelectorAll('.approval-select').forEach(input => {
            input.addEventListener('change', (event) => {
                const approvalId = String(event.target?.dataset?.approvalId || '');
                if (!approvalId) return;
                if (event.target.checked) approvalSelection.add(approvalId);
                else approvalSelection.delete(approvalId);
            });
        });
        document.getElementById('approval-batch-approve')?.addEventListener('click', async () => {
            const ids = Array.from(approvalSelection);
            for (const id of ids) await resolveApprovalRequest(id, 'approve');
            approvalSelection.clear();
        });
        document.getElementById('approval-batch-reject')?.addEventListener('click', async () => {
            const ids = Array.from(approvalSelection);
            for (const id of ids) await resolveApprovalRequest(id, 'reject', 'Batch rejected');
            approvalSelection.clear();
        });
    }

    async function resolveApprovalRequest(approvalId, action, reason = '') {
        if (!approvalId) return;
        try {
            if (action === 'approve') {
                const data = await deps.apiRequest(`/approvals/${approvalId}/approve`, { method: 'POST' }, 'Approve failed');
                if (data.approved) {
                    deps.showToast(`Approved ${approvalId}`, 'success');
                    deps.logOutput('✅ Approved — container starting...', 'ansi-green');
                    await deps.loadContainers();
                } else {
                    deps.showToast(data.error || 'Approve failed', 'error');
                    deps.logOutput(`❌ Approve failed: ${data.error || 'Unknown'}`, 'ansi-red');
                }
            } else {
                await deps.apiRequest(`/approvals/${approvalId}/reject`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: reason || 'User rejected' }),
                }, 'Reject failed');
                deps.showToast(`Rejected ${approvalId}`, 'warn');
                deps.logOutput('✖ Rejected', 'ansi-yellow');
            }
        } catch (error) {
            deps.showToast(error.message || `${action} failed`, 'error');
            deps.logOutput(`❌ ${action} error: ${error.message}`, 'ansi-red');
        }
        if (currentApprovalId === approvalId) hideApprovalBanner();
        await refreshApprovalCenter();
        if (deps.getActiveTab() === 'dashboard') await deps.loadDashboard();
    }

    async function approveRequest() {
        if (!currentApprovalId) return;
        await resolveApprovalRequest(currentApprovalId, 'approve');
    }

    async function rejectRequest() {
        if (!currentApprovalId) return;
        await resolveApprovalRequest(currentApprovalId, 'reject', 'User rejected');
    }

    async function refreshApprovalCenter() {
        try {
            const [pendingData, historyData] = await Promise.all([
                deps.apiRequest('/approvals', {}, 'Could not load approvals'),
                deps.apiRequest('/approvals/history', {}, 'Could not load approval history'),
            ]);
            setPendingApprovals((pendingData?.approvals || []).sort((a, b) => {
                const riskDiff = approvalRisk(b) - approvalRisk(a);
                if (riskDiff !== 0) return riskDiff;
                return Number(a?.ttl_remaining || 0) - Number(b?.ttl_remaining || 0);
            }));
            const validIds = new Set(pendingApprovals.map(item => String(item?.id || '')));
            approvalSelection = new Set(Array.from(approvalSelection).filter(id => validIds.has(id)));
            approvalHistory = historyData?.history || [];
            updateApprovalBadge();
            renderApprovalCenter();
            if (deps.getActiveTab() === 'dashboard') deps.renderDashboard();

            if (pendingApprovals.length > 0) {
                const top = pendingApprovals[0];
                const severity = approvalRisk(top);
                const isNew = !currentApprovalId || currentApprovalId !== top.id;
                const isEscalated = severity > lastApprovalBannerSeverity;
                if (isNew || isEscalated) {
                    showApprovalBanner(top.id, approvalReason(top), top.blueprint_id, top.ttl_remaining || 300);
                    lastApprovalBannerSeverity = severity;
                    lastApprovalBannerId = String(top.id || '');
                } else {
                    const ttlEl = document.getElementById('approval-ttl');
                    if (ttlEl) ttlEl.textContent = `${Math.max(0, Number.parseInt(String(top.ttl_remaining || 0), 10))}s`;
                }
            } else {
                hideApprovalBanner();
                lastApprovalBannerSeverity = -1;
                lastApprovalBannerId = '';
            }
        } catch (_) {
            // silent in poll
        }
    }

    async function pollApprovals() {
        try {
            await refreshApprovalCenter();
        } catch (_) {
            // silent
        }
        approvalPollTimer = window.setTimeout(pollApprovals, 5000);
    }

    function ensurePolling() {
        if (!approvalPollTimer) pollApprovals();
    }

    function registerWindowHandlers() {
        window.termOpenApprovalCenter = async function() {
            toggleApprovalCenter(true);
            await refreshApprovalCenter();
        };

        window.termApproveRequest = async function(approvalId) {
            await resolveApprovalRequest(approvalId, 'approve');
        };

        window.termRejectRequest = async function(approvalId) {
            await resolveApprovalRequest(approvalId, 'reject', 'Rejected from approval center');
        };
    }

    function setPendingApprovals(next) {
        pendingApprovals = Array.isArray(next) ? next : [];
        updateApprovalBadge();
    }

    function getPendingApprovals() {
        return pendingApprovals;
    }

    return {
        approveRequest,
        ensurePolling,
        getPendingApprovals,
        hideApprovalBanner,
        pollApprovals,
        refreshApprovalCenter,
        registerWindowHandlers,
        rejectRequest,
        renderApprovalCenter,
        setApprovalCenterTab,
        setPendingApprovals,
        showApprovalBanner,
        toggleApprovalCenter,
    };
}

export { createApprovalController };
