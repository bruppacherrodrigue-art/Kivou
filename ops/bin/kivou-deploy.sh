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
KIVOU_FOUNDER_FRONTEND_LINK=${KIVOU_FOUNDER_FRONTEND_LINK:-/srv/kivou-founder/frontend}
KIVOU_FOUNDER_FRONTEND_OWNER=${KIVOU_FOUNDER_FRONTEND_OWNER:-root}
KIVOU_FOUNDER_FRONTEND_GROUP=${KIVOU_FOUNDER_FRONTEND_GROUP:-www-data}
KIVOU_FOUNDER_NGINX_WORKER_USER=${KIVOU_FOUNDER_NGINX_WORKER_USER:-www-data}
KIVOU_FOUNDER_SYSTEMD_UNIT=${KIVOU_FOUNDER_SYSTEMD_UNIT:-kivou-founder-api.service}
KIVOU_FOUNDER_SYSTEMD_UNIT_PATH=${KIVOU_FOUNDER_SYSTEMD_UNIT_PATH:-/etc/systemd/system/kivou-founder-api.service}
KIVOU_FOUNDER_NGINX_AVAILABLE=${KIVOU_FOUNDER_NGINX_AVAILABLE:-/etc/nginx/sites-available/kivou-founder-control.conf}
KIVOU_FOUNDER_NGINX_ENABLED=${KIVOU_FOUNDER_NGINX_ENABLED:-/etc/nginx/sites-enabled/kivou-founder-control.conf}
KIVOU_FOUNDER_ENV_FILE=${KIVOU_FOUNDER_ENV_FILE:-/etc/kivou/founder.env}
KIVOU_FOUNDER_ORIGIN_SECRET_FILE=${KIVOU_FOUNDER_ORIGIN_SECRET_FILE:-/etc/kivou/founder-origin-secret.conf}
KIVOU_FOUNDER_HTPASSWD_FILE=${KIVOU_FOUNDER_HTPASSWD_FILE:-/etc/kivou/founder.htpasswd}
KIVOU_FOUNDER_CERT_FULLCHAIN_FILE=${KIVOU_FOUNDER_CERT_FULLCHAIN_FILE:-/etc/letsencrypt/live/control.kivou.eu/fullchain.pem}
KIVOU_FOUNDER_CERT_PRIVATE_KEY_FILE=${KIVOU_FOUNDER_CERT_PRIVATE_KEY_FILE:-/etc/letsencrypt/live/control.kivou.eu/privkey.pem}
KIVOU_FOUNDER_CERT_CHAIN_FILE=${KIVOU_FOUNDER_CERT_CHAIN_FILE:-/etc/letsencrypt/live/control.kivou.eu/chain.pem}
KIVOU_FOUNDER_HEALTH_URL=${KIVOU_FOUNDER_HEALTH_URL:-http://127.0.0.1:8011/healthz}
KIVOU_FOUNDER_HEALTH_ATTEMPTS=${KIVOU_FOUNDER_HEALTH_ATTEMPTS:-15}
KIVOU_FOUNDER_HEALTH_DELAY_SECONDS=${KIVOU_FOUNDER_HEALTH_DELAY_SECONDS:-1}
KIVOU_FOUNDER_HEALTH_MAX_TIME=${KIVOU_FOUNDER_HEALTH_MAX_TIME:-10}
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

check_founder_prerequisites() {
  local path
  for path in \
    "$KIVOU_FOUNDER_ENV_FILE" \
    "$KIVOU_FOUNDER_ORIGIN_SECRET_FILE" \
    "$KIVOU_FOUNDER_HTPASSWD_FILE" \
    "$KIVOU_FOUNDER_CERT_FULLCHAIN_FILE" \
    "$KIVOU_FOUNDER_CERT_PRIVATE_KEY_FILE" \
    "$KIVOU_FOUNDER_CERT_CHAIN_FILE"; do
    [[ -f "$path" && -r "$path" ]] || fail "prérequis Founder absent ou illisible : $path"
  done
  runuser --user "$KIVOU_SERVICE_USER" -- test -r "$KIVOU_FOUNDER_ENV_FILE" \
    || fail "environnement illisible par l'utilisateur du service Founder"
  runuser --user "$KIVOU_FOUNDER_NGINX_WORKER_USER" -- test -r "$KIVOU_FOUNDER_HTPASSWD_FILE" \
    || fail "htpasswd Founder illisible par l'utilisateur nginx"

  if ! python3 - "$KIVOU_FOUNDER_ENV_FILE" "$KIVOU_FOUNDER_ORIGIN_SECRET_FILE" <<'PY'
import re
import sys

required = {
    "KIVOU_FOUNDER_HOSTNAME",
    "KIVOU_FOUNDER_ENVIRONMENT",
    "KIVOU_FOUNDER_ALLOWED_EMAIL",
    "KIVOU_FOUNDER_ALLOWED_USER",
    "KIVOU_FOUNDER_ORIGIN_SECRET",
    "KIVOU_FOUNDER_DATABASE_URL",
}
values: dict[str, str] = {}
with open(sys.argv[1], encoding="utf-8") as stream:
    for raw_line in stream:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")

if any(not values.get(key) for key in required):
    raise SystemExit(1)
if values["KIVOU_FOUNDER_HOSTNAME"] != "control.kivou.eu":
    raise SystemExit(1)
if values["KIVOU_FOUNDER_ENVIRONMENT"] != "PRODUCTION":
    raise SystemExit(1)
if values["KIVOU_FOUNDER_ALLOWED_USER"] != "rodrigue":
    raise SystemExit(1)
if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["KIVOU_FOUNDER_ALLOWED_EMAIL"]):
    raise SystemExit(1)
if not re.match(r"^postgresql(?:\+psycopg)?://", values["KIVOU_FOUNDER_DATABASE_URL"]):
    raise SystemExit(1)
secret = values["KIVOU_FOUNDER_ORIGIN_SECRET"]
if len(secret.encode("utf-8")) < 32:
    raise SystemExit(1)

with open(sys.argv[2], encoding="utf-8") as stream:
    include = stream.read()
match = re.fullmatch(
    r'''\s*set\s+\$kivou_founder_origin_secret\s+(?:"([^"]+)"|'([^']+)')\s*;\s*''',
    include,
)
if not match or (match.group(1) or match.group(2)) != secret:
    raise SystemExit(1)
PY
  then
    fail "prérequis Founder invalide : environnement Founder incomplet ou incohérent"
  fi
}

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
    if [[ "$KIVOU_ENVIRONMENT" == "staging" && "$(basename "$unit")" == "$KIVOU_FOUNDER_SYSTEMD_UNIT" ]]; then
      continue
    fi
    install -o root -g root -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
    unit_count=$((unit_count + 1))
  done
  (( unit_count > 0 )) || fail "aucune unité systemd dans $unit_dir"
  systemctl daemon-reload
  log "unités systemd synchronisées : $unit_count ($KIVOU_ENVIRONMENT)"
}

