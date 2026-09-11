# Founder Console Prospection Design

## Objectif

Ajouter à la Founder Console une page privée `/prospection` qui expose les données d'acquisition déjà persistées, sans créer une seconde vérité ni ajouter de mutation. L'écran prépare l'arrivée du mode assisté PR7 : les commandes futures sont visibles, mais inertes, et le backend reste strictement en lecture seule.

## Navigation et hiérarchie

La navigation principale distingue trois destinations : `Aujourd'hui`, `Prospection`, puis `Système`. La route `/prospection` est une vraie route SPA servie par le repli `index.html` déjà limité au vhost `control.kivou.eu`.

La page commence par un bandeau compact qui affiche l'état réel du timer `kivou-acquisition-production.timer`, son prochain passage lorsqu'il tourne, ou `Arrêté depuis le …` lorsqu'il est inactif. Le dernier cycle et son statut restent visibles dans ce bandeau.

L'ordre des blocs dépend uniquement de la présence d'une file :

1. si aucune cible n'attend une revue, `Annuaire` apparaît en premier, puis `File du jour`, `Ciblage` et `Résultats` ;
2. lorsque PR7 fournira des cibles `pending_review`, `File du jour` reprendra la première place.

## API de lecture

Un endpoint authentifié `GET /api/founder/prospection` retourne un contrat versionné `founder-prospection-v1`. Ses paramètres bornés sont :

- `page`, indexée à partir de 1 ;
- `page_size`, limité à 25 dans l'interface et borné côté API ;
- `q`, recherche insensible à la casse sur le nom légal ;
- `family`, valeur issue des familles présentes ;
- `department`, valeur issue des départements présents ;
- `status`, parmi `confirmed_domain`, `without_website` et `reverification_required`.

La réponse contient la file de revue, les compteurs et la page d'annuaire, le dernier ciblage, les résultats cumulés, ainsi que l'état du timer. Une seule requête recharge tout l'écran. Les filtres sont appliqués côté serveur ; les compteurs globaux et les facettes restent calculés sur l'annuaire actif non supprimé.

Le statut du timer est lu avec un appel borné et sans shell à `systemctl show`. Cette lecture est injectée dans le service pour rester déterministe en test. En cas d'indisponibilité de systemd, le contrat rend `UNKNOWN` et conserve la date du dernier cycle plutôt que d'inventer un état.

## Annuaire

`supplier_directory` est la source unique. Les lignes dont `suppressed_at` est renseigné sont exclues. Les compteurs sont définis ainsi :

- entreprises : toutes les lignes actives ;
- domaines confirmés : `domain` et `domain_validation_method` renseignés ;
- e-mails vérifiés : `professional_email` et `email_verification_status` renseignés ;
- à revérifier : `reverification_required_at` renseigné.

La répartition par famille développe `family_keys`, et la répartition par département groupe `department`. Le tableau dense affiche 25 lignes, triées par nom légal puis SIREN, avec entreprise, famille, localisation, effectif, domaine, contact/e-mail, vérification et fraîcheur. Les familles techniques sont traduites en libellés français dans le frontend.

Le filtre `confirmed_domain` exige un domaine validé ; `without_website` exige l'absence de domaine et de site ; `reverification_required` exige une échéance de revérification. La recherche et les filtres réinitialisent la page à 1.

## File du jour

Le contrat frontend et le composant du tableau couvrent dès maintenant les champs PR7 : entreprise, métier, dirigeant, e-mail et provenance, signal d'appât, objet et corps du mail. Le bouton `Mail` ouvre le texte complet dans un panneau latéral droit ; ce comportement est testé avec une réponse API de fixture.

Le schéma actuel ne possède pas de table `pending_review`. Le backend renvoie donc `available=false` et une file vide, sans lire `acquisition_shadow_mail`, dont le contrat `SHADOW` et l'adresse masquée ne correspondent pas au futur mode assisté. L'état vide affiche exactement `Aucune cible préparée. Le runtime d'acquisition est à l'arrêt.` et la date du dernier cycle.

