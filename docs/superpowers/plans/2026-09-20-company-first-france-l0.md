# Company First France — L0 analyse d’écart et plan d’exécution

**Statut :** L0 seulement, prêt pour revue. Aucun code applicatif, migration,
backfill, déploiement, achat de données, changement Stripe ou envoi n’est inclus.

**Spécification :** PR #275, commit
34b5d8efd487e73283d8f9cd876701694289a059,
docs/superpowers/specs/2026-09-20-company-first-france-v1.html.

**Base inspectée :** origin/main à
f9a4f5b2f5d4f26ec2c53b66b7e7b3f1fba2fb48, application Python 0.1.0,
branche docs/company-first-france-l0.

## 1. Règles de preuve

Ce document distingue trois natures d’affirmation :

- **F — fait de code :** prouvé au SHA ci-dessus par un fichier, un contrat ou
  un test du dépôt.
- **M — mesure datée :** chiffre issu d’un rapport antérieur, avec son périmètre
  et sa date ; ce n’est pas un état LIVE actuel.
- **A — hypothèse à vérifier :** décision produit, mesure de données ou
  comportement d’environnement qui exige une validation ultérieure.

Aucun accès aux bases staging ou production n’a été demandé ou effectué pour
ce L0. Il n’existe donc ici ni distribution CPV actuelle, ni volume national
actuel, ni promesse de couverture de 24 mois. Ces éléments restent des mesures
L1/L6 à produire sur une copie ou une connexion explicitement autorisée en
lecture seule.

## 2. Invariants et non-objectifs

- La recherche factuelle nationale ne lit jamais materialized_signal comme
  corpus : cette table reste une projection d’inférence liée à un Target ICP.
- Les faits nationaux sont partagés ; notes, contacts, statuts, listes,
  recherches, exports et alertes restent privés au compte.
- Aucun GET ne déclenche LLM, Apollo, Instantly, Hermes ou appel fournisseur.
- Les clés cmp_directory_{siren}, les alias publics et les sujets privés
  existants sont conservés.
- Les grants Discovery, les prix, le checkout, Stripe, Policy Gateway et les
  restrictions de campagne ne changent pas.
- Les migrations seront additives, depuis le head réel au moment de chaque
  lot. Aucun ancien fichier de migration ne sera modifié.
- Les quatre nouvelles familles de fonctionnalités resteront désactivées par
  défaut ; les faits additifs survivront à un rollback applicatif.

## 3. Inventaire vérifié au SHA de départ

### 3.1 Ingestion et sources

| Élément | Fait de code vérifié | Écart V1 |
|---|---|---|
| Sources | src/signals/persistence/schema.py déclare simap, boamp, decp et ted. Le socle France visé par la V1 est DECP + BOAMP + TED. | SIMAP ne doit pas élargir implicitement le corpus français ; son rôle transfrontalier devra être explicite. |
| Fenêtre initiale | src/signals/ingestion/sources.py : BOAMP 14 j, DECP 30 j, TED 3 j ; overlaps 7/30/3 j. | Aucun backfill national 24 mois n’est démontré. |
| BOAMP | Recherche d’attributions sans filtre CPV ; EFORMS accepté. FNSimple, MAPA et DSP sont comptés comme familles non prises en charge dans le résultat en mémoire. | Pas de quarantaine durable par item ; qualifier les familles nécessaires, garder les exclusions traçables. |
| DECP | Dataset decp-2022-marches-valides, pages de 100, fenêtre stable comptée et scindée par jour. | Une journée à au moins 10 000 lignes échoue encore : il manque une partition secondaire sûre. |
| TED | Recherche form-type=result, pagination et reprise par notice ; retries 202/429 dans le client. | Une notice non mappable peut retenir le curseur ; IDN manque dans la conversion alpha-3 ; aucun filtre d’acheteur français n’est prouvé. |
| Checkpoints | ingestion_checkpoint et ingestion_run conservent source, curseur, fenêtre, statuts et compteurs. | Pas d’acquittement alternatif durable de quarantaine, ni métriques de couverture métier par fenêtre. |
| Publication | IngestionPipeline persiste les faits avant Need Graph/matching. | L’échec d’inférence peut encore faire échouer le run et retenir la progression de source ; la publication nationale doit être un consommateur indépendant. |
| Rejeu | Les clés de faits sont déterministes et les insertions sont idempotentes. | Un contenu modifié sous le même identifiant n’est pas une nouvelle observation : les insert-if-absent de materialization.py ignorent la correction. |

### 3.2 Faits, identité et historique

| Élément existant | Comportement prouvé | Écart V1 |
|---|---|---|
| source_event | Identité source, notice/version, pays source, URL, publication et découverte, acheteurs JSON. | Pas de hash, version parseur, référence brute durable ni statut de correction/annulation. |
| contract_award | Représentation source : lot, référence, objet, CPV, Numeric(18,2), devise/TVA, parties JSON, lieu, attribution/signature/notification/début/fin. | Pas de nature/portée de valeur, part titulaire, observation immuable, état courant ou conflit par champ. |
| evidence | Ancrage award, type/référence, source, URL, chemin, valeur brute, extrait et date de récupération. | Les preuves de faits ne sont pas garanties pour chaque champ de la future projection canonique. |
| opportunity_representation | Plusieurs award_key peuvent pointer vers un opportunity_key ; seuls les liens forts convergent à l’arrivée. | Pas d’identité canonique centrale, de décision versionnée ni d’alias pour convergence tardive. |
| supplier_directory | Une ligne globale par SIREN, identité/NAF/familles/localité, données enrichies et suppressed_at. | Pas d’historique de nom/statut ni de projection SIRET→SIREN temporelle. |
| saas_company | Identité d’entreprise dérivée des signaux matérialisés. | Dépend du matching client ; impropre au corpus public national. |
| company_subject_alias | Alias public exact ou non résolu. | Bonne brique à préserver ; ne couvre pas à elle seule la convergence des contrats. |
| account_company_alias_override | Maintient un private_subject_key par compte. | À réutiliser lors d’une fusion publique ; aucun contenu privé ne doit être fusionné implicitement. |
| account_company_membership | Suivi idempotent par compte et company_key. | Ce n’est pas une liste nommée ni une recherche dynamique. |
| history.py | Agrège les awards liés à l’empreinte d’un signal ; repli nom + département ; limite 100. | Dépend du signal/ICP, confond attribution/notification/publication dans une date de repli et autorise un lien faible silencieux. |
| France link | Rapprochement BOAMP↔DECP fort/probable/non résolu. | Pas de convergence TED ; comparaison de montant par float à retirer. |

