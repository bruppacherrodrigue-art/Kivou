# Rotation expurgée des secrets de staging

Cette procédure est réservée à `kivou-staging`. Elle ne donne aucune autorité
sur la PRODUCTION et interdit toute clé Stripe LIVE. Elle tourne uniquement
depuis un SHA fusionné de `main`, avec CI verte, pendant une fenêtre de
maintenance annoncée.

Les quatre valeurs concernées sont exactement :

- `KIVOU_DATABASE_URL` ;
- `SMTP_PASSWORD` ;
- `STRIPE_SECRET_KEY` en mode TEST ;
- `STRIPE_WEBHOOK_SECRET` pour l'endpoint TEST.

## Périmètre et interdictions

Une valeur secrète ne doit jamais apparaître dans `argv`, une commande
`sudo env`, un argument de `grep` ou `rg`, un terminal, le `shell history`, Git,
GitHub, une issue, une PR, un ticket, la sortie CI ou journald. Ne jamais la
copier-coller dans une commande. La seule saisie interactive autorisée ci-dessous
passe par `/dev/tty` avec l'écho désactivé : les frappes n'apparaissent donc pas
dans le terminal. Les commandes ne transportent que des chemins et des noms de
variables ; les sorties ne contiennent que des compteurs.

Tout dry-run qui dépend de la configuration déployée passe exclusivement par
`systemd-run` avec
`--property=EnvironmentFile=/etc/kivou/staging.env`. Ne pas charger le fichier
avec un shell et ne pas préserver un environnement `sudo`.

Arrêter immédiatement si l'un des fichiers protégés est un lien symbolique,
n'est pas régulier, n'a pas le mode exact `0600`, contient une clé inconnue, une
clé en double, une valeur vide ou une valeur multiligne. Le CLI refuse ces cas
sans imprimer le détail fautif.

## 1. Préparer un espace tmpfs root-only

Vérifier d'abord que le chemin n'existe pas, puis créer un montage éphémère
distinct. Aucun fichier ne doit être créé sur un stockage persistant.

```bash
sudo test ! -e /run/kivou-secret-rotation
sudo install -d -o root -g root -m 0700 /run/kivou-secret-rotation
sudo mount -t tmpfs \
  -o nodev,nosuid,noexec,mode=0700,size=1M \
  tmpfs /run/kivou-secret-rotation
sudo stat -c '%U:%G %a %n' /run/kivou-secret-rotation
```

Le dernier contrôle doit rendre `root:root 700` et aucun contenu secret.

Créer une sauvegarde temporaire root-only et extraire les quatre anciennes
valeurs vers un fichier séparé, sans passage par le terminal :

```bash
sudo cp --preserve=mode,ownership,timestamps \
  /etc/kivou/staging.env \
  /run/kivou-secret-rotation/staging.env.backup
sudo chown root:root /run/kivou-secret-rotation/staging.env.backup
sudo chmod 0600 /run/kivou-secret-rotation/staging.env.backup
sudo install -o root -g root -m 0600 /dev/null \
  /run/kivou-secret-rotation/old.values
sudo awk -F= '
  $1 == "KIVOU_DATABASE_URL" ||
  $1 == "SMTP_PASSWORD" ||
  $1 == "STRIPE_SECRET_KEY" ||
  $1 == "STRIPE_WEBHOOK_SECRET" { print }
' /etc/kivou/staging.env | sudo tee \
  /run/kivou-secret-rotation/old.values >/dev/null
sudo chown root:root /run/kivou-secret-rotation/old.values
sudo chmod 0600 /run/kivou-secret-rotation/old.values
sudo install -o root -g root -m 0600 /dev/null \
  /run/kivou-secret-rotation/new.values
```

Valider la structure de `old.values` avec un journal vide. La sortie autorisée
est uniquement un objet de trois compteurs, dont
`secret_values_checked=4`, `matching_lines=0` et
`matching_occurrences=0` :

```bash
sudo /usr/bin/python3.12 \
  /srv/kivou/app/ops/bin/kivou_secret_hygiene.py \
  audit-journal /run/kivou-secret-rotation/old.values </dev/null
```

## 2. Figer les consommateurs et enregistrer leur état

