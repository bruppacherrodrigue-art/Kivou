# Prospecting V11 — matrice de recette Q01–Q32

## Référence et règle de lecture

Cartographie établie le 13 septembre 2026 sur le worktree `feat/prospecting-v11-staging`, base `2599d77840c073086051cbaa95441caf170afeac`. Les changements V11 sont encore ceux du worktree : ce SHA de base **n’est pas présenté comme un SHA candidat déployé**.

Plan relu : `/home/jaybe/projects/kivou-implementation-plan-2026-09-13/index.html`, section Q01–Q32 ; SHA256 vérifié `5a535272a41ccf6a18fb0717ce6a7b0a9b5983472310653795be39f4aaf0c233`.

Les noms ci-dessous sont ceux réellement présents dans les fichiers, y compris les intitulés historiques « drawer » de tests aujourd’hui portés sur V11. Leur présence a été vérifiée automatiquement. Les noms paramétrés conservent leur modèle exact ; les variantes utiles sont précisées.

**Aucun Q n’est coché globalement.** « Preuves connues » distingue exécution locale, inspection statique, navigateur avec API simulée et opérations staging. La colonne textuelle « Reste staging » n’est pas une exécution. Les nombres de suites se recouvrent et ne doivent pas être additionnés. Aucun paiement réel, email commercial ni appel fournisseur consommant un quota n’a été effectué pour cette recette.

## Registre des preuves

| Réf. | Exécution ou inspection effectivement connue | Limite / artefact |
| --- | --- | --- |
| F1 | Suite frontend générale finale : **752/752**, 73 fichiers, en 59,79 s. | `/tmp/kivou-v11-frontend-release-gate.log` relu ; `npm test -- --run --maxWorkers=2`, code 0 rapporté par root et résumé du log vérifié. Remplace le précédent run 743 réussis/1 échec du garde CSS avant correction de `::backdrop`. |
| F3 | Session/logout, checkout et Provider : 72/72, 4 fichiers, puis TypeScript non incrémental et ESLint verts. | Commande C3 ; résultat terminal observé avant gel React. Inclut les deux courses tardives `/me` et le retour checkout froid sans Provider préexistant. |
| F4 | L10/L11 ciblés : Entreprises/dossier/annuaire/contact 29/29 ; enrichissement/dossier/détail signal/checkout 31/31 lors de la dernière correction de suppression Apollo. | Exécutions terminal observées, pas un nouveau run dans cette tâche documentaire. Inclut CAS contact, refus de lookup, adressage exact et non-résurrection des coordonnées. |
| F5 | Nettoyage CSS final : 53/53 dans 9 fichiers, puis TypeScript non incrémental et ESLint verts ; `git diff --check` vert. | Commande C5, session terminal 44106 terminée avec code 0. Deux tests de retraite observés RED puis GREEN. Audit AST : 287 règles exclusives retirées / 1 925 lignes ; 708 règles conservées strictement identiques, règles mixtes intactes. Module Dashboard inutilisé supprimé. |
| F6 | Billing/upgrade : 165/165 à deux workers après portage des anciennes suites ; contrats retour compte+TTL, prix API et action explicite. | Exécution ciblée terminal antérieure à l’ajout du dernier test de retour froid, couvert ensuite dans F3. Aucun checkout externe réel. |
| F7 | Courses d’intégration Q07/Q10 : 3/3, un fichier, en 4,71 s ; TypeScript non incrémental, ESLint ciblé et diff check verts. | `src/prospecting/__tests__/navigation-races.test.tsx`, commande C7. Deux variantes pagination (annuaire et prospection), puis A→B tardif. Réponses HTTP volontairement résolues après abort ; aucun code produit modifié. |
| B1 | Dernier gate backend général **interrompu** : 454 réussis, cinq erreurs de fixture, en 140,89 s ; aucune validation globale. | `/tmp/kivou-v11-backend-release-gate.log` relu. Les cinq erreurs de `test_accounts_signal_binding.py` proviennent d'un setup historique descendant depuis0060, dont le downgrade est volontairement interdit ; correction de fixture confiée au propriétaire backend, nouveau run complet requis. L'ancien run `/tmp/kivou-v11-backend-final-20260913.log` (5 978 réussis, un échec, 32 skips, un xfail) reste historique, pas une preuve finale verte. |
| B2 | Migrations peuplées + audit identité : 26/26 en 21,54 s, SQLite **et** PostgreSQL 16 jetable. | `/tmp/kivou-v11-migrations-identity-final-20260913.log` relu. Commande C2. Six scénarios migration et sept cas audit exécutés sur les deux moteurs. Ce n’est pas la base vive staging. |
| B3 | Concurrence identité : **6/6** SQLite/PostgreSQL en 1,68 s ; validation finale identité **85/85**, sans skip, en 123,70 s. | Logs relus : `/tmp/kivou-v11-identity-lock-sqlite-pg-green-20260913.log` et `/tmp/kivou-v11-identity-lock-final-20260913.log`. Mutex transactionnel PostgreSQL avant alias puis compte ; SQLite prend son verrou d'écriture avant lecture via UPDATE sans ligne modifiée. Verrou compte PostgreSQL `FOR NO KEY UPDATE`, compatible avec le `KEY SHARE` d'une FK workflow déjà prise. Tests des deux sens quarantaine/réconciliation et ordres opposés sans deadlock ; aucune concurrence staging provoquée. |
| B4 | Helper de restauration : **35/35**, sans skip, en 54,40 s sur SQLite et PostgreSQL jetable local ; Ruff et compilation Python verts. | `tests/test_staging_rehearsal_checks.py`, commande C4. URL copie exclusive, baseline compte et descendants FK, migration/audits, notes2000/CAS/tombstones/statuts/export intercompte, sélection des quatre avis et reprise max3/idempotence. Deux nouveaux RED→GREEN : retour `contacted→new` avec `contacted_at` et export conservés, projection `unified_status=new`, rejet d'un writer qui efface l'historique. Données synthétiques et lecteur BOAMP injecté : ni restauration staging ni requête fournisseur dans ces tests. |
| V1 | Recette navigateur finale : **32/32**, aucun échec, flaky ou skip ; 1 worker, environ 1,3 min. | Rapport `frontend/playwright-report/index.html` relu : stats total=32, expected=32, unexpected=0, flaky=0, skipped=0 ; `frontend/test-results/.last-run.json` indique passed. 21 comparaisons pixels inchangées, 6 parcours V11, 5 contrats/utilitaires ; 24 captures `output/playwright/v11-*.png`. Aucun golden modifié. API interceptée avec données de test, pas staging. |
| O1 | Garde nginx réellement répété sur hôte staging : dix assertions de statut 503/204 réussies, sidecar isolé `127.0.0.1:18083`. | Exécuté par root : `python3 /tmp/kivou-v11-guard.QKFv6V/nginx-guard-probe.py`. Copies locales `output/playwright/nginx-guard-test.conf` et `nginx-guard-probe.py`. Start puis quit en finally, configuration active non remplacée. Preuve JSON agrégée à joindre par root. **Ce n’est pas un rollback live.** |

