"""Le BKP — la classification de métier que l'avis publie lui-même.

WEDGE-HARDENING R2. Le closeout R1 laissait trois signaux faibles, tous rattachés
à la même couche : le CPV décrit le **projet**, pas le lot vendu.

Le corpus le démontre sans ambiguïté. Le projet « Umbau Hallen- und Freibad
Talegg » est publié en **treize avis d'attribution portant tous le CPV
45212212**, et treize métiers différents s'y cachent — ventilation, maçonnerie,
charpente acier, ferblanterie, électricité, technique de bassin, sauna,
sanitaire, chauffage, revêtement de bassin, caisse, photovoltaïque, automation.
Le CPV est constant : il ne distingue rien. Le seul champ qui distingue est le
code BKP publié dans l'objet de chaque avis.

C'est la justification structurelle de la précédence : **une classification de
métier explicitement publiée pour CET avis prime un code marchandise constant
sur tous les métiers du projet.** Ce n'est pas « le lot bat la procédure » — les
données ne portent pas cette distinction ici, chaque avis étant sa propre
publication.

    Autorité
    ────────
    BKP = Baukostenplan, le plan suisse des coûts de construction. La table
    ci-dessous est transcrite de l'arbre BKP officiel exposé par la plateforme
    SIMAP (outil `browse_bkp_tree`), consulté le 2026-08-18, niveau par niveau
    depuis la racine. Elle est **locale et versionnée** : aucun appel réseau
    n'a lieu à l'exécution, et aucun code n'a été mappé d'intuition.

Le BKP n'est jamais deviné d'un libellé. « Elektro », « Sanitär », « Garten »,
« Photovoltaik » restent du texte : ils peuvent servir de preuve ou d'affichage,
jamais de décideur. Le décideur est le code, et seulement quand le marqueur
`BKP` le déclare explicitement.
"""

from __future__ import annotations

import re

from signals.understanding.cpv import TradeDomain

BKP_POLICY_VERSION = "bkp-trade-v0.1"

BKP_AUTHORITY = (
    "arbre BKP officiel de la plateforme SIMAP, parcouru depuis la racine "
    "le 2026-08-18 (racine 0-9, puis niveaux 2 et 3 des familles observées)"
)

#: Préfixe BKP → corps de métier. Le préfixe le plus long gagne, ce qui permet
#: aux exceptions à trois chiffres de se détacher de leur famille.
#:
#: `None` signifie : **famille reconnue par l'autorité, mais sans domaine
#: correspondant dans la taxonomie R1** (§15). Elle ne déclasse rien — le CPV
#: reste en place. Un code absent de la table est simplement inconnu, et ne
#: déclasse rien non plus.
BKP_TRADE_RULES: dict[str, TradeDomain | None] = {
    # ── 1 Vorbereitungsarbeiten ────────────────────────────────────────────
    "10": None,  # Bestandsaufnahmen, Baugrunduntersuchungen — des études
    "11": "earthworks_demolition",  # Räumungen, Terrainvorbereitungen
    "12": None,  # Sicherungen, Provisorien
    "13": None,  # Gemeinsame Baustelleneinrichtung — installation de chantier
    "14": None,  # Anpassungen an bestehenden Bauten
    "15": None,  # Anpassungen an bestehenden Erschliessungsanlagen
    "16": None,  # Anpassungen an bestehenden Verkehrsanlagen
    "17": "special_civil",  # Spezialtiefbau
    "19": None,  # Honorare
    # ── 2 Gebäude ──────────────────────────────────────────────────────────
    "20": "earthworks_demolition",  # Baugrube
    "21": "general_building",  # Rohbau 1
    "22": "general_building",  # Rohbau 2
    "23": "technical_installation",  # Elektroanlagen
    "24": "technical_installation",  # HLK-Anlagen, Gebäudeautomation
    "25": "technical_installation",  # Sanitäranlagen
    "26": "technical_installation",  # Transportanlagen, Lageranlagen
    "27": "interior_finishing",  # Ausbau 1
    "28": "interior_finishing",  # Ausbau 2
    # Trois exceptions dans Ausbau 2 : ni l'une ni l'autre n'est du second œuvre.
    "286": None,  # Bautrocknung
    "287": None,  # Baureinigung
    "288": None,  # Gärtnerarbeiten (Gebäude)
    "29": None,  # Honorare
    # ── 3 Betriebseinrichtungen ────────────────────────────────────────────
    # L'autorité y reprend mot pour mot les intitulés de métier de la série 2.
    "33": "technical_installation",  # Elektroanlagen
    "34": "technical_installation",  # HLK-Anlagen, Gebäudeautomation
    "35": "technical_installation",  # Sanitäranlagen
    "36": "technical_installation",  # Transportanlagen, Lageranlagen
    "37": "interior_finishing",  # Ausbau 1
    "38": "interior_finishing",  # Ausbau 2
    "39": None,  # Honorare
    # ── 4 Umgebung ─────────────────────────────────────────────────────────
    # `42 Gartenanlagen` est un métier réel, mais AUCUN domaine de la taxonomie
    # R1 ne le représente : ni gros œuvre, ni second œuvre, ni terrassement.
    # §15 — on ne crée pas un domaine pour faire entrer un cas.
    "40": None,  # Terraingestaltung
    "41": None,  # Rohbau- und Ausbauarbeiten (Umgebung)
    "42": None,  # Gartenanlagen  ← BKP DOMAIN NOT REPRESENTABLE
    "44": None,  # Installationen
    "45": None,  # Leitungen innerhalb Grundstück
    "46": "roadworks_civil",  # Trassenbauten
    "47": None,  # Kunstbauten
    "48": None,  # Untertagbauten
    "49": None,  # Honorare
    # ── 0, 5, 9 — ni métier, ni travaux ────────────────────────────────────
    "0": None,  # Grundstück
    "5": None,  # Baunebenkosten
    "9": None,  # Ausstattung
}

