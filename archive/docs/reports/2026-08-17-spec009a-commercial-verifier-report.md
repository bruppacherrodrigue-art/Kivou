# SPEC-009A — LLM Commercial Signal Verifier V0

**Date** : 2026-08-17 · **Verdict** : `SPEC-009A NOT DONE`

---

## FILES CHANGED

Aucun moteur gelé n'a été touché. Rien n'est committé (§56).

**Nouveau paquet `src/signals/verification/`** — le produit client, 12 modules :

| Fichier | Rôle |
|---|---|
| `model.py` | contrat de sortie fermé (§19), schéma JSON strict dérivé du modèle, versions (§27) |
| `view.py` | vue d'entrée (§14), catalogue de faits identifiés (§20), barrière de langue (§16) |
| `prompt.py` | consigne (§18), délimitation du contenu non fiable (§17), vocabulaire interdit (§21) |
| `protocol.py` | `CommercialSignalVerificationModel` — la frontière fournisseur (§7) |
| `validation.py` | validateur déterministe (§20–§22) |
| `policy.py` | politique finale V0 (§23, §24) |
| `runner.py` | orchestration, plafond de budget, concurrence bornée, cache périodique (§9, §10, §26) |
| `cache.py` | cache déterministe portable, borné, à écriture atomique (§11) |
| `errors.py` | taxonomie des pannes (§25) |
| `metrics.py` | métriques et gates DEV/final (§31, §32, §39–§45) |
| `fake.py` | double déterministe pour les tests hors ligne (§7) |
| `openrouter.py` | **seul** module nommant un fournisseur : adaptateur + point de composition |

**Script de recherche** : `src/signals/research/verifier_dev.py` — agnostique du
fournisseur ; reçoit modèle, sondes et libellé de blocage en paramètres.

**Tests** — 151 ajoutés, tous hors ligne :
`test_verifier_contract.py` (61), `test_verifier_adversarial.py` (45),
`test_verifier_metrics.py` (24), `test_verifier_dev_set.py` (21), plus
`tests/conftest.py`.

**Fixtures** : `verifier_dev_gold.json`, et les artefacts des deux itérations
(`verifier_dev_{report,result}_iter1.json`, `…_iter2.json`).

---

## VERIFIER MODEL

```text
Provider    OpenRouter
Model       deepseek/deepseek-v4-flash     ← slug exact de §6, confirmé au catalogue
Context     1 048 576
Prix        0,0798 / 0,1596 USD par M tokens (entrée / sortie)
temperature 0 · max_tokens 4000 · timeout 90 s · 6 workers
retry       1 retentative de schéma, 0 retentative sémantique
```

