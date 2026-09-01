# Runtime Acquisition PRODUCTION/SHADOW — phase 1

Ce runbook installe le second orchestrateur borné, distinct de celui du
staging décrit au runbook 10. Le cycle de production tourne en
`PRODUCTION` avec zéro outil natif Hermes — `RuntimeExecutionMode` reste
`SHADOW` au sens mécanique de ce champ, Hermes n'agissant jamais autrement
que par les commandes fermées du registre Kivou. Cela ne veut plus dire que
le cycle est inerte : l'autorité Policy posée à l'étape 6 est **ASSISTED**,
pas SHADOW, et le cycle est réellement exécutable. Il reste **sans aucun
chemin d'envoi**, mais par construction, jamais par le mode seul : cinq
gardes indépendants le retiennent (détaillés à l'étape 6), dont
`--allow-qa-provider-mutations`, un argument invalide dès que
`KIVOU_ACQUISITION_ENVIRONMENT=PRODUCTION` et que l'unité de production ne le
passe jamais. Chaque cycle sélectionne
automatiquement une opportunité France encore jamais retenue par un cycle
terminal et dont le cycle précédent, s'il existe, a dépassé le
refroidissement de 20 heures (`selection.py`), la fait progresser aussi loin
que la Policy l'y autorise, et n'émet aucune mutation commerciale. Il ne
remplace ni le runbook 07 (promotion staging → production), ni le
runbook 10 (staging), qui restent inchangés.

Les commandes mutantes lisent exclusivement `KIVOU_DATABASE_URL` depuis
l'`EnvironmentFile` protégé et utilisent l'horloge UTC du serveur. Elles
refusent tout remplacement en ligne de commande de la base ou de l'horloge.

## 1. Préconditions

- le SHA installé sous `/srv/kivou/app` provient d'une fusion **approuvée**
  dans `main`, dont la CI GitHub est verte ; l'arborescence déployée est
  propre (`git status --porcelain` vide dans la release) ;
- `kivou-api.service` est sain et `/etc/kivou/production.env` existe déjà en
  `root:root 600` (runbook `ops/production/README.md`) — ce fichier porte
  `KIVOU_DATABASE_URL`, `KIVOU_PUBLIC_APP_URL`, `KIVOU_ATTRIBUTION_HMAC_KEY`,
  `KIVOU_ATTRIBUTION_HMAC_KEY_VERSION` et le paquet complet des clés webhook
  Instantly/suppression/réponse ; ce runbook ne les répète jamais ;
- aucun contrôle Policy de production n'existe encore : `bootstrap-policy-control`
  (étape 6) refuse d'écrire un second contrôle initial, par construction ;
- la migration `0026_acquisition_runtime` et toutes celles qui suivent
  jusqu'à `0028_card_presentation` sont déjà appliquées à la base de
  production ; `0029_production_observation_boundary` (étape 2) ne l'est
  **pas encore** ;
- staging et production restent deux bases, deux jeux de secrets, deux
  comptes/espaces de travail fournisseur distincts (runbook 07) ;
- le wedge choisi pour le premier cycle est déjà décidé par l'opérateur — il
  doit être identique dans `acquisition-production.json`
  (`qa_scope.wedge`, étape 5) et dans la commande `bootstrap-policy-control`
  (étape 6) ; un désaccord fait échouer chaque cycle avec `POLICY_SCOPE_NOT_EXACT`.

## 2. Sauvegarde puis migration `0029_production_observation_boundary`

`0029_production_observation_boundary` assouplit — sans jamais la relâcher —
la contrainte de vérification `ck_acquisition_runtime_observation_boundary`
de la table `acquisition_runtime_observation` : elle continue d'exiger
`mode = 'SHADOW'` et `native_tools = 0` sans exception, exige toujours
`qa_only IS TRUE` en `STAGING`, et **ajoute** la seule forme nouvellement
acceptée : `environment = 'PRODUCTION' AND qa_only IS FALSE`. Sans cette
migration, PostgreSQL rejette la toute première observation de production
avant même qu'un stage ne s'exécute. Appliquer cette migration seul, avant
toute autre étape de ce runbook, sur une base fraîchement sauvegardée :

```bash
set -euo pipefail
sudo systemd-run --wait --collect --pipe --unit=kivou-backup-pre-0029 \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  --property=UMask=0077 \
  /srv/kivou/app/ops/bin/kivou-backup.sh
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/app/.venv/bin/python -c '
from alembic import command
from signals.persistence.database import alembic_config, create_database_engine, current_revision
engine = create_database_engine(pool_pre_ping=True)
try:
    print(f"before={current_revision(engine)}")
    config = alembic_config(engine)
    command.upgrade(config, "0029_production_observation_boundary")
    print(f"after={current_revision(engine)}")
finally:
    engine.dispose()
'
```

`set -euo pipefail` est ce qui rend ce bloc réellement bloquant : sans lui,
un shell interactif continue après une commande en échec. Si la sauvegarde
échoue, la migration ne s'exécute pas — coller ce bloc en une fois, jamais
ligne par ligne.

Vérifier que la ligne `after=` affiche exactement
`0029_production_observation_boundary` avant de continuer. N'exécuter aucune
étape suivante si la sauvegarde ou la migration a échoué.

## 3. Vérification des identifiants Apollo et Instantly de production

**Obligatoire, jamais théorique.** Les clés Apollo et Instantly de
production doivent différer de celles du staging — par empreinte de clé,
référence de workspace Instantly et références de boîte — avant que le
runtime de production ne soit démarré une seule fois. Le runbook 07 l'exige
déjà en général ; la confusion des comptes Stripe entre Kivou et Turiya
montre que ce contrôle a déjà été manqué une fois dans ce projet et n'est
pas une précaution superflue.

Cette vérification ne peut s'exécuter qu'une fois les fichiers protégés de
production écrits — **exécuter le bloc ci-dessous immédiatement après avoir
terminé l'étape 5 (provisionnement), avant l'étape 6.** Aucune valeur secrète
n'est jamais affichée : seules des empreintes SHA-256 et des références
opaques (non sensibles) sont comparées.

```bash
set -euo pipefail
sudo test -f /etc/kivou/acquisition-shadow.env
sudo test -f /etc/kivou/acquisition-shadow.json
sudo test -f /etc/kivou/acquisition-production.env
sudo test -f /etc/kivou/acquisition-production-connectivity.json

kivou_staging_apollo_fp=$(sudo grep -F 'KIVOU_APOLLO_API_KEY=' /etc/kivou/acquisition-shadow.env | cut -d= -f2- | sha256sum | cut -d' ' -f1)
kivou_production_apollo_fp=$(sudo grep -F 'KIVOU_APOLLO_API_KEY=' /etc/kivou/acquisition-production.env | cut -d= -f2- | sha256sum | cut -d' ' -f1)
test -n "$kivou_staging_apollo_fp"
test -n "$kivou_production_apollo_fp"
test "$kivou_staging_apollo_fp" != "$kivou_production_apollo_fp"

kivou_staging_instantly_fp=$(sudo grep -F 'KIVOU_INSTANTLY_API_KEY=' /etc/kivou/acquisition-shadow.env | cut -d= -f2- | sha256sum | cut -d' ' -f1)
kivou_production_instantly_fp=$(sudo grep -F 'KIVOU_INSTANTLY_API_KEY=' /etc/kivou/acquisition-production.env | cut -d= -f2- | sha256sum | cut -d' ' -f1)
test -n "$kivou_staging_instantly_fp"
test -n "$kivou_production_instantly_fp"
test "$kivou_staging_instantly_fp" != "$kivou_production_instantly_fp"

kivou_staging_workspace=$(sudo jq -r '.instantly_workspace_ref' /etc/kivou/acquisition-shadow.json)
kivou_production_workspace=$(sudo jq -r '.instantly_workspace_ref' /etc/kivou/acquisition-production-connectivity.json)
test "$kivou_staging_workspace" != "$kivou_production_workspace"

kivou_shared_mailbox_refs=$(comm -12 \
  <(sudo jq -r '.mailboxes[].mailbox_ref' /etc/kivou/acquisition-shadow.json | sort) \
  <(sudo jq -r '.mailboxes[].mailbox_ref' /etc/kivou/acquisition-production-connectivity.json | sort))
test -z "$kivou_shared_mailbox_refs"

kivou_shared_provider_accounts=$(comm -12 \
  <(sudo jq -r '.mailboxes[].provider_account_id' /etc/kivou/acquisition-shadow.json | sort) \
  <(sudo jq -r '.mailboxes[].provider_account_id' /etc/kivou/acquisition-production-connectivity.json | sort))
test -z "$kivou_shared_provider_accounts"

echo 'kivou_credential_isolation_check=PASS'
```

C'est le `set -euo pipefail` en tête du bloc qui arrête l'exécution au
premier `test` en échec, avant `echo` ; coller ce bloc en une fois, jamais
ligne par ligne, sans quoi un shell interactif continuerait après une
commande en échec. Ne jamais continuer sur un échec de cette vérification :
cela signifierait que la production partage une clé, un workspace ou une
boîte avec le staging.

## 4. Installation du runtime Hermes épinglé

Le runtime Hermes de production réutilise l'installation immuable déjà
décrite au runbook 08 : dépôt `https://github.com/NousResearch/hermes-agent.git`,
tag `v2026.8.18`, commit `e624e9fde561e1add9388384012b295fde669ade`, version
de paquet `0.20.4`. C'est la **même** installation `/opt/kivou/hermes-agent/<commit>`
que le staging — un seul binaire épinglé sert les deux environnements ; seuls
`KIVOU_HERMES_HOME` et `KIVOU_HERMES_CWD` diffèrent (étape 5). Si cette
installation existe déjà (staging déployé en premier), vérifier seulement
la version et passer à l'étape 5 :

```bash
sudo -u kivou \
  /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade/.venv/bin/python \
  -c 'import importlib.metadata; assert importlib.metadata.version("hermes-agent") == "0.20.4"'
```

Sinon, installer exactement comme au runbook 08 :

```bash
set -euo pipefail
sudo install -d -m 0755 -o root -g root /opt/kivou/hermes-agent
sudo git clone --no-checkout https://github.com/NousResearch/hermes-agent.git \
  /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade
sudo git -C /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade \
  fetch --depth=1 origin tag v2026.8.18
sudo git -C /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade \
  checkout --detach e624e9fde561e1add9388384012b295fde669ade
test "$(sudo git -C /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade rev-parse HEAD)" = \
  e624e9fde561e1add9388384012b295fde669ade
test "$(sudo git -C /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade rev-list -n1 v2026.8.18)" = \
  e624e9fde561e1add9388384012b295fde669ade
sudo env UV_PROJECT_ENVIRONMENT=/opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade/.venv \
  uv sync --locked --python 3.12 --extra all \
  --directory /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade
sudo chown -R root:root \
  /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade
sudo -u kivou \
  /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade/.venv/bin/python \
  -c 'import importlib.metadata; assert importlib.metadata.version("hermes-agent") == "0.20.4"'
```

`set -euo pipefail` en tête du bloc est ce qui rend cette phrase vraie : sans
lui, un `test` en échec sur le commit ou le tag laisserait `uv sync`, `chown`
et l'assertion finale s'exécuter quand même, sur un checkout potentiellement
faux. Coller ce bloc en une fois, jamais ligne par ligne. Tout écart de
version, de commit ou de tag arrête l'installation. Ne jamais substituer un
tag plus récent, une branche, un autre paquet, ou un modèle de repli.

## 5. Provisionnement des fichiers protégés

Quatre fichiers protégés, distincts de ceux du staging, sont nécessaires :
l'environnement de production, le document de déploiement (Policy/QA scope/
limites), le document de connectivité (workspace Instantly + boîtes), et le
répertoire HOME de Hermes en production.

