# Port exact des frontends de référence

Statut : approuvé par le propriétaire produit le 29 août 2026.

## Objectif

Remplacer les interprétations visuelles actuellement servies par Kivou par un
port direct des deux frontends de référence :

- site public : `https://kivou-refonte.bruppacherrodrigue.chatgpt.site/`,
  source `efaa4160f4c3bbbdb01448bf9228772491e614f5` ;
- application connectée :
  `https://kivou-dashboard-refonte.bruppacherrodrigue.chatgpt.site/`,
  source `05212f2da5197699e6a9bb191556afcb2dcf1bb3`.

La référence commande le DOM, les composants, les classes, les styles, la
composition, la densité, les espacements et le comportement responsive. Kivou
reste l'autorité exclusive pour les données, les droits et les actions.

## Cause de la régression

Les PR précédentes ont reconstruit une interface inspirée des captures au lieu
de porter les sources de référence. Le plan de la PR 111 demandait notamment de
conserver les anciens blocs `NeedList`, `EvidencePanel` et `FeedbackControl`
dans une nouvelle composition, ce qui empêchait par construction une identité
visuelle avec la maquette.

Les tests nommés « fidélité » validaient des libellés, des destinations et une
structure sémantique générale. Ils ne comparaient ni le DOM et les classes de
la source, ni le rendu visuel. Une CI verte ne prouvait donc pas l'identité des
frontends.

Le correctif porte les sources exactes et ajoute des contrôles capables de
détecter ce type de dérive.

## Autorités et invariants

### Autorité de présentation

Les deux commits de référence ci-dessus sont normatifs. Aucun composant visible
ne doit être réinventé lorsque son équivalent existe dans ces sources.

Les seules différences autorisées avec une capture de référence sont :

- les valeurs provenant des API réelles ;
- l'identité et la formule du compte connecté ;
- les droits et états de verrouillage décidés par le backend ;
- les états honnêtes de chargement, d'erreur ou d'absence de données ;
- le préfixe `/app` nécessaire pour séparer les routes SPA des routes API.

### Autorité d'exécution

Les contrats actuels restent autoritaires :

- `GET /me` pour la session et la langue du compte ;
- `GET /signals` et `GET /signals/{signal_id}` pour le flux et le détail ;
- `GET /companies/{company_key}` uniquement après autorisation ;
- `/target-icps` pour les profils de ciblage ;
- `/billing/status`, `/billing/plans`, `/billing/checkout` et
  `/billing/portal` pour les offres et Stripe ;
- `/notification-preferences` pour les alertes ;
- les points d'entrée existants de note, pertinence et contact restent
  inchangés côté backend.

Le matching, l'authentification, Stripe, les permissions, le paywall, Apollo,
Instantly, Hermes, les migrations métier et la production ne sont pas modifiés
par le port visuel.

## Langue

Le site public est rendu en français, sans sélecteur FR/EN visible. L'anglais
reste une préférence du compte connecté et se change depuis les paramètres du
compte.

Comme aucun point d'entrée ne permet actuellement de modifier cette préférence,
`PATCH /me` acceptera uniquement `{ "locale": "fr" | "en" }` et renverra la
même forme que `GET /me`. La mise à jour porte sur la locale du compte. Elle ne
change ni les identifiants, ni la session, ni les permissions et ne nécessite
aucune migration. La réponse de session sera relue après succès afin que les
libellés du frontend et les données localisées du backend restent cohérents.

## Correspondance des routes

| Référence dashboard | Kivou staging | Écran |
| --- | --- | --- |
| `/` | `/app/dashboard` | Vue d'ensemble |
| `/signals?signal=:id` | `/app/signals/:id` | Liste et détail d'un signal |
| `/signals` | `/app/signals` | Liste et sélection initiale |
| `/companies` | `/app/companies` | Entreprises autorisées |
| `/companies?company=:id` | `/app/companies/:id` | Fiche entreprise |
| `/targeting` | `/app/icps` | Profil de ciblage |
| `/settings` | `/app/settings` | Compte |
| `/settings/billing` | `/app/billing` | Facturation |
| `/settings/notifications` | `/app/notifications` | Notifications |

Les routes publiques existantes restent `/`, `/produit`, `/tarifs`,
`/exemple-de-signal`, `/contact`, `/informations-legales`, `/login` et
`/signup`.

## Architecture du frontend

### Couche de présentation de référence

Le frontend Vite conserve React Router et les fournisseurs de session actuels,
mais reçoit un port direct :

- du `SiteHeader`, du `SiteFooter`, du logo, des pages publiques et du CSS du
  site public de référence ;
- du `KivouDashboardShell`, des compositions de pages et du CSS du dashboard de
  référence ;
- des pages d'authentification, d'onboarding et de checkout du dashboard de
  référence, adaptées aux contrats Kivou existants ;
