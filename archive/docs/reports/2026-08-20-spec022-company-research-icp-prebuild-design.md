# SPEC-022 — Company Research + Acquisition Prospect Prebuild — Design

Date : 2026-08-20

Branche : `feat/spec022-company-research-icp-prebuild`

Base autoritaire : `341011a51d94ce298c08add0f905a85a78121773`

Alembic head : `0010_contact_discovery`

Statut : design uniquement — aucune implémentation, migration ou requête Apollo

## 1. Objectif et périmètre

SPEC-022 prépare des faits d'entreprise minimisés et des features Kivou
déterministes pour le futur Decision Engine :

```text
AcquisitionOpportunity
  state = ENRICHING
  supplier_ref connu
  contact_ref connu
  next_action = enrich_company
        -> CompanyResearchProfile Kivou
        -> Policy Gateway évaluée à neuf
        -> company_research_run STARTED durable
        -> GET Apollo /organizations/{id}
        -> observation entreprise bornée
        -> AcquisitionProspectPrebuild déterministe
        -> acquisition_company_profile durable
        -> ENRICHING -> READY_FOR_DECISION
        -> next_action = evaluate_opportunity
```

Le composant ne prend aucune décision commerciale. Il ne produit ni score de
fit/lead/outreach, ni `SEND`, `NO_SEND`, `HOLD` ou `REVIEW`, ne crée aucune
campagne, n'envoie rien et ne modifie ni le Need Graph, ni le Matching Engine,
ni le produit client. Aucun LLM, crawler, recherche web générique ou second
endpoint Apollo n'est introduit.

## 2. Entry gate vérifié

Le dépôt autoritaire a été synchronisé avant la création de la branche :

```text
HEAD        341011a51d94ce298c08add0f905a85a78121773
origin/main 341011a51d94ce298c08add0f905a85a78121773
PR #16      MERGED
merge SHA   341011a51d94ce298c08add0f905a85a78121773
Alembic     0010_contact_discovery
```

`main` contient les packages `signals.supplier_discovery` et
`signals.contact_discovery`. Le SHA attendu dans la consigne était le SHA
pré-merge de SPEC-020 ; le squash de SPEC-021 a produit le nouveau SHA
autoritaire ci-dessus.

## 3. Audit du code autoritaire

### 3.1 Acquisition Opportunity

`AcquisitionOpportunity` est la projection Kivou du workflow d'acquisition,
distincte de l'opportunité de marché public. Après SPEC-021, le chemin normal
est :

```text
signal_ref   = procurement-opportunity:<opportunity_key>
supplier_ref = acquisition_supplier.supplier_ref
contact_ref  = acquisition_contact.contact_ref
campaign_ref = NULL
state        = ENRICHING
next_action  = enrich_company
```

Le reducer `acquisition-state-v1` autorise déjà
`ENRICHING -> READY_FOR_DECISION`, et `NEXT_ACTION_SET` accepte déjà
`evaluate_opportunity`. `AcquisitionStore.append_in_transaction()` permet
d'enchaîner ces mutations dans une transaction appartenant au service, avec
idempotence, optimistic concurrency, event/projection atomicity et replay.

### 3.2 Identité fournisseur

`acquisition_supplier` est l'autorité Kivou de l'identité entreprise. Elle
contient :

```text
supplier_ref
provider = apollo
provider_organization_id
display_name / normalized_name
primary_domain / website_url
country_code / location / industry
identity_status
provider_observed_at / source_fingerprint
```

SPEC-022 ne remplace jamais `supplier_ref`, ne réconcilie pas par nom ou
domaine et ne met pas à jour cette ligne. L'observation de recherche ultérieure
est conservée séparément pour distinguer la provenance de recherche SPEC-020
de la provenance d'enrichissement SPEC-022.

### 3.3 Contact sélectionné

`acquisition_contact` contient une identité emploi Kivou et un email
professionnel `PROVIDER_VERIFIED`. SPEC-022 n'a besoin que de :

```text
contact_ref
supplier_ref
verification_state
verification_provider
provider_email_status
role_profile_version
role_tier
```

Le nom et l'email ne sont ni lus pour construire le profil entreprise, ni
dupliqués dans les nouvelles tables.

### 3.4 Signal public et Need Graph

Le `signal_ref` acquisition est exactement :

```text
procurement-opportunity:<opportunity_key>
```

Il référence les faits publics persistés via `opportunity_key`. Le resolver
SPEC-020 reconstruit une seed à partir de `source_event`, `contract_award` et
`opportunity_representation`, sans `materialized_signal` client.

