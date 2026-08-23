#!/usr/bin/env bash
# Sauvegarde PostgreSQL de Kivou — versionnée, verrouillée et vérifiée.
#
#     Ceci n'est PAS un plan de reprise d'activité.
#
# Une sauvegarde posée sur le même hôte que la base disparaît avec l'hôte. Elle
# protège contre l'erreur humaine et la corruption logique — pas contre la perte
# du serveur. La production exige une copie HORS HÔTE (Swiss Backup, S3, autre
# machine) : c'est une porte de production explicite, pas un détail.
#
# Le principe qui gouverne tout le fichier
# ────────────────────────────────────────
# Une sauvegarde qui échoue en silence est PIRE que pas de sauvegarde, parce
# qu'on croit en avoir une. Rien n'est donc considéré comme valide avant d'avoir
# été relu par `pg_restore --list`, et la rétention n'efface jamais quoi que ce
# soit avant qu'une nouvelle copie soit acceptée.
set -Eeuo pipefail

# Tout ce que ce script crée contient des données client : personne d'autre ne
# lit. `umask` le garantit dès la création — un `chmod` après coup laisserait
# une fenêtre pendant laquelle le fichier est lisible.
umask 077

BACKUP_DIR="${KIVOU_BACKUP_DIR:-/srv/kivou/backups}"
RETENTION_DAYS="${KIVOU_BACKUP_RETENTION_DAYS:-14}"
MIN_BYTES="${KIVOU_BACKUP_MIN_BYTES:-4096}"
LOCK_FILE="${KIVOU_BACKUP_LOCK_FILE:-${BACKUP_DIR}/kivou-backup.lock}"

# Plusieurs distributions n'exposent `pg_dump` que sous un chemin versionné
# (`/usr/lib/postgresql/16/bin`). Le rendre injectable évite d'imposer un PATH.
PG_DUMP="${KIVOU_PG_DUMP:-pg_dump}"
PG_RESTORE="${KIVOU_PG_RESTORE:-pg_restore}"

# Codes de sortie, pour qu'un journal systemd se lise sans deviner.
EX_USAGE=64        # configuration absente ou inutilisable
EX_UNAVAILABLE=69  # dépendance manquante
EX_SOFTWARE=70     # la sauvegarde a échoué ou n'a pas passé la vérification
EX_TEMPFAIL=75     # une autre sauvegarde tient le verrou

log() { printf '[kivou-backup] %s\n' "$*"; }
fail() { local code="$1"; shift; log "ÉCHEC : $*"; exit "${code}"; }

# Le piège : ce trap ne doit JAMAIS afficher une variable. `${LINENO}` situe le
# problème sans risquer de recopier une URL ou un mot de passe dans le journal.
trap 'log "ÉCHEC inattendu à la ligne ${LINENO}"; exit '"${EX_SOFTWARE}" ERR

# ── 1. Configuration ─────────────────────────────────────────────────────────

if [ -z "${KIVOU_DATABASE_URL:-}" ]; then
    fail "${EX_USAGE}" "KIVOU_DATABASE_URL doit être défini"
fi

# `KIVOU_DATABASE_URL` est une URL SQLAlchemy : elle nomme le PILOTE Python
# (`postgresql+psycopg://`). Les outils PostgreSQL ne connaissent pas cette
# forme et refusent de l'ouvrir. On ramène donc toutes les variantes à l'URL
# libpq standard — y compris `postgres://`, que SQLAlchemy accepte encore.
NORMALIZED="${KIVOU_DATABASE_URL}"
case "${NORMALIZED}" in
    postgresql+*://*) NORMALIZED="postgresql://${NORMALIZED#*://}" ;;
    postgres://*)     NORMALIZED="postgresql://${NORMALIZED#*://}" ;;
    postgresql://*)   : ;;
    *)
        # Défaut fermé : mieux vaut pas de sauvegarde qu'une sauvegarde de rien.
        # Le message ne recopie PAS l'URL — elle porte un mot de passe.
        fail "${EX_USAGE}" "KIVOU_DATABASE_URL n'est pas une URL PostgreSQL"
        ;;
esac

