# Fiche entreprise SaaS officielle — rapport technique

Date : 23 août 2026  
Branche : `feat/saas-company-profile-apollo`  
SHA de départ : `b75c87a22f3ff9da9a71b5bf64bb08633a4a7993`

## Résultat produit

La fiche entreprise est disponible sous `/app/companies/:companyKey` depuis le détail connecté d’un signal déverrouillé. Elle rassemble, dans cet ordre :

1. la raison sociale gagnante et les faits officiels publiés ;
2. les signaux Kivou actuellement accessibles qui concernent exactement cette entreprise ;
3. la lecture commerciale déjà calculée par Kivou : besoins plausibles, correspondance ICP et timing ;
4. les actions réellement disponibles ;
5. les sources, la date absolue d’observation et une limite compacte lorsque la couverture est partielle.

La page n’est ni un annuaire, ni une recherche libre, ni une fiche personne, ni un CRM, ni une surface de l’Acquisition Engine.

## Décision fournisseur

Apollo n’est pas intégré à cette tranche. Il n’existe :

- aucun client ou appel Apollo ;
- aucune clé ou configuration Apollo côté SaaS ou navigateur ;
- aucune donnée, mention ou identifiant Apollo dans le contrat client ;
- aucun cache, job ou retry fournisseur ;
- aucun coût fournisseur déclenché par l’ouverture d’une fiche.

Cette décision évite d’exposer des données Apollo dans une surface client sans autorisation contractuelle explicite. Les conditions API publiques décrivent un usage interne et renvoient les intégrations ou partages de données à un accord écrit adapté :

- <https://www.apollo.io/terms/api>
- <https://docs.apollo.io/docs/developer-faqs>

Une évolution future devra commencer par une validation contractuelle écrite distincte. Elle ne devra pas réutiliser les DTO de l’Acquisition Engine.

## Frontière SaaS

Le module `src/signals/companies/` possède ses propres objets client-safe :

- `CompanyProfile` ;
- `CompanyOfficialIdentity` ;
- `CompanyOfficialIdentifier` ;
- `CompanyRelatedSignal` ;
- `CompanyCoverage`.

Il dépend uniquement des faits publics, du feed SaaS, de la matérialisation et de l’accès de facturation existant. Des tests d’architecture interdisent les imports des modules acquisition, campagnes, recherche de contacts, recherche d’entreprise, personnalisation et découverte de fournisseurs.

Le frontend ne lit aucune table. Il consomme uniquement les routes SaaS authentifiées.

## Résolution de l’identité

La création de la clé opaque suit une résolution exacte et auditable :

1. identifiant officiel exact publié avec le pays ;
2. à défaut, domaine HTTPS officiel publié avec le pays ;
3. à défaut, identité limitée à l’opportunité source.

Le nom et le pays servent uniquement à retrouver l’organisation exacte au sein de l’avis qui porte déjà le gagnant affiché. Un nom seul ne fusionne jamais deux opportunités. Une correspondance approximative n’est pas utilisée.

La table `saas_company` conserve :

- la clé Kivou opaque aléatoire ;
- une empreinte SHA-256 normalisée ;
- la méthode et les éléments de validation ;
- les références vers l’avis et le signal d’origine ;
- la projection officielle autorisée ;
- les dates d’observation et de création.

Elle ne conserve aucun payload brut, donnée de personne, e-mail, téléphone direct, score, verdict ou objet fournisseur. La création est idempotente et converge sur l’empreinte unique en cas de concurrence.

## Contrat API

`GET /companies/{company_key}` est authentifié et renvoie :

```json
{
  "company_key": "cmp_opaque_random_key",
  "official_identity": {
    "name": "Entreprise SA",
    "country": "CH",
    "address": null,
    "identifiers": [],
    "website_url": null,
    "observed_at": "2026-08-23T12:00:00Z",
    "source": "public_notice"
  },
  "related_signals": [
    {
      "signal_id": "sig_current_unlocked",
      "contract_title": "Marché publié",
      "amount": null,
      "event": {
        "status": "recent_award",
        "date": "2026-08-20",
        "headline": "…",
        "why_now": "…",
        "award_date_note": null
      },
      "plausible_needs": [],
      "fit": { "label": "…", "reasons": [] }
    }
  ],
  "coverage": {
    "related_signals_complete": true,
    "unavailable_fields": []
  }
}
```

