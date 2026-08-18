# SPEC-009D — Recency & Purchase-Channel Observability Audit

`AUDIT ONLY` — aucun moteur modifié, aucun label commercial rejugé, aucun seuil posé.

---

## PRECONDITION

SPEC-009C est acceptée comme EVAL valide et négative : `SPEC-009C NOT DONE`,
64,00 % de précision utile sur 100 signaux frais, 23 des 36 échecs en couche
`matching`.

Cet audit ne relance ni TED ni SIMAP, n'appelle aucun LLM et ne touche aucun
moteur. Il rejoue le pipeline **gelé** sur le corpus **gelé** pour retrouver les
110 SHOW naturels — le banc n'en conservait que 100 — et vérifie que ce rejeu
reproduit exactement le banc :

```text
rejeu du pipeline sur spec009c_corpus.json (2001 award-lots, ICP unique)
→ 110 SHOW                                            = natural_shows du banc  ✔
→ les 100 signal_id du banc sont un sous-ensemble      ✔
→ award/publication/start/end identiques au snapshot   ✔  (100 signaux × 4 dates)
```

Cette égalité est testée (`test_the_replay_reproduces_the_frozen_bench_exactly`)
et le runner s'interrompt si elle tombe : mesurer la fraîcheur sur un pipeline
qui aurait bougé ne mesurerait rien.

Vérification §39 — les quatre répertoires moteurs sont intacts :

```bash
$ git status --porcelain src/signals/understanding src/signals/needs \
                         src/signals/matching src/signals/documents
(vide)
```

---

## FILES CHANGED

```text
src/signals/research/spec009d.py            nouveau   modèle, métriques, garde-fous, tables gelées
src/signals/research/spec009d_run.py        nouveau   exécution hors ligne de l'audit
tests/test_spec009d_audit.py                nouveau   40 tests (§41, §42, précondition)
tests/fixtures/signal100/spec009d_audit.json nouveau  sortie complète de l'audit
docs/reports/2026-08-18-spec009d-…​.md        nouveau   ce rapport
```

Aucun fichier de SPEC-009C n'est modifié (§40).

---

## INPUTS

```text
corpus   spec009c_corpus.json   2001 award-lots   sha256 da91b4a2b70ba631… (identique au gold)
bench    spec009c_bench.json     100 signaux      sha256 d613648823ba631… (identique au gold)
gold     spec009c_gold.json      100 verdicts     sha256 c579a1396cdffbc2…
ICP      icp-construction-inputs-ch-eu-v0
rubric   commercial-signal-rubric-v1
as_of    2026-08-18

engine_versions
  understanding contract-understanding-v0.3   need     need-graph-v0.2
  match_policy  icp-match-v0.2                score    signal-score-v0.2
  bkp_policy    bkp-trade-v0.1                rules    need-rules-v0.5
```

Aucune adjudication commerciale nouvelle. Les 100 verdicts A/B/C/D sont repris
tels quels.

---

# PART A — RECENCY

## AWARD DATE COVERAGE

Sur les 110 SHOW naturels :

```text
award_date connue          89   80,9 %
award_date inconnue        21   19,1 %
```

La moyenne masque une fracture nette par source :

```text
SIMAP    76 SHOW    76 connues    100,0 %
TED      34 SHOW    13 connues     38,2 %      ← 21 des 21 inconnues
```

**La totalité du déficit de fraîcheur observable est sur TED.** SIMAP publie une
date d'attribution sur chaque avis du banc ; TED n'en publie une que sur un tiers
et lui préfère `contract_signature_date` (34 signaux du banc en portent une).
Ces deux dates ne sont pas la même chose et §6 interdit de les confondre : la
signature suit la décision, parfois de plusieurs semaines.

## PUBLICATION DATE COVERAGE

```text
publication_date connue   110   100,0 %
```

C'est la seule date que le moteur consulte. `MatchingEngine._freshness_filter` et
`_freshness_component` calculent tous deux `as_of − published_at` ; `award_date`
n'entre dans aucune décision de matching ni dans aucun point de score.

**Le produit filtre donc sur la date de parution de l'avis, jamais sur la date à
laquelle l'entreprise a gagné.** C'est le constat structurel de cette partie.

## CONTRACT DATE COVERAGE