### 3.3 HTTP et interface

Les routeurs FastAPI sont montés sans préfixe /api dans
src/signals/api/app.py. Les chemins normatifs de ce plan suivent donc le
contrat réellement exposé.

| Surface | Comportement actuel | Écart V1 |
|---|---|---|
| GET /companies/directory/options | Taxonomies familles/départements, authentifié. | Pas de facettes marchés, sources, rôles, dates ou qualité. |
| GET /companies/directory | Annuaire SIREN global, q/département/famille, tri nom/ville, 1–50 lignes. | Ne cherche pas les titulaires par leurs marchés. Curseur offset non signé, sans compte/droits/snapshot/expiration. |
| GET /companies | Entreprises accessibles au compte, issues des signaux. | Périmètre privé/ICP, donc non réutilisable comme recherche nationale. |
| GET /companies/directory/{siren} | Fiche annuaire et jusqu’à 100 marchés, contexte privé du compte. | Historique non paginé, sémantique date/montant ambiguë, dépendance au repli faible. |
| /app/companies | Deux vues : Ma prospection et Annuaire, filtres URL, annulation des requêtes obsolètes. | La vue Titulaires et ses états/filtres restent à créer. |
| CompanyDossier | Identité, marchés, preuves/contacts, notes et suivi existants. | Doit séparer faits publics paginés et analyse commerciale, avec provenance et complétude. |

### 3.4 Droits, alertes, exports et flags

| Élément | Fait de code vérifié | Décision L0 |
|---|---|---|
| Catalogue | Discovery : 3 grants permanents et historique général 0 j ; Essential : 30 j/hebdo ; Pro : 365 j/quotidien et export_level=manual. | Ces droits de signaux ne valent pas autorisation nationale. Ajouter des capacités séparées, fermées pour tous les plans tant que le choix commercial n’est pas approuvé. |
| Capacités entreprise | Vue payante, enrichissement, lookup, contact personnel, note et suivi. | Ajouter les capacités publiques explicites décrites en §4.5. |
| Alertes | Préférence par compte, livraison durable par signal, lease, Message-ID, états failed/unknown/suppressed, droit revérifié. | Réutiliser transport, lease et politique d’erreur ; ne pas réutiliser l’identité signal_key pour les événements de contrats. |
| Exports | Aucun endpoint d’export national. export_level est seulement un droit de catalogue. | Créer un job et un snapshot propres ; aucun export synchrone silencieusement tronqué. |
| Flag existant | KIVOU_COMPANY_DIRECTORY_ENRICHMENT_ENABLED=false. | Ne couvre aucune des quatre frontières Company First. |
| Flags V1 | Absents. | Ajouter quatre flags indépendants, tous false par défaut, listés en §4.5. |

### 3.5 Migrations et données mesurées

- Head Alembic unique constaté : 0067_acceptance_error_cleanup.
- Le prochain identifiant n’est volontairement pas inventé dans L0. Chaque PR
  de schéma résoudra le head courant juste avant création.
- Le rapport daté docs/reports/prospecting-v11/company-continuity-live.md
  consigne une ancienne répétition : 284 545 lignes sur 33 tables, 33
  entreprises, 755 snapshots et 1 638 faits BOAMP ; un autre instantané y
  mentionne 876 lignes d’annuaire publiables. **M :** ce périmètre BOAMP/V11
  n’est ni un volume national actuel ni une distribution CPV.
- La matrice docs/reports/prospecting-v11/qa-matrix.md consigne un ancien
  backfill borné de 434 avis/1 154 lots, dont 825 lots avec faits. **M :** cette
  sélection de profils actifs ne mesure pas la couverture France.
- **A :** volumes DECP/BOAMP/TED, intersections, CPV, dates, pays acheteur,
  identités SIREN/SIRET, montants et taux de quarantaine devront être mesurés
  en L1 sur une copie autorisée, avec requêtes et horodatage publiés.

## 4. Architecture retenue

Trois options ont été examinées :

1. Requêter directement les JSON de contract_award. Écartée : identité,
   versions, participations, conflits et indexation resteraient ambigus.
2. Construire un second entrepôt de faits autonome. Écartée : deux vérités,
   migration risquée et divergence avec les preuves déjà conservées.
3. **Étendre le journal de faits existant et produire une projection
   reconstruisible. Retenue.** source_event, contract_award, evidence et
   opportunity_representation restent les faits/liaisons historiques. Les
   observations ajoutent la version absente ; la projection nationale ne
   contient que l’état de lecture dérivable et ses références de preuve.

Le chemin cible est :

source → observation immuable ou quarantaine → représentation source
contract_award → décision de lien → projection de contrat canonique →
participations SIREN/SIRET → recherche/snapshot → fiche, liste, export ou
alerte. materialized_signal consomme éventuellement ces faits, mais n’est
jamais un prérequis.

### 4.1 Tables existantes réutilisées

- source_event, contract_award, evidence et opportunity_representation :
  événements et représentations de source.
- supplier_directory : projection courante d’une unité légale française,
  identifiée par SIREN.
- company_subject_alias et account_company_alias_override : résolution publique
  et continuité du sujet privé.
- account_company_membership, company_contact, company_note et
  company_manual_contact : suivi privé existant.
- account_notification_preference et signal_alert_job_lease : préférence,
  lease et transport d’alertes, sans réutiliser signal_alert_delivery.
