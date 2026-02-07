/**
 * Sequential Thinking Plugin v7.2 - DEBUG
 * TRION Plugin Format
 */

import { TRIONPlugin, PluginContext } from '../../runtime/plugin-base.ts';

interface ThinkingStep {
  title: string;
  content: string;
  timestamp: number;
}

export default class SequentialThinkingPlugin implements TRIONPlugin {
  private ctx: PluginContext;
  private tabId = 'seq-thinking-tab';
  private steps: ThinkingStep[] = [];
  private currentStepContent = "";
  private isAnalyzing = false;

  constructor(ctx: PluginContext) {
    this.ctx = ctx;
  }

  async init(): Promise<void> {
    console.log('[SequentialThinking] Initializing v7.2...');

    // Create panel tab
    await this.ctx.panel.createTab(this.tabId, '🧠 Thinking', 'markdown', {
      autoOpen: false
    });

    // Listen for SSE events - with debug wrapper
    const self = this;
    
    this.ctx.events.on('sequential_start', (data: any) => {
      console.log('[SequentialThinking] GOT sequential_start:', data);
      self.handleStart(data);
    });
    
    this.ctx.events.on('seq_thinking_stream', (data: any) => {
      console.log('[SequentialThinking] GOT seq_thinking_stream');
      self.handleStream(data);
    });
    
    this.ctx.events.on('sequential_step', (data: any) => {
      console.log('[SequentialThinking] GOT sequential_step:', data?.step_number);
      self.handleStep(data);
    });
    
    this.ctx.events.on('sequential_done', (data: any) => {
      console.log('[SequentialThinking] GOT sequential_done');
      self.handleDone(data);
    });
    
    this.ctx.events.on('sequential_error', (data: any) => {
      console.log('[SequentialThinking] GOT sequential_error:', data);
      self.handleError(data);
    });
    
    console.log('[SequentialThinking] Event listeners registered!');
  }

  async destroy(): Promise<void> {
    console.log('[SequentialThinking] Destroying...');
    await this.ctx.panel.closeTab(this.tabId);
  }

  private async handleStart(data: any): Promise<void> {
    console.log('[SequentialThinking] handleStart called');
    this.steps = [];
    this.currentStepContent = "";
    this.isAnalyzing = true;
    await this.ctx.panel.createTab(this.tabId, '🧠 Thinking', 'markdown', {
      autoOpen: true,
      content: `### 🚀 Starting Analysis...\nTask ID: ${data?.task_id || 'unknown'}\nComplexity: ${data?.complexity || 'unknown'}`
    });
  }

  private async handleStream(data: { chunk?: string }): Promise<void> {
    this.currentStepContent += data?.chunk || '';
    await this.render();
  }

  private async handleStep(data: { step_number?: number, title?: string, thought?: string }): Promise<void> {
    console.log('[SequentialThinking] handleStep called, step:', data?.step_number);
    this.steps.push({
      title: data?.title || `Step ${data?.step_number}`,
      content: data?.thought || this.currentStepContent,
      timestamp: Date.now()
    });
    this.currentStepContent = "";
    await this.render();
  }

  private async handleDone(data: { steps?: any[] }): Promise<void> {
    console.log('[SequentialThinking] handleDone called');
    this.isAnalyzing = false;
    await this.ctx.panel.updateTab(this.tabId, '\n\n---\n### ✅ Analysis Complete', true);
  }

  private async handleError(data: { error?: string }): Promise<void> {
    this.isAnalyzing = false;
    await this.ctx.panel.updateTab(this.tabId, `\n\n---\n❌ **Error**: ${data?.error || 'Unknown'}`, true);
  }

  private async render(): Promise<void> {
    let md = '## 🧠 Sequential Thinking\n\n';
    
    for (let i = 0; i < this.steps.length; i++) {
      const step = this.steps[i];
      md += `### Step ${i + 1}: ${step.title}\n\n`;
      md += step.content + '\n\n';
    }
    
    if (this.currentStepContent) {
      md += `### 💭 Processing...\n\n${this.currentStepContent}\n`;
    }
    
    if (this.isAnalyzing) {
      md += '\n\n*Thinking...*';
    }
    
    await this.ctx.panel.updateTab(this.tabId, md, false);
  }

  getSettings() {
    return [
      {
        key: 'autoOpen',
        label: 'Auto-open Panel',
        type: 'toggle' as const,
        default: true,
        description: 'Automatically open the thinking panel when analysis starts'
      }
    ];
  }
}
