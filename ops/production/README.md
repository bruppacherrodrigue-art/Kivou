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

Aucune release n'est supprimée manuellement.
Aucune sauvegarde n'est supprimée manuellement par ce runbook. Les seuls
effacements de sauvegardes sont ceux des scripts versionnés, après acceptation
d'un nouveau dump ou d'un nouvel upload : rétention locale de 14 jours, puis
rétention restic de 30 quotidiennes, 12 mensuelles et 3 annuelles. Chaque
rollback conserve ses captures. Arrêter au premier échec ; ne jamais continuer
« à la main » après un stop gate rouge.

Ouvrir d'abord un shell root dédié avec `sudo -i`. Les blocs sont à copier dans
l'ordre dans ce même shell ; ils n'affichent aucune variable secrète et
commencent tous en mode Bash strict.

## 1. Vérifier et extraire le SHA exact de `main`

Préconditions : la deploy key GitHub est en lecture seule, son empreinte et le
fichier `known_hosts` ont déjà été revus hors de ce runbook. Le checkout est
construit dans une nouvelle release ; aucun lien actif n'est touché.

```bash
set -euo pipefail
test "$(id -u)" -eq 0
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

## 3. Préflight des secrets et des unités candidates

Le contenu des fichiers n'est ni chargé, ni copié, ni affiché. Ce bloc est
strictement en lecture seule vis-à-vis du runtime actif : aucun service n'est
arrêté et aucun fichier sous `/etc/systemd/system` n'est remplacé.

```bash
set -euo pipefail
for KIVOU_ENV_FILE in /etc/kivou/production.env /etc/kivou/swiss-backup.env; do
  sudo test -f "$KIVOU_ENV_FILE"
  sudo test ! -L "$KIVOU_ENV_FILE"
  test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ENV_FILE")" = root:root:600
done

KIVOU_ROLLOUT_UNITS=(
  kivou-api.service
  kivou-alerts.service kivou-alerts.timer
  kivou-backup-local.service kivou-backup.service kivou-backup.timer
  kivou-ingest@simap.service kivou-ingest-simap.timer
  kivou-ingest@boamp.service kivou-ingest-boamp.timer
  kivou-ingest@decp.service kivou-ingest-decp.timer
  kivou-ingest@ted.service kivou-ingest-ted.timer
)
sudo systemd-analyze verify "$KIVOU_BACKEND_RELEASE_DIR"/ops/systemd/production/*.service "$KIVOU_BACKEND_RELEASE_DIR"/ops/systemd/production/*.timer
```

Stop gate : les deux fichiers sont des fichiers réguliers non symboliques en
`root:root 600` et `systemd-analyze verify` est vert. Aucun état actif n'a
changé.

## 4. Stager les unités et capturer leur baseline

Les unités candidates sont copiées hors des chemins chargés par systemd. Pour
chaque unité, le fichier précédent et ses états `is-enabled`/`is-active` sont
capturés avant toute mutation.

```bash
set -euo pipefail
KIVOU_ROLLBACK_UTC=$(date -u +%Y%m%dT%H%M%SZ)
KIVOU_ROLLBACK_DIR=/srv/kivou/rollbacks/rollout-$KIVOU_ROLLBACK_UTC-$KIVOU_RELEASE_SHORT
KIVOU_STAGE_DIR=/root/kivou-rollouts/production-runtime-$KIVOU_ROLLBACK_UTC
case "$KIVOU_ROLLBACK_DIR" in (/srv/kivou/rollbacks/rollout-*) ;; (*) exit 69 ;; esac
case "$KIVOU_STAGE_DIR" in (/root/kivou-rollouts/production-runtime-*) ;; (*) exit 69 ;; esac
sudo install -o root -g root -m 700 -d /srv/kivou/rollbacks /root/kivou-rollouts
sudo test ! -e "$KIVOU_ROLLBACK_DIR"
sudo test ! -e "$KIVOU_STAGE_DIR"
sudo install -o root -g root -m 700 -d "$KIVOU_ROLLBACK_DIR" "$KIVOU_STAGE_DIR"
KIVOU_ROLLOUT_LOCK=/run/lock/kivou-production-rollout.lock
case "$KIVOU_ROLLOUT_LOCK" in (/run/lock/kivou-production-rollout.lock) ;; (*) exit 69 ;; esac
sudo touch "$KIVOU_ROLLOUT_LOCK"
sudo chown root:root "$KIVOU_ROLLOUT_LOCK"
sudo chmod 600 "$KIVOU_ROLLOUT_LOCK"
sudo test -f "$KIVOU_ROLLOUT_LOCK"; sudo test ! -L "$KIVOU_ROLLOUT_LOCK"
exec 9<>"$KIVOU_ROLLOUT_LOCK"
flock --exclusive 9
KIVOU_UNIT_CAPTURE_DIR=$KIVOU_ROLLBACK_DIR/systemd
KIVOU_UNIT_STAGE_DIR=$KIVOU_STAGE_DIR/systemd
sudo install -o root -g root -m 700 -d "$KIVOU_UNIT_CAPTURE_DIR" "$KIVOU_UNIT_STAGE_DIR"

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
  sudo test -f "$KIVOU_UNIT_SOURCE"
  sudo test ! -L "$KIVOU_UNIT_SOURCE"
  sudo install -o root -g root -m 644 "$KIVOU_UNIT_SOURCE" "$KIVOU_UNIT_STAGE_DIR/$KIVOU_UNIT"
  test "$(sudo stat -c '%U:%G:%a' "$KIVOU_UNIT_STAGE_DIR/$KIVOU_UNIT")" = root:root:644

  KIVOU_UNIT_PATH=/etc/systemd/system/$KIVOU_UNIT
  case "$KIVOU_UNIT_PATH" in (/etc/systemd/system/kivou-*) ;; (*) exit 69 ;; esac
  if sudo test -e "$KIVOU_UNIT_PATH" || sudo test -L "$KIVOU_UNIT_PATH"; then
    sudo cp -a "$KIVOU_UNIT_PATH" "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.saved"
  else
    sudo touch "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.ABSENT"
  fi
done
for KIVOU_UNIT in "${KIVOU_ROLLOUT_UNITS[@]}"; do
  KIVOU_UNIT_WAS_ENABLED=$(sudo systemctl is-enabled "$KIVOU_UNIT" 2>/dev/null || :)
  KIVOU_UNIT_WAS_ACTIVE=$(sudo systemctl is-active "$KIVOU_UNIT" 2>/dev/null || :)
  case "$KIVOU_UNIT_WAS_ENABLED" in (enabled|disabled|static|indirect|masked|not-found) ;; (*) exit 69 ;; esac
  case "$KIVOU_UNIT_WAS_ACTIVE" in (active|inactive|failed|unknown) ;; (*) exit 69 ;; esac
  printf '%s\n' "$KIVOU_UNIT_WAS_ENABLED" | sudo tee "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.enabled" >/dev/null
  printf '%s\n' "$KIVOU_UNIT_WAS_ACTIVE" | sudo tee "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.active" >/dev/null
done
KIVOU_ROLLBACK_READINESS=$KIVOU_ROLLBACK_DIR/kivou-api-readiness.sh
case "$KIVOU_ROLLBACK_READINESS" in (/srv/kivou/rollbacks/rollout-*/kivou-api-readiness.sh) ;; (*) exit 69 ;; esac
sudo test ! -e "$KIVOU_ROLLBACK_READINESS"; sudo test ! -L "$KIVOU_ROLLBACK_READINESS"
sudo install -o root -g root -m 555 \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/bin/kivou-api-readiness.sh" "$KIVOU_ROLLBACK_READINESS"
sudo test -f "$KIVOU_ROLLBACK_READINESS"; sudo test ! -L "$KIVOU_ROLLBACK_READINESS"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLBACK_READINESS")" = root:root:555
```

Stop gate : chaque unité candidate stagée est `root:root 644`; chaque baseline
est capturée. La sonde readiness du SHA candidat est capturée en `root:root
555`. Aucun fichier systemd actif n'a été installé ou remplacé.

## 5. Capturer les liens, nginx et les états de service avant mutation

Les seules valeurs de lien acceptées sont `ABSENT` ou une release immuable du
type attendu. Les fichiers et liens nginx sont copiés ou marqués `ABSENT` dans
un répertoire borné avant toute bascule. Le fichier d'état ne contient aucun
secret. Si un lien était absent, le rollback n'inventera aucune cible.

```bash
set -euo pipefail
case "$KIVOU_ROLLBACK_DIR" in (/srv/kivou/rollbacks/rollout-*) ;; (*) exit 69 ;; esac
case "$KIVOU_STAGE_DIR" in (/root/kivou-rollouts/production-runtime-*) ;; (*) exit 69 ;; esac
sudo test -d "$KIVOU_UNIT_CAPTURE_DIR"

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

while IFS= read -r KIVOU_ENABLED_SITE; do
  case "$KIVOU_ENABLED_SITE" in
    (default|kivou-production-default-deny|kivou|kivou-www) ;;
    (*) KIVOU_UNKNOWN_ENABLED_SITE=$KIVOU_ENABLED_SITE; printf 'unknown_enabled_site=%s\n' "$KIVOU_UNKNOWN_ENABLED_SITE" >&2; exit 69 ;;
  esac
done < <(sudo find /etc/nginx/sites-enabled -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)

