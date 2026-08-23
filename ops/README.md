# Runtime d'exploitation Kivou

Ce dossier ne contient que ce qui doit être **versionné pour être reproductible**.
Aujourd'hui : la sauvegarde PostgreSQL (RTL-03 / #39).

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
