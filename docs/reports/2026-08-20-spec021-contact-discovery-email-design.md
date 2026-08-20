# SPEC-021 — Contact Discovery + Provider-Verified Business Email — Design

Date : 2026-08-20

Branche : `feat/spec021-contact-discovery-email`

Base autoritaire : `2216837d9884594b91f38cd3704fdb6b3234c985`

Alembic head : `0009_supplier_discovery`

Statut : design uniquement — aucune implémentation, migration ou requête Apollo

## 1. Objectif et périmètre

SPEC-021 conçoit un chemin borné, permissionné et sans outbound :

```text
AcquisitionOpportunity
  supplier_ref connu
  next_action = find_decision_makers
        -> profil de recherche de décideur Kivou
        -> Policy Gateway évaluée à neuf
        -> Apollo People API Search
        -> classement déterministe Kivou
        -> jusqu'à trois People Enrichment séquentiels
        -> email professionnel vérifié par Apollo
        -> identité contact Kivou durable
        -> CONTACT_SELECTED
        -> DISCOVERED -> ENRICHING
        -> next_action = enrich_company
```

Le composant ne contacte personne. Il ne crée ni campagne, ni message, ni
décision `SEND`/`NO_SEND`, n'appelle ni Instantly ni SMTP, n'utilise aucun
téléphone, aucun email personnel, aucun waterfall et ne définit aucune règle
juridique CH/FR/EU. SPEC-025 reste l'autorité future de conformité détaillée.

## 2. Audit du code autoritaire

### 2.1 Acquisition Opportunity et `contact_ref`

Le code courant distingue correctement l'opportunité de marché public de
`AcquisitionOpportunity`. SPEC-020 crée cette dernière avec :

```text
signal_ref   = procurement-opportunity:<opportunity_key>
supplier_ref = <supplier_ref Kivou>
contact_ref  = NULL
campaign_ref = NULL
state        = DISCOVERED
next_action  = find_decision_makers
```

`contact_ref` existe déjà dans le contrat, la projection SQL et le reducer
`acquisition-state-v1`, mais il n'est renseigné que par
`OPPORTUNITY_CREATED`. Aucun événement courant ne peut attacher honnêtement un
contact découvert après la création. Une mise à jour SQL directe produirait
une projection impossible à reconstruire depuis le journal et est rejetée.

### 2.2 Garanties du store acquisition

`AcquisitionStore` fournit déjà :

- append event + projection dans une transaction ;
- `expected_version` et conflit d'optimistic concurrency ;
- idempotence par `(acquisition_opportunity_id, idempotency_key)` ;
- `append_in_transaction()` pour une transaction métier appartenant à
  l'appelant ;
- replay déterministe sélectionné par `state_machine_version`.

SPEC-021 doit étendre cette API connection-aware de la manière la plus étroite
possible afin d'enchaîner plusieurs événements dans une unique transaction,
sans dupliquer le reducer ni contourner ses contrôles.

### 2.3 Supplier Discovery disponible

`acquisition_supplier` fournit l'identité Kivou `supplier_ref`, l'identité
Apollo `provider_organization_id`, le nom normalisé et la provenance de
l'observation. L'identité fournisseur est donc connue avant la recherche de
personnes. SPEC-021 n'effectue jamais une recherche globale par nom quand
l'identifiant Apollo exact est disponible.

### 2.4 Policy Gateway actuelle

`find_decision_makers` existe avec `TargetScope.OPPORTUNITY`, mais sa métadonnée
ne demande actuellement que l'évidence `SUPPLIER` et un budget. Elle ne marque
pas encore le quota fournisseur ni le control plane comme pertinents.

Une évaluation opportunity-scoped écrit déjà atomiquement `policy_evaluation`
et `POLICY_EVALUATED`, ce qui avance la version du stream d'une unité. Le
service devra donc :

1. lire la version `V` de l'opportunité ;
2. évaluer la policy avec `expected_opportunity_version=V` ;
3. considérer `V+1` comme version attendue après l'audit policy ;
4. refuser la mutation finale si un événement concurrent est apparu.

