let runtime = null;
let state = null;

function syncRuntime(ctx) {
    if (!ctx || typeof ctx !== "object" || !ctx.state) {
        throw new Error("Storage Broker runtime context missing.");
    }
    runtime = ctx;
    state = ctx.state;
}

function apiJson(path, options = {}) {
    return runtime.apiJson(path, options);
}

function esc(value) {
    return runtime.esc(value);
}

function setBusy(key, value) {
    runtime.setBusy(key, value);
}

function setFeedback(message, level = "info") {
    runtime.setFeedback(message, level);
}

function renderDetail() {
    runtime.renderDetail();
}

function renderMcpList() {
    runtime.renderMcpList();
}

function renderDetailActions() {
    runtime.renderDetailActions();
}

export const STORAGE_BROKER_BUSY_STATE = Object.freeze({
    sbSave: false,
    sbLoadDisks: false,
    sbAction: false,
});

export function createStorageBrokerState() {
    return {
        settings: null,
        disks: [],
        summary: null,
        audit: [],
        managedPaths: [],
        activeTab: "disks",      // disks | overview | setup | managed_paths | policies | audit
        mode: "basic",           // basic | advanced
        loaded: false,
        selectedDiskId: "",
        selectedPartitionDevice: "",
        locallyUnmountedDevices: [],
        expanded: {},
        diskSearch: "",
        selectedPartId: "",
        lastOutput: "",
        fullscreen: false,
        diskFilter: "all",       // all | recommended | protected | managed
        diskTab: "details",      // details | partition | rechte | ordner | sicherheit
        auditFilter: "all",      // all | allowed | blocked | provisioning | mount | format
        partEditor: {
            open: false,
            diskId: "",
            tableType: "gpt",
            plan: [],            // [{id, label, sizeGb, useRest, filesystem}]
            addFormOpen: false,
            addLabel: "",
            addSizeGb: "",
            addUseRest: false,
            addFilesystem: "ext4",
            showPreview: false,
            applyResult: "",
            applying: false,
        },
        setup: {
            open: false,
            flow: "",            // backup | services | existing_path | import_ro
            step: 1,
            values: {},
            result: "",
        },
        preview: null,
    };
}

export function isStorageBroker(name) {
    return String(name || "").toLowerCase().replace(/[-_]/g, "") === "storagebroker";
}

const SB_NAV_ITEMS = [
    { id: "overview", label: "Uebersicht" },
    { id: "setup", label: "Einrichtung" },
    { id: "disks", label: "Datentraeger" },
    { id: "managed_paths", label: "Verwaltete Pfade" },
    { id: "policies", label: "Richtlinien" },
    { id: "audit", label: "Audit" },
];

const SB_POLICY_META = {
    blocked: { label: "Geschuetzt", className: "sb-policy-blocked", description: "Nicht nutzbar fuer TRION." },
    read_only: { label: "Nur Lesen", className: "sb-policy-ro", description: "Sicher lesbar, keine Schreibrechte." },
    managed_rw: { label: "Von TRION verwaltet", className: "sb-policy-rw", description: "Schreiben nur in freigegebenen Bereichen." },
};

const SB_ZONE_META = {
    system: "Systemspeicher",
    managed_services: "Service-Speicher",
    backup: "Backup-Speicher",
    external: "Externer Datentraeger",
    docker_runtime: "Docker-Laufzeit",
    unzoned: "Noch nicht eingerichtet",
};

const SB_RISK_META = {
    critical: { label: "Kritisch", className: "sb-risk-critical" },
    caution: { label: "Vorsicht", className: "sb-risk-caution" },
    safe: { label: "Sicher", className: "sb-risk-safe" },
};

const SB_SETUP_FLOW_META = {
    backup: { label: "Backup-Speicher", zone: "backup", policy_state: "managed_rw", service_name: "backup", profile: "backup" },
    services: { label: "Container-Speicher", zone: "managed_services", policy_state: "managed_rw", service_name: "containers", profile: "standard" },
    existing_path: { label: "Bestehenden Pfad freigeben", zone: "managed_services", policy_state: "managed_rw", service_name: "service", profile: "standard" },
    import_ro: { label: "Nur-Lesen Import", zone: "external", policy_state: "read_only", service_name: "import", profile: "minimal" },
};

const SB_SERVICE_DIR_PROFILES = {
    standard: ["config", "data", "logs"],
    full: ["config", "data", "logs", "workspace", "backups", "tmp"],
    minimal: ["data"],
    backup: ["backups"],
};

// Partitions smaller than this are considered system/EFI/boot partitions and
// are excluded from container storage targets and the setup wizard picker.
const SB_MIN_USABLE_BYTES = 512 * 1024 * 1024; // 512 MiB

function sbIsSmallSystemPart(disk) {
    if (String(disk?.disk_type || "") !== "partition") return false;
    const size = Number(disk?.size_bytes || disk?.size || 0);
    return size > 0 && size < SB_MIN_USABLE_BYTES;
}

const SB_ASSET_ALLOWED_FOR_OPTIONS = [
    { value: "appdata", label: "App-Daten" },
    { value: "games", label: "Spielebibliothek" },
    { value: "workspace", label: "Workspace" },
    { value: "media", label: "Medien / Import" },
    { value: "backup", label: "Backup" },
];

function sbLabelPolicy(policy) {
    const meta = SB_POLICY_META[String(policy || "").trim()] || null;
    return meta ? meta.label : (policy || "Unbekannt");
}

function sbLabelZone(zone) {
    return SB_ZONE_META[String(zone || "").trim()] || (zone || "Unbekannt");
}

function sbSafeIso(ts) {
    const raw = String(ts || "").trim();
    if (!raw) return "-";
    return raw.slice(0, 19).replace("T", " ");
}

function sbRiskBadge(risk) {
    const key = String(risk || "caution").trim();
    const meta = SB_RISK_META[key] || SB_RISK_META.caution;
    return `<span class="sb-badge ${meta.className}">${esc(meta.label)}</span>`;
}

function sbPolicyBadge(policy) {
    const key = String(policy || "blocked").trim();
    const meta = SB_POLICY_META[key] || SB_POLICY_META.blocked;
    return `<span class="sb-badge ${meta.className}" title="${esc(key)}">${esc(meta.label)}</span>`;
}

function sbFormatBytes(b) {
    if (!b) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let v = Number(b);
    if (!Number.isFinite(v) || v <= 0) return "—";
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i += 1;
    }
    return `${v.toFixed(1)} ${units[i]}`;
}

function sbParentDevice(device, id) {
    const dev = String(device || "").trim() || `/dev/${String(id || "").trim()}`;
    if (/^\/dev\/nvme\d+n\d+p\d+$/.test(dev) || /^\/dev\/mmcblk\d+p\d+$/.test(dev)) {
        return dev.replace(/p\d+$/, "");
    }
    if (/^\/dev\/[a-z]+[0-9]+$/.test(dev)) {
        return dev.replace(/[0-9]+$/, "");
    }
    return "";
}

function sbBuildDiskTree(disks) {
    const items = Array.isArray(disks) ? disks : [];
    const roots = items.filter((d) => String(d.disk_type || "") === "disk");
    const rootByDevice = new Map(roots.map((r) => [String(r.device || ""), r]));
    const childrenByRootId = new Map(roots.map((r) => [String(r.id || ""), []]));
    const orphans = [];

    items
        .filter((d) => String(d.disk_type || "") !== "disk")
        .forEach((part) => {
            const parentDevice = sbParentDevice(part.device, part.id);
            const parent = rootByDevice.get(parentDevice);
            if (!parent) {
                orphans.push(part);
                return;
            }
            const key = String(parent.id || "");
            const list = childrenByRootId.get(key) || [];
            list.push(part);
            childrenByRootId.set(key, list);
        });

    roots.sort((a, b) => String(a.device || a.id || "").localeCompare(String(b.device || b.id || "")));
    for (const list of childrenByRootId.values()) {
        list.sort((a, b) => String(a.device || a.id || "").localeCompare(String(b.device || b.id || "")));
    }
    orphans.sort((a, b) => String(a.device || a.id || "").localeCompare(String(b.device || b.id || "")));
    return { roots, childrenByRootId, orphans };
}


function sbDefaultSetupValues(flow) {
    const meta = SB_SETUP_FLOW_META[flow] || SB_SETUP_FLOW_META.services;
    return {
        disk_id: state.sb.selectedDiskId || "",
        zone: meta.zone,
        policy_state: meta.policy_state,
        service_name: meta.service_name,
        profile: meta.profile,
        existing_path: "",
        do_format: false,
        filesystem: "ext4",
        label: "",
        do_mount: false,
        persist_mount: true,
        mountpoint: "",
        mount_options: "",
        publish_to_commander: flow === "services",
        asset_label: "",
        asset_default_mode: flow === "import_ro" || flow === "backup" ? "ro" : "rw",
        asset_allowed_for: flow === "backup" ? "backup" : (flow === "import_ro" ? "media" : (flow === "services" ? "appdata" : "workspace")),
    };
}

function sbOpenSetup(flow, preset = {}) {
    const values = { ...sbDefaultSetupValues(flow), ...preset };
    state.sb.setup = {
        open: true,
        flow,
        step: 1,
        values,
        result: "",
    };
    state.sb.activeTab = "setup";
    renderDetail();
}

function sbCloseSetup() {
    state.sb.setup = {
        open: false,
        flow: "",
        step: 1,
        values: {},
        result: "",
    };
    state.sb.activeTab = "disks";
    renderDetail();
}

function sbReadSetupFields(root) {
    if (!state.sb.setup?.open) return;
    const values = { ...(state.sb.setup.values || {}) };
    root.querySelectorAll("[data-sb-field]").forEach((el) => {
        const key = String(el.getAttribute("data-sb-field") || "").trim();
        if (!key) return;
        if (el.type === "checkbox") {
            values[key] = Boolean(el.checked);
        } else {
            values[key] = String(el.value || "");
        }
    });
    state.sb.setup.values = values;
}

function sbValidateSetupStep(step) {
    const flow = String(state.sb.setup?.flow || "");
    const values = state.sb.setup?.values || {};
    const currentStep = Number(step || state.sb.setup?.step || 1);

    if (currentStep === 1) {
        if (flow === "existing_path") {
            const path = String(values.existing_path || "").trim();
            if (!path) return "Bitte einen Pfad angeben.";
            if (!path.startsWith("/")) return "Der Pfad muss absolut sein.";
            return "";
        }
        if (!String(values.disk_id || "").trim()) {
            return "Bitte zuerst einen Datentraeger auswaehlen.";
        }
    }

    if (currentStep === 2) {
        if (flow !== "existing_path" && flow !== "import_ro" && !String(values.service_name || "").trim()) {
            return "Bitte einen Service-Namen angeben.";
        }
        if (values.do_mount && !String(values.mountpoint || "").trim()) {
            return "Bitte einen Mountpoint angeben oder das automatische Mounten deaktivieren.";
        }
        if (values.do_format && !String(values.filesystem || "").trim()) {
            return "Bitte ein Filesystem fuer die Formatierung waehlen.";
        }
        if (values.publish_to_commander && !String(values.asset_allowed_for || "").trim()) {
            return "Bitte einen Verwendungszweck fuer die Commander-Freigabe waehlen.";
        }
    }

    return "";
}

function sbFindDiskById(diskId) {
    const id = String(diskId || "").trim();
    return (state.sb.disks || []).find((d) => String(d.id || "") === id) || null;
}

function sbBuildSetupPreview() {
    const flow = String(state.sb.setup?.flow || "");
    const values = state.sb.setup?.values || {};
    const disk = sbFindDiskById(values.disk_id);
    const actionTarget = sbResolveSetupActionTarget(disk);
    let risk = "Low";
    if (values.do_format) risk = "High";
    else if (values.do_mount) risk = "Medium";
    const target = flow === "existing_path"
        ? (values.existing_path || "-")
        : (actionTarget.label || disk?.device || disk?.id || "-");
    const actionLabel = SB_SETUP_FLOW_META[flow]?.label || "Einrichtung";
    return {
        target,
        actionLabel,
        writeScope: flow === "import_ro" ? "Keine Schreibrechte auf Datentraeger" : "Nur verwaltete Zielpfade",
        formatting: values.do_format ? `Ja (${values.filesystem || "ext4"})` : "Nein",
        mountChange: values.do_mount ? `Ja (${values.mountpoint || "ohne Ziel"})` : "Nein",
        mountPersistence: values.do_mount ? (values.persist_mount ? "Ja" : "Nein") : "Nein",
        publishChange: values.publish_to_commander
            ? `Ja (${values.asset_default_mode === "ro" ? "RO" : "RW"} / ${values.asset_allowed_for || "workspace"})`
            : "Nein",
        risk,
        targetError: actionTarget.error || "",
    };
}

function sbSlugifyAssetToken(raw) {
    const value = String(raw || "")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "");
    return value.slice(0, 72) || "asset";
}

function sbResolveAssetPath(flow, values, details = {}) {
    const mountpoint = String(values?.mountpoint || "").trim().replace(/\/+$/, "");
    const existingPath = String(values?.existing_path || "").trim();
    const serviceName = String(values?.service_name || "").trim() || "service";
    const targetBase = String(details?.targetBase || "").trim();
    const usage = String(values?.asset_allowed_for || "").trim().toLowerCase();
    if (flow === "existing_path") return existingPath;
    if (targetBase) {
        if (usage === "games" && flow !== "import_ro") return `${targetBase.replace(/\/+$/, "")}/data`;
        return targetBase;
    }
    if (flow === "import_ro") return mountpoint;
    if (usage === "games" && mountpoint) return `${mountpoint}/services/${serviceName}/data`;
    if (mountpoint) return `${mountpoint}/services/${serviceName}`;
    return "";
}

function sbBuildAssetLabel(flow, values, assetPath) {
    const explicit = String(values?.asset_label || "").trim();
    if (explicit) return explicit;
    if (flow !== "existing_path" && flow !== "import_ro") {
        return String(values?.service_name || "").trim() || "service";
    }
    const path = String(assetPath || "").trim();
    return path.split("/").filter(Boolean).pop() || "storage";
}

function sbBuildAssetPayload(flow, values, assetPath, disk) {
    const path = String(assetPath || "").trim();
    const zone = String(values?.zone || "managed_services").trim() || "managed_services";
    const policyState = String(values?.policy_state || "managed_rw").trim() || "managed_rw";
    const sourceKind = flow === "existing_path" ? "existing_path" : (flow === "import_ro" ? "import" : "service_dir");
    const label = sbBuildAssetLabel(flow, values, path);
    const usage = String(values?.asset_allowed_for || "").trim().toLowerCase();
    const defaultMode = String(values?.asset_default_mode || "ro").trim().toLowerCase() === "rw" ? "rw" : "ro";
    const identityBase = flow !== "existing_path" && flow !== "import_ro"
        ? `${zone}-${String(values?.service_name || "").trim() || label}`
        : path;
    return {
        id: `sb-${sbSlugifyAssetToken(identityBase)}`,
        label,
        path,
        zone,
        policy_state: policyState,
        published_to_commander: true,
        default_mode: defaultMode,
        allowed_for: usage ? [usage] : [],
        source_disk_id: String(disk?.id || "").trim() || null,
        source_kind: sourceKind,
        notes: `Published from Storage Manager flow '${flow || "setup"}'.`,
    };
}

async function sbUpsertStorageAsset(payload) {
    return apiJson("/api/commander/storage/assets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
    });
}

