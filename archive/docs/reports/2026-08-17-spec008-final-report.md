# SPEC-008 — Target ICP Schema + Matching Engine + Signal Score V0

Rapport final. Date : 2026-08-17. Aucun commit (§54).

> **Suite — SPEC-008R.** Les questions ouvertes **1** et **2** ci-dessous ont été refermées par
> `docs/reports/2026-08-17-spec008r-coherence-closeout.md` : les configurations géographiques
> contradictoires sont désormais refusées à la construction, et la bande `strong` ne peut plus
> exister hors d'une décision `show`. `SCORE_POLICY_VERSION` passe à `signal-score-v0.2` ; les
> décisions, les scores et les trois empreintes gelées sont inchangés.

---

## FILES CHANGED

Tous les fichiers ci-dessous sont **nouveaux**. Aucun fichier existant de `src/` n'a été modifié
(vérifié : `git diff --stat HEAD -- src/signals/domain src/signals/needs src/signals/understanding
src/signals/documents` est vide).

| Fichier | Rôle |
|---|---|
| `src/signals/matching/__init__.py` | surface publique du module |
| `src/signals/matching/icp.py` | `TargetICP`, `Territory`, `ValueThreshold`, littéraux de politique |
| `src/signals/matching/model.py` | `HardFilterResult`, `SignalScoreComponent`, `ScoredSignalMatch` |
| `src/signals/matching/engine.py` | `MatchingEngine` — filtres durs puis score |
| `src/signals/matching/reference.py` | bibliothèque de 8 ICPs de référence (fixtures de benchmark) |
| `tests/test_icp_model.py` | invariants du schéma ICP + frontière client/acquisition |
| `tests/test_matching_engine.py` | filtres, score, décision, déterminisme, non-régression |
| `tests/test_matching_adversarial.py` | les 20 tests adverses §45 A–T |
| `tests/test_matching_fixtures.py` | gel §42 : SHA-256, composition, disjonction |
| `tests/fixtures/matching/reference_icps.json` | bibliothèque d'ICPs gelée |
| `tests/fixtures/matching/signal_match_final_corpus.json` | corpus held-out gelé |
| `tests/fixtures/matching/signal_match_final_gold.json` | gold final gelé |
| `docs/reports/2026-08-17-spec008-score-component-study.md` | étude préalable des composants de score |
| `docs/reports/2026-08-17-spec008-icp-match-rubric-v1.md` | rubrique d'adjudication v1 |
| `docs/reports/2026-08-17-spec008-final-report.md` | ce rapport |

---

## TARGET ICP MODEL

`TargetICP` est un `CanonicalModel` (`extra="forbid"`) qui décrit **l'offre d'un client**, jamais son
outillage commercial.

| Champ | Type | Rôle |
|---|---|---|
| `icp_id`, `name` | `NonEmptyStr` | identité |
| `offer_summary` | `str` (défaut `""`) | **déclaratif et inerte** — n'entre dans aucun calcul |
| `primary_need_categories` | `tuple[NeedCategory, ...]` | besoins qui déclenchent le feed principal |
| `secondary_need_categories` | `tuple[NeedCategory, ...]` | besoins qui rapportent moins |
| `geography_basis` | `place_of_performance` \| `winner_location` \| `either` \| `ignore` | *quelle* localisation compte |
| `geography_policy` | `required` \| `preferred` \| `ignored` | *à quel point* elle contraint |
| `territories` | `tuple[Territory, ...]` | `country` + `subdivision_code`/`subdivision_scheme` |
| `included_contract_types` / `excluded_contract_types` | `tuple[ContractType, ...]` | filtre type |
| `included_sectors` / `excluded_sectors` | `tuple[Sector, ...]` | filtre secteur |
| `value_thresholds` | `tuple[ValueThreshold, ...]` | un seuil **par devise**, aucune conversion |
| `unknown_value_policy` | `exclude` \| `allow_with_penalty` \| `allow_neutral` | montant absent |
| `maximum_signal_age_days` | `int`, `0 < n ≤ 730` | fraîcheur maximale acceptée |
| `preferred_timings` | `tuple[NeedTiming, ...]` | timings valorisés |
| `source_modes_allowed` | `tuple[SourceMode, ...]` | modes de production acceptés |

§50 autorisait `NeedPreference` « ou équivalents minimaux » : la préférence de besoin est ici portée
par les deux tuples `primary_need_categories` / `secondary_need_categories` plutôt que par un modèle
dédié — même expressivité, un modèle de moins, et l'exclusivité primaire/secondaire devient un
invariant vérifiable plutôt qu'une convention.

Invariants validés à la construction — **sept** dans `_un_profil_coherent`, plus deux portés par les
sous-modèles :

