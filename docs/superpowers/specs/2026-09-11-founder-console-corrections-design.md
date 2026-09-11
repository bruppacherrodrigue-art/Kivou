# Founder Console — état acquisition, tunnel et annuaire

## Objectif

Corriger la Founder Console avant lundi pour qu'elle expose une seule vérité opérationnelle sur l'acquisition, un tunnel commercial lisible selon deux vues, et un annuaire dont les domaines visibles sont réellement confirmés. La console reste privée, en lecture seule et servie sur `control.kivou.eu`.

## Contraintes conservées

- Aucun changement de schéma ni nouvelle migration.
- L'API Founder reste sur `127.0.0.1:8011` et conserve son rôle PostgreSQL en lecture seule.
- Les modèles analytiques existants (proxy de livraison, M2, wedges et qualité) peuvent rester dans l'API, mais ne sont plus affichés.
- Les boutons de la File du jour restent désactivés tant que les actions assistées de la Session A ne sont pas disponibles.
- Les dates affichées et les bornes calendaires utilisent `Europe/Zurich`; les dates persistées restent en UTC.

## 1. État d'acquisition unique

Un contrat `FounderAcquisitionStatus` devient l'unique source affichée sur Aujourd'hui, Prospection et Système. Il contient :

- `mode` : mode observé dans `acquisition_runtime_observation`, actuellement `SHADOW`;
- `activity` : `RUNNING`, `STOPPED` ou `UNKNOWN`, lu depuis `kivou-acquisition-production.timer`;
- `activity_since` : `ActiveEnterTimestamp` quand le timer est actif, `InactiveEnterTimestamp` quand il est arrêté;
- `last_cycle_ref`, `last_cycle_at` et `last_cycle_status` : champs de la dernière observation du runtime;
- `last_cycle_reason_code` : motif du cycle référencé, lu dans `acquisition_runtime_cycle`.

Le read model agrège ces deux autorités techniques une seule fois et fournit le même objet aux endpoints Overview et Prospection. Une observation absente ne déclenche aucun calcul optimiste : le mode et le cycle deviennent inconnus. Un échec ou un état transitionnel de systemd donne `UNKNOWN`.

Le frontend rend le même composant sur les trois emplacements : mode traduit, « Actif depuis… » ou « Arrêté depuis… », dernier cycle et résultat traduit. Il supprime de l'écran :

- « État global : Non prêt »;
- la carte « Hermes : Prêt »;
- le mode sûr issu de readiness;
- la ligne de santé « Runtime Hermes » lorsqu'elle serait présentée comme un second état global.

Les détails techniques de santé et les gates peuvent rester visibles dans Système, sans produire un autre mode ni un autre état synthétique d'acquisition.

## 2. Tunnel commercial

La section Business devient « Tunnel commercial ». L'ancien cockpit hebdomadaire reste dans la réponse API pour les usages analytiques, mais le frontend n'affiche plus proxy de livraison, réponses positives, M2, wedges, secteurs non résolus ni tableau analytique.

### Vue par période — vue par défaut

L'onglet par défaut est « Période » et la sélection initiale est « 7 derniers jours ». Une bascule permet « Aujourd'hui ».

- Aujourd'hui : de minuit Europe/Zurich jusqu'à `now`.
- 7 derniers jours : les sept jours calendaires incluant aujourd'hui, de minuit six jours auparavant jusqu'à `now`.
- Les bornes sont converties en UTC avant les requêtes.

Chaque étape est comptée à sa propre date, indépendamment des autres étapes :

- Envoyés : membres distincts ayant un événement `email_sent`, étape 1, dans la période.
- Ouverts : membres distincts ayant un événement `email_opened` accepté ou traité dans la période.
- Clics : événements de conversion `CLICK` distincts dans la période.
- Atterrissages : comptes non-QA distincts dont `account_landing_signal.created_at` est dans la période.
- Profils confirmés : comptes non-QA distincts dont `profile_confirmed_at` est dans la période.
- Payants : comptes distincts ayant un événement `PAID` dans la période.

La réponse expose les bornes exactes pour que l'interface indique clairement la période observée.

### Vue par cohorte — onglet secondaire

Le sélecteur existant des 52 semaines terminées est conservé. La cohorte contient les membres distincts dont le premier mail (`email_sent`, étape 1) appartient à la semaine sélectionnée.

Pour cette cohorte, Ouverts, Clics, Atterrissages, Profils confirmés et Payants comptent tout événement atteint après l'envoi et jusqu'à `now`, sans borne à la clôture de la semaine. Un clic à J+10 appartient donc à la cohorte d'envoi. Les comptes sont reliés à la cohorte par `acquisition_conversion_journey.member_ref`.

### Situation actuelle

MRR et Churn sont affichés dans un encart « Situation actuelle », identique pour les deux vues et indépendant de la période/cohorte :

- MRR : dernière valeur connue par parcours payé, hors parcours churné, agrégée par devise;
- Churn : nombre de parcours dont l'état commercial courant est churné.

