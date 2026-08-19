# SPEC-015 — Frontend MVP + Design System Integration

**Date :** 18–19 août 2026
**Verdict :** voir §22.

---

## 1. Entry gate

```text
7bdcdce feat(saas): add alerts feedback and analytics   ← SPEC-014
1965c8a feat(saas): add Stripe billing and paywall      ← SPEC-013
3757678 feat(saas): add customer signal feed
1d894eb feat(saas): add account auth and ICP onboarding
30d431c feat(saas): add signal persistence foundation
```

**SHA du commit SPEC-014 : `7bdcdce`.** Il est bien présent après le commit de
facturation SPEC-013. Aucun travail non committé d'une SPEC antérieure n'a été
absorbé : le seul code produit ici vit sous `frontend/`.

---

## 2. Design Intake — synthèse

Le rapport complet est `docs/reports/2026-08-18-spec015-design-intake.md`. En
résumé :

* **17 fichiers de design** inspectés intégralement — directive maître (30
  sections), README, manifeste d'assets, spécification DOCX (~1 600 lignes de
  texte extrait, 10 images), 3 fichiers de tokens, 8 planches de référence, la
  planche de marque et 12 fichiers de logo.
* Le langage visuel est **entièrement exécutable** : palette, typographie,
  échelle, rayons, ombres et motion viennent de fichiers, pas d'une lecture
  d'image.
* Les écrans clients principaux — landing, shell SaaS, feed, détail, mobile,
  checkout — sont **tous** couverts par une référence approuvée.
* Les écrans d'authentification, d'onboarding et de réglages **ne le sont pas**
  et ont été extrapolés sous contrainte stricte, sans introduire une seule
  couleur, un seul rayon ou une seule famille typographique nouvelle.
* **Quatre conflits** ont été tranchés explicitement (§4 ci-dessous). Aucun par
  moyenne silencieuse.

### Références exactement utilisées

| Référence | Ce qu'elle gouverne dans le code livré |
|---|---|
| `04-approved-direction-client-signal-feed.png` | Shell SaaS, sidebar 240 px, carte de signal, panneau de détail, barre d'actions |
| `02-approved-direction-marketing-home.png` | Header public, hero deux colonnes, chaîne de valeur 01→05, trois preuves, footer |
| `03-approved-direction-mobile.png` | Hero mobile, carte verticale, tuiles de méta, CTA pleine largeur |
| `01-approved-direction-saas-overview.png` | Cohérence d'ensemble, palette appliquée, rapport landing / SaaS / mobile |
| `06-approved-direction-checkout.png` | Composition du panneau de marque des écrans d'authentification |
| `07-approved-direction-illustrations.png` | Les quatre illustrations modulaires, recréées en SVG |
| `kivou-brand-board-clean.png` | Vérification de la palette nommée et de la direction |
| `tokens/kivou.tokens.css` + `.json` | **Autorité** des tokens : couleurs, typographie, espacement, rayons, ombres, motion |
| `brand/logo/kivou-mark.svg`, `kivou-favicon.svg` | Symbole radial et favicon, repris tels quels |
| `05-…-internal-weekly-cockpit.png`, `08-…-internal-funnel-table.png` | **Inspectées, non implémentées** — cockpit interne hors scope (§41) |

### Inventaire des assets embarqués au runtime

| Asset | Origine | Poids |
|---|---|---|
| `frontend/public/brand/kivou-mark.svg` | copié du pack, inchangé | 1,7 ko |
| `frontend/public/brand/kivou-favicon.svg` | copié du pack, inchangé | 1,7 ko |
| Symbole radial inline (`KivouMark`) | redessiné en JSX depuis `kivou-mark.svg`, géométrie identique | ~1,3 ko |
| 4 illustrations modulaires | **recréées** en SVG géométrique | ~4 ko au total |
| `ArchitecturalHero` | composition vectorielle | ~2 ko |
| 18 icônes | tracées à la main, trait 1,5, monochromes | ~3 ko |

**Aucune planche de référence n'est embarquée.** Elles restent dans `docs/` et
ne sont jamais servies au navigateur. Les originaux du pack n'ont pas été
modifiés.

---

## 3. Technologie retenue et justification

