# Post-mortem SPEC-006 — anatomie du problème Document Intelligence

**Kivou / GoSimap — 17 août 2026 — rapport d'analyse rétrospective**
*Toutes les mesures citées sont sourcées dans le code, les fixtures gelées ou les rapports de runs du dépôt.*

---

## 1. Le problème en une page

SPEC-006 voulait transformer les dossiers de consultation (DCE) en **exigences
d'exécution prouvées** : « le titulaire devra assurer la maintenance 24h/24 »,
extraite du CCTP, citée mot pour mot, exposable à un commercial comme un fait.
Le gate exigeait ≥ 95 % de précision d'auto-acceptation et zéro fausse
acceptation en haute confiance.

Après neuf itérations et trois held-out gelés, le meilleur pipeline atteint
**82,5 % de précision** sur l'évaluation finale — avec une évidence parfaite
(100 % des extraits retrouvables au caractère près, zéro extrait inventé) et
une couverture excellente (11 dossiers sur 12, rappel 78,8 %).

Le problème n'est **ni l'accès aux documents** (résolu pour la France), **ni
l'extraction** (résolu en R5), **ni l'évidence** (garantie par construction),
**ni le coût** (0,27 $ pour toute la campagne R5). Le problème résiduel est une
**tâche de sémantique juridique fine** que le modèle imposé (DeepSeek V4 Flash,
seul autorisé, budget 1 $) ne tranche pas assez finement : distinguer, phrase
par phrase, quatre frontières du droit des marchés publics — offre/exécution,
porteur/bénéficiaire de l'obligation, formation/exécution du contrat, et
énoncé autoportant/dépendant du contexte. Chaque itération a déplacé l'erreur
d'une frontière à la suivante ; la dernière (l'autoportance) a coûté 7 des 11
fausses acceptations finales.

---

## 2. Ce que SPEC-006 devait faire — et les invariants tenus

```
ContractAward → procédure → avis d'appel d'offres → documents
                                                      ↓
                                        texte localisé (page, paragraphe, cellule)
                                                      ↓
                                        ExecutionRequirement + Evidence
```

Trois règles absolues, **jamais violées sur aucun run** :
- pas d'extrait source exact retrouvable → pas d'exigence ;
- le modèle classe une phrase déjà extraite, il ne rédige jamais ;
- une panne (API, schéma) n'est jamais un verdict.

Ces invariants ont tenu jusqu'au bout : sur le run final, 100 % de couverture
d'évidence, 0 extrait inventé, les 12 `raw_excerpt_failures` bloqués par le
validateur déterministe avant d'atteindre quiconque.

---

## 3. Chronologie — neuf itérations, une leçon chacune