Le code actuel ne relie toutefois pas durablement une
`AcquisitionOpportunity` au `supplier_discovery_run` qui a accepté son
supplier : la création ne persiste pas le run en `correlation_id` et il
n'existe pas de table de relation supplier/run. SPEC-022 ne devine donc pas
les `need_categories` d'un run par association ambiguë. Le prebuild persiste
le `signal_ref` public, mais pas un faux snapshot du Need Graph. SPEC-023 pourra
résoudre le contexte public par ce ref ou un futur contrat explicitement
versionné.

### 3.5 Policy Gateway

`enrich_company` existe avec `TargetScope.OPPORTUNITY`, `PREPARATORY`,
`required_evidence=(SUPPLIER,)` et `uses_budget=true`. Le futur changement
minimal est :

```text
risk_class              PREPARATORY
target_scope            OPPORTUNITY
required_evidence       SUPPLIER, VERIFIED_CONTACT, COMPANY_RESEARCH_PROFILE
uses_budget             true
uses_provider_quota     true
requires_control_plane  true
uses_send_controls      false
requires_compliance     false
```

La mailbox et la send window sont hors sujet. La configuration de quota
fournisseur reste une entrée Kivou autoritaire ; aucun appel Apollo préalable
n'est autorisé pour la remplir.

### 3.6 Frontière client

Le package proposé n'importe ni `TargetICP`, ni matching client, ni feedback,
ni billing/entitlements, ni `materialized_signal`. Cette séparation sera
contrôlée par un test d'architecture AST/import. Le terme « ICP Prebuild » de
la roadmap est remplacé dans le code par `AcquisitionProspectPrebuild`.

## 4. Options de conception évaluées

### Option A — exact-ID, profil opportunity-scoped, deux tables — retenue

Une requête Apollo exacte par run produit une observation minimisée et un
prebuild opportunity-scoped. Deux tables isolent la projection décisionnelle
de l'audit d'exécution. Cette option conserve l'identité SPEC-020, coûte au
plus un crédit et suit les transactions SPEC-020/021.

### Option B — `/organizations/enrich` par nom/domaine — rejetée

Cette option rematcherait une identité déjà connue, pourrait retourner une
autre organisation et ne fournirait pas d'avantage nécessaire au MVP. Appeler
les deux endpoints doublerait le coût et créerait deux observations
potentiellement incompatibles.

### Option C — cache fournisseur partagé entre opportunités — différée

Une observation supplier-scoped pourrait économiser des crédits, mais exige
une politique de fraîcheur, de réutilisation et d'invalidation qui n'existe pas
encore. Le MVP privilégie une vérité opportunity-scoped directement
consommable par SPEC-023. La duplication sera mesurée avant une optimisation.

## 5. Baseline Apollo officielle vérifiée

Sources officielles consultées le 2026-08-20 :

