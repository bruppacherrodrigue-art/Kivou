# SPEC-008R — Model Coherence Closeout

Deux invariants, cohérence décision/bande, audit `as_of`. Date : 2026-08-17. Aucun commit (§10).

Corpus, gold et bibliothèque d'ICPs **non modifiés** — les trois empreintes sont vérifiées intactes
sur disque :

```
FINAL CORPUS   441f0d10614ea1ad05d5948b530a9dab22f9fba7d25143b14aa66435cf62c006   OK
FINAL GOLD     7e183446b7bfa63dc18e153c5ade2edb6ffce7565df354cc809b3e6ece75b583   OK
REFERENCE ICP  698cb112eaa6478eb4680e8513cf036dc22d7651437a356f0637967361400fb2   OK
```

Aucun tuning sur le held-out : la rubrique, les filtres durs, les poids et les quatre seuils
(`SHOW_THRESHOLD`, `BORDERLINE_THRESHOLD`, `STRONG_BAND`, `PROMISING_BAND`) sont inchangés.

---

## FILES CHANGED

| Fichier | Nature | Changement |
|---|---|---|
| `src/signals/matching/icp.py` | modifié | invariant géographique §2 dans `_un_profil_coherent` |
| `src/signals/matching/model.py` | modifié | invariant décision/bande §3 + `SCORE_POLICY_VERSION` → `v0.2` |
| `src/signals/matching/engine.py` | modifié | la bande est dérivée de la décision (§3) |
| `tests/test_matching_coherence.py` | **nouveau** | les 13 tests §8 (16 cas avec paramétrage) |
| `tests/test_matching_adversarial.py` | modifié | test J : le cas `ignore` prend sa configuration cohérente |
| `tests/test_matching_fixtures.py` | modifié | le gold garde la version de politique de **son** run |
| `docs/reports/2026-08-17-spec008-final-report.md` | modifié | renvoi vers cette clôture, questions 1 et 2 refermées |
| `docs/reports/2026-08-17-spec008r-coherence-closeout.md` | **nouveau** | ce rapport |

`src/signals/matching/reference.py` n'est **pas** modifié : la précondition a montré que les 8 ICPs
gelés satisfont déjà le nouvel invariant (0 violation), donc §1 et §2 ne se contredisent pas. Sans
cela, il aurait fallu bloquer.

Aucun fichier de `signals.domain`, `signals.needs`, `signals.understanding` ou `signals.documents`
n'est touché.

**Une modification incidente, hors périmètre, à signaler.**
`docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md` porte une
modification de **formatage seul** : `ruff format` normalise aussi les blocs Python inclus dans le
Markdown, et ce plan en contient. Le fichier était déjà dans cet état dans l'arbre de travail avant
SPEC-008R ; je l'ai brièvement restauré à sa version commitée en croyant à une modification de ma
part, ce qui a fait échouer `ruff format --check`, puis rétabli. Aucun contenu n'est changé, et cela
ne constitue évidemment pas un début de SPEC-009 — mais la ligne apparaît dans `git status` et doit
être connue avant la revue.

`HEAD` reste `367839a` (SPEC-007) : aucun commit n'a été créé.

---

## GEOGRAPHY INVARIANTS

Deux règles, ajoutées à la validation de `TargetICP` — donc **impossibles à contourner**, y compris
par un appelant qui construirait l'ICP à la main.

**1. `basis == "ignore"` si et seulement si `policy == "ignored"`.**

| `geography_basis` | `geography_policy` | Verdict |
|---|---|---|
| `ignore` | `ignored` | ✅ autorisé (le seul mariage cohérent) |
| `ignore` | `required` | ❌ refusé |
| `ignore` | `preferred` | ❌ refusé |
| `place_of_performance` / `winner_location` / `either` | `ignored` | ❌ refusé |
| `place_of_performance` / `winner_location` / `either` | `required` / `preferred` | ✅ autorisé |

**2. Une politique active exige des territoires.** `policy ∈ {required, preferred}` avec
`territories = ()` est refusé. La règle existait déjà pour `required` ; elle est étendue à
`preferred`, parce qu'une préférence sans territoire n'exprime aucune préférence — c'est une
configuration vide qui se lit comme une intention.