```text
contract_start_date connue    21   19,1 %
contract_end_date connue      21   19,1 %
contract_signature_date       34   sur le banc de 100
```

Les 21 sont toutes TED. Aucun signal SIMAP du banc ne publie de calendrier
d'exécution.

## AWARD AGE DISTRIBUTION

Sur les 89 SHOW à date d'attribution connue :

```text
0–7 jours        7
8–14            14
15–30           35
31–60           22
61–90            7
91–120           3
>120             1        ← un seul cas, et c'est une donnée fausse (ci-dessous)
unknown         21
```

```text
médiane   26 j        p25   18 j     p75   49 j
p90       63 j        p95   76 j     max   8767 j
```

Le `max` de 8767 jours est le signal `fdaa458200` (SIMAP), dont l'avis publie
`award_date = 2002-08-17` pour une publication du 2026-08-18 — très probablement
`2026-08-17` mal saisi. Il n'est pas dans les 100 adjugés. Corrigé de cette seule
valeur aberrante, la distribution devient :

```text
n = 88   médiane 26 j   p25 15 j   p75 48 j   p90 63 j   p95 70 j   max 99 j
```

Le fait important n'est pas la valeur : c'est qu'**aucun filtre ne l'a arrêtée**.
Le moteur ne lit pas `award_date`, donc une date d'attribution de 2002 traverse le
pipeline sans déclencher quoi que ce soit. Constat posé ; §1 interdit d'y toucher.

Pour mémoire, l'âge de **publication** — celui que le moteur voit réellement :

```text
n = 110   médiane 11 j   p25 0 j   p75 18 j   p90 21 j   p95 24 j   max 25 j
```

Sur cette mesure-là, le feed est irréprochable : aucun avis de plus de 25 jours.

## PUBLICATION DELAY DISTRIBUTION

`publication_date − award_date`, sur les 89 signaux où les deux dates existent :

```text
médiane    8 j       p25   2 j      p75  33 j
p90       47 j       p95  63 j      max  8767 j   (aberrant ; 98 j sans lui)
```

```text
same day     1
1–7 j       43
8–14 j       8
15–30 j     12
31–60 j     20
>60 j        5
unknown     21
```

> Combien de temps après l'attribution l'information devient-elle publiquement
> exploitable par Kivou ?

**La moitié du feed environ arrive en moins de huit jours ; 28 % des signaux datés
mettent plus d'un mois.** La distribution est franchement bimodale : 44 signaux publiés en une
semaine, puis un plateau de 32 signaux entre 15 et 60 jours, puis 5 au-delà.
Il n'y a pas un délai de publication, il y en a deux régimes.

## JUST-WON 7-DAY RESULTS

```text
award_age ≤ 7 j        n = 5      5,0 % des 100 adjugés
                                  6,4 % des 110 SHOW

A 2   B 1   C 1   D 1
useful precision    60,0 %
actionable rate     40,0 %
weak rate           20,0 %
false rate          20,0 %
```

## JUST-WON 14-DAY RESULTS

```text
award_age ≤ 14 j       n = 17    17,0 % des adjugés   19,1 % des SHOW

A 4   B 7   C 5   D 1
useful precision    64,7 %
actionable rate     23,5 %
weak rate           29,4 %
false rate           5,9 %
```

## JUST-WON 30-DAY RESULTS

```text
award_age ≤ 30 j       n = 51    51,0 % des adjugés   50,9 % des SHOW

A 14   B 16   C 18   D 3
useful precision    58,8 %
actionable rate     27,5 %
weak rate           35,3 %
false rate           5,9 %
```

> Les signaux vraiment récents sont-ils commercialement meilleurs que le feed
> global à 64 % ?

**Non.** Aucun des trois seuils ne dépasse le feed global :

```text
feed global (100)        64,0 %
just-won ≤ 7 j            60,0 %      −4,0 pts
just-won ≤ 14 j           64,7 %      +0,7 pt
just-won ≤ 30 j           58,8 %      −5,2 pts
```

Et le gradient est **inversé** :

```text
award_age ≤ 30 j    n = 51    useful 58,8 %    actionable 27,5 %
award_age > 30 j    n = 28    useful 67,9 %    actionable 35,7 %
                              gradient  −9,1 points
```

## RECENCY × COMMERCIAL VERDICT