1. au moins une `primary_need_categories` — un ICP sans besoin primaire ne décrit aucune offre ;
2. aucune catégorie à la fois primaire et secondaire ;
3. aucun type de contrat à la fois inclus et exclu ;
4. aucun secteur à la fois inclus et exclu ;
5. `geography_policy = "required"` exige des `territories` — sinon la règle serait inévaluable ;
6. une seule `ValueThreshold` par devise — aucune conversion n'étant permise, deux seuils seraient ambigus ;
7. `source_modes_allowed` non vide ;
8. `Territory` : `subdivision_code` sans `subdivision_scheme` est refusé ;
9. `ValueThreshold` : `minimum_amount ≤ maximum_amount`.

`TargetICP` est instanciable autant de fois qu'on veut : aucune notion de plan, quota, entitlement,
paywall ou checkout n'existe dans SPEC-008 (§48). Les limites commerciales restent à SPEC-012.

---

## CLIENT / ACQUISITION BOUNDARY

Test d'architecture `test_icp_model.py::test_matching_module_does_not_reference_acquisition_engine`.

Première version naïve (recherche de sous-chaînes sur le fichier entier) : **rejetée**, elle signalait
le mot « mailbox » figurant dans une de mes propres docstrings. Version retenue : parcours **AST** du
module, collecte des `Import`/`ImportFrom` **et** de tous les identifiants (`Name`, `Attribute`,
`arg`, noms de classes et de fonctions, clés de littéraux), en excluant explicitement les nœuds de
docstring par `id()`. Le test échoue si l'un de ces termes apparaît comme **code** :

`apollo`, `instantly`, `campaign`, `contact`, `mailbox`, `email`, `prospect`, `reply_rate`,
`outbound`, `sequence`, `deliverability`, `acquisition_cost`, `personalization`.

Résultat : aucune occurrence dans `icp.py`, `model.py`, `engine.py`, `reference.py`.
Le module `signals.matching` n'importe rien hors `signals.domain`, `signals.understanding`,
`signals.needs` et la bibliothèque standard.

---

## ICP MATCH RUBRIC V1

`docs/reports/2026-08-17-spec008-icp-match-rubric-v1.md`, version `icp-match-rubric-v1`.

Elle définit **7 filtres durs ordonnés** et **4 grades** (`strong_match`, `plausible_match`,
`no_match`, `insufficient_data`), et fige **8 points de doctrine tranchés d'avance** pour que deux
adjudicateurs indépendants convergent sans se parler. Le plus structurant :

> Le pays de l'acheteur n'est **pas** une localisation au sens de `geography_basis`. Les seules bases
> nommées par la rubrique sont le lieu d'exécution et la localisation du titulaire. Si
> `place_country` est nul, une géographie `required` devient **inévaluable** (`insufficient_data`),
> et une géographie `preferred` **plafonne** le grade à `plausible_match`.

Ce point est précisément celui qu'a produit l'arbitrage DEV (les 5 seuls désaccords), et son
inscription dans la rubrique explique l'accord parfait obtenu sur le gold final.

---

## GOLD STABILITY STUDY

Deux passes d'adjudication indépendantes (A et B), toutes deux exécutées **avant** tout run du
moteur, puis arbitrage individuel des désaccords à partir des faits sources.

| Gold | Paires | Accord A/B | Désaccords | Nature |
|---|---|---|---|---|
| DEV | 480 | **98,96 %** (475/480) | 5 | tous `strong_match` vs `plausible_match`, tous sur `icp-national-supplier` avec `place_country` nul |
| FINAL | 680 | **100 %** (680/680) | 0 | — |

Gate §35 (accord ≥ 85 %) : **PASS** sur les deux golds.

Adjudicateur : Claude Fable 5 (`claude-fable-5`). Vérification faite sur le transcript de session :
aucun `model` n'a été passé aux sous-agents d'adjudication, ils ont donc hérité du modèle de session.
Les notes de mémoire de session mentionnant « Opus 5 » étaient une étiquette erronée de ma part et
sont corrigées ici — la source d'autorité est le transcript, pas la note.

**Limite à retenir** : l'accord de 100 % sur le gold final ne mesure pas une vérité externe. Il
mesure que la rubrique est devenue assez explicite pour que deux passes du **même** modèle
convergent. Les deux passes partagent donc un biais corrélé, et le chiffre doit se lire comme
« la doctrine est reproductible », pas comme « la doctrine est correcte ».

---

## HARD FILTER POLICY

Sept filtres, **absolus** et **ordonnés**, évalués avant tout calcul de score. Aucun ne peut être
compensé par un autre composant.

| # | Filtre | Échec ⇒ |
|---|---|---|
| 1 | `source_mode` | mode de source non autorisé |
| 2 | `need_overlap` | aucun besoin commun entre le graphe de besoins et l'ICP |
| 3 | `contract_type` | type de marché explicitement exclu par l'ICP |
| 4 | `sector` | secteur hors périmètre de l'ICP |
| 5 | `signal_age` | publication plus vieille que `maximum_signal_age_days` |
| 6 | `geography` | territoire incompatible selon `geography_basis` |
| 7 | `value_threshold` | montant hors bornes de la devise correspondante |

