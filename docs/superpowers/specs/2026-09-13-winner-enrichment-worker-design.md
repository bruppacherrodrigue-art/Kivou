# Enrichissement économique des titulaires — arbitrage et worker dédié

Date : 13 septembre 2026  
Statut : approuvé par la décision opérateur du 13 septembre 2026

## Objectif

Réduire l'arbitrage Sonnet aux ambiguïtés utiles, empêcher deux exécutions d'une
même passe et enrichir dans l'heure les titulaires de nouveaux signaux récents
appartenant à un compte actif. Le backfill historique reste une action séparée,
chiffrée et soumise à un nouveau go.

## Décision d'arbitrage

Le juge économique reste l'autorité de premier niveau. Sonnet est appelé une
seule fois si le JSON du juge est invalide, ou si au moins une valeur non nulle
parmi `website`, `email` et `family` a une confiance comprise entre 0,2 inclus
et 0,8 exclu. Une valeur non nulle sous 0,2 est rejetée par la politique sans
arbitrage. Une valeur nulle n'est jamais arbitrée : une confiance supérieure ou
égale à 0,8 signifie que l'absence est établie dans les preuves visibles ; une
confiance inférieure signifie que les preuves sont insuffisantes. Dans les deux
cas, la politique conserve `null` et la fiche peut rester à revérifier.

Le prompt explique explicitement que la confiance qualifie soit la valeur
retournée, soit, quand la valeur vaut `null`, l'affirmation qu'aucune valeur
confirmable n'existe dans le paquet. Il interdit de transformer « je ne sais
pas » en absence certaine.

## Verrou d'exécution

La commande de replay prend elle-même un verrou fichier non bloquant avant de
construire les clients ou d'appeler un fournisseur. Un second lancement quitte
avec un code distinct et `INSTANCE_ALREADY_RUNNING`. Le service systemd garde
également `flock`, mais il n'est plus l'unique protection.

## Worker de matérialisation

Un module dédié sélectionne un petit lot de `winner_enrichment_job` : statut
`pending`, signal non invalidé, révision ICP courante, ICP actif, date métier du
signal dans les 30 derniers jours et `queued_at` postérieur à un watermark de
mise en service obligatoire. Ce watermark empêche le timer automatique de
consommer les 915 jobs constituant le backfill en attente d'autorisation.

Pour chaque job, le worker :

1. réutilise la projection officielle existante pour obtenir l'identité et le
   SIREN ;
2. lit la fiche publique SIRENE exacte pour alimenter ou mettre à jour
   `supplier_directory` sans écraser un enrichissement frais ;
3. appelle `CompanyEnrichmentService`, donc `enrichment_judge`, l'arbitre
   conditionnel et leurs plafonds persistés ;
4. termine le job seulement avec un résultat durable ; une erreur bornée rend
   le job `failed` et reste rejouable dans la limite existante.

Les doublons de titulaire sont sans surcoût LLM grâce au cache de 90 jours. Le
timer tourne au moins toutes les heures, sous un verrou d'instance propre, avec
un lot borné. Il ne déclenche ni acquisition ni envoi.

## Backfill et mesure

Les 65 fiches restantes servent de mesure après déploiement. Le rapport donne
le nombre de décisions juge valides, les motifs d'arbitrage et le taux réel ; le
seuil de succès attendu est inférieur à 30 %. Le backfill des titulaires récents
utilise une commande explicite qui ignore le watermark uniquement pour la liste
figée autorisée. Il ne sera pas lancé avant un nouveau go et une projection
actualisée attendue entre 3 et 4 USD.

## Vérification

Les tests couvrent toutes les bornes 0,2/0,8, les absences certaines et
incertaines, le JSON invalide, le refus d'un second replay, la sélection
actif/récent/watermark, l'idempotence par SIREN et l'arrêt propre au plafond.
La recette staging matérialise un signal d'un compte actif puis démontre, en
moins d'une heure, un job terminé et une fiche `supplier_directory` portant un
jugement journalisé. Aucune recette n'envoie d'e-mail.
