/**
 * Sequential Thinking Plugin v8.0
 * Multi-tab observability: Thinking + Build + Planning
 */

import { TRIONPlugin, PluginContext } from '../../runtime/plugin-base.ts';

interface ThinkingStep {
  title: string;
  content: string;
  timestamp: number;
}

interface BuildEvent {
  ts: number;
  kind: 'info' | 'ok' | 'error';
  lane: 'skill' | 'code' | 'general';
  text: string;
}

export default class SequentialThinkingPlugin implements TRIONPlugin {
  private ctx: PluginContext;

  private thinkingTabId = 'seq-thinking-tab';
  private buildTabId = 'build-activity-tab';
  private planningTabId = 'planning-tab';

  private steps: ThinkingStep[] = [];
  private currentStepContent = '';
  private isAnalyzing = false;
  private buildEvents: BuildEvent[] = [];
  private lastTaskId = '';
  private lastComplexity: number | string = 'unknown';
  private hydratingFromWorkspace = false;

  constructor(ctx: PluginContext) {
    this.ctx = ctx;
  }

  async init(): Promise<void> {
    this.ctx.log('[SequentialThinking] Initializing v8.0...');

    await this.ctx.panel.createTab(this.thinkingTabId, 'Thinking', 'markdown', {
      autoOpen: false,
      content: '## Thinking\n\nWaiting for sequential events...',
    });
    await this.ctx.panel.createTab(this.buildTabId, 'Build', 'markdown', {
      autoOpen: false,
      content: '## Build Activity\n\nWaiting for tool events...',
    });
    await this.ctx.panel.createTab(this.planningTabId, 'Planning', 'markdown', {
      autoOpen: false,
      content: '## Planning\n\nWaiting for a complex task...',
    });

    this.ctx.events.on('sequential_start', (data: any) => this.handleStart(data));
    this.ctx.events.on('seq_thinking_stream', (data: any) => this.handleStream(data));
    this.ctx.events.on('sequential_step', (data: any) => this.handleStep(data));
    this.ctx.events.on('sequential_done', (data: any) => this.handleDone(data));
    this.ctx.events.on('sequential_error', (data: any) => this.handleError(data));

    this.ctx.events.on('tool_start', (data: any) => this.handleToolStart(data));
    this.ctx.events.on('tool_result', (data: any) => this.handleToolResult(data));
    this.ctx.events.on('skill_routed', (data: any) => this.handleSkillEvent('ok', data));
    this.ctx.events.on('skill_blocked', (data: any) => this.handleSkillEvent('error', data));
    this.ctx.events.on('response_mode', (data: any) => this.handleResponseMode(data));
    this.ctx.events.on('container_start', (data: any) => this.handleContainerStart(data));
    this.ctx.events.on('container_done', (data: any) => this.handleContainerDone(data));
    this.ctx.events.on('blueprint_routed', (data: any) => this.handleBlueprintEvent('ok', data));
    this.ctx.events.on('blueprint_blocked', (data: any) => this.handleBlueprintEvent('error', data));
    this.ctx.events.on('blueprint_suggest', (data: any) => this.handleBlueprintEvent('info', data));
    this.ctx.events.on('workspace_update', (data: any) => this.handleWorkspaceUpdate(data));

    this.ctx.log('[SequentialThinking] Event listeners registered');
  }

  async destroy(): Promise<void> {
    this.ctx.log('[SequentialThinking] Destroying...');
    await this.ctx.panel.closeTab(this.thinkingTabId);
    await this.ctx.panel.closeTab(this.buildTabId);
    await this.ctx.panel.closeTab(this.planningTabId);
  }

  private formatTime(ts: number): string {
    return new Date(ts).toLocaleTimeString('de-DE', { hour12: false });
  }

  private normalizeOneLine(text: string, maxLen = 200): string {
    const compact = String(text || '')
      .replace(/\s+/g, ' ')
      .trim();
    if (compact.length <= maxLen) return compact;
    return compact.slice(0, maxLen - 3) + '...';
  }

  private inferBuildLaneFromTools(toolNames: string[]): BuildEvent['lane'] {
    const names = toolNames.map((name) => String(name || '').toLowerCase()).filter(Boolean);
    if (!names.length) return 'general';
    if (names.some((name) => name.includes('skill'))) return 'skill';
    if (
      names.some(
        (name) =>
          name.includes('code') ||
          name.includes('container') ||
          name.includes('sandbox') ||
          name.includes('exec') ||
          name.includes('write') ||
          name.includes('patch') ||
          name.includes('file'),
      )
    ) {
      return 'code';
    }
    return 'general';
  }

  private addBuildEvent(kind: BuildEvent['kind'], text: string, lane: BuildEvent['lane'] = 'general'): void {
    this.buildEvents.push({
      ts: Date.now(),
      kind,
      lane,
      text: this.normalizeOneLine(text),
    });
    if (this.buildEvents.length > 80) {
      this.buildEvents = this.buildEvents.slice(-80);
    }
    void this.renderBuild();
  }

