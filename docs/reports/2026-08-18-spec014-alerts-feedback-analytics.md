# SPEC-014 — Alertes, retour client et analytique produit

**Date** : 2026-08-18
**Portée** : `NOUVEAU SIGNAL → CLIENT ÉLIGIBLE → ALERTE → OUVERTURE → JUGEMENT → CONTACT → ANALYTIQUE`
**Statut** : livré, **non committé**
**Verdict** : **ALERTS + FEEDBACK + ANALYTICS READY**

---

## 1. Porte d'entrée — SPEC-013 est committée

```
$ git log -4 --oneline
1965c8a feat(saas): add Stripe billing and paywall
3757678 feat(saas): add customer signal feed
1d894eb feat(saas): add account auth and ICP onboarding
30d431c feat(saas): add signal persistence foundation
```

**SPEC-013 : `1965c8ac48eff986b9b600b47bb6719c6cfae000`**, après `3757678`,
`1d894eb` et `30d431c`. Aucun travail de facturation non committé n'est absorbé
ici : l'arbre était propre à l'ouverture.

## 2. La doctrine qui gouverne tout le lot

```
RETOUR CLIENT  →  STOCKER  →  ANALYSER  →  R&D SUPERVISÉE PLUS TARD
```

et jamais « le client clique 👎 → le score se réécrit ». Un moteur qui apprend
sans surveillance de quelques dizaines d'avis apprend surtout le biais des
premiers clients, et le fait silencieusement.

Deux tests l'imposent : après un jugement et un contact, `materialized_signal`
est **identique ligne pour ligne**, et le détail du signal — `contract`,
`event`, `evidence`, `analysis`, `company`, `source` — ne bouge pas d'un
caractère. Le carnet « besoin résiduel post-attribution » reste au backlog ;
SPEC-014 fabrique seulement la matière première qui permettra de le rouvrir.

## 3. Migration `0004_alerts_feedback_analytics`

**Strictement additive** : quatre `create_table`, aucune table antérieure
nommée, aucun `alter_column`, aucun `drop_table` dans `upgrade()`.

| Table | Rôle | Garantie portée par le schéma |
|---|---|---|
| `signal_feedback` | l'état courant du jugement | `(account_id, signal_key)` clé primaire — un avis courant, pas un historique |
| `product_event` | l'analytique, **append-only** | aucune colonne de surveillance ; `occurred_at` distinct de l'écriture |
| `account_notification_preference` | à qui écrire | `account_id` clé primaire — un destinataire par compte |
| `signal_alert_delivery` | ce qui a été envoyé | `(account_id, signal_key)` clé primaire — alerté avec succès **au plus une fois** |

Aucune clé étrangère de `signal_feedback.signal_key` ou
`signal_alert_delivery.signal_key` vers `materialized_signal` : un avis et un
envoi doivent survivre à une rematérialisation, et la contrainte imposerait une
reconstruction destructive sous SQLite — même déviation reportée qu'en
SPEC-011 §9, pour la même raison.

## 4. L'API de retour

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/signals/{signal_key}/feedback` | l'état courant du jugement |
| PUT | `/signals/{signal_key}/feedback` | juger, ou changer d'avis |
| POST | `/signals/{signal_key}/contacted` | déclarer une démarche commerciale |

Authentifié ; les écritures passent la protection CSRF par origine.
`extra="forbid"` : un `account_id`, un `target_icp_id` ou tout champ inconnu
font échouer la requête en **422**, ils ne sont pas ignorés en silence.

### Vocabulaire (§5)

```
relevant                    →  aucune raison
not_relevant                →  une raison obligatoire

