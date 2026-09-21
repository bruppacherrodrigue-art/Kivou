# Milo Mail — recensement A1 des organisations

Run staging du 21 septembre 2026, 22:27:32–22:38:25 UTC. Produit : **Milo
Mail** ; Milo reste l'agent du produit. Données brutes et checkpoints conservés
uniquement dans la base PostgreSQL isolée `kivou_milomail_census_a0`. Ce
document ne contient aucun nom, domaine individuel, contact ou adresse e-mail.

## Contrôles et consommation

Le préflight était entièrement vert : base isolée à `0074`, neuf partitions,
plan figé de 81 nouvelles pages, suppression accessible, source française
accessible, clé staging présente, permis valide et programme Milo Mail
désactivé en `SHADOW`. Le permis
`78788015-0e8c-41cb-b82c-23febdffb44a` avait l'empreinte de configuration
`247b0a83f43052b0da95d289e95a2ece849b1096c73344d44a299a19c46c5903`,
le plan `0ececfe6c3c6015d18575df1a2de9afe45f3a26ce1d83aa40f8fc016e324863d`
et une limite de 81 appels/crédits nouveaux. Il a été **révoqué** après le
run. La base applicative staging est restée à `0065_chief_of_staff`.

| Mesure | Résultat |
| --- | ---: |
| Pages A0 réutilisées depuis le cache | 9 |
| Pages A1 prévues / réussies / échouées | 81 / 81 / 0 |
| Appels Organization Search A1 / retries | 81 / 0 |
| Crédits A1 réservés et réconciliés | 81 |
| Solde Apollo staging avant → après | 2 126 → 2 045 |
| Compteur Organization Search du jour avant → après | 9 → 90 |
| Limite totale du pool avant → après | 2 620 → 2 620 |
| Achat, top-up ou dépassement observé | 0 |
| Charge incrémentale autorisée et observée | 0.00 CHF |
| Coût comptable d'allocation des crédits | inconnu |
| Appels à l'API française | 384, plafond 600 et 60/min |
| Contacts, dirigeants et adresses vérifiés | 0 / 0 / 0 |
| Appels Instantly et e-mails envoyés | 0 / 0 |

Le solde du pool est partagé. Le delta de 81 crédits et celui de 81 recherches
coïncident exactement avec les 81 réservations du ledger A1, sans signe de
consommation concurrente durant ce run. Une reprise a relu les 81 checkpoints
sans nouvel appel facturable : solde 2 045, compteur 90 et ledger 81 inchangés.
Le seul type d'appel Apollo du census est `ORG_SEARCH` (90 cumulatifs avec A0) ;
aucune identité `EMAIL`, aucun contact, enrichissement ou décision d'envoi
n'est présent dans cette base.

## Plan réellement exécuté

La graine publique était
`e84b6de1d60822ff097af207ca01bf202f1e655ded56850822651646169f0f6d`.
Chaque ligne comprend la page 1 déjà mise en cache par A0, puis neuf pages
A1 réparties dans la profondeur accessible. Les préfixes de partition sont
des identifiants techniques, non des sociétés.

| Partition | Secteur | Effectif | Pages observées | Total déclaré Apollo | Organisations observées | Google Workspace |
| --- | --- | --- | --- | ---: | ---: | ---: |
| `0a6e6da79f3e` | Agence digitale/créative | 4–6 | 1, 4, 6, 13, 19, 22, 26, 31, 35, 39 | 1 048 | 250 | 51 |
| `2446b6d2e686` | Conseil | 7–10 | 1, 5, 88, 122, 188, 268, 316, 339, 395, 453 | 17 463 | 250 | 31 |
| `3a62e58c5f24` | Agence digitale/créative | 1–3 | 1, 9, 16, 28, 47, 53, 65, 77, 88, 103 | 2 646 | 250 | 51 |
| `5b923a4d643e` | Recrutement | 1–3 | 1, 14, 34, 72, 96, 124, 148, 184, 208, 242 | 6 164 | 250 | 37 |
| `791dc7694f35` | Conseil | 4–6 | 1, 41, 86, 112, 190, 259, 316, 373, 394, 488 | 24 955 | 250 | 38 |
| `854074f31d93` | Recrutement | 7–10 | 1, 3, 12, 15, 21, 28, 34, 43, 50, 58 | 1 450 | 250 | 44 |
| `d1956e158dfb` | Recrutement | 4–6 | 1, 6, 15, 27, 36, 43, 57, 61, 73, 81 | 2 102 | 250 | 40 |
| `dc675b5fe1a2` | Conseil | 1–3 | 1, 12, 64, 148, 170, 270, 324, 386, 423, 492 | 81 245 | 250 | 36 |
| `f21fc2777c78` | Agence digitale/créative | 7–10 | 1, 3, 6, 8, 10, 14, 17, 19, 21, 26 | 627 | 228 | 60 |

## Résultats observés et limites de couverture

| Niveau de mesure | Résultat |
| --- | ---: |
| Résultats **déclarés** par Apollo, somme des partitions | 137 700 |
| Résultats déclarés accessibles au maximum à 500 pages × 25 | 51 537 |
| Résultats déclarés hors fenêtre accessible, au minimum | 86 163 |
| Lignes d'organisations **réellement parcourues** | 2 228 |
| Organisations **uniques observées** après déduplication | 2 210 |
| Doublons observés entre pages/partitions | 18 (0,81 %) |
| Domaines valides observés | 2 077 (93,22 %) |
| Google Workspace confirmé par MX | 388 occurrences ; 384 entreprises uniques |
| Microsoft 365 / autre / fournisseur inconnu, uniques | 405 / 967 / 454 |
| Contacts / adresses professionnelles réellement vérifiés | 0 / 0 |

