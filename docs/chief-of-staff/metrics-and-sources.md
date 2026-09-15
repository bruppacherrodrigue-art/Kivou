# Chief of Staff — métriques et sources V1

| Domaine | Contrat/service autoritaire | Projection |
|---|---|---|
| Business | `WeeklyCommercialCockpitService`, `WeeklyCommercialCockpit` | funnel, MRR par devise, churn, M2, qualité |
| Parcours produit | Founder overview et tunnel commercial | étapes agrégées, sans identifiant client |
| Données | `CockpitDataQuality` | secteurs non résolus, MRR inconnu, preuves M2 |
| Opérations | `OperationsReadService` et Founder system status | santé, readiness, incidents, dead letters, ingestion |
| Acquisition | `FounderAcquisitionStatusReadService` | mode, activité réelle, dernier cycle, timer distinct |
| Release | Founder system status | SHA déployé seulement s'il est disponible |

Règles sémantiques : timezone business `Europe/Zurich` ; livraison
`PROXY_SENT_MINUS_BOUNCE_V1` ; CHF/EUR séparés ; montant entier en unité
mineure ; inconnu distinct de zéro ; `INSUFFICIENT_M2_EVIDENCE` conservé ;
activité du service, timer et dernier cycle restent trois faits distincts.

Chaque `fact_ref` est l'empreinte déterministe du contrat source, de la
métrique, de la période et de la dimension. Le Chief of Staff ne lance aucune
requête SQL et ne refait aucun agrégat métier.
