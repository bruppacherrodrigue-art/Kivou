# SPEC-023 — Deterministic Acquisition Decision Engine — Design

Date : 2026-08-20

Branche : `feat/spec023-decision-engine`

Base acquisition auditée : `55906b7da2ea965749cf97fcde5639608760e7a7`

`origin/main` observé au closeout : `25bc0ab22bd70819cbd71003c6222bd9ddedec87`

Alembic head : `0011_company_research`

Statut : design uniquement — aucune implémentation, migration ou modification du reducer

## 1. Verdict de conception

Le design est prêt pour revue superviseur. `decision-policy-v1` est une
matrice explicite, sans score, modèle appris, LLM ni réglage Hermes. Elle émet
seulement :

```text
SEND
REVIEW
NO_SEND
```

`HOLD` et `ENRICH` restent dans le domaine existant mais sont désactivés en v1 :
aucune condition temporaire assortie d'un réveil fiable, ni aucune nouvelle
action d'enrichissement bornée, n'existe dans le MVP.

Recommandations soumises au superviseur :

```text
max_send_age_days                 60, frontière inclusive
migration 0012                    OUI
table                             acquisition_decision_evaluation, une seule
nouvel EventType                  NON
extension DECISION_RECORDED       OUI, additive et compatible
acquisition-state-v2              NON
risk class Policy Gateway         PREPARATORY
provider/budget/send/compliance   non applicables
```

## 2. Entry gate vérifié

Le dépôt a été synchronisé depuis `main` avant la création de la branche :

```text
HEAD        55906b7da2ea965749cf97fcde5639608760e7a7
origin/main 55906b7da2ea965749cf97fcde5639608760e7a7
Alembic     0011_company_research
```

Le squash SPEC-022 est présent sur `main` et contient Supplier Discovery,
Contact Discovery, Company Research et `AcquisitionProspectPrebuild`. La
branche de design a été créée depuis ce SHA, pas depuis la branche SPEC-022.

Pendant le closeout, `origin/main` a avancé vers
`25bc0ab22bd70819cbd71003c6222bd9ddedec87` avec le squash P0-01 « Public
product proof and signal demo ». La divergence a été auditée avant toute
réconciliation : elle contient uniquement le frontend public et
`docs/reports/p0-01-eval`; aucun fichier `src/signals`, acquisition, policy,
persistence ou migration n'a changé. Elle ne modifie donc aucun contrat lu par
ce design. La PR est ouverte contre ce `main` courant et son diff reste limité
au présent rapport ; aucun rebase forcé n'a été effectué.

## 3. Objectif et limite métier

SPEC-023 prend une décision commerciale interne sur une opportunité déjà
préparée :

```text
READY_FOR_DECISION + evaluate_opportunity
        -> résolution de faits autoritaires locaux
        -> AcquisitionDecisionInput immuable
        -> proposition pure decision-policy-v1
        -> Policy Gateway fraîche, liée à la proposition exacte
        -> si exécutable : DECISION_RECORDED atomique
```

`SEND` signifie uniquement : « cette opportunité est commercialement éligible
à la préparation d'une campagne ». Il ne constitue ni une permission légale de
contact, ni une autorisation d'envoi, ni une validation mailbox, conformité ou
deliverability. La prochaine action est `prepare_campaign`, qui devra elle-même
passer de futurs contrôles frais.

Le composant ne prépare aucun message, ne crée aucune campagne et n'appelle
Apollo, Instantly, SMTP, le Web ou un LLM.

## 4. Audit du code autoritaire

### 4.1 State machine

Le code expose déjà `Decision.SEND`, `HOLD`, `ENRICH`, `NO_SEND` et `REVIEW`,
ainsi que `EventType.DECISION_RECORDED`. Depuis `READY_FOR_DECISION`, les
transitions existantes couvrent déjà les cinq états de décision. Aucun état
`QUALIFIED`, `FIT` ou `APPROVED_TO_SEND` n'est nécessaire.

Le reducer actuel de `DECISION_RECORDED` valide la décision, change `decision`
et `state`, puis copie reasons/evidence/confidence/`next_review_at`. Il ne
modifie pas `next_action`. Une décision laisserait donc la valeur obsolète
`evaluate_opportunity`. C'est le seul défaut de state-machine à corriger.

### 4.2 Profil SPEC-022 et bindings courants

Le chemin amont produit :

