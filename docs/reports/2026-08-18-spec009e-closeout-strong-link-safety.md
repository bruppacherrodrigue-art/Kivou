# SPEC-009E CLOSEOUT — Strong Link Safety + Commit Readiness

**Rien n'est committé.** Durcissement ciblé du lien fort, nettoyage du dépôt, et
état exact avant revue. Aucun autre changement.

---

## 1. DURCISSEMENT DU LIEN FORT

`france-link-v0.2` → **`france-link-v0.3`**.

### La règle

```text
strong       parties identiques + date compatible + AU MOINS UN corroborant
             indépendant du CONTRAT
probable     parties identiques + la date OU un corroborant, pas les deux
unresolved   tout le reste — y compris le couple de parties seul
```

```python
INDEPENDENT_CORROBORATORS = frozenset({"cpv", "amount", "contract_reference"})
```

Aucune ressemblance de raison sociale n'entre nulle part — un test le vérifie
sur le contenu même de l'ensemble. Elle n'est ni déterministe ni vérifiable, et
deux établissements d'un même groupe portent souvent le même nom.

### Une précision sur la référence de contrat

`contract_reference` **corrobore quand elle concorde, et se tait sinon**. Les deux
registres formatent le numéro de marché différemment ; une inégalité ne démontre
donc rien, et la compter comme divergence n'aurait produit que du bruit. Une
égalité, en revanche, identifie le contrat lui-même — c'est le corroborant le
plus fort des trois.

### Le contre-exemple qui justifie l'exigence

Le triplet parties + date suffisait tant qu'on supposait qu'un fournisseur ne
gagne qu'un marché par jour chez le même acheteur. Mesuré sur
`decp-2022-marches-valides`, notifications du 2026-06-01 au 2026-08-18, 600
contrats lus :

```text
61 groupes partagent acheteur + titulaire + date de notification + CPV
   et contiennent pourtant PLUSIEURS contrats distincts
```

Le risque n'était pas théorique. Un cas est gelé en fixture :

```text
20261jkav0000000   notif 2026-07-08   85 435 €   CPV 44220000-8   menuiserie plaxée
2026vnpu40000000   notif 2026-07-08   58 325 €   CPV 44220000-8   menuiserie aluminium
                   même acheteur, même titulaire — deux lots, deux marchés
```

---

## 2. GARDE-FOU D'AMBIGUÏTÉ

Aucun contrat n'est fusionné quand deux candidats le valent autant. Tous les
candidats sont **conservés** — les perdre effacerait la preuve qu'un doute
existait — et tous sont déclassés en `probable` avec `ambiguous = True`.

`unique_strong()` est la seule porte vers une fusion : elle rend l'unique
candidat fort, ou `None`. Jamais « le premier de la liste ».

### « Également forts » se mesure, il ne se suppose pas

La première version du garde-fou déclassait dès que deux candidats étaient
forts. Relancée sur données réelles, elle a fait tomber un des quatre liens de
R2 — et l'inspection a montré qu'elle avait tort :

```text
BOAMP 26-79293   référence de marché « 26-011 »   CPV 79952100   signé 2026-08-05

DECP 26-011        notif 2026-08-05   320 000 €   CPV 79952100-3   « ASSISTANCE TECHNIQUE… »
DECP 20262601101   notif 2026-08-05   320 000 €   CPV 79952100-3   « ASSISTANCE TECHNIQUE… »
```

Ce ne sont pas deux marchés : c'est **le même contrat publié deux fois** par
DECP sous deux identifiants, à une coquille près dans l'objet. Et l'un des deux
porte la référence exacte du marché BOAMP.

Le garde-fou ne se déclenche donc que sur une **domination stricte** :

```text
rang de corroboration = (référence de contrat exacte ?, nombre de corroborants)

un seul candidat au rang maximal   → il reste `strong`, les autres deviennent
                                     `probable` (dominés, pas ambigus)
plusieurs à égalité au rang max    → tous déclassés, tous `ambiguous`
```

Un test prouve que le déclassement vient bien de l'ambiguïté et de rien d'autre :
retirer le concurrent de la paire réelle restaure immédiatement le lien fort.

