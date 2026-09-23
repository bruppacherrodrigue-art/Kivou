# Milo Mail France B1 — recensement agrégé des 22–23 septembre 2026

**Statut : objectif quantitatif atteint, sans autorisation d'envoi.** La base
staging isolée contient 500 adresses professionnelles Google Workspace
vérifiées et distinctes. Les 32 dernières ont été obtenues le 23 septembre,
après expiration de la limitation de l'endpoint gratuit de solde Apollo et
réconciliation du second permis. Les 500 adresses restent en HOLD. Aucun
message n'a été envoyé et Instantly n'a reçu aucune mutation.

## Dépôt et périmètre

- PR #284 : head final `0e1ead96555f21bad70cb07f5089926ef5a3dc47`,
  CI `35716769471` verte ; fusion
  `450a7a379a6bf6845d1e6da18d8cb3fdc8727f88` le 22 septembre 2026 à
  10:55:42 UTC. La base de #285 est ce même SHA.
- PR B1 [#285](https://github.com/bruppacherrodrigue-art/Kivou/pull/285),
  branche `feat/milomail-france-b1-ready-base`. La CI du code avant mise à jour
  du rapport est verte : quatre shards backend et job décisionnel réussis ;
  frontend ignoré par le routage du diff. La CI du SHA final est vérifiée
  séparément avant toute fusion.
- Migration additive/réversible `0076_milomail_b1_ready_base.py` appliquée
  uniquement à `kivou_milomail_census_a0`. Aucune nouvelle migration n'a été
  ajoutée pour terminer la collecte. La base applicative staging reste à
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
SEND théorique. Dans les 1 500 entreprises B0+B1 terminées, la dernière
version de décision donne :

| Activité | Entreprises |
| --- | ---: |
| OFFICIAL_ACTIVE | 1 |
| OPERATIONALLY_ACTIVE | 3 |
| ACTIVITY_UNKNOWN | 1 496 |
| OFFICIAL_CEASED | 0 |

Une extraction d'identifiant légal depuis un site est conservée et une
entreprise est officiellement confirmée active. Le contrôle public des sites
a confirmé quatre identités par preuve indépendante ; il n'a appelé ni Apollo
ni l'API administrative. B1 a effectué **zéro** appel supplémentaire à l'API
officielle, dont le plafond cumulatif antérieur de 600 requêtes était déjà
atteint. Il serait faux de classer les autres entreprises comme cessées.

Les dernières décisions agrégées sont **0 READY_THEORETICAL, 500 HOLD et
1 000 NO_SEND**. Les 500 adresses techniquement vérifiées restent en HOLD pour
des raisons réelles encore ouvertes : pays non corroboré sur la fiche,
landing française indisponible, information de provenance et confidentialité,
identité/boîte d'envoi, opposition et budget d'envoi fermés. La preuve de site
manque en outre à 496 de ces 500 dossiers. Le changement SIRENE n'a donc pas
artificiellement créé de SEND.

## Rendement mesuré

| Mesure | Résultat |
| --- | ---: |
| B0 réutilisées, sans nouvel enrichissement | 80 adresses |
| Entreprises B1 terminées et distinctes | 1 300 |
| Nouvelles pages Apollo B1 terminées | 282 |
| Dirigeants B1 identifiés | 444 |
| E-mails professionnels B1 trouvés et vérifiés sur domaine Google Workspace | 420 |
| Total B0+B1 vérifié et distinct | **500** |
| Écart à l'objectif de 500 | **0** |
| B1 recherche d'organisations / personnes / enrichissement de personne | 282 / 1 301 / 450 |
| Crédits B1 réservés dans le ledger | **732** |
| Rendement B1 | **0,574 adresse/crédit**, soit **1,74 crédit/adresse** |
| Suppressions parmi les adresses de la vue livrable | 0 |
| Mutations Instantly / e-mails / déploiements | **0 / 0 / 0** |

Les 420 nouvelles adresses B1 se répartissent en 204 agences, 104 cabinets de
conseil et 112 cabinets de recrutement ; 109 entreprises ont 1–3 personnes,
177 en ont 4–6 et 134 en ont 7–10. La vue privée B0+B1 contient 243 HOLD
agences, 122 HOLD conseil et 135 HOLD recrutement. Elle ne contient aucune
adresse exportable aujourd'hui.

| Partition opaque (préfixe) | Adresses B1 | Crédits B1 | Adresses/crédit |
| --- | ---: | ---: | ---: |
| `0a6e6da79f3e` | 92 | 130 | 0,708 |
| `2446b6d2e686` | 36 | 77 | 0,468 |
| `3a62e58c5f24` | 65 | 109 | 0,596 |
| `5b923a4d643e` | 20 | 51 | 0,392 |
| `791dc7694f35` | 44 | 81 | 0,543 |
| `854074f31d93` | 51 | 88 | 0,580 |
| `d1956e158dfb` | 41 | 76 | 0,539 |
| `dc675b5fe1a2` | 24 | 55 | 0,436 |
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
52 enrichissements. Aucune opération payante ambiguë n'a été répétée.
Son ledger réserve **85 crédits**. Après le `429` et le `Retry-After: 17191`,
le solde mesuré du pool a été **1 192 crédits**, contre **1 377** avant ce
permis. La baisse du pool partagé est donc de **185 crédits** ; seuls 85 sont
attribuables au ledger B1 et les **100 restants sont concurrents ou non
attribuables**. Le reçu conserve `AMBIGUOUS_SHARED_POOL`. Ce permis est
révoqué.

Le 23 septembre, un troisième permis `milomail-b1-resume-20260923-v2`, lié à
la base isolée, au plan figé
`93b517b50bbc66b83a38a99be3cdd53fb4c1c14860af4cbe47c71687e78fdc87`
et à l'empreinte de configuration
`5a2c33245500da41d93e81c2e6c5a49e84ffafca90400f0ac2a75a75fd795676`,
a été émis après un préflight vert. Son plafond de 160 crédits était inférieur
à `min(236, 1192 − 1000) = 192`. Le plan excluait les 253 pages et les
entreprises déjà terminées ; aucune page payée n'a été rappelée. Le moteur
s'est arrêté à 500 adresses : **29 pages, 106 entreprises, 106 recherches de
personnes, 39 enrichissements et 32 adresses vérifiées**. Les 174 opérations
journalisées sont toutes `COMPLETED`, dont **68 crédits** réservés. Le solde
Apollo mesuré est passé de **1 192 à 1 124**. Le reçu qualifie encore le pool
partagé d'`AMBIGUOUS_SHARED_POOL`, malgré l'égalité entre delta global et
ledger. Le permis est révoqué ; la réserve finale dépasse le minimum de 1 000
de **124 crédits**.

Le cumul B1 est **732 crédits sur 900 autorisés**. Aucun achat ni top-up n'a
été initié ; le coût incrémental attesté est **0,00 CHF** sur le pool prépayé.
Le coût comptable d'allocation par crédit reste **inconnu**.

Le journal HTTP ajouté en B1 contient 738 cache misses et 186 hits,
736 résolutions DNS publiques (2 erreurs), 435 réponses robots 200,
104 pages d'accueil HTML acceptées et 9 pages légales acceptées.
Les redirections refusées, dépassements de taille, statuts HTTP et timeouts
sont comptabilisés séparément ; aucun corps de page n'est conservé dans ce
journal. Les requêtes B0 précédant la migration ne sont pas reconstituées.

## Projection France, avec limites

La projection utilise les poids de population et les estimations Google
Workspace du [rapport A1](milomail-a1-coverage-2026-09-22.md), puis le taux
B0+B1 de contacts vérifiés par partition. Le rendement stratifié central
est **29,07 %** ; l'intervalle Wilson-Bonferroni simultané calculé sur les
neuf strates est **20,08–40,25 %** pour les observations de ce run.

| Fenêtre Apollo | Basse | Centrale | Haute |
| --- | ---: | ---: | ---: |
| Portion affichable, scénario d'adresses techniquement vérifiables | 993 | 2 212 | 4 572 |
| Tous résultats déclarés, hors fenêtre accessible | 2 582 | 5 790 | 12 032 |

Les bornes combinent les bornes A1 de Google Workspace et les proportions
par strate. L'allocation B1 a été adaptative et les pages Apollo sont
classées ; ces nombres sont donc des **scénarios**, pas un intervalle de
confiance calibré de la population française ni un inventaire d'adresses
accessibles. Ils ne sont surtout pas une projection de SEND : la preuve
administrative/opérationnelle et les autres obligations restent à appliquer.

## Export simulé et reprise sûre

Le dry-run `Milo Mail — France` a reçu 500 lignes, exclu les 500 HOLD,
retenu **zéro** `READY_THEORETICAL`, et produit un reçu avec
`provider_calls=0` et `mutations_allowed=false`. Aucune liste, campagne ou
lead Instantly n'a été créé. Le programme reste en SHADOW, désactivé pour
l'envoi et avec plafonds d'envoi/coût à zéro.

L'objectif de 500 est atteint et les trois permis B1 sont révoqués. **Aucune
reprise payante n'est requise ni autorisée par ce rapport.** Les 282 pages B1
terminées et les réponses payantes restent checkpointées dans la base isolée.
Le [runbook B1](../runbooks/21-milomail-b1-ready-base.md) conserve la procédure
historique de reprise après une interruption.

## Validation du code

Avant fusion, #284 a eu sa CI complète verte et une suite backend complète
locale ; aucun résultat nominatif n'a été commité. Pour #285 : suite Milo
Mail locale **258 passés, 2 ignorés** sur `/tmp` ; première suite backend
locale **7 455 passés, 74 ignorés, 1 échec attendu, 1 échec** (registre de
runbook B1 manquant). Ce registre a été corrigé, ses **5 tests ciblés** sont
passés et la CI backend complète du code a ensuite été verte. Migrations SQLite ciblées et
PostgreSQL jetable `0075→0076→0075→0076`, Ruff, mypy pertinent,
compilation, `uv lock --check` et recherche de secrets ont passé. Les tests
ajoutés au lot couvrent les règles d'activité, le rejeu, les plafonds,
l'idempotence, le journal HTTP et le dry-run ; les données réelles ne sont
jamais dans les fixtures ou dans les journaux CI.