Ce que cela ferme concrètement : la question ouverte n°1 du rapport SPEC-008. `basis="ignore"` avec
`policy="required"` était constructible et faisait retomber le score de 91 à 73, le composant
géographie restant au dénominateur alors que le filtre était court-circuité. La configuration n'est
plus atteignable, donc l'asymétrie de dénominateur n'a plus de chemin d'accès.

**Précondition vérifiée avant d'écrire la règle** — la bibliothèque gelée y satisfait déjà :

| ICP | basis | policy | territoires |
|---|---|---|---|
| `icp-staffing-ch` | `place_of_performance` | `required` | 1 |
| `icp-plant-hire-ch` | `place_of_performance` | `required` | 1 |
| `icp-materials-eu` | `place_of_performance` | `required` | 7 |
| `icp-ppe-safety-ch` | `place_of_performance` | `preferred` | 1 |
| `icp-waste-ch` | `place_of_performance` | `required` | 1 |
| `icp-subcontracting-eu` | `place_of_performance` | `preferred` | 5 |
| `icp-national-supplier` | `either` | `preferred` | 6 |
| `icp-remote-specialist` | `ignore` | `ignored` | 0 |

**0 violation** — aucun ICP de référence n'a dû être modifié, les hashes sont donc préservés.

---

## DECISION / BAND POLICY

Le score numérique est inchangé. La décision est toujours calculée **avant** la bande. Ce qui change,
c'est que la bande est désormais une **lecture de la décision**, et non une seconde opinion calculée
en parallèle sur le seul score.

```
decision = show
    score >= STRONG_BAND      → strong
    sinon                     → promising

decision = borderline
    score >= PROMISING_BAND   → promising
    sinon                     → weak

decision ∈ {exclude, insufficient_data}
                              → excluded
```

Interdiction structurelle : **`decision != show` et `band == strong` est impossible**.

Elle est posée à deux endroits, volontairement :

- dans `MatchingEngine`, la bande est dérivée de la décision — le moteur ne peut plus la produire ;
- dans `ScoredSignalMatch`, un validateur refuse toute combinaison contradictoire — un appelant ne
  peut pas la fabriquer à la main non plus.

Le validateur du modèle couvre les trois cas, pas seulement `strong` : une décision `show` n'accepte
que `strong` ou `promising`, une `borderline` que `promising` ou `weak`, et `exclude` comme
`insufficient_data` imposent `excluded`. La règle préexistante ne couvrait que `exclude`.

### Cas devise non couverte (§4)

Test de non-régression dédié : montant connu, devise sans `ValueThreshold` correspondant, score
suffisant pour franchir `STRONG_BAND`.

| Grandeur | Avant | Après |
|---|---|---|
| score brut et normalisé | inchangé | inchangé |
| points par composant | inchangés | inchangés |
| statut de devise (`currency_unsupported`) | inchangé | inchangé |
| filtre dur | inchangé (non évaluable, aucun échec fabriqué) | inchangé |
| décision | `borderline` | `borderline` |
| **bande** | **`strong`** | **`promising`** |

Seule la bande de présentation bouge, ce qui est exactement le périmètre autorisé par §4.

---

## SCORE POLICY VERSION

```
SCORE_POLICY_VERSION           signal-score-v0.1  →  signal-score-v0.2
MATCH_POLICY_VERSION           icp-match-v0.1        inchangé
MATCH_RUBRIC_VERSION           icp-match-rubric-v1   inchangé
REFERENCE_ICP_LIBRARY_VERSION  reference-icps-v0.1   inchangé
```

Le matching et les décisions ne changent pas ; c'est la sémantique publique de `ScoreBand` qui
évolue, et elle seule.

**Un point à signaler.** Le gold gelé déclare `score_policy_version = "signal-score-v0.1"`, et §1
interdit d'y toucher. La divergence avec la constante courante est donc **voulue et correcte** : le
gold est l'archive datée d'un run, pas un miroir du code. Le test qui vérifiait l'égalité a été
remplacé par un test qui constate la divergence et en explique la raison
(`test_the_gold_keeps_the_score_policy_version_of_its_own_run`). Ce qui doit rester vrai — que les
décisions n'ont pas bougé — est vérifié par le rerun ci-dessous, pas par une égalité de chaîne.

