# SPEC-007 — Need Graph V0 — RAPPORT FINAL

**Kivou — 17 août 2026 — metadata-first, document-ready**

# SPEC-007 NOT DONE

Le held-out atteint **60,0 % de précision** (15 besoins soutenus sur 25) contre
90 % exigés, et **1 critical false need** contre 0 exigé. Le DEV passait ses
neuf gates (précision 100 %) : l'écart DEV → held-out est un sur-ajustement des
deux itérations de règles autorisées.

---

## FILES CHANGED

| Fichier | Nature |
|---|---|
| `src/signals/needs/__init__.py` | **Nouveau** — façade du package |
| `src/signals/needs/model.py` | **Nouveau** — `ResourceNeed`, `NeedGraphResult`, `SuppressedCandidate`, taxonomies, invariants |
| `src/signals/needs/features.py` | **Nouveau** — extraction déterministe, échelle économique, politique de timing |
| `src/signals/needs/rules.py` | **Nouveau** — bibliothèque de 10 règles + table de recouvrement deliverable |
| `src/signals/needs/engine.py` | **Nouveau** — pipeline candidats → gardes → preuves → dédup → ranking → top 3 |
| `tests/test_need_model.py` | **Nouveau** — 20 tests d'invariants du modèle |
| `tests/test_need_engine.py` | **Nouveau** — 24 tests moteur (features, timing, génération, dédup) |
| `tests/test_need_adversarial.py` | **Nouveau** — 29 tests, cas A-L + wording + non-régression SPEC-006 |
| `tests/fixtures/needs/need100_heldout_corpus.json` | **Nouveau** — held-out gelé (40 lignes / 29 notices) |
| `tests/fixtures/needs/need100_heldout_gold.json` | **Nouveau** — gold gelé + journal |
| `tests/fixtures/needs/need100_dev.json` | **Nouveau** — DEV + gold DEV + journal |
| `tests/fixtures/needs/need100_{dev,heldout}_run_2026-08-17.json` | **Nouveau** — résultats bruts des runs |
| `docs/reports/2026-08-17-spec007-need-taxonomy-study.md` | **Nouveau** — étude de taxonomie (§9) |

Aucun modèle existant modifié (`ContractAward`, `ContractUnderstanding`,
`Evidence`, `ExecutionRequirement`… intacts) — §42 respecté.

## NEED GRAPH MODEL

```
ResourceNeed          category · statement · reasoning · timing · externalisability
                      confidence · evidence_refs[] · supporting_facts[] · rule_ids[]
                      source_mode · engine_version
NeedGraphResult       award_ref · source_mode · needs[] · suppressed_candidates[]
                      warnings[] · engine_version
SuppressedCandidate   category · rule_id · reason
```

Invariants portés **par le type**, pas par un filtre aval : `high` n'existe pas
dans `NeedConfidence` ; un besoin sans règle, sans preuve ou sans deux faits
indépendants (pour `medium`) ne se construit pas ; le vocabulaire de certitude
(`will buy`, `va recruter`, `besoin confirmé`…) est refusé à la validation ; le
raisonnement doit porter un marqueur hypothétique ; `NeedGraphResult` refuse
plus de 3 besoins, un besoin `low`, ou deux besoins de même catégorie.

## SOURCE MODE POLICY

`metadata_fallback` **utilisé** ; `document_supported` **réservé, jamais
produit**. Chaque `ResourceNeed` porte son mode. Aucun code du package ne
mentionne `signals.documents` (test dédié) ; `derive()` n'accepte qu'un
`ContractUnderstanding` (test de signature).

## NEED TAXONOMY STUDY

Livrée : `docs/reports/2026-08-17-spec007-need-taxonomy-study.md`, fondée sur
les 100 ContractUnderstandings réels de Contract-100. Mesures structurantes :
CPV 100/100 ; montant 91/100 dont **79 % en EUR/CHF** (seuils comparables sans
conversion) ; secteur `unknown` 56/100 (écarté) ; multi-lot 57/100 ; durée
31/100 ; **date de début 8/100** ; **framework 0/100** et **multi-site absent du
canonique** — deux familles candidates éliminées faute de faits.

