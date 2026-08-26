# Runtime d'exploitation Kivou

Ce dossier ne contient que ce qui doit être **versionné pour être reproductible**.
Aujourd'hui : la sauvegarde PostgreSQL (RTL-03 / #39), le runtime des alertes
transactionnelles (RTL-05), les ingestions DECP (#77) et TED (#82) bornées et l'outillage de
rotation expurgée des secrets de staging (#81).

> Un service systemd qui appelle un fichier absent de la branche déployable
> échoue au premier déploiement propre. C'est exactement ce qu'a révélé #39 :
> `kivou-backup.service` sortait en code 69 parce que le script ne vivait que
> sur une branche jamais intégrée.

## Ce que garantit `bin/kivou-backup.sh`

| Garantie | Comment |
| --- | --- |
| Une seule sauvegarde à la fois | `flock` sur un descripteur tenu par le processus |
| Aucun secret sur la ligne de commande | le mot de passe passe par `PGPASSWORD` |
| Aucun secret dans le journal | aucun message n'interpole l'URL |
| Aucun fichier lisible par des tiers | `umask 077`, répertoire `700`, dump `600` |
| Aucune sauvegarde partielle publiée | écriture en `.part`, renommage atomique après contrôle |
| Aucun dump accepté sans relecture | taille minimale **puis** `pg_restore --list` |
| Aucune purge après un échec | rétention exécutée en dernier, seulement après succès |

Ce n'est **pas** un plan de reprise d'activité : une copie posée sur l'hôte de la
base disparaît avec l'hôte. La copie **hors hôte** reste une porte de production
distincte.

## Configuration

Toutes les variables sont lues dans l'environnement ; aucune valeur par défaut
ne contient de secret.

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `KIVOU_DATABASE_URL` | — (**requis**) | URL SQLAlchemy ; `postgresql+psycopg://`, `postgres://` et `postgresql://` sont normalisées |
| `KIVOU_BACKUP_DIR` | `/srv/kivou/backups` | destination |
| `KIVOU_BACKUP_RETENTION_DAYS` | `14` | âge au-delà duquel un dump est purgé |
| `KIVOU_BACKUP_MIN_BYTES` | `4096` | seuil sous lequel un dump est tenu pour raté |
| `KIVOU_BACKUP_LOCK_FILE` | `<dir>/kivou-backup.lock` | verrou |
| `KIVOU_PG_DUMP` / `KIVOU_PG_RESTORE` | `pg_dump` / `pg_restore` | chemins, si la distribution les versionne |

Codes de sortie : `64` configuration, `69` dépendance manquante, `70` sauvegarde
refusée, `75` verrou déjà tenu.

## Installation

`KIVOU_DATABASE_URL` vit dans `/etc/kivou/staging.env`, **hors du dépôt**. Ce
fichier porte le mot de passe de la base : il ne doit jamais y entrer.

```bash
sudo install -o kivou -g kivou -m 700 -d /srv/kivou/backups
sudo cp ops/systemd/kivou-backup.service ops/systemd/kivou-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kivou-backup.timer
```

## Vérification après déploiement

```bash
sudo systemctl start kivou-backup.service            # 1. doit réussir
systemctl status kivou-backup.service                # 2. exit 0
sudo ls -l /srv/kivou/backups                        # 3. dump horodaté, mode 600
sudo -u kivou pg_restore --list \
     /srv/kivou/backups/kivou-<horodatage>.dump      # 4. table des matières lisible
systemctl list-timers kivou-backup.timer             # 5. timer actif
sudo journalctl -u kivou-backup -n 50 --no-pager     # 6. aucun secret
```

Le point 6 n'est pas une formalité : c'est le seul contrôle qui distingue un
journal exploitable d'une fuite de mot de passe dans les logs d'un hôte partagé.

## Tests

`tests/test_ops_backup_runtime.py` exerce le vrai script avec de faux `pg_dump`
et `pg_restore` et des répertoires temporaires — sans base, sans réseau, sans
jamais toucher une base active.

```bash
bash -n ops/bin/kivou-backup.sh
uv run pytest tests/test_ops_backup_runtime.py
```

Ce que ces tests **ne** prouvent pas : qu'un dump PostgreSQL réel se restaure.
Cela demande un serveur et une base isolée — c'est la validation staging de #39,
et elle reste à faire.

## Alertes transactionnelles RTL-05

Le couple `kivou-alerts.service` / `kivou-alerts.timer` exécute
`python -m signals.alerts` au plus une fois par heure, avec un léger délai
aléatoire. Le timer ne transforme donc pas la cadence `priority` en temps réel.
Le verrou hôte `flock` couvre les déclenchements systemd et le lease PostgreSQL
couvre aussi deux processus ou deux hôtes. Une contention normale retourne 0 ;
une panne technique ou un incident apparu pendant le cycle retourne un code non
nul.

La commande lit exclusivement l'environnement. Elle n'accepte aucune URL de
base sur la ligne de commande et n'imprime ni adresse, ni secret, ni texte
d'exception. Les variables applicatives requises sont documentées dans
`.env.example`; leurs valeurs vivent dans `/etc/kivou/staging.env`, hors dépôt.

### Installation staging

```bash
sudo install -o kivou -g kivou -m 700 -d /srv/kivou/run
sudo install -o root -g root -m 644 \
  ops/systemd/kivou-alerts.service \
  ops/systemd/kivou-alerts.timer \
  /etc/systemd/system/
sudo systemd-analyze verify \
  /etc/systemd/system/kivou-alerts.service \
  /etc/systemd/system/kivou-alerts.timer
sudo systemctl daemon-reload
sudo systemctl start kivou-alerts.service
sudo systemctl status kivou-alerts.service --no-pager
sudo journalctl -u kivou-alerts.service -n 50 --no-pager
sudo systemctl enable --now kivou-alerts.timer
systemctl list-timers kivou-alerts.timer --no-pager
```

Le démarrage manuel précède l'activation du timer. Avant toute exécution hors
simulation, la boîte destinataire doit être synthétique, contrôlée et autorisée.

### Simulation et diagnostic

```bash
sudo systemd-run \
  --unit=kivou-alerts-dry-run \
  --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  /srv/kivou/app/.venv/bin/python -m signals.alerts --dry-run
systemctl cat kivou-alerts.service kivou-alerts.timer
sudo journalctl -u kivou-alerts.service -n 50 --no-pager
```

La simulation valide la configuration sans effectuer d'appel SMTP. La lecture
du journal doit confirmer uniquement des compteurs et des codes opérationnels.

### Rollback

```bash
sudo systemctl disable --now kivou-alerts.timer
sudo systemctl stop kivou-alerts.service
sudo cp /chemin/controle/kivou-alerts.service /etc/systemd/system/
sudo cp /chemin/controle/kivou-alerts.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl reset-failed kivou-alerts.service
```

Le rollback applicatif restaure ensuite le SHA précédent. Le downgrade de la
migration `0023` n'est exécuté que si la procédure de release le décide
explicitement ; il conserve l'historique antérieur des livraisons. Si aucun
timer antérieur n'existait, les deux commandes `cp` sont omises et les unités
restent simplement désactivées.

## Ingestion DECP bornée (#77)

`kivou-ingest-decp.service` traite DECP par lots bornés à l'intérieur de journées
calendaires. Le curseur versionné conserve le jour, le total observé et l'offset intra-journée
dans `ingestion_checkpoint` après chaque lot persisté. Lorsque le
jour est épuisé, le curseur avance au lendemain avec un offset nul. Un quota ou
le budget de vingt minutes termine le passage avec succès et laisse explicitement
du travail pour le prochain déclenchement. Une variation du total fournisseur
réinitialise le jour à l'offset zéro ; le rejeu reste idempotent. Une mutation
pendant un lot échoue en mode fermé sans avancer le curseur. Avant chaque démarrage,
les anciennes lignes
`running` sont fermées avec le code machine `stale_run_reconciled`, sans effacer
les faits publics, les rapprochements ni les signaux déjà produits.

Les limites viennent de `/etc/kivou/staging.env` :
`KIVOU_DECP_MAX_WINDOWS_PER_RUN`, `KIVOU_DECP_BATCH_SIZE`,
`KIVOU_DECP_TIME_BUDGET_SECONDS`,
`KIVOU_DECP_OVERLAP_DAYS` et `KIVOU_INGESTION_STALE_RUN_SECONDS`. Elles doivent
toutes être des entiers strictement positifs. Le verrou hôte vit dans
`/run/kivou`, créé par `RuntimeDirectory`; une contention normale est un succès
sans seconde exécution. `MAX_WINDOWS` reste le quota strict de journées
finalisées ; les lots d'une même journée ne le consomment pas. Le timer est
horaire et utilise `Persistent=true` ; chaque déclenchement reprend exactement
l'offset durable du précédent passage.

### Installation et passage manuel

```bash
sudo install -o root -g root -m 644 \
  ops/systemd/kivou-ingest-decp.service \
  ops/systemd/kivou-ingest-decp.timer \
  /etc/systemd/system/
sudo systemd-analyze verify \
  /etc/systemd/system/kivou-ingest-decp.service \
  /etc/systemd/system/kivou-ingest-decp.timer
sudo systemctl daemon-reload
sudo systemctl start kivou-ingest-decp.service
sudo systemctl status kivou-ingest-decp.service --no-pager
sudo systemctl enable --now kivou-ingest-decp.timer
systemctl list-timers kivou-ingest-decp.timer --no-pager
```

Après deux déclenchements, vérifier le curseur, les statuts et les durées sans
afficher de donnée client ni de secret :

```sql
SELECT source, cursor, window_end, status, last_completed_at
FROM ingestion_checkpoint WHERE source = 'decp';
SELECT status, error_category, count(*)
FROM ingestion_run WHERE source = 'decp'
GROUP BY status, error_category ORDER BY status, error_category;
```

Le journal attendu contient une ligne synthétique `source=decp`, des compteurs,
`status`, `pending` et `duration`; il ne contient aucun payload fournisseur.

### Rollback

```bash
sudo systemctl disable --now kivou-ingest-decp.timer
sudo systemctl stop kivou-ingest-decp.service
sudo install -o root -g root -m 644 \
  /chemin/rollback/kivou-ingest-decp.service \
  /chemin/rollback/kivou-ingest-decp.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl reset-failed kivou-ingest-decp.service
```

Restaurer ensuite le SHA applicatif précédent. Ce correctif ne crée aucune
migration et son rollback ne modifie aucune donnée métier.

## Ingestion TED bornée (#82)

`kivou-ingest-ted.service` exécute une seule convergence TED séquentielle. La
recherche et chaque téléchargement XML partagent la même cadence conservative.
Les réponses `202`, `429` et `5xx`, ainsi que les erreurs réseau, utilisent un
backoff exponentiel borné ; `Retry-After` est respecté lorsqu'il demande une
attente plus longue qui reste dans le budget total. Aucune réponse fournisseur
brute n'est inscrite dans le journal ou dans la base.

Le curseur versionné vit dans `ingestion_checkpoint`. Il fixe la fenêtre, la
page, `pending_publication_numbers` et l'index suivant. La page de recherche est
checkpointée avant son premier XML, puis chaque notice n'avance l'index qu'après
la persistance idempotente. Un arrêt peut donc rejouer au plus une notice ; il
ne repart pas de `cursor=null`. Le quota de notices et le budget de vingt minutes
terminent proprement un passage avec `status=success` et `pending=1`. Une limite
fournisseur épuisée reste un échec `rate_limited` non nul, avec la progression
déjà finalisée conservée.

Les cinq limites strictement positives viennent de
`/etc/kivou/staging.env` : `KIVOU_TED_REQUEST_INTERVAL_SECONDS`,
`KIVOU_TED_MAX_ATTEMPTS`, `KIVOU_TED_MAX_RETRY_SECONDS`,
`KIVOU_TED_MAX_RECORDS_PER_RUN` et `KIVOU_TED_TIME_BUDGET_SECONDS`.

### Installation et preuve manuelle obligatoire

Le fichier timer est versionné mais cette installation ne l'active pas. **Ne pas activer le timer avant** qu'un passage manuel complet ait réussi et que le
curseur ait avancé.

```bash
sudo install -o root -g root -m 644 \
  ops/systemd/kivou-ingest-ted.service \
  ops/systemd/kivou-ingest-ted.timer \
  /etc/systemd/system/
sudo systemd-analyze verify \
  /etc/systemd/system/kivou-ingest-ted.service \
  /etc/systemd/system/kivou-ingest-ted.timer
sudo systemctl daemon-reload
systemctl is-enabled kivou-ingest-ted.timer  # attendu avant preuve : disabled
sudo systemctl start kivou-ingest-ted.service
sudo systemctl status kivou-ingest-ted.service --no-pager
```

Comparer ensuite uniquement les états et compteurs opérationnels :

```sql
SELECT source, cursor, window_end, status, last_completed_at
FROM ingestion_checkpoint WHERE source = 'ted';
SELECT status, error_category, count(*)
FROM ingestion_run WHERE source = 'ted'
GROUP BY status, error_category ORDER BY status, error_category;
SELECT source, status, window_end
FROM ingestion_checkpoint WHERE source IN ('simap', 'boamp');
```

SIMAP et BOAMP doivent rester en succès. Après cette preuve manuelle seulement :

```bash
sudo systemctl enable --now kivou-ingest-ted.timer
systemctl list-timers kivou-ingest-ted.timer --no-pager
systemctl is-enabled kivou-ingest-ted.timer
sudo journalctl -u kivou-ingest-ted.service -n 50 --no-pager
```

Vérifier un déclenchement systemd, puis le déclenchement planifié suivant. Les
deux passages doivent finir sans exécution `running` orpheline, le curseur doit
avancer et `systemctl is-enabled` doit rester `enabled`. Le journal attendu ne
contient qu'une ligne `source=ted`, des compteurs, `status`, `pending` et
`duration`, jamais un XML ou une réponse HTTP.

### Rollback

```bash
sudo systemctl disable --now kivou-ingest-ted.timer
sudo systemctl stop kivou-ingest-ted.service
sudo install -o root -g root -m 644 \
  /chemin/rollback/kivou-ingest-ted.service \
  /chemin/rollback/kivou-ingest-ted.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl reset-failed kivou-ingest-ted.service
```

Restaurer ensuite le SHA applicatif précédent. Aucune migration n'est associée
à #82 ; le rollback ne supprime ni curseur, ni fait public, ni signal.

## Hygiène des secrets de staging (#81)

La procédure complète est
[`docs/runbooks/09-staging-secret-rotation.md`](../docs/runbooks/09-staging-secret-rotation.md).
Elle reste strictement limitée au staging et ne contient aucune valeur réelle.

`bin/kivou_secret_hygiene.py` reste entièrement limité à la bibliothèque standard
Python et expose trois sous-commandes :

- `set-secret` lit une valeur fournisseur autorisée par saisie masquée sur
  `/dev/tty`, exige un alphabet ASCII non ambigu pour `EnvironmentFile=` et une
  clé Stripe `sk_test_` ou `rk_test_`, puis met à jour atomiquement le fichier
  partiel sans écho ;
- `replace-env` remplace atomiquement les quatre variables autorisées, conserve
  toutes les autres lignes ainsi que uid, gid et mode du fichier cible, puis
  publie seulement deux compteurs ;
- `audit-journal` lit un flux de journal sur stdin, compare en mémoire une ou
  plusieurs générations complètes de quatre valeurs et publie seulement
  `secret_values_checked`, `matching_lines` et `matching_occurrences`. Une
  correspondance rend le code de sortie non nul.

`bin/kivou_rotate_postgres_secret.py` est un second petit exécutable. Il importe
Psycopg statiquement depuis l'environnement virtuel du projet, réutilise les
primitives de lecture `0600` et de remplacement atomique du CLI d'hygiène,
génère en mémoire le nouveau mot de passe du rôle `kivou_app`, écrit d'abord la
candidate, puis utilise le protocole libpq sans placer de secret dans les
arguments ou les sorties.

Les commandes lisent les valeurs uniquement depuis des fichiers `0600`
réguliers et non symboliques. Elles refusent les noms hors allowlist, doublons,
valeurs vides ou multilignes et ne rendent jamais une exception contenant une
valeur. Les arguments ne portent que des chemins et, pour la saisie masquée, un
nom de clé autorisé :

```bash
sudo /usr/bin/python3.12 ops/bin/kivou_secret_hygiene.py \
  set-secret SMTP_PASSWORD \
  --values-file /run/kivou-secret-rotation/new.values
sudo /srv/kivou/app/.venv/bin/python \
  /srv/kivou/app/ops/bin/kivou_rotate_postgres_secret.py \
  --old-env-file /etc/kivou/staging.env \
  --values-file /run/kivou-secret-rotation/new.values
sudo /usr/bin/python3.12 ops/bin/kivou_secret_hygiene.py \
  replace-env \
  --values-file /run/kivou-secret-rotation/new.values \
  --target /etc/kivou/staging.env
sudo /bin/bash -o pipefail -c '
  /usr/bin/journalctl --all --no-pager --output=export |
    /usr/bin/python3.12 \
      /srv/kivou/app/ops/bin/kivou_secret_hygiene.py \
      audit-journal \
      /run/kivou-secret-rotation/old.values \
      /run/kivou-secret-rotation/new.values
'
```

Le format export couvre tous les champs journald, dont `_CMDLINE`, et `pipefail`
interdit de valider un audit si la lecture du journal a échoué.

Toute simulation applicative qui dépend des secrets déployés doit rester une
unité transitoire `systemd-run` avec
`--property=EnvironmentFile=/etc/kivou/staging.env`, comme pour les alertes.

## Reverse proxy public de staging (#84)

Cette procédure installe ensemble le journal nginx expurgé, les quatre routes
sensibles, le runtime API sans journal d'accès Uvicorn et un rollback qui ne
descend jamais sous cette limite. Elle s'exécute depuis un shell de connexion
sur kivou-staging. La reprise et le rollback utilisent un état root-only fixe :
ils restent autonomes si le shell initial disparaît après une erreur.

Le runtime webhook Instantly conserve son groupe de configuration atomique :
`KIVOU_INSTANTLY_WEBHOOK_SECRET`, `KIVOU_INSTANTLY_WORKSPACE_REF`,
`KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY`,
`KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION`,
`KIVOU_SUPPRESSION_HMAC_KEY`, `KIVOU_SUPPRESSION_HMAC_KEY_VERSION`,
`KIVOU_RESPONSE_SOURCE_HMAC_KEY`,
`KIVOU_RESPONSE_SOURCE_HMAC_KEY_VERSION`,
`KIVOU_RESPONSE_CONTENT_HMAC_KEY` et
`KIVOU_RESPONSE_CONTENT_HMAC_KEY_VERSION`. Les dix variables sont lues depuis
le fichier d'environnement protégé par systemd, jamais depuis ce runbook :
toutes absentes, le webhook répond 503 ; partiellement présentes, l'API refuse
de démarrer sans imprimer leurs valeurs.

Les quatre variables facultatives de rétention
`KIVOU_INSTANTLY_WEBHOOK_RETAINED_FINGERPRINT_KEYS_JSON`,
`KIVOU_SUPPRESSION_RETAINED_KEYS_JSON`,
`KIVOU_RESPONSE_SOURCE_RETAINED_KEYS_JSON` et
`KIVOU_RESPONSE_CONTENT_RETAINED_KEYS_JSON` portent des objets JSON bornés à
huit versions par keyring, clé courante comprise. Avant de remplacer une
version déjà référencée par des événements ou suppressions durables, conserver
son secret dans le keyring correspondant ; la rotation ne réinterprète jamais
l'historique avec une nouvelle clé.

No migration, provider call, e-mail, production action, or secret argument belongs to this procedure.
Les seules substitutions du gabarit de site sont STAGING_HOST et
KIVOU_API_PORT. Aucune valeur de /etc/kivou/staging.env n'est chargée dans le
shell ou placée dans argv.

### Préparer la release exacte et le candidat nginx isolé

Valider l'hôte, n'accepter que le port vert 8001 ou le port normal 8000, puis
saisir le SHA main préalablement revu. Le fetch ne modifie ni l'arbre déployé ni
le lien /srv/kivou/app. La deploy key read-only côté GitHub ne doit disposer
d'aucun droit d'écriture sur le dépôt.

~~~bash
set -euo pipefail
KIVOU_STAGING_HOST=staging.kivou.eu
KIVOU_API_PORT=8001

case "$KIVOU_STAGING_HOST" in
  (*[!a-z0-9.-]*|'') printf '%s\n' 'hôte staging invalide' >&2; exit 64 ;;
  (*) ;;
esac
case "$KIVOU_API_PORT" in
  (8000|8001) ;;
  (*) printf '%s\n' 'port API hors liste revue' >&2; exit 64 ;;
esac

# set KIVOU_RELEASE_SHA to the reviewed main SHA
printf '%s' 'SHA main revu (40 hex): ' >/dev/tty
IFS= read -r KIVOU_RELEASE_SHA </dev/tty
printf '%s\n' "$KIVOU_RELEASE_SHA" | grep -Eq '^[0-9a-f]{40}$'

KIVOU_RELEASE_REMOTE=git@github.com:bruppacherrodrigue-art/Kivou.git
KIVOU_DEPLOY_KEY=/srv/kivou/.ssh/github_deploy
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_DEPLOY_KEY")" = "kivou:kivou:600"
KIVOU_KNOWN_HOSTS=/etc/nginx/kivou-github-known-hosts
KIVOU_KNOWN_HOSTS_NEW=/etc/nginx/kivou-github-known-hosts.new
sudo test -d /etc/nginx
sudo -u kivou test ! -w /etc/nginx
sudo install -o root -g root -m 644 /dev/null "$KIVOU_KNOWN_HOSTS_NEW"
printf '%s\n' \
  'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' |
  sudo tee "$KIVOU_KNOWN_HOSTS_NEW" >/dev/null
test "$(sudo ssh-keygen -lf "$KIVOU_KNOWN_HOSTS_NEW" -E sha256 |
  awk '{print $2}')" = \
  'SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'
sudo mv -f "$KIVOU_KNOWN_HOSTS_NEW" "$KIVOU_KNOWN_HOSTS"
sudo test -f "$KIVOU_KNOWN_HOSTS"
sudo test ! -L "$KIVOU_KNOWN_HOSTS"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_KNOWN_HOSTS")" = "root:root:644"
sudo -u kivou test -r "$KIVOU_KNOWN_HOSTS"
sudo -u kivou test ! -w "$KIVOU_KNOWN_HOSTS"
test "$(sudo ssh-keygen -lf "$KIVOU_KNOWN_HOSTS" -E sha256 |
  awk '{print $2}')" = \
  'SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'
