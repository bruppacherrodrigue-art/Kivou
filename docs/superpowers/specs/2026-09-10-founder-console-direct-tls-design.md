# Founder Console Direct TLS Design

## Objectif

Publier l'unique console Founder sur `https://control.kivou.eu` directement depuis le serveur de production, sans Cloudflare, tunnel ni Access. La console conserve son frontend, son service FastAPI sur `127.0.0.1:8011`, son accès PostgreSQL en lecture seule et son déploiement par `kivou-deploy.sh`.

## DNS et TLS

Rodrigue crée chez son registrar un enregistrement DNS de type `A` :

```text
control.kivou.eu.  A  179.237.105.52
```

La valeur est l'adresse IPv4 actuellement publiée par `kivou.eu`. Aucun proxy DNS ou tunnel ne se place devant nginx.

Le site nginx possède un serveur HTTP sur les interfaces publiques, réservé à `/.well-known/acme-challenge/` et à la redirection du reste vers HTTPS. Le certificat est obtenu avec `certbot certonly --webroot`, comme pour `kivou.eu`, afin que Certbot ne réécrive pas le gabarit versionné. Le serveur HTTPS écoute publiquement sur 443 pour le seul nom `control.kivou.eu` et référence explicitement les fichiers sous `/etc/letsencrypt/live/control.kivou.eu/`.

## Authentification et secret d'origine

Le serveur HTTPS applique `auth_basic` à toutes les ressources de la console. L'unique identifiant est `rodrigue`. Le fichier `/etc/kivou/founder.htpasswd` est créé sur le serveur, reste hors dépôt et n'est lisible que par les comptes système qui en ont besoin. Un mot de passe aléatoire fort est généré lors de l'installation, transmis une seule fois à Rodrigue, puis n'est inscrit ni dans le dépôt ni dans la documentation.

nginx ignore toute identité ou tout secret fourni par le client et fixe lui-même :

- `X-Kivou-Founder-User` depuis `$remote_user` ;
- `X-Kivou-Founder-Origin-Secret` depuis le fichier root-managed existant.

L'API Founder refuse une requête si le secret d'origine est absent ou incorrect, ou si l'utilisateur transmis par le proxy n'est pas exactement `rodrigue`. `KIVOU_FOUNDER_ALLOWED_USER=rodrigue` devient un paramètre obligatoire. Le courriel Founder existant reste dans la configuration et dans le contrat de session comme métadonnée affichée ; il n'est plus une assertion Cloudflare.

Cette combinaison protège aussi contre l'ajout accidentel d'un second compte au fichier htpasswd : seul l'utilisateur configuré est accepté par le service. Le port 8011 reste lié à loopback et ne doit jamais être publié.

## Routage et isolation

Le vhost HTTPS sert le frontend depuis `/srv/kivou-founder/frontend` et ne proxifie que `/api/founder/` vers `127.0.0.1:8011`. Le endpoint `/healthz` peut également être proxifié pour les contrôles authentifiés du vhost ; le contrôle de processus local continue d'appeler directement `127.0.0.1:8011/healthz`.

Les familles `/api/`, `/internal/`, `/app/` et toutes les routes publiques du SaaS client répondent explicitement 404 sur le nom Founder. Le repli SPA ne s'applique qu'aux routes propres au frontend Founder. Inversement, aucune route, redirection, ressource ou navigation vers la console Founder n'est ajoutée au vhost ou au frontend de `kivou.eu`.

## Déploiement et exploitation

Le fichier `ops/examples/cloudflared-founder.yml.example` est supprimé. `docs/FOUNDER_CONSOLE.md` est réécrit pour supprimer les exigences Cloudflare et documenter :

1. l'enregistrement DNS `A` ;
2. la création initiale du vhost HTTP et du répertoire webroot ACME ;
3. l'émission du certificat avec `certbot certonly --webroot` ;
4. la création hors dépôt du htpasswd et la transmission unique du mot de passe ;
5. la génération et l'installation du secret d'origine ;
6. l'activation du vhost HTTPS par la procédure candidate, validation et rollback de `kivou-deploy.sh` ;
7. les contrôles locaux et publics avec et sans Basic Auth.

Le déploiement continue de construire `frontend/dist-founder`, de le publier atomiquement dans `/srv/kivou-founder/frontend`, d'installer l'unité `kivou-founder-api` et le gabarit nginx, puis de valider la configuration avant rechargement.

## Gestion des échecs

- Avant propagation DNS, Certbot n'est pas lancé.
- Sans certificat valide, le serveur HTTPS n'est pas activé.
- Sans fichier htpasswd ou secret d'origine lisible, la validation ou le démarrage doit échouer plutôt que publier une console non protégée.
- Une requête publique sans Basic Auth reçoit `401` avec le challenge nginx.
- Une requête ayant franchi nginx mais dont l'utilisateur ou le secret ne correspond pas reçoit un refus de l'API.
- Les chemins client ou internes reçoivent 404 et ne tombent jamais dans le frontend Founder.

## Vérification

Les tests automatisés couvrent la structure des deux serveurs nginx, le challenge ACME, la redirection HTTPS, les chemins explicites du certificat, la présence globale de Basic Auth, le fichier htpasswd hors dépôt, l'écrasement des deux en-têtes de confiance, la suppression des en-têtes Cloudflare, l'isolation des routes client et les refus de l'API lorsque l'utilisateur ou le secret est incorrect.

Les smoke tests d'exploitation vérifient ensuite :

- le service local sur `127.0.0.1:8011` ;
- un `401` public sans identifiants ;
- un accès HTTPS réussi avec `rodrigue` et le mot de passe transmis ;
- une réponse 404 pour une route du SaaS client sur `control.kivou.eu` ;
- l'absence de route Founder sur `kivou.eu` ;
- le certificat et son renouvellement Certbot.

## Hors périmètre

Le changement ne crée pas de console staging, de compte Founder supplémentaire, de mécanisme de récupération de mot de passe, de route d'écriture ni de nouvelle permission PostgreSQL. Il ne modifie pas le contenu métier du frontend ou des read models.
