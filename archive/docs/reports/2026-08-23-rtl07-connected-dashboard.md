# RTL-07 — Dashboard SaaS connecté orienté action

## Résultat

La route authentifiée `/app/dashboard` devient l’accueil normal des comptes
dont l’onboarding est prêt. Elle compose les contrats SaaS existants sans
endpoint agrégé, migration, persistance ou règle backend supplémentaire.
Toutes les routes précédentes restent disponibles.

La route `/app` et une connexion sans destination profonde conduisent au
dashboard. Une destination profonde demandée reste prioritaire pour un compte
prêt. Un compte incomplet rejoint l’onboarding avant tout appel du dashboard ;
un `401` suit le parcours commun de session expirée.

## API réutilisées

- `GET /signals?limit=3&offset=0` fournit les occasions dans l’ordre du serveur.
- `GET /signals/{signal_key}` est appelé au plus une fois pour le premier item
  dont le feed fournit `locked: false`. Son détail décide seul de la présence
  d’une `company_key`.
- `GET /target-icps` fournit les profils, leur ordre, leur état et
  `plan_limit`.
- `GET /billing/status` fournit la formule, le statut, `billing_action`, les
  valeurs Discovery, `target_icps_over_limit`, la cadence permise et
  `scheduled_cancellation_at`.
- `GET /notification-preferences` fournit le choix persistant
  `email_enabled`.

Le dashboard ne précharge pas `GET /companies/{company_key}` : il lie la clé
opaque autorisée vers la fiche officielle existante. Aucun contrat n’a été
ajouté, car les API auditées suffisent à tous les blocs approuvés.

## Autorisation et concurrence

Les cartes de signal réutilisent `SignalCard` et sa séparation entre item
déverrouillé et teaser verrouillé. Un teaser ne rend ni entreprise, ni montant,
ni marché, ni besoin, ni preuve, ni source, ni `company_key`. Aucun détail
n’est demandé pour un item verrouillé et aucune clé entreprise n’est reconstruite
depuis un nom ou un identifiant public.

Chaque ressource possède son propre chargement, résultat, erreur et retry.
Après chaque succès courant du feed, une seule relecture de
`GET /billing/status` est lancée. Des générations de requêtes empêchent une
ancienne réponse de remplacer cette relecture. Un retry du feed invalide le
détail entreprise, resélectionne le premier item serveur accessible, borne le
nouveau détail à un appel et ne relance ni les ICP ni les préférences d’alertes.

Aucune donnée entreprise ou `company_key` n’est écrite dans `localStorage` ou
`sessionStorage`.

## Blocs et actions

- **Occasions :** extrait de trois items au plus, ordre et contenu serveur
  inchangés, actions « Examiner le signal » et « Voir tout le feed ».
- **Ciblages :** tous les ICP `active`, dans l’ordre serveur, avec résumé,
  territoires, seuil éventuel, `plan_limit` et appartenance à
  `target_icps_over_limit`. Une seule action globale mène à `/app/icps`.
- **Formule et accès :** formule, statut localisé, valeurs exactes de
  déblocages utilisés, restants et limite. Le CTA est uniquement la traduction
  de `billing_action` et mène à `/app/billing`. Seul
  `scheduled_cancellation_at`, lorsqu’il existe, produit un état programmé ;
  aucun changement de formule de la PR nº58 n’est anticipé.
- **Alertes :** `email_enabled` décrit l’activation choisie et
  `entitlements.alert_cadence` la capacité de la formule. Une préférence en
  erreur laisse la cadence disponible visible sans affirmer l’activation.
  « Prioritaire » ne devient jamais « temps réel ». L’action mène à
  `/app/notifications`.
- **Fiche entreprise :** le bloc existe seulement pour un signal serveur
  accessible. Une clé renvoyée par son détail mène à
  `/app/companies/:companyKey`. « Fiche indisponible » est réservé au succès
  d’un détail accessible sans clé ; une erreur propose uniquement un retry
  local.

Une erreur du feed ne masque pas les autres sources, une erreur billing ne
masque pas les signaux, et une erreur des préférences ne masque pas les ICP.
Aucune erreur ne substitue un faux plan, compteur, statut, ICP, cadence ou
entreprise.

## Validation

- Backend de base : `uv run pytest` — `4115 passed, 2 skipped` ; aucun fichier
  backend n’est modifié.
- Frontend : typecheck et lint verts ; `376 passed` sur la suite Vitest ; build
  Vite vert.
- Navigateur réel : 1440, 1024, 768, 390 et 320 px vérifiés avec quatre ICP
  actifs. À chaque largeur, `scrollWidth` égale la largeur du viewport, les
  quatre profils restent rendus, et la page contient exactement un `main` et
  un `h1`.
- Clavier : focus visible dès le skip link, menu mobile ouvert avec Entrée et
  fermé avec Échap ; toutes les actions exposent un nom accessible. Aucun
  avertissement ni erreur console n’a été observé.
- FR et EN, session expirée, onboarding incomplet, ordre serveur, accès
  verrouillé, erreurs partielles, retries, historique précédent/suivant et
  interdiction de stockage sont couverts par les tests du dashboard.

Les validations complètes sont rejouées après synchronisation finale avec
`origin/main` avant ouverture de la PR.

## Limites restantes

- Le dashboard ne recherche pas une autre fiche si le premier signal accessible
  n’en fournit pas ; cette borne évite le N+1 demandé par RTL-07.
- Il n’affiche que l’extrait initial de trois occasions ; le feed complet reste
  l’autorité et l’action dédiée.
- Il ne fournit aucun changement programmé de formule, le SHA de base ne
  contenant que `scheduled_cancellation_at`.
- RTL-07 reste « livré en PR » jusqu’à sa fusion dans `main` et la CI verte du
  SHA final de `main`.

## Périmètre confirmé

Aucun fichier backend, moteur de signaux, matching, scoring, Policy Engine,
Acquisition Engine, Hermes, Campaign Factory, Apollo, Instantly, Contact
Discovery, Supplier Discovery, Company Research, personnalisation, Stripe,
checkout, portail, entitlement, pricing, page publique, légal ou OPS n’est
modifié. Aucun paiement, e-mail, campagne, lead, mailbox ou appel fournisseur
n’est créé.
