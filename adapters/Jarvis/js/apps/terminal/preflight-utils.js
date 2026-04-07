function parseMemoryToMb(rawValue) {
    const value = String(rawValue || '').trim().toLowerCase();
    if (!value) return NaN;
    const match = value.match(/^(\d+(?:\.\d+)?)([kmg])$/);
    if (!match) return NaN;
    const amount = Number(match[1]);
    const unit = match[2];
    if (!Number.isFinite(amount) || amount <= 0) return NaN;
    if (unit === 'g') return amount * 1024;
    if (unit === 'm') return amount;
    return amount / 1024;
}

function formatMemoryMb(mb) {
    if (!Number.isFinite(mb) || mb <= 0) return 'n/a';
    if (mb >= 1024) return `${(mb / 1024).toFixed(2)}g`;
    return `${Math.round(mb)}m`;
}

function parseEnvOverrides(rawText) {
    const environment = {};
    const lines = String(rawText || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
    for (const line of lines) {
        const index = line.indexOf('=');
        if (index <= 0) {
            throw new Error(`Invalid env line: "${line}" (expected KEY=VALUE)`);
        }
        const key = line.slice(0, index).trim();
        const value = line.slice(index + 1);
        if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
            throw new Error(`Invalid env key: "${key}"`);
        }
        environment[key] = value;
    }
    return environment;
}

