# SPEC-020 — Supplier Discovery + Apollo

Date : 2026-08-20

Branche : `feat/spec020-supplier-discovery-apollo`

Base `main` : `0718550f4c42a419b3cac87a9ad1b98474a0de95`

Statut : implémenté, validé localement et validé par GitHub Actions.

## Résultat

SPEC-020 fournit le premier consommateur de fournisseur externe derrière la
Policy Gateway, sans personne, contact, campagne ni outbound :

```text
opportunité de marché public
  -> seed Kivou public
  -> SupplierSearchProfile supplier-search-v1
  -> évaluation Policy Gateway fraîche
  -> run STARTED détenu par un seul processus
  -> Apollo Organization Search borné
  -> fournisseur Kivou
  -> AcquisitionOpportunity(seed × fournisseur)
```

Apollo n'a pas été appelé en direct. Tous les tests utilisent un provider
déterministe hors ligne et des identifiants factices.

## Seed public et confidentialité

La référence d'acquisition est exactement :

```text
signal_ref = procurement-opportunity:<opportunity_key>
```

Le nom historique `signal_ref` de SPEC-018 désigne ici le seed public stable,
pas un `materialized_signal`, un `TargetICP` ou un signal appartenant à un
client. Le résolveur lit uniquement `opportunity_representation`,
`contract_award` et `source_event`, puis utilise les moteurs existants
`ContractUnderstandingEngine` et `NeedGraphEngine` sans les modifier.

La sélection de représentation est déterministe : complétude publique
décroissante, publication la plus récente, puis `award_key` lexical. Le profil
persisté ne contient pas les objets Python Understanding/Need Graph, seulement
les champs canoniques bornés utiles à l'audit.

Des tests d'architecture interdisent toute dépendance du package envers
TargetICP, feedback, billing, entitlements, matching client ou
`materialized_signal`.

## Policy Gateway

`TargetScope.SIGNAL` autorise `discover_suppliers` avant l'existence d'une
AcquisitionOpportunity :

```text
target_ref = procurement-opportunity:<opportunity_key>
acquisition_opportunity_id = NULL
```

Le registre callable-free déclare :

- risque `PREPARATORY` ;
- preuves `PUBLIC_OPPORTUNITY`, `PUBLIC_EVIDENCE`,
  `SUPPLIER_SEARCH_PROFILE` ;
- budget coût actif ;
- quota provider actif ;
- control plane provider requis ;
- contrôles mailbox/send-window inactifs ;
- conformité outbound inactive.

`OperationalReadiness.provider_quota` vient d'un état Kivou fourni à la
Policy Gateway. Aucun appel Apollo `usage_stats` n'est effectué avant
autorisation. `UNKNOWN` échoue fermé.

La course concurrente SPEC-019 sur un même `evaluation_id` est fermée avec un
insert dialectal `ON CONFLICT DO NOTHING`. Des entrées sémantiquement
identiques rejouent la décision persistée ; des sémantiques différentes
déclenchent toujours `PolicyEvaluationIdempotencyConflict`. L'audit double
opportunity-scoped de SPEC-019 reste atomique.

L'API publique du service reçoit `opportunity_key` et la configuration Kivou,
pas un profil Apollo préconstruit. Le service résout lui-même les faits
persistés et reconstruit le profil ; un appelant ne peut donc fabriquer une
référence au bon préfixe tout en contournant la provenance publique.

En SHADOW ou lorsque `decision.executable == false`, le service ne crée aucun
run et n'appelle jamais le provider.

## SupplierSearchProfile

Version : `supplier-search-v1`.

Le mapping des catégories Need Graph vers les tags est fixe, déterministe et
Kivou-owned. Les filtres supportés sont bornés :

- `organization_locations` ;
- `organization_not_locations` ;
- `organization_num_employees_ranges` ;
- tags de mots-clés ;
- domaines exclus ;
- `max_pages` de 1 à 5, défaut 1 ;
- `per_page` de 1 à 100, défaut 100 ;
- plafond candidats de 1 à 500 ;
- seuil `SEARCH_TOO_BROAD`, défaut Kivou 10 000.

