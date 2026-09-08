# SPEC-009B — Client Feed Decomposition & MVP Wedge Selection

**Date** : 2026-08-17 · **Verdict** : `AMBER WEDGE ONLY`

---

## SPEC-009A CLOSEOUT

L'infrastructure du vérificateur commercial est conservée et **structurellement
isolée**, vérifié dans les deux sens par `tests/test_verifier_isolation.py` :

```text
aucun runtime produit ne l'importe        ✅  0 import depuis matching, needs,
                                              understanding, resolution,
                                              connectors, domain, documents
aucun MatchingEngine ne l'appelle         ✅
aucun feed produit ne l'appelle           ✅
aucun résultat client n'en dépend         ✅
le paquet n'importe lui-même aucun moteur ✅  (dépendance sortante : zéro)
un seul pont déclaré                      ✅  src/signals/research/verifier_dev.py
aucun feature flag de production          ✅  vérifié par AST, pas par chaîne
```

Statut documenté dans `src/signals/verification/__init__.py` :

```text
EXPERIMENTAL
NOT PRODUCTION ENABLED
GENERALIST FILTER FAILED DEV GATES
```

---

## COMMIT

```text
973c8da  research(verification): preserve commercial verifier experiment
```

Corps du commit : `SPEC-009A NOT DONE` / `NOT USED BY MVP PIPELINE`. Non poussé.
Arbre suivi propre après commit (0 fichier suivi modifié).

**Une décision à signaler.** Le commit inclut toute la chaîne de recherche
SPEC-009 **et** SPEC-009A, pas seulement le vérificateur. La raison est
mécanique : `tests/test_verifier_dev_set.py` épingle les empreintes du corpus et
du gold Signal-100, et le gold DEV du vérificateur est construit sur le shadow
set de SPEC-009. Un commit ne préservant que `verification/` aurait été cassé sur
un clone neuf. Le commit a été fait **sur `main`**, comme toute l'histoire du
dépôt ; s'il devait vivre sur une branche, il est trivialement déplaçable.

---

## PRECONDITION

| | |
|---|---|
| `uv run pytest -q` | **1608 passed** (avant SPEC-009B) ✅ |
| `uv run ruff check .` | All checks passed ✅ |
| `git diff --check` | propre ✅ |
| `git status --short` | seuls les artefacts non suivis attendus |
| `ruff format --check` | 1 écart, **hors périmètre**, non modifié |

L'écart de formatage reste
`docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md`,
committé en `d173265`. §2 demande explicitement de ne pas y toucher pour obtenir
un arbre vert ; il n'a pas été touché.

---

## FILES CHANGED

| Fichier | Rôle |
|---|---|
| `src/signals/research/wedge.py` | reconstruction des feeds, échantillonnage §11/§12, classement §34–§37 |
| `tests/test_wedge_analysis.py` | 32 tests (§50) |
| `tests/test_verifier_isolation.py` | 6 tests d'isolation SPEC-009A (§1) |
| `tests/fixtures/signal100/wedge_gold.json` | 236 adjudications + profils de feed + impact dédup |
| `src/signals/verification/__init__.py` | statut expérimental documenté |
| ce rapport | |

Aucun moteur gelé n'a été touché (§6) — vérifié par test.

---

## INPUTS

Entièrement hors ligne, depuis les fixtures gelées (§5). **Aucun appel à TED,
SIMAP, OpenRouter ou DeepSeek.**

```text
800 award-lots frais              reproduits à l'identique
6 400 paires award-lot × ICP      553 SHOW · 428 BORDERLINE · 4 198 EXCLUDE · 1 221 INSUFFICIENT
commercial-signal-rubric-v1       inchangée
Signal-100 gold                   100 couples, réutilisés par identité exacte
SPEC-009A DEV gold                50 couples borderline
```

Les totaux de décision se reproduisent **exactement** — c'est ce que vérifie
`test_the_frozen_decision_totals_match_spec009`.

---

## PER-CLIENT FEED DOCTRINE

```text
PER-CLIENT FEED RECOMMENDED
```

Ce n'est pas une préférence esthétique, c'est le résultat le plus important de
cette SPEC. Dans Kivou, un client a son ICP et son feed ; le feed d'un client
n'a aucune raison d'être amputé parce qu'un autre client aurait mieux « gagné »
le même marché. La déduplication cross-ICP de SPEC-009 était une commodité de
banc, et elle mesurait un feed **qu'aucun client réel n'aurait jamais vu**.