```bash
set -euo pipefail
sudo install -d -m 0700 -o kivou -g kivou /var/lib/kivou/hermes
sudo install -d -m 0700 -o kivou -g kivou /var/lib/kivou/hermes/work
sudo install -m 0600 -o kivou -g kivou ops/examples/hermes-shadow-config.yaml \
  /var/lib/kivou/hermes/config.yaml
sudo install -m 0600 -o kivou -g kivou /dev/null \
  /var/lib/kivou/hermes/.env
sudoedit /var/lib/kivou/hermes/.env

sudo install -m 0600 -o root -g kivou ops/examples/acquisition-production.env.example \
  /etc/kivou/acquisition-production.env
sudo install -m 0640 -o root -g kivou ops/examples/acquisition-production.json.example \
  /etc/kivou/acquisition-production.json
sudo install -m 0640 -o root -g kivou ops/examples/acquisition-production-connectivity.json.example \
  /etc/kivou/acquisition-production-connectivity.json
sudoedit /etc/kivou/acquisition-production.env
sudoedit /etc/kivou/acquisition-production.json
sudoedit /etc/kivou/acquisition-production-connectivity.json
```

Coller ce bloc en une fois : `set -euo pipefail` arrête le provisionnement au
premier `install`/`sudoedit` en échec plutôt que de laisser les étapes
suivantes s'exécuter contre un fichier absent ou mal posé.

