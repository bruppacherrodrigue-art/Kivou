# Corrections frontend 001 à 003 et Card Intelligence × QA Signals

Statut : approuvé par le propriétaire produit le 30 août 2026.

## Sources normatives

Ce design traduit :

- l'issue produit #119 ;
- la passation technique #127 ;
- `CONTRIBUTING.md` ;
- les drafts #121, #122, #123, #124 et #125, utilisées uniquement comme
  références techniques.

Le SHA de départ audité était
`a1ffc5021f1d981059f4e9017d295683a389605b`. Avant le premier changement
produit, `main` a avancé à
`9b73cc370ef6657e0a53a9fb53fde1d226500fc9` avec #115. Ce delta isole la
console fondateur, ajoute son build à la CI et ne change ni les contrats
Signaux, ni les entreprises, ni la persistance métier. La branche de fondation
a donc été recréée proprement depuis `9b73cc3`, sans rebase ni force-push. La
migration courante reste `0027_signal_notes`. Chaque création de branche et
chaque fusion reverra la tête distante avant d'agir.

Les drafts ne sont pas des dépendances Git. Aucune ne sera fusionnée, rebasée
ou réécrite. Leurs éléments utiles seront réimplémentés dans de nouvelles
branches. Les anciennes PR seront fermées seulement après publication de leur
remplacement et reliées explicitement à celui-ci.

## Objectif et résultat livré

Livrer une pile propre qui :

1. persiste et publie hors requête des présentations de carte versionnées ;
2. refuse toute présentation non prouvée ou incohérente ;
3. corrige la navigation master–detail Entreprises ;
4. transforme le Dashboard en vue d'ensemble factuelle de quatre à six
   attributions ;
5. transforme Signaux en feed et détail commerciaux cohérents ;
6. déploie uniquement le SHA final fusionné de `main` sur staging.

Le déploiement staging reste limité à l'architecture et aux fallbacks
factuels. Aucun contenu intelligent `PASS/FULL` ne sera activé.

## Limites fermes

Sont hors périmètre :

- tout déploiement ou changement de production ;
- toute modification du matching ou du classement du Signal Engine ;
- toute mutation d'un provider, d'une campagne, d'un prospect ou de Stripe ;
- toute configuration live d'un LLM, d'un prompt ou d'un worker IA ;
- toute réutilisation de credentials, modèles, prompts ou workers Hermes ;
- Apollo comme source produit client ;
- toute reconstruction frontend à partir d'un titre administratif brut.

Les GET frontend et API ne peuvent jamais appeler un provider, un modèle ou un
service de génération. Cette propriété est structurelle et testée, pas une
convention de configuration.

## Topologie Git et PR

La pile est logique, mais les PR ne restent pas empilées simultanément. Chaque
PR est créée depuis le dernier `main` fusionné et validé :

1. **Fondation Card Intelligence × QA Signals** — remplace #123 ;
2. **Garde-fous de véracité Signaux** — remplace #121 ;
3. **C002 Entreprises attributaires** — remplace #122 ;
4. **C001 Dashboard** — remplace #124 ;
5. **C003 Signaux commerciaux** — remplace #125.

Après chaque squash merge : relire l'état GitHub, vérifier le SHA et l'arbre
résultants, attendre la CI `push` de ce SHA, puis seulement créer la branche
suivante. Il n'y a aucun force-push, même si GitHub n'applique pas actuellement
de protection technique sur `main`. L'interdiction de `CONTRIBUTING.md` reste
absolue.

## Architecture transverse

### Couches et responsabilités

Les données restent séparées en quatre couches :

1. **faits source** : attribution, acheteur, attributaire, montant, lieu, dates
   qualifiées et références de preuve ;
2. **identité entreprise** : projection publique officielle et autorisée ;
3. **présentation publiée** : résumé, importance commerciale, adéquation,
   timing, action et rôles cibles ;
4. **vue frontend** : composition stricte de faits et présentation, sans règle
   métier ni génération locale.

Card Intelligence prépare un candidat. Les validateurs déterministes le
contrôlent. QA Signals rend une décision. Le publisher écrit un artefact
immuable ou refuse. QA Signals ne modifie jamais le texte et ne complète jamais
un champ manquant.