```text
bucket      n     A    B    C    D    useful    actionable   weak     false
0–7         5     2    1    1    1    60,0 %     40,0 %     20,0 %   20,0 %
8–14       12     2    6    4    0    66,7 %     16,7 %     33,3 %    0,0 %
15–30      34    10    9   13    2    55,9 %     29,4 %     38,2 %    5,9 %
31–60      21     6    7    7    1    61,9 %     28,6 %     33,3 %    4,8 %
61–90       5     2    2    1    0    80,0 %     40,0 %     20,0 %    0,0 %
91–120      2     2    0    0    0    sample too small
>120        0     —
unknown    21     6    9    5    1    71,4 %     28,6 %     23,8 %    4,8 %
```

Aucune monotonie. Le meilleur bucket reportable est `61–90` (80,0 %), le pire est
`15–30` (55,9 %), et les signaux **sans date d'attribution du tout** font 71,4 % —
mieux que toutes les tranches fraîches. Ce dernier chiffre n'est pas un mérite de
l'ignorance : les 21 sans date sont tous TED, et TED fait 73,5 % sur le banc quand
SIMAP fait 59,1 %. La variable qui bouge est la source, pas la fraîcheur.

**La récence n'achète aucune qualité commerciale sur ce banc.**

## RECENTLY PUBLISHED BUT OLD AWARDS

`publication_age ≤ 14 j` **et** `award_age > 60 j` — l'avis vient de paraître,
l'attribution date. Sept cas sur 110 (6,4 %) :

```text
signal_id   src    award_date   publication  delay   award_age   gold
fdaa458200  simap  2002-08-17   2026-08-18    8767      8767     non adjugé   ← date fausse
ec186af38a  simap  2026-05-11   2026-08-07      88        99     non adjugé
9ba633780c  ted    2026-05-12   2026-08-18      98        98     A
f3e563259f  ted    2026-05-12   2026-08-18      98        98     A
73c9b15f0c  simap  2026-06-11   2026-08-04      54        68     non adjugé
7c19bf5ef5  ted    2026-06-16   2026-08-18      63        63     B
92587889f6  simap  2026-06-18   2026-08-04      47        61     C
```

Un seul cas dépasse 120 jours : l'aberration `fdaa458200`.

Ces sept cas sont exactement le risque que porte la promesse « il vient de
gagner » : le moteur les traite comme frais parce que l'avis est frais. Et
pourtant, trois des quatre qui ont été adjugés sont **utiles** (2 A, 1 B, 1 C) —
la vétusté de l'attribution ne les a pas dégradés. Le danger est donc de
*discours*, pas de qualité : Kivou dirait « vient de gagner » d'une entreprise qui
a gagné il y a trois mois.

## CONTRACT ALREADY STARTED / ENDING

Six signaux sur 110 ont un contrat déjà commencé. Tous TED, tous récents :

```text
signal_id   start        depuis   end          gold
82494b4f91  2026-07-27   22 j     2027-02-05   A
1644743753  2026-07-27   22 j     2026-09-16   B
42bd8585c2  2026-07-20   29 j     2027-06-11   C
9c1c8e1018  2026-08-07   11 j     2028-02-29   A
8be5e6b291  2026-08-17    1 j     2026-11-16   B
e9fbc300ec  2026-08-17    1 j     2027-01-29   C
```

```text
démarrés > 30 j    0
démarrés > 60 j    0
```

Deux signaux ont un contrat qui se termine dans les 30 jours :

```text
1644743753   fin 2026-09-16   dans 29 j   gold B
c0f3e5e48c   fin 2026-09-11   dans 24 j   gold C
```

Aucune conclusion négative : sur les six déjà démarrés, 4 sont utiles (67 %), soit
la moyenne du feed. Un démarrage récent n'est pas une fenêtre fermée — c'est même
le moment où les commandes de matériaux se passent. Les deux contrats en fin de
course méritent une lecture différente, mais deux cas ne fondent rien (§24).

## RECENCY VERDICT

```text
RECENCY PARTIALLY OBSERVABLE
```

Justification quantitative :

