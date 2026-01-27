/**
 * ═══════════════════════════════════════════════════════════════
 * SEQUENTIAL THINKING PLUGIN v6.0
 * Refactored for PluginManager Interface
 * ═══════════════════════════════════════════════════════════════
 */

const MANIFEST = {
    id: 'sequential-thinking',
    name: 'Sequential Thinking',
    version: '6.0.0',
    description: 'Visualizes DeepSeek reasoning process in TRION panel',
    author: 'Jarvis Team',
    icon: 'brain'
};

class SequentialThinkingPlugin extends PluginBase {
    constructor(panel, manager) {
        super(panel, manager);
        this.activeTasks = new Map();
        this.eventHandler = null;
        this.settings = {
            autoOpen: true,
            showThinking: true,
            truncateLength: 3000
        };
    }
    
    init() {
        console.log('[SequentialPlugin] v6.0 Initializing...');
        this.eventHandler = (e) => this.handleSSEEvent(e);
        window.addEventListener('sse-event', this.eventHandler);
        console.log('[SequentialPlugin] Event listeners registered');
    }
    
    destroy() {
        console.log('[SequentialPlugin] Destroying...');
        if (this.eventHandler) {
            window.removeEventListener('sse-event', this.eventHandler);
            this.eventHandler = null;
        }
        for (const [taskId] of this.activeTasks) {
            if (this.panel) {
                this.panel.closeTab(taskId);
            }
        }
        this.activeTasks.clear();
    }
    
    getSettings() {
        return [
            {
                key: 'autoOpen',
                label: 'Auto-open Panel',
                type: 'toggle',
                default: true,
                description: 'Automatically open TRION panel when thinking starts'
            },
            {
                key: 'showThinking',
                label: 'Show Thinking Process',
                type: 'toggle',
                default: true,
                description: 'Display raw thinking stream from DeepSeek'
            },
            {
                key: 'truncateLength',
                label: 'Thinking Truncate Length',
                type: 'number',
                default: 3000,
                min: 500,
                max: 10000,
                description: 'Maximum characters to show in thinking preview'
            }
        ];
    }
    
    onSettingChange(key, value) {
        this.settings[key] = value;
        console.log(`[SequentialPlugin] Setting changed: ${key} = ${value}`);
    }
    
    handleSSEEvent(e) {
        const event = e.detail;
        switch(event.type) {
            case 'sequential_start': this.handleStart(event); break;
            case 'seq_thinking_stream': this.handleThinkingStream(event); break;
            case 'seq_thinking_done': this.handleThinkingDone(event); break;
            case 'sequential_step': this.handleStep(event); break;
            case 'sequential_done': this.handleDone(event); break;
            case 'sequential_error': this.handleError(event); break;
        }
    }
    
    handleStart(event) {
        const { task_id, complexity, cim_modes } = event;
        console.log('[SequentialPlugin] Starting task:', task_id);
        
        let content = '# Sequential Thinking\n\n';
        content += `**Task ID:** \`${task_id}\`\n`;
        content += `**Complexity:** ${complexity} steps\n`;
        if (cim_modes?.length > 0) content += `**CIM Modes:** ${cim_modes.join(', ')}\n`;
        content += `\n---\n\n## 🤔 Thinking...\n\n_Waiting for DeepSeek reasoning..._\n`;
        
        this.panel.createTab(task_id, `🧠 Thinking (${complexity})`, 'markdown', 
            { autoOpen: this.settings.autoOpen, content });
        
        this.activeTasks.set(task_id, {
            tabId: task_id, steps: [], startTime: Date.now(),
            complexity, thinkingContent: '', thinkingPhase: true
        });
    }
    
    handleThinkingStream(event) {
        if (!this.settings.showThinking) return;
        const { task_id, chunk, total_length } = event;
        const task = this.activeTasks.get(task_id);
        if (!task) return;
        
        task.thinkingContent += chunk;
        const escaped = this.escapeHtml(task.thinkingContent);
        
        let content = `# Sequential Thinking\n\n**Status:** 🤔 Thinking... (${total_length} chars)\n\n---\n\n`;
        content += `## 🤔 DeepSeek Reasoning\n\n\`\`\`\n${escaped}\n\`\`\`\n\n_Still thinking..._\n`;
        this.panel.updateContent(task_id, content, false);
    }
    