  private async handleStart(data: any): Promise<void> {
    this.steps = [];
    this.currentStepContent = '';
    this.isAnalyzing = true;
    this.lastTaskId = String(data?.task_id || '');
    this.lastComplexity = data?.complexity ?? 'unknown';

    await this.ctx.panel.createTab(this.thinkingTabId, 'Thinking', 'markdown', {
      autoOpen: true,
      content: '## Thinking\n\nStarting analysis...',
    });
    await this.ctx.panel.createTab(this.planningTabId, 'Planning', 'markdown', {
      autoOpen: true,
      content: '## Planning\n\nPreparing checklist...',
    });

    await this.renderThinking();
    await this.renderPlanning();
  }

  private async handleStream(data: { chunk?: string }): Promise<void> {
    this.currentStepContent += data?.chunk || '';
    await this.renderThinking();
    await this.renderPlanning();
  }

  private async handleStep(data: { step_number?: number; title?: string; thought?: string }): Promise<void> {
    this.steps.push({
      title: data?.title || `Step ${data?.step_number || this.steps.length + 1}`,
      content: data?.thought || this.currentStepContent || '',
      timestamp: Date.now(),
    });
    this.currentStepContent = '';
    await this.renderThinking();
    await this.renderPlanning();
  }

  private async handleDone(_data: { steps?: any[] }): Promise<void> {
    this.isAnalyzing = false;
    await this.renderThinking();
    await this.renderPlanning();
  }

  private async handleError(data: { error?: string }): Promise<void> {
    this.isAnalyzing = false;
    this.addBuildEvent('error', `Sequential error: ${data?.error || 'Unknown'}`);
    await this.renderThinking(data?.error || 'Unknown');
    await this.renderPlanning(data?.error || 'Unknown');
  }

  private handleToolStart(data: { tools?: string[] }): void {
    const names = Array.isArray(data?.tools) ? data.tools.filter(Boolean) : [];
    const toolLabel = names.length ? names.join(', ') : 'unknown tool';
    const lane = this.inferBuildLaneFromTools(names);
    this.addBuildEvent('info', `Tool start: ${toolLabel}`, lane);
    void this.ctx.panel.createTab(this.buildTabId, 'Build', 'markdown', { autoOpen: false });
  }

  private handleToolResult(data: { tool?: string; success?: boolean; error?: string }): void {
    const tool = data?.tool || 'tool';
    const lane = this.inferBuildLaneFromTools([tool]);
    if (data?.success) {
      this.addBuildEvent('ok', `Tool result: ${tool} succeeded`, lane);
    } else {
      this.addBuildEvent('error', `Tool result: ${tool} failed (${data?.error || 'unknown error'})`, lane);
    }
  }

  private handleSkillEvent(kind: BuildEvent['kind'], data: any): void {
    if (kind === 'ok') {
      this.addBuildEvent('ok', `Skill routed: ${data?.skill_name || 'unknown'}`, 'skill');
    } else {
      this.addBuildEvent('error', `Skill blocked: ${data?.reason || 'unknown reason'}`, 'skill');
    }
  }

  private handleResponseMode(data: { mode?: string }): void {
    const mode = String(data?.mode || 'interactive');
    this.addBuildEvent('info', `Response mode: ${mode}`, 'general');
  }

  private handleContainerStart(data: { container?: string; task?: string }): void {
    const container = String(data?.container || 'container');
    const task = String(data?.task || '').trim();
    const text = task ? `Container start: ${container} (${task})` : `Container start: ${container}`;
    this.addBuildEvent('info', text, 'code');
  }

  private handleContainerDone(data: { result?: any }): void {
    const hasError = Boolean(data?.result?.error);
    this.addBuildEvent(hasError ? 'error' : 'ok', hasError ? 'Container done with error' : 'Container done', 'code');
  }

  private handleBlueprintEvent(kind: BuildEvent['kind'], data: any): void {
    if (data?.blueprint_id) {
      this.addBuildEvent(kind, `Blueprint: ${data.blueprint_id}`, 'code');
      return;
    }
    if (Array.isArray(data?.candidates) && data.candidates.length) {
      const names = data.candidates
        .map((candidate: any) => String(candidate?.id || '').trim())
        .filter(Boolean)
        .slice(0, 4);
      this.addBuildEvent(kind, `Blueprint candidates: ${names.join(', ') || 'unknown'}`, 'code');
      return;
    }
    this.addBuildEvent(kind, `Blueprint event: ${data?.reason || 'no details'}`, 'code');
  }

  private isTruthyToken(value: string): boolean {
    const token = String(value || '').trim().toLowerCase();
    return token === 'true' || token === '1' || token === 'yes' || token === 'on';
  }

