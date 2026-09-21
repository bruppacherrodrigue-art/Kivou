# Milo Mail : couverture Apollo bornée en SHADOW

Milo Mail est le produit ; Milo est l'agent intégré. Kivou garde les données
Apollo et les décisions. Le produit Milo Mail ne reçoit ni prospects ni
identifiants fournisseur. Aucun contenu Gmail, token OAuth ou résultat d'audit
détaillé ne revient dans Kivou. Ce runbook ne permet ni e-mail, ni mutation
Instantly, ni déploiement. Le programme doit rester désactivé et en `SHADOW`.

## Coût documenté et autorisation actuelle

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

L'opérateur a autorisé l'utilisation de crédits Apollo le 21 septembre 2026.
Cette autorisation permet de préparer A0 à **neuf pages au plus**, une par
partition, sous un permis `COVERAGE` daté et lié à la base et à la configuration.
Elle ne fournit ni clé dédiée, ni base autorisée, ni prix CHF/crédit attesté.
Le montant CHF maximal doit être calculé à partir du prix vérifié du plan
avant toute émission du permis. Les plafonds restent à zéro par défaut et
aucun appel facturable n'est permis avec un plafond nul ou un coût inconnu.
La phase A1 exige une nouvelle évaluation des résultats A0 et un permis
distinct, limité aux pages utiles ; aucun enrichissement n'est autorisé ici.

## Bootstrap et préflight sans dépense

Depuis le worktree Kivou, avec les secrets injectés par le gestionnaire
normal, préparer le diagnostic sans connecter Apollo ni la source française :

```bash
uv run milomail-census bootstrap \
  --program-config ops/examples/milomail-acquisition.json.example
```

`bootstrap` fonctionne même sans `KIVOU_DATABASE_URL`. Le JSON indique les
variables manquantes, les neuf partitions, les plafonds, le SHA, le plan/prix
si un fichier de prix est fourni, la réservation de crédit et
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
`MILOMAIL_COMPANY_STATUS_RATE_LIMIT<=60`. Pour A0, configurer explicitement
`MILOMAIL_CENSUS_ENABLED=true`, `MILOMAIL_CENSUS_AUTHORIZATION_REF`,
`MILOMAIL_CENSUS_MAX_PARTITIONS=9`, `MILOMAIL_CENSUS_MAX_PAGES=9`,
`MILOMAIL_CENSUS_MAX_CANDIDATES=225`,
`MILOMAIL_CENSUS_MAX_ENRICHMENTS=0`,
`MILOMAIL_CENSUS_MAX_APOLLO_CREDITS=9` et
`MILOMAIL_CENSUS_MAX_COST_CHF=9 × prix CHF/crédit vérifié`.
`MILOMAIL_CENSUS_CHF_PER_CREDIT_CEILING` doit être au moins ce prix et ne doit
pas être choisi avant la vérification du plan. Les défauts du code restent à
**zéro**. Aucun secret ni URL avec mot de passe ne doit être
transcrit dans Git ou le rapport.

## Plan, permis et reprise

Sur la base autorisée, `plan` persiste les neuf partitions sans appel Apollo :

```bash
uv run milomail-census plan --program-config <programme-validé.json> \
  --database-authorization <autorisation-base.json>
uv run milomail-census status --census-id <id>
```

Après vérification du préflight, émettre un permis `COVERAGE` limité aux neuf
partitions, neuf pages, 225 emplacements candidats, zéro enrichissement, neuf
crédits et au montant CHF calculé. Il doit expirer rapidement et reprendre
l'empreinte exacte `configuration_hash` du préflight. Ne créer ce permis que
sur la base non productive autorisée :

```bash
uv run milomail-census issue-permit --permit <permis-COVERAGE.json> \
  --database-authorization <autorisation-base.json> \
  --pricing <prix-apollo-plan-vérifié.json>
uv run milomail-census preflight --phase COVERAGE --census-id <id> \
  --permit-id <permis-COVERAGE> \
  --database-authorization <autorisation-base.json> \
  --pricing <prix-apollo-plan-vérifié.json> \
  --probe-official-source --probe-apollo-free
```

Exiger `execution_authorized=true`, `operation_cost=READY`,
`no_enrichment=READY`, `credit_caps=READY`, `postgresql=READY` et
`instantly_mutation_allowed=false`. La commande exacte d'A0 est :

```bash
uv run milomail-census run --phase COVERAGE --a0 --census-id <id> \
  --program-config <programme-validé.json> --permit-id <permis-COVERAGE> \
  --database-authorization <autorisation-base.json> \
  --pricing <prix-apollo-plan-vérifié.json> \
  --operations <coûts-par-opération-vérifiés.json> \
  --probe-official-source --probe-apollo-free --authorize-paid-apollo
uv run milomail-census status --census-id <id>
uv run milomail-census resume --phase COVERAGE --a0 --census-id <id> \
  --program-config <programme-validé.json> --permit-id <permis-COVERAGE> \
  --database-authorization <autorisation-base.json> \
  --pricing <prix-apollo-plan-vérifié.json> \
  --operations <coûts-par-opération-vérifiés.json> \
  --probe-official-source --probe-apollo-free --authorize-paid-apollo
```

`--a0` impose une seule page de recherche d'organisations par partition et
exclut la recherche de personnes. Il peut observer les MX publics des domaines
trouvés. Dans cet environnement, la clé et la base autorisée sont absentes ;
ces commandes ne sont **pas encore exécutées**. Pour A1, retirer `--a0`
seulement après examen des checkpoints et du coût confirmé, avec un permis et
des plafonds explicitement autorisés. Le plafond global du census est figé au
premier `run` : un A0 configuré à neuf pages ne peut pas être étendu
silencieusement dans le même recensement. Prévoir dès le départ un plafond
global A1 distinct du permis A0, ou préparer un nouveau plan avec ses propres
crédits et checkpoints après A0. A1 n'est envisagé qu'après A0 réussi et
rapprochement du solde.
Si le prix ou le résultat d'un appel est ambigu,
le checkpoint reste en revue et aucune reprise ne rejoue cet appel.

Pour le permis A0, le modèle d'émission/révocation,
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

`purge-cache` efface les copies de réponses Apollo terminées et les snapshots
bruts de candidats après la fin du run ou à l'échéance de rétention configurée.
Elle conserve les checkpoints,
comptages, réservations, reçus d'usage, permis et suppressions. Un run
incomplet purgé passe en revue : il ne peut plus rejouer la réponse effacée.
La conservation par défaut est de 30 jours, configurable par
`MILOMAIL_CENSUS_RETENTION_DAYS`.

Pour arrêter d'urgence : révoquer le permis s'il en existe un, régler
`MILOMAIL_CENSUS_ENABLED=false`, retirer la clé Apollo dédiée et arrêter le
processus. Vérifier `status`, réconcilier les crédits sur Apollo, puis examiner
tout appel `REVIEW_REQUIRED` avant une reprise. Aucune suppression de preuve
d'usage ou de registre de suppression ne débloque le run.
