# Kivou — activation contrôlée du runtime de production

## Portée et règle de Release 1

Ce fichier est le runbook d'une activation ultérieure. **Release 1 est de la
documentation uniquement : ne pas exécuter ces commandes pendant sa revue ou
sa livraison.** Une autorisation de production distincte, un SHA `main` revu et
les preuves de chaque stop gate sont nécessaires avant toute exécution.

Cette procédure ne crée ni ne modifie aucun enregistrement DNS, paiement ou
configuration Stripe, message SMTP, compte ou appel de provider. Acquisition,
Hermes, Apollo, Instantly et toute prospection restent exclus et désactivés.
Elle ne lit jamais un secret dans le shell : les deux fichiers d'environnement
existants sont seulement contrôlés par métadonnées puis lus par systemd.

Aucune ancienne release et aucune sauvegarde ne sont supprimées. Chaque
rollback conserve aussi ses captures. Arrêter au premier échec ; ne jamais
continuer « à la main » après un stop gate rouge.

Les blocs sont à copier dans l'ordre dans le même shell root-administré. Ils
n'affichent aucune variable secrète et commencent tous en mode Bash strict.

## 1. Vérifier et extraire le SHA exact de `main`

Préconditions : la deploy key GitHub est en lecture seule, son empreinte et le
fichier `known_hosts` ont déjà été revus hors de ce runbook. Le checkout est
construit dans une nouvelle release ; aucun lien actif n'est touché.

```bash
set -euo pipefail
KIVOU_RELEASE_REMOTE=git@github.com:bruppacherrodrigue-art/Kivou.git
KIVOU_DEPLOY_KEY=/srv/kivou/.ssh/github_deploy
KIVOU_KNOWN_HOSTS=/etc/nginx/kivou-github-known-hosts
KIVOU_PRODUCTION_HOST=kivou.eu
KIVOU_PRODUCTION_WWW_HOST=www.kivou.eu
KIVOU_API_PORT=8000

printf '%s' 'SHA main revu (40 hex): ' >/dev/tty
IFS= read -r KIVOU_RELEASE_SHA </dev/tty
printf '%s\n' "$KIVOU_RELEASE_SHA" | grep -Eq '^[0-9a-f]{40}$'
test "$KIVOU_PRODUCTION_HOST" = kivou.eu
test "$KIVOU_PRODUCTION_WWW_HOST" = www.kivou.eu
test "$KIVOU_API_PORT" = 8000
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_DEPLOY_KEY")" = kivou:kivou:600
sudo test -f "$KIVOU_KNOWN_HOSTS"
sudo test ! -L "$KIVOU_KNOWN_HOSTS"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_KNOWN_HOSTS")" = root:root:644
sudo -u kivou test -r "$KIVOU_KNOWN_HOSTS"
sudo -u kivou test ! -w "$KIVOU_KNOWN_HOSTS"

KIVOU_GIT_SSH_COMMAND="/usr/bin/ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KIVOU_KNOWN_HOSTS -o GlobalKnownHostsFile=/dev/null -i $KIVOU_DEPLOY_KEY"
KIVOU_REMOTE_MAIN_SHA=$(sudo -u kivou /usr/bin/env -i \
  HOME=/srv/kivou PATH=/usr/bin:/bin \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  GIT_SSH_COMMAND="$KIVOU_GIT_SSH_COMMAND" \
  /usr/bin/git ls-remote --exit-code "$KIVOU_RELEASE_REMOTE" refs/heads/main | \
  awk '$2 == "refs/heads/main" {print $1}')
test "$KIVOU_REMOTE_MAIN_SHA" = "$KIVOU_RELEASE_SHA"

KIVOU_RELEASE_UTC=$(date -u +%Y%m%dT%H%M%SZ)
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_RELEASE_SHA" | cut -c1-12)
KIVOU_BACKEND_RELEASE_DIR=/srv/kivou/releases/backend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT
KIVOU_FRONTEND_RELEASE_DIR=/srv/kivou/releases/frontend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT
case "$KIVOU_BACKEND_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
case "$KIVOU_FRONTEND_RELEASE_DIR" in
  (/srv/kivou/releases/frontend-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
sudo install -o kivou -g kivou -m 755 -d /srv/kivou/releases
sudo test ! -e "$KIVOU_BACKEND_RELEASE_DIR"
sudo test ! -e "$KIVOU_FRONTEND_RELEASE_DIR"

kivou_git() {
  sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
    /usr/bin/git "$@"
}
kivou_git init --quiet --initial-branch=main "$KIVOU_BACKEND_RELEASE_DIR"
kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" remote add origin "$KIVOU_RELEASE_REMOTE"
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  GIT_SSH_COMMAND="$KIVOU_GIT_SSH_COMMAND" \
  /usr/bin/git -C "$KIVOU_BACKEND_RELEASE_DIR" fetch --no-tags origin \
  +refs/heads/main:refs/kivou-rollout/reviewed-main
test "$(kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" rev-parse refs/kivou-rollout/reviewed-main)" = "$KIVOU_RELEASE_SHA"
kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" cat-file -e "$KIVOU_RELEASE_SHA^{commit}"
kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" checkout --detach "$KIVOU_RELEASE_SHA"
if kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" symbolic-ref -q HEAD; then exit 69; fi
test "$(kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
test -z "$(kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" status --porcelain)"
```

Stop gate : le SHA distant de `refs/heads/main`, le HEAD détaché et le SHA revu
sont identiques ; le checkout est propre.

## 2. Construire les releases verrouillées et immuables

`uv.lock` et `frontend/package-lock.json` sont les seules autorités de
dépendances. Les tests et builds restent hors réseau applicatif : aucun serveur
Kivou n'est démarré.

