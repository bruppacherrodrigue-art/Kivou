# Envoi asynchrone des prospects Founder — design

## Contexte et incident

Le 16 septembre 2026, le Founder Console a soumis 21 cibles avec la requête
`f593879c-1e4d-4e81-9619-8a2addf773e5`. La route synchrone a créé la campagne
Instantly et les 21 leads, puis a interrogé leur vérification jusqu'à 15 fois.
Nginx a rendu un HTTP 504 après 30,019 secondes alors que l'API a poursuivi son
traitement environ 79 secondes. Une cible a été acceptée puis effectivement
envoyée, 17 autres leads sont devenus valides, et 3 ont été déclarés invalides.
La campagne a été mise en pause avant toute reprise.

Le correctif doit supprimer le travail fournisseur de la requête HTTP, rendre
la progression durable et empêcher tout doublon après un timeout, un reclic ou
un redémarrage du worker.

## Sémantique des statuts

Les deux plans suivants restent strictement séparés :

- **Acceptation Instantly** : une cible passe à `prospect_target.status = sent`
  lorsque son lead a `verification_status = 1` et est accepté par Instantly pour
  envoi. La console appelle cet état « Envoyé ».
- **Livraison** : `prospect_target.delivery_status` et les horodatages de
  livraison ne changent qu'à partir d'un webhook Instantly authentifié et
  dédupliqué. Ils expriment `delivered`, `bounced`, `opened`, `clicked`,
  `replied` ou `unsubscribed` indépendamment de l'acceptation.

Une nouvelle colonne `instantly_accepted_at` porte l'heure d'acceptation. Le
champ `sent_at` reste réservé à l'événement de livraison. Le worker ne renseigne
jamais `delivery_status` ni `sent_at` lorsqu'il accepte un lead.

Pour les anciennes lignes, la migration copie l'ancien `sent_at` dans
`instantly_accepted_at`. Elle ne fabrique pas de livraison : les événements
présents dans `prospect_delivery_event` restent la source de vérité de la
livraison et permettent de reconstruire le statut correspondant.

La migration remplace l'ancien état ambigu `delivery_status = sent` par
`not_sent` tant qu'aucun événement `email_sent` n'est présent. Le projecteur de
webhook traduit désormais `email_sent` en `delivered`; les événements suivants
font progresser ce même cycle sans modifier l'acceptation Instantly.

## Architecture retenue

### File durable

`prospect_send_request` devient la racine d'un job durable. Ses états sont
`queued`, `running`, `waiting`, `completed`, `partial` et `failed`, tout en
acceptant temporairement l'ancien état `started` pendant la migration. Il porte
les compteurs, le fournisseur/campagne, le prochain instant d'exécution et un
bail de worker récupérable.

Une nouvelle table `prospect_send_item` contient une ligne par couple
`request_id` / `target_id` avec :

- la version attendue au clic ;
- l'ordre d'origine ;
- l'état `queued`, `running`, `verification_pending`, `sent` ou `failed` ;
- l'identifiant de lead Instantly et son statut de vérification ;
- le motif d'échec public, borné et sans secret ;
- `next_attempt_at`, les compteurs d'appel et les horodatages de traitement.

La clé primaire composée rend la progression par cible idempotente. Le total,
le nombre traité, le nombre envoyé et le nombre en échec sont dérivés des items
et recopiés sur la requête pour une lecture rapide.

### Route HTTP

`POST /api/founder/actions/prospection/send` effectue uniquement une
transaction locale :

1. calculer le fingerprint canonique du payload ;
2. si `request_id` existe avec le même fingerprint, retourner son état sans
   nouvel appel fournisseur ;
3. si le même identifiant porte un autre fingerprint, répondre 409
   `SEND_REQUEST_IDEMPOTENCY_CONFLICT` ;
4. verrouiller les cibles et ne réserver que celles encore `approved` avec la
   version attendue ;
5. créer la requête et ses items ;
6. répondre immédiatement HTTP 202 avec `request_id`, les compteurs et l'URL de
   suivi.

Aucun client Instantly, attente réseau ou lancement de thread n'est autorisé
dans cette route.

`GET /api/founder/actions/prospection/send/{request_id}` retourne l'état, les
compteurs et chaque résultat. Une requête rejouée reste consultable après
rechargement de la page.

### Worker

Un worker oneshot dédié, lancé fréquemment par systemd, réclame une requête avec
`FOR UPDATE SKIP LOCKED` et un bail expirant. Il traite au plus une cible à la
fois, persiste chaque transition, puis réclame l'item suivant. Un crash ne peut
donc ni perdre tout le lot ni autoriser deux workers à traiter le même item.

Pour un item :

1. relire la cible sous verrou ; si elle est déjà `sent`, finaliser l'item sans
   appel fournisseur ;
