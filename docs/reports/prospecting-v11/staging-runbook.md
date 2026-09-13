# V11 — déploiement et repli staging

Périmètre exclusif : `staging.kivou.eu`, hôte SSH `kivou-staging`. Production exclue. Référence précédente lue : `2599d77840c073086051cbaa95441caf170afeac`. Aucun downgrade des migrations 0059/0060 : les données privées et archives sont conservées.

## 1. Conditions préalables

- Exécuter suites backend, frontend, typecheck, lint, build, isolation CSS, build Founder et tests navigateur. Relire les écarts visuels ; conserver les contrats publics inchangés.
- Vérifier `git diff --check`, absence de données de maquette dans les imports applicatifs, pas de secrets dans les fichiers, migrations à tête unique 0060.
- Commit exécutable de cette branche, push de cette branche seulement, vérifier le SHA et CI. Ne pas merger main/production pour rendre le commit récupérable.
- Si main a avancé indépendamment de staging, utiliser pour la PR de CI une référence de validation pointant sur la base staging vérifiée. Ne pas fusionner des migrations ou composants de production hors périmètre pour déclencher la CI ; ce contrôle valide l'exact delta staging.
- Sur staging, noter cibles de `/srv/kivou/app`, `/srv/kivou/frontend`, HEAD via utilisateur kivou et état Alembic. Conserver configuration nginx précédente sous un répertoire `mktemp -d /etc/nginx/.kivou-v11-evidence.XXXXXX`, accès root.
- Fetch explicite de la branche ou du SHA candidat dans `/srv/kivou/source` via utilisateur kivou. Le déployeur fetch main, mais accepte le SHA déjà présent : ne pas modifier son mécanisme ni le checkout partagé pour déployer.
- Avant activation, lancer `docs/reports/prospecting-v11/legacy-preflight.py` avec le Python/code candidat et l'environnement staging protégé. La connexion PostgreSQL vive est forcée en lecture seule ; les migrations et rapprochements s'exécutent exclusivement dans une base SQLite en mémoire. Entrées bornées à 10 000 lignes par table ; sortie agrégée sans identifiants ni valeurs privées. Ce contrôle vérifie la conservation des notes/statuts existants et les collisions d'identité des comptes ayant déjà des données privées. Les audits complets de l'étape 4 restent obligatoires après migration.

## 2. Installer le garde-fou avant la bascule

Le site TLS staging inclut `/etc/nginx/kivou-prospecting-writes.conf`. Son état normal est le fragment versionné `ops/nginx/kivou-prospecting-open.conf` (commentaires seulement). Son état de repli est `kivou-prospecting-maintenance.conf`.

Suivre l'installation candidate de `ops/README.md` : fichiers issus du SHA candidat, rendu STAGING_HOST/port réel et chemins d'includes sous le répertoire candidat, `nginx -t -c <config candidate>` **avant publication**, sauvegarde des fichiers actifs, install `.new` puis mv sur le même filesystem, second `nginx -t`, reload. Ne pas remplacer aveuglément une configuration hôte divergente ; comparer les directives avant publication. Ne pas ouvrir implicitement un garde-fou déjà fermé.

Répéter le fragment fermé dans une configuration nginx isolée : PUT note/statut/contact, POST lookup et tout POST/PUT/PATCH/DELETE sur `/target-icps` ou ses descendants → 503 ; GET, OPTIONS, authentification et webhook restent routés. POST ICP doit être fermé aussi : il crée un profil et rematérialise ses signaux. Le test ne contacte aucun fournisseur. Le rollback reste protégé tant que ce fragment fermé est conservé, y compris si l'ancienne application ne le connaît pas.

## 3. Release atomique

Utiliser exclusivement `ops/bin/kivou-deploy.sh staging <SHA40>` via une unité `systemd-run` **asynchrone**, avec EnvironmentFile `/etc/kivou/staging.env`, WorkingDirectory `/srv/kivou/source`, Type`oneshot`, `TimeoutStartSec=infinity` et `RemainAfterExit=yes`. Ne pas employer `--pipe` pour cette longue opération : une coupure SSH ne doit ni supprimer le rapport ni masquer le code retour. Conserver le journal systemd, contrôler `LoadState`, `ActiveState`, `SubState`, `Result` et `ExecMainStatus` de l'unité exacte ; ne pas interpréter les valeurs par défaut d'une unité déjà collectée comme une réussite. Connexion SSH avec keepalive. Arrêter l'unité terminée seulement après collecte de sa preuve ; ne jamais afficher le fichier d'environnement.