```bash
set -euo pipefail
case "$KIVOU_BACKEND_RELEASE_DIR" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
case "$KIVOU_FRONTEND_RELEASE_DIR" in (/srv/kivou/releases/frontend-*) ;; (*) exit 69 ;; esac
test "$(kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
test -z "$(kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" status --porcelain)"

sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin \
  /usr/bin/env --chdir="$KIVOU_BACKEND_RELEASE_DIR" \
  /usr/local/bin/uv sync --frozen --extra server --extra postgres
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin \
  /usr/bin/env --chdir="$KIVOU_BACKEND_RELEASE_DIR" /usr/local/bin/uv run pytest
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin \
  /usr/bin/env --chdir="$KIVOU_BACKEND_RELEASE_DIR" /usr/local/bin/uv run ruff check .

sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  /usr/bin/env --chdir="$KIVOU_BACKEND_RELEASE_DIR/frontend" /usr/bin/npm ci
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  /usr/bin/env --chdir="$KIVOU_BACKEND_RELEASE_DIR/frontend" /usr/bin/npm run test -- --run
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  /usr/bin/env --chdir="$KIVOU_BACKEND_RELEASE_DIR/frontend" /usr/bin/npm run build
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  /usr/bin/env --chdir="$KIVOU_BACKEND_RELEASE_DIR/frontend" /usr/bin/npm run typecheck
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  /usr/bin/env --chdir="$KIVOU_BACKEND_RELEASE_DIR/frontend" /usr/bin/npm run lint
sudo -u kivou test -f "$KIVOU_BACKEND_RELEASE_DIR/frontend/dist/index.html"
sudo -u kivou test ! -L "$KIVOU_BACKEND_RELEASE_DIR/frontend/dist/index.html"
test -n "$(sudo -u kivou find "$KIVOU_BACKEND_RELEASE_DIR/frontend/dist/assets" -type f -print -quit)"
test -z "$(kivou_git -C "$KIVOU_BACKEND_RELEASE_DIR" status --porcelain)"

sudo install -o root -g root -m 755 -d "$KIVOU_FRONTEND_RELEASE_DIR"
sudo cp -a "$KIVOU_BACKEND_RELEASE_DIR/frontend/dist/." "$KIVOU_FRONTEND_RELEASE_DIR/"
sudo test -f "$KIVOU_FRONTEND_RELEASE_DIR/index.html"
sudo test ! -L "$KIVOU_FRONTEND_RELEASE_DIR/index.html"
test -n "$(sudo find "$KIVOU_FRONTEND_RELEASE_DIR/assets" -type f -print -quit)"
sudo chown -R root:root "$KIVOU_BACKEND_RELEASE_DIR" "$KIVOU_FRONTEND_RELEASE_DIR"
sudo chmod -R a-w "$KIVOU_BACKEND_RELEASE_DIR" "$KIVOU_FRONTEND_RELEASE_DIR"
test -z "$(sudo find "$KIVOU_BACKEND_RELEASE_DIR" -perm /222 -print -quit)"
test -z "$(sudo find "$KIVOU_FRONTEND_RELEASE_DIR" -perm /222 -print -quit)"
test "$(sudo -u kivou /usr/bin/git -C "$KIVOU_BACKEND_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
test -z "$(sudo -u kivou /usr/bin/git -C "$KIVOU_BACKEND_RELEASE_DIR" status --porcelain)"
```

Stop gate : backend et frontend ont des répertoires séparés, horodatés,
`root:root`, sans aucun write bit et le build frontend réel contient
`index.html` et au moins un asset.

## 3. Préflight des secrets et arrêt des runtimes

Le contenu des fichiers n'est ni chargé, ni copié, ni affiché. Ce bloc doit
précéder toute installation. L'absence d'une unité ancienne est acceptable ;
une unité présente est arrêtée et désactivée.

```bash
set -euo pipefail
for KIVOU_ENV_FILE in /etc/kivou/production.env /etc/kivou/swiss-backup.env; do
  sudo test -f "$KIVOU_ENV_FILE"
  sudo test ! -L "$KIVOU_ENV_FILE"
  test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ENV_FILE")" = root:root:600
done

KIVOU_DISABLED_UNITS=(
  kivou-api.service
  kivou-alerts.service kivou-alerts.timer
  kivou-backup-local.service kivou-backup.service kivou-backup.timer
  kivou-ingest@simap.service kivou-ingest-simap.timer
  kivou-ingest@boamp.service kivou-ingest-boamp.timer
  kivou-ingest@decp.service kivou-ingest-decp.timer
  kivou-ingest@ted.service kivou-ingest-ted.timer
)
for KIVOU_UNIT in "${KIVOU_DISABLED_UNITS[@]}"; do
  if sudo systemctl list-unit-files "$KIVOU_UNIT" --no-legend | grep -q .; then
    sudo systemctl disable --now "$KIVOU_UNIT"
  fi
done

sudo systemd-analyze verify "$KIVOU_BACKEND_RELEASE_DIR"/ops/systemd/production/*.service "$KIVOU_BACKEND_RELEASE_DIR"/ops/systemd/production/*.timer
```

Stop gate : les deux fichiers sont des fichiers réguliers non symboliques en
`root:root 600`, toutes les unités de cette release sont désactivées, et
`systemd-analyze verify` est vert.

## 4. Installer les unités atomiquement, sans les activer

Les fichiers `.new` sont tous prêts avant la première publication. Aucune
activation de timer n'appartient à ce bloc.

```bash
set -euo pipefail
KIVOU_UNIT_NAMES=(
  kivou-api.service
  kivou-alerts.service kivou-alerts.timer
  kivou-backup-local.service kivou-backup.service kivou-backup.timer
  kivou-ingest@.service
  kivou-ingest-simap.timer kivou-ingest-boamp.timer
  kivou-ingest-decp.timer kivou-ingest-ted.timer
)
for KIVOU_UNIT in "${KIVOU_UNIT_NAMES[@]}"; do
  KIVOU_UNIT_SOURCE="$KIVOU_BACKEND_RELEASE_DIR/ops/systemd/production/$KIVOU_UNIT"
  KIVOU_UNIT_NEW="/etc/systemd/system/$KIVOU_UNIT.new"
  sudo test -f "$KIVOU_UNIT_SOURCE"
  sudo install -o root -g root -m 644 "$KIVOU_UNIT_SOURCE" "$KIVOU_UNIT_NEW"
  sudo chown root:root "$KIVOU_UNIT_NEW"
  sudo chmod 644 "$KIVOU_UNIT_NEW"
done
for KIVOU_UNIT in "${KIVOU_UNIT_NAMES[@]}"; do
  sudo mv -Tf "/etc/systemd/system/$KIVOU_UNIT.new" "/etc/systemd/system/$KIVOU_UNIT"
done
sudo systemctl daemon-reload
for KIVOU_UNIT in "${KIVOU_UNIT_NAMES[@]}"; do
  test "$(sudo stat -c '%U:%G:%a' "/etc/systemd/system/$KIVOU_UNIT")" = root:root:644
done
```

