# SPEC-009E R1 — Current DECP + Contract Notification Correction

**Rien n'est committé.** SPEC-009E reste non approuvée.

> ## ⚠ COMPLÉTÉ ET PARTIELLEMENT CORRIGÉ PAR R2
>
> Deux points de ce rapport sont dépassés :
>
> * la politique de fraîcheur y est **mutuellement exclusive** — une décision
>   périmée y efface une notification fraîche. R2 sépare les trois horloges.
> * la section §6 additionne 45 et 383 pour annoncer « 428 événements
>   exploitables par semaine ». Ce sont deux comptages d'événements bruts dont le
>   recouvrement n'était pas mesuré. R2 mesure : **415 à 424 marchés distincts,
>   dont 45 seulement prêts pour un client.**
>
> Tout le reste — jeu DECP courant, `contract_notification_date`, adapter 2022,
> sûreté de formulation, fixtures de clone frais — est valide et préservé.
>
> Voir `docs/reports/2026-08-18-spec009e-r2-multiclock-unique-signals.md`.

---

## 0. LA FAUTE, ET SA CAUSE

Le superviseur a raison, et le fait est vérifié avant toute correction :

```text
decp-2022-marches-valides   COURANT   689 062 marchés   notif. la plus récente 2026-08-17
decp-v3-marches-valides     HÉRITÉ    702 901 marchés   notif. la plus récente 2024-02-08
```

Recensement posé aux deux portails le 2026-08-18 :

```text
contrats notifiés dans les…        courant     hérité
7 derniers jours                       383          0
30 derniers jours                    6 661          0
60 derniers jours                   18 552          0
90 derniers jours                   31 665          0
365 derniers jours                 196 160          0
```

**Cause racine.** J'ai choisi le jeu de données sur la plausibilité de son nom :
« decp-v3 » se lit comme « version 3 », donc comme la plus récente. C'est
exactement la discipline que SPEC-009E avait appliquée avec succès aux
*champs* — refuser de déduire une sémantique d'un nom, ce qui a permis
d'attraper le piège `cac:TenderResult/cbc:AwardDate` du BOAMP — sans jamais
l'appliquer au choix de la *source*.

Le contrôle que j'avais fait — « quelle est la notification la plus récente ? » —
a bien rendu 2024-02-08. Je l'ai lu comme une propriété de DECP au lieu d'y voir
le signal que j'interrogeais le mauvais jeu. C'est le défaut le plus coûteux du
travail : une vérification exécutée, et mal interprétée.

La leçon est écrite dans le code, pas seulement ici — l'en-tête de
`connectors/decp/parser.py` et la note du registre `recency/sources.py` la
portent toutes deux, de sorte qu'un futur lecteur du module la rencontre avant
d'en changer la source.

---

## 1. CURRENT DECP SOURCE

```text
identifiant officiel   decp-2022-marches-valides
titre                  Données Essentielles de la Commande Publique (DECP)
                       — Arrêté du 22/12/2022 — Marchés
licence                Licence Ouverte v2.0 (Etalab)
enregistrements        689 062
dernière mise à jour   2026-08-17T12:41:12Z  (quotidienne)
champs                 55
```

### Différences de schéma face à `decp-v3`

Aucune équivalence n'a été supposée : les deux schémas ont été relus champ par
champ.

```text
SUPPRIMÉS par le schéma 2022 — et ce sont les plus regrettables
  titulaire_denominationsociale_2 / _3   raison sociale du titulaire
  acheteur_nom                           nom de l'acheteur
  lieuexecution_nom                      nom de la commune d'exécution
  booleanmodification, objetmodification, titulairesmodification
  typeprix, typeprix0, modaliteexecution, technique  (singuliers)
  created_at, updated_at

AJOUTÉS par le schéma 2022
  idaccordcadre                          rattachement à un accord-cadre
  typegroupementoperateurs               forme du groupement
  modalitesexecution, techniques, typesprix          (pluriels)
  origineue, originefrance, marcheinnovant
  considerationssociales / environnementales
  bloc de modification complet           idtitulairemodification, …
  bloc de sous-traitance complet         idsoustraitant, montantactesoustraitance, …

CHANGÉS
  titulaire_id_1                         `int` → `text`
  montant                                libellé explicite : « Montant HT forfaitaire
                                         ou estimé MAXIMUM en euros »
```

