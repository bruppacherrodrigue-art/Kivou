# Milo Mail : préflight d'un recensement Apollo autorisé

Pour la phase A bornée, utiliser le
[runbook COVERAGE](17-milomail-zero-cost-coverage.md). La recherche
d'organisations coûte actuellement un crédit par page. Le préflight refuse
un plafond nul ; un plafond positif requiert un prix vérifié, une base
autorisée, un permis daté et zéro enrichissement.

**État de cette PR :** préparation technique seulement. Aucun recensement
Apollo réel, crédit consommé, e-mail, export Instantly ou déploiement. Milo
Mail est le produit ; Milo est son agent intégré. Kivou conserve les prospects
et les décisions ; le produit Milo Mail ne reçoit aucune donnée Apollo. Kivou
ne reçoit ni contenu Gmail, ni token OAuth, ni résultat détaillé d'audit.

## Source officielle et rapprochement

L'[API Recherche d'entreprises de l'Annuaire des Entreprises](https://annuaire-entreprises.data.gouv.fr/donnees/api-entreprises),
opérée par l'administration française, fournit les données SIRENE/RNE. La
[documentation de l'API](https://github.com/annuaire-entreprises-data-gouv-fr/search-api)
décrit la recherche par SIREN, SIRET ou nom et une limite annoncée de 400
requêtes par minute et par IP. Documentation consultée le 21 septembre 2026.
Kivou utilise déjà cette origine pour une recherche SIRET exacte ; le census
réutilise l'origine HTTPS fixe et n'accède qu'à `/search`. Le client limite
la réponse, le timeout, les requêtes par recensement et le cache (TTL 7 jours
par défaut, configurable). Un timeout, un 429 ou une indisponibilité laisse
le candidat en attente et suspend la phase B jusqu'à `resume` ; l'erreur ne
prouve jamais l'activité. Une recherche officielle sans résultat donne `HOLD`.

Le statut `A`/`C` de **l'unité légale** détermine actif/cessé. Le statut
`A`/`F` du siège est un autre fait et ne le remplace pas. Le census conserve
SIREN, SIRET du siège, raison sociale, nom commercial, APE, statut, commune,
code postal, date et référence de source. Les champs personnels superflus de
la réponse officielle sont retirés avant mise en cache. Les résultats du
rapprochement sont rattachés au recensement et visibles en agrégat dans le
rapport (`official_legal_status`, `official_match_confidence`).

Un SIREN déjà lié à l'identifiant Apollo par le `SireneApolloBindingStore`
Kivou peut produire `CONFIRMED_MATCH` seulement si le lien a été résolu par
domaine, a une confiance d'au moins 0,9, a moins de 90 jours et son domaine
est identique au domaine Apollo observé. La requête officielle doit rendre
exactement ce SIREN. Une autre voie de confirmation exige un résultat unique,
une raison sociale ou un nom commercial exact, une ville exacte, un code
postal exact fourni par Apollo et le même domaine dans la recherche et
l'enrichissement Apollo. Le domaine n'est alors qu'une cohérence Apollo,
pas une preuve officielle du site. Nom exact et ville concordante sans
SIREN ni code postal donnent `PROBABLE_MATCH`, donc `HOLD` au maximum.
Homonymes concordants donnent
`AMBIGUOUS_MATCH`. Aucun résultat donne `NO_MATCH` et `HOLD` ; une cessation
confirmée donne `NO_SEND`. La source officielle ne publie pas de domaine dans
le résultat de recherche : il serait faux d'affirmer qu'un rapprochement
Apollo/domaine seul est confirmé par l'administration. Les cas non corroborés
restent à revoir. Une entreprise active ne suffit pas à autoriser un message.
Une recherche par nom dont le total est absent, invalide ou supérieur à la
page reçue est aussi `AMBIGUOUS_MATCH` : la première page ne prouve pas
l'unicité. Un SIREN Kivou lié ne peut jamais être remplacé par un autre SIREN
retourné par la recherche officielle.

Configuration fermée par défaut :

| Variable | Défaut | Rôle |
| --- | ---: | --- |
| `MILOMAIL_COMPANY_STATUS_ENABLED` | `false` | Aucun appel officiel si absent. |
| `MILOMAIL_COMPANY_STATUS_MAX_REQUESTS` | `0` | Plafond durable de requêtes publiques par recensement, conservé après `resume`. |
| `MILOMAIL_COMPANY_STATUS_REQUEST_TIMEOUT_SECONDS` | `5` | Timeout HTTP. |
| `MILOMAIL_COMPANY_STATUS_CACHE_TTL_DAYS` | `7` | Validité du cache. |
| `MILOMAIL_COMPANY_STATUS_RATE_LIMIT` | `60` | Maximum local par minute, au plus 400. |
| `MILOMAIL_COMPANY_STATUS_SOURCE` | `ANNUAIRE_ENTREPRISES` | Origine fixe autorisée. |

## Base autorisée et migration

La commande `preflight` ne modifie ni la base ni Apollo. Elle montre un
identifiant logique `dialecte:empreinte-hôte:nom-base`, jamais une URL ou un
mot de passe. Un fichier d'autorisation hors dépôt doit contenir exactement
`database_id`, `environment` (`test`, `staging` ou `authorized-census`),
`issued_by_reference` et `expires_at` ISO 8601 avec fuseau. Aucun environnement
de production n'est accepté. `test` exige une base SQLite jetable ; pour
`staging` ou `authorized-census`, la base doit être PostgreSQL et
`KIVOU_ACQUISITION_ENVIRONMENT=STAGING` doit être déclaré. Les marqueurs
de production Kivou et un hôte ou nom logique de base contenant `prod` sont refusés.
Une autorisation absente, périmée ou visant une
autre base bloque le run. Garder ce fichier dans le gestionnaire opérateur,
pas dans Git.

Sur une base non productive **explicitement autorisée** et sauvegardée à la
révision exacte `0071_milomail_shadow_census`, appliquer une seule fois :

```bash
uv run milomail-census migrate-authorized \
  --database-authorization <autorisation-base.json> --acknowledge-migration
```

La commande refuse une autre révision ; elle ne touche jamais la production.
`0072_milomail_census_readiness` est additive, et l'upgrade/downgrade est
testé sur SQLite et PostgreSQL jetables. Les appels historiques de `0071`
gardent `permit_id=NULL` : aucun permis fictif n'est attribué. Vérifier ensuite
le head et les tables avec `preflight`.

## Compte Apollo, crédits et coût

Les [tarifs de crédit API Apollo](https://docs.apollo.io/docs/api-pricing)
indiquent les unités de crédit par opération, notamment une recherche
d'organisations facturée par page. La phase A peut donc coûter des crédits,
même sans enrichissement. Le tarif **monétaire** CHF/crédit du plan n'est pas
publié comme valeur universelle ; le code n'en invente aucune. L'opérateur
doit fournir un fichier de prix daté et référencé : `currency=CHF`,
`price_per_credit`, `verified_at`, `source_type`, `source_reference`,
`plan_name`, `verified_by_reference`, crédits maximum par recherche
d'organisation, enrichissement d'organisation, recherche de personnes et
enrichissement de personne, solde daté, limites de taux par opération et
`rate_limit_reference`. Le champ obligatoire `credit_pools_by_operation`
associe `ORG_SEARCH`, `ORG_ENRICH`, `PEOPLE_SEARCH` et `PERSON_ENRICH` à la
catégorie de crédit réellement débitée par le plan (`lead_credit`,
`export_credit`, etc.). Le solde du fichier est le minimum attesté sur ces
catégories ; la sonde gratuite vérifie ensuite chaque catégorie séparément
et le préflight refuse une catégorie absente ou insuffisante. Cette
correspondance doit être attestée par l'opérateur : la documentation générale
Apollo ne garantit pas une catégorie identique pour tous les plans. La valeur
doit correspondre au plan du compte. Les
coûts variables ou en cascade doivent être plafonnés à leur pire cas ou
désactivés ; la cascade n'est pas utilisée par ce pipeline.

Les endpoints Apollo [credit usage stats](https://docs.apollo.io/reference/view-credit-usage-stats)
et [API usage stats](https://docs.apollo.io/reference/view-api-usage-stats)
sont officiellement à **0 crédit**. Le préflight peut les consulter, avec
`auth/health`, uniquement si l'opérateur ajoute `--probe-apollo-free`.
L'[authentification Apollo](https://docs.apollo.io/docs/test-api-key) exige
`healthy=true` et `is_logged_in=true` ; un simple HTTP 200 ne suffit pas.
Le code de cette PR ne les a pas appelés. Le solde `lead_credit` n'est pas
additionné aux autres pools d'un plan unifié. Une réponse 401/403, un solde
indisponible, une limite de taux non prouvée ou un prix périmé bloquent
l'exécution. La clé dédiée `MILOMAIL_CENSUS_APOLLO_API_KEY` est injectée par
le gestionnaire de secrets ; sa valeur n'apparaît jamais dans le rapport.
Le point d'accès Apollo est l'origine fixe `https://api.apollo.io` des
adaptateurs Kivou ; il n'est pas remplaçable par une URL arbitraire.

Les variables existantes `MILOMAIL_CENSUS_*` restent désactivées et tous les
plafonds globaux restent à zéro par défaut. Le préflight compare crédits,
prix CHF/crédit, coût maximal et limites de taux. La consommation effective
est rapprochée par `reconcile-usage` selon le runbook du census. Une réserve
ambiguë reste en revue : on ne la rejoue ni ne remet son coût à zéro.

## Préflight, permis et deux phases

Après la migration de la base autorisée, préparer les partitions, puis
inspecter le rapport :

```bash
uv run milomail-census plan --program-config <programme-validé.json> \
  --database-authorization <autorisation-base.json>
uv run milomail-census preflight --census-id <id> \
  --database-authorization <autorisation-base.json> \
  --pricing <prix-apollo.json> \
  --probe-official-source --probe-apollo-free
```

Sans les deux options `--probe-*`, aucun appel réseau n'est fait et les
contrôles sont marqués `NOT_PROBED`. Le résultat sépare `technically_ready`
de `execution_authorized`, et indique le SHA, la version d'application, la
révision Alembic, la base expurgée, le programme SHADOW, la politique, les
partitions, les plafonds, le solde, le pire coût, les réservations, le prix,
les erreurs et `instantly_mutation_allowed=false`. La base doit avoir le
programme Milo Mail désactivé, des plafonds **d'envoi** à zéro, le ruleset
`MILOMAIL_GMAIL_AUDIT_B2B` et un registre de suppression lisible. Aucun
credential Instantly n'est demandé. Un préflight réussi ne crée pas de permis.

Un responsable délivrera plus tard un fichier de permis hors dépôt contenant
`permit_id`, `census_id`, `program_key=milomail`, `phase`, `environment`,
`database_id`, `country=FR`, `allowed_partitions`, `max_pages`,
`max_candidates`, `max_enrichments`, `max_credits`, `max_cost_chf`,
`price_chf_per_credit`, `pricing_reference`, `configuration_hash` fourni par
le préflight, `issued_by_reference`, `issued_at`, `valid_from`, `expires_at`
et `status=ACTIVE`. Le permis `COVERAGE` a `max_enrichments=0`. Le permis
`ENRICHMENT` a `max_pages=0`. Les recherches de personnes de la phase A
utilisent le tarif de crédit vérifié pour cette opération (zéro uniquement
si le plan le confirme). Les partitions autorisées et tous les budgets
sont bornés. Changer les filtres, la configuration du programme, les plafonds
ou le prix, ou encore les plafonds et réglages de la source officielle,
modifie le hash et invalide le permis. Les soldes de crédit mis à
jour n'invalident pas le hash, mais doivent rester suffisants. Aucun permis
n'est créé dans cette mission.

```bash
uv run milomail-census issue-permit --permit <permis-approuvé.json> \
  --database-authorization <autorisation-base.json> --pricing <prix-apollo.json>
uv run milomail-census preflight --census-id <id> --permit-id <id-permis> \
  --database-authorization <autorisation-base.json> --pricing <prix-apollo.json> \
  --probe-official-source --probe-apollo-free
```

La phase A utilise la recherche d'organisations puis la recherche de personnes
filtrées par rôle, sans révélation d'adresse. Elle mesure couverture,
recouvrements et contacts candidats déclarés par Apollo, sans
enrichissement ni vérification d'adresse. Elle nécessite son propre permis,
car les pages de recherche coûtent des crédits. La phase B, avec un autre
permis, traite les seuls candidats persistés, en lots plafonnés : entreprise,
source officielle, MX, rôle, adresse, suppression, score et décision. Elle
ne relance pas les pages Apollo. Un `resume` reprend le curseur et les
réservations du même recensement ; un résultat incertain demande une revue.

```bash
uv run milomail-census run --census-id <id> --phase COVERAGE \
  --program-config <programme-validé.json> --permit-id <permis-a> \
  --database-authorization <autorisation-base.json> --pricing <prix-apollo.json> \
  --probe-official-source --probe-apollo-free --authorize-paid-apollo
uv run milomail-census resume --census-id <id> --phase ENRICHMENT \
  --program-config <programme-validé.json> --permit-id <permis-b> \
  --database-authorization <autorisation-base.json> --pricing <prix-apollo.json> \
  --probe-official-source --probe-apollo-free --authorize-paid-apollo
```

Le coût marginal d'une opération est réservé dans la même transaction que
le plafond du permis et celui du census. Un second passage sur une page déjà
terminée utilise le cache. Une réservation sans résultat ne peut pas être
rejouée sans revue. La phase B peut s'arrêter après un petit lot, sans
enrichir toute la couverture. Il faut conserver les fichiers d'autorisation,
de prix et de permis à disposition des opérateurs autorisés pour `resume`.

## Arrêt, revue et limites commerciales

Pour arrêter, révoquer le permis actif avec `revoke-permit` (autorisation de
base requise), mettre `MILOMAIL_CENSUS_ENABLED=false`, retirer la clé Apollo
dédiée et arrêter le processus. Aucune suppression de prospect ou de ligne
de coût n'est nécessaire. Réconcilier les réservations avec le relevé Apollo
avant toute nouvelle autorisation ; ne jamais considérer un appel ambigu
comme gratuit. `purge-cache` nettoie les réponses Apollo mises en cache selon le
runbook du census, sans effacer les décisions ni la preuve officielle minimale.

Le nombre de 15 000–50 000 adresses demeure une **hypothèse non mesurée**.
Un volume Apollo brut n'est pas un volume d'adresses envoyables. Aucun
résultat commercial réel n'existe avant une phase B autorisée et mesurée.
`SEND` dans le census signifie « théoriquement éligible en SHADOW » et
**jamais** « e-mail envoyé ». Instantly reste inaccessible au processus.