Dans `/var/lib/kivou/hermes/.env`, saisir uniquement l'identifiant OpenRouter
sous la variable `OPENROUTER_API_KEY`. Ne jamais le coller dans une commande,
un historique de shell, Git, ou un journal. `config.yaml` reste le contrat de
modèle figé et non secret (`HERMES_SHADOW_MODEL_CONFIG`, identique en
production et en staging) ; le copier tel quel, sans le modifier.

Dans `/etc/kivou/acquisition-production.env`, saisir les clés Apollo et
Instantly de production réelles — jamais celles du staging (étape 3). Dans
`/etc/kivou/acquisition-production.json`, ajuster `qa_scope.wedge` à la
valeur décidée (précondition, étape 1) ; ne pas modifier `limits` sans
relire la justification du runbook de conception (`maximum_cycle_cost`
couvre le pire cycle isolé, pas le coût attendu). Dans
`/etc/kivou/acquisition-production-connectivity.json`, remplacer le
`instantly_workspace_ref` d'exemple et les trois boîtes par les références
réelles de production — jamais celles du staging.

Vérifier ensuite les permissions :

```bash
sudo stat -c '%a %U %G %n' \
  /etc/kivou/acquisition-production.env \
  /etc/kivou/acquisition-production.json \
  /etc/kivou/acquisition-production-connectivity.json \
  /var/lib/kivou/hermes \
  /var/lib/kivou/hermes/.env
```