Le précédent run navigateur 29/32 comportait trois timeouts de chargement sous forte contention, sans différence de pixels rapportée. V1 le remplace après exécution isolée ; aucun seuil ni golden n’a été assoupli.

Les six noms de parcours V1 sont :

- `V11 desktop paid complete three-tab flow`
- `V11 desktop discovery complete three-tab flow`
- `V11 mobile paid complete three-tab flow`
- `V11 mobile discovery complete three-tab flow`
- `V11 mobile320 paid complete three-tab flow`
- `V11 mobile320 discovery complete three-tab flow`

Ils correspondent à 1440×1000, 390×844 et 320×740, chacun en payant et Découverte. Le helper `expectNativeFocusTrap` contrôle le modal natif, le focus initial, Tab/Shift+Tab, l’absence de focus sur le fond inerte, puis Escape et le retour au déclencheur. Le test contrôle aussi un seul main/h1, l’absence de débordement global, les filtres annuaire et back/forward signal↔entreprise.

## Matrice

### Q01 — Compte neuf/profil provisoire

Attendu du plan : Aujourd’hui utile, onboarding préservé, aucun faux chiffre.

Tests présents :

- [frontend/src/pages/dashboard.test.tsx](../../../frontend/src/pages/dashboard.test.tsx) — `affiche les états vides et le titre de première visite`.
- [frontend/src/pages/ConfirmProfile.test.tsx](../../../frontend/src/pages/ConfirmProfile.test.tsx) — `préremplit un profil kat1 avec le département et la famille du signal`.
- [tests/test_dashboard.py](../../../tests/test_dashboard.py) — `test_fresh_account_without_any_signal_sees_an_empty_dashboard`.

Preuves connues : F1 + B1 ; surfaces auth/profil dans V1.

Reste staging : Créer ou utiliser un compte de recette neuf ; confirmer le profil provisoire et l’absence de chiffres inventés avec les réponses réelles.

### Q02 — Nouveaux tous sauvegardés

Attendu du plan : Accès aux sauvegardés, sans faux message d’absence de signaux.

Tests présents :

- [frontend/src/prospecting/__tests__/signal-feed-regression.test.tsx](../../../frontend/src/prospecting/__tests__/signal-feed-regression.test.tsx) — `an empty new segment guides the user to saved signals`.
- [frontend/src/pages/dashboard.test.tsx](../../../frontend/src/pages/dashboard.test.tsx) — `affiche les états vides et le titre de première visite`.
- [tests/test_consultation_targeting.py](../../../tests/test_consultation_targeting.py) — `test_week_saved_reads_reversible_workflow_not_historical_relevance`.

Preuves connues : F1 + B1.

Reste staging : Sauvegarder tous les nouveaux du compte de recette ; contrôler Aujourd’hui et le lien vers le segment sauvegardé.

### Q03 — Aucune relance ni réponse

Attendu du plan : État compact, signaux visibles, aucun panneau vide répété.

Tests présents :

- [frontend/src/pages/dashboard.test.tsx](../../../frontend/src/pages/dashboard.test.tsx) — `affiche les états vides et le titre de première visite`.
- [frontend/src/prospecting/__tests__/today-v11.test.tsx](../../../frontend/src/prospecting/__tests__/today-v11.test.tsx) — `Today uses selected scope, real weekly counters and company follow-up links`.
- [frontend/src/pages/dashboard.test.tsx](../../../frontend/src/pages/dashboard.test.tsx) — `affiche les relances et les compteurs de la semaine`.

Preuves connues : F1 ; V1 couvre la composition nominale, pas toutes les combinaisons vides.

Reste staging : Contrôler un compte ayant des signaux mais zéro relance et zéro réponse ; vérifier l’absence de panneaux vides répétés.

### Q04 — Deux profils et offres différentes

Attendu du plan : Même offre/zone/seuil sur les trois surfaces, reload conservé, rétablissement sans PATCH ICP.

Tests présents :

- [frontend/src/prospecting/__tests__/target-bar.test.tsx](../../../frontend/src/prospecting/__tests__/target-bar.test.tsx) — `switching profile and refining offer zone and amount in one form preserves every explicit choice`.
- [frontend/src/prospecting/__tests__/routeState.test.ts](../../../frontend/src/prospecting/__tests__/routeState.test.ts) — `uses URL first, then account/profile preferences, then profile defaults`.
- [frontend/src/prospecting/__tests__/routeState.test.ts](../../../frontend/src/prospecting/__tests__/routeState.test.ts) — `resets overrides without clearing list filters, other accounts, or changing the stored profile`.
- [frontend/src/prospecting/__tests__/provider.test.tsx](../../../frontend/src/prospecting/__tests__/provider.test.tsx) — `validates URL scope and restores non-sensitive preferences across tabs without changing the profile`.
- [tests/test_consultation_targeting.py](../../../tests/test_consultation_targeting.py) — `test_three_surfaces_return_same_selected_profile_scope_without_mutating_it`.

Preuves connues : F1/F3 + B1.

Reste staging : Passer entre deux profils réels, raffiner puis recharger chaque onglet ; vérifier requêtes et scope retourné, puis rétablir sans mutation ICP.

### Q05 — Modifier une option du profil

Attendu du plan : Conservation des autres champs, révision/rematérialisation et invalidation.

Tests présents :

- [frontend/src/pages/referenceTargeting.test.tsx](../../../frontend/src/pages/referenceTargeting.test.tsx) — `mappe uniquement les tokens explicites et préserve secondaires et maximum au PATCH`.
- [frontend/src/prospecting/__tests__/provider.test.tsx](../../../frontend/src/prospecting/__tests__/provider.test.tsx) — `survives StrictMode effect replay and reloads matching revision events`.
- [tests/test_target_icp_revision.py](../../../tests/test_target_icp_revision.py) — `test_materialization_records_the_target_revision_and_invalidates_old_matches`.
- [tests/test_target_icp_revision.py](../../../tests/test_target_icp_revision.py) — `test_failed_rematerialization_rolls_back_the_profile_and_all_signal_changes`.

Preuves connues : F1 + B1.

Reste staging : Modifier un seul champ du profil de recette ; comparer les champs conservés et matching_revision, puis vérifier les trois lectures.

### Q06 — Recherche dont le résultat était page 3

Attendu du plan : Recherche, compteurs et tri serveur avant pagination.

Tests présents :