KIVOU_NGINX_SITE_LINKS=(
  /etc/nginx/sites-enabled/default
  /etc/nginx/sites-enabled/kivou-production-default-deny
  /etc/nginx/sites-enabled/kivou
  /etc/nginx/sites-enabled/kivou-www
)
for KIVOU_SITE_LINK in "${KIVOU_NGINX_SITE_LINKS[@]}"; do
  KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_SITE_LINK" | sed 's#^/##; s#/#__#g')
  if sudo test -L "$KIVOU_SITE_LINK"; then
    KIVOU_SITE_TARGET=$(sudo readlink -f "$KIVOU_SITE_LINK")
    case "$KIVOU_SITE_TARGET" in (/etc/nginx/sites-available/*) ;; (*) exit 69 ;; esac
    sudo cp -a "$KIVOU_SITE_LINK" "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved"
  else
    sudo test ! -e "$KIVOU_SITE_LINK"
    sudo touch "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT"
  fi
done

KIVOU_NGINX_WAS_ENABLED=$(sudo systemctl is-enabled nginx.service 2>/dev/null || :)
KIVOU_NGINX_WAS_ACTIVE=$(sudo systemctl is-active nginx.service 2>/dev/null || :)
case "$KIVOU_NGINX_WAS_ENABLED" in (enabled|disabled) ;; (*) exit 69 ;; esac
case "$KIVOU_NGINX_WAS_ACTIVE" in (active|inactive) ;; (*) exit 69 ;; esac
printf '%s\n' "$KIVOU_NGINX_WAS_ENABLED" | sudo tee "$KIVOU_ROLLBACK_DIR/nginx.enabled" >/dev/null
printf '%s\n' "$KIVOU_NGINX_WAS_ACTIVE" | sudo tee "$KIVOU_ROLLBACK_DIR/nginx.active" >/dev/null

KIVOU_ROLLOUT_STATE=$KIVOU_ROLLBACK_DIR/links.manifest
KIVOU_ROLLOUT_STATUS=$KIVOU_ROLLBACK_DIR/rollout.status
sudo install -o root -g root -m 600 /dev/null "$KIVOU_ROLLOUT_STATE"
printf '%s\n%s\n' "$KIVOU_PREVIOUS_APP_TARGET" "$KIVOU_PREVIOUS_FRONTEND_TARGET" | sudo tee "$KIVOU_ROLLOUT_STATE" >/dev/null
printf '%s\n' PREPARED | sudo tee "$KIVOU_ROLLOUT_STATUS" >/dev/null
sudo chown root:root "$KIVOU_ROLLOUT_STATE" "$KIVOU_ROLLOUT_STATUS" \
  "$KIVOU_ROLLBACK_DIR"/*.enabled "$KIVOU_ROLLBACK_DIR"/*.active \
  "$KIVOU_UNIT_CAPTURE_DIR"/*.enabled "$KIVOU_UNIT_CAPTURE_DIR"/*.active
sudo chmod 600 "$KIVOU_ROLLOUT_STATE" "$KIVOU_ROLLOUT_STATUS" \
  "$KIVOU_ROLLBACK_DIR"/*.enabled "$KIVOU_ROLLBACK_DIR"/*.active \
  "$KIVOU_UNIT_CAPTURE_DIR"/*.enabled "$KIVOU_UNIT_CAPTURE_DIR"/*.active
KIVOU_NGINX_CAPTURE_COMPLETE=1
sudo chmod -R a-w "$KIVOU_UNIT_CAPTURE_DIR" "$KIVOU_ROLLBACK_DIR/nginx"

KIVOU_CURRENT_ROLLBACK=/srv/kivou/rollbacks/current
if sudo test -L "$KIVOU_CURRENT_ROLLBACK"; then
  KIVOU_PRIOR_ROLLBACK=$(sudo readlink -f "$KIVOU_CURRENT_ROLLBACK")
  case "$KIVOU_PRIOR_ROLLBACK" in (/srv/kivou/rollbacks/rollout-*) ;; (*) exit 69 ;; esac
  KIVOU_PRIOR_STATUS=$(sudo sed -n '1p' "$KIVOU_PRIOR_ROLLBACK/rollout.status")
  case "$KIVOU_PRIOR_STATUS" in (COMMITTED|ROLLED_BACK) ;; (*) exit 69 ;; esac
else
  sudo test ! -e "$KIVOU_CURRENT_ROLLBACK"
fi
KIVOU_CURRENT_NEW=/srv/kivou/rollbacks/.current-$KIVOU_ROLLBACK_UTC-$KIVOU_RELEASE_SHORT
case "$KIVOU_CURRENT_NEW" in (/srv/kivou/rollbacks/.current-*) ;; (*) exit 69 ;; esac
sudo test ! -e "$KIVOU_CURRENT_NEW"; sudo test ! -L "$KIVOU_CURRENT_NEW"
sudo ln -s "$KIVOU_ROLLBACK_DIR" "$KIVOU_CURRENT_NEW"
sudo mv -Tf "$KIVOU_CURRENT_NEW" "$KIVOU_CURRENT_ROLLBACK"
test "$(sudo readlink -f "$KIVOU_CURRENT_ROLLBACK")" = "$KIVOU_ROLLBACK_DIR"
```

Stop gate : les anciennes cibles app/frontend, les unités, les huit destinations
nginx, `sites-enabled/default`, tous les liens Kivou autorisés et les états de
service sont capturés. Tout site activé inconnu bloque le rollout. Rien n'a
encore été basculé, arrêté, installé ou activé.

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

## 7. Prouver le certificat existant

Ce runbook ne lance ni certbot, ni HSTS. Les trois fichiers doivent exister et
le SAN doit contenir l'apex et `www` avant tout rendu.

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
```

Stop gate : les fichiers sont lisibles et le SAN prouve au minimum `kivou.eu`
et `www.kivou.eu`.

## 8. Rendre et tester nginx entièrement hors des chemins actifs

Le staging est sous `/root/kivou-rollouts`, jamais sous `sites-enabled` ou un
autre chemin inclus. Le candidat représente exactement l'état attendu après
mutation : default Ubuntu absent, default deny Kivou présent, apex et `www`
présents. Le refus des sites inconnus au bloc 5 écarte une collision extérieure.

```bash
set -euo pipefail
KIVOU_NGINX_STAGE_DIR=$KIVOU_STAGE_DIR/nginx
KIVOU_NGINX_CANDIDATE=$KIVOU_STAGE_DIR/nginx-candidate
case "$KIVOU_NGINX_STAGE_DIR" in (/root/kivou-rollouts/production-runtime-*/nginx) ;; (*) exit 69 ;; esac
case "$KIVOU_NGINX_CANDIDATE" in (/root/kivou-rollouts/production-runtime-*/nginx-candidate) ;; (*) exit 69 ;; esac
sudo install -o root -g root -m 700 -d "$KIVOU_NGINX_STAGE_DIR" "$KIVOU_NGINX_CANDIDATE"
sudo install -o root -g root -m 644 \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-limits.conf" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-proxy-params.conf" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production-security-headers.conf" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production-sensitive-link-security-headers.conf" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production-default-deny.conf" \
  "$KIVOU_NGINX_STAGE_DIR/"
sudo install -o root -g root -m 600 \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-sensitive-links-closed.conf" \
  "$KIVOU_NGINX_STAGE_DIR/kivou-sensitive-links-gate.conf"
sed -e "s/PRODUCTION_HOST/$KIVOU_PRODUCTION_HOST/g" \
  -e "s/KIVOU_API_PORT/$KIVOU_API_PORT/g" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production.conf" | \
  sudo tee "$KIVOU_NGINX_STAGE_DIR/kivou-production.conf" >/dev/null
sed -e "s/PRODUCTION_WWW_HOST/$KIVOU_PRODUCTION_WWW_HOST/g" \
  -e "s/PRODUCTION_HOST/$KIVOU_PRODUCTION_HOST/g" \
  "$KIVOU_BACKEND_RELEASE_DIR/ops/nginx/kivou-production-www.conf" | \
  sudo tee "$KIVOU_NGINX_STAGE_DIR/kivou-production-www.conf" >/dev/null
if sudo grep -ERn 'PRODUCTION_HOST|PRODUCTION_WWW_HOST|KIVOU_API_PORT' "$KIVOU_NGINX_STAGE_DIR"; then exit 69; fi

sudo cp -a "$KIVOU_NGINX_STAGE_DIR/." "$KIVOU_NGINX_CANDIDATE/"
for KIVOU_RENDERED_SITE in kivou-production.conf kivou-production-www.conf; do
  sed \
    -e "s#/etc/nginx/kivou-proxy-params.conf#$KIVOU_NGINX_CANDIDATE/kivou-proxy-params.conf#g" \
    -e "s#/etc/nginx/kivou-production-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-production-security-headers.conf#g" \
    -e "s#/etc/nginx/kivou-production-sensitive-link-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-production-sensitive-link-security-headers.conf#g" \
    -e "s#/etc/nginx/kivou-sensitive-links-gate.conf#$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf#g" \
    "$KIVOU_NGINX_STAGE_DIR/$KIVOU_RENDERED_SITE" | \
    sudo tee "$KIVOU_NGINX_CANDIDATE/$KIVOU_RENDERED_SITE" >/dev/null
