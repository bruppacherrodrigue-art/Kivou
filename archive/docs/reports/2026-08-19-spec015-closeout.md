# SPEC-015 CLOSEOUT — Design Reproducibility + Frontend Delivery Safety

**Date :** 19 août 2026
**Base :** SPEC-015, implémentation et direction visuelle acceptées.
**Verdict :** voir §9.

Les textures travertin/marbre restent en implémentation vectorielle, acceptée
explicitement par le superviseur. Aucun blocage de commit de ce côté.

---

## 1. Source de design faisant autorité — désormais suivie

`docs/designPattern/` contient **58 entrées**, dont **29 métadonnées NTFS**
`:Zone.Identifier` produites par le transfert Windows → WSL. Elles ne portent
aucun contenu.

### Règle d'exclusion

Une règle a été ajoutée au `.gitignore` de la racine :

```gitignore
*:Zone.Identifier
```

Elle est **globale au dépôt**, pas seulement au pack de design : les mêmes
artefacts polluaient aussi `tests/fixtures/documents/` et les `.docx` de la
racine. Après la règle, `git status` n'en mentionne plus **aucun** (29 → 0).

Aucun original n'a été modifié, déplacé ou supprimé — seulement ignoré.

### Fichiers suivis : 29

| Catégorie | Fichiers | Taille |
|---|---:|---:|
| Planches de référence approuvées (`assets/reference/01…08`) | 8 | 12,51 Mo |
| Spécification illustrée `KIVOU_DESIGN_SYSTEM_v1.0.docx` | 1 | 11,13 Mo |
| Suite de logos (6 SVG + 6 PNG d'aperçu) | 12 | 0,17 Mo |
| Planche de marque `kivou-brand-board-clean.png` | 1 | 0,08 Mo |
| Directives + README + manifeste d'assets | 4 | 0,05 Mo |
| Tokens (`.css`, `.json`, preset Tailwind) | 3 | 0,01 Mo |
| **Total ajouté à Git** | **29** | **23,95 Mo** |

Liste exacte :

```text
docs/designPattern/KIVOU_CLAUDE_CODE_DESIGN_DIRECTIVE.md
docs/designPattern/Kivou_Design_System_v1_0/KIVOU_CLAUDE_CODE_DESIGN_DIRECTIVE.md
docs/designPattern/Kivou_Design_System_v1_0/README.md
docs/designPattern/Kivou_Design_System_v1_0/ASSET_MANIFEST.md
docs/designPattern/Kivou_Design_System_v1_0/docs/KIVOU_DESIGN_SYSTEM_v1.0.docx
docs/designPattern/Kivou_Design_System_v1_0/tokens/kivou.tokens.css
docs/designPattern/Kivou_Design_System_v1_0/tokens/kivou.tokens.json
docs/designPattern/Kivou_Design_System_v1_0/tokens/kivou.tailwind.preset.ts
docs/designPattern/Kivou_Design_System_v1_0/assets/kivou-brand-board-clean.png
docs/designPattern/Kivou_Design_System_v1_0/assets/reference/01-approved-direction-saas-overview.png
docs/designPattern/Kivou_Design_System_v1_0/assets/reference/02-approved-direction-marketing-home.png
docs/designPattern/Kivou_Design_System_v1_0/assets/reference/03-approved-direction-mobile.png
docs/designPattern/Kivou_Design_System_v1_0/assets/reference/04-approved-direction-client-signal-feed.png
docs/designPattern/Kivou_Design_System_v1_0/assets/reference/05-approved-direction-internal-weekly-cockpit.png
docs/designPattern/Kivou_Design_System_v1_0/assets/reference/06-approved-direction-checkout.png
docs/designPattern/Kivou_Design_System_v1_0/assets/reference/07-approved-direction-illustrations.png
docs/designPattern/Kivou_Design_System_v1_0/assets/reference/08-approved-direction-internal-funnel-table.png
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-mark.svg
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-mark.png
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-logo-horizontal.svg
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-logo-horizontal.png
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-logo-horizontal-monochrome-dark.svg
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-logo-horizontal-monochrome-dark.png
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-logo-horizontal-monochrome-light.svg
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-logo-horizontal-monochrome-light.png
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-logo-stacked.svg
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-logo-stacked.png
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-favicon.svg
docs/designPattern/Kivou_Design_System_v1_0/brand/logo/kivou-favicon.png
```

**Aucun fichier de police** n'est présent dans le pack — vérifié : aucun `.woff`,
`.woff2`, `.ttf`, `.otf` ou `.eot`. Rien à exclure de ce côté.

### Deux points à votre attention

1. **La directive existe en double.** `docs/designPattern/KIVOU_CLAUDE_CODE_DESIGN_DIRECTIVE.md`
   et sa copie dans `Kivou_Design_System_v1_0/` sont **octet pour octet
   identiques** (`diff` vide). Les deux sont suivies : la copie interne est
   référencée par le `README.md` du pack, qui doit rester autonome, et la copie
   racine est le point d'entrée du dossier que vous avez désigné. Coût : 20 ko.
   **Risque assumé :** elles peuvent diverger. Si vous préférez n'en garder
   qu'une, dites laquelle — je n'ai pas voulu trancher à votre place sur la
   forme du dossier que vous avez livré.

2. **Le DOCX pèse 11,13 Mo à lui seul**, soit 46 % du pack, parce qu'il embarque
   dix images en pleine résolution. C'est la spécification illustrée complète et
   elle fait autorité, donc elle est suivie telle quelle. Elle changera rarement,
   mais chaque révision ajoutera ~11 Mo à l'historique. Si cela devient un
   problème, la piste est Git LFS — hors scope ici.

---

## 2. Livraison réelle des polices

### Ce qui n'allait pas

L'implémentation initiale chargeait Lora et Instrument Sans par une balise
`<link>` vers `fonts.googleapis.com`. Le rapport parlait de « licence SIL OFL »
sans dire comment les fichiers atteignaient le navigateur. Trois défauts :
dépendance à un tiers à chaque affichage, fuite de l'adresse IP du visiteur vers
Google, et rendu qui échoue silencieusement en Georgia/Arial si la requête est
bloquée — dans un pays qui filtre, sur un réseau d'entreprise, ou hors ligne.

### Ce qui a été mis en place

Livraison **au build**, par paquets npm verrouillés :

```json
"@fontsource-variable/lora": "^5.3.0",              // SIL OFL 1.1
"@fontsource-variable/instrument-sans": "^5.3.0"    // SIL OFL 1.1
```

Elles sont en **`dependencies`**, pas en `devDependencies` : ce sont des entrées
de construction, et une installation de production doit les avoir.

L'entrée se fait dans `src/main.tsx` :

```ts
import '@fontsource-variable/lora/wght.css'
import '@fontsource-variable/instrument-sans/wght.css'
```

Vite résout ces feuilles à la construction, copie les `.woff2` dans
`dist/assets/` avec une empreinte de contenu et réécrit les `@font-face`. Les
binaires ne sont **jamais committés** : ils viennent d'une dépendance verrouillée
par `package-lock.json`, ce que le manifeste d'assets autorise et qu'un fichier
déposé dans le dépôt ne permettrait pas.

Seule la variante **`wght` droite** est importée. Le design system n'emploie
aucune italique ; l'importer doublerait le poids pour rien.

Les piles de tokens nomment la famille **réellement livrée** — les `@font-face`
de Fontsource déclarent `Lora Variable` et `Instrument Sans Variable`, et sans ce
nom en tête la pile n'aurait jamais sélectionné la police téléchargée :

```css
--kivou-font-display: 'Lora Variable', 'Lora', Georgia, 'Times New Roman', serif;
--kivou-font-sans:
  'Instrument Sans Variable', 'Instrument Sans', Inter, Arial, Helvetica, sans-serif;
```

### Mesure en navigateur réel

Chromium 148, page `/app/signals`, écoute réseau CDP + interrogation de
`document.fonts` après `document.fonts.ready` :

```text
polices chargées      : Lora Variable 400 700 · Instrument Sans Variable 400 700
document.fonts.check  : Lora Variable → true · Instrument Sans Variable → true
h1   rendu avec       : "Lora Variable", Lora, Georgia, "Times New Roman", serif
body rendu avec       : "Instrument Sans Variable", "Instrument Sans", Inter, …

requêtes de police    : /assets/instrument-sans-latin-wght-normal-BbzFLZTg.woff2
                        /assets/lora-latin-wght-normal-BiLcIKcI.woff2
requêtes vers un tiers : AUCUNE
```

**Deux requêtes, toutes deux sur notre origine.** Le build émet 9 fichiers
(194 ko au total, tous sous-ensembles confondus), mais les `unicode-range` des
`@font-face` font que le navigateur ne télécharge que le latin : **65 ko** pour
une page française ou anglaise. Les sous-ensembles cyrillique, grec, vietnamien,
mathématique et symboles restent sur le disque du serveur et ne sont jamais
demandés.

### Comportement de repli

`font-display: swap` (posé par Fontsource). Si un `.woff2` ne se charge pas, le
texte s'affiche immédiatement dans le substitut suivant de la pile — Georgia pour
le display, Inter/Arial pour l'interface — puis bascule dès l'arrivée du fichier.
**Le chemin normal ne repose sur aucun de ces substituts** : ils ne servent que
si notre propre origine ne répond pas, auquel cas l'application entière est déjà
indisponible.

### Garde-fou

`frontend/src/styles/fonts.test.ts` — 5 tests qui échouent si l'une des quatre
pièces du montage disparaît :

1. les deux paquets sont bien en `dependencies` ;
2. `main.tsx` importe les deux feuilles ;
3. les tokens nomment `Lora Variable` / `Instrument Sans Variable` en tête ;
4. aucun hôte tiers de police (`fonts.googleapis.com`, `fonts.gstatic.com`,
   `use.typekit.net`, `fonts.bunny.net`, `cdn.jsdelivr.net`) n'apparaît dans le
   HTML ni dans les feuilles globales ;
5. aucun binaire de police n'est référencé depuis `index.html`.

### Vérification visuelle

Les 14 écrans ont été recapturés après le changement. Le rendu est **identique** :
mêmes familles, même graisse, même mesure. L'audit d'accessibilité du feed a été
rejoué : **0 violation**.

---

## 3. URL de retour Stripe — le défaut dangereux est supprimé

### Ce qui n'allait pas

```python
stripe_success_url: str = "https://app.kivou.ch/billing/success"
stripe_cancel_url: str = "https://app.kivou.ch/billing/cancel"
stripe_portal_return_url: str = "https://app.kivou.ch/billing"
```

Le domaine produit est `kivou.eu`. Ce défaut a survécu au changement de domaine
sans que rien ne le signale, et il ne se serait vu qu'au premier paiement réel :
le client paie, puis atterrit sur un hôte qui n'est plus le nôtre. Les alias de
routes React ne corrigent pas un mauvais **nom d'hôte** — vous avez raison, ils
ne réparaient que le chemin.

### La règle appliquée

> Les URL de retour Stripe doivent être **explicitement configurées** pour un
> déploiement qui encaisse.

Concrètement, en trois temps :

**1. Plus aucun défaut.** Les trois champs valent `None`.

**2. Échec au démarrage.** Une clé Stripe déclare l'intention d'encaisser. À
partir de là, l'absence d'une URL de retour est une erreur de configuration, et
elle s'entend au démarrage — pas au premier paiement :

```text
ValueError: facturation activée sans URL de retour :
            STRIPE_CANCEL_URL doivent être définies
```

Le message **nomme la variable manquante** : une erreur de configuration doit se
réparer sans lire le code source.

**3. Échec net à l'exécution.** Si une application est construite à la main sans
ces URL, `POST /billing/checkout` et `POST /billing/portal` répondent
**503 `billing_unavailable`**. On ne sait pas où renvoyer le client : ouvrir un
paiement l'abandonnerait au bout du parcours Stripe. Le service se déclare
indisponible — c'est exact, et c'est réparable par configuration.

La **lecture** reste ouverte : `GET /billing/status` et `GET /billing/plans`
répondent 200 sans URL de retour. Consulter son offre n'est pas une transaction,
et un compte doit pouvoir le faire sur un déploiement dont la facturation n'est
pas encore branchée.

Les trois URL passent par le même contrôle `https://` obligatoire qu'auparavant.

### Fixtures de test

Domaines **synthétiques**, regroupés dans `tests/billing_helpers.py` :

```python
TEST_SUCCESS_URL       = "https://kivou.test/checkout/success"
TEST_CANCEL_URL        = "https://kivou.test/checkout/cancel"
TEST_PORTAL_RETURN_URL = "https://kivou.test/app/billing"
```

### Nettoyage des fixtures d'origine CSRF

`app.kivou.ch` servait aussi d'`ORIGIN` synthétique dans trois fichiers de test
(`feed_helpers.py`, `test_accounts_security.py`, `test_accounts_target_icp.py`).
Ce n'est pas une URL de retour et cela ne créait aucun risque de production —
mais un nom d'hôte réel et obsolète laissé dans des fixtures finit par être
recopié dans une documentation de déploiement. Il est passé à
**`https://kivou.test`**.

`app.kivou.ch` ne subsiste donc plus que dans trois endroits, tous délibérés :
deux commentaires qui expliquent le défaut historique, et l'assertion qui
vérifie qu'il ne réapparaît pas.

### Nouveaux tests — `tests/test_billing_return_urls.py`, 11 tests

* un déploiement sans clé Stripe démarre sans URL de retour ;
* une clé Stripe **sans** l'une des trois URL refuse de démarrer (3 cas) ;
* une configuration complète démarre ;
* aucun domaine obsolète ne subsiste dans les défauts ;
* une URL non-`https` est refusée ;
* checkout sans URL → 503 ;
* portail sans URL → 503 ;
* la lecture de l'état de facturation fonctionne quand même ;
* checkout s'ouvre une fois les URL configurées.

### À configurer au déploiement

```bash
STRIPE_SUCCESS_URL=https://kivou.eu/checkout/success
STRIPE_CANCEL_URL=https://kivou.eu/checkout/cancel
STRIPE_PORTAL_RETURN_URL=https://kivou.eu/app/billing
```

Les alias de routes `/billing/success` → `/checkout/success` sont **conservés**
pour compatibilité, mais ils ne sont plus l'autorité : la configuration l'est.

---

## 4. Lien profond des alertes — relation de déploiement documentée

### Le rapport

> **Correction (2026-08-24, RTL-05).** Cette section annonçait que
> `KIVOU_PUBLIC_APP_URL` **devait inclure** le préfixe `/app`. C'est FAUX, et
> la consigne était dangereuse. Elle décrivait un constructeur qui n'existe
> plus : `signal_url()` ajoute lui-même `/app`. La variable désigne la **racine
> publique du site**. Le texte d'origine est conservé ci-dessous, barré, parce
> que staging portait exactement la valeur qu'il recommandait.

```text
Route navigateur du signal :   /app/signals/{signal_key}
Construction réelle du job :   {KIVOU_PUBLIC_APP_URL}/app/signals/{signal_key}
```

La base **ne doit donc PAS inclure** le préfixe `/app` :

```bash
KIVOU_PUBLIC_APP_URL=https://kivou.eu
  → https://kivou.eu/app/signals/{signal_key}   ✅
  → https://kivou.eu/reset-password?token=…     ✅
  → https://kivou.eu/app/notifications          ✅

KIVOU_PUBLIC_APP_URL=https://kivou.eu/app       ❌ ce que recommandait ce rapport
  → https://kivou.eu/app/app/signals/{clé}      préfixe dupliqué
  → https://kivou.eu/app/reset-password         route INEXISTANTE
```

~~Une base sans `/app` produirait `https://kivou.eu/signals/{clé}`, qui tombe à
côté du signal annoncé.~~ Les routes sont **asymétriques** : `/reset-password`
vit à la racine, `/app/signals/{clé}` et `/app/notifications` sous `/app`. Aucune
valeur unique de préfixe ne peut donc être portée par la variable — c'est le
backend qui ajoute la bonne route à chaque usage. La valeur exacte est
`https://kivou.eu` en production et `https://staging.kivou.eu` en staging.

### Ce qui a été fait

**Aucune sémantique d'alerte n'a été modifiée. Aucun renommage n'a été
nécessaire.** La construction du lien dans `alerts/job.py` est inchangée.

Deux changements, tous deux documentaires ou de test :

1. Le champ `public_app_url` de `ApiConfig` porte désormais un commentaire qui
   énonce la relation et donne la valeur attendue.
2. La fixture de test est passée de `https://app.kivou.ch` à
   **`https://kivou.test/app`** — elle reflète maintenant la **forme** réelle du
   déploiement, préfixe compris, au lieu d'un domaine obsolète.

Un test épingle le contrat :
`test_the_deep_link_resolves_to_the_browser_signal_route` vérifie que le lien de
l'e-mail contient bien `/app/signals/`.

---

## 5. Liste des territoires — décision produit rendue visible

Les 10 codes sont **inchangés** :

```text
FR  France          CH  Suisse         BE  Belgique
DE  Allemagne       IT  Italie         ES  Espagne
LU  Luxembourg      NL  Pays-Bas       AT  Autriche
PT  Portugal
```

La liste était enfouie dans `src/pages/IcpForm.tsx`, où elle se lisait comme un
détail de rendu. Elle vit désormais dans un module nommé,
**`src/api/capabilities.ts`**, avec les deux devises de seuil (`EUR`, `CHF`).

### Ce que la liste dit, et ce qu'elle ne dit pas

Le module le documente explicitement :

> Elle dit : voici les territoires que l'onboarding propose au MVP.
> Elle **ne dit pas** : voici les seuls pays présents dans TED.

TED couvre l'Espace économique européen entier. La restriction est une décision
de **périmètre produit** : proposer un pays dont Kivou ne traite pas encore les
avis produirait un profil complet et un flux vide, ce qui est pire qu'une liste
courte et honnête. Le backend, lui, accepte tout code ISO 3166-1 alpha-2 —
`TargetIcpInput.territories` n'impose aucune énumération.

**Aucune API de capacités backend n'a été inventée.**

`src/api/capabilities.test.ts` — 5 tests épinglent la liste, la forme ISO-2
majuscule, l'absence de doublon, la présence des deux traductions et les deux
devises. Un ajout ou un retrait fera échouer ce fichier, pour que le changement
de périmètre soit **revu** plutôt que constaté par un client au flux vide.

---

## 6. Ce qui est resté gelé

Aucune modification de : composition du design, routes frontend, sémantique du
paywall, grants Découverte, logique de facturation, sémantique des signaux,
retour client, cadence d'alerte, analytique, Signal Engine, Acquisition Engine.

Aucune implémentation Hermes n'existe dans le frontend client — vérifié : le mot
n'apparaît nulle part sous `frontend/`.

Les seuls fichiers Python touchés le sont pour l'item 3 (configuration) et les
fixtures/tests qui en dépendent.

---

## 7. Gates

### Frontend

```text
npm test -- --run   →  10 fichiers, 84 tests, 84 passés, 0 ignoré
npm run build       →  ✓ built
                       index.css   64,05 ko (10,85 ko gz)
                       index.js   365,47 ko (113,79 ko gz)
                       9 .woff2   194 ko émis · 65 ko réellement téléchargés
npx tsc -b          →  0 erreur
npm run lint        →  0 problème
```

84 tests = 74 de SPEC-015 + 5 (polices) + 5 (capacités).

### Backend

```text
uv run pytest -q      →  2724 passed in 228.62s, 0 ignoré
uv run ruff check .   →  All checks passed!
git diff --check      →  propre
```

**2724 tests** = 2712 de référence + 11 (URL de retour) + 1 (lien profond).
Aucune régression : les 2712 tests d'origine passent tous.

### Vérification navigateur

14 écrans recapturés après le changement de polices — rendu identique, aucun
débordement horizontal à 1440 / 1024 / 768 / 390 px. Audit d'accessibilité du
feed rejoué : **0 violation**.

---

## 8. État du dépôt

### `git status --porcelain`

```text
 M .gitignore
 M src/signals/api/config.py
 M src/signals/api/routes_billing.py
 M tests/billing_helpers.py
 M tests/engagement_helpers.py
 M tests/feed_helpers.py
 M tests/test_accounts_security.py
 M tests/test_accounts_target_icp.py
 M tests/test_alerts_cycle.py
 M tests/test_billing_checkout.py
 M tests/test_billing_checkout_lock.py
 M tests/test_billing_single_subscription.py
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx
?? docs/designPattern/
?? docs/reports/2026-08-17-spec006-postmortem.md
?? docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md
?? docs/reports/2026-08-18-spec015-design-intake.md
?? docs/reports/2026-08-18-spec015-frontend-mvp.md
?? docs/reports/spec015-ui/
?? frontend/
?? src/signals/research/spec009c.py
?? src/signals/research/spec009c_run.py
?? tests/fixtures/signal100/spec009c_blind.json
?? tests/test_billing_return_urls.py
?? tests/test_spec009c_bench.py
```

### `git diff --stat`

```text
 .gitignore                                |  5 ++
 src/signals/api/config.py                 | 88 ++++++++++++++++++++++---------
 src/signals/api/routes_billing.py         |  7 +++
 tests/billing_helpers.py                  | 17 ++++++
 tests/engagement_helpers.py               |  6 ++-
 tests/test_alerts_cycle.py                | 20 +++++++
 tests/test_billing_checkout.py            |  3 +-
 tests/test_billing_checkout_lock.py       |  2 +
 tests/test_billing_single_subscription.py |  2 +
 tests/feed_helpers.py                     |  5 +-
 tests/test_accounts_security.py           |  4 +-
 tests/test_accounts_target_icp.py         |  3 +-
 12 files changed, 133 insertions(+), 30 deletions(-)
```

### Fichiers du commit SPEC-015 attendu

| Bloc | Fichiers |
|---|---:|
| `frontend/` — application | 91 |
| `docs/designPattern/` — source de design | 29 |
| `docs/reports/spec015-ui/` — captures QA | 20 |
| `docs/reports/2026-08-18-spec015-design-intake.md` | 1 |
| `docs/reports/2026-08-18-spec015-frontend-mvp.md` | 1 |
| `docs/reports/2026-08-19-spec015-closeout.md` | 1 |
| `tests/test_billing_return_urls.py` | 1 |
| Modifiés : `.gitignore`, `config.py`, `routes_billing.py`, 9 fichiers de test | 12 |
| **Total** | **156** |

`node_modules/` et `frontend/dist/` sont ignorés.

**N'appartiennent PAS à SPEC-015** et doivent rester hors du commit — ils
préexistent :

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

## 9. Verdict

```text
SPEC-015 READY TO COMMIT
```

Les trois points de closeout sont traités, et le quatrième documenté :

1. **Design suivi** — 29 fichiers, 23,95 Mo, `:Zone.Identifier` exclus par une
   règle globale qui nettoie tout le dépôt.
2. **Polices réellement livrées** — auto-hébergées au build depuis deux paquets
   OFL verrouillés ; deux requêtes same-origin mesurées, **zéro tiers**, aucun
   binaire committé, aucun repli dans le chemin normal, 5 tests de garde.
3. **Défaut Stripe supprimé** — plus aucune URL par défaut, échec explicite au
   démarrage pour un déploiement qui encaisse, 503 net à l'exécution, 11 tests.
4. **Territoires** — 10 codes inchangés, déplacés dans un module nommé,
   décision documentée comme périmètre MVP et non comme limite de TED.

84 tests frontend, 2724 tests backend, aucun ignoré. Build, typecheck, lint et
ruff propres.

**Deux décisions vous appartiennent** et ne bloquent pas le commit :
la duplication de la directive de design (§1), et le poids du DOCX dans
l'historique (§1).

**Rien n'a été committé. Rien n'a été déployé. Stripe n'a pas été touché.**
