# PR3 — Entreprises CRM et déploiement reproductible

## Objectif

Remplacer les anciennes vues Entreprises par une liste CRM centrée sur les
titulaires, reliée directement aux endpoints `/companies`, et faire de
`ops/bin/kivou-deploy.sh` l'unique chemin de déploiement staging/production.

## Écran Entreprises

`/app/companies` affiche le titre « Entreprises », le sous-titre « Les
titulaires de vos signaux, avec où vous en êtes », une recherche et les quatre
segments de statut avec leurs nombres. Les nombres sont calculés à partir de
requêtes serveur par statut ; la liste courante reste paginée par curseur et
« Charger plus » concatène sans doublon.

Le tableau contient Entreprise, Ville, Marchés, Total, Dernier et Statut. Les
totaux restent séparés par devise et utilisent des chiffres tabulaires. Une
valeur absente devient « — ». La ligne sélectionnée suit l'URL
`/app/companies/{company_key}`.

## Panneaux imbriqués

La fiche entreprise est un panneau droit utilisant la même mécanique modale et
responsive que `SignalDrawer`, large de 50 % au-dessus de 1100 px. Elle affiche
le nom, l'identifiant officiel formaté, la ville, le site HTTPS éventuel, les
actions « Marquer contactée » et « A répondu », les cartes `SignalRow`, la note
et l'historique. Une carte de marché ouvre `SignalDrawer` au-dessus du panneau
sans perdre la sélection entreprise.

La note est sauvegardée au blur et affiche un état enregistré seulement après
réponse du serveur. L'historique ne prétend pas être un journal complet : l'API
n'expose que `contact_status` et `contacted_at`, donc l'interface montre
uniquement le contact daté lorsqu'il existe, sinon « — ».

`Companies.tsx`, `CompanyProfile.tsx` et leurs anciens tests sont supprimés. La
nouvelle page consomme exclusivement `GET /companies`, `GET
/companies/{key}`, `POST /companies/{key}/contact` et `PUT
/companies/{key}/note`; aucune résolution SIRET n'est effectuée dans le
navigateur.

## Déploiement

`ops/bin/kivou-deploy.sh` reçoit un environnement (`staging` ou `production`)
et un SHA complet. Il valide des chemins et noms fermés, prépare une release
identifiée par ce SHA avec son build frontend, exécute `uv sync --frozen --extra server --extra
postgres`, puis `npm ci` et le build frontend.

Avant toute mutation vive, il lance `kivou-backup.sh`, restaure la sauvegarde
acceptée dans une base jetable appartenant au rôle applicatif, et exécute
Alembic sur cette copie. Toute erreur de sauvegarde, restauration ou répétition
termine le script non-zéro avant migration vive, arrêt ou bascule. Après succès,
il migre la base vive, bascule atomiquement les liens backend/frontend,
redémarre systemd et appelle `kivou-api-readiness.sh`. La release précédente
reste présente et ses chemins sont journalisés pour rollback.

Le script est idempotent : si les deux liens actifs portent déjà le SHA demandé
et que la readiness réussit, il sort avec succès sans nouvelle sauvegarde ni
migration. Les secrets restent dans l'EnvironmentFile de l'hôte et ne sont
jamais imprimés. Le runtime acquisition n'est ni reconfiguré ni modifié.

## CI rapide et décisionnelle

Un job de détection de chemins s'exécute sur chaque PR. Le frontend ne tourne
que pour ses fichiers ou le workflow ; le backend ne tourne que pour Python,
les tests, les dépendances ou l'ops. Le backend est réparti en quatre shards de
fichiers, chacun avec son PostgreSQL isolé. Sur `main`, les deux surfaces sont
toujours forcées afin qu'une seule exécution finale valide l'ensemble.

Un job d'agrégation stable échoue si un job requis a échoué et accepte les jobs
explicitement ignorés par le filtre. Les tests déjà mis en quarantaine gardent
leurs `TODO PR3`/`TODO PR4`; PR3 réactive et remplace les tests Entreprises et
ses goldens.

## Validation

Les tests frontend couvrent liste, recherche, segments, pagination, panneau,
deux transitions de contact, sauvegarde de note et superposition du drawer.
Les goldens Entreprises sont régénérés. Le test shell simule un échec de
répétition et prouve l'absence de migration vive, restart ou bascule. Les tests
du workflow vérifient le routage par chemins et les quatre shards.