- des breakpoints et comportements mobile de ces sources.

Les composants sont adaptés de Next vers React Router sans modifier leur arbre
visible. Les liens Next deviennent des `Link` React Router et les redirections
Next deviennent des routes ou navigations React Router.

Les styles publics et connectés sont isolés sous deux racines pour éviter
qu'une règle globale du dashboard ne régresse le site public, ou inversement.

### Adaptateurs de données

Une couche de modèles de vue transforme les réponses actuelles sans inventer
de valeur :

- un élément de feed alimente exactement une carte `signal-item` ;
- le détail alimente le hero, le brief en quatre points, les faits publiés, le
  périmètre disponible, les questions à confirmer, la fiche entreprise et la
  note ;
- les champs absents affichent `Non publié` dans l'emplacement prévu ;
- un signal verrouillé utilise la carte verrouillée de la référence et ne
  provoque jamais de requête de détail interdite ;
- les prix de la matrice publique sont issus exclusivement de
  `GET /billing/plans` ;
- la formule, le badge d'accès, le compte et le ciblage de l'en-tête proviennent
  des ressources authentifiées.

Les éléments fixes de démonstration (`Mode démonstration`, `Compte démo`, faux
signaux, faux ciblages et faux prix) ne sont jamais portés comme données. Leur
emplacement et leur style sont conservés, mais leur contenu est remplacé par
l'état réel correspondant.

### Actions et données complémentaires

Le port ne réintroduit aucun ancien bloc visuel. Les actions réelles sont
placées dans les contrôles équivalents de la référence :

- source officielle dans `Ouvrir l'avis` ;
- entreprise dans `Voir l'entreprise` ;
- note dans `Note sur ce signal` ;
- abonnement dans la page Compte/Abonnement ;
- notifications dans la page Compte/Notifications.

Le port n'ajoute pas de contrôle absent de la référence pour exposer une
ancienne action. La source officielle et la note restent accessibles dans les
contrôles prévus par la maquette. Les charges de preuve continuent d'alimenter
les faits et la source affichés, et les anciens points d'entrée backend restent
compatibles, mais aucun panneau de preuve ou de pertinence supplémentaire ne
peut réapparaître sans approbation explicite d'une différence visuelle.

## États honnêtes

Chaque ressource conserve son chargement, son erreur et sa relance locale. Une
erreur de facturation n'efface pas les signaux ; une erreur de notification
n'efface pas le ciblage ; une erreur de détail ne remplace pas la liste.

Les squelettes, alertes, listes vides et cartes verrouillées utilisent la même
géométrie que la référence. Aucun état ne présente une donnée précédente comme
actuelle et aucune donnée de démonstration ne sert de repli silencieux.

## Validation

### Contrats automatisés

- tests de structure sur l'arbre, l'ordre et les classes des composants de
  référence ;
- tests de mapping de chaque charge utile réelle vers le modèle de vue ;
- tests des routes, liens, CTA, formulaires et redirections ;
- tests fail-closed des signaux verrouillés et des entreprises ;
- tests des actions Stripe et notification sans mutation réelle en CI ;
- tests de la préférence de langue et de sa relecture de session ;
- tests frontend et backend complets, build, typecheck et lint.

### Régression visuelle

Des captures de référence générées depuis les deux commits normatifs sont
versionnées avec les tests afin que la CI ne dépende pas des dépôts privés de
maquette. Des rendus déterministes comparent le port à ces références dans le
même Chromium, aux largeurs 1440 px et 390 px. Les pages critiques couvrent au
minimum :

- accueil public, produit, tarifs et exemple de signal ;
- vue d'ensemble, workspace signal, entreprises, ciblage et compte ;
- shell, navigation ouverte et états verrouillé/vide/erreur.

Le seuil ne permet aucune différence structurelle ou de composant. Les zones
de texte variables sont alimentées par des fixtures équivalentes pour rendre
la comparaison stable. Le ratio de pixels différents est limité à 0,1 %,
réservé à l'anticrénelage du navigateur ; les boîtes de mise en page, les
polices, les couleurs, les espacements et les breakpoints doivent être exacts.
Toute autre différence doit être explicitement documentée et approuvée avant
fusion.

### Staging

Après CI verte et fusion :

1. construire le frontend depuis le SHA exact de `main` ;
2. publier une nouvelle release frontend atomique sur le staging seulement ;
3. vérifier le SHA servi et conserver le backend existant sauf nécessité
   stricte liée à la locale ;
4. contrôler directement toutes les routes publiques et connectées, en desktop
   et mobile, avec la session de test ;
5. comparer les captures staging aux références ;
6. vérifier les données API, la console, Stripe TEST, le paywall et les actions
   autorisées ;
7. ne rien déployer en production.

Le travail n'est terminé que lorsque le frontend réellement visible sur
`staging.kivou.eu` satisfait ces contrôles.