- product_event : télémétrie produit sans contenu source ni donnée personnelle
  supplémentaire.

### 4.2 Tables additives normatives

Ces noms sont arrêtés pour L1–L5. Tout changement devra amender ce L0 dans la
PR concernée, avec sa raison.

| Table | Propriété et rôle |
|---|---|
| source_event_observation | Journal immuable : source/notice/version, hash, URL ou référence brute durable, observed_at, parser_version, résultat et lien event_key. Unicité identité source + hash. |
| contract_award_observation | Valeurs normalisées d’un contrat/lot dans une observation, avec payload versionné, preuves de champs et lien award_key. La dernière observation n’est pas automatiquement la vérité. |
| ingestion_quarantine | Item isolé non publiable : source/fenêtre/cursor/item/hash, code fermé, contexte sans secret, parser, essais, résolution et replay. |
| public_award_coverage_window | Source, bornes, partition, état, volumes acquis/persistés/quarantaines/indisponibles et dates de réussite ; seule source des déclarations de couverture. |
| public_company_identity_observation | Preuves temporelles SIREN/SIRET, nom, pays, état de diffusion/activité, source, référence, hash et observed_at. |
| public_company_establishment | Projection courante SIRET→SIREN, état et géographie d’établissement ; supplier_directory reste la projection unité légale. |
| public_contract_projection | Une ligne reconstruisible par opportunity_key : état actif/annulé/incertain, objet, acheteur/pays, CPV, géographies, horloges séparées, montant/nature/portée/TVA, conflits, révision et suppression. |
| public_contract_link_decision | Historique immuable des décisions award_key→opportunity_key : méthode, espace d’identifiants, critères, confiance, policy_version et supersession. |
| public_contract_alias | Ancienne opportunity_key vers clé canonique, provenance, décision, dates et état de redirection réversible. |
| public_contract_participation | Participation canonique : opportunity_key, company_key/SIREN/SIRET ou identité non résolue, rôle, part attribuable, preuve et qualité. Une participation étrangère/non résolue reste présente. |
| public_contract_projection_event | Séquence monotone new_publication, late_discovery, correction, cancellation ou suppression ; backfill explicite ; source des watermarks et outbox. |
| company_award_search_snapshot | Snapshot privé au compte : filtres/version, droits/version, révision projection, epoch de suppression, création, expiration 30 min, révocation et total. |
| company_award_search_snapshot_item | Ordre et payload figés par entreprise, métriques et clés des contrats admissibles ; clé primaire snapshot + ordinal. |
| account_company_list | Liste statique nommée, possédée par le compte, révision et tombstone. |
| account_company_list_member | Membre unique compte/liste/company_key, ajout/retrait idempotent et résolution d’alias auditée. |
| account_company_saved_search | Filtres/version et période fixe ou glissante avec fuseau et règle de fin de mois ; aucun résultat copié. |
| account_company_award_alert | Activation explicite sur suivi ou recherche, cadence/fuseau, watermark, droits/version et état. |
| account_company_award_alert_delivery | Déduplication compte + contrat canonique + type/version d’événement, recherches concernées, batch/état/tentatives. |
| account_company_export_job | Type companies ou awards, compte, droits, filtre/snapshot, quota réservé, état, fichier/référence, expiration 24 h et invalidation. |
| account_company_export_row | Périmètre et valeurs autorisées figés à l’acceptation, une ligne ordonnée par job ; rendu CSV déterministe et indépendant du curseur de navigation. |

Les payloads JSON d’observation sont versionnés et validés à l’écriture ; les
colonnes de public_contract_projection et public_contract_participation portent
les champs filtrables. Aucun filtre national ne scanne un JSON en mémoire.

### 4.3 Index et contraintes normatifs

- uq_source_event_observation_identity_hash ;
  ix_source_event_observation_source_observed.
- uq_contract_award_observation_identity_hash ;
  ix_contract_award_observation_award_observed.
- uq_ingestion_quarantine_item_hash ;
  ix_ingestion_quarantine_source_status_retry.
- uq_public_award_coverage_window_source_bounds.
- ix_public_company_establishment_siren_status.
- ix_public_contract_projection_contract_date_key ;
  ix_public_contract_projection_publication_date_key ;
  ix_public_contract_projection_buyer_country_identifier ;
  ix_public_contract_projection_cpv ;
  ix_public_contract_projection_execution_geo.
- ix_public_contract_participation_company_contract ;
  ix_public_contract_participation_contract_role ; unicité déterministe de la
  participation canonique pour empêcher deux SIRET d’un SIREN de doubler un
  contrat.
- uq_public_contract_link_decision_current, index partiel sur la décision
  courante d’une représentation ; public_contract_alias.alias_opportunity_key
  est unique.
- company_award_search_snapshot_item a pour PK (snapshot_id, ordinal) et un
  index (snapshot_id, company_key).
- account_company_list_member a pour PK (account_id, list_id, company_key).
- account_company_award_alert_delivery a une unicité
  (account_id, opportunity_key, event_type, event_version).
- account_company_export_row a pour PK (job_id, ordinal).

Les migrations créent d’abord tables/colonnes nullable et index adaptés ; les
index PostgreSQL lourds sont construits séparément et, si nécessaire,
concurrently hors transaction avec garde opérateur. Le backfill n’est jamais
une étape Alembic.

### 4.4 Contrats HTTP et frontend normatifs

Recherche et fiche :

- GET /companies/award-holders/options
- GET /companies/award-holders
- GET /companies/directory/{siren}/awards
- GET /companies/directory/{siren} reste la fiche canonique et reçoit seulement
  un résumé public versionné ; l’historique complet passe par la route paginée.
- Route frontend /app/companies/award-holders, troisième vue intégrée à
  CompaniesPage ; CompanyDossier reste le dossier partagé.

Actions privées :

