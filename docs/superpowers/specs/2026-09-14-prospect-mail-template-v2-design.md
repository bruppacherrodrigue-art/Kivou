# Gabarit de mail de prospection v2

## Décision

Le rendu des mails de la file founder devient déterministe et versionné. Il ne
fait aucun appel fournisseur et conserve le corps hors pied à 110 mots maximum.

## Contrat

- Civilité issue d'un référentiel de prénoms à haute certitude : `Bonjour
  Madame/Monsieur Nom,`; repli `Bonjour,`; aucun prénom dans le mail.
- Raison sociale nettoyée des mentions `EN ABREGE`, formes juridiques et
  mentions de registre. Un sigle en majuscules est placé avant le nom normalisé
  entre parenthèses.
- Copie famille au présent général, suivie d'une phrase métier + ville +
  distance lorsque une distance déterministe est fournie.
- URL d'attribution Kivou en clair dans le texte, ligne de présentation Kivou,
  signature `Rodrigue / Kivou · kivou.eu`, P.S. imposé et pied `Kivou, Sion
  (Suisse)`.
- Le pied n'entre pas dans la limite de 110 mots.

## Régénération

Les cibles non envoyées sont rendues à nouveau sous verrou de transaction. Les
valeurs précédentes restent dans `prospect_target_history`; chaque ligne reçoit
un événement `mail_regenerated_v2` et son numéro de version est incrémenté.
Les cibles envoyées ne sont jamais modifiées. La régénération ne déclenche ni
envoi ni appel de modèle.

## Distance et téléphone

Le renderer accepte `distance_km` comme donnée déjà calculée. En son absence,
la justification omet la distance. Le téléphone de Rodrigue est ajouté
uniquement si `RODRIGUE_PHONE` est configuré.