done
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
sudo chmod 644 "$KIVOU_NGINX_CANDIDATE/nginx.conf"
KIVOU_EXPECTED_DEFAULT_SERVER_DIRECTIVES=4
test "$(sudo grep -RhE '^[[:space:]]*listen .*default_server;' "$KIVOU_NGINX_CANDIDATE"/*.conf | wc -l)" = "$KIVOU_EXPECTED_DEFAULT_SERVER_DIRECTIVES"
sudo nginx -t -c "$KIVOU_NGINX_CANDIDATE/nginx.conf"
```

Stop gate : aucun placeholder ne reste et le candidat hermétique, avec exactement
les quatre directives `default_server` du default deny (HTTP et HTTPS, IPv4 et IPv6),
passe `nginx -t`.

## 9. Dernier gate d'intégrité avant mutation

Ce dernier bloc read-only rattache le staging et les captures au SHA exact. Il
refuse aussi une baseline alertes active : une autorisation SMTP séparée et un
compte de test dédié seront requis dans une procédure ultérieure.

```bash
set -euo pipefail
test "$KIVOU_NGINX_CAPTURE_COMPLETE" = 1
case "$KIVOU_UNIT_STAGE_DIR" in (/root/kivou-rollouts/production-runtime-*/systemd) ;; (*) exit 69 ;; esac
case "$KIVOU_NGINX_STAGE_DIR" in (/root/kivou-rollouts/production-runtime-*/nginx) ;; (*) exit 69 ;; esac
test -z "$(sudo find "$KIVOU_UNIT_CAPTURE_DIR" "$KIVOU_ROLLBACK_DIR/nginx" -perm /222 -print -quit)"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_STATE")" = root:root:600
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_STATUS")" = root:root:600
test "$(sudo readlink -f /srv/kivou/rollbacks/current)" = "$KIVOU_ROLLBACK_DIR"
test "$(sudo -u kivou /usr/bin/git -C "$KIVOU_BACKEND_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
test -z "$(sudo find "$KIVOU_BACKEND_RELEASE_DIR" "$KIVOU_FRONTEND_RELEASE_DIR" -perm /222 -print -quit)"
test "$(sudo sed -n '1p' "$KIVOU_UNIT_CAPTURE_DIR/kivou-alerts.timer.enabled")" != enabled
test "$(sudo sed -n '1p' "$KIVOU_UNIT_CAPTURE_DIR/kivou-alerts.service.active")" != active
if sudo systemctl is-enabled --quiet kivou-alerts.timer; then exit 70; fi
if sudo systemctl is-active --quiet kivou-alerts.timer; then exit 70; fi
if sudo systemctl is-active --quiet kivou-alerts.service; then exit 70; fi
for KIVOU_CAPTURED_PATH in "${KIVOU_NGINX_CAPTURE_PATHS[@]}" "${KIVOU_NGINX_SITE_LINKS[@]}"; do
  KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_CAPTURED_PATH" | sed 's#^/##; s#/#__#g')
  if sudo test -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved" || sudo test -L "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved"; then
    sudo test ! -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT"
  else
    sudo test -f "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT"
  fi
done
sudo test -f "$KIVOU_NGINX_STAGE_DIR/kivou-production.conf"
sudo test -f "$KIVOU_UNIT_STAGE_DIR/kivou-api.service"
```

Stop gate : tous les préflights longs, restore compris, sont verts ; captures et
staging sont complets ; alertes et SMTP restent désactivés.

## 10. Fenêtre unique de mutation, smokes et activations

Ce bloc unique définit le rollback avant la première mutation, acquiert le
verrou global, puis arme un trap `ERR` qui conserve le code original. Toute la
fenêtre doit rester dans cette même session shell. En cas d'échec, services et
timers sont arrêtés, app/frontend puis unités puis nginx sont restaurés.
Chaque phase de rollback est un sous-shell strict indépendant ; son statut est
capturé sur l'instruction immédiatement suivante, jamais dans `if !` ou `||`,
car ces contextes désactivent `errexit` jusque dans le sous-shell Bash.

```bash
set -euo pipefail
KIVOU_MUTATION_WINDOW_BEGIN=1
case "$KIVOU_ROLLOUT_LOCK" in (/run/lock/kivou-production-rollout.lock) ;; (*) exit 69 ;; esac
KIVOU_FAILED_DIR=/srv/kivou/rollbacks/failed-$KIVOU_ROLLBACK_UTC
case "$KIVOU_FAILED_DIR" in (/srv/kivou/rollbacks/failed-*) ;; (*) exit 69 ;; esac
sudo install -o root -g root -m 700 -d "$KIVOU_FAILED_DIR"

kivou_capture_current_nginx_bundle() {
  KIVOU_NGINX_CURRENT_BUNDLE=$KIVOU_FAILED_DIR/nginx-current
  case "$KIVOU_NGINX_CURRENT_BUNDLE" in (/srv/kivou/rollbacks/failed-*/nginx-current) ;; (*) return 69 ;; esac
  sudo install -o root -g root -m 700 -d "$KIVOU_NGINX_CURRENT_BUNDLE"
  for KIVOU_NGINX_PATH in "${KIVOU_NGINX_CAPTURE_PATHS[@]}" "${KIVOU_NGINX_SITE_LINKS[@]}"; do
    case "$KIVOU_NGINX_PATH" in (/etc/nginx/*) ;; (*) return 69 ;; esac
    KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_NGINX_PATH" | sed 's#^/##; s#/#__#g')
    if sudo test -e "$KIVOU_NGINX_PATH" || sudo test -L "$KIVOU_NGINX_PATH"; then
      sudo cp -a "$KIVOU_NGINX_PATH" "$KIVOU_NGINX_CURRENT_BUNDLE/$KIVOU_CAPTURE_NAME.saved"
    else
      sudo touch "$KIVOU_NGINX_CURRENT_BUNDLE/$KIVOU_CAPTURE_NAME.ABSENT"
    fi
  done
}

kivou_apply_nginx_bundle() {
  KIVOU_BUNDLE=$1
  KIVOU_EVAC=$2
  case "$KIVOU_BUNDLE" in (/srv/kivou/rollbacks/rollout-*/nginx|/srv/kivou/rollbacks/failed-*/nginx-current) ;; (*) return 69 ;; esac
  case "$KIVOU_EVAC" in (/srv/kivou/rollbacks/failed-*/nginx-*) ;; (*) return 69 ;; esac
  sudo install -o root -g root -m 700 -d "$KIVOU_EVAC"
  for KIVOU_NGINX_PATH in "${KIVOU_NGINX_CAPTURE_PATHS[@]}" "${KIVOU_NGINX_SITE_LINKS[@]}"; do
    case "$KIVOU_NGINX_PATH" in (/etc/nginx/*) ;; (*) return 69 ;; esac
    KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_NGINX_PATH" | sed 's#^/##; s#/#__#g')
    if sudo test -e "$KIVOU_NGINX_PATH" || sudo test -L "$KIVOU_NGINX_PATH"; then
      sudo test ! -e "$KIVOU_EVAC/$KIVOU_CAPTURE_NAME"
      sudo test ! -L "$KIVOU_EVAC/$KIVOU_CAPTURE_NAME"
      sudo mv -Tf "$KIVOU_NGINX_PATH" "$KIVOU_EVAC/$KIVOU_CAPTURE_NAME"
    fi
    if sudo test -e "$KIVOU_BUNDLE/$KIVOU_CAPTURE_NAME.saved" || sudo test -L "$KIVOU_BUNDLE/$KIVOU_CAPTURE_NAME.saved"; then
      KIVOU_NGINX_NEW=$KIVOU_NGINX_PATH.rollback-new
      case "$KIVOU_NGINX_NEW" in (/etc/nginx/*.rollback-new|/etc/nginx/*/*.rollback-new) ;; (*) return 69 ;; esac
      sudo test ! -e "$KIVOU_NGINX_NEW"
      sudo test ! -L "$KIVOU_NGINX_NEW"
      sudo cp -a "$KIVOU_BUNDLE/$KIVOU_CAPTURE_NAME.saved" "$KIVOU_NGINX_NEW"
      sudo mv -Tf "$KIVOU_NGINX_NEW" "$KIVOU_NGINX_PATH"
    else
      sudo test -f "$KIVOU_BUNDLE/$KIVOU_CAPTURE_NAME.ABSENT"
    fi
  done
}

kivou_restore_current_nginx_bundle() {
  kivou_apply_nginx_bundle "$KIVOU_NGINX_CURRENT_BUNDLE" "$KIVOU_FAILED_DIR/nginx-invalid-baseline"
}

kivou_publish_captured_nginx_bundle() {
  kivou_capture_current_nginx_bundle
  kivou_apply_nginx_bundle "$KIVOU_ROLLBACK_DIR/nginx" "$KIVOU_FAILED_DIR/nginx-replaced-current"
  if ! sudo nginx -t; then
    kivou_restore_current_nginx_bundle
    return 71
  fi
  if [ "$KIVOU_NGINX_WAS_ACTIVE" = active ]; then
    sudo systemctl reload nginx
  fi
}

kivou_restore_unit_states() {
  for KIVOU_UNIT in "${KIVOU_ROLLOUT_UNITS[@]}"; do
    KIVOU_UNIT_WAS_ENABLED=$(sudo sed -n '1p' "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.enabled")
    KIVOU_UNIT_WAS_ACTIVE=$(sudo sed -n '1p' "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.active")
    case "$KIVOU_UNIT_WAS_ENABLED" in
      (enabled) sudo systemctl enable "$KIVOU_UNIT" ;;
      (masked) sudo systemctl mask "$KIVOU_UNIT" ;;
      (disabled) sudo systemctl disable "$KIVOU_UNIT" ;;
      (not-found) ;;
      (static|indirect) ;;
      (*) return 69 ;;
    esac
    if [ "$KIVOU_UNIT_WAS_ACTIVE" = active ]; then
      sudo systemctl start "$KIVOU_UNIT"
    elif [ "$KIVOU_UNIT_WAS_ENABLED" != not-found ]; then
      sudo systemctl stop "$KIVOU_UNIT"
    fi
  done
}

kivou_fail() {
  return "$1"
}

KIVOU_ROLLBACK_READINESS_MARKER=$KIVOU_FAILED_DIR/api-readiness.ok
case "$KIVOU_ROLLBACK_READINESS_MARKER" in (/srv/kivou/rollbacks/failed-*/api-readiness.ok) ;; (*) exit 69 ;; esac
sudo test ! -e "$KIVOU_ROLLBACK_READINESS_MARKER"; sudo test ! -L "$KIVOU_ROLLBACK_READINESS_MARKER"

