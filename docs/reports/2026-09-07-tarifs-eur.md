# Livraison — grille tarifaire EUR

Branche `feat/tarifs-eur`, base initiale `efa995c`. Recette sur la base staging `1ed73e3` de la PR #175 : la PR #183 cible `fix/qa-attribution-runtime` pour conserver les migrations et correctifs déjà déployés, avec un diff limité aux tarifs. La correction utilisateur fixe **Pro à 49 €**, et non 79 €. Essentiel 29 €, Scale 199 €, Découverte gratuit ; mensualités HT et mention « TVA en sus ».

## Fichiers modifiés

| Chemin | Changement |
|---|---|
| `frontend/index.html` | Méta-description remplacée par la phrase demandée. |
| `frontend/src/presentation/public/PricingResource.tsx` | Sélection EUR pour les offres publiques ; symbole € issu du prix du catalogue. |
| `frontend/src/pages/PublicPricing.tsx` | Cartes et comparaison : montant, espace insécable, € ; même catalogue. |
| `frontend/src/pages/Landing.tsx` | Matrice d’offres de l’accueil : même format EUR. |
| `frontend/src/pages/Billing.tsx` | Nouveau choix en EUR ; devise du contrat conservée pour les abonnements existants. |
| `frontend/src/billing/billing.test.tsx` | Attentes 29/49/199, devise EUR et payload Checkout. |
| `frontend/src/billing/packaging.test.tsx` | Attentes tarifaires et retrait de l’ancienne assertion confondant 29 avec l’offre fondateur. |
| `frontend/src/billing/referenceBilling.test.tsx` | Attentes du sélecteur, payloads EUR et prix manquant en EUR. |
| `frontend/src/pages/landingHowItWorks.test.tsx` | Attente accueil 29 €. |
| `frontend/src/pages/publicReferencePort.test.tsx` | Catalogue arbitraire EUR et régression cartes/tableau, espace insécable, méta-description. |
| `frontend/src/test/harness.tsx` | Catalogue de test EUR 2900/4900/19900 ; montants historiques CHF conservés. |
| `frontend/tests/visual/fixtures.ts` | Catalogue visuel EUR 2900/4900/19900. |
| `frontend/tests/visual/reference-goldens/public-pricing-desktop.png` | Capture de référence avec les nouveaux prix. |
| `frontend/tests/visual/reference-goldens/public-pricing-mobile.png` | Capture de référence avec les nouveaux prix. |
| `frontend/tests/staging/tarifs-eur.mjs` | Recette Playwright réelle /tarifs et un Checkout test par palier ; aucun paiement soumis. |
| `src/signals/billing/catalogue.py` | Montants EUR 2900/4900/19900 ; clés EUR versionnées ; anciens montants CHF et anciennes clés conservés. |
| `src/signals/api/routes_billing.py` | Catalogue des devises achetables limité à EUR ; coupon historique réservé au parcours historique CHF. |
| `src/signals/billing/checkout.py` | Devise de la tentative transmise explicitement à Stripe. |
| `src/signals/billing/gateway.py` | Paramètre currency explicite et Adaptive Pricing désactivé dans Checkout pour empêcher la conversion géographique. |
| `tests/test_billing_catalogue.py` | Montants EUR corrigés, anciens CHF et résolution des deux devises avec Price ID opaque. |
| `tests/test_billing_checkout.py` | Régression du coupon historique sur nouveau Pro EUR. |
| `tests/test_billing_checkout_params.py` | Vérification du dictionnaire réellement envoyé au SDK : currency=eur et adaptive_pricing.enabled=false. |
| `docs/reports/2026-09-07-tarifs-eur.md` | Présent inventaire et preuves de validation. |
| `docs/reports/tarifs-eur/tarifs-desktop.png` | Capture réelle de la page staging sur desktop. |
| `docs/reports/tarifs-eur/tarifs-mobile.png` | Capture réelle de la page staging sur mobile. |
| `docs/reports/tarifs-eur/checkout-essential.png` | Checkout test Essentiel à 29 €. |
| `docs/reports/tarifs-eur/checkout-pro.png` | Checkout test Pro à 49 €. |
| `docs/reports/tarifs-eur/checkout-scale.png` | Checkout test Scale à 199 €. |
| `docs/reports/tarifs-eur/acceptance.json` | Résultats navigateur et SDK Stripe, sans identifiants Stripe ni secrets. |

