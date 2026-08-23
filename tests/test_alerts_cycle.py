"""SPEC-014 §15 à §29, §37 — l'alerte automatique, et tout ce qu'elle ne doit pas envoyer.

Le droit est réévalué À L'ENVOI (§29)
────────────────────────────────────
Un signal mis en file quand le compte payait ne part pas parce qu'il payait
hier. La chaîne est refaite au moment d'envoyer : propriété, fraîcheur
courante, identité affichable, droit du plan **courant**. Une résiliation de
la veille doit fermer la piste, pas la laisser filer par la poste.

Rejouable sans dégât
────────────────────
`signal_alert_delivery` a `(compte, signal)` en clé primaire et ne passe à
`sent` qu'après un envoi confirmé. Relancer le job n'envoie jamais deux fois
le même signal au même compte.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from engagement_helpers import (
    NOW,
    PUBLIC_APP_URL,
    Clock,
    FakeMailer,
    account_of,
    events,
    failure,
    icp_of,
    make_app,
    make_engine,
    pay,
    seed,
    seed_rich,
    signed_up,
)
from feed_helpers import RESEARCH_ICP_ID, SIMAP_RICH, materialize, materialize_simap, simap_award

from signals.alerts import policy, run_alert_cycle
from signals.alerts.gateway import UncertainDelivery, message_id
from signals.engagement.schema import signal_alert_delivery
from signals.recency.claim import JUST_WON_MARKERS


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    return make_engine(tmp_path)


@pytest.fixture
def app(engine, clock: Clock):
    return make_app(engine, clock)


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


def cycle(engine, mailer, *, now: dt.datetime = NOW, url: str | None = PUBLIC_APP_URL):
    return run_alert_cycle(engine, mailer, now=now, public_app_url=url)


def deliveries(engine) -> list[sa.Row]:
    with engine.connect() as connection:
        return connection.execute(sa.select(signal_alert_delivery)).all()


def subscriber(app, engine, *, plan: str, count: int = 1, email: str = "alice@negoce-romand.ch"):
    client = signed_up(app, email)
    icp = icp_of(client)
    pay(engine, client, plan=plan)
    keys = seed(engine, icp, count=count)
    return client, keys


# ─── §37.1 — Discovery ne reçoit rien ────────────────────────────────────────


def test_a_discovery_account_never_receives_an_automatic_email(app, engine, mailer):
    client = signed_up(app)
    icp = icp_of(client)
    seed(engine, icp, count=5)

    report = cycle(engine, mailer)
    assert mailer.sent == []
    assert deliveries(engine) == []
    assert [outcome.result for outcome in report.outcomes] == ["not_eligible"]


# ─── §37.2 à §37.5 — les cadences ────────────────────────────────────────────


def test_essential_receives_at_most_one_digest_per_week(app, engine, mailer):
    client, _ = subscriber(app, engine, plan="essential", count=3)
    icp = client.get("/target-icps").json()[0]["target_icp_id"]

    assert cycle(engine, mailer).signals_sent == 3
    seed(engine, icp, count=2, offset=3)

    # Le lendemain : rien. Huit jours plus tard : le digest suivant.
    assert cycle(engine, mailer, now=NOW + dt.timedelta(days=1)).signals_sent == 0
    assert cycle(engine, mailer, now=NOW + dt.timedelta(days=8)).signals_sent == 2
    assert len(mailer.sent) == 2


def test_pro_receives_at_most_one_digest_per_day(app, engine, mailer):
    client, _ = subscriber(app, engine, plan="pro", count=2)
    icp = client.get("/target-icps").json()[0]["target_icp_id"]

    assert cycle(engine, mailer).signals_sent == 2
    seed(engine, icp, count=1, offset=2)
    assert cycle(engine, mailer, now=NOW + dt.timedelta(hours=6)).signals_sent == 0
    assert cycle(engine, mailer, now=NOW + dt.timedelta(days=1)).signals_sent == 1


def test_a_founding_account_follows_the_pro_cadence(app, engine, mailer):
    client = signed_up(app)
    icp = icp_of(client)
    pay(engine, client, plan="pro", coupon_id="coupon_test_f")
    seed(engine, icp, count=1)
    assert client.get("/billing/status").json()["offer_code"] == "founding"

    assert cycle(engine, mailer).signals_sent == 1
    seed(engine, icp, count=1, offset=1)
    assert cycle(engine, mailer, now=NOW + dt.timedelta(hours=2)).signals_sent == 0
    assert cycle(engine, mailer, now=NOW + dt.timedelta(days=1)).signals_sent == 1


def test_scale_is_eligible_on_every_cycle(app, engine, mailer):
    client, _ = subscriber(app, engine, plan="scale", count=1)
    icp = client.get("/target-icps").json()[0]["target_icp_id"]

    assert cycle(engine, mailer).signals_sent == 1
    seed(engine, icp, count=1, offset=1)
    assert cycle(engine, mailer, now=NOW + dt.timedelta(minutes=10)).signals_sent == 1


def test_priority_is_never_called_realtime():
    """§15 — l'appeler « temps réel » promettrait ce qu'aucun cron ne tient."""
    from signals.billing.catalogue import SCALE

    assert SCALE.alert_cadence == "priority"
    assert "realtime" not in policy.MINIMUM_INTERVAL
    assert policy.MINIMUM_INTERVAL["priority"] == dt.timedelta(0)


def test_an_unknown_cadence_sends_nothing():
    """Défaut fermé : un plan mal orthographié ne provoque pas d'e-mails."""
    assert policy.is_due("hourly", last_sent_at=None, now=NOW) is False
    assert policy.is_due("none", last_sent_at=None, now=NOW) is False