- [Get Complete Organization Info](https://docs.apollo.io/reference/get-complete-organization-info) :
  `GET https://api.apollo.io/api/v1/organizations/{id}`, Apollo ID en path,
  scope `organization_read`, 1 crédit par entreprise ;
- [OpenAPI Apollo](https://docs.apollo.io/openapi/apollo-rest-api.json) :
  exemple courant de la racine `organization` et réponses endpoint
  `200/401/403/422` ;
- [API Pricing and Credits](https://docs.apollo.io/docs/api-pricing) :
  `Get complete organization info` coûte 1 crédit par entreprise, avec la
  réserve que les plans legacy peuvent différer ;
- [Status Codes and Errors](https://docs.apollo.io/reference/status-codes) :
  sémantique générique des `401/403/404/422/429/500`.

L'OpenAPI actuelle expose dans l'exemple `200` notamment `organization.id`,
`name`, `website_url`, `primary_domain`, `industry`,
`estimated_num_employees`, `founded_year`, `keywords`, `country`,
`short_description` et `annual_revenue`, ainsi que beaucoup de champs que
Kivou rejettera par minimisation.

### 5.1 Endpoint retenu

```text
GET /api/v1/organizations/{provider_organization_id}
```

L'identifiant provient de l'Organization Search SPEC-020. Le client ne prend
ni URL arbitraire, ni endpoint arbitraire, ni identifiant fourni par Hermes.
Il n'appelle jamais `/organizations/enrich`, bulk enrichment, job postings,
People API ou Account API.

### 5.2 Suffisance de l'endpoint

Les champs documentés suffisent au MVP pour établir une observation corporate,
un size band, une complétude et un contexte de recherche pour SPEC-023. Aucun
champ critique ne justifie une deuxième requête. `Organization Enrichment`
n'est donc pas nécessaire.

### 5.3 Absence de record courant

La référence endpoint documente `422` comme ID invalide, mais ne documente pas
un sentinel métier distinct « organisation anciennement valide désormais
absente ». La page générique indique qu'un `404` peut signifier soit record
inexistant, soit record inaccessible avec les credentials. Ces signaux ne
permettent pas de distinguer de manière fiable l'absence de record d'un défaut
d'accès.

Décision fail-closed proposée :

- `200` avec objet exact et partiel : prebuild `LIMITED` possible ;
- `401`, `403`, `404` observé mais non spécifié pour cet endpoint, `422`, `429`,
  timeout, réseau ou `5xx` : run `FAILED` ;
- aucune progression `READY_FOR_DECISION` sur un non-`200` ;
- aucune fabrication depuis la seule ligne SPEC-020 pour masquer un échec.

Un futur smoke explicitement autorisé pourra documenter un sentinel stable.
Jusqu'alors, `NO_CURRENT_PROVIDER_RECORD` reste réservé et non produit.

## 6. Contrats et package proposés

Package futur : `signals.company_research`.

```text
contracts.py  contrats bornés, enums, erreurs
profile.py    CompanyResearchProfile + empreinte
apollo.py     client HTTP exact-ID et parser strict
provider.py   protocole étroit CompanyResearchProvider
prebuild.py   normalisation et AcquisitionProspectPrebuild
store.py      profil courant, run, CAS, transactions
service.py    actionnabilité, policy, ownership, provider, finalisation
```

Le provider protocol reste étroit :

```text
fetch_organization(profile, observed_at) -> ApolloOrganizationObservation
```

Il ne constitue ni SDK Apollo générique, ni système multi-provider.

## 7. `CompanyResearchProfile`

Version initiale : `company-research-v1`.

Le profil contient uniquement la sémantique de requête/provider :

```text
profile_version
provider = apollo
provider_organization_id
endpoint_kind = exact_organization_id
response_contract_version = apollo-organization-info-v1
allowed_provider_fields[]
max_response_bytes = 1_048_576
max_keywords = 32
max_keyword_length = 128
max_description_length = 2_000
normalization_version = company-normalization-v1
profile_fingerprint
```

Les bindings `acquisition_opportunity_id`, `supplier_ref` et `contact_ref`
entrent dans les arguments canoniques de la `PolicyRequest` et dans le run,
mais pas dans l'empreinte de la requête provider. Deux opportunités pour la
même organisation ont donc la même sémantique HTTP sans partager une
autorisation ou un run.

`expected_opportunity_version`, `evaluation_id`, `run_id`, timestamps et
`correlation_id` ne figurent jamais dans `profile_fingerprint`.

L'empreinte SHA-256 couvre tous les champs ci-dessus. Tout changement
d'allowlist, limite ou normalisation qui peut modifier le résultat persistant
exige une nouvelle version/empreinte.

## 8. Contrat Apollo et allowlist

### 8.1 Champs persistés

L'observation provider conserve exactement :

```text
provider = apollo
provider_organization_id      <- organization.id, exact match obligatoire
provider_company_name         <- organization.name
provider_primary_domain       <- organization.primary_domain, nullable
provider_website_url          <- organization.website_url, nullable
provider_country              <- organization.country, nullable, texte provider
provider_industry             <- organization.industry, nullable
provider_employee_count       <- organization.estimated_num_employees, nullable
provider_founded_year         <- organization.founded_year, nullable
provider_short_description    <- organization.short_description, nullable, 2 000 max
provider_keywords             <- organization.keywords, max 32 × 128
provider_observed_at
provider_source_fingerprint
```

Apollo ne documente pas `country` comme ISO-3166 dans l'exemple. SPEC-022 ne
fabrique donc pas `country_code`; il conserve un texte provider borné. De même,
`annual_revenue` est présent sans contrat de devise au niveau de
l'organisation. SPEC-022 v1 le rejette plutôt que de créer une somme monétaire
ambiguë. Un futur champ revenu devra être explicitement typé avec une devise
autoritaire.

### 8.2 Champs délibérément écartés

Sont ignorés avant persistance et exclus des empreintes métier :

```text
phone/account phone
street/raw address, postal code, city/state détaillés
LinkedIn/Twitter/Facebook URLs et UIDs
logo/photo
account objet et custom fields
funding rounds, investisseurs, total funding
technology lists
suborganizations, hierarchy, org chart et people IDs
intent signals et scores Apollo
retail counts, Alexa ranking
generic insights
raw payload et headers
```

Apollo intent ou insight ne devient jamais un signal Kivou confirmé.

### 8.3 Validation

Le parser exige :

- JSON et racine objet ;
- clé `organization` contenant un objet ;
- `organization.id` borné et égal à l'ID demandé ;
- `organization.name` non vide et borné ;
- taille HTTP au plus 1 MiB ;
- URLs HTTP(S) syntaxiquement valides, jamais fetchées ;
- domaine normalisé valide s'il est présent ;
- employé entier entre 0 et 10 000 000 ;
- année fondée entière entre 1000 et l'année d'observation + 1 ;
- tableaux/strings bornés, sans valeurs non finies.

Un ID divergent produit `provider_identity_mismatch`. Une racine invalide, un
type impossible ou une valeur numérique hors domaine produit
`malformed_response`. L'absence d'un champ optionnel reste valide et devient
`missing_fields`.

## 9. `AcquisitionProspectPrebuild`

Code name : `AcquisitionProspectPrebuild`.

Projection SQL : `acquisition_company_profile`.

Version initiale : `acquisition-prospect-prebuild-v1`.

Le prebuild est un snapshot opportunity-scoped, déterministe et prêt à être
lu par SPEC-023. Il n'est ni un `TargetICP`, ni un résultat du Matching Engine,
ni une décision. Il contient :

```text
acquisition_opportunity_id
signal_ref
supplier_ref
contact_ref

supplier_identity_status
provider / provider_organization_id
provider facts allowlistés

provider_verified_contact_present = true (dérivé, non dupliqué en SQL)
contact_role_profile_version
contact_role_tier

provider_research_status
research_completeness
missing_fields[]

size_band
prebuild_version
prebuild_fingerprint
```

Le booléen de contact vérifié est dérivé du FK `contact_ref` et de la
revalidation de `acquisition_contact`; il n'est pas stocké comme une colonne
redondante. Le prebuild ne contient jamais nom ou email du contact.

### 9.1 Size band Kivou

Mapping `company-size-v1`, callable-free et testé :

```text
employee_count absent -> UNKNOWN
0 .. 9                -> MICRO
10 .. 249             -> SMB
250 .. 999            -> MID_MARKET
>= 1 000              -> ENTERPRISE
```

`provider_employee_count` reste explicitement une observation Apollo ;
`size_band` est explicitement dérivé par Kivou. Le mapping ne modifie aucun
Need Graph ou score client.

### 9.2 Complétude

Vocabulaire :

```text
provider_research_status = CURRENT_PROVIDER_RECORD
research_completeness    = COMPLETE | LIMITED
```

Une réponse `200` exacte est `COMPLETE` si elle contient, outre ID/nom, un
domaine ou site, le pays, l'industrie et l'effectif. Sinon elle est `LIMITED`.
`founded_year`, description et keywords sont enrichissants mais non requis.
`missing_fields` est une liste triée et bornée de codes stables.

`LIMITED` ne signifie ni mauvais prospect ni `NO_SEND`. Cela indique seulement
que SPEC-023 doit décider avec moins de faits.

### 9.3 Empreinte prebuild

`prebuild_fingerprint` couvre :

- version du prebuild et `company-size-v1` ;
- opportunity/signal/supplier/contact refs ;
- `supplier_identity_status` ;
- toute l'observation provider persistée et son fingerprint ;
- rôle contact version/tier sans PII ;
- `provider_research_status`, complétude, missing fields et size band.

Il exclut run/evaluation/correlation IDs, timestamps d'audit générés, headers
HTTP et tout champ non retenu. Tout input futur de SPEC-023 devra faire partie
de cette empreinte.

## 10. Persistence et migration 0011

Migration recommandée : **OUI**.

```text
0010_contact_discovery
    ->
0011_company_research
```

`0011_company_research` contient 21 caractères, donc respecte la limite
Alembic de 32. Deux tables seulement sont nécessaires.

### 10.1 `acquisition_company_profile`

```text
acquisition_opportunity_id       PK, FK RESTRICT
supplier_ref                     FK acquisition_supplier RESTRICT
contact_ref                      FK acquisition_contact RESTRICT
signal_ref                       VARCHAR(256), NOT NULL

provider                         apollo
provider_organization_id         VARCHAR(128)
provider_observed_at             timestamptz
provider_source_fingerprint      CHAR/VARCHAR(64)

provider_company_name            TEXT
provider_primary_domain          VARCHAR(253), nullable
provider_website_url             TEXT, nullable
provider_country                 VARCHAR(128), nullable
provider_industry                VARCHAR(256), nullable
provider_employee_count          INTEGER, nullable
provider_founded_year            INTEGER, nullable
provider_short_description       TEXT, nullable
provider_keywords                JSON, NOT NULL, borné par contrat

supplier_identity_status         VARCHAR(32)
contact_role_profile_version     VARCHAR(64)
contact_role_tier                INTEGER
provider_research_status         VARCHAR(32)
research_completeness            VARCHAR(16)
missing_fields                   JSON, NOT NULL, borné
size_band                        VARCHAR(16)
prebuild_version                 VARCHAR(64)
prebuild_fingerprint             VARCHAR(64)
created_at                       timestamptz
updated_at                       timestamptz
```

Checks : provider Apollo, enums fixes, employee count non négatif et borné,
année fondée bornée, role tier 1..4, fingerprint SHA-256 shape. Indexes :
supplier et `(research_completeness, updated_at)`. Aucune colonne score,
decision, email ou téléphone.

### 10.2 `company_research_run`

```text
company_research_run_id          PK
acquisition_opportunity_id       FK RESTRICT
supplier_ref                     FK RESTRICT
contact_ref                      FK RESTRICT
policy_evaluation_id             FK policy_evaluation RESTRICT, UNIQUE

research_profile_version
research_profile_fingerprint
research_profile                 JSON borné
provider                         apollo
provider_endpoint_kind           exact_organization_id
provider_request_fingerprint
expected_post_policy_version     >= 2

planned_provider_credit_units    1
observed_provider_credit_units   nullable
provider_calls                   0..1

started_at
completed_at                     nullable
status                           STARTED | SUCCESS | LIMITED | FAILED
error_category                   nullable, code stable
error_detail                     nullable, 512 max, sans payload/secret
retry_after                      nullable
correlation_id
```

`acquisition_opportunity_id` localise directement le profil produit ; aucun
troisième FK « produced profile » n'est requis puisque le profil a ce même PK.
Indexes : `(acquisition_opportunity_id, started_at)` et `(status, started_at)`.

Les tables 0007–0010 ne peuvent pas représenter honnêtement l'observation
corporate, les inputs préparés pour SPEC-023, la propriété d'un appel provider
ou son coût. Une migration est donc nécessaire. Aucun cache, Event Bus, worker,
queue, historique provider ou table d'input client n'est créé.

## 11. Observation CAS

`acquisition_company_profile` suit la règle déterministe :

```text
incoming.provider_observed_at > stored.provider_observed_at
    -> remplace les champs mutables bornés

timestamps égaux + même provider_source_fingerprint
    -> replay exact / no-op

timestamps égaux + fingerprints différents
    -> CompanyResearchObservationConflict

incoming plus ancien
    -> aucun overwrite
```

Les refs opportunity/supplier/contact sont immuables pour cette projection.
Une divergence de binding est un conflit, jamais une mise à jour. Le
`provider_source_fingerprint` représente l'observation actuellement persistée.

## 12. Actionnabilité avant policy

Avant toute nouvelle évaluation :

```text
opportunity.state == ENRICHING
opportunity.supplier_ref != NULL
opportunity.contact_ref != NULL
opportunity.next_action == enrich_company
```

Le service charge ensuite supplier et contact et exige :

```text
supplier.provider == apollo
supplier.provider_organization_id présent
contact.contact_ref == opportunity.contact_ref
contact.supplier_ref == opportunity.supplier_ref
contact.verification_state == PROVIDER_VERIFIED
contact.verification_provider == apollo
contact.provider_email_status == verified
```

Toute divergence produit `CompanyResearchNotActionable` avant policy : zéro
run et zéro appel Apollo.

## 13. Policy Gateway et crash window

La `PolicyRequest` est opportunity-scoped :

```text
command                       enrich_company
target_ref                    acquisition-opportunity:<id>
acquisition_opportunity_id    <id>
expected_opportunity_version  V
canonical_arguments           bindings + CompanyResearchProfile canonique
action_fingerprint            SHA-256(arguments)
```

Le service n'accepte jamais un `PolicyDecision` entrant. Il applique cet ordre :

1. chercher un run par `authorization.evaluation_id`; s'il existe, valider
   tous ses bindings et le retourner sans policy/provider ;
2. si une `policy_evaluation` existe sans run, lever
   `CompanyResearchEvaluationRequiresFreshAttempt`, sans reconstituer la
   requête depuis `V+1` et sans réutiliser l'ancienne approbation ;
3. lire l'opportunité actuelle `V`, vérifier l'actionnabilité et construire le
   profil ;
4. appeler `PolicyGateway.evaluate_and_record()` ; son `POLICY_EVALUATED`
   avance `V -> V+1` ;
5. si `executable=false`, ne créer aucun run et ne joindre aucun provider ;
6. sinon tenter de posséder un run STARTED avec
   `expected_post_policy_version=V+1`.

En SHADOW, l'audit counterfactual est permis mais `executable=false` garantit
zéro appel Apollo. Quota `UNKNOWN`, control plane indisponible, budget ou policy
bloquante produisent également zéro réseau.

## 14. Ownership du run et consommation provider

`UNIQUE(policy_evaluation_id)` impose : une évaluation, au plus un run et donc
au plus un appel exact-ID.

Le STARTED doit être committé avant l'HTTP. Seul l'appelant ayant inséré cette
ligne (`owned=true`) peut appeler Apollo. Les règles sont :

```text
même policy_evaluation_id
    -> run existant, zéro nouvel appel

même run ID + mêmes bindings
    -> run existant, zéro nouvel appel

même run ID + autre policy evaluation
    -> CompanyResearchRunIdentityConflict, zéro appel
```

Les races SQLite/PostgreSQL utilisent l'insert conflict-safe déjà établi par
SPEC-020/021 ; aucune `IntegrityError` brute ne constitue le flux normal.

Budget planifié : exactement 1 crédit Apollo. `provider_calls` vaut 0 ou 1.
Les crédits observés restent `NULL` sauf donnée autoritaire Apollo. Un échec
HTTP n'est jamais déclaré facturé par supposition. Les crédits Apollo restent
distincts des budgets CHF/EUR.

## 15. Exécution provider et erreurs

Taxonomie bornée :

```text
unauthorized
forbidden
client_error
rate_limited
timeout
network_error
server_error
malformed_response
response_too_large
provider_identity_mismatch
```

Mapping :

- `401 -> unauthorized` ;
- `403 -> forbidden` ;
- `404/422 -> client_error`, fail closed ;
- `429 -> rate_limited`, `Retry-After` conservé seulement s'il est autoritaire ;
- `5xx -> server_error` ;
- timeout/réseau séparés ;
- réponse `200` structurellement invalide -> `malformed_response` ;
- ID `200` divergent -> `provider_identity_mismatch`.

Tout échec termine le run `FAILED`, sans profil, sans transition et sans boucle
de retry. Un échec ne devient jamais un profil `LIMITED`.

## 16. Transaction terminale

### 16.1 Réponse actuelle complète ou partielle

Après `V -> POLICY_EVALUATED -> V+1`, le service ouvre une transaction unique :

1. lock/reload opportunity ;
2. exiger `stream_version == V+1`, état `ENRICHING`, supplier/contact inchangés
   et `next_action == enrich_company` ;
3. revalider supplier/contact et l'identité Apollo exacte ;
4. insert/update `acquisition_company_profile` avec CAS ;
5. append `STATE_TRANSITIONED(READY_FOR_DECISION)` avec expected `V+1` ;
6. append `NEXT_ACTION_SET(evaluate_opportunity)` avec expected `V+2` ;
7. terminer le run `SUCCESS` ou `LIMITED` ;
8. commit.

Après commit : stream `V+3`, `campaign_ref` et `decision` inchangés, aucune
action outbound. Les idempotency keys sont dérivées du run et de l'opération,
par exemple `company_research:<run_id>:ready` et
`company_research:<run_id>:next_action`.

Si l'une des écritures, le CAS ou la concurrence échoue, la transaction entière
est rollback. Le run STARTED préexistant peut ensuite être marqué `FAILED` dans
une transaction bornée séparée avec `opportunity_concurrency_conflict` ou
`persistence_error`. Aucun profil partiel ni workflow partiellement avancé ne
reste committé.

### 16.2 Pas de nouvel EventType

SPEC-022 n'ajoute aucun `EventType`. Le profil durable est adressable par
`acquisition_opportunity_id`, et les événements existants expriment exactement
la progression de workflow. Un événement `COMPANY_RESEARCHED` dupliquerait la
projection et élargirait inutilement `acquisition-state-v1`.

## 17. Comment SPEC-023 trouve le prebuild

L'autorité est une lecture exacte :

```text
acquisition_company_profile.acquisition_opportunity_id
    == AcquisitionOpportunity.acquisition_opportunity_id
```

SPEC-023 devra exiger :

- opportunité `READY_FOR_DECISION` ;
- `next_action == evaluate_opportunity` ;
- profil présent avec refs supplier/contact identiques ;
- `prebuild_version` supportée et empreinte vérifiable ;
- complétude explicitement consommée, jamais supposée `COMPLETE`.

Le run est un audit d'exécution, pas l'input décisionnel. Les faits publics
restent localisables via `signal_ref`.

## 18. Même supplier dans plusieurs opportunités

Le même `supplier_ref` peut apparaître dans plusieurs opportunités et produire
un profil par opportunité. Cela conserve le signal, le contact sélectionné et
le workflow propres à chaque stream, au prix possible d'un crédit Apollo par
opportunité.

Aucune base runtime n'a été interrogée — et aucun VPS ne doit l'être — donc le
taux réel de duplication n'est pas mesuré dans ce design. Le run devra exposer
les IDs nécessaires à une mesure offline ultérieure. Si la duplication devient
matérielle, une future politique de réutilisation supplier-scoped avec durée
de fraîcheur explicite pourra être proposée. Aucun cache n'est créé ici.

## 19. Sécurité, secrets et confidentialité

- credential Apollo injecté par configuration protégée ;
- aucun secret dans source, migration, fixture, report, exception ou log ;
- jamais de header d'autorisation ou corps complet loggé ;
- endpoint et host fixes ; aucune URL provider arbitraire ;
- URLs retournées traitées comme données et jamais fetchées ;
- Pydantic strict/frozen, `extra=forbid`, datetimes timezone-aware ;
- strings, arrays, JSON, numériques et payload HTTP bornés ;
- aucune donnée client, aucun LLM, raisonnement caché ou prompt ;
- aucune duplication du nom/email/personne du contact ;
- aucun téléphone corporate ou personnel ;
- aucune policy auto-modifiée par Apollo/Hermes.

## 20. Plan TDD déterministe

### Entry et actionnabilité

- seul `ENRICHING + enrich_company` est actionnable ;
- supplier/contact requis, mêmes refs ;
- contact durable `PROVIDER_VERIFIED` Apollo requis ;
- mauvais état/ref/statut -> zéro policy/run/provider.

### Policy et ownership

- `enrich_company` a le profil de metadata corrigé ;
- scope OPPORTUNITY et action fingerprint exact ;
- SHADOW et quota UNKNOWN -> zéro provider ;
- une évaluation -> un run ; replay -> zéro second appel ;
- évaluation présente/run absent -> fresh ID requis ;
- run ID collision -> conflit typé ;
- STARTED durable avant le fake provider.

### Apollo

- URL exacte `/api/v1/organizations/{id}` et méthode GET ;
- `/organizations/enrich` jamais appelé ;
- un seul appel ; API key non loggée ;
- 200 complet, 200 partiel, optional fields absents ;
- 401, 403, 404 inattendu, 422, 429, timeout, réseau, 5xx ;
- JSON/racine/organization invalides, oversize, ID divergent ;
- negative/oversized employees, founded year impossible ;
- description/keywords bornés ; URLs invalides rejetées ;
- téléphone, funding, technologies, social et raw payload non persistés.

### Prebuild

- même input -> même profil/empreinte ;
- size bands aux limites 9/10/249/250/999/1000 ;
- effectif absent -> UNKNOWN ;
- champs manquants -> LIMITED + missing codes stables ;
- aucune revenue sans devise, aucun score/decision ;
- prebuild fingerprint change avec tout input SPEC-023 ;
- run/timestamps techniques ne changent pas cette empreinte.

### Persistence et migration

- `0010 -> 0011`, fresh DB -> head, un head linéaire ;
- exactement deux tables, revision <= 32 ;
- FKs RESTRICT, unique policy evaluation, checks/indexes ;
- CAS newer/replay equal/conflict equal/stale ;
- aucune mutation de `acquisition_supplier` ou `acquisition_contact`.

### Transaction et concurrence

- profile + READY_FOR_DECISION + evaluate_opportunity + run terminal atomiques ;
- injection d'échec à chaque write -> rollback complet ;
- changement opportunity après policy -> aucun overwrite, run FAILED ;
- `LIMITED` 200 valide avance honnêtement ;
- échec réseau/HTTP ne produit jamais LIMITED.

### Architecture/privacy/side effects

- test AST contre TargetICP, accounts, matching client, billing, feedback et
  materialized signal ;
- aucun campaign/SEND/Instantly/email/crawler/shell/LLM ;
- aucun PII contact dans profil/run ;
- protocole fake/offline uniquement.

### Performance diagnostique

100 fixtures d'organisation déterministes : parse, normalisation, prebuild et
persistance SQLite transactionnelle. Mesurer médiane/total local sans créer de
SLA, de cache ou d'optimisation prématurée.

## 21. Expected files — future implementation only

```text
src/signals/company_research/__init__.py
src/signals/company_research/contracts.py
src/signals/company_research/profile.py
src/signals/company_research/prebuild.py
src/signals/company_research/provider.py
src/signals/company_research/apollo.py
src/signals/company_research/store.py
src/signals/company_research/service.py

src/signals/policy/registry.py
src/signals/persistence/schema.py
src/signals/persistence/migrations/versions/0011_company_research_*.py

tests/test_company_research_profile.py
tests/test_company_research_apollo.py
tests/test_company_research_prebuild.py
tests/test_company_research_store.py
tests/test_company_research_service.py
tests/test_company_research_migration.py
tests/test_company_research_architecture.py
```

Le design pass ne crée aucun de ces fichiers.

## 22. Réponses explicites au supervisor

1. **Pourquoi l'ID exact Apollo ?** Parce que SPEC-020 a déjà établi l'identité
   provider ; rematcher par nom/domaine la rendrait plus faible.
2. **`GET /organizations/{id}` est-il suffisant ?** Oui pour les faits corporate
   et dérivations MVP retenus.
3. **`/organizations/enrich` est-il nécessaire ?** Non.
4. **Champs persistés ?** ID/nom, domaine/site, pays provider, industrie,
   effectif, année, description courte, keywords, provenance, puis features
   Kivou explicitement dérivées.
5. **Champs écartés ?** Téléphones, adresses détaillées, social, funding,
   technologies, hiérarchie, org chart/person IDs, intent, account, raw payload
   et revenue sans devise autoritaire.
6. **Qu'est-ce que le prebuild ?** Un snapshot opportunity-scoped de faits
   minimisés et features déterministes pour SPEC-023.
7. **Pourquoi n'est-il pas TargetICP ?** Il appartient à l'Acquisition Engine
   Kivou, sans compte, préférence, feedback, matching ou ownership client.
8. **Dérivations ?** Size band, identity status repris, contact role tier,
   provider research status, complétude et missing fields.
9. **Score fit/lead/SEND ?** **NON.**
10. **Localisation par SPEC-023 ?** PK/FK exact
    `acquisition_opportunity_id` sur `acquisition_company_profile`.
11. **Réponse partielle ?** 200 exact accepté, absences explicites, profil/run
    LIMITED, workflow prêt pour décision.
12. **ID Apollo plus disponible ?** Aucun fallback fabriqué dans v1 ; run
    FAILED tant qu'un sentinel fiable n'est pas documenté.
13. **Distinction fiable ?** Non avec l'OpenAPI endpoint actuelle : 422 est
    invalide, et le 404 générique peut aussi signifier inaccessible.
14. **Nouvel EventType ?** Non.
15. **Progression ?** Deux événements existants, atomiques avec le profil/run :
    `STATE_TRANSITIONED(READY_FOR_DECISION)`, puis
    `NEXT_ACTION_SET(evaluate_opportunity)`.
16. **Crédits normaux ?** Exactement 1 crédit Apollo planifié par run.
17. **Pourquoi séparer la PII contact ?** Le profil entreprise n'a besoin que
    du ref et du role tier ; dupliquer l'email augmente exposition et dérive.
18. **Supplier partagé ?** Un profil par opportunity ; coût possiblement répété,
    cache supplier-level différé jusqu'à mesure et politique de fraîcheur.

## 23. Décisions finales de design

```text
Apollo endpoint selected             GET /api/v1/organizations/{id}
Organization Enrichment needed       NO
planned provider credits/run         1
migration 0011 recommended           YES
tables                               acquisition_company_profile
                                     company_research_run
new Acquisition EventType required   NO
prebuild code name                   AcquisitionProspectPrebuild
LLM / crawler / outbound             NO
```

Question nécessitant validation supervisor, mais sans ambiguïté
d'implémentation proposée : approuver le choix fail-closed qui refuse de traiter
`404/422` comme « no current provider record » tant qu'Apollo ne fournit pas un
sentinel exact et fiable. Aucun travail d'implémentation ne commence avant cet
accord.