## Occurrences CHF remplacées

Les montants affichés étaient calculés à partir de `currency="chf"` : il n’existait pas de littéral « CHF 49 » dans les composants de production. Les trois cartes, trois cellules de comparaison et trois cellules de l’accueil utilisent maintenant le catalogue EUR.

Les lignes de référence suivantes contenant littéralement CHF ont été remplacées (numéros avant PR) :

- `frontend/src/billing/billing.test.tsx:66` : `// Les montants viennent du catalogue : 0 / 49 / 99 / 199, en CHF par défaut.`
- `frontend/src/billing/billing.test.tsx:110` : `expect(within(group).getByLabelText('CHF')).toBeInTheDocument()`
- `frontend/src/billing/billing.test.tsx:114` : `expect(within(group).getByLabelText('CHF')).toBeChecked()`
- `frontend/src/pages/landingHowItWorks.test.tsx:37` : `await screen.findByText('CHF 49')`
- `frontend/src/pages/publicReferencePort.test.tsx:79` : `expect(within(essential).getByText('CHF')).toBeInTheDocument()`
- `frontend/src/pages/publicReferencePort.test.tsx:112` : `expect(await screen.findByText(/CHF\s+57/)).toBeInTheDocument()`
- `src/signals/billing/catalogue.py:18` : `Les montants sont des décisions commerciales, pas des conversions. 49 CHF **ou**`

Sélections techniques `chf → eur` : `PricingResource.tsx`, `Billing.tsx`, `harness.tsx`, `fixtures.ts` et les tests de tarification ci-dessus. Aucun montant n’est converti par un taux de change.

## Audit des autres surfaces

Commande de recherche sur les fichiers suivis : `rg -n "CHF|\b49\b|\b99\b|\b199\b" frontend src ops` ; tri manuel des résultats, puis recherche complémentaire des occurrences `chf`, `4900`, `9900`, `19900` et `price_`.

- Aucun prix d’abonnement trouvé dans `src/signals/alerts/`, `src/signals/transactional_email/`, `src/signals/personalization/`, `src/signals/responses/` ni `frontend/src/pages/LegalInformation.tsx`. Le seul 99 de ces répertoires est une borne de regex dans `personalization/contracts.py`.
- Métadonnées publiques et footer : le seul terme banni trouvé dans la surface inspectée était dans `frontend/index.html`. Aucune balise OG statique présente. La recette Playwright vérifie aussi titre, méta-description, balises OG éventuelles et footer.
- Les devises des marchés SIMAP, seuils de profils et métriques historiques restent distinctes de la tarification SaaS. Le grep global frontend n’est donc pas nul : `frontend/founder/src/FounderApp.tsx` (1), `frontend/founder/src/types.ts` (2), `frontend/src/api/capabilities.ts` (1), `frontend/src/api/types.ts` (1), `frontend/src/pages/Icps.tsx` (1), `frontend/src/presentation/dashboard/OnboardingFlow.tsx` (3) conservent neuf lignes métier CHF hors tests. Les assertions négatives de tests conservent aussi le mot CHF. Aucun remplacement artificiel ni retrait de support métier.
- Les autres nombres sont coordonnées SVG/CSS, codes de département, indicatif téléphonique allemand, limites de regex et références de spécification. `ops/validation/plan_change_testclock.py` vérifie toujours les contrats historiques CHF.

## Stripe et configuration