function parseDeviceOverrides(rawText) {
    const devices = [];
    const seen = new Set();
    const lines = String(rawText || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
    for (const line of lines) {
        if (/\s/.test(line)) {
            throw new Error(`Invalid device mapping (no spaces allowed): "${line}"`);
        }
        const hostPath = line.split(':')[0].trim();
        if (!hostPath.startsWith('/dev/')) {
            throw new Error(`Invalid device host path (must start with /dev/): "${line}"`);
        }
        if (hostPath.includes('..')) {
            throw new Error(`Invalid device host path: "${line}"`);
        }
        if (!seen.has(line)) {
            seen.add(line);
            devices.push(line);
        }
    }
    return devices;
}

function normalizeManagedPathCatalog(payload) {
    const catalog = Array.isArray(payload?.catalog) ? payload.catalog : [];
    const normalized = [];
    const seen = new Set();

    for (const item of catalog) {
        const path = String(item?.path || '').trim();
        if (!path || seen.has(path)) continue;
        seen.add(path);
        normalized.push({
            id: String(item?.id || `mp-${normalized.length + 1}`),
            label: String(item?.label || path.split('/').filter(Boolean).pop() || path),
            path,
            source: String(item?.source || '').trim(),
            asset_id: String(item?.asset_id || '').trim(),
            default_mode: String(item?.default_mode || 'rw').trim().toLowerCase() === 'ro' ? 'ro' : 'rw',
            allowed_for: Array.isArray(item?.allowed_for)
                ? item.allowed_for.map(entry => String(entry || '').trim()).filter(Boolean)
                : [],
            published_to_commander: Boolean(item?.published_to_commander),
        });
    }

    if (!normalized.length) {
        const fallback = Array.isArray(payload?.managed_paths) ? payload.managed_paths : [];
        for (const raw of fallback) {
            const path = String(raw || '').trim();
            if (!path || seen.has(path)) continue;
            seen.add(path);
            normalized.push({
                id: `mp-${normalized.length + 1}`,
                label: path.split('/').filter(Boolean).pop() || path,
                path,
                source: 'storage_broker',
                asset_id: '',
                default_mode: 'rw',
                allowed_for: [],
                published_to_commander: false,
            });
        }
    }

    return normalized.sort((a, b) => a.path.localeCompare(b.path));
}

function findManagedCatalogItem(managedCatalog, selectedPath) {
    const target = String(selectedPath || '').trim();
    if (!target || !Array.isArray(managedCatalog)) return null;
    return managedCatalog.find(item => String(item?.path || '').trim() === target) || null;
}

function getManagedMounts(formValues) {
    const mounts = Array.isArray(formValues?.managed_mounts)
        ? formValues.managed_mounts
        : [];
    if (mounts.length > 0) {
        return mounts
            .map(item => ({
                path: String(item?.path || '').trim(),
                container: String(item?.container || '').trim(),
                mode: String(item?.mode || 'rw').trim().toLowerCase() === 'ro' ? 'ro' : 'rw',
            }))
            .filter(item => item.path);
    }

    const selectedPath = String(formValues?.managed_path || '').trim();
    if (!selectedPath) return [];
    return [{
        path: selectedPath,
        container: String(formValues?.managed_container || '').trim(),
        mode: String(formValues?.managed_mode || 'rw').trim().toLowerCase() === 'ro' ? 'ro' : 'rw',
    }];
}

function hasResourceOverride(base, current) {
    return String(base.cpu_limit || '') !== String(current.cpu_limit || '')
        || String(base.memory_limit || '').toLowerCase() !== String(current.memory_limit || '').toLowerCase()
        || String(base.memory_swap || '').toLowerCase() !== String(current.memory_swap || '').toLowerCase()
        || Number(base.timeout_seconds || 0) !== Number(current.timeout_seconds || 0)
        || Number(base.pids_limit || 0) !== Number(current.pids_limit || 0);
}

function evaluateDeployPreflight(blueprint, quota, secrets, resources) {
    const blockers = [];
    const warnings = [];
    const checks = [];

    if (!blueprint?.dockerfile && !blueprint?.image) {
        blockers.push('Blueprint has neither Dockerfile nor image configured.');
    }

    const required = Array.isArray(blueprint?.secrets_required) ? blueprint.secrets_required : [];
    const available = new Set();
    (Array.isArray(secrets) ? secrets : []).forEach(secret => {
        if (secret?.scope === 'global') available.add(String(secret.name || '').trim());
        if (secret?.scope === 'blueprint' && secret?.blueprint_id === blueprint.id) {
            available.add(String(secret.name || '').trim());
        }
    });

    required.forEach(req => {
        const name = String(req?.name || '').trim();
        if (!name) return;
        if (!available.has(name)) {
            if (req?.optional) warnings.push(`Optional secret missing: ${name}`);
            else blockers.push(`Required secret missing: ${name}`);
        }
    });
    if (!required.length) checks.push('No declared secrets required.');

    const requestedCpu = Number.parseFloat(String(resources.cpu_limit || '0'));
    if (!Number.isFinite(requestedCpu) || requestedCpu <= 0) {
        blockers.push(`Invalid CPU limit: ${resources.cpu_limit}`);
    }
    const requestedMemMb = parseMemoryToMb(resources.memory_limit);
    if (!Number.isFinite(requestedMemMb) || requestedMemMb <= 0) {
        blockers.push(`Invalid memory limit: ${resources.memory_limit}`);
    }
    const requestedSwapMb = parseMemoryToMb(resources.memory_swap);
    if (!Number.isFinite(requestedSwapMb) || requestedSwapMb <= 0) {
        blockers.push(`Invalid swap limit: ${resources.memory_swap}`);
    }
    if (!Number.isFinite(resources.timeout_seconds) || resources.timeout_seconds <= 0) {
        blockers.push(`Invalid timeout (TTL): ${resources.timeout_seconds}`);
    }
    if (!Number.isFinite(resources.pids_limit) || resources.pids_limit <= 0) {
        blockers.push(`Invalid pids limit: ${resources.pids_limit}`);
    }

    const containersUsed = Number(quota?.containers_used || 0);
    const maxContainers = Number(quota?.max_containers || 0);
    const memoryUsed = Number(quota?.memory_used_mb || 0);
    const memoryMax = Number(quota?.max_total_memory_mb || 0);
    const cpuUsed = Number(quota?.cpu_used || 0);
    const cpuMax = Number(quota?.max_total_cpu || 0);
    const remainingSlots = maxContainers - containersUsed;
    const remainingMemMb = memoryMax - memoryUsed;
    const remainingCpu = cpuMax - cpuUsed;

    if (remainingSlots <= 0) blockers.push(`Container quota exhausted (${containersUsed}/${maxContainers}).`);
    else checks.push(`Container slots available: ${remainingSlots}/${maxContainers}.`);

    if (Number.isFinite(requestedMemMb) && requestedMemMb > remainingMemMb) {
        blockers.push(`Not enough memory quota. Need ${formatMemoryMb(requestedMemMb)}, available ${formatMemoryMb(remainingMemMb)}.`);
    } else if (Number.isFinite(requestedMemMb)) {
        checks.push(`Memory check passed (${formatMemoryMb(requestedMemMb)} requested).`);
    }

    if (Number.isFinite(requestedCpu) && requestedCpu > remainingCpu + 1e-9) {
        blockers.push(`Not enough CPU quota. Need ${requestedCpu.toFixed(2)}, available ${Math.max(remainingCpu, 0).toFixed(2)}.`);
    } else if (Number.isFinite(requestedCpu)) {
        checks.push(`CPU check passed (${requestedCpu.toFixed(2)} requested).`);
    }

    const network = String(blueprint?.network || 'internal');
    if (network === 'full') warnings.push('Network mode FULL requires explicit user approval.');
    else if (network === 'bridge') warnings.push('Network mode BRIDGE has host-level network access.');
    else checks.push(`Network mode ${network.toUpperCase()} (restricted).`);

    if (blueprint?.image && !blueprint?.image_digest) {
        warnings.push('Image is not digest-pinned. Consider setting image_digest for stronger trust guarantees.');
    } else if (blueprint?.image && blueprint?.image_digest) {
        checks.push('Image digest pinning configured.');
    }

    return {
        blockers,
        warnings,
        checks,
        requested: {
            cpu: requestedCpu,
            memory_mb: requestedMemMb,
            swap_mb: requestedSwapMb,
        },
    };
}

function applyManagedStoragePreflightChecks(report, blueprint, formValues, managedCatalog) {
    const mounts = getManagedMounts(formValues);
    if (!mounts.length) {
        report.checks.push('Managed storage picker: no extra host path selected.');
        return;
    }

    const seenTargets = new Set();
    const seenPairs = new Set();
    mounts.forEach((mount, index) => {
        const selected = findManagedCatalogItem(managedCatalog, mount.path);
        const label = selected?.label || mount.path;
        const mountLabel = mounts.length > 1 ? `Mount ${index + 1}` : 'Managed storage mount';

        if (!selected) {
            report.blockers.push(`${mountLabel}: path is not in broker catalog: ${mount.path}`);
            return;
        }

        const containerPath = String(mount.container || '').trim();
        if (!containerPath || !containerPath.startsWith('/')) {
            report.blockers.push(`${mountLabel}: container target must be an absolute path: ${containerPath || '(empty)'}`);
            return;
        }
        if (containerPath === '/') {
            report.blockers.push(`${mountLabel}: target "/" is not allowed.`);
            return;
        }
        if (seenTargets.has(containerPath)) {
            report.blockers.push(`${mountLabel}: duplicate container target "${containerPath}".`);
            return;
        }
        seenTargets.add(containerPath);

        const pairKey = `${mount.path}=>${containerPath}`;
        if (seenPairs.has(pairKey)) {
            report.blockers.push(`${mountLabel}: duplicate storage mapping ${pairKey}.`);
            return;
        }
        seenPairs.add(pairKey);

        if (String(selected?.default_mode || 'rw').trim().toLowerCase() === 'ro' && mount.mode === 'rw') {
            report.blockers.push(`${mountLabel}: ${label} is published read-only and cannot be mounted rw.`);
            return;
        }

        if (selected?.asset_id) {
            const usage = Array.isArray(selected?.allowed_for) && selected.allowed_for.length > 0
                ? selected.allowed_for.join(', ')
                : 'general';
            report.checks.push(`${mountLabel}: asset ${selected.label} (${usage}, default ${selected.default_mode || 'rw'}).`);
        } else {
            report.checks.push(`${mountLabel}: broker path ${label}.`);
        }

        if (Array.isArray(selected?.allowed_for) && selected.allowed_for.length > 0 && blueprint?.id) {
            if (selected.allowed_for.includes(String(blueprint.id))) {
                report.checks.push(`${mountLabel}: explicitly allowed for blueprint ${blueprint.id}.`);
            } else {
                report.warnings.push(`${mountLabel}: path is not explicitly listed for blueprint ${blueprint.id}.`);
            }
        }

        if (mount.mode === 'rw') {
            report.warnings.push(`${mountLabel}: write access ${mount.path} → ${containerPath}.`);
        } else {
            report.checks.push(`${mountLabel}: read-only ${mount.path} → ${containerPath}.`);
        }
    });

    if (mounts.length > 1) {
        report.checks.push(`Managed storage mounts configured: ${mounts.length}.`);
    }
}

function applyAdvancedOverridesPreflightChecks(report, blueprint, formValues) {
    try {
        const environment = parseEnvOverrides(formValues?.env_raw || '');
        const count = Object.keys(environment).length;
        if (count > 0) {
            report.warnings.push(`Environment overrides configured: ${count} variable(s).`);
        } else {
            report.checks.push('Environment overrides: none.');
        }
    } catch (error) {
        report.blockers.push(error.message || 'Invalid environment overrides.');
    }

    try {
        const devices = parseDeviceOverrides(formValues?.devices_raw || '');
        if (devices.length > 0) {
            report.warnings.push(`Device overrides configured: ${devices.length} mapping(s).`);
        } else if (Array.isArray(blueprint?.devices) && blueprint.devices.length > 0) {
            report.checks.push(`Blueprint has ${blueprint.devices.length} static device mapping(s).`);
        } else {
            report.checks.push('Device overrides: none.');
        }
    } catch (error) {
        report.blockers.push(error.message || 'Invalid device overrides.');
    }
}

function deriveTrustInfo(blueprint) {
    const network = String(blueprint?.network || 'internal');
    const risk = network === 'full' ? 'high' : (network === 'bridge' ? 'medium' : 'low');
    const digest = blueprint?.image_digest ? 'pinned' : 'unverified';
    const signature = blueprint?.signature_verified ? 'verified' : 'unknown';
    const recommendation = risk === 'high'
        ? 'High-risk network path. Require explicit approval.'
        : (risk === 'medium' ? 'Bridge network increases host exposure.' : 'Restricted network profile.');
    return { risk, digest, signature, recommendation };
}

export {
    applyAdvancedOverridesPreflightChecks,
    applyManagedStoragePreflightChecks,
    deriveTrustInfo,
    evaluateDeployPreflight,
    findManagedCatalogItem,
    formatMemoryMb,
    hasResourceOverride,
    normalizeManagedPathCatalog,
    parseDeviceOverrides,
    parseEnvOverrides,
    parseMemoryToMb,
};