Aucun substitut n'a été nécessaire, aucun `SPEC-009A BLOCKED — APPROVED MODEL
UNAVAILABLE`. La clé a été lue uniquement depuis `OPENROUTER_API_KEY`, jamais
écrite dans le dépôt, un log, une fixture ou le cache.

---

## INPUT VIEW

Strictement §14. Absents et vérifiés par test (§13) : `normalized_score`,
`raw_points`, `score_components`, `band`, `decision`, `rule_ids`,
`mechanism_facts`, `pressure_facts`, gold, verdict attendu.

Mesuré sur les 150 vues réelles : catalogue de **10 à 14 faits** par signal
(médiane 12) ; langue détectée fr 125, en 8, indéterminée 17 ; **0 candidat
écarté** par la barrière de langue.

**Interprétation déclarée de §16** : la vue est composée en français, le texte
source y est cité comme donnée non fiable. Elle n'est jugée non représentable que
si le texte libre n'est ni FR ni EN **et** que le squelette structuré (CPV + type
de contrat) ne porte rien. Écarter mécaniquement toute adjudication germanophone
aurait créé la règle par pays que §16 interdit, et détruit le rappel sur un
marché CH + UE.

---

## OUTPUT SCHEMA

`commercial-verifier-schema-v0.1` — 14 champs, tous requis,
`additionalProperties: false`, aucune définition externe (`$ref` résolus
récursivement pour `strict: true`), **dérivé du modèle Pydantic** plutôt que
réécrit. Double validation : par le fournisseur, puis par Pydantic — seule cette
seconde fait autorité.

Résultat : **0 échec de schéma sur 150** en itération 2 (6 retentatives de forme,
toutes réussies), **0 identifiant de fait inventé**, **0 formulation de
certitude**.

---

## FINAL POLICY

`commercial-verifier-policy-v0.1`, inchangée entre les deux itérations. Elle
applique §23 à la lettre : neuf conditions, `blockers` vide, au moins un fait de
soutien, identifiants tous valides. Un candidat `borderline` passe **exactement**
la même politique (§24) — l'objet de politique est littéralement le même, ce
qu'un test vérifie.

Trois choix de conception :

1. **Validateur et politique ne se recouvrent pas.** §22 invalide la
   contradiction franche (`confirmed`, `yes`, `stale`) ; §23 refuse en plus le
   doute (`suspected`, `possible`).
2. **Aucun texte source ne sort du bloc non fiable**, pas même l'énoncé d'un
   fait : le catalogue est scindé, identifiants dans la consigne, énoncés dans le
   bloc. Ce défaut existait en v0.1 du prompt et c'est le test adversarial J qui
   l'a attrapé.
3. **La `description` du marché n'est pas transmise** — §14 ne la liste pas, ce
   qui réduit d'autant la surface d'injection.

---

## DEV GOLD

**150 candidats** (§28) : 100 `show` de Signal-100 + 50 `borderline` du shadow set.

| | A | B | C | D | utiles (A+B) |
|---|---|---|---|---|---|
| 100 SHOW (gold SPEC-009, inchangé) | 5 | 47 | 38 | 10 | 52 |
| 50 BORDERLINE (gold SPEC-009A) | 6 | 21 | 16 | 7 | 27 |
| **DEV total** | **11** | **68** | **54** | **17** | **79 / 150 = 52,7 %** |

Les 50 borderline ont été adjugés par deux perspectives indépendantes sur vues
aveugles, rubrique `commercial-signal-rubric-v1` **inchangée**, doctrine
d'arbitrage de SPEC-009, **avant** tout appel au modèle.

```text
accord exact               80,0 %   (40 / 50)
accord à un grade près    100,0 %   (50 / 50)
arbitrages                    19