    handleThinkingDone(event) {
        const { task_id, total_length } = event;
        const task = this.activeTasks.get(task_id);
        if (!task) return;
        
        console.log(`[SequentialPlugin] Thinking done: ${total_length} chars`);
        task.thinkingPhase = false;
        
        const truncLen = this.settings.truncateLength;
        let content = `# Sequential Thinking\n\n**Status:** 📊 Parsing steps...\n\n---\n\n`;
        content += `**Thinking:** ${total_length} chars (collapsed below)\n\n`;
        content += `<details><summary>🤔 Click to see thinking process</summary>\n\n`;
        content += `\`\`\`\n${task.thinkingContent.substring(0, truncLen)}${task.thinkingContent.length > truncLen ? '\n...(truncated)' : ''}\n\`\`\`\n</details>\n\n`;
        content += `---\n\n## Steps\n\n_Parsing steps from analysis..._\n`;
        this.panel.updateContent(task_id, content, false);
    }
    
    handleStep(event) {
        const { task_id, step_number, title, thought } = event;
        const task = this.activeTasks.get(task_id);
        if (!task) return;
        
        console.log(`[SequentialPlugin] Step ${step_number}/${task.complexity}: ${title}`);
        task.steps.push({ step_number, title, thought });
        
        const truncLen = this.settings.truncateLength;
        let content = `# Sequential Thinking\n\n**Status:** 🔄 Step ${step_number}/${task.complexity}\n\n---\n\n`;
        if (task.thinkingContent) {
            content += `<details><summary>🤔 Thinking process</summary>\n\n\`\`\`\n${task.thinkingContent.substring(0, Math.floor(truncLen/2))}...\n\`\`\`\n</details>\n\n---\n\n`;
        }
        for (const step of task.steps) {
            content += `## Step ${step.step_number}: ${step.title}\n\n${step.thought}\n\n✅ Complete\n\n---\n\n`;
        }
        this.panel.updateContent(task_id, content, false);
    }
    
    handleDone(event) {
        const { task_id, steps, thinking_length, summary } = event;
        const task = this.activeTasks.get(task_id);
        if (!task) return;
        
        const duration = ((Date.now() - task.startTime) / 1000).toFixed(1);
        console.log(`[SequentialPlugin] Done: ${task_id} in ${duration}s`);
        
        const truncLen = this.settings.truncateLength;
        let content = `# Sequential Thinking ✅\n\n**Duration:** ${duration}s | **Steps:** ${steps.length}`;
        if (thinking_length) content += ` | **Thinking:** ${thinking_length} chars`;
        content += `\n\n---\n\n`;
        
        if (task.thinkingContent) {
            content += `<details><summary>🤔 Thinking process</summary>\n\n\`\`\`\n${task.thinkingContent.substring(0, truncLen)}${task.thinkingContent.length > truncLen ? '\n...' : ''}\n\`\`\`\n</details>\n\n---\n\n`;
        }
        for (const step of steps) {
            const stepNum = step.step || step.step_number;
            content += `## Step ${stepNum}: ${step.title}\n\n${step.thought}\n\n---\n\n`;
        }
        content += `## Summary\n\n${summary}\n\n✅ **Complete**\n`;
        this.panel.updateContent(task_id, content, false);
        this.activeTasks.delete(task_id);
    }
    
    handleError(event) {
        const { task_id, error } = event;
        const task = this.activeTasks.get(task_id);
        console.error('[SequentialPlugin] Error:', task_id, error);
        
        let content = `# Sequential Thinking ❌\n\n**Error:** ${error}\n\n`;
        if (task?.thinkingContent) {
            content += `---\n\n<details><summary>🤔 Thinking before error</summary>\n\n\`\`\`\n${task.thinkingContent}\n\`\`\`\n</details>\n`;
        }
        if (task) {
            this.panel.updateContent(task_id, content, false);
            this.activeTasks.delete(task_id);
        } else {
            this.panel.createTab(task_id, '❌ Error', 'markdown', { autoOpen: true, content });
        }
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Register with PluginManager
if (window.PluginManager) {
    window.PluginManager.registerBuiltIn(MANIFEST, SequentialThinkingPlugin);
} else {
    window.addEventListener('DOMContentLoaded', () => {
        if (window.PluginManager) {
            window.PluginManager.registerBuiltIn(MANIFEST, SequentialThinkingPlugin);
        }
    });
}