Stop gate : chaque unité installée est `root:root 644`, le daemon a été
rechargé, mais aucun service ni timer n'a été activé.

## 5. Capturer toutes les cibles de rollback avant mutation

Les seules valeurs de lien acceptées sont `ABSENT` ou une release immuable du
type attendu. Les fichiers et liens nginx sont copiés ou marqués `ABSENT` dans
un répertoire borné avant toute bascule. Le fichier d'état ne contient aucun
secret. Si un lien était absent, le rollback n'inventera aucune cible.

```bash
set -euo pipefail
KIVOU_ROLLBACK_UTC=$(date -u +%Y%m%dT%H%M%SZ)
KIVOU_ROLLBACK_DIR=/root/kivou-rollbacks/production-runtime-$KIVOU_ROLLBACK_UTC
case "$KIVOU_ROLLBACK_DIR" in (/root/kivou-rollbacks/production-runtime-*) ;; (*) exit 69 ;; esac
sudo install -o root -g root -m 700 -d /root/kivou-rollbacks "$KIVOU_ROLLBACK_DIR"

if sudo test -L /srv/kivou/app; then
  KIVOU_PREVIOUS_APP_TARGET=$(sudo readlink -f /srv/kivou/app)
else
  sudo test ! -e /srv/kivou/app
  KIVOU_PREVIOUS_APP_TARGET=ABSENT
fi
case "$KIVOU_PREVIOUS_APP_TARGET" in
  (ABSENT) ;;
  (/srv/kivou/releases/backend-*)
    sudo test -d "$KIVOU_PREVIOUS_APP_TARGET"
    test -z "$(sudo find "$KIVOU_PREVIOUS_APP_TARGET" -perm /222 -print -quit)"
    ;;
  (*) exit 69 ;;
esac

if sudo test -L /srv/kivou/frontend; then
  KIVOU_PREVIOUS_FRONTEND_TARGET=$(sudo readlink -f /srv/kivou/frontend)
else
  sudo test ! -e /srv/kivou/frontend
  KIVOU_PREVIOUS_FRONTEND_TARGET=ABSENT
fi
case "$KIVOU_PREVIOUS_FRONTEND_TARGET" in
  (ABSENT) ;;
  (/srv/kivou/releases/frontend-*)
    sudo test -d "$KIVOU_PREVIOUS_FRONTEND_TARGET"
    test -z "$(sudo find "$KIVOU_PREVIOUS_FRONTEND_TARGET" -perm /222 -print -quit)"
    ;;
  (*) exit 69 ;;
esac

KIVOU_ROLLOUT_STATE=/etc/kivou/production-runtime.state
KIVOU_ROLLOUT_STATE_NEW=/etc/kivou/production-runtime.state.new
sudo install -o root -g root -m 600 /dev/null "$KIVOU_ROLLOUT_STATE_NEW"
printf '%s\n%s\n%s\n' "$KIVOU_PREVIOUS_APP_TARGET" "$KIVOU_PREVIOUS_FRONTEND_TARGET" "$KIVOU_ROLLBACK_DIR" | sudo tee "$KIVOU_ROLLOUT_STATE_NEW" >/dev/null
sudo mv -Tf "$KIVOU_ROLLOUT_STATE_NEW" "$KIVOU_ROLLOUT_STATE"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_STATE")" = root:root:600

KIVOU_NGINX_CAPTURE_PATHS=(
  /etc/nginx/conf.d/kivou-limits.conf
  /etc/nginx/kivou-proxy-params.conf
  /etc/nginx/kivou-production-security-headers.conf
  /etc/nginx/kivou-production-sensitive-link-security-headers.conf
  /etc/nginx/kivou-sensitive-links-gate.conf
  /etc/nginx/sites-available/kivou-production-default-deny
  /etc/nginx/sites-available/kivou
  /etc/nginx/sites-available/kivou-www
)
sudo install -o root -g root -m 700 -d "$KIVOU_ROLLBACK_DIR/nginx"
for KIVOU_NGINX_PATH in "${KIVOU_NGINX_CAPTURE_PATHS[@]}"; do
  KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_NGINX_PATH" | sed 's#^/##; s#/#__#g')
  if sudo test -e "$KIVOU_NGINX_PATH" || sudo test -L "$KIVOU_NGINX_PATH"; then
    sudo cp -a "$KIVOU_NGINX_PATH" "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved"
  else
    sudo touch "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT"
  fi
done
for KIVOU_SITE_LINK in /etc/nginx/sites-enabled/kivou-production-default-deny /etc/nginx/sites-enabled/kivou /etc/nginx/sites-enabled/kivou-www; do
  KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_SITE_LINK" | sed 's#^/##; s#/#__#g')
  if sudo test -L "$KIVOU_SITE_LINK"; then
    KIVOU_SITE_TARGET=$(sudo readlink -f "$KIVOU_SITE_LINK")
    case "$KIVOU_SITE_TARGET" in (/etc/nginx/sites-available/*) ;; (*) exit 69 ;; esac
    printf '%s\n' "$KIVOU_SITE_TARGET" | sudo tee "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.target" >/dev/null
  else
    sudo test ! -e "$KIVOU_SITE_LINK"
    sudo touch "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT"
  fi
done
sudo chmod -R a-w "$KIVOU_ROLLBACK_DIR"
```

Stop gate : les anciennes cibles app/frontend, les huit destinations nginx et
les trois liens `sites-enabled` sont capturés ou explicitement marqués absents.
Rien n'a encore été basculé ni activé.

## 6. Prévalider la sauvegarde candidate et exercer le restore

Avant la bascule, `/srv/kivou/app` peut être absent ou pointer vers une ancienne
release : il ne fait donc pas autorité. Deux services transitoires synchrones
exécutent directement les scripts du SHA candidat. Le premier ne reçoit que
`production.env`; le second ne reçoit que `swiss-backup.env` et son cache
restic. `--wait --pipe --collect` propage l'échec de chaque script et retire
l'unité transitoire. Le restore hors site ne commence qu'après leurs succès.

