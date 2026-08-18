# WEDGE-HARDENING R1 — durcissement ciblé du wedge intrants de chantier

**Date** : 2026-08-17 · **Branche** : `main` · **Verdict** : `WEDGE-HARDENING PASS`

Trois corrections, toutes rattachées à un défaut observé dans SPEC-009B. Aucun
appel LLM. Une seule itération d'implémentation consommée sur les deux
autorisées. Le durcissement **n'est pas committé** (§66).

---

## SPEC-009B COMMIT

```text
hash     71d4f07a4cacc40ea3d2d14da999d8469274d3a3
message  research(wedges): identify construction materials MVP wedge
branch   main (non poussée)
files    docs/reports/2026-08-17-spec009b-wedge-selection.md   712 lignes
         src/signals/research/wedge.py                         294 lignes
         tests/fixtures/signal100/wedge_gold.json             9225 lignes
         tests/test_wedge_analysis.py                          356 lignes
```

Précondition vérifiée avant ce commit : 1640 tests verts, `ruff check` propre,
`git diff --check` propre, zéro fichier suivi modifié.

---

## FILES CHANGED

Durcissement (non committé) :

```text
A  src/signals/understanding/object_text.py     objet publié informatif ou non
M  src/signals/understanding/cpv.py             TradeDomain + table CPV
M  src/signals/understanding/engine.py          domaine, objet publié, résumé
M  src/signals/understanding/model.py           champ trade_domain
M  src/signals/needs/features.py                objet publié + métier exposés
M  src/signals/needs/model.py                   champ subject ; v0.2
M  src/signals/needs/rules.py                   deux gabarits rendus conditionnels ; v0.5
M  src/signals/needs/engine.py                  composition du sujet
M  src/signals/matching/icp.py                  domaines métier ICP ; v0.2
M  src/signals/matching/engine.py               filtre dur + porte métier
M  src/signals/matching/reference.py            ICP du wedge
M  src/signals/matching/__init__.py             exports
A  tests/test_wedge_hardening.py                34 tests de régression
M  tests/test_{contract_understanding,contract100_benchmark,icp_model,
     matching_fixtures,need_roles,signal100_gold,verifier_dev_set,
     wedge_analysis}.py                         épinglages de version
```

Aucune dépendance ajoutée : `pyproject.toml` et `uv.lock` sont inchangés.

---

## WEDGE BASELINE

SPEC-009B, wedge *fournisseur d'intrants de chantier × `construction` ×
`materials_or_components`*, 41 signaux adjugés (A=7, B=26, C=8, D=0) :

```text
précision utile      80,49 %      (GREEN exige 85 %)
faux / trompeurs     0
faux critiques       0
intégrité factuelle  100 %
couverture de preuve 100 %
taux générique       0 %
erreurs de timing    0
volume naturel       73 SHOW pour 800 award-lots
```

Seul blocage : la précision. Huit signaux faibles, huit causes nommées — six de
granularité métier (couche `matching`), deux de sujet du besoin (couche
`need graph`).

---

## TRADE DOMAIN STUDY

Étude conduite avant toute modification du domaine, sur les 41 signaux du wedge
puis validée sur les 197 award-lots CPV-45 du pool de 800.

**Le profil existant ne sépare pas les échecs.** `ConstructionProfile`
(préfixe CPV 3 chiffres, SPEC-007) donne : `building_civil` n=30 → 80,0 % utile ;
`technical_installation` n=5 → 60,0 % ; `finishing` n=6 → 100 %. La granularité
est trop grossière pour distinguer un négoce d'un grossiste.

**À 5 chiffres, les distinctions apparaissent** : 45212/45213/45215/45262 →
100 % (13 signaux) ; 45420/45421/45442 → 100 % (6) ; 45311/45315 → 100 % (3) ;
45233 routes → 71,4 % (7) ; 45240 → 66,7 % (3) ; **45316 éclairage public → 0 %**,
**45331 CVC → 0 %**, **45234 caténaire → 0 %**.