  private handleWorkspaceControlDecision(fields: Record<string, string>): void {
    const approved = this.isTruthyToken(fields.approved || '');
    const skipped = this.isTruthyToken(fields.skipped || '');
    const skipReason = String(fields.skip_reason || '').trim();
    const corrections = String(fields.corrections || '').trim();

    let kind: BuildEvent['kind'] = skipped ? 'info' : approved ? 'ok' : 'error';
    let text = skipped ? 'Control skipped' : approved ? 'Control approved' : 'Control rejected';
    if (skipReason) {
      text += ` (${skipReason})`;
    }
    if (corrections && corrections !== '-') {
      text += ` | corrections=${corrections}`;
    }
    this.addBuildEvent(kind, text, 'general');
  }

  private handleWorkspaceObservation(sourceLayer: string, content: string): void {
    const compact = this.normalizeOneLine(content, 220);
    if (!compact) return;

    const layer = String(sourceLayer || '').trim().toLowerCase();
    let prefix = 'Observation';
    if (layer === 'thinking') prefix = 'Thinking';
    else if (layer === 'control') prefix = 'Control';
    else if (layer === 'orchestrator') prefix = 'Orchestrator';

    const lane = /\b(skill|run_skill|create_skill|autonomous_skill_task)\b/i.test(compact)
      ? 'skill'
      : 'general';
    this.addBuildEvent('info', `${prefix}: ${compact}`, lane);
  }

  private handleWorkspaceChatDone(fields: Record<string, string>): void {
    const reason = String(fields.done_reason || 'stop').trim();
    const mode = String(fields.response_mode || 'interactive').trim();
    const model = String(fields.model || '').trim();
    const modelPart = model ? `, ${model}` : '';
    this.addBuildEvent('ok', `Chat done: ${reason} (${mode}${modelPart})`, 'general');
  }

  private handleWorkspaceNote(content: string): void {
    const line = String(content || '')
      .split('\n')
      .map((item) => item.trim())
      .find((item) => /^tools executed:/i.test(item));
    if (!line) return;
    const rawTools = line.split(':', 2)[1] || '';
    const toolNames = rawTools
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
    if (!toolNames.length) return;
    const lane = this.inferBuildLaneFromTools(toolNames);
    this.addBuildEvent('info', `Tools executed: ${toolNames.join(', ')}`, lane);
  }

  private parsePipeSummary(text: string): Record<string, string> {
    const result: Record<string, string> = {};
    const parts = String(text || '')
      .split('|')
      .map((part) => part.trim())
      .filter(Boolean);
    for (const part of parts) {
      const idx = part.indexOf('=');
      if (idx <= 0) continue;
      const key = part.slice(0, idx).trim();
      const value = part.slice(idx + 1).trim();
      if (!key) continue;
      result[key] = value;
    }
    return result;
  }

  private handleWorkspaceUpdate(data: {
    entry_type?: string;
    source_layer?: string;
    content?: string;
    replay?: boolean;
  }): void {
    const entryType = String(data?.entry_type || '').trim();
    const sourceLayer = String(data?.source_layer || '').trim();
    const content = String(data?.content || '').trim();
    const fields = this.parsePipeSummary(content);
    const isPlanningEvent = entryType.startsWith('planning_') && sourceLayer === 'sequential';
    if (isPlanningEvent) {
      if (!data?.replay) return;

      if (entryType === 'planning_start') {
        this.steps = [];
        this.currentStepContent = '';
        this.isAnalyzing = true;
        this.hydratingFromWorkspace = true;
        this.lastTaskId = fields.task_id || this.lastTaskId;
        this.lastComplexity = fields.complexity || this.lastComplexity;
        this.addBuildEvent('info', `Planning restored for task ${this.lastTaskId || 'unknown'}`, 'general');
        void this.renderThinking();
        void this.renderPlanning();
        return;
      }

      if (entryType === 'planning_step') {
        if (!this.hydratingFromWorkspace && this.steps.length === 0) {
          this.hydratingFromWorkspace = true;
        }
        const stepNum = Number(fields.step || this.steps.length + 1);
        const title = fields.title || `Step ${Number.isFinite(stepNum) ? stepNum : this.steps.length + 1}`;
        this.steps.push({
          title,
          content: `Restored from workspace event (thought_len=${fields.thought_len || '?'})`,
          timestamp: Date.now(),
        });
        void this.renderThinking();
        void this.renderPlanning();
        return;
      }

      if (entryType === 'planning_done') {
        this.isAnalyzing = false;
        this.hydratingFromWorkspace = false;
        void this.renderThinking();
        void this.renderPlanning();
        return;
      }

      if (entryType === 'planning_error') {
        this.isAnalyzing = false;
        this.hydratingFromWorkspace = false;
        const err = fields.error || 'Unknown';
        this.addBuildEvent('error', `Planning restore error: ${err}`, 'general');
        void this.renderThinking(err);
        void this.renderPlanning(err);
        return;
      }

      return;
    }

    // Non-planning workspace updates enrich Build Activity in live mode.
    if (data?.replay) return;
    if (!entryType) return;

    if (entryType === 'control_decision') {
      this.handleWorkspaceControlDecision(fields);
      return;
    }

    if (entryType === 'chat_done') {
      this.handleWorkspaceChatDone(fields);
      return;
    }

    if (entryType === 'observation') {
      this.handleWorkspaceObservation(sourceLayer, content);
      return;
    }

    if (entryType === 'note') {
      this.handleWorkspaceNote(content);
      return;
    }
  }

