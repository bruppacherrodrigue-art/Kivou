# Correction du gabarit de prospection v2

## Portée

Le renderer de la file Founder applique une normalisation déterministe au
moment du rendu. Les données source restent inchangées. Aucun modèle, aucun
enrichissement et aucun envoi ne sont déclenchés.

## Rendu attendu

- Le titulaire est affiché sous sa raison sociale normalisée. Lorsqu'un sigle
  explicite termine la raison sociale, il est prioritaire :
  `CONSTRUCTION DE MAISONS ET CHARPENTES DU DAUPHINE - CMCD` devient `CMCD`.
- La phrase famille est immédiatement suivie de :
  `… et vous êtes {métier} à {ville}{, à N km du chantier si connu}.`
- La phrase de présentation de Kivou apparaît avant la formule de politesse et
  la signature.
- Le corps contient le lien Kivou vers le détail du marché, mais aucune URL de
  source publique.
- Le pied contient `Source : registres publics et avis d'attribution officiel`
  et le lien de désinscription.
- La fin du corps est, dans cet ordre : `Bien à vous,`,
  `Rodrigue / Kivou · kivou.eu`, puis
  `P.S. : Vous travaillez sur ce type de chantier ? Un mot en retour et je vous
  envoie les prochains marchés de votre secteur.`
- La limite reste à 110 mots hors pied.

## Contrat et HTML

Le validateur refuse un mail si la raison sociale normalisée n'est pas
utilisée, si l'URL source apparaît, si la phrase Kivou, la formule de politesse,
la signature, le P.S. ou la source légale du pied manquent. Le HTML porte le
même contenu et conserve uniquement les liens vers le détail Kivou et la
désinscription.

## Régénération

Après déploiement, toutes les cibles `pending_review` ou `approved` sont
rendues à nouveau dans une transaction verrouillée. Chaque ancienne version
reste dans `prospect_target_history`. Les cibles envoyées ou rejetées ne sont
pas modifiées. Le résultat ALPES ZINGUERIE est relu directement en production.
