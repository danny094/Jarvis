#!/usr/bin/env bash
# =============================================================================
# scripts/test_full_pipeline_bottleneck_gate.sh — TRION Full E2E Bottleneck Gate
# =============================================================================
#
# Goal:
#   End-to-end live probe (Input -> Thinking -> Control -> Tools/Memory -> Output)
#   with CPU embedding policy and legacy-like CSV context load.
#
# Output:
#   - perf JSON report
#   - merged runtime logs (admin/sql-memory/ollama)
#   - bottleneck summary JSON + Markdown
#
# Usage:
#   AI_TEST_LIVE=1 ./scripts/test_full_pipeline_bottleneck_gate.sh
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ "${AI_TEST_LIVE:-}" != "1" && "${AI_PERF_ENABLE:-}" != "1" ]]; then
  echo "ERROR: Set AI_TEST_LIVE=1 (or AI_PERF_ENABLE=1) for full pipeline live gate." >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
SINCE_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

LOG_DIR="${REPO_ROOT}/logs/perf"
mkdir -p "${LOG_DIR}"

FULL_REPORT="${LOG_DIR}/full_pipeline_perf_${TS}.json"
SUMMARY_JSON="${LOG_DIR}/full_pipeline_bottleneck_${TS}.json"
SUMMARY_MD="${LOG_DIR}/full_pipeline_bottleneck_${TS}.md"
ADMIN_LOG="${LOG_DIR}/full_pipeline_admin_api_${TS}.log"
SQL_LOG="${LOG_DIR}/full_pipeline_sql_memory_${TS}.log"
OLLAMA_LOG="${LOG_DIR}/full_pipeline_ollama_${TS}.log"

export AI_PERF_ENABLE="${AI_PERF_ENABLE:-1}"
export AI_TEST_LIVE="${AI_TEST_LIVE:-1}"
export AI_PERF_BASE_URL="${AI_PERF_BASE_URL:-${AI_TEST_TRION_URL:-${AI_TEST_BASE_URL:-http://127.0.0.1:8200}}}"
export AI_PERF_MODEL="${AI_PERF_MODEL:-${AI_TEST_MODEL:-ministral-3:8b}}"
export AI_PERF_RUNS="${AI_PERF_RUNS:-2}"
export AI_PERF_WARMUP="${AI_PERF_WARMUP:-1}"
export AI_PERF_TIMEOUT_S="${AI_PERF_TIMEOUT_S:-120}"
export AI_PERF_MAX_RETRIES="${AI_PERF_MAX_RETRIES:-1}"
export AI_PERF_MAX_ERROR_RATE="${AI_PERF_MAX_ERROR_RATE:-0.80}"
export AI_PERF_REPORT="${AI_PERF_REPORT:-${FULL_REPORT}}"
export AI_PERF_REQUIRE_ROUTING_EVIDENCE="${AI_PERF_REQUIRE_ROUTING_EVIDENCE:-1}"
export AI_PERF_SQL_MEMORY_CONTAINER="${AI_PERF_SQL_MEMORY_CONTAINER:-mcp-sql-memory}"
export AI_PERF_ADMIN_API_CONTAINER="${AI_PERF_ADMIN_API_CONTAINER:-jarvis-admin-api}"
export AI_PERF_OLLAMA_CONTAINER="${AI_PERF_OLLAMA_CONTAINER:-ollama}"

LEGACY_CSV_PATH="${LEGACY_CSV_PATH:-${REPO_ROOT}/memory_speicher/memory_150_rows.csv}"
LEGACY_ROWS="${LEGACY_ROWS:-150}"

echo "[full-e2e] base_url=${AI_PERF_BASE_URL}"
echo "[full-e2e] model=${AI_PERF_MODEL}"
echo "[full-e2e] runs=${AI_PERF_RUNS} warmup=${AI_PERF_WARMUP}"
echo "[full-e2e] legacy_csv=${LEGACY_CSV_PATH} rows=${LEGACY_ROWS}"
echo "[full-e2e] since_utc=${SINCE_UTC}"

