"""SPEC-013 §31 — aucun secret Stripe ne doit jamais entrer dans le dépôt.

    Pourquoi un test et pas une relecture
    ─────────────────────────────────────
    Une clé committée reste dans l'historique git même après suppression :
    la révoquer devient la seule issue, et il faut d'abord s'apercevoir qu'elle
    est là. Un test la refuse au moment où elle apparaît, c'est-à-dire au seul
    moment où c'est encore gratuit.

Le balayage porte sur les fichiers SPEC-013 — code, tests, rapports — plus la
configuration du projet. Il cherche des **préfixes de secret** ; les
identifiants d'objets Stripe (`prod_`, `price_`, `coupon_`) sont légitimes et
ne sont pas visés.
"""

from __future__ import annotations

import pathlib
import re

REPOSITORY = pathlib.Path(__file__).resolve().parents[1]

#: Les préfixes des secrets Stripe. `sk_` et `rk_` ouvrent l'API ; `whsec_`
#: permet de forger un webhook, donc d'accorder un abonnement à volonté.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk_(?:test|live)_[A-Za-z0-9]{8,}"),
    re.compile(r"rk_(?:test|live)_[A-Za-z0-9]{8,}"),
    re.compile(r"whsec_[A-Za-z0-9]{16,}"),
    re.compile(r"pk_live_[A-Za-z0-9]{8,}"),
)

#: Les valeurs fabriquées pour les tests. Elles ne déverrouillent rien et
#: n'existent que dans ce dépôt ; les exclure évite un test qui crie au loup.
KNOWN_TEST_FIXTURES: tuple[str, ...] = (
    "whsec_" + "0" * 32,
    "whsec_" + "9" * 32,
    "sk_" + "live_exemple_de_cle_qui_ne_doit_pas_passer",
    "sk_" + "test_exemple_de_cle_qui_ne_doit_pas_passer",
)

SCANNED_PATHS: tuple[str, ...] = (
    "src/signals/billing",
    "src/signals/api",
    "tests",
    "docs/reports",
    "pyproject.toml",
)

SCANNED_SUFFIXES = {".py", ".toml", ".md", ".ini", ".cfg", ".env", ".json", ".yaml", ".yml"}


def scanned_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for entry in SCANNED_PATHS:
        path = REPOSITORY / entry
        if path.is_file():
            files.append(path)
            continue
        files += [
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file()
            and candidate.suffix in SCANNED_SUFFIXES
            and "__pycache__" not in candidate.parts
        ]
    return files


def findings(text: str) -> list[str]:
    found: list[str] = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.findall(text):
            if match not in KNOWN_TEST_FIXTURES:
                found.append(match)
    return found


def test_no_stripe_secret_prefix_exists_anywhere_in_the_scanned_files():
    offenders: dict[str, list[str]] = {}
    for path in scanned_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        found = findings(text)
        if found:
            # Le chemin suffit à agir ; recopier la clé dans un message d'échec
            # la ferait entrer dans les journaux de CI.
            offenders[str(path.relative_to(REPOSITORY))] = [f"{len(found)} occurrence(s)"]
    assert offenders == {}, offenders


def test_the_scan_actually_detects_a_secret_when_one_is_present():
    """Un garde-fou qui ne peut pas échouer ne garde rien.

    Les témoins sont assemblés à l'exécution : les écrire en clair ferait
    échouer le balayage sur CE fichier, et un test qui doit s'auto-exclure
    finit toujours par exclure autre chose.
    """
    body = "51QabcdefGHIJKLmnopqrstuv"
    assert findings("STRIPE_SECRET_KEY=" + "sk_" + "test_" + body)
    assert findings("sk_" + "live_" + body)
    assert findings("rk_" + "test_" + body)
    assert findings("whsec" + "_abcdefghijklmnopqrstuvwxyz012345")


def test_stripe_object_identifiers_are_not_treated_as_secrets():
    """`prod_`, `price_` et `coupon_` sont publiables : §31 les autorise."""
    assert findings("prod_Sabcdef12345 price_1Qabcdef coupon_XyZ123") == []


def test_the_scan_covers_the_billing_code_the_tests_and_the_reports():
    scanned = {str(path.relative_to(REPOSITORY)) for path in scanned_files()}
    assert "src/signals/billing/service.py" in scanned
    assert "src/signals/api/routes_webhooks.py" in scanned
    assert "tests/billing_helpers.py" in scanned
    assert "pyproject.toml" in scanned


def test_no_secret_is_ever_written_into_the_database_schema():
    """§8 — la table d'événements garde une empreinte, jamais la charge."""
    from signals.billing.schema import stripe_webhook_event

    columns = {column.name for column in stripe_webhook_event.columns}
    assert "payload_hash" in columns
    # `payload_hash` est l'empreinte, et c'est précisément ce qu'on veut : elle
    # trace sans rien divulguer. Tout le reste est interdit.
    suspicious = columns - {"payload_hash"}
    for forbidden in ("payload", "raw", "secret", "signature", "api_key", "token"):
        assert not any(forbidden in name for name in suspicious), forbidden


def test_no_card_or_payment_method_is_ever_stored():
    """§8 — les données de paiement restent chez Stripe."""
    from signals.billing.schema import BILLING_TABLES

    columns = {column.name for table in BILLING_TABLES for column in table.columns}
    for forbidden in ("card", "pan", "cvc", "iban", "payment_method", "last4", "expiry"):
        assert not any(forbidden in name for name in columns), forbidden
