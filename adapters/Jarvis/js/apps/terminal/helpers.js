function esc(value) {
    if (!value) return '';
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
}

function stripAnsi(input) {
    return String(input || '').replace(/\x1B\[[0-9;]*[A-Za-z]/g, '');
}

function normalizeTerminalOutput(input, options = {}) {
    const text = String(input || '');
    if (!text) return '';

    if (options.forXterm) {
        // xterm expects CRLF for line breaks; lone LF preserves the current column.
        return text.replace(/\r?\n/g, '\r\n');
    }

    return text
        .replace(/\r\n/g, '\n')
        .replace(/\r/g, '\n');
}

function downloadText(filename, text) {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
}

function toApiErrorMessage(payload, fallbackMessage) {
    if (payload && typeof payload.error === 'string' && payload.error.trim()) return payload.error;
    if (payload && typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail;
    return fallbackMessage;
}

function toApiErrorHint(errorCode) {
    const code = String(errorCode || '').trim();
    if (!code) return '';
    const hints = {
        bad_request: 'Please check the entered values.',
        not_found: 'Verify ID or object still exists.',
        conflict: 'Resource conflict detected. Refresh and retry.',
        validation_error: 'One or more fields are invalid.',
        unauthorized: 'Permission is missing.',
        forbidden: 'Action is currently blocked by policy.',
        approval_failed: 'Approval was resolved, expired, or rejected.',
        snapshot_failed: 'Volume state prevented snapshot creation.',
        restore_failed: 'Snapshot restore could not be completed.',
        deploy_conflict: 'Deploy blocked by runtime or trust constraints.',
        healthcheck_timeout: 'Container did not become healthy in time and was auto-stopped.',
        healthcheck_unhealthy: 'Container failed healthcheck and was auto-stopped.',
        container_not_ready: 'Container exited before readiness and was auto-stopped.',
        policy_denied: 'Request blocked by TRION memory policy.',
        home_container_missing: 'TRION home container is not available.',
        home_container_not_running: 'TRION home container exists but is not running.',
        home_container_ambiguous: 'Multiple home containers detected. Resolve ambiguity first.',
        home_container_unavailable: 'Home memory is currently unavailable.',
    };
    return hints[code] || '';
}

function renderEmpty(icon, title, sub) {
    return `<div class="term-empty"><div class="term-empty-icon">${icon}</div><p>${title}</p><small>${sub}</small></div>`;
}

export {
    downloadText,
    esc,
    normalizeTerminalOutput,
    renderEmpty,
    stripAnsi,
    toApiErrorHint,
    toApiErrorMessage,
};
