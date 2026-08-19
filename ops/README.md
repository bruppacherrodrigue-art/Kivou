# Exploitation de Kivou — staging

Ce dossier contient tout ce qui est nécessaire pour faire tourner Kivou sur un
serveur, et **rien qui soit secret**. Les gabarits portent des marqueurs à
remplacer ; les valeurs réelles vivent dans `/etc/kivou/staging.env`, hors de
Git.

> **Statut au 19 août 2026 :** déployé sur `kivou-staging-01`, au SHA `5102348`. L'application tourne, la base est
> migrée, les sondes sont vertes et la restauration de sauvegarde est vérifiée.
>
> **TLS bloqué :** les ports 80 et 443 sont filtrés en amont de la machine par
> le pare-feu Infomaniak Public Cloud. Seul 22 est ouvert. Tant que le groupe de
> sécurité OpenStack n'autorise pas 80/443 en entrée, Let's Encrypt ne peut pas
> valider et le site reste inaccessible publiquement.

---

## La règle qui prime sur toutes les autres

```text
On ne déploie JAMAIS « ce qu'il y a dans le dossier de travail ».
On déploie un SHA de commit GitHub validé par la CI.
```

Chaque déploiement inscrit dans le journal d'exploitation :

```text
dépôt        github.com/bruppacherrodrigue-art/Kivou
branche      <branche>
SHA          <sha complet>
horodatage   <UTC>
révision Alembic  <avant> → <après>
```

Sans ces cinq lignes, personne ne peut répondre à « qu'est-ce qui tourne ? » —
et donc personne ne peut revenir en arrière avec certitude.

---

## Ce que le serveur doit contenir

```text
/srv/kivou/app/          checkout Git, propriété de kivou
/srv/kivou/app/.venv/    environnement Python (uv sync --locked)
/srv/kivou/frontend/     contenu de frontend/dist/
/srv/kivou/backups/      sauvegardes PostgreSQL, chmod 700
/srv/kivou/run/          verrous flock
/etc/kivou/staging.env   secrets, propriété root:kivou, chmod 640
```

L'utilisateur `kivou` n'a pas de shell de connexion et n'est pas sudoer. Il fait
tourner l'application, rien d'autre.

---

## Première installation

```bash
# 1. Utilisateur et arborescence
sudo useradd --system --home /srv/kivou --shell /usr/sbin/nologin kivou
sudo mkdir -p /srv/kivou/{app,frontend,backups,run} /etc/kivou
sudo chown -R kivou:kivou /srv/kivou
sudo chmod 700 /srv/kivou/backups

# 2. PostgreSQL — rôle dédié, jamais le superutilisateur
sudo -u postgres createuser --pwprompt kivou_app
sudo -u postgres createdb --owner=kivou_app kivou_staging
# Vérifier que PostgreSQL n'écoute PAS sur l'extérieur :
#   listen_addresses = 'localhost'   dans postgresql.conf

# 3. Configuration — voir « Secrets » plus bas
sudo install -o root -g kivou -m 640 /dev/null /etc/kivou/staging.env
sudo -e /etc/kivou/staging.env

# 4. Code, à un SHA précis
sudo -u kivou git clone https://github.com/bruppacherrodrigue-art/Kivou.git /srv/kivou/app
cd /srv/kivou/app && sudo -u kivou git checkout <SHA>

# 5. Dépendances et build
#    `--extra server` est OBLIGATOIRE : uvicorn est une dépendance optionnelle,
#    et `uv sync --locked` seul ne l'installe pas. Sans lui, le service échoue
#    en 203/EXEC — l'exécutable n'existe pas.
sudo -u kivou uv sync --locked --extra server
cd frontend && sudo -u kivou npm ci && sudo -u kivou npm run build
sudo rsync -a --delete frontend/dist/ /srv/kivou/frontend/

# 6. Migration — UNE fois, avant de démarrer l'application
sudo -u kivou env $(grep -v '^#' /etc/kivou/staging.env | xargs) \
    /srv/kivou/app/.venv/bin/python -c \
    "from signals.persistence.database import create_database_engine, migrate_to_latest, current_revision; \
     e=create_database_engine(); print('avant', current_revision(e)); migrate_to_latest(e); print('après', current_revision(e))"

# 7. Services
sudo cp ops/systemd/*.service ops/systemd/*.timer /etc/systemd/system/
sudo cp ops/nginx/kivou-proxy-params.conf /etc/nginx/
sudo cp ops/nginx/kivou-security-headers.conf /etc/nginx/
sudo cp ops/nginx/kivou-limits.conf /etc/nginx/conf.d/
sudo sed "s/STAGING_HOST/<hôte>/g" ops/nginx/kivou-staging.conf \
    | sudo tee /etc/nginx/sites-available/kivou > /dev/null
sudo ln -sf /etc/nginx/sites-available/kivou /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo systemctl daemon-reload
# `kivou-alerts.timer` reste DÉSACTIVÉE tant que SMTP n'est pas configuré :
# sans SMTP le job sort en code 2 à chaque déclenchement, et une unité
# perpétuellement en échec masquerait les vraies pannes dans la surveillance.
sudo systemctl enable --now kivou-api kivou-backup.timer

# 8. TLS — `certonly`, PAS `--nginx`
#    `--nginx` réécrit le fichier de site et le ferait diverger du gabarit
#    versionné. `certonly` ne touche qu'à /etc/letsencrypt ; le gabarit déclare
#    lui-même les chemins de certificat.
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d <hôte> \
    --non-interactive --agree-tos --email <email>
sudo nginx -t && sudo systemctl reload nginx

# 9. Vérification
KIVOU_HEALTHCHECK_URL=https://<hôte> ops/bin/kivou-healthcheck.sh
```

