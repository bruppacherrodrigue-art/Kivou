# Commercial Signal Rubric v1

**Version** : `commercial-signal-rubric-v1`
**Gelée le** : 2026-08-17, AVANT toute adjudication et AVANT toute lecture des scores moteur.
**Périmètre** : SPEC-009 Signal-100 — évaluation commerciale de bout en bout.

---

## 0. Ce que cette rubrique n'est pas

Elle ne recopie **aucune** règle interne de Kivou. Elle ne demande jamais :

- si une règle du Need Graph s'est déclenchée correctement ;
- si un filtre dur de l'ICP Matching a été appliqué comme prévu ;
- si le Signal Score est mathématiquement juste.

Ces questions ont été traitées par SPEC-007 et SPEC-008. Elles sont closes.

Cette rubrique pose une seule question, sous sept angles :

> **Ce signal donnerait-il à un fournisseur B2B une raison crédible d'investiguer
> ou de contacter le gagnant maintenant ?**

L'adjudicateur ne voit ni score, ni bande, ni décision, ni `rule_id`, ni
composant de score, ni attente gold (§28). Il juge un signal, pas un moteur.

---

## 1. Frontière de vérité (§4)

Quatre statuts distincts, jamais confondus :

```text
FAIT PUBLIC        ce que l'avis publie
BESOIN DÉRIVÉ      une hypothèse d'exécution plausible
ICP FIT            la pertinence pour ce que vend le client Kivou
INTENTION D'ACHAT  n'existe pas, et n'est jamais affirmée
```

Autorisé :

> L'entreprise X a remporté un marché de construction de 8,4 MCHF. Un besoin de
> capacité en personnel et en EPI est plausible. Ces besoins correspondent à
> l'ICP du fournisseur Y. Le signal mérite investigation.

Interdit :

> X va acheter des EPI. X cherche actuellement du personnel. X a besoin des
> services de Y. X va sous-traiter.

Une formulation qui présente une hypothèse comme une certitude est un
**overclaiming critique** et déclenche à elle seule le verdict `D`.

---

## 2. Mode documentaire (§5, §51)

Tous les signaux du banc sont produits en `source_mode = metadata_fallback`.
Aucun document de marché n'a été lu. Chaque signal porte la limitation :

> Need inferred from public award information.
> No validated execution requirement was available.

L'adjudicateur ne pénalise **pas** un signal pour cette limitation : elle est la
règle du banc, pas un défaut du signal. Il pénalise en revanche tout signal qui
présenterait un besoin comme une exigence d'exécution confirmée.

---

## DIMENSION A — FACTUAL INTEGRITY (§18)

**Question** : les faits publics affichés sont-ils exacts et soutenus par les
preuves fournies ?

Vérifier :

- le gagnant est-il correct ?
- l'attribution est-elle réelle ?
- l'objet du contrat est-il correctement représenté ?
- le montant est-il correctement représenté ?
- la devise est-elle correcte ?
- la date de publication est-elle correcte ?
- le lieu, quand il est affiché, est-il correct ?
- les preuves soutiennent-elles les faits publics affichés ?

**Grades** : `pass` | `critical_failure`

Un signal qui utilise un fait critique faux est `critical_failure`. Un champ
absent n'est pas un fait faux : « montant non publié » est honnête, « montant
0 CHF » inventé ne l'est pas.

---

## DIMENSION B — NEED CREDIBILITY (§19)

**Question** : les faits connus donnent-ils réellement une raison raisonnable de
penser que ce type de besoin peut devenir pertinent pour l'exécution du contrat ?

**Ne pas demander** « ce besoin est-il garanti ? ». La certitude n'existe pas.

**Grades** :

| Grade | Signification |
|---|---|
| `credible` | Le lien fait → besoin tient de lui-même pour un praticien du secteur. |
| `plausible_but_weak` | Le lien est défendable mais générique ou ténu. |
| `unsupported` | Rien dans les faits publics ne porte ce besoin. |
| `contradicted` | Les faits publics vont contre ce besoin (le besoin est le livrable même, ou l'objet l'exclut). |

Piège nommé : le **livrable pris pour un besoin aval**. Un marché *de fourniture
d'EPI* ne crée pas un besoin d'EPI chez le gagnant : c'est ce qu'il vend.
Ce cas est `contradicted`.

---

## DIMENSION C — ICP COMMERCIAL FIT (§20)

**Question** : une entreprise vendant réellement ce que décrit cet ICP
aurait-elle une raison cohérente de s'intéresser à ce gagnant ?

**Grades** : `strong_fit` | `plausible_fit` | `weak_fit` | `no_fit`

- `strong_fit` — l'offre de l'ICP répond directement au besoin dérivé, et la
  géographie comme la taille du contrat rendent l'approche réaliste.
- `plausible_fit` — la correspondance tient mais une dimension (géographie,
  taille, spécialité) demande vérification.
- `weak_fit` — la correspondance est nominale : la catégorie coïncide, la réalité
  commerciale beaucoup moins.
- `no_fit` — aucune raison commerciale cohérente.

Un décalage géographique dur (l'ICP ne vend pas dans ce pays et ne peut pas y
livrer) est `no_fit`, jamais `weak_fit`.

---

## DIMENSION D — ACTIONABILITY (§21)

**Question fondamentale** : si j'étais commercial dans cette entreprise
fournisseur, ce signal justifierait-il raisonnablement quelques minutes
d'investigation ou une prise de contact ciblée ?

**Grades** :

