# 🏗️ TRION RAG Architecture

Technical blueprint of the **Retrieval-Augmented Generation** system within the TRION environment.

## 🗺️ System Overview

TRION fuses **Causal Intelligence (CIM)** with **Long-Term Memory** to create a grounded reasoning agent.

```mermaid
graph TD
    User([User Query]) --> Thinking[Sequential Thinking Server]
    Thinking --> CIM[CIM Server]
    Thinking --> Memory[SQL Memory Server]
    
    CIM --> RAG_Priors[Cognitive Priors/Procedures]
    Memory --> SQLite[(SQLite + Vector Store)]
    
    Thinking --> Ollama[Ollama - DeepSeek R1]
    Ollama --> Response([Response])

    subgraph "Reasoning Pipeline"
    CIM -- "1. Reasoning Roadmap (Static RAG)" --> Thinking
    Memory -- "2. Factual Context (Dynamic RAG)" --> Thinking
    Thinking -- "3. Prompt Injection" --> Ollama
    end