- GET et POST /company-lists
- PATCH et DELETE /company-lists/{list_id}
- PUT et DELETE /company-lists/{list_id}/members/{company_key}
- GET et POST /company-award-searches
- PATCH et DELETE /company-award-searches/{search_id}
- GET et POST /company-award-alerts
- GET, PATCH et DELETE /company-award-alerts/{alert_id}
- POST /company-award-exports
- GET /company-award-exports/{export_id}
- GET /company-award-exports/{export_id}/download

Le curseur de recherche contient seulement un identifiant aléatoire de snapshot
et une position opaque. Le serveur recharge compte, filtre, droits, révision et
epoch de suppression depuis la base. Toute divergence donne une erreur stable ;
aucune transaction PostgreSQL ne reste ouverte entre deux requêtes.

Le moteur de prédicats partagé sera placé dans
src/signals/company_awards/query.py. Recherche, fiche contextualisée, export et
alerte l’appellent avec le même contrat de filtres versionné ; aucun de ces
consommateurs ne réimplémente dates ou argent.

### 4.5 Capacités et flags normatifs

Nouvelles capacités serveur, distinctes des droits du feed :

- can_search_public_awards
- can_view_public_award_details
- public_award_history_days
- can_export_public_companies
- public_company_export_limit
- can_alert_public_awards
- public_award_alert_cadence

Elles sont false, 0 ou none pour Discovery, Essential et Pro tant que la
politique commerciale n’est pas approuvée. Les tests injectent des droits
explicites ; une activation d’environnement ne peut donc pas contourner le
catalogue.

Flags dans src/signals/api/config.py, tous false par défaut :

- KIVOU_COMPANY_AWARDS_PROJECTION_ENABLED
- KIVOU_COMPANY_AWARDS_READS_ENABLED
- KIVOU_COMPANY_AWARDS_EXPORTS_ENABLED
- KIVOU_COMPANY_AWARDS_ALERTS_ENABLED

Projection ne donne aucun droit de lecture ; reads ne donne ni export ni
alerte. Export et alerte exigent aussi reads, la capacité courante et le droit
du compte. Le rollback coupe lecteurs et jobs, sans supprimer les nouvelles
tables.

## 5. Matrice exigence → existant → écart → test

### 5.1 Décisions et périmètre

| Exigence | Existant prouvé | Écart / décision | Lot et preuve attendue |
|---|---|---|---|
| DEC-01 | Les faits sont écrits avant l’inférence, mais la lecture entreprise passe encore par saas_company/materialized_signal. | Projection publique indépendante obligatoire. | L1/L3, T01 et T17. |
| DEC-02 | supplier_directory est global ; notes, suivi et alias privés portent account_id. | Ne jamais élargir /companies en retirant account_id ; routes dédiées. | L3, T13/T13b. |
| DEC-03 | Le directory GET ne fait pas d’appel fournisseur ; enrichissement est un job flaggé. | Étendre cette propriété à recherche, fiche, liste et export. | L3–L5, T17 + spies fournisseurs. |
| DEC-04 | Essential vaut actuellement 49 EUR ; aucun droit Company First n’existe. | Prix constaté ≠ autorisation du module. Catalogue inchangé. | L6, décision humaine ; test de packaging inchangé. |
| DEC-05 | CONTRIBUTING et CI imposent branches/PR/tests. | Aucun déploiement ou service externe dans L0–L5. | Chaque lot : SHA, diff, tests, limites, PR. |
| SCOPE-01 | source_country, winner_country et place_country existent partiellement, mais source_country n’est pas toujours le pays acheteur. | Modéliser pays acheteur/titulaire/exécution séparément ; base = acheteur FR prouvé. | L1/L2, T09 et corpus transfrontalier. |
| SCOPE-02 | Historique persistant et backfills bornés existent ; lookbacks initiaux 3–30 j. | Plan 24 mois, fenêtres de couverture et indisponibilités manquent. | L1, dry-run + rapport public_award_coverage_window. |
| SCOPE-03 | BOAMP conserve des motifs de skip en mémoire ; CPV absent accepté par plusieurs parseurs. | Exclusions durables ; aucun filtre BTP/CPV implicite ; brut/référence conservé. | L1, T01 et T18. |

### 5.2 Ingestion

| Exigence | Existant prouvé | Écart / décision | Lot et preuve attendue |
|---|---|---|---|
| ING-01 | checkpoint/run par source, clés idempotentes, TED/DECP ont des curseurs fins. | Acquittement seulement après fait ou ingestion_quarantine ; preuve de pagination complète. | L1, T18 crash/replay. |
| ING-02 | Erreurs catégorisées ; retries TED 202/429 ; un échec de mapping arrête encore certaines sources. | Quarantaine isolée/replay et poursuite ; retry/backoff borné homogène. | L1, T18/T18b. |
| ING-03 | URL, ID/version et discovered_at existent ; procedure_documents possède parfois hash/archive. | Généraliser observation hash/parser/référence brute sans inférer une annulation par absence. | L1/L2, T07b. |
| ING-04 | CLI dry-run et bornes existent pour certains backfills. | Contrat commun : dry-run défaut, bornes, batch, volume, progression, pause/reprise et autorisation base partagée. | L1, tests CLI + rapport dry-run 24 mois. |
| ING-05 | Timers et checkpoints peuvent exécuter quotidiennement ; aucun SLO national mesuré. | Mesurer publication amont et traitement Kivou séparément ; cible 24 h reste un paramètre de recette. | L1/L6, métriques datées par source. |
| ING-06 | Catégories rate_limited/systemic existent, sans quarantaine durable ni coupe-circuit de ratio. | Classifier item vs système, seuil de quarantaine, source fail-closed et alerte. | L1, T18b tous-invalides/429. |

### 5.3 Identités et déduplication