Ce dernier point n'est pas cosmétique : le conflit de montant que SPEC-009E
avait diagnostiqué sans pouvoir l'expliquer est désormais **documenté par la
source elle-même**. DECP publie un maximum, le BOAMP la valeur de l'offre
retenue. Ce ne sont pas deux versions d'un même chiffre.

### Le piège de remplissage du jeu courant

```text
la chaîne littérale « CDL » occupe les champs vides
  dureemoismodification                      1000/1000
  idtitulairemodification                    1000/1000
  idmodificationactesoustraitance            1000/1000
  montantmodification                         997/1000
  idmodification                              994/1000
  … et huit autres champs
```

Même nature que les `2000-01-01` du BOAMP, mêmes conséquences si on la prend
pour une valeur : elle créerait des co-titulaires et des références de contrat
imaginaires. `FILLER_VALUES` la traite comme une absence, et deux tests le
vérifient sur des enregistrements réels.

### Couverture 2026 du jeu courant

Sur 1 000 contrats notifiés entre le 2026-05-20 et le 2026-08-18 :

```text
id, nature, objet, codecpv, procedure          100,0 %
acheteur_id, titulaire_id_1                    100,0 %
datenotification, datepublicationdonnees       100,0 %
montant, dureemois                             100,0 %
lieuexecution_code + typecode                  100,0 %
typegroupementoperateurs, offresrecues         100,0 %
idaccordcadre                                   19,3 %
titulaire_id_2                                   5,3 %

types d'identifiant titulaire                  SIRET 998 · TVA 2
```

---

## 2. DATE SEMANTICS — CHANGEMENT DE SCHÉMA PARTAGÉ

> ### ⚠ MODIFICATION DU DOMAINE CANONIQUE
>
> `ContractAward` gagne **un champ** :
>
> ```python
> contract_notification_date: dt.date | None = None
> ```
>
> C'est la plus petite extension possible. Elle touche un modèle partagé par
> les quatre connecteurs, le moteur de compréhension et tous les corpus gelés.

Les cinq concepts sont désormais séparés dans le code :

```text
award_date                    la DÉCISION — l'acheteur a retenu ce titulaire
contract_signature_date       la CONCLUSION du contrat  (eForms BT-145)
contract_notification_date    la NOTIFICATION au titulaire        ← NOUVEAU
contract_start_date           le DÉBUT d'exécution
PublicEvent.published_at      la PUBLICATION de l'avis / de la donnée
Provenance.retrieved_at       la DÉCOUVERTE par Kivou
```

### Sur le nom `contract_signature_date`

R1 §2 nomme le concept `contract_conclusion_date`. Le champ existant porte déjà
cette sémantique — il reçoit BT-145, littéralement *contract conclusion date* —
sous un nom hérité du premier connecteur écrit. Le renommer toucherait quatre
connecteurs, le moteur de compréhension, les snapshots et les corpus gelés de
SPEC-009C et SPEC-009D, pour un gain nul et un risque réel sur des artefacts
que §8 demande de ne pas bouger.

Le choix retenu est donc : **garder le nom, écrire la sémantique dans le
modèle**. Le commentaire de `ContractAward` dit désormais explicitement lequel
des cinq actes chaque champ porte. Si le superviseur préfère le renommage, il
est mécanique et se fait en une passe — mais il n'appartient pas à une R1
chirurgicale.

### Un invariant a fait son travail

