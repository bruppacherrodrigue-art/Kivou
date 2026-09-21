# Milo Mail A1 : échantillon d'organisations en staging

Milo Mail est le produit ; Milo est son agent. Seul Kivou détient les réponses
Apollo, les preuves MX et les correspondances administratives. A1 observe
uniquement des organisations : zéro recherche de personne, dirigeant, contact ou
adresse, zéro enrichissement, zéro mutation Instantly et zéro e-mail.

## Autorisation et périmètre

L'autorisation opérateur du 22 septembre 2026 plafonne cette phase
`COVERAGE_A1_SAMPLE` à 81 **nouveaux** appels Organization Search et 81 crédits
prépayés, sur la base PostgreSQL staging isolée `kivou_milomail_census_a0`.
Les neuf pages A0 sont réutilisées depuis le cache. Le total cumulé ne peut
dépasser 90 pages. Le coût **incrémental autorisé** est `0.00 CHF` : cela ne
signifie pas que le coût comptable d'un crédit est nul. Aucun achat, top-up ou
dépassement n'est autorisé. Le secret physique partagé `KIVOU_APOLLO_API_KEY`
n'est autorisé qu'ici, avec un permis expirant sous quatre heures ; il reste
interdit pour B0 et tout enrichissement. La base applicative staging et la
production restent hors périmètre.

L'[Organization Search Apollo](https://docs.apollo.io/reference/organization-search)
coûte un crédit par page et expose au maximum 500 pages ou 50 000 résultats
par recherche. Le plan A1 n'ajoute aucune partition. Chaque partition existante
garde la page 1 d'A0, puis sélectionne au plus neuf pages distinctes parmi
`2..min(total_pages,500)`. La graine publique est le SHA-256 de la version du
plan et de l'identifiant du permis. L'intervalle est découpé en blocs de
profondeur disjoints ; une page est tirée de manière déterministe dans chaque
bloc. Les pages, blocs, empreinte du cache A0 et empreinte du plan sont
persistés **avant** l'émission du permis et le premier appel payant.

## Préparation et commandes

Utiliser un checkout temporaire de ce code sur le serveur staging, sans
déployer le service. Charger les secrets depuis `/etc/kivou/staging.env` et
`/etc/kivou/acquisition-shadow.env` dans le processus seulement. Construire
`KIVOU_DATABASE_URL` avec `sqlalchemy.URL.set(database=...)` après avoir
vérifié que l'URL de départ désigne `kivou_staging`. Ne jamais imprimer ni
enregistrer l'URL, la clé ou les réponses brutes. Stocker les JSON opérateur
hors Git, en mode `0600`.

```text
KIVOU_ACQUISITION_ENVIRONMENT=STAGING
MILOMAIL_CENSUS_ENABLED=true
MILOMAIL_CENSUS_AUTHORIZATION_REF=<référence de ce permis>
MILOMAIL_CENSUS_APOLLO_SECRET_REF=KIVOU_APOLLO_API_KEY
MILOMAIL_CENSUS_MAX_PARTITIONS=9
MILOMAIL_CENSUS_MAX_PAGES=90
MILOMAIL_CENSUS_MAX_CANDIDATES=2250
MILOMAIL_CENSUS_MAX_ENRICHMENTS=0
MILOMAIL_CENSUS_MAX_APOLLO_CREDITS=90
MILOMAIL_CENSUS_MAX_COST_CHF=0
MILOMAIL_CENSUS_CHF_PER_CREDIT_CEILING=0
MILOMAIL_COMPANY_STATUS_ENABLED=true
MILOMAIL_COMPANY_STATUS_MAX_REQUESTS=600
MILOMAIL_COMPANY_STATUS_RATE_LIMIT=60
```

Ces plafonds cumulatifs incluent A0. Pour un solde insuffisant, créer un plan
avec moins de pages **avant** le permis et réduire proportionnellement pages,
candidats et crédits : `9 + nouvelles_pages`, `25 × pages`, `pages`.
Les défauts du projet restent désactivés et à zéro.

Sur la seule base A0 autorisée à `0073`, appliquer l'upgrade additif `0074`.
Le downgrade doit être testé sur une autre base jetable, jamais sur les
résultats A0/A1.

```bash
uv run milomail-census migrate-authorized \
  --database-authorization <autorisation-base-renouvelée.json> \
  --acknowledge-migration
uv run milomail-census plan-sample --census-id <id-A0> \
  --permit-id <id-permis-A1-public> --max-new-pages 81 \
  --database-authorization <autorisation-base-renouvelée.json>
uv run milomail-census preflight --phase COVERAGE_A1_SAMPLE --census-id <id-A0> \
  --permit-id <id-permis-A1-public> \
  --database-authorization <autorisation-base-renouvelée.json> \
  --pricing <attestation-prépayée-A1.json> \
  --probe-official-source --probe-apollo-free
uv run milomail-census issue-permit --permit <permis-A1.json> \
  --database-authorization <autorisation-base-renouvelée.json> \
  --pricing <attestation-prépayée-A1.json>
uv run milomail-census preflight --phase COVERAGE_A1_SAMPLE --census-id <id-A0> \
  --permit-id <id-permis-A1-public> \
  --database-authorization <autorisation-base-renouvelée.json> \
  --pricing <attestation-prépayée-A1.json> \
  --probe-official-source --probe-apollo-free
uv run milomail-census run --phase COVERAGE_A1_SAMPLE --census-id <id-A0> \
  --permit-id <id-permis-A1-public> --program-config <programme.json> \
  --database-authorization <autorisation-base-renouvelée.json> \
  --pricing <attestation-prépayée-A1.json> \
  --authorize-paid-apollo --probe-official-source --probe-apollo-free
```

