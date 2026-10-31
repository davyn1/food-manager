import pytest

from app.core.schemas import (
    Category,
    CategoryDefault,
    ItemState,
    Location,
    ShelfLifeDuration,
    ShelfLifeProduct,
)
from app.core.shelf_life import MatchMethod, ShelfLifeIndex


def _product(pid: int, name: str, category: Category = Category.OTHER, subtitle: str | None = None,
             keywords: list[str] | None = None) -> ShelfLifeProduct:
    return ShelfLifeProduct(
        id=pid, category=category, source_category="x", name=name, subtitle=subtitle,
        keywords=keywords or [], storage={"fridge": ShelfLifeDuration(min_days=1, max_days=1)},
    )


PRODUCTS = [
    _product(1, "Chicken parts", Category.POULTRY, "legs or thighs", ["chicken", "thigh"]),
    _product(2, "Chicken", Category.POULTRY, "whole"),
    _product(3, "Chicken", Category.DELI, "luncheon/deli meat", ["deli meat", "packaged"]),
    _product(4, "Fruit pies", Category.BAKED_GOODS, "apple, peach", ["pie", "apple"]),
    _product(5, "Apples", Category.PRODUCE),
    _product(6, "Milk", Category.DAIRY, "lactose-free", ["lactose"]),
    _product(7, "Milk", Category.DAIRY, "plain or flavored", ["plain", "flavored", "flavor"]),
    _product(8, "Broccoli", Category.PRODUCE),
]
DEFAULTS = [
    CategoryDefault(category=c, location=loc, state=s, days=5)
    for c in Category for loc in Location for s in ItemState
]


@pytest.fixture
def index() -> ShelfLifeIndex:
    return ShelfLifeIndex(PRODUCTS, DEFAULTS, aliases={"Milk": 7})


def test_token_match_ignores_case_plurals_and_descriptors(index: ShelfLifeIndex) -> None:
    for name in ("chicken thighs", "Chicken Thigh", "boneless chicken thighs"):
        match = index.match(name)
        assert match.product is not None and match.product.id == 1
        assert match.method is MatchMethod.TOKENS
        assert match.score == 1.0


def test_alias_beats_token_match(index: ShelfLifeIndex) -> None:
    match = index.match("2% Milk")
    assert match.method is MatchMethod.ALIAS
    assert match.product is not None and match.product.id == 7


def test_head_noun_alias_used_when_no_full_token_match(index: ShelfLifeIndex) -> None:
    # "skim" is unknown, so the best token match only covers "milk": defer to the alias.
    match = index.match("skim milk")
    assert match.method is MatchMethod.ALIAS
    assert match.product is not None and match.product.id == 7


def test_full_token_match_beats_head_noun_alias(index: ShelfLifeIndex) -> None:
    match = index.match("lactose milk")
    assert match.product is not None and match.product.id == 6


def test_head_noun_outweighs_modifier(index: ShelfLifeIndex) -> None:
    match = index.match("apple pie")
    assert match.product is not None and match.product.id == 4


def test_more_generic_product_preferred_on_ties(index: ShelfLifeIndex) -> None:
    match = index.match("chicken")
    assert match.product is not None and match.product.id == 2


def test_category_hint_breaks_ties(index: ShelfLifeIndex) -> None:
    match = index.match("chicken", category=Category.DELI)
    assert match.product is not None and match.product.id == 3


def test_typos_are_corrected(index: ShelfLifeIndex) -> None:
    match = index.match("brocoli")
    assert match.method is MatchMethod.FUZZY
    assert match.product is not None and match.product.id == 8


def test_short_tokens_are_not_fuzzy_corrected(index: ShelfLifeIndex) -> None:
    assert index.match("mil").method is MatchMethod.NONE


@pytest.mark.parametrize("name", ["", "   ", "xyz123", "spaceship"])
def test_unmatched_names_return_none(index: ShelfLifeIndex, name: str) -> None:
    match = index.match(name)
    assert match.product is None
    assert match.method is MatchMethod.NONE


def test_alias_to_unknown_product_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown product id 999"):
        ShelfLifeIndex(PRODUCTS, DEFAULTS, aliases={"ghost": 999})


def test_search_lists_candidates_best_first(index: ShelfLifeIndex) -> None:
    results = index.search("chicken thigh")
    assert [p.id for p in results][:3] == [1, 2, 3]


def test_search_respects_limit_and_blank(index: ShelfLifeIndex) -> None:
    assert len(index.search("chicken", limit=2)) == 2
    assert index.search("  ") == []


def test_add_alias_updates_matching(index: ShelfLifeIndex) -> None:
    index.add_alias("Mystery Meat", 3)
    match = index.match("mystery meats")
    assert match.method is MatchMethod.ALIAS
    assert match.product is not None and match.product.id == 3


def test_default_days_lookup(index: ShelfLifeIndex) -> None:
    assert index.default_days(Category.DAIRY, Location.FRIDGE, ItemState.OPENED) == 5


# --- against the real FoodKeeper data -------------------------------------------

@pytest.mark.parametrize(
    ("name", "product_id"),
    [
        ("chicken thighs", 118),
        ("Chicken Thigh", 118),
        ("boneless chicken thighs", 118),
        ("Boneless Skinless Chicken Breasts", 117),
        ("ground beef", 43),
        ("milk", 27),
        ("2% milk", 27),
        ("soy milk", 421),
        ("eggs", 21),
        ("bananas", 251),
        ("lemons", 256),
        ("onions", 294),
        ("green onions", 295),
        ("scallions", 295),
        ("canned tuna", 618),
        ("rice", 338),
        ("brown rice", 339),
        ("chiken thighs", 118),
        ("frozen peas", 331),
    ],
)
def test_real_data_common_items(real_index: ShelfLifeIndex, name: str, product_id: int) -> None:
    match = real_index.match(name)
    assert match.product is not None, name
    assert match.product.id == product_id, f"{name} -> #{match.product.id} {match.product.name}"


@pytest.mark.parametrize(
    "dish",
    ["Chinese stir fry", "chicken stir fry", "pad thai", "kimchi fried rice", "turkey sandwich", "tteokbokki"],
)
def test_real_data_unfamiliar_dishes_are_not_forced_into_a_match(real_index: ShelfLifeIndex, dish: str) -> None:
    match = real_index.match(dish)
    assert match.product is None, f"{dish} -> #{match.product.id} {match.product.name}"


@pytest.mark.parametrize(
    ("name", "product_id"),
    [("greek yogurt", 33), ("baby spinach", 291), ("chicken soup", 193), ("skim milk", 27), ("smoked salmon", 146)],
)
def test_real_data_good_partial_matches_still_match(real_index: ShelfLifeIndex, name: str, product_id: int) -> None:
    match = real_index.match(name)
    assert match.product is not None and match.product.id == product_id


def test_real_data_every_product_name_matches_something(real_index: ShelfLifeIndex) -> None:
    unmatched = []
    for product_id in range(1, 700):
        try:
            product = real_index.product(product_id)
        except KeyError:
            continue
        if real_index.match(product.name).product is None:
            unmatched.append(product.name)
    assert unmatched == []
