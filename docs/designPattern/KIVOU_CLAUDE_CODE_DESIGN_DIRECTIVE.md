# KIVOU DESIGN SYSTEM v1.0 — Directive maître pour Claude Code

**Statut :** source d’autorité frontend pour Kivou  
**Date :** 18 août 2026  
**Langues produit :** français + anglais en priorité  
**Thème MVP :** clair uniquement  
**Portée :** identité, site marketing, SaaS client, onboarding, pricing, paywall, checkout, confirmation de paiement, cockpit commercial interne.

---

## 0. Rôle

Tu agis comme **Lead Product Designer, Design Systems Engineer et Frontend Engineer** de Kivou.

Tu ne dois pas inventer une nouvelle direction artistique. Tu dois reproduire avec fidélité le langage visuel approuvé dans les documents et assets du repository, puis le transformer en composants robustes, accessibles, responsives et réutilisables.

La réussite n’est pas « une page jolie ». La réussite est un système cohérent qui :

1. rend la proposition de valeur Kivou immédiatement compréhensible ;
2. sépare strictement les faits, les inférences et les opportunités ;
3. permet au client de comprendre un signal, sa preuve, son timing et son adéquation à l’ICP ;
4. convertit sans friction vers un abonnement ;
5. ne mélange jamais le produit client avec l’Acquisition Engine interne ;
6. reste fidèle au scope MVP et à la grille tarifaire en vigueur.

---

## 1. Étape obligatoire avant toute modification

Avant de coder :

1. Inspecte le repository, notamment `package.json`, la structure `src/` ou `app/`, le système de styles, les composants existants, les tests, les routes et les dépendances.
2. Inspecte en priorité tous les documents et assets présents sous `docs/` et les sous-dossiers associés. Ils constituent la source visuelle et produit d’autorité.
3. Ne remplace pas la stack existante sans nécessité démontrée.
4. Ne rajoute pas une bibliothèque UI lourde si les primitives nécessaires existent déjà.
5. Ne modifie aucun schéma partagé ni contrat API sans SPEC explicite.
6. Présente un inventaire court de ce qui existe, des écarts et du plan de mise en œuvre avant un changement transversal.

En cas de contradiction, applique l’ordre de gouvernance défini à la section suivante.

---

## 2. Gouvernance et ordre de priorité

### 2.1 Produit et business

Ordre de priorité des décisions :

1. Les corrections et décisions les plus récentes portant explicitement sur le sujet concerné.
2. **Kivou Architecture opérationnelle simple v2.5** pour le MVP opérationnel ; elle reporte la vision agentique v2.4.
3. **Kivou Pricing & Packaging v0.1** pour le pricing et les entitlements : Découverte 0, Essential 49, Pro 99, Scale 199 CHF/€ par mois ; Founding Customer privé à 29 pour cinq design partners maximum.
4. **Kivou Correction stratégique Acquisition Stack v2.3** pour le nom Kivou, le domaine `kivou.eu` et la séparation de la stack outbound.
5. **Correction stratégique Document Intelligence v2.2** pour la preuve documentaire, les exigences d’exécution, les besoins plausibles, le timing et l’externalisabilité.
6. **Correction SaaS avant outbound v2.1** pour le SaaS transactionnel, le paywall, le checkout et le funnel de conversion.
7. Plan directeur et roadmap v2.0 pour les principes non remplacés.
8. Backlog Residual Post-Award Need du 18 août 2026 pour la gestion de la fraîcheur, les feedbacks et les limites du moteur V0.

### 2.2 Visuel

1. Les maquettes expressément approuvées par Rodrigue sont l’autorité visuelle.
2. Les images composites sont des **références de direction**, pas des captures à intégrer telles quelles dans le produit.
3. Le contenu textuel, les prix, chiffres, dates, logos tiers et données fictives des maquettes ne sont pas contractuels.
4. Les prix anciens 29/59/129 visibles dans certaines maquettes doivent être remplacés par la grille actuelle 0/49/99/199.
5. Les assets de production doivent être recréés proprement en SVG/WebP/AVIF ou via composants CSS, et non découpés grossièrement dans une planche.

---

## 3. Vérité produit à préserver dans l’interface

