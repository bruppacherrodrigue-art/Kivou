# Préparation de la file du jour depuis la console Founder

## Objectif

La page `control.kivou.eu/prospection` permet au fondateur de déclencher un
cycle Acquisition assisté sans terminal. Le cycle prépare au plus 25 cibles en
`pending_review`, ne transporte aucun message et met la file à jour sans
rechargement manuel. Le même cycle continue d'être lancé automatiquement chaque
heure à partir de 06:00 Europe/Zurich, sous les plafonds et coupe-circuits
existants.

## Périmètre

Le changement couvre une nouvelle action Founder, la projection de l'état du
cycle, la carte « File du jour », le timer production et la recette de bout en
bout. Il ne modifie ni les critères de ciblage, ni la préparation des textes,
ni l'approbation, ni l'envoi. Le backfill d'enrichissement des titulaires reste
hors périmètre.

## Déclenchement et verrou d'instance

La route authentifiée
`POST /api/founder/actions/prospection/prepare` ne reçoit aucun paramètre. Elle
utilise le moteur d'écriture Founder pour compter les `prospect_target` créés
pendant la journée Europe/Zurich. La préparation assistée utilise la même borne
de journée ; un clic entre minuit et 02:00 en été ne peut donc pas consommer le
plafond UTC de la veille.

- À 25 cibles, elle répond `429` avec le code
  `DAILY_PENDING_CAP_REACHED` et la phrase « La file du jour a atteint son
  plafond de 25 cibles. »
- Si le coupe-circuit fichier `/etc/kivou/acquisition.disabled` est présent,
  elle répond `423` avec `ACQUISITION_DISABLED` et une phrase explicite.
- Sinon, elle ouvre `/run/kivou/acquisition.lock` et tente un verrou `flock`
  non bloquant. Un conflit répond `409`, code
  `ACQUISITION_ALREADY_RUNNING`, avec « Une préparation est déjà en cours. »
- Le descripteur verrouillé est transmis au processus enfant qui exécute
  `python -m signals.acquisition_runtime run-once`. Le parent ferme sa copie
  après le démarrage ; l'enfant conserve le verrou jusqu'à sa fin. Un thread
  léger attend l'enfant afin qu'il soit correctement récolté.

Le service systemd planifié utilise exactement le même fichier de verrou et un
code de conflit non nul. Un clic et un passage planifié ne peuvent donc jamais
exécuter deux cycles simultanément. Le verrou durable déjà présent dans le
runtime reste une seconde barrière avec fencing en base.

Une acceptation répond `202` avec un contrat JSON versionné contenant l'état
`accepted`, le nombre déjà préparé et le plafond `25`. Le processus enfant
hérite des variables de production déjà chargées par `kivou-founder-api` ; aucun
secret n'est transmis dans la requête ou la réponse.

## Garanties Assisted et absence d'envoi

La configuration production est fixée à `ASSISTED`. Le chemin existant
`AssistedPreparationAction` s'arrête à `pending_review` et n'appelle ni création
de campagne, ni import Instantly, ni activation. L'envoi reste accessible
uniquement par l'action Founder séparée, après validation explicite de chaque
cible et confirmation du lot.

Le cycle manuel et le cycle planifié partagent les garde-fous existants :
plafond quotidien de 25 cibles, cinq signaux par jour, exclusion de deux lots du
même avis, cooldown de 90 jours, policy gateway, plafond de coût, limite de
temps et kill switch.

## Projection Founder

`FounderAcquisitionStatus` est étendu avec :

- `prepared_today_count`, entier de 0 à 25 ;
- `daily_pending_cap`, toujours `25` ;
- `next_run_at`, instant timezone-aware ou `null` si le timer est absent ou
  désactivé.

Le lecteur systemd interroge séparément :

- `kivou-acquisition-production.service` pour déterminer si un cycle est
  réellement en cours ;
- `kivou-acquisition-production.timer` pour lire
  `NextElapseUSecRealtime`.

Un timer actif mais en attente ne produit donc plus l'état `RUNNING`. Le dernier
cycle, son heure, son statut et son motif restent lus dans le journal runtime
persisté. Le compteur du jour vient de `prospect_target`, autorité effective du
plafond de préparation.

## Carte « File du jour »

La carte affiche en permanence :

- le dernier cycle avec son heure et son résultat traduit ;
- le prochain passage planifié, en Europe/Zurich ;
- le compteur `N/25` ;
- le bouton « Préparer la file du jour ».

Après une réponse `202`, le bouton est désactivé et la carte affiche
« Préparation en cours · N/25 ». Le navigateur rafraîchit la projection et les
deux listes `pending_review`/`approved` toutes les deux secondes. Le polling
s'arrête dès que l'un des événements suivants est observé : le service est
passé de `RUNNING` à un état terminal, le dernier cycle a changé, le compteur
atteint 25, ou une limite de 25 minutes est atteinte. Dans les trois premiers
cas, la file finale apparaît sans rechargement de page. À 25 minutes, la carte
revient à l'état normal et affiche une erreur de suivi sans supposer la fin du
cycle.

Les refus `409`, `423` et `429` conservent la file visible et affichent la
phrase renvoyée par l'API. Une panne réseau utilise le message générique Founder
existant. Un double clic est bloqué localement pendant la requête, sans être
considéré comme une protection de concurrence.

## Planification production

`kivou-acquisition-production.timer` utilise une expression explicite avec le
fuseau `Europe/Zurich` et déclenche chaque heure de 06:00 à 23:00. Le passage de
06:00 ouvre la journée ; les passages suivants complètent la file. Une fois le
plafond atteint, le runtime termine proprement avec
`DAILY_PENDING_CAP_REACHED`. `Persistent=true` conserve le rattrapage après une
indisponibilité de l'hôte.

Le service reste `Type=oneshot`, lit exclusivement les environnements
production, conserve son hardening et exécute le runtime sans option QA. Le
timer est activé seulement après le déploiement de `main` et la vérification de
la configuration `ASSISTED`.

## Tests et recette

Les tests backend couvrent l'acceptation `202`, les refus verrou/plafond/kill
switch, la transmission du verrou à l'enfant, le reap du processus et l'absence
d'information sensible dans les erreurs. Ils vérifient aussi la borne de journée
Europe/Zurich autour de minuit. Les tests de projection distinguent
service actif et timer en attente, vérifient le prochain passage et le compteur
du jour.

Les tests frontend couvrent l'état initial, le clic, le polling, la progression
`N/25`, les trois phrases de refus, l'arrêt du polling et l'apparition de la file
sans rechargement. Les tests systemd vérifient le fuseau, la plage horaire, le
verrou partagé, le code de conflit non nul et l'absence de toute option de
transport ou de QA.

La recette production est effectuée depuis `main` : vérifier une file sous le
plafond, cliquer une fois, observer le compteur et le dernier cycle, attendre
la fin, confirmer qu'aucun envoi n'a été créé, puis capturer la carte remplie
avec le bouton, le dernier résultat et le prochain passage visibles.
