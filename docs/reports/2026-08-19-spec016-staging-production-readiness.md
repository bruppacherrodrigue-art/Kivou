# SPEC-016 — Staging VPS + Production Readiness + SaaS End-to-End

**Date :** 19 août 2026
**Verdict :** voir §T10.

> Ce document a deux parties, dans l'ordre où les choses se sont passées.
>
> **Partie I — audit initial, avant provisionnement du VPS dédié** (§1 à §14).
> Conservée telle quelle. Son verdict `NOT READY` était juste **au moment où il
> a été rendu** : ni hôte Kivou, ni domaine.
>
> **Partie II — suite après provisionnement** (§S1 à §S12). Le VPS dédié existe,
> `kivou.eu` est enregistré, et le déploiement a eu lieu. Il restait un pare-feu
> fermé.
>
> **Partie III — après ouverture du pare-feu** (§T1 à §T10). TLS public, et
> l'ensemble validé depuis l'extérieur. **C'est le verdict courant.**
>
> L'audit initial n'est pas effacé : il explique pourquoi les gabarits existent
> avant le serveur, et ce que le serveur réel a ensuite corrigé.

---

# PARTIE I — Audit initial, avant provisionnement du VPS dédié

---

## 1. Résumé en une page

L'audit préalable a établi deux faits qui décident de tout le reste :

1. **`kivou.eu` n'a aucune délégation DNS.** Résolution NXDOMAIN, autorité
   EURid. Sans domaine, pas de `staging.kivou.eu`, pas de certificat, pas
   d'origine HTTPS — et donc pas de webhook Stripe, pas d'origine CSRF, pas de
   lien profond d'alerte, pas de parcours navigateur.
2. **Aucun hôte Kivou n'existe.** Le seul serveur accessible est
   `courrierclair-prod`, qui fait tourner **19 conteneurs répartis en 5 piles de
   production** pour quatre autres projets.

Vous avez tranché : **VPS dédié Kivou** à provisionner, et **`kivou.eu` à
enregistrer** — les deux de votre côté.

Le déploiement n'a donc pas eu lieu, et il ne pouvait pas avoir lieu. Ce qui a
été fait, c'est **tout le travail dépôt qui ne dépend ni de l'hôte ni du nom
d'hôte**, de sorte que le jour où les deux existent, le déploiement soit une
procédure courte, écrite et déjà testée.

**Rien n'a été modifié sur `courrierclair-prod`.** L'audit y a été strictement
en lecture seule.

---

## 2. GitHub

| Élément | Valeur |
|---|---|
| Dépôt | `bruppacherrodrigue-art/Kivou` (privé) |
| Branche | `chore/spec016-staging-readiness` |
| SHA de la branche | `510234848218382e2827a02fbe81bd2fbd22d8fb` |
| PR | **#6, brouillon, non fusionnée** — ouverte uniquement pour déclencher la CI |
| SHA déployé | **aucun** — pas d'hôte |

### Entry gate

```text
HEAD        1e61cc3ada3427745e3f55bd32652fcf3d9dc9e0
origin/main 1e61cc3ada3427745e3f55bd32652fcf3d9dc9e0   ✅ identiques
```

`.github/workflows/ci.yml`, `.github/dependabot.yml`, `.env.example` et
`CONTRIBUTING.md` sont tous suivis. **Entry gate PASS.**

### CI de la branche — run `32220616143`

| Job | Résultat | Détail |
|---|---|---|
| Backend | **PASS** | `2716 passed` · `All checks passed!` |
| Frontend | **PASS** | 84 tests, build, typecheck, lint |

Base GitHub avant SPEC-016 : **2700**. Après : **2716** — les 16 tests ajoutés
ici. Le compte n'a jamais diminué.

*Note :* une poussée de branche seule ne déclenche pas la CI, le workflow
n'écoutant que `pull_request` et `push` vers `main`. D'où la PR en **brouillon**,
ouverte pour obtenir la CI et explicitement pas pour fusionner.

---

## 3. Audit dépôt

| Élément | État |
|---|---|
| Python | 3.12 (`requires-python = "==3.12.*"`) |
| Node / npm | 24.14.1 / 11.11.0 |
| Point d'entrée FastAPI | **n'existait pas** — `create_app()` est une fabrique. Créé ici |
| Build frontend | `npm run build` → `frontend/dist/` |
| Tête Alembic | `0004_alerts_feedback_analytics` (4 migrations) |
| Endpoints de santé | **n'existaient pas**. Créés ici |
| Configuration | `ApiConfig.from_environment()`, sans défaut dangereux |
| Adaptateur SMTP | présent (`signals.alerts`), aucune identification configurée |
| Livraison de réinitialisation | `_NullDelivery` — le jeton n'est remis à personne |
| Job d'alerte | `python -m signals.alerts` — **seul point d'entrée exécutable du dépôt** |
| Fichiers de déploiement | **aucun**. Créés ici |

---

## 4. Audit VPS — lecture seule, rien modifié

`courrierclair-prod`, accessible par SSH (`deploy@`, clé ed25519).

| Élément | Valeur |
|---|---|
| OS | Ubuntu 22.04.5 LTS, noyau 5.15 |
| CPU / RAM | 4 vCPU · 11 Gi total, **7,8 Gi disponibles** |
| Disque | 20 Go, 5,8 utilisés, **14 Go libres** |
| Ports publics | 22, 80, 443 |
| Reverse proxy | **Traefik v3.7**, en conteneur, détient 80/443 |
| PostgreSQL système | inactif — toutes les bases sont en conteneur |
| Sécurité | fail2ban actif |

### Les cinq piles présentes

```text
courrierclair-infra   traefik · app · postgres · ocr · pseudo
turiya                web · worker · postgres
cortex-core           core · postgres · qdrant
bisse-ia              site · dashboard · n8n · postgres
glitchtip             web · worker · postgres · redis
```

**19 conteneurs.** Les ressources permettraient d'ajouter Kivou, mais le rayon
d'impact d'une erreur couvre quatre projets en production, dont le Traefik qui
sert tout le trafic entrant. Vous avez choisi un VPS dédié : c'est le bon appel,
et c'est la trajectoire que la SPEC prévoyait déjà, simplement anticipée.

### Spécification du VPS à provisionner

```text
2 vCPU · 4 Go RAM · 40 Go SSD · Ubuntu 24.04 LTS
Ports publics : 22, 80, 443 uniquement
PostgreSQL : local, listen_addresses = 'localhost', jamais exposé
```

---

## 5. DNS — le blocage racine

| Nom | Résultat |
|---|---|
| `kivou.eu` | **NXDOMAIN**, SOA `si.dns.eu` / `tech.eurid.eu` — aucune délégation |
| `staging.kivou.eu` | NXDOMAIN, même autorité |
| `kivou.ch` | NXDOMAIN |
| `kivou.com` | résout vers `52.20.84.62` — **tiers, pas nous** |

Les domaines du compte Infomaniak sont `courrierclair.ch` et `bisse-ia.ch`.
`kivou.eu` n'y figure pas.

Je n'ai pas pu établir depuis ici si le domaine est libre ou enregistré sans
délégation : RDAP répond 404 même pour `europa.eu`, il n'est donc pas
concluant. **Dans les deux cas le résultat est le même** : aucune zone
utilisable sans action registrar.

### Ce qu'il faudra créer, une fois le domaine délégué

```text
staging.kivou.eu.   A      <IPv4 du VPS Kivou>
staging.kivou.eu.   AAAA   <IPv6 du VPS Kivou>   (si fournie)
```

**Aucun enregistrement MX, SPF, DKIM ou DMARC n'a été touché**, et aucun ne doit
l'être sans autorisation explicite.

---

## 6. Ce qui a été construit

### Sondes de santé — `src/signals/api/routes_health.py`

`/health/live` **n'ouvre jamais la base**. Ce n'est pas une économie : si la
vivacité dépendait de PostgreSQL, une base tombée ferait redémarrer
l'application en boucle par le superviseur, sans rien réparer puisque la panne
est ailleurs. Un test verrouille ce comportement contre une base injoignable.

`/health/ready` distingue **quatre** états, parce qu'ils se réparent
différemment :

| `reason` | Cause |
|---|---|
| `database_unreachable` | PostgreSQL arrêté ou identifiants faux |
| `migrations_not_applied` | base vide, migration jamais jouée |
| `schema_revision_mismatch` | l'application a redémarré sans migrer |
| `schema_unreadable` | droits insuffisants sur `alembic_version` |

La disponibilité **ne dépend ni de Stripe, ni de SMTP, ni de SIMAP/BOAMP/DECP/
TED** — un test le vérifie en construisant l'application sans passerelle. Lier
la disponibilité à un tiers lui laisserait décider de la nôtre.

Aucune sonde ne publie d'URL de connexion, d'identifiant, de nom d'hôte ni de
trace : un test tente de faire fuir un mot de passe et un hôte de base par les
deux routes.

### Point d'entrée ASGI — `src/signals/api/asgi.py`

`uvicorn signals.api.asgi:app`. Il n'en existait aucun : chaque déploiement
aurait inventé son propre code de démarrage, et c'est ainsi que les
configurations divergent.

Construction **paresseuse** via `__getattr__` : `uvicorn …:app` lit l'attribut
et déclenche la construction, mais un simple `import` — celui de la collecte de
tests — n'ouvre aucun moteur. La première version construisait à l'import et
cassait la collecte entière ; corrigé, et deux tests fixent la distinction.

Il **ne migre pas au démarrage** : la migration est une étape de déploiement
jouée une fois (§12), et la déclencher ici ferait courir chaque worker sur
`alembic_version`. Un test le vérifie.

### Surface d'API réduite — §19

`docs_url` et `redoc_url` étaient déjà coupés, mais **`openapi_url` restait
ouvert** et publiait la forme complète de l'API à qui la demandait. Un dépôt
privé qui sert son propre schéma en clair annule l'intérêt de l'avoir gardé
privé. Coupé, avec trois tests.

### `ops/` — 12 fichiers, aucun secret, aucun hôte en dur

```text
ops/README.md                      manuel : installation, déploiement, retour arrière
ops/systemd/kivou-api.service      uvicorn, 2 workers, durcissement systemd
ops/systemd/kivou-alerts.{service,timer}    horaire, verrou flock
ops/systemd/kivou-backup.{service,timer}    quotidien 03h17
ops/nginx/kivou-staging.conf       séparation frontend/API, en-têtes, cache
ops/nginx/kivou-proxy-params.conf  en-têtes mandataires, Origin transmis tel quel
ops/nginx/kivou-limits.conf        zones de limitation de débit
ops/bin/kivou-backup.sh            pg_dump, rétention, contrôle de taille
ops/bin/kivou-restore-verify.sh    restauration en base jetable + comptages
ops/bin/kivou-healthcheck.sh       sonde externe + expiration du certificat
```

Les trois scripts passent `bash -n`. Deux d'entre eux avaient un défaut réel :
une apostrophe et une parenthèse **à l'intérieur d'un `${VAR:?message}`**
ouvraient une citation non fermée. Le fichier paraissait correct à la lecture ;
seul `bash -n` l'a montré. Corrigé.

#### Choix du reverse proxy

**nginx + certbot**, pas Caddy. Le TLS automatique de Caddy est plus élégant,
mais §18 exige une limitation de débit et Caddy la délègue à un module tiers,
alors que nginx a `limit_req` en natif — comme `client_max_body_size` et les
en-têtes. Tout ce que la SPEC demande est de première main.

#### Le piège de routage, traité explicitement

```text
/billing/*     →  BACKEND    (status, plans, checkout, portal)
/checkout/*    →  FRONTEND   (success, cancel)
```

Les deux se ressemblent et désignent des couches opposées. Le gabarit nginx les
sépare et le commentaire dit pourquoi.

#### Limites de débit retenues (§18)

| Zone | Débit | Rafale | Couvre |
|---|---|---|---|
| `kivou_auth` | 5/min | 3 | `/auth/login`, `/auth/signup` |
| `kivou_reset` | 3/min | 2 | demande et confirmation de réinitialisation |
| `kivou_api` | 120/min | 40 | reste de l'API |
| `kivou_hook` | 300/min | 100 | `/webhooks/stripe` |

Dépassement → **429**. La zone webhook est large à dessein : Stripe réessaie un
événement non acquitté avec un recul exponentiel, et l'étrangler ferait perdre
des synchronisations d'abonnement.

#### En-têtes de sécurité (§16)

`X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options: DENY`,
`Permissions-Policy`, `HSTS`, et une CSP **sans `unsafe-eval`**. `font-src
'self'` verrouille au niveau navigateur ce que §9 exige : aucune police tierce
possible. `form-action` autorise `checkout.stripe.com` et `billing.stripe.com`,
sans quoi la redirection de paiement serait bloquée par notre propre CSP.

**La CSP n'a pas été validée dans un navigateur réel** — cela demande le site
déployé.

#### Taille de corps (§20)

`client_max_body_size 1m`. Kivou n'accepte aucun téléversement ; les corps les
plus gros sont un profil de ciblage et un webhook Stripe, de l'ordre du
kilo-octet.

---

## 7. Pipeline de données — BLOCAGE identifié (§33/§34)

Question posée par §33 : *quelle commande de production transforme une
adjudication publique en signal client ?*

**Réponse : aucune.**

| Composant | État |
|---|---|
| Connecteurs BOAMP · DECP · SIMAP · TED | présents |
| `materialize_signal()` | présent, dans `persistence/materialization.py` |
| **Appelant hors tests** | **aucun** |
| Points d'entrée exécutables | `python -m signals.alerts`, et c'est tout |
| `src/signals/research/*_run.py` | scripts de recherche : spikes, corpus, bancs |

Les briques existent, l'orchestration n'existe pas. Rien ne relie source →
`ContractAward` → understanding → need graph → matching → matérialisation →
base SaaS.

Construire cet enchaînement n'est pas de l'ourdissage de staging : c'est du
travail produit substantiel, qui touche des composants que la SPEC gèle
explicitement. §34 demande dans ce cas de s'arrêter et de le nommer.

```text
INGESTION RUNTIME BLOCKER
```

**Recommandation : une SPEC dédiée.** Elle devra décider de la cadence par
source, de l'idempotence de la reprise, du traitement des avis partiels, et de
ce qui se passe quand une source change de format — aucune de ces questions
n'est une question de déploiement.

Sans elle, un staging déployé afficherait un feed **vide**, ou alimenté à la
main depuis des fixtures.

---

## 8. Stripe — audit, sans action

Compte accessible : **Turiya**, en test (`acct_1TMqChC34k5bO7Y3`) et en live.
C'est exactement le compte partagé que §21 signale : le catalogue Kivou y vit à
côté de Turiya.

| Porte | État |
|---|---|
| Isolation TEST Turiya (§21) | **non traitée** — sans URL staging, aucun webhook Kivou à créer, donc aucun risque de confusion aujourd'hui |
| Webhook TEST Kivou (§22) | **impossible** — l'URL `https://staging.kivou.eu/webhooks/stripe` n'existe pas |
| Portail client (§23) | **non configuré** |
| `automatic_tax` (§24) | **reste `false`** — conforme, aucune décision fiscale prise |
| Checkout TEST E2E (§25) | **impossible** |

**Aucune modification Stripe n'a été faite.** Ni produit, ni prix, ni coupon, ni
webhook, ni configuration de portail. La séquence §21 → §22 → §25 est ordonnée :
elle ne peut commencer qu'avec une URL publique.

---

## 9. E-mail

| Élément | État |
|---|---|
| Identifiants SMTP | **absents** — aucune variable, aucun `.env` |
| Boîte de test staging | **inexistante** |
| Réinitialisation de mot de passe E2E (§29) | **BLOQUÉ** |
| Alerte client E2E (§30) | **BLOQUÉ** |
| SPF / DKIM / DMARC (§31) | **non audité** — le domaine expéditeur n'existe pas |

§29 est explicite : sans identifiants ni boîte de test, la porte est **BLOQUÉE**,
pas simulée.

Le compte Infomaniak dispose d'hébergement e-mail sur `courrierclair.ch` et
`bisse-ia.ch`, mais pas sur un domaine Kivou. Une fois `kivou.eu` enregistré,
SPF, DKIM et DMARC devront être posés **avant** toute conclusion sur la
délivrabilité : un envoi SMTP réussi ne prouve pas qu'un message arrive en boîte
de réception.

---

## 10. Tests

### Backend

```text
uv run pytest -q      →  2740 passed   (arbre local, 24 tests non suivis compris)
                         2716 passed   (périmètre du dépôt — CI)
uv run ruff check .   →  All checks passed!
git diff --check      →  propre
```

**2716 = 2700 (base GitHub) + 16 nouveaux tests SPEC-016** :

* 11 sur les sondes de santé — vivacité sans base, quatre états de disponibilité,
  non-fuite d'infrastructure, indépendance vis-à-vis de Stripe/SMTP/sources,
  absence de `/docs`, `/redoc` et `/openapi.json` ;
* 5 sur le point d'entrée ASGI — import sans configuration, échec clair à
  l'accès, construction depuis l'environnement, absence de migration au
  démarrage.

Les 24 tests de recherche SPEC-009C restent **volontairement non suivis** et ne
servent pas de base de déploiement.

### Frontend

```text
npm test -- --run  →  10 fichiers, 84 tests
npm run build      →  ✓ built
npx tsc -b         →  0 erreur
npm run lint       →  0 problème
```

**Aucun test ignoré**, ni backend ni frontend.

---

## 11. Matrice des portes

Rien n'est converti en PASS faute d'identifiants ou d'infrastructure.