| domaine candidat | cas observés | faits canoniques | valeur commerciale | risque d'ambiguïté | verdict |
|---|---|---|---|---|---|
| `general_building` | 19/41 · 65/197 | CPV 452 hors 4523-4525 | cœur de cible du négoce | faible ; inclut 4522 ouvrages d'art | **garder** |
| `interior_finishing` | 6/41 · 10/197 | CPV 454 | second œuvre, 100 % utile | faible | **garder** |
| `earthworks_demolition` | 0/41 · 5/197 | CPV 451 | granulats, remblais | faible | **garder** |
| `roadworks_civil` | 7/41 · 22/197 | CPV 4523 hors 45234 | achète, mais l'essentiel en centrale d'enrobés | moyen | **garder, secondaire** |
| `special_civil` | 3/41 · 5/197 | CPV 4524-4525 | fourniture sur plan | moyen | **garder, secondaire** |
| `technical_installation` | 5/41 · 11+6/197 | CPV 453 | canal électricité/CVC distinct | faible | **garder, hors cible** |
| `rail_infrastructure` | 1/41 · 1/197 | CPV 45234 | fabricant ferroviaire | faible ; n=1 dans ce pool | **garder, hors cible** |
| `equipment_hire` | 0/41 · 1/197 | CPV 455 | déjà distingué par SPEC-007 | faible ; n=1 | **garder, hors cible** |
| `unknown_or_general` | 0/41 · 71/197 | CPV 45000000 | aucune | — | **garder comme aveu** |
| séparer électricité de CVC | 0 cas le justifiant | CPV 4531 vs 4533 | nulle en V0 | — | **rejeter** |
| `bridges_tunnels` distinct | 0 cas le justifiant | CPV 4522 | nulle en V0 | — | **rejeter** |

---

## FINAL TRADE DOMAIN TAXONOMY

Neuf valeurs, toutes peuplées dans le pool, toutes issues de la nomenclature CPV
publique. Le préfixe le plus long gagne — c'est ce qui permet à `45234` de se
détacher des `4523` routiers.

```text
451    → earthworks_demolition
452    → general_building            (4522 ouvrages d'art, 4526 travaux spéciaux compris)
4523   → roadworks_civil
45234  → rail_infrastructure
4524   → special_civil
4525   → special_civil
453    → technical_installation      (électricité, CVC, sanitaire — un seul domaine en V0)
454    → interior_finishing
455    → equipment_hire
sinon  → unknown_or_general
```

`unknown_or_general` n'est pas un domaine : c'est l'aveu qu'un `45000000` ne dit
pas le métier. 71 des 197 marchés de travaux mesurés sont dans ce cas.

---

## DOMAIN MODEL

`TradeDomain` vit dans `signals/understanding/cpv.py`, à côté de `ContractType`
et `Sector`, parce que le corps de métier est un fait du contrat et que la
compréhension est la première couche où il existe (§5).

`ContractUnderstanding.trade_domain: Claim | None`. Le champ est facultatif :
quand le CPV ne dit rien, le moteur **n'affirme rien du tout** — pas même
« inconnu ». C'est cohérent avec `Claim.is_material`, qui traite `unknown` comme
une non-affirmation, et cela évite de creuser la couverture de preuve avec une
affirmation vide.

Aucun mot-clé, aucun nom d'entreprise, aucun texte libre n'entre dans cette
dérivation (§12).

---

## ICP TRADE-FIT MODEL

`TargetICP` gagne `primary_trade_domains` et `secondary_trade_domains`, calqués
sur `primary/secondary_need_categories`. Trois validateurs :

- un métier ne peut être primaire et secondaire à la fois ;
- `unknown_or_general` ne se cible pas (§13) — un CPV muet ne peut pas être une
  correspondance positive ;
- des secondaires sans primaire sont refusés : l'ICP dirait ce qu'il accepte à
  regret sans dire ce qu'il vise.

