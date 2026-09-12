# Enrichissement économique et budgets modèles — design

Date : 12 septembre 2026

Statut : approuvé par Rodrigue

Périmètre : `supplier_directory`, fournisseurs de modèles et vues founder associées

## 1. Objectif et ordre obligatoire

La chaîne d'enrichissement doit devenir mesurable et bornée avant tout nouvel
appel payé. L'ordre de livraison est impératif :

1. plafonds journaliers persistants par usage et affichage Système ;
2. entrée d'enrichissement inférieure à 4 000 tokens ;
3. routeur par usage et journal append-only de chaque appel ;
4. benchmark des trois modèles économiques sur 30 fiches ;
5. projection de coût, puis attente d'un nouveau go avant toute passe sur les
   281 fiches sans jugement ou les titulaires de comptes actifs.

Aucun enrichissement de production ni purge de file n'est autorisé pendant les
quatre premières étapes.

## 2. Registre central des appels modèles

Tous les appels OpenRouter passent par un adaptateur commun dans
`signals.documents.providers`. Il reçoit un usage fermé :

- `enrichment_judge` ;
- `enrichment_arbiter` ;
- `for_you` ;
- `hermes` ;
- `document_classifier`.

La configuration associe à chaque usage un modèle et un plafond journalier via
des variables d'environnement explicites. Les valeurs par défaut sont :

| Usage | Plafond quotidien |
|---|---:|
| `enrichment_judge` | 2,00 USD |
| `enrichment_arbiter` | 1,00 USD |
| `for_you` | 1,00 USD |
| `hermes` | 1,00 USD |
| `document_classifier` | 1,00 USD |

La journée budgétaire commence à minuit dans `Europe/Zurich`, y compris lors
des changements d'heure. Une variable absente prend la valeur par défaut du
tableau ; une valeur fournie négative, non numérique ou non finie rend la
configuration invalide. Aucun usage n'est implicitement illimité.

Le plafond de `enrichment_judge` est un coupe-circuit, pas un objectif de
dépense ni un rythme de traitement. La configuration est relue au démarrage de
chaque lot : un opérateur peut relever ou abaisser un plafond dans le fichier
d'environnement puis démarrer le lot suivant, sans reconstruire ni redéployer
l'application. La valeur capturée au démarrage est figée pour toute la durée du
lot et enregistrée avec celui-ci ; une modification en cours de lot ne change
pas rétroactivement ses admissions.

### 2.1 Tables

`model_daily_budget` contient une ligne par `(budget_date, timezone, usage)` :
plafond configuré, montant réservé, montant débité, compteurs d'appels terminés,
échoués et refusés, et dates de création/mise à jour.

`model_call_journal` contient une ligne immuable par tentative : identifiant,
usage, date budgétaire, SIREN optionnel, identifiant de lot optionnel, modèle
demandé et observé, état, tokens d'entrée et sortie, coût réel, réservation,
latence, catégorie d'échec, validité JSON, dates de début et de fin. Le contenu
des prompts et réponses n'y est jamais stocké.

`supplier_directory` continue de porter le dernier jugement pour les lectures
rapides. Chaque remplacement doit être précédé par la finalisation d'une ligne
du journal liée au SIREN ; un nouveau jugement ne peut donc plus effacer la
trace du précédent.

### 2.2 Admission concurrente et arrêt propre

Avant l'appel, une transaction verrouille la ligne journalière et réserve un
coût conservateur calculé depuis la taille UTF-8 de l'entrée, le maximum de
sortie et les tarifs configurés du modèle. L'appel est refusé avant le réseau si
`dépensé + réservé + nouvelle réservation > plafond`.

Après réponse, la même ligne est verrouillée : la réservation est libérée et le
coût OpenRouter réel est débité. Une réponse dont le coût dépasse la réservation
est conservée et ferme immédiatement l'usage pour le reste de la journée. Les
workers reçoivent `DAILY_MODEL_BUDGET_EXHAUSTED`, terminent proprement le lot et
n'entament aucun nouvel appel. Les timeouts, HTTP non 200 et JSON invalides
finalisent aussi le journal et libèrent leur réservation ; le coût réel est
enregistré lorsqu'OpenRouter le fournit.

Le benchmark publie, par modèle et globalement, `somme des réservations / somme
des coûts réels`. Si ce ratio dépasse 3, la formule ou ses tarifs sont recalibrés
sur les observations, puis le benchmark de mesure de réservation est rejoué
avant toute passe. L'ajustement ne peut jamais rendre la réservation inférieure
au coût maximal observé pour une entrée de taille équivalente ; il évite qu'une
borne théorique grossière bloque artificiellement des appels économiques.

## 3. Entrée économique

Le paquet transmis au juge respecte `docs/kivou-enrichissement-economique.md`.

- Serper : au plus dix résultats avec titre, URL et extrait uniquement.
- Annuaires : jamais de texte brut ; seulement les trois champs extraits par
  regex `site`, `phone`, `director`, marqués comme indices non fiables.
- Site officiel candidat : accueil et contact rendus par un renderer injecté,
  réduits au titre, au texte nettoyé de `<main>` limité à 800 caractères, aux
  e-mails et téléphones extraits en clair.
- Navigation, footer, scripts, styles, SVG et instructions contenues dans les
  pages sont exclus du texte utile.
