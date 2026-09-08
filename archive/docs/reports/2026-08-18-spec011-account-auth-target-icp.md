# SPEC-011 — Compte, authentification et onboarding TargetICP

**Date** : 2026-08-18
**Portée** : le plus petit socle sûr permettant `INSCRIPTION → SESSION → COMPTE → TARGET ICP → PRÊT POUR LE FEED`
**Statut** : livré, non committé, en attente de revue superviseur

---

## 1. Cadre HTTP retenu — et pourquoi

Le dépôt n'avait aucun cadre HTTP avant cette SPEC. Inspection préalable :
`httpx` était déjà une dépendance (connecteur TED), `pydantic` v2 est la base du
modèle canonique (`CanonicalModel`), SQLAlchemy 2.0 Core est la couche de
persistance, et rien dans `src/signals/` ne suppose un serveur.

**Choix : FastAPI** (`fastapi>=0.115`).

- Il valide les corps de requête avec **pydantic v2**, la technologie déjà
  souveraine dans le projet. Aucun second système de validation n'apparaît.
- Son client de test appelle l'application en direct via `httpx`, déjà présent :
  la suite reste hors-ligne et sans serveur, comme le reste du dépôt.
- Il n'impose ni ORM, ni couche de données, ni structure de projet. SQLAlchemy
  Core reste inchangé.

Les points d'entrée sont **synchrones** : SQLAlchemy Core est synchrone, et une
façade `async` au-dessus d'un pilote bloquant n'apporterait qu'une illusion de
concurrence. Le serveur ASGI de production (`uvicorn`) est un extra
`server = [...]`, inutile aux tests.

Rien de ce qui était interdit n'a été construit : pas de microservices, pas de
GraphQL, pas d'authentification événementielle, pas d'API gateway, pas de
service d'identité séparé. Une seule application, une seule base.

## 2. Stratégie d'authentification

Un compte (`account`) porte un ou plusieurs utilisateurs (`auth_user`). Le MVP
en crée un seul à l'inscription, mais le schéma ne l'interdit pas pour la suite.

L'adresse est **normalisée** avant stockage et comparaison
(`normalize_email` → minuscules, espaces retirés) et porte une contrainte
`UNIQUE`. La casse ne peut donc pas dupliquer un compte.

Toute la logique vit dans `signals/accounts/service.py`, **sans dépendance
HTTP** : elle prend une `sa.Connection` et un `now` explicite, et retourne des
objets simples. La couche FastAPI ne fait que traduire.

## 3. Hachage des mots de passe

`argon2-cffi` (`PasswordHasher(type=Type.ID)`) — **Argon2id**, paramètres par
défaut de la bibliothèque, qui suivent les recommandations courantes. Aucune
cryptographie maison : pas de sel géré à la main, pas de SHA-256 sur mot de
passe, pas de chiffrement réversible.

