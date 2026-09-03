#!/usr/bin/env bash
# Déploiement atomique Kivou. Usage : kivou-deploy.sh staging|production SHA
set -Eeuo pipefail
umask 027

log() { printf '[kivou-deploy] %s\n' "$*"; }
fail() { log "ÉCHEC : $*" >&2; exit 1; }

[[ $# -eq 2 ]] || fail "usage: $0 staging|production SHA"
KIVOU_ENVIRONMENT=$1
KIVOU_SHA=$2
case "$KIVOU_ENVIRONMENT" in staging|production) ;; *) fail "environnement invalide" ;; esac
[[ "$KIVOU_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "SHA Git explicite requis"

: "${KIVOU_DATABASE_URL:?KIVOU_DATABASE_URL doit être défini}"
: "${KIVOU_MIGRATION_ADMIN_URL:?KIVOU_MIGRATION_ADMIN_URL doit être défini}"

KIVOU_SOURCE_DIR=${KIVOU_SOURCE_DIR:-/srv/kivou/source}
KIVOU_RELEASES_DIR=${KIVOU_RELEASES_DIR:-/srv/kivou/releases}
KIVOU_BACKEND_LINK=${KIVOU_BACKEND_LINK:-/srv/kivou/app}
KIVOU_FRONTEND_LINK=${KIVOU_FRONTEND_LINK:-/var/www/kivou/current}
KIVOU_BACKUP_DIR=${KIVOU_BACKUP_DIR:-/srv/kivou/backups}
KIVOU_BACKUP_SCRIPT=${KIVOU_BACKUP_SCRIPT:-$KIVOU_SOURCE_DIR/ops/bin/kivou-backup.sh}
KIVOU_READINESS_SCRIPT=${KIVOU_READINESS_SCRIPT:-$KIVOU_SOURCE_DIR/ops/bin/kivou-api-readiness.sh}
KIVOU_SYSTEMD_UNIT=${KIVOU_SYSTEMD_UNIT:-kivou-api.service}
KIVOU_READINESS_PORT=${KIVOU_READINESS_PORT:-8000}
KIVOU_SERVICE_USER=${KIVOU_SERVICE_USER:-kivou}
KIVOU_RELEASE_DIR="$KIVOU_RELEASES_DIR/$KIVOU_ENVIRONMENT-$KIVOU_SHA"

for dependency in git uv npm createdb dropdb pg_restore runuser systemctl; do
  command -v "$dependency" >/dev/null 2>&1 || fail "$dependency introuvable"
done
[[ -x "$KIVOU_BACKUP_SCRIPT" ]] || fail "helper de sauvegarde introuvable"
[[ -x "$KIVOU_READINESS_SCRIPT" ]] || fail "helper de readiness introuvable"

if [[ "$(readlink -f "$KIVOU_BACKEND_LINK" 2>/dev/null || true)" == "$KIVOU_RELEASE_DIR" ]] \
  && [[ "$(readlink -f "$KIVOU_FRONTEND_LINK" 2>/dev/null || true)" == "$KIVOU_RELEASE_DIR/frontend/dist" ]]; then
  "$KIVOU_READINESS_SCRIPT" "$KIVOU_SYSTEMD_UNIT" "$KIVOU_READINESS_PORT"
  log "release déjà active : $KIVOU_SHA"
  exit 0
fi

mkdir -p "$KIVOU_RELEASES_DIR"
git -C "$KIVOU_SOURCE_DIR" fetch --no-tags origin main
git -C "$KIVOU_SOURCE_DIR" cat-file -e "$KIVOU_SHA^{commit}"
if [[ ! -d "$KIVOU_RELEASE_DIR/.git" && ! -f "$KIVOU_RELEASE_DIR/.git" ]]; then
  [[ ! -e "$KIVOU_RELEASE_DIR" ]] || fail "release partielle existante : $KIVOU_RELEASE_DIR"
  git -C "$KIVOU_SOURCE_DIR" worktree add --detach "$KIVOU_RELEASE_DIR" "$KIVOU_SHA"
fi
[[ "$(git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" == "$KIVOU_SHA" ]] || fail "checkout différent du SHA demandé"

uv sync --project "$KIVOU_RELEASE_DIR" --frozen --extra server --extra postgres
npm --prefix "$KIVOU_RELEASE_DIR/frontend" ci
npm --prefix "$KIVOU_RELEASE_DIR/frontend" run build

marker=$(mktemp)
rehearsal_name="kivou_rehearsal_${KIVOU_SHA:0:12}_$$"
rehearsal_created=0
cleanup() {
  rm -f "$marker"
  if [[ "$rehearsal_created" -eq 1 ]]; then
    dropdb --if-exists --maintenance-db="$KIVOU_MIGRATION_ADMIN_URL" "$rehearsal_name" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

export KIVOU_BACKUP_DIR KIVOU_DATABASE_URL
runuser --user "$KIVOU_SERVICE_USER" -- "$KIVOU_BACKUP_SCRIPT"
backup_file=$(find "$KIVOU_BACKUP_DIR" -maxdepth 1 -type f -name 'kivou-*.dump' -newer "$marker" -print -quit)
[[ -n "$backup_file" ]] || backup_file=$(find "$KIVOU_BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' -newer "$marker" -print -quit)
[[ -n "$backup_file" ]] || fail "la sauvegarde n'a produit aucune archive"

createdb --maintenance-db="$KIVOU_MIGRATION_ADMIN_URL" "$rehearsal_name"
rehearsal_created=1
admin_base=${KIVOU_MIGRATION_ADMIN_URL%%\?*}
admin_query=''
[[ "$KIVOU_MIGRATION_ADMIN_URL" == *\?* ]] && admin_query="?${KIVOU_MIGRATION_ADMIN_URL#*\?}"
rehearsal_restore_url="${admin_base%/*}/$rehearsal_name$admin_query"
pg_restore --exit-on-error --no-owner --no-privileges --dbname="$rehearsal_restore_url" "$backup_file"
rehearsal_url="${admin_base%/*}/$rehearsal_name$admin_query"
MIGRATE_CODE='from signals.persistence import create_database_engine, migrate_to_latest; migrate_to_latest(create_database_engine())'
if ! KIVOU_DATABASE_URL="$rehearsal_url" uv run --project "$KIVOU_RELEASE_DIR" python -c "$MIGRATE_CODE"; then
  fail "répétition Alembic échouée ; la base et la release vives sont intactes"
fi
dropdb --if-exists --maintenance-db="$KIVOU_MIGRATION_ADMIN_URL" "$rehearsal_name"
rehearsal_created=0

KIVOU_DATABASE_URL="$KIVOU_DATABASE_URL" uv run --project "$KIVOU_RELEASE_DIR" python -c "$MIGRATE_CODE"

preserve_previous() {
  local link=$1
  local current
  current=$(readlink -f "$link" 2>/dev/null || true)
  [[ -z "$current" ]] || ln -sfn "$current" "$link.previous"
}
activate() {
  local target=$1 link=$2 temporary="${link}.next"
  mkdir -p "$(dirname "$link")"
  ln -sfn "$target" "$temporary"
  mv -Tf "$temporary" "$link"
}
preserve_previous "$KIVOU_BACKEND_LINK"
preserve_previous "$KIVOU_FRONTEND_LINK"
activate "$KIVOU_RELEASE_DIR" "$KIVOU_BACKEND_LINK"
activate "$KIVOU_RELEASE_DIR/frontend/dist" "$KIVOU_FRONTEND_LINK"
systemctl restart "$KIVOU_SYSTEMD_UNIT"
"$KIVOU_READINESS_SCRIPT" "$KIVOU_SYSTEMD_UNIT" "$KIVOU_READINESS_PORT"
trap - EXIT
cleanup
log "release active : $KIVOU_SHA ($KIVOU_ENVIRONMENT)"
