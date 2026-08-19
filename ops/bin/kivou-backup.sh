#!/usr/bin/env bash
# Sauvegarde PostgreSQL de Kivou.
#
#     Ceci n'est PAS un plan de reprise d'activité.
#
# Une sauvegarde posée sur le même hôte que la base disparaît avec l'hôte. Elle
# protège contre l'erreur humaine et la corruption logique — pas contre la perte
# du serveur. La production exige une copie HORS HÔTE (Swiss Backup, S3, autre
# machine) : c'est une porte de production explicite, pas un détail.
set -Eeuo pipefail

BACKUP_DIR="${KIVOU_BACKUP_DIR:-/srv/kivou/backups}"
RETENTION_DAYS="${KIVOU_BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${BACKUP_DIR}/kivou-${STAMP}.dump"

: "${KIVOU_DATABASE_URL:?KIVOU_DATABASE_URL doit être défini}"

# `KIVOU_DATABASE_URL` est une URL SQLAlchemy : elle nomme le PILOTE Python
# (`postgresql+psycopg://`). `pg_dump` ne connaît pas cette forme et refuse de
# l'ouvrir. On la ramène donc à l'URL libpq standard.
PG_URL="$(printf '%s' "${KIVOU_DATABASE_URL}" | sed -E 's#^postgresql\+[a-z0-9_]+://#postgresql://#')"

mkdir -p "${BACKUP_DIR}"
# La sauvegarde contient TOUTES les données client : personne d'autre ne la lit.
chmod 700 "${BACKUP_DIR}"

log() { echo "[kivou-backup] $*"; }

# Un échec doit être bruyant et laisser une trace exploitable : une sauvegarde
# qui échoue en silence est pire que pas de sauvegarde, parce qu'on croit en
# avoir une.
trap 'log "ÉCHEC à la ligne ${LINENO}"; exit 1' ERR

log "sauvegarde vers ${TARGET}"

# Format `custom` : compressé, et restaurable sélectivement par pg_restore.
# `--no-owner`/`--no-privileges` : la restauration vise une base jetable dont
# les rôles n'ont aucune raison d'exister.
pg_dump --dbname="${PG_URL}" \
        --format=custom \
        --no-owner \
        --no-privileges \
        --file="${TARGET}"

chmod 600 "${TARGET}"

SIZE="$(du -h "${TARGET}" | cut -f1)"
log "terminé : ${SIZE}"

# Une sauvegarde vide ou minuscule est un échec déguisé en succès.
MIN_BYTES="${KIVOU_BACKUP_MIN_BYTES:-4096}"
ACTUAL="$(stat -c%s "${TARGET}")"
if [ "${ACTUAL}" -lt "${MIN_BYTES}" ]; then
    log "ÉCHEC : sauvegarde suspecte (${ACTUAL} octets < ${MIN_BYTES})"
    exit 1
fi

# Purge APRÈS succès seulement : sinon un dump raté supprimerait les bons.
DELETED="$(find "${BACKUP_DIR}" -name 'kivou-*.dump' -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)"
log "rétention ${RETENTION_DAYS} j — ${DELETED} archive(s) supprimée(s)"
