"""MICRO-SPIKE — ce que la lecture d'une page publique a le droit de conclure.

Le spike doit distinguer trois obstacles que le fetcher SPEC-006 confondait tous
en `external` : contenu injecté en JavaScript, formulaire d'identité, et absence
réelle de documents. Ces tests fixent cette distinction — et surtout la règle
qui interdit de franchir le second.
"""

from __future__ import annotations

from signals.research.fr_portal_spike import analyse, platform_of

PLACE_SEARCH = (
    "<html><body><!--Debut Bloc de Resultat--> <!--Fin Bloc de Resultat-->"
    + "x" * 3000
    + "</body></html>"
)
ACHATPUBLIC = (
    "<html><body>" + "y" * 3000 + "<p>Vous pouvez telecharger les pieces de maniere anonyme.</p>"
    "<p>Dossier de consultation (DCE)</p>"
    '<input name="nomEntiteContact" required><input name="nomPointContact" required>'
    '<input name="mailPointContact" required>'
    '<div class="loginForm__capchaWrapp"><div id="textCaptchaDiv">captcha</div></div>'
    "</body></html>"
)


class TestPlatformRecognition:
    def test_place_is_recognised(self) -> None:
        assert platform_of("https://www.marches-publics.gouv.fr/?page=x") == "place"

    def test_achatpublic_subdomains_count(self) -> None:
        assert platform_of("https://saintjoseph.achatpublic.com/sdm/x") == "achatpublic"

    def test_another_profile_is_not_confused_with_place(self) -> None:
        assert platform_of("https://www.marches-publics.info/x") == "other"


class TestJavascriptRenderingIsNamedAsSuch:
    def test_an_empty_result_block_means_a_browser_is_required(self) -> None:
        probe = analyse("https://www.marches-publics.gouv.fr/?page=x", 200, PLACE_SEARCH, [])
        assert probe.browser_required is True
        assert probe.results_rendered_server_side is False
        assert "JavaScript" in probe.blocker

    def test_a_javascript_page_is_not_reported_as_authentication(self) -> None:
        """Confondre les deux ferait croire à un mur qui n'existe pas."""
        probe = analyse("https://www.marches-publics.gouv.fr/?page=x", 200, PLACE_SEARCH, [])
        assert probe.identity_form_required is False
        assert probe.captcha_present is False


class TestTheIdentityFormIsDetectedButNeverSubmitted:
    def test_the_three_required_fields_are_detected(self) -> None:
        probe = analyse("https://www.achatpublic.com/sdm/x", 200, ACHATPUBLIC, ["PROD_APC_ID"])
        assert probe.identity_form_required is True
        assert set(probe.identity_fields) == {
            "nomEntiteContact",
            "nomPointContact",
            "mailPointContact",
        }

    def test_the_anonymous_option_is_recorded(self) -> None:
        probe = analyse("https://www.achatpublic.com/sdm/x", 200, ACHATPUBLIC, [])
        assert probe.anonymous_download_option_detected is True
        assert probe.documents_section_detected is True

    def test_nothing_is_ever_downloaded_by_the_analyser(self) -> None:
        """`analyse` lit une page. Elle ne poste rien, jamais."""
        probe = analyse("https://www.achatpublic.com/sdm/x", 200, ACHATPUBLIC, [])
        assert probe.download_attempted is False
        assert probe.document_download_success is False

    def test_the_blocker_names_the_false_declaration_risk(self) -> None:
        probe = analyse("https://www.achatpublic.com/sdm/x", 200, ACHATPUBLIC, [])
        assert "fausse déclaration" in probe.blocker


class TestCaptchaIsAttributedToTheRightPath:
    def test_a_login_captcha_is_not_a_captcha_on_the_public_path(self) -> None:
        """Le CAPTCHA d'Achatpublic garde le formulaire de connexion.

        Le compter comme un obstacle au retrait anonyme ferait conclure à tort
        qu'aucune automatisation légitime n'est possible.
        """
        probe = analyse("https://www.achatpublic.com/sdm/x", 200, ACHATPUBLIC, [])
        assert probe.captcha_present is True
        assert probe.captcha_on_login_path_only is True


class TestAnEmptyPageIsNotAnObstacle:
    def test_a_page_without_documents_says_so(self) -> None:
        probe = analyse("https://x.fr/", 200, "<html>" + "z" * 3000 + "</html>", [])
        assert probe.documents_section_detected is False
        assert "aucune section documentaire" in probe.blocker

    def test_a_failed_request_is_not_a_consultation(self) -> None:
        probe = analyse("https://x.fr/", 404, "", [])
        assert probe.consultation_page_found is False
