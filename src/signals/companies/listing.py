"""PR1 §3 — `GET /companies` : l'agrégat par titulaire résolu, pas par signal.

Un signal se lit un par un ; une démarche commerciale vise une ENTREPRISE.
Cette liste regroupe donc les signaux accessibles du compte par
`company_identity_fingerprint` → `saas_company`, exactement comme
`engagement/company.py` le fait déjà pour la fiche d'une entreprise, mais pour
TOUTES les entreprises du compte à la fois plutôt qu'une seule.

Un signal sans entreprise résolue (aucun `run_winner_enrichment_batch` encore
passé) n'apparaît pas : ce n'est pas une exclusion, c'est qu'il n'a encore
rien à regrouper.

Le balayage est le même que `history_page` (§17 SPEC-012) : borné par
`HISTORY_SCAN_CAP`, annoncé par `scan_truncated` plutôt que silencieusement
tronqué. Mais contrairement à `history_page`, qui pagine directement le
balayage SQL, cette liste pagine l'agrégat déjà construit : le classement par
`company_key` n'existe qu'après le regroupement, donc le keyset ne peut porter
que sur la liste triée finale, en mémoire.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Literal

import sqlalchemy as sa

from signals.billing.access import FeedAccess
from signals.client_value.company_identity import exact_french_siren
from signals.client_value.company_name import normalize_holder_name
from signals.companies.schema import saas_company
from signals.companies.service import (
    company_keys_for_signals,
    ensure_companies_for_signal_keys,
)
from signals.engagement.company import contacts_by_company
from signals.engagement.prospecting_schema import (
    account_company_alias_override,
    account_company_membership,
    company_manual_contact,
    company_subject_alias,
)
from signals.engagement.schema import company_contact, company_note
from signals.feed import query as feed_query
from signals.feed.history import effective_history_date
from signals.feed.policy import fit_band
from signals.feed.query import (
    FEEDING_ICP_STATUS,
    FeedSignal,
    _ownership_scoped,
    owned_target_icps,
)
from signals.feed.text import normalize_text
from signals.persistence.repository import StoredSignal, signal_from_row
from signals.persistence.schema import materialized_signal, supplier_directory

_SCAN_BATCH = 250

_CURSOR_KEYS = frozenset({"v", "d", "k"})
_CURSOR_VERSION = 1
_MAX_ENCODED_CURSOR_LENGTH = 512
#: `signals.companies.identity.company_key` — `cmp_` suivi d'un `token_urlsafe`.
_COMPANY_KEY = re.compile(r"^cmp_[A-Za-z0-9_-]{6,80}$")

#: Meilleur `icp_match_band` d'abord. `excluded` et l'absence de bande (aucune
#: correspondance encore évaluée) se valent : `unknown` ne prétend à rien.
#:
#: PR2b — le vocabulaire de la bande (`strong|promising|weak|unknown`) vient de
#: `feed.policy.fit_band` : seul le RANG de tri reste propre à ce module.
_FIT_RANK: dict[str, int] = {"strong": 3, "promising": 2, "weak": 1, "unknown": 0}
_RANK_TO_FIT = {rank: label for label, rank in _FIT_RANK.items()}


class InvalidCompanyCursor(ValueError):
    """Le curseur est malformé ou appartient à une autre version de contrat."""


@dataclasses.dataclass(frozen=True)
class CompanyCursor:
    date: dt.date | None
    company_key: str
    version: Literal[1] = _CURSOR_VERSION
    context_tag: str | None = None
    sort: str = "recent"
    amount: Decimal | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if self.version != _CURSOR_VERSION or not _COMPANY_KEY.fullmatch(self.company_key):
            raise InvalidCompanyCursor("invalid company cursor")


def encode_company_cursor(cursor: CompanyCursor) -> str:
    extra = (
        {
            "x": {
                "f": cursor.context_tag,
                "s": cursor.sort,
                "a": str(cursor.amount) if cursor.amount is not None else None,
                "u": cursor.currency,
            }
        }
        if cursor.context_tag is not None or cursor.sort != "recent"
        else {}
    )
    payload = json.dumps(
        {
            "v": cursor.version,
            "d": cursor.date.isoformat() if cursor.date is not None else None,
            "k": cursor.company_key,
            **extra,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_company_cursor(value: str) -> CompanyCursor:
    if not value or len(value) > _MAX_ENCODED_CURSOR_LENGTH:
        raise InvalidCompanyCursor("invalid company cursor")
    padding = "=" * (-len(value) % 4)
    try:
        raw = base64.b64decode(
            (value + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw)
    except (UnicodeEncodeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as error:
        raise InvalidCompanyCursor("invalid company cursor") from error
    if not isinstance(payload, dict) or frozenset(payload) not in (
        _CURSOR_KEYS,
        _CURSOR_KEYS | {"x"},
    ):
        raise InvalidCompanyCursor("invalid company cursor")
    if payload["v"] != _CURSOR_VERSION or not isinstance(payload["k"], str):
        raise InvalidCompanyCursor("invalid company cursor")
    raw_date = payload["d"]
    if raw_date is not None and not isinstance(raw_date, str):
        raise InvalidCompanyCursor("invalid company cursor")
    try:
        parsed_date = None if raw_date is None else dt.date.fromisoformat(raw_date)
        extra = payload.get("x")
        if extra is None:
            return CompanyCursor(date=parsed_date, company_key=payload["k"])
        if not isinstance(extra, dict) or set(extra) != {"f", "s", "a", "u"}:
            raise ValueError("invalid cursor context")
        amount = None if extra["a"] is None else Decimal(extra["a"])
        if amount is not None and (not amount.is_finite() or amount < 0):
            raise ValueError("invalid amount")
        if extra["s"] not in ("recent", "amount") or (
            extra["f"] is not None
            and (not isinstance(extra["f"], str) or not re.fullmatch(r"[a-f0-9]{24}", extra["f"]))
        ):
            raise ValueError("invalid cursor context")
        if extra["u"] is not None and not re.fullmatch(r"[A-Z]{3}", extra["u"]):
            raise ValueError("invalid currency")
        return CompanyCursor(
            date=parsed_date,
            company_key=payload["k"],
            context_tag=extra["f"],
            sort=extra["s"],
            amount=amount,
            currency=extra["u"],
        )
    except (TypeError, ValueError, InvalidOperation) as error:
        raise InvalidCompanyCursor("invalid company cursor") from error


@dataclasses.dataclass(frozen=True)
class CompanyRow:
    """Une entreprise, agrégée sur ses signaux accessibles à cette lecture."""

    company_key: str
    name: str
    city: str | None
    country: str | None
    awards_count: int
    #: Un `(devise, somme)` par devise portée, trié par devise.
    total_amount: tuple[tuple[str, Decimal], ...]
    last_award_at: dt.date | None
    contact_status: str
    contacted_at: dt.datetime | None
    top_fit: str
    #: Fix round 2 (F4) — la clé du signal qui a fourni `last_award_at`.
    #: L'agrégation la connaît déjà ; sans elle, un appelant qui veut « le
    #: dernier signal de cette entreprise » doit rebalayer l'entreprise entière,
    #: une fois par entreprise. `None` seulement si aucun signal n'a été absorbé.
    last_signal_key: str | None = None
    tracked: bool = False
    origin: str = "signal"


@dataclasses.dataclass(frozen=True)
class CompanyPage:
    rows: tuple[CompanyRow, ...]
    limit: int
    cursor: str | None
    next_cursor: str | None
    has_more: bool
    scan_truncated: bool
    counts: dict[str, int] = dataclasses.field(default_factory=dict)
    total: int = 0


def _sort_key(row: CompanyRow) -> tuple[int, int, str]:
    """`last_award_at` décroissant, nulls en dernier, puis `company_key`."""
    if row.last_award_at is None:
        return (1, 0, row.company_key)
    return (0, -row.last_award_at.toordinal(), row.company_key)


def _cursor_key(cursor: CompanyCursor) -> tuple[int, int, str]:
    if cursor.date is None:
        return (1, 0, cursor.company_key)
    return (0, -cursor.date.toordinal(), cursor.company_key)


@dataclasses.dataclass
class _Accumulator:
    awards_count: int = 0
    amounts: dict[str, Decimal] = dataclasses.field(default_factory=dict)
    last_award_at: dt.date | None = None
    #: Rang de comparaison du signal le plus récent retenu jusqu'ici — une date
    #: connue l'emporte toujours sur son absence, quel que soit l'ordre de
    #: balayage. `None` tant qu'AUCUN signal n'a été absorbé : fix round 2 (F5d)
    #: — le distinguer du rang `(0, 0)` d'un signal SANS date effective est ce
    #: qui rend `city` déterministe. Tester `last_award_at is None` retenait le
    #: DERNIER signal sans date rencontré, donc une commune qui changeait avec
    #: l'ordre de balayage ; le premier rencontré gagne désormais.
    last_award_rank: tuple[int, int] | None = None
    city: str | None = None
    last_signal_key: str | None = None
    top_fit_rank: int = 0

    def absorb(self, signal: StoredSignal) -> None:
        self.awards_count += 1
        if signal.award.amount is not None and signal.award.currency is not None:
            self.amounts[signal.award.currency] = (
                self.amounts.get(signal.award.currency, Decimal(0)) + signal.award.amount
            )
        date, _kind = effective_history_date(signal)
        rank = (1, date.toordinal()) if date is not None else (0, 0)
        if self.last_award_rank is None or rank > self.last_award_rank:
            self.last_award_rank = rank
            self.last_award_at = date
            self.last_signal_key = signal.signal_key
            place = signal.award.place_of_performance or {}
            self.city = place.get("locality")
        fit_rank = _FIT_RANK[fit_band(signal.icp_match_band)]
        self.top_fit_rank = max(self.top_fit_rank, fit_rank)


def _scan_accessible_signals(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str] | None,
    access: FeedAccess,
    consultation_scope=None,
) -> tuple[list[StoredSignal], bool]:
    """Les signaux DÉBLOQUÉS du compte, dans la même portée que `view=history`.

    Le plafond borne les lignes LUES en base, pas les signaux retenus après
    déverrouillage : un signal verrouillé consomme donc bel et bien du budget
    de balayage — c'est le prix d'un plafond qui borne le COÛT de la lecture,
    et non son rendement (fix round 2, F5d : le commentaire d'origine
    prétendait l'inverse).

    Fix round 2 (F5) — le balayage garde l'ordre de `_ownership_scoped`
    (`materialized_at DESC, signal_key ASC`) et son curseur à deux colonnes.
    Trier par `signal_key` seul faisait tomber, à la troncature, des lignes
    tirées au hasard d'un identifiant opaque ; l'ordre de matérialisation fait
    tomber les PLUS ANCIENNES, comme partout ailleurs dans le feed.

    Fix round 2 (F6) — le plafond est relu à chaque appel
    (`feed_query.HISTORY_SCAN_CAP`) : le lier à l'import le figeait, et un
    plafond qu'on ne peut plus changer est un plafond qu'on ne peut plus tester.
    """
    owned = owned_target_icps(connection, account_id=account_id)
    if not any(profile.status == FEEDING_ICP_STATUS for profile in owned.values()):
        return [], False
    if allowed_target_icp_ids is not None and not allowed_target_icp_ids:
        return [], False

    query = _ownership_scoped(account_id)
    if allowed_target_icp_ids is not None:
        query = query.where(materialized_signal.c.target_icp_id.in_(sorted(allowed_target_icp_ids)))
    if not access.is_paid:
        # Un compte Découverte possède quelques clés explicites. Les chercher
        # directement évite qu'un grand profil fasse tomber ses cadeaux hors
        # du plafond avant même que `is_unlocked` puisse les reconnaître.
        query = query.where(materialized_signal.c.signal_key.in_(sorted(access.granted)))

    scan_cap = (
        max(feed_query.HISTORY_SCAN_CAP, len(access.granted))
        if not access.is_paid
        else feed_query.HISTORY_SCAN_CAP
    )
    scanned = 0
    accessible: list[StoredSignal] = []
    last_at: dt.datetime | None = None
    last_key: str | None = None
    exhausted = False
    while scanned < scan_cap:
        batch_query = query
        if last_key is not None:
            batch_query = batch_query.where(
                sa.or_(
                    materialized_signal.c.materialized_at < last_at,
                    sa.and_(
                        materialized_signal.c.materialized_at == last_at,
                        materialized_signal.c.signal_key > last_key,
                    ),
                )
            )
        batch_limit = min(_SCAN_BATCH, scan_cap - scanned)
        rows = connection.execute(batch_query.limit(batch_limit)).all()
        if not rows:
            exhausted = True
            break
        last_at = rows[-1].materialized_at
        last_key = rows[-1].signal_key
        scanned += len(rows)
        for row in rows:
            signal = signal_from_row(row)
            profile = owned[signal.target_icp_id]
            item = FeedSignal(
                signal=signal,
                recency=signal.current_recency(as_of=as_of),
                account_id=account_id,
                target_icp_label=profile.label,
            )
            if access.is_unlocked(item) and (
                consultation_scope is None or consultation_scope.matches(signal)
            ):
                accessible.append(signal)
        if len(rows) < batch_limit:
            exhausted = True
            break
    return accessible, not exhausted


def list_companies(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str] | None,
    access: FeedAccess,
    contact_statuses: frozenset[str] | None,
    #: Fix round 1 (I3) — filtre AVANT le tri/la pagination, comme
    #: `contact_statuses` : une entreprise sans `contacted_at`, ou contactée
    #: APRÈS cette date, n'est jamais candidate — ce n'est pas une page qui
    #: manquerait de place pour elle.
    contacted_before: dt.datetime | None,
    query: str | None,
    limit: int,
    cursor: str | None,
    now: dt.datetime,
    consultation_scope=None,
    sort: str = "recent",
    context_tag: str | None = None,
) -> CompanyPage:
    decoded_cursor = None if cursor is None else decode_company_cursor(cursor)
    if decoded_cursor is not None and (
        (decoded_cursor.context_tag is not None and decoded_cursor.context_tag != context_tag)
        or decoded_cursor.sort != sort
    ):
        raise InvalidCompanyCursor("cursor belongs to another consultation")

    signals, scan_truncated = _scan_accessible_signals(
        connection,
        account_id=account_id,
        as_of=as_of,
        allowed_target_icp_ids=allowed_target_icp_ids,
        access=access,
        consultation_scope=consultation_scope,
    )

    ensure_companies_for_signal_keys(
        connection,
        signal_keys=tuple(signal.signal_key for signal in signals),
        now=now,
    )
    company_keys = company_keys_for_signals(
        connection, signal_keys=tuple(signal.signal_key for signal in signals)
    )
    # Read private reconciliation in batches. A list never copies/deletes notes.
    membership_rows = connection.execute(
        sa.select(account_company_membership).where(
            account_company_membership.c.account_id == account_id,
        )
    ).all()
    private_rows = [
        (
            fields,
            list(
                connection.execute(
                    sa.select(table).where(table.c.account_id == account_id)
                ).mappings()
            ),
        )
        for table, fields in (
            (company_note, ("body",)),
            (company_contact, ("status", "contacted_at")),
            (company_manual_contact, ("name", "role", "email", "phone", "deleted_at")),
        )
    ]
    relevant_keys = set(company_keys.values()) | {row.company_key for row in membership_rows}
    relevant_keys.update(row["company_key"] for _fields, rows in private_rows for row in rows)
    bindings = {
        row.alias_company_key: row
        for row in connection.execute(
            sa.select(company_subject_alias).where(
                company_subject_alias.c.alias_company_key.in_(relevant_keys),
            )
        )
    }
    quarantined = {key for key, row in bindings.items() if row.resolution_status != "exact"}
    public = {
        key: row.canonical_company_key for key, row in bindings.items() if key not in quarantined
    }
    for row in connection.execute(
        sa.select(saas_company).where(saas_company.c.company_key.in_(relevant_keys))
    ).mappings():
        siren = exact_french_siren(row["official_identifiers"], country=row["official_country"])
        if siren and row["company_key"] not in quarantined:
            key = row["company_key"]
            canonical = f"cmp_directory_{siren}"
            if key in public and public[key] != canonical:
                quarantined.add(key)
                public.pop(key)
            else:
                public.setdefault(key, canonical)
    overrides = {
        row.alias_company_key: row.private_subject_key
        for row in connection.execute(
            sa.select(account_company_alias_override).where(
                account_company_alias_override.c.account_id == account_id
            )
        )
        if row.alias_company_key not in quarantined
    }
    conflicts = set()
    for fields, rows in private_rows:
        values = {}
        for row in rows:
            key = row["company_key"]
            if key in overrides and overrides[key] != key:
                continue
            canonical = public.get(key, key)
            values.setdefault(canonical, set()).add(tuple(row[field] for field in fields))
        conflicts.update(key for key, states in values.items() if len(states) > 1)

    def subject(key):
        if key in quarantined:
            return key
        canonical = public.get(key, key)
        return overrides.get(key, key if canonical in conflicts else canonical)

    memberships = {subject(row.company_key): row.origin for row in membership_rows}

    accumulators: dict[str, _Accumulator] = {}
    for signal in signals:
        company_key = company_keys.get(signal.signal_key)
        if company_key is None:
            continue
        accumulators.setdefault(subject(company_key), _Accumulator()).absorb(signal)
    for key in memberships:
        accumulators.setdefault(key, _Accumulator())

    identities: dict[str, sa.Row] = {}
    raw_search_names: dict[str, set[str]] = {}
    if accumulators:
        rows = connection.execute(
            sa.select(
                saas_company.c.company_key,
                saas_company.c.official_name,
                saas_company.c.official_country,
            ).where(
                saas_company.c.company_key.in_(
                    sorted(set(accumulators) | set(company_keys.values()))
                )
            )
        ).all()
        for row in rows:
            company_subject = subject(row.company_key)
            identities[company_subject] = row
            raw_search_names.setdefault(company_subject, set()).add(row.official_name)
    directory = (
        {
            f"cmp_directory_{row.siren}": row
            for row in connection.execute(
                sa.select(
                    supplier_directory.c.siren,
                    supplier_directory.c.legal_name,
                    supplier_directory.c.city,
                ).where(
                    supplier_directory.c.siren.in_(
                        [
                            key.removeprefix("cmp_directory_")
                            for key in accumulators
                            if key.startswith("cmp_directory_")
                        ]
                    )
                )
            )
        }
        if accumulators
        else {}
    )
    for company_key, directory_identity in directory.items():
        raw_search_names.setdefault(company_key, set()).add(directory_identity.legal_name)

    contacts = {}
    stored_contacts = contacts_by_company(connection, account_id=account_id)
    for key in sorted(stored_contacts, key=lambda key: (key == subject(key), key)):
        contacts[subject(key)] = stored_contacts[key]

    rows: list[CompanyRow] = []
    for company_key, acc in accumulators.items():
        identity = identities.get(company_key)
        directory_identity = directory.get(company_key)
        if identity is None and directory_identity is None:
            # Une entreprise projetée mais pas (encore) lisible n'a rien à
            # afficher — ne devrait pas arriver (clé FK), mais ne fabrique rien.
            continue
        contact = contacts.get(company_key)
        rows.append(
            CompanyRow(
                company_key=company_key,
                name=normalize_holder_name(
                    identity.official_name
                    if identity is not None
                    else directory_identity.legal_name
                ),
                city=acc.city
                or (directory_identity.city if directory_identity is not None else None),
                country=identity.official_country if identity is not None else "FR",
                awards_count=acc.awards_count,
                total_amount=tuple(sorted(acc.amounts.items())),
                last_award_at=acc.last_award_at,
                contact_status=contact.status if contact is not None else "to_contact",
                contacted_at=contact.contacted_at if contact is not None else None,
                top_fit=_RANK_TO_FIT[acc.top_fit_rank],
                last_signal_key=acc.last_signal_key,
                tracked=company_key in memberships,
                origin=memberships.get(company_key, "signal"),
            )
        )

    if query:
        needle = normalize_text(query)
        rows = [
            row
            for row in rows
            if needle in normalize_text(row.name)
            or any(
                needle in normalize_text(raw_name)
                for raw_name in raw_search_names.get(row.company_key, ())
            )
        ]
    if contacted_before is not None:
        rows = [
            row
            for row in rows
            if row.contacted_at is not None and row.contacted_at <= contacted_before
        ]

    counts = {
        status: sum(row.contact_status == status for row in rows)
        for status in ("to_contact", "contacted", "replied")
    }
    total = len(rows)
    if contact_statuses is not None:
        rows = [row for row in rows if row.contact_status in contact_statuses]

    def ordering(row):
        if sort != "amount":
            return _sort_key(row)
        if not row.total_amount:
            return (1, "", Decimal(0), row.company_key)
        currency, amount = row.total_amount[0]
        return (0, currency, -amount, row.company_key)

    rows.sort(key=ordering)

    if decoded_cursor is not None:
        cursor_key = (
            _cursor_key(decoded_cursor)
            if sort != "amount"
            else (
                (1, "", Decimal(0), decoded_cursor.company_key)
                if decoded_cursor.amount is None
                else (
                    0,
                    decoded_cursor.currency,
                    -decoded_cursor.amount,
                    decoded_cursor.company_key,
                )
            )
        )
        rows = [row for row in rows if ordering(row) > cursor_key]

    page = rows[:limit]
    has_more = len(rows) > limit
    next_cursor = (
        encode_company_cursor(
            CompanyCursor(
                date=page[-1].last_award_at,
                company_key=page[-1].company_key,
                context_tag=context_tag,
                sort=sort,
                currency=page[-1].total_amount[0][0] if page[-1].total_amount else None,
                amount=page[-1].total_amount[0][1] if page[-1].total_amount else None,
            )
        )
        if has_more
        else None
    )

    return CompanyPage(
        rows=tuple(page),
        limit=limit,
        cursor=cursor,
        next_cursor=next_cursor,
        has_more=has_more,
        scan_truncated=scan_truncated,
        counts=counts,
        total=total,
    )


__all__ = [
    "CompanyCursor",
    "CompanyPage",
    "CompanyRow",
    "InvalidCompanyCursor",
    "decode_company_cursor",
    "encode_company_cursor",
    "list_companies",
]