Le seuil fait partie de l'empreinte du profil. Hermes ne peut fournir ni JSON
Apollo brut, ni filtre arbitraire, ni endpoint, ni URL d'exécution.

Un résultat Need Graph sans besoin (`needs=()`) est une conclusion valide mais
non actionnable : `SupplierSearchNotActionable(reason=no_supplier_need)` est
levée avant Policy Gateway, avant création du run et avant tout appel Apollo.
La frontière service contrôle à la fois les catégories et les tags dérivés ; un
profil injecté sans catégorie ou sans sélecteur positif ne peut donc pas
transformer l'absence de besoin en recherche large. Aucun mot-clé de repli
n'est inventé.

## Apollo Organization Search

Seul cet endpoint est implémenté :

```text
POST https://api.apollo.io/api/v1/mixed_companies/search
```

Paramètres exacts émis :

```text
organization_num_employees_ranges[]
organization_locations[]
organization_not_locations[]
q_organization_keyword_tags[]
page
per_page
```

Aucun endpoint People, enrichissement d'organisation, contact, email, téléphone
ou `usage_stats` n'existe dans ce chemin. `partial_results_only` est
optionnel : son absence est valide ; sa présence à `true` entraîne une
conclusion conservatrice `SEARCH_TOO_BROAD`.

Le client lit la réponse en streaming avec une limite dure de 1 MiB, impose un
timeout fini et des pages de 100 organisations maximum. Il rejette aussi une
pagination incohérente avec la requête. Les erreurs sont typées :
`unauthorized`, `forbidden`, `rate_limited`, `provider_limit`,
`timeout`, `server_error`, `client_error`, `network_error` et
`malformed_response`. Un 429 ne produit aucune boucle de retry et conserve
uniquement un `Retry-After` autoritaire.

Une racine JSON, une collection ou une pagination invalide fait échouer la
page. Un changement de total/pages/limitation entre deux pages termine le run
en échec partiel plutôt que d'accepter une couverture faussement complète. Une
organisation individuelle sans ID/nom utilisable, ou avec
URL/domaine/localisation/normalisation invalide, est rejetée avec un reason
code stable sans perdre les autres organisations valides.

## Closeout R1 — complétude provider et crédits sans gaspillage

La complétude d'une recherche est maintenant explicite :

- `total_entries == 0` avec page vide est un succès vide valide ;
- une page finale normale non vide est un succès ;
- atteindre `candidate_cap` ou `max_pages` après des résultats valides est une
  terminaison bornée normale ;
- toute page vide sans rejet qui annonce `total_entries > 0` est une réponse
  incohérente, y compris `total_pages == 0` ; elle termine en
  `malformed_response / unexpected_empty_page` ;
- sans candidat déjà commit, le run est `FAILED` ; après des pages sûres déjà
  commit, il est `PARTIAL` ; il n'est jamais `SUCCESS`.

Le garde zéro-crédit refuse avant même l'évaluation Policy Gateway tout seed
dont le Need Graph ne contient aucun besoin, ainsi que tout profil sans
catégorie ou sans tag positif dérivé. Les tests confirment alors zéro appel
provider, zéro `supplier_discovery_run`, zéro fournisseur et zéro
AcquisitionOpportunity.

La propriété de run couvre désormais les deux identités. Un même
`policy_evaluation_id` rejoue son run existant. Un même `discovery_run_id` avec
la même évaluation et les mêmes sémantiques rejoue aussi le run. Le même
`discovery_run_id` présenté avec une autre évaluation produit
`DiscoveryRunIdentityConflict`, jamais une `IntegrityError` brute et jamais un
second appel Apollo.

