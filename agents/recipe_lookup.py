"""recipe_lookup: "Yes, the tacos please - what's the recipe?"

Resolves WHICH recipe the user means from what Dnner already showed them, then fetches the full recipe
(ingredients + steps) with the get_recipe tool. Deterministic: no LLM call, no new recipe search.

Resolution order:
  1. A day named in the message ("Thursday's dinner") -> that slot in the current plan.
  2. Words from a recipe name ("the tacos", "black bean") -> best match, preferring the dishes Dnner just
     recommended (tonight's primary + alternatives), then the plan, then the whole recipe book.
  3. Plain acceptance ("yes", "sounds good, recipe please") -> tonight's primary pick.
  4. Otherwise not found -> the composer asks which recipe they mean.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.runnables import RunnableConfig

from agents.common import last_user_message, run_tool, values
from config import DAY_KEYS, DAY_NAMES
from tools import get_recipe
from tools.data import recipes

AGENT = "recipe_lookup"

_STOP = {"the", "a", "an", "and", "with", "of", "for", "in", "on", "to", "me", "my", "i", "id", "i'd", "like",
         "please", "give", "recipe", "recipes", "yes", "yeah", "that", "one", "sounds", "good", "great", "make",
         "want", "do", "can", "you", "it", "how", "what", "is", "let's", "lets", "go", "ok", "okay", "sure",
         "first", "second", "dinner", "lunch", "breakfast", "tonight", "style", "easy", "quick"}
_ACCEPT = re.compile(r"\b(yes|yeah|yep|sure|ok(ay)?|sounds (good|great)|let'?s do (it|that)|that one|i'?ll take|"
                     r"i'?d like|go with|perfect|the recipe|how do i make)\b", re.I)


def _words(text_: str) -> set:
    out = set()
    for w in re.findall(r"[a-z']+", text_.lower()):
        w = w.strip("'")
        if len(w) < 3 or w in _STOP:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 3 else w)  # tacos -> taco, beans -> bean
    return out


def candidates(state: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """(recipe_id, source, label) in preference order, de-duplicated."""
    seen, out = set(), []

    def add(rid, source, label):
        if rid and rid not in seen and rid in recipes():
            seen.add(rid)
            out.append((rid, source, label))

    rec = state.get("tonight_recommendation") or {}
    add((rec.get("primary") or {}).get("recipe_id"), "recommended", "primary")
    for i, alt in enumerate(rec.get("alternatives") or []):
        add(alt.get("recipe_id"), "recommended", f"alternative {i + 1}")
    for m in (state.get("current_plan") or {}).get("meals", []):
        add(m.get("recipe_id"), "plan", f"{m.get('day')} {m.get('slot')}")
    for rid in recipes():
        add(rid, "recipe_book", "")
    return out


def _plan_day(state: Dict[str, Any], message: str) -> Optional[Tuple[str, str]]:
    plan = state.get("current_plan") or {}
    m = message.lower()
    for key, name in zip(DAY_KEYS, DAY_NAMES):
        if re.search(rf"\b({name.lower()}|{key})\b", m):
            slot = "lunch" if "lunch" in m else "breakfast" if "breakfast" in m else "dinner"
            meal = next((x for x in plan.get("meals", []) if x["day"] == key and x["slot"] == slot), None)
            if meal and meal.get("recipe_id"):
                return meal["recipe_id"], f"plan:{key} {slot}"
    return None


def resolve(state: Dict[str, Any], message: str) -> Tuple[Optional[str], str]:
    """Returns (recipe_id or None, how_it_was_resolved)."""
    by_day = _plan_day(state, message)
    if by_day:
        return by_day
    said = _words(message)
    if said:
        best, best_score = None, 0.0
        for rank, (rid, source, label) in enumerate(candidates(state)):
            name = _words(recipes()[rid].name)
            hits = len(said & name)
            if not hits:
                continue
            # More matching words wins; ties go to what Dnner just showed the user.
            score = hits + {"recommended": 0.5, "plan": 0.25}.get(source, 0) - rank * 1e-4
            if score > best_score:
                best, best_score = (rid, f"name_match:{source}" + (f" ({label})" if label else "")), score
        if best:
            return best
    primary = ((state.get("tonight_recommendation") or {}).get("primary") or {}).get("recipe_id")
    if primary and _ACCEPT.search(message):
        return primary, "accepted_primary"
    return None, "not_found"


def recipe_lookup(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    message = last_user_message(state)
    rid, how = resolve(state, message)
    recipe = run_tool(get_recipe, {"recipe_id": rid}, config) if rid else None
    if recipe and recipe.get("error"):
        recipe = None
    allergies = set(values(state.get("profile")).get("allergies") or [])
    details = {
        "resolved_by": how,
        "recipe": recipe,
        "allergen_conflicts": sorted(allergies & set((recipe or {}).get("allergens", []))),
        "options": [recipes()[r].name for r, src, _ in candidates(state) if src != "recipe_book"][:5],
    }
    out: Dict[str, Any] = {"recipe_details": details}
    if recipe:
        task = dict(state.get("active_task") or {})
        out["active_task"] = {"intent": "recipe_request", "agent": AGENT, "status": "done",
                              "recipe_id": recipe["id"], "pending_question": None, "question_targets": [],
                              "clarifying_turns": 0, "decisions_so_far": task.get("decisions_so_far", {}),
                              "started_turn": state.get("turn_index", 0)}
    return out
