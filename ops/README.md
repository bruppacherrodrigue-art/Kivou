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

Les quatre fichiers sous `ops/nginx/` forment un seul candidat versionné :

- `kivou-staging.conf` porte la liste blanche publique et le repli SPA ;
- `kivou-limits.conf` déclare les zones de débit au niveau `http` ;
- `kivou-proxy-params.conf` conserve l'hôte, l'origine et les adresses relayées ;
- `kivou-security-headers.conf` centralise CSP, HSTS et les autres en-têtes.

La liste blanche relaie les groupes SaaS actuels, dont `/companies`, les deux
webhooks exacts et le préfixe `^~ /a/`. Elle ne relaie aucun `/internal/*` et ne
contient aucun catch-all backend : une nouvelle route FastAPI exige une revue de
`tests/test_ops_nginx_routes.py` et du gabarit avant de devenir publique.

Les six variables `KIVOU_INSTANTLY_WEBHOOK_SECRET`,
`KIVOU_INSTANTLY_WORKSPACE_REF`, `KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY`,
`KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION`,
`KIVOU_SUPPRESSION_IDENTITY_KEY` et `KIVOU_SUPPRESSION_IDENTITY_KEY_VERSION`
décrites dans `.env.example` sont un groupe atomique. Toutes absentes, le
webhook répond 503 ; partiellement présentes, l'API refuse de démarrer sans
imprimer leurs valeurs. Avant de remplacer une version de clé déjà utilisée,
vérifier les versions référencées dans les événements et suppressions durables.
Le câblage actuel ne retient qu'une version : une rotation exige d'abord un
keyring de déploiement capable de conserver les anciennes clés.

### Préparer et valider le candidat

Définir l'hôte explicitement et refuser tout caractère qui pourrait modifier le
gabarit. Le répertoire candidat est créé sous `/etc/nginx`, sur le même système
de fichiers que les destinations finales : les renommages de publication y sont
atomiques.

```bash
set -euo pipefail
KIVOU_STAGING_HOST=staging.kivou.eu
case "$KIVOU_STAGING_HOST" in
  (*[!a-z0-9.-]*|'') printf '%s\n' 'hôte staging invalide' >&2; exit 64 ;;
esac

KIVOU_NGINX_CANDIDATE=$(sudo mktemp -d /etc/nginx/.kivou-candidate.XXXXXX)
sudo chmod 700 "$KIVOU_NGINX_CANDIDATE"
sudo install -o root -g root -m 644 \
  ops/nginx/kivou-limits.conf \
  ops/nginx/kivou-proxy-params.conf \
  ops/nginx/kivou-security-headers.conf \
  "$KIVOU_NGINX_CANDIDATE/"

sed \
  -e "s/STAGING_HOST/$KIVOU_STAGING_HOST/g" \
  -e "s#/etc/nginx/kivou-proxy-params.conf#$KIVOU_NGINX_CANDIDATE/kivou-proxy-params.conf#g" \
  -e "s#/etc/nginx/kivou-security-headers.conf#$KIVOU_NGINX_CANDIDATE/kivou-security-headers.conf#g" \
  ops/nginx/kivou-staging.conf |
  sudo tee "$KIVOU_NGINX_CANDIDATE/kivou-staging.test.conf" >/dev/null

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

sudo nginx -t -c "$KIVOU_NGINX_CANDIDATE/nginx.conf"
```

Ce premier `nginx -t` lit les quatre fichiers candidats ensemble. Il utilise les
certificats déjà déclarés pour l'hôte ; une absence de certificat est donc un
échec réel de précondition, pas une raison de publier sans validation.

### Sauvegarder, publier puis recharger

La sauvegarde précède toute publication. Les fichiers `.new` sont écrits puis
renommés dans leur répertoire final ; nginx continue d'exécuter son ancienne
configuration jusqu'au `reload` final. Le second `nginx -t` valide exactement
les chemins qui seront relus par le processus actif.

```bash
set -euo pipefail
KIVOU_NGINX_BACKUP=$(sudo mktemp -d /etc/nginx/.kivou-backup.XXXXXX)
sudo chmod 700 "$KIVOU_NGINX_BACKUP"
if sudo test -e /etc/nginx/kivou-proxy-params.conf; then
  sudo cp -a /etc/nginx/kivou-proxy-params.conf "$KIVOU_NGINX_BACKUP/proxy"
else
  sudo touch "$KIVOU_NGINX_BACKUP/proxy.absent"
fi
if sudo test -e /etc/nginx/kivou-security-headers.conf; then
  sudo cp -a /etc/nginx/kivou-security-headers.conf "$KIVOU_NGINX_BACKUP/security"
else
  sudo touch "$KIVOU_NGINX_BACKUP/security.absent"
fi
if sudo test -e /etc/nginx/conf.d/kivou-limits.conf; then
  sudo cp -a /etc/nginx/conf.d/kivou-limits.conf "$KIVOU_NGINX_BACKUP/limits"
else
  sudo touch "$KIVOU_NGINX_BACKUP/limits.absent"
fi
if sudo test -e /etc/nginx/sites-available/kivou; then
  sudo cp -a /etc/nginx/sites-available/kivou "$KIVOU_NGINX_BACKUP/site"
else
  sudo touch "$KIVOU_NGINX_BACKUP/site.absent"
fi

sudo install -o root -g root -m 644 \
  ops/nginx/kivou-proxy-params.conf /etc/nginx/kivou-proxy-params.conf.new
sudo install -o root -g root -m 644 \
  ops/nginx/kivou-security-headers.conf /etc/nginx/kivou-security-headers.conf.new
sudo install -o root -g root -m 644 \
  ops/nginx/kivou-limits.conf /etc/nginx/conf.d/kivou-limits.conf.new
sed "s/STAGING_HOST/$KIVOU_STAGING_HOST/g" ops/nginx/kivou-staging.conf |
  sudo tee /etc/nginx/sites-available/kivou.new >/dev/null
sudo chown root:root /etc/nginx/sites-available/kivou.new
sudo chmod 644 /etc/nginx/sites-available/kivou.new

sudo mv -f /etc/nginx/kivou-proxy-params.conf.new \
  /etc/nginx/kivou-proxy-params.conf
sudo mv -f /etc/nginx/kivou-security-headers.conf.new \
  /etc/nginx/kivou-security-headers.conf
sudo mv -f /etc/nginx/conf.d/kivou-limits.conf.new \
  /etc/nginx/conf.d/kivou-limits.conf
sudo mv -f /etc/nginx/sites-available/kivou.new \
  /etc/nginx/sites-available/kivou

sudo nginx -t
sudo systemctl reload nginx
```

