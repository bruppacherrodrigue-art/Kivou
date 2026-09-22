# Milo Mail B0 — rendement en dirigeants et adresses professionnelles

État : procédure pour la base isolée staging `kivou_milomail_census_a0`. Aucun envoi,
export Instantly, déploiement ni enrichissement hors permis B0. Milo Mail est le
produit ; Milo est l'agent du produit. Kivou conserve les prospects et les preuves.

## Diagnostic administratif A1

Les 384 organisations Google Workspace observées en A1 n'ont **ni ville ni code
postal** dans la réponse Apollo conservée. La recherche de l'API Recherche
d'entreprises a produit 353 `NO_CORROBORATED_MATCH` et 31 résultats tronqués.
Cette situation ne prouve pas une cessation d'activité. Le matcher conserve son
exigence d'identité corroborée. B0 cherche un SIREN/SIRET ou une TVA française
valide dans les mentions légales du domaine public, puis interroge la source
officielle par identifiant exact. Un nom commercial différent, un siège distinct,
des homonymes ou plusieurs identifiants restent en `HOLD`. Une entreprise cessée
confirmée donne `NO_SEND`.

Le résolveur ne charge que `robots.txt`, la page d'accueil et au plus deux pages
internes de mentions légales (quatre requêtes HTTP par domaine). Il n'exécute ni
JavaScript ni instruction de la page, refuse les hôtes privés et les redirections,
borne taille et délai, et conserve uniquement l'identifiant, la source, la date et
la raison dans le cache autorisé. Le TTL est de sept jours. Les résultats du
matcher restent dans la base isolée. L'API officielle est plafonnée à 600 requêtes
et 60/minute ; les résultats existants en cache sont réutilisés.

## Échantillon et crédit

Le plan B0 sélectionne au plus 200 organisations uniques Google Workspace parmi
les observations A1. La graine publique et le hash du plan sont liés à l'ID du
permis ; le plan est persisté **avant** émission du permis. La sélection tourne
entre les strates secteur, tranche d'effectif Apollo, partition, première page
ou page profonde, preuve administrative et complétude des champs. Les strates
absentes dans A1 ne peuvent pas être créées artificiellement. Les organisations
cessées confirmées, déjà traitées ou associées à une suppression Milo Mail
identifiable sont exclues.

