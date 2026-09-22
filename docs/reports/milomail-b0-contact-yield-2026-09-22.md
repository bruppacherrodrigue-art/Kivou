# Milo Mail — rendement B0 réel sur entreprises Google Workspace

**État au 22 septembre 2026 : échantillon B0 de 200 entreprises terminé, sans envoi.**
Ce rapport ne contient que des agrégats. Les identités, adresses et réponses
Apollo restent dans la base PostgreSQL isolée `kivou_milomail_census_a0`, à la
révision `0075_milomail_b0_contact_yield`. La base applicative staging est restée
à `0065_chief_of_staff`. Milo Mail est le produit ; Milo est son agent. Milo Mail
ne reçoit aucune donnée de prospection.

## Méthode et échantillon

A1 a observé 384 entreprises Google Workspace uniques dans la fenêtre Apollo
accessible. B0 a sélectionné de façon déterministe un maximum de 200 entreprises,
stratifiées selon secteur, tranche d'effectif Apollo, partition, profondeur de
page, preuve administrative et qualité de fiche. Les précédents checkpoints,
suppressions connues et réponses Apollo sans checkpoint ont été exclus des
plans suivants. Quatre permis ont réellement exécuté des appels ; un premier
permis préparatoire a été révoqué avant tout appel payant. Les quatre permis
utilisés sont maintenant révoqués. Chaque entreprise a eu au plus deux candidats
dirigeants recherchés et un seul e-mail livrable retenu. Aucun e-mail n'a été
construit par supposition ou testé par SMTP.

Le premier micro-pilote de cinq entreprises a trouvé un dirigeant et une adresse
professionnelle Google Workspace vérifiée pour un crédit débité. Les micro-lots
des permis de continuation ont recalibré leur solde avant la suite. Le deuxième
permis s'est arrêté sur un compteur Apollo ambigu, le troisième après une
réponse payante sans checkpoint ; ces appels restent conservés dans le ledger
et n'ont jamais été rejoués. Le quatrième permis a amené le cumul à 200
checkpoints sans dépasser les plafonds.

## Funnel mesuré

| Mesure | Valeur |
| --- | ---: |
| Entreprises Google Workspace A1 effectivement observées | 384 |
| Entreprises B0 avec checkpoint complet | 200 |
| Dirigeants pertinents identifiés | 85 |
| E-mails professionnels trouvés | 80 |
| E-mails professionnels vérifiés sur le domaine Google Workspace | 80 |
| Aucun contact trouvé | 115 |
| Domaine d'adresse différent de l'entreprise | 4 |
| Rôle rejeté après enrichissement | 1 |
| Entreprises avec un deuxième candidat enrichi | 2 |
| Décision théorique HOLD | 80 |
| Décision NO_SEND | 120 |
| Décision SEND_THEORETICAL | 0 |
| Identifiants légaux validés sur un site public | 1 |
| Entreprises `CONFIRMED_MATCH + ACTIVE` | 1 |
| Entreprises `AMBIGUOUS_MATCH` / `NO_MATCH` parmi les 80 adresses | 6 / 73 |
| Appels Apollo People Search inscrits | 203 |
| Appels Apollo People Enrichment inscrits | 89 |
| Appels terminés sans checkpoint d'entreprise | 5 : 3 recherches gratuites, 2 enrichissements |
| Crédits réservés au pire cas pour les appels B0 | 801 |
| Solde initial / final du pool partagé | 2 045 / 1 956 crédits |
| Variation brute du pool partagé | 89 crédits |
| Réserve effective finale | 1 956 crédits, soit 1 456 au-dessus du minimum |
| Coût incrémental, sans achat ni top-up | 0,00 CHF |
| Coût comptable d'allocation des crédits prépayés | inconnu |
| Mutations Instantly / e-mails envoyés / déploiements | 0 / 0 / 0 |

Les **87 enrichissements checkpointés** montrent chacun un delta immédiat de
un crédit. Deux enrichissements supplémentaires ont un reçu Apollo `COMPLETED`
mais pas de checkpoint d'entreprise. Le solde du pool est passé de 2 045 à
1 956 crédits, soit 89, ce qui concorde avec les 89 enrichissements inscrits.
Le pool étant partagé, cette concordance ne prouve pas à elle seule une
attribution exclusive. Le coût opérationnel observé sur les seuls checkpoints
est **87/80 = 1,09 crédit par adresse vérifiée** et **87/200 = 0,435 crédit
par entreprise étudiée**. Le débit global est 89 crédits ; le prix comptable
unitaire en CHF n'est pas connu. Le plafond autorisé était 1 500 nouveaux
crédits avec au moins 500 restants ; ni achat ni rechargement n'a été effectué.

Les 80 adresses techniques sont en HOLD. Pour 79, l'activité officielle n'est
pas confirmée. Le seul cas `CONFIRMED_MATCH + ACTIVE` reste aussi HOLD : pays
Apollo non confirmé et configuration d'envoi fermée (identité, opposition,
transparence, domaine/boîte, landing française et budget d'envoi). Les 120
NO_SEND proviennent de 115 absences de contact, 4 domaines incohérents et
1 rôle rejeté. Aucun `SEND_THEORETICAL` n'a été forcé pour augmenter le chiffre.

