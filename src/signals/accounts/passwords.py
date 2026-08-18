"""Le hachage des mots de passe — Argon2id, et aucune cryptographie maison.

`argon2-cffi` est l'implémentation de référence du lauréat de la Password
Hashing Competition. Elle gère le sel, les paramètres et leur encodage dans
l'empreinte : rien de tout cela n'est écrit ici, parce que tout cela est
exactement ce qu'on rate quand on l'écrit soi-même.

    Politique de mot de passe (§6)
    ──────────────────────────────
    Une longueur minimale, et rien d'autre. « Une majuscule, un chiffre, un
    symbole » produit `Motdepasse1!` — court, prévisible, et pénible. Douze
    caractères libres valent mieux, et laissent passer les phrases de passe.

Le plafond n'est pas cosmétique : Argon2 hache l'entrée entière, et accepter un
mégaoctet offrirait un déni de service à qui le demande.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

MINIMUM_PASSWORD_LENGTH = 12
MAXIMUM_PASSWORD_LENGTH = 1024

PASSWORD_HASH_SCHEME = "argon2id"

#: Paramètres par défaut d'`argon2-cffi`, suivis délibérément : ils sont revus
#: par la bibliothèque à chaque version, ce qu'une constante figée ici ne serait
#: pas. `Type.ID` sélectionne explicitement Argon2**id**.
_HASHER = PasswordHasher(type=Type.ID)


class WeakPassword(ValueError):
    """Le mot de passe ne satisfait pas la politique minimale."""


def validate_password(password: str) -> None:
    """Vérifie la longueur, et uniquement la longueur (§6)."""
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise WeakPassword(
            f"mot de passe trop court : {MINIMUM_PASSWORD_LENGTH} caractères minimum"
        )
    if len(password) > MAXIMUM_PASSWORD_LENGTH:
        raise WeakPassword(f"mot de passe trop long : {MAXIMUM_PASSWORD_LENGTH} caractères maximum")


def hash_password(password: str) -> str:
    """L'empreinte Argon2id — sel et paramètres inclus dans la chaîne rendue."""
    validate_password(password)
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Vérifie sans jamais lever sur un échec ordinaire.

    Un mot de passe faux n'est pas une erreur du programme : c'est un résultat.
    Le distinguer d'une empreinte corrompue par une exception ferait fuir
    l'information dans les journaux.
    """
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Vrai quand les paramètres de la bibliothèque ont évolué depuis le hachage."""
    try:
        return _HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
