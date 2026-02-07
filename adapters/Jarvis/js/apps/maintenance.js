/**
 * maintenance.js - Memory Maintenance App
 * Shows STM/MTM/LTM stats, graph info, and maintenance tasks
 */

import { getApiBase } from "../../static/js/api.js";
import { log } from "../../static/js/debug.js";

const els = {
    container: document.getElementById('maintenance-content')
};

export function initMaintenanceApp() {
    renderUI();
    loadStats();
}

function renderUI() {
    if (!els.container) return;

    els.container.innerHTML = `
        <!-- Memory Stats -->
        <div class="grid grid-cols-5 gap-3 mb-4">
            <div class="bg-dark-bg p-3 rounded-lg border border-dark-border text-center">
                <div id="stat-stm" class="text-2xl font-bold text-orange-400">-</div>
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mt-1">STM</div>
            </div>
            <div class="bg-dark-bg p-3 rounded-lg border border-dark-border text-center">
                <div id="stat-mtm" class="text-2xl font-bold text-blue-400">-</div>
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mt-1">MTM</div>
            </div>
            <div class="bg-dark-bg p-3 rounded-lg border border-dark-border text-center">
                <div id="stat-ltm" class="text-2xl font-bold text-green-400">-</div>
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mt-1">LTM</div>
            </div>
            <div class="bg-dark-bg p-3 rounded-lg border border-dark-border text-center">
                <div id="stat-nodes" class="text-2xl font-bold text-purple-400">-</div>
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mt-1">Nodes</div>
            </div>
            <div class="bg-dark-bg p-3 rounded-lg border border-dark-border text-center">
                <div id="stat-edges" class="text-2xl font-bold text-purple-400">-</div>
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mt-1">Edges</div>
            </div>
        </div>

        <!-- Conversations -->
        <div class="flex items-center gap-2 mb-4 px-1">
            <span class="text-xs text-gray-500">Conversations:</span>
            <span id="stat-convos" class="text-xs text-gray-300 font-mono">-</span>
            <span class="text-xs text-gray-600 ml-auto">Worker:</span>
            <span id="stat-worker" class="text-xs font-mono text-green-500">idle</span>
        </div>

        <!-- Tasks & Actions -->
        <div class="grid grid-cols-2 gap-4">
            <div class="bg-dark-bg p-4 rounded-lg border border-dark-border">
                <h3 class="font-bold text-gray-200 mb-2 text-sm">Optimization Tasks</h3>
                <div class="space-y-2">
                    <label class="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked value="duplicates" class="accent-accent-primary">
                        <span class="text-sm text-gray-400">Remove Duplicates</span>
                    </label>
                    <label class="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked value="promote" class="accent-accent-primary">
                        <span class="text-sm text-gray-400">Promote to LTM</span>
                    </label>
                    <label class="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked value="summarize" class="accent-accent-primary">
                        <span class="text-sm text-gray-400">Summarize Clusters</span>
                    </label>
                    <label class="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked value="graph" class="accent-accent-primary">
                        <span class="text-sm text-gray-400">Rebuild Graph</span>
                    </label>
                </div>
            </div>
            
            <div class="flex flex-col justify-center gap-3">
                <button id="start-maintenance-btn" class="w-full py-3 bg-accent-primary hover:bg-orange-500 text-black font-bold text-lg rounded-xl transition-all shadow-[0_0_15px_rgba(255,179,2,0.3)] hover:scale-[1.02]">
                    Start Optimization
                </button>
                <button id="refresh-stats-btn" class="w-full py-2 bg-dark-hover hover:bg-dark-border text-gray-300 font-medium rounded-lg transition-all border border-dark-border">
                    ↻ Refresh Stats
                </button>
                <button id="reset-memory-btn" class="w-full py-2 bg-red-900/30 hover:bg-red-900/50 text-red-400 border border-red-900/50 font-medium rounded-lg transition-all text-sm">
                    Reset Memory (Graph)
                </button>
            </div>
        </div>

        <!-- Progress Area (hidden by default) -->
        <div id="maintenance-progress" class="hidden space-y-2 mt-4">
            <div class="flex justify-between text-xs uppercase tracking-wider text-gray-500 font-mono">
                <span id="progress-phase">Initializing...</span>
                <span id="progress-percent">0%</span>
            </div>
            <div class="h-2 w-full bg-dark-bg rounded-full overflow-hidden border border-dark-border">
                <div id="progress-bar" class="h-full bg-accent-primary w-0 transition-all duration-300 relative overflow-hidden">
                    <div class="absolute inset-0 bg-white/20 animate-[shimmer_2s_infinite]"></div>
                </div>
            </div>
            <div id="progress-logs" class="h-32 bg-black/50 rounded border border-dark-border p-2 font-mono text-[10px] text-gray-400 overflow-y-auto"></div>
        </div>

        <!-- Results (hidden by default) -->
        <div id="maintenance-results" class="hidden mt-4 bg-green-900/20 border border-green-900/50 rounded-lg p-4">
            <h4 class="text-green-400 font-bold text-sm mb-2">Results</h4>
            <div class="grid grid-cols-3 gap-2 text-xs text-gray-300">
                <div>Duplicates: <span id="result-dupes" class="text-white font-mono">0</span></div>
                <div>Promoted: <span id="result-promoted" class="text-white font-mono">0</span></div>
                <div>Summaries: <span id="result-summaries" class="text-white font-mono">0</span></div>
                <div>Deleted: <span id="result-deleted" class="text-white font-mono">0</span></div>
                <div>Edges pruned: <span id="result-edges" class="text-white font-mono">0</span></div>
            </div>
        </div>
    `;

    document.getElementById('start-maintenance-btn').addEventListener('click', startMaintenance);
    document.getElementById('reset-memory-btn').addEventListener('click', resetMemory);
    document.getElementById('refresh-stats-btn').addEventListener('click', loadStats);
}