### Régressions demandées par §2

```text
✔ parties + date proche SANS corroborant indépendant        → PAS strong (probable)
✔ corroborant SANS date compatible                          → PAS strong (probable)
✔ deux candidats également corroborés                       → aucun strong, aucun perdu,
                                                              unique_strong() rend None
✔ les 4 liens forts réels de R2                             → restent STRONG
✔ les leurres existants (2021, 2022, 2024)                  → restent rejetés
✔ référence de contrat exacte acceptée comme corroborant    → testée
✔ aucun nom d'entreprise dans les corroborants              → testé sur l'ensemble
```

---

## 3. COMPTAGES APRÈS DURCISSEMENT

Passe relancée sur les 45 award-lots BOAMP à décision récente
(fenêtre 2026-08-11 → 2026-08-18) :

```text
BOAMP candidats testés                    45
  dont testables (2 SIRET)                37     82,2 %
  dont non testables                       8     17,8 %
DECP candidats retournés                   8

STRONG                                     4
PROBABLE                                   1
UNRESOLVED                                32
                                        ────
                                          37     l'agrégat se referme

conflits sur liens forts                   2
leurres rejetés                            2
```

**Identiques à R2** — le durcissement n'a coûté aucun lien légitime.

Les quatre liens forts, tous corroborés indépendamment :

```text
26-79293 → DECP 26-011        CPV + référence de contrat exacte
26-80916 → DECP 26-012        CPV + référence de contrat exacte
26-80736 → DECP 2026F20180    CPV
26-80112 → DECP 202607LOT03   montant  (CPV divergent → conflit diagnostiqué, rien écrasé)

accord CPV                    3 / 4
accord référence de contrat   2 / 4
accord montant                1 / 4
au moins un corroborant       4 / 4
```

Un lien s'est *amélioré* : `26-79293` se résout désormais vers `26-011`, celui
des deux doublons qui porte la référence exacte, au lieu de `20262601101`.

### Capacité France — inchangée

```text
A  bruts       45 décisions BOAMP + 383 notifications DECP   (somme naïve 428 ⚠)
B  uniques     415 à 424 marchés distincts / semaine — aucun milieu
C  livrables   45 / semaine ; 379 notifications DECP restent résolvables
               en interne seulement, faute de nom d'entreprise
```

---

## 4. NETTOYAGE DU DÉPÔT

### Supprimé — artefact de l'expérience DECP erronée

```text
tests/fixtures/france/decp_records.json    0,05 Mo    SUPPRIMÉ
```

Six enregistrements du jeu **hérité** `decp-v3-marches-valides`. Ils étaient
encore lus par `test_source_date_semantics.py`, qui vérifiait « aucun contrat
DECP n'atteint un statut daté » sur la mauvaise source. Le test a été migré vers
`decp2022_records.json` et **renforcé** : il vérifie maintenant, sur le jeu
courant, que l'horloge d'attribution reste `unknown` **et** que l'horloge de
notification parle — ce que l'ancien fixture ne pouvait pas montrer.

### Exclus du commit — régénérables, requis par aucun test

```text
tests/fixtures/france/spec009e_boamp_raw.json      13,86 Mo   .gitignore
tests/fixtures/france/spec009e_decp2022_raw.json    1,99 Mo   .gitignore
```

Vérifié : aucun test suivi ne les lit. Seul `spec009e_run.measure()` les relit,
et `acquire()` les régénère. La mesure dérivée `spec009e_france.json` porte
l'échantillon aplati (`award_lots`) et suffit à rejouer toute l'analyse hors
ligne — c'est bien l'artefact reproductible qui est conservé, pas le gel brut.

```bash
$ git check-ignore -v tests/fixtures/france/spec009e_boamp_raw.json \
                      tests/fixtures/france/spec009e_decp2022_raw.json
.gitignore:11: …spec009e_boamp_raw.json
.gitignore:12: …spec009e_decp2022_raw.json
```

### Conservés

