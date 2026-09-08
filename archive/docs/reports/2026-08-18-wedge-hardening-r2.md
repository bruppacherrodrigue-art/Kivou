# WEDGE-HARDENING R2 — résolution de métier au niveau du lot par le BKP

**Date** : 2026-08-18 · **Branche** : `main` · **Verdict** : `WEDGE-HARDENING FINAL PASS`

Une seule correction, au seul défaut que le closeout R1 avait isolé : le CPV du
projet écrasait une classification de métier plus précise publiée pour le lot.
Aucun LLM. Rien n'est committé.

---

## PRECONDITION

```text
uv run pytest -q     1674 passed
uv run ruff check .  All checks passed!
git diff --check     propre
```

R1 intact dans le working tree : 19 fichiers modifiés, plus `object_text.py`,
`test_wedge_hardening.py` et les deux artefacts du closeout R1. R2 s'ajoute comme
un diff distinct — un module neuf (`bkp.py`), un point d'entrée modifié dans la
compréhension de contrat, un fichier de tests neuf, deux fixtures neuves.

---

## BKP AUTHORITY

Le dépôt ne contenait **aucune** nomenclature BKP : ni table, ni fixture, ni
source versionnée. Une recherche exhaustive n'a trouvé le sigle que dans du
texte publié à l'intérieur des corpus, et une seule mention en commentaire.

Source retenue : **l'arbre BKP officiel exposé par la plateforme SIMAP**
(`browse_bkp_tree`), parcouru depuis la racine le 2026-08-18 — les 7 catégories
racines, puis les niveaux 2 et 3 de chaque famille observée dans le corpus. BKP
= *Baukostenplan*, le plan suisse des coûts de construction. C'est la
nomenclature de la plateforme qui publie les avis que nous lisons : elle décrit
ces lots-là, dans les termes de leur propre acheteur.

La table est **transcrite, locale et versionnée** (`bkp-trade-v0.1`). Aucun
appel réseau à l'exécution (§39). Aucun code n'a été mappé d'intuition : chaque
entrée porte en commentaire l'intitulé allemand rendu par l'autorité.

---

## BKP CORPUS STUDY

Étude conduite **avant** toute modification du moteur, sur les 800 award-lots du
pool gelé — pas sur les trois erreurs connues.

```text
award-lots portant au moins un code BKP        53 / 800
  · source simap                               52
  · source ted                                  1   (« BKP 282.5 Wandbekleidung aus Holz »)
champs porteurs                          title et description, à parts égales
codes distincts observés                       43
occurrences de code                            66

le BKP tranche un métier                       47
le BKP ne tranche pas                           6
  · famille reconnue sans domaine représentable  5
  · codes de métiers différents                  1   (BKP 227/285)
```

Confrontation au CPV, sur les 47 qui tranchent :

```text
BKP == CPV, accord                              7
BKP != CPV, conflit                            17     ← le BKP l'emporte
CPV muet (45000000), BKP renseigne             23     ← gain net d'information
```

Domaines établis par le BKP : `technical_installation` 25, `general_building` 11,
`interior_finishing` 9, `earthworks_demolition` 2.

Les 17 conflits, un par un, sont tous du même type et tous cohérents : de
l'électricité, de la ventilation, du froid, du chauffage, du sanitaire, de la
technique de bassin, de l'automation, de la caisse, de la plâtrerie, de la
serrurerie, du terrassement — publiés sous un CPV de bâtiment. **Aucun conflit
ne déplace un lot vers un métier absurde.** Les 23 cas à CPV muet sont un gain
pur : ces lots n'avaient aucun métier avant, ils en ont un maintenant.

---

## BKP PARSER

Structurel et étroit (§12). Le marqueur `BKP` est **obligatoire** : sans lui,
aucun nombre n'est un code.

```text
marqueur   (?<![A-Za-z])BKP(?![A-Za-z])[\s.:#-]*
code       (?<!\d)(\d{1,3})(?:\.(\d))?(?!\d)
chaînage   [ \t]*[,;/_+&][ \t]*
```

