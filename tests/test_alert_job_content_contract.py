"""Exercise the timer's real job and capture its email, not just a template."""
from __future__ import annotations

import datetime as dt
import html
import os
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal

import pytest
import sqlalchemy as sa
from alert_identity_helpers import verified_signed_up
from engagement_helpers import (
    NOW,
    Clock,
    FakeMailer,
    account_of,
    icp_of,
    make_app,
    make_engine,
    pay,
    seed,
)

from signals.accounts.schema import account_landing_signal
from signals.alerts import job
from signals.engagement.schema import product_event, signal_alert_delivery
from signals.persistence.schema import for_you_sentence

PUBLIC_ORIGIN = 'https://kivou.eu'
SENTENCE = 'Votre offre accompagne les besoins vérifiés de ce titulaire.'


def prepared(tmp_path, *, locale='fr', paid=True, count=1):
    engine = make_engine(tmp_path)
    app = make_app(engine, Clock())
    client = verified_signed_up(app, engine, locale=locale)
    if paid:
        pay(engine, client, plan='essential')
    keys = seed(engine, icp_of(client), count=count)
    with engine.begin() as connection:
        connection.execute(sa.update(for_you_sentence).where(
            for_you_sentence.c.signal_key.in_(keys)
        ).values(sentence=SENTENCE, provenance='generated', state='completed'))
    return engine, app, client, account_of(client), keys


@pytest.mark.parametrize('locale', ['fr', 'en'])
def test_timer_job_emits_today_fields_and_persisted_for_you_in_both_parts(tmp_path, locale):
    engine, _app, client, account_id, keys = prepared(tmp_path, locale=locale)
    response = client.get('/dashboard')
    assert response.status_code == 200
    card = response.json()['top3'][0]
    assert card['analysis']['fit']['for_you_sentence'] == SENTENCE
    mailer = FakeMailer()
    report = job.run_alert_cycle(engine, mailer, account_id=account_id,
                                 now=NOW, public_app_url=PUBLIC_ORIGIN)
    assert report.signals_sent == 1
    assert len(mailer.sent) == 1
    message = mailer.last
    title = card['contract']['lot_title'] or card['contract']['title'] or card['factual_display']['object_short']
    amount = card['contract']['amount']
    rounded = Decimal(amount['value']).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    digits = f'{rounded:,.0f}'
    expected_amount = (digits.replace(',', '\u00a0') + '\u00a0CHF'
                       if locale == 'fr' else 'CHF\u00a0' + digits)
    date = dt.date.fromisoformat(card['factual_display']['date']['value'])
    expected_date = f'{date.day} ' + ('août' if locale == 'fr' else 'Aug')
    place = card['contract']['location']
    for body in (message.text_body, html.unescape(message.html_body or '')):
        for value in (card['company']['name'], title, expected_amount, expected_date,
                      (place['locality'] or place['subdivision_label']) if place else '—', SENTENCE,
                      f'{PUBLIC_ORIGIN}/app/signals/{keys[0]}',
                      'Ouvrir' if locale == 'fr' else 'Open'):
            assert value in body
        for obsolete in ('Besoins plausibles', 'Plausible needs',
                         'Une attribution concernant', 'vient de remporter un marché public.',
                         'Décision d\'attribution récente.'):
            assert obsolete not in body
    assert message.message_id.endswith('@kivou.eu>')
    assert message.content_version == 'kivou-alert-pr6-v1'


def test_discovery_job_offer_link_is_tarifs_not_pricing(tmp_path):
    engine, _app, client, account_id, _keys = prepared(tmp_path, paid=False, count=3)
    assert client.get('/signals').status_code == 200
    mailer = FakeMailer()
    report = job.run_alert_cycle(engine, mailer, account_id=account_id,
                                 now=NOW, public_app_url=PUBLIC_ORIGIN)
    assert report.signals_sent == 1
    for body in (mailer.last.text_body, mailer.last.html_body):
        assert f'{PUBLIC_ORIGIN}/tarifs' in body
        assert '/pricing' not in body