Le premier commentaire que j'avais écrit nommait « SIMAP » et « DECP » pour
illustrer les champs. Le test `test_ajouter_un_portail_ne_touche_pas_contract_award`
a échoué immédiatement : **aucun nom de portail ne doit apparaître dans le module
des contrats attribués.** L'invariant est juste et la faute était la mienne ; le
commentaire décrit maintenant les actes, pas les sources.

### Mapping DECP

```text
dateNotification            → contract_notification_date    can_represent_award_date: NO
datePublicationDonnees      → PublicEvent.published_at      can_represent_award_date: NO
dateNotification…Modification → non mappé                   can_represent_award_date: NO
dateNotificationActeSousTraitance → non mappé               can_represent_award_date: NO
```

Vérifié par test sur les quatre enregistrements réels de la fixture : aucun ne
produit `award_date`, aucun ne produit `contract_signature_date`.

L'Evidence et la provenance sont préservées : chaque contrat DECP porte son
`source_url` reconstruit vers l'enregistrement du portail et son `retrieved_at`.

---

## 3. RECENCY POLICY EXTENSION

`award-recency-v0.1` → **`award-recency-v0.2`**.

`RECENT_AWARD` n'est **pas** affaibli. Les trois états datés gardent leur
définition au jour près, et un test le prouve directement :

```python
def test_an_old_award_date_is_not_rescued_by_a_fresh_notification():
    got = notified(award="2026-05-20", notification="2026-08-17", published="2026-08-18")
    assert got.status == "stale_award"
```

Sept états au lieu de six :

```text
recent_award                 décision datée, valide, ≤ 30 j
aging_award                  31 à 60 j
stale_award                  > 60 j
recently_notified_contract   décision INCONNUE, notification valide ≤ 30 j   ← NOUVEAU
recently_published_award     décision inconnue, avis paru ≤ 30 j
award_date_unknown           rien d'exploitable
invalid_award_date           date incohérente — diagnostic
```

La hiérarchie des actes est explicite dans le code, et c'est elle qui garantit
qu'on n'affaiblit rien :

```text
décision d'attribution   ce que le client veut vraiment savoir — l'emporte toujours
notification du contrat  un acte réel, daté, mais postérieur
parution de l'avis       une date sur le document, pas sur l'entreprise
```

Nouveaux seuils et métriques, tous versionnés :

```text
RECENT_NOTIFICATION_DAYS = 30      configurable par argument nommé
notification_age_days              as_of − contract_notification_date
notification_delay_days            publication_date − contract_notification_date
```

Une notification future ou vieille de plus de dix ans ne produit **jamais**
`recently_notified_contract` : elle est ignorée et le signal retombe sur la
publication. La valeur brute reste conservée.

---

## COPY / CLAIM SAFETY

```text
RECENT_AWARD                 fr  « {société} vient de remporter un marché public. »
                             en  « {société} has recently won a public contract. »

RECENTLY_NOTIFIED_CONTRACT   fr  « Un marché attribué à {société} vient d'être notifié. »
                             en  « A public contract awarded to {société} has recently
                                   been notified. »

RECENTLY_PUBLISHED_AWARD     fr  « Une attribution concernant {société} vient d'être
                                   publiée. »
```

La phrase de notification parle du **marché**, pas de l'entreprise : « un marché
attribué à X » énonce un fait acquis sans dater la victoire — ce que la source
ne permet pas de faire.

L'interdiction est vérifiée sur **7 états × 2 langues** contre une liste de
marqueurs (`vient de remporter`, `has recently won`, `a remporté`, `just won`…).
Ajouter un huitième état sans phrase fait échouer la suite.

Types d'événement MVP : **trois** désormais, liste fermée et testée.

```text
RECENT_AWARD · RECENTLY_NOTIFIED_CONTRACT · RECENTLY_PUBLISHED_AWARD
aging_award et stale_award n'en portent aucun : exacts, mais pas des nouveautés
```

---

## 4. RE-MEASURE CURRENT DECP

Échantillon gelé de **1 000 contrats**, notifiés du 2026-05-20 au 2026-08-18,
tirés par notification décroissante.