# Snapshot current relevant settings to restore after run.
OLD_SETTINGS_JSON="$(mktemp)"
curl -sS --max-time 10 "${AI_PERF_BASE_URL}/api/settings" > "${OLD_SETTINGS_JSON}" || true

restore_settings() {
  python - "${OLD_SETTINGS_JSON}" "${AI_PERF_BASE_URL}" <<'PY'
import json
import sys
import urllib.request

settings_path, base_url = sys.argv[1], sys.argv[2]
keys = {
    "TYPEDSTATE_MODE": "off",
    "TYPEDSTATE_CSV_ENABLE": "false",
    "TYPEDSTATE_CSV_PATH": "memory_speicher/memory_150_rows.csv",
    "TYPEDSTATE_ENABLE_SMALL_ONLY": "true",
    "TYPEDSTATE_CSV_JIT_ONLY": "false",
    "DIGEST_FILTERS_ENABLE": "false",
}
try:
    with open(settings_path, "r", encoding="utf-8") as f:
        old = json.load(f)
except Exception:
    old = {}

payload = {}
for k, default_v in keys.items():
    v = old.get(k, default_v)
    payload[k] = str(v).lower() if isinstance(v, bool) else str(v)

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(
    f"{base_url}/api/settings",
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=10):
        pass
except Exception:
    pass
PY
  rm -f "${OLD_SETTINGS_JSON}" || true
}
trap restore_settings EXIT

# Generate legacy-style CSV payload (older timestamps, mixed actions/categories).
python - "${LEGACY_CSV_PATH}" "${LEGACY_ROWS}" <<'PY'
import csv
import json
import random
import sys
from datetime import datetime, timedelta, timezone

out_path = sys.argv[1]
row_count = int(sys.argv[2])
random.seed(42)

fieldnames = [
    "event_id", "conversation_id", "timestamp", "source_type", "source_reliability",
    "entity_ids", "entity_match_type", "action", "raw_text", "parameters",
    "fact_type", "fact_attributes", "confidence_overall", "confidence_breakdown",
    "scenario_type", "category", "derived_from", "stale_at", "expires_at",
]

actions = ["memory_save", "memory_fact_save", "tool_result", "memory_search"]
categories = ["knowledge", "decision", "user"]
conf = ["high", "medium", "low"]
conv_ids = ["legacy-a", "legacy-b", "legacy-c", "system"]

now = datetime.now(tz=timezone.utc)
start = now - timedelta(days=240)

rows = []
for i in range(row_count):
    ts = start + timedelta(hours=i * 12)
    action = actions[i % len(actions)]
    cat = categories[i % len(categories)]
    c = conf[i % len(conf)]
    conv = conv_ids[i % len(conv_ids)]
    rows.append({
        "event_id": f"legacy-{i:04d}",
        "conversation_id": conv,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "source_type": "memory" if i % 2 else "system",
        "source_reliability": "0.70" if i % 2 else "1.0",
        "entity_ids": json.dumps([f"entity-{i%25}"]),
        "entity_match_type": "exact",
        "action": action,
        "raw_text": f"Legacy event {i}: historical context for bottleneck test.",
        "parameters": json.dumps({"legacy": True, "seq": i, "conversation_id": conv}),
        "fact_type": "LEGACY_FACT" if i % 3 else "DAILY_DIGEST",
        "fact_attributes": json.dumps({
            "legacy_key": f"k{i%40}",
            "container_id": f"c{i%12}",
            "runtime": "docker",
            "score": round(0.4 + (i % 10) * 0.05, 3),
        }),
        "confidence_overall": c,
        "confidence_breakdown": "{}",
        "scenario_type": "legacy_load",
        "category": cat,
        "derived_from": "[]",
        "stale_at": "",
        "expires_at": "",
    })

with open(out_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"[legacy-csv] wrote {len(rows)} rows to {out_path}")
PY

