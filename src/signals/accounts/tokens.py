"""Jetons opaques — le porteur détient le secret, la base n'en détient que l'ombre.

Deux usages, une seule mécanique : session et réinitialisation de mot de passe.
Dans les deux cas, un secret aléatoire part vers le client et **seule son
empreinte** est écrite. Un vol de dump ne donne alors ni session valide ni
réinitialisation possible.

    `secrets.token_urlsafe`   32 octets d'entropie, sûrs en URL et en cookie
    SHA-256                   empreinte de recherche, pas de mot de passe

Pourquoi SHA-256 ici alors que les mots de passe exigent Argon2 : un jeton de
256 bits tiré au hasard n'a pas d'espace de recherche exploitable. Le coût
d'Argon2 protège un secret **choisi par un humain** ; sur un secret aléatoire il
n'ajoute rien et ralentirait chaque requête authentifiée.
"""

from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32


def new_token() -> str:
    """Un secret opaque, à remettre au porteur et à ne jamais journaliser."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    """L'empreinte stockée. Déterministe, donc consultable par index."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(stored_hash: str, presented: str) -> bool:
    """Comparaison à temps constant — un `==` fuirait la longueur du préfixe."""
    return secrets.compare_digest(stored_hash, token_hash(presented))