kivou_git() {
  sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
    /usr/bin/git "$@"
}
KIVOU_GIT_SSH_COMMAND="/usr/bin/ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KIVOU_KNOWN_HOSTS -o GlobalKnownHostsFile=/dev/null -i $KIVOU_DEPLOY_KEY"
KIVOU_REMOTE_MAIN_SHA=$(sudo -u kivou /usr/bin/env -i \
  HOME=/srv/kivou PATH=/usr/bin:/bin \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  GIT_SSH_COMMAND="$KIVOU_GIT_SSH_COMMAND" \
  /usr/bin/git ls-remote --exit-code "$KIVOU_RELEASE_REMOTE" refs/heads/main |
  awk '$2 == "refs/heads/main" {print $1}')
test "$KIVOU_REMOTE_MAIN_SHA" = "$KIVOU_RELEASE_SHA"

KIVOU_RELEASE_UTC=$(date -u +%Y%m%dT%H%M%SZ)
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_RELEASE_SHA" | cut -c1-12)
KIVOU_RELEASE_DIR=/srv/kivou/releases/backend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT
sudo install -o kivou -g kivou -m 755 -d /srv/kivou/releases
sudo test ! -e "$KIVOU_RELEASE_DIR"
kivou_git init --quiet --initial-branch=main "$KIVOU_RELEASE_DIR"
kivou_git -C "$KIVOU_RELEASE_DIR" remote add origin \
  "$KIVOU_RELEASE_REMOTE"
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  GIT_SSH_COMMAND="$KIVOU_GIT_SSH_COMMAND" \
  /usr/bin/git -C "$KIVOU_RELEASE_DIR" fetch --no-tags origin \
  +refs/heads/main:refs/kivou-rollout/reviewed-main