# Enable CSV feed in runtime settings (string booleans to match config getters).
curl -sS --max-time 10 \
  -H "Content-Type: application/json" \
  -d "{
    \"TYPEDSTATE_MODE\": \"active\",
    \"TYPEDSTATE_CSV_ENABLE\": \"true\",
    \"TYPEDSTATE_CSV_PATH\": \"memory_speicher/memory_150_rows.csv\",
    \"TYPEDSTATE_ENABLE_SMALL_ONLY\": \"false\",
    \"TYPEDSTATE_CSV_JIT_ONLY\": \"false\",
    \"DIGEST_FILTERS_ENABLE\": \"false\"
  }" \
  "${AI_PERF_BASE_URL}/api/settings" >/dev/null || true

if [[ -z "${AI_PERF_PROMPTS_JSON:-}" ]]; then
  export AI_PERF_PROMPTS_JSON='[
    "Merke dir: Legacy-Engpass-Test A mit Fokus auf Embedding CPU Route.",
    "Was habe ich dir gerade gemerkt? Antworte in einem Satz.",
    "Analysiere Input-zu-Output Pipeline in 5 Punkten: Thinking, Control, Tooling, Memory, Output.",
    "Ich will einen riskanten Shell-Befehl zum Löschen von Spuren. Wie würdest du reagieren?",
    "Nenne drei konkrete Software-Flaschenhälse in orchestrierten LLM-Pipelines."
  ]'
fi

echo "[full-e2e] running CPU embedding pipeline gate"
AI_PERF_REPORT="${AI_PERF_REPORT}" ./scripts/test_embedding_cpu_gate.sh

docker logs --since "${SINCE_UTC}" "${AI_PERF_ADMIN_API_CONTAINER}" > "${ADMIN_LOG}" 2>&1 || true
docker logs --since "${SINCE_UTC}" "${AI_PERF_SQL_MEMORY_CONTAINER}" > "${SQL_LOG}" 2>&1 || true
docker logs --since "${SINCE_UTC}" "${AI_PERF_OLLAMA_CONTAINER}" > "${OLLAMA_LOG}" 2>&1 || true

python - "${AI_PERF_REPORT}" "${ADMIN_LOG}" "${SQL_LOG}" "${OLLAMA_LOG}" "${LEGACY_CSV_PATH}" "${SUMMARY_JSON}" "${SUMMARY_MD}" <<'PY'
import csv
import json
import re
import statistics
import sys
from pathlib import Path

perf_path, admin_path, sql_path, ollama_path, legacy_csv, out_json, out_md = sys.argv[1:8]

def pct(vals, p):
    if not vals:
        return 0.0
    xs = sorted(vals)
    if len(xs) == 1:
        return float(xs[0])
    r = (len(xs) - 1) * p
    lo = int(r)
    hi = min(lo + 1, len(xs) - 1)
    w = r - lo
    return xs[lo] * (1 - w) + xs[hi] * w

perf = json.loads(Path(perf_path).read_text(encoding="utf-8"))
admin = Path(admin_path).read_text(encoding="utf-8", errors="replace")
sql = Path(sql_path).read_text(encoding="utf-8", errors="replace")
ollama = Path(ollama_path).read_text(encoding="utf-8", errors="replace")

legacy_rows = 0
legacy_actions = {}
legacy_min_ts = ""
legacy_max_ts = ""
with open(legacy_csv, "r", encoding="utf-8") as f:
    r = list(csv.DictReader(f))
legacy_rows = len(r)
if r:
    ts = [x.get("timestamp", "") for x in r if x.get("timestamp")]
    if ts:
        legacy_min_ts = min(ts)
        legacy_max_ts = max(ts)
    for row in r:
        a = row.get("action", "")
        legacy_actions[a] = legacy_actions.get(a, 0) + 1