Si le second test échoue, ne pas recharger : appliquer immédiatement le rollback
ci-dessous. Si le reload échoue, restaurer également le snapshot puis tester de
nouveau ; le processus nginx antérieur doit rester l'autorité. Ne pas remplacer
le lien `sites-enabled/kivou` s'il pointe déjà vers `sites-available/kivou`; le
renommage conserve cette cible stable.

### Preuve HTTP non mutante

Une fois l'API redémarrée avec le groupe Instantly complet, un secret
délibérément faux doit être refusé par FastAPI en JSON. Il ne peut ni lier une
campagne ni écrire un événement. Un token d'attribution invalide doit produire
le 404 JSON de l'application, sans cookie et sans HTML SPA.

```bash
curl --silent --show-error --include \
  --request POST "https://$KIVOU_STAGING_HOST/webhooks/instantly" \
  --header 'content-type: application/json' \
  --header 'x-kivou-instantly-secret: deliberately-wrong-synthetic-value' \
  --data '{}'
# Attendu : 401, application/json, code invalid_instantly_webhook_secret.

curl --silent --show-error --include \
  "https://$KIVOU_STAGING_HOST/a/bogus-token"
# Attendu : 404, application/json, code attribution_not_found,
# aucun Set-Cookie et aucun <!doctype html>.
```

La preuve 200/replay du webhook et la preuve 303/cookie d'attribution utilisent
une base jetable dans les tests. Ne pas fabriquer ces preuves sur staging : un
webhook métier valide écrit durablement et demande une autorisation distincte.

### Rollback

Le rollback restaure uniquement les fichiers qui existaient dans la sauvegarde.
Si un fichier avait été créé par cette installation, le déplacer dans le
répertoire de sauvegarde plutôt que le supprimer conserve une récupération
possible. Tester avant de recharger.

```bash
set -euo pipefail
if sudo test -e "$KIVOU_NGINX_BACKUP/proxy.absent"; then
  sudo test ! -e /etc/nginx/kivou-proxy-params.conf ||
    sudo mv /etc/nginx/kivou-proxy-params.conf "$KIVOU_NGINX_BACKUP/installed-proxy"
else
  sudo cp -a "$KIVOU_NGINX_BACKUP/proxy" \
    /etc/nginx/kivou-proxy-params.conf.rollback
  sudo mv -f /etc/nginx/kivou-proxy-params.conf.rollback \
    /etc/nginx/kivou-proxy-params.conf
fi
if sudo test -e "$KIVOU_NGINX_BACKUP/security.absent"; then
  sudo test ! -e /etc/nginx/kivou-security-headers.conf ||
    sudo mv /etc/nginx/kivou-security-headers.conf \
      "$KIVOU_NGINX_BACKUP/installed-security"
else
  sudo cp -a "$KIVOU_NGINX_BACKUP/security" \
    /etc/nginx/kivou-security-headers.conf.rollback
  sudo mv -f /etc/nginx/kivou-security-headers.conf.rollback \
    /etc/nginx/kivou-security-headers.conf
fi
if sudo test -e "$KIVOU_NGINX_BACKUP/limits.absent"; then
  sudo test ! -e /etc/nginx/conf.d/kivou-limits.conf ||
    sudo mv /etc/nginx/conf.d/kivou-limits.conf \
      "$KIVOU_NGINX_BACKUP/installed-limits"
else
  sudo cp -a "$KIVOU_NGINX_BACKUP/limits" \
    /etc/nginx/conf.d/kivou-limits.conf.rollback
  sudo mv -f /etc/nginx/conf.d/kivou-limits.conf.rollback \
    /etc/nginx/conf.d/kivou-limits.conf
fi
if sudo test -e "$KIVOU_NGINX_BACKUP/site.absent"; then
  sudo test ! -e /etc/nginx/sites-available/kivou ||
    sudo mv /etc/nginx/sites-available/kivou "$KIVOU_NGINX_BACKUP/installed-site"
else
  sudo cp -a "$KIVOU_NGINX_BACKUP/site" \
    /etc/nginx/sites-available/kivou.rollback
  sudo mv -f /etc/nginx/sites-available/kivou.rollback \
    /etc/nginx/sites-available/kivou
fi

sudo nginx -t
sudo systemctl reload nginx
```

Il n'existe aucune migration à annuler pour #84. Le rollback retire l'exposition
des routes ; il ne supprime jamais les événements métier déjà reçus. Conserver
les répertoires candidat et sauvegarde jusqu'à validation, puis les archiver ou
les retirer selon la politique d'exploitation de l'hôte.
