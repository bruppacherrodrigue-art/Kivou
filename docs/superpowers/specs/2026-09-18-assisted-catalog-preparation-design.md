# Conception — préparation catalogue ASSISTED

> **Statut : référence active.** Ce document remplace la conception et le plan Stendhal/couple unique du 18 septembre 2026.

## Objectif

Remplacer la préparation d'un couple unique famille–avis par une préparation catalogue. Le même chemin est appelé par `POST /api/founder/actions/prospection/prepare` et par le timer ASSISTED. Il parcourt toutes les familles de `ops/config/supplier-families.yaml`, sélectionne des avis strictement mono-famille, puis crée au plus 25 lignes `pending_review` toutes familles confondues.

Cette opération prépare une file de revue. Elle n'appelle jamais `/send`, ne déclenche aucune mutation Instantly et n'utilise ni modèle ni Apollo pour compléter un vivier.

## Source de vérité

Le cycle d'acquisition affiché par la console reste un résumé opérationnel. Il n'est ni la source du prochain `prepare`, ni la source métier des lignes de la file.

Chaque `prospect_target` est autonome et porte obligatoirement :

- un seul `family_key` ;
- l'`opportunity_key` exact de l'avis qui a produit la ligne ;
- les faits de cet avis utilisés comme bait ;
- un token kat1 créé pour le couple cible–avis ;
- l'`attribution_url` correspondant à ce token.

Le prochain `prepare` repart du catalogue YAML, des avis matérialisés, de l'annuaire fournisseur et de l'historique des cibles. Il ne repart jamais de l'`opportunity_key` ou des `family_keys` du dernier cycle vitrine.

## Sélection des avis

Le service parcourt toutes les familles dans l'ordre stable du catalogue : ordre des verticales dans le YAML, puis `priority`, puis `family_key`.

Pour une famille `F`, un avis est admissible seulement si :

- sa famille recalculée depuis les faits matérialisés vaut exactement `[F]` ;
- son titulaire est résolu par la source officielle ;
- son attribution est dans la fenêtre courante de 30 jours ;
- son montant et ses faits publics satisfont les règles de production déjà en vigueur ;
- son objet n'est pas vide.

Une correspondance multi-famille est rejetée. En particulier, un avis timber ne peut jamais transporter `roofing` ou `scaffolding`.

Les avis admissibles d'une famille sont classés par :

1. nombre de cibles site fraîches décroissant ;
2. date d'attribution décroissante ;
3. `opportunity_key` croissant pour départager de façon déterministe.

La préparation commence avec le meilleur avis de chaque famille. Si les viviers de premier niveau sont épuisés et que la file reste sous le plafond, elle ouvre le deuxième avis des familles concernées, puis les suivants, en conservant le même mécanisme équitable.

## Sélection des cibles

Le vivier d'un avis contient uniquement les fournisseurs :

- confirmés pour la famille `F` ;
- situés dans le département de l'avis ou dans ses départements voisins versionnés ;
- dotés d'un e-mail professionnel publié sur leur site avec sa preuve ;
- non supprimés de l'annuaire.

Les candidats sont exclus et comptés séparément pour les motifs suivants :

- `sent_30j` : SIREN accepté pour envoi durant les 30 derniers jours ;
- `rejected_history` : SIREN déjà rejeté historiquement ;
- `holder` : SIREN du titulaire de l'avis ;
- `non_site_email` : aucune adresse publiée sur le site ;
- `active_duplicate` : SIREN déjà présent en `pending_review` ou `approved`, ou déjà choisi dans le lot courant ;
- `historical_target` : même identité cible–avis déjà matérialisée historiquement.

Un SIREN ne peut apparaître qu'une fois dans la file active, même s'il est admissible pour plusieurs avis ou plusieurs familles.

## Allocation globale

Le plafond de file est de 25 lignes actives au total. Il inclut toutes les lignes déjà en `pending_review` ou `approved`, quelle que soit leur date de création. La nouvelle préparation ne crée que le delta disponible :

```text
places_disponibles = 25 - lignes_actives
```

L'allocation est un round-robin strict :

1. première passe : au plus une cible par famille éligible ;
2. passes suivantes : une cible supplémentaire par famille encore alimentée ;
3. arrêt dès que la file contient 25 lignes actives ou que tous les viviers sont épuisés ;
4. si les meilleurs avis sont épuisés avant le plafond, ouverture des avis de rang suivant puis reprise du round-robin.

Les candidats encore éligibles après atteinte du plafond sont comptés `deferred_global_cap`. Ils ne sont jamais marqués `rejected` et restent disponibles pour une préparation ultérieure.

