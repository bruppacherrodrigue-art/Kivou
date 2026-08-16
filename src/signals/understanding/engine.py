"""Le moteur de compréhension — déterministe, local, traçable.

**Pourquoi aucun modèle de langue.** Le corpus a tranché : le CPV est présent
sur 168 adjudications sur 168 et suffit à établir le type de contrat, tandis
que le résumé peut être *composé* de faits publiés au lieu d'être rédigé. Un
modèle de langue n'apporterait rien qu'on ne sache déjà, et introduirait le seul
risque que cette SPEC interdit absolument : inventer. Le protocole
`UnderstandingModel` reste disponible pour le jour où un texte réellement
difficile le justifiera.

**Ordre des signaux**, du plus sûr au moins sûr :

1. fait structuré publié (CPV, montant, dates, gagnant, acheteur) ;
2. confirmation par le titre ou la description ;
3. rien d'autre. Aucune intuition, aucune complétion.

Quand les signaux se contredisent, la confiance tombe — elle ne s'arbitre pas.
"""

from __future__ import annotations

from typing import Protocol

from signals.domain import ContractAward, Evidence, PublicEvent
from signals.understanding.cpv import contract_type_for_cpv, sector_for_cpv
from signals.understanding.model import (
    Claim,
    ContractGeography,
    ContractParties,
    ContractTiming,
    ContractUnderstanding,
)
from signals.understanding.text import plain_text

ENGINE_VERSION = "contract-understanding-v0.1"

# Mots-clés de confirmation, multilingues, volontairement peu nombreux : ils
# CONFIRMENT une lecture donnée par le CPV, ils n'en produisent jamais une.
TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "construction": (
        "bau",
        "neubau",
        "umbau",
        "sanierung",
        "travaux",
        "construction",
        "rénovation",
        "renovation",
        "chantier",
        "costruzione",
        "lavori",
        "obras",
        "budowa",
        "prenovo",
        "gradnja",
        "byggnad",
        "cantiere",
    ),
    "it_digital": (
        "informatique",
        "software",
        "logiciel",
        "it-",
        " it ",
        "digital",
        "numérique",
        "système d'information",
        "applikation",
        "application",
        "cloud",
        "serveur",
        "server",
        "datacenter",
        "informatica",
        "oprogramowanie",
        "sistem",
    ),
    "engineering_architecture": (
        "ingenieur",
        "ingénieur",
        "architekt",
        "architecte",
        "planung",
        "planer",
        "études",
        "engineering",
        "progettazione",
        "redacción",
        "projektierung",
    ),
    "transport_logistics": (
        "transport",
        "logistik",
        "logistique",
        "bus",
        "autobus",
        "fret",
        "spedition",
        "trasporto",
        "przewóz",
        "location d'autobus",
    ),
    "medical_supply": (
        "medizin",
        "médical",
        "medical",
        "pharma",
        "arzneimittel",
        "diagnost",
        "medicinal",
        "lekarstw",
        "лекарствен",
    ),
    "social_health_services": (
        "pflege",
        "soins",
        "sozial",
        "social",
        "assistenza",
        "servizio sociale",
        "betreuung",
        "santé",
    ),
    "facility_services": (
        "reinigung",
        "nettoyage",
        "cleaning",
        "pulizia",
        "entsorgung",
        "déchets",
        "abfall",
        "ateria",
        "puhtauspalvelu",
        "restauration",
    ),
    "security_services": (
        "sicherheit",
        "sécurité",
        "surveillance",
        "bewachung",
        "ochrony",
        "security",
        "vigilan",
    ),
    "maintenance_repair": (
        "wartung",
        "maintenance",
        "entretien",
        "unterhalt",
        "manutenzione",
        "réparation",
        "instandsetzung",
    ),
    "equipment_supply": (
        "lieferung",
        "fourniture",
        "beschaffung",
        "achat",
        "acquisition",
        "supply",
        "möbel",
        "mobilier",
        "matériel",
        "beszerzés",
        "dobava",
        "adquisición",
        "levering",
        "ersatzanschaffung",
    ),
    "energy_utilities": (
        "energie",
        "énergie",
        "strom",
        "électricité",
        "diesel",
        "gaz",
        "elektrisch",
    ),
    "telecom": ("telekom", "télécom", "telecom", "réseau mobile", "dns"),
    "education_services": ("formation", "ausbildung", "schulung", "education", "training"),
    "research": ("forschung", "recherche", "research", "étude scientifique"),
    "business_services": ("beratung", "conseil", "consulting", "werbung", "marketing"),
}


