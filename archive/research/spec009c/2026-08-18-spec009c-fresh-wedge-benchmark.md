# SPEC-009C — Fresh Construction Inputs Wedge Benchmark

**Date** : 2026-08-18 · **Branche** : `main` · **Verdict** : `SPEC-009C NOT DONE`

Première évaluation du **feed client complet** de Kivou : un client, un ICP, un
feed, sur des marchés jamais utilisés en développement. Aucun réglage n'a été
fait, aucun LLM n'entre dans le pipeline, et rien n'est committé hormis le
durcissement préalable.

---

## HARDENING COMMIT

```text
hash     b881dad50e811e4a7eae8d75819afd7ac56a62bb
message  feat(wedge): harden construction inputs matching
branch   main (non poussée)
fichiers 30 · 15 247 insertions
```

Il regroupe R1 et R2 : `TradeDomain` et table CPV, Need Graph et appariement
sensibles au métier, garde d'objet publié, parser et table BKP, les 67 tests de
régression R1+R2, les golds d'évaluation, et les trois rapports nécessaires à la
reproductibilité.

Exclus délibérément : les deux `.docx` de planification, les fichiers
`Zone.Identifier`, et le post-mortem SPEC-006 sans rapport. Aucun secret, aucun
chemin absolu, aucune dépendance ajoutée. Arbre suivi propre après commit.

---

## PRECONDITION

```text
uv run pytest -q     1707 passed
uv run ruff check .  All checks passed!
git diff --check     propre
```

---

## ENGINE VERSION SET

```text
contract-understanding-v0.3
need-graph-v0.2
need-rules-v0.5
icp-match-v0.2
signal-score-v0.2
bkp-trade-v0.1
reference-icps-v0.1
```

Gelées pendant toute la durée du banc. `AUTO_DOCUMENT_REQUIREMENTS_ENABLED`
reste `False` : tous les signaux sont en `metadata_fallback`, aucun document de
marché n'a été lu.

---

## ICP DEFINITION

```text
icp-construction-inputs-ch-eu-v0
besoin primaire      materials_or_components
besoin secondaire    equipment_or_rental
type de contrat      construction
métiers primaires    general_building · interior_finishing · earthworks_demolition
métiers secondaires  roadworks_civil · special_civil
territoires          CH · DE · FR · ES · PT   (lieu d'exécution REQUIS)
seuils               CHF 100 000 · EUR 100 000
âge maximal          120 jours
SHA256 sérialisé     17776638e6beeaeb2590e205d02e2eb38e5f3ed35ea4e2a3a46346cc95d432d1
```

---

## FRESH ACQUISITION

```text
acquisition_from   2026-04-20   (SIMAP `since` · TED fenêtre de 120 jours)
acquisition_to     2026-08-18
as_of              2026-08-18
award-lots         2001   —  TED 1201 · SIMAP 800
connecteurs        ceux de production, inchangés
```

**Ce que « frais » veut dire ici, précisément.** Le pool de développement couvre
2026-07-10 → 2026-08-17 et le run a lieu le 18 : il n'existe pas de fenêtre
postérieure exploitable. La fenêtre interrogée est donc celle des 120 jours —
exactement l'intervalle où cet ICP accepterait un signal, et pas un élargissement
destiné à gonfler le volume. Tout ce qui a servi au développement en est retiré
identité par identité, aux quatre niveaux. Les 2001 award-lots retenus n'ont
jamais été vus par aucune SPEC.

Acquisition en deux temps, conformément à §10 : 1000 lots d'abord (56 SHOW
naturels, sous la cible de 100), puis extension à 2001 (110 SHOW). Le plafond de
3000 n'a pas été atteint. Neuf pauses de débit TED absorbées, aucun échec.

---

## DISJOINTNESS

```text
niveau              SPEC-009C   antérieur   intersection
publication              1728         934              0
notice                   1728         934              0
procedure                1704         932              0
award identity           1980        1078              0
```

Confronté à : SPEC-005/007 DEV, SPEC-007 DEV, SPEC-007 held-out, SPEC-007 final,
SPEC-008 final, **et le pool SPEC-009** — dont SPEC-009, 009A, 009B, R1 et R2 ont
tous tiré. `prior_identities()` ne le couvrait pas ; il a fallu l'ajouter
explicitement, sans quoi la disjonction aurait été un trompe-l'œil.

Les deux côtés sont non vides à chaque niveau. Un test le vérifie.

---

## NATURAL FUNNEL

```text
2001 award-lots frais, confrontés au SEUL ICP du wedge

show                  110
borderline             41
exclude              1295
insufficient_data     555
                    ─────
                     2001

dont marchés de travaux : 478
```