---

## AS_OF AUDIT

Audit déterministe sur les **mêmes 680 paires gelées**, moteur corrigé, en ne faisant varier que la
date de référence.

| Grandeur comparée | `as_of = 2026-08-17` vs `2026-08-20` |
|---|---|
| **score changes** | **0** |
| **band changes** | **0** |
| **decision changes** | **0** |
| **hard-filter changes** | **0** |
| **gold-grade-impacting changes** | **0** |
| **gate changes** | **0** |

Métriques identiques aux deux dates :

```
as_of = 2026-08-17   show precision 100 %   recall 100 %   critical 0   show 57
as_of = 2026-08-20   show precision 100 %   recall 100 %   critical 0   show 57
```

**Pourquoi l'écart de trois jours ne change rien.** Le corpus est bimodal : 45 lots à 83 jours et 40
lots entre 6 et 17 jours au 20 août. Au 17 août ils deviennent 80 jours et 3 à 14 jours. Aucun de ces
déplacements ne franchit un plafond `maximum_signal_age_days` de la bibliothèque (le plus serré est
60 jours, que les 83 comme les 80 jours dépassent déjà), ni une frontière de bande de fraîcheur.

**VERDICT §6 : as_of SANS EFFET — benchmark conservé.**

`2026-08-20` est donc documentée comme **date de référence synthétique fixe** du benchmark. Elle
n'introduit aucune donnée future : le corpus a été acquis le 2026-08-17 et ne contient aucune
publication postérieure à cette date — la date de référence sert uniquement à figer le calcul
d'ancienneté pour que le benchmark reste reproductible quel que soit le jour où on le rejoue. La
publication la plus récente du corpus a 6 jours au 20 août, donc 3 jours au 17 août : à aucun moment
un âge négatif, c'est-à-dire une donnée du futur, n'apparaît.

---

## HELD-OUT NON-REGRESSION

Rerun du moteur corrigé sur les mêmes 680 paires, `as_of = 2026-08-20`.

| Grandeur | Attendu §7 | Mesuré |
|---|---|---|
| **decisions changed** | 0 | **0** |
| **scores changed** | 0 | **0** |
| **bands changed** | libre | **0** |

Décisions produites, identiques au run SPEC-008 : **57 `show`, 37 `borderline`, 420 `exclude`,
166 `insufficient_data`**.

| Métrique | Valeur | Gate |
|---|---|---|
| show precision | **100 %** | ≥ 95 % PASS |
| critical false shows | **0** | = 0 PASS |
| strong-match recall | **100 %** | ≥ 75 % PASS |
| hard-filter violations | **0** | = 0 PASS |
| pairwise ranking | **100 %** | ≥ 90 % PASS |
| macro precision@5 | **100 %** | ≥ 80 % PASS |
| explanation / evidence / component trace | **100 %** chacune | = 100 % PASS |
| determinism | **100 %** | = 100 % PASS |

**Pourquoi 0 bande changée, et pourquoi ce n'est pas un non-événement.** L'incohérence corrigée était
**latente** sur ce held-out, pas active. Les 37 paires `borderline` ont pour scores :

```
46, 48×7, 53×3, 60×4, 66×3, 67×7, 68, 73×11        maximum = 73
```

`STRONG_BAND = 75` : aucune paire `borderline` n'atteignait le seuil, à deux points près. La bande
`strong` hors `show` était donc réelle et atteignable — le test §4 la déclenche avec un montant en
EUR — mais le benchmark gelé ne l'exerçait pas. La correction est un durcissement authentique, et
elle laisse le benchmark strictement identique. Les deux choses sont vraies en même temps.

Une correction de mesure mérite d'être signalée : ma première reconstruction de la règle v0.1
comptait 166 changements `weak → excluded`. C'était un défaut de ma reconstruction, pas du moteur :
en v0.1, un filtre dur bloqué provoquait un retour anticipé qui posait `excluded` en dur, si bien que
`insufficient_data` n'atteignait jamais l'expression de bande. Reconstruction corrigée, le compte
réel est **0**.

---

## TEST RESULTS

```
uv run pytest -q             → 1355 passed
uv run ruff check .          → All checks passed!
uv run ruff format --check . → 139 files already formatted
git diff --check             → propre
```