Les modes attendus sont `0600 root:kivou` pour l'environnement, `0640
root:kivou` pour les deux documents JSON, `0700 kivou:kivou` pour le HOME
Hermes, et `0600 kivou:kivou` pour son fichier secret. **Exécuter maintenant
le bloc de vérification de l'étape 3** avant de continuer.

## 6. Amorçage du premier contrôle Policy de production

Une seule commande, exécutée une seule fois par environnement, pose le tout
premier contrôle Policy — décidé le 2026-09-01 : ASSISTED (pas SHADOW),
lecture seule et coupe-circuit désarmés, plafond de volume quotidien à zéro.
Elle échoue si un contrôle existe déjà : ne jamais la répéter après un
premier succès.

Ce contrôle est exécutable, mais ce n'est pas un levier d'envoi : cinq gardes
indépendants retiennent la commercial mutation, aucun d'eux porté par ce seul
contrôle — `PROVIDER_HANDOFF` reste `WAITING` inconditionnel sans
`--allow-qa-provider-mutations`, un drapeau que le CLI refuse de toute façon
dès que l'environnement est PRODUCTION (étape 8) ; `daily_volume_cap=0` fait
échouer en `BUDGET_EXCEEDED` les deux seules commandes du registre qui
portent un volume (`schedule_campaign`, `execute_provider_operations`) ;
sous ASSISTED, toute commande COMMERCIAL_MUTATION exige un accord humain à
usage unique, qu'aucun cycle automatisé ne fournit ; et la composition de
production ne construit aucun détournement de destinataire. Le détail complet
de ces cinq gardes vit dans le docstring de `bootstrap_policy_control`.

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations \
  bootstrap-policy-control \
  --reason-code ACQUISITION_PRODUCTION_SHADOW --actor OPAQUE_ACTOR \
  --daily-cost-cap 30.00 --country FR --language fr --wedge WEDGE_VALUE
```

Remplacer `OPAQUE_ACTOR` par une référence opérateur opaque (jamais un nom ou
une adresse) et `WEDGE_VALUE` par la valeur exacte déjà saisie dans
`qa_scope.wedge` à l'étape 5 — un désaccord fait échouer chaque cycle avec
`POLICY_SCOPE_NOT_EXACT`. `--country` n'accepte que `CH` ou `FR` ; `--language`
n'accepte que `fr` ou `en`. La commande refuse toute base ou horloge fournie
en ligne de commande (précisé en tête de ce runbook) : ne jamais ajouter un
tel argument.

