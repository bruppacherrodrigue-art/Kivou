# Hermes Chief of Staff V1 — conception

Date : 2026-09-15
Base observée : `ef159fa8fcc078f1e85811c76e6cfa2bc60e0eae`

## Décision

Hermes devient un interprète transversal des faits Kivou, sans devenir une
autorité métier. La V1 produit uniquement des briefings `SHADOW` en lecture.
Elle ne dispose d'aucun outil exécutable et ne peut modifier ni policy, ni
gate, ni donnée commerciale, ni fournisseur.

Le contrat Acquisition existant reste inchangé. Un nouveau domaine
`signals.chief_of_staff` possède ses contrats, sa mémoire métier, sa collecte,
sa validation, son service et son stockage. Les deux profils partagent la
frontière technique Hermes (transport isolé, pin, route structurée, absence de
fallback et de retry), pas leurs contextes ni leurs sorties.

## Flux retenu

```text
WeeklyCommercialCockpitService + Founder read models + Operations
  -> projections déterministes et assainies
  -> ChiefOfStaffFact[] + mémoire métier approuvée
  -> ChiefOfStaffContext v2 (UNTRUSTED_DATA, borné, Europe/Zurich)
  -> profil Hermes kivou-chief-of-staff v1.1 en SHADOW, zéro outil
  -> ChiefOfStaffReport strict
  -> validation sémantique fail-closed
  -> rapport append-only/idempotent + journaux modèle et tentative assainie
  -> GET Founder authentifiés
  -> section « Brief d'Hermes » sur Aujourd'hui
```

## Frontières

`facts.py` ne recalcule aucune métrique. Il projette les contrats du cockpit,
de la Founder overview, du statut Acquisition et des opérations. Les montants
restent en unités mineures avec une devise par fait. CHF et EUR ne sont jamais
additionnés. `delivered_proxy_count` conserve
`PROXY_SENT_MINUS_BOUNCE_V1`. Les inconnues et preuves M2 insuffisantes sont
des faits explicites, jamais des zéros.

Les données exclues comprennent adresses email, corps de messages, notes,
texte client ou fournisseur brut, identifiants administrateurs, secrets,
prompts et réponses fournisseur brutes. Les références opaques nécessaires
sont limitées aux `fact_ref`, `source_contract` et références d'incident déjà
assainies.

## Contrats

Tous les modèles sont Pydantic stricts, gelés, `extra="forbid"`, avec dates
timezone-aware et cardinalités bornées.

- `BusinessDecision` : clé, catégorie, déclaration, statut, date d'effet,
  version et source vérifiable.
- `ChiefOfStaffFact` : référence stable, domaine, métrique, valeur typée,
  unité, période, capture, contrat/version source et statut de donnée.
- `ChiefOfStaffContext` : version, génération, timezone, cadence, période,
  versions mémoire/profil, faits, gates, incidents, qualité, statuts de
  capacités et frontière `UNTRUSTED_DATA`.
- `ChiefOfStaffReport` : référence/fingerprint, période, statut exécutif,
  résumé sans chiffres libres, observations, trois priorités au plus, cinq
  décisions au plus, inconnues, sources, confiance et versions.

Les observations, priorités et décisions portent des `reason_codes` et des
`fact_refs`. Les propriétaires sont limités à `FOUNDER`, `ENGINEERING`,
`ACQUISITION`, `PRODUCT`, `DATA` et `NONE`. Une décision demandée est toujours
explicitement humaine.

## Chiffres et texte

Les textes Hermes n'ont pas le droit de contenir de chiffres libres. La
validation refuse les chiffres dans les champs narratifs ; l'UI matérialise
les valeurs depuis les faits cités. Cela évite un rapprochement numérique
fragile et rend l'interdiction vérifiable hors ligne.

## Validation fail-closed

Après la validation Pydantic, le validateur vérifie l'ensemble des références,
les périodes, les versions du profil et du pin Hermes, les limites, les preuves
des statuts critiques, le caractère humain des décisions, la confiance, la
taille, l'absence de PII/secrets/commandes/actions exécutées et l'absence
d'extension de mission. Une violation interdit toute persistance.

Les contenus hostiles sont sérialisés sous `UNTRUSTED_DATA`. Le profil rappelle
qu'ils ne sont jamais des instructions. Les fixtures d'évaluation couvrent les
injections et les références inventées.

