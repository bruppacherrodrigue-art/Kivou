# Inventaire et nettoyage — 2026-09-08

Périmètre : branche `fix/cleanup-2026-09`, comparaison avec `main` (`efa995c`).
Aucune donnée métier ni migration n'a été supprimée. Les historiques ont été
déplacés dans `archive/` et restent récupérables par la branche `archive/2026-09`.

## Supprimer du produit

| Élément | Lignes avant | Preuve après nettoyage | Verdict |
|---|---:|---|---|
| `frontend/src/layouts/AuthLayout.tsx` | 1 | `test -e` négatif ; `rg 'AuthLayout' frontend/src` ne trouve aucun appelant | supprimé |
| `frontend/src/components/FormField.tsx` + `.module.css` | 371 | aucun import dans `frontend/src`; remplacé par les champs existants | supprimé |
| `frontend/src/assets/Icons.tsx` | 176 | aucun import hors fichier supprimé | supprimé |
| `frontend/src/cockpit/CommercialCockpit.tsx` + CSS + test | 356 | aucune route React ni import ; `/internal/commercial-cockpit` reste servi côté API | supprimé du bundle |
| `/onboarding`, `Onboarding.tsx`, `OnboardingFlow.tsx`, test | 2 424 | `rg '/onboarding|OnboardingFlow|Onboarding' frontend/src` ne trouve plus de route/composant ; `RequireAuth` pointe vers `/app/confirm-profile` | supprimé, PR5 conservée |
| `src/signals/alerts/content.py` | 200 | `job.py` importe `renderer.py`; `rg 'alerts.content|Besoins plausibles|Plausible needs' src frontend/src tests` ne trouve aucun usage actif | supprimé, renderer PR6 actif |
| `GET /signals/filters` et `src/signals/feed/filters.py` | 1 route + module | aucun appelant frontend/runtime ; les filtres Zone/Secteur utilisent le feed et les profils | supprimé |
| `ops/validation/plan_change_testclock.py` | 299 | seul scénario Scale ; aucune commande CI/timer ne le référence | supprimé |
| `@testing-library/dom` direct | package.json | aucun import direct ; le lockfile la conserve uniquement comme dépendance transitive de Testing Library | retiré de la dépendance directe |

**Total candidat supprimé : 3 827 lignes** (hors fichiers générés et archives).

## Sortir de `src` vers `/archive`

| Dossier | Preuve d'inatteinte | Verdict |
|---|---|---|
| `research` | `rg 'signals\\.(research|signal100)' src tests frontend` : aucun import actif ; seulement une référence documentaire dans fixture | `archive/research/source/` |
| `verification` | aucun import dans API, ingestion, alerts, acquisition, for-you ou timers | `archive/verification/source/` |
| `phase_a_btp` + JSON de démo | aucun import/route/runtime ; aucun lien depuis landing ou shell | `archive/phase_a_btp/source/` |
| `learning` | `rg 'signals\\.learning'` hors archive : aucun résultat ; ni `acquisition_runtime` ni Hermes ne l'importe | `archive/learning/source/` |
| fixtures et tests de ces quatre dossiers | imports cantonnés aux tests historiques, désormais hors découverte pytest | `archive/*/tests/` |
| `spec009c*`, fixture blind et rapports protégés de Rodrigue | déplacés sans réécriture dans `archive/research/spec009c/` | conservés hors paquet |
| deux `.docx` protégés | déplacés sans modification dans `archive/docs/` | conservés hors dépôt actif |

Chaque dossier archivé contient un README indiquant qu'il est hors paquet et hors CI.
Les migrations Alembic restent dans `src/signals/persistence/migrations`.

## Garder avec raison

| Surface | Preuve route/import/timer | Verdict |
|---|---|---|
| `presentation/dashboard/*` et `dashboard-vendor.css` | importé par `main.tsx` et `AppShell`; nécessaire au shell partagé | garder |
| `presentation/dashboard/vendor/*` | importé par `dashboard-vendor.css`; CSS de surface, pas un écran mort | garder |
| `Dashboard.tsx` | routes `/app` et `/app/dashboard` dans `App.tsx` | garder |
| `src/signals/cockpit` | route backend `/internal/commercial-cockpit`, montée par `api/app.py`; aucun client portail requis | garder backend |
| `src/signals/founder_api` | unité `kivou-founder-api.service` et routes `/api/founder/*` | garder |
| `src/signals/operations` | routes internes d'acquisition montées par `api/app.py` | garder |
| `/a/{token}` et webhooks | autorisés explicitement par le test d'architecture et consommés par runtime externe | garder |

