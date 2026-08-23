# Fiche entreprise SaaS fondée sur les sources officielles — Design

Date : 2026-08-23  
Statut : approuvé  
Branche : `feat/saas-company-profile-apollo`

## Décision

Kivou ajoute une fiche entreprise connectée sans intégration Apollo ni autre
fournisseur d'enrichissement. La fiche rassemble uniquement l'identité publiée
de l'entreprise gagnante et la valeur commerciale déjà calculée dans les
signaux Kivou actuellement accessibles au compte.

Cette décision remplace le volet Apollo de la demande initiale. Elle évite de
transformer le SaaS en surface d'acquisition, respecte l'autorité des avis
publics et garde l'intégration fournisseur hors production tant qu'aucun droit
contractuel spécifique n'est établi.

## Valeur et hiérarchie éditoriale

La page suit l'ordre : valeur commerciale, contexte, actions, sources, limites.

1. Le hero nomme la raison sociale officielle et résume le nombre de signaux
   accessibles, le pays et la dernière observation absolue.
2. La synthèse commerciale reprend les marchés remportés, montants publiés,
   événements, timing serveur, besoins plausibles et motifs d'adéquation ICP.
3. Les actions sont limitées à examiner un signal, revenir aux signaux et
   ouvrir le site officiel lorsqu'un avis le publie avec une URL HTTPS sûre.
4. La provenance distingue les faits issus de l'avis public des analyses Kivou.
5. Un message compact explique les champs officiels absents sans produire une
   succession de valeurs « non disponibles ».

## Frontière backend

Le paquet `src/signals/companies/` possède ses propres contrats client-safe :

- `CompanyProfile` ;
- `CompanyOfficialIdentity` ;
- `CompanyOfficialIdentifier` ;
- `CompanyRelatedSignal` ;
- `CompanyCoverage`.

Il ne dépend d'aucun module d'acquisition et n'expose aucun DTO interne. Une
barrière d'architecture interdira notamment les imports depuis `acquisition`,
`company_research`, `supplier_discovery`, `contact_discovery`, `campaigns`,
`personalization`, `compliance` et `policy`.

## Identité et clé opaque

La table SaaS `saas_company` contient une clé aléatoire `cmp_…`, une empreinte
d'identité Kivou et un instantané normalisé des faits officiels nécessaires à
l'audit de création. Cet instantané n'est pas l'autorité de la réponse client :
à chaque lecture, les faits affichés sont reconstruits uniquement depuis un
avis lié à un signal encore accessible au compte. La clé n'est jamais
construite par le navigateur et ne contient ni nom, ni domaine, ni identifiant
officiel.

L'identité est résolue dans cet ordre strict :

1. premier identifiant officiel non vide, avec son schéma et son pays ;
2. domaine HTTPS officiel publié dans l'avis, avec son pays ;
3. à défaut, l'opportunité publique Kivou elle-même.

Le nom seul n'est jamais une clé de rapprochement. Le troisième cas empêche
de fusionner deux sociétés homonymes : plusieurs matérialisations de la même
opportunité peuvent partager une fiche, mais deux opportunités distinctes ne
sont pas rapprochées sans identifiant ou domaine exact.

La création est idempotente et protégée par une unicité sur l'empreinte. Une
course concurrente converge vers la même clé sans exposer l'empreinte au
client.

## Autorisation

Le lien de fiche est ajouté uniquement à la réponse complète d'un détail de
signal déjà déverrouillé. Le payload verrouillé reste inchangé et ne contient
aucune clé entreprise.

`GET /companies/{company_key}` recalcule, dans la transaction courante :

- la session et le compte ;
- les ICP actifs autorisés par l'offre ;
- la révision ICP courante ;
- l'absence d'invalidation de la matérialisation ;
- la propriété par `target_icp.account_id` ;
- l'accès payant ou le déverrouillage Discovery permanent.

La fiche est rendue seulement si au moins un signal courant de cette identité
est déverrouillé pour ce compte. Les signaux liés suivent exactement les mêmes
règles. Une clé inconnue, une fiche étrangère, une fiche ne portant plus aucun
signal accessible ou une entreprise seulement liée à des signaux verrouillés
répondent toutes `404 company_not_found`.

Chaque matérialisation porte une empreinte d'identité officielle opaque,
calculée dans la frontière SaaS depuis l'avis public et indexée en base. La
migration rétroprojette les signaux existants par lots bornés et les écritures
suivantes maintiennent cette projection. La recherche d'autorisation interroge
donc uniquement les matérialisations courantes du compte portant l'empreinte
exacte, au lieu de parcourir tous ses signaux. `FeedAccess.is_unlocked` reste
appliqué avant la limite de réponse de 100 signaux : un grant Discovery ancien
ne peut pas être masqué par des signaux verrouillés plus récents.

