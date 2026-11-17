"""Recipe lookup tools over data/recipes.json."""
from typing import List, Optional

from langchain_core.tools import tool

from tools.data import recipe_summary, recipes

STAPLE_CATEGORIES = {"spices"}
STAPLES = {"olive oil", "vegetable oil"}


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def ingredient_matches(user_term: str, ingredient: str, category: str) -> bool:
    """'rice' matches 'jasmine rice' / 'cooked rice' (head noun) but not 'rice noodles';
    'chicken' matches protein 'chicken thighs'; 'egg' matches 'eggs'."""
    term = " ".join(_singular(w) for w in user_term.lower().split())
    name = " ".join(_singular(w) for w in ingredient.lower().split())
    if term == name or name.split()[-1] == term:
        return True
    return category == "protein" and name.startswith(term + " ")


@tool
def search_recipes(query: str = "", cuisine: Optional[str] = None, meal_type: Optional[str] = None,
                   max_total_minutes: Optional[int] = None, required_tags: Optional[List[str]] = None,
                   exclude_allergens: Optional[List[str]] = None, exclude_ingredients: Optional[List[str]] = None,
                   limit: int = 8) -> List[dict]:
    """Search the recipe catalog. All filters optional.

    query: words matched against name/cuisine/tags. cuisine: e.g. 'Thai'. meal_type: breakfast|lunch|dinner.
    required_tags: e.g. ['vegetarian','gluten_free','meal_prep_friendly']. exclude_allergens: e.g. ['tree_nut','dairy'].
    exclude_ingredients: ingredient words to avoid (e.g. dislikes like 'mushrooms')."""
    words = [w for w in query.lower().split() if len(w) > 2]
    results = []
    for r in recipes().values():
        if cuisine and cuisine.lower() not in r.cuisine.lower():
            continue
        if meal_type and r.meal_type != meal_type.lower():
            continue
        if max_total_minutes is not None and r.total_minutes > max_total_minutes:
            continue
        if required_tags and not set(required_tags) <= set(r.tags):
            continue
        if exclude_allergens and set(exclude_allergens) & set(r.allergens):
            continue
        if exclude_ingredients and any(ingredient_matches(x, i.name, i.category) or x.lower() in i.name
                                       for x in exclude_ingredients for i in r.ingredients):
            continue
        haystack = f"{r.name} {r.cuisine} {' '.join(r.tags)} {' '.join(i.name for i in r.ingredients)}".lower()
        score = sum(w in haystack for w in words)
        if words and score == 0:
            continue
        results.append((score, -r.total_minutes, r))
    results.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [recipe_summary(r) for _, _, r in results[:limit]]


@tool
def get_recipe(recipe_id: str) -> dict:
    """Full recipe (ingredients with quantities, steps, allergens, tags) by id."""
    r = recipes().get(recipe_id)
    return r.model_dump() if r else {"error": f"no recipe with id '{recipe_id}'"}


@tool
def find_recipes_by_ingredients(ingredients: List[str], meal_type: Optional[str] = None,
                                max_missing: int = 3, limit: int = 5) -> List[dict]:
    """Recipes you can make from what's on hand. Ranks by how many of `ingredients` are used,
    then by fewest missing (spices/oil are assumed staples). Returns matched + missing lists."""
    out = []
    for r in recipes().values():
        if meal_type and r.meal_type != meal_type.lower():
            continue
        needed = [i for i in r.ingredients if i.category not in STAPLE_CATEGORIES and i.name not in STAPLES]
        matched = [i.name for i in needed if any(ingredient_matches(u, i.name, i.category) for u in ingredients)]
        missing = [i.name for i in needed if i.name not in matched]
        if not matched or len(missing) > max_missing:
            continue
        out.append((len(matched), -len(missing), r, matched, missing))
    out.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [{**recipe_summary(r), "matched": m, "missing": miss} for _, _, r, m, miss in out[:limit]]
