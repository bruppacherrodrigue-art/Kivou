# SPEC-009E — Recent Award Signal Policy + France Ingestion

> ## ⚠ CORRIGÉ PAR R1 — NE PAS CITER LA PARTIE DECP DE CE RAPPORT
>
> La revue superviseur a établi que l'étude DECP de ce rapport a été menée sur
> `decp-v3-marches-valides`, le jeu **hérité** de l'arrêté du 22 mars 2019, figé
> à une notification du 2024-02-08. Le jeu **courant** est
> `decp-2022-marches-valides` : 689 062 marchés, mis à jour quotidiennement,
> 383 contrats notifiés dans les sept derniers jours.
>
> **Toute conclusion de ce rapport reposant sur « DECP s'arrête en février
> 2024 » est fausse** — notamment la section DECP ADAPTER / ENRICHMENT, le taux
> de rapprochement de 0 % et la place de la France dans la comparaison des
> sources.
>
> Les parties BOAMP, la politique de fraîcheur, la sûreté de formulation et le
> piège `cac:TenderResult/cbc:AwardDate` restent valides.
>
> Voir `2026-08-18-spec009e-r1-current-decp.md`, puis
> `2026-08-18-spec009e-r2-multiclock-unique-signals.md` — ce dernier fait foi.

---

## SPEC-009D COMMIT

Portes passées avant commit :

```text
uv run pytest -q        1771 passed
uv run ruff check .     All checks passed!
git diff --check        (rien)
git diff --stat         (rien — tout était non suivi)
```

Commit unique créé, non poussé :

```text
1cd8628  research(recency): audit award timing and purchase-channel observability

 docs/reports/2026-08-18-spec009d-recency-channel-audit.md   759 +
 src/signals/research/spec009d.py                           1116 +
 src/signals/research/spec009d_run.py                        470 +
 tests/fixtures/signal100/spec009d_audit.json               1552 +
 tests/test_spec009d_audit.py                                445 +
 5 files changed, 4342 insertions(+)

tracked working tree clean ✔
```

Une décision a dû être prise en chemin. Les artefacts gelés de SPEC-009C —
corpus, banc, gold — sont eux aussi **non suivis par git**, et §52 n'autorisait
que le commit SPEC-009D. Committer des tests qui relisent des fichiers absents
du dépôt aurait cassé la suite sur un clone frais. Les trois tests concernés
sont donc conditionnés à la présence des artefacts (`@needs_spec009c`), avec un
motif explicite plutôt qu'un succès silencieux. La question reste ouverte plus
bas.

---

## FILES CHANGED

```text
NOUVEAUX — politique de fraîcheur
  src/signals/recency/__init__.py
  src/signals/recency/policy.py            statuts, seuils versionnés, dates dérivées
  src/signals/recency/claim.py             phrases FR/EN autorisées, types d'événement MVP
  src/signals/recency/sources.py           sémantique des dates, source par source

NOUVEAUX — France
  src/signals/connectors/boamp/__init__.py
  src/signals/connectors/boamp/parser.py   avis BOAMP → PublicEvent + ContractAward
  src/signals/connectors/boamp/client.py   lecture Opendatasoft, curseur par date
  src/signals/connectors/decp/__init__.py
  src/signals/connectors/decp/parser.py    contrat DECP → PublicEvent + ContractAward
  src/signals/france/__init__.py
  src/signals/france/link.py               résolution BOAMP↔DECP et fusion

NOUVEAUX — recherche
  src/signals/research/spec009e.py         instrument de mesure, pur et hors ligne
  src/signals/research/spec009e_run.py     acquisition puis mesure, séparées

NOUVEAUX — tests (145)
  tests/test_award_recency.py              20
  tests/test_award_claim_copy.py           40
  tests/test_boamp_adapter.py              21
  tests/test_boamp_client_cursor.py        10
  tests/test_france_decp_link.py           22
  tests/test_source_date_semantics.py      20
  tests/test_spec009e_france_study.py      12

NOUVEAUX — fixtures
  tests/fixtures/france/boamp_records.json      4 avis BOAMP réels, non modifiés
  tests/fixtures/france/decp_records.json       6 contrats DECP réels + leur avis BOAMP
  tests/fixtures/france/spec009e_france.json    la mesure France complète
  tests/fixtures/france/spec009e_boamp_raw.json le gel brut (14,5 Mo — voir §VPS)

MODIFIÉS (2 fichiers, 12 lignes)
  src/signals/domain/events.py    SourceSystem += "boamp", "decp"
  tests/test_model_invariants.py  cf. BUG GOVERNANCE
```

Aucun moteur n'est modifié : `understanding`, `needs`, `matching`, `documents`
sont intacts (vérifié par `git status --porcelain`).

---

## NEW MVP SIGNAL DOCTRINE

La doctrine du superviseur est appliquée telle quelle. Kivou ne promet plus
d'inférence commerciale juste ; il promet un **événement daté, vrai, et
qualifié pour ce qu'il est**.

```text
Cette entreprise vient de remporter ce marché.      ← affirmé seulement si daté et récent
Voici ce que nous savons de ce contrat.             ← chaque fait porte sa preuve
Voici les besoins commerciaux plausibles.           ← inchangé, jamais « demande confirmée »
Voici pourquoi cela peut vous intéresser.
```

