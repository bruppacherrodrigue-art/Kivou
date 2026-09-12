# Kivou — Roadmap post-production Award & Sales Signals

**Statut :** roadmap produit post-production  
**Date de référence :** 24 août 2026  
**Périmètre :** SaaS client Kivou — Award & Sales Signals  
**Hors périmètre :** Acquisition Engine interne, refonte pricing, bid management, réponse aux appels d'offres  
**Principe de livraison :** aucun élément de cette roadmap ne doit retarder le go-live initial.

---

## 1. Résumé exécutif

Kivou doit rester centré sur un wedge très précis :

> **Transformer une adjudication publique en opportunité commerciale B2B envers l'entreprise qui vient de gagner le contrat.**

Le produit actuel possède déjà les briques les plus difficiles : gagnant résolu, compréhension du contrat, exigences d'exécution lorsqu'elles sont disponibles, Need Graph, matching ICP, récence multi-horloges, preuve, feed commercial, détail de signal, feedback client et alertes.

La prochaine étape n'est donc pas de construire une plateforme d'appels d'offres plus large. Elle consiste à rendre la sortie actuelle encore plus directement exploitable par un commercial :

1. **dire quand agir ;**
2. **dire pourquoi le gagnant pourrait acheter à l'extérieur ;**
3. **dire quoi faire ensuite ;**
4. **apprendre des retours client sans dégrader la fiabilité ;**
5. **envoyer les meilleurs signaux dans les workflows commerciaux existants ;**
6. **étendre le signal au cycle de vie du contrat, notamment aux expirations.**

Les benchmarks concurrentiels utiles sont principalement TedScout et publicdeals.io / aufträge.io. Ils valident la catégorie « award data → commercial leads », mais leurs meilleures idées sont surtout des couches d'action autour de l'award. Kivou doit les intégrer sans abandonner son avantage structurel : **la compréhension prouvée du contrat et des besoins aval**.

---

## 2. Positionnement à préserver

### 2.1 Ce que Kivou est

Kivou est un système de **post-award sales intelligence**.

Chaîne cible :

```text
AWARD PUBLIC
    ↓
WINNER RESOLUTION
    ↓
CONTRACT UNDERSTANDING
    ↓
EXECUTION REQUIREMENTS / NEED GRAPH
    ↓
PROBABLE DOWNSTREAM NEEDS
    ↓
ICP / SUPPLIER FIT
    ↓
COMMERCIAL TIMING
    ↓
NEXT BEST ACTION
    ↓
B2B OUTREACH
```

La proposition de valeur n'est pas « trouvez des marchés publics à gagner » mais :

> **« Découvrez quelles entreprises viennent de gagner de nouveaux contrats, ce qu'elles vont probablement devoir acheter pour les exécuter, pourquoi votre offre est pertinente et quand les contacter. »**

### 2.2 Ce que Kivou ne doit pas devenir

Ne pas dériver vers une plateforme générique de bid management ou de tender intelligence.

Sont explicitement hors roadmap Award & Sales Signals :

- GO / NO-GO pour répondre à un appel d'offres ;
- génération de dossier de réponse ;
- pipeline de soumissions ;
- scoring de probabilité de gagner un marché public ;
- price benchmarking pour fixer un prix d'offre ;
- buyer intelligence destinée à choisir quels acheteurs publics prospecter ;
- chat généraliste sur les appels d'offres ;
- moteur de recherche CPV comme produit principal.

Ces fonctions peuvent être utiles chez TedScout, mais elles déplaceraient Kivou vers une catégorie beaucoup plus encombrée et affaibliraient son wedge différenciant.

---

## 3. Baseline produit déjà disponible

La roadmap part de capacités déjà présentes dans le produit et ne doit pas les dupliquer.

### 3.1 Signal client

Le détail de signal expose déjà :

- entreprise gagnante ;
- titre et montant du contrat ;
- acheteur public ;
- lot, référence, CPV et localisation lorsque disponibles ;
- dates d'attribution, de notification et de publication séparées ;
- `event.headline`, `event.why_now` et note sur la date d'attribution ;
- besoins plausibles avec `timing`, `timing_label`, confiance et raisonnement ;
- lecture du contrat ;
- fit ICP et raisons de fit ;
- preuve / provenance ;
- lien vers la fiche entreprise.

Références principales :

- `frontend/src/pages/SignalDetail.tsx`
- `frontend/src/api/types.ts`

### 3.2 Profil ICP

Le profil de ciblage sait déjà décrire :

- les offres vendues ;
- les métiers des clients visés ;
- les territoires ;
- un seuil de valeur de contrat ;
- un résumé libre de l'offre.