L'attestation utilise `PREPAID_SHARED_POOL`, `price_per_credit=null`,
`max_incremental_charge_chf=0`, `auto_top_up_allowed=false`,
`overage_allowed=false`, la catégorie `ORG_SEARCH=1 crédit/page`, le solde
daté et les limites observées. Le permis reprend `sample_plan_hash`,
`configuration_hash` du préflight, `phase=COVERAGE_A1_SAMPLE`, les neuf
partitions et `max_pages=max_credits=81`, `max_candidates=2025`, ou les caps
réduits du plan. Son `database_id` doit être celui de la base isolée ; sa
durée est au plus quatre heures. Aucune valeur secrète ne figure dans le
permis. Le plan est immuable après émission.

La commande `run` capture le solde et le compteur Organization Search avant
le premier appel. Chaque réponse Apollo terminée est enregistrée dans le
ledger, mise en cache et checkpointée. Une sonde gratuite vérifie ensuite le
solde et le compteur avant la prochaine recherche. Une divergence ou une
réponse Apollo ambiguë arrête le run ; le pool partagé ne permet jamais
d'attribuer aveuglément un delta global à Milo Mail. Un retry facturable
réserve un nouvel appel et un nouveau crédit dans les mêmes plafonds.

## Suivi, reprise et arrêt

```bash
uv run milomail-census status --census-id <id-A0>
uv run milomail-census report --census-id <id-A0> --public-aggregate \
  --sample-permit-id <id-permis-A1-public>
uv run milomail-census reconcile-usage --shared-pool --census-id <id-A0> \
  --permit-id <id-permis-A1-public> --pool-before <solde-avant> \
  --pool-after <solde-après> \
  --database-authorization <autorisation-base-renouvelée.json>
uv run milomail-census resume --phase COVERAGE_A1_SAMPLE --census-id <id-A0> \
  --permit-id <id-permis-A1-public> --program-config <programme.json> \
  --database-authorization <autorisation-base-renouvelée.json> \
  --pricing <attestation-prépayée-A1.json> \
  --authorize-paid-apollo --probe-official-source --probe-apollo-free
uv run milomail-census revoke-permit --permit-id <id-permis-A1-public> \
  --database-authorization <autorisation-base-renouvelée.json>
```

Ne lancer `resume` que si le permis est encore valide, les compteurs gratuits
se réconcilient avec le ledger et le run n'est pas en revue. Une page
checkpointée ou une réponse complète en cache ne déclenche pas de nouvel
appel. Une opération potentiellement facturée sans réponse exploitable exige
une revue manuelle : ne jamais répéter automatiquement cette page. Révoquer
le permis en fin de run ou à l'arrêt d'urgence. Pour couper les accès,
désactiver également `MILOMAIL_CENSUS_ENABLED` dans l'environnement éphémère.
`purge-cache --acknowledge-cache-purge` reste soumis à la durée de conservation
configurée et ne supprime pas suppressions, permis et reçus d'usage. Conserver
le cache A1 autorisé pour l'analyse et la reprise ; ne pas le commiter.

## Lecture du rapport et suite B0

Le rapport sépare les totaux déclarés par Apollo, les lignes réellement
observées, les organisations uniques, les estimations et les deux comptes de
contacts/adresses vérifiés qui restent à **zéro**. Les poids de strate
proviennent des totaux Apollo par partition ; les intervalles de Wilson à
95 % décrivent les proportions de strate. Les bornes pondérées utilisent
une correction de Bonferroni sur les neuf intervalles de strate. La correction
de doublons utilise
le taux mesuré. Les secteurs peuvent se chevaucher, les pages restent
classées par Apollo et une recherche ne donne accès qu'à 500 pages. Les
fourchettes extrapolées au-delà de cette limite sont des scénarios, pas des
intervalles garantis. Un volume d'organisations ne représente pas un nombre
d'adresses disponibles. L'ancienne fourchette de 15 000–50 000 adresses
reste une hypothèse historique non mesurée.

B0 sera une mission distincte, sans envoi. Pour une marge de ±10 points à
95 % au pire cas `p=0.5`, il faut environ 97 observations indépendantes **par
taux** (dirigeants identifiables puis adresses professionnelles vérifiées
parmi eux). Un plan prudent choisira au moins 200 entreprises Google Workspace
avec activité confirmée, stratifiées et dédupliquées, puis ajustera le lot
pour obtenir au moins 97 dirigeants observables. La
[recherche de personnes](https://docs.apollo.io/reference/people-api-search)
est documentée à zéro crédit, sans adresses ; l'[enrichissement de
personne](https://docs.apollo.io/reference/people-enrichment) peut coûter
1 à 9 crédits/personne sans cascade. Pour 200 personnes, le pire plafond
initial documenté serait 1 800 crédits, à revalider avec le plan et les
options exactes (aucun téléphone, e-mail personnel ou cascade). B0 exige une
clé Milo Mail dédiée, un permis et un budget séparés, le contrôle des rôles
fondateur/dirigeant/owner, la suppression avant enrichissement, une preuve
professionnelle et la décision déterministe SEND théorique/HOLD/NO_SEND.
Aucun endpoint B0 n'est appelé pendant A1.