**Laissés vides, ces champs n'introduisent aucune règle.** C'est la garantie de
non-régression : les sept ICPs de référence gelés traversent la correction sans
changer d'un signal.

---

## WEDGE ICP

```text
icp_id                   icp-construction-inputs-ch-eu-v0
name                     Négoce d'intrants de chantier — Suisse et zone euro
primary_need_categories  materials_or_components
secondary                equipment_or_rental
primary_trade_domains    general_building, interior_finishing, earthworks_demolition
secondary_trade_domains  roadworks_civil, special_civil
territoires              CH, DE, FR, ES, PT   (lieu d'exécution, requis)
type de contrat          construction
seuils                   CHF 100 000 · EUR 100 000
âge maximal              120 jours
```

Il vit **hors** de `REFERENCE_ICPS` : y ajouter un huitième profil rendrait le
banc SPEC-008 incomparable. Son périmètre est celui mesuré dans le rapport
SPEC-009B, pas une cible inventée.

Profil sur les 800 award-lots : **39 SHOW** (4,9 pour 100), 17 `borderline`,
540 `exclude`, 204 `insufficient_data`. Les SHOW se répartissent en
`general_building` 34 et `interior_finishing` 5. Les 39 besoins matériaux portent
tous un sujet.

---

## MATCHING CHANGES

Un filtre dur `trade_domain` et une porte de décision — **aucun nouveau composant
pondéré** (§18). Cinq issues :

```text
not_configured  l'ICP ne cible aucun métier          → rien ne change
exact           métier primaire                      → peut atteindre le feed
compatible      métier secondaire                    → borderline
unknown         le CPV ne dit pas le métier          → borderline, jamais show
incompatible    métier hors cible                    → filtre dur, exclude
```

`incompatible` est **évaluable** : ce n'est pas une donnée qui manque, c'est une
donnée qui dit non. Le verdict est `exclude`, jamais `insufficient_data`.

La décision `show` exige désormais `trade_ok` en plus des trois appuis existants.
`compatible` et `unknown` descendent en `borderline` : le signal reste pertinent,
il ne disparaît pas du produit.

`MATCH_POLICY_VERSION` : `icp-match-v0.1` → **`icp-match-v0.2`**.

---

## NEED SUBJECT MODEL

`ResourceNeed.subject: NonEmptyStr | None` — de quoi ce besoin parle. Composé de
deux faits canoniques seulement : l'objet publié tel quel, et le corps de métier
porté par le CPV.

```text
« BKP 272.0 Innentüren aus Metall (general_building) »
```

Les blancs sont réduits (les avis publient des métrés multilignes), le texte est
coupé à 120 caractères — **jamais résumé** : couper est vérifiable, résumer
serait réécrire l'avis. Quand aucun objet n'est établi, le sujet est `None` et la
justification le dit.

---

## NEED GRAPH CHANGES

Deux gabarits **affirmaient** ce que l'objet pouvait contredire. Ils deviennent
conditionnels (§21) :

```diff
- Les travaux relèvent du terrassement ou du génie civil, qui mobilisent des
- engins au-delà du parc courant : une location est plausible.
+ Le corps de métier publié compte parmi ceux qui mobilisent des engins au-delà
+ du parc courant : si l'exécution comporte de tels travaux, une location est
+ plausible.
```

```diff
- La nature des travaux — bâtiment, installation technique ou finition —
- consomme des matériaux en volume : des achats sont plausibles.
+ Le corps de métier publié consomme des matériaux et des composants en volume :
+ si l'objet du lot en relève, des achats sont plausibles.
```

Chaque besoin ajoute ensuite sa clause de sujet :

> Elle porte sur l'objet publié « … » : si cet objet ne relève pas de ces
> travaux, elle ne tient pas.

L'hypothèse devient **révocable par le sujet qu'elle nomme** — c'est exactement
ce qui manquait au lot de portes métalliques.

