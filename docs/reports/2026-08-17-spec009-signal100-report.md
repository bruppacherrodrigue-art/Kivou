# SPEC-009 — Signal-100 End-to-End Commercial Benchmark V1

**Date** : 2026-08-17 · **as_of** : 2026-08-17 · **Verdict** : `SPEC-009 NOT DONE`

---

## PRECONDITION

| Condition §1 | État |
|---|---|
| `uv run pytest -q` | **1355 passed** ✅ |
| `uv run ruff check .` | **All checks passed** ✅ |
| `uv run ruff format --check .` | **1 fichier à reformater** ⚠️ |
| `git diff --check` | propre ✅ |
| working tree clean (fichiers suivis) | aucun fichier suivi modifié ni indexé ✅ |
| SPEC-007 committed | `367839a feat(needs): add deterministic need graph v0` ✅ |
| SPEC-008 + SPEC-008R committed | `d75cb61 feat(matching): add ICP matching and signal scoring v0` (contient `tests/test_matching_coherence.py`, SPEC-008R) ✅ |
| ≥ 1355 tests passing | 1355 ✅ |
| `AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False` | `src/signals/documents/mvp.py:30` ✅ |

**Écart déclaré.** `ruff format --check` échouait **avant** le début de SPEC-009, sur
`docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md` —
un document committé en `d173265`, issu de la lignée SPEC-006 (collision de nom :
cette « SPEC-009 » là est celle des *document requirements*, pas Signal-100). Le
défaut porte sur des blocs de code Python à l'intérieur d'un Markdown. Il n'a pas
été corrigé : §46 interdit de réparer pendant l'évaluation, et le corriger aurait
mêlé un diff étranger à SPEC-009. Les 15 fichiers produits par SPEC-009 sont, eux,
`ruff format` propres.

Les autres fichiers non suivis présents au départ (`.docx`, `:Zone.Identifier`,
post-mortem SPEC-006) préexistaient également.

**PRECONDITION : satisfaite, avec l'écart de formatage ci-dessus documenté.**

---

## FILES CHANGED

Aucun moteur gelé n'a été touché. Rien n'est committé (§65).

**Nouveaux modules de recherche** (`src/signals/research/`) :

| Fichier | Rôle |
|---|---|
| `signal100.py` | identités, disjonction 4 niveaux, `signal_id`, vocabulaire interdit, terciles, déduplication |
| `signal100_run.py` | acquisition fraîche TED + SIMAP (seul module réseau) |
| `signal100_pipeline.py` | exécution du pipeline gelé × 8 ICPs, entonnoir |
| `signal100_select.py` | sélection déterministe stratifiée |
| `signal100_snapshot.py` | snapshot §15, vue aveugle §28, rendu textuel §49 |
| `signal100_build.py` | orchestration corpus → banc → shadow |
| `signal100_adjudication.py` | vocabulaire fermé, arbitrage, résolution |
| `signal100_gold.py` | assemblage du gold |
| `signal100_metrics.py` | métriques §33–§45 et gates |
| `signal100_freeze.py` | sceau §32 |

**Nouveaux tests** : `test_signal100_policy.py` (32), `test_signal100_bench.py` (24),
`test_signal100_adjudication.py` (25), `test_signal100_gold.py` (15) — **96 tests**.

**Nouvelles fixtures** : `tests/fixtures/signal100/` (corpus, banc, vues aveugles,
rendus, shadow, gold, sceau, métriques).

**Nouveaux documents** : la rubrique v1 et ce rapport.

---

## INFRASTRUCTURE PORTABILITY CHECK

| Exigence §54/§55 | État |
|---|---|
| Compatible Linux | oui — exécuté sur WSL2/Linux |
| Aucun chemin absolu Windows | oui — `pathlib`, aucun littéral de chemin machine |
| Configurable par environnement | `KIVOU_ROOT`, `KIVOU_SIGNAL100_WORKDIR` |
| Sans dépendance à l'état de la machine | racine dérivée du module ; corpus antérieurs référencés en relatif |
| Sans service cloud obligatoire | oui — deux API publiques sans authentification |
| Portable local → VPS → VPS | oui — un dossier de travail, aucun état externe |
| Pas de Kubernetes / Terraform / AWS / microservices / files cloud / vector DB | aucun |
| Pagination bornée | TED `max_pages` 60, SIMAP `max_pages_per_filter` 40 |
| Ressources fermées | `with TedClient()` / `with SimapClient()`, lecture SHA par blocs de 64 Kio |
| Répertoires temporaires déterministes | `workdir()` |
| Croissance disque maîtrisée | 8,0 Mio de fixtures au total ; le fichier intermédiaire d'extension a été supprimé après fusion |
| Pas de DB (§56) | aucune — fixtures structurées uniquement |