| Exigence | Existant prouvé | Écart / décision | Lot et preuve attendue |
|---|---|---|---|
| ID-01 | supplier_directory est par SIREN ; l’identité de signal privilégie aujourd’hui le SIRET. | Projection SIRET→SIREN corroborée, SIRET d’origine conservé. | L2, T04/T05b. |
| ID-02 | Alias exact/unresolved et politiques de validation existent ; history.py garde un repli nom+lieu. | Interdire ce repli dans les résultats certifiés ; motif non résolu durable. | L2/L3, T03/T17. |
| ID-03 | Annuaire unitaire par SIREN. | Ajouter établissements, historique nom/statut et temporalité sans fusion de groupes. | L2, T04. |
| ID-04 | Alias public et override privé existent. | Redirection auditée/réversible et rejeu idempotent, sans fusion des sujets privés. | L2/L5, T13/T13b. |
| ID-05 | awardee_parties JSON peut conserver étrangers/non résolus. | Les projeter relationnellement sans les exclure des taux. | L2/L4, corpus identité non résolue. |
| DEDUP-01 | opportunity_representation relie les liens forts BOAMP↔DECP. | Historiser méthode/critères/confiance et espaces d’identifiants ; TED inclus. | L2, T02/T02b/T03. |
| DEDUP-02 | Les liens probables peuvent rester séparés, sans contrat d’agrégat fiable. | État de cluster, exclusions et compteurs explicites. | L2/L3, T03 + MONEY-02. |
| DEDUP-03 | Les insertions sont immuables mais correction/avenant/annulation ne sont pas projetés. | Projection courante versionnée, statut actif, historique conservé et rôles séparés. | L2, T07. |
| DEDUP-04 | Une même award_key n’est pas mise à jour ; pas de priorité par champ. | Observations par hash, filiation/règles par champ, conflits exclus des totaux. | L1/L2, T07b. |
| DEDUP-05 | Une convergence tardive de deux opportunités lève actuellement un conflit. | public_contract_alias + propagation idempotente ; ancienne URL redirigée sous mêmes droits. | L2/L5, T02b/T13b. |

### 5.4 Argent et dates

| Exigence | Existant prouvé | Écart / décision | Lot et preuve attendue |
|---|---|---|---|
| MONEY-01 | contract_award.amount est Numeric et le domaine utilise Decimal/Money ; france/link compare encore par float. | Retirer tout float ; ajouter nature, portée, part, preuve/version ; inconnu = null. | L2, T05–T07b. |
| MONEY-02 | history.py compte et somme par devise sans complétude ni parts. | Implémenter les deux métriques normatives et toutes les exclusions/complétudes. | L2/L3, T03/T05/T11. |
| MONEY-03 | Aucun filtre de valeur qualifiée national. | fixed/ceiling/estimate, EUR HT et cumul attribuable distincts, même moteur de prédicats. | L3, T06/T11/T24. |
| DATE-01 | Attribution, signature, notification, début, fin, publication et découverte sont majoritairement séparées. | Ajouter provenance/précision par champ dans observation/projection. | L2, T07b/T08. |
| DATE-02 | history.py replie attribution→notification→publication sans type visible partout. | Par défaut attribution sinon notification ; publication jamais substitut caché. | L2–L4, T08/T24. |
| DATE-03 | Aucun mode national publication explicite. | Filtre/date_kind publication et libellé « Publié le ». | L3/L4, T08. |
| DATE-04 | Dates civiles et timestamps timezone-aware coexistent. | Formaliser bornes inclusives Europe/Paris et fonctions partagées. | L2/L3, T19b/T24. |
| DATE-05 | discovered_at existe. | Conserver first_observed_at et event late_discovery, copie non trompeuse. | L2/L4/L5, T08/T19. |
| DATE-06 | Signature, début et fin existent. | Les propager sans déplacer award_date lors d’une correction. | L2/L4, T07/T08. |

### 5.5 Architecture, recherche et fiche

| Exigence | Existant prouvé | Écart / décision | Lot et preuve attendue |
|---|---|---|---|
| ARCH-01 | Les GET directory sont sans fournisseur ; alertes possèdent leases/idempotence. | Projection et événements écrits hors GET ; outbox durable public_contract_projection_event. | L1–L5, T17/T18/T19. |
| ARCH-02 | Tables publiques et privées sont déjà séparées par account_id. | Nouvelles actions toutes account-owned ; agrégats exclusivement publics. | L3–L5, T13/T13b. |
| ARCH-03 | Head 0067 unique ; inventaire et noms fixés aux §3–4. | Créer uniquement migrations additives depuis le head alors courant. | Chaque PR schéma, T23. |
| ARCH-04 | Directory filtre/trie/compte en SQL ; history limite puis agrège un ensemble incomplet. | Index normatifs et CTE SQL sur tous les contrats admissibles avant tri/pagination. | L3, T10/T11/T12 + EXPLAIN. |
| ARCH-05 | Clés cmp_directory, alias/override/private_subject existent ; repli nom+lieu existe. | Seuls liens exacts/corroborés alimentent Titulaires certifiés ; garder les garde-fous privés. | L2–L4, T03/T04/T13. |
| SEARCH-01 | Pas de moteur national ; les filtres actuels sont annuaire ou feed. | Un unique CTE produit M par entreprise, puis agrégats et seuils ; OU interne/ET externe. | L3, T10/T11/T24. |
| SEARCH-02 | Directory renvoie identité/localité/suivi/capacités. | Ajouter métriques qualifiées, dernière date/type et aucune coordonnée par défaut. | L3, tests contrat API. |
| SEARCH-03 | Curseur directory = offset + fingerprint ; pas de snapshot/droits/compte. | Snapshot privé, ordre stable, inconnus derniers, curseur opaque et erreurs explicites. | L3, T12/T14. |
| SEARCH-04 | CompaniesPage synchronise déjà URL, vue/filtres, annule les réponses obsolètes. | Étendre aux filtres titulaires, sélection et position. | L3, T22 frontend. |
| SEARCH-05 | États annuaire et responsive existent partiellement. | Ajouter huit états exacts, 390/1440/2560, clavier/focus, sans chiffres fictifs. | L3, T21/T22 + visuels. |
| SEARCH-06 | Aucun snapshot ; rows mutables entre pages. | Matérialisation bornée 30 min choisie, payload/ordre figés, révocation droits/diffusion prioritaire. | L3, T12/T14/T16. |
| PROFILE-01 | evidence permet chemin, brut et extrait ; source_url est affichée. | Chaque champ majeur de projection référence une preuve, pas URL seule. | L2/L4, T07b/T15. |
| PROFILE-02 | market_summary affiche des totaux sans phrase de couverture normative. | Copier couverture disponible, complétude et interdictions d’inférence économique. | L4, T03/T05/T21. |
| PROFILE-03 | Besoins/matches sont déjà des champs inferred dans materialized_signal. | Section Analyse commerciale séparée, optionnelle, jamais garde d’accès. | L4, T01/T17. |

