# SPEC-010 — SaaS Persistence + Signal Materialization Foundation

**Rien n'est committé.** Aucun travail d'authentification, de frontend ni de
paiement n'est engagé.

> ## ⚠ TROIS SÉMANTIQUES CORRIGÉES PAR LE CLOSEOUT
>
> L'architecture de ce rapport est acceptée et inchangée. Trois points de
> détail y sont dépassés :
>
> * les colonnes de fraîcheur s'appellent désormais `materialized_*` — un statut
>   stocké est un **instantané**, et toute affirmation client passe par
>   `current_recency(as_of=…)` ;
> * `signal_key = f(opportunity_key, target_icp_id)` — la représentation source
>   n'est plus l'unité montrée au client, pour que BOAMP et DECP ne dupliquent
>   pas un même marché ;
> * `icp_id` devient `target_icp_id` : un signal appartient à un `TargetICP`
>   **possédé par un compte** (décision superviseur), et la révision suit
>   désormais une empreinte de contenu et non les seules versions de moteur.
>
> Voir `2026-08-18-spec010-closeout-recency-and-opportunity.md` — il fait foi
> pour le schéma et les identités.

---

## 1. REVUE D'ARCHITECTURE (§2)

Inspection menée avant toute écriture de code.

```text
structure          src/ layout, 12 paquets sous `src/signals`, build hatchling,
                   Python 3.12 fixé (`==3.12.*`)
dépendances        4 seulement — pydantic, httpx, defusedxml, pypdf
                   dev : pytest, ruff
abstraction BD     AUCUNE. Pas d'ORM, pas de driver, pas de pattern Repository.
migrations         AUCUNE.
framework HTTP     AUCUN. Les modules `live_smoke` sont des scripts, pas un service.
sérialisation      pydantic v2 — `CanonicalModel(frozen=True, extra="forbid")`,
                   `model_dump(mode="json")` / `model_validate`
persistance        des fichiers JSON : artefacts de recherche gelés et un cache
                   de vérification. Rien de relationnel.
qualité            ruff avec un jeu de règles très large (828 règles actives),
                   suite à 2 026 tests, zéro ignoré
```

**Où placer la persistance sans créer une seconde architecture.** Le dépôt a une
règle implicite lisible partout : le modèle canonique est pydantic, immuable, et
personne ne le contourne. Un ORM déclaratif obligerait chaque entité du domaine
à devenir aussi une entité de base — deux vérités pour un même objet, et la
tentation permanente d'écrire la logique métier du côté du stockage.

Le nouveau paquet `src/signals/persistence` est donc **en aval** du domaine :
il consomme des objets canoniques, il n'en définit aucun.

---

## 2. TECHNOLOGIE RETENUE (§3)

```text
SQLAlchemy 2.0 en mode CORE      tables et requêtes, jamais d'ORM
Alembic 1.19                     migrations versionnées
psycopg 3 (extra `postgres`)     pilote PostgreSQL de production
SQLite (stdlib)                  tests, sans aucun service à lancer
```

**Pourquoi Core et pas l'ORM.** Core donne exactement ce que §3 demande —
schéma versionné, transactions, portabilité de dialecte — sans demander au
domaine de changer de nature. Aucune classe de `signals.domain` ne devient une
entité persistée ; `materialize_signal` traduit, et la traduction est visible.

**Pourquoi Alembic plutôt qu'un lanceur maison.** §13 exige qu'une base se
reconstruise depuis zéro et interdit toute création de table hors mécanisme de
migration. Un lanceur maison, c'est soixante lignes à écrire *et* les bugs à
posséder ; Alembic est un outil, pas un framework, et il n'impose aucune
structure au reste du dépôt.

**Ce qui a été refusé.** SQLModel — il fusionne pydantic et l'ORM, donc
exactement la seconde architecture que §2 met en garde contre. `JSONB`,
`UUID`, les types `postgresql.*` — plus rapides en production, indisponibles en
test, et un test qui ne s'exécute pas ne garantit rien.

**PostgreSQL vérifié sans serveur.** Le DDL des quatre tables est compilé contre
le dialecte PostgreSQL dans la suite ordinaire, et un test refuse tout type
propre à un dialecte. La compatibilité de production est donc une propriété
testée à chaque exécution, pas une intention.

---

## 3. SCHÉMA (§4, §5)

Quatre tables, et une frontière que la base rend visible.