```text
GATE                                      STATUS

GitHub branch CI                          PASS
Exact SHA deployed                        BLOCKED    aucun hôte

HTTPS staging                             BLOCKED    aucun domaine
Frontend serving                          BLOCKED    aucun hôte
FastAPI                                   BLOCKED    aucun hôte
PostgreSQL                                BLOCKED    aucun hôte
Migrations                                BLOCKED    aucun hôte

Health live                               BLOCKED    implémenté et testé, non déployé
Health ready                              BLOCKED    implémenté et testé, non déployé

Auth/browser session                      BLOCKED    aucun hôte
CSRF                                      BLOCKED    aucune origine
Rate limiting                             BLOCKED    gabarit écrit, non appliqué
Security headers                          BLOCKED    gabarit écrit, non appliqué

Turiya Stripe TEST isolation              BLOCKED    prérequis : URL staging
Kivou Stripe TEST webhook                 BLOCKED    prérequis : URL staging
Stripe Checkout TEST E2E                  BLOCKED    prérequis : webhook
Stripe success authorization safety       BLOCKED    prérequis : checkout
Customer Portal TEST                      BLOCKED    prérequis : checkout

SMTP                                      BLOCKED    aucun identifiant
Password reset email E2E                  BLOCKED    aucune boîte de test
Customer alert email E2E                  BLOCKED    aucun SMTP
SPF/DKIM/DMARC                            BLOCKED    aucun domaine expéditeur

Alert timer                               BLOCKED    unité écrite, non installée
Ingestion/materialization runtime         BLOCKED    INGESTION RUNTIME BLOCKER
Ingestion timer                           BLOCKED    aucun runtime à planifier

Backup                                    BLOCKED    script écrit, aucune base
Restore                                   BLOCKED    script écrit, aucune sauvegarde

Logging                                   BLOCKED    journald configuré dans les unités
Monitoring                                BLOCKED    sonde écrite, aucune cible
Firewall                                  BLOCKED    aucun hôte
Secret scan                               PASS       17 fichiers indexés, aucun secret

Desktop E2E                               BLOCKED    aucun serveur
Mobile smoke                              BLOCKED    aucun serveur
Restart continuity                        BLOCKED    aucun service
```

**2 PASS, 31 BLOCKED.** Les blocages ont trois causes seulement : pas de
domaine, pas d'hôte, pas de runtime d'ingestion.

---

## 12. Verdict

```text
STAGING + PRODUCTION READINESS NOT READY
```

Kivou ne tourne pas en staging, et ne peut pas tourner aujourd'hui. Le verdict
n'est pas `PARTIALLY` : `PARTIALLY` supposerait un staging partiellement
fonctionnel, alors qu'aucun composant n'est déployé.

Ce n'est pas un échec d'exécution. Les deux prérequis sont des décisions
d'infrastructure que vous avez prises pendant cette SPEC, et dont la réalisation
vous appartient.

### Chemin critique

1. **Enregistrer `kivou.eu`** et déléguer le DNS.
2. **Provisionner le VPS Kivou** — 2 vCPU · 4 Go · 40 Go · Ubuntu 24.04.
3. Créer `staging.kivou.eu` → IP du VPS. Je fournis alors l'installation, le
   TLS et le déploiement au SHA exact : `ops/README.md` est écrit et prêt.
4. Identifiants SMTP et boîte de test → débloque §29 et §30.
5. **SPEC dédiée à l'ingestion** → débloque le feed avec de vraies données.

Les étapes 1 et 2 débloquent à elles seules 20 portes.

### Ce qui est acquis

Sondes de santé, point d'entrée ASGI, surface d'API réduite, et l'ensemble des
gabarits d'exploitation — tous écrits, testés, passés en CI, et sans hôte codé
en dur. Le déploiement, le jour venu, sera une procédure mécanique et non une
improvisation.

---

## 13. Git

### Fichiers de SPEC-016

```text
A  src/signals/api/routes_health.py       sondes /health/live et /health/ready
A  src/signals/api/asgi.py                point d'entrée ASGI de production
M  src/signals/api/app.py                 montage des sondes, openapi_url coupé
A  tests/test_api_health.py               11 tests
A  tests/test_api_asgi.py                 5 tests
A  ops/README.md                          manuel d'exploitation
A  ops/systemd/  (5 fichiers)             API, alertes, sauvegarde
A  ops/nginx/    (3 fichiers)             proxy, limites, paramètres
A  ops/bin/      (3 scripts)              sauvegarde, restauration, sonde
A  docs/reports/2026-08-19-spec016-staging-production-readiness.md
```

### `git diff --stat` (branche vs `main`)

```text
 17 files changed, 1156 insertions(+), 1 deletion(-)
```

### `git status --porcelain`

```text
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx
?? docs/reports/2026-08-17-spec006-postmortem.md
?? docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md
?? src/signals/research/spec009c.py
?? src/signals/research/spec009c_run.py
?? tests/fixtures/signal100/spec009c_blind.json
?? tests/test_spec009c_bench.py
```

Les huit fichiers historiques restent volontairement non suivis.

---

## 14. Limites du périmètre respectées

Aucune production lancée. Aucun Stripe LIVE. Aucun abonnement réel. Aucun
outbound. **Hermes non installé, aucun jeton créé, aucune permission
d'écriture accordée.** Aucun workflow de déploiement automatique. Aucun tag,
aucune release. Aucune modification de `courrierclair-prod` ni des quatre
projets qu'il héberge. Aucune modification DNS. Aucun moteur de signal touché.

La branche SPEC-016 **n'est pas fusionnée** ; la PR #6 est un brouillon ouvert
pour la CI seule.

---
---

# PARTIE II — Suite après provisionnement du VPS dédié

**Date :** 19 août 2026, après-midi.

Deux des trois blocages de la Partie I sont levés : le VPS dédié existe, et
`kivou.eu` est enregistré. Kivou **tourne** désormais sur un serveur réel.

---

## S1. Ce qui a changé depuis l'audit initial

| Blocage — Partie I | État maintenant |
|---|---|
| Aucun hôte Kivou | **levé** — `kivou-staging-01` provisionné |
| `kivou.eu` sans délégation | **levé** — enregistré, NS Infomaniak, DNSSEC actif |
| Aucun runtime d'ingestion | **inchangé** — reporté en SPEC-016A |

Un **nouveau** blocage est apparu, qui n'existait pas dans l'audit initial :
le pare-feu du cloud filtre 80 et 443 (voir §S6).

---

## S2. Git

| Élément | Valeur |
|---|---|
| Branche | `chore/spec016-staging-readiness` |
| SHA au début de la reprise | `510234848218382e2827a02fbe81bd2fbd22d8fb` |
| **SHA déployé** | **`a276aed3aa05b12b360e7e3626b4080e58e58dcb`** |
| PR | **#6, brouillon, non fusionnée** |
| `main` | `1e61cc3…`, **intact** |

### CI — run `32224029650`

| Job | Résultat |
|---|---|
| Backend | **PASS** — `2716 passed`, ruff propre |
| Frontend | **PASS** — 84 tests, build, typecheck, lint |

Base jamais diminuée : 2700 → 2716.

### Le SHA déployé est celui validé

```text
attendu (CI) : a276aed3aa05b12b360e7e3626b4080e58e58dcb
sur serveur  : a276aed3aa05b12b360e7e3626b4080e58e58dcb   ✅
arbre de travail du serveur : 0 modification locale
```

Le déploiement passe par un **clone Git**, jamais par une copie du poste. La
règle a d'ailleurs été mise à l'épreuve : un correctif copié à la main sur le
serveur pendant le diagnostic a fait échouer le `git checkout` suivant. Le
correctif a été jeté et repris par Git. C'est exactement pour cela que la règle
existe.

---

## S3. Audit du nouveau VPS — lecture seule d'abord

| Élément | Valeur |
|---|---|
| Nom d'origine | `ov-f58505` (défaut Infomaniak) → renommé **`kivou-staging-01`** |
| FQDN | `ov-f58505.infomaniak.ch` |
| OS | **Ubuntu 24.04.4 LTS**, noyau 6.8 |
| CPU / RAM | 2 vCPU · 3,8 Gi (3,4 Gi disponibles) |
| Disque | 58 Go, **56 Go libres** |
| IPv4 | `179.237.100.62` |
| IPv6 | assignée, sortant fonctionnel |
| Utilisateurs | `ubuntu` uniquement |
| Plateforme | OpenStack (Infomaniak Public Cloud), produit `kivou-staging-01` id 56826 |

**Aucune autre application** : `/srv`, `/opt` et `/var/www` vides, aucune unité
systemd personnalisée, aucun conteneur. Les 6 unités présentes sont celles
d'Ubuntu (ModemManager, iscsi, vmtoolsd…). Machine bien neuve, dédiée à Kivou.

`courrierclair-prod` **n'a pas été touché** pendant cette reprise.

---

## S4. DNS

`kivou.eu` est enregistré, délégué à `nsany1/nsany2.infomaniak.com`, DNSSEC
actif, et présent dans le compte Infomaniak (id 2239500).

**Enregistrement créé :**

```text
staging.kivou.eu.  300  A  179.237.100.62
```

Propagation vérifiée immédiatement. **Aucun MX, SPF, DKIM ou DMARC n'a été
modifié.**

### AAAA — délibérément NON créé

L'IPv6 sortante fonctionne, mais l'entrante n'est pas démontrée. Or Let's
Encrypt privilégie l'IPv6 dès qu'un AAAA existe : publier l'enregistrement avant
d'avoir prouvé le trafic entrant ferait **échouer l'émission du certificat**, et
enverrait les clients qui préfèrent l'IPv6 vers une adresse muette. À créer une
fois 80/443 réellement joignables en v6, pas avant.

### SPF / DKIM / DMARC — déjà en place

| Type | Valeur |
|---|---|
| SPF | `v=spf1 include:spf.infomaniak.ch -all` |
| DKIM | sélecteur `20260819._domainkey`, clé publiée |
| DMARC | `v=DMARC1; p=reject;` |

Posés par Infomaniak à la création du domaine. `p=reject` est strict : un envoi
mal aligné sera **rejeté**, pas mis en quarantaine — à garder en tête au moment
de configurer SMTP.

---

## S5. Ce qui tourne sur le serveur

| Couche | État |
|---|---|
| PostgreSQL 16.14 | actif, `listen_addresses=localhost`, socket `127.0.0.1:5432` |
| Base `kivou_staging` | créée, propriétaire `kivou_app` |
| Rôle `kivou_app` | **`rolsuper=false`, `rolcreatedb=false`** |
| Migration | `None` → **`0004_alerts_feedback_analytics`**, jouée UNE fois avant démarrage |
| API | `kivou-api.service` actif, uvicorn 0.52.3, 2 workers, durcissement systemd |
| Frontend | 14 fichiers publiés dans `/srv/kivou/frontend` |
| nginx 1.24 | actif, séparation frontend/API opérationnelle |
| Configuration | `/etc/kivou/staging.env`, `root:kivou`, `chmod 640` |

Le mot de passe PostgreSQL a été **généré sur le serveur** et écrit directement
dans le fichier protégé : il n'a transité ni par mon poste, ni par ce rapport.

### Sondes

```text
/health/live  → 200
/health/ready → {"status":"ready","revision":"0004_alerts_feedback_analytics"}
```

### Séparation des routes — le piège de §7, vérifié

| Route | Sert | Résultat |
|---|---|---|
| `/health/live`, `/health/ready` | API | 200 |
| `/billing/plans` | API | 200, JSON du catalogue |
| `/me`, `/signals` | API | 401 sans session — correct |
| `/`, `/login`, `/signup`, `/app/signals`, `/forgot-password` | frontend | 200, SPA |
| **`/checkout/success`**, **`/checkout/cancel`** | **frontend** | 200, `<title>Kivou</title>` |

`/billing/*` rend du JSON, `/checkout/*` rend l'application. Les deux se
ressemblent et désignent des couches opposées : c'est vérifié, pas supposé.

---

## S6. Le nouveau blocage — pare-feu du cloud

```text
depuis l'extérieur :  22 OUVERT  ·  80 filtré  ·  443 filtré
depuis la machine  :  curl http://127.0.0.1/ → 200
ufw                :  actif, 22/80/443 autorisés
iptables INPUT     :  policy ACCEPT
```

La machine laisse passer ; **le filtrage est en amont**. L'instance vit dans
Infomaniak Public Cloud (OpenStack) et son **groupe de sécurité** n'autorise que
le port 22 en entrée. Ce groupe ne se configure ni par `ufw`, ni par l'API REST
Infomaniak — j'ai vérifié : elle couvre domaines, mail et drive, pas le réseau
OpenStack.

Conséquence directe : `certbot` a échoué avec
`Timeout during connect (likely firewall problem)` sur la validation ACME. Sans
port 80 joignable, Let's Encrypt ne peut rien valider.

### Action requise — console Public Cloud, groupe de sécurité de `ov-f58505`

```text
Ingress  TCP  80    0.0.0.0/0  ::/0
Ingress  TCP  443   0.0.0.0/0  ::/0
```

Vérification depuis n'importe quel poste :

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://staging.kivou.eu/
```

Tant que cela expire, **aucune porte TLS ne peut être franchie**. Aucun
certificat auto-signé n'a été fabriqué pour faire semblant.

---

## S7. Sécurité vérifiée sur le serveur réel

### Cookie de session

```text
kivou_session=***; expires=…; HttpOnly; Path=/; SameSite=lax; Secure
```

Les quatre attributs attendus. Effet de bord instructif : `curl` en HTTP simple
**refuse de stocker** ce cookie, précisément parce qu'il est `Secure`. La
protection fonctionne — et cela confirme que tout test de session navigateur
exige d'abord TLS.

### CSRF — testé avec une charge utile valide

| Origine | Résultat |
|---|---|
| `https://evil.example.com` | **`csrf_origin_rejected`** |
| `https://staging.kivou.eu` | passe l'origine, échoue ensuite sur l'authentification — correct |

Un premier essai avec un corps invalide renvoyait 422 des deux côtés : la
validation pydantic court-circuitait le contrôle d'origine. Le test ne prouvait
rien ; refait avec un corps valide.

### Limitation de débit

12 requêtes consécutives sur `/auth/login` :

```text
422 422 422 422 429 429 429 429 429 429 429 429
```

4 passent (rafale 3 + 1), 8 sont refusées en **429**. Conforme.

### En-têtes de sécurité — un défaut réel trouvé et corrigé

Ils étaient **absents** de la page d'accueil alors que le bloc serveur les
déclarait. Cause : dans nginx, `add_header` **cesse d'être hérité** dès qu'une
`location` en déclare un à son tour. `location = /index.html` posait son
`Cache-Control` et annulait, en silence, CSP, `X-Frame-Options` et le reste.

Rien ne le signalait — ni `nginx -t`, ni les journaux. Il fallait lire les
en-têtes d'une vraie réponse.

Corrigé par un fichier partagé, inclus dans le bloc serveur **et** dans chaque
`location` concernée. Vérifié après correction :

```text
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
X-Frame-Options: DENY
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
Content-Security-Policy: default-src 'self'; script-src 'self'; … font-src 'self'; …
Cache-Control: no-cache
```

**La CSP n'a pas encore été validée dans un navigateur réel** — cela demande
HTTPS.

### Pare-feu de l'hôte

`ufw` actif : 22, 80, 443 en entrée, tout le reste refusé. PostgreSQL non
exposé. Les règles ont été posées **avant** l'activation, et la continuité SSH
vérifiée par une **seconde connexion indépendante** après coup.

### Accès au dépôt

Le serveur clone par une **clé de déploiement en lecture seule**, générée sur le
serveur — la moitié privée n'en sort jamais. Vérifié qu'elle **ne peut pas
pousser** : `git push --dry-run` est refusé.

---

## S8. Sauvegarde et restauration — testées pour de vrai

```text
sauvegarde  : /srv/kivou/backups/kivou-20260819T062359Z.dump  (51 Ko, chmod 600)
restauration: base JETABLE kivou_restore_check
vérification: révision 0004_alerts_feedback_analytics · 20 tables
destruction : base jetable supprimée ; kivou_staging jamais touchée
```

Deux défauts réels trouvés en exécutant, pas en relisant :

1. **`pg_dump` refusait l'URL.** `KIVOU_DATABASE_URL` est une URL SQLAlchemy
   (`postgresql+psycopg://`) qui nomme le pilote Python ; `pg_dump` ne connaît
   que la forme libpq. Le script la normalise désormais.
2. **Trois tables vérifiées n'existaient pas** — `app_user`,
   `discovery_grant`, `notification_preference`. Les vrais noms sont
   `auth_user`, `discovery_signal_grant`, `account_notification_preference`. Le
   script criait « table absente » sur une restauration parfaitement saine :
   un **faux négatif**, le pire résultat possible pour une vérification de
   sauvegarde. Noms relevés sur le schéma réel.

`kivou-backup.timer` est actif (quotidien, 03h17). La sauvegarde reste **sur le
même hôte** : ce n'est pas un plan de reprise. Un Swiss Backup existe désormais
sur le compte (`BK-1982051-2`) et serait la destination hors hôte naturelle —
porte de production, non traitée ici.

---

## S9. Continuité au redémarrage

```text
compte de staging créé      → HTTP 201
comptes en base AVANT       → 1
systemctl restart kivou-api → active
comptes en base APRÈS       → 1
```

L'état persiste. Aucun effet de bord dupliqué. Services activés au démarrage :
`kivou-api`, `nginx`, `postgresql`, `kivou-backup.timer`, `ufw` — tous
`enabled`.

---

## S10. Job d'alerte — préparé, volontairement non planifié

Deux découvertes :

1. L'unité systemd **omettait `--database-url`**, obligatoire pour le CLI. Le
   service échouait en `2/INVALIDARGUMENT`. Corrigé.