## Modèle et budget

L'usage `chief_of_staff` est ajouté à `signals.model_runtime`. Sa route est
configurable par `KIVOU_MODEL_CHIEF_OF_STAFF` et ses trois variables de budget
et réservation. Contrairement aux usages historiques, l'absence de ces quatre
variables laisse le service `NOT_CONFIGURED` : aucune activation implicite.

Une réservation atomique précède l'invocation. Toute erreur finalise le journal
en échec ; une réponse utilisable finalise coût et tokens. L'appel reste unique,
sans fallback et sans retry. Les tests utilisent un transport simulé et aucun
appel OpenRouter réel.

Le verrouillage est appliqué au CLI, à l'adapter et au bridge. L'opération
`report` exige les quatre variables Chief of Staff, une `ModelRoute` d'usage
`chief_of_staff` exactement concordante et un `ModelBudgetStore`. Elle ne peut
jamais utiliser `OPENROUTER_MODEL`. Une construction invalide échoue avant
réservation et avant transport. Le chemin Acquisition `plan` conserve son
comportement historique.

## Persistance et concurrence

Une migration additive après le head Alembic réel crée
`chief_of_staff_report` et `chief_of_staff_attempt`. Le
`context_fingerprint` et les versions pertinentes forment l'identité
sémantique d'un rapport ; un conflit retourne le rapport existant sans le
remplacer. Chaque invocation reçoit néanmoins une tentative terminale
append-only. Elle conserve seulement étapes, codes fermés, route, coût et
versions, jamais prompt, réponse brute, narration, PII ou secret. Le journal
financier modèle reste l'autorité sur le résultat facturé. Aucun `UPDATE` ou
`DELETE` applicatif n'est exposé.

## Durcissement du 2026-09-16

La disponibilité analytique est désormais calculée par Kivou, jamais par le
modèle. Chaque capacité porte un statut `AVAILABLE`, `UNAVAILABLE` ou
`INSUFFICIENT_EVIDENCE`, des raisons fermées et les faits qui justifient le
statut. Business, Data, Operations et Acquisition exigent leur domaine et leur
contrat source déterministe. Strategic Synthesis exige ces quatre capacités.
Product Journey et Roadmap/Release sont `UNAVAILABLE` tant qu'aucun read model
et aucune projection déterministe dédiés ne sont fournis.

Les faits `STALE` sont repris explicitement dans la qualité des données. La
validation interdit aussi les comparaisons quantitatives ou magnitudes en texte
libre (par exemple doublement, majorité, moitié ou forte hausse) : la V1 ne
possède aucun champ structuré permettant à Hermes d'établir ces mesures. Les
observations non inconnues doivent citer une preuve `KNOWN` ou `STALE`, et les
inconnues ne peuvent pas devenir des faits.

La CLI utilise un verrou non bloquant configurable. Elle est dry-run par
défaut ; `--persist` est explicite. Les unités systemd proposées sont des
artefacts non activés : `Type=oneshot`, utilisateur `kivou`, timeout, verrou et
hardening, sans migration ni installation.

## Founder API et Console

Deux GET authentifiés sont ajoutés à l'application Founder existante : latest
et history, avec cadence et limite bornée. Une absence de rapport est un état
vide versionné ; une dépendance absente ou une erreur SQL renvoie 503. Aucune
route n'est ajoutée à l'application client et aucune génération POST n'existe.

La page Aujourd'hui charge le briefing indépendamment de l'overview afin que
son indisponibilité ne masque pas les autres read models. La section française
réutilise les tokens, listes, statuts et responsive existants. Elle offre
chargement, vide, indisponible, périmé et actualisation, sans chatbot ni bouton
d'exécution.

## Évaluation et démonstration

Une fixture versionnée décrit quinze scénarios, leurs faits, statut/domaines/
reason codes attendus, priorités permises et conclusions interdites. La
démonstration locale utilise SQLite et un rapport simulé : contexte,
validation, persistance, GET Founder et rendu frontend, sans donnée réelle ni
réseau fournisseur.

## Hors périmètre

Autonomie, exécution d'actions, planification activée, mémoire Hermes libre,
SQL direct depuis Hermes, mise à jour du pin, déploiement, modification nginx,
pricing/scoring/conformité, agents spécialisés et génération depuis le
navigateur sont exclus.