## FINAL NEED TAXONOMY (7)

`workforce_capacity`, `equipment_or_rental`, `materials_or_components`,
`logistics_and_transport`, `specialist_subcontracting`, `safety_and_ppe`,
`waste_and_environment`.

Rejetées avec motif mesuré : `it_software_or_cloud` et `maintenance_and_support`
(adjacentes au deliverable), `cybersecurity_and_compliance` et
`training_and_enablement` (aucune trace canonique), `facility_services`
(spéculatif), `other` (non vendable).

## RULE LIBRARY — `need-rules-v0.3` · engine `need-graph-v0.1`

Dix règles déclaratives (dataclasses gelées) : `workforce-construction-large-v1`,
`workforce-recurring-service-v1`, `workforce-transport-v1`,
`equipment-construction-large-v1`, `equipment-transport-fleet-v1`,
`materials-construction-v1`, `logistics-supply-distribution-v1`,
`subcontracting-large-multilot-v1`, `safety-ppe-construction-v1`,
`waste-construction-large-v1`.

Chacune porte : `rule_id`, catégorie, types de contrat requis, prédicats
supplémentaires, minimum requis, gabarits de formulation, politique
d'externalisabilité.

**Itérations (2 sur 2 consommées, guidées par le DEV uniquement)**
1. Retrait d'`equipment_supply` de la règle logistique (le type mélange
   grossistes — dont la livraison *est* le métier — et fabricants) ; ajout de
   `several_lots` aux matériaux et au personnel des services ; version v0.2.
2. Prédicat `lots_with_known_scale` : un découpage en lots ne dit rien de la
   charge quand le montant n'est pas comparable (huit micro-marchés de
   transport en RON étaient pris pour des besoins de personnel) ; version v0.3.

## NEGATIVE RULES

- **Recouvrement deliverable** (table `DELIVERABLE_OVERLAP`) : `transport_logistics`
  → jamais logistique ; `equipment_supply` → ni équipement ni composants ;
  `medical_supply` → jamais composants. Les candidats sont supprimés avec le
  motif `deliverable_overlap`.
- **Indice unique** : le type seul ne produit jamais un besoin — motif
  `single_indicator`, visible en diagnostic.
- **Anti-inférences structurelles** : pas de personnel sur le seul montant (le
  type doit être à intensité humaine) ; pas d'équipement ni de matériaux pour
  une prestation intellectuelle ou un pur logiciel ; sous-traitance à deux
  indices minimum en plus du type ; aucune catégorie cyber/IT dans la
  taxonomie ; aucun vocabulaire de recrutement (`workforce_capacity` est le
  concept canonique).

## CONFIDENCE POLICY

`medium` = au moins deux faits indépendants ; `low` = un indice, jamais retourné
en sortie principale ; `high` **inexistant** en mode metadata. Mesuré : **0
besoin `high` sur les deux splits**.

## TIMING POLICY

Référence = `published_at`. `start − published ≤ 30 j` → `immediate` ; `31-90 j`
→ `near_term` ; `> 90 j` → `medium_term` ; service récurrent (facility,
security, social-health, maintenance, transport) à durée publiée ≥ 12 mois →
`recurring` ; sinon `unknown`. La date d'adjudication n'est **jamais** traitée
comme un début (test dédié). Mesuré : **0 timing faux** sur les deux splits.

## EXTERNALISABILITY POLICY

`likely_internal` / `mixed` / `external_plausible` / `unknown` — jamais
`certainly_external`. `external_plausible` exige ≥ 3 faits distincts, sinon
rétrogradé en `mixed` par le moteur. Mesuré : **0 suraffirmation**.

## EVIDENCE / RULE TRACE