# ─── §37.6, §37.7 — préférences et configuration ─────────────────────────────


def test_a_disabled_notification_preference_sends_nothing(app, engine, mailer):
    client, _ = subscriber(app, engine, plan="pro")
    assert (
        client.patch("/notification-preferences", json={"email_enabled": False}).status_code == 200
    )

    report = cycle(engine, mailer)
    assert mailer.sent == []
    assert [outcome.result for outcome in report.outcomes] == ["notifications_disabled"]


def test_without_a_public_app_url_nothing_is_sent_and_signals_stay_queued(app, engine, mailer):
    """§22 — un lien cassé est pire qu'un e-mail non envoyé."""
    subscriber(app, engine, plan="pro", count=2)

    report = cycle(engine, mailer, url=None)
    assert mailer.sent == []
    assert [outcome.result for outcome in report.outcomes] == ["blocked"]
    queued = deliveries(engine)
    assert len(queued) == 2
    assert {row.status for row in queued} == {"queued"}

    # L'URL configurée, les signaux en attente partent.
    assert cycle(engine, mailer).signals_sent == 2


def test_the_notification_email_is_initialised_from_the_owner_then_frozen(app, engine, mailer):
    client, _ = subscriber(app, engine, plan="pro")
    preference = client.get("/notification-preferences").json()
    assert preference["notification_email"] == "alice@negoce-romand.ch"
    assert preference["email_enabled"] is True

    client.patch(
        "/notification-preferences", json={"notification_email": "Alertes@Negoce-Romand.CH"}
    )
    cycle(engine, mailer)
    assert mailer.last.to_email == "alertes@negoce-romand.ch"


