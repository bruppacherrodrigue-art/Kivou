# SPEC-021 — Contact Discovery + provider-verified business email

Date : 2026-08-20

Branche : `feat/spec021-contact-discovery-email`

Base `main` : `2216837d9884594b91f38cd3704fdb6b3234c985`

Commit de design : `046836ce57fe4afd0034a167d7fe48cc98fe49cb`

Commit exécutable R1 final : `3b8f198c4fd2be49906f3ce38cbe2f4cf71d9b82`

## Résultat

SPEC-021 implémente la découverte bornée d’un contact commercial dans une
entreprise fournisseur déjà connue, avec autorisation fraîche du Policy Gateway,
recherche Apollo People, classement Kivou déterministe, enrichissement séquentiel
et sélection d’un email professionnel dont le statut Apollo est exactement
`verified`.

Le composant ne contient aucun chemin d’envoi, de campagne, d’Instantly, de
téléphone, d’email personnel, de waterfall, de SMTP ou de décision SEND/NO_SEND.
Aucun appel Apollo réel n’a été effectué.

## Architecture livrée

Le flux est :

```text
AcquisitionOpportunity DISCOVERED / find_decision_makers
  -> préflight d’actionnabilité et d’idempotence
  -> Policy Gateway (nouvelle évaluation, version courante)
  -> contact_discovery_run STARTED durable
  -> Apollo People Search, 1 page / 25 résultats maximum
  -> classement commercial FR/EN déterministe
  -> Apollo People Enrichment séquentiel, 3 essais maximum
  -> transaction contact + CONTACT_SELECTED + ENRICHING + enrich_company
```

`DecisionMakerSearchProfile` ne contient pas
`expected_opportunity_version`. La version attendue reste une métadonnée de
contrôle du `PolicyRequest` et du run, et ne participe pas au profil fournisseur
ni à son empreinte.

## Rejeu Policy Gateway et fenêtre de crash

Le préflight applique cet ordre :

1. un run existe pour `evaluation_id` : retour du run durable, aucun nouvel audit
   de politique et aucun appel fournisseur ;
2. un `policy_evaluation` existe sans run :
   `ContactDiscoveryEvaluationRequiresFreshAttempt`, aucun appel fournisseur ;
3. sinon l’opportunité doit être `DISCOVERED`, avoir un `supplier_ref`, aucun
   `contact_ref`, et `next_action=find_decision_makers` ;
4. une nouvelle évaluation utilise la version de stream courante `V` ; son audit
   `POLICY_EVALUATED` produit `V+1` ;
5. seul le propriétaire du run `STARTED` peut appeler Apollo.

Le crash entre audit de politique et création du run ne réutilise donc jamais une
ancienne décision APPROVED. Le prochain essai exige un nouvel `evaluation_id` et
une nouvelle lecture de l’état courant.

Le retour d’un run existant est lui-même lié à l’opportunité, au `request_id`, à la
commande, au target de politique et à l’empreinte d’action. Une tentative de
réutilisation du même `evaluation_id` pour une autre target produit
`ContactRunIdentityConflict` sans exposer le run ni appeler le fournisseur.

## Policy Gateway

`find_decision_makers` reste `TargetScope.OPPORTUNITY` et porte les métadonnées :

- preuves requises : `SUPPLIER`, `CONTACT_SEARCH_PROFILE` ;
- budget : applicable ;
- quota fournisseur : applicable ;
- control plane fournisseur : requis ;
- contrôles mailbox/send-window : non applicables ;
- conformité outbound : non applicable dans SPEC-021.

SHADOW produit uniquement l’audit de politique : aucun run et aucun appel Apollo.
Un quota inconnu ou un control plane indisponible échoue fermé avant Apollo.

## Contrat Apollo exact

People Search : `POST /api/v1/mixed_people/api_search` avec uniquement :

- `organization_ids[]` égal à l’ID Apollo exact du fournisseur ;
- `person_titles[]` et `person_seniorities[]` issus du profil Kivou FR/EN ;
- `contact_email_status[]=verified` ;
- `include_similar_titles=false` ;
- `page=1` ;
- `per_page=25` au maximum.

Une différence textuelle du nom d’organisation renvoyé par Search est uniquement
diagnostique. L’identité employeur est contrôlée après enrichissement avec
`person.organization_id == acquisition_supplier.provider_organization_id`.

People Enrichment : `POST /api/v1/people/match`, identifié par l’ID People Search,
avec :

- `reveal_personal_emails=false` ;
- `reveal_phone_number=false` ;
- `run_waterfall_email=false` ;
- `run_waterfall_phone=false`.

Il n’existe ni Bulk Match, ni Contact Search, ni webhook, ni autre vérificateur.

## Profil commercial et classement

`decision-maker-search-v1` appartient à Kivou. Il cible en français et en anglais
les familles Sales, Commercial, Business Development, Revenue et, selon le rang,
Direction générale/Fondateur/Propriétaire. Il ne dérive pas les titres de la
catégorie opérationnelle du marché public.

