"""Un texte publié décrit-il l'objet du marché, ou renvoie-t-il ailleurs ?

WEDGE-HARDENING R1, correction 3. Un award-lot du pool portait pour objet
« WEGLEITUNG INHALT UND ECKDATEN » — l'intitulé d'une rubrique du formulaire
SIMAP, recopié dans le champ description. Le signal en héritait un sujet qui ne
nomme aucun marché.

La trace a montré que le connecteur est fidèle : la source publie réellement
cette chaîne dans `procurement.orderDescription`. La première couche fautive est
la compréhension de contrat, qui composait « Objet publié : … » dès que le champ
était non vide.

    Ce qui a été essayé, et mesuré, avant d'en arriver à une liste
    ─────────────────────────────────────────────────────────────
    La hiérarchie de champs est la correction préférable en principe : elle
    généralise, une liste non. Elle a été essayée puis rejetée **sur données**.

    · Forme typographique (capitales, absence de chiffres, brièveté) : sur les
      800 award-lots, la règle attrape six descriptions dont trois sont de
      vrais objets — `BOISSONS ET SIROPS`, `EPICES ET SELS`,
      `GESTIONE NIDO SELLA GIUDICARIE`.
    · « Courte et sans mot commun avec le titre » : quarante descriptions
      tombent, dont les plus informatives du corpus. Le titre publie le PROJET
      et la description publie le LOT : `BKP 213 Montagenbau in Stahl` sous
      « Umbau Hallen- und Freibad », `Façades` sous « Campus du Pôle Santé »,
      `Środki przeciwnowotworowe` sous un titre réduit à « Pakiet Nr 1 ». La
      hiérarchie inverse détruirait précisément le champ qui porte le métier.

    Le seul trait commun des cas non informatifs est sémantique : ce sont des
    renvois vers une autre pièce (« voir le cahier des charges ») ou des restes
    de formulaire. Aucune forme ne les distingue. La liste est donc assumée,
    et tenue étroite par trois contraintes : elle ne s'applique qu'au texte
    ENTIER, jamais en sous-chaîne ; un renvoi ne tolère après lui qu'une
    référence courte ; et son effet est de **taire une affirmation**, jamais
    d'écarter un signal.
"""

from __future__ import annotations

import re
import unicodedata

OBJECT_TEXT_POLICY_VERSION = "object-text-v0.1"

MAX_REFERENCE_TOKENS = 3
"""Ce qu'un renvoi peut traîner derrière lui sans cesser d'être un renvoi.

« Se référer au cahier des charges C02C1 » reste un renvoi. « Voir cahier des
charges : fourniture de 300 fenêtres bois » n'en est plus un — il nomme l'objet,
et la règle le laisse passer."""

DOCUMENT_REFERRALS: frozenset[str] = frozenset(
    {
        # allemand
        "siehe ausschreibungsunterlagen",
        "siehe unterlagen",
        "gemass ausschreibungsunterlagen",
        # français
        "se referer au cahier des charges",
        "voir cahier des charges",
        "voir le cahier des charges",
        "selon cahier des charges",
        # italien
        "vedi capitolato",
        # espagnol
        "lo indicado en los pliegos",
        "segun pliegos",
        # néerlandais
        "zie bestek",
        # polonais
        "zgodnie z zapisami swz i formularza cenowego",
        "zgodnie z swz",
        # roumain
        "conform caiet de sarcini",
        # suédois
        "se upphandlingsdokumentet",
        # anglais
        "see tender documents",
        "as per tender documents",
    }
)
"""Renvois vers une autre pièce du dossier. Chacun a été relevé dans le pool de
800 award-lots, ou en est la variante immédiate dans la même langue."""

FORM_SCAFFOLDING: frozenset[str] = frozenset(
    {
        "wegleitung inhalt und eckdaten",
        "inhalt und eckdaten",
        "hauptauftrag",
        "default lot",
    }
)
"""Restes de formulaire : un intitulé de rubrique ou un libellé par défaut que
l'acheteur n'a pas remplacé. Correspondance EXACTE seulement — « Hauptauftrag
Neubau Schule » nomme un marché."""

_LOT_PLACEHOLDER = re.compile(
    r"^(?:default\s+)?"
    r"(?:lot|los|lote|lotto|part|partia|pakiet|czesc|dio|grupa\s+predmeta\s+nabave|reihen)?"
    r"(?:\s*(?:nr|no|n|num|nb))?"
    r"[\s.:#-]*\d*$"
)
"""Un numéro de lot n'est pas un objet.

`cpv.py` le documente depuis SPEC-005 : « les titres publiés valent souvent
`Default lot`, `Lote 1`, `Reihen` ou `1` ». La règle est structurelle — un mot
générique de lot, éventuellement suivi d'un nombre, et rien d'autre."""


def normalise(text: str | None) -> str:
    """Minuscules, sans accent, ponctuation réduite à l'espace."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def describes_object(text: str | None) -> bool:
    """Ce texte nomme-t-il l'objet du marché ?

    Faux pour un renvoi documentaire, un reste de formulaire ou un simple
    numéro de lot. Vrai pour tout le reste, y compris les objets très courts :
    « Façades » est un objet, « Zie bestek » n'en est pas un.
    """
    normalised = normalise(text)
    if not normalised:
        return False
    if normalised in FORM_SCAFFOLDING:
        return False
    if _LOT_PLACEHOLDER.match(normalised):
        return False
    for referral in DOCUMENT_REFERRALS:
        if normalised == referral:
            return False
        if normalised.startswith(f"{referral} "):
            trailing = normalised[len(referral) :].split()
            if len(trailing) <= MAX_REFERENCE_TOKENS:
                return False
    return True


def published_object(title: str | None, description: str | None) -> tuple[str | None, str]:
    """L'objet publié et le champ qui l'établit, ou `(None, "none")`.

    La description l'emporte quand elle décrit : sur les sources mesurées, le
    titre porte le PROJET et la description porte le LOT — et c'est le lot qui
    est vendu. Le titre reprend la main dès que la description ne décrit rien.
    """
    if describes_object(description):
        return (description or "").strip(), "description"
    if describes_object(title):
        return (title or "").strip(), "title"
    return None, "none"
