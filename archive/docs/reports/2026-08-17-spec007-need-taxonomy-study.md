# NEED TAXONOMY STUDY — SPEC-007 §9

**Corpus analysé : Contract-100** (100 adjudications réelles — 55 SIMAP + 45 TED,
19 pays), passées dans le `ContractUnderstandingEngine` de production
(`contract-understanding-v0.1`). Aucune donnée théorique : chaque chiffre
ci-dessous vient de ce corpus.

## 1. Ce que les métadonnées offrent réellement

| Dimension | Mesure corpus |
|---|---|
| Types de contrat | 12 familles : construction 25, engineering_architecture 13, it_digital 12, equipment_supply 11, transport_logistics 10, facility_services 8, medical_supply 7, social_health_services 6, energy_utilities 3, security_services 2, business_services 2, telecom 1 |
| Secteur | `unknown` 56/100 — le secteur est un signal FAIBLE, inutilisable comme condition principale |
| CPV | présent 100/100 (divisions dominantes : 45, 71, 60, 72, 90, 33, 85) |
| Montant | présent 91/100 ; devises : CHF 55, EUR 24, RON 7, NOK 2, PLN/HUF/CZK 1 — **79 % en EUR/CHF comparables** |
| Multi-lot (`several_lots`) | 57/100 |
| Durée publiée | 31/100 (médiane 12 mois) ; `long_duration` (≥ 24 mois) : 12 |
| Date de début | **8/100** — le timing sera massivement `unknown` (§19 : award_date ≠ start) |
| Framework agreement | **0/100** — aucune règle ne peut s'y adosser dans ce corpus |
| Multi-site explicite | **non exposé** par le modèle canonique — indisponible |
| Consortium / multi-contractors | 3/100 |
| Lieu d'exécution | 82/100 ; pays acheteur 100/100 |
| Maintenance / support / supply+installation | non exposés comme caractéristiques ; seul le CPV (division 50 → `maintenance_repair`) porte ce trait |

Conséquences structurantes :
- l'« échelle économique » est définissable par **seuils par devise** sur
  EUR/CHF uniquement (large ≥ 1 000 000, modest sinon) ; autre devise →
  `unknown` (12 contrats) — aucune conversion inventée ;
- le **timing** honnête est `unknown` dans ~90 % des cas ; `recurring` n'est
  déductible que d'un type service + durée publiée ;
- les règles ne peuvent PAS s'appuyer sur : multi-site, framework, phase
  d'implémentation, composant support — invisibles dans le canonique.

## 2. Familles candidates × corpus (§10)

| Candidate | Contrats couverts (types) | Utilité commerciale | Risque de fausse inférence | Verdict |
|---|---|---|---|---|
| **workforce_capacity** | ~51 : construction 25, transport 10, facility 8, social_health 6, security 2 (types à intensité humaine) | Très élevée — intérim, staffing, capacité | Élevé si fondé sur le montant seul → règle exige type à intensité humaine + 2ᵉ fait (§15) | **KEEP** |
| **equipment_or_rental** | construction 25, transport 10 (matériel, engins, véhicules) | Élevée — loueurs BTP, matériel | Moyen — interdit sur prestation intellectuelle/logicielle (§15) | **KEEP** |
| **materials_or_components** | construction 25 (négoce matériaux) | Élevée | Moyen — interdit quand le deliverable EST la fourniture (equipment/medical_supply) §11 | **KEEP** |
| **logistics_and_transport** | equipment_supply 11, medical_supply 7 (distribution multi-lots), construction (évacuation) | Élevée | Moyen — interdit pour transport_logistics (deliverable) §11 | **KEEP** |
| **specialist_subcontracting** | construction/engineering/IT de grande échelle avec multi-lots ou consortium | Élevée | Élevé — §15 exige PLUSIEURS indices ; règle à 3 conditions | **KEEP** |
| **safety_and_ppe** | construction 25 (EPI de chantier, obligation réglementaire) | Élevée — vendeurs EPI | Faible sur construction, élevé ailleurs → restreint au BTP | **KEEP** |
| **waste_and_environment** | construction 25 (évacuation de déchets de chantier) | Moyenne-élevée — collecteurs BTP | Moyen — interdit quand CPV 90 est le deliverable | **KEEP** |
| it_software_or_cloud | it_digital 12 : répétition du deliverable ; ailleurs : aucune trace canonique | Faible en metadata_fallback | Très élevé | **REJECT** (V0) |
| cybersecurity_and_compliance | aucun CPV cyber dans le corpus ; « sécurité explicitement visible » n'existe pas en métadonnées | — | Anti-rule §15 explicite | **REJECT** (V0) |
| maintenance_and_support | le support du livrable incombe au gagnant (deliverable-adjacent) ; aucun trait canonique | Moyenne | Élevé | **REJECT** (V0) |
| training_and_enablement | idem — aucune trace canonique d'un volet formation | Moyenne | Élevé | **REJECT** (V0) |
| facility_services | base-vie de chantier : purement spéculatif en métadonnées | Faible | Élevé | **REJECT** |
| other | non vendable par définition | — | — | **REJECT** |

## 3. Taxonomie V0 retenue — 7 catégories

`workforce_capacity`, `equipment_or_rental`, `materials_or_components`,
`logistics_and_transport`, `specialist_subcontracting`, `safety_and_ppe`,
`waste_and_environment`.

Chacune correspond à une offre B2B réelle (intérim/staffing, location de
matériel, négoce de matériaux, transport/distribution, sous-traitance
spécialisée, EPI, gestion de déchets). Les catégories rejetées le sont pour une
raison mesurée : soit invisibles dans le canonique (cyber, formation,
implémentation), soit deliverable-adjacentes (IT, maintenance), soit non
vendables (other).

## 4. Anti-inférences structurelles (§11, §15) issues du corpus

- `transport_logistics` → jamais `logistics_and_transport` (deliverable) ;
- `equipment_supply` → jamais `equipment_or_rental` ni `materials_or_components` ;
- `medical_supply` → jamais `materials_or_components` ;
- prestation intellectuelle (`engineering_architecture`, `business_services`,
  `research`, `financial_insurance`) et logiciel (`it_digital`) → jamais
  `equipment_or_rental` ;
- `workforce_capacity` → jamais sur le montant seul ; jamais formulé
  « recrutement » (le gagnant peut recruter, intérimer, réaffecter ou
  sous-traiter) ;
- `specialist_subcontracting` → jamais sans au moins trois indices convergents ;
- montant en devise non EUR/CHF → échelle `unknown`, jamais « large ».