Le classement pur utilise famille commerciale, titre exact, séniorité, titre
normalisé, ID fournisseur puis ordre borné. Aucun LLM et aucun attribut personnel
ou protégé ne participe au classement. Le contact retenu est le meilleur contact
acceptable dans l’ensemble Kivou borné, pas dans tout l’univers Apollo.

## Vérification et identité

Un contact est accepté uniquement si :

- l’ID enrichi égale l’ID demandé ;
- l’organisation enrichie égale le fournisseur Apollo ;
- l’email professionnel est syntaxiquement valide ;
- `email_status == verified`.

La normalisation durable est :

```text
verification_state = PROVIDER_VERIFIED
verification_provider = apollo
provider_email_status = verified
```

Il s’agit d’une vérification fournie par Apollo, pas d’une vérification indépendante
ni d’une garantie de délivrabilité.

`contact_ref` est une empreinte `contact-identity-v1` de
`provider + provider_person_id + supplier_ref`. L’email, le nom et LinkedIn ne sont
pas des identités. Une même personne chez un autre fournisseur reçoit donc une
autre identité d’emploi et ne corrompt pas l’historique existant.

Le compare-and-set des observations est déterministe :

- date plus récente : mise à jour des champs bornés ;
- même date et même empreinte : rejeu sans effet ;
- même date et empreinte différente : `ContactObservationConflict` ;
- date antérieure : aucune réécriture de l’observation plus récente.

## Migration 0010

Le head est linéaire :

```text
0009_supplier_discovery
  -> 0010_contact_discovery
```

La migration crée exactement deux tables :

- `acquisition_contact` : seule l’identité d’emploi sélectionnée, les métadonnées
  professionnelles minimales et la provenance de vérification ;
- `contact_discovery_run` : propriété du run, profil/empreintes, couverture,
  compteurs, crédits, résultat et erreurs typées.

`policy_evaluation_id` est unique et lié en `RESTRICT`. Le run `STARTED` est écrit
avant People Search. Il n’existe ni table candidate, ni historique d’email, ni
queue, ni table générique de personnes.

## CONTACT_SELECTED et compatibilité state-v1

`CONTACT_SELECTED` est une extension additive de `acquisition-state-v1`. Depuis
`DISCOVERED`, il exige un fournisseur existant, la correspondance exacte du
`supplier_ref` et l’absence de contact. Le reducer ne modifie que `contact_ref` et
les métadonnées communes de stream.

Les streams antérieurs à SPEC-021 rejouent bit-à-bit vers la même projection. Les
événements historiques inconnus restent rejetés. Aucun `acquisition-state-v2`
n’est requis.

Le payload durable de `CONTACT_SELECTED` accepte exactement `contact_ref` et
`supplier_ref`, tous deux bornés et normalisés. Toute clé supplémentaire, y compris
un email, un téléphone ou une réponse fournisseur, échoue avant journalisation.

## Transactions terminales

Après l’audit Policy Gateway, le succès verrouille/recharge la projection et exige
la version exacte `V+1`. Une seule transaction écrit :

```text
acquisition_contact
CONTACT_SELECTED                    V+2
STATE_TRANSITIONED -> ENRICHING     V+3
NEXT_ACTION_SET -> enrich_company   V+4
contact_discovery_run -> SUCCESS
```

Une erreur de contact, d’événement, de projection, de version ou de terminaison du
run annule l’ensemble. Le run préexistant est ensuite marqué FAILED dans une
transaction bornée distincte.

`NO_CANDIDATE`, `NO_VERIFIED_CONTACT` et `CONTACT_SEARCH_TOO_BROAD` n’inventent
aucun contact. Ils ajoutent atomiquement `request_human_review` et terminent le
run, sans changer l’état `DISCOVERED`. Une concurrence annule ce changement et
marque le run FAILED sans écraser le workflow.

## Couverture de recherche et crédits

Le run persiste `provider_total_entries`, `search_results_returned` et
`search_results_truncated`. Par exemple 80 résultats fournisseur pour 25 éléments
Kivou peut produire SUCCESS avec `search_results_truncated=true`; ce succès signifie
qu’un contact acceptable a été trouvé dans la fenêtre bornée, pas que la recherche
Apollo est exhaustive.

Au-delà de 250 résultats, `CONTACT_SEARCH_TOO_BROAD` termine sans enrichissement.
People Search est compté séparément des enrichissements. Le budget fournisseur
prévu est au maximum 3 unités email-only ; aucune unité monétaire n’est inventée et
les crédits observés ne sont renseignés que par une donnée fournisseur autoritative.

## R1 — Complétude fournisseur et intégrité du rôle courant

La complétude People Search échoue désormais fermée. Une réponse
`total_entries=0` avec `people=[]` reste un résultat vide valide. En revanche,
un total strictement positif avec une page vide et aucune ligne rejetée produit
`malformed_response / unexpected_empty_search_page`. Le run devient `FAILED` et
aucun événement `NEXT_ACTION_SET(request_human_review)` n'est ajouté. Ce contrôle
existe dans le client Apollo et à la frontière du service ; une page non vide
dont tous les éléments sont rejetés individuellement reste un `NO_CANDIDATE`
métier valide.

