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

Le chemin normal reste le défaut. Pour reprendre exclusivement le rollout
arrêté au SHA `51202525d3163aeac259acbf9ac23086ed2cc256`, l'opérateur doit
exécuter explicitement `export KIVOU_ROLLOUT_PATH=resume_51202525` et fournir le
chemin absolu du fichier privé `rollout-stop.txt` via
`KIVOU_RECOVERY_STOP_FILE`. Ne jamais déduire automatiquement le mode de reprise
de l'état de staging.

~~~bash
set -euo pipefail
KIVOU_REPOSITORY=bruppacherrodrigue-art/Kivou

git fetch origin main
KIVOU_FINAL_SHA=$(git rev-parse origin/main)
printf '%s\n' "$KIVOU_FINAL_SHA" | grep -Eq '^[0-9a-f]{40}$'
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
KIVOU_ROLLOUT_PATH=${KIVOU_ROLLOUT_PATH:-initial_0027}
KIVOU_RECOVERY_SOURCE_SHA=51202525d3163aeac259acbf9ac23086ed2cc256
KIVOU_RECOVERY_DIFF=()
case "$KIVOU_ROLLOUT_PATH" in
  (initial_0027)
    KIVOU_EXPECTED_START_REVISION=0027_signal_notes
    ;;
  (resume_51202525)
    KIVOU_EXPECTED_START_REVISION=0028_card_presentation
    test "$KIVOU_FINAL_SHA" != "$KIVOU_RECOVERY_SOURCE_SHA"
    git merge-base --is-ancestor \
      "$KIVOU_RECOVERY_SOURCE_SHA" "$KIVOU_FINAL_SHA"
    mapfile -t KIVOU_RECOVERY_DIFF < <(
      git diff --name-only "$KIVOU_RECOVERY_SOURCE_SHA" "$KIVOU_FINAL_SHA"
    )
    mapfile -t KIVOU_RECOVERY_EXPECTED_DIFF < <(printf '%s\n' \
      src/signals/card_intelligence/backfill.py \
      src/signals/card_intelligence/cli.py \
      tests/test_card_intelligence_backfill.py \
      tests/test_card_presentation_runbook.py \
      docs/runbooks/11-staging-card-presentation-rollout.md | LC_ALL=C sort)
    mapfile -t KIVOU_RECOVERY_DIFF < <(
      printf '%s\n' "${KIVOU_RECOVERY_DIFF[@]}" | LC_ALL=C sort
    )
    test "${#KIVOU_RECOVERY_DIFF[@]}" -eq 5
    test "${KIVOU_RECOVERY_DIFF[*]}" = "${KIVOU_RECOVERY_EXPECTED_DIFF[*]}"
    unset KIVOU_RECOVERY_EXPECTED_DIFF
    ;;
  (*) exit 69 ;;
esac
test "$(git rev-parse 'origin/main^{tree}')" = \
  "$(gh api "repos/$KIVOU_REPOSITORY/git/commits/$KIVOU_FINAL_SHA" --jq .tree.sha)"

KIVOU_CI_RUN_ID=$(gh run list --repo "$KIVOU_REPOSITORY" \
  --workflow CI --branch main --commit "$KIVOU_FINAL_SHA" \
  --event push --status success --limit 1 \
  --json databaseId,headSha,conclusion \
  --jq '.[0].databaseId')
test -n "$KIVOU_CI_RUN_ID"
readonly KIVOU_ROLLOUT_PATH KIVOU_EXPECTED_START_REVISION
readonly KIVOU_RECOVERY_SOURCE_SHA
readonly -a KIVOU_RECOVERY_DIFF

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
if test "$KIVOU_ROLLOUT_PATH" = resume_51202525; then
  test "${#KIVOU_RECOVERY_DIFF[@]}" -eq 5
