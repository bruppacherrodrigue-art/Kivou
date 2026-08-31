# Rollout staging Card Intelligence × QA Signals

Ce runbook promeut un unique SHA final de `main` vers l'hôte de staging. Il
prépare les artefacts Card Intelligence, mais n'active aucune génération IA :
les seules publications autorisées ici sont `FALLBACK/FACTUAL_FALLBACK`, hors
des requêtes GET. Aucun provider, modèle, prompt, QA provider ou worker live
n'est configuré ou exécuté.

La seule cible SSH connue de cette procédure est `kivou-staging`; son hostname
court doit être `kivou-staging-01`. Garder un même shell local du début à la fin
afin de conserver les valeurs gelées. Ne jamais afficher ni copier un fichier
d'environnement, un cookie, une donnée de compte ou un fait source.

**STOP immédiat** si le SHA final, la CI push exacte, ses jobs et étapes, le
hostname, les deux liens de release, la révision de base, la sauvegarde, la
procédure blue/green, le root de preuves externe ou l'approbation QA ne sont pas
prouvés exactement. Une topologie différente de celle documentée exige une
validation du propriétaire avant la première mutation.

## 1. Geler le SHA final et prouver la CI réellement exécutée

Partir d'un checkout propre. Le run historique sans runner ou sans étapes ne
vaut aucune validation. Le JSON conservé ci-dessous doit montrer deux jobs
terminés, des tableaux d'étapes non vides, toutes les étapes exécutées vertes et
seulement l'étape conditionnelle d'upload éventuellement ignorée.

~~~bash
set -euo pipefail
KIVOU_REPOSITORY=bruppacherrodrigue-art/Kivou

git fetch origin main
KIVOU_FINAL_SHA=$(git rev-parse origin/main)
printf '%s\n' "$KIVOU_FINAL_SHA" | grep -Eq '^[0-9a-f]{40}$'
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
test "$(git rev-parse 'origin/main^{tree}')" = \
  "$(gh api "repos/$KIVOU_REPOSITORY/git/commits/$KIVOU_FINAL_SHA" --jq .tree.sha)"

KIVOU_CI_RUN_ID=$(gh run list --repo "$KIVOU_REPOSITORY" \
  --workflow CI --branch main --commit "$KIVOU_FINAL_SHA" \
  --event push --status success --limit 1 \
  --json databaseId,headSha,conclusion \
  --jq '.[0].databaseId')
test -n "$KIVOU_CI_RUN_ID"

KIVOU_CI_JSON_PAYLOAD=$(gh run view "$KIVOU_CI_RUN_ID" \
  --repo "$KIVOU_REPOSITORY" --json headSha,status,conclusion,jobs)

jq -e --arg sha "$KIVOU_FINAL_SHA" '
  def one_successful_job($name; $required):
    ([.jobs[] | select(.name == $name)]) as $matches
    | ($matches | length == 1)
    and ($matches[0] as $job
      | $job.status == "completed"
      and $job.conclusion == "success"
      and ($job.steps | type == "array")
      and ($job.steps | length > 0)
      and ([$job.steps[] | select(.conclusion != "skipped")] | length > 0)
      and all($job.steps[];
        .status == "completed"
        and (.conclusion == "success" or .conclusion == "skipped"))
      and any($job.steps[];
        (.name | contains("actions/checkout")) and .conclusion == "success")
      and all($required[];
        . as $required_name
        | any($job.steps[];
            .name == $required_name and .conclusion == "success")));
  .headSha == $sha
  and .status == "completed"
  and .conclusion == "success"
  and (.jobs | length == 2)
  and one_successful_job(
    "Backend (Python 3.12 · uv)";
    ["Installer uv", "Synchroniser les dépendances verrouillées", "Tests", "Lint"]
  )
  and one_successful_job(
    "Frontend (Node 24 · npm)";
    ["Installer Node", "Installer les dépendances verrouillées", "Tests",
     "Installer Chromium verrouillé", "Régression visuelle des références",
     "Build", "Build Founder Console", "Typecheck", "Lint"]
  )
' <<<"$KIVOU_CI_JSON_PAYLOAD" >/dev/null

test "$(gh api "repos/$KIVOU_REPOSITORY/commits/main" --jq .sha)" = \
  "$KIVOU_FINAL_SHA"
test "$(git rev-parse HEAD)" = "$KIVOU_FINAL_SHA"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
KIVOU_RUNBOOK_PATH=docs/runbooks/11-staging-card-presentation-rollout.md
test "$(git hash-object "$KIVOU_RUNBOOK_PATH")" = \
  "$(git rev-parse "$KIVOU_FINAL_SHA:$KIVOU_RUNBOOK_PATH")"