La garantie SPEC-020 « une policy evaluation = au plus un run fournisseur »
est réutilisée à l'identique.

## 3. Qui est le décideur recherché ?

Le décideur est une personne, chez l'entreprise fournisseur découverte par
SPEC-020, susceptible d'acheter ou d'utiliser Kivou comme outil de sales
intelligence et d'acquisition commerciale.

Ce rôle n'est **pas** déduit de la catégorie de besoin opérationnel du marché
public. Un contrat public peut révéler un besoin de recrutement, de sécurité,
de logiciel ou de travaux chez l'attributaire ; ce besoin sert à identifier
des entreprises susceptibles de lui vendre une solution. Il ne signifie pas
que Kivou doit contacter le responsable RH, sécurité, IT ou opérations de ces
fournisseurs. Kivou cherche prioritairement les responsables Sales,
Commercial, Business Development ou Revenue de ces fournisseurs, puis un
dirigeant/fondateur en fallback.

Cette séparation empêche le Need Graph d'être détourné en profil de personne.
Le Need Graph reste gelé et n'entre pas dans le classement des contacts.

## 4. Baseline Apollo officielle vérifiée

Sources techniques officielles consultées le 2026-08-20 :

- [People API Search](https://docs.apollo.io/reference/people-api-search) :
  `POST https://api.apollo.io/api/v1/mixed_people/api_search`, 0 crédit,
  aucun email ni téléphone retourné, au plus 100 résultats par page et limite
  d'affichage de 50 000 ;
- [People Enrichment](https://docs.apollo.io/reference/people-enrichment) :
  `POST https://api.apollo.io/api/v1/people/match`, paramètre `id` issu de
  People Search, emails personnels et téléphones désactivés par défaut ;
- [API Pricing and Credits](https://docs.apollo.io/docs/api-pricing) : People
  Enrichment consomme actuellement 1 à 9 crédits par personne si une donnée
  facturable est trouvée — 1 pour démographie/email, 8 supplémentaires pour un
  mobile — et 0 si aucune donnée facturable n'est trouvée ; les plans legacy
  peuvent différer ;
- [OpenAPI officielle](https://docs.apollo.io/reference/openapi-specification)
  : schéma régénéré lors de chaque publication Apollo.

Le schéma OpenAPI courant confirme les filtres :

```text
organization_ids[]
person_titles[]
person_seniorities[]
contact_email_status[]
include_similar_titles
page
per_page
```

La réponse People Search documente `people[].id`, `first_name`,
`last_name_obfuscated`, `title`, `last_refreshed_at`, `has_email` et un objet
`organization` limité. Elle ne documente ni email, ni téléphone, ni
`organization.id` dans chaque résultat. La requête est donc strictement
contrainte à un seul `organization_ids[]`; le nom d'organisation documenté est
un contrôle conservateur supplémentaire, mais seul
`People Enrichment.person.organization_id` fournit le hard gate d'employeur.

People Enrichment documente notamment `person.id`, `name`, `first_name`,
`last_name`, `title`, `organization_id`, `email` et `email_status`. Aucun champ
non documenté n'est rendu obligatoire.

## 5. Profil Kivou FR + EN

Version initiale : `decision-maker-search-v1`.

Le profil est callable-free, immuable et appartient à Kivou. Hermes ne fournit
ni titre, ni seniority, ni paramètre Apollo. La version initiale propose les
familles suivantes :

| Priorité | Famille | Titres anglais | Titres français |
|---|---|---|---|
| 1 | direction commerciale | Head of Sales, Sales Director, VP Sales, Commercial Director, Chief Revenue Officer | Directeur commercial, Directeur des ventes |
| 2 | développement commercial | Business Development Director, Head of Business Development, VP Business Development | Directeur du développement commercial, Responsable développement commercial |
| 3 | management commercial | Sales Manager, Business Development Manager | Responsable commercial, Responsable des ventes |
| 4 | direction générale fallback | Managing Director, CEO, Founder, Owner | Directeur général, Fondateur, Dirigeant |

Seniorities Apollo autorisées :

```text
owner, founder, c_suite, vp, head, director, manager
```

`include_similar_titles=false` limite l'élargissement automatique. Toute
modification de titres, tiers, seniorities ou seuils exige une nouvelle version
du profil et une nouvelle empreinte ; aucun LLM ne classe ou ne complète la
liste.

Les dirigeants généralistes sont un fallback : sans donnée fiable de taille
d'entreprise, ils restent sous les fonctions commerciales explicites. Aucun
genre, âge, photo, origine, personnalité ou lieu personnel n'entre dans le
profil ou le score.

## 6. `DecisionMakerSearchProfile`

Contrat proposé :

```text
profile_version
acquisition_opportunity_id
expected_opportunity_version
supplier_ref
provider_organization_id
supplier_normalized_name
title_families[]
person_titles[]
person_seniorities[]
contact_email_status[] = [verified]
include_similar_titles = false
max_pages = 1
per_page <= 25
max_enrichment_attempts <= 3
search_too_broad_threshold = 250
profile_fingerprint
```

Le seuil de 250 est un choix Kivou conservateur de
`decision-maker-search-v1`, soit dix fois le plafond de résultats demandé. Il
n'est ni la limite fournisseur de 50 000 ni une invitation à crawler. Il entre
dans `profile_fingerprint` et Hermes ne peut pas le modifier.

Le profil n'accepte aucun JSON Apollo arbitraire, endpoint, URL, titre ou
filtre libre. L'encodage canonique trie les collections sans ordre métier et
calcule SHA-256 sur tous les champs décisionnels.

## 7. Recherche People bornée

Requête proposée :

```text
POST /api/v1/mixed_people/api_search
organization_ids[]        = [supplier.provider_organization_id]
person_titles[]            = liste FR/EN Kivou
person_seniorities[]       = liste Kivou
contact_email_status[]     = [verified]
include_similar_titles     = false
page                       = 1
per_page                   <= 25
```

`contact_email_status[]=verified` est uniquement un préfiltre à coût nul. Ni
ce filtre ni `has_email=true` ne créent un contact vérifié.

Le parser exige un objet racine borné, `total_entries >= 0` et une collection
`people` conforme. Chaque item est rejeté isolément s'il manque un ID Apollo,
un titre exploitable ou si ses champs dépassent les limites. Une réponse JSON
invalide, une racine incorrecte, une collection absente ou une payload trop
grande est un échec page-level `malformed_response`.

Le nom employeur documenté par Search, lorsqu'il est présent, doit correspondre
de façon conservatrice au nom Kivou normalisé ; une divergence est rejetée avec
`search_employer_mismatch`. Comme Apollo ne documente pas l'ID employeur dans
le résultat Search, cette étape n'est pas une preuve d'emploi : le hard gate
reste l'enrichissement.

Si `total_entries > 250`, le run se termine
`CONTACT_SEARCH_TOO_BROAD`, sans enrichissement. Aucun parcours des 50 000
résultats n'est autorisé.

## 8. Classement déterministe

Le classement sert uniquement à choisir l'ordre des trois enrichissements. Il
ne constitue ni une décision commerciale, ni une décision `SEND`.

Ordre proposé :

1. tier de famille de titre ;
2. correspondance exacte du titre normalisé avant correspondance de famille ;
3. priorité de seniority Kivou ;
4. titre normalisé lexical ;
5. Apollo person ID lexical.

La normalisation Unicode/casse/espaces/ponctuation est pure et versionnée. Les
doublons d'ID sont éliminés avant classement. La position Apollo peut être
conservée pour diagnostic mais ne peut inverser un ordre Kivou plus fort. Une
même collection logique produit le même ordre, même si Apollo change l'ordre
de retour.

## 9. Enrichissement séquentiel et coût

Le protocole provider étroit expose uniquement :

```text
search_people(profile, page=1)
enrich_person(provider_person_id)
```

L'implémentation Apollo appelle un enrichissement à la fois, dans l'ordre
Kivou, et s'arrête au premier contact acceptable ou après trois tentatives.
Chaque requête force explicitement :

```text
id                      = provider_person_id
reveal_phone_number     = false
reveal_personal_emails  = false
run_waterfall_phone     = false
run_waterfall_email     = false
```

Aucun bulk match, webhook ou endpoint générique n'est utilisé.

People Search compte 0 crédit selon la documentation courante. Sans téléphone
ni waterfall, le budget fournisseur planifié est au plus un crédit email/
démographie par tentative, donc au plus trois unités pour le run MVP. Ce sont
des crédits Apollo, pas des CHF/EUR. Les crédits observés restent `NULL` sauf
si Apollo fournit une donnée autoritaire. Un 401, 403 ou 429 ne sera jamais
présumé facturé.

## 10. Ce que « VERIFIED » signifie

Un contact réussit uniquement si :

- `person.id` est valide et correspond au candidat demandé ;
- `person.organization_id` correspond exactement au
  `provider_organization_id` du supplier ;
- l'email professionnel est syntaxiquement valide et borné ;
- `person.email_status` vaut exactement `verified` ;
- `reveal_personal_emails=false` et aucun waterfall n'a été utilisé.

Kivou enregistre alors :

```text
verification_state    = PROVIDER_VERIFIED
verification_provider = apollo
provider_email_status = verified
```

La vérification est **fournie par Apollo**, pas indépendante. Elle ne garantit
ni la délivrabilité future, ni l'identité humaine avec certitude, ni la
conformité d'un outbound. Aucun SMTP ping, MX probe, ZeroBounce, NeverBounce ou
Hunter n'est ajouté.

`unverified`, `unavailable`, `likely to engage`, une valeur inconnue ou un
email malformé échouent. Kivou ne fabrique jamais
`prenom.nom@domaine`.

## 11. Identité contact Kivou

`contact_ref` est immuable et déterministe :

```text
SHA-256(
  contact-identity-v1,
  provider=apollo,
  provider_person_id,
  supplier_ref
)
```

Contrainte SQL correspondante :

```text
UNIQUE(provider, provider_person_id, supplier_ref)
```

L'email, le nom, le titre et LinkedIn ne participent jamais à l'identité. Une
même personne Apollo chez deux suppliers produit deux `contact_ref`. Ainsi un
changement d'employeur ne déplace ni ne corrompt l'identité historique attachée
à une ancienne AcquisitionOpportunity.

Un changement ultérieur d'email vérifié ou de titre conserve `contact_ref` et
met à jour uniquement les métadonnées bornées si
`incoming.provider_observed_at >= stored.provider_observed_at`. Une observation
plus ancienne ne remplace jamais une plus récente.

## 12. Data minimization

Table `acquisition_contact` proposée :

```text
contact_ref                         PK
supplier_ref                        FK acquisition_supplier, RESTRICT
provider
provider_person_id
provider_organization_id
first_name
last_name
display_name
title
normalized_title
role_profile_version
role_tier
business_email
provider_email_status
verification_state
verification_provider
provider_observed_at
email_observed_at
source_fingerprint
created_at
updated_at
UNIQUE(provider, provider_person_id, supplier_ref)
```

Le LinkedIn personnel n'est **pas persisté** dans le MVP : l'ID Apollo suffit
à l'enrichissement et l'URL n'est nécessaire ni à l'identité ni au prochain
workflow. Sont également exclus : téléphone, email personnel, photo, adresse
ou localisation personnelle, historique d'emploi, biographie, profils sociaux,
payload brut, headers Apollo et listes d'emails.

Un seul email professionnel sélectionné est stocké. Il n'est ni unique ni une
clé de fusion.

## 13. Migration 0010

Migration recommandée : **OUI**.

Révision :

```text
0009_supplier_discovery
    ->
0010_contact_discovery
```

L'identifiant fait moins de 32 caractères. Deux tables seulement sont
nécessaires :

1. `acquisition_contact`, identité et observation courante minimisée du
   contact/employeur ;
2. `contact_discovery_run`, propriété d'exécution et audit provider borné.

Les tables 0007–0009 ne peuvent pas représenter honnêtement une identité de
personne, un email vérifié, les tentatives d'enrichissement ou la propriété
d'un run. Aucun Event Bus, table de personne générique, historique d'emails,
queue ou table d'approbation n'est créé.

Indexes justifiés : supplier + verification state sur `acquisition_contact`,
opportunity + started_at et status + started_at sur le run. Aucun index ou
contrainte d'unicité sur l'email.

## 14. `contact_discovery_run`

Schéma conceptuel :

```text
contact_discovery_run_id            PK
acquisition_opportunity_id           FK RESTRICT
supplier_ref                         FK RESTRICT
policy_evaluation_id                 FK RESTRICT, UNIQUE
provider                             apollo
search_profile_version
search_profile_fingerprint
provider_request_fingerprint
requested_max_pages                  1
per_page                             <= 25
max_enrichment_attempts              <= 3
people_search_requests
candidates_returned
candidates_eligible
candidates_rejected
enrichment_attempts
planned_provider_credit_units
observed_provider_credit_units       nullable
attempted_contact_refs               JSON borné, max 3
selected_contact_ref                 nullable FK RESTRICT
started_at
completed_at                         nullable
status
error_category                       nullable
error_detail                         nullable, borné et sans PII
retry_after                          nullable
correlation_id
```

Vocabulaire fixe :

```text
STARTED
SUCCESS
NO_CANDIDATE
NO_VERIFIED_CONTACT
CONTACT_SEARCH_TOO_BROAD
FAILED
```

`attempted_contact_refs` contient uniquement les hashes Kivou, jamais les
emails ni les payloads Apollo. Le run STARTED est inséré **avant** People
Search. `UNIQUE(policy_evaluation_id)` impose : une policy evaluation, au plus
un run et donc au plus un chemin de consommation de crédits. Même run ID avec
une autre policy evaluation produit un conflit typé ; aucune `IntegrityError`
brute ne devient un flux de contrôle.

## 15. Policy Gateway

Métadonnée `find_decision_makers` corrigée :

```text
risk_class              PREPARATORY
target_scope            OPPORTUNITY
required_evidence       SUPPLIER, CONTACT_SEARCH_PROFILE
uses_budget             true
uses_provider_quota     true
requires_control_plane  true
uses_send_controls      false
requires_compliance     false
```

La requête est liée à :

```text
target_ref                      acquisition-opportunity:<id>
acquisition_opportunity_id      <id>
expected_opportunity_version    V
canonical_arguments             profil canonique + bornes provider
action_fingerprint              SHA-256 des arguments
```

Le service construit le profil depuis l'opportunité et le supplier persistés,
puis appelle `PolicyGateway.evaluate_and_record()` immédiatement avant de
revendiquer le run. Il n'accepte jamais un ancien `PolicyDecision` comme token.

En SHADOW, la policy et son audit counterfactual peuvent être produits, mais
`executable=false` entraîne : zéro run et zéro appel Apollo. Quota fournisseur
`UNKNOWN` ou control plane indisponible échoue avant le réseau. Mailbox quota
et send window sont sans effet car ce n'est pas un envoi.

## 16. Provider et erreurs

Un unique `ApolloContactDiscoveryClient` implémente le protocole étroit ; le
service métier ne dépend d'aucun objet SDK Apollo.

Erreurs typées :

```text
unauthorized
forbidden
rate_limited
provider_limit
timeout
server_error
client_error
network_error
malformed_response
```

Un 429 n'est jamais un résultat vide et ne déclenche aucune boucle. Le
`Retry-After` est conservé seulement s'il est fourni de manière autoritaire.
Les API keys et headers d'autorisation ne sont ni journalisés ni persistés ; le
corps complet d'une réponse invalide n'est pas loggé.

## 17. Événement `CONTACT_SELECTED`

Extension acquisition recommandée : **OUI**.

```text
EventType.CONTACT_SELECTED
payload:
  contact_ref
  supplier_ref
```

Règles reducer :

- état source `DISCOVERED` ;
- `supplier_ref` courant non nul et identique au payload ;
- `contact_ref` courant nul ;
- la validité durable du contact, son fournisseur et son statut
  `PROVIDER_VERIFIED` sont contrôlés par le store/service dans la même
  transaction avant append ;
- l'événement renseigne uniquement `contact_ref` et les métadonnées communes
  de stream ; il ne modifie ni state, decision, retry, supplier_ref ou
  campaign_ref ;
- idempotence opportunity-scoped obligatoire ; un second contact différent
  produit un conflit, jamais un remplacement silencieux.

## 18. Compatibilité `acquisition-state-v1`

Changement de version du state machine recommandé : **NON**.

La justification est étroite :

- `contact_ref` est déjà un champ de la projection v1 et peut déjà être défini
  par `OPPORTUNITY_CREATED` ;
- `CONTACT_SELECTED` ajoute une nouvelle forme d'événement pour de nouveaux
  streams futurs sans modifier l'interprétation d'aucun EventType existant ;
- aucune transition d'état historique ne change ;
- un stream créé avant SPEC-021 ne contient pas `CONTACT_SELECTED` et doit
  rejouer vers une projection strictement identique avant/après l'extension ;
- un type inconnu autre que la nouvelle valeur explicitement enregistrée reste
  rejeté fail-closed.

Il s'agit donc d'une extension additive de vocabulaire sous
`acquisition-state-v1`, comparable en mécanique aux événements audit additifs,
mais avec un test de non-régression plus strict car `contact_ref` est modifié.
Si l'implémentation exigeait de réinterpréter `OPPORTUNITY_CREATED`,
`STATE_TRANSITIONED` ou une ancienne transition, elle devrait s'arrêter et
proposer `acquisition-state-v2`; le design approuvé ici ne l'exige pas.

## 19. Transaction de succès

Après l'audit policy (version `V+1`) et les appels provider, une transaction
bornée effectue :

```text
BEGIN
  relire/verrouiller l'AcquisitionOpportunity à V+1
  vérifier DISCOVERED + next_action=find_decision_makers + contact_ref NULL
  upsert acquisition_contact par observation compare-and-set
  append CONTACT_SELECTED              -> V+2
  append STATE_TRANSITIONED ENRICHING   -> V+3
  append NEXT_ACTION_SET enrich_company -> V+4
  terminer contact_discovery_run SUCCESS
COMMIT
```

`supplier_ref` ne change pas, `campaign_ref` reste `NULL`, et aucun événement
de décision ou d'envoi n'est produit. Une erreur de contact, append,
projection, run ou concurrency annule toute cette transaction. Le run STARTED
préexistant est ensuite marqué `FAILED` avec une catégorie sûre dans une
transaction séparée ; aucune ligne contact orpheline et aucun stream partiel
ne subsistent.

Une replay du même run retourne son état durable sans nouveau provider call.
Une nouvelle tentative requiert un nouvel `evaluation_id`, mais une opportunité
ayant déjà un contact ou ayant progressé n'est pas actionable et ne consomme
pas de crédit.

## 20. Aucun contact vérifié

L'absence de contact est un résultat métier valide :

- recherche valide sans candidat : `NO_CANDIDATE` ;
- candidats épuisés sans email acceptable : `NO_VERIFIED_CONTACT` ;
- profil trop large : `CONTACT_SEARCH_TOO_BROAD`.

Dans chaque cas, aucun `acquisition_contact` n'est inventé et `contact_ref`
reste nul. La terminaison du run et un unique
`NEXT_ACTION_SET(request_human_review)` sont atomiques. L'état reste
`DISCOVERED`; aucun retry automatique des mêmes trois personnes n'est lancé.

En cas de panne fournisseur, le run est `FAILED`. Un `Retry-After` autoritaire
peut être persisté dans le run et, si l'orchestration choisit explicitement de
le faire, via `RETRY_SCHEDULED`; aucune date n'est inventée et aucun worker
n'est ajouté.

## 21. Sécurité et confidentialité

Les réponses Apollo sont des données externes non fiables. Les contrats
bornent tailles, tableaux, IDs, noms, titres, emails, timestamps et payload
HTTP. Les textes de titre ou de nom ne sont jamais des instructions.

Interdictions d'architecture testables :

- aucun import de `TargetICP`, feedback, billing, materialized-signal ownership
  ou matching client ;
- aucun People Bulk Match, People Contact Search, phone, personal email,
  waterfall, SMTP, Instantly, Stripe, shell ou exécuteur générique ;
- aucun secret dans les fixtures, logs, tables ou rapports ;
- aucune donnée protégée/personnelle utilisée par le ranking ;
- aucune conformité ou autorisation d'outbound déduite du statut Apollo.

## 22. Alternatives évaluées

### A — Deux tables + `CONTACT_SELECTED` additif v1 — retenu

Cette option sépare l'identité personnelle minimisée de l'audit provider,
préserve l'event sourcing et permet une transaction de sélection complète.

### B — Mise à jour directe de `contact_ref` — rejetée

La projection ne serait plus reconstructible et l'audit ne pourrait expliquer
ni qui a sélectionné le contact ni sur quelle preuve.

### C — Nouveau `acquisition-state-v2` — non requis

Aucun événement historique ni transition existante n'est réinterprété. Un v2
introduirait une migration de streams sans gain de sécurité pour cette
extension additive.

### D — Table de tous les candidats/enrichissements — rejetée

Elle augmenterait la collecte de PII et conserverait des personnes non
sélectionnées. Le run conserve uniquement compteurs et contact refs hashés.

### E — Email indépendant ou waterfall — rejetée

Ce serait une nouvelle exposition de données, un nouveau coût et un nouveau
fournisseur hors périmètre. Le MVP demande une provenance Apollo explicite.

## 23. Plan TDD déterministe

### Policy et ownership

- scope opportunity, supplier/profile evidence, provider quota et control
  plane requis ;
- SHADOW, quota UNKNOWN, policy refusée : zéro run et zéro provider call ;
- STARTED avant People Search ;
- un `policy_evaluation_id` donne au plus un run ;
- collision run ID typée ; replay : aucun second appel ;
- nouvelle tentative : nouvel evaluation ID et policy fraîche.

### Search et profil

- exact `organization_ids[]` supplier ;
- titres FR/EN, seniorities et `verified` appartenant à Kivou ;
- aucun paramètre Hermes arbitraire ;
- une page, 25 résultats, seuil 250 ;
- recherche trop large ; schéma/root/item malformé ;
- divergence de nom employeur Search rejetée ;
- aucun email/téléphone lu depuis Search.

### Ranking

- même input logique, même ordre ;
- commercial/sales avant rôle opérationnel ;
- dirigeants en fallback ; tie lexical stable ;
- aucun attribut protégé ou personnel.

### Enrichment

- trois tentatives maximum, séquentielles ;
- arrêt au premier email acceptable ;
- flags phone/personal/waterfall toujours faux ;
- ID personne et organisation contrôlés ;
- 401, 403, 429, timeout, 5xx, réseau et malformed typés ;
- Retry-After préservé sans invention.

### Email, identité et employeur

- `verified` exact accepté ; autres statuts et email malformé rejetés ;
- aucune génération d'email ;
- même personne + supplier : même contact ref ;
- même personne + autre supplier : contact ref différent ;
- email changé : même identité ;
- aucun merge par nom/email/LinkedIn ;
- mismatch d'organisation Search rejeté conservativement ; mismatch
  `enrichment.organization_id` toujours rejeté.

### Persistence et acquisition

- fresh DB -> 0010 et 0009 -> 0010 ; deux tables/contraintes/indexes ;
- observation ancienne ne remplace pas la nouvelle ;
- ni raw payload, téléphone, email personnel ou LinkedIn stocké ;
- succès atomique : contact + trois events + terminal run ;
- rollback de chaque direction ;
- `CONTACT_SELECTED` idempotent et concurrency-safe ;
- état `ENRICHING`, next action `enrich_company`, campagne nulle ;
- redécouverte ne remplace pas le contact, ne rewind pas le workflow et
  n'ajoute aucun event ;
- NO_CANDIDATE/NO_VERIFIED_CONTACT : contact nul et human review bornée.

### Replay et version

- streams SPEC-018/019/020 antérieurs rejoués avant/après avec projection
  identique ;
- `CONTACT_SELECTED` renseigne seulement contact_ref + audit metadata ;
- replay complet reconstruit contact, état et next action ;
- événement inconnu et version historique inconnue rejetés fail-closed.

### Non-régression et side effects

- aucun import customer privé ;
- aucun phone/personal/waterfall/bulk endpoint ;
- aucun email, Instantly, SMTP, Stripe, shell, campagne ou `SEND` ;
- 100 fixtures Search puis trois enrichissements simulés maximum pour une
  mesure locale de normalisation/ranking/persistence, sans SLA inventée.

## 24. Fichiers attendus lors de l'implémentation

```text
src/signals/contact_discovery/__init__.py
src/signals/contact_discovery/contracts.py
src/signals/contact_discovery/profile.py
src/signals/contact_discovery/ranking.py
src/signals/contact_discovery/identity.py
src/signals/contact_discovery/provider.py
src/signals/contact_discovery/apollo.py
src/signals/contact_discovery/store.py
src/signals/contact_discovery/service.py
src/signals/acquisition/contracts.py
src/signals/acquisition/state.py
src/signals/acquisition/store.py
src/signals/policy/registry.py
src/signals/persistence/schema.py
src/signals/persistence/migrations/versions/0010_contact_discovery_*.py
tests/test_contact_discovery_*.py
tests/test_acquisition_state.py
tests/test_*migration*.py
docs/reports/2026-08-20-spec021-contact-discovery-email.md
```

La liste est indicative et doit rester minimale. Aucun frontend n'est attendu.

## 25. Réponses explicites

**Qui est le décideur ?** Le responsable commercial/sales/business development
ou revenue du fournisseur, avec direction générale/fondateur comme fallback.

**Pourquoi est-il sans rapport avec le besoin opérationnel du marché ?** Le
Need Graph explique ce que le gagnant du marché pourrait acheter au fournisseur
; le contact recherché est la personne du fournisseur susceptible d'acheter
Kivou pour développer ses ventes.

**Qu'est-ce qu'un email VERIFIED ?** Un email professionnel syntaxiquement
valide retourné par People Enrichment avec `email_status=verified`, employeur
Apollo strictement concordant et flags personal/phone/waterfall désactivés.

**Vérification Apollo ou indépendante ?** Apollo uniquement, enregistrée
`PROVIDER_VERIFIED`; aucune vérification indépendante.

**Pourquoi un changement d'employeur ne corrompt-il pas `contact_ref` ?**
Parce que l'identité hashée et la contrainte unique incluent `supplier_ref` ;
la personne chez un nouvel employeur reçoit une autre identité Kivou.

**Comment le contact est-il attaché ?** Par l'événement idempotent
`CONTACT_SELECTED` dans la même transaction que le contact durable, la
transition vers `ENRICHING`, `NEXT_ACTION_SET(enrich_company)` et le run
terminal.

**Faut-il `acquisition-state-v2` ?** Non : aucun ancien événement n'est
réinterprété, le champ existe déjà et les anciens streams rejouent à
l'identique. Toute découverte contraire pendant TDD impose un arrêt.

**Que se passe-t-il sans contact vérifié ?** Aucun contact n'est inventé ; le
run finit `NO_CANDIDATE` ou `NO_VERIFIED_CONTACT`, l'opportunité reste
`DISCOVERED` et passe à `request_human_review` sans retry automatique.

## 26. Décisions finales du design

```text
migration 0010 recommandée       OUI
tables                            acquisition_contact
                                  contact_discovery_run
extension acquisition event      OUI — CONTACT_SELECTED
state-machine version change      NON
People Search pages               1
People Search per_page            <= 25
enrichment attempts               <= 3
Apollo live call                  AUCUN
questions non résolues            AUCUNE
```

CONTACT DISCOVERY DESIGN READY FOR REVIEW