### Contrat versionné

`CardPresentationPayload` est un contrat fermé (`extra=forbid`) comportant au
minimum :

- `schema_version` ;
- `variant` ;
- `headline` et `award_summary` ;
- les conclusions commerciales facultatives ;
- des catégories de besoin et rôles issus d'énumérations fermées ;
- les inconnues explicites ;
- une liste bornée de claims.

Chaque claim, y compris une recommandation, porte au moins une
`evidence_ref`. Les faits et inférences non prouvés sont invalides. Une
inférence porte en plus une confiance explicite. Les identifiants de claim sont
bornés et uniques dans le payload.

Les seules associations publiables sont :

- `PASS` avec `FULL` ;
- `FALLBACK` avec `FACTUAL_FALLBACK`.

`REGENERATE` et `REVIEW` peuvent être conservés comme tentatives privées, mais
ne franchissent jamais l'API client. `FACTUAL_FALLBACK` contient uniquement des
faits et aucun rôle cible, besoin déduit, timing commercial, urgence ou action
inventée.

### Entrée contrôlée

`PresentationInput` est construit côté serveur depuis :

- le compte propriétaire ;
- le signal matérialisé courant et non invalidé ;
- sa révision et la révision ICP active exacte ;
- la langue `fr` ou `en` ;
- l'attributaire et l'acheteur dans leurs rôles source exacts ;
- des dates typées séparément : attribution, notification du contrat et
  publication ;
- les faits source et leurs références de preuve ;
- les besoins réellement liés au profil de ciblage courant.

L'empreinte canonique inclut tous ces champs. Une révision de signal, d'ICP ou
de langue produit une entrée distincte ; une publication obsolète ne peut donc
pas redevenir courante silencieusement.

### Persistance additive `0028_card_presentation`

La migration crée une table dédiée sans modifier la sémantique de tables
existantes. En particulier, les changements sans rapport observés dans le
draft #123 sur `acquisition_event.payload` et
`acquisition_personalization_artifact.input_snapshot` ne sont pas repris.

Chaque ligne conserve notamment :

- identifiant opaque d'artefact ;
- compte, signal, ICP, langue et type d'artefact ;
- révisions signal et ICP ;
- version monotone et empreinte d'entrée ;
- contrat, payload, décision QA et raisons ;
- versions du schéma, de la politique QA et du renderer/générateur ;
- provider, modèle et prompt éventuels, tous nuls pour un fallback factuel ;
- dates de création, publication et remplacement.

Une contrainte unique protège les versions. Un index unique partiel protège la
publication active par compte, signal, ICP, langue et type. La migration monte
depuis `0027_signal_notes` et son downgrade est testé uniquement sur une base
jetable ; le rollback staging ne l'exécutera pas automatiquement.

### Publication et concurrence

La publication s'effectue dans une seule transaction :

1. verrouiller le signal courant sur PostgreSQL ;
2. vérifier propriétaire, statut ICP et révisions ;
3. valider le payload contre les faits source ;
4. allouer la version suivante ;
5. remplacer l'ancienne publication et insérer la nouvelle ;
6. laisser l'index unique fermer toute course restante.

Un conflit, une révision obsolète ou une intégrité non démontrée échoue fermé.
Les tests couvrent l'interleaving de publications, la compilation PostgreSQL du
verrou et la contrainte finale de publication active.

### Pipeline hors GET

Les protocoles de génération et de QA restent provider-neutral. Les tests
peuvent utiliser des fakes, mais l'application web ne construit ni provider ni
worker. Le pipeline futur est :

`input → generator → validation déterministe → QA → publication`.

Sur staging, seul ce chemin est autorisé :

`input → renderer factuel déterministe → validation → FALLBACK publié`.

Le renderer possède sa propre version. Il n'a ni modèle, ni prompt, ni
credential et ne peut produire que `FACTUAL_FALLBACK`.

### Lecture API, batch et artefact épinglé

Le feed calcule les bindings autorisés et charge toutes leurs présentations
dans une seule requête account-scoped. Les teasers verrouillés sont exclus de
cette lecture et n'ont pas de clé `presentation` dans leur JSON.