restore_founder_nginx_path() {
  local path=$1 backup=$2 existed=$3
  rm -f -- "$path" || return 1
  if [[ "$existed" -eq 1 ]]; then
    cp -a -- "$backup" "$path" || return 1
  fi
}

rollback_founder_nginx() {
  local rollback_dir=$1 available_existed=$2 enabled_existed=$3
  KIVOU_FOUNDER_NGINX_ROLLBACK_FAILURE="nettoyage du candidat"
  rm -f -- "$KIVOU_FOUNDER_NGINX_ENABLED.next" || return 1
  KIVOU_FOUNDER_NGINX_ROLLBACK_FAILURE="restauration du site disponible"
  restore_founder_nginx_path \
    "$KIVOU_FOUNDER_NGINX_AVAILABLE" "$rollback_dir/available" "$available_existed" || return 1
  KIVOU_FOUNDER_NGINX_ROLLBACK_FAILURE="restauration du site activé"
  restore_founder_nginx_path \
    "$KIVOU_FOUNDER_NGINX_ENABLED" "$rollback_dir/enabled" "$enabled_existed" || return 1
  KIVOU_FOUNDER_NGINX_ROLLBACK_FAILURE="revalidation de la configuration précédente"
  nginx -t || return 1
  KIVOU_FOUNDER_NGINX_ROLLBACK_FAILURE="rechargement de la configuration précédente"
  systemctl reload nginx || return 1
}