```text
state        = READY_FOR_DECISION
supplier_ref != NULL
contact_ref  != NULL
next_action  = evaluate_opportunity
```

`acquisition_company_profile` est indexé par opportunity et contient le
`signal_ref`, les bindings supplier/contact, `acquisition-prospect-prebuild-v1`,
son fingerprint, `company-size-v1`, la complétude, les research gaps et des
snapshots sûrs de l'identité fournisseur et du rôle contact. Il ne contient
aucun score.

Le supplier courant est `PROVIDER_IDENTIFIED` ou `DOMAIN_CONFLICT`. Ce dernier
est une incertitude d'identité, pas la preuve d'un mauvais prospect. Le contact
durable est supplier-bound et Apollo `PROVIDER_VERIFIED`. Le Decision Engine ne
lit que ses refs, états de vérification et rôle/version ; jamais son nom ou son
email.

### 4.3 Résolution publique

Le resolver SPEC-020 lit uniquement `opportunity_representation`,
`contract_award` et `source_event`. Il choisit une attribution représentative
de façon déterministe par :

1. complétude décroissante ;
2. publication la plus récente ;
3. `award_key` croissant.

Il produit déjà `source-event:<event-key>` et
`contract-award:<award-key>`, sans `materialized_signal` client. Cependant,
`resolve_acquisition_seed()` calcule ensuite Contract Understanding et Need
Graph. La future implémentation doit extraire dans le même module un noyau
partagé `resolve_public_acquisition_context()` conservant exactement la
sélection ci-dessus. SPEC-020 continuera d'ajouter understanding/Need Graph ;
SPEC-023 n'utilisera que le noyau public et ne recalculera aucun fit fournisseur.

### 4.4 Recency actuelle

`signals.recency.policy` sépare déjà `award_date`, notification, publication et
`discovered_at`. Son statut primaire sert toutefois au feed : une notification
récente peut y prendre la parole avant une attribution ancienne. Ce n'est pas
la sélection unique exigée ici.

SPEC-023 réutilise les faits bruts et la tolérance publique existante d'un jour
entre award et publication, mais définit `acquisition-recency-v1`. Aucun seuil
du feed ou gold commercial n'est repris silencieusement.

### 4.5 Policy Gateway actuelle

`evaluate_opportunity` est déjà `PREPARATORY` et `OPPORTUNITY`, mais n'exige
que `SIGNAL` et `PUBLIC_EVIDENCE`. Son profil de preuves doit être précisé. Le
Policy Gateway append un `POLICY_EVALUATED` state-neutral, donc avance le stream
`V -> V+1`.

## 5. Frontière client et gouvernance

Le futur package `signals.decision_engine` n'a aucune dépendance sur :

```text
TargetICP
customer/account preferences
customer feedback or contacted/relevant flags
billing or entitlements
MatchingEngine
materialized_signal ownership
customer scores or another customer's behavior
```

Un test d'architecture AST/import l'interdit. Hermes ne fournit ni décision,
seuil, score, règle, reason code ni override.

## 6. Actionnabilité et intégrité

Avant une nouvelle Policy Gateway, le service exige :

```text
opportunity.state       == READY_FOR_DECISION
opportunity.next_action == evaluate_opportunity
supplier_ref            présent
contact_ref             présent

company profile présent
profile opportunity/supplier/contact/signal refs exacts
prebuild_version         == acquisition-prospect-prebuild-v1
size_band_version        == company-size-v1

supplier courant présent et lié
contact courant présent et lié au supplier
contact PROVIDER_VERIFIED par apollo
provider_email_status    == verified
role_tier                1..4
```

Le signal doit avoir le format exact
`procurement-opportunity:<opportunity_key>` et se résoudre vers une attribution
et un événement publics existants.

Les défauts suivants sont des erreurs système typées avant policy, pas des
décisions `REVIEW` :

```text
DecisionNotActionable
DecisionCompanyProfileMissing
DecisionInputVersionUnsupported
DecisionBindingConflict
DecisionPublicContextNotResolvable
```

Ils produisent zéro `policy_evaluation`, zéro decision audit et zéro
`DECISION_RECORDED`. `REVIEW` reste réservé à une ambiguïté métier sur des
données valides.

## 7. Recency `acquisition-recency-v1`

### 7.1 Dates et précédence

Les trois dates restent distinctes :