### 3.1 Définition

Kivou transforme les marchés publics gagnés et leurs documents en signaux commerciaux B2B actionnables.

La chaîne de valeur est :

**Attribution récente → entreprise gagnante → marché et documents → exigences d’exécution → besoins plausibles → timing → externalisabilité → adéquation avec l’ICP → preuve → action.**

### 3.2 Règle de vérité

L’interface doit distinguer visuellement :

- **FAIT** : ce que le marché, l’avis ou le document public établit ;
- **INFÉRENCE** : ce que l’exigence implique probablement ;
- **OPPORTUNITÉ** : pourquoi ce besoin peut être pertinent pour l’offre du client.

Ne jamais écrire qu’un gagnant « va acheter » un produit sans preuve. Utiliser des formulations comme :

- « besoin plausible » ;
- « besoin potentiellement externalisable » ;
- « peut créer une fenêtre commerciale » ;
- « confiance élevée / moyenne / faible » ;
- « attribution récemment publiée » si la vraie date d’attribution est inconnue.

### 3.3 Fraîcheur

La date d’attribution est prioritaire. Une publication récente d’une vieille attribution ne doit pas être présentée comme « vient de gagner ».

Prévoir des statuts distincts :

- `recent_award` — attribution réellement récente ;
- `recently_published_award` — attribution publiée récemment, date réelle inconnue ou plus ancienne ;
- `stale` — signal hors fenêtre commerciale ;
- `unknown_timing` — timing insuffisant.

---

## 4. Séparation stricte des surfaces

### 4.1 Site marketing public

But : expliquer, démontrer la preuve, faire configurer un ICP, convertir.

### 4.2 SaaS client

Le client voit :

- ses signaux ;
- les entreprises gagnantes ;
- les marchés et faits clés ;
- les exigences documentaires ;
- les besoins plausibles ;
- le timing ;
- la confiance ;
- l’externalisabilité ;
- le fit ICP ;
- les passages et documents sources ;
- les actions `Sauvegarder`, `Marquer contacté`, `Ajouter une note`, `Ignorer` ;
- les alertes, notes, paramètres ICP et facturation.

Le client **ne voit jamais** : Apollo, Instantly, mailboxes, délivrabilité, séquences, campagne d’acquisition Kivou, Supplier Discovery interne ou décideurs trouvés par Kivou pour sa propre prospection.

### 4.3 Cockpit commercial interne

Le cockpit hebdomadaire contient uniquement, dans cet ordre :

1. Emails délivrés
2. Réponses positives
3. Clics Kivou
4. Comptes activés
5. Paiements
6. MRR
7. Churn

Puis un tableau groupable par :

**pays × secteur × besoin × campagne**

Ne pas ajouter des widgets de vanity metrics, délivrabilité, objectifs, rendez-vous, pipeline CRM ou monitoring à cet écran.

---

## 5. Direction artistique

### 5.1 Impression recherchée

- éditoriale ;
- minérale ;
- architecturale ;
- européenne ;
- premium sans ostentation ;
- calme ;
- précise ;
- crédible ;
- orientée preuve et décision.

Kivou doit évoquer une maison de conseil haut de gamme et une plateforme d’intelligence fiable, pas une startup « IA futuriste ».

### 5.2 Interdits

- bleu SaaS générique comme couleur dominante ;
- violet/bleu néon ;
- globes lumineux ;
- gradients holographiques ;
- cyberpunk ;
- glassmorphism massif ;
- blobs 3D ;
- personnages cartoon ;
- illustrations d’IA avec cerveau ou robot ;
- tableaux de bord décoratifs ;
- ombres noires fortes ;
- surcharge de badges ;
- texte minuscule ;
- dark mode au MVP sans demande explicite.

### 5.3 Matières et motifs

Utiliser avec retenue :

- travertin / pierre claire ;
- marbre vert profond ;
- papier haut de gamme ;
- laiton brossé ;
- arches, escaliers et portiques ;
- courbes architecturales ;
- motif radial Kivou ;
- grilles, lignes et radars très discrets.

Les matières servent à créer une signature, jamais à réduire la lisibilité.

---

## 6. Identité visuelle

