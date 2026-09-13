# Prospecting V11 — exécution staging

État courant au 13 septembre 2026, 23:33 UTC : **la release exécutable
`7f2a2080bbc3dfe280d1a699e0e0e9183c30b203` est servie sur staging** depuis
22:57:40 UTC. Sa CI complète et les quatre parcours de recette réels sont passés ;
le nettoyage ciblé est confirmé. **L00–L14 terminés pour staging uniquement.**
Le [rapport final](staging-release-7f2a208.md) distingue code servi, copies,
tests locaux, observations vives et limites. Les paragraphes chronologiques
suivants conservent les résultats intermédiaires, pas tous l'état courant.

## Référence et périmètre

Plan approuvé : `/home/jaybe/projects/kivou-implementation-plan-2026-09-13/index.html`.
SHA256 : `5a535272a41ccf6a18fb0717ce6a7b0a9b5983472310653795be39f4aaf0c233`.
Prototype visuel : `/home/jaybe/projects/kivou-audit-preview-2026-09-13/v2` (V11).
Décisions finales : notes personnelles à la place de l'approche ; durées sourcées sans démarrage estimé ; dossier entreprise exclusivement dans Entreprises.

Base relue sur l'hôte staging : `2599d77840c073086051cbaa95441caf170afeac`.
Backend et frontend pointent sur la même release. Branche isolée : `feat/prospecting-v11-staging`.
Le checkout principal et ses changements documentaires ne sont pas modifiés. Production exclue.
Alembic initial : tête unique `0058_client_location`, après merge `0056_company_contact_merge` des deux branches 0054.

Pendant la recette, `origin/main` a avancé à `b72f06c614b7364ec10adf84b325090206f399f1` avec d'autres évolutions d'enrichissement, Founder et migrations. La base réellement servie par staging est restée `2599d77840c073086051cbaa95441caf170afeac`. Cette release reste fondée sur cette base staging, conformément à L00 ; aucune réécriture ni incorporation implicite des travaux de production. La CI de la candidate utilise une PR de validation vers une référence staging dédiée, pas une fusion vers main. Une future intégration production est un chantier distinct.

## Lots et état

- [x] L00 — base, graphe et référence vérifiés ; revue indépendante du worktree.
- [x] L01 — contrats et capacités indépendantes du rendu.
- [x] L02 — notes révisées et workflow réversible.
- [x] L03 — alias exacts, exceptions privées, suivi et interlocuteur personnel.
- [x] L04 — annuaire paginé et prospection unifiée.
- [x] L05 — snapshots et extraction BOAMP.
- [x] L06 — projection commerciale et reprise bornée.
- [x] L07 — ciblage, filtres et compteurs serveur.
- [x] L08 — contexte React, courses et autosave.
- [x] L09 — Signaux V11.
- [x] L10 — Entreprises V11 et dossier commun.
- [x] L11 — Aujourd'hui, shell, ciblage et retour checkout.
- [x] L12 — retrait des anciens rendus et styles exclusifs.
- [x] L13 — suites du SHA7f2, adverses sur build/PG isolés, revues et véritable répétition du repli sur copie610 à backend identique.
- [x] L14 — backend/frontend7f2 servis, recette réelle trois plans, observation et nettoyage ciblé confirmés.

Les travaux préparatoires indépendants peuvent avancer en parallèle ; migrations 0059/0060 sous un propriétaire unique. Une case produit exige tests et revue, pas seulement du code écrit.

## Premières suites de diagnostic

Installation verrouillée uv et npm réussie. npm signale deux vulnérabilités modérées existantes ; aucune montée de dépendances forcée.
Frontend : 656 tests verts, 35 échecs sur 691, 7 fichiers en échec sur 52. Backend : 5770 tests verts, 8 échecs, 25 skips, 1 xfail. Ces suites ont été **lancées** avant les changements mais ont terminé pendant les travaux : elles ne constituent pas une baseline immuable. Les écarts anciens sont vérifiés individuellement contre le code de base avant modification d'une assertion. Aucun échec n'est accepté par simple attribution à la baseline.

## Inventaire des propriétaires initiaux