```text
enregistrements exploitables           1 000 / 1 000
contract_notification_date connue      1 000   100,0 %
award_date connue                          0     0,0 %
contract_signature_date connue             0     0,0 %

notifiés ≤ 7 jours     383   ← recensement portail sur la fenêtre exacte
notifiés ≤ 30 jours  6 661
notifiés ≤ 60 jours 18 552
notifiés ≤ 90 jours 31 665

délai notification → publication de la donnée
  p25 0 j · médiane 2 j · p75 5 j · p90 6 j · max 11 j

identité et faits, sur l'échantillon
  acheteur SIRET            100,0 %      acheteur nommé        0,0 %
  titulaire identifié        99,8 %      titulaire nommé       0,0 %
  montant                   100,0 %      CPV                  99,9 %
  durée en mois             100,0 %      lieu d'exécution    100,0 %
  identifiant de contrat    100,0 %      lot                   0,0 %
  procédure (nature)        100,0 %      identifiant procédure 0,0 %
```

Deux lectures s'imposent.

**DECP publie vite.** Deux jours de médiane entre la notification et la mise en
ligne de la donnée. C'est le canal français le plus rapide, et de loin — le
BOAMP met 58 jours médians entre la décision et la parution de l'avis.

**DECP n'identifie que par numéro.** Zéro raison sociale, ni pour le titulaire
ni pour l'acheteur. La complémentarité avec le BOAMP est exacte et symétrique :
l'un nomme sans identifier, l'autre identifie sans nommer.

Un biais doit être dit : l'échantillon étant les 1 000 notifications les plus
récentes, sa distribution d'âge (médiane 8 jours, max 13) décrit ce que voit un
feed vivant, **pas** la population des 689 062 marchés. Les volumes cités
au-dessus viennent du recensement portail, pas de l'échantillon.

---

## 5. BOAMP × CURRENT DECP LINKAGE

Expérience refaite sur des périodes qui se recouvrent réellement — ce qui était
impossible avec le jeu hérité.

**121 couples (acheteur, titulaire)** tirés d'award-lots BOAMP d'août 2026 ont
été interrogés dans le jeu courant : **44 ont trouvé au moins un enregistrement
DECP**, contre 14 sur le jeu hérité et sans recouvrement temporel.

Trois avis et leurs onze contrepartie DECP sont gelés comme fixture. Ils
couvrent les trois cas :

```text
26-79799  logiciel, Calvados
  BOAMP  sign. 2026-07-16   250 000 €   CPV 48000000
  DECP   notif 2026-07-16   250 000 €   CPV 48000000-8
  → STRONG, aucun conflit — date, montant et CPV concordent tous les trois

26-79670  Ville de Paris
  BOAMP  sign. 2026-07-09   200 000 €   CPV 73430000
  DECP   notif 2026-07-09   100 000 €   CPV 73430000-5
  → STRONG avec CONFLIT de montant : DECP publie un maximum, BOAMP l'offre retenue

26-79715  denrées alimentaires, six lots
  neuf enregistrements DECP du MÊME couple acheteur/titulaire, de 2021 à 2025
  → UNRESOLVED sur les neuf : le leurre de SPEC-009E se reproduit à l'identique
```

Les règles anti-faux-lien apprises en SPEC-009E sont conservées telles quelles,
et la mesure les confirme sur le jeu courant :

```text
strong       même acheteur + même titulaire + notification à ≤ 7 j de la conclusion
probable     même acheteur + même titulaire + accord de CPV ou de montant, sans date
unresolved   tout le reste — y compris le couple de parties seul
```

**Le couple (acheteur, titulaire) n'identifie toujours pas un contrat.** Il
identifie une relation commerciale, et neuf contrats étalés sur quatre ans le
démontrent une seconde fois.

### FIELD_PRIORITY — réévaluée sur les données courantes

`france-link-v0.1` → **`france-link-v0.2`**.