```text
AWARD_DATE
    si award_date est présente

CONTRACT_NOTIFICATION_DATE
    uniquement si award_date est absente

PUBLICATION_DATE
    uniquement si award_date et notification sont absentes

UNRESOLVED
    si les trois sont absentes
```

Une date de rang supérieur présente mais invalide n'est jamais remplacée par
une date inférieure : elle produit `PUBLIC_TIMING_INCONSISTENT` et `REVIEW`.
`publication_date` date un document ; une valeur datetime est convertie en jour
UTC explicitement. Un datetime naïf est une erreur d'input.

`discovered_at` ne participe jamais à la base, à l'âge ou au fingerprint. Une
découverte récente ne rajeunit donc jamais une attribution.

### 7.2 Calcul et contradictions

```text
as_of_date = evaluated_at converti en UTC, puis date calendrier
age_days   = as_of_date - recency_date
```

Le pure evaluator ne lit aucune horloge. Une date sélectionnée après
`as_of_date` mène à `REVIEW`. Une `award_date` postérieure à sa propre
publication de plus d'un jour mène aussi à `REVIEW`. Les dates d'exécution ne
servent jamais à inventer un calendrier d'achat.

Avec le seuil proposé de 60 jours :

```text
age_days <= 60  dans la fenêtre
age_days > 60   hors fenêtre
```

## 8. Comparaison du seuil commercial

Le seuil doit être gelé avant tout benchmark commercial. Aucun gold, verdict
historique ou taux cible ne sert à le choisir.

| Seuil | Interprétation métier | Fausse fraîcheur | Opportunités manquées |
|---|---|---|---|
| 30 jours | Immédiat post-attribution | Faible | Élevées si publication et qualification prennent plusieurs semaines |
| 60 jours | Fenêtre courte incluant la phase « aging » Kivou | Modérée | Modérées ; laisse fonctionner SPEC-020/021/022 |
| 90 jours | Trimestre complet | Élevée ; relations fournisseur possiblement déjà établies | Faibles |

Recommandation : **60 jours inclusifs**. Trente jours peuvent périmer un signal
pendant le pipeline ; quatre-vingt-dix jours présentent trop facilement comme
active une attribution ancienne. Soixante jours reprend la borne haute nommée
« aging » sans reprendre le verdict de feed et sans tuning sur des golds.

## 9. `DecisionPolicyConfig`

Contrat callable-free `decision-policy-v1` :

```text
policy_version                       decision-policy-v1
recency_version                      acquisition-recency-v1
max_send_age_days                    60 (proposé)
accepted_recency_bases               AWARD_DATE,
                                      CONTRACT_NOTIFICATION_DATE,
                                      PUBLICATION_DATE
future_date_tolerance_days           0
award_publication_tolerance_days     1
provider_identified_behavior         CONTINUE
domain_conflict_behavior             REVIEW
supplier_snapshot_mismatch_behavior  REVIEW
limited_research_behavior            CONTINUE
size_band_behavior                   CONTEXT_ONLY
contact_role_tier_behavior           CONTEXT_ONLY
hold_enabled                         false
enrich_enabled                       false
reason_code_version                  decision-reasons-v1
config_fingerprint                   SHA-256 canonique
```

Le fingerprint couvre chaque paramètre. Il exclut date d'exécution,
opportunity, evaluation ID et données métier.

## 10. `AcquisitionDecisionInput`

Contrat immuable `acquisition-decision-input-v1`, sans PII :

```text
input_version
acquisition_opportunity_id
signal_ref
supplier_ref
contact_ref

company_prebuild_version
company_prebuild_fingerprint
size_band_version

profile_supplier_identity_status
current_supplier_identity_status
profile_contact_role_profile_version
profile_contact_role_tier
current_contact_role_profile_version
current_contact_role_tier
current_contact_verification_state/provider/status

representative_award_key
source_event_key
public_evidence_refs
public_context_fingerprint

award_date
contract_notification_date
publication_date
recency_basis
recency_date
as_of_date
age_days

research_completeness
research_gaps
size_band

decision_policy_version
decision_policy_config_fingerprint
decision_input_fingerprint
```

Le snapshot et les valeurs courantes sont tous deux explicites. Une divergence
de supplier identity depuis la recherche produit `REVIEW`. Une évolution du
role tier, si le même contact reste lié et verified, est auditée mais ne rejette
pas à elle seule le prospect ; le tier 4 est valide.