**Réserve honnête** : `run()` conserve les lignes acquises en mémoire avant une
écriture unique (800 lignes ≈ 2,6 Mio). C'est borné et sûr pour un VPS, mais ce
n'est pas du streaming au sens strict de §55. Le passage en écriture incrémentale
sera nécessaire si le pool dépasse l'ordre de 10⁴ award-lots.

---

## FRESH ACQUISITION

Sources : connecteurs de production **TED** et **SIMAP**, tels quels. Aucun nouveau
connecteur, aucun portail français (§9).

Fenêtre : publications du **2026-07-10 au 2026-08-17** (requête TED
`form-type=result` sur 88 jours ; SIMAP depuis 2026-05-21).

| | Course 1 | Extension | Total |
|---|---|---|---|
| TED notices interrogées | 225 | 292 | 517 |
| TED notices parsées | 224 | 291 | 515 |
| TED échecs | 1 | 1 | 2 |
| TED écartées (déjà consommées) | 1 | 210 | 211 |
| TED award-lots retenus | 260 | 301 | 561 → **560** |
| SIMAP publications interrogées | 288 | 0 | 288 |
| SIMAP écartées (déjà consommées) | 140 | 0 | 140 |
| SIMAP award-lots retenus | 240 | 0 | **240** |

**Total : 800 award-lots frais** (560 TED / 240 SIMAP), soit exactement le plafond
de §12. Une ligne excédentaire (801ᵉ) a été retirée de façon déterministe.

Deux décisions d'acquisition, documentées :

1. **Plafond de 2 award-lots par notice appliqué dès l'acquisition** (§8) : 387 + 129
   lots ont été écartés à ce titre. Une notice à quarante lots ne colonise ni le pool
   ni le banc.
2. **SIMAP restreint à `award_tender` et `direct_award`.** Mesuré sur échantillon :
   ces deux familles produisent 1 `ContractAward` par publication, tandis que
   `award_competition` et `award_study_contract` en produisent **zéro** — le mapping
   les refuse déjà (`not-a-contract-award`). Les interroger dépensait des requêtes
   pour rien ; cela n'a écarté aucun contrat.

Deux limites réseau rencontrées et traitées **sans toucher au connecteur gelé** :
TED limite le débit (HTTP 429) sur la **recherche** autant que sur le XML ; un repli
exponentiel vit dans le script de recherche.

---

## DISJOINTNESS

Contre les cinq corpus antérieurs : DEV SPEC-005/007 (`contract100/awards.json`),
SPEC-007 DEV, SPEC-007 held-out, SPEC-007 final, SPEC-008 final.

| Niveau | Identités fraîches | Identités antérieures | Intersection |
|---|---|---|---|
| publication | 686 | 248 | **0** |
| notice | 686 | 248 | **0** |
| procedure | 684 | 248 | **0** |
| award identity | 799 | 279 | **0** |

Les ensembles extraits sont **non vides** aux quatre niveaux, et un test échoue
explicitement s'ils devenaient vides : une extraction cassée ne peut pas se lire
comme une disjonction (§10). 351 lignes ont été activement écartées en cours
d'acquisition parce qu'elles appartenaient à un corpus antérieur.

---

## SIGNAL POOL

| | |
|---|---|
| award-lots frais | 800 |
| award-lots avec gagnant identifié | 800 (100 %) |
| award-lots produisant ≥ 1 besoin | 415 (51,9 %) |
| paires évaluées (award-lot × 8 ICPs) | 6 400 |
| `exclude` | 4 198 |
| `insufficient_data` | 1 221 |
| `borderline` | 428 |
| `show` | 553 |
| **signaux `show` uniques** (1 par award-lot, §8) | **283** |
| minimum §12 | 120 |
| `show` perdus faute de gagnant identifié | 0 |

`source_mode` : `metadata_fallback` sur la totalité du pool (§5).

**Condition de non-trivialité §12 : SATISFAITE** — 283 ≥ 120, sans extension forcée.

---

## SIGNAL-100 SELECTION POLICY