| Grade | Signification |
|---|---|
| `actionable` | Le signal donne déjà une raison claire et spécifique de prospecter. |
| `worth_investigating` | Crédible, mais une courte vérification reste nécessaire avant contact. |
| `too_weak` | Techniquement cohérent, trop générique pour être commercialement utile. |
| `misleading` | Pourrait envoyer le commercial dans une mauvaise direction. |

Un signal `generic` en dimension E **ne peut pas** être `actionable` (§22).

---

## DIMENSION E — SPECIFICITY (§22)

**Question** : le signal explique-t-il réellement *ce qui pourrait être
nécessaire*, ou seulement *que cette entreprise a gagné un contrat* ?

**Grades** : `specific` | `acceptable` | `generic`

- `specific` — le besoin est nommé avec un ancrage concret (nature des travaux,
  échelle, durée, lieu) qui oriente l'argumentaire.
- `acceptable` — le besoin est nommé, l'ancrage reste partiel.
- `generic` — « a gagné un marché, aura donc besoin de ressources ».

---

## DIMENSION F — TIMING / WHY NOW (§23)

**Grades** : `clear` | `acceptable` | `unknown` | `wrong`

- `clear` — une date opérationnelle fiable (début d'exécution, durée) justifie
  l'attention maintenant.
- `acceptable` — la date de publication récente suffit à justifier le moment.
- `unknown` — aucune date opérationnelle fiable n'existe. **Acceptable.**
- `wrong` — timing inventé, avis trop ancien au regard de la politique de l'ICP,
  ou interprétation de date incorrecte.

Aucun timing faux n'est acceptable : `wrong` implique `D`.

---

## DIMENSION G — PROOF QUALITY (§24)

**Question** : un client pourrait-il comprendre pourquoi Kivou lui montre ce
signal et vérifier les faits publics principaux ?

**Grades** : `strong` | `adequate` | `insufficient`

La preuve porte sur les **faits**. Elle ne prétend jamais prouver l'achat futur.

- `strong` — chaque fait affiché est traçable à la source publique citée.
- `adequate` — les faits critiques (gagnant, objet, date) sont traçables.
- `insufficient` — un fait affiché n'est rattaché à aucune source vérifiable.

---

## VERDICT COMMERCIAL FINAL (§25)

Chaque signal reçoit exactement **un** verdict.

### A — `actionable_signal`

Conditions minimales, toutes requises :

```text
factual integrity = pass
need            = credible
ICP             = strong_fit
actionability   = actionable
specificity    != generic
proof          != insufficient
```

### B — `useful_lead`

Signal commercialement légitime mais nécessitant encore une vérification.
Typiquement :

```text
need            credible ou plausible_but_weak
ICP             strong_fit ou plausible_fit
actionability   worth_investigating
factual integrity = pass
timing         != wrong
```

### C — `weak_signal`

Techniquement possible mais insuffisamment utile pour mériter le feed principal.
Typiquement `too_weak`, ou `weak_fit`, ou `generic`.

### D — `false_or_misleading`

Erreur factuelle, absence de fit réel, besoin contradictoire, timing faux, ou
signal susceptible d'induire un commercial en erreur.

Déclencheurs suffisants et non négociables :

- `factual integrity = critical_failure`
- `need = contradicted` ou `need = unsupported`
- `ICP = no_fit`
- `actionability = misleading`
- `timing = wrong`
- overclaiming : une hypothèse présentée comme une certitude d'achat

---

## CRITICAL FALSE SIGNAL (§26)

Un signal est un **critical false signal** si l'un de ces cas est constaté :

```text
wrong winner
wrong award
wrong contract
fabricated amount
wrong currency
unsupported need presented as meaningful
no real ICP fit
hard geographic mismatch
commercially absurd interpretation
deliverable mistaken for downstream need
stale signal that should have been excluded
evidence contradicts displayed fact
```

Gate absolu du banc :

```text
CRITICAL FALSE SIGNALS = 0
```

Un critical false signal implique toujours le verdict `D`. L'inverse n'est pas
vrai : un `D` peut être seulement trop faible ou mal ciblé sans être critique.

---

## PROTOCOLE D'ADJUDICATION (§27–§31)

1. **Deux perspectives indépendantes**, sur la même vue aveugle.
   - **Reviewer A — B2B Sales Director.** « Voudrais-je ceci dans le feed de mon
     équipe commerciale ? » Évalue utilité commerciale, spécificité,
     actionnabilité, fit, bruit.
   - **Reviewer B — Procurement / Contract Analyst.** « La preuve contractuelle
     publique soutient-elle raisonnablement l'interprétation commerciale ? »
     Évalue faits, sens du contrat, plausibilité du besoin, overclaiming, preuve.
   Les deux revues sont indépendantes : aucun des deux ne voit l'autre.

2. **Arbitrage** si A et B divergent de plus d'un niveau sur le verdict final,
   ou si l'un des deux donne `D`. L'arbitre voit la preuve brute du signal et
   cette rubrique, **jamais** les verdicts précédents.

3. **Conservation** : `review_a`, `review_b`, `arbitration_if_any`,
   `final_verdict`.

4. **Stabilité de la doctrine** (§31) — gate minimal :

```text
agreement within one grade >= 90 %
```

En deçà, la rubrique est déclarée instable et SPEC-009 est invalide, sans
qu'aucun moteur ne soit modifié.

Ordre des verdicts pour mesurer l'écart : `A < B < C < D` (distance de 1 entre
voisins).
