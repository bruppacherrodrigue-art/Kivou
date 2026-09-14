# V11 — procédure de répétition sur une copie complète de staging

> Deux répétitions réelles ont été refusées avant activation ; **aucune répétition complète validée à cette mise à jour**. La seconde prouve la conservation exhaustive de260069lignes privées mais bloque sur les faits RAZEL ; voir [implementation.md](implementation.md). Elles complètent L14 avant toute activation. Le déployeur existant reste inchangé. Ce document n'est pas un script automatique de création/suppression de bases.

**Objectif :** vérifier migration, conservation des valeurs privées, révisions, export et reprise BOAMP sur une restauration complète, sans aucune écriture dans la base vive.

**Architecture :** dump PostgreSQL en lecture seule, restauration dans une base explicitement créée pour cette invocation, candidate utilisée exclusivement contre cette copie, puis suppression de cette seule base. Les contrôles métier appellent les fonctions du domaine : ils ne démarrent ni API, ni worker, ni fournisseur d'enrichissement.

**Outils :** environnement protégé systemd de staging, outils PostgreSQL déjà utilisés par le déployeur, Python de la release candidate, SQLAlchemy et psycopg. Opérateur : root sur `kivou-staging`, processus de travail sous utilisateur `kivou` lorsque ses droits le permettent.

## Helper livré et preuve locale

[rehearsal-checks.py](rehearsal-checks.py) est un helper de **contrôles uniquement** : ni dump, ni CREATE/DROP, ni bascule de liens. Version streaming de `tests/test_staging_rehearsal_checks.py` : **54/54, sans skip**, SQLite et PostgreSQL jetable local ;75,43s dans le worktree isolé puis105,73s après intégration, code0, `/tmp/kivou-v11-streaming-helper-integrated.log`. Ruff et compilation verts. La suite remplace la preuve35/35 de la version en mémoire ; elle couvre notamment10017descendants privés, dernier lot modifié/supprimé, limites de stockage et nettoyage. Données synthétiques et lecteur BOAMP injecté : ni restauration complète de staging ni couverture des quatre avis publics réels. La concurrence identité est validée séparément : six cas ciblés puis85/85 sans skip, références dans [qa-matrix.md](qa-matrix.md).

Après restauration et validation des cibles par le driver opérateur, lancer le helper sans argument avec le Python de la candidate :

```text
.venv/bin/python docs/reports/prospecting-v11/rehearsal-checks.py
```

Le sous-processus doit recevoir exclusivement le contrat suivant, sans DSN dans les logs :

- `KIVOU_V11_REHEARSAL_DATABASE_URL` et `KIVOU_DATABASE_URL` : la **même URL de copie** après normalisation du pilote, jamais celle de la base vive.
- `KIVOU_V11_REHEARSAL_DATABASE_NAME` : nom exact `kivou_v11_rehearsal_<SHA12>_<aléatoire16hex>` ; le helper vérifie aussi `current_database()`.
- `KIVOU_V11_CANDIDATE_SHA` : SHA de 40 caractères hexadécimaux égal au HEAD de la candidate ; ses douze premiers caractères doivent correspondre au nom de copie.
- `KIVOU_V11_REHEARSAL_CURSOR` : chemin dans un répertoire privé 0700, curseur 0600, verrou de reprise exclusif. Retirer URL de maintenance et variables `PG*` ambiantes avant construction de l'environnement enfant.

Les sections 3–5 décrivent les assertions du helper et la revue métier complémentaire ; ne pas lancer en plus une reprise CLI indépendante. Le helper imprime uniquement un JSON agrégé : code 0 `passed`, code 2 `failed` avec motif fermé, code 3 `coverage_incomplete`. Le driver opérateur conserve un `report.json` atomique0600/fsync dans son répertoire0700, avec étape, codes fermés et résultats du nettoyage. Aucune erreur d'écriture de ce rapport ne doit empêcher la suppression de la seule copie validée par OID. Lancer le driver dans une unité systemd asynchrone `Type=oneshot`, `TimeoutStartSec=infinity`, `RemainAfterExit=yes` ; contrôler journal et résultat avant d'arrêter l'unité. Ne pas utiliser un long pipe SSH ni qualifier de succès les valeurs par défaut d'une unité déjà collectée.