class UnderstandingModel(Protocol):
    """Point d'extension pour un futur moteur linguistique.

    Il ne remplacera jamais un fait structuré : sa place est la classification
    d'un texte que le CPV ne couvre pas, et sa sortie devra rester structurée,
    versionnée et adossée à des preuves — exactement comme celle du moteur
    déterministe.
    """

    name: str
    version: str

    def classify(self, title: str | None, description: str | None) -> tuple[str, str] | None:
        """Retourne `(contract_type, rule)` ou `None` si le texte ne tranche pas."""
        ...


class ContractUnderstandingEngine:
    """Dérive une compréhension d'un award, sans jamais le modifier."""

    def __init__(self, *, model: UnderstandingModel | None = None) -> None:
        self._model = model
        self.version = ENGINE_VERSION

    def understand(self, award: ContractAward, event: PublicEvent) -> ContractUnderstanding:
        source = _SourceFacts(award, event)
        contract_type = self._contract_type(award, source)
        sector = self._sector(award, source)
        characteristics = self._characteristics(award, source)
        summary = self._summary(award, event, source)

        facts = self._facts(award, event, source)
        claims = (contract_type, sector, summary, *characteristics, *facts.values())
        return ContractUnderstanding(
            award_ref=award.event_ref,
            source_system=event.provenance.source_system,
            source_award_id=award.source_award_id,
            contract_type=contract_type,
            sector=sector,
            object_summary=summary,
            characteristics=characteristics,
            facts=facts,
            parties=ContractParties(
                procedure_buyers=event.procedure_buyers,
                contract_signatories=award.contract_signatories,
            ),
            geography=ContractGeography(
                place_of_performance=award.place_of_performance,
                buyer_country=event.provenance.source_country,
            ),
            timing=self._timing(award, event),
            evidence_coverage=ContractUnderstanding.coverage_of(claims),
            engine_version=self.version,
        )

    # ─── Faits critiques restitués ──────────────────────────────────────────────

    def _facts(
        self, award: ContractAward, event: PublicEvent, source: _SourceFacts
    ) -> dict[str, Claim]:
        """Les faits que Kivou affichera : chacun revient à son champ d'origine.

        Ce ne sont pas des conclusions — `kind="source_fact"` le dit — mais ils
        exigent la même traçabilité : un montant affiché sans preuve est un
        montant qu'on ne peut pas défendre.
        """
        facts: dict[str, Claim] = {}

        def add(name: str, value: str | None, path: str) -> None:
            if value:
                facts[name] = Claim(
                    value=value,
                    confidence="high",
                    kind="source_fact",
                    rule="valeur publiée dans l'avis",
                    evidence=(source.field_evidence(path, value),),
                )

        winners = ", ".join(o.legal_name for o in award.awardee_organizations())
        add("winner", winners or None, "awardee_parties[].members[].organization")
        if award.value is not None:
            add("amount", f"{award.value.amount} {award.value.currency}", "value")
        if award.cpv_main is not None:
            facts["cpv"] = Claim(
                value=award.cpv_main.code,
                confidence="high",
                kind="source_fact",
                rule="valeur publiée dans l'avis",
                evidence=(source.cpv_evidence(),),
            )
        # Deux rôles publiés distinctement, donc deux faits distincts. Prendre le
        # premier acheteur pour « l'acheteur » ferait d'une position un rôle.
        add(
            "procedure_buyers",
            _join(event.procedure_buyers),
            "procedure_buyers",
        )
        add(
            "contract_signatories",
            _join(award.contract_signatories),
            "contract_signatories",
        )
        if award.award_date is not None:
            add("award_date", award.award_date.isoformat(), "award_date")
        if award.lot is not None:
            add("lot", award.lot.identifier, "lot.identifier")
        return facts

    # ─── Type de contrat ────────────────────────────────────────────────────────

    def _contract_type(self, award: ContractAward, source: _SourceFacts) -> Claim:
        cpv = award.cpv_main.code if award.cpv_main else None
        from_cpv = contract_type_for_cpv(cpv)
        families = self._text_families(source.searchable_text)
        # Hors CPV, un texte qui évoque plusieurs familles ne tranche rien.
        from_text = next(iter(families)) if len(families) == 1 else None

        if from_cpv != "unknown":
            evidence = [source.cpv_evidence()]
            if from_cpv in families:
                # Deux signaux indépendants concordent.
                evidence.append(source.text_evidence())
                return Claim(
                    value=from_cpv,
                    confidence="high",
                    rule="CPV et texte publié concordants",
                    evidence=tuple(evidence),
                )
            if families:
                # Contradiction : le CPV reste le signal le plus fiable, mais la
                # confiance tombe. On ne tranche pas à la place d'un humain.
                return Claim(
                    value=from_cpv,
                    confidence="low",
                    rule=(
                        f"CPV donne « {from_cpv} », le texte publié suggère "
                        f"« {', '.join(sorted(families))} » — divergence"
                    ),
                    evidence=(source.cpv_evidence(), source.text_evidence()),
                )
            return Claim(
                value=from_cpv,
                confidence="medium",
                rule="CPV seul ; texte publié non concluant",
                evidence=tuple(evidence),
            )

        if from_text is not None:
            return Claim(
                value=from_text,
                confidence="low",
                rule="aucun CPV exploitable ; lecture du seul texte publié",
                evidence=(source.text_evidence(),),
            )
        return Claim(
            value="unknown",
            confidence="low",
            rule="ni CPV exploitable, ni texte concluant",
        )

    def _text_families(self, text: str | None) -> set[str]:
        """Les familles évoquées par le texte publié.

        Un contrat réel en évoque souvent plusieurs — « maintenance de la
        solution logiciel » parle légitimement d'informatique ET d'entretien.
        C'est pourquoi la confirmation se fait par APPARTENANCE : si la famille
        donnée par le CPV figure parmi celles du texte, les deux signaux se
        confirment ; les autres familles évoquées ne l'infirment pas.
        """
        if not text:
            return set()
        lowered = text.casefold()
        return {
            contract_type
            for contract_type, keywords in TYPE_KEYWORDS.items()
            if any(keyword in lowered for keyword in keywords)
        }

    # ─── Secteur ────────────────────────────────────────────────────────────────

    def _sector(self, award: ContractAward, source: _SourceFacts) -> Claim:
        cpv = award.cpv_main.code if award.cpv_main else None
        sector = sector_for_cpv(cpv)
        if sector == "unknown":
            return Claim(
                value="unknown",
                confidence="low",
                rule="le CPV publié n'exprime aucun secteur",
            )
        return Claim(
            value=sector,
            confidence="medium",
            rule="secteur explicitement porté par le code CPV",
            evidence=(source.cpv_evidence(),),
        )

    # ─── Caractéristiques opérationnelles ───────────────────────────────────────

    def _characteristics(self, award: ContractAward, source: _SourceFacts) -> tuple[Claim, ...]:
        """Uniquement ce que l'avis montre. Chaque caractéristique cite son fait."""
        claims: list[Claim] = []

        if award.lot is not None:
            claims.append(
                Claim(
                    value="several_lots",
                    confidence="high",
                    rule="l'avis rattache le contrat à un lot identifié",
                    evidence=(source.field_evidence("lot", award.lot.identifier),),
                )
            )
        if len(award.awardee_parties) > 1:
            claims.append(
                Claim(
                    value="multiple_contractors",
                    confidence="high",
                    rule="plusieurs soumissionnaires retenus sur le même contrat",
                    evidence=(
                        source.field_evidence("awardee_parties", str(len(award.awardee_parties))),
                    ),
                )
            )
        if any(party.is_group for party in award.awardee_parties):
            claims.append(
                Claim(
                    value="consortium_award",
                    confidence="high",
                    rule="un soumissionnaire retenu réunit plusieurs organisations",
                    evidence=(source.field_evidence("awardee_parties[].members", "groupement"),),
                )
            )
        if award.duration is not None:
            claims.append(
                Claim(
                    value="long_duration"
                    if _is_long(award.duration.value, award.duration.unit)
                    else "defined_contract_period",
                    confidence="high",
                    rule="durée contractuelle publiée",
                    evidence=(
                        source.field_evidence(
                            "duration", f"{award.duration.value} {award.duration.unit}"
                        ),
                    ),
                )
            )
        elif award.contract_start_date and award.contract_end_date:
            claims.append(
                Claim(
                    value="defined_contract_period",
                    confidence="high",
                    rule="dates de début et de fin publiées",
                    evidence=(
                        source.field_evidence(
                            "contract_start_date", award.contract_start_date.isoformat()
                        ),
                        source.field_evidence(
                            "contract_end_date", award.contract_end_date.isoformat()
                        ),
                    ),
                )
            )
        return tuple(claims)

    # ─── Résumé ─────────────────────────────────────────────────────────────────

    def _summary(self, award: ContractAward, event: PublicEvent, source: _SourceFacts) -> Claim:
        """Le résumé est COMPOSÉ de faits publiés, jamais rédigé librement.

        Chaque fragment provient d'un champ de l'avis et le cite tel quel. C'est
        ce qui rend l'hallucination structurellement impossible : il n'y a nulle
        part où une information non publiée pourrait entrer.
        """
        pieces: list[str] = []
        evidence: list[Evidence] = []

        winners = [o.legal_name for o in award.awardee_organizations()]

        if award.title:
            pieces.append(f"Marché « {award.title} »")
            evidence.append(source.field_evidence("title", award.title))
        else:
            pieces.append("Marché sans intitulé publié")

        # Chaque rôle est nommé pour ce qu'il est. Rien n'affirme qu'un acheteur
        # de procédure a signé le contrat : l'avis ne le dit pas.
        if event.procedure_buyers:
            label = "Acheteur publié" if len(event.procedure_buyers) == 1 else "Acheteurs publiés"
            noms = _join(event.procedure_buyers)
            pieces.append(f"{label} : {noms}")
            evidence.append(source.field_evidence("procedure_buyers", noms))
        if award.contract_signatories:
            label = (
                "Signataire du contrat publié"
                if len(award.contract_signatories) == 1
                else "Signataires du contrat publiés"
            )
            noms = _join(award.contract_signatories)
            pieces.append(f"{label} : {noms}")
            evidence.append(source.field_evidence("contract_signatories", noms))
        if winners:
            pieces.append("à " + ", ".join(winners))
            evidence.append(source.field_evidence("awardee_parties", ", ".join(winners)))
        if award.value is not None:
            # Le montant PUBLIÉ, pas sa forme canonique de comparaison :
            # « 934877.50 » et « 934877.5 » ne s'écrivent pas pareil dans un avis.
            montant = f"{award.value.amount} {award.value.currency}"
            pieces.append(f"pour {montant}")
            evidence.append(source.field_evidence("value", montant))
        if award.place_of_performance is not None:
            lieu = _place_label(award.place_of_performance)
            if lieu:
                pieces.append(f"à {lieu}")
                evidence.append(source.field_evidence("place_of_performance", lieu))
        if award.award_date is not None:
            pieces.append(f"décision du {award.award_date.isoformat()}")
            evidence.append(source.field_evidence("award_date", award.award_date.isoformat()))

        summary = ", ".join(pieces) + "."
        description = plain_text(award.description)
        if description:
            extrait = description[:280].rstrip()
            summary += f" Objet publié : {extrait}"
            summary += "…" if len(description) > 280 else ""
            evidence.append(source.text_evidence())

        return Claim(
            value=summary,
            confidence="high" if evidence else "low",
            rule="composition de faits publiés, sans reformulation",
            evidence=tuple(evidence),
        )

    # ─── Timing ─────────────────────────────────────────────────────────────────

    def _timing(self, award: ContractAward, event: PublicEvent) -> ContractTiming:
        derived: list[str] = []
        days_to_start = None
        if award.award_date and award.contract_start_date:
            days_to_start = (award.contract_start_date - award.award_date).days
            derived.extend(("award_date", "contract_start_date"))
        span = None
        if award.contract_start_date and award.contract_end_date:
            span = (award.contract_end_date - award.contract_start_date).days
            for field in ("contract_start_date", "contract_end_date"):
                if field not in derived:
                    derived.append(field)

        return ContractTiming(
            published_at=event.published_at,
            award_date=award.award_date,
            contract_signature_date=award.contract_signature_date,
            contract_start_date=award.contract_start_date,
            contract_end_date=award.contract_end_date,
            duration_value=award.duration.value if award.duration else None,
            duration_unit=award.duration.unit if award.duration else None,
            days_between_award_and_start=days_to_start,
            contract_span_days=span,
            derived_from=tuple(derived),
        )


