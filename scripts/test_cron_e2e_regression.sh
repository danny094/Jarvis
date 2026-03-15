#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8200}"
CONV_ID="webui-cron-e2e-$(date +%s)"
JOB_NAME="cron-e2e-$(date +%s)"
OBJECTIVE="user_reminder::Cronjob funktioniert?"

RUN_AT="$(python - <<'PY'
from datetime import datetime, timedelta, timezone
dt = datetime.now(timezone.utc) + timedelta(minutes=2)
dt = dt.replace(second=0, microsecond=0)
print(dt.isoformat().replace("+00:00", "Z"))
PY
)"

echo "[cron-e2e] BASE_URL=${BASE_URL}"
echo "[cron-e2e] CONV_ID=${CONV_ID}"
echo "[cron-e2e] RUN_AT=${RUN_AT}"

create_payload="$(jq -cn \
  --arg name "${JOB_NAME}" \
  --arg objective "${OBJECTIVE}" \
  --arg conv "${CONV_ID}" \
  --arg run_at "${RUN_AT}" \
  '{name:$name, objective:$objective, conversation_id:$conv, schedule_mode:"one_shot", run_at:$run_at, timezone:"UTC", max_loops:3, created_by:"user", enabled:true}')"

create_resp="$(curl -fsS --max-time 20 -H 'Content-Type: application/json' -d "${create_payload}" "${BASE_URL}/api/autonomy/cron/jobs")"
job_id="$(printf '%s' "${create_resp}" | jq -r '.id // empty')"
if [[ -z "${job_id}" ]]; then
  echo "[cron-e2e] ERROR: create response missing id: ${create_resp}" >&2
  exit 1
fi
echo "[cron-e2e] created job_id=${job_id}"

cleanup() {
  curl -fsS --max-time 10 -X DELETE "${BASE_URL}/api/autonomy/cron/jobs/${job_id}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

conversation_id="$(printf '%s' "${create_resp}" | jq -r '.conversation_id // ""')"
if [[ "${conversation_id}" != "${CONV_ID}" ]]; then
  echo "[cron-e2e] ERROR: conversation mismatch create=${conversation_id} expected=${CONV_ID}" >&2
  exit 1
fi

run_now_resp="$(curl -fsS --max-time 20 -X POST "${BASE_URL}/api/autonomy/cron/jobs/${job_id}/run-now")"
scheduled="$(printf '%s' "${run_now_resp}" | jq -r '.scheduled // false')"
if [[ "${scheduled}" != "true" ]]; then
  echo "[cron-e2e] ERROR: run-now not scheduled: ${run_now_resp}" >&2
  exit 1
fi
echo "[cron-e2e] run-now scheduled"

found_feedback="false"
feedback_text=""
for _ in $(seq 1 25); do
  ev_resp="$(curl -fsS --max-time 15 "${BASE_URL}/api/workspace-events?conversation_id=${CONV_ID}&event_type=cron_chat_feedback&limit=25")"
  ev_count="$(printf '%s' "${ev_resp}" | jq -r '.count // 0')"
  if [[ "${ev_count}" =~ ^[0-9]+$ ]] && [[ "${ev_count}" -gt 0 ]]; then
    feedback_text="$(printf '%s' "${ev_resp}" | jq -r '.events[-1].event_data.content // ""')"
    found_feedback="true"
    break
  fi
  sleep 2
done

if [[ "${found_feedback}" != "true" ]]; then
  echo "[cron-e2e] ERROR: no cron_chat_feedback event for ${CONV_ID}" >&2
  exit 1
fi
echo "[cron-e2e] feedback=${feedback_text}"

delete_resp="$(curl -fsS --max-time 15 -X DELETE "${BASE_URL}/api/autonomy/cron/jobs/${job_id}")"
deleted="$(printf '%s' "${delete_resp}" | jq -r '.deleted // false')"
if [[ "${deleted}" != "true" ]]; then
  echo "[cron-e2e] ERROR: delete failed: ${delete_resp}" >&2
  exit 1
fi
trap - EXIT
echo "[cron-e2e] PASS"
