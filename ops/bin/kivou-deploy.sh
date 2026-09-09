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

KIVOU_ADMIN_SAFE_URL=$KIVOU_MIGRATION_ADMIN_URL
if [[ "$KIVOU_MIGRATION_ADMIN_URL" =~ ^postgresql://([^:/@]*):([^@]*)@(.*)$ ]]; then
  PGPASSWORD=${BASH_REMATCH[2]}
  export PGPASSWORD
  KIVOU_ADMIN_SAFE_URL="postgresql://${BASH_REMATCH[1]}@${BASH_REMATCH[3]}"
fi

KIVOU_SOURCE_DIR=${KIVOU_SOURCE_DIR:-/srv/kivou/source}
if [[ ! -d "$KIVOU_SOURCE_DIR" ]] || ! git -c "safe.directory=$KIVOU_SOURCE_DIR" -C "$KIVOU_SOURCE_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  fail "checkout Git introuvable ou invalide : $KIVOU_SOURCE_DIR"
fi
[[ "$(stat -c '%U:%G' "$KIVOU_SOURCE_DIR")" == "kivou:kivou" ]] || fail "propriétaire du checkout invalide : $KIVOU_SOURCE_DIR"
KIVOU_RELEASES_DIR=${KIVOU_RELEASES_DIR:-/srv/kivou/releases}
KIVOU_BACKEND_LINK=${KIVOU_BACKEND_LINK:-/srv/kivou/app}
# Nginx serves this path on both staging and production. Keep the default
# aligned with the web server so a missing override cannot leave stale HTML
# live after an otherwise successful release activation.
KIVOU_FRONTEND_LINK=${KIVOU_FRONTEND_LINK:-/srv/kivou/frontend}
KIVOU_BACKUP_DIR=${KIVOU_BACKUP_DIR:-/srv/kivou/backups}
KIVOU_BACKUP_SCRIPT_CONFIGURED=${KIVOU_BACKUP_SCRIPT+x}
KIVOU_BACKUP_SCRIPT=${KIVOU_BACKUP_SCRIPT:-$KIVOU_SOURCE_DIR/ops/bin/kivou-backup.sh}
KIVOU_READINESS_SCRIPT=${KIVOU_READINESS_SCRIPT:-$KIVOU_SOURCE_DIR/ops/bin/kivou-api-readiness.sh}
KIVOU_SYSTEMD_UNIT=${KIVOU_SYSTEMD_UNIT:-kivou-api.service}
KIVOU_READINESS_PORT=${KIVOU_READINESS_PORT:-8000}
KIVOU_SERVICE_USER=${KIVOU_SERVICE_USER:-kivou}
KIVOU_PLAYWRIGHT_BROWSERS_DIR=${KIVOU_PLAYWRIGHT_BROWSERS_DIR:-/srv/kivou/playwright}
KIVOU_RELEASE_DIR="$KIVOU_RELEASES_DIR/$KIVOU_ENVIRONMENT-$KIVOU_SHA"
if [[ "$KIVOU_ENVIRONMENT" == "production" ]]; then
  KIVOU_RUNTIME_HOST_CONFIG=${KIVOU_RUNTIME_HOST_CONFIG:-/etc/kivou/acquisition-production.json}
else
  KIVOU_RUNTIME_HOST_CONFIG=${KIVOU_RUNTIME_HOST_CONFIG:-/etc/kivou/acquisition-runtime.json}
fi

check_runtime_config_shape() {
  local example=$1 host=$2
  [[ -f "$example" ]] || fail "exemple de configuration runtime introuvable : $example"
  [[ -f "$host" ]] || fail "configuration runtime hôte introuvable : $host"
  python3 - "$example" "$host" <<'PY'
import json, sys

example_path, host_path = sys.argv[1:]
try:
    with open(example_path, encoding="utf-8") as stream:
        expected = json.load(stream)
    with open(host_path, encoding="utf-8") as stream:
        actual = json.load(stream)
except (OSError, json.JSONDecodeError) as exc:
    print(f"configuration runtime invalide : {type(exc).__name__}", file=sys.stderr)
    raise SystemExit(1)

def compare(required, observed, path="$"):
    if isinstance(required, dict):
        if not isinstance(observed, dict):
            return f"{path}: objet requis"
        for key, value in required.items():
            if key not in observed:
                return f"{path}.{key}: champ obligatoire absent"
            mismatch = compare(value, observed[key], f"{path}.{key}")
            if mismatch:
                return mismatch
        return None
    if isinstance(required, list):
        return None if isinstance(observed, list) else f"{path}: tableau requis"
    if required is None:
        return None
    if type(required) is not type(observed):
        return f"{path}: type JSON attendu {type(required).__name__}"
    return None

mismatch = compare(expected, actual)
if mismatch:
    print(f"écart structurel hôte/exemple : {mismatch}", file=sys.stderr)
    raise SystemExit(1)
print("configuration runtime : structure et champs obligatoires conformes")
PY
}

sync_systemd_units() {
  local release_dir=$1
  local unit_dir="$release_dir/ops/systemd"
  local unit
  local unit_count=0
  local -a units=()

  if [[ "$KIVOU_ENVIRONMENT" == "production" ]]; then
    unit_dir="$unit_dir/production"
  fi
  [[ -d "$unit_dir" ]] || fail "unités systemd introuvables : $unit_dir"

  shopt -s nullglob
  units=("$unit_dir"/*.service "$unit_dir"/*.timer)
  shopt -u nullglob
  for unit in "${units[@]}"; do
    install -o root -g root -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
    unit_count=$((unit_count + 1))
  done
  (( unit_count > 0 )) || fail "aucune unité systemd dans $unit_dir"
  systemctl daemon-reload
  log "unités systemd synchronisées : $unit_count ($KIVOU_ENVIRONMENT)"
}

for dependency in git uv npm createdb dropdb pg_restore runuser systemctl install; do
  command -v "$dependency" >/dev/null 2>&1 || fail "$dependency introuvable"
done
command -v python3 >/dev/null 2>&1 || fail "python3 introuvable"
[[ -x "$KIVOU_BACKUP_SCRIPT" ]] || fail "helper de sauvegarde introuvable"
[[ -x "$KIVOU_READINESS_SCRIPT" ]] || fail "helper de readiness introuvable"

if [[ "$(readlink -f "$KIVOU_BACKEND_LINK" 2>/dev/null || true)" == "$KIVOU_RELEASE_DIR" ]] \
  && [[ "$(readlink -f "$KIVOU_FRONTEND_LINK" 2>/dev/null || true)" == "$KIVOU_RELEASE_DIR/frontend/dist" ]]; then
  sync_systemd_units "$KIVOU_RELEASE_DIR"
  "$KIVOU_READINESS_SCRIPT" "$KIVOU_SYSTEMD_UNIT" "$KIVOU_READINESS_PORT"
  log "release déjà active : $KIVOU_SHA"
  exit 0
fi

install -d -o "$KIVOU_SERVICE_USER" -g "$KIVOU_SERVICE_USER" -m 0755 "$KIVOU_RELEASES_DIR"
runuser --user "$KIVOU_SERVICE_USER" -- git -c "safe.directory=$KIVOU_SOURCE_DIR" -C "$KIVOU_SOURCE_DIR" fetch --no-tags origin main
runuser --user "$KIVOU_SERVICE_USER" -- git -c "safe.directory=$KIVOU_SOURCE_DIR" -C "$KIVOU_SOURCE_DIR" cat-file -e "$KIVOU_SHA^{commit}"
if [[ ! -d "$KIVOU_RELEASE_DIR/.git" && ! -f "$KIVOU_RELEASE_DIR/.git" ]]; then
  [[ ! -e "$KIVOU_RELEASE_DIR" ]] || fail "release partielle existante : $KIVOU_RELEASE_DIR"
  runuser --user "$KIVOU_SERVICE_USER" -- git -c "safe.directory=$KIVOU_SOURCE_DIR" -C "$KIVOU_SOURCE_DIR" worktree add --detach "$KIVOU_RELEASE_DIR" "$KIVOU_SHA"
fi
[[ "$(runuser --user "$KIVOU_SERVICE_USER" -- git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" == "$KIVOU_SHA" ]] || fail "checkout différent du SHA demandé"
if [[ -z "${KIVOU_BACKUP_SCRIPT_CONFIGURED:-}" ]]; then
  KIVOU_BACKUP_SCRIPT="$KIVOU_RELEASE_DIR/ops/bin/kivou-backup.sh"
fi
[[ -x "$KIVOU_BACKUP_SCRIPT" ]] || fail "helper de sauvegarde introuvable dans la release"

uv sync --project "$KIVOU_RELEASE_DIR" --frozen --extra server --extra postgres
mkdir -p "$KIVOU_PLAYWRIGHT_BROWSERS_DIR"
PLAYWRIGHT_BROWSERS_PATH="$KIVOU_PLAYWRIGHT_BROWSERS_DIR" \
  env -u KIVOU_DATABASE_URL uv run --project "$KIVOU_RELEASE_DIR" playwright install --with-deps chromium
chmod -R a+rX "$KIVOU_PLAYWRIGHT_BROWSERS_DIR"
npm --prefix "$KIVOU_RELEASE_DIR/frontend" ci
npm --prefix "$KIVOU_RELEASE_DIR/frontend" run build
chmod -R a+rX "$KIVOU_RELEASE_DIR"

marker=$(mktemp)
rehearsal_name="kivou_rehearsal_${KIVOU_SHA:0:12}_$$"
rehearsal_created=0
cleanup() {
  rm -f "$marker"
  if [[ "$rehearsal_created" -eq 1 ]]; then
    dropdb --if-exists --maintenance-db="$KIVOU_ADMIN_SAFE_URL" "$rehearsal_name" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

export KIVOU_BACKUP_DIR KIVOU_DATABASE_URL
runuser --user "$KIVOU_SERVICE_USER" -- "$KIVOU_BACKUP_SCRIPT"
backup_file=$(find "$KIVOU_BACKUP_DIR" -maxdepth 1 -type f -name 'kivou-*.dump' -newer "$marker" -print -quit)
[[ -n "$backup_file" ]] || backup_file=$(find "$KIVOU_BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' -newer "$marker" -print -quit)
[[ -n "$backup_file" ]] || fail "la sauvegarde n'a produit aucune archive"

createdb --maintenance-db="$KIVOU_ADMIN_SAFE_URL" "$rehearsal_name"
rehearsal_created=1
admin_base=${KIVOU_MIGRATION_ADMIN_URL%%\?*}
admin_query=''
[[ "$KIVOU_MIGRATION_ADMIN_URL" == *\?* ]] && admin_query="?${KIVOU_MIGRATION_ADMIN_URL#*\?}"
rehearsal_restore_url="${admin_base%/*}/$rehearsal_name$admin_query"
rehearsal_restore_safe_url="${KIVOU_ADMIN_SAFE_URL%%\?*}"
rehearsal_restore_safe_query=''
[[ "$KIVOU_ADMIN_SAFE_URL" == *\?* ]] && rehearsal_restore_safe_query="?${KIVOU_ADMIN_SAFE_URL#*\?}"
rehearsal_restore_safe_url="${rehearsal_restore_safe_url%/*}/$rehearsal_name$rehearsal_restore_safe_query"
pg_restore --exit-on-error --no-owner --no-privileges --dbname="$rehearsal_restore_safe_url" "$backup_file"
rehearsal_url="${admin_base%/*}/$rehearsal_name$admin_query"
case "$rehearsal_url" in
  postgresql://*) rehearsal_url="postgresql+psycopg://${rehearsal_url#postgresql://}" ;;
esac
MIGRATE_CODE='from signals.persistence import create_database_engine, migrate_to_latest; migrate_to_latest(create_database_engine())'
if ! KIVOU_DATABASE_URL="$rehearsal_url" uv run --project "$KIVOU_RELEASE_DIR" python -c "$MIGRATE_CODE"; then
  fail "répétition Alembic échouée ; la base et la release vives sont intactes"
fi
dropdb --if-exists --maintenance-db="$KIVOU_ADMIN_SAFE_URL" "$rehearsal_name"
rehearsal_created=0

if [[ -f "$KIVOU_RUNTIME_HOST_CONFIG" ]]; then
  check_runtime_config_shape \
    "$KIVOU_RELEASE_DIR/ops/host/acquisition-runtime.$KIVOU_ENVIRONMENT.json" \
    "$KIVOU_RUNTIME_HOST_CONFIG"
else
  log "configuration runtime hôte absente, contrôle structurel différé : $KIVOU_RUNTIME_HOST_CONFIG"
fi

KIVOU_DATABASE_URL="$KIVOU_DATABASE_URL" uv run --project "$KIVOU_RELEASE_DIR" python -c "$MIGRATE_CODE"

# `uv run` peut recréer les métadonnées du paquet éditable. Appliquer les
# permissions après le dernier appel à uv garantit que kivou et www-data lisent
# tous les fichiers de la release au moment de la bascule.
chmod -R a+rX "$KIVOU_RELEASE_DIR"

preserve_previous() {
  local link=$1
  local current
  current=$(readlink -f "$link" 2>/dev/null || true)
  [[ -z "$current" ]] || ln -sfn "$current" "$link.previous"
}
activate() {
  local target=$1
  local link=$2
  local temporary="${link}.next"
  mkdir -p "$(dirname "$link")"
  ln -sfn "$target" "$temporary"
  mv -Tf "$temporary" "$link"
}
preserve_previous "$KIVOU_BACKEND_LINK"
preserve_previous "$KIVOU_FRONTEND_LINK"
activate "$KIVOU_RELEASE_DIR" "$KIVOU_BACKEND_LINK"
activate "$KIVOU_RELEASE_DIR/frontend/dist" "$KIVOU_FRONTEND_LINK"
sync_systemd_units "$KIVOU_RELEASE_DIR"
systemctl restart "$KIVOU_SYSTEMD_UNIT"
"$KIVOU_READINESS_SCRIPT" "$KIVOU_SYSTEMD_UNIT" "$KIVOU_READINESS_PORT"
trap - EXIT
cleanup
log "release active : $KIVOU_SHA ($KIVOU_ENVIRONMENT)"