### 6.1 Logo

Le système comprend :

- symbole radial ;
- logo horizontal ;
- logo empilé ;
- wordmark seul ;
- favicon / app icon ;
- versions monochromes.

Règles :

- conserver les proportions ;
- ne pas appliquer d’ombre, de dégradé ou d’effet 3D ;
- ne pas recolorer librement ;
- utiliser le symbole brass sur fond clair ou monochrome sur fond sombre ;
- zone de protection minimale : largeur d’un `K` autour du lockup ;
- minimum digital recommandé : 24 px pour le symbole, 96 px pour le lockup.

### 6.2 Baseline

`Performance commerciale sous contrôle` est une baseline de marque possible, secondaire à la proposition de valeur produit.

### 6.3 Promesse principale

Formulation de référence :

`Transformez les marchés publics gagnés en opportunités B2B concrètes.`

Formulation produit :

`Kivou transforme les marchés publics gagnés et leurs documents en signaux commerciaux B2B actionnables.`

---

## 7. Design tokens

Importer et utiliser les fichiers :

- `tokens/kivou.tokens.css`
- `tokens/kivou.tokens.json`
- `tokens/kivou.tailwind.preset.ts` si Tailwind est déjà installé.

### 7.1 Couleurs principales

| Token | Hex | Usage |
|---|---:|---|
| Deep Ink | `#0F1D18` | texte, titres, logo, contraste |
| Warm Ivory | `#FAF6F1` | fond global |
| Forest Green | `#234236` | CTA, navigation active, accents forts |
| Mineral Beige | `#E7DFD3` | surfaces secondaires, fonds doux |
| Terracotta | `#C56440` | accent chaud mesuré, états secondaires |
| Brass | `#B08D57` | marque, détails premium, focus |
| Surface | `#FFFDF9` | cards et panneaux |
| Line | `#D9CFC2` | bordures et séparateurs |

Le brass n’est pas une couleur de texte courant : contraste insuffisant sur ivoire pour de petits caractères.

### 7.2 Typographie

- Display / marketing : `Lora`.
- Interface / contenu : `Instrument Sans`.
- Fallback sans : `Inter`, Arial, sans-serif.
- Code et identifiants : monospace existant dans le repo.

Règle : serif pour l’éditorial et les titres à forte valeur ; sans-serif pour l’interface, les données et les actions.

### 7.3 Échelle recommandée

- Display XL : 64/67, Lora, 400
- Display L : 52/58, Lora, 400
- H1 app : 32/38, Lora ou Instrument Sans selon densité
- H2 : 26/32
- H3 : 20/26
- Body : 16/25
- Small : 14/21
- Micro / label : 12/17

Sur mobile, réduire les displays avec `clamp()` et conserver un minimum de 16 px pour les champs.

### 7.4 Grille, espacements et conteneurs

- base spacing : 4 px ;
- contenu principal : max 1280 px ;
- landing large : max 1440 px ;
- lecture : max 720 px ;
- sidebar desktop : 240 px ;
- gouttière desktop : 32 px ;
- mobile : 20 px ;
- sections marketing : 96 à 144 px ;
- sections SaaS : 24 à 40 px.

### 7.5 Rayons et ombres

- petit : 10 px ;
- moyen : 14 px ;
- grand : 18 px ;
- XL : 24 px ;
- pills : 999 px.

Ombres chaudes très légères uniquement. Une card doit surtout être définie par sa surface, sa bordure et son espacement.

### 7.6 Motion

- rapide : 120 ms ;
- standard : 180 ms ;
- lente : 260 ms ;
- easing : `cubic-bezier(.2, 0, 0, 1)`.

Respecter `prefers-reduced-motion`. Aucun rebond gratuit.

---

## 8. Architecture de composants

Adapter les noms au repository, sans dupliquer les primitives existantes.

Structure recommandée :

```text
src/
  components/
    kivou/
      ui/          # Button, Input, Card, Badge, Tabs, Drawer, Modal, Table...
      marketing/   # Hero, TrustStrip, HowItWorks, PricingGrid...
      product/     # SignalCard, EvidencePanel, NeedList, ICPFitPanel...
      internal/    # WeeklyFunnel, SegmentPerformanceTable...
  styles/
    kivou-tokens.css
  lib/
    formatters/    # money, date, confidence, freshness
    entitlements/
    analytics/
public/
  brand/kivou/
  illustrations/kivou/
  textures/kivou/
```