Le taux Google Workspace brut sur les lignes parcourues est **17,41 %**
(388/2 228). Par secteur : agence digitale/créative 162/728 = 22,25 % ;
conseil 105/750 = 14,00 % ; recrutement 121/750 = 16,13 %. Par tranche
d'effectif : 1–3, 124/750 = 16,53 % ; 4–6, 129/750 = 17,20 % ; 7–10,
135/728 = 18,54 %. La géographie fine est absente de toutes les lignes
normalisées ; elle reste `UNKNOWN`, pas « France officiellement prouvée ».

La page 1 donne 46/225 = **20,44 %**, contre 342/2 003 = **17,07 %** sur
les pages profondes. Les quartiles de profondeur donnent respectivement
20,27 %, 17,05 %, 16,91 % et 13,69 %. Ce gradient suggère un classement
Apollo ; la proportion A0 ne doit pas être extrapolée telle quelle.

## Estimations conditionnelles

Les poids proviennent des totaux déclarés **par partition**, et les pages
profondes ont été choisies par blocs déterministes. Le taux Google Workspace
pondéré est **14,58 %** sur les totaux déclarés et **14,89 %** sur la portion
affichable. Les bornes ci-dessous combinent des intervalles de Wilson par
strate avec une correction de Bonferroni pour les neuf strates, puis le taux
de doublons observé. Ce sont des **scénarios conditionnels**, non des
intervalles de confiance garantis sur la population : les pages restent
classées par Apollo, les secteurs peuvent se chevaucher et 86 163 résultats
déclarés sont hors fenêtre accessible.

| Population considérée | Bas | Centre | Haut |
| --- | ---: | ---: | ---: |
| Organisations uniques parmi les 51 537 résultats affichables déclarés | 50 881 | 51 121 | 51 273 |
| Dont Google Workspace détectable dans cette portion | 4 944 | 7 610 | 11 359 |
| Organisations uniques sur tous les 137 700 résultats déclarés **si les zones invisibles ressemblent aux pages accessibles** | 135 946 | 136 588 | 136 995 |
| Dont Google Workspace, sous la même hypothèse invérifiable | 12 861 | 19 918 | 29 891 |

Ces chiffres ne sont **pas** des adresses e-mail ni des entreprises françaises
actives confirmées. Le nombre d'adresses vérifiées reste **zéro**.

## Preuve française et décision commerciale

Les 384 organisations uniques Google Workspace ont été examinées via
l'[API officielle Recherche d'entreprises](https://recherche-entreprises.api.gouv.fr/docs/)
sans enrichissement Apollo. Le matcher a persisté 31 résultats
`AMBIGUOUS_MATCH`/`AMBIGUOUS` et 353 `NO_MATCH`/`UNKNOWN`. Aucun
`CONFIRMED_MATCH + ACTIVE` ni `CONFIRMED_MATCH + CEASED` n'a été établi.
Les résultats officiels insuffisants ne sont pas transformés en activité
présumée. Il n'y a donc **aucune entreprise confirmée active par cette
méthode**, ce qui ne signifie pas que ces entreprises sont cessées. Une
fourchette numérique d'entreprises actives serait injustifiée. Il n'existe
aucune décision SEND/HOLD/NO_SEND de contact en A1, car aucun contact n'a été
recherché.

Le prochain travail technique avant B0 est d'obtenir une correspondance
officielle robuste : SIREN/SIRET attesté ou éléments indépendants de
localisation et de raison sociale, sans forcer un homonyme ni traiter le
domaine Apollo comme preuve administrative. La recherche d'organisations
Apollo normalisée ne fournit ici aucune géographie fine exploitable.

## Préparation B0, sans exécution

Une estimation d'une proportion avec marge maximale de ±10 points à 95 % au
pire cas `p=0,5` exige environ 97 observations indépendantes **pour chacun**
des deux taux : dirigeants identifiables puis adresses professionnelles
vérifiées parmi les dirigeants. Prévoir un lot initial d'au moins 200
entreprises Google Workspace officiellement actives, sélectionnées par
secteur, taille et profondeur, avec ajustement si moins de 97 dirigeants
sont trouvés. A1 n'en fournit encore aucune officiellement confirmée ; le
rapprochement doit être corrigé avant ce tirage.

La [recherche de personnes Apollo](https://docs.apollo.io/reference/people-api-search)
est documentée à zéro crédit et ne renvoie pas d'adresse. Si nécessaire
pour corroborer la localisation et la raison sociale,
l'[enrichissement d'organisation](https://docs.apollo.io/reference/organization-enrichment)
coûte un crédit par entreprise, soit au plus 200 crédits pour ce lot.
L'[enrichissement individuel](https://docs.apollo.io/reference/people-enrichment)
coûte jusqu'à 9 crédits/personne selon les données et options ; pour 200
personnes, le **plafond conservateur envisagé** serait 1 800 crédits de
personne, ou **2 000 crédits au total** avec 200 enrichissements
d'organisation, à revoir selon le plan détecté. B0 nécessitera une clé Milo
Mail dédiée, son propre permis,
un budget séparé, le filtrage des suppressions avant enrichissement et une
politique de preuve professionnelle. Les rôles admissibles sont fondateur,
dirigeant, owner ou équivalent ; `@gmail.com` ne vaut pas preuve
professionnelle. Le score et la politique peuvent alors produire SEND
théorique, HOLD ou NO_SEND en `SHADOW`, sans envoi. Aucun endpoint de personne
ou d'enrichissement n'a été appelé ici.