---

## Déploiement d'une nouvelle version

L'ordre compte : **migrer une seule fois, avant de redémarrer**. Laisser
plusieurs workers migrer en parallèle les ferait se disputer
`alembic_version`.

```bash
cd /srv/kivou/app
sudo -u kivou git fetch origin
sudo -u kivou git checkout <NOUVEAU_SHA>

# Confirmer ce qui va réellement tourner
git rev-parse HEAD          # doit égaler le SHA validé par la CI

sudo -u kivou uv sync --locked --extra server
cd frontend && sudo -u kivou npm ci && sudo -u kivou npm run build
sudo rsync -a --delete frontend/dist/ /srv/kivou/frontend/

# Migration : UNE fois
sudo -u kivou env $(grep -v '^#' /etc/kivou/staging.env | xargs) \
    /srv/kivou/app/.venv/bin/python -c \
    "from signals.persistence.database import create_database_engine, migrate_to_latest; \
     migrate_to_latest(create_database_engine())"

sudo systemctl restart kivou-api
KIVOU_HEALTHCHECK_URL=https://<hôte> ops/bin/kivou-healthcheck.sh
```

---

## Retour arrière

```bash
cd /srv/kivou/app
sudo -u kivou git checkout <SHA_PRÉCÉDENT_VALIDÉ>
sudo -u kivou uv sync --locked --extra server
cd frontend && sudo -u kivou npm ci && sudo -u kivou npm run build
sudo rsync -a --delete frontend/dist/ /srv/kivou/frontend/
sudo systemctl restart kivou-api
```

**On ne rétrograde PAS la base.** Un `alembic downgrade` réflexe détruit des
colonnes et les données qu'elles portent.

Si l'ancien code ne sait pas lire le schéma migré, le retour arrière applicatif
seul ne suffit pas : **dites-le, arrêtez-vous, et demandez une décision
humaine**. Restaurer une sauvegarde fait perdre tout ce qui a été écrit depuis —
c'est une décision de perte de données, jamais une étape de routine.

En pratique, les migrations additives (colonnes nullables, nouvelles tables) se
tolèrent d'une version à l'autre ; les migrations destructives ne se rattrapent
pas.

---

## Accès au dépôt depuis le serveur

