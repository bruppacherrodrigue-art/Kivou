# SPEC-020 — Supplier Discovery + Apollo — Design

Date : 2026-08-20

Branche : `feat/spec020-supplier-discovery-apollo`

Base autoritaire : `0718550f4c42a419b3cac87a9ad1b98474a0de95`

Alembic head : `0008_policy_gateway`

Statut : design uniquement — aucune implémentation, migration ou requête Apollo

## 1. Objectif et limite

SPEC-020 compose un chemin borné et permissionné :

```text
opportunité de marché public Kivou
        -> profil de recherche fournisseur Kivou
        -> Policy Gateway évalué à neuf
        -> Apollo Organization Search
        -> entreprises candidates normalisées
        -> une AcquisitionOpportunity par opportunité publique × fournisseur
```

Le résultat est une liste de **supplier candidates**, pas une qualification
commerciale. Le composant ne cherche aucune personne, ne découvre ni email ni
téléphone, ne décide jamais `SEND`, ne personnalise rien, ne crée aucune
campagne et n'appelle pas Instantly. Il n'ajoute ni moteur de décision, ni règle
juridique par pays, ni exécuteur générique.

## 2. Audit du code autoritaire

### 2.1 Deux opportunités distinctes

Le code courant confirme deux objets sans équivalence implicite :

- l'opportunité publique persistante est identifiée par `opportunity_key` et
  relie une ou plusieurs lignes `opportunity_representation` à des
  `contract_award` ;
- `signals.acquisition.AcquisitionOpportunity` est l'objet durable du futur
  workflow d'acquisition. Il porte un `identity_key`, un `signal_ref`, un
  `supplier_ref` nullable, un état et une version de flux.

`opportunity_key` reste stable lorsqu'une représentation BOAMP/DECP arrive plus
tard. SPEC-020 ne renomme, ne fusionne et ne réinterprète pas cet objet.

### 2.2 Sens actuel de `signal_ref` et décision SPEC-020

Le contrat SPEC-018 exige un `signal_ref`, mais le code et ses tests utilisent
jusqu'ici des références abstraites (`signal-1`) sans l'attacher à un objet
production précis. `materialized_signal` n'est pas un candidat acceptable : il
est identifié par `opportunity_key × target_icp_id` et contient une décision de
matching client.

SPEC-020 fixe le sens production de `signal_ref` à une référence de seed
d'acquisition publique, namespacée et stable :

```text
procurement-opportunity:<opportunity_key>
```

Le nom de champ historique `signal_ref` est conservé pour compatibilité avec
SPEC-018 ; sa valeur ne désigne ni un `signal_key`, ni un `TargetICP`, ni la
propriété d'un signal par un compte. Le résolveur Kivou retrouve les faits via
`opportunity_representation`, `contract_award` et `source_event`.

### 2.3 Compréhension et Need Graph

Le pipeline existant reconstruit déjà les objets canoniques depuis les faits
persistés et appelle `ContractUnderstandingEngine` puis `NeedGraphEngine`. Le
nouveau profil réutilisera ce chemin public/générique, sans `MatchingEngine`,
sans `TargetICP` et sans lire le payload d'un `materialized_signal`.

Si plusieurs représentations publiques existent, le résolveur applique une
clé de tri versionnée et déterministe : nombre décroissant de groupes publics
non vides parmi objet/titre, CPV, attributaire légal, date d'attribution, date
de notification et date de publication ; puis publication la plus récente ;
enfin `award_key` lexical croissant. La référence du seed ne change pas. Une
représentation plus complète peut produire une nouvelle empreinte de profil
lors d'une exécution ultérieure, sans renommer le seed ni les fournisseurs déjà
créés. Ce classement appartient uniquement au builder de profil fournisseur :
il ne modifie ni le Need Graph, ni le matching, ni la représentation utilisée
pour le feed client.

