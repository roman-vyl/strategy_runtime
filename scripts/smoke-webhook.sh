#!/usr/bin/env bash
set -euo pipefail

base_url="${RUNTIME_BASE_URL:-http://127.0.0.1:8093}"

curl --fail --silent --show-error "${base_url}/health/live"
printf '\n'
curl --fail --silent --show-error "${base_url}/health/ready"
printf '\n'
curl --fail --silent --show-error \
  -H 'content-type: application/json' \
  -d '{"instrument":"BTCUSDT.P","timeframe":"5m","open_time_ms":1784106300000}' \
  "${base_url}/v1/webhooks/closed-bar"
printf '\n'
