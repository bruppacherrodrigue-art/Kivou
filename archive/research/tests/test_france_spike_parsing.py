"""SPIKE FRANCE — lecture d'un avis BOAMP, sans rien inventer.

Le spike mesure une faisabilité ; il ne doit surtout pas la surestimer. Ces
tests fixent la règle qui protège la mesure : un champ absent vaut `None`, un
lien non publié vaut `not_found`, et un rapprochement par ressemblance de titre
n'existe pas.

Les fragments eForms utilisés ici sont réduits d'un avis réel (SITREVA,
26-80582 / 26-22817).
"""

from __future__ import annotations

from decimal import Decimal

from signals.research.france_spike import (
    amount_eur,
    buyer_name,
    classify_host,
    cpv_codes,
    document_urls,
    linkage,
    procedure_reference,
    winner_names,
)

AWARD = {
    "idweb": "26-80582",
    "nature": "ATTRIBUTION",
    "nomacheteur": "SITREVA",
    "objet": "TRAITEMENT ET VALORISATION DU BOIS",
    "contractfolderid": "71ac6e62-1258-4be1-a5d6-e35e5bf97251",
    "annonce_lie": ["26-22817"],
    "titulaire": ["PAPREC FRANCE", "SARL PATRICE DUPILLE AGRICULTEUR"],
    "donnees": {
        "EFORMS": {
            "ContractAwardNotice": {
                "ext:UBLExtensions": {
                    "ext:UBLExtension": {
                        "ext:ExtensionContent": {
                            "efext:EformsExtension": {
                                "efac:NoticeResult": {
                                    "efbc:OverallMaximumFrameworkContractsAmount": {
                                        "@currencyID": "EUR",
                                        "#text": "2560000",
                                    }
                                }
                            }
                        }
                    }
                },
                "cac:ProcurementProject": {
                    "cac:MainCommodityClassification": {
                        "cbc:ItemClassificationCode": {
                            "@listName": "cpv",
                            "#text": "90514000",
                        }
                    }
                },
            }
        }
    },
}

TENDER = {
    "idweb": "26-22817",
    "nature": "APPEL_OFFRE",
    "donnees": {
        "EFORMS": {
            "ContractNotice": {
                "cac:TenderingTerms": {
                    "cac:CallForTendersDocumentReference": {
                        "cbc:ID": "1788923",
                        "cbc:DocumentType": "non-restricted-document",
                        "cac:Attachment": {
                            "cac:ExternalReference": {
                                "cbc:URI": (
                                    "https://www.marches-publics.info/mpiaws/index.cfm"
                                    "?fuseaction=dematEnt.login&type=DCE&IDM=1788923"
                                )
                            }
                        },
                    }
                }
            }
        }
    },
}


class TestFieldsAreReadNotGuessed:
    def test_the_buyer_is_read_from_its_own_field(self) -> None:
        assert buyer_name(AWARD) == "SITREVA"

    def test_winners_are_deduplicated_in_publication_order(self) -> None:
        assert winner_names(AWARD) == ["PAPREC FRANCE", "SARL PATRICE DUPILLE AGRICULTEUR"]

    def test_a_missing_winner_is_none_not_empty_string(self) -> None:
        assert winner_names({"titulaire": None}) == []

    def test_the_amount_comes_from_the_eforms_payload(self) -> None:
        assert amount_eur(AWARD) == Decimal("2560000")

    def test_an_absent_amount_is_none(self) -> None:
        assert amount_eur({"donnees": {}}) is None

    def test_the_cpv_is_read_from_its_classification_node(self) -> None:
        assert cpv_codes(AWARD) == ["90514000"]

    def test_a_boamp_descriptor_is_never_passed_off_as_a_cpv(self) -> None:
        """`descripteur_code` est une nomenclature BOAMP, pas du CPV."""
        assert cpv_codes({"descripteur_code": ["A1"], "donnees": {}}) == []

    def test_the_procedure_reference_is_the_contract_folder(self) -> None:
        assert procedure_reference(AWARD) == "71ac6e62-1258-4be1-a5d6-e35e5bf97251"


