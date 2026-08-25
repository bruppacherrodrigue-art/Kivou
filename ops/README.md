# Runtime d'exploitation Kivou

Ce dossier ne contient que ce qui doit être **versionné pour être reproductible**.
Aujourd'hui : la sauvegarde PostgreSQL (RTL-03 / #39), le runtime des alertes
transactionnelles (RTL-05), l'ingestion DECP bornée (#77) et l'outillage de
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