- `MINIMUM_PASSWORD_LENGTH = 12`, `MAXIMUM_PASSWORD_LENGTH = 1024` (le plafond
  évite qu'une entrée démesurée serve de déni de service par coût de hachage).
- `verify_password` retourne `False` sur un échec ordinaire **et** sur une
  empreinte corrompue : une base abîmée refuse l'accès, elle ne plante pas.
- `needs_rehash` est **branché sur la connexion** : une empreinte périmée est
  réécrite lors d'une authentification réussie, dans la même transaction (§15.3).

## 4. Sessions

**Opaques et côté serveur.** `secrets.token_urlsafe(32)` produit un jeton de 256
bits ; le navigateur reçoit ce jeton brut, la base ne stocke que
`sha256(jeton)`. Une fuite de la table `auth_session` ne rend aucune session
utilisable.

SHA-256 est ici le bon outil — et non Argon2 : le jeton est déjà aléatoire sur
256 bits, il n'y a pas d'espace de recherche à ralentir. Le raisonnement est
écrit dans `signals/accounts/tokens.py` pour qu'il ne se reperde pas.

Cookie : `HttpOnly`, `Secure` (configurable, **vrai par défaut** ; le relâcher
est un acte explicite), `SameSite=Lax`, `Path=/`, expiration alignée sur la
session. Durée par défaut 14 jours (`KIVOU_SESSION_TTL_SECONDS`).

Aucun jeton n'est placé dans `localStorage`. `authenticate` refuse à
l'identique un cookie absent, un jeton inconnu, une session expirée et une
session révoquée — le client n'apprend pas laquelle des quatre.

**Aucune horloge cachée** : `request_now()` (frontière HTTP) est le seul endroit
où le temps entre dans le système ; `now` est ensuite passé explicitement à
chaque fonction du service, et remplaçable en test (`now_override`).

## 5. CSRF

**Validation stricte de l'origine** sur toute requête modifiante
(`POST/PUT/PATCH/DELETE`), doublée du cookie `SameSite=Lax`.

`Origin` est lu en premier, `Referer` sert de repli. Une requête modifiante
**sans aucune origine est refusée** : accepter l'absence offrirait le
contournement en clair. Les lectures ne sont pas bloquées. `/auth/login` est
protégé comme le reste — un login CSRF connecterait la victime sur le compte de
l'attaquant.

Le choix est motivé dans le module : pas d'état supplémentaire, pas d'échange
préalable, et un navigateur pose `Origin` lui-même — une page tierce ne peut pas
le falsifier. Coût assumé : un client non navigateur devra envoyer l'en-tête ;
le MVP sert un frontend web, et une future intégration machine aura ses propres
identifiants.

La protection n'est jamais désactivée pour simplifier un test : les tests
envoient une vraie origine, et deux tests vérifient explicitement le refus.

## 6. Réinitialisation de mot de passe

Même modèle que les sessions : jeton aléatoire remis au porteur, `sha256` en
base, TTL 1 heure (`KIVOU_PASSWORD_RESET_TTL_SECONDS`).

- **Usage unique** (`used_at`), et **toutes les sessions sont révoquées** à la
  confirmation — un mot de passe changé doit déconnecter le voleur.
- La demande répond `202` avec le même corps que le compte existe ou non.
- **Le jeton brut n'est jamais journalisé** : le module `accounts` et le module
  `api` ne contiennent aucun `logging`, `logger` ni `print`. Le jeton est remis à
  un `PasswordResetDelivery` (protocole injecté), jamais écrit ailleurs.

## 7. Schéma ajouté

Cinq tables, enregistrées dans le `METADATA` **partagé** importé de
`signals.persistence.schema` — une seule base, une seule chaîne de migration.

| Table | Rôle | Points notables |
|---|---|---|
| `account` | le client | `display_name`, `locale`, `onboarding_status` |
| `auth_user` | l'identifiant de connexion | `email_normalized` UNIQUE, `password_hash`, FK compte `ON DELETE CASCADE` |
| `auth_session` | session opaque | `token_hash` UNIQUE, `expires_at`, `revoked_at` |
| `password_reset` | jeton de réinitialisation | `token_hash` UNIQUE, `expires_at`, `used_at` |
| `target_icp` | le profil client | `customer_input` JSON, `status` (`draft`/`active`), FK compte |

Aucun type propre à un dialecte : les cinq tables compilent en DDL PostgreSQL
**et** SQLite, vérifié par test sans serveur — la discipline de SPEC-010 §3 est
étendue aux tables SPEC-011.

## 8. Chemin de migration 0001 → 0002

`0002_account_auth_target_icp`, `down_revision = "0001_initial"`.

**Strictement additif** : cinq `op.create_table` et six `op.create_index` dans
`upgrade()`, aucun `op.drop_table`, aucun `op.alter_column`, aucune table de
SPEC-010 touchée. Les suppressions n'existent que dans `downgrade()`.

Trois tests protègent le chemin :

- une base vide atteint `0002` avec les tables SPEC-010 **et** SPEC-011 ;
- **une base SPEC-010 déjà peuplée d'un signal réel** monte à `0002` sans perdre
  ce signal (`list_signals` le retrouve, même `signal_key`, même `target_icp_id`) ;
- migrer deux fois ne change rien.

`src/signals/persistence/migrations/env.py` gagne un unique
`import signals.accounts.schema  # noqa: F401` pour que l'autogénération voie
les nouvelles tables.

## 9. Modèle de propriété

```
account ──< auth_user ──< auth_session
   │                  └─< password_reset
   └──< target_icp ──< materialized_signal
```

Un signal appartient à un compte **par l'intermédiaire de son TargetICP**,
jamais directement : `materialized_signal` n'a **pas** de colonne `account_id`,
et un test l'interdit. Dupliquer la propriété créerait deux vérités qui
finiraient par diverger.

`account_id` n'existe dans **aucun schéma de requête**. La propriété est
toujours déduite de la session, et se trouve dans le `WHERE` de chaque requête
du service — pas dans une vérification postérieure qu'on peut oublier. Un
`account_id` envoyé par le client fait échouer la requête en `422` (`extra="forbid"`).

**Déviation reportée depuis SPEC-010 §5** : il n'y a toujours pas de clé
étrangère de `materialized_signal.target_icp_id` vers `target_icp`, parce que
les signaux SPEC-010 existants référencent des identifiants d'ICP de référence
et que SQLite ne sait pas ajouter une FK sans reconstruction destructive de la
table. L'invariant est tenu par le résolveur de propriété et par les tests — la
frontière de référence molle est écrite explicitement dans
`src/signals/accounts/ownership.py` (§15.2).

## 10. TargetICP : entrée client et traduction moteur

`signals/accounts/icp_input.py` définit **le contrat client**, délibérément
séparé du modèle moteur `TargetICP`.

Le client coche des libellés métier : `offers` (7 valeurs, ex.
`materials_and_components`), `buyer_trades` (8 valeurs, ex.
`building_construction`), `territories`, `minimum_contract_value`, plus un
`offer_summary` **purement déclaratif** — deux textes différents avec les mêmes
cases produisent le même profil moteur (leçon SPEC-008 : le texte libre ne
pilote rien).

La traduction vers `NeedCategory` / `TradeDomain` est **déterministe** (deux
tables de correspondance), jamais devinée. Les politiques moteur
(`geography_basis`, `unknown_value_policy`, `maximum_signal_age_days`,
`source_modes`, pondérations) sont **fixées par la plateforme**, pas exposées.
Un test vérifie qu'aucun terme moteur n'apparaît dans la réponse API.

Un champ client inconnu est **refusé** (`422`), pas ignoré silencieusement.

### API

| Méthode | Chemin | Rôle |
|---|---|---|
| POST | `/auth/signup` | crée compte + utilisateur + session, pose le cookie |
| POST | `/auth/login` | ouvre une session |
| POST | `/auth/logout` | révoque la session côté serveur, efface le cookie |
| GET | `/me` | identité, compte, locale, état d'onboarding |
| POST | `/auth/password-reset/request` | `202`, réponse identique dans tous les cas |
| POST | `/auth/password-reset/confirm` | change le mot de passe, révoque tout |
| GET | `/target-icps` | les profils **du compte seulement** |
| POST | `/target-icps` | crée un profil |
| GET | `/target-icps/{id}` | lit un profil du compte |
| PATCH | `/target-icps/{id}` | modifie un profil du compte |

La réponse TargetICP expose l'entrée client, le `status` et `missing_fields` —
jamais le profil moteur dérivé.

## 11. Logique de disponibilité (onboarding)

Trois états : `account_created` → `icp_incomplete` → `ready_for_signals`.

Un profil est `active` quand `offers`, `territories` et `minimum_contract_value`
sont présents — plus `buyer_trades`, exigé seulement si `secondary_buyer_trades`
est renseigné : dire ce qu'on accepte à regret sans dire ce qu'on vise ne décrit
rien. Sinon le profil reste `draft` et l'API **dit lesquels manquent**. Le compte passe
`ready_for_signals` dès qu'il possède au moins un profil `active`.

`ready_for_signals` signifie **complétude technique uniquement** : aucune notion
de paiement, d'essai, d'abonnement ou de droit d'accès n'apparaît nulle part —
un test le vérifie sur le corps de `/me`.

## 12. Tests

**Total du dépôt : 2267 tests, 0 échec, 0 test ignoré.** (Base SPEC-010 : 2170.)

| Fichier | Tests | Objet |
|---|---|---|
| `tests/test_accounts_security.py` | 34 | §16 + closeout §4 — invariants de sécurité, remise à niveau Argon2 |
| `tests/test_accounts_target_icp.py` | 29 | §13, §17 + closeout §5 — isolation, traduction, réversibilité de l'onboarding |
| `tests/test_accounts_migration_and_ownership.py` | 22 | §5, §17, §22 — migration, propriété, portabilité PostgreSQL |
| `tests/test_accounts_signal_binding.py` | 11 | closeout §3 — liaison client des signaux matérialisés |

**Aucun test n'est ignoré (`skipped`) dans l'ensemble du dépôt.**

### Sécurité (28)

Mot de passe jamais en clair en base ; empreinte qui ne valide que le bon mot de
passe ; empreinte corrompue = refus, pas plantage ; mot de passe court refusé
par l'API. Jeton de session brut jamais stocké ; jeton inconnu, session expirée,
session révoquée refusés ; `logout` révoque côté serveur ; cookie `HttpOnly` ;
`Secure` quand configuré. Jeton de réinitialisation stocké haché, expirant,
**à usage unique**, invalidant **toutes** les sessions ; l'ancien mot de passe
cesse de fonctionner. Adresse dupliquée refusée sans laisser de compte orphelin ;
inscription échouée **entièrement annulée** (transaction) ; casse normalisée.

### Non-énumération

`login` répond **identiquement** pour une adresse inconnue et pour un mauvais
mot de passe (et l'implémentation fait une vérification factice sur adresse
inconnue pour égaliser le temps de réponse). La demande de réinitialisation
répond identiquement que le compte existe ou non — seul le compte réel reçoit un
jeton. Aucun secret n'apparaît dans une réponse.

### Isolation inter-comptes (§17)

Bob ne peut ni lire ni modifier le profil d'Alice, et **un profil étranger est
indiscernable d'un profil inexistant** — réponse et corps identiques, sinon
l'API devient un oracle d'énumération interrogeable identifiant par identifiant.
La liste ne montre que les profils du compte. Deux comptes qui déclarent
exactement la même chose reçoivent **deux profils distincts** : aucune
déduplication par contenu, sinon les feeds se mélangeraient. Un appelant non
authentifié obtient `401`. Le signal d'Alice n'apparaît jamais dans le feed de
Bob ; le même marché matérialisé pour deux clients donne deux `signal_key`
distincts et une seule `opportunity_key` — la réalité est partagée, le signal
non.

## 13. Fichiers

**Nouveaux** — `src/signals/accounts/` (`__init__`, `schema`, `passwords`,
`tokens`, `icp_input`, `service`, `ownership`), `src/signals/api/`
(`__init__`, `config`, `errors`, `dependencies`, `app`, `routes_auth`,
`routes_icp`), la migration `0002_account_auth_target_icp_...py`, et les quatre
fichiers de tests. La liste exacte du commit envisagé figure au §16.

**Modifiés** — `pyproject.toml` (dépendances + filtre d'avertissement),
`uv.lock`, `src/signals/persistence/migrations/env.py` (+2 lignes),
`tests/test_persistence_schema.py` (l'assertion « le `METADATA` contient
exactement ces tables » devient une inclusion, puisque SPEC-011 en ajoute ;
un nouveau test vérifie en compensation qu'**aucune table SPEC-010 n'a été
altérée** par une SPEC ultérieure).

**Dépendances ajoutées** : `fastapi>=0.115`, `argon2-cffi>=23.1`,
`pydantic[email]>=2.9` (remplace `pydantic>=2.9` — `email-validator` traite les
cas particuliers d'adresse qu'une expression régulière maison raterait) ; extra
`server = ["uvicorn[standard]>=0.30"]`.

Un filtre `filterwarnings` a été ajouté pour taire l'avertissement de dépréciation
`httpx`/`starlette.testclient` : il concerne la dépendance, pas Kivou, et rien
n'est corrigible ici tant que FastAPI n'a pas migré.

## 14. Non-régression (§26)

`git status --porcelain` sur `src/signals/{understanding,needs,matching,documents,connectors,recency,france,domain}`
ne retourne **rien** : aucun moteur, aucun connecteur, aucune politique de
récence n'a été touché. Dans `src/signals/persistence/`, seul `migrations/env.py`
change (deux lignes d'import), plus la nouvelle migration. Le closeout n'a
touché aucun fichier hors de `src/signals/accounts/` et des tests.

Versions en vigueur, inchangées : `contract-understanding-v0.3`,
`need-graph-v0.2`, `need-rules-v0.5`, `icp-match-v0.2`, `signal-score-v0.2`,
`award-recency-v0.3`, `bkp-trade-v0.1`, `object-text-v0.1`,
`boamp-adapter-v0.1`, `decp-adapter-v0.2`, `france-link-v0.3`.

## 15. Closeout — liaison client, durcissement de l'authentification

### 15.1 Porte d'entrée SPEC-010 (§1)

```
$ git log -4 --oneline
30d431c feat(saas): add signal persistence foundation
05ecfd7 feat(signals): add multi-clock recency and France ingestion
1cd8628 research(recency): audit award timing and purchase-channel observability
b881dad feat(wedge): harden construction inputs matching
```

Le commit approuvé `feat(saas): add signal persistence foundation` existe et
porte le SHA **`30d431c5eb075ebb4f69d998a2a742eea4b69ef1`**, daté du
**2026-08-18 13:27:15 +0200**. Il est `HEAD`, donc **antérieur à l'intégralité du
travail SPEC-011** — dont aucun fichier n'est committé. SPEC-010 n'est ni caché,
ni replié dans SPEC-011.

### 15.2 Sémantique de `materialized_signal.target_icp_id` (§2, §3)

**Règle faisant autorité, écrite dans `src/signals/accounts/ownership.py`** :

> Un signal matérialisé est **lié à un client** si et seulement si son
> `target_icp_id` désigne une ligne réelle de `target_icp`.
> `target_icp.account_id` est la **seule** source de propriété.
> Sans ligne correspondante, le signal est **NON LIÉ / RECHERCHE / PRÉ-SaaS** :
> il n'appartient à aucun compte.

Les signaux produits par SPEC-010 référencent des identifiants d'ICP de
recherche (`icp-construction-inputs-ch-eu-v0`), créés avant qu'un compte
existe. Ils survivent à la migration — c'est voulu — et restent **non liés**.
Aucun faux compte hérité n'est créé, aucun identifiant de recherche n'est
rattaché à un compte réel, et la ressemblance d'une chaîne d'identifiant ne
lie rien.

La propriété n'est **jamais** déduite du contenu du signal, du contenu de l'ICP,
de ce que le compte a saisi, ni d'une similarité de ciblage.

Le résolveur, quatre fonctions :

| Fonction | Rend |
|---|---|
| `customer_binding_for_signal(connection, *, signal_key)` | `CustomerBinding(signal_key, target_icp_id, account_id \| None)`, ou `None` si le signal n'existe pas |
| `account_for_materialized_signal(connection, *, signal_key)` | `str \| None` — `None` pour un signal inconnu **comme** pour un signal non lié |
| `signal_is_owned_by(connection, *, signal_key, account_id)` | `bool` ; `account_id` est dans le `WHERE`, pas dans une vérification postérieure |
| `customer_signal_keys(connection, *, account_id)` | les clés du compte, **en partant du compte** |

`customer_binding_for_signal` fait une jointure **externe** : un signal non lié
est un fait à énoncer, pas une ligne à cacher. `customer_signal_keys` fait la
jointure **interne** depuis `target_icp` — un signal non lié ne peut pas y
entrer. Elle ne rend que des clés : le contenu, l'ordre et les filtres du feed
appartiennent à SPEC-012.

**§3 — pas de reconstruction de clé étrangère dans ce closeout.** La FK physique
`materialized_signal.target_icp_id → target_icp` reste absente, et la frontière
de référence molle est désormais explicite dans le module et dans sa docstring,
plutôt que seulement dans un rapport.

Tests — `tests/test_accounts_signal_binding.py`, 11 tests :

| Cas | Vérifié |
|---|---|
| **A** | un signal SPEC-010 matérialisé **avant** les comptes survit à la migration, est non lié, ne résout vers aucun compte ; **aucun** compte ne peut le revendiquer ; créer un ICP dont le libellé ressemble au profil de recherche ne lie toujours rien |
| **B** | un signal lié résout vers **exactement** le compte propriétaire du TargetICP ; une clé de signal inconnue ne résout vers rien |
| **C** | le compte B ne peut ni revendiquer ni lire la propriété du signal du compte A ; la même question posée par deux comptes donne la même réponse — la propriété ne vient pas du demandeur |
| **D** | deux comptes au ciblage **identique** gardent deux `target_icp_id`, deux `signal_key` et deux propriétés distinctes, pour une seule `opportunity_key` — la réalité est partagée, le signal non |

Un test supplémentaire fixe la forme imposée à SPEC-012 : avec deux signaux en
base dont un non lié, `customer_signal_keys` n'en rend qu'un. **Un feed qui
partirait de `materialized_signal` puis filtrerait après coup laisserait passer
les lignes dont personne ne peut prouver le propriétaire.**

### 15.3 Remise à niveau de l'empreinte Argon2 à la connexion (§4)

Une connexion réussie est le **seul** instant où le mot de passe en clair est
disponible : c'est donc le seul moment où l'empreinte peut être remise aux
paramètres courants. `log_in` le fait dans la **même transaction** que la
connexion :

```python
values = {"last_login_at": now, "updated_at": now}
if needs_rehash(password_hash):
    values["password_hash"] = hash_password(password)
```

L'écriture arrive **après** les trois refus (utilisateur inconnu, mot de passe
faux, compte désactivé), donc aucun de ces cas ne peut réécrire quoi que ce
soit. Une empreinte illisible échoue à `verify_password` et sort par le même
chemin.

Six tests, avec un jeu de paramètres Argon2id volontairement affaibli
(`time_cost=1, memory_cost=8, parallelism=1`) — déterministe, et indépendant
d'une future évolution des défauts de la bibliothèque :

- ancienne empreinte valide → connexion réussie → **empreinte remplacée**, la
  nouvelle est aux paramètres courants et vérifie toujours le mot de passe ;
- la session est créée normalement pendant la mise à niveau (une session vivante,
  `/me` répond `200`) ;
- **une empreinte courante n'est pas réécrite à chaque connexion** — réécrire
  sans raison ferait payer un hachage supplémentaire à chaque fois ;
- un mot de passe faux ne réécrit rien ;
- une empreinte corrompue n'est **jamais** réécrite : c'est un incident, pas une
  occasion de la remplacer ;
- une adresse inconnue n'écrit rien du tout et ne crée aucun utilisateur.

### 15.4 L'état d'onboarding redescend (§5)

`onboarding_status()` est **calculé** depuis l'ensemble réel des profils actifs,
et `_refresh_onboarding()` réécrit la colonne stockée à chaque création ou
modification de profil. `/me` lit la colonne stockée : c'est donc elle qui ne
doit pas dériver, et les tests l'interrogent directement en base.

- **CAS A** — un compte avec un seul profil actif est `ready_for_signals` ; un
  `PATCH` qui vide l'essentiel rend le profil `draft`, le compte redescend à
  `icp_incomplete`, en réponse API **et** en base.
- **CAS B** — avec deux profils dont un seul se dégrade, le compte **reste**
  `ready_for_signals`, et la liste montre bien `draft` d'un côté, `active` de
  l'autre.
- La remontée fonctionne aussi : réparer le profil rend `ready_for_signals`.
- Renommer un profil ne déplace jamais l'état.
- Cinq configurations paramétrées (aucun profil, un incomplet, un complet, un de
  chaque, deux incomplets) vérifient que **stocké, calculé et rendu par `/me`
  coïncident** dans chacune.

### 15.5 Filtre d'avertissement (§6)

Filtre exact, unique, tel qu'il figure dans `pyproject.toml` :

```toml
filterwarnings = [
    "ignore:Using `httpx` with `starlette.testclient` is deprecated",
]
```

C'est un filtre **par message**, sans joker et sans catégorie : il ne peut taire
que cet avertissement précis, émis par `starlette`. Il n'y a **aucun**
`ignore::DeprecationWarning` ni aucun autre filtre capable de masquer une
dépréciation de Kivou.

### 15.6 Limitation de débit — contrainte de production, non implémentée (§7)

**Non implémentée dans cette SPEC, et volontairement.**

Avant toute exposition sur l'Internet public, une limitation de débit et une
protection contre l'abus sont **obligatoires** au minimum sur :

```
POST /auth/signup
POST /auth/login
POST /auth/password-reset/request
POST /auth/password-reset/confirm
```

Sans elle, le coût d'Argon2 devient une arme contre le serveur lui-même, et la
réponse indistincte de `login` cesse de protéger dès qu'un attaquant peut
essayer sans limite.

L'implémentation peut vivre dans l'application ou dans un reverse-proxy de
confiance ; elle relève du durcissement de déploiement.

- **Ce n'est pas un bloquant** pour committer le socle MVP hors-ligne.
- **C'en est un** pour l'exposition publique en production.

### 15.7 Ce qui n'a pas changé (§8)

Inchangés : architecture FastAPI, sessions opaques côté serveur, politique de
cookie, CSRF par origine stricte, conception du jeton de réinitialisation,
contrat d'entrée client TargetICP, traduction déterministe de l'ICP, migration
`0001`, identité d'opportunité, récence courante/matérialisée, logique moteur,
BOAMP/DECP/SIMAP/TED, tarification, feed, facturation.

Vérifié par `git status --porcelain` : rien dans
`src/signals/{understanding,needs,matching,documents,connectors,recency,france,domain}`,
ni dans `persistence/{schema,opportunity,materialization,repository,identity,database}.py`,
ni dans `migrations/versions/0001_initial.py`.

Le seul fichier touché par le closeout hors des ajouts est
`src/signals/accounts/service.py` (§4, la remise à niveau de l'empreinte).

## 16. Portes de qualité

| Porte | Résultat |
|---|---|
| `uv run pytest -q` | **2267 passed**, 0 échec, **0 ignoré** |
| `uv run ruff check .` | **All checks passed!** |
| `git diff --check` | propre |

Répartition des tests SPEC-011 (**96**) :

| Fichier | Tests |
|---|---|
| `tests/test_accounts_security.py` | 34 |
| `tests/test_accounts_target_icp.py` | 29 |
| `tests/test_accounts_migration_and_ownership.py` | 22 |
| `tests/test_accounts_signal_binding.py` | 11 |

Base SPEC-010 : 2170 tests.

### `git status --porcelain`

```
 M pyproject.toml
 M src/signals/persistence/migrations/env.py
 M tests/test_persistence_schema.py
 M uv.lock
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx:Zone.Identifier
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx:Zone.Identifier
?? docs/reports/2026-08-17-spec006-postmortem.md
?? docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md
?? docs/reports/2026-08-18-spec011-account-auth-target-icp.md
?? src/signals/accounts/
?? src/signals/api/
?? src/signals/persistence/migrations/versions/0002_account_auth_target_icp_account_auth_and_target_icp.py
?? src/signals/research/spec009c.py
?? src/signals/research/spec009c_run.py
?? tests/fixtures/documents/heldout3_gold.json:Zone.Identifier
?? tests/fixtures/documents/heldout3_gold.sha256.txt:Zone.Identifier
?? tests/fixtures/signal100/spec009c_blind.json
?? tests/test_accounts_migration_and_ownership.py
?? tests/test_accounts_security.py
?? tests/test_accounts_signal_binding.py
?? tests/test_accounts_target_icp.py
?? tests/test_spec009c_bench.py
```

### `git diff --stat` (fichiers suivis)

```
 pyproject.toml                            |  18 +-
 src/signals/persistence/migrations/env.py |   2 +
 tests/test_persistence_schema.py          |  27 ++-
 uv.lock                                   | 289 +++++++++++++++++++++++++++++-
 4 files changed, 330 insertions(+), 6 deletions(-)
```

### Liste exacte des fichiers du commit SPEC-011 envisagé

**Modifiés (4)**

```
pyproject.toml
uv.lock
src/signals/persistence/migrations/env.py
tests/test_persistence_schema.py
```

**Nouveaux (18)**

```
src/signals/accounts/__init__.py
src/signals/accounts/icp_input.py
src/signals/accounts/ownership.py
src/signals/accounts/passwords.py
src/signals/accounts/schema.py
src/signals/accounts/service.py
src/signals/accounts/tokens.py
src/signals/api/__init__.py
src/signals/api/app.py
src/signals/api/config.py
src/signals/api/dependencies.py
src/signals/api/errors.py
src/signals/api/routes_auth.py
src/signals/api/routes_icp.py
src/signals/persistence/migrations/versions/0002_account_auth_target_icp_account_auth_and_target_icp.py
tests/test_accounts_migration_and_ownership.py
tests/test_accounts_security.py
tests/test_accounts_signal_binding.py
tests/test_accounts_target_icp.py
docs/reports/2026-08-18-spec011-account-auth-target-icp.md
```

**Explicitement exclus** — hors périmètre §25, ni modifiés ni indexés :
`Plan_directeur_*.docx`, `Roadmap_execution_*.docx`, tous les
`*:Zone.Identifier`, `docs/reports/2026-08-17-spec006-postmortem.md`,
`docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md`,
`src/signals/research/spec009c.py`, `src/signals/research/spec009c_run.py`,
`tests/fixtures/signal100/spec009c_blind.json`, `tests/test_spec009c_bench.py`.

## 17. Ce que SPEC-011 impose à SPEC-012

1. **Le feed part du compte, pas du signal.** Il doit passer par
   `customer_signal_keys` / `signal_is_owned_by`, jamais par
   `materialized_signal` filtré après coup — sans quoi les signaux non liés
   d'avant les comptes deviendraient visibles.
2. **Un signal sans ligne `target_icp` n'appartient à personne.** Il ne devient
   client ni par ressemblance d'identifiant, ni par similarité de ciblage.
3. **`account_id` ne vient jamais du client.** Aucun schéma de requête ne
   l'accepte, et aucun ne doit l'accepter.
4. **`now` reste explicite.** `request_now()` est le seul point d'entrée du
   temps. La récence *courante* se recalcule à `as_of` ; celle qui est stockée
   reste un instantané (SPEC-010 §1).
5. **`ready_for_signals` est technique**, réversible, et recalculé depuis
   l'ensemble réel des profils actifs. La facturation apportera son propre état.
6. **Le vocabulaire moteur ne franchit pas la frontière API.**
7. **`target_icp.customer_input` est la source ; le profil moteur est dérivé** —
   donc un changement de règle de traduction s'applique sans migration de
   données, mais change les signaux (politique de révision SPEC-010 §4).
8. **Bloquant de production, pas de commit** : limitation de débit sur les
   quatre points d'entrée d'authentification (§15.6).
9. **Reste à faire, hors périmètre** : la FK
   `materialized_signal.target_icp_id → target_icp`, qui exige une
   reconstruction de table et donc une migration dédiée — impossible tant que
   des signaux pré-comptes subsistent.
10. **Interdits toujours en vigueur** : facturation, feed, frontend, alertes,
    recherche automatique d'entreprise, et toute acquisition (Apollo, Instantly,
    campagnes, contact prospect, e-mail, boîte aux lettres, outbound).

---

## Verdict

**SPEC-011 READY TO COMMIT**

Le chemin `INSCRIPTION → SESSION → COMPTE → TARGET ICP → PRÊT POUR LE FEED`
fonctionne de bout en bout, sur une base migrée depuis SPEC-010 (`30d431c`) sans
perte de signal. La propriété client est résolue par une seule règle explicite,
et les signaux d'avant les comptes restent sans propriétaire.

Non committé, dans l'attente de l'autorisation.
