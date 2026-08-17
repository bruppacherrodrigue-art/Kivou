# NEED SUPPORT RUBRIC V1 — doctrine d'adjudication du Need Graph

**Version : `need-support-rubric-v1` — SPEC-007R1 §4-§5 — 17 août 2026**

Cette rubrique est la référence unique pour adjuger un besoin candidat. Elle
remplace la doctrine binaire « ≥ 2 faits indépendants », dont l'imprécision a
produit 44 désaccords sur 47 cas entre deux passes d'adjudication : elle ne
disait pas *quels* faits comptaient, ni *pour quoi*.

Toute adjudication — gold comme moteur — applique les quatre dimensions
ci-dessous **dans l'ordre**, à partir des seuls faits canoniques.

---

## 1. Les quatre dimensions

### A. MECHANISM FACT — pourquoi cette ressource peut être nécessaire

Un fait établit que l'exécution de **ce** contrat consomme structurellement ce
type de ressource. Le mécanisme se lit dans la **nature du travail**, jamais
dans sa taille.

### B. PRESSURE FACT — pourquoi une capacité supplémentaire est plausible

Un fait, **distinct du mécanisme**, établit que l'exécution mobilise assez de
ressources pour qu'un appoint externe soit commercialement plausible. La
pression se lit dans l'**échelle, la durée ou la complexité**, jamais dans la
nature du travail.

> Deux faits du même rôle ne se cumulent jamais. « Type construction » et
> « CPV 45 » sont deux représentations du même mécanisme, pas un mécanisme plus
> une pression.

### C. DELIVERABLE OVERLAP — le besoin n'est pas le livrable

La catégorie candidate ne doit pas être ce que le gagnant s'est déjà engagé à
fournir. Un transporteur n'a pas besoin de transport ; un fournisseur
d'équipements n'a besoin ni d'équipements ni de composants.

### D. COMMERCIAL SPECIFICITY — une offre B2B réelle existe

La catégorie doit être assez précise pour désigner un fournisseur identifiable
(loueur de matériel, négoce de matériaux, agence d'intérim, collecteur de
déchets…). « Support opérationnel » ou « ressources » ne le sont pas.

---

## 2. Vocabulaire déterministe des faits

### 2.1 Bandes d'échelle

Calculées sur le montant publié, **sans aucune conversion** :

| Bande | Condition |
|---|---|
| `not_material` | montant en EUR/CHF < 50 000 |
| `modest` | 50 000 ≤ montant < 1 000 000 (EUR/CHF) |
| `large` | 1 000 000 ≤ montant < 10 000 000 (EUR/CHF) |
| `very_large` | montant ≥ 10 000 000 (EUR/CHF) |
| `unknown` | montant absent, ou devise hors EUR/CHF |

`known_nontrivial_scale` = `modest`, `large` ou `very_large`.
`large_scale` = `large` ou `very_large`.

Un montant `not_material` (26 EUR, 538 RON…) ne soutient **jamais** un besoin :
il peut être un prix unitaire, une donnée source aberrante ou un micro-marché.
Diagnostic : `scale_not_material`. Un montant en devise non comparable ne
constitue **pas** une pression : `scale_unavailable`.

### 2.2 Faits de MÉCANISME (rôle A)

Un seul par catégorie suffit ; ils viennent du **type de contrat** et, pour la
construction, du **profil CPV**.

| Catégorie | Mécanisme reconnu |
|---|---|
| `workforce_capacity` | type à intensité humaine : construction, facility_services, security_services, social_health_services, transport_logistics, maintenance_repair |
| `equipment_or_rental` | construction de profil `earthworks` ou `building_civil` ; transport_logistics (flotte) |
| `materials_or_components` | construction de profil `building_civil`, `technical_installation` ou `finishing` |
| `logistics_and_transport` | fourniture avec distribution structurée **démontrée par les faits** (voir §4.3) |
| `specialist_subcontracting` | construction, engineering_architecture, it_digital — travaux à spécialités séparables |
| `safety_and_ppe` | construction (obligations de sécurité de chantier) |
| `waste_and_environment` | construction de profil `earthworks`, `building_civil` ou `finishing` (déblais, gravats) |

### 2.3 Faits de PRESSION (rôle B)

Liste **exhaustive** ; tout ce qui n'y figure pas n'est pas une pression.

| Fait de pression | Condition canonique |
|---|---|
| `large_scale` | bande `large` ou `very_large` |
| `known_nontrivial_scale` | bande `modest`, `large` ou `very_large` |
| `long_recurring_duration` | type de service récurrent **et** durée publiée ≥ 12 mois |
| `parallel_lots_with_scale` | `several_lots` **et** `known_nontrivial_scale` |
| `distinct_specialties` | groupement (`consortium_award`) ou `multiple_contractors` |
| `near_term_start` | date de début publiée, à ≤ 90 jours de la publication |

### 2.4 Faits qui ne sont **jamais** une pression (§11-§12)

`defined_contract_period` (fait temporel), `several_lots` seul (fait
structurel), présence d'un CPV, présence d'un montant, fait d'avoir remporté le
marché. Un montant `not_material` ou `unknown` n'est pas davantage une pression.

---

## 3. Profils de ressources CPV — construction (§13)

Le type canonique `construction` couvre des chantiers dont les intrants n'ont
rien de commun. Profil déterministe par préfixe CPV, mesuré sur le corpus :