Chaque filtre renvoie un `HardFilterResult(name, passed, evaluable, detail)`. La distinction
`passed` / `evaluable` est essentielle : un filtre **non évaluable** (fait absent) ne produit jamais
un échec fabriqué — il produit `insufficient_data` ou une neutralisation, selon la politique de
l'ICP. C'est ce qui empêche le moteur de transformer une absence de donnée en jugement négatif.

---

## GEOGRAPHY POLICY

Deux axes indépendants, délibérément séparés :

- **`geography_basis`** — *quelle* localisation compte : `place_of_performance`, `winner_location`,
  `either`, `ignore`.
- **`geography_policy`** — *à quel point* elle contraint : `required` (filtre dur), `preferred`
  (pas de filtre, mais plafond de score et de grade), `ignored` (le composant géographie est retiré
  du dénominateur, pas mis à zéro).

Règles de fond :

1. Le **pays de l'acheteur n'est pas une localisation**. Il n'entre dans aucune des quatre bases.
2. Une subdivision ne matche que si le **schéma** est identique (`subdivision_scheme`). Un code
   `ZH` en schéma cantonal suisse ne matche pas un `ZH` d'un autre référentiel — absence de schéma
   commun ⇒ pas de match, jamais un match par coïncidence de chaîne.
3. `geography_policy = "required"` avec localisation absente ⇒ `insufficient_data`, jamais `exclude`.
   Le signal n'est pas mauvais, il est inconnu.
4. `geography_policy = "ignored"` retire les 20 points du maximum applicable ; le score normalisé est
   recalculé sur le dénominateur réduit (normalisation N/A), de sorte qu'un ICP sans contrainte
   géographique n'est pas structurellement pénalisé face à un ICP qui en a une.

---

## VALUE POLICY

Le seuil est **par devise**. Le moteur cherche la `ValueThreshold` dont la devise correspond à celle
du montant du marché ; il ne convertit jamais, et n'invente jamais de taux.

| Situation | Comportement |
|---|---|
| Montant connu, seuil de la devise présent, dans les bornes | filtre passé, points économiques attribués |
| Montant connu, hors bornes | `value_threshold` échoue ⇒ `exclude` |
| Montant connu, **aucun seuil pour cette devise** | filtre **non évaluable** — aucune comparaison inventée, aucun échec |
| Montant absent, `unknown_value_policy = "exclude"` | `value_missing` ⇒ écarté |
| Montant absent, `allow_with_penalty` | passe, composant économique pénalisé |
| Montant absent, `allow_neutral` | passe, composant économique retiré du dénominateur |

Un ICP sans aucune `ValueThreshold` est dans l'état `no_threshold_configured` : le filtre est passé
par construction et les points économiques sont attribués sur le seul fait que le montant existe.

---

## FRESHNESS / TIMING POLICY

- Plafond dur global : `MAX_SIGNAL_AGE_DAYS = 730` (deux ans — au-delà, un avis d'attribution n'est
  plus un signal commercial). Aucun ICP ne peut demander plus : le champ est borné par le type.
- Plafond par ICP : `maximum_signal_age_days`. Au-delà, le filtre `signal_age` échoue ⇒ `exclude`.
- En deçà, la fraîcheur alimente le composant `freshness_timing` (15 points), décroissant avec l'âge.
- **Timing inconnu ⇒ zéro point positif.** Une date de début ou de fin de contrat absente ne peut
  jamais créer de points ; elle ne crée pas non plus de pénalité fabriquée.

Le held-out est délibérément bimodal sur ce point (voir plus bas) : 45 lots à 83 jours contre 40 lots
à 6–17 jours, ce qui met le filtre d'âge sous tension réelle plutôt que de le laisser inerte.

---

## SCORE COMPONENT STUDY

`docs/reports/2026-08-17-spec008-score-component-study.md`. Étude conduite **avant** de figer les
poids, sur 100 award-lots, pour ne pondérer que des signaux réellement présents.

| Composant candidat | Mesure sur 100 lots | Décision |
|---|---|---|
| Adresse du titulaire | **0/100** renseignée | `winner_fit` **retiré** |
| Subdivision territoriale | **0/100** renseignée | pas de sous-score subdivision |
| Confiance du graphe de besoins | constante à `medium` | **retirée du score** (variance nulle) |
| Besoins dérivés | 67/100 lots en ont | conservé, composant principal |

Retirer `winner_fit` et `confidence` n'est pas une simplification de confort : pondérer un champ
vide à 0/100 aurait produit un score dont une part fixe est du bruit, et une confiance constante
n'ordonne rien. Les deux auraient dégradé le classement sans rien expliquer.

---

## FINAL SCORE WEIGHTS

| Composant | Points max |
|---|---|
| `need_offer_fit` | **45** |
| `economic_impact` | **20** |
| `geography` | **20** |
| `freshness_timing` | **15** |
| **Total** | **100** |

Attribution du besoin : `PRIMARY_FIT_POINTS = 45` si un besoin de rôle `primary` est touché,
`SECONDARY_FIT_POINTS = 25` si seuls des besoins `secondary` le sont, plus `SECOND_NEED_BONUS = 5`
si au moins deux besoins distincts sont touchés — le total du composant restant **plafonné à 45**.

