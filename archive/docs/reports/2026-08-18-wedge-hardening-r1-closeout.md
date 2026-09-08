# WEDGE-HARDENING R1 CLOSEOUT — réadjudication en aveugle et audit de portée

**Date** : 2026-08-18 · **Branche** : `main` · **Verdict** : `WEDGE-HARDENING FINAL FAIL`

Deux vérifications finales, aucune modification algorithmique. Le seul changement
au code est le nom et la description de l'ICP candidat, que §6 autorise pour
refléter exactement sa configuration.

---

## BLIND READJUDICATION

Les 25 signaux retenus ont été réadjugés depuis zéro sur leur sortie **nouvelle**
— nouveau `ResourceNeed`, nouveau `subject`, nouvelle `reasoning`.

**Vue aveugle** — `tests/fixtures/signal100/wedge_hardening_r1_blind.json`.
Contrôle automatique de fuite : aucun des champs `score`, `band`, `decision`,
`normalized_score`, `verdict`, `gold_verdict`, `rule_ids`, `mechanism_facts`,
`pressure_facts`, `trade_domain`, `primary_trade_domains`,
`primary_failure_layer` n'apparaît dans le fichier. Les `limitations` sont
transmises expurgées de toute mention de métier, afin que l'état du trade-match
reste invisible. Les adjudicateurs voient : gagnant, faits du contrat, preuves,
besoins dérivés avec sujet et justification, ICP cible, timing, limitations.

**Deux perspectives indépendantes**, cinq lots de cinq signaux chacune, dix
adjudicateurs sans communication entre eux :

- **Reviewer A — B2B Sales Director** : A=8, B=14, C=3, D=0
- **Reviewer B — Procurement / Contract Analyst** : A=7, B=15, C=2, D=1

Aucun appel OpenRouter ni DeepSeek. Rubrique `commercial-signal-rubric-v1`,
inchangée.

**Validation** : 25/25 revues complètes de chaque côté, vocabulaire fermé
respecté, **zéro incohérence de rubrique** détectée par `rubric_consistency()`.

**Arbitrage** : un seul requis, sur le seul désaccord de plus d'un grade
(`239917c2bf`, A=C contre B=D). L'arbitre a reçu la preuve brute et la rubrique,
jamais les verdicts précédents. Il a tranché **C** — faits exacts, aucun
déclencheur `D`, mais besoins génériques sur un objet mal compris. Sa lecture
rejoint sans le savoir la limite déjà nommée en question ouverte du rapport
précédent : une centrale photovoltaïque classée `general_building` par le CPV du
projet.

---

## NEW GOLD DISTRIBUTION

Artefact : `tests/fixtures/signal100/wedge_hardening_r1_gold.json`.
Le gold SPEC-009B (`wedge_gold.json`) **n'est pas modifié**.

```text
A                                6
B                               16
C                                3
D                                0
                              ────
                                25

exact agreement            21/25 = 84,0 %
within-one-grade agreement 25/25 = 100,0 %      (gate >= 90 %  → PASS)
arbitrations                     1
```

L'accord à un grade est **parfait** : les deux perspectives n'ont jamais divergé
de plus d'un cran sauf une fois. La doctrine commerciale est stable, ce qui rend
les chiffres qui suivent interprétables.

---

## OLD VS NEW VERDICTS