### 5.6 Listes, alertes et exports

| Exigence | Existant prouvé | Écart / décision | Lot et preuve attendue |
|---|---|---|---|
| ACT-01 | account_company_membership suit une entreprise ; notes/statuts sont réutilisables. | Listes nommées et recherches sauvegardées distinctes, membres uniques et mutations idempotentes. | L5, T13/T13b. |
| ACT-02 | Aucun contrat de période sauvegardée. | Stocker fixed ou rolling, timezone et end-of-month ; calcul partagé à l’exécution. | L5, T19b/T24. |
| ALERT-01 | Préférence email compte et alertes de signaux existent. | Activation par recherche/suivi, uniquement vers le client ; aucune campagne. | L5, T19 + SEC-03. |
| ALERT-02 | Le registre signal évite les renvois, mais n’a pas de watermark/backfill public. | Watermark à l’activation, aperçu, backfill exclu du digest. | L5, T19. |
| ALERT-03 | Déduplication actuelle = compte + signal. | Séquence projection, types d’événement et unicité compte+contrat+type/version, recherches recoupées. | L5, T02/T02b/T19b. |
| ALERT-04 | Livraison durable, Message-ID, leases et état inconnu existent ; cadence vient du plan. | Lundi 08:00 Europe/Paris par défaut, configurable, aucun email vide ; réutiliser la politique ambiguë. | L5, T19. |
| ALERT-05 | Le job actuel revalide préférence et droit avant envoi. | Étendre aux droits publics, suppression/diffusion et fenêtre d’historique. | L5, T14/T16/T19. |
| EXPORT-01 | Aucun export national. | Deux types figés, métadonnées complètes et participations non assimilées à du revenu. | L5, T05/T06/T20/T24. |
| EXPORT-02 | Les DTO actuels n’ont pas les colonnes normatives. | Schémas de colonnes versionnés companies-v1 et awards-v1, sans données privées/nominatives. | L5, tests golden CSV. |
| EXPORT-03 | Aucun job/quota/fichier national. | CSV UTF-8 sûr, async, réservation atomique, succès débité une fois, auth/droit/expiration 24 h. | L5, T15/T16/T20. |
| EXPORT-04 | Directory pagine mais ne sait pas exporter. | Refus explicite au-delà du plafond, identifiants texte, scope figé par export rows et réservation libérée. | L5, T20. |

### 5.7 Droits, API, sécurité et exploitation

| Exigence | Existant prouvé | Écart / décision | Lot et preuve attendue |
|---|---|---|---|
| RIGHT-01 | Catalogue/paywall actuels sont testés ; aucun droit national. | Nouvelles capacités fermées et flags off ; aucun changement Stripe. | L3–L5, tests catalogue et T14/T17. |
| RIGHT-02 | feed_access et projection directory revalident au serveur. | Toutes les surfaces publiques utilisent compte + rights_version + projection + suppression epoch. | L3–L5, T13/T14/T16. |
| RIGHT-03 | product_event mesure déjà des actions produit. | Ajouter événements de recherche/liste/contact/réutilisation sans conclure à la valeur ni journaliser le contenu. | L5/L6, rapport commercial humain. |
| API-01 | api_error fournit codes stables sur plusieurs routes. | Ajouter invalid_filter, invalid_cursor, insufficient_rights, not_found uniforme, quota_exceeded, snapshot_expired, source_degraded. | L3–L5, tests de contrat négatifs. |
| API-02 | SQLAlchemy paramètre les requêtes ; directory échappe contains ; certaines URLs sont validées côté UI. | Validation http(s) serveur, texte source inerte, suppression invalide snapshots/caches. | L3–L5, T15/T16 + tests injection. |
| SEC-01 | supplier_directory.suppressed_at et tombstones privés existent. | Propagation à projection, snapshots, suggestions, alertes et exports encore actifs via suppression epoch. | L2–L5, T16. |
| SEC-02 | Données enrichies premium sont projetées par droits et fournisseur. | Les exclure de la liste/export national ; toute extension contact reste hors périmètre. | L3–L5, T15 + test absence champs. |
| SEC-03 | Campagnes et Policy Gateway ont des services séparés. | Aucune route Company First ne les appelle ; pas de CTA implicite d’envoi. | L3–L5, T17 + test d’architecture. |
| OPS-01 | Head, version et schéma inventoriés ; plusieurs outils dry-run existent. | Une PR DDL puis jobs de backfill séparés, bornés, rapportés, jamais au startup. | L1/L2, T23. |
| OPS-02 | Aucun sizing du corpus national autorisé dans L0. | Gate opérateur préalable : lignes/octets, index, WAL/temp, backup, batch pilote et seuil d’arrêt. | L1/L6, rapport de capacité ; bloque base partagée. |
| OPS-03 | Un flag enrichissement existe ; aucun flag national. | Quatre flags exacts du §4.5, off, rollback applicatif non destructif. | L1–L5, T23. |
| PERF-01 | Anciennes mesures V11 ne couvrent pas cette recherche. | Benchmark explicite 1 M contrats/100 k entreprises + échantillon réel ; p95 1,5 s et export 1 000 ≤60 s restent des seuils à mesurer. | L6, rapport matériel/cache/plans/mémoire. |
| PERF-02 | Directory fait des lectures batch ; dossier/history peut faire plusieurs requêtes bornées. | Requêtes set-based, preuves/participations batch, aucun fichier source par GET, limites conservées. | L3–L6, compteur SQL + profils. |

