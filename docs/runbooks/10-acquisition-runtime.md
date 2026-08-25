# Runtime Acquisition QA/SHADOW sur staging

Ce runbook installe un seul orchestrateur borné. Le timer normal peut lire les
fournisseurs nécessaires au cycle, mais il ne reçoit jamais l’autorisation
processus `--allow-qa-provider-mutations`. Il ne peut donc ni activer une
campagne ni envoyer un message à un prospect. Une preuve fournisseur contrôlée
reste une opération manuelle, approuvée et limitée à l’identité QA liée par
HMAC.

Les commandes mutantes lisent exclusivement `KIVOU_DATABASE_URL` depuis
l’`EnvironmentFile` protégé et utilisent l’horloge UTC du serveur. Elles
refusent les options opérateur `--database-url` et `--now`.

## Préconditions

- le SHA déployé provient de `main` et la migration
  `0026_acquisition_runtime` est appliquée après sauvegarde ;
- l’environnement indique exactement `KIVOU_ACQUISITION_ENVIRONMENT=STAGING` ;
- Apollo, Instantly, Hermes, Policy, attribution et la boîte QA sont configurés
  dans leurs fichiers protégés existants ;
- la clé de signal autorisée désigne un vrai signal staging approuvé pour la
  QA, jamais une adresse ni une URL ;
- la rotation des secrets staging est terminée et aucun secret ne figure dans
  un argument de processus ou dans journald.

## Fichiers protégés

Installer les exemples, puis saisir les valeurs réelles avec un éditeur root.
Ne jamais passer la boîte ou la clé HMAC sur la ligne de commande.

```bash
sudo install -o root -g kivou -m 600 \
  ops/examples/acquisition-runtime.env.example \
  /etc/kivou/acquisition-runtime.env
sudo install -o root -g kivou -m 640 \
  ops/examples/acquisition-runtime.json.example \
  /etc/kivou/acquisition-runtime.json
sudoedit /etc/kivou/acquisition-runtime.env
sudoedit /etc/kivou/acquisition-runtime.json
```

`qa_recipient_identity_hmac` est le HMAC-SHA256 de la boîte QA normalisée avec
`KIVOU_ACQUISITION_QA_RECIPIENT_KEY`. La clé et la boîte restent uniquement
dans le fichier d’environnement `600`; seul le digest est copié dans le JSON.
Le runtime refuse une liaison différente.

Le plafond de coût `10.00` est une enveloppe conservatrice, pas une hausse de
volume : il couvre le chemin Apollo normal (`1 + 3 + 1`) et au plus une reprise
native de chacun de ces appels après interruption. Une réponse réseau perdue
laisse l'acceptation fournisseur ambiguë ; la garantie est donc *at-least-once*
dans cette fenêtre, avec un seul replay durable et jamais de troisième appel.
Si ce replay reste ambigu, le cycle demeure `WAITING` sur le même attempt et la
même réservation, sans nouvel appel fournisseur. Le health expose
`APOLLO_PROVIDER_OUTCOME_AMBIGUOUS` jusqu'à intervention opérateur.

## Installation du runtime

```bash
sudo install -o root -g root -m 644 \
  ops/systemd/kivou-acquisition.service \
  ops/systemd/kivou-acquisition.timer \
  /etc/systemd/system/
sudo systemd-analyze verify \
  /etc/systemd/system/kivou-acquisition.service \
  /etc/systemd/system/kivou-acquisition.timer
sudo systemctl daemon-reload
sudo systemctl start kivou-acquisition.service
sudo systemctl status kivou-acquisition.service --no-pager
sudo systemctl enable --now kivou-acquisition.timer
```

La contention `flock` ou du lease PostgreSQL retourne proprement
`already_running`. Une panne technique du cycle courant retourne un code non
nul. Le lease expiré est repris depuis le premier stage durable non terminal.

## Approbation humaine et preuve fournisseur QA

Arrêter temporairement le timer, ouvrir une fenêtre Policy QA de trente minutes
au maximum, puis exécuter d’abord sans mutation. Inspecter chaque demande
durable et son contexte métier avant de l’approuver. Les commandes ne rendent
que des identifiants opaques, des états et des codes machine.

