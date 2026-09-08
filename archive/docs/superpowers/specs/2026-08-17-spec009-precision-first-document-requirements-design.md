# SPEC-009 — Precision-First Document Requirements

**Kivou — conception validée le 17 août 2026**

## 1. Objectif

Reprendre la chaîne Document Intelligence de SPEC-006 et dépasser honnêtement
95 % de précision sur les exigences d'exécution auto-acceptées, sans modifier
les corpus ni les golds après observation des résultats.

La stratégie est explicitement *precision-first*. Une exigence ambiguë est
envoyée en revue, même si elle est probablement vraie. Le rappel et le volume
d'auto-acceptation sont secondaires à la sûreté du fait présenté au client.

La doctrine produit reste celle de FR-DCE-FINAL : une exigence auto-acceptée doit
être autoportante. La phrase citée doit permettre à elle seule d'identifier le
fournisseur comme porteur de l'obligation. Le voisinage peut invalider une
exigence, mais ne peut pas fournir un acteur ou un référent absent de la phrase.

## 2. Contraintes non négociables

- Le passage cité est retrouvé exactement dans les blocs sources ; sinon il
  n'existe aucune exigence.
- Le modèle classe un candidat extrait ; il ne rédige jamais l'exigence.
- Une panne, un désaccord ou une réponse invalide produit `review_required`,
  jamais un verdict métier implicite.
- `AUTO_DOCUMENT_REQUIREMENTS_ENABLED` reste à `False` jusqu'à réussite de tous
  les gates d'activation.
- FR-DCE-FINAL reste inchangé et devient un test de régression connu. Il ne
  constitue plus une preuve de généralisation puisque ses onze erreurs ont été
  étudiées pour concevoir cette version.
- Le nouveau held-out est annoté, arbitré et figé avant le premier appel modèle.
- Une fois la configuration candidate gelée, aucun prompt, seuil, modèle, gold ou
  corpus ne change pendant l'évaluation officielle.

## 3. Architecture

La nouvelle cascade est une version expérimentale placée après le pipeline
SPEC-006 existant. Elle ne modifie pas immédiatement le chemin MVP.

```text
CandidateSnapshot + Evidence
              |
              v
      EligibilityGuard
              |
              v
    DeepSeek primary model
              |
              v
  Sentence-only verifier (A)
              |
              v
 Contextual legal verifier (B)
              |
              v
       AcceptancePolicy
          /         \
 AUTO_ACCEPTED   REVIEW_REQUIRED
```

### 3.1 `EligibilityGuard`

La garde détecte des risques structurels observables et ne déclare jamais une
exigence vraie. Elle produit une collection de motifs typés et auditables.

Risques bloquant l'auto-acceptation :

- pronom sujet sans antécédent interne explicite ;
- démonstratif dépendant d'une liste ou d'une phrase précédente ;
- anaphore temporelle ou logique dépendante du contexte ;
- phrase, puce ou énumération grammaticalement fragmentaire ;
- sujet inanimé portant seul la modalité ;
- tournure impersonnelle sans agent explicite ;
- acteur multiple ou mixte ;
- fournisseur bénéficiaire d'une action portée par l'acheteur ;
- phase ou type de section déjà exclus par le `PhaseGuard` de SPEC-006.

Les règles doivent être génériques. Chaque motif comporte des exemples positifs
et des contre-exemples afin d'interdire les raccourcis lexicaux.

### 3.2 Modèle primaire

DeepSeek reste le primaire économique à fort rappel. Il conserve sa mission de
classification initiale. Sa confiance déclarative n'est jamais utilisée comme
une probabilité ni comme un gate d'acceptation.

### 3.3 Vérificateur A — phrase seule

Le vérificateur A ne reçoit ni phrase précédente, ni phrase suivante. Il répond
à quatre questions fermées :