§29 demandait de ne créer un modèle que si les structures existantes ne
suffisaient pas. Elles suffisaient, à une pièce près :

```text
event_type            ← dérivé du statut de fraîcheur (mvp_event_type)
event_date            ← ContractAward.award_date          existait
event_date_status     ← AwardRecency.status               MANQUAIT → ajouté
publication_date      ← PublicEvent.published_at          existait
discovered_at         ← Provenance.retrieved_at           existait (§14)
recency_status        ← AwardRecency.status               MANQUAIT → ajouté
winner                ← ContractAward.awardee_parties     existait
award                 ← ContractAward                     existait
potential_needs       ← NeedGraphResult                   existait, non touché (§32)
ICP match             ← ScoredSignalMatch                 existait, non touché
confidence / proof    ← Evidence, evidence_coverage       existait
```

**Aucun `KivouSignalEvent` n'a donc été créé.** Ce qui manquait n'était pas une
enveloppe, c'était une politique : la réponse à « que dit-on de cette date ? ».

### §34 — niveaux de qualité (doctrine, pas algorithme)

Documentés, **non implémentés** — §34 l'interdit explicitement.

```text
HIGH VALUE    recent_award  + bon fit ICP + besoin plausible
MEDIUM VALUE  recent_award  + fit partiel / besoin plus faible
DISCOVERY     recently_published_award — date d'attribution inconnue
```

Aucun nouveau score n'existe. `signal-score-v0.2` est inchangé.

---

## RECENCY MODEL

`signals/recency/policy.py`, version `award-recency-v0.1`.

Trois horloges, jamais interchangeables (§6) :

```text
award_date        quand l'entreprise a réellement obtenu le marché
publication_date  quand l'avis est devenu public
discovered_at     quand Kivou l'a appris   (Provenance.retrieved_at)
```

Six états :

```text
recent_award                award datée, valide, ≤ 30 jours
aging_award                 31 à 60 jours
stale_award                 > 60 jours
recently_published_award    award inconnue, avis paru ≤ 30 jours
award_date_unknown          award inconnue, avis ancien ou absent
invalid_award_date          date incohérente — diagnostic, jamais correction
```

Cinq métriques dérivées, calculées seulement quand les deux dates existent (§15) :

```text
award_age_days · publication_age_days · publication_delay_days
discovery_delay_from_publication · discovery_delay_from_award
```

L'ordre d'évaluation n'est pas cosmétique : **la validité passe avant l'âge**.
Une date future ou aberrante n'est pas une attribution récente, c'est une
source cassée.

`assess_recency` ne reçoit aucune date de signature. Ce n'est pas un oubli :
lui en passer une lève `TypeError`, et un test le vérifie. §7 interdit la
substitution silencieuse, et la meilleure façon de l'interdire est de rendre le
geste impossible.

---

## RECENT AWARD POLICY

```text
RECENT_AWARD_DAYS          = 30      §9, paramètre versionné
AGING_AWARD_DAYS           = 60      §10
RECENT_PUBLICATION_DAYS    = 30      §12
PUBLICATION_TOLERANCE_DAYS = 1       §13
IMPLAUSIBLE_AWARD_AGE_DAYS = 3650    §13
```

Le seuil est un argument nommé de `assess_recency`, pas une constante enfouie :
un test le fait varier à 60 jours et vérifie que le statut change, sans toucher
au moteur.

### Les gardes de plausibilité, mesurées sur du réel

Trois règles, et chacune répond à un cas observé, pas à une hypothèse :

```text
award_date > as_of                      → invalid   date future
award_age > 3650 j                      → invalid   SIMAP « 2002-08-17 » (SPEC-009D)
                                                    BOAMP « 2000-01-01 » / « 1970-01-01 »
award_date > publication_date + 1 j     → invalid   attribution postérieure à sa parution
```

Le cas SIMAP de SPEC-009D est un test de régression nommé
(`test_the_simap_two_thousand_two_case_is_flagged_invalid`). Rejoué sur le banc
des 110 SHOW, il est désormais **le seul** signal suisse marqué
`invalid_award_date` — la garde attrape exactement ce qu'elle devait attraper,
et rien d'autre.

Aucune date n'est corrigée : `invalid_award_date` conserve la valeur brute et sa
provenance.

---

## COPY / CLAIM SAFETY

C'est la section la plus courte et la plus importante. Toute la valeur du MVP
tient dans une distinction d'une ligne, et c'est le seul mensonge que le produit
puisse commettre à grande échelle.

```text
RECENT_AWARD                fr  « {société} vient de remporter un marché public. »
                            en  « {société} has recently won a public contract. »

RECENTLY_PUBLISHED_AWARD    fr  « Une attribution concernant {société} vient d'être publiée. »
                            en  « An award notice concerning {société} has recently been
                                  published. »
```

Trois choix de conception rendent la confusion difficile plutôt qu'interdite sur
le papier :

1. **La phrase découle du statut, jamais des dates.** `claim_for()` lit
   `recency.status` et rien d'autre. Une règle de date écrite dans le texte
   finirait par diverger de la politique qui l'a produite.