Normalisation N/A : tout composant non applicable (géographie ignorée, valeur neutre) est retiré
**du numérateur et du dénominateur**. Le score normalisé vaut `round(100 × raw / maximum_applicable)`.

---

## MATCH DECISION THRESHOLDS

```
SHOW_THRESHOLD       = 60
BORDERLINE_THRESHOLD = 40
STRONG_BAND          = 75
PROMISING_BAND       = 55
```

Règle de décision, telle qu'itérée une fois sur le DEV :

```python
geography_ok = geography_status in ("match", "ignored")
economic_ok = value_status in ("within", "no_threshold_configured")
decision = (
    "show"
    if normalized >= SHOW_THRESHOLD and primary_hits and geography_ok and economic_ok
    else "borderline"
    if normalized >= BORDERLINE_THRESHOLD
    else "exclude"
)
```

Un score élevé ne suffit **pas** à déclencher `show` : il faut en plus qu'un besoin **primaire** soit
touché et que la géographie et la valeur soient positivement établies. C'est exactement cette
conjonction qui aligne `show` sur la définition rubrique de `strong_match`, et c'est la seule
itération de règle qu'a demandée la phase DEV.

---

## SCORE / CONFIDENCE SEPARATION

`SignalConfidence = Literal["medium", "low"]`. La valeur `"high"` **n'existe pas** dans le type.

La séparation est structurelle, pas conventionnelle :

- le **score** dit *à quel point ce signal ressemble à l'offre du client* ;
- la **confiance** dit *à quel point les faits sous-jacents sont solides* ;
- ils ne sont jamais multipliés, additionnés ni fusionnés.

Un signal peut être à 87/100 en confiance `medium` : c'est le cas normal en mode `metadata`, où
l'inférence de besoin reste une inférence. Interdire `"high"` au niveau du type rend la promesse
inviolable par une future régression : aucun code ne peut hausser la confiance sans changer le type.

La triade SPEC-007 reste tenue en amont : **FAIT ≠ INFÉRENCE ≠ ACHAT CERTAIN**.

---

## EXPLANATION MODEL

Tout `ScoredSignalMatch` porte :

- `positive_reasons` / `negative_reasons` — phrases courtes, dérivées des faits, pas du texte libre ;
- `score_components` — un `SignalScoreComponent(name, points, maximum_points, detail)` par composant ;
- `hard_filter_results` — les 7 verdicts, y compris ceux qui sont passés ;
- `evidence_refs` — les `Evidence` des faits effectivement utilisés ;
- `matched_needs` — les besoins touchés.

Trois invariants sont validés par le modèle lui-même, donc impossibles à contourner :

1. `sum(component.points) == raw_points`
2. `sum(component.maximum_points) == maximum_applicable_points`
3. `normalized_score == round(100 × raw_points / maximum_applicable_points)`

Et une décision `show` ou `borderline` **sans** `positive_reasons`, `score_components`,
`evidence_refs` et `matched_needs` lève une `ValidationError`. Un score non expliqué n'est pas un
score dégradé : c'est un modèle invalide.

---

## REFERENCE ICP LIBRARY

`REFERENCE_ICPS`, version `reference-icps-v0.1` — **8 ICPs de fixtures**, jamais des clients réels.

| ICP | Ce qu'il exerce |
|---|---|
| `icp-staffing-ch` | main-d'œuvre, géographie `required` CH |
| `icp-plant-hire-ch` | location de matériel, `unknown_value_policy = "exclude"`, âge court |
| `icp-materials-eu` | matériaux, seuil EUR |
| `icp-ppe-safety-ch` | EPI/sécurité, besoins secondaires |
| `icp-waste-ch` | **contrôle négatif** — ne doit presque jamais matcher |
| `icp-subcontracting-eu` | sous-traitance, seuil élevé |
| `icp-national-supplier` | fournisseur national, géographie `preferred` |
| `icp-remote-specialist` | spécialiste à distance, géographie `ignore` |

Le contrôle négatif est là pour attraper un moteur trop généreux : `icp-waste-ch` obtient
**0 `strong_match`** dans le gold final, comme attendu.

---

## DEV CORPUS

- **60 award-lots** (25 TED + 35 SIMAP), issus de `tests/fixtures/contract100/awards.json`
- **× 8 ICPs = 480 paires**
- Gold DEV : 353 `no_match`, 57 `strong_match`, 56 `plausible_match`, 14 `insufficient_data`
- Accord A/B **98,96 %**, 5 désaccords arbitrés individuellement

---

## DEV RESULTS

Première évaluation DEV : **FAIL** (3 gates). Une seule itération de règle a suivi (alignement de
`show` sur `strong_match`, cf. *Match decision thresholds*), puis :