```text
tests/fixtures/france/boamp_records.json          0,04 Mo   test_boamp_adapter, test_source_date_semantics
tests/fixtures/france/decp2022_records.json       0,01 Mo   test_decp2022_adapter, test_source_date_semantics
tests/fixtures/france/boamp_decp2022_link.json    0,14 Mo   test_france_decp_link
tests/fixtures/france/spec009e_france.json        0,86 Mo   test_spec009e_france_study
tests/fixtures/france/spec009e_r2_linkage.json    0,01 Mo   preuve gelée de l'agrégat
                                                 ────────
                                                  1,06 Mo

tests/fixtures/signal100/spec009c_{corpus,bench,gold}.json  11,5 Mo
                                                  test_spec009d_audit — clone frais (R1 §7)
```

Total ajouté au dépôt : **12,6 Mo**, dont 11,5 Mo déjà validés en R1.

---

## 5. ÉTAT EXACT DU DÉPÔT

```bash
$ uv run pytest -q
2026 passed in 16.42s          # 2010 après R2, + 16

$ uv run ruff check .
All checks passed!

$ git diff --check
(rien)

$ uv run ruff format --check .
1 file would be reformatted
  docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md
```

**Tests ignorés : zéro.**

### `git status --porcelain`

```text
INTENTIONNELS — indexés
A  tests/fixtures/france/boamp_decp2022_link.json
A  tests/fixtures/france/boamp_records.json
A  tests/fixtures/france/decp2022_records.json
A  tests/fixtures/france/spec009e_france.json
A  tests/fixtures/france/spec009e_r2_linkage.json
A  tests/fixtures/signal100/spec009c_bench.json
A  tests/fixtures/signal100/spec009c_corpus.json
A  tests/fixtures/signal100/spec009c_gold.json
A  docs/reports/2026-08-18-spec009e-recent-award-france.md
A  docs/reports/2026-08-18-spec009e-r1-current-decp.md
A  docs/reports/2026-08-18-spec009e-r2-multiclock-unique-signals.md
A  docs/reports/2026-08-18-spec009e-closeout-strong-link-safety.md
A  src/signals/connectors/boamp/{__init__,client,parser}.py
A  src/signals/connectors/decp/{__init__,parser}.py
A  src/signals/france/{__init__,capacity,link}.py
A  src/signals/recency/{__init__,claim,policy,sources}.py
A  src/signals/research/spec009e.py
A  src/signals/research/spec009e_run.py
A  tests/test_award_claim_copy.py
A  tests/test_award_recency.py
A  tests/test_boamp_adapter.py
A  tests/test_boamp_client_cursor.py
A  tests/test_contract_notification_date.py
A  tests/test_decp2022_adapter.py
A  tests/test_france_capacity.py
A  tests/test_france_decp_link.py
A  tests/test_source_date_semantics.py
A  tests/test_spec009e_france_study.py
M  .gitignore
M  src/signals/domain/awards.py
M  src/signals/domain/events.py
M  tests/test_model_invariants.py
M  tests/test_spec009d_audit.py

HORS PÉRIMÈTRE — laissés non suivis, jamais indexés
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx      (+ :Zone.Identifier)
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx (+ :Zone.Identifier)
?? docs/reports/2026-08-17-spec006-postmortem.md
?? docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md
?? src/signals/research/spec009c.py
?? src/signals/research/spec009c_run.py
?? tests/test_spec009c_bench.py
?? tests/fixtures/signal100/spec009c_blind.json
?? tests/fixtures/documents/heldout3_gold.json:Zone.Identifier
?? tests/fixtures/documents/heldout3_gold.sha256.txt:Zone.Identifier

IGNORÉS — régénérables
   tests/fixtures/france/spec009e_boamp_raw.json
   tests/fixtures/france/spec009e_decp2022_raw.json
```

Les artefacts SPEC-009C (`spec009c.py`, `spec009c_run.py`,
`test_spec009c_bench.py`, `spec009c_blind.json`, le rapport de banc) restent
**non suivis** : SPEC-009C n'a jamais été autorisée au commit, et seuls les trois
fixtures gelés dont dépend l'audit SPEC-009D entrent, conformément à R1 §7.

### `git diff --stat` (non indexé)