2. **Aucune date n'apparaît dans le gabarit.** C'est ce qui rend impossible
   d'afficher une valeur que `invalid_award_date` vient de disqualifier — un
   test vérifie que « 2002 » ne peut pas sortir du cas SIMAP.
3. **L'interdiction est testée sur les six états × deux langues**, contre une
   liste de marqueurs (`vient de remporter`, `has recently won`, `a remporté`…).
   Ajouter un septième état sans phrase fait échouer la suite.

`aging_award` et `stale_award` ont bien une phrase — exacte, datée, mais qui ne
revendique aucune victoire récente — et **aucun type d'événement MVP** : ils
n'entrent pas dans « nouvelles opportunités » (§11).

---

## SOURCE DATE SEMANTICS

Registre exécutable : `signals/recency/sources.py`, version
`source-date-semantics-v0.1`. Chaque source déclare ce qu'elle publie, sur quel
champ, et sur quel échantillon la couverture a été mesurée. Un test interdit à
toute source de déclarer qu'un champ ambigu porte une date d'attribution.

### SIMAP

```text
award_date_status          published
champ                      publication.award_decision_date
sémantique                 date de la décision d'adjudication publiée dans l'avis
couverture mesurée         100,0 %   (76 SHOW naturels, SPEC-009D)
autres dates               aucune
```

Meilleur cas de référence pour un signal « vient de remporter ». Extraction
existante conservée sans modification (§17).

### TED

```text
award_date_status          sometimes_published
champ                      efac:SettledContract/cbc:AwardDate   (BT-1451)
couverture mesurée          38,2 %   (34 SHOW naturels, 13 datés)
autre date                 efac:SettledContract/cbc:IssueDate   (BT-145, conclusion)
                           → contract_signature_date, AMBIGUOUS pour award_date
```

Une date absente ne rétrograde que l'avis concerné (§18) : les avis TED datés
restent éligibles à `recent_award`, les autres deviennent
`recently_published_award`.

### BOAMP

```text
award_date_status          sometimes_published
champ                      efac:SettledContract/cbc:AwardDate   (BT-1451 — même norme que TED)
couverture mesurée          29,2 %   (1 482 award-lots, 529 avis eForms, parution 2026-08-11→18)
autre date                 efac:SettledContract/cbc:IssueDate   (BT-145) → signature, AMBIGUOUS
PIÈGE                      cac:TenderResult/cbc:AwardDate       → JAMAIS mappé
```

### DECP

```text
award_date_status          not_published
champ                      aucun
couverture mesurée           0,0 %
dateNotification           → contract_signature_date, AMBIGUOUS
datePublicationDonnees     → PublicEvent.published_at, NO
```

---

## FRANCE SOURCE FIELD STUDY

### Le champ piège — la découverte principale de cette SPEC

BOAMP expose `cac:TenderResult/cbc:AwardDate`. Le nom est exactement celui du
champ recherché. Il est présent sur **100 % des avis eForms**. Ses valeurs :

```text
2000-01-01     297 avis
1970-01-01      19 avis
dates réelles   13 avis
               ────
                329 avis mesurés  →  96,0 % de remplissage sentinelle
```

Mapper ce champ sur son nom aurait produit des signaux « vient de remporter »
datés de l'an 2000, sur la quasi-totalité du feed français. C'est le cas d'école
que §20 anticipait, et il n'était pas théorique.

Le champ est nommé dans le registre, avec sa raison, et un test de l'adapter
vérifie sur un avis réel que la sentinelle est bien présente **et** bien ignorée.

### Trois formes coexistent dans le flux BOAMP

Mesuré sur 666 avis d'attribution parus du 2026-08-11 au 2026-08-18 :

```text
EFORMS      529   79,4 %   adapté
FNSimple    121   18,2 %   écarté
MAPA         16    2,4 %   écarté
```

Les 20,6 % écartés ne sont pas un défaut d'ingestion. `FNSimple` enferme
gagnant, SIRET, montant et date de notification dans **une seule phrase
libre** :

```text
« Lot 1 : Travaux de réhabilitation … - GRAGLIA BTP (43293695300012)
  Notifié le 05/06/2026 Montant : 213400.41 euros »
```

En extraire des faits serait de l'inférence sur du texte, pas de l'adaptation —
et un fait inféré n'a pas de provenance opposable. Ils sont comptés et écartés,
jamais devinés. `payload_form_counts()` les compte pour que le taux de
couverture ne mente pas sur son dénominateur.

### Sémantique des dates, champ par champ

```text
source  champ                              sémantique officielle          award_date ?
BOAMP   efac:SettledContract/cbc:AwardDate BT-1451 décision d'attribution  OUI
BOAMP   efac:SettledContract/cbc:IssueDate BT-145 conclusion du contrat    AMBIGU → signature
BOAMP   cac:TenderResult/cbc:AwardDate     champ UBL homonyme, non rempli  NON (sentinelle)
BOAMP   dateparution                       parution de l'avis              NON → publication
DECP    dateNotification                   « Date de notification »        AMBIGU → signature
DECP    datePublicationDonnees             publication de la donnée ouverte NON → publication
DECP    dateNotificationModification       notification d'un avenant       NON (non mappé)
```