VERIFIER_DEV_GOLD_SHA256
ce02903d1b987858204e027357027047fd3b8ebd5b407048137aaedbf8195e8a
```

L'accord à un grade près de **100 %** écarte l'hypothèse que le résultat qui suit
serait un artefact de doctrine instable.

**Observation non sollicitée** : la majorité des `D` du lot borderline sont des
décalages géographiques durs (DK, RO, IE, NO, CY, GR, CZ, FI, SE, IT) hors des
territoires déclarés. Ils ont franchi le filtre parce que `icp-national-supplier`
et `icp-subcontracting-eu` déclarent `geography_policy: preferred` et non
`required` : hors territoire coûte une pénalité au lieu d'exclure. Constat
SPEC-008, consigné sans être corrigé (§5).

---

## DEV ITERATION 1

Prompt `commercial-verifier-prompt-v0.1`.

```text
final shows                 16 / 150  (10,7 %)
useful precision              62,5 %      gate >= 95 %    ÉCHEC
useful recall                 12,7 %      gate >= 60 %    ÉCHEC
final show rate               10,7 %      gate >= 30 %    ÉCHEC
weak final show rate          37,5 %      gate <=  8 %    ÉCHEC
top20 useful precision        62,5 %      gate >= 95 %    ÉCHEC
false final show rate          0,0 %      gate <=  2 %    OK
critical false final shows         0      gate  =  0      OK
fact reference validity      100,0 %                      OK
forbidden wording                  0                      OK
```

**Diagnostic.** Le filtre bloquait tout : 74 `downgrade`, 21 `reject`, et 31
`approve` invalidés — dont **30 pour le seul motif `need_credibility =
plausible_but_weak`**. Le modèle classait 111 besoins sur 149 en
`plausible_but_weak`.

Cause identifiée, et c'était un défaut réel du prompt : **la v0.1 ne définissait
aucun grade**. Le modèle devait déduire `credible` du seul nom de l'énumération,
et le lisait comme « prouvé ». Or §23 exige `need_credibility = credible` pour
montrer : seuls **16 des 79 signaux utiles** avaient reçu ce grade, ce qui
plafonnait mécaniquement le rappel à **20,3 %** contre 60 % exigé — inatteignable
par construction, quel que soit le reste.

---

## DEV ITERATION 2

Prompt `commercial-verifier-prompt-v0.2` — ajout des **définitions explicites de
chaque grade**, reprises de la rubrique qui a produit le gold. Aucune règle
nouvelle : la fin d'une devinette. Schéma et politique inchangés.

```text
final shows                 80 / 150  (53,3 %)
useful precision             68,75 %      gate >= 95 %    ÉCHEC
useful recall                69,62 %      gate >= 60 %    OK
final show rate              53,33 %      gate >= 30 %    OK
weak final show rate         28,75 %      gate <=  8 %    ÉCHEC
false final show rate          2,5 %      gate <=  2 %    ÉCHEC
critical false final shows         1      gate  =  0      ÉCHEC
top20 useful precision        70,0 %      gate >= 95 %    ÉCHEC
fact reference validity      100,0 %      gate = 100 %    OK
forbidden wording                  0      gate  =  0      OK
```

Distribution des 80 montrés : A 9, B 46, C 23, D 2.
Verdicts bruts du modèle : `approve` 82, `downgrade` 50, `reject` 18.

Le rappel passe de 12,7 % à **69,6 %** et le volume de 10,7 % à 53,3 % : la
correction visait juste. La précision, elle, ne bouge que de 62,5 % à 68,75 %.

### Pourquoi la seconde itération n'a pas été dépensée

§30 en autorise deux ; une seule a été consommée. La seconde a été **refusée sur
preuve**, pas par renoncement.

**Preuve 1 — le modèle note les vrais et les faux à l'identique.** Sur les 80
signaux montrés :

| dimension | 55 montrés **utiles** | 25 montrés **non utiles** |
|---|---|---|
| `need_credibility` | credible 100 % | credible 100 % |
| `icp_fit` | strong 60 % / plausible 40 % | strong 56 % / plausible 44 % |
| `actionability` | worth_inv. 67 % / actionable 33 % | worth_inv. 76 % / actionable 24 % |
| `specificity` | acceptable 67 % / specific 33 % | acceptable 72 % / specific 28 % |
| `timing_status` | unknown 60 % / current 40 % | unknown 52 % / current 48 % |

Les distributions sont indiscernables. Aucun seuil posé sur la sortie du modèle
ne peut séparer ces deux populations.

**Preuve 2 — être plus sélectif n'améliore pas la précision.** L'itération 1
montrait 16 signaux à 62,5 % de précision ; l'itération 2 en montre 80 à
68,75 %. Restreindre a **dégradé** la précision : l'ordre de confiance du modèle
ne porte pas d'information sur l'utilité commerciale.

**Preuve 3 — les seize durcissements possibles de la politique, simulés hors
ligne sur les résultats déjà obtenus** (sans un appel de plus) :

```text
politique la plus permissive   n=80   précision 68,8 %   rappel 69,6 %
politique la plus stricte      n=10   précision 70,0 %   rappel  8,9 %
MEILLEURE précision atteignable        75,0 %  (n=24, rappel 22,8 %)
politiques satisfaisant >= 95 % ET >= 60 %            0
```

Aucune combinaison de `icp_fit` × `actionability` × `specificity` ×
`timing_status` n'approche le gate. Le plafond est à 75 %, vingt points sous
l'exigence, et il coûte 47 points de rappel.

Dépenser la seconde itération à reformuler encore le prompt aurait été une
partie de pêche sur un gold de 150 lignes — exactement la boucle de tuning que
SPEC-009 §46 proscrit.

---

## DEV FINAL RESULTS

```text
candidates                        150
gold                              A 11 · B 68 · C 54 · D 17   (utiles 79)

final shows                        80
true useful final shows            55
weak final shows                   23
false / misleading final shows      2
critical false final shows          1