## 6. Carte de recette T01–T24

Les fixtures sont versionnées et hors réseau. Les tests d’intégration utilisent
PostgreSQL jetable ; les sources réelles sont des échantillons publics figés,
identifiés comme tels. Aucun résultat attendu ne sera dérivé du code testé.

| Scénarios | Lot principal | Fichiers de test prévus |
|---|---|---|
| T01, T08, T18, T18b, T21 | L1 | tests/test_public_award_ingestion.py, tests/test_public_award_coverage.py, extensions de test_decp_client.py, test_ted_connector.py et test_ingestion_runner.py |
| T02, T02b, T03, T04 | L2 | tests/test_public_contract_identity.py, tests/test_public_company_identity.py, régressions dans test_company_entity_aliases.py et test_company_identity_concurrency.py |
| T05, T05b, T06, T07, T07b, T09, T11 | L2 | tests/test_public_contract_projection.py, tests/test_public_award_money.py et tests/test_public_award_dates.py |
| T10, T12, T14, T17 | L3 | tests/test_company_award_search_api.py, tests/test_company_award_snapshots.py et test_billing_entitlements.py |
| T21, T22 | L3 | frontend/src/companies/CompanyAwardHoldersPage.test.tsx et tests Playwright 390/1440/2560 |
| T05–T09, T13–T17, T22, T24 | L4 | tests/test_company_award_profile_api.py et frontend/src/prospecting/__tests__/company-award-profile.test.tsx |
| T13, T13b, T19, T19b | L5 | tests/test_company_award_actions.py et tests/test_company_award_alerts.py, plus régressions test_alerts_cycle.py |
| T15, T16, T20 | L5 | tests/test_company_award_exports.py et tests/test_company_award_security.py |
| T23 | L1–L5 | tests/test_company_award_migrations.py sur ancienne application compatible, flags off et base peuplée synthétique |
| T24 | L3–L5 | tests/test_company_award_query_consistency.py : même moteur de prédicats pour recherche, fiche, export et alerte |
| PERF-01/02 | L6 | tests/benchmarks/company_awards_search.py et rapport daté, jamais inclus dans la suite unitaire ordinaire |

Le corpus métier final contient au moins 100 contrats/participations, cinq
familles sectorielles, les trois sources, CPV absent, groupements, corrections,
annulations, conflits et champs inconnus. Les T02b, T05b, T07b, T13b, T18b et
T19b sont des scénarios obligatoires, pas des notes facultatives.

## 7. Plan de branches, PR et migrations

Chaque lot repart du main alors courant dans un worktree propre, écrit d’abord
les tests RED, puis le minimum GREEN. Une PR ne dépend jamais d’une migration
non fusionnée d’une autre branche sans base explicitement mise à jour.

### L1 — couverture factuelle

**Branche proposée :** feat/company-first-ingestion-foundation.

**Fichiers :**

- src/signals/persistence/schema.py et une nouvelle migration depuis le head
  réel : source_event_observation, contract_award_observation,
  ingestion_quarantine, public_award_coverage_window.
- src/signals/company_awards/observations.py,
  src/signals/company_awards/quarantine.py et
  src/signals/company_awards/coverage.py.
- src/signals/ingestion/sources.py, runner.py et pipeline.py.
- Connecteurs DECP/TED/BOAMP strictement pour partition secondaire, mapping
  pays, familles nécessaires et classification item/système.
- Tests T01, T08, T18, T18b, T21 et CLI dry-run.

**Migration/backfill :** DDL seulement dans Alembic. Un CLI séparé
src/signals/company_awards/backfill.py est dry-run par défaut, borné et
interdit sur base partagée sans option/autorisation explicite. La PR ne lance
aucun backfill.

### L2 — identité et projection canonique

**Branche proposée :** feat/company-first-contract-identity.

**Fichiers :**

- Migration additive pour public_company_identity_observation,
  public_company_establishment, public_contract_projection,
  public_contract_link_decision, public_contract_alias,
  public_contract_participation et public_contract_projection_event.
- src/signals/company_awards/identity.py, linking.py, projection.py, money.py,
  dates.py et proofs.py.
- Adaptation bornée de opportunity_representation et du rapprochement France ;
  aucun changement de materialized_signal requis pour publier.
- Tests T02–T07b, T09, T11 et T23.

**Migration/backfill :** colonnes/tables vides compatibles avec l’ancienne
application ; projection reconstruite par job borné après la PR et seulement
sur environnement autorisé.

### L3 — recherche nationale

**Branche proposée :** feat/company-first-search.

**Fichiers :**

- Migration additive pour company_award_search_snapshot et
  company_award_search_snapshot_item.
- src/signals/company_awards/contracts.py, query.py, snapshots.py et rights.py.
- src/signals/api/routes_company_awards.py, app.py, config.py,
  client_value/capabilities.py et contrats Pydantic.
- frontend/src/api/endpoints.ts, frontend/src/api/types.ts,
  frontend/src/companies/CompaniesPage.tsx et nouveau composant
  CompanyAwardHoldersPage.tsx ; App.tsx et AppShell.tsx pour route/état.
- Tests T10–T14, T17, T21, T22 et contrats d’erreur.

**Activation :** projection et reads restent off ; capacités de tous les plans
restent fermées hors fixtures de test.

### L4 — fiche et preuves

**Branche proposée :** feat/company-first-profile.

**Fichiers :**

- src/signals/api/routes_companies.py et routes_company_awards.py pour résumé et
  historique paginé.
- src/signals/company_awards/profile.py et proofs.py.
- frontend/src/prospecting/components/CompanyDossier.tsx et types/endpoints.
- Tests T05–T09, T13–T17, T22, T24 et visuels.