Les horloges sont séparées par une horloge de service injectable et timezone
aware : `evaluated_at` reste l'heure de policy, `started_at` est capturé avant
l'insert `STARTED`, `provider_observed_at` est capturé pour chaque page et
`completed_at` au passage terminal. Une fixture déterministe prouve :

```text
evaluated_at < started_at <= provider_observed_at <= completed_at
```

## Identité fournisseur

`supplier_ref` est un identifiant Kivou immuable dérivé d'un fingerprint
versionné du namespace provider et de l'identifiant organisation Apollo.
L'identifiant Apollo est une provenance, jamais l'identité business d'une
AcquisitionOpportunity.

Règles prouvées :

- même provider + même ID -> même `supplier_ref`, y compris en course
  concurrente ;
- domaine absent -> aucun domaine inventé ;
- IDs provider différents sur un même domaine -> aucune fusion ;
- le conflit de domaine marque symétriquement toutes les lignes avec
  `DOMAIN_CONFLICT` et le même fingerprint de groupe ;
- une observation plus ancienne ne remplace jamais les métadonnées récentes ;
- une observation égale ou plus récente peut mettre à jour les champs bornés,
  sans changer `supplier_ref`.

Les mises à jour concurrentes utilisent un compare-and-set SQL sur
`provider_observed_at`. PostgreSQL sérialise les réconciliations de domaine avec
un advisory lock transactionnel déterministe pris dans l'ordre lexical ;
SQLite conserve sa sérialisation native. Le retrait ultérieur d'un domaine
efface aussi proprement un ancien conflit pour toutes les lignes concernées.

Données Apollo persistées : identifiant organisation provider, nom normalisé,
domaine/website/LinkedIn entreprise facultatifs, pays/localisation/industrie
bornés, observation, fingerprint et statut d'identité.

Délibérément non persistés : réponse brute, headers, secret, rang/page comme
identité, personnes, emails, téléphones, LinkedIn personnel, historique
provider complet, intent/funding/jobs et objets SDK.

## Exécution, crédits et échecs partiels

Une évaluation de policy possède au maximum un run grâce à
`UNIQUE(policy_evaluation_id)`. Le run `STARTED` est inséré avant la requête
HTTP ; seul le propriétaire de cet insert appelle Apollo. Une nouvelle
tentative nécessite un nouvel `evaluation_id`, donc une évaluation fraîche.

Les états sont `STARTED`, `SUCCESS`, `PARTIAL`, `FAILED` et
`SEARCH_TOO_BROAD`. Le défaut consomme au plus une page planifiée. Les unités
de crédit planifiées et les pages tentées sont stockées séparément du budget
monétaire Kivou ; aucun coût CHF/EUR n'est inventé. Les crédits observés restent
NULL sauf donnée autoritaire Apollo.

Si une page ultérieure échoue, les fournisseurs/opportunités déjà commit restent
durables, le run devient `PARTIAL`, et un replay ultérieur est absorbé par les
identités stables. Un 401/429 n'est jamais présenté comme un crédit
nécessairement consommé.

## AcquisitionOpportunity et atomicité

L'identité d'acquisition dépend uniquement du couple :

```text
procurement-opportunity:<opportunity_key> × supplier_ref
```

Elle exclut le nom, le rang Apollo, la page et les métadonnées mutables. Le
premier passage crée atomiquement, dans une transaction bornée par candidat :

1. le fournisseur/upsert et les conflits de domaine ;
2. l'AcquisitionOpportunity en `DISCOVERED` avec `supplier_ref` ;
3. un unique `NEXT_ACTION_SET(find_decision_makers)`.

`contact_ref` et `campaign_ref` restent NULL. Un ajout minimal
connection-aware à `AcquisitionStore` préserve atomicité, stream sequence,
idempotence et concurrence SPEC-018.

Une rediscovery d'une opportunité déjà avancée ne modifie ni état, ni
`next_action`, ni `stream_version`. Aucun événement n'est ajouté juste parce
qu'Apollo a retrouvé le fournisseur.

## Migration 0009

Graphe linéaire vérifié :

