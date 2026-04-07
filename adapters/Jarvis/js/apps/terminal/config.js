const HTTP_BASE = (() => {
    if (typeof window.getApiBase === "function") {
        const base = window.getApiBase();
        if (base) return base;
    }
    return `${window.location.protocol}//${window.location.host}`;
})();

const API = `${HTTP_BASE}/api/commander`;
const WS_URL = `${HTTP_BASE.replace(/^http/, "ws")}/api/commander/ws`;

const CLI_COMMANDS = [
    { cmd: 'help', desc: 'Show available commands' },
    { cmd: 'list', desc: 'List blueprints' },
    { cmd: 'deploy', desc: 'Deploy a blueprint: deploy <id>' },
    { cmd: 'restart', desc: 'Restart via blueprint: restart <container_id>' },
    { cmd: 'stop', desc: 'Stop a container: stop <id>' },
    { cmd: 'attach', desc: 'Attach to container: attach <id>' },
    { cmd: 'detach', desc: 'Detach from current container' },
    { cmd: 'exec', desc: 'Run command: exec <container> <cmd>' },
    { cmd: 'logs', desc: 'Show container logs: logs <id>' },
    { cmd: 'stats', desc: 'Show container stats: stats <id>' },
    { cmd: 'trion', desc: 'Analyze attached container or enter shell mode: trion <task>|shell' },
    { cmd: 'secrets', desc: 'List secrets' },
    { cmd: 'volumes', desc: 'List workspace volumes' },
    { cmd: 'snapshot', desc: 'Create snapshot: snapshot <volume>' },
    { cmd: 'restore', desc: 'Restore snapshot: restore <filename> [target_volume]' },
    { cmd: 'rmvolume', desc: 'Remove volume: rmvolume <volume_name>' },
    { cmd: 'quota', desc: 'Show resource quota' },
    { cmd: 'market', desc: 'Marketplace: market sync|list|install <id>' },
    { cmd: 'audit', desc: 'Show audit log' },
    { cmd: 'activity', desc: 'Show latest TRION activity events' },
    { cmd: 'clear', desc: 'Clear terminal output' },
    { cmd: 'cleanup', desc: 'Stop all containers' },
];

const COMMAND_GROUPS = [
    {
        category: 'Container',
        items: [
            { label: 'List Containers', run: 'list containers' },
            { label: 'Attach Container', run: 'attach ' },
            { label: 'Stop Container', run: 'stop ' },
            { label: 'Container Stats', run: 'stats ' },
            { label: 'TRION Shell Mode', run: 'trion shell' },
        ],
    },
    {
        category: 'Storage',
        items: [
            { label: 'List Volumes', run: 'volumes' },
            { label: 'Create Snapshot', run: 'snapshot ' },
            { label: 'Restore Snapshot', run: 'restore ' },
        ],
    },
    {
        category: 'Approval',
        items: [
            { label: 'Open Approval Center', run: 'activity' },
            { label: 'Refresh Approvals', run: 'activity' },
        ],
    },
    {
        category: 'Marketplace',
        items: [
            { label: 'Sync Catalog', run: 'market sync' },
            { label: 'List Catalog', run: 'market list' },
            { label: 'Install Blueprint', run: 'market install ' },
        ],
    },
];

function buildBlueprintPreset(type) {
    const suffix = Date.now().toString().slice(-6);
    const base = {
        id: `custom-${suffix}`,
        name: 'Custom Blueprint',
        description: '',
        icon: '📦',
        dockerfile: '',
        image: '',
        network: 'internal',
        tags: [],
        system_prompt: '',
        resources: {
            cpu_limit: '1.0',
            memory_limit: '512m',
            memory_swap: '1g',
            timeout_seconds: 300,
            pids_limit: 100,
        },
        mounts: [],
        secrets_required: [],
        allowed_exec: [],
    };

    const presets = {
        python: {
            id: `python-${suffix}`,
            name: 'Python Sandbox',
            icon: '🐍',
            image: 'python:3.12-slim',
            description: 'Python runtime with pip for scripts and analysis.',
            tags: ['python', 'sandbox'],
            allowed_exec: ['python', 'python3', 'pip', 'pip3', 'sh', 'bash'],
        },
        node: {
            id: `node-${suffix}`,
            name: 'Node Sandbox',
            icon: '🟢',
            image: 'node:20-slim',
            description: 'Node.js runtime for JS/TS tooling.',
            tags: ['node', 'javascript'],
            allowed_exec: ['node', 'npm', 'npx', 'sh', 'bash'],
        },
        db: {
            id: `db-${suffix}`,
            name: 'DB Workspace',
            icon: '🗄',
            image: 'postgres:16-alpine',
            description: 'Database-oriented environment for SQL tasks.',
            tags: ['database', 'sql'],
            network: 'internal',
        },
        shell: {
            id: `shell-${suffix}`,
            name: 'Shell Toolbox',
            icon: '🖥',
            image: 'alpine:latest',
            description: 'Minimal shell toolbox with system utilities.',
            tags: ['shell', 'tools'],
            allowed_exec: ['sh', 'ash', 'ls', 'cat', 'grep', 'echo', 'curl', 'wget'],
        },
        webscraper: {
            id: `web-scraper-${suffix}`,
            name: 'Web Scraper',
            icon: '🕷',
            image: 'python:3.12-slim',
            description: 'Requests + parsing workflows with controlled networking.',
            tags: ['scraping', 'python'],
            network: 'bridge',
            allowed_exec: ['python', 'python3', 'pip', 'sh', 'bash'],
        },
    };

    return { ...base, ...(presets[type] || {}) };
}

export {
    API,
    CLI_COMMANDS,
    COMMAND_GROUPS,
    HTTP_BASE,
    WS_URL,
    buildBlueprintPreset,
};