Le dépôt ne contenait **aucun** `package.json`, aucun répertoire frontend, aucun
système de style JS. Il n'existait donc pas de stack à réutiliser, et aucun
matériau fourni ne contient d'implémentation exécutable.

```text
React 19 + TypeScript 5.7 + Vite 7
CSS custom properties + CSS Modules
React Router 7
Vitest 3 + Testing Library
```

**Tailwind est écarté** malgré la présence d'un preset dans le pack. La
directive est explicite : « NE PAS FORCER TAILWIND — si le dépôt n'utilise pas
Tailwind, consommer les tokens CSS/JSON dans le système déjà présent ; le design
system ne justifie pas à lui seul une migration de stack. » Le fichier
`kivou.tokens.css` livré est déjà exactement la forme attendue par un système
CSS custom properties : c'est le format qui reproduit le design avec le moins
d'interprétation.

**Next.js est écarté** : aucun besoin de SSR pour une application authentifiée.

Aucun Redux, aucune bibliothèque UI, aucun GraphQL, aucun BFF, aucune
bibliothèque d'icônes, aucune bibliothèque d'internationalisation.

---

## 4. Conflits de design tranchés

1. **Typographie.** La planche 01 affiche « PP Neue Montreal » ; la directive,
   les tokens CSS/JSON et le DOCX spécifient **Lora + Instrument Sans**.
   → **Lora + Instrument Sans.** Les tokens sont la source d'autorité
   auto-déclarée, la planche est une référence de direction dont « le contenu
   textuel n'est pas contractuel », et PP Neue Montreal est sous licence
   commerciale alors que le manifeste interdit de committer des polices.
2. **Prix.** La référence 06 affiche 59 €.
   → **0 / 49 / 99 / 199, lus depuis `GET /billing/plans`.** Le conflit est déjà
   tranché par les sources elles-mêmes (directive §2.2.4, README, DOCX).
3. **Navigation SaaS.** La référence 04 montre 8 entrées ; 4 d'entre elles
   (`Entreprises`, `Marchés`, `Veille`, `Notes`) n'ont **aucun endpoint** dans
   `src/signals/api/`.
   → **Géométrie de sidebar conservée à l'identique, entrées réduites aux
   fonctions réellement servies.** Afficher une navigation vers une
   fonctionnalité inexistante la promettrait, ce que la Definition of Done
   interdit (point 9).
4. **Checkout.** La référence 06 dessine un formulaire carte complet.
   → **Composition reprise, champs carte non reproduits.** La directive §17 et
   le DOCX le disent en toutes lettres ; SPEC-015 §24 confirme la redirection
   vers l'URL Stripe hébergée.

---

## 5. Carte des routes

```text
PUBLIC
/                        landing marketing
/login                   connexion
/signup                  inscription
/forgot-password         demande de réinitialisation
/reset-password          confirmation (jeton en query)

AUTHENTIFIÉ
/onboarding              création du premier profil de ciblage
/app                     → /app/signals
/app/signals             feed
/app/signals/:signalKey  détail
/app/icps                profils de ciblage (liste, création, édition)
/app/billing             offres, statut, portail
/app/notifications       préférences d'alerte
/checkout/success        retour Stripe — NE DONNE AUCUN ACCÈS
/checkout/cancel         annulation — aucune mutation

ALIAS
/billing/success  → /checkout/success
/billing/cancel   → /checkout/cancel
/billing          → /app/billing
```

**Le préfixe `/app` évite la collision avec l'API servie sur la même origine** :
`GET /signals` appartient au backend, `/app/signals` au navigateur.

**Sur les alias :** `ApiConfig` définit par défaut `stripe_success_url =
https://app.kivou.ch/billing/success` et `stripe_cancel_url = .../billing/cancel`.
La SPEC impose `/checkout/success` et `/checkout/cancel`. Les URL canoniques sont
donc celles de la SPEC, et les trois alias garantissent que le parcours reste
intact même si les variables d'environnement `KIVOU_STRIPE_SUCCESS_URL` /
`KIVOU_STRIPE_CANCEL_URL` ne sont pas renseignées au déploiement. **Aucun
changement backend n'a été fait.**

---

## 6. Structure et composants