```text
0008_policy_gateway
  -> 0009_supplier_discovery
```

L'identifiant a 23 caractères, donc respecte la limite Alembic de 32. Un seul
head existe.

La migration ajoute exactement deux tables :

- `acquisition_supplier` : identité Kivou et métadonnées provider sûres ;
- `supplier_discovery_run` : audit opérationnel borné, FK RESTRICT et UNIQUE
  vers `policy_evaluation.evaluation_id`.

Elle n'ajoute ni personne/contact, ni provider générique, ni Event Bus, queue,
worker ou DLQ. Les tests couvrent DB fraîche vers head, upgrade depuis 0008,
contraintes/indexes et SQL PostgreSQL offline.

## Tests TDD et performance

Les tests déterministes couvrent notamment :

- scope SIGNAL, preuve/quota/control-plane et SHADOW zéro provider ;
- course d'`evaluation_id` sans IntegrityError brut ;
- un run par policy evaluation et ownership concurrent ;
- profil stable, filtres refusés et seuil fingerprinté ;
- schéma officiel Apollo, page vide, item/page malformed, 401/403/429/5xx,
  timeout/network, taille, non-fuite de clé ;
- replay fournisseur, collision domaine symétrique, observation stale ;
- transaction candidat et rollback complet ;
- seed public réel depuis fixture ingestion et absence de dépendance client ;
- création/replay/no-rewind acquisition ;
- succès partiel, rate limit, compteurs de rejet et absence d'outbound ;
- complétude page vide, zéro-besoin/zéro-crédit, collision de run typée et
  horloges d'audit distinctes.

Mesure diagnostique locale, sans SLA :

```text
fixtures organisations : 100
fournisseurs persistés  : 100
opportunités créées     : 100
temps mural             : 1.081371 s
```

## Régression complète locale

```text
backend pytest : 3055 passed
skipped        : 0
ruff           : PASS
git diff check : PASS

frontend tests : 84 passed
build          : PASS
typecheck      : PASS
lint           : PASS
```

Aucun test n'utilise Internet ou un secret Apollo.

## Sécurité et non-objectifs

Confirmé absent : People API, Organization Enrichment, Apollo live, email,
SMTP, Instantly, Stripe, shell, exécuteur générique, SEND/NO_SEND, décision
commerciale, personnalisation, campagne, contact, PII, worker, scheduler, VPS et
déploiement. Le Signal Engine, Need Graph, matching client, billing, feed et
frontend ne sont pas modifiés.

Le scan des changements ne trouve aucune clé réelle, mot de passe, clé privée,
secret Stripe/SMTP/GitHub ou credential Apollo.

## Fichiers modifiés

- `src/signals/supplier_discovery/` : contrats, profil, seed, client Apollo,
  protocole, identité, store et service ;
- `src/signals/policy/` : scope SIGNAL, métadonnée quota provider et
  idempotence concurrente ;
- `src/signals/acquisition/store.py` : API transaction-aware minimale ;
- `src/signals/persistence/schema.py` ;
- migration `0009_supplier_discovery` ;
- tests SPEC-020 et attentes de head migration ;
- rapports design et final SPEC-020.

Diff du closeout R1 exécutable
`d86fc46c27db89b60cb67e073d21fe9aa5d8b7d6` :

```text
7 files changed, 424 insertions(+), 20 deletions(-)
git status --porcelain : vide
```

Aucune modification `ops/` ou frontend n'est incluse. Le commit de closeout
qui suit la tête exécutable ne modifie que ce rapport.

## GitHub CI

```text
PR             : #13 (DRAFT, base main)
executable SHA : d86fc46c27db89b60cb67e073d21fe9aa5d8b7d6
CI run ID      : 32352219065
backend        : PASS — 3055 passed, 0 skipped, Ruff PASS
frontend       : PASS — 84 passed, build/typecheck/lint PASS
```

## Verdict

```text
SUPPLIER DISCOVERY READY
```