def test_an_invalid_notification_email_is_refused(app, engine):
    client, _ = subscriber(app, engine, plan="pro")
    response = client.patch(
        "/notification-preferences", json={"notification_email": "pas-une-adresse"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_notification_email"


def test_one_account_never_reads_the_preferences_of_another(app, engine):
    alice, _ = subscriber(app, engine, plan="pro")
    bob = signed_up(app, "bob@materiaux-leman.ch")
    alice.patch(
        "/notification-preferences", json={"notification_email": "alertes@negoce-romand.ch"}
    )

    assert bob.get("/notification-preferences").json()["notification_email"] == (
        "bob@materiaux-leman.ch"
    )


def test_notification_preferences_need_a_session_and_csrf(app, engine):
    from fastapi.testclient import TestClient
    from feed_helpers import ORIGIN

    client, _ = subscriber(app, engine, plan="pro")
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.get("/notification-preferences").status_code == 401
    assert (
        client.patch(
            "/notification-preferences",
            json={"email_enabled": False},
            headers={"Origin": "https://attaquant.example"},
        ).status_code
        == 403
    )


# ─── §19, §37.8 — un signal n'est alerté qu'une fois ─────────────────────────


def test_an_already_alerted_signal_is_never_sent_again(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=2)
    assert cycle(engine, mailer).signals_sent == 2
    assert cycle(engine, mailer, now=NOW + dt.timedelta(hours=1)).signals_sent == 0
    assert len(mailer.sent) == 1


def test_the_job_is_safe_to_rerun(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=3)
    for _ in range(5):
        cycle(engine, mailer)
    assert len(mailer.sent) == 1
    assert {row.status for row in deliveries(engine)} == {"sent"}


# ─── §16, §37.9 à §37.12 — ce qui n'est jamais alerté ────────────────────────


def test_a_stale_signal_is_never_alerted(app, engine, mailer):
    """Seules les NOUVEAUTÉS partent : un marché de mai n'en est pas une."""
    client = signed_up(app)
    icp = icp_of(client)
    pay(engine, client, plan="scale")
    with engine.begin() as connection:
        materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)

    assert cycle(engine, mailer).signals_sent == 0
    assert mailer.sent == []


def test_a_foreign_account_signal_is_never_alerted(app, engine, mailer):
    _, alice_keys = subscriber(app, engine, plan="pro", count=1)
    bob = signed_up(app, "bob@materiaux-leman.ch")
    icp_of(bob)
    pay(engine, bob, plan="scale")

    cycle(engine, mailer)
    bob_account = account_of(bob)
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(signal_alert_delivery).where(
                signal_alert_delivery.c.account_id == bob_account
            )
        ).all()
    assert rows == []
    assert alice_keys[0] not in str(rows)


def test_an_unbound_signal_is_never_alerted(app, engine, mailer):
    client = signed_up(app)
    icp = icp_of(client)
    pay(engine, client, plan="scale")
    keys = seed(engine, icp, count=1)
    with engine.begin() as connection:
        event, awards = simap_award("41098-01")
        unbound = materialize(
            connection,
            event,
            awards[0].model_copy(update={"award_date": dt.date(2026, 8, 13)}),
            target_icp_id=RESEARCH_ICP_ID,
        )

    cycle(engine, mailer)
    alerted = {row.signal_key for row in deliveries(engine)}
    assert alerted == {keys[0]}
    assert unbound.signal_key not in alerted


def test_a_winner_known_only_by_its_identifier_is_never_alerted(app, engine, mailer):
    """Un e-mail annonçant « 44284979000013 » n'aiderait personne."""
    client = signed_up(app)
    icp = icp_of(client)
    pay(engine, client, plan="scale")
    with engine.begin() as connection:
        event, awards = simap_award("29997-02")
        award = awards[0].model_copy(update={"award_date": dt.date(2026, 8, 13)})
        parties = []
        for party in award.awardee_parties:
            members = [
                member.model_copy(
                    update={
                        "organization": member.organization.model_copy(
                            update={"legal_name": member.organization.identifiers[0].value}
                        )
                    }
                )
                for member in party.members
            ]
            parties.append(party.model_copy(update={"members": tuple(members)}))
        materialize(
            connection,
            event,
            award.model_copy(update={"awardee_parties": tuple(parties)}),
            target_icp_id=icp,
        )

    assert cycle(engine, mailer).signals_sent == 0
    assert mailer.sent == []


# ─── §29, §37.13 — le droit est réévalué à l'envoi ───────────────────────────