async function loadStats() {
    try {
        const res = await fetch(`${getApiBase()}/api/maintenance/status`);
        const data = await res.json();
        
        const mem = data.memory || {};
        document.getElementById('stat-stm').textContent = mem.stm_entries ?? 0;
        document.getElementById('stat-mtm').textContent = mem.mtm_entries ?? 0;
        document.getElementById('stat-ltm').textContent = mem.ltm_entries ?? 0;
        document.getElementById('stat-nodes').textContent = mem.graph_nodes ?? 0;
        document.getElementById('stat-edges').textContent = mem.graph_edges ?? 0;
        document.getElementById('stat-convos').textContent = mem.conversations ?? 0;
        
        const worker = data.worker || {};
        const workerEl = document.getElementById('stat-worker');
        workerEl.textContent = worker.state || 'idle';
        workerEl.className = `text-xs font-mono ${worker.state === 'idle' ? 'text-green-500' : 'text-orange-400'}`;
        
        log("info", "Memory stats loaded", mem);
    } catch (e) {
        log("error", `Stats load failed: ${e.message}`);
    }
}

async function resetMemory() {
    if (!confirm("⚠️ ACHTUNG: Dies löscht das gesamte Langzeitgedächtnis (Graph) unwiderruflich!\n\nFortfahren?")) return;

    const btn = document.getElementById('reset-memory-btn');
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = "Resetting...";

    try {
        const res = await fetch(`${getApiBase()}/api/maintenance/clear`, { method: 'POST' });
        if (!res.ok) throw new Error("Reset failed");
        btn.textContent = "✓ Cleared!";
        loadStats();
        setTimeout(() => { btn.innerHTML = orig; btn.disabled = false; }, 2000);
    } catch (e) {
        alert("Error: " + e.message);
        btn.innerHTML = orig;
        btn.disabled = false;
    }
}

async function startMaintenance() {
    const btn = document.getElementById('start-maintenance-btn');
    const tasks = Array.from(document.querySelectorAll('#maintenance-content input[type="checkbox"]:checked')).map(cb => cb.value);
    if (tasks.length === 0) return;

    btn.disabled = true;
    btn.classList.add('opacity-50');
    btn.textContent = "Running...";

    const progressArea = document.getElementById('maintenance-progress');
    const resultsArea = document.getElementById('maintenance-results');
    progressArea.classList.remove('hidden');
    resultsArea.classList.add('hidden');

    const logs = document.getElementById('progress-logs');
    const bar = document.getElementById('progress-bar');
    const phaseEl = document.getElementById('progress-phase');
    const percentEl = document.getElementById('progress-percent');
    logs.innerHTML = '';

    const addLog = (msg) => {
        const line = document.createElement('div');
        line.textContent = `> ${msg}`;
        logs.appendChild(line);
        logs.scrollTop = logs.scrollHeight;
    };

    try {
        addLog(`Starting tasks: ${tasks.join(', ')}`);
        const response = await fetch(`${getApiBase()}/api/maintenance/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tasks })
        });

        if (!response.ok) throw new Error("Connection failed");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value);
            for (const line of chunk.split('\n')) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const data = JSON.parse(line.slice(6));
                    if (data.type === 'stream_end') break;
                    if (data.phase) phaseEl.textContent = data.phase;
                    if (data.progress != null) {
                        bar.style.width = `${data.progress}%`;
                        percentEl.textContent = `${Math.round(data.progress)}%`;
                    }
                    if (data.message) addLog(data.message);
                    if (data.type === 'completed' && data.stats) {
                        const a = data.stats.actions || {};
                        resultsArea.classList.remove('hidden');
                        document.getElementById('result-dupes').textContent = (a.duplicates_found || 0);
                        document.getElementById('result-promoted').textContent = (a.promoted_to_ltm || 0);
                        document.getElementById('result-summaries').textContent = (a.summaries_created || 0);
                        document.getElementById('result-deleted').textContent = (a.entries_deleted || 0);
                        document.getElementById('result-edges').textContent = (a.edges_pruned || 0);
                    }
                } catch (_) {}
            }
        }

        addLog("✅ Complete.");
        bar.style.width = '100%';
        percentEl.textContent = '100%';
        loadStats();

    } catch (e) {
        addLog(`❌ Error: ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.classList.remove('opacity-50');
        btn.textContent = "Start Optimization";
    }
}
