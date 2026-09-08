# ICP MATCH RUBRIC V1 — doctrine d'adjudication du matching

**Version : `icp-match-rubric-v1` — SPEC-008 §32 — 17 août 2026**

Cette rubrique adjuge une paire **award-lot × TargetICP**. Elle ne fixe jamais
un score numérique : le moteur décide du score, la rubrique décide du **grade**
(§33). Elle est la référence unique des deux passes de gold et de l'arbitrage.

---

## 1. Ce qu'on juge

> Ce contrat remporté, et les besoins plausibles qui en découlent,
> correspondent-ils à ce que ce client vend, aux entreprises qu'il cible, à sa
> zone d'intervention et à son timing commercial ?

Trois niveaux à ne jamais confondre :

    BESOIN PLAUSIBLE  ≠  FIT AVEC LE CLIENT  ≠  OPPORTUNITÉ CERTAINE

Un grade `strong_match` dit « signal commercial fortement pertinent pour cet
ICP ». Il ne dit **jamais** que le gagnant achètera.

---

## 2. Procédure — les filtres durs d'abord

Applique ces conditions **dans l'ordre**. La première qui échoue décide, et
aucune qualité par ailleurs ne la compense.

| # | Condition | Si elle échoue |
|---|---|---|
| 1 | **Mode de production** : le mode des besoins figure dans `source_modes_allowed` de l'ICP | `no_match` |
| 2 | **Recouvrement de besoin** : au moins une catégorie produite figure exactement dans les catégories primaires **ou** secondaires de l'ICP | `no_match` |
| 3 | **Type de contrat** : le type de l'award-lot ne figure pas dans `excluded_contract_types` | `no_match` |
| 4 | **Secteur** : le secteur ne figure pas dans `excluded_sectors`. Un secteur `unknown` ne bloque jamais et n'est jamais un point positif | `no_match` |
| 5 | **Âge du signal** : `as_of` − date de publication ≤ `maximum_signal_age_days`. La date d'attribution n'est jamais la date de publication | `no_match` |
| 6 | **Géographie requise** : si `geography_policy = required`, le pays de la base géographique demandée doit figurer dans les territoires. Pays **connu et différent** → `no_match`. Pays **absent** → `insufficient_data` | voir colonne |
| 7 | **Seuil de valeur** : si un seuil existe **pour la devise du contrat**, le montant doit être dans la fourchette. Aucune conversion : une devise sans seuil ne se compare pas. Montant absent → applique `unknown_value_policy` (`exclude` → `insufficient_data`) | voir colonne |

**Aucune catégorie n'est jamais rapprochée par synonymie.** Le recouvrement de
besoin est une égalité exacte de catégorie canonique.

---

## 3. Les quatre grades

### `strong_match`

Les sept filtres passent **et** toutes les conditions suivantes tiennent :

- au moins un besoin **primaire** de l'ICP est produit pour cet award-lot ;
- la géographie est **compatible** quand elle est applicable (`required` ou
  `preferred` avec pays connu dans la zone), ou explicitement `ignored` ;
- l'échelle économique est **cohérente** avec l'offre : montant connu dans une
  devise couverte par un seuil de l'ICP et au-dessus de ce seuil, **ou** ICP
  sans seuil et montant connu non dérisoire ;
- le signal est assez actionnable pour un feed principal.

### `plausible_match`

Les sept filtres passent, mais le fit est incomplet — typiquement :

- seul un besoin **secondaire** correspond ; **ou**
- la géographie est `preferred` et le pays est inconnu ou hors zone ; **ou**
- le montant est absent, dans une devise non couverte, ou non matériel, alors
  que la politique le tolère.

Commercialement défendable, mais **ne doit pas devenir `show` par défaut**.

### `no_match`

Un filtre dur a échoué de façon **évaluable** : aucun besoin commun, type ou
secteur exclu, signal trop ancien, géographie requise incompatible, montant
connu hors seuil, mode de production refusé.

### `insufficient_data`

Une condition stricte **ne peut pas être évaluée** faute de donnée :
géographie `required` sans pays publié, montant absent sous politique
`exclude`, date de publication manquante. Le motif exact est conservé — ce
n'est jamais un `no_match` déguisé.

---

## 4. Points de doctrine tranchés d'avance

1. **`offer_summary` est inerte.** Le texte libre de l'ICP ne change jamais un
   grade. Seuls les champs structurés comptent.
2. **Un secteur `unknown`** n'est ni positif ni bloquant.
3. **`winner_location`** n'est jamais évaluable dans le domaine actuel : aucune
   adresse de gagnant n'existe. Un ICP fondé dessus produit
   `insufficient_data`, jamais un match.
4. **`geography_basis = either`** : une correspondance sur le lieu d'exécution
   suffit ; l'absence des deux localisations vaut inconnu.
5. **Plusieurs besoins correspondants** ne montent pas le grade : un second
   besoin conforte, il ne transforme pas un `plausible` en `strong`. Seule la
   présence d'un besoin **primaire** fait la différence.
6. **Montant dérisoire** (déjà neutralisé en amont) : jamais un appui
   économique. Au mieux `plausible_match`.
7. **Deux lots d'une même notice** sont deux paires distinctes, jugées
   séparément — jamais fusionnées.
8. **Timing `unknown`** n'est jamais un désavantage éliminatoire, mais n'apporte
   aucun soutien.

---

## 5. Ce que le gold enregistre

Pour chaque paire : le **grade**, les filtres durs attendus (passés / échoués /
inévaluables), les raisons positives et les motifs de rejet. **Jamais un score
numérique** : c'est le moteur qui le calcule, et l'évaluation juge la décision,
la précision, le rappel, l'ordre relatif et l'explication (§33).