- Trois nouveaux Prices créés en test et trois en live, sur les Products existants : EUR 2900/4900/19900, intervalle month, `tax_behavior=exclusive`, métadonnée `plan`.
- Descriptions des trois Products corrigées dans Stripe test et live : Essentiel « 1 profil de ciblage » → « 1 profil cible », Pro « 3 profils de ciblage » → « 3 profils cibles », Scale « 10 profils de ciblage » → « 10 profils cibles ». Le reste des descriptions et les droits restent identiques.
- Clés de recherche `kivou_{essential,pro,scale}_monthly_eur_202609`. Les Prices CHF et les anciens Prices EUR sont conservés, sans transfert de clé. Leur résolution vers les paliers reste acceptée.
- La configuration existante utilise les clés de recherche ; aucun Price ID n’est codé en dur ni lu depuis une variable d’environnement. Aucune variable inutilisée ajoutée ; aucun identifiant réel de Price, Product ou clé secrète dans le dépôt.
- Lecture du compte live : aucune souscription Kivou trouvée, tous statuts compris ; aucun coupon fondateur configuré en staging ou prod. Les montants CHF historiques restent inchangés dans le calcul du MRR.
- Tax test : siège et paramètres existants copiés du live, réglages test `active`, `STRIPE_AUTOMATIC_TAX_ENABLED=1` dans `/etc/kivou/staging.env` avec sauvegarde. Aucune immatriculation créée ; aucune immatriculation active, donc aucune collecte fiscale. Validation fiscale toujours à faire avec le comptable.
- Le paramètre applicatif de collecte automatique Tax reste désactivé en production. Aucun déploiement production effectué. Les nouveaux Prices live seront sélectionnés par cette version lors d’un futur déploiement production.

## Commandes et validations locales

- Référence avant modification : `PYTHONPATH=src .venv/bin/pytest tests/test_billing_catalogue.py tests/test_billing_checkout_params.py -q` → 53 réussis.
- Régressions constatées avant correction : montants EUR, rendu cartes/tableau, paramètre currency manquant et ancien coupon appliqué au nouveau Pro.
- Suite complète : `PYTHONPATH=src .venv/bin/pytest -q -o faulthandler_timeout=90` → 6282 réussis, 24 ignorés, 1 xfailed.
- Suite frontend locale complète : `npm test -- --run` → 675 réussis, 49 fichiers.
- Après la protection du coupon : catalogue, Checkout, webhooks et conversion → 123 réussis.
- `npm run test:visual` → 39 réussis. Captures actualisées uniquement pour `/tarifs` desktop/mobile ; accueil inchangé au seuil visuel.
- `npm run build`, `npm run build:founder`, `npm run lint`, `.venv/bin/ruff check .`, `git diff --check` exécutés ; TypeScript inclus dans les builds.
- Les premières exécutions réseau/processus bloquées par le sandbox ont été relancées avec les permissions nécessaires. Les polices de Vite nécessitent une installation locale des dépendances dans le worktree.

## CI et staging

