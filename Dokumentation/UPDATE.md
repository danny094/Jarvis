TRION v4.0 Update Log
This document details the major architectural shifts, new features, and bug fixes introduced in the v4.0 release.

🛠️ Bug Fixes & Improvements
💬 Adaptive Chat Bubbles: The chat interface now scales dynamically with text content, fixing previous overflow/cutoff issues.
🌍 Multilingual Native Speech: TRION automatically detects the user's input language and responds in the same language, maintaining the persona's tone.
⚡ Optimized System Prompts: Core prompts for Thinking and Control layers have been minimized for latency but tuned for higher precision and stricter JSON adherence.
🛡️ Enhanced Error Handling: Fixed KeyError in home tools by adding heuristic parameter injection in the Orchestrator.
✨ New Features
1. Expanded Plugin Ecosystem
The plugin list on the frontend has been significantly expanded:

Code Beautifier: Automatically formats code blocks using built-in formatters (Prettier/Black) for readability.
Markdown Renderer: Rich text rendering with syntax highlighting, resolving previous conflicts with code blocks.
Ping Test: A simple connectivity debug tool to verify network health.
2. Protocol (The Memory Graph)
The daily overview of your digital life.

A new dedicated view for managing interactions:

Daily Timeline: All messages (User & AI) are organized by timestamp.
Graph Migration: Crucial interactions can be "promoted" to the long-term Knowledge Graph.
Full Control: Messages can be edited or deleted to curate the AI's context.
Priority Handling: Protocol entries are treated with higher weight than standard logs.
3. Workspace (The Sidepanel)
Visibility into the "Black Box".

While the main chat shows the final result, the Workspace tab reveals the entire reasoning chain:

Intent: The raw intent classification (e.g., "Coding", "Chit-Chat").
Sequential Thinking: The step-by-step logic stream from the Control Layer.
Control Decisions: Warnings, corrections, and safety checks applied to the plan.
Tool Execution: Raw inputs, outputs, logs, and error traces.
Container Status: Real-time health metrics of background workers.
4. Skill Servers (AI Studio)
TRION creates its own abilities.

A powerful new module allowing the AI to extend itself:

AI Studio: Integrated IDE for TRION (or you) to write Python skills.
Draft Mode: Skills created by the AI with a Security Level < 5 are automatically marked as Drafts and require human activation ("Human-in-the-Loop").
Registry: Browse "Installed" vs "Available" skills.
5. Container Commander
DevOps Automation & Infrastructure.

TRION can now provision its own runtime environments:

Security First: Only pulls images from Docker Official Images or Verified Publishers.
Blueprints: Create and reuse successful container configurations (python-sandbox, web-scraper).
Vault: Secure storage for API keys and secrets needed by containers.
Lifecycle Management: Automatically monitors and stops idle containers.
6. TRION Home Directors
Persistence: A dedicated /home/trion volume that survives container restarts.
Testing Ground: A safe, persistent space for the AI to simple write notes, test code snippets, or store project files.
🏗️ Architectural Changes
Split Thinking Layers
The cognitive architecture has been decoupled for better reasoning:

Old: Thinking and Control were mixed.
New:
Layer 1 (True Thinking): Pure reasoning (DeepSeek-R1). It plans what to do but cannot execute.
Layer 2 (Control): Verification (Qwen 2.5). It validates how it's done, checks safety, and streams the "Sequential Thinking" steps to the UI.
Tool Selector (Layer 0)
New: Added a pre-filtering layer (Qwen 1.5B) to select the top 3-5 relevant tools from the 65+ available, solving the "context window dilution" problem.