La séquence ci-dessous est un bloc opératoire `try/finally` : dès que la fenêtre
est ouverte, la commande `close-runtime-qa-policy-window` et le redémarrage du
timer sont obligatoires, même si une commande intermédiaire échoue. L’expiration
de la fenêtre restaure en plus l’ancien contrôle comme sécurité passive. Remplacer
uniquement les références opaques, jamais par une adresse ou un secret.

```bash
sudo systemctl stop kivou-acquisition.timer
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-shadow.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-runtime.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations \
  open-runtime-qa-policy-window \
  --duration-seconds 1800 \
  --actor-ref OPAQUE_ACTOR --reason-code QA_E2E_PROOF
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=RuntimeDirectory=kivou \
  --property=RuntimeDirectoryMode=0700 \
  --property=RuntimeMaxSec=20min \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-shadow.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-runtime.env \
  /usr/bin/flock --verbose --nonblock --conflict-exit-code 0 \
  /run/kivou/acquisition.lock \
  /srv/kivou/app/.venv/bin/python -m signals.acquisition_runtime run-once
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations list-runtime-approvals
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations \
  approve-runtime-approval --approval-id OPAQUE_ID --actor-ref OPAQUE_ACTOR
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=RuntimeDirectory=kivou \
  --property=RuntimeDirectoryMode=0700 \
  --property=RuntimeMaxSec=20min \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-shadow.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-runtime.env \
  /usr/bin/flock --verbose --nonblock --conflict-exit-code 0 \
  /run/kivou/acquisition.lock \
  /srv/kivou/app/.venv/bin/python -m signals.acquisition_runtime run-once \
  --allow-qa-provider-mutations
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-shadow.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-runtime.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations \
  close-runtime-qa-policy-window \
  --actor-ref OPAQUE_ACTOR --reason-code QA_E2E_PROOF_COMPLETE
sudo systemctl start kivou-acquisition.timer
```

Répéter uniquement le triplet `list-runtime-approvals`, approbation exacte,
`run-once` si le cycle s’arrête sur une nouvelle approbation. Le runtime contient
au plus trois points de revue humaine ; ne jamais approuver en masse ni réutiliser
une approbation consommée. Une dérive des opérations ou de la liaison QA crée une
nouvelle demande et interdit la mutation.

L’autorisation processus ne remplace ni Policy, ni l’approbation one-shot, ni
la liaison QA. Le worker limite l’opération Instantly au brouillon contrôlé
`CREATE_CAMPAIGN`, `CONFIGURE_CAMPAIGN`, `ADD_LEAD`; aucune activation ou
émission ne fait partie de ce runtime.

## Santé, readiness et arrêt d’urgence

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations health
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations readiness
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations \
  activate-kill-switch --reason-code OPERATOR_QA_STOP
```

Un health `READY` exige une observation durable récente, le pin Hermes exact,
le registre fermé, zéro outil natif, Policy et toutes les dépendances du cycle.
La readiness autonome reste honnêtement bornée : un cycle QA/SHADOW sain ne
constitue pas une autorisation de production.

Les événements opératoires restent bornés à des codes machine et références
opaques. Cette lecture ne doit révéler ni adresse, ni contenu, ni payload :

```bash
sudo journalctl -u kivou-acquisition.service \
  --since "today" --output=short-iso --no-pager
```

## Rollback

```bash
sudo systemctl disable --now kivou-acquisition.timer
sudo systemctl stop kivou-acquisition.service
sudo rm /etc/systemd/system/kivou-acquisition.service \
  /etc/systemd/system/kivou-acquisition.timer
sudo systemctl daemon-reload
```

Restaurer ensuite l’artefact applicatif précédent. Le downgrade de
`0026_acquisition_runtime` n’est exécuté que si la procédure de release le
décide explicitement et avant tout nouveau cycle à conserver. Il ne justifie
jamais de supprimer les tables métier des moteurs existants. Les opérations
Instantly déjà acceptées sont réconciliées avant toute nouvelle tentative.

Après sauvegarde, timer arrêté et confirmation qu’aucun cycle runtime ne doit
être conservé, le downgrade exact d’une révision est :

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  /srv/kivou/app/.venv/bin/alembic downgrade 0025_alert_recipient_context
```
