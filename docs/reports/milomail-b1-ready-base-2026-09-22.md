# Milo Mail France B1 — recensement agrégé du 22 septembre 2026

**Statut : PARTIEL.** Le code est validé et 468 adresses professionnelles
Google Workspace distinctes sont vérifiées dans la base staging isolée. Il en
manque 32 pour l'objectif de 500. Apollo a limité l'endpoint gratuit de solde
pendant le second permis ; le moteur a arrêté tout appel payant. Aucun message
n'a été envoyé et Instantly n'a reçu aucune mutation.

## Dépôt et périmètre

- PR #284 : head final `0e1ead96555f21bad70cb07f5089926ef5a3dc47`,
  CI `35716769471` verte ; fusion
  `450a7a379a6bf6845d1e6da18d8cb3fdc8727f88` le 22 septembre 2026 à
  10:55:42 UTC. La base de #285 est ce même SHA.
- PR B1 [#285](https://github.com/bruppacherrodrigue-art/Kivou/pull/285),
  branche `feat/milomail-france-b1-ready-base`, laissée ouverte. Sa CI de code
  `35730802395` est verte : quatre shards backend et job décisionnel réussis ;
  frontend ignoré par le routage du diff.
- Migration additive/réversible `0076_milomail_b1_ready_base.py` appliquée
  uniquement à `kivou_milomail_census_a0`. La base applicative staging reste à
  `0065_chief_of_staff`. Aucune production ou application Milo Mail n'a été
  modifiée.
- Les identités, adresses, réponses Apollo et extraits de preuves restent dans
  la base PostgreSQL isolée. Ce rapport contient uniquement des agrégats.

## Règle d'activité et décisions rejouées

Le ruleset `milomail-fr-b2b-v2` distingue `OFFICIAL_ACTIVE`,
`OPERATIONALLY_ACTIVE`, `ACTIVITY_UNKNOWN` et `OFFICIAL_CEASED`. La preuve
administrative française reste prioritaire. En son absence, une identité du
site public corroborée, un MX Google Workspace daté et un dirigeant actuel
avec adresse vérifiée peuvent établir une activité opérationnelle. Une
cessation officielle exclut, une preuve insuffisante maintient HOLD. Aucune
preuve Apollo seule n'est devenue une confirmation administrative.

La règle est fondée sur la [CNIL, prospection électronique B2B](https://www.cnil.fr/fr/la-prospection-commerciale-par-courrier-electronique-sms-mms-et-automate-dappel),
le [CPCE L34-5](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000042155961/)
et le [RGPD, articles 6, 14 et 21](https://eur-lex.europa.eu/eli/reg/2016/679/oj?locale=fr),
consultés le 22 septembre 2026. L'absence d'obligation autonome de contrôle
SIRENE préalable est une inférence du ruleset ; elle ne dispense ni de la
pertinence professionnelle, ni de l'information sur la collecte indirecte,
ni de l'opposition simple et gratuite, ni des autres vérifications Kivou.

Les 200 décisions B0 ont été rejouées sans nouvel appel Apollo et sans
réécrire les preuves ou décisions historiques : 80 HOLD, 120 NO_SEND, zéro
SEND théorique. Dans les 1 394 entreprises B0+B1 terminées, la dernière
version de décision donne :

| Activité | Entreprises |
| --- | ---: |
| OFFICIAL_ACTIVE | 1 |
| OPERATIONALLY_ACTIVE | 3 |
| ACTIVITY_UNKNOWN | 1 390 |
| OFFICIAL_CEASED | 0 |

Une extraction d'identifiant légal depuis un site est conservée et une
entreprise est officiellement confirmée active. Le contrôle public des sites
a confirmé quatre identités par preuve indépendante ; il n'a appelé ni Apollo
ni l'API administrative. B1 a effectué **zéro** appel supplémentaire à l'API
officielle, dont le plafond cumulatif antérieur de 600 requêtes était déjà
atteint. Il serait faux de classer les autres entreprises comme cessées.

Les dernières décisions agrégées sont **0 READY_THEORETICAL, 468 HOLD et
926 NO_SEND**. Les 468 adresses techniquement vérifiées restent en HOLD pour
des raisons réelles encore ouvertes : pays non corroboré sur la fiche,
landing française indisponible, information de provenance et confidentialité,
identité/boîte d'envoi, opposition et budget d'envoi fermés. La preuve de site
manque en outre à 464 de ces 468 dossiers. Le changement SIRENE n'a donc pas
artificiellement créé de SEND.

## Rendement mesuré

| Mesure | Résultat |
| --- | ---: |
| B0 réutilisées, sans nouvel enrichissement | 80 adresses |
| Entreprises B1 terminées et distinctes | 1 194 |
| Nouvelles pages Apollo B1 terminées | 253 |
| Entreprises Google Workspace vues sur pages B1 | 1 032 |
| Dont nouvelles par rapport aux pages A1 | 1 017 |
| Dirigeants B1 identifiés | 407 |
| E-mails professionnels B1 trouvés et vérifiés sur domaine Google Workspace | 388 |
| Total B0+B1 vérifié et distinct | **468** |
| Écart à l'objectif de 500 | **32** |
| B1 recherche d'organisations / personnes / enrichissement de personne | 253 / 1 195 / 411 |
| Crédits B1 réservés dans le ledger | **664** |
| Rendement B1 | **0,584 adresse/crédit**, soit **1,71 crédit/adresse** |
| Suppressions parmi les adresses de la vue livrable | 0 |
| Mutations Instantly / e-mails / déploiements | **0 / 0 / 0** |

Les 388 nouvelles adresses B1 se répartissent en 195 agences, 92 cabinets de
conseil et 101 cabinets de recrutement ; 96 entreprises ont 1–3 personnes,
169 en ont 4–6 et 123 en ont 7–10. La vue privée B0+B1 contient 234 HOLD
agences, 110 HOLD conseil et 124 HOLD recrutement. Elle ne contient aucune
adresse exportable aujourd'hui.

| Partition opaque (préfixe) | Adresses B1 | Crédits B1 | Adresses/crédit |
| --- | ---: | ---: | ---: |
| `0a6e6da79f3e` | 92 | 130 | 0,708 |
| `2446b6d2e686` | 31 | 64 | 0,484 |
| `3a62e58c5f24` | 56 | 92 | 0,609 |
| `5b923a4d643e` | 17 | 44 | 0,386 |
| `791dc7694f35` | 38 | 69 | 0,551 |
| `854074f31d93` | 45 | 78 | 0,577 |
| `d1956e158dfb` | 39 | 71 | 0,549 |
| `dc675b5fe1a2` | 23 | 51 | 0,451 |
| `f21fc2777c78` | 47 | 65 | 0,723 |

## Permis, solde et arrêt

Le premier permis B1 avait l'empreinte de plan
`be69f0f341eff249c4d196efb021964b08e3b75938e7771744f09680ebfadb51`.
Ses 220 pages et 1 055 entreprises ont été terminées. Son ledger totalise
579 crédits ; le solde Apollo mesuré est passé de **1 956 à 1 377**. Le reçu
de réconciliation qualifie explicitement cette variation de pool partagé
d'`AMBIGUOUS_SHARED_POOL`, même si elle égale le ledger. Son permis est révoqué.

Le second plan, empreinte
`a3e616a3bc27e2cc5a131440748ca5adeb026e0b39bb3a31b87e55009be9d8ab`,
avait un plafond de 321 crédits, 80 pages, 500 entreprises et 241
enrichissements, avec réserve de 1 000 crédits. Il a terminé 33 pages et
139 entreprises ; 47 pages et deux entreprises sont restées planifiées.
Toutes ses 225 opérations Apollo journalisées sont `COMPLETED` avec réponse
persistée : 33 recherches d'organisations, 140 recherches de personnes et
52 enrichissements. Aucune opération payante ambiguë ne doit être répétée.
Son ledger réserve **85 crédits**. L'endpoint gratuit du solde a ensuite
renvoyé `429` avec `Retry-After: 17191` secondes ; le **solde final du pool
après ce second permis n'a pas été mesuré**. Son permis a été révoqué et
aucun nouvel appel facturable n'a été lancé.

Le cumul B1 est **664 crédits sur 900 autorisés** ; le reliquat de permis
possible est au plus **236 crédits**, puis doit être réduit si le solde réel
mesuré moins la réserve de 1 000 est inférieur. Aucun achat ni top-up n'a été
initié ; le coût incrémental autorisé est **0,00 CHF** sur le pool prépayé.
Le coût comptable d'allocation par crédit reste **inconnu**. Il serait
incorrect de publier un solde final calculé à partir du ledger comme s'il
avait été observé chez Apollo.

Le journal HTTP ajouté en B1 contient, sur ce run, 706 cache misses et
154 hits, 704 résolutions DNS publiques (2 erreurs), 413 réponses robots
200, 101 pages d'accueil HTML acceptées et 9 pages légales acceptées.
Les redirections refusées, dépassements de taille, statuts HTTP et timeouts
sont comptabilisés séparément ; aucun corps de page n'est conservé dans ce
journal. Les requêtes B0 précédant la migration ne sont pas reconstituées.

## Projection France, avec limites

La projection utilise les poids de population et les estimations Google
Workspace du [rapport A1](milomail-a1-coverage-2026-09-22.md), puis le taux
B0+B1 de contacts vérifiés par partition. Le rendement stratifié central
est **28,81 %** ; l'intervalle Wilson-Bonferroni simultané calculé sur les
neuf strates est **19,51–40,50 %** pour les observations de ce run.

| Fenêtre Apollo | Basse | Centrale | Haute |
| --- | ---: | ---: | ---: |
| Portion affichable, scénario d'adresses techniquement vérifiables | 965 | 2 192 | 4 601 |
| Tous résultats déclarés, hors fenêtre accessible | 2 510 | 5 737 | 12 107 |

Les bornes combinent les bornes A1 de Google Workspace et les proportions
par strate. L'allocation B1 a été adaptative et les pages Apollo sont
classées ; ces nombres sont donc des **scénarios**, pas un intervalle de
confiance calibré de la population française ni un inventaire d'adresses
accessibles. Ils ne sont surtout pas une projection de SEND : la preuve
administrative/opérationnelle et les autres obligations restent à appliquer.

## Export simulé et reprise sûre

Le dry-run `Milo Mail — France` a reçu 468 lignes, exclu les 468 HOLD,
retenu **zéro** `READY_THEORETICAL`, et produit un reçu avec
`provider_calls=0` et `mutations_allowed=false`. Aucune liste, campagne ou
lead Instantly n'a été créé. Le programme reste en SHADOW, désactivé pour
l'envoi et avec plafonds d'envoi/coût à zéro.

Après expiration du `Retry-After`, l'opérateur staging doit mesurer le solde
Apollo gratuit, réconcilier le second permis révoqué, puis créer une nouvelle
autorisation de base à courte durée et un nouveau permis. Le plafond de
crédits est `min(236, solde mesuré - 1000)` ; aucun appel n'est permis si ce
nombre est nul ou si l'endpoint de solde est encore indisponible. Le nouveau
plan doit exclure les 253 pages B1 déjà terminées et les entreprises déjà
enrichies ; il doit conserver la recherche de personne terminée d'une des
deux entreprises planifiées, sans rappel payant. Les commandes exactes et les
contrôles de reprise figurent dans le
[runbook B1](../runbooks/21-milomail-b1-ready-base.md).

## Validation du code

Avant fusion, #284 a eu sa CI complète verte et une suite backend complète
locale ; aucun résultat nominatif n'a été commité. Pour #285 : suite Milo
Mail locale **258 passés, 2 ignorés** sur `/tmp` ; suite backend locale
**7 455 passés, 74 ignorés, 1 échec attendu**, avec une erreur de registre
de runbook corrigée avant la CI de code verte. Migrations SQLite ciblées et
PostgreSQL jetable `0075→0076→0075→0076`, Ruff, mypy pertinent,
compilation, `uv lock --check` et recherche de secrets ont passé. Les tests
ajoutés au lot couvrent les règles d'activité, le rejeu, les plafonds,
l'idempotence, le journal HTTP et le dry-run ; les données réelles ne sont
jamais dans les fixtures ou dans les journaux CI.
