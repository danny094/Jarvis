function toMountLines(mounts) {
    if (!Array.isArray(mounts)) return '';
    return mounts
        .map(mount => `${mount?.host || ''}:${mount?.container || ''}:${mount?.mode || 'rw'}`)
        .map(line => line.trim())
        .filter(Boolean)
        .join('\n');
}

function toEnvLines(environment) {
    if (!environment || typeof environment !== 'object') return '';
    return Object.entries(environment)
        .map(([key, value]) => `${String(key || '').trim()}=${String(value ?? '')}`)
        .map(line => line.trim())
        .filter(Boolean)
        .join('\n');
}

function toDeviceLines(devices) {
    if (!Array.isArray(devices)) return '';
    return devices
        .map(item => String(item || '').trim())
        .filter(Boolean)
        .join('\n');
}

function toSecretLines(secrets) {
    if (!Array.isArray(secrets)) return '';
    return secrets
        .map(secret => {
            const name = String(secret?.name || '').trim();
            if (!name) return '';
            const optional = secret?.optional ? 'optional' : 'required';
            const description = String(secret?.description || '').trim();
            return description ? `${name}|${optional}|${description}` : `${name}|${optional}`;
        })
        .filter(Boolean)
        .join('\n');
}

function parseBlueprintMounts(raw) {
    const mounts = [];
    const errors = [];
    const lines = String(raw || '').split('\n').map(line => line.trim()).filter(Boolean);
    lines.forEach((line, index) => {
        const parts = line.split(':').map(part => part.trim());
        if (parts.length < 2 || parts.length > 3 || !parts[0] || !parts[1]) {
            errors.push(`Mount Zeile ${index + 1}: Format ist host:container[:ro|rw]`);
            return;
        }
        const mode = (parts[2] || 'rw').toLowerCase();
        if (mode !== 'ro' && mode !== 'rw') {
            errors.push(`Mount Zeile ${index + 1}: Mode muss ro oder rw sein`);
            return;
        }
        mounts.push({ host: parts[0], container: parts[1], mode });
    });
    return { mounts, errors };
}

function parseBlueprintSecrets(raw) {
    const secrets = [];
    const errors = [];
    const lines = String(raw || '').split('\n').map(line => line.trim()).filter(Boolean);
    lines.forEach((line, index) => {
        const parts = line.split('|').map(part => part.trim());
        const name = parts[0] || '';
        if (!name) {
            errors.push(`Secret Zeile ${index + 1}: Name fehlt`);
            return;
        }
        let optional = false;
        let descStart = 1;
        const token = (parts[1] || '').toLowerCase();
        if (token) {
            if (['optional', 'opt', 'true', 'yes'].includes(token)) {
                optional = true;
                descStart = 2;
            } else if (['required', 'req', 'false', 'no'].includes(token)) {
                optional = false;
                descStart = 2;
            }
        }
        const description = parts.slice(descStart).join('|').trim();
        secrets.push({ name, optional, description });
    });
    return { secrets, errors };
}

export {
    parseBlueprintMounts,
    parseBlueprintSecrets,
    toDeviceLines,
    toEnvLines,
    toMountLines,
    toSecretLines,
};
