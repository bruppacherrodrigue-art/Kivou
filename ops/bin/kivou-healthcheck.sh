#!/usr/bin/env bash
# Sonde externe — ce qu'un système de surveillance appelle.
#
# Elle interroge l'application par le MÊME chemin qu'un client : à travers le
# proxy, en HTTPS. Une sonde qui frapperait 127.0.0.1:8000 déclarerait tout vert
# alors que le certificat a expiré ou que le proxy est tombé.
set -Eeuo pipefail

BASE_URL="${KIVOU_HEALTHCHECK_URL:?definir KIVOU_HEALTHCHECK_URL, ex. https://staging.kivou.eu}"
FAILED=0

check() {
    local path="$1" expected="$2"
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${BASE_URL}${path}" || echo 000)"
    if [ "${code}" = "${expected}" ]; then
        echo "  OK    ${path} → ${code}"
    else
        echo "  ÉCHEC ${path} → ${code} (attendu ${expected})"
        FAILED=1
    fi
}

echo "[kivou-healthcheck] ${BASE_URL}"
check /health/live 200
check /health/ready 200

# Le certificat : une expiration silencieuse coupe tout le service.
HOST="${BASE_URL#https://}"; HOST="${HOST%%/*}"
if command -v openssl >/dev/null; then
    END="$(echo | openssl s_client -servername "${HOST}" -connect "${HOST}:443" 2>/dev/null \
           | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"
    if [ -n "${END:-}" ]; then
        DAYS=$(( ( $(date -d "${END}" +%s) - $(date +%s) ) / 86400 ))
        if [ "${DAYS}" -lt 15 ]; then
            echo "  ÉCHEC certificat expire dans ${DAYS} j"
            FAILED=1
        else
            echo "  OK    certificat valide ${DAYS} j"
        fi
    fi
fi

exit "${FAILED}"