- [tests/test_consultation_targeting.py](../../../tests/test_consultation_targeting.py) — `test_text_query_matches_beyond_an_unfiltered_third_page`.
- [tests/test_consultation_targeting.py](../../../tests/test_consultation_targeting.py) — `test_amount_sort_is_stable_across_three_pages_without_mixing_currencies`.
- [tests/test_company_directory_api.py](../../../tests/test_company_directory_api.py) — `test_directory_searches_all_pages_and_binds_cursor_to_filters`.
- [frontend/src/prospecting/__tests__/directory.test.tsx](../../../frontend/src/prospecting/__tests__/directory.test.tsx) — `sends directory search and sorting to the server rather than filtering a captured page`.

Preuves connues : F1 + B1.

Reste staging : Rejouer avec un jeu de recette suffisamment peuplé ; contrôler compteurs/tri/requêtes, sans scan local.

### Q07 — Filtre changé pendant Charger plus

Attendu du plan : Ancienne page ignorée, sans doublon ni mélange.

Tests présents :

- [frontend/src/prospecting/__tests__/directory.test.tsx](../../../frontend/src/prospecting/__tests__/directory.test.tsx) — `appends the server cursor page once without four counting scans`.
- [frontend/src/prospecting/__tests__/provider.test.tsx](../../../frontend/src/prospecting/__tests__/provider.test.tsx) — `never renders an old private response after a resource key changes`.
- [frontend/src/prospecting/__tests__/navigation-races.test.tsx](../../../frontend/src/prospecting/__tests__/navigation-races.test.tsx) — `ignores delayed company pagination after a %s filter changes` (variantes `directory` et `prospection`).

Preuves connues : F1 + F7. Les deux variantes retardent l’ancienne page, changent le filtre, libèrent l’ancienne réponse puis poursuivent le curseur courant sans doublon ni contamination.

Reste staging : Retarder la page suivante Entreprises, modifier un filtre, puis libérer l’ancienne réponse ; seule la nouvelle liste doit subsister.

### Q08 — Signaux history/recent

Attendu du plan : Curseurs/offsets respectés, troncature annoncée, compteurs conservés.

Tests présents :

- [frontend/src/prospecting/__tests__/signal-feed-regression.test.tsx](../../../frontend/src/prospecting/__tests__/signal-feed-regression.test.tsx) — `pagination carries the cursor, replaces the current page, and can return to the first page`.
- [frontend/src/prospecting/__tests__/signal-feed-regression.test.tsx](../../../frontend/src/prospecting/__tests__/signal-feed-regression.test.tsx) — `count truncation is visibly qualified independently of next-page availability`.
- [frontend/src/prospecting/__tests__/signals-v11.test.tsx](../../../frontend/src/prospecting/__tests__/signals-v11.test.tsx) — `retains the first page global counts when the next page intentionally omits counts`.
- [tests/test_feed_history.py](../../../tests/test_feed_history.py) — `test_history_pages_follow_effective_date_without_overlap_or_missing_rows`.
- [tests/test_feed_pagination.py](../../../tests/test_feed_pagination.py) — `test_walking_every_page_yields_every_signal_exactly_once`.

Preuves connues : F1 + B1.

Reste staging : Parcourir recent et history sur la release servie ; contrôler curseur/offset et absence de réinitialisation trompeuse des compteurs.

### Q09 — Ouverture Today, flux, marché entreprise

Attendu du plan : Même détail complet et statuts réellement fonctionnels.

Tests présents :

- [frontend/src/pages/dashboard.test.tsx](../../../frontend/src/pages/dashboard.test.tsx) — `ouvre le drawer partagé depuis une carte`.
- [frontend/src/prospecting/__tests__/signal-detail-regression.test.tsx](../../../frontend/src/prospecting/__tests__/signal-detail-regression.test.tsx) — `a deep link loads an independently requested detail even when the list is empty`.
- [frontend/src/companies/CompaniesPage.test.tsx](../../../frontend/src/companies/CompaniesPage.test.tsx) — `preserves a real signal artifact and company return path in linked-publication navigation`.
- [frontend/src/prospecting/__tests__/signal-feed-regression.test.tsx](../../../frontend/src/prospecting/__tests__/signal-feed-regression.test.tsx) — `a successful detail workflow refreshes the list and server global counts`.

Preuves connues : F1/F4 ; V1 couvre Today, flux et navigation dossier. Le mot « drawer » dans certains noms est historique ; le test rend le composant V11.

Reste staging : Ouvrir le même signal par les trois entrées, comparer le GET détail et son artifact, puis changer son statut.

### Q10 — Signal A puis B rapidement

Attendu du plan : Aucune réponse tardive de A ne remplace B.

Tests présents :

- [frontend/src/prospecting/__tests__/provider.test.tsx](../../../frontend/src/prospecting/__tests__/provider.test.tsx) — `never renders an old private response after a resource key changes`.
- [frontend/src/prospecting/__tests__/signal-artifact-navigation.test.tsx](../../../frontend/src/prospecting/__tests__/signal-artifact-navigation.test.tsx) — `closing an email artifact then opening another signal never reuses the first artifact`.
- [frontend/src/prospecting/__tests__/navigation-races.test.tsx](../../../frontend/src/prospecting/__tests__/navigation-races.test.tsx) — `a late signal A response cannot replace signal B after route navigation`.

Preuves connues : F1 + F7. Après libération de A, le test vérifie titre, note privée, lien entreprise et action de B avec sa propre révision ; aucune lecture de note ni écriture de statut de A.

Reste staging : Retarder le GET A, ouvrir B, libérer A : titre/notes/actions et entreprise doivent rester ceux de B.

### Q11 — Signal → entreprise → retour navigateur

Attendu du plan : Identité, onglet, filtres, retour et focus conservés.

Tests présents :

- [frontend/src/companies/CompaniesPage.test.tsx](../../../frontend/src/companies/CompaniesPage.test.tsx) — `preserves a real signal artifact and company return path in linked-publication navigation`.
- [frontend/src/prospecting/__tests__/routeState.test.ts](../../../frontend/src/prospecting/__tests__/routeState.test.ts) — `retains only internal return paths and valid artifact identifiers`.
- [frontend/src/pages/referenceResponsiveContract.test.tsx](../../../frontend/src/pages/referenceResponsiveContract.test.tsx) — `confine le focus dans le drawer puis le rend au déclencheur avec Échap et le scrim`.

Preuves connues : F1/F4/F5 + V1 : les six parcours incluent back/forward, mode annuaire/prospection et restitution du focus.

Reste staging : Confirmer les mêmes routes et paramètres avec une identité réelle après déploiement.

### Q12 — Ancienne URL email/artifact/directe

Attendu du plan : Nouvelle fiche, artifact validé, aucun ancien écran.

Tests présents :