| | déduplication globale (SPEC-009) | feed par client (SPEC-009B) |
|---|---|---|
| visibilité des ICPs spécialisés | 3 feeds réduits à zéro | tous visibles |
| sémantique | un award appartient au « meilleur » ICP | un award appartient à tout client concerné |
| concentration | 73 % du banc sur 2 ICPs larges | chaque feed a sa propre densité |
| précision mesurée | 52 % (banc global) | 32,5 % à 80,5 % selon le feed |

---

## CROSS-ICP DEDUP IMPACT

C'est la mesure décisive de §8.

| ICP | paires SHOW brutes | survivants Signal-100 | taux de survie |
|---|---|---|---|
| `icp-subcontracting-eu` | 59 | 20 | 33,9 % |
| `icp-materials-eu` | 22 | 7 | 31,8 % |
| `icp-national-supplier` | 130 | 37 | 28,5 % |
| `icp-remote-specialist` | 215 | 36 | 16,7 % |
| **`icp-staffing-ch`** | **68** | **0** | **0,0 %** |
| **`icp-ppe-safety-ch`** | **45** | **0** | **0,0 %** |
| **`icp-plant-hire-ch`** | **14** | **0** | **0,0 %** |
| `icp-waste-ch` | 0 | 0 | — |

**Trois feeds spécialisés — 127 signaux `show` — ont été intégralement effacés
par la règle « meilleur ICP gagne ».** Le banc SPEC-009 n'a pas mesuré un
mauvais produit : il a mesuré le produit des deux ICPs les plus larges, en
faisant disparaître ceux dont le métier est le plus net.

Cela ne réhabilite pas le résultat de SPEC-009 — les feeds spécialisés,
mesurés ici pour la première fois, sont eux aussi RED. Mais cela explique
pourquoi le banc global était structurellement incapable de trouver un wedge.

---

## PER-ICP NATURAL VOLUME

| ICP | SHOW | BORDER | EXCL | INSUF | TED/SIMAP | pays | score méd. | montant connu | timing connu |
|---|---|---|---|---|---|---|---|---|---|
| `icp-remote-specialist` | 215 | 14 | 571 | 0 | 82/133 | 17 | 84 | 100 % | 84 % |
| `icp-national-supplier` | 130 | 133 | 537 | 0 | 59/71 | 5 | 87 | 100 % | 86 % |
| `icp-staffing-ch` | 68 | 13 | 515 | 204 | 7/61 | 1 | 87 | 100 % | 93 % |
| `icp-subcontracting-eu` | 59 | 174 | 567 | 0 | 18/41 | 4 | 93 | 100 % | 85 % |
| `icp-ppe-safety-ch` | 45 | 82 | 673 | 0 | 7/38 | 1 | 87 | 100 % | 87 % |
| `icp-materials-eu` | 22 | 12 | 562 | 204 | 22/0 | 4 | 93 | 100 % | 82 % |
| `icp-plant-hire-ch` | 14 | 0 | 177 | 609 | 0/14 | 1 | 87 | 100 % | 100 % |
| `icp-waste-ch` | **0** | 0 | 596 | 204 | — | 0 | — | — | — |

`icp-waste-ch` ne produit **aucun** signal sur 800 award-lots. Ce n'est pas un
feed faible, c'est un feed vide.

---

## PER-ICP COMMERCIAL RESULTS

236 signaux adjugés — 192 nouveaux, 44 réutilisés par identité exacte de couple
(§16).