Ne jamais hardcoder un hex dans un composant métier. Utiliser les tokens sémantiques.

---

## 9. Primitives UI obligatoires

### Button

Variantes : `primary`, `secondary`, `ghost`, `quiet`, `danger`, `icon`.

- hauteur standard : 44 px ;
- mobile CTA : 48 px ;
- primary : fond Forest Green, texte blanc ;
- secondary : fond transparent, bordure Line, texte Ink ;
- danger : réservé aux actions destructives réelles ;
- `Ignorer` est une action neutre, pas destructive.

États : hover, active, focus-visible, disabled, loading.

### Card

- surface `#FFFDF9` ;
- bordure 1 px ;
- rayon 14–18 px ;
- padding 20–28 px ;
- ombre optionnelle très légère ;
- pas d’effet glass.

### Input / Select / Combobox

- hauteur 44 px ;
- label visible ;
- aide et erreur distinctes ;
- focus brass + offset ;
- ne jamais utiliser le placeholder comme seul label.

### Badge / Tag

Catégories : confiance, timing, statut, besoin, secteur, pays, plan.

Les badges ne doivent pas créer un arc-en-ciel. Utiliser surtout beige, vert doux, terracotta doux et neutres.

### Table

- header sticky lorsque pertinent ;
- cellules alignées ;
- nombres tabulaires ;
- ligne 48–56 px ;
- tri explicite ;
- empty state ;
- scroll horizontal mobile avec colonnes prioritaires épinglées si possible ;
- ne pas réduire la police sous 12 px.

### Drawer

Utilisé pour le détail d’un signal sur desktop lorsque la liste reste visible. Sur mobile, devenir une page complète.

---

## 10. Composants métier Kivou

### `SignalCard`

Affiche :

- entreprise gagnante ;
- titre du marché ;
- pays / localisation ;
- valeur ;
- date ou statut de fraîcheur ;
- besoin principal ;
- niveau de confiance avec libellé ;
- indication de fit ICP ;
- état sauvegardé.

Ne jamais afficher un score seul. Associer nombre + libellé + raison courte.

### `SignalDetail`

Ordre recommandé :

1. résumé ;
2. entreprise gagnante ;
3. marché / contrat ;
4. faits et exigences ;
5. besoins plausibles ;
6. timing ;
7. externalisabilité ;
8. fit ICP ;
9. confiance ;
10. preuve documentaire et passage source ;
11. actions.

### `EvidencePanel`

Doit rendre visibles : source, document, page/section, passage, date d’accès ou version, niveau de confiance et lien.

### `FactInferenceOpportunity`

Composant tripartite :

- fait public ;
- inférence ;
- opportunité pour l’ICP.

Utiliser des traitements visuels proches mais distincts, sans faire passer l’inférence pour un fait.

### `NeedList`

- 1 à 5 besoins maximum ;
- classés ;
- libellé de confiance ;
- justification courte ;
- timing ;
- externalisabilité.

### `ConfidenceIndicator`

Toujours afficher :

- pourcentage éventuel ;
- libellé (`Très élevée`, `Élevée`, `Moyenne`, `Faible`) ;
- base de confiance ou tooltip accessible.

### `TimingStatus`

Afficher clairement :

- date d’attribution ;
- date de publication ;
- date de découverte ;
- fenêtre estimée ;
- statut de fraîcheur.

### `SignalActions`

Ordre :

- Sauvegarder ;
- Marquer contacté ;
- Ajouter une note ;
- Ignorer.

Le feedback « Ignorer » peut demander une raison : déjà couvert, réalisé en interne, mauvais type de client, trop tard, besoin erroné, autre.

### `PaywallPreview`

Découverte : trois vrais signaux accessibles immédiatement avec preuve, puis feed partiellement verrouillé. Ne jamais masquer toute la valeur avant conversion.

### `PricingCard`

Plans actuels :