```text
couverture award_date        80,9 %  (SIMAP 100 %, TED 38,2 %)   → au-dessus du seuil d'illisibilité, sous le seuil de fiabilité
part des SHOW ≤ 30 j         50,9 %                              → la moitié du feed est réellement récente
gradient de qualité ≤30j     −9,1 points                         → la récence n'achète rien
moteur : date utilisée       publication_date, jamais award_date  → la fraîcheur mesurée n'est pas la fraîcheur promise
```

Ce n'est ni `STRONG` — la couverture n'atteint pas 90 % et le gradient est
négatif — ni `NOT RELIABLY OBSERVABLE` — quatre signaux sur cinq portent bien
leur date. C'est une fraîcheur **lisible sur SIMAP, aveugle sur TED, et inutilisée
par le moteur**.

---

# PART B — PURCHASE CHANNEL

## AVAILABLE WINNER FACTS

Couverture sur les 100 adjugés, avec les deux dénominateurs séparés (§19) :

```text
fait                     tous     A+B (64)   C+D (36)
winner_identifiers      100,0 %   100,0 %    100,0 %
winner_address          100,0 %   100,0 %    100,0 %
amount                  100,0 %   100,0 %    100,0 %
award_date               79,0 %    76,6 %     83,3 %
place_of_performance     78,0 %    76,6 %     80,6 %
bkp_codes                47,0 %    43,8 %     52,8 %
lot_title                34,0 %    39,1 %     25,0 %
contract_reference       34,0 %    39,1 %     25,0 %
characteristics          34,0 %    39,1 %     25,0 %
cpv_additional           21,0 %    21,9 %     19,4 %
contract_start_date      21,0 %    21,9 %     19,4 %
contract_end_date        21,0 %    21,9 %     19,4 %
sector                   19,0 %    15,6 %     25,0 %
winner_website            6,0 %     4,7 %      8,3 %
```

Aucun écart de couverture ne dépasse 14 points, et les deux plus grands
(`lot_title`, `contract_reference`, `characteristics` à +14,1 pts) mesurent la
même chose : ces trois champs ne sont peuplés que par TED, et TED fait un peu
mieux que SIMAP. Ce n'est pas une propriété du canal d'achat.

## COMPANY INFORMATION COVERAGE

> Qu'est-ce que Kivou sait actuellement sur l'activité commerciale du gagnant ?

```text
champ                        disponible   couverture   source
legal_name                   oui          100,0 %      winner.parties[].members[].legal_name
country                      oui          100,0 %      …members[].country
address                      oui          100,0 %      …members[].address
identifiers                  oui          100,0 %      …members[].identifiers
website                      oui            6,0 %      …members[].website
legal_form                   NON            0 %        —
industry_code_nace           NON            0 %        —
industry_code_noga           NON            0 %        —
business_activity            NON            0 %        —
company_size                 NON            0 %        —
employee_count               NON            0 %        —
turnover                     NON            0 %        —
manufacturer_status          NON            0 %        —
wholesaler_status            NON            0 %        —
contractor_status            NON            0 %        —
```

Les identifiants portés par les 100 gagnants :

```text
SIMAP-VENDOR-ID    66    clé de fournisseur interne à la plateforme
TED-BT-501         33    identifiant national d'organisation
eu                  1    identifiant européen

aucun n'est une classification d'activité
```

**Un seul champ décrit l'activité du gagnant — son site web — et il est présent
six fois sur cent.** Tout le reste identifie ou localise : cela dit à qui écrire,
jamais ce que l'entreprise achète. C'est le fait central de la partie B.

Le rôle publié (`sole`, `member`) décrit la position dans le groupement, pas le
métier. Aucun signal du banc n'est un consortium : 100 parties, 100 membres
uniques, `is_group = false` partout.

## 23 MATCHING FAILURE STUDY