```text
frontend/
  src/
    api/       client.ts · endpoints.ts · types.ts · errorCopy.ts
    auth/      SessionProvider.tsx · RequireAuth.tsx
    components/ KivouLogo · Button · FormField · Surfaces · FullPageLoader
    layouts/   AppShell · PublicLayout · AuthLayout
    pages/     Landing · Login · Signup · PasswordReset · Onboarding ·
               SignalsFeed · SignalDetail · Icps · IcpForm · Billing ·
               Checkout · Notifications · NotFound
    signals/   SignalCard · EvidenceGroup · NeedList · DiscoveryPanel
    billing/   PlanGrid
    feedback/  FeedbackControl
    i18n/      index.tsx · fr.ts · en.ts
    assets/    Illustrations.tsx · Icons.tsx
    styles/    tokens.css · global.css
  public/brand/
```

**88 fichiers versionnables**, dont 77 sous `src/`. `node_modules/` et `dist/`
sont ignorés. **12 543 lignes** de TS/TSX/CSS.

Les composants réutilisables ont été créés là où la répétition est réelle :
`Button`, `TextField`/`SelectField`/`TextAreaField`/`CheckboxGroup`/`Switch`,
`Card`, `Badge`, `Callout`, `EmptyState`, `Skeleton`, `SectionHeading`,
`DataList`, `SignalCard`, `LockedSignalCard`, `EvidencePanel`, `NeedList`,
`PlanGrid`, `FeedbackControl`, `DiscoveryPanel`. Aucun système de 70 composants
n'a été construit avant l'application.

---

## 7. Tokens de design dérivés

`src/styles/tokens.css` reprend `kivou.tokens.css` du pack et n'ajoute que des
rôles sémantiques réellement consommés :

* **couleur** : 13 primitives du pack + `--kivou-nav-active-bg` (fond vert très
  doux de la navigation active, exigé par la directive §5) et
  `--kivou-select-bg` (teinte de sélection observée en référence 04) ;
* **typographie** : deux familles, échelle 64/52/32/26/20/16/14/12 en `clamp()`
  sur les displays, plancher de 16 px dans les champs ;
* **espacement** : base 4 px, sections marketing 96→144 px en `clamp()`,
  gouttières 32 px desktop / 20 px mobile ;
* **rayons** : 10 / 14 / 18 / 24 / 999 px ;
* **ombres** : les deux ombres chaudes du pack, sans ajout ;
* **motion** : 120 / 180 / 260 ms, easing `cubic-bezier(.2,0,0,1)` ;
* **conteneurs** : 720 / 1280 / 1440 px, sidebar 240 px ;
* **contrôles** : 44 px, 48 px en CTA mobile.

**Aucun hex n'apparaît hors de `tokens.css`.**

### Deux valeurs corrigées pour conformité — et pourquoi

1. `--kivou-color-text-muted` : le pack livre `#7B827E`, mesuré à **3,66:1** sur
   l'ivoire, sous le seuil AA de 4,5:1 pour du petit texte. Assombri en
   `#5C6561` (5,59:1 sur canvas, 5,92:1 sur surface, 4,56:1 sur le beige des
   badges), teinte gris-vert conservée.
2. **Anneau de focus** : le laiton seul plafonne à **2,87:1**, sous les 3:1
   qu'exige SC 1.4.11 pour un indicateur non textuel. La couleur de marque est
   conservée ; un halo d'encre extérieur porte le contraste.

Ce ne sont pas des écarts à la direction artistique : le design system exige
lui-même WCAG 2.2 AA (§21), et la directive §7.1 interdit déjà le laiton pour du
petit texte — règle appliquée en retirant le laiton du numéro d'étape de la
chaîne de valeur.

---

## 8. Frontière d'API

`src/api/client.ts` est la **seule** frontière HTTP. Aucun composant n'appelle
`fetch`.

* URL **relatives** — même origine en production, proxy Vite en développement,
  ce qui reproduit la condition que `enforce_origin` exige sur toute requête
  modifiante ;
* `credentials: 'same-origin'` — le cookie de session est HttpOnly ;
* **aucun jeton porteur, jamais** : rien n'est écrit dans `localStorage`,
  `sessionStorage` ou l'état JS ;