## Personnalisation et kat1

Chaque ligne est rendue avec sa propre paire `(family_key, opportunity_key)` :

- le titulaire, l'objet, le montant, la zone et la date proviennent de cet avis ;
- le vocabulaire métier provient uniquement de cette famille ;
- le sujet, le texte et le HTML ne peuvent pas reprendre le bait d'une autre ligne ;
- le token kat1 est unique pour la paire cible–avis ;
- la valeur persistée dans `attribution_url` est exactement celle injectée dans `mail_text` et `mail_html`.

L'égalité des trois occurrences de l'URL est vérifiée avant toute insertion. Le token et son payload ne doivent contenir aucune fuite de métier provenant d'une autre famille.

## Idempotence

Un deuxième `prepare` le même jour ignore tout SIREN déjà `pending_review` ou `approved`, réutilise le plafond restant et ne crée ni deuxième ligne ni deuxième token pour ce SIREN.

L'identité historique cible–avis reste déterministe. Une cible déjà matérialisée pour le même avis n'est jamais recréée, même si son ancienne ligne n'est plus active.

## Transactions et concurrence

Le POST et le timer utilisent le même orchestrateur catalogue et le même verrou d'acquisition. Le service prend aussi le verrou transactionnel de préparation avant de recalculer le plafond et les doublons.

Le travail suit deux phases :

1. qualification en lecture seule des familles, avis et candidats ;
2. validation de toutes les lignes rendues, puis insertion de tout le lot dans une transaction globale.

Une erreur de qualification propre à une famille est isolée : la famille produit zéro ligne, reçoit un motif d'erreur, et les autres familles continuent. Une erreur globale — verrou, base, rendu, kat1, invariant d'URL ou insertion — annule la transaction complète et produit zéro insertion.

## Résultat et décompte

Le résultat de préparation contient une ligne par famille du catalogue avec :

- les avis examinés et les avis admissibles ;
- les avis effectivement utilisés ;
- le nombre de candidats éligibles ;
- le nombre de lignes enfilées ;
- le nombre reporté par `deferred_global_cap` ;
- les refus ventilés par motif.

Une famille sans production porte un `zero_reason` explicite :

- `no_mono_avis` ;
- `no_official_holder` ;
- `no_site_in_geo` ;
- `all_candidates_excluded` ;
- ou un code d'erreur de qualification borné et sans secret.

Une famille à zéro ne bloque jamais les autres.

## Intégration runtime

`prepare-queue` devient le point d'entrée unique de la préparation catalogue lorsque la configuration est en mode `ASSISTED`. Le lanceur Founder continue à répondre `202` immédiatement et à démarrer ce même processus asynchrone. Le timer appelle la même commande et obtient donc exactement les mêmes règles, plafonds et protections d'idempotence.

La configuration ne pince plus une famille ou un avis unique pour la préparation ASSISTED catalogue. Le cycle éventuellement conservé pour l'affichage est calculé après l'opération comme résumé du lot ; il ne pilote aucune sélection ultérieure.

## Recette

La recette doit prouver :

- `0 < N <= 25` si au moins une cible existe ;
- `N` tient compte de toutes les lignes déjà actives, y compris celles d'un jour précédent ;
- toutes les nouvelles lignes sont `pending_review` ;
- chaque ligne contient un seul `family_key`, l'avis mono-famille correspondant et une adresse `email_source=site` ;
- le titulaire de chaque avis est absent des cibles associées ;
- aucun SIREN n'est dupliqué dans la file active ;
- `attribution_url` est identique dans le champ, le texte et le HTML ;
- un second `prepare` ne crée ni nouvelle ligne ni nouveau token pour les SIREN déjà actifs ;
- une preview électrique utilise un avis électrique ;
- une preview d'une autre famille, si elle existe, utilise l'avis et le vocabulaire de cette famille ;
- aucune preview ni aucun token ne contient de fuite de métier ;
- le compteur `sent` est strictement inchangé ;
- aucun appel `/send`, aucune mutation Instantly, aucun appel modèle et aucun appel Apollo n'a lieu.

Le compte rendu final donne, pour chaque famille, `éligibles / enfilées / refus / deferred_global_cap`, les avis utilisés et le `zero_reason` éventuel.

## Hors périmètre

- envoi ou reprise d'envoi ;
- vérification de livraison Instantly ;
- enrichissement par modèle ou Apollo ;
- élargissement national de la zone ;
- modification du catalogue des familles ou de ses règles CPV ;
- correction de titres BOAMP ;
- refonte générale de la page Entreprises ou de la console.