def test_explicit_qa_nonce_resends_once_without_touching_another_account(tmp_path):
    engine, app, _client, account_id, _keys = prepared(tmp_path)
    other = verified_signed_up(app, engine, email='bob@materiaux-leman.ch')
    pay(engine, other, plan='essential')
    seed(engine, icp_of(other))
    other_id = account_of(other)
    with engine.begin() as connection:
        connection.execute(sa.insert(account_landing_signal).values(
            account_id=account_id, qa=True, created_at=NOW))
    mailer = FakeMailer()
    assert job.run_alert_cycle(engine, mailer, account_id=account_id, now=NOW,
                               public_app_url=PUBLIC_ORIGIN).signals_sent == 1
    original_id = mailer.last.message_id
    kwargs = {'account_id': account_id, 'now': NOW, 'public_app_url': PUBLIC_ORIGIN,
              'qa_resend_nonce': 'recipe-20260908-g1'}
    assert job.run_alert_cycle(engine, mailer, **kwargs).signals_sent == 1
    assert mailer.last.message_id != original_id
    assert job.run_alert_cycle(engine, mailer, **kwargs).signals_sent == 0
    assert len(mailer.sent) == 2
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(signal_alert_delivery)
                                 .where(signal_alert_delivery.c.account_id == other_id)) == 0
        markers = connection.execute(sa.select(product_event.c.properties).where(
            product_event.c.account_id == account_id,
            product_event.c.event_id.like('evt_qa_alert_%'),
        )).scalars().all()
        assert len(markers) == 1
        assert markers[0]['qa'] is True
        assert 'recipe-20260908-g1' not in str(markers)


@pytest.mark.parametrize('condition', ['unscoped', 'unmarked', 'unverified'])
def test_qa_resend_cannot_bypass_scope_marker_or_verification(tmp_path, condition):
    engine, _app, _client, account_id, _keys = prepared(tmp_path)
    if condition != 'unmarked':
        with engine.begin() as connection:
            connection.execute(sa.insert(account_landing_signal).values(
                account_id=account_id, qa=True, created_at=NOW))
    if condition == 'unverified':
        from signals.accounts.email_verification import email_identity
        with engine.begin() as connection:
            connection.execute(sa.update(email_identity).values(verified_at=None, verified_email=None))
    mailer = FakeMailer()
    kwargs = {'account_id': None if condition == 'unscoped' else account_id,
              'now': NOW, 'public_app_url': PUBLIC_ORIGIN, 'qa_resend_nonce': 'recipe-20260908-g1'}
    if condition in {'unscoped', 'unmarked'}:
        with pytest.raises(ValueError):
            job.run_alert_cycle(engine, mailer, **kwargs)
    else:
        assert job.run_alert_cycle(engine, mailer, **kwargs).signals_sent == 0
    assert mailer.sent == []


def test_cli_imports_and_dry_runs_in_a_fresh_process_without_smtp(tmp_path):
    env = {**os.environ, 'PYTHONPATH': 'src',
           'KIVOU_DATABASE_URL': f'sqlite+pysqlite:///{tmp_path / "cli.db"}',
           'KIVOU_ALLOWED_ORIGIN': PUBLIC_ORIGIN, 'KIVOU_PUBLIC_APP_URL': PUBLIC_ORIGIN,
           'SMTP_HOST': 'smtp.example.test', 'SMTP_PORT': '587',
           'SMTP_FROM_EMAIL': 'alerts@kivou.eu', 'SMTP_TLS_MODE': 'starttls'}
    for key in ('SMTP_USERNAME', 'SMTP_PASSWORD', 'STRIPE_SECRET_KEY',
                'KIVOU_ATTRIBUTION_HMAC_KEY', 'KIVOU_ATTRIBUTION_HMAC_KEY_VERSION'):
        env.pop(key, None)
    result = subprocess.run([sys.executable, '-m', 'signals.alerts', '--account-id',
                             'acc_approved_qa', '--qa-resend-nonce', 'recipe-20260908-g1',
                             '--dry-run'], env=env, capture_output=True, text=True, timeout=30,
                            check=False)
    assert result.returncode == 0, result.stderr
    assert 'no_delivery_attempted=true' in result.stdout


@pytest.mark.parametrize(('clock', 'label'), [('notification', 'Attribué le'), ('publication', 'Publié le')])
def test_actual_job_uses_effective_date_and_clock_label(tmp_path, clock, label):
    from signals.persistence.schema import contract_award, materialized_signal, source_event

    engine, _app, client, account_id, keys = prepared(tmp_path)
    with engine.begin() as connection:
        award_key = connection.scalar(sa.select(materialized_signal.c.materialization_award_key)
                                      .where(materialized_signal.c.signal_key == keys[0]))
        event_key = connection.scalar(sa.select(contract_award.c.event_key)
                                      .where(contract_award.c.award_key == award_key))
        connection.execute(sa.update(contract_award).where(contract_award.c.award_key == award_key)
                           .values(award_date=None, contract_notification_date=(
                               NOW.date() - dt.timedelta(days=2) if clock == 'notification' else None)))
        connection.execute(sa.update(source_event).where(source_event.c.event_key == event_key)
                           .values(published_on=NOW.date(), published_at_raw=NOW.date().isoformat(),
                                   published_precision='date'))
    card = client.get('/dashboard').json()['top3'][0]
    assert card['factual_display']['date']['kind'] == clock
    expected_day = dt.date.fromisoformat(card['factual_display']['date']['value']).day
    mailer = FakeMailer()
    report = job.run_alert_cycle(engine, mailer, account_id=account_id,
                                 now=NOW, public_app_url=PUBLIC_ORIGIN)
    assert report.signals_sent == 1
    for body in (mailer.last.text_body, html.unescape(mailer.last.html_body)):
        assert f'{label} {expected_day} août' in body
        assert 'Notifié le' not in body