```text
champ                       préférée  conflit       raison (mesurée)
winner_siret                DECP      diagnostic    DECP 99,8 % vs BOAMP 38,3 %
winner_legal_name           BOAMP     silencieux    le schéma 2022 n'a AUCUN champ de nom
buyer_siret                 DECP      diagnostic    BOAMP 53,8 %
publication_date            BOAMP     silencieux    DECP date la donnée, pas l'avis
award_date                  BOAMP     silencieux    DECP n'en publie aucune
contract_signature_date     BOAMP     silencieux    DECP 2022 n'en publie aucune → sans conflit possible
contract_notification_date  DECP      silencieux    seul DECP publie cet acte          ← NOUVEAU
amount                      BOAMP     diagnostic    offre retenue vs « montant maximum »
cpv                         BOAMP     diagnostic    classements divergents
place_of_performance        DECP      silencieux    code typé vs NUTS de procédure
duration_months             DECP      silencieux    absent des eForms BOAMP
```

Deux lignes ont changé à la lumière des données courantes :
`contract_signature_date` passe de `diagnostic` à `prefer_without_diagnostic`
— le schéma 2022 n'en publie aucune, donc aucun conflit n'est possible — et
`contract_notification_date` apparaît.

**La fusion n'écrase toujours rien.** Le contrat canonique ressort inchangé,
DECP ajoute ses faits à côté, les divergences deviennent des diagnostics portant
les deux valeurs et leur origine.

---

## 6. FRANCE PRODUCT TIMING

La comparaison ne fond jamais décision et notification dans une seule métrique.

```text
source                    mesure                   n      award_date   « récent »   délai
SIMAP (CH)                décision                76        98,7 %       64,5 %      5 j¹
TED (UE)                  décision                34        38,2 %       20,6 %     27 j¹
BOAMP (FR)                décision             1 482        29,2 %        3,0 %     58 j¹
DECP (FR)                 notification         1 000         0,0 %          —²       2 j³

¹ délai médian décision → parution de l'avis
² sans date de décision, aucun statut « récent » au sens de RECENT_AWARD
³ délai médian notification → publication de la donnée
```

### A. Combien d'événements français par semaine peuvent dire « vient de remporter » ?

```text
45 par semaine
```

Source : BOAMP, `award_date` (BT-1451) valide et ≤ 30 jours, observés sur une
fenêtre de sept jours non plafonnée. Les 45 sont réels et nommés — Sopra Steria
(9,6 M€, J-7), Dupont Restauration (2,6 M€, J-19), Rock SAS (800 k€, J-25)…

### B. Combien d'événements supplémentaires peuvent dire « vient d'être notifié » ?

```text
383 par semaine     (6 661 sur 30 jours)
```

Source : recensement DECP sur la fenêtre exacte.

> **Un bug de mon instrument a été trouvé et corrigé avant d'être rapporté.**
> Le premier calcul dérivait ce volume de l'échantillon gelé — plafonné à
> 1 000 contrats sur 90 jours — et annonçait **77,8 par semaine**, soit cinq
> fois moins que la réalité. Une extrapolation depuis un plafond n'est pas une
> mesure prudente, c'est une mesure fausse. Le volume vient désormais d'un
> `COUNT` posé au portail ; en son absence, la fonction rend `None` et déclare
> `basis: "unavailable"` plutôt qu'un chiffre inventé. Deux tests l'imposent.

**La France passe donc de 45 à 428 événements exploitables par semaine** — un
facteur 9,5 — à condition d'accepter que 90 % d'entre eux parlent d'une
notification et non d'une décision.

### C. Quelle part porte de quoi désigner l'entreprise ?

```text
                        BOAMP (1 482)      DECP (1 000)
nommée                     91,1 %              0,0 %
identifiée (SIRET)         38,3 %             99,8 %
nommée OU identifiée       91,1 %             99,8 %
nommée ET identifiée       38,3 %              0,0 %
```