Politique **fixée avant adjudication**, entièrement déterministe (aucun aléa, aucune
date d'exécution). Deux exécutions produisent le même banc.

1. Un signal par award-lot : meilleur `normalized_score`, puis `icp_id` croissant (§8).
2. Au plus 2 award-lots par notice (§8) — **jamais relâché**.
3. Stratification par rang de score en trois zones, quotas 33/34/33 (§14).
4. Glouton à priorité de couverture : à chaque tour, le candidat qui fait avancer le
   plus de minima de diversité non atteints ; égalités tranchées par (zone la plus en
   retard, score décroissant, `signal_id`).

**Déviation déclarée — plafond par ICP relâché de 25 à 37.** Après la déduplication
§8, seuls **4 ICPs** survivent dans le pool `show` unique
(`icp-remote-specialist` 103, `icp-national-supplier` 90, `icp-subcontracting-eu` 21,
`icp-materials-eu` 12 sur 283). Avec un plafond dur de 25 par ICP, le banc maximal
atteignable était de **83 signaux**, y compris après extension du pool à 800 award-lots
(le passage de 500 à 800 n'a fait gagner que 4 signaux). Or « construire exactement
100 signaux » est l'exigence dure et gatée (§13 première ligne, §59), tandis que
« maximum 25 signals from one ICP » figure sous les *objectifs de diversité*. Le
plafond a donc cédé **d'un cran à la fois** — 12 relaxations tracées dans
`signal100_pool_report.json` — jusqu'à permettre 100 signaux. Le plafond par type de
contrat (35) et le plafond anti-duplication par notice (2) n'ont jamais été touchés.

Cette concentration est elle-même un résultat : la règle « meilleur score gagne »
élimine systématiquement les ICPs spécialisés suisses au profit des ICPs larges.
`icp-staffing-ch` passe de 66 paires `show` à 1 signal unique ; `icp-ppe-safety-ch`
de 43 à 0 ; `icp-plant-hire-ch` de 14 à 0.

---

## SIGNAL-100 COMPOSITION

| Dimension | Observé | Objectif §13 | |
|---|---|---|---|
| Signaux | 100 | exactement 100 | ✅ |
| Zones de score | top 33 / middle 34 / bottom 33 | 33/34/33 | ✅ |
| TED | 45 | ≥ 35 | ✅ |
| SIMAP | 55 | ≥ 35 | ✅ |
| Notices distinctes | 96 | ≥ 75 | ✅ |
| Max lots par notice | 2 | ≤ 2 | ✅ |
| Pays | 8 (AT, CH, DE, ES, FR, IT, LT, SK) | ≥ 5 | ✅ |
| Types de contrat | 7 | ≥ 5 | ✅ |
| `NeedCategory` productives | 5 | ≥ 5 | ✅ |
| Max par type de contrat | 35 | ≤ 35 | ✅ |
| Max par ICP | 37 | ≤ 25 | ❌ **déviation déclarée** |

Répartition par ICP : `icp-national-supplier` 37, `icp-remote-specialist` 36,
`icp-subcontracting-eu` 20, `icp-materials-eu` 7.

---

## SIGNAL100 CORPUS SHA256

```text
7996beae4a7c1c609f2db1e7eea647f32beb4c06eb3349071e613aceb224aebf
```

---

## COMMERCIAL SIGNAL RUBRIC V1

`commercial-signal-rubric-v1`, gelée le 2026-08-17 **avant** toute adjudication et
avant toute lecture des scores moteur. Document :
`docs/reports/2026-08-17-spec009-commercial-rubric-v1.md`.

Sept dimensions à vocabulaire fermé — factual integrity, need credibility, ICP fit,
actionability, specificity, timing, proof quality — puis un verdict unique A/B/C/D et
un drapeau `critical_false_signal`. La rubrique ne recopie aucune règle interne : elle
ne demande jamais si une règle du Need Graph s'est déclenchée correctement.

**Vue d'adjudication aveugle (§28) — vérifiée par test** : `normalized_score`,
`score_components`, `band`, `decision`, `raw_points`, `rule_ids`, `mechanism_facts` et
`pressure_facts` sont absents des 100 vues montrées aux adjudicateurs.

**Réserve de procédure.** Un hook de session tronquait la lecture du fichier rubrique
à sa première ligne. Plusieurs adjudicateurs l'ont détecté et contourné (lecture par
`sed`) ; les autres disposaient des règles opérantes — conditions de `A`, déclencheurs
de `D`, `generic` ≠ `actionable`, `timing=unknown` acceptable, piège du livrable,
décalage géographique — directement dans leur consigne. L'accord observé (98 % à un
grade près) et la cohérence des motifs cités indiquent que la doctrine a été appliquée
uniformément, mais l'exposition à la rubrique n'a pas été rigoureusement identique
entre adjudicateurs.

---

## REVIEWER AGREEMENT

| | |
|---|---|
| Accord exact | **73 / 100** (73,0 %) |
| Accord à un grade près | **98 / 100** (98,0 %) — gate §31 ≥ 90 % ✅ |
| Désaccords | 27 |
| Écart de 2 grades | 2 |
| Arbitrages | **14** |
| Distribution Reviewer A | A 15, B 43, C 30, D 12 |
| Distribution Reviewer B | A 6, B 50, C 34, D 10 |
| Distribution finale | A 5, B 47, C 38, D 10 |