`insufficient_data` domine à 27,7 % : ce sont les award-lots sans lieu
d'exécution publié, que la politique `required` rend inévaluables plutôt que de
les rapprocher à tort.

---

## SIGNAL DENSITY

```text
SHOW pour 100 award-lots                  5,50
SHOW pour 100 marchés de travaux         23,01
```

Densité stable entre les deux tirages — 5,6 sur les 1000 premiers, 5,5 sur les
2001. Elle est **observée**, non extrapolée : aucune projection mensuelle ou
annuelle n'est produite (§39).

```text
SHOW par source     SIMAP 66 · TED 34   (sur le banc de 100)
SHOW par pays       CH 70 · DE 22 · FR 6 · ES 2
```

Le feed est très majoritairement suisse alors que le corpus est majoritairement
TED : SIMAP publie proportionnellement bien plus de lots de travaux exploitables.

---

## BENCHMARK COMPOSITION

```text
banc                100 signaux, tirés des 110 SHOW naturels
notices distinctes   98        (jamais plus de 2 lots par notice)
zones de score       top 33 · milieu 33 · bas 34
bande                strong ×100
source               SIMAP 66 · TED 34
pays                 CH 70 · DE 22 · FR 6 · ES 2
corps de métier      general_building 61 · interior_finishing 39
tranche de montant   250 k–1 M 58 · 1–5 M 22 · < 250 k 16 · > 5 M 4
métier issu du BKP   47      métier issu du CPV   53
```

Le BKP n'a pas été sur-échantillonné (§14) : sa part de 47 % est celle du flux
réel.

---

## CORPUS SHA256

```text
da91b4a2b70ba4bb97438dca0744d01007f7f845f4066c494a2f5d38e86dc951
```

---

## COMMERCIAL RUBRIC

`commercial-signal-rubric-v1`, utilisée sans aucune modification. Aucune
définition n'a bougé après le début de l'adjudication.

Vue aveugle : score, bande, décision, `rule_ids`, diagnostic de conflit BKP/CPV,
état du trade-match, gold et verdict attendu en sont absents — un test le
vérifie champ par champ.

---

## REVIEWER AGREEMENT

```text
Reviewer A — B2B Sales Director              A=40 B=31 C=24 D=5
Reviewer B — Procurement / Contract Analyst  A=33 B=39 C=20 D=8

accord exact                 69/100 =  69,0 %
accord à un grade           100/100 = 100,0 %     (gate >= 90 %  → PASS)
arbitrages                        8
distances observées          0 → 69 cas · 1 → 31 cas · jamais 2 ni 3
```

200 revues, **zéro incohérence de rubrique** au contrôle automatique. Les deux
perspectives ne divergent jamais de plus d'un grade : la doctrine commerciale est
stable, et l'échec qui suit n'est pas un artefact de rubrique.

Les huit arbitrages ont été rendus en aveugle, sans connaissance des verdicts
précédents, par deux arbitres distincts. Aucun appel OpenRouter ni DeepSeek.

---

## GOLD SHA256

```text
c579a1396cdffbc24d57c564172f77f8f2d600a8f6d65c7e5363c2079fdbf50b
```

Corpus, gold et ICP sont immuables depuis ce gel. Les gates n'ont été calculés
qu'après (§21).

---

## FINAL VERDICTS

```text
A    30
B    34
C    31
D     5
   ────
    100
```

Dimensions, sur les 100 :

```text
factual_integrity   pass 99 · critical_failure 1
need                credible 74 · plausible_but_weak 22 · contradicted 3 · unsupported 1
icp_fit             strong_fit 45 · weak_fit 32 · plausible_fit 21 · no_fit 2
actionability       worth_investigating 40 · actionable 30 · too_weak 26 · misleading 4
```

---

## USEFUL PRECISION

```text
(A+B) / 100  =  64,00 %          gate >= 90 %   ÉCHEC
```

---

## ACTIONABLE RATE

```text
A / 100  =  30,00 %              gate >= 15 %   PASS
```

C'est le seul indicateur de qualité qui passe largement, et il est instructif :
quand le wedge touche juste, il touche vraiment juste. Trente signaux sur cent
donnent déjà une raison claire et spécifique de prospecter.

---

## SAFETY GATES

