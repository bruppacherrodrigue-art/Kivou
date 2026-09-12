# Aperçu dashboard Signaux et Entreprises

## But

Produire un aperçu navigateur rapide de la maquette Signaux + Entreprises dans le chrome visuel du dashboard Kivou, avant toute implémentation des composants réels.

## Périmètre

- Un document HTML statique et interactif, sans backend ni authentification.
- Une sidebar, un en-tête de profil et un résumé de plan visuellement alignés sur le dashboard client actuel.
- Deux vues accessibles par la navigation : Signaux et Entreprises.
- Le contenu et les libellés proviennent du fichier fourni `kivou-maquette-entreprises.html`.
- Le contenu principal respecte le conteneur centré de 1 280 px, la liste de 640 px et le panneau de 600 px.
- Sous 1 280 px, la liste et le panneau occupent chacun la moitié de l’espace disponible.
- Sous 900 px, la liste est affichée en premier et le panneau sélectionné devient une feuille plein écran.

## Interaction

- La navigation latérale permet de basculer entre Signaux et Entreprises.
- Une ligne sélectionnée affiche son panneau associé.
- Le bouton de fermeture de la feuille mobile revient à la liste.
- Les boutons métier sont uniquement décoratifs dans cet aperçu.

## Données et sécurité

- Toutes les données sont fictives ou déjà présentes dans la maquette fournie.
- Aucun appel réseau applicatif, aucune écriture en base et aucune donnée de compte réelle.
- L’aperçu est servi uniquement par le serveur HTTP local existant.

## Livrable et validation

- Un fichier non applicatif sous `output/previews/` afin d’éviter toute confusion avec l’implémentation réelle.
- Une URL `http://localhost:4176/...` directement ouvrable.
- Validation visuelle attendue avant le début de l’étape 1 sur staging.