`Dashboard.tsx` et `SignalsFeed.tsx` importent SignalDrawer ; celui-ci, CompaniesPage et DirectoryCompanyPage utilisent CompanyPanel. SignalRow fournit également des helpers aux trois surfaces. Les branches de présentation `signals_companies_v2_enabled`, `company_profile_v2_enabled` et `redesigned` doivent disparaître après découplage des droits.
Routes conservées : `/app`, `/app/dashboard`, `/app/signals`, `/app/signals/:signalKey`, `/app/companies`, `/app/companies/:companyKey`, `/app/companies/directory/:directorySiren`.

## Preuves d'exécution

Les commandes ci-dessous sont lancées dans le worktree. Les nombres sont des vérifications ciblées, qui se recouvrent ; ne pas les additionner.

| Lot / revue | Preuve ciblée et corrections |
| --- | --- |
| L01/L03/L04 | Droits projetés avant HTTP, alias SIREN/SIRET exacts, pas de rapprochement au nom. Revue indépendante : entreprise suivie restant accessible hors ICP ; website premium absent du JSON Découverte ; notes exactes sans trim. Suite entreprise 71 verts + 2 skips. Audit identité/migration : 24 verts avec SQLite et PostgreSQL 16 jetable. |
| L02 | 89 tests engagement initialement verts ; CAS notes/contact/statuts, tombstones, séparation feedback historique. Revue : même statut idempotent sans nouvel événement ; 4 états testés. Hook frontend corrigé après RED pour accepter uniquement le vrai acquittement idempotent et refuser réponse malformée. |
| L04 | Annuaire indépendant, recherche SQL globale nom/ville/SIREN/NAF, taxonomie versionnée en sélecteurs, curseurs liés aux filtres ; 4 tests API verts. Options/proxy : 36 verts avant ajout guard. |
| L05/L06 | 189 tests extraction/ingestion initiaux. Revue indépendante P1/P2 puis RED 4 → GREEN : faits append-only par source_set_hash, reprise d'une source explicitement liée, arrêt après avis non concordant, dates/TTL propres à chaque source. 115 verts + 5 skips puis 12 SQLite/PostgreSQL verts sur 0060. Nouvelle revue main : ordering/provenance/versions et reprise concordants. |
| L07 | 93 tests ciblage/feed/dashboard/prospection verts : droit filtre serveur, compteurs, tri monnaie stable, curseur scoped, route profonde autorisée indépendamment des filtres de consultation. |
| L08/L09/L12 | 171 tests dans 22 fichiers verts après transfert ; 40 garanties ligne/détail/feed/adaptateurs, notes autosave révisées, purge changement compte/logout, courses et erreurs. Aucun ancien import SignalDrawer/SignalRow/CompanyPanel, MatchDots/StatusPill, ni CSS exclusif actif. |
| L10 | 32 tests dossier/annuaire/contact verts ; annuaire et prospection emploient les mêmes lignes/dossier. Revue corrige la résurrection d'un contact Apollo supprimé. |
| L11 | 165 tests billing/upgrade verts à 2 workers ; origine typée compte+TTL, prix catalogue, aucun POST implicite ; retour froid status → me → dossier serveur. P1 suppression lookup testé aussi dans SignalDetail ; aucune confiance dans le seul retour Stripe. |
| Shell / Aujourd'hui | 12 tests dashboard/ressources verts ; 9 tests shell/responsive verts avant ajout non-invention de compteurs ; une seule racine main, détails natifs modaux, barre cible unique, mode annuaire mémorisé dans le shell du compte. |
| Exploitation | Guard nginx staging : RED include absent puis 48 tests proxy/guard verts. Expiration bornée des bytes BOAMP conserve faits et provenance. Ruff global vert après format des seuls fichiers de cette branche. |
| Recette finale frontend | 752/752 tests, 73 fichiers, 59,79s à deux workers ; aucun échec. Les courses Q07 (deux modes) et Q10 sont des intégrations HTTP tardives, pas seulement un test abstrait du cache. |
| Gate migrations + BOAMP | 363/363, sans skip, PostgreSQL compris. Attentes de tête historiques actualisées ; défaut préexistant de la projection du backfill0022 corrigé sans modifier l'ancienne migration ni le lecteur runtime. Sélection BOAMP exacte liée au curseur, testée RED→GREEN. |
| Quarantaine d'identité | Contradiction d'un SIREN exact : preuve initiale conservée mais alias durablement unresolved, anciens overrides ignorés, exclusion des regroupements et candidatures canoniques. Concurrence : 6/6 SQLite/PostgreSQL ; validation finale identité 85/85 en 123,70s, sans skip (`/tmp/kivou-v11-identity-lock-final-20260913.log`). Mutex transactionnel PostgreSQL acquis avant les verrous alias puis compte ; SQLite prend le verrou d'écriture avant lecture par UPDATE sans ligne modifiée. Le verrou compte PostgreSQL `FOR NO KEY UPDATE` reste compatible avec le `KEY SHARE` d'un INSERT workflow antérieur. Quarantaine/réconciliation dans les deux sens et ordres de groupes opposés testés sans deadlock. |
| Helper de répétition | Version streaming : **54/54**, sans skip, SQLite/PostgreSQL local ;75,43s dans le worktree isolé puis **105,73s après intégration**, log `/tmp/kivou-v11-streaming-helper-integrated.log`, code0. Ruff et compilation verts. Baseline exhaustive PK+HMAC privée par lots, test10017descendants, modifications/suppressions du dernier lot détectées, ajouts autorisés, normalisationJSON/nombres/dates, bornes et nettoyage vérifiés. URL défaut exclusivement vers la même copie, migration/audits/backfill, CAS/tombstones/2000 caractères, retour `contacted→new` sans perte d'historique, exports anciens exacts. Quatre avis exacts et trois tentatives maximum. Remplace la preuve35/35 du helper en mémoire ; ce n'est pas une répétition réelle de staging. |

