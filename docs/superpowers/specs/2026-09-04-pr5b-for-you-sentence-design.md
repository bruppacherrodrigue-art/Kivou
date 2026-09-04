# PR5b — Phrase « Pour vous »

## But

Chaque couple signal–profil cible possède une phrase française rédigée, identique dans Aujourd’hui, le drawer, le cold mail et l’alerte hebdomadaire. La génération ne bloque jamais la matérialisation ni le parcours d’atterrissage.

## Architecture

Une table dédiée conserve une version par couple et par empreintes du signal et du profil. À la création ou mise à jour d’un signal matérialisé, la transaction écrit immédiatement la première `fit.reason` comme repli disponible et enregistre un travail de génération durable. Aucun appel fournisseur n’a lieu dans cette transaction.

Un worker borné réclame les travaux en attente, appelle un protocole de génération défini dans `signals.personalization`, valide la sortie, puis remplace atomiquement le repli si la phrase est acceptée. Une panne, un timeout ou une sortie rejetée laisse le repli visible et clôt le travail avec son motif. Les reprises sont idempotentes : une paire d’empreintes ne provoque au plus qu’une génération réussie ou rejetée.

L’adaptateur fournisseur existant est factorisé afin que son module reste le seul endroit qui nomme le modèle et implémente le transport HTTP. Le service métier ne connaît qu’un protocole injecté et ne déclenche jamais de réseau dans les tests.

## Entrées et sortie

L’entrée du générateur contient seulement les champs vérifiés du signal : titulaire, objet, montant et devise, lieu, date, CPV, besoins plausibles et raisons de correspondance. Elle contient aussi le secteur, les zones et la phrase « ce que vous vendez » du profil cible. Le prompt délimite ces données comme contenu non fiable et demande une seule phrase française de 25 mots maximum, sans point d’exclamation ni superlatif.

La sortie persistée contient la phrase servie, les empreintes d’entrée, la provenance `generated` ou `fallback`, le verdict de validation, le motif fermé de rejet, le détail libre expurgé, les horodatages et la version de politique. Aucune réponse brute du fournisseur n’est exposée aux clients.

## Validation déterministe

La validation compte les mots après normalisation Unicode, refuse `!` et une liste versionnée de superlatifs français. Chaque nombre et chaque date normalisés doivent être présents dans les entrées. Les séquences capitalisées interprétées comme noms propres ou lieux doivent appartenir au lexique construit depuis le titulaire, l’acheteur, l’objet, le lieu, les besoins, les raisons et le profil. La majuscule du premier mot ne suffit pas à classer un terme comme nom propre.

Tout échec utilise la première raison de correspondance déjà vérifiée. Le motif appartient à une énumération fermée : `provider_unavailable`, `invalid_shape`, `too_many_words`, `exclamation`, `superlative`, `invented_number`, `invented_date`, `invented_name_or_place`. Les compteurs `attempted`, `accepted`, `rejected` et `fallback` permettent de calculer le taux de rejet journalier sans relire du texte libre.

## Cache et invalidation

La clé logique est `(signal_key, target_icp_id, signal_fingerprint, profile_fingerprint, policy_version)`. Un changement du signal, du profil ou de la politique crée un nouveau travail ; un rendu ne génère jamais. Les anciennes versions restent auditables mais seule la version courante est jointe aux réponses.

## Consommateurs

Le feed et le détail exposent `for_you_sentence`. Aujourd’hui et le drawer affichent ce champ. Le runtime d’acquisition et l’alerte hebdomadaire lisent cette même valeur persistée lors de leur composition ; ils ne possèdent ni prompt ni rédaction alternative. Si la génération n’est pas terminée, les quatre surfaces voient le même repli.

## Backfill et exploitation

La commande `python -m signals.personalization.for_you_backfill --limit N --since YYYY-MM-DD` sélectionne uniquement les couples courants sans tentative pour leurs empreintes. `--limit` est obligatoire et strictement positif ; `--since` filtre la date de matérialisation. Elle utilise le même worker que le traitement normal.

Sur staging, la commande est lancée une fois sur exactement 50 couples pour le benchmark. Le rapport fournit 20 phrases, les volumes acceptés/rejetés/replis et le taux de rejet calculé depuis la table. Aucun backfill production n’est inclus : avant l’ouverture, il visera seulement les comptes actifs, jamais l’ensemble des 39 000 signaux.

## Tests et critères

Les tests restent hors ligne avec un faux fournisseur : phrase acceptée, chiffre/date/nom/lieu inventé, point d’exclamation, superlatif, dépassement de 25 mots, repli, cache, invalidation d’empreinte et panne fournisseur. Un test d’intégration prouve que la matérialisation commit malgré un fournisseur indisponible et qu’un worker ultérieur enrichit la phrase. Un test de contrat compare byte pour byte la phrase des quatre consommateurs. Le test PR5 clic → dashboard est rejoué sans fournisseur et doit rester dans sa variance normale, sans appel réseau ni attente supplémentaire.