  private async renderThinking(errorText = ''): Promise<void> {
    let md = '## Thinking\n\n';
    md += `- Task ID: ${this.lastTaskId || 'unknown'}\n`;
    md += `- Complexity: ${this.lastComplexity}\n`;
    md += `- Status: ${this.isAnalyzing ? 'running' : 'idle'}\n\n`;

    for (let i = 0; i < this.steps.length; i++) {
      const step = this.steps[i];
      md += `### Step ${i + 1}: ${step.title}\n\n`;
      md += `${step.content || '_no thought content_'}\n\n`;
    }

    if (this.currentStepContent) {
      md += `### In progress\n\n${this.currentStepContent}\n\n`;
    }

    if (errorText) {
      md += `---\n\nError: ${this.normalizeOneLine(errorText, 400)}\n`;
    } else if (!this.isAnalyzing && this.steps.length > 0) {
      md += '---\n\nDone.\n';
    }

    await this.ctx.panel.updateTab(this.thinkingTabId, md, false);
  }

  private async renderPlanning(errorText = ''): Promise<void> {
    let md = '## Planning\n\n';
    md += `Current mode: ${this.isAnalyzing ? 'active' : 'idle'}\n\n`;

    if (!this.steps.length && !this.currentStepContent && !errorText) {
      md += '- [ ] Waiting for sequential plan\n';
      await this.ctx.panel.updateTab(this.planningTabId, md, false);
      return;
    }

    for (let i = 0; i < this.steps.length; i++) {
      const step = this.steps[i];
      md += `- [x] Step ${i + 1}: ${this.normalizeOneLine(step.title, 120)}\n`;
    }

    if (this.isAnalyzing) {
      const nextText = this.currentStepContent
        ? this.normalizeOneLine(this.currentStepContent, 140)
        : 'Next step is being generated';
      md += `- [ ] Next: ${nextText}\n`;
    }

    if (errorText) {
      md += `\nError: ${this.normalizeOneLine(errorText, 220)}\n`;
    } else if (!this.isAnalyzing) {
      md += '\nStatus: Completed.\n';
    }

    await this.ctx.panel.updateTab(this.planningTabId, md, false);
  }

  private async renderBuild(): Promise<void> {
    let md = '## Build Activity\n\n';
    if (!this.buildEvents.length) {
      md += 'Waiting for tool events...\n';
      await this.ctx.panel.updateTab(this.buildTabId, md, false);
      return;
    }
    const laneConfig: Array<{ lane: BuildEvent['lane']; title: string; emptyText: string }> = [
      { lane: 'skill', title: 'Skill Lane', emptyText: 'No skill activity yet.' },
      { lane: 'code', title: 'Code Lane', emptyText: 'No code activity yet.' },
      { lane: 'general', title: 'General Lane', emptyText: 'No general activity yet.' },
    ];

    const laneCounts = laneConfig.map(
      (cfg) =>
        `${cfg.title.replace(' Lane', '')}: ${this.buildEvents.filter((event) => event.lane === cfg.lane).length}`,
    );
    md += `${laneCounts.join(' | ')}\n\n`;

    for (const cfg of laneConfig) {
      md += `### ${cfg.title}\n\n`;
      const laneEvents = this.buildEvents.filter((event) => event.lane === cfg.lane).slice(-10);
      if (!laneEvents.length) {
        md += `- ${cfg.emptyText}\n\n`;
        continue;
      }
      for (const event of laneEvents) {
        const icon = event.kind === 'ok' ? 'OK' : event.kind === 'error' ? 'ERR' : 'INFO';
        md += `- ${this.formatTime(event.ts)} [${icon}] ${event.text}\n`;
      }
      md += '\n';
    }
    await this.ctx.panel.updateTab(this.buildTabId, md, false);
  }

  getSettings() {
    return [
      {
        key: 'autoOpen',
        label: 'Auto-open Thinking',
        type: 'toggle' as const,
        default: true,
        description: 'Automatically open thinking/planning tab when sequential analysis starts',
      },
    ];
  }
}