function sbResultLabel(result) {
    const r = result?.result || result || {};
    if (r.error) return `Fehler: ${r.error}`;
    if (r.ok === true && r.executed) return "Erfolgreich ausgefuehrt";
    if (r.ok === true && r.dry_run) return "Dry-Run Vorschau bereit";
    if (r.ok === true) return "Erfolgreich";
    return "Unbekanntes Ergebnis";
}

function sbRequireResultOk(result, fallbackMessage) {
    const r = result?.result || result || {};
    if (r?.ok === true && !r?.error) return;
    const detail = String(r?.error || "").trim();
    throw new Error(detail || String(fallbackMessage || "Aktion fehlgeschlagen."));
}

function sbSetLastOutput(title, payload = "") {
    const heading = String(title || "").trim();
    let body = "";
    if (payload instanceof Error) {
        body = payload.message || String(payload);
    } else if (typeof payload === "string") {
        body = payload.trim();
    } else if (payload != null && payload !== "") {
        try {
            body = JSON.stringify(payload, null, 2);
        } catch {
            body = String(payload);
        }
    }
    state.sb.lastOutput = [heading, body].filter(Boolean).join("\n\n").trim();
}

function sbSetLastActionOutput(title, payload) {
    const result = payload?.result || payload || {};
    const lines = [];
    if (title) lines.push(String(title).trim());
    lines.push(sbResultLabel(payload));
    if (result?.device) lines.push(`Ziel: ${result.device}`);
    if (result?.preview) lines.push(`Preview: ${result.preview}`);
    if (result?.error) lines.push(`Fehler: ${result.error}`);
    sbSetLastOutput("", lines.filter(Boolean).join("\n"));
}

function sbApplyUnmountLocalState(device) {
    const target = String(device || "").trim();
    if (!target) return;
    const overrideSet = new Set((state.sb.locallyUnmountedDevices || []).map((value) => String(value || "").trim()).filter(Boolean));
    overrideSet.add(target);
    state.sb.locallyUnmountedDevices = Array.from(overrideSet);
    state.sb.disks = (state.sb.disks || []).map((disk) => {
        if (sbPartitionDevicePath(disk) !== target && sbDiskDevicePath(disk) !== target) {
            return disk;
        }
        return {
            ...disk,
            mountpoint: "",
            mount_path: "",
            mountpoints: [],
            used_bytes: 0,
            used_human: "0 B",
        };
    });
}

function sbClearUnmountOverride(device) {
    const target = String(device || "").trim();
    if (!target) return;
    state.sb.locallyUnmountedDevices = (state.sb.locallyUnmountedDevices || []).filter((value) => String(value || "").trim() !== target);
}

async function sbLoadAll() {
    try {
        const [settingsRes, summaryRes, auditRes, managedRes] = await Promise.allSettled([
            apiJson("/api/storage-broker/settings"),
            apiJson("/api/storage-broker/summary"),
            apiJson("/api/storage-broker/audit?limit=80"),
            apiJson("/api/storage-broker/managed-paths"),
        ]);
        if (settingsRes.status === "fulfilled") state.sb.settings = settingsRes.value?.settings || null;
        if (summaryRes.status === "fulfilled") state.sb.summary = summaryRes.value?.summary || null;
        if (auditRes.status === "fulfilled") state.sb.audit = auditRes.value?.entries || [];
        if (managedRes.status === "fulfilled") state.sb.managedPaths = managedRes.value?.managed_paths || [];
        state.sb.loaded = true;
        renderDetail();
    } catch (e) {
        setFeedback(`Storage Broker Ladefehler: ${e.message}`, "err");
    }
}

async function sbLoadDisks() {
    setBusy("sbLoadDisks", true);
    try {
        const data = await apiJson("/api/storage-broker/disks");
        state.sb.disks = data?.disks || data?.result?.disks || [];
        const hasSelected = state.sb.disks.some((d) => String(d.id || "") === state.sb.selectedDiskId);
        if (!hasSelected) {
            const firstDisk = state.sb.disks.find((d) => String(d.disk_type || "") === "disk") || state.sb.disks[0];
            state.sb.selectedDiskId = String(firstDisk?.id || "");
        }
        renderDetail();
    } catch (e) {
        setFeedback(`Datentraeger konnten nicht geladen werden: ${e.message}`, "err");
    } finally {
        setBusy("sbLoadDisks", false);
    }
}

async function sbSaveSettings(updates) {
    setBusy("sbSave", true);
    try {
        const data = await apiJson("/api/storage-broker/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(updates),
        });
        state.sb.settings = data?.settings || state.sb.settings;
        setFeedback("Storage Broker Einstellungen gespeichert", "ok");
        renderDetail();
        return data;
    } catch (e) {
        setFeedback(`Speichern fehlgeschlagen: ${e.message}`, "err");
        throw e;
    } finally {
        setBusy("sbSave", false);
    }
}

