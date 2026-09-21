# Milo Mail : phase A à zéro crédit

Milo Mail est le produit ; Milo est l'agent intégré. Kivou garde les données
Apollo et les décisions. Le produit Milo Mail ne reçoit ni prospects ni
identifiants fournisseur. Aucun contenu Gmail, token OAuth ou résultat d'audit
détaillé ne revient dans Kivou. Ce runbook ne permet ni e-mail, ni mutation
Instantly, ni déploiement. Le programme doit rester désactivé et en `SHADOW`.

## État vérifié et impossibilité actuelle du parcours à zéro crédit

Documentation Apollo consultée le 21 septembre 2026 : la
[recherche d'organisations](https://docs.apollo.io/reference/organization-search)
`POST /api/v1/mixed_companies/search`, utilisée par les neuf partitions du
census, consomme **1 crédit par page** sur les plans actuels. La
[recherche de personnes](https://docs.apollo.io/reference/people-api-search)
annonce **0 crédit**, mais elle ne renvoie aucune adresse e-mail et mesure
d'abord des personnes, pas le nombre exhaustif d'entreprises de chaque
partition. La [recherche des comptes sauvegardés](https://docs.apollo.io/reference/search-for-accounts)
est également gratuite, mais ne couvre que les comptes déjà enregistrés dans
le workspace Apollo. Aucune de ces deux opérations ne remplace donc
silencieusement la recherche d'organisations du census.

Le plafond de cette mission est **0 crédit / 0.00 CHF**. Le préflight
`COVERAGE` signale `ORG_SEARCH_REQUIRES_CREDIT` et refuse l'autorisation,
même si une clé et une base autorisée existent. Aucun permis à plafond nul
n'est créé : le modèle de permis actuel exige à juste titre un budget positif
pour ce parcours facturable. A0 et A1 restent non exécutables dans ces
conditions. Il faut soit une preuve vérifiable que le plan précis facture
réellement cette opération à zéro crédit et une adaptation ciblée des
contrôles, soit une **nouvelle autorisation budgétaire** pour au moins neuf
pages (une par partition). Cette dernière n'est pas accordée ici.

## Bootstrap et préflight sans dépense

Depuis le worktree Kivou, avec les secrets injectés par le gestionnaire
normal, préparer le diagnostic sans connecter Apollo ni la source française :

```bash
uv run milomail-census bootstrap \
  --program-config ops/examples/milomail-acquisition.json.example
```

`bootstrap` fonctionne même sans `KIVOU_DATABASE_URL`. Le JSON indique les
variables manquantes, les neuf partitions, les plafonds, le SHA, le plan/prix
si un fichier de prix est fourni, l'opération facturée et
`instantly_mutation_allowed=false`. Les options suivantes approfondissent
la vérification lorsqu'une base PostgreSQL non productive a été **déjà**
autorisée et migrée à `0072` ; elles n'effectuent que les sondes officiellement
gratuites demandées explicitement :

```bash
uv run milomail-census bootstrap \
  --program-config <programme-validé.json> --census-id <id> \
  --database-authorization <autorisation-base.json> \
  --pricing <prix-apollo-plan-vérifié.json> \
  --probe-official-source --probe-apollo-free
uv run milomail-census preflight --phase COVERAGE --census-id <id> \
  --database-authorization <autorisation-base.json> \
  --pricing <prix-apollo-plan-vérifié.json> \
  --probe-official-source --probe-apollo-free
```

Ne lancer les sondes Apollo que si leur gratuité est confirmée pour le plan
détecté. L'origine Apollo est fixe. La source française est limitée à **60
requêtes/minute au maximum** pour ce lot, y compris si son quota officiel est
plus élevé. Un résultat de préflight avec `operation_cost` différent de
`READY` interdit tout appel de recherche. Une absence de prix, plan, pool de
crédits, solde ou taux vérifié reste un diagnostic, jamais un coût nul inféré.

Configuration requise pour l'approfondissement : `KIVOU_DATABASE_URL`,
`KIVOU_ACQUISITION_ENVIRONMENT=STAGING`, une autorisation de base datée,
`MILOMAIL_CENSUS_APOLLO_API_KEY` dédiée, les clés
`KIVOU_SUPPRESSION_HMAC_KEY_VERSION`, `KIVOU_SUPPRESSION_HMAC_KEY` et, le cas
échéant, `KIVOU_SUPPRESSION_RETAINED_KEYS_JSON`. La source officielle exige
`MILOMAIL_COMPANY_STATUS_ENABLED=true`, un plafond explicite
`MILOMAIL_COMPANY_STATUS_MAX_REQUESTS` et
`MILOMAIL_COMPANY_STATUS_RATE_LIMIT<=60`. Les autres plafonds census gardent
leur défaut **zéro**. Aucun secret ni URL avec mot de passe ne doit être
transcrit dans Git ou le rapport.

## Plan, permis et reprise

Sur la base autorisée, `plan` persiste les neuf partitions sans appel Apollo :

```bash
uv run milomail-census plan --program-config <programme-validé.json> \
  --database-authorization <autorisation-base.json>
uv run milomail-census status --census-id <id>
```

La création d'un permis `COVERAGE` à **0 crédit** et **0.00 CHF** n'a pas de
commande exécutable pour le parcours actuel ; `issue-permit` refuse ce
permis. Il ne faut pas modifier le fichier JSON ou augmenter le plafond pour
contourner ce refus. Les commandes `run --phase COVERAGE` et
`resume --phase COVERAGE` restent donc bloquées avant Apollo. A0 aurait au
maximum neuf pages, une par partition ; A1 n'est envisagé qu'après A0 réussi
et rapprochement du solde. Si le prix ou le résultat d'un appel est ambigu,
le checkpoint reste en revue et aucune reprise ne rejoue cet appel.

Pour un permis futur réellement autorisé, le modèle d'émission/révocation,
les réservations et l'empreinte de configuration sont décrits dans le
[runbook readiness](16-milomail-census-readiness.md). Aucun permis
`ENRICHMENT` n'est autorisé par cette mission.

## Rapport et confidentialité

```bash
uv run milomail-census report --census-id <id> --public-aggregate
uv run milomail-census reconcile-usage --census-id <id> \
  --actual-credits <crédits-confirmés> --actual-cost-chf <CHF-confirmés> \
  --usage-evidence-ref <référence-opaque> \
  --database-authorization <autorisation-base.json> \
  --acknowledge-exclusive-attribution
uv run milomail-census purge-cache --census-id <id> \
  --database-authorization <autorisation-base.json> --acknowledge-cache-purge
uv run milomail-census revoke-permit --permit-id <id-permis> \
  --database-authorization <autorisation-base.json>
```

`report` sépare le total **déclaré** par Apollo (somme des partitions
mesurées, susceptible de recouvrement), les résultats **parcourus**, les
entreprises **uniques observées**, les recouvrements entre partitions et les
adresses réellement **vérifiées**. Les partitions non mesurées gardent
`estimated_result_count=null`. Le rapport public regroupe les localisations
avec moins de cinq entreprises sous `SMALL_GROUPS_REDACTED`. Aucun nom,
adresse, token ni réponse brute n'y figure. Les réponses brutes et
checkpoints restent dans la base autorisée.
Quand une page d'organisations a réellement été parcourue, la phase A peut
tester ses domaines par DNS MX public et conserver la preuve datée :
`GOOGLE_WORKSPACE`, `GMAIL_CONSUMER`, `MICROSOFT_365`, `OTHER` ou `UNKNOWN`.
Le timeout DNS reste `UNKNOWN`. Cela ne vérifie ni un dirigeant ni une adresse.

Sans taux de conversion observé ou hypothèses opérateur sourcées, la
fourchette d'adresses potentielles reste `null`. Pour publier **un scénario,
pas un résultat mesuré**, fournir trois taux croissants entre 0 et 1 :

```bash
uv run milomail-census report --census-id <id> --public-aggregate \
  --forecast-low <taux-bas> --forecast-central <taux-central> \
  --forecast-high <taux-haut> --forecast-source <référence-opaque>
```

Le calcul multiplie les entreprises uniques **observées** par chaque taux,
avec arrondi inférieur, usuel et supérieur respectivement. Il ne projette
pas automatiquement les partitions non parcourues ; le rapport porte
`SCENARIO_NOT_MEASURED`. Un volume d'entreprises Apollo n'est jamais une
liste d'adresses envoyables. L'ancienne fourchette 15 000–50 000 reste une
hypothèse non mesurée et ne doit pas être reprise sans nouvelles données.

`purge-cache` efface les copies de réponses Apollo terminées après la fin du
run ou à l'échéance de rétention configurée. Elle conserve les checkpoints,
comptages, réservations, reçus d'usage, permis et suppressions. Un run
incomplet purgé passe en revue : il ne peut plus rejouer la réponse effacée.
La conservation par défaut est de 30 jours, configurable par
`MILOMAIL_CENSUS_RETENTION_DAYS`.

Pour arrêter d'urgence : révoquer le permis s'il en existe un, régler
`MILOMAIL_CENSUS_ENABLED=false`, retirer la clé Apollo dédiée et arrêter le
processus. Vérifier `status`, réconcilier les crédits sur Apollo, puis examiner
tout appel `REVIEW_REQUIRED` avant une reprise. Aucune suppression de preuve
d'usage ou de registre de suppression ne débloque le run.