`decision_input_fingerprint` couvre tous ces champs sauf lui-même en JSON
canonique. Toute modification du prebuild, supplier/contact sûrs, représentant
public, dates, `as_of_date` ou configuration change l'empreinte.

## 11. Matrice `decision-policy-v1`

Le pure evaluator applique cet ordre fixe :

1. snapshot supplier différent du supplier courant :
   `REVIEW / SUPPLIER_IDENTITY_CHANGED_SINCE_RESEARCH` ;
2. supplier courant `DOMAIN_CONFLICT` :
   `REVIEW / SUPPLIER_DOMAIN_CONFLICT` ;
3. recency `UNRESOLVED` : `REVIEW / RECENCY_UNRESOLVED` ;
4. recency future ou contradiction publique :
   `REVIEW / PUBLIC_TIMING_INCONSISTENT` ;
5. `age_days > max_send_age_days` :
   `NO_SEND / SIGNAL_OUTSIDE_ACQUISITION_WINDOW` ;
6. sinon : `SEND / SIGNAL_WITHIN_ACQUISITION_WINDOW`.

Pour `SEND`, les reasons complémentaires sont ajoutées dans un ordre constant :

```text
SUPPLIER_IDENTITY_ACCEPTABLE
VERIFIED_COMMERCIAL_CONTACT
ACQUISITION_PREBUILD_AVAILABLE
```

Une base de fallback ajoute exactement `RECENCY_NOTIFICATION_FALLBACK` ou
`RECENCY_PUBLICATION_FALLBACK`. La liste est construite depuis des branches
ordonnées, jamais depuis l'itération d'un set/dict. Maximum proposé : 8 codes.
Il n'existe aucun texte libre ou raisonnement narratif.

`LIMITED`, un size band quelconque ou un role tier 4 ne changent jamais la
décision seuls. Ces faits restent dans l'input pour audit et analytics futures.

## 12. HOLD et ENRICH réservés

### HOLD désactivé

Aucune condition MVP ne possède une cause temporaire, un `next_review_at`
défendable et un réveil sûr. Un signal ancien ne redevient pas frais en
attendant ; une panne provider est une erreur amont. V1 n'émet jamais `HOLD`.

### ENRICH désactivé

SPEC-022 a déjà consommé la recherche corporate disponible. Aucun second
enrichissement borné et différent n'est défini. Émettre `ENRICH` créerait une
boucle vers le même appel. V1 n'émet jamais `ENRICH`.

Les enums et transitions existants restent disponibles pour de futurs workflows
explicitement conçus.

## 13. Proposition pure

```text
evaluate_decision(
    AcquisitionDecisionInput,
    DecisionPolicyConfig,
) -> AcquisitionDecisionProposal
```

La proposition contient :

```text
proposed_decision
reason_codes
evidence_refs
next_action
next_review_at = NULL
decision_input_fingerprint
decision_policy_version
proposal_fingerprint
confidence = NULL
```

Mappings exacts :

```text
SEND     -> prepare_campaign
REVIEW   -> request_human_review
NO_SEND  -> NULL
```

Le pure evaluator n'a aucun accès DB, réseau, horloge, UUID ou random. Aucune
confiance numérique n'est inventée.

## 14. Evidence refs

La liste canonique, ordonnée par type défini, contient au maximum :

```text
contract-award:<award_key>
source-event:<event_key>
acquisition-company-profile:<opportunity_id>
acquisition-supplier:<supplier_ref>
acquisition-contact:<contact_ref>
```

Elle ne contient ni email, nom, payload Apollo, document brut ou texte libre.
Les reason codes disent pourquoi ; ces refs disent quels records durables
soutiennent la proposition.

## 15. Quatre empreintes distinctes

### 15.1 `decision_policy_config_fingerprint`

SHA-256 du contrat callable-free complet `decision-policy-v1`.

### 15.2 `decision_input_fingerprint`

SHA-256 de tous les faits et dérivations décisionnels, dont prebuild, bindings
courants, attribution représentative, dates, recency, `as_of_date` et config.

### 15.3 `proposal_fingerprint`

SHA-256 de : input fingerprint, décision, reasons ordonnées, evidence refs
ordonnées, next action, next review et policy version.

### 15.4 `PolicyRequest.action_fingerprint`

SHA-256 de :

```text
command = evaluate_opportunity
target_ref = acquisition-opportunity:<id>
acquisition_opportunity_id
supplier_ref
contact_ref
proposal_fingerprint
```