PR [#183](https://github.com/bruppacherrodrigue-art/Kivou/pull/183), base `fix/qa-attribution-runtime` (#175). Cette base conserve les migrations et correctifs déjà présents en staging ; elle doit être intégrée avant de cibler main.

CI du code déployable : [34220017237](https://github.com/bruppacherrodrigue-art/Kivou/actions/runs/34220017237), **sept jobs réussis**, SHA `a8ca58bfcd316a10f523e1f9edf607ef2da1a67f`. Les quatre lots backend passent ; le lot 1 confirme 1613 réussis et 3 ignorés. Sur cette base : **712 tests frontend dans 52 fichiers et 47 tests visuels réussis**, builds app/founder, TypeScript, ESLint et Ruff validés.

Après la désactivation explicite d’Adaptive Pricing : test rouge du paramètre observé, puis `PYTHONPATH=src .venv/bin/pytest tests/test_billing_catalogue.py tests/test_billing_checkout_params.py -q` → **62 réussis**. Checkout garde `locale=fr`, transmet la devise et désactive la conversion géographique.

Commande de déploiement exécutée sur staging, par une unité systemd chargée avec `/etc/kivou/staging.env` :

```sh
/srv/kivou/source/ops/bin/kivou-deploy.sh staging a8ca58bfcd316a10f523e1f9edf607ef2da1a67f
```

Sauvegarde préalable acceptée : `kivou-20260908T115013Z.dump`, **1830087530 octets**. Restauration de contrôle terminée, API prête en 3 secondes ; unité `kivou-tarifs-eur-a8ca58b` terminée avec succès. Release activée le **8 septembre 2026 à 11:57:18 UTC**, lien `/srv/kivou/app` vers `/srv/kivou/releases/staging-a8ca58bfcd316a10f523e1f9edf607ef2da1a67f`.


## Recette publique et Checkout

La recette utilise Chromium réel, le compte QA `pr2b-qa-20260903152743@kivou-qa.ch` et les endpoints staging sans réponse simulée. Les captures et résultats sans identifiants Stripe sont joints dans `docs/reports/tarifs-eur/`.

```sh
curl --silent --show-error --fail -L https://staging.kivou.eu/tarifs -o /tmp/kivou-tarifs-live-final/tarifs.html
grep -c CHF /tmp/kivou-tarifs-live-final/tarifs.html
# 0 ; grep renvoie le code 1 attendu quand aucune ligne ne correspond.

# Depuis frontend/, avec une session QA placée dans un fichier privé :
KIVOU_QA_STORAGE_STATE=/tmp/kivou-tarifs-qa-state.json KIVOU_QA_OUTPUT=/tmp/kivou-tarifs-live-final node tests/staging/tarifs-eur.mjs essential
KIVOU_QA_STORAGE_STATE=/tmp/kivou-tarifs-qa-state.json KIVOU_QA_OUTPUT=/tmp/kivou-tarifs-live-final node tests/staging/tarifs-eur.mjs pro
KIVOU_QA_STORAGE_STATE=/tmp/kivou-tarifs-qa-state.json KIVOU_QA_OUTPUT=/tmp/kivou-tarifs-live-final node tests/staging/tarifs-eur.mjs scale
```

Entre chaque parcours, la session test est relue puis expirée via le SDK Stripe sur staging ; le statut local `billing_checkout_attempt.status=expired` est vérifié après réception du webhook. L’orchestration réellement exécutée est `bash /tmp/kivou-tarifs-acceptance.sh a8ca58bfcd316a10f523e1f9edf607ef2da1a67f`. Les helpers temporaires de session et de vérification lisent les secrets sur le serveur ; aucun cookie, URL Checkout ou identifiant réel de Price n’est versionné.

Le HTML initial contient la phrase de méta-description demandée, sans CHF. Après rendu React, la description propre à `/tarifs` reste « Les quatre offres mensuelles Kivou, de Découverte à Scale. », également sans terme banni. Cartes et tableau affichent 29, 49 et 199 avec espace insécable et symbole €. Corps rendu : zéro CHF ; titre, footer et balises OG éventuelles contrôlés.

Les **trois parcours ont réussi** sur la même release :

| Palier | Montant HT affiché | Sous-total API, centimes | Devise / période | Mode | Nettoyage QA |
|---|---|---|---|---|---|
| Essentiel | 29 € | 2900 | EUR / mois | test | session expirée, webhook appliqué |
| Pro | 49 € | 4900 | EUR / mois | test | session expirée, webhook appliqué |
| Scale | 199 € | 19900 | EUR / mois | test | session expirée, webhook appliqué |

Chaque session utilise le nouveau lookup key approuvé, une quantité de 1, `tax_behavior=exclusive`, `automatic_tax.enabled=true`, `adaptive_pricing.enabled=false`, le compte QA attendu et `livemode=false`. Aucun paiement soumis. Le corps de chaque Checkout est sans CHF ni terme banni. Les captures ne valident pas une liquidation de TVA : aucune adresse fiscale n’a été soumise, aucune immatriculation active configurée.

Le commit de livraison suivant `a8ca58b` ne contient que le rapport, ses six preuves et le script de recette. Le code applicatif déployé reste identique ; la dernière CI de PR est consultable dans les checks de #183.