kivou_rollback_api_readiness_required() {
  KIVOU_API_WAS_ACTIVE=$(sudo sed -n '1p' "$KIVOU_UNIT_CAPTURE_DIR/kivou-api.service.active")
  case "$KIVOU_API_WAS_ACTIVE" in (active|inactive|failed|unknown) ;; (*) return 69 ;; esac
  [ "$KIVOU_API_WAS_ACTIVE" = active ] && [ "$KIVOU_PREVIOUS_APP_TARGET" != ABSENT ]
}

kivou_evaluate_rollback_api_readiness_requirement() {
  KIVOU_READINESS_ERREXIT_WAS_SET=0
  case "$-" in (*e*) KIVOU_READINESS_ERREXIT_WAS_SET=1 ;; esac
  set +e
  ( set -Eeuo pipefail; kivou_rollback_api_readiness_required )
  KIVOU_READINESS_REQUIRED_RC=$?
  if [ "$KIVOU_READINESS_ERREXIT_WAS_SET" = 1 ]; then set -e; fi
}

kivou_verify_rollback_api_readiness() {
  kivou_evaluate_rollback_api_readiness_requirement
  case "$KIVOU_READINESS_REQUIRED_RC" in (0) ;; (1) return 0 ;; (*) return "$KIVOU_READINESS_REQUIRED_RC" ;; esac
  test "$(sudo readlink -f /srv/kivou/app)" = "$KIVOU_PREVIOUS_APP_TARGET"
  sudo test -f "$KIVOU_ROLLBACK_READINESS"; sudo test ! -L "$KIVOU_ROLLBACK_READINESS"
  test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLBACK_READINESS")" = root:root:555
  sudo /usr/bin/env -i HOME=/root PATH=/usr/bin:/bin \
    "$KIVOU_ROLLBACK_READINESS" kivou-api.service 8000
  sudo touch "$KIVOU_ROLLBACK_READINESS_MARKER"
  sudo chown root:root "$KIVOU_ROLLBACK_READINESS_MARKER"
  sudo chmod 400 "$KIVOU_ROLLBACK_READINESS_MARKER"
}

kivou_require_rollback_api_readiness() {
  kivou_evaluate_rollback_api_readiness_requirement
  case "$KIVOU_READINESS_REQUIRED_RC" in (0) ;; (1) return 0 ;; (*) return "$KIVOU_READINESS_REQUIRED_RC" ;; esac
  sudo test -f "$KIVOU_ROLLBACK_READINESS_MARKER"
  sudo test ! -L "$KIVOU_ROLLBACK_READINESS_MARKER"
  test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLBACK_READINESS_MARKER")" = root:root:400
}

# KIVOU_ROLLBACK_ENGINE_BEGIN
kivou_rollback_stop_phase() {
  sudo systemctl disable --now \
    kivou-ingest-simap.timer kivou-ingest-boamp.timer \
    kivou-ingest-decp.timer kivou-ingest-ted.timer \
    kivou-backup.timer kivou-alerts.timer kivou-alerts.service \
    kivou-api.service
  sudo systemctl stop \
    kivou-ingest@simap.service kivou-ingest@boamp.service \
    kivou-ingest@decp.service kivou-ingest@ted.service \
    kivou-backup.service kivou-backup-local.service
}

kivou_rollback_app_phase() {
  case "$KIVOU_PREVIOUS_APP_TARGET" in
    (ABSENT)
      if sudo test -L /srv/kivou/app; then sudo mv -Tf /srv/kivou/app "$KIVOU_FAILED_DIR/app-link"; else sudo test ! -e /srv/kivou/app; fi
      ;;
    (/srv/kivou/releases/backend-*)
      sudo test -d "$KIVOU_PREVIOUS_APP_TARGET"
      test -z "$(sudo find "$KIVOU_PREVIOUS_APP_TARGET" -perm /222 -print -quit)"
      sudo test ! -e /srv/kivou/app.rollback
      sudo test ! -L /srv/kivou/app.rollback
      sudo ln -s "$KIVOU_PREVIOUS_APP_TARGET" /srv/kivou/app.rollback
      sudo mv -Tf /srv/kivou/app.rollback /srv/kivou/app
      ;;
    (*) return 69 ;;
  esac
}

kivou_rollback_frontend_phase() {
  case "$KIVOU_PREVIOUS_FRONTEND_TARGET" in
    (ABSENT)
      if sudo test -L /srv/kivou/frontend; then sudo mv -Tf /srv/kivou/frontend "$KIVOU_FAILED_DIR/frontend-link"; else sudo test ! -e /srv/kivou/frontend; fi
      ;;
    (/srv/kivou/releases/frontend-*)
      sudo test -d "$KIVOU_PREVIOUS_FRONTEND_TARGET"
      test -z "$(sudo find "$KIVOU_PREVIOUS_FRONTEND_TARGET" -perm /222 -print -quit)"
      sudo test ! -e /srv/kivou/frontend.rollback
      sudo test ! -L /srv/kivou/frontend.rollback
      sudo ln -s "$KIVOU_PREVIOUS_FRONTEND_TARGET" /srv/kivou/frontend.rollback
      sudo mv -Tf /srv/kivou/frontend.rollback /srv/kivou/frontend
      ;;
    (*) return 69 ;;
  esac
}

kivou_rollback_units_phase() {
  sudo install -o root -g root -m 700 -d "$KIVOU_FAILED_DIR/systemd-new"
  for KIVOU_UNIT in "${KIVOU_UNIT_NAMES[@]}"; do
    KIVOU_UNIT_PATH=/etc/systemd/system/$KIVOU_UNIT
    case "$KIVOU_UNIT_PATH" in (/etc/systemd/system/kivou-*) ;; (*) return 69 ;; esac
    if sudo test -e "$KIVOU_UNIT_PATH" || sudo test -L "$KIVOU_UNIT_PATH"; then
      sudo test ! -e "$KIVOU_FAILED_DIR/systemd-new/$KIVOU_UNIT"
      sudo test ! -L "$KIVOU_FAILED_DIR/systemd-new/$KIVOU_UNIT"
      sudo mv -Tf "$KIVOU_UNIT_PATH" "$KIVOU_FAILED_DIR/systemd-new/$KIVOU_UNIT"
    fi
    if sudo test -e "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.saved" || sudo test -L "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.saved"; then
      sudo cp -a "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.saved" "$KIVOU_UNIT_PATH.rollback-new"
      sudo mv -Tf "$KIVOU_UNIT_PATH.rollback-new" "$KIVOU_UNIT_PATH"
    else
      sudo test -f "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.ABSENT"
    fi
  done
  sudo systemctl daemon-reload

  kivou_restore_unit_states
  kivou_verify_rollback_api_readiness
}

kivou_rollback_nginx_phase() {
  kivou_require_rollback_api_readiness
  KIVOU_NGINX_CAPTURE_VALID=0
  if sudo test -d "$KIVOU_ROLLBACK_DIR/nginx" && test -z "$(sudo find "$KIVOU_ROLLBACK_DIR/nginx" -perm /222 -print -quit)"; then
    KIVOU_NGINX_CAPTURE_VALID=1
  fi
  if [ "$KIVOU_NGINX_CAPTURE_VALID" = 1 ]; then
    kivou_publish_captured_nginx_bundle
  else
    printf '%s\n' 'nginx_rollback=invalid_capture' >&2
    return 72
  fi

  if [ "$KIVOU_NGINX_WAS_ENABLED" = enabled ]; then sudo systemctl enable nginx; else sudo systemctl disable nginx; fi
  if [ "$KIVOU_NGINX_WAS_ACTIVE" = active ]; then sudo systemctl start nginx; else sudo systemctl stop nginx; fi
}

kivou_rollout_rollback() {
  KIVOU_ROLLBACK_ERREXIT_WAS_SET=0
  case "$-" in (*e*) KIVOU_ROLLBACK_ERREXIT_WAS_SET=1 ;; esac
  set +e
  KIVOU_ROLLBACK_RC=0

  KIVOU_PHASE_RC=0
  ( set -Eeuo pipefail; kivou_rollback_stop_phase )
  KIVOU_PHASE_RC=$?
  if [ "$KIVOU_PHASE_RC" -ne 0 ] && [ "$KIVOU_ROLLBACK_RC" -eq 0 ]; then KIVOU_ROLLBACK_RC=$KIVOU_PHASE_RC; fi

  KIVOU_PHASE_RC=0
  ( set -Eeuo pipefail; kivou_rollback_app_phase )
  KIVOU_PHASE_RC=$?
  if [ "$KIVOU_PHASE_RC" -ne 0 ] && [ "$KIVOU_ROLLBACK_RC" -eq 0 ]; then KIVOU_ROLLBACK_RC=$KIVOU_PHASE_RC; fi

  KIVOU_PHASE_RC=0
  ( set -Eeuo pipefail; kivou_rollback_frontend_phase )
  KIVOU_PHASE_RC=$?
  if [ "$KIVOU_PHASE_RC" -ne 0 ] && [ "$KIVOU_ROLLBACK_RC" -eq 0 ]; then KIVOU_ROLLBACK_RC=$KIVOU_PHASE_RC; fi

  KIVOU_PHASE_RC=0
  ( set -Eeuo pipefail; kivou_rollback_units_phase )
  KIVOU_PHASE_RC=$?
  if [ "$KIVOU_PHASE_RC" -ne 0 ] && [ "$KIVOU_ROLLBACK_RC" -eq 0 ]; then KIVOU_ROLLBACK_RC=$KIVOU_PHASE_RC; fi

  KIVOU_PHASE_RC=0
  ( set -Eeuo pipefail; kivou_rollback_nginx_phase )
  KIVOU_PHASE_RC=$?
  if [ "$KIVOU_PHASE_RC" -ne 0 ] && [ "$KIVOU_ROLLBACK_RC" -eq 0 ]; then KIVOU_ROLLBACK_RC=$KIVOU_PHASE_RC; fi

  if [ "$KIVOU_ROLLBACK_ERREXIT_WAS_SET" = 1 ]; then set -e; fi
  return "$KIVOU_ROLLBACK_RC"
}