Recette Playwright finale locale : **32/32 tests verts**, un worker, 1,3 minute. Six parcours V11 à 1440/390/320 px, payant/Découverte, 24 captures dans `output/playwright/v11-*.png`, relues indépendamment. Clavier natif, Escape/retour focus, racine main/h1 unique, absence de débordement et navigation aller/retour couverts. Les **21 comparaisons visuelles des surfaces conservées** passent sans modification des goldens ; les anciens goldens des trois onglets restent seulement archivés. Données synthétiques exclusivement dans les tests, jamais dans le bundle applicatif.

Préflight des anciennes données : **2/2 tests SQLite/PostgreSQL** vérifient schéma source0058 inchangé et conservation exacte des notes, avec rapprochement exécuté uniquement dans un miroir en mémoire. Répétition réelle du guard avec nginx isolé sur staging : **10/10 requêtes conformes**, écritures de prospection/ICP bloquées, lectures/auth/webhooks préservés ; processus isolé arrêté après contrôle. Cela n'est pas un déploiement de l'application.

Compilation frontend, TypeScript, ESLint, isolation CSS et build Founder : verts. Le contrôle d'isolation a détecté les pseudo-éléments backdrop non préfixés, corrigés et revérifiés sans assouplir le contrôle. Le test qui réalise un build complet a une borne105s adaptée au build mesuré à55s sous charge, sans modifier les assertions ni le délai global des tests unitaires.

**Gate backend global sur la candidate `476b22f90cec87ccf48319375866bf96984ce787` : 6 438 réussis, 11 skips, un xfail, aucun échec inattendu**, code 0 en 2 644,81 s. Log `/tmp/kivou-v11-backend-release-gate-2.log`, PostgreSQL jetable disponible via les deux variables dédiées et tests lents inclus (`-o addopts= -q -n 2 -x`). Les quatre fixtures historiques ont été reconstruites depuis leurs véritables révisions anciennes, sans autoriser le downgrade0059/0060 ; 76/76 tests ciblés étaient verts avant cette passe. Complément `tests/test_persistence_conflicts.py` avec le troisième alias `KIVOU_TEST_DATABASE_URL` : **22/22, aucun skip, code0 en2,22s**, journal `/tmp/kivou-v11-persistence-conflicts-pg-complement.log` ; ses neuf cas PostgreSQL ignorés dans le full sont ainsi exécutés. Les deux autres skips concernent des smoke Stripe opt-in sans clé ; le xfail strict documente une frontière HTTP historique de `companies/france.py`, hors changement V11.

