# Milo Mail — recensement Apollo en SHADOW

**État livré :** code préparatoire, désactivé et non exécuté contre Apollo.
Milo Mail est le produit ; Milo est son agent intégré. Kivou possède les
prospects, scores, suppressions, décisions et coûts. Aucun prospect ni
identifiant Apollo/Instantly ne passe au produit Milo Mail ; Kivou ne reçoit
aucun contenu Gmail, token OAuth ni détail d'audit de messagerie.

## Architecture et frontière d'envoi

`milomail-census` est une commande de Kivou. Elle réutilise
`ApolloOrganizationSearchClient`, `ApolloCompanyResearchClient`,
`ApolloContactDiscoveryClient`, `MailProviderDetector`,
`ProgramDiscoveryPipeline` et `MilomailShadowRuntime`. Les requêtes Apollo de
recherche et d'enrichissement traversent le registre de réservation de crédits
avant l'appel. Les candidats Google Workspace repassent dans la recherche
entreprise/contact, le classificateur professionnel, le score, la suppression
Milo Mail et la politique française B2B existants. Les autres fournisseurs
reçoivent une décision du ruleset Milo Mail sans enrichissement payant.

L'ancien `ProgramDiscoveryPipeline.run()` reste limité aux transports Apollo
mockés ; le recensement emploie son évaluateur de candidat avec des adaptateurs
Apollo budgétés. La commande n'importe aucun client Instantly utilisable :
`MilomailShadowRuntime` reçoit un fournisseur qui lève une erreur à tout
accès. Le programme doit être `enabled=false` et `campaign_mode=SHADOW`.
Un `SEND` dans le rapport est **théorique** et ne crée ni campagne ni lead
Instantly.

## Partitions et couverture

Le plan forme trois tranches d'effectif sans chevauchement pour chaque secteur
configuré : 1–3, 4–6, 7–10 dans la configuration actuelle. Les filtres envoyés
à Apollo sont ceux de l'adaptateur Kivou : `organization_locations[]=France`,
`organization_num_employees_ranges[]` et `q_organization_keyword_tags[]`.
Chaque signature inclut la version des filtres et l'empreinte du programme.
Les secteurs peuvent se recouper ; une table d'occurrences mesure ces doublons.
Une identité globale relie les identifiants d'entreprise Apollo, les domaines
normalisés et les HMAC d'adresses vérifiées, sans adresse en clair dans le
rapport. Le premier fait conservé est daté ; les faits incertains restent
`UNKNOWN`/`HOLD`.
Le fournisseur MX du domaine de l'entreprise et celui de l'adresse du
destinataire sont conservés séparément : une entreprise Google Workspace peut
avoir un contact `@gmail.com` qui reste `NO_SEND` dans ce pilote.

