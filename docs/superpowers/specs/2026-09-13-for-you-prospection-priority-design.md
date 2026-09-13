# Priorité For You et éligibilité acquisition

## Décision

Un `model_fit` inconnu n'est pas un veto. La sélection acquisition accepte une
valeur absente ou `NULL` et exclut uniquement la valeur explicite `none`.

Le worker For You réclame les travaux dans cet ordre :

1. signaux de moins de 30 jours correspondant au couple vertical/région de la
   configuration acquisition active ;
2. autres signaux de moins de 30 jours rattachés à un profil actif, courant et
   non invalidé ;
3. autres travaux encore conservés, avec un ordre stable par date puis ID.

Le service For You charge la configuration acquisition depuis le même fichier
d'environnement que le runtime. En l'absence de configuration, la priorité 1
est désactivée mais la priorité 2 reste opérationnelle.

## Rétention et historique

Avant chaque réclamation, la maintenance retire uniquement le backlog
exécutable (`pending` ou bail `running` expiré) lorsque le signal a plus de 30
jours, ou n'est plus rattaché à un profil actif à sa révision courante. Les
lignes `completed` sont conservées comme historique. La date est
`COALESCE(award_date, contract_notification_date)`, identique à l'acquisition.

La maintenance expose un rapport déterministe avec total, candidats anciens,
candidats inactifs, recouvrement et suppressions. Elle peut être appelée à blanc
avant l'application en production.

## Limites

Le cumul quotidien de 500 tentatives disparaît. Un lot technique de 500 lignes
maximum borne la mémoire et le temps d'un passage, sans empêcher le passage
horaire suivant. La seule limite quotidienne économique est le plafond
persistant `for_you` du routeur de modèles. Une exception
`DailyModelBudgetExhausted` arrête proprement le lot et remet les travaux non
traités en attente.

## Validation

Les tests couvrent : `NULL` et absence de fit éligibles, `none` exclu, les trois
niveaux de priorité, la purge bornée au backlog, l'absence de compteur quotidien
et l'arrêt par budget. En production : audit avant/après, contrôle du vivier,
clic Founder, file actualisée sans envoi, capture.