* codes d'erreur stables typés depuis `signals.api.errors.ERROR_CODES` ;
* 401 → diffusion **unique** vers la session, qui décide ; la frontière ne
  navigue pas, ce qui évite la boucle « 401 → redirection → requête → 401 » ;
* 422 pydantic → erreurs reconstruites **par champ** ;
* panne réseau → `network_error`, jamais une exception brute ;
* **aucune requête ne porte d'`account_id`** — vérifié par test sur l'ensemble
  des appels émis.

États d'erreur rendus comme états produit : identifiants invalides, session
expirée, validation, ressource étrangère/introuvable, filtre non autorisé,
signal verrouillé, paiement déjà ouvert, déjà abonné, facturation indisponible,
aucun dossier de facturation, origine refusée. **Aucune trace, aucune erreur SQL
n'atteint l'écran** — vérifié par test.

---

## 9. Authentification et session

`GET /me` est la **seule** autorité. Trois états explicites : `loading`,
`authenticated`, `unauthenticated`.

`loading` **ne redirige pas** — traiter « je ne sais pas encore » comme « non
connecté » renverrait chaque rechargement vers la connexion puis vers
l'application, l'aller-retour que §11 appelle une boucle.

La destination d'un utilisateur authentifié vit dans une seule fonction,
`homeFor(me)` : un compte sans profil exploitable va à l'onboarding, un compte
prêt au feed. Elle est partagée par le formulaire de connexion et par la garde
de route ; la dupliquer les aurait fait diverger, et un compte incomplet aurait
atterri sur un feed vide.

Session expirée → état nettoyé, retour à la connexion **avec le motif affiché**.

---

## 10. Onboarding

Cinq questions, exactement le contrat `TargetIcpInput` : ce que vous vendez
(7 catégories), à quels corps de métier (8, facultatif), où vous intervenez
(territoires ISO-2), à partir de quel montant, et une description libre inerte.

Le vocabulaire moteur — `NeedCategory`, `TradeDomain`, `geography_basis`,
`unknown_value_policy`, `source_modes_allowed` — **n'apparaît nulle part** :
vérifié par test. Aucune option n'est inventée ; toutes proviennent des `Literal`
du backend.

La complétude est rendue comme un **résultat**, dans les mots du client
(« Prêt pour les signaux » / « Informations manquantes : ce que vous vendez, où
vous pouvez intervenir, le montant minimum »), jamais comme `draft`,
`icp_incomplete` ou `ready_for_signals` bruts.

La liste des territoires est bornée à 10 pays réellement couverts par les
sources (BOAMP/DECP, SIMAP, TED) : en proposer davantage promettrait un flux qui
resterait vide.

---

## 11. Feed

`GET /signals` est la **seule** source. Le frontend ne rejoue ni le classement,
ni la fraîcheur, ni la décision de verrouillage.

États implémentés : chargement (squelette reprenant la structure de la carte),
résultats, feed vide, aucun profil actif, erreur récupérable avec reprise,
pagination, lecture bornée annoncée (`scan_truncated`).

La pagination **déduplique sur `signal_id`** : deux pages qui se recouvrent —
parce que la fraîcheur a été réévaluée entre deux appels — ne produisent pas
deux cartes du même signal. Vérifié par test.

La preuve documentaire **n'apparaît pas** sur une carte de feed : elle appartient
au détail. Vérifié par test.

---

## 12. Paywall

Le teaser rend **uniquement** les champs de `paywall.locked_teaser` : statut,
date, `why_now`, pays, secteur, ordre de grandeur, nombre de besoins, et la
phrase sans sujet nommé. Il ne tente à aucun moment de reconstituer
l'attributaire depuis l'URL, un identifiant de source, un cache ou une autre
réponse.

Vérifié par test, sur la carte **et** sur le détail verrouillé : ni le nom
(`Constructions Bertrand`), ni le SIRET, ni l'intitulé du marché, ni l'URL
source, ni le montant exact n'apparaissent — seul l'ordre de grandeur.

CTA : « Déverrouiller Kivou » / « Voir les offres », jamais une formulation
d'extraction de données cachées. Aucun contrôle de retour n'est rendu sur un
signal verrouillé.

