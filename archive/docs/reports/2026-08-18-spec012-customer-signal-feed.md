# SPEC-012 — Feed client, détail de signal et preuve

**Date** : 2026-08-18
**Portée** : la plus petite API client permettant `COMPTE → TARGET ICP → FEED → DÉTAIL → FAITS PUBLICS + BESOINS PLAUSIBLES + PREUVE`
**Statut** : livré, **non committé**, en attente de revue superviseur

---

## 1. Porte d'entrée — SPEC-011 est bien committée

```
$ git log -3 --oneline
1d894eb feat(saas): add account auth and ICP onboarding
30d431c feat(saas): add signal persistence foundation
05ecfd7 feat(signals): add multi-clock recency and France ingestion
```

**SPEC-011 : `1d894eb8b96a5a1f71896a01959b88b905a9e906`**, immédiatement après
`30d431c`. Elle n'est pas absorbée dans SPEC-012 : aucun de ses fichiers n'est
retouché ici. Les fichiers historiques hors périmètre (`*.docx`,
`*:Zone.Identifier`, SPEC-009C, `spec006-postmortem`) sont restés non suivis,
non modifiés, non indexés.

## 2. Points d'entrée

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/signals` | le feed du compte, les plus actionnables d'abord |
| GET | `/signals/{signal_key}` | le détail, avec de quoi vérifier |

Aucun `POST` : un signal est produit par Kivou, jamais rédigé par un client.

**`GET /signals/summary` n'a pas été ajouté.** §3 le conditionne à l'absence de
duplication ; or un résumé se calcule sur la page déjà rendue (`total_returned`,
`excluded`, `page.has_more` sont dans la réponse). L'ajouter maintenant créerait
un second chemin de lecture à garder cohérent, sans rien économiser au frontend.

Paramètres de `/signals` : `freshness`, `target_icp_id`, `primary_event`,
`country`, `winner`, `limit`, `offset`. Aucun filtre de score : ni bande, ni
score normalisé, ni composant, ni seuil.

## 3. Chemin de propriété

La requête **part du compte** :

```sql
FROM target_icp
  JOIN materialized_signal ON materialized_signal.target_icp_id = target_icp.target_icp_id
  JOIN contract_award      ON contract_award.award_key = materialized_signal.materialization_award_key
  JOIN source_event        ON source_event.event_key = contract_award.event_key
WHERE target_icp.account_id = :account_id
  AND target_icp.status = 'active'
