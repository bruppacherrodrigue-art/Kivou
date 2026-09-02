# Page « Signaux » lisible par un commercial — spécification

**Date :** 2026-09-02 · **Base :** branche `design/acquisition-production-activation`
(`9de4d0f`, ce que staging exécute) · **Décision fondateur :** « Go A, ensuite Go B
quand fini, ensuite hors périmètre » (Rodrigue, 2026-09-02).

## 1. Constat sur données réelles (staging, compte Essentiel, ICP Matériaux·FR)

Trois audits en lecture seule (UX commerciale, design/typographie, qualité des
données) ont convergé. Le produit n'est pas cassé : chargement 1,3 s, aucune
erreur console ni réseau. Il est vide de sens commercial, et la cause première
est la donnée DECP 2022, pas le style.

| Symptôme à l'écran | Cause racine | Lot |
|---|---|---|
| 8 signaux visibles, `excluded.without_display_name = 491`, `scan_truncated = true` | `feed_page` lit 500 lignes par `materialized_at desc` PUIS écarte celles sans nom ; l'ingestion DECP en masse remplit les 500 | A1 |
| « ACHETEUR 27920022400012 » | DECP 2022 ne publie pas le nom ; `view._buyer` recopie le SIRET en `name` sans le test « nom ≠ identifiant » que le feed applique au titulaire | A2 |
| « LIEU France », titre court « … à FR » | `locality` null, `postal_code` présent, aucun département dérivé | A2 |
| « Aucune donnée essentielle manquante » sous un acheteur sans nom | `factual_display` compte un SIRET comme nom et un pays comme lieu | A3 |
| « 19 août 2026 » signifie notification sur une carte, publication sur la suivante | la carte n'affiche pas `eventDateKind` | A4 |
| « 14 jours », « 1 jours » | `ageDays: '{count} jours'` sans référent ni pluriel | A4 |
| « 5338215 € » | `Intl` émet U+202F que les polices auto-hébergées ne rendent pas | A5 |
| Badge « SOURCE OFFICIELLE » sur deux lignes, polices 9–11 px, « 1 attribution », « 7 · Essentiel » | CSS liste | A6 |
| `recent_award` dans un `<select>`, « Tous les st », CPV grisé sans explication | filtres historiques | A7 |
| grille de faits 5 cellules / 4 colonnes, chips avec point final et phrase entière | détail | A8 |
| « lecture bornée » puis « fin des attributions » | deux messages pour un même état | A9 |

## 2. Lot A — défauts purs (ce plan)

Aucun changement de sens. Chaque point est vérifiable par un test.

- **A1** Le plafond de lecture de la vue Récentes compte les candidats
  **affichables**, par lots, avec un plafond absolu de lignes lues
  (`scan_cap × 10`). `scan_truncated` reste annoncé. Le repli « nom d'une
  représentation sœur » est conservé.
- **A2** Acheteur : `contract.buyer.name` devient `null` quand la source n'a
  publié qu'un identifiant ; l'identifiant reste. Lieu : `contract.location`
  gagne `subdivision_label` (nom du département français) ; le département est
  dérivé du code postal quand la source ne le publie pas, à la lecture ET à
  l'ingestion DECP. Le titre court dit « dans le département 92
  (Hauts-de-Seine) » au lieu de « à FR ».
- **A3** `factual_display` : `buyer` connu seulement si c'est un nom ;
  `location` connue seulement si commune ou département. Les
  `missing_fields` existants (`buyer`, `location`) et leurs libellés frontend
  suffisent.
- **A4** Carte : « Notifié le 19 août 2026 » / « Attribué le » / « Publié le ».
  Chip d'âge : « Il y a 14 jours », « Il y a 1 jour ».
- **A5** Montants : U+202F et U+2009 remplacés par U+00A0 dans `amount`,
  `money`, `number`.
- **A6** Liste : badge sur une ligne ; objet du marché clampé à 2 lignes ;
  échelle 12/13 px ; « 2 attributions » seulement au-delà de 1 ; compteur
  « 7 signaux » / « 20+ signaux ».
- **A7** Statuts temporels en clair (fr/en) ; grille de filtres qui ne tronque
  plus ; filtre verrouillé expliqué par `aria-describedby` et style pointillé.
- **A8** Grille de faits à 5 colonnes (3 puis 2 en dessous de 1180/620 px) ;
  chip courte dérivée du statut, `why_now` en paragraphe.
