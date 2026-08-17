"""SPIKE Achatpublic — ce que la requête de retrait contient, et ne contient pas.

Le point vérifié ici est celui qui a coûté un faux diagnostic : les trois champs
de contact sont bien envoyés, mais **vides**. Un test qui les verrait remplis
signalerait qu'une identité a été fabriquée quelque part.
"""

from __future__ import annotations

from signals.research.achatpublic_dce import (
    EMPTY_IDENTITY,
    DceAttempt,
    dce_id_from_page,
    download_request,
    is_zip,
    pcslid_from_url,
)

PAGE = (
    '<html><body><div id="detailsDce_383958044" class="sdmDce"></div>'
    '<a onclick="submitFormeDownload(383958044)">Télécharger</a></body></html>'
)


class TestIdentifiersAreReadFromThePage:
    def test_the_consultation_id_comes_from_the_url(self) -> None:
        url = "https://www.achatpublic.com/sdm/ent/gen/ent_detail.do?PCSLID=CSL_2026_4644hBiweX"
        assert pcslid_from_url(url) == "CSL_2026_4644hBiweX"

    def test_a_url_without_consultation_id_yields_none(self) -> None:
        assert pcslid_from_url("https://www.achatpublic.com/") is None

    def test_the_dce_id_is_read_from_the_detail_block(self) -> None:
        assert dce_id_from_page(PAGE) == "383958044"

    def test_an_absent_dce_block_yields_none(self) -> None:
        assert dce_id_from_page("<html><body>rien</body></html>") is None


class TestTheRequestCarriesNoIdentity:
    def test_the_three_contact_fields_are_sent_empty(self) -> None:
        """C'est le cœur du chemin anonyme : présents, vides, acceptés."""
        _, body = download_request("CSL_2026_X", "383958044")
        for field in ("nomEntiteContact", "nomPointContact", "mailPointContact"):
            assert field in body
            assert body[field] == ""

    def test_no_identity_value_is_ever_configured(self) -> None:
        """Une valeur non vide ici serait une fausse déclaration."""
        assert set(EMPTY_IDENTITY.values()) == {""}

    def test_the_body_carries_only_the_published_identifiers(self) -> None:
        _, body = download_request("CSL_2026_X", "383958044")
        assert body["PCSLID"] == "CSL_2026_X"
        assert body["dceId"] == "383958044"
        assert body["cycNum"] == "0"

    def test_the_endpoint_is_the_public_download_action(self) -> None:
        url, _ = download_request("CSL_2026_X", "1")
        assert url.startswith("https://www.achatpublic.com/sdm/ent2/gen/telechargerDCE.action")
        assert "PCSLID=CSL_2026_X" in url

    def test_no_credential_appears_anywhere_in_the_request(self) -> None:
        url, body = download_request("CSL_2026_X", "1")
        blob = (url + str(body)).lower()
        for marker in ("password", "login", "token", "session", "captcha"):
            assert marker not in blob


class TestArchiveRecognition:
    def test_a_zip_signature_is_recognised(self) -> None:
        assert is_zip(b"PK\x03\x04rest") is True

    def test_a_pdf_is_not_an_archive(self) -> None:
        assert is_zip(b"%PDF-1.7") is False

    def test_an_empty_payload_is_not_an_archive(self) -> None:
        assert is_zip(b"") is False


class TestAttemptReporting:
    def test_an_empty_attempt_has_not_succeeded(self) -> None:
        assert DceAttempt(pcslid="X").succeeded is False

    def test_a_download_of_zero_bytes_is_not_a_success(self) -> None:
        """Un 200 vide est un échec, pas un DCE."""
        attempt = DceAttempt(pcslid="X", download_status=200, byte_size=0)
        assert attempt.succeeded is False

    def test_a_real_download_is_a_success(self) -> None:
        attempt = DceAttempt(pcslid="X", download_status=200, byte_size=4096)
        assert attempt.succeeded is True