Le permis `CONTACT_YIELD_B0` autorise au maximum 1 500 crédits nouveaux, 200
entreprises, deux enrichissements de personnes par entreprise et une seule
adresse livrable par entreprise. Chaque People Search est réservé à zéro crédit.
Chaque People Enrichment réserve neuf crédits, plafond conservateur de la
[documentation Apollo](https://docs.apollo.io/reference/people-enrichment),
avec téléphone, e-mail personnel et cascade désactivés. Les crédits réservés
ne sont pas récupérés sur simple estimation. La réserve du pool partagé reste
au moins 500 ; coût incrémental autorisé 0,00 CHF, coût comptable d'allocation
inconnu. Ni achat ni recharge ne sont autorisés. Les sondes gratuites du compte
relisent le solde et les compteurs People Search / People Match autour de chaque
appel. Un delta impossible ou concurrent arrête le run pour revue. Les appels
ambigus ne sont jamais rejoués automatiquement.

## Commandes staging

Exécuter depuis une copie temporaire du code de cette PR sur `kivou-staging-01`.
Le script [milomail-b0-staging.sh](../../ops/bin/milomail-b0-staging.sh) charge les
secrets existants, pointe **seulement** vers la base isolée, configure les plafonds
et n'affiche aucune valeur sensible. Il doit être lancé sous `sudo` depuis cette
copie ; aucune commande ci-dessous ne cible la base applicative staging.

Créer dans un répertoire privé root un nouveau reçu `database-authorization.json`
avec `database_id` obtenu par `database_identity` sur la base isolée,
`environment=staging`, `issued_by_reference=user-prompt-2026-09-22-b0` et une
expiration ultérieure au permis (huit heures maximum). Le reçu A1 a expiré et
ne doit pas être réutilisé. Tester l'upgrade/downgrade `0075` sur une base
PostgreSQL jetable, puis appliquer **uniquement l'upgrade** `0074→0075` sur
`kivou_milomail_census_a0`. Ne jamais migrer la base applicative staging.

Dans les commandes ci-dessous, `CENSUS_ID` vient du `status.json` A1 privé,
`PERMIT_ID` est un nouvel identifiant opaque, `AUTH` le reçu de base privé,
`PRICING` l'attestation actuelle sans secret et `PROGRAM` la configuration Milo
Mail revue. Le prix documentaire n'est pas présenté comme prix CHF universel :
`PREPAID_SHARED_POOL`, `price_per_credit=null`, `max_incremental_charge_chf=0`,
`auto_top_up_allowed=false`, `overage_allowed=false`, catégories 0/9 crédits,
solde et date courants, source Apollo et référence opérateur sont requis.

```bash
sudo ops/bin/milomail-b0-staging.sh plan --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH" --max-companies 200 --max-credits 1500
sudo ops/bin/milomail-b0-staging.sh issue-permit --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH" --pricing "$PRICING"
sudo ops/bin/milomail-b0-staging.sh preflight --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH" --pricing "$PRICING"
sudo ops/bin/milomail-b0-staging.sh run --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH" --pricing "$PRICING" --program-config "$PROGRAM" --authorize-paid-apollo
sudo ops/bin/milomail-b0-staging.sh status --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH"
sudo ops/bin/milomail-b0-staging.sh report --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH"
```

`run` traite exactement cinq entreprises puis s'arrête pour calibration. La
continuation exige cinq checkpoints complets, au moins un enrichissement et
un delta de crédits attribuable pour chaque appel. Reprendre ensuite avec le
même plan et permis tant qu'il est valide :

```bash
sudo ops/bin/milomail-b0-staging.sh resume --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH" --pricing "$PRICING" --program-config "$PROGRAM" --authorize-paid-apollo --all-after-calibration
sudo ops/bin/milomail-b0-staging.sh revoke --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH"
```

Le `report` ne renvoie que des agrégats. Les réponses Apollo, identités et
adresses restent dans la base isolée. Conserver au plus 30 jours les snapshots
Apollo de personnes, puis utiliser la purge sélective existante
`milomail-census purge-cache` après export interne autorisé des agrégats ; elle
retire aussi les champs personnels des checkpoints B0 et ne supprime ni
suppressions, ni permis, ni reçus de crédits. Révoquer le permis
et couper le wrapper pour un arrêt immédiat. La reprise lit les snapshots déjà
checkpointés ; une réponse facturable ambiguë impose une revue, jamais un
nouvel appel implicite.

### Arrêt, reprise et lecture après le pilote

Le pilote du 22 septembre a atteint **200 entreprises checkpointées** et ses
quatre permis exécutés sont révoqués. Ne relancez ni `run` ni `resume` sur eux.
Le ledger garde cinq réponses Apollo complètes sans checkpoint : trois recherches
gratuites et deux enrichissements payés. Le planificateur les exclut d'un
nouveau plan ; il ne rejoue jamais leur appel. Tout nouveau lot exige une
autorisation, un plan et un permis distincts avec le solde courant et les
réservations cumulées, sans dépasser le plafond de mission.

Apollo peut remettre le compteur `People Match` à zéro en cours de minute. Une
réponse d'enrichissement n'est acceptée malgré ce changement que si le nouveau
compteur vaut exactement 1 et si le pool a baissé d'un crédit. Après la
calibration de cinq entreprises, la recherche de personnes documentée gratuite
ne déclenche plus de sonde de solde à chaque appel ; le solde reste contrôlé
avant et après chaque enrichissement payé et en fin de run. Un HTTP 429 sur les
endpoints gratuits bloque l'émission du permis ; `APOLLO_RATE_LIMIT` et
`retry_after_seconds` sont renvoyés sans clé ni réponse brute. Les
[limites Apollo](https://docs.apollo.io/reference/rate-limits) sont établies
par équipe, pas par clé.

Pour contrôler le lot achevé, lire les agrégats et réconcilier prudemment le
pool partagé avec le ledger, utiliser le dernier permis révoqué :

```bash
sudo ops/bin/milomail-b0-staging.sh status --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH"
sudo ops/bin/milomail-b0-staging.sh report --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH" --a1-report "$A1_REPORT"
sudo ops/bin/milomail-b0-staging.sh reconcile-usage --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH"
```

`CONSISTENT_SHARED_POOL_NON_EXCLUSIVE` signifie que la variation globale du
pool égale le nombre d'enrichissements inscrits ; elle ne prouve pas qu'aucun
autre usage du pool partagé n'a eu lieu. Pour refaire uniquement la recherche
publique d'activité après révocation, avec le plafond explicite approprié :

```bash
sudo ops/bin/milomail-b0-staging.sh refresh-official --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH" --max-companies 5 --acknowledge-public-requests
```

Après l'expiration du délai de conservation et la validation des agrégats,
la purge sélective du census se lance ainsi ; elle ne supprime ni suppressions,
ni permis, ni reçus de coûts :

```bash
sudo ops/bin/milomail-b0-staging.sh purge-cache --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" --database-authorization "$AUTH" --acknowledge-cache-purge
```

## Lecture du rapport et futur Instantly

Les nombres de dirigeants, e-mails professionnels trouvés, e-mails vérifiés,
e-mails Google Workspace et décisions sont distincts. Un `HOLD` administratif
peut coexister avec un rendement technique positif. Un `SEND_THEORETICAL` exige
le ruleset Kivou complet ; avec la configuration SHADOW fermée et sans landing
française, ce nombre peut rester zéro. Il ne correspond jamais à un e-mail envoyé.
Les projections France devront utiliser les intervalles A1 pour la portion
affichable (4 944 / 7 610 / 11 359) séparément des totaux déclarés hors fenêtre
Apollo (12 861 / 19 918 / 29 891), avec l'intervalle de rendement B0 et les
limites de stratification. L'ancienne hypothèse 15 000–50 000 adresses n'est
pas une observation.

Un futur export Instantly, **hors périmètre**, ne recevrait que : ID Kivou
pseudonymisé, prénom, fonction, entreprise, domaine, e-mail professionnel
vérifié, pays, langue, secteur, tranche d'effectif, statut Google Workspace,
décision, segment et personnalisation minimale. Les segments prévus sont agences
digitales/créatives, conseil et recrutement. Les preuves Apollo/SIREN et les
suppressions restent dans Kivou. B0 ne crée aucune liste, lead, campagne ou
boîte Instantly et n'envoie aucun e-mail.
