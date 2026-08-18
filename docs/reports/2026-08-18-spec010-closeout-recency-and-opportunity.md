# SPEC-010 CLOSEOUT — Current Recency Safety + Opportunity Identity

**Rien n'est committé.** L'architecture de persistance est inchangée : SQLAlchemy
Core, Alembic, cible PostgreSQL, modèles pydantic, séparation faits/inférences,
doctrine Evidence, multi-clock v0.3. Trois sémantiques produit ont été
verrouillées.

> ## ⚠ LA SECTION 2 EST CORRIGÉE PAR LE CLOSEOUT FINAL
>
> La stratégie d'identité décrite ici — `opportunity_key = hash(ensemble trié
> des award_key)` — est **instable en cas de liaison tardive** : attacher une
> représentation B des semaines après A recalculait la clé et renommait un
> signal déjà servi.
>
> L'identité est désormais **persistée à la création** et relue ensuite, jamais
> dérivée de l'appartenance courante. Les sections 1, 3 et 4 de ce rapport
> restent valides.
>
> Voir `2026-08-18-spec010-final-closeout-stable-opportunity.md`.

---

## 1. L'INSTANTANÉ N'EST PAS LA VÉRITÉ DU JOUR (§1)

Le défaut visé est celui d'un feed qui vieillit sans le savoir. Un marché
matérialisé `recent_award` le 18 août reste `recent_award` en base pour
toujours ; si la phrase client se déduisait de cette colonne, le produit dirait
« vient de remporter » deux mois plus tard.

### Le nommage porte l'avertissement

Chaque colonne de fraîcheur est préfixée. Ce n'est pas décoratif : c'est ce nom
qu'un développeur lira dans six mois, et `recency_status` invitait à l'oublier.

```text
AVANT                          APRÈS
recency_status            →    materialized_recency_status
primary_event             →    materialized_primary_event
award_clock_status        →    materialized_award_clock_status
notification_clock_status →    materialized_notification_clock_status
publication_clock_status  →    materialized_publication_clock_status
award_age_days            →    materialized_award_age_days
notification_age_days     →    materialized_notification_age_days
publication_age_days      →    materialized_publication_age_days
as_of                     →    materialized_as_of
```

Un test refuse désormais toute colonne contenant `recency`, `clock`, `age_days`
ou nommée `as_of` qui ne porterait pas le préfixe.

### La réévaluation

```python
StoredSignal.current_recency(*, as_of: dt.date) -> AwardRecency
StoredSignal.claim(*, as_of: dt.date, lang: str = "fr") -> str
StoredSignal.current_primary_event(*, as_of: dt.date) -> str | None
```

`current_recency` rejoue `assess_recency` sur les **dates brutes** rechargées —
`award_date`, `contract_notification_date`, `published_on` — et non sur les
statuts figés. Toute affirmation client passe par elle.

**`as_of` n'a pas de valeur par défaut.** Deux tests le vérifient par
introspection de signature, et un troisième interdit `date.today()`,
`datetime.now(`, `utcnow(` et `time.time(` dans les quatre modules de
persistance. Une horloge cachée rendrait la suite non reproductible dès le
lendemain — et rendrait indémontrable la propriété que §1 demande.

### Le cas exact de la SPEC, testé

```text
matérialisé le 2026-08-18, award_date = 2026-08-10
  materialized_recency_status              recent_award       (figé, pour l'audit)

lu le 2026-08-23   current_recency          recent_award       → « vient de remporter » ✔
lu le 2026-10-18   current_recency          stale_award        → aucune revendication ✔
                   materialized_award_age_days        8
                   current_recency().award_age_days  69
```

Trois autres régressions couvrent la notification (`recently_notified_contract`
ne se revendique plus après le seuil), l'horloge de publication, et la
permanence de l'instantané : après plusieurs réévaluations, la ligne relue est
identique au bit près.

### Le filtre de lecture

```python
list_signals(..., materialized_recency_status=...)  # et non recency_status=
list_signals(..., materialized_primary_event=...)
```

C'est la plus petite implémentation sûre : le paramètre dit ce qu'il interroge.
Un appelant qui construirait un feed « nouveautés » sur ce filtre voit dans son
propre code qu'il lit un instantané, et chaque résultat expose
`current_recency(as_of=…)` pour la suite.

---

## 2. IDENTITÉ D'OPPORTUNITÉ (§2)

```text
award_key         une REPRÉSENTATION porteuse de faits
                  « l'avis BOAMP 26-79799, lot 1 »
opportunity_key   le CONTRAT RÉEL montré au client
signal_key        f(opportunity_key, target_icp_id)
```

Le problème était réel et mesuré : SPEC-009E a démontré quatre rapprochements
forts BOAMP × DECP sur une seule semaine. Sans cette séparation, un client
verrait deux fois le même marché — une fois « vient de remporter », une fois
« vient d'être notifié ».

### Stratégie

```text
marché mono-source        opportunity_key = award_key          repli déterministe
rapprochement STRONG      opportunity_key = empreinte de
                          l'ensemble TRIÉ des award_key
tout le reste             refus — ValueError
```

La clé collapsée est une empreinte de l'ensemble trié, et non l'une des
représentations : choisir « la première » ferait dépendre l'identité de l'ordre
d'ingestion, et changer de source primaire renommerait le signal.

`COLLAPSIBLE_LINK_STRENGTHS = frozenset({"strong"})`. Un `probable` de
SPEC-009E n'a jamais autorisé une fusion de faits, et il ne l'autorise pas
davantage ici.

**Aucun rapprochement flou.** Un test analyse l'AST du module, docstrings
retirées, et refuse `difflib`, `levenshtein`, `fuzz`, `ratio`, `similar`,
`distance`. La prose a le droit d'expliquer ce qu'elle interdit ; le code n'a
pas le droit de l'implémenter.

### La table de rattachement

```text
opportunity_representation(opportunity_key, award_key, created_at)
```

Elle n'enregistre que la représentation **réellement persistée** au moment de
l'appel. Les autres membres annoncés par la résolution n'ont pas encore de ligne
de faits, et la clé étrangère l'interdirait à juste titre — la table décrit donc
ce qui est stocké, jamais une appartenance promise.

### Tests de dédup inter-sources

```text
✔ même award source + même ICP                      → un seul signal
✔ deux lots distincts                               → deux opportunités
✔ deux awards sources sans rapport                  → deux opportunités
✔ BOAMP + DECP rapprochés STRONG, même ICP          → UNE opportunité, UN signal
                                                      et DEUX contract_award conservés
✔ mêmes représentations sans rapprochement fourni   → deux opportunités
✔ lien `probable` / `unresolved` / `ambiguous`      → refus avant la base
✔ l'ordre d'arrivée des sources ne change pas la clé
```

Le quatrième utilise la paire réelle gelée en SPEC-009E — BOAMP `26-79799` et
DECP `178645481096900`, mêmes parties, même date, même montant, même CPV — et
vérifie que le lien est bien reconnu `strong` par `unique_strong` avant de
matérialiser.

---

## 3. PROPRIÉTÉ DU TARGETICP (§3)

Décision du superviseur enregistrée dans le schéma et dans le code.

```text
Account 1 ─── N TargetICP 1 ─── N MaterializedSignal
```

```text
icp_id  →  target_icp_id
```

Sémantique documentée dans `schema.py` et dans `identity.signal_key` :
`target_icp_id` désigne **une instance de TargetICP possédée par un compte**, et
non un profil partagé entre clients.

Aucune table `account` n'est créée, et un test vérifie qu'aucune colonne
`account_id` fictive n'a été anticipée. SPEC-011 ajoutera `account` et
`target_icp(account_id, …)` sans toucher `materialized_signal`.

```text
UNIQUE (opportunity_key, target_icp_id)
```

remplace l'ancienne `UNIQUE (award_key, icp_id)`.

---

## 4. SÉCURITÉ DES RÉVISIONS (§4)

La révision ne dépend plus des seules versions de moteur — c'était le défaut que
§4 demandait de fermer.

```python
content_fingerprint(payload) -> sha256
```

L'empreinte couvre **toute** la charge matérialisée : statuts, inférences,
score, identité du gagnant, versions de moteur. Elle exclut `materialized_at`,
`created_at`, `revision` et elle-même — sinon chaque exécution produirait une
empreinte neuve et l'idempotence disparaîtrait.

```text
contenu identique                              → revision inchangée, updated=False
inférence changée à versions constantes        → revision + 1        ← le cas visé
score changé                                   → revision + 1
version de moteur changée                      → revision + 1
même contenu rematérialisé plus tard           → revision inchangée
```

Le deuxième test modifie `understanding.sector` sans toucher aucune version et
vérifie que la révision avance et que le contenu relu a changé.

---

## 5. CHANGEMENT DE SCHÉMA EXACT

```text
NOUVELLE TABLE
  opportunity_representation(opportunity_key PK, award_key PK/FK, created_at)

materialized_signal
  + opportunity_key        String(64), NOT NULL, indexé
  + content_fingerprint    String(64), NOT NULL
  ~ icp_id                          → target_icp_id
  ~ recency_status                  → materialized_recency_status
  ~ primary_event                   → materialized_primary_event
  ~ award_clock_status              → materialized_award_clock_status
  ~ notification_clock_status       → materialized_notification_clock_status
  ~ publication_clock_status        → materialized_publication_clock_status
  ~ award_age_days                  → materialized_award_age_days
  ~ notification_age_days           → materialized_notification_age_days
  ~ publication_age_days            → materialized_publication_age_days
  ~ as_of                           → materialized_as_of
  ~ UNIQUE(award_key, icp_id)       → UNIQUE(opportunity_key, target_icp_id)

source_event · contract_award · evidence   INCHANGÉES
```

```text
source_event                14 colonnes
contract_award              27 colonnes
evidence                    15 colonnes
opportunity_representation   3 colonnes
materialized_signal         33 colonnes
```

**La migration `0001_initial` a été régénérée plutôt que complétée.** Elle n'a
jamais été committée ni appliquée à une base réelle ; livrer une migration
initiale suivie d'une migration qui la corrige aurait laissé une trace d'un
schéma qui n'a existé nulle part. Le test « schéma migré == schéma déclaré,
colonne par colonne » couvre le résultat.

---

## 6. NON-RÉGRESSION (§5)

```text
SQLAlchemy Core                inchangé
Alembic                        inchangé
cible PostgreSQL               inchangée — DDL compilé, aucun type de dialecte
modèles pydantic du domaine    inchangés
faits vs inférences            inchangée — 4 tables de faits, 1 d'inférences
doctrine Evidence              inchangée
multi-clock v0.3               award-recency-v0.3, intact
BOAMP / DECP / TED / SIMAP     intacts
Need Graph                     need-graph-v0.2, intact
Matching                       icp-match-v0.2, intact
Signal Score                   signal-score-v0.2, intact
benchmarks historiques         non touchés
Document Intelligence          AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False
Commercial Verifier            OFF
```

```bash
$ git status --porcelain src/signals/understanding src/signals/needs \
      src/signals/matching src/signals/documents src/signals/connectors \
      src/signals/recency src/signals/france src/signals/domain
(vide)
```

Aucun auth, aucun frontend, aucun paiement, aucun déploiement.

---

## 7. PORTES (§6)

```bash
$ uv run pytest -q
2160 passed in 23.37s        # 2 111 avant le closeout, + 49

$ uv run ruff check .
All checks passed!

$ git diff --check
(rien)

$ uv run ruff format --check .
1 file would be reformatted
  docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md
```

**Tests ignorés : zéro.** Aucun service de base de données requis — SQLite dans
un `tmp_path`.

```text
test_persistence_identity.py           14
test_persistence_opportunity.py        17     nouveau
test_persistence_schema.py             42
test_persistence_migrations.py         10
test_persistence_materialization.py    35
test_persistence_current_recency.py    16     nouveau
                                      ────
                                      134
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
  pyproject.toml                                    + sqlalchemy, alembic, psycopg
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

NOUVEAUX — tests (134)
  tests/test_persistence_identity.py
  tests/test_persistence_opportunity.py
  tests/test_persistence_schema.py
  tests/test_persistence_migrations.py
  tests/test_persistence_materialization.py
  tests/test_persistence_current_recency.py

NOUVEAUX — rapports
  docs/reports/2026-08-18-spec010-saas-persistence-foundation.md
  docs/reports/2026-08-18-spec010-closeout-recency-and-opportunity.md
```

**Hors périmètre, à ne jamais indexer** : les deux `.docx`, les
`:Zone.Identifier`, le postmortem SPEC-006, le rapport de banc SPEC-009C,
`src/signals/research/spec009c*.py`, `tests/test_spec009c_bench.py`,
`tests/fixtures/signal100/spec009c_blind.json`.

---

## VERDICT

```text
SPEC-010 READY TO COMMIT
```

```text
instantané ≠ vérité du jour        ✔ 9 colonnes préfixées `materialized_`,
                                     current_recency(as_of) + claim(as_of),
                                     `as_of` obligatoire, aucune horloge cachée
J+5 revendique / J+90 non          ✔ le cas exact de la SPEC, testé dans les deux sens
instantané préservé pour l'audit   ✔ relecture identique après réévaluations
filtre non trompeur                ✔ `materialized_recency_status=`
identité d'opportunité             ✔ opportunity_key, repli déterministe,
                                     collapse STRONG seul, aucun flou (AST vérifié)
dédup inter-sources                ✔ BOAMP + DECP réels → 1 signal, 2 faits conservés
probable/unresolved jamais fondus  ✔ refus avant la base
TargetICP possédé par un compte    ✔ target_icp_id, UNIQUE(opportunity, target_icp),
                                     aucun account_id anticipé
révision par contenu               ✔ empreinte déterministe ; inférence changée à
                                     versions constantes → révision + 1
non-régression                     ✔ aucun moteur, aucun modèle du domaine touché
tests                              ✔ 2 160 passed, 0 ignoré, ruff clean
```

Aucun blocage.

**Rien n'est committé.** En attente de votre autorisation.
