"""Data integrity: the static JSON is ground truth for judging agent output, so it must be consistent."""
import json
from collections import Counter
from pathlib import Path

import pytest

from state import IngredientFact, Recipe

DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name):
    return json.loads((DATA / name).read_text())


RECIPES = [Recipe(**r) for r in _load("recipes.json")]
FACTS = {k: IngredientFact(**v) for k, v in _load("ingredients.json").items()}


# ---------------------------------------------------------------- recipes
def test_recipe_ids_unique():
    ids = [r.id for r in RECIPES]
    assert len(ids) == len(set(ids))


def test_recipe_coverage():
    by_meal = Counter(r.meal_type for r in RECIPES)
    assert by_meal["breakfast"] >= 12 and by_meal["lunch"] >= 12
    dinners = Counter(r.cuisine for r in RECIPES if r.meal_type == "dinner")
    assert len(dinners) == 8 and min(dinners.values()) >= 6


def test_total_minutes_is_prep_plus_cook():
    for r in RECIPES:
        assert r.total_minutes == r.prep_minutes + r.cook_minutes, r.id


def test_every_ingredient_has_facts_and_matching_category():
    for r in RECIPES:
        for ing in r.ingredients:
            assert ing.name in FACTS, f"{r.id}: unknown ingredient {ing.name}"
            assert ing.category == FACTS[ing.name].category, f"{r.id}: {ing.name}"


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda r: r.id)
def test_allergens_match_ingredients(recipe):
    derived = set()
    for ing in recipe.ingredients:
        derived |= set(FACTS[ing.name].allergens)
    assert set(recipe.allergens) == derived


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda r: r.id)
def test_diet_tags_match_ingredients(recipe):
    animals = {FACTS[i.name].animal_product for i in recipe.ingredients}
    tags = set(recipe.tags)
    assert ("vegetarian" in tags) == (not animals & {"meat", "fish", "shellfish"})
    assert ("vegan" in tags) == (not animals & {"meat", "fish", "shellfish", "dairy", "egg", "honey"})
    assert ("gluten_free" in tags) == ("gluten" not in recipe.allergens)
    assert ("dairy_free" in tags) == ("dairy" not in recipe.allergens)
    if "high_protein" in tags:
        assert recipe.protein_g >= 25


def test_pantry_search_has_material():
    """'what can I make with eggs, rice and spinach?' needs real hits."""
    hits = [r for r in RECIPES if {"eggs", "spinach"} <= {i.name for i in r.ingredients}]
    assert hits
    assert sum(r.total_minutes <= 20 for r in RECIPES if r.meal_type == "dinner") >= 6
    assert sum("meal_prep_friendly" in r.tags for r in RECIPES) >= 15