Un succès du helper reste insuffisant sans les contrôles opérateur de restauration, repli, nettoyage et sources réelles. Le gate backend et la CI de476 sont verts (voir `implementation.md`) ; L13/L14 ne sont pas validés par ces seules preuves locales. La première copie complète a révélé 26 tables privées, 260069lignes dont256322phrases de profil ; l'ancienne limite10000 était donc insuffisante. La comparaison exhaustive ci-dessous remplace cette limite en mémoire, sans exclure ces descendants privés.

## 1. Verrouiller les cibles avant toute commande

- [ ] Vérifier hors journal les deux URL de `/etc/kivou/staging.env` : `KIVOU_DATABASE_URL` désigne la base **staging**, `KIVOU_MIGRATION_ADMIN_URL` sa base de maintenance sur le même cluster. Comparer hôte/port et noms de bases aux valeurs d'exploitation déjà vérifiées. Un nom « staging » n'est pas, à lui seul, une preuve de cible.
- [ ] Vérifier HEAD de la release candidate et conserver les cibles actuelles de `/srv/kivou/app` et `/srv/kivou/frontend`. Aucun changement de lien, restart API, nginx actif, timer ou configuration production pendant la répétition.
- [ ] Créer un répertoire avec `mktemp -d /var/tmp/kivou-v11-rehearsal.XXXXXX`, mode `0700`, sous `umask 077`. Le dump, les curseurs et les journaux expurgés restent dans ce répertoire privé. Ne jamais exécuter `set -x`.
- [ ] Générer un nom de base de la forme `kivou_v11_rehearsal_<12hexSHA>_<16hexaléatoires>`. Validation obligatoire : `re.fullmatch(r"kivou_v11_rehearsal_[0-9a-f]{12}_[0-9a-f]{16}", name)`. Exiger qu'il diffère de la base source et de la base de maintenance.
- [ ] Initialiser `created = False` en mémoire. Refuser une base déjà existante ; ne pas la vider et ne pas employer `--if-exists` pour cacher une collision.

Les paramètres libpq sont transmis par l'environnement du **seul sous-processus** concerné (`PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, `PGPASSWORD` et options TLS existantes), pas par une URL avec mot de passe dans argv. Retirer les variables `PG*` héritées avant de construire cet environnement explicite. Préserver le mode TLS configuré ; ne pas le désactiver pour faire réussir l'essai. Ne jamais imprimer ces paramètres.

## 2. Dump protégé, création et restauration

- [ ] Utiliser `ops/bin/kivou-backup.sh` de la candidate avec son `KIVOU_BACKUP_DIR` limité au répertoire privé de cette invocation. Cette opération utilise le `KIVOU_DATABASE_URL` source uniquement pour `pg_dump`. Vérifier code retour, fichier unique produit, mode `0600` et taille non nulle. Ne pas choisir un ancien dump par glob dans le répertoire de sauvegarde partagé.
- [ ] Depuis la connexion **maintenance**, en autocommit, créer la base avec un identifiant SQL cité par `psycopg.sql.Identifier`, pas par interpolation brute :

```python
admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
created = True
```

- [ ] Immédiatement enregistrer, en mémoire, son OID obtenu dans `pg_database` avec `WHERE datname = %s`. Cette identité sera revérifiée avant suppression. Ne pas attribuer l'accès aux services API/worker vivants.
- [ ] Exécuter `pg_restore --exit-on-error --no-owner --no-privileges --dbname NOM_EXACT_COPIE` avec `PGDATABASE=name` et les paramètres du cluster de maintenance. Le nom seul, sans mot de passe, est passé par `--dbname` pour imposer une restauration effective et non l'émission d'un script SQL. Le seul argument fichier est le dump explicitement créé plus haut. Capturer stderr dans le répertoire privé ; ne pas publier ses détails SQL.
- [ ] Construire une URL SQLAlchemy de copie avec `URL.set(database=name)`, jamais par substitution textuelle de morceaux de l'URL source. Le Python de la candidate reçoit cette URL via `KIVOU_V11_REHEARSAL_DATABASE_URL` **et** `KIVOU_DATABASE_URL`, obligatoirement égales après normalisation du pilote. Retirer du sous-processus l'URL de maintenance et les autres configurations KIVOU inutiles. Même une factory appelée par défaut ne doit disposer que de la copie. Le driver garde seul la connexion source en lecture seule.
- [ ] Avant chaque phase mutante, vérifier par requête `SELECT current_database()` que la connexion désigne exactement `name`. Exiger aussi le préfixe validé. Ne jamais laisser une fonction appelée sans URL explicite retomber sur `KIVOU_DATABASE_URL` source.