```text
FAITS PUBLICS                              INFÉRENCES
─────────────                              ──────────
source_event      la publication           materialized_signal
contract_award    le contrat attribué        compréhension, besoins plausibles,
evidence          l'ancrage vérifiable       pertinence ICP, score
```

```text
source_event          event_key (PK, = EventRef.key()), source_system,
                      source_notice_id, notice_version, source_country,
                      source_procedure_id, source_url, event_type,
                      published_at_raw, published_on, published_precision,
                      discovered_at, procedure_buyers, created_at

contract_award        award_key (PK), event_key (FK), source_award_id,
                      lot_identifier, lot_title, contract_reference, title,
                      description, cpv_main, cpv_check_digit, cpv_additional,
                      amount, currency, vat_category, winner_status,
                      awardee_parties, contract_signatories,
                      place_of_performance, place_country,
                      award_date, contract_signature_date,
                      contract_notification_date, contract_start_date,
                      contract_end_date, duration_value, duration_unit, created_at

evidence              evidence_key (PK), award_key (FK), anchors_kind,
                      anchors_ref, source_system, source_kind, source_notice_id,
                      source_procedure_id, source_url, path, raw_value,
                      excerpt, retrieved_at, engine_version, created_at

materialized_signal   signal_key (PK), award_key (FK), icp_id, revision,
                      recency_status, primary_event,
                      award_clock_status, notification_clock_status,
                      publication_clock_status, award_age_days,
                      notification_age_days, publication_age_days, as_of,
                      recency_policy_version,
                      winner_name, winner_country,
                      winner_identifier_scheme, winner_identifier_value,
                      inferred_contract_type, inferred_sector,
                      inferred_trade_domain, inferred_contract_summary,
                      plausible_needs,
                      icp_match_decision, icp_match_band, icp_match_confidence,
                      icp_match_normalized_score, icp_matched_needs,
                      engine_versions, materialized_at, created_at
                      UNIQUE (award_key, icp_id)
```

### La doctrine, rendue exécutable

`FAIT ≠ INFÉRENCE ≠ CERTITUDE COMMERCIALE` n'est pas laissée à la vigilance des
relecteurs. Un nom de colonne survit à tous les commentaires — c'est lui qu'un
développeur pressé lira dans six mois — donc le schéma déclare ses interdits et
un test les applique à chaque colonne :

```python
FORBIDDEN_COLUMN_PATTERNS = (
    r"confirmed",
    r"purchase_intent",
    r"will_buy",
    r"guaranteed",
    r"certain_",
    r"_certainty",
)
```

Un second test vérifie que ces motifs attrapent bien les exemples que la SPEC
nomme (`confirmed_need`, `purchase_intent_confirmed`, `will_buy`,
`needs_confirmed`, `guaranteed_demand`) — un garde-fou qui ne garde rien serait
pire que pas de garde-fou.

Trois choix de nommage en découlent :

```text
plausible_needs               et jamais `needs` tout court : le pluriel nu
                              laisserait croire à un besoin établi
inferred_contract_summary     et non `contract_summary` : le préfixe dit qui parle
icp_match_*                   une décision de moteur, pas une propriété du marché
```

### Deux colonnes pour une seule date de parution

`published_at_raw` conserve exactement ce que la source a publié — jour seul ou
instant horodaté, la distinction que `PublicationInstant` protège depuis
SPEC-005 — pendant que `published_on` porte le jour, seul indexable. Une seule
colonne `TIMESTAMP` aurait inventé une heure ; une seule colonne `DATE` aurait
détruit une précision qu'aucun traitement ne peut reconstituer.

---

## 4. LES HORLOGES SURVIVENT (§6)

C'est le test qui compte le plus. SPEC-009E a coûté deux révisions pour séparer
décision, notification et parution ; un stockage qui les replierait effacerait
ce travail sans qu'aucun test d'unité ne s'en aperçoive.

Trois niveaux de garantie, tous testés sur un avis BOAMP réel :

```text
1. les quatre dates du contrat reviennent au jour près
   award_date · contract_signature_date · contract_notification_date
   contract_start_date · contract_end_date

2. les trois statuts d'horloge et leurs âges reviennent identiques
   award_clock_status · notification_clock_status · publication_clock_status

3. les dates stockées REPRODUISENT les statuts stockés
   assess_recency(dates rechargées, as_of rechargé) == statuts rechargés
```

Le troisième est le seul qui protège vraiment. Sans lui, un statut et des dates
pourraient diverger en base, et le produit afficherait « vient de remporter »
sur un marché que ses propres dates démentent.