| ICP | rev | A | B | C | D | précision utile | actionnable | faux | critiques | TOP10 | volume | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `icp-materials-eu` | 22 | 4 | 12 | 6 | 0 | **72,7 %** | 18,2 % | 0,0 % | **0** | 70,0 % | 22 | RED |
| `icp-national-supplier` | 40 | 3 | 24 | 12 | 1 | 67,5 % | 7,5 % | 2,5 % | 1 | 90,0 % | 130 | RED |
| `icp-staffing-ch` | 40 | 7 | 17 | 11 | 5 | 60,0 % | 17,5 % | 12,5 % | 5 | 80,0 % | 68 | RED |
| `icp-ppe-safety-ch` | 40 | 2 | 21 | 16 | 1 | 57,5 % | 5,0 % | 2,5 % | 1 | 90,0 % | 45 | RED |
| `icp-subcontracting-eu` | 40 | 4 | 15 | 12 | 9 | 47,5 % | 10,0 % | 22,5 % | 8 | 50,0 % | 59 | RED |
| `icp-plant-hire-ch` | 14 | 3 | 2 | 5 | 4 | 35,7 % | 21,4 % | 28,6 % | 4 | 50,0 % | 14 | RED (LOW SAMPLE) |
| `icp-remote-specialist` | 40 | 0 | 13 | 23 | 4 | **32,5 %** | 0,0 % | 10,0 % | 3 | 20,0 % | 215 | RED |
| `icp-waste-ch` | — | — | — | — | — | — | — | — | — | — | 0 | INSUFFICIENT SAMPLE |

**Aucun ICP entier n'est vendable tel quel.** Mais la dispersion est le
résultat utile : de 32,5 % à 72,7 %, ce n'est pas un moteur uniformément
mauvais, c'est un moteur dont la qualité dépend fortement du client.

### Stabilité de la doctrine (§17)

```text
nouveaux signaux adjugés            192
accord exact                        72,9 %
accord à un grade près              99,0 %      gate >= 90 %   ✅
arbitrages                          35
```

Le gate est tenu largement : les verdicts qui suivent ne sont pas un artefact de
rubrique instable.

**Une doctrine a dû être tranchée en arbitrage.** Les deux relecteurs ont
divergé sur l'ancrage de la fraîcheur : âge mesuré depuis la **date
d'attribution** ou depuis la **date de publication** ? La rubrique dit
`timing = wrong` inclut « award too old under ICP policy » ; les arbitres ont
donc appliqué uniformément l'âge de l'**attribution**, avec repli sur la
publication quand aucune date d'attribution n'est publiée. C'est la lecture
littérale de la rubrique gelée, appliquée à tous. Elle explique 13 des 22 faux
signaux critiques et doit être considérée comme une décision de doctrine
explicite, pas comme un détail de mesure.

---

## BROAD ICP ANALYSIS

### `icp-national-supplier` — **TOO BROAD FOR MVP**

2 catégories primaires + 2 secondaires, `geography_basis: either`,
`geography_policy: preferred`, aucun type de contrat inclus ni exclu, seuil
100 k. Résultat : 130 signaux `show`, 5 pays, et une précision utile de 67,5 %.

Il capture parce qu'il ne refuse presque rien. Sur `construction` seul il monte
à **79,4 %** — ce qui montre que le problème n'est pas l'ICP en soi mais son
absence de frontière de type de contrat. Un déchet vert italien et un serveur
informatique entrent dans le même feed qu'un chantier routier.

### `icp-remote-specialist` — **DIAGNOSTIC ICP ONLY**

215 signaux `show` — 39 % de tout le volume — pour **32,5 % de précision utile
et zéro verdict A sur 40 signaux évalués**. Il ignore la géographie, n'impose
aucun seuil de valeur, n'inclut aucun type de contrat et n'exclut que
`medical_supply` et `equipment_supply`. Une livraison de substrat de gazon typée
`construction` y entre sans obstacle.

Ce n'est pas un client Kivou : c'est un filtre passe-tout. Il devrait servir de
sonde de diagnostic, jamais de feed.

---

## SPECIALIZED ICP ANALYSIS

| ICP | volume naturel | précision utile | cause dominante d'échec |
|---|---|---|---|
| `icp-materials-eu` | 22 | 72,7 % | granularité de métier (`matching`) — 0 faux, 0 critique |
| `icp-staffing-ch` | 68 | 60,0 % | fraîcheur (5 des 5 D) |
| `icp-ppe-safety-ch` | 45 | 57,5 % | besoin générique, seuil de valeur trop bas |
| `icp-subcontracting-eu` | 59 | 47,5 % | fraîcheur (8 D) + IT/digital |
| `icp-plant-hire-ch` | 14 | 35,7 % | motif « terrassement ou génie civil » câblé en dur |
| `icp-waste-ch` | 0 | — | aucun signal produit |