Le détail d’un signal déverrouillé peut ajouter `company_key`. Cette clé n’est jamais construite depuis le nom, le domaine, un identifiant officiel ou un identifiant fournisseur. Le détail verrouillé conserve sa forme existante et ne contient jamais cette clé.

Une clé absente, mal formée, étrangère au compte ou sans signal encore accessible reçoit la même réponse `404 company_not_found`.

## Autorisation

Une lecture de fiche revalide dans la transaction courante :

- la session et le compte authentifiés ;
- les ICP appartenant au compte et autorisés par le plan ;
- le statut actif de l’ICP et l’absence de limite territoriale ;
- la révision de matérialisation égale à la révision ICP courante ;
- l’absence d’invalidation ;
- l’identité officielle exacte ;
- le déverrouillage par le plan ou par une attribution Discovery permanente.

Les signaux verrouillés sont exclus. Si aucun signal autorisé ne reste, la fiche répond `404`. Une même entreprise peut être visible par deux comptes seulement lorsque chacun possède son propre signal courant et déverrouillé ; chaque réponse contient uniquement les signaux du compte appelant.

Chaque signal matérialisé porte une empreinte d’identité officielle opaque et indexée. La migration `0022` rétroprojette les lignes existantes par lots de 250 et la matérialisation maintient ensuite cette projection. La fiche ne charge que les lignes courantes du compte portant l’empreinte exacte ; elle ne reparcourt pas tous les signaux du compte. La résolution exacte et `FeedAccess.is_unlocked` précèdent toujours la limite de réponse de 100 signaux, afin qu’un grant Discovery ancien ne puisse pas être caché par des signaux verrouillés plus récents.

L’identité officielle de la réponse est reconstruite depuis un avis lié à ces signaux déverrouillés. L’instantané de création persiste pour l’audit et la déduplication, mais n’est jamais utilisé pour transmettre à un compte les champs optionnels observés uniquement par un autre compte.

## Données affichées

Faits officiels, lorsqu’ils existent :

- raison sociale ;
- pays ;
- adresse ;
- identifiants d’organisation ;
- site d’organisation HTTPS publié ;
- date absolue d’observation.

Contexte Kivou, uniquement depuis les signaux accessibles :

- marché et montant publiés ;
- événement et timing serveur ;
- besoins plausibles ;
- correspondance avec l’ICP et raisons existantes.

Le site est rendu seulement après une validation de domaine public HTTPS côté backend et une seconde validation défensive côté frontend. Les IP littérales et les hôtes locaux sont refusés. Le lien est externe, ouvre un nouvel onglet et porte `rel="noopener noreferrer"`.

## Coût, cache et limites

Le coût fournisseur est nul : aucun fournisseur n’est appelé. Il n’existe donc aucun TTL, retry, quota ou cache fournisseur à exploiter. La seule persistance nouvelle déduplique l’identité officielle normalisée ; les signaux restent lus depuis les matérialisations SaaS courantes.

Les limites restantes sont explicites :

- la fiche ne dispose d’aucun enrichissement sectoriel, d’effectif, d’année de création, de description ou de mots-clés ;
- le site n’est affiché que si l’avis public le publie en HTTPS ;
- la fiche ne révèle aucune coordonnée personnelle ou directe ;
- une évolution Apollo exige un accord contractuel écrit et une nouvelle revue produit, sécurité, coût et provenance ;
- un déploiement Alembic `--sql` hors ligne n'exécute pas la rétroprojection applicative : il faut alors lancer un backfill séparé avant d'exposer la route ; le chemin de promotion recommandé reste la migration Alembic en ligne ;
- la migration doit être promue selon le runbook habituel avant toute mise en production.

## Validation

Les tests backend couvrent les contrats fermés, la résolution exacte, l’idempotence, la migration SQLite/PostgreSQL, l’isolement inter-comptes, la séparation des faits officiels par avis accessible, les signaux verrouillés, la troncature après déverrouillage, Discovery, les invalidations et les révisions ICP.

Les tests frontend couvrent FR/EN, sources, date absolue, champs absents, URL sûre, états chargement/partiel/404/503/session expirée, navigation depuis le détail, absence de lien verrouillé, clavier, titres et absence de `sessionStorage`.

Un contrôle Firefox réel vérifie 1440, 1024, 768, 390 et 320 px : aucun débordement horizontal, contenu essentiel visible, un seul `main`, un seul `h1`, focus visible, lien externe sûr, retour/avance navigateur fonctionnel et aucune erreur console.

Les résultats complets des commandes de validation sont consignés dans la pull request de livraison.