Enregistrer dans le même tmpfs l'état actif/activé des consommateurs avant de
les arrêter. Ce relevé ne contient que des noms d'unités et des états. Il sert à
restaurer exactement l'état précédent : une unité désactivée, notamment TED ou
un smoke statique, ne doit pas être activée par cette rotation.

Ordre d'arrêt : déclencheurs, jobs, puis API.

1. Arrêter les timers alertes, sauvegarde, SIMAP, BOAMP, DECP et TED qui sont
   actuellement actifs.
2. Attendre ou arrêter proprement leurs services oneshot ; ne pas tuer un
   processus au milieu d'une écriture durable.
3. Laisser tout runtime Acquisition déjà désactivé ou statique dans cet état.
4. Arrêter `kivou-api.service` en dernier.

Ne pas modifier Policy, le kill switch, le mode SHADOW, les migrations ou les
données pendant cette fenêtre.

## 3. Effectuer les rotations fournisseur et PostgreSQL

Effectuer d'abord les opérations depuis les consoles fournisseur approuvées,
uniquement dans les comptes staging/TEST : mot de passe SMTP, clé restreinte
Stripe TEST, puis secret de signature du webhook Stripe TEST. Quand le fournisseur
permet deux identifiants simultanés, créer le nouveau, valider Kivou, puis révoquer
l'ancien. Quand une rotation invalide immédiatement l'ancien identifiant,
conserver les consommateurs arrêtés jusqu'au remplacement atomique.

Après chaque rotation, lancer exactement la commande correspondante ci-dessous.
Le nom de clé et le chemin sont les seuls arguments. Le CLI lit la valeur depuis
`/dev/tty` avec `getpass` ; cette saisie masquée n'a aucun fallback sans écho. Il
met à jour `new.values` par remplacement atomique et ne sort que deux compteurs
numériques :

```bash
sudo /usr/bin/python3.12 \
  /srv/kivou/app/ops/bin/kivou_secret_hygiene.py \
  set-secret SMTP_PASSWORD \
  --values-file /run/kivou-secret-rotation/new.values
sudo /usr/bin/python3.12 \
  /srv/kivou/app/ops/bin/kivou_secret_hygiene.py \
  set-secret STRIPE_SECRET_KEY \
  --values-file /run/kivou-secret-rotation/new.values
sudo /usr/bin/python3.12 \
  /srv/kivou/app/ops/bin/kivou_secret_hygiene.py \
  set-secret STRIPE_WEBHOOK_SECRET \
  --values-file /run/kivou-secret-rotation/new.values
```

Les trois invites sont respectivement la saisie masquée du nouveau mot de passe
`SMTP_PASSWORD`, de la nouvelle `STRIPE_SECRET_KEY` TEST et du nouveau
`STRIPE_WEBHOOK_SECRET` TEST. Ne jamais rediriger ces invites, utiliser `echo`,
les lancer avec `systemd-run`, ni copier leur saisie dans une variable de shell.
Un échec laisse le fichier précédent intact et ne révèle aucune valeur.

Tourner ensuite localement le mot de passe PostgreSQL du rôle fixe `kivou_app`.
Cette commande utilise l'environnement actuellement authentifié comme ancienne
connexion et complète elle-même `new.values` :

```bash
sudo /srv/kivou/app/.venv/bin/python \
  /srv/kivou/app/ops/bin/kivou_secret_hygiene.py \
  rotate-postgres-password \
  --old-env-file /etc/kivou/staging.env \
  --values-file /run/kivou-secret-rotation/new.values
```

Le CLI génère le nouveau mot de passe en mémoire, écrit d'abord la nouvelle
`KIVOU_DATABASE_URL` candidate dans `new.values` par remplacement atomique, puis
ouvre la connexion avec l'ancienne URL lue en mémoire. La sémantique PostgreSQL
`ALTER ROLE` passe exclusivement par `PGconn.change_password`/`PQchangePassword` :
libpq chiffre le mot de passe côté client avant de l'envoyer par le protocole. Il
n'existe donc ni URL de base en `argv`, ni SQL contenant le mot de passe brut, ni
valeur dans stdout, stderr ou journald. Ne pas remplacer cet appel par
`ALTER ROLE ... PASSWORD %s` : les paramètres liés côté serveur ne sont pas
acceptés pour cette commande utility.