L'effet géographique est net : les ICPs à `geography_policy: required` (staffing,
plant-hire, materials) n'ont produit aucun décalage géographique dur dans les
feeds mesurés ici. Les décalages observés en SPEC-009A venaient des ICPs
`preferred`, où hors territoire coûte une pénalité au lieu d'exclure.

---

## ICP × CONTRACT TYPE × NEED RESULTS

Publiées à partir de 8 signaux évalués (§21).

| ICP × type | n | précision utile | D | critiques | |
|---|---|---|---|---|---|
| `subcontracting-eu` × `engineering_architecture` | 8 | **87,5 %** | 0 | 0 | à surveiller |
| `national-supplier` × `construction` | 34 | **79,4 %** | 1 | 1 | |
| `materials-eu` × `construction` | 22 | 72,7 % | 0 | 0 | |
| `staffing-ch` × `construction` | 38 | 63,2 % | 5 | 5 | |
| `remote-specialist` × `engineering_architecture` | 13 | 61,5 % | 0 | 0 | |
| `ppe-safety-ch` × `construction` | 40 | 57,5 % | 1 | 1 | |
| `subcontracting-eu` × `construction` | 25 | 44,0 % | 7 | 7 | |
| `plant-hire-ch` × `construction` | 14 | 35,7 % | 4 | 4 | |
| `remote-specialist` × `construction` | 16 | 18,8 % | 1 | 1 | |
| `remote-specialist` × `it_digital` | 11 | **18,2 %** | 3 | 2 | |
| `subcontracting-eu` × `it_digital` | 7 | 14,3 % | 2 | 1 | échantillon indicatif |

---

## CONSTRUCTION / ENGINEERING

| type de contrat | n | précision utile | D | critiques |
|---|---|---|---|---|
| `construction` | 189 | 57,7 % | 19 | 19 |
| `engineering_architecture` | 21 | **71,4 %** | 0 | 0 |
| `it_digital` | 18 | 16,7 % | 5 | 3 |
| `facility_services` | 2 | 0,0 % | 0 | 0 |
| `maintenance_repair` | 4 | 0,0 % | 0 | 0 |
| `transport_logistics` | 2 | 0,0 % | 0 | 0 |

`construction` seul ne suffit pas — 57,7 %, c'est le socle, pas un wedge. La
distinction utile n'est **pas** entre familles de construction (le modèle
canonique ne les distingue pas, et §24 interdit d'en créer) mais entre
**catégories de besoin à l'intérieur de la construction** : c'est là que se
trouve le wedge.

`engineering_architecture` est la seule autre famille saine : 71,4 %, **zéro D,
zéro critique** sur 21 signaux.

---

## MATERIALS

L'hypothèse de §25 tient, et se renforce quand on l'affine.

```text
icp-materials-eu (feed entier, 100 % construction)   n=22   72,7 %   0 D   0 critique
+ icp-national-supplier × construction               n=56   76,8 %   1 D   1 critique
+ restriction au besoin materials_or_components      n=41   80,5 %   0 D   0 critique
```

Le passage de 76,8 % à 80,5 % vient d'une frontière **de définition de client**,
pas d'un tri par qualité : un négociant en matériaux vend
`materials_or_components`. Restreindre le feed à cette catégorie retire les
signaux appariés uniquement sur `equipment_or_rental` — dont l'unique faux
critique de la famille (Condecta AG, installations de chantier en conteneurs :
le livrable pris pour un besoin aval).

Par source : TED 30 / SIMAP 11 sur l'échantillon, TED 44 / SIMAP 29 en volume
naturel. Par pays : DE 17, CH 11, FR 7, ES 5, PT 1. Montant connu : 100 %.

---

## PPE / SAFETY

L'hypothèse de §26 **ne tient pas** hors déduplication.

Signal-100 mesurait 83,3 % sur 12 signaux de la catégorie `safety_and_ppe`.
Le feed client réel `icp-ppe-safety-ch`, mesuré sur 40 signaux, donne **57,5 %**
avec 1 faux critique.

Deux causes, toutes deux nommées par les relecteurs :

1. **Le seuil de valeur à 100 kCHF** admet des lots MEP et finition de
   146–244 kCHF où aucun achat d'EPI incrémental ne suit.