- Découverte — 0 ;
- Essential — 49 ;
- Pro — 99, recommandé ;
- Scale — 199.

Le Founding Customer à 29 est privé et ne figure pas dans la grille publique.

### `WeeklyCommercialFunnel`

Uniquement les sept KPI demandés, dans l’ordre. Fournir valeur, taux de conversion vers l’étape suivante lorsque pertinent et variation semaine précédente.

### `SegmentPerformanceTable`

Dimensions : pays, secteur, besoin, campagne. Mesures : emails délivrés, réponses positives, clics Kivou, comptes activés, paiements, MRR, churn.

---

## 11. Pages et routes

Adapter les routes au projet existant.

### Marketing

- `/`
- `/produit`
- `/comment-ca-marche`
- `/tarifs`
- `/demo` ou `/contact`
- `/connexion`
- `/inscription`

### Produit client

- `/app/signaux`
- `/app/signaux/[id]`
- `/app/icp`
- `/app/alertes`
- `/app/notes`
- `/app/parametres`
- `/app/facturation`

### Interne

- `/internal/commercial`

Ne pas exposer les routes internes dans la navigation client.

---

## 12. Homepage

Ordre recommandé :

1. Header ;
2. Hero ;
3. trois preuves de confiance ;
4. chaîne de valeur ;
5. exemple de signal ;
6. intelligence documentaire ;
7. bénéfices ;
8. pricing ou CTA ;
9. FAQ ;
10. footer.

Hero :

- H1 : `Transformez les marchés publics gagnés en opportunités B2B concrètes.`
- texte : expliquer les faits publics, les documents, les besoins plausibles et le timing ;
- CTA principal : `Voir mes signaux` ou `Découvrir mes signaux` ;
- CTA secondaire : `Voir un exemple` ou `Comprendre Kivou`.

Éviter les promesses absolues. Mettre en avant les sources, preuves et niveaux de confiance.

---

## 13. Landing contextualisée

Un prospect provenant d’un email doit reconnaître son contexte.

Afficher :

- secteur / pays / besoin détecté ;
- « Voici ce que nous avons compris de votre activité » ;
- ICP préconstruit modifiable ;
- nombre de signaux disponibles ;
- trois vrais exemples ;
- preuve visible ;
- CTA d’activation puis paywall.

Ne pas arriver sur une homepage générique après un clic outbound contextualisé.

---

## 14. Onboarding ICP

Parcours court :

1. offre du client ;
2. type d’entreprises ciblées ;
3. secteurs ;
4. territoires ;
5. taille / seuil de marché ;
6. besoins vendus ;
7. aperçu du résultat ;
8. confirmation.

Préremplir ce qui est connu, expliquer pourquoi chaque question améliore la pertinence, permettre de revenir en arrière et sauvegarder progressivement.

Activation = le client consulte un signal suffisamment pertinent, pas seulement la création du compte.

---

## 15. Feed client

Desktop recommandé :

- sidebar ;
- header de page ;
- résumé ICP actif ;
- filtres ;
- liste ;
- panneau de détail ou route dédiée ;
- actions persistantes.

Prioriser : fraîcheur, fit, confiance, valeur et besoin. Ne pas saturer de données de marché public.

Mobile :

- filtres en bottom sheet ;
- cards verticales ;
- détail en page complète ;
- action principale sticky en bas ;
- preuve lisible sans zoom.

---

## 16. Pricing et entitlements

### Découverte — 0

- 1 ICP simplifié ou préconstruit ;
- 3 signaux réels immédiatement ;
- preuve complète sur ces exemples ;
- aperçu d’alertes ;
- historique très limité ;
- pas d’export.

### Essential — 49 CHF/€ / mois

- 1 ICP ;
- 1 territoire principal ;
- flux du périmètre ;
- preuve complète ;
- alertes hebdomadaires ;
- historique 30 jours ;
- filtres basiques ;
- pas d’export.

### Pro — 99 CHF/€ / mois, recommandé

- 3 ICP ;
- plusieurs territoires ;
- flux complet des ICP actifs ;
- preuve complète ;
- alertes quotidiennes ;
- historique 12 mois ;
- filtres avancés ;
- export limité.

### Scale — 199 CHF/€ / mois