```text
signal        009B   new   changé   raison du changement
────────────────────────────────────────────────────────────────────────────────
2ce8b05c17      A     A    non
4bc8232d6a      A     A    non
9e04550bdd      A     A    non
ffd0dfe063      A     A    non
0b51bab972      A     B    OUI     peinture/plâtrerie : fit réel mais vérification encore requise
8f08f3c486      A     B    OUI     agencement intérieur : ancrage jugé partiel, pas immédiat
1c025a9f9c      B     A    OUI     lot « Tischler 1 Türen », métré publié → devient directement prospectable
2815aaec98      B     A    OUI     Estricharbeiten 630 kEUR chez un spécialiste → ancrage suffisant
04ce27ea37      B     B    non
0f17333d4e      B     B    non
14e8d46e83      B     B    non
21116fb3a2      B     B    non
2587f7ae40      B     B    non
4a00b8636f      B     B    non
4d6598bfe5      B     B    non
88be693cb0      B     B    non
991a58cd63      B     B    non
9a0f6b5342      B     B    non
9fa4803816      B     B    non
bfcd09ed33      B     B    non
127931a14b      B     C    OUI     habillage de bassin + whirlpool lu comme general_building
239917c2bf      B     C    OUI     centrale photovoltaïque lue comme general_building   [arbitré]
94eb38816d      B     C    OUI     BKP 421 travaux de jardinage lus comme general_building
0cffdfe9e5      C     B    OUI     ← mis en évidence par §4
19d9fab760      C     B    OUI     ← mis en évidence par §4
────────────────────────────────────────────────────────────────────────────────
verdicts changés : 9 / 25          A: 6 → 6      B: 17 → 16      C: 2 → 3
```

### Les deux cas que §4 demandait de mettre en évidence

Ils n'ont reçu **aucun traitement particulier** pendant l'adjudication : ils
étaient noyés dans leurs lots, indiscernables des autres.

**`19d9fab760` — C → B.** A et B l'ont tous deux noté `B`, sans arbitrage.
Sujet désormais affiché : « Komplett- u. Teilbauleistungen bei Schulerweiterung
(general_building) ». Le reproche de SPEC-009B — un objet d'une ligne, sans
ancrage — ne s'applique plus : la hiérarchie de champs a fait remonter la
description du lot à la place du titre `Totalübernehmer`. La réserve subsistante
des deux adjudicateurs porte ailleurs, sur le fait que le gagnant est un
*Bauträger* de services plutôt qu'un exécutant.

**`0cffdfe9e5` — C → B.** A et B l'ont tous deux noté `B`, sans arbitrage.
Sujet : « Neubau BKP 272.0 Innentüren aus Metall (general_building) ».
L'approvisionnement en profilés, vitrages et ferrures est jugé plausible par les
deux. Le besoin d'engins reste critiqué par les deux — mais il n'affirme plus
que « les travaux relèvent du terrassement », et cette assertion était l'objet
même de la correction 2.

**Les deux corrections ciblées ont donc produit exactement l'effet visé sur les
deux cas visés.** Ce n'est pas ce qui fait échouer la mission.

---

## FINAL HARDENING METRICS

Recalculées uniquement sur les 25 signaux, à partir du gold neuf.

| métrique | gate | mesuré | |
|---|---|---|---|
| useful precision | ≥ 90 % | **88,00 %** | **ÉCHEC** |
| false / misleading | 0 | **0** | PASS |
| critical false | 0 | **0** | PASS |
| factual integrity | 100 % | **100,00 %** | PASS |
| proof coverage | 100 % | **100,00 %** | PASS |
| generic signal rate | ≤ 5 % | **8,00 %** | **ÉCHEC** |
| trade mismatch false shows | 0 | **0** | PASS |
| retention | ≥ 60 % | **61,0 %** | PASS |
| retained signals | ≥ 25 | **25** | PASS |

Métriques hors gate :

```text
actionable rate           24,00 %
weak rate                 12,00 %
timing errors                  0
critical overclaiming          0
```

### Correction du chiffre annoncé au rapport précédent

Le rapport du 2026-08-17 annonçait **92,00 %**, mesurés contre le gold SPEC-009B
antérieur à la reformulation, avec une réserve explicite : la réadjudication
restait due. Cette réadjudication a eu lieu et donne **88,00 %**.

J'avais qualifié la mesure de « conservatrice ». C'était faux dans sa direction :
je supposais que nommer le sujet ne pouvait qu'améliorer ou laisser stable le
jugement. Neuf verdicts ont bougé, dans les deux sens, pour un solde de **−1
signal utile**. Nommer le sujet a effectivement réparé deux cas — et en a exposé
trois autres que le gold précédent ne voyait pas.

### Pourquoi c'est un échec, et de quoi

Les trois `C` invoquent **la même couche primaire**, sans exception :

```text
primary_failure_layer :  { "contract understanding": 3 }
```