C'est aussi pourquoi `as_of` est une colonne : une fraîcheur n'a de sens que
rapportée à une date de référence, et sans elle le recalcul serait impossible.

**Aucune phrase client n'est stockée.** `StoredSignal.claim(lang=…)` la
régénère depuis le statut rechargé via `claim_for_status`. Une phrase stockée
divergerait le jour où la politique de formulation change ; régénérée, elle dit
toujours ce que les faits autorisent — et un test vérifie qu'un signal rechargé
dont le statut n'est pas `recent_award` ne peut pas contenir « vient de
remporter ».

---

## 5. IDEMPOTENCE (§7)

```text
clé logique   signal_key = f(award_key, icp_id)
              award_key  = f(système, notice, version, contrat, lot)
révision      materialized_signal.revision
```

**La clé ne contient aucune version de moteur**, et c'est une divergence
assumée avec `research.signal100.signal_id`, qui plie `match_policy_version` et
`score_policy_version` dans son empreinte. Cette fonction-là identifie une
*mesure de banc*, où deux versions sont deux observations distinctes — c'est
correct pour un banc. Ici on identifie une *opportunité commerciale*, qui ne
change pas de nature parce qu'un moteur a changé de version. Les confondre
ferait remonter tout le feed comme neuf à chaque montée de version.

Comportement, testé :

```text
même bundle rematérialisé        → même signal_key, revision inchangée, 1 ligne
versions de moteur différentes   → même signal_key, revision + 1, 1 ligne
deux lots d'un même avis         → deux signal_key
deux contextes ICP               → deux signal_key, UN SEUL contract_award
```

La contrainte `UNIQUE (award_key, icp_id)` rend la garantie **structurelle** :
la base refuse le doublon même si un appelant oubliait de vérifier.

Les faits ne se dupliquent pas parce que deux clients regardent le même marché.
`_insert_if_absent` n'écrit une ligne de fait que si elle manque et ne réécrit
jamais l'existante : un fait publié ne se corrige pas silencieusement, une
republication qui changerait un montant doit produire un nouvel événement.

**Non-objectif assumé** : l'historique des révisions n'est pas conservé. §7
demande de *distinguer* le signal logique de sa révision, pas de garder chaque
état. Une table `materialized_signal_revision` s'ajouterait sans migration
destructive le jour où le produit en aura besoin.

---

## 6. PROVENANCE DES VERSIONS (§8)

```json
{
  "understanding": "contract-understanding-v0.3",
  "need":          "need-graph-v0.2",
  "match_policy":  "icp-match-v0.2",
  "score_policy":  "signal-score-v0.2",
  "recency_policy": "award-recency-v0.3"
}
```

Lues sur les objets de moteur — `understanding.engine_version`,
`needs.engine_version`, `match.match_policy_version`, … — et jamais recopiées
dans le stockage. Un test refuse toute chaîne ressemblant à `-vN.N` dans les
trois modules de persistance : si quelqu'un codait une version en dur, la suite
tomberait.

---

## 7. SERVICE ET LECTURE (§9, §10)

```python
materialize_signal(connection, *, event, award, understanding, needs,
                   match, recency, as_of, materialized_at) -> MaterializationResult

get_signal(connection, signal_key) -> StoredSignal | None
list_signals(connection, *, icp_id, country, primary_event,
             recency_status, winner_identifier_value, limit) -> list[StoredSignal]
```

Le service ne calcule rien : il ne relance aucune ingestion, n'ouvre aucune
connexion réseau, ne touche ni au Need Graph ni au Matching, et ignore tout de
la facturation comme du rendu. Il écrit **dans la transaction de l'appelant** —
c'est lui qui décide quand valider, donc un signal à moitié écrit ne peut pas
exister.

Le filtre est volontairement pauvre. Le moteur de recherche du produit n'existe
pas ; construire maintenant pagination, classement et indexation reviendrait à
figer des choix avant d'avoir un client. `limit` borne la lecture, l'ordre est
total et déterministe, et c'est tout.

---

## 8. AUCUN COMPTE ANTICIPÉ (§11)

`materialized_signal.icp_id` est le point d'accroche du contexte client. Aucune
table `user` ou `account` n'est créée, et un test vérifie qu'aucune colonne
`account_id` fictive n'a été ajoutée « pour plus tard ».

SPEC-011 pourra introduire les comptes sans refonte destructive :

```text
account(account_id, …)
account_icp(account_id, icp_id)   →  jointure vers materialized_signal.icp_id
```

