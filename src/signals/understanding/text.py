"""Vue texte des descriptions publiées — déterministe, sans perte de contenu.

55 des 168 descriptions du corpus sont du HTML SIMAP (`<p>`, `<br>`, listes,
entités). Les lire brutes donnerait des résumés illisibles ; les nettoyer avec
un modèle de langue risquerait d'en altérer le sens.

Le nettoyage est donc **structurel et déterministe** : les balises de bloc
deviennent des séparations, les balises restantes disparaissent, les entités
sont décodées **une seule fois**. Ce dernier point est essentiel : un émetteur
qui publie `&amp;amp;` a réellement voulu écrire `&amp;` — décoder deux fois
réécrirait sa donnée.

Le texte source reste intact partout ailleurs : cette vue ne remplace jamais la
description publiée, elle s'ajoute à côté.
"""

from __future__ import annotations

import html
import re

# Balises qui marquent une rupture de bloc dans les descriptions observées.
_BLOCK_BREAK = re.compile(
    r"</\s*(p|div|li|tr|h[1-6]|blockquote)\s*>|<\s*(br|hr)\s*/?>|<\s*li\s*>", re.IGNORECASE
)
_TAG = re.compile(r"<[^>]+>")
# Le corps d'un `<script>` ou d'un `<style>` n'est jamais du texte de document :
# le garder ferait passer « alert(1) » ou « p{color:red} » pour une phrase.
_SCRIPT_STYLE = re.compile(
    r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL
)
_WHITESPACE = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def looks_like_html(text: str | None) -> bool:
    return bool(text) and bool(_TAG.search(text))


def plain_text(text: str | None) -> str | None:
    """Rend une description lisible sans en retirer de contenu significatif."""
    if text is None:
        return None
    if not looks_like_html(text):
        return _tidy(html.unescape(text))

    # Les ruptures de bloc d'abord, sinon `</p><p>` collerait deux phrases.
    broken = _BLOCK_BREAK.sub("\n", _SCRIPT_STYLE.sub(" ", text))
    stripped = _TAG.sub("", broken)
    # Une seule passe de décodage : `&amp;amp;` → `&amp;`, et on s'arrête là.
    return _tidy(html.unescape(stripped))


def _tidy(text: str) -> str | None:
    lines = [_WHITESPACE.sub(" ", line).strip() for line in text.split("\n")]
    joined = "\n".join(line for line in lines if line)
    return _BLANK_LINES.sub("\n\n", joined).strip() or None