Le Policy Gateway lie son audit à la proposition exacte. La version de stream
reste dans `PolicyRequest.expected_opportunity_version` et son semantic
fingerprint global ; elle n'est pas confondue avec la proposition métier.

## 16. Policy Gateway

Profil recommandé pour `evaluate_opportunity` :

```text
risk_class              PREPARATORY
target_scope            OPPORTUNITY
required_evidence       PUBLIC_OPPORTUNITY
                        PUBLIC_EVIDENCE
                        ACQUISITION_PROSPECT_PREBUILD
                        VERIFIED_CONTACT
                        DECISION_INPUT
uses_budget             false
uses_volume             false
uses_provider_quota     false
requires_control_plane  false
uses_send_controls      false
requires_compliance     false
```

`RECENT_SIGNAL` n'est pas une policy evidence : un signal ancien doit atteindre
le Decision Engine pour devenir honnêtement `NO_SEND`.

`PREPARATORY` est approprié car l'action ne contacte personne, ne crée aucune
campagne et ne mute aucun provider. Elle peut produire l'état commercial
interne `SEND`, mais `prepare_campaign` et les actions externes resteront
derrière de nouvelles policies fraîches. Coût et volume proposés valent zéro ;
quota provider, mailbox, send window, budget et conformité sont hors sujet.

## 17. Orchestration et crash window

Le service futur suit exactement :

1. chercher une `acquisition_decision_evaluation` par `evaluation_id` ;
2. si elle existe, valider ses bindings et la retourner, sans nouvelle policy ;
3. si `policy_evaluation` existe mais pas la decision audit, lever
   `DecisionEvaluationRequiresFreshAttempt` ;
4. lire et valider opportunity/profile/supplier/contact/public context ;
5. construire l'input depuis `evaluated_at` explicite ;
6. calculer la proposition pure ;
7. construire une `PolicyRequest` fraîche sur la proposition ;
8. Policy Gateway append `POLICY_EVALUATED`, donc `V -> V+1` ;
9. si non-exécutable, persister le proposal audit `POLICY_BLOCKED`, sans event
   business ;
10. si exécutable, revalider puis enregistrer audit + `DECISION_RECORDED` dans
    une transaction unique.

Le service n'accepte jamais un ancien `PolicyDecision` comme capability.

Si une `policy_evaluation` existe sans decision audit, l'ancienne décision
policy n'est pas rejouée. Le caller doit fournir un nouvel `evaluation_id`,
relire l'état et recalculer input, proposal et policy.

## 18. SHADOW et policy blocked

En SHADOW :

- l'input et la proposition pure sont calculés ;
- Policy Gateway produit son audit counterfactual ;
- la table de décision conserve proposition et statut policy avec
  `disposition=POLICY_BLOCKED` ;
- aucun `DECISION_RECORDED` n'est append ;
- `state`, `decision` et `next_action` restent inchangés.

Toute policy non-exécutable suit la même règle d'absence de mutation. Le proposal
audit ne constitue jamais une autorisation réutilisable.

## 19. Migration 0012 : décision et justification

Migration recommandée : **OUI**.

L'option sans migration est insuffisante :

- `DECISION_RECORDED` ne doit pas exister en SHADOW ou policy blocked ;
- `policy_evaluation` conserve l'action fingerprint mais pas la décision
  proposée, sa recency, ses reasons métier ou ses evidence refs ;
- reconstruire plus tard depuis des projections mutables ne serait pas l'audit
  du moment évalué.

Une table étroite conserve donc la proposition, notamment quand elle ne peut
pas modifier le workflow. Elle n'est ni queue, score store, feature store ni
second Event Bus.

Après approbation seulement :

```text
0011_company_research
    ->
0012_decision_engine
```

`0012_decision_engine` respecte la limite Alembic de 32 caractères et crée une
seule table.

## 20. `acquisition_decision_evaluation`

Schéma proposé :

