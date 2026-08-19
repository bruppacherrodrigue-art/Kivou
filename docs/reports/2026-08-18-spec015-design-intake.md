# SPEC-015 — Design Intake Report

**Date :** 18 août 2026
**Entry gate :** SPEC-014 committé — `7bdcdce feat(saas): add alerts feedback and analytics`
**Objet :** inventaire complet des matériaux de design fournis, avant toute écriture de code frontend.

Ce rapport est produit **avant** l'implémentation. Il n'invente rien : chaque
ligne est adossée à un fichier réellement inspecté sous `docs/designPattern/`.

---

## A. Fichiers source inspectés

Tous les fichiers ci-dessous ont été ouverts et lus intégralement. Les fichiers
`*:Zone.Identifier` sont des métadonnées NTFS produites par le transfert
Windows→WSL ; ils ne portent aucun contenu de design et sont ignorés.

| Fichier | Nature | Rôle |
|---|---|---|
| `docs/designPattern/KIVOU_CLAUDE_CODE_DESIGN_DIRECTIVE.md` | Markdown, 30 sections | Directive maître |
| `docs/designPattern/Kivou_Design_System_v1_0/KIVOU_CLAUDE_CODE_DESIGN_DIRECTIVE.md` | Markdown | **Copie identique** de la précédente (`diff` vide) — aucun conflit |
| `.../Kivou_Design_System_v1_0/README.md` | Markdown | Ordre de lecture + vérité tarifaire |
| `.../Kivou_Design_System_v1_0/ASSET_MANIFEST.md` | Markdown | Inventaire d'assets + assets à recréer |
| `.../Kivou_Design_System_v1_0/docs/KIVOU_DESIGN_SYSTEM_v1.0.docx` | DOCX, ~1600 lignes de texte extrait, 10 images | Spécification illustrée complète |
| `.../Kivou_Design_System_v1_0/tokens/kivou.tokens.css` | CSS | **Tokens exécutables** — autorité |
| `.../Kivou_Design_System_v1_0/tokens/kivou.tokens.json` | JSON (DTCG) | Tokens structurés, échelles complètes |
| `.../Kivou_Design_System_v1_0/tokens/kivou.tailwind.preset.ts` | TypeScript | Preset Tailwind — **non utilisé**, voir §F |
| `.../assets/kivou-brand-board-clean.png` | PNG 1800×1100 | Planche d'identité propre |
| `.../assets/reference/01..08-*.png` | 8 PNG | Références de direction approuvées |
| `.../brand/logo/*.svg` (6 fichiers) | SVG | Suite logo, drafts de production |
| `.../brand/logo/*.png` (6 fichiers) | PNG | Aperçus PNG des mêmes logos |

