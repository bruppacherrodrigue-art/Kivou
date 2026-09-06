# PR de finition avant production

## Objectif

Livrer une seule PR sur `fix/recette-finition`, créée depuis `main`, qui ferme les exigences de finition avant production dans l'ordre contractuel: bloquants 0 à 6, puis non bloquants 7 à 14.

## Décisions produit

- Le filtre `Secteur` est disponible pour les plans Essentiel et Pro.
- Le profil cible actif dans le bandeau plan est un lien vers `/app/icps`.
- Toute offre verrouillée et la ligne de découverte limitée renvoient vers `/tarifs`.
- Le compte rendu de recette contient exactement 15 lignes.

## Architecture

Le backend expose un contrat de présentation canonique pour un signal. Il résout une seule fois l'objet affichable, `zone_labels`, la date d'attribution, l'identité publique de l'entreprise, les besoins déterminés et `for_you_sentence`. Carte Aujourd'hui, drawer, mail et alerte consomment la même représentation; un test de contrat compare les sorties octet par octet sur un compte sans cache.

Les signaux dépourvus d'objet exploitable sont exclus de la matérialisation par profil, sauf lorsqu'un libellé CPV fournit l'objet affichable. Un backfill rend cette règle vraie pour les signaux existants. L'agrégation entreprises est servie par une vue/cache ciblé afin de maintenir les endpoints `/companies` et `/signals` sous une seconde sur `client-3mois`.

Le statut de contact est lu et écrit dans une table unique. Les compteurs Aujourd'hui, le segment Entreprises et le panneau réutilisent cette source et invalident la même donnée après mutation.

Le frontend partage les primitives de navigation, identité et statut entre le shell desktop et mobile. Sous `900px`, les signaux deviennent des lignes-cartes contenant titulaire, objet/montant, lieu, date et score, sans tableau à colonnes. Le panneau Entreprises n'affiche alors que Entreprise et Statut; il conserve un layout côte à côte sans recouvrement.

## Comportements requis

### Bloquants

0. Le bloc compte est en bas des menus desktop/mobile, au-dessus du bandeau plan: initiales, nom ou email, entreprise si renseignée et lien `/app/settings`. L'action de déconnexion est toujours visible, invalide la session côté serveur et redirige vers `/login`. Le profil cible actif du bandeau plan est cliquable vers `/app/icps`.
1. Le bloc des besoins est masqué lorsqu'aucun besoin n'a de timing ou quantité déterminés. `Pourquoi ça vous concerne` affiche exclusivement la phrase persistée, générée ou fallback déterministe à partir de l'objet court, lieu, montant et date; aucune phrase générique ni code pays ne peut être produite.
2. À moins de `900px`, chaque signal est une ligne-carte avec les cinq groupes d'information requis et un hit-area complet.
3. Aucun objet ne s'affiche sous `—`. Un objet manquant empêche la matérialisation profil, sauf fallback sur le libellé CPV; les données existantes sont backfillées.
4. Sur desktop (`>= 900px`), le panneau Entreprises reste visible à côté du contenu et la liste se réduit à Entreprise et Statut, sans recouvrement. Sous `900px`, le panneau prend tout l'écran, comme le drawer Signaux, et la liste n'est pas visible simultanément.
5. Aujourd'hui, « Cette semaine », le segment Entreprises et le panneau utilisent la table de contact unique; une mutation du panneau met à jour les trois compteurs.
6. Les réglages utilisent le design system, omettent les champs absents, n'affichent ni `—` ni « Tarif facturé absent », exposent l'onglet Données avec export JSON et suppression de compte, et affichent « Enregistré » après chaque sauvegarde de note ou réglage.

### Non bloquants

7. Une ligne verrouillée ouvre un mini-panneau « Réservé aux offres Essentiel et Pro » avec bouton `/tarifs`; la ligne « N autres signaux — voir les offres » navigue aussi vers `/tarifs`.
8. La ligne d'identité entreprise n'expose que SIRET, IDE ou TVA; TED et SIMAP sont exclus de cette ligne uniquement. La ligne du drawer `Source : TED 568562-2026 ↗` reste affichée comme référence de l'avis.
9. Les cartes et le drawer utilisent « Attribué le ».
10. La ligne « N correspondent fortement » est absente lorsque `N = 0`.
11. Un quota illimité affiche « 27 signaux ouverts ce mois ».
12. Les zones viennent de `zone_labels` partout, y compris mobile; un code comme `FR` ne doit jamais être affiché seul.
13. `/companies` et `/signals` répondent sous une seconde sur `client-3mois` avec 1 002 signaux; le compte rendu donne les mesures avant/après.
14. Le filtre Secteur est visible et fonctionnel en Essentiel et Pro.

## Tests et recette

Chaque point 0 à 14 reçoit au moins un test unitaire, contrat ou golden. Les tests de contrat couvrent l'égalité exacte du texte du signal entre les quatre canaux, les comptes sans cache et la mutation du statut contact. Les tests responsive vérifient le seuil `900px`, l'absence de débordement et les liens de monétisation.

La recette Playwright automatisée couvre les comptes QA Découverte, `client-3mois` (Essentiel) et Rodrigue, en desktop et mobile. Elle vérifie notamment la déconnexion depuis chaque écran, le lien ICP, le contact transverse et le filtre Secteur Essentiel. Le déploiement de staging utilise `kivou-deploy.sh`; les résultats et les artefacts sont joints au compte rendu de 15 lignes.

## Hors périmètre

Pas de refonte générale du design system, pas de changement de règles commerciales hors activation du filtre Secteur en Essentiel, et pas d'exposition d'identifiants techniques internes.
