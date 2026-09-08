# SPEC-009E R2 — Multi-Clock Events + France Unique Signal Count

**Rien n'est committé.** SPEC-009E reste non approuvée. R1 est intégralement préservée.

---

## 0. LES DEUX REPROCHES, ET CE QU'ILS VALENT

### §1 — les horloges effondrées

Bug reproduit avant toute correction :

```text
award_date = 2026-05-20 (J-90)   contract_notification_date = 2026-08-17 (J-1)

politique v0.2   status = stale_award
                 → le fait de notification est PERDU pour le produit
```

La faute est structurelle : j'avais fait de `recently_notified_contract` un
**état exclusif**, ne parlant que lorsque la décision était absente. Une décision
connue mais périmée écrasait donc une notification d'hier — le seul fait
commercialement exploitable du signal.

### §3 — « 45 + 383 = 428 »

C'est moi qui l'ai écrit, et c'est une surinterprétation. J'ai additionné deux
comptages d'**événements** issus de deux registres qui décrivent parfois le même
marché, et j'ai présenté la somme comme un nombre d'**opportunités**, avec un
« facteur 9,5 » qui donnait à l'erreur l'allure d'un résultat.

Les deux corrections sont faites et mesurées.

---

## 1. RECENCY MODEL CHANGES

`award-recency-v0.2` → **`award-recency-v0.3`**.

Trois horloges évaluées **indépendamment**, puis un événement **dérivé**.

```python
ClockStatus = Literal["recent", "aging", "stale", "unknown", "invalid"]


@dataclass(frozen=True)
class ClockAssessment:
    clock: str  # "award" | "notification" | "publication"
    status: ClockStatus
    date: date | None
    age_days: int | None
    reason: str
```

`AwardRecency` porte désormais `award_clock`, `notification_clock`,
`publication_clock` — plus un accès par nom via `.clocks`. Aucune horloge
n'emprunte à une autre : `_assess_clock` juge chaque date sur elle-même.

### La dérivation de l'événement produit

```text
1. décision récente        → recent_award                 ce que le client veut savoir
2. notification récente    → recently_notified_contract   un acte réel, pas une victoire
3. décision vieillissante  → aging_award
4. décision périmée        → stale_award
5. décision incohérente    → invalid_award_date
6. parution récente        → recently_published_award
7. sinon                   → award_date_unknown
```

L'étape 1 passe **avant** tout : c'est ce qui garantit que `RECENT_AWARD` n'est
pas affaibli. Les quatre cas de R2 §1, vérifiés par test :

```text
award J-90  + notif J-1     award_clock=stale    notif=recent   → recently_notified_contract
award J-5   + notif J-1     award_clock=recent   notif=recent   → recent_award
award absent + notif J-3    award_clock=unknown  notif=recent   → recently_notified_contract
tout absent + publication J-2                    pub=recent     → recently_published_award
```

Deux comportements méritent d'être signalés, tous deux testés :

- **Une décision vieillissante cède la parole à une notification fraîche.**
  `award J-40 + notif J-1` ressort `recently_notified_contract` : l'attribution
  n'est plus une nouveauté, la notification l'est.
- **Une date de décision cassée ne fait plus perdre un fait de notification
  vrai.** `award 2002-08-17 + notif J-1` ressort `recently_notified_contract`,
  avec `award_clock.status = "invalid"` et la valeur brute `2002-08-17`
  conservée.

### Ce qui n'a pas bougé

```text
recent_award    ≤ 30 j        borne inchangée, testée à 30 et 31 jours
aging_award     31 à 60 j     borne inchangée, testée à 60 et 61 jours
stale_award     > 60 j        inchangé
protections     futur, > 10 ans, décision postérieure à sa parution — inchangées
```

Une notification périmée ne rattrape jamais rien :
`award J-90 + notif J-78` reste `stale_award`.

---

## 2. CLAIM SAFETY

Les trois formulations sont inchangées :