kivou_rollout_on_err() {
  KIVOU_ROLLOUT_RC=$?
  kivou_rollout_request_exit "$KIVOU_ROLLOUT_RC"
}

kivou_disarm_rollout_traps() {
  trap - ERR HUP INT TERM EXIT
}

kivou_rollout_request_exit() {
  KIVOU_ROLLOUT_RC=$1
  trap - ERR HUP INT TERM
  exit "$KIVOU_ROLLOUT_RC"
}

kivou_rollout_is_committed() {
  if [ "${KIVOU_COMMITTED:-0}" = 1 ]; then return 0; fi
  if [ -f "${KIVOU_ROLLOUT_STATUS:-/nonexistent}" ] && [ ! -L "$KIVOU_ROLLOUT_STATUS" ]; then
    KIVOU_PERSISTED_STATUS=$(sed -n '1p' "$KIVOU_ROLLOUT_STATUS")
    if [ "$KIVOU_PERSISTED_STATUS" = COMMITTED ]; then return 0; fi
  fi
  return 1
}

kivou_mark_rollout_status() {
  KIVOU_STATUS_VALUE=$1
  case "$KIVOU_STATUS_VALUE" in (COMMITTED|ROLLED_BACK) ;; (*) return 69 ;; esac
  case "$KIVOU_ROLLOUT_STATUS" in (/srv/kivou/rollbacks/rollout-*/rollout.status) ;; (*) return 69 ;; esac
  sudo test -f "$KIVOU_ROLLOUT_STATUS"; sudo test ! -L "$KIVOU_ROLLOUT_STATUS"
  KIVOU_STATUS_NEW=$KIVOU_ROLLOUT_STATUS.new-$$
  case "$KIVOU_STATUS_NEW" in (/srv/kivou/rollbacks/rollout-*/rollout.status.new-*) ;; (*) return 69 ;; esac
  printf '%s\n' "$KIVOU_STATUS_VALUE" | sudo tee "$KIVOU_STATUS_NEW" >/dev/null
  sudo chown root:root "$KIVOU_STATUS_NEW"; sudo chmod 600 "$KIVOU_STATUS_NEW"
  sudo mv -Tf "$KIVOU_STATUS_NEW" "$KIVOU_ROLLOUT_STATUS"
}

kivou_rollout_on_exit() {
  KIVOU_ROLLOUT_RC=$1
  kivou_disarm_rollout_traps
  if [ "${KIVOU_MUTATION_STARTED:-0}" != 1 ]; then exit "$KIVOU_ROLLOUT_RC"; fi
  if kivou_rollout_is_committed; then exit "$KIVOU_ROLLOUT_RC"; fi
  if [ "${KIVOU_ROLLBACK_RUNNING:-0}" = 1 ]; then exit "$KIVOU_ROLLOUT_RC"; fi
  KIVOU_ROLLBACK_RUNNING=1
  set +e
  kivou_rollout_rollback
  KIVOU_ROLLBACK_RC=$?
  if [ "$KIVOU_ROLLBACK_RC" -ne 0 ]; then printf 'rollback_failed=%s\n' "$KIVOU_ROLLBACK_RC" >&2; fi
  if [ "$KIVOU_ROLLBACK_RC" -eq 0 ]; then
    kivou_mark_rollout_status ROLLED_BACK
    KIVOU_STATUS_RC=$?
    if [ "$KIVOU_STATUS_RC" -ne 0 ]; then printf 'rollback_status_failed=%s\n' "$KIVOU_STATUS_RC" >&2; fi
  fi
  exit "$KIVOU_ROLLOUT_RC"
}

kivou_arm_rollout_traps() {
  trap 'kivou_rollout_on_err' ERR
  trap 'kivou_rollout_request_exit 129' HUP
  trap 'kivou_rollout_request_exit 130' INT
  trap 'kivou_rollout_request_exit 143' TERM
  trap 'kivou_rollout_on_exit $?' EXIT
}
# KIVOU_ROLLBACK_ENGINE_END

sudo test -f "$KIVOU_ROLLOUT_LOCK"; sudo test ! -L "$KIVOU_ROLLOUT_LOCK"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_LOCK")" = root:root:600
flock --exclusive 9
KIVOU_MUTATION_STARTED=0
KIVOU_COMMITTED=0
KIVOU_ROLLBACK_RUNNING=0
kivou_arm_rollout_traps

KIVOU_MUTATION_STARTED=1
KIVOU_FIRST_RUNTIME_MUTATION=1
for KIVOU_UNIT in "${KIVOU_ROLLOUT_UNITS[@]}"; do
  if sudo systemctl list-unit-files "$KIVOU_UNIT" --no-legend | grep -q .; then sudo systemctl disable --now "$KIVOU_UNIT"; fi
done
for KIVOU_UNIT in "${KIVOU_UNIT_NAMES[@]}"; do
  KIVOU_UNIT_PATH=/etc/systemd/system/$KIVOU_UNIT
  KIVOU_UNIT_NEW=$KIVOU_UNIT_PATH.new
  case "$KIVOU_UNIT_NEW" in (/etc/systemd/system/kivou-*.new) ;; (*) kivou_fail 69 ;; esac
  sudo install -o root -g root -m 644 "$KIVOU_UNIT_STAGE_DIR/$KIVOU_UNIT" "$KIVOU_UNIT_NEW"
  sudo chown root:root "$KIVOU_UNIT_NEW"
  sudo chmod 644 "$KIVOU_UNIT_NEW"
  sudo mv -Tf "$KIVOU_UNIT_NEW" "$KIVOU_UNIT_PATH"
done
sudo systemctl daemon-reload

KIVOU_APP_LINK_NEW=/srv/kivou/app.new-$KIVOU_RELEASE_SHORT
KIVOU_FRONTEND_LINK_NEW=/srv/kivou/frontend.new-$KIVOU_RELEASE_SHORT
case "$KIVOU_APP_LINK_NEW" in (/srv/kivou/app.new-*) ;; (*) kivou_fail 69 ;; esac
case "$KIVOU_FRONTEND_LINK_NEW" in (/srv/kivou/frontend.new-*) ;; (*) kivou_fail 69 ;; esac
sudo test ! -e "$KIVOU_APP_LINK_NEW"; sudo test ! -L "$KIVOU_APP_LINK_NEW"
sudo ln -s "$KIVOU_BACKEND_RELEASE_DIR" "$KIVOU_APP_LINK_NEW"
sudo mv -Tf "$KIVOU_APP_LINK_NEW" /srv/kivou/app
sudo test "$(sudo readlink -f /srv/kivou/app)" = "$KIVOU_BACKEND_RELEASE_DIR"
sudo test ! -e "$KIVOU_FRONTEND_LINK_NEW"; sudo test ! -L "$KIVOU_FRONTEND_LINK_NEW"
sudo ln -s "$KIVOU_FRONTEND_RELEASE_DIR" "$KIVOU_FRONTEND_LINK_NEW"
sudo mv -Tf "$KIVOU_FRONTEND_LINK_NEW" /srv/kivou/frontend
sudo test "$(sudo readlink -f /srv/kivou/frontend)" = "$KIVOU_FRONTEND_RELEASE_DIR"

sudo systemctl enable --now kivou-api.service
sudo systemctl is-active --quiet kivou-api.service
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  /srv/kivou/app/ops/bin/kivou-api-readiness.sh kivou-api.service 8000

KIVOU_NGINX_STAGE_NAMES=(
  kivou-limits.conf kivou-proxy-params.conf
  kivou-production-security-headers.conf
  kivou-production-sensitive-link-security-headers.conf
  kivou-sensitive-links-gate.conf kivou-production-default-deny.conf
  kivou-production.conf kivou-production-www.conf
)
KIVOU_NGINX_DESTINATIONS=(
  /etc/nginx/conf.d/kivou-limits.conf
  /etc/nginx/kivou-proxy-params.conf
  /etc/nginx/kivou-production-security-headers.conf
  /etc/nginx/kivou-production-sensitive-link-security-headers.conf
  /etc/nginx/kivou-sensitive-links-gate.conf
  /etc/nginx/sites-available/kivou-production-default-deny
  /etc/nginx/sites-available/kivou
  /etc/nginx/sites-available/kivou-www
)
for KIVOU_INDEX in "${!KIVOU_NGINX_STAGE_NAMES[@]}"; do
  KIVOU_NGINX_PATH=${KIVOU_NGINX_DESTINATIONS[$KIVOU_INDEX]}
  KIVOU_NGINX_NEW=$KIVOU_NGINX_PATH.new
  case "$KIVOU_NGINX_NEW" in (/etc/nginx/*.new|/etc/nginx/*/*.new) ;; (*) kivou_fail 69 ;; esac
  KIVOU_NGINX_MODE=644
  if [ "${KIVOU_NGINX_STAGE_NAMES[$KIVOU_INDEX]}" = kivou-sensitive-links-gate.conf ]; then KIVOU_NGINX_MODE=600; fi
  sudo install -o root -g root -m "$KIVOU_NGINX_MODE" "$KIVOU_NGINX_STAGE_DIR/${KIVOU_NGINX_STAGE_NAMES[$KIVOU_INDEX]}" "$KIVOU_NGINX_NEW"
  sudo mv -Tf "$KIVOU_NGINX_NEW" "$KIVOU_NGINX_PATH"
done
if sudo test -e /etc/nginx/sites-enabled/default || sudo test -L /etc/nginx/sites-enabled/default; then
  sudo mv -Tf /etc/nginx/sites-enabled/default "$KIVOU_FAILED_DIR/nginx-default-link"