Une présentation publique contient `artifact_id`, `version`, `status`,
`schema_version`, `published_at` et `content`. Une forme JSON invalide, une
association statut/variant inconnue, une mauvaise langue ou une révision
obsolète est omise ; le frontend ne reçoit aucune reconstruction de secours.

Pour éviter qu'une publication concurrente fasse diverger le feed et le
détail :

- le feed expose l'identifiant de l'artefact immuable affiché ;
- la requête de détail lancée depuis ce feed épingle cet identifiant ;
- le serveur ne le restitue que s'il appartient au même compte, signal, ICP,
  langue et aux révisions toujours courantes ;
- une nouvelle publication peut devenir courante sans modifier l'ancien
  artefact déjà choisi ;
- le frontend affiche la présentation du détail seulement si identifiant et
  version correspondent exactement au feed.

Un deep-link sans sélection préalable résout la publication courante, puis
l'épingle pour la session du workspace.

### Vérité sémantique

Les validateurs et tests garantissent :

- acheteur et attributaire jamais inversés ;
- une date de publication jamais appelée date d'attribution ;
- les dates FR, EN et abrégées reliées au bon champ source ;
- les collisions de noms et les fragments ambigus rejetés ;
- aucune adéquation « Matériaux → personnel » ;
- aucun rôle, personne, contact, urgence ou échéance inventé ;
- aucune conclusion commerciale sans besoin ICP structuré et preuve ;
- aucune publication liée à une révision ICP obsolète ;
- aucune fuite inter-tenant.

## Adaptateur frontend partagé

Un parseur runtime commun reçoit la présentation API. Il vérifie les champs
requis, les bornes, les clés fermées, les enums, les preuves et l'association
statut/variant. Il produit l'un de ces états :

- présentation complète publiée ;
- fallback factuel publié ;
- présentation absente ou invalide.

Les composants n'accèdent jamais directement au JSON brut et ne retombent
jamais sur `contract.title`, `event.headline` ou une autre copie administrative
pour fabriquer un résumé. Les faits structurés autorisés — montant, acheteur,
attributaire, lieu et date qualifiée — peuvent être composés autour de
l'artefact, mais pas reformulés en nouvelle claim.

## PR 1 — Fondation Card Intelligence × QA Signals

Cette PR contient :

- contrats, protocoles et validateurs ;
- table et migration `0028` ;
- store de tentatives et de publications ;
- batch read et lecture par identifiant épinglé ;
- renderer factuel déterministe ;
- backfill CLI borné à 50 éléments par invocation et à la limite de scan
  existante ;
- intégration feed/détail sans provider ;
- tests adversariaux backend ;
- runbook versionné du déploiement staging complet.

Le backfill est idempotent par empreinte, mais republie si la ligne courante est
malformée ou incohérente. Une erreur d'élément utilise un savepoint et produit
un résultat non nul sans annuler les éléments sûrs précédents.

La baseline du SHA initial a révélé un test flaky préexistant :
`test_a_locked_teaser_never_names_the_company` recherchait la sous-chaîne
générique `AG` dans la sérialisation complète et pouvait la trouver dans un
`target_icp_id` aléatoire. La PR le remplace par des assertions sur la surface
publique et les vraies valeurs sensibles. Le contrat de confidentialité reste
plus strict, sans dépendre du hasard d'un identifiant opaque.

## PR 2 — Garde-fous de véracité Signaux

Cette PR porte les protections utiles du draft #121 sans conserver son résumé
brut provisoire :

- premier besoin ciblé, non vide et prouvable seulement ;
- adéquation générique masquée si aucune raison concrète n'existe ;
- libellé exact de la nature de date ;
- absence transparente de rôle ou contact ;
- CTA uniquement vers une capacité existante ;
- FR et EN symétriques.

Elle ne publie pas encore une conclusion `FULL` et n'utilise aucun champ brut
comme substitut de présentation.

## PR 3 — C002 Entreprises attributaires

### Données

