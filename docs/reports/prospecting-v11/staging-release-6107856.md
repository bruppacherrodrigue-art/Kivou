# V11 — répétition et première activation 6107856

État au 13 septembre 2026, 22:24 UTC. Ce rapport est une preuve intermédiaire,
pas la clôture L14 : le contrôle complémentaire du panneau d'abonnement a révélé
une double conversion du prix en unités mineures. Une correction frontend et une
nouvelle candidate sont requises avant la livraison finale. Aucun paiement n'a
été lancé et aucun montant facturé n'a été modifié.

## Candidate et CI

SHA exécuté : `6107856f2f1d7dfa0218b8cf9b0b42db672a1e73`.
Base staging : `2599d77840c073086051cbaa95441caf170afeac`.
La branche de validation reste séparée de main ; aucune production modifiée.

[CI exacte 34783736909](https://github.com/bruppacherrodrigue-art/Kivou/actions/runs/34783736909)
terminée à 21:54:58 UTC, sept jobs réussis. Les quatre journaux backend ont été
relus séparément : 1 625 + 1 627 + 1 627 + 1 626 = **6 505 tests réussis**,
11 skips, un xfail historique, 16 avertissements, aucun échec inattendu.
Frontend : **752 tests / 73 fichiers**, **32 tests visuels**, types, lint et builds
client/Founder réussis. Les exclusions PostgreSQL historiques ont leur complément
local ; les smoke Stripe nécessitant des clés ne sont pas annoncés exécutés.

## Répétition complète réelle — acceptée

Unité `kivou-v11-rehearsal-6107856.service`, du 21:44:42 au 21:59:21 UTC,
invocation `d6af07befa9448b7af80fb7e92f708f5`, résultat success, exit 0.
Le rapport durable privé confirme les trois gates et le nettoyage, et a été
relu indépendamment par l'opérateur principal.

- Migration sur restauration isolée, jamais staging comme fixture de tests.
- Conservation exhaustive de **260 070 lignes / 26 tables privées** et des
  **34 exports historiques** ; huit contrats notes/statuts/contacts/isolation validés.
- Audits : registre 666 identités exactes, 363 non résolues ; comptes 2 942
  rapprochements, 1 353 non résolus. Aucune fusion au nom pour réduire les refus.
- Quatre avis / six lots BOAMP stockés en une passe ; reprise idempotente,
  aucun pending ni terminal sur cette sélection de référence.
- Disponibilité des trois plans sur comptes de copie, sans override d'auth ni
  fournisseur externe : Découverte 3/6 signaux, Essentiel 6/6, Pro 6/12 sur deux profils.
- Base copiée et dump temporaire propres supprimés ; source vive encore 0058
  et liens 2599 inchangés à la fin de cette répétition.

### Performance sur copie

Mesures ASGI/TestClient authentifiées, sans proxy ni réseau client : un amorçage
puis 20 lectures séquentielles par route, p95 nearest-rank, budget **800 ms inchangé**.
Les sondes SQL diagnostiques viennent après les 120 mesures et n'en font pas partie.

| Route | p95, ms |
| --- | ---: |
| Aujourd'hui | 585,64 |
| Signaux | 313,23 |
| Entreprises | 362,96 |
| Annuaire | 393,31 |
| Détail signal | 296,82 |
| Dossier entreprise | 52,21 |

Ces valeurs remplacent le refus de performance de la troisième copie 893 ;
elles ne sont pas présentées comme des mesures HTTPS de la base vive.

### Q31 — véritable aller-retour de code

La copie 0060 a servi les factories réelles candidate puis 2599, derrière un nginx
loopback isolé et des liens privés. Fermeture du garde avant ancien code, lectures
authentifiées anciennes et assets fonctionnels, anciens writers refusés 503,
retour candidate puis réouverture et écritures CAS vérifiées.

La seconde baseline exhaustive conserve **264 429 lignes / 30 tables** : elle
inclut les ajouts de migration et de préparation QA antérieurs à cette baseline.
Tombstones, révisions, historique contacted et statut new préservés. Aucun
downgrade, aucun remplacement de la base vive, aucun service global basculé.
Processus enfants et liens privés supprimés ; zéro override d'auth ou service fournisseur.

Tests des opérateurs finaux : **83/83**, sans skip, code 0 en 33,94 s.
Harnais principal : **16/16** tests locaux ; complément notes UI : **7/7**.
Ces tests d'outillage ne sont pas une recette navigateur vive.

## Première activation staging — effective

Garde nginx ouvert installé et rechargé à 22:00:55 UTC après validation du candidat
et de la configuration active. Empreinte du fragment ouvert :
`1ef686d2935c4f552cd91a9fbba98eedf9e3c1a181b9daf9dab618a31a13d989`.
Sauvegardes privées de configuration conservées.

Déployeur versionné inchangé, unité `kivou-v11-deploy-6107856.service`, invocation
`4282f4bfadf845cf81c95d460c8fff53`, du 22:01:27 au **22:13:10 UTC**, exit 0.
Sauvegarde de 2 878 530 522 octets acceptée à 22:06:01, restauration et migration
de contrôle effectuées avant la migration et la bascule vives. Aucune base
temporaire propre au déployeur restante.

Contrôle indépendant après activation :

- Les deux liens backend/frontend et le HEAD physique correspondent au SHA 610.
- API active/running, PID **1216665** démarré à **22:13:06 UTC**, cwd physique 610.
- Readiness réelle réussie dès la première tentative ; tête unique **0060_boamp_notice_facts**.
- Les trois URL HTTPS `/app/dashboard`, `/app/signals`, `/app/companies` répondent 200.
- Leurs octets HTML, JS et CSS correspondent exactement aux fichiers de la release.

| Artefact effectivement servi | SHA256 |
| --- | --- |
| index.html | `6b23d8e3855e177eb0ae082f36410bc14d2a13f2e1bc2a2e86a0a8bb1c0f8151` |
| index-CrBGbSeA.js | `584063cf7586d8bf44980317426a1cf2697f6a53b55c723553672d37d1969d86` |
| index-DjtWjRdL.css | `30d6389bb56d1e5c275ff0291bb1ee5d5bc2aaa99b9c102d23b3ab262472c802` |

## Reprises vives et couverture

Sélection figée : **434 avis / 1 154 lots**, avis BOAMP des profils actifs à leur
révision courante, plus les quatre références. Cinq lots de reprise, maximum
100 avis par passe et trois tentatives par avis. Empreinte de sélection :
`49d5df34bf99631e82402c8189738d578ee89a74281c491ff28df920b14a7394`.
Les curseurs privés sont conservés et jamais remis à zéro. Les résultats terminaux
et la couverture finale doivent compléter le rapport de livraison.

Audit registre exécuté : 11 pages, **666 registered / 363 unresolved**, complete.
Audit comptes après registre : 43 pages, **2 942 resolved / 1 353 unresolved**,
complete. Le dry-run identité exécute puis annule sa transaction ; il ne constitue
pas une transaction PostgreSQL READ ONLY. Le dry-run BOAMP ne fait ni réseau ni
écriture DB, mais peut figer la sélection et créer ses verrous privés.

La politique conservative peut refuser un avis complet si un de ses lots n'a pas
de contrat/titulaire vérifiable. Deux exemples publics inspectés en lecture seule :
26-77363 (un lot identifié et un lot undisclosed sans contrat), 26-78046 (deux et un).
Le lot non vérifiable ne remplit pas le contrat de concordance ; cela ne prouve pas
un rejet erroné d'un lot attribué exact. Sans snapshot disponible pour ces refus,
on ne distingue pas formellement résultat non attribué et source incomplète.
26-80641 illustre le refus explicite de la borne des trois avis liés. Aucun garde
n'a été relâché pour augmenter la couverture ; aucun succès partiel silencieux.

Rétention : dry-run **eligible 0 / purged 0** ; service effectif contrôlé, timer
explicitement activé, active/waiting/enabled, échéance 14 septembre **03:40:56 UTC**.
Seuls les octets d'archives expirées sont concernés, jamais les faits ou leur provenance.

### Q23 revérifié sur la base vive

Lecture strictement READ ONLY des quatre avis/six lots réussie ; les quatre hashes
publics concordent avec la copie acceptée et le [rapport Q23 détaillé](staging-copy-893312e.md).

- **26-84423** : publication 1er septembre, 24 mois de travaux, trois lots et leurs
  groupements/titulaires exacts. Collecte 22:17:08 UTC.
- **26-85899** : publication 6 septembre, maximum 12 mois par bon de commande,
  pas une durée totale de marché. Collecte 22:15:15 UTC.
- **26-87113 / RAZEL-BEC** : publication 10 septembre, trois reconductions maximum ;
  aucune durée ou date de démarrage ajoutée. Collecte 22:18:13 UTC.
- **26-88050 / GJG FONCIERE** : publication 12 septembre, durée du contrat 240 mois,
  statut d'avis annulé distinct d'une annulation de travaux. Collecte 22:18:14 UTC.

## Surfaces conservées et suite

Navigateur anonyme réel sur neuf routes : accueil, produit, tarifs, exemple de
signal, contact, informations légales, login, signup, mot de passe oublié.
Toutes 200, un main/h1, aucun débordement à 1440 px, aucune erreur de page ou HTTP
inattendue, aucune requête externe bloquée, **zéro mutation**. Aucun formulaire soumis.

À ce point, aucun des trois nouveaux comptes QA vifs n'a été créé. La correction
du prix et sa CI doivent précéder la recette finale authentifiée, les captures
d'accès ordinateur/mobile et le nettoyage ciblé. Ne pas déduire la clôture L14
du seul succès de cette première activation.

### Delta de correction du prix, validé localement à 22:29 UTC

Seule expression runtime changée : `UpgradeDialog` transmet les unités mineures
brutes au formateur commun, lequel effectue déjà la division par 100. Quatre
régressions reproduisent le défaut puis vérifient CHF/EUR, FR/EN, prix entiers et
centimes, sans checkout ni portail. Revue indépendante sans point important restant.

La première vérification TypeScript a refusé une option de test `exact` non prévue
par Testing Library ; elle a été retirée sans changer les assertions de prix. Le
premier full frontend a donc refusé le test qui compile le bundle. Après correction,
la nouvelle exécution indépendante est **756/756, 73 fichiers, code 0 en 61,02 s**
(`/tmp/kivou-v11-price-frontend-root-green.log`), types et lint verts. Ni tests ni
seuils n'ont été désactivés. Une comparaison Git confirme **zéro changement backend,
migration, exploitation ou dépendance** depuis la release 610 répétée et servie.
La nouvelle CI exacte et la bascule finale restent à confirmer séparément.