**Découverte** : le panneau affiche le nombre **réel** de déblocages — 0, 1, 2 ou
3 — et dit que ces déblocages sont acquis définitivement, qu'ils ne se
renouvellent pas et n'expirent pas. Vérifié par test, y compris le cas « moins de
trois signaux éligibles ».

---

## 13. Détail

La séparation **FAITS / ANALYSE** est portée par la structure, pas par une nuance
de gris : deux `<section>` nommées avec en-têtes distincts, un liseré laiton sur
toute la hauteur de la carte d'analyse. Vérifié par test — l'acheteur est dans
les faits, le besoin plausible dans l'analyse, et jamais l'inverse.

Les **trois dates** (attribution, notification, publication) sont affichées
séparément. La phrase de fraîcheur, le `why_now` et le complément
`award_date_note` viennent de `recency.claim` et ne sont jamais reformulés.

La note « ces besoins sont plausibles » précède la liste et n'est pas masquée.
Chaque besoin porte son raisonnement, sa fenêtre, et un marqueur explicite quand
il correspond au profil du client.

**Preuve** : groupes repliés par défaut, dépliables. `public_facts` et
`analysis_inputs` restent séparés, et la mise en garde de l'API (« elles ne
prouvent pas un achat ») est rendue. Le lien source ouvre l'avis public en
`target="_blank" rel="noopener noreferrer"`. Aucun chemin local, aucune fixture,
aucun identifiant de règle moteur n'est rendu — vérifié par test.

---

## 14. Retour client

« Pertinent / Pas pertinent » (jugement) et « J'ai contacté cette entreprise »
(action) sont **deux commandes distinctes**, sur deux points d'entrée distincts.
Vérifié par test : marquer « contacté » n'écrit aucun avis de pertinence.

Les **six** raisons approuvées sont présentes, traduites FR/EN. Une raison est
exigée pour un avis négatif — refusé côté client avant l'aller-retour. La note
libre est bornée à 500 caractères (`MAXIMUM_NOTE_LENGTH`).

Le sens de « contacté » est écrit : « Cela ne dit rien d'une réponse, d'un
rendez-vous ou d'une affaire gagnée. » Une fois enregistré, l'état est confirmé
sobrement et l'action disparaît — aucun clic ne peut simuler une nouvelle
démarche. Aucune étape CRM (pipeline, relance, opportunité, négociation) n'est
fabriquée : vérifié par test.

---

## 15. Facturation et Stripe

Le navigateur n'envoie **que** `{ plan, currency }`. Vérifié par test : aucun
`price_`, aucun coupon, aucune `lookup_key`, aucun drapeau fondateur, aucun
`account_id`.

La devise est un **choix explicite** CHF/EUR, jamais déduite de la langue —
vérifié par test avec une locale française qui ne présélectionne pas l'euro.

Redirection vers l'URL Stripe **renvoyée par le backend**, jamais construite.
Aucune intégration Stripe.js.

`checkout_in_progress` → état non destructif, avec la date d'expiration renvoyée
par le backend, et **un seul appel** : aucune relance automatique.

Compte payant → « Gérer ma facturation » (portail Stripe) et **pas** de second
paiement proposé. `no_billing_customer` géré. Aucun écran de moyen de paiement,
de facture ou de résiliation n'est reconstruit. Aucune mention Turiya.

**Page de succès — la règle centrale.** Elle n'accorde **aucun** accès. Être
arrivé là ne prouve rien. La page relit `GET /billing/status` toutes les 2,5 s
pendant 45 s au maximum, puis rend la main avec « Actualiser » et « Voir ma
facturation ». Rien n'est jamais écrit depuis le navigateur. Vérifié par deux
tests : avec un backend qui dit encore `discovery`, aucun accès n'est proposé et
le titre reste « Paiement en cours de confirmation » ; l'accès n'apparaît que
lorsque l'état serveur a basculé.

**Page d'annulation** : aucune mutation, et aucun mot d'échec — quitter un
paiement n'est pas un refus de carte.

---

## 16. Notifications

L'adresse de réception est modifiable ; l'activation persiste. La **cadence est
en lecture seule**, dérivée de `billing/status → entitlements.alert_cadence` : la
proposer comme un choix laisserait croire qu'un compte Découverte peut s'abonner
à des alertes quotidiennes.