```text
RECENT_AWARD                 fr « {société} vient de remporter un marché public. »
                             en « {société} has recently won a public contract. »
RECENTLY_NOTIFIED_CONTRACT   fr « Un marché attribué à {société} vient d'être notifié. »
                             en « A public contract awarded to {société} has recently
                                  been notified. »
RECENTLY_PUBLISHED_AWARD     formulation de publication uniquement
```

Les quatre régressions demandées par §2 sont écrites et vertes :

```text
✔ attribution périmée + notification récente PRODUIT bien la formulation de notification
✔ aucune notification ne produit « vient de remporter », quelle que soit l'horloge
  d'attribution — testé sur {absente, périmée, vieillissante, invalide} × {fr, en}
✔ une attribution récente le reste même quand une autre horloge est récente aussi,
  et la notification reste lisible sur son horloge
✔ les trois dates brutes restent inspectables indépendamment
```

---

## 3. LINKAGE AGGREGATE

Passe réelle sur les 45 award-lots BOAMP à décision récente de la fenêtre
2026-08-11 → 2026-08-18, interrogés un par un contre `decp-2022-marches-valides`.

```text
BOAMP candidats testés                    45
  dont testables (2 SIRET présents)       37      82,2 %
  dont non testables                       8      17,8 %

DECP candidats retournés                   8

STRONG                                     4
PROBABLE                                   1
UNRESOLVED                                32
                                        ────
                                          37     l'agrégat se referme

conflits sur liens forts                   2
leurres rejetés                            2

taux de lien fort / testables           10,8 %
taux de lien fort / testés               8,9 %
```

**Direction : BOAMP → DECP uniquement.** L'API du BOAMP n'est pas interrogeable
par SIRET — ceux-ci sont enfouis dans le JSON eForms — donc le sens inverse
n'est pas mesurable. Le recouvrement rapporté est un **plancher**, pas un total.

### Preuve de précision disponible sur les liens forts

Les quatre liens reposent sur le triplet `acheteur × titulaire × date de
notification`. Trois d'entre eux concordent en plus sur un champ **indépendant
des clés de jointure** :

```text
26-79293  CON-0001   award 2026-07-24 → DECP 20262601101   + CPV concordant
                                                             (le closeout le résout vers 26-011)
26-80736  CON-0001   award 2026-08-03 → DECP 2026F20180    + CPV concordant
26-80916  CON-0001   award 2026-07-24 → DECP 26-012        + CPV concordant
26-80112  CON-0001   award 2026-07-23 → DECP 202607LOT03   + montant concordant, CPV divergent
                                                             → conflit diagnostiqué, rien écrasé
```

```text
accord CPV sur liens forts       3 / 4
accord montant sur liens forts   1 / 4
au moins un accord indépendant   4 / 4
```

La règle anti-faux-lien n'a **pas** été relâchée pour gonfler le taux. Les deux
leurres rejetés sont des enregistrements DECP partageant le couple
acheteur/titulaire mais divergeant sur la date — exactement le motif identifié
en SPEC-009E et reconfirmé en R1.

---

## 4. FRANCE CAPACITY — LES TROIS NOMBRES

### A. ÉVÉNEMENTS PUBLICS BRUTS / SEMAINE

```text
décisions d'attribution récentes, BOAMP       45     fenêtre observée de 7 jours,
                                                     non plafonnée
notifications de contrat récentes, DECP      383     recensement portail sur 7 jours

somme naïve                                  428     ⚠ CE N'EST PAS UN NOMBRE
                                                       D'OPPORTUNITÉS
```

L'avertissement est porté par la donnée elle-même, pas seulement par ce rapport :
le champ `warning` accompagne `naive_sum` dans l'artefact, et un test refuse que
la somme soit publiée sans lui.

### B. OPPORTUNITÉS CONTRACTUELLES UNIQUES / SEMAINE

```text
415 à 424
```

