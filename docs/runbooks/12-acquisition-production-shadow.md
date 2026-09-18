# Préparation catalogue Acquisition — PRODUCTION/ASSISTED

Ce runbook couvre uniquement la préparation de la file Founder. Le runtime
parcourt toutes les familles de `ops/config/supplier-families.yaml`, retient des
avis strictement mono-famille et crée au plus 25 lignes `pending_review` toutes
familles confondues. Le plafond inclut les lignes déjà `pending_review` ou
`approved`, quelle que soit leur date.

La commande de production est exclusivement `prepare-queue`. Elle ne charge ni
Apollo, ni un modèle, ni le client Instantly et ne transporte aucun message.
Elle ne doit jamais être remplacée par `run-once` pour préparer la file. L'envoi
reste une action Founder séparée, hors de ce runbook ; ne jamais appeler
`/api/founder/actions/prospection/send` pendant cette procédure.

Le coupe-circuit immédiat est :

```bash
set -euo pipefail
sudo systemctl stop kivou-acquisition-production.timer
```

Le fichier `/etc/kivou/acquisition.disabled` bloque aussi le service et l'action
Founder. Ne le retirer qu'après diagnostic opérateur.

## 1. Contrat du catalogue

Une ligne préparée doit respecter simultanément ces invariants :

- une seule `family_key`, identique à la famille mono-famille de son avis ;
- un titulaire officiel avec SIREN, exclu des cibles de son propre avis ;
- une cible confirmée dans le département de l'avis ou un département voisin ;
- `email_source=site`, preuve de publication conservée et statut `mx_verified` ;
- aucune cible envoyée depuis 30 jours, rejetée, déjà active ou déjà matérialisée
  pour cet avis ;
- un kat1 propre au couple cible–avis, identique dans le HTML, le texte et
  `attribution_url` ;
- statut final `pending_review` et `delivery_status=not_sent`.

La sélection et le rendu restent attachés au même `award_key`. Le cycle global
est seulement un résumé d'affichage : chaque ligne conserve son
`opportunity_key`, sa famille, les faits de son avis et son token. Un second
prepare le même jour ignore les SIREN déjà `pending_review` ou `approved` et ne
frappe aucun second token.

L'allocation est un round-robin strict : une cible de chaque famille éligible,
puis une nouvelle passe, avant d'ouvrir les avis de rang suivant. Une famille à
zéro n'empêche jamais les autres. `deferred_global_cap` n'est pas un rejet
persisté.

## 2. Configuration protégée

Le service lit `/etc/kivou/production.env` puis
`/etc/kivou/acquisition-production.env`. Pour `prepare-queue`, les seules
dépendances sensibles utilisées sont la base et la configuration kat1 partagées
par l'application. Les clés Apollo/Instantly et la configuration Hermes peuvent
rester présentes pour les anciens chemins, mais elles ne sont ni lues ni
testées par la composition catalogue.

Installer le document catalogue depuis l'exemple versionné :

```bash
set -euo pipefail
sudo install -m 0640 -o root -g kivou \
  /srv/kivou/app/ops/examples/acquisition-production.json.example \
  /etc/kivou/acquisition-production.json
sudo stat -c '%a %U %G %n' \
  /etc/kivou/acquisition-production.env \
  /etc/kivou/acquisition-production.json
```

Le JSON doit porter `mode=ASSISTED`, `selection.mode=catalog`,
`selection.email_source=site`, `qa_scope.vertical=null`, une région connue et
aucun `family_key`, `vertical`, `pinned_opportunity_key` ou avis autorisé dans
la sélection.

## 3. Installation des unités

```bash
set -euo pipefail
sudo install -o root -g root -m 0644 \
  /srv/kivou/app/ops/systemd/kivou-acquisition-production.service \
  /srv/kivou/app/ops/systemd/kivou-acquisition-production.timer \
  /etc/systemd/system/
sudo systemd-analyze verify \
  /etc/systemd/system/kivou-acquisition-production.service \
  /etc/systemd/system/kivou-acquisition-production.timer
sudo systemctl daemon-reload
```