Scale dit **« Prioritaire »**. Vérifié par test : ni « temps réel », ni
« realtime », ni « instantané », ni « immédiat » n'apparaissent nulle part.

Découverte explique l'absence d'alertes plutôt que de la masquer. Une adresse
refusée est signalée **sur le champ concerné**, pas dans un bandeau redondant.

**Aucun historique de livraison n'est inventé** — la remise SMTP est un point de
déploiement. Vérifié par test.

---

## 17. FR / EN

Dictionnaires typés : `en.ts` est typé `typeof fr`, donc une clé ajoutée sans
traduction casse le typecheck. Un test compare en plus récursivement les deux
arbres de clés.

Aucun texte d'interface n'est écrit en dur dans un composant. `Intl.NumberFormat`
et `Intl.DateTimeFormat` sont utilisés avec la locale courante. Les codes
machine ne sont jamais traduits.

Les libellés que l'API renvoie déjà — `headline`, `why_now`, `award_date_note`,
libellés de besoin, motifs de fit, note sur les besoins plausibles — ne sont
**pas** dupliqués côté frontend : les traduire une seconde fois créerait deux
vérités.

Sélecteur FR/EN sur les surfaces publiques uniquement ; une fois connecté,
`account.locale` fait autorité et `document.documentElement.lang` suit.

**Un bug réel a été trouvé et corrigé par la QA visuelle** : les montants de
contrat s'affichaient `1,240,000 EUR` — séparateurs anglais — dans une interface
française, parce que le formatage utilisait la locale du navigateur. Ils
s'affichent désormais `1 240 000 €`. Un test verrouille la correction.

---

## 18. Responsive

Points d'arrêt de la directive : < 768 (mobile), 768–1023 (tablette), 1024–1439
(desktop), ≥ 1440 (wide).

Sidebar 240 px au-dessus de 1024 px, **tiroir** en dessous, fermé par Échap et
par la navigation. Détail en page complète sur mobile. Zones tactiles ≥ 44 px
partout, 48 px pour les CTA mobiles.

**Vérifié en navigateur réel à 1440, 1024, 768 et 390 px : aucun débordement
horizontal sur aucun des 14 écrans capturés** (`scrollWidth ≤ innerWidth` mesuré
à chaque prise).

---

## 19. Accessibilité

Objectif WCAG 2.2 AA. Décisions :

* boutons et liens **sémantiques** — ce qui navigue est un `<a>`, ce qui agit est
  un `<button>` ;
* labels **permanents**, jamais le placeholder comme seul label ; aide et erreur
  distinctes, toutes deux reliées par `aria-describedby` ;
* focus visible laiton + halo d'encre pour tenir 3:1 (SC 1.4.11) ;
* **un `h1` par page**, ordre de titres sans saut, y compris pendant le
  chargement du détail ;
* `<main>`, lien d'évitement, `aria-label` sur les listes et régions ;
* états jamais portés par la seule couleur : la sélection ajoute bordure, fond
  **et** graisse ; le verrouillage ajoute un liseré en tirets, une icône et un
  badge ; les erreurs portent un signe ;
* `aria-live` sur le paiement, les erreurs et les confirmations ;
* `prefers-reduced-motion` respecté (squelettes et spinner figés) ;
* `role="switch"` accompagné d'`aria-checked` explicite.

**Audit outillé** — moteur `@accesslint/core` contre le DOM réel, via CDP :

| Écran | Résultat final |
|---|---|
| Landing | **0 violation** |
| Connexion | **0 violation** |
| Inscription | **0 violation** |
| Mot de passe oublié | **0 violation** |
| Feed | **0 violation** |
| Détail débloqué | **0 violation** |
| Détail verrouillé | **0 violation** |
| Profils de ciblage | **0 violation** |
| Facturation | **0 violation** |
| Notifications | **0 violation** |
| Onboarding | **0 violation** |

**Quatre défauts réels trouvés par l'audit et corrigés :**

1. contraste 3,66:1 du gris « muted » du pack sur ivoire → assombri ;
2. contraste 2,87:1 de l'anneau de focus laiton → halo d'encre ajouté ;
3. saut de niveau de titre h1 → h3 sur les cartes de signal → passées en h2 ;
4. `role="switch"` sans `aria-checked` (critique) → attribut ajouté.