| gate | exigé | mesuré | |
|---|---|---|---|
| C weak rate | ≤ 10 % | **31,00 %** | **ÉCHEC** |
| D false / misleading | ≤ 2 % | **5,00 %** | **ÉCHEC** |
| critical false signals | 0 | **5** | **ÉCHEC** |
| factual integrity | ≥ 99 % | **99,00 %** | PASS |
| proof coverage | 100 % | **100,00 %** | PASS |
| critical overclaiming | 0 | **0** | PASS |
| timing errors | 0 | **0** | PASS |
| generic signal rate | ≤ 5 % | **7,00 %** | **ÉCHEC** |
| trade mismatch false shows | 0 | **0** | PASS |

Les garde-fous de **véracité** tiennent : les faits publiés sont exacts à 99 %,
chaque fait affiché reste traçable à sa source, et aucune hypothèse n'est
présentée comme une certitude d'achat. Ce qui échoue n'est pas l'honnêteté du
signal, c'est sa **pertinence commerciale**.

---

## TOP QUALITY

```text
TOP20 (scores 93 à 98)      A=9  B=7  C=4  D=0
TOP20 useful precision      80,00 %      gate >= 95 %   ÉCHEC
TOP20 critical false             0       gate = 0       PASS
```

Aucun faux critique n'atteint la tête du feed — mais un signal sur cinq y est
déjà trop faible. Le score ne sépare pas assez : voir la section suivante.

---

## BOTTOM THIRD

```text
BOTTOM33 (score 87, uniforme)   A=6  B=11  C=15  D=1
useful precision                51,52 %     seuil indicatif >= 80 %
```

**Le score est plat.** Le tiers inférieur est entièrement à 87 points et le
sommet plafonne à 98 : toute la population tient dans onze points. Le classement
qui en résulte n'ordonne presque rien, ce qui explique qu'un banc stratifié par
terciles produise trois zones de qualité voisines. Diagnostic seulement — §30
interdit d'y toucher ici.

---

## SOURCE RESULTS

```text
source   n     A    B    C    D    utile      actionnable   faux critiques
SIMAP    66   17   22   23    4    59,09 %       25,76 %          4
TED      34   13   12    8    1    73,53 %       38,24 %          1
```

Les deux sources dépassent le seuil de 20 signaux, donc les deux sont gatées à
85 % : **les deux échouent**. TED fait nettement mieux que SIMAP sur les deux
axes, mais reste 11,5 points sous la barre. L'échec n'est donc pas propre à une
source.

---

## COUNTRY RESULTS

```text
pays   n     A    B    C    D    utile
CH    70    17   26   23    4    61,43 %
DE    22    10    4    7    1    63,64 %
FR     6     2    3    1    0    83,33 %
ES     2     1    1    0    0    — (n < 5, non publié)
PT     0     —    —    —    —    aucun signal naturel
```

Le Portugal ne produit **aucun** SHOW sur 2001 award-lots frais, et l'Espagne
deux. Ces deux territoires figurent dans l'ICP parce qu'ils apparaissaient dans
l'empreinte du wedge SPEC-009B, pas parce qu'un volume les y justifie.

---

## TRADE DOMAIN RESULTS

```text
domaine                n     A    B    C    D    utile
general_building      61    19   19   19    4    62,30 %
interior_finishing    39    11   15   12    1    66,67 %
earthworks_demolition  0     —    —    —    —    aucun signal naturel
```

**Aucun métier secondaire n'atteint le feed** — `roadworks_civil` et
`special_civil` restent en `borderline`, exactement comme §33 l'attendait. La
porte métier fonctionne comme spécifiée.

Mais les deux domaines primaires qui produisent du volume échouent tous les deux,
et à un niveau voisin : le problème n'est pas *quel* domaine, c'est la
granularité même de la notion.

---

## BKP RESULTS

```text
                        n     utile     A    B    C    D
avec BKP reconnu       47    59,57 %   11   17   17    2
sans BKP               53    67,92 %   19   17   14    3
métier décidé par BKP  47    59,57 %
métier décidé par CPV  53    67,92 %
```

**Résultat contre-intuitif, à rapporter tel quel.** Sur données fraîches, les
signaux dont le métier vient du BKP sont *moins* utiles de 8,3 points que ceux
classés au CPV. R2 avait mesuré l'inverse sur son sous-échantillon de 23.

L'explication tient à ce que le BKP fait bien son travail : il descend au lot, et
les lots BKP sont des lots de **spécialité** — serrurerie, menuiserie, parois
mobiles, échafaudage. Le classer correctement en `interior_finishing` ou
`general_building` ne rend pas son titulaire client d'un négoce généraliste. Le
BKP a corrigé une erreur de classification ; il a rendu visible une erreur de
ciblage qu'il ne pouvait pas corriger.

Diagnostic seulement : §34 interdit d'en faire un gate.