- **A9** `endOfList` masqué quand `scan_truncated` ; note de troncature qui
  renvoie vers l'Historique.
- **A10** Régénération des goldens `dashboard-signals-{desktop,mobile}.png`
  en une seule fois, à la fin.

Hors lot A, à ne pas faire ici : toucher au titre en `h2` (B2), afficher
`analysis` (B1), trier (B5), câbler le retour (B4), normaliser la casse (refusé).

## 3. Lot B — décisions produit validées (plan séparé, après A)

B1 besoins plausibles + raisons de fit dans le détail, étiquetés
« hypothèse » ; B2 entreprise en titre, objet en sous-titre clampé ; B3
« Nouvelle opportunité » réservé aux attributions datées ; B4 boutons
Pertinent / Contacté / Ignorer sur l'endpoint de retour existant ; B5 tri de la
vue Récentes par date d'événement ; B6 parenté SIREN affichée. B7 (casse des
titres) refusé.

## 4. Lot C — chantier données (spécification à écrire après B)

Nom des acheteurs via l'Annuaire des entreprises (client `companies/france.py`
déjà présent, résolution SIRET titulaires déjà commencée sur la branche de
design, migrations 0031–0033) ; commune depuis le code postal (référentiel) ;
enrichissement des titulaires DECP à la matérialisation.

## 5. Contraintes globales

- Jamais présenter une inférence comme un fait (directive de design §3.2) ;
  jamais fabriquer un nom depuis un identifiant (§19).
- Aucune migration Alembic dans le lot A (toute migration casse ~26 tests à
  tête codée en dur).
- `main` ne se modifie pas directement ; PR obligatoire ; CI verte.
- Tests hors ligne uniquement.
- Les textes existent en `fr` ET `en`.

## 6. Écarts connus à la date du lot A (hors périmètre)

Constatés pendant la revue de branche complète qui a produit la vague de
correctifs finale du lot A. Aucun n'est traité ici : ils sont consignés pour
que le lot B (ou une tâche dédiée) les reprenne en connaissance de cause.

1. **Trois sections perdues par le commit `b44686b`** de la branche de
   design, avant même le début du lot A : le texte du statut de complétude
   dans `.published-status`, le paragraphe `analysisUnavailable`, et les
   sections « historique des attributions » et « source et preuves » avec
   leur `<details>`. `ReferenceSignalDetail` ne les rend plus. Les
   assertions Playwright qui les vérifiaient ont été inversées ou
   collapsées vers « n'existe plus » dans `reference-port.spec.ts` pour
   rester honnêtes sur ce que la page rend réellement — voir les
   commentaires qui y citent `b44686b`.
2. **Les migrations `0032` et `0033` ne sont plus rejouables hors ligne
   au-delà de `0031`.** Elles exécutent des `SELECT`/`UPDATE` en direct
   contre la connexion pour décider quelles lignes requeue, ce qui
   n'existe pas en mode `alembic upgrade --sql` (génération de SQL sans
   connexion réelle). `tests/test_compliance_migration.py` a donc dû être
   borné à `0014_compliance` (`COMPLIANCE`), pas à la tête de chaîne
   courante (`CURRENT_HEAD = 0033_requeue_unresolved_siret`), pour son
   test de génération SQL PostgreSQL hors ligne.
3. **90 tests vitest et 9 goldens Playwright d'autres pages** échouaient
   déjà sur la branche de design avant le lot A — listés dans
   `.superpowers/sdd/2026-09-02-signals-feed-sales-fixes-lot-a/baseline-vitest-failures-9de4d0f.txt`
   et `.superpowers/sdd/2026-09-02-signals-feed-sales-fixes-lot-a/playwright-results-8236aa8.txt`
   (`dashboard-login`, `dashboard-overview`, `dashboard-companies`,
   `dashboard-account`, `dashboard sidebar open mobile`). Le lot A n'a pas
   ajouté à ces échecs, mais ne les corrige pas non plus ; à traiter avec
   le lot B.
4. **`test_saas_company_architecture.py` échoue** parce que
   `companies/france.py` utilise `httpx` pour appeler l'Annuaire des
   entreprises — décision d'architecture du fondateur, distincte du refus
   générique d'appels réseau à la lecture que ce test vérifie par
   ailleurs.