Le dépôt est privé : le serveur ne peut pas cloner anonymement. Il utilise une
**clé de déploiement en LECTURE SEULE**, générée sur le serveur — la moitié
privée n'en sort jamais et ne peut pas pousser.

```bash
sudo -u kivou ssh-keygen -t ed25519 -N "" -f /srv/kivou/.ssh/github_deploy
# puis, depuis un poste autorisé :
gh repo deploy-key add <clé.pub> --title "<hôte> (read-only)" --repo bruppacherrodrigue-art/Kivou
```

Vérifier qu'elle ne peut PAS pousser :

```bash
sudo -u kivou git -C /srv/kivou/app push --dry-run origin HEAD:refs/heads/probe
# doit être refusé
```

## Secrets

`/etc/kivou/staging.env` — `root:kivou`, `chmod 640`. Jamais dans Git, jamais
dans un rapport, jamais dans une sortie de terminal recopiée.

Variables attendues : voir `.env.example` à la racine du dépôt. Pour le staging :

```text
KIVOU_STRIPE_MODE=test          ← JAMAIS live en staging
KIVOU_ALLOWED_ORIGIN=https://<hôte>
STRIPE_SUCCESS_URL=https://<hôte>/checkout/success
STRIPE_CANCEL_URL=https://<hôte>/checkout/cancel
STRIPE_PORTAL_RETURN_URL=https://<hôte>/app/billing
KIVOU_PUBLIC_APP_URL=https://<hôte>/app     ← le /app est obligatoire
```

Le suffixe `/app` de `KIVOU_PUBLIC_APP_URL` n'est pas décoratif : le job
d'alerte construit `{base}/signals/{clé}` et la route navigateur est
`/app/signals/{clé}`. Sans lui, chaque lien d'alerte tombe à côté.

---

## Ingestion — trois groupes, un seul verrou

Les sources publiques n'ont ni le même rythme de publication ni le même
volume ; leur donner une cadence unique reviendrait soit à marteler DECP et
TED, soit à laisser vieillir SIMAP et BOAMP.

```bash
sudo cp ops/systemd/kivou-ingest-*.service ops/systemd/kivou-ingest-*.timer /etc/systemd/system/
sudo cp ops/systemd/kivou-ingestion.tmpfiles.conf /etc/tmpfiles.d/kivou-ingestion.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/kivou-ingestion.conf
sudo systemctl daemon-reload
sudo systemctl enable --now kivou-ingest-simap.timer kivou-ingest-boamp.timer \
    kivou-ingest-decp.timer kivou-ingest-ted.timer
```

| Unité | Source | Cadence | Borne |
|---|---|---|---|
| `kivou-ingest-simap` | SIMAP | toutes les 2 h, minute 05 | 30 min |
| `kivou-ingest-boamp` | BOAMP | toutes les 2 h, minute 15 | 30 min |
| `kivou-ingest-decp` | DECP | 00 h et 12 h, minute 35 | 30 min |
| `kivou-ingest-ted` | TED | 02:30 UTC | 45 min |

**Une unité par source, et c'est délibéré.** SIMAP et BOAMP ont d'abord partagé
une unité `kivou-ingest-fast`. En conditions réelles, BOAMP échouait sur une
catégorie d'avis non gérée et marquait l'unité entière en échec — alors que
SIMAP venait de réussir. La surveillance voyait « ingestion rapide en panne »
sans pouvoir dire laquelle des deux sources allait mal, et une source saine
était noyée dans le bruit d'une source malade. Chaque source porte désormais
son état, son checkpoint et son alerte.

**Le verrou est le point à comprendre.** Les trois groupes partagent
`/run/kivou-ingestion.lock` pour que deux écritures de faits ne se croisent
jamais. En cas de collision, `flock --timeout 300 --conflict-exit-code 0`
attend cinq minutes puis **renonce proprement** : l'unité sort en 0, le journal
garde la trace du passage sauté, et le déclenchement suivant reprend au
checkpoint durable. Sortir en erreur ferait d'un chevauchement bénin une unité
« failed » permanente — et une surveillance qui crie en continu n'alerte plus
de rien.