- [frontend/src/prospecting/__tests__/signals-v11.test.tsx](../../../frontend/src/prospecting/__tests__/signals-v11.test.tsx) — `normalizes a legacy signal query to the canonical detail route retaining its artifact and context`.
- [frontend/src/prospecting/__tests__/signal-artifact-navigation.test.tsx](../../../frontend/src/prospecting/__tests__/signal-artifact-navigation.test.tsx) — `closing an email artifact then opening another signal never reuses the first artifact`.
- [tests/test_card_presentation_api.py](../../../tests/test_card_presentation_api.py) — `test_pinned_detail_keeps_the_exact_feed_artifact_after_a_new_publication`.
- [tests/test_card_presentation_api.py](../../../tests/test_card_presentation_api.py) — `test_invalid_pin_is_rejected_before_any_reader`.

Preuves connues : F1 + B1.

Reste staging : Ouvrir une ancienne URL de recette et un artifact périmé/invalide ; vérifier le détail V11 et l’absence de fallback vers un ancien rendu.

### Q13 — Note 2 000 / 2 001 caractères

Attendu du plan : Acceptation/refus précis ; feedback toujours limité à 500.

Tests présents :

- [tests/test_engagement_revisions.py](../../../tests/test_engagement_revisions.py) — `test_signal_note_accepts_2000_without_expanding_feedback`.
- [tests/test_signal_notes.py](../../../tests/test_signal_notes.py) — `test_locked_anonymous_foreign_origin_and_long_notes_fail_closed`.
- [frontend/src/prospecting/__tests__/notes-field.test.tsx](../../../frontend/src/prospecting/__tests__/notes-field.test.tsx) — `notes field displays literal text, the 2000 limit and acknowledgement only after saving`.

Preuves connues : F1 + B1/B4 ; B4 accepte 2000 et refuse 2001 pour les deux types de note via le domaine réel, pas HTTP.

Reste staging : Sur le compte de recette, enregistrer 2 000 caractères et tenter 2 001 via API ; comparer le message et vérifier qu’aucun feedback n’est créé.

### Q14 — Notes après fermeture/reload/offre/statut

Attendu du plan : Texte serveur exact, notes signal/entreprise indépendantes.

Tests présents :

- [frontend/src/prospecting/__tests__/usePersistedNote.test.tsx](../../../frontend/src/prospecting/__tests__/usePersistedNote.test.tsx) — `keeps draft and pending save when its React editor closes then reopens`.
- [frontend/src/prospecting/__tests__/queryKeys.test.ts](../../../frontend/src/prospecting/__tests__/queryKeys.test.ts) — `keeps company private subjects separate and never keys a note by the route alias`.
- [tests/test_company_dossier_fallback.py](../../../tests/test_company_dossier_fallback.py) — `test_directory_note_roundtrip_keeps_exact_spaces_and_newlines`.
- [tests/test_signal_notes.py](../../../tests/test_signal_notes.py) — `test_note_roundtrip_does_not_create_feedback_or_analytics`.
- [tests/test_company_dossier_fallback.py](../../../tests/test_company_dossier_fallback.py) — `test_followed_company_dossier_and_private_work_survive_profile_change`.

Preuves connues : F1/F3 + B1 ; V1 couvre fermeture/réouverture avec note signal, avec API simulée persistante.

Reste staging : Enregistrer des textes distincts avec espaces/retours ligne, recharger réellement puis changer offre/statut ; relire les deux notes serveur.

### Q15 — Deux onglets sur la même note

Attendu du plan : Conflit explicite, brouillon conservé, aucun écrasement automatique.

Tests présents :

- [frontend/src/prospecting/__tests__/usePersistedNote.test.tsx](../../../frontend/src/prospecting/__tests__/usePersistedNote.test.tsx) — `keeps both versions on conflict until the user explicitly accepts the server`.
- [frontend/src/prospecting/__tests__/usePersistedNote.test.tsx](../../../frontend/src/prospecting/__tests__/usePersistedNote.test.tsx) — `overwrites only after explicit conflict resolution using the latest server revision`.
- [tests/test_engagement_revisions.py](../../../tests/test_engagement_revisions.py) — `test_note_revision_conflict_clear_and_late_writer`.
- [tests/test_prospecting_migration.py](../../../tests/test_prospecting_migration.py) — `test_migrated_note_compare_and_swap_allows_only_one_concurrent_winner`.

Preuves connues : F1/F3 + B1/B2/B4 ; B2 exerce la concurrence CAS SQLite/PostgreSQL, B4 vérifie les conflits et l'export sur copie synthétique locale.

Reste staging : Deux vrais onglets du même compte : produire 409, comparer les deux versions, tester accepter serveur puis écraser explicitement avec la nouvelle révision.

### Q16 — Effacement et vieille sauvegarde en vol

Attendu du plan : Le tombstone confirmé empêche la résurrection.

Tests présents :

- [frontend/src/prospecting/__tests__/usePersistedNote.test.tsx](../../../frontend/src/prospecting/__tests__/usePersistedNote.test.tsx) — `writes a blank tombstone using the previous revision`.
- [frontend/src/prospecting/__tests__/usePersistedNote.test.tsx](../../../frontend/src/prospecting/__tests__/usePersistedNote.test.tsx) — `accepts the server whitespace tombstone without resending the same blank draft forever`.
- [tests/test_engagement_revisions.py](../../../tests/test_engagement_revisions.py) — `test_note_revision_conflict_clear_and_late_writer`.
- [tests/test_prospecting_migration.py](../../../tests/test_prospecting_migration.py) — `test_upgrade_replay_does_not_overwrite_cas_tombstones_or_reversible_workflow`.

Preuves connues : F1 + B1/B2/B4 ; B4 vérifie aussi le refus de résurrection par INSERT initial après tombstone.

Reste staging : Retarder une écriture ancienne, confirmer l’effacement depuis un autre onglet, libérer l’ancienne écriture et recharger.

### Q17 — Réseau / 401 / 403 pendant sauvegarde

Attendu du plan : Aucun faux succès ; retry/reconnexion appropriée.

Tests présents :

- [frontend/src/prospecting/__tests__/usePersistedNote.test.tsx](../../../frontend/src/prospecting/__tests__/usePersistedNote.test.tsx) — `keeps draft after error %s and retries without announcing success`.
- [frontend/src/prospecting/__tests__/usePersistedNote.test.tsx](../../../frontend/src/prospecting/__tests__/usePersistedNote.test.tsx) — `retries a failed initial read without losing text typed before the failure`.
- [frontend/src/auth/session.test.tsx](../../../frontend/src/auth/session.test.tsx) — `invalide la session sur un vrai 401`.
- [frontend/src/api/client.test.ts](../../../frontend/src/api/client.test.ts) — `does not broadcast a late unauthorized response from an aborted account request`.

Preuves connues : F1/F3 ; le cas paramétré note couvre 0, 401, 403, 404 et 500.

Reste staging : Simuler réseau perdu puis session expirée du seul compte de recette ; vérifier texte conservé, absence d’Enregistré et reprise autorisée.