def test_real_discovery_job_does_not_render_locked_neighbour_cards(tmp_path):
    from signals.accounts import service as accounts
    from signals.persistence.schema import materialized_signal

    engine, _app, client, account_id, keys = prepared(tmp_path, paid=False, count=3)
    with engine.begin() as connection:
        opportunity = connection.scalar(sa.select(materialized_signal.c.opportunity_key)
                                        .where(materialized_signal.c.signal_key == keys[0]))
        accounts.record_landing_signal(connection, account_id=account_id,
                                       opportunity_key=opportunity, signal_key=keys[0], qa=True, now=NOW)
    dashboard = client.get('/dashboard').json()
    assert dashboard['plan']['opened'] == 1
    assert [card['signal_id'] for card in dashboard['top3']] == [keys[0]]
    mailer = FakeMailer()
    assert job.run_alert_cycle(engine, mailer, account_id=account_id,
                               now=NOW, public_app_url=PUBLIC_ORIGIN).signals_sent == 1
    assert mailer.last.html_body.count('<article') == 1
    for key in keys[1:]:
        assert key not in mailer.last.text_body
        assert key not in mailer.last.html_body


def test_nonce_retry_preserves_id_and_backoff_without_rearming_a_pending_batch(tmp_path):
    from signals.alerts.gateway import AlertDeliveryError

    engine, _app, _client, account_id, _keys = prepared(tmp_path)
    with engine.begin() as connection:
        connection.execute(sa.insert(account_landing_signal).values(
            account_id=account_id, qa=True, created_at=NOW))
    mailer = FakeMailer()
    assert job.run_alert_cycle(engine, mailer, account_id=account_id, now=NOW,
                               public_app_url=PUBLIC_ORIGIN).signals_sent == 1
    mailer.fail_with = AlertDeliveryError('smtp_451')
    kwargs = {'account_id': account_id, 'public_app_url': PUBLIC_ORIGIN,
              'qa_resend_nonce': 'recipe-20260908-retry'}
    report = job.run_alert_cycle(engine, mailer, now=NOW, **kwargs)
    assert report.outcomes[0].result == 'failed'
    with engine.connect() as connection:
        identifier = connection.scalar(sa.select(signal_alert_delivery.c.delivery_message_id).where(
            signal_alert_delivery.c.account_id == account_id))
    assert job.run_alert_cycle(engine, mailer, now=NOW, **kwargs).signals_sent == 0
    other_nonce = {**kwargs, 'qa_resend_nonce': 'recipe-20260908-other'}
    assert job.run_alert_cycle(engine, mailer, now=NOW, **other_nonce).outcomes[0].result == 'qa_resend_pending_batch'
    assert job.run_alert_cycle(engine, mailer, now=NOW + dt.timedelta(minutes=15), **kwargs).signals_sent == 1
    assert mailer.last.message_id == identifier
    assert mailer.attempts == 3


def test_configured_sender_domain_is_used_without_hardcoding_staging():
    from signals.alerts.gateway import configured_message_domain

    assert configured_message_domain('https://staging.kivou.eu', 'Kivou <alerts@kivou.eu>') == 'kivou.eu'
    assert configured_message_domain('https://preview.example.org') == 'preview.example.org'


def test_pending_legacy_id_is_preserved_while_current_content_is_rendered(tmp_path):
    engine, _app, _client, account_id, _keys = prepared(tmp_path)
    mailer = FakeMailer()
    assert job.run_alert_cycle(engine, mailer, account_id=account_id,
                               now=NOW, public_app_url=None).outcomes[0].result == 'blocked'
    legacy_id = '<legacy-queued-alert@kivou.ch>'
    with engine.begin() as connection:
        connection.execute(sa.update(signal_alert_delivery).where(
            signal_alert_delivery.c.account_id == account_id
        ).values(delivery_message_id=legacy_id))
    assert job.run_alert_cycle(engine, mailer, account_id=account_id,
                               now=NOW, public_app_url=PUBLIC_ORIGIN).signals_sent == 1
    assert mailer.last.message_id == legacy_id
    assert mailer.last.content_version == 'kivou-alert-pr6-v1'
    assert 'Besoins plausibles' not in mailer.last.text_body
    assert job.run_alert_cycle(engine, mailer, account_id=account_id,
                               now=NOW, public_app_url=PUBLIC_ORIGIN).signals_sent == 0
    assert len(mailer.sent) == 1
