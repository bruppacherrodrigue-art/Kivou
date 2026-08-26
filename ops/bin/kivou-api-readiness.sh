#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf '%s\n' 'api_readiness=invalid_arguments' >&2
  exit 64
fi

KIVOU_API_READY_UNIT=$1
KIVOU_API_READY_PORT=$2
case "$KIVOU_API_READY_UNIT:$KIVOU_API_READY_PORT" in
  (kivou-api.service:8000 | \
    kivou-api-green.service:8001 | \
    kivou-api-rollback-green.service:8001) ;;
  (*)
    printf '%s\n' 'api_readiness=invalid_arguments' >&2
    exit 64
    ;;
esac

readonly KIVOU_API_READY_ATTEMPTS=5
readonly KIVOU_API_READY_DELAY_SECONDS=1

for ((KIVOU_API_READY_ATTEMPT = 1; \
  KIVOU_API_READY_ATTEMPT <= KIVOU_API_READY_ATTEMPTS; \
  KIVOU_API_READY_ATTEMPT++)); do
  if ! timeout --foreground 1 systemctl is-active --quiet \
    "$KIVOU_API_READY_UNIT"; then
    printf 'api_readiness=service_inactive unit=%s attempt=%s\n' \
      "$KIVOU_API_READY_UNIT" "$KIVOU_API_READY_ATTEMPT" >&2
    exit 1
  fi

  if KIVOU_API_READY_STATUS=$(curl --silent --output /dev/null \
    --connect-timeout 1 --max-time 1 --write-out '%{http_code}' \
    "http://127.0.0.1:$KIVOU_API_READY_PORT/openapi.json"); then
    if [[ "$KIVOU_API_READY_STATUS" == 200 ]]; then
      printf 'api_readiness=ready unit=%s port=%s attempt=%s\n' \
        "$KIVOU_API_READY_UNIT" "$KIVOU_API_READY_PORT" \
        "$KIVOU_API_READY_ATTEMPT"
      exit 0
    fi
  fi

  if [[ "$KIVOU_API_READY_ATTEMPT" -lt "$KIVOU_API_READY_ATTEMPTS" ]]; then
    sleep "$KIVOU_API_READY_DELAY_SECONDS"
  fi
done

printf 'api_readiness=timeout unit=%s attempts=%s\n' \
  "$KIVOU_API_READY_UNIT" "$KIVOU_API_READY_ATTEMPTS" >&2
exit 1
