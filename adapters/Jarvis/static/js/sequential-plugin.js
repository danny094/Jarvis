/**
 * ═══════════════════════════════════════════════════════════════
 * SEQUENTIAL THINKING PLUGIN v5.0
 * Event-based Observability with LIVE THINKING STREAM
 * ═══════════════════════════════════════════════════════════════
 * 
 * Architecture:
 * - Phase 1: thinking_stream events → Live thinking display
 * - Phase 2: sequential_step events → Step-by-step display
 * - Uses TRIONPanel API to visualize (NO business logic!)
 */

class SequentialThinkingPlugin {
    constructor(panel) {
        this.panel = panel;
        this.activeTasks = new Map();
        
        console.log('[SequentialPlugin] v5.0 Initialized - Live Thinking Support');
    }
    
    init() {
        window.addEventListener('sse-event', (e) => {
            const event = e.detail;
            
            switch(event.type) {
                case 'sequential_start':
                    this.handleStart(event);
                    break;
                case 'seq_thinking_stream':
                    this.handleThinkingStream(event);
                    break;
                case 'seq_thinking_done':
                    this.handleThinkingDone(event);
                    break;
                case 'sequential_step':
                    this.handleStep(event);
                    break;
                case 'sequential_done':
                    this.handleDone(event);
                    break;
                case 'sequential_error':
                    this.handleError(event);
                    break;
            }
        });
        
        console.log('[SequentialPlugin] Event listeners registered');
    }
    
    handleStart(event) {
        console.log('[SequentialPlugin] Starting task:', event.task_id);
        
        const { task_id, complexity, cim_modes, reasoning_type } = event;
        
        let content = '# Sequential Thinking\n\n';
        content += `**Task ID:** \`${task_id}\`\n`;
        content += `**Complexity:** ${complexity} steps\n`;
        if (cim_modes?.length > 0) {
            content += `**CIM Modes:** ${cim_modes.join(', ')}\n`;
        }
        content += `\n---\n\n`;
        content += `## 🤔 Thinking...\n\n`;
        content += `_Waiting for DeepSeek reasoning..._\n`;
        
        this.panel.createTab(
            task_id,
            `🧠 Thinking (${complexity})`,
            'markdown',
            { autoOpen: true, content: content }
        );
        
        this.activeTasks.set(task_id, {
            tabId: task_id,
            steps: [],
            startTime: Date.now(),
            complexity: complexity,
            thinkingContent: '',
            thinkingPhase: true
        });
    }
    
    handleThinkingStream(event) {
        const { task_id, chunk, total_length } = event;
        const task = this.activeTasks.get(task_id);
        
        if (!task) return;
        
        task.thinkingContent += chunk;
        
        // Format thinking for display
        const escapedThinking = this.escapeHtml(task.thinkingContent);
        
        let content = '# Sequential Thinking\n\n';
        content += `**Status:** 🤔 Thinking... (${total_length} chars)\n\n`;
        content += `---\n\n`;
        content += `## 🤔 DeepSeek Reasoning\n\n`;
        content += `\`\`\`\n${escapedThinking}\n\`\`\`\n\n`;
        content += `_Still thinking..._\n`;
        
        // Replace content (append=false)
        this.panel.updateContent(task_id, content, false);
    }
    
    handleThinkingDone(event) {
        const { task_id, total_length } = event;
        const task = this.activeTasks.get(task_id);
        
        if (!task) return;
        
        console.log(`[SequentialPlugin] Thinking done: ${total_length} chars`);
        
        task.thinkingPhase = false;
        
        let content = '# Sequential Thinking\n\n';
        content += `**Status:** 📊 Parsing steps...\n\n`;
        content += `---\n\n`;
        content += `**Thinking:** ${total_length} chars (collapsed below)\n\n`;
        content += `<details>\n`;
        content += `<summary>🤔 Click to see thinking process</summary>\n\n`;
        content += `\`\`\`\n${task.thinkingContent.substring(0, 3000)}${task.thinkingContent.length > 3000 ? '\n...(truncated)' : ''}\n\`\`\`\n`;
        content += `</details>\n\n`;
        content += `---\n\n`;
        content += `## Steps\n\n`;
        content += `_Parsing steps from analysis..._\n`;
        
        this.panel.updateContent(task_id, content, false);
    }
    
