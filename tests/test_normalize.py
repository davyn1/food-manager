import pytest

from app.core.normalize import name_tokens, normalize_name, singularize


@pytest.mark.parametrize(
    "name",
    ["chicken thighs", "Chicken Thigh", "boneless chicken thighs", "Boneless, Skinless Chicken Thighs"],
)
def test_chicken_thigh_variants_normalize_the_same(name: str) -> None:
    assert normalize_name(name) == "chicken thigh"


@pytest.mark.parametrize(
    ("plural", "singular"),
    [
        ("eggs", "egg"),
        ("berries", "berry"),
        ("cherries", "cherry"),
        ("tomatoes", "tomato"),
        ("potatoes", "potato"),
        ("peaches", "peach"),
        ("radishes", "radish"),
        ("olives", "olive"),
        ("cloves", "clove"),
        ("oranges", "orange"),
        ("cheeses", "cheese"),
        ("pies", "pie"),
        ("cookies", "cookie"),
        ("loaves", "loaf"),
        ("leaves", "leaf"),
        ("quiches", "quiche"),
    ],
)
def test_singularize_plurals(plural: str, singular: str) -> None:
    assert singularize(plural) == singular


@pytest.mark.parametrize(
    "word",
    ["hummus", "asparagus", "couscous", "molasses", "swiss", "bass", "rice", "pea", "egg"],
)
def test_singularize_leaves_singulars_alone(word: str) -> None:
    assert singularize(word) == word


def test_accents_are_stripped() -> None:
    assert normalize_name("Jalapeños") == "jalapeno"


def test_apostrophes_are_joined_not_split() -> None:
    assert normalize_name("Baker's Chocolate") == "baker chocolate"
    assert normalize_name("Baker’s Chocolate") == "baker chocolate"


def test_punctuation_and_hyphens_become_spaces() -> None:
    assert normalize_name("half-and-half") == "half and half"


def test_numbers_units_and_stopwords_are_dropped() -> None:
    assert normalize_name("2 lbs of ground beef") == "ground beef"
    assert normalize_name("2% milk") == "milk"


def test_shelf_life_relevant_words_are_kept() -> None:
    assert normalize_name("canned tomatoes") == "canned tomato"
    assert normalize_name("fresh tomatoes") == "tomato"
    assert normalize_name("dried cranberries") == "dried cranberry"


def test_ampersand_becomes_and() -> None:
    assert normalize_name("Mac & Cheese") == "mac and cheese"


def test_only_descriptors_falls_back_to_them() -> None:
    assert normalize_name("Large") == "large"


def test_blank_input_gives_empty_string() -> None:
    assert normalize_name("") == ""
    assert normalize_name("   ,  ") == ""


def test_name_tokens_preserve_order() -> None:
    assert name_tokens("Greek Yogurt, Plain") == ["greek", "yogurt", "plain"]


@pytest.mark.parametrize(
    "name",
    ["Boneless Chicken Thighs", "Jalapeños", "Mac & Cheese", "canned tomatoes", "Large", "hummus"],
)
def test_normalize_is_idempotent(name: str) -> None:
    once = normalize_name(name)
    assert normalize_name(once) == once