| Profil | Préfixes | Corpus | Intrants crédibles |
|---|---|---|---|
| `earthworks` | 451 | 1 | engins, déchets/déblais, personnel, EPI |
| `building_civil` | 452 | 12 | engins, matériaux, déchets, personnel, EPI |
| `technical_installation` | 453 | 2 | composants, personnel, EPI — **pas** de gros engins |
| `finishing` | 454 | 3 | matériaux, déchets, personnel, EPI — **pas** de gros engins |
| `general_or_unknown` | 450 et tout autre | 7 | personnel, EPI uniquement — **ni engins ni matériaux** |

Un chantier dont le CPV ne dit pas la nature des travaux ne permet pas
d'affirmer qu'il mobilise des engins : `general_or_unknown` **supprime**
`equipment_or_rental` et `materials_or_components` (§14).

---

## 4. Politiques par type de contrat

### 4.1 social_health_services (§15)

Le type est un mécanisme de capacité humaine. Mais `medium` exige une pression
réelle : `large_scale`, **ou** la combinaison `long_recurring_duration` +
`known_nontrivial_scale`. `defined_contract_period` ne compte jamais. Un lot de
22 k à 185 k EUR reste `plausible_but_weak`.

### 4.2 construction

`equipment_or_rental` exige un profil `earthworks` ou `building_civil`
**et** `known_nontrivial_scale`. `materials_or_components` exige un profil
`building_civil`, `technical_installation` ou `finishing`. `workforce_capacity`
et `safety_and_ppe` acceptent tous les profils, mais toujours avec une pression
distincte.

### 4.3 medical_supply et equipment_supply (§16)

La livraison est **inhérente** à une fourniture : elle ne constitue pas un
besoin logistique supplémentaire. En mode `metadata_fallback`, aucun fait
canonique ne démontre une distribution structurée au-delà du livrable →
`logistics_and_transport` est **supprimé** pour ces types.

### 4.4 Recouvrement avec le livrable (§17)

| Type de contrat | Catégories interdites |
|---|---|
| `transport_logistics` | `logistics_and_transport` |
| `equipment_supply` | `equipment_or_rental`, `materials_or_components`, `logistics_and_transport` |
| `medical_supply` | `materials_or_components`, `logistics_and_transport` |

---

## 5. Les trois états

### `supported`

Les quatre conditions tiennent : mécanisme **oui**, pression **oui**,
recouvrement **non**, spécificité **oui**. C'est le seul état qui autorise un
besoin `medium` en sortie.

### `plausible_but_weak`

Le mécanisme existe et le recouvrement est absent, mais la pression n'est pas
établie (échelle inconnue, non matérielle, ou seulement des faits structurels
ou temporels). Ne doit **jamais** être retourné comme besoin `medium` : peut
produire un candidat `low`, supprimé.

### `forbidden`

Au moins une de ces situations : contradiction avec le contrat ; répétition du
livrable ; mauvais type de projet (mécanisme absent) ; catégorie sans mécanisme
pour ce contrat ; besoin commercialement absurde ; montant manifestement trop
faible pour porter le raisonnement ; timing inventé ; externalisabilité
suraffirmée.

> Un besoin `plausible_but_weak` produit en sortie est une **imprécision**.
> Un besoin `forbidden` produit en sortie est une **faute** (critical false
> need). Les deux ne se comptent jamais ensemble (§6).

---

## 6. Procédure d'adjudication

Pour chaque award-lot, et pour chacune des sept catégories :

1. **Mécanisme ?** Le type (et le profil CPV pour la construction) figure-t-il
   au tableau 2.2 ? Sinon → `forbidden` (catégorie sans mécanisme).
2. **Recouvrement ?** La catégorie figure-t-elle au tableau 4.4 pour ce type ?
   Si oui → `forbidden`.
3. **Pression ?** Au moins un fait du tableau 2.3, distinct du mécanisme,
   tient-il ? Sinon → `plausible_but_weak`.
4. **Spécificité ?** La catégorie désigne-t-elle une offre B2B réelle ? Sinon →
   `forbidden`.
5. Sinon → `supported`.

Les politiques du §4 s'appliquent en priorité sur cette procédure générale.

---

## 7. Cas travaillés (issus des erreurs mesurées)

| Cas réel | Adjudication | Motif |
|---|---|---|
| Construction 1 686 397 CHF, CPV 45000000, sans caractéristique | `equipment_or_rental` = **forbidden** | profil `general_or_unknown` : aucun mécanisme d'engins (§14) |
| Construction 1 686 397 CHF, même contrat | `workforce_capacity` = **supported** | mécanisme (type humain) + pression (`large_scale`) |
| Social health 45 666 EUR, `several_lots`, `defined_period` | `workforce_capacity` = **plausible_but_weak** | mécanisme oui ; aucune pression : lots et période exclus (§11-§12, §15) |
| Medical supply 26 EUR, `several_lots` | `logistics_and_transport` = **forbidden** | recouvrement livrable (§16) **et** `scale_not_material` |
| Transport 538 RON, `several_lots` | `workforce_capacity` = **plausible_but_weak** | mécanisme oui ; échelle `unknown` (RON) → pas de pression |
| Construction 4 500 000 CHF, CPV 45210000 (452) | `materials_or_components` = **supported** | mécanisme `building_civil` + pression `large_scale` |
| Construction 298 925 CHF, CPV 45232140 (452), `several_lots` | `equipment_or_rental` = **supported** | mécanisme `building_civil` + pression `parallel_lots_with_scale` |