    handleStep(event) {
        const { task_id, step_number, title, thought } = event;
        const task = this.activeTasks.get(task_id);
        
        if (!task) {
            console.warn('[SequentialPlugin] Step for unknown task:', task_id);
            return;
        }
        
        console.log(`[SequentialPlugin] Step ${step_number}/${task.complexity}: ${title}`);
        
        task.steps.push({ step_number, title, thought });
        
        // Rebuild full content
        let content = '# Sequential Thinking\n\n';
        content += `**Status:** 🔄 Step ${step_number}/${task.complexity}\n\n`;
        content += `---\n\n`;
        
        if (task.thinkingContent) {
            content += `<details>\n`;
            content += `<summary>🤔 Thinking process</summary>\n\n`;
            content += `\`\`\`\n${task.thinkingContent.substring(0, 1500)}...\n\`\`\`\n`;
            content += `</details>\n\n`;
            content += `---\n\n`;
        }
        
        for (const step of task.steps) {
            content += `## Step ${step.step_number}: ${step.title}\n\n`;
            content += `${step.thought}\n\n`;
            content += `✅ Complete\n\n`;
            content += `---\n\n`;
        }
        
        this.panel.updateContent(task_id, content, false);
    }
    
    handleDone(event) {
        const { task_id, steps, thinking_length, summary } = event;
        const task = this.activeTasks.get(task_id);
        
        if (!task) return;
        
        const duration = ((Date.now() - task.startTime) / 1000).toFixed(1);
        
        console.log(`[SequentialPlugin] Done: ${task_id} in ${duration}s`);
        
        let content = '# Sequential Thinking ✅\n\n';
        content += `**Duration:** ${duration}s | **Steps:** ${steps.length}`;
        if (thinking_length) {
            content += ` | **Thinking:** ${thinking_length} chars`;
        }
        content += `\n\n---\n\n`;
        
        if (task.thinkingContent) {
            content += `<details>\n`;
            content += `<summary>🤔 Thinking process</summary>\n\n`;
            content += `\`\`\`\n${task.thinkingContent.substring(0, 2000)}${task.thinkingContent.length > 2000 ? '\n...' : ''}\n\`\`\`\n`;
            content += `</details>\n\n`;
            content += `---\n\n`;
        }
        
        for (const step of steps) {
            const stepNum = step.step || step.step_number;
            content += `## Step ${stepNum}: ${step.title}\n\n`;
            content += `${step.thought}\n\n`;
            content += `---\n\n`;
        }
        
        content += `## Summary\n\n`;
        content += `${summary}\n\n`;
        content += `✅ **Complete**\n`;
        
        this.panel.updateContent(task_id, content, false);
        
        this.activeTasks.delete(task_id);
    }
    
    handleError(event) {
        const { task_id, error } = event;
        const task = this.activeTasks.get(task_id);
        
        console.error('[SequentialPlugin] Error:', task_id, error);
        
        let content = '# Sequential Thinking ❌\n\n';
        content += `**Error:** ${error}\n\n`;
        
        if (task?.thinkingContent) {
            content += `---\n\n`;
            content += `<details>\n`;
            content += `<summary>🤔 Thinking before error</summary>\n\n`;
            content += `\`\`\`\n${task.thinkingContent}\n\`\`\`\n`;
            content += `</details>\n`;
        }
        
        if (task) {
            this.panel.updateContent(task_id, content, false);
            this.activeTasks.delete(task_id);
        } else {
            this.panel.createTab(task_id, '❌ Error', 'markdown', 
                { autoOpen: true, content: content });
        }
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Auto-init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        if (window.TRIONPanel) {
            window.sequentialPlugin = new SequentialThinkingPlugin(window.TRIONPanel);
            window.sequentialPlugin.init();
        }
    });
} else {
    if (window.TRIONPanel) {
        window.sequentialPlugin = new SequentialThinkingPlugin(window.TRIONPanel);
        window.sequentialPlugin.init();
    } else {
        setTimeout(() => {
            if (window.TRIONPanel) {
                window.sequentialPlugin = new SequentialThinkingPlugin(window.TRIONPanel);
                window.sequentialPlugin.init();
            }
        }, 100);
    }
}