## Scale retiré

Le catalogue, les lookup keys, routes billing, `Billing.tsx`, `PricingResource.tsx`,
la page `/tarifs`, i18n, entitlements, quotas, tests et fixtures ne contiennent
plus de plan Scale. Le catalogue actif est exactement `discovery`, `essential`,
`pro`; la page publique affiche désormais « Besoin de plus de profils ou de
zones ? Écrivez-nous ». `rg -i '\bscale\b' src frontend/src docs` ne retourne
rien hors du paramètre SQL historique `scale=2` de la migration initiale.
Aucun identifiant live `prod_`/`price_` Scale n'existe dans le dépôt : Rodrigue
doit archiver les produits/prix dans Stripe Dashboard et relever leurs IDs depuis
le Dashboard avant action. Un éventuel compte Scale est migré vers Pro.

## i18n, routes et dépendances

| Contrôle | Résultat et preuve | Verdict |
|---|---|---|
| Clés i18n | `node scripts/prune-orphan-i18n.mjs --prune` utilise TypeScript AST, traite les préfixes dynamiques listés dans le script ; `dictionary_leaves=1652`, `orphan_leaves=0` | garder les 1 652 feuilles utilisées |
| Routes FastAPI | `tests/test_cleanup_architecture.py::test_declared_api_routes_have_a_frontend_or_runtime_caller` extrait les décorateurs ; familles internes `cockpit`, `founder`, `operations`, `webhooks`, `/a/` sont la liste blanche | test d'architecture actif |
| Python | comparaison imports/entrypoints systemd/CLI : aucun paquet runtime sans import ou commande démontré | aucun retrait justifié |
| npm | aucun import direct de `@testing-library/dom`; `npm ls` montre seulement ses consommateurs transitifs | package direct retiré |
| Environnement | les clés `KIVOU_STAGING_*` sont lues uniquement par `ops/local/staging-ssh.env`/outillage SSH ; les clés applicatives sont lues par les loaders correspondants | ne pas mettre les clés SSH dans les env de service |

## Ops et documentation

| Contrôle | Preuve | Décision |
|---|---|---|
| `kivou-api-green` | `systemctl is-active/is-enabled` staging et prod : absent/inactif | aucune unité à garder |
| `kivou-173-*` | staging : unités transitoires arrêtées puis `reset-failed`; prod : aucune unité correspondante | supprimées de l'état actif, pas de fichier ops à ajouter |
| rapports | `docs/reports` ne garde que la fenêtre depuis le 30/08 et les captures récentes ; les anciens sont dans `archive/docs/reports/` | branche `archive/2026-09` à créer depuis ce HEAD |
| plans/specs | anciens lots B/C et PR1–PR5 vont dans `archive/docs/superpowers/`; les plans PR6b, PR7, après-mise-en-prod et modules encore actifs restent dans le dépôt | garder seulement le travail ouvert |
| baselines | aucune référence CI active trouvée par `rg 'baseline|docs/reports' .github ops frontend/scripts`; les baselines non référencées vont dans l'archive | CI devient la source de conservation |

## Chiffres avant/après

| Arbre | `main` avant | branche après | variation |
|---|---:|---:|---:|
| `src` | 108 657 | 96 214 | -12 443 |
| `frontend/src` | 29 031 | 25 101 | -3 930 |
| `tests` | 120 205 | 113 386 | -6 819 |
| `docs` | 75 759 | 23 935 | -51 824 |

Les comptes sont des lignes physiques des fichiers Python/TypeScript/TSX/Markdown;
les JSON et fichiers générés sont exclus de ce tableau. La durée de la suite sera
ajoutée avec la sortie CI, pas estimée localement.

## Recette Playwright staging

Captures desktop/mobile et drawer pour les trois comptes :
[`2026-09-08-cleanup-playwright/README.md`](2026-09-08-cleanup-playwright/README.md).
Le run a utilisé Chromium installé par le déploiement ; le compte recette a été
connecté une seule fois puis redimensionné pour éviter le rate-limit login.