**Le gate de stabilité de la doctrine est le seul qui rende le reste interprétable.**
À 98 %, l'échec du banc ne peut pas être imputé à une rubrique instable : les deux
perspectives voient la même chose. La rubrique n'est donc **pas** déclarée instable, et
SPEC-009 n'est pas invalide — elle est valide et négative.

Règle de résolution déclarée avant adjudication : l'arbitrage tranche quand il a eu
lieu ; sinon le verdict **le plus sévère** l'emporte (produit precision-first).
Reproductibilité vérifiée par test sur les 100 enregistrements.

---

## GOLD SHA256

```text
21be11fc89d27eb8a229b22213454073b0a02cfd2d23bc6b0b6833aaf1d3e5af
```

Sceau complet (`signal100_seal.json`) :

```text
COMMERCIAL_RUBRIC_VERSION   commercial-signal-rubric-v1
ICP LIBRARY SHA             698cb112eaa6478eb4680e8513cf036dc22d7651437a356f0637967361400fb2
ENGINE VERSION SET          contract-understanding-v0.1
                            need-graph-v0.1
                            icp-match-v0.1
                            signal-score-v0.2
                            reference-icps-v0.1
```

Gel effectué **après** la fin des adjudications et **avant** toute comparaison aux
scores Kivou (§32).

---

## FINAL VERDICT DISTRIBUTION

```text
A    5
B   47
C   38
D   10
```

---

## USEFUL PRECISION

```text
(A + B) / 100 = 52,0 %      gate §34 : >= 90 %      ÉCHEC (-38,0 pts)
```

---

## ACTIONABLE RATE

```text
A / 100 = 5,0 %             gate §35 : >= 60 %      ÉCHEC (-55,0 pts)
```

---

## SAFETY RESULTS

| Mesure | Observé | Gate §36 | |
|---|---|---|---|
| D false/misleading | 10,0 % | ≤ 2 % | ❌ |
| **Critical false signals** | **9** | = 0 | ❌ |
| Factual integrity | **100,0 %** | ≥ 99 % | ✅ |
| Timing errors | **4** | = 0 | ❌ |
| Proof coverage | **100,0 %** | = 100 % | ✅ |
| Critical overclaiming | **0** | = 0 | ✅ |
| C weak signals | 38,0 % | ≤ 10 % (§37) | ❌ |

Compteurs de diagnostic : échecs de crédibilité du besoin 7, absence de fit ICP 6,
signaux génériques 22.

**Ce qui tient est net.** Aucun fait public affiché n'est faux, sur 100 signaux :
gagnants, objets, montants, devises, dates et lieux ont été vérifiés un par un contre
la preuve. Les champs absents sont affichés comme absents, jamais fabriqués. Aucune
formulation de certitude d'achat n'a été trouvée, en français comme en anglais.

**Ce qui ne tient pas** est le raisonnement commercial construit au-dessus de ces
faits exacts.

Les 9 critical false signals se répartissent par couche primaire en :
`contract understanding` 4, `need graph` 3, `timing` 2 — et par source en TED 4,
SIMAP 5 ; aucune source n'est épargnée.

---

## TOP-20 QUALITY

Les 20 meilleurs scores (93 → 100), ceux que le futur feed mettrait naturellement en avant :

```text
useful precision   65,0 %     gate §39 : >= 95 %   ÉCHEC
critical false     1          gate §39 : = 0       ÉCHEC
distribution       A 2 | B 11 | C 6 | D 1
```

C'est le résultat le plus inquiétant du banc : **le sommet du feed n'est pas meilleur
que sa moyenne**. Un signal à 93/100 peut être un critical false signal.

---

## BOTTOM-THIRD QUALITY

Tiers inférieur des signaux encore classés `show` (33 signaux, score médian 84) :

```text
useful precision   48,48 %    seuil diagnostic §40 : >= 80 %   NON ATTEINT (non bloquant)
distribution       B 16 | C 13 | D 4 | A 0
```

Diagnostic explicite de §40 : `SHOW_THRESHOLD` est probablement trop permissif. **Le
seuil n'a pas été modifié** (§40, §46).

---

## SCORE CALIBRATION

Médianes de `normalized_score` par verdict commercial :

| Verdict | n | médiane | p25 | p75 | min | max |
|---|---|---|---|---|---|---|
| A | 5 | **93** | 90,0 | 95,5 | 87 | 98 |
| B | 47 | **87** | 84,0 | 93,0 | 84 | 100 |
| C | 38 | **87** | 84,0 | 93,0 | 84 | 95 |
| D | 10 | **87** | 84,0 | 93,0 | 84 | 93 |