## Rapprochement administratif

Les 384 fiches A1 ne comportaient ni ville ni code postal. La recherche par nom
seul avait donné 353 résultats non corroborés et 31 ambigus, sans démontrer
une cessation d'activité. Le nouveau chemin lit au plus quatre pages publiques
par domaine validé, vérifie la syntaxe et le checksum des SIREN/SIRET/TVA,
interroge l'API Recherche d'entreprises par identifiant exact, puis exige que
l'identité officielle corrobore la fiche Apollo. La page web est traitée comme
donnée non fiable, sans exécution de JavaScript ni de ses instructions.

Le compteur d'appels à l'API officielle est passé de **384 après A1 à 464
après B0**, soit 80 nouveaux appels. Les recontrôles ont réutilisé le cache.
Parmi les 80 domaines soumis au résolveur v3, le cache retient : 29 fichiers
`robots.txt` indisponibles ou restrictifs, 42 pages légales inaccessibles,
7 pages consultables sans identifiant valide, 1 domaine non résolu vers une
adresse publique et **1 identifiant valide** ayant conduit à une entreprise
ACTIVE officiellement confirmée. Ces catégories n'affirment rien sur
l'activité des 79 autres entreprises.

L'ancienne instrumentation n'a pas persisté chaque tentative HTTP de site :
61 tentatives ont été explicitement comptées dans les recontrôles publics des
53 premiers cas, mais le total de toutes les passes B0 n'est pas reconstructible.
Il s'agit d'une limite d'observabilité ; aucun nombre total n'est inventé.
Les preuves et les pages brutes restent uniquement dans la base autorisée.

## Projection France, non inventaire d'adresses

Le taux brut **80/200 = 40,0 %** décrit l'échantillon. La pondération par les
18 strates A1 donne un taux central de **39,57 %** d'entreprises Google Workspace
permettant une adresse professionnelle vérifiée. L'intervalle simultané
Wilson-Bonferroni à 95 % est **14,21 %–72,54 %**. Cette méthode suppose en plus
une échangeabilité non vérifiée au sein de chaque strate. Les tris Apollo,
recouvrements, entreprises non accessibles au-delà de la limite d'affichage et
qualité des fiches peuvent élargir l'incertitude réelle.

| Base A1 Google Workspace | Dirigeants : bas / central / haut | Adresses GW vérifiables : bas / central / haut | Portée |
| --- | ---: | ---: | --- |
| Portion affichable Apollo | 778 / 3 209 / 8 461 | **702 / 3 011 / 8 240** | Extrapolation à partir de 4 944 / 7 610 / 11 359 entreprises estimées |
| Tous résultats déclarés | 2 024 / 8 398 / 22 265 | **1 828 / 7 882 / 21 684** | Hors fenêtre Apollo, forte incertitude ; base 12 861 / 19 918 / 29 891 |

Il s'agit de volumes potentiellement **vérifiables**, jamais d'adresses déjà
obtenues. Le nombre réellement vérifié dans ce pilote est **80**. La collecte
complète de la portion affichable coûterait, dans un scénario maintenant le
ratio checkpointé de 87/80 crédits par adresse vérifiée, environ **764 / 3 275 /
8 961 crédits** pour les bornes basse / centrale / haute. Ce calcul est
indicatif : il ignore les appels orphelins, variations de tarification et
limitations d'accès Apollo. Son équivalent CHF comptable est inconnu. La
projection hors fenêtre Apollo n'est pas un inventaire accessible. Aucune
projection `SEND_THEORETICAL` n'est défendable avec une seule entreprise active
confirmée et l'infrastructure d'envoi volontairement fermée.

## Sécurité, conservation et suite

Milo Mail est resté désactivé en SHADOW, avec volumes et coûts d'envoi à zéro.
B0 n'importe rien dans Instantly et n'appelle aucune fonction d'envoi. Les cinq
appels sans checkpoint sont marqués dans le ledger et exclus des plans suivants ;
aucune facturation répétée n'a été déclenchée. Les quatre permis exécutés sont
révoqués et aucun B0 supplémentaire n'est nécessaire pour atteindre 200
entreprises. Les données personnelles restent dans la base isolée, avec un TTL
de 30 jours. La commande sélective `purge-cache` retire les réponses Apollo et
champs personnels B0 après expiration, sans supprimer les suppressions, permis,
ledger ou preuves comptables.

Avant une future phase d'enrichissement plus large ou une activation de campagne,
il faut une nouvelle autorisation bornée, une clé Milo Mail dédiée, une méthode
administrative mieux couverte, une landing française, des domaines et boîtes
autorisés, le mécanisme d'opposition et les contrôles du Policy Gateway. Ce
pilote n'a produit aucun e-mail envoyé et aucune donnée Gmail/OAuth n'a traversé
la frontière entre produits.