---

## FAILURE ATTRIBUTION

36 signaux `C` ou `D`, chacun rattaché à une seule couche primaire.

```text
matching                23     (23 C · 0 D)
contract understanding   6     ( 4 C · 2 D)
need graph               5     ( 3 C · 2 D)
source data              1     ( 0 C · 1 D)
ICP configuration        1     ( 1 C · 0 D)
```

### La concentration : 23 échecs sur 36 en couche `matching`

Un motif unique, répété, et parfaitement lisible dans les motifs d'adjudication :
**le gagnant est un spécialiste dont la filière d'achat n'est pas celle d'un
négoce.** Dimensions de ces 23 cas : `icp_fit` faible ou seulement plausible dans
la totalité, `actionability` = `too_weak` dans la quasi-totalité.

```text
19284980bc  spécialiste de la clôture — 478 m de grillage, portails, motorisations
1c3ca2d297  serrurerie-métallerie — profilés acier galvanisés et thermolaqués
42bd8585c2  serrurier-métallier — portes acier, garde-corps, encagement de toiture
52f5b6f584  construction métallique — 39 balcons acier, 9800 kg d'ossature
48b30b9519  fabricant de parois mobiles, produites en usine
2f40938a6a  technique de grande cuisine
3e043bd794  forage de cinq puits — tubage inox, gravier filtrant certifié
1bca9c53f9  ouvrages d'art autoroutiers — joints de chaussée, renfort carbone
… et quinze autres du même type
```

Le mot « nominal » revient six fois sous la plume des adjudicateurs, « fabricant »
trois fois, « spécialisé » six fois. Le métier concorde au niveau de la
**catégorie**, jamais au niveau du **canal d'achat**.

### Les cinq faux signaux critiques

```text
3c35bb7ed5  simap CH  interior_finishing   source data
            montant affiché en EUR pour un marché de la Ville de Bienne — devise fausse
232b29d894  ted   DE  general_building     contract understanding
            automatisme du bâtiment (vannes, compteurs, armoires) classé en travaux
8e4ed5eb55  simap CH  general_building     contract understanding
            mandat d'ingénieur civil SIA 31-53 classé en travaux de construction
9542df9356  simap CH  general_building     need graph
            lot d'échafaudage BKP 226.0 remporté par un échafaudeur
a0c9e9eb47  simap CH  general_building     need graph
            CPV 45262100 « montage et démontage d'échafaudages », gagné par un échafaudeur
```

Les deux derniers sont le piège nommé par la rubrique : **le livrable du contrat
pris pour un besoin aval**. Un échafaudeur ne « aura pas besoin » d'échafaudages.
`DELIVERABLE_OVERLAP` couvre ce cas pour `transport_logistics`,
`equipment_supply` et `medical_supply`, mais pas pour un lot de travaux dont le
livrable *est* la prestation dérivée.

### Nature de l'échec

```text
précision              OUI  — c'est l'échec principal, 64 % contre 90 % exigés
volume                 NON  — 110 SHOW naturels, au-dessus du plancher de 50
timing                 NON  — zéro erreur de timing
classification métier  OUI  — mais par insuffisance de granularité, pas par erreur
need graph             PARTIEL — 5 cas sur 36, dont les deux échafaudages
territoire             NON  — aucun signal hors zone ; PT et ES sont vides, pas faux
spécifique à une source NON — SIMAP 59 % et TED 74 %, les deux sous la barre
```

---

## SPEC-006/007/008/009 NON-REGRESSION

```text
SPEC-006  AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False. Intouché.
          Le vérificateur commercial reste expérimental et isolé ; un test vérifie
          qu'aucune de ses traces n'apparaît dans le banc.
SPEC-007  need-graph-v0.2 / need-rules-v0.5 inchangés. Gold `need_final` intact.
SPEC-008  icp-match-v0.2 inchangé. Bibliothèque des sept ICPs et son SHA intacts.
SPEC-009  corpus et gold byte-identiques ; le sceau épingle toujours
          contract-understanding-v0.1. Aucun ancien SHA ne bouge.
R1 / R2   106 tests de durcissement et d'intégrité ciblés, tous verts.
```

Aucun moteur n'a été modifié pendant SPEC-009C (§4).

---

## VPS PORTABILITY

```text
Python pur, déterministe                    oui
chemins relatifs                            oui (`workdir()` configurable)
mémoire et disque bornés                    corpus 3,9 Mo, banc 1,3 Mo
base de données                             aucune
service cloud managé                        aucun
dépendance Windows                          aucune
réseau à l'exécution des tests              aucun
LLM dans le pipeline                        aucun
dépendances ajoutées                        aucune
```