`dateNotification` mérite un mot. Le portail ne la documente que par « Date de
notification ». La notification **forme** le contrat ; rien dans le schéma ne
dit qu'elle date la décision qui l'a précédée. §20 tranche : elle alimente
`contract_signature_date`, jamais `award_date`. C'est le choix conservateur, et
il coûte cher — il prive la France d'une date sur 90,8 % de ses award-lots.
Il est rouvert en question ouverte.

---

## BOAMP ADAPTER

`signals/connectors/boamp/parser.py`, version `boamp-adapter-v0.1`.

Aucun domaine France parallèle : la sortie est `PublicEvent` + `ContractAward`,
les modèles existants. `SourceSystem` gagne `"boamp"` et `"decp"` — c'est
l'unique modification du domaine, et elle est de la compatibilité d'adapter au
sens de §46.

Chaîne d'extraction du gagnant, telle que l'eForms la publie :

```text
efac:LotResult
  → efac:LotTender/cbc:ID        → efac:LotTender
  → efac:SettledContract/cbc:ID  → efac:SettledContract   (dates, titre, référence)
     efac:LotTender
       → efac:TenderingParty/cbc:ID → efac:TenderingParty
          → efac:Tenderer/cbc:ID    → efac:Organizations/efac:Organization/efac:Company
```

Aucun rapprochement par nom nulle part. Un contrat attribué = un `LotResult`.

Deux refus délibérés, tous deux testés sur des avis réels :

- **Les formes non-eForms lèvent** `BoampUnsupportedPayload` au lieu d'être
  interprétées.
- **Le plafond d'un accord-cadre n'est pas un montant attribué.** L'avis
  `26-80978` publie `efac:FrameworkAgreementValues/cbc:MaximumValueAmount` à
  160 000 et 280 000 EUR sans aucun `PayableAmount`. Le reprendre comme valeur
  du contrat afficherait au client une commande qui n'a pas eu lieu :
  `value` reste vide.

`CompanyID` est nommé pour ce qu'il est — `SIRET` quand la valeur fait quatorze
chiffres, le schéma déclaré sinon (`eu`). Chercher un SIRET dans un champ qui
n'en porte pas est précisément ce que la résolution d'identité ne doit pas faire.

---

## DECP ADAPTER / ENRICHMENT

`signals/connectors/decp/parser.py`, version `decp-adapter-v0.1`.

§22 laissait le choix entre enrichissement d'un parent BOAMP et contrat
autonome. Les identités disponibles tranchent : un enregistrement DECP porte son
propre identifiant de marché, ses parties et son montant. Il est donc **adapté
comme contrat canonique autonome**, sans parent forcé.

Ce que DECP apporte, et ce qu'il n'a pas — mesuré, pas supposé :

```text
apporte    SIRET acheteur, SIRET titulaire(s), montant, CPV, durée en mois,
           lieu d'exécution (commune + code postal), nature du contrat
n'a pas    `titulaire_denominationsociale_1` — le champ n'existe pas dans le jeu
           `acheteur_nom` — nul sur les enregistrements observés
```

C'est la complémentarité exactement inverse de BOAMP, qui **nomme** sans
toujours identifier : SIRET du gagnant sur 38,3 % de ses award-lots seulement.

Sans raison sociale publiée, le SIRET tient lieu de désignation. Fabriquer un
nom — même « Titulaire 44284979000013 » — donnerait l'illusion d'une identité
nommée ; un test vérifie que la désignation reste le SIRET brut.

### DECP ne peut pas dater une victoire récente

Sonde exécutée le 2026-08-18 contre `decp-v3-marches-valides` :

```text
total du jeu                          702 901
notifiés dans les 30 derniers jours         0
notifiés dans les 90 derniers jours         0
notifiés dans les 365 derniers jours        0
notification la plus récente        2024-02-08
```

Deux ans et demi de retard. Le jeu `decp_augmente` (994 123 lignes) atteint
2026-05-11 mais ne compte qu'une vingtaine de notifications réelles sur douze
mois.

**DECP est une source d'enrichissement rétrospective, jamais un déclencheur de
signal.** La doctrine de §3 est confirmée par la mesure.

---

## FRANCE IDENTITY RESOLUTION

`signals/france/link.py`, version `france-link-v0.1`.

La tentation évidente est de joindre BOAMP et DECP sur ce qu'ils ont en commun :
le SIRET de l'acheteur et celui du titulaire. **Les données interdisent ce
raccourci**, et c'est le second résultat important de cette SPEC.

Sur 61 couples (acheteur, titulaire) tirés d'avis BOAMP réels, 14 ont trouvé au
moins un enregistrement DECP. Presque tous étaient **le mauvais contrat** :

```text
BOAMP 24-37533   ville de Paris × titulaire   attribution du 2024-01-23
  DECP trouvé    même couple                  notifié 2019-07-23, abris de jardin
  DECP trouvé    même couple                  notifié 2021-08-24, rondins et tuteurs
```

Un couple de parties n'identifie pas un contrat : il identifie une **relation
commerciale**, qui dure des années. C'est la date qui tranche.

