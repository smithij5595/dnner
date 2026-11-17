"""grocery_agent: consolidates the plan's ingredients into a ShoppingList.

Scaling / dedupe / grouping is deterministic code (exact numbers should be verifiable);
the LLM only adds a couple of practical shopping notes.
"""
from collections import OrderedDict
from typing import Any, Dict

from langchain_core.runnables import RunnableConfig

from agents.common import dumps, human, run_tool, system, text, values
from config import Settings
from state import ShoppingItem, ShoppingList
from tools import get_recipe

AGENT = "grocery_agent"
CATEGORY_ORDER = ["produce", "protein", "dairy", "bakery", "frozen", "pantry", "spices"]
COOK_MODES = ("cook_from_scratch", "quick_meal")


def _household(state) -> int:
    try:
        return int(values(state.get("profile")).get("household_size") or 2)
    except (TypeError, ValueError):
        return 2


def scale_factor(meal: Dict[str, Any], recipe: Dict[str, Any], household: int, scaling_bug: bool) -> float:
    servings = meal.get("servings_to_cook") or household
    # --- FAILURE INJECTION: INJECT_GROCERY_SCALING_BUG -------------------------------------
    # Batch cooks are scaled for ONE meal for the household, not for all the servings being cooked.
    if scaling_bug and meal.get("is_batch_cook"):
        servings = household
    return servings / recipe["servings"]


def build_shopping_list(plan: Dict[str, Any], household: int, scaling_bug: bool, config=None) -> ShoppingList:
    totals: "OrderedDict[tuple, ShoppingItem]" = OrderedDict()
    for meal in (plan or {}).get("meals", []):
        if meal.get("mode") not in COOK_MODES or not meal.get("recipe_id"):
            continue  # leftovers / eat-out / skip need no groceries
        recipe = run_tool(get_recipe, {"recipe_id": meal["recipe_id"]}, config or {})
        if "error" in recipe:
            continue
        factor = scale_factor(meal, recipe, household, scaling_bug)
        for ing in recipe["ingredients"]:
            key = (ing["name"], ing["unit"])
            item = totals.setdefault(key, ShoppingItem(name=ing["name"], quantity=0, unit=ing["unit"],
                                                       category=ing["category"]))
            item.quantity = round(item.quantity + ing["quantity"] * factor, 3)
            if recipe["name"] not in item.for_recipes:
                item.for_recipes.append(recipe["name"])
    items = sorted(totals.values(), key=lambda i: (CATEGORY_ORDER.index(i.category), i.name))
    return ShoppingList(items=items)


def grocery_agent(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    settings = Settings.from_config(config)
    shopping = build_shopping_list(state.get("current_plan"), _household(state),
                                   settings.has("INJECT_GROCERY_SCALING_BUG"), config)
    shopping.notes = text(AGENT, "notes", [
        system("Write 1-2 short, practical shopping tips for this list (e.g. staples to check at home, what to "
               "buy for the batch cook). No more than 40 words."),
        human(dumps([f"{i.quantity} {i.unit} {i.name}" for i in shopping.items])),
    ], settings)
    return {"shopping_list": shopping.model_dump()}