### Q18 — Statuts réversibles et double clic

Attendu du plan : État exact, compteur unique et historique préservé.

Tests présents :

- [frontend/src/prospecting/__tests__/actions.test.tsx](../../../frontend/src/prospecting/__tests__/actions.test.tsx) — `uses status_revision, confirms the server value and invalidates shared views only on success`.
- [frontend/src/prospecting/__tests__/signal-detail-regression.test.tsx](../../../frontend/src/prospecting/__tests__/signal-detail-regression.test.tsx) — `all workflow controls are disabled during a write, with no duplicate submit`.
- [frontend/src/companies/CompaniesPage.test.tsx](../../../frontend/src/companies/CompaniesPage.test.tsx) — `keeps the previous status on failure and prevents same-batch duplicate writes`.
- [tests/test_engagement_revisions.py](../../../tests/test_engagement_revisions.py) — `test_all_signal_workflow_transitions_preserve_contact_history`.
- [tests/test_engagement_revisions.py](../../../tests/test_engagement_revisions.py) — `test_identical_workflow_write_preserves_revision_timestamp_and_event_count`.

Preuves connues : F1/F4 + B1.

Reste staging : Faire les transitions retour inclus, double-cliquer sous latence ; contrôler révisions, un seul événement et compteurs serveur.

### Q19 — Annuaire → suivre → même société depuis signal

Attendu du plan : Un sujet privé, suivi explicite et aucune duplication.

Tests présents :

- [tests/test_company_entity_aliases.py](../../../tests/test_company_entity_aliases.py) — `test_exact_aliases_share_private_subject_without_implicit_follow`.
- [tests/test_company_membership.py](../../../tests/test_company_membership.py) — `test_follow_is_explicit_idempotent_and_private`.
- [frontend/src/prospecting/__tests__/company-dossier.test.tsx](../../../frontend/src/prospecting/__tests__/company-dossier.test.tsx) — `shows only real locked families and does not follow or enrich simply by opening`.
- [frontend/src/prospecting/__tests__/company-dossier.test.tsx](../../../frontend/src/prospecting/__tests__/company-dossier.test.tsx) — `persists the private note with the requested alias and revision, then follows only on click`.
- [frontend/src/prospecting/__tests__/usePersistedNote.test.tsx](../../../frontend/src/prospecting/__tests__/usePersistedNote.test.tsx) — `shares the same private subject across aliases but writes through the original authorized alias`.

Preuves connues : F1/F4 + B1/B2.

Reste staging : Avec un SIREN exact lié à un signal réel, ouvrir sans suivre, puis suivre et comparer private_subject_key, note/contact et liste unique.

### Q20 — Homonymes / identités ambiguës

Attendu du plan : Aucune propagation privée par nom/département.

Tests présents :

- [tests/test_company_entity_aliases.py](../../../tests/test_company_entity_aliases.py) — `test_exact_identifiers_only_and_contradictions_are_rejected`.
- [tests/test_company_entity_aliases.py](../../../tests/test_company_entity_aliases.py) — `test_conflicting_notes_isolate_only_the_affected_account`.
- [tests/test_company_entity_aliases.py](../../../tests/test_company_entity_aliases.py) — `test_unresolved_aliases_remain_distinct`.
- [frontend/src/prospecting/__tests__/noteTransport.test.ts](../../../frontend/src/prospecting/__tests__/noteTransport.test.ts) — `refuses to bind a note editor to a different server private subject`.
- [tests/test_company_identity_audit.py](../../../tests/test_company_identity_audit.py) — `test_account_audit_preserves_collisions_and_other_accounts_and_redacts_report`.

Preuves connues : F1 + B1/B2/B3 ; B3 ferme le contrôle local de concurrence quarantaine/réconciliation et de l'ordre des verrous.

Reste staging : Examiner le rapport de collision du dry-run staging ; vérifier les exceptions privées sans afficher les notes ou contacts dans les preuves.

### Q21 — Contact personnel ajouté/modifié/supprimé

Attendu du plan : Source user, compte/sujet correct, aucun fournisseur ni email.

Tests présents :

- [frontend/src/prospecting/__tests__/manual-contact.test.tsx](../../../frontend/src/prospecting/__tests__/manual-contact.test.tsx) — `saves only after explicit submission, with the addressed alias and expected revision`.
- [frontend/src/prospecting/__tests__/manual-contact.test.tsx](../../../frontend/src/prospecting/__tests__/manual-contact.test.tsx) — `keeps the draft after conflict and only overwrites after explicit comparison`.
- [frontend/src/prospecting/__tests__/manual-contact.test.tsx](../../../frontend/src/prospecting/__tests__/manual-contact.test.tsx) — `requires a reachable contact and confirms revision-checked deletion`.
- [tests/test_company_manual_contact.py](../../../tests/test_company_manual_contact.py) — `test_contact_is_private_revisioned_and_deletion_cannot_resurrect_it`.
- [tests/test_prospecting_company_api.py](../../../tests/test_prospecting_company_api.py) — `test_discovery_directory_hides_fields_but_keeps_private_work`.

Preuves connues : F1/F4 + B1.

Reste staging : Créer/modifier/supprimer un contact synthétique de recette ; vérifier source=user, CAS, isolation compte et aucun appel lookup/email dans le réseau.

### Q22 — Contact connu / absent / invalide

Attendu du plan : Coordonnée exploitable ou guide utile, acheteur non affecté au titulaire.

Tests présents :

- [frontend/src/prospecting/__tests__/signal-content.test.tsx](../../../frontend/src/prospecting/__tests__/signal-content.test.tsx) — `known holder contacts replace the missing-contact guide and company name is a company route link`.
- [frontend/src/prospecting/__tests__/signal-content.test.tsx](../../../frontend/src/prospecting/__tests__/signal-content.test.tsx) — `unknown holder guides the next action, and locked values are placeholders only`.
- [frontend/src/prospecting/__tests__/company-dossier.test.tsx](../../../frontend/src/prospecting/__tests__/company-dossier.test.tsx) — `attributes each public contact to its own evidence rather than the telephone source`.
- [tests/test_boamp_notice_facts.py](../../../tests/test_boamp_notice_facts.py) — `test_tribunal_role_cannot_be_published_as_a_winner_contact_even_if_chain_says_so`.
- [tests/test_notice_projection.py](../../../tests/test_notice_projection.py) — `test_notice_projection_keeps_duration_without_start_and_separates_buyer`.

Preuves connues : F1/F4 + B1.

Reste staging : Contrôler trois dossiers représentatifs et leurs sources exactes, sans créer de contact à partir des coordonnées acheteur.

### Q23 — RAZEL, ERGC, GJG, LEFEVRE

Attendu du plan : Lot, unités/portée/reconductions corrects, aucun démarrage inventé.

