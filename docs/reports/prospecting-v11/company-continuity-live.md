# Entreprises : continuité des données et livraison live

## État

Implémentation, revues indépendantes, CI exacte et déploiement terminés.
**Production sert `88f1891` ; staging sert `cae05b3`, au même produit V11.**
Les écritures sont rouvertes et les tâches planifiées rétablies. La couverture
BOAMP reste partielle sur six avis complexes, décrits en fin de rapport.
Les sections chronologiques ci-dessous distinguent chaque
preuve et chaque candidat. Le plan HTML approuvé reste inchangé ; le complément
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

## Intégration de la nouvelle branche mail de production

Cette équivalence vaut pour `f374546`, pas pour les intégrations suivantes.
La CI `34826773517` a échoué lors de la collecte : son checkout de fusion incluait
les migrations mail arrivées entre-temps sur `main`. La collecte du candidat seul
réussissait, y compris avec les 49 dépendances exactes de CI ; l'ajout des
migrations amont reproduit les erreurs de têtes Alembic multiples. La collecte
masquée par le filtre du script de sharding expliquait l'absence du détail dans
le journal, pas une réussite des tests.

La fusion `3ee4934` conserve intégralement `main` à `2d4aa6d`, dont le contrat
mail de 110 mots. Une jonction additive `0064_company_mail_merge` est vérifiée
avant la prochaine CI ; aucune révision historique n'est réécrite. Les preuves
opérateur `e79e8fb` ci-dessus restent identifiées par leur SHA, sans les attribuer
au nouveau candidat. Le déploiement devra répéter la migration PostgreSQL sur
copie avec son SHA exact avant toute migration de la base active.

La répétition staging `e79e8fb` est maintenant réussie : **284 545 lignes sur
33 tables préservées**, export des 37 comptes inchangé, avec 33 entreprises,
755 snapshots et 1 638 faits BOAMP. Le retour réel à l'ancien artefact `7f2a208`,
derrière le garde fermé, puis au candidat a réussi : **282 438 lignes privées
et catalogue contrôlées**, huit contrats privés, authentification, facturation,
note de 2 000 caractères et reprise CAS. Aucun fournisseur appelé, aucune
configuration ni lien actif modifié. Les processus de répétition sont arrêtés ;
zéro connexion à la base jetable constatée avant sa suppression ciblée.

Le manifeste BOAMP initial est conservé sur production dans le répertoire privé
de l'opérateur : 28 événements exacts pour 239 signaux courants. Il a été établi
en lecture seule ; aucun backfill, envoi commercial ou changement de quota n'a
été exécuté.

La jonction 0064 passe les revues SPEC et qualité distinctes. Collecte avec les
dépendances CI : **6 856 tests**, sans erreur. Vérification intégrateur explicite
avec `-o addopts=` : **17 tests** de migrations, configuration pytest et mail
shadow, sans exclusion des suites lentes. Revue qualité : sept tests de migration
indépendants. Les assertions mail historiques ont été raccordées au contrat amont
110 mots, sans modifier son runtime ; Ruff global et diffcheck passent.

La seule base jetable staging a été supprimée après revalidation de son OID,
absence de connexions et empreinte de sauvegarde. La sauvegarde de 3,2 Go et les
rapports privés restent sur l'hôte. La copie production reste conservée. Aucun
compte, entreprise ou schéma actif n'a été supprimé.

## Dernière préparation opérationnelle

La production a ensuite activé `2d4aa6d239aae713d204dd864cfa24403208278c`
indépendamment de cette livraison : backend, client et Founder sont raccordés,
schéma réel `0059_prospect_mail_word_limit_v2`. Ce runtime est déjà conservé par
notre fusion ; les nouveaux opérateurs acceptent ce point de départ uniquement
avec le sélecteur explicite `--expected-source-head`. Le défaut reste 0058 et
refuse la nouvelle tête observée sans sélection ; staging reste limité à 0060.
Les protections SHA, racine physique, URL et tête réellement restaurée restent
inchangées. Une nouvelle sauvegarde et répétition production sont requises.