Le seul accès réseau est l'acquisition, par les connecteurs de production
existants. Le banc se rejoue entièrement hors ligne depuis les fixtures gelées.

---

## TEST RESULTS

```text
uv run pytest -q          1731 passed in 14,88s     (1707 avant, +24)
uv run ruff check .       All checks passed!
git diff --check          propre
uv run ruff format --check .
                          1 file would be reformatted
```

Défaut de formatage **historique et connu**, rapporté séparément :
`docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md`,
committé en `d173265`, dont ruff reformate les blocs de code Python. Hors
périmètre, non touché. `ruff format --check src tests` passe sans réserve.

Aucun test n'accède au réseau.

---

## OPEN QUESTIONS

1. **Le corps de métier ne modélise pas le canal d'achat.** C'est la cause des
   deux tiers des échecs. Savoir qu'un lot est du `general_building` ne dit pas
   si son titulaire s'approvisionne chez un négoce ou chez un sidérurgiste. La
   question est de savoir si cette information existe dans les données publiques
   — probablement pas au niveau du seul avis d'attribution.

2. **Le livrable pris pour un besoin, sur les marchés de travaux.**
   `DELIVERABLE_OVERLAP` protège trois types de contrat mais pas un lot de
   travaux dont l'objet est la prestation même qu'on lui dérive. Deux des cinq
   faux critiques viennent de là, et ce sont les deux plus faciles à corriger.

3. **Le score est plat.** Onze points séparent le meilleur signal du moins bon.
   Un feed ordonné par ce score n'est pas ordonné. Cela n'a pas coûté de gate
   ici, mais rend le TOP20 peu significatif.

4. **PT ne produit rien, ES presque rien.** Deux territoires de l'ICP sont vides
   sur 2001 award-lots frais. Ils viennent de l'empreinte SPEC-009B, pas d'un
   volume observé.

5. **Une devise fausse a été affichée.** Un marché de la Ville de Bienne présenté
   en EUR. Un seul cas, mais c'est la seule atteinte à l'intégrité factuelle du
   banc, et elle relève de la couche `source data`.

6. **La fenêtre fraîche est adjacente au développement, pas postérieure.** Les
   identités sont rigoureusement disjointes, mais la période se recoupe. Un banc
   véritablement postérieur demanderait d'attendre plusieurs semaines.

---

# VERDICT

```text
SPEC-009C NOT DONE
```

### Gates en échec

```text
useful precision            64,00 %   <  90 %
C weak rate                 31,00 %   >  10 %
D false / misleading         5,00 %   >   2 %
critical false signals            5   >   0
generic signal rate          7,00 %   >   5 %
TOP20 useful precision      80,00 %   <  95 %
SOURCE useful precision     SIMAP 59,09 % · TED 73,53 %   <  85 %
```

### Gates franchis

```text
natural SHOW volume              110   >=  50
actionable rate              30,00 %   >=  15 %
factual integrity            99,00 %   >=  99 %
proof coverage              100,00 %    = 100 %
critical overclaiming              0    =   0
timing errors                      0    =   0
trade mismatch false shows         0    =   0
TOP20 critical false               0    =   0
rubric agreement 1-grade    100,00 %   >=  90 %
```

### Ce que ce résultat établit

Le durcissement R1+R2 mesurait **95,65 %** sur 23 signaux issus du pool de
développement. Sur 100 signaux frais et jamais vus, le même moteur mesure
**64,00 %**. L'écart n'est pas une régression : c'est ce que coûte le passage
d'un sous-échantillon adjugé à un feed client réel. Les corrections R1 et R2
étaient justes et le restent — elles ont simplement été calibrées sur une
population trop étroite pour révéler le défaut dominant.

Ce défaut est unique, nommé et concentré : **le corps de métier classe le
marché, il ne modélise pas le canal d'achat du gagnant.** Vingt-trois des
trente-six échecs en viennent, et la classification BKP — qui fonctionne
correctement — le rend plus visible plutôt que moins.

Ce que le banc valide, en revanche, tient : les faits sont exacts, les preuves
complètes, aucune intention d'achat n'est jamais affirmée, la porte métier écarte
bien les domaines secondaires, la rubrique est stable à 100 % d'accord à un
grade, et la densité commerciale — 5,5 SHOW pour 100 award-lots — est réelle et
reproductible entre deux tirages.

Conformément à §47 : **aucun réglage n'a été fait, aucune R3 n'est créée, aucun
autre wedge n'est engagé.** SPEC-009C n'est pas committée (§49).