Les deux sources sont exploitables pour un signal client, mais pas de la même
façon : le BOAMP donne un nom à afficher, DECP un numéro à résoudre. **Aucune
des deux ne donne les deux à la fois**, et c'est précisément ce que le
rapprochement §5 permettrait de réparer — pour les 44 couples sur 121 où il
aboutit.

---

## 7. SPEC-009C FIXTURES / FRESH-CLONE TESTS

Solution retenue : **suivre les artefacts** (option 1). Elle est la plus simple
et la seule qui préserve le sens exact des tests — la preuve que le rejeu du
pipeline reproduit le banc gelé ne peut pas se dériver d'un extrait.

```text
tests/fixtures/signal100/spec009c_corpus.json    7,6 Mo
tests/fixtures/signal100/spec009c_bench.json     3,6 Mo
tests/fixtures/signal100/spec009c_gold.json      0,3 Mo
                                                ───────
                                                11,5 Mo   (≤ 12 Mo autorisés)
```

`spec009c_blind.json` (1,2 Mo) n'est **pas** inclus : aucun test suivi ne le lit.

Les quatre `@needs_spec009c` sont retirés, et un test les remplace :

```python
def test_every_frozen_spec009c_artefact_is_present_for_a_fresh_clone():
    """L'absence d'un artefact doit faire ÉCHOUER, jamais sauter."""
```

Un saut silencieux sur la seule preuve que le rejeu reproduit le banc n'est pas
un test, c'est une case verte.

**Aucun label gold ni résultat de benchmark n'est modifié.** Les fichiers sont
gelés tels qu'ils étaient ; leurs SHA-256 sont ceux qu'enregistrait déjà
`spec009d_audit.json`.

Les trois fichiers sont **indexés (`git add`) et non committés**, conformément à
l'interdiction de committer. `git status --porcelain` les montre en `A `.

---

## 8. NON-REGRESSION MATRIX

```text
élément                                      état        vérification
RECENT_AWARD / AGING / STALE                 inchangés   31 tests, bornes 30/31/60/61 j
BOAMP eForms parser                          inchangé    21 tests, 0 modification
protection sentinelle BOAMP                  inchangée   2000-01-01 / 1970-01-01 toujours invalides
TED connu / inconnu                          inchangé    7 recent · 21 recently_published
award_date ≠ publication_date                inchangée   testée sur les 4 sources
Need Graph                                   need-graph-v0.2          intact
Matching                                     icp-match-v0.2           intact
Signal Score                                 signal-score-v0.2        intact
Contract Understanding                       contract-understanding-v0.3  intact
BKP                                          bkp-trade-v0.1           intact
règles de besoin                             need-rules-v0.5          intact
Document Intelligence auto-accept            AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False
Commercial Verifier                          OFF, non touché
golds historiques                            non modifiés
résultat commercial SPEC-009C (64 %)         non re-mesuré, non modifié
commit d'audit SPEC-009D (1cd8628)           intact
```

```bash
$ git status --porcelain src/signals/understanding src/signals/needs \
                         src/signals/matching src/signals/documents
(vide)
```

Aucun nouveau benchmark commercial n'a été lancé.

### BUG GOVERNANCE

Trois incidents, aucun n'altère une métrique historique.

```text
BUG 1     mauvaise source DECP — decp-v3 au lieu de decp-2022
IMPACT    toute la partie DECP de SPEC-009E : « 0 notification en 12 mois »,
          « rapprochement 0 % », place de la France dans la comparaison
CORRECTIF adapter réécrit sur le schéma courant, registre corrigé, rapport
          SPEC-009E marqué d'une bannière de correction
RÉGRESSION test_the_adapter_targets_the_current_dataset_not_the_legacy_one
           test_the_decp_entry_names_the_current_dataset_and_not_the_legacy_one

BUG 2     volume hebdomadaire §6.B extrapolé d'un échantillon plafonné
IMPACT    77,8/semaine annoncés contre 383 réels — jamais sorti de la machine,
          détecté avant rédaction
CORRECTIF le volume vient du recensement portail ; sans lui, `None` et
          `basis: "unavailable"`
RÉGRESSION test_the_weekly_notified_volume_comes_from_the_portal_census
           test_a_capped_sample_is_never_extrapolated_into_a_weekly_volume

BUG 3     commentaire du domaine nommant « SIMAP » et « DECP »
IMPACT    aucun — l'invariant existant a échoué immédiatement
CORRECTIF le commentaire décrit les actes, pas les sources
RÉGRESSION test_ajouter_un_portail_ne_touche_pas_contract_award (préexistant)
```