`ENGINE_VERSION` : `need-graph-v0.1` → **`need-graph-v0.2`**.
`RULE_LIBRARY_VERSION` : `need-rules-v0.4` → **`need-rules-v0.5`**.

---

## NON-INFORMATIVE SUBJECT TRACE

Objet fautif : `WEGLEITUNG INHALT UND ECKDATEN` (« notice : contenu et données
clés » — l'intitulé d'une rubrique du formulaire SIMAP).

```text
1. SOURCE            procurement.orderDescription = "<p>WEGLEITUNG INHALT UND ECKDATEN</p>"
                     La source publie RÉELLEMENT cette chaîne.

2. CONNECTEUR        award.description = "<p>WEGLEITUNG INHALT UND ECKDATEN</p>"
                     award.title       = "BKP 230 Elektro"        ← informatif
                     Fidèle. Aucune erreur de mapping : trois award-lots frères
                     partagent la même description alors que leurs titres
                     diffèrent (BKP 230 Elektro / BKP 242 Heizung / BKP 250
                     Sanitäranlagen). C'est l'acheteur qui a laissé le gabarit.

3. CONTRACT UNDERST. object_summary = "... Objet publié : WEGLEITUNG INHALT UND ECKDATEN"
                     engine.py:508 ajoutait la clause dès que le champ était
                     non vide, sans test d'informativité.        ← PREMIÈRE FAUTE

4. NEED GRAPH        héritait le sujet sans pouvoir le contester.
5. SNAPSHOT          l'affichait au client.
```

---

## FIRST WRONG LAYER

```text
CONTRACT UNDERSTANDING — composition de object_summary
```

Le connecteur et la source sont hors de cause.

---

## SUBJECT GUARD / FIX

§31 demande de préférer une hiérarchie de champs à une liste de phrases. **Les
deux options structurelles ont été essayées et mesurées sur les 800 award-lots
avant d'être écartées** :

- *Forme typographique* (capitales, absence de chiffres, brièveté) : la règle
  attrape six descriptions, dont **trois vrais objets** — `BOISSONS ET SIROPS`,
  `EPICES ET SELS`, `GESTIONE NIDO SELLA GIUDICARIE`.
- *« Courte et sans mot commun avec le titre »* : **quarante descriptions
  tombent, dont les plus informatives du corpus.** Le titre publie le PROJET et
  la description publie le LOT — `BKP 213 Montagenbau in Stahl` sous « Umbau
  Hallen- und Freibad », `Façades` sous « Campus du Pôle Santé »,
  `Środki przeciwnowotworowe` sous un titre réduit à « Pakiet Nr 1 ». Cette
  hiérarchie détruirait précisément le champ qui porte le métier.

Le seul trait commun des cas non informatifs est **sémantique** : ce sont des
renvois vers une autre pièce (`Siehe Ausschreibungsunterlagen`, `Zie bestek`,
`Lo indicado en los pliegos`, `Conform Caiet de sarcini`) ou des restes de
formulaire. Aucune forme ne les distingue. La liste est donc assumée, et tenue
étroite par trois contraintes :

1. elle ne s'applique qu'au texte **entier**, jamais en sous-chaîne — « Voir
   cahier des charges : fourniture de 300 fenêtres bois » passe ;
2. un renvoi ne tolère après lui qu'une référence de trois mots au plus, ce qui
   couvre « Se référer au cahier des charges C02C1 » ;
3. son effet est de **taire une affirmation**, jamais d'écarter un signal.

S'y ajoute une règle réellement structurelle : un numéro de lot nu (`Default
lot`, `Lote 1`, `Pakiet Nr 1`, `1`) n'est pas un objet — phénomène que `cpv.py`
documente depuis SPEC-005.

La hiérarchie de champs subsiste, mais **dans le bon sens** : la description
l'emporte quand elle décrit, le titre reprend la main sinon. Résultat sur le cas
tracé — l'objet publié devient `BKP 230 Elektro`, établi par le champ `title`,
et le gabarit disparaît du résumé.

---

## BUG GOVERNANCE

```text
BUG
  Le résumé de contrat composait « Objet publié : … » à partir de
  award.description sans vérifier que ce champ décrive l'objet.

