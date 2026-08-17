"""Primitives linguistiques déterministes — ce que le texte dit, sans modèle.

Ce module ne connaît ni document, ni pipeline, ni modèle de langue. Il ne
contient que des règles fermées et testables : découper des phrases, lire une
modalité, reconnaître le sujet d'une obligation, classer un type, lire une
quantité.

Il est partagé par deux étages qui, eux, ne se connaissent pas :

- `intelligence` — génère les candidats et assemble le pipeline ;
- `classification` — porte le contrat sémantique confié au modèle de langue.

Séparer ces primitives évite le cycle d'import entre ces deux étages, et rend
explicite ce qui reste **hors de portée du modèle** : aucune de ces fonctions
n'appelle quoi que ce soit.
"""

from __future__ import annotations

import re
from typing import Literal

from signals.documents.extract import TextBlock
from signals.documents.requirements import (
    Confidence,
    Modality,
    RequirementQuantity,
    RequirementType,
)

# ─── Détection déterministe de la modalité ──────────────────────────────────────
# Multilingue et volontairement restreinte aux formes normatives sans ambiguïté.

_HISTORICAL = re.compile(
    r"\b(précédent contrat|contrat précédent|précédent (?:titulaire|prestataire|marché)|"
    r"titulaire précédent|devait|devaient|ancien march|ancienne prestation|"
    r"previous contract|previous contractor|former contract|vorheriger vertrag|bisherige|"
    r"contrato anterior|prethodni ugovor|prejšnj|à titre indicatif|for information only|"
    r"zur information)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"\b(ne (?:doit|doivent|peut|peuvent|sera|seront) pas|n'est pas (?:requis|exigé|obligatoire)|"
    r"non (?:requis|exigé|obligatoire)|aucune? obligation|"
    r"(?:shall|must|will) not|is not required|are not required|no requirement|"
    r"nicht (?:erforderlich|zulässig)|darf nicht|"
    r"não (?:pode|é (?:exigid|obrigatóri))|ni (?:zahtevan|obvezn))\b",
    re.IGNORECASE,
)
_OPTIONAL = re.compile(
    r"\b(souhaitable|facultatif|optionnel|de préférence|le cas échéant|"
    r"peut|peuvent|pourra|pourront|"
    r"desirable|optional|preferably|may|recommended|"
    r"wünschenswert|kann|können|"
    r"opcional|desejável|pode|podem|zaželen|priporočljivo|lahko)\b",
    re.IGNORECASE,
)
_OBLIGATION = re.compile(
    r"\b(doit|doivent|devra|devront|est tenu|sont tenus|s'engage|s'engagent|"
    r"est obligé|sont obligés|sont? à la charge|est à la charge|"
    r"sont de la responsabilité|est de la responsabilité|"
    r"shall|must|is required to|are required to|is obliged|has to|"
    r"muss|müssen|hat zu|sind verpflichtet|verpflichtet sich|"
    r"deve|devem|é obrigado|está obrigado|são da responsabilidade|é da responsabilidade|"
    r"obriga-se|mora|morajo|je dolžan|zavezuje se)\b",
    re.IGNORECASE,
)

# Sujet de l'obligation. Un devoir de l'acheteur (« le pouvoir adjudicateur doit
# notifier ») n'est pas une exigence pour le titulaire. Mais l'acheteur est aussi
# le destinataire de la moitié des obligations du dossier (« le fournisseur doit
# remettre au maître d'ouvrage… ») : le repérer ne suffit pas, il faut savoir
# s'il **porte** l'obligation ou s'il la reçoit.
_BUYER_SUBJECT = re.compile(
    r"\b("
    r"pouvoirs? adjudicateurs?|acheteurs?|maîtres? d'ouvrage|entités? adjudicatrices?|"
    r"jurys?|commission d'appel d'offres|"
    r"entidade adjudicante|órgão competente|dono da obra|júri|contraente públic\w*|"
    r"naročnik\w*|"
    r"contracting authority|contracting entity|"
    r"auftraggeber\w*|vergabestelle|"
    r"amministrazione aggiudicatrice|stazione appaltante"
    r")\b",
    re.IGNORECASE,
)
_CONTRACTOR_SUBJECT = re.compile(
    r"\b("
    r"titulaires?|prestataires?|attributaires?|fournisseurs?|entreprises?|candidats?|"
    r"adjudicatári\w*|concorrentes?|fornecedor\w*|"
    r"izvajal\w*|dobavitelj\w*|ponudnik\w*|gospodarski subjekt\w*|"
    r"contractors?|suppliers?|tenderers?|economic operators?|"
    r"auftragnehmer\w*|bieter\w*|"
    r"aggiudicatari\w*|operatore economico"
    r")\b",
    re.IGNORECASE,
)

# Phase de l'obligation. Un dossier mélange deux régimes : ce qu'il faut faire
# pour **déposer une offre** et ce qu'il faudra faire pour **exécuter le marché**.
# SPEC-006 ne s'intéresse qu'au second — « les documents d'habilitation doivent
# être rédigés en portugais » n'apprend rien sur le travail à fournir.
_BID_PHASE = re.compile(
    r"("
    # slovène — dépôt, formulaires, conditions de participation
    r"\bv ponudbi\b|priprav\w* ponudb\w*|izdelav\w* ponudb\w*|"
    r"ponudba mora biti pripravljena|"
    r"odda\w* ponudb\w*|oddan\w* dokument\w*|skupn\w* ponudb\w*|ponudbo umakne|"
    r"veljavnost\w* ponudb\w*|prijav\w* za sodelovanje|"
    r"\bespd\b|\bobraz(ec|ce|cu)\b|predračun\w*|\be-jn\b|informacijskem sistemu|"
    r"\bpogoj\w* (?:mora|morajo|za sodelovanje|za priznanje)|razlog\w* za izključitev|"
    r"popravni mehanizem|lastno izjavo|"
    # portugais — proposition, habilitation, certidões
    r"\bproposta (?:deve|deverá|será)|apresenta[çc][ãa]o da proposta|na proposta\b|"
    r"documentos? de habilita[çc][ãa]o|certid[ãa]o permanente|\bdume\b|do concurso\b|"
    # français, anglais, allemand
    r"dans (?:son|leur) offre|dossier de candidature|pièces de la candidature|"
    r"règlement de la consultation|"
    r"in (?:its|their) tender|tender submission|"
    r"im angebot|mit dem angebot"
    r")",
    re.IGNORECASE,
)

# Pièces qui portent l'exécution du marché. Le règlement de consultation, le
# formulaire ESPD et la copie d'annonce décrivent la procédure : les lire pour y
# chercher des obligations d'exécution revient à mesurer l'appel d'offres.
# ─── Classification déterministe du type ────────────────────────────────────────

_TYPE_PATTERNS: tuple[tuple[RequirementType, re.Pattern[str]], ...] = (
    # Ordre = priorité. Les motifs tolèrent la flexion (`fatura`/`faturas`,
    # `technicien`/`techniciens`) : sans cela, un mot au pluriel échappe au
    # classement et l'exigence tombe en « other ».
    (
        "certification",
        re.compile(
            r"\b(iso\s?\d{4,5}|certifi\w*|akkredit\w*|accredit\w*|habilitation\w*|zertifi\w*|"
            r"certificad\w*|certifikat\w*|atest\w*|homologa\w*|qualifica\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "operating_hours",
        re.compile(
            r"(24\s*/\s*7|24h/24|7j/7|astreinte\w*|permanence\w*|piquet|on-call|bereitschaft\w*|"
            r"hor[áa]rio\w*|delovni čas|horaires? d'ouverture)",
            re.IGNORECASE,
        ),
    ),
    (
        "service_level",
        re.compile(
            r"\b(sla|niveau\w* de service|d[ée]lai\w* d'intervention|temps de r[ée]ponse|"
            r"response time|verf[üu]gbarkeit|disponibilit\w*|n[íi]vel de servi[çc]o|odzivni čas)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "staffing_constraint",
        re.compile(
            r"\b(technicien\w*|collaborateur\w*|personnel\w*|effectif\w*|[ée]quipes?|"
            r"chef de projet|staff|teams?|mitarbeiter\w*|t[ée]cnic\w*|equipas?|osebj\w*|"
            r"kader\w*|trabalhador\w*|funcion[áa]ri\w*|zaposlen\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "subcontracting_rule",
        re.compile(
            r"\b(sous-trait\w*|subcontract\w*|unterauftrag\w*|subcontrat\w*|subempreit\w*|"
            r"podizvajal\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "training_obligation",
        re.compile(
            r"\b(formations?|forma[çc]\w*|training|schulung\w*|usposabljanj\w*)\b", re.IGNORECASE
        ),
    ),
    (
        "maintenance_obligation",
        re.compile(
            r"\b(maintenance\w*|entretien\w*|wartung\w*|manuten[çc]\w*|vzdrževanj\w*|"
            r"repara[çc]\w*|r[ée]paration\w*|assist[êe]ncia t[ée]cnica)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "documentation_obligation",
        re.compile(
            r"\b(documentation\w*|manuais|manuel\w*|notices?|rapports?|relat[óo]ri\w*|"
            r"dokumentation\w*|dokumentacij\w*|certid[õo]es|declara[çc]\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "warranty_liability",
        re.compile(
            r"\b(garanti\w*|gew[äa]hrleistung\w*|warrant\w*|responsabilit\w*|responsabilidad\w*|"
            r"odgovornost\w*|patentes?|licen[çc]\w*|licences?|marcas? registadas?|cau[çc][ãa]o|"
            r"penalidades?|p[ée]nalit\w*|multas?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "payment_terms",
        re.compile(
            r"\b(paiement\w*|factur\w*|fatur\w*|pagament\w*|zahlung\w*|rechnung\w*|plačil\w*|"
            r"račun\w*|situacij\w*|"
            r"invoic\w*|payment\w*|pre[çc]\w*|prix|honorair\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "security_constraint",
        re.compile(
            r"\b(s[ée]curit[ée]\w*|confidentialit\w*|confidencial\w*|rgpd|gdpr|sicherheit\w*|"
            r"datenschutz|seguran[çc]\w*|varnost\w*|clearance|sigilo)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "environmental_constraint",
        re.compile(
            r"\b(environnement\w*|[ée]cologiq\w*|umwelt\w*|ambienta\w*|okoljsk\w*|[ée]missions?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "technology",
        re.compile(
            r"\b(logiciel\w*|software|plateforme\w*|azure|aws|cloud|serveur\w*|api|"
            r"syst[èe]me d'information|anwendung\w*|programsk\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "schedule_deadline",
        re.compile(
            r"\b(d[ée]lais?|[ée]ch[ée]ances?|calendrier\w*|planning|prazos?|frist\w*|termin\w*|"
            r"rok\w*|deadline|dias? (?:[úu]teis|seguidos)|jours ouvrables)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "site_location",
        re.compile(
            r"\b(sites?|locaux|instala[çc]\w*|standort\w*|lokacij\w*|sur place|on-site|"
            r"oficina\w*|estabelecimento\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "quantity_volume",
        re.compile(
            r"\b(quantit[ée]s?|volumes?|nombre de|quantidade\w*|menge\w*|količin\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        # Placé juste avant `deliverable` : une caractéristique imposée à la chose
        # livrée (dimension, matériau, tension, norme de fabrication) est plus
        # précise que « livrable », et beaucoup plus fréquente qu'attendu.
        "technical_characteristic",
        re.compile(
            r"(\b\d+[\d ,.]*\s?(mm|cm|m2|m²|m3|m³|kg|kw|kva|volts?|v\b|bar|l/min|hz|"
            r"°c|db|lm|lux)\b|"
            r"\b(mati[èe]riau\w*|materiala?\w*|a[çc]o\b|inox|b[ée]ton|betona?\w*|jekl\w*|"
            r"dimension\w*|dimensionn?\w*|debelin\w*|espessura|[ée]paisseur\w*|"
            r"normativ\w*|standard\w*|norme\w*|din\b|en\s?\d{3,5})\b|"
            # Formes qui décrivent la chose livrée elle-même : la moitié des
            # obligations du cahier des charges portugais (un camion) tient là.
            r"\b(equipad\w*|dotad\w*|munid\w*|compost\w*|constru[íi]d\w*|revestid\w*|"
            r"protegid\w*|refor[çc]ad\w*|isolad\w*|possuir|instalad\w*|"
            r"equipped with|fitted with|ausgestattet|opremljen\w*|izdelan\w*|vgrajen\w*)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "deliverable",
        re.compile(
            r"\b(livrables?|fournitures?|livraisons?|fornecimento\w*|entregas?|forneced\w*|"
            r"lieferung\w*|dobav\w*|bem objeto|equipamento\w*|blago)\b",
            re.IGNORECASE,
        ),
    ),
)

_QUANTITY = re.compile(
    # Deux écritures : groupée (« 1 500 », « 1'500 ») ou nue (« 3500 »). La
    # première seule laissait passer tous les nombres à quatre chiffres.
    r"(?<![\w.,])(\d{1,3}(?:[  ']\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(%|jours?|days?|mois|months?|monate|ans?|années?|years?|jahre|heures?|hours?|"
    r"techniciens?|personnes?|collaborateurs?|sites?|postes?|véhicules?|unités?|"
    r"exemplaires?|dias|meses|anos|dni|mesecev|let|km|m2|m²|m3|m³|"
    # Unités physiques : un cahier des charges de fournitures chiffre en volts,
    # en millimètres et en kilos autant qu'en jours.
    r"mm|cm|kg|kw|kva|volts?|bar|hz|db|lux|lm)(?![\w])",
    re.IGNORECASE,
)

_SENTENCE = re.compile(r"(?<=[.;:!?])\s+|\n+")
MIN_SENTENCE_CHARS = 25
MAX_SENTENCE_CHARS = 600


def normalize_for_match(text: str) -> str:
    """Forme de comparaison d'un extrait : les espaces seuls sont tolérés.

    Un modèle peut recomposer les espaces d'un passage sans le trahir. Il ne
    peut rien changer d'autre — c'est exactement la tolérance que le validateur
    accorde, et pas une de plus.
    """
    return re.sub(r"\s+", " ", text).strip().casefold()


def sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE.split(text)]
    return [part for part in parts if MIN_SENTENCE_CHARS <= len(part) <= MAX_SENTENCE_CHARS]


def detect_modality(sentence: str) -> Modality | None:
    """Quatre états, dans l'ordre où ils l'emportent l'un sur l'autre."""
    if _HISTORICAL.search(sentence):
        return "informational"
    if _NEGATION.search(sentence):
        return "prohibited"
    if _OPTIONAL.search(sentence) and not _OBLIGATION.search(sentence):
        return "optional"
    if _OBLIGATION.search(sentence):
        return "mandatory"
    return None


ObligationSubject = Literal["buyer", "unknown"]

_MODALITY_MARKERS = (_OBLIGATION, _NEGATION, _OPTIONAL)


def obligation_subject(sentence: str) -> ObligationSubject:
    """Qui porte l'obligation, quand la phrase le dit clairement.

    L'acheteur n'est reconnu comme sujet que s'il précède le verbe normatif et
    qu'aucune désignation du titulaire ne le devance. Sans cette précaution,
    « le fournisseur doit remettre au maître d'ouvrage les bordereaux » serait
    lu comme une obligation de l'acheteur — sur le dossier slovène, cette seule
    confusion écartait 78 exigences réelles.

    Tout le reste est `unknown` : une phrase passive (« les travaux doivent être
    exécutés ») reste une exigence, et présumer un sujet non écrit serait une
    inférence.
    """
    marker = min(
        (
            found.start()
            for found in (pattern.search(sentence) for pattern in _MODALITY_MARKERS)
            if found
        ),
        default=len(sentence),
    )
    buyer = _BUYER_SUBJECT.search(sentence)
    if buyer is None or buyer.start() > marker:
        return "unknown"
    contractor = _CONTRACTOR_SUBJECT.search(sentence)
    if contractor is not None and contractor.start() < buyer.start():
        return "unknown"
    return "buyer"


def classify_requirement(sentence: str) -> RequirementType:
    for requirement_type, pattern in _TYPE_PATTERNS:
        if pattern.search(sentence):
            return requirement_type
    return "other"


def extract_quantity(sentence: str) -> RequirementQuantity | None:
    """Un nombre n'est retenu que collé à une unité reconnue.

    Le calcul reste déterministe : un modèle de langue ne produit jamais de
    chiffre dans ce moteur.
    """
    found = _QUANTITY.search(sentence)
    if not found:
        return None
    raw = found.group(0).strip()
    digits = found.group(1).replace(" ", "").replace(" ", "").replace("'", "").replace(",", ".")
    try:
        value = float(digits)
    except ValueError:
        value = None
    return RequirementQuantity(raw=raw, value=value, unit=found.group(2).lower())


def confidence_for(sentence: str, modality: Modality, block: TextBlock) -> Confidence:
    if modality == "optional":
        return "low"
    # Une cellule de tableau n'a pas le contexte normatif d'un paragraphe.
    if block.method == "xlsx_cell":
        return "medium"
    if _OBLIGATION.search(sentence) and len(sentence) >= 40:
        return "high"
    return "medium"