```text
strong       même acheteur + même titulaire + notification DECP à ≤ 7 jours
             de la conclusion BT-145 publiée par BOAMP
probable     même acheteur + même titulaire + accord de CPV ou de montant,
             sans accord de date
unresolved   tout le reste — y compris le couple de parties seul
```

Un `probable` ne fusionne rien : il est rendu comme candidat, et l'appelant
décide (§23). L'ordre de sortie est déterministe — force décroissante puis
identifiant DECP — ce que le futur polling exige.

### Vérifié sur un vrai couple

L'avis BOAMP `24-37607` (Ville de Nice, voirie, quatre lots) et six
enregistrements DECP de la même ville avec les mêmes titulaires :

```text
LOT-0001 VRD            sign. 2023-12-22  →  DECP 202323V0975-0101  notif. 2023-12-22  STRONG
LOT-0002 ESPACES VERTS  sign. 2023-12-22  →  DECP 202323V0975-0200  notif. 2023-12-22  STRONG
LOT-0004 ÉCLAIRAGE      sign. 2024-03-14  →  aucun candidat                        UNRESOLVED

leurres — même acheteur, même titulaire, contrats sans rapport
  202323V0379-0002  notif. 2023-10-19  promenade du Paillon   UNRESOLVED
  202019V1502-0101  notif. 2020-06-04  réseaux d'arrosage     UNRESOLVED
  202019V1502-0102  notif. 2020-06-04  réseaux d'arrosage     UNRESOLVED
  202322V1147-0300  notif. 2023-05-23  fourniture de végétaux UNRESOLVED
```

Quatre leurres, zéro fusion abusive. Chacun est un test paramétré.

### Taux de rapprochement sur données fraîches

```text
0 %
```

Ce n'est pas un défaut de la résolution : aucun avis BOAMP de la fenêtre récente
ne **peut** avoir de contrepartie DECP, puisque DECP s'arrête en février 2024.
La mécanique fonctionne et se démontre sur la fenêtre d'où DECP a des données ;
elle est inopérante là où le produit vit.

---

## BOAMP × DECP MERGE

Table de priorité explicite (`FIELD_PRIORITY`), chaque ligne justifiée par une
mesure et non par une commodité d'implémentation :

```text
champ                     préférée   repli    conflit       raison
winner_siret              DECP       BOAMP    diagnostic    DECP 100 % vs BOAMP 38,3 %
winner_legal_name         BOAMP      DECP     silencieux    DECP ne publie pas le nom
buyer_siret               DECP       BOAMP    diagnostic    BOAMP 53,8 %
publication_date          BOAMP      DECP     silencieux    DECP date la donnée ouverte
award_date                BOAMP      BOAMP    silencieux    DECP n'en a aucune (§20)
contract_signature_date   BOAMP      DECP     diagnostic    BT-145 explicite vs notification
amount                    BOAMP      DECP     diagnostic    offre retenue vs total du contrat
cpv                       BOAMP      DECP     diagnostic    classements divergents
place_of_performance      DECP       BOAMP    silencieux    commune + CP vs NUTS seul
duration_months           DECP       BOAMP    silencieux    absent des eForms BOAMP
```

**La fusion n'écrase rien.** Le contrat canonique ressort inchangé ; DECP ajoute
des faits à côté et les divergences deviennent des diagnostics. Une valeur
remplacée est une preuve perdue, ce que §25 interdit.

Le conflit du lot VRD est le cas parfait, et il n'est la faute de personne :

```text
amount    BOAMP 15 763 785 EUR      valeur de l'offre retenue
          DECP  20 200 000 EUR      total de l'accord-cadre sur 48 mois
          → diagnostic ; la valeur BOAMP reste en place, les deux sont conservées

cpv       BOAMP 45233228            DECP 45220000
          → diagnostic ; l'écart de classement est un fait, pas une erreur
```

`nature = "Accord-cadre"` dans l'enregistrement DECP explique l'écart. Aucune
des deux valeurs n'est fausse ; elles mesurent des choses différentes.

---

## FRANCE SAMPLE

```text
fenêtre                  parution 2026-08-11 → 2026-08-18 (7 jours)
avis d'attribution       666
dont eForms              529   (79,4 %)
award-lots canoniques  1 482
échecs de parsing          0
verdict §27              target reached   (cible 100, minimum 50)
```

Gel reproductible : `spec009e_boamp_raw.json` (SHA-256 enregistré dans la
mesure). `measure()` ne touche pas le réseau — l'analyse est rejouable hors
ligne.

---

## FRANCE FACT COVERAGE

Sur les 1 482 award-lots, dénominateur constant :

```text
cpv                       1482/1482   100,0 %
lot                       1482/1482   100,0 %
procedure_id              1482/1482   100,0 %
publication_date          1482/1482   100,0 %
buyer_name                1482/1482   100,0 %
winner_name               1350/1482    91,1 %
contract_id               1350/1482    91,1 %
contract_signature_date   1345/1482    90,8 %
amount / currency         1071/1482    72,3 %
place_of_performance       913/1482    61,6 %
buyer_siret                798/1482    53,8 %
winner_siret               567/1482    38,3 %
award_date                 433/1482    29,2 %
```