```text
127931a14b   BKP 272.8 Poolauskleidung inkl. Whirlpool     → general_building
239917c2bf   Lieferung und Montage einer PVA, 410 kWp      → general_building
94eb38816d   Instandsetzung BKP 421 Gärtnerarbeiten        → general_building
```

Un bassin de piscine, une centrale photovoltaïque et des travaux de jardinage
portent tous le CPV du **projet parent**, pas celui du lot. Le domaine de métier
est donc juste au niveau de la division CPV et faux au niveau du lot vendu. Les
deux signaux `generic` sont deux de ces trois.

C'est précisément la limite nommée en question ouverte n°1 du rapport précédent —
« le CPV du lot est parfois celui du projet ». Elle y était estimée sans effet
sur la précision parce que le gold d'alors jugeait ces cas utiles. Trois
adjudicateurs indépendants la jugent aujourd'hui décisive.

Aucune correction n'est appliquée : §0 gèle la taxonomie, les mappings CPV, le
Need Graph, le matching et la garde d'informativité, et §6 interdit toute
modification algorithmique dans cette clôture.

---

## GEOGRAPHIC SCOPE AUDIT

### ACTUAL GEOGRAPHIC SCOPE

> Le lieu d'exécution doit être **publié**, et son code pays doit appartenir à
> l'ensemble `{CH, DE, FR, ES, PT}`.

C'est tout. Le filtre est une appartenance à un ensemble de codes pays —
`wanted = {territory.country for territory in icp.territories}` — sans aucune
notion de bloc, d'union ou de région. `geography_basis = place_of_performance`
et `geography_policy = required` impliquent qu'un lieu absent produit
`insufficient_data`, jamais un rapprochement : sur les 800 award-lots du pool,
204 n'ont aucun lieu publié et sont inévaluables pour cet ICP.

Les deux formulations en circulation étaient fausses, chacune à sa manière :

- « **Suisse et zone euro** » — la zone euro compte vingt États, dont quinze que
  l'ICP ne cible pas (IT, NL, BE, AT, IE, FI, GR…), et n'inclut pas la Suisse.
- « **CH + UE** » — l'Union compte vingt-sept États ; le modèle en autorise
  quatre, plus la Suisse qui n'en fait pas partie.

### Pourquoi ces territoires ont été choisis

**Derived from observed corpus, via the SPEC-009B wedge.** La mesure est sans
ambiguïté : les cinq pays sont **exactement** l'empreinte des 41 signaux du
wedge.

```text
pays des 41 signaux du wedge SPEC-009B      DE 17 · CH 11 · FR 7 · ES 5 · PT 1  = 41
territoires de l'ICP candidat               CH · DE · FR · ES · PT
```

Ce n'est donc ni une commodité de banc, ni une hypothèse commerciale. Mais c'est
une **couverture de mesure, pas une frontière de marché**, et l'empreinte est
confondue par les ICPs qui l'ont produite :

```text
icp-materials-eu         FR DE ES IT PT BE NL
icp-national-supplier    CH FR DE IT ES PL
union des deux           CH DE ES FR IT PT BE NL PL     ← 9 pays éligibles
wedge observé dans       CH DE ES FR PT                 ← 5
jamais produit de signal IT BE NL PL                    ← 4
jamais éligibles         PL 43 lots · RO 42 · CZ 22 · SE 16 · HR 16 · BG 13 …
```

Le corpus n'établit donc **pas** que le wedge échoue en Tchéquie, en Roumanie ou
en Suède : il n'y a jamais été testé. Conformément à la règle de §5, la
géographie n'est pas élargie pour augmenter le volume ; le scope est nommé
honnêtement pour ce qu'il est.

### EU-WIDE TERRITORY MODEL NOT YET AVAILABLE

`Territory` ne porte que trois champs — `country`, `subdivision_code`,
`subdivision_scheme` — et aucune constante du dépôt ne représente l'Union
européenne. Il n'existe aucune représentation canonique permettant de déclarer
« Union européenne » autrement qu'en énumérant vingt-sept `Territory`.
Conformément à §5, cette abstraction n'est pas créée ici.