La frontière est posée sur les **lettres**, pas sur `\b` : les avis écrivent
« BKP224 » sans espace et « Q26.0169_BKP 211 » après un souligné, deux cas où
`\b` ne se déclenche pas. `ABKP 230` et `BKPX 230` restent refusés.

Les gardes `(?<!\d)` / `(?!\d)` empêchent qu'un millésime (`2026/2027`) ou une
référence interne (`Q26.0169`) fournisse un faux code. Un CPV n'est jamais lu
comme un BKP.

Formes réellement observées et toutes reconnues : `BKP 230`, `BKP 23`,
`BKP 272.8`, `BKP 211.7`, `BKP224, 221.1`, `BKP 222_224`, `BKP 227/285`.

**Aucun libellé ne décide.** « Elektro », « Sanitär », « Garten »,
« Photovoltaik » restent du texte — preuve ou affichage, jamais décideur (§5).

---

## BKP → TRADE DOMAIN MAPPING

Le préfixe le plus long gagne, exactement comme la table CPV de R1. La décimale
ne classe pas : `272.8` se lit dans `272`, puis `27`.

```text
11  Räumungen, Terrainvorbereitungen      → earthworks_demolition
17  Spezialtiefbau                        → special_civil
20  Baugrube                              → earthworks_demolition
21  Rohbau 1                              → general_building
22  Rohbau 2                              → general_building
23  Elektroanlagen                        → technical_installation
24  HLK-Anlagen, Gebäudeautomation        → technical_installation
25  Sanitäranlagen                        → technical_installation
26  Transportanlagen, Lageranlagen        → technical_installation
27  Ausbau 1                              → interior_finishing
28  Ausbau 2                              → interior_finishing
      286 Bautrocknung                    → aucun
      287 Baureinigung                    → aucun
      288 Gärtnerarbeiten (Gebäude)       → aucun
33-36  (Betriebseinrichtungen)            → technical_installation
37-38  (Betriebseinrichtungen)            → interior_finishing
46  Trassenbauten                         → roadworks_civil
```

La série 3 reprend mot pour mot les intitulés de métier de la série 2 dans
l'autorité : la mapper identiquement lit l'autorité, ne l'interprète pas.

**Familles reconnues mais sans domaine représentable** — elles ne déclassent
rien (§15) : `10`, `12`, `13`, `14`, `15`, `16`, `19`, `29`, `39`, `40`, `41`,
**`42 Gartenanlagen`**, `44`, `45`, `47`, `48`, `49`, et les séries `0`, `5`, `9`.

> `BKP DOMAIN NOT REPRESENTABLE — 42 Gartenanlagen`
>
> Le jardinage est un métier réel qu'aucun domaine de la taxonomie R1 ne
> représente : ni gros œuvre, ni second œuvre, ni terrassement. Aucun domaine
> n'a été créé pour le loger. Le cas reste non résolu, et le CPV reste en place.

Aucun nouveau `TradeDomain` n'a été créé (§15). La taxonomie R1 est celle de R2.

---

## LOT / PROJECT PRECEDENCE

§8 demandait d'inspecter les champs réels avant de copier une hiérarchie. Je l'ai
fait, et la hiérarchie théorique **ne s'applique pas** ici :

```text
procédures à plusieurs award-lots                                    116
procédures où le CPV est constant pendant que le BKP varie             0
```

Dans ce corpus, chaque award-lot SIMAP est sa propre publication, et le CPV
comme la description proviennent du même objet `procurement`. Il n'existe pas,
dans les données, de distinction champ-de-lot contre champ-de-procédure.

La structure réelle est autre, et elle est massive :

```text
projet « Umbau Hallen- und Freibad Talegg »  →  13 avis d'attribution
CPV de chacun des 13                             45212212  (identique)
BKP de chacun des 13                             244+246 · 221 · 213 · 222+224 ·
                                                 230 · 359 · 259 · 250 · 243 ·
                                                 272.8 · 339 · 239 · 237

projet « Neubau Kantonsschule Stein »        →  7 avis, CPV 45000000 pour tous
projet « Mieterausbau Kantonales Labor »     →  5 avis, CPV 45000000 pour tous
```

