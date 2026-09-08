# SPEC-005 — Contract Understanding + Award Evidence

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:test-driven-development` pour chaque tâche. Étapes en cases à cocher.

**Goal:** Dériver des awards existants une compréhension structurée du contrat, chaque affirmation importante étant reliée à une preuve traçable.

**Architecture:** Deux modèles neufs et séparés — `Evidence` (canonique, source-agnostique, dans `signals.domain`) et `ContractUnderstanding` (couche dérivée, dans `signals.understanding`). Le `ContractAward` reste le fait brut et n'est jamais modifié. La classification est **déterministe** (CPV d'abord), avec un protocole permettant de brancher plus tard un moteur linguistique.

**Tech Stack:** Python 3.12, Pydantic v2, aucune dépendance nouvelle.

**Spec:** SPEC-005 (message du superviseur, 2026-08-16)

## Global Constraints

- `ContractAward`, `PublicEvent`, `Money`, `Company`, `AwardeeParty`, `Provenance` : **interdiction de modifier**. Sinon → `SPEC-005 BLOCKED — EXISTING DOMAIN CHANGE REQUIRED`.
- Aucun besoin commercial, aucun Need Graph, aucun ICP (§26).
- Aucun document de marché téléchargé ou analysé (§27).
- Aucune persistance, aucun ORM, aucune migration (§41).
- Toute donnée dérivée porte `engine_version` (§25).
- `Evidence` est immuable (§40).
- Les tests ne sortent jamais sur le réseau.

## Décisions prises à partir du corpus réel (168 awards)

| Question | Mesure | Décision |
|---|---|---|
| Signal de classification | **CPV présent sur 168/168** ; titres souvent inutilisables (`Default lot`, `Lote 1`, `Reihen`) | CPV = signal primaire, titre = confirmation |
| LLM nécessaire ? | CPV suffit pour le type ; le résumé peut être composé de faits publiés | **Non.** Déterministe (§42). Protocole prévu pour plus tard |
| `economic_scale` ? | **8 devises** (EUR, CHF, RON, HUF, NOK, SEK, PLN, CZK), médianes de 4 530 RON à 620 000 CHF, conversion interdite (§11) | **Non créé.** Seuils cross-devises indéfendables |
| Caractéristiques observables | lot 125/168, durée publiée 74, groupement 2, multi-titulaires 1 | uniquement celles reliées à un fait publié |

## File Structure

```
src/signals/domain/evidence.py          Evidence, SourceKind — canonique, source-agnostique
src/signals/understanding/__init__.py   surface publique
src/signals/understanding/model.py      ContractUnderstanding, Claim, ContractType, Sector, Confidence
src/signals/understanding/cpv.py        tables CPV → type / secteur (déterministes, testées)
src/signals/understanding/text.py       HTML → texte, déterministe et réversible
src/signals/understanding/engine.py     ContractUnderstandingEngine + protocole de moteur
tests/test_evidence.py
tests/test_contract_understanding.py
tests/test_understanding_adversarial.py
tests/test_contract100_benchmark.py
tests/fixtures/contract100/awards.json  100 awards réels + étiquettes de revue
```

---

### Task 1 : `Evidence` canonique

**Files:** Create `src/signals/domain/evidence.py`, `tests/test_evidence.py`

**Interfaces produites :** `SourceKind`, `Evidence(source_system, source_kind, source_notice_id?, source_procedure_id?, source_url?, path?, raw_value?, excerpt?, retrieved_at?, engine_version?)`, `Evidence.is_derived`.

- [ ] Test : une preuve de champ conserve `path` et `raw_value` sans les réécrire
- [ ] Test : une preuve dérivée porte `engine_version` et `source_kind="derived"`
- [ ] Test : une preuve est immuable (frozen)
- [ ] Test : `source_kind="tender_document"` est accepté sans migration (readiness SPEC-006)
- [ ] Test : une preuve de fait source ne peut pas porter `engine_version`
- [ ] Implémenter, formater, lint

### Task 2 : tables CPV

**Files:** Create `src/signals/understanding/cpv.py`, test dans `tests/test_contract_understanding.py`

**Interfaces produites :** `contract_type_for(cpv: str) -> ContractType`, `sector_for(cpv: str) -> Sector`, `CPV_TYPE_RULES`.

- [ ] Test : `45215100` → `construction` ; `72267100` → `it_digital` ; `33600000` → `medical_supply`
- [ ] Test : `85321000` → `social_health_services` (secteur santé, type services) — §6
- [ ] Test : le préfixe le plus long gagne (`79710000` → `security_services`, pas `business_services`)
- [ ] Test : un code inconnu → `unknown`
- [ ] Implémenter

### Task 3 : nettoyage HTML déterministe

**Files:** Create `src/signals/understanding/text.py`

- [ ] Test : `<p>A</p><p>B</p>` → deux paragraphes séparés, rien perdu
- [ ] Test : `<li>` devient une liste lisible
- [ ] Test : `&nbsp;` et `&amp;` sont décodés une fois, pas deux
- [ ] Test : un texte cyrillique traverse intact
- [ ] Test : le texte source reste disponible non modifié
- [ ] Implémenter

### Task 4 : modèle `ContractUnderstanding`

**Files:** Create `src/signals/understanding/model.py`

**Interfaces produites :** `ContractType`, `Sector`, `Confidence`, `Claim(value, confidence, evidence[], rule?)`, `ContractUnderstanding(award_ref, source_system, contract_type, sector, object_summary, characteristics[], geography, timing, evidence_coverage, engine_version)`.

- [ ] Test : un `Claim` sans preuve est refusé quand sa confiance n'est pas `low`
- [ ] Test : `evidence_coverage` = claims prouvés / claims matériels, formule documentée
- [ ] Test : `ContractUnderstanding` porte toujours `engine_version`
- [ ] Implémenter

### Task 5 : moteur déterministe

**Files:** Create `src/signals/understanding/engine.py`, `__init__.py`

**Interfaces produites :** `ContractUnderstandingEngine.understand(award, event) -> ContractUnderstanding`, protocole `UnderstandingModel`.

- [ ] Test : award SIMAP réel → type `construction`, preuve CPV + titre
- [ ] Test : CPV et titre concordants → confiance `high` ; CPV seul → `medium`
- [ ] Test : contradiction CPV/titre → confiance abaissée, jamais `high`
- [ ] Test : titre vide + CPV absent → `unknown`/`low`
- [ ] Test : chaque fait critique (winner, montant, CPV, dates, buyer, lot) porte sa preuve
- [ ] Test : le résumé ne contient jamais de formulation de besoin (§38)
- [ ] Implémenter

### Task 6 : benchmark Contract-100

**Files:** Create `tests/fixtures/contract100/awards.json`, `tests/test_contract100_benchmark.py`

- [ ] Construire le corpus : 100 awards réels, ~50 TED / ~50 SIMAP, diversité imposée par §45
- [ ] Test : composition (sources, pays, types, multi-lot, valeur absente)
- [ ] Test : 0 mauvaise classification `high` connue
- [ ] Test : couverture des preuves des claims matériels = 100 %
- [ ] Test : aucun résumé ne contient de besoin commercial

### Task 7 : tests adversariaux (§37)

**Files:** Create `tests/test_understanding_adversarial.py`

- [ ] A CPV construction / titre ambigu → construction
- [ ] B titre « maintenance informatique » / CPV générique → compris
- [ ] C CPV et titre contradictoires → confiance réduite
- [ ] D « cloud » dans une formation → pas d'infrastructure cloud
- [ ] E valeur énorme, description vide → aucune intensité déduite
- [ ] F gagnant en groupement → compréhension inchangée
- [ ] G HTML SIMAP → résumé propre, rien d'inventé
- [ ] H texte non latin → aucune corruption
- [ ] I description très longue → résumé factuel
- [ ] J titre promotionnel → aucune inférence commerciale

## Self-Review

- **Couverture de la spec** : §3-§13 → Tasks 2-5 ; §14-§22 → Tasks 1, 4, 5 ; §28-§32 → Task 6 ; §37-§39 → Tasks 5, 7. §11 `economic_scale` : décision documentée de ne pas le créer. §8/§42-§43 LLM : décision documentée de ne pas en utiliser, protocole prévu.
- **Types** : `Claim`, `Evidence`, `ContractType`, `Sector`, `Confidence` nommés identiquement dans toutes les tâches.
- **Pas de placeholder** : chaque tâche a ses tests nommés.