**Observation annexe, non traitée** (§6). La docstring de `Territory` affirme
que « sur le corpus mesuré, aucun lieu d'exécution ne publie de subdivision ».
C'était vrai des 100 award-lots de SPEC-008. Sur les 800 du pool, **533 en
publient une** — 463 en NUTS, 70 en ISO-3166-2. L'observation est périmée ; la
logique qu'elle justifie reste correcte, et n'est pas touchée.

### Correction appliquée (§6)

Seul changement au code de cette clôture — nom et description de l'ICP :

```diff
- name="Négoce d'intrants de chantier — Suisse et zone euro",
+ name="Négoce d'intrants de chantier — CH, DE, FR, ES, PT",
```

La docstring énonce désormais la portée réelle, l'origine des cinq pays, et le
fait qu'ils mesurent une couverture et non un marché.

---

## ACTUAL WEDGE DEFINITION

```text
client type        négoce d'intrants de chantier (gros œuvre et second œuvre)
besoin primaire    materials_or_components
besoin secondaire  equipment_or_rental
type de contrat    construction
corps de métier    primaires   general_building · interior_finishing · earthworks_demolition
                   secondaires roadworks_civil · special_civil
                   hors cible  technical_installation · rail_infrastructure · equipment_hire
                   jamais positif  unknown_or_general
géographie         lieu d'exécution PUBLIÉ et ∈ {CH, DE, FR, ES, PT}
seuils             CHF 100 000 · EUR 100 000
âge maximal        120 jours depuis la publication
mode               metadata_fallback (aucun document de marché lu)
volume naturel     39 SHOW pour 800 award-lots (4,9 pour 100)
```

Formulation honnête en une phrase : *un négoce de matériaux livrant le gros œuvre
et le second œuvre, sur des marchés de travaux d'au moins 100 k dont le lieu
d'exécution est publié en Suisse, Allemagne, France, Espagne ou Portugal.*

---

## TEST RESULTS

```text
uv run pytest -q          1674 passed in 13,99s
uv run ruff check .       All checks passed!
git diff --check          propre
uv run ruff format --check .
                          1 file would be reformatted
```

Le défaut de format est **le défaut Markdown historique déjà connu**, rapporté
séparément comme demandé : il porte sur
`docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md`,
document de plan committé en `d173265`, dont ruff reformate les blocs de code
Python qu'il contient. Il est antérieur à ce travail et n'a pas été touché.
`ruff format --check src tests` passe sans réserve.

Aucun test n'a été modifié dans cette clôture.

---

# VERDICT

```text
WEDGE-HARDENING FINAL FAIL
```

Deux gates de §3 ne passent pas :

```text
useful precision      88,00 %   <  90 %
generic signal rate    8,00 %   >   5 %
```

Les sept autres passent, dont les quatre gates absolus de sûreté — zéro faux,
zéro faux critique, intégrité factuelle et couverture de preuve à 100 %.

Ce que l'échec dit, et ne dit pas :

- **Il ne remet pas en cause le durcissement.** Les six défauts de granularité
  métier de SPEC-009B restent tous hors du feed, et les deux défauts de sujet du
  besoin sont passés `C → B` sous double revue aveugle sans arbitrage.
- **Il révèle un défaut jusqu'ici masqué**, d'une seule et même nature :
  `contract understanding` attribue au lot le CPV du projet parent. Trois lots
  spécialisés — bassin de piscine, centrale photovoltaïque, jardinage — sont
  présentés comme du gros œuvre. Ces trois signaux sont les trois `C`, et deux
  d'entre eux sont les deux `generic`.
- **Il était prévisible et avait été nommé** : c'est la question ouverte n°1 du
  rapport du 2026-08-17. La réadjudication l'a fait passer d'une réserve
  théorique à la cause unique de l'échec.

Une piste existe, non explorée conformément à §0 et §6 : le code **BKP** figure
en clair dans l'objet publié des trois cas suisses (`BKP 272.8`, `BKP 421`), et
c'est une classification de métier canonique, pas un mot-clé libre. Elle
appartiendrait à la couche `contract understanding`. Le superviseur décidera.

**Le durcissement n'est pas committé** (§9). SPEC-009C n'est pas engagée.
