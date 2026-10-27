"""Forgiving food-name normalization.

Shared by shelf-life matching and recipe ingredient matching, so that
"Boneless Chicken Thighs", "chicken thigh" and "chicken thighs" all compare equal.

Pipeline: strip accents -> lowercase -> drop apostrophes -> punctuation to spaces
-> tokenize -> drop numbers/units/stopwords -> singularize -> drop descriptor words.
"""

import re
import unicodedata

# Words that describe preparation, size, or marketing but not what the food *is*.
# Deliberately excludes words that change shelf life, e.g. "canned", "dried",
# "cooked", "smoked", "ground", "frozen".
DESCRIPTOR_WORDS: frozenset[str] = frozenset(
    {
        "boneless", "skinless", "fresh", "organic", "natural",
        "large", "small", "medium", "jumbo", "extra", "mini",
        "sliced", "diced", "chopped", "minced", "shredded", "grated", "cubed",
        "trimmed", "peeled", "pitted", "raw", "whole", "lean",
        "premium", "select", "choice", "family", "value", "pack",
    }
)

STOPWORDS: frozenset[str] = frozenset({"a", "an", "the", "of"})

UNIT_WORDS: frozenset[str] = frozenset(
    {"lb", "lbs", "oz", "g", "kg", "ml", "ct", "pk", "pkg", "dozen", "doz"}
)

_IRREGULAR_PLURALS: dict[str, str] = {
    "loaves": "loaf",
    "halves": "half",
    "leaves": "leaf",
    "knives": "knife",
    "calves": "calf",
    "geese": "goose",
    "cookies": "cookie",
    "brownies": "brownie",
    "smoothies": "smoothie",
    "veggies": "veggie",
    "quiches": "quiche",
}

# Words that end in "s" but are already singular.
_INVARIANT: frozenset[str] = frozenset({"molasses", "hummus", "asparagus", "couscous", "citrus"})

_NUMBER_RE = re.compile(r"^\d+(\.\d+)?$")
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def singularize(word: str) -> str:
    """Reduce a common English food plural to its singular form.

    Rule-based and intentionally small: the goal is that both the plural and the
    singular map to the same string, not perfect English.
    """
    if word in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[word]
    if len(word) <= 3 or word in _INVARIANT or not word.endswith("s"):
        return word
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"  # berries -> berry
    if word.endswith(("ches", "shes", "xes", "oes")):
        return word[:-2]  # peaches -> peach, tomatoes -> tomato
    return word[:-1]  # olives -> olive, eggs -> egg


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def name_tokens(name: str) -> list[str]:
    """Return the meaningful, singularized tokens of a food name, in order."""
    text = _strip_accents(name).lower()
    text = text.replace("'", "").replace("’", "")  # baker's -> bakers
    text = text.replace("&", " and ")
    raw = [t for t in _NON_WORD_RE.split(text) if t]

    tokens = [
        singularize(t)
        for t in raw
        if not _NUMBER_RE.match(t) and t not in UNIT_WORDS and t not in STOPWORDS
    ]
    meaningful = [t for t in tokens if t not in DESCRIPTOR_WORDS]
    # If the name was nothing but descriptors (e.g. "Large"), keep them rather
    # than returning an empty name.
    return meaningful or tokens


def normalize_name(name: str) -> str:
    """Canonical form of a food name, e.g. "Boneless Chicken Thighs" -> "chicken thigh"."""
    return " ".join(name_tokens(name))