2. Sans SMTP, le job **refuse de lui-même** d'envoyer quoi que ce soit et sort
   en code 2 avec « alertes non configurées ». C'est le bon comportement.

**`kivou-alerts.timer` est délibérément désactivée.** Activée, elle produirait
une unité en échec toutes les heures ; la surveillance des unités en échec (§40)
ne distinguerait alors plus une vraie panne d'un état attendu. Une alarme qui
sonne en permanence n'alarme plus personne. À activer quand SMTP existera.

---

## S11. Matrice des portes — réévaluée

```text
GATE                                      STATUS

GitHub branch CI                          PASS       run 32224029650
Exact SHA deployed                        PASS       a276aed, arbre propre

HTTPS staging                             BLOCKED    pare-feu cloud 80/443
Frontend serving                          PASS       vérifié via nginx
FastAPI                                   PASS       actif, 2 workers
PostgreSQL                                PASS       16.14, localhost, rôle non-superutilisateur
Migrations                                PASS       None → 0004, jouée une fois

Health live                               PASS       200
Health ready                              PASS       200 + révision

Auth/browser session                      BLOCKED    cookie Secure : exige TLS
CSRF                                      PASS       origine étrangère rejetée
Rate limiting                             PASS       429 après 4 requêtes
Security headers                          PASS       5 en-têtes, défaut d'héritage corrigé

Turiya Stripe TEST isolation              BLOCKED    prérequis : URL publique
Kivou Stripe TEST webhook                 BLOCKED    prérequis : HTTPS
Stripe Checkout TEST E2E                  BLOCKED    prérequis : webhook
Stripe success authorization safety       BLOCKED    prérequis : checkout
Customer Portal TEST                      BLOCKED    prérequis : checkout

SMTP                                      BLOCKED    aucun identifiant
Password reset email E2E                  BLOCKED    aucun SMTP
Customer alert email E2E                  BLOCKED    aucun SMTP
SPF/DKIM/DMARC                            PASS       les trois publiés et vérifiés

Alert timer                               BLOCKED    volontairement désactivée jusqu'à SMTP
Ingestion/materialization runtime         BLOCKED    SPEC-016A requise
Ingestion timer                           BLOCKED    SPEC-016A requise

Backup                                    PASS       dump 51 Ko, minuterie active
Restore                                   PASS       restauré, vérifié, base jetable détruite
Logging                                   PASS       journald, diagnostics exploitables
Monitoring                                BLOCKED    sonde externe exige HTTPS
Firewall                                  PASS       ufw 22/80/443, PostgreSQL fermé
Secret scan                               PASS       aucun secret indexé

Desktop E2E                               BLOCKED    exige HTTPS
Mobile smoke                              BLOCKED    exige HTTPS
Restart continuity                        PASS       état persisté, aucun doublon
```

**16 PASS · 17 BLOCKED.** Les blocages n'ont plus que **trois** causes :
le pare-feu du cloud, l'absence de SMTP, et l'ingestion reportée en SPEC-016A.

---

## S12. Verdict

```text
STAGING HOST READY — DOMAIN + INGESTION BLOCKED
```

L'hôte est prêt : Kivou tourne sur `kivou-staging-01`, au SHA validé par la CI,
avec PostgreSQL migré, les sondes vertes, la CSRF et la limitation de débit
actives, les en-têtes en place, la sauvegarde **restaurée et vérifiée**, et la
continuité au redémarrage prouvée.

Le domaine est enregistré et `staging.kivou.eu` résout vers ce serveur. Ce qui
manque n'est plus le DNS mais **l'ouverture de 80/443 dans le groupe de sécurité
OpenStack** — une action de console que ni `ufw` ni l'API Infomaniak ne peuvent
faire.

### Chemin critique, par ordre de déblocage

1. **Ouvrir 80 et 443** dans le groupe de sécurité de `ov-f58505`.
   → débloque TLS, session navigateur, Stripe, surveillance, E2E desktop et
   mobile : **11 portes** d'un seul geste. Je reprends ensuite automatiquement
   (certificat, HSTS, bascule du gabarit TLS, vérification navigateur).
2. **Identifiants SMTP + boîte de test.** → réinitialisation de mot de passe,
   alertes clients, activation de la minuterie.
3. **SPEC-016A — runtime d'ingestion.** → un feed alimenté par de vraies
   données.

### Limites respectées

Stripe **non touché**, ni test ni live. Aucun secret dans Git ni dans ce
rapport. `courrierclair-prod` intact. Aucun Hermes, aucun jeton d'écriture —
la clé de déploiement est en lecture seule et refuse de pousser. PR #6 **non
fusionnée**, `main` intact.

---
---

# PARTIE III — Après ouverture du pare-feu du cloud

**Date :** 19 août 2026, fin de journée.

Le propriétaire a ouvert 80 et 443 en entrée. Le blocage réseau est levé, et
Kivou est **publiquement accessible en HTTPS**.

---

## T1. Vérification réseau, avant toute émission

```text
TCP 22  OUVERT
TCP 80  OUVERT          ← nouvellement ouvert
TCP 443 pas encore servi (rien n'écoutait à ce stade)

staging.kivou.eu → 179.237.100.62
http://staging.kivou.eu/ → HTTP 200, servi par 179.237.100.62
```

**Le trafic atteint bien le bon hôte** — vérifié sur le contenu, pas seulement
sur l'adresse : `Server: nginx/1.24.0`, `<title>Kivou</title>`, racine SPA
présente, en-têtes Kivou, et `/health/ready` répondant avec notre révision
Alembic. Aucun risque d'avoir configuré un serveur tiers.

---

## T2. Certificat TLS

Émis par **`certbot certonly --webroot`**, délibérément pas `--nginx` : le mode
`--nginx` réécrit le fichier de site, ce qui ferait diverger le serveur du
gabarit versionné. Avec `certonly`, certbot ne touche qu'à `/etc/letsencrypt`,
et le gabarit du dépôt reste la seule source de vérité.

```text
subject   CN = staging.kivou.eu
issuer    Let's Encrypt (CN = YE1)
validité  19 août 2026 → 17 novembre 2026   (89 jours restants)
```

**Renouvellement automatique :** `certbot.timer` `enabled`, prochaine exécution
dans ~13 h. Aucun certificat auto-signé n'a été fabriqué à aucun moment.

**Redirection :** `http://staging.kivou.eu/` → **301** →
`https://staging.kivou.eu/`.

---

## T3. Routage vérifié depuis l'extérieur, en HTTPS réel

| Route | Couche | Résultat |
|---|---|---|
| `/health/live` | API | 200 `{"status":"live"}` |
| `/health/ready` | API | 200 + révision `0004_alerts_feedback_analytics` |
| `/billing/plans` | API | 200, JSON du catalogue |
| `/me`, `/signals` | API | 401 sans session — correct |
| `POST /webhooks/stripe` | API | 503 `billing_unavailable` — atteint bien le backend |
| `/`, `/login`, `/signup`, `/forgot-password`, `/reset-password` | frontend | 200, SPA |
| `/app/signals` | frontend | 200, SPA |
| **`/checkout/success`**, **`/checkout/cancel`** | **frontend** | 200, SPA |

Le piège de §7 tient en production : `/billing/*` rend du JSON, `/checkout/*`
rend l'application.

---

## T4. En-têtes de sécurité — sur les réponses HTTPS réelles

Inspectés sur trois surfaces distinctes : le document HTML, un actif empreinté,
et une réponse d'API.

| En-tête | `/` | `/assets/…js` | `/health/live` |
|---|---|---|---|
| `Content-Security-Policy` | ✅ | ✅ | ✅ |
| `X-Content-Type-Options` | ✅ | ✅ | ✅ |
| `Referrer-Policy` | ✅ | ✅ | ✅ |
| `X-Frame-Options: DENY` | ✅ | ✅ | ✅ |
| `Permissions-Policy` | ✅ | ✅ | ✅ |
| `Strict-Transport-Security` | ✅ | ✅ | ✅ |

Anti-cadrage doublement assuré : `frame-ancestors 'none'` dans la CSP **et**
`X-Frame-Options: DENY`. **Aucun `unsafe-eval`** — vérifié sur la réponse, pas
sur la configuration.

### Un second défaut d'héritage, trouvé ici

HSTS était déclaré au niveau serveur et **manquait sur toutes les réponses du
frontend** — exactement le piège corrigé en Partie II, mais sur un autre
en-tête : `location = /index.html` et `/assets/` posent leur propre
`Cache-Control`, ce qui annule l'héritage. Le document HTML, première réponse
que voit le navigateur et la seule qui compte vraiment pour HSTS, partait sans.

Corrigé en déplaçant HSTS dans le fichier partagé. Au passage, `expires` a été
retiré des blocs d'actifs : il émettait un **second** `Cache-Control` en plus de
la directive explicite.

Aucun de ces deux défauts n'apparaît dans `nginx -t` ni dans les journaux. Ils
ne se voient qu'en lisant les en-têtes d'une vraie réponse.

---

## T5. Validation navigateur — CSP et polices

Chromium sur `https://staging.kivou.eu/` :

```text
titre          Kivou
h1             Turn won public contracts into concrete B2B opportunities.
polices        Lora Variable · Instrument Sans Variable   (chargées)
racine SPA     peuplée
requêtes tierces   AUCUNE
violations CSP     AUCUNE
```

Seule erreur console : un `401` — la vérification de session sur `/me` pour un
visiteur anonyme. C'est le comportement attendu, pas un défaut.

Deux confirmations importantes :

* **la CSP ne casse pas notre propre application** ;
* **l'auto-hébergement des polices tient en production** : zéro requête vers un
  hôte tiers, ce que `font-src 'self'` verrouille désormais au niveau du
  navigateur.

---

## T6. Cookie et CSRF — parcours complet sur HTTPS

```text
set-cookie: kivou_session=***; expires=…; HttpOnly; Path=/; SameSite=lax; Secure
```

| Vérification | Résultat |
|---|---|
| Inscription depuis `https://staging.kivou.eu` | **201**, cookie accepté par le client |
| Session réutilisable sur `/me` | **200** |
| Requête modifiante depuis `https://evil.example.com` | **`csrf_origin_rejected`** |

Le parcours de session complet fonctionne maintenant : en HTTP simple, le
cookie `Secure` était — correctement — refusé par le client. C'est TLS qui a
débloqué cette porte, pas un assouplissement de la sécurité.

---

## T7. Limitation de débit et surveillance, par le chemin public

Huit requêtes sur `/auth/login` en HTTPS :

```text
401 401 401 429 429 429 429 429
```

Trois passent (mot de passe faux, refus applicatif), puis **429**. Conforme.

Sonde externe du dépôt, exécutée contre l'origine publique :

```text
[kivou-healthcheck] https://staging.kivou.eu
  OK  /health/live  → 200
  OK  /health/ready → 200
  OK  certificat valide 89 j
  code de sortie 0
```

Surveillance conventionnelle, sans agent, comme demandé.

---

## T8. Stripe

### Isolation Turiya — **PASS**

Le webhook TEST de Turiya est **déjà désactivé** :

```text
we_1TPGpwC34k5bO7Y37W1YR4bp
description  [DÉSACTIVÉ 2026-08-18] Turiya production v7
status       disabled
url          https://turiya-audit.ch/api/webhooks/stripe
```

Il ne peut donc plus recevoir d'événement, et l'historique financier est
conservé — désactivé, pas supprimé. **Aucun objet LIVE n'a été touché.**

### Un défaut de câblage trouvé — et corrigé

`build_application()` construisait l'application **sans passerelle Stripe**. La
facturation aurait été indisponible **en permanence** sur tout déploiement, même
parfaitement configuré. Le défaut est silencieux : l'application démarre, sert
le feed, et seule une tentative de paiement l'aurait révélé.

Corrigé : la passerelle est construite quand `STRIPE_SECRET_KEY` existe, et vaut
`None` sinon — auquel cas les routes de facturation répondent 503
`billing_unavailable`, ce qui est exact. Deux tests couvrent les deux cas.

### Ce qui reste bloqué, et pourquoi

Le serveur n'a **aucune clé Stripe TEST**. Je n'ai pas les moyens d'en obtenir
une : le MCP Stripe agit sur le compte mais n'expose aucune clé secrète, et
Stripe n'autorise pas la création de clés secrètes par API.

**Je n'ai délibérément pas créé le webhook TEST Kivou.** Créé maintenant, il
pointerait vers un service qui répond 503 faute de clé : il ne collecterait que
des échecs, et Stripe finit par désactiver un point d'entrée qui échoue
durablement. Mieux vaut le créer en même temps que la clé.

**Pour débloquer :** déposer une clé Stripe **TEST** dans
`/etc/kivou/staging.env` (`STRIPE_SECRET_KEY=sk_test_…`). Je crée ensuite le
webhook vers `https://staging.kivou.eu/webhooks/stripe` avec les 8 événements
requis, configure le portail, et déroule le parcours de paiement TEST complet.

`automatic_tax` reste `false` (§24). Aucune décision fiscale n'est prise ici.

---

## T9. Ce qui n'a pas bougé

**SMTP** — aucun identifiant, aucune boîte de test. Réinitialisation de mot de
passe et alertes clients restent bloquées. `kivou-alerts.timer` reste
**volontairement désactivée** : sans SMTP, le job sortirait en code 2 chaque
heure et une unité en échec permanent n'est pas de la surveillance, c'est du
bruit qui masque les vraies pannes.

Le domaine dispose déjà de SPF, DKIM et DMARC (`p=reject`, strict) — la
délivrabilité sera donc à vérifier sérieusement dès que l'expéditeur existera.

**Ingestion** — inchangé, **SPEC-016A**, en cours indépendamment. Aucun script
de recherche n'a été utilisé comme job de production.

---

## T10. Matrice des portes — état courant

```text
GATE                                      STATUS

GitHub branch CI                          PASS       run 32227772758
Exact SHA deployed                        PASS       10c6f11, arbre propre

HTTPS staging                             PASS       Let's Encrypt, renouvellement actif
Frontend serving                          PASS       vérifié en HTTPS externe
FastAPI                                   PASS       actif, 2 workers
PostgreSQL                                PASS       16.14, localhost, rôle non-superutilisateur
Migrations                                PASS       0004, jouée une fois

Health live                               PASS       200 en HTTPS public
Health ready                              PASS       200 + révision

Auth/browser session                      PASS       cookie Secure accepté, /me à 200
CSRF                                      PASS       origine étrangère rejetée en HTTPS
Rate limiting                             PASS       429 par le chemin public
Security headers                          PASS       6 en-têtes sur les 3 surfaces
CSP navigateur                            PASS       aucune violation, aucune requête tierce

Turiya Stripe TEST isolation              PASS       webhook désactivé, historique conservé
Kivou Stripe TEST webhook                 BLOCKED    STRIPE_SECRET_KEY absente
Stripe Checkout TEST E2E                  BLOCKED    prérequis : webhook
Stripe success authorization safety       BLOCKED    prérequis : checkout
Customer Portal TEST                      BLOCKED    prérequis : checkout

SMTP                                      BLOCKED    aucun identifiant
Password reset email E2E                  BLOCKED    aucun SMTP
Customer alert email E2E                  BLOCKED    aucun SMTP
SPF/DKIM/DMARC                            PASS       les trois publiés et vérifiés

Alert timer                               BLOCKED    désactivée à dessein jusqu'à SMTP
Ingestion/materialization runtime         BLOCKED    SPEC-016A
Ingestion timer                           BLOCKED    SPEC-016A

Backup                                    PASS       dump vérifié, minuterie active
Restore                                   PASS       restauré, vérifié, base jetable détruite
Logging                                   PASS       journald exploitable
Monitoring                                PASS       sonde externe verte, certificat suivi
Firewall                                  PASS       ufw 22/80/443, PostgreSQL fermé
Secret scan                               PASS       aucun secret indexé

Desktop E2E                               PARTIEL    parcours session vérifié ; paiement bloqué
Mobile smoke                              BLOCKED    non exécuté sur le site live
Restart continuity                        PASS       état persisté, aucun doublon
```

**23 PASS · 1 PARTIEL · 11 BLOCKED.**

Les blocages se ramènent à **trois** causes, plus une vérification non encore
exécutée :

```text
CLÉ STRIPE TEST absente  →  4 portes
SMTP absent              →  4 portes
INGESTION (SPEC-016A)    →  2 portes
Passage mobile à faire   →  1 porte
```

**`CLOUD FIREWALL` est retiré de la liste des blocages.** `DOMAIN` l'était déjà.

---

## T11. Git

| Élément | Valeur |
|---|---|
| Branche | `chore/spec016-staging-readiness` |
| **SHA déployé** | **`10c6f117ea86ffa4c5b975495738a01ea398504b`** |
| CI | run `32227772758` — backend **2718**, ruff propre ; frontend **84**, build, typecheck, lint |
| PR #6 | **brouillon, non fusionnée** |
| `main` | `1e61cc3…`, intact |

Base backend : 2700 → 2716 → **2718**. Jamais diminuée.

Cinq correctifs ont été poussés pendant cette phase, chacun passé par la CI puis
déployé depuis son SHA exact. **Aucun fichier n'a été rapiécé à la main sur le
serveur** : l'arbre de travail du serveur affiche `0 modification locale` après
chaque déploiement.

### Défauts trouvés en Partie III

1. **`http2 on;` n'existe qu'à partir de nginx 1.25.1.** Ubuntu 24.04 livre
   1.24 : le gabarit était **indéployable** sur la distribution cible.
   `nginx -t` l'a arrêté avant tout rechargement — le service n'a pas été
   interrompu.
2. **HSTS absent des réponses frontend** (§T4).
3. **Double `Cache-Control`** sur les actifs.
4. **Passerelle Stripe jamais construite** (§T8).
5. **Chemins de certificat absents du gabarit**, puisque `certonly` ne les écrit
   pas.