fail_founder_nginx_transaction() {
  local reason=$1 rollback_dir=$2 available_existed=$3 enabled_existed=$4
  if ! rollback_founder_nginx "$rollback_dir" "$available_existed" "$enabled_existed"; then
    fail "ROLLBACK NGINX FOUNDER INCOMPLET : $KIVOU_FOUNDER_NGINX_ROLLBACK_FAILURE ; sauvegardes conservées : $rollback_dir ; intervention manuelle requise"
  fi
  rm -rf -- "$rollback_dir" || fail "ROLLBACK NGINX FOUNDER INCOMPLET : nettoyage ; intervention manuelle requise"
  fail "$reason ; configuration précédente restaurée"
}

check_founder_health() {
  local attempt
  [[ "$KIVOU_FOUNDER_HEALTH_ATTEMPTS" =~ ^[1-9][0-9]*$ ]] || fail "nombre de tentatives readiness Founder invalide"
  [[ "$KIVOU_FOUNDER_HEALTH_DELAY_SECONDS" =~ ^[0-9]+([.][0-9]+)?$ ]] || fail "délai readiness Founder invalide"
  [[ "$KIVOU_FOUNDER_HEALTH_MAX_TIME" =~ ^[1-9][0-9]*$ ]] || fail "timeout readiness Founder invalide"
  for ((attempt = 1; attempt <= KIVOU_FOUNDER_HEALTH_ATTEMPTS; attempt++)); do
    if curl --fail --silent --show-error --max-time "$KIVOU_FOUNDER_HEALTH_MAX_TIME" \
      "$KIVOU_FOUNDER_HEALTH_URL" >/dev/null; then
      return
    fi
    if (( attempt < KIVOU_FOUNDER_HEALTH_ATTEMPTS )); then
      sleep "$KIVOU_FOUNDER_HEALTH_DELAY_SECONDS"
    fi
  done
  fail "readiness Founder épuisée après $KIVOU_FOUNDER_HEALTH_ATTEMPTS tentatives"
}

sync_founder_nginx() {
  local source="$KIVOU_RELEASE_DIR/ops/nginx/kivou-founder-control.conf"
  local rollback_dir available_existed=0 enabled_existed=0
  [[ -f "$source" && -r "$source" ]] || fail "vhost Founder introuvable : $source"
  mkdir -p "$(dirname "$KIVOU_FOUNDER_NGINX_AVAILABLE")" "$(dirname "$KIVOU_FOUNDER_NGINX_ENABLED")"
  rollback_dir=$(mktemp -d)
  if [[ -e "$KIVOU_FOUNDER_NGINX_AVAILABLE" || -L "$KIVOU_FOUNDER_NGINX_AVAILABLE" ]]; then
    cp -a -- "$KIVOU_FOUNDER_NGINX_AVAILABLE" "$rollback_dir/available"
    available_existed=1
  fi
  if [[ -e "$KIVOU_FOUNDER_NGINX_ENABLED" || -L "$KIVOU_FOUNDER_NGINX_ENABLED" ]]; then
    cp -a -- "$KIVOU_FOUNDER_NGINX_ENABLED" "$rollback_dir/enabled"
    enabled_existed=1
  fi

  if ! install -o root -g root -m 0644 "$source" "$KIVOU_FOUNDER_NGINX_AVAILABLE"; then
    fail_founder_nginx_transaction \
      "installation du vhost Founder échouée" "$rollback_dir" "$available_existed" "$enabled_existed"
  fi
  if ! ln -sfn "$KIVOU_FOUNDER_NGINX_AVAILABLE" "$KIVOU_FOUNDER_NGINX_ENABLED.next"; then
    fail_founder_nginx_transaction \
      "préparation du lien nginx Founder échouée" "$rollback_dir" "$available_existed" "$enabled_existed"
  fi
  if ! mv -Tf "$KIVOU_FOUNDER_NGINX_ENABLED.next" "$KIVOU_FOUNDER_NGINX_ENABLED"; then
    fail_founder_nginx_transaction \
      "activation du lien nginx Founder échouée" "$rollback_dir" "$available_existed" "$enabled_existed"
  fi

  if ! nginx -t; then
    fail_founder_nginx_transaction \
      "validation nginx Founder échouée" "$rollback_dir" "$available_existed" "$enabled_existed"
  fi
  if ! systemctl reload nginx; then
    fail_founder_nginx_transaction \
      "rechargement nginx Founder échoué" "$rollback_dir" "$available_existed" "$enabled_existed"
  fi
  rm -rf -- "$rollback_dir"
}

