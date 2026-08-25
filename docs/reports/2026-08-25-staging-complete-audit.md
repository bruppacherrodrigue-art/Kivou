# Audit opérationnel complet du staging avant production

**Date de l'audit :** 2026-08-25 (10:03 → 10:35 UTC)
**Environnement :** `https://staging.kivou.eu` — hôte `kivou-staging-01` (179.237.100.62)
**SHA backend audité :** `030861dc72d4ccca2f36e3d33c964e569df3aa89` (`030861d`)
**Révision Alembic :** `0024_scheduled_plan_change`
**Issue de suivi :** [#80](https://github.com/bruppacherrodrigue-art/Kivou/issues/80)

## Verdict

> ## `NO-GO PRODUCTION`

| Ensemble | Verdict |
| --- | --- |
| Signal Engine | **FAIL** |
| Acquisition Engine | **FAIL** |
| SaaS client | **PASS** |
| Infrastructure staging | **FAIL** |

Le SaaS client est le seul ensemble prouvé de bout en bout. Deux des quatre
sources d'ingestion ne produisent plus rien automatiquement, la chaîne
d'acquisition n'a aucun point d'entrée exécutable, et quatre secrets de
production du staging sont écrits en clair dans journald.

## Nature de l'audit

Audit **runtime**. Aucune conclusion ne repose sur un fichier de configuration,
une lecture de code ou une CI verte. Chaque ligne du tableau ci-dessous
correspond à une commande réellement exécutée sur l'hôte déployé ou à une
requête réellement émise vers l'API de staging, une seule fois.

**Actions d'écriture effectuées, toutes sur des comptes QA contrôlés :**

- création de deux comptes QA (`audit-030861d@kivou-qa.ch`, `audit2-030861d@kivou-qa.ch`) ;
- un paiement **Stripe TEST** (`livemode=false`, carte de test) sur le second compte ;
- un changement de formule immédiat, un downgrade programmé puis son annulation ;
- un `SIGKILL` volontaire sur `kivou-api` pour prouver le redémarrage automatique ;
- une restauration de sauvegarde dans une base temporaire isolée, supprimée ensuite ;
- extinction des notifications des deux comptes QA créés, pour ne pas aggraver #79.

**Aucune** action de production, DNS, Stripe LIVE, e-mail client ou campagne.
Aucun secret n'apparaît dans ce rapport.

---

## 1. Signal Engine — `FAIL`

| Périmètre | Contrôle | Preuve observée | Résultat |
| --- | --- | --- | --- |
| Signal Engine | SIMAP — service + timer | `kivou-ingest-simap.timer` `enabled`/`active`, toutes les 2 h ; dernier passage 2026-08-25 10:06:02 → 10:06:09 (`ExecMainStatus=0`) | PASS |
| Signal Engine | SIMAP — volumes 24 h | 12 passages, 12 succès, durée moyenne 6,5 s, 1 177 lus / 1 236 persistés | PASS |
| Signal Engine | SIMAP — curseur | `ingestion_checkpoint`: `status=success`, `cursor={"window_end":"2026-08-25"}`, `last_completed_at=10:06:09` | PASS |
| Signal Engine | BOAMP — service + timer | `kivou-ingest-boamp.timer` `enabled`/`active`, toutes les 2 h ; dernier passage 08:15:13 → 08:22:05 (`ExecMainStatus=0`) | PASS |
| Signal Engine | BOAMP — volumes 24 h | 12 passages, 12 succès, durée moyenne 399 s, 6 351 lus / 14 824 persistés / 465 matérialisés | PASS |
| Signal Engine | BOAMP — curseur | `cursor={"window_end":"2026-08-25"}`, `last_completed_at=08:22:05` | PASS |
| Signal Engine | **DECP — passage borné automatique** | `Result=timeout`, `ExecMainStatus=15` (SIGTERM) ; journal : `start operation timed out. Terminating.` à 01:05:20 après `TimeoutStartSec=30min` | **FAIL** |
| Signal Engine | **DECP — lignes bloquées en `running`** | 10 lignes `ingestion_run` en `running`, de 2026-08-20 12:36 à 2026-08-25 00:35, la plus ancienne âgée de **4 j 21 h**, toutes à `fetched=0 persisted=0` | **FAIL** |
| Signal Engine | **DECP — spirale de fenêtres croissantes** | Le seul rattrapage réussi (manuel, 08-25 08:40 → 09:27) a duré **47 min**, soit **17 min de plus que la borne systemd de 30 min**. Le même travail relancé par le timer expirera encore. | **FAIL** |
| Signal Engine | DECP — progression du curseur | `cursor` passé de `2026-08-20` à `2026-08-25`, mais **uniquement** par 6 exécutions manuelles de l'opérateur le 2026-08-25 entre 08:38 et 08:57. Aucun passage automatique n'a abouti depuis le 2026-08-20 00:35. | **FAIL** |
| Signal Engine | **TED — HTTP 429** | 10 passages sur 10 en `status=rate_limited` ; dernier 08-25 02:30:44 : `fetched=2000 persisted=0 rate_limited=1 error=rate_limited`, message `recherche TED en échec (429)` | **FAIL** |
| Signal Engine | **TED — déclenchement automatique** | `kivou-ingest-ted.timer` : `UnitFileState=disabled`, `ActiveState=inactive`, aucun symlink dans `timers.target.wants/`. Désactivé le 2026-08-25 08:57:37 UTC (`sudo … systemctl disable --now kivou-ingest-ted.timer`). **TED ne s'exécutera plus, y compris après reboot.** | **FAIL** |
| Signal Engine | TED — point de reprise | `ingestion_checkpoint` TED : `status=failed`, `cursor=null`, `last_completed_at` vide. Le curseur n'a **jamais** avancé. | **FAIL** |
| Signal Engine | Aucun job hors systemd | 3 timers sur 4 pilotent l'ingestion ; TED n'a **plus aucun** déclencheur (ni timer, ni cron : `crontab -l` vide pour `root` et `kivou`, rien dans `/etc/cron.d`) | **FAIL** |
| Signal Engine | Normalisation + matérialisation réelles | `source_event` = 21 310 (boamp 2 191 · decp 18 598 · simap 509 · ted 8) ; `opportunity_representation` = 25 901 ; `contract_award` = 25 895 ; `materialized_signal` = 28 622 dont 28 118 matérialisés dans les 24 h | PASS |
| Signal Engine | Document intelligence | `evidence` = 1 168 672 lignes ; détail de signal : `evidence.public_facts[].source_system`, `source_kind`, `notice_id`, `url` par fait | PASS |
| Signal Engine | Signal récent visible côté client | `GET /signals` (compte QA) : `EIFFAGE METAL`, SIRET `33391638500250`, marché 365 830,76 € pour l'établissement de restauration de Notre-Dame de Paris, attribution 2026-08-07, publication 2026-08-25, `recency_status=recent_award`, `age_days=18` | PASS |
| Signal Engine | Fiche entreprise cohérente | `GET /companies/cmp_0U8zQ_…` → identité officielle `EIFFAGE METAL`, FR, `3-7 Place de l'Europe, 78140, Vélizy-Villacoublay`, identifiant SIRET, `identity_method=official_identifier`, signaux liés | PASS |
| Signal Engine | Provenance et source visibles | Détail : `source={"system":"boamp","country":"FR","notice_id":"26-82535","url":"https://www.boamp.fr/pages/avis/?q=idweb:26-82535"}` | PASS |
| Signal Engine | Aucun signal ou renseignement inventé | Chaque fait porte sa source ; `analysis.plausible_needs.note` : « Hypothèses commerciales déduites des faits publiés — jamais un besoin confirmé » ; l'identité entreprise vient d'un identifiant officiel | PASS |

**Conclusion — Signal Engine `FAIL`.** SIMAP et BOAMP sont pleinement
opérationnels. DECP n'aboutit plus par lui-même depuis le 2026-08-20 et laisse
10 exécutions ouvertes en base. TED n'a jamais réussi un seul passage et n'a
plus de déclencheur du tout. Deux des quatre sources obligatoires ne
fonctionnent pas.

---

## 2. Acquisition Engine — `FAIL`

| Périmètre | Contrôle | Preuve observée | Résultat |
| --- | --- | --- | --- |
| Acquisition Engine | Disponibilité et version d'Hermes | `kivou-acquisition-shadow-smoke` (10:26:37) : `hermes state=AVAILABLE version=0.20.4 tag=v2026.8.18 commit=e624e9fde561…` ; interpréteur `/opt/kivou/hermes-agent/e624e9f…/.venv/bin/python` (Python 3.12.3) présent | PASS |
| Acquisition Engine | Modèle réellement configuré | `model=anthropic/claude-sonnet-4.6` | PASS |
| Acquisition Engine | **Hermes comme superviseur** | `executable_tools=0` — Hermes ne dispose d'**aucun outil exécutable**. Il ne supervise rien, il émet un avis. | **FAIL** |
| Acquisition Engine | Lecture de la politique staging | `environment=STAGING policy=SHADOW read_only=true kill_switch=true deployment_sha=030861d… policy_control_revision=1` | PASS |
| Acquisition Engine | Policy Engine et kill switch | `acquisition_policy_snapshot` : `autonomy_mode=SHADOW`, `read_only=t`, `kill_switch=t`, `allowed_commands=[]`, `allowed_countries=[]`, `allowed_wedges=[]`, créé par `staging-operator` | PASS |
| Acquisition Engine | **Budgets et plafonds** | `daily_cost_cap=0.000000 CHF`, `daily_volume_cap=0` — aucune enveloppe n'est configurée ; `operations readiness` remonte `ALLOCATION_ENVELOPE_UNCONFIGURED` et `COST_COVERAGE_INCOMPLETE` | **FAIL** |
| Acquisition Engine | Connexion Apollo | `apollo auth=READY acting_profile=BOUND` ; clé présente dans `/etc/kivou/acquisition-shadow.env` | PASS |
| Acquisition Engine | Connexion Instantly | `instantly workspace=BOUND mailboxes_ready=3 mailboxes_total=3` (workspace `4c9291e0-…`) | PASS |
| Acquisition Engine | État réel des trois boîtes | 3/3 prêtes : `mailbox-staging-01/02/03` sur `teamkivou.com` | PASS |
| Acquisition Engine | Démarrage et exécution d'un cycle | `python -m signals.supervisor shadow` → `mode=SHADOW plan_id=plan-20260825-102655 **actions=0** estimated_cost=0 status=advisory`. Le plan ne contient aucune action. | **FAIL** |
| Acquisition Engine | **Supplier Discovery** | Aucun point d'entrée : `src/signals/supplier_discovery/` n'a ni `__main__.py` ni `cli.py`, aucune unité systemd, aucun `[project.scripts]`. Table `supplier_discovery_run` = **0 ligne**. | **FAIL** |
| Acquisition Engine | **Recherche contrôlée d'une entreprise et d'un décideur** | Aucun point d'entrée exécutable. `acquisition_supplier` = 0, `acquisition_contact` = 0. | **FAIL** |
| Acquisition Engine | **Company Research** | Aucun `__main__.py`/`cli.py` ; `company_research_run` = **0 ligne** | **FAIL** |
| Acquisition Engine | **Contact Discovery** | Aucun `__main__.py`/`cli.py` ; `contact_discovery_run` = **0 ligne** | **FAIL** |
| Acquisition Engine | **Personnalisation** | Aucun `__main__.py`/`cli.py` ; `acquisition_personalization_artifact` = **0 ligne** | **FAIL** |
| Acquisition Engine | **Compliance Filter** | Aucun `__main__.py`/`cli.py` ; `acquisition_compliance_assessment` = **0 ligne** | **FAIL** |
| Acquisition Engine | **Construction d'une campagne** | Aucun `__main__.py`/`cli.py` ; `acquisition_campaign` = 0, `acquisition_campaign_member` = 0 | **FAIL** |
| Acquisition Engine | **Réception des événements Instantly** | `POST https://staging.kivou.eu/webhooks/instantly` → **405 nginx**. La route existe dans l'application mais **n'est pas relayée** : le site n'expose que `^/(auth\|me\|target-icps\|signals\|companies\|billing\|notification-preferences\|health)` et `= /webhooks/stripe`. `acquisition_provider_event` = 0. | **FAIL** |
| Acquisition Engine | Persistance décisions / preuves / coûts / résultats | `policy_evaluation` = 0, `acquisition_decision_evaluation` = 0, `acquisition_event` = 0, `acquisition_provider_operation` = 0, `acquisition_conversion_event` = 0, `acquisition_dead_letter` = 0. **Aucune décision, preuve, ni coût n'a jamais été persisté.** | **FAIL** |
| Acquisition Engine | **Test bout en bout** | Impossible : aucun exécutable n'enchaîne les étapes. Le seul cycle exécutable (`supervisor shadow`) produit 0 action ; `mutation_delta campaigns=0 members=0 provider_operations=0 provider_events=0`. Après l'audit, les 16 tables d'acquisition restent à 0 ligne. | **FAIL** |
| Acquisition Engine | Verdict d'aptitude déclaré par l'application | `operations readiness` → `highest_safe_mode=SHADOW blockers=ALLOCATION_ENVELOPE_UNCONFIGURED, COST_COVERAGE_INCOMPLETE, HERMES_RUNTIME_UNAVAILABLE, HUMAN_REVIEW_TRUTH_UNAVAILABLE, PRODUCTION_MAILBOX_UNCONFIGURED, SUPERVISOR_LOOP_UNHEALTHY`<br>`operations health` → `status=NOT_READY reasons=HERMES_RUNTIME_UNCONFIGURED, SUPERVISOR_LOOP_UNOBSERVED` | **FAIL** |

**Conclusion — Acquisition Engine `FAIL`.** La connectivité aux fournisseurs est
réelle (Apollo authentifié, Instantly lié, 3 boîtes prêtes, Hermes disponible),
et le Policy Engine ainsi que le kill switch sont vérifiablement en place. Mais
la chaîne documentée `Supplier Discovery → Apollo → Company Research → Contact
Discovery → Personalization → Compliance → Instantly` **n'a aucun point d'entrée
exécutable** : ni CLI, ni unité systemd, ni script de projet. Aucune étape n'a
jamais produit une ligne en base. Kivou déclare lui-même l'ensemble `NOT_READY`
avec six bloqueurs. Un cycle contrôlé ne peut pas être exécuté.

> Une remarque de méthode : le smoke renvoie `result=PASS`. Il mesure la
> connectivité, pas la chaîne. Pris pour un feu vert, il masquerait exactement
> ce que cet audit constate.

---

## 3. SaaS client — `PASS`

Parcours exécuté en réel contre les APIs de staging, avec un compte QA créé pour
l'audit (`audit2-030861d@kivou-qa.ch`), puis rejoué en navigateur (Chromium) en
1440×900 et 390×844.

| Périmètre | Contrôle | Preuve observée | Résultat |
| --- | --- | --- | --- |
| SaaS | Landing publique FR | `/` `lang=fr` h1 « Les entreprises qui remportent des contrats publics… », 6 155 car. | PASS |
| SaaS | Landing publique EN | `/` avec `en-GB` → `lang=en` h1 « The companies winning public contracts… », 5 522 car. | PASS |
| SaaS | Pages légales et liens du footer | `/informations-legales` rendu FR (19 652 car.) et EN (16 476 car.) ; `/mentions-legales`, `/confidentialite`, `/cgu` redirigent en `#ancre` vers la page canonique | PASS |
| SaaS | Routes directes SPA | `/exemple-de-signal`, `/contact`, `/login`, `/signup`, `/forgot-password`, `/reset-password` rendues directement en 200 ; `/route-inexistante` → page NotFound | PASS |
| SaaS | Garde d'authentification | `/app/dashboard` non authentifié → redirection `/login` ; `GET /signals`, `/billing/status`, `/target-icps`, `/notification-preferences`, `POST /billing/checkout` → **401** `not_authenticated` | PASS |
| SaaS | Inscription | `POST /auth/signup` → **201**, session posée, `onboarding_status=account_created` | PASS |
| SaaS | Connexion / déconnexion | `POST /auth/logout` → 204 puis `GET /me` → 401 ; `POST /auth/login` → 200 puis `GET /me` → 200 | PASS |
| SaaS | Oubli de mot de passe — pas d'oracle temporel | `POST /auth/password-reset/request` : compte **connu** 202 en **25 ms**, compte **inconnu** 202 en **26 ms**, corps identique `{"status":"accepted"}` | PASS |
| SaaS | Limitation de débit | 2ᵉ appel à `/auth/password-reset/confirm` → **429 nginx**, log : `limiting requests, excess: 2.302 by zone "kivou_reset"` | PASS |
| SaaS | Réinitialisation — rejet d'un jeton invalide | Non exercé : la requête a été absorbée par la limitation de débit ci-dessus. Règle « une seule exécution par contrôle » respectée. | UNPROVEN |
| SaaS | Création et activation d'un ICP | `POST /target-icps` → 201, `status=active`, `matching_revision=1`, `missing_fields=[]` | PASS |
| SaaS | Feed contenant des signaux réels | `GET /signals` → 3 signaux Discovery réels ; `excluded={"without_display_name":4,"by_freshness":1}` ; `policy={feed:customer-feed-v0.1, recency:award-recency-v0.3, paywall:kivou-paywall-v0.1}` | PASS |
| SaaS | Détail d'un signal | `GET /signals/{clé}` → 200, entreprise, acheteur, montant, CPV, lieu, dates, analyse, preuves, `company_key` | PASS |
| SaaS | Déverrouillage (droits Discovery) | 3 signaux servis puis `discovery={"granted_signal_count":3,"remaining_slots":0,"limit":3}` — les 3 crédits sont consommés et bornés | PASS |
| SaaS | Fiche entreprise depuis un signal | Lien `/app/companies/{clé}` présent au détail ; page rendue h1 « EIFFAGE METAL » | PASS |
| SaaS | Feedback pertinent / non pertinent | `PUT /signals/{clé}/feedback` `{relevance:"relevant"}` → 200, `interaction.relevance="relevant"` persistée ; motif hors dictionnaire → 422 avec la liste des valeurs admises | PASS |
| SaaS | Action « contacté » | `POST /signals/{clé}/contacted` → 200, `contacted=true`, `contacted_at=2026-08-25T10:17:03Z` | PASS |
| SaaS | Préférences de notifications | `GET` puis `PATCH /notification-preferences` `{email_enabled:false}` → 200, relecture confirmée ; page `/app/notifications` affiche la cadence liée à l'offre | PASS |
| SaaS | Alertes | `kivou-alerts.timer` `enabled`/`active`, horaire ; passage de 09:45 : `signaux envoyés=5 … sent=1` ; 21 livraisons `sent` en base avec `provider_message_id` | PASS |
| SaaS | Droits Discovery | `max_active_icps=1, history_days=0, granted_signals=3, alert_cadence=none, export_level=none` | PASS |
| SaaS | Droits Essential | Après paiement TEST : `history_days=30, alert_cadence=weekly, filter_level=basic` | PASS |
| SaaS | Droits Pro | Après upgrade : `max_active_icps=3, history_days=365, territory_mode=multiple, alert_cadence=daily` ; feed passé de 3 à **9** signaux | PASS |
| SaaS | Droits Scale | Après upgrade : `max_active_icps=10, history_days=null, history_scope=all_available, alert_cadence=priority` ; ICP multi-territoires FR+CH alors accepté (refusé en 422 `territory_limit_exceeded` sous Discovery) | PASS |
| SaaS | Limite de profils exposée | `/billing/status` publie `target_icps_over_limit:[…]` ; l'écran `/app/icps` affiche « Profils actifs : 3 / 10 » | PASS |
| SaaS | Checkout Stripe TEST | `POST /billing/checkout` → session `cs_test_…`, `livemode=false`, `client_reference_id=acc_…`, `billing_address_collection=required`, `tax_id_collection.required=never` ; paiement réel effectué à la carte de test | PASS |
| SaaS | Réservation avant Stripe | Deuxième `POST /billing/checkout` pendant qu'une tentative est ouverte → **409** `checkout_in_progress` avec `expires_at` | PASS |
| SaaS | Webhook Stripe TEST | `checkout.session.completed` → `applied` en 0 s ; `invoice.paid` → `applied` ; `customer.subscription.created` → `ignored` ; abonnement `essential/active/eur` créé | PASS |
| SaaS | Webhook — signature | `POST /webhooks/stripe` sans signature → **400** `invalid_webhook_signature` | PASS |
| SaaS | Aucun événement LIVE | `stripe_webhook_event` : 174 lignes, **toutes** `livemode=false` ; `KIVOU_STRIPE_MODE=test`, clé `sk_test_…` | PASS |
| SaaS | Portail client | `POST /billing/portal` → 200, `https://billing.stripe.com/p/session?secret=test_…` ; sur un compte Discovery → **409** `no_billing_customer` | PASS |
| SaaS | Changement de formule immédiat | `POST /billing/plan {plan:"pro"}` → `{"effect":"immediate","effective_at":null}`, droits Pro actifs immédiatement | PASS |
| SaaS | Downgrade programmé | `POST /billing/plan {plan:"essential"}` → `{"effect":"scheduled","effective_at":"2026-09-25T10:20:10Z"}` ; `plan_code` **reste `pro`** — les droits payés sont conservés jusqu'au terme | PASS |
| SaaS | Statut local du changement programmé | `GET /billing/status` → `scheduled_plan_change:{plan_code:"essential", effective_at:"2026-09-25T10:20:10Z"}`, sans aucun identifiant Stripe dans la réponse | PASS |
| SaaS | Annulation du downgrade | `DELETE /billing/plan` → `{"cancelled":true}` ; `scheduled_plan_change` repasse à `null` | PASS |
| SaaS | Refus de changement sans abonnement | `POST /billing/plan` sur Discovery → **409** `plan_change_unavailable` ; `price_id` glissé dans le corps → **422** `extra_forbidden` | PASS |
| SaaS | Affichage desktop et mobile | `/app/dashboard`, `/app/signals`, `/app/icps`, `/app/billing`, `/app/notifications`, détail de signal et fiche entreprise rendus en 1440×900 **et** 390×844 | PASS |
| SaaS | Absence de débordement horizontal | `scrollWidth − clientWidth = 0` sur les 13 routes publiques (FR et EN) et les 7 écrans authentifiés, aux deux tailles | PASS |
| SaaS | Absence d'assets 404 | Aucune réponse ≥ 400 sur les ressources statiques ; seule occurrence : `401 /me`, la sonde de session d'un visiteur anonyme | PASS |
| SaaS | Absence d'erreurs JavaScript | Aucune `pageerror`, aucune exception ; 0 réponse 5xx sur 258 requêtes API tracées pendant l'audit | PASS |
| SaaS | En-têtes de sécurité | HSTS 1 an `includeSubDomains` ; CSP `default-src 'self'` avec `frame-ancestors 'none'` et `form-action 'self' checkout.stripe.com billing.stripe.com` ; `X-Frame-Options: DENY` ; `nosniff` ; `Referrer-Policy` ; `Permissions-Policy` | PASS |
| SaaS | Titre principal du détail de signal | Le `h1` vaut « Non disponible » lorsque l'avis source ne porte pas de titre de marché (cas BOAMP fréquent) alors que le corps de page est complet | Observation |

**Conclusion — SaaS client `PASS`.** Le parcours complet a été exécuté sans une
seule intervention technique entre les étapes : inscription, ICP, feed de vrais
signaux, déverrouillage, fiche entreprise, retour, contact, notifications,
paiement TEST, webhook, portail, upgrade immédiat, downgrade programmé et son
annulation. Un seul contrôle reste `UNPROVEN` (rejet d'un jeton de
réinitialisation invalide), pour une raison qui est elle-même un succès : la
limitation de débit a fait son travail.

---

## 4. E-mails transactionnels

| Périmètre | Contrôle | Preuve observée | Résultat |
| --- | --- | --- | --- |
| E-mails | Reset reçu par `contact@kivou.eu` | Preuve existante (#61) réutilisée ; aucun nouvel envoi effectué | PASS (preuve réutilisée) |
| E-mails | Alerte reçue par `contact@kivou.eu` | `signal_alert_delivery` : 5 livraisons `sent` le 2026-08-25 09:45:16 pour `acc_wmMzQ50…` (`contact@kivou.eu`), cadence `daily`, `attempt_count=1`, `provider_message_id` présent | PASS |
| E-mails | Lien reset vers `/reset-password` | Exécuté sur le code déployé : `reset_url("https://staging.kivou.eu","TOKEN") → https://staging.kivou.eu/reset-password?token=TOKEN` | PASS |
| E-mails | Liens de signaux vers `/app/signals/…` | `signal_url(…) → https://staging.kivou.eu/app/signals/38f4345fd7d…` | PASS |
| E-mails | `List-Unsubscribe` vers `/app/notifications` | `preferences_url(…) → https://staging.kivou.eu/app/notifications` ; `alerts/gateway.py:158` pose `List-Unsubscribe: <{preferences_url}>`. Pas de `List-Unsubscribe-Post` — choix documenté, la désinscription en un clic n'est pas promise. | PASS |
| E-mails | Racine publique correcte | `KIVOU_PUBLIC_APP_URL=https://staging.kivou.eu` — racine sans chemin, le piège `/app` est évité | PASS |
| E-mails | SPF | `kivou.eu TXT` → `v=spf1 include:spf.infomaniak.ch -all` (échec strict) | PASS |
| E-mails | DKIM | `20260819._domainkey.kivou.eu TXT` → `v=DKIM1; t=s; p=…` (RSA 2048), résolu publiquement | PASS |
| E-mails | DMARC | `_dmarc.kivou.eu TXT` → `v=DMARC1; p=reject;` | PASS |
| E-mails | DMARC — adresse de rapport | Aucun `rua=`/`ruf=` : la politique est en `reject` sans qu'aucun rapport d'échec ne soit collecté | Observation |
| E-mails | Absence de secret ou d'adresse dans les erreurs persistées | `signal_alert_delivery.last_error_code` ne contient que `smtp_recipient_refused` et `smtp_450` — aucun destinataire, aucune réponse SMTP brute, aucun identifiant | PASS |
| E-mails | Timer d'alertes | `kivou-alerts.timer` `enabled`/`active`, déclenchement horaire, dernier 10:00:40, prochain 11:03:42 | PASS |
| E-mails | **Budget de tentatives** | `smtp_recipient_refused` est levé avec `retryable=false`, or `attempt_count` atteint **79** sur 49 livraisons, et `suppression_reason_code` est **NULL sur la totalité** des lignes. Le budget de tentatives n'est donc jamais terminalisé. | **FAIL** |
| E-mails | **Comportement des destinataires invalides** | Trois comptes `@kivou-qa.ch` produisent `failed=3` à **chaque** cycle horaire, y compris à 10:00:42 avec `signaux envoyés=0`. De nouvelles livraisons sont créées à chaque cycle pour un domaine qui refuse les destinataires. | **FAIL** (#79) |
| E-mails | Bruit documenté dans #79 | `kivou-alerts.service` sort en code 1 à chaque passage où `failed>0` ; unité en `failed` au moment de l'audit. Le code de sortie ne distingue pas « des envois ont échoué » de « le job n'a pas pu s'exécuter ». | **FAIL** (#79) |
| E-mails | Destinataire de preuve | `no-reply@kivou.eu` n'a été utilisé comme destinataire d'aucune preuve | PASS |

> **Réponse à la question ouverte de #79.** Les `attempt_count` élevés ne sont pas
> des relances de la même livraison : ce sont **de nouvelles livraisons créées à
> chaque cycle** pour de nouveaux signaux, sur un compte dont l'adresse est
> morte. `suppression_reason_code` étant NULL partout, aucun mécanisme de
> suppression ne se déclenche jamais.

---

## 5. Infrastructure staging — `FAIL`

| Périmètre | Contrôle | Preuve observée | Résultat |
| --- | --- | --- | --- |
| Infrastructure | SHA réellement exécuté | `git -C /srv/kivou/app rev-parse HEAD` → `030861dc72d4ccca2f36e3d33c964e569df3aa89`, message `feat(billing): switch plans with a server-side subscription schedule (#58)` | PASS |
| Infrastructure | Propreté du checkout | `git status --porcelain` → **0 ligne** | PASS |
| Infrastructure | Provenance du frontend servi | `/srv/kivou/frontend → releases/frontend-20260824T113509Z-003e917`, soit **7 commits derrière** le backend. `git diff --name-only 003e917 030861d -- frontend/` → **0 fichier** : aucun écart fonctionnel, mais l'étiquette de version du frontend ne désigne pas le SHA déployé. | Observation |
| Infrastructure | Révision Alembic | `SELECT version_num FROM alembic_version` → `0024_scheduled_plan_change` | PASS |
| Infrastructure | PostgreSQL 16 | `PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)`, `postgresql@16-main.service` actif, écoute sur `127.0.0.1:5432` uniquement | PASS |
| Infrastructure | nginx et certificat TLS | nginx 1.24.0, `nginx -t` réussi, actif et activé au boot ; certificat Let's Encrypt `CN=staging.kivou.eu`, valide jusqu'au 2026-11-17 (83 j), `certbot.timer` actif ; TLS 1.2/1.3 | PASS |
| Infrastructure | API et nombre de workers | `kivou-api.service` actif ; 1 parent + **2 workers** uvicorn (PID 190826 → 190828, 190829) sur `127.0.0.1:8000` | PASS |
| Infrastructure | Frontend réellement servi | `index.html` + `/assets/` + `/brand/` servis par nginx en `try_files … =404` ; aucune ressource en erreur sur 20 chargements de page | PASS |
| Infrastructure | Services et timers systemd | 5 timers Kivou `enabled`/`active` (simap, boamp, decp, alerts, backup) ; **`kivou-ingest-ted.timer` `disabled`/`inactive`** | **FAIL** |
| Infrastructure | Redémarrage automatique après incident | `systemctl kill kivou-api` → PID 181788 → **190826**, `NRestarts 0 → 1`, unité `active running` en < 12 s, `GET /me` → 401 à travers nginx. `Restart=on-failure`, `RestartUSec=5s`. | PASS |
| Infrastructure | Redémarrage après reboot | `kivou-api`, `nginx`, `postgresql` et 5 timers `enabled` ; **`kivou-ingest-ted.timer` `disabled` : TED ne repartira pas non plus après un reboot** | **FAIL** |
| Infrastructure | Sauvegarde récente | `kivou-20260825T083625Z.dump`, 47,9 Mo, `Result=success`, `ExecMainStatus=0`, rétention 14 j appliquée ; `kivou-backup.timer` actif | PASS |
| Infrastructure | Permissions des sauvegardes | `/srv/kivou/backups` en `700 kivou:kivou`, dumps en `600` — `postgres` lui-même n'y accède pas (restauration faite par tube). Le défaut « mode 664 » constaté auparavant est corrigé. | PASS |
| Infrastructure | Lisibilité par `pg_restore --list` | 371 entrées TOC, format CUSTOM, compression gzip, `Dumped from database version: 16.15`, 49 entrées `TABLE DATA` | PASS |
| Infrastructure | Restauration en base temporaire isolée | `CREATE DATABASE kivou_audit_restore_20260825` → `pg_restore` par tube → **49 tables**, `evidence` 971 466 lignes, `materialized_signal` 19 935, `account` 20. Base supprimée ensuite ; `kivou_staging` inchangée (`alembic_version` toujours `0024`). | PASS |
| Infrastructure | Fraîcheur du contenu sauvegardé | La sauvegarde la plus récente porte `alembic_version = 0023_transactional_email_runtime` : elle est prise **avant** la migration du déploiement. Le point de restauration le plus récent est donc en retard d'une migration. | Observation |
| Infrastructure | Espace disque | `/dev/sda1` 58 G, 5,9 G utilisés, **52 G libres (11 %)** ; base 628 Mo ; journaux 64,6 Mo | PASS |
| Infrastructure | Mémoire | 3,8 Gi total, 830 Mi utilisés, 3,0 Gi disponibles ; **aucun swap configuré** | PASS |
| Infrastructure | CPU | 2 vCPU AMD EPYC-Genoa, charge `0,19 0,23 0,31` | PASS |
| Infrastructure | Permissions des fichiers sensibles | `/etc/kivou/staging.env` en `600 root:kivou` ; `acquisition-shadow.env` en `600` ; `/srv/kivou/validation` en `700` ; aucun `.env` dans `/srv/kivou/app` | PASS |
| Infrastructure | Ports exposés | Publics : **22, 80, 443** uniquement. `8000` (API) et `5432` (PostgreSQL) liés à `127.0.0.1`. | PASS |
| Infrastructure | Rotation des journaux | nginx : `daily`, `rotate 14`, `compress` ; journald **persistant** (`/var/log/journal`), 64,6 Mo | PASS |
| Infrastructure | Plafond de taille du journal | Aucun `SystemMaxUse` déclaré dans `journald.conf` : la rétention repose sur le défaut (10 % du disque) | Observation |
| Infrastructure | Journalisation applicative HTTP | 258 lignes d'accès depuis 08:37 avec IP réelle et statut ; répartition 180×200, 7×201, 52×401, 6×422, 4×409, 4×404, 2×400 — **0 réponse 5xx** | PASS |
| Infrastructure | **Journalisation applicative des envois** | Le job d'alertes n'émet qu'**une ligne agrégée** : `comptes examinés=20 · signaux envoyés=5 · failed=3, …`. Ni le compte concerné, ni le code d'erreur, ni le signal ne sont journalisés. Un échec d'envoi reste indiscernable sans requête en base. | **FAIL** (#78) |
| Infrastructure | Visibilité des échecs #78 / #79 | Les unités en échec sont visibles (`kivou-alerts`, `kivou-ingest-decp`, `kivou-ingest-ted` en `failed`), mais leur **cause** ne l'est pas pour #78 | Partiel |
| Infrastructure | Route webhook Instantly non relayée | `POST /webhooks/instantly` → 405 nginx (repli statique). La route applicative existe mais n'est pas exposée. | **FAIL** |
| Infrastructure | Route d'attribution non relayée | `GET /a/{token}` → **200 avec le HTML de la SPA** au lieu de la redirection 303 de `routes_attribution.py`. Le cookie d'attribution n'est jamais posé ; tout lien d'attribution émis serait silencieusement inopérant. | **FAIL** |
| Infrastructure | **Secrets dans les journaux** | journald contient en **clair** : le mot de passe du rôle PostgreSQL `kivou_app` sur **43 lignes** (2026-08-19 → 2026-08-25 08:57), le mot de passe SMTP de `no-reply@kivou.eu` sur **11 lignes**, la clé secrète Stripe TEST sur **6 lignes**, le secret de signature du webhook Stripe sur **5 lignes**. Toutes émises par la journalisation `sudo` de commandes du type `sudo env KIVOU_DATABASE_URL=… ` / `sudo env SMTP_PASSWORD=… `. Le journal est lisible par le groupe `adm`, dont l'utilisateur `ubuntu` est membre. | **FAIL** |
| Infrastructure | Absence de clé LIVE | **0 occurrence** de `sk_live_` dans l'ensemble du journal ; `stripe_webhook_event` 174/174 en `livemode=false` | PASS |

---

## Configuration générale (sans secrets)

| Variable | Valeur |
| --- | --- |
| `KIVOU_PUBLIC_APP_URL` | `https://staging.kivou.eu` |
| `KIVOU_ALLOWED_ORIGIN` | `https://staging.kivou.eu` |
| `KIVOU_COOKIE_SECURE` | `1` |
| `KIVOU_STRIPE_MODE` | `test` |
| `STRIPE_SECRET_KEY` | `sk_test_…` (TEST) |
| `STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL` | `…/checkout/success` · `…/checkout/cancel` |
| `STRIPE_PORTAL_RETURN_URL` | `…/app/billing` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_TLS_MODE` | `mail.infomaniak.com` · `587` · `starttls` |
| `SMTP_FROM_EMAIL` / `SMTP_FROM_NAME` | `no-reply@kivou.eu` · `Kivou` |
| `KIVOU_ACQUISITION_ENVIRONMENT` | `STAGING` |
| `KIVOU_HERMES_PYTHON` | `/opt/kivou/hermes-agent/e624e9f…/.venv/bin/python` |

## Services et timers

| Unité | Activée | État | Cadence |
| --- | --- | --- | --- |
| `kivou-api.service` | oui | active (running), 2 workers | permanent, `Restart=on-failure` |
| `kivou-ingest-simap.timer` | oui | active | 2 h |
| `kivou-ingest-boamp.timer` | oui | active | 2 h |
| `kivou-ingest-decp.timer` | oui | active — **service en `failed` (timeout)** | 12 h |
| `kivou-ingest-ted.timer` | **non** | **inactive (dead)** — service en `failed` | — |
| `kivou-alerts.timer` | oui | active — **service en `failed` (code 1)** | 1 h |
| `kivou-backup.timer` | oui | active, dernier succès 08:36:30 | quotidien 03:2x |
| `kivou-acquisition-shadow-smoke.service` | static | manuel uniquement, `result=PASS` à 10:26:37 | aucun timer |

## Volumes réels

| Table | Lignes |
| --- | --- |
| `evidence` | 1 168 672 |
| `materialized_signal` | 28 622 (28 118 dans les 24 h) |
| `opportunity_representation` | 25 901 |
| `contract_award` | 25 895 |
| `source_event` | 21 310 — boamp 2 191 · decp 18 598 · simap 509 · **ted 8** |
| `ingestion_run` | 184 |
| `stripe_webhook_event` | 174 (100 % `livemode=false`) |
| `signal_alert_delivery` | 79 — 21 `sent`, 58 `failed` |
| `account` / `auth_user` | 22 / 22 (dont 2 comptes QA créés par l'audit) |
| `target_icp` | 18 |
| `billing_subscription` | 7 |
| `saas_company` | 1 |
| **16 tables `acquisition_*` / `*_run`** | **0** |

## Tests E2E exécutés

1. **Parcours SaaS complet, compte neuf** — inscription → session → déconnexion → connexion → droits Discovery → ICP → feed → détail → déverrouillage → fiche entreprise → retour → contacté → préférences. Aucune intervention technique.
2. **Conversion payante Stripe TEST** — checkout `cs_test_…` → paiement carte de test → webhook `applied` → abonnement `essential/active` → droits Essential.
3. **Cycle de vie de la formule (#58)** — upgrade `essential → pro` immédiat, upgrade `pro → scale` immédiat, downgrade `pro → essential` programmé à la fin de période, annulation par `DELETE /billing/plan`.
4. **Rendu navigateur** — 13 routes publiques × FR/EN × desktop/mobile, puis 7 écrans authentifiés × desktop/mobile.
5. **Résilience** — `SIGKILL` sur l'API, retour en service en moins de 12 s.
6. **Sauvegarde** — `pg_restore --list` puis restauration complète en base temporaire isolée, puis suppression.
7. **Cycle acquisition contrôlé** — smoke systemd, `supervisor health`, `supervisor shadow`, `operations readiness`, `operations health`. Aucune mutation produite.

## Issues ouvertes par cet audit

| Issue | Gravité | Objet |
| --- | --- | --- |
| [#81](https://github.com/bruppacherrodrigue-art/Kivou/issues/81) | **Critical** | Quatre secrets du staging sont écrits en clair dans journald |
| [#82](https://github.com/bruppacherrodrigue-art/Kivou/issues/82) | **High** | TED n'a aucun déclencheur et n'a jamais réussi un passage (429, curseur `null`) |
| [#83](https://github.com/bruppacherrodrigue-art/Kivou/issues/83) | **High** | L'Acquisition Engine n'a aucun point d'entrée exécutable |
| [#84](https://github.com/bruppacherrodrigue-art/Kivou/issues/84) | **Medium** | nginx ne relaie pas `/webhooks/instantly` ni `/a/{token}` |

## Problèmes connus rattachés

- [#77](https://github.com/bruppacherrodrigue-art/Kivou/issues/77) — Ingestion DECP/TED en timeout. **Confirmé et aggravé** : DECP laisse 10 exécutions ouvertes en base ; le rattrapage manuel a demandé 47 min contre 30 min de borne systemd.
- [#78](https://github.com/bruppacherrodrigue-art/Kivou/issues/78) — Journalisation applicative. **Confirmé pour le chemin e-mail.** À nuancer : la journalisation HTTP existe (258 lignes d'accès tracées) ; c'est le résultat par livraison qui manque.
- [#79](https://github.com/bruppacherrodrigue-art/Kivou/issues/79) — Bruit des destinataires SMTP invalides. **Confirmé**, avec la réponse à sa question ouverte : ce sont de nouvelles livraisons à chaque cycle, et `suppression_reason_code` est NULL partout.

Les trois tickets ont reçu un commentaire portant les preuves runtime correspondantes.

## Risques avant production

| # | Risque | Gravité |
| --- | --- | --- |
| R1 | Quatre secrets du staging (PostgreSQL, SMTP, Stripe TEST, signature webhook) sont lisibles en clair par tout compte du groupe `adm`. La même méthode d'exploitation reproduirait la fuite en production avec des secrets LIVE. | **Critical** |
| R2 | TED n'a aucun déclencheur et n'a jamais réussi un passage : une source obligatoire est absente du produit, y compris après reboot. | **High** |
| R3 | DECP ne converge pas seul ; sans intervention manuelle quotidienne le feed français dérive, et 10 exécutions restent ouvertes en base. | **High** |
| R4 | L'Acquisition Engine n'a aucun point d'entrée exécutable : la promesse commerciale de la chaîne d'acquisition n'est adossée à aucun runtime. | **High** |
| R5 | Un échec d'envoi d'e-mail n'est pas journalisé par livraison ; le jour où un envoi client échouera, rien ne le distinguera du bruit permanent de #79. | **High** |
| R6 | Le budget de tentatives n'est jamais terminalisé : une adresse morte régénère un échec par signal et par cycle, indéfiniment. | **Medium** |
| R7 | `/webhooks/instantly` et `/a/{token}` ne sont pas relayés par nginx : deux routes applicatives sont inaccessibles depuis l'extérieur. | **Medium** |
| R8 | La sauvegarde la plus récente précède la dernière migration ; une restauration ramènerait un schéma en `0023`. | **Low** |
| R9 | Le frontend servi est étiqueté `003e917` alors que le backend est en `030861d` — sans écart fonctionnel, mais la provenance affichée est fausse. | **Low** |
| R10 | DMARC est en `p=reject` sans `rua`/`ruf` : aucun rapport d'échec d'authentification n'est collecté. | **Low** |

## Actions minimales nécessaires avant production

1. **Faire tourner les quatre secrets exposés** (rôle `kivou_app`, mot de passe SMTP `no-reply@kivou.eu`, clé Stripe TEST, secret de signature du webhook), **purger le journal**, et supprimer l'habitude de passer un secret en argument de `sudo` — il faut passer par `EnvironmentFile`, `systemd-run --property=EnvironmentFile=` ou une redirection depuis un fichier à `600`.
2. **Réactiver `kivou-ingest-ted.timer` et lever le 429** — étaler ou plafonner le débit vers TED, et faire en sorte qu'un lot partiel avance le curseur au lieu de le laisser à `null`.
3. **Rendre DECP convergent** — soit relever `TimeoutStartSec` au-delà du besoin réel mesuré (47 min), soit borner la fenêtre par passage, et **fermer la ligne `ingestion_run` sur SIGTERM** pour qu'aucune exécution ne reste `running`. Nettoyer les 10 lignes ouvertes.
4. **Trancher le statut de l'Acquisition Engine** — soit livrer un point d'entrée qui enchaîne réellement les étapes et configure l'enveloppe budgétaire, soit le retirer explicitement du périmètre de lancement. Il n'est aujourd'hui ni exécutable ni annoncé comme indisponible.
5. **Journaliser le résultat par livraison d'e-mail** (compte, signal, code) et **terminaliser un refus définitif de destinataire** — puis assainir les trois comptes de test de #79.
6. **Exposer `/webhooks/instantly` et `/a/{token}`** dans nginx, ou les retirer de l'application.
7. **Prendre une sauvegarde après migration** dans la procédure de déploiement.

Les points 1 à 5 conditionnent le passage en production. Les points 6 et 7
peuvent suivre, mais avant tout usage réel de l'acquisition pour le point 6.

## Ce qui est prêt

Il faut le dire aussi nettement que le reste : **le produit vendu au client
fonctionne**. Un prospect peut créer son compte, décrire son ICP, voir de vrais
signaux issus d'avis publics français et suisses avec leur preuve et leur
source, ouvrir une fiche entreprise fondée sur un identifiant officiel, payer,
obtenir ses droits immédiatement, changer de formule, programmer un downgrade
sans perdre la période payée, et recevoir ses alertes. Deux sources sur quatre
alimentent ce parcours de façon fiable et automatique. L'infrastructure tient,
redémarre seule et se sauvegarde de manière restaurable.

Ce qui bloque n'est pas le cœur du produit : c'est la couverture des sources,
l'hygiène des secrets, l'observabilité des échecs, et une chaîne d'acquisition
qui n'existe pas encore en exécution.
