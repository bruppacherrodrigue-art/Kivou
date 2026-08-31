# Acquisition en production — phase 1 : naissance du mode PRODUCTION en SHADOW

Date : 2026-08-31
Statut : design validé en conversation ; implémentation non commencée
Socle de référence : `origin/main` à `c8ea78c`
Cible : `kivou-production-01`, backend déployé `ab7861fec297`

## Objet

Installer en production l'intégralité de la chaîne d'acquisition, la faire tourner
en continu, et garantir qu'**aucun message ne peut partir** — non par une politique
qui retiendrait l'envoi, mais parce que le chemin d'envoi n'existe pas en
production. La phase 2, hors de ce document, construira ce chemin et le levier
d'activation.

Le résultat attendu de la phase 1 est une mesure : combien d'opportunités
françaises le moteur traiterait, lesquelles il jugerait envoyables, et à quel coût
réel par opportunité.

## État constaté

### Dans le dépôt

`main` porte un runtime d'acquisition complet — `src/signals/acquisition_runtime/`,
les unités `kivou-acquisition.service`/`.timer`, le runbook
`10-acquisition-runtime.md`, la migration `0026_acquisition_runtime` et la table
durable `acquisition_runtime_approval`.

Ce runtime est **un banc d'essai de staging, par construction** :

| Barrière | Emplacement |
| --- | --- |
| `load_runtime_config` lève `WRONG_ENVIRONMENT` hors `STAGING` | `config.py:72` |
| `environment: Literal["STAGING"]` | `contracts.py:153`, `contracts.py:271` |
| `mode: Literal[SHADOW]`, `qa_only: Literal[True]` | `contracts.py` |
| détournement de destinataire vers une boîte QA liée par HMAC | `transport.py:33` |
| `maximum_suppliers: Literal[1]`, `maximum_contacts: Literal[1]` | `contracts.py` |
| allowlist d'opportunités possédée par l'opérateur, 1 à 8 clés | `contracts.py` |
| `qa_scope` explicite : « no runtime heuristic may derive it » | `contracts.py` |

Aucune de ces bornes n'est un défaut. Ce sont des barrières délibérées. La
phase 1 en relâche exactement **deux**, nommées : l'élargissement du type
`environment` (D2) et le remplacement de l'allowlist par une sélection bornée,
en production seulement (D4). Toutes les autres restent en place.

### En production, constaté le 2026-08-31 en lecture seule

- aucune unité `kivou-acquisition*` dans `/etc/systemd/system` ;
- `/opt/kivou` inexistant : **aucun runtime Hermes** ;
- `/etc/kivou/production.env` ne définit aucune variable Apollo, Instantly,
  Hermes, OpenRouter ni `KIVOU_ACQUISITION_ENVIRONMENT` ;
- `python -m signals.operations health` →
  `NOT_READY reasons=POLICY_CONTROL_UNAVAILABLE,RUNTIME_OBSERVATION_UNAVAILABLE` ;
- `python -m signals.operations readiness` →
  `highest_safe_mode=SHADOW` avec sept bloqueurs :
  `ALLOCATION_ENVELOPE_UNCONFIGURED`, `CAMPAIGN_EXECUTION_UNHEALTHY`,
  `COST_COVERAGE_INCOMPLETE`, `HUMAN_REVIEW_TRUTH_UNAVAILABLE`,
  `POLICY_CONTROL_UNAVAILABLE`, `PRODUCTION_MAILBOX_UNCONFIGURED`,
  `RUNTIME_OBSERVATION_UNAVAILABLE` ;
- **aucune ligne de contrôle Policy n'existe** : `downgrade()` et `critical_stop()`
  lisent le contrôle courant avant d'écrire et échouent donc en production ; seul
  `qa_policy_window`, restreint au staging, sait en écrire un premier.

L'absence d'erreur de schéma sur `health` indique que `0026_acquisition_runtime`
est appliquée ; l'installation le confirmera explicitement.

## Périmètre

### Dans la phase 1