class _SourceFacts:
    """Fabrique les preuves pointant vers l'avis d'origine."""

    def __init__(self, award: ContractAward, event: PublicEvent) -> None:
        self._provenance = event.provenance
        self._award = award
        self._is_ted = event.provenance.source_system == "ted"

    def _base(self) -> dict[str, object]:
        return {
            "source_system": self._provenance.source_system,
            "source_notice_id": self._provenance.source_notice_id,
            "source_procedure_id": self._provenance.source_procedure_id,
            "source_url": self._provenance.source_url,
            "retrieved_at": self._provenance.retrieved_at,
        }

    def cpv_evidence(self) -> Evidence:
        path = (
            "cac:ProcurementProject/cac:MainCommodityClassification/cbc:ItemClassificationCode"
            if self._is_ted
            else "procurement.cpvCode.code"
        )
        return Evidence(
            **self._base(),
            source_kind="publication_field",
            path=path,
            raw_value=self._award.cpv_main.code if self._award.cpv_main else None,
        )

    def text_evidence(self) -> Evidence:
        path = (
            "cac:ProcurementProject/cbc:Description"
            if self._is_ted
            else "procurement.orderDescription"
        )
        return Evidence(
            **self._base(),
            source_kind="publication_text",
            path=path,
            # L'extrait est la donnée publiée, non nettoyée : la preuve ne
            # réécrit jamais sa source.
            excerpt=(self._award.description or self._award.title or "")[:400] or None,
        )

    def field_evidence(self, path: str, raw_value: str | None) -> Evidence:
        return Evidence(
            **self._base(),
            source_kind="publication_field",
            path=path,
            raw_value=raw_value,
        )

    @property
    def searchable_text(self) -> str | None:
        parts = [self._award.title, plain_text(self._award.description)]
        joined = " ".join(part for part in parts if part)
        return joined or None


def _join(organizations) -> str | None:
    """Toutes les organisations publiées, dans l'ordre de publication."""
    names = [organization.legal_name for organization in organizations]
    return ", ".join(names) or None


def _is_long(value: int, unit: str) -> bool:
    """« Longue durée » = au moins deux ans, calculé sur l'unité publiée."""
    months = {"day": value / 30, "week": value / 4.3, "month": value, "year": value * 12}[unit]
    return months >= 24


def _place_label(location) -> str | None:
    parts = [location.locality, location.subdivision_code or location.country]
    label = ", ".join(part for part in parts if part)
    return label or None