sync_founder_surface() {
  local frontend_target="$KIVOU_RELEASE_DIR/frontend/dist-founder"
  local unit_source="$KIVOU_RELEASE_DIR/ops/systemd/kivou-founder-api.service"
  [[ -d "$frontend_target" ]] || fail "build frontend Founder introuvable : $frontend_target"
  [[ -f "$unit_source" && -r "$unit_source" ]] || fail "unité systemd Founder introuvable : $unit_source"

  install -d -o "$KIVOU_FOUNDER_FRONTEND_OWNER" -g "$KIVOU_FOUNDER_FRONTEND_GROUP" -m 0755 \
    "$(dirname "$KIVOU_FOUNDER_FRONTEND_LINK")"
  if [[ "$(readlink -f "$KIVOU_FOUNDER_FRONTEND_LINK" 2>/dev/null || true)" != "$frontend_target" ]]; then
    preserve_previous "$KIVOU_FOUNDER_FRONTEND_LINK"
    activate "$frontend_target" "$KIVOU_FOUNDER_FRONTEND_LINK"
  fi
  install -o root -g root -m 0644 "$unit_source" "$KIVOU_FOUNDER_SYSTEMD_UNIT_PATH"
  systemctl daemon-reload
  systemctl enable "$KIVOU_FOUNDER_SYSTEMD_UNIT"
  systemctl restart "$KIVOU_FOUNDER_SYSTEMD_UNIT"
  check_founder_health
  sync_founder_nginx
  log "surface Founder synchronisée"
}

for dependency in git uv npm createdb dropdb pg_restore runuser systemctl install; do
  command -v "$dependency" >/dev/null 2>&1 || fail "$dependency introuvable"
done
command -v python3 >/dev/null 2>&1 || fail "python3 introuvable"
[[ -x "$KIVOU_BACKUP_SCRIPT" ]] || fail "helper de sauvegarde introuvable"
[[ -x "$KIVOU_READINESS_SCRIPT" ]] || fail "helper de readiness introuvable"
if [[ "$KIVOU_ENVIRONMENT" == "production" ]]; then
  for dependency in curl nginx; do
    command -v "$dependency" >/dev/null 2>&1 || fail "$dependency introuvable"
  done
  check_founder_prerequisites
fi

if [[ "$(readlink -f "$KIVOU_BACKEND_LINK" 2>/dev/null || true)" == "$KIVOU_RELEASE_DIR" ]] \
  && [[ "$(readlink -f "$KIVOU_FRONTEND_LINK" 2>/dev/null || true)" == "$KIVOU_RELEASE_DIR/frontend/dist" ]]; then
  sync_systemd_units "$KIVOU_RELEASE_DIR"
  "$KIVOU_READINESS_SCRIPT" "$KIVOU_SYSTEMD_UNIT" "$KIVOU_READINESS_PORT"
  if [[ "$KIVOU_ENVIRONMENT" == "production" ]]; then
    sync_founder_surface
  fi
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
if [[ "$KIVOU_ENVIRONMENT" == "production" ]]; then
  npm --prefix "$KIVOU_RELEASE_DIR/frontend" run build:founder
fi
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

preserve_previous "$KIVOU_BACKEND_LINK"
preserve_previous "$KIVOU_FRONTEND_LINK"
activate "$KIVOU_RELEASE_DIR" "$KIVOU_BACKEND_LINK"
activate "$KIVOU_RELEASE_DIR/frontend/dist" "$KIVOU_FRONTEND_LINK"
sync_systemd_units "$KIVOU_RELEASE_DIR"
systemctl restart "$KIVOU_SYSTEMD_UNIT"
"$KIVOU_READINESS_SCRIPT" "$KIVOU_SYSTEMD_UNIT" "$KIVOU_READINESS_PORT"
if [[ "$KIVOU_ENVIRONMENT" == "production" ]]; then
  sync_founder_surface
fi
trap - EXIT
cleanup
log "release active : $KIVOU_SHA ($KIVOU_ENVIRONMENT)"