1. Faire naître le mode `PRODUCTION` du runtime, en `SHADOW`, sans chemin d'envoi.
2. Sélectionner automatiquement l'opportunité de chaque cycle, côté production.
3. Amorcer le premier contrôle Policy de production.
4. Provisionner l'hôte : Hermes épinglé, fichiers protégés, unités de production.
5. Observer en continu et produire le relevé à sept jours.

### Hors phase 1

Le chemin d'envoi et le levier d'activation ASSISTED — c'est la phase 2.
`AUTONOMOUS_CAPPED` et `ADAPTIVE_SCALE`. Les pages légales de l'issue #30. La
panne d'ingestion TED. Toute modification du feed client ou du moteur de signaux.

## Décisions de conception

### D1 — Deux formes de déploiement, discriminées par `schema_version`

`acquisition-runtime-v1` reste **inchangé** et reste la forme du staging : QA,
allowlist, boîte de repli. Une forme nouvelle `acquisition-production-v1` porte le
déploiement de production. Elle n'a **aucun** champ QA — ni `qa_only`, ni
`qa_recipient_identity_hmac`, ni `qa_recipient_key_version`, ni
`qa_provider_mutations_capable` — et remplace `allowed_opportunity_keys` par un
bloc de ciblage : pays `FR`, langue `fr`, wedge.

Le staging n'est donc pas touché d'une ligne, et une configuration de staging
posée par erreur en production est rejetée par son seul `schema_version`.

### D2 — `load_runtime_config` branche sur l'environnement

`STAGING` conserve le chemin actuel à l'identique. `PRODUCTION` exige un
déploiement `acquisition-production-v1` et **refuse de démarrer** si
`KIVOU_ACQUISITION_QA_RECIPIENT` ou `KIVOU_ACQUISITION_QA_RECIPIENT_KEY` sont
seulement présents dans l'environnement. Une boîte de repli en production est une
erreur de configuration fatale, jamais une valeur ignorée.

`environment` devient `Literal["STAGING", "PRODUCTION"]` sur
`AcquisitionRuntimeConfig` et `RuntimeCapabilityEvidence`. C'est le seul
élargissement de type de la phase 1.

### D3 — La production n'a pas de chemin d'envoi

`--allow-qa-provider-mutations` est **rejeté** en `PRODUCTION` : la commande sort
en erreur d'argument. Le drapeau reste ce que le runbook 10 en dit — une porte
manuelle de staging.

Le garde de `transport.py` n'est pas modifié. Il continue d'exiger `STAGING`,
`SHADOW`, `qa_only` et `qa_provider_mutations_capable` pour construire un
détournement de destinataire. En production, ce constructeur ne peut donc jamais
être instancié : il n'existe pas de destinataire de repli, et pas d'envoi.

### D4 — Sélection bornée de l'opportunité du cycle

C'est la seule barrière relâchée, et seulement en `PRODUCTION` : l'allowlist
possédée par l'opérateur est remplacée par une sélection déterministe.

Chaque cycle choisit **une** opportunité éligible : pays `FR`, wedge configuré,
jamais retenue par un cycle antérieur — la preuve étant l'enregistrement durable
des cycles, pas un fichier ni une mémoire de processus —, la plus récente d'abord. La règle est
déterministe, idempotente, et la clé retenue est inscrite dans l'événement de
cycle. Deux cycles concurrents ne peuvent pas choisir la même : le bail
PostgreSQL et le verrou `flock` existants s'en chargent.

`maximum_suppliers` et `maximum_contacts` **restent à 1**. Le volume vient de la
cadence, pas de l'élargissement des bornes.

### D5 — Amorçage du contrôle Policy

Une commande explicite écrit la **première** ligne de contrôle de production —
elle refuse si un contrôle existe déjà, exige un code de motif, inscrit
`created_by_actor_type="HUMAN"`, et pose :

```
autonomy_mode      = SHADOW
shadow_target_mode = ASSISTED
read_only          = True
kill_switch        = True
daily_volume_cap   = 0
allowed_countries  = ("FR",)
currency           = CHF
daily_cost_cap     = 30.00 CHF
```