Ces valeurs sont calculées à `now` et portent leur propre horodatage. Elles ne sont jamais présentées comme des résultats de la semaine ou de la cohorte.

## 3. Liste noire et audit

`localbiz.fr` est ajouté à la liste centrale des domaines annuaires rejetés. La règle couvre le domaine exact et tous ses sous-domaines.

Une commande opérationnelle idempotente audite toutes les fiches actives dont le domaine est marqué confirmé. Elle utilise exactement la même fonction de rejet que la résolution de domaines :

- mode par défaut : simulation, sans écriture;
- `--apply` : chaque fiche touchée passe « à revérifier » avec le motif `blocked_domain_audit`;
- l'identité fournisseur, la famille et la localisation restent intactes;
- domaine, URL, liaison Apollo, e-mail et preuves de contact sont effacés par la méthode existante `mark_for_reverification`;
- la sortie indique le nombre de fiches examinées, touchées et modifiées, ainsi que leurs SIREN/domaines;
- une seconde exécution ne modifie rien.

L'instantané de pré-audit du 11 septembre trouve une fiche confirmée : AJEBAT, SIREN `402274716`, domaine `neyron.localbiz.fr`. Après déploiement, la procédure est : simulation, application, puis nouvelle simulation qui doit trouver zéro domaine confirmé bloqué.

## 4. Annuaire Prospection

- La File du jour est toujours le premier bloc de contenu après l'en-tête Prospection, même lorsqu'elle est vide.
- L'état vide dit explicitement qu'aucune cible en attente de revue n'a encore été produite par la Session A et rappelle l'état acquisition unique.
- Le contrat actuel des lignes `pending_review` et le panneau de mail sont conservés pour recevoir les données de la Session A.
- Dans la colonne Domaine, une fiche non confirmée n'affiche jamais le domaine ni un lien. Elle affiche seulement le badge « À qualifier ».
- Le statut distinct « À revérifier » reste visible dans la colonne État.
- Les départements sont fournis avec leur nom de référentiel. Le rendu est « Rhône (69) », « Isère (38) », etc., dans les facettes, le filtre et les lignes.
- `mx_verified`, `mx_accepted` et leurs variantes visibles sont rendus « MX vérifié ».
- Les modes, états de cycle et principaux motifs visibles sont traduits en français. Les codes bruts restent disponibles dans l'API.
- La description technique `supplier_directory` disparaît du texte utilisateur.

## 5. Frontières et erreurs

- Aucune nouvelle route d'écriture n'est ajoutée à l'API Founder.
- L'audit de domaines est un outil d'exploitation distinct; il n'est pas appelable depuis la console.
- Les requêtes du tunnel sont bornées par les périodes autorisées et le décalage de semaine `0..51`.
- Si l'état systemd est indisponible, l'interface affiche « État indisponible » sans réutiliser une date de dernier cycle comme date d'arrêt.
- Si aucun cycle n'est observé, la console affiche « Aucun cycle observé ».
- Les compteurs à zéro restent affichés à zéro.

## 6. Tests et recette

Backend :

- contrat unique identique entre Overview et Prospection;
- mode issu de `acquisition_runtime_observation`, dates actif/arrêté issues de systemd et résultat du cycle référencé;
- bornes Europe/Zurich pour Aujourd'hui et 7 derniers jours;
- chaque événement de période compté à sa propre date;
- cohorte hebdomadaire avec un clic à J+10 compté;
- MRR et churn identiques quelle que soit la vue;
- ajout de `localbiz.fr`, audit simulation/application/idempotence et nettoyage des champs sensibles;
- noms de départements et pagination conservée.

Frontend :

- même composant d'état sur Aujourd'hui, Prospection et Système;
- absence des anciens libellés État global/Hermes/proxy/M2/wedge/secteurs non résolus;
- vue Période par défaut sur 7 jours, bascule Aujourd'hui et onglet Cohorte;
- MRR/Churn clairement séparés comme situation actuelle;
- File du jour avant Annuaire;
- domaine non confirmé masqué, « À qualifier », départements nommés et « MX vérifié ».

Production :

- déploiement atomique par `kivou-deploy.sh` d'un SHA fusionné et validé;
- contrôle `401` sans Basic Auth, `200` avec Basic Auth et `404` sur `kivou.eu/api/founder/*`;
- vérification des services API, Founder et nginx;
- audit domaines simulation → application → zéro reliquat;
- captures desktop 1600 px : Aujourd'hui/Période, Aujourd'hui/Cohorte, Prospection et Système;
- aucune erreur console navigateur.

## 7. Intégration avec la Session A

La branche de la Session A modifie actuellement la revalidation de domaines et corrige une régression de baseline introduite par `1ac296e` : l'absence de résultat Serper était déclarée permanente avant de réutiliser une liaison Apollo valide. Cette livraison ne duplique pas cette correction. Avant l'implémentation finale, la branche est rebasée sur le `main` contenant la Session A, puis la suite complète de l'annuaire est rejouée. En cas de chevauchement sur les contrats `pending_review`, le contrat de la Session A prévaut et la File du jour s'y branche sans adapter la vérité métier côté frontend.