Treize métiers — ventilation, maçonnerie, charpente acier, ferblanterie,
électricité, technique de bassin, sauna, sanitaire, chauffage, revêtement de
bassin, caisse, photovoltaïque, automation — sous un CPV constant qui ne
discrimine rien. Le seul champ qui distingue est le code BKP.

**La précédence retenue n'est donc pas « le lot bat la procédure » mais : une
classification de métier explicitement publiée pour CET avis prime un code
marchandise constant sur tous les métiers du projet.** C'est ce que les données
portent, et rien de plus.

Le CPV n'est jamais supprimé : sa `Claim` et son `Evidence` restent intacts dans
`facts["cpv"]`.

---

## CONFLICT POLICY

Le désaccord n'est pas masqué. Il vit dans la `Claim` de `trade_domain` — la
structure existante suffisait, aucun champ public n'a été créé (§10).

```text
BKP tranche, CPV muet
  rule : « corps de métier porté par le code BKP publié »

BKP tranche, CPV en désaccord
  rule : « corps de métier porté par le code BKP publié
           — il prime le CPV publié, qui indiquait « general_building » »

BKP présent mais sans domaine représentable
  rule : « corps de métier porté par la division CPV ;
           code BKP publié, sans domaine de métier correspondant — le CPV est conservé »

BKP présent, codes de métiers différents
  rule : « corps de métier porté par la division CPV ;
           codes BKP de métiers différents : general_building, interior_finishing
           — le CPV est conservé »
```

La source et le conflit se lisent donc tous deux dans le texte de la règle, avec
l'`Evidence` qui pointe le champ porteur du code. On peut expliquer plus tard
pourquoi Kivou a préféré le BKP au CPV, et pourquoi il ne l'a pas fait.

**Aucun override si le BKP est incertain** (§11) : code inconnu de la table,
famille sans domaine, ou codes contradictoires laissent le CPV en place. Pas de
fuzzy matching, pas de code voisin, pas de devinette. Les deux champs `title` et
`description` sont **fusionnés** avant résolution, jamais mis en concurrence :
un titre et une description annonçant deux métiers différents ne tranchent pas.

---

## CONTRACT UNDERSTANDING VERSION

```text
contract-understanding-v0.2   →   contract-understanding-v0.3
```

La sémantique de `trade_domain` change réellement : elle n'est plus dérivée du
seul CPV. R1 avait déjà porté v0.1 → v0.2, et le gold du closeout R1 enregistre
v0.2 ; passer à v0.3 laisse cet artefact dire la vérité sur ce qui l'a produit.

Nouvelle version de politique : `bkp-trade-v0.1`.

Inchangées, la sémantique de leurs composants n'ayant pas bougé :
`need-graph-v0.2`, `need-rules-v0.5`, `icp-match-v0.2`, `signal-score-v0.2`,
`reference-icps-v0.1`.

---

## THREE REMAINING C CASES

| | `127931a14b` | `239917c2bf` | `94eb38816d` |
|---|---|---|---|
| CPV publié | 45212212 | 45210000 | 45210000 |
| ancien domaine | general_building | general_building | general_building |
| BKP publié | `272.8` | `231.5` | `421` |
| sens d'autorité | 272 Metallbauarbeiten (27 Ausbau 1) | 231 Starkstromanlagen (23 Elektroanlagen) | 421 Gärtnerarbeiten (42 Gartenanlagen) |
| nouveau domaine | **interior_finishing** | **technical_installation** | *non résolu* |
| décision wedge | `show` (métier primaire) | **`exclude`** | `show` (CPV conservé) |
| Evidence | champ `description`, `BKP 272.8` | champ `title`+`description`, `BKP 231.5` | — (le CPV garde la sienne) |
| verdict après réadjudication | **C → B** | sorti du feed | **C**, inchangé |

Deux des trois sont résolus, chacun par un mécanisme différent et honnête :