La composition du nouvel alias catalogue nginx a révélé une directive
`proxy_buffering off` dupliquée par son include partagé, également présent sur
l'hôte. La directive locale redondante est retirée ; la valeur reste imposée par
l'include. Régression reproduite puis corrigée avec nginx réel, contrôles
syntaxiques et contrat d'alias exact. Vérification intégrateur combinée :
**199 tests réussis**, nginx réel compris, sans skip ; revue nginx indépendante :
37 tests réussis. Les opérateurs adaptés passent séparément 88 tests.

Le compte utilisateur est connecté sur staging avec son abonnement Essential
pour la future recette ; aucune note, contact, cible, facture ou recherche n'a
été modifié par le navigateur. Le frontend de la CI `34828412795` sur `8095ccb`
est réussi ; la CI du candidat incluant les derniers ajustements reste requise.

## Validation `cae05b3` et activation staging en cours

La CI exacte `34829355015` est intégralement réussie à 10:06 UTC : frontend,
quatre shards backend et porte décisionnelle. La nouvelle répétition PostgreSQL
production, de `2d4aa6d` / 0059 vers `cae05b3` / 0064, a réussi : 11 944 lignes
sur 29 tables et les exports des 11 comptes sont préservés, ainsi que les
876 entreprises, 1 845 appels modèles et huit lignes de budgets. Sauvegarde
retenue : 1 667 780 247 octets, SHA-256
`30fe52001de24b1dc8f72c9d8514234b25515302013fc279ee2e4895009f86cf`.
Le retour réel à l'ancien runtime puis au candidat a également réussi sur
cette copie : 10 268 lignes contrôlées, huit contrats privés, écritures bloquées
pendant l'ancien runtime puis CAS repris. Aucun lien actif ni fournisseur touché.

La composition nginx production complète du candidat passe `nginx -t` avec les
trois autres sites existants. Le jeton catalogue dédié est préparé dans des
fichiers privés inactifs ; aucun secret fournisseur n'est transféré à staging.
Les tests navigateur de continuité stricte ont reçu une revue indépendante
SPEC et qualité : 13 tests réussis, dont masquage serveur Discovery et fermeture
du navigateur, sans appel distant dans cette suite locale.

Le déploiement staging `cae05b3` a démarré à 10:07 UTC, après fermeture du garde
d'écriture et arrêt des seuls timers concernés. Le déployeur existant réalise
une nouvelle sauvegarde/restauration/migration de copie avant toute bascule.
La recette réelle, la quarantaine et la synchronisation ne sont pas encore
annoncées réussies.

À 10:09 UTC, `main` et la production ont avancé indépendamment à `9c5d613` :
retrait de la localisation du pied de page des e-mails, sans changement de
schéma ni des onglets V11. Cette modification est intégrée sans altérer son
runtime ; le test shadow historique est aligné après échec reproduit.
Vérification ciblée : 11 tests passent. Une nouvelle CI du candidat intégré
reste nécessaire avant sa promotion production ; les preuves `cae05b3` restent
attribuées à leur SHA exact.

## Recette staging et promotion du candidat `88f1891`

Staging sert effectivement `cae05b3`, schéma `0064_company_mail_merge`, API saine
et garde d'écriture rouvert. Le bootstrap public a inséré874 entreprises et
actualisé2 ; son replay est sans changement sur876 lignes. Les30 fixtures du
manifeste ont été mises en quarantaine par `suppressed_at`, sans suppression ;
replay sans changement. Le catalogue affiche877 lignes visibles,30 masquées,
876 lignes suivies par le miroir. Le compte Essential de l'utilisateur a été
contrôlé en lecture seule. La synchronisation périodique attend encore son
activation au moment de cette section.

