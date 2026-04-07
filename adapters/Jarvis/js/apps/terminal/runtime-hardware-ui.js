function parseHardwareResourceId(resourceId) {
    const raw = String(resourceId || "").trim();
    const parts = raw.split("::");
    return {
        raw,
        connector: parts[0] || "",
        kind: parts[1] || "",
        hostPath: parts.slice(2).join("::") || "",
    };
}

function kindLabel(kind) {
    const map = {
        input: "Input",
        device: "Device",
        usb: "USB",
        block_device_ref: "Block-Device",
        mount_ref: "Mount-Ref",
    };
    return map[String(kind || "").trim()] || "Hardware";
}

function summarizeCapabilities(resource) {
    const caps = Array.isArray(resource?.capabilities) ? resource.capabilities : [];
    return caps
        .filter(cap => !["block", "fixed", "mount_ref"].includes(String(cap)))
        .slice(0, 3)
        .join(" · ");
}

function displayPrimaryName(resource) {
    const displayName = String(resource?.metadata?.display_name || "").trim();
    if (displayName) return displayName;
    const label = String(resource?.label || "").trim();
    const product = String(resource?.product || "").trim();
    const vendor = String(resource?.vendor || "").trim();
    const hostPath = String(resource?.host_path || "").trim();
    const baseName = hostPath.split("/").filter(Boolean).pop() || hostPath;
    if (label && label !== hostPath && label !== baseName) return label;
    if (product && vendor) return `${vendor} ${product}`.trim();
    if (product) return product;
    if (label) return label;
    return hostPath || "Unbenannte Hardware";
}

function displaySecondaryMeta(resource) {
    const displaySecondary = String(resource?.metadata?.display_secondary || "").trim();
    if (displaySecondary) return displaySecondary;
    const kind = String(resource?.kind || "").trim();
    const hostPath = String(resource?.host_path || "").trim();
    const vendor = String(resource?.vendor || "").trim();
    const product = String(resource?.product || "").trim();
    const caps = summarizeCapabilities(resource);
    const parts = [];
    if (vendor && product) {
        parts.push(`${vendor} · ${product}`);
    } else if (product) {
        parts.push(product);
    }
    if (caps) parts.push(caps);
    if (hostPath && kind !== "mount_ref" && kind !== "block_device_ref") parts.push(hostPath);
    if (hostPath && (kind === "mount_ref" || kind === "block_device_ref")) parts.unshift(hostPath);
    return parts.filter(Boolean).join(" · ");
}

function displayBadges(resource) {
    return Array.isArray(resource?.metadata?.display_badges)
        ? resource.metadata.display_badges.filter(Boolean).map(item => String(item).trim()).filter(Boolean)
        : [];
}

function simpleVisibility(resource) {
    const value = String(resource?.metadata?.simple_visibility || "").trim().toLowerCase();
    return value || "visible";
}

function simpleSelectableResourceIds(resource) {
    const values = Array.isArray(resource?.metadata?.simple_select_resource_ids)
        ? resource.metadata.simple_select_resource_ids
        : [];
    const ids = values.map(item => String(item || "").trim()).filter(Boolean);
    if (ids.length) return ids;
    const ownId = String(resource?.id || "").trim();
    return ownId ? [ownId] : [];
}

function simpleGroupId(resource) {
    return String(resource?.metadata?.simple_group_id || resource?.id || "").trim();
}

function buildFallbackHardwareResource(resourceId) {
    const parsed = parseHardwareResourceId(resourceId);
    const hostPath = parsed.hostPath;
    const baseName = hostPath.split("/").filter(Boolean).pop() || hostPath || resourceId;
    return {
        id: resourceId,
        kind: parsed.kind || "device",
        label: baseName,
        host_path: hostPath,
        vendor: "",
        product: "",
        capabilities: [],
        metadata: {},
    };
}

function findHardwareResource(resources, resourceId) {
    const normalized = String(resourceId || "").trim();
    const items = Array.isArray(resources) ? resources : [];
    return items.find(item => String(item?.id || "").trim() === normalized) || null;
}

function resolveDisplayHardwareResource(resources, resourceId) {
    return findHardwareResource(resources, resourceId) || buildFallbackHardwareResource(resourceId);
}

async function loadRuntimeHardwareResources(getApiBase) {
    const baseUrl = typeof getApiBase === "function"
        ? String(getApiBase() || "").replace(/\/commander$/, "")
        : "";
    if (!baseUrl) return [];
    try {
        const response = await fetch(`${baseUrl}/api/runtime-hardware/resources?connector=container`);
        if (!response.ok) return [];
        const payload = await response.json().catch(() => ({}));
        return Array.isArray(payload?.resources) ? payload.resources : [];
    } catch (_) {
        return [];
    }
}

export {
    displayBadges,
    displayPrimaryName,
    displaySecondaryMeta,
    findHardwareResource,
    kindLabel,
    loadRuntimeHardwareResources,
    parseHardwareResourceId,
    resolveDisplayHardwareResource,
    simpleGroupId,
    simpleSelectableResourceIds,
    simpleVisibility,
    summarizeCapabilities,
};