- **`239917c2bf`** — une centrale photovoltaïque de 410 kWp est du courant fort.
  L'autorité la place en `23 Elektroanlagen`, hors cible pour un négoce de
  matériaux : le signal sort du feed. C'est exactement le défaut que R2 visait.
- **`127931a14b`** — un revêtement de bassin est de la construction métallique
  (`272 Metallbauarbeiten`, `27 Ausbau 1`), pas du gros œuvre. Il reste dans le
  feed, mais avec le bon métier — et les deux adjudicateurs, en aveugle, l'ont
  jugé **utile** (B) là où R1 le jugeait faible.
- **`94eb38816d`** — reste `C`. `42 Gartenanlagen` n'a pas de domaine
  représentable, donc pas d'override. **Aucune règle n'a été créée pour ce seul
  cas** (§34, §32).

Le moteur ne produit plus de `general_building` par défaut simplement parce que
le CPV parent dit construction générale.

---

## R1 NON-REGRESSION

```text
les six mismatch de SPEC-009B, tous hors feed :
  rail_infrastructure     exclude
  technical_installation  exclude   ×2
  special_civil           borderline
  roadworks_civil         borderline ×2

les deux corrigés de R1 :
  19d9fab760  show   sujet « Komplett- u. Teilbauleistungen bei Schulerweiterung (general_building) »
  0cffdfe9e5  show   sujet « Neubau BKP 272.0 Innentüren aus Metall (interior_finishing) »
              l'assertion « relèvent du terrassement » reste absente des deux

la garde d'objet informatif, inchangée :
  « WEGLEITUNG INHALT UND ECKDATEN » refusé · « Façades » conservé

tests R1 : 34 passed
```

Effet de bord favorable et non recherché : `0cffdfe9e5` passe de
`general_building` à `interior_finishing` — le BKP 272.0 que son objet publiait
déjà. Sa réadjudication en aveugle le confirme `B`.

---

## NATURAL WEDGE VOLUME

ICP `icp-construction-inputs-ch-eu-v0` sur les 800 award-lots gelés :

```text
show                  32        (R1 : 39)
borderline            17
exclude              547
insufficient_data    204

gate : SHOW >= 25  →  PASS
```

La baisse de 39 à 32 est le travail attendu : sept lots dont le BKP révèle un
métier hors cible quittent le feed.

---

## BLIND READJUDICATION

`wedge_hardening_r2_blind.json`. Contrôle de fuite automatique : aucun des
champs `score`, `band`, `decision`, `verdict`, `gold_verdict`, `rule_ids`,
`trade_domain`, `primary_trade_domains`, `primary_failure_layer`, `bkp`,
`conflict` n'apparaît. Le diagnostic de conflit BKP est invisible pour
l'adjudicateur (§29).

Périmètre déterminé mécaniquement, en comparant les sorties R1 et R2 signal par
signal sur `category`, `subject`, `statement` et `reasoning` :

```text
sortis du feed                      2    (239917c2bf, 9fa4803816)
sortie MATÉRIELLEMENT changée       3    (0cffdfe9e5, 127931a14b, 9a0f6b5342)
sortie INCHANGÉE                   20    verdict R1 réutilisé à l'identité exacte
```

Les trois changées ont toutes vu leur métier passer à `interior_finishing`, ce
que le sujet du besoin affiche. Deux perspectives indépendantes,
`commercial-signal-rubric-v1`, aucun appel OpenRouter ni DeepSeek :

```text
Reviewer A — B2B Sales Director            A=1 B=2 C=0 D=0
Reviewer B — Procurement / Contract Analyst A=1 B=2 C=0 D=0
arbitrage requis                            0
```

---

## R2 GOLD

`tests/fixtures/signal100/wedge_hardening_r2_gold.json`. Les golds SPEC-009B et
R1 ne sont pas modifiés.

```text
A                        7
B                       15
C                        1
D                        0
                      ────
                        23

exact agreement          87,0 %
within-one-grade        100,0 %      (gate >= 90 %  → PASS)
arbitrations                 0

réadjugés                    3
réutilisés à l'identique    20
```

---

## USEFUL RETENTION