Deux tests dont la **prémisse** a été périmée par une décision explicite ont été
mis à jour, sans changer ce qu'ils vérifient :

```text
test_only_two_event_types_exist_in_the_mvp
  → renommé et étendu au troisième type, autorisé par R1 §3. Reste une liste
    fermée : un quatrième type non décidé fait toujours échouer la suite.

test_source_inconnue_refusee  (déjà signalé en SPEC-009E)
  → l'exemple de source inconnue était « boamp », devenu un connecteur réel.
```

---

## 9. TESTS / GATES

```bash
$ uv run pytest -q
1971 passed in 16.37s          # 1916 avant R1, + 55

$ uv run ruff check .
All checks passed!

$ git diff --check
(rien)

$ uv run ruff format --check .
1 file would be reformatted
  docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md
```

**Tests ignorés : zéro.** C'était l'objet de §7.

```bash
$ git status --porcelain
 M src/signals/domain/awards.py
 M src/signals/domain/events.py
 M tests/test_model_invariants.py
 M tests/test_spec009d_audit.py
A  tests/fixtures/signal100/spec009c_bench.json
A  tests/fixtures/signal100/spec009c_corpus.json
A  tests/fixtures/signal100/spec009c_gold.json
?? docs/reports/2026-08-18-spec009e-r1-current-decp.md
?? src/signals/connectors/boamp/  src/signals/connectors/decp/
?? src/signals/france/  src/signals/recency/
?? src/signals/research/spec009e.py  src/signals/research/spec009e_run.py
?? tests/fixtures/france/
?? tests/test_award_claim_copy.py  tests/test_award_recency.py
?? tests/test_boamp_adapter.py  tests/test_boamp_client_cursor.py
?? tests/test_contract_notification_date.py  tests/test_decp2022_adapter.py
?? tests/test_france_decp_link.py  tests/test_source_date_semantics.py
?? tests/test_spec009e_france_study.py
   (+ artefacts SPEC-009C antérieurs, hors périmètre)

$ git diff --stat
 src/signals/domain/awards.py   | 21 +++++++++++++++++--
 src/signals/domain/events.py   | 10 ++++++++--
 tests/test_model_invariants.py |  5 ++++-
 tests/test_spec009d_audit.py   | 27 +++++++++++++-----------
 4 files changed, 48 insertions(+), 15 deletions(-)
```

### Fichiers modifiés par R1

```text
DOMAINE PARTAGÉ  ⚠
  src/signals/domain/awards.py       + contract_notification_date, commentaire des 4 horloges

RÉÉCRITS
  src/signals/connectors/decp/parser.py   schéma 2022, filtre CDL, sémantique des dates
  tests/test_france_decp_link.py          refait sur le jeu courant

ÉTENDUS
  src/signals/recency/policy.py      v0.2, recently_notified_contract
  src/signals/recency/claim.py       phrase et type d'événement « notifié »
  src/signals/recency/sources.py     entrée DECP corrigée, notification_date_field
  src/signals/france/link.py         v0.2, priorité remesurée, date de notification
  src/signals/research/spec009e.py   mesure de notification, identité client
  src/signals/research/spec009e_run.py acquisition DECP, recensement, timing §6
  tests/test_award_recency.py        +11
  tests/test_award_claim_copy.py     +8
  tests/test_source_date_semantics.py +4
  tests/test_spec009e_france_study.py +8
  tests/test_spec009d_audit.py       skips retirés, garde de présence

NOUVEAUX
  tests/test_decp2022_adapter.py             21 tests
  tests/test_contract_notification_date.py    3 tests
  tests/fixtures/france/decp2022_records.json        4 contrats réels
  tests/fixtures/france/boamp_decp2022_link.json     3 avis + 11 contrats réels
  tests/fixtures/france/spec009e_decp2022_raw.json   1 000 contrats gelés
  docs/reports/2026-08-18-spec009e-r1-current-decp.md
```

