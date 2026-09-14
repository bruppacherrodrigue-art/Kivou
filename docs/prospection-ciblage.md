# Règles de ciblage de la file de prospection

Les cycles assistés appliquent ces règles avant de créer une ligne dans
`prospect_target` :

- la famille confirmée du titulaire est exclue des familles ciblées ;
- un signal de montant inférieur ou égal à 100 000 € fournit au plus 5 cibles,
  les autres au plus 8 ;
- l'ordre de sélection favorise un dirigeant nommé, puis le département du
  signal, puis ses départements voisins et enfin le SIREN ;
- une cible déjà en file (`pending_review` ou `approved`) est dédupliquée par
  SIREN, quel que soit le signal ; un SIREN effectivement envoyé est refroidi
  pendant 30 jours à partir de `sent_at` ;
- la préparation de la file enchaîne plusieurs signaux sous le verrou de cycle,
  jusqu'à 25 cibles ou 5 signaux. Aucun second couple de prospection n'est
  sélectionné automatiquement.

Lorsque l'identité du titulaire est connue mais que sa famille n'est pas encore
confirmée, le signal est suspendu avec `HOLDER_FAMILY_ENRICHMENT_REQUIRED`.
Son job `winner_enrichment_job` est remis en `pending` avec `queued_at` courant,
afin que l'enrichissement le traite en priorité au cycle suivant.