Le feed déverrouillé expose la clé entreprise autorisée grâce à une résolution
backend bornée et batchée des identités. Le frontend n'appelle plus le détail
de chaque signal pour découvrir l'entreprise.

Le profil entreprise enrichit ses signaux liés avec les présentations publiées
au moyen d'une seule lecture batch. Il ne reconstruit aucun résumé depuis le
titre administratif. Les autres faits de la fiche restent issus du contrat
officiel existant.

### Desktop

- workspace sous l'en-tête à hauteur disponible ;
- liste et détail avec défilements verticaux indépendants ;
- position de liste conservée ;
- changement de sélection : ancien détail effacé, état de chargement visible,
  détail seul replacé en haut ;
- réponse obsolète ignorée ;
- carte active distinguée autrement que par la couleur.

### Mobile et accessibilité

- mono-pane plein écran sous 1180 px ;
- URL canonique `/app/companies/:companyKey?signal=:signalId` ;
- Retour aux attributions restaurant sélection, focus et position de liste ;
- focus du détail sur son titre après sélection clavier ;
- historique navigateur et redimensionnement conservant la sélection ;
- états vide, chargement, partiel et erreur visibles et annoncés.

Les libellés normatifs sont « Entreprises attributaires », « Attributions
détectées », « Contexte de l'attribution » et « n attributions ».

## PR 4 — C001 Dashboard

La section devient « Attributions récentes pertinentes » et affiche les quatre
à six premiers éléments dans l'ordre serveur. Chaque carte présente dans le
même ordre :

1. entreprise attributaire ;
2. résumé factuel publié ou fallback transparent ;
3. montant, date qualifiée, acheteur et localisation ;
4. raison ICP concrète seulement si elle est publiée ;
5. CTA « Voir l'attribution ».

Le résumé est borné visuellement à deux ou trois lignes. Les valeurs absentes
portent un libellé exact. Le compteur n'invente pas un total : il affiche le
total réellement fourni ou un nombre partiel explicitement qualifié.

Cette PR n'ajoute aucun appel détail et consomme les présentations déjà
batchées par le feed.

## PR 5 — C003 Signaux commerciaux

Le workspace réutilise le comportement master–detail de C002 :

- scroll indépendant desktop ;
- mono-pane mobile ;
- URL `/app/signals/:signalId` ;
- sélection, Retour, Suivant, focus et scroll restaurés ;
- chargement local et protection contre les réponses tardives.

Les cartes et le détail utilisent le parseur commun et l'artefact épinglé. La
liste ne montre jamais une conclusion que le détail contredit. Le détail
sépare faits, inférences et recommandations. Les titres administratifs peuvent
rester disponibles dans une section factuelle/source clairement secondaire,
jamais comme headline ou résumé commercial.

Le CTA Entreprise utilise exclusivement la route canonique
`/app/companies/:companyKey?signal=:signalId`. Sans clé autorisée, aucun lien
n'est inventé.

Les goldens Signaux desktop et mobile sont recapturés depuis le résultat final,
comparés par Playwright et inspectés visuellement avant fusion.

## Tests adversariaux obligatoires

La pile conserve ou recrée au minimum :

- rôles acheteur/attributaire inversés ;
- dates françaises, anglaises et abrégées ;
- collisions de noms, fragments et nombres non-date ;
- révisions ICP obsolètes, profil inactif et signal invalidé ;
- isolation tenant ;
- concurrence de version et de publication ;
- JSON malformé, clés inconnues et statut/variant incohérent ;
- claim sans preuve ;
- fallback strictement factuel et borné ;
- teaser verrouillé sans `presentation` ;
- absence de provider/generator/QA pendant les GET ;
- une seule lecture batch de présentations pour le feed et les profils ;
- même identifiant et même version entre feed et détail ;
- clics rapides, réponses tardives, deep-links, historique, focus et scroll ;
- parité FR/EN et absence de reconstruction depuis le titre brut.

## Validation de chaque PR

Avant push :

```text
uv run pytest -q
uv run ruff check .
cd frontend
npm test -- --run
npm run test:visual
npm run build
npx tsc -b
npm run lint
```