Motifs commerciaux, repris des adjudications déjà écrites (§25 — aucun signal
n'est rejugé, les 23 restent `C`) :

```text
specialist_contractor            9    le gagnant exerce un métier dont les intrants sont hors catalogue
trade_specific_buyer_channel     6    le gagnant achète chez un grossiste de sa filière (acier, peinture, clôture)
manufacturer                     3    le gagnant produit lui-même l'élément adjugé
deliverable_overlap              3    ce que l'ICP vend EST le livrable du gagnant
integrated_supplier              2    le gagnant fabrique et pose son propre produit
                                ──
                                23
```

Les cinq motifs disent la même chose sous cinq angles : **le corps de métier du
lot classe le marché, il ne modélise pas le canal d'achat du gagnant.**

## FAILURE OBSERVABILITY

> Y avait-il, AVANT la décision de matching, au moins un fait canonique
> disponible permettant raisonnablement de prévoir ce problème ?

La règle appliquée, unique et vérifiable sur le banc :

```text
YES      un code canonique (BKP ou CPV) nomme un métier hors catalogue,
         et sa valeur n'apparaît sur AUCUN signal utile du banc
PARTIAL  un code canonique existe mais sa valeur se retrouve aussi sur des
         signaux utiles : il oriente sans trancher
NO       aucun code ne distingue, ou le code décrit un type de bâtiment,
         ou il nomme un métier DU catalogue alors que le problème tient à
         l'activité du gagnant
```

```text
signal_id   obs       motif                          fait cité      raison
19284980bc  YES       trade_specific_buyer_channel   bkp_codes      BKP 422 Einfriedungen, famille 42 absente de la taxonomie
2f40938a6a  YES       integrated_supplier            cpv_main       CPV 45421151 Kücheneinrichtung, exclusif aux échecs
3e043bd794  YES       trade_specific_buyer_channel   cpv_main       CPV 45262220 forage de puits, filière propre
48b30b9519  YES       manufacturer                   bkp_codes      BKP 277.1 Schiebe-/Faltwände, exclusif
52f5b6f584  YES       specialist_contractor          cpv_main       CPV 45223210 Stahlbau, exclusif
61fe1e4906  YES       manufacturer                   bkp_codes      BKP 228 Sonnenschutz, exclusif
9fe93a3cda  YES       trade_specific_buyer_channel   bkp_codes      BKP 227 + 285 peinture, exclusifs
a7198f4855  YES       trade_specific_buyer_channel   bkp_codes      BKP 285 Malerarbeiten, exclusif
bbf780f7a7  YES       trade_specific_buyer_channel   bkp + cpv      BKP 285.1 et CPV 45442110, tous deux exclusifs
eb947063b5  YES       trade_specific_buyer_channel   bkp_codes      BKP 285.1, exclusif

1bca9c53f9  PARTIAL   specialist_contractor          cpv_main       CPV 45221119 porte aussi un signal utile
1c3ca2d297  PARTIAL   specialist_contractor          bkp_codes      BKP 272 Metallbau présent sur 2 signaux utiles
42bd8585c2  PARTIAL   specialist_contractor          cpv_main       CPV 45262670 : 2 échecs, 2 signaux utiles
82a8af8318  PARTIAL   specialist_contractor          bkp_codes      BKP 272.2, racine partagée avec 1 signal utile
8dd986660b  PARTIAL   manufacturer                   bkp_codes      BKP 215 partagé avec 1 signal utile
b45adc669b  PARTIAL   specialist_contractor          cpv_main       CPV 45262670, même partage

65195148b6  NO        integrated_supplier            cpv_main       CPV 45421130 nomme la menuiserie — DANS le catalogue
7550a394b4  NO        deliverable_overlap            bkp_codes      BKP 273 porte 4 signaux utiles
780564b171  NO        deliverable_overlap            bkp + cpv      BKP 273.0 et CPV 45213331 partagés
783db7c9dd  NO        deliverable_overlap            bkp_codes      BKP 221.5 partagé ; la réserve de crédit est en texte libre
92587889f6  NO        specialist_contractor          bkp + cpv      « CFC 242 Chauffage » non extrait ; CPV = type de bâtiment
974a67e479  NO        specialist_contractor          bkp + cpv      « 275.00 Schliessanlagen » sans marqueur ; CPV = type de bâtiment
b671961171  NO        specialist_contractor          cpv_main       CPV 45214610 = type de bâtiment ; l'électricité n'est qu'au titre
```

### OBSERVABILITY RATE

```text
fully observable      10 / 23     43,5 %
partially observable   6 / 23     26,1 %
not observable         7 / 23     30,4 %
                      ────────
                      23 / 23    100,0 %
```

**Moins d'un échec sur deux était prévisible depuis un fait canonique.** Et cette
mesure est optimiste par construction : « exclusif aux échecs » est établi sur un
banc de 100 signaux, où un code vu deux fois du même côté peut l'être par hasard.
Sur un feed réel, la part `YES` ne peut que baisser.

Deux causes de `NO` méritent d'être nommées séparément :

- **Le recouvrement de livrable est structurellement invisible** (3 cas + 2
  `integrated_supplier`). BKP 273 « Nebenraumtüren » désigne de la menuiserie, et
  la menuiserie *est* au catalogue de l'ICP. Le code est correct, le catalogue est
  correct, et le rapprochement est faux — parce que le gagnant *fabrique* ce que
  l'ICP vend. Aucun code de lot ne peut porter cette information : elle décrit
  l'entreprise, pas le marché.
- **Un marqueur d'extraction manque** (1 cas sur les 23, 2 sur les 100).
  `bkp.py` ne reconnaît que le marqueur littéral `BKP` ; « CFC », son équivalent
  romand, laisse le code non extrait. Constat posé, non corrigé (§1).

## A+B CONTROL SAMPLE

Témoin déterministe de 23 signaux `A`/`B`, apparié strate par strate aux
(source × trade_domain) des 23 échecs, dans l'ordre des `signal_id` (§28) :

```text
                          échecs (23)     témoin A+B (23)
source simap / ted           17 / 6           17 / 6      apparié par construction
trade general / interior     13 / 10          13 / 10     apparié par construction
bkp_codes présent            13 (56,5 %)      12 (52,2 %)      Δ  +4,3 pts
cpv « métier » (non générique) 12 (52,2 %)    17 (73,9 %)      Δ −21,7 pts
winner_website connu          1 ( 4,3 %)       0 ( 0,0 %)      Δ  +4,3 pts
```

> Quels faits canoniques permettent de distinguer ces vrais signaux des 23
> échecs de matching ?

**Aucun, de façon exploitable.** Le seul écart notable — 21,7 points sur la
spécificité du CPV — va dans le sens attendu mais n'est pas un critère : 12 des 23
échecs portent un CPV « métier », et 6 des 23 signaux utiles portent un CPV
générique. La règle « exiger un CPV métier » couperait la moitié des échecs *et*
un quart des bons signaux, sur des effectifs de 23 (`indicative only`, §24).

## MATCHABILITY MATRIX

`décrit le canal` = le fait pourrait en principe informer une filière d'achat, par
opposition à un proxy de taille, de plateforme ou de géographie.
`écart` = amplitude de précision utile entre les valeurs d'effectif ≥ 10.

```text
fait                   dispo avant   décrit le    couverture   écart      candidat
                       matching      canal                     (points)   futur
amount                 oui           NON          100,0 %       38,0        NO
source                 oui           NON          100,0 %       14,4        NO
lot_title              oui           oui           34,0 %       14,4        NO
need_categories        oui           oui          100,0 %       13,1        NO
award_date             oui           NON           79,0 %        9,4        NO
bkp_codes              oui           oui           47,0 %        8,3        NO
trade_domain_source    oui           oui          100,0 %        8,3        NO
currency               oui           NON          100,0 %        5,4        NO
place_of_performance   oui           NON           78,0 %        5,4        NO
trade_domain           oui           oui          100,0 %        4,4        NO
winner_country         oui           NON          100,0 %        2,2        NO
cpv_main               oui           oui          100,0 %        0,6        NO
contract_type          oui           NON          100,0 %       constant   UNKNOWN
winner_website         oui           oui            6,0 %      n < 10       UNKNOWN
```

**Aucune ligne ne vaut `YES`.** La seule variable qui sépare franchement le banc
est le montant du lot — 43,8 % d'utilité sous 250 kCHF contre 81,8 % entre 1 et
5 MCHF — et c'est un proxy de taille de chantier, sans rapport avec la filière
d'achat. La retenir reviendrait à vendre du hasard sous un nom sérieux ; le code
le refuse explicitement (`matchability_candidate`).

Les deux variables qui *décrivent* réellement un métier — `bkp_codes` et
`cpv_main` — sont les moins discriminantes du tableau : 8,3 et 0,6 point. Le
paradoxe de SPEC-009C s'y lit directement : la présence d'un BKP est associée à
*moins* d'utilité (59,6 % contre 67,9 %), parce que le BKP apparaît sur les lots
suisses finement découpés, où le gagnant est précisément un spécialiste.

## MISSING INFORMATION

Chaque donnée absente est chiffrée contre les 23 échecs observés (§32) :

```text
donnée manquante                                valeur    couvre   provenance
manufacturer / distributor / installer status   HIGH      23/23    EXTERNAL COMPANY ENRICHMENT
winner_business_description                     HIGH      23/23    EXTERNAL COMPANY ENRICHMENT
winner_industry_classification (NACE/NOGA)      HIGH      20/23    EXTERNAL COMPANY ENRICHMENT
bkp_trade_semantics à trois chiffres            HIGH      13/23    canonical award data
winner_website                                  MEDIUM    23/23    EXTERNAL COMPANY ENRICHMENT
reconnaissance du marqueur « CFC »              MEDIUM     1/23    SIMAP
winner_legal_form                               LOW        0/23    EXTERNAL COMPANY ENRICHMENT
winner_size_and_turnover                        LOW        0/23    EXTERNAL COMPANY ENRICHMENT
```

`bkp_trade_semantics` mérite d'être lu à part : **le code est déjà publié et déjà
stocké**. `bkp_codes` contient bien « 285 », « 272.2 », « 277.1 ». Ce qui manque
n'est pas la donnée mais sa signification : la table `BKP_TRADE_RULES` ne mappe
que les familles à deux chiffres (21, 22, 27, 28). C'est le seul gisement
disponible **sans source externe** — mais il plafonne à 13 des 23 cas, et ne
touche aucun des trois recouvrements de livrable.

## EXTERNAL ENRICHMENT GAP

```text
déjà présent dans TED / SIMAP / canonical award data
    bkp_codes à trois chiffres (47 % de couverture)          → sémantique manquante
    marqueur CFC (2 cas sur 100)                             → extracteur manquant

nécessite EXTERNAL COMPANY ENRICHMENT
    statut fabricant / distributeur / installateur           ← la variable exacte
    description d'activité du gagnant
    classification NACE / NOGA
    site web du gagnant (6 % aujourd'hui)
```

La frontière est nette : **les données de marché sont épuisées, les données
d'entreprise n'ont jamais été collectées.** Aucune recherche externe n'est
engagée dans cette SPEC (§33).

## PURCHASE CHANNEL VERDICT

```text
PURCHASE CHANNEL NOT OBSERVABLE WITH CURRENT DATA
```

Justification quantitative :

```text
champs décrivant l'activité du gagnant       1 sur 15    (site web, 6 % de couverture)
échecs pleinement prévisibles               43,5 %       (10 / 23)
échecs non prévisibles                      30,4 %       ( 7 / 23)
meilleur fait « canal » du banc              8,3 points  d'écart de précision utile
faits candidats pour la suite                0 sur 14
```

---

# FINAL

## DECISION MATRIX

```text
RECENCY PARTIALLY OBSERVABLE   ×   PURCHASE CHANNEL NOT OBSERVABLE WITH CURRENT DATA
```

```text
                            canal observable          canal non observable
recency strong              A  correction             B  enrichissement externe
                               déterministe              ou signal plus étroit
recency non strong          C  correction               D  repenser la promesse
                               source / timing             ← ICI
```

→ **Scénario D.** Seul `RECENCY STRONG` compte comme fraîcheur démontrée : une
fraîcheur partiellement observable documente une incertitude, elle ne soutient pas
une promesse produit.

## PRODUCT IMPLICATION

Trois conclusions, dans l'ordre de gravité.

**1. La promesse temporelle n'est pas celle que le produit tient.** Kivou dit
« vient de gagner » et filtre sur « vient d'être publié ». Sur SIMAP l'écart est
tolérable — médiane 8 jours — mais 28 % des signaux datés ont plus d'un mois d'écart
entre décision et parution, et sept signaux sur 110 sont publiés frais sur une
attribution de plus de deux mois. Sur TED, l'écart n'est même pas mesurable :
62 % des avis ne publient pas de date d'attribution.

**2. La récence n'est pas le levier de qualité.** C'est le résultat le plus net de
la partie A, et il est contre-intuitif : les signaux de moins de 30 jours font
58,8 % d'utilité contre 67,9 % pour les plus anciens. Resserrer la fenêtre
temporelle dégraderait le feed. Le problème de SPEC-009C n'était pas un problème
de timing, et cet audit l'écarte définitivement.

**3. Le canal d'achat n'est pas dans les données.** C'est une propriété du
**gagnant**, et Kivou ne possède du gagnant qu'un nom, une adresse et une clé de
plateforme. Les codes du **marché** — BKP, CPV, corps de métier — décrivent ce qui
est acheté par l'acheteur public, pas ce qui sera racheté par l'attributaire.
Aucune quantité de finesse taxonomique ne comble cet écart : dans 7 cas sur 23, le
code est juste, le catalogue est juste, et le rapprochement est faux.

La limite de cet audit doit être dite : les 23 cas sont un banc de 23 cas, les
tailles d'échantillon par variable vont de 2 à 100, et un seul ICP a été testé.
Ces chiffres établissent que le canal d'achat n'est pas observable **ici**, pas
qu'il serait inobservable pour tout wedge.

## RECOMMENDED NEXT STEP

```text
rethink MVP signal promise
```

C'est la seule étape que §47 autorise pour le scénario D, et elle n'est pas
engagée. Les deux directions que l'audit rend chiffrables, pour la décision du
superviseur :

- **Enrichissement externe du gagnant.** La variable manquante est nommée et
  couvre 23/23 : statut fabricant / distributeur / installateur. Elle exige une
  source d'entreprise que Kivou n'a jamais interrogée.
- **Promesse plus étroite.** Renoncer à prédire ce que le gagnant achètera, et
  vendre ce que les données portent réellement — un événement d'attribution
  qualifié, daté, tracé, laissé au jugement commercial de l'utilisateur.

Aucune des deux n'est commencée (§48, STOP).

## VPS PORTABILITY

```text
hors ligne          oui   zéro appel réseau ; corpus, banc et gold relus sur disque
Python seul         oui   stdlib + pydantic déjà présent ; aucune dépendance ajoutée
pas de base         oui   entrées et sortie en JSON
pas de réseau       oui   aucun client HTTP importé
chemins relatifs    oui   `workdir()`, surchargeable par variable d'environnement
mémoire bornée      oui   pic mesuré 195 Mo ; audit complet en 2,1 s
compatible Linux    oui   aucune primitive spécifique à une plateforme
```

Portable local → VPS actuel → VPS dédié futur, sans modification.

## TEST RESULTS

```bash
$ uv run pytest -q
1771 passed in 16.38s          # 1731 avant SPEC-009D + 40 nouveaux

$ uv run ruff check .
All checks passed!

$ git diff --check
(rien)

$ uv run ruff format --check .
1 file would be reformatted
  docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md
```

Le défaut Markdown est le défaut historique connu, antérieur à SPEC-009D et
rapporté séparément (§44). Les trois fichiers Python de cette SPEC sont formatés.

Les 40 tests couvrent §41 (bucket 0-7 / 15-30 / 61-90, award manquante, événement
périmé détecté, délai de publication, contrat en fin de course, **aucune
substitution de `publication_date` à `award_date`**) et §42 (seuls les faits
canoniques pré-matching acceptés, nom du gagnant refusé, verdict gold refusé,
motivation de reviewer refusée, dénominateurs de couverture, somme YES/PARTIAL/NO),
plus la précondition de rejeu.

## VERDICT

```text
RECENCY + CHANNEL NOT OBSERVABLE
```

```text
PART A    RECENCY PARTIALLY OBSERVABLE
          award_date connue 80,9 % — mais 38,2 % seulement sur TED
          le moteur filtre sur publication_date, jamais sur award_date
          délai de publication médian 8 j, p75 33 j, p95 63 j
          just-won ≤ 7 j : 60,0 % · ≤ 14 j : 64,7 % · ≤ 30 j : 58,8 %  vs 64,0 % global
          gradient de qualité : −9,1 points

PART B    PURCHASE CHANNEL NOT OBSERVABLE WITH CURRENT DATA
          1 champ d'activité du gagnant sur 15, couvert à 6 %
          10/23 échecs prévisibles · 6/23 partiellement · 7/23 pas du tout
          0 fait candidat sur 14 dans la matrice de matchabilité
          témoin A+B indiscernable des 23 échecs sur les faits canoniques

DÉCISION  scénario D → rethink MVP signal promise
```

Rien n'est commencé. En attente de la décision du superviseur.