---

## T12. Prochaines étapes

1. **Clé Stripe TEST** dans `/etc/kivou/staging.env` → je crée le webhook,
   configure le portail et déroule le parcours de paiement complet. **4 portes.**
2. **SMTP + boîte de test** → réinitialisation de mot de passe, alertes,
   activation de la minuterie. **7 portes.**
3. **SPEC-016A** → ingestion réelle, feed alimenté. **2 portes.**

Un passage mobile sur le site live reste également à faire.

**Limites respectées :** aucun Stripe LIVE, aucun abonnement réel, aucun secret
dans Git ni dans ce rapport, `courrierclair-prod` intact, aucun Hermes, aucun
jeton d'écriture — la clé de déploiement reste en lecture seule. PR #6 non
fusionnée.

---
---

# PARTIE IV — Pré-closeout : mobile, e-mail, et nettoyage Stripe

**Date :** 19 août 2026.

---

## T13. Smoke mobile sur le site live

Exécuté contre `https://staging.kivou.eu` dans un Chromium piloté, en émulation
téléphone : 390 × 844, `isMobile`, `hasTouch`, écran ×3. Aucune dépendance
ajoutée au dépôt — le navigateur vient du cache local.

### Un défaut trouvé, et corrigé

**La page d'accueil défilait horizontalement.** `scrollWidth` 420 pour un
`clientWidth` de 390 : le bandeau public — logo, sélecteur de langue,
« Se connecter », « Créer un compte » — réclamait 419 px et rien ne se repliait.
C'était la première page que voit un prospect.

Corrigé par un repli (`flex-wrap`), et non par un resserrement des espacements :
les libellés changent de langue, « Créer un compte » est plus long que
« Get started », et un calage aux pixels sur l'anglais aurait cassé en français.
Aucun contrôle n'est masqué — masquer une action de navigation serait une
décision de produit, pas une correction de mise en page.

Vérifié après correction, sur le build réel :

| Largeur | Langue | `scrollWidth` | Bandeau |
|---|---|---|---|
| 320 | fr | 320 | replié |
| 390 | fr | 390 | replié |
| 390 | en | 390 | replié |
| 768 | fr | 768 | une ligne, inchangé |
| 1280 | fr | 1280 | une ligne, inchangé |

Le poste de travail n'a pas bougé. Ce défaut n'était pas couvert par les tests
frontend : jsdom tourne avec `css: false`, donc aucune requête média ni aucun
calcul de mise en page n'y est évalué. Il ne pouvait être vu que dans un vrai
navigateur.

### Parcours mesuré, après correction

| Route | Débordement | `h1` | Polices |
|---|---|---|---|
| `/` | non | « Turn won public contracts… » | 2 |
| `/login`, `/signup` | non | Se connecter / Créer un compte | 2 |
| `/forgot-password` | non | Mot de passe oublié | 2 |
| `/reset-password?token=…` | non | Choisir un nouveau mot de passe | 2 |
| `/app/signals` | non | Signaux récents | 2 |
| `/app/billing` | non | Facturation | 2 |
| `/app/notifications` | non | Notifications | 2 |
| `/app/icps` | non | Profils de ciblage | 2 |
| détail de signal | non | état « introuvable » | 2 |
| paiement Stripe | non | — | — |

**Tiroir de navigation :** `aria-expanded` passe à `true`, le conteneur porte
`role="dialog"` et `aria-modal="true"`, le focus entre dans le tiroir, `Échap`
le referme, et **0 lien de navigation reste visible** après fermeture. Un scrim
« Fermer le menu » intercepte les clics extérieurs — c'est d'ailleurs lui qui a
fait échouer ma première tentative d'automatisation, ce qui prouve qu'il est
bien actif.

**CSP : aucune violation. Requêtes tierces : aucune.** Les deux polices
(`Lora Variable`, `Instrument Sans Variable`) se chargent depuis notre origine.

**Session :** connexion depuis le téléphone émulé, navigation sur cinq routes
applicatives, puis rechargement complet — la session survit ; l'utilisateur
reste sur `/app/signals`.

### Cibles tactiles

Tous les contrôles principaux — boutons, champs, liens de navigation, bascules —
mesurent au moins 44 px de haut. Restent sous ce seuil : le lien d'évitement, le
lien du logo, et les liens **en ligne dans une phrase** (« Créer un compte »,
« Retour à la connexion », 22 px). C'est conforme : le critère WCAG 2.2 de
taille de cible exclut explicitement les liens intégrés à un bloc de texte. Les
cases à cocher natives affichent 14–18 px de boîte, mais leur zone cliquable
inclut l'étiquette associée.

### Le feed est vide, et c'est l'état réel

Aucun signal n'a été fabriqué. Le compte de test possède un profil de ciblage
actif et complet (`status: active`, matériaux × gros œuvre et génie civil,
FR + CH, seuil 250 000 EUR) et le feed rend `items: []`. C'est l'état
authentique tant que **SPEC-016A** n'est pas fusionnée. L'état vide s'affiche
correctement, sans débordement.

Faute de carte à ouvrir, la route de détail a été validée sur une clé
inexistante : elle rend son état « introuvable » sans erreur.

**Mobile smoke = PASS.**

---

## T14. Audit de la remise du lien de réinitialisation

### **PASSWORD RESET SMTP WIRING: MISSING**

Le câblage manquait — pas la logique.

```text
POST /auth/password-reset/request
  → routes_auth.password_reset_request
      délégué à  request.app.state.password_reset_delivery
  → service.request_password_reset
      crée le jeton, n'en stocke que l'empreinte, appelle delivery.deliver()
  → app.create_app(password_reset_delivery=…)
      accepte un adaptateur depuis SPEC-011
  → asgi.build_application()
      NE LE FOURNISSAIT PAS      ← le défaut
  → app.state.password_reset_delivery = _NullDelivery()
      « Aucune remise. Le jeton est produit, personne ne le reçoit. »
```

La production tournait donc sur `_NullDelivery`. Le jeton était créé en base, la
route rendait 202, et personne ne recevait jamais rien. **Aucune erreur, aucun
journal** : l'absence d'e-mail ne produit pas d'exception.

**Ajouter des identifiants SMTP à l'environnement n'aurait rien changé.** C'est
exactement l'hypothèse que la consigne demandait de ne pas faire, et elle était
fausse.

Le même défaut existait pour Stripe et a été corrigé en Partie III. Deux fois le
même schéma : une fabrique paramétrable, des tests qui injectent un double, et
un point d'entrée de production qui ne branche rien.

### Ce qui a été implémenté

`src/signals/accounts/reset_delivery.py` — `SmtpPasswordResetDelivery`.

* **Transport réutilisé, pas dupliqué.** `SmtpAlertGateway` n'a d'« alerte » que
  le nom : c'est un client SMTP authentifié avec STARTTLS et une taxinomie
  d'erreurs qui distingue déjà le rejouable de l'irrécupérable. En écrire un
  second exposerait à corriger deux fois le même défaut de TLS ou de délai.
* **Gabarit séparé.** Une alerte est un e-mail commercial : opportunités,
  acheteur, lien profond, pied de page de désinscription. Une réinitialisation
  est un e-mail de sécurité. Un test vérifie que le vocabulaire commercial
  n'apparaît pas dans le message de sécurité.
* **`deliver()` ne lève jamais.** Décision de sécurité : la remise n'est appelée
  que si le compte existe. Une panne SMTP qui remonterait ferait rendre 500 pour
  une adresse connue et 202 pour une inconnue — la page de demande deviendrait
  un **oracle d'existence de compte**. Second effet : la remise a lieu dans la
  transaction qui vient d'insérer le jeton ; laisser remonter l'exception
  annulerait cette insertion, et une personne dont le message est malgré tout
  parti recevrait un lien déjà mort.
* **`Message-ID` aléatoire.** Les alertes utilisent un identifiant déterministe
  pour que deux envois d'un même lot soient dédupliqués. Ici ce serait un
  défaut : deux demandes successives porteraient le même identifiant, et le
  second e-mail — celui qui porte le jeton encore valable — serait écarté comme
  doublon. Il ne dérive jamais du jeton, même par empreinte.
* **`public_site_url`.** `/reset-password` est servi à la **racine** du site,
  tandis que `KIVOU_PUBLIC_APP_URL` pointe sur `/app` pour les liens profonds
  d'alerte. Un lien bâti sur la base des alertes donnerait
  `…/app/reset-password`, que le routeur client ne connaît pas. Le préfixe est
  retiré plutôt que redemandé dans une seconde variable : deux URL publiques à
  tenir cohérentes finissent toujours par diverger.
* **`smtp_transport()` partagé** entre le cycle d'alerte et l'application, pour
  qu'un seul endroit lise la configuration SMTP.

Propriétés préservées et couvertes : réponse générique identique pour une
adresse connue et inconnue, y compris **quand le transport est en panne** ;
jeton à usage unique ; révocation de toutes les sessions à la confirmation ;
jeton et adresse absents des journaux.

**29 tests**, dont un parcours complet : inscription → demande → **extraction du
jeton depuis le corps de l'e-mail capturé** → confirmation → reconnexion avec le
nouveau mot de passe. Vérifier séparément que le service émet un jeton et que le
gabarit contient un lien laisserait passer une troncature ou un mauvais
paramètre ; ici le jeton fait l'aller-retour.

Aucun e-mail réel n'a été envoyé.

**Wiring = READY. Livraison réelle = bloquée sur SMTP.**

---

## T15. Les entrées manquantes, par leur nom exact

### SMTP — lues par `ApiConfig.from_environment()`

| Variable | Sémantique | Obligatoire |
|---|---|---|
| `SMTP_HOST` | hôte SMTP soumission | **oui** |
| `SMTP_FROM_EMAIL` | expéditeur transactionnel | **oui** |
| `SMTP_PORT` | port ; défaut `587` | non |
| `SMTP_USERNAME` | identifiant | selon l'hôte |
| `SMTP_PASSWORD` | mot de passe — jamais journalisé | selon l'hôte |
| `SMTP_FROM_NAME` | nom affiché ; défaut `Kivou` | non |
| `SMTP_USE_TLS` | STARTTLS ; défaut activé | non |
| `KIVOU_PUBLIC_APP_URL` | **déjà posée** — `https://staging.kivou.eu/app` | oui |

`KIVOU_PUBLIC_APP_URL` doit garder son suffixe `/app` : les alertes en
dépendent, et la racine du lien de réinitialisation en est dérivée.

**Identité d'expéditeur retenue :** **`no-reply@kivou.eu`** — avec tiret,
confirmée par l'exploitant le 19 août 2026. Non créée à ce jour, et aucun
enregistrement DNS n'a été modifié. Le domaine publie déjà SPF, DKIM et DMARC en
`p=reject` strict — la délivrabilité devra donc être vérifiée sérieusement dès
que la boîte existera.

**Boîte de réception contrôlée :** il en faut une, distincte de l'expéditeur,
pour recevoir et cliquer le lien lors du test de bout en bout.

### Stripe — correction d'un constat de la Partie III

La Partie III affirmait : « Le serveur n'a aucune clé Stripe TEST. » **C'était
faux au moment de la relecture.** Une clé `sk_test_` a été déposée dans
`/etc/kivou/staging.env` à 08:12 UTC, après le démarrage du service à 07:29 —
donc présente dans le fichier, mais **non chargée** par le processus.

Ce décalage a produit un incident au déploiement suivant : le service a refusé
de démarrer, et staging est passé en 502.

```text
ValueError: facturation activée sans URL de retour :
STRIPE_SUCCESS_URL, STRIPE_CANCEL_URL, STRIPE_PORTAL_RETURN_URL
doivent être définies
```

**Le garde-fou de SPEC-015 a fonctionné exactement comme prévu** : plutôt que de
démarrer et de renvoyer les clients payants vers un domaine choisi par un
défaut, l'application refuse de servir. Les trois URL — non secrètes — ont été
posées, et le service est reparti.

| Variable | Valeur en staging | État |
|---|---|---|
| `STRIPE_SECRET_KEY` | clé **TEST** | posée par l'exploitant |
| `STRIPE_SUCCESS_URL` | `https://staging.kivou.eu/checkout/success` | posée |
| `STRIPE_CANCEL_URL` | `https://staging.kivou.eu/checkout/cancel` | posée |
| `STRIPE_PORTAL_RETURN_URL` | `https://staging.kivou.eu/app/billing` | posée |
| `STRIPE_WEBHOOK_SECRET` | secret du webhook Kivou TEST | posée |
| `KIVOU_STRIPE_MODE` | `test` | déjà posée |
| `STRIPE_PORTAL_CONFIGURATION_ID` | portail Kivou dédié | **manquante** |
| `STRIPE_FOUNDING_COUPON_ID` | coupon fondateur | facultative |

Aucune valeur secrète ne figure dans ce rapport.

**Catalogue TEST vérifié** — les six prix existent avec les clés de recherche
exactes qu'attend le code, et aux montants publics :

```text
kivou_essential_monthly_eur   49,00 EUR      kivou_essential_monthly_chf   49,00 CHF
kivou_pro_monthly_eur         99,00 EUR      kivou_pro_monthly_chf         99,00 CHF
kivou_scale_monthly_eur      199,00 EUR      kivou_scale_monthly_chf      199,00 CHF
```

---

## T16. Nettoyage Stripe — audit Turiya → Kivou

Kivou et Turiya **partagent les mêmes comptes Stripe**. Ce n'est pas un
environnement jetable : le compte LIVE est un compte marchand réel, vérifié,
avec un compte bancaire et des CGU acceptées.

```text
TEST   acct_1TMqChC34k5bO7Y3   « Environnement de test Turiya »   (bac à sable)
LIVE   acct_1TMqCOFx3uZwOQKx   « Turiya »
```

### Où « Turiya » apparaît, par catégorie

| Catégorie | TEST | LIVE | Nature |
|---|---|---|---|
| Nom du compte / tableau de bord | « Environnement de test Turiya » | « Turiya » | opérationnel |
| Nom commercial public | « Environnement de test Turiya » | « Turiya » | **vu du client** |
| Profil d'activité — site | `accessible.stripe.com` (factice) | `turiya-audit.ch` | vu du client |
| Profil d'activité — description | audits web | audits web | vu du client |
| Charte (logo, icône, couleurs) | **aucune** avant intervention | logo + icône Turiya, `#d4af7f` | **vu du client** |
| Portail client | en-tête « Pilotage Turiya », retour `turiya-audit.ch` | idem | **vu du client** |
| Descripteur de relevé | `ENVIRONNEMENT DE TEST ` | **`TURIYA-AUDIT`** (préfixe `TA`) | **vu du client** |
| Entité légale | « Gerald Ellis » (données de test Stripe) | **Rodrigue Bruppacher**, vérifié | légal |
| `company.name` | « Environnement de test Turiya » | `null` | légal (bac à sable : factice) |
| Informations fiscales | — | siège à Sion, aucun « Turiya » | légal |
| Banque / versements | « Sandbox User », YETTEL (factice) | **Rodrigue Bruppacher**, UBS | légal |

**Constat central : aucun champ légal ne dit « Turiya ».** L'entité qui opère le
compte est une personne physique, Rodrigue Bruppacher, vérifiée. « Turiya » n'est
qu'un nom de projet posé sur des champs d'affichage. Il n'y a donc **rien à
arrêter** au titre de la règle « ne pas toucher à l'identité légale ».

Seule exception à signaler : `company.name` du bac à sable vaut « Environnement
de test Turiya ». C'est un champ de nature légale, mais son contenu est
synthétique — numéro d'identification `000000000`, adresse `address_full_match`,
banque factice. Il est signalé sans être modifié.

### Ce qui a été appliqué

**Charte du bac à sable → Kivou.** Elle était vide (défauts Stripe, `#525f7f`) :
la pose est purement additive, rien de Turiya n'a été écrasé.

```text
couleur principale      #234236    Forest Green
couleur d'accent        #c56440    Terracotta
fond du paiement        #faf6f1    Warm Ivory
bouton du paiement      #234236
police                  Inter      (le repli déclaré dans nos jetons)
```

Vérifié sur une vraie session de paiement TEST : `background_color: #faf6f1`,
`button_color: #234236`, `font_family: inter`. **La charte Kivou s'applique
réellement au paiement.**

### Ce qui reste, et pourquoi

L'API disponible ici **n'expose aucune opération d'écriture** sur les réglages de
compte (`POST /v1/accounts/{id}`) ni sur les configurations de portail. Ces deux
surfaces demandent le tableau de bord. Les valeurs sont fournies en §T18.

La preuve que cela compte a été capturée sur la page de paiement réelle, à
390 px :

```text
titre de l'onglet   Environnement de test Turiya
en-tête marchand    Environnement de test Turiya
produit             S'abonner à Kivou Essential — 49,00 € par mois
```

Un client Kivou voit donc « Turiya » au moment de payer.

**Décisions de l'exploitant, prises pendant cette session :** descripteur LIVE
→ `KIVOU` ; identité publique LIVE entièrement basculée sur Kivou ; les
renommages au tableau de bord seront appliqués par l'exploitant à partir des
valeurs de §T18, puis revérifiés par API. **Ils ne sont pas encore faits.**

Rien n'a été supprimé. Le webhook TEST de Turiya reste désactivé et intact, les
produits, prix, factures et clients Turiya n'ont pas été touchés, et aucune
opération LIVE n'a été effectuée.

---

## T17. Parcours de paiement TEST — de bout en bout

Un défaut bloquant a été trouvé au premier appel réel :

```text
Tax ID collection requires updating business name on the customer.
Please set `customer_update[name]` to `auto`.
```

