# Entreprises : continuité des données et livraison live

## État

Implémentation locale et revues indépendantes terminées. Validation intégrée et
répétitions opérateur en cours. **Aucune activation staging ou production n'est
encore revendiquée.** Le plan HTML approuvé reste inchangé ; le complément
`docs/superpowers/plans/2026-09-14-company-continuity-live.md` suit cette livraison.

## Code et limites préservées

- Signaux et dossiers Entreprises partagent les coordonnées BOAMP attribuées au
  bon titulaire/établissement. Pas de contacts acheteur, de nouveau panneau
  Entreprise imbriqué, ni d'idée d'approche. Découverte reçoit uniquement les
  disponibilités réelles ; les valeurs premium sont retirées au serveur.
- Les demandes d'enrichissement sont durables, dédupliquées par SIREN, avec
  limite atomique de cinq demandes actives par compte et cent au total. Ce n'est
  pas un quota payant supplémentaire. Les budgets existants et les recherches
  nominatives restent distincts. Aucun fournisseur n'est appelé par un GET.
- Les résultats incomplets conservent les faits connus et leurs dates. Le dossier
  ouvert est actualisé sans perdre un brouillon de contact personnel.
- Le miroir production → staging exporte seulement les colonnes publiques
  autorisées, sans données client ni traces brutes. Il respecte les corrections,
  retraits, horloges locales et demandes de retrait. Un changement réel de domaine
  invalide seulement l'ancien rattachement Apollo et son cache devenu obsolète.
- L'annuaire se rafraîchit lorsqu'il est visible et inactif ; les filtres sont
  conservés. Les trente fixtures auditées disposent d'une quarantaine récupérable,
  par manifeste exact. Cette opération n'a pas encore été exécutée sur staging.

## Histoires et revues

La production a évolué vers `4c3bc6373e7bc2c1b24c413b6c7db523a44e15ba` pendant la
préparation. Les deux intégrations `87be689` et `b634605` conservent les évolutions
de production, dont le ciblage multi-signaux. Les migrations déjà déployées ne
sont pas réécrites. La jonction0061 conserve0058_model_call_budget et0060_boamp_notice_facts ;
0062 ajoute les demandes durables,0063 les métadonnées du miroir. Les nouvelles
migrations refusent un downgrade destructeur.

Le contrôle suivant a constaté la production sur
`543793c7df22adfa1ff96a09d91df854ff9f1cfa` (audit des SIREN dupliqués dans la
file de prospection). Cette évolution est conservée par la fusion `b2dcea8`.
La relance ciblage et contrats nginx/production a réussi **154 tests**.

Revues SPEC et qualité distinctes : raccord des migrations, contacts, demandes
durables et miroir. Les constats ont été reproduits avant correction : fraîcheur
par champ, retraits source, normalisation Decimal, révocation Apollo, brouillons,
horloge de fin réelle et pagination après changement de filtre. La vérification
supplémentaire du teaser téléphone seul a confirmé le comportement déjà correct.

## Preuves locales déjà acquises

- Frontend complet : **768 tests / 74 fichiers** ; **32 tests visuels**.
- TypeScript, ESLint, builds client et console fondateur réussis. L'avertissement
  existant de taille du bundle client reste présent ; ce n'est pas un échec de build.
- Migrations :287 pass /27 skips PostgreSQL facultatifs avant répétitions réelles.
- Contacts :43 tests ciblés relancés par l'intégrateur, tous réussis.
- Enrichissement :87 pass /1 xfail historique sur le lot élargi ;34 tests ciblés
  après la dernière correction de cache. Le lot UI de l'auteur compte30 tests.
- Miroir/quarantaine/protections opérateur :64 tests réussis après corrections.
- Copie hors réseau :24 nouveaux tests réussis, plus l'ancien helper58 pass /20
  skips PostgreSQL facultatifs. La relecture intégrateur a également été effectuée.

Les résultats qui se recouvrent ne sont pas additionnés. La première exécution
backend complète a saturé `/dev/shm` et ne constitue pas une preuve verte. Une
exécution sur `/tmp` et la CI exacte complètent la validation. L'intégration du
dernier ciblage pendant cette première collecte a aussi rendu une assertion
collectée obsolète ; le lot de ciblage frais a réussi76 tests. Le contrat nginx
a été adapté explicitement à la production V11 et à son seul alias catalogue.

La seconde suite backend, sur `/tmp`, s'est terminée avec **6 725 pass,
65 skips, 1 xfail et 2 échecs** : l'ancienne assertion nginx collectée avant sa
correction, et l'oubli du nouveau module dans l'allowlist des migrations
exhaustives. Les lots frais correspondants passent (154 tests ci-dessus ;
12 tests configuration/migration après reproduction RED et correction).
La CI `34822774471` sur `c40bae9` a réussi le frontend et trois shards backend ;
le quatrième a retrouvé uniquement cet oubli d'allowlist. Une CI complète du
candidat corrigé reste requise ; ces résultats ne sont pas présentés comme une
suite complète verte.

