# SPEC-010 FINAL CLOSEOUT — Stable Opportunity Identity

**Rien n'est committé.** Persistance, fraîcheur, propriété du TargetICP, empreinte
de contenu, moteurs : tous inchangés. Une seule chose a bougé — l'identité
d'opportunité.

---

## 1. LE DÉFAUT, ET POURQUOI IL M'AVAIT ÉCHAPPÉ

Ma stratégie était :

```text
mono-source     opportunity_key = award_key
ensemble STRONG opportunity_key = hash(ensemble trié des award_key)
```

J'avais vérifié — et testé — qu'elle était indépendante de l'ordre. Elle l'est.
Mais l'indépendance à l'ordre suppose que **l'ensemble complet soit connu au
moment du calcul**, et il ne l'est jamais :

```text
jour 1   A arrive, seul               opportunity_key = f(A)
jour 2   B est rapproché de A         opportunity_key = f(A, B)   ← elle a CHANGÉ
```

Le signal servi la veille aurait été renommé. Mon test
`test_the_collapsed_key_does_not_depend_on_the_order_of_representations`
comparait deux résolutions du **même ensemble complet** ; il ne pouvait pas voir
le cas où l'ensemble grandit. La propriété testée était vraie, et ce n'était pas
la propriété qui compte.

---

## 2. IDENTITÉ PERSISTÉE (§1, §2)

L'identité n'est plus **dérivée** de l'appartenance : elle est **écrite une
fois** et relue ensuite.

```python
resolve_or_create_opportunity(
    connection, award, *, now, linked_to=(), link_strength="unresolved"
) -> ResolvedOpportunity        # (opportunity_key, representations, created)

opportunity_of(connection, award_key) -> str | None
```

### Algorithme

```text
reference = award_key(award)
mine      = opportunity_of(reference)                     ← lecture en base
candidats = { opportunity_of(x) pour x dans linked_to }   ← seulement si STRONG

CAS A   mine existe
          candidats \ {mine} non vide  → OpportunityConflict
          sinon                        → rendre mine, created=False

CAS B   mine absent, exactement 1 candidat
          → rattacher `reference` à ce candidat, created=False
          → l'opportunité existante N'EST PAS modifiée

        mine absent, ≥ 2 candidats
          → OpportunityConflict

CAS C   mine absent, aucun candidat
          → créer une identité, l'écrire, created=True
```

La clé neuve est `"opp_" + sha256("opportunity" ⋮ award_key)[:36]`. Déterministe
pour être reproductible, préfixée pour qu'aucun lecteur ne la confonde avec un
`award_key`, et **jamais recalculée** ensuite — la création est le seul moment où
elle est produite.

Deux bases construites dans des ordres d'arrivée différents obtiendront des
valeurs différentes. §7.B l'autorise explicitement, et c'est sans conséquence :
l'identité n'a de sens qu'à l'intérieur d'une base.

### `linked_to` sert à retrouver, pas à rattacher

Les représentations liées ne sont pas rattachées par cet appel. Leurs faits
n'ont pas forcément encore été écrits, et la clé étrangère l'interdirait — à
juste titre. Chacune se rattache lors de sa propre matérialisation. La table
décrit donc ce qui est **réellement stocké**, jamais une appartenance promise.

---

## 3. CONFLIT PLUTÔT QUE FUSION (§3)

```text
A → O1
B → O2
puis A ↔ B devient STRONG
        ↓
OpportunityConflict — les deux opportunités et tous leurs faits sont conservés
```

Le message nomme les deux côtés pour qu'un humain puisse arbitrer :

```text
réconciliation requise : la représentation <award> appartient à <O1>, et un lien
fort la relie à ['<O2>']. Aucune fusion automatique n'est faite — les deux
opportunités et tous leurs faits sont conservés.
```

Fusionner reviendrait à réécrire l'identité d'un signal déjà servi et à faire
disparaître l'un des deux. **La sûreté des faits passe avant la déduplication
automatique.** Un mécanisme de fusion explicite pourra traiter le cas si l'usage
réel le réclame.

---

## 4. UNICITÉ DE REPRÉSENTATION (§4)

```sql
CREATE TABLE opportunity_representation (
    award_key       VARCHAR(64) NOT NULL,
    opportunity_key VARCHAR(64) NOT NULL,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (award_key),
    FOREIGN KEY (award_key) REFERENCES contract_award (award_key) ON DELETE CASCADE
)
CREATE INDEX ix_opportunity_representation_opportunity_key
    ON opportunity_representation (opportunity_key)
```