```bash
set -euo pipefail
case "$KIVOU_BACKEND_RELEASE_DIR" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
sudo test -x "$KIVOU_BACKEND_RELEASE_DIR/ops/bin/kivou-backup.sh"
sudo test -x "$KIVOU_BACKEND_RELEASE_DIR/ops/bin/kivou-restic-upload.sh"
sudo systemd-run --wait --pipe --collect --unit=kivou-backup-local-preflight \
  --expand-environment=no \
  --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_BACKEND_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/production.env \
  --property=TimeoutStartSec=2h \
  --property=UMask=0077 \
  --property=NoNewPrivileges=yes \
  --property=PrivateTmp=yes --property=PrivateDevices=yes \
  --property=ProtectSystem=strict --property=ProtectHome=yes \
  --property=InaccessiblePaths=/srv/kivou/.ssh \
  --property=ReadOnlyPaths="$KIVOU_BACKEND_RELEASE_DIR" \
  --property=ReadWritePaths=/srv/kivou/backups \
  --property=ProtectKernelTunables=yes \
  --property=ProtectKernelModules=yes \
  --property=ProtectControlGroups=yes \
  --property=RestrictSUIDSGID=yes --property=LockPersonality=yes \
  --property="RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" \
  -- "$KIVOU_BACKEND_RELEASE_DIR/ops/bin/kivou-backup.sh"
KIVOU_LOCAL_DUMP=$(sudo -u kivou find /srv/kivou/backups -maxdepth 1 -type f -name 'kivou-*.dump' -printf '%T@ %p\n' | sort -nr | awk 'NR == 1 {print $2}')
case "$KIVOU_LOCAL_DUMP" in (/srv/kivou/backups/kivou-*.dump) ;; (*) exit 66 ;; esac
sudo -u kivou test -f "$KIVOU_LOCAL_DUMP"
sudo -u kivou test ! -L "$KIVOU_LOCAL_DUMP"
sudo -u kivou pg_restore --list "$KIVOU_LOCAL_DUMP" >/dev/null

sudo systemd-run --wait --pipe --collect --unit=kivou-backup-offsite-preflight \
  --expand-environment=no \
  --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_BACKEND_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/swiss-backup.env \
  --property=Environment=RESTIC_CACHE_DIR=/var/cache/kivou-restic \
  --property=CacheDirectory=kivou-restic \
  --property=CacheDirectoryMode=0700 \
  --property=TimeoutStartSec=6h \
  --property=UMask=0077 \
  --property=NoNewPrivileges=yes \
  --property=PrivateTmp=yes --property=PrivateDevices=yes \
  --property=ProtectSystem=strict --property=ProtectHome=yes \
  --property=InaccessiblePaths=/srv/kivou/.ssh \
  --property=ReadOnlyPaths="$KIVOU_BACKEND_RELEASE_DIR" \
  --property=ReadWritePaths=/srv/kivou/backups \
  --property=ProtectKernelTunables=yes \
  --property=ProtectKernelModules=yes \
  --property=ProtectControlGroups=yes \
  --property=RestrictSUIDSGID=yes --property=LockPersonality=yes \
  --property="RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" \
  -- "$KIVOU_BACKEND_RELEASE_DIR/ops/bin/kivou-restic-upload.sh"

KIVOU_RESTORE_ROOT=/srv/kivou/restore-drills
KIVOU_RESTORE_DIR=$KIVOU_RESTORE_ROOT/restore-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT
case "$KIVOU_RESTORE_DIR" in (/srv/kivou/restore-drills/restore-*) ;; (*) exit 69 ;; esac
sudo install -o kivou -g kivou -m 700 -d "$KIVOU_RESTORE_ROOT"
sudo test ! -e "$KIVOU_RESTORE_DIR"
sudo install -o kivou -g kivou -m 700 -d "$KIVOU_RESTORE_DIR"
KIVOU_RESTORE_DB=kivou_restore_${KIVOU_RELEASE_SHORT}_$(date -u +%H%M%S)
printf '%s\n' "$KIVOU_RESTORE_DB" | grep -Eq '^kivou_restore_[a-z0-9_]{1,40}$'
KIVOU_RESTORE_DB_CREATED=0
kivou_restore_cleanup() {
  if [ "$KIVOU_RESTORE_DB_CREATED" = 1 ]; then
    sudo -u postgres dropdb --if-exists "$KIVOU_RESTORE_DB"
  fi
  case "$KIVOU_RESTORE_DIR" in (/srv/kivou/restore-drills/restore-*) ;; (*) exit 69 ;; esac
  sudo find "$KIVOU_RESTORE_DIR" -xdev -mindepth 1 -delete
  sudo rmdir "$KIVOU_RESTORE_DIR"
}
trap kivou_restore_cleanup EXIT

sudo systemd-run --wait --collect --unit=kivou-restore-drill \
  --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=EnvironmentFile=/etc/kivou/swiss-backup.env \
  --property=Environment=RESTIC_CACHE_DIR=/var/cache/kivou-restic \
  --property=CacheDirectory=kivou-restic --property=CacheDirectoryMode=0700 \
  --property=UMask=0077 --property=NoNewPrivileges=yes \
  --property=PrivateTmp=yes --property=ProtectHome=yes \
  --property=ProtectSystem=strict \
  --property=ReadWritePaths="$KIVOU_RESTORE_DIR" \
  -- /usr/bin/restic restore latest --host kivou-production-01 \
  --tag kivou-postgresql --target "$KIVOU_RESTORE_DIR"
KIVOU_RESTORED_DUMP=$(sudo find "$KIVOU_RESTORE_DIR" -xdev -type f -name 'kivou-*.dump' -print -quit)
case "$KIVOU_RESTORED_DUMP" in ("$KIVOU_RESTORE_DIR"/*) ;; (*) exit 66 ;; esac
sudo test -f "$KIVOU_RESTORED_DUMP"
sudo test ! -L "$KIVOU_RESTORED_DUMP"
sudo -u kivou pg_restore --list "$KIVOU_RESTORED_DUMP" >/dev/null
sudo chown -R postgres:postgres "$KIVOU_RESTORE_DIR"
sudo -u postgres createdb --template=template0 "$KIVOU_RESTORE_DB"
KIVOU_RESTORE_DB_CREATED=1
sudo -u postgres pg_restore --exit-on-error --no-owner --no-privileges \
  --dbname "$KIVOU_RESTORE_DB" "$KIVOU_RESTORED_DUMP"
KIVOU_RESTORED_ALEMBIC=$(sudo -u postgres psql -Atqc 'SELECT version_num FROM alembic_version' "$KIVOU_RESTORE_DB")
test -n "$KIVOU_RESTORED_ALEMBIC"
sudo -u postgres dropdb "$KIVOU_RESTORE_DB"
KIVOU_RESTORE_DB_CREATED=0
trap - EXIT
case "$KIVOU_RESTORE_DIR" in (/srv/kivou/restore-drills/restore-*) ;; (*) exit 69 ;; esac
sudo find "$KIVOU_RESTORE_DIR" -xdev -mindepth 1 -delete
sudo rmdir "$KIVOU_RESTORE_DIR"
```

