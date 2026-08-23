# RTL-05 — Runtime des e-mails transactionnels

**État :** implémentation validée localement ; livrée en PR brouillon
**Branche :** `feat/operational-transactional-email-runtime`
**SHA de départ :** `2481c6e88cd20ca5a78c7d3a8894bcdfdd0b48e4`
**PR brouillon :** [#61](https://github.com/bruppacherrodrigue-art/Kivou/pull/61)
**Envoi externe effectué :** aucun
**Action production ou DNS effectuée :** aucune

## Périmètre livré

La même frontière SMTP backend sert les deux usages transactionnels demandés :

- le reset de mot de passe produit un lien à usage unique, envoyé après la
  réponse HTTP afin de ne pas créer un oracle temporel d'existence du compte ;
- `python -m signals.alerts` sélectionne uniquement les comptes, préférences,
  droits et signaux actuellement autorisés, puis envoie un digest client ;
- aucun navigateur ne parle à SMTP et aucune donnée SMTP n'entre dans une URL ;
- aucun e-mail d'acquisition, lead, contact Apollo, appel Instantly, campagne,
  paiement ou action de l'Acquisition Engine n'est créé.

Le transport accepte explicitement STARTTLS ou TLS implicite, avec un timeout
borné. Il ne persiste ni corps d'e-mail, ni destinataire, ni réponse SMTP brute,
ni identifiant d'authentification. Les erreurs conservées sont des codes courts
allowlistés par l'adaptateur.

## Configuration requise

Les valeurs restent exclusivement dans l'environnement cible. Les noms exacts
sont :

- `KIVOU_DATABASE_URL` ;
- `KIVOU_ALLOWED_ORIGIN` ;
- `KIVOU_PUBLIC_APP_URL` ;
- `SMTP_HOST`, `SMTP_PORT` ;
- `SMTP_USERNAME` et `SMTP_PASSWORD`, configurés ensemble lorsqu'une
  authentification est nécessaire ;
- `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME` ;
- `SMTP_TLS_MODE` (`starttls` ou `implicit_tls`) ;
- `SMTP_TIMEOUT_SECONDS` ;
- `SMTP_REPLY_TO_EMAIL`, facultatif ;
- `KIVOU_ALERT_LEASE_SECONDS` ;
- `KIVOU_ALERT_MAX_ATTEMPTS` ;
- `KIVOU_ALERT_RETRY_BASE_SECONDS`.

`KIVOU_PUBLIC_APP_URL` est une origine HTTPS stricte, identique à
`KIVOU_ALLOWED_ORIGIN`, sans chemin, identifiants, query string ni fragment.
Les routes de reset, signal et préférences sont ajoutées exclusivement par le
backend.

## Prestataire et transport audités

L'audit staging en lecture seule identifie Infomaniak, sur le port 587 avec
STARTTLS. Le compte système est `kivou`, le checkout `/srv/kivou/app` et le
fichier d'environnement `/etc/kivou/staging.env`. La présence des variables
SMTP requises a été constatée sans lire ni recopier leur secret.

Le code reste indépendant du prestataire : il utilise SMTP standard et peut
accepter le port 465 avec TLS implicite si l'environnement le décide. Aucun
appel au prestataire réel n'a été réalisé pendant l'implémentation ou les tests.

## Garantie durable des alertes

La migration additive `0023_transactional_email_runtime` ajoute :

- un lease global `signal_alert_job_lease`, avec reprise après expiration ;
- une identité de lot logique et un `Message-ID` déterministe ;
- les états `queued`, `sending`, `sent`, `failed`,
  `unknown_delivery_state` et `suppressed` ;
- l'instant de tentative, le lease d'envoi, le prochain essai et le caractère
  rejouable ;
- un budget et un backoff exponentiel bornés.

Les anciennes lignes `failed` et `unknown_delivery_state` migrent sans analyse
de leur ancien texte d'erreur : elles restent dans leur état historique mais
deviennent terminales, avec `retryable=false` et aucun prochain essai.

Comportement obtenu :

- deux jobs concurrents : un seul acquiert le lease ; l'autre rend
  `already_running` et un code 0 ;
- une panne technique d'acquisition : erreur du cycle courant et code non nul ;
- échec connu avant acceptation SMTP : retry selon 15, 30, 60 puis 120 minutes
  avec la configuration par défaut ;
- refus permanent : état terminal dès la première tentative ;
- refus destinataire `4xx` : retry borné ; refus destinataire `5xx` : état
  terminal, sans conserver l'adresse ni la réponse SMTP ;
- interruption ou `sending` expiré : reprise avec le même lot et le même
  `Message-ID`, sauf budget déjà épuisé, qui devient terminal sans sixième
  tentative ;
- baisse opérateur du budget : une ancienne ligne due déjà au nouveau plafond
  devient terminale une seule fois et n'empoisonne pas les timers suivants ;
- préférences désactivées, droits perdus ou signal devenu inaccessible : état
  terminal `suppressed`, sans tentative SMTP ni événement `alert_failed` ;
- une relance sans nouvelle donnée n'envoie pas de nouveau lot ;
- seules les erreurs apparues pendant l'exécution courante influencent le code
  de sortie. L'historique terminal ne fait pas échouer les timers suivants.

La garantie n'est pas « exactement une fois ». Si le serveur SMTP accepte le
message puis que sa réponse réseau est perdue, ou si l'écriture `sent` échoue
après l'acceptation, Kivou ne peut pas savoir si le message a été remis. La
ligne reste explicitement ambiguë ou `sending`, le retry est borné et réutilise
le même `Message-ID`, mais un doublon reste possible. Éviter cette ambiguïté
absolue nécessiterait un protocole transactionnel que SMTP ne fournit pas.

## Reprise du reset

Le reset reste volontairement one-shot, sans outbox contenant un jeton en
clair. Le jeton n'est stocké que sous forme de hash, expire, fonctionne une
seule fois et révoque les sessions après changement du mot de passe.

La consommation est un `UPDATE` conditionnel atomique sur le hash, l'absence
de `used_at` et l'expiration, dans la même transaction que le changement du mot
de passe. Deux confirmations concurrentes ne peuvent donc pas toutes deux
accepter le même jeton, sur SQLite comme sur PostgreSQL.

Si un premier envoi échoue, l'utilisateur peut refaire une demande. La nouvelle
demande invalide durablement les anciens jetons non utilisés, produit un jeton
et un `Message-ID` nouveaux, puis tente une nouvelle remise. Le statut HTTP et
le corps restent identiques pour une adresse connue ou inconnue ; les logs ne
contiennent que le code d'échec sûr.

## Runtime versionné

`ops/systemd/kivou-alerts.service` charge le même environnement et le même
checkout que l'API. Il applique un `flock` non bloquant dont la contention rend
0, puis le lease PostgreSQL arbitre aussi les autres processus ou hôtes.

`ops/systemd/kivou-alerts.timer` se déclenche chaque heure, avec
`Persistent=true` et un délai aléatoire maximal de cinq minutes. Il ne promet
pas du temps réel. Le service est `oneshot`, sans redémarrage en boucle, avec un
timeout de vingt minutes et les durcissements systemd compatibles avec SMTP et
PostgreSQL.

Le lease configuré ne peut pas être inférieur à trente minutes : il reste donc
possédé pendant la terminaison forcée du service et conserve dix minutes de
marge. Le dry-run opérateur utilise une unité transitoire `systemd-run` avec le
même `EnvironmentFile` que le service, sans interprétation Bash divergente.

Les commandes d'installation, d'exécution manuelle, d'inspection des journaux
et de rollback sont versionnées dans `ops/README.md`.

## DNS en lecture seule

Le domaine du `From` audité est `kivou.eu`.

- SPF : un seul enregistrement observé,
  `v=spf1 include:spf.infomaniak.ch -all` ;
- DMARC : un enregistrement observé avec `p=reject` ;
- DKIM : Infomaniak fournit la fonction, mais le sélecteur réellement utilisé
  n'est pas encore prouvé ;
- Return-Path et alignement SPF/DKIM : à confirmer dans les en-têtes d'un
  message reçu.

La présence DNS seule ne clôt pas RTL-05. La preuve finale doit venir des
en-têtes d'un reset et d'une alerte réellement reçus : `SPF=pass`, `DKIM=pass`
et `DMARC=pass`. Aucune écriture DNS n'est autorisée par cette PR.

## Validation locale

Après merge normal du dernier `origin/main`, la matrice ciblée est verte :
**195 tests en 113,63 s**.

Elle couvre la configuration, les liens, le faux SMTP STARTTLS local, TLS
implicite, les timeouts, la migration et son downgrade/ré-upgrade SQLite, le SQL
PostgreSQL hors ligne, les leases, retries, suppressions, codes CLI, unités
systemd, resets, absence d'énumération et scans de secrets.

Les retries existants sont revalidés par leur clé opaque exacte via le contrat
de détail account-scoped : propriété, ICP actif et courant, absence
d'invalidation, allocation de plan, fraîcheur, identité affichable et unlock
sont recomputés sans dépendre du plafond de pagination du feed.

La validation CI-équivalente locale donne :

- `uv run ruff check .` : vert ;
- `uv run pytest` : **4 210 passés, 2 ignorés en 1 243,41 s** ;
- frontend typecheck et lint : verts ;
- frontend Vitest : **28 fichiers, 376 tests passés** ;
- frontend build : vert, avec l'avertissement de taille de chunk Vite déjà
  non bloquant ;
- `systemd-analyze verify` : les deux unités valides sans avertissement ;
- migration `0023` : downgrade/ré-upgrade SQLite et SQL PostgreSQL hors ligne
  couverts par la matrice ciblée ;
- revue indépendante finale : aucun constat Critical, Important ou Minor.

Aucun script shell n'est ajouté ; `shellcheck` n'est pas installé localement et
n'est pas applicable à ce changement. Aucun test n'a contacté un endpoint SMTP
public.

## Préflight staging préparé, non exécuté

Avant tout envoi, et seulement après autorisation explicite séparée :

1. vérifier que le checkout correspond exactement au SHA de la PR ;
2. lancer et vérifier une sauvegarde staging ;
3. contrôler que `KIVOU_PUBLIC_APP_URL` vaut l'origine staging attendue et que
   les variables SMTP/TLS/timeout sont présentes, sans afficher leurs valeurs ;
4. appliquer `0023` par la couche de migration applicative puis contrôler la
   révision ;
5. créer `/srv/kivou/run`, installer et vérifier les unités sans activer le
   timer ;
6. exécuter `python -m signals.alerts --dry-run` ;
7. utiliser uniquement le compte synthétique et la boîte contrôlée fournie hors
   dépôt ;
8. demander un reset par la route publique réelle, puis vérifier expéditeur,
   sujet, origine du lien, nouveau mot de passe, ancien mot de passe, usage
   unique et expiration ;
9. préparer un signal synthétique autorisé, activer la préférence réelle,
   exécuter le job, vérifier le lien profond, relancer sans doublon, désactiver
   la préférence, puis tester un échec et sa reprise ;
10. vérifier les en-têtes reçus SPF, DKIM et DMARC avant toute conclusion.

Les sorties sont limitées à des compteurs et codes. Aucun jeton complet, aucune
adresse contrôlée, aucun contenu client et aucune valeur d'environnement ne
doivent entrer dans les preuves.

## Rollback

1. désactiver et arrêter `kivou-alerts.timer` ;
2. restaurer les unités précédentes, ou les laisser absentes si aucun runtime
   versionné ne précédait celui-ci ;
3. restaurer le SHA applicatif précédent ;
4. redémarrer l'API et vérifier le reset sans effectuer d'envoi non autorisé ;
5. ne downgrader `0023` que si la procédure de release le décide explicitement ;
6. si le downgrade n'est pas sûr dans le contexte réel, restaurer la sauvegarde
   selon la procédure PostgreSQL validée.

Le downgrade `0023` supprime uniquement les colonnes et le lease ajoutés par ce
chantier. Les colonnes historiques de livraison restent présentes ; une
restauration complète reste l'autorité en cas d'incident de migration.

## Gates restant avant production

- fusion dans `main` et CI verte sur le SHA final de `main` ;
- sauvegarde staging vérifiée puis migration `0023` réelle ;
- installation et activation staging du service et du timer ;
- reset réel réussi sur la boîte contrôlée ;
- alerte réelle réussie, lien profond, préférence, non-duplication et reprise
  contrôlée validés ;
- en-têtes reçus confirmant SPF, DKIM et DMARC ;
- revue des journaux expurgés ;
- autorisation distincte avant toute production.

RTL-05 ne doit être déclaré « validé sur staging » qu'après les deux messages
réels, et « opérationnel » qu'après validation du service, du timer et des
en-têtes DNS. À ce stade, aucun message externe, déploiement, DNS ou changement
de production n'a été effectué.