fi
for KIVOU_SITE in kivou-production-default-deny kivou kivou-www; do
  KIVOU_SITE_LINK_NEW=/etc/nginx/sites-enabled/$KIVOU_SITE.new
  case "$KIVOU_SITE_LINK_NEW" in (/etc/nginx/sites-enabled/*.new) ;; (*) kivou_fail 69 ;; esac
  sudo test ! -e "$KIVOU_SITE_LINK_NEW"; sudo test ! -L "$KIVOU_SITE_LINK_NEW"
  sudo ln -s "/etc/nginx/sites-available/$KIVOU_SITE" "$KIVOU_SITE_LINK_NEW"
  sudo mv -Tf "$KIVOU_SITE_LINK_NEW" "/etc/nginx/sites-enabled/$KIVOU_SITE"
done
sudo nginx -t
if [ "$KIVOU_NGINX_WAS_ACTIVE" = active ]; then
  sudo systemctl enable nginx
  sudo systemctl reload nginx
else
  sudo systemctl enable --now nginx
fi
sudo systemctl is-enabled --quiet nginx
sudo systemctl is-active --quiet nginx

KIVOU_HTTPS_HEALTH_URL=https://kivou.eu/
KIVOU_HTTPS_STATUS=$(curl --silent --show-error --output /dev/null --connect-timeout 5 --max-time 15 --write-out '%{http_code}' "$KIVOU_HTTPS_HEALTH_URL")
test "$KIVOU_HTTPS_STATUS" = 200
KIVOU_WWW_STATUS=$(curl --silent --show-error --output /dev/null --connect-timeout 5 --max-time 15 --write-out '%{http_code}' https://www.kivou.eu/)
case "$KIVOU_WWW_STATUS" in (301|302|307|308) ;; (*) kivou_fail 69 ;; esac

sudo systemctl start kivou-backup.service
if sudo systemctl is-failed --quiet kivou-backup-local.service; then kivou_fail 70; fi
if sudo systemctl is-failed --quiet kivou-backup.service; then kivou_fail 70; fi

for KIVOU_TIMER in kivou-ingest-simap.timer kivou-ingest-boamp.timer kivou-ingest-decp.timer kivou-ingest-ted.timer; do
  if sudo systemctl is-enabled --quiet "$KIVOU_TIMER"; then kivou_fail 70; fi
  if sudo systemctl is-active --quiet "$KIVOU_TIMER"; then kivou_fail 70; fi
done
sudo systemctl start kivou-ingest@simap.service
if sudo systemctl is-failed --quiet kivou-ingest@simap.service; then kivou_fail 70; fi
sudo systemctl start kivou-ingest@boamp.service
if sudo systemctl is-failed --quiet kivou-ingest@boamp.service; then kivou_fail 70; fi
sudo systemctl start kivou-ingest@decp.service
if sudo systemctl is-failed --quiet kivou-ingest@decp.service; then kivou_fail 70; fi
sudo systemctl start kivou-ingest@ted.service
if sudo systemctl is-failed --quiet kivou-ingest@ted.service; then kivou_fail 70; fi
sudo systemctl enable --now \
  kivou-ingest-simap.timer kivou-ingest-boamp.timer \
  kivou-ingest-decp.timer kivou-ingest-ted.timer
sudo systemctl enable --now kivou-backup.timer
sudo systemctl disable --now kivou-alerts.timer kivou-alerts.service
kivou_mark_rollout_status COMMITTED
KIVOU_COMMITTED=1
kivou_disarm_rollout_traps
KIVOU_MUTATION_WINDOW_END=1
```

Stop gate : une seule fenêtre protégée a installé les unités, basculé les deux
releases, prouvé l'API 8000, publié nginx, vérifié HTTPS, fumé backup, puis fumé
les quatre sources avec tous leurs timers désactivés avant leur activation
groupée. Alertes et SMTP restent bloqués en attente d'une autorisation séparée.

## 11. Rollback immédiat autonome après perte de session

Ce bloc est autonome et doit être lancé dans une nouvelle session `sudo -i`.
Il ne dépend d'aucune variable ou fonction de la fenêtre précédente. Le pointeur
fixe est résolu et borné ; seul un rollout `PREPARED` peut être restauré. Un
rollout `COMMITTED` ou `ROLLED_BACK` est refusé. Le rollback conserve toutes les
captures, releases et sauvegardes. Si cette reprise est elle-même interrompue,
rouvrir `sudo -i` et relancer ce bloc en entier : le statut reste `PREPARED`, un
nouvel attempt unique est créé et chaque restauration peut être rejouée.

```bash
set -euo pipefail
test "$(id -u)" -eq 0
KIVOU_ROLLOUT_LOCK=/run/lock/kivou-production-rollout.lock
test -f "$KIVOU_ROLLOUT_LOCK"; test ! -L "$KIVOU_ROLLOUT_LOCK"
test "$(stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_LOCK")" = root:root:600
exec 9<>"$KIVOU_ROLLOUT_LOCK"
flock --exclusive 9

test -L /srv/kivou/rollbacks/current
KIVOU_ROLLBACK_DIR=$(readlink -f /srv/kivou/rollbacks/current)
case "$KIVOU_ROLLBACK_DIR" in (/srv/kivou/rollbacks/rollout-*) ;; (*) exit 69 ;; esac
test -d "$KIVOU_ROLLBACK_DIR"; test ! -L "$KIVOU_ROLLBACK_DIR"
test "$(stat -c '%U:%G:%a' "$KIVOU_ROLLBACK_DIR")" = root:root:700
KIVOU_ROLLOUT_STATUS=$KIVOU_ROLLBACK_DIR/rollout.status
KIVOU_ROLLOUT_STATE=$KIVOU_ROLLBACK_DIR/links.manifest
for KIVOU_MANIFEST in "$KIVOU_ROLLOUT_STATUS" "$KIVOU_ROLLOUT_STATE"; do
  test -f "$KIVOU_MANIFEST"; test ! -L "$KIVOU_MANIFEST"
  test "$(stat -c '%U:%G:%a' "$KIVOU_MANIFEST")" = root:root:600
done
test "$(sed -n '1p' "$KIVOU_ROLLOUT_STATUS")" = PREPARED
test "$(wc -l < "$KIVOU_ROLLOUT_STATE")" = 2
KIVOU_PREVIOUS_APP_TARGET=$(sed -n '1p' "$KIVOU_ROLLOUT_STATE")
KIVOU_PREVIOUS_FRONTEND_TARGET=$(sed -n '2p' "$KIVOU_ROLLOUT_STATE")
case "$KIVOU_PREVIOUS_APP_TARGET" in (ABSENT|/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
case "$KIVOU_PREVIOUS_FRONTEND_TARGET" in (ABSENT|/srv/kivou/releases/frontend-*) ;; (*) exit 69 ;; esac
KIVOU_ROLLBACK_READINESS=$KIVOU_ROLLBACK_DIR/kivou-api-readiness.sh
case "$KIVOU_ROLLBACK_READINESS" in (/srv/kivou/rollbacks/rollout-*/kivou-api-readiness.sh) ;; (*) exit 69 ;; esac
test -f "$KIVOU_ROLLBACK_READINESS"; test ! -L "$KIVOU_ROLLBACK_READINESS"
test "$(stat -c '%U:%G:%a' "$KIVOU_ROLLBACK_READINESS")" = root:root:555

KIVOU_UNIT_CAPTURE_DIR=$KIVOU_ROLLBACK_DIR/systemd
KIVOU_UNIT_NAMES=(
  kivou-api.service
  kivou-alerts.service kivou-alerts.timer
  kivou-backup-local.service kivou-backup.service kivou-backup.timer
  kivou-ingest@.service
  kivou-ingest-simap.timer kivou-ingest-boamp.timer
  kivou-ingest-decp.timer kivou-ingest-ted.timer
)
KIVOU_ROLLOUT_UNITS=(
  kivou-api.service
  kivou-alerts.service kivou-alerts.timer
  kivou-backup-local.service kivou-backup.service kivou-backup.timer
  kivou-ingest@simap.service kivou-ingest-simap.timer
  kivou-ingest@boamp.service kivou-ingest-boamp.timer
  kivou-ingest@decp.service kivou-ingest-decp.timer
  kivou-ingest@ted.service kivou-ingest-ted.timer
)
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
KIVOU_NGINX_SITE_LINKS=(
  /etc/nginx/sites-enabled/default
  /etc/nginx/sites-enabled/kivou-production-default-deny
  /etc/nginx/sites-enabled/kivou
  /etc/nginx/sites-enabled/kivou-www
)
KIVOU_NGINX_WAS_ENABLED=$(sed -n '1p' "$KIVOU_ROLLBACK_DIR/nginx.enabled")
KIVOU_NGINX_WAS_ACTIVE=$(sed -n '1p' "$KIVOU_ROLLBACK_DIR/nginx.active")
case "$KIVOU_NGINX_WAS_ENABLED" in (enabled|disabled) ;; (*) exit 69 ;; esac
case "$KIVOU_NGINX_WAS_ACTIVE" in (active|inactive) ;; (*) exit 69 ;; esac