Si l'ancienne connexion échoue avant toute demande de changement, le CLI rend
`error=database_update_failed` et restaure atomiquement le fichier à ses trois
valeurs fournisseur. Corriger l'accès ancien puis relancer. Si la connexion est
perdue pendant la demande, il rend `error=database_state_unknown` et conserve la
candidate complète pour récupération : ne pas remplacer `staging.env`, ne pas
réessayer à l'aveugle et conserver les consommateurs arrêtés. Un DBA autorisé
doit alors déterminer, sans publier de valeur, si l'ancien ou le candidat
s'authentifie ; garder le candidat s'il est actif, relancer depuis l'ancien s'il
est encore actif, ou effectuer une rotation vers l'avant si aucun état n'est
prouvé.

Une fois les quatre rotations préparées, forcer à nouveau le propriétaire et le
mode, puis valider le fichier complet par un audit vide. `audit-journal` exige
exactement les quatre clés dans chaque fichier fourni. Seuls les compteurs sont
lus :

```bash
sudo chown root:root /run/kivou-secret-rotation/new.values
sudo chmod 0600 /run/kivou-secret-rotation/new.values
sudo /usr/bin/python3.12 \
  /srv/kivou/app/ops/bin/kivou_secret_hygiene.py \
  audit-journal /run/kivou-secret-rotation/new.values </dev/null
```

Exiger `secret_values_checked=4`, `matching_lines=0` et
`matching_occurrences=0`. Toute autre sortie bloque la suite.

## 4. Remplacer atomiquement l'environnement

Le CLI crée son fichier temporaire dans `/etc/kivou`, conserve uid, gid et mode,
fsync le fichier, utilise `os.replace`, puis fsync le dossier. Il conserve toutes
les lignes étrangères aux quatre noms autorisés.

```bash
sudo /usr/bin/python3.12 \
  /srv/kivou/app/ops/bin/kivou_secret_hygiene.py \
  replace-env \
  --values-file /run/kivou-secret-rotation/new.values \
  --target /etc/kivou/staging.env
sudo stat -c '%U:%G %a %n' /etc/kivou/staging.env
```

La première sortie ne contient que les compteurs `secret_values_replaced=4` et
`target_lines_written`. La seconde doit rendre exactement
`root:kivou 600 /etc/kivou/staging.env`. Une divergence d'identité ou de mode
déclenche le Rollback avant tout redémarrage.

## 5. Redémarrer et prouver chaque consommateur

Ordre de reprise : preuve DB, API, jobs DB, SMTP, puis Stripe. Restaurer ensuite
uniquement les timers qui étaient actifs avant la fenêtre.

### PostgreSQL

Exécuter la readiness applicative dans une unité transitoire avec la même
configuration que systemd. Elle doit finir à zéro sans exception brute :

```bash
sudo systemd-run \
  --unit=kivou-secret-db-proof \
  --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  /srv/kivou/app/.venv/bin/python -m signals.operations readiness
```

### API

Démarrer `kivou-api.service`, exiger `active/running`, puis vérifier que
`/openapi.json` répond `200` et qu'un endpoint authentifié sans session répond
`401`. Ne publier que les codes HTTP, jamais les corps ou en-têtes sensibles.

### Sauvegarde, ingestions et Acquisition

1. Lancer une sauvegarde ponctuelle et vérifier son résultat ainsi que la table
   des matières du dump, sans afficher sa configuration.
2. Réexécuter un cycle borné pour SIMAP puis BOAMP, DECP et TED seulement si
   chacun était autorisé avant la fenêtre ; vérifier le statut durable et le
   checkpoint.
3. Ne lancer aucun runtime Acquisition ou smoke provider qui était désactivé.

Une unité échouée n'est pas masquée par un redémarrage global. Corriger ou
revenir en arrière avant de poursuivre.

### SMTP

Depuis un compte synthétique staging approuvé, demander une réinitialisation de
mot de passe par l'interface Kivou. Exiger la réponse API attendue, la réception
dans la boîte synthétique et un unique résultat de livraison expurgé. Ne publier
ni adresse, ni lien, ni token, ni Message-ID. Ensuite seulement, restaurer le job
d'alertes et son timer s'ils étaient actifs.

### Stripe TEST Checkout et webhook signé