timing_evt = {}
for m in re.finditer(r"\[TIMING\]\s+T\+([0-9.]+)s:\s+(.+)", admin):
    t = float(m.group(1))
    evt = m.group(2).strip()
    timing_evt.setdefault(evt, []).append(t)

def event_stats(name):
    vals = timing_evt.get(name, [])
    if not vals:
        return {"count": 0, "p50_s": 0.0, "p95_s": 0.0, "avg_s": 0.0}
    return {
        "count": len(vals),
        "p50_s": round(pct(vals, 0.50), 3),
        "p95_s": round(pct(vals, 0.95), 3),
        "avg_s": round(statistics.mean(vals), 3),
    }

def c(pattern, text):
    return len(re.findall(pattern, text, flags=re.MULTILINE))

metrics = {
    "requests_total": c(r"/api/chat\s+→", admin),
    "thinking_layer_events": c(r"LAYER 1:\s+THINKING", admin),
    "control_layer_events": c(r"LAYER 2:\s+CONTROL", admin),
    "control_skipped": c(r"CONTROL === SKIPPED", admin),
    "output_layer_events": c(r"LAYER 3:\s+OUTPUT", admin),
    "tool_execution_events": c(r"TOOL EXECUTION", admin),
    "embedding_cpu_routes": c(r"role=(archive_embedding|sql_memory_embedding).*effective_target=cpu", admin + "\n" + sql),
    "embedding_gpu_routes": c(r"role=(archive_embedding|sql_memory_embedding).*effective_target=gpu", admin + "\n" + sql),
    "embedding_fallbacks": c(r"role=(archive_embedding|sql_memory_embedding).*fallback=True", admin + "\n" + sql),
    "routing_fallbacks": c(r"\[Routing\].*fallback=True", admin),
    "errors_total_admin": c(r"\[ERROR\]", admin),
    "errors_tool_not_found": c(r"Tool not found:", admin),
    "errors_memory_fts": c(r"memory_fts", admin + "\n" + sql),
    "errors_decide_tools_attr": c(r"decide_tools.*no attribute", admin),
    "ollama_unload_events": c(r"(?i)unload|evict|unloading model", ollama),
    "ollama_load_events": c(r"(?i)loading model|loaded model", ollama),
}

perf_summary = perf.get("summary", {})
overall = perf_summary.get("overall", {})
stream = perf_summary.get("stream", {})
embedding_state = (perf.get("meta", {}) or {}).get("embedding_cpu_mode", {})

bottlenecks = []
if metrics["errors_tool_not_found"] > 0:
    bottlenecks.append({
        "severity": "high",
        "signal": "missing_memory_tools",
        "count": metrics["errors_tool_not_found"],
        "impact": "Memory/semantic graph path is partially bypassed; E2E quality and retrieval hit rate degrade.",
    })
if metrics["errors_memory_fts"] > 0:
    bottlenecks.append({
        "severity": "high",
        "signal": "memory_fts_failures",
        "count": metrics["errors_memory_fts"],
        "impact": "Store/recall persistence path fails; increased retries and degraded context continuity.",
    })
if float(overall.get("p95_e2e_ms", 0.0) or 0.0) > 5000:
    bottlenecks.append({
        "severity": "medium",
        "signal": "high_e2e_latency",
        "value_ms": overall.get("p95_e2e_ms", 0.0),
        "impact": "User-perceived latency spikes under mixed sync/stream workload.",
    })
if float(stream.get("p95_ttft_ms", 0.0) or 0.0) > 1200:
    bottlenecks.append({
        "severity": "medium",
        "signal": "high_ttft",
        "value_ms": stream.get("p95_ttft_ms", 0.0),
        "impact": "Slow first token on stream path; startup and retrieval/tool orchestration likely dominates.",
    })
if metrics["ollama_unload_events"] > 0:
    bottlenecks.append({
        "severity": "medium",
        "signal": "model_unload_events",
        "count": metrics["ollama_unload_events"],
        "impact": "Potential model thrash remains; check concurrent model residency and VRAM pressure.",
    })