```text
(rien — tout est indexé)
```

### `git diff --cached --stat`

```text
 .gitignore                                       |      6 +
 docs/reports/…spec009e-recent-award-france.md    |    ~880 +
 docs/reports/…spec009e-r1-current-decp.md        |    ~560 +
 docs/reports/…spec009e-r2-multiclock…md          |    ~480 +
 docs/reports/…spec009e-closeout…md               |    ~430 +
 src/signals/connectors/boamp/*                   |    ~700 +
 src/signals/connectors/decp/*                    |    ~330 +
 src/signals/domain/awards.py                     |     21 +-
 src/signals/domain/events.py                     |     10 +-
 src/signals/france/*                             |    ~600 +
 src/signals/recency/*                            |    ~700 +
 src/signals/research/spec009e*.py                |    ~900 +
 tests/test_*.py (10 nouveaux)                    |   ~1900 +
 tests/test_model_invariants.py                   |      5 +-
 tests/test_spec009d_audit.py                     |     27 +-
 tests/fixtures/france/*.json                     |   ~1,1 Mo
 tests/fixtures/signal100/spec009c_*.json         |  363216 +   (11,5 Mo)
```

---

## 6. NON-RÉGRESSION

```text
élément                                état        vérification
multi-clock recency v0.3               inchangé    44 tests, bornes 30/31/60/61
RECENT_AWARD                           inchangé    priorité de dérivation intacte
sémantique de notification             inchangée   recently_notified_contract
formulations / claims                  inchangées  54 tests, 7 états × 2 langues
BOAMP parser                           inchangé    boamp-adapter-v0.1, 21 tests
DECP 2022 adapter                      inchangé    decp-adapter-v0.2, 21 tests
contract_notification_date             inchangé    3 tests dédiés
méthodologie de capacité France        inchangée   17 tests, bornes identiques
Need Graph                             need-graph-v0.2             intact
Matching                               icp-match-v0.2              intact
Signal Score                           signal-score-v0.2           intact
Contract Understanding                 contract-understanding-v0.3 intact
BKP                                    bkp-trade-v0.1              intact
Document Intelligence auto-accept      AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False
Commercial Verifier                    OFF, non touché
golds historiques                      non modifiés
résultat commercial SPEC-009C (64 %)   non re-mesuré, non modifié
commit SPEC-009D (1cd8628)             intact
politique FNSimple / MAPA              inchangée
```

```bash
$ git status --porcelain src/signals/understanding src/signals/needs \
                         src/signals/matching src/signals/documents
(vide)
```

Aucun nouveau benchmark. Aucun enrichissement SIRENE. Aucun travail SaaS.

Seule modification hors du périmètre du lien fort : la migration de
`test_source_date_semantics.py` vers le fixture courant, rendue nécessaire par
la suppression demandée au §4.

---

## 7. CONFIRMATIONS DEMANDÉES

```text
✔ les quatre liens forts réels passent toujours       4/4, tous corroborés
✔ un candidat ambigu ne fusionne jamais                unique_strong() → None,
                                                       les deux candidats conservés
✔ aucun artefact DECP hérité n'est indexé              decp_records.json SUPPRIMÉ
✔ aucun gel brut n'est indexé                          les deux .json en .gitignore,
                                                       git check-ignore le confirme
✔ aucun fichier hors périmètre n'est indexé            10 fichiers restent en `??`
✔ tests ignorés                                        zéro
```

---

## VERDICT

```text
SPEC-009E READY TO COMMIT
```

Le lien fort exige désormais un corroborant indépendant du contrat, l'ambiguïté
bloque toute fusion, et le départage n'a lieu que sur une domination stricte —
règle qui, sur données réelles, distingue un doublon de publication de deux
marchés véritablement distincts. Les quatre liens mesurés en R2 survivent tous,
et l'un s'est corrigé.

Le dépôt est prêt : 2 026 tests verts, zéro ignoré, ruff propre, 12,6 Mo
d'artefacts gelés dont aucun n'est un gel brut régénérable, et aucun fichier
hors périmètre indexé.

**Rien n'est committé.** En attente de votre autorisation.