## 3. Mesurer puis migrer les vrais enregistrements restaurés

- [ ] **Avant migration**, réfléchir les tables de la copie. Partir des tables possédant `account_id`, puis inclure transitivement leurs descendants par clés étrangères : `auth_session` et `password_reset` via `auth_user`, `for_you_sentence` via le profil. Inventorier **toutes les lignes**, sans filtrage d'appartenance implicite ni échantillon. Conserver les anciennes clés primaires typées, propriétaire et HMAC-SHA256 de toutes les colonnes d'origine ; clé HMAC éphémère uniquement en mémoire. Aucun corps ni hash de note n'est publié.
- [ ] Stockage temporaire privé SQLite0600 sous dossier0700, plafonné256MiB par pages, cache2MiB, journaux désactivés ; ligne canonique≤4MiB, clé≤16KiB. Lecture serveur par16lignes, comparaison par128anciennesPK, normalisation canonique des objetsJSON/nombres/dates. Tout dépassement ferme la répétition, jamais un succès partiel. `MAX_ROWS=10000` reste seulement un garde optionnel explicitement demandé, pas une limite de l'exécution normale. Ces bornes concernent la **baseline**, pas `export_account`, qui conserve son contrat métier réel et charge un compte à la fois.
- [ ] Appeler uniquement `migrate_to_latest(copy_engine)` puis vérifier `current_revision(copy_engine) == "0060_boamp_notice_facts"` et une seule tête Alembic. Aucune migration avec le moteur source.
- [ ] Relire chaque clé primaire inventoriée et comparer l'empreinte canonique de **toutes ses colonnes d'origine** à celle d'avant migration. Les colonnes nouvelles telles que `revision` ne font pas partie de cette égalité. Exiger également que chaque ancienne clé existe encore. Une modification ou suppression dans le dernier lot doit être détectée ; de nouvelles lignes restent autorisées. Fermer et supprimer la baseline temporaire dans `finally`, y compris en échec de migration.
- [ ] Exécuter `audit_identity_batch(copy_engine, phase="registry", execute=True, limit=100)` jusqu'à `complete`, puis la phase `accounts` avec ses deux curseurs. Respecter les pages (borne helper1000 pages par phase) ; inspecter les compteurs `isolated`, `conflict`, `blocked`. Les quarantaines d'identité ne doivent jamais devenir des fusions privées. Le mutex transactionnel PostgreSQL précède les verrous alias puis compte ; le verrou compte `FOR NO KEY UPDATE` ne bloque pas le `KEY SHARE` d'une FK workflow déjà détenue. Le test SQLite équivalent prend son verrou d'écriture par UPDATE sans ligne modifiée avant toute lecture d'identité.
- [ ] Refaire l'égalité de toutes les anciennes lignes après réconciliation. Des nouvelles copies canoniques sont permises ; la modification ou disparition d'une ancienne ligne ne l'est pas.

## 4. Notes, tombstones, workflow et export sur la copie

Créer deux comptes **synthétiques uniquement dans la copie**, avec des identifiants aléatoires préfixés `v11_rehearsal_`, sans utilisateur authentifiable, sans abonnement, profil, outbox ni destinataire. Les valeurs métier sont synthétiques ; les clés de signal et d'entreprise le sont aussi. Les tables de notes et workflow n'exigent pas une annonce réelle. Chaque mutation réussie doit être commitée, puis relue sur une nouvelle connexion pour exercer une vraie persistance.

Fonctions et signatures réelles à utiliser :