Aucun autre répertoire de `docs/` ne contient de matériel de design
(`docs/reports/` = rapports d'ingénierie, `docs/superpowers/` = skills).

---

## B. Inventaire des assets visuels

### B.1 — Logos (`brand/logo/`)

| Fichier | Format | Dimensions | Poids | Objet observé |
|---|---|---|---|---|
| `kivou-mark.svg` | SVG | viewBox 0 0 100 100 | 1,7 ko | Symbole radial : 8 rayons brisés + 8 points, trait `#B08D57` |
| `kivou-mark.png` | PNG | 800×800 | 21 ko | Aperçu du symbole |
| `kivou-logo-horizontal.svg` | SVG | 760×180 | 2,1 ko | Symbole + wordmark `KIVOU` + baseline, en `<text>` vivant |
| `kivou-logo-horizontal.png` | PNG | 1200×284 | 25 ko | Aperçu |
| `kivou-logo-horizontal-monochrome-dark.svg/.png` | SVG/PNG | 760×180 / 1600×379 | 2,1 / 35 ko | Une seule couleur, fonds clairs |
| `kivou-logo-horizontal-monochrome-light.svg/.png` | SVG/PNG | 760×180 / 1600×379 | 2,1 / 27 ko | Une seule couleur, fonds sombres |
| `kivou-logo-stacked.svg/.png` | SVG/PNG | — / 800×800 | 2,3 / 31 ko | Lockup empilé, largeur contrainte |
| `kivou-favicon.svg` | SVG | 128×128 | 1,7 ko | Symbole brass sur carré Deep Ink, `rx=28` |
| `kivou-favicon.png` | PNG | 800×800 | 28 ko | Aperçu |

**Observation technique importante.** Les SVG de lockup composent le wordmark
avec un élément `<text font-family="Instrument Sans, Inter, Arial">`. Un SVG
n'embarquant pas de police, le rendu dépend de la police disponible chez le
visiteur — un même fichier donnera deux lockups différents selon le poste. Le
manifeste interdit par ailleurs de livrer des fichiers de police propriétaires.

**Décision retenue :** en production, le symbole (`kivou-mark.svg`, purement
géométrique, donc rendu identique partout) est utilisé comme asset, et le
wordmark est composé en **texte HTML réel** avec la même famille, la même
graisse (500) et le même interlettrage (`0.16em` ≈ 8/74 em mesuré dans le SVG).
Le lockup reste ainsi typographiquement cohérent avec le reste de l'interface,
sélectionnable, traduisible pour les lecteurs d'écran, et net à toute taille.
Les SVG de lockup fournis restent la référence de proportions.

### B.2 — Planches de référence (`assets/reference/`)

| Fichier | Dimensions | Poids | Objet observé |
|---|---|---|---|
| `01-approved-direction-saas-overview.png` | 1672×941 | 1,7 Mo | Écosystème : landing + shell SaaS + mobile + palette + chaîne de valeur |
| `02-approved-direction-marketing-home.png` | 1672×941 | 1,9 Mo | Homepage marketing complète, header→footer |
| `03-approved-direction-mobile.png` | 941×1672 | 1,4 Mo | Deux écrans mobiles : hero landing, carte signal + chaîne de valeur |
| `04-approved-direction-client-signal-feed.png` | 1672×941 | 1,4 Mo | **Référence principale du SaaS client** : sidebar, feed, détail |
| `05-approved-direction-internal-weekly-cockpit.png` | 1672×941 | 1,5 Mo | Cockpit interne — **hors scope SPEC-015** (§41) |
| `06-approved-direction-checkout.png` | 1448×1086 | 1,6 Mo | Composition checkout : panneau marque + récapitulatif |
| `07-approved-direction-illustrations.png` | 1448×1086 | 1,7 Mo | 4 illustrations modulaires |
| `08-approved-direction-internal-funnel-table.png` | 1672×941 | 1,5 Mo | Tableau segmenté interne — **hors scope SPEC-015** (§41) |
| `kivou-brand-board-clean.png` | 1800×1100 | 80 ko | Palette nommée + direction + 6 valeurs de marque |

Le manifeste qualifie ces images de *composite design-direction boards* : elles
gouvernent **la composition, l'espacement, la matière, la palette et la
hiérarchie**, jamais le contenu. Aucune n'est copiée dans l'application ; elles
restent dans `docs/` et ne sont pas embarquées au runtime.

---

## C. Langage visuel extrait

Ce qui suit est **uniquement** ce que les sources établissent.

### Traitement du logo
Symbole radial brass sur fond clair ; monochrome sur fond sombre. Proportions
conservées, aucune ombre, aucun dégradé, aucun effet 3D, aucune recoloration
libre. Zone de protection = largeur d'un `K`. Minimum 24 px pour le symbole,
96 px pour le lockup. Le logo pointe toujours vers la racine de la surface
courante.

### Système de couleur
Palette minérale, 8 primitives + 3 statuts, confirmée à l'identique dans les
trois sources (directive §7.1, `kivou.tokens.css`, `kivou.tokens.json`) et
visuellement sur la planche de marque :

| Token | Hex | Rôle |
|---|---|---|
| Deep Ink | `#0F1D18` | texte, titres, contraste |
| Warm Ivory | `#FAF6F1` | fond global (canvas) |
| Forest Green | `#234236` | CTA, navigation active |
| Mineral Beige | `#E7DFD3` | surfaces secondaires |
| Terracotta | `#C56440` | accent chaud mesuré |
| Brass | `#B08D57` | marque, focus, détail premium |
| Surface | `#FFFDF9` | cards et panneaux |
| Line | `#D9CFC2` | bordures 1 px |
| Text secondary / muted | `#52605A` / `#7B827E` | hiérarchie de texte |
| Success / Warning / Danger | `#2E6A50` / `#A86B2C` / `#9A4A3A` | statuts |

Contrainte explicite : **le brass n'est pas une couleur de petit texte** —
contraste insuffisant sur ivoire. Il sert la marque, le focus et les détails.
Thème **clair uniquement** au MVP (`color-scheme: light`).

### Traitement de fond
Canvas ivoire chaud `#FAF6F1`, cards en `#FFFDF9` — la différenciation
canvas/surface est explicitement demandée. Matières (travertin, marbre vert,
laiton) utilisées **en accent de signature**, jamais en fond derrière un
tableau, une preuve ou un formulaire. Les références 01/02/03 montrent la
matière confinée à une zone : quart de cercle en bas-gauche du hero mobile,
grande arche en colonne droite du hero desktop, bandeau latéral du checkout.

### Typographie
- Display / éditorial : **Lora** (serif), fallback Georgia.
- Interface / données / actions : **Instrument Sans**, fallback Inter, Arial.
- Mono : JetBrains Mono, fallback système.
- Deux familles maximum. Serif interdit dans un tableau dense. Titres jamais
  tout en capitales. Aucun texte UI sous 12 px.

Échelle mesurée (directive §7.3 + docx) : Display XL 64/67 · Display L 52/58 ·
H1 32/38 · H2 26/32 · H3 20/26 · Body 16/25 · Small 14/21 · Micro 12/17.
Sur mobile, `clamp()` sur les displays, minimum 16 px dans les champs.

### Rythme d'espacement
Base 4 px, échelle `space.0`…`space.24` (0 → 6 rem) définie dans les tokens
JSON. Sections marketing 96–144 px ; sections SaaS 24–40 px. Gouttière desktop
32 px, mobile 20 px. Conteneurs : lecture 720 px, contenu 1280 px, large
1440 px. Sidebar 240 px.

### Bordures et rayons
Bordures **1 px chaudes** (`#D9CFC2`). Rayons 10 / 14 / 18 / 24 px + pill 999 px.
Ombres chaudes très légères seulement :
`0 10px 30px -16px rgba(15,29,24,.07)` et `0 18px 48px -20px rgba(15,29,24,.10)`.
Une card est définie d'abord par surface + bordure + espacement, pas par l'ombre.

### Cards
Surface `#FFFDF9`, bordure 1 px, rayon 14–18 px, padding 20–28 px, ombre
optionnelle très légère, **aucun effet glass**. Observé en 04 : la card
sélectionnée reçoit une bordure brass et une surface légèrement teintée.

### Boutons
Variantes `primary`, `secondary`, `ghost`, `quiet`, `danger`, `icon`.
Hauteur 44 px (48 px en CTA mobile). Primary = fond Forest Green, texte blanc.
Secondary = transparent, bordure Line, texte Ink. **`danger` réservé aux
actions réellement destructives** — la directive précise que « Ignorer » est
une action *neutre*, pas destructive. Le libellé est un verbe clair ; le
chargement conserve la largeur.

### Champs
Hauteur 44 px, **label visible permanent** (jamais le placeholder comme seul
label), aide et erreur visuellement distinctes, focus brass avec offset.

### Navigation
Sidebar 240 px avec logo en haut, items à icône + libellé, carte de plan en bas,
puis chip utilisateur (observé en 04). Item actif : fond vert très doux. Sur
mobile, la sidebar devient un drawer. Le marketing utilise un header horizontal
avec liens + `Se connecter` + CTA plein.

### Badges
Catégories : confiance, timing, statut, besoin, secteur, pays, plan. Palette
retenue au beige, vert doux, terracotta doux et neutres — « les badges ne
doivent pas créer un arc-en-ciel ». Un badge répond à une question ; si tout
devient badge, rien n'est prioritaire.

### Icônes
Trait fin, géométriques, monochromes, alignées sur la grille. Observées en 02
dans des pastilles circulaires à bordure fine, et en 04 en tête de section du
panneau de détail. Aucune icône colorée, aucun pictogramme illustratif.

### Style d'illustration
Modulaire, architectural, **sans personnage, robot, cerveau ni blob 3D**.
Vocabulaire : arches, escaliers, portiques, radar, documents, travertin, marbre
vert, laiton. Quatre illustrations nommées en 07 : *Signal détecté*, *Preuve
documentaire*, *Aucun signal pertinent*, *Paiement confirmé / Accès activé*.

### États verrouillés / paywall
« Aperçu réel + bénéfice du plan, jamais écran aveugle. » Le titre recommandé
est `Déverrouillez le flux complet`, l'action `Choisir une offre`. Formulation
interdite : « Acheter maintenant avant qu'il soit trop tard ».

### États hover / focus
Focus : contour 2 px brass avec `outline-offset: 3px` — spécifié en CSS
exécutable dans `kivou.tokens.css`. Hover primaire : `#19352B`. Aucun hover ne
peut être le seul moyen d'accéder à une information.

### Motion
120 / 180 / 260 ms, easing `cubic-bezier(.2, 0, 0, 1)`.
`prefers-reduced-motion` respecté. « Aucun rebond gratuit. »

---

## D. Écrans déjà représentés par le design fourni

| Écran | Référence | Couverture |
|---|---|---|
| Landing marketing desktop | 02, 01 | **Complète** — header, hero 2 colonnes, chaîne de valeur 01→05, 3 preuves, blocs bénéfices/intelligence documentaire/exemple de signal, bandeau de confiance, footer 5 colonnes |
| Landing marketing mobile | 03 | **Complète** — hero une colonne, CTA empilés, 3 preuves en ligne, matière en bas |
| Shell SaaS desktop | 01, 04 | **Complète** — sidebar 240 px, header de page, carte de plan, chip utilisateur |
| Feed de signaux | 04, 01 | **Complète** — filtres en chips, compteur + tri, cards de signal, card sélectionnée |
| Détail de signal | 04, 01 | **Complète** — en-tête entreprise + confiance, onglets, sections à icône, rail de fit ICP, barre d'actions |
| Signal mobile | 03, 01 | **Complète** — card verticale, méta en tuiles, lien vers le détail |
| Checkout | 06 | **Complète en composition** — panneau marque à gauche, récapitulatif de plan, bénéfices débloqués |
| Illustrations d'état | 07 | 4 illustrations définies |
| Cockpit interne | 05, 08 | Défini mais **hors scope SPEC-015** (§41) |

---

## E. États non définis par le design — et extrapolation retenue

Le design ne montre **aucun pixel** des écrans suivants. Chacun est extrapolé de
façon conservatrice depuis un motif déjà établi ; aucun second langage visuel
n'est introduit.

| Manquant | Extrapolation retenue | Motif source réutilisé |
|---|---|---|
| Connexion / inscription | Card centrée sur canvas ivoire, largeur de lecture réduite, champs 44 px à label permanent, CTA primaire pleine largeur | Card + champs de 06 ; conteneur `reading` |
| Mot de passe oublié / réinitialisation | Même card d'authentification, confirmation générique en callout beige | Idem |
| Onboarding ICP | Stepper court, une question par étape, aperçu puis confirmation, sauvegarde progressive | 7 étapes listées **textuellement** dans la directive §14 et le docx ; visuel dérivé des cards + boutons |
| Page de tarifs / facturation | Grille de 4 `PricingCard`, Pro portant une bande Forest Green | Traitement Pro décrit textuellement (docx §Cards) ; card standard |
| Retour de checkout (succès / annulation) | Page centrée, illustration *Paiement confirmé* (07-4), titre `Paiement confirmé — accès activé` | Illustration 07-4 + titre imposé par la directive §18 |
| Préférences de notification | Formulaire simple sur card, interrupteur + champ email + cadence en lecture seule | Card + champs |
| Gestion des ICP (liste) | Liste de cards, badge de statut, avertissement de dépassement de limite | SignalCard décomposé en card générique |
| Chargement / squelettes | Squelettes reprenant la structure finale, pas un rond qui tourne | Imposé textuellement (docx §Overlays : « Skeleton reprenant la structure finale ») |
| États d'erreur | Callout beige/terracotta doux + action de reprise | Callout listé dans la bibliothèque de composants |
| Menu mobile du SaaS | Drawer depuis la sidebar | Imposé textuellement (directive §20) |

**Règle appliquée à toutes ces extrapolations :** aucune nouvelle couleur, aucun
nouveau rayon, aucune nouvelle famille typographique, aucun nouveau motif
décoratif. Elles ne recombinent que des primitives déjà approuvées.

---

## F. Conflits détectés et décisions

Quatre conflits réels ont été trouvés. Aucun n'a été « moyenné » silencieusement.

### F.1 — Typographie : `PP Neue Montreal` contre `Lora` + `Instrument Sans`

La planche 01 affiche, dans son encart « TYPOGRAPHIE », le nom **PP Neue
Montreal**. Les trois sources exécutables (directive §7.2, `kivou.tokens.css`,
`kivou.tokens.json`) et le docx §Typographie spécifient **Lora** (display) +
**Instrument Sans** (interface).

**Décision : Lora + Instrument Sans.**
Motifs, dans l'ordre : (1) la directive et les tokens sont datés du 18 août 2026
et se présentent eux-mêmes comme « source d'autorité frontend », tandis que la
planche est explicitement qualifiée de *référence de direction* dont « le
contenu textuel n'est pas contractuel » ; (2) le docx, qui est le document le
plus récent et le plus détaillé, ne mentionne jamais PP Neue Montreal dans son
tableau typographique normatif ; (3) PP Neue Montreal est une police
commerciale sous licence, et le manifeste interdit de committer des fichiers de
police. Lora et Instrument Sans sont sous licence libre (SIL OFL) et
distribuables. Le rendu des références reste fidèle : les deux familles servent
les mêmes rôles éditoriaux que ceux montrés sur les planches.

### F.2 — Tarifs : 29 / 59 / 129 sur les maquettes contre 0 / 49 / 99 / 199

La référence 06 affiche `Plan Pro — 59 € / mois` et un récapitulatif à 59,00 €.

**Décision : 0 / 49 / 99 / 199, lus depuis `GET /billing/plans`.**
Le conflit est déjà tranché par les sources elles-mêmes : la directive §2.2.4
ordonne le remplacement, le README répète la grille courante, et le docx la
qualifie de « grille de référence qui remplace les anciens prix visibles dans
certaines maquettes ». Aucun prix n'est écrit en dur dans le frontend.

### F.3 — Navigation SaaS : 8 entrées sur la maquette contre 5 fonctions autorisées

La référence 04 montre `Vue d'ensemble · Signaux · Entreprises · Marchés ·
Veille · Alertes · Notes · Paramètres`. SPEC-015 §14 impose l'accès à
`Signals · Target profiles/ICP · Billing · Notifications · Logout`, et §42
interdit d'inventer une sémantique produit absente du backend.

**Décision : conserver la logique visuelle et de navigation, réduire aux
fonctions réellement servies par une API.**
`Entreprises`, `Marchés`, `Veille` et `Notes` n'ont **aucun endpoint** dans
`src/signals/api/` : les afficher, même désactivés, promettrait des
fonctionnalités hors scope, ce que la Definition of Done interdit
explicitement (point 9). La sidebar conserve donc sa géométrie exacte —
largeur 240 px, logo en haut, items icône + libellé, séparateur, carte de plan,
chip utilisateur — avec les entrées `Signaux · Profils de ciblage ·
Facturation · Notifications`. Aucune entrée d'acquisition (Apollo, Instantly,
campagnes, séquences, délivrabilité) n'existe, conformément à §14 et §40.

