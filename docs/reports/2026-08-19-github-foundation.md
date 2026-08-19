# GITHUB-001 — Private Repository + CI Foundation

**Date :** 19 août 2026
**Verdict :** voir §16.

---

## 1. Entry gate

```text
43c41e2 feat(web): add Kivou frontend MVP          ← SPEC-015
7bdcdce feat(saas): add alerts feedback and analytics
1965c8a feat(saas): add Stripe billing and paywall
3757678 feat(saas): add customer signal feed
1d894eb feat(saas): add account auth and ICP onboarding
30d431c feat(saas): add signal persistence foundation
```

**SHA du commit SPEC-015 : `43c41e2989e46724198f81e34a6f87087a0bcdd9`.** Il est
en tête de `main` et suit bien les commits SaaS. Rien de SPEC-015 n'a été replié
dans ce travail.

---

## 2. Audit du dépôt local, avant toute poussée

| Élément | Valeur |
|---|---|
| Branche | `main` |
| HEAD | `43c41e2989e46724198f81e34a6f87087a0bcdd9` |
| Commits | **21** |
| Branches | `main` uniquement |
| Remotes avant | **aucun** |
| Fichiers suivis | 581 |
| Poids des fichiers suivis | 71,54 Mo |
| `.git` | 49 Mo |
| Arbre de travail hors `.git`/`node_modules` | 219 Mo |
| `frontend/node_modules` (ignoré) | 133 Mo |

L'historique n'a **pas** été recréé. Aucun `git init`, aucun `--orphan`, aucun
écrasement : les 21 commits d'origine sont ceux qui sont sur GitHub.

### Les 20 plus gros fichiers suivis

| Taille | Fichier |
|---:|---|
| 11,13 Mo | `docs/designPattern/…/docs/KIVOU_DESIGN_SYSTEM_v1.0.docx` |
| 7,59 Mo | `tests/fixtures/signal100/spec009c_corpus.json` |
| 3,62 Mo | `tests/fixtures/signal100/spec009c_bench.json` |
| 2,82 Mo | `tests/fixtures/documents/fr_dce_final_candidates.json` |
| 2,80 Mo | `tests/fixtures/signal100/signal100_corpus.json` |
| 2,56 Mo | `tests/fixtures/signal100/signal100_pool_corpus.json` |
| 1,83 Mo | `tests/fixtures/documents/fr_dce_candidates_ext.json` |
| 1,81 Mo | `docs/designPattern/…/02-approved-direction-marketing-home.png` |
| 1,80 Mo | `tests/fixtures/documents/fr_dce_candidates.json` |
| 1,69 Mo | `docs/designPattern/…/07-approved-direction-illustrations.png` |
| 1,65 Mo | `docs/designPattern/…/01-approved-direction-saas-overview.png` |
| 1,61 Mo | `docs/designPattern/…/06-approved-direction-checkout.png` |
| 1,48 Mo | `docs/designPattern/…/05-approved-direction-internal-weekly-cockpit.png` |
| 1,48 Mo | `docs/designPattern/…/08-approved-direction-internal-funnel-table.png` |
| 1,40 Mo | `docs/reports/spec015-ui/01-landing--desktop-1440.png` |
| 1,39 Mo | `docs/designPattern/…/03-approved-direction-mobile.png` |
| 1,39 Mo | `docs/designPattern/…/04-approved-direction-client-signal-feed.png` |
| 1,17 Mo | `docs/reports/spec015-ui/13-landing-en--desktop-1024.png` |
| 1,04 Mo | `tests/fixtures/signal100/signal100_blind.json` |
| 1,00 Mo | `docs/reports/spec015-ui/01-landing--mobile-390.png` |

Le plus gros fichier fait 11,13 Mo, loin sous la limite de 100 Mo par fichier de
GitHub. **Aucun Git LFS introduit** — la poussée est passée sans avertissement
de taille, donc aucune migration spéculative n'était justifiée.

### Fichiers volontairement laissés NON SUIVIS

Ils préexistent à cette tâche et n'ont **pas** été ajoutés :