Un cinquième point mineur — l'écran de détail en chargement n'avait aucun titre
de niveau 1 — a été corrigé par un `h1` visuellement masqué portant l'état.

---

## 20. QA visuelle

**Capacité disponible :** Chromium 148 déjà présent sur la machine
(`~/.cache/ms-playwright/`), piloté en **CDP brut**. Aucune dépendance n'a été
ajoutée au projet pour produire des captures — Playwright n'a pas été installé,
conformément à §55.

**21 captures** sous `docs/reports/spec015-ui/`, 4 points d'arrêt, rendues sur le
bundle de production réel servi avec des charges utiles calquées sur les réponses
du backend. `probe.json` conserve pour chaque prise le titre, la structure de
titres et la mesure de débordement.

| Écran | Points d'arrêt capturés |
|---|---|
| Landing | 1440, 1024 (EN), 390 |
| Inscription | 1440, 390 |
| Connexion, mot de passe oublié | 1440 |
| Feed Découverte | 1440, 768, 390 |
| Détail débloqué | 1440, 390 |
| Détail verrouillé | 1440 |
| Facturation | 1440, 390 |
| Notifications, profils, onboarding, succès de paiement | 1440 |

**Comparaison aux références — écarts corrigés après inspection visuelle :**

* montants non localisés (§17) ;
* H1 du hero sur cinq lignes au lieu des trois de la référence 02 → mesure
  élargie ;
* masse de marbre vert du hero trop pâle et rognée → composition redessinée en
  format paysage, arche, escalier courbe, paroi cannelée et masse verte
  désormais lisibles comme sur la référence.

**Correspondance jugée fidèle** sur : sidebar 240 px et ses trois zones,
composition de la carte de signal, panneau de détail et son rail de fit,
traitement verrouillé, grille tarifaire avec la bande Forest Green de Pro,
hiérarchie éditoriale serif/sans, palette minérale, rythme d'espacement.

---

## 21. Gates

### Frontend

```text
npm test -- --run      →  8 fichiers, 74 tests, 74 passés
npm run build          →  ✓ built — 59,12 ko CSS (9,23 ko gz)
                                    365,41 ko JS (113,75 ko gz)
npx tsc -b             →  0 erreur
npm run lint           →  0 problème
```

Répartition des tests : authentification 10 · onboarding et profils 6 · feed 13 ·
détail 7 · retour client 7 · facturation 13 · notifications 7 · frontière d'API,
secrets et localisation 11.

**Aucun test ignoré.** Aucun appel à Stripe, aucun SMTP : la frontière HTTP est
remplacée par un routeur déterministe.

### Backend — non-régression

```text
uv run pytest -q       →  2712 passed in 243.48s
uv run ruff check .    →  All checks passed!
git diff --check       →  propre
```

**2 712 tests**, identique au relevé de référence pris avant toute modification.
Aucun fichier Python n'a été touché.

### Dépendances ajoutées

Runtime : `react`, `react-dom`, `react-router-dom`.
Développement : `typescript`, `vite`, `@vitejs/plugin-react`, `vitest`, `jsdom`,
`@testing-library/{react,dom,jest-dom,user-event}`, `eslint` +
`typescript-eslint` + 2 plugins React, `globals`, `@types/{node,react,react-dom}`.

Aucune bibliothèque UI, d'icônes, d'internationalisation, d'état global, de
graphiques ou de télémétrie.

### `git status --porcelain`

```text
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx:Zone.Identifier
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx:Zone.Identifier
?? docs/designPattern/
?? docs/reports/2026-08-17-spec006-postmortem.md
?? docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md
?? docs/reports/2026-08-18-spec015-design-intake.md
?? docs/reports/spec015-ui/
?? frontend/
?? src/signals/research/spec009c.py
?? src/signals/research/spec009c_run.py
?? tests/fixtures/documents/heldout3_gold.json:Zone.Identifier
?? tests/fixtures/documents/heldout3_gold.sha256.txt:Zone.Identifier
?? tests/fixtures/signal100/spec009c_blind.json
?? tests/test_spec009c_bench.py
```