| Métrique | DEV | Gate | Verdict |
|---|---|---|---|
| show precision | **100 %** (57/57) | ≥ 95 % | PASS |
| critical false shows | **0** | = 0 | PASS |
| strong-match recall | **100 %** | ≥ 75 % | PASS |
| hard-filter violations | **0** | = 0 | PASS |
| pairwise ranking | **100 %** | ≥ 90 % | PASS |
| macro precision@5 | **100 %** (4 ICPs) | ≥ 80 % | PASS |
| explanation coverage | **100 %** | = 100 % | PASS |
| evidence coverage | **100 %** | = 100 % | PASS |
| component trace coverage | **100 %** | = 100 % | PASS |
| determinism | **100 %** | = 100 % | PASS |
| médianes | 87 > 67 > 0 | strong > plausible > no_match | PASS |

**11/11 PASS.** Une correction de ma propre métrique est à signaler : je comptais initialement tout
`show` non-`strong` comme *critical false show*, alors que §38 réserve ce terme aux mismatches durs
(`no_match` / `insufficient_data`). La définition a été corrigée avant l'itération, et les paires
`insufficient_data` — qui n'ont pas de note — sont exclues du classement par paires.

---

## FRESH HELD-OUT COMPOSITION

Corpus acquis **après** le gel de la phase DEV, via les connecteurs de production TED et SIMAP.

- **85 award-lots** répartis sur **80 notices distinctes**
- **45 TED + 40 SIMAP**
- `as_of = 2026-08-20`
- **× 8 ICPs = 680 paires**
- Montant connu : 72/85 lots
- Pays d'exécution : 16 pays représentés (DE 11, CH 11, FR 5, RO 4, PL 4, NL 3, ES 3, CZ 3, …),
  **33 lots sans pays d'exécution publié** — c'est ce qui exerce réellement `insufficient_data`
- Âges de publication **bimodaux** : 45 lots à 83 jours, 40 lots entre 6 et 17 jours

**Disjonction** vérifiée à quatre niveaux contre le corpus DEV **et** contre le held-out SPEC-007,
et verrouillée par `tests/test_matching_fixtures.py` :

| Niveau | Champs d'identité comparés | Intersection DEV | Intersection SPEC-007 |
|---|---|---|---|
| publication | `(source, notice)` | **0** | **0** |
| notice | `provenance.(source_system, source_notice_id)` | **0** | **0** |
| procédure | `provenance.(source_system, source_procedure_id)` | **0** | **0** |
| identité d'award | `event_ref.(source_system, source_notice_id, notice_version)` + `source_award_id` + `lot.identifier` | **0** | **0** |

Le test vérifie aussi que chacun de ces ensembles est **non vide**, pour qu'une extraction cassée ne
puisse pas se faire passer pour une disjonction. Côté corpus final : 80 publications, 80 notices et
80 procédures distinctes pour 85 award-lots — plusieurs lots partagent une notice, ce qui est le
comportement attendu et ce qu'exerce le test adverse S. 73 notices SIMAP candidates ont été
explicitement écartées à l'acquisition parce que déjà utilisées.

Gold final : 556 `no_match`, 57 `strong_match`, 50 `plausible_match`, 17 `insufficient_data`.
Répartition des `strong_match` par ICP : `icp-remote-specialist` 26, `icp-national-supplier` 14,
`icp-ppe-safety-ch` 9, `icp-staffing-ch` 7, `icp-materials-eu` 1, et **0** pour `icp-waste-ch`,
`icp-plant-hire-ch`, `icp-subcontracting-eu`.

---

## FINAL CORPUS SHA256

```
441f0d10614ea1ad05d5948b530a9dab22f9fba7d25143b14aa66435cf62c006
```

## FINAL GOLD SHA256

```
7e183446b7bfa63dc18e153c5ade2edb6ffce7565df354cc809b3e6ece75b583
```

## REFERENCE ICP SHA256

```
698cb112eaa6478eb4680e8513cf036dc22d7651437a356f0637967361400fb2
```

Versions gelées : `MATCH_RUBRIC_VERSION = icp-match-rubric-v1`,
`MATCH_POLICY_VERSION = icp-match-v0.1`, `SCORE_POLICY_VERSION = signal-score-v0.1`,
`REFERENCE_ICP_LIBRARY_VERSION = reference-icps-v0.1`.

**CORPUS IMMUTABLE — GOLD IMMUTABLE — ICPS IMMUTABLE — WEIGHTS IMMUTABLE — THRESHOLDS IMMUTABLE —
POLICY IMMUTABLE.** Le gel a précédé le run ; les trois empreintes sont verrouillées par
`tests/test_matching_fixtures.py`.

---

## FINAL RESULTS

Run unique sur le held-out frais, 680 paires.

| Métrique | Valeur | Gate | Verdict |
|---|---|---|---|
| **show precision** | **100 %** (57/57, 0 faux positif) | ≥ 95 % | **PASS** |
| **critical false shows** | **0** | = 0 | **PASS** |
| **strong-match recall** | **100 %** (57/57, 0 faux négatif) | ≥ 75 % | **PASS** |
| **hard-filter violations** | **0** | = 0 | **PASS** |
| **pairwise ranking accuracy** | **100 %** | ≥ 90 % | **PASS** |
| **precision@5** | **100 %** (macro, 4 ICPs à ≥ 5 strong) | ≥ 80 % | **PASS** |
| **explanation coverage** | **100 %** | = 100 % | **PASS** |
| **evidence coverage** | **100 %** | = 100 % | **PASS** |
| **component trace coverage** | **100 %** | = 100 % | **PASS** |
| **determinism** | **100 %** | = 100 % | **PASS** |