Les deux plafonds jouent des rôles distincts et ne se déduisent pas l'un de
l'autre. `maximum_cycle_cost` reste à `10.00` : c'est le pire cycle isolé, celui
qui couvre le chemin Apollo normal plus une reprise après réponse ambiguë, pas le
coût attendu. `daily_cost_cap` à `30.00` borne la journée entière — sans lui, une
cadence horaire autoriserait vingt-quatre fois le pire cycle. Une fois le plafond
quotidien atteint, la Policy répond `BUDGET_EXCEEDED` et les cycles suivants
s'arrêtent d'eux-mêmes jusqu'au lendemain. Ces deux valeurs sont révisées sur le
relevé à sept jours, pas avant.

Ce n'est **pas** le levier d'activation : ce contrôle est non exécutable. Le
coupe-circuit reste armé sans gêner le cycle, puisque `kill_switch` laisse passer
les classes `READ_ONLY`, `PREPARATORY`, `RISK_REDUCTION` et `HUMAN_REVIEW`, et que
tout le cycle d'observation est `PREPARATORY`.

### D6 — Cadence et unités

Les unités de production sont des variantes de celles de `main` : `production.env`
au lieu de `staging.env`, `acquisition-production.env` au lieu de
`acquisition-shadow.env`/`acquisition-runtime.env`. Le timer reste **horaire**,
comme livré : une opportunité par cycle, jusqu'à vingt-quatre mesures par jour,
chacune bornée par `maximum_cycle_cost`.

## Invariants de sûreté

Ces énoncés sont vérifiés par des tests, et leur violation fait échouer la suite.

1. `PRODUCTION` ne construit jamais de détournement de destinataire.
2. `PRODUCTION` refuse `--allow-qa-provider-mutations`.
3. Un déploiement `acquisition-runtime-v1` est rejeté en `PRODUCTION`.
4. Un déploiement `acquisition-production-v1` est rejeté en `STAGING`.
5. Le cycle de production n'émet aucune mutation commerciale : tout delta de
   mutation fournisseur vaut zéro à la fin de chaque cycle, et un delta non nul
   fait échouer le cycle. Le nombre exact de compteurs est celui que le runtime
   expose déjà ; l'implémentation les assertera tous, sans en présumer le nombre.
6. Aucun secret, aucune adresse, aucun objet fournisseur brut, aucun prompt ni
   réponse de modèle n'entre dans le journal.
7. Le staging reste inchangé : ses contrats, ses fichiers et son runbook ne sont
   pas modifiés.

## Provisionnement

Runtime Hermes épinglé au dépôt `NousResearch/hermes-agent`, tag `v2026.8.18`,
commit `e624e9fde561e1add9388384012b295fde669ade`, version `0.20.4`, installé sous
`/opt/kivou/hermes-agent/<commit>` en `root:root`, version vérifiée après
installation.

Fichiers protégés, saisis par éditeur root, jamais par ligne de commande :
`/etc/kivou/acquisition-production.env` en `0600 root:kivou`,
`/etc/kivou/acquisition-production.json` en `0640 root:kivou`,
`/var/lib/kivou/hermes/.env` en `0600 kivou:kivou`.

`KIVOU_ACQUISITION_ENVIRONMENT=PRODUCTION` est explicite : `resolve_acquisition_environment()`
n'infère jamais la production.

**Vérification préalable obligatoire** : les clés Apollo et Instantly de production
doivent être distinctes de celles du staging — par empreinte, référence de
workspace et références de mailbox. Le runbook 07 l'exige, et la confusion
Kivou/Turiya sur Stripe montre que la vérification n'est pas théorique.

Un runbook `12-acquisition-production-shadow.md` porte la procédure complète,
versionné avec les unités dans `ops/`.

## Preuves d'acceptation

1. `python -m signals.acquisition_runtime check-dependencies` en production : toutes
   les dépendances `READY`.
2. Un premier cycle manuel : code de sortie 0, une opportunité traitée, coût réel
   mesuré, contrefactuel enregistré, tous les deltas de mutation nuls.