```text
decision_evaluation_id              VARCHAR(64) PK
acquisition_opportunity_id          FK RESTRICT, NOT NULL
policy_evaluation_id                FK policy_evaluation RESTRICT,
                                    UNIQUE, NOT NULL

decision_input_version              VARCHAR(64)
decision_input_fingerprint          VARCHAR(64)
decision_input                      JSON borné, PII-free
company_prebuild_fingerprint        VARCHAR(64)

representative_award_key            VARCHAR(64)
recency_basis                       AWARD_DATE |
                                    CONTRACT_NOTIFICATION_DATE |
                                    PUBLICATION_DATE | UNRESOLVED
recency_date                        DATE nullable
as_of_date                          DATE NOT NULL
age_days                            INTEGER nullable

decision_policy_version             VARCHAR(64)
decision_policy_config_fingerprint  VARCHAR(64)

proposed_decision                   SEND | REVIEW | NO_SEND
reason_codes                        JSON, 1..8
evidence_refs                       JSON, 1..16
proposed_next_action                VARCHAR(100) nullable
proposed_next_review_at             NULL en v1
proposal_fingerprint                VARCHAR(64)

policy_status                       VARCHAR(32)
policy_counterfactual_status        VARCHAR(32) nullable
expected_post_policy_version        INTEGER >= 2

disposition                         POLICY_BLOCKED | RECORDED
recorded_event_id                   FK acquisition_event RESTRICT,
                                    UNIQUE, nullable
created_at                          timestamptz
```

`decision_evaluation_id` est dérivé stablement par Kivou depuis le policy
evaluation ID ; le pure evaluator ne génère aucun ID.

Contraintes : `RECORDED` exige un event ID et `POLICY_BLOCKED` l'interdit ;
`UNRESOLVED` exige date/âge nuls, les autres bases les exigent ; le mapping
décision/next action est exact ; `next_review_at` est nul en v1. Aucune colonne
email, nom, score ou raisonnement libre.

La table est append-only par policy evaluation. Même ID + même proposal
fingerprint retourne l'existant ; une autre sémantique produit
`DecisionEvaluationIdempotencyConflict`.

## 21. Extension additive `DECISION_RECORDED`

Aucun nouvel `EventType` n'est requis. Pour un nouvel événement SPEC-023 :

```json
{"decision":"SEND","next_action":"prepare_campaign"}
```

Règles exactes :

```text
SEND     exige next_action == prepare_campaign
REVIEW   exige next_action == request_human_review
NO_SEND  exige next_action == null
```

Le reducer change `decision`, `state` et `next_action` atomiquement. Aucun
second `NEXT_ACTION_SET` n'est produit.

Compatibilité : si la clé `next_action` est absente, le reducer exécute
strictement le chemin historique et ne touche pas cette valeur. Tous les
streams pré-SPEC023 replayent donc vers la même projection. Si la clé est
présente, la nouvelle validation s'applique. Les événements inconnus continuent
à échouer fermés.

C'est une extension additive de `acquisition-state-v1`, pas un changement du
sens historique. Aucun `acquisition-state-v2` n'est requis.

## 22. Transaction exécutable

Supposons le stream initial `V`. Policy Gateway append son audit en `V+1`.
Une transaction caller-owned unique doit ensuite :

1. lock/reload l'opportunité ;
2. exiger stream `V+1`, `READY_FOR_DECISION`, `evaluate_opportunity` et bindings
   inchangés ;
3. relire supplier, contact et company profile ;
4. résoudre le contexte public dans une vue transactionnelle cohérente ;
5. reconstruire input et proposition avec le même `as_of_date` et la même
   config ;
6. exiger les mêmes input/proposal fingerprints ;
7. append `DECISION_RECORDED` avec une idempotency key dérivée de la policy
   evaluation ;
8. insérer l'audit `RECORDED` avec l'event ID ;
9. commit.

Le stream final vaut `V+2`. Si l'insert audit échoue, event et projection sont
rollback. Si l'append échoue, aucune ligne `RECORDED` n'est committée.

PostgreSQL doit utiliser une transaction sérialisable ou équivalente pour que
le phantom d'une nouvelle représentation publique pouvant changer le
representative award abort/retry la transaction. SQLite utilise sa transaction
d'écriture compatible. Une sérialisation échouée impose une nouvelle evaluation
ID, jamais le replay d'une autorisation.

## 23. Concurrence et changement d'input

Après policy, toute divergence de stream/action, supplier/contact binding,
verification du contact, prebuild fingerprint, supplier identity, contact role,
representative award, dates publiques ou fingerprints annule la transaction
avec `DecisionInputChanged` ou `OpportunityConcurrencyConflict`.

Aucune décision stale n'est enregistrée. La policy evaluation demeure un audit ;
le caller reprend avec une nouvelle evaluation ID et des inputs frais.

Cas d'idempotence :