already_covered   done_internally   wrong_customer_type
too_late          wrong_need        other
```

Les deux contraintes disent la même chose : une raison sans refus n'a rien à
analyser, un refus sans raison n'apprend rien. Note facultative, **500
caractères** au plus, jamais envoyée à un modèle de langage.

### « Contacté » est une action (§6)

`contacted_at` est distinct de `relevance`. Un client peut juger un signal
excellent sans avoir encore décroché son téléphone ; confondre les deux
effacerait la seule mesure qui compte vraiment.

L'action est **idempotente** : le second appel ne déplace pas la date et
n'enregistre pas un second événement. La réponse porte `recorded: false` pour
le dire au client sans fausser le décompte. Aucune réponse, aucun
rendez-vous, aucune affaire gagnée n'est inventée — ces événements n'existent
pas.

### Ce que le client voyait (§32)

Chaque jugement fige `event_status_at_feedback`,
`event_age_days_at_feedback` et `signal_revision_at_feedback`. C'est ce qui
rend un `too_late` analysable : recalculé à la date du jour, l'âge donnerait
un autre nombre, et l'on ne saurait plus si le client trouvait tard un signal
de trois jours ou de trois mois. Un test avance l'horloge de six mois et
vérifie que l'âge stocké n'a pas bougé.

### Le bloc d'interaction (§8)

`GET /signals/{id}` porte désormais `interaction` — `relevance`, `reason`,
`note`, `contacted`, `contacted_at`, `updated_at` — dans **son propre bloc**.
L'avis d'un client n'est ni un fait publié ni une inférence du moteur ; le
mêler à `contract`, `event`, `evidence` ou `analysis` rendrait indistinguable
ce que la source publie et ce qu'un utilisateur pense. `null` quand rien n'a
été jugé.

## 5. Qui a le droit de juger (§30)

```
session → compte → TargetICP possédé → signal → DÉBLOQUÉ
```

Un aperçu verrouillé ne montre ni l'entreprise ni le marché : il n'y a rien à
juger. Accepter un avis dessus ferait du formulaire de retour un **oracle** —
« ce signal est-il pertinent ? » finirait par renseigner sur ce qu'il cache.

| Situation | Résultat |
|---|---|
| signal d'un autre compte | **404**, indiscernable d'un signal inexistant |
| signal non lié (pré-SaaS) | **404** |
| aperçu Discovery verrouillé | **403 `signal_not_accessible`** |
| déblocage Discovery | autorisé |
| signal payant débloqué | autorisé |

Le 403 est délibéré : le compte **possède** ce signal, il ne l'a pas payé. Un
404 confondrait « pas à vous » et « pas encore accessible ».

## 6. Analytique produit

### Elle est serveur, jamais cliente (§11)

Il n'existe **aucun** `POST /analytics/event`. Un point d'entrée où le
navigateur choisirait le nom et le contenu de l'événement produirait des
chiffres qu'un client peut fabriquer — donc une activation à laquelle on ne
pourrait plus croire. Les événements naissent d'actions serveur déjà
authentifiées. Un test vérifie qu'aucune route de ce genre n'existe.

### Vocabulaire fermé (§10)

```
signal_feed_viewed        signal_detail_viewed
signal_feedback_relevant  signal_feedback_not_relevant  signal_contacted
alert_queued              alert_sent                    alert_failed
checkout_started          subscription_activated        subscription_lost
```

Un type hors liste est **refusé à l'écriture**. Les trois derniers sont
déclarés mais **non émis** dans cette SPEC : SPEC-013 tient déjà l'état
d'abonnement, et le dupliquer créerait deux vérités sur le même fait. §33
l'autorise explicitement — Stripe et les tables de facturation restent la
source des faits de paiement, et aucune comptabilité de revenu n'entre dans
`product_event` (test sur les noms de colonnes).

### Ce qui n'est jamais stocké (§9)

Mots de passe, jetons, sessions, secrets, adresse IP, User-Agent, texte de
preuve, corps de requête, adresse e-mail. Le contrôle porte sur les **noms de
propriété** et s'exerce **à l'écriture** : une propriété nommée `ip_address`
lève, plutôt que d'être découverte six mois plus tard dans un export.

### Observation répétable ≠ action métier (§12)

| Geste | Effet |
|---|---|
| ouvrir deux fois un signal | **deux** consultations — la répétition est l'information |
| marquer deux fois « contacté » | **une** démarche commerciale |

Un test clique quatre fois sur « contacté » et vérifie qu'il n'y a qu'un
événement, et que l'étoile polaire compte un compte.

### Volume maîtrisé (§34)

Un appel de feed produit **une** consultation, jamais une par carte affichée.
Un appel de détail produit **une** consultation, avec `access_granted:
true/false` — c'est cette dernière qui mesure l'appétit derrière le mur payant.
Un signal d'un **autre compte** n'écrit rien : l'analytique ne doit pas devenir
un annuaire de ce qui existe ailleurs.

## 7. Définitions métier (§13)

### Activation

> Un compte est **activé produit** lorsqu'il enregistre au moins un
> `signal_feedback_relevant` **ou** un `signal_contacted`.

Une inscription n'est pas une activation. Quatre tests le fixent : s'inscrire
et consulter le feed n'active pas ; un jugement positif active ; un contact
active ; un jugement **négatif** n'active pas.

### Action commerciale

`signal_contacted`, et rien d'autre.

### Étoile polaire

> **Nombre de comptes DISTINCTS ayant au moins un `signal_contacted` sur les
> 30 derniers jours.**

Ni connexions, ni pages vues, ni inscriptions, ni e-mails envoyés : ces
chiffres montent tout seuls et ne disent rien. Un test enchaîne dix
consultations de feed et vérifie que l'étoile polaire reste à zéro ; un autre
vérifie qu'elle oublie un compte après trente jours.

### Le service de requête (§14)

`activated_accounts`, `accounts_with_commercial_action`, `north_star`,
`feedback_breakdown`, `negative_reason_breakdown`, `signals_contacted_count`,
`relevant_signal_count`, et un `snapshot` qui les rassemble. Pas de tableau de
bord, pas d'entrepôt, pas de SDK tiers — PostgreSQL suffit.

La répartition des raisons se lit dans les **événements**, pas dans l'état
courant : un client qui change d'avis ne doit pas effacer la raison qu'il avait
donnée. Testé.

## 8. Cadence des alertes (§15, §26)

| Plan | `alert_cadence` | Règle |
|---|---|---|
| Discovery | `none` | **aucun** envoi automatique |
| Essential | `weekly` | au moins 7 jours depuis le dernier digest **réussi** |
| Pro | `daily` | au moins 1 jour |
| Fondateur | `daily` | plan Pro, donc cadence Pro |
| Scale | `priority` | éligible **à chaque cycle** dès qu'il existe des signaux non envoyés |

L'échéance se calcule sur le dernier envoi **réussi** : un échec SMTP ne
consomme pas le tour du client, sinon une panne de deux jours lui ferait perdre
deux digests. Testé.

**Changement à signaler** : `SCALE.alert_cadence` passe de `"daily"` à
`"priority"`, et le type `AlertCadence` remplace `realtime` par `priority`.
§15 le demande explicitement, et interdit d'appeler « instantané » ce qu'aucun
cron ne tient. Les Produits et Prix Stripe ne sont **pas** touchés — c'est une
capacité Kivou, pas un objet de facturation.

Une cadence inconnue n'envoie rien : défaut fermé, comme partout ailleurs.

## 9. Éligibilité d'un signal (§16, §29)

```
CANDIDAT
→  AVANT L'ENVOI : propriété du compte · profil actif dans l'allocation du plan
   · identité affichable · NOUVEAUTÉ au sens de la politique de fraîcheur
   · débloqué par le droit COURANT · jamais déjà envoyé