KIVOU_RECOVERY_ATTEMPT_DIR=$(mktemp -d "$KIVOU_ROLLBACK_DIR/recovery-attempt.XXXXXX")
case "$KIVOU_RECOVERY_ATTEMPT_DIR" in ("$KIVOU_ROLLBACK_DIR"/recovery-attempt.??????) ;; (*) exit 69 ;; esac
test -d "$KIVOU_RECOVERY_ATTEMPT_DIR"; test ! -L "$KIVOU_RECOVERY_ATTEMPT_DIR"
test "$(stat -c '%U:%G:%a' "$KIVOU_RECOVERY_ATTEMPT_DIR")" = root:root:700
KIVOU_RECOVERY_ATTEMPT_ID=${KIVOU_RECOVERY_ATTEMPT_DIR##*.}
case "$KIVOU_RECOVERY_ATTEMPT_ID" in (*[!A-Za-z0-9]*|'') exit 69 ;; esac
test "${#KIVOU_RECOVERY_ATTEMPT_ID}" = 6
KIVOU_FAILED_DIR=$KIVOU_RECOVERY_ATTEMPT_DIR

kivou_recovery_cleanup() {
  case "$KIVOU_RECOVERY_ATTEMPT_DIR" in ("$KIVOU_ROLLBACK_DIR"/recovery-attempt.??????) ;; (*) return 69 ;; esac
  if test -e "$KIVOU_RECOVERY_ATTEMPT_DIR"; then
    test -d "$KIVOU_RECOVERY_ATTEMPT_DIR"; test ! -L "$KIVOU_RECOVERY_ATTEMPT_DIR"
    find "$KIVOU_RECOVERY_ATTEMPT_DIR" -xdev -depth -delete
  fi
}

kivou_recovery_on_exit() {
  KIVOU_RECOVERY_EXIT_RC=$1
  trap - HUP INT TERM EXIT
  set +e
  kivou_recovery_cleanup
  KIVOU_RECOVERY_CLEANUP_RC=$?
  if [ "$KIVOU_RECOVERY_EXIT_RC" -eq 0 ] && [ "$KIVOU_RECOVERY_CLEANUP_RC" -ne 0 ]; then
    KIVOU_RECOVERY_EXIT_RC=$KIVOU_RECOVERY_CLEANUP_RC
  fi
  exit "$KIVOU_RECOVERY_EXIT_RC"
}

kivou_recovery_request_exit() {
  KIVOU_RECOVERY_SIGNAL_RC=$1
  trap - HUP INT TERM
  exit "$KIVOU_RECOVERY_SIGNAL_RC"
}

trap 'kivou_recovery_request_exit 129' HUP
trap 'kivou_recovery_request_exit 130' INT
trap 'kivou_recovery_request_exit 143' TERM
trap 'kivou_recovery_on_exit $?' EXIT

kivou_recovery_capture_nginx() {
  KIVOU_NGINX_CURRENT_BUNDLE=$KIVOU_FAILED_DIR/nginx-current
  install -o root -g root -m 700 -d "$KIVOU_NGINX_CURRENT_BUNDLE"
  for KIVOU_NGINX_PATH in "${KIVOU_NGINX_CAPTURE_PATHS[@]}" "${KIVOU_NGINX_SITE_LINKS[@]}"; do
    case "$KIVOU_NGINX_PATH" in (/etc/nginx/*) ;; (*) return 69 ;; esac
    KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_NGINX_PATH" | sed 's#^/##; s#/#__#g')
    if test -e "$KIVOU_NGINX_PATH" || test -L "$KIVOU_NGINX_PATH"; then
      cp -a "$KIVOU_NGINX_PATH" "$KIVOU_NGINX_CURRENT_BUNDLE/$KIVOU_CAPTURE_NAME.saved"
    else
      touch "$KIVOU_NGINX_CURRENT_BUNDLE/$KIVOU_CAPTURE_NAME.ABSENT"
    fi
  done
}

kivou_recovery_apply_nginx_bundle() {
  KIVOU_BUNDLE=$1
  KIVOU_EVAC=$2
  case "$KIVOU_BUNDLE" in ("$KIVOU_ROLLBACK_DIR"/nginx|"$KIVOU_RECOVERY_ATTEMPT_DIR"/nginx-current) ;; (*) return 69 ;; esac
  case "$KIVOU_EVAC" in ("$KIVOU_RECOVERY_ATTEMPT_DIR"/nginx-*) ;; (*) return 69 ;; esac
  install -o root -g root -m 700 -d "$KIVOU_EVAC"
  for KIVOU_NGINX_PATH in "${KIVOU_NGINX_CAPTURE_PATHS[@]}" "${KIVOU_NGINX_SITE_LINKS[@]}"; do
    case "$KIVOU_NGINX_PATH" in (/etc/nginx/*) ;; (*) return 69 ;; esac
    KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_NGINX_PATH" | sed 's#^/##; s#/#__#g')
    if test -e "$KIVOU_NGINX_PATH" || test -L "$KIVOU_NGINX_PATH"; then
      test ! -e "$KIVOU_EVAC/$KIVOU_CAPTURE_NAME"; test ! -L "$KIVOU_EVAC/$KIVOU_CAPTURE_NAME"
      mv -Tf "$KIVOU_NGINX_PATH" "$KIVOU_EVAC/$KIVOU_CAPTURE_NAME"
    fi
    if test -e "$KIVOU_BUNDLE/$KIVOU_CAPTURE_NAME.saved" || test -L "$KIVOU_BUNDLE/$KIVOU_CAPTURE_NAME.saved"; then
      KIVOU_NGINX_NEW=$KIVOU_NGINX_PATH.recovery-$KIVOU_RECOVERY_ATTEMPT_ID-new
      case "$KIVOU_NGINX_NEW" in (/etc/nginx/*.recovery-??????-new|/etc/nginx/*/*.recovery-??????-new) ;; (*) return 69 ;; esac
      KIVOU_NGINX_STALE=$KIVOU_RECOVERY_ATTEMPT_DIR/stale-$KIVOU_CAPTURE_NAME
      case "$KIVOU_NGINX_STALE" in ("$KIVOU_RECOVERY_ATTEMPT_DIR"/stale-*) ;; (*) return 69 ;; esac
      if test -e "$KIVOU_NGINX_NEW" || test -L "$KIVOU_NGINX_NEW"; then
        mv -Tf "$KIVOU_NGINX_NEW" "$KIVOU_NGINX_STALE"
      fi
      cp -a "$KIVOU_BUNDLE/$KIVOU_CAPTURE_NAME.saved" "$KIVOU_NGINX_NEW"
      mv -Tf "$KIVOU_NGINX_NEW" "$KIVOU_NGINX_PATH"
    else
      test -f "$KIVOU_BUNDLE/$KIVOU_CAPTURE_NAME.ABSENT"
    fi
  done
}

kivou_recovery_restore_unit_states() {
  for KIVOU_UNIT in "${KIVOU_ROLLOUT_UNITS[@]}"; do
    KIVOU_UNIT_WAS_ENABLED=$(sed -n '1p' "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.enabled")
    KIVOU_UNIT_WAS_ACTIVE=$(sed -n '1p' "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.active")
    case "$KIVOU_UNIT_WAS_ENABLED" in
      (enabled) systemctl enable "$KIVOU_UNIT" ;;
      (masked) systemctl mask "$KIVOU_UNIT" ;;
      (disabled) systemctl disable "$KIVOU_UNIT" ;;
      (not-found) ;;
      (static|indirect) ;;
      (*) return 69 ;;
    esac
    if [ "$KIVOU_UNIT_WAS_ACTIVE" = active ]; then
      systemctl start "$KIVOU_UNIT"
    elif [ "$KIVOU_UNIT_WAS_ENABLED" != not-found ]; then
      systemctl stop "$KIVOU_UNIT"
    fi
  done
}

KIVOU_ROLLBACK_READINESS_MARKER=$KIVOU_RECOVERY_ATTEMPT_DIR/api-readiness.ok
case "$KIVOU_ROLLBACK_READINESS_MARKER" in ("$KIVOU_ROLLBACK_DIR"/recovery-attempt.??????/api-readiness.ok) ;; (*) exit 69 ;; esac

kivou_rollback_api_readiness_required() {
  KIVOU_API_WAS_ACTIVE=$(sed -n '1p' "$KIVOU_UNIT_CAPTURE_DIR/kivou-api.service.active")
  case "$KIVOU_API_WAS_ACTIVE" in (active|inactive|failed|unknown) ;; (*) return 69 ;; esac
  [ "$KIVOU_API_WAS_ACTIVE" = active ] && [ "$KIVOU_PREVIOUS_APP_TARGET" != ABSENT ]
}

kivou_evaluate_rollback_api_readiness_requirement() {
  KIVOU_READINESS_ERREXIT_WAS_SET=0
  case "$-" in (*e*) KIVOU_READINESS_ERREXIT_WAS_SET=1 ;; esac
  set +e
  ( set -Eeuo pipefail; kivou_rollback_api_readiness_required )
  KIVOU_READINESS_REQUIRED_RC=$?
  if [ "$KIVOU_READINESS_ERREXIT_WAS_SET" = 1 ]; then set -e; fi
}

kivou_verify_rollback_api_readiness() {
  kivou_evaluate_rollback_api_readiness_requirement
  case "$KIVOU_READINESS_REQUIRED_RC" in (0) ;; (1) return 0 ;; (*) return "$KIVOU_READINESS_REQUIRED_RC" ;; esac
  test "$(readlink -f /srv/kivou/app)" = "$KIVOU_PREVIOUS_APP_TARGET"
  test -f "$KIVOU_ROLLBACK_READINESS"; test ! -L "$KIVOU_ROLLBACK_READINESS"
  test "$(stat -c '%U:%G:%a' "$KIVOU_ROLLBACK_READINESS")" = root:root:555
  /usr/bin/env -i HOME=/root PATH=/usr/bin:/bin \
    "$KIVOU_ROLLBACK_READINESS" kivou-api.service 8000
  touch "$KIVOU_ROLLBACK_READINESS_MARKER"
  chown root:root "$KIVOU_ROLLBACK_READINESS_MARKER"
  chmod 400 "$KIVOU_ROLLBACK_READINESS_MARKER"
}

kivou_require_rollback_api_readiness() {
  kivou_evaluate_rollback_api_readiness_requirement
  case "$KIVOU_READINESS_REQUIRED_RC" in (0) ;; (1) return 0 ;; (*) return "$KIVOU_READINESS_REQUIRED_RC" ;; esac
  test -f "$KIVOU_ROLLBACK_READINESS_MARKER"
  test ! -L "$KIVOU_ROLLBACK_READINESS_MARKER"
  test "$(stat -c '%U:%G:%a' "$KIVOU_ROLLBACK_READINESS_MARKER")" = root:root:400
}

kivou_rollback_stop_phase() {
  for KIVOU_UNIT in \
    kivou-ingest-simap.timer kivou-ingest-boamp.timer \
    kivou-ingest-decp.timer kivou-ingest-ted.timer \
    kivou-backup.timer kivou-alerts.timer kivou-alerts.service \
    kivou-api.service; do
    if systemctl is-enabled --quiet "$KIVOU_UNIT"; then
      systemctl disable --now "$KIVOU_UNIT"
    elif systemctl is-active --quiet "$KIVOU_UNIT"; then
      systemctl stop "$KIVOU_UNIT"
    fi
  done
  for KIVOU_UNIT in \
    kivou-ingest@simap.service kivou-ingest@boamp.service \
    kivou-ingest@decp.service kivou-ingest@ted.service \
    kivou-backup.service kivou-backup-local.service; do
    if systemctl is-active --quiet "$KIVOU_UNIT"; then systemctl stop "$KIVOU_UNIT"; fi
  done
}

kivou_rollback_app_phase() {
  case "$KIVOU_PREVIOUS_APP_TARGET" in
    (ABSENT)
      if test -L /srv/kivou/app; then mv -Tf /srv/kivou/app "$KIVOU_FAILED_DIR/app-link"; else test ! -e /srv/kivou/app; fi
      ;;
    (/srv/kivou/releases/backend-*)
      test -d "$KIVOU_PREVIOUS_APP_TARGET"
      test -z "$(find "$KIVOU_PREVIOUS_APP_TARGET" -perm /222 -print -quit)"
      KIVOU_APP_RECOVERY_NEW=$KIVOU_RECOVERY_ATTEMPT_DIR/app-link.new
      case "$KIVOU_APP_RECOVERY_NEW" in ("$KIVOU_RECOVERY_ATTEMPT_DIR"/app-link.new) ;; (*) return 69 ;; esac
      test ! -e "$KIVOU_APP_RECOVERY_NEW"; test ! -L "$KIVOU_APP_RECOVERY_NEW"
      ln -s "$KIVOU_PREVIOUS_APP_TARGET" "$KIVOU_APP_RECOVERY_NEW"
      mv -Tf "$KIVOU_APP_RECOVERY_NEW" /srv/kivou/app
      ;;
    (*) return 69 ;;
  esac
}

kivou_rollback_frontend_phase() {
  case "$KIVOU_PREVIOUS_FRONTEND_TARGET" in
    (ABSENT)
      if test -L /srv/kivou/frontend; then mv -Tf /srv/kivou/frontend "$KIVOU_FAILED_DIR/frontend-link"; else test ! -e /srv/kivou/frontend; fi
      ;;
    (/srv/kivou/releases/frontend-*)
      test -d "$KIVOU_PREVIOUS_FRONTEND_TARGET"
      test -z "$(find "$KIVOU_PREVIOUS_FRONTEND_TARGET" -perm /222 -print -quit)"
      KIVOU_FRONTEND_RECOVERY_NEW=$KIVOU_RECOVERY_ATTEMPT_DIR/frontend-link.new
      case "$KIVOU_FRONTEND_RECOVERY_NEW" in ("$KIVOU_RECOVERY_ATTEMPT_DIR"/frontend-link.new) ;; (*) return 69 ;; esac
      test ! -e "$KIVOU_FRONTEND_RECOVERY_NEW"; test ! -L "$KIVOU_FRONTEND_RECOVERY_NEW"
      ln -s "$KIVOU_PREVIOUS_FRONTEND_TARGET" "$KIVOU_FRONTEND_RECOVERY_NEW"
      mv -Tf "$KIVOU_FRONTEND_RECOVERY_NEW" /srv/kivou/frontend
      ;;
    (*) return 69 ;;
  esac
}

kivou_rollback_units_phase() {
  install -o root -g root -m 700 -d "$KIVOU_FAILED_DIR/systemd-current"
  for KIVOU_UNIT in "${KIVOU_UNIT_NAMES[@]}"; do
    KIVOU_UNIT_PATH=/etc/systemd/system/$KIVOU_UNIT
    case "$KIVOU_UNIT_PATH" in (/etc/systemd/system/kivou-*) ;; (*) return 69 ;; esac
    if test -e "$KIVOU_UNIT_PATH" || test -L "$KIVOU_UNIT_PATH"; then
      mv -Tf "$KIVOU_UNIT_PATH" "$KIVOU_FAILED_DIR/systemd-current/$KIVOU_UNIT"
    fi
    if test -e "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.saved" || test -L "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.saved"; then
      KIVOU_UNIT_RECOVERY_NEW=$KIVOU_UNIT_PATH.recovery-$KIVOU_RECOVERY_ATTEMPT_ID-new
      case "$KIVOU_UNIT_RECOVERY_NEW" in (/etc/systemd/system/kivou-*.recovery-??????-new) ;; (*) return 69 ;; esac
      KIVOU_UNIT_STALE=$KIVOU_RECOVERY_ATTEMPT_DIR/stale-systemd-$KIVOU_UNIT
      case "$KIVOU_UNIT_STALE" in ("$KIVOU_RECOVERY_ATTEMPT_DIR"/stale-systemd-kivou-*) ;; (*) return 69 ;; esac
      if test -e "$KIVOU_UNIT_RECOVERY_NEW" || test -L "$KIVOU_UNIT_RECOVERY_NEW"; then
        mv -Tf "$KIVOU_UNIT_RECOVERY_NEW" "$KIVOU_UNIT_STALE"
      fi
      cp -a "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.saved" "$KIVOU_UNIT_RECOVERY_NEW"
      mv -Tf "$KIVOU_UNIT_RECOVERY_NEW" "$KIVOU_UNIT_PATH"
    else
      test -f "$KIVOU_UNIT_CAPTURE_DIR/$KIVOU_UNIT.ABSENT"
    fi
  done
  systemctl daemon-reload
  kivou_recovery_restore_unit_states
  kivou_verify_rollback_api_readiness
}

kivou_rollback_nginx_phase() {
  kivou_require_rollback_api_readiness
  test -d "$KIVOU_ROLLBACK_DIR/nginx"
  test -z "$(find "$KIVOU_ROLLBACK_DIR/nginx" -perm /222 -print -quit)"
  for KIVOU_NGINX_PATH in "${KIVOU_NGINX_CAPTURE_PATHS[@]}" "${KIVOU_NGINX_SITE_LINKS[@]}"; do
    KIVOU_CAPTURE_NAME=$(printf '%s' "$KIVOU_NGINX_PATH" | sed 's#^/##; s#/#__#g')
    if test -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved" || test -L "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.saved"; then
      test ! -e "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT"
    else
      test -f "$KIVOU_ROLLBACK_DIR/nginx/$KIVOU_CAPTURE_NAME.ABSENT"
    fi
  done
  kivou_recovery_capture_nginx
  kivou_recovery_apply_nginx_bundle "$KIVOU_ROLLBACK_DIR/nginx" "$KIVOU_FAILED_DIR/nginx-replaced"
  if ! nginx -t; then
    kivou_recovery_apply_nginx_bundle "$KIVOU_NGINX_CURRENT_BUNDLE" "$KIVOU_FAILED_DIR/nginx-invalid"
    return 71
  fi
  if [ "$KIVOU_NGINX_WAS_ACTIVE" = active ]; then
    if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl start nginx; fi
  elif systemctl is-active --quiet nginx; then
    systemctl stop nginx
  fi
  if [ "$KIVOU_NGINX_WAS_ENABLED" = enabled ]; then systemctl enable nginx; else systemctl disable nginx; fi
}

kivou_recovery_rollback() {
  set +e
  KIVOU_RECOVERY_RC=0
  for KIVOU_PHASE in stop app frontend units nginx; do
    case "$KIVOU_PHASE" in
      (stop) ( set -Eeuo pipefail; kivou_rollback_stop_phase ) ;;
      (app) ( set -Eeuo pipefail; kivou_rollback_app_phase ) ;;
      (frontend) ( set -Eeuo pipefail; kivou_rollback_frontend_phase ) ;;
      (units) ( set -Eeuo pipefail; kivou_rollback_units_phase ) ;;
      (nginx) ( set -Eeuo pipefail; kivou_rollback_nginx_phase ) ;;
      (*) ( exit 69 ) ;;
    esac
    KIVOU_PHASE_RC=$?
    if [ "$KIVOU_PHASE_RC" -ne 0 ] && [ "$KIVOU_RECOVERY_RC" -eq 0 ]; then KIVOU_RECOVERY_RC=$KIVOU_PHASE_RC; fi
  done
  return "$KIVOU_RECOVERY_RC"
}

set +e
kivou_recovery_rollback
KIVOU_RECOVERY_RC=$?
set -e
if [ "$KIVOU_RECOVERY_RC" -ne 0 ]; then exit "$KIVOU_RECOVERY_RC"; fi
kivou_recovery_cleanup
KIVOU_STATUS_NEW=$KIVOU_ROLLOUT_STATUS.recovered-$$
case "$KIVOU_STATUS_NEW" in (/srv/kivou/rollbacks/rollout-*/rollout.status.recovered-*) ;; (*) exit 69 ;; esac
printf '%s\n' ROLLED_BACK >"$KIVOU_STATUS_NEW"
chown root:root "$KIVOU_STATUS_NEW"; chmod 600 "$KIVOU_STATUS_NEW"
mv -Tf "$KIVOU_STATUS_NEW" "$KIVOU_ROLLOUT_STATUS"
trap - HUP INT TERM EXIT
```