1. La phrase est-elle grammaticalement complète et autoportante ?
2. Quel segment exact de la phrase nomme l'acteur obligé ?
3. Cet acteur est-il le fournisseur chargé d'accomplir l'action ?
4. Quel segment exact porte la modalité normative ?

Une réponse positive sans segments justificatifs présents dans la phrase est
invalide. Un pronom sans antécédent interne, un acteur implicite ou une réponse
ambiguë force `review_required`.

### 3.4 Vérificateur B — contexte juridique

Le vérificateur B reçoit la phrase, son voisinage non fiable et les métadonnées
documentaires. Il tranche séparément :

- offre contre exécution ;
- formation du contrat contre exécution du contrat ;
- fournisseur contre acheteur, tiers ou acteur inconnu ;
- prescription normative contre information descriptive.

Le contexte est une source non fiable et reste encadré comme tel. Il peut
révéler une contradiction ou imposer une abstention. Il ne peut jamais réparer
l'absence d'acteur ou d'autoportance constatée par le vérificateur A.

Le fournisseur du vérificateur est interchangeable derrière le protocole de
domaine existant. Le modèle retenu est choisi sur les corpus DEV, puis son
identifiant exact et sa version sont gelés.

### 3.5 `AcceptancePolicy`

L'auto-acceptation exige simultanément :

- évidence exacte valide ;
- aucune garde d'inéligibilité ;
- phrase autoportante selon la vue A ;
- fournisseur explicitement nommé comme acteur obligé ;
- modalité normative explicitement localisée ;
- phase d'exécution certaine selon la vue B ;
- accord compatible du primaire et des deux vérifications ;
- réponses complètes et conformes au schéma fermé ;
- modèle et configuration identiques à la version gelée.

Tout autre résultat devient `review_required`. Il n'existe aucun fallback
silencieux vers un modèle, un prompt ou une politique différents.

## 4. Confiance système

Le champ de confiance autodéclaré par un modèle est exclu des décisions : R5 a
montré qu'il n'était pas corrélé à la justesse.

Une classe de confiance système est calculée à partir de faits observables :

- acteur fournisseur explicitement localisé ;
- modalité explicitement localisée ;
- absence de risque déterministe ;
- accord des analyses indépendantes ;
- stabilité sur le protocole de sélection DEV.

Le sous-ensemble `high` doit contenir zéro faux positif lors de chaque gate. La
classe de confiance, sa justification et la version de la politique sont
conservées avec la décision.

## 5. Sélection du contradicteur

Les candidats compatibles avec une sortie structurée stricte sont comparés sur
les corpus DEV historiques avec le même contrat de sortie et la même politique.
Le choix tient compte de :

- précision globale et par frontière juridique ;
- stabilité sur plusieurs passages identiques ;
- erreurs d'acteur et d'autoportance ;
- taux de réponses invalides ;
- calibration empirique ;
- latence et coût.

Le benchmark de sélection ne touche ni FR-DCE-FINAL pour régler la solution, ni
le nouveau held-out. Le modèle, son identifiant fournisseur, ses paramètres, le
prompt et le parseur sont enregistrés dans un manifeste gelé.

## 6. Gestion des erreurs

Tous les échecs sont explicites et fermés :

- timeout ou transport : reprises bornées et idempotentes, puis revue ;
- crédit, quota ou rate limit : catégorie d'infrastructure, puis revue ;
- JSON ou schéma invalide : échec de schéma, puis revue ;
- version de modèle inattendue : run refusé ;
- preuve ou localisation invalide : candidat bloqué ;
- désaccord sémantique : revue ;
- absence de trace complète : candidat non publiable.

Une reprise technique d'un run officiel ne peut rejouer que les appels manquants
avec les octets d'entrée, versions et paramètres originaux. Elle ne peut modifier
aucune décision déjà obtenue.

## 7. Tests avant évaluation

### 7.1 Tests déterministes

