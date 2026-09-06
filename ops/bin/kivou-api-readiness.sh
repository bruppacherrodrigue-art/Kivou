#!/usr/bin/env bash

set -euo pipefail

kivou_api_unit_is_allowed() {
  case "$1" in
    (kivou-api.service | \
      kivou-api-green.service | \
      kivou-api-rollback-green.service) ;;
    (*) return 1 ;;
  esac
}

if [[ $# -eq 2 && "$1" == "--state" ]]; then
  KIVOU_API_READY_UNIT=$2
  if ! kivou_api_unit_is_allowed "$KIVOU_API_READY_UNIT"; then
    printf '%s\n' 'api_readiness=invalid_arguments' >&2
    exit 64
  fi
  if ! KIVOU_API_UNIT_RAW_STATE=$(timeout --foreground 1 systemctl show \
    "$KIVOU_API_READY_UNIT" --property=LoadState --property=ActiveState \
    --value); then
    printf 'api_unit_state=unavailable unit=%s\n' \
      "$KIVOU_API_READY_UNIT" >&2
    exit 1
  fi
  case "$KIVOU_API_UNIT_RAW_STATE" in
    ($'loaded\nactive') KIVOU_API_UNIT_STATE=active ;;
    ($'loaded\ninactive') KIVOU_API_UNIT_STATE=inactive ;;
    ($'loaded\nfailed') KIVOU_API_UNIT_STATE=failed ;;
    ($'not-found\ninactive') KIVOU_API_UNIT_STATE=absent ;;
    (*)
      printf 'api_unit_state=unavailable unit=%s\n' \
        "$KIVOU_API_READY_UNIT" >&2
      exit 1
      ;;
  esac
  printf '%s\n' "$KIVOU_API_UNIT_STATE"
  exit 0
fi

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

# Type=exec reports the supervisor as active before its workers import and
# construct the ASGI application. Staging boot took 4.58s; five immediate
# connection refusals exhausted the former window in 4.23s. Allow that measured
# cold boot without relaxing HTTP timeouts or accepting an inactive service.
readonly KIVOU_API_READY_ATTEMPTS=15
readonly KIVOU_API_READY_DELAY_SECONDS=1
readonly KIVOU_API_READY_STARTED_SECONDS=$SECONDS

for ((KIVOU_API_READY_ATTEMPT = 1; \
  KIVOU_API_READY_ATTEMPT <= KIVOU_API_READY_ATTEMPTS; \
  KIVOU_API_READY_ATTEMPT++)); do
  if ! timeout --foreground 1 systemctl is-active --quiet \
    "$KIVOU_API_READY_UNIT"; then
    printf 'api_readiness=service_inactive unit=%s attempt=%s\n' \
      "$KIVOU_API_READY_UNIT" "$KIVOU_API_READY_ATTEMPT" >&2
    exit 1
  fi

  KIVOU_API_READY_CURL_EXIT=0
  if KIVOU_API_READY_STATUS=$(curl --silent --output /dev/null \
    --connect-timeout 1 --max-time 1 --write-out '%{http_code}' \
    "http://127.0.0.1:$KIVOU_API_READY_PORT/openapi.json"); then
    if [[ "$KIVOU_API_READY_STATUS" == 200 ]]; then
      printf 'api_readiness=ready unit=%s port=%s attempt=%s elapsed_seconds=%s\n' \
        "$KIVOU_API_READY_UNIT" "$KIVOU_API_READY_PORT" \
        "$KIVOU_API_READY_ATTEMPT" \
        "$((SECONDS - KIVOU_API_READY_STARTED_SECONDS))"
      exit 0
    fi
  else
    KIVOU_API_READY_CURL_EXIT=$?
  fi

  printf 'api_readiness=waiting unit=%s attempt=%s http_status=%s curl_exit=%s elapsed_seconds=%s\n' \
    "$KIVOU_API_READY_UNIT" "$KIVOU_API_READY_ATTEMPT" \
    "${KIVOU_API_READY_STATUS:-000}" "$KIVOU_API_READY_CURL_EXIT" \
    "$((SECONDS - KIVOU_API_READY_STARTED_SECONDS))" >&2

  if [[ "$KIVOU_API_READY_ATTEMPT" -lt "$KIVOU_API_READY_ATTEMPTS" ]]; then
    sleep "$KIVOU_API_READY_DELAY_SECONDS"
  fi
done

printf 'api_readiness=timeout unit=%s attempts=%s http_status=%s curl_exit=%s elapsed_seconds=%s\n' \
  "$KIVOU_API_READY_UNIT" "$KIVOU_API_READY_ATTEMPTS" \
  "${KIVOU_API_READY_STATUS:-000}" "$KIVOU_API_READY_CURL_EXIT" \
  "$((SECONDS - KIVOU_API_READY_STARTED_SECONDS))" >&2
exit 1