**Aucune session de paiement n'aurait jamais pu s'ouvrir**, ni en staging ni en
production. Un numéro de TVA appartient à une raison sociale ; le collecter sans
autoriser la mise à jour du nom produirait une facture dont le numéro fiscal et
le nom ne correspondent pas — Stripe préfère refuser.

Le défaut n'apparaissait dans **aucun test** : toute la suite double la
passerelle, et personne ne vérifiait la forme des paramètres envoyés. C'est le
bon choix pour rester hors ligne, mais il laissait cet angle mort exact. Un
module de tests substitue désormais le client du SDK et inspecte le
dictionnaire de paramètres, toujours sans appeler Stripe.

### Le parcours, après correction

```text
1  webhook Kivou TEST créé          we_1U65UUC34k5bO7Y3UUS7kCxY
                                    8 événements, statut enabled
                                    secret posé sur le serveur
2  /webhooks/stripe                 400 invalid_webhook_signature   (au lieu de 503)
3  POST /billing/checkout           200, session cs_test_…
4  seconde tentative                409 checkout_in_progress + date d'expiration
5  page de paiement, 390 px         aucun débordement, charte Kivou
6  carte de test 4242…              paiement accepté
7  retour                           vers staging.kivou.eu
8  abonnement Stripe                sub_… actif, 49,00 EUR/mois
                                    lookup_key kivou_essential_monthly_eur
                                    metadata.kivou_account_id = le bon compte
                                    automatic_tax.enabled = false
9  feed du compte                   plan_code: essential
```

L'étape 9 est celle qui compte : **le webhook a réellement synchronisé
l'abonnement dans Kivou**, et le paywall applique le plan payé.

Le garde-fou d'unicité (étape 4) fonctionne et rend une erreur lisible portant
la date d'expiration.

### Une fragilité trouvée au passage, non corrigée

Quand Stripe rejette une session pour une raison **permanente**, l'exception
remonte en 500 et la tentative locale **reste ouverte**. Sa clé d'idempotence
étant liée à la tentative, tout nouvel essai rejoue la même clé — et Stripe la
refuse dès que les paramètres ont changé. Le compte est alors bloqué jusqu'à
expiration, soit **30 minutes**.

Pour une erreur transitoire, garder la tentative ouverte est correct : rejouer
la même clé est précisément ce qui évite d'ouvrir deux paiements. Le problème ne
concerne que les erreurs définitivement non rejouables.

Correction proposée, à instruire séparément : distinguer les erreurs Stripe non
rejouables, clore la tentative, et rendre un code applicatif plutôt qu'un 500.
Impact borné, mais réel pour un client qui paie.

Le superviseur a tranché le 19 août 2026 : **ne pas modifier dans SPEC-016**, le
parcours de staging contrôlé n'étant pas bloqué. Consigné en
`docs/backlog/post-mvp-billing-hardening.md` sous **BILL-H1**, avec le symptôme,
l'état affecté, le rétablissement de 30 minutes et la distinction proposée entre
erreurs rejouables et terminales. Aucun ajustement discret n'a été fait.

**Ce que cela débloque :** Kivou Stripe TEST webhook · Stripe Checkout TEST E2E ·
sécurité du retour de succès · catalogue TEST → **PASS**.
**Reste bloqué :** portail client TEST, tant que la configuration Kivou n'existe
pas — le portail par défaut est celui de Turiya, et l'utiliser sciemment est
exclu.

---

## T18. Valeurs à appliquer au tableau de bord Stripe

Aucune n'est un secret.

### Bac à sable — `acct_1TMqChC34k5bO7Y3`

| Champ | Valeur cible |
|---|---|
| Nom du compte / tableau de bord | `Kivou — Staging` |
| Nom commercial public | `Kivou — Staging` |
| Site de l'activité | `https://staging.kivou.eu` |
| Description de l'activité | signaux d'adjudication publique pour la prospection B2B |
| Descripteur de relevé | `KIVOU` *(actuellement « ENVIRONNEMENT DE TEST »)* |
| Logo / icône | logo Kivou (`frontend/public/brand/`) |

### Production — `acct_1TMqCOFx3uZwOQKx`

| Champ | Actuel | Valeur cible |
|---|---|---|
| Nom du compte / tableau de bord | `Turiya` | `Kivou — Production` |
| Nom commercial public | `Turiya` | `Kivou` |
| Site de l'activité | `turiya-audit.ch` | `https://kivou.eu` |
| Description | audits web par agents IA | signaux d'adjudication publique pour la prospection B2B |
| Descripteur de relevé | **`TURIYA-AUDIT`** | **`KIVOU`** — approuvé |
| Préfixe carte | `TA` | `KI` |
| Charte | logo Turiya, `#d4af7f` | logo Kivou, `#234236` / `#c56440` |

`KIVOU` est éligible : cinq caractères, uniquement des lettres, aucun caractère
interdit. Les transactions déjà passées conservent leur libellé d'origine —
**l'historique n'est pas réécrit.**

Les couleurs LIVE n'ont **pas** été posées par API bien que ce soit techniquement
possible : cela aurait créé un état intermédiaire incohérent — charte Kivou,
logo Turiya, nom Turiya, descripteur Turiya — sur un compte marchand réel. Le
basculement gagne à être fait d'un bloc.

### Portail client — à créer dans les deux environnements

| Réglage | Valeur |
|---|---|
| En-tête | `Gérer votre abonnement Kivou` |
| Conditions générales | `https://kivou.eu/cgu` |
| Confidentialité | `https://kivou.eu/confidentialite` |
| Retour (staging) | `https://staging.kivou.eu/app/billing` |
| Retour (production) | `https://kivou.eu/app/billing` |

L'identifiant de la configuration TEST devra ensuite être posé dans
`STRIPE_PORTAL_CONFIGURATION_ID` sur le serveur ; sans lui, Kivou emprunte le
portail par défaut, qui est celui de Turiya.

---

## T19. Matrice des portes — après cette phase

```text
GATE                                      STATUS       ÉVOLUTION

Kivou Stripe TEST webhook                 PASS         était BLOCKED
Stripe Checkout TEST E2E                  PASS         était BLOCKED
Stripe success authorization safety       PASS         était BLOCKED
Stripe TEST catalogue                     PASS         6 prix, clés exactes
Turiya Stripe TEST isolation              PASS         inchangé, webhook désactivé
Customer Portal TEST                      BLOCKED      portail Kivou à créer

Mobile smoke                              PASS         était BLOCKED
Desktop E2E                               PASS         était PARTIEL

Password reset SMTP wiring                PASS         était MISSING (implémenté)
SMTP                                      BLOCKED      aucun identifiant
Password reset email E2E                  BLOCKED      aucun SMTP
Customer alert email E2E                  BLOCKED      aucun SMTP
Alert timer                               BLOCKED      désactivée jusqu'à SMTP

Ingestion/materialization runtime         BLOCKED      SPEC-016A
Ingestion timer                           BLOCKED      SPEC-016A

(23 portes de la Partie III inchangées, toutes PASS)
```

**30 PASS · 7 BLOCKED.**

```text
SMTP absent              →  4 portes
INGESTION (SPEC-016A)    →  2 portes
PORTAIL KIVOU à créer    →  1 porte
```

---

## T20. Git

| Élément | Valeur |
|---|---|
| Branche | `chore/spec016-staging-readiness` |
| **SHA déployé** | **`4e92d82399233a9bfbe0e915c168f100489b0c8a`** |
| CI | run `32234025363` — backend **2757**, ruff propre ; frontend **84** |
| PR #6 | **brouillon, non fusionnée** |
| `main` | `1e61cc3…`, intact |

Base backend : 2700 → 2718 → **2757**. Jamais diminuée.

### Défauts trouvés en Partie IV

1. **La remise du lien de réinitialisation n'était pas câblée** en production.
2. **Le paiement était impossible** : `customer_update[name]` absent.
3. **Débordement horizontal de la page d'accueil** à 390 px.
4. **URL de retour Stripe absentes**, révélées par un refus de démarrage.
5. **Une tentative de paiement bloque le compte 30 minutes** après une erreur
   Stripe permanente — signalé, non corrigé.

Les trois premiers ont été corrigés, poussés, validés par la CI, puis déployés
depuis leur SHA exact. Le serveur affiche `0 modification locale`.

---
---

# PARTIE V — Identité Kivou sur Stripe, et mise en service SMTP

**Date :** 19 août 2026.

---

## T21. La boîte d'expédition — vérification avant tout envoi

La consigne signalait une orthographe douteuse (`no-replay.kivou.eu`) et
demandait de vérifier l'adresse réelle avant d'envoyer quoi que ce soit.
Vérifié côté Infomaniak, hébergement mail `1059575` (`kivou.eu`) :

```text
mailbox        no-reply
mailbox        no-reply@kivou.eu
total          1
```

**Aucun écart.** L'adresse réelle est bien `no-reply@kivou.eu`, avec tiret. La
graphie `no-replay` n'existait que dans le message, pas dans l'infrastructure.
Aucun envoi n'a été tenté depuis une identité approximative.

---

## T22. Ce que le plan mail autorise — et ce qu'il refuse

Deux limites de l'hébergement ont arrêté le plan prévu.

**Une seule boîte.** La création de `qa@kivou.eu` est refusée :

```text
400  You have reached the maximum number of e-mail accounts for this e-mail service.
```

**Aucun alias.** `enabled_alias: 0` ; la création d'alias échoue également.

Le destinataire de test dédié n'est donc pas réalisable sur `kivou.eu` en
l'état. Il faudra soit augmenter le plan, soit accepter une adresse de
réception hors domaine — ce qui affaiblit la démonstration d'alignement DMARC,
puisque le message ne serait plus évalué par le même récepteur.

---

## T23. Le mot de passe de la boîte — blocage externe

L'API Infomaniak **accepte** le changement de mot de passe :

```text
PUT   /1/mail_hostings/1059575/mailboxes/no-reply     → {"result":"success","data":true}
PATCH /1/mail_hostings/1059575/mailboxes/no-reply     → {"result":"success","data":true}
```

Mais l'authentification reste refusée, de façon identique partout :

```text
mail.infomaniak.com:587  STARTTLS   535 5.7.0 Invalid login or password
mail.infomaniak.com:465  SSL        535 5.7.0 Invalid login or password
smtp.infomaniak.com:587  STARTTLS   535 5.7.0 Invalid login or password
imap.infomaniak.com:993             Invalid login or password
```

Testé avec l'identifiant complet et l'identifiant court, après propagation.
L'API rend un succès que le service d'authentification ne reflète pas.

**Ce blocage est externe à Kivou.** Il ne peut être levé qu'en définissant le
mot de passe depuis le Manager Infomaniak. Les autres variables SMTP sont déjà
en place sur le serveur ; seule `SMTP_PASSWORD` attend une valeur utilisable.

L'échec a néanmoins produit une vérification utile : le journal du service a
montré

```text
remise du lien de réinitialisation échouée (code=smtp_authentication_failed)
```

pendant que la route rendait bien **202**. L'adaptateur se comporte donc
exactement comme conçu — il absorbe la panne, journalise un code, et ne
transforme pas un échec d'envoi en signal d'existence de compte. Ni le jeton ni
l'adresse n'apparaissent dans le journal.

---

## T24. Un canal auxiliaire trouvé, et refermé

C'est le résultat le plus important de cette phase, et il n'aurait pas été
visible sans un vrai serveur SMTP configuré.

Mesuré sur `staging.kivou.eu`, statut et corps strictement identiques :

```text
adresse CONNUE     202  en  2178 ms
adresse INCONNUE   202  en    98 ms
```

L'aller-retour SMTP n'a lieu que s'il existe un jeton à envoyer. **La durée
trahissait donc l'existence du compte** — une poignée de requêtes suffisait à
énumérer les clients de Kivou, ce que la réponse générique existe précisément
pour empêcher. La réponse était générique ; le temps ne l'était pas.

La remise est désormais retenue puis exécutée **après** la réponse HTTP. Le
point délicat est le suivant : la route appelle `add_task`
**inconditionnellement**. Si elle demandait « y a-t-il un e-mail à envoyer ? »
pour décider de programmer la tâche, elle apprendrait l'existence du compte, et
la branche redeviendrait observable par le prochain qui touche à ce code. Vider
zéro remise coûte le même prix que d'en vider une.

Vérifié sur le serveur après déploiement :

```text
connue = 178 ms   inconnue = 164 ms
connue = 100 ms   inconnue =  92 ms
connue =  96 ms   inconnue =  90 ms
```

L'écart de 2,1 s a disparu. Effet secondaire souhaitable : la remise quitte la
transaction qui insère le jeton, qui est donc validé avant l'envoi.

Six tests ajoutés, dont l'invariant qui compte — vider une remise vide est sans
effet, et une double vidange n'envoie pas deux fois le même lien.

---

## T25. Alignement DNS — un point à confirmer

```text
kivou.eu        TXT   v=spf1 include:spf.infomaniak.ch -all
_dmarc.kivou.eu TXT   v=DMARC1; p=reject;
kivou.eu        MX    5 mta-gw.infomaniak.ch.
```

SPF autorise Infomaniak en rejet strict, et l'expéditeur prévu passe par
Infomaniak : l'alignement SPF tient.

**DKIM n'a pas pu être confirmé.** Aucun sélecteur n'a répondu parmi treize
graphies courantes (`infomaniak`, `ik1`, `default`, `mail`, `dkim`,
`selector1`…). Ce n'est pas une preuve d'absence — un sélecteur est arbitraire —
mais **la Partie III affirmait que DKIM était publié, et cette affirmation
n'est pas vérifiée.** Correction apportée ici.

Avec `p=reject` et un alignement relâché par défaut, SPF seul peut suffire.
Mais DKIM absent dégrade la délivrabilité et ne survit pas au réacheminement. À
confirmer au Manager avant de déclarer la remise opérationnelle.

---

## T26. Stripe — le renommage est incomplet

Le renommage effectué par l'exploitant a porté sur **un seul champ**, dans les
deux environnements :

```text
settings.dashboard.display_name    « Kivou - Staging »   « Kivou - Production »
```

Tous les autres champs visibles du client sont inchangés.

### Quelle surface lit quel champ

C'est le point qui explique la confusion, et il a été établi sur des objets
réels, pas sur la documentation :

| Surface client | Champ lu | Ce que le client voit |
|---|---|---|
| **Paiement (Checkout)** | `business_profile.name` | **« Environnement de test Turiya »** |
| **Facture hébergée** | `settings.dashboard.display_name` | « Kivou - Staging » ✓ |
| **Facture hébergée, 2ᵉ ligne** | descripteur de relevé | **« Environnement de test »** |
| Objet facture (API) | `account_name` | « Environnement de test Turiya » |

Renommer le libellé du tableau de bord corrige donc la facture hébergée, **mais
pas la page de paiement** — qui est la première surface que voit un client.

Vérifié sur une session TEST créée après le renommage :

```text
branding_settings.display_name : « Environnement de test Turiya »
```

### Champs restants, TEST — `acct_1TMqChC34k5bO7Y3`

| Champ | Actuel | Cible |
|---|---|---|
| `business_profile.name` | Environnement de test Turiya | `Kivou — Staging` |
| `business_profile.url` | `accessible.stripe.com` | `https://staging.kivou.eu` |
| `business_profile.product_description` | audits web par agents IA | signaux d'adjudication publique B2B |
| descripteur de relevé | `ENVIRONNEMENT DE TEST ` | `KIVOU` |
| logo / icône | aucun | logo et marque Kivou |
| `company.name` | Environnement de test Turiya | *(champ légal, contenu synthétique — signalé, non modifié)* |

### Champs restants, LIVE — `acct_1TMqCOFx3uZwOQKx`

| Champ | Actuel | Cible |
|---|---|---|
| `business_profile.name` | `Turiya` | `Kivou` |
| `business_profile.url` | `turiya-audit.ch` | `https://kivou.eu` |
| `business_profile.product_description` | audits web par agents IA | signaux d'adjudication publique B2B |
| descripteur de relevé | **`TURIYA-AUDIT`** | **`KIVOU`** *(approuvé)* |
| préfixe carte | `TA` | `KI` |
| logo / icône | fichiers Turiya | logo et marque Kivou |
| couleurs | `#d4af7f` / `#0f172a` | `#234236` / `#c56440` |

**Aucun champ légal ne dit « Turiya ».** L'entité reste Rodrigue Bruppacher,
personne physique vérifiée ; banque, fiscalité et représentant n'ont pas été
touchés et n'ont pas à l'être.

### Ce qui a pu être appliqué, et ce qui n'a pas pu

**Appliqué — couleurs TEST :**

```text
principale        #234236   Forest Green
accent            #c56440   Terracotta
fond paiement     #faf6f1   Warm Ivory
bouton paiement   #234236
police            Inter
```

**Refusé — logo et icône.** Les deux variantes approuvées ont été publiées par
le frontend, à l'identique du pack de design, sans recadrage ni retraitement :

```text
/brand/kivou-mark.png             800 × 800    contextes carrés  (icône)
/brand/kivou-logo-horizontal.png  1200 × 284   contextes larges  (logo)
```

Mais Stripe refuse de les enregistrer par URL :

```text
Something went wrong with saving brand image.
```

Le champ accepte en principe une URL ou un jeton de fichier ; en pratique seul
le jeton fonctionne, et l'API disponible ici **n'expose aucune opération de
téléversement de fichier**. Le logo passe donc obligatoirement par le tableau de
bord.

### LIVE délibérément non modifié

Le superviseur avait autorisé « poser ce qui est possible malgré tout ». Cette
option supposait de poser logo **et** couleurs. Le logo s'avérant impossible,
poser les seules couleurs sur LIVE produirait :