Les captures desktop et mobile sont ouvertes et inspectées, pas seulement
générées. Le rapport de PR documente la base, les dépendances, les risques, les
limites et les captures vues.

Après push, les jobs backend et frontend doivent contenir des étapes réellement
allouées et exécutées. Une conclusion GitHub sans étapes ou un échec avant
runner ne compte pas. La PR n'est fusionnée qu'après les deux jobs verts.

## Déploiement staging du `main` final

Le déploiement n'a lieu qu'après la CI `push` verte du SHA final de `main`.

### Sauvegarde et migration

1. vérifier hostname, SHA courant, services et symlinks ;
2. créer un dump PostgreSQL staging horodaté avec permissions protégées ;
3. enregistrer taille et SHA-256 ;
4. vérifier le catalogue `pg_restore` et restaurer dans une base jetable pour
   contrôler la lisibilité et la révision ;
5. préparer la release backend immuable du SHA final ;
6. confirmer `alembic current == 0027_signal_notes` ;
7. appliquer `0028_card_presentation` depuis cette release ;
8. confirmer une tête unique et les contraintes attendues.

### Backend et frontend

Le backend suit le runbook blue/green existant : candidat nginx isolé, service
green, probes, lien `/srv/kivou/app` atomique, redémarrage et vérifications.

Le frontend suit la procédure opérateur retrouvée et désormais versionnée :

1. construire `frontend/dist` depuis un checkout détaché du SHA final ;
2. créer `/srv/kivou/releases/frontend-<UTC>-<SHA12>` ;
3. transférer le contenu et vérifier `index.html` et les assets ;
4. créer un lien temporaire vers la release ;
5. remplacer `/srv/kivou/frontend` avec `mv -Tf` ;
6. sonder les routes publiques et applicatives ;
7. restaurer atomiquement l'ancien lien si ces sondes échouent.

Backend et frontend doivent porter le même suffixe SHA. Aucun fichier de nginx
n'est modifié si sa configuration reste inchangée.

### Backfill factuel

Un compte QA est accepté seulement s'il est vérifié sur le serveur comme compte
staging autorisé. Son identifiant et ses credentials ne sont ni demandés ni
imprimés dans le chat.

Le backfill s'exécute séparément :

1. français, limite explicite au plus 50 ;
2. inspection du résultat et des lignes publiées ;
3. anglais, même limite explicite ;
4. nouvelle inspection.

Les lignes doivent avoir `FALLBACK/FACTUAL_FALLBACK`, un renderer déterministe
versionné et des champs provider/modèle/prompt/QA-provider nuls. Les compteurs
de mutation provider restent à zéro.

### Smokes et captures staging

Avec la session QA protégée :

- Dashboard, Entreprises et Signaux en desktop et mobile ;
- feed/détail et identité d'artefact ;
- deep-links et actualisation ;
- Retour, Suivant, focus et restauration du scroll ;
- teaser verrouillé et absence de fuite ;
- erreurs partielles et relances locales ;
- console et réseau sans erreur inattendue ;
- aucune requête provider pendant les GET ;
- bundles réellement servis correspondant à la release finale.

Les captures sont enregistrées comme preuves et inspectées visuellement.

### Rollback

Le rollback applicatif conserve les releases précédentes et remet les symlinks
backend/frontend vers elles. Il vérifie ensuite API, nginx et routes. La
migration `0028`, additive, n'est pas downgradée automatiquement. Une
incompatibilité nécessitant un downgrade de données devient un incident séparé
et bloque la poursuite.

## Statut explicite de l'IA

À la fin de cette livraison :

- architecture provider-neutral : **présente** ;
- QA Signals contractuelle et fail-closed : **présente** ;
- renderer factuel hors GET : **actif uniquement pour le compte QA staging** ;
- génération LLM : **désactivée** ;
- provider/model/prompt IA approuvés : **aucun** ;
- worker IA live : **aucun** ;
- artefacts `PASS/FULL` en staging : **aucun** ;
- production : **non touchée**.

L'activation future exige une décision séparée sur le provider, des prompts
versionnés, une QA configurée, un worker hors GET, un jeu d'évaluation, des
seuils d'acceptation et un rollout contrôlé.
