# PR6b — fiche valeur vendable

## But et portée

Les surfaces authentifiées `/dashboard`, `/signals` et `/companies` doivent compléter les faits de l'avis public avec trois lectures locales : le calendrier probable du contrat, l'historique public du titulaire et l'annuaire professionnel local. La phrase « Pour vous » générée est activable après un backfill borné. Le cold mail et les modules d'acquisition, de recherche d'entreprise, de recherche de contact et de console Founder ne changent pas.

Le bloc Contact reste un service applicatif séparé du runtime d'acquisition. Il a été construit après la fusion de la chaîne Apollo de la fenêtre A dans `main` (`organizations/enrich`, `people/search`, `people/match`) et réutilise ses profils, son classement et ses adaptateurs sans les modifier.

## Read-models

`signals.client_value.calendar` utilise d'abord la date de démarrage publiée. À défaut, il calcule un mois depuis la date de notification et un délai configurable par préfixe CPV avec `KIVOU_COMMERCIAL_START_DELAY_MONTHS_BY_CPV_JSON` (par exemple `{"45": 3, "452331": 5}`), avec deux mois par défaut. Il restitue la durée publiée en mois lorsqu'elle est convertible. Le bloc est absent si aucune date de notification ou de démarrage n'est publiée.

`signals.client_value.history` lit les attributions existantes. Avec une `company_key`, il utilise l'empreinte d'identité déjà projetée; sinon il rapproche le nom normalisé et le département et marque explicitement ce repli. Il déduplique les contrats, calcule le nombre et les montants des douze derniers mois, la première attribution connue, la cadence trimestrielle, la médiane par devise, la part des groupements et les acheteurs récurrents. Une valeur impossible à établir est omise.

`signals.client_value.directory` lit uniquement `supplier_directory`. Pour un titulaire français, il cherche d'abord son SIREN/SIRET publié, puis le nom normalisé et le département. Il restitue NAF, familles métier, effectif, ville, département, site HTTPS et dirigeants du registre; les données personnelles supprimées restent absentes. Pour le circuit local, il sélectionne au plus huit entreprises du département du signal dont les familles intersectent celles du profil cible, trie la même ville avant les autres puis par effectif décroissant et expose un lien vers une fiche annuaire authentifiée.

## API et confidentialité

Les cartes déverrouillées reçoivent un objet `commercial_calendar` facultatif afin que la carte Aujourd'hui et le drawer partagent la même donnée. Le détail d'un signal ajoute `holder_history` et `local_circuit`; la fiche titulaire ajoute `directory`, `market_summary` et l'état `contact_lookup` lorsque le fournisseur est configuré. Une route `/companies/directory/{siren}` sert la fiche non titulaire aux seuls comptes connectés. Les réponses verrouillées ne reçoivent aucun de ces champs.

`POST /companies/{company_key}/contact-lookup` vérifie d'abord la session, l'accès de ce compte à la fiche et un identifiant d'organisation Apollo déjà résolu sur une entrée non supprimée de `supplier_directory`, puis exécute la chaîne seulement au clic. Le repli nom/domaine/ville du fournisseur est volontairement interdit ici : ses appels internes ne sont pas exposés par le contrat fusionné et ne pourraient donc pas être journalisés fidèlement. Les réponses organisation et personne sont reliées aux identifiants exacts demandés; le titre est reclassifié et le contrat de contact partagé rejette les boîtes génériques ou les adresses non valides avant toute persistance.

`company_contact_lookup` isole les résultats par compte et entreprise, conserve une date de recherche et impose 90 jours avant actualisation. Le cache et son journal portent le SIREN et l'identifiant d'organisation Apollo exacts qui ont produit les données. Son bail possède un identifiant de tentative et une expiration : seule la tentative encore propriétaire, toujours reliée à la même identité annuaire résolue, peut poursuivre ou écrire le résultat. Une suppression ou une correction du rattachement Apollo dans l'annuaire purge immédiatement le cache et bloque la suite de la chaîne; si cette révocation est observée par le navigateur, le bloc et ses données locales sont retirés.

`company_contact_lookup_attempt` est un journal append-only sans donnée personnelle. Chaque nouvelle chaîne fournisseur, y compris un réessai après échec, consomme une unité du quota mensuel et réserve au plus quatre crédits fournisseur. Les compteurs d'appels et crédits tentés sont incrémentés avant chaque appel externe. Les contrats Apollo fusionnés ne publient pas encore le coût facturé observé : `observed_credit_units` reste donc nul, au lieu de présenter une estimation locale comme un coût réel. Les quotas sont 0 en Découverte, 20 en Essentiel et 100 en Pro; une réservation sérialise le compteur du compte et compte toute la fenêtre mensuelle avant l'appel externe.

Chaque groupe de données nomme sa propre source. Les données d'attribution pointent vers les avis publics; les données d'annuaire affichent « registre » et une procédure de suppression; le site indique séparément sa provenance enregistrée. Aucun e-mail nominatif de l'annuaire ne traverse cette API. Les URL non HTTPS et les champs absents sont omis dès la réponse backend.

## Phrase « Pour vous »

`KIVOU_GENERATED_FOR_YOU_ENABLED` est désactivé par défaut. Une fois activé, une phrase persistée n'est choisie que pour une correspondance forte et un `model_fit` différent de `none`; tous les autres cas utilisent le repli déterministe. Le backfill existant reste borné par `--limit` et sélectionne uniquement les signaux courants, non invalidés, rattachés à la révision courante de leur profil. L'activation staging et production reste bloquée tant que la sélection des seuls comptes actifs n'est pas livrée dans le module `personalization`, détenu par la fenêtre A. Le contenu des quatre canaux existants ne reçoit aucun des nouveaux blocs.

## Interface

Le drawer conserve ses composants et suit cet ordre : statut et correspondance, titre, grille, calendrier, historique du titulaire, exigences du dossier lorsqu'une preuve DCE avec document et page existe, circuit local, Pour vous, actions, source. Chaque section disparaît quand son read-model est absent. L'audit de production du 11 septembre 2026 a trouvé 634 documents, mais aucun lien document-procédure et aucune exigence classifiée : l'ancien bloc dérivé des seules métadonnées est donc retiré pour ne pas présenter une inférence comme une exigence du dossier.

La fiche titulaire suit l'ordre identité et annuaire, synthèse des marchés, Contact, marchés, notes, historique. Contact montre l'effectif, le site et jusqu'à trois personnes avec un e-mail professionnel vérifié quand les contrats Apollo les fournissent; téléphone et LinkedIn sont anticipés comme champs facultatifs et restent omis tant que le contrat fournisseur ne les publie pas. En Découverte, le bouton reste visible mais verrouillé avec une invitation vers les offres. La fiche annuaire réutilise le bloc d'identité et d'annuaire et affiche les marchés publics trouvés, sans contrôles CRM propres à un titulaire du compte.

## Vérification et livraison

Les tests backend couvrent les données présentes et absentes, les deux modes de rapprochement, le tri local, l'isolation de compte et l'absence de changement du mail. Les tests frontend couvrent chaque bloc présent et absent, l'ordre, les liens, l'absence de tirets et les deux formats d'écran. Après CI verte, le SHA est déployé en staging avec préavis; des captures desktop et mobile sont prises avec `client-3mois` et le compte QA Découverte, puis `main` est immédiatement restauré sur staging. La production ne part que de `main` après fusion.