### 2.4 Création et enrichissement d'une AcquisitionOpportunity

`AcquisitionStore.create_opportunity()` autorise actuellement
`supplier_ref=None`, mais aucun événement/reducer ne permet d'ajouter ensuite ce
champ en conservant les garanties SPEC-018. Il serait donc incorrect de créer
un objet vide avant la recherche. SPEC-020 créera l'AcquisitionOpportunity
seulement après avoir obtenu un `supplier_ref` Kivou.

La création actuelle protège déjà `identity_key` et l'idempotence de création.
`NEXT_ACTION_SET` est state-neutral et accepte uniquement les commandes du
registre Kivou. L'état initial reste `DISCOVERED`.

### 2.5 Policy Gateway et registre de commandes

`discover_suppliers` existe, mais il est actuellement déclaré avec
`TargetScope.OPPORTUNITY`. `PolicyRequest` sait déjà porter un `target_ref` sans
`acquisition_opportunity_id`, et `policy_evaluation` sait auditer une décision
globale/non rattachée sans inventer un événement acquisition.

Le store SPEC-019 fait un pré-contrôle d'idempotence avant insertion. Une course
simultanée sur le même `evaluation_id` peut encore exposer l'unicité SQL brute ;
ce hardening doit être fermé avant le premier appel fournisseur réel.

### 2.6 Frontière client / Kivou

Les données interdites comme seeds ou filtres d'acquisition sont :

- `TargetICP` et ses besoins client ;
- feedback, contacté/non pertinent, préférences et historique d'un compte ;
- plans, facturation, entitlement et comportement privé ;
- `materialized_signal.target_icp_id`, score/matching ou propriété client.

Les seules fondations admises sont les faits de marché public, leurs références
d'évidence publique, la compréhension Kivou générique, le Need Graph gelé et
une configuration de ciblage acquisition appartenant à Kivou.

## 3. Alternatives évaluées

### A — Scope `SIGNAL` puis création par fournisseur — retenu

`discover_suppliers` vise le seed public, avec
`acquisition_opportunity_id=NULL`. La Policy Gateway produit une entrée
universelle `policy_evaluation`. Une AcquisitionOpportunity réelle n'apparaît
qu'après normalisation d'un fournisseur.

Cette option représente honnêtement l'ordre causal, évite les objets vides et
réutilise l'audit universel de SPEC-019.

### B — AcquisitionOpportunity vide avant Apollo — rejeté

Cette option inventerait `supplier_ref`, ou demanderait une nouvelle mutation
de référence dans le reducer SPEC-018. Elle créerait aussi un objet métier par
recherche plutôt que par couple seed × fournisseur.

### C — Audit global uniquement sans scope typé — rejeté

Traiter le seed public comme une commande `GLOBAL` perdrait la liaison stricte
à l'opportunité de marché et rendrait les autorisations trop larges.

## 4. Correction de scope Policy Gateway

Ajouter le scope callable-free :

```text
TargetScope.SIGNAL
```

La politique `discover_suppliers` devient :

```text
risk_class              PREPARATORY
target_scope            SIGNAL
required_evidence       PUBLIC_OPPORTUNITY, PUBLIC_EVIDENCE,
                        SUPPLIER_SEARCH_PROFILE
uses_budget             true
uses_provider_quota     true
requires_control_plane  true
requires_compliance     false
```

`uses_provider_quota` est une métadonnée Kivou, pas un callable. Elle rend la
quota Apollo pertinente sans appliquer les quotas mailbox/send window. Les
autres commandes gardent leur comportement.

La requête utilise :

```text
command                    discover_suppliers
target_ref                 procurement-opportunity:<opportunity_key>
acquisition_opportunity_id null
```

Le `canonical_arguments` et l'`action_fingerprint` lient la version/empreinte
du profil, `max_pages`, `per_page`, le plafond de candidats et le coût Kivou
annoncé. Hermes ne fournit aucun paramètre Apollo.

