"""Cached loaders for the static JSON in data/ (shared by tools and agents)."""
import json
from functools import lru_cache
from typing import Dict, List

from config import DATA_DIR
from state import IngredientFact, Recipe


@lru_cache(maxsize=None)
def recipes() -> Dict[str, Recipe]:
    return {r["id"]: Recipe(**r) for r in json.loads((DATA_DIR / "recipes.json").read_text())}


@lru_cache(maxsize=None)
def ingredient_facts() -> Dict[str, IngredientFact]:
    raw = json.loads((DATA_DIR / "ingredients.json").read_text())
    return {k: IngredientFact(**v) for k, v in raw.items()}


def recipe_summary(r: Recipe) -> dict:
    """Compact view handed to LLMs (keeps prompts short)."""
    return {"id": r.id, "name": r.name, "cuisine": r.cuisine, "meal_type": r.meal_type,
            "total_minutes": r.total_minutes, "difficulty": r.difficulty, "servings": r.servings,
            "tags": r.tags, "allergens": r.allergens, "calories_per_serving": r.calories_per_serving,
            "protein_g": r.protein_g, "cost_per_serving_usd": r.estimated_cost_per_serving_usd,
            "leftovers_good_for_days": r.leftovers_good_for_days}


def all_recipe_ids() -> List[str]:
    return list(recipes())
