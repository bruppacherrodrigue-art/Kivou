# Milo Mail — pilote B0 sur entreprises Google Workspace (22 septembre 2026)

État : **pilote réel partiel, sans envoi**. Ce rapport contient uniquement des
agrégats. Les identités, réponses Apollo et adresses restent dans la base
PostgreSQL isolée `kivou_milomail_census_a0`, à la révision `0075`. Milo Mail est
le produit ; Milo est son agent. Aucune donnée de prospection ne va dans Milo Mail.

## Population et méthode

A1 a observé 384 entreprises Google Workspace uniques parmi les pages Apollo
accessibles. B0 a figé un échantillon stratifié selon secteur, taille Apollo,
partition, profondeur, preuve administrative et qualité de la fiche. Chaque
recherche de personnes vise les fonctions dirigeantes, puis au plus deux
candidats par entreprise ; un seul e-mail professionnel peut être retenu.
Les entreprises déjà traitées et les appels ayant une réponse facturable sans
checkpoint sont exclus des permis suivants. Aucun e-mail n'est construit par
supposition. Les décisions restent théoriques en SHADOW.

Le premier permis a traité 64 entreprises, le deuxième 65. Les deux permis
sont révoqués. Le troisième plan est figé pour 71 entreprises supplémentaires
mais **aucun permis correspondant n'a été émis** : les endpoints Apollo de
consultation du solde sont temporairement limités (HTTP 429). Aucun appel de
contact supplémentaire ne doit être lancé avant un nouveau préflight vert.

## Résultats mesurés au 22 septembre, 08:03 UTC

| Mesure | Valeur |
| --- | ---: |
| Entreprises avec checkpoint B0 | 129 |
| Dirigeants pertinents identifiés | 54 |
| E-mails professionnels trouvés | 53 |
| E-mails professionnels vérifiés, sur domaine Google Workspace | 53 |
| Aucun contact trouvé | 75 |
| Domaine d'adresse différent de l'entreprise | 1 |
| Décision théorique HOLD | 53 |
| Décision NO_SEND | 76 |
| Décision SEND_THEORETICAL | 0 |
| Identifiant légal validé depuis le site | 0 |
| Entreprises ACTIVE + CONFIRMED_MATCH | 0 |
| Appels Apollo People Search inscrits | 131 |
| Appels Apollo People Enrichment inscrits | 56 |
| Appels Apollo terminés sans checkpoint d'entreprise | 3 |
| Crédits réservés au pire cas dans le ledger B0 | 504 |
| Pool Apollo avant / après | 2 045 / 1 989 |
| Variation brute du pool partagé | 56 crédits |
| Réserve observée après run | 1 989 crédits |
| Coût incrémental autorisé et observé | 0,00 CHF |
| Coût comptable d'allocation | inconnu |
| Mutations Instantly / e-mails envoyés / déploiements | 0 / 0 / 0 |

Les 56 appels d'enrichissement ont chacun un reçu `COMPLETED` dans la base ;
55 figurent dans un checkpoint d'entreprise et ont un delta immédiat de
1 crédit. Un enrichissement et deux recherches gratuites ne sont pas associés
à un checkpoint. Ils ne sont pas rejoués. La variation de 56 crédits du pool
partagé est cohérente avec le ledger, mais elle ne démontre pas à elle seule
l'absence de consommation concurrente. Le rendement observé sur les seuls
checkpoints est de **53/129 = 41,1 %** d'adresses vérifiées, et **55/53 ≈ 1,04
crédit de débit observé par adresse vérifiée**, hors appel orphelin. Le prix
comptable d'un crédit prépayé reste inconnu ; aucun taux CHF/crédit n'est inventé.

## Rapprochement administratif

Les 384 fiches A1 ne contenaient ni ville ni code postal. La recherche par nom
seul ne pouvait pas corroborer une identité légale : 353 résultats non prouvés
et 31 ambigus. Le nouveau chemin consulte au plus quatre pages publiques du
site validé, extrait et vérifie SIREN/SIRET/TVA, interroge ensuite l'API
Recherche d'entreprises par identifiant exact et exige une corroboration du
nom officiel ou commercial. Le site est traité comme donnée non fiable ; aucun
JavaScript ou contenu arbitraire n'est exécuté.

Sur les 53 adresses techniques, le statut officiel est resté non prouvé :
5 correspondances ambiguës, 48 sans correspondance suffisante. **Aucune
entreprise n'est déclarée inactive sur cette base.** Le compteur de demandes
à l'API officielle a progressé de 384 à 437, soit 53 nouvelles requêtes dans
B0. Les recontrôles publics ultérieurs ont réutilisé son cache. Les 53 sites
ont été revus avec le résolveur v3 ; 61 tentatives HTTP ont été comptées dans
ces deux recontrôles, sans identifiant valide. Les tentatives HTTP des passes
antérieures n'étaient pas toutes journalisées et leur total exact ne peut pas
être reconstitué ; le cache conserve 86 réponses ou tentatives comptabilisées
sur les versions v1–v3. L'absence de preuve administrative impose HOLD aux
adresses techniquement exploitables.

## Projection prudente, non inventaire

Le taux brut 41,1 % est descriptif. Le taux central pondéré par les strates
A1 est **39,13 %**. La borne statistique simultanée à 95 % utilise Wilson
avec correction Bonferroni sur 18 strates : **10,21 % à 78,92 %**. L'échantillon
étant déterministe et partiel, cet intervalle exige en plus l'hypothèse non
vérifiée d'échangeabilité au sein de chaque strate.

| Base A1 Google Workspace | Bas | Central | Haut | Portée |
| --- | ---: | ---: | ---: | --- |
| Portion affichable Apollo | 504 | 2 978 | 8 965 | E-mails GW vérifiables potentiels, extrapolés |
| Tous résultats déclarés | 1 313 | 7 795 | 23 592 | Hors fenêtre Apollo, forte incertitude |

Les chiffres de base A1 sont respectivement 4 944 / 7 610 / 11 359 et
12 861 / 19 918 / 29 891 entreprises Google Workspace estimées. Le nombre
réellement vérifié ici est **53 adresses**. La projection `SEND_THEORETICAL`
reste non estimable tant que l'identité administrative, la landing française
et l'infrastructure d'envoi ne sont pas prouvées. Aucune des valeurs de la
table ne constitue une liste d'adresses ou un volume envoyable. Le coût d'une
collecte complète peut être exprimé en crédits seulement après fermeture du
pilote et réconciliation des trois appels sans checkpoint ; il ne peut pas être
converti en CHF comptables sans prix d'allocation vérifié.

## État sûr et suite

Le programme reste désactivé en SHADOW. Les deux permis utilisés sont révoqués.
Le troisième permis ne doit être émis qu'après retour des endpoints gratuits
Apollo, nouveau solde confirmé, préflight vert et vérification que les
réservations cumulées restent sous 1 500 crédits avec au moins 500 en réserve.
Le plan de 71 entreprises est conservé, sans modification ni appel facturable.
Les commandes exactes figurent dans le runbook B0. Les snapshots privés sont
conservés au plus 30 jours dans la base autorisée ; `purge-cache` retire les
réponses Apollo et champs personnels B0 sans effacer les suppressions, permis
ou reçus comptables. Le rapport pourra être mis à jour après une reprise sûre.
