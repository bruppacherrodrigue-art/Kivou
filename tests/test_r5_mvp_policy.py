"""Clôture SPEC-006 — AUTO DOCUMENT REQUIREMENTS DISABLED dans le chemin MVP.

Le benchmark final FR-DCE-FINAL (17 août 2026) est l'EVAL permanente de
référence : précision 82,54 % contre 95 % exigés. Décision superviseur :
aucun résultat du classifieur documentaire n'est exposé comme fait certain au
client ni utilisé comme fait fort par le Need Graph. Tant qu'aucune version
éligible n'existe :

    document_requirement = unavailable

Ces tests épinglent cette politique : tout futur consommateur (SPEC-007+) doit
passer par elle, et la réactivation exigera de changer ce contrat — jamais un
oubli silencieux.
"""

from __future__ import annotations

from signals.documents import (
    AUTO_DOCUMENT_REQUIREMENTS_ENABLED,
    DOCUMENT_REQUIREMENT_UNAVAILABLE,
    document_requirement_status,
)


class TestMvpPolicy:
    def test_auto_document_requirements_are_disabled(self) -> None:
        assert AUTO_DOCUMENT_REQUIREMENTS_ENABLED is False

    def test_the_mvp_status_is_unavailable(self) -> None:
        assert document_requirement_status() == "unavailable"
        assert DOCUMENT_REQUIREMENT_UNAVAILABLE == "unavailable"

    def test_the_policy_names_its_reference_eval(self) -> None:
        """La désactivation n'est pas un choix arbitraire : elle cite l'EVAL
        qui l'a décidée, pour qu'une reprise future sache quoi battre."""
        from signals.documents import mvp

        assert "FR-DCE-FINAL" in (mvp.__doc__ or "")