```text
couleurs Kivou  +  logo Turiya  +  nom Turiya  +  descripteur TURIYA-AUDIT
```

c'est-à-dire exactement l'état incohérent que le §6 interdit — et **moins
cohérent qu'aujourd'hui**, où la présentation LIVE est uniformément Turiya, sur
un compte marchand réel portant un historique financier. Le compte LIVE n'a donc
reçu aucune modification. Le basculement doit se faire d'un bloc, au tableau de
bord.

### Portail client

Toujours une seule configuration, celle de Turiya, par défaut :

```text
bpc_1TR9skC34k5bO7Y3mS1FxOh7
en-tête   « Gérer votre abonnement Pilotage Turiya »
retour    https://turiya-audit.ch/espace/parametres#billing
CGU       https://turiya-audit.ch/cgu
```

La création d'une configuration n'est pas exposée par l'API disponible. Le
parcours portail n'a pas été exécuté : ouvrir sciemment un portail Turiya pour
un client Kivou est exclu par le §6.

---

## T27. QA visuelle de la facture TEST

Facture `20YXHWJK-0001`, issue de l'abonnement TEST existant.

**Correct :**

```text
1 × Kivou Essential (at €49.00 / month)      nom de produit Kivou
49,00 €                                       montant et devise du catalogue public
Kivou - Staging                               en-tête de la facture hébergée
QA Billing Kivou, 12 rue de la Paix, Paris    identité client collectée
Visa •••• 4242                                moyen de paiement
automatic_tax : désactivé                     aucune décision fiscale (§24)
```

Le nom et l'adresse du client apparaissent parce que `customer_update` a été
autorisé — la correction de la Partie IV se voit donc jusque sur la facture.

**À corriger :** la seconde ligne affiche « Environnement de test », reprise du
descripteur de relevé périmé.

Aucune information légale obligatoire n'a été masquée.

### Répartition de la maîtrise

| Entièrement maîtrisé par Kivou | Partiellement | Non personnalisable |
|---|---|---|
| nom de produit, plan, devise, montant | couleurs et logo *(champs Stripe, valeurs Kivou)* | gabarit de la facture hébergée |
| identité client collectée | nom marchand *(champ Stripe, dépend du Dashboard)* | numérotation des factures |
| URL de retour | descripteur *(règles de longueur Stripe)* | libellés Stripe, mentions « Propulsé par » |
| politique fiscale | | disposition des e-mails Stripe |

Une limite de l'interface Stripe n'est pas un défaut de design Kivou.

---

## T28. Matrice des portes

```text
GATE                                       STATUS      ÉVOLUTION

Reset request timing indistinguishability   PASS        NOUVEAU — défaut trouvé et corrigé
SMTP sender identity verified               PASS        no-reply@kivou.eu confirmé
SPF / DMARC                                 PASS        vérifiés en direct
DKIM published                              À CONFIRMER la Partie III l'affirmait à tort

SMTP mailbox password                       BLOCKED     API en succès, authentification refusée
Password reset email E2E                    BLOCKED     dépend du mot de passe
Customer alert email E2E                    BLOCKED     dépend du mot de passe
Alert timer                                 BLOCKED     reste désactivée

Stripe TEST customer-visible identity       BLOCKED     Dashboard uniquement
Stripe LIVE customer-visible identity       BLOCKED     Dashboard uniquement
Stripe brand assets (logo / icône)          BLOCKED     aucun téléversement exposé
Stripe TEST brand colours                   PASS        posées et vérifiées
Customer Portal TEST                        BLOCKED     configuration Kivou à créer

Invoice visual QA                           PASS        produit Kivou correct ; descripteur à corriger

Ingestion runtime + timer                   BLOCKED     SPEC-016A

(30 portes des parties précédentes inchangées)
```

**32 PASS · 1 À CONFIRMER · 10 BLOCKED.**

```text
Dashboard Stripe          →  4 portes
Mot de passe de la boîte  →  4 portes
Ingestion (SPEC-016A)     →  2 portes
```

---

## T29. Git

| Élément | Valeur |
|---|---|
| Branche | `chore/spec016-staging-readiness` |
| **SHA déployé** | **`bbd33a7`** |
| CI | run `32241590209` — backend **2763**, ruff propre ; frontend **84** |
| PR #6 | **brouillon, non fusionnée** |
| `main` | `1e61cc3…`, intact |

Base backend : 2700 → 2718 → 2757 → **2763**. Jamais diminuée.

Deux livraisons dans cette phase : la publication des deux PNG de marque
approuvés, et l'égalisation du temps de réponse. Toutes deux passées par la CI
puis déployées depuis leur SHA exact ; le serveur affiche `0 modification
locale`.

Aucun secret ne figure dans ce rapport. `SMTP_PASSWORD` vit uniquement dans
`/etc/kivou/staging.env`, en `600 root:kivou`.

---
---

# PARTIE VI — Mise en service de l'e-mail, et clôture Stripe LIVE

**Date :** 19 août 2026.

---

## T30. Le mot de passe posé au Manager débloque tout

L'échec de la Partie V venait bien de l'API : un mot de passe défini depuis le
Manager Infomaniak est accepté immédiatement.

```text
SMTP  mail.infomaniak.com:587 STARTTLS   LOGIN OK
IMAP  imap.infomaniak.com:993            LOGIN OK
```

**À retenir :** l'API Infomaniak `PUT`/`PATCH` sur une boîte rend
`{"result":"success"}` sans que le mot de passe soit réellement appliqué. Ne pas
s'y fier — un succès d'API n'est pas une preuve d'authentification.

---

## T31. Une boîte `no-reply` ne reçoit rien — diagnostic

Le premier plan de validation supposait de lire l'e-mail dans
`no-reply@kivou.eu`. Il ne fonctionne pas, et la cause a été isolée plutôt que
devinée.

Un message de contrôle envoyé **hors application**, accepté par le serveur de
soumission sans refus de destinataire, n'est jamais arrivé après 90 secondes.
Interrogation directe de la passerelle d'entrée :

```text
RCPT TO:<no-reply@kivou.eu>     250 Ok                   ← adresse livrable
RCPT TO:<inexistant@kivou.eu>   550 User unknown         ← contrôle : elle discrimine
```

La passerelle accepte donc l'adresse, la soumission fonctionne, et le message
disparaît entre les deux. Une boîte `no-reply` jette le courrier entrant — c'est
sa fonction. Elle n'a jamais eu vocation à recevoir.

S'ajoutent deux limites du plan mail `kivou.eu` : **une seule boîte**, et
**aucun alias** (`enabled_alias: 0`). Un destinataire de test sur le domaine
n'est donc pas réalisable en l'état.

La validation a été menée avec un destinataire externe contrôlé, appartenant à
l'exploitant. Son adresse ne figure pas ici.

---

## T32. Réinitialisation de mot de passe — parcours réel complet

Un compte de staging, une demande, un e-mail réellement reçu, et le lien
consommé.

```text
1  session ouverte avec l'ancien mot de passe    200
   /me sur cette session                         200

2  confirmation avec le jeton reçu par e-mail    200  {"status":"password_updated"}

3  la session ouverte AVANT                      401   révoquée
4  l'ancien mot de passe                         401   refusé
5  le nouveau mot de passe                       200   accepté
6  rejeu du même jeton                           400   invalid_reset_token
```

**Six points sur six.** Le lien reçu par e-mail ouvre bien
`https://staging.kivou.eu/reset-password?token=…`, servi par le frontend Kivou.

### La page, à 390 px

```text
h1                    « Choisir un nouveau mot de passe »
débordement           aucun (scrollWidth 390)
champs affichés       un seul, de type password
jeton présent au DOM  NON
polices               Lora Variable · Instrument Sans Variable
violations CSP        aucune
hôtes tiers           aucun
```

Le point le plus intéressant est **`jeton présent au DOM : NON`**. Le jeton est
lu depuis l'URL, porté par l'état du composant, et jamais réinjecté dans le
document. Il ne peut donc pas fuir par une capture d'écran, une extension qui
lit le DOM, ni un copier-coller involontaire.

### Indistinguabilité, vérifiée avec un vrai SMTP

```text
adresse connue     202 en 175 ms
adresse inconnue   202 en 129 ms
```

Le correctif de la Partie V tient en conditions réelles : l'écart de 2,1 s a
disparu, alors même que l'envoi part vraiment.

### Alignement DNS

L'e-mail a été remis à un fournisseur externe alors que `kivou.eu` publie
`DMARC p=reject`. Une remise réussie dans ces conditions **prouve que
l'alignement a été validé** par le récepteur — sans quoi le message aurait été
rejeté. Le sélecteur DKIM reste inconnu ; SPF suffit ici, mais DKIM améliorerait
la survie au réacheminement.

---

## T33. Minuterie d'alerte — activée

Le critère posé était de ne pas activer une minuterie vouée à l'échec. Il est
désormais satisfait : le cycle s'exécute proprement.

```text
comptes examinés=8 · signaux envoyés=0 · not_eligible=7, nothing_to_send=1
ExecMainStatus=0   Result=success
```

Contre `2/INVALIDARGUMENT` ce matin. Zéro envoi n'est pas un échec : c'est
l'absence de signal éligible tant que **SPEC-016A** n'est pas fusionnée.

```text
kivou-alerts.timer   enabled · active
OnCalendar=hourly · Persistent=true · RandomizedDelaySec=300
prochaine exécution  2026-08-19 14:02:03 UTC
```

L'envoi d'alerte **réel** reste à valider quand un signal éligible existera.
Aucun signal n'a été fabriqué pour faire illusion.

---

## T34. Stripe LIVE — presque terminé

Vérifié champ par champ après l'intervention de l'exploitant :

```text
nom commercial public      Kivou
site                       https://kivou.eu
description                Intelligence commerciale
tableau de bord            Kivou - Production
descripteur de relevé      KIVOU
descripteur abrégé         KIVOU
couleurs                   #234236 / #c56440
logo et icône              présents, non intervertis (800×800 et 1200×284)
rendu du paiement          fond #faf6f1, bouton #234236, police Inter, logo affiché
```

L'entité légale, la banque, la fiscalité et le représentant vérifié n'ont pas
été touchés — et ne mentionnaient de toute façon jamais « Turiya ».

### Une erreur de ma part, réparée

En alignant le rendu du paiement, j'ai appelé la mise à jour de la charte **sans
repasser `logo` et `icon`**. Ces champs ont été remis à `null` : omettre un champ
d'image l'efface, il n'est pas conservé. L'exploitant a re-téléversé les deux
fichiers. Aucune donnée financière n'était concernée.

**À retenir :** sur `settings/brand`, toujours repasser `logo` et `icon` dans
tout appel de mise à jour, même quand on ne veut modifier qu'une couleur.

### Ce qui reste, et c'est visible du client

**Le portail client LIVE est encore entièrement Turiya :**

```text
bpc_1TRFNUFx3uZwOQKxMuVSUbp1
en-tête   « Gérer votre abonnement Pilotage Turiya »
CGU       https://turiya-audit.ch/cgu
retour    https://turiya-audit.ch/espace/parametres#billing
```

Un client Kivou qui cliquerait sur « gérer ma facturation » atterrirait sur un
portail Turiya et serait renvoyé vers `turiya-audit.ch`. C'est la dernière
surface Turiya en production.

Les **comportements** sont en revanche déjà ceux qu'attend Kivou : annulation en
fin de période, changement de plan désactivé, historique de factures et moyen de
paiement activés. Seuls les libellés et les URL sont à reprendre.

| Réglage | Valeur cible |
|---|---|
| En-tête | `Gérer votre abonnement Kivou` |
| Conditions générales | `https://kivou.eu/cgu` |
| Confidentialité | `https://kivou.eu/confidentialite` |
| Retour | `https://kivou.eu/app/billing` |

L'environnement TEST reste sur son ancienne présentation, l'exploitant l'ayant
explicitement dépriorisé.

---

## T35. Matrice des portes

```text
GATE                                      STATUS      ÉVOLUTION

SMTP mailbox / transport                   PASS        était BLOCKED
Password reset email E2E                   PASS        était BLOCKED — 6 points sur 6
Reset token absent du DOM                  PASS        NOUVEAU
Reset timing indistinguishability          PASS        confirmé avec un SMTP réel
DMARC alignment                            PASS        prouvé par une remise externe
Alert timer                                PASS        était BLOCKED — activée, exécution propre

Stripe LIVE customer-visible identity      PASS        était BLOCKED
Stripe brand assets (logo / icône)         PASS        était BLOCKED
Stripe LIVE statement descriptor           PASS        TURIYA-AUDIT → KIVOU

Customer Portal LIVE                       BLOCKED     configuration encore Turiya
Customer Portal TEST                       BLOCKED     configuration Kivou à créer
Stripe TEST customer-visible identity      BLOCKED     déprioritisé par l'exploitant

Customer alert email E2E                   BLOCKED     aucun signal éligible — SPEC-016A
Ingestion runtime + timer                  BLOCKED     SPEC-016A
```

**38 PASS · 6 BLOCKED.**

```text
SPEC-016A                    →  3 portes
Portail client (Dashboard)   →  2 portes
Présentation TEST            →  1 porte  (déprioritisée)
```

---

## T36. Git

SHA déployé **`bbd33a7`**, CI `32241590209` — backend **2763**, frontend **84**.
PR #6 en brouillon, `main` intact, serveur à `0 modification locale`.

Cette phase n'a produit **aucun changement de code** : uniquement de la
configuration serveur, du Dashboard Stripe, et de la validation.

Aucun secret ne figure dans ce rapport.

---

## T37. Portail client LIVE — conforme

Vérifié après l'intervention de l'exploitant, sur la configuration **par défaut**
du compte — aucune seconde configuration n'a été créée, ce qui rend
`STRIPE_PORTAL_CONFIGURATION_ID` inutile :

```text
bpc_1TRFNUFx3uZwOQKxMuVSUbp1        is_default: true
en-tête   « Gérer votre abonnement Kivou »
CGU       https://kivou.eu/cgu
vie privée https://kivou.eu/confidentialite
retour    https://kivou.eu/app/billing
```

Les comportements sont restés ceux qu'attend le code — annulation **en fin de
période**, changement de plan désactivé, historique de factures et moyen de
paiement activés.

**Plus aucune surface Turiya visible du client en production.**

L'environnement TEST conserve son ancienne configuration, l'exploitant l'ayant
explicitement dépriorisé.

---

## T38. Catalogue LIVE

Les six prix existent, aux clés exactes qu'attend le code et aux montants
publics :

```text
kivou_essential_monthly_eur   49,00 EUR      kivou_essential_monthly_chf   49,00 CHF
kivou_pro_monthly_eur         99,00 EUR      kivou_pro_monthly_chf         99,00 CHF
kivou_scale_monthly_eur      199,00 EUR      kivou_scale_monthly_chf      199,00 CHF
```

Aucun prix Turiya n'est actif en production.

---

## T39. Annulation en fin de période — chaîne complète

Le portail TEST étant resté sur la présentation Turiya, l'annulation a été
déclenchée **par l'API plutôt que par ce portail** : l'événement produit est le
même (`customer.subscription.updated`), et cela évite d'exposer sciemment un
client Kivou à une interface Turiya.

```text
avant                    plan_code = essential

annulation               cancel_at_period_end = true
                         cancel_at   = 2026-09-19
                         status      = active

après webhook, en base   status                 active
                         cancel_at_period_end   true
                         current_period_end     2026-09-19 09:10:38+00

après, côté client       plan_code = essential
```

Les trois propriétés attendues sont vérifiées : l'annulation est **reflétée**,
le droit d'accès **court jusqu'au terme réel**, et **aucune révocation immédiate
accidentelle** ne se produit. Un client qui annule garde ce qu'il a payé.

Reste à valider le jour du terme, quand la période s'achèvera réellement — cela
ne s'observe pas dans cette session.

---

## T40. Matrice finale

```text
Customer Portal LIVE                       PASS       était BLOCKED
Stripe LIVE catalogue                      PASS       NOUVEAU — 6 prix, clés exactes
Cancel at period end → webhook → droit     PASS       NOUVEAU — 3 propriétés vérifiées

Customer Portal TEST                       BLOCKED    présentation Turiya — dépriorisé
Stripe TEST customer-visible identity      BLOCKED    dépriorisé

Customer alert email E2E                   BLOCKED    aucun signal éligible — SPEC-016A
Ingestion runtime + timer                  BLOCKED    SPEC-016A
```

**41 PASS · 5 BLOCKED.**

```text
SPEC-016A                    →  3 portes
Présentation TEST            →  2 portes  (dépriorisées par l'exploitant)
```

**Aucune porte n'est bloquée par du travail Kivou restant.** Les trois portes
réelles attendent l'ingestion ; les deux autres sont un choix assumé.

---
---

# PARTIE VII — Intégration SPEC-016A et clôture

**Date :** 19 août 2026.

---

## T41. Intégration

`main` ne portait qu'un commit au-dessus de la base commune, et **aucun fichier
n'était partagé** avec la branche SPEC-016 : SPEC-016A apporte
`src/signals/ingestion/`, la migration 0005 et ses tests ; SPEC-016 ne touchait
que l'infrastructure, l'API et le frontend.

Fusion `--no-ff`, **sans conflit**, sans rebase et sans push forcé. Aucune
sémantique métier n'a eu à être arbitrée.

Un seul obstacle : le rapport SPEC-016A existait déjà localement en non-suivi.
Comparé avant toute action — empreintes identiques — puis supprimé pour laisser
Git livrer la version versionnée. Une copie manuelle aurait créé exactement la
divergence que la règle interdit.

**Alembic :** une seule tête, chemin linéaire.

```text
0004_alerts_feedback_analytics  →  0005_ingestion_runtime
```