def test_a_downgrade_before_sending_re_evaluates_the_entitlement(app, engine, mailer):
    """Le compte payait quand le signal est devenu éligible ; il ne paie plus."""
    client, _ = subscriber(app, engine, plan="pro", count=3)
    pay(engine, client, plan="pro", status="canceled")

    report = cycle(engine, mailer)
    assert mailer.sent == []
    assert [outcome.result for outcome in report.outcomes] == ["not_eligible"]


def test_a_paid_account_only_receives_what_its_plan_unlocks(app, engine, mailer):
    """Essential ouvre 30 jours : un signal plus ancien reste verrouillé."""
    client = signed_up(app)
    icp = icp_of(client)
    pay(engine, client, plan="essential")
    with engine.begin() as connection:
        fresh_event, fresh_awards = simap_award("29997-02")
        materialize(
            connection,
            fresh_event,
            fresh_awards[0].model_copy(update={"award_date": dt.date(2026, 8, 13)}),
            target_icp_id=icp,
        )
        old_event, old_awards = simap_award("33112-02")
        materialize(
            connection,
            old_event,
            old_awards[0].model_copy(update={"award_date": dt.date(2026, 5, 1)}),
            target_icp_id=icp,
        )

    assert cycle(engine, mailer).signals_sent == 1


# ─── §20, §37.14, §37.15 — le digest est borné ───────────────────────────────


def test_an_email_carries_at_most_ten_signals(app, engine, mailer):
    client, _ = subscriber(app, engine, plan="scale", count=6)
    icp = client.get("/target-icps").json()[0]["target_icp_id"]
    seed(engine, icp, count=6, offset=6)

    report = cycle(engine, mailer)
    assert report.signals_sent == policy.MAXIMUM_SIGNALS_PER_EMAIL == 10
    assert len(mailer.sent) == 1


def test_the_remaining_signals_stay_available_for_the_next_cycle(app, engine, mailer):
    client, _ = subscriber(app, engine, plan="scale", count=6)
    icp = client.get("/target-icps").json()[0]["target_icp_id"]
    seed(engine, icp, count=6, offset=6)

    assert cycle(engine, mailer).signals_sent == 10
    assert cycle(engine, mailer, now=NOW + dt.timedelta(minutes=5)).signals_sent == 2
    assert len(mailer.sent) == 2
    assert len({row.signal_key for row in deliveries(engine)}) == 12


# ─── §27, §37.16 — l'échec reste rejouable ───────────────────────────────────


def test_a_known_delivery_failure_stays_retryable(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=2)
    mailer.fail_with = failure("smtp_451")

    report = cycle(engine, mailer)
    assert [outcome.result for outcome in report.outcomes] == ["failed"]
    rows = deliveries(engine)
    assert {row.status for row in rows} == {"failed"}
    assert {row.last_error_code for row in rows} == {"smtp_451"}
    assert {row.attempt_count for row in rows} == {1}

    # Le backoff est durable : pas de rejeu précoce, puis reprise à l'échéance.
    assert cycle(engine, mailer, now=NOW + dt.timedelta(minutes=5)).signals_sent == 0
    assert mailer.attempts == 1
    assert cycle(engine, mailer, now=NOW + dt.timedelta(minutes=15)).signals_sent == 2
    assert {row.status for row in deliveries(engine)} == {"sent"}


def test_an_uncertain_delivery_is_never_blindly_resent(app, engine, mailer):
    """§27 — recevoir deux fois la même alerte coûte plus cher que la recevoir tard."""
    subscriber(app, engine, plan="scale", count=1)
    mailer.fail_with = UncertainDelivery()

    report = cycle(engine, mailer)
    assert [outcome.result for outcome in report.outcomes] == ["unknown_delivery_state"]
    rows = deliveries(engine)
    assert {row.status for row in rows} == {"unknown_delivery_state"}
    assert {row.last_error_code for row in rows} == {"unknown_delivery_state"}
    assert {row.retryable for row in rows} == {True}
    assert cycle(engine, mailer, now=NOW + dt.timedelta(minutes=14)).signals_sent == 0
    assert mailer.attempts == 1

    identifier = rows[0].delivery_message_id
    assert cycle(engine, mailer, now=NOW + dt.timedelta(minutes=15)).signals_sent == 1
    assert mailer.last.message_id == identifier


