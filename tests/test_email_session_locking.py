"""Identity mutations lock the user and session before authorizing the request."""
import sqlalchemy as sa
from test_email_verification import request_proof

pytest_plugins = ("test_email_verification",)


def test_email_request_authorizes_after_user_and_session_locks(prepared_email, monkeypatch):
    engine, client, _, _, _ = prepared_email
    from signals.api import routes_email

    locked = []

    def capture(connection, statement, multiparams, params, options):
        if isinstance(statement, sa.sql.Select) and statement._for_update_arg is not None:
            locked.extend(table.name for table in statement.get_final_froms())

    original = routes_email.current_session

    def after_locks(*args, **kwargs):
        assert locked[:2] == ["auth_user", "auth_session"]
        return original(*args, **kwargs)

    sa.event.listen(engine, "before_execute", capture)
    monkeypatch.setattr(routes_email, "current_session", after_locks)
    try:
        assert request_proof(client).status_code == 200
    finally:
        sa.event.remove(engine, "before_execute", capture)


def test_revoked_session_cannot_request_another_proof(prepared_email):
    engine, client, mailbox, clock, user = prepared_email
    from signals.accounts.service import revoke_all_sessions

    with engine.begin() as connection:
        revoke_all_sessions(connection, user_id=user["user_id"], now=clock[0])
    assert request_proof(client).status_code == 401
    assert mailbox.messages == []