Tests présents :

- [tests/test_boamp_notice_facts.py](../../../tests/test_boamp_notice_facts.py) — `test_facts_align_exactly_with_each_event_award_lot_and_winning_organization`.
- [tests/test_boamp_notice_facts.py](../../../tests/test_boamp_notice_facts.py) — `test_explicit_initial_duration_and_renewals_do_not_manufacture_a_maximum`.
- [tests/test_boamp_notice_facts.py](../../../tests/test_boamp_notice_facts.py) — `test_explicit_purchase_order_maximum_does_not_become_contract_duration`.
- [tests/test_boamp_notice_facts.py](../../../tests/test_boamp_notice_facts.py) — `test_related_tender_requires_exact_prior_notice_procedure_business_reference_and_lot`.
- [frontend/src/prospecting/__tests__/signal-detail-regression.test.tsx](../../../frontend/src/prospecting/__tests__/signal-detail-regression.test.tsx) — `does not show missing facts, inferred needs, estimated start dates or duplicated legacy fit reasons`.

Preuves connues : F1 + B1 couvrent les règles ; B4 vérifie le protocole de reprise des quatre identifiants avec données synthétiques. Aucun de ces résultats ne constitue la recette des quatre avis réels nommés ; leur validation reste ouverte.

Reste staging : Reprise BOAMP bornée sur event-key puis comparaison des quatre avis exacts : titulaire/lot/source/date/unité/portée/reconductions. RAZEL 26-87113 / 25-2744 : ne pas déduire un lien des seuls identifiants métier contradictoires.

### Q24 — Tranche d’effectif, email MX, devises

Attendu du plan : Précision fidèle, pas de faux vérifié, aucune somme EUR+CHF.

Tests présents :

- [tests/test_prospecting_contracts.py](../../../tests/test_prospecting_contracts.py) — `test_paid_projection_preserves_safe_sources_and_workforce_precision`.
- [tests/test_company_enrichment.py](../../../tests/test_company_enrichment.py) — `test_service_applies_thresholds_mx_placeholder_and_persists_one_model_decision`.
- [tests/test_consultation_targeting.py](../../../tests/test_consultation_targeting.py) — `test_amount_sort_is_stable_across_three_pages_without_mixing_currencies`.
- [frontend/src/prospecting/__tests__/adapters.test.ts](../../../frontend/src/prospecting/__tests__/adapters.test.ts) — `formats exact decimal amounts without a binary floating point conversion`.
- [frontend/src/prospecting/__tests__/adapters.test.ts](../../../frontend/src/prospecting/__tests__/adapters.test.ts) — `omits missing or invalid money instead of guessing a currency or showing NaN`.

Preuves connues : F1 + B1.

Reste staging : Contrôler un effectif en tranche et une coordonnée modèle à vérifier ; afficher un jeu EUR/CHF et inspecter séparément montants/tri.

### Q25 — Découverte : JSON, DOM et réseau

Attendu du plan : Aucune valeur premium, placeholders réels non sensibles, grants stables.

Tests présents :

- [tests/test_prospecting_contracts.py](../../../tests/test_prospecting_contracts.py) — `test_discovery_projection_contains_no_protected_values`.
- [tests/test_prospecting_company_api.py](../../../tests/test_prospecting_company_api.py) — `test_discovery_directory_hides_fields_but_keeps_private_work`.
- [tests/test_notice_projection.py](../../../tests/test_notice_projection.py) — `test_discovery_notice_contacts_never_leave_the_server`.
- [tests/test_billing_paywall.py](../../../tests/test_billing_paywall.py) — `test_the_grants_are_persisted_and_never_rotate`.
- [frontend/src/prospecting/__tests__/company-dossier.test.tsx](../../../frontend/src/prospecting/__tests__/company-dossier.test.tsx) — `shows only real locked families and does not follow or enrich simply by opening`.
- [frontend/src/billing/paywallContinuity.test.tsx](../../../frontend/src/billing/paywallContinuity.test.tsx) — `ne laisse fuir aucune donnée protégée dans l’état de navigation`.

Preuves connues : F1/F4/F6 + B1 ; V1 vérifie les trois tailles Découverte avec réponses simulées sans données premium.

Reste staging : Avec un vrai compte Découverte, inspecter JSON et réseau brut, DOM/state/navigation, stabilité des grants et absence de fournisseur lancé par GET.

### Q26 — Upgrade, retour et droits différés

Attendu du plan : Même dossier après autorité serveur ; aucune ouverture par query string.

Tests présents :

- [frontend/src/billing/checkoutV11.test.tsx](../../../frontend/src/billing/checkoutV11.test.tsx) — `awaits billing status then /me before offering the exact company return`.
- [frontend/src/billing/checkoutV11.test.tsx](../../../frontend/src/billing/checkoutV11.test.tsx) — `revalidates the company dossier on a cold success-page load without any previous prospecting provider`.
- [frontend/src/billing/checkoutV11.test.tsx](../../../frontend/src/billing/checkoutV11.test.tsx) — `does not confirm paid access when refreshing /me fails`.
- [frontend/src/billing/checkoutFlow.test.tsx](../../../frontend/src/billing/checkoutFlow.test.tsx) — `E — une arrivée directe sans paiement ne confirme jamais rien`.
- [frontend/src/billing/checkoutReturn.test.ts](../../../frontend/src/billing/checkoutReturn.test.ts) — `preserves the exact signal and artifact without storing signal content`.
- [frontend/src/billing/checkoutReturn.test.ts](../../../frontend/src/billing/checkoutReturn.test.ts) — `expires without being extended by reads, rejects tampered timestamps and clears on logout intent`.

Preuves connues : F1/F3/F6. Les contrats couvrent aussi company/directory et anciennes clés ; aucun paiement réel n’a été exécuté.

Reste staging : Sur staging, contrôler choix catalogue/intention et accès direct /checkout/success sans confirmer un paiement réel ; une vraie transaction requiert une autorité de recette dédiée, non implicite.

### Q27 — Downgrade / compte changé pendant GET

Attendu du plan : Purge et rejet des réponses obsolètes, aucune fuite intercompte.

Tests présents :

- [frontend/src/prospecting/__tests__/provider.test.tsx](../../../frontend/src/prospecting/__tests__/provider.test.tsx) — `aborts a pre-downgrade resource and rejects its late protected result`.
- [frontend/src/prospecting/__tests__/provider.test.tsx](../../../frontend/src/prospecting/__tests__/provider.test.tsx) — `aborts the previous account note and ignores its late result after switching accounts`.
- [frontend/src/prospecting/__tests__/provider.test.tsx](../../../frontend/src/prospecting/__tests__/provider.test.tsx) — `purges immediately at logout intent even if the network logout remains pending`.
- [frontend/src/auth/session.test.tsx](../../../frontend/src/auth/session.test.tsx) — `ignores a previous /me response after %s`.
- [frontend/src/prospecting/__tests__/signal-detail-regression.test.tsx](../../../frontend/src/prospecting/__tests__/signal-detail-regression.test.tsx) — `a suppressed Apollo result cannot reappear from the original holder snapshot`.
- [frontend/src/prospecting/__tests__/company-dossier.test.tsx](../../../frontend/src/prospecting/__tests__/company-dossier.test.tsx) — `removes previously visible Apollo contacts when the server reports suppression`.