- un test unitaire par motif de la garde ;
- paires minimales, dont « le titulaire doit livrer » contre « il doit livrer » ;
- voix active, passive, bénéficiaire et impersonnelle ;
- sujets inanimés, acteurs multiples et obligations de l'acheteur ;
- tests métamorphiques : remplacer l'acteur explicite par un pronom impose la
  revue ;
- contre-exemples empêchant un filtre lexical ;
- invariants d'évidence et de provenance existants.

### 7.2 Régressions d'infrastructure

- réponse 402 jamais comptée comme erreur sémantique ;
- budget de sortie incompatible avec le reasoning refusé avant appel ;
- réponse tronquée ou invalide envoyée en revue ;
- mapping de preuve longueur-préservé ;
- contenu documentaire hostile jamais traité comme une instruction ;
- version ou manifeste différents refusés pendant un run gelé.

### 7.3 Régression FR-DCE-FINAL

FR-DCE-FINAL doit atteindre :

- précision observée strictement supérieure à 95 % ;
- zéro faux positif dans la classe système `high` ;
- évidence exacte à 100 % ;
- zéro extrait inventé ;
- nombre d'auto-acceptations et rappel publiés, sans minimum de rappel.

Les onze erreurs historiques doivent être envoyées en revue par des motifs
génériques. Ce résultat reste nécessaire mais ne prouve pas la généralisation.

## 8. Held-out aveugle et gate d'activation

Le held-out d'activation utilise de nouvelles consultations françaises et est
dédoublonné contre tous les corpus existants par `consultation_id`, SHA-256 du
document et hash de phrase.

Sa composition doit couvrir au moins 25 consultations et plusieurs familles de
documents, notamment CCTP, CCAP, BPU et annexes. Deux adjudications indépendantes
sont réalisées avant tout appel modèle ; les désaccords sont arbitrés, journalisés
et le corpus final est figé par SHA-256.

Le corpus doit être assez grand pour permettre au pipeline de produire au moins
le nombre d'auto-acceptations requis par le gate statistique. Aucun candidat
n'est ajouté après observation d'une sortie modèle.

Conditions cumulatives d'activation :

- précision observée strictement supérieure à 95 % ;
- borne basse à 95 % de l'intervalle de Wilson supérieure ou égale à 95 % ;
- zéro faux positif dans la classe système `high` ;
- évidence exacte à 100 % ;
- zéro extrait inventé ;
- couverture d'au moins 10 consultations ;
- métriques également publiées par consultation et famille documentaire.

À titre de dimensionnement, la borne de Wilson exige au minimum 73 succès sur 73
auto-acceptations, environ 109 succès sur 110 avec une erreur, ou 140 succès sur
142 avec deux erreurs. La constitution vise donc au moins 75 auto-acceptations
si le système ne commet aucune erreur, et doit être agrandie avant gel si le gold
montre que ce rendement est structurellement impossible.

Un seul run officiel est autorisé. Une mauvaise métrique est un échec de version,
pas une invitation à modifier le gold ou à relancer. Toute version suivante
retourne en DEV et devra être évaluée sur un futur corpus aveugle distinct.

## 9. Activation du MVP

La réussite de FR-DCE-FINAL et du held-out aveugle autorise une décision de
supervision ; elle ne modifie pas automatiquement le produit. L'activation exige
un changement explicite et testé du contrat MVP qui maintient actuellement :

```python
AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False
DOCUMENT_REQUIREMENT_UNAVAILABLE = "unavailable"
```

Le rapport d'activation doit inclure le manifeste gelé, les SHA des corpus et
golds, les métriques complètes, les coûts, les latences, les incidents et la
distribution des abstentions.

## 10. Hors périmètre

- modifier ou ré-adjudiquer FR-DCE-FINAL ;
- améliorer le rappel au détriment de la précision ;
- résoudre les pronoms par le voisinage pour auto-accepter une phrase ;
- exposer les sorties expérimentales au Need Graph avant activation ;
- construire une interface de revue humaine ;
- étendre l'acquisition à de nouveaux portails européens.