FINAL SHOW USEFUL PRECISION    68,75 %     gate >= 95 %    ÉCHEC
ACTIONABLE RATE                11,25 %
WEAK FINAL SHOW RATE           28,75 %     gate <=  8 %    ÉCHEC
FALSE FINAL SHOW RATE            2,5 %     gate <=  2 %    ÉCHEC
CRITICAL FALSE FINAL SHOWS           1     gate  =  0      ÉCHEC
USEFUL RECALL                  69,62 %     gate >= 60 %    OK
A RECALL                       81,82 %
B RECALL                       67,65 %
FINAL SHOW RATE                53,33 %     gate >= 30 %    OK
FACT REFERENCE VALIDITY       100,00 %     gate = 100 %    OK
FORBIDDEN WORDING                    0     gate  =  0      OK
TOP20 USEFUL PRECISION          70,0 %     gate >= 95 %    ÉCHEC
```

### Ce que le filtre fait réellement bien

Il serait malhonnête de ne rapporter que l'échec. Sur trois axes, le vérificateur
apporte une valeur mesurable :

| | avant filtre | après filtre |
|---|---|---|
| précision utile des `show` | 52,0 % | **62,7 %** (+10,7 pts, rappel 71,2 %) |
| précision utile des `borderline` promus | 54,0 % | **85,7 %** (+31,7 pts) |

**18 opportunités utiles ont été récupérées parmi les `borderline`** que le
moteur déterministe cachait. Le filtre est nettement meilleur en *promoteur de
borderline* qu'en *nettoyeur de show* — un résultat qui n'était pas anticipé et
qui oriente la suite.

Il bloque aussi correctement 15 des 17 `D` et 31 des 54 `C`.

Par source : SIMAP 42 montrés à 76,2 % de précision utile, TED 38 à 60,5 % —
les deux sous le gate de 85 % de §40.

---

## FALSE APPROVALS

**25 signaux non utiles montrés** (23 gold `C`, 2 gold `D`), rattachés à la
couche que le gold tient pour responsable :

```text
need graph              10
matching                 9
ICP configuration        4
contract understanding   1
timing                   1
```

Le seul **critical false signal** montré est `2210d48c…` (Condecta AG,
Wallisellen) : le marché porte précisément sur la conception et le montage
d'installations de chantier en conteneurs, et le besoin dérivé propose de vendre
au gagnant de la « capacité en matériel de chantier » — le livrable pris pour un
besoin aval, dans sa forme la plus pure.

Ce cas est le plus instructif du banc : **le piège est nommé explicitement dans
le prompt, exemple à l'appui, et le modèle est passé à côté**, répondant
`need_credibility: credible`, `icp_fit: plausible`. Catégorie de défaut :
*deliverable overlap missed*.

---

## FALSE REJECTIONS

**24 signaux utiles cachés** (22 gold `B`, 2 gold `A`) :

```text
verdict=downgrade                        21
verdict=reject                            2
winner_already_provides_need=possible     1
```

Le rejet à tort se concentre presque entièrement sur le `downgrade` : le modèle
hésite sur des `B` — précisément la classe que le gold définit comme « légitime
mais nécessitant vérification ». Les deux `A` perdus sont le coût le plus élevé,
mais le rappel `A` reste le meilleur de tous (81,8 %).

---

## COST

```text
MEASURED
  itération 1        149 requêtes · 12 retentatives · 0,105058 USD
  itération 2        150 requêtes ·  6 retentatives · 0,115377 USD
  course interrompue (limite d'outil, cache perdu)  ≈ 0,10 USD
  ─────────────────────────────────────────────────────────────
  TOTAL SPEC-009A    0,3246 USD           plafond §9 : 1,00 USD

  itération 2 : 1 016 912 jetons d'entrée · 378 938 de sortie
  cache hits 0 (le changement de prompt invalide la clé — comportement voulu)

PROJECTED (depuis l'itération 2)
  coût / 100 candidats                    0,0769 USD
  coût / 100 final shows                  0,1442 USD
  coût / 1 000 candidats déterministes    0,7692 USD
```

Le coût n'est pas un obstacle : filtrer 1 000 candidats coûterait moins d'un
dollar. **Ce n'est pas l'économie du filtre qui échoue, c'est sa discrimination.**

---

## LATENCY

```text
MEASURED (itération 2, 6 workers)
  p50        20 430 ms
  p95        33 963 ms
  max        69 432 ms
  wall time  3 359 s cumulés sur les appels · ~40 min de course réelle

PROJECTED
  100 candidats     ≈ 2 240 s de temps d'appel cumulé (~6 min à 6 workers)
  1 000 candidats   ≈ 22 395 s de temps d'appel cumulé (~1 h à 6 workers)
```

Une latence médiane de 20 s par candidat est vivable en traitement par lots, pas
en synchrone devant un utilisateur. Aucun système asynchrone complexe n'a été
construit (§45).

---

## TEST RESULTS

```text
uv run pytest -q            1602 passed        (1451 avant SPEC-009A, +151)
uv run ruff check .         All checks passed
uv run ruff format --check  1 file would be reformatted   ← préexistant, hors SPEC-009A
git diff --check            propre
git status                  aucun fichier suivi modifié ; rien de committé (§56)
```

Les quinze cas adversariaux de §49 sont tous couverts et verts (A–O). Ils
établissent que chaque piège est représentable, nommé au modèle, et que la
machinerie déterministe cache le candidat dès que la réponse porte la trace du
piège. Ils n'établissent pas que le modèle détecte le piège — et le cas Condecta
montre précisément qu'il ne le détecte pas toujours.

### Non-régression (§48)

| | |
|---|---|
| `SIGNAL100_CORPUS_SHA256` | `7996beae…b224aebf` — **identique** ✅ |
| `SIGNAL100_GOLD_SHA256` | `21be11fc…f1d3e5af` — **identique** ✅ |
| `need-graph-v0.1`, `icp-match-v0.1`, `signal-score-v0.2`, `reference-icps-v0.1` | inchangés ✅ |
| `AUTO_DOCUMENT_REQUIREMENTS_ENABLED` | `False` ✅ |
| Tests historiques | 1602/1602 ✅ |

Deux régressions ont été rencontrées et corrigées **chez moi**, pas dans le test
hérité : le test `test_the_domain_never_names_a_provider` de SPEC-006 interdit
toute marque de fournisseur dans `src/signals`, docstrings comprises. La CLI des
commandes réseau a donc été déplacée dans l'adaptateur et le harnais de recherche
reçoit modèle, sondes et libellé de blocage en paramètres. L'allowlist du test
n'a pas été élargie ; l'architecture y a gagné.

---

## VERDICT

```text
SPEC-009A NOT DONE
GENERALIST LLM FILTER FAILED
PROCEED TO WEDGE SELECTION
```

Le filtre commercial généraliste n'atteint pas les gates DEV de §32. Il échoue
sur la précision (68,75 % contre 95 %), le taux de signaux faibles (28,75 %
contre 8 %), le taux de faux (2,5 % contre 2 %), les faux critiques (1 contre 0)
et la qualité du top-20 (70 % contre 95 %).

Il réussit sur le rappel (69,6 %), le volume (53,3 %), l'ancrage factuel (100 %)
et le vocabulaire (0 formulation de certitude).

**La raison de fond, établie par trois preuves indépendantes** : le modèle
attribue exactement les mêmes grades aux signaux que le gold juge utiles et à
ceux qu'il juge faibles. Restreindre dégrade la précision au lieu de
l'améliorer, et aucune des seize politiques possibles ne dépasse 75 %. Le filtre
sépare bien le **faux** du **vrai** — il bloque 15 des 17 `D` — mais il ne
sépare pas l'**utile** du **techniquement correct mais commercialement vague**.
Or c'est exactement la frontière que SPEC-009 avait identifiée comme le problème
de Kivou, et que SPEC-009A devait faire franchir.

Conformément à §32 et §55 : aucun held-out n'est construit, aucun autre modèle
n'est testé, aucun moteur n'est modifié, aucune R2 n'est créée.

La prochaine unité est **Client Feed Decomposition & MVP Wedge Selection**. Elle
n'a pas été commencée (§55, STOP).

Rien n'est committé (§56). HEAD reste `d75cb61`.

---

## OPEN QUESTIONS

1. **La frontière B/C est-elle apprenable ?** Les deux adjudicateurs humains ne
   s'accordent exactement que sur 73–80 % des cas ; le gate exige 95 % de
   précision. Demander à un modèle de reproduire à 95 % une frontière que des
   experts tracent à 80 % est peut-être mal posé, indépendamment du modèle.
2. **Le filtre vaut-il d'être conservé comme promoteur ?** Il porte les
   `borderline` de 54 % à 85,7 % de précision utile et récupère 18 opportunités.
   C'est le seul usage où il tient un niveau proche des gates. Une V1 pourrait
   l'employer uniquement à cela, et laisser les `show` au moteur déterministe.
3. **Un modèle plus fort changerait-il quelque chose ?** §55 interdit d'en tester
   un autre, et c'est probablement sage : le problème observé n'est pas un
   manque de raisonnement mais l'absence de signal discriminant dans l'entrée —
   les besoins dérivés sont du boilerplate quasi identique d'un contrat à
   l'autre, constat déjà posé par SPEC-009.
4. **`geography_policy: preferred` reste le premier générateur de `D`
   borderline.** Décision SPEC-008, hors périmètre ici, mais elle empoisonne
   toute mesure faite au-dessus.
5. **La latence médiane de 20 s** convient au traitement par lots, pas à un feed
   synchrone. À intégrer si le filtre revient sous une autre forme.
