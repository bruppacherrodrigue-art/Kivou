#!/usr/bin/env bash
# Vérifie le dump PostgreSQL local le plus récent, puis le copie hors hôte.
# Le dump local n'est jamais supprimé par ce script.
set -Eeuo pipefail

umask 077

BACKUP_DIR="${KIVOU_BACKUP_DIR:-/srv/kivou/backups}"
MAX_AGE_SECONDS="${KIVOU_BACKUP_MAX_AGE_SECONDS:-7200}"
RESTIC="${KIVOU_RESTIC:-restic}"
PG_RESTORE="${KIVOU_PG_RESTORE:-pg_restore}"

EX_USAGE=64
EX_DATAERR=65
EX_NOINPUT=66
EX_UNAVAILABLE=69
EX_SOFTWARE=70
EX_TEMPFAIL=75

log() { printf '[kivou-restic-upload] %s\n' "$*"; }
fail() {
    local code="$1"
    shift
    log "$*"
    exit "${code}"
}

# Ne jamais recopier l'environnement dans un diagnostic inattendu.
trap 'log "unexpected_error line=${LINENO}"; exit '"${EX_SOFTWARE}" ERR

if [ -z "${RESTIC_REPOSITORY:-}" ]; then
    fail "${EX_USAGE}" "configuration_missing name=RESTIC_REPOSITORY"
fi
if [ -z "${RESTIC_PASSWORD:-}" ]; then
    fail "${EX_USAGE}" "configuration_missing name=RESTIC_PASSWORD"
fi
if ! [[ "${MAX_AGE_SECONDS}" =~ ^[0-9]+$ ]]; then
    fail "${EX_USAGE}" "configuration_invalid name=KIVOU_BACKUP_MAX_AGE_SECONDS"
fi

command -v "${RESTIC}" >/dev/null 2>&1 \
    || fail "${EX_UNAVAILABLE}" "dependency_missing name=$(basename "${RESTIC}")"
command -v "${PG_RESTORE}" >/dev/null 2>&1 \
    || fail "${EX_UNAVAILABLE}" "dependency_missing name=$(basename "${PG_RESTORE}")"

shopt -s nullglob
dumps=("${BACKUP_DIR}"/kivou-*.dump)
if [ "${#dumps[@]}" -eq 0 ]; then
    fail "${EX_NOINPUT}" "dump_missing"
fi

dump="${dumps[0]}"
for candidate in "${dumps[@]:1}"; do
    if [ "${candidate}" -nt "${dump}" ]; then
        dump="${candidate}"
    fi
done
readonly dump

if [ ! -s "${dump}" ]; then
    fail "${EX_NOINPUT}" "dump_empty name=$(basename "${dump}")"
fi
if [ ! -f "${dump}" ] || [ -L "${dump}" ]; then
    fail "${EX_DATAERR}" "dump_type_invalid name=$(basename "${dump}")"
fi

if ! mode="$(stat -c '%a' -- "${dump}")"; then
    fail "${EX_DATAERR}" "dump_stat_failed name=$(basename "${dump}")"
fi
if [ "${mode}" != 600 ]; then
    fail "${EX_DATAERR}" "dump_mode_invalid name=$(basename "${dump}")"
fi

if ! modified_at="$(stat -c '%Y' -- "${dump}")"; then
    fail "${EX_DATAERR}" "dump_stat_failed name=$(basename "${dump}")"
fi
now="$(date +%s)"
age=$((now - modified_at))
if [ "${age}" -lt 0 ] || [ "${age}" -gt "${MAX_AGE_SECONDS}" ]; then
    fail "${EX_TEMPFAIL}" "dump_age_invalid name=$(basename "${dump}")"
fi

if ! "${PG_RESTORE}" --list "${dump}" >/dev/null 2>&1; then
    fail "${EX_SOFTWARE}" "dump_verification_failed name=$(basename "${dump}")"
fi

if ! "${RESTIC}" backup \
        --tag kivou-postgresql \
        --host kivou-production-01 \
        -- "${dump}" >/dev/null 2>&1; then
    fail "${EX_SOFTWARE}" "upload_failed name=$(basename "${dump}")"
fi

if ! "${RESTIC}" forget \
        --tag kivou-postgresql \
        --keep-daily 30 \
        --keep-monthly 12 \
        --keep-yearly 3 \
        --prune >/dev/null 2>&1; then
    fail "${EX_SOFTWARE}" "retention_failed"
fi

log "upload_complete name=$(basename "${dump}")"