→  envoi
```

Tout vient du feed de SPEC-012 : aucun second modèle de classement n'est
introduit. **Le droit est réévalué à l'instant de l'envoi**, pas à la mise en
file — un compte résilié hier ne reçoit pas la piste que son abonnement d'hier
avait rendue éligible. Testé.

Ne sont jamais alertés : signaux d'un autre compte, signaux non liés,
attributaires réduits à un identifiant, signaux périmés, aperçus verrouillés.
Cinq tests, un par cas.

## 10. Préférences de notification (§17, §18)

| Méthode | Chemin |
|---|---|
| GET | `/notification-preferences` |
| PATCH | `/notification-preferences` |

Défaut : e-mail **activé**, adresse reprise de l'utilisateur propriétaire — le
premier créé, sans ambiguïté. L'initialisation est **écrite**, pas seulement
rendue : la recalculer à chaque exécution du job ferait changer le destinataire
dans le dos du client dès qu'un second utilisateur apparaît. Une fois écrite,
elle fait autorité, et seul le client la change.

Le destinataire est **au niveau du compte** : aucun envoi dupliqué vers chaque
`auth_user`. Les notifications d'équipe sont hors périmètre.

L'adresse est validée par **le même chemin que l'authentification**
(`EmailStr` + `normalize_email`) — deux validateurs finiraient par diverger, et
l'un laisserait passer ce que l'autre refuse. Ni SMS, ni push, ni Slack.

## 11. Le digest (§20, §21, §22)

**Au plus 10 signaux par e-mail.** Au-delà, les suivants restent en file pour
le cycle suivant — testé sur 12 signaux : 10 puis 2, deux e-mails, douze lignes
de livraison.

Chaque ligne porte : nom de l'entreprise, phrase d'événement, `why_now`, titre
de marché tronqué, acheteur, **1 à 3** familles de besoin, et le lien profond.
Rien d'autre.

**La formulation vient de `recency.claim`, via la carte de feed déjà rendue.**
Écrire ici une seconde phrase d'événement recréerait exactement l'écart que
SPEC-009D a mesuré : un feed qui dit une chose, un e-mail qui en dit une autre,
et aucun test qui compare les deux.

Six tests balaient le corps : aucune preuve, aucune URL de source, aucun
vocabulaire moteur (`need-rules`, `icp-match`, `signal-score`, `rule_ids`,
`normalized_score`, `trade_domain`, `bkp-trade`), aucun pixel ni traqueur
(`<img`, `utm_`, `open.gif`, `click?`), et FR/EN vérifiés sur le sujet, le
corps et les libellés de besoin.

**Les liens profonds viennent de `KIVOU_PUBLIC_APP_URL`**, jamais du client. Si
l'URL n'est pas configurée, l'envoi **échoue en douceur** : les signaux sont
mis en file et partent quand l'URL existe. Un lien cassé est pire qu'un e-mail
non envoyé. La configuration exige une URL `https://` absolue, refusée au
démarrage sinon.