Stop gate : les deux scripts du SHA candidat ont réussi dans deux environnements
séparés, le dump local passe `pg_restore --list`, puis le dernier snapshot
restic filtré est réellement restauré dans une base temporaire. La révision
Alembic est lisible et le nettoyage est terminé. Aucun paiement, e-mail ou
provider n'est contacté.

## 7. Prouver le certificat et construire le candidat nginx hermétique

Le certificat doit déjà exister. Ce runbook ne lance pas certbot et n'ajoute
pas HSTS. Le candidat inclut réellement le default deny, les limites, le site
apex et la redirection `www`, sans dépendre des sites actifs.

```bash
set -euo pipefail
KIVOU_CERT_DIR=/etc/letsencrypt/live/kivou.eu
for KIVOU_CERT_FILE in fullchain.pem privkey.pem chain.pem; do
  sudo test -e "$KIVOU_CERT_DIR/$KIVOU_CERT_FILE"
  sudo test -r "$KIVOU_CERT_DIR/$KIVOU_CERT_FILE"
done
KIVOU_CERT_SANS=$(sudo openssl x509 -in "$KIVOU_CERT_DIR/fullchain.pem" -noout -ext subjectAltName | tr ',' '\n' | sed -n 's/^[[:space:]]*DNS://p' | sort -u)
grep -Fxq "$KIVOU_PRODUCTION_HOST" <<<"$KIVOU_CERT_SANS"
grep -Fxq "$KIVOU_PRODUCTION_WWW_HOST" <<<"$KIVOU_CERT_SANS"

KIVOU_NGINX_CANDIDATE=$(sudo mktemp -d /etc/nginx/.kivou-production-candidate.XXXXXX)
case "$KIVOU_NGINX_CANDIDATE" in (/etc/nginx/.kivou-production-candidate.*) ;; (*) exit 69 ;; esac
sudo chmod 700 "$KIVOU_NGINX_CANDIDATE"
sudo install -o root -g root -m 644 \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-limits.conf" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-proxy-params.conf" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production-security-headers.conf" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production-sensitive-link-security-headers.conf" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production-default-deny.conf" \
  "$KIVOU_NGINX_CANDIDATE/"
sudo install -o root -g root -m 600 \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-sensitive-links-closed.conf" \
  "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf"

sed \
  -e "s/PRODUCTION_HOST/$KIVOU_PRODUCTION_HOST/g" \
  -e "s/KIVOU_API_PORT/$KIVOU_API_PORT/g" \
  -e "s#/etc/nginx/kivou-proxy-params.conf#$KIVOU_NGINX_CANDIDATE/kivou-proxy-params.conf#g" \
  -e "s#/etc/nginx/kivou-production-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-production-security-headers.conf#g" \
  -e "s#/etc/nginx/kivou-production-sensitive-link-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-production-sensitive-link-security-headers.conf#g" \
  -e "s#/etc/nginx/kivou-sensitive-links-gate.conf#$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf#g" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production.conf" | \
  sudo tee "$KIVOU_NGINX_CANDIDATE/kivou-production.conf" >/dev/null
sed -e "s/PRODUCTION_WWW_HOST/$KIVOU_PRODUCTION_WWW_HOST/g" \
  -e "s/PRODUCTION_HOST/$KIVOU_PRODUCTION_HOST/g" \
  -e "s#/etc/nginx/kivou-production-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-production-security-headers.conf#g" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production-www.conf" | \
  sudo tee "$KIVOU_NGINX_CANDIDATE/kivou-production-www.conf" >/dev/null
if sudo grep -ERn 'PRODUCTION_HOST|PRODUCTION_WWW_HOST|KIVOU_API_PORT' "$KIVOU_NGINX_CANDIDATE"; then exit 69; fi

sudo tee "$KIVOU_NGINX_CANDIDATE/nginx.conf" >/dev/null <<EOF
pid $KIVOU_NGINX_CANDIDATE/nginx.pid;
error_log stderr;
events {}
http {
    include /etc/nginx/mime.types;
    include $KIVOU_NGINX_CANDIDATE/kivou-limits.conf;
    include $KIVOU_NGINX_CANDIDATE/kivou-production-default-deny.conf;
    include $KIVOU_NGINX_CANDIDATE/kivou-production.conf;
    include $KIVOU_NGINX_CANDIDATE/kivou-production-www.conf;
}
EOF
sudo chmod 644 \
  "$KIVOU_NGINX_CANDIDATE/nginx.conf" \
  "$KIVOU_NGINX_CANDIDATE/kivou-limits.conf" \
  "$KIVOU_NGINX_CANDIDATE/kivou-proxy-params.conf" \
  "$KIVOU_NGINX_CANDIDATE/kivou-production-security-headers.conf" \
  "$KIVOU_NGINX_CANDIDATE/kivou-production-sensitive-link-security-headers.conf" \
  "$KIVOU_NGINX_CANDIDATE/kivou-production-default-deny.conf" \
  "$KIVOU_NGINX_CANDIDATE/kivou-production.conf" \
  "$KIVOU_NGINX_CANDIDATE/kivou-production-www.conf"
sudo chmod 600 "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf"
sudo nginx -t -c "$KIVOU_NGINX_CANDIDATE/nginx.conf"

sudo install -o root -g root -m 644 "$KIVOU_NGINX_CANDIDATE/kivou-limits.conf" /etc/nginx/conf.d/kivou-limits.conf.new
sudo install -o root -g root -m 644 "$KIVOU_NGINX_CANDIDATE/kivou-proxy-params.conf" /etc/nginx/kivou-proxy-params.conf.new
sudo install -o root -g root -m 644 "$KIVOU_NGINX_CANDIDATE/kivou-production-security-headers.conf" /etc/nginx/kivou-production-security-headers.conf.new
sudo install -o root -g root -m 644 "$KIVOU_NGINX_CANDIDATE/kivou-production-sensitive-link-security-headers.conf" /etc/nginx/kivou-production-sensitive-link-security-headers.conf.new
sudo install -o root -g root -m 600 "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf" /etc/nginx/kivou-sensitive-links-gate.conf.new
sudo install -o root -g root -m 644 "$KIVOU_NGINX_CANDIDATE/kivou-production-default-deny.conf" /etc/nginx/sites-available/kivou-production-default-deny.new
sudo install -o root -g root -m 644 "$KIVOU_NGINX_CANDIDATE/kivou-production.conf" /etc/nginx/sites-available/kivou.new
sudo install -o root -g root -m 644 "$KIVOU_NGINX_CANDIDATE/kivou-production-www.conf" /etc/nginx/sites-available/kivou-www.new
for KIVOU_SITE in kivou-production-default-deny kivou kivou-www; do
  KIVOU_SITE_LINK_NEW=/etc/nginx/sites-enabled/$KIVOU_SITE.new
  case "$KIVOU_SITE_LINK_NEW" in (/etc/nginx/sites-enabled/*.new) ;; (*) exit 69 ;; esac
  sudo test ! -e "$KIVOU_SITE_LINK_NEW"
  sudo test ! -L "$KIVOU_SITE_LINK_NEW"
  sudo ln -s "/etc/nginx/sites-available/$KIVOU_SITE" "$KIVOU_SITE_LINK_NEW"
done
```