IMPACT
  3 award-lots sur 800 dans ce pool. Le signal atteignait le feed en nommant un
  sujet inexistant. Aucun fait faux : le texte cité était réellement publié.

AFFECTED PRIOR RESULTS
  Aucun. Les 3 lots portent le CPV 45000000, donc le profil
  `general_or_unknown`, qui ne produit aucun besoin `materials_or_components` :
  ils ne sont dans aucun des 41 signaux du wedge, ni dans les 100 de SPEC-009.

FIX
  describes_object() dans signals/understanding/object_text.py, appliqué à la
  composition du résumé et à la dérivation de l'objet publié.

REGRESSION TEST
  tests/test_wedge_hardening.py :
    TestPublishedObjectIsInformative (7 tests)
    TestPublishedObjectHierarchy::test_the_engine_keeps_the_boilerplate_out_of_
      the_object_summary — rejoue l'award-lot réel de bout en bout.
```

Aucun `PRIOR RESULT INVALIDATED`.

Un second point, non qualifié de bug mais signalé : les bancs gelés de SPEC-009,
009A et 009B ne sont plus reproductibles avec les moteurs courants, puisque la
compréhension et l'appariement ont changé de version. Les trois tests qui
épinglaient les constantes vivantes ont été **réécrits pour épingler le relevé
historique du sceau** plutôt que réalignés sur les nouvelles versions — les
réaligner aurait fait dire au dépôt que les 68,75 % de SPEC-009A avaient été
mesurés sur `icp-match-v0.2`, ce qui est faux.

---

## DEV ITERATION 1

Mesure isolée : mêmes ICPs sources (`icp-materials-eu`, `icp-national-supplier`),
seuls les domaines de métier du wedge ajoutés. Rien d'autre ne bouge, donc l'écart
mesuré est bien celui de la correction.

```text
retenus              25 / 41       rétention 61,0 %
précision utile      92,00 %
faibles (C) retenus  2             — tous deux couche `need graph`
faux (D) retenus     0
utiles écartés       10
faibles écartés      6
```

Un seul défaut découvert dans le code neuf — les sauts de ligne des métrés
passaient dans le sujet — corrigé par normalisation des blancs. Il n'a pas
consommé d'itération : aucune règle n'a changé.

## DEV ITERATION 2

Non consommée.

---

## FINAL WEDGE DEV RESULTS

```text
signals retained            25
useful                      23
weak                         2
false/misleading             0