### F.4 — Checkout : champs carte dessinés contre Stripe hébergé

La référence 06 dessine un formulaire carte complet (numéro, MM/AA, CVC,
titulaire) avec les logos des réseaux.

**Décision : composition reprise, champs carte non reproduits.**
Ce n'est pas une interprétation : la directive §17 et le docx §Checkout
disent tous deux, en toutes lettres, que « le visuel de checkout approuvé est
une direction de composition, pas une prescription pour réimplémenter les
champs carte à la main » et « ne jamais créer de faux champs carte pour imiter
la maquette ». SPEC-015 §24 confirme la redirection vers l'URL Stripe hébergée.
Le panneau de marque à gauche, le récapitulatif de plan et le bloc « vous
débloquez immédiatement » sont donc repris ; la saisie de carte appartient à
Stripe.

---

## G. Assets manquants signalés

Le manifeste liste des assets « à recréer comme fichiers de production isolés ».
Leur état au moment de l'intake :

| Asset attendu | Fourni ? | Traitement en SPEC-015 |
|---|---|---|
| Illustration *Signal détecté* | Non — seulement sur la planche 07 | **Recréée** en SVG propre (radar + arc + escalier) |
| Illustration *Preuve documentaire* | Non | **Recréée** en SVG propre |
| Illustration *Aucun signal* | Non | **Recréée** en SVG propre (arche + croix + escalier) |
| Illustration *Paiement confirmé* | Non | **Recréée** en SVG propre (porte + symbole radial + marches) |
| Texture travertin seamless | **Non fournie** | Non substituée — voir ci-dessous |
| Texture marbre vert | **Non fournie** | Non substituée — voir ci-dessous |
| Illustration architecturale de hero | **Non fournie** | Composition géométrique dérivée des références |
| Image OG 1200×630 | Non fournie | Hors scope SPEC-015 (déploiement) |
| En-tête d'email 1200×400 | Non fournie | Hors scope SPEC-015 (SMTP = gate ops, §59) |
| Motif radial en tuile | Non fournie | Dérivé du symbole existant |