3. Premier déclenchement automatique du timer observé.
4. `health` ne rapporte plus `POLICY_CONTROL_UNAVAILABLE` ni
   `RUNTIME_OBSERVATION_UNAVAILABLE`.
5. Journal relu : aucun secret, aucune adresse.
6. **Relevé à sept jours** : nombre d'opportunités traitées, nombre de
   contrefactuels `APPROVED`, coût réel par opportunité, part de
   `REVIEW_REQUIRED`, et les bloqueurs de readiness restants. C'est le dossier
   d'entrée de la phase 2.

## Retour arrière

`sudo systemctl disable --now kivou-acquisition.timer`, arrêt de l'unité,
puis restauration de l'artefact précédent par la procédure de release normale.

La phase 1 introduit **une migration, `0029`**, et une seule. Elle remplace la
contrainte `ck_acquisition_runtime_observation_boundary`, qui imposait
`environment = 'STAGING' AND qa_only IS TRUE` au niveau de la base et rendait
donc toute observation de production impossible — un cycle de production
échouait à sa première écriture, avant le moindre stage.

La contrainte nouvelle n'affaiblit pas le staging d'un iota : `mode = 'SHADOW'`
et `native_tools = 0` restent exigés sans condition, le staging continue
d'exiger `qa_only IS TRUE`, et la production exige `qa_only IS FALSE`. La base
refuse donc d'elle-même une observation de production qui se prétendrait QA.

Cette révision était annoncée absente dans une version antérieure de ce
document. Elle a été découverte par l'exécution, et son ajout a été autorisé
explicitement le 2026-09-01.

Le downgrade rétablit la contrainte d'origine. Il n'est exécutable que si aucune
ligne d'observation de production n'existe — sans quoi la contrainte restaurée
rejetterait des lignes déjà écrites. La procédure de retour arrière doit donc
supprimer l'observation de production avant de redescendre, ou renoncer au
downgrade et se contenter de désactiver le timer.

Le contrôle Policy amorcé reste en place — il est non exécutable, donc
inoffensif — et `activate-kill-switch` redevient disponible dès qu'un contrôle
existe.

Aucune réactivation automatique.

## Risques et dépendances

- **#30, pages légales.** Sans identité d'expéditeur, mécanisme d'opposition,
  notice de confidentialité et notice de provenance publiées, la conformité
  française ne peut pas atteindre `ALLOWED`. La phase 1 mesurera donc surtout des
  `REVIEW_REQUIRED` tant que #30 n'est pas close. C'est une mesure honnête, pas un
  échec du moteur.
- **Dépense sans revenu.** Chaque cycle consomme de vrais crédits Apollo et
  OpenRouter. Le plafond `maximum_cycle_cost` et la cadence horaire bornent la
  dépense ; le relevé à sept jours la chiffre.
- **Sept bloqueurs de readiness.** La phase 1 vise à lever
  `POLICY_CONTROL_UNAVAILABLE` et `RUNTIME_OBSERVATION_UNAVAILABLE`, qui sont des
  conséquences directes de l'installation. `COST_COVERAGE_INCOMPLETE` devrait
  suivre une fois des coûts réels enregistrés, sans que ce soit acquis.
  `PRODUCTION_MAILBOX_UNCONFIGURED`, `CAMPAIGN_EXECUTION_UNHEALTHY`,
  `ALLOCATION_ENVELOPE_UNCONFIGURED` et `HUMAN_REVIEW_TRUTH_UNAVAILABLE`
  appartiennent à la phase 2. Le relevé à sept jours dira lesquels sont
  réellement tombés — c'est une mesure, pas une prévision.
- **Backend de production en retard.** L'hôte tourne `ab7861f` quand `main` est à
  `c8ea78c`. La phase 1 suppose un déploiement du SHA approuvé le plus récent.

## Ce que cette phase ne prouve pas

Qu'un e-mail réel part correctement, qu'un prospect répond, que le webhook de
désinscription alimente la suppression, ou que la conformité française tient
devant un contrôle. Elle ne lève pas non plus la réserve nº 2 du rapport #141 :
l'Acquisition Engine consomme les signaux, il n'en produit pas.
