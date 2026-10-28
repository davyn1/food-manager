"""Match a free-text item name to a FoodKeeper shelf-life product.

Order of attempts:
1. Exact alias (curated `data/aliases_extra.json` + aliases learned from user corrections).
2. Token match against each product's name, subtitle and keywords. Query tokens that
   aren't in the vocabulary are first corrected to the closest known token (typos).
   If no product covers every token, an alias for the last word (head noun) wins.
3. No match: the caller falls back to category defaults.

Pure: the index is built from already-loaded data; reading files is the caller's job.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz, process

from app.core.normalize import name_tokens, normalize_name
from app.core.schemas import (
    Category,
    CategoryDefault,
    DurationNote,
    ItemState,
    Location,
    ShelfLifeProduct,
    StorageKey,
)

# The last word of a food name is usually the head noun ("apple pie" is a pie),
# so it counts more toward a match than the modifiers before it.
HEAD_WEIGHT = 2.0
# Minimum weighted share of query tokens a product must contain to count as a match.
MIN_SCORE = 0.5
# Typo correction: rapidfuzz ratio needed, and the shortest token we try to correct.
FUZZY_MIN_RATIO = 85
FUZZY_MIN_LENGTH = 4


class MatchMethod(StrEnum):
    ALIAS = "alias"
    TOKENS = "tokens"
    FUZZY = "fuzzy"  # token match after correcting a typo
    NONE = "none"


class ShelfLifeMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    product: ShelfLifeProduct | None
    method: MatchMethod
    score: float  # 0..1, weighted share of the query covered by the product


@dataclass(frozen=True)
class _Entry:
    product: ShelfLifeProduct
    name_tokens: frozenset[str]
    all_tokens: frozenset[str]


def _product_tokens(product: ShelfLifeProduct) -> tuple[frozenset[str], frozenset[str]]:
    names = frozenset(name_tokens(product.name))
    everything = set(names)
    for text in (product.subtitle or "", *product.keywords):
        everything.update(name_tokens(text))
    return names, frozenset(everything)


class ShelfLifeIndex:
    def __init__(
        self,
        products: Iterable[ShelfLifeProduct],
        category_defaults: Iterable[CategoryDefault],
        aliases: Mapping[str, int] | None = None,
    ) -> None:
        self._products = {p.id: p for p in products}
        self._entries = [_Entry(p, *_product_tokens(p)) for p in self._products.values()]
        self._vocabulary_set = frozenset(t for e in self._entries for t in e.all_tokens)
        self._vocabulary = sorted(self._vocabulary_set)
        self._defaults = {(d.category, d.location, d.state): d.days for d in category_defaults}
        self._aliases: dict[str, int] = {}
        for alias, product_id in (aliases or {}).items():
            if product_id not in self._products:
                raise ValueError(f"Alias {alias!r} points to unknown product id {product_id}")
            self._aliases[normalize_name(alias)] = product_id

    @classmethod
    def from_data(
        cls, shelf_life: Mapping[str, Any], aliases: Mapping[str, int] | None = None
    ) -> "ShelfLifeIndex":
        """Build from the parsed contents of data/shelf_life.json."""
        return cls(
            products=[ShelfLifeProduct.model_validate(p) for p in shelf_life["products"]],
            category_defaults=[CategoryDefault.model_validate(d) for d in shelf_life["category_defaults"]],
            aliases=aliases,
        )

    def product(self, product_id: int) -> ShelfLifeProduct:
        return self._products[product_id]

    def default_days(self, category: Category, location: Location, state: ItemState) -> int:
        return self._defaults[(category, location, state)]

    def add_alias(self, alias: str, product_id: int) -> None:
        """Remember a user correction for future matches (persisting it is the caller's job)."""
        if product_id not in self._products:
            raise ValueError(f"Alias {alias!r} points to unknown product id {product_id}")
        if normalized := normalize_name(alias):
            self._aliases[normalized] = product_id

    def suggest_location(self, product: ShelfLifeProduct | None, category: Category) -> Location:
        """Where a new item most likely goes, so quick-add needs no location tap.

        Frozen food goes to the freezer; leftovers and unknown food to the fridge. Otherwise the pantry
        if the product (or, unmatched, its category) can be kept there, else the fridge.
        """
        if category is Category.FROZEN:
            return Location.FREEZER
        if category in (Category.LEFTOVERS, Category.OTHER):
            # Unknown food is safer in the fridge than on a shelf.
            return Location.FRIDGE
        if product is not None:
            pantry = product.storage.get(StorageKey.PANTRY)
            if pantry is not None and pantry.note is not DurationNote.NOT_RECOMMENDED:
                return Location.PANTRY
            if StorageKey.FRIDGE in product.storage or StorageKey.FRIDGE_OPENED in product.storage:
                return Location.FRIDGE
            if StorageKey.FREEZER in product.storage:
                return Location.FREEZER
            return Location.FRIDGE
        if self.default_days(category, Location.PANTRY, ItemState.UNOPENED) > 0:
            return Location.PANTRY
        return Location.FRIDGE

    def match(self, name: str, category: Category | None = None) -> ShelfLifeMatch:
        """Best shelf-life product for `name`. `category` breaks ties when given."""
        normalized = normalize_name(name)
        if not normalized:
            return ShelfLifeMatch(product=None, method=MatchMethod.NONE, score=0.0)
        if normalized in self._aliases:
            return ShelfLifeMatch(
                product=self._products[self._aliases[normalized]], method=MatchMethod.ALIAS, score=1.0
            )

        query, corrected = self._correct_typos(normalized.split())
        weights = [1.0] * len(query)
        weights[-1] = HEAD_WEIGHT if len(query) > 1 else 1.0
        total_weight = sum(weights)
        ranked = self._ranked(query, weights, category, MIN_SCORE)
        best = ranked[0] if ranked else None

        # A partial match ("skim milk" only matching "lactose-free milk" on "milk") defers
        # to a curated alias for the head noun, which names the generic product.
        head = query[-1]
        if (best is None or best[1] < 1.0) and len(query) > 1 and head in self._aliases:
            return ShelfLifeMatch(
                product=self._products[self._aliases[head]],
                method=MatchMethod.ALIAS,
                score=round(HEAD_WEIGHT / total_weight, 3),
            )
        if best is None:
            return ShelfLifeMatch(product=None, method=MatchMethod.NONE, score=0.0)
        entry, score = best
        method = MatchMethod.FUZZY if corrected else MatchMethod.TOKENS
        return ShelfLifeMatch(product=entry.product, method=method, score=round(score, 3))

    def search(self, text: str, category: Category | None = None, limit: int = 10) -> list[ShelfLifeProduct]:
        """Products sharing any word with `text`, best first. For picking a match by hand."""
        normalized = normalize_name(text)
        if not normalized:
            return []
        query, _ = self._correct_typos(normalized.split())
        ranked = self._ranked(query, [1.0] * len(query), category, min_score=1e-9)
        return [entry.product for entry, _ in ranked[:limit]]

    def _ranked(
        self, query: list[str], weights: list[float], category: Category | None, min_score: float
    ) -> list[tuple[_Entry, float]]:
        """Entries covering at least `min_score` of the weighted query, best first."""
        total_weight = sum(weights)
        query_set = set(query)
        scored = []
        for entry in self._entries:
            score = sum(w for t, w in zip(query, weights) if t in entry.all_tokens) / total_weight
            if score < min_score:
                continue
            name_precision = len(entry.name_tokens & query_set) / len(entry.name_tokens) if entry.name_tokens else 0.0
            key = (
                score,
                1.0 if category is not None and entry.product.category is category else 0.0,
                name_precision,
                -len(entry.all_tokens),  # fewer extra qualifiers = more generic = better default
                -entry.product.id,
            )
            scored.append((key, entry, score))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [(entry, score) for _, entry, score in scored]

    def _correct_typos(self, tokens: list[str]) -> tuple[list[str], bool]:
        corrected = False
        result = []
        for token in tokens:
            if token not in self._vocabulary_set and len(token) >= FUZZY_MIN_LENGTH:
                found = process.extractOne(
                    token, self._vocabulary, scorer=fuzz.ratio, score_cutoff=FUZZY_MIN_RATIO
                )
                if found is not None:
                    token = found[0]
                    corrected = True
            result.append(token)
        return result, corrected