### SHA-256 des artefacts R1

```text
spec009e_decp2022_raw.json   1,99 Mo
  10f63777d09936f36cefd5a184463185b7e82e0fe2c4da832cc1c65395ba5d40
spec009e_boamp_raw.json     13,86 Mo
  10409f6f63b5960454d0cb9eec65d73aefddfca1aa6c744626f29f8fa659f6a5
spec009e_france.json         0,86 Mo
  e0a398043f7a0c628d2e533d7cd867847bb44945d2cbff12aca7e5216abc821f
decp2022_records.json        0,01 Mo
  b82c620d6bc298a63dd638b460a68daf2dcc60a36ee2d07d9d97beee916b237b
boamp_decp2022_link.json     0,11 Mo
  4d079ed2647cc799c705d7dd6c4225e883361f9c60a223eda20caed9e60b540a
```

Le gel brut BOAMP de 13,9 Mo reste un artefact de travail régénérable : la
mesure dérivée (0,86 Mo) suffit à rejouer toute l'analyse.

### Répartition des 55 nouveaux tests

```text
§2 date de notification au domaine          3
§1 adapter DECP courant                    21
§3 politique de fraîcheur étendue          11
§3 formulation « notifié »                  8
§1 registre des sources corrigé             4
§4 §6 mesure et volumes                     8
§7 présence des artefacts gelés             1
§5 liaison refaite (net, 22 → 21)          −1
```

---

## VERDICT

```text
RECENT AWARD FOUNDATION READY AFTER R1
```

Preuves, condition par condition :

```text
source DECP courante et documentée      ✔ decp-2022-marches-valides, 55 champs relus,
                                          différences de schéma listées, « CDL » neutralisé
dateNotification jamais award_date      ✔ testé sur 4 + 11 enregistrements réels ;
                                          jamais contract_signature_date non plus
RECENT_AWARD non affaibli               ✔ une notification fraîche ne rattrape pas une
                                          décision de 90 jours (test dédié)
séparation des formulations             ✔ 7 états × 2 langues contre 6 marqueurs
DECP re-mesuré sur données réelles      ✔ 1 000 contrats gelés + recensement portail :
                                          383 / 6 661 / 18 552 / 31 665
liaison refaite sur périodes couvrantes ✔ 44 couples sur 121 ; 1 exact, 1 conflit
                                          documenté, 9 leurres rejetés
faits + Evidence préservés              ✔ aucune fusion destructive ; les deux valeurs
                                          et leurs sources survivent au conflit
tests exécutables sur clone frais       ✔ 11,5 Mo indexés, 0 test ignoré
zéro régression factuelle               ✔ moteurs intacts, 48 lignes de diff suivi
tests verts                             ✔ 1 971 passed, ruff clean
```

Ce que le verdict ne dit pas, et qui compte pour la décision produit : **la
France change de nature avec cette correction.** Elle passe de 45 à 428
événements exploitables par semaine, mais 90 % de ce volume parle d'une
*notification de contrat* et non d'une *décision d'attribution*, et n'apporte
aucun nom d'entreprise — seulement un SIRET. C'est une bien meilleure position
que celle décrite par SPEC-009E, et ce n'est pas la même promesse.

---

**Rien n'est committé.** Aucune suite n'est engagée : ni SPEC-010, ni base de
données, ni auth, ni frontend, ni déploiement, ni Acquisition Engine. En attente
de la revue superviseur.