```text
Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx
Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx
docs/reports/2026-08-17-spec006-postmortem.md
docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md
src/signals/research/spec009c.py
src/signals/research/spec009c_run.py
tests/fixtures/signal100/spec009c_blind.json
tests/test_spec009c_bench.py
```

---

## 3. Audit de secrets — porte dure, franchie

Analyse par expressions régulières exigeant une **charge utile plausible** —
`sk_live_` seul est un préfixe cité dans du code, pas un secret. 18 familles
couvertes : clés Stripe (live/test/restricted/publishable), secrets de webhook,
PAT GitHub (classique, fine-grained, OAuth), blocs de clé privée, URL
PostgreSQL/MySQL avec mot de passe, clés AWS, jetons Slack, clés OpenAI et
OpenRouter, clés Apollo et Instantly, et une règle générique
`(password|secret|api_key|token) = "…"`.

| Périmètre | Objets analysés | Résultat |
|---|---:|---|
| Contenu suivi (HEAD) | 581 | **aucun secret réel** |
| **Historique complet** (tout blob jamais committé) | **668** | **aucun secret réel** |

Les seules correspondances sont la règle générique, sur cinq fichiers de test et
leurs révisions historiques. Vérification manuelle : il s'agit du même littéral
de fixture synthétique dans les trois cas
(`tests/feed_helpers.py`, `test_accounts_security.py`,
`test_accounts_target_icp.py`, `test_accounts_signal_binding.py`,
`test_accounts_migration_and_ownership.py`). Ce n'est pas un identifiant : c'est
un mot de passe d'essai assez long pour satisfaire la politique de longueur.

**Aucune réécriture d'historique n'a été nécessaire. Aucun secret n'a été
poussé.** Les fichiers indexés pour le commit de fondation ont été re-scannés
séparément avant commit : aucune correspondance.

---

## 4. `.gitignore`

Ajouts, tous vérifiés comme ne masquant **aucun** fichier suivi
(`git ls-files | git check-ignore` → vide) :

```gitignore
.env
.env.*
!.env.example          # seule variante suivie

.coverage / .coverage.* / coverage.xml / htmlcov/

*.dump *.sql.gz *.sqlite *.sqlite3 *.db *.bak

frontend/node_modules/
frontend/dist/

.DS_Store  Thumbs.db
```

Règles préexistantes conservées : `.venv/`, `__pycache__/`, `*.pyc`,
`.pytest_cache/`, `.ruff_cache/`, les deux gels bruts d'acquisition, et
`*:Zone.Identifier`.

`docs/designPattern/` **reste suivi** — vérifié dans le clone frais, tokens
compris. Aucun motif n'a été ajouté qui toucherait du code source, des
migrations, des sources de design ou des fixtures requises.

---

## 5. `.env.example`

**Créé.** Il documente les 19 variables réellement lues par le code, relevées
dans `src/signals/api/config.py` et `src/signals/persistence/database.py` — pas
une liste inventée. Une variable absente de ce fichier est une variable que le
code ne lit pas.

Base de données · session et CSRF · Stripe (mode, clés, les trois URL de retour
obligatoires, options) · base des liens profonds d'alerte · SMTP.

**Valeurs d'exemple uniquement**, vérifié par le même scanner de secrets : aucune
correspondance. Il est bien suivi malgré la règle `.env.*`, grâce à la négation
`!.env.example`.

---

## 6. Authentification et propriétaire GitHub

| Élément | Valeur |
|---|---|
| Mécanisme | **CLI `gh`** (le MCP GitHub du plugin est hors service, faute de `GITHUB_PERSONAL_ACCESS_TOKEN`) |
| Compte authentifié | `bruppacherrodrigue-art` (type **User**) |
| Dépôts existants | 19 — **aucun** nommé `kivou` sous quelque casse que ce soit |
| Remote local avant | aucun |

Aucun jeton n'est affiché dans ce rapport, ni embarqué dans l'URL du remote :
l'authentification passe par l'assistant d'identifiants de `gh`.

Le dépôt `gosimap-engine` du même compte est le prédécesseur du projet ; il
n'entre pas en conflit et n'a pas été touché.