L'identité officielle rendue est choisie seulement parmi les résolutions ainsi
déverrouillées. Deux comptes partageant une empreinte ne partagent jamais les
champs optionnels d'un avis auquel un seul des deux a accès.

La lecture réutilise la requête de feed actuelle avec `freshness=all`, puis
applique `FeedAccess.is_unlocked`. Elle ne modifie ni l'ordre du feed, ni les
limites Discovery, ni la politique de facturation.

## Contrat HTTP

```http
GET /companies/{company_key}
```

```json
{
  "company_key": "cmp_opaque",
  "official_identity": {
    "name": "Entreprise SA",
    "country": "CH",
    "address": "Rue Exemple 1, 1000 Lausanne",
    "identifiers": [{"scheme": "CHE-UID", "value": "CHE-123.456.789"}],
    "website_url": "https://entreprise.example",
    "observed_at": "2026-08-18T09:00:00Z",
    "source": "public_notice"
  },
  "related_signals": [
    {
      "signal_id": "opaque-signal-key",
      "contract_title": "Marché remporté",
      "amount": {"value": "1240000.00", "currency": "EUR"},
      "event": {
        "status": "recent_award",
        "date": "2026-08-04",
        "headline": "…",
        "why_now": "…"
      },
      "plausible_needs": [],
      "fit": {"label": "…", "reasons": []}
    }
  ],
  "coverage": {
    "official_identity_available": true,
    "address_available": true,
    "identifiers_available": true,
    "website_available": true
  }
}
```

Le contrat ne contient aucun score interne, verdict d'acquisition, contact,
payload fournisseur, référence de recherche ou donnée d'un signal verrouillé.

## Frontend

La route protégée `/app/companies/:companyKey` vit dans l'`AppShell` existant,
sans nouvel item de navigation ni dashboard. Le détail déverrouillé affiche un
CTA discret « Voir la fiche entreprise » / « View company profile ».

La page possède un seul `h1` et quatre sections :

1. entreprise identifiée ;
2. signaux Kivou liés ;
3. pourquoi cette entreprise mérite votre attention ;
4. sources et couverture.

Tous les champs absents sont masqués. Une couverture partielle produit un seul
message compact. Les liens externes sont limités à des domaines publics HTTPS
(ni IP littérale, ni hôte local), ouverts dans un nouvel onglet et portent
`rel="noopener noreferrer"`.

Les états prévus sont : chargement, fiche complète, identité officielle
partielle, fiche inaccessible, session expirée et absence de signal accessible.
Le dernier cas se confond volontairement avec la fiche inaccessible côté API.

## Migration et compatibilité

La migration additive `0022_saas_company_profile` crée la table
`saas_company` et ajoute à `materialized_signal` la seule colonne opaque
`company_identity_fingerprint`, avec son index. La migration rétroprojette les
signaux existants sans payload fournisseur ni donnée personnelle. Son downgrade
retire la table, l'index et cette colonne. Le modèle SQLAlchemy Core est déclaré
dans la frontière SaaS et la projection reste distincte des modules internes
du moteur.

Les tests de migration couvrent l'aller-retour SQLite, la parité avec
`METADATA`, la tête linéaire et le SQL PostgreSQL hors ligne. Ce dernier ne peut
pas exécuter la rétroprojection Python : un déploiement fondé uniquement sur
l'artefact `--sql` doit lancer le backfill applicatif séparément avant
d'exposer la route.

## Tests et garde-fous

Les tests backend couvrent l'authentification, l'isolation inter-comptes, les
signaux verrouillés, l'invalidation, les révisions ICP, les déblocages
Discovery, l'identité exacte, les homonymes, l'idempotence, la migration et
la séparation des faits officiels entre comptes, la sélection indexée avant
hydratation, le déverrouillage avant troncature et l'absence de champs internes.

Les tests frontend couvrent le rendu FR/EN, les champs officiels, les champs
absents, les liens sûrs, la navigation depuis un détail déverrouillé, l'absence
de lien verrouillé, les erreurs de session, le clavier, les titres et
l'absence de données sensibles dans la navigation ou `sessionStorage`.

La validation visuelle utilise un navigateur réel à 1440, 1024, 768, 390 et
320 pixels, avec contrôle du débordement horizontal, du focus et de la
hiérarchie des titres.

## Hors périmètre

Apollo, tout autre fournisseur d'enrichissement, les personnes, coordonnées
directes, décideurs, prospection, campagnes, CRM, dashboard, nouveau plan,
nouvel entitlement, modification du feed commercial, Acquisition Engine,
Instantly et déploiement restent hors périmètre.
