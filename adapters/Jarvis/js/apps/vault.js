/**
 * vault.js — TRION Vault
 * KeePassXC-style password manager, AES-256 encrypted via admin-api
 */

function getApiBase() {
    if (typeof window.getApiBase === 'function' && window.getApiBase !== getApiBase)
        return window.getApiBase();
    return `${window.location.protocol}//${window.location.hostname}:8200`;
}

function esc(v) {
    const d = document.createElement('div');
    d.textContent = v == null ? '' : String(v);
    return d.innerHTML;
}

const VAULT_CATEGORIES = [
    { id: 'all',      icon: '🗂',  label: 'Alle Einträge' },
    { id: 'fav',      icon: '⭐',  label: 'Favoriten' },
    { id: 'internet', icon: '🌐',  label: 'Internet' },
    { id: 'api',      icon: '🔑',  label: 'API Keys' },
    { id: 'server',   icon: '💻',  label: 'Server' },
    { id: 'trion',    icon: '🤖',  label: 'TRION intern' },
];

let vaultState = {
    locked: true,
    entries: [],
    selectedId: null,
    activeCategory: 'all',
    search: '',
    masterToken: null,
};

let vaultRoot = null;

export function initVaultApp(container) {
    vaultRoot = container;
    initVaultWithStatus();
}

async function initVaultWithStatus() {
    if (!vaultRoot) return;
    // Show loading briefly
    vaultRoot.innerHTML = '<div class="vault-loading">🔐 TRION Vault wird geladen...</div>';
    try {
        const res = await fetch(`${getApiBase()}/api/vault/status`);
        const data = await res.json();
        if (!data.has_master) {
            renderSetupScreen();
        } else {
            renderLockScreen();
        }
    } catch (_) {
        renderLockScreen();
    }
}

function renderVault() {
    if (!vaultRoot) return;
    if (vaultState.locked) {
        renderLockScreen();
    } else {
        renderVaultApp();
    }
}

function renderSetupScreen() {
    vaultRoot.innerHTML = `
        <div class="vault-lock-screen">
            <div class="vault-lock-icon">🔐</div>
            <div class="vault-lock-title">Vault einrichten</div>
            <div class="vault-lock-sub">Willkommen! Lege jetzt dein Master-Passwort fest.</div>
            <div class="vault-setup-info">
                <span class="vault-setup-warn">⚠</span>
                Das Master-Passwort kann <strong>nicht wiederhergestellt</strong> werden.<br>
                Verlierst du es, sind alle gespeicherten Daten unwiderruflich verloren.
            </div>
            <div class="vault-lock-form">
                <input class="vault-lock-input" type="password" id="vault-setup-pw1"
                    placeholder="Master-Passwort wählen" autocomplete="new-password" />
                <input class="vault-lock-input" type="password" id="vault-setup-pw2"
                    placeholder="Passwort bestätigen" autocomplete="new-password" />
                <div class="vault-pw-strength" id="vault-setup-strength" style="padding:0 2px"></div>
                <button class="vault-lock-btn" id="vault-setup-btn">🔐 Vault erstellen</button>
                <div class="vault-lock-hint">Mindestens 8 Zeichen · Groß- und Kleinbuchstaben empfohlen</div>
            </div>
        </div>`;

    const pw1 = vaultRoot.querySelector('#vault-setup-pw1');
    const pw2 = vaultRoot.querySelector('#vault-setup-pw2');
    const btn = vaultRoot.querySelector('#vault-setup-btn');
    const strengthEl = vaultRoot.querySelector('#vault-setup-strength');

    pw1.addEventListener('input', () => {
        const s = _pwStrengthText(pw1.value);
        strengthEl.innerHTML = pw1.value
            ? `<div class="vault-pw-bar">${[1,2,3,4,5].map(i =>
                `<div class="vault-pw-seg ${i<=s.score ? (s.score>=4?'vault-seg-strong':s.score>=3?'vault-seg-med':'vault-seg-weak') : 'vault-seg-empty'}"></div>`
              ).join('')}</div><div class="vault-pw-label ${s.cls}">${s.label}</div>`
            : '';
    });

    btn.addEventListener('click', () => attemptSetup(pw1.value, pw2.value));
    [pw1, pw2].forEach(el => el.addEventListener('keydown', e => {
        if (e.key === 'Enter') attemptSetup(pw1.value, pw2.value);
    }));
    setTimeout(() => pw1.focus(), 100);
}