Chaque besoin référence les `Evidence` des **claims d'entrée** (type, montant,
lot, durée…) — jamais une preuve du futur ; le passage du fait à l'hypothèse
vit dans `reasoning`. Couverture preuve **100 %**, couverture rule trace
**100 %** sur les deux splits.

## DEV SET

60 lignes / 46 notices (SIMAP 29, TED 31), 26 contrats éligibles.

## DEV RESULTS (après itération 2)

| Métrique | Valeur | Gate | |
|---|---|---|---|
| Besoins générés | 24 | | |
| Soutenus / non soutenus | 24 / 0 | | |
| **Précision** | **100 %** | ≥ 90 % | ✅ |
| Critical false needs | 0 | = 0 | ✅ |
| Couverture éligibles | 69,2 % (18/26) | ≥ 60 % | ✅ |
| Timing (correct/unknown/faux) | 5 / 19 / 0 | ≥ 90 % | ✅ |
| Suraffirmations externalisabilité | 0 | = 0 | ✅ |
| Preuve / rule trace | 100 % / 100 % | = 100 % | ✅ |
| Besoins high en mode metadata | 0 | = 0 | ✅ |
| Max besoins par contrat | 3 | ≤ 3 | ✅ |
| Candidats supprimés | 121 | | |

**DEV PASS — 9/9.**

## HELD-OUT COMPOSITION