`award_key` est la **clé primaire**. La clé composite `(opportunity_key,
award_key)` que j'avais posée laissait structurellement possible le rattachement
d'un même award à deux opportunités — c'est-à-dire exactement le dédoublement
silencieux qu'on cherche à empêcher.

```text
plusieurs représentations → une opportunité      autorisé, c'est l'objet de la table
une représentation        → plusieurs opportunités   refusé par la base
```

Un test l'exerce en insérant directement un second rattachement et vérifie que
`IntegrityError` est levée : la garantie vient de la base, pas seulement du code.

---

## 5. `materialization_award_key` (§6)

```text
materialized_signal.award_key  →  materialized_signal.materialization_award_key
```

Le renommage est fait parce qu'il est gratuit avant le premier commit de la
migration. Un champ nommé `award_key` sur une table de **signaux** invite à le
prendre pour l'identité logique ; le nouveau nom dit ce qu'il est : la
représentation source qui a produit la **révision courante**.

L'identité logique reste `opportunity_key`, et un test vérifie qu'`award_key`
n'existe plus sur cette table.

---

## 6. SCHÉMA D'OPPORTUNITÉ — ÉTAT EXACT

```text
opportunity_representation
  award_key        VARCHAR(64)  PK, FK → contract_award.award_key, ON DELETE CASCADE
  opportunity_key  VARCHAR(64)  NOT NULL, indexé
  created_at       TIMESTAMPTZ  NOT NULL

materialized_signal
  signal_key                 VARCHAR(64)  PK
  opportunity_key            VARCHAR(64)  NOT NULL, indexé   ← identité LOGIQUE
  materialization_award_key  VARCHAR(64)  NOT NULL, FK, indexé ← représentation courante
  target_icp_id              VARCHAR(128) NOT NULL, indexé
  …
  UNIQUE (opportunity_key, target_icp_id)
```

`signal_key = f(opportunity_key, target_icp_id)` — inchangé dans sa forme, mais
l'`opportunity_key` qu'il reçoit vient désormais de la base.

La migration `0001_initial` a de nouveau été **régénérée** plutôt que complétée :
elle n'a jamais été committée ni appliquée à une base réelle, et livrer une
migration initiale suivie d'une migration qui la corrige laisserait la trace d'un
schéma qui n'a existé nulle part.

---

## 7. RÉSULTATS DES TESTS DEMANDÉS (§7)

### A — liaison tardive

```text
matérialiser A                      → signal S, opportunité O
attacher B, lien STRONG, plus tard  → MÊME opportunité O
                                      MÊME signal S
                                      DEUX représentations conservées
                                      DEUX contract_award conservés
```

Vérifié à la fois sur le résolveur seul et de bout en bout, sur la paire réelle
BOAMP `26-79799` × DECP `178645481096900` gelée en SPEC-009E. Un test dédié —
`test_a_late_link_never_renames_an_already_served_signal` — relit le signal du
jour 1 après la liaison du jour 2 et le retrouve intact.

Un troisième rattachement (`C`) laisse également la clé inchangée.

### B — ordre d'arrivée inversé

```text
B d'abord, puis A lié STRONG → une seule opportunité dans cette base
                               aucun doublon après l'arrivée de la seconde
```

Les valeurs de clé diffèrent entre deux bases construites dans des ordres
opposés ; leur **nombre** ne diffère pas. C'est ce que §7.B autorise.

### C — opportunités déjà séparées

```text
A → O1, B → O2, puis A ↔ B STRONG
  → OpportunityConflict, message nommant O1 et O2
  → A reste sur O1, B reste sur O2
  → les deux contract_award intacts
  → de bout en bout : les deux signaux restent lisibles par get_signal
```

Aucune fusion automatique. Aucun signal ne disparaît en silence.

### D — unicité de représentation

```text
insertion directe d'un second rattachement pour le même award_key
  → sqlalchemy.exc.IntegrityError
```

### E — liens non forts

```text
probable / unresolved / ambiguous
  → jamais réunis : la représentation obtient sa propre opportunité
  → et la matérialisation n'est PAS bloquée pour autant
```

Deux tests séparés : l'un vérifie la non-réunion, l'autre qu'un candidat faible
n'empêche pas une matérialisation normale.

---

## 8. NON-RÉGRESSION (§8)

```text
SQLAlchemy Core                    inchangé
Alembic                            inchangé
cible PostgreSQL                   inchangée — DDL compilé, aucun type de dialecte
current vs materialized recency    inchangée — 16 tests
propriété du TargetICP             inchangée — target_icp_id, aucun account_id
révision par empreinte de contenu  inchangée — content_fingerprint
faits vs inférences                inchangée
Evidence                           inchangée
moteurs                            inchangés
BOAMP / DECP / TED / SIMAP         intacts
benchmarks historiques             non touchés
```