test "$(kivou_git -C "$KIVOU_RELEASE_DIR" \
  rev-parse refs/kivou-rollout/reviewed-main)" = "$KIVOU_RELEASE_SHA"
kivou_git -C "$KIVOU_RELEASE_DIR" \
  cat-file -e "$KIVOU_RELEASE_SHA^{commit}"
kivou_git -C "$KIVOU_RELEASE_DIR" checkout --detach "$KIVOU_RELEASE_SHA"
test "$(kivou_git -C "$KIVOU_RELEASE_DIR" remote get-url origin)" = \
  "$KIVOU_RELEASE_REMOTE"
test "$(kivou_git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = \
  "$KIVOU_RELEASE_SHA"
# git status --porcelain must remain empty before and after dependency sync.
test -z "$(kivou_git -C "$KIVOU_RELEASE_DIR" status --porcelain)"
sudo -u kivou /usr/bin/env --chdir="$KIVOU_RELEASE_DIR" \
  /usr/local/bin/uv sync --frozen --extra server --extra postgres
test -z "$(kivou_git -C "$KIVOU_RELEASE_DIR" status --porcelain)"
~~~

Le candidat vit sous /etc/nginx, appartient à root et contient les six fragments
immuables de la release revue. Le fragment ouvert est copié séparément comme
gate actif en mode 600 ; les autres fichiers restent en mode 644. Les quatre
chemins include du site sont rendus vers ce répertoire, puis nginx lit le
fragment http limits et le site rendu dans une configuration isolée.

~~~bash
KIVOU_NGINX_CANDIDATE=$(sudo mktemp -d /etc/nginx/.kivou-candidate.XXXXXX)
sudo chmod 700 "$KIVOU_NGINX_CANDIDATE"
sudo install -o root -g root -m 644 \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-limits.conf" \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-proxy-params.conf" \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-security-headers.conf" \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-sensitive-link-security-headers.conf" \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-sensitive-links-open.conf" \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-sensitive-links-closed.conf" \
  "$KIVOU_NGINX_CANDIDATE/"
sudo install -o root -g root -m 600 \
  "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-open.conf" \
  "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf"
KIVOU_REVIEWED_OPEN_SHA=$(kivou_git -C "$KIVOU_RELEASE_DIR" show \
  "$KIVOU_RELEASE_SHA:ops/nginx/kivou-sensitive-links-open.conf" |
  sha256sum | awk '{print $1}')
KIVOU_CANDIDATE_OPEN_SHA=$(sudo sha256sum \
  "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf" |
  awk '{print $1}')
test "$KIVOU_CANDIDATE_OPEN_SHA" = "$KIVOU_REVIEWED_OPEN_SHA"
test -z "$(sudo awk 'NF && $1 !~ /^#/ {print}' \
  "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf")"