### `git diff --stat`

**Vide.** Aucun fichier suivi n'a été modifié. La totalité de SPEC-015 est
additive : `frontend/` (88 fichiers versionnables, `node_modules/` et `dist/`
ignorés), les deux rapports et le dossier de captures.

Les entrées `spec009c`, `spec006`, les `.docx` et les `Zone.Identifier`
**préexistent à SPEC-015** et n'en font pas partie.

---

## 22. Scope respecté

Aucune modification de : Signal Engine, Need Graph, matching, récence,
sémantique d'Evidence, tarification, catalogue Stripe, sémantique d'abonnement,
logique de grant Découverte, définitions analytiques, cadences d'alerte,
Acquisition Engine. **Aucun fichier Python n'a été touché.**

Aucune opération Stripe (§58). Aucun SMTP (§59). Aucune analytique frontend
ajoutée (§31). Aucun dashboard interne (§41). Aucun déploiement (§61).

Aucun secret dans le bundle — vérifié par un test qui balaie l'ensemble de
`src/` à la recherche de `sk_live`, `sk_test`, `rk_live`, `whsec_`, de mots de
passe SMTP littéraux et de variables `VITE_*` nommant un secret.

---

## 23. Écarts restants et décisions humaines requises

1. **Textures photographiques manquantes.** Le manifeste appelle une texture
   travertin seamless et un marbre vert en WebP/AVIF. **Elles ne sont pas
   fournies dans le pack et n'ont pas été substituées** — §39 interdit de
   remplacer silencieusement par de l'imagerie de banque. La composition
   architecturale est rendue en dégradés minéraux et formes vectorielles issues
   de la palette approuvée, ce qui préserve la géométrie et le rapport de
   valeurs. **Décision requise :** livrer les deux textures, ou valider la
   version vectorielle.

2. **Revue optique et disponibilité de marque du logo.** Le manifeste la
   demande avant lancement public. Non faite ici : hors scope frontend.

3. **Assets de diffusion non produits** : image OG 1200×630 et en-tête d'email
   1200×400. Ils appartiennent au déploiement et à la remise SMTP, tous deux
   hors scope (§59, §61).

4. **`stripe_success_url` / `stripe_cancel_url`.** Les valeurs par défaut de
   `ApiConfig` pointent vers `/billing/success` et `/billing/cancel`, et le
   domaine `app.kivou.ch` alors que la SPEC vise `kivou.eu`. Le frontend sert
   les deux couples d'URL, donc rien n'est cassé. **À trancher au déploiement :**
   renseigner `KIVOU_STRIPE_SUCCESS_URL`, `KIVOU_STRIPE_CANCEL_URL`,
   `KIVOU_STRIPE_PORTAL_RETURN_URL` et `KIVOU_ALLOWED_ORIGIN` sur le domaine
   retenu.

5. **QA visuelle sur données de fixtures.** Les captures ont été prises contre un
   serveur de fixtures reproduisant les réponses réelles, pas contre le backend
   avec une base peuplée. Le comportement est couvert par les 74 tests contre le
   contrat ; la **fidélité visuelle avec des données de production réelles**
   reste à confirmer en staging.

6. **Portail client Stripe et webhook** restent les gates d'opérations hérités de
   SPEC-013.

---

## 24. Verdict

```text
FRONTEND MVP READY
```

Le parcours navigateur complet du MVP est implémenté et vérifié : landing →
inscription → onboarding ICP → feed → détail avec preuve → retour client →
facturation → redirection Stripe → retour de paiement → notifications. Les 74
tests frontend passent, le build, le typecheck et le lint sont propres, les
2 712 tests backend sont intacts, et les onze écrans audités ne présentent
aucune violation d'accessibilité.

Les points listés en §23 sont des **gates de déploiement et une décision
d'asset**, pas des blocages fonctionnels : aucun n'empêche l'application de
fonctionner de bout en bout. Le seul écart de fidélité visuelle assumé est
l'absence des deux textures photographiques, qui n'ont pas été fournies et
qu'il aurait fallu inventer pour combler.

**Rien n'a été committé. Rien n'a été déployé. Stripe n'a pas été touché.**
En attente de revue superviseur.