La nouvelle couche commerciale doit donc consommer l'ICP existant plutôt que créer un deuxième profil de vente.

### 3.3 Feedback et action commerciale

Kivou collecte déjà deux informations distinctes :

1. **jugement de qualité** : `relevant` / `not_relevant` ;
2. **action commerciale** : `contacted_at`.

Les motifs négatifs sont déjà structurés :

- `already_covered` ;
- `done_internally` ;
- `wrong_customer_type` ;
- `too_late` ;
- `wrong_need` ;
- `other`.

Le schéma actuel interdit volontairement que ce feedback modifie automatiquement le Need Graph ou le matching. Cette frontière doit être conservée pour la première version de la boucle d'apprentissage.

Références :

- `frontend/src/feedback/FeedbackControl.tsx`
- `src/signals/engagement/schema.py`

### 3.4 Fiche entreprise

La fiche entreprise existe déjà à partir de l'identité officielle disponible dans les avis publics et des signaux Kivou liés. L'enrichissement fournisseur externe n'est pas une condition du lancement.

---

## 4. Benchmark concurrentiel utile

### 4.1 TedScout

Référence vérifiée le 24 août 2026 : `https://tedscout.eu/docs`

Les idées à retenir sont :

- `get_subcontractor_leads` transforme les gagnants récents en leads B2B ;
- statut de mobilisation : 0–30 jours, 31–60 jours, 61+ jours ;
- signaux de sous-traitance fondés notamment sur valeur, consortium et procédure ;
- description sectorielle des sous-traitants typiquement nécessaires ;
- prochaines étapes d'outreach suggérées ;
- watchlists avec e-mail et webhook compatible Zapier / Make / CRM ;
- ratings utilisés pour améliorer le matching futur.

Ce que Kivou doit faire mieux : ne pas déduire principalement le besoin à partir d'une heuristique « secteur + montant », mais utiliser les exigences et le Need Graph lorsque la preuve documentaire est disponible.

### 4.2 publicdeals.io / aufträge.io

Référence vérifiée le 24 août 2026 : `https://www.publicdeals.io/facts/`

Les idées à retenir sont :

- award notices comme source de leads ;
- vector analysis pour rapprocher gagnants et fournisseurs / partenaires ;
- contrats arrivant à expiration comme early-warning system ;
- notion explicite de « secondary market » après adjudication ;
- expiration d'un framework comme moment possible de recomposition de la supply chain.

Ce que Kivou doit faire mieux : faire de l'expiration un **signal commercial prouvé**, pas une simple date de fin projetée lorsque la source ne publie pas suffisamment d'information.

---

# 5. Priorités de roadmap

| Priorité | Epic | Valeur attendue | Effort relatif | Dépendance critique |
|---|---|---:|---:|---|
| **P1** | Commercial Mobilisation Window | Très forte | Faible / moyen | récence + timing Need Graph |
| **P1** | Externalisability / Delivery Dependency | Très forte | Moyen | Need Graph + exigences |
| **P1** | Next Best Commercial Action | Très forte | Faible / moyen | deux epics P1 précédentes |
| **P2** | Feedback-assisted Matching | Forte | Moyen | volume de feedback réel |
| **P2** | Customer Webhooks / CRM | Forte | Moyen | alertes + contrat d'événement |
| **P2 conditionnel** | Winner Enrichment & Contact Surface | Forte | Moyen | droits fournisseur / provenance |
| **P3** | Contract Lifecycle & Expiry Signals | Forte | Moyen / fort | durées et dates de fin fiables |

Ordre recommandé :

```text
P1-A Mobilisation
       ↓
P1-B Externalisabilité
       ↓
P1-C Next Best Action
       ↓
P2-A Feedback-assisted ranking
P2-B Webhooks / CRM
P2-C Enrichissement conditionnel
       ↓
P3 Contract lifecycle / expiry
```

---

# 6. P1-A — Commercial Mobilisation Window

## 6.1 Problème

Kivou sait déjà dire quand l'attribution a eu lieu et peut posséder un timing par besoin. Mais le commercial doit encore traduire lui-même ces données en décision : **est-ce le bon moment pour appeler ?**

TedScout résout cette friction avec des classes simples de mobilisation. Kivou doit reprendre la simplicité, tout en utilisant plus d'information que le seul âge de l'award.

## 6.2 Objectif produit

Chaque signal doit fournir une réponse explicite à :

> **« Quelle est la fenêtre commerciale probable pour ce besoin ? »**

Vocabulaire client proposé :

- `act_now` → **Contacter maintenant** ;
- `favorable` → **Fenêtre favorable** ;
- `mature` → **Opportunité mature** ;
- `monitor` → **À surveiller** ;
- `unknown` → **Timing insuffisant**.