L'`ExecStart` attendu contient exactement le verrou global puis
`python -m signals.acquisition_runtime prepare-queue`, avec le code de conflit
75. Il ne doit contenir ni `run-once`, ni drapeau de mutation fournisseur.

## 4. Snapshot avant préparation

Arrêter temporairement le timer pour garantir une seule exécution observée :

```bash
set -euo pipefail
sudo systemctl stop kivou-acquisition-production.timer
sudo systemctl is-active kivou-acquisition-production.service \
  && { echo 'catalog service is still active' >&2; exit 1; } || true
```

Avant le prepare, relever en lecture seule le nombre de lignes par statut et
conserver en particulier `sent`. La recette exige que ce nombre soit strictement
inchangé après l'opération.

## 5. Unique préparation manuelle verrouillée

Exécuter ce bloc une seule fois. Un code 75 signifie qu'un autre prepare détient
déjà le verrou : ne pas relancer automatiquement.

```bash
set -euo pipefail
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=RuntimeDirectory=kivou \
  --property=RuntimeDirectoryMode=0700 \
  --property=EnvironmentFile=/etc/kivou/production.env \
  --property=EnvironmentFile=/etc/kivou/acquisition-production.env \
  /usr/bin/flock --verbose --nonblock --conflict-exit-code 75 \
  /run/kivou/acquisition.lock \
  /srv/kivou/app/.venv/bin/python -m signals.acquisition_runtime prepare-queue
```

La première ligne attendue est :

```text
status=CATALOG_PREPARED prepared=N active=M cycle_ref=...
```

Elle est suivie d'une ligne par famille avec `notices_examined`,
`notices_admissible`, `notices_used`, `eligible`, `queued`, les refus par motif,
`deferred`, les opportunités utilisées et `zero_reason`. Une erreur propre à une
famille donne zéro pour cette famille ; une erreur globale rend
`status=CATALOG_PREPARATION_FAILED` et la transaction entière doit rester vide.

## 6. Recette

Après le prepare, vérifier :

1. `pending_review + approved <= 25` sur toute la file, sans filtre de date ;
2. chaque nouvelle ligne a une seule famille, `email_source=site`, le bon
   `opportunity_key`, `delivery_status=not_sent` et aucune référence fournisseur ;
3. HTML, texte et `attribution_url` contiennent exactement le même kat1 ;
4. le titulaire de l'avis n'est pas une cible ;
5. aucun couple historique cible–avis et aucun couple avis–e-mail n'est recréé ;
6. deux previews de familles différentes, si disponibles, parlent uniquement
   du métier et de l'avis de leur propre ligne ;
7. le nombre `sent` est identique au snapshot précédent.

Le journal borné du service est accessible ainsi :

```bash
set -euo pipefail
sudo journalctl -u kivou-acquisition-production.service \
  --since today --output=short-iso --no-pager
```

Ne jamais corriger une ligne en la faisant partir depuis ce runbook.

## 7. Réactivation du timer

Réactiver le timer uniquement s'il était actif avant l'intervention et si la
recette est entièrement conforme :

```bash
set -euo pipefail
sudo systemctl enable --now kivou-acquisition-production.timer
sudo systemctl list-timers kivou-acquisition-production.timer --no-pager
```

Le timer prépare de 06:00 à 23:00 Europe/Zurich. Le verrou fichier et le verrou
transactionnel PostgreSQL empêchent deux préparations concurrentes. Une file
déjà pleine produit un delta nul sans créer de token.

## Rollback applicatif

En cas d'échec global, conserver le timer arrêté, restaurer l'artefact applicatif
précédent selon `ops/production/README.md`, puis refaire uniquement les contrôles
en lecture seule. La transaction catalogue est tout-ou-rien ; aucune suppression
manuelle de cibles ne doit être nécessaire après un échec avant commit.