```text
recouvrement démontré (liens forts)                 4
recouvrement maximal possible                      13     4 forts + 1 probable
                                                          + 8 non testables
borne haute   428 − 4  = 424     on ne retire que les doublons DÉMONTRÉS
borne basse   428 − 13 = 415     on suppose que tout le non testé fait doublon
exact                    aucun   rapprochement partiel
```

**Aucun milieu n'est produit.** `UniqueContractCount` n'expose pas de champ
d'estimation, et un test le vérifie explicitement. La valeur exacte n'apparaît
que lorsque chaque candidat a pu être testé et qu'aucun lien n'est resté
« probable ».

Le recouvrement est faible, et la raison est structurelle plutôt que technique :
une décision d'attribution publiée cette semaine au BOAMP n'a pas encore été
notifiée — ou pas encore publiée dans les Données Essentielles. Les deux flux se
recoupent avec un décalage, pas au même instant.

### C. OPPORTUNITÉS PRÊTES POUR UN CLIENT / SEMAINE

```text
45 mesurées
```

```text
                              BOAMP (45)        DECP (383)
identifiant stable                 37               383
raison sociale publiée             45                 0
nom ET identifiant                 37                 0
nom récupéré par lien fort          0                 4
                                 ────              ────
PRÊT POUR UN CLIENT                45                 4      ← doublons des 45
résolvable en interne seulement     0               379
```

C'est la correction la plus lourde de R2. **Les 383 notifications hebdomadaires
de DECP ne portent aucun nom d'entreprise** : le schéma 2022 ne comporte pas de
champ de raison sociale. Quatre d'entre elles récupèrent un nom par lien fort
vers un avis BOAMP — mais ce sont les mêmes marchés que quatre des 45, donc ils
ne s'ajoutent pas.

```text
379 événements DECP par semaine sont des candidats résolvables en interne :
identité stable, aucun nom affichable. Ils ne sont PAS des signaux livrables.
```

La borne haute de C dépend des liens DECP → BOAMP que l'API du BOAMP ne permet
pas de chercher. Elle n'est pas estimée.

### Ce que R1 disait, et ce que R2 mesure

```text
R1   « 428 événements exploitables par semaine, un facteur 9,5 »
R2   45 opportunités prêtes pour un client par semaine
     415 à 424 marchés distincts, dont ~379 sans nom d'entreprise
```

---

## 5. FILES CHANGED

```text
NOUVEAUX
  src/signals/france/capacity.py            agrégat de liaison, encadrement unique,
                                            identité affichable
  tests/test_france_capacity.py             17 tests
  tests/fixtures/france/spec009e_r2_linkage.json   la passe de rapprochement gelée
  docs/reports/2026-08-18-spec009e-r2-multiclock-unique-signals.md

RÉÉCRITS
  src/signals/recency/policy.py             v0.3 — ClockAssessment, _assess_clock,
                                            _primary_status ; assess_recency dérive
  src/signals/research/spec009e_run.py      linkage_sweep(), france_capacity()
                                            remplace france_product_timing()

ÉTENDUS
  src/signals/recency/__init__.py           exporte ClockAssessment, ClockStatus, CLOCKS
  src/signals/france/__init__.py            exporte le module capacity
  tests/test_award_recency.py               +13 (horloges indépendantes)
  tests/test_award_claim_copy.py            +6  (formulation multi-horloges)
  tests/test_spec009e_france_study.py       +3 net (portés de R1 vers france_capacity)

INCHANGÉS — vérifiés
  src/signals/connectors/boamp/*            parser, sentinelles, curseur
  src/signals/connectors/decp/*             jeu 2022, filtre CDL, sémantique des dates
  src/signals/france/link.py                règles strong/probable/unresolved
  src/signals/domain/*                      contract_notification_date, SourceSystem
```

Diff sur le code suivi : **inchangé depuis R1** — 4 fichiers, 48 insertions.
Tout le reste de R2 vit dans des fichiers non suivis.