Lecture produit : la France identifie très bien **le marché** (CPV, lot,
procédure, acheteur à 100 %), correctement **le gagnant** (nom à 91 %), mal son
**identité stable** (SIRET à 38 %) et rarement **la date de la décision** (29 %).

---

## FRANCE AWARD-DATE COVERAGE

```text
award_date publiée (BT-1451)     433 / 1 482    29,2 %
award_date absente             1 049 / 1 482    70,8 %
```

Statuts de fraîcheur au 2026-08-18 :

```text
recently_published_award   1 049   70,8 %   ← aucune date de décision
stale_award                  235   15,9 %
aging_award                  153   10,3 %
recent_award                  45    3,0 %   ← seuls autorisés à dire « vient de remporter »
invalid_award_date             0    0,0 %
award_date_unknown             0    0,0 %
```

Âge d'attribution, sur les 433 datés :

```text
p25 42 j · médiane 63 j · p75 110 j · p90 491 j · max 491 j
```

**3,0 % du feed français peut porter la promesse « vient de remporter ».**
C'est une caractéristique produit, pas un échec de gate — §26 le disait
explicitement.

Ces 45 signaux ne sont pas théoriques :

```text
26-79753  SOPRA STERIA GROUP     9 600 000 EUR   attribué J-7   paru 2026-08-12
26-79727  DUPONT RESTAURATION    2 600 000 EUR   attribué J-19  paru 2026-08-12
26-79751  ROCK SAS                 800 000 EUR   attribué J-25  paru 2026-08-12
26-79804  UTPM ENVIRONNEMENT       336 000 EUR   attribué J-27  paru 2026-08-13
26-79745  DEMCY                    285 560 EUR   attribué J-12  paru 2026-08-12
```

Sur les 45, **39 portent le SIRET du gagnant** et **20 portent simultanément
gagnant nommé, montant et acheteur** — c'est-à-dire tout ce qu'une fiche client
affiche.

---

## FRANCE PUBLICATION DELAY

Sur les 433 award-lots datés :

```text
p25 40 j · médiane 58 j · p75 108 j · p90 485 j · max 485 j
```

L'âge de **publication**, lui, est excellent : médiane 3 jours sur la fenêtre.
Le feed français est frais ; l'**événement** qu'il décrit ne l'est pas.

C'est le cœur du problème français : la France publie ses attributions environ
deux mois après la décision.

---

## SWITZERLAND RECENCY SUMMARY

Recalculé en rejouant les 110 SHOW naturels de SPEC-009D à travers la nouvelle
politique — 76 award-lots SIMAP :

```text
recent_award          49   64,5 %
aging_award           19   25,0 %
stale_award            7    9,2 %
invalid_award_date     1    1,3 %   ← le cas « 2002-08-17 », désormais attrapé

award_date exploitable        98,7 %
délai de publication   p25 2 j · médiane 5 j · p75 26 j · p90 44 j · max 88 j
```

SIMAP est le meilleur cas de référence, et de loin. Deux signaux suisses sur
trois peuvent légitimement dire « vient de remporter ».

---

## TED RECENCY SUMMARY

34 award-lots TED du même banc :

```text
recently_published_award   21   61,8 %   ← BT-1451 absent
recent_award                7   20,6 %
aging_award                 3    8,8 %
stale_award                 3    8,8 %

award_date exploitable            38,2 %
délai de publication   p25 26 j · médiane 27 j · p75 49 j · p90 98 j · max 98 j
```

Conforme à §18 : les avis datés restent éligibles, les autres deviennent des
découvertes. Aucune rétrogradation globale, aucune date fabriquée.

---

## THREE-SOURCE COMPARISON

```text
source        award-lots   award_date    recent_award   délai médian
                            exploitable                  de publication
SIMAP  (CH)           76        98,7 %         64,5 %            5 j
TED    (UE)           34        38,2 %         20,6 %           27 j
BOAMP  (FR)        1 482        29,2 %          3,0 %           58 j
```

Trois régimes, un seul modèle canonique. C'est exactement ce que §16 demandait :
même politique partout, différences visibles.

Lecture produit :

- **La Suisse porte la promesse**, seule et confortablement.
- **La France apporte le volume** — 1 482 award-lots en sept jours contre 110 en
  quatre mois pour le banc CH+UE — et 45 signaux vraiment récents par semaine,
  ce qui suffit largement à alimenter un test client.
- **L'Union est intermédiaire** sur les deux axes.

Le feed mixte de §35 est donc réalisable, à condition que la promesse soit
portée par le **statut** et non par la source. C'est précisément ce que la
politique de formulation garantit.

---

## MVP COMMERCIAL GATES

### TRUTH GATES

```text
erreurs factuelles critiques        0     aucune substitution possible ; 145 tests
tout fait affiché porte Evidence    ✔     493 award-lots FR passés dans
                                          Contract Understanding : 0 échec,
                                          evidence_coverage = 1,0 partout,
                                          0 fait sans preuve
dates source brutes préservées      ✔     invalid_award_date conserve la valeur
aucune substitution publication→award ✔   testé sur les 4 sources
```

