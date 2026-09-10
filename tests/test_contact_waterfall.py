from __future__ import annotations

import datetime as dt

import httpx

from signals.contact_discovery.deliverability import EmailDeliverabilityVerifier
from signals.contact_discovery.profile import build_decision_maker_profile
from signals.contact_discovery.providers import (
    OpenRouterPublishedContactExtractor,
    coherent_email_domain,
)
from signals.contact_discovery.web import (
    AnnuaireDirectorClient,
    CompanyWebsiteClient,
    OfficialDirector,
    PublishedWebsiteContactProvider,
    WebsiteEvidence,
)

NOW = dt.datetime(2026, 9, 10, 12, tzinfo=dt.UTC)


def _profile():
    return build_decision_maker_profile(
        acquisition_opportunity_id="opp-1",
        supplier_ref="supplier-1",
        provider_organization_id="siren-123456789",
        supplier_siren="123456789",
        binding_resolution_method="serper",
        organization_name="BETON ALPES",
        organization_city="Lyon",
        organization_domain="beton-alpes.fr",
    )


def test_model_extraction_is_strict_and_must_select_published_email() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat/completions"
        payload = __import__("json").loads(request.content)
        assert payload["max_tokens"] == 1000
        schema = payload["response_format"]["json_schema"]["schema"]
        assert set(schema["required"]) == {"email", "dirigeant", "confiance"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"email":"alice@beton-alpes.fr",'
                                '"dirigeant":"Alice Martin","confiance":0.98}'
                            )
                        }
                    }
                ]
            },
        )

    extractor = OpenRouterPublishedContactExtractor(
        api_key="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = extractor.extract(
        company_name="BETON ALPES",
        directors=(OfficialDirector(name="Alice Martin", title="Gérante"),),
        evidence=(
            WebsiteEvidence(
                url="https://beton-alpes.fr/contact",
                text="Contactez notre équipe.",
                published_emails=("alice@beton-alpes.fr",),
            ),
        ),
    )

    assert result is not None
    assert result.dirigeant == "Alice Martin"
    assert result.email == "alice@beton-alpes.fr"


def test_model_extraction_rejects_invented_email() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"email":"invented@beton-alpes.fr",'
                                    '"dirigeant":"Alice Martin","confiance":0.50}'
                                )
                            }
                        }
                    ]
                },
            )
        )
    )
    result = OpenRouterPublishedContactExtractor(api_key="test", client=client).extract(
        company_name="BETON ALPES",
        directors=(OfficialDirector(name="Alice Martin", title="Gérante"),),
        evidence=(
            WebsiteEvidence(
                url="https://beton-alpes.fr/contact",
                text="Contact",
                published_emails=("contact@beton-alpes.fr",),
            ),
        ),
    )

    assert result is None


def test_website_level_accepts_generic_mailbox_only_with_named_director() -> None:
    class Directors:
        def find(self, _siren):
            return (OfficialDirector(name="Alice Martin", title="Gérante", first_name="Alice"),)

    class Pages:
        def fetch(self, _domain):
            return (
                WebsiteEvidence(
                    url="https://beton-alpes.fr/contact",
                    text="Alice Martin, gérante",
                    published_emails=("contact@beton-alpes.fr",),
                ),
            )

    class Extractor:
        def extract(self, **_kwargs):
            from signals.contact_discovery.providers import PublishedContactExtraction

            return PublishedContactExtraction(
                email="contact@beton-alpes.fr",
                dirigeant="Alice Martin",
                confiance=0.95,
            )

    class Deliverability:
        def verify(self, email):
            assert email == "contact@beton-alpes.fr"
            return True

    contact = PublishedWebsiteContactProvider(
        directors=Directors(),
        pages=Pages(),
        extractor=Extractor(),
        deliverability=Deliverability(),
    ).find(_profile(), observed_at=NOW)

    assert contact is not None
    assert contact.provider == "company_website"
    assert contact.first_name == "Alice"
    assert contact.display_name == "Alice Martin"
    assert contact.business_email == "contact@beton-alpes.fr"
    assert contact.verification_state == "DELIVERABILITY_VERIFIED"