useful precision            92,00 %
generic rate                 0,00 %
critical false               0
trade mismatch false shows   0
retention                   61,0 %
useful signals suppressed   10
```

Dimensions du gold sur les 25 retenus :

```text
factual_integrity   pass 25                              → 100 %
proof               adequate 16 · strong 9               → 100 %
specificity         acceptable 17 · specific 8           → 0 % générique
need                credible 22 · plausible_but_weak 3
icp_fit             strong 14 · plausible 10 · weak 1
actionability       actionable 6 · worth_investigating 18 · too_weak 1
timing              clear 10 · acceptable 14 · unknown 1 → 0 erreur
```

**Réserve méthodologique (§39).** Ces verdicts sont ceux du gold SPEC-009B,
antérieurs à la reformulation des justifications. Les 25 signaux retenus voient
leur texte changer : la justification devient conditionnelle et nomme son sujet.
Une réadjudication en aveugle serait nécessaire pour un chiffre définitif. Elle
n'a pas été conduite ici — la mesure est donc **conservatrice sur ce qui a été
vérifié** : les 25 sujets ont été inspectés un par un, aucun n'est vide ni
aberrant, et la clause ajoutée n'affirme rien de neuf. Elle rend une hypothèse
contestable, elle n'en fabrique aucune.

---

## SIX MATCHING FAILURES

Les six signaux faibles de granularité métier, et leur sort après correction :

```text
9605ced2bd  45234160  caténaire tramway        rail_infrastructure     exclude
60eb2b53e7  45316110  éclairage public         technical_installation  exclude
386a648d28  45331210  centrale de ventilation  technical_installation  exclude
6aca6c92f4  45240000  fonçage DN800 sous A63   special_civil           borderline
ea40b38ed6  45233220  renforcement chaussée    roadworks_civil         borderline
9065fde48e  45233220  routier tier 1 intégré   roadworks_civil         borderline
```

**Six sur six sortent du feed.** Trois par filtre dur (le métier dit non), trois
par rétrogradation en `borderline` (le métier achète parfois au négoce, mais
commande l'essentiel ailleurs).

Le cas `9065fde48e` mérite une note : l'adjudicateur l'avait rattaché à
l'intégration verticale du titulaire, un fait que le moteur n'a pas le droit de
lire (§12 interdit les noms d'entreprise). Il sort néanmoins du feed, par son
métier — la bonne raison, pas la raison invoquée.

---

## TWO GENERIC NEED FAILURES

```text
19d9fab760  « GGS Steigerweg Erweiterung - Totalübernehmer »
            objet d'une ligne, aucune date d'exécution.
            → la hiérarchie de champs fait remonter la description du lot :
              le sujet devient « Komplett- u. Teilbauleistungen bei
              Schulerweiterung (general_building) », qui nomme un vrai marché.

0cffdfe9e5  « BKP 272.0 Innentüren aus Metall »
            le besoin d'engins était justifié par « les travaux relèvent du
            terrassement ou du génie civil » — sur un lot de portes.
            → l'affirmation a disparu. Les trois besoins nomment désormais
              « Neubau BKP 272.0 Innentüren aus Metall (general_building) » et
              se déclarent révocables par cet objet.
```

Les deux restent dans le feed avec leur verdict C d'origine : ce sont des
défauts de **couche `need graph`**, et le gold n'a pas été rejoué. Le mécanisme
exact que les adjudicateurs reprochaient n'existe plus dans la sortie.

---

## REGRESSION TESTS

`tests/test_wedge_hardening.py` — 34 tests. Chaque règle est éprouvée trois fois
(§46) : le cas qu'elle doit attraper, le cas voisin qu'elle ne doit **pas**
attraper, et un cas qui ne la concerne pas.

Cycle rouge-vert vérifié (§49) — chaque correction retirée, la suite ciblée
repasse au rouge, puis restaurée :

```text
porte métier (décision)          retirée → 1 échec / 6
filtre dur métier                neutralisé → 3 échecs / 6
objet non informatif             retiré → 1 échec / 4
sujet du besoin                  retiré → 4 échecs / 6
```

---

## SPEC-006/007/008/009 NON-REGRESSION

```text
SPEC-006  AUTO_DOCUMENT_REQUIREMENTS_ENABLED reste False. Intouché.
SPEC-007  Le gold `need_final` est un test d'intégrité de fixture : il n'exécute
          pas le moteur, ses SHA sont inchangés. Les versions montent en v0.2 /
          v0.5, comme §22 l'exige d'un changement de sémantique.
SPEC-008  Les sept ICPs de référence ne déclarent aucun métier : le filtre rend
          `not_configured` et rien ne change. La bibliothèque gelée et son SHA
          (698cb112…) sont intacts, l'ICP du wedge vit à côté.
SPEC-009  Corpus (7996beae…) et gold (21be11fc…) byte-identiques. Le sceau est
          intact. Les bancs 009 / 009A / 009B deviennent des relevés historiques,
          ce que leurs tests énoncent désormais explicitement.
