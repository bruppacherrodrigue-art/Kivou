# PR6 — alertes, compte et finitions

## Décision

PR6 ferme le parcours client sans créer de second modèle de signal. Le mail hebdomadaire, Aujourd’hui et Signaux lisent les mêmes cartes backend et la même phrase « Pour vous ». Les exclusions métier (`model_fit=none`, objet ou titulaire absent), la normalisation du lieu et les compteurs sont décidés côté backend, jamais recomposés dans React.

## Alerte hebdomadaire

Le minuteur existant conserve un cycle idempotent par compte actif et par semaine. Un lot contient au plus trois signaux éligibles, ordonnés comme Aujourd’hui, et n’est pas envoyé si aucun signal ne reste après filtrage. Le rendu HTML et texte présente titulaire, objet, montant, lieu, date et la phrase persistée, avec un lien profond vers le drawer et un lien signé de désinscription. Le HTML est prévisualisable hors envoi. Pour Découverte, un seul signal est ouvert ; le mail indique le nombre restant et renvoie vers les tarifs. Les verdicts `model_fit=none` ne peuvent entrer ni dans un nouveau lot ni dans une reprise.

## Compte et historique

Réglages expose un export JSON déterministe de toutes les données appartenant au compte. La suppression exige une confirmation explicite, crée une demande journalisée et rend l’effacement effectif au plus tard sous 24 heures par un job idempotent. La fiche Entreprise dérive son historique des événements datés déjà détenus par le compte : contacts, notes et changements de statut saved/contacted. Aucun événement n’est inventé lorsque la source ne l’expose pas.

## Cohérence des surfaces

`GET /dashboard` lit `last_seen_at` avant de l’avancer, puis calcule bandeau, top3 et semaine sur un instantané cohérent. Un profil actif fournit toujours `sector_label` et `zone_labels`; une donnée impossible à dériver produit une erreur interne observable plutôt qu’un copy client vide. Les cartes top3 et alertes exigent un objet et un titulaire nommé. Le lieu affiché est une ville nettoyée des suffixes CEDEX, sinon le département, jamais le pays.

Sur Signaux, Découverte affiche les signaux ouverts puis au plus cinq lignes verrouillées. Elles masquent le titulaire mais conservent date, département et montant arrondi, suivies d’une ligne agrégée vers les offres. Les restrictions de filtre sont portées par des infobulles attachées aux contrôles. Un test de rendu interdit les chaînes moteur `materials_or_components`, `workforce_capacity`, `ICP`, `plausible` et `ciblé`.

## Vérification et exploitation

Chaque lot suit RED → GREEN avec tests ciblés en avant-plan et timeout. La validation finale couvre backend, frontend, Playwright et les goldens Aujourd’hui, Signaux Découverte, Entreprises et alerte rendue. Le déploiement staging utilise uniquement `ops/bin/kivou-deploy.sh` sur le SHA de la PR et vérifie readiness, rendu des quatre captures et absence de tests ignorés.
