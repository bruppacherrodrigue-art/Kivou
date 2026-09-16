# Chief of Staff — métriques et sources V1

| Domaine | Contrat/service autoritaire | Projection |
|---|---|---|
| Business | `WeeklyCommercialCockpitService`, `WeeklyCommercialCockpit` | funnel, MRR par devise, churn, M2, qualité |
| Parcours produit | Aucun read model dédié en V1 | capacité indisponible, aucun faux fait |
| Données | `CockpitDataQuality` | secteurs non résolus, MRR inconnu, preuves M2 |
| Opérations | `OperationsReadService` et Founder system status | santé, readiness, incidents, dead letters, ingestion |
| Acquisition | `FounderAcquisitionStatusReadService` | mode, activité réelle, dernier cycle, timer distinct |
| Release | Aucun read model déployé/versionné dédié en V1 | capacité indisponible, aucun faux fait |

Règles sémantiques : timezone business `Europe/Zurich` ; livraison
`PROXY_SENT_MINUS_BOUNCE_V1` ; CHF/EUR séparés ; montant entier en unité
mineure ; inconnu distinct de zéro ; `INSUFFICIENT_M2_EVIDENCE` conservé ;
activité du service, timer et dernier cycle restent trois faits distincts.

Chaque `fact_ref` est l'empreinte déterministe du contrat source, de la
métrique, de la période et de la dimension. Le Chief of Staff ne lance aucune
requête SQL et ne refait aucun agrégat métier.

## Matrice de disponibilité

| Capacité | Domaines et contrats minimaux | Condition `AVAILABLE` | Sinon |
|---|---|---|---|
| Business Review | `BUSINESS` + `WeeklyCommercialCockpit` | au moins un fait `KNOWN` ou `STALE` | `INSUFFICIENT_EVIDENCE` |
| Product Journey Review | read model produit dédié absent | jamais en V1 | `UNAVAILABLE` / `READ_MODEL_UNAVAILABLE` |
| Data Health Review | `DATA` + `CockpitDataQuality` | au moins un fait `KNOWN` ou `STALE` | `INSUFFICIENT_EVIDENCE` |
| Operations Review | `OPERATIONS` + `AcquisitionOperationalHealth` | au moins un fait `KNOWN` ou `STALE` | `INSUFFICIENT_EVIDENCE` |
| Acquisition Review | `ACQUISITION` + `FounderAcquisitionStatus` | au moins un fait `KNOWN` ou `STALE` | `INSUFFICIENT_EVIDENCE` |
| Roadmap and Release Review | read model release dédié absent | jamais en V1 | `UNAVAILABLE` / `READ_MODEL_UNAVAILABLE` |
| Strategic Synthesis | quatre capacités supportées ci-dessus | toutes `AVAILABLE` | `INSUFFICIENT_EVIDENCE` |

L'ordre est canonique et stable. Les `fact_refs` du statut proviennent
uniquement des sources requises. Aucun texte ou choix de modèle n'intervient
dans cette décision.
