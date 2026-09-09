# Contrat de rendu des alertes — 9 septembre 2026

## Objectif

Une alerte transactionnelle doit reproduire exactement la carte Aujourd'hui du
même signal. Elle ne doit pas exposer les formulations internes de récence.

## Contrat

Pour chaque signal, le rendu contient, dans cet ordre : titulaire, objet,
montant formaté, lieu, date, phrase « Pour vous », puis le bouton « Ouvrir ».
Avant la carte, il n'y a aucun texte. Après la carte, seuls le lien de
désinscription et le pied légal sont autorisés.

Les chaînes « Une attribution concernant », « Publication récente » et « date
de décision » doivent être absentes du rendu final. `recency/claim.py` peut
continuer à servir au moteur, mais son texte ne traverse aucune surface client.

## Flux et vérification

Le test de contrat lance le chemin réel de `python -m signals.alerts
--dry-run --account <recette>` et compare le contenu produit à la carte du
`GET /dashboard` pour le même signal. Il vérifie aussi le domaine
`@kivou.eu` du `Message-ID`.

Le déploiement synchronise les unités systemd et installe ripgrep sur staging
et production afin que les preuves DOM et de rendu soient reproductibles.

