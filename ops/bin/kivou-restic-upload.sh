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
trap 'log "unexpected_error"; exit "${EX_SOFTWARE}"' ERR

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
    || fail "${EX_UNAVAILABLE}" "dependency_missing name=$(basename -- "${RESTIC}")"
command -v "${PG_RESTORE}" >/dev/null 2>&1 \
    || fail "${EX_UNAVAILABLE}" "dependency_missing name=$(basename -- "${PG_RESTORE}")"
for dependency in basename date flock id ln mktemp realpath rm rmdir stat; do
    command -v "${dependency}" >/dev/null 2>&1 \
        || fail "${EX_UNAVAILABLE}" "dependency_missing name=${dependency}"
done

# Ce wrapper ne crée pas le répertoire local : `kivou-backup.sh` en reste
# l'unique producteur. Le chemin doit désigner directement un répertoire privé
# appartenant à l'utilisateur courant, jamais un alias ou un lien symbolique.
case "${BACKUP_DIR}" in
    /*) : ;;
    *) fail "${EX_DATAERR}" "backup_directory_invalid" ;;
esac
if [ ! -d "${BACKUP_DIR}" ] || [ -L "${BACKUP_DIR}" ]; then
    fail "${EX_DATAERR}" "backup_directory_invalid"
fi
if ! canonical_backup_dir="$(realpath -e -- "${BACKUP_DIR}" 2>/dev/null)"; then
    fail "${EX_DATAERR}" "backup_directory_invalid"
fi
if [ "${canonical_backup_dir}" != "${BACKUP_DIR}" ]; then
    fail "${EX_DATAERR}" "backup_directory_invalid"
fi
if ! backup_metadata="$(stat -c '%a:%u' -- "${BACKUP_DIR}" 2>/dev/null)"; then
    fail "${EX_DATAERR}" "backup_directory_invalid"
fi
if [ "${backup_metadata}" != "700:$(id -u)" ]; then
    fail "${EX_DATAERR}" "backup_directory_invalid"
fi

# Deux uploads concurrents partageraient le cache et la serrure distante. Le
# verrou local échoue immédiatement et reste tenu par le descripteur 9.
LOCK_FILE="${BACKUP_DIR}/.kivou-restic-upload.lock"
if [ -L "${LOCK_FILE}" ] || { [ -e "${LOCK_FILE}" ] && [ ! -f "${LOCK_FILE}" ]; }; then
    fail "${EX_DATAERR}" "upload_lock_invalid"
fi
exec 9>"${LOCK_FILE}" || fail "${EX_DATAERR}" "upload_lock_invalid"
chmod 600 "${LOCK_FILE}" 2>/dev/null || fail "${EX_DATAERR}" "upload_lock_invalid"
if ! flock --nonblock 9; then
    fail "${EX_TEMPFAIL}" "upload_already_running"
fi

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

dump_name="$(basename -- "${dump}")"
if ! [[ "${dump_name}" =~ ^kivou-([0-9]{8})T([0-9]{6})Z\.dump$ ]]; then
    fail "${EX_DATAERR}" "dump_name_invalid"
fi
name_date="${BASH_REMATCH[1]}"
name_time="${BASH_REMATCH[2]}"
formatted_timestamp="${name_date:0:4}-${name_date:4:2}-${name_date:6:2} ${name_time:0:2}:${name_time:2:2}:${name_time:4:2} UTC"
if ! dump_timestamp="$(date -u -d "${formatted_timestamp}" +%s 2>/dev/null)"; then
    fail "${EX_DATAERR}" "dump_name_invalid"
fi

if [ ! -s "${dump}" ]; then
    fail "${EX_NOINPUT}" "dump_empty name=${dump_name}"
fi
if [ ! -f "${dump}" ] || [ -L "${dump}" ]; then
    fail "${EX_DATAERR}" "dump_type_invalid name=${dump_name}"
fi

if ! dump_metadata="$(stat -c '%a:%u:%h' -- "${dump}" 2>/dev/null)"; then
    fail "${EX_DATAERR}" "dump_stat_failed name=${dump_name}"
fi
if [ "${dump_metadata}" != "600:$(id -u):1" ]; then
    fail "${EX_DATAERR}" "dump_metadata_invalid name=${dump_name}"
fi

if ! modified_at="$(stat -c '%Y' -- "${dump}" 2>/dev/null)"; then
    fail "${EX_DATAERR}" "dump_stat_failed name=${dump_name}"
fi
now="$(date +%s)"
age=$((now - modified_at))
if [ "${dump_timestamp}" -gt "${now}" ] \
        || [ "${age}" -lt 0 ] \
        || [ "${age}" -gt "${MAX_AGE_SECONDS}" ]; then
    fail "${EX_TEMPFAIL}" "dump_age_invalid name=${dump_name}"
fi

# Créer un hardlink dans un répertoire privé fige l'inode sélectionné.
# Remplacer ensuite le chemin original ne change donc jamais les octets lus par
# `pg_restore` puis restic. Ce second `--list` est une validation d'archive ; un
# vrai restore drill nécessite une base isolée et appartient au runbook dédié.
snapshot_dir=""
snapshot=""
cleanup_snapshot() {
    if [ -n "${snapshot}" ] && [ -e "${snapshot}" ]; then
        rm -f -- "${snapshot}" >/dev/null 2>&1 || :
    fi
    if [ -n "${snapshot_dir}" ] && [ -d "${snapshot_dir}" ]; then
        rmdir -- "${snapshot_dir}" >/dev/null 2>&1 || :
    fi
}
trap cleanup_snapshot EXIT

if ! snapshot_dir="$(mktemp -d -- "${BACKUP_DIR}/.kivou-restic-upload.XXXXXX")"; then
    fail "${EX_SOFTWARE}" "snapshot_creation_failed"
fi
chmod 700 "${snapshot_dir}" 2>/dev/null \
    || fail "${EX_SOFTWARE}" "snapshot_creation_failed"
snapshot="${snapshot_dir}/${dump_name}"
if ! ln -- "${dump}" "${snapshot}" 2>/dev/null; then
    fail "${EX_SOFTWARE}" "snapshot_creation_failed"
fi
if [ ! -s "${snapshot}" ] || [ ! -f "${snapshot}" ] || [ -L "${snapshot}" ]; then
    fail "${EX_DATAERR}" "snapshot_invalid name=${dump_name}"
fi
if ! snapshot_metadata="$(stat -c '%a:%u:%d:%i' -- "${snapshot}" 2>/dev/null)"; then
    fail "${EX_DATAERR}" "snapshot_invalid name=${dump_name}"
fi
case "${snapshot_metadata}" in
    "600:$(id -u):"*) : ;;
    *) fail "${EX_DATAERR}" "snapshot_invalid name=${dump_name}" ;;
esac
snapshot_inode="${snapshot_metadata#600:$(id -u):}"

if ! "${PG_RESTORE}" --list "${snapshot}" >/dev/null 2>&1; then
    fail "${EX_SOFTWARE}" "dump_verification_failed name=${dump_name}"
fi
if [ "$(stat -c '%d:%i' -- "${snapshot}" 2>/dev/null || :)" != "${snapshot_inode}" ]; then
    fail "${EX_DATAERR}" "snapshot_changed name=${dump_name}"
fi

if ! "${RESTIC}" backup \
        --tag kivou-postgresql \
        --host kivou-production-01 \
        -- "${snapshot}" >/dev/null 2>&1; then
    fail "${EX_SOFTWARE}" "upload_failed name=${dump_name}"
fi

if ! "${RESTIC}" forget \
        --tag kivou-postgresql \
        --host kivou-production-01 \
        --group-by host,tags \
        --keep-daily 30 \
        --keep-monthly 12 \
        --keep-yearly 3 \
        --prune >/dev/null 2>&1; then
    fail "${EX_SOFTWARE}" "retention_failed"
fi

log "upload_complete name=${dump_name}"
