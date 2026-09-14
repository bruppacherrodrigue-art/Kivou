# Continuité entreprise, enrichissement et passage en production

## Autorisation et références

Le 14 septembre 2026, l'utilisateur a approuvé la proposition en cinq points puis
explicitement demandé son implémentation et sa mise en production. Ce document
est l'avenant au plan HTML V11 approuvé du 13 septembre, conservé sans réécriture
dans `/home/jaybe/projects/kivou-implementation-plan-2026-09-13/index.html`.
Il n'autorise aucun changement de tarification, de campagnes, de volumes d'envoi
ou d'autonomie d'acquisition.

## État vérifié avant travaux

- Espace isolé : `feat/prospecting-v11-staging`, HEAD `c83e034`, exécutable
  staging `7f2a2080bbc3dfe280d1a699e0e0e9183c30b203`.
- Production : `b72f06c614b7364ec10adf84b325090206f399f1`, schéma
  `0058_model_call_budget`. Cette branche apporte un moteur économique et un
  worker de titulaires qui doivent être conservés lors de l'intégration V11.
- Lecture SQL sans mutation : staging 33 entreprises visibles, dont 30 fiches
  `Entreprise test 01` à `Entreprise test 30`; production 876 entreprises visibles,
  dont 577 horodatées comme enrichies. 575 de ces dernières manquent à staging.
- À base identique, Founder et client lisent déjà `supplier_directory` : ne pas
  inventer un second annuaire métier ou modifier les périmètres privés.
- Les contacts BOAMP du titulaire sont affichés dans Signal, pas dans Entreprise.
- Le bouton déclare prêt un annuaire existant même incomplet ; son autre branche
  ne déclenche que l'identification du titulaire, pas l'enrichissement complet.

## Contrat produit

1. Une identité d'entreprise commune ; agences et membres de groupement restent
   attribués individuellement. Aucun contact de l'acheteur ne devient contact du
   titulaire. Les coordonnées déjà accessibles dans un signal restent accessibles
   dans son dossier. Les notes et contacts privés restent isolés par compte.
2. Signal conserve sa synthèse compacte et le lien vers le dossier Entreprises.
   Pas de nouveau panneau entreprise imbriqué ni d'idée d'approche.
3. Les données publiques sont accompagnées de leur source et date disponibles.
   La publication d'un email exige une preuve appropriée ; un domaine avec MX
   ne suffit pas à présenter un email nominatif comme vérifié.
4. Découverte et abonnements partagent le catalogue. Les valeurs premium sont
   retirées au serveur, avec disponibilité réelle permettant l'aperçu commercial.
5. L'enrichissement est une tâche durable, indépendante du navigateur : elle
   traite les informations manquantes/périmées d'une entreprise existante aussi.
   États explicites en attente, en cours, terminé avec changement, terminé sans
   nouveauté et échec. Aucun résultat vide n'efface une donnée publique connue.
6. Réutiliser le moteur et les budgets déployés. Dédupliquer les demandes d'une
   même entreprise, limiter fréquence/concurrence/coûts et séparer strictement
   la recherche nominative et son quota. Aucun appel fournisseur sur simple GET.
7. Une nouvelle entreprise augmente le catalogue au prochain rafraîchissement ;
   réenrichir actualise la même identité. Actualiser les vues ouvertes sans
   interrompre une saisie ou réinitialiser les filtres.
8. Staging reçoit un miroir contrôlé des seules données d'entreprise partageables,
   incluant ajouts, corrections et retraits. Ni connexion à la base production,
   ni réplication de comptes, notes, contacts privés, résultats de recherches
   nominatives, secrets, dépenses ou traces brutes de modèles.
9. Les 30 fixtures sont sorties de l'annuaire client de manière récupérable et
   précisément ciblée ; aucune suppression globale fondée seulement sur un nom.

## Frontières et livraison

Réutiliser les tables, lecteurs et services existants. Ajouter uniquement les
contrats, files durables et métadonnées de synchronisation nécessaires. Une
source commune de coordonnées alimente les deux présentations. Les lectures
restent sans effet fournisseur ; les demandes d'enrichissement passent par les
contrôles d'accès existants. Le miroir est un flux production vers staging,
authentifié, limité aux colonnes explicitement autorisées et fermé par défaut.

Les migrations divergentes déjà déployées ne sont jamais renommées : un raccord
Alembic explicite conserve leurs deux histoires. Répéter migrations et contrôles
de préservation sur des copies PostgreSQL avant chaque activation vive. Sauvegarder
avant migration ; revenir à l'artefact précédent si nécessaire sans effacer les
écritures privées ou les vérités de la base. Les outils historiques épinglés à
staging ne sont pas réutilisés aveuglément en production.

## Critères d'acceptation

- Parcours signal BOAMP → dossier et annuaire → même dossier : coordonnées,
  provenance, identité et droits cohérents, y compris groupement/agence.
- Compte découverte : aucune valeur premium dans JSON/DOM ; aperçu honnête.
- Entreprise existante incomplète : demande durable réelle, résultat après
  fermeture/réouverture, aucune fausse réussite fondée sur sa seule présence.
- Deux clics/deux comptes : pas de double dépense simultanée ; quotas nominatif
  et enrichissement indépendants ; budgets et erreurs visibles et bornés.
- Réenrichissement sans résultat : données utiles préservées et aucun doublon.
- Miroir rejouable : mêmes SIREN partageables, suppressions propagées, données
  privées inchangées ; refus des charges mal formées/incomplètes/non autorisées.
- Zéro fixture client ; une nouvelle entrée actualise liste et compteur.
- Tests backend/frontend et revues indépendantes ; migration sur copies,
  recette staging puis production, santé client/Founder et tâches planifiées.

## Statut

Conception approuvée dans la conversation. Implémentation et vérification en cours ;
aucune mise en production n'est déclarée acquise par ce document.