## Portes restantes avant activation

1. CI du candidat exact et contrôles intégrés terminés.
2. Copies PostgreSQL des deux schémas déployés, empreintes de toutes les lignes
   privées et des tables catalogue/budgets/faits existantes, migration et replay.
3. Ancien artefact réellement servi derrière le garde fermé sur la copie, puis
   retour au candidat sans downgrade ni perte des nouvelles écritures.
4. Sauvegarde retenue, configurations nginx/unités et limites fournisseurs
   vérifiées ; recette staging avant promotion du même code en production.
5. Santé, trois onglets, droits Découverte/abonnements, console fondateur et
   tâches planifiées réellement vérifiés après activation.

La production possède une clé Serper configurée ; staging n'en expose pas dans
ses fichiers d'environnement vérifiés. Le bouton d'enrichissement reste fermé par
défaut jusqu'au raccordement et à la vérification effective du worker. Aucun
budget, campagne, tarif ni volume d'envoi n'a été modifié par cette livraison.

## Répétitions opérateur du 14 septembre

Les releases **inactives** `staging-e79e8fb…` et `production-e79e8fb…` sont
préparées, dépendances verrouillées installées. Les liens servis restent
respectivement sur `7f2a208…` et `543793c…`. Les opérateurs sont des outils séparés
du produit ; leurs chemins, SHA Git, racines physiques et bases jetables sont
vérifiés explicitement. Revue SPEC puis qualité indépendante : CLEAR.

- Copy-driver : **48 tests** indépendamment relancés ; accepte le port PostgreSQL
  omis en le normalisant à5432, sans modifier les URL déployées. Les deux
  préflights réels ont ensuite réussi.
- Rollback : **22 tests**, nginx local réel compris, indépendamment relancés.
- Copie production migrée/rejouée vers `0063_catalogue_mirror` : **11 824 lignes
  sur29 tables préservées**, export des11 comptes inchangé ; inclut876 entreprises,
  1 839 appels modèles et8 lignes de budgets partagées.
- L'ancien artefact production `543793c…` a ensuite été réellement servi derrière
  le garde fermé sur cette copie, puis remplacé par le candidat. Authentification,
  lecture facturation, note de2 000 caractères, tombstones et reprise des écritures
  CAS validés. Les processus privés sont arrêtés, aucun fournisseur appelé.
- Sauvegarde production retenue,1 667 553 809 octets, SHA-256
  `5495972b9a7254d08db6cc002f85988b88e3db63e81f96827a5b5a9eddd85bf8`.
- Sauvegarde staging retenue,3 204 872 170 octets, SHA-256
  `1f3a6f67a75427582da13921a1f23c05dbacca186d336ca5d5b2c61adfd69b5e` ;
  restauration et contrôles staging encore en cours à cette rédaction.

Rapports et dumps privés conservés sur chaque hôte sous
`/var/tmp/kivou-company-copy.*`. Les captures de configuration sont protégées
dans `/srv/kivou/rollbacks/company-live-e79e8fb`. Aucune copie ni sauvegarde n'a
encore été supprimée. Après un arrêt forcé, exiger absence de connexions et OID
inchangé avant toute suppression de la seule base jetable créée par l'opérateur.

Le catalogue production a été validé en lecture seule :876 lignes publiables,
1 350 515 octets, aucune donnée client dans cette projection. Le backfill BOAMP
administratif reste nécessaire après activation pour les anciens signaux : la
sélection courante sur30 jours comporte28 avis couvrant239 matérialisations.
Utiliser l'outil existant, un manifeste exact et un curseur, par lots de25 ; pas
de recherche au chargement d'une fiche ni de lancement global non borné.

La revue globale a aussi reproduit le crash d'un compte incomplet accédant à une
route V11 sans `ProspectingProvider`. Le correctif ciblé ramène ces routes à la
confirmation du profil, conserve uniquement l'intention d'abonnement valide et
laisse facturation/réglages accessibles. Le rapprochement utilise les règles du
routeur, y compris les chemins avec majuscules ou segments encodés. Ses51
régressions et102 tests adjacents passent ; les revues SPEC puis qualité sont
terminées. La vérification intégrée du nouveau candidat reste requise.

La CI `34825013511` sur `e79e8fb` a validé le frontend puis a été annulée avant
la fin des quatre shards backend. Le journal expose uniquement
`The operation was canceled` ; aucune cause d'annulation n'est attribuée sans
preuve. Une nouvelle CI du candidat final remplace cette preuve incomplète.

Relance finale après le correctif du routeur : **819 tests frontend /75 fichiers**,
TypeScript, ESLint, builds client et Founder réussis. Ruff global et diffcheck
réussis. La comparaison `git diff --quiet e79e8fb -- src ops pyproject.toml uv.lock`
confirme que le backend, ses dépendances et les migrations des répétitions sont
inchangés ; le delta produit final est uniquement la frontière de navigation.