precision@10 (non gaté) : 90 %.

Décisions produites : 57 `show`, 37 `borderline`, 420 `exclude`, 166 `insufficient_data`.

**Score distributions** (score normalisé 0–100) :

| Grade gold | n | p25 | médiane | p75 |
|---|---|---|---|---|
| `strong_match` | 57 | 84 | **87** | 87 |
| `plausible_match` | 50 | 28 | **60** | 67 |
| `insufficient_data` | 17 | 0 | **0** | 0 |
| `no_match` | 556 | 0 | **0** | 0 |

Ordre `strong > plausible > no_match` respecté (87 > 60 > 0) : **PASS**.

L'intervalle interquartile de `plausible_match` est large (28–67), là où `strong_match` est très
resserré (84–87). C'est le comportement attendu : `plausible_match` regroupe des cas plafonnés pour
des raisons hétérogènes (géographie `preferred` sans pays, besoin secondaire seul, valeur neutre),
qui n'ont aucune raison de converger vers une même note.

**11/11 gates PASS sur le held-out frais**, sans aucune itération après le gel.

---

## ADVERSARIAL RESULTS

`tests/test_matching_adversarial.py` — **20 tests écrits, 20 passés, 0 échec, 0 divergence** avec les
énoncés §45. Aucun mock : moteur, Need Graph et modèles réels.

| # | Attendu §45 | Observé |
|---|---|---|
| **A** | besoin exact, mauvaise géographie `required` → `exclude` | `exclude` |
| **B** | bonne géographie, aucun besoin commun → `exclude` | `exclude`, via `need_overlap` |
| **C** | montant connu sous le minimum → `exclude` | `exclude`, via `value_threshold` |
| **D** | montant absent + `unknown_value_policy="exclude"` | `insufficient_data` — `value_missing` est `passed=False, evaluable=False` |
| **E** | devise sans seuil → aucune comparaison inventée | aucun échec de seuil fabriqué, `economic_impact = 0` |
| **F** | type de contrat exclu → `exclude` | `exclude`, via `contract_type` |
| **G** | secteur inconnu → jamais positif par défaut | filtre passé, aucun composant `sector`, aucune raison positive sectorielle |
| **H** | publication trop ancienne → `exclude` | `exclude`, via `signal_age` |
| **I** | timing inconnu → aucun point positif | 0 point de timing, et aucune pénalité fabriquée |
| **J** | winner OK / lieu KO → suit `geography_basis` | `place_of_performance` → `exclude` ; `winner_location` → `insufficient_data` ; `either` → `exclude` ; `ignore` → non exclu |
| **K** | subdivision de schéma différent → aucun faux match | `exclude`, et le code ne fuit ni dans le détail ni dans les limitations |
| **L** | primaire > secondaire | primaire strictement au-dessus, toutes choses égales |
| **M** | plusieurs besoins → score plafonné | 3 besoins primaires donnent **exactement** le même `need_offer_fit` (45/45) qu'un seul |
| **N** | mode `metadata` → confiance max `medium` | `medium`, `"high"` inexistant dans le type |
| **O** | sortie SPEC-006 jamais utilisée | `AUTO_DOCUMENT_REQUIREMENTS_ENABLED is False`, aucun import `signals.documents` (AST sur les 5 modules), aucun champ documentaire, `extra="forbid"` rejette l'injection |
| **P** | breakdown exact | les trois égalités de somme et de normalisation tiennent |
| **Q** | score sans explication → invalide | `ValidationError` |
| **R** | aucun champ acquisition/campagne | absent de `TargetICP` et de `ScoredSignalMatch` |
| **S** | deux lots d'une même notice → distincts | décisions **et** `model_dump()` différents |
| **T** | répétition déterministe | `model_dump()` identiques |

Trois énoncés étaient ambigus et ont été tranchés explicitement plutôt que contournés :

- **D** — le test dérive l'attendu de l'évaluabilité (`exclude` si le filtre est évaluable, sinon
  `insufficient_data`) au lieu de figer une valeur, et assertionne sur le filtre valeur **nommément**,
  parce que sans montant le Need Graph ne produit aucun besoin et que `need_overlap` échoue aussi :
  assertionner sur le seul verdict global aurait testé le mauvais filtre.
- **J** — seul `geography_basis` varie ; `geography_policy="required"` et `territories=(CH,)` restent
  fixes, gagnant CH et lieu d'exécution FR. `winner_location` donne `insufficient_data` et non un
  faux positif, ce qui est le comportement voulu au §14 puisque aucune adresse de gagnant n'est
  publiée dans le corpus.