Le fichier de verrou est déclaré en `tmpfiles.d` parce que `/run` est un tmpfs :
créé à la main, il disparaîtrait au premier redémarrage. Les services tournant
en `ProtectSystem=strict` ne peuvent pas le créer eux-mêmes, et leur ouvrir tout
`/run` en écriture pour un seul fichier serait disproportionné.

Amorçage initial, à ne jouer qu'une fois, avec la base de production :

```bash
cd /srv/kivou/app
sudo -u kivou env $(sudo cat /etc/kivou/staging.env | xargs) \
    .venv/bin/python -m signals.ingestion run --source simap --since 2026-07-20
# puis boamp, decp (mêmes fenêtres), et ted sur une fenêtre plus courte
```

Pas de `--max-records` pour un amorçage : la borne empêcherait le checkpoint
d'avancer jusqu'au bout de la fenêtre, et le rattrapage suivant repartirait
d'un état incomplet sans le dire.

L'ingestion ne déclenche **jamais** l'envoi d'alertes. Les deux jobs restent
séparés, pour qu'une ingestion lente ne retarde pas les alertes et qu'un
incident d'envoi ne bloque pas l'acquisition des faits.

## Sauvegardes

`kivou-backup.timer` déclenche un `pg_dump` quotidien vers
`/srv/kivou/backups`, rétention 14 jours, avec contrôle de taille minimale — un
dump vide est un échec, pas un succès.

**Ce n'est pas un plan de reprise d'activité.** Une sauvegarde posée sur le même
hôte que la base disparaît avec l'hôte. La production exige une copie **hors
hôte** (Swiss Backup, S3, autre machine). C'est une porte de production
explicite.

Vérifier qu'une sauvegarde est restaurable — la seule preuve qui compte :

```bash
KIVOU_RESTORE_ADMIN_URL='postgresql://…@127.0.0.1:5432/postgres' \
    ops/bin/kivou-restore-verify.sh /srv/kivou/backups/kivou-<horodatage>.dump
```

Le script restaure dans une base **jetable**, compte les lignes des tables qui
comptent, puis détruit la base. Il ne touche jamais la base active.

---

## Diagnostic

```bash
journalctl -u kivou-api -n 200 --no-pager
journalctl -u kivou-alerts -n 100 --no-pager
journalctl -u kivou-backup -n 50 --no-pager
systemctl list-timers 'kivou-*'
sudo nginx -t
curl -s https://<hôte>/health/ready
```

`/health/ready` distingue les pannes qui se réparent différemment :

| `reason` | Ce qui s'est passé |
|---|---|
| `database_unreachable` | PostgreSQL est arrêté, ou les identifiants sont faux |
| `migrations_not_applied` | Base vide — la migration n'a pas été jouée |
| `schema_revision_mismatch` | L'application a redémarré sans migrer |
| `schema_unreadable` | Droits insuffisants sur `alembic_version` |


---

## Pare-feu — deux couches, et la seconde n'est pas sur la machine

`ufw` sur l'hôte autorise 22, 80 et 443. Mais l'instance vit dans Infomaniak
Public Cloud (OpenStack) : un **groupe de sécurité** filtre en amont, et il ne
se configure ni par `ufw` ni par l'API REST Infomaniak.

Symptôme caractéristique : depuis la machine, `curl http://127.0.0.1/` répond ;
depuis l'extérieur, le port expire sans refus. `ufw status` est actif et
`iptables -S INPUT` vaut `ACCEPT` — la machine n'y est pour rien.

Ouverture requise dans la console Public Cloud (Horizon), sur le groupe de
sécurité de l'instance `ov-f58505` :

```text
Ingress  TCP  80    0.0.0.0/0, ::/0
Ingress  TCP  443   0.0.0.0/0, ::/0
```

Vérification depuis un poste extérieur :

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://staging.kivou.eu/
```

Tant que cela expire, aucune porte TLS ne peut être franchie — et on ne
fabrique pas de certificat auto-signé pour faire semblant.