2. **L'énoncé de besoin est identique mot pour mot sur les 40 signaux.** Un pont
   sur voie ferrée en exploitation et un remplacement de logiciel SCADA
   reçoivent la même phrase. La spécificité ne dépasse jamais `acceptable`,
   d'où **2 verdicts A sur 40**.

Le faux critique est un remplacement de logiciel de conduite (CPV 45000000)
lu comme un chantier, générant un besoin d'EPI sur 2,6 MCHF de logiciel.

---

## EQUIPMENT / RENTAL

`icp-plant-hire-ch` : **35,7 %**, 4 faux critiques sur 14 signaux — le pire feed
mesurable.

La cause est unique et mécanique : **un motif câblé en dur**, « Les travaux
relèvent du terrassement ou du génie civil », déclenché sur `cpv` + `amount`
seuls. Six des quatorze signaux sont des sous-lots du **même** projet (piscine
d'Embrach ZH, CPV projet 45212212) : seul le lot Baumeister est un vrai
prospect ; les cinq autres pointent vers des spécialistes CVC, sanitaire,
électricité et revêtement de bassin. Trois faux critiques sont des lots de
menuiserie intérieure, de portes métalliques et de serrurerie présentés comme du
terrassement.

C'est aussi le feed le plus étranglé en amont : 609 des 800 award-lots y
finissent en `insufficient_data`, à cause de `unknown_value_policy: exclude`.

---

## STAFFING

`icp-staffing-ch` : **60,0 %**, 5 faux critiques — **tous les cinq sont des
adjudications périmées**, pas des erreurs de fond.

Les décisions datent de 102 à 153 jours contre une politique de 90, alors que les
avis ont été publiés il y a moins d'une semaine (SIMAP publie par lots des
attributions décidées des mois plus tôt). Sans ces cinq, le feed monte à
**70,0 %** — encore sous AMBER, mais c'est le feed que la correction du timing
améliorerait le plus.

Le piège nommé par §28 — le personnel qui est déjà le livrable — n'a frappé
qu'une fois dans ce feed (un mandat de dépannage automobile pour la police,
`no_fit`). Les ICPs à géographie `required` protègent efficacement ce feed.

---

## SPECIALIST SUBCONTRACTING

`icp-subcontracting-eu` : **47,5 %**, 9 D, 8 faux critiques. Décomposition :

| sous-famille | n | précision utile | D |
|---|---|---|---|
| `engineering_architecture` | 8 | **87,5 %** | 0 |
| `construction` | 25 | 44,0 % | 7 |
| `it_digital` | 7 | 14,3 % | 2 |

**Il existe un sous-wedge sain, et il est dans l'ingénierie, pas dans la
construction.** Les 8 signaux `engineering_architecture` — mandats de
planification générale, lots explicitement découpés en sous-lots techniques —
donnent 87,5 % sans aucun D. Mais 8 signaux, c'est sous le plancher de 10 : la
SPEC interdit d'en publier un taux officiel, et je ne le fais pas.

La partie `construction` échoue pour deux raisons cumulées : la fraîcheur (8 des
15 timing=wrong du banc) et des lots mono-métier remportés par le spécialiste
lui-même — l'ICP vendrait à un pair.

---

## IT / DIGITAL

```text
REMOVE FROM MVP LAUNCH
```

18 signaux évalués, **16,7 % de précision utile**, 5 D, 3 faux critiques. Les
motifs sont systématiques et non accidentels :

- **l'éditeur qui vend ses propres licences** (Untis, Cohesity, Gemdat, SAP
  LeanIX) — rien à sous-traiter chez lui ;
- **du matériel classé `it_digital`** par un CPV logiciel, ce qui neutralise
  l'exclusion `equipment_supply` que l'ICP avait explicitement déclarée ;
- **des extensions de maintenance sur le code du titulaire lui-même**.

Aucun sous-wedge IT n'est apparu. Ce n'est pas un réglage à trouver : la
catégorie doit sortir du lancement.

---

## TIMING FAILURES

```text
timing = wrong                15 / 236  = 6,4 %
dont faux signaux critiques   13 / 22   = 59 % de tous les critiques
répartition                   subcontracting-eu 8 · staffing-ch 5 ·
                              plant-hire-ch 1 · remote-specialist 1
```