La documentation officielle Apollo People Enrichment consultée le 2026-08-20
confirme qu'un HTTP 200 peut ne contenir aucun enregistrement enrichi. Le client
accepte uniquement HTTP 200 avec le payload exact `{"person": null}` comme no-match et
retourne `None`; une clé absente, une liste, une chaîne ou toute autre structure
— y compris une clé supplémentaire — reste `malformed_response`. Un statut autre
que 200 échoue également avec `unexpected_http_status`. Un no-match incrémente les rejets et poursuit le
candidat suivant. Trois no-match bornés terminent en `NO_VERIFIED_CONTACT`, sans
contact fabriqué. Source officielle :
`https://docs.apollo.io/reference/people-enrichment` et OpenAPI publiée
`https://docs.apollo.io/openapi/apollo-rest-api.json`.

Le titre enrichi est maintenant l'observation de rôle courante. Un classificateur
pur unique est partagé entre le ranking Search et la validation Enrichment :

- titre enrichi commercial reconnu : nouveau titre normalisé et tier recalculés ;
- titre enrichi non commercial, par exemple `CTO` : candidat rejeté ;
- titre enrichi absent : fallback borné vers le titre Search courant documenté.

Le profil `decision-maker-search-v1`, utilisé avec
`include_similar_titles=false`, comprend aussi les variantes françaises
explicites `Directrice commerciale`, `Directrice des ventes`, `Directrice du
développement commercial`, `Directrice générale`, `Fondatrice`, `Dirigeante`,
`Responsable commerciale` et `Responsable du développement commercial`. Elles
utilisent les mêmes tiers que leurs familles de rôle ; aucun genre n'est inféré
et aucun classement ne dépend du genre.

## Minimisation et sécurité

Ne sont pas persistés : téléphone, email personnel, adresse/localisation personnelle,
photo, biographie, historique d’emploi, LinkedIn personnel, réponse Apollo brute,
headers ou listes de candidats. Les réponses externes sont des données non fiables,
strictement bornées et normalisées.

Le package n’importe ni `TargetICP`, ni `materialized_signal`, ni feedback client,
ni facturation. Il ne dépend d’aucune propriété privée d’un client.

Le client Apollo lit les réponses en streaming et interrompt la lecture dès que le
prochain chunk ferait dépasser la borne de 1 MiB. Le rejet ne dépend donc pas d’un
buffering préalable et non borné du corps externe.

## Tests et mesure locale

Tests déterministes ajoutés : profil FR/EN et variantes littérales, ranking,
paramètres Apollo, erreurs
401/403/429/timeout/5xx/réseau, données malformées, identité/CAS, propriété concurrente
du run, fenêtre de crash Policy Gateway, SHADOW, couverture tronquée, seuil 250,
employeur, trois enrichissements maximum, page Search vide incohérente, no-match
Enrichment documenté, revalidation du rôle courant, transactions succès/no-contact,
concurrence, migration et replay historique.

Mesure diagnostique locale : 100 fixtures de contact, chacune classée, normalisée
et persistée dans SQLite, ont pris `0.506961 s`. Aucun SLA n’est déduit de cette
mesure.

Gates locaux :

- backend : `3139 passed`, `0 skipped`, `415.79 s` ;
- Ruff : PASS ;
- `git diff --check` : PASS ;
- frontend : `84 passed` ;
- build : PASS ;
- typecheck : PASS ;
- lint : PASS.

## GitHub CI

GitHub Actions run R1 final `32369163866` sur le commit exécutable
`3b8f198c4fd2be49906f3ce38cbe2f4cf71d9b82` : SUCCESS.

- backend CI : `3139 passed`, `0 skipped`, Ruff PASS ;
- frontend CI : `84 passed`, build PASS, typecheck PASS, lint PASS.

La PR #16 reste DRAFT. Aucun appel Apollo réel, aucune migration distante et aucun
déploiement n’ont été exécutés.

## Fichiers modifiés

- `src/signals/contact_discovery/` ;
- extension additive de `src/signals/acquisition/` ;
- métadonnée `find_decision_makers` dans `src/signals/policy/registry.py` ;
- schéma Core et migration `0010_contact_discovery` ;
- tests déterministes SPEC-021 et attentes de head Alembic ;
- rapports/design/plan SPEC-021.

Diff stat du commit exécutable : `31 files changed, 3937 insertions(+), 84
deletions(-)`. `git status --porcelain` était vide immédiatement après ce commit ;
le seul changement du closeout suivant est cette mise à jour documentaire.

Diff stat R1 exécutable : `8 files changed, 307 insertions(+), 16 deletions(-)`.
Durcissement final du sentinel : `2 files changed, 32 insertions(+), 2 deletions(-)`.
`git status --porcelain` était vide immédiatement après le commit exécutable R1
final, avant ce closeout documentaire.