```

Aucun test historique supprimé. Les épinglages modifiés le sont pour dire la
vérité sur une version qui a bougé, jamais pour masquer un échec.

---

## VPS PORTABILITY CHECK

```text
chemins absolus dans le code ajouté   aucun
dépendances ajoutées                  aucune (pyproject.toml et uv.lock intacts)
réseau requis par les tests           aucun — tout part des fixtures gelées
horloge lue                           aucune : `as_of` reste explicite partout
appels LLM                            aucun
```

---

## TEST RESULTS

```text
uv run pytest -q          1674 passed in 14,21s        (1640 avant, +34)
uv run ruff check .       All checks passed!
git diff --check          propre
uv run ruff format --check .
                          1 file would be reformatted
```

Le défaut de format est **le défaut historique connu** : il porte sur
`docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md`,
un document de plan committé en `d173265`, dont ruff reformate les blocs de code
Python. Il est antérieur à ce travail et n'a pas été touché. `ruff format --check
src tests` passe sans réserve.

---

## OPEN QUESTIONS

1. **Le CPV du lot est parfois celui du projet.** Deux signaux retenus portent un
   objet dont le métier réel diverge de leur CPV : `BKP 250
   Sanitärinstallationen` et `Lieferung und Montage einer PVA, min. 410 kWp`,
   tous deux sous un CPV `general_building` hérité du projet. Le métier vrai est
   dans la description du lot, mais le dériver d'un texte libre serait du
   mot-clé — ce que le dépôt refuse comme décideur depuis SPEC-005, où `cpv.py`
   pose que « le titre confirme une lecture, il ne la décide pas ». Non corrigé,
   assumé, mesuré : les deux sont dans les 25 retenus, et le gold les juge
   **utiles** (B). C'est donc une limite à surveiller, pas un défaut qui pèse
   aujourd'hui sur la précision.

2. **La réadjudication de §39 reste due.** Les 92,00 % s'appuient sur un gold
   antérieur à la reformulation. Un chiffre définitif exige une adjudication en
   aveugle des 25 signaux retenus.

3. **`rail_infrastructure` et `equipment_hire` sont à n=1** dans ce pool. La
   règle qui les définit est une division CPV publique, pas une inférence sur un
   cas — mais leur valeur commerciale n'est pas mesurée.

4. **L'âge du signal se compte toujours depuis la publication**, pas depuis la
   décision d'attribution, alors que l'arbitrage SPEC-009B a tranché l'inverse.
   Le wedge ne présentant aucune erreur de timing, la correction sortait du
   périmètre autorisé (§1). Elle reste ouverte.

---

# VERDICT

```text
WEDGE-HARDENING PASS
```

| critère | exigé | mesuré | |
|---|---|---|---|
| useful precision | ≥ 90 % | **92,00 %** | ✓ |
| false / misleading | 0 | **0** | ✓ |
| critical false | 0 | **0** | ✓ |
| factual integrity | 100 % | **100 %** | ✓ |
| proof coverage | 100 % | **100 %** | ✓ |
| generic signal rate | ≤ 5 % | **0 %** | ✓ |
| trade mismatch false shows | 0 | **0** | ✓ |
| retention | ≥ 60 % | **61,0 %** | ✓ |
| retained signals | ≥ 25 | **25** | ✓ |

Deux critères passent de justesse — la rétention à 1,0 point et le nombre retenu
exactement au plancher. C'est la conséquence directe d'un arbitrage refusé :
`roadworks_civil` aurait pu être déclaré primaire pour gagner sept signaux, mais
les données disent 71,4 % d'utilité sur ce domaine, et le déclarer cœur de cible
aurait fait retomber la précision à 87,5 %. Le durcissement n'a pas été calibré
pour franchir le gate ; le gate est franchi par ce que le négoce vend vraiment.

Le durcissement **n'est pas committé** (§66). La suite n'est pas engagée (§67) :
SPEC-009C — *Fresh Construction Inputs Wedge Benchmark* — reste à la décision du
superviseur.