: "${KIVOU_CARD_EVIDENCE_ROOT:?STOP: evidence root absolu opérateur requis}"
kivou_validate_evidence_root() {
  case "$KIVOU_CARD_EVIDENCE_ROOT" in
    (/*) ;;
    (*) return 69 ;;
  esac
  test -d "$KIVOU_CARD_EVIDENCE_ROOT"
  test ! -L "$KIVOU_CARD_EVIDENCE_ROOT"
  KIVOU_CARD_EVIDENCE_ROOT_REAL=$(readlink -f \
    "$KIVOU_CARD_EVIDENCE_ROOT")
  test "$KIVOU_CARD_EVIDENCE_ROOT_REAL" = "$KIVOU_CARD_EVIDENCE_ROOT"
  test "$(stat -c '%U:%a' "$KIVOU_CARD_EVIDENCE_ROOT_REAL")" = \
    "$(id -un):700"
  KIVOU_OPERATOR_ROOT_REAL=$(readlink -f "$(git rev-parse --show-toplevel)")
  case "$KIVOU_CARD_EVIDENCE_ROOT_REAL" in
    ("$KIVOU_OPERATOR_ROOT_REAL"|"$KIVOU_OPERATOR_ROOT_REAL"/*) return 69 ;;
    (*) ;;
  esac
}
kivou_validate_evidence_root
KIVOU_EVIDENCE_DIR="$KIVOU_CARD_EVIDENCE_ROOT_REAL/card-presentation-$KIVOU_FINAL_SHA"
test ! -e "$KIVOU_EVIDENCE_DIR"
install -m 700 -d "$KIVOU_EVIDENCE_DIR"
test ! -L "$KIVOU_EVIDENCE_DIR"
test "$(readlink -f "$KIVOU_EVIDENCE_DIR")" = "$KIVOU_EVIDENCE_DIR"
test "$(stat -c '%U:%a' "$KIVOU_EVIDENCE_DIR")" = "$(id -un):700"
KIVOU_CI_JSON="$KIVOU_EVIDENCE_DIR/github-ci.json"
test ! -e "$KIVOU_CI_JSON"
umask 077
printf '%s\n' "$KIVOU_CI_JSON_PAYLOAD" >"$KIVOU_CI_JSON"
chmod 600 "$KIVOU_CI_JSON"
test ! -L "$KIVOU_CI_JSON"
test "$(stat -c '%U:%a' "$KIVOU_CI_JSON")" = "$(id -un):600"
KIVOU_CI_JSON_SHA256=$(sha256sum "$KIVOU_CI_JSON" | awk '{print $1}')
printf '%s\n' "$KIVOU_CI_JSON_SHA256" | grep -Eq '^[0-9a-f]{64}$'
unset KIVOU_CI_JSON_PAYLOAD
~~~

Si `main` avance après ce point, STOP : qualifier le delta et obtenir une
nouvelle CI push exacte avant de recommencer.

## 2. Prouver staging et capturer les deux rollback targets

Ce preflight est en lecture seule. Il ne charge pas le contenu de
`/etc/kivou/staging.env`; il laisse uniquement systemd le fournir au processus
isolé qui lit la révision.

~~~bash
mapfile -t KIVOU_PREFLIGHT < <(
  ssh kivou-staging 'bash -s' <<'REMOTE'
set -euo pipefail
test "$(hostname -s)" = "kivou-staging-01"
test -L /srv/kivou/app
test -L /srv/kivou/frontend
test "$(stat -c '%U:%G:%a' /etc/kivou/staging.env)" = "root:kivou:600"
systemctl is-active --quiet kivou-api.service
systemctl is-active --quiet nginx.service
systemctl is-enabled --quiet kivou-backup.timer
curl --silent --show-error --fail --connect-timeout 3 --max-time 5 \
  http://127.0.0.1:8000/openapi.json >/dev/null

KIVOU_PREVIOUS_BACKEND=$(readlink -f /srv/kivou/app)
KIVOU_PREVIOUS_FRONTEND=$(readlink -f /srv/kivou/frontend)
case "$KIVOU_PREVIOUS_BACKEND" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
case "$KIVOU_PREVIOUS_FRONTEND" in
  (/srv/kivou/releases/frontend-*) ;;
  (*) exit 69 ;;
esac
test -d "$KIVOU_PREVIOUS_BACKEND"
test -d "$KIVOU_PREVIOUS_FRONTEND"
test $((8#$(stat -c '%a' "$KIVOU_PREVIOUS_BACKEND") & 8#022)) -eq 0
test $((8#$(stat -c '%a' "$KIVOU_PREVIOUS_FRONTEND") & 8#022)) -eq 0
KIVOU_PREVIOUS_BACKEND_SHA=$(sudo -u kivou /usr/bin/env -i \
  HOME=/srv/kivou PATH=/usr/bin:/bin GIT_CONFIG_GLOBAL=/dev/null \
  GIT_CONFIG_NOSYSTEM=1 git -C "$KIVOU_PREVIOUS_BACKEND" rev-parse HEAD)
printf '%s\n' "$KIVOU_PREVIOUS_BACKEND_SHA" | grep -Eq '^[0-9a-f]{40}$'

KIVOU_CURRENT_REVISION=$(sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-preflight-$$" \
  --property=Type=oneshot --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_PREVIOUS_BACKEND" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  --property=ProtectHome=yes \
  -- "$KIVOU_PREVIOUS_BACKEND/.venv/bin/python" -c \
  'from signals.persistence.database import create_database_engine,current_revision; engine=create_database_engine(); revision=current_revision(engine); assert revision == "0027_signal_notes", revision; print(revision)')
test "$KIVOU_CURRENT_REVISION" = "0027_signal_notes"

printf 'backend=%s\nfrontend=%s\nbackend_sha=%s\nrevision=%s\n' \
  "$KIVOU_PREVIOUS_BACKEND" "$KIVOU_PREVIOUS_FRONTEND" \
  "$KIVOU_PREVIOUS_BACKEND_SHA" "$KIVOU_CURRENT_REVISION"
REMOTE
)
test "${#KIVOU_PREFLIGHT[@]}" -eq 4
KIVOU_PREVIOUS_BACKEND=${KIVOU_PREFLIGHT[0]#backend=}
KIVOU_PREVIOUS_FRONTEND=${KIVOU_PREFLIGHT[1]#frontend=}
KIVOU_PREVIOUS_BACKEND_SHA=${KIVOU_PREFLIGHT[2]#backend_sha=}
KIVOU_CURRENT_REVISION=${KIVOU_PREFLIGHT[3]#revision=}
case "$KIVOU_PREVIOUS_BACKEND" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
case "$KIVOU_PREVIOUS_FRONTEND" in (/srv/kivou/releases/frontend-*) ;; (*) exit 69 ;; esac
test "$KIVOU_CURRENT_REVISION" = "0027_signal_notes"
~~~

Conserver ces deux chemins exacts. Ne jamais redécouvrir un rollback target par
un glob ou par le seul suffixe du SHA.

## 3. Sauvegarder, lister et restaurer dans une base scratch unique

Cette étape produit une sauvegarde fraîche, en vérifie l'archive, la restaure
réellement et supprime uniquement la base scratch validée après le succès. En
cas d'échec avant la suppression, STOP et faire qualifier la base scratch
exacte; ne lancer aucun nettoyage générique.

~~~bash
ssh kivou-staging 'bash -s' -- "$KIVOU_FINAL_SHORT" <<'REMOTE'
set -euo pipefail
cd /srv/kivou
KIVOU_FINAL_SHORT=$1
printf '%s\n' "$KIVOU_FINAL_SHORT" | grep -Eq '^[0-9a-f]{12}$'
test "$(hostname -s)" = "kivou-staging-01"

KIVOU_BACKUP_STARTED=$(date -u +%s.%N)
sudo systemctl start kivou-backup.service
test "$(systemctl show kivou-backup.service --property=Result --value)" = success
mapfile -t KIVOU_BACKUP_FILES < <(
  sudo -u kivou find /srv/kivou/backups -maxdepth 1 -type f \
    -name 'kivou-*.dump' -newermt "@$KIVOU_BACKUP_STARTED" -print
)
test "${#KIVOU_BACKUP_FILES[@]}" -eq 1
KIVOU_BACKUP_FILE=${KIVOU_BACKUP_FILES[0]}
case "$KIVOU_BACKUP_FILE" in (/srv/kivou/backups/kivou-*.dump) ;; (*) exit 69 ;; esac
test "$(sudo -u kivou stat -c '%U:%G:%a' "$KIVOU_BACKUP_FILE")" = "kivou:kivou:600"

KIVOU_BACKUP_MIN_BYTES=$(sudo awk -F= \
  '$1 == "KIVOU_BACKUP_MIN_BYTES" {print $2}' /etc/kivou/staging.env)
test -n "$KIVOU_BACKUP_MIN_BYTES" || KIVOU_BACKUP_MIN_BYTES=4096
printf '%s\n' "$KIVOU_BACKUP_MIN_BYTES" | grep -Eq '^[1-9][0-9]*$'
KIVOU_BACKUP_BYTES=$(sudo -u kivou stat -c '%s' "$KIVOU_BACKUP_FILE")
test "$KIVOU_BACKUP_BYTES" -ge "$KIVOU_BACKUP_MIN_BYTES"
KIVOU_BACKUP_SHA=$(sudo -u kivou sha256sum "$KIVOU_BACKUP_FILE" | awk '{print $1}')
printf '%s\n' "$KIVOU_BACKUP_SHA" | grep -Eq '^[0-9a-f]{64}$'
KIVOU_BACKUP_TOC_LINES=$(sudo -u kivou pg_restore --list "$KIVOU_BACKUP_FILE" | wc -l)
test "$KIVOU_BACKUP_TOC_LINES" -gt 0

KIVOU_APP=$(readlink -f /srv/kivou/app)
case "$KIVOU_APP" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
KIVOU_DB_BINDING=$(sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-db-binding-$$" \
  --property=Type=oneshot --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_APP" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  -- "$KIVOU_APP/.venv/bin/python" -c \
  'import sqlalchemy as sa; from signals.persistence.database import create_database_engine; engine=create_database_engine(); connection=engine.connect(); row=connection.execute(sa.text("SELECT current_database(), pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()" )).one(); print(f"{row[0]}|{row[1]}")')
IFS='|' read -r KIVOU_LIVE_DB KIVOU_LIVE_OWNER <<EOF
$KIVOU_DB_BINDING
EOF
for KIVOU_DB_IDENTIFIER in "$KIVOU_LIVE_DB" "$KIVOU_LIVE_OWNER"; do
  printf '%s\n' "$KIVOU_DB_IDENTIFIER" | \
    grep -Eq '^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
done

KIVOU_RESTORE_DB="kivou_card_restore_${KIVOU_FINAL_SHORT}_$(date -u +%Y%m%d%H%M%S)_$$"
case "$KIVOU_RESTORE_DB" in
  (kivou_card_restore_[0-9a-f]*_[0-9]*_[0-9]*) ;;
  (*) exit 64 ;;
esac
printf '%s\n' "$KIVOU_RESTORE_DB" | grep -Eq '^[a-z0-9_]{1,63}$'
printf '%s\n' "$KIVOU_RESTORE_DB" | \
  grep -Eq '^kivou_card_restore_[0-9a-f]{12}_[0-9]{14}_[0-9]{1,8}$'
kivou_restore_db_count() {
  sudo -u postgres psql -X -qAt --dbname=postgres \
    --set=ON_ERROR_STOP=1 --set=db="$KIVOU_RESTORE_DB" <<'SQL'
SELECT count(*) FROM pg_database WHERE datname = :'db';
SQL
}
kivou_restore_table_count() {
  sudo -u postgres psql -X -qAt --dbname="$KIVOU_RESTORE_DB" \
    --set=ON_ERROR_STOP=1 --set=table="$KIVOU_TABLE" <<'SQL'
SELECT count(*) FROM pg_catalog.pg_class WHERE oid = to_regclass(:'table');
SQL
}
KIVOU_RESTORE_DB_COUNT=$(kivou_restore_db_count)
test "$KIVOU_RESTORE_DB_COUNT" = 0
unset KIVOU_RESTORE_DB_COUNT
sudo -u postgres createdb --template=template0 --owner="$KIVOU_LIVE_OWNER" \
  "$KIVOU_RESTORE_DB"
sudo -u kivou /usr/bin/cat "$KIVOU_BACKUP_FILE" | \
  sudo -u postgres pg_restore --exit-on-error --no-owner --no-privileges \
    --dbname="$KIVOU_RESTORE_DB"

test "$(sudo -u postgres psql -At -d "$KIVOU_RESTORE_DB" \
  -c 'SELECT version_num FROM alembic_version')" = "0027_signal_notes"
for KIVOU_TABLE in account target_icp materialized_signal contract_award alembic_version; do
  KIVOU_RESTORE_TABLE_COUNT=$(kivou_restore_table_count)
  test "$KIVOU_RESTORE_TABLE_COUNT" = 1
  unset KIVOU_RESTORE_TABLE_COUNT
  KIVOU_TABLE_COUNT=$(sudo -u postgres psql -At -d "$KIVOU_RESTORE_DB" \
    -c "SELECT count(*) FROM $KIVOU_TABLE")
  printf '%s\n' "$KIVOU_TABLE_COUNT" | grep -Eq '^[0-9]+$'
done
KIVOU_RESTORE_BYTES=$(sudo -u postgres psql -At -d "$KIVOU_RESTORE_DB" \
  -c 'SELECT pg_database_size(current_database())')
printf '%s\n' "$KIVOU_RESTORE_BYTES" | grep -Eq '^[1-9][0-9]*$'

case "$KIVOU_RESTORE_DB" in
  (kivou_card_restore_[0-9a-f]*_[0-9]*_[0-9]*) ;;
  (*) exit 64 ;;
esac
printf '%s\n' "$KIVOU_RESTORE_DB" | grep -Eq '^[a-z0-9_]{1,63}$'
sudo -u postgres dropdb "$KIVOU_RESTORE_DB"
KIVOU_RESTORE_DB_COUNT=$(kivou_restore_db_count)
test "$KIVOU_RESTORE_DB_COUNT" = 0
unset KIVOU_RESTORE_DB_COUNT

printf 'backup_file=%s\nbackup_bytes=%s\nbackup_sha256=%s\ntoc_lines=%s\nrestore_revision=0027_signal_notes\nrestore_size_positive=1\n' \
  "$(basename "$KIVOU_BACKUP_FILE")" "$KIVOU_BACKUP_BYTES" \
  "$KIVOU_BACKUP_SHA" "$KIVOU_BACKUP_TOC_LINES"
REMOTE
~~~

## 4. Préparer la release backend immuable et migrer vers 0028

Créer les deux noms de release à partir du même instant et du même SHA. La
release backend vient exclusivement de `refs/heads/main`; aucune branche de
travail ni le lien actif ne sert de source de build.

~~~bash
test "$(gh api "repos/$KIVOU_REPOSITORY/commits/main" --jq .sha)" = \
  "$KIVOU_FINAL_SHA"
KIVOU_RELEASE_SHA="$KIVOU_FINAL_SHA"
KIVOU_RELEASE_UTC=$(date -u +%Y%m%dT%H%M%SZ)
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
KIVOU_RELEASE_DIR="/srv/kivou/releases/backend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT"

ssh kivou-staging 'bash -s' -- \
  "$KIVOU_FINAL_SHA" "$KIVOU_RELEASE_UTC" "$KIVOU_PREVIOUS_BACKEND" <<'REMOTE'
set -euo pipefail
cd /srv/kivou
KIVOU_FINAL_SHA=$1
KIVOU_RELEASE_UTC=$2
KIVOU_EXPECTED_PREVIOUS=$3
printf '%s\n' "$KIVOU_FINAL_SHA" | grep -Eq '^[0-9a-f]{40}$'
printf '%s\n' "$KIVOU_RELEASE_UTC" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$'
case "$KIVOU_EXPECTED_PREVIOUS" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
test "$(hostname -s)" = "kivou-staging-01"
test "$(readlink -f /srv/kivou/app)" = "$KIVOU_EXPECTED_PREVIOUS"

KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
KIVOU_RELEASE_DIR="/srv/kivou/releases/backend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT"
case "$KIVOU_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
KIVOU_RELEASE_REMOTE=git@github.com:bruppacherrodrigue-art/Kivou.git
KIVOU_DEPLOY_KEY=/srv/kivou/.ssh/github_deploy
KIVOU_KNOWN_HOSTS=/etc/nginx/kivou-github-known-hosts
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_DEPLOY_KEY")" = "kivou:kivou:600"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_KNOWN_HOSTS")" = "root:root:644"
test "$(sudo ssh-keygen -lf "$KIVOU_KNOWN_HOSTS" -E sha256 | awk '{print $2}')" = \
  "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"
KIVOU_GIT_SSH_COMMAND="/usr/bin/ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KIVOU_KNOWN_HOSTS -o GlobalKnownHostsFile=/dev/null -i $KIVOU_DEPLOY_KEY"
kivou_git() {
  sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 /usr/bin/git "$@"
}
KIVOU_REMOTE_MAIN_SHA=$(sudo -u kivou /usr/bin/env -i \
  HOME=/srv/kivou PATH=/usr/bin:/bin \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  GIT_SSH_COMMAND="$KIVOU_GIT_SSH_COMMAND" \
  /usr/bin/git ls-remote --exit-code "$KIVOU_RELEASE_REMOTE" refs/heads/main | \
  awk '$2 == "refs/heads/main" {print $1}')
test "$KIVOU_REMOTE_MAIN_SHA" = "$KIVOU_FINAL_SHA"
sudo test ! -e "$KIVOU_RELEASE_DIR"
sudo test ! -L "$KIVOU_RELEASE_DIR"
sudo install -o kivou -g kivou -m 755 -d "$KIVOU_RELEASE_DIR"
kivou_git init --quiet --initial-branch=main "$KIVOU_RELEASE_DIR"
kivou_git -C "$KIVOU_RELEASE_DIR" remote add origin "$KIVOU_RELEASE_REMOTE"
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  GIT_SSH_COMMAND="$KIVOU_GIT_SSH_COMMAND" \
  /usr/bin/git -C "$KIVOU_RELEASE_DIR" fetch --no-tags origin \
  +refs/heads/main:refs/kivou-rollout/reviewed-main
test "$(kivou_git -C "$KIVOU_RELEASE_DIR" rev-parse refs/kivou-rollout/reviewed-main)" = \
  "$KIVOU_FINAL_SHA"
kivou_git -C "$KIVOU_RELEASE_DIR" checkout --detach "$KIVOU_FINAL_SHA"
test "$(kivou_git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_FINAL_SHA"
test -z "$(kivou_git -C "$KIVOU_RELEASE_DIR" status --porcelain)"
sudo -u kivou /usr/bin/env -i --chdir="$KIVOU_RELEASE_DIR" \
  HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin \
  /usr/local/bin/uv sync --frozen --extra server --extra postgres
test -z "$(kivou_git -C "$KIVOU_RELEASE_DIR" status --porcelain)"
REMOTE
~~~

Vérifier ensuite la paire Alembic et appliquer la migration avec l'API interne
de cette release, avant tout démarrage green. Le script compare aussi les
comptes des tables existantes, la structure additive et l'état de publication
vide.

~~~bash
ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" <<'REMOTE'
set -euo pipefail
cd /srv/kivou
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
case "$KIVOU_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*-$KIVOU_FINAL_SHORT) ;;
  (*) exit 69 ;;
esac
test "$(sudo -u kivou /usr/bin/git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = \
  "$KIVOU_FINAL_SHA"

sudo -u kivou /usr/bin/env -i --chdir="$KIVOU_RELEASE_DIR" \
  HOME=/srv/kivou PATH="$KIVOU_RELEASE_DIR/.venv/bin:/usr/bin:/bin" \
  python - <<'PY'
import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from signals.persistence.database import MIGRATIONS_PATH

config = Config()
config.set_main_option("script_location", str(MIGRATIONS_PATH))
script = ScriptDirectory.from_config(config)
assert script.get_current_head() == "0028_card_presentation"
path = Path("src/signals/persistence/migrations/versions/0028_card_presentation.py")
spec = importlib.util.spec_from_file_location("kivou_0028", path)
assert spec is not None and spec.loader is not None
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
assert migration.revision == "0028_card_presentation"
assert migration.down_revision == "0027_signal_notes"
PY

KIVOU_MIGRATION_UNIT="kivou-card-migrate-$KIVOU_FINAL_SHORT"
sudo systemd-run --quiet --wait --collect --pipe \
  --unit="$KIVOU_MIGRATION_UNIT" --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  --property=ProtectHome=yes \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/python" - <<'PY'
import sqlalchemy as sa

from signals.persistence.database import (
    create_database_engine,
    current_revision,
    migrate_to_latest,
)

engine = create_database_engine()
core_tables = ("account", "target_icp", "materialized_signal", "contract_award")
with engine.connect() as connection:
    before = current_revision(engine)
    assert before == "0027_signal_notes", before
    before_counts = {
        table: connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"'))
        for table in core_tables
    }
migrate_to_latest(engine)
after = current_revision(engine)
assert after == "0028_card_presentation", after
with engine.connect() as connection:
    inspector = sa.inspect(connection)
    assert inspector.get_table_names().count("card_presentation_artifact") == 1
    assert connection.scalar(sa.text("SELECT count(*) FROM card_presentation_artifact")) == 0
    after_counts = {
        table: connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"'))
        for table in core_tables
    }
    assert after_counts == before_counts
    checks = {
        item["name"]
        for item in inspector.get_check_constraints("card_presentation_artifact")
    }
    assert {
        "ck_card_presentation_publishable_pair",
        "ck_card_presentation_fallback_offline",
        "ck_card_presentation_payload_binding",
    } <= checks
    indexes = {
        item["name"]: item
        for item in inspector.get_indexes("card_presentation_artifact")
    }
    assert "ix_card_presentation_tenant_read" in indexes
    assert indexes["uq_card_presentation_active_publication"]["unique"] is True
print(f"migration={before}->{after}")
PY
REMOTE
~~~

Le résultat attendu est uniquement
`migration=0027_signal_notes->0028_card_presentation`. Ne pas exécuter de
downgrade : la migration est additive.

## 5. Publier le backend par le blue/green versionné

La procédure autoritaire est la section **`Reverse proxy public de staging
(#84)`** de [`ops/README.md`](../../ops/README.md). L'étape 4 a déjà exécuté le
premier bloc et créé la release. La commande suivante extrait donc exactement
les blocs bash 2 à 6 de cette section depuis le seul SHA final de `main`, leur
préfixe un bootstrap contrôlé, puis envoie l'ensemble dans **une seule session
SSH et un seul shell distant persistant**. Aucun copier-coller ni nouveau shell
ne doit être intercalé.

~~~bash
set -euo pipefail
KIVOU_BLUE_GREEN_SCRIPT=$(
  sed -n 'p' <<'KIVOU_BLUE_GREEN_BOOTSTRAP'
set -euo pipefail
cd /srv/kivou
KIVOU_RELEASE_DIR=$1
KIVOU_RELEASE_SHA=$2
KIVOU_STAGING_HOST=$3
KIVOU_API_PORT=$4
KIVOU_PREVIOUS_BACKEND=$5
test "$(hostname -s)" = "kivou-staging-01"
case "$KIVOU_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
printf '%s\n' "$KIVOU_RELEASE_SHA" | grep -Eq '^[0-9a-f]{40}$'
test "$KIVOU_STAGING_HOST" = "staging.kivou.eu"
test "$KIVOU_API_PORT" = 8001
case "$KIVOU_PREVIOUS_BACKEND" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
test "$(readlink -f /srv/kivou/app)" = "$KIVOU_PREVIOUS_BACKEND"
sudo test -d "$KIVOU_RELEASE_DIR"
sudo test -d "$KIVOU_PREVIOUS_BACKEND"
kivou_git() {
  sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
    /usr/bin/git "$@"
}
test "$(kivou_git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = \
  "$KIVOU_RELEASE_SHA"
test -z "$(kivou_git -C "$KIVOU_RELEASE_DIR" status --porcelain)"
KIVOU_BLUE_GREEN_BOOTSTRAP
  git show "$KIVOU_FINAL_SHA:ops/README.md" | awk '
    /^## Reverse proxy public de staging \(#84\)$/ {
      section = 1
      next
    }
    section && /^## / { exit 69 }
    section && /^~~~bash$/ {
      block += 1
      emit = block >= 2 && block <= 6
      next
    }
    section && /^~~~$/ {
      if (emit && block == 3) {
        print "test \"$KIVOU_PREVIOUS_RELEASE\" = \"$KIVOU_PREVIOUS_BACKEND\""
      }
      if (emit) print ""
      if (block == 6) {
        complete = 1
        exit
      }
      emit = 0
      next
    }
    section && emit { print }
    END { if (!section || !complete || block != 6) exit 69 }
  '
)
printf '%s\n' "$KIVOU_BLUE_GREEN_SCRIPT" | bash -n
printf '%s\n' "$KIVOU_BLUE_GREEN_SCRIPT" | ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "staging.kivou.eu" 8001 \
  "$KIVOU_PREVIOUS_BACKEND"
unset KIVOU_BLUE_GREEN_SCRIPT
~~~

Cette session réhydrate et valide `KIVOU_RELEASE_DIR`, `KIVOU_RELEASE_SHA`,
`KIVOU_STAGING_HOST`, `KIVOU_API_PORT`, `KIVOU_PREVIOUS_BACKEND` et
`kivou_git` avant toute mutation. Le garde injecté à la fin du troisième bloc
exige que le snapshot autoritaire ait capturé exactement le rollback target de
l'étape 2. Les blocs autoritaires exécutent ensuite, sans réordonnancement, le
candidat nginx et son `nginx -t`, la preuve antérieure, green sur 8001 avec
`kivou-api-green.service 8001`, `green_openapi_status=200` et
`green_me_status=401`, la publication du bundle,
le monitor public, `sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app`, le runtime
normal sur 8000 et la preuve que toutes les lignes de `public-status.codes`
valent `200 401`.

STOP si l'extraction ne trouve pas exactement ces six premiers blocs, si la
topologie versionnée diffère, ou si une validation du bootstrap échoue. La
migration 0028 doit déjà être verte avant la première commande de démarrage
green; cette procédure ne migre rien.

~~~bash
ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "$KIVOU_PREVIOUS_BACKEND" <<'REMOTE'
set -euo pipefail
cd /srv/kivou
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_PREVIOUS_BACKEND=$3
case "$KIVOU_RELEASE_DIR" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
case "$KIVOU_PREVIOUS_BACKEND" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
test "$(readlink -f /srv/kivou/app)" = "$KIVOU_RELEASE_DIR"
test "$(sudo -u kivou /usr/bin/git -C /srv/kivou/app rev-parse HEAD)" = \
  "$KIVOU_FINAL_SHA"
test -z "$(sudo -u kivou /usr/bin/git -C /srv/kivou/app status --porcelain)"
systemctl is-active --quiet kivou-api.service
systemctl is-active --quiet nginx.service
sudo -u kivou /usr/bin/env -i PATH=/usr/bin:/bin \
  "$KIVOU_RELEASE_DIR/ops/bin/kivou-api-readiness.sh" \
  kivou-api.service 8000
test "$(curl --silent --connect-timeout 2 --max-time 5 --output /dev/null \
  --write-out '%{http_code}' http://127.0.0.1:8000/openapi.json)" = 200
test "$(curl --silent --connect-timeout 2 --max-time 5 --output /dev/null \
  --write-out '%{http_code}' http://127.0.0.1:8000/me)" = 401
KIVOU_DEPLOYED_REVISION=$(sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-backend-proof-$$" --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/python" -c \
  'from signals.persistence.database import create_database_engine,current_revision; engine=create_database_engine(); print(current_revision(engine))')
test "$KIVOU_DEPLOYED_REVISION" = "0028_card_presentation"
REMOTE
~~~

## 6. Construire et basculer le frontend du même SHA

Le build est détaché du lien actif et de tout home de connexion. Le Founder
Console n'est ni construit ni copié ici. La release frontend reçoit un marker
appartenant à root et contenant uniquement le SHA final. Le manifest complet
du `dist` est comparé au manifest de la release (le marker étant vérifié à
part), sans symlink, hardlink, fichier spécial ni chemin hors release. Le
preview sert ensuite cette release root-owned exacte; la même preuve est
recalculée immédiatement avant le switch.

~~~bash
ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "$KIVOU_RELEASE_UTC" \
  "$KIVOU_PREVIOUS_FRONTEND" <<'REMOTE'
set -euo pipefail
cd /srv/kivou
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_RELEASE_UTC=$3
KIVOU_PREVIOUS_FRONTEND=$4
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
KIVOU_FRONTEND_BUILD="/srv/kivou/releases/.frontend-build-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT"
KIVOU_FRONTEND_RELEASE="/srv/kivou/releases/frontend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT"
case "$KIVOU_FRONTEND_BUILD" in
  (/srv/kivou/releases/.frontend-build-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
case "$KIVOU_FRONTEND_RELEASE" in
  (/srv/kivou/releases/frontend-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
case "$KIVOU_PREVIOUS_FRONTEND" in
  (/srv/kivou/releases/frontend-*) ;;
  (*) exit 69 ;;
esac
test "$(readlink -f /srv/kivou/frontend)" = "$KIVOU_PREVIOUS_FRONTEND"
test "$(sudo -u kivou git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_FINAL_SHA"
sudo test ! -e "$KIVOU_FRONTEND_BUILD"
sudo test ! -e "$KIVOU_FRONTEND_RELEASE"
sudo test ! -L "$KIVOU_FRONTEND_BUILD"
sudo test ! -L "$KIVOU_FRONTEND_RELEASE"
sudo install -o kivou -g kivou -m 700 -d "$KIVOU_FRONTEND_BUILD"
sudo install -o root -g root -m 755 -d "$KIVOU_FRONTEND_RELEASE"

kivou_frontend_build_owner() {
  sudo -u kivou /usr/bin/env -i \
    --chdir="$KIVOU_FRONTEND_BUILD" \
    HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin "$@"
}

sudo -u kivou /usr/bin/env -i --chdir="$KIVOU_RELEASE_DIR" \
  HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin \
  git -C "$KIVOU_RELEASE_DIR" archive "$KIVOU_FINAL_SHA" frontend | \
  kivou_frontend_build_owner tar -xf -
sudo -u kivou /usr/bin/env -i \
  --chdir="$KIVOU_FRONTEND_BUILD/frontend" \
  HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin npm ci
sudo -u kivou /usr/bin/env -i \
  --chdir="$KIVOU_FRONTEND_BUILD/frontend" \
  HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin npm run build
sudo -u kivou /usr/bin/env -i \
  --chdir="$KIVOU_FRONTEND_BUILD/frontend" \
  HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin npm run typecheck
sudo -u kivou /usr/bin/env -i \
  --chdir="$KIVOU_FRONTEND_BUILD/frontend" \
  HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin npm run lint
kivou_frontend_build_owner test -f frontend/dist/index.html
kivou_frontend_build_owner /bin/sh -eu -c '
  find frontend/dist/assets -type f -print -quit | grep -q .
'

KIVOU_FRONTEND_BUILD_MANIFEST="$KIVOU_FRONTEND_BUILD/build.manifest.sha256"
KIVOU_FRONTEND_RELEASE_MANIFEST="$KIVOU_FRONTEND_BUILD/release.manifest.sha256"
KIVOU_FRONTEND_RELEASE_RECHECK_MANIFEST="$KIVOU_FRONTEND_BUILD/release.recheck.manifest.sha256"
for KIVOU_FRONTEND_MANIFEST in \
  "$KIVOU_FRONTEND_BUILD_MANIFEST" \
  "$KIVOU_FRONTEND_RELEASE_MANIFEST" \
  "$KIVOU_FRONTEND_RELEASE_RECHECK_MANIFEST"; do
  case "$KIVOU_FRONTEND_MANIFEST" in
    ("$KIVOU_FRONTEND_BUILD"/*.manifest.sha256) ;;
    (*) exit 69 ;;
  esac
  kivou_frontend_build_owner test ! -e "$KIVOU_FRONTEND_MANIFEST"
  kivou_frontend_build_owner test ! -L "$KIVOU_FRONTEND_MANIFEST"
done
kivou_frontend_build_owner test \
  "$(kivou_frontend_build_owner readlink -f \
    "$KIVOU_FRONTEND_BUILD/frontend/dist")" = \
  "$KIVOU_FRONTEND_BUILD/frontend/dist"
kivou_frontend_build_owner test ! -L \
  "$KIVOU_FRONTEND_BUILD/frontend/dist"
KIVOU_FRONTEND_BUILD_INVALID=$(kivou_frontend_build_owner find \
  "$KIVOU_FRONTEND_BUILD/frontend/dist" -xdev \
  ! -type d ! -type f -print -quit)
test -z "$KIVOU_FRONTEND_BUILD_INVALID"
unset KIVOU_FRONTEND_BUILD_INVALID
KIVOU_FRONTEND_BUILD_HARDLINKS=$(kivou_frontend_build_owner find \
  "$KIVOU_FRONTEND_BUILD/frontend/dist" -xdev \
  -type f -links +1 -print -quit)
test -z "$KIVOU_FRONTEND_BUILD_HARDLINKS"
unset KIVOU_FRONTEND_BUILD_HARDLINKS
kivou_frontend_build_owner /bin/sh -eu -c '
  cd frontend/dist
  find . -xdev -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum
' | kivou_frontend_build_owner tee \
  "$KIVOU_FRONTEND_BUILD_MANIFEST" >/dev/null
kivou_frontend_build_owner test -s "$KIVOU_FRONTEND_BUILD_MANIFEST"

kivou_frontend_build_owner tar -C frontend/dist -cf - . | \
  sudo tar -C "$KIVOU_FRONTEND_RELEASE" -xf -
printf '%s\n' "$KIVOU_FINAL_SHA" | \
  sudo tee "$KIVOU_FRONTEND_RELEASE/KIVOU_RELEASE_SHA" >/dev/null
sudo chown -R root:root "$KIVOU_FRONTEND_RELEASE"
sudo find "$KIVOU_FRONTEND_RELEASE" -type d -exec chmod 755 {} +
sudo find "$KIVOU_FRONTEND_RELEASE" -type f -exec chmod 444 {} +
test "$(stat -c '%U:%G:%a' "$KIVOU_FRONTEND_RELEASE/KIVOU_RELEASE_SHA")" = \
  "root:root:444"
test "$(cat "$KIVOU_FRONTEND_RELEASE/KIVOU_RELEASE_SHA")" = "$KIVOU_FINAL_SHA"
test $((8#$(stat -c '%a' "$KIVOU_FRONTEND_RELEASE") & 8#022)) -eq 0

kivou_revalidate_frontend_release() {
  KIVOU_REVALIDATION_MANIFEST=$1
  case "$KIVOU_REVALIDATION_MANIFEST" in
    ("$KIVOU_FRONTEND_BUILD"/*.manifest.sha256) ;;
    (*) return 69 ;;
  esac
  case "$KIVOU_FRONTEND_RELEASE" in
    (/srv/kivou/releases/frontend-*-$KIVOU_RELEASE_SHORT) ;;
    (*) return 69 ;;
  esac
  test "$(sudo readlink -f "$KIVOU_FRONTEND_RELEASE")" = \
    "$KIVOU_FRONTEND_RELEASE"
  test ! -L "$KIVOU_FRONTEND_RELEASE"
  KIVOU_RELEASE_INVALID=$(sudo find "$KIVOU_FRONTEND_RELEASE" -xdev \
    ! -type d ! -type f -print -quit)
  test -z "$KIVOU_RELEASE_INVALID"
  unset KIVOU_RELEASE_INVALID
  KIVOU_RELEASE_HARDLINKS=$(sudo find "$KIVOU_FRONTEND_RELEASE" -xdev \
    -type f -links +1 -print -quit)
  test -z "$KIVOU_RELEASE_HARDLINKS"
  unset KIVOU_RELEASE_HARDLINKS
  KIVOU_RELEASE_WRONG_OWNER=$(sudo find "$KIVOU_FRONTEND_RELEASE" -xdev \
    \( ! -user root -o ! -group root \) -print -quit)
  test -z "$KIVOU_RELEASE_WRONG_OWNER"
  unset KIVOU_RELEASE_WRONG_OWNER
  KIVOU_RELEASE_WRONG_DIR_MODE=$(sudo find "$KIVOU_FRONTEND_RELEASE" -xdev \
    -type d ! -perm 0755 -print -quit)
  test -z "$KIVOU_RELEASE_WRONG_DIR_MODE"
  unset KIVOU_RELEASE_WRONG_DIR_MODE
  KIVOU_RELEASE_WRONG_FILE_MODE=$(sudo find "$KIVOU_FRONTEND_RELEASE" -xdev \
    -type f ! -perm 0444 -print -quit)
  test -z "$KIVOU_RELEASE_WRONG_FILE_MODE"
  unset KIVOU_RELEASE_WRONG_FILE_MODE
  test "$(cat "$KIVOU_FRONTEND_RELEASE/KIVOU_RELEASE_SHA")" = \
    "$KIVOU_FINAL_SHA"
  sudo /bin/sh -eu -c '
    cd "$1"
    find . -xdev -type f ! -name KIVOU_RELEASE_SHA -print0 |
      LC_ALL=C sort -z | xargs -0 -r sha256sum
  ' sh "$KIVOU_FRONTEND_RELEASE" | \
    kivou_frontend_build_owner tee \
      "$KIVOU_REVALIDATION_MANIFEST" >/dev/null
  kivou_frontend_build_owner test -s "$KIVOU_REVALIDATION_MANIFEST"
  kivou_frontend_build_owner cmp --silent \
    "$KIVOU_FRONTEND_BUILD_MANIFEST" \
    "$KIVOU_REVALIDATION_MANIFEST"
  test "$(kivou_frontend_build_owner sha256sum \
    "$KIVOU_REVALIDATION_MANIFEST" | awk '{print $1}')" = \
    "$KIVOU_EXPECTED_FRONTEND_MANIFEST_SHA"
}

KIVOU_EXPECTED_FRONTEND_MANIFEST_SHA=$(kivou_frontend_build_owner sha256sum \
  "$KIVOU_FRONTEND_BUILD_MANIFEST" | awk '{print $1}')
printf '%s\n' "$KIVOU_EXPECTED_FRONTEND_MANIFEST_SHA" | \
  grep -Eq '^[0-9a-f]{64}$'
kivou_revalidate_frontend_release "$KIVOU_FRONTEND_RELEASE_MANIFEST"

KIVOU_FRONTEND_PREVIEW_PORT=4174
KIVOU_FRONTEND_PREVIEW_UNIT="kivou-frontend-preview-$KIVOU_RELEASE_SHORT"
case "$KIVOU_FRONTEND_PREVIEW_UNIT" in
  (kivou-frontend-preview-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  (*) exit 69 ;;
esac
test "$KIVOU_FRONTEND_PREVIEW_PORT" = 4174
test "$(systemctl show "$KIVOU_FRONTEND_PREVIEW_UNIT.service" \
  --property=LoadState --value)" = "not-found"
test -z "$(sudo ss --no-header --listening --tcp \
  "sport = :$KIVOU_FRONTEND_PREVIEW_PORT")"
KIVOU_FRONTEND_PREVIEW_STARTED=0
kivou_stop_frontend_preview() {
  case "$KIVOU_FRONTEND_PREVIEW_UNIT" in
    (kivou-frontend-preview-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
    (*) return 69 ;;
  esac
  if test "$KIVOU_FRONTEND_PREVIEW_STARTED" = 1; then
    sudo systemctl stop "$KIVOU_FRONTEND_PREVIEW_UNIT.service"
  fi
}
trap kivou_stop_frontend_preview EXIT
KIVOU_FRONTEND_PREVIEW_STARTED=1
sudo systemd-run --quiet --collect \
  --unit="$KIVOU_FRONTEND_PREVIEW_UNIT" --property=Type=exec \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_FRONTEND_RELEASE" \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  -- /usr/bin/env -i HOME=/srv/kivou PATH=/usr/local/bin:/usr/bin:/bin \
  "$KIVOU_FRONTEND_BUILD/frontend/node_modules/.bin/vite" preview \
  --outDir "$KIVOU_FRONTEND_RELEASE" \
  --host 127.0.0.1 --port "$KIVOU_FRONTEND_PREVIEW_PORT" --strictPort
KIVOU_FRONTEND_PREVIEW_STATUS=000
for KIVOU_PREVIEW_ATTEMPT in 1 2 3 4 5; do
  systemctl is-active --quiet "$KIVOU_FRONTEND_PREVIEW_UNIT.service"
  KIVOU_FRONTEND_PREVIEW_STATUS=$(curl --silent --show-error \
    --connect-timeout 1 --max-time 2 --output /dev/null \
    --write-out '%{http_code}' \
    "http://127.0.0.1:$KIVOU_FRONTEND_PREVIEW_PORT/") || true
  test "$KIVOU_FRONTEND_PREVIEW_STATUS" = 200 && break
  sleep 1
done
test "$KIVOU_FRONTEND_PREVIEW_STATUS" = 200
for KIVOU_PATH in / /app/dashboard /app/companies /app/signals; do
  test "$(curl --silent --show-error --connect-timeout 1 --max-time 2 \
    --output /dev/null --write-out '%{http_code}' \
    "http://127.0.0.1:$KIVOU_FRONTEND_PREVIEW_PORT$KIVOU_PATH")" = 200
done
mapfile -t KIVOU_CANDIDATE_ASSET_PATHS < <(
  grep -Eo '(src|href)="/[^"]+"' "$KIVOU_FRONTEND_RELEASE/index.html" |
    sed -E 's/^(src|href)="([^"]+)"$/\2/' | sort -u
)
test "${#KIVOU_CANDIDATE_ASSET_PATHS[@]}" -gt 0
for KIVOU_ASSET_PATH in "${KIVOU_CANDIDATE_ASSET_PATHS[@]}"; do
  case "$KIVOU_ASSET_PATH" in
    (/assets/*|/reference/*) ;;
    (*) exit 69 ;;
  esac
  test -f "$KIVOU_FRONTEND_RELEASE$KIVOU_ASSET_PATH"
  test "$(curl --silent --show-error --connect-timeout 1 --max-time 2 \
    --output /dev/null --write-out '%{http_code}' \
    "http://127.0.0.1:$KIVOU_FRONTEND_PREVIEW_PORT$KIVOU_ASSET_PATH")" = 200
done
kivou_stop_frontend_preview
KIVOU_FRONTEND_PREVIEW_STARTED=0
trap - EXIT

kivou_frontend_http_smoke() {
  KIVOU_SMOKE_RELEASE=$1
  case "$KIVOU_SMOKE_RELEASE" in
    (/srv/kivou/releases/frontend-*) ;;
    (*) return 69 ;;
  esac
  mapfile -t KIVOU_SMOKE_ASSET_PATHS < <(
    grep -Eo '(src|href)="/[^"]+"' "$KIVOU_SMOKE_RELEASE/index.html" |
      sed -E 's/^(src|href)="([^"]+)"$/\2/' | sort -u
  )
  test "${#KIVOU_SMOKE_ASSET_PATHS[@]}" -gt 0 || return 1
  for KIVOU_PATH in / /app/dashboard /app/companies /app/signals; do
    test "$(curl --silent --show-error --connect-timeout 2 --max-time 5 \
      --output /dev/null --write-out '%{http_code}' \
      --resolve staging.kivou.eu:443:127.0.0.1 \
      "https://staging.kivou.eu$KIVOU_PATH")" = 200 || return 1
  done
  for KIVOU_SMOKE_ASSET_PATH in "${KIVOU_SMOKE_ASSET_PATHS[@]}"; do
    case "$KIVOU_SMOKE_ASSET_PATH" in
      (/assets/*|/reference/*) ;;
      (*) return 69 ;;
    esac
    test -f "$KIVOU_SMOKE_RELEASE$KIVOU_SMOKE_ASSET_PATH" || return 1
    test "$(curl --silent --show-error --connect-timeout 2 --max-time 5 \
      --output /dev/null --write-out '%{http_code}' \
      --resolve staging.kivou.eu:443:127.0.0.1 \
      "https://staging.kivou.eu$KIVOU_SMOKE_ASSET_PATH")" = 200 || return 1
  done
}

KIVOU_FRONTEND_SWITCH_DIR=$(sudo mktemp -d \
  /srv/kivou/.kivou-frontend-next.XXXXXX)
sudo chmod 700 "$KIVOU_FRONTEND_SWITCH_DIR"
KIVOU_FRONTEND_SWITCH_DIR_REAL=$(sudo readlink -f "$KIVOU_FRONTEND_SWITCH_DIR")
test "$KIVOU_FRONTEND_SWITCH_DIR_REAL" = "$KIVOU_FRONTEND_SWITCH_DIR"
case "$KIVOU_FRONTEND_SWITCH_DIR_REAL" in
  (/srv/kivou/.kivou-frontend-next.*) ;;
  (*) exit 69 ;;
esac
kivou_cleanup_frontend_switch_dir() {
  case "$KIVOU_FRONTEND_SWITCH_DIR_REAL" in
    (/srv/kivou/.kivou-frontend-next.*) ;;
    (*) return 69 ;;
  esac
  sudo find "$KIVOU_FRONTEND_SWITCH_DIR_REAL" -depth -mindepth 1 -delete
  case "$KIVOU_FRONTEND_SWITCH_DIR_REAL" in
    (/srv/kivou/.kivou-frontend-next.*) ;;
    (*) return 69 ;;
  esac
  sudo rmdir "$KIVOU_FRONTEND_SWITCH_DIR_REAL"
}
trap kivou_cleanup_frontend_switch_dir EXIT
KIVOU_FRONTEND_NEXT="$KIVOU_FRONTEND_SWITCH_DIR/frontend.next"
KIVOU_FRONTEND_ROLLBACK="$KIVOU_FRONTEND_SWITCH_DIR/frontend.rollback"
sudo ln -s "$KIVOU_FRONTEND_RELEASE" "$KIVOU_FRONTEND_NEXT"
sudo ln -s "$KIVOU_PREVIOUS_FRONTEND" "$KIVOU_FRONTEND_ROLLBACK"
test "$(sudo readlink -f "$KIVOU_FRONTEND_NEXT")" = \
  "$KIVOU_FRONTEND_RELEASE"
test "$(sudo readlink -f "$KIVOU_FRONTEND_ROLLBACK")" = \
  "$KIVOU_PREVIOUS_FRONTEND"
kivou_revalidate_frontend_release \
  "$KIVOU_FRONTEND_RELEASE_RECHECK_MANIFEST"
test "$(readlink -f /srv/kivou/frontend)" = "$KIVOU_PREVIOUS_FRONTEND"
sudo mv -Tf "$KIVOU_FRONTEND_NEXT" /srv/kivou/frontend
if ! kivou_frontend_http_smoke "$KIVOU_FRONTEND_RELEASE"; then
  sudo mv -Tf "$KIVOU_FRONTEND_ROLLBACK" /srv/kivou/frontend
  test "$(readlink -f /srv/kivou/frontend)" = "$KIVOU_PREVIOUS_FRONTEND"
  kivou_frontend_http_smoke "$KIVOU_PREVIOUS_FRONTEND"
  exit 1
fi
test "$(readlink -f /srv/kivou/frontend)" = "$KIVOU_FRONTEND_RELEASE"
test "$(cat /srv/kivou/frontend/KIVOU_RELEASE_SHA)" = "$KIVOU_FINAL_SHA"
kivou_cleanup_frontend_switch_dir
trap - EXIT

KIVOU_FRONTEND_BUILD_REAL=$(kivou_frontend_build_owner readlink -f \
  "$KIVOU_FRONTEND_BUILD")
case "$KIVOU_FRONTEND_BUILD_REAL" in
  ("$KIVOU_FRONTEND_BUILD") ;;
  (*) exit 69 ;;
esac
kivou_frontend_build_owner find "$KIVOU_FRONTEND_BUILD_REAL" \
  -depth -mindepth 1 -delete
case "$KIVOU_FRONTEND_BUILD_REAL" in
  ("$KIVOU_FRONTEND_BUILD") ;;
  (*) exit 69 ;;
esac
sudo rmdir "$KIVOU_FRONTEND_BUILD_REAL"
REMOTE
~~~

Le rollback frontend immédiat est donc intégré avant de considérer le switch
réussi. Les deux releases frontend immuables sont conservées.

## 7. Exiger le compte QA puis backfiller FR et EN séparément

Le fichier protégé `/etc/kivou/card-presentation-qa.env` est une approbation
préalable du propriétaire. Cette procédure **ne crée pas ce fichier** et ne déduit jamais le compte depuis un nom, un domaine, une activité ou une donnée
client. Il doit contenir exactement une affectation
`KIVOU_CARD_QA_ACCOUNT_ID`, être `root:kivou:640` et ne pas être un lien.

Avant mutation, le navigateur QA protégé doit retourner dans `/me` le même
`account_id` que ce fichier et le feed doit montrer au moins un signal réellement
déverrouillé. Comparer uniquement une empreinte SHA-256 locale; ne journaliser
ni l'identifiant brut, ni l'e-mail, ni les contenus du signal. Si cette preuve
ne peut pas être faite, STOP.

~~~bash
KIVOU_BACKFILL_AS_OF=$(date -u +%F)
printf '%s\n' "$KIVOU_BACKFILL_AS_OF" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
KIVOU_QA_SCOPE_SUMMARY=$(ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "$KIVOU_BACKFILL_AS_OF" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_BACKFILL_AS_OF=$3
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
KIVOU_QA_ENV=/etc/kivou/card-presentation-qa.env
test -f "$KIVOU_QA_ENV"
test ! -L "$KIVOU_QA_ENV"
test "$(stat -c '%U:%G:%a' "$KIVOU_QA_ENV")" = "root:kivou:640"
test "$(sudo awk 'NF && $1 !~ /^#/ {count++} END {print count+0}' \
  "$KIVOU_QA_ENV")" = 1
sudo grep -Eq \
  '^KIVOU_CARD_QA_ACCOUNT_ID=[0-9A-Za-z][0-9A-Za-z_-]{0,63}$' \
  "$KIVOU_QA_ENV"
test "$(sudo awk -F= 'NF && $1 !~ /^#/ {print $1}' "$KIVOU_QA_ENV")" = \
  KIVOU_CARD_QA_ACCOUNT_ID

sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-qa-scope-$KIVOU_FINAL_SHORT" --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile="$KIVOU_QA_ENV" \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/python" - <<'PY'
import hashlib
import os
import sys

import sqlalchemy as sa

from signals.persistence.database import create_database_engine


def main() -> None:
    account_id = os.environ["KIVOU_CARD_QA_ACCOUNT_ID"]
    engine = create_database_engine()
    with engine.connect() as connection:
        account_count = connection.scalar(sa.text(
            "SELECT count(*) FROM account WHERE account_id=:account_id"
        ), {"account_id": account_id})
        active_users = connection.scalar(sa.text(
            "SELECT count(*) FROM auth_user "
            "WHERE account_id=:account_id AND is_active"
        ), {"account_id": account_id})
        active_icps = connection.scalar(sa.text(
            "SELECT count(*) FROM target_icp WHERE account_id=:account_id "
            "AND status='active' AND plan_limit_code IS NULL"
        ), {"account_id": account_id})
        current_signals = connection.scalar(sa.text(
            "SELECT count(*) FROM materialized_signal AS signal "
            "JOIN target_icp AS icp "
            "ON icp.target_icp_id=signal.target_icp_id "
            "WHERE icp.account_id=:account_id AND icp.status='active' "
            "AND icp.plan_limit_code IS NULL "
            "AND signal.invalidated_at IS NULL "
            "AND signal.target_icp_revision=icp.matching_revision"
        ), {"account_id": account_id})
    assert account_count == 1
    assert active_users >= 1
    assert active_icps >= 1
    assert current_signals >= 1
    fingerprint = hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:16]
    print(
        f"qa_scope_ok fingerprint={fingerprint} active_users={active_users} "
        f"active_icps={active_icps} current_signals={current_signals}"
    )


try:
    main()
except Exception:
    print("qa_scope_failed", file=sys.stderr)
    raise SystemExit(1) from None
PY
REMOTE
)
printf '%s\n' "$KIVOU_QA_SCOPE_SUMMARY" | grep -Eq \
  '^qa_scope_ok fingerprint=[0-9a-f]{16} active_users=[1-9][0-9]* active_icps=[1-9][0-9]* current_signals=[1-9][0-9]*$'
KIVOU_QA_DB_FINGERPRINT=$(printf '%s\n' "$KIVOU_QA_SCOPE_SUMMARY" | \
  sed -E 's/^qa_scope_ok fingerprint=([0-9a-f]{16}) .*$/\1/')
unset KIVOU_QA_SCOPE_SUMMARY
printf '%s\n' "$KIVOU_QA_DB_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'

: "${KIVOU_QA_STORAGE_STATE:?STOP: storage state QA protégé non fourni}"
printf '%s\n' "$KIVOU_QA_STORAGE_STATE" | \
  grep -Eq '^/[A-Za-z0-9._/-]+$'
test -f "$KIVOU_QA_STORAGE_STATE"
test ! -L "$KIVOU_QA_STORAGE_STATE"
KIVOU_QA_STORAGE_STATE_REAL=$(readlink -f "$KIVOU_QA_STORAGE_STATE")
test "$KIVOU_QA_STORAGE_STATE_REAL" = "$KIVOU_QA_STORAGE_STATE"
test "$(stat -c '%U:%a' "$KIVOU_QA_STORAGE_STATE")" = "$(id -un):600"
test -r "$KIVOU_QA_STORAGE_STATE"
KIVOU_OPERATOR_ROOT=$(git rev-parse --show-toplevel)
case "$KIVOU_QA_STORAGE_STATE_REAL" in
  ("$KIVOU_OPERATOR_ROOT"/*) exit 69 ;;
  (*) ;;
esac
(
  cd frontend
  npm ci
  npx playwright install chromium
  KIVOU_QA_STORAGE_STATE="$KIVOU_QA_STORAGE_STATE_REAL" \
  KIVOU_QA_DB_FINGERPRINT="$KIVOU_QA_DB_FINGERPRINT" \
  KIVOU_BACKFILL_AS_OF="$KIVOU_BACKFILL_AS_OF" \
  KIVOU_QA_ORIGIN=https://staging.kivou.eu node <<'JS'
async function run() {
  const { chromium } = require('playwright')
  const origin = process.env.KIVOU_QA_ORIGIN
  const asOf = process.env.KIVOU_BACKFILL_AS_OF
  const expectedFingerprint = process.env.KIVOU_QA_DB_FINGERPRINT
  const storageState = process.env.KIVOU_QA_STORAGE_STATE
  if (!origin || !asOf || !expectedFingerprint || !storageState) throw new Error()
  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext({ storageState })
    const page = await context.newPage()
    await page.goto(`${origin}/app/signals`, { waitUntil: 'networkidle' })
    const verified = await page.evaluate(async ({ asOf, expectedFingerprint }) => {
      const meResponse = await fetch('/me', { credentials: 'same-origin' })
      if (meResponse.status !== 200) throw new Error()
      const me = await meResponse.json()
      if (typeof me.account_id !== 'string' || me.account_id.length === 0) {
        throw new Error()
      }
      const bytes = new TextEncoder().encode(me.account_id)
      const digest = await crypto.subtle.digest('SHA-256', bytes)
      const fingerprint = Array.from(new Uint8Array(digest))
        .map((value) => value.toString(16).padStart(2, '0'))
        .join('')
        .slice(0, 16)
      if (fingerprint !== expectedFingerprint) throw new Error()
      const feedResponse = await fetch(
        `/signals?as_of=${encodeURIComponent(asOf)}&limit=50&offset=0`,
        { credentials: 'same-origin' },
      )
      if (feedResponse.status !== 200) throw new Error()
      const feed = await feedResponse.json()
      if (feed.read_at !== asOf || !Array.isArray(feed.items)) throw new Error()
      if (!feed.items.some((item) => item && item.locked === false)) {
        throw new Error()
      }
      return true
    }, { asOf, expectedFingerprint })
    if (verified !== true) throw new Error()
    await context.close()
  } finally {
    await browser.close()
  }
}

run()
  .then(() => console.log("qa_browser_gate_ok"))
  .catch(() => {
    console.error("qa_browser_gate_failed")
    process.exitCode = 1
  })
JS
)

ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "$KIVOU_BACKFILL_AS_OF" \
  "$KIVOU_QA_DB_FINGERPRINT" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_BACKFILL_AS_OF=$3
KIVOU_QA_DB_FINGERPRINT=$4
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
KIVOU_QA_ENV=/etc/kivou/card-presentation-qa.env
printf '%s\n' "$KIVOU_QA_DB_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'

kivou_revalidate_qa_binding() {
  test -f "$KIVOU_QA_ENV"
  test ! -L "$KIVOU_QA_ENV"
  test "$(stat -c '%U:%G:%a' "$KIVOU_QA_ENV")" = "root:kivou:640"
  test "$(sudo awk 'NF && $1 !~ /^#/ {count++} END {print count+0}' \
    "$KIVOU_QA_ENV")" = 1
  sudo grep -Eq \
    '^KIVOU_CARD_QA_ACCOUNT_ID=[0-9A-Za-z][0-9A-Za-z_-]{0,63}$' \
    "$KIVOU_QA_ENV"
  test "$(sudo awk -F= 'NF && $1 !~ /^#/ {print $1}' \
    "$KIVOU_QA_ENV")" = KIVOU_CARD_QA_ACCOUNT_ID
  KIVOU_QA_BOUND_ACCOUNT=$(sudo awk -F= \
    '$1 == "KIVOU_CARD_QA_ACCOUNT_ID" {print $2}' "$KIVOU_QA_ENV")
  KIVOU_QA_BOUND_FINGERPRINT=$(printf '%s' "$KIVOU_QA_BOUND_ACCOUNT" | \
    sha256sum | cut -c1-16)
  unset KIVOU_QA_BOUND_ACCOUNT
  test "$KIVOU_QA_BOUND_FINGERPRINT" = "$KIVOU_QA_DB_FINGERPRINT"
  unset KIVOU_QA_BOUND_FINGERPRINT
}

kivou_validate_backfill_summary() {
  printf '%s\n' "$1" | awk '
    BEGIN { ok=0 }
    /^scanned=[0-9]+ published=[0-9]+ unchanged=[0-9]+ failed=0 next_offset=(none|[0-9]+) scan_truncated=0$/ {
      split($1, scanned, "="); split($2, published, "="); split($3, unchanged, "=")
      if (scanned[2] <= 50 && published[2] <= 50 && unchanged[2] <= 50 &&
          published[2] + unchanged[2] <= scanned[2]) ok=1
    }
    END { exit !ok }
  '
}

kivou_revalidate_qa_binding
KIVOU_FR_SUMMARY=$(sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-backfill-fr-$KIVOU_FINAL_SHORT" --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile="$KIVOU_QA_ENV" \
  --setenv=HOME=/srv/kivou \
  --setenv="PATH=$KIVOU_RELEASE_DIR/.venv/bin:/usr/bin:/bin" \
  --setenv="KIVOU_BACKFILL_AS_OF=$KIVOU_BACKFILL_AS_OF" \
  --setenv="KIVOU_QA_DB_FINGERPRINT=$KIVOU_QA_DB_FINGERPRINT" \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/python" - <<'PY'
import grp
import hashlib
import hmac
import os
import re
import stat
import sys

from signals.card_intelligence.cli import main as cli_main


def approved_account_id() -> str:
    qa_env = "/etc/kivou/card-presentation-qa.env"
    file_descriptor = os.open(
        qa_env, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    )
    try:
        qa_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(qa_stat.st_mode)
            or stat.S_IMODE(qa_stat.st_mode) != 0o640
            or qa_stat.st_uid != 0
            or grp.getgrgid(qa_stat.st_gid).gr_name != "kivou"
        ):
            raise ValueError()
        handle = os.fdopen(file_descriptor, "r", encoding="utf-8")
        file_descriptor = -1
        with handle:
            contents = handle.read(257)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    if len(contents) > 256:
        raise ValueError()
    assignments = [
        line for line in contents.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if len(assignments) != 1:
        raise ValueError()
    key, separator, file_account_id = assignments[0].partition("=")
    if (
        separator != "="
        or key != "KIVOU_CARD_QA_ACCOUNT_ID"
        or re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z_-]{0,63}", file_account_id)
        is None
    ):
        raise ValueError()
    environment_account_id = os.environ["KIVOU_CARD_QA_ACCOUNT_ID"]
    if not hmac.compare_digest(file_account_id, environment_account_id):
        raise ValueError()
    return file_account_id


def main() -> None:
    file_account_id = approved_account_id()
    expected = os.environ["KIVOU_QA_DB_FINGERPRINT"]
    if re.fullmatch(r"[0-9a-f]{16}", expected) is None:
        raise ValueError()
    actual = hashlib.sha256(file_account_id.encode("utf-8")).hexdigest()[:16]
    if not hmac.compare_digest(actual, expected):
        raise ValueError()
    exit_code = cli_main([
        "backfill-fallbacks",
        "--account-id", file_account_id,
        "--as-of", os.environ["KIVOU_BACKFILL_AS_OF"],
        "--language", "fr",
        "--limit", "50",
        "--offset", "0",
    ])
    if exit_code != 0:
        raise ValueError()


try:
    main()
except Exception:
    print("qa_backfill_failed", file=sys.stderr)
    raise SystemExit(1) from None
PY
)
kivou_validate_backfill_summary "$KIVOU_FR_SUMMARY"
printf 'fr_%s\n' "$KIVOU_FR_SUMMARY"

kivou_revalidate_qa_binding
KIVOU_EN_SUMMARY=$(sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-backfill-en-$KIVOU_FINAL_SHORT" --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile="$KIVOU_QA_ENV" \
  --setenv=HOME=/srv/kivou \
  --setenv="PATH=$KIVOU_RELEASE_DIR/.venv/bin:/usr/bin:/bin" \
  --setenv="KIVOU_BACKFILL_AS_OF=$KIVOU_BACKFILL_AS_OF" \
  --setenv="KIVOU_QA_DB_FINGERPRINT=$KIVOU_QA_DB_FINGERPRINT" \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/python" - <<'PY'
import grp
import hashlib
import hmac
import os
import re
import stat
import sys

from signals.card_intelligence.cli import main as cli_main


def approved_account_id() -> str:
    qa_env = "/etc/kivou/card-presentation-qa.env"
    file_descriptor = os.open(
        qa_env, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    )
    try:
        qa_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(qa_stat.st_mode)
            or stat.S_IMODE(qa_stat.st_mode) != 0o640
            or qa_stat.st_uid != 0
            or grp.getgrgid(qa_stat.st_gid).gr_name != "kivou"
        ):
            raise ValueError()
        handle = os.fdopen(file_descriptor, "r", encoding="utf-8")
        file_descriptor = -1
        with handle:
            contents = handle.read(257)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    if len(contents) > 256:
        raise ValueError()
    assignments = [
        line for line in contents.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if len(assignments) != 1:
        raise ValueError()
    key, separator, file_account_id = assignments[0].partition("=")
    if (
        separator != "="
        or key != "KIVOU_CARD_QA_ACCOUNT_ID"
        or re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z_-]{0,63}", file_account_id)
        is None
    ):
        raise ValueError()
    environment_account_id = os.environ["KIVOU_CARD_QA_ACCOUNT_ID"]
    if not hmac.compare_digest(file_account_id, environment_account_id):
        raise ValueError()
    return file_account_id


def main() -> None:
    file_account_id = approved_account_id()
    expected = os.environ["KIVOU_QA_DB_FINGERPRINT"]
    if re.fullmatch(r"[0-9a-f]{16}", expected) is None:
        raise ValueError()
    actual = hashlib.sha256(file_account_id.encode("utf-8")).hexdigest()[:16]
    if not hmac.compare_digest(actual, expected):
        raise ValueError()
    exit_code = cli_main([
        "backfill-fallbacks",
        "--account-id", file_account_id,
        "--as-of", os.environ["KIVOU_BACKFILL_AS_OF"],
        "--language", "en",
        "--limit", "50",
        "--offset", "0",
    ])
    if exit_code != 0:
        raise ValueError()


try:
    main()
except Exception:
    print("qa_backfill_failed", file=sys.stderr)
    raise SystemExit(1) from None
PY
)
kivou_validate_backfill_summary "$KIVOU_EN_SUMMARY"
printf 'en_%s\n' "$KIVOU_EN_SUMMARY"
REMOTE
~~~

Ce sont deux unités, processus et transactions distincts, FR puis EN. Exiger
`failed=0` et `scan_truncated=0`; **ne pas suivre `next_offset`** même s'il est
présent. Dans chaque unité, le fichier d'approbation est rouvert avec
`O_NOFOLLOW`, validé par `fstat` comme fichier régulier `root:kivou:640`, puis
son identifiant est comparé en temps constant à l'EnvironmentFile et à
l'empreinte DB avant l'appel CLI. Un remplacement du fichier ne peut donc pas
rediriger la mutation vers un autre compte. Une page explicite de 50 est
l'unique portée autorisée par langue : `--language fr --limit 50 --offset 0`,
puis `--language en --limit 50 --offset 0` dans l'unité suivante.

Vérifier ensuite en lecture seule, toujours au seul compte approuvé : statuts
`FALLBACK`, variantes `FACTUAL_FALLBACK`, preuve non vide sur chaque claim,
aucun `PASS/FULL`, aucun doublon actif et payload strictement décodable. Les
prédicats attendus sont `provider IS NULL`, `model_id IS NULL`,
`prompt_version IS NULL`, `qa_provider IS NULL` et `qa_model_id IS NULL`.

Un historique n'est jamais fabriqué pour ce smoke : aucune révision ICP/source
n'est modifiée et aucune publication supplémentaire n'est autorisée au-delà des
deux backfills bornés ci-dessus. La preuve factuelle courante est obligatoire
et indépendante. La même lecture découvre seulement un état historique opaque
`available|absent`; un éventuel artefact doit être légitimement supersédé,
compatible avec la révision courante et la locale du compte. Sur une table 0028
fraîche, `absent` est normal. Il ne bloque ni les preuves factuelles courantes,
ni les six captures, ni l'audit journal, ni les probes finales. La décision
STOP historique est différée après toutes ces preuves. Les identifiants ne sont
transportés vers le navigateur que pour l'état `available`, sans être affichés
ou consignés.

~~~bash
KIVOU_QA_FACTUAL_PROOF=$(ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" \
  "$KIVOU_QA_DB_FINGERPRINT" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_QA_DB_FINGERPRINT=$3
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
printf '%s\n' "$KIVOU_QA_DB_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'
sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-factual-proof-$KIVOU_FINAL_SHORT" --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile=/etc/kivou/card-presentation-qa.env \
  --setenv="KIVOU_QA_DB_FINGERPRINT=$KIVOU_QA_DB_FINGERPRINT" \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/python" - <<'PY'
import hashlib
import hmac
import json
import os
import re
import sys

import sqlalchemy as sa

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    PresentationVariant,
)
from signals.persistence.database import create_database_engine


def main() -> None:
    account_id = os.environ["KIVOU_CARD_QA_ACCOUNT_ID"]
    expected = os.environ["KIVOU_QA_DB_FINGERPRINT"]
    actual = hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:16]
    assert re.fullmatch(r"[0-9a-f]{16}", expected)
    assert hmac.compare_digest(actual, expected)
    engine = create_database_engine()
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        rows = connection.execute(sa.text(
            "SELECT language, qa_status, payload_variant, payload, provider, "
            "model_id, prompt_version, qa_provider, qa_model_id "
            "FROM card_presentation_artifact "
            "WHERE account_id=:account_id AND published_at IS NOT NULL"
        ), {"account_id": account_id}).mappings().all()
        foreign_rows = connection.scalar(sa.text(
            "SELECT count(*) FROM card_presentation_artifact "
            "WHERE account_id<>:account_id"
        ), {"account_id": account_id})
        duplicates = connection.scalar(sa.text(
            "SELECT count(*) FROM (SELECT account_id,signal_key,target_icp_id,"
            "artifact_kind,language FROM card_presentation_artifact "
            "WHERE published_at IS NOT NULL AND superseded_at IS NULL "
            "GROUP BY 1,2,3,4,5 HAVING count(*)>1) AS duplicate"
        ))
        historical = connection.execute(sa.text(
            "SELECT old.signal_key, old.artifact_id, old.version "
            "FROM card_presentation_artifact AS old "
            "JOIN account AS qa ON qa.account_id=old.account_id "
            "JOIN target_icp AS icp "
            "ON icp.target_icp_id=old.target_icp_id "
            "AND icp.account_id=old.account_id "
            "JOIN materialized_signal AS signal "
            "ON signal.signal_key=old.signal_key "
            "AND signal.target_icp_id=old.target_icp_id "
            "JOIN card_presentation_artifact AS current "
            "ON current.account_id=old.account_id "
            "AND current.signal_key=old.signal_key "
            "AND current.target_icp_id=old.target_icp_id "
            "AND current.artifact_kind=old.artifact_kind "
            "AND current.language=old.language "
            "AND current.signal_revision=old.signal_revision "
            "AND current.target_icp_revision=old.target_icp_revision "
            "AND current.input_fingerprint=old.input_fingerprint "
            "WHERE old.account_id=:account_id "
            "AND old.artifact_kind='CARD_PRESENTATION' "
            "AND old.language=CASE WHEN qa.locale IN ('fr','en') "
            "THEN qa.locale ELSE 'fr' END "
            "AND old.published_at IS NOT NULL "
            "AND old.superseded_at IS NOT NULL "
            "AND old.qa_status='FALLBACK' "
            "AND old.payload_variant='FACTUAL_FALLBACK' "
            "AND current.published_at IS NOT NULL "
            "AND current.superseded_at IS NULL "
            "AND current.version>old.version "
            "AND signal.invalidated_at IS NULL "
            "AND signal.revision=old.signal_revision "
            "AND signal.target_icp_revision=old.target_icp_revision "
            "AND icp.status='active' AND icp.plan_limit_code IS NULL "
            "AND icp.matching_revision=old.target_icp_revision "
            "ORDER BY old.signal_key, old.version, old.artifact_id LIMIT 1"
        ), {"account_id": account_id}).mappings().one_or_none()
    assert rows
    assert foreign_rows == 0
    assert duplicates == 0
    assert {row["language"] for row in rows} == {"fr", "en"}
    for row in rows:
        assert row["qa_status"] == "FALLBACK"
        assert row["payload_variant"] == "FACTUAL_FALLBACK"
        assert all(row[field] is None for field in (
            "provider", "model_id", "prompt_version", "qa_provider",
            "qa_model_id",
        ))
        payload = CardPresentationPayload.from_json_value(row["payload"])
        assert payload.variant is PresentationVariant.FACTUAL_FALLBACK
        assert payload.claims
        assert all(claim.evidence_refs for claim in payload.claims)
    counts = {
        language: sum(row["language"] == language for row in rows)
        for language in ("fr", "en")
    }
    history = {"status": "absent"}
    if historical is not None:
        assert re.fullmatch(r"[0-9a-f]{64}", historical["signal_key"])
        assert re.fullmatch(r"[0-9a-f]{64}", historical["artifact_id"])
        assert type(historical["version"]) is int and historical["version"] >= 1
        history = {
            "status": "available",
            "signal_id": historical["signal_key"],
            "artifact_id": historical["artifact_id"],
            "version": historical["version"],
        }
    print(json.dumps({
        "status": "qa_factual_ok",
        "fr": counts["fr"],
        "en": counts["en"],
        "ai_enabled": 0,
        "history": history,
    }, sort_keys=True, separators=(",", ":")))


try:
    main()
except Exception:
    print("qa_factual_failed", file=sys.stderr)
    raise SystemExit(1) from None
PY
REMOTE
)
printf '%s' "$KIVOU_QA_FACTUAL_PROOF" | jq -e '
  .status == "qa_factual_ok" and .fr > 0 and .en > 0 and
  .ai_enabled == 0 and
  ((.history.status == "absent" and (.history | keys) == ["status"]) or
   (.history.status == "available" and
    (.history.signal_id | type == "string" and test("^[0-9a-f]{64}$")) and
    (.history.artifact_id | type == "string" and test("^[0-9a-f]{64}$")) and
    (.history.version | type == "number" and . >= 1 and floor == .)))
' >/dev/null
KIVOU_HISTORICAL_STATUS=$(printf '%s' "$KIVOU_QA_FACTUAL_PROOF" | \
  jq -r '.history.status')
case "$KIVOU_HISTORICAL_STATUS" in
  (absent) ;;
  (available)
    KIVOU_HISTORICAL_SIGNAL_ID=$(printf '%s' "$KIVOU_QA_FACTUAL_PROOF" | \
      jq -r '.history.signal_id')
    KIVOU_HISTORICAL_ARTIFACT_ID=$(printf '%s' "$KIVOU_QA_FACTUAL_PROOF" | \
      jq -r '.history.artifact_id')
    KIVOU_HISTORICAL_ARTIFACT_VERSION=$(printf '%s' "$KIVOU_QA_FACTUAL_PROOF" | \
      jq -r '.history.version')
    printf '%s\n' "$KIVOU_HISTORICAL_SIGNAL_ID" | grep -Eq '^[0-9a-f]{64}$'
    printf '%s\n' "$KIVOU_HISTORICAL_ARTIFACT_ID" | grep -Eq '^[0-9a-f]{64}$'
    printf '%s\n' "$KIVOU_HISTORICAL_ARTIFACT_VERSION" | \
      grep -Eq '^[1-9][0-9]*$'
    ;;
  (*) exit 69 ;;
esac
unset KIVOU_QA_FACTUAL_PROOF
printf 'qa_factual_proof_ok history=%s\n' "$KIVOU_HISTORICAL_STATUS"
~~~

## 8. Smoke navigateur desktop et mobile

Utiliser uniquement un storage state QA existant, protégé et correspondant à
l'empreinte de l'étape 7. Ne pas le créer, l'imprimer ou le copier dans le
dépôt. Inspecter réellement à `1440×900` (desktop) et `390×844` (mobile), avec
collecteurs `console`, `pageerror`, `requestfailed` et réponses HTTP 5xx; tout
événement inattendu est un échec.

Checklist obligatoire, captures desktop et mobile à l'appui :

- **C001 Dashboard** : au plus six résumés factuels, date qualifiée,
  acheteur/attributaire distincts, valeurs manquantes explicites, CTA avec
  l'artifact ID publié et aucun titre administratif reconstruit;
- **C002 Entreprises** : aucune rafale navigateur vers `/signals/:id`,
  master-detail et scroll indépendant desktop, sélection et rechargement du
  deep-link, `Back`, `Forward`, restauration du focus, navigation mobile puis
  `Retour aux attributions`, faits du profil et lien canonique Signaux;
- **C003 Signaux** : feed/détail sur le même artifact ID et la même version,
  sélection courante, deep-link/rechargement, `Back`, `Forward`, scroll
  indépendant, focus, `Retour aux signaux`, note chargée sans mutation et lien
  canonique Entreprise; le parcours historique est la gate séparée finale;
- **teaser verrouillé** : le JSON ne contient ni la clé `presentation` ni la
  clé `company_key`, aucune identité entreprise/attributaire, aucune requête détail/note et le CTA reste
  l'action de facturation réelle;
- tous les artefacts visibles sont `FALLBACK/FACTUAL_FALLBACK`; aucun appel de
  génération ou QA pendant les GET, aucune erreur console, aucun 5xx.

Sur les trois surfaces, vérifier aussi qu'aucune date de publication comme date d’attribution n'est affichée, qu'aucune association « Matériaux → personnel » n'apparaît et qu'aucune personne ni urgence inventée n'est présentée.

Le contrat DOM normatif de `MasterDetailFrame` porte
`data-master-detail-pane="list"` et `data-master-detail-pane="detail"`
directement sur les deux panes `overflow-y:auto`. Avant sélection C002, seule
la pane liste visible doit déborder : le placeholder détail peut rester court.
Après sélection desktop, les deux panes visibles doivent déborder et être
manipulées séparément; sur mobile, une seule pane est visible à chaque état.
L'absence, la duplication ou l'ambiguïté de ces attributs impose STOP et doit
être corrigée dans la PR UI concernée.

Le feed contrôlé expose exactement un contrôle interactif verrouillé identifié
par `.signal-item.is-locked`. Son texte doit correspondre exactement au headline
borné du payload, sans recopier le signal ID dans le DOM. Le contrôle ne porte
ni présentation ni identité entreprise et son clic ne doit déclencher aucun GET
détail/note Signaux.

Exécuter ce smoke local depuis le checkout du SHA final. Il utilise les rôles,
noms accessibles et URLs normatifs des plans C001–C003; l'absence d'un de ces
contrats est un échec, jamais une raison de relâcher un sélecteur. Il ne crée,
ne copie ni ne réécrit le storage state protégé :

~~~bash
set -euo pipefail
test "$(git rev-parse HEAD)" = "$KIVOU_FINAL_SHA"
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
printf '%s\n' "$KIVOU_FINAL_SHORT" | grep -Eq '^[0-9a-f]{12}$'
printf '%s\n' "$KIVOU_BACKFILL_AS_OF" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
printf '%s\n' "$KIVOU_QA_DB_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'
: "${KIVOU_QA_STORAGE_STATE_REAL:?STOP: storage state QA protégé absent}"
test -f "$KIVOU_QA_STORAGE_STATE_REAL"
test ! -L "$KIVOU_QA_STORAGE_STATE_REAL"
test "$(readlink -f "$KIVOU_QA_STORAGE_STATE_REAL")" = \
  "$KIVOU_QA_STORAGE_STATE_REAL"
test "$(stat -c '%U:%a' "$KIVOU_QA_STORAGE_STATE_REAL")" = \
  "$(id -un):600"
case "$KIVOU_QA_STORAGE_STATE_REAL" in
  ("$KIVOU_OPERATOR_ROOT_REAL"|"$KIVOU_OPERATOR_ROOT_REAL"/*) exit 69 ;;
  (*) ;;
esac
kivou_validate_evidence_root
test "$KIVOU_EVIDENCE_DIR" = \
  "$KIVOU_CARD_EVIDENCE_ROOT_REAL/card-presentation-$KIVOU_FINAL_SHA"
test ! -L "$KIVOU_EVIDENCE_DIR"
test "$(readlink -f "$KIVOU_EVIDENCE_DIR")" = "$KIVOU_EVIDENCE_DIR"
test "$(stat -c '%U:%a' "$KIVOU_EVIDENCE_DIR")" = "$(id -un):700"
KIVOU_BROWSER_EVIDENCE_DIR="$KIVOU_EVIDENCE_DIR/browser"
test ! -e "$KIVOU_BROWSER_EVIDENCE_DIR"
install -m 700 -d "$KIVOU_BROWSER_EVIDENCE_DIR"
test ! -L "$KIVOU_BROWSER_EVIDENCE_DIR"
test "$(readlink -f "$KIVOU_BROWSER_EVIDENCE_DIR")" = \
  "$KIVOU_BROWSER_EVIDENCE_DIR"
test "$(stat -c '%U:%a' "$KIVOU_BROWSER_EVIDENCE_DIR")" = \
  "$(id -un):700"
umask 077
for KIVOU_CAPTURE in \
  desktop-dashboard.png desktop-companies.png desktop-signals.png \
  mobile-dashboard.png mobile-companies.png mobile-signals.png; do
  test ! -e "$KIVOU_BROWSER_EVIDENCE_DIR/$KIVOU_CAPTURE"
done

KIVOU_CARD_JOURNAL_BOUNDARY=$(ssh kivou-staging 'bash -s' <<'REMOTE'
set -euo pipefail
kivou_assert_no_card_ai_runtime() {
  KIVOU_CARD_UNIT_FILES=$(systemctl list-unit-files --no-legend --no-pager \
    'kivou-card-ai*' 'kivou-card-intelligence*' \
    'kivou-card-generation*' 'kivou-card-generator*' \
    'kivou-card-provider*' 'kivou-card-qa-worker*')
  test -z "$KIVOU_CARD_UNIT_FILES"
  unset KIVOU_CARD_UNIT_FILES
  KIVOU_CARD_UNITS=$(systemctl list-units --all --no-legend --no-pager \
    'kivou-card-ai*' 'kivou-card-intelligence*' \
    'kivou-card-generation*' 'kivou-card-generator*' \
    'kivou-card-provider*' 'kivou-card-qa-worker*')
  test -z "$KIVOU_CARD_UNITS"
  unset KIVOU_CARD_UNITS
  test -f /etc/kivou/staging.env
  test ! -L /etc/kivou/staging.env
  KIVOU_CARD_CONFIG_KEYS=$(sudo awk -F= '
    $1 ~ /^KIVOU_CARD_(AI|INTELLIGENCE|GENERATION|GENERATOR|PROVIDER|QA_PROVIDER|WORKER)/ {
      print "configured"; exit
    }
  ' /etc/kivou/staging.env)
  test -z "$KIVOU_CARD_CONFIG_KEYS"
  unset KIVOU_CARD_CONFIG_KEYS
  KIVOU_API_UNIT_TEXT=$(sudo systemctl cat kivou-api.service)
  KIVOU_CARD_API_UNIT_DIRECTIVES=$(printf '%s\n' "$KIVOU_API_UNIT_TEXT" | \
    awk 'BEGIN { IGNORECASE=1 }
      /card[_ -]?(generation|generator|provider|qa[_ -]?worker)/ {
        print "configured"; exit
      }')
  unset KIVOU_API_UNIT_TEXT
  test -z "$KIVOU_CARD_API_UNIT_DIRECTIVES"
  unset KIVOU_CARD_API_UNIT_DIRECTIVES
}
kivou_assert_no_card_ai_runtime
KIVOU_CARD_JOURNAL_CURSOR=$(sudo journalctl -u kivou-api.service -n 0 \
  --show-cursor --no-pager | sed -n 's/^-- cursor: //p')
printf '%s\n' "$KIVOU_CARD_JOURNAL_CURSOR" | \
  grep -Eq '^[A-Za-z0-9:;._=-]+$'
KIVOU_CARD_JOURNAL_SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '%s\n' "$KIVOU_CARD_JOURNAL_SINCE" | \
  grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
printf 'cursor=%s\nsince=%s\n' \
  "$KIVOU_CARD_JOURNAL_CURSOR" "$KIVOU_CARD_JOURNAL_SINCE"
REMOTE
)
test "$(printf '%s\n' "$KIVOU_CARD_JOURNAL_BOUNDARY" | wc -l)" = 2
printf '%s\n' "$KIVOU_CARD_JOURNAL_BOUNDARY" | grep -Eq \
  '^cursor=[A-Za-z0-9:;._=-]+$'
printf '%s\n' "$KIVOU_CARD_JOURNAL_BOUNDARY" | grep -Eq \
  '^since=[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
KIVOU_CARD_JOURNAL_CURSOR=$(printf '%s\n' "$KIVOU_CARD_JOURNAL_BOUNDARY" | \
  sed -n 's/^cursor=//p')
KIVOU_CARD_JOURNAL_SINCE=$(printf '%s\n' "$KIVOU_CARD_JOURNAL_BOUNDARY" | \
  sed -n 's/^since=//p')
unset KIVOU_CARD_JOURNAL_BOUNDARY
printf '%s\n' "$KIVOU_CARD_JOURNAL_CURSOR" | \
  grep -Eq '^[A-Za-z0-9:;._=-]+$'
printf '%s\n' "$KIVOU_CARD_JOURNAL_SINCE" | \
  grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
(
  cd frontend
  KIVOU_QA_STORAGE_STATE="$KIVOU_QA_STORAGE_STATE_REAL" \
  KIVOU_QA_DB_FINGERPRINT="$KIVOU_QA_DB_FINGERPRINT" \
  KIVOU_BACKFILL_AS_OF="$KIVOU_BACKFILL_AS_OF" \
  KIVOU_BROWSER_EVIDENCE_DIR="$KIVOU_BROWSER_EVIDENCE_DIR" \
  KIVOU_QA_ORIGIN=https://staging.kivou.eu node <<'JS'
function requireTrue(value) {
  if (!value) throw new Error()
}

async function accountFingerprint(page, expectedFingerprint) {
  return page.evaluate(async (expected) => {
    const response = await fetch('/me', { credentials: 'same-origin' })
    if (response.status !== 200) throw new Error()
    const me = await response.json()
    if (typeof me.account_id !== 'string' || me.account_id.length === 0) {
      throw new Error()
    }
    const bytes = new TextEncoder().encode(me.account_id)
    const digest = await crypto.subtle.digest('SHA-256', bytes)
    const fingerprint = Array.from(new Uint8Array(digest))
      .map((value) => value.toString(16).padStart(2, '0'))
      .join('')
      .slice(0, 16)
    if (fingerprint !== expected) throw new Error()
    return true
  }, expectedFingerprint)
}

async function verifyPublishedApi(page, asOf) {
  return page.evaluate(async (readDate) => {
    const feedResponse = await fetch(
      `/signals?as_of=${encodeURIComponent(readDate)}&limit=50&offset=0`,
      { credentials: 'same-origin' },
    )
    if (feedResponse.status !== 200) throw new Error()
    const feed = await feedResponse.json()
    if (feed.read_at !== readDate || !Array.isArray(feed.items)) throw new Error()
    const unlocked = feed.items.filter((item) => item && item.locked === false)
    const locked = feed.items.filter((item) => item && item.locked === true)
    if (unlocked.length === 0 || locked.length === 0) throw new Error()
    const signalIds = feed.items.map((item) => item?.signal_id)
    if (signalIds.some((signalId) => (
      typeof signalId !== 'string' || !/^[0-9a-f]{64}$/.test(signalId)
    )) || new Set(signalIds).size !== signalIds.length) throw new Error()
    if (locked.some((item) => (
      Object.hasOwn(item, 'presentation') || Object.hasOwn(item, 'company_key')
    ))) throw new Error()
    const published = unlocked.filter((item) => item.presentation)
    if (published.length === 0) throw new Error()
    for (const item of published) {
      const artifact = item.presentation
      if (!/^[0-9a-f]{64}$/.test(artifact.artifact_id) ||
          !Number.isInteger(artifact.version) || artifact.version < 1 ||
          typeof artifact.content?.headline !== 'string' ||
          artifact.content.headline.length === 0) throw new Error()
      if (artifact.status !== 'FALLBACK') throw new Error()
      if (!artifact.content || artifact.content.variant !== 'FACTUAL_FALLBACK') {
        throw new Error()
      }
      if (!Array.isArray(artifact.content.claims) ||
          artifact.content.claims.length === 0 ||
          artifact.content.claims.some((claim) => (
            !Array.isArray(claim.evidence_refs) || claim.evidence_refs.length === 0
          ))) throw new Error()
    }
    const item = published[0]
    const artifact = item.presentation
    const detailResponse = await fetch(
      `/signals/${encodeURIComponent(item.signal_id)}` +
      `?presentation_artifact_id=${encodeURIComponent(artifact.artifact_id)}`,
      { credentials: 'same-origin' },
    )
    if (detailResponse.status !== 200) throw new Error()
    const detail = await detailResponse.json()
    if (!detail.presentation ||
        detail.signal_id !== item.signal_id ||
        detail.presentation.artifact_id !== artifact.artifact_id ||
        detail.presentation.version !== artifact.version) throw new Error()
    if (typeof locked[0].headline !== 'string' ||
        locked[0].headline.length === 0) throw new Error()
    return {
      lockedSignalId: locked[0].signal_id,
      lockedHeadline: locked[0].headline,
      pinnedSignalId: item.signal_id,
      pinnedArtifactId: artifact.artifact_id,
      pinnedVersion: artifact.version,
      pinnedHeadline: artifact.content.headline,
    }
  }, asOf)
}

function installFailureCollectors(page, origin, errors, requests, responses) {
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push('console')
  })
  page.on('pageerror', () => errors.push('pageerror'))
  page.on('requestfailed', () => errors.push('requestfailed'))
  page.on('response', (response) => {
    if (response.status() >= 500) errors.push('http5xx')
    let url
    try {
      url = new URL(response.url())
    } catch {
      errors.push('invalid-response-url')
      return
    }
    if (url.origin === origin) {
      responses.push({
        method: response.request().method(),
        path: `${url.pathname}${url.search}`,
        status: response.status(),
      })
    }
  })
  page.on('request', (request) => {
    let url
    try {
      url = new URL(request.url())
    } catch {
      errors.push('invalid-url')
      return
    }
    if (url.origin !== origin) errors.push('external-request')
    requests.push({ method: request.method(), path: `${url.pathname}${url.search}` })
  })
}

function waitForExactGetResponse(page, origin, expectedPath) {
  return page.waitForResponse((response) => {
    let url
    try {
      url = new URL(response.url())
    } catch {
      return false
    }
    return response.request().method() === 'GET' &&
      url.origin === origin &&
      `${url.pathname}${url.search}` === expectedPath
  })
}

async function expectFocusedHeading(page) {
  await page.waitForFunction(() => /^H[1-3]$/.test(document.activeElement?.tagName || ''))
}

async function expectLocatorFocused(locator) {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (await locator.evaluate((element) => document.activeElement === element)) return
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error()
}

async function visibleMasterDetailPane(page, viewport, pane, phase) {
  requireTrue(viewport.name === 'desktop' || viewport.name === 'mobile')
  requireTrue(pane === 'list' || pane === 'detail')
  requireTrue(typeof phase === 'string' && phase.length > 0)
  const locator = page.locator(
    `[data-master-detail-pane="${pane}"]:visible`,
  )
  await locator.first().waitFor()
  requireTrue(await locator.count() === 1)
  if (viewport.name === 'mobile') {
    const otherPane = pane === 'list' ? 'detail' : 'list'
    const otherLocator = page.locator(
      `[data-master-detail-pane="${otherPane}"]:visible`,
    )
    await otherLocator.first().waitFor({ state: 'hidden' })
    requireTrue(await otherLocator.count() === 0)
  }
  return locator
}

async function setScrollContract(page, viewport, pane, phase) {
  const locator = await visibleMasterDetailPane(page, viewport, pane, phase)
  return locator.evaluate((element, contract) => {
    const overflow = getComputedStyle(element).overflowY
    const bounds = element.getBoundingClientRect()
    const maximum = element.scrollHeight - element.clientHeight
    if (element.getAttribute('data-master-detail-pane') !== contract.pane ||
        bounds.width <= 0 || bounds.height <= 0 ||
        !(overflow === 'auto' || overflow === 'scroll') || maximum < 200) {
      throw new Error()
    }
    const main = element.closest('main')
    if (!main) throw new Error()
    const path = []
    let cursor = element
    while (cursor !== main) {
      const parent = cursor.parentElement
      if (!parent) throw new Error()
      path.unshift(Array.from(parent.children).indexOf(cursor))
      cursor = parent
    }
    const target = contract.pane === 'list' ? 120 : 160
    element.scrollTop = target
    element.dispatchEvent(new Event('scroll', { bubbles: true }))
    if (!(element.scrollTop > 0) || Math.abs(element.scrollTop - target) > 2) {
      throw new Error()
    }
    return { position: element.scrollTop, panePath: path.join('.') }
  }, { pane, phase })
}

async function expectScrollContractRestored(page, viewport, pane, phase, expected) {
  requireTrue(expected.position > 0)
  const locator = await visibleMasterDetailPane(page, viewport, pane, phase)
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const actual = await locator.evaluate((element, expectedPane) => {
      const overflow = getComputedStyle(element).overflowY
      const bounds = element.getBoundingClientRect()
      if (element.getAttribute('data-master-detail-pane') !== expectedPane ||
          bounds.width <= 0 || bounds.height <= 0 ||
          !(overflow === 'auto' || overflow === 'scroll')) return -1
      return element.scrollTop
    }, pane)
    if (actual > 0 && Math.abs(actual - expected.position) <= 2) return
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error()
}

async function smokeDashboard(page, origin, evidencePath) {
  await page.goto(`${origin}/app/dashboard`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', {
    name: /Attributions récentes pertinentes|Relevant recent awards/i,
  }).waitFor()
  const links = page.locator(
    'a[href^="/app/signals/"][href*="presentation_artifact_id="]',
  )
  const count = await links.count()
  requireTrue(count >= 1 && count <= 6)
  for (let index = 0; index < count; index += 1) {
    const href = await links.nth(index).getAttribute('href')
    requireTrue(Boolean(href))
    const url = new URL(href, origin)
    requireTrue(/^[0-9a-f]{64}$/.test(
      url.searchParams.get('presentation_artifact_id') || '',
    ))
  }
  await page.screenshot({ path: evidencePath, fullPage: true })
}

async function smokeCompanies(page, origin, viewport, evidencePath, requests) {
  const requestStart = requests.length
  await page.goto(`${origin}/app/companies`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', {
    name: /Entreprises attributaires|Awarded companies/i,
  }).waitFor()
  requireTrue(!requests.slice(requestStart).some(({ method, path }) => (
    method === 'GET' && /^\/signals\/[^?]+(?:\?|$)/.test(path)
  )))
  const award = page.getByRole('link', { name: /attribution|award/i }).first()
  await award.waitFor()
  await award.focus()
  let companyListScroll = await setScrollContract(page, viewport, 'list', 'companies-initial-list')
  await award.evaluate((element) => element.click())
  await page.waitForURL(/\/app\/companies\/[^?]+\?signal=[^&]+$/)
  const selectedUrl = page.url()
  await expectFocusedHeading(page)
  requireTrue(await page.locator('a[href^="/app/signals/"]').count() >= 1)
  if (viewport.name === 'desktop') {
    companyListScroll = await setScrollContract(page, viewport, 'list', 'companies-selected-list')
  }
  const companyDetailScroll = await setScrollContract(page, viewport, 'detail', 'companies-selected-detail')
  if (viewport.name === 'desktop') {
    requireTrue(companyListScroll.panePath !== companyDetailScroll.panePath)
  }
  await page.goBack({ waitUntil: 'networkidle' })
  await page.waitForURL(/\/app\/companies$/)
  await award.waitFor()
  await expectLocatorFocused(award)
  await expectScrollContractRestored(
    page, viewport, 'list', 'companies-back-list', companyListScroll,
  )
  await page.goForward({ waitUntil: 'networkidle' })
  requireTrue(page.url() === selectedUrl)
  await expectFocusedHeading(page)
  await expectScrollContractRestored(
    page, viewport, 'detail', 'companies-forward-detail', companyDetailScroll,
  )
  if (viewport.name === 'desktop') {
    await expectScrollContractRestored(
      page, viewport, 'list', 'companies-forward-list', companyListScroll,
    )
  }
  await page.reload({ waitUntil: 'networkidle' })
  requireTrue(page.url() === selectedUrl)
  await expectScrollContractRestored(
    page, viewport, 'detail', 'companies-reload-detail', companyDetailScroll,
  )
  if (viewport.name === 'desktop') {
    await expectScrollContractRestored(
      page, viewport, 'list', 'companies-reload-list', companyListScroll,
    )
  }
  await page.screenshot({ path: evidencePath, fullPage: true })
  if (viewport.name === 'mobile') {
    const back = page.getByRole('button', {
      name: /Retour aux attributions|Back to awards/i,
    }).or(page.getByRole('link', {
      name: /Retour aux attributions|Back to awards/i,
    })).first()
    await back.click()
    await page.waitForURL(/\/app\/companies$/)
    await award.waitFor()
    await expectLocatorFocused(award)
    await expectScrollContractRestored(
      page, viewport, 'list', 'companies-return-list', companyListScroll,
    )
  }
}

async function smokeSignals(
  page, origin, viewport, evidencePath, requests, responses, api,
) {
  await page.goto(`${origin}/app/signals`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', {
    name: /Signaux détectés|Detected signals/i,
  }).waitFor()
  const lockedBinding = page.locator('.signal-list .signal-item.is-locked')
  requireTrue(await lockedBinding.count() === 1)
  const lockedControl = lockedBinding
  requireTrue(await lockedControl.evaluate((element) => (
    element.tagName === 'BUTTON' || element.tagName === 'A'
  )))
  await lockedControl.waitFor()
  const lockedText = lockedControl.getByText(api.lockedHeadline, { exact: true })
  requireTrue(await lockedText.count() === 1)
  await lockedText.waitFor()
  requireTrue(await lockedControl.evaluate((element) => (
    !element.outerHTML.includes('presentation') &&
    !element.outerHTML.includes('company_key') &&
    !element.querySelector('a[href^="/app/companies/"]')
  )))
  await lockedControl.focus()
  const lockedRequestStart = requests.length
  await lockedControl.click()
  await page.waitForURL(/\/app\/billing(?:\?|$)/)
  await page.waitForLoadState('networkidle')
  requireTrue(!requests.slice(lockedRequestStart).some(({ method, path }) => (
    method === 'GET' &&
    /^\/signals\/[^/?]+(?:\/note)?(?:\?|$)/.test(path)
  )))
  await page.goBack({ waitUntil: 'networkidle' })
  await page.waitForURL(/\/app\/signals$/)
  await lockedControl.waitFor()
  await expectLocatorFocused(lockedControl)
  const selection = page.locator(
    '.signal-list .signal-item:not(.is-locked)',
  ).filter({ hasText: api.pinnedHeadline })
  requireTrue(await selection.count() === 1)
  await selection.waitFor()
  await selection.focus()
  let signalListScroll = await setScrollContract(page, viewport, 'list', 'signals-initial-list')
  const expectedDetailPath =
    `/signals/${encodeURIComponent(api.pinnedSignalId)}` +
    `?presentation_artifact_id=${encodeURIComponent(api.pinnedArtifactId)}`
  const expectedNotePath =
    `/signals/${encodeURIComponent(api.pinnedSignalId)}/note`
  const currentDetailResponsePromise = waitForExactGetResponse(
    page, origin, expectedDetailPath,
  )
  const currentNoteResponsePromise = waitForExactGetResponse(
    page, origin, expectedNotePath,
  )
  const selectionRequestStart = requests.length
  const selectionResponseStart = responses.length
  await selection.evaluate((element) => element.click())
  await page.waitForURL((url) => (
    url.pathname === `/app/signals/${encodeURIComponent(api.pinnedSignalId)}` &&
    url.searchParams.get('presentation_artifact_id') === api.pinnedArtifactId &&
    Array.from(url.searchParams).length === 1
  ))
  const selectedUrl = page.url()
  const selected = new URL(selectedUrl)
  const artifactId = selected.searchParams.get('presentation_artifact_id')
  requireTrue(Boolean(artifactId && /^[0-9a-f]{64}$/.test(artifactId)))
  requireTrue(selected.pathname ===
    `/app/signals/${encodeURIComponent(api.pinnedSignalId)}`)
  requireTrue(
    selected.searchParams.get('presentation_artifact_id') === api.pinnedArtifactId,
  )
  requireTrue(Array.from(selected.searchParams).length === 1)
  requireTrue(Number.isInteger(api.pinnedVersion) && api.pinnedVersion >= 1)
  await expectFocusedHeading(page)
  await page.getByText(api.pinnedHeadline, { exact: true }).first().waitFor()
  const [currentDetailResponse, currentNoteResponse] = await Promise.all([
    currentDetailResponsePromise,
    currentNoteResponsePromise,
  ])
  requireTrue(currentDetailResponse.status() === 200)
  requireTrue(currentNoteResponse.status() === 200)
  requireTrue(requests.slice(selectionRequestStart).some(({ method, path }) => (
    method === 'GET' && path === expectedDetailPath
  )))
  requireTrue(requests.slice(selectionRequestStart).some(({ method, path }) => (
    method === 'GET' && path === expectedNotePath
  )))
  requireTrue(responses.slice(selectionResponseStart).some(({
    method, path, status,
  }) => method === 'GET' && status === 200 && path === expectedDetailPath))
  requireTrue(responses.slice(selectionResponseStart).some(({
    method, path, status,
  }) => method === 'GET' && status === 200 && path === expectedNotePath))
  requireTrue(await page.locator(
    'a[href^="/app/companies/"][href*="signal="]',
  ).count() >= 1)
  requireTrue(!requests.some(({ method, path }) => (
    method !== 'GET' && /\/signals\/[^/]+\/note(?:\?|$)/.test(path)
  )))
  if (viewport.name === 'desktop') {
    signalListScroll = await setScrollContract(page, viewport, 'list', 'signals-selected-list')
  }
  const signalDetailScroll = await setScrollContract(page, viewport, 'detail', 'signals-selected-detail')
  if (viewport.name === 'desktop') {
    requireTrue(signalListScroll.panePath !== signalDetailScroll.panePath)
  }
  await page.goBack({ waitUntil: 'networkidle' })
  await page.waitForURL(/\/app\/signals$/)
  await selection.waitFor()
  await expectLocatorFocused(selection)
  await expectScrollContractRestored(
    page, viewport, 'list', 'signals-back-list', signalListScroll,
  )
  await page.goForward({ waitUntil: 'networkidle' })
  requireTrue(page.url() === selectedUrl)
  await expectFocusedHeading(page)
  await expectScrollContractRestored(
    page, viewport, 'detail', 'signals-forward-detail', signalDetailScroll,
  )
  if (viewport.name === 'desktop') {
    await expectScrollContractRestored(
      page, viewport, 'list', 'signals-forward-list', signalListScroll,
    )
  }
  await page.reload({ waitUntil: 'networkidle' })
  requireTrue(page.url() === selectedUrl)
  await expectScrollContractRestored(
    page, viewport, 'detail', 'signals-reload-detail', signalDetailScroll,
  )
  if (viewport.name === 'desktop') {
    await expectScrollContractRestored(
      page, viewport, 'list', 'signals-reload-list', signalListScroll,
    )
  }
  await page.screenshot({ path: evidencePath, fullPage: true })

  if (viewport.name === 'mobile') {
    const back = page.getByRole('button', {
      name: /Retour aux signaux|Back to signals/i,
    }).or(page.getByRole('link', {
      name: /Retour aux signaux|Back to signals/i,
    })).first()
    await back.click()
    await page.waitForURL(/\/app\/signals$/)
    await selection.waitFor()
    await expectLocatorFocused(selection)
    await expectScrollContractRestored(
      page, viewport, 'list', 'signals-return-list', signalListScroll,
    )
  }

}

async function run() {
  const { chromium } = require('playwright')
  const origin = process.env.KIVOU_QA_ORIGIN
  const asOf = process.env.KIVOU_BACKFILL_AS_OF
  const expectedFingerprint = process.env.KIVOU_QA_DB_FINGERPRINT
  const storageState = process.env.KIVOU_QA_STORAGE_STATE
  const evidenceDir = process.env.KIVOU_BROWSER_EVIDENCE_DIR
  requireTrue(Boolean(origin && asOf && expectedFingerprint && storageState &&
    evidenceDir))
  const browser = await chromium.launch({ headless: true })
  try {
    const viewports = [
      { name: 'desktop', width: 1440, height: 900 },
      { name: 'mobile', width: 390, height: 844 },
    ]
    for (const viewport of viewports) {
      const context = await browser.newContext({
        storageState: process.env.KIVOU_QA_STORAGE_STATE,
        viewport: { width: viewport.width, height: viewport.height },
      })
      const page = await context.newPage()
      const errors = []
      const requests = []
      const responses = []
      installFailureCollectors(page, origin, errors, requests, responses)
      await page.goto(`${origin}/app/signals`, { waitUntil: 'networkidle' })
      requireTrue(await accountFingerprint(page, expectedFingerprint))
      const api = await verifyPublishedApi(page, asOf)
      await smokeDashboard(
        page, origin, `${evidenceDir}/${viewport.name}-dashboard.png`,
      )
      await smokeCompanies(
        page, origin, viewport,
        `${evidenceDir}/${viewport.name}-companies.png`, requests,
      )
      await smokeSignals(
        page, origin, viewport,
        `${evidenceDir}/${viewport.name}-signals.png`, requests, responses, api,
      )
      requireTrue(!requests.some(({ path }) => (
        path.startsWith(`/signals/${encodeURIComponent(api.lockedSignalId)}?`) ||
        path === `/signals/${encodeURIComponent(api.lockedSignalId)}` ||
        path.startsWith(`/signals/${encodeURIComponent(api.lockedSignalId)}/note`)
      )))
      requireTrue(!requests.some(({ method }) => !['GET', 'HEAD'].includes(method)))
      requireTrue(errors.length === 0)
      await context.close()
    }
  } finally {
    await browser.close()
  }
}

run()
  .then(() => console.log("card_current_smoke_ok"))
  .catch(() => {
    console.error("card_current_smoke_failed")
    process.exitCode = 1
  })
JS
)

kivou_audit_card_get_journal() {
  ssh kivou-staging 'bash -s' -- \
    "$KIVOU_CARD_JOURNAL_CURSOR" "$KIVOU_CARD_JOURNAL_SINCE" <<'REMOTE'
set -euo pipefail
KIVOU_CARD_JOURNAL_CURSOR=$1
KIVOU_CARD_JOURNAL_SINCE=$2
printf '%s\n' "$KIVOU_CARD_JOURNAL_CURSOR" | \
  grep -Eq '^[A-Za-z0-9:;._=-]+$'
printf '%s\n' "$KIVOU_CARD_JOURNAL_SINCE" | \
  grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
kivou_assert_no_card_ai_runtime() {
  KIVOU_CARD_UNIT_FILES=$(systemctl list-unit-files --no-legend --no-pager \
    'kivou-card-ai*' 'kivou-card-intelligence*' \
    'kivou-card-generation*' 'kivou-card-generator*' \
    'kivou-card-provider*' 'kivou-card-qa-worker*')
  test -z "$KIVOU_CARD_UNIT_FILES"
  unset KIVOU_CARD_UNIT_FILES
  KIVOU_CARD_UNITS=$(systemctl list-units --all --no-legend --no-pager \
    'kivou-card-ai*' 'kivou-card-intelligence*' \
    'kivou-card-generation*' 'kivou-card-generator*' \
    'kivou-card-provider*' 'kivou-card-qa-worker*')
  test -z "$KIVOU_CARD_UNITS"
  unset KIVOU_CARD_UNITS
  test -f /etc/kivou/staging.env
  test ! -L /etc/kivou/staging.env
  KIVOU_CARD_CONFIG_KEYS=$(sudo awk -F= '
    $1 ~ /^KIVOU_CARD_(AI|INTELLIGENCE|GENERATION|GENERATOR|PROVIDER|QA_PROVIDER|WORKER)/ {
      print "configured"; exit
    }
  ' /etc/kivou/staging.env)
  test -z "$KIVOU_CARD_CONFIG_KEYS"
  unset KIVOU_CARD_CONFIG_KEYS
  KIVOU_API_UNIT_TEXT=$(sudo systemctl cat kivou-api.service)
  KIVOU_CARD_API_UNIT_DIRECTIVES=$(printf '%s\n' "$KIVOU_API_UNIT_TEXT" | \
    awk 'BEGIN { IGNORECASE=1 }
      /card[_ -]?(generation|generator|provider|qa[_ -]?worker)/ {
        print "configured"; exit
      }')
  unset KIVOU_API_UNIT_TEXT
  test -z "$KIVOU_CARD_API_UNIT_DIRECTIVES"
  unset KIVOU_CARD_API_UNIT_DIRECTIVES
}
KIVOU_CARD_GET_JOURNAL=$(sudo journalctl -u kivou-api.service \
  --after-cursor "$KIVOU_CARD_JOURNAL_CURSOR" --no-pager --output=cat)
if printf '%s\n' "$KIVOU_CARD_GET_JOURNAL" | \
  grep -Eqi 'Traceback|unhandled|exception'; then
  exit 69
fi
if printf '%s\n' "$KIVOU_CARD_GET_JOURNAL" | grep -Eqi \
  'signals\.card_intelligence|signals\.qa_signals|card[_ -]?(generation|provider|qa[_ -]?worker)|card[_ -]?generator'; then
  exit 69
fi
unset KIVOU_CARD_GET_JOURNAL
kivou_assert_no_card_ai_runtime
printf "%s\n" "card_get_journal_ok"
REMOTE
}
kivou_audit_card_get_journal

find "$KIVOU_BROWSER_EVIDENCE_DIR" -maxdepth 1 -type f -name '*.png' \
  -exec chmod 600 {} +
test "$(find "$KIVOU_BROWSER_EVIDENCE_DIR" -maxdepth 1 -type f \
  \( -name '*-dashboard.png' -o -name '*-companies.png' -o \
  -name '*-signals.png' \) | wc -l)" = 6
printf 'name=%s sha256=%s verdict=ci_green\n' \
  "$(basename "$KIVOU_CI_JSON")" "$KIVOU_CI_JSON_SHA256"
for KIVOU_CAPTURE in \
  desktop-dashboard.png desktop-companies.png desktop-signals.png \
  mobile-dashboard.png mobile-companies.png mobile-signals.png; do
  KIVOU_CAPTURE_FILE="$KIVOU_BROWSER_EVIDENCE_DIR/$KIVOU_CAPTURE"
  test -f "$KIVOU_CAPTURE_FILE"
  test ! -L "$KIVOU_CAPTURE_FILE"
  test "$(stat -c '%U:%a' "$KIVOU_CAPTURE_FILE")" = "$(id -un):600"
  KIVOU_CAPTURE_SHA256=$(sha256sum "$KIVOU_CAPTURE_FILE" | awk '{print $1}')
  printf '%s\n' "$KIVOU_CAPTURE_SHA256" | grep -Eq '^[0-9a-f]{64}$'
  printf 'name=%s sha256=%s verdict=visual_pending\n' \
    "$KIVOU_CAPTURE" "$KIVOU_CAPTURE_SHA256"
done
unset KIVOU_CAPTURE_FILE KIVOU_CAPTURE_SHA256
~~~

Le curseur journald est la frontière autoritaire; le timestamp UTC est conservé
comme repère opérateur secondaire. Le filtre ne lit que le journal de
`kivou-api.service` entre cette frontière et la fin du smoke. Il prouve
l'absence d'exception non gérée et de trace d'invocation Card Intelligence,
génération, provider Card ou worker QA pendant ces GET, sans afficher les
journaux. L'inventaire avant et après vérifie séparément qu'aucune unité ni clé
de configuration **Card AI** approuvée n'existe. Il ne prétend pas auditer ni
interdire un provider d'acquisition indépendant dans un autre service.

Le script est une gate automatisée, pas l'**inspection visuelle humaine**.
Ouvrir séparément les six PNG à leur résolution originale et contrôler la
hiérarchie, les intitulés acheteur/attributaire, les dates qualifiées, les
valeurs manquantes, les deux scrolls desktop, la pile mobile, les focus, le
teaser verrouillé, l'absence de débordement et tout texte potentiellement
inventé. Consigner le verdict de chaque image dans le rapport. **STOP** avant
la validation finale si une capture n'a pas été réellement inspectée ou si un
doute subsiste; `card_current_smoke_ok` seul ne vaut jamais validation visuelle.
Le rapport ne conserve pour chaque preuve que `name`, `sha256` et `verdict` :
`verdict=ci_green` pour le JSON CI et `verdict=visual_pass|visual_fail` après
l'inspection humaine. Ne jamais y copier un chemin absolu, le JSON, une capture,
un cookie ou une donnée compte/source.

Vérifier enfin le marker frontend, le SHA backend, la migration et les probes
publiques après la navigation :

~~~bash
ssh kivou-staging 'bash -s' -- "$KIVOU_FINAL_SHA" "$KIVOU_RELEASE_DIR" <<'REMOTE'
set -euo pipefail
KIVOU_FINAL_SHA=$1
KIVOU_RELEASE_DIR=$2
test "$(readlink -f /srv/kivou/app)" = "$KIVOU_RELEASE_DIR"
test "$(sudo -u kivou git -C /srv/kivou/app rev-parse HEAD)" = "$KIVOU_FINAL_SHA"
test "$(cat /srv/kivou/frontend/KIVOU_RELEASE_SHA)" = "$KIVOU_FINAL_SHA"
systemctl is-active --quiet kivou-api.service
systemctl is-active --quiet nginx.service
test "$(curl --silent --connect-timeout 2 --max-time 5 --output /dev/null \
  --write-out '%{http_code}' http://127.0.0.1:8000/me)" = 401
KIVOU_FINAL_REVISION=$(sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-final-revision-$$" --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/python" -c \
  'from signals.persistence.database import create_database_engine,current_revision; engine=create_database_engine(); revision=current_revision(engine); assert revision == "0028_card_presentation", revision; print(revision)')
test "$KIVOU_FINAL_REVISION" = "0028_card_presentation"
KIVOU_FINAL_ASSET_PATH=$(grep -Eo '/assets/[^"[:space:]]+' \
  /srv/kivou/frontend/index.html | head -n 1)
case "$KIVOU_FINAL_ASSET_PATH" in (/assets/*) ;; (*) exit 69 ;; esac
test -f "/srv/kivou/frontend$KIVOU_FINAL_ASSET_PATH"
for KIVOU_PATH in / /app/dashboard /app/companies /app/signals \
  "$KIVOU_FINAL_ASSET_PATH"; do
  test "$(curl --silent --show-error --connect-timeout 2 --max-time 5 \
    --output /dev/null --write-out '%{http_code}' \
    --resolve staging.kivou.eu:443:127.0.0.1 \
    "https://staging.kivou.eu$KIVOU_PATH")" = 200
done
REMOTE
~~~

Les preuves factuelles courantes, les six captures, leur inspection humaine,
l'audit journal et les probes finaux ci-dessus restent valides quel que soit
l'état historique découvert. Traiter maintenant cet état séparément. Si aucun
historique légitime n'existe, produire explicitement **STOP / NON-EXÉCUTABLE**
et obtenir une validation propriétaire; ne jamais déclarer le parcours
historique réussi et ne fabriquer aucune donnée. Si l'état est `available`, le
second smoke ci-dessous prouve le pin exact, la version, le headline dans la
pane détail et les GET détail/note 200, puis rejoue l'audit journal depuis la
frontière antérieure.

~~~bash
case "$KIVOU_HISTORICAL_STATUS" in
  (absent)
    KIVOU_HISTORICAL_SMOKE_STATUS=STOP_NON_EXECUTABLE
    KIVOU_ROLLOUT_STATUS=STOP_INCOMPLETE
    printf '%s\n' \
      'historical_smoke=STOP / NON-EXÉCUTABLE; validation propriétaire requise' \
      >&2
    ;;
  (available)
    : "${KIVOU_HISTORICAL_SIGNAL_ID:?STOP: historical signal absent}"
    : "${KIVOU_HISTORICAL_ARTIFACT_ID:?STOP: historical artifact absent}"
    : "${KIVOU_HISTORICAL_ARTIFACT_VERSION:?STOP: historical version absent}"
    printf '%s\n' "$KIVOU_HISTORICAL_SIGNAL_ID" | grep -Eq '^[0-9a-f]{64}$'
    printf '%s\n' "$KIVOU_HISTORICAL_ARTIFACT_ID" | grep -Eq '^[0-9a-f]{64}$'
    printf '%s\n' "$KIVOU_HISTORICAL_ARTIFACT_VERSION" | \
      grep -Eq '^[1-9][0-9]*$'

    (
  cd frontend
  KIVOU_QA_STORAGE_STATE="$KIVOU_QA_STORAGE_STATE_REAL" \
  KIVOU_QA_DB_FINGERPRINT="$KIVOU_QA_DB_FINGERPRINT" \
  KIVOU_HISTORICAL_SIGNAL_ID="$KIVOU_HISTORICAL_SIGNAL_ID" \
  KIVOU_HISTORICAL_ARTIFACT_ID="$KIVOU_HISTORICAL_ARTIFACT_ID" \
  KIVOU_HISTORICAL_ARTIFACT_VERSION="$KIVOU_HISTORICAL_ARTIFACT_VERSION" \
  KIVOU_QA_ORIGIN=https://staging.kivou.eu node <<'JS'
function requireTrue(value) {
  if (!value) throw new Error()
}

async function accountFingerprint(page, expectedFingerprint) {
  return page.evaluate(async (expected) => {
    const response = await fetch('/me', { credentials: 'same-origin' })
    if (response.status !== 200) throw new Error()
    const me = await response.json()
    if (typeof me.account_id !== 'string' || me.account_id.length === 0) {
      throw new Error()
    }
    const bytes = new TextEncoder().encode(me.account_id)
    const digest = await crypto.subtle.digest('SHA-256', bytes)
    const fingerprint = Array.from(new Uint8Array(digest))
      .map((value) => value.toString(16).padStart(2, '0'))
      .join('')
      .slice(0, 16)
    if (fingerprint !== expected) throw new Error()
    return true
  }, expectedFingerprint)
}

function waitForExactGetResponse(page, origin, expectedPath) {
  return page.waitForResponse((response) => {
    let url
    try {
      url = new URL(response.url())
    } catch {
      return false
    }
    return response.request().method() === 'GET' &&
      url.origin === origin &&
      `${url.pathname}${url.search}` === expectedPath
  })
}

async function run() {
  const { chromium } = require('playwright')
  const origin = process.env.KIVOU_QA_ORIGIN
  const expectedFingerprint = process.env.KIVOU_QA_DB_FINGERPRINT
  const storageState = process.env.KIVOU_QA_STORAGE_STATE
  const historicalSignalId = process.env.KIVOU_HISTORICAL_SIGNAL_ID
  const historicalArtifactId = process.env.KIVOU_HISTORICAL_ARTIFACT_ID
  const historicalArtifactVersion = Number.parseInt(
    process.env.KIVOU_HISTORICAL_ARTIFACT_VERSION || '', 10,
  )
  requireTrue(Boolean(origin && expectedFingerprint && storageState &&
    historicalSignalId && historicalArtifactId))
  requireTrue(/^[0-9a-f]{64}$/.test(historicalSignalId))
  requireTrue(/^[0-9a-f]{64}$/.test(historicalArtifactId))
  requireTrue(Number.isInteger(historicalArtifactVersion) &&
    historicalArtifactVersion >= 1)
  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext({ storageState })
    const page = await context.newPage()
    const errors = []
    const requests = []
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push('console')
    })
    page.on('pageerror', () => errors.push('pageerror'))
    page.on('requestfailed', () => errors.push('requestfailed'))
    page.on('response', (response) => {
      if (response.status() >= 500) errors.push('http5xx')
    })
    page.on('request', (request) => {
      let url
      try {
        url = new URL(request.url())
      } catch {
        errors.push('invalid-url')
        return
      }
      if (url.origin !== origin) errors.push('external-request')
      requests.push({
        method: request.method(),
        path: `${url.pathname}${url.search}`,
      })
    })
    await page.goto(`${origin}/app/signals`, { waitUntil: 'networkidle' })
    requireTrue(await accountFingerprint(page, expectedFingerprint))
    const historicalDetail = await page.evaluate(async ({
      signalId, artifactId, artifactVersion,
    }) => {
      const response = await fetch(
        `/signals/${encodeURIComponent(signalId)}` +
        `?presentation_artifact_id=${encodeURIComponent(artifactId)}`,
        { credentials: 'same-origin' },
      )
      if (response.status !== 200) throw new Error()
      const detail = await response.json()
      if (detail.signal_id !== signalId || !detail.presentation ||
          detail.presentation.artifact_id !== artifactId ||
          detail.presentation.version !== artifactVersion ||
          detail.presentation.status !== 'FALLBACK' ||
          detail.presentation.content?.variant !== 'FACTUAL_FALLBACK' ||
          typeof detail.presentation.content?.headline !== 'string' ||
          detail.presentation.content.headline.length === 0) throw new Error()
      return detail
    }, {
      signalId: historicalSignalId,
      artifactId: historicalArtifactId,
      artifactVersion: historicalArtifactVersion,
    })
    const historicalUrl = new URL(
      `/app/signals/${encodeURIComponent(historicalSignalId)}`, origin,
    )
    historicalUrl.searchParams.set('presentation_artifact_id', historicalArtifactId)
    const expectedHistoricalDetailPath =
      `/signals/${encodeURIComponent(historicalSignalId)}` +
      `?presentation_artifact_id=${encodeURIComponent(historicalArtifactId)}`
    const expectedHistoricalNotePath =
      `/signals/${encodeURIComponent(historicalSignalId)}/note`
    const historicalDetailResponsePromise = waitForExactGetResponse(
      page, origin, expectedHistoricalDetailPath,
    )
    const historicalNoteResponsePromise = waitForExactGetResponse(
      page, origin, expectedHistoricalNotePath,
    )
    const historicalRequestStart = requests.length
    await page.goto(historicalUrl.toString(), { waitUntil: 'networkidle' })
    await page.waitForURL((url) => (
      url.pathname === `/app/signals/${encodeURIComponent(historicalSignalId)}` &&
      url.searchParams.get('presentation_artifact_id') === historicalArtifactId &&
      Array.from(url.searchParams).length === 1
    ))
    const [historicalDetailResponse, historicalNoteResponse] = await Promise.all([
      historicalDetailResponsePromise,
      historicalNoteResponsePromise,
    ])
    requireTrue(historicalDetailResponse.status() === 200)
    requireTrue(historicalNoteResponse.status() === 200)
    const detailPane = page.locator(
      `[data-master-detail-pane="detail"]:visible`,
    )
    requireTrue(await detailPane.count() === 1)
    const headline = detailPane.getByText(
      historicalDetail.presentation.content.headline, { exact: true },
    )
    requireTrue(await headline.count() === 1)
    await headline.waitFor()
    requireTrue(requests.slice(historicalRequestStart).some(({ method, path }) => (
      method === 'GET' && path === expectedHistoricalDetailPath
    )))
    requireTrue(requests.slice(historicalRequestStart).some(({ method, path }) => (
      method === 'GET' && path === expectedHistoricalNotePath
    )))
    requireTrue(!requests.some(({ method }) => !['GET', 'HEAD'].includes(method)))
    requireTrue(errors.length === 0)
    await context.close()
  } finally {
    await browser.close()
  }
}

run()
  .then(() => console.log("card_historical_browser_ok"))
  .catch(() => {
    console.error("card_historical_browser_failed")
    process.exitCode = 1
  })
JS
    )
    kivou_audit_card_get_journal
    printf '%s\n' "card_historical_smoke_ok"
    KIVOU_HISTORICAL_SMOKE_STATUS=PASS
    KIVOU_ROLLOUT_STATUS=PASS
    ;;
  (*) exit 69 ;;
esac
export KIVOU_HISTORICAL_SMOKE_STATUS KIVOU_ROLLOUT_STATUS
~~~

## 9. Rollback applicatif

Préparer l'**application-only rollback** mais ne l'exécuter que sur un trigger
documenté : readiness perdue, 5xx répétés, mauvais SHA servi, SPA/assets cassés,
fuite de teaser, mismatch feed/détail ou smoke navigateur impossible. Une
approbation QA absente impose STOP, pas un rollback ni une activation IA.

Valider à nouveau les deux chemins capturés à l'étape 2. Le rollback frontend
est le switch atomique suivant; il conserve les deux releases :

~~~bash
ssh kivou-staging 'bash -s' -- \
  "$KIVOU_PREVIOUS_FRONTEND" "$KIVOU_FINAL_SHA" <<'REMOTE'
set -euo pipefail
KIVOU_PREVIOUS_FRONTEND=$1
KIVOU_FINAL_SHA=$2
case "$KIVOU_PREVIOUS_FRONTEND" in
  (/srv/kivou/releases/frontend-*) ;;
  (*) exit 69 ;;
esac
printf '%s\n' "$KIVOU_FINAL_SHA" | grep -Eq '^[0-9a-f]{40}$'
test -d "$KIVOU_PREVIOUS_FRONTEND"
test "$(cat /srv/kivou/frontend/KIVOU_RELEASE_SHA)" = "$KIVOU_FINAL_SHA"
KIVOU_FRONTEND_ROLLBACK_DIR=$(sudo mktemp -d \
  /srv/kivou/.kivou-frontend-next.XXXXXX)
sudo chmod 700 "$KIVOU_FRONTEND_ROLLBACK_DIR"
KIVOU_FRONTEND_ROLLBACK_DIR_REAL=$(sudo readlink -f \
  "$KIVOU_FRONTEND_ROLLBACK_DIR")
test "$KIVOU_FRONTEND_ROLLBACK_DIR_REAL" = "$KIVOU_FRONTEND_ROLLBACK_DIR"
case "$KIVOU_FRONTEND_ROLLBACK_DIR_REAL" in
  (/srv/kivou/.kivou-frontend-next.*) ;;
  (*) exit 69 ;;
esac
kivou_cleanup_frontend_rollback_dir() {
  case "$KIVOU_FRONTEND_ROLLBACK_DIR_REAL" in
    (/srv/kivou/.kivou-frontend-next.*) ;;
    (*) return 69 ;;
  esac
  sudo find "$KIVOU_FRONTEND_ROLLBACK_DIR_REAL" -depth -mindepth 1 -delete
  case "$KIVOU_FRONTEND_ROLLBACK_DIR_REAL" in
    (/srv/kivou/.kivou-frontend-next.*) ;;
    (*) return 69 ;;
  esac
  sudo rmdir "$KIVOU_FRONTEND_ROLLBACK_DIR_REAL"
}
trap kivou_cleanup_frontend_rollback_dir EXIT
KIVOU_FRONTEND_ROLLBACK="$KIVOU_FRONTEND_ROLLBACK_DIR/frontend.rollback"
sudo ln -s "$KIVOU_PREVIOUS_FRONTEND" "$KIVOU_FRONTEND_ROLLBACK"
test "$(sudo readlink -f "$KIVOU_FRONTEND_ROLLBACK")" = "$KIVOU_PREVIOUS_FRONTEND"
test "$(cat /srv/kivou/frontend/KIVOU_RELEASE_SHA)" = "$KIVOU_FINAL_SHA"
sudo mv -Tf "$KIVOU_FRONTEND_ROLLBACK" /srv/kivou/frontend
test "$(readlink -f /srv/kivou/frontend)" = "$KIVOU_PREVIOUS_FRONTEND"
mapfile -t KIVOU_PREVIOUS_ASSET_PATHS < <(
  grep -Eo '(src|href)="/[^"]+"' "$KIVOU_PREVIOUS_FRONTEND/index.html" |
    sed -E 's/^(src|href)="([^"]+)"$/\2/' | sort -u
)
test "${#KIVOU_PREVIOUS_ASSET_PATHS[@]}" -gt 0
for KIVOU_PATH in / /app/dashboard /app/companies /app/signals; do
  test "$(curl --silent --show-error --connect-timeout 2 --max-time 5 \
    --output /dev/null --write-out '%{http_code}' \
    --resolve staging.kivou.eu:443:127.0.0.1 \
    "https://staging.kivou.eu$KIVOU_PATH")" = 200
done
for KIVOU_PREVIOUS_ASSET_PATH in "${KIVOU_PREVIOUS_ASSET_PATHS[@]}"; do
  case "$KIVOU_PREVIOUS_ASSET_PATH" in
    (/assets/*|/reference/*) ;;
    (*) exit 69 ;;
  esac
  test -f "$KIVOU_PREVIOUS_FRONTEND$KIVOU_PREVIOUS_ASSET_PATH"
  test "$(curl --silent --show-error --connect-timeout 2 --max-time 5 \
    --output /dev/null --write-out '%{http_code}' \
    --resolve staging.kivou.eu:443:127.0.0.1 \
    "https://staging.kivou.eu$KIVOU_PREVIOUS_ASSET_PATH")" = 200
done
kivou_cleanup_frontend_rollback_dir
trap - EXIT
REMOTE
~~~

Pour le backend, lire l'état root-only sans l'afficher, en valider la forme et
les quatre valeurs contre les targets capturées, puis exécuter le bloc
autoritaire `Rollback applicatif préservant la sécurité` depuis le même SHA.
La commande concatène validation et bloc versionné dans un unique shell SSH;
aucun shell intermédiaire n'est permis :

~~~bash
set -euo pipefail
KIVOU_BACKEND_ROLLBACK_SCRIPT=$(
  sed -n 'p' <<'KIVOU_ROLLBACK_BOOTSTRAP'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_PREVIOUS_BACKEND=$3
case "$KIVOU_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
case "$KIVOU_PREVIOUS_BACKEND" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
printf '%s\n' "$KIVOU_FINAL_SHA" | grep -Eq '^[0-9a-f]{40}$'
KIVOU_ROLLOUT_STATE=/etc/kivou/kivou-safe-rollout.state
sudo test -f "$KIVOU_ROLLOUT_STATE"
sudo test ! -L "$KIVOU_ROLLOUT_STATE"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_STATE")" = "root:root:600"
KIVOU_ROLLOUT_STATE_CONTENT=$(sudo cat "$KIVOU_ROLLOUT_STATE")
test "$(grep -Ec '^KIVOU_(STAGING_HOST|SECURITY_RELEASE|PREVIOUS_RELEASE|RELEASE_SHA)=' \
  <<<"$KIVOU_ROLLOUT_STATE_CONTENT")" = 4
test "$(grep -Evc '^KIVOU_(STAGING_HOST|SECURITY_RELEASE|PREVIOUS_RELEASE|RELEASE_SHA)=' \
  <<<"$KIVOU_ROLLOUT_STATE_CONTENT")" = 0
unset KIVOU_STAGING_HOST KIVOU_SECURITY_RELEASE \
  KIVOU_PREVIOUS_RELEASE KIVOU_RELEASE_SHA
source /dev/stdin <<<"$KIVOU_ROLLOUT_STATE_CONTENT"
unset KIVOU_ROLLOUT_STATE_CONTENT
test "$KIVOU_SECURITY_RELEASE" = "$KIVOU_RELEASE_DIR"
test "$KIVOU_PREVIOUS_RELEASE" = "$KIVOU_PREVIOUS_BACKEND"
test "$KIVOU_RELEASE_SHA" = "$KIVOU_FINAL_SHA"
test "$KIVOU_STAGING_HOST" = "staging.kivou.eu"
KIVOU_ROLLBACK_BOOTSTRAP
  git show "$KIVOU_FINAL_SHA:ops/README.md" | awk '
    /^### Rollback applicatif préservant la sécurité$/ {
      heading = 1
      next
    }
    heading && /^~~~bash$/ {
      emit = 1
      next
    }
    emit && /^~~~$/ {
      complete = 1
      exit
    }
    emit { print }
    END { if (!heading || !complete) exit 69 }
  '
)
printf '%s\n' "$KIVOU_BACKEND_ROLLBACK_SCRIPT" | bash -n
printf '%s\n' "$KIVOU_BACKEND_ROLLBACK_SCRIPT" | ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "$KIVOU_PREVIOUS_BACKEND"
unset KIVOU_BACKEND_ROLLBACK_SCRIPT
~~~

Ce bloc démarre la release de sécurité sur green, prouve 8001, republie le
bundle sûr sous monitor, puis commute `/srv/kivou/app` vers le
`KIVOU_PREVIOUS_BACKEND` capturé — jamais vers un glob. STOP si le fichier
d'état, ses permissions, ses quatre clés, le SHA, l'hôte ou l'un des deux
targets ne correspondent pas exactement.

La base doit rester à `0028_card_presentation` : **ne pas exécuter de downgrade** automatiquement. La table additive et les artefacts factuels sont
conservés pour diagnostic; une modification de schéma demanderait une procédure
d'incident distincte et approuvée.

Après rollback, revalider `/srv/kivou/frontend`, `/srv/kivou/app`, les routes et
assets publics, readiness 8000, `/me=401`, nginx et la révision 0028.

## 10. Rapport de preuve

Le rapport final doit associer sans ambiguïté : SHA final `main`, run CI et
étapes, backup (nom/taille/SHA-256/TOC/restore), transition
`0027_signal_notes → 0028_card_presentation`, releases backend/frontend,
compteurs FR/EN, captures inspectées, matrice Dashboard/Entreprises/Signaux,
deep-links/Retour/focus/scroll/teaser/console, rollback targets et éventuel
rollback exécuté.

Valider et inscrire le statut historique et le statut global sans les
réinterpréter :

~~~bash
: "${KIVOU_HISTORICAL_SMOKE_STATUS:?STOP: historical smoke status absent}"
: "${KIVOU_ROLLOUT_STATUS:?STOP: rollout status absent}"
case "$KIVOU_HISTORICAL_SMOKE_STATUS:$KIVOU_ROLLOUT_STATUS" in
  (PASS:PASS|STOP_NON_EXECUTABLE:STOP_INCOMPLETE) ;;
  (*) exit 69 ;;
esac
printf 'historical_smoke_status=%s rollout_status=%s\n' \
  "$KIVOU_HISTORICAL_SMOKE_STATUS" "$KIVOU_ROLLOUT_STATUS"
~~~

Si `KIVOU_HISTORICAL_SMOKE_STATUS != PASS`, toute formulation présentant le
rollout global, le parcours historique ou la livraison comme complète est
**interdite**. Le rapport reste `rollout_status=STOP_INCOMPLETE`, tout en
conservant les preuves courantes, les cibles de rollback et leur préparation.
L'absence d'historique légitime n'autorise aucune fabrication de donnée.

Le rapport doit aussi porter la ligne :

```text
Production : aucun déploiement, aucune mutation.
```

Terminer par :

```text
Activation IA : DÉSACTIVÉE — aucun provider, modèle, prompt, QA provider ou worker live approuvé ; staging limité à l’architecture et aux FALLBACK/FACTUAL_FALLBACK factuels hors GET.
```
