# SCORE COMPONENT STUDY — SPEC-008 §23

**Mesurée sur les 100 award-lots réels de Contract-100**, passés par le moteur
de compréhension (`contract-understanding-v0.1`) puis par le Need Graph
(`need-graph-v0.1` / `need-rules-v0.4`). Aucun chiffre théorique.

## 1. Ce que les données offrent réellement

| Fait | Disponibilité | Conséquence |
|---|---|---|
| Besoins produits | 67 award-lots sur 100 en portent au moins un (0 : 33, 1 : 33, 2 : 10, 3 : 24) | un tiers du corpus ne peut structurellement matcher aucun ICP |
| Catégories produites | workforce 44, subcontracting 35, equipment 23, materials 16, safety 7 | `waste_and_environment` et `logistics_and_transport` : **0** — voir §5 |
| Lieu d'exécution | 82/100, **tous avec pays** | géographie exploitable au niveau pays |
| Subdivision du lieu | **0/100** | le matching infranational est impossible sur ce corpus |
| Pays de l'acheteur | 100/100 | disponible mais ce n'est pas le lieu d'exécution |
| Adresse du gagnant | **0/100** | voir §3 |
| Pays du gagnant | **0/100** | voir §3 |
| Montant publié | 91/100 — bandes : modest 51, unknown 21, large 18, not_material 7, very_large 3 | composant économique exploitable, avec 21 % d'inconnu |
| Date de publication | 100/100 | fraîcheur exploitable partout |
| Timing des besoins | unknown 98, recurring 18, immediate 9 (sur 125 besoins) | **78 % d'inconnu** : le timing seul ne peut pas porter un composant |
| Confiance des besoins | `medium` pour les 125 besoins | **constante** en mode metadata — voir §4 |

## 2. Composants candidats

| Composant | Faits disponibles | Valeur commerciale | Risque de double comptage | Verdict | Points |
|---|---|---|---|---|---|
| **need / offer fit** | catégories de besoin exactes, primaire vs secondaire | Très élevée — c'est la question même du produit | Aucun s'il reste seul à lire les catégories | **KEEP** — composant dominant (§24) | **45** |
| **economic impact** | montant + devise, bandes d'échelle | Élevée — un marché de 2,4 MCHF n'est pas un marché de 60 k | Réel : SPEC-007 utilise déjà l'échelle pour *produire* le besoin. Le score la relit pour *qualifier l'opportunité* — une seule fois côté score. Aucun autre composant ne touche au montant | **KEEP** | **20** |
| **geography** | pays du lieu d'exécution (82 %), pays de l'acheteur (100 %) | Élevée — une offre locale hors zone est inactionnable | Réel si la géographie servait aussi de hard filter *et* de points. Résolu : `required` filtre (hard), `preferred` marque des points, jamais les deux | **KEEP** | **20** |
| **freshness + timing** | date de publication (100 %), `NeedTiming` (78 % inconnu) | Moyenne-élevée — un signal de six mois est mort commercialement | Réel entre fraîcheur et timing : partagent un composant unique, plafonné, sans cumul du même avantage (§24) | **KEEP fusionné** | **15** |
| **winner / ICP fit** | **aucun** : 0 adresse, 0 pays sur 100 gagnants | Élevée en théorie | — | **REMOVE** (§14) | **0** |
| **data / inference confidence** | `medium` pour 100 % des besoins | Nulle en tant que score : une constante ne discrimine rien | Deviendrait un décalage uniforme, donc un proxy du score général — explicitement interdit (§24) | **REMOVE du score**, rapporté séparément (§26) | **0** |

**Total : 100 points avant normalisation N/A.**

## 3. Pourquoi `winner_fit` disparaît

La roadmap historique lui accordait 20 %. La mesure est sans appel : sur les 100
award-lots, **aucun** ne publie l'adresse ni le pays du gagnant — la résolution
d'entreprise (SPEC-004) donne une identité, pas une implantation. Fabriquer un
`winner_fit` reviendrait à noter une dimension vide, ou à déduire l'industrie du
gagnant depuis son nom, ce que le §13 interdit.

Conséquence pratique sur la géographie : `geography_basis = winner_location`
reste **modélisable et configurable**, mais produira systématiquement
`insufficient_data` tant qu'aucun enrichissement d'entreprise n'existe. Le
modèle le permet, les données ne le portent pas encore ; le comportement est
testé explicitement.

## 4. Pourquoi `confidence` sort du score

En mode `metadata_fallback`, tous les besoins portent `medium` : intégrer la
confiance au score ajouterait la même constante à chaque signal, sans jamais
séparer deux candidats. Ce serait exactement le « proxy du score général »
proscrit au §24. La confiance reste donc **une dimension affichée à côté du
score** (§26), plafonnée à `medium`, jamais fondue dedans.

## 5. Deux catégories sans production sur DEV

Le Need Graph ne produit aujourd'hui **aucun** besoin
`waste_and_environment` (écarté par le ranking top-3) ni
`logistics_and_transport` (sans règle en v0.4, §16 de SPEC-007R1). Un ICP de
référence ciblant ces familles est néanmoins requis (§31) : il servira de
contrôle négatif — il doit produire zéro `show` sans lever d'erreur, et le
rapport final doit le dire plutôt que de le masquer.

## 6. Redistribution par rapport à la roadmap historique

| Composant | Roadmap | SPEC-008 | Motif |
|---|---|---|---|
| need / offer fit | 30 | **45** | doit dominer (§24) ; absorbe une part des points libérés |
| winner / ICP fit | 20 | **0** | aucune donnée (§14) |
| economic impact | 15 | **20** | données solides (91 %) |
| geography | 15 | **20** | données solides au niveau pays (82 %) |
| freshness / timing | 10 | **15** | fusionnés, plafonnés ; la fraîcheur porte l'essentiel puisque 78 % des timings sont inconnus |
| data / inference confidence | 10 | **0** | constante, donc non discriminante (§24, §26) |

Les 30 points libérés (winner fit + confidence) sont répartis sur les quatre
dimensions réellement mesurables, en respectant la contrainte de dominance du
besoin.

## 7. Normalisation N/A

Une dimension **non applicable à l'ICP** sort du dénominateur (§22) :
`geography_policy = ignored` retire ses 20 points du maximum applicable, et le
score normalisé se calcule sur 80. Une dimension **applicable mais non
satisfaite** reste au dénominateur et rapporte zéro. Aucun point n'est jamais
accordé par défaut à une préférence non configurée.
