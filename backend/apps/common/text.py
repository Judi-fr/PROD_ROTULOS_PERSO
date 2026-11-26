"""Comparar texto como lo escribe la gente: sin importar tildes, eñes ni
mayúsculas ("joaquin" es "Joaquín", "pena" es "Peña").
"""

import re
import unicodedata

# Cada letra sin tilde y las formas con que puede venir escrita.
_VARIANTS = {
    "a": "aáàäâã",
    "e": "eéèëê",
    "i": "iíìïî",
    "o": "oóòöôõ",
    "u": "uúùüû",
    "n": "nñ",
    "c": "cç",
}


def fold(text):
    """``text`` sin tildes ni eñes y en minúsculas: "Peña" → "pena"."""
    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return plain.casefold()


def accent_insensitive_regex(word):
    """Una expresión regular que encuentra ``word`` con o sin tildes ni eñes,
    para un filtro ``__iregex`` (anda igual en Postgres y en SQLite)."""
    parts = []
    for char in fold(word):
        variants = _VARIANTS.get(char)
        parts.append(f"[{variants}{variants.upper()}]" if variants else re.escape(char))
    return "".join(parts)
