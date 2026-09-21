# Milo Mail census: préparation d'un recensement réel

Base observée : `c1a20674369a35a93313edf2ea47c97bb018654a` (PR #279 fusionnée).

| Besoin | Composant Kivou | Écart ciblé |
| --- | --- | --- |
| Découverte et reprise | `CensusRunner`, `CensusStore`, Apollo adapters | deux phases et permis par appel |
| Crédit et coût | réservations `acquisition_census_call`, `CensusLimits` | prix attesté et plafond du permis |
| Preuve d'activité | `ProgramDiscoveryPipeline.company_activity`, API Annuaire déjà utilisée dans `companies` | recherche officielle et rapprochement conservateur |
| Décision | ruleset `MILOMAIL_GMAIL_AUDIT_B2B`, runtime SHADOW | aucune modification de la politique d'envoi |
| Suppression | `MilomailShadowRuntime` | contrôle dans le préflight |
| Base et migrations | Alembic `0071`, schéma Core | migration additive `0072`, autorisation explicite |

La source officielle choisie est l'API Recherche d'entreprises de l'Annuaire des
Entreprises, opérée par la DINUM, qui agrège SIRENE et RNE. L'état administratif
de l'unité légale est distinct de celui du siège. Le rapprochement par nom seul
n'est jamais suffisant ; SIREN exact ou plusieurs éléments concordants uniques
sont nécessaires. Une réponse indisponible, ambiguë ou périmée mène à HOLD.

L'API Apollo facture la recherche d'organisations par page. La phase de
couverture peut donc coûter des crédits : elle exige un permis, même sans
enrichissement. Le prix monétaire par crédit dépend du contrat ; aucun montant
ne sera codé en dur. Un opérateur devra fournir une attestation datée de son
plan et du prix avant tout run.

Ordre : tests de preuve officielle ; client/cache et matching ; tests des permis ;
migration et réservation transactionnelle ; préflight et phases ; tests de
migration, lint, mypy, docs ; PR. Aucun appel Apollo réel durant ce lot.