def test_website_extracts_text_email_after_mailto_addresses() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                '<a href="mailto:direction@beton-alpes.fr">Direction</a>'
                "<p>Écrivez aussi à contact@beton-alpes.fr.</p>"
                '<form action="/contact"><input name="message"></form>'
            ),
        )

    pages = CompanyWebsiteClient(
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    ).fetch("beton-alpes.fr")

    assert pages[0].published_emails == (
        "direction@beton-alpes.fr",
        "contact@beton-alpes.fr",
    )
    assert pages[0].has_contact_form is True


def test_registry_keeps_operational_directors_and_rejects_auditors() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "dirigeants": [
                            {
                                "prenoms": "Alice",
                                "nom": "Martin",
                                "qualite": "Gérante",
                                "type_dirigeant": "personne physique",
                            },
                            {
                                "prenoms": "Zoé",
                                "nom": "Petit",
                                "qualite": "Cogérante",
                                "type_dirigeant": "personne physique",
                            },
                            {
                                "denomination": "HOLDING ALPES",
                                "qualite": "Président de SAS",
                                "type_dirigeant": "personne morale",
                            },
                            {
                                "prenoms": "Léa",
                                "nom": "Bernard",
                                "qualite": "Directrice Générale Déléguée",
                                "type_dirigeant": "personne physique",
                            },
                            {
                                "prenoms": "Lou",
                                "nom": "Robert",
                                "qualite": "Présidente du conseil",
                                "type_dirigeant": "personne physique",
                            },
                            {
                                "prenoms": "Sam",
                                "nom": "Richard",
                                "qualite": "Personne physique dirigeante",
                                "type_dirigeant": "personne physique",
                            },
                            {
                                "prenoms": "Noé",
                                "nom": "Roux",
                                "qualite": "Associé gérant",
                                "type_dirigeant": "personne physique",
                            },
                            {
                                "prenoms": "Marc",
                                "nom": "Audit",
                                "qualite": "Commissaire aux comptes suppléant",
                                "type_dirigeant": "personne physique",
                            },
                            {
                                "prenoms": "Jean",
                                "nom": "Sans Pouvoir",
                                "qualite": "Représentant",
                                "type_dirigeant": "personne physique",
                            },
                        ]
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    directors = AnnuaireDirectorClient(client=client).find("123456789")

    assert requests[0].url.params["minimal"] == "true"
    assert requests[0].url.params["include"] == "dirigeants"
    assert [(item.name, item.title, item.entity_type) for item in directors] == [
        ("Alice Martin", "Gérante", "personne physique"),
        ("Zoé Petit", "Cogérante", "personne physique"),
        ("HOLDING ALPES", "Président de SAS", "personne morale"),
        ("Léa Bernard", "Directrice Générale Déléguée", "personne physique"),
        ("Lou Robert", "Présidente du conseil", "personne physique"),
        ("Sam Richard", "Personne physique dirigeante", "personne physique"),
        ("Noé Roux", "Associé gérant", "personne physique"),
    ]


def test_website_accepts_verified_email_without_named_director() -> None:
    class Directors:
        def find(self, _siren):
            return ()

    class Pages:
        def fetch(self, _domain):
            return (
                WebsiteEvidence(
                    url="https://beton-alpes.fr/contact",
                    text="Contactez BETON ALPES à contact@beton-alpes.fr",
                    published_emails=("contact@beton-alpes.fr",),
                ),
            )

    class NoModel:
        def extract(self, **_kwargs):
            raise AssertionError("a published address does not require the model")

    class Deliverability:
        def verify(self, _email):
            return True

    contact = PublishedWebsiteContactProvider(
        directors=Directors(), pages=Pages(), extractor=NoModel(), deliverability=Deliverability()
    ).find(_profile(), observed_at=NOW)

    assert contact is not None
    assert contact.first_name is None
    assert contact.display_name == "BETON ALPES"
    assert contact.business_email == "contact@beton-alpes.fr"