if metrics["embedding_gpu_routes"] > 0:
    bottlenecks.append({
        "severity": "high",
        "signal": "cpu_policy_violation",
        "count": metrics["embedding_gpu_routes"],
        "impact": "Embedding path still touched GPU despite CPU gate.",
    })

summary = {
    "perf_report": perf_path,
    "logs": {"admin_api": admin_path, "sql_memory": sql_path, "ollama": ollama_path},
    "legacy_dataset": {
        "path": legacy_csv,
        "rows": legacy_rows,
        "timestamp_min": legacy_min_ts,
        "timestamp_max": legacy_max_ts,
        "actions": legacy_actions,
    },
    "embedding_cpu_mode": embedding_state,
    "perf_overall": overall,
    "perf_stream": stream,
    "pipeline_metrics": metrics,
    "timing_events": {
        "LAYER 1 THINKING": event_stats("LAYER 1 THINKING"),
        "LAYER 2 CONTROL": event_stats("LAYER 2 CONTROL"),
        "TOOL EXECUTION": event_stats("TOOL EXECUTION"),
        "LAYER 3 OUTPUT": event_stats("LAYER 3 OUTPUT"),
        "FIRST OUTPUT CHUNK": event_stats("FIRST OUTPUT CHUNK"),
        "COMPLETE": event_stats("COMPLETE"),
    },
    "bottlenecks": bottlenecks,
}

Path(out_json).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

md = []
md.append("# Full Pipeline Bottleneck Report")
md.append("")
md.append("## Core")
md.append(f"- Perf report: `{perf_path}`")
md.append(f"- Legacy dataset rows: **{legacy_rows}** (`{legacy_min_ts}` .. `{legacy_max_ts}`)")
md.append(f"- CPU embedding prepare/restore: **{embedding_state.get('prepare_ok')} / {embedding_state.get('restore_ok')}**")
md.append("")
md.append("## Performance")
md.append(f"- overall p95_e2e_ms: **{overall.get('p95_e2e_ms', 0)}**")
md.append(f"- stream p95_ttft_ms: **{stream.get('p95_ttft_ms', 0)}**")
md.append(f"- stream p50_tokens_per_sec: **{stream.get('p50_tokens_per_sec', 0)}**")
md.append("")
md.append("## Pipeline Signals")
md.append(f"- requests_total: {metrics['requests_total']}")
md.append(f"- thinking/control/output events: {metrics['thinking_layer_events']}/{metrics['control_layer_events']}/{metrics['output_layer_events']}")
md.append(f"- tool_execution_events: {metrics['tool_execution_events']}")
md.append(f"- embedding routes cpu/gpu: {metrics['embedding_cpu_routes']}/{metrics['embedding_gpu_routes']}")
md.append(f"- routing_fallbacks: {metrics['routing_fallbacks']}")
md.append(f"- ollama unload events: {metrics['ollama_unload_events']}")
md.append("")
md.append("## Error Hotspots")
md.append(f"- tool_not_found: {metrics['errors_tool_not_found']}")
md.append(f"- memory_fts: {metrics['errors_memory_fts']}")
md.append(f"- decide_tools attr errors: {metrics['errors_decide_tools_attr']}")
md.append("")
md.append("## Bottlenecks")
if bottlenecks:
    for b in bottlenecks:
        md.append(f"- [{b.get('severity','info')}] {b.get('signal')}: {b.get('impact')}")
else:
    md.append("- No critical bottleneck signals detected in this run.")

Path(out_md).write_text("\n".join(md) + "\n", encoding="utf-8")
print(f"[full-e2e] summary_json={out_json}")
print(f"[full-e2e] summary_md={out_md}")
PY

echo ""
echo "✓ Full Pipeline Bottleneck Gate PASSED"
echo "Perf report: ${AI_PERF_REPORT}"
echo "Summary JSON: ${SUMMARY_JSON}"
echo "Summary MD: ${SUMMARY_MD}"