Preuves connues : F1/F3/F4. Le test /me couvre Déconnexion et Autre compte.

Reste staging : Compte de recette seulement : retarder GET, révoquer les droits ou déconnecter, changer de compte et libérer les réponses ; aucun ancien contenu privé ni réadoption session.

### Q28 — Lookup disponible/absent/quota épuisé

Attendu du plan : Action explicite, quota réel, états lisibles et formulaire distinct.

Tests présents :

- [frontend/src/prospecting/__tests__/enrichment.test.tsx](../../../frontend/src/prospecting/__tests__/enrichment.test.tsx) — `does not consume quota or queue enrichment simply by mounting`.
- [frontend/src/prospecting/__tests__/enrichment.test.tsx](../../../frontend/src/prospecting/__tests__/enrichment.test.tsx) — `starts lookup once, uses only GET for bounded polling, and stops on a server result`.
- [frontend/src/prospecting/__tests__/enrichment.test.tsx](../../../frontend/src/prospecting/__tests__/enrichment.test.tsx) — `refreshes authority with GET after quota exhaustion without repeating the paid POST`.
- [frontend/src/prospecting/__tests__/enrichment.test.tsx](../../../frontend/src/prospecting/__tests__/enrichment.test.tsx) — `times out without inventing a contact and retry performs GET only`.
- [tests/test_company_contact_lookup.py](../../../tests/test_company_contact_lookup.py) — `test_monthly_quota_is_enforced_before_the_next_company_is_called`.
- [tests/test_saas_company_api.py](../../../tests/test_saas_company_api.py) — `test_company_contact_lookup_fails_closed_without_a_provider`.

Preuves connues : F1/F4 + B1.

Reste staging : Lire les états réels sans consommer un quota fournisseur pour la recette ; un test du POST externe exige une autorisation explicite distincte. Formulaire manuel toujours autonome.

### Q29 — 390/320 px et clavier

Attendu du plan : Pas de débordement global ; filtres/tri/focus/fermeture accessibles.

Tests présents :

- [frontend/tests/visual/prospecting-v11.spec.ts](../../../frontend/tests/visual/prospecting-v11.spec.ts) — `V11 ${viewport.name} ${paid ? 'paid' : 'discovery'} complete three-tab flow`.
- [frontend/src/pages/referenceResponsiveContract.test.tsx](../../../frontend/src/pages/referenceResponsiveContract.test.tsx) — `conserve un main, un h1, ouvre le détail en feuille modale et rend le chrome inerte`.
- [frontend/src/pages/referenceResponsiveContract.test.tsx](../../../frontend/src/pages/referenceResponsiveContract.test.tsx) — `confine le focus dans le drawer puis le rend au déclencheur avec Échap et le scrim`.

Preuves connues : V1 : 32/32 verts dont six parcours V11 ; F5 : 53 tests incluant responsive/styles. Le run 29/32 sous contention est remplacé, pas masqué.

Reste staging : Refaire le parcours court sur le SHA servi aux trois tailles ; vérifier clavier sur navigateur réel sans API interceptée.

### Q30 — Public/auth/ICP/billing/notifications/Founder

Attendu du plan : Pas de régression des surfaces non remplacées.

Tests présents :

- [frontend/src/pages/referenceAccount.test.tsx](../../../frontend/src/pages/referenceAccount.test.tsx) — `branche la sécurité sur le reset existant et une seule déconnexion réelle`.
- [frontend/src/notifications/notifications.test.tsx](../../../frontend/src/notifications/notifications.test.tsx) — `persiste l’activation ou la coupure des alertes`.
- [frontend/src/billing/billing.test.tsx](../../../frontend/src/billing/billing.test.tsx) — `affiche les prix RENVOYÉS par l’API, jamais une grille écrite en dur`.
- [frontend/src/styles/dashboardVendorBundle.test.ts](../../../frontend/src/styles/dashboardVendorBundle.test.ts) — `préfixe le preflight et les utilitaires Tailwind sous la surface dashboard`.
- [tests/founder_api/test_access.py](../../../tests/founder_api/test_access.py) — `test_founder_session_is_production_only_and_read_only`.

Preuves connues : F1/F5/F6 + V1 (21 comparaisons pixels inchangées) + B1. Build/suite Founder séparés : ne pas inférer leur réussite du seul frontend client.

Reste staging : Smoke public/auth/profil/compte/notifications/billing sur staging ; Founder reste production-only et hors déploiement staging. Attacher ses preuves locales de build/tests séparées.

### Q31 — Migration peuplée et retour release précédente

Attendu du plan : Notes/statuts/contacts conservés ; alias documentés ; aucun downgrade destructif.

Tests présents :

- [tests/test_prospecting_migration.py](../../../tests/test_prospecting_migration.py) — `test_populated_0058_upgrade_retains_notes_feedback_contacts_and_account_scope`.
- [tests/test_prospecting_migration.py](../../../tests/test_prospecting_migration.py) — `test_upgrade_replay_does_not_overwrite_cas_tombstones_or_reversible_workflow`.
- [tests/test_prospecting_migration.py](../../../tests/test_prospecting_migration.py) — `test_concurrent_exact_alias_reconciliation_preserves_one_canonical_note_and_legacy_copy`.
- [tests/test_company_identity_audit.py](../../../tests/test_company_identity_audit.py) — `test_account_audit_preserves_collisions_and_other_accounts_and_redacts_report`.
- [tests/test_prospecting_rollback_guard.py](../../../tests/test_prospecting_rollback_guard.py) — `test_staging_installs_the_write_guard_in_the_tls_server_only`.
- [tests/test_prospecting_rollback_guard.py](../../../tests/test_prospecting_rollback_guard.py) — `test_guard_matches_writes_only`.

Preuves connues : B2/B3 : migrations/audit et concurrence SQLite+PostgreSQL ; B4 : helper 35/35 incluant préservation des comptes, sessions/réinitialisations indirectes, notes, retour `contacted→new` sans perte de l'historique et export ; O1 : nginx isolé sur staging, dix routes vérifiées. Cela ne prouve pas encore la répétition sur restauration complète ni une bascule/restauration réelle des symlinks.

Reste staging : Exécuter le runbook : audit collisions de la base staging, migration sur copie puis vive, garde fermé avant ancien exécutable, restauration des deux .previous vérifiés, aucune restauration destructive de DB ni downgrade 0059/0060.

