# Award & Sales Signals

Exploitation des **adjudications publiques** (Suisse via SIMAP, Union européenne via
TED) pour produire des signaux commerciaux actionnables.

Ce dépôt contient le **modèle canonique des faits publics** : ce qu'une adjudication
affirme, et d'où l'information vient. Il ne contient volontairement ni inférence
commerciale, ni scoring, ni matching ICP — ceux-ci consommeront ce modèle depuis
un moteur séparé.

## État

**SPEC-001 — modèle canonique `PublicEvent` / `ContractAward`.**

Pas encore de connecteur, pas encore de persistance : le modèle est pur Python
(Pydantic v2) et se teste sans base ni Docker.

## Principes

| Règle | Traduction dans le code |
|---|---|
| Source-agnostique | SIMAP et TED sont des connecteurs ; ajouter un portail = ajouter une valeur à `SourceSystem` |
| Faits ≠ inférences | seuls des faits publiés ici ; aucun besoin commercial supposé |
| Provenance obligatoire | `Provenance` isolée de la donnée métier, `EventRef` rattache chaque contrat |
| Rien d'inventé | tout champ inconnu reste `None` ; `winner_status` distingue *inconnu* de *absent* |
| Déterministe | dates, montants, devises, CPV normalisés sans LLM ; `Money` refuse le flottant |
| Certitude ≠ heuristique | `source_identity()` = ce que la source identifie (ou `None`) ; `dedupe_fingerprint()` = piste de rapprochement, jamais une clé d'unicité |
| Précision préservée | `published_at` reste une `date` ou un `datetime` selon ce que la source publie — ni minuit inventé, ni heure tronquée |

## Développement local (uv)

```bash
uv sync
uv run pytest
uv run ruff check .
```

## Structure

```
src/signals/domain/
  values.py   objets-valeur : Money, CpvCode, Location, Duration, OrganizationRef
  events.py   PublicEvent, Provenance, EventRef
  awards.py   ContractAward, Awardee, LotRef
tests/
  test_spec001_scenarios.py   les 8 scénarios obligatoires de SPEC-001
  test_model_invariants.py    ce que le modèle refuse
```