Le défaut est **transversal, déterministe et clairement isolé** : le filtre de
fraîcheur s'ancre sur la date de publication, alors que la politique de l'ICP
parle de l'âge de l'attribution. Un avis publié cette semaine pour une
attribution d'avril franchit le filtre.

**Le wedge principal retenu ne contient aucune erreur de timing** (0 sur 41).
La correction n'est donc pas requise pour le lancer — elle l'est pour staffing
et subcontracting.

---

## DELIVERABLE OVERLAP

```text
besoin contredit ou non soutenu   9 / 236 = 3,8 %
icp_fit = no_fit                  4 / 236 = 1,7 %
répartition                       plant-hire 3 · remote-specialist 3 ·
                                  national-supplier 1 · ppe-safety 1 ·
                                  subcontracting-eu 1
```

Le wedge principal en contient **zéro** après restriction à
`materials_or_components` — la restriction retire précisément le seul cas de la
famille. Il ne dépend donc pas massivement d'un correctif de ce type au sens de
§32.

---

## LLM VERIFIER DIAGNOSTIC

Diagnostic seulement — ne participe à aucun classement (§33). DeepSeek n'a pas
été appelé ; les résultats proviennent du run SPEC-009A gelé.

11 des 41 signaux du wedge principal portent un résultat du vérificateur :

```text
avant vérificateur       90,9 % de précision utile (10/11)
final_show               8
après vérificateur       87,5 % (7/8)
```

Sur ce wedge, le vérificateur **n'apporte rien** : il retire 3 signaux dont 2
étaient utiles. Ce n'est pas surprenant — il avait été mesuré comme utile en
*promoteur de borderline* (54 % → 85,7 %), pas en nettoyeur d'un feed déjà
propre. L'échantillon est petit (11) et ne tranche pas ; il n'indique simplement
aucune raison de le rebrancher ici.

---

## WEDGE TABLE

| wedge | rev | précision utile | faux | critiques | TOP10 | volume | verdict |
|---|---|---|---|---|---|---|---|
| **Fournisseur d'intrants de chantier × construction × `materials_or_components`** | 41 | **80,5 %** | 0,0 % | **0** | **90,0 %** | 73 | **AMBER** |
| Fournisseur d'intrants × construction (sans restriction de besoin) | 56 | 76,8 % | 1,8 % | 1 | 90,0 % | 122 | RED |
| Sous-traitance spécialisée UE × ingénierie/architecture | 8 | 87,5 % | 0,0 % | 0 | 87,5 % | 10 | INSUFFICIENT SAMPLE |
| Staffing CH × construction | 38 | 63,2 % | 13,2 % | 5 | 80,0 % | 66 | RED |
| EPI/sécurité CH × construction | 40 | 57,5 % | 2,5 % | 1 | 90,0 % | 45 | RED |
| Sous-traitance spécialisée UE × cœur (hors IT) | 33 | 54,5 % | 21,2 % | 7 | 70,0 % | 49 | RED |
| Spécialiste à distance × ingénierie | 13 | 61,5 % | 0,0 % | 0 | 70,0 % | 72 | RED |
| Location de matériel CH × construction | 14 | 35,7 % | 28,6 % | 4 | 50,0 % | 14 | RED |
| Déchets CH | 0 | — | — | — | — | 0 | INSUFFICIENT SAMPLE |

---

## PRIMARY MVP WEDGE

### Fournisseur d'intrants de chantier — matériaux et composants

```text
ARCHÉTYPE CLIENT
  Négociant en matériaux de construction / fournisseur d'intrants de chantier,
  vendant à l'entreprise adjudicataire pendant l'exécution.

CE QU'IL VEND
  Matériaux et composants de construction : granulats, béton, coffrage,
  canalisation, menuiserie, second œuvre, fournitures de chantier.

BESOIN PRIMAIRE          materials_or_components
BESOINS SECONDAIRES      aucun — la restriction au besoin primaire EST le wedge

TYPES DE CONTRAT INCLUS  construction
TYPES EXCLUS             it_digital · equipment_supply · medical_supply ·
                         facility_services · maintenance_repair ·
                         transport_logistics · social_health_services

GÉOGRAPHIE               place_of_performance
TERRITOIRES              CH · DE · FR · ES · PT   (observés dans le feed)
SEUIL DE VALEUR          100 000 CHF / EUR       (hérité, non modifié)
FRAÎCHEUR                120–180 jours           (hérité, non modifié)
SOURCES                  TED + SIMAP — les deux contribuent
```