Ne pas afficher un faux niveau de précision si le moteur ne dispose que d'une date de publication.

## 6.3 Sources de décision, par ordre d'autorité

1. date / période d'exécution explicitement publiée ;
2. exigence d'exécution avec échéance prouvée ;
3. timing du besoin déjà porté dans le Need Graph ;
4. date d'attribution ;
5. date de notification du contrat ;
6. date de publication ;
7. fallback « timing insuffisant ».

Une date de publication récente ne doit jamais être présentée comme une attribution récente si la date d'attribution est ancienne ou inconnue.

## 6.4 Contrat de données proposé

Ajout d'un bloc serveur-authoritative sur le détail et, en version condensée, sur le feed :

```json
{
  "commercial_timing": {
    "status": "act_now",
    "label": "Contacter maintenant",
    "confidence": "high",
    "basis": [
      "award_8_days_ago",
      "execution_start_in_34_days"
    ],
    "reason": "Le contrat vient d'être attribué et le démarrage publié laisse une fenêtre de mobilisation avant exécution.",
    "policy": "commercial-timing-v1"
  }
}
```

### Règles

- aucune logique de calcul côté React ;
- le frontend rend le verdict serveur ;
- `status=unknown` est une sortie normale ;
- la confiance doit refléter la source du timing ;
- chaque raison affichée doit être reconstructible depuis des données accessibles au compte ;
- aucune date « recommandée avant le » ne doit être inventée sans règle déterministe documentée.

## 6.5 UX proposée

Sur la carte feed :

```text
🔥 Contacter maintenant
Attribution il y a 8 jours · exécution annoncée dans 34 jours
```

Dans le détail :

```text
Fenêtre commerciale
Contacter maintenant

Pourquoi : le contrat vient d'être attribué et son exécution débute prochainement.
Confiance : élevée
```

Le badge commercial doit apparaître avant les détails documentaires, après le fait principal et avant les preuves.

## 6.6 Critères d'acceptation

- le même signal reçoit le même statut à données égales ;
- aucune date n'est recalculée dans le frontend ;
- la publication seule ne peut pas produire un faux « vient de gagner » ;
- un contrat sans date exploitable donne `unknown` ;
- la logique est testée sur les frontières temporelles ;
- les textes FR/EN restent sémantiquement équivalents ;
- les signaux historiques ne sont pas artificiellement promus en urgence.

## 6.7 KPI

Primaire :

- taux `signal_contacted / signal_detail_viewed` par statut de fenêtre commerciale.

Secondaires :

- taux `too_late` par statut ;
- délai entre premier affichage du signal et `signal_contacted` ;
- taux de pertinence par statut.

---

# 7. P1-B — Externalisability / Delivery Dependency

## 7.1 Problème

Un besoin plausible ne signifie pas nécessairement une opportunité fournisseur.

Exemples :

- le gagnant possède déjà la ressource en interne ;
- le besoin est explicitement inclus dans le consortium ;
- le marché exige une prestation mais rien n'indique qu'elle sera achetée ;
- le besoin est externe par nature ou par spécialisation ;
- le planning ou la capacité rend un achat externe plus probable.

Kivou doit distinguer :

```text
BESOIN D'EXÉCUTION
        ≠
BESOIN COMMERCIAL EXTERNALISABLE
```

## 7.2 Objectif produit

Pour chaque besoin ciblé par l'ICP, produire une évaluation :

- `high` → forte plausibilité d'achat externe ;
- `medium` → possibilité crédible ;
- `low` → externalisation peu soutenue ;
- `unknown` → insuffisamment démontrable.

Le produit ne doit jamais dire « le gagnant va acheter X » comme un fait.

## 7.3 Hiérarchie de preuve

### Niveau 1 — preuve documentaire directe

Exemples :

- sous-traitance explicitement autorisée / structurée ;
- obligation de recours à une spécialité ;
- fourniture ou équipement explicitement requis ;
- quantité ou capacité clairement supérieure à une composante déjà identifiée.

### Niveau 2 — Need Graph + composition du marché

Exemples :

- besoin distinct de l'objet principal du titulaire ;
- besoin de spécialité complémentaire ;
- plusieurs familles de ressources nécessaires ;
- timing incompatible avec un approvisionnement tardif.

### Niveau 3 — signaux contextuels

Utilisables uniquement comme soutien, jamais comme preuve unique forte :

- montant élevé ;
- consortium ;
- complexité de lot ;
- durée d'exécution ;
- diversité des exigences.

### Niveau 4 — fallback sectoriel