40 lignes / 29 notices (SIMAP 26, TED 14), **aucune notice commune avec le DEV**
(vérifié : le tri déterministe par `sha256(award_ref.key())` regroupe les lots
d'une même notice du même côté). 16 contrats éligibles. Gold : PASS A (10 lots)
puis PASS B en aveugle sur les 47 cas éligibles des 100 ; consolidation
`supported = A∩B`, `forbidden = A∪B`, timing recalculé par la règle §19 ;
**21 corrections journalisées** côté held-out.

## HELD-OUT CORPUS SHA256

`373adf9651399888b3d41e20515360dd758678a4ccaf75fc54597fdb034a692d`

## HELD-OUT GOLD SHA256

`62fd70e709c4bee45d0b441509ccb3df0fb1d535e6c11af51b06d7110401f152`

## HELD-OUT RESULTS

| Métrique | Valeur | Gate | |
|---|---|---|---|
| Contrats évalués | 40 | | |
| Besoins générés | 25 | | |
| Soutenus / non soutenus | 15 / 9 | | |
| **Précision** | **60,0 %** | ≥ 90 % | ❌ |
| **Critical false needs** | **1** | = 0 | ❌ |
| Couverture éligibles | 75,0 % (12/16) | ≥ 50 % | ✅ |
| Timing (correct/unknown/faux) | 3 / 22 / 0 — précision 100 % | ≥ 90 % | ✅ |
| Suraffirmations externalisabilité | 0 | = 0 | ✅ |
| Couverture preuve | 100 % | = 100 % | ✅ |
| Couverture rule trace | 100 % | = 100 % | ✅ |
| Besoins high en mode metadata | 0 | = 0 | ✅ |
| Besoins par contrat (moyenne / médiane non vide / max) | 0,62 / 1 / 3 | ≤ 3 | ✅ |
| Candidats supprimés | 48 | | |

### Le critical false need (listé individuellement, §33)

**`simap:a5eca0c9-2bcb-4e01-9651-f0a311af2972` (ligne 83)** — construction,
1 686 397 CHF, aucune caractéristique publiée. Le moteur produit
`equipment_or_rental` ; le gold l'interdit explicitement (`gold_forbidden`) et
ne soutient que `workforce_capacity`. Cause : la règle
`equipment-construction-large-v1` traite « grande échelle » comme suffisant,
alors que le gold distingue les chantiers mobilisant des engins de ceux
mobilisant surtout de la main-d'œuvre — distinction que le type `construction`
seul ne porte pas.

### Les 9 non soutenus, par motif

- **5 × `workforce_capacity` sur `social_health_services`** (lignes 35-39,
  22 k à 185 k EUR) : la règle accepte `defined_period` comme second fait ; le
  gold juge ces micro-marchés d'aide sociale sans pression d'effectifs.
- **3 × `materials_or_components` sur `construction`** (16, 83, 88) : le gold y
  voit du personnel, des engins ou des EPI, pas des matériaux.
- **1 × `logistics_and_transport` sur `medical_supply`** (28, 26 EUR) : montant
  dérisoire — le gold ne soutient aucun besoin.

## ADVERSARIAL RESULTS

29 tests, **tous verts** : A (contrat opaque → 0 besoin) · B (nettoyage → jamais
« nettoyage », seulement le personnel) · C (logiciel → cyber structurellement
impossible) · D (fournitures → pas de personnel sur le montant) · E
(construction multi-lots → équipement soutenu par ≥ 2 faits, classé par
ranking) · F (conseil → pas de location d'équipement) · G (pas de date début →
`unknown`) · H (récurrent/démarré → `recurring`/`immediate`) · I (répétition du
deliverable → supprimée avec motif) · J (sorties expérimentales SPEC-006 →
jamais consommées) · K (langue non FR/EN → faits canoniques seuls) · L (deux
règles, même catégorie → un besoin, tous les `rule_ids`).

## SPEC-006 NON-REGRESSION

`AUTO_DOCUMENT_REQUIREMENTS_ENABLED is False` vérifié par test ; aucun fichier
de `src/signals/needs/` n'importe `signals.documents` (test dédié) ;
`NeedGraphEngine.derive` n'accepte qu'un `ContractUnderstanding` (test de
signature). Le commit SPEC-006 `74b03a85` n'a pas été touché.

## TEST RESULTS

`uv run pytest -q` : **1 216 tests verts** (1 144 historiques + 72 nouveaux) ·
`uv run ruff check .` : propre · `uv run ruff format --check .` : propre ·
`git diff --check` : propre. Aucun commit (§46).

## OPEN QUESTIONS

1. **Le gold est-il la bonne cible ?** Les deux passes d'adjudication ont
   divergé sur 44 des 47 cas éligibles — non par erreur, mais parce que la
   règle « ≥ 2 faits indépendants » ne dit pas *combien de catégories* un même
   couple de faits peut soutenir. J'ai tranché par consensus (`A∩B`) et
   prudence (`A∪B`) et journalisé les 49 corrections, mais un gold construit
   sur une doctrine plus explicite (par exemple : une liste ordonnée
   d'intrants par type de contrat, validée une fois pour toutes) serait plus
   stable — et déplacerait probablement la précision held-out.
2. **`several_lots` et `defined_contract_period` sont-ils des faits de charge ?**
   Les deux itérations ont montré que non quand l'échelle est inconnue ; le
   held-out montre que `defined_period` seul ne suffit pas non plus sur les
   services sociaux. Un prédicat « échelle connue ET non négligeable » serait
   plus juste que la binarité actuelle large/modest.
3. **`construction` est trop large.** Le held-out le prouve : gros œuvre,
   installations électriques et rénovation appellent des intrants différents,
   mais partagent un seul type canonique. La division CPV (45.1 terrassement,
   45.3 installations…) est disponible et autorisée par §14 — non exploitée ici
   pour rester sur la taxonomie de SPEC-005.
4. **Le corpus porte des lots, pas des contrats** : 100 lignes pour 75 notices.
   Les métriques « par contrat » comptent donc des lots. Le split respecte
   §28 (aucune notice commune), mais une future SPEC devrait décider si le Need
   Graph raisonne par lot ou par procédure.

**LLM EXTENSION MAY BE REQUIRED** — non déclenchée : le moteur déterministe
atteint 100 % de précision sur le DEV. L'écart held-out s'explique par la
granularité des règles et la stabilité du gold, pas par un manque de
compréhension textuelle.