Sauvegarde fraîche staging retenue :3 206 729 913 octets, SHA-256
`45300c3cc71622af6dbba2223f4c4a1c0cb7340a44c84f04e5b8f13f410a6be8`.
Les comptes QA sont des créations isolées en mode Stripe TEST, sans fournisseur
ni e-mail. La recette principale réelle des trois plans réussit :50 requêtes
par plan,31 mutations de nos propres données,7 conflits attendus et2 validations
422 attendues. Notes2 000/2 001, CAS/tombstones, contacts manuels, suivi, quota
inchangé, changement des deux profils Pro et captures1440/390/320 contrôlés.
Le complément navigateur d'écriture réussit également : autosauvegarde,
rechargement, effacement, conflit explicite et brouillon hors ligne Pro.
Le garde confirme l'export et la neutralisation des trois comptes QA, la
révocation des sessions et les profils désactivés ; aucune purge globale.

Le contrôle strict additionnel demandait initialement un même signal débloqué
sur les trois plans. Son échec vient de l'échantillon : le titre brut de l'avis
RAZEL est vide, donc la règle normale Découverte ne l'offre pas. Aucun titre,
date ou droit n'a été modifié pour forcer ce test. La seconde tentative de seed
a refusé ce cas et sa transaction a été intégralement annulée. Une preuve SQL
en lecture seule confirme zéro compte de ce run avant l'arrêt ciblé de son
garde bloqué ; les cinq verrous sont libérés et les rapports d'échec conservés.
La recette complémentaire distingue désormais la continuité payante et le
signal verrouillé/Dossier masqué de la même entreprise en Découverte.

La CI `34831911514` du candidat exact
`88f189196f80bb8f93566398b0d5fddc95a379ed` est entièrement réussie à10:32 UTC :
frontend, quatre shards backend et porte décisionnelle. Sa répétition production
depuis `9c5d613` /0059 conserve11 716 lignes sur29 tables, les exports11comptes,
876entreprises,1 851appels modèles et8budgets ; migration/replay0064 réussis.
Le repli ancien runtime/candidat sur copie conserve10 034 lignes et réussit les
huit contrats privés. Sauvegarde1 667 738 586octets, SHA-256
`ece811513d9583f8e4b3e86cee22f0c885e19007932c48d0b36b2a5ac9014b90`.

La PR251 est fusionnée dans `main` par `7305dd4` ; son arbre est strictement
identique au candidat88 testé. Staging reste identifié `cae05b3` : l'unique delta
produit vers88 conserve le pied de page mail amont, aucun delta V11/frontend,
opérateur ou schéma. Pas de seconde répétition staging de plusieurs gigaoctets
sur son disque limité uniquement pour ce changement de pied de page.

À10:57 UTC, nginx production valide le fragment fermé : mutation de prospection
503, accueil200, authentification non connectée401. Le drop-in API dédié charge
le jeton catalogue, l'environnementPRODUCTION et le flag enrichissement encore
faux ; `production.env`, la configuration acquisition et les budgets restent
inchangés. Le déployeur stock `kivou-company-deploy-88f1891` est lancé à10:58 UTC.
Les timers métier concernés sont temporairement arrêtés et leurs services drainés ;
leur état initial et les configurations sont conservés pour restauration.

## Production activée et contrôles après livraison

Le déployeur stock a terminé avec code0 à11:01:51 UTC. Backend, client et
Founder pointent sur `production-88f189196f80bb8f93566398b0d5fddc95a379ed` ;
schéma réel0064, API et Founder actifs, readiness prête et `/healthz` FounderOK.
Le HTML public charge les mêmes fichiers client que l'artefact installé :
`index-BYgXrCmu.js` et `index-DjtWjRdL.css`. Les trois routes V11 et réglages
répondent200 ; les frontières facturation/Founder sans authentification401.
Une seule tentative de connexion production avec les identifiants staging
n'a pas authentifié le compte : aucune réinitialisation ni impersonation.
La recette authentifiée des trois offres a donc été faite sur staging, pas
présentée comme une session client production ; les contrats privés production
sont éprouvés sur la copie exacte décrite plus haut.

La sauvegarde fraîche propre à cette bascule est retenue hors du cleanup du
déployeur :1 668 096 957octets, permissions0600, SHA-256
`03739f2638423d233cfd99502a66473be69e6fa8977c7b197eb3de277c002564`.
L'archive de configuration avant bascule est privée et conservée. La sauvegarde
hors hôte existante a réussi à03:23 UTC ; elle n'est pas confondue avec cette
nouvelle sauvegarde locale. Aucun dump n'a été restauré sur la base vive.