Possible uniquement avec confiance réduite et wording explicite.

Une heuristique « construction > X € = sous-traitance forte » ne doit jamais être l'autorité principale lorsqu'une information contractuelle plus précise existe.

## 7.4 Contrat de données proposé

Au niveau du besoin :

```json
{
  "externalisation": {
    "level": "high",
    "label": "Forte plausibilité d'externalisation",
    "confidence": "high",
    "reasons": [
      {
        "code": "specialist_execution_requirement",
        "text": "Le contrat exige une spécialité distincte de la prestation principale.",
        "evidence_refs": ["ev_123"]
      },
      {
        "code": "short_mobilisation_window",
        "text": "Le démarrage publié laisse une fenêtre courte de mobilisation.",
        "evidence_refs": []
      }
    ],
    "policy": "externalisation-v1"
  }
}
```

## 7.5 UX proposée

Bloc dans le détail :

```text
Pourquoi ce gagnant pourrait acheter à l'extérieur

Forte plausibilité d'externalisation

✓ spécialité distincte requise pour l'exécution
✓ délai de mobilisation court
✓ besoin correspondant à votre offre

Ce résultat est une analyse Kivou, pas une déclaration du gagnant.
```

Le bloc doit rester séparé visuellement des faits publics.

## 7.6 Interaction avec le feedback existant

Les raisons négatives actuelles deviennent des signaux R&D particulièrement utiles :

- `already_covered` → qualité de l'évaluation d'externalisation ;
- `done_internally` → externalisation surestimée ;
- `wrong_need` → erreur de Need Graph / qualification ;
- `wrong_customer_type` → erreur de matching ICP ;
- `too_late` → erreur de timing.

Cette mapping doit être analytique avant d'être corrective.

## 7.7 Critères d'acceptation

- besoin plausible et besoin externalisable restent deux champs distincts ;
- aucun niveau `high` sans raisons structurées ;
- toute raison documentaire conserve une provenance ;
- les heuristiques contextuelles seules ne peuvent pas créer un `high` ;
- `unknown` doit être préféré à une affirmation faible déguisée ;
- aucun feedback d'un client ne modifie le fait public ou le Need Graph partagé.

## 7.8 KPI

- taux de `already_covered` et `done_internally` par niveau d'externalisation ;
- taux de contact par niveau ;
- taux de pertinence par niveau ;
- proportion de signaux `unknown` afin de surveiller la couverture documentaire.

---

# 8. P1-C — Next Best Commercial Action

## 8.1 Problème

Même un bon signal demande encore au client de répondre à trois questions :

- dois-je agir ?
- sur quel besoin ?
- avec quel angle ?

TedScout fournit des « suggested next steps ». Kivou doit transformer cette idée en action fondée sur son intelligence propre.

## 8.2 Objectif produit

Chaque signal débloqué doit pouvoir fournir **une action principale**, et une seule.

Vocabulaire v1 proposé :

- `contact_now` ;
- `research_contact` ;
- `prepare_supplier_offer` ;
- `monitor` ;
- `no_action`.

La recommandation est un verdict de présentation, pas un outil d'envoi automatique.

## 8.3 Entrées

La décision doit consommer :

- commercial timing ;
- externalisabilité ;
- fit ICP ;
- besoin ciblé par l'ICP ;
- niveau de confiance ;
- état `contacted` ;
- éventuellement disponibilité d'une fiche entreprise exploitable.

## 8.4 Sortie proposée

```json
{
  "next_action": {
    "type": "contact_now",
    "label": "Contacter cette entreprise",
    "priority": "high",
    "need_ref": "need_abc",
    "reason": "Votre offre correspond à un besoin d'exécution à forte plausibilité d'externalisation pendant une fenêtre de mobilisation active.",
    "outreach_angle": "Positionnez votre offre sur la fourniture / spécialité identifiée avant le démarrage d'exécution.",
    "policy": "next-commercial-action-v1"
  }
}
```

## 8.5 UX proposée

En tête du détail :

```text
Action recommandée

Contacter cette entreprise

Pourquoi maintenant : fenêtre de mobilisation active.
Angle : proposer [besoin ciblé] comme ressource d'exécution du contrat remporté.

[Voir l'entreprise]  [Marquer comme contacté]
```

Si une future surface de contacts est disponible :

```text
[Trouver le bon contact]
```

Aucun bouton d'envoi d'e-mail automatique ne doit être ajouté à cette étape.

## 8.6 Règles de sûreté produit

