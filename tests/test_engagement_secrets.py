"""SPEC-014 §39 — aucun secret d'e-mail ne doit entrer dans le dépôt.

Un mot de passe SMTP committé reste dans l'historique git même après
suppression : le changer devient la seule issue, et il faut d'abord s'apercevoir
qu'il est là. Le balayage le refuse au moment où il apparaît.

Le motif reste **étroit** : un nom d'hôte d'exemple (`smtp.example.com`) ou une
adresse d'expéditeur ne sont pas des secrets, et un scanner qui crie au loup
finit par être désactivé.
"""

from __future__ import annotations

import pathlib
import re

REPOSITORY = pathlib.Path(__file__).resolve().parents[1]

#: Une affectation de secret. Les motifs sont **sensibles à la casse** et visent
#: la forme majuscule : c'est celle des fichiers `.env`, des `export` shell et
#: des fichiers de configuration — là où une fuite réelle se produit. Une
#: lecture d'environnement (`os.environ.get(...)`) et un `None` sont exclus :
#: ce sont précisément les formes correctes.
_VALUE = r"(?!os\.|None|\$|\{|\\)[^\s\"']"

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"SMTP_PASSWORD\s*[:=]\s*[\"']?{_VALUE}{{6,}}"),
    re.compile(rf"MAIL(?:GUN|JET)?_API_KEY\s*[:=]\s*[\"']?{_VALUE}{{12,}}"),
    re.compile(r"SENDGRID_API_KEY\s*[:=]\s*[\"']?SG\.[A-Za-z0-9_\-]{10,}"),
    re.compile(rf"POSTMARK_(?:SERVER_)?TOKEN\s*[:=]\s*[\"']?{_VALUE}{{16,}}"),
    re.compile(r"\bkey-[0-9a-f]{32}\b"),
)

SCANNED_PATHS: tuple[str, ...] = (
    "src/signals/alerts",
    "src/signals/engagement",
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
    return [match for pattern in SECRET_PATTERNS for match in pattern.findall(text)]


def test_no_mail_secret_is_committed_anywhere_in_the_scanned_files():
    offenders: dict[str, str] = {}
    for path in scanned_files():
        found = findings(path.read_text(encoding="utf-8", errors="ignore"))
        if found:
            # Le chemin suffit à agir ; recopier la valeur la ferait entrer
            # dans les journaux d'intégration continue.
            offenders[str(path.relative_to(REPOSITORY))] = f"{len(found)} occurrence(s)"
    assert offenders == {}, offenders


def test_the_scan_can_actually_fail():
    """Un garde-fou qui ne peut pas échouer ne garde rien.

    Les témoins sont assemblés à l'exécution : écrits en clair, ils feraient
    échouer le balayage sur CE fichier.
    """
    assert findings("SMTP_" + "PASSWORD=" + "un-mot-de-passe-smtp")
    assert findings("POSTMARK_" + "SERVER_TOKEN=" + "abcdefghij0123456789")
    assert findings("SENDGRID_" + "API_KEY=" + "SG.abcdefghij0123456789")
    assert findings("MAILGUN_" + "API_KEY=" + "abcdefghijklmnop0123")


def test_ordinary_hostnames_and_addresses_are_not_treated_as_secrets():
    """§39 — un scanner trop large finit désactivé."""
    assert findings("SMTP_HOST=smtp.example.com") == []
    assert findings("SMTP_FROM_EMAIL=alertes@kivou.ch") == []
    assert findings("SMTP_PORT=587") == []
    assert findings("smtp_password: str | None = None") == []
    assert findings("SMTP_PASSWORD=os.environ.get('SMTP_PASSWORD')") == []
    assert findings("SMTP_PASSWORD=${SMTP_PASSWORD}") == []


def test_the_scan_covers_the_alert_code_and_the_configuration():
    scanned = {str(path.relative_to(REPOSITORY)) for path in scanned_files()}
    assert "src/signals/alerts/gateway.py" in scanned
    assert "src/signals/api/config.py" in scanned
    assert "pyproject.toml" in scanned


def test_the_delivery_table_stores_no_credential_and_no_address():
    """§27 — un code d'erreur, jamais une trace ni un identifiant."""
    from signals.engagement.schema import signal_alert_delivery

    columns = {column.name for column in signal_alert_delivery.columns}
    context = signal_alert_delivery.c.recipient_context_fingerprint
    assert context.type.length == 64
    assert context.name.endswith("_fingerprint")
    columns.remove(context.name)
    for forbidden in ("password", "credential", "smtp", "recipient", "email", "trace", "stack"):
        assert not any(forbidden in name for name in columns), forbidden
    assert "last_error_code" in columns


def test_the_transactional_runtime_tables_store_no_private_mail_data():
    from signals.engagement.schema import signal_alert_delivery, signal_alert_job_lease

    forbidden = (
        "password",
        "credential",
        "smtp",
        "recipient",
        "email",
        "token",
        "trace",
        "stack",
        "body",
        "raw_payload",
    )
    for table in (signal_alert_delivery, signal_alert_job_lease):
        columns = {column.name for column in table.columns}
        if table is signal_alert_delivery:
            # Hash only: the address and the inputs used to bind eligibility
            # remain outside this table and outside operational logs.
            columns.remove("recipient_context_fingerprint")
        for marker in forbidden:
            assert not any(marker in name for name in columns), (table.name, marker)


def test_no_smtp_secret_is_ever_rendered_by_the_api(tmp_path):
    """La configuration porte le mot de passe ; aucune réponse ne le montre."""
    from engagement_helpers import Clock, icp_of, make_app, make_engine, signed_up

    engine = make_engine(tmp_path)
    # Assemblé à l'exécution : écrit en clair, il ferait échouer le balayage
    # sur ce fichier même (§39).
    placeholder = "un-" + "secret-" + "de-test"
    app = make_app(engine, Clock(), smtp_host="smtp.example.com", smtp_password=placeholder)
    client = signed_up(app)
    icp_of(client)

    body = (
        client.get("/me").text
        + client.get("/billing/status").text
        + client.get("/notification-preferences").text
        + client.get("/signals").text
    )
    assert placeholder not in body
    assert "smtp" not in body.lower()