- 10 ICP ;
- Suisse + couverture UE étendue ;
- couverture élargie ;
- alertes prioritaires selon disponibilité ;
- historique étendu ;
- filtres avancés ;
- export étendu.

Ne pas promettre CRM complet, API, collaboration avancée, application mobile ou intégrations complexes tant que ces fonctions sont hors scope.

Facturation mensuelle au lancement. Annuel seulement après preuve de rétention.

---

## 17. Checkout Stripe

Stripe est le fournisseur de paiement et d’abonnement de Kivou.

Règles UX :

- shell Kivou à gauche ou autour du paiement ;
- récapitulatif de plan et prix ;
- devise CHF ou EUR selon le contexte ;
- taxes affichées après pays et informations fiscales ;
- annulation et renouvellement clairement expliqués ;
- formulaire de paiement fourni par Stripe Payment Element ou Checkout ;
- ne pas recréer des champs carte non sécurisés ;
- états loading, 3DS, échec, succès, abonnement déjà actif ;
- retour immédiat au produit après succès ;
- confirmation par email.

Le visuel de checkout approuvé est une direction de composition, pas une prescription pour réimplémenter les champs carte à la main.

---

## 18. Confirmation de paiement

Afficher :

- `Paiement confirmé — accès activé` ;
- plan ;
- prochaine facturation ;
- ce qui est débloqué ;
- CTA `Accéder à mes signaux` ;
- lien vers facturation ;
- illustration architecturale légère.

Ne pas interrompre le parcours par une page marketing longue.

---

## 19. Cockpit commercial hebdomadaire interne

Header : semaine sélectionnée + filtres nécessaires.

Ligne KPI :

1. Emails délivrés
2. Réponses positives
3. Clics Kivou
4. Comptes activés
5. Paiements
6. MRR
7. Churn

Pour chaque KPI : valeur, variation vs semaine précédente, tooltip de définition. Pour les étapes de funnel, afficher le taux de conversion en complément sans remplacer le volume.

Tableau :

- dimensions groupables dans l’ordre pays → secteur → besoin → campagne ;
- colonnes des sept KPI ;
- tri, filtres, export ;
- total hebdomadaire ;
- nombres et devises formatés ;
- aucune donnée client sensible exposée inutilement.

Interdits sur cette page : vanity metrics, open rate comme KPI principal, rendez-vous, opportunités CRM, délivrabilité détaillée, mailboxes, Apollo, Instantly, monitoring technique.

---

## 20. Responsive

### Breakpoints

- mobile : < 768 px ;
- tablet : 768–1023 px ;
- desktop : 1024–1439 px ;
- wide : ≥ 1440 px.

### Règles

- marketing : une colonne mobile, hero compact, matières en bas de section ;
- SaaS : sidebar devient drawer ;
- détail split-view devient page ;
- tableaux : vue cartes ou scroll contrôlé ;
- CTA principal reste visible ;
- aucun hover comme seule interaction ;
- zones tactiles ≥ 44 px.

---

## 21. Accessibilité

Objectif WCAG 2.2 AA.

- contraste suffisant ;
- focus visible ;
- navigation clavier ;
- labels et messages d’erreur ;
- titres hiérarchisés ;
- liens explicites ;
- icônes avec nom accessible ;
- tableaux avec headers ;
- états non communiqués par couleur seule ;
- `aria-live` pour paiement, filtres et chargement ;
- `prefers-reduced-motion` ;
- langage de page FR ou EN correct ;
- dates et devises localisées.

---

## 22. Internationalisation

French + English first.

- aucun texte UI en dur dans les composants ;
- clés de traduction sémantiques ;
- nombres via `Intl.NumberFormat` ;
- dates via `Intl.DateTimeFormat` ;
- CHF et EUR ;
- gestion des textes plus longs en anglais ;
- pas de troncature d’un passage de preuve essentiel sans option d’expansion.

---

## 23. États obligatoires

Chaque page/composant doit prévoir :

