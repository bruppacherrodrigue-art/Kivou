# PR1 — API tableau de bord, statut unifié et entreprises

**Date :** 2026-09-03 · **Branche :** `feat/pr1-dashboard-companies-api` depuis `main` (`82e7594`) · **Périmètre :** backend uniquement, aucun fichier `frontend/` · **Décision :** Rodrigue, PR1 de la refonte des trois écrans (Aujourd'hui, Signaux, Entreprises).

## 1. Principes

Réutiliser l'existant : signaux matérialisés (`materialized_signal`, `feed_page`, `history_page`), retours (`signal_feedback` : `relevance`, `contacted_at`), notes (`signal_note`), entreprises (`saas_company`, `company_keys_for_signals`, `company_profile_for_account`), accès plan (`feedable_target_icps`, `feed_access().is_unlocked`). Aucun moteur, aucune inférence nouvelle : « fit fort » lit la colonne stockée `icp_match_band` (`strong`), déjà calculée par le moteur de matching et jamais exposée jusqu'ici. Aucun appel Instantly, Apollo, Hermes. Ni prix ni facturation modifiés.

## 2. Statut unifié par signal

- `status` sur chaque item de `GET /signals` et sur `GET /signals/{key}` (clé de premier niveau, à côté de `signal_id`). Valeurs : `new | saved | ignored | contacted`.
- Dérivation, dans cet ordre, à partir de la ligne `signal_feedback` du compte : `contacted_at` non nul → `contacted` ; sinon `relevance = not_relevant` → `ignored` ; sinon `relevance = relevant` → `saved` ; sinon `new`. Un signal contacté puis jugé non pertinent reste `contacted`.
- Lecture groupée : nouvelle fonction `engagement.feedback.feedback_by_signal(connection, *, account_id) -> dict[signal_key, StoredFeedback]` (une requête par compte). `engagement.status.unified_status(feedback: StoredFeedback | None) -> str` porte la dérivation.
- Filtre `?status=` sur `GET /signals`, répétable (`?status=new&status=saved`), valeurs hors liste → 422 `invalid_status`. Sans filtre : tout sauf `ignored`. Le filtre s'applique AVANT la pagination, dans `feed_page` et `history_page`, via un paramètre `status_of: Callable[[str], str]` et `statuses: frozenset[str]`. Le filtre existant `status` de l'historique (statut de récence) est renommé en paramètre de requête `recency_status` ; l'ancien nom reste accepté un cycle avec le même sens (compatibilité du frontend actuel).
- `counts: {new, saved, ignored, contacted}` dans la réponse de liste, calculés sur l'ensemble filtré par zone, secteur, période et fraîcheur, avant le filtre de statut et avant la page. Bornés par le même balayage que la liste ; `counts_truncated: bool` reprend `scan_truncated`.
- Fix round 2 (F7/F8) — en `view=history`, `counts` n'est calculé que sur la **première page** (sans curseur), et `counts_available: bool` le dit. Une page atteinte par curseur rend les quatre clés à zéro avec `counts_available: false` : le client garde les compteurs de la première page. Repartir du curseur ne compterait que la queue de l'historique, donc un nombre différent — et faux — à chaque page ; recompter tout l'historique à chaque page relirait `HISTORY_SCAN_CAP` lignes pour rien. Le balayage s'arrête alors dès que la page est pleine et qu'un item admis a été vu derrière elle — `has_more`, `next_cursor` et `scan_truncated` gardent exactement leur sens. La vue `recent` compte toujours (`counts_available: true`).
- Le bloc `interaction` existant est inchangé.

## 3. `GET /companies`

- Agrégat par titulaire résolu (`company_key`) sur les signaux accessibles du compte : même portée que `view=history` sans filtre de date (`feedable_target_icps`, `is_unlocked`, balayage borné `HISTORY_SCAN_CAP`, `scan_truncated` exposé), regroupés par `company_identity_fingerprint` → `saas_company`. Un signal sans entreprise résolue n'apparaît pas.
- Ligne : `company_key`, `name` (identité officielle), `city` (commune du dernier signal, sinon `null`), `country`, `awards_count`, `total_amount` (liste `{currency, value}` par devise, décimal en chaîne), `last_award_at` (date effective du signal le plus récent : attribution, sinon notification, sinon publication), `contact_status` (`to_contact | contacted | replied`, défaut `to_contact`), `contacted_at`, `top_fit` (`strong | promising | weak | unknown`, meilleur `icp_match_band` parmi ses signaux).
- Filtres : `?contact_status=` répétable ; `?q=` sous-chaîne insensible à la casse et aux accents sur `name`. Tri : `last_award_at` desc, puis `company_key`.
- Pagination par curseur opaque comme l'historique : `{v: 1, d: last_award_at, k: company_key}`, `limit` ≤ 50, `page: {limit, cursor, next_cursor, has_more, scan_truncated}`.

## 4. Contact et notes par entreprise

- Migration `0034_company_engagement` (trois `create_table`, aucun `batch_alter_table`) : tables `company_contact` (`account_id`, `company_key`, `status` avec contrainte `IN ('to_contact','contacted','replied')`, `contacted_at` nullable, `updated_at` ; PK `(account_id, company_key)`), `company_note` (`account_id`, `company_key`, `body`, `updated_at` ; PK idem) et table `account_visit` (`account_id` PK → `account`, `last_seen_at`, `updated_at`) — une colonne sur `account` exigerait `batch_alter_table`, dont la recopie de table déclenche les `ON DELETE CASCADE` sous SQLite. `downgrade` symétrique. Les 23 tests de tête Alembic passent sur `0034`.
- `POST /companies/{key}/contact` body `{status}` ; `contacted_at` est posé à chaque passage en `contacted` depuis `to_contact` (nouveau cycle), conservé par `replied`, jamais remis à nul par `to_contact`. Réponse : `{company_key, contact_status, contacted_at, updated_at}`.
- `PUT /companies/{key}/note` body `{body}` ; corps vide supprime la note. Réponse : `{company_key, note, updated_at}`.
- `GET /companies/{key}` conserve `official_identity`, `related_signals`, `coverage` et ajoute `contact_status`, `contacted_at`, `note`, `signals` (items complets de `GET /signals` avec `status`, au plus `MAX_RELATED_SIGNALS`, tri date effective desc).
- `POST /signals/{key}/contacted` : après l'enregistrement, si le signal a une entreprise résolue et que son `company_contact` est absent ou `to_contact`, la passer à `contacted` avec `contacted_at = now`. Aucun effet inverse.
- Accès : 404 si l'entreprise n'a aucun signal accessible au compte (même règle que `GET /companies/{key}`) — et **404 aussi** quand le plan ne donne pas `feed_access` : jamais 403. Un 403 dirait « cette entreprise existe, mais pas pour vous », c'est-à-dire révélerait ce qui n'est pas visible ; les trois routes `/companies/{key}` répondent donc la même chose à une clé inconnue, à une clé d'un autre compte et à une clé qu'un plan ferme.
- La propagation depuis `POST /signals/{key}/contacted` n'a lieu qu'au **premier** enregistrement du contact (idempotence) : un second appel sur le même signal ne repose ni `contact_status`, ni `contacted_at`. C'est ce qui empêche une relance manuelle passée en `to_contact` d'être annulée par un clic répété sur le signal.

## 5. `GET /dashboard`

Lecture unique, `as_of` = date du serveur. `previous_seen = account_visit.last_seen_at` (ligne absente → `null`) lu AVANT la mise à jour ; la route écrit (insère ou met à jour) `account_visit.last_seen_at = now` en fin d'appel.

- `new_since_last_visit` : signaux accessibles de statut `new` dont `dates.publication` > `previous_seen` (tous si `previous_seen` est nul), sur la portée `view=recent`.
- `strong_matches` : parmi ceux-là, `icp_match_band == 'strong'`.
- `top3` : les 3 signaux de statut `new` (même portée) classés par bande (`strong` > `promising` > `weak` > autre), puis `icp_match_normalized_score` desc, puis date effective desc ; items complets.
- `to_follow_up` : entreprises `contact_status = contacted` avec `contacted_at` ≤ `now − 7 j`, tri `contacted_at` asc : `{company_key, name, last_signal (item complet), days_since_contact}`. Fix round 2 (F4) — la liste est **limitée aux 10 relances les plus anciennes**, le tri précédant la découpe, et la découpe précédant toute lecture par entreprise : le coût du bloc ne croît plus avec le nombre d'entreprises contactées. `to_follow_up_truncated: bool` vaut vrai dès que plus de dix relances étaient dues, ou que le balayage de la liste a été tronqué.
- `week` sur `[now − 7 j, now]` : `new` = signaux accessibles publiés dans la fenêtre, quel que soit leur statut ; `saved` = lignes `signal_feedback` `relevant` mises à jour dans la fenêtre ; `contacted` = `contacted_at` de signaux dans la fenêtre ; `replied` = `company_contact` `replied` mises à jour dans la fenêtre.
- Réponse : `{as_of, last_seen_at (previous_seen), new_since_last_visit, strong_matches, top3, to_follow_up, to_follow_up_truncated, week, scan_truncated}`.
- Fix round 2 (F1) — `new_since_last_visit`, `strong_matches` et `top3` se calculent sur l'ensemble sélectionné ENTIER (`FeedPage.matched`), jamais sur une page rendue : les lire sur `items` plafonnait chaque nombre à `MAXIMUM_PAGE_SIZE` et interdisait à un signal `strong` classé cinquante-et-unième par date d'atteindre `top3`.

## 6. Tests hors ligne (SQLite, `TestClient` avec `Origin`)

`tests/test_signal_status.py` (dérivation, cas contacté puis non pertinent, filtre multi-valeurs, défaut sans `ignored`, `counts`), `tests/test_companies_list.py` (agrégats, deux signaux dont un contacté, `q`, `contact_status`, curseur), `tests/test_company_engagement.py` (contact, note, propagation depuis `/signals/{key}/contacted`, non-propagation inverse, 404/403), `tests/test_dashboard.py` (compte sans `last_seen_at`, mise à jour de `last_seen_at`, `top3`, `to_follow_up` à 7 jours, `week`), `tests/test_company_engagement_migration.py` (0034 linéaire, tables et colonne, aller-retour). Suites existantes vertes hors échec connu `test_saas_company_architecture` (`httpx`, décision fondateur).

## 7. Hors périmètre

Frontend ; réparation des 90 tests vitest hérités ; toute agrégation nécessitant un nouveau calcul de fit ; suppression ou historisation des retours (le modèle `signal_feedback` reste à état courant).