- ne jamais inventer le nom d'un décideur ;
- ne pas fabriquer un « responsable du projet » si aucun contact n'est connu ;
- l'angle commercial ne doit pas affirmer que le gagnant cherche activement un fournisseur ;
- `no_action` est une sortie valide ;
- après `contacted_at`, la CTA principale doit refléter l'état déjà contacté ;
- un signal de faible fit ne doit pas recevoir une recommandation agressive uniquement parce qu'il est récent.

## 8.7 Critères d'acceptation

- une seule action principale ;
- décision serveur-authoritative ;
- raisons visibles ;
- aucune recommandation d'action forte si timing ou externalisabilité sont insuffisants ;
- test de cohérence avec `contacted_at` ;
- instrumentation de l'affichage et du clic sur l'action.

## 8.8 KPI

North-star feature metric :

```text
signal_action_contacted_rate
= signaux marqués contactés / signaux avec next_action=contact_now vus
```

Guardrails :

- `not_relevant` après recommandation `contact_now` ;
- `too_late` après recommandation ;
- `done_internally` après recommandation.

---

# 9. P2-A — Feedback-assisted Matching

## 9.1 Principe

Kivou collecte déjà le feedback nécessaire. La roadmap ne doit pas créer un deuxième système de notation.

Le changement consiste à passer de :

```text
FEEDBACK → STOCKAGE → ANALYTIQUE
```

à :

```text
FEEDBACK → ANALYTIQUE → HYPOTHÈSE DE CORRECTION
         → SHADOW RANKING
         → VALIDATION
         → RÈGLE VERSIONNÉE
```

et non :

```text
CLIC 👎 → MODIFICATION IMMÉDIATE DU MOTEUR
```

## 9.2 Utilisation des motifs

| Feedback | Composant à investiguer en priorité |
|---|---|
| `wrong_need` | Need Graph / besoin ciblé |
| `wrong_customer_type` | matching buyer trade / ICP |
| `too_late` | commercial timing / récence |
| `already_covered` | externalisabilité |
| `done_internally` | externalisabilité / connaissance entreprise |
| `relevant` + `contacted` | signal positif fort |

## 9.3 Première version recommandée

Construire un **re-ranker client-specific en shadow**, jamais un moteur qui réécrit les faits.

Sortie shadow :

```json
{
  "feedback_rerank": {
    "baseline_rank": 4,
    "shadow_rank": 2,
    "factors": ["historically_relevant_need_family"],
    "policy": "feedback-rerank-shadow-v1"
  }
}
```

Aucun impact visible avant validation offline / cohort.

## 9.4 Gate de données proposé

Ne pas activer de personnalisation automatique sur un ICP avec trop peu de labels.

Gate v1 à valider empiriquement avant production :

- au moins 20 signaux explicitement notés ;
- au moins 5 positifs et 5 négatifs ;
- aucune raison unique ne doit être transformée en règle permanente sur un seul clic ;
- toute règle appliquée doit être versionnée et réversible.

Le seuil final doit être confirmé par l'évaluation offline ; il n'est pas un dogme produit.

## 9.5 Étapes

1. dashboard interne de distribution des feedbacks ;
2. analyse des faux positifs par composant ;
3. re-ranking shadow ;
4. comparaison baseline / shadow sur données historiques ;
5. exposition à une cohorte restreinte ;
6. généralisation uniquement si le taux de pertinence progresse sans augmenter les faux signaux critiques.

## 9.6 KPI

- uplift de `relevant` vs baseline ;
- uplift de `contacted` ;
- baisse de `wrong_need` ;
- baisse de `wrong_customer_type` ;
- aucune hausse significative de faux `contact_now`.

---

# 10. P2-B — Customer Webhooks / CRM

## 10.1 Objectif

Faire entrer Kivou dans le workflow commercial du client sans construire un CRM.

Ordre recommandé :

1. webhook générique signé ;
2. documentation Make / Zapier ;
3. connecteurs natifs uniquement si la demande réelle le justifie.

## 10.2 Événements v1

- `signal.created` ;
- `signal.priority_changed` uniquement si le changement est matériel et défini ;
- `signal.contacted` ;
- éventuellement `company.new_award` pour les comptes multi-signaux.

Ne pas générer des événements à chaque révision technique du signal.

## 10.3 Payload minimal proposé

```json
{
  "event_id": "evt_opaque",
  "event_type": "signal.created",
  "occurred_at": "2026-08-24T08:00:00Z",
  "signal": {
    "signal_id": "sig_opaque",
    "company_name": "Example SA",
    "contract_title": "...",
    "amount": {"value": "1250000", "currency": "CHF"},
    "commercial_timing": "act_now",
    "externalisation": "high",
    "next_action": "contact_now",
    "app_url": "https://kivou.eu/app/signals/..."
  }
}
```