Stop gate : le SAN contient au minimum `kivou.eu` et `www.kivou.eu`, aucun
placeholder ne subsiste, le candidat hermétique incluant le default deny passe
`nginx -t`. Tous les fichiers `.new` et liens temporaires sont prêts. La
capture immuable de l'ancien état a déjà été validée au bloc 5.

## 8. Fenêtre courte : basculer les releases, l'API puis nginx

Tous les stop gates coûteux ou susceptibles d'échouer sont maintenant verts.
Ce bloc ouvre la première fenêtre de mutation : il bascule app et frontend,
prouve l'API sur 8000, puis publie nginx. Tous les fichiers et liens sont
préparés sous un nom temporaire puis commutés atomiquement.

```bash
set -euo pipefail
KIVOU_APP_LINK_NEW=/srv/kivou/app.new-$KIVOU_RELEASE_SHORT
KIVOU_FRONTEND_LINK_NEW=/srv/kivou/frontend.new-$KIVOU_RELEASE_SHORT
case "$KIVOU_APP_LINK_NEW" in (/srv/kivou/app.new-*) ;; (*) exit 69 ;; esac
case "$KIVOU_FRONTEND_LINK_NEW" in (/srv/kivou/frontend.new-*) ;; (*) exit 69 ;; esac
sudo test ! -e "$KIVOU_APP_LINK_NEW"
sudo test ! -L "$KIVOU_APP_LINK_NEW"
sudo ln -s "$KIVOU_BACKEND_RELEASE_DIR" "$KIVOU_APP_LINK_NEW"
sudo mv -Tf "$KIVOU_APP_LINK_NEW" /srv/kivou/app
sudo test "$(sudo readlink -f /srv/kivou/app)" = "$KIVOU_BACKEND_RELEASE_DIR"
sudo test ! -e "$KIVOU_FRONTEND_LINK_NEW"
sudo test ! -L "$KIVOU_FRONTEND_LINK_NEW"
sudo ln -s "$KIVOU_FRONTEND_RELEASE_DIR" "$KIVOU_FRONTEND_LINK_NEW"
sudo mv -Tf "$KIVOU_FRONTEND_LINK_NEW" /srv/kivou/frontend
sudo test "$(sudo readlink -f /srv/kivou/frontend)" = "$KIVOU_FRONTEND_RELEASE_DIR"

sudo systemctl enable --now kivou-api.service
sudo systemctl is-active --quiet kivou-api.service
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  /srv/kivou/app/ops/bin/kivou-api-readiness.sh kivou-api.service 8000

sudo mv -Tf /etc/nginx/conf.d/kivou-limits.conf.new /etc/nginx/conf.d/kivou-limits.conf
sudo mv -Tf /etc/nginx/kivou-proxy-params.conf.new /etc/nginx/kivou-proxy-params.conf
sudo mv -Tf /etc/nginx/kivou-production-security-headers.conf.new /etc/nginx/kivou-production-security-headers.conf
sudo mv -Tf /etc/nginx/kivou-production-sensitive-link-security-headers.conf.new /etc/nginx/kivou-production-sensitive-link-security-headers.conf
sudo mv -Tf /etc/nginx/kivou-sensitive-links-gate.conf.new /etc/nginx/kivou-sensitive-links-gate.conf
sudo mv -Tf /etc/nginx/sites-available/kivou-production-default-deny.new /etc/nginx/sites-available/kivou-production-default-deny
sudo mv -Tf /etc/nginx/sites-available/kivou.new /etc/nginx/sites-available/kivou
sudo mv -Tf /etc/nginx/sites-available/kivou-www.new /etc/nginx/sites-available/kivou-www

sudo mv -Tf /etc/nginx/sites-enabled/kivou-production-default-deny.new /etc/nginx/sites-enabled/kivou-production-default-deny
sudo mv -Tf /etc/nginx/sites-enabled/kivou.new /etc/nginx/sites-enabled/kivou
sudo mv -Tf /etc/nginx/sites-enabled/kivou-www.new /etc/nginx/sites-enabled/kivou-www
sudo nginx -t
sudo systemctl reload nginx
```

Stop gate : les deux liens pointent vers les nouvelles releases, l'API répond
sur 8000, le default deny est activé, les trois sites et cinq fragments sont
publiés, puis `nginx -t` et l'unique reload sont verts.

## 9. Vérifier HTTPS puis le service backup installé