Le script effectue build, sauvegarde, restauration jetable, migrations sur copie puis base vive, bascule backend/frontend et readiness. Contrôler son code retour et le journal expurgé. Il **ne revient pas automatiquement** à la release précédente en cas d'échec de readiness après bascule.

**Reprise après échec partiel : ne pas relancer aveuglément.** Si les deux liens pointent déjà sur le candidat, le chemin « release déjà active » vérifie la readiness mais ne redémarre pas l'API. Des liens corrects et `/openapi.json` 200 ne prouvent donc pas le code chargé. Relever `systemctl show kivou-api.service --property=MainPID,ExecMainStartTimestamp,FragmentPath,ExecStart`, puis les cibles `/proc/<MainPID>/cwd` et `/proc/<MainPID>/exe` avec `readlink -f` ; le répertoire doit être la release physique attendue, et l'interpréteur seul n'identifie pas un SHA. Ne pas afficher `/proc/<pid>/environ`. Après vérification des liens et de l'unité candidate, effectuer un `systemctl restart kivou-api.service` contrôlé, puis `/srv/kivou/app/ops/bin/kivou-api-readiness.sh kivou-api.service 8000` ; relever à nouveau PID, heure de démarrage et répertoire, puis vérifier les assets frontend du candidat. Ce contrôle concerne la reprise après activation partielle, pas une raison de modifier le premier déploiement normal.

0059 ajoute révisions/workflow/alias/suivi/contact personnel ; 0060 ajoute snapshots/faits. Les anciens enregistrements privés restent présents. Aucune modification du tarif, du SDK Stripe ou des fournisseurs d'enrichissement.

## 4. Reprises bornées après migration

Lancer les commandes avec utilisateur kivou, WorkingDirectory `/srv/kivou/app` et environnement systemd protégé. Garder uniquement rapports d'identifiants opaques, nombres et codes fermés — pas de notes, contacts, payloads ou exceptions brutes.

1. `python -m signals.client_value.identity_audit --phase registry --limit 100` : dry-run par défaut ; examiner le rapport. Refaire avec `--execute`, puis reprendre `--after-company-key` du rapport jusqu'à `complete`. Ne pas sauter les pages.
2. Même audit `--phase accounts --limit 100`, dry-run puis execute ; reprendre les deux curseurs `--after-account-id` et `--after-company-key`. Les conflits privés restent isolés par compte ; ne pas fusionner manuellement les valeurs ambiguës.
3. `python -m signals.client_value.notice_backfill --limit 100` : dry-run sans réseau/écritures. Exécuter ensuite `--execute --limit 100 --cursor-file <chemin privé staging>` ; curseur durable, trois tentatives maximum, trois sources liées maximum par avis. Reprendre le même curseur et consigner couverture/rejets. Ne pas passer une relation floue pour gagner artificiellement une durée.
   Pour les avis du périmètre actif et les quatre cas de recette, résoudre d'abord les `source_event.event_key` par lecture SQL puis répéter `--event-key <clé exacte>` (1–100 clés) avec un curseur dédié. Toute reprise répète le même ensemble complet de clés ; ne jamais fabriquer un pending ni réutiliser le curseur global. Les quatre avis26-87113/26-84423/26-85899/26-88050 sont présents sur la base staging vérifiée (six lots au total).
4. `python -m signals.client_value.notice_retention --limit 1000` : dry-run. Vérifier puis activer `kivou-notice-retention.timer` installé par le déployeur ; son service utilise `--execute --limit 1000` chaque jour. La purge concerne seulement les bytes expirés, jamais les faits extraits.

## 5. Recette du SHA servi