Ne pas inclure par défaut :

- texte intégral des documents ;
- excerpts de preuve ;
- notes privées non nécessaires ;
- secrets fournisseur ;
- contacts personnels sans base contractuelle claire.

## 10.4 Fiabilité

Obligatoire :

- signature HMAC ;
- secret rotatable ;
- idempotency event ID ;
- timeout borné ;
- retry avec backoff ;
- journal de livraison ;
- état terminal ;
- désactivation après échecs persistants ;
- replay manuel borné ;
- aucun blocage du pipeline principal si le CRM du client tombe.

## 10.5 UX

Dans les paramètres :

```text
Intégrations
Webhook commercial
URL : …
Secret : généré / rotatable
Événements : nouveaux signaux
Dernière livraison : OK / erreur
[Envoyer un test]
```

## 10.6 KPI

- % comptes Pro/Scale configurant une intégration ;
- taux de livraison ;
- taux d'ouverture Kivou depuis CRM ;
- contact rate des signaux exportés vs non exportés.

---

# 11. P2-C conditionnel — Winner Enrichment & Contact Surface

## 11.1 Contexte

La fiche entreprise actuelle doit rester fondée sur l'identité officielle publique. Un enrichissement externe peut apporter une valeur commerciale supplémentaire, mais il ne doit pas devenir une dépendance structurante du signal.

Cette epic est **conditionnelle** à la validation des droits d'usage client-facing du fournisseur choisi.

## 11.2 Valeur cible

Ajouter, lorsque légalement et contractuellement permis :

- site officiel / domaine confirmé ;
- secteur ;
- taille approximative ;
- description d'activité ;
- rôles commerciaux ou opérationnels pertinents ;
- contact professionnel vérifié lorsque le fournisseur autorise cet usage.

## 11.3 Principes

- l'identité officielle Kivou reste l'autorité de rattachement ;
- un fournisseur d'enrichissement ne fusionne jamais deux entreprises sur le seul nom ;
- chaque champ externe porte `source`, `retrieved_at`, TTL et statut de confiance ;
- aucun payload fournisseur brut n'est rendu au client ;
- absence d'enrichissement ≠ absence d'entreprise ;
- aucun appel payant automatique sur chaque affichage sans budget / cache explicite.

## 11.4 UX cible

```text
Entreprise gagnante
Example SA

Données officielles
…

Contexte commercial enrichi
Secteur : …
Effectif : …
Site : …

Contact recommandé
Rôle : Responsable opérations / achats / projet
[Voir les contacts disponibles]
```

Le **rôle** peut être recommandé avant qu'une personne réelle soit disponible. Le système ne doit jamais inventer une personne.

---

# 12. P3 — Contract Lifecycle & Expiry Signals

## 12.1 Opportunité

L'award est un moment commercial fort, mais pas le seul.

Un contrat public peut créer plusieurs fenêtres :

```text
AWARD
  ↓
MOBILISATION
  ↓
EXECUTION
  ↓
MID-CONTRACT NEEDS
  ↓
EXPIRY / RENEWAL
  ↓
SUPPLY-CHAIN REFRESH
```

publicdeals.io exploite déjà l'expiration comme early-warning system. Kivou peut aller plus loin en reliant cette échéance aux besoins et au titulaire.

## 12.2 Nouveaux types de signaux envisagés

### `contract_expiring`

Le contrat possède une date de fin explicitement publiée et entre dans une fenêtre de fin proche.

### `supply_chain_refresh_window`

La fin d'un framework ou d'un contrat rend plausible une remise en concurrence des partenaires / fournisseurs.

Ce second signal est une inférence Kivou et doit être présenté comme telle.

## 12.3 Autorité temporelle

Ordre :

1. date de fin contractuelle publiée ;
2. durée explicitement publiée + date de début publiée ;
3. aucune date de fin si l'un des deux éléments manque ;
4. ne jamais inventer une durée moyenne sectorielle comme date de fin contractuelle.

## 12.4 Contrat de données proposé

```json
{
  "lifecycle_signal": {
    "type": "contract_expiring",
    "status": "upcoming",
    "event_date": "2027-02-28",
    "days_until_event": 92,
    "confidence": "high",
    "basis": "published_contract_end_date",
    "commercial_reason": "La fin publiée du contrat peut ouvrir une nouvelle fenêtre de sourcing ou de partenariat.",
    "policy": "contract-lifecycle-v1"
  }
}
```

## 12.5 Expérience utilisateur

Le compte ne doit pas avoir un feed séparé complexe au départ. Les lifecycle signals doivent entrer dans le feed actuel avec un type distinct :