## 5. `AcquisitionSeed`

Contrat immuable interne proposé :

```text
signal_ref
opportunity_key
representative_award_key
public_event_ref
public_evidence_refs[]
contract_understanding
need_graph_result
observed_at
seed_fingerprint
```

Les deux derniers objets sont produits par les moteurs existants. Aucune
donnée TargetICP ou customer-match ne peut entrer dans ce contrat. Les textes
publics restent des **données non fiables**, jamais des instructions.

## 6. `SupplierSearchProfile`

Version initiale : `supplier-search-v1`.

```text
profile_version
signal_ref
representative_award_key
need_categories[]
keyword_tags[]
organization_locations[]
organization_not_locations[]
employee_ranges[]
excluded_domains[]
max_pages
per_page
candidate_cap
profile_fingerprint
```

Règles :

- `need_categories` provient du Need Graph existant ;
- une table Kivou versionnée et testée traduit les catégories en familles de
  mots-clés Apollo ; elle ne modifie pas le Need Graph ;
- localisation, taille et exclusions proviennent d'une configuration de
  ciblage acquisition Kivou, jamais d'Hermes ou d'un client ;
- le lieu du marché n'est jamais assimilé automatiquement au siège du
  fournisseur ;
- seuls des filtres explicitement modélisés sont admis ; tout nom de filtre
  Apollo inconnu est rejeté ;
- défaut : une page, 100 résultats maximum ; hard limit proposé : cinq pages
  et 500 candidats par run ;
- le JSON Apollo brut, une URL/endpoint arbitraire et tout texte exécutable sont
  interdits.

L'encodage canonique trie les ensembles, préserve l'ordre des bornes et calcule
SHA-256 sur le profil complet. Une entrée identique produit exactement la même
requête logique.

## 7. Baseline Apollo officielle vérifiée

La source technique est exclusivement la documentation officielle Apollo :