- Identité : preview puis application,59 alias exacts et8 sans identifiant
  univoque ;73 sujets de comptes résolus et38 non résolus, aucun conflit privé
  détecté. Les cas non résolus ne sont pas fusionnés par nom.
- Enrichissement explicite : navigateur Chromium lancé avec les protections
  du service, sans réseau ; worker requests-only code0, verrou réellement acquis,
  file vide, coût0. Cela prouve le raccord, **pas un résultat fournisseur réel**.
  Le timer60s est activé et le processus API chargé confirme flagtrue, publication
  PRODUCTION et jeton dédié. Aucun débit de recherche nominative de recette.
  Staging garde le flag et les workers fournisseurs désactivés, Serper absent.
- Miroir : GET sans jeton404, POST405, lecture HTTPS authentifiée validée depuis
  staging. Source877 entreprises ; premier import automatique1insertion et876
  inchangées, replay877inchangées. Timer15min activé. Staging compte878 entreprises
  visibles (dont sa ligne locale conservée),30 fixtures masquées et877 entrées
  suivies par le miroir. Aucun contact privé ou secret fournisseur transféré.
- Recette stricte finale :12 captures chargées, deux largeurs et trois plans,
  mêmes valeurs/sources/dates en payant, même entreprise canonique masquée et
  signal verrouillé en Découverte. Zéro mutation navigateur, fournisseur ou
  requête hors périmètre. Les quatre captures principales ont été relues
  visuellement. Le dernier ajustement du harnais ne réclame plus l'alias du
  signal verrouillé, légitimement404 ; aucun droit produit n'a été modifié.
  Régression RED puis15tests locaux relancés verts ; recette live ensuite verte.
  Cleanup du garde confirmé :3exports,3comptes neutralisés, profils désactivés,
  sessions révoquées, MainPID0. Les copies locales des quatre fichiers d'accès
  ont été retirées ; aucune purge globale.
- Retention : preview0éligible/0purgé, timer production activé. Tous les timers
  métier suspendus ont retrouvé leur activité précédente. La restauration de
  budget prévue le15septembre reste active. Empreintes de `production.env`,
  `acquisition-production.json` et `api-attribution.env` strictement inchangées.
- À11:09 UTC, garde ouvert publié atomiquement et nginx revalidé/rechargé.
  La mutation sans corps de recette atteint de nouveau la validation API422,
  au lieu du503 de maintenance ; aucune mutation client. Readiness après
  réouverture prête, aucune entrée de journal prioritéerreur API/Founder depuis
  l'activation dans la fenêtre contrôlée.

## Réserve explicite : six avis BOAMP non complètement pris en charge

La sélection initiale reste exactement28avis couvrant239 signaux courants.
Les quatre passes bornées ont ajouté94faits sur136awards, depuis22avis ;
six avis restent en réserve après au plus trois tentatives chacun,0pending et
6terminal. `coverage_complete=false` est conservé, sans reset du curseur,
élargissement de sélection ni faux rattachement.

Le diagnostic indépendant des sources officielles retrouve42awards sur ces
six avis :34faits seraient extractibles individuellement,8résultats sont rejetés.
L'atomicité par avis écarte également ces34faits. Les limites ne sont pas une
régression du delta88 : extracteur/backfill inchangés depuis476b22f et aucun
fait production antérieur n'a été retiré. Les avis26-82975/26-88152 comportent
quatre résultats multicontrats ;26-83102 un résultat à plusieurs offres/parties ;
26-86748 un groupement à plusieurs SIRET par organisation. Les résultats rejetés
de26-84973/26-85072 sont **non attribués**, sans contrat ni gagnant. Il s'agit donc
de six attributions complexes et deux résultats non attribués, pas de huit lots
ambigus. Leur prise en charge fine demande une évolution testée du parseur et
du contrat de backfill ; elle n'a pas été improvisée dans la bascule.