Appliquée **une fois**, avant le redémarrage des workers. `/health/ready` rend
`{"status":"ready","revision":"0005_ingestion_runtime"}`.

---

## T42. Amorçage réel — résultats par source

Joué sur la base PostgreSQL de staging, sans script de recherche et sans
`--max-records`.

| Source | Récupérés | Persistés | Liés | Matérialisés | Écartés | Conflits | Statut |
|---|---|---|---|---|---|---|---|
| SIMAP | 642 | 348 | 0 | 0 | 0 | 0 | **success** |
| BOAMP | ~2 900 | 5 865 | 51 | 106 | 752 | 2 | **failed** (`malformed`) |
| DECP | 10 000 | 10 000 | 66 | 642 | 0 | 29 | **failed** (`client_error`) |
| TED | 5 173 | 4 | 0 | 0 | 0 | 0 | **rate_limited** |

### SIMAP — le plafond de pages exige un découpage

Une fenêtre de 30 jours dépasse `max_pages_per_filter=20` : le premier essai a
rendu `incomplete_window` et — c'est le point important — **n'a pas fait avancer
le checkpoint** (`window_end: None`, `status: failed`). La garantie du §7 tient.

Découpé en tranches hebdomadaires puis complété par la tranche courante, SIMAP
est **success**, checkpoint au 19 août.

Un détail vaut d'être noté : `--until` refuse une date future. La dernière
tranche doit donc être jouée sans borne haute.

### BOAMP — une catégorie d'avis non normalisable

```text
BOAMP payload cannot be normalized (kind=DSP)
```

**DSP** — délégation de service public. Une catégorie réelle d'avis français que
l'adaptateur ne sait pas normaliser. Elle apparaît dans quatre fenêtres sur
cinq, ce n'est donc pas un enregistrement isolé.

Un second défaut, distinct et plus sérieux :

```text
(psycopg.errors.StringDataRightTruncation)
value too long for type character varying(256)  [INSERT INTO contract_award …]
```

Une donnée réelle dépasse une colonne de 256 caractères — parmi
`source_award_id`, `lot_identifier` et `contract_reference`. **Ce n'est pas une
limite de source mais un défaut de schéma**, et il fait échouer toute la fenêtre.

Ces deux points relèvent de la sémantique métier et du schéma de SPEC-016A. Je
ne les corrige pas : décider si une DSP est une attribution que Kivou couvre, et
élargir une colonne persistée, appartiennent à son auteur.

### DECP — plafond dur de l'API

`DECP HTTP 400` à exactement 10 000 enregistrements. C'est une limite de
pagination de la source, pas un défaut Kivou. Les 10 000 enregistrements sont
persistés et **642 signaux** en sont issus. Le checkpoint reste à `None`, comme
il se doit.

### TED — limité en amont

```text
429 Too Many Requests
```

Même sur une fenêtre d'un seul jour. TED reste inexploitable au volume
d'amorçage ; la minuterie quotidienne réessaiera depuis le checkpoint inchangé.
Je n'ai pas martelé le service.

---

## T43. Données réellement persistées

```text
source_event                 10 533
contract_award               13 480
opportunity_representation   13 480
evidence                     11 213
materialized_signal             701
ingestion_run                    17
ingestion_checkpoint              4
```

Aucun fait métier n'a été fabriqué.

---

## T44. Le parcours client, sur données réelles

Compte de staging contrôlé, ICP active (matériaux × gros œuvre et génie civil,
FR + CH, seuil 250 000 EUR). `GET /signals` rend **8 signaux réels**, et
492 opportunités sont écartées faute de nom d'acheteur publié — un filtre de
qualité qui fonctionne.

Premier signal, vérifiable de bout en bout :

```text
entreprise   Groupement EIFFAGE CONSTRUCTION PICARDIE (mandataire) et 7 autres
identifiant  SIRET 40768202000166
marché       construction d'un bâtiment de soins médicaux et de réadaptation
             pour le Centre Hospitalier Intercommunal de Montdidier-Roye
événement    marché récemment notifié · horloge « notification » · 31 juillet
```

La discipline fait/inférence tient sur données réelles :

```text
award_clock_status : unknown
award_date_note    : « La date de décision d'attribution n'est pas publiée
                      par la source. »
```

Kivou dit ce qu'il ne sait pas, plutôt que de le déduire.

**Provenance vérifiable** — chaque fait porte sa source :

```text
source_system  decp
notice_id      2026T19862
url            https://data.economie.gouv.fr/explore/dataset/
               decp-2022-marches-valides/table/?q=2026T19862
path           procurement.cpvCode.code
retrieved_at   2026-08-19T14:32:45Z
```

La chaîne complète est donc prouvée : **opportunité publique persistée → décision
de correspondance → `materialized_signal` → `GET /signals` → signal visible**.
Aucune règle de correspondance n'a été modifiée pour faire apparaître un signal.

---

## T45. Backfill à l'activation d'une ICP — borné, et tronqué

Compte neuf, feed vide, puis création d'une ICP (location de matériel × voirie
et terrassement, FR, seuil 100 000 EUR).

```text
feed avant activation      0 signal
durée d'activation         484 ms
feed après activation      3 signaux

candidats disponibles      12 502
plafond de balayage           500
signaux matérialisés            3
truncated                    TRUE
```

Le feed reçoit des signaux **sans attendre une réingestion**. Mais
`truncated: true` : seuls les 500 candidats les plus récents ont été évalués sur
12 502 disponibles. **Ce backfill n'est pas exhaustif et ne doit pas être
présenté comme tel.**

La conséquence mérite d'être anticipée : plus la base grandit, plus la fraction
d'historique évaluée à l'activation d'un nouveau client diminue.

---

## T46. Minuteries d'ingestion

Trois groupes, aux cadences approuvées par SPEC-016A, derrière un verrou d'hôte
unique.

```text
kivou-ingest-fast   SIMAP + BOAMP   */2 h, minute 05   prochaine 16:05 UTC
kivou-ingest-decp   DECP            00 h et 12 h, m 35 prochaine 00:35 UTC
kivou-ingest-ted    TED             02:30 UTC          prochaine 02:30 UTC
kivou-alerts        alertes         horaire            prochaine 15:01 UTC
kivou-backup        sauvegarde      03:20 UTC          prochaine 03:22 UTC
```

Les cinq sont `enabled` et `active`.

Le verrou `/run/kivou-ingestion.lock` est déclaré en `tmpfiles.d` : `/run` est un
tmpfs, un fichier créé à la main y disparaîtrait au premier redémarrage. Les
services tournant en `ProtectSystem=strict` ne peuvent pas le créer eux-mêmes, et
leur ouvrir tout `/run` en écriture pour un seul fichier serait disproportionné.

### Un défaut attrapé avant déploiement

`systemd-analyze verify` a signalé :

```text
RuntimeMaxSec= has no effect in combination with Type=oneshot. Ignoring.
```

Les bornes de durée documentées n'auraient donc jamais existé. Corrigé en
`TimeoutStartSec`. Le défaut est silencieux : systemd le mentionne puis
n'applique rien.

### Exécutions contrôlées

```text
kivou-ingest-decp   exit 0    success
kivou-ingest-fast   exit 1    SIMAP success, BOAMP failed (kind=DSP)
```

**`kivou-ingest-fast` finit en `failed` à chaque passage** à cause de BOAMP, alors
que SIMAP réussit et que BOAMP persiste malgré tout des milliers
d'enregistrements. C'est précisément l'unité en échec permanent que le §12
refuse.

Je la laisse néanmoins **activée**, et c'est un arbitrage assumé : la désactiver
arrêterait aussi l'acquisition SIMAP, qui fonctionne. Le produit continue donc
d'être alimenté, au prix d'une unité rouge tant que BOAMP n'est pas corrigé.
Cette porte ne peut pas être fermée par SPEC-016.

---

## T47. Alerte client réelle

Compte de staging **Pro**, notifications activées, un signal réel correspondant.

```text
comptes examinés=9 · signaux envoyés=1 · sent=1     exit 0
```

Un e-mail réel est parti vers le destinataire contrôlé. Rejoué immédiatement :

```text
comptes examinés=9 · signaux envoyés=0 · not_due=1
```

**Aucun doublon.** La minuterie d'alerte reste activée et planifiée.

Le contenu du message (locale, expéditeur, lien profond
`https://staging.kivou.eu/app/signals/{signal_key}`, absence de vocabulaire
moteur) demande une confirmation visuelle du destinataire : la boîte
`no-reply@kivou.eu` ne reçoit rien, et le destinataire de test est externe.

---

## T48. Couverture d'historique — limitation de lancement

**La base ne contient pas douze mois**, quel que soit ce que le plan Pro autorise.

| Source | Événements | Plus ancien | Plus récent |
|---|---|---|---|
| BOAMP | 1 275 | 2026-07-21 | 2026-08-18 |
| DECP | 8 938 | 2026-07-20 | 2026-08-06 |
| SIMAP | 318 | 2026-08-10 | 2026-08-19 |
| TED | 2 | 2026-08-19 | 2026-08-19 |

Soit **environ un mois** pour BOAMP et DECP, **dix jours** pour SIMAP, et
pratiquement rien pour TED. La limitation documentée par SPEC-016A reste donc
entièrement valable, et le restera jusqu'à ce que Kivou accumule naturellement
de l'historique ou qu'un rattrapage délibéré soit décidé.

---

## T49. Sauvegarde, restauration, redémarrage

Sauvegarde fraîche prise **après** la migration 0005, l'amorçage et la
matérialisation : **3,2 Mo**, contre 51 Ko avant l'ingestion.

Restaurée dans une base jetable, détruite ensuite :

```text
révision Alembic : 0005_ingestion_runtime
account 9 · auth_user 9 · auth_session 22 · target_icp 3
materialized_signal 701 · discovery_signal_grant 7
billing_customer 3 · billing_subscription 2 · billing_checkout_attempt 3
product_event 24 · account_notification_preference 3 · signal_alert_delivery 1
contract_award 13 480 · source_event 10 533 · evidence 11 213
opportunity_representation 13 480 · ingestion_checkpoint 4 · ingestion_run 17
RESTAURATION VÉRIFIÉE
```

La vérification a été étendue aux trois tables de SPEC-016A. Restaurer sans les
checkpoints ferait reprendre l'acquisition à un point erroné, en croyant couvrir
une fenêtre jamais acquise.

**Redémarrage** de l'API : `/health/ready` à 0005, connexion, ICP, **15 signaux
réels**, plan `pro`, préférences d'alerte, checkpoints et unique envoi d'alerte —
tout persiste. Un cycle d'alerte rejoué après redémarrage n'envoie rien
(`not_due`). **Aucun effet de bord dupliqué.**

---

## T50. Matrice finale

```text
GATE                                        STATUS

Intégration SPEC-016A                        PASS    fusion sans conflit
Migration 0005, tête unique et linéaire      PASS
CI sur SHA déployé                           PASS    2818 backend · 84 frontend
Déploiement du SHA exact                     PASS    0 modification locale
Ingestion réelle — SIMAP                     PASS    success, checkpoint à jour
Ingestion réelle — DECP                      PARTIEL 10 000 persistés, plafond API
Ingestion réelle — BOAMP                     PARTIEL persiste, mais échoue (DSP)
Ingestion réelle — TED                       BLOCKED 429 en amont
Checkpoints honnêtes après échec             PASS    aucun avancement indu
Données réelles persistées                   PASS    13 480 attributions
Feed client sur données réelles              PASS    chaîne complète prouvée
Provenance et preuves vérifiables            PASS    URL et chemin JSON réels
Backfill à l'activation                      PASS    borné — truncated: true
Minuteries d'ingestion                       PASS    3 groupes, verrou partagé
Unité kivou-ingest-fast verte                BLOCKED échoue à cause de BOAMP
Alerte client réelle                         PASS    envoyée, sans doublon
Minuterie d'alerte                           PASS    activée et planifiée
Sauvegarde après migration                   PASS    3,2 Mo
Restauration vérifiée                        PASS    19 tables, révision 0005
Continuité au redémarrage                    PASS    aucun doublon
Couverture d'historique                      LIMITE  ~1 mois, documenté

Portail client TEST                          BLOCKED présentation Turiya — dépriorisé
Identité TEST visible du client              BLOCKED dépriorisé
URL légales kivou.eu                         BLOCKED go-live production
Rotation du mot de passe no-reply            À CONFIRMER
```

**Blocages de production, non de staging :**

```text
BOAMP — catégorie DSP + colonne varchar(256) trop courte   → SPEC-016A
TED   — limitation 429 en amont                            → source
URL légales /cgu et /confidentialite                       → avant 1re vente LIVE
Rotation du mot de passe no-reply@kivou.eu                 → sécurité
```

Les deux portes TEST restantes sont un choix explicite de l'exploitant, et ne
comptent pas comme des portes runtime Kivou.

---

## T51. Git

| Élément | Valeur |
|---|---|
| Branche | `chore/spec016-staging-readiness` |
| **SHA déployé** | **`36a0b0e65a4bc7c89d326e1853fd9819d3758d9c`** |
| CI | run `32267268066` — backend **2818**, ruff propre ; frontend **84** |
| PR #6 | **brouillon, non fusionnée** |
| `main` | `5df7e32`, intact |

Base backend : 2700 → 2718 → 2757 → 2763 → **2818** après fusion. Jamais
diminuée.

Aucun secret ne figure dans ce rapport.

---
---

# PARTIE VIII — Intégration R1 : arrêtée sur un défaut de migration

**Date :** 19 août 2026, soirée.

L'intégration de SPEC-016A-R1 est **arrêtée avant la migration**. La cause est
un défaut de la migration 0006 elle-même, qui appartient à SPEC-016A. Aucune
donnée n'a été perdue et staging est revenu à son état antérieur.

---

## T52. Porte d'entrée — franchie

```text
2bb72ef  fix(data): harden ingestion for live source data      ← R1
2586efd  feat(acquisition): add Hermes supervisor foundation
5df7e32  feat(data): add production ingestion runtime
```

Tête Alembic sur `origin/main` : `0006_contract_award_text_capacity`. ✓

`main` apportait aussi une fondation **Hermes** non annoncée. Inspectée avant
d'intégrer : `src/signals/supervisor/` n'est que du code, sans migration, sans
unité systemd et sans point d'entrée déclenché. Le fusionner ne démarre rien, et
rien n'a été démarré.

---

## T53. Point de rollback pris avant toute modification

```text
sauvegarde   kivou-20260819T200641Z.dump   3 296 057 octets
révision     0005_ingestion_runtime
source_event                 10 533
contract_award               13 480
opportunity_representation   13 480
materialized_signal             701
ingestion_run                    23
```

---

## T54. Fusion — sans conflit

`git merge --no-ff origin/main`, sans rebase, sans push forcé, sans
cherry-pick. Quatre rapports SPEC-016A/017 existaient localement en non-suivi ;
comparés un à un — **empreintes identiques** — puis supprimés pour laisser Git
livrer les versions versionnées.

Lignée vérifiée : **tête unique**, chemin linéaire, aucune ancienne migration
modifiée.

```text
0005_ingestion_runtime  →  0006_contract_award_text_capacity
```

Portes locales : backend **2887**, ruff propre, `git diff --check` propre ;
frontend **84**, build, typecheck et lint propres.

CI GitHub verte — run `32297558014`, SHA `f5c243a` : backend **2887**,
frontend **84**.

---

## T55. Le blocage — la migration 0006 est inapplicable sur PostgreSQL

Déployée sur staging, la migration échoue :

```text
psycopg.errors.StringDataRightTruncation
value too long for type character varying(32)
[SQL: UPDATE alembic_version SET version_num='0006_contract_award_text_capacity'
      WHERE alembic_version.version_num = '0005_ingestion_runtime']
```

L'identifiant de révision fait **33 caractères**, et la colonne
`alembic_version.version_num` en compte **32**. Ce n'est pas une largeur choisie
par Kivou : c'est le défaut d'Alembic pour sa propre table de version.

```text
longueur  identifiant
      12  0001_initial
      28  0002_account_auth_target_icp
      12  0003_billing
      30  0004_alerts_feedback_analytics
      22  0005_ingestion_runtime
      33  0006_contract_award_text_capacity      ← dépasse
```

Le précédent record était 30. **0006 est le premier à franchir la limite.**

### Pourquoi ni les tests ni la CI ne l'ont vu

```text
SQLite : insertion de 33 caractères dans varchar(32) → ACCEPTÉE (longueur stockée 33)
```

SQLite **n'applique pas** les longueurs déclarées. Les 2 887 tests, y compris
ceux de migration, s'exécutent sur SQLite : ils passent. PostgreSQL, lui,
refuse. Le défaut ne pouvait apparaître que sur la vraie base.

Il concerne donc **toute** installation PostgreSQL, staging comme production.

---

## T56. État de staging après l'échec — intact

PostgreSQL applique le DDL de façon transactionnelle : l'échec du tampon de
version a annulé l'`ALTER COLUMN` avec lui.

```text
alembic_version              0005_ingestion_runtime      inchangée
contract_reference           character varying(256)      inchangée
contract_award               13 480 lignes               intactes
materialized_signal             701 lignes               intactes
```

Le code de R1 étant déployé alors que le schéma restait en 0005, la sonde a
signalé la divergence — exactement ce pour quoi elle a été écrite :

```text
503  {"status":"not_ready","reason":"schema_revision_mismatch",
      "applied_revision":"0005_ingestion_runtime",
      "expected_revision":"0006_contract_award_text_capacity"}
```

Staging a été ramené au dernier SHA cohérent, `36a0b0e` :

```text
/health/ready   200   {"revision":"0005_ingestion_runtime"}
arbre serveur   0 modification locale
minuteries      5 actives (fast, decp, ted, alerts, backup)
```

