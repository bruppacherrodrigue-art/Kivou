# Répétition réelle 893312e — conservation validée, performance refusée

Candidate : `893312e1e0a008e0da7797fb1e2ca5dd96f32332`.
[CI exacte](https://github.com/bruppacherrodrigue-art/Kivou/actions/runs/34781563227) : sept jobs réussis, terminés le13septembre2026 à20:59:04UTC ;6478tests backend réussis,11skips,un xfail historique ;752tests frontend et32visuels réussis. Builds client/Founder, types et lint verts. La CI intermédiaire e686 a été annulée automatiquement au push suivant ; elle n'est pas une preuve backend complète.

Répétition sur restauration complète du13septembre,20:43:32–20:58:01UTC : unité `kivou-v11-rehearsal-893312e.service`, code2, étape finale `copy_api_checks`, statut `latency_budget_failed`. **Cette candidate n'a pas été activée.** Le rapport agrégé durable est conservé dans le répertoire privé de l'opération ; aucune note, coordonnée privée, session ou valeur d'export n'est publiée ici.

## Données et parcours sur copie

- 26 tables privées et 260 070 lignes anciennes comparées exhaustivement : conservées.
- 34 comptes historiques exportés et vérifiés en mémoire.
- Huit contrats validés : isolation compte/export, CAS note/statut, tombstones note/contact, limite 2 000 caractères, conservation de l'historique de contact après retour à `new`.
- Audit registre : 666 enregistrements exacts, 363 non résolus ; audit comptes : 2 942 résolutions, 1 353 non résolues, aucune fusion arbitraire.
- Quatre avis BOAMP/six lots stockés en une passe, aucun pending/terminal, rejeu idempotent. La régression du SIRET RAZEL espacé est corrigée sur les véritables données historiques.
- Préparation QA sur copie : trois plans prêts, authentification réelle sans override ni fournisseur. Découverte : 3 signaux accessibles sur 6 ; Essentiel : 6 sur 6 ; Pro : 6 sur 12 (deux profils), chacun un SIREN réellement disponible dans l'annuaire. Aucune création QA sur la base vive à cette étape.

## Mesures API

Compte de recette existant, Essential, un profil fixé de1148signaux courants. Transport ASGI/TestClient, sans proxy/réseau ni traitement fournisseur. Pour chaque route : sonde initiale puis20mesures séquentielles ; p95 au rang supérieur. Le budget reste strictement inférieur à800ms.

| Route | p50(ms) | p95(ms) | Verdict |
| --- | ---: | ---: | --- |
| Aujourd'hui |865,35|908,85|Refusé|
| Signaux |173,13|310,17|Validé|
| Entreprises |206,32|365,56|Validé|
| Annuaire |252,97|391,48|Validé|
| Détail signal |156,29|299,95|Validé|
| Dossier entreprise |1057,02|1194,95|Refusé|

Les deux dépassements bloquent la bascule. Les optimisations doivent conserver données, droits, compteurs et indications de troncature ; aucune hausse du budget ni réduction du nombre d'échantillons.

## Q23 — revue des faits publics réellement extraits

Source recueillie le13septembre à20:54:52UTC, extracteur `boamp-notice-facts-v1`. Les chemins de provenance et les hashes sont ceux du rapport issu du reader BOAMP, pas du prototype.

| Avis / lot / marché | Titulaire | Publication | Calendrier attesté |
| --- | --- | --- | --- |
|[26-84423](https://www.boamp.fr/pages/avis/?q=idweb:26-84423),LOT-0002,CON-0001|ERGC,EUROP TP,NGE FONDATIONS,EUROP ACRO,TM SCOP|01/09/2026|24mois de travaux|
|26-84423,LOT-0011,CON-0002|DALKIA|01/09/2026|24mois de travaux|
|26-84423,LOT-0012,CON-0003|EIFFAGE ENERGIE SYSTEMES COTE D'AZUR|01/09/2026|24mois de travaux|
|[26-85899](https://www.boamp.fr/pages/avis/?q=idweb:26-85899),LOT-0000,CON-0001|LEFEVRE CENTRE OUEST|06/09/2026|12mois maximum par bon de commande, pas durée totale du marché|
|[26-87113](https://www.boamp.fr/pages/avis/?q=idweb:26-87113),LOT-0001,CON-0001|RAZEL-BEC SAS|10/09/2026|Trois reconductions maximum ; aucune durée initiale/maximale rattachable, aucun démarrage inventé|
|[26-88050](https://www.boamp.fr/pages/avis/?q=idweb:26-88050),LOT-0001,CON-0001|GJG FONCIERE|12/09/2026|240mois de contrat, pas de travaux ; avis annulé, sans conclure à l'annulation du marché|

RAZEL : le champ de reconductions provient directement de `cac:ContractExtension/cbc:MaximumNumberNumeric` dans l'avis d'attribution. La consultation25-2744 a un UUID de procédure contradictoire ; elle n'autorise pas à ajouter12/48mois. L'absence de durée ne supprime pas les trois reconductions effectivement documentées.

Hashes SHA256 des sources :

| Avis | content_hash |
| --- | --- |
|26-84423|`932b5479437a72913e9e02e88df18009f4d1dd2729568272310fe0762d96891d`|
|26-85899|`997159c2d8873412edd8eab4e9c5fd0b61fe08ed4b0eb2abceb9ad92f9357ade`|
|26-87113|`75822106b468fbbdd47b30f69c3f6431cf5ca7c709e7198386d5370a005427be`|
|26-88050|`803cf06f04d4c2b48d550e86d880a1b3926832ac17ce03e543b8caa050a25775`|

## Nettoyage et état live

Suppression de la seule copie validée par son OID et de son dump temporaire confirmée. Liens backend/frontend toujours sur2599, schéma0058 inchangé. La sauvegarde préactivation privée de20:06 reste volontairement conservée dans le répertoire normal et suit sa rétention habituelle. Aucun nginx actif, worker, paiement, envoi commercial ou fournisseur payant modifié par cette répétition.