**Résultats mesurés**

```text
échantillon évalué            41        (30 nouveaux + 11 gold réutilisé)
A actionnables                 7        17,1 %
B utiles                      26
C faibles                      8        19,5 %
D faux/trompeurs               0         0,0 %
faux signaux critiques         0
précision utile            80,5 %
intégrité factuelle       100,0 %
couverture de preuve      100,0 %
signaux génériques             0
erreurs de timing              0
overclaiming                   0
TOP10 précision utile      90,0 %
volume naturel SHOW           73        sur 800 award-lots
volume BORDERLINE             45
```

**Modes d'échec — les 8 signaux C**

| couche | n | nature |
|---|---|---|
| `matching` | 6 | granularité de métier : CVC acheté en gros ventilation, éclairage tramway en gros électricité, micro-tunnelier A63, caténaire ferroviaire, et deux filiales d'un routier de tier 1 intégré verticalement qui produit ses propres enrobés |
| `need graph` | 2 | motif « terrassement ou génie civil » sur un lot de portes métalliques ; un lot routier de 118 kCHF sous-dimensionné |

**Une seule chose bloque le GREEN** : la précision utile, 80,5 % contre 85 %.
Tous les autres gates GREEN passent, y compris le TOP10 à exactement 90 %.
Et les six erreurs de `matching` sont une même erreur : le moteur apparie sur
une catégorie de besoin (`materials_or_components`) sans distinguer **le canal
d'achat du métier**. Si elles étaient corrigées, la précision atteindrait 95 %.

---

## OPTIONAL SECONDARY WEDGE

```text
AUCUN
```

Le seul candidat de qualité est **sous-traitance spécialisée UE ×
ingénierie/architecture** : 87,5 % de précision utile, 0 D, 0 critique. Mais
8 signaux évalués et 10 de volume naturel — sous le plancher de 10 de §11 pour
publier un taux, et très loin des 15 de §36.

§43 interdit explicitement de retenir un second wedge pour élargir l'apparence
du marché. Celui-ci est signalé comme **à surveiller lors du prochain corpus
frais**, pas comme un wedge.

---

## OBSERVED NATURAL VOLUME

Wedge principal, sur le pool gelé de 800 award-lots :

```text
signaux SHOW                    73
signaux BORDERLINE              45
TED                             44
SIMAP                           29
densité observée               9,1 signaux pour 100 award-lots
```

**Ce chiffre n'est pas une estimation annuelle.** La fenêtre SPEC-009 court du
2026-07-10 au 2026-08-17 : cinq semaines, en plein été, la période la plus creuse
de la commande publique européenne. Aucune correction saisonnière n'est
appliquée (§39) — extrapoler serait inventer.

Portée géographique retenue : **CH + UE**. Les deux sources contribuent
substantiellement (60 % TED / 40 % SIMAP) et la précision ne s'effondre sur
aucune des deux, ce qui ne justifierait pas de restreindre le lancement à une
zone.

---

## REQUIRED CORRECTIONS

Pour le wedge principal uniquement, par ordre de rendement. Chaque correction
est justifiée par une erreur réellement observée dans ce wedge — aucune n'est
proposée « au cas où ».

### 1. SPEC-008R2 — granularité de métier dans le matching · **6 des 8 C**

Le moteur apparie sur `materials_or_components` sans distinguer le canal
d'approvisionnement. Un négociant en matériaux de construction se voit proposer
des lots dont les composants s'achètent chez un grossiste électricité, un
grossiste ventilation ou un fabricant de caténaire, et des marchés remportés par
des majors routiers intégrés verticalement qui produisent leurs propres enrobés.

Deux distinctions suffiraient, toutes deux dérivables de champs déjà présents :
le CPV additionnel du lot (et non celui du projet parent), et une notion
d'auto-approvisionnement du gagnant.

### 2. SPEC-007R2 — motif de besoin câblé en dur · **2 des 8 C**

