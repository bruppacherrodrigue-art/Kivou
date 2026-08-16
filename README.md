# Award & Sales Signals

Exploitation des **adjudications publiques** (Suisse via SIMAP, Union européenne via
TED) pour produire des signaux commerciaux actionnables.

Ce dépôt contient le **modèle canonique des faits publics** : ce qu'une adjudication
affirme, et d'où l'information vient. Il ne contient volontairement ni inférence
commerciale, ni scoring, ni matching ICP — ceux-ci consommeront ce modèle depuis
un moteur séparé.

## État

**SPEC-001** — modèle canonique `PublicEvent` / `ContractAward`.
**SPEC-002** — connecteur TED (Search API v3 + eForms).

Pas encore de persistance : tout est en mémoire, testable sans base ni Docker.

## Principes

| Règle | Traduction dans le code |
|---|---|
| Source-agnostique | SIMAP et TED sont des connecteurs ; ajouter un portail = ajouter une valeur à `SourceSystem` |
| Faits ≠ inférences | seuls des faits publiés ici ; aucun besoin commercial supposé |
| Provenance obligatoire | `Provenance` isolée de la donnée métier, `EventRef` rattache chaque contrat |
| Rien d'inventé | tout champ inconnu reste `None` ; `winner_status` distingue *inconnu* de *absent* |
| Déterministe | dates, montants, devises, CPV normalisés sans LLM ; `Money` refuse le flottant |
| Groupement explicite | `AwardeeParty` : plusieurs titulaires indépendants ne deviennent jamais un consortium |
| Certitude ≠ heuristique | `source_identity()` = ce que la source identifie (ou `None`) ; `dedupe_fingerprint()` = piste de rapprochement, jamais une clé d'unicité |
| Précision préservée | `published_at` reste une `date` ou un `datetime` selon ce que la source publie — ni minuit inventé, ni heure tronquée |

## Développement local (uv)

```bash
uv sync
uv run pytest
uv run ruff check .
```

## Smoke test live TED (volontaire, hors suite de tests)

```bash
uv run python -m signals.connectors.ted.live_smoke --days 10 --limit 25
```

Appelle l'API publique TED, télécharge les XML, les traduit et imprime les
statistiques d'extraction. `pytest` n'y touche jamais : la suite est hors ligne.

## Structure

```
src/signals/domain/            le modèle canonique — ignore que TED existe
  values.py   objets-valeur : Money, CpvCode, Location, Duration, OrganizationRef
  events.py   PublicEvent, Provenance, EventRef
  awards.py   ContractAward, AwardeeParty, Awardee, LotRef, SourceIdentity
src/signals/connectors/ted/    traduit eForms VERS le canonique, jamais l'inverse
  client.py   HTTP : Search API v3 + XML des notices (seul module réseau)
  parser.py   XML eForms → graphe TED (hors ligne)
  mapping.py  graphe TED → PublicEvent + ContractAward[]
  codes.py    tables de codes (pays alpha-3 → alpha-2)
  live_smoke.py
tests/
  test_spec001_scenarios.py   les 8 scénarios obligatoires de SPEC-001
  test_model_invariants.py    ce que le modèle refuse
  test_ted_connector.py       vraies notices TED, hors ligne
  test_ted_client.py          contrat HTTP, transport simulé
  fixtures/ted/               notices TED réelles + 1 fixture synthétique signalée
```
