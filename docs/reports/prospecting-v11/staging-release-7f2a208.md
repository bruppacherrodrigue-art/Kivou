# V11 — release staging finale 7f2a208

**Déployé et recette staging réussie.** État au 13 septembre 2026, 23:39 UTC
(14 septembre, 01:39 à Zurich). Les quatre parcours de recette réels sont passés ;
le nettoyage ciblé a été confirmé après la fenêtre de trente minutes.
La production n'a pas été modifiée. Les limites de couverture et les échecs
d'outillage intermédiaires sont explicités ci-dessous.

## Référence, périmètre et provenance des preuves

SHA exécutable servi : `7f2a2080bbc3dfe280d1a699e0e0e9183c30b203`.
Base staging : `2599d77840c073086051cbaa95441caf170afeac`.
Branche de validation : `feat/prospecting-v11-staging`, PR de validation vers la
base staging dédiée. Aucune fusion vers main ni modification de la production.
Un éventuel commit documentaire ultérieur ne sera pas présenté comme le SHA servi.

Le plan approuvé reste inchangé : `kivou-implementation-plan-2026-09-13/index.html`,
SHA256 **`5a535272a41ccf6a18fb0717ce6a7b0a9b5983472310653795be39f4aaf0c233`**,
revérifié localement pendant cette rédaction. Voir la
[référence d'exécution](implementation.md#référence-et-périmètre).

Ce rapport rassemble les journaux CI réellement lus, les contrôles de déploiement
et de couverture indépendants, l'état opérateur `release-state-7f2a208.md` et le
[rapport de première activation 6107856](staging-release-6107856.md). Les éléments
transmis par l'opérateur sont distingués des répétitions sur copie et des tests
locaux. Aucun identifiant de compte, cookie, secret ou export privé n'est publié.

## Delta final : correction du prix, backend inchangé

La revue complémentaire du panneau d'abonnement après l'activation 610 a identifié
une double division par 100 du prix affiché. `UpgradeDialog` transmet désormais
les unités mineures brutes au formateur commun, qui effectue déjà cette conversion.
Quatre régressions couvrent CHF/EUR, FR/EN et les centimes. Aucun checkout, portail
Stripe, montant facturé ou abonnement réel n'a été modifié pour cette correction.

La comparaison Git entre 610 et 7f2 ne contient que `UpgradeDialog.tsx`, ses tests
et le rapport intermédiaire 610. Backend, tests backend, migrations, exploitation
et dépendances sont inchangés. Les objets Git des arbres confirment notamment :

| Arbre | Objet identique dans les deux releases |
| --- | --- |
| `src` | `47a0b36c3fdcc7578f3d64b248d97de044faeb74` |
| `ops` | `b73b31ad75ca7865353c273f2e0e4455049ff9f3` |

Les preuves backend de la quatrième répétition complète 610 restent donc
applicables à ce code identique. **Aucune cinquième répétition complète sur 7f2
n'est revendiquée.** La restauration de contrôle du déployeur final est une
opération distincte ; elle ne remplace ni ne duplique artificiellement cette preuve.

## CI du SHA exact — sept jobs réussis

[Run 34786998271](https://github.com/bruppacherrodrigue-art/Kivou/actions/runs/34786998271),
démarré le 13 septembre à 22:30:22 UTC, terminé à **22:43:39 UTC** : sept jobs sur
sept en succès, pour le SHA 7f2 complet ci-dessus. Les quatre journaux backend ont
été récupérés et leurs résumés lus séparément, sans extrapolation depuis 610.

| Shard backend | Réussis | Skips | Xfail | Durée des tests |
| --- | ---: | ---: | ---: | ---: |
| 0/4 | 1 625 | 4 | 1 | 718,25 s |
| 1/4 | 1 627 | 2 | 0 | 720,94 s |
| 2/4 | 1 627 | 2 | 0 | 628,79 s |
| 3/4 | 1 626 | 3 | 0 | 728,57 s |
| Total | **6 505** | **11** | **1** | — |

Seize avertissements, aucun échec inattendu. Les skips et le xfail historiques
ne sont pas présentés comme des tests exécutés avec succès ; les compléments
PostgreSQL locaux et les smoke Stripe opt-in non exécutés sont décrits dans le
[rapport d'exécution](implementation.md#preuves-dexécution).

Frontend : **756 tests dans 73 fichiers**, **32 tests visuels**, builds client et
Founder, TypeScript et lint réussis. Le job frontend s'est terminé à 22:34:17 UTC.
Les suites backend, sélection des suites et décision globale sont également vertes.

## Quatrième répétition complète 610 — preuve réutilisée à code backend identique

Unité de répétition 610, du **21:44:42 au 21:59:21 UTC**, success et exit 0.
La restauration isolée est partie du schéma staging 0058 et a exercé la migration
vers 0060, sans employer la base vive comme fixture.

- **260 070 lignes dans 26 tables privées** et **34 exports historiques** préservés.
- Huit contrats notes, statuts, contacts et isolation validés ; quatre avis BOAMP
  et six lots de référence couverts, reprise idempotente sur cette sélection.
- Trois plans accessibles sur les comptes créés uniquement dans la copie, sans
  override d'authentification ni appel fournisseur.
- Copie et dump temporaire supprimés, liens et schéma vifs initiaux inchangés à
  la fin de cette répétition.

### Performance sur copie, pas mesure HTTPS vive

Lectures ASGI/TestClient authentifiées : un amorçage puis **20 mesures par route**,
p95 nearest-rank, budget **800 ms inchangé**. Profil de consultation de
**1 148 signaux courants**. Les sondes SQL ont été exécutées après les mesures,
hors échantillon ; ni proxy ni réseau client ne sont inclus.

| Route | p95, ms |
| --- | ---: |
| Aujourd'hui | 585,64 |
| Signaux | 313,23 |
| Entreprises | 362,96 |
| Annuaire | 393,31 |
| Détail signal | 296,82 |
| Dossier entreprise | 52,21 |

### Q31 : ancien code réellement servi puis retour compatible

La copie 0060 a servi les factories réelles candidate et 2599, avec nginx loopback
isolé et liens privés. Le garde a été fermé avant le changement de code ; les
lectures anciennes authentifiées et les assets ont fonctionné, les anciens writers
ont reçu 503, puis le code compatible a repris et ses écritures CAS ont été vérifiées.

La baseline privée de ce second contrôle compte **264 429 lignes dans 30 tables**,
après migration et préparation de la copie. Tombstones, révisions, historique de
contact et statut `new` ont été préservés. Aucun downgrade, aucun écrasement de la
base vive et aucun changement de ses liens. Les enfants et liens privés ont été
supprimés. Il s'agit d'une vraie répétition de repli isolée, pas seulement de tests
unitaires ni d'un rollback exécuté sur staging après activation.

## Dernier déploiement staging — effectif

Unité `kivou-v11-deploy-7f2a208.service`, invocation
`5971ce0e190c43759d16b2552a8ae683`, démarrée à **22:46:37 UTC**, terminée à
**22:57:40 UTC**, success et exit 0. Aucun deuxième déploiement de cette candidate
n'a été lancé pendant sa progression.

Sauvegarde acceptée à **22:50:58 UTC** : **2 883 388 839 octets**, rétention de
14 jours, aucune archive expirée supprimée à cette étape. Le déployeur inchangé
a effectué sa restauration et son contrôle Alembic avant la bascule ; cette fois,
la source vive était déjà en 0060. Trente unités systemd ont été synchronisées.

Contrôles après bascule :

- Backend et frontend pointent tous deux sur le SHA 7f2 exact, HEAD physique concordant.
- API active/running, **PID 1224116**, démarrée à **22:57:36 UTC**, cwd physique 7f2 ;
  `NRestarts=0` au contrôle opérateur.
- Readiness réelle réussie dès la première tentative ; tête unique
  **`0060_boamp_notice_facts`**.
- À **22:58:58 UTC**, les trois URL `/app/dashboard`, `/app/signals` et
  `/app/companies` répondent 200 ; HTML, JavaScript et CSS servis correspondent
  exactement aux octets de la release, selon la vérification opérateur.

| Artefact servi | SHA256 |
| --- | --- |
| `index.html` | `33ae29c67130d0c8f66c95aeb559966e568c82cce10096b06906f0d4f2e72c25` |
| `index-CV2lRDCo.js` | `3ed1a12aa42faf82fb2cbe91ed1a6696b1a62abae38d0db50a2e288dce385881` |
| `index-DjtWjRdL.css` | `30d6389bb56d1e5c275ff0291bb1ee5d5bc2aaa99b9c102d23b3ab262472c802` |

Le rechargement d'un onglet anonyme propre à 22:59:17 UTC a remplacé le bundle 610
par le bundle 7f2. Cette preuve reste qualifiée d'anonyme : elle ne vaut pas recette
d'une session authentifiée historique. Le garde nginx ouvert reste en place ;
aucune limite de débit n'a été augmentée pour la recette.

## Reprises BOAMP terminées — couverture bornée, non forcée à 100 %

Les reprises ont été exécutées sous 610, avant le delta frontend 7f2. Sélection
figée : **434 avis / 1 154 lots**, cinq lots de reprise de 100 avis au maximum.
La sélection et les cinq curseurs privés restent conservés avec leur liaison
d'origine à 610. **Aucun reset, changement d'enveloppe ou nouvelle tentative sous
un autre SHA pour contourner la limite de trois essais.**

Couverture de `boamp-notice-facts-v1` vérifiée indépendamment à 22:28–22:29 UTC,
puis répétée par l'opérateur principal à **22:32:30 UTC**, en transaction PostgreSQL
repeatable-read/read-only. Les **1 154 appels au véritable lecteur** valident
**825 faits courants**, sans erreur typée ni discordance d'identité ; 329 lots
n'ont pas de faits courants. Il existe **835 lignes de versions** pour ces 825 lots.
La seconde lecture a pris 0,407 s et n'a fait aucun appel fournisseur.

| Couverture des avis sélectionnés | Nombre |
| --- | ---: |
| Tous les lots couverts | 366 |
| Couverture partielle | 11 |
| Aucun fait | 57 |
| Au moins un fait | 377 |

Sur les 825 lots couverts : **673 durées sourcées**, 825 publications, descriptions
et titulaires, 821 montants attribués, 262 nombres maximum de reconductions,
278 valeurs maximum. Les **152 lacunes de durée sont explicites** ; aucune date
de démarrage ni durée manquante n'est inventée. Disponibilité de contacts publics
BOAMP du titulaire : 395 lots avec au moins un email, 346 avec un téléphone,
50 avec un site et 62 avec un nom de contact ; il ne s'agit pas de contacts uniques.
Ces comptes mesurent la présence dans les faits, pas l'exposition de valeurs aux
plans qui n'y ont pas droit. L'ingestion normale peut faire augmenter ces chiffres
après l'instantané, sans changer la sélection auditée.

Les cinq curseurs ont atteint leur fin : **pending 0**, **69 terminaux**, tous à
exactement trois tentatives. Terminal ne signifie pas automatiquement absence de
tout fait, notamment lorsqu'une couverture antérieure existe :

| Résultat terminal | Sans fait | Partiel | Complet | Total |
| --- | ---: | ---: | ---: | ---: |
| `source_facts_alignment_rejected` | 54 | 11 | 0 | 65 |
| `related_notice_limit` | 3 | 0 | 1 | 4 |

Les 365 avis non terminaux sont entièrement couverts. La politique conservative
tout-ou-rien peut refuser une nouvelle extraction d'avis mêlant lots identifiés
et lots sans contrat/titulaire vérifiable. La lecture de deux exemples publics
et une reproduction synthétique ont confirmé ce mécanisme, sans démontrer de
mauvais rattachement ni de rejet erroné d'un lot attribué exact. Sans snapshot
disponible des refus étudiés, on ne distingue pas formellement un résultat non
attribué d'une source incomplète. Aucun garde de concordance n'a été relâché.

Les quatre cas publics de référence Q23 restent couverts : 26-84423, 26-85899,
26-87113 et 26-88050, avec leurs six lots. Les portées de durée, reconductions,
annulation d'avis et hashes publics sont détaillés dans le
[rapport 610](staging-release-6107856.md#q23-revérifié-sur-la-base-vive).
Le timer de rétention activé conserve faits et provenance et ne purge que les
octets des archives expirées ; il n'est pas réactivé inutilement pour 7f2.

## Recette QA vive — préparation et premier refus

Le garde QA a été lancé à **22:59:43 UTC**. Trois nouveaux comptes dédiés ont été
réellement créés vers **22:59:46 UTC** : Découverte, Essentiel et Pro, avec deux
profils Pro. Essentiel et Pro utilisent des **droits d'abonnement synthétiques en
mode test**, lus par les véritables projections serveur : cela ne constitue pas
une preuve de paiement ou d'activation Stripe. Les sorties de préparation indiquent respectivement 6, 6 et 12 signaux,
sans appel fournisseur. Ce sont des totaux préparés, pas une promesse de déverrouillage
de tous les signaux en Découverte. Aucun compte existant n'est réutilisé ou modifié.

Les quatre verrous de workers ont été détenus par le garde pendant la fenêtre QA.
L'échéance maximale était **23:29:46 UTC environ** ; elle n'a pas été prolongée.
Le garde a confirmé le nettoyage avant de libérer ses verrous, puis a terminé
avec succès à23:29:48 UTC. Aucun rejeu n'a créé d'autres comptes de recette.
Les fichiers d'authentification restent privés ; leurs contenus et chemins ne
figurent pas dans ce rapport.

Les quatre préflights principal/écritures UI/paywall/surfaces conservées sont
passés à 23:00:49 UTC, sans HTTP ni mutation. Les tests locaux de ces outils et
leurs revues ne sont pas assimilés à l'exécution de la recette sur staging.

Le premier harnais réel a passé son bloc métier Découverte, puis a échoué dans le
parcours navigateur « Ajuster », après une rafale de lectures API. Cet échec est
conservé, sans requalification du harnais entier en succès. Lecture seule du
journal nginx safeJSON, fenêtre **23:00:45–23:02:30 UTC** :

| Route | Heure UTC | Statut |
| --- | --- | ---: |
| `/billing/status` | 23:01:16 | 200 |
| `/billing/status` | 23:01:21 | 429 |
| `/target-icps` | 23:01:21 | 429 |
| `/target-icps/options` | 23:01:21 | 429 |

Aucune entrée `/dashboard` dans cette fenêtre filtrée. La configuration nginx
active confirme **120 requêtes/minute, burst 40, nodelay et rejet 429**. Le lien
avec la rafale est cohérent ; le format safeJSON ne contient pas l'état amont
permettant d'attribuer formellement chaque 429 à nginx plutôt qu'à l'application.
Aucune IP, donnée privée ou ligne brute n'a été publiée. Ce diagnostic n'a fait
aucune requête HTTP et n'a modifié ni limite, ni compte, ni produit.

### Adaptations de l'outillage, sans modification du produit

Le harnais espace désormais les départs API de550ms, dans une file commune aux
lectures directes et au navigateur. Les fichiers statiques ne sont pas ralentis.
Les CLI sont exécutées séquentiellement. Aucun retry, statut ignoré, changement
nginx ou assouplissement du budget de performance produit n'a été ajouté.
Le temps d'attente de l'outil est exclu de son chronomètre API.

Découverte avait déjà passé ses50requêtes métier, dont31tentatives de requêtes
d'écriture synthétiques avec réponse,
sept conflits409 et deux refus422. La reprise valide strictement la preuve privée
initiale et le même compte/plan, puis confirme par sept GET les états finaux :
notes vides révision3, statut new révision4, contact manuel vide révision3 et
suivi révision1. Les écritures initiales ne sont ni répétées ni comptées comme
de nouvelles opérations. Essentiel et Pro gardent leurs parcours complets.

Un deuxième refus concernait uniquement le garde de l'outil d'écriture UI :
il exigeait une clé canonique dans le manifeste, alors que le client écrit sur
la clé **adressée**. Une entreprise source exacte sans ligne annuaire peut avoir
une clé canonique légitime non ajoutée au manifeste. Quatre GET sur Essentiel
ont confirmé ce cas, les droits de notes et la note vide. Le garde corrigé
conserve la clé adressée exacte, le sujet privé et la capacité serveur ; aucun
chemin réseau supplémentaire n'est autorisé. Deux régressions prouvent notamment
le refus d'une écriture vers la clé canonique non manifestée. Aucun sélecteur,
compte, alias métier ni code produit n'a été modifié pour contourner ce refus.

Vérifications indépendantes des opérateurs : pacing10/10 ; principal avec reprise
19/19 en21,675s ; trois compléments23/23 en22,473s ; dernier correctif UI9/9
en22,084s. Aucun skip. Les deux refus vifs originaux sont conservés dans les preuves.

## Résultats QA finaux — quatre parcours réels réussis

Les heures ci-dessous sont celles des fichiers de résultats locaux, en UTC.
Tous les contextes vérifient d'abord `/me`, puis le plan exact, avant navigation.
L'origine, les entités et les mutations permises sont limitées au manifeste.

| Parcours | Fin UTC | Résultat réel |
| --- | --- | --- |
| Principal | **23:20:01** | Trois plans ; Découverte et Pro1440/390/320, Essentiel1440. Notes2000/2001, CAS, tombstones, statuts réversibles/idempotents, contact personnel, suivi, navigation signal↔dossier et annuaire. Pro change ses deux profils et confirme les six portées API, puis rétablit le profil initial. Zéro erreur HTTP inattendue, pageerror ou requête bloquée dans le navigateur de la reprise. |
| Catalogue d'abonnement | **23:25:10** | Découverte1440/390 : ouverture réelle, prix API49/99 CHF/EUR, dialogue natif, absence de débordement, Escape et retour du focus.14GET navigateur par taille ; zéro mutation, paiement, portail ou fournisseur. |
| Pages conservées | **23:26:46** | Six routes × trois plans : ICP, abonnement, alertes, compte, profil du compte, sécurité. Un main, un titre, JS/CSS chargés ;63GET navigateur par plan, zéro requête bloquée. Préférences d'email désactivées avant et après. |
| Notes dans l'interface | **23:29:43** | Autosave et rechargement des notes signal/entreprise sur trois plans. Pro : deux vrais contextes, deux409 attendus, adoption de la version serveur, écrasement explicite puis brouillon hors ligne conservé et réessai validé après réouverture. Notes finales vides.4/4/13 tentatives PUT pour Découverte/Essentiel/Pro, dont l'essai Pro hors ligne ; zéro action d'authentification ou fournisseur. |

Les trois plans ont chacun passé les50requêtes métier initiales, dont31tentatives
d'écriture synthétiques du principal. Ce compteur inclut les sept409 et deux422
attendus : il ne signifie pas31modifications persistées. La reprise Découverte
ajoute sept lectures seulement.
Les maxima API observés de251/165/127ms pendant la reprise sont des maxima de ce
petit parcours HTTPS, **pas une nouvelle mesure p95** ni une garantie générale.
Les six p95 contractuels sont ceux de la copie représentative documentée plus haut.

### Revue des captures et limites de cette preuve

Revue indépendante UX : aucun défaut visuel bloquant démontré sur les vues
chargées. Sur les35captures du principal,22sont chargées,11intermédiaires et
deux partielles. Les dernières ne sont pas validées comme écrans finaux.
Les sept captures d'écriture UI et les deux captures de catalogue sont chargées.
Les aplats roses masquent les données privées ; les assertions UI/API, et non
la lecture d'un texte masqué, prouvent la persistance et la récupération des notes.

**Limite explicite :** le dossier payant GJG de ce parcours ne disposait pas de
coordonnées. L'affichage d'un dossier/titulaire payant riche n'a pas été revérifié
visuellement sur la base vive. Le complément prévu pour cette observation a passé
6/6tests locaux avec le vrai build, mais **n'a pas été lancé sur staging** : la
fenêtre QA était terminée après les contrôles requis. Aucun nouveau compte n'a
été créé pour prolonger cette observation facultative. La couverture payante
riche des32tests visuels isolés et les faits BOAMP réels sont des preuves séparées.
Aucun paiement, downgrade réel ou appel fournisseur payant n'est annoncé testé.

### Empreintes des résultats conservés

Les JSON et captures restent privés dans `output/playwright`, répertoires700 et
fichiers600. Les empreintes permettent de distinguer les preuves sans publier
leurs contenus sensibles ou les fichiers d'authentification.

| Résultat | SHA256 du JSON |
| --- | --- |
| Principal réussi | `f1749c1bdcc7d737f2c6709209adbdc3daa59e97a46d651a2fd9f75bef56089d` |
| UI notes réussies | `558dfbb47513c4aaf5af9e257b69022c8c2a84aa367df5ab40ee3fe0b2e99f07` |
| Catalogue réussi | `b41cacb47bac27933ca21e3068e55274ffc1b8189d9ef878109193e5c94c6009` |
| Pages conservées réussies | `d957ff349a5ff62d4bb37715691c5be59cf2696c23290e61c52ea09fd6740044` |
| Premier refus429 | `2cc9ee05ac2f434676f564183c42eac073d72b89b2b9cd1b918f73a13b1906ee` |
| Premier refus de garde UI | `c8aa9fa9e0f1c5da103db550399d433f0a3adbdbc211523a2521d9c98c67d15a` |

## Nettoyage et observation finale

Le garde a terminé automatiquement à**23:29:48 UTC**, success/exit0, après
**une seule tentative** de nettoyage confirmé : trois exports vérifiés en mémoire,
trois demandes de suppression différée et profils désactivés. `global_purge_called`
est faux. Les demandes de suppression à24h ne sont pas présentées comme une purge
physique déjà réalisée. Aucun compte utilisateur existant n'a été modifié.
L'onglet anonyme créé pour vérifier le nouveau bundle a été fermé ; ses seuls
messages console étaient les401 `/me` attendus sans connexion.

Relecture indépendante directe de la base à**23:37:27 UTC**, en transaction
repeatable-read/read-only : trois comptes encore présents, quatre profils exacts
en brouillon et aucun actif, trois sessions révoquées et aucune non révoquée,
trois préférences email désactivées, trois suppressions en attente et aucune
terminée. Les adresses de notification sont conservées : désactivation ne veut
pas dire effacement. La tête0060 est confirmée une nouvelle fois.

Après cette vérification, les trois fichiers de cookies locaux et leurs trois
copies serveur ont été supprimés, avec contrôle de leur absence. Ces fichiers
éphémères ne sont pas conservés pour récupération ; leurs sessions étaient déjà
révoquées. Les manifestes sans jetons et les preuves de recette restent privés.
Le seul conteneur PostgreSQL local étiqueté pour cette tâche a été arrêté et
auto-supprimé ; aucune base de production ou autre ressource utilisateur supprimée.

Contrôle serveur en lecture seule à**23:31:37 UTC** : API active PID1224116,
aucun redémarrage, cwd et deux liens7f2 exacts, readiness réussie à la première
tentative. Le garde n'a plus de processus ni de cgroup peuplé ; aucun détenteur
des quatre inodes de verrou n'a été trouvé à cet instant. Les workers normaux
peuvent reprendre leurs propres verrous ensuite.

Journal API :244entrées,23tracebacks de conflits CAS attendus
(14NoteRevisionError,3StatusConflict,6ContactConflict), aucune exception ASGI
générique. Le code journalise les causes chaînées des HTTP4xx ; ces traces ne sont
pas des500. Nginx depuis22:57 :1113requêtes, **zéro5xx**,23réponses409,
six422, trois429du premier burst et trois499. La relecture opérateur à23:37:27 UTC
retrouve exactement ces agrégats et zéro5xx. Ce constat borné ne signifie pas
que tout incident futur serait exclu. Aucun journal brut ni identifiant privé
n'est publié.

Selon le plan approuvé, les adverses L13 sont exécutés sur le build candidat et
PostgreSQL isolé ; L14 ajoute la recette métier staging sur trois plans. La
livraison ne prétend pas que les32scénarios adverses ont tous été provoqués sur
la base vive. Les résultats ci-dessus, la CI exacte et Q31 ferment les lots de
release, avec les limites explicitement conservées.