function _pwStrengthText(pw) {
    if (!pw) return { score: 0, label: '', cls: '' };
    let s = 0;
    if (pw.length >= 8)  s++;
    if (pw.length >= 12) s++;
    if (/[A-Z]/.test(pw)) s++;
    if (/[0-9]/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw)) s++;
    const labels = ['Sehr schwach','Schwach','Mittel','Stark','Sehr stark'];
    const cls = ['','','vault-pw-med','vault-pw-strong','vault-pw-strong'];
    return { score: s, label: labels[s]||labels[0], cls: cls[s]||'' };
}

async function attemptSetup(pw1, pw2) {
    if (!pw1 || pw1.length < 8) {
        _lockError('vault-setup-pw1', 'Mindestens 8 Zeichen erforderlich');
        return;
    }
    if (pw1 !== pw2) {
        _lockError('vault-setup-pw2', 'Passwörter stimmen nicht überein');
        return;
    }
    try {
        const res = await fetch(`${getApiBase()}/api/vault/setup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ master_password: pw1 }),
        });
        if (!res.ok) throw new Error('Setup fehlgeschlagen');
        const data = await res.json();
        vaultState.masterToken = data.session_token;
        vaultState.locked = false;
        await loadEntries();
        renderVaultApp();
        startInactivityTimer();
    } catch (err) {
        _lockError('vault-setup-btn', err.message || 'Fehler beim Einrichten');
    }
}

function renderLockScreen() {
    vaultRoot.innerHTML = `
        <div class="vault-lock-screen">
            <div class="vault-lock-icon">🔐</div>
            <div class="vault-lock-title">TRION Vault</div>
            <div class="vault-lock-sub">Gib dein Master-Passwort ein um fortzufahren</div>
            <div class="vault-lock-form">
                <input class="vault-lock-input" type="password" id="vault-master-pw"
                    placeholder="Master-Passwort" autocomplete="off" />
                <button class="vault-lock-btn" id="vault-unlock-btn">🔓 Tresor öffnen</button>
                <div class="vault-lock-hint">Schließt sich nach 5 min Inaktivität automatisch</div>
            </div>
        </div>`;
    const input = vaultRoot.querySelector('#vault-master-pw');
    const btn   = vaultRoot.querySelector('#vault-unlock-btn');
    btn.addEventListener('click', () => attemptUnlock(input.value));
    input.addEventListener('keydown', e => { if (e.key === 'Enter') attemptUnlock(input.value); });
    setTimeout(() => input.focus(), 100);
}

function _lockError(elId, msg) {
    const el = vaultRoot.querySelector('#' + elId);
    if (!el) return;
    const orig = el.value !== undefined ? el.value : el.textContent;
    if (el.value !== undefined) {
        el.style.borderColor = 'rgba(248,81,73,0.6)';
        el.value = '';
        el.placeholder = msg;
        setTimeout(() => { el.style.borderColor=''; el.placeholder = orig || ''; }, 2500);
    }
}

async function attemptUnlock(pw) {
    if (!pw) return;
    try {
        // Validate against admin-api — if it responds, the token works
        const res = await fetch(`${getApiBase()}/api/vault/unlock`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ master_password: pw }),
        });
        if (!res.ok) throw new Error('Falsches Passwort');
        const data = await res.json();
        vaultState.masterToken = data.session_token || pw;
        vaultState.locked = false;
        await loadEntries();
        renderVaultApp();
        startInactivityTimer();
    } catch (err) {
        const input = vaultRoot.querySelector('#vault-master-pw');
        if (input) {
            input.style.borderColor = 'rgba(248,81,73,0.6)';
            input.value = '';
            input.placeholder = 'Falsches Passwort — nochmal versuchen';
            setTimeout(() => {
                input.style.borderColor = '';
                input.placeholder = 'Master-Passwort';
            }, 2000);
        }
    }
}

async function loadEntries() {
    try {
        const res = await fetch(`${getApiBase()}/api/vault/entries`, {
            headers: { 'X-Vault-Token': vaultState.masterToken || '' },
        });
        if (!res.ok) return;
        const data = await res.json();
        vaultState.entries = data.entries || [];
    } catch (_) {
        vaultState.entries = [];
    }
}

let inactivityTimer = null;
function startInactivityTimer() {
    clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(() => lockVault(), 5 * 60 * 1000);
    document.addEventListener('mousemove', resetTimer, { passive: true });
    document.addEventListener('keydown', resetTimer, { passive: true });
}
function resetTimer() {
    clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(() => lockVault(), 5 * 60 * 1000);
}
function lockVault() {
    vaultState.locked = true;
    vaultState.masterToken = null;
    vaultState.entries = [];
    vaultState.selectedId = null;
    clearTimeout(inactivityTimer);
    renderVault();
}

function filteredEntries() {
    let list = vaultState.entries;
    if (vaultState.activeCategory === 'fav')  list = list.filter(e => e.favorite);
    else if (vaultState.activeCategory !== 'all') list = list.filter(e => e.category === vaultState.activeCategory);
    if (vaultState.search) {
        const q = vaultState.search.toLowerCase();
        list = list.filter(e =>
            (e.title||'').toLowerCase().includes(q) ||
            (e.username||'').toLowerCase().includes(q) ||
            (e.url||'').toLowerCase().includes(q) ||
            (e.tags||[]).some(t => t.toLowerCase().includes(q))
        );
    }
    return list;
}

function countForCategory(id) {
    const e = vaultState.entries;
    if (id === 'all') return e.length;
    if (id === 'fav') return e.filter(x => x.favorite).length;
    return e.filter(x => x.category === id).length;
}

function renderVaultApp() {
    const entries  = filteredEntries();
    const selected = vaultState.entries.find(e => e.id === vaultState.selectedId) || entries[0] || null;
    if (selected && !vaultState.selectedId) vaultState.selectedId = selected?.id;

    const sidebarHtml = VAULT_CATEGORIES.map(c => `
        <div class="vault-cat-item ${vaultState.activeCategory === c.id ? 'active' : ''}" data-cat="${c.id}">
            <span class="vault-cat-icon">${c.icon}</span>
            <span>${esc(c.label)}</span>
            <span class="vault-cat-count">${countForCategory(c.id)}</span>
        </div>`).join('') +
        `<div class="vault-cat-divider"></div>
        <div class="vault-cat-item vault-cat-special" data-cat="expired">
            <span class="vault-cat-icon">⏰</span><span>Abgelaufen</span>
            <span class="vault-cat-count">${vaultState.entries.filter(e=>e.expires && new Date(e.expires)<new Date()).length}</span>
        </div>`;

    const listHtml = entries.map(e => `
        <div class="vault-entry ${e.id === vaultState.selectedId ? 'active' : ''}" data-id="${esc(e.id)}">
            <div class="ve-title"><span class="ve-icon">${esc(e.icon||'🔑')}</span><span class="ve-name">${esc(e.title)}</span></div>
            <div class="ve-user">${esc(e.username||'—')}</div>
            <div class="ve-url">${esc(e.url ? new URL(e.url).hostname : '—')}</div>
        </div>`).join('') || '<div class="vault-list-empty">Keine Einträge</div>';

    vaultRoot.innerHTML = `
        <div class="vault-app-wrap">
            <div class="vault-app-hdr">
                <div class="vault-app-title">🔓 TRION Vault</div>
                <div class="vault-app-hdr-sub">AES-256-GCM · ${vaultState.entries.length} Einträge</div>
                <div class="vault-app-hdr-right">
                    <button class="vault-hdr-btn vault-hdr-btn-primary" id="vault-new-btn">+ Neuer Eintrag</button>
                    <button class="vault-hdr-btn vault-hdr-btn-lock" id="vault-lock-btn">🔒 Sperren</button>
                </div>
            </div>
            <div class="vault-toolbar">
                <input class="vault-search" id="vault-search" placeholder="Suchen… Titel, Benutzername, URL, Tags"
                    value="${esc(vaultState.search)}" />
            </div>
            <div class="vault-body">
                <div class="vault-sidebar">${sidebarHtml}</div>
                <div class="vault-list">
                    <div class="vault-list-hdr">
                        <div>Titel</div><div>Benutzername</div><div>URL</div>
                    </div>
                    <div class="vault-entries" id="vault-entries">${listHtml}</div>
                </div>
                <div class="vault-detail" id="vault-detail">
                    ${selected ? renderDetail(selected) : '<div class="vault-detail-empty">Eintrag wählen</div>'}
                </div>
            </div>
        </div>`;

    bindVaultEvents();
}

function pwStrength(pw) {
    if (!pw) return { score: 0, label: '—', cls: '' };
    let s = 0;
    if (pw.length >= 8)  s++;
    if (pw.length >= 12) s++;
    if (/[A-Z]/.test(pw)) s++;
    if (/[0-9]/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw)) s++;
    const labels = ['Sehr schwach','Schwach','Mittel','Stark','Sehr stark'];
    const cls    = ['','','vault-pw-med','vault-pw-strong','vault-pw-strong'];
    return { score: s, label: labels[s]||labels[0], cls: cls[s]||'' };
}

function renderDetail(e) {
    const str = pwStrength(e._plainPassword || '');
    const segs = [1,2,3,4,5].map(i =>
        `<div class="vault-pw-seg ${i <= str.score ? (str.score >= 4 ? 'vault-seg-strong' : str.score >= 3 ? 'vault-seg-med' : 'vault-seg-weak') : 'vault-seg-empty'}"></div>`
    ).join('');
    return `
        <div class="vault-detail-hdr">
            <div class="vault-det-icon-row">
                <div class="vault-det-big-icon">${esc(e.icon||'🔑')}</div>
                <div>
                    <div class="vault-det-title">${esc(e.title)}</div>
                    <div class="vault-det-path">${esc(e.category||'Alle Einträge')} / ${esc(e.title)}</div>
                </div>
            </div>
            ${e.totp_secret ? `<div class="vault-totp">
                <div><div class="vault-totp-label">2FA Code</div>
                <div class="vault-totp-code" id="vault-totp-code">••• •••</div></div>
                <div style="flex:1"><div class="vault-totp-bar"><div class="vault-totp-fill" id="vault-totp-fill"></div></div>
                <div class="vault-totp-timer" id="vault-totp-timer">—</div></div>
            </div>` : ''}
        </div>
        <div class="vault-det-tabs">
            <button class="vault-det-tab active">Allgemein</button>
            <button class="vault-det-tab">Erweitert</button>
        </div>
        <div class="vault-det-fields">
            <div class="vault-det-field">
                <div class="vault-det-label">Benutzername</div>
                <div class="vault-det-val">${esc(e.username||'—')}
                    <button class="vault-copy-btn" data-copy="${esc(e.username||'')}">📋</button></div>
            </div>
            <div class="vault-det-field">
                <div class="vault-det-label">Passwort</div>
                <div class="vault-det-val vault-det-pw" id="vault-pw-val">
                    <span id="vault-pw-text">••••••••••</span>
                    <button class="vault-show-btn" id="vault-pw-show" data-visible="0">👁</button>
                    <button class="vault-copy-btn" data-copy="${esc(e._plainPassword||'')}">📋</button>
                </div>
                <div class="vault-pw-strength">
                    <div class="vault-pw-bar">${segs}</div>
                    <div class="vault-pw-label ${str.cls}">${str.label}</div>
                </div>
            </div>
            <div class="vault-det-field">
                <div class="vault-det-label">URL</div>
                <div class="vault-det-val vault-det-url">${esc(e.url||'—')}
                    <button class="vault-copy-btn" data-copy="${esc(e.url||'')}">📋</button></div>
            </div>
            <div class="vault-det-field">
                <div class="vault-det-label">Ablauf</div>
                <div class="vault-det-val">${esc(e.expires||'Niemals')}</div>
            </div>
            ${e.tags?.length ? `<div class="vault-det-field">
                <div class="vault-det-label">Tags</div>
                <div class="vault-det-tags">${e.tags.map(t=>`<span class="vault-tag">${esc(t)}</span>`).join('')}</div>
            </div>` : ''}
            ${e.notes ? `<div class="vault-det-field">
                <div class="vault-det-label">Notizen</div>
                <div class="vault-det-notes">${esc(e.notes)}</div>
            </div>` : ''}
        </div>
        <div class="vault-det-actions">
            <button class="vault-det-btn" id="vault-edit-btn" data-id="${esc(e.id)}">✏ Bearbeiten</button>
            <button class="vault-det-btn" data-copy="${esc(e.username||'')}">📋 Username</button>
            <button class="vault-det-btn vault-det-btn-fav" data-id="${esc(e.id)}">${e.favorite?'★':'☆'} Favorit</button>
            <button class="vault-det-btn vault-det-btn-del" data-id="${esc(e.id)}">🗑 Löschen</button>
        </div>`;
}

function bindVaultEvents() {
    vaultRoot.querySelector('#vault-lock-btn')?.addEventListener('click', lockVault);
    vaultRoot.querySelector('#vault-new-btn')?.addEventListener('click', () => openEntryEditor(null));
    vaultRoot.querySelector('#vault-search')?.addEventListener('input', e => {
        vaultState.search = e.target.value;
        renderVaultApp();
    });
    vaultRoot.querySelectorAll('.vault-cat-item').forEach(el => {
        el.addEventListener('click', () => {
            vaultState.activeCategory = el.dataset.cat || 'all';
            renderVaultApp();
        });
    });
    vaultRoot.querySelectorAll('.vault-entry').forEach(el => {
        el.addEventListener('click', () => {
            vaultState.selectedId = el.dataset.id;
            renderVaultApp();
        });
    });
    vaultRoot.querySelectorAll('.vault-copy-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            navigator.clipboard.writeText(btn.dataset.copy || '').catch(() => {});
            btn.textContent = '✓';
            setTimeout(() => btn.textContent = '📋', 1200);
        });
    });
    const pwShow = vaultRoot.querySelector('#vault-pw-show');
    if (pwShow) {
        pwShow.addEventListener('click', async () => {
            const visible = pwShow.dataset.visible === '1';
            if (!visible) {
                const entry = vaultState.entries.find(e => e.id === vaultState.selectedId);
                if (entry && !entry._plainPassword) {
                    try {
                        const res = await fetch(`${getApiBase()}/api/vault/entries/${entry.id}/password`, {
                            headers: { 'X-Vault-Token': vaultState.masterToken || '' },
                        });
                        if (res.ok) {
                            const d = await res.json();
                            entry._plainPassword = d.password || '';
                        }
                    } catch (_) {}
                }
                const pw = entry?._plainPassword || '';
                const el = vaultRoot.querySelector('#vault-pw-text');
                if (el) el.textContent = pw || '(leer)';
                pwShow.dataset.visible = '1';
                pwShow.textContent = '🙈';
            } else {
                const el = vaultRoot.querySelector('#vault-pw-text');
                if (el) el.textContent = '••••••••••';
                pwShow.dataset.visible = '0';
                pwShow.textContent = '👁';
            }
        });
    }
    vaultRoot.querySelectorAll('.vault-det-btn-del').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Eintrag wirklich löschen?')) return;
            await fetch(`${getApiBase()}/api/vault/entries/${btn.dataset.id}`, {
                method: 'DELETE',
                headers: { 'X-Vault-Token': vaultState.masterToken || '' },
            }).catch(() => {});
            vaultState.entries = vaultState.entries.filter(e => e.id !== btn.dataset.id);
            vaultState.selectedId = null;
            renderVaultApp();
        });
    });
}

function openEntryEditor(entry) {
    const isNew = !entry;
    const e = entry || { id: '', title: '', username: '', password: '', url: '', category: 'internet', tags: [], notes: '', icon: '🔑' };
    vaultRoot.innerHTML = `
        <div class="vault-editor-wrap">
            <div class="vault-editor-hdr">
                <div class="vault-editor-title">${isNew ? '+ Neuer Eintrag' : '✏ Bearbeiten'}</div>
            </div>
            <div class="vault-editor-body">
                <div class="vault-ed-row vault-ed-row-2">
                    <div class="vault-ed-field"><div class="vault-ed-label">Titel</div>
                        <input class="vault-ed-input" id="ved-title" value="${esc(e.title)}" placeholder="z.B. Apple" /></div>
                    <div class="vault-ed-field"><div class="vault-ed-label">Kategorie</div>
                        <select class="vault-ed-select" id="ved-cat">
                            ${VAULT_CATEGORIES.filter(c=>c.id!=='all'&&c.id!=='fav').map(c =>
                                `<option value="${c.id}" ${e.category===c.id?'selected':''}>${c.icon} ${c.label}</option>`
                            ).join('')}
                        </select></div>
                </div>
                <div class="vault-ed-row vault-ed-row-2">
                    <div class="vault-ed-field"><div class="vault-ed-label">Benutzername</div>
                        <input class="vault-ed-input" id="ved-user" value="${esc(e.username)}" /></div>
                    <div class="vault-ed-field"><div class="vault-ed-label">Passwort</div>
                        <input class="vault-ed-input" id="ved-pw" type="password" value="${esc(e.password||'')}" /></div>
                </div>
                <div class="vault-ed-row vault-ed-row-2">
                    <div class="vault-ed-field"><div class="vault-ed-label">URL</div>
                        <input class="vault-ed-input" id="ved-url" value="${esc(e.url)}" placeholder="https://…" /></div>
                    <div class="vault-ed-field"><div class="vault-ed-label">Icon (Emoji)</div>
                        <input class="vault-ed-input" id="ved-icon" value="${esc(e.icon||'🔑')}" style="font-size:18px;width:60px" /></div>
                </div>
                <div class="vault-ed-field"><div class="vault-ed-label">Tags (kommagetrennt)</div>
                    <input class="vault-ed-input" id="ved-tags" value="${esc((e.tags||[]).join(', '))}" /></div>
                <div class="vault-ed-field"><div class="vault-ed-label">Notizen</div>
                    <textarea class="vault-ed-textarea" id="ved-notes">${esc(e.notes||'')}</textarea></div>
                <div class="vault-ed-footer">
                    <button class="vault-ed-cancel" id="ved-cancel">Abbrechen</button>
                    <button class="vault-ed-save" id="ved-save">💾 Speichern</button>
                </div>
            </div>
        </div>`;
    vaultRoot.querySelector('#ved-cancel').addEventListener('click', () => renderVaultApp());
    vaultRoot.querySelector('#ved-save').addEventListener('click', () => saveEntry(isNew, e.id));
}

async function saveEntry(isNew, existingId) {
    const payload = {
        title:    vaultRoot.querySelector('#ved-title')?.value || '',
        username: vaultRoot.querySelector('#ved-user')?.value  || '',
        password: vaultRoot.querySelector('#ved-pw')?.value    || '',
        url:      vaultRoot.querySelector('#ved-url')?.value   || '',
        category: vaultRoot.querySelector('#ved-cat')?.value   || 'internet',
        icon:     vaultRoot.querySelector('#ved-icon')?.value  || '🔑',
        tags:     (vaultRoot.querySelector('#ved-tags')?.value||'').split(',').map(t=>t.trim()).filter(Boolean),
        notes:    vaultRoot.querySelector('#ved-notes')?.value || '',
    };
    try {
        const url    = isNew ? `${getApiBase()}/api/vault/entries` : `${getApiBase()}/api/vault/entries/${existingId}`;
        const method = isNew ? 'POST' : 'PUT';
        const res    = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json', 'X-Vault-Token': vaultState.masterToken || '' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error('Fehler beim Speichern');
        await loadEntries();
        renderVaultApp();
    } catch (err) {
        alert('Fehler: ' + err.message);
    }
}