---

## 7. Dépôt créé

| Élément | Valeur |
|---|---|
| Propriétaire | `bruppacherrodrigue-art` |
| Nom | **`Kivou`** — convention du compte pour un produit (cf. `Turiya`) |
| Visibilité | **PRIVATE** |
| URL | https://github.com/bruppacherrodrigue-art/Kivou |
| Description | Kivou — public procurement award intelligence and B2B sales signals. |
| Branche par défaut | `main` |
| Création | **vide** — ni README ni licence distants, donc aucun premier commit divergent |

Ni GitHub Pages, ni publication de paquets.

---

## 8. Remote, poussée et intégrité de l'historique

`origin` était inutilisé ; il a été ajouté en HTTPS, **sans identifiants dans
l'URL**.

Avant la poussée : `git status --porcelain` sans rien d'indexé,
`git diff --check` propre, HEAD = commit SPEC-015 approuvé.

```text
git push -u origin main   →  * [new branch]  main -> main
```

| Vérification | Résultat |
|---|---|
| SHA local `main` | `43c41e2989e46724198f81e34a6f87087a0bcdd9` |
| SHA distant `main` | `43c41e2989e46724198f81e34a6f87087a0bcdd9` |
| **Égalité** | **oui** |
| Commits sur le distant | **21** — historique complet préservé |
| Branche par défaut | `main` |

Aucun `--force`, aucun `--mirror`. Aucune branche détruite ni renommée : la
branche locale s'appelait déjà `main`.

---

## 9. CI

`.github/workflows/ci.yml` — déclenchée sur `pull_request` et `push` vers `main`.

```yaml
permissions:
  contents: read
```

Deux jobs, aucun secret, aucun service de base de données ou de réseau ajouté :
les suites sont hors ligne par conception.

**Backend** — `actions/checkout@v7`, `astral-sh/setup-uv@v10.0.1` (cache sur
`uv.lock`), puis `uv sync --locked`, `uv run pytest -q`, `uv run ruff check .`.
`--locked` échoue si le verrou ne correspond plus au manifeste : la CI teste les
versions verrouillées dans le dépôt, pas ce que PyPI publiait ce matin.

**Frontend** — `actions/setup-node@v7` en **Node 24** (cache npm sur
`frontend/package-lock.json`), puis `npm ci`, `npm test -- --run`,
`npm run build`, `npx tsc -b`, `npm run lint`. `npm ci` et jamais
`npm install`. `dist/` n'est pas committé.

Cache : uniquement les mécanismes intégrés aux actions officielles. Aucune
infrastructure d'artefacts maison.

### Un correctif a été nécessaire

Le premier run a échoué côté backend à l'étape « Set up job » :

```text
Unable to resolve action `astral-sh/setup-uv@v10`, unable to find version `v10`
```

Cause réelle : `astral-sh/setup-uv` ne publie **pas** de tag majeur flottant
au-delà de `v7` — seuls `v10.0.0` et `v10.0.1` existent. `actions/checkout` et
`actions/setup-node` en publient, ce qui explique que le job frontend soit passé
du premier coup. Corrigé en épinglant la version exacte `v10.0.1`, ce qui est de
toute façon la meilleure pratique.

C'est un défaut de la fondation GitHub, pas du produit. **Aucun test n'a été
affaibli, aucun échec autorisé.**

### Résultat

| Job | Résultat | Détail |
|---|---|---|
| Backend (Python 3.12 · uv) | **PASS** | `2700 passed in 345.40s` · `All checks passed!` |
| Frontend (Node 24 · npm) | **PASS** | `Tests 84 passed (84)` · build, typecheck, lint |

Run vérifié : `32203211945`, conclusion `success` sur les deux jobs.

---

## 10. Le nombre de tests backend — précision nécessaire

Le clone frais et la CI rapportent **2700** tests, là où mes rapports SPEC-015
annonçaient **2724**. L'écart est réel et s'explique entièrement :

```text
tests/test_spec009c_bench.py   →  24 tests  (fichier NON SUIVI, recherche SPEC-009C)
```