---

## 6. NON-REGRESSION MATRIX

```text
élément                                   état          vérification
choix du jeu DECP                         inchangé      decp-2022-marches-valides
BOAMP parser                              inchangé      boamp-adapter-v0.1, 21 tests
protections sentinelles                   inchangées    2000-01-01 / 1970-01-01 / CDL
SourceSystem += boamp, decp               inchangé      diff R1 intact
contract_notification_date                inchangé      3 tests dédiés
RECENT_AWARD ≤ 30 j                       inchangé      testé à 30 et 31 jours
AGING 31–60 · STALE > 60                  inchangés     testés aux quatre bornes
règle anti-faux-lien                       inchangée     france-link-v0.2, 2 leurres rejetés
Need Graph                                need-graph-v0.2            intact
Matching                                  icp-match-v0.2             intact
Signal Score                              signal-score-v0.2          intact
Contract Understanding                    contract-understanding-v0.3 intact
BKP                                       bkp-trade-v0.1             intact
Document Intelligence auto-accept         AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False
Commercial Verifier                       OFF, non touché
golds historiques                         non modifiés
résultat commercial SPEC-009C (64 %)      non re-mesuré, non modifié
commit SPEC-009D (1cd8628)                intact
politique FNSimple / MAPA                 inchangée — écartés et comptés
pricing / SaaS / acquisition              non touchés
```

```bash
$ git status --porcelain src/signals/understanding src/signals/needs \
                         src/signals/matching src/signals/documents
(vide)
```

Aucun nouveau benchmark commercial.

### Tests dont la prémisse a été renversée par R2

Trois, tous mis à jour en conservant l'invariant protégé — jamais supprimés.

```text
test_an_old_award_date_is_not_rescued_by_a_fresh_notification
  R1 attendait `stale_award` ; R2 §1 impose `recently_notified_contract`.
  → renommé …_is_never_rescued_into_award_recency. Il vérifie maintenant ce qui
    compte réellement : award_clock reste `stale`, may_claim_just_won reste faux.

test_a_capped_sample_is_never_extrapolated_into_a_weekly_volume
test_the_weekly_won_volume_still_comes_from_the_boamp_window
  Visaient `france_product_timing`, remplacée par `france_capacity`.
  → portés sur la nouvelle fonction, invariant identique. Deux tests ajoutés :
    la somme naïve n'est publiable qu'avec son avertissement, et le comptage
    unique ne peut jamais égaler cette somme.
```

Aucune métrique historique n'a été modifiée.

---

## 7. TESTS / GATES

```bash
$ uv run pytest -q
2010 passed in 16.33s        # 1971 après R1, + 39

$ uv run ruff check .
All checks passed!

$ git diff --check
(rien)

$ uv run ruff format --check .
1 file would be reformatted
  docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md
```

**Tests ignorés : zéro.**

```bash
$ git status --porcelain
 M src/signals/domain/awards.py
 M src/signals/domain/events.py
 M tests/test_model_invariants.py
 M tests/test_spec009d_audit.py
A  tests/fixtures/signal100/spec009c_bench.json
A  tests/fixtures/signal100/spec009c_corpus.json
A  tests/fixtures/signal100/spec009c_gold.json
?? docs/reports/2026-08-18-spec009e-r1-current-decp.md
?? docs/reports/2026-08-18-spec009e-r2-multiclock-unique-signals.md
?? src/signals/connectors/boamp/  src/signals/connectors/decp/
?? src/signals/france/  src/signals/recency/
?? src/signals/research/spec009e.py  src/signals/research/spec009e_run.py
?? tests/fixtures/france/
?? tests/test_award_claim_copy.py  tests/test_award_recency.py
?? tests/test_boamp_adapter.py  tests/test_boamp_client_cursor.py
?? tests/test_contract_notification_date.py  tests/test_decp2022_adapter.py
?? tests/test_france_capacity.py  tests/test_france_decp_link.py
?? tests/test_source_date_semantics.py  tests/test_spec009e_france_study.py
   (+ artefacts SPEC-009C antérieurs, hors périmètre)

$ git diff --stat
 src/signals/domain/awards.py   | 21 ++++++++++++++++++++-
 src/signals/domain/events.py   | 10 ++++++++--
 tests/test_model_invariants.py |  5 ++++-
 tests/test_spec009d_audit.py   | 27 ++++++++++++++++-----------
 4 files changed, 48 insertions(+), 15 deletions(-)
```