sed \
  -e "s/STAGING_HOST/$KIVOU_STAGING_HOST/g" \
  -e "s/KIVOU_API_PORT/$KIVOU_API_PORT/g" \
  -e "s#/etc/nginx/kivou-proxy-params.conf#$KIVOU_NGINX_CANDIDATE/kivou-proxy-params.conf#g" \
  -e "s#/etc/nginx/kivou-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-security-headers.conf#g" \
  -e "s#/etc/nginx/kivou-sensitive-link-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-sensitive-link-security-headers.conf#g" \
  -e "s#/etc/nginx/kivou-sensitive-links-gate.conf#$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf#g" \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-staging.conf" |
  sudo tee "$KIVOU_NGINX_CANDIDATE/kivou-staging.test.conf" >/dev/null
sudo chmod 644 "$KIVOU_NGINX_CANDIDATE/kivou-staging.test.conf"

sudo tee "$KIVOU_NGINX_CANDIDATE/nginx.conf" >/dev/null <<EOF
pid $KIVOU_NGINX_CANDIDATE/nginx.pid;
error_log stderr;
events {}
http {
    include /etc/nginx/mime.types;
    include $KIVOU_NGINX_CANDIDATE/kivou-limits.conf;
    include $KIVOU_NGINX_CANDIDATE/kivou-staging.test.conf;
}
EOF
sudo chmod 644 "$KIVOU_NGINX_CANDIDATE/nginx.conf"
sudo nginx -t -c "$KIVOU_NGINX_CANDIDATE/nginx.conf"
~~~

Ce test est obligatoire avant toute publication. Il valide le port 8001, les
certificats existants et toutes les inclusions sans toucher au nginx actif.

### Capturer la preuve antérieure sans en faire un rollback

Après la validation isolée et avant toute mutation live, capturer la
configuration active, le gate ou son absence, la cible applicative et l'unité.
Le snapshot unique est EVIDENCE ONLY. L'état de reprise fixe ne contient que
quatre valeurs non secrètes validées, shell-quotées et publiées atomiquement
en root:root 600.

~~~bash
KIVOU_PREVIOUS_RELEASE=$(sudo readlink -f /srv/kivou/app)
case "$KIVOU_PREVIOUS_RELEASE" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
sudo test -d "$KIVOU_PREVIOUS_RELEASE"
KIVOU_SECURITY_RELEASE=$KIVOU_RELEASE_DIR
case "$KIVOU_SECURITY_RELEASE" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
test "$(kivou_git -C "$KIVOU_SECURITY_RELEASE" rev-parse HEAD)" = \
  "$KIVOU_RELEASE_SHA"
test -z "$(kivou_git -C "$KIVOU_SECURITY_RELEASE" status --porcelain)"

KIVOU_EVIDENCE_DIR=$(sudo mktemp -d /etc/nginx/.kivou-evidence.XXXXXX)
sudo chmod 700 "$KIVOU_EVIDENCE_DIR"
sudo cp -a /etc/nginx/sites-available/kivou \
  "$KIVOU_EVIDENCE_DIR/kivou.site"
sudo cp -a /etc/nginx/conf.d/kivou-limits.conf \
  "$KIVOU_EVIDENCE_DIR/kivou-limits.conf"
sudo cp -a /etc/nginx/kivou-proxy-params.conf \
  "$KIVOU_EVIDENCE_DIR/kivou-proxy-params.conf"
sudo cp -a /etc/nginx/kivou-security-headers.conf \
  "$KIVOU_EVIDENCE_DIR/kivou-security-headers.conf"
if sudo test -e /etc/nginx/kivou-sensitive-links-gate.conf; then
  sudo cp -a /etc/nginx/kivou-sensitive-links-gate.conf \
    "$KIVOU_EVIDENCE_DIR/kivou-sensitive-links-gate.conf"
else
  sudo touch "$KIVOU_EVIDENCE_DIR/kivou-sensitive-links-gate.absent"
fi
printf '%s\n' "$KIVOU_PREVIOUS_RELEASE" |
  sudo tee "$KIVOU_EVIDENCE_DIR/app-target" >/dev/null
printf '%s\n' "$KIVOU_SECURITY_RELEASE" |
  sudo tee "$KIVOU_EVIDENCE_DIR/reviewed-release-target" >/dev/null
sudo cp -a /etc/systemd/system/kivou-api.service \
  "$KIVOU_EVIDENCE_DIR/kivou-api.service"
sudo chmod -R go-rwx "$KIVOU_EVIDENCE_DIR"

KIVOU_ROLLOUT_STATE=/etc/kivou/kivou-safe-rollout.state
KIVOU_ROLLOUT_STATE_NEW=/etc/kivou/kivou-safe-rollout.state.new
sudo test -d /etc/kivou
sudo -u kivou test ! -w /etc/kivou
sudo install -o root -g root -m 600 /dev/null "$KIVOU_ROLLOUT_STATE_NEW"
{
  printf 'KIVOU_STAGING_HOST=%q\n' "$KIVOU_STAGING_HOST"
  printf 'KIVOU_SECURITY_RELEASE=%q\n' "$KIVOU_SECURITY_RELEASE"
  printf 'KIVOU_PREVIOUS_RELEASE=%q\n' "$KIVOU_PREVIOUS_RELEASE"
  printf 'KIVOU_RELEASE_SHA=%q\n' "$KIVOU_RELEASE_SHA"
} | sudo tee "$KIVOU_ROLLOUT_STATE_NEW" >/dev/null
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_STATE_NEW")" = \
  "root:root:600"
sudo mv -f "$KIVOU_ROLLOUT_STATE_NEW" "$KIVOU_ROLLOUT_STATE"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_STATE")" = \
  "root:root:600"
~~~

Ces fichiers de preuve peuvent contenir l'ancien format de log ou l'ancienne
unité et ne sont jamais des sources de restauration. L'état fixe ne contient
aucun secret et sert uniquement aux blocs autonomes de reprise.

### Démarrer et prouver le runtime vert sur 8001

La transient unit reprend le fichier d'environnement protégé, le même
durcissement, deux workers et exactement --no-access-log. Elle exécute
l'exécutable et le répertoire de la release revue ; aucune variable secrète
n'est développée par le shell.

Le helper versionné `ops/bin/kivou-api-readiness.sh` ne contient aucun `sudo`.
Il s'exécute comme `kivou` avec un environnement fermé, vérifie que l'unité
reste active et attend `/openapi.json = 200` pendant cinq tentatives au maximum.
Chaque lecture systemd et chaque requête HTTP est bornée à une seconde ; quatre
pauses d'une seconde séparent les tentatives. Une unité inactive, un échec curl
ou une expiration retourne un code non nul ; il n'existe aucun retry infini.

~~~bash
sudo systemd-run \
  --unit=kivou-api-green \
  --collect \
  --property=Type=exec \
  --property=User=kivou \
  --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=Restart=on-failure \
  --property=RestartSec=5s \
  --property=StandardOutput=journal \
  --property=StandardError=journal \
  --property=SyslogIdentifier=kivou-api-green \
  --property=NoNewPrivileges=yes \
  --property=PrivateTmp=yes \
  --property=ProtectSystem=strict \
  --property=ProtectHome=yes \
  --property=ReadWritePaths=/srv/kivou/run \
  --property=ProtectKernelTunables=yes \
  --property=ProtectKernelModules=yes \
  --property=ProtectControlGroups=yes \
  --property=RestrictSUIDSGID=yes \
  --property=RestrictNamespaces=yes \
  --property=LockPersonality=yes \
  --property=MemoryDenyWriteExecute=yes \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/uvicorn" signals.api.asgi:app \
  --host 127.0.0.1 \
  --port 8001 \
  --workers 2 \
  --proxy-headers \
  --forwarded-allow-ips 127.0.0.1 \
  --no-server-header \
  --no-access-log \
  --timeout-keep-alive 20

/usr/bin/sudo -u kivou -- /usr/bin/env -i PATH=/usr/bin:/bin \
  "$KIVOU_RELEASE_DIR/ops/bin/kivou-api-readiness.sh" \
  kivou-api-green.service 8001
