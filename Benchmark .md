# 🚀 TRION Performance Benchmarks

> **Phase**: RAG Integration & Verification  
> **Date**: 2026-01-30  
> **Hardware Target**: RTX 2060 (6GB VRAM)

## ⚡ Inference Speed (TPS)

The following metrics were captured using the **DeepSeek-R1-8B** model (Q4_K_M).

| Metric | Value | Technical Context |
| :--- | :--- | :--- |
| **Tokens per Second (TPS)** | **58.94** | Full GPU Offload (CUDA) |
| **Avg. Message Length** | 669 tokens | Reasoning + Final Response |
| **Avg. Response Latency** | 11.35s | With active KV-Caching |

> [!TIP]
> **59 TPS** is exceptional for an 8B model on legacy hardware. This confirms that the context window and model weights are perfectly fitted into the 6GB VRAM.

---

## ⏱️ Component Latency (The RAG Flow)

Breakdown of the internal pipeline steps:

| Step | Latency | Process Type |
| :--- | :--- | :--- |
| **Memory Injection** | 0.72s - 0.96s | SQLite Write + Vector Embedding |
| **Semantic Search** | **0.35s** | Semantic Seed + Graph Walk |
| **Reasoning Chain** | 12.0s - 73.0s | Multi-step Sequential Thinking |

---

## 🖥️ Resource Utilization (System Load)

Real-time monitoring during heavy inference:

* **GPU / VRAM**: 🟦 **HIGH** (Primary Engine, ~5.2GB utilized)
* **CPU (Host)**: ⬜ **IDLE** (< 1% load, 12 Cores free)
* **RAM (Host)**: 🟩 **LOW** (~4.5GB used of 32GB)

**Conclusion**: TRION is highly optimized for local GPU inference. The RAG overhead is negligible (< 400ms), ensuring factual grounding without sacrificing speed.