Vérifié par collecte :

```text
uv run pytest --collect-only -q                                    → 2724
uv run pytest --collect-only -q --ignore=tests/test_spec009c_bench.py → 2700
```

Donc :

* **2724** = arbre de travail local, fichiers de recherche non suivis compris ;
* **2700** = ce que contient le dépôt, et donc ce que la CI et tout clone
  exécutent.

Les rapports SPEC-015 n'étaient pas faux — ils mesuraient le poste local — mais
le chiffre de référence pour GitHub est **2700**. C'est celui qui doit servir de
base de non-régression désormais.

---

## 11. Reproductibilité depuis un clone frais

Clone neuf de `https://github.com/bruppacherrodrigue-art/Kivou.git` dans un
répertoire temporaire, sans réutiliser le poste de travail.

| Vérification | Résultat |
|---|---|
| SHA cloné | `43c41e2989e46724198f81e34a6f87087a0bcdd9` |
| Commits | 21 |
| Fichiers suivis | 581 |
| Pack de design présent | oui, tokens compris |
| Taille du clone | 114 Mo |
| `uv sync --locked` | OK |
| `uv run pytest -q` | **2700 passed** |
| `npm ci` | OK, 0 vulnérabilité |
| `npm test -- --run` | **84 passed** |
| `npm run build` | OK, polices `.woff2` auto-hébergées émises |

GitHub contient donc réellement tout ce qu'il faut pour construire et tester le
produit. Le clone temporaire a été supprimé.

---

## 12. Protection de branche — limitation de plan

**Les deux mécanismes sont refusés :**

```text
POST /repos/…/rulesets                    → 403
PUT  /repos/…/branches/main/protection    → 403

"Upgrade to GitHub Pro or make this repository public to enable this feature."
```

Le compte est un compte **User sur plan gratuit**, et le dépôt est **privé** :
GitHub réserve rulesets et protection de branche classique aux dépôts publics ou
aux plans payants. Ce n'est pas un problème de scope du jeton — c'est le plan.

Conformément à la consigne, **rien n'a été simulé**. La configuration la plus
forte réellement disponible a été appliquée :

| Mesure | État |
|---|---|
| Permissions par défaut des workflows | **`read`** (abaissé depuis `write`) |
| Actions autorisées à approuver des PR | **non** |
| Dépôt privé | oui — nul autre que le propriétaire ne pousse |
| Flux par PR | **documenté** dans `CONTRIBUTING.md`, **exercé** par la PR #1 |
| CI sur `pull_request` et `push` vers `main` | oui |
| GitHub Projects | désactivé |
| Wiki, Discussions, Pages | déjà désactivés |
| Issues | conservées — utiles au suivi |
| Interdiction du fork | impossible : réservée aux dépôts privés d'organisation |

**Ce qui manque, et qu'il faut savoir :** sur ce plan, rien n'empêche
techniquement une poussée directe ou une poussée forcée sur `main`. La discipline
est conventionnelle, pas appliquée par la plateforme.

Lever cette limite demande un **plan payant**, sans exception :

| Hébergement du dépôt | Dépôt public | Dépôt **privé** |
|---|---|---|
| GitHub Free (compte personnel) | rulesets disponibles | **non** |
| GitHub Free for organizations | rulesets disponibles | **non** |
| GitHub Pro (compte personnel) | oui | **oui** |
| GitHub Team / Enterprise (organisation) | oui | **oui** |

Autrement dit, transférer le dépôt à une organisation **gratuite** n'apporterait
rien : la gratuité d'organisation n'ouvre les rulesets que sur les dépôts
publics, exactement comme un compte personnel gratuit. Les seules voies réelles
sont **GitHub Pro** pour un dépôt personnel, ou **GitHub Team/Enterprise** pour
un dépôt d'organisation.

**Décision du superviseur :** le dépôt reste **privé sous le compte personnel
actuel**, sans transfert vers une organisation et sans montée de plan. L'absence
de protection appliquée **ne bloque pas** le staging. Elle devra être réexaminée
**avant qu'une automatisation quelconque reçoive un droit d'écriture GitHub** ;
jusque-là, aucune automatisation ne reçoit de jeton d'écriture ni
d'administration.