Depuis un compte synthétique staging, ouvrir un Stripe TEST Checkout par le flux
Kivou et confirmer qu'une session TEST est créée sans prélèvement LIVE. Depuis
le Dashboard Stripe en mode TEST, envoyer un événement test à l'endpoint staging
déjà configuré. Exiger que le webhook Stripe TEST signé soit accepté et que
l'événement durable attendu apparaisse une seule fois. Ne pas utiliser un secret
de signature local sur une ligne de commande.

Toute preuve Stripe montrant LIVE ou toute ressource PRODUCTION arrête la
procédure sans appel supplémentaire.

## 6. Révoquer, purger journald et auditer en mémoire

Après les cinq preuves, révoquer les anciens identifiants encore valides chez
les fournisseurs. Faire tourner puis purger les archives journald selon la
politique de l'hôte afin que les segments susceptibles de contenir les anciennes
valeurs ne persistent pas :

```bash
sudo journalctl --rotate
sudo journalctl --vacuum-time=1s --vacuum-size=1K
```

Auditer ensuite tous les journaux restants contre les anciennes **et** nouvelles
valeurs. Les valeurs sont lues depuis les deux fichiers `0600`, conservées
uniquement en mémoire et jamais transmises à l'outil de lecture du journal :

```bash
sudo journalctl --all --no-pager -o cat | \
  sudo /usr/bin/python3.12 \
  /srv/kivou/app/ops/bin/kivou_secret_hygiene.py \
  audit-journal \
  /run/kivou-secret-rotation/old.values \
  /run/kivou-secret-rotation/new.values
```

Le CLI sort exactement `secret_values_checked`, `matching_lines` et
`matching_occurrences`, tous numériques. Il retourne non-zéro si une occurrence
est trouvée. Exiger `secret_values_checked=8`, `matching_lines=0` et
`matching_occurrences=0`. Publier uniquement ces trois compteurs, le SHA déployé
et les résultats non sensibles des cinq preuves.

Si un compteur de correspondance est non nul, ne jamais chercher la valeur à la
main. Identifier les unités par fenêtres temporelles et compteurs, corriger la
source, refaire rotation/purge, puis relancer l'audit complet.

## 7. Détruire les copies temporaires

Après validation complète et audit à zéro, détruire les deux jeux de valeurs et
la sauvegarde root-only, démonter le tmpfs, puis retirer le point de montage :

```bash
sudo rm -- \
  /run/kivou-secret-rotation/old.values \
  /run/kivou-secret-rotation/new.values \
  /run/kivou-secret-rotation/staging.env.backup
sudo umount /run/kivou-secret-rotation
sudo rmdir /run/kivou-secret-rotation
```

Vérifier que le chemin n'existe plus. Aucune copie d'une valeur compromise ne
doit rester dans `/run`, `/etc`, un home opérateur ou un artefact de validation.

## Rollback

Déclencher le rollback à la première preuve échouée, avant la révocation finale
et la destruction des fichiers :

1. arrêter à nouveau timers, jobs et API dans l'ordre de la section 2 ;
2. réactiver les anciens identifiants côté fournisseur quand c'est possible ;
3. restaurer les quatre anciennes valeurs avec `replace-env`, en prenant
   `/run/kivou-secret-rotation/old.values` comme fichier de valeurs, uniquement
   si l'ancien mot de passe PostgreSQL est encore prouvé actif ;
4. vérifier de nouveau `root:kivou` et `0600` ;
5. redémarrer et revalider dans l'ordre PostgreSQL, API, sauvegarde/ingestions,
   SMTP, Stripe TEST ;
6. restaurer exactement les états de timer enregistrés avant la fenêtre ;
7. faire rotation/purge de journald, auditer les deux jeux de valeurs, puis
   détruire les trois fichiers et le tmpfs comme en section 7.

Après un changement PostgreSQL réussi, l'ancien fichier n'est plus un rollback
valide tant qu'un DBA n'a pas explicitement retourné le rôle vers l'ancien mot de
passe. Après `database_state_unknown`, la candidate est volontairement conservée
et aucun des deux jeux n'est supposé actif. Si PostgreSQL ou un fournisseur ne
permet pas de prouver ou réactiver l'ancien identifiant, ne pas restaurer un
fichier devenu faux : effectuer une rotation vers l'avant, reconstruire un
fichier complet `new.values`, puis reprendre à la section 4. Le rollback ne
justifie jamais une valeur PRODUCTION/LIVE, une copie persistante ou une
exposition de secret.
