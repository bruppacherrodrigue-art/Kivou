"""The landing journal is the single authority for recipe-account exclusion."""

import sqlalchemy as sa

from signals.accounts.schema import account_landing_signal


def commercial_account(account_id):
    return ~sa.exists().where(
        account_landing_signal.c.account_id == account_id,
        account_landing_signal.c.qa.is_(True),
    )


def is_qa_account(connection, account_id: str) -> bool:
    return bool(connection.scalar(sa.select(account_landing_signal.c.qa).where(
        account_landing_signal.c.account_id == account_id,
    )))
