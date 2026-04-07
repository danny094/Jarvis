from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_terminal_logs_panel_supports_mode_split_and_activity_feed():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert 'data-log-mode="logs"' in src
    assert 'data-log-mode="shell"' in src
    assert 'id="term-activity-feed"' in src
    assert 'id="term-activity-list"' in src
    assert "function setLogPanelMode(mode)" in src


def test_terminal_routes_ws_output_by_stream_channel():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "function routeStreamOutput(msg)" in src
    assert "if (stream === 'logs')" in src
    assert "if (stream === 'shell')" in src
    assert "appendLogStream(data);" in src
    assert "appendShellStream(data);" in src


def test_terminal_includes_container_detail_drawer_endpoints():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "window.termOpenCtDetails = function(id)" in src
    assert "async function refreshContainerDetail()" in src
    assert "apiRequest(`/containers/${containerId}/logs?tail=180`, {}, 'Could not load logs')" in src
    assert "apiRequest(`/containers/${containerId}/stats`, {}, 'Could not load stats')" in src
    assert "apiRequest('/audit?limit=120', {}, 'Could not load audit log')" in src


def test_terminal_container_stats_support_openable_service_links():
    src = _read("adapters/Jarvis/js/apps/terminal/containers.js")
    assert "stats?.connection?.access_links" in src
    assert "target=\"_blank\"" in src
    assert "Open Desktop GUI" in _read("container_commander/engine.py")


def test_terminal_includes_volume_snapshot_manager_endpoints():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "apiRequest('/volumes', {}, 'Could not load volumes')" in src
    assert "apiRequest('/snapshots', {}, 'Could not load snapshots')" in src
    assert "apiRequest('/snapshots/create', {" in src
    assert "apiRequest('/snapshots/restore', {" in src
    assert "apiRequest(`/volumes/${encodeURIComponent(volumeName)}`, { method: 'DELETE' }, 'Could not remove volume')" in src


def test_terminal_supports_slash_quick_commands():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "function getQuickCommands()" in src
    assert "function normalizeQuickCommand(cmd)" in src
    assert "if (parts.length === 1 && first.startsWith('/'))" in src


def test_terminal_has_dashboard_home_with_kpis_timeline_and_continue():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert 'data-tab="dashboard"' in src
    assert 'id="panel-dashboard"' in src
    assert 'id="dash-kpis"' in src
    assert 'id="dash-timeline"' in src
    assert 'id="dash-recent-blueprints"' in src
    assert "async function loadDashboard()" in src


def test_terminal_blueprint_ux_has_presets_inline_validation_and_export_download():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    config_src = _read("adapters/Jarvis/js/apps/terminal/config.js")
    assert 'class="bp-preset-btn" data-preset="python"' in src
    assert "function buildBlueprintPreset(type)" in config_src
    assert "function validateBlueprintFieldLive(fieldId)" in src
    assert "downloadText(`${id}.yaml`, yaml);" in src


def test_terminal_power_user_features_include_palette_history_sessions_and_clean_log_export():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    helpers_src = _read("adapters/Jarvis/js/apps/terminal/helpers.js")
    assert 'id="term-command-palette"' in src
    assert "function toggleCommandPalette(force = null)" in src
    assert 'id="term-history-filter"' in src
    assert "function renderHistoryList()" in src
    assert "function renderShellSessions()" in src
    assert "function stripAnsi(input)" in helpers_src
    assert "function downloadLogs()" in src


def test_terminal_approval_and_trust_ux_includes_batch_context_and_trust_panel():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert 'id="approval-center-context"' in src
    assert "function approvalReason(item)" in src
    assert "function approvalRisk(item)" in src
    assert "function renderApprovalContextCard()" in src
    assert "risk_flags" in src
    assert "risk_reasons" in src
    assert "network_mode" in src
    assert "approval-batch-approve" in src
    assert "class=\"bp-preflight-trust\"" in src
    assert "function deriveTrustInfo(blueprint)" in src


def test_terminal_index_serves_xterm_assets_locally_not_via_cdn():
    src = _read("adapters/Jarvis/index.html")
    assert "static/vendor/xterm/xterm.css" in src
    assert "static/vendor/xterm/xterm.js" in src
    assert "static/vendor/xterm/xterm-addon-fit.js" in src
    assert "cdn.jsdelivr.net/npm/xterm" not in src


def test_terminal_normalizes_line_endings_for_xterm_and_plain_output():
    helpers = _read("adapters/Jarvis/js/apps/terminal/helpers.js")
    xterm = _read("adapters/Jarvis/js/apps/terminal/xterm.js")
    terminal = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "function normalizeTerminalOutput(input, options = {})" in helpers
    assert "return text.replace(/\\r?\\n/g, '\\r\\n');" in helpers
    assert "xterm.write(normalizeTerminalOutput(data, { forXterm: true }));" in xterm
    assert "const normalized = normalizeTerminalOutput(msg, { forXterm: true });" in xterm
    assert 'xterm.write(`${code}${normalized}${reset}\\r\\n`);' in xterm
    assert "const normalized = normalizeTerminalOutput(data);" in terminal