| # | Itération | Approche | Résultat clé | Leçon |
|---|---|---|---|---|
| 0 | Spike découverte (TED/SIMAP) | Suivre BT-15 depuis 100 attributions | **< 2 % des URL mènent à un fichier** ; 65 % « external » vers ~40 portails nationaux ; SIMAP = auth_required | Le problème d'ACCÈS domine ; un connecteur par portail n'est pas tenable |
| 1 | Heuristique (regex) | Modalité + sujet par motifs | **52,5 % de précision** (gold-40 manuel) ; 47,5 % des « exigences » n'en étaient pas | La cause est linguistique, pas lexicale : mêmes mots, régimes différents |
| 2 | R v0.1 (LLM, schéma lâche) | `actor` + `issue` optionnelle | **18,2 % de fausses acceptations** ; raccourcis `{"issue": …}` ; confusion porteur/destinataire en haute confiance | Schéma fermé obligatoire ; nommer le champ `obligated_actor` |
| 3 | v0.2 (porteur nommé, schéma complet) | 7 clés obligatoires | **89,5 % précision / 68 % rappel** — faux rejets = phrases coupées par la mise en page | Le rappel se perd dans le PDF, pas dans le modèle |
| 4 | R3 / DEV-3 (consensus 2 modèles) | Vérificateur à question fermée | **84,6 % seul → 94,7 % consensus, 0 FA haute confiance** ; 6/8 exigences manquées = troncatures ; 48 seconds passages pour UNE exigence récupérée | Un désaccord ne se tranche pas ; les fragments se réparent à l'EXTRACTION |
| 5 | R4 (snapshot + gates permanents) | Voisinage réel figé, évidence non tautologique | Incident **MIN_REASONING_TOKENS** : 400 tokens partaient en canal reasoning → 73-100 % de faux « échecs de schéma » (fix : 4000 → 0 échec) ; HELD-OUT-3 : **4 exigences claires sur 150** (SI/PT, dénominateur inutilisable) | Mesurer un modèle exige un harnais irréprochable ; le corpus anglophone/TED ne rend rien (0,4 % de dossiers accessibles) |
| 6 | Pivot France (Achatpublic) | BOAMP → retrait DCE anonyme | **DCE téléchargeables anonymement**, champs d'identité vides ; corpus FR-DCE-1 : 400 candidats gelés | La France est la seule source documentaire ouverte à l'échelle |
| 7 | Benchmark FR-DCE-1 (17/08 matin) | DeepSeek vs Kimi K3, primaire seul | DeepSeek **46,2 %**, Kimi **56,7 %** ; 64-69 % des FA = artefact de fragmentation (136/400 candidats tronqués par pages) ; Kimi : 12 extraits inventés, 81× plus cher ; incident crédits (402 comptés « schema failures ») | Même l'artefact neutralisé, plafond à 80-86 % ; l'intersection des 2 modèles ne donne que 62 % ; audit : 2 erreurs gold (155/156) |
| 8 | R5 + R5.1 (fix fragmentation + contradicteur + phase guard) | Pipeline complet, DEV | Fragments : **34 % → 6 % du corpus** ; contradicteur v1 : rappel 15 % (blocage lexical réflexe, p50 1,9 s) ; v2 : **94,1 %/40 %**, blockers instables, confiance saturée à « high » ; + phase guard : **100 % précision**, couverture 53 % | Le mécanisme déterministe marche ; DeepSeek en rôle contradicteur est instable et jamais calibré — deux prompts très différents, même mode d'échec |
| 9 | **FR-DCE-FINAL (run unique)** | Pipeline gelé, gold avant modèle | **82,54 %** (52 VP / 11 FP), rappel 78,8 %, couverture 11/12, évidence 100 % | 7/11 FP = la frontière d'AUTOPORTANCE (voir §5) ; verdict : NOT DONE |

---

## 4. Anatomie du problème — cinq couches, trois résolues

### Couche 1 — L'accès aux documents *(résolue pour la France, fermée ailleurs)*
TED publie des adresses de portails, pas des documents : < 2 % de fichiers
directement téléchargeables, ~40 hôtes distincts pour 74 procédures, SIMAP
verrouillé derrière authentification. Le spike anglophone a rendu 2 dossiers
accessibles sur 500 avis (0,4 %). La découverte qui a sauvé la spec :
**Achatpublic sert les DCE anonymement** (retrait POST avec champs d'identité
vides) — d'où le pivot francophone et trois corpus français propres.

### Couche 2 — L'extraction et la fragmentation *(résolue en R5)*
Les blocs PDF sont des pages ; le découpage page → phrases fabriquait des
moitiés de phrases. Coût mesuré : 136 étiquettes `context_fragment` sur 400
(34 % de FR-DCE-1), 64-69 % des fausses acceptations du benchmark. Trois
défauts corrigés en R5 (découpage sur `LogicalTextSpan`, blancs de bordure,
dérive de 14 caractères du mapping brut dans `_soften_wraps`) : le corpus final
ne compte plus que **6 % de fragments**, et le rappel du pipeline est passé de
40 % à 78,8 %. C'est la plus grande victoire technique de la spec.

### Couche 3 — La sémantique juridique fine *(NON résolue — le cœur du problème)*
Quatre frontières que le français des marchés publics écrit avec les mêmes
mots (« doit », « titulaire », « prestations », « engagement ») :