La racine publique est le health check disponible dans le contrat nginx actuel
(la route interne de santé n'est volontairement pas publiée). À ce stade, le
rollback capturé au bloc 5 est disponible. Le smoke suivant est le premier
démarrage autorisé de l'orchestrateur installé : son `Requires=` exerce le
service local, puis le service principal exerce l'upload hors site.

```bash
set -euo pipefail
KIVOU_HTTPS_HEALTH_URL=https://kivou.eu/
KIVOU_HTTPS_STATUS=$(curl --silent --show-error --output /dev/null --connect-timeout 5 --max-time 15 --write-out '%{http_code}' "$KIVOU_HTTPS_HEALTH_URL")
test "$KIVOU_HTTPS_STATUS" = 200
KIVOU_WWW_STATUS=$(curl --silent --show-error --output /dev/null --connect-timeout 5 --max-time 15 --write-out '%{http_code}' https://www.kivou.eu/)
case "$KIVOU_WWW_STATUS" in (301|302|307|308) ;; (*) exit 69 ;; esac
sudo systemctl start kivou-backup.service
if sudo systemctl is-failed --quiet kivou-backup-local.service; then exit 70; fi
if sudo systemctl is-failed --quiet kivou-backup.service; then exit 70; fi
```

Stop gate : l'apex HTTPS répond 200, `www` redirige et les unités backup
installées réussissent sur la nouvelle cible `/srv/kivou/app`. En cas d'échec,
exécuter immédiatement le rollback du bloc 11 ; le timer reste désactivé.

## 10. Prouver les sources localement avant leurs timers

Chaque source est démarrée manuellement, puis contrôlée avec `is-failed` avant
que son timer propre soit activé. Le timer de sauvegarde peut être activé car
le dump local, l'upload, le restore et le smoke des unités installées ont été
prouvés. Le service et le timer d'alertes restent désactivés : aucun smoke SMTP
n'appartient à cette release.

```bash
set -euo pipefail
sudo systemctl start kivou-ingest@simap.service
if sudo systemctl is-failed --quiet kivou-ingest@simap.service; then exit 70; fi
sudo systemctl enable --now kivou-ingest-simap.timer

sudo systemctl start kivou-ingest@boamp.service
if sudo systemctl is-failed --quiet kivou-ingest@boamp.service; then exit 70; fi
sudo systemctl enable --now kivou-ingest-boamp.timer

sudo systemctl start kivou-ingest@decp.service
if sudo systemctl is-failed --quiet kivou-ingest@decp.service; then exit 70; fi
sudo systemctl enable --now kivou-ingest-decp.timer

sudo systemctl start kivou-ingest@ted.service
if sudo systemctl is-failed --quiet kivou-ingest@ted.service; then exit 70; fi
sudo systemctl enable --now kivou-ingest-ted.timer

sudo systemctl enable --now kivou-backup.timer
sudo systemctl disable --now kivou-alerts.timer kivou-alerts.service
```

Stop gate : les quatre sources ont chacune réussi leur exécution locale avant
activation ; backup a déjà son smoke complet ; alertes restent désactivées en
attente d'un smoke SMTP séparément autorisé.

## 11. Rollback immédiat et borné

Ce bloc est autonome : il lit trois valeurs non secrètes par lignes, sans
évaluer le fichier. Il désactive d'abord les sources et timers fautifs. Il ne
restaure qu'une cible de release capturée et immuable. Si une cible était
`ABSENT`, le runtime reste désactivé et son lien courant est déplacé pour
analyse. La restauration app/frontend ne dépend jamais de la capture nginx.
Nginx n'est restauré et rechargé que si sa capture complète est encore valide.

```bash
set -euo pipefail
sudo systemctl disable --now \
  kivou-ingest-simap.timer kivou-ingest-boamp.timer \
  kivou-ingest-decp.timer kivou-ingest-ted.timer \
  kivou-backup.timer kivou-alerts.timer kivou-alerts.service
sudo systemctl stop \
  kivou-ingest@simap.service kivou-ingest@boamp.service \
  kivou-ingest@decp.service kivou-ingest@ted.service
sudo systemctl disable --now kivou-api.service

KIVOU_ROLLOUT_STATE=/etc/kivou/production-runtime.state
sudo test -f "$KIVOU_ROLLOUT_STATE"
sudo test ! -L "$KIVOU_ROLLOUT_STATE"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_STATE")" = root:root:600
test "$(sudo wc -l < "$KIVOU_ROLLOUT_STATE")" = 3
KIVOU_PREVIOUS_APP_TARGET=$(sudo sed -n '1p' "$KIVOU_ROLLOUT_STATE")
KIVOU_PREVIOUS_FRONTEND_TARGET=$(sudo sed -n '2p' "$KIVOU_ROLLOUT_STATE")
KIVOU_ROLLBACK_DIR=$(sudo sed -n '3p' "$KIVOU_ROLLOUT_STATE")
case "$KIVOU_ROLLBACK_DIR" in (/root/kivou-rollbacks/production-runtime-*) ;; (*) exit 69 ;; esac

KIVOU_FAILED_DIR=/root/kivou-rollbacks/failed-$(date -u +%Y%m%dT%H%M%SZ)
case "$KIVOU_FAILED_DIR" in (/root/kivou-rollbacks/failed-*) ;; (*) exit 69 ;; esac
sudo install -o root -g root -m 700 -d "$KIVOU_FAILED_DIR"

case "$KIVOU_PREVIOUS_APP_TARGET" in
  (ABSENT)
    if sudo test -L /srv/kivou/app; then
      sudo mv -Tf /srv/kivou/app "$KIVOU_FAILED_DIR/app-link"
    else
      sudo test ! -e /srv/kivou/app
    fi
    ;;
  (/srv/kivou/releases/backend-*)
    sudo test -d "$KIVOU_PREVIOUS_APP_TARGET"
    test -z "$(sudo find "$KIVOU_PREVIOUS_APP_TARGET" -perm /222 -print -quit)"
    KIVOU_APP_ROLLBACK_LINK=/srv/kivou/app.rollback
    sudo test ! -e "$KIVOU_APP_ROLLBACK_LINK"
    sudo test ! -L "$KIVOU_APP_ROLLBACK_LINK"
    sudo ln -s "$KIVOU_PREVIOUS_APP_TARGET" "$KIVOU_APP_ROLLBACK_LINK"
    sudo mv -Tf "$KIVOU_APP_ROLLBACK_LINK" /srv/kivou/app
    ;;
  (*) exit 69 ;;
esac
case "$KIVOU_PREVIOUS_FRONTEND_TARGET" in
  (ABSENT)
    if sudo test -L /srv/kivou/frontend; then
      sudo mv -Tf /srv/kivou/frontend "$KIVOU_FAILED_DIR/frontend-link"
    else
      sudo test ! -e /srv/kivou/frontend
    fi
    ;;
  (/srv/kivou/releases/frontend-*)
    sudo test -d "$KIVOU_PREVIOUS_FRONTEND_TARGET"
    test -z "$(sudo find "$KIVOU_PREVIOUS_FRONTEND_TARGET" -perm /222 -print -quit)"
    KIVOU_FRONTEND_ROLLBACK_LINK=/srv/kivou/frontend.rollback
    sudo test ! -e "$KIVOU_FRONTEND_ROLLBACK_LINK"
    sudo test ! -L "$KIVOU_FRONTEND_ROLLBACK_LINK"
    sudo ln -s "$KIVOU_PREVIOUS_FRONTEND_TARGET" "$KIVOU_FRONTEND_ROLLBACK_LINK"
    sudo mv -Tf "$KIVOU_FRONTEND_ROLLBACK_LINK" /srv/kivou/frontend
    ;;
  (*) exit 69 ;;
esac

if [ "$KIVOU_PREVIOUS_APP_TARGET" != ABSENT ]; then
  sudo systemctl enable --now kivou-api.service
  sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
    /srv/kivou/app/ops/bin/kivou-api-readiness.sh kivou-api.service 8000
fi

KIVOU_NGINX_CAPTURE_PATHS=(
  /etc/nginx/conf.d/kivou-limits.conf
  /etc/nginx/kivou-proxy-params.conf
  /etc/nginx/kivou-production-security-headers.conf
  /etc/nginx/kivou-production-sensitive-link-security-headers.conf
  /etc/nginx/kivou-sensitive-links-gate.conf
  /etc/nginx/sites-available/kivou-production-default-deny
  /etc/nginx/sites-available/kivou
  /etc/nginx/sites-available/kivou-www
)
KIVOU_NGINX_CAPTURE_VALID=0
if sudo test -d "$KIVOU_ROLLBACK_DIR/nginx" && \
    test -z "$(sudo find "$KIVOU_ROLLBACK_DIR/nginx" -perm /222 -print -quit)"; then
  KIVOU_NGINX_CAPTURE_VALID=1
  for KIVOU_NGINX_PATH in "${KIVOU_NGINX_CAPTURE_PATHS[@]}"; do
    KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_NGINX_PATH" | sed 's#^/##; s#/#__#g')
    if { sudo test -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved" || sudo test -L "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved"; } && \
        sudo test ! -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT"; then
      :
    elif sudo test -f "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT" && \
        sudo test ! -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved" && \
        sudo test ! -L "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved"; then
      :
    else
      KIVOU_NGINX_CAPTURE_VALID=0
    fi
  done
  for KIVOU_SITE_LINK in /etc/nginx/sites-enabled/kivou-production-default-deny /etc/nginx/sites-enabled/kivou /etc/nginx/sites-enabled/kivou-www; do
    KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_SITE_LINK" | sed 's#^/##; s#/#__#g')
    if sudo test -f "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.target" && \
        sudo test ! -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT"; then
      KIVOU_SITE_TARGET=$(sudo sed -n '1p' "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.target")
      case "$KIVOU_SITE_TARGET" in (/etc/nginx/sites-available/*) ;; (*) KIVOU_NGINX_CAPTURE_VALID=0 ;; esac
      if [ "$(sudo wc -l < "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.target")" != 1 ]; then
        KIVOU_NGINX_CAPTURE_VALID=0
      fi
    elif sudo test -f "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT" && \
        sudo test ! -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.target"; then
      :
    else
      KIVOU_NGINX_CAPTURE_VALID=0
    fi
  done
fi

if [ "$KIVOU_NGINX_CAPTURE_VALID" = 1 ]; then
  for KIVOU_NGINX_PATH in "${KIVOU_NGINX_CAPTURE_PATHS[@]}"; do
    KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_NGINX_PATH" | sed 's#^/##; s#/#__#g')
    case "$KIVOU_NGINX_PATH" in (/etc/nginx/*) ;; (*) exit 69 ;; esac
    if sudo test -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved" || sudo test -L "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved"; then
      sudo test ! -e "$KIVOU_NGINX_PATH.rollback-new"
      sudo test ! -L "$KIVOU_NGINX_PATH.rollback-new"
      sudo cp -a "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved" "$KIVOU_NGINX_PATH.rollback-new"
      sudo mv -Tf "$KIVOU_NGINX_PATH.rollback-new" "$KIVOU_NGINX_PATH"
    elif sudo test -e "$KIVOU_NGINX_PATH" || sudo test -L "$KIVOU_NGINX_PATH"; then
      sudo mv -Tf "$KIVOU_NGINX_PATH" "$KIVOU_FAILED_DIR/$KIVOU_CAPTURE_NAME"
    fi
  done
  for KIVOU_SITE_LINK in /etc/nginx/sites-enabled/kivou-production-default-deny /etc/nginx/sites-enabled/kivou /etc/nginx/sites-enabled/kivou-www; do
    KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_SITE_LINK" | sed 's#^/##; s#/#__#g')
    case "$KIVOU_SITE_LINK" in (/etc/nginx/sites-enabled/*) ;; (*) exit 69 ;; esac
    if sudo test -f "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.target"; then
      KIVOU_SITE_TARGET=$(sudo sed -n '1p' "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.target")
      sudo test -e "$KIVOU_SITE_TARGET"
      KIVOU_SITE_LINK_NEW=$KIVOU_SITE_LINK.rollback-new
      sudo test ! -e "$KIVOU_SITE_LINK_NEW"
      sudo test ! -L "$KIVOU_SITE_LINK_NEW"
      sudo ln -s "$KIVOU_SITE_TARGET" "$KIVOU_SITE_LINK_NEW"
      sudo mv -Tf "$KIVOU_SITE_LINK_NEW" "$KIVOU_SITE_LINK"
    elif sudo test -e "$KIVOU_SITE_LINK" || sudo test -L "$KIVOU_SITE_LINK"; then
      sudo mv -Tf "$KIVOU_SITE_LINK" "$KIVOU_FAILED_DIR/$KIVOU_CAPTURE_NAME"
    fi
  done
  sudo nginx -t
  sudo systemctl reload nginx
else
  printf '%s\n' 'nginx_rollback=skipped_invalid_capture' >&2
fi
```

Le retour app/frontend et l'état API sont établis avant d'examiner nginx. Une
capture nginx absente ou invalide est ignorée sans annuler ce retour ; une
capture valide n'est publiée que si `nginx -t` passe, puis nginx est rechargé.
Les releases, dumps, snapshots et captures sont tous conservés.