2. réutiliser `provider_campaign_id` et `instantly_id` s'ils existent ;
3. seulement en leur absence, créer la campagne ou importer le lead ;
4. appeler `get_lead` une seule fois ;
5. si la vérification vaut `11` ou `12`, passer l'item à
   `verification_pending`, fixer `next_attempt_at` et libérer le worker ;
6. au passage suivant, relire le même lead sans le réimporter ;
7. si le statut vaut `1`, marquer l'item et la cible acceptés (`status=sent`,
   `instantly_accepted_at` renseigné) ;
8. pour `-1`, `-2`, `-3` ou `-4`, conserver la cible `approved`, libérer sa
   réservation et exposer respectivement le motif invalide, risqué, catch-all
   ou changement de poste.

Le délai de nouvelle vérification est durable et borné. Aucun `sleep` n'existe
dans le worker. La campagne n'est activée qu'une fois tous les items terminaux ;
elle n'est jamais recréée lors d'une reprise.

### Progression de la console

Après le HTTP 202, la console conserve le `request_id` en session et interroge
le GET de suivi. Elle affiche notamment :

- `7/21 envoyées` pour les acceptations Instantly ;
- le nombre en vérification et le nombre en échec ;
- pour chaque échec, l'adresse et le motif public ;
- une colonne de livraison distincte, alimentée exclusivement par les données
  webhook (`En attente`, `Livré`, `Bounce`, `Ouvert`, etc.).

Une erreur réseau de polling ne remet jamais les lignes à `approved` et ne
provoque jamais un second POST. La page reprend le suivi après rechargement.

## Reprise du lot du 16 septembre

La reprise réutilise la requête et la campagne existantes. Un outil opérateur
explicite reconstruit les items à partir des 21 identifiants originaux :

- la cible déjà `sent` est inscrite comme terminée et n'est jamais transmise au
  worker ;
- les 20 cibles encore `approved` sont mises en file ;
- leurs `instantly_id` existants sont obligatoirement réutilisés ;
- les 17 statuts valides deviennent `sent` sans réimport ;
- les 3 statuts invalides deviennent `failed`, restent `approved` et montrent
  leur motif dans la console ;
- la campagne mise en pause est réactivée une seule fois après convergence.

Avant la reprise réelle, un mode `--dry-run` doit prouver la sélection exacte :
20 cibles `approved`, 1 cible ignorée car déjà `sent`, aucune création de lead.

## Nginx et exploitation

Les routes Founder héritent d'un `proxy_read_timeout` de 120 secondes. Cette
marge ne remplace pas l'asynchronisme : le POST doit rester local et répondre
en 202 bien avant cette limite.

Le worker dispose d'une unité et d'un timer systemd de production, d'un verrou
d'instance, d'un timeout borné et de journaux contenant uniquement les
identifiants techniques, compteurs, codes et traces d'erreur expurgées. Il ne
journalise ni contenu d'e-mail, ni clé, ni jeton d'attribution.

## Gestion des erreurs et invariants

- Une cible `sent` ne peut jamais être réimportée ni remise en file.
- Un item avec `instantly_id` ne peut jamais appeler la création de lead.
- Un `request_id` rejoué avec le même payload ne produit aucun effet externe.
- Un `request_id` rejoué avec un payload différent échoue avant tout effet.
- Un statut de vérification en cours est une attente, jamais un échec.
- Une erreur terminale libère uniquement la cible concernée ; les autres items
  continuent.
- La limite quotidienne compte les réservations actives et les acceptations,
  sans compter deux fois une reprise du même `request_id`.
- Le kill switch est contrôlé avant la réservation, avant chaque effet externe
  et avant l'activation de campagne.
- L'acceptation fournisseur ne modifie jamais la livraison SMTP.

## Vérification

Les tests doivent couvrir :

- HTTP 202 immédiat sans appel fournisseur ;
- relecture idempotente et conflit de fingerprint ;
- réclamation concurrente et récupération d'un bail expiré ;
- un seul appel de vérification par passage ;
- replanification des statuts 11/12 sans `sleep` ;
- progression persistée après chaque cible ;
- séparation stricte acceptation/livraison ;
- webhook seul autorisé à modifier la livraison ;
- reprise du lot sans réimport et exclusion de la cible déjà envoyée ;
- affichage `x/21`, motifs d'échec et reprise après rechargement ;
- configuration nginx à 120 secondes ;
- dry-run de reprise avant toute mutation fournisseur.

La validation de production exige enfin : migration appliquée, worker actif,
POST mesuré sous une seconde, polling jusqu'à l'état terminal, aucun doublon
Instantly, puis reprise contrôlée des seuls items encore `approved`.