1. **Offre vs exécution** — « Tous les prix doivent être chiffrés » (offre) vs
   « le titulaire devra assurer la maintenance » (exécution). Les critères de
   jugement décrivent le travail futur avec le vocabulaire de l'exécution.
2. **Porteur vs bénéficiaire** — « Le montant des pénalités ne pourra excéder
   5 % » protège le titulaire mais oblige l'acheteur. Une seule confusion de
   ce type écartait 78 exigences réelles du dossier slovène.
3. **Formation vs exécution** — « S'engage … à exécuter les prestations »
   (clause de signature d'AE) contient littéralement le mot « exécuter ».
4. **Autoportance vs contexte** — « Il devra adapter ses approvisionnements » :
   le pronom se résout dans la phrase précédente. Exigence réelle ? Oui, pour
   qui lit le bloc. Fait exposable seul ? Non, pour qui exige une citation
   autoportante.

Chaque itération a durci une frontière et l'erreur a migré vers la suivante.
Le run final meurt sur la quatrième.

### Couche 4 — Le modèle contraint *(la limite opérante)*
Contrainte assumée : DeepSeek V4 Flash uniquement, 1 $ de budget (Kimi :
+10 pts de précision mais 12 extraits inventés et 81× le prix — disqualifié).
Mesures :
- **Primaire** : honnête mais insuffisant seul — 44-46 % de précision
  d'auto-acceptation, rappel 95 %.
- **Contradicteur** : le vrai point dur. Version 1 : blocage lexical réflexe
  (latence p50 1,9 s, « capacité » → qualification, « normes » →
  informational), rappel 15 %. Version 2 : raisonne (12,4 s) mais reste
  sur-sévère, ses motifs **changent d'une itération à l'autre sur la même
  phrase**, et sa confiance est **saturée** : 100 % « high » sur les 22 vraies
  exigences bloquées à tort ET sur l'unique fausse acceptation — dont la
  clause d'AE que son propre prompt citait verbatim comme exemple à bloquer.
  Deux prompts très différents, même mode d'échec : **ce n'est pas un problème
  de prompt.**

### Couche 5 — L'épistémologie du gold *(le paradoxe final)*
Le gold final a été durci par une passe contradictoire (PASS B) qui a rétrogradé
19 exigences pour non-autoportance (pronoms sans référent, anaphores, passifs
impersonnels). Résultat mesurable au run : **7 des 11 fausses acceptations
finales sont exactement ces candidats-là**. Le pipeline lit le voisinage et
résout les référents ; le gold exige qu'un fait montré au client soit
autoportant. Les deux positions sont défendables — mais elles définissent des
tâches différentes, et le gate a mesuré la plus stricte. Sans cette frontière,
la précision finale serait ≈ 92,6 % (59/63,7 — toujours sous 95 : les 4 FP
restants sont des confusions d'acteur réelles).

---

## 5. La mécanique de l'échec final, chiffrée

```
300 candidats
 ├─ Primaire accepte ............. 112   (rappel primaire élevé, précision faible)
 ├─ Évidence exacte ✂ ............  12 raw_excerpt_failures bloqués
 ├─ Contradicteur confirme .......  76
 ├─ Phase guard ✂ ................   8 (AE, règlements de consultation)
 └─ AUTO_ACCEPTED ................  63  = 52 vraies + 11 fausses  → 82,54 %
```

Les 11 fausses : 5 fragments à pronom/anaphore, 2 acteurs impersonnels,
1 acteur mixte, 2 obligations de l'acheteur, 1 acteur indéterminé. Aucune
n'est un extrait inventé, une phase d'offre grossière ou un formulaire — les
gardes déterministes ont tout absorbé. Ce qui reste est exactement ce qu'aucune
règle mécanique ne tranche : *qui porte l'obligation quand la phrase ne le dit
pas elle-même.*

---

## 6. Ce que la spec laisse d'acquis (committé, `74b03a85`)

1. **La chaîne d'acquisition France** : BOAMP → Achatpublic, retrait DCE
   anonyme, garde-fous d'archives hostiles — la seule source documentaire
   ouverte à l'échelle identifiée en Europe.
2. **`LogicalTextSpan` + fix fragmentation** : 0 candidat tronqué par frontière
   de page, évidence multi-bloc (un extrait brut par page traversée).
3. **La validation d'évidence exacte** : aux espaces près, jamais tautologique.
4. **La taxonomie de pannes API** : plus jamais un 402 compté comme un échec
   de modèle (l'incident Kimi est devenu un test de régression).
5. **Trois evals gelées par SHA** avec golds adjudiqués avant tout appel
   modèle, journaux de corrections, et disjonction triple testée — dont
   **FR-DCE-FINAL, l'EVAL permanente de référence** (66 exigences claires).
6. **Le contradicteur + phase guard** : code expérimental prêt pour une reprise.
7. **La politique MVP verrouillée** : `AUTO_DOCUMENT_REQUIREMENTS_ENABLED =
   False`, `document_requirement = unavailable` — réactiver exige de changer un
   contrat testé, pas d'oublier une ligne.

Coût total de la campagne R5 → FINAL : **0,27 $** d'API (984 appels utiles),
~3 h de mur d'horloge, 1 144 tests verts.

## 7. Les incidents d'infrastructure (tous convertis en tests)

| Incident | Effet avant correction | Correction |
|---|---|---|
| `max_tokens=400` vs canal reasoning (R4) | 73-100 % de faux « échecs de schéma » | Plancher 4000, gardé par une exception |
| Crédits OpenRouter épuisés (402) | 10 pannes comptées comme échecs modèle | Taxonomie §32 + `last_failure` |
| `_soften_wraps` non longueur-préservé | Preuves décalées de 14 caractères | Remplacement 1:1, test sur pages réelles |
| Filtre modalité comparé à `"none"` (str) | Filtre inopérant, corpus dilué | Comparaison à `None`, test de régression |
| Évidence tautologique de DEV-3 | Couverture de preuve « vraie par construction » | `CandidateSnapshot` avec blocs sources réels |

## 8. Conditions d'une reprise (matière pour SPEC-009)

À battre : **FR-DCE-FINAL, 82,54 % → ≥ 95 %**, sans toucher au gold ni au corpus.
Leviers, par ordre de rendement attendu :

1. **Le modèle du contradicteur** — la variable jamais explorée (interdite par
   protocole). Le rôle exige stabilité et calibration, pas de la puissance
   brute ; le primaire peut rester DeepSeek.
2. **Une garde déterministe d'autoportance** — pronom/démonstratif en tête de
   phrase sans référent interne, anaphores datées (« À cette date ») :
   détectable mécaniquement, aurait éliminé ~5-7 des 11 FP finales. C'était le
   symétrique exact du PASS B, jamais implémenté car gelé trop tard.
3. **Trancher la doctrine produit** : soit l'exigence exposée est la phrase
   autoportante (gold actuel — alors la garde n° 2 est obligatoire), soit c'est
   la phrase *résolue avec son voisinage cité* (alors le gold doit être
   ré-adjudiqué sous cette règle et l'UI doit montrer le contexte).
4. **La calibration de confiance** — aucun des deux rôles DeepSeek n'a produit
   une confiance corrélée à la justesse ; « high » ne veut rien dire. Un seuil
   de probabilité calibré vaudrait mieux qu'un champ déclaratif.

---

*Sources : docstrings et tests du commit `74b03a85` ; fixtures gelées
(`document100.json`, `linkage800.json`, `heldout2_gold.json`,
`dev3_model_runs.json`, `heldout3_gold.json`, `fr_dce_*`) ; rapports de runs
`fr_dce_bench_results_2026-08-17.json`, `fr_dce_r5_dev_*`,
`fr_dce_r51_dev_report_2026-08-17.json`, `fr_dce_final_run_2026-08-17.json` ;
rapport de clôture `docs/reports/2026-08-17-spec006-r5-final.md`.*
