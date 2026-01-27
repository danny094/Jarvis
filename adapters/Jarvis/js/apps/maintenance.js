/**
 * maintenance.js - Memory Maintenance App
 * connect to /api/maintenance/start via SSE
 */

import { getApiBase } from "../../static/js/api.js";
import { log } from "../../static/js/debug.js";

const els = {
    // We assume these elements exist in the modal or app view
    // Since it's currently a Modal triggered from Launchpad, we need to inject content dynamically
    container: document.getElementById('maintenance-content')
};

/**
 * Initialize Maintenance UI
 * Called when the modal opens
 */
export function initMaintenanceApp() {
    renderUI();
}

function renderUI() {
    if (!els.container) return; // Should not happen if modal is open via shell

    els.container.innerHTML = `
        <div class="space-y-6">
            <div class="grid grid-cols-2 gap-4">
                <div class="bg-dark-bg p-4 rounded-lg border border-dark-border">
                    <h3 class="font-bold text-gray-200 mb-2">Tasks</h3>
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
                    </div>
                </div>
                
                <div class="flex flex-col justify-center gap-3">
                    <button id="start-maintenance-btn" class="w-full py-3 bg-accent-primary hover:bg-orange-500 text-black font-bold text-lg rounded-xl transition-all shadow-[0_0_15px_rgba(255,179,2,0.3)] hover:scale-[1.02]">
                        Start Optimization
                    </button>
                     <button id="reset-memory-btn" class="w-full py-2 bg-red-900/30 hover:bg-red-900/50 text-red-400 border border-red-900/50 font-medium rounded-lg transition-all">
                        <i data-lucide="trash-2" class="w-4 h-4 inline-block mr-2"></i>
                        Reset Memory (Graph)
                    </button>
                </div>
            </div>

            <!-- Progress Area -->
            <div id="maintenance-progress" class="hidden space-y-2">
                <div class="flex justify-between text-xs uppercase tracking-wider text-gray-500 font-mono">
                    <span id="progress-phase">Initializing...</span>
                    <span id="progress-percent">0%</span>
                </div>
                <div class="h-2 w-full bg-dark-bg rounded-full overflow-hidden border border-dark-border">
                    <div id="progress-bar" class="h-full bg-accent-primary w-0 transition-all duration-300 relative overflow-hidden">
                        <div class="absolute inset-0 bg-white/20 animate-[shimmer_2s_infinite]"></div>
                    </div>
                </div>
                <div id="progress-logs" class="h-32 bg-black/50 rounded border border-dark-border p-2 font-mono text-[10px] text-gray-400 overflow-y-auto">
                    <!-- Logs go here -->
                </div>
            </div>
        </div>
    `;

    document.getElementById('start-maintenance-btn').addEventListener('click', startMaintenance);
    document.getElementById('reset-memory-btn').addEventListener('click', resetMemory);
}

async function resetMemory() {
    if (!confirm("⚠️ ACHTUNG: Dies löscht das gesamte Langzeitgedächtnis (Graph) unwiderruflich!\n\nFortfahren?")) return;

    const btn = document.getElementById('reset-memory-btn');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = "Resetting...";

    try {
        const res = await fetch(`${getApiBase()}/api/maintenance/clear`, {
            method: 'POST'
        });

        if (!res.ok) throw new Error("Reset failed");

        btn.textContent = "Memory Cleared!";
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }, 2000);

    } catch (e) {
        alert("Error: " + e.message);
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function startMaintenance() {
    const btn = document.getElementById('start-maintenance-btn');
    const tasks = Array.from(document.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);

    // UI State
    btn.disabled = true;
    btn.classList.add('opacity-50', 'cursor-not-allowed');
    btn.textContent = "Running...";

    const progressArea = document.getElementById('maintenance-progress');
    progressArea.classList.remove('hidden');

    const logs = document.getElementById('progress-logs');
    const bar = document.getElementById('progress-bar');
    const phaseEl = document.getElementById('progress-phase');

    logs.innerHTML = '';

    // Add log helper
    const addLog = (msg) => {
        const line = document.createElement('div');
        line.textContent = `> ${msg}`;
        logs.appendChild(line);
        logs.scrollTop = logs.scrollHeight;
    };

    try {
        addLog("Connecting to Memory Worker...");

        // Fetch with ReadableStream
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
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const jsonStr = line.slice(6);
                    if (!jsonStr) continue;

                    try {
                        const data = JSON.parse(jsonStr);

                        // Handle Loop End
                        if (data.type === 'stream_end') break;

                        // UI Updates
                        if (data.phase) phaseEl.textContent = data.phase;
                        if (data.progress) bar.style.width = `${data.progress}%`;
                        if (data.message) addLog(data.message);
                        if (data.logs) data.logs.forEach(l => addLog(l));

                    } catch (e) {
                        // ignore keepalives or broken json
                    }
                }
            }
        }

        addLog("Maintenance Complete.");
        bar.style.width = '100%';
        btn.textContent = "Done";
        setTimeout(() => {
            btn.disabled = false;
            btn.classList.remove('opacity-50', 'cursor-not-allowed');
            btn.textContent = "Start Optimization";
        }, 2000);

    } catch (e) {
        addLog(`Error: ${e.message}`);
        btn.textContent = "Failed";
    }
}