### TIMING GATES

```text
RECENT_AWARD ⟺ award_date connue et ≤ 30 j     ✔ testé (5 j, 30 j, 31 j, 61 j)
stale jamais étiqueté RECENT_AWARD             ✔ testé
award inconnue jamais « just won »             ✔ testé sur 6 états × 2 langues
```

### DOCTRINE COMMERCIALE MVP

Aucun gate de précision commerciale à 90–95 % n'est réintroduit, conformément à
§1 et §33. La doctrine du projet est désormais :

```text
≥ 50 % de signaux commercialement utiles  →  base vendable pour validation MVP
≥ 10 signaux récents utiles               →  suffisant pour tester avec de vrais clients
```

État mesuré :

```text
signaux récents disponibles par semaine
  France     45   (dont 20 avec gagnant + montant + acheteur nommés)
  Suisse     49   (sur le banc SPEC-009D)
                                                    →  seuil de 10 largement franchi

précision commerciale utile
  non re-mesurée dans SPEC-009E — le Need Graph et le Matching sont
  inchangés (§32, §46). La dernière mesure reste celle de SPEC-009C :
  64,0 % sur le wedge intrants de chantier, au-dessus du seuil de 50 %.
```

Cette précision-là a été mesurée sur **un ICP** et **un pays**. Elle ne se
transpose pas telle quelle au feed français ; elle indique seulement que le
seuil de 50 % n'est pas hors d'atteinte.

---

## POLLING READINESS

Aucun daemon n'est construit (§38). Ce qui est prêt :

```text
AwardCursor(since=…, until=…, offset=…)
  → reprise sur `dateparution`, jamais sur un décalage : un offset se périme
    dès qu'un avis s'insère dans la fenêtre, une date non

order_by = "dateparution asc, idweb asc"
  → ordre total : deux pages consécutives ne peuvent ni se recouvrir ni sauter

client.fetch_awards_since(since, until=…, max_records=…)
  → générateur : un futur polling s'arrête quand il veut, sans charger le
    catalogue en mémoire
```

Idempotence (§37), testée :

```text
même enregistrement → même identité canonique      (natural_key, source_identity)
même curseur        → même requête                 (aucune horloge, aucun aléa)
même paire          → même fusion, mêmes conflits
aucun UUID aléatoire nulle part
```

Un écueil rencontré mérite d'être noté, parce qu'il aurait pu passer pour un
résultat : le curseur ascendant, appliqué à une fenêtre de 90 jours plafonnée à
400 avis, échantillonne le **début** de la fenêtre. La première mesure a ainsi
rendu 0 % de `recent_award` — non parce que la France n'en produit pas, mais
parce que l'échantillon datait de mai. La fenêtre a été resserrée à sept jours
pour que l'échantillon soit celui qu'un feed vivant verrait.

---

## VPS PORTABILITY

```text
hors ligne          `measure()` et tous les tests ne touchent pas le réseau ;
                    seul `acquire()` sort, et il gèle son résultat
Python seul         httpx + pydantic, déjà présents ; aucune dépendance ajoutée
pas de DB           entrées et sorties en JSON (§40)
chemins relatifs    résolus depuis le module, aucune dépendance à un $HOME
mémoire bornée      `fetch_awards_since` est un générateur ; mesure ≈ 0,3 s
                    sur 1 482 award-lots
compatible Linux    aucune primitive spécifique à une plateforme
```

Une réserve honnête sur le disque : `spec009e_boamp_raw.json` pèse **14,5 Mo**
pour sept jours d'avis français. C'est un artefact de travail régénérable, pas
une fixture destinée au dépôt — la mesure dérivée (838 Ko) suffit à rejouer
toute l'analyse. À conserver hors de git, ou à trimmer si le superviseur veut le
figer.

---

## NON-REGRESSION

```text
SPEC-006 auto document requirements    AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False   ✔
Contract Understanding                 contract-understanding-v0.3    inchangé      ✔
Need Graph                             need-graph-v0.2                inchangé      ✔
règles de besoin                       need-rules-v0.5                inchangé      ✔
Matching                               icp-match-v0.2                 inchangé      ✔
Signal Score                           signal-score-v0.2              inchangé      ✔
BKP                                    bkp-trade-v0.1                 inchangé      ✔
corpora historiques SPEC-009           non touchés                                  ✔
audit SPEC-009D                        non touché (commit 1cd8628)                  ✔
```

Diff total sur le code suivi : **2 fichiers, 12 lignes**.

```bash
$ git status --porcelain src/signals/understanding src/signals/needs \
                         src/signals/matching src/signals/documents
(vide)
```

### BUG GOVERNANCE (§47)

Un seul incident, et ce n'est pas une régression de mesure.

```text
BUG                     tests/test_model_invariants.py::test_source_inconnue_refusee
                        échouait après l'extension de SourceSystem
IMPACT                  aucun sur une métrique ; le test utilisait la chaîne
                        « boamp » comme EXEMPLE de source inconnue, écrit avant
                        que BOAMP n'existe. Sa prémisse a disparu, pas son objet.
RÉSULTATS ANTÉRIEURS    aucun. Le test vérifie un invariant de validation, pas
                        un chiffre. Aucune mesure passée n'en dépend.
CORRECTIF               l'exemple devient « marchesonline », qui n'est pas un
                        connecteur ; un commentaire dit pourquoi il a changé.
TEST DE RÉGRESSION      le test lui-même, inchangé dans son intention : ce qui
                        n'est pas dans `SourceSystem` est refusé.
```

