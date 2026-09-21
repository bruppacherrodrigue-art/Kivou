# Milo Mail A0 : pool Apollo staging prépayé

Milo Mail est le produit ; Milo est son agent. Kivou seul conserve les données
Apollo. Ce runbook autorise uniquement la couverture d'organisations. Aucun
contact, adresse e-mail, enrichissement, export Instantly ou envoi n'est permis.

## Périmètre et preuve de coût

La [documentation Apollo Organization Search](https://docs.apollo.io/reference/organization-search)
consultée le 21 septembre 2026 indique un crédit par page, 100 résultats
maximum par page et une limite d'affichage de 50 000. La
[documentation des crédits](https://knowledge.apollo.io/hc/en-us/articles/9527776320781-What-Are-Credits)
décrit l'achat complémentaire comme une action séparée et le refus d'une
opération si les crédits sont insuffisants. Le solde staging doit être relu
avant et après l'exécution par l'endpoint gratuit `credit_usage_stats`.
Le permis A0 réserve au maximum neuf appels et neuf crédits ; une relance
facturable utilise une place dans ce même plafond. Aucun prix CHF/crédit
universel n'est supposé : le coût incrémental autorisé vaut 0.00 CHF, tandis
que le coût comptable d'allocation reste `UNKNOWN`.

`PREPAID_SHARED_POOL` n'est autorisé que pour `COVERAGE_A0` sur la base
`kivou_milomail_census_a0` en staging. La référence de secret physique
`KIVOU_APOLLO_API_KEY` est résolue uniquement en mémoire. La référence,
l'attestation et les plafonds sont liés par le hash de configuration inscrit
dans le permis. Une modification des filtres, plafonds, prix attesté, source
officielle ou phase invalide le permis. Il expire sous quatre heures et peut
être révoqué. Les défauts du programme et du census restent fermés et à zéro.

## Base isolée

Utiliser seulement une base PostgreSQL nouvelle et vide sur l'infrastructure
staging. Vérifier son absence avant création et ne copier aucune donnée
applicative. La base `kivou_staging` à `0065_chief_of_staff` est hors périmètre.
Migrer la nouvelle base à `0073_milomail_a0_prepaid`, qui inclut `0072`.
Tester séparément upgrade et downgrade sur une autre base jetable ; ne pas
downgrader la base A0 contenant des résultats. L'autorisation de base contient
son identité calculée par `database_identity`, l'environnement `staging`, une
référence opérateur et une expiration. Garder ce JSON hors Git en mode 0600.

## Configuration éphémère

Injecter `KIVOU_DATABASE_URL` pour la base **isolée** depuis le gestionnaire de
secrets staging. Ne pas publier l'URL. Utiliser les clés de suppression staging
normales et la clé Apollo staging existante. Les valeurs non secrètes sont :

```text
KIVOU_ACQUISITION_ENVIRONMENT=STAGING
MILOMAIL_CENSUS_ENABLED=true
MILOMAIL_CENSUS_AUTHORIZATION_REF=<référence datée>
MILOMAIL_CENSUS_APOLLO_SECRET_REF=KIVOU_APOLLO_API_KEY
MILOMAIL_CENSUS_MAX_PARTITIONS=9
MILOMAIL_CENSUS_MAX_PAGES=9
MILOMAIL_CENSUS_MAX_CANDIDATES=225
MILOMAIL_CENSUS_MAX_ENRICHMENTS=0
MILOMAIL_CENSUS_MAX_APOLLO_CREDITS=9
MILOMAIL_CENSUS_MAX_COST_CHF=0
MILOMAIL_CENSUS_CHF_PER_CREDIT_CEILING=0
MILOMAIL_COMPANY_STATUS_ENABLED=true
MILOMAIL_COMPANY_STATUS_MAX_REQUESTS=9
MILOMAIL_COMPANY_STATUS_RATE_LIMIT=60
```

L'attestation JSON hors Git utilise `billing_basis=PREPAID_SHARED_POOL`,
`price_per_credit=null`, `max_incremental_charge_chf=0`,
`auto_top_up_allowed=false`, `overage_allowed=false`, un solde daté, les
catégories de crédit, les limites API observées et les références officielles.
Le plan exact doit être indiqué comme inconnu si l'API gratuite ne l'expose
pas. Ne pas inventer un prix comptable.

## Commandes

```bash
uv run milomail-census bootstrap --program-config <programme.json> \
  --database-authorization <autorisation-base.json> --pricing <attestation.json> \
  --probe-official-source --probe-apollo-free
uv run milomail-census plan --program-config <programme.json> \
  --database-authorization <autorisation-base.json>
uv run milomail-census preflight --phase COVERAGE_A0 --census-id <id> \
  --database-authorization <autorisation-base.json> --pricing <attestation.json> \
  --probe-official-source --probe-apollo-free
uv run milomail-census issue-permit --permit <permis-a0.json> \
  --database-authorization <autorisation-base.json> --pricing <attestation.json>
uv run milomail-census preflight --phase COVERAGE_A0 --census-id <id> \
  --permit-id <permis-id> --database-authorization <autorisation-base.json> \
  --pricing <attestation.json> --probe-official-source --probe-apollo-free
uv run milomail-census run --phase COVERAGE_A0 --a0 --census-id <id> \
  --program-config <programme.json> --permit-id <permis-id> \
  --database-authorization <autorisation-base.json> --pricing <attestation.json> \
  --probe-official-source --probe-apollo-free --authorize-paid-apollo
uv run milomail-census status --census-id <id>
uv run milomail-census report --census-id <id> --public-aggregate
uv run milomail-census resume --phase COVERAGE_A0 --a0 --census-id <id> \
  --program-config <programme.json> --permit-id <permis-id> \
  --database-authorization <autorisation-base.json> --pricing <attestation.json> \
  --probe-official-source --probe-apollo-free --authorize-paid-apollo
uv run milomail-census reconcile-usage --shared-pool --census-id <id> \
  --pool-before <solde-avant> --pool-after <solde-après> \
  --database-authorization <autorisation-base.json>
uv run milomail-census revoke-permit --permit-id <permis-id> \
  --database-authorization <autorisation-base.json>
```

Le JSON du permis contient `phase=COVERAGE_A0`, neuf identifiants de partition,
`max_pages=max_credits=9`, `max_candidates=225`, `max_enrichments=0`,
`max_cost_chf=0`, `price_chf_per_credit=null`,
`billing_basis=PREPAID_SHARED_POOL`,
`apollo_secret_ref=KIVOU_APOLLO_API_KEY`, l'identité de la base et le
`configuration_hash` renvoyé par le préflight. Il est daté et expire sous
quatre heures. Le reçu est conservé en base ; ne pas le commiter.

Exiger `execution_authorized=true`, neuf partitions, `credits_available>=9`,
`instantly_mutation_allowed=false`, zéro enrichissement et zéro contact avant
`run`. Un timeout ambigu ne doit pas être rejoué automatiquement. Le bilan
du pool partagé ne suffit pas à attribuer tous les débits à ce run :
`reconcile-usage --shared-pool` compare le delta au ledger et laisse le reçu
exclusif vide. Signaler toute consommation concurrente comme ambiguë.

Après A0, conserver les réponses brutes et checkpoints uniquement sur la base
isolée pendant la rétention configurée, 30 jours par défaut. `purge-cache`
efface les copies Apollo, pas les suppressions, permis, réservations ni reçus ;
ne l'utiliser qu'après analyse. Pour arrêter immédiatement, révoquer le permis,
mettre `MILOMAIL_CENSUS_ENABLED=false`, couper le processus et examiner le
ledger avant toute reprise.

Un total Apollo déclaré n'est ni une organisation observée, ni une adresse
professionnelle vérifiée. Les contacts et adresses vérifiés doivent être zéro
en A0. Toute projection d'adresses reste un scénario avec hypothèses explicites.
Le chiffre historique 15 000–50 000 n'est pas un résultat mesuré.