Les boutons `Valider`, `Corriger`, `Écarter` et `Envoyer les N validées` sont présents mais désactivés. Un conteneur focusable fournit l'infobulle `Disponible quand le mode assisté sera livré`. Aucun endpoint `/api/founder/actions/*` n'est ajouté par cette livraison.

## Ciblage

Le dernier cycle provient de `acquisition_runtime_cycle`. Le signal choisi est résolu par `opportunity_representation` et `contract_award`. Le journal `supplier_discovery_run` correspondant est sélectionné par le `signal_ref` exact et par sa fenêtre temporelle de cycle.

Le bloc compact affiche : objet et montant du signal, familles depuis `search_profile.supplier_family_keys`, comptes SIRENE depuis `records_returned`, domaines confirmés pour les opportunités d'acquisition créées dans la fenêtre du cycle et raccordables à `supplier_directory`, e-mails sélectionnés par `role_tier` 1 à 4, et écarts issus de `rejection_reason_counts` complétés par les `reason_codes` des stages du cycle. Une valeur non journalisée ou non raccordable reste explicitement à zéro ; elle n'est pas estimée.

S'il n'existe aucun cycle récent, le bloc conserve la date du dernier cycle connu et affiche un état vide. Un cycle est `récent` pendant 48 heures ; ce seuil ne modifie pas le bandeau du timer, qui reste fondé sur systemd.

## Résultats

Les compteurs lisent les tables existantes et affichent toujours une valeur, y compris zéro :

- envoyés : membres de campagne ayant `step_1_sent_at` ;
- ouvertures : événements fournisseur `email_opened` acceptés ou traités ;
- clics `/a/{token}` : événements de conversion `CLICK` ;
- atterrissages : lignes `account_landing_signal` non QA ;
- profils confirmés : lignes non QA avec `profile_confirmed_at` ;
- comptes payants : parcours possédant un événement `PAID` ;
- MRR : dernier événement `MRR_CHANGED` connu par parcours payé, regroupé par devise et annulé après `CHURNED`.

Lorsque les compteurs commerciaux sont tous nuls, le bloc affiche `Aucun envoi à ce jour` au lieu d'un état vide.

## Présentation et accessibilité

La page réutilise les tokens, Instrument Sans et le vert forêt de la console. Les compteurs utilisent des cartes compactes, les tableaux restent denses et horizontalement défilables sur petit écran, et le panneau latéral possède un titre, un bouton de fermeture, une touche `Échap` et un fond de page non masqué. Les contrôles de filtre ont tous un libellé explicite. Les états chargement, erreur et absence de résultat sont distincts.

## Tests et déploiement

Les tests backend couvrent le contrat versionné, les compteurs réels, les filtres, la pagination à 25, le dernier cycle, les zéros commerciaux, l'état du timer injecté et la frontière d'authentification. Les tests frontend couvrent la route et l'ordre du menu, l'Annuaire placé en tête lorsque la file est vide, les filtres/pagination, les actions désactivées avec infobulle, le panneau de mail et les états vides.

La vérification comprend pytest ciblé, Vitest, typecheck, lint et build Founder. La branche est ensuite poussée, intégrée selon le flux GitHub du dépôt, puis déployée par `kivou-deploy.sh`. Les contrôles publics vérifient Basic Auth, `/prospection`, l'API et l'isolement du domaine client. Une capture Playwright de la page de production authentifiée est réalisée après déploiement ; elle doit montrer les compteurs et des lignes réelles de l'annuaire.

## Hors périmètre

Aucune migration, mutation, activation du timer, donnée simulée, route client, modification de `kivou.eu` ou commande du mode assisté n'est incluse. PR7 définira et branchera la table de revue ainsi que `/api/founder/actions/*`.