def test_a_failure_never_consumes_the_accounts_turn(app, engine, mailer):
    """La cadence se calcule sur le dernier envoi RÉUSSI."""
    subscriber(app, engine, plan="essential", count=1)
    mailer.fail_with = failure()
    cycle(engine, mailer)

    # Le lendemain, l'hebdomadaire n'a rien perdu : il réessaie.
    assert cycle(engine, mailer, now=NOW + dt.timedelta(days=1)).signals_sent == 1


def test_no_exception_trace_or_credential_reaches_the_database(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=1)
    mailer.fail_with = failure("smtp_535")
    cycle(engine, mailer)

    body = str([dict(row._mapping) for row in deliveries(engine)])
    for forbidden in (
        "Traceback",
        "password",
        "smtplib",
        "login",
        "alice@negoce-romand.ch",
    ):
        assert forbidden not in body, forbidden


# ─── §28, §37.17 — l'identifiant de message ──────────────────────────────────


def test_the_message_id_is_deterministic_and_leaks_nothing(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=2)
    cycle(engine, mailer)

    identifier = mailer.last.message_id
    assert identifier.startswith("<kivou-alert-")
    assert identifier.endswith("@kivou.ch>")
    for forbidden in ("@negoce-romand", "alice", "acc_"):
        assert forbidden not in identifier, forbidden


def test_the_same_batch_always_produces_the_same_message_id():
    first = message_id(account_id="acc_1", batch_key="2026-08-25:a:b")
    second = message_id(account_id="acc_1", batch_key="2026-08-25:a:b")
    third = message_id(account_id="acc_2", batch_key="2026-08-25:a:b")
    assert first == second
    assert first != third


# ─── §21, §37.18 à §37.20 — le contenu de l'e-mail ───────────────────────────


def test_the_digest_is_written_in_the_account_language(app, engine, mailer):
    english = signed_up(app, "bob@materiaux-leman.ch", locale="en")
    icp = icp_of(english)
    pay(engine, english, plan="scale")
    # L'avis riche : celui qui porte des besoins plausibles à traduire.
    seed_rich(engine, icp)

    cycle(engine, mailer)
    message = mailer.last
    assert message.language == "en"
    assert "new opportunit" in message.subject
    assert "Hello," in message.text_body
    assert "Plausible needs" in message.text_body


def test_the_french_digest_uses_the_established_safe_wording(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=1)
    cycle(engine, mailer)

    body = mailer.last.text_body
    assert "Bonjour," in body
    assert "vient de remporter un marché public." in body
    assert "Décision d'attribution récente." in body


def test_an_old_signal_never_gets_new_opportunity_wording_in_an_email(app, engine, mailer):
    """§21 — la formulation vient de la politique de fraîcheur, jamais de l'e-mail."""
    client = signed_up(app)
    icp = icp_of(client)
    pay(engine, client, plan="scale")
    with engine.begin() as connection:
        materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)

    cycle(engine, mailer)
    assert mailer.sent == [], "un signal périmé n'est pas une nouveauté"


def test_the_email_contains_a_deep_link_to_each_signal(app, engine, mailer):
    _, keys = subscriber(app, engine, plan="scale", count=2)
    cycle(engine, mailer)

    body = mailer.last.text_body
    for key in keys:
        assert f"{PUBLIC_APP_URL}/app/signals/{key}" in body


def test_the_deep_link_resolves_to_the_browser_signal_route(app, engine, mailer):
    """CLOSEOUT §3 — le lien reçu par e-mail doit ouvrir la route du navigateur.

    La configuration fournit seulement l'origine. Le constructeur serveur
    ajoute `/app/signals/{clé}` afin que le déploiement ne puisse ni omettre ni
    dupliquer le préfixe du routeur.

    Aucune sémantique d'alerte n'est modifiée ici : seule la FORME de la base
    est vérifiée.
    """
    _, keys = subscriber(app, engine, plan="scale", count=1)
    cycle(engine, mailer)

    link = f"{PUBLIC_APP_URL}/app/signals/{keys[0]}"
    assert link in mailer.last.text_body
    # C'est bien la route cliente, pas la route publique.
    assert "/app/signals/" in link


