# Full Pipeline Bottleneck Report

## Core
- Perf report: `/home/danny/Jarvis/logs/perf/full_pipeline_perf_20260308-234947.json`
- Legacy dataset rows: **150** (`2025-07-11T23:49:47.428453Z` .. `2025-09-24T11:49:47.428453Z`)
- CPU embedding prepare/restore: **True / True**

## Performance
- overall p95_e2e_ms: **10121.893**
- stream p95_ttft_ms: **1415.869**
- stream p50_tokens_per_sec: **25000.0**

## Pipeline Signals
- requests_total: 30
- thinking/control/output events: 15/18/24
- tool_execution_events: 9
- embedding routes cpu/gpu: 172/0
- routing_fallbacks: 16
- ollama unload events: 0

## Error Hotspots
- tool_not_found: 0
- memory_fts: 0
- decide_tools attr errors: 0

## Bottlenecks
- [medium] high_e2e_latency: User-perceived latency spikes under mixed sync/stream workload.
- [medium] high_ttft: Slow first token on stream path; startup and retrieval/tool orchestration likely dominates.