---

## 13. Sécurité et Dependabot

| Fonction | État réel |
|---|---|
| Alertes Dependabot | **activées** |
| Correctifs de sécurité automatiques | **activés** (`enabled: true, paused: false`) |
| Graphe de dépendances | actif — **373 paquets** détectés : 322 npm, 50 PyPI, 1 GitHub Actions |
| Secret scanning | **indisponible** — `422 Secret scanning is not available for this repository` |
| Push protection | **indisponible** — dépend du secret scanning |
| Signalement privé de vulnérabilité | **indisponible** — `404` |

Secret scanning et push protection exigent GitHub Advanced Security, hors du
plan gratuit sur dépôt privé. **Aucune de ces fonctions n'est présentée comme
active alors qu'elle ne l'est pas.**

### Dependabot — décision

`.github/dependabot.yml` déclare **trois** écosystèmes, cadence hebdomadaire,
limites de PR ouvertes, **sans fusion automatique** :

* `npm` sur `/frontend` — dépendances de développement groupées ;
* `github-actions` sur `/` ;
* `uv` sur `/` — **conservé**.

Le support `uv` a été vérifié empiriquement plutôt que supposé : dès l'activation
des alertes, GitHub a lancé un job interne `update-uv-graph` et le SBOM du dépôt
liste **50 paquets PyPI** issus de `uv.lock`. L'écosystème est donc bien analysé,
et il n'y avait aucune raison d'omettre l'automatisation Python.

**Réserve :** Dependabot lit sa configuration sur la **branche par défaut**. Le
fichier vit pour l'instant sur la branche de fondation ; il ne prendra effet
qu'à la fusion de la PR #1.

---

## 14. Ce qui n'a pas été fait, délibérément

Aucun workflow de déploiement — ni `deploy.yml`, ni staging, ni SSH vers un VPS,
ni publication d'image. Aucun tag, aucune release. Aucun secret de dépôt créé.
Aucun jeton Hermes, aucun jeton administrateur « pour plus tard ». Aucun Git LFS.
Aucune configuration de GitHub Projects.

---

## 15. État des fichiers

### Fichiers modifiés ou créés par GITHUB-001

```text
A  .env.example                    modèle de configuration, valeurs d'exemple
A  .github/workflows/ci.yml        CI backend + frontend
A  .github/dependabot.yml          npm · github-actions · uv, hebdomadaire
A  CONTRIBUTING.md                 flux de branche, bornes de l'automatisation
M  .gitignore                      secrets, couverture, dumps, artefacts
M  README.md                       commandes frontend ajoutées, état des SPEC à jour
A  docs/reports/2026-08-19-github-foundation.md   ce rapport
```

`README.md` **préexistait et a été préservé** : la structure, les principes et
l'arborescence sont intacts. Deux corrections seulement, au service du clone
frais — l'ajout des commandes frontend, absentes, et la mise à jour d'un état qui
s'arrêtait à SPEC-006R et affirmait « pas encore de persistance » alors que le
dépôt porte le SaaS complet et le frontend.

### `git diff --stat` (branche de fondation vs `main`)

```text
 .env.example             | 71 +++++++++++++++++++++++++++++++++++++++
 .github/dependabot.yml   | 31 +++++++++++++++++
 .github/workflows/ci.yml | 87 ++++++++++++++++++++++++++++++++++++++++++++++++
 .gitignore               | 33 ++++++++++++++++++
 CONTRIBUTING.md          | 52 +++++++++++++++++++++++++++++
 README.md                | 34 ++++++++++++++++---
 6 files changed, 304 insertions(+), 4 deletions(-)
```

Le rapport lui-même reste **non committé**, en attente de votre revue.

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

Ce sont exactement les huit fichiers historiques volontairement non suivis. Rien
n'a été ajouté au prétexte que GitHub existait.

### Commits et branche

```text
main                        43c41e2   (= distant, inchangé)
chore/github-foundation     e37dd0e   chore(repo): add GitHub foundation and CI
                            90339f1   ci: pin setup-uv to an existing tag
```

