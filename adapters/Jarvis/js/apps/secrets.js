/**
 * API Keys / Secrets Manager
 * Settings → API Keys
 */

function getApiBase() {
    if (typeof window.getApiBase === "function") {
        return window.getApiBase();
    }
    if (window.location.port === "3000" || window.location.port === "80" || window.location.port === "") {
        return "";
    }
    return `${window.location.protocol}//${window.location.hostname}:8200`;
}

function secretsUrl() {
    return `${getApiBase()}/api/secrets`;
}

let _editingName = null;

async function loadSecrets() {
    const tbody = document.getElementById('secrets-table-body');
    if (!tbody) return;

    try {
        const res = await fetch(secretsUrl());
        const data = await res.json();
        const secrets = data.secrets || [];

        if (secrets.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="px-4 py-8 text-center text-gray-500">
                Noch keine Keys gespeichert. Füge deinen ersten Key oben hinzu.
            </td></tr>`;
            return;
        }

        tbody.innerHTML = secrets.map(s => `
            <tr class="border-b border-[#333] hover:bg-[#2a2a2a] transition-colors">
                <td class="px-4 py-3 font-mono text-accent-primary">${escHtml(s.name)}</td>
                <td class="px-4 py-3 text-gray-500 font-mono tracking-widest">●●●●●●●●●●●●</td>
                <td class="px-4 py-3 text-gray-500 text-xs">${s.updated_at ? s.updated_at.slice(0,16).replace('T',' ') : '—'}</td>
                <td class="px-4 py-3 text-right">
                    <div class="flex gap-2 justify-end">
                        <button onclick="window.SecretsApp.openEdit('${escHtml(s.name)}')"
                            class="px-3 py-1.5 bg-[#333] text-gray-300 rounded-lg text-xs hover:bg-[#444] flex items-center gap-1">
                            <i data-lucide="pencil" class="w-3 h-3"></i> Bearbeiten
                        </button>
                        <button onclick="window.SecretsApp.deleteSecret('${escHtml(s.name)}')"
                            class="px-3 py-1.5 bg-red-900/30 text-red-400 rounded-lg text-xs hover:bg-red-900/50 flex items-center gap-1">
                            <i data-lucide="trash-2" class="w-3 h-3"></i> Löschen
                        </button>
                    </div>
                </td>
            </tr>
        `).join('');

        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="px-4 py-4 text-center text-red-400">Fehler: ${escHtml(e.message)}</td></tr>`;
    }
}

async function addSecret() {
    const name = document.getElementById('secret-new-name')?.value?.trim().toUpperCase();
    const value = document.getElementById('secret-new-value')?.value?.trim();

    if (!name || !value) { alert('Name und Wert sind erforderlich.'); return; }

    try {
        const res = await fetch(secretsUrl(), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, value })
        });
        const data = await res.json();
        if (data.success) {
            document.getElementById('secret-new-name').value = '';
            document.getElementById('secret-new-value').value = '';
            await loadSecrets();
        } else {
            alert('Fehler: ' + (data.error || 'Unbekannt'));
        }
    } catch (e) { alert('Fehler: ' + e.message); }
}

function openEdit(name) {
    _editingName = name;
    document.getElementById('secret-edit-name').textContent = name;
    document.getElementById('secret-edit-value').value = '';
    document.getElementById('secret-edit-modal').classList.remove('hidden');
    document.getElementById('secret-edit-value').focus();
}

async function saveEdit() {
    const value = document.getElementById('secret-edit-value')?.value?.trim();
    if (!value) { alert('Bitte neuen Wert eingeben.'); return; }

    try {
        const res = await fetch(`${secretsUrl()}/${encodeURIComponent(_editingName)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value })
        });
        const data = await res.json();
        document.getElementById('secret-edit-modal').classList.add('hidden');
        if (data.success) { await loadSecrets(); }
        else { alert('Fehler: ' + (data.error || 'Unbekannt')); }
    } catch (e) { alert('Fehler: ' + e.message); }
}

async function deleteSecret(name) {
    if (!confirm(`Key "${name}" wirklich löschen?\nKann nicht wiederhergestellt werden.`)) return;
    try {
        await fetch(`${secretsUrl()}/${encodeURIComponent(name)}`, { method: 'DELETE' });
        await loadSecrets();
    } catch (e) { alert('Fehler: ' + e.message); }
}

function escHtml(text) {
    const d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
}

window.SecretsApp = { loadSecrets, addSecret, openEdit, saveEdit, deleteSecret };