Aucune métrique ancienne n'a été modifiée.

---

## TEST RESULTS

```bash
$ uv run pytest -q
1916 passed in 16.30s          # 1771 avant SPEC-009E + 145 nouveaux

$ uv run ruff check .
All checks passed!

$ git diff --check
(rien)

$ uv run ruff format --check .
1 file would be reformatted
  docs/superpowers/plans/2026-08-17-spec009-precision-first-document-requirements.md
```

Le défaut Markdown est le défaut historique connu, hors périmètre.

Répartition des 145 nouveaux tests :

```text
§43 fraîcheur                    20   5 j, 30 j, 31 j, 61 j, inconnue, futur, 2002, sentinelles
§31 formulation                  40   6 états × 2 langues + interdiction + types d'événement
§21 §44 §45 adapter BOAMP        21   avis réels, champ piège, plafond d'accord-cadre, Evidence
§37 §38 curseur                  10   requête pure, pagination, idempotence
§22 §23 §24 §25 DECP + fusion    22   vrais rapprochements, 4 leurres, conflits
§16 §44 sémantique des dates     20   registre, SIMAP, TED, BOAMP, DECP
§26 §27 §28 étude France         12   dénominateurs, statuts, seuils d'échantillon
```

---

## OPEN QUESTIONS

Quatre, toutes réelles.

**1. `dateNotification` doit-elle rester hors de `award_date` ?**
C'est la décision la plus coûteuse de cette SPEC. Le choix conservateur de §20
prive la France d'une date sur 90,8 % de ses award-lots, alors que la
notification est commercialement très proche de ce que le client veut savoir —
c'est le moment où l'entreprise apprend qu'elle a gagné. Une option existe et
n'a pas été prise : un statut distinct, `recently_notified_award`, avec une
phrase à lui. Elle demande une décision produit, pas technique.

**2. Faut-il committer les artefacts gelés de SPEC-009C ?**
Trois tests de SPEC-009D et la comparaison à trois sources de SPEC-009E les
relisent. Ils sont aujourd'hui non suivis, donc ces tests sont ignorés sur un
clone frais et la comparaison CH/UE n'y est pas recalculable. Le coût est ~12 Mo
de fixtures.

**3. Les 20,6 % d'avis BOAMP non-eForms.**
`FNSimple` et `MAPA` représentent 137 avis sur 666, et leurs faits sont dans du
texte libre. Les ignorer coûte du volume français ; les parser demanderait une
extraction dont la provenance serait faible. La question n'est pas tranchée, et
la doctrine actuelle (écarter, compter) est défendable telle quelle.

**4. Le rapprochement BOAMP × DECP est démontré mais inopérant.**
Il fonctionne — deux vrais rapprochements, quatre leurres correctement rejetés —
et son taux sur données fraîches est de 0 %, DECP s'arrêtant en février 2024.
Faut-il le conserver pour un enrichissement rétrospectif, ou le mettre en
sommeil jusqu'à ce que DECP rattrape son retard ?

---

## VERDICT

```text
RECENT AWARD FOUNDATION READY
```

Les huit conditions de §49, une par une :

```text
SIMAP distingue décision et publication          ✔  98,7 % de couverture, délai médian 5 j,
                                                    le cas aberrant de 2002 désormais attrapé
l'ingestion France fonctionne sur du réel        ✔  1 482 award-lots issus de 666 avis BOAMP
                                                    réels, 0 échec de parsing ; DECP adapté et
                                                    rapproché sur un vrai couple
TED gère connu contre inconnu                    ✔  7 recent_award, 21 recently_published,
                                                    aucune date fabriquée
aucune source ne substitue la publication        ✔  testé sur les quatre ; `assess_recency`
à la date d'attribution                             refuse même de recevoir une date de signature
récent / périmé / inconnu déterministes          ✔  six états, fonction pure, seuil versionné
tout fait affiché conserve sa preuve             ✔  493 award-lots FR dans Contract
                                                    Understanding : evidence_coverage = 1,0,
                                                    zéro fait sans preuve
zéro régression factuelle critique               ✔  moteurs intacts, 12 lignes de diff suivi
tests verts                                      ✔  1 916 passed, ruff clean
```

La fondation est prête. Ce que la mesure ajoute, et que le verdict ne dit pas :
**la promesse « vient de remporter » n'a pas la même force selon le pays** —
64,5 % en Suisse, 20,6 % dans l'Union, 3,0 % en France. Le produit peut la
tenir partout parce que la politique de formulation l'y oblige ; il ne la tiendra
pas au même volume partout.

Rien n'est committé pour SPEC-009E (§52). Aucune suite n'est commencée : ni
SPEC-010, ni base de données, ni auth, ni frontend, ni déploiement, ni
Acquisition Engine. En attente de la décision du superviseur.
