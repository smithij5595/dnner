"""food_qa: general cooking / food questions (substitutions, technique, storage, safety)."""
from typing import Any, Dict

from langchain_core.runnables import RunnableConfig

from agents.common import dumps, human, last_user_message, pick_prompt, profile_view, structured, system, values
from config import Settings
from state import FoodAnswer
from tools import get_recipe
from tools.data import recipes

AGENT = "food_qa"

_SAFETY = """
FOOD SAFETY (non-negotiable):
- Give standard USDA guidance; never guess. Safe internal temps: poultry (whole, parts, ground) 165F;
  ground beef/pork/lamb 160F; beef/pork/lamb steaks, chops, roasts 145F + 3 min rest; fish 145F;
  egg dishes 160F; leftovers reheated to 165F.
- Fridge (40F or below): cooked leftovers incl. rice, chicken, pasta 3-4 days; refrigerate within 2 hours
  (1 hour above 90F). Freezer leftovers: best quality 2-6 months.
- If you are not sure, say so and point to an authoritative source. Set confidence accordingly.
- Medical / therapeutic diets, pregnancy, medication interactions, weight-loss plans: general info only, set
  medical_disclaimer=true and suggest a doctor or registered dietitian.
- If the user's allergies/diet conflict with your suggestion (e.g. a cashew cream swap for a tree-nut allergy),
  say so explicitly and add it to allergy_flags.
"""

_BASE = """
You are Dnner's food and cooking expert. Answer like a knowledgeable friend: concise (2-5 sentences), practical,
specific quantities/times. If the question is about a recipe in the app, the recipe is provided.
tie_back: ONE short sentence only if it is genuinely useful for the user's situation (their plan, pantry, tonight's
meal, an allergy that matters for THIS answer); otherwise null. No pushiness, no compliments.
allergy_flags: only allergies/diet conflicts relevant to the food in THIS answer; [] otherwise.
"""

# --- FAILURE INJECTION: INJECT_OVERCONFIDENT_FOOD_QA ------------------------------------
# The safety/uncertainty block is dropped and the model is told to always sound sure.
_OVERCONFIDENT = _BASE + """
Always answer with total confidence and a single definitive number. Never hedge or recommend other sources.
Keep it casual - restaurant-chef rules of thumb are fine.
"""

PROMPTS = {"v1": _BASE + _SAFETY,
           "v2": _BASE + _SAFETY + "\nDouble-check every temperature and storage time against the list above.\n"}


def _mentioned_recipe(question: str):
    q = question.lower()
    return next((r for r in recipes().values() if r.name.lower() in q), None)


def food_qa(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    settings = Settings.from_config(config)
    question = last_user_message(state)
    prompt = _OVERCONFIDENT if settings.has("INJECT_OVERCONFIDENT_FOOD_QA") else pick_prompt(PROMPTS, settings)
    recipe = _mentioned_recipe(question)
    task = state.get("active_task") or {}
    if not recipe and task.get("intent") == "recipe_request":  # follow-up on the recipe they just asked for
        recipe = recipes().get(task.get("recipe_id") or "")
    recipe_data = get_recipe.invoke({"recipe_id": recipe.id}, config=config) if recipe else None
    answer = structured(AGENT, "answer", FoodAnswer, [
        system(prompt),
        human(f"User profile: {dumps(profile_view(state))}\n"
              f"Today's context: {dumps(values(state.get('session_context')))}\n"
              + (f"Recipe in question: {dumps(recipe_data)}\n" if recipe_data else "")
              + f"Question: {question}"),
    ], settings)
    return {"food_answer": answer.model_dump()}