- **K** — le moteur ne compare que le pays ; l'adversaire pose donc le **même** code (`FR10`) sous
  deux schémas différents (`ISO-3166-2` et `NUTS`) avec des pays différents, ce qui teste réellement
  l'absence de match par coïncidence de chaîne.

Le test **O** mérite d'être noté pour sa méthode : un grep textuel aurait été trompeur, `engine.py`
et `model.py` contenant légitimement le mot « documentaire » dans des docstrings et une limitation.
La vérification est donc structurelle (AST des imports + inspection des champs + `extra="forbid"`),
comme le test de frontière §46.

---

## SPEC-006 / SPEC-007 NON-REGRESSION

| Vérification | Résultat |
|---|---|
| `AUTO_DOCUMENT_REQUIREMENTS_ENABLED` | **`False`** — inchangé, `document_supported` non réactivé |
| Sortie expérimentale SPEC-006 utilisée par le matching | **aucune** (test adverse O) |
| `need-graph-v0.1` | **inchangé** |
| `need-rules-v0.4` (`RULE_LIBRARY_VERSION`) | **inchangé** |
| Fichiers modifiés dans `src/signals/{domain,needs,understanding,documents}` | **aucun** (`git diff --stat HEAD` vide) |
| Résultats SPEC-007 reproductibles | oui — suite SPEC-007 verte |

Preuve structurelle plutôt que déclarative : la liste complète des imports non-standard de
`engine.py` est `signals.matching.icp`, `signals.matching.model`, `signals.needs`,
`signals.needs.features` et `signals.understanding.model`. **`signals.documents` n'y figure pas** —
le moteur ne peut pas consommer une sortie SPEC-006 même par accident.

De même, `offer_summary` n'apparaît dans `engine.py` que dans une docstring : aucun texte libre
n'entre dans le calcul du score, ni de l'ICP, ni du marché.

Le moteur ne consomme donc que `NeedGraphResult`, `ContractUnderstanding`, les faits d'award/company
validés et le `TargetICP`. §50 : aucun modèle de domaine existant n'a été modifié, donc pas de
`SPEC-008 BLOCKED`.

---

## TEST RESULTS

```
uv run pytest -q            → 1338 passed
uv run ruff check .         → All checks passed!
uv run ruff format --check .→ 138 files already formatted
git diff --check            → propre
```

Décomposition de l'apport SPEC-008 (1 312 tests avant l'ajout des tests §45 et §42) :

| Fichier | Tests |
|---|---|
| `tests/test_icp_model.py` | 19 |
| `tests/test_matching_engine.py` | 33 |
| `tests/test_matching_adversarial.py` | **20** (§45 A–T) |
| `tests/test_matching_fixtures.py` | **6** (§42) |

Non-régression ciblée, exécutée séparément : les suites SPEC-006 et SPEC-007
(`test_need_*`, `test_document_*`) donnent **247 passed**.

Tous les tests sont **offline** : aucun appel réseau, aucun LLM. Le moteur de matching est
entièrement déterministe — c'est la différence de fond avec SPEC-006, dont l'échec venait
précisément d'un composant LLM non calibré dans la boucle de décision.

---

## OPEN QUESTIONS

Uniquement des ambiguïtés **réellement observées** pendant la construction ou les tests. Aucune n'a
affecté les résultats finaux ; aucune n'est corrigée ici, le moteur étant gelé depuis le run.

**1. ~~`geography_basis = "ignore"` avec `geography_policy = "required"` est constructible et
incohérent.~~ — FERMÉE par SPEC-008R §2.** Les validateurs acceptent la combinaison (l'invariant 5 n'exige que des `territories`).
Le filtre court-circuite correctement — statut `ignored` — mais le composant géographie reste au
dénominateur, parce que la condition d'exclusion porte sur `geography_policy != "ignored"` et non sur
le basis (`engine.py:143`). Résultat mesuré : 0 point sur 20 au lieu d'un retrait du dénominateur,
soit 73/100 au lieu de 91/100. **Aucun des 8 ICPs de référence n'utilise cette combinaison** — le
seul ICP en `ignore` est `icp-remote-specialist`, qui est aussi en `policy = "ignored"` — donc aucune
des 680 paires finales n'est concernée. La question ouverte est de savoir si le basis `ignore` doit
être interdit avec une policy `required` par un invariant, ou si l'exclusion du dénominateur doit
tenir compte des deux axes.

**2. ~~Décision et bande peuvent diverger sur une devise sans seuil.~~ — FERMÉE par SPEC-008R §3-§4.** Un montant en devise non
couverte (`currency_unsupported`) rend `economic_ok` faux, ce qui plafonne la décision à `borderline`
(`engine.py:156`), alors que la bande reste calculée sur le seul score normalisé et peut valoir
`strong` au-dessus de 75 (`engine.py:165`). C'est cohérent avec §27 — la décision est plus stricte
que la bande — mais un affichage qui montrerait « strong » à côté de « borderline » surprendrait.
La question est de présentation, pas de calcul.