```text
🔄 Fenêtre de renouvellement

Example SA
Contrat arrivant à échéance dans 3 mois

Pourquoi cela compte
La fin publiée du contrat peut entraîner une nouvelle phase de sourcing.

Besoin correspondant à votre offre : …
```

## 12.6 KPI

- pertinence des lifecycle signals ;
- taux de contact ;
- délai de contact avant expiration ;
- taux de `too_late` comparé aux award signals.

---

# 13. Ordonnancement de livraison

## Phase POST-PROD 1 — rendre le signal actionnable

**Objectif :** augmenter directement le taux de contact sans élargir la catégorie produit.

Livrer :

1. Commercial Mobilisation Window ;
2. Externalisability / Delivery Dependency ;
3. Next Best Commercial Action.

Cette phase doit réutiliser les API, le Need Graph, l'ICP et le système de preuve existants. Elle ne doit nécessiter ni CRM externe ni enrichissement personnel.

### Gate de sortie

- trois blocs disponibles en FR/EN ;
- aucune régression facts vs analysis ;
- analytics en place ;
- comparatif avant/après sur `signal_contacted` ;
- aucune hausse notable de `wrong_need`, `done_internally` ou `too_late`.

## Phase POST-PROD 2 — apprendre et distribuer

Livrer :

1. analyse structurée du feedback ;
2. shadow feedback re-ranking ;
3. webhook générique ;
4. éventuellement enrichissement winner / contacts si les droits fournisseur le permettent.

### Gate de sortie

- amélioration mesurée du taux de pertinence ;
- aucune mutation opaque du Need Graph ;
- webhook idempotent et signé ;
- coûts d'enrichissement bornés et observables.

## Phase POST-PROD 3 — cycle de vie du contrat

Livrer :

1. modèle de lifecycle event ;
2. dates de fin fiables ;
3. expiring contract signals ;
4. supply-chain refresh inference ;
5. intégration au matching ICP et aux alertes.

### Gate de sortie

- date de fin prouvée pour tout signal `contract_expiring` ;
- absence de fausse précision lorsque la durée n'est pas publiée ;
- valeur commerciale validée sur une cohorte avant généralisation.

---

# 14. Architecture produit recommandée

Les nouvelles couches doivent rester séparées :

```text
Public facts
    ↓
Contract understanding
    ↓
Execution requirements
    ↓
Need Graph
    ↓
Externalisation assessment
    ↓
ICP fit
    ↓
Commercial timing
    ↓
Next commercial action
    ↓
Customer interaction / feedback
```

Règles :

- un feedback client ne modifie jamais un fait public ;
- l'externalisabilité ne doit pas être confondue avec l'existence du besoin ;
- le timing commercial ne doit pas réécrire la récence source ;
- la Next Best Action ne doit pas devenir une deuxième implémentation du matching ;
- chaque décision dérivée possède une policy/version ;
- les décisions client-facing doivent être reconstructibles et auditables.

---

# 15. Instrumentation post-production

Événements additionnels recommandés :

```text
commercial_timing_viewed
externalisation_viewed
next_action_viewed
next_action_clicked
crm_webhook_configured
crm_webhook_delivered
lifecycle_signal_viewed
```

Ne pas créer un événement pour chaque rendu React. Les événements doivent correspondre à une interaction ou une exposition produit utile à l'analyse.

## 15.1 Funnel produit cible

```text
signal_feed_viewed
    ↓
signal_detail_viewed
    ↓
next_action_viewed
    ↓
signal_feedback_relevant
    ↓
signal_contacted
```

La métrique commerciale principale reste **le passage à l'action**, pas le nombre de cartes affichées.

---

# 16. Packaging — hypothèse, pas décision tarifaire

Ne pas modifier les prix dans cette roadmap. En revanche, la future segmentation de valeur peut être pensée ainsi :

### Essential

- Award Signals ;
- besoins plausibles ;
- preuve ;
- timing de base.

### Pro

- commercial timing avancé ;
- externalisabilité ;
- Next Best Action ;
- plusieurs ICP / historique selon entitlements existants.

### Scale

- webhooks / CRM ;
- lifecycle signals avancés ;
- éventuels enrichissements supplémentaires ;
- fonctionnalités de distribution / équipe.

Ce packaging devra être validé par usage réel avant toute modification du catalogue.

---

# 17. Risques et garde-fous

## 17.1 Sur-promesse commerciale

Risque : transformer une plausibilité en certitude.

Garde-fou : wording systématique « plausible », « peut », « probabilité / plausibilité », jamais « recherche actuellement » sans preuve publique.

## 17.2 Urgence artificielle

Risque : badges « maintenant » trop agressifs.