```python
from signals.engagement import company, notes, status
from signals.engagement.feedback import SignalContext
from signals.client_value import user_contacts
from signals.accounts.data_rights import export_account

notes.put(c, account_id=owner, signal_key=signal, note=text,
          expected_revision=expected, now=now)
company.put_note(c, account_id=owner, company_key=company_key, body=text,
                 expected_revision=expected, now=now)
user_contacts.put_contact(c, account_id=owner, company_key=company_key,
    payload=user_contacts.ManualContactWrite(
        name="Contact de répétition", email="rehearsal@example.com", expected_revision=expected),
    now=now)
user_contacts.delete_contact(c, account_id=owner, company_key=company_key,
                             expected_revision=expected, now=now)
context = SignalContext(signal_key=signal, opportunity_key="v11_rehearsal_opportunity",
    target_icp_id="v11_rehearsal_profile", revision=1, event_status="active", event_age_days=1)
status.set_status(c, account_id=owner, context=context, status=target,
                  expected_revision=expected, now=now)
payload = export_account(c, account_id=owner)
```

Assertions obligatoires, pour les notes signal **et** entreprise :

- [ ] Écriture initiale de 2000 caractères à révision attendue `0` → révision `1`, texte conservé après nouvelle connexion.
- [ ] Deuxième écriture à révision attendue `1` → révision `2` ; rejeu ancien à `1` → `notes.NoteRevisionError`, aucune modification. Effectuer cette tentative dans sa propre transaction et la rollbacker.
- [ ] Effacement à révision `2` → révision `3`, texte exposé `None` mais ligne conservée ; nouvel INSERT à révision `0` rejeté, révision toujours `3`.
- [ ] Texte de 2001 caractères rejeté ; aucun écrasement du tombstone.
- [ ] Le deuxième compte, avec la même clé de signal/entreprise, ne lit ni ne modifie les lignes du premier ; son écriture propre reste indépendante.
- [ ] Contact personnel : création `0→1`, suppression `1→2`, vue `contact=None`, ligne/tombstone conservés ; ancien `put_contact(expected_revision=1)` rejeté par `ContactConflict`, aucune résurrection.
- [ ] Workflow : `saved` à révision `0` → `1`, `ignored` à `1` → `2`, `new` à `2` → `3`, `contacted` à `3` → `4`, puis `new` à `4` → `5`. Un rejeu à `1` lève `StatusConflict` et doit rollbacker toute sa transaction. Après reconnexion, vérifier révision `5`, `feedback.contacted_at` conservé exactement, et `status.unified_status(historical, workflow) == "new"`, projection réellement utilisée par les GET. L'export doit conserver cet historique de contact sans rétablir le statut courant `contacted`.
- [ ] Export du compte synthétique : contient ses notes/tombstones, workflow, contact personnel, et seulement ses `account_id`. Exclut `password_hash`, `token_hash`, tables `notice_source_snapshot`/`notice_award_facts` et données de l'autre compte. Inspecter le dictionnaire **en mémoire**, ne pas écrire l'export privé dans les preuves publiques.
- [ ] Pour tous les comptes originaux inventoriés, appeler également `export_account` et vérifier la présence de leurs anciennes lignes `signal_note`, `company_note`, `signal_feedback`, `company_contact` ainsi que des tables V11 lorsqu'elles préexistaient. Vérifier que chaque ligne munie d'un `account_id` porte le bon compte. Respecter les exclusions intentionnelles de l'export (`account_deletion_request`, colonnes secrètes) ; ne pas publier le contenu.

Ces contrôles sont des contrôles du domaine réellement utilisé par l'API, pas une affirmation de recette HTTP complète. Le mapping des conflits en HTTP 409 reste couvert par les tests API ; la recette authentifiée sur compte de test a lieu selon le runbook après activation.

## 5. Reprise des quatre avis exacts

Dans **la base restaurée**, résoudre la sélection, sans payload du prototype :

```sql
SELECT source_notice_id, event_key, notice_version, event_type
FROM source_event
WHERE source_system = 'boamp'
  AND source_notice_id IN ('26-87113', '26-84423', '26-85899', '26-88050')
ORDER BY source_notice_id, event_key;
```

- [ ] Exiger au moins une ligne pour chaque avis et au maximum 100 clés au total. Ne pas sélectionner arbitrairement une version avec `LIMIT 1`. Une absence bloque la preuve Q23 correspondante ; ne pas élargir silencieusement une fenêtre de dates. Les avis GJG supplémentaires `26-87168` / `26-85068` ne remplacent pas automatiquement `26-88050`.
- [ ] Le helper transmet au domaine la sélection `event_keys` exactement résolue dans la copie, puis un dry-run sans lecteur et les passes execute avec curseur privé. Équivalent CLI de référence seulement, **à ne pas rejouer indépendamment du helper** ; conserver le même curseur et la même URL de copie si une reprise manuelle est nécessaire :