Par zone de score :

| Zone | n | médiane | actionable rate | useful precision |
|---|---|---|---|---|
| top | 33 | 93 | 12,12 % | 54,55 % |
| middle | 34 | 87 | 2,94 % | 52,94 % |
| bottom | 33 | 84 | 0,00 % | 48,48 % |

L'ordre attendu `median A > median B > median C` est formellement respecté au sens
non strict, mais c'est une lecture trompeuse : **B, C et D ont exactement la même
médiane, les mêmes quartiles et des étendues quasi identiques**. Le Signal Score
sépare marginalement `A` du reste (93 contre 87) et **ne sépare pas du tout un signal
utile d'un signal faux**. L'écart de précision utile entre le tiers haut et le tiers
bas est de 6 points — un pouvoir discriminant quasi nul sur la dimension qui compte.

Le score se distribue par ailleurs sur très peu de valeurs distinctes (84, 86, 87, 93,
95, 98, 100), ce qui limite structurellement sa capacité de tri.

---

## SOURCE ANALYSIS

| Source | n | A | B | C | D | useful precision | médiane | gate §42 (≥ 85 %) |
|---|---|---|---|---|---|---|---|---|
| SIMAP | 55 | 3 | 31 | 16 | 5 | **61,82 %** | 87 | ❌ |
| TED | 45 | 2 | 16 | 22 | 5 | **40,00 %** | 87 | ❌ |

Les deux sources dépassent 20 signaux, donc le gate s'applique aux deux : **les deux
échouent**. Le moteur n'est pas « bon sur une source et faible sur l'autre » — il est
insuffisant sur les deux, avec un écart marqué de 22 points en défaveur de TED.

---

## ICP ANALYSIS

| ICP | n | A | B | C | D | useful precision | médiane |
|---|---|---|---|---|---|---|---|
| `icp-materials-eu` | 7 | 2 | 4 | 1 | 0 | **85,71 %** | 95 |
| `icp-national-supplier` | 37 | 1 | 18 | 14 | 4 | 51,35 % | 87 |
| `icp-subcontracting-eu` | 20 | 2 | 8 | 8 | 2 | 50,00 % | 93 |
| `icp-remote-specialist` | 36 | 0 | 17 | 15 | 4 | **47,22 %** | 84 |

**Concentration extrême signalée** : 73 des 100 signaux proviennent de deux ICPs
(`icp-national-supplier` et `icp-remote-specialist`), qui sont aussi les deux plus
mauvais en précision utile. Ce sont les deux ICPs les plus larges — `icp-national-supplier`
déclare 2 catégories primaires et 2 secondaires, `icp-remote-specialist` ignore
totalement la géographie et n'impose aucun seuil de valeur. Le seul ICP étroit à
survivre en nombre significatif, `icp-materials-eu`, est aussi le seul à approcher le
gate de précision — sur 7 signaux seulement.

`icp-remote-specialist` ne produit **aucun** verdict A sur 36 signaux.

**Aucun ICP n'a été modifié** (§41, §46).

---

## NEED CATEGORY ANALYSIS

| Catégorie | n | A | B | C | D | useful precision |
|---|---|---|---|---|---|---|
| `safety_and_ppe` | 12 | 0 | 10 | 2 | 0 | **83,33 %** |
| `materials_or_components` | 20 | 3 | 12 | 4 | 1 | 75,00 % |
| `equipment_or_rental` | 20 | 2 | 11 | 5 | 2 | 65,00 % |
| `workforce_capacity` | 38 | 1 | 19 | 14 | 4 | 52,63 % |
| `specialist_subcontracting` | 56 | 2 | 25 | 23 | 6 | **48,21 %** |