async function sbSaveDiskPolicy(diskId, updates) {
    const id = String(diskId || "").trim();
    if (!id) return { ok: false, error: "disk_id fehlt" };
    const data = await apiJson(`/api/storage-broker/disks/${encodeURIComponent(id)}/policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates || {}),
    });
    if (data?.ok === false) {
        const msg = Array.isArray(data?.errors) && data.errors.length ? data.errors.join("; ") : "Datentraeger-Update fehlgeschlagen";
        throw new Error(msg);
    }
    return data;
}

async function sbValidatePath(path) {
    return apiJson("/api/storage-broker/validate-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
    });
}

async function sbProvisionServiceDir(args) {
    return apiJson("/api/storage-broker/provision/service-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args || {}),
    });
}

async function sbMountDevice(args) {
    return apiJson("/api/storage-broker/mount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args || {}),
    });
}

async function sbUnmountDevice(args) {
    return apiJson("/api/storage-broker/unmount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args || {}),
    });
}

async function sbFormatDevice(args) {
    return apiJson("/api/storage-broker/format", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args || {}),
    });
}

async function sbPartitionDisk(args) {
    return apiJson("/api/storage-broker/partition", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args || {}),
    });
}

async function sbExecuteSetup(dryRun) {
    const flow = String(state.sb.setup?.flow || "");
    const values = state.sb.setup?.values || {};
    const disk = sbFindDiskById(values.disk_id);
    const messages = [];
    const mountpoint = String(values.mountpoint || "").trim();
    const serviceName = String(values.service_name || "").trim() || "service";
    const profile = String(values.profile || "standard").trim() || "standard";
    let mountOk = !values.do_mount;
    let provisionOk = flow === "existing_path" || flow === "import_ro";
    let publishedAssetPath = "";

    setBusy("sbAction", true);
    try {
        if (flow === "existing_path") {
            const path = String(values.existing_path || "").trim();
            if (!path) throw new Error("Bitte einen Pfad angeben.");
            const validation = await sbValidatePath(path);
            const vr = validation?.validation || {};
            messages.push(`Pfadpruefung: ${vr.valid ? "ok" : "blockiert"} (${vr.reason || "kein Grund"})`);
            if (!dryRun) {
                const existing = Array.isArray(state.sb.settings?.managed_bases) ? [...state.sb.settings.managed_bases] : [];
                if (!existing.includes(path)) existing.push(path);
                await sbSaveSettings({ managed_bases: existing });
                messages.push("Pfad in managed_bases aufgenommen.");
                publishedAssetPath = path;
            }
        } else {
            if (!disk) throw new Error("Bitte einen Datentraeger waehlen.");
            if (disk.is_system) throw new Error("Systemdatentraeger kann nicht neu zugewiesen werden.");

            if (!dryRun) {
                await sbSaveDiskPolicy(String(disk.id || ""), {
                    zone: values.zone || "managed_services",
                    policy_state: values.policy_state || "managed_rw",
                });
                messages.push(`Disk ${disk.id}: zone=${values.zone} policy=${values.policy_state} gesetzt.`);
            } else {
                messages.push(`Vorschau: Disk ${disk.id} -> zone=${values.zone}, policy=${values.policy_state}`);
            }

            if (values.do_format) {
                const actionTarget = sbResolveSetupActionTarget(disk);
                if (actionTarget.error) throw new Error(actionTarget.error);
                const formatRes = await sbFormatDevice({
                    device: actionTarget.device,
                    filesystem: values.filesystem || "ext4",
                    label: values.label || "",
                    dry_run: dryRun,
                });
                sbRequireResultOk(formatRes, "Formatierung fehlgeschlagen.");
                messages.push(`Format: ${sbResultLabel(formatRes)}`);
            }

            if (values.do_mount) {
                const actionTarget = sbResolveSetupActionTarget(disk);
                if (actionTarget.error) throw new Error(actionTarget.error);
                if (!mountpoint) {
                    messages.push("Mount uebersprungen: mountpoint fehlt.");
                } else {
                    const mountRes = await sbMountDevice({
                        device: actionTarget.device,
                        mountpoint,
                        filesystem: "",
                        options: values.mount_options || "",
                        dry_run: dryRun,
                        create_mountpoint: true,
                        persist: Boolean(values.persist_mount),
                    });
                    messages.push(`Mount: ${sbResultLabel(mountRes)}`);

                    mountOk = mountRes?.result?.ok === true;
                    if (!dryRun && mountOk && flow !== "import_ro") {
                        const existing = Array.isArray(state.sb.settings?.managed_bases) ? [...state.sb.settings.managed_bases] : [];
                        if (!existing.includes(mountpoint)) {
                            existing.push(mountpoint);
                            await sbSaveSettings({ managed_bases: existing });
                            messages.push("Mountpoint in managed_bases aufgenommen.");
                        }
                    }
                }
            }

            if (flow !== "import_ro") {
                if (dryRun && mountpoint) {
                    const normalizedBase = mountpoint.replace(/\/+$/, "");
                    const serviceRoot = `${normalizedBase}/services/${serviceName}`;
                    const profileDirs = SB_SERVICE_DIR_PROFILES[profile] || SB_SERVICE_DIR_PROFILES.standard;
                    const totalPaths = 1 + profileDirs.length;
                    messages.push(`Provisioning: Vorschau (${totalPaths} Pfad(e) unter ${serviceRoot}).`);
                } else {
                    const provisionRes = await sbProvisionServiceDir({
                        service_name: serviceName,
                        zone: values.zone || "managed_services",
                        profile,
                        dry_run: dryRun,
                        base_path: mountpoint || "",
                    });
                    const pr = provisionRes?.result || {};
                    provisionOk = !pr?.errors?.length && pr?.ok !== false;
                    publishedAssetPath = sbResolveAssetPath(flow, values, { targetBase: pr?.target_base || "" });
                    if (pr?.errors?.length) {
                        messages.push(`Provisioning: Fehler (${pr.errors.join("; ")})`);
                    } else {
                        const createdCount = Array.isArray(pr.created) ? pr.created.length : 0;
                        const planCount = Array.isArray(pr.paths_to_create) ? pr.paths_to_create.length : 0;
                        messages.push(`Provisioning: ${dryRun ? "Vorschau" : "Fertig"} (${dryRun ? planCount : createdCount} Pfad(e)).`);
                    }
                }
            } else if (!dryRun) {
                publishedAssetPath = sbResolveAssetPath(flow, values, {});
            }
        }

        if (values.publish_to_commander) {
            const resolvedAssetPath = publishedAssetPath || sbResolveAssetPath(flow, values, {});
            if (dryRun) {
                messages.push(`Commander-Freigabe: Vorschau (${resolvedAssetPath || "Pfad wird bei Apply aufgeloest"}).`);
            } else if (!resolvedAssetPath) {
                messages.push("Commander-Freigabe: uebersprungen (kein Pfad ermittelt).");
            } else if (!mountOk || !provisionOk) {
                messages.push("Commander-Freigabe: uebersprungen (Setup war nicht erfolgreich genug).");
            } else {
                const assetRes = await sbUpsertStorageAsset(sbBuildAssetPayload(flow, values, resolvedAssetPath, disk));
                const stored = assetRes?.asset || {};
                messages.push(`Commander-Freigabe: Aktiv (${stored.label || resolvedAssetPath} -> ${stored.path || resolvedAssetPath}).`);
            }
        }

        state.sb.setup.step = 4;
        state.sb.setup.result = messages.join("\n");
        sbSetLastOutput(dryRun ? "Setup Dry-Run" : "Setup angewendet", state.sb.setup.result);
        await Promise.all([sbLoadAll(), sbLoadDisks()]);
        setFeedback(dryRun ? "Dry-Run abgeschlossen" : "Einrichtung angewendet", "ok");
    } catch (e) {
        setFeedback(`Einrichtung fehlgeschlagen: ${e.message}`, "err");
        state.sb.setup.step = 4;
        state.sb.setup.result = `Fehler: ${e.message}`;
        sbSetLastOutput("Setup fehlgeschlagen", state.sb.setup.result);
    } finally {
        setBusy("sbAction", false);
        renderDetail();
    }
}

function sbRenderOverview(disks, summary, managedPaths) {
    const tree = sbBuildDiskTree(disks);
    const physicalDisks = tree.roots;
    const systemCount = physicalDisks.filter((d) => d.is_system).length;
    const availableCount = physicalDisks.filter((d) => !d.is_system).length;
    const warnings = physicalDisks.filter((d) => !d.is_system && String(d.risk_level || "") !== "safe").length;
    const managedCount = managedPaths.length || Number(summary.managed_rw_count || 0);

    const recent = (state.sb.audit || []).slice(0, 4);

    return `
        <section class="sb-view-head">
            <h4>Speicher-Uebersicht</h4>
            <p>So sieht TRION auf einen Blick, was sicher nutzbar ist.</p>
        </section>

        <div class="sb-summary-grid">
            <article class="sb-summary-card">
                <h5>System geschuetzt</h5>
                <strong>${systemCount}</strong>
                <small>Host-Speicher hart blockiert</small>
            </article>
            <article class="sb-summary-card">
                <h5>Verfuegbare Datentraeger</h5>
                <strong>${availableCount}</strong>
                <small>Erkannt und pruefbar</small>
            </article>
            <article class="sb-summary-card">
                <h5>Verwalteter Speicher</h5>
                <strong>${managedCount}</strong>
                <small>Verwaltete Pfade / RW-Eintraege</small>
            </article>
            <article class="sb-summary-card">
                <h5>Warnungen</h5>
                <strong>${warnings}</strong>
                <small>Bitte pruefen</small>
            </article>
        </div>

        <div class="sb-recommended">
            <h5>Empfohlene naechste Schritte</h5>
            <div class="sb-chip-row">
                <button class="sb-btn" data-sb-setup-start="backup">Backup-Ziel einrichten</button>
                <button class="sb-btn" data-sb-setup-start="services">Container-Speicher vorbereiten</button>
                <button class="sb-btn" data-sb-nav="disks">Datentraeger-Sicherheit pruefen</button>
            </div>
        </div>

        <div class="sb-overview-grid">
            <article class="sb-summary-panel">
                <h5>Datentraeger-Status</h5>
                <ul>
                    <li>Systemdatentraeger-Schutz ist aktiv.</li>
                    <li>${availableCount} Datentraeger fuer gefuehrtes Setup verfuegbar.</li>
                    <li>Keine unbeschraenkten Schreibrechte ausserhalb verwalteter Bereiche.</li>
                </ul>
            </article>
            <article class="sb-summary-panel">
                <h5>Letzte Aktivitaet</h5>
                ${recent.length ? `
                    <ul>
                        ${recent.map((e) => `<li>${esc(e.operation || "op")} auf <code>${esc(e.target || "-")}</code> (${esc(e.error ? "blockiert" : (e.result || "ok"))})</li>`).join("")}
                    </ul>
                ` : `<p class="sb-hint">Keine aktuellen Audit-Eintraege.</p>`}
            </article>
        </div>
    `;
}

function sbRenderSetupWizard(disks) {
    const setup = state.sb.setup || {};
    const values = setup.values || {};
    const flow = String(setup.flow || "services");
    const step = Number(setup.step || 1);
    const preview = sbBuildSetupPreview();

    const flowMeta = {
        services: { name: "Container-Speicher einrichten", steps: ["Datentr\u00e4ger", "Konfiguration", "Vorschau", "Ausf\u00fchren"] },
        backup:   { name: "Backup-Speicher einrichten",    steps: ["Datentr\u00e4ger", "Konfiguration", "Vorschau", "Ausf\u00fchren"] },
        import_ro:{ name: "Medien importieren",            steps: ["Datentr\u00e4ger", "Einstellungen", "Vorschau", "Ausf\u00fchren"] },
        existing_path: { name: "Pfad freigeben",           steps: ["Pfad w\u00e4hlen", "Einstellungen", "Vorschau", "Ausf\u00fchren"] },
    };
    const meta = flowMeta[flow] || flowMeta.services;
    const totalSteps = 4;

    // Step progress indicator
    const stepNodes = meta.steps.map((label, i) => {
        const n = i + 1;
        const isDone = n < step;
        const isActive = n === step;
        const circleClass = isDone ? "sb-wiz-step-done" : isActive ? "sb-wiz-step-active" : "sb-wiz-step-todo";
        const labelClass = isActive ? "sb-wiz-step-label active" : "sb-wiz-step-label";
        const icon = isDone ? "&#10003;" : String(n);
        const line = i < meta.steps.length - 1
            ? `<div class="sb-wiz-step-line${isDone ? " done" : ""}"></div>`
            : "";
        return `
            <div class="sb-wiz-step-node">
                <div class="sb-wiz-step-circle ${circleClass}">${icon}</div>
                <div class="${labelClass}">${esc(label)}</div>
            </div>
            ${line}`;
    }).join("");

    // Step intro boxes
    const stepIntros = {
        services: [
            { icon: "&#128190;", title: "Welchen Datentr\u00e4ger m\u00f6chtest du verwenden?", text: "W\u00e4hle den Datentr\u00e4ger der f\u00fcr deine Docker-Services genutzt werden soll. System-Datentr\u00e4ger sind nicht w\u00e4hlbar." },
            { icon: "&#9881;&#65039;", title: "Wie soll der Speicher konfiguriert werden?", text: "Diese Einstellungen bestimmen wie TRION auf den Datentr\u00e4ger zugreift. F\u00fcr die meisten F\u00e4lle sind die Standardwerte richtig." },
            { icon: "&#128269;", title: "Alles korrekt? Bitte pr\u00fcfe die Zusammenfassung.", text: "Diese Aktionen werden ausgef\u00fchrt wenn du auf \"Jetzt anwenden\" klickst." },
            { icon: "&#9654;&#65039;", title: "Einrichtung ausf\u00fchren", text: "Du kannst zuerst einen Dry-Run starten um zu pr\u00fcfen was passieren w\u00fcrde \u2014 ohne \u00c4nderungen vorzunehmen." },
        ],
        backup: [
            { icon: "&#128190;", title: "Welchen Datentr\u00e4ger f\u00fcr Backups?", text: "W\u00e4hle einen Datentr\u00e4ger der als Backup-Ziel dienen soll. Externe USB-Laufwerke eignen sich gut." },
            { icon: "&#9881;&#65039;", title: "Backup-Einstellungen", text: "Lege fest wie der Backup-Speicher eingebunden und gesichert werden soll." },
            { icon: "&#128269;", title: "Zusammenfassung pr\u00fcfen", text: "Bitte pr\u00fcfe die Einstellungen bevor du die Einrichtung startest." },
            { icon: "&#9654;&#65039;", title: "Einrichtung ausf\u00fchren", text: "Starte die Einrichtung oder probiere zuerst einen Dry-Run." },
        ],
    };
    const intros = stepIntros[flow] || stepIntros.services;
    const intro = intros[step - 1] || intros[0];

    // Build disk picker for step 1
    const eligibleDisks = (disks || []).filter(d =>
        String(d.disk_type || "") === "disk" &&
        !d.is_system &&
        String(d.zone || "") !== "system"
    );
    const diskPickerRows = eligibleDisks.length
        ? eligibleDisks.map(d => {
            const id = String(d.id || "");
            const dev = esc(sbDiskDevicePath(d));
            const model = esc(d.model || d.name || dev);
            const size = sbFormatBytes(d.size_bytes || d.size || 0);
            const mount = esc(d.mountpoint || d.mount_path || "");
            const sub = [d.transport || d.bus, mount ? ("gemountet: " + mount) : "nicht gemountet"].filter(Boolean).join(" · ");
            const isChosen = String(values.disk_id || "") === id;
            return `
                <div class="sb-wiz-disk-choice${isChosen ? " chosen" : ""}" data-wiz-disk="${esc(id)}">
                    <div class="sb-wiz-dc-radio"></div>
                    <div class="sb-wiz-dc-icon">&#128189;</div>
                    <div class="sb-wiz-dc-info">
                        <div class="sb-wiz-dc-name">${model}</div>
                        <div class="sb-wiz-dc-sub">${esc(sub)}</div>
                    </div>
                    <div class="sb-wiz-dc-size">${size}</div>
                </div>`;
        }).join("")
        : `<div class="sb-wiz-empty-disks">Keine geeigneten Datentr\u00e4ger gefunden. Bitte zuerst einen Datentr\u00e4ger einbinden.</div>`;

    // Build step body
    let stepBody = "";

    if (step === 1) {
        if (flow === "existing_path") {
            stepBody = `
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Pfad eingeben</div>
                    <div class="sb-wiz-field-hint">Der vollst\u00e4ndige absolute Pfad zum Ordner der freigegeben werden soll.</div>
                    <input class="sb-wiz-input" data-sb-field="existing_path" value="${esc(values.existing_path || "")}" placeholder="/mnt/trion-data" />
                </div>`;
        } else {
            stepBody = `<div class="sb-wiz-disk-picker">${diskPickerRows}</div>`;
        }
    }

    if (step === 2) {
        stepBody = `
            <div class="sb-wiz-form">
                ${flow !== "existing_path" && flow !== "import_ro" ? `
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Service-Name</div>
                    <div class="sb-wiz-field-hint">Ein eindeutiger Name \u2014 wird als Ordnername verwendet.</div>
                    <input class="sb-wiz-input" data-sb-field="service_name" value="${esc(values.service_name || "")}" placeholder="mein-service" />
                </div>
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Profil</div>
                    <div class="sb-wiz-field-hint">Legt fest welche Standard-Ordner fuer den Service erstellt werden.</div>
                    <select class="sb-wiz-select" data-sb-field="profile">
                        ${Object.keys(SB_SERVICE_DIR_PROFILES).map((profile) => `<option value="${profile}" ${values.profile === profile ? "selected" : ""}>${profile}</option>`).join("")}
                    </select>
                </div>` : ""}
                ${flow !== "existing_path" ? `
                <div class="sb-wiz-toggle-row">
                    <div class="sb-wiz-toggle-info">
                        <div class="sb-wiz-toggle-name">Vor Nutzung formatieren</div>
                        <div class="sb-wiz-toggle-hint">Datentr\u00e4ger neu formatieren \u2014 l\u00f6scht alle Daten!</div>
                    </div>
                    <label class="sb-toggle"><input type="checkbox" data-sb-field="do_format" ${values.do_format ? "checked" : ""} /><span class="sb-toggle-slider"></span></label>
                </div>
                ${values.do_format ? `
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Filesystem</div>
                    <select class="sb-wiz-select" data-sb-field="filesystem">
                        ${["ext4","xfs","btrfs","vfat"].map(fs => `<option value="${fs}" ${values.filesystem === fs ? "selected" : ""}>${fs}</option>`).join("")}
                    </select>
                </div>
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Label</div>
                    <input class="sb-wiz-input" data-sb-field="label" value="${esc(values.label || "")}" placeholder="trion-data" />
                </div>` : ""}
                <div class="sb-wiz-toggle-row">
                    <div class="sb-wiz-toggle-info">
                        <div class="sb-wiz-toggle-name">Mountpoint automatisch setzen</div>
                        <div class="sb-wiz-toggle-hint">Datentr\u00e4ger unter /mnt/[name] einh\u00e4ngen</div>
                    </div>
                    <label class="sb-toggle"><input type="checkbox" data-sb-field="do_mount" ${values.do_mount ? "checked" : ""} /><span class="sb-toggle-slider"></span></label>
                </div>
                ${values.do_mount ? `
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Mountpoint</div>
                    <input class="sb-wiz-input" data-sb-field="mountpoint" value="${esc(values.mountpoint || "")}" placeholder="/mnt/trion-data" />
                </div>
                <div class="sb-wiz-toggle-row">
                    <div class="sb-wiz-toggle-info">
                        <div class="sb-wiz-toggle-name">Mount persistent halten</div>
                        <div class="sb-wiz-toggle-hint">Schreibt einen passenden Eintrag fuer spaetere Neustarts.</div>
                    </div>
                    <label class="sb-toggle"><input type="checkbox" data-sb-field="persist_mount" ${values.persist_mount ? "checked" : ""} /><span class="sb-toggle-slider"></span></label>
                </div>
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Mount-Optionen</div>
                    <input class="sb-wiz-input" data-sb-field="mount_options" value="${esc(values.mount_options || "")}" placeholder="defaults,noatime" />
                </div>` : ""}` : ""}
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Richtlinie (Policy)</div>
                    <div class="sb-wiz-field-hint">Bestimmt wie TRION auf diesen Speicher zugreift.</div>
                    <select class="sb-wiz-select" data-sb-field="policy_state">
                        ${["blocked","read_only","managed_rw"].map(p => `<option value="${p}" ${values.policy_state === p ? "selected" : ""}>${esc(sbLabelPolicy(p))}</option>`).join("")}
                    </select>
                </div>
                <div class="sb-wiz-toggle-row">
                    <div class="sb-wiz-toggle-info">
                        <div class="sb-wiz-toggle-name">Im Container Manager anzeigen</div>
                        <div class="sb-wiz-toggle-hint">Erstellt oder aktualisiert eine sichere Commander-Freigabe fuer diesen Pfad.</div>
                    </div>
                    <label class="sb-toggle"><input type="checkbox" data-sb-field="publish_to_commander" ${values.publish_to_commander ? "checked" : ""} /><span class="sb-toggle-slider"></span></label>
                </div>
                ${values.publish_to_commander ? `
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Anzeige-Name</div>
                    <input class="sb-wiz-input" data-sb-field="asset_label" value="${esc(values.asset_label || "")}" placeholder="games-media" />
                </div>
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Standard-Zugriff</div>
                    <select class="sb-wiz-select" data-sb-field="asset_default_mode">
                        <option value="ro" ${values.asset_default_mode === "ro" ? "selected" : ""}>Read Only</option>
                        <option value="rw" ${values.asset_default_mode === "rw" ? "selected" : ""}>Read Write</option>
                    </select>
                </div>
                <div class="sb-wiz-field">
                    <div class="sb-wiz-field-label">Verwendungszweck</div>
                    <select class="sb-wiz-select" data-sb-field="asset_allowed_for">
                        ${SB_ASSET_ALLOWED_FOR_OPTIONS.map((opt) => `<option value="${opt.value}" ${values.asset_allowed_for === opt.value ? "selected" : ""}>${esc(opt.label)}</option>`).join("")}
                    </select>
                </div>
            </div>` : ""}`;
    }

    if (step === 3) {
        const riskLevel = String(preview.risk || "").toLowerCase();
        const riskCls = riskLevel.includes("hoch") || riskLevel.includes("high") ? "sb-wiz-risk-high"
            : riskLevel.includes("mittel") || riskLevel.includes("med") ? "sb-wiz-risk-med"
            : "sb-wiz-risk-low";
        const riskIcon = riskCls === "sb-wiz-risk-high" ? "&#9888;&#65039;" : riskCls === "sb-wiz-risk-med" ? "&#128310;" : "&#9989;";
        const previewRows = [
            ["Ziel", preview.target],
            ["Geplante Aktion", preview.actionLabel],
            ["Schreibzugriff", preview.writeScope],
            ["Formatierung", preview.formatting],
            ["Mount-\u00c4nderung", preview.mountChange],
            ["Mount persistent", preview.mountPersistence],
            ["Commander-Freigabe", preview.publishChange],
            ["Audit-Log", "Ja"],
        ].map(([k, v]) => v ? `
            <div class="sb-wiz-preview-row">
                <span class="sb-wiz-pr-key">${k}</span>
                <span class="sb-wiz-pr-val">${esc(String(v || ""))}</span>
            </div>` : "").join("");

        stepBody = `
            <div class="sb-wiz-preview-card">
                <div class="sb-wiz-preview-header">Zusammenfassung</div>
                ${previewRows}
            </div>
            <div class="sb-wiz-risk-row ${riskCls}">
                <span class="sb-wiz-risk-icon">${riskIcon}</span>
                <div>
                    <strong>Risiko: ${esc(preview.risk || "Niedrig")}</strong>
                    ${preview.targetError ? `<div style="font-size:11px;margin-top:2px;">${esc(preview.targetError)}</div>` : ""}
                </div>
            </div>`;
    }

    if (step === 4) {
        const result = String(setup.result || "");
        const hasResult = result.length > 0;
        const isOk = result.toLowerCase().includes("ok") || result.toLowerCase().includes("erfolg");
        const introCls = hasResult ? (isOk ? "sb-wiz-intro-success" : "sb-wiz-intro-warn") : "sb-wiz-intro-default";
        const introIcon = hasResult ? (isOk ? "&#9989;" : "&#9888;&#65039;") : "&#9654;&#65039;";
        const introTitle = hasResult ? (isOk ? "Einrichtung abgeschlossen!" : "Es gab ein Problem") : "Einrichtung ausf\u00fchren";
        const introText = hasResult
            ? (isOk ? "Der Datentr\u00e4ger wurde erfolgreich eingerichtet." : "Bitte pr\u00fcfe das Protokoll unten.")
            : "Du kannst zuerst einen Dry-Run starten um zu pr\u00fcfen was passieren w\u00fcrde \u2014 ohne \u00c4nderungen vorzunehmen.";
        stepBody = `
            <div class="sb-wiz-intro ${introCls}">
                <div class="sb-wiz-intro-icon">${introIcon}</div>
                <div>
                    <div class="sb-wiz-intro-title">${introTitle}</div>
                    <div class="sb-wiz-intro-text">${introText}</div>
                </div>
            </div>
            ${hasResult ? `
            <div class="sb-wiz-preview-card" style="margin-top:14px;">
                <div class="sb-wiz-preview-header">Ausf\u00fchrungsprotokoll</div>
                <pre class="sb-wiz-result-pre">${esc(result)}</pre>
            </div>` : ""}`;
    }

    // Footer buttons
    const backBtn = step > 1 && step < 4
        ? `<button class="sb-wiz-btn sb-wiz-btn-ghost" data-sb-setup-back="1">&#8592; Zur\u00fcck</button>`
        : `<span></span>`;
    const cancelBtn = `<button class="sb-wiz-btn sb-wiz-btn-ghost" data-sb-setup-cancel="1">Abbrechen</button>`;
    let rightBtns = "";
    if (step < 3) rightBtns = `<button class="sb-wiz-btn sb-wiz-btn-primary" data-sb-setup-next="1">Weiter &#8594;</button>`;
    if (step === 3) rightBtns = `
        <button class="sb-wiz-btn" data-sb-setup-run="dry">Dry-Run</button>
        <button class="sb-wiz-btn sb-wiz-btn-primary" data-sb-setup-run="apply" ${state.busy.sbAction ? "disabled" : ""}>Jetzt anwenden</button>`;
    if (step === 4) rightBtns = `<button class="sb-wiz-btn sb-wiz-btn-primary" data-sb-setup-done="1">Fertig &#10003;</button>`;

    return `
        <div class="sb-wiz-wrap">
            <div class="sb-wiz-progress">
                <div class="sb-wiz-progress-header">
                    <div class="sb-wiz-progress-title">${esc(meta.name)}</div>
                    <div class="sb-wiz-progress-step">Schritt ${step} von ${totalSteps}</div>
                </div>
                <div class="sb-wiz-steps-track">${stepNodes}</div>
            </div>
            <div class="sb-wiz-body">
                ${step === 4 ? "" : `
                <div class="sb-wiz-intro sb-wiz-intro-default">
                    <div class="sb-wiz-intro-icon">${intro.icon}</div>
                    <div>
                        <div class="sb-wiz-intro-title">${intro.title}</div>
                        <div class="sb-wiz-intro-text">${intro.text}</div>
                    </div>
                </div>`}
                <div class="sb-wiz-step-body">
                    ${stepBody}
                </div>
            </div>
            <div class="sb-wiz-footer">
                <div class="sb-wiz-footer-left">${backBtn} ${cancelBtn}</div>
                <div class="sb-wiz-footer-right">${rightBtns}</div>
            </div>
        </div>`;
}


function sbRenderSetup(disks) {
    const setupOpen = Boolean(state.sb.setup?.open);
    if (setupOpen) return sbRenderSetupWizard(disks);

    const flows = [
        {
            id: "services",
            icon: "&#128230;",
            name: "Container-Speicher",
            desc: "Datentr\u00e4ger f\u00fcr Docker-Services vorbereiten \u2014 mit verwalteten Ordnerstrukturen f\u00fcr Config, Daten und Logs.",
            badge: "Empfohlen",
            badgeCls: "sb-wiz-badge-green",
        },
        {
            id: "backup",
            icon: "&#128190;",
            name: "Backup-Speicher",
            desc: "Externen Datentr\u00e4ger oder Ordner als Backup-Ziel einrichten. Nur-Lesen-Schutz optional.",
            badge: "Einfach",
            badgeCls: "sb-wiz-badge-blue",
        },
        {
            id: "import_ro",
            icon: "&#127916;",
            name: "Medien importieren",
            desc: "Datentr\u00e4ger schreibgesch\u00fctzt einbinden \u2014 f\u00fcr Medien, Fotos oder Dokumente die nur gelesen werden sollen.",
            badge: "Einfach",
            badgeCls: "sb-wiz-badge-blue",
        },
        {
            id: "existing_path",
            icon: "&#128193;",
            name: "Vorhandenen Pfad freigeben",
            desc: "Einen bereits existierenden Ordner in die TRION-Verwaltung aufnehmen \u2014 ohne Formatierung.",
            badge: "Fortgeschritten",
            badgeCls: "sb-wiz-badge-purple",
        },
    ];
    const flowCards = flows.map(f => `
        <div class="sb-wiz-flow-card" data-wiz-flow="${esc(f.id)}">
            <span class="sb-wiz-flow-badge ${f.badgeCls}">${f.badge}</span>
            <div class="sb-wiz-flow-icon">${f.icon}</div>
            <div class="sb-wiz-flow-name">${f.name}</div>
            <div class="sb-wiz-flow-desc">${f.desc}</div>
        </div>`).join("");

    return `
        <div class="sb-wiz-select-wrap">
            <div class="sb-wiz-select-header">
                <div class="sb-wiz-select-title">Speicher einrichten</div>
                <div class="sb-wiz-select-sub">Was m\u00f6chtest du tun? W\u00e4hle eine Aufgabe \u2014 der Wizard startet direkt.</div>
            </div>
            <div class="sb-wiz-flow-grid">
                ${flowCards}
            </div>
        </div>`;
}

function sbDiskDevicePath(disk) {
    return String(disk?.device_path || disk?.device || "").trim() || `/dev/${String(disk?.id || "-").trim()}`;
}

function sbPartitionDevicePath(partition) {
    return String(partition?.device_path || partition?.device || "").trim() || `/dev/${String(partition?.id || "-").trim()}`;
}

function sbStorageItemLabel(item, fallback = "") {
    const fsLabel = String(item?.label || "").trim();
    if (fsLabel) return fsLabel;
    const partLabel = String(item?.partlabel || item?.part_label || "").trim();
    if (partLabel) return partLabel;
    const name = String(item?.name || "").trim();
    if (name) return name;
    const device = String(item?.device || item?.device_path || "").trim();
    if (device) return device;
    return String(fallback || "").trim();
}

function sbStorageItemDisplayName(item, fallback = "") {
    const label = sbStorageItemLabel(item, fallback);
    const device = String(item?.device || item?.device_path || "").trim();
    if (!label) return device || String(fallback || "").trim();
    if (!device || label === device) return label;
    return `${label} (${device})`;
}

function sbSelectedPartitionForDisk(disk, tree) {
    const partitions = sbPartitionListForDisk(disk, tree);
    if (!partitions.length) return null;
    const current = String(state.sb.selectedPartId || "").trim();
    if (!current) return null;
    return partitions.find((part, index) => String(part?.id || index) === current) || null;
}

function sbResolveDirectActionTarget(disk, tree) {
    if (!disk) {
        return { device: "", label: "", kind: "", mountpoints: [], mounted: false, partition: null, error: "Bitte einen Datentraeger waehlen." };
    }
    const partitions = sbPartitionListForDisk(disk, tree);
    if (!partitions.length) {
        const device = sbDiskDevicePath(disk);
        const mountpoints = [
            String(disk?.mountpoint || disk?.mount_path || "").trim(),
            ...((Array.isArray(disk?.mountpoints) ? disk.mountpoints : []).map((mp) => String(mp || "").trim())),
        ].filter(Boolean);
        return { device, label: sbStorageItemDisplayName(disk, device), kind: "disk", mountpoints, mounted: mountpoints.length > 0, partition: null, error: "" };
    }
    const usablePartitions = partitions.filter((part) => !sbIsSmallSystemPart(part));
    const selectedPart = sbSelectedPartitionForDisk(disk, tree);
    if (!selectedPart && usablePartitions.length === 1) {
        const autoPart = usablePartitions[0];
        const device = sbPartitionDevicePath(autoPart);
        const mountpoints = [
            String(autoPart?.mountpoint || autoPart?.mount_path || "").trim(),
            ...((Array.isArray(autoPart?.mountpoints) ? autoPart.mountpoints : []).map((mp) => String(mp || "").trim())),
        ].filter(Boolean);
        return {
            device,
            label: sbStorageItemDisplayName(autoPart, device),
            kind: "partition",
            mountpoints,
            mounted: mountpoints.length > 0,
            partition: autoPart,
            error: "",
        };
    }
    if (!selectedPart) {
        return {
            device: "",
            label: "",
            kind: "partition",
            mountpoints: [],
            mounted: false,
            partition: null,
            error: "Bitte zuerst eine Partition in der Tabelle oder im Balken auswaehlen.",
        };
    }
    const device = sbPartitionDevicePath(selectedPart);
    const mountpoints = [
        String(selectedPart?.mountpoint || selectedPart?.mount_path || "").trim(),
        ...((Array.isArray(selectedPart?.mountpoints) ? selectedPart.mountpoints : []).map((mp) => String(mp || "").trim())),
    ].filter(Boolean);
    return {
        device,
        label: sbStorageItemDisplayName(selectedPart, device),
        kind: "partition",
        mountpoints,
        mounted: mountpoints.length > 0,
        partition: selectedPart,
        error: "",
    };
}

function sbResolveSetupActionTarget(disk) {
    if (!disk) {
        return { device: "", label: "", kind: "", error: "Bitte einen Datentraeger waehlen." };
    }
    const tree = sbBuildDiskTree(state.sb.disks || []);
    const allParts = sbPartitionListForDisk(disk, tree);
    const partitions = allParts.filter(p => !sbIsSmallSystemPart(p));
    if (!partitions.length && !allParts.length) {
        const device = sbDiskDevicePath(disk);
        return { device, label: sbStorageItemDisplayName(disk, device), kind: "disk", error: "" };
    }
    if (!partitions.length) {
        // Only tiny system partitions found — fall back to the whole disk
        const device = sbDiskDevicePath(disk);
        return { device, label: sbStorageItemDisplayName(disk, device), kind: "disk", error: "" };
    }
    if (partitions.length === 1) {
        const device = sbPartitionDevicePath(partitions[0]);
        return { device, label: sbStorageItemDisplayName(partitions[0], device), kind: "partition", error: "" };
    }
    const selectedPart = sbSelectedPartitionForDisk(disk, tree);
    if (selectedPart && !sbIsSmallSystemPart(selectedPart)) {
        const device = sbPartitionDevicePath(selectedPart);
        return { device, label: sbStorageItemDisplayName(selectedPart, device), kind: "partition", error: "" };
    }
    return {
        device: "",
        label: "",
        kind: "partition",
        error: "Mehrere Partitionen erkannt. Bitte die gewuenschte Partition im Datentraeger-Tab direkt auswaehlen.",
    };
}

function sbDiskPolicyKey(disk) {
    return String(disk?.policy_state || "").trim() || (disk?.is_system ? "blocked" : "read_only");
}


function sbPartitionListForDisk(selectedDisk, tree) {
    if (!selectedDisk) return [];
    if (Array.isArray(selectedDisk.partitions) && selectedDisk.partitions.length) {
        return selectedDisk.partitions;
    }
    return tree.childrenByRootId.get(String(selectedDisk.id || "")) || [];
}


function sbKdePathRole(p) {
    if (p.includes("backup")) return { key: "backup", label: "Backup", icon: "&#128190;", cls: "sb-path-icon-backup", badgeCls: "sb-path-badge-backup" };
    if (p.includes("media") || p.includes("import")) return { key: "media", label: "Medien", icon: "&#127916;", cls: "sb-path-icon-media", badgeCls: "sb-path-badge-media" };
    if (p.includes("workspace")) return { key: "workspace", label: "Workspace", icon: "&#128193;", cls: "sb-path-icon-workspace", badgeCls: "sb-path-badge-workspace" };
    return { key: "service", label: "Service", icon: "&#128193;", cls: "sb-path-icon-service", badgeCls: "sb-path-badge-service" };
}

function sbKdePathService(p) {
    const parts = p.split("/").filter(Boolean);
    return parts.slice(-2).join("/") || parts.slice(-1)[0] || "unbekannt";
}

function sbKdePathUsagePct(p) {
    const assets = (state.sb.summary?.assets || []);
    const match = assets.find(a => String(a.path || "").startsWith(p) || p.startsWith(String(a.base || "")));
    if (!match || !match.size_bytes || !match.used_bytes) return null;
    return Math.round((match.used_bytes / match.size_bytes) * 100);
}

function sbRenderManagedPaths(summary) {
    const merged = Array.from(new Set([...(summary.managed_paths || []), ...(state.sb.managedPaths || [])]));
    const total = merged.length;
    const backups = merged.filter(p => p.includes("backup")).length;
    const roCount = merged.filter(p => p.includes("import") || p.includes("media")).length;
    const rwCount = total - roCount;

    const statsHtml = `
        <div class="sb-kde-path-stats">
            <div class="sb-kde-stat-card">
                <div class="sb-kde-stat-label">Gesamt</div>
                <div class="sb-kde-stat-val sb-kde-stat-blue">${total}</div>
            </div>
            <div class="sb-kde-stat-card">
                <div class="sb-kde-stat-label">Schreibbar</div>
                <div class="sb-kde-stat-val sb-kde-stat-green">${rwCount}</div>
            </div>
            <div class="sb-kde-stat-card">
                <div class="sb-kde-stat-label">Nur-Lesen</div>
                <div class="sb-kde-stat-val sb-kde-stat-amber">${roCount}</div>
            </div>
            <div class="sb-kde-stat-card">
                <div class="sb-kde-stat-label">Backups</div>
                <div class="sb-kde-stat-val sb-kde-stat-gray">${backups}</div>
            </div>
        </div>`;

    if (!merged.length) {
        return `
            <div class="sb-kde-paths-wrap">
                <div class="sb-kde-paths-header">
                    <div>
                        <div class="sb-kde-paths-title">Verwaltete Pfade</div>
                        <div class="sb-kde-paths-sub">Alle Speicherorte die TRION kennt und verwaltet.</div>
                    </div>
                </div>
                <div class="sb-kde-paths-empty">
                    <div class="sb-kde-empty-icon">&#128193;</div>
                    <div class="sb-kde-empty-title">Noch keine verwalteten Pfade</div>
                    <div class="sb-kde-empty-sub">Richte zuerst einen Service- oder Backup-Speicher ein. Danach erscheinen die Pfade hier automatisch.</div>
                    <div class="sb-kde-empty-btns">
                        <button class="sb-kde-empty-btn sb-kde-empty-btn-primary" data-sb-setup-start="services">+ Service-Pfad einrichten</button>
                        <button class="sb-kde-empty-btn" data-sb-setup-start="backup">Backup-Ziel einrichten</button>
                    </div>
                </div>
            </div>`;
    }

    const cards = merged.map((p) => {
        const role = sbKdePathRole(p);
        const service = sbKdePathService(p);
        const isRo = role.key === "media";
        const pct = sbKdePathUsagePct(p);
        const fillCls = pct == null ? "" : pct >= 90 ? "sb-kde-uf-crit" : pct >= 70 ? "sb-kde-uf-warn" : "sb-kde-uf-ok";
        const usageHtml = pct != null ? `
            <div class="sb-kde-path-usage">
                <div class="sb-kde-path-ubar"><div class="sb-kde-path-ufill ${fillCls}" style="width:${pct}%;"></div></div>
                <span class="sb-kde-path-unums${pct >= 90 ? ' sb-kde-path-unums-crit' : ''}">${pct}% belegt</span>
            </div>` : "";

        return `
            <div class="sb-kde-path-card">
                <div class="sb-kde-path-top">
                    <div class="sb-kde-path-icon ${role.cls}">${role.icon}</div>
                    <div class="sb-kde-path-info">
                        <div class="sb-kde-path-name">${esc(service)}</div>
                        <div class="sb-kde-path-fullpath">${esc(p)}</div>
                    </div>
                    <div class="sb-kde-path-badges">
                        <span class="sb-kde-path-badge ${role.badgeCls}">${role.label}</span>
                        <span class="sb-kde-path-badge ${isRo ? "sb-kde-path-badge-ro" : "sb-kde-path-badge-rw"}">${isRo ? "ro" : "rw"}</span>
                    </div>
                </div>
                ${usageHtml}
                <div class="sb-kde-path-service-row">Pfad: <strong>${esc(p)}</strong></div>
                <div class="sb-kde-path-actions">
                    <button class="sb-kde-path-btn" data-copy-path="${esc(p)}">Kopieren</button>
                    <button class="sb-kde-path-btn sb-kde-path-btn-danger" data-remove-path="${esc(p)}">Entfernen</button>
                </div>
            </div>`;
    }).join("");

    return `
        <div class="sb-kde-paths-wrap">
            <div class="sb-kde-paths-header">
                <div>
                    <div class="sb-kde-paths-title">Verwaltete Pfade</div>
                    <div class="sb-kde-paths-sub">Alle Speicherorte die TRION kennt und verwaltet — pro Service, Backup oder Import.</div>
                </div>
                <button class="sb-kde-paths-add-btn" data-sb-setup-start="services">+ Pfad hinzufügen</button>
            </div>
            ${statsHtml}
            <div class="sb-kde-filter-bar">
                <button class="sb-kde-filter-chip active" data-path-filter="all">Alle</button>
                <button class="sb-kde-filter-chip" data-path-filter="service">Service</button>
                <button class="sb-kde-filter-chip" data-path-filter="backup">Backup</button>
                <button class="sb-kde-filter-chip" data-path-filter="media">Medien</button>
            </div>
            <div class="sb-kde-path-cards" id="sb-kde-path-cards">
                ${cards}
            </div>
        </div>`;
}

function sbPolicyLabel(key) {
    if (key === "managed_rw") return "Verwaltet";
    if (key === "read_only") return "Nur-Lesen";
    if (key === "blocked") return "Gesperrt";
    return "Unbekannt";
}

function sbPolicyPillClass(key) {
    if (key === "managed_rw") return "sb-pol-pill-managed";
    if (key === "read_only") return "sb-pol-pill-ro";
    if (key === "blocked") return "sb-pol-pill-blocked";
    return "sb-pol-pill-free";
}

function sbRenderPolicies(summary) {
    const s = state.sb.settings || {};
    const disks = Array.isArray(state.sb.disks) ? state.sb.disks : [];
    const activeSubTab = String(state.sb.policySubTab || "disks");

    // Filter out tiny system partitions (EFI, BIOS boot, etc.) — not manageable as container storage
    const visibleDisks = disks.filter(d => !sbIsSmallSystemPart(d));

    // Security status badges
    const systemDiskCount = visibleDisks.filter(d => d.is_system || String(d.zone||"") === "system").length;
    const unsecuredCount = visibleDisks.filter(d => !d.policy_state || d.policy_state === "").length;
    const managedCount = visibleDisks.filter(d => d.policy_state === "managed_rw").length;
    const secBadges = [
        systemDiskCount > 0
            ? `<div class="sb-pol-sec-badge sb-pol-ok"><span class="sb-pol-sec-dot sb-pol-dot-ok"></span>System geschützt</div>`
            : "",
        `<div class="sb-pol-sec-badge sb-pol-ok"><span class="sb-pol-sec-dot sb-pol-dot-ok"></span>Schreibschutz aktiv</div>`,
        managedCount > 0
            ? `<div class="sb-pol-sec-badge sb-pol-info"><span class="sb-pol-sec-dot sb-pol-dot-info"></span>${managedCount} Datenträger verwaltet</div>`
            : "",
        unsecuredCount > 0
            ? `<div class="sb-pol-sec-badge sb-pol-warn"><span class="sb-pol-sec-dot sb-pol-dot-warn"></span>${unsecuredCount} ungesichert</div>`
            : "",
    ].filter(Boolean).join("");

    // Per-disk cards
    const diskCards = visibleDisks.length ? visibleDisks.map(disk => {
        const id = esc(String(disk.id || ""));
        const dev = esc(sbDiskDevicePath(disk));
        const name = esc(disk.model || disk.name || dev);
        const sub = [disk.transport || disk.bus, sbFormatBytes(disk.size_bytes || disk.size || 0)].filter(Boolean).join(" · ");
        const policyKey = sbDiskPolicyKey(disk);
        const isSystem = disk.is_system || String(disk.zone||"") === "system";
        const pillCls = sbPolicyPillClass(policyKey);
        const icon = (disk.transport === "usb" || String(disk.bus||"").includes("usb")) ? "&#128280;" : "&#128189;";
        const unsecured = !disk.policy_state || disk.policy_state === "";
        const warnHtml = unsecured ? `
            <div class="sb-pol-warn-box">
                &#9888; Kein Policy gesetzt — bitte eine Richtlinie wählen bevor TRION diesen Datenträger nutzt.
            </div>` : "";
        const switcher = ["managed_rw","read_only","blocked"].map(p => {
            const active = policyKey === p ? `sb-pol-ps-${p === "managed_rw" ? "managed" : p === "read_only" ? "ro" : "blocked"}` : "";
            return `<button class="sb-pol-ps-btn ${active}" data-pol-disk="${id}" data-pol-value="${p}">${sbPolicyLabel(p)}</button>`;
        }).join("");

        const auditToggle = "";

        const cardStyle = unsecured ? ' style="border-color:#F09595;"' : "";
        const hdrStyle = unsecured ? ' style="background:#FCEBEB;"' : "";

        return `
            <div class="sb-pol-disk-card"${cardStyle}>
                <div class="sb-pol-disk-header" data-pol-toggle="${id}"${hdrStyle}>
                    <span class="sb-pol-disk-icon">${icon}</span>
                    <div class="sb-pol-disk-info">
                        <div class="sb-pol-disk-name">${name}</div>
                        <div class="sb-pol-disk-sub">${esc(sub)} · ${dev}${isSystem ? " · <strong>System</strong>" : ""}</div>
                    </div>
                    <div class="sb-pol-disk-status">
                        <span class="sb-pol-pill ${pillCls}">${sbPolicyLabel(policyKey)}</span>
                        <span class="sb-pol-chevron" id="chev-${id}">&#9660;</span>
                    </div>
                </div>
                <div class="sb-pol-disk-body" id="polbody-${id}">
                    ${warnHtml}
                    <div class="sb-pol-policy-row">
                        <div>
                            <div class="sb-pol-tgl-label">Zugriffs-Policy</div>
                            <div class="sb-pol-tgl-hint">Wie darf TRION auf diesen Datenträger zugreifen?</div>
                        </div>
                        <div class="sb-pol-switcher" id="psw-${id}">
                            ${isSystem ? `<span class="sb-pol-pill sb-pol-pill-blocked">Gesperrt (System)</span>` : switcher}
                        </div>
                    </div>
                    ${auditToggle}
                </div>
            </div>`;
    }).join("") : `<div class="sb-pol-empty">Keine verwaltbaren Datenträger erkannt.</div>`;

    // Global settings tab
    const globalTab = `
        <div class="sb-pol-gs-card">
            <div class="sb-pol-gs-header"><div class="sb-pol-gs-title">Standard-Verhalten</div><div class="sb-pol-gs-sub">Was passiert wenn ein neues Gerät angeschlossen wird.</div></div>
            <div class="sb-pol-gs-rows">
                <div class="sb-pol-gs-row">
                    <div class="sb-pol-gs-info"><div class="sb-pol-gs-label">Externe Datenträger (USB)</div><div class="sb-pol-gs-hint">Standard-Policy für neu angeschlossene externe Geräte.</div></div>
                    <select class="sb-pol-gs-select" id="sb-ext-policy">
                        ${["blocked","read_only","managed_rw"].map(p => `<option value="${p}" ${s.external_default_policy === p ? "selected" : ""}>${sbPolicyLabel(p)}</option>`).join("")}
                    </select>
                </div>
                <div class="sb-pol-gs-row">
                    <div class="sb-pol-gs-info"><div class="sb-pol-gs-label">Unbekannte Mounts</div><div class="sb-pol-gs-hint">Datenträger die nicht in der Konfiguration stehen.</div></div>
                    <select class="sb-pol-gs-select" id="sb-unknown-policy">
                        ${["blocked","read_only"].map(p => `<option value="${p}" ${s.unknown_mount_default === p ? "selected" : ""}>${sbPolicyLabel(p)}</option>`).join("")}
                    </select>
                </div>
                <div class="sb-pol-gs-row">
                    <div class="sb-pol-gs-info"><div class="sb-pol-gs-label">Dry-Run standardmäßig aktiv</div><div class="sb-pol-gs-hint">Aktionen werden zuerst simuliert.</div></div>
                    <label class="sb-toggle"><input type="checkbox" id="sb-dry-run" ${s.dry_run_default ? "checked" : ""} /><span class="sb-toggle-slider"></span></label>
                </div>
                <div class="sb-pol-gs-row">
                    <div class="sb-pol-gs-info"><div class="sb-pol-gs-label">Freigabe für Schreibzugriffe erzwingen</div><div class="sb-pol-gs-hint">Jede Schreibaktion muss bestätigt werden.</div></div>
                    <label class="sb-toggle"><input type="checkbox" id="sb-req-approval" ${s.requires_approval_for_writes ? "checked" : ""} /><span class="sb-toggle-slider"></span></label>
                </div>
            </div>
        </div>`;

    // Blocked paths tab
    const blockedPaths = (s.blacklist_extra || []).map((p, i) => `
        <div class="sb-pol-bl-item">
            <span class="sb-pol-bl-path">${esc(p)}</span>
            <span class="sb-pol-bl-src">Benutzerdefiniert</span>
            <button class="sb-pol-bl-rm" data-sb-remove-bl="${i}">Entfernen</button>
        </div>`).join("") || `<div class="sb-pol-empty">Keine zusätzlichen gesperrten Pfade.</div>`;

    const blockedTab = `
        <div class="sb-pol-gs-card">
            <div class="sb-pol-gs-header"><div class="sb-pol-gs-title">Gesperrte Pfade</div><div class="sb-pol-gs-sub">Diese Pfade sind niemals gültige Provisioning-Ziele für TRION.</div></div>
            <div style="padding:12px 14px;display:flex;flex-direction:column;gap:8px;">
                <div class="sb-pol-bl-item" style="opacity:0.6;">
                    <span class="sb-pol-bl-path">/proc</span><span class="sb-pol-bl-src">System</span>
                </div>
                <div class="sb-pol-bl-item" style="opacity:0.6;">
                    <span class="sb-pol-bl-path">/sys</span><span class="sb-pol-bl-src">System</span>
                </div>
                <div class="sb-pol-bl-item" style="opacity:0.6;">
                    <span class="sb-pol-bl-path">/boot</span><span class="sb-pol-bl-src">System</span>
                </div>
                ${blockedPaths}
                <div class="sb-pol-add-row">
                    <input id="sb-bl-input" class="sb-pol-add-input" type="text" placeholder="/pfad/der/gesperrt/werden/soll" />
                    <button id="sb-bl-add-btn" class="sb-pol-add-btn">+ Hinzufügen</button>
                </div>
            </div>
        </div>`;

    const tabs = [
        { id: "disks", label: "Pro Datenträger" },
        { id: "global", label: "Globale Einstellungen" },
        { id: "blocked", label: "Gesperrte Pfade" },
    ];
    const subTabHtml = tabs.map(t =>
        `<button class="sb-pol-sub-tab${activeSubTab === t.id ? " active" : ""}" data-pol-subtab="${t.id}">${t.label}</button>`
    ).join("");

    const bodyContent = activeSubTab === "disks" ? diskCards
        : activeSubTab === "global" ? globalTab
        : blockedTab;

    return `
        <div class="sb-pol-wrap">
            <div class="sb-pol-header">
                <div>
                    <div class="sb-pol-title">Sicherheitsrichtlinien</div>
                    <div class="sb-pol-sub">Lege fest wie TRION auf deine Datenträger zugreift.</div>
                </div>
                <button class="sb-pol-save-btn" id="sb-save-btn" ${state.busy.sbSave ? "disabled" : ""}>
                    ${state.busy.sbSave ? "Speichert…" : "Speichern"}
                </button>
            </div>
            <div class="sb-pol-sec-status">${secBadges}</div>
            <div class="sb-pol-sub-tabs">${subTabHtml}</div>
            <div class="sb-pol-body">${bodyContent}</div>
        </div>`;
}

function sbAuditMatch(entry, filter) {
    const op = String(entry?.operation || "").toLowerCase();
    const hasError = Boolean(entry?.error);
    if (filter === "allowed") return !hasError;
    if (filter === "blocked") return hasError || String(entry?.result || "").toLowerCase().includes("blocked");
    if (filter === "provisioning") return op.includes("service") || op.includes("provision");
    if (filter === "mount") return op.includes("mount");
    if (filter === "format") return op.includes("format");
    return true;
}

function sbRenderAudit() {
    const filter = String(state.sb.auditFilter || "all");
    const entries = (state.sb.audit || []).filter((e) => sbAuditMatch(e, filter));
    const filterLabel = (f) => ({
        all: "Alle",
        allowed: "Erlaubt",
        blocked: "Blockiert",
        provisioning: "Provisioning",
        mount: "Mount",
        format: "Format",
    }[f] || f);
    return `
        <section class="sb-view-head">
            <h4>Audit</h4>
            <p>Nachvollziehen, welche Speicheraktionen erlaubt oder blockiert wurden.</p>
        </section>
        <div class="sb-filter-row">
            ${["all", "allowed", "blocked", "provisioning", "mount", "format"].map((f) => `
                <button class="sb-filter-btn ${filter === f ? "active" : ""}" data-sb-audit-filter="${f}">
                    ${esc(filterLabel(f))}
                </button>
            `).join("")}
        </div>
        <div class="sb-advanced-table-wrap">
            <table class="sb-advanced-table">
                <thead>
                    <tr>
                        <th>Zeit</th>
                        <th>Aktion</th>
                        <th>Ziel</th>
                        <th>Ergebnis</th>
                        <th>Grund</th>
                    </tr>
                </thead>
                <tbody>
                    ${entries.length ? entries.map((e) => `
                        <tr>
                            <td>${esc(sbSafeIso(e.created_at))}</td>
                            <td>${esc(e.operation || "-")}</td>
                            <td><code>${esc(e.target || "-")}</code></td>
                            <td class="${e.error ? "sb-txt-danger" : "sb-txt-ok"}">${esc(e.error ? "blockiert" : (e.result || "ok"))}</td>
                            <td>${esc(e.error || e.after_state || "-")}</td>
                        </tr>
                    `).join("") : `<tr><td colspan="5">Keine Audit-Eintraege vorhanden.</td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function sbNormalizeActiveTab() {
    const current = String(state.sb.activeTab || "disks");
    const kdeTab = ["disks", "overview", "managed_paths", "policies", "audit", "setup"];
    const known = kdeTab.includes(current) ? current : "disks";
    if (known !== current) state.sb.activeTab = known;
    return known;
}


function sbKdeRenderDiskBar(disk, tree) {
    if (!disk) return `<div class="sb-kde-bar-empty">Kein Datentraeger</div>`;
    const parts = sbPartitionListForDisk(disk, tree);
    const totalBytes = Math.max(1, Number(disk.size_bytes || 0));
    const palette = ["#378ADD","#1D9E75","#EF9F27","#a78bfa","#ef4444","#14b8a6","#888780"];
    let usedBytes = 0;
    let segs = parts.map((p, i) => {
        const size = Math.max(0, Number(p.size_bytes || 0));
        usedBytes += size;
        const flex = Math.max(1, Math.round((size / totalBytes) * 20));
        const color = palette[i % palette.length];
        const label = esc(sbStorageItemLabel(p, "p" + (i + 1)));
        const tooltip = esc(`${sbStorageItemDisplayName(p, "p" + (i + 1))} · ${p.filesystem || p.fstype || "—"} · ${sbFormatBytes(p.size_bytes)}`);
        return `<div class="sb-kde-seg" style="background:${color};flex:${flex};" data-part-id="${esc(String(p.id||i))}" title="${tooltip}">${label}</div>`;
    });
    if (!segs.length) segs = [`<div class="sb-kde-seg" style="background:var(--sb-muted);flex:1;color:var(--sb-text-muted);">Keine Partitionen</div>`];
    const freeBytes = Math.max(0, totalBytes - usedBytes);
    const freeFlex = Math.max(1, Math.round((freeBytes / totalBytes) * 20));
    segs.push(`<div class="sb-kde-seg sb-kde-seg-free" style="flex:${freeFlex};" title="Freier Speicher · ${esc(sbFormatBytes(freeBytes))}">frei</div>`);
    return segs.join("");
}

function sbKdeRenderPartTable(disk, tree) {
    if (!disk) return "";
    const parts = sbPartitionListForDisk(disk, tree);
    const palette = ["#378ADD","#1D9E75","#EF9F27","#a78bfa","#ef4444","#14b8a6","#888780"];
    const diskLabel = esc(sbStorageItemLabel(disk, disk.device || disk.id || "?"));
    const diskSize = sbFormatBytes(disk.size_bytes);
    const diskDev = esc(sbDiskDevicePath(disk));
    const rows = parts.map((p, i) => {
        const color = palette[i % palette.length];
        const dev = esc(sbPartitionDevicePath(p) || p.name || "");
        const fs = esc(p.filesystem || p.fstype || "—");
        const mount = esc(p.mountpoint || p.mount_path || "—");
        const label = esc(sbStorageItemLabel(p, "—"));
        const size = sbFormatBytes(p.size_bytes);
        const isLocked = Boolean(p.encrypted || p.crypto);
        const partId = esc(String(p.id || i));
        const zebraClass = i % 2 === 0 ? "" : " sb-kde-row-odd";
        let usageCell = sbFormatBytes(p.available_bytes);
        if (p.size_bytes > 0 && p.available_bytes != null) {
            const usedBytes = Math.max(0, p.size_bytes - p.available_bytes);
            const pct = Math.min(100, Math.round((usedBytes / p.size_bytes) * 100));
            const barColor = pct >= 90 ? "#ef4444" : pct >= 70 ? "#f59e0b" : "#22c55e";
            usageCell = `<div class="sb-kde-usage-wrap">
                <div class="sb-kde-usage-bar" style="width:${pct}%;background:${barColor};"></div>
                <span class="sb-kde-usage-label">${esc(sbFormatBytes(p.available_bytes))} frei</span>
            </div>`;
        }
        return `<tr class="sb-kde-row${zebraClass}" data-part-id="${partId}">
            <td><span class="sb-kde-dot" style="background:${color};"></span>${dev}</td>
            <td>${fs}</td>
            <td>${mount}${isLocked ? ' <span class="sb-kde-lock">&#128274;</span>' : ""}</td>
            <td>${label}</td>
            <td>${size}</td>
            <td>${usageCell}</td>
        </tr>`;
    });
    const freeRow = `<tr class="sb-kde-row sb-kde-row-free">
        <td><span class="sb-kde-dot sb-kde-dot-free"></span><span style="opacity:0.5;">Freier Speicher</span></td>
        <td style="opacity:0.5;">—</td><td style="opacity:0.5;">—</td><td style="opacity:0.5;">—</td>
        <td style="opacity:0.5;">—</td><td style="opacity:0.5;">—</td>
    </tr>`;
    return `
        <thead><tr class="sb-kde-thead">
            <th>Partition</th><th>Type</th><th>Mount Point</th><th>Label</th><th>Size</th><th>Used</th>
        </tr></thead>
        <tbody>
            <tr class="sb-kde-disk-heading"><td colspan="6">&#128189;&nbsp; ${diskLabel} — ${diskSize} (${diskDev})</td></tr>
            ${rows.join("")}
            ${freeRow}
        </tbody>`;
}

function sbKdeRenderInfoPanel(disk, partId, tree) {
    if (!disk) return `<span class="sb-kde-hint">Datentraeger auswaehlen…</span>`;
    if (!partId) return `<span class="sb-kde-hint">Partition auswaehlen…</span>`;
    const parts = sbPartitionListForDisk(disk, tree);
    const part = parts.find((p, i) => String(p.id || i) === String(partId));
    if (!part) return `<span class="sb-kde-hint">Freier Speicher</span>`;
    const infoRows = [
        ["Geraet", sbPartitionDevicePath(part) || part.name || "—"],
        ["Type", part.filesystem || part.fstype || "—"],
        ["Mount", part.mountpoint || part.mount_path || "—"],
        ["Label", sbStorageItemLabel(part, "—")],
        ["Groesse", sbFormatBytes(part.size_bytes)],
        ["Verfuegbar", sbFormatBytes(part.available_bytes)],
    ].map(([k, v]) => `<div class="sb-kde-info-cell"><span class="sb-kde-info-key">${esc(k)}</span><span class="sb-kde-info-val">${esc(String(v))}</span></div>`).join("");
    return infoRows;
}

function sbKdeRenderSidebar(disks, selectedId) {
    if (!disks.length) return `<div class="sb-kde-empty">Keine Datentraeger erkannt</div>`;
    return disks.map((disk) => {
        const id = String(disk.id || "");
        const isSelected = id === String(selectedId || "");
        const name = esc(sbStorageItemLabel(disk, disk.device || id));
        const sub = esc([disk.model, disk.transport || disk.bus].filter(Boolean).join(" · ") || "");
        const size = sbFormatBytes(disk.size_bytes);
        const policyKey = sbDiskPolicyKey(disk);
        const badgeClass = policyKey === "managed_rw" || policyKey === "managed_ro" ? "sb-kde-badge-managed"
            : policyKey === "blocked" ? "sb-kde-badge-blocked"
            : "sb-kde-badge-free";
        const badgeLabel = sbLabelPolicy(policyKey);
        const icon = disk.transport === "usb" ? "&#128280;" : (disk.transport === "nvme" || (disk.device||"").includes("nvme")) ? "&#9889;" : "&#128189;";
        const isMounted = Boolean(disk.mountpoint || disk.mount_path || (Array.isArray(disk.mountpoints) && disk.mountpoints.length));
        const mountTitle = esc(isMounted ? "Gemountet" : "Nicht gemountet");
        return `<div class="sb-kde-disk-item${isSelected ? " selected" : ""}" data-disk-id="${esc(id)}">
            <div class="sb-kde-disk-icon-wrap">
                <span class="sb-kde-disk-icon">${icon}</span>
                <span class="sb-kde-mount-dot ${isMounted ? "mounted" : "unmounted"}" title="${mountTitle}"></span>
            </div>
            <div class="sb-kde-disk-info">
                <span class="sb-kde-disk-name">${name}</span>
                <span class="sb-kde-disk-sub">${sub}</span>
            </div>
            <div class="sb-kde-disk-meta">
                <span class="sb-kde-disk-size">${size}</span>
                <span class="sb-kde-badge ${badgeClass}"><span class="sb-kde-badge-dot"></span>${badgeLabel}</span>
            </div>
        </div>`;
    }).join("");
}

// ─────────────────────────────────────────────────────────────────────────────
// PARTITION EDITOR
// ─────────────────────────────────────────────────────────────────────────────

const SB_PE_PALETTE = ["#378ADD","#1D9E75","#EF9F27","#a78bfa","#ef4444","#14b8a6","#888780"];

function sbPartEditorOpen(diskId) {
    state.sb.partEditor = {
        open: true,
        diskId: String(diskId || ""),
        tableType: "gpt",
        plan: [],
        addFormOpen: false,
        addLabel: "",
        addSizeGb: "",
        addUseRest: false,
        addFilesystem: "ext4",
        showPreview: false,
        applyResult: "",
        applying: false,
    };
}

function sbPartEditorFreeGb(disk, plan) {
    const totalGb = Number(disk.size_bytes || 0) / (1024 ** 3);
    const usedGb = plan.filter(p => !p.useRest).reduce((s, p) => s + Number(p.sizeGb || 0), 0);
    return Math.max(0, totalGb - usedGb);
}

function sbPartEditorBar(disk, plan) {
    const totalBytes = Math.max(1, Number(disk.size_bytes || 0));
    const totalGb = totalBytes / (1024 ** 3);
    const usedGb = plan.filter(p => !p.useRest).reduce((s, p) => s + Number(p.sizeGb || 0), 0);
    const freeGb = Math.max(0, totalGb - usedGb);
    const hasRest = plan.some(p => p.useRest);

    const segs = plan.map((p, i) => {
        const gb = p.useRest ? freeGb : Number(p.sizeGb || 0);
        const flex = Math.max(1, Math.round((gb / totalGb) * 1000));
        const color = SB_PE_PALETTE[i % SB_PE_PALETTE.length];
        const label = p.label || `p${i + 1}`;
        const sizeStr = p.useRest
            ? `~${sbFormatBytes(freeGb * 1024 ** 3)} (Rest)`
            : sbFormatBytes(gb * 1024 ** 3);
        return `<div class="sb-pe-seg" style="background:${color};flex:${flex};" title="${esc(label + ' · ' + p.filesystem + ' · ' + sizeStr)}">${esc(label)}</div>`;
    });

    if (!hasRest && freeGb > 0.001) {
        const freeFlex = Math.max(1, Math.round((freeGb / totalGb) * 1000));
        segs.push(`<div class="sb-pe-seg sb-pe-seg-free" style="flex:${freeFlex};" title="Nicht zugewiesen · ${esc(sbFormatBytes(freeGb * 1024 ** 3))}">nicht zugewiesen</div>`);
    }
    if (!segs.length) {
        segs.push(`<div class="sb-pe-seg sb-pe-seg-free" style="flex:1;">${esc(sbFormatBytes(totalBytes))} — noch keine Partitionen</div>`);
    }

    const legend = [
        ...plan.map((p, i) => {
            const color = SB_PE_PALETTE[i % SB_PE_PALETTE.length];
            const gb = p.useRest ? freeGb : Number(p.sizeGb || 0);
            const sizeStr = p.useRest ? `~${sbFormatBytes(freeGb * 1024 ** 3)}` : sbFormatBytes(gb * 1024 ** 3);
            return `<div class="sb-pe-leg-item"><span class="sb-pe-leg-dot" style="background:${color};"></span><span class="sb-pe-leg-name">${esc(p.label || `p${i + 1}`)}</span><span class="sb-pe-leg-detail">${esc(p.filesystem)} · ${sizeStr}</span></div>`;
        }),
        (!hasRest && freeGb > 0.001)
            ? `<div class="sb-pe-leg-item"><span class="sb-pe-leg-dot sb-pe-leg-dot-free"></span><span class="sb-pe-leg-name">Nicht zugewiesen</span><span class="sb-pe-leg-detail">${sbFormatBytes(freeGb * 1024 ** 3)}</span></div>`
            : "",
    ].join("");

    return `<div class="sb-pe-bar-wrap"><div class="sb-pe-bar">${segs.join("")}</div><div class="sb-pe-legend">${legend}</div></div>`;
}

function sbPartEditorBuildPreview(disk, plan) {
    const device = sbDiskDevicePath(disk);
    const tableType = state.sb.partEditor.tableType;
    const partedLabel = tableType === "mbr" ? "msdos" : "gpt";
    const freeGb = sbPartEditorFreeGb(disk, plan);

    const lines = [`parted -s ${device} mklabel ${partedLabel}`];
    let cursorMib = 1;
    for (let i = 0; i < plan.length; i++) {
        const p = plan[i];
        const partLabel = p.label || `part${i + 1}`;
        const start = `${cursorMib}MiB`;
        let end;
        if (p.useRest) {
            end = "100%";
        } else {
            const sizeMib = Math.max(1, Math.round(Number(p.sizeGb || 0) * 1024));
            end = `${cursorMib + sizeMib}MiB`;
            cursorMib += sizeMib;
        }
        if (partedLabel === "msdos") {
            lines.push(`parted -s ${device} mkpart primary ${p.filesystem} ${start} ${end}`);
        } else {
            lines.push(`parted -s ${device} mkpart "${partLabel}" ${p.filesystem} ${start} ${end}`);
        }
    }
    const isNvme = device.includes("nvme") || device.includes("mmcblk");
    for (let i = 0; i < plan.length; i++) {
        const p = plan[i];
        const partDev = isNvme ? `${device}p${i + 1}` : `${device}${i + 1}`;
        const labelFlag = p.label ? ` -L "${p.label}"` : "";
        lines.push(`mkfs.${p.filesystem}${labelFlag} ${partDev}`);
    }
    return lines;
}

function sbRenderPartEditorPreview(disk, plan) {
    const pe = state.sb.partEditor;
    const device = sbDiskDevicePath(disk);
    const lines = sbPartEditorBuildPreview(disk, plan);
    const hasResult = Boolean(pe.applyResult);
    const isOk = hasResult && pe.applyResult.startsWith("ok:");

    const resultHtml = hasResult ? `
        <div class="sb-pe-apply-result ${isOk ? "sb-pe-result-ok" : "sb-pe-result-err"}">
            <pre class="sb-pe-result-pre">${esc(pe.applyResult)}</pre>
        </div>` : "";

    const applyLabel = pe.applying ? "Wird ausgefuehrt…" : isOk ? "Fertig ✓" : "Jetzt anwenden";

    return `
        <div class="sb-pe-wrap">
            <div class="sb-pe-header">
                <button class="sb-pe-back-link" id="sb-pe-preview-back">← Zurueck zum Editor</button>
                <div class="sb-pe-title">Vorschau: Partitionierung ${esc(device)}</div>
                <div></div>
            </div>
            <div class="sb-pe-preview-section">
                <div class="sb-pe-section-title">Folgende Befehle werden ausgefuehrt:</div>
                <pre class="sb-pe-code">${esc(lines.join("\n"))}</pre>
            </div>
            <div class="sb-pe-warning-box">
                &#9888; Diese Aktion loescht ALLE Daten auf ${esc(device)}! Alle bestehenden Partitionen werden entfernt.
            </div>
            ${resultHtml}
            <div class="sb-pe-footer">
                <button class="sb-pe-btn" id="sb-pe-preview-back2" ${pe.applying || isOk ? "disabled" : ""}>← Zurueck</button>
                <button class="sb-pe-btn sb-pe-btn-danger" id="sb-pe-apply-btn" ${pe.applying || isOk ? "disabled" : ""}>${applyLabel}</button>
            </div>
        </div>`;
}

function sbRenderPartEditor(disk) {
    const pe = state.sb.partEditor;
    if (pe.showPreview) return sbRenderPartEditorPreview(disk, pe.plan);

    const device = sbDiskDevicePath(disk);
    const diskName = esc(disk.model || disk.name || device);
    const totalBytes = Math.max(1, Number(disk.size_bytes || 0));
    const totalGb = totalBytes / (1024 ** 3);
    const plan = pe.plan;
    const freeGb = sbPartEditorFreeGb(disk, plan);
    const hasRest = plan.some(p => p.useRest);
    const usedGb = totalGb - freeGb;

    const rows = plan.map((p, i) => {
        const color = SB_PE_PALETTE[i % SB_PE_PALETTE.length];
        const sizeStr = p.useRest
            ? `~${sbFormatBytes(freeGb * 1024 ** 3)} <span class="sb-pe-rest-tag">Rest</span>`
            : sbFormatBytes(Number(p.sizeGb || 0) * 1024 ** 3);
        return `<tr class="sb-pe-row">
            <td><span class="sb-pe-dot" style="background:${color};"></span>p${i + 1}</td>
            <td>${esc(p.label || "—")}</td>
            <td>${sizeStr}</td>
            <td>${esc(p.filesystem)}</td>
            <td><button class="sb-pe-rm-btn" data-pe-remove="${i}" title="Entfernen">&#x2715;</button></td>
        </tr>`;
    }).join("");

    const tableEmpty = !plan.length
        ? `<tr><td colspan="5" class="sb-pe-empty-row">Noch keine Partitionen geplant.</td></tr>`
        : "";

    const addForm = pe.addFormOpen ? `
        <div class="sb-pe-add-form">
            <input class="sb-pe-input" id="sb-pe-add-label" placeholder="Label (optional)" value="${esc(pe.addLabel || "")}">
            <div class="sb-pe-add-size-group">
                <input class="sb-pe-input sb-pe-input-sm" id="sb-pe-add-size" type="number" min="1" step="1" placeholder="GB" value="${esc(String(pe.addSizeGb || ""))}" ${pe.addUseRest ? "disabled" : ""}>
                <label class="sb-pe-rest-label"><input type="checkbox" id="sb-pe-add-rest" ${pe.addUseRest ? "checked" : ""}> Restlichen Speicher</label>
            </div>
            <select class="sb-pe-select" id="sb-pe-add-fs">
                ${["ext4","xfs","btrfs","vfat"].map(fs => `<option value="${fs}" ${pe.addFilesystem === fs ? "selected" : ""}>${fs}</option>`).join("")}
            </select>
            <div class="sb-pe-add-btns">
                <button class="sb-pe-btn sb-pe-btn-primary" id="sb-pe-add-confirm">Hinzufuegen</button>
                <button class="sb-pe-btn" id="sb-pe-add-cancel">Abbrechen</button>
            </div>
        </div>` : "";

    return `
        <div class="sb-pe-wrap">
            <div class="sb-pe-header">
                <button class="sb-pe-back-link" id="sb-pe-cancel">← Zurueck</button>
                <div class="sb-pe-title">Partitionieren: ${diskName} <span class="sb-pe-device-tag">${esc(device)}</span></div>
                <div class="sb-pe-table-sel">
                    <span class="sb-pe-table-label">Partitionstabelle:</span>
                    <select class="sb-pe-select" id="sb-pe-table-type">
                        <option value="gpt" ${pe.tableType === "gpt" ? "selected" : ""}>GPT</option>
                        <option value="mbr" ${pe.tableType === "mbr" ? "selected" : ""}>MBR</option>
                    </select>
                </div>
            </div>

            <div class="sb-pe-disk-stats">
                <span>Gesamt: <strong>${sbFormatBytes(totalBytes)}</strong></span>
                <span>Verplant: <strong>${sbFormatBytes(usedGb * 1024 ** 3)}</strong></span>
                <span>Verfuegbar: <strong>${sbFormatBytes(freeGb * 1024 ** 3)}</strong></span>
            </div>

            ${sbPartEditorBar(disk, plan)}

            <div class="sb-pe-plan-section">
                <div class="sb-pe-section-title">Partitions-Plan</div>
                <table class="sb-pe-table">
                    <thead><tr class="sb-pe-thead"><th>#</th><th>Label</th><th>Groesse</th><th>Filesystem</th><th></th></tr></thead>
                    <tbody>${tableEmpty}${rows}</tbody>
                </table>
            </div>

            <div class="sb-pe-add-section">
                ${!pe.addFormOpen ? `<button class="sb-pe-add-btn" id="sb-pe-add-open">+ Partition hinzufuegen</button>` : ""}
                ${addForm}
            </div>

            <div class="sb-pe-footer">
                <button class="sb-pe-btn" id="sb-pe-cancel2">Abbrechen</button>
                <button class="sb-pe-btn sb-pe-btn-primary" id="sb-pe-preview-btn" ${!plan.length ? "disabled" : ""}>Vorschau &amp; Bestaetigen &#8594;</button>
            </div>
        </div>`;
}

function sbPartEditorBind(root, disk) {
    const cancel = () => { state.sb.partEditor.open = false; renderDetail(); };
    root.querySelector("#sb-pe-cancel")?.addEventListener("click", cancel);
    root.querySelector("#sb-pe-cancel2")?.addEventListener("click", cancel);

    root.querySelector("#sb-pe-table-type")?.addEventListener("change", (e) => {
        state.sb.partEditor.tableType = e.target.value;
    });

    root.querySelectorAll("[data-pe-remove]").forEach(btn => {
        btn.addEventListener("click", () => {
            const idx = Number(btn.getAttribute("data-pe-remove"));
            state.sb.partEditor.plan.splice(idx, 1);
            renderDetail();
        });
    });

    root.querySelector("#sb-pe-add-open")?.addEventListener("click", () => {
        state.sb.partEditor.addFormOpen = true;
        state.sb.partEditor.addLabel = "";
        state.sb.partEditor.addSizeGb = "";
        state.sb.partEditor.addUseRest = false;
        state.sb.partEditor.addFilesystem = "ext4";
        renderDetail();
    });

    root.querySelector("#sb-pe-add-rest")?.addEventListener("change", (e) => {
        state.sb.partEditor.addUseRest = e.target.checked;
        const sizeInput = root.querySelector("#sb-pe-add-size");
        if (sizeInput) sizeInput.disabled = e.target.checked;
    });
    root.querySelector("#sb-pe-add-label")?.addEventListener("input", (e) => {
        state.sb.partEditor.addLabel = e.target.value;
    });
    root.querySelector("#sb-pe-add-size")?.addEventListener("input", (e) => {
        state.sb.partEditor.addSizeGb = e.target.value;
    });
    root.querySelector("#sb-pe-add-fs")?.addEventListener("change", (e) => {
        state.sb.partEditor.addFilesystem = e.target.value;
    });

    root.querySelector("#sb-pe-add-cancel")?.addEventListener("click", () => {
        state.sb.partEditor.addFormOpen = false;
        renderDetail();
    });

    root.querySelector("#sb-pe-add-confirm")?.addEventListener("click", () => {
        const pe = state.sb.partEditor;
        const freeGb = sbPartEditorFreeGb(disk, pe.plan);
        if (pe.addUseRest) {
            if (pe.plan.some(p => p.useRest)) {
                setFeedback("Es kann nur eine Partition den restlichen Speicher nutzen.", "warn");
                return;
            }
        } else {
            const gb = Number(pe.addSizeGb || 0);
            if (!gb || gb <= 0) {
                setFeedback("Bitte eine gueltige Groesse in GB eingeben.", "warn");
                return;
            }
            if (gb > freeGb + 0.001) {
                setFeedback(`Zu gross — verfuegbar: ${sbFormatBytes(freeGb * 1024 ** 3)}`, "warn");
                return;
            }
        }
        pe.plan.push({
            id: `pe-${Date.now()}`,
            label: String(pe.addLabel || "").trim(),
            sizeGb: pe.addUseRest ? null : Number(pe.addSizeGb),
            useRest: pe.addUseRest,
            filesystem: pe.addFilesystem || "ext4",
        });
        pe.addFormOpen = false;
        pe.addLabel = "";
        pe.addSizeGb = "";
        pe.addUseRest = false;
        renderDetail();
    });

    root.querySelector("#sb-pe-preview-btn")?.addEventListener("click", () => {
        if (!state.sb.partEditor.plan.length) return;
        state.sb.partEditor.showPreview = true;
        state.sb.partEditor.applyResult = "";
        renderDetail();
    });

    // Preview screen bindings
    const backFromPreview = () => { state.sb.partEditor.showPreview = false; renderDetail(); };
    root.querySelector("#sb-pe-preview-back")?.addEventListener("click", backFromPreview);
    root.querySelector("#sb-pe-preview-back2")?.addEventListener("click", backFromPreview);

    root.querySelector("#sb-pe-apply-btn")?.addEventListener("click", async () => {
        const pe = state.sb.partEditor;
        if (pe.applying) return;
        pe.applying = true;
        renderDetail();
        try {
            const freeGb = sbPartEditorFreeGb(disk, pe.plan);
            const partitions = pe.plan.map(p => ({
                label: p.label || "",
                size_gib: p.useRest ? null : Number(p.sizeGb),
                filesystem: p.filesystem,
            }));
            const res = await sbPartitionDisk({
                device: sbDiskDevicePath(disk),
                table_type: pe.tableType,
                partitions,
                dry_run: false,
            });
            const result = res?.result || res || {};
            if (result.ok === true) {
                pe.applyResult = "ok: Partitionierung erfolgreich ausgefuehrt.";
                setFeedback("Partitionierung abgeschlossen", "ok");
                await Promise.all([sbLoadAll(), sbLoadDisks()]);
            } else {
                pe.applyResult = "Fehler: " + (result.error || "Unbekannter Fehler");
                setFeedback(pe.applyResult, "err");
            }
        } catch (e) {
            pe.applyResult = "Fehler: " + (e.message || String(e));
            setFeedback(pe.applyResult, "err");
        } finally {
            pe.applying = false;
            renderDetail();
        }
    });
}

function renderStorageBrokerDetail() {
    const root = document.getElementById("mcp-detail");
    if (!root) return;

    const summary = state.sb.summary || {};
    const disks = Array.isArray(state.sb.disks) ? state.sb.disks : [];
    const activeTab = sbNormalizeActiveTab();

    if (!disks.length && !state.busy.sbLoadDisks) sbLoadDisks();

    const tree = sbBuildDiskTree(disks);
    const selectedId = String(state.sb.selectedDiskId || (disks[0]?.id ?? ""));
    const selectedDisk = tree.roots.find(d => String(d.id || "") === selectedId) || tree.roots[0] || null;
    const selectedPartId = String(state.sb.selectedPartId || "");

    // Partition editor takes over the whole panel
    if (state.sb.partEditor.open) {
        const peDiskId = state.sb.partEditor.diskId;
        const peDisk = tree.roots.find(d => String(d.id || "") === peDiskId) || selectedDisk;
        if (peDisk) {
            root.innerHTML = `<div class="sb-panel sb-panel-kde">${sbRenderPartEditor(peDisk)}</div>`;
            sbPartEditorBind(root, peDisk);
            return;
        }
        state.sb.partEditor.open = false;
    }

    if (activeTab !== "disks") {
        const managedPaths = Array.from(new Set([...(summary.managed_paths || []), ...(state.sb.managedPaths || [])]));
        let body = "";
        if (activeTab === "overview") body = sbRenderOverview(disks, summary, managedPaths);
        else if (activeTab === "managed_paths") body = sbRenderManagedPaths(summary);
        else if (activeTab === "policies") body = sbRenderPolicies(summary);
        else if (activeTab === "audit") body = sbRenderAudit();
        else if (activeTab === "setup") body = sbRenderSetup(disks);
        else body = sbRenderOverview(disks, summary, managedPaths);
        root.innerHTML = `
            <div class="sb-panel sb-panel-kde">
                ${sbKdeToolbar(activeTab)}
                <div class="sb-tab-scroll">${body}</div>
            </div>`;
        sbKdeBindToolbar(root, activeTab);
        return;
    }

    const policyKey = selectedDisk ? sbDiskPolicyKey(selectedDisk) : "blocked";
    const directTarget = sbResolveDirectActionTarget(selectedDisk, tree);
    const isMounted = Boolean(directTarget.mounted);
    const isSystemDisk = Boolean(selectedDisk?.is_system || String(selectedDisk?.zone || "") === "system" || policyKey === "blocked");

    root.innerHTML = `
        <div class="sb-panel sb-panel-kde">
            ${sbKdeToolbar(activeTab)}
            <div class="sb-kde-layout">
                <div class="sb-kde-sidebar">
                    <div class="sb-kde-section-label">Datentraeger</div>
                    <div class="sb-kde-disk-list" id="sb-kde-disk-list">
                        ${sbKdeRenderSidebar(tree.roots, selectedId)}
                    </div>
                </div>
                <div class="sb-kde-content">
                    <div class="sb-kde-part-bar-wrap">
                        <div class="sb-kde-bar sb-kde-bar-lg" id="sb-kde-part-bar">
                            ${sbKdeRenderDiskBar(selectedDisk, tree)}
                        </div>
                    </div>
                    <div class="sb-kde-table-wrap">
                        <table class="sb-kde-table" id="sb-kde-table">
                            ${sbKdeRenderPartTable(selectedDisk, tree)}
                        </table>
                    </div>
                    <div class="sb-kde-bottom">
                        <div class="sb-kde-info-panel" id="sb-kde-info">
                            ${sbKdeRenderInfoPanel(selectedDisk, selectedPartId, tree)}
                        </div>
                        <div class="sb-kde-actions-panel">
                            <div class="sb-kde-act-label">Aktionen</div>
                            <button class="sb-btn sb-btn-primary" data-sb-setup-start="services">Setup Wizard</button>
                            <button class="sb-btn" id="sb-kde-reload-btn">Neu laden</button>
                            <button class="sb-btn" id="sb-kde-unmount-btn" ${!isMounted || isSystemDisk ? "disabled" : ""}>Aushaengen</button>
                            <button class="sb-btn" id="sb-kde-policy-btn">Policy aendern</button>
                            <div class="sb-kde-act-label" style="margin-top:8px;">Gefaehrlich</div>
                            <button class="sb-btn sb-btn-danger" id="sb-kde-partition-btn" ${isSystemDisk || !selectedDisk ? "disabled" : ""}>Partitionieren&hellip;</button>
                            <button class="sb-btn sb-btn-danger" id="sb-kde-format-btn" ${isSystemDisk || !directTarget.device || directTarget.mounted ? "disabled" : ""}>Formatieren&hellip;</button>
                        </div>
                    </div>
                    <div class="sb-kde-output" id="sb-kde-output">
                        <div class="sb-kde-output-status">
                            <span class="sb-kde-status-dot ${state.sb.lastOutput ? "active" : ""}"></span>
                            <span class="sb-kde-status-label">${state.sb.lastOutput ? "Letzte Ausgabe" : "Bereit"}</span>
                        </div>
                        ${state.sb.lastOutput ? `<pre class="sb-output-pre">${esc(state.sb.lastOutput)}</pre>` : `<span class="sb-kde-hint">// Output erscheint hier&hellip;</span>`}
                    </div>
                </div>
            </div>
        </div>`;

    sbKdeBindToolbar(root, activeTab);

    root.querySelector("#sb-kde-reload-btn")?.addEventListener("click", async () => {
        try {
            await Promise.all([sbLoadAll(), sbLoadDisks()]);
            sbSetLastOutput("Storage neu geladen", `Datentraeger: ${tree.roots.length}`);
            renderDetail();
        } catch (error) {
            sbSetLastOutput("Reload fehlgeschlagen", error);
            setFeedback(`Reload fehlgeschlagen: ${error.message || error}`, "err");
            renderDetail();
        }
    });

    root.querySelectorAll(".sb-kde-disk-item").forEach(el => {
        el.addEventListener("click", () => {
            state.sb.selectedDiskId = String(el.getAttribute("data-disk-id") || "");
            state.sb.selectedPartId = "";
            renderDetail();
        });
    });

    root.querySelectorAll(".sb-kde-row").forEach(el => {
        el.addEventListener("click", () => {
            const pid = String(el.getAttribute("data-part-id") || "");
            state.sb.selectedPartId = pid;
            const infoPanel = root.querySelector("#sb-kde-info");
            if (infoPanel) infoPanel.innerHTML = sbKdeRenderInfoPanel(selectedDisk, pid, tree);
            root.querySelectorAll(".sb-kde-row").forEach(r => r.classList.remove("selected"));
            el.classList.add("selected");
            const seg = root.querySelector(`.sb-kde-seg[data-part-id="${pid}"]`);
            root.querySelectorAll(".sb-kde-seg").forEach(s => s.classList.remove("selected-seg"));
            if (seg) seg.classList.add("selected-seg");
        });
    });

    root.querySelectorAll(".sb-kde-seg[data-part-id]").forEach(seg => {
        seg.addEventListener("click", () => {
            const pid = String(seg.getAttribute("data-part-id") || "");
            state.sb.selectedPartId = pid;
            root.querySelectorAll(".sb-kde-seg").forEach(s => s.classList.remove("selected-seg"));
            seg.classList.add("selected-seg");
            const row = root.querySelector(`.sb-kde-row[data-part-id="${pid}"]`);
            root.querySelectorAll(".sb-kde-row").forEach(r => r.classList.remove("selected"));
            if (row) { row.classList.add("selected"); row.scrollIntoView({ block: "nearest" }); }
            const infoPanel = root.querySelector("#sb-kde-info");
            if (infoPanel) infoPanel.innerHTML = sbKdeRenderInfoPanel(selectedDisk, pid, tree);
        });
    });

    root.querySelector("#sb-kde-unmount-btn")?.addEventListener("click", async () => {
        if (!selectedDisk) return;
        if (directTarget.error) {
            setFeedback(directTarget.error, "warn");
            sbSetLastOutput("Unmount blockiert", directTarget.error);
            renderDetail();
            return;
        }
        try {
            const res = await sbUnmountDevice({ device: directTarget.device });
            const result = res?.result || res || {};
            const errText = String(result?.error || "").toLowerCase();
            if (result?.ok === true || errText.includes("not currently mounted")) {
                sbApplyUnmountLocalState(directTarget.device);
            }
            sbSetLastActionOutput("Unmount", res);
            await Promise.all([sbLoadAll(), sbLoadDisks()]);
            renderDetail();
        } catch (error) {
            sbSetLastOutput("Unmount fehlgeschlagen", error);
            setFeedback(`Unmount fehlgeschlagen: ${error.message || error}`, "err");
            renderDetail();
        }
    });

    root.querySelector("#sb-kde-partition-btn")?.addEventListener("click", () => {
        if (!selectedDisk || isSystemDisk) return;
        sbPartEditorOpen(String(selectedDisk.id || ""));
        renderDetail();
    });

    root.querySelector("#sb-kde-format-btn")?.addEventListener("click", async () => {
        if (!selectedDisk || isSystemDisk) return;
        if (directTarget.error) {
            setFeedback(directTarget.error, "warn");
            sbSetLastOutput("Format blockiert", directTarget.error);
            renderDetail();
            return;
        }
        if (directTarget.mounted) {
            const mountInfo = directTarget.mountpoints.join(", ") || directTarget.device;
            const message = `Ziel ist noch gemountet: ${mountInfo}`;
            setFeedback(message, "warn");
            sbSetLastOutput("Format blockiert", message);
            renderDetail();
            return;
        }
        const diskLabel = directTarget.label || selectedDisk.name || selectedDisk.device || String(selectedDisk.id || "Unbekannt");
        const confirmed = window.confirm(`Ziel "${diskLabel}" wirklich formatieren?\n\nAlle Daten gehen unwiderruflich verloren!`);
        if (!confirmed) return;
        const filesystem = String(window.prompt("Filesystem fuer die Formatierung:", "ext4") || "").trim().toLowerCase();
        if (!filesystem) {
            sbSetLastOutput("Format abgebrochen", "Kein Filesystem angegeben.");
            renderDetail();
            return;
        }
        const defaultLabel = String(directTarget.partition?.label || selectedDisk?.label || "").trim();
        const label = window.prompt("Label (optional):", defaultLabel);
        if (label === null) {
            sbSetLastOutput("Format abgebrochen", "Label-Eingabe abgebrochen.");
            renderDetail();
            return;
        }
        setBusy("sbAction", true);
        try {
            const res = await sbFormatDevice({
                device: directTarget.device,
                filesystem,
                label: String(label || "").trim(),
                dry_run: false,
            });
            sbSetLastActionOutput("Format", res);
            await Promise.all([sbLoadAll(), sbLoadDisks()]);
            setFeedback("Format ausgefuehrt", "ok");
            renderDetail();
        } catch (error) {
            sbSetLastOutput("Format fehlgeschlagen", error);
            setFeedback(`Format fehlgeschlagen: ${error.message || error}`, "err");
            renderDetail();
        } finally {
            setBusy("sbAction", false);
        }
    });

    root.querySelector("#sb-kde-policy-btn")?.addEventListener("click", async () => {
        if (!selectedDisk) return;
        const current = policyKey;
        const next = current === "managed_rw" ? "read_only" : current === "read_only" ? "blocked" : "managed_rw";
        try {
            const res = await sbSaveDiskPolicy(String(selectedDisk.id || ""), { policy_state: next });
            sbSetLastActionOutput("Policy geaendert", res);
            await Promise.all([sbLoadAll(), sbLoadDisks()]);
            setFeedback(`Policy auf ${next} gesetzt`, "ok");
            renderDetail();
        } catch (error) {
            sbSetLastOutput("Policy-Aenderung fehlgeschlagen", error);
            setFeedback(`Policy-Aenderung fehlgeschlagen: ${error.message || error}`, "err");
            renderDetail();
        }
    });
}

function sbKdeToolbar(activeTab) {
    const tabs = [
        { id: "disks", label: "Uebersicht" },
        { id: "managed_paths", label: "Pfade" },
        { id: "policies", label: "Policies" },
        { id: "audit", label: "Audit" },
    ];
    const tabBtns = tabs.map(t => `<button class="sb-kde-tb-btn${activeTab === t.id ? " active" : ""}" data-sb-kde-tab="${t.id}">${t.label}</button>`).join("");
    return `<div class="sb-kde-toolbar">
        ${tabBtns}
        <button class="sb-kde-tb-btn sb-kde-tb-wizard" data-sb-setup-start="services">+ Setup Wizard</button>
        <div style="margin-left:auto;">
            <input class="sb-kde-search" id="sb-kde-search" placeholder="Datentraeger suchen…" value="${esc(String(state.sb.diskSearch || ""))}" />
        </div>
    </div>`;
}

function sbKdeBindToolbar(root, activeTab) {
    root.querySelectorAll("[data-sb-kde-tab]").forEach(btn => {
        btn.addEventListener("click", () => {
            state.sb.activeTab = String(btn.getAttribute("data-sb-kde-tab") || "disks");
            renderDetail();
        });
    });

    root.querySelectorAll("[data-sb-setup-start]").forEach(btn => {
        btn.addEventListener("click", () => {
            state.sb.setup = { open: false, flow: "", step: 1, values: {}, result: "" };
            state.sb.activeTab = "setup";
            renderDetail();
        });
    });
    const searchInput = root.querySelector("#sb-kde-search");
    if (searchInput) {
        searchInput.addEventListener("input", () => {
            state.sb.diskSearch = searchInput.value;
            renderDetail();
        });
    }

    // Wizard: Flow-Karten Selektion — direkter Start, kein extra Button
    root.querySelectorAll("[data-wiz-flow]").forEach(card => {
        card.addEventListener("click", () => {
            const flow = String(card.getAttribute("data-wiz-flow") || "services");
            sbOpenSetup(flow);
        });
    });

    // Wizard: Disk Picker
    root.querySelectorAll("[data-wiz-disk]").forEach(choice => {
        choice.addEventListener("click", () => {
            root.querySelectorAll("[data-wiz-disk]").forEach(c => c.classList.remove("chosen"));
            choice.classList.add("chosen");
            const diskId = String(choice.getAttribute("data-wiz-disk") || "");
            if (state.sb.setup?.values) state.sb.setup.values.disk_id = diskId;
        });
    });

    root.querySelectorAll("[data-sb-field]").forEach((field) => {
        const eventName = field.type === "checkbox" || field.tagName === "SELECT" ? "change" : "input";
        field.addEventListener(eventName, () => {
            sbReadSetupFields(root);
            if (Number(state.sb.setup?.step || 1) === 2 && (field.type === "checkbox" || field.tagName === "SELECT")) {
                renderDetail();
            }
        });
    });

    root.querySelector("[data-sb-setup-cancel]")?.addEventListener("click", () => {
        sbCloseSetup();
    });
    root.querySelector("[data-sb-setup-back]")?.addEventListener("click", () => {
        sbReadSetupFields(root);
        state.sb.setup.step = Math.max(1, Number(state.sb.setup.step || 1) - 1);
        renderDetail();
    });
    root.querySelector("[data-sb-setup-next]")?.addEventListener("click", () => {
        sbReadSetupFields(root);
        const error = sbValidateSetupStep(state.sb.setup?.step || 1);
        if (error) {
            setFeedback(error, "warn");
            return;
        }
        state.sb.setup.step = Math.min(3, Number(state.sb.setup.step || 1) + 1);
        renderDetail();
    });
    root.querySelectorAll("[data-sb-setup-run]").forEach((btn) => {
        btn.addEventListener("click", () => {
            sbReadSetupFields(root);
            const error = sbValidateSetupStep(2);
            if (error) {
                setFeedback(error, "warn");
                return;
            }
            const modeValue = String(btn.getAttribute("data-sb-setup-run") || "dry");
            sbExecuteSetup(modeValue !== "apply");
        });
    });
    root.querySelector("[data-sb-setup-done]")?.addEventListener("click", () => {
        sbCloseSetup();
    });

    // Pfade: Filter chips
    root.querySelectorAll("[data-path-filter]").forEach(chip => {
        chip.addEventListener("click", () => {
            root.querySelectorAll("[data-path-filter]").forEach(c => c.classList.remove("active"));
            chip.classList.add("active");
            const filter = String(chip.getAttribute("data-path-filter") || "all");
            const cards = root.querySelectorAll(".sb-kde-path-card");
            cards.forEach(card => {
                const pathEl = card.querySelector(".sb-kde-path-fullpath");
                const p = String(pathEl?.textContent || "").toLowerCase();
                const badgeEl = card.querySelector(".sb-kde-path-badge");
                const role = String(badgeEl?.textContent || "").toLowerCase();
                const show = filter === "all"
                    || (filter === "backup" && p.includes("backup"))
                    || (filter === "media" && (p.includes("media") || p.includes("import")))
                    || (filter === "service" && !p.includes("backup") && !p.includes("media") && !p.includes("import"));
                card.style.display = show ? "" : "none";
            });
        });
    });

    // Pfade: Copy path
    root.querySelectorAll("[data-copy-path]").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const p = String(btn.getAttribute("data-copy-path") || "");
            navigator.clipboard?.writeText(p).catch(() => {});
            btn.textContent = "Kopiert!";
            setTimeout(() => { btn.textContent = "Kopieren"; }, 1500);
        });
    });

    // Pfade: Remove path
    root.querySelectorAll("[data-remove-path]").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const p = String(btn.getAttribute("data-remove-path") || "");
            if (!window.confirm(`Pfad "${p}" wirklich aus der Verwaltung entfernen?`)) return;
            const current = state.sb.settings?.managed_bases || [];
            const updated = current.filter(b => b !== p);
            sbSaveSettings({ managed_bases: updated }).then(() => sbLoadAll());
        });
    });

    // Policies: Sub-Tab switching
    root.querySelectorAll("[data-pol-subtab]").forEach(btn => {
        btn.addEventListener("click", () => {
            state.sb.policySubTab = String(btn.getAttribute("data-pol-subtab") || "disks");
            renderDetail();
        });
    });

    // Policies: Per-disk header toggle
    root.querySelectorAll("[data-pol-toggle]").forEach(hdr => {
        hdr.addEventListener("click", () => {
            const id = String(hdr.getAttribute("data-pol-toggle") || "");
            const body = root.querySelector(`#polbody-${id}`);
            const chev = root.querySelector(`#chev-${id}`);
            if (!body) return;
            const isOpen = body.classList.contains("open");
            body.classList.toggle("open", !isOpen);
            if (chev) chev.style.transform = isOpen ? "" : "rotate(180deg)";
        });
    });

    // Policies: Per-disk policy switcher
    root.querySelectorAll("[data-pol-disk]").forEach(btn => {
        btn.addEventListener("click", () => {
            const diskId = String(btn.getAttribute("data-pol-disk") || "");
            const newPolicy = String(btn.getAttribute("data-pol-value") || "");
            if (!diskId || !newPolicy) return;
            // Update visual immediately
            const switcher = root.querySelector(`#psw-${diskId}`);
            if (switcher) {
                switcher.querySelectorAll("[data-pol-disk]").forEach(b => {
                    b.className = "sb-pol-ps-btn";
                });
                btn.className = `sb-pol-ps-btn sb-pol-ps-${newPolicy === "managed_rw" ? "managed" : newPolicy === "read_only" ? "ro" : "blocked"}`;
            }
            // Update pill
            const disk = (state.sb.disks || []).find(d => String(d.id||"") === diskId);
            if (disk) disk.policy_state = newPolicy;
            // Save to backend
            sbSaveDiskPolicy(diskId, { policy_state: newPolicy }).then(() => sbLoadAll());
        });
    });

    // Policies: Save global settings
    root.querySelector("#sb-save-btn")?.addEventListener("click", () => {
        const draft = {
            ...(state.sb.settings || {}),
            external_default_policy: root.querySelector("#sb-ext-policy")?.value || "blocked",
            unknown_mount_default: root.querySelector("#sb-unknown-policy")?.value || "blocked",
            dry_run_default: Boolean(root.querySelector("#sb-dry-run")?.checked),
            requires_approval_for_writes: Boolean(root.querySelector("#sb-req-approval")?.checked),
        };
        state.sb.settings = draft;
        sbSaveSettings(draft).then(() => sbLoadAll()).catch(() => {});
    });

    // Policies: Add blocked path
    root.querySelector("#sb-bl-add-btn")?.addEventListener("click", () => {
        const input = root.querySelector("#sb-bl-input");
        const val = String(input?.value || "").trim();
        if (!val) return;
        const current = state.sb.settings?.blacklist_extra || [];
        if (!current.includes(val)) {
            sbSaveSettings({ blacklist_extra: [...current, val] }).then(() => sbLoadAll());
        }
        if (input) input.value = "";
    });

    // Policies: Remove blocked path
    root.querySelectorAll("[data-sb-remove-bl]").forEach(btn => {
        btn.addEventListener("click", () => {
            const i = Number(btn.getAttribute("data-sb-remove-bl"));
            const current = [...(state.sb.settings?.blacklist_extra || [])];
            current.splice(i, 1);
            sbSaveSettings({ blacklist_extra: current }).then(() => sbLoadAll());
        });
    });
}


export function renderStorageBrokerPanel(ctx) {
    syncRuntime(ctx);
    const root = document.getElementById("mcp-detail");
    if (!root) return;

    if (!state.sb.loaded) {
        sbLoadAll();
        root.innerHTML = `<div class="mcp-empty">Storage Broker wird geladen...</div>`;
        return;
    }

    if (!state.sb.disks.length && !state.busy.sbLoadDisks) {
        sbLoadDisks();
    }

    renderStorageBrokerDetail();
}