Les quatre illustrations sont recréées en SVG géométrique, conformément à
l'instruction « ne pas découper ces assets depuis une maquette d'écran ;
recréer des originaux propres avec la même direction artistique ». Leur
géométrie (arc, escalier, radar concentrique, arche, porte) est entièrement
descriptible en primitives vectorielles et ne perd donc rien à la recréation.

**Les deux textures photographiques (travertin, marbre vert) ne sont pas
fournies et ne sont pas remplacées par de l'imagerie de substitution** —
§39 interdit de substituer silencieusement une banque d'images. Le hero rend la
composition architecturale en dégradés minéraux et formes vectorielles issues
de la palette approuvée, ce qui préserve la géométrie et le rapport de valeurs
des références sans inventer une photographie. **Ce point reste un écart visuel
assumé, et il demande une décision humaine** : livrer les deux textures en
WebP/AVIF, ou valider la version vectorielle. Il est reporté dans le rapport
final.

---

## H. Décision de stack, adossée à l'intake

Le dépôt ne contient **aucun** `package.json`, aucun répertoire `frontend/`,
aucun système de style JS. Il n'existe donc pas de stack existante à réutiliser,
et aucun des matériaux fournis ne contient d'implémentation exécutable
(les tokens CSS/JSON sont des données, pas une application).

En conséquence, et conformément à SPEC-015 §4 :
**React + TypeScript + Vite**, avec **CSS custom properties + CSS Modules**.

Tailwind est **écarté** malgré la présence du preset : la directive dit
« NE PAS FORCER TAILWIND — si le dépôt n'utilise pas Tailwind, consommer les
tokens CSS/JSON dans le système déjà présent ; le design system ne justifie pas
à lui seul une migration de stack ». Le fichier `kivou.tokens.css` fourni est
déjà exactement la forme attendue par un système CSS custom properties : c'est
le format qui reproduit le design fourni avec le moins d'interprétation.

---

## I. Ce que l'intake établit avant de coder

1. Le langage visuel est **entièrement spécifié** et exécutable — palette,
   typographie, échelle, rayons, ombres, motion viennent de fichiers, pas d'une
   lecture d'image.
2. Les écrans clients principaux (landing, feed, détail, checkout, mobile) sont
   **tous** couverts par une référence approuvée.
3. Les écrans d'authentification, d'onboarding et de réglages ne le sont pas et
   sont extrapolés sous contrainte stricte.
4. Quatre conflits sont tranchés explicitement, aucun par moyenne silencieuse.
5. Deux textures photographiques manquent et **ne sont pas substituées**.