```text
decision audit existe pour evaluation_id
    -> vérifier bindings/fingerprints et retourner l'existant
    -> zéro nouvelle policy, zéro event

policy_evaluation existe mais decision audit absent
    -> DecisionEvaluationRequiresFreshAttempt
    -> nouvel evaluation_id obligatoire

même evaluation_id + proposition différente
    -> conflit explicite, aucune mutation
```

Pour une policy bloquée, `POLICY_BLOCKED` est écrit immédiatement après Policy
Gateway. Une coupure entre les deux laisse volontairement le cas « policy sans
decision audit », traité par une tentative fraîche.

## 24. Signification stricte des sorties

`confidence` reste `NULL`. Il n'existe aucun score ou probabilité.

`NO_SEND` signifie exclusivement qu'un input valide établit une date hors de
la fenêtre gelée. Il ne signifie jamais panne provider, policy refusée, DB
manquante ou version inconnue.

`REVIEW` signifie une ambiguïté métier bornée : conflit/changement d'identité
supplier, recency non résolue ou timing public incohérent. Il n'est pas une
poubelle pour erreurs techniques.

`LIMITED`, taille, industrie, année de fondation, description, keywords et rôle
tier 4 ne sont pas des hard gates v1.

## 25. Plan TDD après approbation

### Entry et actionnabilité

- profile SPEC-022 obligatoire ;
- seulement `READY_FOR_DECISION + evaluate_opportunity` ;
- refs supplier/contact exactes ;
- contact Apollo provider-verified ;
- versions prebuild/size supportées ;
- chaque défaut avant policy et sans mutation.

### Public input et recency

- parsing strict `procurement-opportunity:` ;
- representative award stable selon l'algorithme existant ;
- evidence refs stables ;
- award, puis notification, puis publication ;
- date supérieure présente mais invalide non remplacée ;
- `discovered_at` n'établit jamais la fraîcheur ;
- absence de clock -> REVIEW ; futur/contradiction -> REVIEW ;
- limites 59/60/61 ; date UTC explicite.

### Pure matrix

- provider identified + récent -> SEND ;
- domain conflict -> REVIEW ;
- supplier snapshot/current mismatch -> REVIEW ;
- unresolved timing -> REVIEW ;
- stale -> NO_SEND ;
- LIMITED, size band ou tier 4 seuls ne bloquent pas SEND ;
- HOLD et ENRICH jamais émis ;
- reasons non vides, bornés, ordonnés, sans texte libre.

### Fingerprints

- même input logique -> mêmes fingerprints ;
- changement `as_of_date`, prebuild, supplier state, award ou config -> input
  fingerprint différent ;
- changement décision/reasons/next action -> proposal fingerprint différent ;
- action fingerprint lie opportunity + proposal ;
- les quatre fingerprints restent distincts.

### State machine

- SEND -> `SEND + prepare_campaign` ;
- REVIEW -> `REVIEW + request_human_review` ;
- NO_SEND -> `NO_SEND + NULL` ;
- aucun `evaluate_opportunity` stale ;
- historique `DECISION_RECORDED` sans clé rejoué à l'identique ;
- événement inconnu fail closed ; state-v1 inchangé.

### Policy, audit et crash

- profil opportunity/preparatory exact ;
- absence de budget/provider/mailbox/send/compliance gates ;
- action fingerprint exact ;
- SHADOW et blocked conservent proposal audit sans business event ;
- policy exists/audit absent -> nouvelle ID ;
- même ID identique -> une ligne ; sémantique différente -> conflit.

### Atomicité et concurrence

- audit `RECORDED` + event + projection atomiques ;
- chaque write failure injectée rollback tout ;
- changement opportunity/supplier/contact/profile/public context après policy
  empêche la décision ;
- race same evaluation : un event/audit, aucune `IntegrityError` brute.

### Architecture, privacy, side effects, migration

- aucun import TargetICP/customer/matching/billing/feedback ;
- aucun nom/email/PII dans input, audit ou event ;
- zéro Apollo, Instantly, SMTP, crawler, Web, LLM ou campaign creation ;
- fresh DB -> `0012_decision_engine` ; `0011 -> 0012` ; une seule head/table ;
- downgrade propre.

### Performance

Diagnostic de 1 000 inputs synthétiques : input fingerprint, pure evaluation et
proposal fingerprint ; total et médiane, sans DB et sans SLA inventé.

## 26. Fichiers futurs attendus

Après approbation seulement :