### Compte par fichier

```text
test_award_recency.py              44      (+13 R2)
test_award_claim_copy.py           54      (+6  R2)
test_france_capacity.py            17      (nouveau)
test_spec009e_france_study.py      23      (+3 net)
test_france_decp_link.py           21
test_decp2022_adapter.py           21
test_boamp_adapter.py              21
```

### SHA-256 des artefacts R2

```text
spec009e_r2_linkage.json     0,01 Mo
  eb8ccb7c525c401e62011915671f1da83b69f5e077e84019ab5fd583b700c2e9
spec009e_france.json         0,86 Mo
  ddfefee3608abcf27b51cf03b8a3c28d53049bcf4ec6c8e81df31aa8c289b1af
spec009e_decp2022_raw.json   1,99 Mo   (inchangé depuis R1)
  10f63777d09936f36cefd5a184463185b7e82e0fe2c4da832cc1c65395ba5d40
spec009e_boamp_raw.json     13,86 Mo   (inchangé depuis R1)
  10409f6f63b5960454d0cb9eec65d73aefddfca1aa6c744626f29f8fa659f6a5
```

---

## VERDICT

```text
RECENT AWARD FOUNDATION READY AFTER R2
```

```text
horloges indépendantes                   ✔ award / notification / publication jugées
                                           séparément ; 13 tests dont les 4 cas de §1
RECENT_AWARD non affaibli                ✔ bornes 30/31/60/61 inchangées ; la décision
                                           récente garde la priorité de dérivation
notification ne masque jamais une         ✔ award_clock reste `stale` ou `invalid` ;
fraîcheur d'attribution                     aucune formulation de victoire, 4×2 cas testés
dates brutes indépendamment inspectables ✔ trois ClockAssessment + trois dates sources
agrégat de liaison complet               ✔ 45 testés / 37 testables / 4-1-32 / 2 conflits
                                           / 2 leurres ; l'agrégat se referme par contrat
preuve de précision sur liens forts      ✔ 4/4 avec un accord indépendant des clés
                                           de jointure (CPV 3, montant 1)
règle anti-faux-lien non relâchée        ✔ france-link-v0.2 inchangée
identité client ≠ identifiant stable     ✔ 379 événements DECP/semaine classés
                                           « résolvables en interne », pas livrables
trois nombres séparés, bornes assumées   ✔ A 45+383 · B 415–424 · C 45 ; aucun milieu
non-régression                           ✔ moteurs intacts, 48 lignes de diff suivi
tests verts                              ✔ 2 010 passed, 0 ignoré, ruff clean
```

Ce que le verdict ne dit pas, et qui doit peser sur la décision produit :

**La France livre 45 opportunités prêtes pour un client par semaine, pas 428.**
Les 379 notifications DECP restantes sont réelles, fraîches et parfaitement
identifiées — mais anonymes. Les transformer en signaux livrables demanderait de
résoudre un SIRET en raison sociale, c'est-à-dire l'enrichissement d'entreprise
que R2 §5 interdit explicitement de construire ici. C'est, à mon sens, la
question ouverte que SPEC-010 devra trancher avant de promettre un volume.

---

**Rien n'est committé.** Aucune suite n'est engagée : ni SPEC-010, ni base de
données, ni auth, ni frontend, ni déploiement, ni Acquisition Engine. En attente
de la revue superviseur.