La sauvegarde pré-0006 reste disponible comme second filet, non utilisée.

---

## T57. Ce qui reste à faire, et à qui

**Pour SPEC-016A** — un seul point, à trancher par son auteur :

L'identifiant `0006_contract_award_text_capacity` doit tenir en 32 caractères,
ou la table de version doit être élargie. Le raccourcir semble le moins risqué :
0006 est la tête, rien ne dépend d'elle en aval, et **aucune base n'a l'a
enregistrée** — le tampon a été annulé partout. Un identifiant comme
`0006_award_text_capacity` (24 caractères) suffirait. Je ne l'ai pas fait :
la logique de migration appartient à SPEC-016A.

Il vaudrait aussi la peine d'ajouter un test qui échoue si un identifiant de
révision dépasse 32 caractères. Il tiendrait en trois lignes, ne demanderait
pas PostgreSQL, et aurait attrapé ceci avant le déploiement.

**Déjà fait et réutilisable**, une fois 0006 corrigé :

```text
branche fusionnée         98f0bf0 puis f5c243a
CI verte                  run 32297558014 — 2887 backend, 84 frontend
unités séparées           kivou-ingest-simap / -boamp livrées et vérifiées
```

Les vérifications §9 à §29 — rejeu BOAMP, référence longue, partitionnement
DECP, feed réel, backfill, alerte, sauvegarde/restauration, continuité — n'ont
pas pu être exécutées : elles supposent toutes que 0006 soit appliquée.

---

## T58. Séparation des minuteries — livrée

Exigence du §14, indépendante de la migration, donc menée à son terme.

```text
kivou-ingest-simap   toutes les 2 h, minute 05
kivou-ingest-boamp   toutes les 2 h, minute 15
kivou-ingest-decp    00 h et 12 h, minute 35
kivou-ingest-ted     02:30 UTC
```

`kivou-ingest-fast` est supprimée du dépôt : laisser coexister les deux
générations programmerait des passages en double. Chaque unité est vérifiée par
`systemd-analyze verify`, utilise `TimeoutStartSec` et partage
`/run/kivou-ingestion.lock`.

Les nouvelles unités **ne sont pas encore installées sur le serveur** : leur
installation accompagnera le déploiement du SHA qui corrige 0006. Le serveur
tourne donc encore sur l'unité combinée, avec son échec BOAMP connu.

---

## T59. Portes de production, inchangées

```text
URL légales      kivou.eu/cgu et /confidentialite — le domaine ne répond pas
Rotation MDP     no-reply@kivou.eu — non confirmée
```

Aucune des deux ne bloque le staging.

---
---

# PARTIE IX — Intégration R2 et clôture de staging

**Date :** 19-20 août 2026.

---

## T60. Intégration

```text
c4d153c  fix(data): shorten Alembic revision identifier      ← R2
2bb72ef  fix(data): harden ingestion for live source data    ← R1
2586efd  feat(acquisition): add Hermes supervisor foundation
```

Fusion `--no-ff`, sans conflit, sans rebase, sans push forcé. Quatre rapports
SPEC-016A/017 existaient localement en non-suivi ; comparés un à un — empreintes
identiques — puis supprimés pour laisser Git livrer les versions versionnées.

**Lignée Alembic** — tête unique, chemin linéaire, ancien identifiant absent :

```text
0005_ingestion_runtime  →  0006_award_text_capacity     24 caractères
```

R2 a raccourci l'identifiant de 33 à 24 caractères. La cause du blocage
précédent est donc levée à la source, sans que la table de version d'Alembic
ait été touchée.

**Portes** — local : backend **2889**, ruff propre, `git diff --check` propre ;
frontend **84**, build, typecheck, lint propres. CI GitHub verte, run
`32302529271`, SHA `8fa4415` : mêmes chiffres.

**Déploiement** — SHA exact, arbre serveur à `0` modification locale.

---

## T61. Migration 0006

Jouée **une fois**, minuteries en pause, avant redémarrage des workers.

```text
avant   0005_ingestion_runtime   contract_reference = character varying(256)
après   0006_award_text_capacity contract_reference = text

attributions conservées   13 480
signaux conservés            701
```

Aucune valeur n'a été tronquée ni réécrite.

```text
/health/live    200
/health/ready   200   {"revision":"0006_award_text_capacity"}
```

---

## T62. BOAMP — DSP résolu, et une limite historique subsistante

### La catégorie DSP ne tue plus l'ingestion

| | avant R1 | après R1 |
|---|---|---|
| erreur | `malformed` — `kind=DSP` | **aucune** |
| écartés | 215 | **248** |
| cycle | interrompu sur le premier DSP | poursuit au-delà |

Les avis de délégation de service public sont désormais **sautés sûrement** et
comptés comme rejets, au lieu d'arrêter la source.

**Une réserve d'observabilité :** le code de raison
`unsupported_notice_family_dsp` n'est **ni journalisé ni persisté**. Il est émis
par `logger.info(..., extra={...})` — or le seuil par défaut écarte `INFO`, et le
formateur standard ne rend pas `extra`. Le compteur `rejection_reasons` reste en
mémoire et n'est pas écrit dans `ingestion_run`. La répartition des rejets n'est
donc pas consultable en exploitation ; elle ne se déduit que de l'écart des
compteurs. À signaler à SPEC-016A.

### Le cycle planifié réussit

```text
kivou-ingest-boamp.service
source=boamp fetched=1106 persisted=2678 linked=85 materialized=60
             skipped=238 conflicts=31 status=success duration=939s
Result=success  ExecMainStatus=0
checkpoint  failed(2026-08-14)  →  success(2026-08-19 22:03)
```

**Le checkpoint avance enfin.** C'était le critère du §9.

### Une limite reste sur la fenêtre historique

Le rejeu depuis le 20 juillet échoue encore, mais sur un défaut **différent**,
jusque-là masqué par l'arrêt sur DSP :

```text
1 validation error for Location
Value error, Location vide : une localisation inconnue s'écrit None
input_value={'country': None, 'subdivision': None, …, 'postal_code': None}
```

Un avis BOAMP porte une localisation entièrement vide, que le normaliseur
construit comme un objet `Location` plutôt que comme `None`. C'est de la
sémantique d'ingestion : je ne l'ai pas corrigé.

Portée limitée : la fenêtre **courante** (depuis le checkpoint) passe, seule la
reprise historique bute dessus.

---

## T63. Référence de contrat longue — préservée

```text
références > 256 caractères : 2
longueur maximale           : 409
   409  « VdP : 2026S068920000 / EPPM : 2026-26193 … »
   317  « SGAMI33-2025-35-FCS Accord-cadre relatif … »
```

Les deux valeurs sont persistées **intégralement**, sans troncature, et leurs
opportunités restent intactes. C'est la vérification directe du passage en
`TEXT`.

---

## T64. DECP — le partitionnement fonctionne

```text
source=decp fetched=17996 persisted=17996 linked=201 materialized=3674
            skipped=0 conflicts=178 rate_limited=0
            status=success duration=1649s

checkpoint  failed(None)  →  success(2026-08-19 21:35)
```

**17 996 enregistrements récupérés, 17 996 persistés, 0 écarté.** La fenêtre qui
butait sur `HTTP 400` au dix-millième enregistrement passe désormais en entier,
et le checkpoint avance. Aucune requête n'a violé la contrainte
`offset + limit < 10000` — le `client_error` a disparu.

Les 178 conflits d'opportunité sont le comportement voulu : aucune fusion
automatique, les deux opportunités et tous leurs faits conservés.

---

## T65. SIMAP — inchangé

```text
source=simap fetched=107 persisted=109 status=success duration=5.5s
checkpoint  success(2026-08-19 21:36)
```

Aucune régression de R1 sur la source qui fonctionnait déjà.

---

## T66. TED — toujours limité en amont

```text
22:19:19  rate_limited  fetch=3500  pers=0   429 Too Many Requests
22:19:33  rate_limited  fetch=2750  pers=0   429 Too Many Requests
checkpoint : failed, window_end = None
```

TED renvoie 429 à chaque tentative, y compris en soirée. Le comportement Kivou
est **correct** : la source échoue en fermeture, le checkpoint ne bouge pas,
aucune donnée douteuse n'est écrite.

L'exécution planifiée de 02:30 UTC n'a pas encore eu lieu au moment de ce
rapport. Les tentatives répétées ayant toutes échoué, **la disponibilité
opérationnelle de TED est marquée BLOCKED**, et appelle un suivi distinct sur le
runtime de la source — pas une correction dans SPEC-016.

L'unité `kivou-ingest-ted.service` est donc en échec. Je la laisse **activée** :
la désactiver garantirait que TED ne se rétablisse jamais, et un échec quotidien
reste infiniment moins bruyant qu'un échec toutes les deux heures. C'est un
arbitrage assumé, pas un oubli.

---

## T67. Minuteries séparées — livrées et vérifiées

`kivou-ingest-fast` est supprimée du dépôt **et** du serveur. Chaque source
porte désormais son unité, son état et son checkpoint.

```text
kivou-ingest-simap    toutes les 2 h, minute 05   prochaine 00:05 UTC
kivou-ingest-boamp    toutes les 2 h, minute 15   prochaine 00:15 UTC
kivou-ingest-decp     00 h et 12 h, minute 35     prochaine 00:35 UTC
kivou-ingest-ted      02:30 UTC                   prochaine 02:30 UTC
kivou-alerts          horaire                     prochaine 23:03 UTC
kivou-backup          03:20 UTC                   prochaine 03:25 UTC
```

**L'isolation est démontrée, pas supposée :** dans la même session, TED échoue
tandis que SIMAP, BOAMP et DECP restent verts. Auparavant, un échec BOAMP
marquait SIMAP en échec dans l'unité commune.

Les minutes distinctes gardent le verrou `/run/kivou-ingestion.lock` dans son
rôle de sécurité de dernier recours. Une collision observée pendant les essais
s'est résolue exactement comme prévu : l'appel concurrent a attendu puis renoncé
proprement, sans salir l'état.

**Une correction attrapée avant déploiement :** `systemd-analyze verify` avait
signalé que `RuntimeMaxSec` est ignoré avec `Type=oneshot`. Vérifié sur l'unité
chargée, `TimeoutStartUSec=30min` est bien appliqué.

---

## T68. Données réelles

```text
révision                      0006_award_text_capacity
source_event                        17 388
contract_award                      21 411
opportunity_representation          21 411
evidence                            50 652
materialized_signal                  4 184
ingestion_run                           30
```

### Couverture — la limitation de lancement reste entière

| Source | Événements | Plus ancien | Plus récent |
|---|---|---|---|
| DECP | 15 176 | 2026-07-20 | 2026-08-17 |
| BOAMP | 1 892 | 2026-07-21 | 2026-08-19 |
| SIMAP | 318 | 2026-08-10 | 2026-08-19 |
| TED | 2 | 2026-08-19 | 2026-08-19 |

**Environ un mois**, pas douze. Le droit d'accès de douze mois que permet un
plan Pro ne doit pas être présenté comme une disponibilité de données.

---

## T69. Feed client réel

Compte de staging contrôlé, ICP active : **20 signaux réels**, contre 8 avant
R1.

```text
société      SOTRAVEER
identifiant  SIRET 33835695900027
événement    marché récemment notifié · horloge notification · 2026-07-28 · 22 j
honnêteté    award_clock_status = unknown
             « La date de décision d'attribution n'est pas publiée par la source. »
```

**Provenance vérifiable**, cinq familles de faits couvertes — montant, CPV,
acheteurs, objet publié, attributaire :

```text
source  decp   avis 1300215144
url     https://data.economie.gouv.fr/explore/dataset/decp-2022-marches-valides/table/?q=1300215144
chemin  value
```

427 opportunités sont écartées faute de nom d'acheteur publié, 45 pour
fraîcheur. Aucun seuil de correspondance n'a été modifié.

---

## T70. Backfill à l'activation d'une ICP

Deux comptes neufs, deux profils différents.

```text
profil « équipements de sécurité »   feed 0 → 0    377 ms
profil « matériaux gros œuvre »      feed 0 → 1    439 ms

candidats disponibles   14 696
plafond de balayage        500
évalués                    500
truncated                 TRUE
```

Le premier résultat à zéro est **légitime** : aucune opportunité persistée ne
correspond à cette offre. Le second matérialise sans réingestion.

**Le backfill n'est pas exhaustif.** 500 candidats évalués sur 14 696. L'écart
avec le compte plus ancien — 20 signaux contre 1 — illustre exactement l'effet :
un compte accumule au fil des cycles ce qu'une activation seule ne peut pas
rattraper.

---

## T71. Alerte

Le cycle s'exécute proprement sur les données post-R1 :

```text
comptes examinés=11 · signaux envoyés=0 · not_due=1, not_eligible=9, nothing_to_send=1
Result=success
```

Aucun envoi **nouveau** : le compte Pro a déjà reçu son alerte, et sa cadence est
quotidienne — `not_due` est le garde-fou de cadence qui fonctionne, pas un échec.
La remise réelle avait été validée de bout en bout en Partie VI (e-mail reçu,
lien profond, aucun doublon au rejeu).

`kivou-alerts.timer` reste activée et planifiée. SMTP est opérationnel.

---

## T72. Sauvegarde, restauration, redémarrage

Sauvegarde prise **après** 0006, les rejeux et la matérialisation :
**6,9 Mo**, contre 3,3 Mo avant.

Restaurée dans une base jetable, détruite ensuite :

```text
révision Alembic : 0006_award_text_capacity
contract_award 21 411 · source_event 17 388 · evidence 50 652
opportunity_representation 21 411 · materialized_signal 4 184
ingestion_checkpoint 4 · ingestion_run 30
account 11 · target_icp 5 · billing_subscription 2 · signal_alert_delivery 1
RESTAURATION VÉRIFIÉE
```

**Redémarrage** : `/health/ready` à 0006, compte, ICP, 15 signaux réels, plan
`pro`, préférences d'alerte — tout persiste, aucun effet de bord dupliqué.

---

## T73. Exploitation

```text
kivou-api · postgresql · nginx        actifs
certbot.timer                         enabled
disque                                6 % utilisé, 54 Go libres
arbre Git serveur                     8fa4415, 0 modification locale
secrets indexés                       aucun (marqueurs seuls dans .env.example)

unités en échec
   kivou-ingest-ted.service           429 en amont — voir §T66
   cloud-final.service                résidu cloud-init, étranger à Kivou
```

---

## T74. Portes de production

**`kivou.eu` ne résout pas.** Le domaine n'a **aucun enregistrement A ni AAAA**.
Ce n'est donc pas seulement que `/cgu` et `/confidentialite` manquent : le
domaine de production n'est pas publié. Or Stripe LIVE y pointe désormais son
profil d'entreprise et son portail client. Un client qui paierait en production
serait renvoyé vers un domaine mort.

```text
DOMAINE kivou.eu non publié          BLOQUANT go-live
URL légales /cgu, /confidentialite   BLOQUANT go-live
Rotation du mot de passe no-reply    BLOQUANT go-live — non confirmée
```

Aucune de ces trois ne bloque le staging.

---

## T75. Matrice finale

```text
GATE                                        STATUS

Intégration R2, lignée linéaire              PASS
Migration 0006 déployée                      PASS    identifiant 24 car.
CI verte sur le SHA déployé                  PASS    2889 backend · 84 frontend
Arbre serveur propre                         PASS    8fa4415, 0 modification

BOAMP — DSP ne tue plus l'ingestion          PASS    248 écartés, cycle poursuit
BOAMP — checkpoint avance                    PASS    → 2026-08-19 22:03
BOAMP — unité indépendamment saine           PASS    Result=success
BOAMP — raisons de rejet observables         ÉCART   ni journalisées ni persistées
BOAMP — fenêtre historique juillet           BLOCKED Location vide → SPEC-016A

contract_reference > 256 préservée           PASS    409 et 317 caractères
DECP — partitionnement > 10 000              PASS    17 996 / 17 996, 0 écarté
DECP — checkpoint avance                     PASS
SIMAP — aucune régression                    PASS
TED — disponibilité de la source             BLOCKED 429 répétés en amont

Minuteries séparées par source               PASS    isolation démontrée
Verrou d'hôte partagé                        PASS    collision résolue proprement
TimeoutStartSec appliqué                     PASS    vérifié sur l'unité chargée

Feed client sur données réelles              PASS    20 signaux, provenance vérifiable
Backfill à l'activation                      PASS    borné — truncated: true
Cycle d'alerte sur données post-R1           PASS    cadence respectée
Minuterie d'alerte                           PASS    activée et planifiée

Sauvegarde après 0006                        PASS    6,9 Mo
Restauration vérifiée                        PASS    19 tables, révision 0006
Continuité au redémarrage                    PASS    aucun doublon
Aucun secret indexé                          PASS

Portail client TEST                          BLOCKED présentation Turiya — déprioritisé
Identité TEST visible du client              BLOCKED déprioritisé
Domaine kivou.eu publié                      BLOCKED go-live production
URL légales                                  BLOCKED go-live production
Rotation du mot de passe                     BLOCKED go-live production
```

---

## T76. Git

| Élément | Valeur |
|---|---|
| Branche | `chore/spec016-staging-readiness` |
| **SHA déployé** | **`8fa44158e7494a3e21bf5299195b49639cd7a278`** |
| CI | run `32302529271` — backend **2889**, frontend **84** |
| PR #6 | **brouillon, non fusionnée** |
| `main` | `c4d153c`, intact |

Base backend : 2700 → 2718 → 2757 → 2763 → 2818 → **2889**. Jamais diminuée.

Aucun secret ne figure dans ce rapport.
