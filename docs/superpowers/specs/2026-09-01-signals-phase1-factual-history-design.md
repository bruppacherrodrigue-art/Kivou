# Signaux Phase 1 — historique et enrichissement factuel

**Date :** 2026-09-01
**Branche :** `fix/signals-phase1-factual-history`
**Base :** `68888298c5e4f2a4bb1ea8d34eaf4c156ee586ae`

## Périmètre

Cette phase rend la page Signaux utilisable avec les seuls faits publics déjà
ingérés par Kivou. Elle ne choisit aucun modèle, ne crée aucun prompt, ne lance
aucun provider, n'active ni Hermes ni l'Acquisition Engine et ne publie aucune
analyse commerciale. Les présentations Card Intelligence existantes restent un
contrat optionnel pour une phase ultérieure, mais la page Signaux n'en dépend
plus pour son titre, son résumé ou son état de complétude.

## Causes racines observées

1. `Companies.tsx` utilise deux panneaux à défilement indépendant, remet
   uniquement le détail en haut avec `useLayoutEffect`, puis focalise le titre
   avec `preventScroll`. `SignalsFeed.tsx` utilise au contraire la grille
   globale en flux de page, focalise sans `preventScroll` et appelle
   `scrollIntoView`; le navigateur remonte donc la fenêtre et déplace aussi la
   liste.
2. Le frontend force `freshness=new` sur la première page et sur « Charger
   plus ». Il ne lit `freshness=all` que dans une boucle cachée servant à
   résoudre un deep-link; les résultats historiques trouvés ne rejoignent
   jamais la liste visible.
3. Le backend sait paginer par offset, mais présélectionne au plus 500 lignes
   dans l'ordre de matérialisation, puis trie en mémoire par statut de
   fraîcheur. Cet ordre ne garantit pas un parcours complet et stable de
   l'historique par date d'attribution.
4. Les droits d'historique existent déjà côté serveur (Discovery : signaux
   accordés; Essential : 30 jours; Pro : 365 jours; Scale : tout l'historique
   persisté). La réponse du feed ne les explique toutefois pas explicitement à
   l'interface.
5. Le nom, les identifiants, le pays, l'adresse et parfois le site officiel du
   gagnant sont déjà conservés dans `saas_company`, à partir des avis publics.
   La route GET crée encore cette projection à la demande et aucun état durable
   n'explique si l'indexation est en attente, partielle ou en erreur.
6. La liste et le détail prennent leur titre principal dans un artefact de
   présentation optionnel. En son absence, ils affichent « Présentation non
   publiée » au lieu d'une hiérarchie factuelle construite par le serveur.
7. Les preuves publiques existent dans le détail, mais elles sont regroupées
   loin des faits et l'identité gagnante n'expose pas clairement sa source et
   sa date de vérification.

## Décisions d'architecture

### Navigation

La page Signaux reprend le modèle visible d'Entreprises : grille contenue,
panneaux liste/détail défilant séparément, position de la liste intacte,
`scrollTop=0` appliqué uniquement au détail et focus avec `preventScroll`. Sous
1 180 px, un seul panneau est visible à la fois et le bouton Retour restaure la
ligne active. La sélection et tous les filtres restent dans l'URL afin de
respecter deep-links, précédent/suivant et rechargement.

### Historique et pagination

L'API ajoute un mode explicite `view=recent|history`, sans casser le contrat
`freshness` existant. Le mode historique utilise un curseur opaque versionné et
un ordre déterministe :

1. date réelle d'attribution si elle existe;
2. sinon date de notification du contrat;
3. sinon date de publication;
4. date décroissante, type de date explicite, puis `signal_key` croissant.

Le curseur parcourt la requête possédée par le compte et non une liste déjà
rendue. Les filtres sont appliqués côté serveur avant toute donnée protégée :
période sur cette date utile, zone publiée, statut courant et préfixe CPV comme
classification sectorielle factuelle. Le serveur continue de produire des
teasers verrouillés hors droit et n'y ajoute ni titre de marché, ni entreprise,
ni `presentation`.

La réponse expose les droits d'historique et les filtres permis par le niveau
du plan. Le frontend rend cette autorité telle quelle; il ne recalcule ni
fenêtre d'accès ni plan d'upgrade.

### Titre et hiérarchie factuels

Le backend publie une projection `factual_display` issue uniquement des champs
structurés de l'avis : nom gagnant, objet, montant, lieu, acheteur et date utile.
Elle contient un titre, un résumé court, le type de date et un état de
complétude. Aucun texte n'est lu dans `analysis` ou dans une présentation pour
construire ces champs.

Les fallbacks restent bornés : entreprise + objet, entreprise + montant,
entreprise + acheteur, puis « Attribution publiée ». Les identifiants et
détails techniques sont placés dans un `<details>` fermé « Sources et
vérification ».

### Winner Enrichment

`saas_company` reste l'unique entité d'entreprise SaaS. Une table additive de
travail, liée au signal et à son empreinte d'identité, conserve les états
`pending`, `in_progress`, `completed`, `partial` et `failed`, les tentatives et
un code d'erreur borné. Elle ne stocke pas une seconde entreprise.

La matérialisation ne fait qu'indexer l'identité et mettre le travail en file de
façon idempotente. Un worker explicite, sans démarrage automatique et sans
réseau, consolide en lot les champs déjà publiés par les connecteurs autorisés.
Il converge par empreinte exacte, journalise son résultat et peut être relancé.
Les GET lisent en lot les clés et états déjà persistés; ils ne résolvent rien,
n'appellent aucun provider et ne font aucun N+1.

Chaque projection gagnante expose la source publique, l'URL HTTPS sûre, la
référence d'avis, le connecteur et la date observée. Les champs non publiés
(activité, code d'industrie, effectif notamment) restent explicitement
indisponibles. Aucun fournisseur payant ou scraping n'est ajouté.

### Migration et backfill

La migration `0030_winner_enrichment` est additive. Elle crée uniquement la
table de travail et ses contraintes. Son backfill insère en lot une ligne par
signal indexable : les entreprises déjà matérialisées deviennent
`completed`/`partial` selon leurs faits réellement stockés; les autres restent
`pending`. Le traitement peut ensuite être repris par le worker explicite.

Le rollback applicatif revient au code précédent sans effacer la table. Le
downgrade Alembic existe pour les tests et environnements jetables, mais ne doit
pas être lancé automatiquement sur une base partagée.

## Contrats de sûreté

- aucun import de `company_research`, Apollo, Hermes, Acquisition ou d'un
  client HTTP dans la frontière `companies`;
- aucun appel de provider pendant un GET;
- aucun contenu commercial, besoin probable, rôle cible ou recommandation dans
  la page Signaux de cette phase;
- aucune confusion entre `procedure_buyers` et `awardee_parties`;
- `event.clock` reste l'autorité sur le libellé de date;
- tous les filtres et accès sont account-scoped et appliqués côté serveur;
- un teaser verrouillé reste dépourvu de `presentation` et de faits protégés;
- les erreurs de curseur et d'état échouent fermé;
- les requêtes entreprise et enrichissement sont batchées.

## Vérification attendue

Les tests unitaires et d'intégration couvriront l'ordre et les curseurs, les
filtres, les droits, l'isolation compte, les états d'enrichissement, les
preuves, les titres incomplets, l'absence de contenu commercial et de provider
sur GET. Les tests frontend couvriront navigation, défilements indépendants,
focus, historique, filtres, pagination, erreurs et régression Entreprises. Une
vérification Playwright inspectera les cas riche, ancien, incomplet et les états
d'enrichissement sur desktop et mobile.