`daily-cost-cap` (30.00 CHF) et `maximum_cycle_cost` (10.00 CHF, dans le
document de déploiement de l'étape 5) jouent des rôles distincts. Le premier
borne la journée entière — sans lui, une cadence horaire autoriserait
vingt-quatre fois le pire cycle isolé — le second borne un seul cycle. Une
fois le plafond quotidien atteint, la Policy répond `BUDGET_EXCEEDED` et les
cycles suivants s'arrêtent d'eux-mêmes jusqu'au lendemain. Ces deux valeurs
ne sont révisées qu'après le relevé à sept jours, pas avant.

La sortie attendue est exactement une ligne :

```
acquisition_ops bootstrap status=APPENDED revision=1 autonomy=ASSISTED read_only=false kill_switch=false volume_cap=0
```

`status=REFUSED` arrête cette étape ; lire le `reason=` affiché et corriger
avant de réessayer.

## 7. Installation des unités et vérification des dépendances

```bash
set -euo pipefail
sudo install -o root -g root -m 644 \
  ops/systemd/kivou-acquisition-production.service \
  ops/systemd/kivou-acquisition-production.timer \
  /etc/systemd/system/
sudo systemd-analyze verify \
  /etc/systemd/system/kivou-acquisition-production.service \
  /etc/systemd/system/kivou-acquisition-production.timer
sudo systemctl daemon-reload
```

Sans `set -euo pipefail`, un `systemd-analyze verify` en échec n'empêcherait
pas `daemon-reload` de recharger une unité invalide ou absente ; coller ce
bloc en une fois.

Puis, avant tout cycle, prouver que les onze dépendances du runtime sont
`READY` à partir de sondes fraîches en lecture seule — aucune mutation
fournisseur, aucun cycle :

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-production.env \
  /srv/kivou/app/.venv/bin/python -m signals.acquisition_runtime check-dependencies
```

Continuer uniquement sur la ligne exacte `status=READY dependency_count=11`
et un code de sortie zéro.

## 8. Premier cycle manuel et lecture du journal

Exécuter un premier cycle manuellement, hors du timer, pour l'observer avant
toute automatisation :

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=RuntimeDirectory=kivou \
  --property=RuntimeDirectoryMode=0700 \
  --property=RuntimeMaxSec=20min \
  --property=EnvironmentFile=/etc/kivou/production.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-production.env \
  /usr/bin/flock --verbose --nonblock --conflict-exit-code 0 \
  /run/kivou/acquisition.lock \
  /srv/kivou/app/.venv/bin/python -m signals.acquisition_runtime run-once
```

Cette commande ne passe et ne doit **jamais** passer
`--allow-qa-provider-mutations` : le CLI le rejette de toute façon dès que
`KIVOU_ACQUISITION_ENVIRONMENT=PRODUCTION`, mais ce runbook ne le propose
même pas comme option. Lire ensuite le journal — bornée à des codes machine
et des références opaques, jamais une adresse, un contenu ou un payload :

```bash
sudo journalctl -u kivou-acquisition-production.service \
  --since "today" --output=short-iso --no-pager
```

`status=COMPLETED` exige que les onze stages, y compris `PROVIDER_HANDOFF`,
se terminent `SUCCEEDED` — structurellement hors d'atteinte en phase 1, car
`PROVIDER_HANDOFF` reste `WAITING` inconditionnel sans
`--allow-qa-provider-mutations`, que la production ne passe jamais. Le
résultat attendu est donc `status=WAITING`, avec l'un de ces deux
`reason_code` : `POLICY_APPROVAL_REQUIRED` si le cycle a atteint une
commande COMMERCIAL_MUTATION (`PERSONALIZATION`/`prepare_campaign` en
premier) sans accord humain à usage unique préexistant, ou
`QA_PROVIDER_MUTATION_NOT_AUTHORIZED` s'il a atteint `PROVIDER_HANDOFF`. Un
`status=WAITING` répété au même stage avec l'un de ces deux `reason_code` est
sain, pas un échec. Un `status=WAITING` répété au même stage avec
`APOLLO_PROVIDER_OUTCOME_AMBIGUOUS` signale en revanche une reprise
fournisseur ambiguë (identique à la sémantique déjà documentée au
runbook 10) et doit être investigué, de même qu'un `status=BLOCKED` ou
`status=FAILED` — ne jamais activer le timer sur un premier cycle dans l'un
de ces trois états.

## 9. Activation du timer et observation du premier tir automatique

```bash
set -euo pipefail
sudo systemctl enable --now kivou-acquisition-production.timer
sudo systemctl list-timers kivou-acquisition-production.timer --no-pager
```

Attendre le premier déclenchement automatique (au plus une heure, plus le
délai aléatoire de 300 secondes), puis relire le journal comme à l'étape 8.
Chaque tir suivant est indépendant : le bail PostgreSQL et `flock` empêchent
deux cycles concurrents, et un cycle interrompu reprend depuis le premier
stage durable non terminal, jamais depuis le début.

## Santé, readiness et arrêt d'urgence

Ces trois commandes sont indépendantes — exécuter chacune séparément, selon
le besoin, jamais comme un script unique. En particulier,
`activate-kill-switch` est l'action d'urgence : elle ne doit jamais dépendre
d'un `health`/`readiness` préalable réussi, donc ces trois blocs restent
volontairement séparés plutôt que chaînés par `set -euo pipefail` — chaîner
l'arrêt d'urgence derrière deux sondes de lecture le bloquerait précisément
quand la base ou le réseau est déjà en mauvais état, c'est-à-dire au moment
où l'opérateur en a le plus besoin. Chacun des trois blocs ci-dessous est une
seule commande shell (les sauts de ligne ne sont que de la continuation) ;
`set -euo pipefail` n'y ajoute donc rien.

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations health
```

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations readiness
```

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations \
  activate-kill-switch --reason-code OPERATOR_PRODUCTION_STOP
```

Un health `READY` exige une observation durable récente, le pin Hermes
exact, le registre fermé, zéro outil natif, Policy et les onze dépendances du
cycle. La readiness reste honnêtement bornée : un cycle de production sain
— zéro outil natif Hermes, Policy ASSISTED plafonnée à un volume nul — ne
constitue jamais une autorisation d'envoi — la phase 2, hors périmètre, en
décidera séparément.

## Rollback

```bash
set -euo pipefail
sudo systemctl disable --now kivou-acquisition-production.timer
sudo systemctl stop kivou-acquisition-production.service
sudo rm /etc/systemd/system/kivou-acquisition-production.service \
  /etc/systemd/system/kivou-acquisition-production.timer
sudo systemctl daemon-reload
```

Si `disable --now` ou `stop` échoue, ne pas continuer vers `rm` : supprimer
les fichiers d'unité pendant qu'un cycle tourne encore ou que systemd les
croit toujours actifs laisse un état incohérent. `set -euo pipefail` arrête
le bloc à la première commande en échec.

Le downgrade de `0029_production_observation_boundary` restaure l'ancienne
contrainte `environment = 'STAGING' AND ... AND qa_only IS TRUE`, qui rejette
toute ligne `PRODUCTION`. **Il échoue avec une erreur d'intégrité si une
observation de production existe déjà** — la migration ne supprime jamais
cette ligne pour se faire réussir elle-même. Avant de l'exécuter, décider
explicitement : soit supprimer la ligne d'observation de production (perte
de donnée assumée et journalisée), soit renoncer au downgrade et rester sur
`0029`. Ne jamais improviser cette décision au clavier pendant l'incident ;
elle doit être prise avant, dans la procédure de release.

Après sauvegarde et avec l'artefact courant encore présent, le downgrade
exact d'une révision utilise la configuration Alembic programmatique du
dépôt, comme au runbook 10 :

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/app/.venv/bin/python -c '
from alembic import command
from signals.persistence.database import alembic_config, create_database_engine
engine = create_database_engine(pool_pre_ping=True)
try:
    config = alembic_config(engine)
    command.downgrade(config, "0028_card_presentation")
finally:
    engine.dispose()
'
```

Vérifier ensuite que `alembic_version` vaut `0028_card_presentation`.
Restaurer le code avant ce contrôle supprimerait précisément la migration
`0029` nécessaire pour l'annuler.

Restaurer ensuite l'artefact applicatif précédent et conserver le timer
désactivé jusqu'au smoke test du rollback. Le contrôle Policy de production
posé à l'étape 6 n'est jamais supprimé par ce rollback : il reste en place,
ASSISTED avec un plafond de volume quotidien toujours à zéro, mais plus aucun
cycle ne l'invoque tant que le timer reste désactivé. Il ne doit pas être
réutilisé par un futur amorçage — `bootstrap-policy-control` le refuserait de
toute façon.