**SUPERVISOR METRIC REFINEMENT** — §25 remplace la rétention brute par le rappel
utile, mesuré contre le gold réel du closeout R1. Ce n'est pas une correction de
résultat : c'est une métrique plus juste, désormais mesurable parce que le gold
existe.

```text
utiles du gold R1                        22
utiles de R1 encore retenus ET utiles    21
useful retention                    95,45 %      (gate >= 80 %  → PASS)
```

Le seul utile perdu est `9fa4803816` — un lot `BKP 250 Sanitärinstallationen`,
c'est-à-dire du sanitaire, que l'autorité place hors du marché d'un négoce de
matériaux. Sa sortie est un effet correct de la règle, pas une casse.

Gain symétrique, non compté dans la rétention : `127931a14b` passe de faible à
utile. Un signal faible devenu utile est un gain, pas une rétention.

---

## FINAL WEDGE METRICS

| gate §31 | exigé | mesuré | |
|---|---|---|---|
| useful precision | ≥ 90 % | **95,65 %** | PASS |
| false / misleading | 0 | **0** | PASS |
| critical false | 0 | **0** | PASS |
| factual integrity | 100 % | **100,00 %** | PASS |
| proof coverage | 100 % | **100,00 %** | PASS |
| generic signal rate | ≤ 5 % | **4,35 %** | PASS |
| trade mismatch false shows | 0 | **0** | PASS |
| useful retention | ≥ 80 % | **95,45 %** | PASS |
| natural wedge SHOW volume | ≥ 25 | **32** | PASS |
| rubric agreement within one grade | ≥ 90 % | **100,00 %** | PASS |

Hors gate : `actionable` 30,43 %, `weak` 4,35 %, erreurs de timing 0,
overclaiming critique 0.

Trajectoire des trois mesures aveugles successives :

```text
SPEC-009B (gold périmé, 41 signaux)   80,49 %
R1 closeout (25 signaux, aveugle)     88,00 %
R2 (23 signaux, aveugle)              95,65 %
```

---

## BUG GOVERNANCE

```text
BUG
  La compréhension de contrat dérivait le corps de métier du seul CPV. Sur les
  sources qui publient une classification de métier par avis, ce CPV décrit le
  PROJET : treize avis du même chantier le partagent pour treize métiers.

IMPACT
  53 award-lots sur 800 publient un code BKP. 17 d'entre eux recevaient un
  métier contredit par leur propre classification publiée, et 23 n'en recevaient
  aucun alors que leur avis le donnait. Conséquence commerciale mesurée : trois
  signaux faibles dans le feed du wedge, dont deux jugés non spécifiques.

AFFECTED PRIOR RESULTS
  Aucun résultat historique ne devient non interprétable. SPEC-009, SPEC-009A et
  SPEC-009B restent des mesures valides de leurs propres versions de moteur ;
  leurs sceaux continuent d'épingler `contract-understanding-v0.1`, et leurs
  empreintes sont inchangées. Le closeout R1 reste la mesure valide de R1 —
  88,00 %, et non 92,00 %.

FIX
  signals/understanding/bkp.py : parser structurel à marqueur obligatoire et
  table d'autorité locale versionnée. La classification publiée prime le code
  marchandise du projet, et seulement quand elle tranche.

REGRESSION TEST
  tests/test_wedge_hardening_r2.py — 33 tests. Cycle rouge-vert vérifié :
  override neutralisé → 6 échecs sur 33, restauré → 33 verts.
```

Aucun `PRIOR RESULT INVALIDATED`.

---

## SPEC-006/007/008/009 NON-REGRESSION

```text
SPEC-006  AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False. Intouché.
          Le vérificateur commercial reste expérimental et isolé — tests d'isolation verts.
SPEC-007  need-graph-v0.2 / need-rules-v0.5 inchangés depuis R1 : R2 ne touche
          pas au Need Graph. Le gold `need_final` et ses SHA sont intacts.
SPEC-008  icp-match-v0.2 inchangé depuis R1. Les sept ICPs de référence ne
          déclarent aucun métier ; leur bibliothèque et son SHA sont intacts.
SPEC-009  corpus 7996beae… et gold 21be11fc… byte-identiques. Le sceau épingle
          toujours contract-understanding-v0.1 : aucun ancien SHA ne bouge, et
          aucun banc historique ne prétend avoir tourné sur v0.3.

71 tests d'intégrité et de non-régression ciblés : tous verts.
```