Garde-fou : statut serveur déterministe, aucune urgence créée par le frontend, `unknown` normal.

## 17.3 Externalisation inventée

Risque : traiter montant élevé ou CPV comme preuve suffisante.

Garde-fou : heuristiques contextuelles uniquement comme support ; niveau fort exige signaux plus substantiels.

## 17.4 Boucle de feedback instable

Risque : sur-apprendre d'un utilisateur ou d'un petit échantillon.

Garde-fou : shadow first, seuil de données, règles versionnées, rollback.

## 17.5 Enrichissement fournisseur

Risque : coûts, provenance, droits d'usage, données obsolètes.

Garde-fou : feature conditionnelle, TTL, cache, budget, source explicite, identité officielle Kivou comme ancre.

## 17.6 Dérive produit

Risque : copier les fonctions de tender management des concurrents.

Garde-fou : toute future feature doit répondre à au moins une de ces questions :

1. aide-t-elle à identifier un gagnant pertinent ?
2. aide-t-elle à comprendre un besoin aval ?
3. aide-t-elle à savoir quand prospecter ?
4. aide-t-elle à agir commercialement envers le gagnant ?

Sinon elle n'appartient probablement pas à Award & Sales Signals.

---

# 18. Découpage recommandé en futures SPECs

Utiliser des identifiants de travail post-production plutôt que réserver dès maintenant des numéros `SPEC-xxx` susceptibles d'entrer en collision.

## POSTPROD-01 — Commercial Timing

Livrables :

- modèle `commercial_timing` ;
- policy v1 ;
- projection feed + détail ;
- FR/EN ;
- tests frontières temporelles ;
- analytics.

## POSTPROD-02 — Externalisation Assessment

Livrables :

- modèle d'évaluation par need ;
- raisons structurées ;
- preuve ;
- policy v1 ;
- benchmark offline ;
- UX.

## POSTPROD-03 — Next Commercial Action

Livrables :

- vocabulaire fermé ;
- décision serveur ;
- CTA ;
- instrumentation ;
- cohérence avec `contacted_at`.

## POSTPROD-04 — Feedback Learning Shadow

Livrables :

- dataset analytique ;
- mapping motifs → composant ;
- shadow re-ranker ;
- évaluation offline ;
- gates d'activation.

## POSTPROD-05 — Customer Webhooks

Livrables :

- schéma événement ;
- endpoint config ;
- signature ;
- retries ;
- journal ;
- écran paramètres ;
- test payload.

## POSTPROD-06 — Winner Enrichment

**Condition :** validation contractuelle / droits d'usage fournisseur.

Livrables :

- politique de provenance ;
- TTL ;
- budget ;
- mapping identité officielle → fournisseur ;
- exposition client-safe.

## POSTPROD-07 — Contract Lifecycle Signals

Livrables :

- modèle lifecycle ;
- dates / durées ;
- expiration ;
- supply-chain refresh ;
- matching ICP ;
- alertes.

---

# 19. Définition de réussite de la roadmap

La roadmap est réussie si Kivou réduit la distance entre un fait public et une action commerciale à cette séquence :

```text
Cette entreprise vient de gagner ce contrat.
                ↓
Voici ce qu'elle doit probablement mobiliser.
                ↓
Voici ce qui paraît externalisable.
                ↓
Votre offre correspond à ce besoin.
                ↓
La fenêtre commerciale est active.
                ↓
Voici l'action recommandée.
                ↓
CONTACT
```

Le moat visé reste :

> **documents → compréhension des obligations → Need Graph → externalisabilité → timing → ICP fit → action commerciale → apprentissage**

La donnée d'adjudication brute, le nom du gagnant ou le simple CPV doivent être considérés comme des commodités d'entrée. La valeur propriétaire doit se concentrer sur la compréhension, la qualification et la transformation en action.

---

# 20. Décision recommandée

Après le go-live, construire d'abord les trois epics P1 et mesurer leur effet avant d'élargir le produit :

1. **Commercial Mobilisation Window** ;
2. **Externalisability / Delivery Dependency** ;
3. **Next Best Commercial Action**.

Ces trois fonctions exploitent directement les actifs déjà présents dans Kivou et renforcent le positionnement sans imposer de dépendance à un fournisseur externe.

Ensuite seulement :

4. utiliser le feedback existant pour améliorer le ranking sous contrôle ;
5. distribuer les signaux vers les CRM ;
6. enrichir les gagnants si les conditions fournisseur le permettent ;
7. étendre le moteur aux expirations et autres moments du cycle de vie.

**Aucune de ces fonctions ne doit devenir un prérequis au lancement initial.**