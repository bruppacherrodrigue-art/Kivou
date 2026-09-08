"""Commercial Signal Verifier — expérience de contrôle sémantique (SPEC-009A).

    STATUT : EXPERIMENTAL — NOT PRODUCTION ENABLED
    GENERALIST FILTER FAILED DEV GATES (SPEC-009A §32)

Ce paquet n'est branché à rien. Aucun runtime produit ne l'importe, aucun
`MatchingEngine` ne l'appelle, aucun feed client n'en dépend, et il n'importe
lui-même aucun moteur — l'isolation est vérifiée dans les deux sens par
`tests/test_verifier_isolation.py`. Il n'existe volontairement aucun drapeau de
fonctionnalité qui permettrait de l'activer en production.

Mesuré sur 150 candidats (DEV, 2026-08-17) : précision utile 68,75 % contre 95 %
exigés, rappel utile 69,6 %, 1 faux signal critique. La cause établie est que le
modèle attribue les mêmes grades aux signaux utiles et aux signaux faibles ; les
seize durcissements possibles de la politique plafonnent à 75 % de précision. Le
détail vit dans `docs/reports/2026-08-17-spec009a-commercial-verifier-report.md`.

Conservé parce que l'expérience reste informative pour une V1 : le filtre porte
la précision des candidats `borderline` de 54 % à 85,7 % et récupère 18
opportunités utiles. C'est en promoteur de borderline, jamais en nettoyeur de
feed, qu'il pourrait revenir.

---

Rôle d'origine, pour mémoire.

SPEC-009 a établi que les moteurs déterministes savent reconstruire l'événement
public, nommer le gagnant, conserver les preuves et dériver des besoins
plausibles — mais qu'ils ne savent pas distinguer un signal *techniquement
cohérent* d'un signal *commercialement utile* : 52 % de précision utile, 5 %
d'actionnables, 9 faux signaux critiques.

Ce paquet ajoute un vérificateur, jamais un générateur. Il ne produit ni fait,
ni besoin, ni score. Il reçoit les sorties gelées et décide si elles méritent
d'atteindre le feed.

Frontière d'architecture non négociable : le domaine ne connaît que le protocole
`CommercialSignalVerificationModel`. Aucun nom de fournisseur, aucun transport
HTTP, aucune clé d'API n'apparaît hors de l'adaptateur — pas même dans une
docstring, ce qu'un test de frontière hérité de SPEC-006 vérifie sur tout
`src/signals`.
"""

from signals.verification.cache import VerificationCache
from signals.verification.errors import VerificationFailure, api_failure_kind
from signals.verification.model import (
    POLICY_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    Blocker,
    CommercialVerification,
    VerificationRecord,
    VerifierUsage,
)
from signals.verification.policy import FinalDecision, apply_final_policy
from signals.verification.protocol import CommercialSignalVerificationModel
from signals.verification.validation import ValidationOutcome, validate_verification
from signals.verification.view import (
    SUPPORTED_LANGUAGES,
    Fact,
    VerifierInput,
    build_verifier_input,
    detect_language,
)

__all__ = [
    "POLICY_VERSION",
    "PROMPT_VERSION",
    "SCHEMA_VERSION",
    "SUPPORTED_LANGUAGES",
    "Blocker",
    "CommercialSignalVerificationModel",
    "CommercialVerification",
    "Fact",
    "FinalDecision",
    "ValidationOutcome",
    "VerificationCache",
    "VerificationFailure",
    "VerificationRecord",
    "VerifierInput",
    "VerifierUsage",
    "api_failure_kind",
    "apply_final_policy",
    "build_verifier_input",
    "detect_language",
    "validate_verification",
]
