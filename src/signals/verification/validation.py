"""La validation déterministe d'une réponse du vérificateur (SPEC-009A §20–§22).

Le modèle propose ; ce module dispose. Il ne corrige rien et ne réinterprète
rien : il constate qu'une réponse est cohérente avec elle-même et avec les faits
fournis, ou il l'invalide. **Une réponse invalide ne devient jamais un signal.**

Deux familles de contrôle :

* **Ancrage factuel** (§20) — tout identifiant cité doit exister dans le
  catalogue. C'est ce qui empêche le modèle de fabriquer un montant, une date,
  une technologie ou une obligation : il ne peut pointer que ce qu'on lui a donné.
* **Cohérence interne** (§22) — un `approve` engage le feed. Il ne peut pas
  coexister avec un fait contredit, un besoin non crédible, un fit absent, un
  overlap confirmé ou un timing périmé.
"""

from __future__ import annotations

import dataclasses
import re

from signals.verification.model import CommercialVerification
from signals.verification.view import VerifierInput

#: §21 — les formulations qui transforment une hypothèse en certitude d'achat.
#: La liste réunit celle de SPEC-009A §21 et celle de SPEC-009 §50 : la frontière
#: de vérité est un invariant produit, pas une contrainte de rédaction locale.
FORBIDDEN_WORDINGS = (
    "will buy",
    "will hire",
    "confirmed need",
    "confirmed demand",
    "certain demand",
    "must purchase",
    "certain opportunity",
    "va acheter",
    "va recruter",
    "besoin confirmé",
    "demande certaine",
    "achat certain",
    "opportunité certaine",
)

_FORBIDDEN = tuple(
    (wording, re.compile(re.escape(wording), re.IGNORECASE)) for wording in FORBIDDEN_WORDINGS
)


def forbidden_wording_hits(text: str) -> tuple[str, ...]:
    """Les formulations de certitude présentes dans un texte, FR et EN (§21)."""
    return tuple(wording for wording, pattern in _FORBIDDEN if pattern.search(text or ""))


@dataclasses.dataclass(frozen=True)
class ValidationOutcome:
    """Le verdict du validateur — et la raison exacte s'il refuse."""

    valid: bool
    errors: tuple[str, ...] = ()

    @property
    def failure_kind(self) -> str | None:
        return None if self.valid else "validation_failure"


def validate_verification(
    verification: CommercialVerification, view: VerifierInput
) -> ValidationOutcome:
    """Confronte une réponse au catalogue de faits et à sa propre cohérence."""
    errors: list[str] = []

    # ─── Ancrage factuel (§20) ──────────────────────────────────────────────────
    known = view.fact_ids
    for field, cited in (
        ("supporting_fact_ids", verification.supporting_fact_ids),
        ("limiting_fact_ids", verification.limiting_fact_ids),
    ):
        unknown = [fact_id for fact_id in cited if fact_id not in known]
        if unknown:
            errors.append(f"{field} cite des faits inexistants : {sorted(unknown)}")

    # ─── Vocabulaire (§21) ──────────────────────────────────────────────────────
    hits = forbidden_wording_hits(verification.commercial_reason)
    if hits:
        errors.append(f"commercial_reason contient une formulation de certitude : {list(hits)}")

    # ─── Cohérence d'un `approve` (§22) ─────────────────────────────────────────
    if verification.verdict == "approve":
        if verification.factual_consistency != "consistent":
            errors.append(f"approve avec factual_consistency={verification.factual_consistency}")
        if verification.need_credibility != "credible":
            errors.append(f"approve avec need_credibility={verification.need_credibility}")
        if verification.icp_fit in ("weak", "none"):
            errors.append(f"approve avec icp_fit={verification.icp_fit}")
        if verification.actionability in ("too_weak", "misleading"):
            errors.append(f"approve avec actionability={verification.actionability}")
        if verification.specificity == "generic":
            errors.append("approve avec specificity=generic (§22, et §18 piège 4)")
        if verification.blockers:
            errors.append(f"approve malgré des blockers : {list(verification.blockers)}")
        if verification.deliverable_overlap == "confirmed":
            errors.append("approve avec deliverable_overlap=confirmed")
        if verification.winner_already_provides_need == "yes":
            errors.append("approve alors que le gagnant fournit déjà le besoin")
        if verification.timing_status in ("stale", "ending_soon", "contradictory"):
            errors.append(f"approve avec timing_status={verification.timing_status}")
        if not verification.supporting_fact_ids:
            errors.append("approve sans aucun fait de soutien cité")
        # §15 — le texte libre de l'ICP ne peut pas fabriquer un fit que les
        # catégories structurées ne portent pas.
        if not (view.derived_need_categories & view.structured_need_categories):
            errors.append(
                "approve alors qu'aucun besoin dérivé n'appartient aux catégories "
                "structurées de l'ICP (§15 : offer_summary n'a pas autorité)"
            )

    return ValidationOutcome(valid=not errors, errors=tuple(errors))