---

## VPS PORTABILITY

```text
Python pur, déterministe                    oui
hors ligne à l'exécution                    oui — la table BKP est locale et versionnée
appel réseau au runtime                     aucun
LLM au runtime                              aucun
base de données                             aucune
dépendances ajoutées                        aucune (pyproject.toml, uv.lock intacts)
chemins absolus dans le code ajouté          aucun
complexité du parsing et du mapping         O(longueur du texte) puis O(1) par code
                                            — trois expressions régulières et un dict
```

L'autorité SIMAP n'a été consultée **qu'à la conception**, pour transcrire la
table. Aucun service externe de classification en production.

---

## TEST RESULTS

```text
uv run pytest -q          1707 passed in 13,93s      (1674 avant R2, +33)
uv run ruff check .       All checks passed!
git diff --check          propre
uv run ruff format --check .
                          1 file would be reformatted
```

Le défaut de formatage est **le défaut Markdown historique déjà connu**, rapporté
séparément : `docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md`,
committé en `d173265`, dont ruff reformate les blocs de code Python. Hors
périmètre, non touché. `ruff format --check src tests` passe sans réserve.

---

## OPEN QUESTIONS

1. **`42 Gartenanlagen` n'a pas de domaine.** Le seul signal faible restant est
   un lot de jardinage. Ni gros œuvre, ni second œuvre, ni terrassement ne le
   décrivent. Créer un domaine pour lui seul aurait été exactement ce que §32
   interdit. La question — le paysagisme est-il un marché du négoce d'intrants ?
   — est commerciale, pas technique.

2. **La couverture BKP est étroite.** 53 award-lots sur 800, dont 52 sur SIMAP.
   La règle est source-neutre par architecture, mais ne mord aujourd'hui que là
   où un acheteur publie un code BKP. Les marchés TED restent classés au CPV.

3. **Aucune autre nomenclature n'est reconnue.** Les codes NPK, CPC ou eCCC-BAT
   suisses, et les nomenclatures nationales des autres États, ne sont pas lus.
   L'architecture les accueillerait ; les données du corpus ne les justifiaient
   pas ici.

4. **Le gold R2 mêle deux régimes.** 20 verdicts sont réutilisés de R1 à
   l'identité exacte de sortie, 3 sont réadjugés. C'est le protocole de
   SPEC-009B, et il tient parce que la comparaison des sorties est mécanique —
   mais l'échantillon aveugle neuf de cette phase ne compte que 3 signaux.

5. **La rétention brute n'est plus mesurée.** §25 l'a remplacée par le rappel
   utile. Le sous-échantillon de 23 signaux reste petit : c'est SPEC-009C, sur
   des awards frais, qui décidera commercialement du wedge.

---

# VERDICT

```text
WEDGE-HARDENING FINAL PASS
```

Les dix gates de §31 passent.

Ce que ce PASS dit, et ne dit pas :

- **Il ne prétend pas que la règle soit conçue pour ces trois cas.** Elle mord
  sur 47 award-lots du pool, dont 23 que le CPV laissait sans métier. Deux des
  trois cas visés sont résolus, le troisième est explicitement laissé ouvert, et
  un utile a été perdu au passage — un lot sanitaire que l'autorité place hors
  du marché du négoce.
- **Il ne remplace pas une validation commerciale.** 23 signaux dans un
  sous-échantillon gelé, dont 3 seulement adjugés à neuf. Le wedge n'est pas
  prouvé ; il est prêt à être mesuré.
- **Il repose sur une autorité externe transcrite, pas inventée.** Chaque
  entrée de la table cite l'intitulé rendu par l'arbre BKP officiel de SIMAP.

**Rien n'est committé** (§44). SPEC-009C n'est pas engagée.
