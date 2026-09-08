# Livraison — grille tarifaire EUR

Branche `feat/tarifs-eur`, base initiale `efa995c`. Recette sur la base staging `d7f1d7a` de la PR #175 : la PR #183 cible `fix/qa-attribution-runtime` pour conserver les migrations et correctifs déjà déployés, avec un diff limité aux tarifs. La correction utilisateur fixe **Pro à 49 €**, et non 79 €. Essentiel 29 €, Scale 199 €, Découverte gratuit ; mensualités HT et mention « TVA en sus ».

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
| `src/signals/billing/gateway.py` | Paramètre currency explicite dans Checkout. |
| `tests/test_billing_catalogue.py` | Montants EUR corrigés, anciens CHF et résolution des deux devises avec Price ID opaque. |
| `tests/test_billing_checkout.py` | Régression du coupon historique sur nouveau Pro EUR. |
| `tests/test_billing_checkout_params.py` | Vérification du dictionnaire réellement envoyé au SDK : currency=eur. |
| `docs/reports/2026-09-07-tarifs-eur.md` | Présent inventaire et preuves de validation. |

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
- Métadonnées publiques et footer : le seul terme banni trouvé dans la surface inspectée était dans `frontend/index.html`. Aucune balise OG statique présente. Recette DOM prévue ci-dessous.
- Les devises des marchés SIMAP, seuils de profils et métriques historiques restent distinctes de la tarification SaaS. Le grep global frontend n’est donc pas nul : `api/capabilities.ts`, `api/types.ts`, `pages/Icps.tsx`, `presentation/dashboard/OnboardingFlow.tsx` et leurs tests conservent CHF. Les assertions négatives de tests conservent aussi le mot CHF. Aucun remplacement artificiel ni retrait de support métier.
- Les autres nombres sont coordonnées SVG/CSS, codes de département, indicatif téléphonique allemand, limites de regex et références de spécification. `ops/validation/plan_change_testclock.py` vérifie toujours les contrats historiques CHF.

## Stripe et configuration

- Trois nouveaux Prices créés en test et trois en live, sur les Products existants : EUR 2900/4900/19900, intervalle month, `tax_behavior=exclusive`, métadonnée `plan`.
- Clés de recherche `kivou_{essential,pro,scale}_monthly_eur_202609`. Les Prices CHF et les anciens Prices EUR sont conservés, sans transfert de clé. Leur résolution vers les paliers reste acceptée.
- La configuration existante utilise les clés de recherche ; aucun Price ID n’est codé en dur ni lu depuis une variable d’environnement. Aucune variable inutilisée ajoutée ; aucun identifiant réel de Price, Product ou clé secrète dans le dépôt.
- Lecture du compte live : aucune souscription Kivou trouvée, tous statuts compris ; aucun coupon fondateur configuré en staging ou prod. Les montants CHF historiques restent inchangés dans le calcul du MRR.
- Tax test : siège et paramètres existants copiés du live, réglages test `active`, `STRIPE_AUTOMATIC_TAX_ENABLED=1` dans `/etc/kivou/staging.env` avec sauvegarde. Aucune immatriculation créée ; aucune immatriculation active, donc aucune collecte fiscale. Validation fiscale toujours à faire avec le comptable.
- Tax live reste désactivé. Aucun déploiement production effectué. Les nouveaux Prices live seront sélectionnés par cette version lors d’un futur déploiement production.

## Commandes et validations locales

- Référence avant modification : `PYTHONPATH=src .venv/bin/pytest tests/test_billing_catalogue.py tests/test_billing_checkout_params.py -q` → 53 réussis.
- Régressions constatées avant correction : montants EUR, rendu cartes/tableau, paramètre currency manquant et ancien coupon appliqué au nouveau Pro.
- Suite complète : `PYTHONPATH=src .venv/bin/pytest -q -o faulthandler_timeout=90` → 6282 réussis, 24 ignorés, 1 xfailed.
- Suite frontend finale : `npm test -- --run` → 675 réussis, 49 fichiers.
- Après la protection du coupon : catalogue, Checkout, webhooks et conversion → 123 réussis.
- `npm run test:visual` → 39 réussis. Captures actualisées uniquement pour `/tarifs` desktop/mobile ; accueil inchangé au seuil visuel.
- `npm run build`, `npm run build:founder`, `npm run lint`, `.venv/bin/ruff check .`, `git diff --check` exécutés ; TypeScript inclus dans les builds.
- Les premières exécutions réseau/processus bloquées par le sandbox ont été relancées avec les permissions nécessaires. Les polices de Vite nécessitent une installation locale des dépendances dans le worktree.

## CI et staging

PR créée en brouillon pendant la CI. La fusion de la base staging conserve `locale=fr` et ajoute `currency=eur` dans Checkout. Déploiement et recette live à compléter sur le SHA validé ; aucune demande de review avant ces preuves.