(Un signal peut porter plusieurs catégories ; les lignes ne s'additionnent pas à 100.)

`specialist_subcontracting` est à la fois la catégorie la plus produite (56 signaux) et
la plus bruyante. Deux catégories du vocabulaire n'apparaissent jamais dans le banc :
`waste_and_environment` et `logistics_and_transport`.

**Aucune règle n'a été modifiée** (§43, §46).

---

## CONTRACT TYPE ANALYSIS

| Type | n | A | B | C | D | useful precision |
|---|---|---|---|---|---|---|
| `construction` | 35 | 3 | 23 | 7 | 2 | **74,29 %** |
| `engineering_architecture` | 30 | 2 | 18 | 9 | 1 | 66,67 % |
| `it_digital` | 24 | 0 | 6 | 13 | 5 | **25,00 %** |
| `facility_services` | 5 | 0 | 0 | 4 | 1 | 0,00 % |
| `maintenance_repair` | 3 | 0 | 0 | 3 | 0 | 0,00 % |
| `transport_logistics` | 2 | 0 | 0 | 2 | 0 | 0,00 % |
| `social_health_services` | 1 | 0 | 0 | 0 | 1 | 0,00 % |

La famille où le signal devient générique ou faux est nette : **`it_digital`** — 24
signaux, 25 % de précision utile, 5 des 10 verdicts D. Le cœur du produit
(`construction`, `engineering_architecture`) tient bien mieux, sans atteindre le gate.

---

## FAILURE ATTRIBUTION

48 signaux en échec (38 C + 10 D), chacun rattaché à **une** couche primaire.

| Couche primaire | C | D | total |
|---|---|---|---|
| `need graph` | 14 | 3 | **17** |
| `matching` | 13 | 0 | **13** |
| `contract understanding` | 4 | 4 | **8** |
| `ICP configuration` | 6 | 0 | **6** |
| `timing` | 0 | 3 | **3** |
| `source data` | 1 | 0 | **1** |

Couches secondaires citées : `matching` 24, `need graph` 20, `ICP configuration` 12,
`contract understanding` 6, `timing` 2, `score threshold` 1.

**Concentration des échecs** : 63 % des échecs se logent dans SPEC-007 (need graph) et
SPEC-008 (matching + ICP configuration). Les 10 verdicts D se répartissent en
`contract understanding` 4, `need graph` 3, `timing` 3.

### Les 10 signaux D, individuellement

| # | signal | source | ICP | score | couche | motif |
|---|---|---|---|---|---|---|
| 1 | `109437d3` | TED | `subcontracting-eu` | 93 | need graph | Licences d'une plateforme SaaS bancaire de l'éditeur : aucune spécialité séparable, besoin de sous-traitance non soutenu |
| 2 | `5e4ab59d` | TED | `national-supplier` | 93 | need graph | Fourniture de personnel soignant OSS : le personnel **est** le livrable ; de plus 390 jours d'âge contre une politique de 180 |
| 3 | `b0e70ef4` | TED | `national-supplier` | 93 | timing | Décontamination incendie : besoin étiqueté « immédiat » sur un contrat qui **se termine dans 11 jours** |
| 4 | `2210d48c` | SIMAP | `national-supplier` | 87 | need graph | Installations de chantier en conteneurs : l'équipement de chantier **est** le livrable ; terrassements inventés |
| 5 | `2b534b33` | SIMAP | `national-supplier` | 87 | contract understanding | Lot « BKP 339 Kassensystem » (caisse/contrôle d'accès, 120 kCHF) : le CPV du projet parent a fait dériver terrassement et matériaux en vrac |
| 6 | `ab66cc11` | TED | `subcontracting-eu` | 87 | timing | `timing=immediate` sur un `contract_start_date` du 2025-09-01, soit 351 jours contre une politique de 90 |
| 7 | `43de1c3d` | TED | `remote-specialist` | 84 | timing | Attribution du **2024-06-17**, soit 792 jours, contre `maximum_signal_age_days = 365` |
| 8 | `595e4def` | SIMAP | `remote-specialist` | 84 | contract understanding | Licences SAP LeanIX achetées **à l'éditeur lui-même** : prospecter SAP en sous-traitance est absurde |
| 9 | `6b0a5d44` | SIMAP | `remote-specialist` | 84 | contract understanding | Location de presse Canon classée `it_digital`, ce qui contourne l'exclusion `equipment_supply` de l'ICP |
| 10 | `7b250870` | SIMAP | `remote-specialist` | 84 | contract understanding | Fourniture de PDU/onduleurs par le fabricant Eaton, même contournement de l'exclusion `equipment_supply` |

**Trois familles de défaut se répètent** :

1. **Le livrable pris pour un besoin aval** (#1, #2, #4, #8, #10) — le piège explicitement
   nommé par la rubrique. Le Need Graph dérive un besoin que le gagnant *vend* déjà.
   `DELIVERABLE_OVERLAP` couvre le cas quand le `contract_type` est correct, mais pas
   quand la classification l'envoie ailleurs.
2. **La date d'attribution non contrôlée** (#3, #6, #7) — la fraîcheur est mesurée sur la
   date de *publication*, pas sur la date d'attribution ou la fin d'exécution. Un avis
   republié en 2026 pour une attribution de 2024 franchit le filtre.
3. **La classification qui neutralise les filtres de l'ICP** (#5, #9, #10) — un CPV logiciel
   sur un marché de matériel donne `it_digital`, ce qui contourne l'exclusion
   `equipment_supply` que l'ICP avait explicitement déclarée.

**Aucune correction n'a été appliquée** (§46).

---

## SHADOW NEGATIVE CONTROL

100 contrôles fraîchement produits par les mêmes données (§47), adjudication légère,
**hors gates**.

| Ensemble | n | `should_have_been_show` | `maybe` | `correctly_not_show` |
|---|---|---|---|---|
| `borderline` | 50 | **13** | 15 | 22 |
| `exclude` | 50 | **0** | 4 | 46 |
| **Total** | 100 | **13** | 19 | 68 |

**Rappel manqué (§48)** : 13 opportunités clairement manquées sur 100 contrôles, **toutes
en `borderline`, aucune en `exclude`**. Parmi les cas les plus nets cités par les
adjudicateurs : un design-build bernois de 48 MCHF correspondant à deux catégories
primaires de l'ICP, un accord-cadre électrique de 11,1 MCHF sur cinq ans à l'aéroport de
Genève, un contrat FM de 13,1 MEUR sur douze ans nommant explicitement des lots
électriques séparables, et un lot de toiture-terrasse de 400 kCHF envoyé à un ICP EPI.

Les 46 `correctly_not_show` de l'ensemble `exclude` se répartissent proprement en
décalages géographiques durs hors territoires déclarés (DK, BG, RO, NO, IE), pièges du
livrable, types de contrat explicitement exclus, et objets contredisant le besoin.

**Lecture du compromis précision/rappel** : le moteur n'est pas globalement trop
conservateur — ses `exclude` sont sains à 92 %. La perte de rappel est **entièrement
localisée à la frontière `borderline`**, exactement là où le seuil se joue. Combiné à
une précision utile de 52 % sur ce qu'il montre, cela signifie que le seuil actuel
n'est pas seulement mal réglé en niveau : **il ne trie pas selon la bonne dimension.**

---

## SPEC-006/007/008 NON-REGRESSION

| | |
|---|---|
| Moteurs modifiés | **aucun** — `understanding/`, `needs/`, `matching/`, `resolution/`, `connectors/` intacts |
| Poids, seuils, profils CPV, règles de scale, ICPs de référence | **inchangés** |
| LLM ajouté au pipeline | **non** |
| Nouvelle taxonomie | **non** |
| `AUTO_DOCUMENT_REQUIREMENTS_ENABLED` | `False` — vérifié par test au moment du banc |
| `source_mode` du banc | `metadata_fallback` sur 100/100 |
| Sortie expérimentale SPEC-006 consommée | aucune (`document_supported` absent du banc, vérifié par test) |
| Empreintes gelées SPEC-008 §42 | intactes (`reference_icps.json`, corpus et gold de matching) |
| Empreintes gelées SPEC-007 | intactes |
| Bibliothèque d'ICPs | SHA identique à celui gelé par SPEC-008 |

Les modules SPEC-006 restent en place et désactivés ; aucun DCE archivé n'a participé
au banc.

---

## TEST RESULTS

```text
uv run pytest -q            1451 passed        (1355 avant SPEC-009, +96)
uv run ruff check .         All checks passed
uv run ruff format --check  1 file would be reformatted   ← préexistant, hors SPEC-009
git diff --check            propre
git status                  aucun fichier suivi modifié ; rien de committé (§65)
```

Détail des 96 tests ajoutés : politique 32, intégrité du banc 24, adjudication 25,
gel du gold 15. Aucun d'eux n'appelle Internet — l'acquisition fraîche est un script
de recherche distinct de la suite (§58).

Les 1355 tests antérieurs restent verts.

---

## SPEC-009 NOT DONE

### Gates échoués

```text
USEFUL SIGNAL PRECISION (A+B)     52,0 %   <  90 %     §34
ACTIONABLE SIGNAL RATE (A)         5,0 %   <  60 %     §35
WEAK SIGNAL RATE (C)              38,0 %   >  10 %     §37
FALSE/MISLEADING (D)              10,0 %   >   2 %     §36
CRITICAL FALSE SIGNALS                 9   >   0       §36
TIMING ERRORS                          4   >   0       §36
TOP20 USEFUL PRECISION            65,0 %   <  95 %     §39
TOP20 CRITICAL FALSE                   1   >   0       §39
SOURCE USEFUL PRECISION (TED)     40,0 %   <  85 %     §42
SOURCE USEFUL PRECISION (SIMAP)   61,8 %   <  85 %     §42
```

### Gates tenus

```text
SIGNALS                              100   =  100      §59
FACTUAL INTEGRITY                100,0 %   >= 99 %     §36
PROOF COVERAGE                   100,0 %   = 100 %     §36
CRITICAL OVERCLAIMING                  0   =   0       §36
RUBRIC AGREEMENT WITHIN ONE       98,0 %   >= 90 %     §31
```

### SPEC à rouvrir, par ordre de rendement

1. **SPEC-007 — Need Graph** (17 échecs primaires, 20 secondaires). Le défaut dominant
   est le livrable pris pour un besoin aval, hors des cas que `DELIVERABLE_OVERLAP`
   couvre déjà. `specialist_subcontracting` sur-produit et sous-performe (56 signaux,
   48 % de précision utile). Les adjudicateurs signalent aussi des énoncés de besoin
   **strictement identiques mot pour mot** d'un contrat à l'autre : la spécificité est
   portée par le résumé du contrat, jamais par le besoin — d'où 22 signaux génériques.
2. **SPEC-008 — ICP Matching** (13 + 6 échecs primaires). La règle de déduplication
   « meilleur score gagne » concentre 73 % du feed sur les deux ICPs les plus larges,
   qui sont les moins précis, et efface les ICPs spécialisés. Les exclusions déclarées
   par un ICP (`equipment_supply`) sont contournables via la classification.
3. **SPEC-005 — Contract Understanding** (8 échecs primaires, dont 4 des 10 D). Le CPV du
   projet parent contamine des lots dont l'objet publié dit autre chose ; du matériel
   se classe `it_digital` ; le motif « les travaux relèvent du terrassement ou du génie
   civil » est asserté sur des objets qui l'excluent (relevé sur au moins 9 signaux).
4. **SPEC-008R2 — seuil et calibration** (candidat). `SHOW_THRESHOLD` laisse passer des
   signaux faibles (tiers inférieur à 48 % de précision utile) et le score ne sépare pas
   B de D. Mais l'ordre est important : recalibrer un score au-dessus d'un besoin
   défectueux ne ferait que déplacer le bruit. Cette SPEC devrait venir **après** 1 et 2.
5. **Fraîcheur** (transverse, 3 verdicts D). La date de publication n'est pas la date
   d'attribution. Un avis republié fait franchir le filtre d'âge à une attribution de
   2024, et un contrat qui s'achève dans 11 jours reçoit `timing=immediate`.

**SPEC-004 — Winner Resolution n'est pas en cause** : 100 % d'intégrité factuelle,
aucun gagnant erroné sur 100 signaux. Trois défauts de *présentation* ont été relevés
sans faire basculer de verdict : un préfixe de langue `FR_` collé au nom du gagnant, un
membre de consortium dupliqué, une URL d'organisation mal mappée.

**Aucune correction n'a été commencée** (§46, §61). Rien n'est committé (§65).

---

## OPEN QUESTIONS

1. **Le plafond de 25 signaux par ICP est-il tenable ?** Après déduplication §8, le pool
   n'expose que 4 ICPs. Soit la règle de déduplication change (un award-lot pourrait
   produire un signal par ICP distinct, au prix de la duplication d'événement), soit le
   plafond descend, soit le banc accepte la concentration. La question est de doctrine
   produit, pas de mesure.
2. **Un feed mono-ICP est-il le vrai produit ?** 73 % des signaux viennent de deux ICPs
   très larges. Si le client réel est un fournisseur spécialisé suisse, le banc ne mesure
   pas son feed : `icp-staffing-ch` n'obtient qu'**un seul** signal sur 100.
3. **Le Signal Score mérite-t-il d'être conservé sous cette forme ?** Il prend 7 valeurs
   distinctes et ne sépare pas un signal utile d'un signal faux. Le tri du feed pourrait
   n'avoir aujourd'hui aucune valeur informative.
4. **Que devient le gate de rappel ?** 13 % des `borderline` sont des manques nets. SPEC-009
   ne gate pas le rappel ; une V2 devrait décider si un feed precision-first peut se
   permettre d'en perdre autant à la frontière.
5. **`it_digital` doit-il être servi du tout au MVP ?** 24 signaux, 25 % de précision utile,
   la moitié des verdicts D. L'exclure du feed relèverait les métriques globales sans rien
   corriger au fond — c'est une décision de périmètre commercial, pas d'ingénierie.
6. **Deux catégories de besoin ne sont jamais produites** (`waste_and_environment`,
   `logistics_and_transport`) et deux ICPs suisses n'obtiennent aucun signal. Sont-ils
   morts en pratique, ou seulement absents de cette fenêtre de 5 semaines ?
7. **L'exposition inégale à la rubrique** (hook de troncature) est une faiblesse de
   procédure. À 98 % d'accord elle n'a probablement rien changé, mais une V2 devrait
   embarquer la rubrique dans la consigne plutôt que dans un fichier à lire.
8. **La fenêtre de 5 semaines** (2026-07-10 → 2026-08-17) est courte et estivale. Elle est
   disjointe et représentative du flux courant, mais la saisonnalité des marchés publics
   n'est pas mesurée.