**Compatibilité :** le tableau markets actuel reste lisible pendant la
transition ; la nouvelle section utilise le contrat versionné et ne réécrit
pas l’analyse commerciale.

### L5a — listes et recherches sauvegardées

**Branche proposée :** feat/company-first-saved-actions.

**Fichiers :**

- Migration additive account_company_list,
  account_company_list_member et account_company_saved_search.
- src/signals/company_awards/actions.py et routes privées dédiées.
- UI listes/recherches dans l’espace Entreprises.
- Tests ACT-01/02, T13/T13b/T19b/T24.

### L5b — exports et alertes

**Branche proposée :** feat/company-first-exports-alerts.

**Fichiers :**

- Migration additive public_contract_projection_event,
  account_company_award_alert, account_company_award_alert_delivery,
  account_company_export_job et account_company_export_row si la table
  d’événements n’a pas déjà été livrée en L2.
- src/signals/company_awards/alerts.py, exports.py et csv.py ; adaptation du
  job d’alertes pour partager transport/lease, pas les identités signal.
- Routes export/alerte et UI de suivi.
- Tests T15, T16, T19, T19b, T20, T24, concurrence et timeout ambigu.

**Activation :** flags exports/alerts off, zéro envoi externe en test ; gateway
fake. Aucun fichier durable au-delà de son expiration.

### L6 — recette et décision

**Branche proposée :** docs/company-first-release-evidence.

Rapports seulement : couverture/qualité, licences, benchmark, capacité
DB/WAL/index/backup, sécurité, droits, métriques produit et procédure de
rollback. L’activation, le tarif, les plans et le déploiement demandent une
décision humaine séparée.

## 8. Paramètres V1 et choix restant à approuver

### Paramètres normatifs de la V1

- Acheteur français prouvé, entreprises françaises prouvées par défaut ;
  transfrontalier conservé et catégorisé.
- Cible de reprise 24 mois, sans déclaration de couverture avant fenêtres
  réellement traitées/qualifiées.
- Recherche multi-sectorielle, CPV absent autorisé, concessions hors MVP mais
  observations conservées.
- Date par défaut attribution sinon notification ; mode publication explicite.
- EUR HT fixe pour la somme fiable et le filtre monétaire par défaut.
- Snapshot de navigation 30 minutes ; export expirant après 24 heures.
- Digest hebdomadaire lundi 08:00 Europe/Paris par défaut, sans email vide.
- Objectifs de recette p95 1,5 s et export 1 000 lignes ≤60 s, à mesurer.

### Choix qui bloquent uniquement activation ou opération partagée

| Choix | Responsable / preuve requise | Ce qui peut avancer avant |
|---|---|---|
| Mapping des capacités par plan, quotas, tarif éventuel 49 EUR | Produit + commercial + facturation ; validation packaging et checkout | Tout L0–L5 avec capacités fermées et fixtures |
| Licences, attribution et champs publiables DECP/BOAMP/TED/Sirene | Revue juridique/données datée et registre source | Parseurs, modèle, tests sur fixtures publiques |
| Inclusion précise des familles BOAMP MAPA/FNSimple ; concessions | Mesure de volume/qualité puis décision produit | Quarantaine, métriques et conservation brute |
| Backfill sur staging/production, fenêtres et limites | Autorisation opérateur, sizing, backup, seuils d’arrêt | CLI dry-run et tests jetables |
| Capacité CPU/DB/index/WAL/temp/stockage | Batch pilote sur copie autorisée | DDL et benchmark synthétique |
| Activation des quatre flags, déploiement et rollback | Go/no-go L6 humain | Fusion technique possible si CI/revue approuvées |
| Appels ou achats fournisseurs, campagnes, Hermes/Instantly | Mission séparée et autorisation explicite | Parcours factuel complet sans eux |

## 9. Gate de sortie L0

- SHA, instructions, routes, tables, droits, flags, sources et head Alembic :
  inventoriés.
- Matrice DEC-01 à PERF-02 : complète, avec lot et preuve attendue.
- T01 à T24, y compris variantes b : affectés à des tests.
- Tables, index, routes, capacités, flags et stratégie de snapshot : arrêtés.
- Mesures historiques séparées des faits de code et des inconnues LIVE.
- Plan de PR et migration : additif, reviewable, DDL séparé des backfills.
- Aucun effet externe ou état partagé modifié.

Le prochain lot autorisé par la spécification est **L1 uniquement**. Il devra
commencer par les tests RED de quarantaine/reprise et par une mesure dry-run
locale ; il ne devra ni lancer le backfill 24 mois ni activer un flag.

## 10. État de validation du socle

Ces commandes ont été lancées dans le worktree isolé sur le SHA de base, avant
toute modification de code :

- uv sync --locked : réussi.
- npm ci : réussi ; npm signale deux vulnérabilités modérées préexistantes,
  sans audit fix appliqué.
- uv run ruff check . : réussi.
- uv run pytest -q : 6 816 réussis, 61 ignorés, 1 xfail, 7 échecs en 668,74 s.
  Les sept échecs sont reproductibles en sélection ciblée : deux assertions de
  journalisation reset dans test_api_runtime.py, deux contrats du runbook dans
  test_ops_production_runtime.py, deux variantes de payload dans
  test_prospection_provider_bindings.py et l’allowlist de migrations dans
  test_pytest_configuration.py. Ils ne touchent pas ce document et ne sont pas
  corrigés dans L0.
- npm test -- --run : 873 réussis, 2 échecs dans
  referenceTargeting.test.tsx sous la charge complète. Le fichier rejoué seul
  passe 26/26 ; cette instabilité du socle reste à surveiller.
- Head Alembic relu par ScriptDirectory : 0067_acceptance_error_cleanup.

La CI de cette PR documentaire appliquera la décision docs-only du workflow.
Ces échecs de base sont néanmoins consignés afin qu’aucun lot ultérieur ne les
présente comme une régression Company First ou comme une suite entièrement
verte.