Le motif « Les travaux relèvent du terrassement ou du génie civil » est produit
verbatim sur `cpv` + `amount` seuls. Il est faux sur les lots de second œuvre.
Plus largement, l'énoncé de besoin est **identique mot pour mot dans tout le
banc** : l'ancrage vient entièrement de la description du marché, jamais du
besoin — c'est ce qui plafonne l'actionnabilité à 17 %.

### 3. Garde sur les objets vides · **1 C, transversal**

Plusieurs avis SIMAP publient l'en-tête de formulaire
« WEGLEITUNG INHALT UND ECKDATEN » comme objet du marché, affiché tel quel au
client. Une garde sur les objets non porteurs éviterait de montrer un signal
sans contenu.

**Non requis pour ce wedge** : la correction de la fraîcheur (0 erreur de timing
ici) et la garde de recouvrement de livrable (0 cas ici). Toutes deux sont
requises pour staffing et subcontracting, pas pour lui.

---

## NEXT RECOMMENDED SPEC

Aucun wedge GREEN n'existe. Conformément à §48, la recommandation est :

1. **SPEC-008R2** — granularité de métier dans le matching (correction 1).
2. **SPEC-007R2** — énoncé de besoin ancré sur l'objet réel (correction 2).
3. Puis **SPEC-009C — Fresh Wedge-Specific Signal Benchmark** sur le wedge
   principal : corpus frais, ICP réel du wedge, `commercial-signal-rubric-v1`
   inchangée, **sans concurrence cross-ICP**, gates indicatifs ≥ 100 signaux,
   précision utile ≥ 90 %, critiques = 0, faux ≤ 2 %, TOP20 ≥ 95 %.

Aucune de ces SPEC n'a été commencée (§52).

---

## VPS PORTABILITY CHECK

| Exigence §49 | État |
|---|---|
| Hors ligne après chargement des fixtures | ✅ aucun appel réseau dans toute la SPEC |
| Compatible Linux | ✅ |
| Aucun chemin Windows absolu | ✅ `pathlib`, aucun littéral machine |
| Aucune base de données | ✅ |
| Aucune dépendance cloud managée | ✅ |
| Portable local → VPS → VPS dédié | ✅ un dossier de fixtures, aucun état externe |
| Aucune infrastructure de déploiement créée | ✅ |

Le module `wedge.py` n'importe aucun moteur — vérifié par test AST.

---

## TEST RESULTS

```text
uv run pytest -q            1640 passed        (1608 avant SPEC-009B, +32)
uv run ruff check .         All checks passed
git diff --check            propre
git status                  arbre suivi propre ; SPEC-009B non committée (§53)

uv run ruff format --check  1 écart, rapporté séparément :
    docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md
    committé en d173265, antérieur à toute cette lignée, non modifié (§2, §50)
```

Répartition des 32 tests ajoutés : absence de déduplication cross-ICP,
règles anti-duplication par feed, échantillonnage déterministe et aveugle,
seuils de taille d'échantillon, classement GREEN/AMBER/RED, réutilisation du
gold par identité exacte, dénominateurs, métriques de volume, moteurs intacts.

---

## VERDICT

```text
AMBER WEDGE ONLY
```

Aucun wedge GREEN n'existe aujourd'hui. Un wedge AMBER existe, et il est net :

> **Un fournisseur d'intrants de chantier — matériaux et composants — recevant
> les marchés de construction attribués en Suisse et dans l'UE, verrait
> aujourd'hui un feed utile à 80,5 %, sans aucun faux signal, sans aucun faux
> critique, avec 100 % de faits vérifiables et un top-10 à 90 %.**

Il manque 4,5 points de précision pour le GREEN, et ces 4,5 points portent un
nom : six signaux où le moteur confond « matériaux de construction » et « ce
métier-là s'achète ailleurs ».

Le second résultat de cette SPEC compte autant : **la déduplication cross-ICP
effaçait 127 signaux et trois feeds entiers**. SPEC-009 ne mesurait pas le
produit de Kivou, elle mesurait le produit de ses deux ICPs les plus larges. La
doctrine du feed par client n'est pas une préférence — c'est la condition pour
que le prochain banc mesure quelque chose de réel.

Rien n'est committé pour SPEC-009B (§53). Aucune SPEC-005R, SPEC-007R2,
SPEC-008R2 ni SPEC-009C n'a été commencée (§52).