Aucune migration de données n'est nécessaire : les signaux existants restent
rattachés à leur ICP, et l'appartenance d'un ICP à un compte devient une
relation supplémentaire.

---

## 9. MIGRATIONS (§13)

```text
src/signals/persistence/migrations/
  env.py                    contexte Alembic, piloté par un moteur fourni
  script.py.mako
  versions/0001_initial_initial_saas_persistence_schema.py
```

Les migrations **voyagent dans le paquet** : une installation par wheel sait se
migrer elle-même, ce qui est ce dont un déploiement VPS a besoin.

**Il n'y a pas d'`alembic.ini`, et c'est délibéré.** Ce fichier porterait une
URL de base, donc un secret, dans un fichier versionné. L'appelant fournit un
moteur déjà configuré via `config.attributes`.

La révision initiale a été **générée** depuis le schéma (`--autogenerate`)
plutôt que transcrite à la main : une transcription introduit des dérives
silencieuses entre le schéma déclaré et le schéma migré.

Tests :

```text
✔ base vide → schéma courant
✔ le schéma migré correspond au schéma déclaré, colonne par colonne
✔ migrer une base déjà à jour ne change rien (rejouable au démarrage)
✔ la révision appliquée est enregistrée dans la base
✔ les clés étrangères sont actives même sur SQLite
```

Le deuxième test est celui qui interdit toute création de table hors migration :
une table ajoutée à la main se verrait immédiatement.

**Environnement de test.** Aucun service à lancer. Les tests créent une base
SQLite dans un `tmp_path` et appliquent les migrations. Pour viser un vrai
PostgreSQL, il suffit de `KIVOU_DATABASE_URL=postgresql+psycopg://…` — mais
aucun test n'en dépend.

---

## 10. PORTABILITÉ VPS (§14)

```text
local → VPS Infomaniak actuel → VPS Kivou dédié
```

Un déploiement a besoin de quatre choses, et pas d'une de plus :

```text
l'application (wheel ou dépôt)
PostgreSQL
un volume persistant
KIVOU_DATABASE_URL
```

```text
aucun service cloud géré        aucun appel AWS/GCP/Azure
aucun conteneur                 rien n'est ajouté ; le dépôt n'en avait pas
aucun orchestrateur             ni Kubernetes ni Terraform
chemins relatifs                migrations résolues depuis le module
secrets hors du code            une seule variable d'environnement, testée
aucune base par défaut          l'absence de configuration lève une erreur claire
                                plutôt que d'écrire silencieusement quelque part
```

---

## 11. NON-RÉGRESSION (§16)

```text
BOAMP ingestion                  boamp-adapter-v0.1              intact
DECP ingestion                   decp-adapter-v0.2 · decp-2022   intact
multi-clock recency v0.3         award-recency-v0.3              intact
SIMAP / TED                      inchangés
Contract Understanding           contract-understanding-v0.3     intact
Need Graph                       need-graph-v0.2                 intact
règles de besoin                 need-rules-v0.5                 intact
Matching                         icp-match-v0.2                  intact
Signal Score                     signal-score-v0.2               intact
BKP                              bkp-trade-v0.1                  intact
rapprochement France             france-link-v0.3                intact
Document Intelligence            AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False
Commercial Verifier              OFF, non touché
SPEC-009C (64 %)                 non re-mesuré, non modifié
SPEC-009D · SPEC-009E            intacts (commits 1cd8628, 05ecfd7)
```

```bash
$ git status --porcelain src/signals/understanding src/signals/needs \
      src/signals/matching src/signals/documents src/signals/connectors \
      src/signals/recency src/signals/france
(vide)
```

**Cette SPEC est de la persistance, pas de l'intelligence.** Aucun fichier
moteur n'a été touché. Les seuls fichiers suivis modifiés sont `pyproject.toml`
(trois dépendances) et `uv.lock`.

---

## 12. FICHIERS

```text
NOUVEAUX — persistance
  src/signals/persistence/__init__.py
  src/signals/persistence/identity.py          clés d'événement, d'award, de signal
  src/signals/persistence/schema.py            quatre tables, doctrine exécutable
  src/signals/persistence/database.py          moteur, configuration, migrations
  src/signals/persistence/materialization.py   la frontière applicative
  src/signals/persistence/repository.py        get_signal / list_signals
  src/signals/persistence/migrations/env.py
  src/signals/persistence/migrations/script.py.mako
  src/signals/persistence/migrations/versions/0001_initial_…py

NOUVEAUX — tests (85)
  tests/test_persistence_identity.py         13
  tests/test_persistence_schema.py           35
  tests/test_persistence_migrations.py       10
  tests/test_persistence_materialization.py  27

MODIFIÉS
  pyproject.toml   + sqlalchemy, alembic ; extra `postgres` ; psycopg en dev
  uv.lock
```