## 12. Envoi et reprises (§23, §27, §28)

`AlertDeliveryGateway` est un protocole ; la suite de tests utilise un double
déterministe et **ne touche jamais le réseau**. L'adaptateur réel parle **SMTP
authentifié** (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
`SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`, `SMTP_USE_TLS`), secrets d'environnement
uniquement.

**Instantly n'est pas utilisé** : il reste réservé à la prospection sortante.
Mêler une alerte client à une infrastructure de campagne mettrait la
délivrabilité du produit à la merci d'une réputation de prospection.

| Issue | État persisté | Suite |
|---|---|---|
| succès | `sent`, `provider_message_id` | jamais renvoyé |
| échec connu | `failed`, `last_error_code`, `attempt_count += 1` | **rejouable** |
| issue incertaine | `unknown_delivery_state` | **pas de renvoi à l'aveugle** |

Recevoir deux fois la même alerte coûte plus cher en confiance que la recevoir
une fois tard. Aucune trace d'exception, aucun identifiant de connexion,
aucune adresse n'entre en base — seulement un code court. Testé.

**`Message-ID` déterministe** (§28) : `<kivou-alert-{sha256(compte:lot)}@kivou.ch>`.
Le même lot produit toujours le même identifiant — ce qui aide les serveurs à
écarter un doublon et le support à retrouver un envoi — sans qu'aucune adresse
ni aucun secret n'y apparaisse. Testé.

## 13. Le job (§25)

```python
run_alert_cycle(engine, gateway, now=…, public_app_url=…)
```