#: Le marqueur est OBLIGATOIRE (§12). Sans lui, aucun nombre n'est un BKP.
#: La frontière est posée sur les LETTRES, pas sur `\b` : les avis écrivent
#: « BKP224 » sans espace et « Q26.0169_BKP 211 » après un souligné, deux cas
#: où `\b` ne se déclenche pas. `ABKP` ou `BKPX` restent refusés.
_MARKER = re.compile(r"(?<![A-Za-z])BKP(?![A-Za-z])[\s.:#\-]*", re.IGNORECASE)

#: Un code BKP : un à trois chiffres, une décimale au plus. Les gardes
#: `(?<!\d)` et `(?!\d)` empêchent qu'un millésime comme « 2026/2027 » ou une
#: référence comme « Q26.0169 » fournisse un faux code.
_CODE = re.compile(r"(?<!\d)(\d{1,3})(?:\.(\d))?(?!\d)")

#: Les séparateurs réellement observés entre codes d'un même marqueur :
#: « BKP224, 221.1 », « BKP 222_224 », « BKP 227/285 ».
_CHAIN = re.compile(r"[ \t]*[,;/_+&][ \t]*")


def bkp_codes(text: str | None) -> tuple[str, ...]:
    """Les codes BKP explicitement déclarés dans ce texte, dans l'ordre.

    Rien n'est déduit d'un libellé : seul un code suivant le marqueur `BKP`
    est retenu, et une chaîne ne se poursuit que sur un séparateur réel.
    """
    if not text:
        return ()
    found: list[str] = []
    for marker in _MARKER.finditer(text):
        position = marker.end()
        while True:
            code = _CODE.match(text, position)
            if not code:
                break
            found.append(f"{code.group(1)}.{code.group(2)}" if code.group(2) else code.group(1))
            chain = _CHAIN.match(text, code.end())
            if not chain:
                break
            position = chain.end()
    return tuple(dict.fromkeys(found))


def trade_domain_for_bkp(code: str) -> TradeDomain | None:
    """Le corps de métier d'UN code, ou `None` si l'autorité n'en donne aucun.

    La décimale ne sert pas au classement : `272.8` se lit dans la famille
    `272`, puis `27`. Le préfixe le plus long l'emporte.
    """
    family = code.split(".")[0]
    for length in range(len(family), 0, -1):
        prefix = family[:length]
        if prefix in BKP_TRADE_RULES:
            return BKP_TRADE_RULES[prefix]
    return None


def resolve_trade_domain(codes: tuple[str, ...]) -> tuple[TradeDomain | None, str]:
    """Le métier que ces codes établissent ensemble, et pourquoi (§13).

    Un seul domaine reconnu — même porté par plusieurs codes — tranche. Deux
    domaines différents ne tranchent pas : le lot couvre plusieurs métiers, et
    choisir le premier serait arbitraire.
    """
    if not codes:
        return None, "aucun code BKP publié"
    domains = {d for d in (trade_domain_for_bkp(c) for c in codes) if d is not None}
    if not domains:
        return None, "code BKP publié, sans domaine de métier correspondant"
    if len(domains) > 1:
        return None, f"codes BKP de métiers différents : {', '.join(sorted(domains))}"
    return domains.pop(), "corps de métier porté par le code BKP publié"