Aucun fichier hors périmètre n'a été touché ni indexé (§15). Les artefacts
SPEC-009C restants et les documents Word demeurent non suivis.

---

## 13. PORTES (§17)

```bash
$ uv run pytest -q
2111 passed in 21.08s        # 2 026 avant SPEC-010, + 85

$ uv run ruff check .
All checks passed!

$ git diff --check
(rien)

$ uv run ruff format --check .
1 file would be reformatted
  docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md
```

**Tests ignorés : zéro.** Aucun service de base de données n'est requis.

```bash
$ git status --porcelain
 M pyproject.toml
 M uv.lock
?? src/signals/persistence/
?? tests/test_persistence_identity.py
?? tests/test_persistence_materialization.py
?? tests/test_persistence_migrations.py
?? tests/test_persistence_schema.py
?? docs/reports/2026-08-18-spec010-saas-persistence-foundation.md
   (+ 10 fichiers hors périmètre, antérieurs et non suivis)

$ git diff --stat
 pyproject.toml |  12 +++
 uv.lock        | 139 +++++++++++++++++++++++++++++
 2 files changed, 151 insertions(+)

$ git diff --cached --stat
(rien d'indexé)
```

---

## 14. DÉCISIONS QUI CONTRAIGNENT SPEC-011 ET AU-DELÀ

Cinq, à valider maintenant plutôt qu'à découvrir plus tard.

**1. SQLAlchemy Core, jamais l'ORM.** Tout code ultérieur écrira des requêtes
Core. C'est un peu plus verbeux qu'un ORM et cela garde le domaine souverain.
Revenir en arrière coûterait la réécriture des quatre modules de persistance.

**2. La clé de signal exclut les versions de moteur.** Un futur besoin
d'historiser chaque révision demandera une table fille, pas un changement de
clé.

**3. Le contexte client est un `icp_id`, pas un compte.** SPEC-011 ajoute
`account` et `account_icp` par-dessus. Si le produit décidait plutôt qu'un
signal appartient directement à un compte — et non à un ICP partagé — la table
`materialized_signal` changerait de clé d'unicité. C'est le point le plus
structurant du schéma, et il mérite une décision explicite avant SPEC-011.

**4. Les faits ne sont jamais réécrits.** Une republication qui corrigerait un
montant ne remplace pas la ligne existante. Le jour où une source publie des
corrections, il faudra un mécanisme de version d'événement — le modèle le
permet déjà via `notice_version`, mais rien ne l'exploite encore.

**5. Aucun historique de révision.** Volontaire, et facile à ajouter.

---

## VERDICT

```text
SAAS PERSISTENCE FOUNDATION READY
```

```text
persistance relationnelle durable        ✔ 4 tables, PostgreSQL-compatible,
                                           DDL compilé et testé sans serveur
migrations depuis zéro                   ✔ base vide → schéma, colonne par colonne
horloges multiples préservées            ✔ dates, statuts, ET recalcul depuis la base
faits distincts des inférences           ✔ 3 tables de faits, 1 d'inférences,
                                           noms interdits testés colonne par colonne
matérialisation idempotente              ✔ 2 exécutions → 1 signal ; versions → révision
provenance des moteurs                   ✔ 5 versions, aucune codée en dur
service et lecture                       ✔ frontière explicite, filtres minimaux
transaction                              ✔ rollback vérifié, rien ne subsiste
portabilité VPS                          ✔ application + PostgreSQL + volume + 1 variable
non-régression                           ✔ aucun moteur touché
tests                                    ✔ 2 111 passed, 0 ignoré, ruff clean
```

Aucun blocage. Le point qui mérite une décision avant SPEC-011 est le n°3
ci-dessus : un signal appartient-il à un **ICP** (partageable entre comptes) ou
à un **compte** ? Le schéma actuel suppose le premier, et c'est le seul choix
qu'un changement d'avis rendrait coûteux.

**Rien n'est committé.** Aucune suite n'est engagée : ni authentification, ni
frontend, ni paiement, ni déploiement. En attente de la revue superviseur.