```bash
$ git status --porcelain src/signals/understanding src/signals/needs \
      src/signals/matching src/signals/documents src/signals/connectors \
      src/signals/recency src/signals/france src/signals/domain
(vide)
```

Aucun auth, aucun frontend, aucun paiement, aucun déploiement.

---

## 9. PORTES (§9)

```bash
$ uv run pytest -q
2170 passed in 26.19s        # 2 160 avant ce closeout, + 10

$ uv run ruff check .
All checks passed!

$ git diff --check
(rien)

$ uv run ruff format --check .
1 file would be reformatted
  docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md
```

**Tests ignorés : zéro.** Aucun service de base de données requis.

```text
test_persistence_identity.py           14
test_persistence_opportunity.py        23     réécrit pour le résolveur persistant
test_persistence_schema.py             44
test_persistence_migrations.py         10
test_persistence_materialization.py    37
test_persistence_current_recency.py    16
                                      ────
                                      144
```

```bash
$ git status --porcelain
 M pyproject.toml
 M uv.lock
?? src/signals/persistence/
?? tests/test_persistence_current_recency.py
?? tests/test_persistence_identity.py
?? tests/test_persistence_materialization.py
?? tests/test_persistence_migrations.py
?? tests/test_persistence_opportunity.py
?? tests/test_persistence_schema.py
?? docs/reports/2026-08-18-spec010-saas-persistence-foundation.md
?? docs/reports/2026-08-18-spec010-closeout-recency-and-opportunity.md
?? docs/reports/2026-08-18-spec010-final-closeout-stable-opportunity.md
   (+ 10 fichiers hors périmètre, antérieurs et non suivis)

$ git diff --stat
 pyproject.toml |  12 +++
 uv.lock        | 139 +++++++++++++++++++++++++++++
 2 files changed, 151 insertions(+)

$ git diff --cached --stat
(rien d'indexé)
```

### Liste exacte des fichiers destinés au commit

```text
MODIFIÉS
  pyproject.toml
  uv.lock

NOUVEAUX — persistance
  src/signals/persistence/__init__.py
  src/signals/persistence/identity.py
  src/signals/persistence/opportunity.py
  src/signals/persistence/schema.py
  src/signals/persistence/database.py
  src/signals/persistence/materialization.py
  src/signals/persistence/repository.py
  src/signals/persistence/migrations/env.py
  src/signals/persistence/migrations/script.py.mako
  src/signals/persistence/migrations/versions/0001_initial_…py

NOUVEAUX — tests (144)
  tests/test_persistence_identity.py
  tests/test_persistence_opportunity.py
  tests/test_persistence_schema.py
  tests/test_persistence_migrations.py
  tests/test_persistence_materialization.py
  tests/test_persistence_current_recency.py

NOUVEAUX — rapports
  docs/reports/2026-08-18-spec010-saas-persistence-foundation.md
  docs/reports/2026-08-18-spec010-closeout-recency-and-opportunity.md
  docs/reports/2026-08-18-spec010-final-closeout-stable-opportunity.md
```

**Hors périmètre, à ne jamais indexer** : les deux `.docx`, les
`:Zone.Identifier`, le postmortem SPEC-006, le rapport de banc SPEC-009C,
`src/signals/research/spec009c*.py`, `tests/test_spec009c_bench.py`,
`tests/fixtures/signal100/spec009c_blind.json`.

Les deux rapports antérieurs portent des bannières de correction : celui-ci fait
foi pour l'identité d'opportunité.

---

## VERDICT

```text
SPEC-010 READY TO COMMIT
```

```text
identité persistée, jamais recalculée   ✔ créée une fois, relue ensuite
liaison tardive sans renommage          ✔ A puis B → même opportunité, même signal
                                          testé sur le résolveur ET de bout en bout
troisième représentation                ✔ clé inchangée
ordre d'arrivée inversé                 ✔ une seule opportunité dans la base
opportunités déjà séparées              ✔ OpportunityConflict, aucune fusion,
                                          les deux signaux restent lisibles
une représentation → une opportunité     ✔ award_key en clé primaire,
                                          IntegrityError vérifiée
liens non forts                         ✔ jamais réunis, jamais bloquants
materialization_award_key               ✔ renommé, `award_key` absent du signal
non-régression                          ✔ moteurs, recency, TargetICP, empreinte
tests                                   ✔ 2 170 passed, 0 ignoré, ruff clean
```

Aucun blocage.

**Rien n'est committé.** En attente de votre autorisation.