- Le catalogue métier devient la seule liste des clés et noms de familles, sans
  NAF, descriptions ni exemples.
- La sortie est un JSON strict de 300 tokens maximum.

Le premier tour rend au maximum deux pages officielles. Si un site est trouvé
mais aucune adresse n'est suffisamment sûre, le juge peut demander une seule
URL supplémentaire appartenant au domaine retenu. La liste noire reste
applicable et le total rendu reste borné à trois pages. Il n'existe qu'un second
tour.

La mesure compare exactement les mêmes 20 paquets avant et après réduction.
Elle publie moyenne, médiane, minimum, maximum et p95. La condition de livraison
est une moyenne strictement inférieure à 4 000 tokens d'entrée.

## 4. Routage et arbitrage

Chaque usage lit son modèle depuis une variable dédiée :

- `KIVOU_MODEL_ENRICHMENT_JUDGE` ;
- `KIVOU_MODEL_ENRICHMENT_ARBITER` ;
- `KIVOU_MODEL_FOR_YOU` ;
- `KIVOU_MODEL_HERMES` ;
- `KIVOU_MODEL_DOCUMENT_CLASSIFIER`.

Le transport OpenRouter, le `response_format` JSON strict et le journal sont
communs. Les contrats métier et parseurs restent propres à chaque usage.

Le juge économique est appelé une fois. Sonnet, configuré par défaut comme
`anthropic/claude-sonnet-4.6`, arbitre seulement si :

- le JSON du juge est invalide ;
- la confiance site est inférieure à 0,8 ;
- la confiance adresse est inférieure à 0,8.

L'arbitre reçoit le même paquet réduit et la sortie brute bornée du juge, jamais
un nouveau corpus web. Si le JSON du juge est invalide, sa sortie est traitée
comme donnée non fiable. La politique déterministe finale garde seule le droit
de retenir site, e-mail, famille, dirigeant et téléphone.

## 5. Benchmark de sélection

Le corpus contient 30 fiches déjà jugées par Sonnet, dont ALYA BATIMENT,
ENT A. GIRARD, LE NY, DENIOS, MATERIAUX DE HAUTE DURANCE,
ADIL EL MANSOURI et BOURGEOIS. La vérité manuelle est figée avant les appels et
versionnée sans données personnelles inutiles.

Les candidats, dans l'ordre de préférence, sont :

1. `mistralai/mistral-small` ;
2. `google/gemini-flash-lite` ;
3. `deepseek/deepseek-chat`.

Ils reçoivent les mêmes octets d'entrée réduite, la même température, le même
schéma et 300 tokens maximum. Pour DeepSeek, chaque nom de dirigeant devient un
jeton opaque stable (`DIR_1`, `DIR_2`, etc.) ; la sélection est restaurée
déterministiquement après validation, sans transmettre le nom au modèle.

Le rapport donne par candidat : accord site, adresse, famille et nom, accord
global sur l'ensemble des champs, JSON invalides, latence médiane, coût pour 30
et projection pour 20 000, ainsi que le ratio réservé/réel. Les valeurs nulles
sont des réponses évaluées, pas des champs ignorés. Le premier candidat
atteignant au moins 95 % d'accord global
est retenu ; Mistral gagne toute égalité. Si aucun ne passe, Sonnet reste juge
avec l'entrée réduite. Le modèle sélectionné n'est configuré en production
qu'après publication du rapport.

Le benchmark est lui-même soumis aux plafonds. Un budget épuisé suspend le run,
qui reprend uniquement les appels manquants depuis son manifeste.

## 6. Console founder

La section Système expose pour la journée Europe/Zurich : usage, modèle,
plafond, réservé, dépensé, restant, appels terminés, échecs et refus. Elle lit la
base avec le rôle founder existant et n'effectue aucune mutation.

La vue Prospection → Annuaire affiche le coût du dernier lot, son nombre de
fiches et son coût moyen, à partir du journal. Aucun secret, prompt ou contenu de
réponse n'est exposé.

## 7. Étape postérieure soumise à un nouveau go

Après sélection, une commande de planification en lecture seule calcule :

- les fiches sans jugement au moment de la mesure ;
- les titulaires distincts rattachés à au moins un compte actif ;
- les doublons entre les deux cohortes ;
- le taux d'arbitrage observé ;
- le coût projeté bas, central et haut sous les plafonds configurés.

Le résultat est présenté à Rodrigue. Aucun replay et aucune purge ne sont lancés
avant son nouveau go. Après autorisation, la purge de `winner_enrichment_job`
ne cible que les titulaires sans aucun compte actif et reste auditée avec les
comptages avant/après. La file de prospection est régénérée sans envoi.

## 8. Vérification

Les tests hors ligne couvrent les frontières de journée Zurich, le passage
heure d'été/hiver, les réservations concurrentes, l'arrêt budgétaire, la
libération après erreur, le journal immuable, les cinq usages, la réduction des
pages, la liste noire, le second tour unique, le masquage DeepSeek, le calcul du
score et les vues founder.

Les appels du benchmark sont les seuls appels réseau autorisés avant le nouveau
go. La recette staging de la console comprend captures desktop et mobile. La
production ne peut être déployée que depuis `main`, après fusion et CI verte.