class TestLinkageIsNeverFuzzy:
    def test_a_published_linked_notice_is_exact(self) -> None:
        result = linkage(AWARD)
        assert result.strength == "exact"
        assert result.notice_ids == ("26-22817",)

    def test_a_contract_folder_alone_is_strong(self) -> None:
        record = {**AWARD, "annonce_lie": None}
        assert linkage(record).strength == "strong"

    def test_several_linked_notices_are_ambiguous(self) -> None:
        record = {**AWARD, "annonce_lie": ["26-1", "26-2", "26-3"]}
        assert linkage(record).strength == "ambiguous"

    def test_nothing_published_is_not_found(self) -> None:
        record = {"idweb": "x", "annonce_lie": None, "contractfolderid": None}
        assert linkage(record).strength == "not_found"

    def test_titles_are_never_compared(self) -> None:
        """Deux avis au même objet ne sont pas liés pour autant."""
        a = {"idweb": "1", "objet": "NETTOYAGE DES LOCAUX", "annonce_lie": None}
        assert linkage(a).strength == "not_found"


class TestDocumentUrlsAreTakenFromTheNotice:
    def test_the_call_for_tenders_uri_is_extracted(self) -> None:
        urls = document_urls(TENDER)
        assert len(urls) == 1
        assert urls[0].startswith("https://www.marches-publics.info/")

    def test_a_notice_without_document_reference_yields_nothing(self) -> None:
        assert document_urls({"donnees": {"EFORMS": {"ContractNotice": {}}}}) == []

    def test_html_entities_in_the_uri_are_decoded(self) -> None:
        record = {
            "donnees": {
                "EFORMS": {
                    "ContractNotice": {
                        "cac:CallForTendersDocumentReference": {
                            "cac:Attachment": {
                                "cac:ExternalReference": {"cbc:URI": "https://x.fr/a?b=1&amp;c=2"}
                            }
                        }
                    }
                }
            }
        }
        assert document_urls(record) == ["https://x.fr/a?b=1&c=2"]


class TestTheApiPayloadShapeIsRespected:
    """`donnees` arrive de l'API en CHAÎNE JSON, pas en dict.

    Les premiers tests de ce fichier construisaient la fixture à la main, en
    dict : ils passaient pendant que le run réel rendait zéro montant, zéro CPV
    et zéro URL sur 30 avis. La forme réelle du payload fait donc partie du
    contrat testé.
    """

    def test_a_string_payload_is_parsed(self) -> None:
        import json as _json

        record = {**AWARD, "donnees": _json.dumps(AWARD["donnees"], ensure_ascii=False)}
        assert amount_eur(record) == Decimal("2560000")
        assert cpv_codes(record) == ["90514000"]

    def test_a_string_payload_yields_document_urls(self) -> None:
        import json as _json

        record = {"donnees": _json.dumps(TENDER["donnees"], ensure_ascii=False)}
        assert len(document_urls(record)) == 1

    def test_an_unparsable_payload_is_not_a_crash(self) -> None:
        assert amount_eur({"donnees": "pas du json"}) is None
        assert document_urls({"donnees": "pas du json"}) == []


class TestHostClassification:
    def test_place_is_recognised_on_its_real_domain(self) -> None:
        """PLACE se sert sur `www.marches-publics.gouv.fr`.

        Ne reconnaître que `place.marches-publics.gouv.fr` a fait rapporter un
        `place_match_rate` de 0 % alors que trois avis sur trente y menaient.
        """
        assert classify_host("https://www.marches-publics.gouv.fr/?page=x") == "place"
        assert classify_host("https://place.marches-publics.gouv.fr/x") == "place"

    def test_a_lookalike_buyer_profile_is_not_place(self) -> None:
        """`marches-publics.info` est un profil privé, pas la plateforme d'État."""
        assert classify_host("https://www.marches-publics.info/x") != "place"

    def test_a_known_buyer_profile_is_named(self) -> None:
        assert classify_host("https://www.marches-publics.info/x") == "marches-publics.info"

    def test_an_unknown_host_keeps_its_domain(self) -> None:
        assert classify_host("https://achats.example.fr/y") == "achats.example.fr"

    def test_a_malformed_url_is_not_a_host(self) -> None:
        assert classify_host("pas une url") is None