def test_the_email_never_dumps_evidence(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=2)
    cycle(engine, mailer)

    body = mailer.last.text_body
    for forbidden in ("evidence", "public_facts", "analysis_inputs", "retrieved_at", "path"):
        assert forbidden not in body.lower(), forbidden
    assert "simap.ch" not in body.lower()


def test_the_email_never_carries_internal_engine_vocabulary(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=2)
    cycle(engine, mailer)

    body = mailer.last.text_body.lower()
    for forbidden in (
        "need-rules",
        "icp-match",
        "signal-score",
        "rule_ids",
        "normalized_score",
        "trade_domain",
        "bkp-trade",
        "confidence",
    ):
        assert forbidden not in body, forbidden


def test_the_email_never_claims_a_win_it_cannot_support(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=3)
    cycle(engine, mailer)

    body = mailer.last.text_body
    # Les signaux envoyés sont tous `recent_award` : la phrase de victoire est
    # légitime ici, et c'est la seule configuration où elle l'est.
    assert any(marker in body.lower() for marker in JUST_WON_MARKERS)


def test_no_tracking_pixel_or_third_party_tracker_is_added(app, engine, mailer):
    """§24 — on veut savoir qu'un e-mail est parti, pas espionner qui l'ouvre."""
    subscriber(app, engine, plan="scale", count=1)
    cycle(engine, mailer)

    body = mailer.last.text_body.lower()
    for forbidden in ("<img", "pixel", "utm_", "open.gif", "track", "click?"):
        assert forbidden not in body, forbidden


# ─── §10 — l'analytique des alertes ──────────────────────────────────────────


def test_the_cycle_records_queue_and_send_events(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=2)
    cycle(engine, mailer)

    queued = events(engine, event_type="alert_queued")
    sent = events(engine, event_type="alert_sent")
    assert len(queued) == 2
    assert len(sent) == 1, "un envoi, pas un par signal"
    assert sent[0].properties["signal_count"] == 2
    assert sent[0].properties["cadence"] == "priority"


def test_a_failure_records_an_alert_failed_event(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=1)
    mailer.fail_with = failure("smtp_451")
    cycle(engine, mailer)

    recorded = events(engine, event_type="alert_failed")
    assert len(recorded) == 1
    assert recorded[0].properties["error_code"] == "smtp_451"
    assert recorded[0].properties["retryable"] is True


def test_a_requeued_signal_is_not_counted_twice_as_queued(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=1)
    mailer.fail_with = failure()
    cycle(engine, mailer)
    cycle(engine, mailer, now=NOW + dt.timedelta(minutes=5))

    assert len(events(engine, event_type="alert_queued")) == 1


# ─── §25 — le job reste une simple fonction ──────────────────────────────────


def test_no_task_queue_or_broker_is_introduced():
    """§25 — un VPS avec cron, pas un orchestrateur.

    L'analyse porte sur les IMPORTS, pas sur le texte : un commentaire a le
    droit de nommer Celery pour expliquer qu'on ne s'en sert pas.
    """
    import ast
    import inspect

    from signals.alerts import job

    tree = ast.parse(inspect.getsource(job))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for forbidden in ("celery", "redis", "kafka", "rq", "apscheduler", "kombu"):
        assert forbidden not in imported, forbidden


def test_the_job_reads_no_hidden_clock():
    """§26 — `now` est explicite, sinon une cadence cesserait d'être testable."""
    import inspect

    from signals.alerts import content, job
    from signals.alerts import policy as alert_policy

    for module in (job, alert_policy, content):
        source = inspect.getsource(module)
        for forbidden in ("date.today()", "datetime.now(", "utcnow("):
            assert forbidden not in source, f"{module.__name__} : {forbidden}"