def test_website_records_contact_form_without_published_email() -> None:
    recorded = []

    class Directors:
        def find(self, _siren):
            return ()

    class Pages:
        def fetch(self, _domain):
            return (
                WebsiteEvidence(
                    url="https://beton-alpes.fr/contact",
                    text="Formulaire de contact",
                    published_emails=(),
                    has_contact_form=True,
                ),
            )

    class Directory:
        def record_contact_form(self, siren, *, url, observed_at):
            recorded.append((siren, url, observed_at))

    contact = PublishedWebsiteContactProvider(
        directors=Directors(),
        pages=Pages(),
        extractor=object(),
        deliverability=object(),
        directory=Directory(),
    ).find(_profile(), observed_at=NOW)

    assert contact is None
    assert recorded == [("123456789", "https://beton-alpes.fr/contact", NOW)]


def test_website_does_not_record_third_party_contact_form() -> None:
    recorded = []

    class Directors:
        def find(self, _siren):
            return ()

    class Pages:
        def fetch(self, _domain):
            return (
                WebsiteEvidence(
                    url="https://fr.mappy.com/",
                    text="Formulaire de l'annuaire",
                    published_emails=(),
                    has_contact_form=True,
                ),
            )

    class Directory:
        def record_contact_form(self, siren, *, url, observed_at):
            recorded.append((siren, url, observed_at))

    assert (
        PublishedWebsiteContactProvider(
            directors=Directors(),
            pages=Pages(),
            extractor=object(),
            deliverability=object(),
            directory=Directory(),
        ).find(
            _profile().model_copy(update={"organization_domain": "fr.mappy.com"}),
            observed_at=NOW,
        )
        is None
    )
    assert recorded == []


def test_model_rejects_published_email_from_unrelated_domain() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"email":"mairie@certines.fr",'
                                    '"dirigeant":"Alice Martin","confiance":0.95}'
                                )
                            }
                        }
                    ]
                },
            )
        )
    )

    result = OpenRouterPublishedContactExtractor(api_key="test", client=client).extract(
        company_name="JACQUET",
        directors=(OfficialDirector(name="Alice Martin", title="Gérante"),),
        evidence=(
            WebsiteEvidence(
                url="https://jacquet.fr/contact",
                text="Contact mairie@certines.fr",
                published_emails=("mairie@certines.fr",),
            ),
        ),
    )

    assert result is None


def test_email_domain_must_exactly_match_validated_website_domain() -> None:
    evidence = (
        WebsiteEvidence(
            url="https://beton-alpes.fr/contact",
            text="Adresse publiée contact@beton-alpes.com",
            published_emails=("contact@beton-alpes.com",),
        ),
    )

    assert coherent_email_domain("contact@beton-alpes.com", evidence) is False


def test_deliverability_stops_after_rcpt_and_never_sends_data() -> None:
    events: list[str] = []

    class Resolver:
        def resolve(self, _domain, _record_type):
            class Mx:
                preference = 10
                exchange = "mx.example.test."

            return (Mx(),)

    class Smtp:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def ehlo(self):
            events.append("ehlo")

        def mail(self, _sender):
            events.append("mail")
            return 250, b"ok"

        def rcpt(self, _recipient):
            events.append("rcpt")
            return 250, b"ok"

        def data(self, *_args):
            raise AssertionError("SMTP DATA must never be used for verification")

    verifier = EmailDeliverabilityVerifier(
        resolver=Resolver(), smtp_factory=lambda *_args, **_kwargs: Smtp()
    )

    assert verifier.verify("alice@example.test") is True
    assert events == ["ehlo", "mail", "rcpt"]