et un point d'entrée `python -m signals.alerts --database-url … [--now …]
[--dry-run]`, destiné à `cron` ou à un minuteur `systemd`. **Ni Celery, ni
Redis, ni Kafka, ni agent permanent** — vérifié en analysant les **imports** du
module, pas son texte : un commentaire a le droit de nommer Celery pour
expliquer qu'on ne s'en sert pas.

`now` est explicite partout ; un test lit le source de `job`, `policy` et
`content` et refuse `date.today()`, `datetime.now(` et `utcnow(`. L'heure
système n'est lue qu'au point d'entrée CLI.

Le job est **sûr à relancer** : cinq exécutions consécutives produisent un seul
e-mail. L'envoi a lieu **hors transaction** — garder une transaction ouverte
pendant un appel réseau bloquerait la base le temps d'un timeout SMTP.

## 14. L'export d'apprentissage (§31)

`learning_export(connection, start=…, end=…)` rend des lignes déterministes :
signal, opportunité, compte, ICP, jugement, raison, contact, **statut et âge
d'événement au moment du jugement**, révision, horodatage.

**Fonction interne, aucune route ne l'expose** — testé sur trois chemins
plausibles. Aucun mot de passe, aucun jeton, aucune adresse : un test balaie la
sortie à la recherche d'un `@`. Aucun entraînement automatique : elle rend des
lignes qu'un humain lira, et le jour où une règle changera, ce sera parce que
quelqu'un l'aura décidé en les regardant.

## 15. Tests

**Total du dépôt : 2712 tests, 0 échec, 0 ignoré.** (Base SPEC-013 : 2602.)

| Fichier | Tests | Objet |
|---|---|---|
| `tests/test_alerts_cycle.py` | 42 | §15 à §29, §37 — cadences, éligibilité, contenu, reprises |
| `tests/test_engagement_feedback.py` | 35 | §4 à §8, §30 à §32, §35, §36 — vocabulaire, propriété, instantané |
| `tests/test_engagement_analytics.py` | 27 | §9 à §14, §33, §34, §38 — événements, activation, étoile polaire |
| `tests/test_engagement_secrets.py` | 6 | §39 — aucun secret d'e-mail dans le dépôt |
| **Total SPEC-014** | **110** | |

`tests/engagement_helpers.py` porte les fabriques et la fausse passerelle.
Aucun test n'envoie d'e-mail réel.

Les listes §35, §36, §37 et §38 sont couvertes intégralement — dix tests de
propriété, douze de retour, vingt d'alerte, onze d'analytique — plus les cas
limites trouvés en chemin.

## 16. Ce que les tests ont trouvé

Trois constats méritent d'être remontés.

1. **`"signal_feedback_not_relevant".endswith("_relevant")` est vrai.** Ma
   première version de `feedback_breakdown` classait donc les refus parmi les
   accords. Le défaut ne se voyait que lorsque les deux jugements coexistaient
   — les tests à un seul côté passaient. Corrigé par une correspondance sur le
   type complet.
2. **Trois lots d'un même avis SIMAP partagent leur identifiant de lot**, donc
   leur `award_key` : ils ne produisent qu'un signal. Un jeu de test qui les
   comptait pour trois gonflait un décompte sans rien créer. Le pool de
   fixtures énumère désormais les couples réellement distincts, complétés par
   trois lots BOAMP pour atteindre douze — de quoi éprouver le plafond de dix.
3. **Le balayage de secrets attrapait `smtp_password=os.environ.get(...)`.**
   C'est pourtant la forme correcte. Le motif est devenu sensible à la casse et
   vise la forme majuscule des fichiers `.env` et des `export` shell, en
   excluant explicitement les lectures d'environnement et les gabarits `${…}`.

## 17. Non-régression (§43)

`git status --porcelain` ne rend **rien** sur
`src/signals/{understanding,needs,matching,documents,connectors,recency,france,domain,accounts,feed}`,
ni sur `persistence/{schema,materialization,opportunity,repository}.py`. Moteur
de signaux, fraîcheur, preuve, BOAMP/DECP/SIMAP/TED, Need Graph, Matching,
Signal Score, authentification, propriété de compte, traduction TargetICP,
déblocages Discovery, aperçu verrouillé, bancs historiques : **inchangés**.

Quatre fichiers antérieurs sont modifiés, tous de façon additive :

| Fichier | Changement |
|---|---|
| `src/signals/api/routes_signals.py` | deux enregistrements analytiques et le bloc `interaction` ; le détail verrouillé et les faits sont inchangés |
| `src/signals/api/config.py` | huit réglages d'alerte, tous facultatifs |
| `src/signals/api/errors.py` | trois codes d'erreur stables |
| `src/signals/billing/catalogue.py` | `SCALE.alert_cadence` → `priority` (§15, ci-dessus §8) |

**Aucun objet Stripe n'a été touché** — ni TEST, ni LIVE, ni lecture, ni
écriture. Les portes d'exploitation de SPEC-013 restent ouvertes et sont
rappelées au §19.

## 18. Portes de qualité

| Porte | Résultat |
|---|---|
| `uv run pytest -q` | **2712 passed**, 0 échec, **0 ignoré** |
| `uv run ruff check .` | **All checks passed!** |
| `git diff --check` | propre |

**Aucune dépendance ajoutée.** `smtplib` et `email.message` sont dans la
bibliothèque standard ; la validation d'adresse réutilise `pydantic[email]`,
déjà présent depuis SPEC-011.

### `git status --porcelain`

```
 M src/signals/api/app.py
 M src/signals/api/config.py
 M src/signals/api/errors.py
 M src/signals/api/routes_signals.py
 M src/signals/billing/catalogue.py
 M src/signals/persistence/migrations/env.py
 M tests/test_accounts_migration_and_ownership.py
 M tests/test_billing_entitlements.py
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx:Zone.Identifier
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx:Zone.Identifier
?? docs/reports/2026-08-17-spec006-postmortem.md
?? docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md
?? docs/reports/2026-08-18-spec014-alerts-feedback-analytics.md
?? src/signals/alerts/
?? src/signals/api/routes_feedback.py
?? src/signals/api/routes_notifications.py
?? src/signals/engagement/
?? src/signals/persistence/migrations/versions/0004_alerts_feedback_analytics_alerts_feedback_analytics.py
?? src/signals/research/spec009c.py
?? src/signals/research/spec009c_run.py
?? tests/engagement_helpers.py
?? tests/fixtures/documents/heldout3_gold.json:Zone.Identifier
?? tests/fixtures/documents/heldout3_gold.sha256.txt:Zone.Identifier
?? tests/fixtures/signal100/spec009c_blind.json
?? tests/test_alerts_cycle.py
?? tests/test_engagement_analytics.py
?? tests/test_engagement_feedback.py
?? tests/test_engagement_secrets.py
?? tests/test_spec009c_bench.py
```

### `git diff --stat`

```
 src/signals/api/app.py                         |  6 +++
 src/signals/api/config.py                      | 51 ++++++++++++++++++++++++++
 src/signals/api/errors.py                      |  4 ++
 src/signals/api/routes_signals.py              | 51 +++++++++++++++++++++++++-
 src/signals/billing/catalogue.py               |  7 +++-
 src/signals/persistence/migrations/env.py      |  3 +-
 tests/test_accounts_migration_and_ownership.py |  9 ++++-
 tests/test_billing_entitlements.py             | 11 ++++--
 8 files changed, 132 insertions(+), 8 deletions(-)
```

### Fichiers du commit SPEC-014 envisagé

**Modifiés (8)**

```
src/signals/api/app.py
src/signals/api/config.py
src/signals/api/errors.py
src/signals/api/routes_signals.py
src/signals/billing/catalogue.py
src/signals/persistence/migrations/env.py
tests/test_accounts_migration_and_ownership.py
tests/test_billing_entitlements.py
```

**Nouveaux (19)**

```
src/signals/alerts/__init__.py
src/signals/alerts/__main__.py
src/signals/alerts/cli.py
src/signals/alerts/content.py
src/signals/alerts/gateway.py
src/signals/alerts/job.py
src/signals/alerts/policy.py
src/signals/api/routes_feedback.py
src/signals/api/routes_notifications.py
src/signals/engagement/__init__.py
src/signals/engagement/analytics.py
src/signals/engagement/feedback.py
src/signals/engagement/notifications.py
src/signals/engagement/schema.py
src/signals/persistence/migrations/versions/0004_alerts_feedback_analytics_alerts_feedback_analytics.py
tests/engagement_helpers.py
tests/test_alerts_cycle.py
tests/test_engagement_analytics.py
tests/test_engagement_feedback.py
tests/test_engagement_secrets.py
docs/reports/2026-08-18-spec014-alerts-feedback-analytics.md
```

**Explicitement exclus** — hors périmètre : `*.docx`, `*:Zone.Identifier`,
`docs/reports/2026-08-17-spec006-postmortem.md`,
`docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md`,
`src/signals/research/spec009c*.py`,
`tests/fixtures/signal100/spec009c_blind.json`, `tests/test_spec009c_bench.py`.

## 19. Portes d'exploitation — préservées (§40)

Aucune n'a été résolue par effet de bord ici, et aucune n'est un bloquant de
commit.

> **AVANT LE PREMIER CHECKOUT KIVOU EN MODE TEST :
> DÉSACTIVER OU ISOLER LE WEBHOOK TEST DE TURIYA**
> (`we_1TPGpwC34k5bO7Y37W1YR4bp` → `https://turiya-audit.ch/api/webhooks/stripe`).

Avant le lancement de la facturation en production :

1. configuration de portail client propre à Kivou (TEST et LIVE) ;
2. destination d'événements Stripe publique de Kivou ;
3. décision fiscale — Stripe Tax `active` en LIVE avec zéro immatriculation ;
4. limitation de débit sur les points d'entrée d'authentification et sur
   `/webhooks/stripe`.

**S'y ajoutent, propres à SPEC-014 :**

5. `KIVOU_PUBLIC_APP_URL` et la configuration SMTP — sans elles, aucune alerte
   ne part (et rien n'est perdu : les signaux restent en file) ;
6. le minuteur `cron` ou `systemd` appelant `python -m signals.alerts` ;
7. les enregistrements SPF, DKIM et DMARC du domaine expéditeur, sans lesquels
   un digest légitime finira en indésirable.

## 20. Ce que SPEC-014 impose à la suite

1. **Le retour ne réécrit jamais le moteur.** Toute exploitation des raisons de
   refus passe par une R&D supervisée, jamais par une boucle automatique.
2. **L'analytique reste serveur.** Une télémétrie de frontend, si elle arrive un
   jour, sera un chemin distinct, avec son propre vocabulaire et sa propre
   défiance — elle ne doit pas alimenter l'activation ni l'étoile polaire.
3. **L'activation et l'étoile polaire ont une définition unique**, dans
   `engagement/schema.py` et `engagement/analytics.py`. Ne pas les redéfinir
   ailleurs.
4. **Juger suppose d'avoir vu.** Toute nouvelle action client sur un signal doit
   passer par le même contrôle d'accès que le détail.
5. **Le droit d'alerte est réévalué à l'envoi**, jamais à la mise en file.
6. **Un signal est alerté au plus une fois par compte.** Les relances et
   campagnes de réengagement sont un autre sujet, avec leur propre table.
7. **`now` reste explicite** dans tout le code métier ; l'heure système n'entre
   qu'aux points d'entrée HTTP et CLI.
8. **Aucun pixel, aucun traqueur.** Ce qui compte se mesure dans Kivou.
9. **Interdits toujours en vigueur** : frontend, exports, recherche automatique
   d'entreprise, et toute acquisition — Apollo, Instantly, campagnes, contact
   prospect, boîte aux lettres, outbound. Les alertes client ne sont pas des
   e-mails d'acquisition.

---

## Verdict

**ALERTS + FEEDBACK + ANALYTICS READY**

La boucle opérationnelle est fermée : un nouveau signal éligible déclenche une
alerte selon la cadence du plan, le client ouvre, juge, contacte, et chaque
geste laisse une trace exploitable. L'activation et l'étoile polaire ont une
définition unique et testée. Le retour est stocké avec ce que le client voyait
au moment de juger — ce qui rend un « trop tard » analysable un an plus tard —
et ne modifie **rien** du moteur de signaux.

Aucun blocage. Aucune dépendance ajoutée, aucun objet Stripe touché, aucune
donnée d'acquisition approchée.

Non committé, conformément à §44.