- HEAD backend, symlink frontend, fichiers JS référencés et readiness cohérents avec le SHA candidat.
- Authentification puis Aujourd'hui → Signaux → fiche → entreprise → annuaire → prospection. Desktop/mobile, ouverture clavier/Escape/retour focus, pas de débordement horizontal.
- Une seule barre de ciblage ; changement profil/offre/zone/montant modifie données ET compteurs. Annuaire indépendant ; aucun détail caché rendu dans Signaux.
- Compte de recette uniquement pour écritures : notes conservées après reload, 409 concurrent sans écrasement, statut réversible, suivi, interlocuteur personnel. Ne pas changer les notes/statuts du compte commercial réel.
- Découverte : vérifier le JSON, pas seulement le flou visuel ; champs premium absents, présence annoncée seulement si donnée réelle, aucun lookup déclenché par GET. Compte payant : coordonnées existantes visibles et enrichissement explicitement demandé.
- BOAMP : acheteur unique, titre/montants/lot/publication/durée/reconductions sourcés. Pas de date de démarrage inventée. Pas de panneau d'approche ; note privée à sa place.
- Aucun paiement réel, email commercial ou appel fournisseur consommant un quota pour la recette. Test checkout via les tests de contrat et parcours sans confirmation de paiement réel.

## 6. Repli compatible avec les nouvelles écritures

Si un défaut bloquant exige l'ancien exécutable :

1. **Fermer les écritures avant tout changement d'application** : tester le fragment fermé dans la configuration candidate, publier atomiquement `kivou-prospecting-maintenance.conf` comme `kivou-prospecting-writes.conf`, `nginx -t`, reload, prouver 503 sur une route d'écriture de recette et lecture/auth disponibles.
2. **Geler les workers avant la bascule** : enregistrer avec `systemctl show` les états actif/activé et PID des paires `.timer`/`.service` `kivou-ingest-boamp`, `kivou-ingest-simap`, `kivou-tender-notices`, `kivou-ingest-ted`, `kivou-ingest-decp`, `kivou-for-you` et `kivou-notice-retention`. Arrêter leurs timers avec `systemctl stop`, puis attendre la fin naturelle des services, sans les tuer ; vérifier absence de démarrage en attente et `MainPID=0`. **Acquérir et vérifier**, avant de changer les liens, les quatre verrous `/run/kivou/ingestion.lock` (BOAMP/SIMAP/tender-notices), `/run/kivou/ingest-ted.lock`, `/run/kivou/ingest-decp.lock` et `/srv/kivou/run/for-you.lock` dans un détenteur opérateur indépendant de `/srv/kivou/app`, maintenu jusqu'au correctif. Ces verrous ne sont pas présumés détenus et ne doivent pas être supprimés/recréés. Un éventuel `systemctl mask --runtime` n'est une barrière que si `LoadState=masked` est confirmé : les unités installées dans `/etc/systemd/system` peuvent primer sur `/run`. Aucun reboot sans blocage persistant validé. **Si drainage, acquisition ou maintien ne sont pas vérifiables, conserver V11 avec le garde 503 et résoudre avant tout repli** ; cette section pose des préconditions, pas un nouveau keeper prêt à exécuter.
3. Conserver la base vive en 0060. Vérifier les cibles `.previous`, puis basculer les deux liens vers leurs releases explicitement vérifiées et redémarrer le service API. Jamais de restauration de la sauvegarde sur les écritures privées déjà reçues ; jamais d'alembic downgrade.
4. Readiness et GET de recette. Les fonctions de prospection en écriture restent temporairement indisponibles ; ne pas rouvrir pour contourner une incompatibilité de révision.
5. Déployer un correctif compatible 0060, vérifier son processus réellement servi et la recette notes/statuts/contacts. Ensuite seulement tester et publier le fragment ouvert, retirer exclusivement les masques posés pour ce repli, libérer les quatre verrous et restaurer les états initiaux des timers/services enregistrés à l'étape 2 ; ne pas activer globalement des unités auparavant désactivées. Les données saisies sur V11 redeviennent disponibles.

Consigner temps, SHA, tests, états des workers et du garde-fou ; ne jamais qualifier de rollback réussi une ancienne interface qui peut écraser des révisions nouvelles. Le garde ferme les mutations de prospection, pas toute écriture SQL : les lectures/authentifications conservées peuvent encore entretenir leurs métadonnées. Ces restrictions concernent le repli ; elles ne bloquent pas un premier déploiement normal dont les préconditions sont validées.