Apollo limite [Organization Search à 50 000 fiches affichables par recherche,
100 par page, 500 pages](https://docs.apollo.io/reference/organization-search).
Ce plafond n'est ni contourné ni présenté comme une taille du marché. Le code
prend `apollo_per_page` dans la version du programme (25 dans l'exemple actuel) ;
à 25 par page, 500 pages ne couvrent que 12 500 fiches d'une partition. Une
autre taille de page exige une nouvelle version de programme et un nouveau plan.
L'ordre des résultats Apollo n'est pas garanti par l'adaptateur actuel ; les
recouvrements observés et les partitions incomplètes doivent donc rester
visibles dans le rapport. Le code signale `APOLLO_COVERAGE_LIMIT` si le total
annoncé l'atteint, si Apollo
indique des résultats partiels, ou si la dernière page dépasse 500. Une limite
locale atteinte avant la dernière page laisse une partition incomplète. Les
requêtes par mots-clés peuvent avoir des recouvrements ou manquer des acteurs
du segment ; le rapport mesure les doublons observés mais ne peut pas prouver
une couverture exhaustive. La fourchette 15 000–50 000 adresses demeure une
**hypothèse non mesurée** jusqu'à un recensement Apollo autorisé et achevé.

## Crédits et coûts

La [tarification API Apollo](https://docs.apollo.io/docs/api-pricing) indique
actuellement 1 crédit/page d'entreprises, 1 crédit/entreprise enrichie,
0 crédit pour People Search et jusqu'à 9 crédits/personne enrichie sans
waterfall. Les paramètres d'enrichissement personnel, téléphone et waterfalls
sont désactivés dans l'adaptateur Kivou. Ces réservations sont des **plafonds
prudents**, pas des crédits effectivement débités. Les plans Apollo
anciens peuvent différer ; vérifier le plan du workspace et le prix CHF/crédit
avant autorisation. Les [limites de taux](https://docs.apollo.io/reference/rate-limits)
sont propres au plan et à l'équipe. Un 429 est réessayé au plus une fois si
`Retry-After` est écoulé et si les plafonds restants le permettent.

| Variable | Défaut | Effet |
| --- | ---: | --- |
| `MILOMAIL_CENSUS_ENABLED` | `false` | Bloque `run` et `resume`. |
| `MILOMAIL_CENSUS_MAX_PARTITIONS` | `0` | Nombre de partitions démarrables. |
| `MILOMAIL_CENSUS_MAX_PAGES` | `0` | Réservations de pages, retries inclus. |
| `MILOMAIL_CENSUS_MAX_CANDIDATES` | `0` | Places réservées avant chaque page. |
| `MILOMAIL_CENSUS_MAX_ENRICHMENTS` | `0` | Entreprises et personnes enrichies. |
| `MILOMAIL_CENSUS_MAX_APOLLO_CREDITS` | `0` | Crédits maximaux réservés. |
| `MILOMAIL_CENSUS_MAX_COST_CHF` | `0` | Coût maximal réservé. |
| `MILOMAIL_CENSUS_CHF_PER_CREDIT_CEILING` | `0` | Prix plafond explicite par crédit. |

Les coûts unitaires sont aussi configurables avec
`MILOMAIL_CENSUS_CREDITS_ORG_PAGE` (minimum 1),
`MILOMAIL_CENSUS_CREDITS_ORG_ENRICH` (minimum 1),
`MILOMAIL_CENSUS_CREDITS_PERSON_ENRICH_MAX` (minimum 9) et
`MILOMAIL_CENSUS_CREDITS_PEOPLE_SEARCH` (minimum 0).
`MILOMAIL_CENSUS_RETENTION_DAYS` fixe à 30 jours par défaut le délai maximal
du cache de réponses personnelles Apollo. Le lancement exige aussi
`MILOMAIL_CENSUS_AUTHORIZATION_REF`, la clé dédiée
`MILOMAIL_CENSUS_APOLLO_API_KEY`, les clés HMAC de suppression Kivou, et
`--authorize-paid-apollo`. Aucune absence de variable ne vaut « illimité ».

Chaque appel potentiellement facturable est réservé en base avant le réseau.
Les résultats terminés sont mis en cache pour la reprise ; une réponse
ambiguë garde sa réservation et passe en `REVIEW_REQUIRED`. Le compteur de
coût n'est jamais réinitialisé sur `resume`, qui exige la même version de
programme et les mêmes plafonds. Une augmentation de budget exige une nouvelle
revue et un nouveau plan versionné. Le rapport distingue toujours
`apollo_credits_reserved_upper_bound` et `apollo_credits_actual` (inconnu tant
qu'il n'est pas rapproché avec la consommation du workspace Apollo), ainsi que
coût réservé et coût réel. Aucun clic ni contact trouvé n'est compté comme
conversion payante Milo Clean.

Après un recensement autorisé, le coût réel peut être saisi une seule fois :

```bash
uv run milomail-census reconcile-usage --census-id <id-du-plan> \
  --actual-credits <credits-confirmés> --actual-cost-chf <montant-confirmé> \
  --usage-evidence-ref <référence-opaque> \
  --database-authorization <autorisation-base.json> \
  --acknowledge-exclusive-attribution
```

Cette commande s'emploie après un run terminé ou arrêté pour revue, ou pour
documenter un plan jamais lancé (toute charge inattendue déclenche une revue) ;
un run actif ou simplement en pause ne peut pas recevoir un reçu final. La référence
doit renvoyer à une facture ou à un relevé conservé hors du rapport, sans nom,
adresse ni secret. L'[API Apollo de consommation](https://docs.apollo.io/reference/view-credit-usage-stats)
donne un total de workspace, pas une ventilation Milo Mail ; elle ne suffit
donc pas seule à attribuer des crédits au census si d'autres activités Apollo
sont simultanées. L'opérateur doit vérifier une période exclusive ou une
preuve équivalente avant l'acquittement. Le reçu est immuable et rejouable de
façon idempotente ; toute divergence exige une revue manuelle. Un coût ou un
nombre de crédits supérieurs au plafond réservé met le run en
`REVIEW_REQUIRED`. Avant cette saisie, les valeurs réelles et le coût réel
par `SEND` théorique restent `null`.

## Préparation réelle et commandes

La migration `0072_milomail_census_readiness` ajoute une preuve officielle
conservée, des permis d'exécution et un rattachement des réservations Apollo.
Le [runbook de préparation](16-milomail-census-readiness.md) détaille le
préflight, l'autorisation de base, l'attestation du prix, les deux phases et
la révocation. L'ancien callback `UNKNOWN` a été remplacé, pour le census,
par l'API française officielle et un rapprochement conservateur. Un nom et
une ville concordants restent au maximum `PROBABLE_MATCH` ; un SIREN déjà
corroboré ou une concordance unique de nom, ville et code postal peut prouver
l'activité et contribuer à `SEND` théorique.

`plan`, `status`, `report`, `purge-cache` et `reconcile-usage` conservent leurs
contrats. `run` et `resume` exigent maintenant `--phase COVERAGE` ou
`--phase ENRICHMENT`, un permis distinct, une autorisation de base et un prix
attesté. Ils ne peuvent appeler Apollo sans les vérifications de compte à
zéro crédit et de la source officielle. Le programme reste désactivé, en
`SHADOW`, sans accès mutable à Instantly.

## Reprise, arrêt et revue

`status` affiche les pages et crédits réservés ainsi que l'état des
partitions. `report` expose le funnel, les reason codes et les ventilations
par secteur, taille, localisation, rôle, fournisseur et partition. Une page
terminée est rejouée depuis son cache après une interruption, sans second
appel facturable. Si l'appel était réservé mais sans réponse persistée, la
reprise s'arrête en `REVIEW_REQUIRED` : rapprocher l'usage Apollo et les logs
du fournisseur avant toute décision manuelle. Ne jamais effacer une ligne du
registre pour « débloquer » le coût. Un 429 avec échéance future passe en
pause et ne peut être réessayé avant cette échéance.

Pour arrêter immédiatement un futur recensement, supprimer l'autorisation
opérationnelle (`MILOMAIL_CENSUS_ENABLED=false`) ou la clé dédiée, puis arrêter
le processus. Cela ne touche ni les suppressions Kivou ni le programme Milo
Mail. Toute tentative de lancer le census sans les sept plafonds positifs ou
sans la clé échoue avant le premier appel Apollo. Vérifier les lignes
`REVIEW_REQUIRED` et la consommation fournisseur avant de redémarrer.

Les réponses People Search et People Enrichment sont mises en cache dans
Kivou pour une reprise sans nouvel enrichissement. Une exécution `COMPLETE`
efface aussitôt ces copies ; le compteur de contacts reste agrégé. Pour un
run arrêté ou en revue, lancer avant la fin de la période de rétention :

```bash
uv run milomail-census purge-cache --census-id <id-du-plan> \
  --database-authorization <autorisation-base.json> --acknowledge-cache-purge
```

La commande refuse un run incomplet avant son délai de rétention ; après ce
délai elle efface les copies personnelles et met le run en revue, car un appel
payant purgé ne peut plus être rejoué. Les fiches de contact Kivou et les
suppressions restent gouvernées par leurs règles de conservation existantes.

## Autorisation future et limites

Avant le **premier** appel réel, obtenir un budget explicite en CHF et crédits,
un prix plafond par crédit vérifié sur le plan Apollo, une clé Apollo dédiée,
une base migrée et sauvegardée, toutes les versions HMAC de suppression, et
une revue de conformité FR B2B. Vérifier le profil de filtres et les plafonds
avec une prévisualisation `plan`. Le nombre 15 000–50 000 ne doit pas guider
un débit automatique. Aucun envoi, export Instantly, domaine d'expédition,
landing ou déploiement n'est activé par ce runbook.

Le rapport actuel et les tests sont exclusivement synthétiques. Les champs de
coût réel restent `null` sans mesure fournisseur. Le nombre `SEND` théorique
reste sensible aux preuves d'activité, à la landing française, à la santé de
l'expéditeur, aux plafonds d'envoi et à la suppression ; il ne se confond pas
avec les adresses vérifiées. Les bases contenant des contacts Apollo restent
dans Kivou et relèvent de sa politique de conservation et d'accès.
