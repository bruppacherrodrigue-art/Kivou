# PR6b — panneaux unifiés et lieu client

## But

Corriger les écrans connectés Signaux et Entreprises sans modifier le parcours
d’atterrissage ni les services de recherche gérés dans les autres fenêtres. Le
frontend ne conserve qu’un `SignalDrawer` et qu’un `CompanyPanel`. Le lieu
affiché devient une donnée backend cohérente et les états de contact deviennent
compréhensibles sans bouton désactivé muet.

## Frontend canonique

`SignalDrawer` ne possède plus de branche historique. Le rendu décisionnel
validé devient son seul rendu. Les chaînes et le CSS propres à la grille
Titulaire/Acheteur/Lieu/Publié le/CPV, à « Historique du titulaire » et à
l’ancien « Pour vous » sont supprimés.

`CompanyPanel` remplace `CompanyDrawer` et `CompanyProfileV2`. Il expose deux
densités d’un même composant : `holder`, intégrée au bloc Titulaire du signal,
et `full`, utilisée par les routes Entreprises et annuaire. Les sous-blocs
contact, identité, marchés et actions vivent dans ce fichier et partagent les
mêmes règles d’affichage.

Un marché de la fiche appelle la navigation vers `/app/signals/{signal_key}`
avec un état de retour `{ href, companyName }`. La route Entreprises est alors
démontée. `SignalsFeed` ouvre le signal demandé et passe ce retour au drawer,
qui rend « ← Retour à {entreprise} ». Aucun panneau signal ne peut donc être
monté au-dessus d’un panneau entreprise.

## Lieu client

Le lieu brut publié reste intact dans `place_of_performance`. Une projection
`client_location` est calculée côté backend au moment où les faits sont
persistés : localité humaine du lieu d’exécution, sinon localité publiée de
l’acheteur, sinon département résolu, sinon absence. La projection conserve sa
base (`execution_city`, `buyer_city` ou `department`) pour l’audit, mais le
frontend ne reçoit qu’un lieu affichable.

Le résolveur rejette les agrégats nationaux et les jetons techniques des
sources, notamment « Territoire métropolitain », codes commune, codes postaux
isolés, codes NUTS et libellés de type DECP/BOAMP. Les réponses liste et détail
emploient la même projection, sous la forme `Nice (Alpes-Maritimes)` lorsque la
ville et le département sont connus. Un backfill borné calcule cette projection
pour les signaux des comptes de recette avant les captures.

## Contact et enrichissement

En Découverte, `CompanyPanel` affiche le mur « Inclus dans Essentiel —
49 €/mois » et un lien vers `/tarifs`.

En Essentiel, une entreprise dont l’annuaire est incomplet affiche « Contact en
cours de recherche — revenez dans une heure ». Le composant appelle une route
idempotente qui remet les `winner_enrichment_job` associés en file. Cette action
n’appelle aucun fournisseur et ne consomme aucun quota décideur. Le worker
existant reste seul responsable des appels d’enrichissement.

Une fois l’annuaire exploitable, le seul bouton primaire est « Trouver le
décideur ». Son clic appelle la chaîne existante et consomme une recherche du
quota. Une absence ou une défaillance du fournisseur produit « Service
temporairement indisponible, réessayez plus tard » et un événement structuré
journalisé. Le bouton ne reste jamais grisé sans explication.

## Hiérarchie des actions

Le contact ou son mur est la seule action primaire. « Marquer contacté »,
« Sauver » et « Ignorer » utilisent le style secondaire. Les sources sont des
liens texte placés sous les actions. Les champs absents sont omis.

## Validation en deux temps

La première phase implémente les composants réels sous le flag commun, construit
le frontend, redéploie staging et prend les captures RAZEL-BEC en Essentiel et
Découverte. Aucun test n’est lancé avant la validation visuelle de Rodrigue.

Après son OK seulement, la seconde phase met à jour et exécute les tests du
composant, du contrat et les goldens, puis la CI. Aucune fusion ni mise en
production n’intervient avant ces contrôles.
