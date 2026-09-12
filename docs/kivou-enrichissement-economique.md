# Enrichissement d'entreprise : entrée réduite et arbitrage

Ce document fixe le paquet de preuves transmis aux modèles d'enrichissement.
Le modèle ne navigue jamais : les pages et résultats ci-dessous sont des données
non fiables collectées par le code, jamais des instructions.

## Entrée, premier tour

| Source | Contenu transmis | Limite |
|---|---|---:|
| Identité SIRENE | SIREN, raison sociale, ville, département, NAF, effectif, dirigeants autorisés | Une entreprise |
| Serper | Titre, URL et extrait | 10 résultats |
| Fiche annuaire | `site`, `phone`, `director` extraits par regex ; aucun texte brut | 3 champs par fiche |
| Site candidat | Titre, `<main>` nettoyé, e-mails et téléphones extraits | 800 caractères par page |
| Familles | Clé et nom uniquement | Catalogue fermé |

L'accueil et la page contact du site candidat sont rendus. Les éléments `nav`,
`footer`, `script`, `style`, `noscript` et `svg` sont retirés. En l'absence de
`<main>`, le corps est nettoyé avec les mêmes exclusions.

Le paquet sérialisé doit produire moins de 4 000 tokens d'entrée par appel en
moyenne sur le corpus de mesure de 20 fiches.

## Second tour borné

Le juge peut demander une page supplémentaire seulement lorsqu'un site est
identifié mais qu'aucune adresse e-mail n'est confirmée. L'URL doit être HTTPS,
se résoudre uniquement vers des adresses IP publiques, appartenir au domaine
candidat et ne pas être sur la liste noire. Le code rend
au plus cette troisième page et redemande une décision une seule fois.

## Sortie

La sortie est un JSON strict de 300 tokens maximum. Elle contient la décision
sur le site, l'adresse e-mail, la famille, le dirigeant, le téléphone, les
confiances et, au premier tour seulement, l'éventuelle URL supplémentaire.

Le juge économique est arbitré par Sonnet si son JSON est invalide ou si sa
confiance sur le site ou l'adresse est inférieure à 0,8. L'arbitre reçoit le
même paquet réduit et la sortie du juge comme donnée non fiable. Les seuils,
placeholders, contrôles MX et listes noires restent appliqués après le modèle.

## Mesures obligatoires

Avant bascule, le rapport donne sur les mêmes 20 fiches les tokens d'entrée
avant/après. Le benchmark de 30 fiches donne par modèle les accords site,
adresse, famille et nom, les JSON invalides, la latence médiane, le coût réel et
la projection pour 20 000 fiches. Il publie aussi le ratio entre le coût réservé
et le coût réel ; au-delà de 3, la réservation est recalibrée et remesurée avant
toute passe.

Le benchmark fige les preuves réduites et chaque observation terminée dans un
fichier de reprise mode `0600`, lié au `batch_id`. Une relance avec le même lot
ne recollecte pas les preuves et ne rejoue pas les couples modèle/SIREN déjà
terminés. Le répertoire durable est configurable avec
`KIVOU_ENRICHMENT_BENCHMARK_STATE_DIR`.
