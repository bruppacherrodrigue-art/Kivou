# Milo Mail France B1 — base de contacts vérifiés en SHADOW

Milo Mail est le produit ; Milo est l'agent intégré. Kivou conserve les données
Apollo, les preuves et les suppressions. Aucun contact ni résultat brut ne doit
entrer dans Git ou dans Milo Mail. B1 ne crée aucune liste, campagne ou lead
Instantly et n'envoie aucun message.

## Autorisation et limites

L'exécution réelle est réservée à `kivou_milomail_census_a0` sur staging, à
la révision Alembic `0076_milomail_b1_ready_base`. La base applicative staging
à `0065_chief_of_staff` ne doit pas être migrée. Le permis
`FRANCE_B1_READY_BASE` est daté, lié à l'identité de la base, au plan de pages,
à la configuration et au prix attesté. Il expire en quatre heures au plus.
Les valeurs de `.env.example` interdisent tout appel payant par défaut.

Pour ce lot uniquement : au plus 900 nouveaux crédits Apollo, solde du pool
jamais inférieur à 1 000 crédits, aucun achat ni rechargement, au plus une
adresse livrable et deux enrichissements par entreprise. La clé staging
`KIVOU_APOLLO_API_KEY` peut être référencée par
`MILOMAIL_CENSUS_APOLLO_SECRET_REF` dans l'environnement privé de l'opérateur,
jamais copiée dans un fichier de rapport. La référence est révoquée avec le
permis après le run. Une clé Milo Mail dédiée est requise avant un autre lot.

Apollo [facture une recherche d'organisations à un crédit par page](https://docs.apollo.io/reference/organization-search),
[une recherche de personnes à zéro crédit](https://docs.apollo.io/reference/people-api-search),
et [l'enrichissement de personne à un crédit sans téléphone ni cascade](https://docs.apollo.io/reference/people-enrichment)
si des données facturables sont trouvées. L'adaptateur met explicitement les
options téléphone, e-mail personnel et cascade à `false`. B1 réserve un crédit
par enrichissement et compare le solde avant/après chaque appel. Un débit
ambigu arrête la reprise ; le prix d'allocation CHF du crédit prépayé reste
inconnu. Le coût **incrémental** autorisé est 0,00 CHF.

## Procédure

Préparer une autorisation de base non productive, une attestation Apollo et une
configuration du programme Milo Mail dans le gestionnaire privé staging. Les
trois fichiers sont référencés par chemins privés passés aux commandes ; ils
ne sont ni committés ni journalisés. Le programme reste désactivé, en SHADOW,
avec les plafonds d'envoi à zéro.

```bash
# Exemple : les variables B1 sont fournies exclusivement dans l'environnement
# privé de l'opérateur et doivent respecter le permis approuvé.
milomail-b1 plan --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH" --pricing "$PRICING" \
  --seed milomail-france-b1-20260922-public
milomail-b1 replay-b0 --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH" --program-config "$PROGRAM_CONFIG"
milomail-b1 preflight --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH" --pricing "$PRICING"
milomail-b1 issue-permit --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH" --pricing "$PRICING"
milomail-b1 preflight --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH" --pricing "$PRICING"
milomail-b1 run --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH" --pricing "$PRICING" \
  --program-config "$PROGRAM_CONFIG" --authorize-paid-apollo --max-actions 25
milomail-b1 resume --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH" --pricing "$PRICING" \
  --program-config "$PROGRAM_CONFIG" --authorize-paid-apollo --max-actions 100
milomail-b1 replay-b1 --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH" --program-config "$PROGRAM_CONFIG"
milomail-b1 status --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH"
milomail-b1 report --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH"
milomail-b1 revoke --census-id "$CENSUS_ID" --permit-id "$PERMIT_ID" \
  --database-authorization "$DB_AUTH"
```

`plan` fige les pages restantes et les plafonds avant le premier appel. Les
pages déjà présentes en cache A0/A1/B1 sont exclues. Les crédits d'appels
réussis ou ambigus restent réservés, y compris après interruption. `resume`
réutilise les réponses Apollo complètes sans nouvel appel. Si un appel est
ambigu, ne pas effacer son ledger : mettre le permis en revue, réconcilier
le compte et créer un nouveau permis borné seulement après résolution.

`report` est agrégé. La simulation d'export n'a aucune dépendance Instantly :
elle n'accepte que `READY_THEORETICAL`, recontrôle les suppressions juste
avant de calculer un reçu HMAC, les segments et le diff, puis rend
`provider_calls=0` et `mutations_allowed=false`. Aucune adresse n'apparaît
dans le rapport.

Le runner lit le solde sur l'endpoint gratuit `credit_usage_stats` avant et
après chaque opération facturable ; le préflight vérifie en plus la santé du
compte et les limites de taux. Une réponse `429` ou un solde indisponible
interrompt le run sans relancer automatiquement l'opération payante. Attendre
la fin du `Retry-After`, vérifier le checkpoint et le ledger, puis relancer
`preflight` avant `resume`. `replay-b1` met à jour les décisions et la vue
privée depuis les seuls checkpoints complets ; il n'appelle pas Apollo.

Le journal HTTP distingue robots.txt, page d'accueil, page légale, DNS,
redirections, cache et API administrative officielle. Chaque tentative
contient un identifiant de run et d'entreprise, un type, une date et un
résultat ; aucun corps de réponse n'y figure. Les appels effectués avant
l'ajout de ce journal ne sont pas inventés rétroactivement.

## Activité et décisions

Le ruleset `milomail-fr-b2b-v2` distingue `OFFICIAL_ACTIVE`,
`OPERATIONALLY_ACTIVE`, `ACTIVITY_UNKNOWN` et `OFFICIAL_CEASED`. L'activité
opérationnelle exige des preuves indépendantes et datées : MX Google Workspace
actuel, dirigeant vérifié sur le domaine et identité du site corroborée.
Une preuve manquante ou contradictoire laisse `HOLD` ; une cessation officielle
donne `NO_SEND`. La politique conserve aussi les exigences de pays France,
pertinence professionnelle, capacité professionnelle, transparence de la
collecte indirecte, identité d'expéditeur, opposition gratuite, suppression,
landing française, infrastructure et budget d'envoi. SHADOW ne transforme
aucun `SEND_THEORETICAL` en message envoyé.

Références primaires consultées le 22 septembre 2026 :
[CNIL, prospection électronique B2B](https://www.cnil.fr/fr/la-prospection-commerciale-par-courrier-electronique-sms-mms-et-automate-dappel),
[CPCE L34-5](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000042155961/),
[RGPD articles 6, 14 et 21](https://eur-lex.europa.eu/eli/reg/2016/679/oj?locale=fr),
[CNIL, intérêt légitime](https://www.cnil.fr/fr/les-bases-legales/interet-legitime).
L'absence d'une obligation SIRENE préalable dans ces textes est une inférence
du ruleset, pas une dispense des autres exigences. La preuve SIRENE reste
prioritaire lorsqu'elle existe.

## Confidentialité, arrêt et purge

Les réponses Apollo, contacts, adresses et extraits de preuve restent dans la
base isolée. Le cache et les réponses brutes ont une rétention configurable
de 30 jours dans ce lot. `milomail-census purge-cache` retire les snapshots
Apollo selon le runbook census ; les suppressions, permis, reçus d'usage et
décisions auditables ne sont pas supprimés. L'arrêt d'urgence consiste à
révoquer le permis, désactiver `MILOMAIL_B1_ENABLED` et vérifier `status` puis
`reconcile-usage`. Aucun endpoint Instantly n'est appelé par B1.