```

`EXPLAIN QUERY PLAN` sur le schéma réel confirme la table pilote :

```
SEARCH target_icp USING INDEX ix_target_icp_status
SEARCH materialized_signal USING INDEX ix_materialized_signal_target_icp_id (target_icp_id=?)
SEARCH contract_award USING INDEX sqlite_autoindex_contract_award_1 (award_key=?)
SEARCH source_event USING INDEX sqlite_autoindex_source_event_1 (event_key=?)
USE TEMP B-TREE FOR ORDER BY
```

`materialized_signal` n'est **jamais** parcourue en entier : elle est atteinte
par l'index de `target_icp_id`, depuis les profils du compte. Un signal d'avant
les comptes n'a aucune ligne `target_icp` à joindre — il ne peut donc pas
apparaître, même si un futur appelant oubliait un `WHERE`.

**§25.7 — seul un profil `active` alimente le feed.** Un brouillon ne produit
pas de profil moteur valide ; le feed le vérifie quand même, pour qu'un profil
retombé en brouillon cesse de servir des signaux au moment même où le compte
redevient `icp_incomplete`.

Un `target_icp_id` d'un **autre** compte rend `404` avec le même corps qu'un
identifiant inexistant. Un brouillon **du compte lui-même** rend une page vide :
il existe, il ne sert simplement rien.

## 4. Modèles de réponse

Deux formes explicites (§16).

**`SignalFeedItem`** — `signal_id`, `target_icp_id`, `company`, `event`,
`contract`, `analysis` (besoins + adéquation, sans raisonnement long),
`source`. Aucune preuve.

**`SignalDetail`** — la carte, plus `analysis.contract_reading`, le
`reasoning` de chaque besoin, `evidence`, `opportunity_id`, `customer_ready`,
`read_at`, `language`.

La séparation faits / inférences est portée par la structure :

| Bloc | Nature |
|---|---|
| `company`, `contract`, `source` | ce que la source **publie** |
| `event.status`, `event.date` | un constat sur des dates publiées |
| `analysis.plausible_needs` | **hypothèses**, avec leur mise en garde |
| `analysis.fit` | pourquoi Kivou le montre à **ce** client |
| `analysis.contract_reading` | lecture automatique de l'avis |
| `evidence.public_facts` | ancrages des faits publiés |
| `evidence.analysis_inputs` | ancrages des faits **d'entrée** de l'analyse |

Un test vérifie que `contract` et `analysis` n'ont **aucune clé en commun**.

Aucun `account_id`, `user_id`, e-mail, jeton ou session n'apparaît dans une
réponse de signal — vérifié sur la réponse complète.

## 5. Ordre par défaut

```
pertinence de l'événement COURANT
→ date de cet événement, décroissante
→ signal_key
```

Le rang reprend l'ordre de dérivation déjà écrit dans `recency.policy`, rendu
triable — **aucun nouveau modèle de classement** n'est introduit :

| Rang | Statut |
|---|---|
| 0 | `recent_award` |
| 1 | `recently_notified_contract` |
| 2 | `recently_published_award` |
| 3 | `aging_award` |
| 4 | `stale_award` |
| 5 | `invalid_award_date` |
| 6 | `award_date_unknown` |

La date affichée est celle de **l'horloge qui a décidé du statut**
(`event.clock` la nomme). Une date absente passe après les dates connues du même
rang. Le tri n'utilise ni `materialized_at`, ni le score.

### Ce que chaque mode montre

| `freshness` | Statuts admis |
|---|---|
| `new` (défaut) | `recent_award`, `recently_notified_contract`, `recently_published_award` |
| `recent_or_aging` | les trois précédents + `aging_award` |
| `all` | tout, y compris `stale_award` |

**Décision à signaler.** `award_date_unknown` et `invalid_award_date` ne sont
pas nommés par la SPEC. Ils sont traités comme `stale_award` — hors du feed des
nouveautés — parce qu'ils ne portent **aucune date exploitable**. Le piège est
réel : `recency.claim.mvp_event_type` rattache ces deux statuts à
`RECENTLY_PUBLISHED_AWARD`, si bien qu'un feed réglé sur le *type d'événement*
ferait passer une parution ancienne pour une nouveauté. **Le feed se règle donc
sur le statut, jamais sur le type dérivé** ; `event.type` reste exposé, mais ne
décide de rien.

Dans le mode historique, la formulation reste sûre par construction : elle vient
de `recency.claim`, qui n'a aucune phrase de nouveauté pour ces états. Un test
vérifie qu'aucun marqueur de victoire n'apparaît sur un signal périmé.

## 6. Pagination

**Par décalage (`offset`), et c'est un choix assumé.**

L'ordre du feed dépend de la fraîcheur réévaluée au jour de la lecture, qui ne
peut pas être triée en SQL sans la figer — précisément ce que SPEC-010 interdit
d'exposer. Un curseur de clé porterait donc sur une colonne qui n'est pas celle
du tri, et sauterait des lignes.

Garanties tenues :

- **taille de page bornée** : défaut 20, maximum 50 **imposé par le serveur**.
  Une demande supérieure est **refusée en 422**, pas rognée en silence ;
- **ordre total et stable** : deux lectures identiques rendent la même page ;
- **aucun `SELECT` non borné** : la lecture des candidats est plafonnée à 500
  lignes, ordonnées par `materialized_at DESC` — si le plafond tronque, ce sont
  les lignes les plus anciennement matérialisées qui tombent ;
- **la troncature est annoncée** (`page.scan_truncated`), jamais silencieuse.

Le prix est connu : la page N relit les mêmes candidats. Le volume actuel le
permet (France : 45 opportunités client par semaine, SPEC-009E). Le jour où il
ne le permettra plus, il faudra **persister un rang de fraîcheur** — c'est-à-dire
changer le modèle, pas la pagination.

## 7. Fraîcheur courante

```
request_now()  →  now.date()  →  as_of  →  StoredSignal.current_recency(as_of)
```

La frontière HTTP est le seul endroit où le temps entre. `as_of` est ensuite
passé explicitement ; `feed_page` et `owned_signal` n'ont **aucune** valeur par
défaut pour lui. Un test lit le source de `feed/query.py` et `feed/view.py` et
refuse `date.today()`, `datetime.now(` et `utcnow(`.

`event.status`, `event.date`, `event.age_days`, `event.headline`,
`event.why_now` et l'ordre viennent **tous** de cette réévaluation.

**L'instantané `materialized_*` ne sort pas de l'API.** Un test vérifie qu'aucun
de ces noms n'apparaît dans une réponse, et un autre qu'une lecture tardive ne
réécrit ni le statut matérialisé, ni `materialized_as_of`, ni la révision.

La régression citée par la SPEC est testée telle quelle, sur un avis réel
attribué le 2026-07-17 :

| Lu le | Statut | Feed par défaut | Phrase |
|---|---|---|---|
| 2026-07-20 | `recent_award` | présent | « vient de remporter » |
| 2026-08-25 | `aging_award` | **absent** | « attribué récemment » |
| 2026-12-01 | `stale_award` | **absent** | « déjà attribué » |

## 8. `why_now`

Une phrase **temporelle**, tirée du seul statut, jamais d'un modèle de langage :

| Statut | FR |
|---|---|
| `recent_award` | Décision d'attribution récente. |
| `recently_notified_contract` | Notification récente du marché. *(corrigé au closeout §1)* |
| `recently_published_award` | Publication récente d'une attribution dont la date de décision est inconnue. |

Aucune n'affirme que l'entreprise achète.

## 9. Localisation

La langue vient de `account.locale` (`fr`, `en`) ; une locale hors catalogue
retombe sur `fr`. La phrase d'événement est produite par **`recency.claim`**, qui
reste l'unique autorité sur ce que Kivou a le droit d'affirmer d'une date — elle
n'est pas réécrite dans les routes. `feed/copy.py` ne couvre que ce que SPEC-012
ajoute : `why_now`, libellés de familles de besoin, libellés d'adéquation,
libellés de fait, mises en garde.

Trois tests prouvent qu'un même signal se lit en FR et en EN avec **exactement
les mêmes faits** : `contract`, `company`, `source`, `event.status` et
`event.date` sont identiques ; seuls les libellés changent. Les codes machine
(`category`, `status`, `type`) ne sont jamais traduits.

## 10. Preuve

Groupée par le fait qu'elle étaye, à partir de `anchors_kind` / `anchors_ref`
tels que la persistance les a écrits — **aucune correspondance inventée**.

```json
"evidence": {
  "public_facts": [
    {"fact": "award_date", "label": "Date d'attribution", "items": [
      {"source_system": "simap", "source_kind": "publication_field",
       "notice_id": "…", "procedure_id": "…", "url": "https://…",
       "path": "award_date", "excerpt": null, "retrieved_at": "…"}]}
  ],
  "analysis_inputs": {
    "note": "Ces sources prouvent les faits publiés utilisés par l'analyse. Elles ne démontrent pas que le besoin existera.",
    "groups": [{"plausible_need": "materials_or_components", "label": "…", "items": [...]}]
  }
}
```

Faits réellement ancrés sur les données de test : `winner`, `amount`,
`award_date`, `procedure_buyers`, `published_object`, `cpv`, `lot`.

- Les preuves rattachées à un besoin ne rejoignent **jamais** les faits publics ;
  un test vérifie que les deux ensembles de clés sont disjoints.
- Les ancrages `icp_match` restent internes : ils documentent une décision de
  moteur, pas un fait public.
- `path` est filtré : tout ce qui ressemble à un fichier local, une fixture ou un
  artefact de recherche est retiré. Un test balaie la réponse complète à la
  recherche de `/home/`, `tests/fixtures`, `.json`, `src/signals`, `scratchpad`.
- La carte de feed ne porte **aucune** preuve (§16).

## 11. Adéquation ICP

Dérivée de ce qui est **stocké** : `icp_matched_needs` et la géographie.

```json
"fit": {
  "label": "Correspond aux besoins que vous ciblez",
  "target_icp_id": "…", "target_icp_label": "Intrants",
  "reasons": ["Besoin plausible ciblé : Matériaux ou composants",
              "Besoin plausible ciblé : Matériel ou location",
              "Marché exécuté en CH"]
}
```

Ni poids, ni composant de score, ni matrice, ni politique BKP, ni score
normalisé. Onze motifs interdits sont testés un par un sur la réponse complète.

**Limite à signaler.** Le moteur de matching produit `positive_reasons` et
`limitations`, mais SPEC-010 **ne les persiste pas** — seuls `decision`, `band`,
`confidence`, `normalized_score` et `matched_needs` le sont. L'explication
d'adéquation est donc construite depuis les besoins retrouvés et le territoire.
Aucune migration n'a été créée pour les ajouter : §30 interdit de migrer pour
marquer un progrès, et la formulation actuelle est vraie et suffisante. Si le
superviseur veut une explication plus riche, elle demandera de persister ces deux
champs — décision de SPEC-013.

## 12. Besoins plausibles

Relus de la ligne matérialisée. **Aucune ré-exécution du Need Graph**, aucun
appel à un modèle de langage. Chaque entrée porte `category`, `label` traduit,
`statement`, `confidence`, `timing`, `timing_label`,
`targeted_by_your_profile`, et — en détail seulement — `reasoning`.

`rule_ids` et `externalisability` restent internes : le premier expose
`need-rules-v0.5`, que §4 interdit de publier.

Une liste vide reste **vide** : un signal sans besoin exploitable rend
`{"note": …, "items": []}`. Rien n'est fabriqué pour que la carte paraisse
complète.

## 13. Identité client exploitable

**Règle** : un signal n'entre dans le feed que si l'attributaire porte un **nom
affichable**. Ne le sont ni un nom vide, ni un nom purement numérique, ni un nom
qui n'est que l'identifiant recopié — le cas exact des notifications DECP 2022,
qui publient le SIRET du titulaire sans sa dénomination sociale (SPEC-009E).

Les signaux écartés sont **comptés et rendus** :
`excluded.without_display_name`. Rien n'est enrichi : aucun SIRENE, aucun
registre, aucun nom déduit d'un identifiant.

### Repli sur une représentation sœur

Un défaut réel est apparu pendant l'écriture des tests, et il valait la peine
d'être corrigé : quand une notification DECP arrive **après** un avis BOAMP sur
le même contrat, la nouvelle révision écrase `winner_name` avec le SIRET nu — et
le signal, déjà servi au client, **disparaissait du feed**.

Le feed relit donc, en une seule requête pour tous les signaux concernés, les
autres représentations de la même opportunité (`opportunity_representation` →
`contract_award.awardee_parties`), et reprend un nom **déjà publié**. La
provenance est conservée (`from_award_key`). Rien n'est inventé : le repli lit un
fait, il n'en produit pas. C'est ce qui satisfait §28.4 sans toucher à la
matérialisation.

**Décision à signaler.** Un signal sans nom affichable est retiré de **toutes**
les listes, y compris en mode historique — l'affichabilité est orthogonale à la
fraîcheur. Il reste atteignable par son identifiant, avec `company.name = null`
et `customer_ready: false` : l'accès est gouverné par la propriété (§2), pas par
la présentation, et le masquer derrière un `404` confondrait les deux.

## 14. Signaux non liés

Un signal dont le `target_icp_id` ne désigne aucune ligne `target_icp` reste
**PRÉ-SaaS / RECHERCHE**. Il n'apparaît ni dans `GET /signals` (quel que soit le
mode), ni dans `GET /signals/{key}` — la jointure de propriété ne peut pas le
produire. Rien ne le lie silencieusement, et un ICP dont le libellé ressemble au
profil de recherche ne le lie pas davantage. Un test vérifie aussi qu'il ne
décale **aucune** page du client.

## 15. Migration

**Aucune migration n'a été créée.** §30 le demande explicitement, et rien ne
l'exige :

- aucun champ persisté nouveau : le feed lit `materialized_signal`,
  `contract_award`, `source_event`, `evidence`, `opportunity_representation` et
  `target_icp` tels qu'ils existent ;
- aucun index nouveau : le plan d'accès réel montre que chaque jointure passe par
  un index existant. Le seul tri en mémoire porte sur `materialized_at`, borné
  par le plafond de lecture et par le nombre de signaux d'**un** compte.

Le premier index à envisager, le jour où un compte portera beaucoup de signaux,
serait `materialized_signal(target_icp_id, materialized_at DESC)` — il
supprimerait le `TEMP B-TREE`. Il n'est pas justifié aujourd'hui, et l'ajouter
« pour plus tard » serait exactement ce que §30 interdit.

## 16. Performance

- Une requête pour la page (jointure de propriété + fenêtre de dates + filtres),
  plus **au plus une** requête de repli d'identité pour l'ensemble des signaux
  sans nom.
- **Aucune preuve n'est relue pour une carte de feed** : un test branche un
  écouteur `before_cursor_execute` et vérifie qu'aucun `FROM evidence` n'est
  exécuté en listant sept signaux. Le N+1 de SPEC-010 est évité en séparant
  l'hydratation (`signal_from_row`) du chargement des preuves (`load_evidence`).
- Ni Redis, ni Elasticsearch, ni Kafka, ni Celery, ni cache : une base
  PostgreSQL.

La fenêtre SQL de présélection est une condition **nécessaire, jamais
suffisante** : une nouveauté exige qu'au moins une des trois dates brutes tombe
dans la fenêtre (30 jours en mode `new`, 60 en `recent_or_aging`, aucune en
`all`), mais y tomber ne suffit pas — le statut exact est décidé en Python.

## 17. Tests

**Total du dépôt : 2380 tests, 0 échec, 0 ignoré.** (Base SPEC-011 : 2267.)

| Fichier | Tests | Objet |
|---|---|---|
| `tests/test_feed_ownership.py` | 11 | §2, §18, §25 — propriété, isolation, états vides |
| `tests/test_feed_recency.py` | 12 | §5, §6, §26 — fraîcheur courante et ordre |
| `tests/test_feed_facts.py` | 38 | §8, §13, §14, §21, §27 — faits/inférences, preuve, langues |
| `tests/test_feed_identity.py` | 8 | §19, §20, §28 — identité client, unicité, opacité des sources |
| `tests/test_feed_pagination.py` | 14 | §17, §29, §31 — bornes, ordre, absence de N+1 |
| `tests/test_feed_event_copy.py` | 30 | closeout §1, §2, §3 — formulation, type client, filtre |
| **Total SPEC-012** | **113** | |

`tests/feed_helpers.py` porte les fabriques communes. **Toutes les données sont
réelles** : avis BOAMP français, avis SIMAP suisses, et le couple BOAMP × DECP
fortement rapproché de SPEC-009E. Aucune date n'est retouchée pour faire vieillir
un signal — les tests avancent l'horloge de **lecture**, comme la production.

### §25 — propriété

Anonyme → 401 sur les deux points d'entrée. Le compte B ne liste ni n'ouvre le
signal du compte A ; un signal étranger et un signal inexistant rendent le
**même corps**. Un signal pré-SaaS n'apparaît jamais et n'est pas ouvrable. Le
`target_icp_id` d'un autre compte comme filtre rend le même 404 qu'un
identifiant inexistant. Compte sans ICP, avec un ICP brouillon, ou avec un ICP
actif sans signal : trois pages vides ordinaires, jamais une erreur serveur. La
propriété est dérivée uniquement par `target_icp`.

### §26 — fraîcheur

Attribution récente présente par défaut ; la même ligne, lue plus de trente
jours après, ne revendique plus la victoire et quitte le feed ; une notification
récente emploie la formulation de notification et jamais celle d'une victoire ;
une parution récente sans date de décision emploie la formulation de
publication ; un signal périmé est exclu du feed des nouveautés ; l'instantané
matérialisé n'est ni réécrit ni exposé ; la date de lecture est explicite et
rendue (`read_at`).

### §27 — faits contre inférences

L'attributaire, l'acheteur, le montant avec sa devise, les dates et l'URL source
survivent inchangés. Le besoin reste explicitement plausible (`confidence` ne
peut valoir que `medium` ou `low` — la politique interdit `high`). Le résumé de
contrat est placé dans `analysis.contract_reading` avec sa mise en garde, et
n'apparaît pas dans `contract`. Six champs de certitude et onze rouages internes
sont testés un par un. La preuve d'un besoin ne prétend jamais le démontrer.

### §28 — identité

Entreprise nommée → éligible. Attributaire réduit à son identifiant → hors feed,
et compté. Aucun nom fabriqué depuis un SIRET. Le couple BOAMP × DECP
fortement rapproché reste **un** signal client, et l'ajout de la seconde
représentation ne dédouble pas la carte. Le client n'apprend aucune
particularité de portail : `cdl`, `sentinel`, `1970-01-01`, `2000-01-01`,
`eforms`, `bt-1451` sont absents de la réponse.

### §29 — pagination

Plafond serveur refusé en 422 ; taille par défaut bornée ; `limit=0` et
`offset=-1` refusés ; deux lectures identiques rendent la même page ; l'ordre
suit la date décroissante ; deux pages ne se recouvrent pas ; le parcours complet
rend chaque signal **exactement une fois** ; `has_more` dit la vérité ; un
décalage au-delà de la fin est une page vide ; les signaux non liés et ceux d'un
autre compte ne déplacent rien ; la troncature est annoncée.

## 18. Ce que les tests ont trouvé

Deux constats méritent d'être remontés.

1. **La politique de fraîcheur refuse une attribution postérieure à sa propre
   publication.** Mes premiers jeux de test posaient des dates d'attribution
   après la parution de l'avis : le moteur les a classées `invalid_award_date`,
   et il avait raison. Les tests ont été corrigés, pas le moteur.
2. **Une révision DECP tardive effaçait le nom d'un signal déjà servi** — décrit
   au §13. C'est le seul comportement produit que SPEC-012 a dû corriger, et la
   correction est entièrement en lecture.

## 19. Fichiers

**Nouveaux**

```
src/signals/feed/__init__.py
src/signals/feed/policy.py          (121 lignes)
src/signals/feed/copy.py            (163 lignes)
src/signals/feed/query.py           (404 lignes)
src/signals/feed/view.py            (321 lignes)
src/signals/api/routes_signals.py   (126 lignes)
tests/feed_helpers.py
tests/test_feed_ownership.py
tests/test_feed_recency.py
tests/test_feed_facts.py
tests/test_feed_identity.py
tests/test_feed_pagination.py
docs/reports/2026-08-18-spec012-customer-signal-feed.md
```

**Modifiés**

| Fichier | Changement |
|---|---|
| `src/signals/api/app.py` | +2 lignes : le routeur des signaux |
| `src/signals/api/errors.py` | +1 code stable : `signal_not_found` |
| `src/signals/persistence/repository.py` | hydratation scindée en `signal_from_row` / `load_evidence` (évite le N+1), `SIGNAL_SELECT` exposée pour composer la restriction de propriété, et cinq champs lisibles ajoutés : `StoredEvent.source_procedure_id`, `StoredEvent.procedure_buyers`, `StoredAward.lot_title`, `StoredAward.contract_reference`, `StoredAward.place_of_performance`, plus `StoredEvidence.source_procedure_id` et `.retrieved_at` |

Ces champs existaient déjà en base et n'étaient pas relus ; l'acheteur public et
le lieu d'exécution que §7 demande en dépendent. Aucun n'est nouveau au schéma.

**Aucune dépendance ajoutée. Aucune migration.**

## 20. Non-régression (§33)

`git status --porcelain` ne rend rien sur
`src/signals/{understanding,needs,matching,documents,connectors,recency,france,domain,accounts}`,
ni sur `persistence/{schema,opportunity,materialization,identity,database}.py`,
ni sur `persistence/migrations/`. Sémantique de compte, propriété TargetICP,
Argon2, sessions, CSRF, identité d'opportunité, distinction instantané/courant,
BOAMP, DECP, SIMAP, TED, Need Graph, Matching, Signal Score : inchangés.

`AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False` (`documents/mvp.py`) — inchangé.
Vérificateur commercial toujours hors circuit. Aucun nouveau banc commercial.

## 21. Closeout — sûreté de la formulation d'événement

### 21.1 `why_now` de la notification récente (§1)

**Le défaut.** La phrase disait « Notification récente du marché ; la date de
décision n'est pas publiée. » Or `award-recency-v0.3` rend les horloges
**indépendantes** : une attribution vieille de quatre-vingt-dix jours notifiée
hier ressort `recently_notified_contract` **avec** une date de décision connue.
La seconde moitié de la phrase était donc fausse — et fausse dans le cas
français le plus courant, celui que R2 §1 avait justement corrigé pour ne plus
perdre la notification.

**La correction.** La phrase ne dit plus que ce que le statut garantit :

| Langue | `why_now` |
|---|---|
| `fr` | `Notification récente du marché.` |
| `en` | `Recent contract notification.` |

Le complément est conservé, mais il **inspecte l'horloge d'attribution
elle-même** (`award_clock.status`), jamais le statut mis en avant. Il est rendu
dans `event.award_date_note`, à côté de `event.award_clock_status` :

| `award_clock.status` | FR | EN |
|---|---|---|
| `unknown` | La date de décision d'attribution n'est pas publiée par la source. | The award decision date is not published by the source. |
| `invalid` | La date de décision publiée par la source est incohérente. | The award decision date published by the source is inconsistent. |
| `recent` | La décision d'attribution est récente. | The award decision is recent. |
| `aging` | La décision d'attribution est déjà datée. | The award decision already dates back some time. |
| `stale` | La décision d'attribution est ancienne. | The award decision is old. |

**Point à valider par le superviseur** : §1 autorise ce complément, mais il
ajoute deux champs (`award_date_note`, `award_clock_status`) au bloc `event`,
alors que §4 demande de ne pas toucher à la structure de réponse. Les deux
champs existent uniquement pour porter l'explication que §1 permet ; s'ils ne
sont pas souhaités, la copie minimale suffit seule et les retirer est trivial.

Aucune autre formulation n'était concernée : `recently_published_award` n'est
atteint que lorsque l'horloge d'attribution est `unknown` — sa phrase
« dont la date de décision est inconnue » reste donc toujours vraie.

### 21.2 `event.type` côté client (§2)

**Le défaut.** `recency.claim.mvp_event_type` rattache `award_date_unknown` et
`invalid_award_date` à `RECENTLY_PUBLISHED_AWARD`. Rendu tel quel, il
étiquetterait « publication récente » un avis dont **aucune** date n'est
exploitable.

**Où la corriger.** Pas dans `recency.claim` : cette fonction alimente
`materialized_primary_event`, donc une colonne persistée et l'empreinte de
contenu. La corriger en amont réécrirait des instantanés d'audit et la
sémantique des bancs historiques. La correction est donc faite **à la frontière
client**, dans `feed/policy.customer_event_type`.

**Aucun type n'est inventé** : les trois valeurs rendues sont les statuts
eux-mêmes.

| Statut courant | `event.type` |
|---|---|
| `recent_award` | `recent_award` |
| `recently_notified_contract` | `recently_notified_contract` |
| `recently_published_award` | `recently_published_award` |
| `aging_award` | `null` |
| `stale_award` | `null` |
| `invalid_award_date` | `null` |
| `award_date_unknown` | `null` |

Un test parcourt les sept statuts de `CLAIM_TEMPLATES` et exige que chacun ait
une décision explicite ; un autre vérifie que le raccourci interne existe
toujours (`mvp_event_type("award_date_unknown") == "RECENTLY_PUBLISHED_AWARD"`)
et que le feed le neutralise.

### 21.3 Filtre `primary_event` (§3)

Il portait déjà sur le **statut courant**, jamais sur l'instantané. Il porte
désormais explicitement sur `customer_event_type(statut courant)`, et le
paramètre n'accepte que les trois valeurs d'événement client — une autre valeur
rend **422** plutôt qu'une page vide inexpliquée.

Un test analyse l'**arbre syntaxique** de `feed/query.py` et `feed/view.py` et
refuse tout accès à `materialized_primary_event` ou
`materialized_recency_status`. L'analyse porte sur l'AST et non sur le texte :
les commentaires ont le droit de nommer l'instantané pour expliquer pourquoi on
ne s'en sert pas.

Quatre cas testés : une publication récente courante répond au filtre ; le même
avis lu bien plus tard (`award_date_unknown`) n'y répond plus ; une date
d'attribution incohérente n'y répond pas ; et un signal **matérialisé comme
récent** cesse de répondre au filtre `recent_award` une fois périmé — avec, dans
le même test, la vérification que l'instantané en base n'a pas bougé.

### 21.4 Ce qui n'a pas changé (§4)

Requête de propriété, chemin `compte → TargetICP → signal`, règle du profil
`active`, structure des blocs `company`/`contract`/`analysis`/`evidence`,
groupement des preuves, repli d'identité client, réévaluation de la fraîcheur,
ordre, pagination, plafond de lecture, adaptateurs sources, Need Graph,
Matching, persistance, authentification, bancs historiques : **inchangés**.

`git status --porcelain` sur `src/signals/{understanding,needs,matching,documents,connectors,recency,france,domain,accounts}`
et sur toute la persistance ne rend que `persistence/repository.py`, modifié
avant le closeout (hydratation scindée + champs lisibles). `recency/claim.py`
n'est pas touché. **Aucune migration.**

Le closeout n'a modifié que `src/signals/feed/{copy,policy,view,query}.py`,
`src/signals/api/routes_signals.py`, et ajouté
`tests/test_feed_event_copy.py`.

## 22. Portes de qualité

| Porte | Résultat |
|---|---|
| `uv run pytest -q` | **2380 passed**, 0 échec, **0 ignoré** |
| `uv run ruff check .` | **All checks passed!** |
| `git diff --check` | propre |

Répartition SPEC-012 (**113 tests**) :

| Fichier | Tests |
|---|---|
| `tests/test_feed_facts.py` | 38 |
| `tests/test_feed_event_copy.py` | 30 |
| `tests/test_feed_pagination.py` | 14 |
| `tests/test_feed_recency.py` | 12 |
| `tests/test_feed_ownership.py` | 11 |
| `tests/test_feed_identity.py` | 8 |

Base SPEC-011 (`1d894eb`) : 2267.

### `git status --porcelain`

```
 M src/signals/api/app.py
 M src/signals/api/errors.py
 M src/signals/persistence/repository.py
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx:Zone.Identifier
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx:Zone.Identifier
?? docs/reports/2026-08-17-spec006-postmortem.md
?? docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md
?? docs/reports/2026-08-18-spec012-customer-signal-feed.md
?? src/signals/api/routes_signals.py
?? src/signals/feed/
?? src/signals/research/spec009c.py
?? src/signals/research/spec009c_run.py
?? tests/feed_helpers.py
?? tests/fixtures/documents/heldout3_gold.json:Zone.Identifier
?? tests/fixtures/documents/heldout3_gold.sha256.txt:Zone.Identifier
?? tests/fixtures/signal100/spec009c_blind.json
?? tests/test_feed_event_copy.py
?? tests/test_feed_facts.py
?? tests/test_feed_identity.py
?? tests/test_feed_ownership.py
?? tests/test_feed_pagination.py
?? tests/test_feed_recency.py
?? tests/test_spec009c_bench.py
```

### `git diff --stat`

```
 src/signals/api/app.py                |  2 +
 src/signals/api/errors.py             |  1 +
 src/signals/persistence/repository.py | 71 +++++++++++++++++++++++++++--------
 3 files changed, 58 insertions(+), 16 deletions(-)
```

### Liste exacte des fichiers du commit SPEC-012 envisagé

**Modifiés (3)**

```
src/signals/api/app.py
src/signals/api/errors.py
src/signals/persistence/repository.py
```

**Nouveaux (13)**

```
src/signals/api/routes_signals.py
src/signals/feed/__init__.py
src/signals/feed/copy.py
src/signals/feed/policy.py
src/signals/feed/query.py
src/signals/feed/view.py
tests/feed_helpers.py
tests/test_feed_event_copy.py
tests/test_feed_facts.py
tests/test_feed_identity.py
tests/test_feed_ownership.py
tests/test_feed_pagination.py
tests/test_feed_recency.py
docs/reports/2026-08-18-spec012-customer-signal-feed.md
```

**Explicitement exclus** — hors périmètre, ni modifiés ni indexés :
`Plan_directeur_*.docx`, `Roadmap_execution_*.docx`, tous les
`*:Zone.Identifier`, `docs/reports/2026-08-17-spec006-postmortem.md`,
`docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md`,
`src/signals/research/spec009c.py`, `src/signals/research/spec009c_run.py`,
`tests/fixtures/signal100/spec009c_blind.json`, `tests/test_spec009c_bench.py`.

## 23. Ce que SPEC-012 impose à SPEC-013

1. **Le paywall se greffe sur la page, pas sur la requête de propriété.** La
   jointure `target_icp → materialized_signal` garantit qu'aucun signal non lié
   ne sort ; un filtre d'abonnement s'ajoute **après**, sans la contourner.
2. **`freshness` décide déjà ce qui est « nouveau ».** Un quota gratuit ne doit
   pas redéfinir la nouveauté en secret : la fraîcheur est une propriété du
   signal, l'accès une propriété du compte.
3. **`event.type` client est nul hors des trois nouveautés**, et
   `customer_event_type` est le seul point où cette décision est prise. Ne pas
   la rejouer ailleurs, et surtout ne pas relayer `mvp_event_type`.
4. **La fraîcheur reste recalculée à `as_of`.** Rien de ce que SPEC-013 ajoute ne
   doit persister un statut client pour aller plus vite. Si la pagination par
   décalage devient trop coûteuse, la solution est un **rang de fraîcheur
   persisté et daté**, pas un instantané exposé.
5. **`customer_ready` existe déjà.** Un signal sans nom affichable n'est pas
   facturable ; la comptabilité d'usage doit s'appuyer sur le même critère.
6. **Aucun champ de certitude d'achat n'entre dans la réponse**, et les mises en
   garde de `plausible_needs` et `analysis_inputs` sont testées.
7. **`positive_reasons` / `limitations` du matching ne sont pas persistés** —
   première migration à envisager si SPEC-013 veut une explication d'adéquation
   plus riche (§11).
8. **Bloquant d'exposition publique, toujours ouvert** : limitation de débit sur
   `signup`, `login`, `password-reset/request`, `password-reset/confirm`
   (SPEC-011 §15.6). SPEC-012 n'ajoute **aucun** point d'entrée non authentifié.
9. **Interdits toujours en vigueur** : facturation, paywall, quota, entitlements,
   Stripe, frontend, retour d'expérience, alertes, recherche automatique
   d'entreprise, et toute acquisition.

---

## Verdict

**SPEC-012 READY TO COMMIT**

Un client authentifié obtient les opportunités de ses propres profils, les plus
actionnables d'abord, avec l'entreprise concernée, ce qui s'est passé, pourquoi
c'est pertinent **aujourd'hui**, les faits publics séparés des hypothèses, et la
source qui prouve les faits. Les signaux d'avant les comptes n'apparaissent
jamais, un attributaire réduit à un numéro n'est pas présenté comme une
entreprise, et aucune phrase n'affirme l'absence d'une date que la source
publie.

Non committé, dans l'attente de l'autorisation.