```text
python -m signals.client_value.notice_backfill --limit 100 [chaque --event-key exact]
python -m signals.client_value.notice_backfill --execute --limit 100 --cursor-file CURSEUR_PRIVE [même sélection]
```

- [ ] Le premier appel est dry-run et ne fait aucun réseau. Seul `--execute` emploie le client BOAMP officiel, sa politique réseau et ses sources liées bornées. Aucun GET de fiche, Apollo, Stripe ou envoi commercial.
- [ ] Réutiliser le **même curseur** pour les tentatives suivantes, trois invocations de traitement au maximum pour cette sélection ; vérifier `pending`/`terminal` et les raisons fermées. Ne jamais effacer un curseur pour renouveler artificiellement les tentatives.
- [ ] Effectuer un rejeu supplémentaire de vérification lorsque la sélection est complète : zéro nouvel enregistrement snapshots/faits, aucune requête fournisseur si les faits sont déjà complets. Si la sélection a des terminaux `unsupported`/`exhausted`, les consigner comme couverture absente, pas comme succès d'extraction.
- [ ] Relire les faits typés par `load_award_notice_facts` et les clés `contract_award` de chaque `source_event`. Vérifier lot/titulaire/acheteur/source, montant décimal, unité et portée des durées ; pas de date de démarrage estimée. RAZEL : aucune durée 12/48 sans jointure démontrée avec la consultation. GJG : l'annulation de l'avis ne devient pas annulation du marché.
- [ ] Refaire la comparaison des anciennes lignes privées après ce backfill. Aucune note, statut, personne ou révision d'un compte original ne doit avoir changé.

## 6. Preuve de repli puis nettoyage borné

- [ ] Sur une configuration nginx **isolée**, avec upstream local inerte, tester le fragment maintenance candidat : écritures `/signals` et `/companies`, PATCH `/target-icps` → 503 ; GET, auth et webhook restent routés. Les tests ne doivent toucher ni nginx actif ni fournisseur. Conserver le code retour de `nginx -t` et les statuts HTTP, pas d'URL avec jeton.
- [ ] Le code historique peut être utilisé pour une lecture de note dans la copie migrée, avec URL de copie explicite. Ne pas lancer ses writers, migrations, startup workers ou tâches périodiques. Le repli réel conserve la base 0060 et le garde-fou fermé ; il ne restaure jamais le dump sur la base vive.
- [ ] Disposer les moteurs et terminer les sous-processus de répétition avant nettoyage. Depuis la connexion maintenance, vérifier à nouveau le nom, son préfixe, sa différence avec source/maintenance et son OID égal à celui enregistré après CREATE.
- [ ] Seulement si `created is True` et ces vérifications réussissent, exécuter `DROP DATABASE` avec `sql.Identifier(name)`, **sans FORCE**. Ne pas tuer les connexions du cluster ni employer un préfixe/glob comme cible. Si la suppression échoue, conserver la preuve privée et signaler cette unique base résiduelle ; ne pas prétendre le nettoyage réussi.
- [ ] Après confirmation de la suppression, supprimer le seul dump explicitement créé pour cette répétition. Le dump contient des données privées : ne pas l'archiver avec les captures publiques. Conserver uniquement le rapport expurgé et le curseur opaque selon la politique de preuves, puis retirer le répertoire temporaire s'il est vide.
- [ ] Vérifier que les deux liens actifs et la révision de la base vive sont identiques à leurs valeurs initiales. Pour la base vive : connexion `SET TRANSACTION READ ONLY`, seulement lecture Alembic ; pas de comparaison de valeurs privées exposée dans les logs.

**Rapport à conserver :** SHA candidat, heure, source staging validée (sans DSN), nom/OID de copie, nombre de tables/lignes historiques comparées, booléens de conservation/CAS/tombstone/isolation/export, statuts de couverture des quatre avis, idempotence, résultats du garde-fou, suppression de la copie/dump, liens actifs inchangés. Toute assertion échouée ou nettoyage non confirmé empêche de marquer cette répétition « validée ».
