# Kivou

**Kivou** exploite les **adjudications publiques** (Suisse via SIMAP, Union
européenne via TED) pour produire des signaux commerciaux actionnables.

Le paquet Python reste `signals` : le nom de code du produit a changé, pas
l'espace de noms du code.

Ce dépôt contient le **modèle canonique des faits publics** : ce qu'une adjudication
affirme, et d'où l'information vient. Il ne contient volontairement ni inférence
commerciale, ni scoring, ni matching ICP — ceux-ci consommeront ce modèle depuis
un moteur séparé.

## État

**SPEC-001** — modèle canonique `PublicEvent` / `ContractAward`.
**SPEC-002** — connecteur TED (Search API v3 + eForms).
**SPEC-003** — connecteur SIMAP (API publique simap.ch v1.5.1).
**SPEC-004** — Winner Resolution : mentions publiées → entités entreprises.
**SPEC-005** — Contract Understanding + Evidence : ce que l'avis permet de comprendre, et pourquoi.

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
| Fait ≠ interprétation | `ContractUnderstanding` est une couche dérivée ; l'award reste le fait brut |
| Rien sans preuve | une affirmation `high`/`medium` sans `Evidence` est refusée par le modèle |
| Précision > rappel | une mention ambiguë devient `review_required`, jamais une entreprise vérifiée |
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
uv run python -m signals.connectors.simap.live_smoke --limit 40 --since 2026-07-01 --link
uv run python -m signals.resolution.live_smoke --benchmark
uv run python -m signals.resolution.live_smoke --zefix
```

Appelle l'API publique TED, télécharge les XML, les traduit et imprime les
statistiques d'extraction. `pytest` n'y touche jamais : la suite est hors ligne.

## Structure

```
src/signals/domain/            le modèle canonique — ignore que TED existe
  values.py   objets-valeur : Money, CpvCode, Location, Duration, OrganizationRef
  events.py   PublicEvent, Provenance, EventRef
  awards.py   ContractAward, AwardeeParty, Awardee, LotRef, SourceIdentity
  companies.py  Company — l'entité résolue, à CÔTÉ de la mention source
  evidence.py   Evidence — d'où vient une information (champ, texte, registre, document)
src/signals/connectors/ted/    traduit eForms VERS le canonique, jamais l'inverse
  client.py   HTTP : Search API v3 + XML des notices (seul module réseau)
  parser.py   XML eForms → graphe TED (hors ligne)
  mapping.py  graphe TED → PublicEvent + ContractAward[]
  codes.py    tables de codes (pays alpha-3 → alpha-2)
  live_smoke.py
src/signals/connectors/simap/   traduit le modèle SIMAP VERS le canonique
  client.py   HTTP : project-search + publication-details (seul module réseau)
  parser.py   JSON SIMAP → modèle SIMAP (hors ligne, montants en Decimal exact)
  mapping.py  modèle SIMAP → PublicEvent + ContractAward[]
  live_smoke.py
src/signals/resolution/         mention publiée → entité juridique
  normalize.py   formes de comparaison (noms, adresses) — jamais d'affichage
  identifiers.py force d'un identifiant : officiel / local à la source / non attribué
  resolver.py    moteur déterministe et traçable, aucune fusion par le nom
  registries.py  VIES (public) et Zefix (AUTH REQUIRED)
  live_smoke.py
src/signals/understanding/    ce que l'avis permet de comprendre du contrat
  cpv.py       CPV → type de contrat / secteur (déterministe, testé)
  text.py      HTML publié → texte lisible, sans perte
  model.py     ContractUnderstanding, Claim (fait source vs affirmation dérivée)
  engine.py    moteur déterministe ; protocole ouvert à un moteur linguistique
tests/
  test_spec001_scenarios.py   les 8 scénarios obligatoires de SPEC-001
  test_model_invariants.py    ce que le modèle refuse
  test_ted_connector.py       vraies notices TED, hors ligne
  test_ted_client.py          contrat HTTP, transport simulé
  test_simap_connector.py     vraies publications simap.ch, hors ligne
  test_simap_client.py        contrat HTTP, transport simulé
  fixtures/ted/               notices TED réelles + 1 fixture synthétique signalée
  test_resolution.py          moteur de résolution, hors ligne
  test_resolution_adversarial.py  pièges à fusion abusive
  test_winner100_benchmark.py     100 mentions réelles + vérité terrain indépendante
  fixtures/simap/             réponses simap.ch réelles, octets bruts
  fixtures/vies/              réponses VIES réelles
  test_evidence.py            la preuve canonique
  test_contract_understanding.py  tables CPV, texte, modèle, moteur
  test_understanding_adversarial.py  pièges à sur-interprétation
  test_contract100_benchmark.py      100 contrats réels
  fixtures/winner100/         benchmark Winner-100 + gold labels
  fixtures/contract100/       benchmark Contract-100
```