**Deux commits au lieu d'un.** Le second est le correctif d'action décrit en §9.
Le regrouper aurait exigé un `git commit --amend` suivi d'une poussée forcée sur
la branche, ce que la consigne « pas de force push sans autorisation » écarte.
J'ai préféré un second commit honnête, et la PR est *squash-mergeable* si vous
voulez un commit unique dans `main`.

**`main` local est resté au SHA approuvé, égal au distant.** Le travail de
fondation vit sur la branche et dans la **PR #1**, ouverte, verte, non fusionnée
— ce qui laisse la décision de fusion au superviseur tout en permettant de
vérifier réellement que la CI passe.

---

## 16. Gates locaux finaux

### Backend

```text
uv run pytest -q      →  2724 passed   (arbre local, 24 tests non suivis compris)
                         2700 passed   (périmètre du dépôt — CI et clone frais)
uv run ruff check .   →  All checks passed!
git diff --check      →  propre
```

### Frontend

```text
npm test -- --run  →  10 fichiers, 84 tests, 84 passés
npm run build      →  ✓ built
npx tsc -b         →  0 erreur
npm run lint       →  0 problème
```

Aucun test ignoré, ni au backend ni au frontend.

---

## 17. Règle de source de vérité

À partir de maintenant, **`main` sur GitHub** est la source distante de vérité du
code déployable. Le poste WSL reste la copie de travail active.

Tout déploiement futur enregistre le **SHA du commit GitHub** qu'il déploie.
Jamais « ce qu'il y a dans mon dossier ». État actuel déployable :
`43c41e2989e46724198f81e34a6f87087a0bcdd9`.

---

## 18. Verdict

```text
GITHUB FOUNDATION PARTIALLY READY
```

Tous les critères de `READY` sont atteints **sauf un**, et il est hors de ma
portée :

| Critère | État |
|---|---|
| Dépôt GitHub privé existant | ✅ |
| Historique existant préservé | ✅ 21 commits, aucune réécriture |
| Aucun secret poussé | ✅ 668 blobs d'historique analysés, aucun |
| `main` poussé | ✅ |
| `main` local == `main` distant | ✅ `43c41e2` |
| CI configurée | ✅ |
| CI backend passe | ✅ 2700 tests + ruff |
| CI frontend passe | ✅ 84 tests, build, typecheck, lint |
| Clone frais reproduit tests et build | ✅ backend et frontend |
| Protection de branche évaluée et configurée où c'est possible | ⚠️ **évaluée, impossible à configurer** |

La protection de `main` est **techniquement indisponible** : rulesets et
protection classique exigent GitHub Pro sur un dépôt privé, et le compte est sur
le plan gratuit. J'ai appliqué ce qui restait — permissions de workflow en
lecture seule, Actions privées d'approbation de PR, flux par PR documenté et
exercé — mais je ne peux pas affirmer que `main` est protégé, parce qu'elle ne
l'est pas.

C'est la seule raison du verdict `PARTIALLY`. La lever exige un **plan payant** :
**GitHub Pro** pour ce dépôt personnel, ou **GitHub Team/Enterprise** si le dépôt
passait un jour sous organisation. Une organisation *gratuite* n'y changerait
rien — sur dépôt privé, elle est logée à la même enseigne qu'un compte personnel
gratuit (détail en §12).

Le superviseur a tranché : dépôt **maintenu privé sous le compte personnel**,
aucun transfert, aucune montée de plan pour l'instant. Ce point ne bloque pas le
staging. Il devra être réexaminé **avant** qu'une automatisation obtienne un
droit d'écriture GitHub ; jusque-là, aucun jeton d'écriture ou d'administration
n'est délivré à une automatisation.

**Décision en attente de votre part :** fusionner la PR #1. Tant qu'elle est
ouverte, `main` n'a ni CI, ni `.env.example`, ni configuration Dependabot —
Dependabot ne lit sa configuration que sur la branche par défaut.

Aucun déploiement. Aucun tag. Aucune release. Hermes non installé, aucun jeton
créé.