KIVOU_GREEN_OPENAPI_STATUS=$(curl --silent \
  --connect-timeout 1 --max-time 2 --output /dev/null \
  --write-out '%{http_code}' \
  http://127.0.0.1:8001/openapi.json) || exit 1
KIVOU_GREEN_ME_STATUS=$(curl --silent \
  --connect-timeout 1 --max-time 2 --output /dev/null \
  --write-out '%{http_code}' http://127.0.0.1:8001/me) || exit 1
test "$KIVOU_GREEN_OPENAPI_STATUS" = 200
test "$KIVOU_GREEN_ME_STATUS" = 401
printf 'green_openapi_status=%s\ngreen_me_status=%s\n' \
  "$KIVOU_GREEN_OPENAPI_STATUS" "$KIVOU_GREEN_ME_STATUS"
~~~

### Publier le bundle sûr puis effectuer le single public reload to green

Chaque fichier est créé avec install dans le même répertoire que sa destination,
puis renommé par mv. Le gate actif reste en mode 600 ; les fragments immuables,
limits et le site sont en mode 644. Nginx continue d'utiliser l'ancien bundle
jusqu'au test live réussi et au single public reload to green.

~~~bash
sudo install -o root -g root -m 644 \
  "$KIVOU_NGINX_CANDIDATE/kivou-proxy-params.conf" \
  /etc/nginx/kivou-proxy-params.conf.new
sudo mv -f /etc/nginx/kivou-proxy-params.conf.new /etc/nginx/kivou-proxy-params.conf
sudo install -o root -g root -m 644 \
  "$KIVOU_NGINX_CANDIDATE/kivou-security-headers.conf" \
  /etc/nginx/kivou-security-headers.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-link-security-headers.conf" \
  /etc/nginx/kivou-sensitive-link-security-headers.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-open.conf" \
  /etc/nginx/kivou-sensitive-links-open.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-closed.conf" \
  /etc/nginx/kivou-sensitive-links-closed.conf.new
sudo install -o root -g root -m 600 \
  "$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-open.conf" \
  /etc/nginx/kivou-sensitive-links-gate.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_NGINX_CANDIDATE/kivou-limits.conf" \
  /etc/nginx/conf.d/kivou-limits.conf.new
sed \
  -e "s/STAGING_HOST/$KIVOU_STAGING_HOST/g" \
  -e "s/KIVOU_API_PORT/$KIVOU_API_PORT/g" \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-staging.conf" |
  sudo tee /etc/nginx/sites-available/kivou.new >/dev/null
sudo chown root:root /etc/nginx/sites-available/kivou.new
sudo chmod 644 /etc/nginx/sites-available/kivou.new

sudo mv -f /etc/nginx/kivou-security-headers.conf.new /etc/nginx/kivou-security-headers.conf
sudo mv -f /etc/nginx/kivou-sensitive-link-security-headers.conf.new \
  /etc/nginx/kivou-sensitive-link-security-headers.conf
sudo mv -f /etc/nginx/kivou-sensitive-links-open.conf.new \
  /etc/nginx/kivou-sensitive-links-open.conf
sudo mv -f /etc/nginx/kivou-sensitive-links-closed.conf.new \
  /etc/nginx/kivou-sensitive-links-closed.conf
sudo mv -f /etc/nginx/kivou-sensitive-links-gate.conf.new /etc/nginx/kivou-sensitive-links-gate.conf
sudo mv -f /etc/nginx/conf.d/kivou-limits.conf.new /etc/nginx/conf.d/kivou-limits.conf
sudo mv -f /etc/nginx/sites-available/kivou.new /etc/nginx/sites-available/kivou

sudo nginx -t
# single public reload to green
sudo systemctl reload nginx
~~~

### Basculer l'application pendant le monitor public

Le monitor démarre après le routage vers green et reste actif pendant la
création du lien unique, son renommage atomique, l'installation de l'unité, le
daemon-reload, le restart de l'API normale et le retour final du proxy. Il ne
journalise que des codes HTTP.

~~~bash
KIVOU_PUBLIC_MONITOR_LOG=$(mktemp /tmp/kivou-public-status.XXXXXX)
KIVOU_PUBLIC_MONITOR_STOP=$(mktemp /tmp/kivou-public-stop.XXXXXX)
chmod 600 "$KIVOU_PUBLIC_MONITOR_LOG" "$KIVOU_PUBLIC_MONITOR_STOP"
kivou_public_sample() {
  KIVOU_PUBLIC_ROOT_STATUS=$(curl --silent --connect-timeout 3 --max-time 5 \
    --output /dev/null \
    --write-out '%{http_code}' "https://$KIVOU_STAGING_HOST/" || true)
  KIVOU_PUBLIC_ME_STATUS=$(curl --silent --connect-timeout 3 --max-time 5 \
    --output /dev/null \
    --write-out '%{http_code}' "https://$KIVOU_STAGING_HOST/me" || true)
  test -n "$KIVOU_PUBLIC_ROOT_STATUS" || KIVOU_PUBLIC_ROOT_STATUS=000
  test -n "$KIVOU_PUBLIC_ME_STATUS" || KIVOU_PUBLIC_ME_STATUS=000
  printf '%s %s\n' "$KIVOU_PUBLIC_ROOT_STATUS" "$KIVOU_PUBLIC_ME_STATUS"
}
KIVOU_PUBLIC_FIRST_SAMPLE=$(kivou_public_sample)
test "$KIVOU_PUBLIC_FIRST_SAMPLE" = "200 401"
printf '%s\n' "$KIVOU_PUBLIC_FIRST_SAMPLE" >"$KIVOU_PUBLIC_MONITOR_LOG"
(
  while test ! -s "$KIVOU_PUBLIC_MONITOR_STOP"; do
    kivou_public_sample
    sleep 1
  done
) >>"$KIVOU_PUBLIC_MONITOR_LOG" & KIVOU_PUBLIC_MONITOR_PID=$!
kivou_stop_public_monitor() {
  printf '%s\n' stop >"$KIVOU_PUBLIC_MONITOR_STOP"
  wait "$KIVOU_PUBLIC_MONITOR_PID" || true
}
trap kivou_stop_public_monitor EXIT

KIVOU_APP_NEXT_DIR=$(sudo mktemp -d /srv/kivou/.kivou-app-next.XXXXXX)
KIVOU_APP_NEXT="$KIVOU_APP_NEXT_DIR/app.next"
sudo ln -s "$KIVOU_RELEASE_DIR" "$KIVOU_APP_NEXT"
test "$(sudo readlink -f "$KIVOU_APP_NEXT")" = "$KIVOU_RELEASE_DIR"
sudo test -L /srv/kivou/app
sudo mv -Tf "$KIVOU_APP_NEXT" /srv/kivou/app

sudo install -o root -g root -m 644 \
  "$KIVOU_RELEASE_DIR/ops/systemd/kivou-api.service" \
  /etc/systemd/system/kivou-api.service.new
sudo mv -f /etc/systemd/system/kivou-api.service.new \
  /etc/systemd/system/kivou-api.service
sudo systemctl daemon-reload
sudo systemctl restart kivou-api.service
/usr/bin/sudo -u kivou -- /usr/bin/env -i PATH=/usr/bin:/bin \
  "$KIVOU_RELEASE_DIR/ops/bin/kivou-api-readiness.sh" \
  kivou-api.service 8000

KIVOU_NORMAL_OPENAPI_STATUS=$(curl --silent \
  --connect-timeout 1 --max-time 2 --output /dev/null \
  --write-out '%{http_code}' \
  http://127.0.0.1:8000/openapi.json) || exit 1
KIVOU_NORMAL_ME_STATUS=$(curl --silent \
  --connect-timeout 1 --max-time 2 --output /dev/null \
  --write-out '%{http_code}' http://127.0.0.1:8000/me) || exit 1
test "$KIVOU_NORMAL_OPENAPI_STATUS" = 200
test "$KIVOU_NORMAL_ME_STATUS" = 401

KIVOU_API_PORT=8000
case "$KIVOU_API_PORT" in
  (8000|8001) ;;
  (*) printf '%s\n' 'port API hors liste revue' >&2; exit 64 ;;
esac
sed \
  -e "s/STAGING_HOST/$KIVOU_STAGING_HOST/g" \
  -e "s/KIVOU_API_PORT/$KIVOU_API_PORT/g" \
  -e "s#/etc/nginx/kivou-proxy-params.conf#$KIVOU_NGINX_CANDIDATE/kivou-proxy-params.conf#g" \
  -e "s#/etc/nginx/kivou-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-security-headers.conf#g" \
  -e "s#/etc/nginx/kivou-sensitive-link-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-sensitive-link-security-headers.conf#g" \
  -e "s#/etc/nginx/kivou-sensitive-links-gate.conf#$KIVOU_NGINX_CANDIDATE/kivou-sensitive-links-gate.conf#g" \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-staging.conf" |
  sudo tee "$KIVOU_NGINX_CANDIDATE/kivou-staging.test.conf" >/dev/null
sudo nginx -t -c "$KIVOU_NGINX_CANDIDATE/nginx.conf"

sed \
  -e "s/STAGING_HOST/$KIVOU_STAGING_HOST/g" \
  -e "s/KIVOU_API_PORT/$KIVOU_API_PORT/g" \
  "$KIVOU_RELEASE_DIR/ops/nginx/kivou-staging.conf" |
  sudo tee /etc/nginx/sites-available/kivou.new >/dev/null
sudo chown root:root /etc/nginx/sites-available/kivou.new
sudo chmod 644 /etc/nginx/sites-available/kivou.new
sudo mv -f /etc/nginx/sites-available/kivou.new /etc/nginx/sites-available/kivou
sudo nginx -t
sudo systemctl reload nginx

KIVOU_FINAL_PUBLIC_SAMPLE=$(kivou_public_sample)
test "$KIVOU_FINAL_PUBLIC_SAMPLE" = "200 401"
kill -0 "$KIVOU_PUBLIC_MONITOR_PID"
printf '%s\n' stop >"$KIVOU_PUBLIC_MONITOR_STOP"
wait "$KIVOU_PUBLIC_MONITOR_PID"
trap - EXIT
test -s "$KIVOU_PUBLIC_MONITOR_LOG"
# all public monitor status pairs must be 200 401
awk 'NF != 2 || $1 != "200" || $2 != "401" {bad=1} END {exit bad}' \
  "$KIVOU_PUBLIC_MONITOR_LOG"
sudo install -o root -g root -m 600 "$KIVOU_PUBLIC_MONITOR_LOG" \
  "$KIVOU_EVIDENCE_DIR/public-status.codes"
/usr/bin/sudo --non-interactive -- \
  /usr/bin/timeout --foreground 2 /usr/bin/systemctl \
  show kivou-api-green.service --no-pager \
  --property=ActiveState --property=SubState |
  sudo tee "$KIVOU_EVIDENCE_DIR/green-final-state" >/dev/null
sudo systemctl stop kivou-api-green.service
printf 'normal_openapi_status=%s\nnormal_me_status=%s\npublic_root_status=200\npublic_me_status=401\n' \
  "$KIVOU_NORMAL_OPENAPI_STATUS" "$KIVOU_NORMAL_ME_STATUS"
~~~

### Prouver les chemins sensibles sans exposer les marqueurs

La preuve enregistre des offsets et un curseur journald juste avant les requêtes.
Elle exerce HTTP et HTTPS pour attribution et reset, puis un vrai asset avec
l'URL reset synthétique comme Referer. Referrer-Policy: no-referrer doit
apparaître exactement une fois sur chacune des quatre réponses sensibles. Aucun
contenu de requête, réponse ou log n'est imprimé. Only numeric or coded output is emitted.

~~~bash
KIVOU_ACCESS_OFFSET=$(sudo stat -c %s /var/log/nginx/access.log)
KIVOU_ERROR_OFFSET=$(sudo stat -c %s /var/log/nginx/error.log)
KIVOU_JOURNAL_CURSOR=$(sudo journalctl -u kivou-api.service -n 0 \
  --show-cursor --no-pager | sed -n 's/^-- cursor: //p')
test -n "$KIVOU_JOURNAL_CURSOR"

KIVOU_SYNTHETIC_ATTRIBUTION_MARKER=$(printf 'synthetic-attr-%s-%s' \
  "$(date -u +%Y%m%dT%H%M%S)" "$$")
KIVOU_SYNTHETIC_RESET_MARKER=$(printf 'synthetic-reset-%s-%s' \
  "$(date -u +%Y%m%dT%H%M%S)" "$$")

kivou_probe_sensitive() {
  KIVOU_PROBE_RESPONSE=$(curl --silent --max-time 15 \
    --dump-header - --output /dev/null \
    --write-out 'kivou_status=%{http_code}\n' "$1")
  KIVOU_PROBE_STATUS=$(printf '%s\n' "$KIVOU_PROBE_RESPONSE" |
    sed -n 's/^kivou_status=//p')
  KIVOU_PROBE_POLICY_COUNT=$(printf '%s\n' "$KIVOU_PROBE_RESPONSE" |
    awk 'tolower($0) ~ /^referrer-policy:[[:space:]]*no-referrer\r?$/ {n++}
         END {print n+0}')
}

kivou_probe_sensitive \
  "http://$KIVOU_STAGING_HOST/a/$KIVOU_SYNTHETIC_ATTRIBUTION_MARKER"
KIVOU_HTTP_ATTR_STATUS=$KIVOU_PROBE_STATUS
KIVOU_HTTP_ATTR_POLICY_COUNT=$KIVOU_PROBE_POLICY_COUNT

kivou_probe_sensitive \
  "https://$KIVOU_STAGING_HOST/a/$KIVOU_SYNTHETIC_ATTRIBUTION_MARKER"
KIVOU_HTTPS_ATTR_STATUS=$KIVOU_PROBE_STATUS
KIVOU_HTTPS_ATTR_POLICY_COUNT=$KIVOU_PROBE_POLICY_COUNT

kivou_probe_sensitive \
  "http://$KIVOU_STAGING_HOST/reset-password?token=$KIVOU_SYNTHETIC_RESET_MARKER"
KIVOU_HTTP_RESET_STATUS=$KIVOU_PROBE_STATUS
KIVOU_HTTP_RESET_POLICY_COUNT=$KIVOU_PROBE_POLICY_COUNT

kivou_probe_sensitive \
  "https://$KIVOU_STAGING_HOST/reset-password?token=$KIVOU_SYNTHETIC_RESET_MARKER"
KIVOU_HTTPS_RESET_STATUS=$KIVOU_PROBE_STATUS
KIVOU_HTTPS_RESET_POLICY_COUNT=$KIVOU_PROBE_POLICY_COUNT

KIVOU_ASSET_PATH=$(curl --silent "https://$KIVOU_STAGING_HOST/" |
  sed -n 's#.*src="\(/assets/[^"]*\)".*#\1#p' | head -n 1)
case "$KIVOU_ASSET_PATH" in
  (/assets/*) ;;
  (*) exit 69 ;;
esac
KIVOU_ASSET_STATUS=$(curl --silent --output /dev/null \
  --write-out '%{http_code}' \
  --referer "https://$KIVOU_STAGING_HOST/reset-password?token=$KIVOU_SYNTHETIC_RESET_MARKER" \
  "https://$KIVOU_STAGING_HOST$KIVOU_ASSET_PATH")
test "$KIVOU_ASSET_STATUS" = 200

kivou_new_access() {
  sudo test "$(sudo stat -c %s /var/log/nginx/access.log)" -ge \
    "$KIVOU_ACCESS_OFFSET"
  sudo tail -c "+$((KIVOU_ACCESS_OFFSET + 1))" /var/log/nginx/access.log
}
kivou_new_error() {
  sudo test "$(sudo stat -c %s /var/log/nginx/error.log)" -ge \
    "$KIVOU_ERROR_OFFSET"
  sudo tail -c "+$((KIVOU_ERROR_OFFSET + 1))" /var/log/nginx/error.log
}
kivou_new_journal() {
  sudo journalctl -u kivou-api.service \
    --after-cursor "$KIVOU_JOURNAL_CURSOR" --no-pager --output=cat
}

KIVOU_MARKER_OCCURRENCES=$(
  { kivou_new_access; kivou_new_error; kivou_new_journal; } |
    awk -v a="$KIVOU_SYNTHETIC_ATTRIBUTION_MARKER" \
        -v r="$KIVOU_SYNTHETIC_RESET_MARKER" '
      {
        line=$0
        while ((at=index(line, a)) > 0) {
          total++
          line=substr(line, at+length(a))
        }
        line=$0
        while ((rt=index(line, r)) > 0) {
          total++
          line=substr(line, rt+length(r))
        }
      }
      END {print total+0}
    '
)
KIVOU_SANITIZED_ATTRIBUTION_COUNT=$(kivou_new_access |
  awk 'index($0, "/a/[redacted]") {n++} END {print n+0}')
KIVOU_SANITIZED_RESET_COUNT=$(kivou_new_access |
  awk 'index($0, "/reset-password") {n++} END {print n+0}')

test "$KIVOU_HTTP_ATTR_STATUS" = 301
test "$KIVOU_HTTPS_ATTR_STATUS" = 404
test "$KIVOU_HTTP_RESET_STATUS" = 301
test "$KIVOU_HTTPS_RESET_STATUS" = 200
test "$KIVOU_HTTP_ATTR_POLICY_COUNT" = 1
test "$KIVOU_HTTPS_ATTR_POLICY_COUNT" = 1
test "$KIVOU_HTTP_RESET_POLICY_COUNT" = 1
test "$KIVOU_HTTPS_RESET_POLICY_COUNT" = 1
test "$KIVOU_MARKER_OCCURRENCES" = 0
test "$KIVOU_SANITIZED_ATTRIBUTION_COUNT" -ge 2
test "$KIVOU_SANITIZED_RESET_COUNT" -ge 2

printf '%s\n' \
  "http_attribution_status=$KIVOU_HTTP_ATTR_STATUS" \
  "https_attribution_status=$KIVOU_HTTPS_ATTR_STATUS" \
  "http_reset_status=$KIVOU_HTTP_RESET_STATUS" \
  "https_reset_status=$KIVOU_HTTPS_RESET_STATUS" \
  "asset_status=$KIVOU_ASSET_STATUS" \
  'marker_occurrences=0' \
  "sanitized_attribution_count=$KIVOU_SANITIZED_ATTRIBUTION_COUNT" \
  "sanitized_reset_count=$KIVOU_SANITIZED_RESET_COUNT" \
  'http_attribution_referrer_policy_count=1' \
  'https_attribution_referrer_policy_count=1' \
  'http_reset_referrer_policy_count=1' \
  'https_reset_referrer_policy_count=1' \
  'synthetic_proof=PASS'
~~~

Only after synthetic_proof=PASS may a separately authorized valid attribution proof run.
For that separate proof, the real token stays entirely in process memory: it is
never assigned to KIVOU_VALID_ATTRIBUTION_TOKEN, written to a file, passed in
argv, or printed. The #93 proof reuses an already delivered link; no new reset e-mail is needed.

### Fermer atomiquement les liens sensibles

Si un invariant sensible est incertain, installer le candidat fermé comme gate
actif avant toute autre action. kivou-sensitive-links-closed.conf doit contenir
exactement return 503; et le fragment actif doit rester en mode 600.

~~~bash
set -euo pipefail
sudo install -o root -g root -m 600 \
  /etc/nginx/kivou-sensitive-links-closed.conf \
  /etc/nginx/kivou-sensitive-links-gate.conf.new
test "$(sudo awk 'NF && $1 !~ /^#/ {print}' \
  /etc/nginx/kivou-sensitive-links-gate.conf.new)" = "return 503;"
sudo mv -f /etc/nginx/kivou-sensitive-links-gate.conf.new \
  /etc/nginx/kivou-sensitive-links-gate.conf
sudo nginx -t
sudo systemctl reload nginx
~~~

### Réouvrir atomiquement les liens sensibles

Depuis un nouveau shell, recharger l'état root-only puis réouvrir uniquement
après rétablissement et preuve. Le candidat open vient de la release de
sécurité revue, doit lui être identique et rester sans directive active.

~~~bash
set -euo pipefail
KIVOU_ROLLOUT_STATE=/etc/kivou/kivou-safe-rollout.state
sudo test -d /etc/kivou
sudo -u kivou test ! -w /etc/kivou
sudo test -f "$KIVOU_ROLLOUT_STATE"
sudo test ! -L "$KIVOU_ROLLOUT_STATE"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_STATE")" = \
  "root:root:600"
unset KIVOU_STAGING_HOST KIVOU_SECURITY_RELEASE \
  KIVOU_PREVIOUS_RELEASE KIVOU_RELEASE_SHA
KIVOU_STATE_CONTENT=$(sudo cat "$KIVOU_ROLLOUT_STATE")
. /dev/stdin <<<"$KIVOU_STATE_CONTENT"
unset KIVOU_STATE_CONTENT
case "$KIVOU_STAGING_HOST" in
  (*[!a-z0-9.-]*|'') exit 69 ;;
  (*) ;;
esac
case "$KIVOU_SECURITY_RELEASE" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
case "$KIVOU_PREVIOUS_RELEASE" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
printf '%s\n' "$KIVOU_RELEASE_SHA" | grep -Eq '^[0-9a-f]{40}$'
sudo test -d "$KIVOU_SECURITY_RELEASE"
sudo test -d "$KIVOU_PREVIOUS_RELEASE"
kivou_git() {
  sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
    /usr/bin/git "$@"
}
test "$(kivou_git -C "$KIVOU_SECURITY_RELEASE" rev-parse HEAD)" = \
  "$KIVOU_RELEASE_SHA"
test -z "$(kivou_git -C "$KIVOU_SECURITY_RELEASE" status --porcelain)"

KIVOU_REVIEWED_OPEN_SHA=$(kivou_git -C "$KIVOU_SECURITY_RELEASE" show \
  "$KIVOU_RELEASE_SHA:ops/nginx/kivou-sensitive-links-open.conf" |
  sha256sum | awk '{print $1}')
sudo install -o root -g root -m 600 \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-sensitive-links-open.conf" \
  /etc/nginx/kivou-sensitive-links-gate.conf.new
KIVOU_OPEN_GATE_SHA=$(sudo sha256sum \
  /etc/nginx/kivou-sensitive-links-gate.conf.new | awk '{print $1}')
test "$KIVOU_OPEN_GATE_SHA" = "$KIVOU_REVIEWED_OPEN_SHA"
test -z "$(sudo awk 'NF && $1 !~ /^#/ {print}' \
  /etc/nginx/kivou-sensitive-links-gate.conf.new)"
sudo mv -f /etc/nginx/kivou-sensitive-links-gate.conf.new \
  /etc/nginx/kivou-sensitive-links-gate.conf
sudo nginx -t
sudo systemctl reload nginx
~~~

### Rollback applicatif préservant la sécurité

Le safe nginx bundle, le gate et l'unité versionnée avec --no-access-log sont le
security floor. Les captures antérieures sont EVIDENCE ONLY. Never restore the old nginx access format or the old API unit.
Le rollback commute uniquement vers la previous application release enregistrée.
Si le routage sûr ne peut pas être conservé, exécuter d'abord la fermeture
atomique avec kivou-sensitive-links-closed.conf et garder le reste de staging
disponible.

Relancer green avec la release de sécurité enregistrée, valider 8001, puis
rendre et republier depuis cette release l'intégralité du bundle sûr vers 8001
avant de toucher au lien applicatif. Toutes les sources sont validées et tous
les fichiers .new sont prêts avant le premier mv ; le vieux processus nginx
continue de servir jusqu'au nginx-t réussi puis au reload unique de reprise.
La commande est idempotente et reprend exactement le durcissement déjà audité.

~~~bash
set -euo pipefail
KIVOU_ROLLOUT_STATE=/etc/kivou/kivou-safe-rollout.state
sudo test -d /etc/kivou
sudo -u kivou test ! -w /etc/kivou
sudo test -f "$KIVOU_ROLLOUT_STATE"
sudo test ! -L "$KIVOU_ROLLOUT_STATE"
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_ROLLOUT_STATE")" = \
  "root:root:600"
unset KIVOU_STAGING_HOST KIVOU_SECURITY_RELEASE \
  KIVOU_PREVIOUS_RELEASE KIVOU_RELEASE_SHA
KIVOU_STATE_CONTENT=$(sudo cat "$KIVOU_ROLLOUT_STATE")
. /dev/stdin <<<"$KIVOU_STATE_CONTENT"
unset KIVOU_STATE_CONTENT
case "$KIVOU_STAGING_HOST" in
  (*[!a-z0-9.-]*|'') exit 69 ;;
  (*) ;;
esac
case "$KIVOU_SECURITY_RELEASE" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
case "$KIVOU_PREVIOUS_RELEASE" in
  (/srv/kivou/releases/backend-*) ;;
  (*) exit 69 ;;
esac
printf '%s\n' "$KIVOU_RELEASE_SHA" | grep -Eq '^[0-9a-f]{40}$'
sudo test -d "$KIVOU_SECURITY_RELEASE"
sudo test -d "$KIVOU_PREVIOUS_RELEASE"
kivou_git() {
  sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
    /usr/bin/git "$@"
}
test "$(kivou_git -C "$KIVOU_SECURITY_RELEASE" rev-parse HEAD)" = \
  "$KIVOU_RELEASE_SHA"
test -z "$(kivou_git -C "$KIVOU_SECURITY_RELEASE" status --porcelain)"
KIVOU_SAFE_NGINX_SOURCE_PATHS=(
  "ops/nginx/kivou-limits.conf"
  "ops/nginx/kivou-proxy-params.conf"
  "ops/nginx/kivou-security-headers.conf"
  "ops/nginx/kivou-sensitive-link-security-headers.conf"
  "ops/nginx/kivou-sensitive-links-open.conf"
  "ops/nginx/kivou-sensitive-links-closed.conf"
  "ops/nginx/kivou-staging.conf"
)
for KIVOU_SAFE_NGINX_SOURCE_PATH in \
  "${KIVOU_SAFE_NGINX_SOURCE_PATHS[@]}"; do
  KIVOU_GIT_SOURCE_SHA=$(kivou_git -C "$KIVOU_SECURITY_RELEASE" show \
    "$KIVOU_RELEASE_SHA:$KIVOU_SAFE_NGINX_SOURCE_PATH" |
    sha256sum | awk '{print $1}')
  KIVOU_WORKTREE_SOURCE_SHA=$(sudo -u kivou sha256sum \
    "$KIVOU_SECURITY_RELEASE/$KIVOU_SAFE_NGINX_SOURCE_PATH" |
    awk '{print $1}')
  test "$KIVOU_WORKTREE_SOURCE_SHA" = "$KIVOU_GIT_SOURCE_SHA"
done
test -z "$(sudo -u kivou awk 'NF && $1 !~ /^#/ {print}' \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-sensitive-links-open.conf")"
test "$(sudo -u kivou awk 'NF && $1 !~ /^#/ {print}' \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-sensitive-links-closed.conf")" = \
  "return 503;"

kivou_bounded_systemctl_read() {
  /usr/bin/sudo --non-interactive -- \
    /usr/bin/timeout --foreground 2 /usr/bin/systemctl "$@"
}
kivou_validate_recovery_green_unit() {
  KIVOU_GREEN_UNIT_TO_VALIDATE=$1
  test "$(kivou_bounded_systemctl_read show "$KIVOU_GREEN_UNIT_TO_VALIDATE" \
    --property=WorkingDirectory --value)" = "$KIVOU_SECURITY_RELEASE"
  kivou_bounded_systemctl_read show "$KIVOU_GREEN_UNIT_TO_VALIDATE" \
    --property=ExecStart --value |
    grep --fixed-strings --quiet -- \
      "$KIVOU_SECURITY_RELEASE/.venv/bin/uvicorn"
  kivou_bounded_systemctl_read show "$KIVOU_GREEN_UNIT_TO_VALIDATE" \
    --property=ExecStart --value |
    grep --fixed-strings --quiet -- '--no-access-log'
}
if kivou_bounded_systemctl_read is-active --quiet \
  kivou-api-green.service; then
  KIVOU_ROLLBACK_GREEN_UNIT=kivou-api-green.service
  kivou_validate_recovery_green_unit "$KIVOU_ROLLBACK_GREEN_UNIT"
elif kivou_bounded_systemctl_read is-active --quiet \
  kivou-api-rollback-green.service; then
  KIVOU_ROLLBACK_GREEN_UNIT=kivou-api-rollback-green.service
  kivou_validate_recovery_green_unit "$KIVOU_ROLLBACK_GREEN_UNIT"
else
  KIVOU_ROLLBACK_GREEN_UNIT=kivou-api-rollback-green.service
  sudo systemctl stop kivou-api-green.service || true
  sudo systemctl stop "$KIVOU_ROLLBACK_GREEN_UNIT" || true
  sudo systemctl reset-failed kivou-api-green.service || true
  sudo systemctl reset-failed "$KIVOU_ROLLBACK_GREEN_UNIT" || true
  ! kivou_bounded_systemctl_read is-active --quiet \
    kivou-api-green.service
  ! kivou_bounded_systemctl_read is-active --quiet \
    "$KIVOU_ROLLBACK_GREEN_UNIT"
  test -z "$(sudo ss --no-header --listening --tcp 'sport = :8001')"
  sudo systemd-run \
    --unit="$KIVOU_ROLLBACK_GREEN_UNIT" \
    --collect \
    --property=Type=exec \
    --property=User=kivou \
    --property=Group=kivou \
    --property=WorkingDirectory="$KIVOU_SECURITY_RELEASE" \
    --property=EnvironmentFile=/etc/kivou/staging.env \
    --property=Restart=on-failure \
    --property=RestartSec=5s \
    --property=StandardOutput=journal \
    --property=StandardError=journal \
    --property=SyslogIdentifier=kivou-api-rollback-green \
    --property=NoNewPrivileges=yes \
    --property=PrivateTmp=yes \
    --property=ProtectSystem=strict \
    --property=ProtectHome=yes \
    --property=ReadWritePaths=/srv/kivou/run \
    --property=ProtectKernelTunables=yes \
    --property=ProtectKernelModules=yes \
    --property=ProtectControlGroups=yes \
    --property=RestrictSUIDSGID=yes \
    --property=RestrictNamespaces=yes \
    --property=LockPersonality=yes \
    --property=MemoryDenyWriteExecute=yes \
    -- "$KIVOU_SECURITY_RELEASE/.venv/bin/uvicorn" signals.api.asgi:app \
    --host 127.0.0.1 --port 8001 --workers 2 --proxy-headers \
    --forwarded-allow-ips 127.0.0.1 --no-server-header --no-access-log \
    --timeout-keep-alive 20
fi
/usr/bin/sudo -u kivou -- /usr/bin/env -i PATH=/usr/bin:/bin \
  "$KIVOU_SECURITY_RELEASE/ops/bin/kivou-api-readiness.sh" \
  "$KIVOU_ROLLBACK_GREEN_UNIT" 8001
KIVOU_ROLLBACK_GREEN_OPENAPI_STATUS=$(curl --silent \
  --connect-timeout 1 --max-time 2 \
  --output /dev/null --write-out '%{http_code}' \
  http://127.0.0.1:8001/openapi.json) || exit 1
KIVOU_ROLLBACK_GREEN_ME_STATUS=$(curl --silent \
  --connect-timeout 1 --max-time 2 \
  --output /dev/null --write-out '%{http_code}' \
  http://127.0.0.1:8001/me) || exit 1
test "$KIVOU_ROLLBACK_GREEN_OPENAPI_STATUS" = 200
test "$KIVOU_ROLLBACK_GREEN_ME_STATUS" = 401

sudo install -o root -g root -m 644 \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-proxy-params.conf" \
  /etc/nginx/kivou-proxy-params.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-security-headers.conf" \
  /etc/nginx/kivou-security-headers.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-sensitive-link-security-headers.conf" \
  /etc/nginx/kivou-sensitive-link-security-headers.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-sensitive-links-open.conf" \
  /etc/nginx/kivou-sensitive-links-open.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-sensitive-links-closed.conf" \
  /etc/nginx/kivou-sensitive-links-closed.conf.new
sudo install -o root -g root -m 600 \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-sensitive-links-closed.conf" \
  /etc/nginx/kivou-sensitive-links-gate.conf.new
sudo install -o root -g root -m 644 \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-limits.conf" \
  /etc/nginx/conf.d/kivou-limits.conf.new
KIVOU_API_PORT=8001
sed \
  -e "s/STAGING_HOST/$KIVOU_STAGING_HOST/g" \
  -e "s/KIVOU_API_PORT/$KIVOU_API_PORT/g" \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-staging.conf" | \
  sudo tee /etc/nginx/sites-available/kivou.new >/dev/null
sudo chown root:root /etc/nginx/sites-available/kivou.new
sudo chmod 644 /etc/nginx/sites-available/kivou.new
test "$(sudo awk 'NF && $1 !~ /^#/ {print}' \
  /etc/nginx/kivou-sensitive-links-gate.conf.new)" = "return 503;"
sudo mv -f /etc/nginx/kivou-proxy-params.conf.new \
  /etc/nginx/kivou-proxy-params.conf
sudo mv -f /etc/nginx/kivou-security-headers.conf.new \
  /etc/nginx/kivou-security-headers.conf
sudo mv -f /etc/nginx/kivou-sensitive-link-security-headers.conf.new \
  /etc/nginx/kivou-sensitive-link-security-headers.conf
sudo mv -f /etc/nginx/kivou-sensitive-links-open.conf.new \
  /etc/nginx/kivou-sensitive-links-open.conf
sudo mv -f /etc/nginx/kivou-sensitive-links-closed.conf.new \
  /etc/nginx/kivou-sensitive-links-closed.conf
sudo mv -f /etc/nginx/kivou-sensitive-links-gate.conf.new \
  /etc/nginx/kivou-sensitive-links-gate.conf
sudo mv -f /etc/nginx/conf.d/kivou-limits.conf.new \
  /etc/nginx/conf.d/kivou-limits.conf
sudo mv -f /etc/nginx/sites-available/kivou.new \
  /etc/nginx/sites-available/kivou
sudo nginx -t
sudo systemctl reload nginx

# Switch only to the recorded previous application release.
KIVOU_ROLLBACK_NEXT_DIR=$(sudo mktemp -d \
  /srv/kivou/.kivou-rollback-next.XXXXXX)
KIVOU_ROLLBACK_NEXT="$KIVOU_ROLLBACK_NEXT_DIR/app.next"
sudo ln -s "$KIVOU_PREVIOUS_RELEASE" "$KIVOU_ROLLBACK_NEXT"
test "$(sudo readlink -f "$KIVOU_ROLLBACK_NEXT")" = \
  "$KIVOU_PREVIOUS_RELEASE"
sudo mv -Tf "$KIVOU_ROLLBACK_NEXT" /srv/kivou/app

sudo install -o root -g root -m 644 \
  "$KIVOU_SECURITY_RELEASE/ops/systemd/kivou-api.service" \
  /etc/systemd/system/kivou-api.service.new
sudo mv -f /etc/systemd/system/kivou-api.service.new \
  /etc/systemd/system/kivou-api.service
sudo systemctl daemon-reload
sudo systemctl restart kivou-api.service
/usr/bin/sudo -u kivou -- /usr/bin/env -i PATH=/usr/bin:/bin \
  "$KIVOU_SECURITY_RELEASE/ops/bin/kivou-api-readiness.sh" \
  kivou-api.service 8000
KIVOU_ROLLBACK_NORMAL_OPENAPI_STATUS=$(curl --silent \
  --connect-timeout 1 --max-time 2 \
  --output /dev/null --write-out '%{http_code}' \
  http://127.0.0.1:8000/openapi.json) || exit 1
KIVOU_ROLLBACK_NORMAL_ME_STATUS=$(curl --silent \
  --connect-timeout 1 --max-time 2 \
  --output /dev/null --write-out '%{http_code}' \
  http://127.0.0.1:8000/me) || exit 1
test "$KIVOU_ROLLBACK_NORMAL_OPENAPI_STATUS" = 200
test "$KIVOU_ROLLBACK_NORMAL_ME_STATUS" = 401

KIVOU_API_PORT=8000
sed \
  -e "s/STAGING_HOST/$KIVOU_STAGING_HOST/g" \
  -e "s/KIVOU_API_PORT/$KIVOU_API_PORT/g" \
  "$KIVOU_SECURITY_RELEASE/ops/nginx/kivou-staging.conf" |
  sudo tee /etc/nginx/sites-available/kivou.new >/dev/null
sudo chown root:root /etc/nginx/sites-available/kivou.new
sudo chmod 644 /etc/nginx/sites-available/kivou.new
sudo mv -f /etc/nginx/sites-available/kivou.new \
  /etc/nginx/sites-available/kivou
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl stop "$KIVOU_ROLLBACK_GREEN_UNIT"
~~~

Aucun fichier du snapshot ne revient en position active. Le security floor reste
le bundle nginx expurgé, le gate validé et l'unité API sans journal d'accès,
même lorsque l'application précédente est restaurée.