- loading ;
- skeleton ;
- vide ;
- erreur récupérable ;
- erreur critique ;
- accès verrouillé ;
- donnée partielle ;
- preuve indisponible ;
- confiance faible ;
- attribution récemment publiée ;
- aucun signal pertinent ;
- paiement en cours ;
- paiement échoué ;
- paiement confirmé ;
- abonnement expiré ;
- quota atteint.

Le produit doit préférer une incertitude explicite à une certitude fabriquée.

---

## 24. Analytics frontend

Tracer au minimum :

- landing viewed ;
- ICP started / confirmed ;
- signal viewed ;
- evidence opened ;
- signal saved ;
- signal marked contacted ;
- signal ignored + reason ;
- pricing viewed ;
- plan selected ;
- checkout started ;
- payment succeeded / failed ;
- alert preference changed.

Les événements doivent inclure les identifiants nécessaires, pas des textes sensibles ou des passages documentaires complets.

---

## 25. Performance

- images en WebP/AVIF avec dimensions ;
- SVG pour logo et icônes ;
- lazy loading hors hero ;
- pas de vidéo lourde au MVP ;
- éviter les bundles de charts sur les pages qui n’en ont pas besoin ;
- pas de texture 4K si une version 1600 px suffit ;
- préserver CLS ;
- viser un LCP < 2,5 s sur les pages marketing réalistes.

---

## 26. Tests et EVAL

Utiliser le framework de test existant.

Minimum :

- tests des variants de composants ;
- tests clavier et focus ;
- tests des entitlements ;
- tests des formats dates/devises ;
- tests des statuts de fraîcheur ;
- tests de fact/inference/opportunity ;
- tests responsive principaux ;
- screenshots ou visual regression si Playwright existe ;
- parcours signup → ICP → 3 signaux → paywall → Stripe test → accès.

Tester les états réels avec données de fixtures, pas uniquement une page idéale.

---

## 27. Definition of Done frontend

Une interface est DONE seulement si :

1. elle utilise les tokens ;
2. elle respecte la séparation public/client/interne ;
3. elle est responsive ;
4. elle est navigable au clavier ;
5. elle possède les états loading/empty/error/locked nécessaires ;
6. elle est localisable FR/EN ;
7. elle n’affiche pas de prix obsolète ;
8. elle ne présente pas une inférence comme un fait ;
9. elle ne promet pas une fonction hors scope ;
10. elle passe tests, lint, typecheck et build ;
11. elle est vérifiée en staging ;
12. elle correspond visuellement aux références approuvées.

---

## 28. Procédure de travail Claude Code

Pour chaque SPEC frontend :

1. **INPUT** — route, données, contraintes, assets, composants existants ;
2. **OUTPUT** — composants et parcours précis ;
3. **TESTS** — fonctionnels, visuels, responsive, a11y ;
4. **EVIDENCE** — captures, build, tests, comparaison aux références ;
5. **EVAL** — conformité produit et design ;
6. **DONE** — seulement après validation.

Ne jamais répondre à une SPEC par « construire tout le produit ». Décomposer en unités livrables et testables.

---

## 29. Checklist finale avant PR

- [ ] Je n’ai pas inventé un nouveau style.
- [ ] J’ai inspecté les assets `docs/`.
- [ ] Les prix publics sont 0 / 49 / 99 / 199.
- [ ] Pro est recommandé.
- [ ] Founding 29 n’est pas public.
- [ ] Le SaaS client ne contient pas l’Acquisition Engine.
- [ ] Le cockpit hebdomadaire contient seulement les sept KPI demandés et le tableau par segments.
- [ ] Le score n’est jamais affiché seul.
- [ ] Faits, inférences et opportunités sont distingués.
- [ ] La fraîcheur repose sur la date d’attribution lorsque connue.
- [ ] Les composants utilisent les tokens.
- [ ] Les états et responsive sont traités.
- [ ] Les textes sont prêts pour FR/EN.
- [ ] Aucune donnée fictive n’est présentée comme réelle.
- [ ] Tests, typecheck, lint et build passent.

---

## 30. Instruction finale

À partir de cette directive, tu es le gardien du Design System Kivou. Toute proposition qui s’écarte de cette identité, ajoute une fonctionnalité hors scope, mélange les surfaces ou utilise des informations tarifaires obsolètes doit être refusée ou corrigée avant implémentation.