**3. L'accord de 100 % sur le gold final ne prouve pas la justesse de la doctrine.** Les deux passes
sont produites par le même modèle avec la même rubrique : leur convergence mesure la reproductibilité
de la doctrine, pas sa correction. Une validation externe — un adjudicateur humain sur un
échantillon, ou un modèle d'une autre famille — reste la seule façon de distinguer « rubrique claire »
de « rubrique juste ». C'est la limite la plus importante de ce rapport.

**4. `winner_location` est modélisable mais non mesurable.** Aucun des 100 award-lots de l'étude, ni
aucun des 85 du held-out, ne publie l'adresse du titulaire. Le basis existe, il est testé (J), et il
produit correctement `insufficient_data` plutôt qu'un faux positif — mais sa qualité réelle est
inconnue et le restera tant qu'une source ne publiera pas cette donnée.

**5. Le rappel de 100 % sur `strong_match`, aux deux phases, mérite de la prudence.** Le gold est
adjugé selon la même rubrique que celle qu'encode le moteur. Un rappel parfait signifie donc « le
moteur applique la rubrique fidèlement », ce qui est bien la propriété visée, mais ne dit rien de ce
qu'un commercial jugerait pertinent. Le vrai test de rappel est le benchmark de signaux réels.

**6. `plausible_match` a un intervalle interquartile large (28–67).** Attendu, puisque le grade
regroupe des plafonnements de causes hétérogènes, mais cela signifie qu'un seuil unique
`BORDERLINE_THRESHOLD = 40` coupe au milieu de cette population : une partie des `plausible_match`
tombe en `exclude`. Aucun gate ne le sanctionne, et la précision `show` n'en souffre pas — c'est un
arbitrage à revoir si le feed « borderline » devient un produit.

---

## DEFINITION OF DONE

Les seize conditions du §53, vérifiées une par une :

| # | Condition | Vérification | ✓ |
|---|---|---|---|
| 1 | `TargetICP` explicite et indépendant de l'acquisition | test de frontière AST §46, 13 termes interdits absents | ✅ |
| 2 | matching sur champs canoniques uniquement | imports limités à `signals.{domain,needs,understanding}` | ✅ |
| 3 | aucun texte libre n'influence silencieusement le score | `offer_summary` n'apparaît que dans une docstring d'`engine.py` | ✅ |
| 4 | besoin, score et confiance séparés | composants distincts, jamais fusionnés ni multipliés | ✅ |
| 5 | tous les hard filters absolus | 7 filtres, aucun compensable, évalués avant tout score | ✅ |
| 6 | aucun critical false show connu | **0** sur 680 paires | ✅ |
| 7 | show precision ≥ 95 % | **100 %** (57/57) | ✅ |
| 8 | strong-match recall ≥ 75 % | **100 %** (57/57) | ✅ |
| 9 | ranking place les strong au-dessus des non-matches | pairwise **100 %**, médianes 87 > 60 > 0 | ✅ |
| 10 | chaque score est expliqué | explanation coverage **100 %** | ✅ |
| 11 | chaque composant est traçable | component trace coverage **100 %** | ✅ |
| 12 | chaque fait utilisé conserve son `Evidence` | evidence coverage **100 %** | ✅ |
| 13 | confiance maximale `medium` | `"high"` absent du type `SignalConfidence` | ✅ |
| 14 | aucun résultat expérimental SPEC-006 utilisé | test adverse O, aucun import `signals.documents` | ✅ |
| 15 | Acquisition Engine totalement séparé | §46 + test adverse R | ✅ |
| 16 | tous les tests historiques verts | **1338 passed**, dont 247 SPEC-006/007 | ✅ |

# SPEC-008 DONE

Chiffres exacts du run final unique, sur held-out frais et gelé, 680 paires, **sans aucune itération
après le gel** :

```
show precision            100.00 %   (57/57, 0 faux positif)     gate ≥ 95 %    PASS
critical false shows           0                                 gate = 0       PASS
strong-match recall       100.00 %   (57/57, 0 faux négatif)     gate ≥ 75 %    PASS
hard-filter violations         0                                 gate = 0       PASS
pairwise ranking accuracy 100.00 %                               gate ≥ 90 %    PASS
macro precision@5         100.00 %   (4 ICPs à ≥ 5 strong)       gate ≥ 80 %    PASS
explanation coverage      100.00 %                               gate = 100 %   PASS
evidence coverage         100.00 %                               gate = 100 %   PASS
component trace coverage  100.00 %                               gate = 100 %   PASS
determinism               100.00 %                               gate = 100 %   PASS
médianes                  87 > 60 > 0  (strong > plausible > no_match)          PASS
```

**11/11 gates PASS.**

---

## COMMIT

**Aucun commit effectué** (§54). Le dépôt est laissé avec les fichiers SPEC-008 non suivis et
`git diff --check` propre. En attente de la validation du superviseur.

Après ce rapport, conformément au STOP §54 : SPEC-009 non commencée, aucune base de données, pas
d'auth, pas de SaaS, pas de frontend, pas de paywall, pas d'Acquisition Engine, pas d'Apollo, pas
d'Instantly.