- [Organization Search](https://docs.apollo.io/reference/organization-search)
  : `POST /api/v1/mixed_companies/search`, jusqu'à 100 organisations par page,
  un crédit par page et une limite d'affichage de 50 000 résultats ;
- [Authentication](https://docs.apollo.io/reference/authentication) : clé dans
  `x-api-key`, avec la permission minimale de recherche d'organisations ;
- [Rate limits](https://docs.apollo.io/reference/rate-limits) : limites par
  équipe et endpoint, fenêtres minute/heure/jour, `429` et `Retry-After` lorsque
  fourni ; les limites réelles du workspace restent autoritaires ;
- [API pricing](https://docs.apollo.io/docs/api-pricing) : coût courant de la
  recherche d'organisations par page, à distinguer d'un coût monétaire Kivou ;
- [Status codes](https://docs.apollo.io/reference/status-codes) et
  [OpenAPI](https://docs.apollo.io/reference/openapi-specification) pour les
  statuts et formes de réponse.

Le schéma officiel expose notamment `id`, `name`, `website_url`,
`linkedin_url`, `primary_domain` et la pagination. Cela suffit à établir une
identité fournisseur prudente. **Aucun enrichissement organisation n'est
proposé**. L'API expose aussi des champs inutiles ou hors scope, dont le
téléphone : ils seront ignorés.

Endpoint proposé, unique :

```text
POST https://api.apollo.io/api/v1/mixed_companies/search
```

Sont expressément exclus : People Search, People Enrichment, Organization
Enrichment, Bulk Enrichment, Complete Organization Info et Job Postings.

## 8. Frontière fournisseur remplaçable

Le service dépend d'un protocole étroit :

```python
class SupplierDiscoveryProvider(Protocol):
    def search_page(
        self,
        profile: SupplierSearchProfile,
        *,
        page: int,
        per_page: int,
    ) -> SupplierSearchPage: ...
```

`ApolloOrganizationSearchClient` est la seule implémentation SPEC-020. Il
reçoit une configuration et un client HTTP injectés, utilise une URL fixe, un
timeout fini et produit des contrats Kivou. Aucun objet SDK Apollo ne traverse
la couche business.

Configuration non secrète : timeout, hard page cap, candidate cap et base URL
fixe. La clé Apollo est un secret runtime injecté ; elle n'est jamais loggée,
persistée, commitée ou incluse dans les fixtures.

## 9. Normalisation et sécurité de réponse

`ApolloOrganizationCandidate` borne les chaînes, URL, identifiants et taille
de tableau. Une réponse racine trop grosse, un type inattendu, une pagination
incohérente ou une organisation sans identifiant/nom devient
`malformed_response`, jamais une liste vide réussie.

Données persistées :

- fournisseur Kivou et identifiant organisation Apollo ;
- nom affiché et nom normalisé ;
- domaine primaire nullable, sans invention ;
- site web nullable ;
- URL LinkedIn **entreprise** nullable ;
- pays/localisation et industrie seulement si présents, bornés et utiles au
  profil ;
- horodatage d'observation, fingerprint de source et provenance Apollo.

Données délibérément non persistées :

- réponse Apollo brute, headers et clé ;
- personnes, emails, téléphones et LinkedIn personnels ;
- langues personnelles, historique de poste, réseaux sociaux inutiles ;
- signaux d'intent Apollo, funding, offres d'emploi, logo et texte libre non
  nécessaire ;
- rang/page Apollo comme identité ;
- score, verdict SEND ou vérité juridique.

## 10. Identité fournisseur Kivou

Version : `supplier-identity-v1`.

```text
supplier_ref = "sup_" + first_60_hex(SHA-256(
    "supplier-identity-v1\x1fapollo\x1f" + apollo_organization_id
))
```

Le résultat fait exactement 64 caractères et conserve 240 bits d'empreinte.
Le préfixe et l'empreinte sont Kivou-owned. L'identifiant Apollo est traité
comme un opaque case-sensitive, seulement trimé et validé ; il reste une
provenance et n'est jamais l'identité d'AcquisitionOpportunity.

Règles :

- `(provider, provider_organization_id)` est unique ; un replay retrouve le
  même `supplier_ref` ;
- le domaine n'est pas unique ; deux IDs Apollo partageant un domaine restent
  deux fournisseurs et reçoivent un statut explicite `DOMAIN_CONFLICT` ;
- aucune fusion fuzzy par nom ou domaine ;
- un domaine absent reste `NULL` ;
- des métadonnées plus fortes peuvent enrichir la ligne sans renommer
  `supplier_ref` ; le rapprochement cross-provider reste futur.

Cette stratégie privilégie une séparation réversible plutôt qu'une fausse
fusion irréversible.

## 11. Identité et état d'AcquisitionOpportunity

Version : `acquisition-supplier-v1`.

```text
identity_key = "acquisition-supplier-v1:" + SHA-256(
    signal_ref + "\x1f" + supplier_ref
)
```

L'identité exclut nom, domaine, rang, page, run et métadonnées mutables. Le
`creation_idempotency_key` dérive du même couple versionné. Le replay du même
fournisseur pour le même seed retourne donc la même opportunité.

Création :

```text
signal_ref   = procurement-opportunity:<opportunity_key>
supplier_ref = sup_<fingerprint>
contact_ref  = NULL
campaign_ref = NULL
state        = DISCOVERED
```

SPEC-020 ajoute ensuite de façon idempotente le `next_action` symbolique
`find_decision_makers`. Il ne passe pas à `ENRICHING` : cette transition ne
devient vraie que lorsque SPEC-021 démarre effectivement l'enrichissement.
Il ne peut atteindre `READY_FOR_DECISION`, `SEND`, `QUEUED` ou `SENT`.

Pour une création nouvelle, `acquisition_event.correlation_id` peut porter le
`discovery_run_id`. Une redécouverte ultérieure ne crée aucun nouvel événement
uniquement pour refléter un nouveau run ; ses compteurs restent dans le journal
de run. Aucun troisième lien relationnel n'est nécessaire.

## 12. Persistance et migration

### Décision

Migration `0009_supplier_discovery` recommandée : **YES**.

Les tables 0007/0008 représentent respectivement les workflows acquisition et
les autorisations. Elles ne peuvent pas représenter honnêtement l'identité
d'une entreprise fournisseur ni le résultat opérationnel/coût d'une recherche
provider. Deux tables minimales sont proposées, sans personne/contact.

### 12.1 `acquisition_supplier`

Responsabilité : identité Kivou et provenance d'une société candidate.

```text
supplier_ref                       PK, String(64)
provider                           String(32), NOT NULL
provider_organization_id           String(128), NOT NULL
display_name                       Text, NOT NULL
normalized_name                    Text, NOT NULL
primary_domain                     String(253), NULL
website_url                        Text, NULL
linkedin_company_url               Text, NULL
country_code                       String(2), NULL
location                           Text, NULL
industry                           Text, NULL
identity_status                    String(32), NOT NULL
identity_conflict_fingerprint      String(64), NULL
provider_observed_at               timestamptz, NOT NULL
source_fingerprint                 String(64), NOT NULL
created_at / updated_at             timestamptz, NOT NULL
```

Contraintes/indexes : unique `(provider, provider_organization_id)`, index
non-unique sur `primary_domain`, index sur `identity_conflict_fingerprint`,
format/checks applicatifs stricts et timestamps timezone-aware. Le domaine ne
porte aucune unicité.

### 12.2 `supplier_discovery_run`

Responsabilité : audit étroit d'une exécution Apollo, pas queue ni Event Bus.

```text
discovery_run_id                    PK, String(64)
signal_ref                          String(256), NOT NULL
policy_evaluation_id                FK policy_evaluation, NOT NULL
provider                            String(32), NOT NULL
search_profile_version              String(64), NOT NULL
search_profile_fingerprint          String(64), NOT NULL
search_profile                      JSON borné, NOT NULL
provider_request_fingerprint        String(64), NOT NULL
requested_max_pages / per_page      Integer, NOT NULL
candidate_cap                       Integer, NOT NULL
pages_requested                     Integer, NOT NULL
provider_credit_units_estimated     Integer, NOT NULL
provider_credit_units_observed      Integer, NULL
provider_total_entries              Integer, NULL
partial_results_only                Boolean, NULL
records_returned / accepted         Integer, NOT NULL
records_rejected / duplicates       Integer, NOT NULL
opportunities_created               Integer, NOT NULL
started_at / completed_at           timestamptz
status                              String(32), NOT NULL
error_category / error_detail       bornés, NULL
retry_after                         timestamptz, NULL
correlation_id                      String(64), NOT NULL
```

Tous les compteurs ont un check `>= 0`. Statuts bornés : `STARTED`, `SUCCESS`,
`PARTIAL`, `FAILED`, `SEARCH_TOO_BROAD`. Indexes : `(signal_ref, started_at)`,
`(status, started_at)` et `policy_evaluation_id`. Le profil JSON ne contient
que le contrat Kivou sûr, jamais le body Apollo ni le secret.

### 12.3 Graphe

```text
0008_policy_gateway -> 0009_supplier_discovery
```

`0009_supplier_discovery` mesure 23 caractères et reste sous la limite Alembic
de 32. Aucun troisième tableau, aucune table contact/personne, aucun changement
aux migrations existantes.

## 13. Service et Policy Gateway

Flux proposé :

1. résoudre le seed public et construire le profil déterministe ;
2. construire une **nouvelle** `PolicyRequest` avec un `evaluation_id` neuf ;
3. appeler `PolicyGateway.evaluate_and_record()` immédiatement ;
4. si `decision.executable is not True`, terminer sans client/provider/run ;
5. créer un run `STARTED`, appeler Apollo avec les bornes fingerprintées ;
6. normaliser et persister chaque candidat dans une transaction bornée ;
7. créer l'AcquisitionOpportunity et son `next_action` dans la même transaction
   logique que l'acceptation du candidat ;
8. clôturer le run avec compteurs et statut explicites.

Une décision APPROVED n'est jamais passée à un worker ni réutilisée comme
token. Le service réalise sa propre évaluation fraîche et appelle Apollo sans
intervalle de queue. En `SHADOW`, la Policy Gateway peut enregistrer le
counterfactual, mais `executable=false` garantit **zéro requête Apollo**.

## 14. Hardening concurrent `evaluation_id`

Avant tout client Apollo, SPEC-020 ferme la course SPEC-019 avec un insert
atomique conditionnel compatible PostgreSQL et SQLite :

```text
INSERT policy_evaluation ... ON CONFLICT(evaluation_id) DO NOTHING
```

- si l'insert gagne, il suit les garanties d'audit existantes ;
- s'il perd, le gateway recharge `evaluation_id`, compare l'empreinte
  sémantique complète, puis retourne exactement la décision durable ;
- même ID + sémantique différente :
  `PolicyEvaluationIdempotencyConflict` ;
- aucun `IntegrityError` brut n'est une sortie normale ;
- un dialecte non pris en charge échoue fermé.

Pour un audit opportunity-scoped, l'insert et `POLICY_EVALUATED` restent dans
la transaction externe unique : une concurrence/version invalide ne laisse ni
ligne policy, ni événement partiel. La découverte `SIGNAL` n'a pas d'événement
acquisition associé, conformément à son scope pré-opportunité.

Une alternative par savepoint et interception d'`IntegrityError` est rejetée :
elle dépend davantage du dialecte et rend plus difficile la distinction entre
la course attendue et une autre violation d'intégrité.

## 15. Crédits, pagination et recherche trop large

Bornes MVP :

```text
default max_pages   1
hard max_pages      5
per_page            1..100
candidate_cap       <= 500
```

Hermes ne peut augmenter aucune borne. Chaque page suit l'ordre 1..N. Le client
s'arrête lorsque la page est vide, lorsque la pagination officielle indique la
fin, au candidate cap ou au max pages — jamais par boucle ouverte.

Les crédits provider sont enregistrés séparément du coût monétaire. Selon la
documentation actuelle, une page demandée vaut une unité estimée ; le compteur
réel disponible dans le workspace reste autoritaire. Aucune conversion
CHF/EUR n'est inventée. La Policy Gateway reçoit uniquement une estimation de
coût Kivou configurée et la quota Apollo autoritaire dans
`OperationalReadiness`.

La limite d'affichage Apollo de 50 000 n'est pas une cible. Limite de sécurité
proposée pour un profil : si `total_entries > 10_000` ou si
`partial_results_only=true`, le run devient `SEARCH_TOO_BROAD`, aucun candidat
n'est accepté et Kivou doit affiner sa configuration/profile. Hermes ne peut
relâcher les filtres.

## 16. Erreurs et succès partiel

Taxonomie client typée :

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

Un `429` n'est jamais un résultat vide. `Retry-After` est conservé seulement
s'il est valide et autoritaire ; sinon `retry_after=NULL`. Aucun retry
automatique n'est ajouté, afin de ne pas consommer des crédits en boucle. Un
nouveau run réévalue la politique.

Si la page 1 et ses candidats sont durablement persistés puis que la page 2
échoue, les faits sûrs restent. Le run devient `PARTIAL`, ne prétend jamais que
la couverture est complète, et un rerun repasse par la Policy Gateway. Les
upserts fournisseur et identités d'opportunité absorbent le replay, même si
l'ordre Apollo change. Avec le défaut d'une page, cette surface reste petite.

## 17. Atomicité et idempotence d'exécution

Le run est créé avant le réseau. Chaque candidat est traité dans une transaction
bornée : supplier upsert, détection de conflit de domaine, création éventuelle
de l'AcquisitionOpportunity et `NEXT_ACTION_SET`. Une défaillance d'un candidat
ne produit jamais une opportunité sans fournisseur.

Le fingerprint de run lie seed, profile et bornes. Un vrai rerun peut consommer
un nouveau crédit Apollo, mais il ne crée ni fournisseur, ni opportunité, ni
événement de création en double. Une organisation Apollo déjà vue est comptée
`duplicate` pour le run.

## 18. Sécurité et menace

- Apollo, les textes de marchés et sites sont des DATA non fiables ;
- Pydantic/contrats bornés refusent keys de secret/raisonnement caché, tailles,
  types et URL invalides ;
- l'URL du client et l'endpoint sont fixes ; aucune SSRF par paramètres ;
- aucun shell, callable, URL arbitraire ou filtre provider libre ;
- logs structurés sans headers/body complets ;
- timeout réseau fini, aucune boucle de retry ;
- la clé utilise la permission d'organisation-search minimale ;
- aucune donnée client ou PII personne ;
- Apollo ne peut modifier policy, autonomy, kill switch, score, Need Graph ou
  compliance ;
- seul `decision.executable=true` permet l'appel, et aucun exécuteur générique
  n'est introduit.

## 19. Plan TDD déterministe

### Policy

- `discover_suppliers` accepte le scope `SIGNAL`, target public et acquisition
  id NULL ;
- `SHADOW` et toute décision non exécutable : zéro appel provider ;
- denied : zéro appel ; approved/executable : un seul chemin provider ;
- même `evaluation_id` concurrent et même sémantique : une ligne durable et la
  même décision ; sémantique différente : conflit typé ;
- la découverte n'écrit pas un faux `POLICY_EVALUATED` acquisition.

### Profil

- mêmes faits/configuration -> même profil et fingerprint ;
- aucun argument Apollo brut venant d'Hermes ;
- page, taille, candidat et filtre bornés ; filtre inconnu rejeté ;
- aucune dépendance TargetICP/feedback/billing/materialized ownership.

### Client Apollo

- organisation valide, résultat vide et réponse malformed ;
- 401, 403, 429 avec/sans Retry-After, timeout, 5xx, erreur réseau ;
- pagination bornée, fin anticipée et `SEARCH_TOO_BROAD` ;
- chaînes/tableaux/payload bornés et absence de secret dans logs ;
- assertion que seul `/mixed_companies/search` est appelé et aucun endpoint
  people/enrichment.

### Identité et persistance

- replay même Apollo ID -> même `supplier_ref` ;
- même domaine + IDs conflictuels -> aucune fusion et conflit explicite ;
- domaine manquant reste NULL ; champs normalisés round-trip ;
- run SUCCESS/PARTIAL/FAILED/SEARCH_TOO_BROAD et compteurs ;
- aucune réponse brute/clé/PII persistée ;
- upgrade 0008 -> 0009, fresh -> head, contraintes/indexes, head unique et
  revision IDs <=32.

### Acquisition

- seed × supplier -> une opportunité ; replay -> même identité et aucun event
  dupliqué ;
- `supplier_ref` présent dès la création ; contact/campaign NULL ;
- état `DISCOVERED`, next action `find_decision_makers` ;
- aucun état SEND/READY/QUEUED, aucun contact/campagne ;
- rollback atomique supplier/opportunity en cas d'échec.

### Vie privée et side effects

- tests architecturaux interdisant imports/dépendances TargetICP, feedback,
  billing, People, email, SMTP, Instantly, Stripe, shell et executor ;
- fake provider obligatoire en CI ; aucune clé ou internet.

### Performance diagnostique

Mesurer localement 100 fixtures organisation : normalisation, upsert fournisseur,
création/replay des opportunités et audit du run. Aucun SLA ni cache ne sera
inventé à partir de cette mesure.

## 20. Fichiers attendus lors de l'implémentation

```text
src/signals/supplier_discovery/__init__.py
src/signals/supplier_discovery/contracts.py
src/signals/supplier_discovery/profile.py
src/signals/supplier_discovery/provider.py
src/signals/supplier_discovery/apollo.py
src/signals/supplier_discovery/identity.py
src/signals/supplier_discovery/store.py
src/signals/supplier_discovery/service.py

src/signals/policy/registry.py                 # scope/metadata, sans callable
src/signals/policy/store.py                    # race evaluation_id
src/signals/acquisition/store.py               # transaction externe étroite
src/signals/persistence/schema.py               # deux tables
src/signals/persistence/migrations/versions/
  0009_supplier_discovery_*.py

tests/supplier_discovery/*
tests/policy/*                                  # race/scope
tests/persistence/*                             # migration
docs/reports/2026-08-20-spec020-supplier-discovery-apollo.md
```

La liste est indicative et volontairement étroite. Aucun frontend, `ops/`,
worker, personne/contact, Event Bus ou exécuteur.

## 21. Réponses explicites

**Quel objet exact est `signal_ref` pour l'acquisition ?**

La référence namespacée de l'opportunité publique Kivou :
`procurement-opportunity:<opportunity_key>`. Elle se résout vers les faits
publics et n'est jamais un signal matérialisé client.

**Comment autoriser la découverte avant une AcquisitionOpportunity ?**

Avec `TargetScope.SIGNAL`, `target_ref=signal_ref` et
`acquisition_opportunity_id=NULL`. La décision est auditée dans
`policy_evaluation`, sans faux événement acquisition.

**Qu'est-ce que `supplier_ref` ?**

Une identité Kivou immuable et versionnée, dérivée du namespace provider et de
l'identifiant d'organisation Apollo. L'ID Apollo reste provenance.

**Comment traiter les doublons ?**

Même provider+ID retrouve la même ligne ; domaines identiques avec IDs
différents restent séparés et signalés en conflit ; aucune fusion fuzzy.

**Pourquoi une redécouverte ne duplique-t-elle pas les opportunités ?**

L'`identity_key` ne dépend que de `signal_ref × supplier_ref`, et le store
SPEC-018 impose son unicité/idempotence.

**Quelles données Apollo sont persistées ?**

Identité provider, nom, domaine/site/LinkedIn entreprise optionnels, localisation
et industrie bornées utiles, dates et fingerprints de provenance, plus audit
de run.

**Quelles données Apollo ne le sont pas ?**

Body brut, clé/headers, personnes, emails, téléphones, LinkedIn personnel,
intent/funding/jobs et champs sans nécessité SPEC-020.

## 22. Questions non bloquantes avant implémentation

Il n'existe aucune question d'architecture bloquante. L'implémentation devra
recevoir explicitement, sans valeur secrète dans Git :

- les quotas/permissions réels du workspace Apollo ;
- la configuration Kivou initiale de ciblage fournisseur et l'estimation de
  coût Policy Gateway ;
- une autorisation séparée si un smoke Apollo réel est souhaité. En l'absence
  de ces éléments, CI reste entièrement fake/offline et le mode SHADOW ne fait
  aucun appel.

## 23. Non-objectifs

Pas de People API, contact/PII, enrichissement organisation par défaut,
qualification, LLM ranking, Decision Engine, SEND/NO_SEND, campagne, email,
Instantly, compliance pays, frontend, Customer API, daemon, Celery, Redis,
DLQ, Event Bus, exécuteur générique, VPS ou déploiement.

## Verdict de design

SUPPLIER DISCOVERY DESIGN READY FOR REVIEW