# Le mot de passe ne doit pas voyager sur la ligne de commande : `ps` est
# lisible et `/proc/<pid>/cmdline` aussi. libpq lit `PGPASSWORD` — c'est le seul
# chemin qui ne laisse pas le secret exposé au reste de l'hôte, et c'est aussi
# ce qui permet de relayer la sortie des outils sans avoir à la censurer.
SAFE_URL="${NORMALIZED}"
if [[ "${NORMALIZED}" =~ ^postgresql://([^:/@]*):([^@]*)@(.*)$ ]]; then
    PGPASSWORD="${BASH_REMATCH[2]}"
    export PGPASSWORD
    SAFE_URL="postgresql://${BASH_REMATCH[1]}@${BASH_REMATCH[3]}"
fi
readonly SAFE_URL

# ── 2. Dépendances ───────────────────────────────────────────────────────────

command -v "${PG_DUMP}" >/dev/null 2>&1 \
    || fail "${EX_UNAVAILABLE}" "pg_dump introuvable (${PG_DUMP})"
command -v "${PG_RESTORE}" >/dev/null 2>&1 \
    || fail "${EX_UNAVAILABLE}" "pg_restore introuvable (${PG_RESTORE})"
command -v flock >/dev/null 2>&1 \
    || fail "${EX_UNAVAILABLE}" "flock introuvable (util-linux)"

# ── 3. Répertoire de destination ─────────────────────────────────────────────

mkdir -p "${BACKUP_DIR}" || fail "${EX_USAGE}" "répertoire de sauvegarde inaccessible"
chmod 700 "${BACKUP_DIR}"

# ── 4. Verrou ────────────────────────────────────────────────────────────────
#
# Le verrou précède TOUT appel à `pg_dump` : deux sauvegardes concurrentes
# écriraient dans le même répertoire et se disputeraient la rétention. Le
# descripteur reste ouvert jusqu'à la fin du processus, donc le noyau libère le
# verrou même si le script est tué — un verrou qui survit à son porteur
# transformerait le timer en panne silencieuse.
exec 9>"${LOCK_FILE}" || fail "${EX_USAGE}" "verrou inaccessible"
if ! flock --nonblock 9; then
    fail "${EX_TEMPFAIL}" "une sauvegarde est déjà en cours"
fi

# ── 5. Dump ──────────────────────────────────────────────────────────────────

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${BACKUP_DIR}/kivou-${STAMP}.dump"
# On n'écrit JAMAIS directement le nom définitif : un dump interrompu laisserait
# un fichier portant le nom d'une sauvegarde valide, et c'est précisément
# celui-là qu'on restaurerait le jour où il faudrait.
PARTIAL="${TARGET}.part"

# Un fichier partiel ne doit jamais survivre à ce script, quelle qu'en soit la
# sortie : il ne sera plus jamais complété par personne.
cleanup() { rm -f "${PARTIAL}"; }
trap 'cleanup' EXIT

log "sauvegarde en cours vers $(basename "${TARGET}")"

# Format `custom` : compressé, et restaurable sélectivement par `pg_restore`.
# `--no-owner` / `--no-privileges` : la restauration vise une base jetable dont
# les rôles n'ont aucune raison d'exister.
if ! "${PG_DUMP}" \
        --dbname="${SAFE_URL}" \
        --format=custom \
        --no-owner \
        --no-privileges \
        --file="${PARTIAL}"; then
    fail "${EX_SOFTWARE}" "pg_dump n'a pas produit de sauvegarde"
fi

# ── 6. Vérifications ─────────────────────────────────────────────────────────

ACTUAL="$(stat -c%s "${PARTIAL}" 2>/dev/null || echo 0)"
if [ "${ACTUAL}" -lt "${MIN_BYTES}" ]; then
    fail "${EX_SOFTWARE}" "sauvegarde suspecte (${ACTUAL} octets < ${MIN_BYTES})"
fi

# La taille ne prouve rien : un fichier tronqué peut être volumineux. Relire la
# table des matières est le contrôle le moins cher qui distingue une archive
# réellement exploitable d'un tas d'octets.
if ! "${PG_RESTORE}" --list "${PARTIAL}" >/dev/null; then
    fail "${EX_SOFTWARE}" "sauvegarde illisible par pg_restore --list"
fi

# ── 7. Publication atomique ──────────────────────────────────────────────────

chmod 600 "${PARTIAL}"
# `mv` dans le même système de fichiers est atomique : le nom définitif
# n'apparaît qu'une fois la sauvegarde vérifiée, jamais avant.
mv -f "${PARTIAL}" "${TARGET}"
trap - EXIT

log "sauvegarde acceptée : $(basename "${TARGET}") (${ACTUAL} octets)"

# ── 8. Rétention ─────────────────────────────────────────────────────────────
#
# APRÈS succès seulement. Purger avant, ou purger après un échec, c'est effacer
# les bonnes copies le jour précis où elles deviennent indispensables.
DELETED="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'kivou-*.dump' \
    -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)"
log "rétention ${RETENTION_DAYS} j — ${DELETED} archive(s) supprimée(s)"