fi
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
kivou_validate_recovery_stop_file() {
  case "$KIVOU_RECOVERY_STOP_FILE" in
    (/*/rollout-stop.txt) ;;
    (*) return 69 ;;
  esac
  test -f "$KIVOU_RECOVERY_STOP_FILE"
  test ! -L "$KIVOU_RECOVERY_STOP_FILE"
  KIVOU_RECOVERY_STOP_FILE_REAL=$(readlink -f \
    "$KIVOU_RECOVERY_STOP_FILE")
  test "$KIVOU_RECOVERY_STOP_FILE_REAL" = "$KIVOU_RECOVERY_STOP_FILE"
  test "$(stat -c '%U:%a' "$KIVOU_RECOVERY_STOP_FILE_REAL")" = \
    "$(id -un):600"
  case "$KIVOU_RECOVERY_STOP_FILE_REAL" in
    ("$KIVOU_OPERATOR_ROOT_REAL"|"$KIVOU_OPERATOR_ROOT_REAL"/*) return 69 ;;
    (*) ;;
  esac

  declare -A KIVOU_RECOVERY_STOP_KEYS=()
  while IFS= read -r KIVOU_RECOVERY_STOP_LINE || \
    test -n "$KIVOU_RECOVERY_STOP_LINE"; do
    printf '%s\n' "$KIVOU_RECOVERY_STOP_LINE" | \
      grep -Eq '^[a-z][a-z0-9_]*=[A-Za-z0-9_.-]+$' || return 69
    KIVOU_RECOVERY_STOP_KEY=${KIVOU_RECOVERY_STOP_LINE%%=*}
    test -z "${KIVOU_RECOVERY_STOP_KEYS[$KIVOU_RECOVERY_STOP_KEY]+x}" || \
      return 69
    case "$KIVOU_RECOVERY_STOP_LINE" in
      (status=STOP_BACKFILL_SCAN_TRUNCATED) ;;
      ("sha=$KIVOU_RECOVERY_SOURCE_SHA") ;;
      (database_revision=0028_card_presentation) ;;
      (backend_release=backend-20260831T221628Z-51202525d316) ;;
      (frontend_release=frontend-20260831T221628Z-51202525d316) ;;
      (fr_factual_artifacts=8) ;;
      (en_factual_artifacts=0) ;;
      (other_tenant_artifacts=0) ;;
      (ai_bound_artifacts=0) ;;
      (current_owned_signals=790) ;;
      (get_candidate_scan_cap=500) ;;
      (get_page_items=8) ;;
      (get_page_excluded_without_display_name=492) ;;
      (get_page_scan_truncated=1) ;;
      (offline_diagnostic_cap=1000) ;;
      (offline_diagnostic_items=44) ;;
      (offline_diagnostic_scan_truncated=0) ;;
      (production_mutated=0) ;;
      (*) return 69 ;;
    esac
    KIVOU_RECOVERY_STOP_KEYS[$KIVOU_RECOVERY_STOP_KEY]=1
  done < "$KIVOU_RECOVERY_STOP_FILE_REAL"
  test "${#KIVOU_RECOVERY_STOP_KEYS[@]}" -eq 18
  unset KIVOU_RECOVERY_STOP_KEY KIVOU_RECOVERY_STOP_KEYS \
    KIVOU_RECOVERY_STOP_LINE
  KIVOU_ORIGINAL_ROLLOUT_STATUS=STOP_FAIL_CLOSED
}
case "$KIVOU_ROLLOUT_PATH" in
  (initial_0027)
    KIVOU_ORIGINAL_ROLLOUT_STATUS=NOT_APPLICABLE_INITIAL_ROLLOUT
    ;;
  (resume_51202525)
    : "${KIVOU_RECOVERY_STOP_FILE:?STOP: rollout-stop.txt opérateur requis}"
    kivou_validate_recovery_stop_file
    ;;
  (*) exit 69 ;;
esac
readonly KIVOU_ORIGINAL_ROLLOUT_STATUS
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
  ssh kivou-staging 'bash -s' -- \
    "$KIVOU_EXPECTED_START_REVISION" "$KIVOU_ROLLOUT_PATH" \
    "$KIVOU_RECOVERY_SOURCE_SHA" <<'REMOTE'
set -euo pipefail
KIVOU_EXPECTED_START_REVISION=$1
KIVOU_ROLLOUT_PATH=$2
KIVOU_RECOVERY_SOURCE_SHA=$3
case "$KIVOU_EXPECTED_START_REVISION" in
  (0027_signal_notes|0028_card_presentation) ;;
  (*) exit 69 ;;
esac
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
case "$KIVOU_ROLLOUT_PATH" in
  (initial_0027) ;;
  (resume_51202525)
    test "$KIVOU_PREVIOUS_BACKEND_SHA" = "$KIVOU_RECOVERY_SOURCE_SHA"
    test "$(cat "$KIVOU_PREVIOUS_FRONTEND/KIVOU_RELEASE_SHA")" = \
      "$KIVOU_RECOVERY_SOURCE_SHA"
    ;;
  (*) exit 69 ;;
esac

KIVOU_CURRENT_REVISION=$(sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-preflight-$$" \
  --property=Type=oneshot --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_PREVIOUS_BACKEND" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --setenv="KIVOU_EXPECTED_START_REVISION=$KIVOU_EXPECTED_START_REVISION" \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  --property=ProtectHome=yes \
  -- "$KIVOU_PREVIOUS_BACKEND/.venv/bin/python" -c \
  'import os; from signals.persistence.database import create_database_engine,current_revision; engine=create_database_engine(); revision=current_revision(engine); expected_revision=os.environ["KIVOU_EXPECTED_START_REVISION"]; assert revision == expected_revision, (revision, expected_revision); print(revision)')
test "$KIVOU_CURRENT_REVISION" = "$KIVOU_EXPECTED_START_REVISION"

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
test "$KIVOU_CURRENT_REVISION" = "$KIVOU_EXPECTED_START_REVISION"
~~~

Avant la première mutation de staging, valider l'approbation QA et sa session
protégée avec le backend actuellement servi. Ce garde-fou partagé ne fait que
des `SELECT` dans une transaction explicitement read-only et des requêtes HTTP
`GET/HEAD`; il n'exécute aucun backfill, provider ou worker. L'installation
locale des dépendances navigateur ne touche pas staging. Garder la fonction
dans le même shell : elle sera rejouée juste avant chaque backfill en étape 7.

~~~bash
KIVOU_QA_READ_DATE=$(date -u +%F)
printf '%s\n' "$KIVOU_QA_READ_DATE" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
: "${KIVOU_QA_STORAGE_STATE:?STOP: storage state QA protégé non fourni}"
printf '%s\n' "$KIVOU_QA_STORAGE_STATE" | grep -Eq '^/[A-Za-z0-9._/-]+$'
test -f "$KIVOU_QA_STORAGE_STATE"
test ! -L "$KIVOU_QA_STORAGE_STATE"
KIVOU_QA_STORAGE_STATE_REAL=$(readlink -f "$KIVOU_QA_STORAGE_STATE")
test "$KIVOU_QA_STORAGE_STATE_REAL" = "$KIVOU_QA_STORAGE_STATE"
test "$(stat -c '%U:%a' "$KIVOU_QA_STORAGE_STATE_REAL")" = "$(id -un):600"
test -r "$KIVOU_QA_STORAGE_STATE_REAL"
KIVOU_OPERATOR_ROOT=$(git rev-parse --show-toplevel)
case "$KIVOU_QA_STORAGE_STATE_REAL" in
  ("$KIVOU_OPERATOR_ROOT"/*) exit 69 ;;
  (*) ;;
esac
(
  cd frontend
  npm ci
  npx playwright install chromium
)

kivou_validate_qa_read_only() {
  KIVOU_QA_APP_DIR=$1
  case "$KIVOU_QA_APP_DIR" in
    (/srv/kivou/releases/backend-*) ;;
    (*) return 69 ;;
  esac
  KIVOU_QA_SCOPE_SUMMARY=$(ssh kivou-staging 'bash -s' -- \
    "$KIVOU_QA_APP_DIR" "$KIVOU_QA_READ_DATE" <<'REMOTE'
set -euo pipefail
KIVOU_QA_APP_DIR=$1
KIVOU_QA_READ_DATE=$2
KIVOU_QA_ENV=/etc/kivou/card-presentation-qa.env
case "$KIVOU_QA_APP_DIR" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
test -L /srv/kivou/app
KIVOU_QA_SERVED_APP=$(readlink -f /srv/kivou/app)
case "$KIVOU_QA_SERVED_APP" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
test -d "$KIVOU_QA_SERVED_APP"
test "$KIVOU_QA_SERVED_APP" = "$KIVOU_QA_APP_DIR"
printf '%s\n' "$KIVOU_QA_READ_DATE" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
test "$(hostname -s)" = "kivou-staging-01"
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
  --unit="kivou-card-qa-read-only-$$" --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_QA_APP_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile="$KIVOU_QA_ENV" \
  -- "$KIVOU_QA_APP_DIR/.venv/bin/python" - <<'PY'
import hashlib
import os
import sys

import sqlalchemy as sa

from signals.persistence.database import create_database_engine


def main() -> None:
    account_id = os.environ["KIVOU_CARD_QA_ACCOUNT_ID"]
    engine = create_database_engine()
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
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
    print(f"qa_read_only_scope_ok fingerprint={fingerprint}")


try:
    main()
except Exception:
    print("qa_read_only_scope_failed", file=sys.stderr)
    raise SystemExit(1) from None
PY
REMOTE
  )
  printf '%s\n' "$KIVOU_QA_SCOPE_SUMMARY" | \
    grep -Eq '^qa_read_only_scope_ok fingerprint=[0-9a-f]{16}$'
  KIVOU_QA_READ_ONLY_FINGERPRINT=$(printf '%s\n' "$KIVOU_QA_SCOPE_SUMMARY" | \
    sed -E 's/^qa_read_only_scope_ok fingerprint=([0-9a-f]{16})$/\1/')
  unset KIVOU_QA_SCOPE_SUMMARY
  printf '%s\n' "$KIVOU_QA_READ_ONLY_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'
  if test -z "${KIVOU_QA_APPROVED_FINGERPRINT+x}"; then
    KIVOU_QA_APPROVED_FINGERPRINT=$KIVOU_QA_READ_ONLY_FINGERPRINT
  else
    test "$KIVOU_QA_READ_ONLY_FINGERPRINT" = \
      "$KIVOU_QA_APPROVED_FINGERPRINT"
  fi
  export KIVOU_QA_APPROVED_FINGERPRINT
  readonly KIVOU_QA_APPROVED_FINGERPRINT

  (
    cd frontend
    KIVOU_QA_STORAGE_STATE="$KIVOU_QA_STORAGE_STATE_REAL" \
    KIVOU_QA_READ_DATE="$KIVOU_QA_READ_DATE" \
    KIVOU_QA_ORIGIN=https://staging.kivou.eu node <<'JS'
async function run() {
  const { chromium } = require('playwright')
  const { createHash } = require('node:crypto')
  const origin = process.env.KIVOU_QA_ORIGIN
  const expectedFingerprint = process.env.KIVOU_QA_APPROVED_FINGERPRINT
  const storageState = process.env.KIVOU_QA_STORAGE_STATE
  if (!origin || !expectedFingerprint || !storageState) {
    throw new Error()
  }
  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext({ storageState })
    const requests = [{ method: 'GET', path: '/me' }]
    const meResponse = await context.request.get(`${origin}/me`)
    if (meResponse.status() !== 200) throw new Error()
    const me = await meResponse.json()
    if (typeof me.account_id !== 'string' || me.account_id.length === 0) {
      throw new Error()
    }
    const fingerprint = createHash('sha256')
      .update(me.account_id, 'utf8')
      .digest('hex')
      .slice(0, 16)
    if (fingerprint !== expectedFingerprint) throw new Error()
    const onlyReadMethods =
      !requests.some(({ method }) => !['GET', 'HEAD'].includes(method))
    if (!onlyReadMethods || requests.length !== 1 || requests[0].path !== '/me') {
      throw new Error()
    }
    await context.close()
  } finally {
    await browser.close()
  }
}

run()
  .then(() => console.log("qa_read_only_gate_ok"))
  .catch(() => {
    console.error("qa_read_only_gate_failed")
    process.exitCode = 1
  })
JS
  )
  unset KIVOU_QA_READ_ONLY_FINGERPRINT KIVOU_QA_APP_DIR
}
# Fin du garde-fou QA partagé en lecture seule.

kivou_validate_qa_read_only "$KIVOU_PREVIOUS_BACKEND"

kivou_capture_recovery_fr_snapshot() {
  KIVOU_RECOVERY_APP_DIR=$1
  KIVOU_RECOVERY_SNAPSHOT_PHASE=${2:-post_fr}
  case "$KIVOU_RECOVERY_APP_DIR" in
    (/srv/kivou/releases/backend-*) ;;
    (*) return 69 ;;
  esac
  case "$KIVOU_RECOVERY_SNAPSHOT_PHASE" in
    (baseline|post_fr|post_en) ;;
    (*) return 69 ;;
  esac
  ssh kivou-staging 'bash -s' -- \
    "$KIVOU_RECOVERY_APP_DIR" "$KIVOU_RECOVERY_SNAPSHOT_PHASE" \
    "$KIVOU_QA_APPROVED_FINGERPRINT" <<'REMOTE'
set -euo pipefail
KIVOU_RECOVERY_APP_DIR=$1
KIVOU_RECOVERY_SNAPSHOT_PHASE=$2
KIVOU_QA_APPROVED_FINGERPRINT=$3
KIVOU_QA_ENV=/etc/kivou/card-presentation-qa.env
case "$KIVOU_RECOVERY_APP_DIR" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
case "$KIVOU_RECOVERY_SNAPSHOT_PHASE" in
  (baseline|post_fr|post_en) ;;
  (*) exit 69 ;;
esac
test "$(readlink -f /srv/kivou/app)" = "$KIVOU_RECOVERY_APP_DIR"
test -f "$KIVOU_QA_ENV"
test ! -L "$KIVOU_QA_ENV"
test "$(stat -c '%U:%G:%a' "$KIVOU_QA_ENV")" = "root:kivou:640"
sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-recovery-snapshot-$$" --property=Type=oneshot \
  --property=RuntimeMaxSec=5min \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RECOVERY_APP_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile="$KIVOU_QA_ENV" \
  --setenv="KIVOU_RECOVERY_SNAPSHOT_PHASE=$KIVOU_RECOVERY_SNAPSHOT_PHASE" \
  --setenv="KIVOU_QA_APPROVED_FINGERPRINT=$KIVOU_QA_APPROVED_FINGERPRINT" \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  --property=ProtectHome=yes \
  -- "$KIVOU_RECOVERY_APP_DIR/.venv/bin/python" - <<'PY'
import datetime as dt
import hashlib
import hmac
import json
import os
import sys

import sqlalchemy as sa

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    PresentationVariant,
)
from signals.card_intelligence.store import published_for_signals
from signals.feed.query import feed_page
from signals.persistence.database import create_database_engine, current_revision


def main() -> None:
    account_id = os.environ["KIVOU_CARD_QA_ACCOUNT_ID"]
    phase = os.environ["KIVOU_RECOVERY_SNAPSHOT_PHASE"]
    expected_fingerprint = os.environ["KIVOU_QA_APPROVED_FINGERPRINT"]
    actual_fingerprint = hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:16]
    assert hmac.compare_digest(actual_fingerprint, expected_fingerprint)
    engine = create_database_engine()
    assert current_revision(engine) == "0028_card_presentation"
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        rows = connection.execute(sa.text(
            "SELECT artifact_id, signal_key, signal_revision, target_icp_id, "
            "target_icp_revision, language, version, payload, payload_variant, "
            "qa_status, prompt_version, model_id, provider, qa_model_id, "
            "qa_provider, superseded_at "
            "FROM card_presentation_artifact "
            "WHERE account_id=:account_id AND published_at IS NOT NULL "
            "ORDER BY artifact_id"
        ), {"account_id": account_id}).mappings().all()
        foreign_rows = connection.scalar(sa.text(
            "SELECT count(*) FROM card_presentation_artifact "
            "WHERE account_id<>:account_id"
        ), {"account_id": account_id})
        total_rows = connection.scalar(sa.text(
            "SELECT count(*) FROM card_presentation_artifact "
            "WHERE account_id=:account_id"
        ), {"account_id": account_id})
        ai_rows = connection.scalar(sa.text(
            "SELECT count(*) FROM card_presentation_artifact "
            "WHERE prompt_version IS NOT NULL OR model_id IS NOT NULL "
            "OR provider IS NOT NULL OR qa_model_id IS NOT NULL "
            "OR qa_provider IS NOT NULL OR qa_status='PASS' "
            "OR payload_variant='FULL'"
        ))
        duplicates = connection.scalar(sa.text(
            "SELECT count(*) FROM ("
            "SELECT 1 FROM card_presentation_artifact "
            "WHERE published_at IS NOT NULL AND superseded_at IS NULL "
            "GROUP BY account_id, signal_key, target_icp_id, artifact_kind, language "
            "HAVING count(*)>1) AS active_duplicates"
        ))
        page = feed_page(
            connection,
            account_id=account_id,
            as_of=dt.date(2026, 8, 31),
            freshness="all",
            limit=50,
            offset=0,
            scan_cap=1000,
        )
        assert page.limit == 50
        assert page.offset == 0
        assert 1 <= len(page.items) <= 50
        assert page.has_more is False
        assert page.scan_truncated is False
        page_signal_revisions = {
            item.signal.signal_key: item.signal.revision
            for item in page.items
        }
        binding_rows = connection.execute(sa.text(
            "SELECT signal.signal_key, signal.revision, "
            "signal.target_icp_id, signal.target_icp_revision "
            "FROM materialized_signal AS signal "
            "JOIN target_icp AS icp "
            "ON icp.target_icp_id=signal.target_icp_id "
            "WHERE icp.account_id=:account_id "
            "AND icp.status='active' AND icp.plan_limit_code IS NULL "
            "AND signal.invalidated_at IS NULL "
            "AND signal.target_icp_revision=icp.matching_revision"
        ), {"account_id": account_id}).mappings().all()
        page_authorities = {
            row["signal_key"]: (
                row["revision"],
                row["target_icp_id"],
                row["target_icp_revision"],
            )
            for row in binding_rows
            if row["signal_key"] in page_signal_revisions
        }
        assert len(page_authorities) == len(page.items)
        assert set(page_authorities) == set(page_signal_revisions)
        assert all(
            revision == page_signal_revisions[signal_key]
            for signal_key, (
                revision,
                _target_icp_id,
                _target_revision,
            ) in page_authorities.items()
        )
        page_bindings = {
            signal_key: (signal_revision, target_icp_revision)
            for signal_key, (
                signal_revision,
                _target_icp_id,
                target_icp_revision,
            ) in page_authorities.items()
        }
        current_by_language = {}
        for language in ("fr", "en"):
            current = published_for_signals(
                connection,
                account_id=account_id,
                bindings=page_bindings,
                language=language,
            )
            current_by_language[language] = current
            assert all(
                presentation.status == "FALLBACK"
                and presentation.content.variant
                is PresentationVariant.FACTUAL_FALLBACK
                for presentation in current.values()
            )
    assert foreign_rows == 0
    assert ai_rows == 0
    assert duplicates == 0
    assert all(row["qa_status"] == "FALLBACK" for row in rows)
    assert all(row["payload_variant"] == "FACTUAL_FALLBACK" for row in rows)
    ai_fields = ("prompt_version", "model_id", "provider", "qa_model_id", "qa_provider")
    assert all(row[field] is None for field in ai_fields for row in rows)
    payloads = [CardPresentationPayload.from_json_value(row["payload"]) for row in rows]
    for payload in payloads:
        assert payload.variant is PresentationVariant.FACTUAL_FALLBACK
        assert payload.claims
        assert all(claim.evidence_refs for claim in payload.claims)
    active_rows = [row for row in rows if row["superseded_at"] is None]
    active_ids = {
        language: sorted(
            row["artifact_id"]
            for row in active_rows
            if row["language"] == language
        )
        for language in ("fr", "en")
    }
    current_ids = {
        language: sorted(
            presentation.artifact_id
            for presentation in current_by_language[language].values()
        )
        for language in ("fr", "en")
    }
    active_counts = {
        language: len(active_ids[language]) for language in ("fr", "en")
    }
    current_counts = {
        language: len(current_ids[language]) for language in ("fr", "en")
    }
    active_digests = {
        language: hashlib.sha256(json.dumps(
            active_ids[language], separators=(",", ":")
        ).encode("ascii")).hexdigest()
        for language in ("fr", "en")
    }
    current_digests = {
        language: hashlib.sha256(json.dumps(
            current_ids[language], separators=(",", ":")
        ).encode("ascii")).hexdigest()
        for language in ("fr", "en")
    }
    page_signal_keys = set(page_bindings)
    active_outside_candidate_counts = {
        language: sum(
            row["signal_key"] not in page_signal_keys
            for row in active_rows
            if row["language"] == language
        )
        for language in ("fr", "en")
    }
    candidate_binding_digest = hashlib.sha256(json.dumps(sorted(
        (signal_key, signal_revision, target_icp_revision)
        for signal_key, (
            signal_revision,
            target_icp_revision,
        ) in page_bindings.items()
    ), separators=(",", ":")).encode("ascii")).hexdigest()
    current_artifact_ids = {
        artifact_id for ids in current_ids.values() for artifact_id in ids
    }

    def artifact_state(row) -> str:
        if row["superseded_at"] is not None:
            return "superseded"
        authority = page_authorities.get(row["signal_key"])
        assert authority is not None
        signal_revision, target_icp_id, target_icp_revision = authority
        assert row["target_icp_id"] == target_icp_id
        assert row["target_icp_revision"] == target_icp_revision
        if row["artifact_id"] in current_artifact_ids:
            assert row["signal_revision"] == signal_revision
            return "current"
        assert row["signal_revision"] != signal_revision
        return "signal_revision_changed"

    artifacts = [
        {
            "artifact_id": row["artifact_id"],
            "language": row["language"],
            "version": row["version"],
            "signal_revision": row["signal_revision"],
            "target_icp_revision": row["target_icp_revision"],
            "state": artifact_state(row),
            "payload_sha256": hashlib.sha256(
                json.dumps(row["payload"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
        for row in rows
    ]
    if phase == "baseline":
        assert len(artifacts) == 8
        assert total_rows == 8
        assert active_counts == {"fr": 8, "en": 0}
        assert current_counts["en"] == 0
        assert 0 <= current_counts["fr"] <= 8
        assert sum(
            artifact["state"] == "signal_revision_changed"
            for artifact in artifacts
        ) == 8 - current_counts["fr"]
        assert all(
            artifact["state"] in ("current", "signal_revision_changed")
            for artifact in artifacts
        )
        assert active_outside_candidate_counts == {"fr": 0, "en": 0}
        assert all(row["language"] == "fr" for row in rows)
    print(json.dumps({
        "candidate_count": len(page_bindings),
        "candidate_binding_digest": candidate_binding_digest,
        "active_counts": active_counts,
        "active_digests": active_digests,
        "current_counts": current_counts,
        "current_digests": current_digests,
        "active_outside_candidate_counts": active_outside_candidate_counts,
        "active_artifact_ids": active_ids,
        "artifacts": artifacts,
    }, sort_keys=True, separators=(",", ":")))


try:
    main()
except Exception:
    print("recovery_snapshot_failed", file=sys.stderr)
    raise SystemExit(1) from None
PY
REMOTE
}

if test "$KIVOU_ROLLOUT_PATH" = resume_51202525; then
  KIVOU_RECOVERY_BASELINE="$KIVOU_EVIDENCE_DIR/recovery-fr-baseline.json"
  test ! -e "$KIVOU_RECOVERY_BASELINE"
  KIVOU_RECOVERY_BASELINE_PAYLOAD=$(kivou_capture_recovery_fr_snapshot \
    "$KIVOU_PREVIOUS_BACKEND" baseline)
  printf '%s\n' "$KIVOU_RECOVERY_BASELINE_PAYLOAD" > \
    "$KIVOU_RECOVERY_BASELINE"
  unset KIVOU_RECOVERY_BASELINE_PAYLOAD
  chmod 600 "$KIVOU_RECOVERY_BASELINE"
  test ! -L "$KIVOU_RECOVERY_BASELINE"
  test "$(stat -c '%U:%a' "$KIVOU_RECOVERY_BASELINE")" = "$(id -un):600"
  jq -e '
    .candidate_count >= 8 and .candidate_count <= 50
    and (.candidate_binding_digest | test("^[0-9a-f]{64}$"))
    and .active_counts == {"en":0,"fr":8}
    and .current_counts.en == 0
    and .current_counts.fr >= 0 and .current_counts.fr <= 8
    and .active_outside_candidate_counts == {"en":0,"fr":0}
    and (.active_artifact_ids.en | length) == 0
    and (.active_artifact_ids.fr | length) == 8
    and (.artifacts | length) == 8
    and all(.artifacts[];
      .language == "fr"
      and (.artifact_id | test("^[0-9a-f]{64}$"))
      and (.version | type == "number" and . >= 1)
      and (.signal_revision | type == "number" and . >= 1)
      and (.target_icp_revision | type == "number" and . >= 1)
      and (.state == "current" or .state == "signal_revision_changed")
      and (.payload_sha256 | test("^[0-9a-f]{64}$")))
    and ([.artifacts[] | select(.state == "signal_revision_changed")] | length)
      == (8 - .current_counts.fr)
  ' \
    "$KIVOU_RECOVERY_BASELINE" >/dev/null
  KIVOU_RECOVERY_BASELINE_SHA256=$(sha256sum \
    "$KIVOU_RECOVERY_BASELINE" | awk '{print $1}')
  printf '%s\n' "$KIVOU_RECOVERY_BASELINE_SHA256" | \
    grep -Eq '^[0-9a-f]{64}$'
  KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST=$(jq -j -c \
    '[.artifacts[].artifact_id] | sort' "$KIVOU_RECOVERY_BASELINE" | sha256sum | \
    awk '{print $1}')
  printf '%s\n' "$KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST" | \
    grep -Eq '^[0-9a-f]{64}$'
fi
~~~

Conserver ces deux chemins exacts. Ne jamais redécouvrir un rollback target par
un glob ou par le seul suffixe du SHA.

## 3. Sauvegarder, lister et restaurer dans une base scratch unique

Cette étape produit une sauvegarde fraîche, en vérifie l'archive, la restaure
réellement et supprime uniquement la base scratch validée après le succès. En
cas d'échec avant la suppression, STOP et faire qualifier la base scratch
exacte; ne lancer aucun nettoyage générique.

~~~bash
ssh kivou-staging 'bash -s' -- \
  "$KIVOU_FINAL_SHORT" "$KIVOU_EXPECTED_START_REVISION" <<'REMOTE'
set -euo pipefail
cd /srv/kivou
KIVOU_FINAL_SHORT=$1
KIVOU_EXPECTED_START_REVISION=$2
printf '%s\n' "$KIVOU_FINAL_SHORT" | grep -Eq '^[0-9a-f]{12}$'
case "$KIVOU_EXPECTED_START_REVISION" in
  (0027_signal_notes|0028_card_presentation) ;;
  (*) exit 69 ;;
esac
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

KIVOU_RESTORED_REVISION=$(sudo -u postgres psql -X -qAt \
  --dbname="$KIVOU_RESTORE_DB" --set=ON_ERROR_STOP=1 \
  -c 'SELECT version_num FROM alembic_version')
test "$KIVOU_RESTORED_REVISION" = "$KIVOU_EXPECTED_START_REVISION"
KIVOU_RESTORE_TABLES=(
  account target_icp materialized_signal contract_award alembic_version
)
if test "$KIVOU_EXPECTED_START_REVISION" = 0028_card_presentation; then
  KIVOU_RESTORE_TABLES+=(card_presentation_artifact)
fi
for KIVOU_TABLE in "${KIVOU_RESTORE_TABLES[@]}"; do
  KIVOU_RESTORE_TABLE_COUNT=$(kivou_restore_table_count)
  test "$KIVOU_RESTORE_TABLE_COUNT" = 1
  unset KIVOU_RESTORE_TABLE_COUNT
  KIVOU_TABLE_COUNT=$(sudo -u postgres psql -At -d "$KIVOU_RESTORE_DB" \
    -c "SELECT count(*) FROM $KIVOU_TABLE")
  printf '%s\n' "$KIVOU_TABLE_COUNT" | grep -Eq '^[0-9]+$'
done
if test "$KIVOU_EXPECTED_START_REVISION" = 0028_card_presentation; then
  KIVOU_RESTORE_CARD_INVENTORY=$(sudo -u postgres psql -X -qAt \
    --dbname="$KIVOU_RESTORE_DB" --set=ON_ERROR_STOP=1 <<'SQL'
WITH duplicate_groups AS (
  SELECT 1
  FROM card_presentation_artifact
  WHERE published_at IS NOT NULL AND superseded_at IS NULL
  GROUP BY account_id, signal_key, target_icp_id, artifact_kind, language
  HAVING count(*) > 1
)
SELECT
  count(*)::text || '|' ||
  count(*) FILTER (WHERE
    language = 'fr' AND published_at IS NOT NULL AND superseded_at IS NULL
    AND qa_status = 'FALLBACK' AND payload_variant = 'FACTUAL_FALLBACK'
  )::text || '|' ||
  count(*) FILTER (WHERE language = 'en')::text || '|' ||
  count(*) FILTER (WHERE
    prompt_version IS NOT NULL OR model_id IS NOT NULL OR provider IS NOT NULL
    OR qa_model_id IS NOT NULL OR qa_provider IS NOT NULL OR qa_status = 'PASS'
    OR payload_variant = 'FULL'
  )::text || '|' ||
  count(DISTINCT account_id)::text || '|' ||
  (SELECT count(*) FROM duplicate_groups)::text
FROM card_presentation_artifact;
SQL
  )
  test "$KIVOU_RESTORE_CARD_INVENTORY" = "8|8|0|0|1|0"
  unset KIVOU_RESTORE_CARD_INVENTORY
fi
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

printf 'backup_file=%s\nbackup_bytes=%s\nbackup_sha256=%s\ntoc_lines=%s\nrestore_revision=%s\nrestore_size_positive=1\n' \
  "$(basename "$KIVOU_BACKUP_FILE")" "$KIVOU_BACKUP_BYTES" \
  "$KIVOU_BACKUP_SHA" "$KIVOU_BACKUP_TOC_LINES" \
  "$KIVOU_RESTORED_REVISION"
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
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "$KIVOU_ROLLOUT_PATH" <<'REMOTE'
set -euo pipefail
cd /srv/kivou
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_ROLLOUT_PATH=$3
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
  --setenv="KIVOU_ROLLOUT_PATH=$KIVOU_ROLLOUT_PATH" \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  --property=ProtectHome=yes \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/python" - <<'PY'
import os

import sqlalchemy as sa

from signals.persistence.database import (
    create_database_engine,
    current_revision,
    migrate_to_latest,
)

engine = create_database_engine()
core_tables = ("account", "target_icp", "materialized_signal", "contract_award")
rollout_path = os.environ["KIVOU_ROLLOUT_PATH"]
with engine.connect() as connection:
    before = current_revision(engine)
    before_counts = {
        table: connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"'))
        for table in core_tables
    }
if rollout_path == "initial_0027":
    assert before == "0027_signal_notes", before
    migrate_to_latest(engine)
    after = current_revision(engine)
    assert after == "0028_card_presentation", after
elif rollout_path == "resume_51202525":
    assert before == "0028_card_presentation", before
    after = current_revision(engine)
    assert after == "0028_card_presentation", after
else:
    raise AssertionError(rollout_path)
with engine.connect() as connection:
    inspector = sa.inspect(connection)
    assert inspector.get_table_names().count("card_presentation_artifact") == 1
    if rollout_path == "initial_0027":
        assert connection.scalar(sa.text(
            "SELECT count(*) FROM card_presentation_artifact"
        )) == 0
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
print(f"database_transition={before}->{after}")
print(f"migration={before}->{after}")
PY
REMOTE
~~~

Le résultat attendu est `database_transition=0027_signal_notes->0028_card_presentation`
pour le chemin initial ou `database_transition=0028_card_presentation->0028_card_presentation`
pour la reprise; la ligne `migration=` reflète la même transition. Le chemin de
reprise ne rejoue aucune migration. Ne pas exécuter de downgrade : la migration
est additive.

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
case "$KIVOU_ROLLOUT_PATH" in
  (initial_0027)
    KIVOU_BACKFILL_AS_OF=$(date -u +%F)
    KIVOU_FR_LIMIT=50
    KIVOU_EN_LIMIT=50
    KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST=NOT_APPLICABLE
    KIVOU_RECOVERY_EMPTY_ARTIFACT_DIGEST=NOT_APPLICABLE
    KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST=NOT_APPLICABLE
    KIVOU_RECOVERY_CANDIDATE_COUNT=NOT_APPLICABLE
    KIVOU_RECOVERY_FR_ACTIVE_COUNT=NOT_APPLICABLE
    KIVOU_RECOVERY_FR_CURRENT_COUNT=NOT_APPLICABLE
    KIVOU_RECOVERY_CANDIDATE_BINDING_DIGEST=NOT_APPLICABLE
    KIVOU_RECOVERY_FR_ACTIVE_DIGEST=NOT_APPLICABLE
    KIVOU_RECOVERY_FR_CURRENT_DIGEST=NOT_APPLICABLE
    ;;
  (resume_51202525)
    KIVOU_BACKFILL_AS_OF=2026-08-31
    KIVOU_FR_LIMIT=50
    KIVOU_EN_LIMIT=50
    : "${KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST:?STOP: digest baseline absent}"
    KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST=
    KIVOU_RECOVERY_EMPTY_ARTIFACT_DIGEST=$(printf '%s' '[]' | \
      sha256sum | awk '{print $1}')
    printf '%s\n' "$KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST" | \
      grep -Eq '^[0-9a-f]{64}$'
    printf '%s\n' "$KIVOU_RECOVERY_EMPTY_ARTIFACT_DIGEST" | \
      grep -Eq '^[0-9a-f]{64}$'
    ;;
  (*) exit 69 ;;
esac
printf '%s\n' "$KIVOU_BACKFILL_AS_OF" | \
  grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
for KIVOU_BACKFILL_LIMIT in "$KIVOU_FR_LIMIT" "$KIVOU_EN_LIMIT"; do
  printf '%s\n' "$KIVOU_BACKFILL_LIMIT" | grep -Eq '^[1-9][0-9]*$'
done
unset KIVOU_BACKFILL_LIMIT
readonly KIVOU_BACKFILL_AS_OF KIVOU_FR_LIMIT KIVOU_EN_LIMIT
readonly KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST
readonly KIVOU_RECOVERY_EMPTY_ARTIFACT_DIGEST
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
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
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
KIVOU_QA_SCOPE_FINGERPRINT=$(printf '%s\n' "$KIVOU_QA_SCOPE_SUMMARY" | \
  sed -E 's/^qa_scope_ok fingerprint=([0-9a-f]{16}) .*$/\1/')
unset KIVOU_QA_SCOPE_SUMMARY
printf '%s\n' "$KIVOU_QA_SCOPE_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'
test "$KIVOU_QA_SCOPE_FINGERPRINT" = "$KIVOU_QA_APPROVED_FINGERPRINT"
unset KIVOU_QA_SCOPE_FINGERPRINT

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
  KIVOU_QA_BROWSER_READ_DATE=$(date -u +%F)
  printf '%s\n' "$KIVOU_QA_BROWSER_READ_DATE" | \
    grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
  KIVOU_QA_STORAGE_STATE="$KIVOU_QA_STORAGE_STATE_REAL" \
  KIVOU_QA_BROWSER_READ_DATE="$KIVOU_QA_BROWSER_READ_DATE" \
  KIVOU_QA_ORIGIN=https://staging.kivou.eu node <<'JS'
async function run() {
  const { chromium } = require('playwright')
  const origin = process.env.KIVOU_QA_ORIGIN
  const readDate = process.env.KIVOU_QA_BROWSER_READ_DATE
  const expectedFingerprint = process.env.KIVOU_QA_APPROVED_FINGERPRINT
  const storageState = process.env.KIVOU_QA_STORAGE_STATE
  if (!origin || !readDate || !expectedFingerprint || !storageState) {
    throw new Error()
  }
  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext({ storageState })
    const page = await context.newPage()
    await page.goto(`${origin}/app/signals`, { waitUntil: 'networkidle' })
    const verified = await page.evaluate(async ({ readDate, expectedFingerprint }) => {
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
        `/signals?freshness=new&limit=20&offset=0`,
        { credentials: 'same-origin' },
      )
      if (feedResponse.status !== 200) throw new Error()
      const feed = await feedResponse.json()
      if (feed.read_at !== readDate || feed.freshness !== 'new' ||
          feed.page?.limit !== 20 || feed.page.offset !== 0 ||
          !Array.isArray(feed.items)) throw new Error()
      if (!feed.items.some((item) => item && item.locked === false)) {
        throw new Error()
      }
      return true
    }, { readDate, expectedFingerprint })
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

kivou_validate_qa_read_only "$KIVOU_RELEASE_DIR"

# Fermer la fenêtre de drift entre le manifeste pré-FR et le snapshot post-EN.
# Le watchdog restaure l'API et uniquement les timers auparavant actifs si la
# session opérateur disparaît avant la restauration explicite.
KIVOU_WRITER_STATE_FILE="$KIVOU_EVIDENCE_DIR/writer-quiescence.txt"
test ! -e "$KIVOU_WRITER_STATE_FILE"
KIVOU_WRITER_QUIESCENCE=$(ssh kivou-staging 'bash -s' -- \
  "$KIVOU_FINAL_SHORT" <<'REMOTE'
set -euo pipefail
KIVOU_FINAL_SHORT=$1
printf '%s\n' "$KIVOU_FINAL_SHORT" | grep -Eq '^[0-9a-f]{12}$'
test "$(hostname -s)" = "kivou-staging-01"
KIVOU_WRITER_TIMERS=(
  kivou-acquisition.timer
  kivou-ingest-simap.timer
  kivou-ingest-boamp.timer
  kivou-ingest-decp.timer
  kivou-ingest-ted.timer
)
KIVOU_WRITER_SERVICES=(
  kivou-acquisition.service
  kivou-ingest-simap.service
  kivou-ingest-boamp.service
  kivou-ingest-decp.service
  kivou-ingest-ted.service
)
systemctl is-active --quiet kivou-api.service
KIVOU_ACTIVE_TIMERS=()
KIVOU_TIMER_STATES=
for KIVOU_WRITER_TIMER in "${KIVOU_WRITER_TIMERS[@]}"; do
  systemctl show "$KIVOU_WRITER_TIMER" --property=LoadState --value | \
    grep -Fx loaded >/dev/null
  if systemctl is-active --quiet "$KIVOU_WRITER_TIMER"; then
    KIVOU_ACTIVE_TIMERS+=("$KIVOU_WRITER_TIMER")
    KIVOU_TIMER_STATES+=1
  else
    test "$(systemctl is-active "$KIVOU_WRITER_TIMER" || test $? -eq 3)" = \
      inactive
    KIVOU_TIMER_STATES+=0
  fi
done
printf '%s\n' "$KIVOU_TIMER_STATES" | grep -Eq '^[01]{5}$'
KIVOU_WRITER_WATCHDOG="kivou-card-writers-resume-$KIVOU_FINAL_SHORT"
test "$(systemctl show "$KIVOU_WRITER_WATCHDOG.timer" \
  --property=LoadState --value)" = not-found
sudo systemd-run --quiet --unit="$KIVOU_WRITER_WATCHDOG" --on-active=20m \
  --timer-property=AccuracySec=1s -- /usr/bin/systemctl start \
  kivou-api.service "${KIVOU_ACTIVE_TIMERS[@]}"
if test "${#KIVOU_ACTIVE_TIMERS[@]}" -gt 0; then
  sudo systemctl stop "${KIVOU_ACTIVE_TIMERS[@]}"
fi
for KIVOU_WRITER_SERVICE in "${KIVOU_WRITER_SERVICES[@]}"; do
  systemctl show "$KIVOU_WRITER_SERVICE" --property=LoadState --value | \
    grep -Fx loaded >/dev/null
done
sudo systemctl stop kivou-api.service "${KIVOU_WRITER_SERVICES[@]}"
for KIVOU_WRITER_UNIT in kivou-api.service \
  "${KIVOU_WRITER_TIMERS[@]}" "${KIVOU_WRITER_SERVICES[@]}"; do
  KIVOU_WRITER_STATE=$(systemctl is-active "$KIVOU_WRITER_UNIT" || \
    test $? -eq 3)
  test "$KIVOU_WRITER_STATE" = inactive
done
unset KIVOU_WRITER_STATE
printf 'writer_quiesced=1 timer_states=%s watchdog=%s\n' \
  "$KIVOU_TIMER_STATES" "$KIVOU_WRITER_WATCHDOG"
REMOTE
)
printf '%s\n' "$KIVOU_WRITER_QUIESCENCE" | tee \
  "$KIVOU_WRITER_STATE_FILE" >/dev/null
chmod 600 "$KIVOU_WRITER_STATE_FILE"
test ! -L "$KIVOU_WRITER_STATE_FILE"
test "$(stat -c '%U:%a' "$KIVOU_WRITER_STATE_FILE")" = "$(id -un):600"
printf '%s\n' "$KIVOU_WRITER_QUIESCENCE" | grep -Eq \
  '^writer_quiesced=1 timer_states=[01]{5} watchdog=kivou-card-writers-resume-[0-9a-f]{12}$'
KIVOU_WRITER_TIMER_STATES=$(printf '%s\n' "$KIVOU_WRITER_QUIESCENCE" | \
  sed -E 's/^writer_quiesced=1 timer_states=([01]{5}) watchdog=.*$/\1/')
KIVOU_WRITER_WATCHDOG=$(printf '%s\n' "$KIVOU_WRITER_QUIESCENCE" | \
  sed -E 's/^.* watchdog=([a-z0-9-]+)$/\1/')
unset KIVOU_WRITER_QUIESCENCE
printf '%s\n' "$KIVOU_WRITER_TIMER_STATES" | grep -Eq '^[01]{5}$'
test "$KIVOU_WRITER_WATCHDOG" = \
  "kivou-card-writers-resume-$KIVOU_FINAL_SHORT"
readonly KIVOU_WRITER_TIMER_STATES KIVOU_WRITER_WATCHDOG

kivou_rearm_card_writer_watchdog() {
  ssh kivou-staging 'bash -s' -- "$KIVOU_WRITER_WATCHDOG" <<'REMOTE'
set -euo pipefail
KIVOU_WRITER_WATCHDOG=$1
printf '%s\n' "$KIVOU_WRITER_WATCHDOG" | \
  grep -Eq '^kivou-card-writers-resume-[0-9a-f]{12}$'
KIVOU_WRITER_TIMERS=(
  kivou-acquisition.timer
  kivou-ingest-simap.timer
  kivou-ingest-boamp.timer
  kivou-ingest-decp.timer
  kivou-ingest-ted.timer
)
KIVOU_WRITER_SERVICES=(
  kivou-acquisition.service
  kivou-ingest-simap.service
  kivou-ingest-boamp.service
  kivou-ingest-decp.service
  kivou-ingest-ted.service
)
for KIVOU_WATCHDOG_UNIT in "$KIVOU_WRITER_WATCHDOG.timer" \
  "$KIVOU_WRITER_WATCHDOG.service"; do
  systemctl show "$KIVOU_WATCHDOG_UNIT" --property=LoadState --value | \
    grep -Fx loaded >/dev/null
done
unset KIVOU_WATCHDOG_UNIT
KIVOU_WATCHDOG_TIMER_STATE=$(systemctl is-active \
  "$KIVOU_WRITER_WATCHDOG.timer" || test $? -eq 3)
test "$KIVOU_WATCHDOG_TIMER_STATE" = active
KIVOU_WATCHDOG_SERVICE_STATE=$(systemctl is-active \
  "$KIVOU_WRITER_WATCHDOG.service" || test $? -eq 3)
test "$KIVOU_WATCHDOG_SERVICE_STATE" = inactive
for KIVOU_WRITER_UNIT in kivou-api.service \
  "${KIVOU_WRITER_TIMERS[@]}" "${KIVOU_WRITER_SERVICES[@]}"; do
  KIVOU_WRITER_STATE=$(systemctl is-active "$KIVOU_WRITER_UNIT" || \
    test $? -eq 3)
  test "$KIVOU_WRITER_STATE" = inactive
done
unset KIVOU_WRITER_STATE KIVOU_WATCHDOG_TIMER_STATE
unset KIVOU_WATCHDOG_SERVICE_STATE
sudo systemctl restart "$KIVOU_WRITER_WATCHDOG.timer"
KIVOU_WATCHDOG_TIMER_STATE=$(systemctl is-active \
  "$KIVOU_WRITER_WATCHDOG.timer" || test $? -eq 3)
test "$KIVOU_WATCHDOG_TIMER_STATE" = active
KIVOU_WATCHDOG_SERVICE_STATE=$(systemctl is-active \
  "$KIVOU_WRITER_WATCHDOG.service" || test $? -eq 3)
test "$KIVOU_WATCHDOG_SERVICE_STATE" = inactive
for KIVOU_WRITER_UNIT in kivou-api.service \
  "${KIVOU_WRITER_TIMERS[@]}" "${KIVOU_WRITER_SERVICES[@]}"; do
  KIVOU_WRITER_STATE=$(systemctl is-active "$KIVOU_WRITER_UNIT" || \
    test $? -eq 3)
  test "$KIVOU_WRITER_STATE" = inactive
done
unset KIVOU_WRITER_STATE KIVOU_WATCHDOG_TIMER_STATE
unset KIVOU_WATCHDOG_SERVICE_STATE
printf 'writer_watchdog_rearmed=1 watchdog=%s\n' "$KIVOU_WRITER_WATCHDOG"
REMOTE
}

kivou_resume_card_writers() {
  ssh kivou-staging 'bash -s' -- "$KIVOU_RELEASE_DIR" \
    "$KIVOU_WRITER_TIMER_STATES" "$KIVOU_WRITER_WATCHDOG" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_TIMER_STATES=$2
KIVOU_WRITER_WATCHDOG=$3
case "$KIVOU_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
printf '%s\n' "$KIVOU_TIMER_STATES" | grep -Eq '^[01]{5}$'
printf '%s\n' "$KIVOU_WRITER_WATCHDOG" | \
  grep -Eq '^kivou-card-writers-resume-[0-9a-f]{12}$'
KIVOU_WRITER_TIMERS=(
  kivou-acquisition.timer
  kivou-ingest-simap.timer
  kivou-ingest-boamp.timer
  kivou-ingest-decp.timer
  kivou-ingest-ted.timer
)
KIVOU_RESTART_TIMERS=()
for KIVOU_TIMER_INDEX in 0 1 2 3 4; do
  if test "${KIVOU_TIMER_STATES:$KIVOU_TIMER_INDEX:1}" = 1; then
    KIVOU_RESTART_TIMERS+=("${KIVOU_WRITER_TIMERS[$KIVOU_TIMER_INDEX]}")
  fi
done
sudo systemctl start kivou-api.service "${KIVOU_RESTART_TIMERS[@]}"
"$KIVOU_RELEASE_DIR/ops/bin/kivou-api-readiness.sh" \
  kivou-api.service 8000
for KIVOU_TIMER_INDEX in 0 1 2 3 4; do
  KIVOU_WRITER_TIMER=${KIVOU_WRITER_TIMERS[$KIVOU_TIMER_INDEX]}
  if test "${KIVOU_TIMER_STATES:$KIVOU_TIMER_INDEX:1}" = 1; then
    systemctl is-active --quiet "$KIVOU_WRITER_TIMER"
  else
    KIVOU_WRITER_TIMER_STATE=$(systemctl is-active "$KIVOU_WRITER_TIMER" || \
      test $? -eq 3)
    test "$KIVOU_WRITER_TIMER_STATE" = inactive
    unset KIVOU_WRITER_TIMER_STATE
  fi
done
sudo systemctl stop "$KIVOU_WRITER_WATCHDOG.timer"
printf 'writer_resumed=1 timer_states=%s watchdog=%s\n' \
  "$KIVOU_TIMER_STATES" "$KIVOU_WRITER_WATCHDOG"
REMOTE
}

kivou_resume_card_writers_on_exit() {
  KIVOU_ROLLOUT_EXIT_STATUS=$?
  trap - EXIT
  if ! kivou_resume_card_writers; then
    KIVOU_ROLLOUT_EXIT_STATUS=1
  fi
  exit "$KIVOU_ROLLOUT_EXIT_STATUS"
}
trap kivou_resume_card_writers_on_exit EXIT

if test "$KIVOU_ROLLOUT_PATH" = resume_51202525; then
  KIVOU_RECOVERY_PRE_FR="$KIVOU_EVIDENCE_DIR/recovery-fr-preflight.json"
  test ! -e "$KIVOU_RECOVERY_PRE_FR"
  kivou_rearm_card_writer_watchdog
  KIVOU_RECOVERY_PRE_FR_PAYLOAD=$(kivou_capture_recovery_fr_snapshot "$KIVOU_RELEASE_DIR" baseline)
  printf '%s\n' "$KIVOU_RECOVERY_PRE_FR_PAYLOAD" > "$KIVOU_RECOVERY_PRE_FR"
  unset KIVOU_RECOVERY_PRE_FR_PAYLOAD
  chmod 600 "$KIVOU_RECOVERY_PRE_FR"
  test ! -L "$KIVOU_RECOVERY_PRE_FR"
  test "$(stat -c '%U:%a' "$KIVOU_RECOVERY_PRE_FR")" = "$(id -un):600"
  jq -e --slurpfile baseline "$KIVOU_RECOVERY_BASELINE" '
    .candidate_count >= 8 and .candidate_count <= 50
    and (.candidate_binding_digest | test("^[0-9a-f]{64}$"))
    and .active_counts == {"en":0,"fr":8}
    and .current_counts.en == 0
    and .current_counts.fr >= 0 and .current_counts.fr <= 8
    and .active_outside_candidate_counts == {"en":0,"fr":0}
    and ([.artifacts[] | del(.state)]
      == [$baseline[0].artifacts[] | del(.state)])
    and all(.artifacts[];
      .state == "current" or .state == "signal_revision_changed")
    and ([.artifacts[] | select(.state == "signal_revision_changed")] | length)
      == (8 - .current_counts.fr)
    and .active_artifact_ids == $baseline[0].active_artifact_ids
    and .active_digests == $baseline[0].active_digests
  ' "$KIVOU_RECOVERY_PRE_FR" >/dev/null
  test "$(jq -j -c '[.artifacts[].artifact_id] | sort' \
    "$KIVOU_RECOVERY_PRE_FR" | sha256sum | awk '{print $1}')" = \
    "$KIVOU_RECOVERY_BASELINE_ARTIFACT_DIGEST"
  KIVOU_RECOVERY_CANDIDATE_COUNT=$(jq -r '.candidate_count' \
    "$KIVOU_RECOVERY_PRE_FR")
  KIVOU_RECOVERY_FR_ACTIVE_COUNT=$(jq -r '.active_counts.fr' \
    "$KIVOU_RECOVERY_PRE_FR")
  KIVOU_RECOVERY_FR_CURRENT_COUNT=$(jq -r '.current_counts.fr' \
    "$KIVOU_RECOVERY_PRE_FR")
  KIVOU_RECOVERY_CANDIDATE_BINDING_DIGEST=$(jq -r \
    '.candidate_binding_digest' "$KIVOU_RECOVERY_PRE_FR")
  KIVOU_RECOVERY_FR_ACTIVE_DIGEST=$(jq -r '.active_digests.fr' \
    "$KIVOU_RECOVERY_PRE_FR")
  KIVOU_RECOVERY_FR_CURRENT_DIGEST=$(jq -r '.current_digests.fr' \
    "$KIVOU_RECOVERY_PRE_FR")
  printf '%s\n' "$KIVOU_RECOVERY_CANDIDATE_COUNT" | \
    grep -Eq '^([89]|[1-4][0-9]|50)$'
  test "$KIVOU_RECOVERY_FR_ACTIVE_COUNT" = 8
  printf '%s\n' "$KIVOU_RECOVERY_FR_CURRENT_COUNT" | grep -Eq '^[0-8]$'
  for KIVOU_RECOVERY_DIGEST in \
    "$KIVOU_RECOVERY_CANDIDATE_BINDING_DIGEST" \
    "$KIVOU_RECOVERY_FR_ACTIVE_DIGEST" \
    "$KIVOU_RECOVERY_FR_CURRENT_DIGEST"; do
    printf '%s\n' "$KIVOU_RECOVERY_DIGEST" | grep -Eq '^[0-9a-f]{64}$'
  done
  unset KIVOU_RECOVERY_DIGEST
fi
readonly KIVOU_RECOVERY_CANDIDATE_COUNT KIVOU_RECOVERY_FR_ACTIVE_COUNT
readonly KIVOU_RECOVERY_FR_CURRENT_COUNT
readonly KIVOU_RECOVERY_CANDIDATE_BINDING_DIGEST
readonly KIVOU_RECOVERY_FR_ACTIVE_DIGEST KIVOU_RECOVERY_FR_CURRENT_DIGEST
kivou_rearm_card_writer_watchdog
ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "$KIVOU_BACKFILL_AS_OF" \
  "$KIVOU_QA_APPROVED_FINGERPRINT" "$KIVOU_FR_LIMIT" \
  "$KIVOU_ROLLOUT_PATH" "$KIVOU_RECOVERY_CANDIDATE_COUNT" \
  "$KIVOU_RECOVERY_FR_ACTIVE_COUNT" "$KIVOU_RECOVERY_FR_CURRENT_COUNT" \
  "$KIVOU_RECOVERY_CANDIDATE_BINDING_DIGEST" \
  "$KIVOU_RECOVERY_FR_ACTIVE_DIGEST" \
  "$KIVOU_RECOVERY_FR_CURRENT_DIGEST" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_BACKFILL_AS_OF=$3
KIVOU_QA_APPROVED_FINGERPRINT=$4
KIVOU_FR_LIMIT=$5
KIVOU_ROLLOUT_PATH=$6
KIVOU_EXPECTED_CANDIDATE_COUNT=$7
KIVOU_EXPECTED_ACTIVE_COUNT=$8
KIVOU_EXPECTED_CURRENT_COUNT=$9
KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST=${10}
KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST=${11}
KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST=${12}
KIVOU_BACKFILL_LIMIT=$KIVOU_FR_LIMIT
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
KIVOU_QA_ENV=/etc/kivou/card-presentation-qa.env
printf '%s\n' "$KIVOU_QA_APPROVED_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'
printf '%s\n' "$KIVOU_BACKFILL_LIMIT" | grep -Eq '^[1-9][0-9]*$'
test "$KIVOU_BACKFILL_LIMIT" -le 50
readonly KIVOU_BACKFILL_AS_OF KIVOU_BACKFILL_LIMIT
case "$KIVOU_ROLLOUT_PATH" in
  (initial_0027) ;;
  (resume_51202525)
    printf '%s\n' "$KIVOU_EXPECTED_CANDIDATE_COUNT" | \
      grep -Eq '^([89]|[1-4][0-9]|50)$'
    test "$KIVOU_EXPECTED_ACTIVE_COUNT" = 8
    printf '%s\n' "$KIVOU_EXPECTED_CURRENT_COUNT" | grep -Eq '^[0-8]$'
    for KIVOU_EXPECTED_DIGEST in \
      "$KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST" \
      "$KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST" \
      "$KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST"; do
      printf '%s\n' "$KIVOU_EXPECTED_DIGEST" | grep -Eq '^[0-9a-f]{64}$'
    done
    unset KIVOU_EXPECTED_DIGEST
    ;;
  (*) exit 69 ;;
esac

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
  test "$KIVOU_QA_BOUND_FINGERPRINT" = "$KIVOU_QA_APPROVED_FINGERPRINT"
  unset KIVOU_QA_BOUND_FINGERPRINT
}

kivou_validate_backfill_summary() {
  printf '%s\n' "$1" | awk -v limit="$2" '
    BEGIN { ok=0 }
    /^scanned=[0-9]+ published=[0-9]+ unchanged=[0-9]+ failed=0 next_offset=(none|[0-9]+) scan_truncated=0$/ {
      split($1, scanned, "="); split($2, published, "="); split($3, unchanged, "=")
      if (scanned[2] <= limit && published[2] <= limit && unchanged[2] <= limit &&
          published[2] + unchanged[2] <= scanned[2]) ok=1
    }
    END { exit !ok }
  '
}

kivou_validate_recovery_summary() {
  test "$KIVOU_ROLLOUT_PATH" = resume_51202525 || return 0
  test "$1" = fr
  KIVOU_EXPECTED_PUBLISHED=$((KIVOU_EXPECTED_CANDIDATE_COUNT - KIVOU_EXPECTED_CURRENT_COUNT))
  test "$2" = \
    "scanned=$KIVOU_EXPECTED_CANDIDATE_COUNT published=$KIVOU_EXPECTED_PUBLISHED unchanged=$KIVOU_EXPECTED_CURRENT_COUNT failed=0 next_offset=none scan_truncated=0"
  unset KIVOU_EXPECTED_PUBLISHED
}

kivou_revalidate_qa_binding
KIVOU_FR_SUMMARY=$(sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-backfill-fr-$KIVOU_FINAL_SHORT" --property=Type=oneshot \
  --property=RuntimeMaxSec=5min \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile="$KIVOU_QA_ENV" \
  --setenv=HOME=/srv/kivou \
  --setenv="PATH=$KIVOU_RELEASE_DIR/.venv/bin:/usr/bin:/bin" \
  --setenv="KIVOU_BACKFILL_AS_OF=$KIVOU_BACKFILL_AS_OF" \
  --setenv="KIVOU_BACKFILL_LIMIT=$KIVOU_BACKFILL_LIMIT" \
  --setenv="KIVOU_ROLLOUT_PATH=$KIVOU_ROLLOUT_PATH" \
  --setenv="KIVOU_EXPECTED_CANDIDATE_COUNT=$KIVOU_EXPECTED_CANDIDATE_COUNT" \
  --setenv="KIVOU_EXPECTED_ACTIVE_COUNT=$KIVOU_EXPECTED_ACTIVE_COUNT" \
  --setenv="KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST=$KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST" \
  --setenv="KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST=$KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST" \
  --setenv="KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST=$KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST" \
  --setenv="KIVOU_QA_APPROVED_FINGERPRINT=$KIVOU_QA_APPROVED_FINGERPRINT" \
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
    expected = os.environ["KIVOU_QA_APPROVED_FINGERPRINT"]
    if re.fullmatch(r"[0-9a-f]{16}", expected) is None:
        raise ValueError()
    actual = hashlib.sha256(file_account_id.encode("utf-8")).hexdigest()[:16]
    if not hmac.compare_digest(actual, expected):
        raise ValueError()
    arguments = [
        "backfill-fallbacks",
        "--account-id", file_account_id,
        "--as-of", os.environ["KIVOU_BACKFILL_AS_OF"],
        "--language", "fr",
        "--limit", os.environ["KIVOU_BACKFILL_LIMIT"],
        "--offset", "0",
    ]
    if os.environ["KIVOU_ROLLOUT_PATH"] == "resume_51202525":
        arguments.extend([
            "--expect-candidate-count",
            os.environ["KIVOU_EXPECTED_CANDIDATE_COUNT"],
            "--expect-active-publication-count",
            os.environ["KIVOU_EXPECTED_ACTIVE_COUNT"],
            "--expect-current-factual-artifact-digest",
            os.environ["KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST"],
            "--expect-candidate-binding-digest",
            os.environ["KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST"],
            "--expect-active-artifact-digest",
            os.environ["KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST"],
        ])
    exit_code = cli_main(arguments)
    if exit_code != 0:
        raise ValueError()


try:
    main()
except Exception:
    print("qa_backfill_failed", file=sys.stderr)
    raise SystemExit(1) from None
PY
)
kivou_validate_backfill_summary "$KIVOU_FR_SUMMARY" "$KIVOU_FR_LIMIT"
kivou_validate_recovery_summary fr "$KIVOU_FR_SUMMARY"
printf 'fr_%s\n' "$KIVOU_FR_SUMMARY"
REMOTE

if test "$KIVOU_ROLLOUT_PATH" = resume_51202525; then
  KIVOU_RECOVERY_POST_FR="$KIVOU_EVIDENCE_DIR/recovery-fr-post.json"
  test ! -e "$KIVOU_RECOVERY_POST_FR"
  kivou_rearm_card_writer_watchdog
  KIVOU_RECOVERY_POST_FR_PAYLOAD=$(kivou_capture_recovery_fr_snapshot \
    "$KIVOU_RELEASE_DIR" post_fr)
  printf '%s\n' "$KIVOU_RECOVERY_POST_FR_PAYLOAD" > \
    "$KIVOU_RECOVERY_POST_FR"
  unset KIVOU_RECOVERY_POST_FR_PAYLOAD
  chmod 600 "$KIVOU_RECOVERY_POST_FR"
  test ! -L "$KIVOU_RECOVERY_POST_FR"
  test "$(stat -c '%U:%a' "$KIVOU_RECOVERY_POST_FR")" = "$(id -un):600"
  jq -e --slurpfile baseline "$KIVOU_RECOVERY_BASELINE" \
    --slurpfile prefr "$KIVOU_RECOVERY_PRE_FR" '
    . as $post
    | ($prefr[0].candidate_count) as $candidate_count
    | ($prefr[0].current_counts.fr) as $current_count
    | .candidate_count == $candidate_count
    and .candidate_binding_digest == $prefr[0].candidate_binding_digest
    and .active_counts == {"en":0,"fr":$candidate_count}
    and .current_counts == {"en":0,"fr":$candidate_count}
    and .active_digests.fr == .current_digests.fr
    and .active_outside_candidate_counts == {"en":0,"fr":0}
    and (.active_artifact_ids.en | length) == 0
    and (.artifacts | length) == (8 + $candidate_count - $current_count)
    and all($baseline[0].artifacts[];
      del(.state) as $old
      | any($post.artifacts[]; del(.state) == $old))
    and all($prefr[0].artifacts[] | select(.state == "current");
      .artifact_id as $artifact_id
      | ($post.active_artifact_ids.fr | index($artifact_id)) != null)
    and all($prefr[0].artifacts[]
      | select(.state == "signal_revision_changed");
      .artifact_id as $artifact_id
      | ($post.active_artifact_ids.fr | index($artifact_id)) == null)
  ' "$KIVOU_RECOVERY_POST_FR" >/dev/null
  KIVOU_RECOVERY_POST_FR_SHA256=$(sha256sum \
    "$KIVOU_RECOVERY_POST_FR" | awk '{print $1}')
  printf '%s\n' "$KIVOU_RECOVERY_POST_FR_SHA256" | \
    grep -Eq '^[0-9a-f]{64}$'
  KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST=$(jq -r '.active_digests.fr' \
    "$KIVOU_RECOVERY_POST_FR")
  printf '%s\n' "$KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST" | \
    grep -Eq '^[0-9a-f]{64}$'
  printf '%s\n' recovery_fr_baseline_preserved=1
  printf 'recovery_offline_feed_post_fr=%s\n' \
    "$KIVOU_RECOVERY_CANDIDATE_COUNT"
fi
readonly KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST

kivou_rearm_card_writer_watchdog
ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" "$KIVOU_BACKFILL_AS_OF" \
  "$KIVOU_QA_APPROVED_FINGERPRINT" "$KIVOU_EN_LIMIT" \
  "$KIVOU_ROLLOUT_PATH" "$KIVOU_RECOVERY_CANDIDATE_COUNT" \
  "$KIVOU_RECOVERY_CANDIDATE_BINDING_DIGEST" \
  "$KIVOU_RECOVERY_EMPTY_ARTIFACT_DIGEST" \
  "$KIVOU_RECOVERY_EMPTY_ARTIFACT_DIGEST" \
  "$KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST" \
  "$KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_BACKFILL_AS_OF=$3
KIVOU_QA_APPROVED_FINGERPRINT=$4
KIVOU_EN_LIMIT=$5
KIVOU_ROLLOUT_PATH=$6
KIVOU_EXPECTED_CANDIDATE_COUNT=$7
KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST=$8
KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST=$9
KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST=${10}
KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST=${11}
KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST=${12}
KIVOU_BACKFILL_LIMIT=$KIVOU_EN_LIMIT
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
KIVOU_QA_ENV=/etc/kivou/card-presentation-qa.env
printf '%s\n' "$KIVOU_QA_APPROVED_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'
printf '%s\n' "$KIVOU_BACKFILL_LIMIT" | grep -Eq '^[1-9][0-9]*$'
test "$KIVOU_BACKFILL_LIMIT" -le 50
readonly KIVOU_BACKFILL_AS_OF KIVOU_BACKFILL_LIMIT
case "$KIVOU_ROLLOUT_PATH" in
  (initial_0027) ;;
  (resume_51202525)
    printf '%s\n' "$KIVOU_EXPECTED_CANDIDATE_COUNT" | \
      grep -Eq '^([89]|[1-4][0-9]|50)$'
    for KIVOU_EXPECTED_DIGEST in \
      "$KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST" \
      "$KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST" \
      "$KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST" \
      "$KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST" \
      "$KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST"; do
      printf '%s\n' "$KIVOU_EXPECTED_DIGEST" | \
        grep -Eq '^[0-9a-f]{64}$'
    done
    unset KIVOU_EXPECTED_DIGEST
    ;;
  (*) exit 69 ;;
esac

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
  test "$KIVOU_QA_BOUND_FINGERPRINT" = "$KIVOU_QA_APPROVED_FINGERPRINT"
  unset KIVOU_QA_BOUND_FINGERPRINT
}

kivou_validate_backfill_summary() {
  printf '%s\n' "$1" | awk -v limit="$2" '
    BEGIN { ok=0 }
    /^scanned=[0-9]+ published=[0-9]+ unchanged=[0-9]+ failed=0 next_offset=(none|[0-9]+) scan_truncated=0$/ {
      split($1, scanned, "="); split($2, published, "="); split($3, unchanged, "=")
      if (scanned[2] <= limit && published[2] <= limit && unchanged[2] <= limit &&
          published[2] + unchanged[2] <= scanned[2]) ok=1
    }
    END { exit !ok }
  '
}

kivou_validate_recovery_summary() {
  test "$KIVOU_ROLLOUT_PATH" = resume_51202525 || return 0
  test "$1" = en
  test "$2" = \
    "scanned=$KIVOU_EXPECTED_CANDIDATE_COUNT published=$KIVOU_EXPECTED_CANDIDATE_COUNT unchanged=0 failed=0 next_offset=none scan_truncated=0"
}

kivou_revalidate_qa_binding
KIVOU_EN_SUMMARY=$(sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-backfill-en-$KIVOU_FINAL_SHORT" --property=Type=oneshot \
  --property=RuntimeMaxSec=5min \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile="$KIVOU_QA_ENV" \
  --setenv=HOME=/srv/kivou \
  --setenv="PATH=$KIVOU_RELEASE_DIR/.venv/bin:/usr/bin:/bin" \
  --setenv="KIVOU_BACKFILL_AS_OF=$KIVOU_BACKFILL_AS_OF" \
  --setenv="KIVOU_BACKFILL_LIMIT=$KIVOU_BACKFILL_LIMIT" \
  --setenv="KIVOU_ROLLOUT_PATH=$KIVOU_ROLLOUT_PATH" \
  --setenv="KIVOU_EXPECTED_CANDIDATE_COUNT=$KIVOU_EXPECTED_CANDIDATE_COUNT" \
  --setenv="KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST=$KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST" \
  --setenv="KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST=$KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST" \
  --setenv="KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST=$KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST" \
  --setenv="KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST=$KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST" \
  --setenv="KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST=$KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST" \
  --setenv="KIVOU_QA_APPROVED_FINGERPRINT=$KIVOU_QA_APPROVED_FINGERPRINT" \
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
    expected = os.environ["KIVOU_QA_APPROVED_FINGERPRINT"]
    if re.fullmatch(r"[0-9a-f]{16}", expected) is None:
        raise ValueError()
    actual = hashlib.sha256(file_account_id.encode("utf-8")).hexdigest()[:16]
    if not hmac.compare_digest(actual, expected):
        raise ValueError()
    arguments = [
        "backfill-fallbacks",
        "--account-id", file_account_id,
        "--as-of", os.environ["KIVOU_BACKFILL_AS_OF"],
        "--language", "en",
        "--limit", os.environ["KIVOU_BACKFILL_LIMIT"],
        "--offset", "0",
    ]
    if os.environ["KIVOU_ROLLOUT_PATH"] == "resume_51202525":
        arguments.extend([
            "--expect-candidate-count",
            os.environ["KIVOU_EXPECTED_CANDIDATE_COUNT"],
            "--expect-active-publication-count", "0",
            "--expect-current-factual-artifact-digest",
            os.environ["KIVOU_EXPECTED_CURRENT_ARTIFACT_DIGEST"],
            "--expect-candidate-binding-digest",
            os.environ["KIVOU_EXPECTED_CANDIDATE_BINDING_DIGEST"],
            "--expect-active-artifact-digest",
            os.environ["KIVOU_EXPECTED_ACTIVE_ARTIFACT_DIGEST"],
            "--expect-protected-language", "fr",
            "--expect-protected-active-publication-count",
            os.environ["KIVOU_EXPECTED_CANDIDATE_COUNT"],
            "--expect-protected-current-factual-artifact-digest",
            os.environ["KIVOU_PROTECTED_CURRENT_ARTIFACT_DIGEST"],
            "--expect-protected-active-artifact-digest",
            os.environ["KIVOU_PROTECTED_ACTIVE_ARTIFACT_DIGEST"],
        ])
    exit_code = cli_main(arguments)
    if exit_code != 0:
        raise ValueError()


try:
    main()
except Exception:
    print("qa_backfill_failed", file=sys.stderr)
    raise SystemExit(1) from None
PY
)
kivou_validate_backfill_summary "$KIVOU_EN_SUMMARY" "$KIVOU_EN_LIMIT"
kivou_validate_recovery_summary en "$KIVOU_EN_SUMMARY"
printf 'en_%s\n' "$KIVOU_EN_SUMMARY"
REMOTE

if test "$KIVOU_ROLLOUT_PATH" = resume_51202525; then
  KIVOU_RECOVERY_POST_EN="$KIVOU_EVIDENCE_DIR/recovery-post-en.json"
  test ! -e "$KIVOU_RECOVERY_POST_EN"
  kivou_rearm_card_writer_watchdog
  KIVOU_RECOVERY_POST_EN_PAYLOAD=$(kivou_capture_recovery_fr_snapshot \
    "$KIVOU_RELEASE_DIR" post_en)
  printf '%s\n' "$KIVOU_RECOVERY_POST_EN_PAYLOAD" > \
    "$KIVOU_RECOVERY_POST_EN"
  unset KIVOU_RECOVERY_POST_EN_PAYLOAD
  chmod 600 "$KIVOU_RECOVERY_POST_EN"
  test ! -L "$KIVOU_RECOVERY_POST_EN"
  test "$(stat -c '%U:%a' "$KIVOU_RECOVERY_POST_EN")" = "$(id -un):600"
  jq -e --slurpfile baseline "$KIVOU_RECOVERY_BASELINE" \
    --slurpfile post_fr "$KIVOU_RECOVERY_POST_FR" '
    . as $post
    | ($post_fr[0].candidate_count) as $candidate_count
    | .candidate_count == $candidate_count
    and .candidate_binding_digest == $post_fr[0].candidate_binding_digest
    and .active_counts == {"en":$candidate_count,"fr":$candidate_count}
    and .current_counts == {"en":$candidate_count,"fr":$candidate_count}
    and .active_digests.fr == .current_digests.fr
    and .active_digests.en == .current_digests.en
    and .active_digests.fr == $post_fr[0].active_digests.fr
    and .active_outside_candidate_counts == {"en":0,"fr":0}
    and (.active_artifact_ids.fr | length) == $candidate_count
    and (.active_artifact_ids.en | length) == $candidate_count
    and (.artifacts | length) == (($post_fr[0].artifacts | length) + $candidate_count)
    and all($baseline[0].artifacts[];
      del(.state) as $old
      | any($post.artifacts[]; del(.state) == $old))
    and all($post_fr[0].artifacts[];
      del(.state) as $old
      | any($post.artifacts[]; del(.state) == $old))
  ' "$KIVOU_RECOVERY_POST_EN" >/dev/null
  KIVOU_RECOVERY_POST_EN_SHA256=$(sha256sum \
    "$KIVOU_RECOVERY_POST_EN" | awk '{print $1}')
  KIVOU_RECOVERY_POST_EN_FR_ARTIFACT_DIGEST=$(jq -r \
    '.active_digests.fr' "$KIVOU_RECOVERY_POST_EN")
  KIVOU_RECOVERY_POST_EN_EN_ARTIFACT_DIGEST=$(jq -r \
    '.active_digests.en' "$KIVOU_RECOVERY_POST_EN")
  for KIVOU_RECOVERY_DIGEST in \
    "$KIVOU_RECOVERY_POST_EN_SHA256" \
    "$KIVOU_RECOVERY_POST_EN_FR_ARTIFACT_DIGEST" \
    "$KIVOU_RECOVERY_POST_EN_EN_ARTIFACT_DIGEST"; do
    printf '%s\n' "$KIVOU_RECOVERY_DIGEST" | grep -Eq '^[0-9a-f]{64}$'
  done
  unset KIVOU_RECOVERY_DIGEST
  test "$KIVOU_RECOVERY_POST_EN_FR_ARTIFACT_DIGEST" = \
    "$KIVOU_RECOVERY_POST_FR_ARTIFACT_DIGEST"
  readonly KIVOU_RECOVERY_POST_EN_SHA256 \
    KIVOU_RECOVERY_POST_EN_FR_ARTIFACT_DIGEST \
    KIVOU_RECOVERY_POST_EN_EN_ARTIFACT_DIGEST
  printf 'recovery_offline_feed_post_en=%s\n' \
    "$KIVOU_RECOVERY_CANDIDATE_COUNT"
fi
KIVOU_WRITER_RESUME_FILE="$KIVOU_EVIDENCE_DIR/writer-resume.txt"
test ! -e "$KIVOU_WRITER_RESUME_FILE"
KIVOU_WRITER_RESUME=$(kivou_resume_card_writers)
printf '%s\n' "$KIVOU_WRITER_RESUME" > "$KIVOU_WRITER_RESUME_FILE"
unset KIVOU_WRITER_RESUME
chmod 600 "$KIVOU_WRITER_RESUME_FILE"
test ! -L "$KIVOU_WRITER_RESUME_FILE"
test "$(stat -c '%U:%a' "$KIVOU_WRITER_RESUME_FILE")" = "$(id -un):600"
tail -n 1 "$KIVOU_WRITER_RESUME_FILE" | grep -Eq \
  '^writer_resumed=1 timer_states=[01]{5} watchdog=kivou-card-writers-resume-[0-9a-f]{12}$'
trap - EXIT
~~~

Ce sont deux unités, processus et transactions distincts, FR puis EN. Exiger
`failed=0` et `scan_truncated=0`; **ne pas suivre `next_offset`** même s'il est
présent. Dans chaque unité, le fichier d'approbation est rouvert avec
`O_NOFOLLOW`, validé par `fstat` comme fichier régulier `root:kivou:640`, puis
son identifiant est comparé en temps constant à l'EnvironmentFile et à
l'empreinte DB avant l'appel CLI. Un remplacement du fichier ne peut donc pas
rediriger la mutation vers un autre compte. Le chemin initial utilise une page
explicite de 50 par langue. La reprise conserve le `as-of` original
`2026-08-31` et borne les pages FR et EN à 50, toujours avec `--offset 0` et
sans suivre `next_offset`. Le preflight capture un nombre `N` dynamique de
candidats FR offline, exige `8 <= N <= 50`, une page non tronquée et les 8
publications actives existantes dans cette même page. Il capture aussi `C`, le
nombre de ces publications encore courantes (`0 <= C <= 8`). Chacun des `8-C`
artefacts actifs obsolètes doit différer de l'autorité courante uniquement par
`signal_revision`; un drift ICP, une source/fingerprint incohérente ou une
absence de binding échoue fermé. Le ledger immuable des huit artefacts ignore
seulement cette classification dynamique : `C` est donc recalculé après la
sauvegarde et la release, juste avant FR. Aucun candidat n'est laissé hors de la
reprise FR; si la page dépasse 50, STOP sans publication.

En reprise seulement, la précondition transactionnelle du CLI est obligatoire
et indivisible : les cinq attentes `candidate-count`, nombre global de
publications actives compte+langue, digest des artefacts factuels courants,
digest des bindings candidats `(signal_key, signal_revision,
target_icp_revision)` et digest de tous les `artifact_id` actifs sont toujours
fournies ensemble. FR doit retrouver exactement `N` candidats, 8 actifs et les
digests privés capturés au preflight; EN doit retrouver `N` candidats, 0 actif
et les digests canoniques des listes vides. EN ajoute obligatoirement le groupe
protégé indivisible : langue `fr`, `N` publications actives et les digests
actif/courant des `N` `artifact_id` du snapshot post-FR. Sous le même verrou
transactionnel des artefacts et avant toute publication EN, le CLI revalide la
currentness FR sur les mêmes `N` bindings, le compteur global FR et ces digests.
Le CLI revalide aussi, dans la transaction et avant toute publication, une page
complète (`has_more=false`, non tronquée) et les autorités persistées de la
langue publiée. Tout drift, échec de construction ou de verrouillage donne une
sortie opaque non nulle et zéro nouvelle publication. Tous les verrous de table
guarded (`SHARE` sur les autorités et `SHARE ROW EXCLUSIVE` sur les artefacts)
sont acquis avec `NOWAIT` : une indisponibilité arrête le backfill sans jamais
attendre ni sacrifier le writer. Les résumés recovery sont bloquants et exacts :
FR `scanned=N published=N-C unchanged=C failed=0 next_offset=none
scan_truncated=0`, puis EN `scanned=N published=N unchanged=0 failed=0
next_offset=none scan_truncated=0`.

Immédiatement après FR puis après EN, le snapshot protégé relit aussi le feed
offline sous transaction PostgreSQL read-only avec `as_of=2026-08-31`,
`freshness=all`, `limit=50`, `offset=0` et `scan_cap=1000`. Il exige encore
exactement les `N` items et bindings du preflight, `has_more=false` et
`scan_truncated=false`; tout candidat apparu, disparu ou révisé entre les
transactions arrête donc la reprise.

La fenêtre pré-FR → post-EN est une maintenance staging quiescée : l'API, le
runtime acquisition et les quatre services d'ingestion sont inactifs, et seuls
les timers qui étaient actifs sont restaurés. Un watchdog systemd borné à vingt
minutes restaure automatiquement l'API et ces timers si la session opérateur
disparaît. Avant chacune des cinq phases pre-FR, FR, post-FR, EN et post-EN, son
réarmement exige le timer watchdog exactement `active` et son service exactement
`inactive`, puis revalide que l'API, les cinq services writers et leurs cinq
timers sont exactement `inactive`. Après restart, ces treize états sont prouvés
une seconde fois. Chaque snapshot et chaque backfill porte
`RuntimeMaxSec=5min`, donc reste strictement sous les vingt minutes. Tout échec
de réarmement, de preuve de quiescence ou timeout échoue fermé avant la phase
suivante. La restauration explicite annule ce watchdog, prouve readiness 8000
et précède tout smoke navigateur. Aucun provider, modèle ou worker IA n'est
activé par cette quiescence.

Vérifier ensuite en lecture seule, toujours au seul compte approuvé : statuts
`FALLBACK`, variantes `FACTUAL_FALLBACK`, preuve non vide sur chaque claim,
aucun `PASS/FULL`, aucun doublon actif et payload strictement décodable. Les
prédicats attendus sont `provider IS NULL`, `model_id IS NULL`,
`prompt_version IS NULL`, `qa_provider IS NULL` et `qa_model_id IS NULL`.

Un historique n'est jamais fabriqué pour ce smoke : aucune révision ICP/source
n'est modifiée et aucune publication supplémentaire n'est autorisée au-delà des
deux backfills bornés ci-dessus. La preuve factuelle courante est obligatoire
et indépendante. La même lecture découvre seulement un état historique opaque
`available|NOT_APPLICABLE_NO_LEGITIMATE_HISTORY`; un éventuel artefact doit
être légitimement supersédé, compatible avec la révision courante et la locale
du compte. Sur une table 0028 fraîche,
`NOT_APPLICABLE_NO_LEGITIMATE_HISTORY` est normal : il autorise le statut
global `PASS` si toutes les surfaces courantes passent. Le smoke historique
devient bloquant uniquement lorsqu'un artefact légitimement supersédé a
réellement été découvert. Les identifiants ne sont transportés vers le
navigateur que pour l'état `available`, sans être affichés ou consignés.

~~~bash
KIVOU_QA_FACTUAL_PROOF=$(ssh kivou-staging 'bash -s' -- \
  "$KIVOU_RELEASE_DIR" "$KIVOU_FINAL_SHA" \
  "$KIVOU_QA_APPROVED_FINGERPRINT" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_FINAL_SHA=$2
KIVOU_QA_APPROVED_FINGERPRINT=$3
KIVOU_FINAL_SHORT=$(printf '%s' "$KIVOU_FINAL_SHA" | cut -c1-12)
printf '%s\n' "$KIVOU_QA_APPROVED_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'
sudo systemd-run --quiet --wait --collect --pipe \
  --unit="kivou-card-factual-proof-$KIVOU_FINAL_SHORT" --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile=/etc/kivou/card-presentation-qa.env \
  --setenv="KIVOU_QA_APPROVED_FINGERPRINT=$KIVOU_QA_APPROVED_FINGERPRINT" \
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
    expected = os.environ["KIVOU_QA_APPROVED_FINGERPRINT"]
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
            "WHERE account_id=:account_id AND published_at IS NOT NULL "
            "AND superseded_at IS NULL"
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
    history = {"status": "NOT_APPLICABLE_NO_LEGITIMATE_HISTORY"}
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
  ((.history.status == "NOT_APPLICABLE_NO_LEGITIMATE_HISTORY" and
    (.history | keys) == ["status"]) or
   (.history.status == "available" and
    (.history.signal_id | type == "string" and test("^[0-9a-f]{64}$")) and
    (.history.artifact_id | type == "string" and test("^[0-9a-f]{64}$")) and
    (.history.version | type == "number" and . >= 1 and floor == .)))
' >/dev/null
if test "$KIVOU_ROLLOUT_PATH" = resume_51202525; then
  printf '%s' "$KIVOU_QA_FACTUAL_PROOF" | \
    jq -e --argjson expected "$KIVOU_RECOVERY_CANDIDATE_COUNT" \
      '.fr == $expected and .en == $expected' >/dev/null
fi
KIVOU_HISTORICAL_STATUS=$(printf '%s' "$KIVOU_QA_FACTUAL_PROOF" | \
  jq -r '.history.status')
case "$KIVOU_HISTORICAL_STATUS" in
  (NOT_APPLICABLE_NO_LEGITIMATE_HISTORY) ;;
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
printf '%s\n' "$KIVOU_QA_APPROVED_FINGERPRINT" | grep -Eq '^[0-9a-f]{16}$'
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
KIVOU_QA_BROWSER_READ_DATE=$(date -u +%F)
printf '%s\n' "$KIVOU_QA_BROWSER_READ_DATE" | \
  grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
(
  cd frontend
  KIVOU_QA_STORAGE_STATE="$KIVOU_QA_STORAGE_STATE_REAL" \
  KIVOU_QA_BROWSER_READ_DATE="$KIVOU_QA_BROWSER_READ_DATE" \
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

async function verifyPublishedApi(page, browserReadDate) {
  return page.evaluate(async (readDate) => {
    const feedResponse = await fetch(
      `/signals?freshness=new&limit=20&offset=0`,
      { credentials: 'same-origin' },
    )
    if (feedResponse.status !== 200) throw new Error()
    const feed = await feedResponse.json()
    if (feed.read_at !== readDate || feed.freshness !== 'new' ||
        feed.page?.limit !== 20 || feed.page.offset !== 0 ||
        !Array.isArray(feed.items)) throw new Error()
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
    const pinnedIndex = feed.items.findIndex((item) => (
      item && item.locked === false && Boolean(item.presentation)
    ))
    if (pinnedIndex < 0) throw new Error()
    const item = feed.items[pinnedIndex]
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
        detail.presentation.version !== artifact.version ||
        detail.presentation.content?.headline !== artifact.content.headline) {
      throw new Error()
    }
    if (typeof locked[0].headline !== 'string' ||
        locked[0].headline.length === 0) throw new Error()
    return {
      lockedSignalId: locked[0].signal_id,
      lockedHeadline: locked[0].headline,
      pinnedIndex,
      pinnedSignalId: item.signal_id,
      pinnedArtifactId: artifact.artifact_id,
      pinnedVersion: artifact.version,
      pinnedHeadline: artifact.content.headline,
    }
  }, browserReadDate)
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
  const selection = page.locator('.signal-list .signal-item').nth(api.pinnedIndex)
  requireTrue(await selection.count() === 1)
  await selection.waitFor()
  requireTrue(await selection.evaluate((element) => (
    !element.classList.contains('is-locked')
  )))
  const selectedHeadline = selection.getByText(api.pinnedHeadline, { exact: true })
  requireTrue(await selectedHeadline.count() === 1)
  await selectedHeadline.waitFor()
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
  const visibleDetailPane = page.locator(
    `[data-master-detail-pane="detail"]:visible`,
  )
  requireTrue(await visibleDetailPane.count() === 1)
  const detailHeadline = visibleDetailPane.getByRole('heading', {
    name: api.pinnedHeadline, exact: true,
  })
  requireTrue(await detailHeadline.count() === 1)
  await detailHeadline.waitFor()
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
  const browserReadDate = process.env.KIVOU_QA_BROWSER_READ_DATE
  const expectedFingerprint = process.env.KIVOU_QA_APPROVED_FINGERPRINT
  const storageState = process.env.KIVOU_QA_STORAGE_STATE
  const evidenceDir = process.env.KIVOU_BROWSER_EVIDENCE_DIR
  requireTrue(Boolean(origin && browserReadDate && expectedFingerprint &&
    storageState && evidenceDir))
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
      const api = await verifyPublishedApi(page, browserReadDate)
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
artefact supersédé légitime n'existe, inscrire
`NOT_APPLICABLE_NO_LEGITIMATE_HISTORY` sans fabriquer de révision : les preuves
courantes peuvent conclure globalement `PASS`, sans prétendre qu'un parcours
historique a été exécuté. Si l'état est `available`, le second smoke ci-dessous
devient bloquant et prouve le pin exact, la version, le headline dans la pane
détail et les GET détail/note 200, puis rejoue l'audit journal depuis la
frontière antérieure.

~~~bash
case "$KIVOU_HISTORICAL_STATUS" in
  (NOT_APPLICABLE_NO_LEGITIMATE_HISTORY)
    KIVOU_HISTORICAL_SMOKE_STATUS=NOT_APPLICABLE_NO_LEGITIMATE_HISTORY
    KIVOU_ROLLOUT_STATUS=PASS
    printf '%s\n' \
      'historical_smoke=NOT_APPLICABLE_NO_LEGITIMATE_HISTORY'
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
  const expectedFingerprint = process.env.KIVOU_QA_APPROVED_FINGERPRINT
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

Le rapport final doit associer sans ambiguïté : chemin initial ou reprise, SHA
final `main`, run CI et étapes, backup (nom/taille/SHA-256/TOC/restore),
transition dynamique `0027_signal_notes → 0028_card_presentation` ou
`0028_card_presentation → 0028_card_presentation`, releases backend/frontend,
compteurs FR/EN, captures inspectées, matrice Dashboard/Entreprises/Signaux,
deep-links/Retour/focus/scroll/teaser/console, rollback targets et éventuel
rollback exécuté.

Valider et inscrire le statut historique et le statut global sans les
réinterpréter :

~~~bash
: "${KIVOU_HISTORICAL_SMOKE_STATUS:?STOP: historical smoke status absent}"
: "${KIVOU_ROLLOUT_STATUS:?STOP: rollout status absent}"
for KIVOU_WRITER_PROOF in \
  "$KIVOU_WRITER_STATE_FILE" "$KIVOU_WRITER_RESUME_FILE"; do
  test -f "$KIVOU_WRITER_PROOF"
  test ! -L "$KIVOU_WRITER_PROOF"
  test "$(stat -c '%U:%a' "$KIVOU_WRITER_PROOF")" = "$(id -un):600"
done
unset KIVOU_WRITER_PROOF
KIVOU_WRITER_STATE_SHA256=$(sha256sum "$KIVOU_WRITER_STATE_FILE" | \
  awk '{print $1}')
KIVOU_WRITER_RESUME_SHA256=$(sha256sum "$KIVOU_WRITER_RESUME_FILE" | \
  awk '{print $1}')
test "$(printf '%s\n' "$KIVOU_WRITER_STATE_SHA256" \
  "$KIVOU_WRITER_RESUME_SHA256" | grep -Ec '^[0-9a-f]{64}$')" = 2
case "$KIVOU_ROLLOUT_PATH" in
  (initial_0027)
    KIVOU_DATABASE_TRANSITION=0027_signal_notes-to-0028_card_presentation
    KIVOU_RECOVERY_STATUS=NOT_APPLICABLE_INITIAL_ROLLOUT
    KIVOU_RECOVERY_BASELINE_SHA256=NOT_APPLICABLE
    KIVOU_RECOVERY_POST_FR_SHA256=NOT_APPLICABLE
    KIVOU_RECOVERY_POST_EN_SHA256=NOT_APPLICABLE
    ;;
  (resume_51202525)
    KIVOU_DATABASE_TRANSITION=0028_card_presentation-to-0028_card_presentation
    KIVOU_RECOVERY_STATUS=FR_BASELINE_PRESERVED
    for KIVOU_RECOVERY_PROOF in \
      "$KIVOU_RECOVERY_BASELINE" "$KIVOU_RECOVERY_POST_FR" \
      "$KIVOU_RECOVERY_POST_EN"; do
      test -f "$KIVOU_RECOVERY_PROOF"
      test ! -L "$KIVOU_RECOVERY_PROOF"
      test "$(stat -c '%U:%a' "$KIVOU_RECOVERY_PROOF")" = "$(id -un):600"
    done
    unset KIVOU_RECOVERY_PROOF
    jq -e --slurpfile baseline "$KIVOU_RECOVERY_BASELINE" '
      . as $post
      | ($baseline[0] | type == "object" and (.artifacts | length) == 8)
      and (type == "object")
      and all($baseline[0].artifacts[];
        del(.state) as $old
        | any($post.artifacts[]; del(.state) == $old))
    ' "$KIVOU_RECOVERY_POST_FR" >/dev/null
    test "$(sha256sum "$KIVOU_RECOVERY_BASELINE" | awk '{print $1}')" = \
      "$KIVOU_RECOVERY_BASELINE_SHA256"
    test "$(sha256sum "$KIVOU_RECOVERY_POST_FR" | awk '{print $1}')" = \
      "$KIVOU_RECOVERY_POST_FR_SHA256"
    test "$(sha256sum "$KIVOU_RECOVERY_POST_EN" | awk '{print $1}')" = \
      "$KIVOU_RECOVERY_POST_EN_SHA256"
    KIVOU_RECOVERY_FINAL_LIVE_PAYLOAD=$(kivou_capture_recovery_fr_snapshot \
      "$KIVOU_RELEASE_DIR" post_en)
    KIVOU_RECOVERY_FINAL_LIVE_SHA256=$(printf '%s\n' \
      "$KIVOU_RECOVERY_FINAL_LIVE_PAYLOAD" | sha256sum | awk '{print $1}')
    unset KIVOU_RECOVERY_FINAL_LIVE_PAYLOAD
    printf '%s\n' "$KIVOU_RECOVERY_FINAL_LIVE_SHA256" | \
      grep -Eq '^[0-9a-f]{64}$'
    test "$KIVOU_RECOVERY_FINAL_LIVE_SHA256" = \
      "$KIVOU_RECOVERY_POST_EN_SHA256"
    ;;
  (*) exit 69 ;;
esac
case "$KIVOU_HISTORICAL_SMOKE_STATUS:$KIVOU_ROLLOUT_STATUS" in
  (PASS:PASS|NOT_APPLICABLE_NO_LEGITIMATE_HISTORY:PASS) ;;
  (*) exit 69 ;;
esac
printf 'historical_smoke_status=%s rollout_status=%s\n' \
  "$KIVOU_HISTORICAL_SMOKE_STATUS" "$KIVOU_ROLLOUT_STATUS"
printf 'writer_quiescence_sha256=%s writer_resume_sha256=%s\n' \
  "$KIVOU_WRITER_STATE_SHA256" "$KIVOU_WRITER_RESUME_SHA256"
printf 'rollout_path=%s recovery_source_sha=%s database_transition=%s recovery_status=%s\n' \
  "$KIVOU_ROLLOUT_PATH" "$KIVOU_RECOVERY_SOURCE_SHA" \
  "$KIVOU_DATABASE_TRANSITION" "$KIVOU_RECOVERY_STATUS"
printf 'original_rollout_status=%s recovery_baseline_sha256=%s recovery_post_fr_sha256=%s recovery_post_en_sha256=%s\n' \
  "$KIVOU_ORIGINAL_ROLLOUT_STATUS" "$KIVOU_RECOVERY_BASELINE_SHA256" \
  "$KIVOU_RECOVERY_POST_FR_SHA256" "$KIVOU_RECOVERY_POST_EN_SHA256"
~~~

Si un artefact supersédé légitime a été découvert, son smoke doit être `PASS` :
tout échec est bloquant et interdit de présenter la livraison comme complète.
Le statut `NOT_APPLICABLE_NO_LEGITIMATE_HISTORY` signifie qu'aucun artefact supersédé légitime
n'existait après la migration additive; il autorise le
`rollout_status=PASS` pour les surfaces courantes, mais ne permet pas de
présenter le parcours historique comme exécuté. Dans tous les cas, ne jamais fabriquer
de révision ou de donnée historique.

Le rapport doit aussi porter la ligne :

```text
Production : aucun déploiement, aucune mutation.
```

Terminer par :

```text
Activation IA : DÉSACTIVÉE — aucun provider, modèle, prompt, QA provider ou worker live approuvé ; staging limité à l’architecture et aux FALLBACK/FACTUAL_FALLBACK factuels hors GET.
```