```text
src/signals/decision_engine/__init__.py
src/signals/decision_engine/contracts.py
src/signals/decision_engine/input.py
src/signals/decision_engine/policy.py
src/signals/decision_engine/evaluator.py
src/signals/decision_engine/store.py
src/signals/decision_engine/service.py

src/signals/supplier_discovery/seed.py
src/signals/acquisition/state.py
src/signals/policy/registry.py
src/signals/persistence/schema.py
src/signals/persistence/migrations/versions/0012_decision_engine.py

tests/test_decision_engine_contracts.py
tests/test_decision_engine_input.py
tests/test_decision_engine_evaluator.py
tests/test_decision_engine_store.py
tests/test_decision_engine_service.py
tests/test_decision_engine_architecture.py
tests/test_decision_engine_migration.py
tests/test_acquisition_state.py
```

Aucun de ces fichiers n'est créé pendant le design pass.

## 27. Réponses explicites aux 30 questions

1. **SEND ?** Éligibilité commerciale interne à préparer une campagne.
2. **Pourquoi pas autorisation email ?** Aucun contrôle conformité, mailbox,
   fenêtre d'envoi ou mutation provider n'a été exécuté ; les actions futures
   exigent une policy fraîche.
3. **NO_SEND ?** Un signal valide dont `age_days` dépasse le seuil gelé.
4. **REVIEW ?** Conflit/changement d'identité supplier, recency non résolue ou
   timing public incohérent.
5. **V1 émet HOLD ?** Non.
6. **V1 émet ENRICH ?** Non.
7. **Pourquoi ?** Ni réveil fiable ni nouvelle action d'enrichissement bornée ;
   les émettre créerait attente indéfinie ou boucle.
8. **Base recency ?** Award, puis notification si award absente, puis
   publication si les deux précédentes sont absentes.
9. **`discovered_at` établit la fraîcheur ?** Non, jamais.
10. **Seuil recommandé ?** 60 jours inclusifs.
11. **Pourquoi ?** Compromis produit entre pipeline trop court à 30 jours et
    fausse fraîcheur trimestrielle à 90, sans tuning sur golds.
12. **LIMITED empêche SEND ?** Non, pas à lui seul.
13. **La taille détermine SEND ?** Non.
14. **Tier 4 empêche SEND ?** Non.
15. **DOMAIN_CONFLICT ?** REVIEW.
16. **Résolution publique ?** Noyau partagé du resolver SPEC-020 sur
    opportunity representation/award/event, sans customer rows ni Need Graph.
17. **`decision_input_fingerprint` ?** SHA-256 canonique de chaque input pouvant
    modifier le verdict, config comprise.
18. **`proposal_fingerprint` ?** SHA-256 de l'input fingerprint et de la sortie
    exacte : décision, reasons, evidence et action suivante.
19. **Binding Policy ?** `action_fingerprint` contient command, opportunity
    bindings et proposal fingerprint.
20. **SHADOW ?** Proposition et audits durables, aucun business event ni
    transition.
21. **Migration 0012 ?** Oui.
22. **Pourquoi les tables actuelles sont insuffisantes ?** Policy ne garde pas
    le proposal structuré et l'event ne doit pas exister quand policy bloque.
23. **Comment NO_SEND clear `next_action` ?** Le nouveau payload impose
    `next_action=null`, projeté dans le même event.
24. **Comment SEND obtient `prepare_campaign` ?** Même payload/event atomique,
    mapping strict.
25. **Extension additive du reducer ?** Oui.
26. **State-v1 compatible ?** Oui : absence historique de la clé conserve le
    chemin exact actuel.
27. **Input changé après policy ?** Rollback, erreur typée, nouvelle evaluation
    ID requise.
28. **Policy existe, commit absent ?** L'ancien APPROVED n'est pas réutilisé ;
    tentative fraîche obligatoire.
29. **PII lue/persistée ?** Aucune ; seules refs et états sûrs sont lus.
30. **Appels externes ?** Aucun.

## 28. Question restante pour le superviseur

Une seule décision bloque le TDD :

```text
Approuver max_send_age_days = 60, frontière inclusive ?
```

Les autres choix sont fermés par ce design : migration 0012 à une table,
`SEND/REVIEW/NO_SEND` uniquement, aucun nouvel EventType, extension additive de
`DECISION_RECORDED`, `acquisition-state-v1` conservé et risk class
`PREPARATORY`.