**Étape historique476 — CI de cette candidate : succès complet**, [run34777544050](https://github.com/bruppacherrodrigue-art/Kivou/actions/runs/34777544050), quatre shards backend, frontend et décision. [PR251](https://github.com/bruppacherrodrigue-art/Kivou/pull/251) reste une PR de validation vers la base staging dédiée ; aucune fusion vers main/production. À cette étape, ces preuves ne validaient ni le delta ultérieur du helper, ni un déploiement ; L13/L14 n'étaient donc pas cochés. Les preuves finales qui les ferment sont regroupées dans [qa-matrix.md](qa-matrix.md#écarts-et-conditions-de-fermeture).

**Première répétition complète refusée, base vive préservée :** la volumétrie réelle comporte 26 tables privées et 260 069 lignes, dont 256 322 dans `for_you_sentence` (descendant de profil par FK). La borne initiale de 10 000 lignes du helper était insuffisante. La connexion d'exécution a également perdu son stdout ; aucun succès n'est déduit du code systemd d'une unité déjà collectée. Journaux d'échec conservés, dump propre supprimé, absence de base portant le préfixe exact de cette candidate vérifiée en lecture seule. Liens actifs toujours2599 et schéma0058. La nouvelle répétition utilisera une baseline exhaustive par empreintes privées, ainsi qu'un rapport durable et une unité asynchrone dont le résultat est conservé.

Outils opérateurs ignorés, relus indépendamment et testés localement : **28/28 en17,40s**, `/tmp/kivou-v11-operators-final.log` (12contrôles API/couverture sur copie, huit tests du driver durable/nettoyage, huit du garde de comptes QA). Le garde conserve les verrous des workers jusqu'à confirmation du nettoyage ciblé et reprend ce seul nettoyage en échec ; aucun compte réel n'est modifié, aucune création répétée automatiquement. Harnais navigateur ignoré :13/13 sur sept variantes entièrement interceptées, sans réseau staging. Ces preuves ne sont pas une exécution des opérateurs sur la base vive.

**Candidate de répétition `e6a7480e45c343765b35092a6a0838339b6050ed` : CI complète réussie**, [run34779618067](https://github.com/bruppacherrodrigue-art/Kivou/actions/runs/34779618067), terminée le13septembre à20:22:06UTC ; sept jobs verts. Backend6457réussis,11skips et un xfail historique ; frontend752réussis et recette visuelle32réussie. Cette candidate ajoute seulement le helper streaming, ses tests et les preuves documentaires au produit476.

**Deuxième répétition réelle, refusée pour couverture BOAMP :** unité `kivou-v11-rehearsal-e6a7480.service`, du20:06:40 au20:20:21UTC, code2. Le rapport durable privé `report.json` confirme la conservation exhaustive des260069lignes dans26tables, les exports des34comptes historiques et les huit contrats notes/statuts/contacts/isolation. Trois avis et cinq lots ont leurs faits ; RAZEL26-87113 reste sans faits après trois tentatives, code fermé `ValueError`. Les contrôles HTTP et la préparation QA sur copie n'ont donc pas été atteints. La lecture seule du canonique historique a ensuite révélé le titulaire `RAZEL-BEC SAS` avec un identifiant `BOAMP-COMPANY-ID` de14chiffres espacés, tandis que le nouveau parseur produit un SIRET compact ; ce cas fait l'objet d'une régression dédiée avant toute nouvelle répétition.

La seconde copie et son dump temporaire ont été supprimés ; les liens2599 et le schéma0058 sont confirmés inchangés. Une sauvegarde préactivation privée de2878279793octets reste volontairement conservée dans le répertoire normal de sauvegardes, mode0600, selon sa rétention habituelle de14jours. Le rapport ne publie aucune valeur privée de compte. Aucun succès de déploiement n'est déduit de la seule conservation des données.

**Régression de stockage historique confirmée puis corrigée :** cinq échecs attendus et huit gardes négatives vertes reproduisent exactement `store_notice_facts` → `holder/source alignment mismatch`, puis le résultat de backfill `failed/ValueError`. La comparaison normalise seulement les espaces des identifiants SIRET/BOAMP-COMPANY-ID à14chiffres ASCII, en conservant établissement, nom, groupes et liste complète des identifiants ; ni canonique ni archive réécrits. Vérification indépendante main : **95/95**, code0 en1,07s, nouveaux13cas et suites BOAMP existantes ; log `/tmp/kivou-v11-holder-fix-root-verification.log`, Ruff et format verts. Revue indépendante sans point bloquant. Cette preuve locale ne remplace pas la prochaine répétition complète sur données réelles et sa CI exacte.

**Revue du repli :** le garde-fou ferme désormais tous les writers de profil, dont POST `/target-icps` qui rematérialise les signaux, et pas seulement PATCH. RED quatre échecs attendus puis **75/75** tests rollback/nginx/déployeur en3,40s, code0, `/tmp/kivou-v11-profile-rollback-guard-green.log`. Nouvelle répétition sur nginx isolé de staging à20:37:25UTC : **18/18 requêtes conformes**, lectures/OPTIONS/auth/webhooks disponibles, processus isolé arrêté. Le nginx actif n'a pas changé. Le runbook précise également la vérification du processus servi après bascule partielle et l'arrêt des workers pendant un retour à l'ancien code ; le déployeur existant reste inchangé.

### Limites factuelles assumées

**Troisième répétition 893 :** conservation des 260 070 lignes privées, exports, contrats, six lots BOAMP et disponibilité des trois plans validés, mais budget de 800 ms refusé pour Aujourd'hui (p95 : 908,85 ms) et dossier entreprise (p95 : 1 194,95 ms). La copie et son dump sont supprimés, staging demeure 2599/0058. [Rapport détaillé et revue Q23](staging-copy-893312e.md). CI 893 entièrement verte : 6 478 backend, 752 frontend et 32 visuels ; elle ne remplace pas le gate de performance.

**Corrections ciblées des lectures :** l'historique d'un SIREN exact utilise les empreintes d'identité validées, y compris les SIRET BOAMP historiquement espacés, sans parcourir tous les marchés. Les identités rejetées/quarantinées ne peuvent plus revenir via le repli par nom ; le repli préexistant reste disponible en absence réelle de preuve. Aujourd'hui évite le troisième parcours du flux uniquement pour un compte payant dont les trois indicateurs d'activité de la semaine sont prouvés vides par SQL. Les relances, droits et indications de troncature restent inchangés ; Discovery conserve le parcours complet. Régressions RED puis GREEN, revue indépendante sans point bloquant. Vérification regroupée indépendante : **99/99, aucun skip, code 0 en 76,77 s**, `/tmp/kivou-v11-read-cost-root-gate.log`. Ces résultats ne constituent pas une nouvelle mesure p95 sur staging.

L'opérateur de mesure sur copie ajoute une sonde SQL diagnostique par route, uniquement **après les 120 mesures sans instrumentation**. Aucun SQL, paramètre, corps de réponse ou identifiant privé n'est exporté ; seuls nombre de requêtes, temps, lignes et chemin d'appel sont agrégés. Le temps SQL n'inclut pas nécessairement toute l'hydratation Python. **14/14 tests opérateur en 14,97 s**, code 0, revue indépendante sans blocage ; seuil de 800 ms et 20 échantillons inchangés. Harnais navigateur : **16/16 tests locaux** couvrent aussi le changement des deux profils Pro par l'interface et le retour aux trois portées initiales, sans mutation du profil. Ces outils ignorés ne sont pas une preuve de recette vive.

L'avis RAZEL 26-87113 et la consultation 25-2744 partagent un identifiant métier, mais leurs identifiants de procédure se contredisent et aucun lien explicite ne prouve la relation : pas de durée/start fabriqués. Les durées des sources concordantes sont affichées avec publication, nature (travaux/marché/bon de commande), période et reconductions. Pas d'hypothèse de main-d'œuvre si l'offre du profil est matériaux.

### Déploiement

Exécuté sur staging uniquement : première activation 610 à22:13:10 UTC, puis
correction frontend du prix catalogue et activation finale 7f2 à22:57:40 UTC.
La production n'a pas été modifiée. Les deux liens, le processus API physique,
la tête0060 et les octets HTML/JS/CSS servis ont été contrôlés. Le
[rapport final7f2](staging-release-7f2a208.md) consigne la recette trois plans,
le catalogue réel, les18visites des surfaces conservées et les notes UI avec
conflits/hors ligne. Trois sessions QA révoquées, quatre profils désactivés et
trois suppressions différées demandées ; aucune purge globale. Les plans payants
QA sont synthétiques, sans paiement Stripe ni fournisseur consommé.

CI finale :6505tests backend réussis (11skips,1xfail historique),756frontend,
32visuels, types/lint/builds verts. Les preuves frontend riches restent distinguées
des captures vives : aucun dossier payant riche en coordonnées n'a été vérifié
visuellement en live, le dossier GJG sélectionné n'en disposant pas. La
[preuve intermédiaire](staging-release-6107856.md) documente la copie complète,
les six p95 acceptés sous800ms et le véritable aller-retour de code Q31.