### Q32 — Anciens rendus/assets/appels prototype

Attendu du plan : Aucune branche historique ou endpoint démo dans la release active.

Tests présents :

- [frontend/src/styles/prospectingRetirement.test.ts](../../../frontend/src/styles/prospectingRetirement.test.ts) — `the unused pre-V11 dashboard module is retired`.
- [frontend/src/styles/prospectingRetirement.test.ts](../../../frontend/src/styles/prospectingRetirement.test.ts) — `exclusive old prospecting rules are retired without removing shared profile or public styles`.
- [frontend/src/styles/referenceSurface.test.tsx](../../../frontend/src/styles/referenceSurface.test.tsx) — `does not retain the legacy no-script landing page`.
- [tests/test_cleanup_architecture.py](../../../tests/test_cleanup_architecture.py) — `test_active_source_never_imports_archive`.

Preuves connues : F5 + audit rg L12 : aucun import actif SignalDrawer/SignalRow/CompanyPanel ; Dashboard.module.css retiré, 287 règles exclusives supprimées, 708 conservées byte-identical. Les tests échantillonnent les styles ; l’audit du bundle reste distinct.

Reste staging : Vérifier imports/bundle du SHA candidat puis assets effectivement référencés sur staging, absence des deux flags et d’appels localhost/prototype. Conserver les artifacts métier, ne retirer que les anciens assets UI sans consommateur.

## Écarts et conditions de fermeture

- **Gate local préalable :** F1 et V1 restent verts (752/752 et32/32), B3/B4 ferment les contrôles ciblés identité/helper. B1 est interrompu avec cinq erreurs de fixture : corriger puis joindre la suite backend complète, sans déduire un global green des ciblés. L13/L14 restent ouverts.
- **Avant activation — Q23/Q31, conservation Q13–21 :** exécuter [la répétition sur restauration complète](staging-rehearsal.md), contrôler les données privées originales, audits, CAS/tombstones/workflow/export et les quatre avis publics réels. Puis joindre la preuve du repli qui conserve0060, ferme les anciens writers et vérifie les deux liens ; les tests locaux et nginx isolé ne remplacent pas cette preuve.
- **Sur la release servie — Q01–12, Q18–24 et Q29 :** parcours métier avec les réponses réelles, navigation/ciblage/pagination, sources et clavier aux trois tailles. Les étapes détaillées sont celles des rubriques correspondantes ; F7 ferme déjà les tests locaux des courses Q07/Q10.
- **Autorité et données privées — Q13–17, Q25/Q27 :** sur comptes de recette uniquement, vérifier persistance/conflit/réseau/session, JSON Découverte, grants et purge lors d'un changement de droits ou de compte. Une API simulée n'est pas cette preuve.
- **Actions externes — Q26/Q28 :** contrôler catalogue/retour et états de lookup sans transaction ni quota fournisseur ; une vraie opération externe exige l'autorité distincte indiquée dans ces rubriques.
- **Surfaces conservées et livraison — Q30/Q32 :** smoke public/auth/profil/compte/notifications/billing ; attacher SHA backend, lien frontend et assets réellement servis, sans flags ni appels prototype. Founder reste production-only, hors déploiement staging ; conserver ses preuves locales séparées.

Ces points sont des trous de **preuve de recette**, pas des bugs produit déduits. Une mauvaise identité, une fuite premium/intercompte, une perte/résurrection de texte ou un ancien rendu encore actif bloquerait la bascule, conformément au plan. Aucun nouveau défaut de cette nature n’est établi par cette cartographie seule.

## Commandes de reproduction ciblées

À lancer depuis le worktree, séquentiellement avec les recettes lourdes ; les blocs suivants documentent les commandes, **ils ne constituent pas de nouvelles exécutions**.

### C2 — migrations et identité, deux moteurs

Le DSN jetable doit être injecté sans être consigné dans les preuves.

```sh
KIVOU_TEST_POSTGRES_URL='<DSN PostgreSQL jetable local>' uv run pytest -o addopts= -q -n 4 tests/test_prospecting_migration.py tests/test_company_identity_audit.py
```

### C3 — session / checkout / Provider

Depuis `frontend/` :

```sh
DEBUG_PRINT_LIMIT=0 npm test -- --run src/auth/session.test.tsx src/billing/checkoutV11.test.tsx src/billing/checkoutFlow.test.tsx src/prospecting/__tests__/provider.test.tsx --maxWorkers=2 --reporter=dot
npx tsc -p tsconfig.app.json --noEmit --incremental false
```

### C4 — helper de répétition, deux moteurs locaux

Injecter `KIVOU_TEST_POSTGRES_URL` vers une base jetable locale, sans afficher son DSN. Chaque variante PostgreSQL crée son propre schéma de test ; cette commande ne lance pas le helper sur staging.

```sh
PYTEST_DEBUG_TEMPROOT=/tmp .venv/bin/pytest -o addopts= -q -n0 tests/test_staging_rehearsal_checks.py
```

### C5 — retraite CSS et surfaces conservées

Depuis `frontend/` :

```sh
DEBUG_PRINT_LIMIT=0 npm test -- --run src/styles src/pages/referenceResponsiveContract.test.tsx src/pages/referenceAccount.test.tsx src/notifications/notifications.test.tsx src/billing/billing.test.tsx --maxWorkers=2 --reporter=dot
npx tsc -p tsconfig.app.json --noEmit --incremental false
npx eslint src/styles/prospectingRetirement.test.ts
```

### V1 — navigateur final isolé

Depuis `frontend/` :

```sh
npm run test:visual -- tests/visual/reference-port.spec.ts tests/visual/prospecting-v11.spec.ts --workers=1
```

### C7 — courses pagination et navigation

Depuis `frontend/` :

```sh
DEBUG_PRINT_LIMIT=0 npm test -- --run src/prospecting/__tests__/navigation-races.test.tsx --maxWorkers=1 --reporter=dot
```

### Vérification statique complémentaire (Q32)

Depuis la racine du worktree ; un code retour 1 de `rg` signifie ici « aucune correspondance ». Les anciennes fixtures et tests peuvent garder un nom historique ; les imports et branches applicatifs actifs sont la cible.

```sh
rg -n 'SignalDrawer|SignalRow|CompanyPanel|Dashboard\.module\.css|signals_companies_v2_enabled|company_profile_v2_enabled' frontend/src src/signals --glob '!*.test.*' --glob '!**/__tests__/**' --glob '!**/test/**'
git diff --check
```

Procédure staging et repli : [staging-runbook.md](staging-runbook.md). Les artefacts temporaires `/tmp`, rapports Playwright et captures doivent être archivés ou rattachés au SHA candidat avant clôture ; leur chemin local seul n’est pas une preuve durable de déploiement.