Les **1 338 tests historiques restent verts**. Les 17 nouveaux :

| Fichier | Tests | Contenu |
|---|---|---|
| `tests/test_matching_coherence.py` | **16** | les 13 cas §8 (le cas « base active + policy ignorée » est paramétré sur ses 3 bases) |
| `tests/test_matching_fixtures.py` | **+1** | le gold conserve la version de politique de son propre run |

Couverture des 13 tests obligatoires §8 :

| §8 | Test | État |
|---|---|---|
| `basis ignore + policy ignored → valid` | `test_ignore_basis_with_ignored_policy_is_valid` | ✅ |
| `basis ignore + required → invalid` | `test_ignore_basis_with_required_policy_is_refused` | ✅ |
| `basis ignore + preferred → invalid` | `test_ignore_basis_with_preferred_policy_is_refused` | ✅ |
| `active basis + ignored policy → invalid` | `test_active_basis_with_ignored_policy_is_refused` ×3 | ✅ |
| `required without territories → invalid` | `test_required_policy_without_territories_is_refused` | ✅ |
| `preferred without territories → invalid` | `test_preferred_policy_without_territories_is_refused` | ✅ |
| `borderline cannot be strong` | `test_a_borderline_signal_is_never_strong` | ✅ |
| `exclude must be excluded band` | `test_an_excluded_signal_carries_the_excluded_band` | ✅ |
| `insufficient_data must be excluded band` | `test_insufficient_data_carries_the_excluded_band` | ✅ |
| `show may be strong` | `test_a_shown_signal_may_be_strong` | ✅ |
| `show may be promising` | `test_a_shown_signal_may_be_promising` | ✅ |
| `unsupported currency cannot produce borderline + strong` | `test_unsupported_currency_cannot_produce_a_strong_band` | ✅ |
| `manual contradictory ScoredSignalMatch → ValidationError` | `test_a_manually_contradictory_result_is_refused` | ✅ |

Méthode : TDD strict. Les 13 tests ont été écrits d'abord, exécutés en RED — **11 échecs, chacun
pour l'absence de l'invariant visé et non pour une erreur de test** — puis le code minimal a été
écrit pour chaque groupe. Les 5 tests verts au premier passage sont les régressions §8 dont le
comportement existait déjà (`ignored` valide, `required` sans territoire, bande `excluded` sur
`exclude`, `show` fort ou prometteur).

Deux tests existants ont dû être adaptés, aucun affaibli :

- `test_adversarial_j` construisait `basis="ignore"` avec la policy `required` par défaut, désormais
  interdite ; le cas est exprimé sous sa configuration cohérente et ses assertions sont inchangées ;
- `test_frozen_gold_declares_policy_versions` a été scindé, la version de politique du gold gelé
  faisant désormais l'objet d'un test qui en explique la divergence.

---

## VERDICT

| Condition §9 | Vérification | ✓ |
|---|---|---|
| configurations géographiques contradictoires impossibles | 2 invariants dans `TargetICP`, 6 tests | ✅ |
| aucune bande `strong` hors décision `show` | invariant dans le moteur **et** dans `ScoredSignalMatch` | ✅ |
| décisions held-out inchangées | **0** changement, 57/37/420/166 | ✅ |
| scores held-out inchangés | **0** changement | ✅ |
| `as_of` n'affecte aucun gate | **0** gate change entre le 17 et le 20 août | ✅ |
| tous les tests restent verts | **1355 passed**, dont les 1 338 historiques | ✅ |

# SPEC-008 DONE

Les métriques finales sur held-out frais et gelé sont inchangées : show precision **100 %**,
strong-match recall **100 %**, critical false shows **0**, hard-filter violations **0**, pairwise
ranking **100 %**, macro precision@5 **100 %**, Evidence **100 %**, component trace **100 %**,
determinism **100 %**.

---

## COMMIT

**Aucun commit effectué** (§10). `git diff --check` est propre, en attente de la revue du superviseur.

Conformément au STOP §10 : SPEC-009 non commencée, pas de benchmark Signal-100, pas de base de
données, pas de SaaS, pas d'auth, pas de frontend, pas d'Acquisition Engine, pas d'Apollo, pas
d'Instantly.
