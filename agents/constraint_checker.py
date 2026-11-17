"""constraint_checker: validates a WeeklyPlan or a TonightRecommendation against the profile + the week outline (time budget per night)."""
from typing import Any, Dict, List

from langchain_core.runnables import RunnableConfig

from agents.common import dumps, human, pick_prompt, profile_view, run_tool, structured, system, values
from config import Settings, day_order
from state import ConstraintCheck
from tools import get_recipe

AGENT = "constraint_checker"
MAX_RETRIES = {"plan": 2, "tonight": 1}

_V1 = """
You are a strict validator for meal recommendations. Check EVERY item against the user's profile.
Each item has precomputed ground-truth facts: `allergen_overlap` (recipe allergens that match the user's allergies)
and `missing_diet_tags` (required diet tags the recipe lacks). Only the tags in REQUIRED_DIET_TAGS are required.
1. allergen: a violation ONLY when allergen_overlap is non-empty. A recipe that merely contains common allergens
   (gluten, dairy, soy...) is fine if the user is not allergic to them. If the user has no allergies there are no
   allergen violations.
2. diet: any non-empty missing_diet_tags is a violation. Do not invent requirements the user never stated.
3. calories: within ~15% of calorie_target per serving if one is set.
4. budget: cost_per_serving within budget if one is set.
5. time: cook minutes must fit the available minutes for that slot / the time plan.
6. leftovers: use the precomputed `leftovers_check` (days_after_batch, within_limit). Only a slot with
   within_limit=false or a missing/later batch cook is a violation; exactly at the limit is fine.
Leftover and skip slots only need the diet/allergen check of the recipe being eaten (if any).
passed=true only if there are no violations. Be specific in each violation.
"""

# --- FAILURE INJECTION: INJECT_ALLERGEN_MISS ----------------------------------------------
# The checker prompt is "simplified" and allergen data is stripped, so allergen violations slip through.
_WEAK = """
You validate meal recommendations. Allergens and diet are already handled upstream - do NOT check them.
Only check time fit, calories and budget. passed=true unless something is clearly wrong.
"""
PROMPTS = {"v1": _V1, "v2": _V1 + "\nWhen in doubt about an allergen, fail the item.\n"}


DIET_TAGS = {"vegetarian", "vegan", "gluten_free", "dairy_free"}


def required_tags(state) -> List[str]:
    diet = (values(state.get("profile")).get("diet") or [])
    return sorted({d.lower().replace("-", "_").replace(" ", "_") for d in diet} & DIET_TAGS)


def _facts(rid: str, state, config: RunnableConfig, weak: bool) -> Dict[str, Any]:
    r = run_tool(get_recipe, {"recipe_id": rid}, config)
    if "error" in r:
        return {"recipe_id": rid, "error": "unknown recipe id"}
    out = {k: r[k] for k in ["id", "name", "total_minutes", "tags", "calories_per_serving",
                             "estimated_cost_per_serving_usd", "leftovers_good_for_days"]}
    if not weak:  # see INJECT_ALLERGEN_MISS: the weakened checker never sees allergen facts
        allergies = set(values(state.get("profile")).get("allergies") or [])
        out["allergens"] = r["allergens"]
        out["ingredients"] = [i["name"] for i in r["ingredients"]]
        out["allergen_overlap"] = sorted(allergies & set(r["allergens"]))
        out["missing_diet_tags"] = [t for t in required_tags(state) if t not in r["tags"]]
    return out


def _leftovers_check(m: Dict[str, Any], keep_days: Any, order) -> Dict[str, Any]:
    """order = day keys in plan order (today first)."""
    src = (m.get("leftovers_from") or "").split()
    if not src or src[0][:3] not in order:
        return {"batch_cook_slot": None, "days_after_batch": None, "within_limit": False}
    days = order.index(m["day"]) - order.index(src[0][:3])
    ok = days > 0 and (keep_days is None or days <= keep_days)
    return {"batch_cook_slot": m["leftovers_from"], "days_after_batch": days, "within_limit": ok}


def _plan_items(state, config, weak) -> List[Dict[str, Any]]:
    order = day_order(Settings.from_config(config).now)
    cache: Dict[str, Any] = {}
    items = []
    for m in (state.get("current_plan") or {}).get("meals", []):
        rid = m.get("recipe_id")
        if rid and rid not in cache:
            cache[rid] = _facts(rid, state, config, weak)
        item = {"slot": f"{m['day']} {m['slot']}", "mode": m["mode"], "cook_minutes": m.get("cook_minutes"),
                "leftovers_from": m.get("leftovers_from"),
                "available_minutes": m.get("available_minutes"), "recipe": cache.get(rid)}
        if m["mode"] == "leftovers":
            item["leftovers_check"] = _leftovers_check(m, (cache.get(rid) or {}).get("leftovers_good_for_days"), order)
        items.append(item)
    return items


def _tonight_items(state, config, weak) -> List[Dict[str, Any]]:
    rec = state.get("tonight_recommendation") or {}
    picks = [("primary", rec.get("primary") or {})] + [(f"alternative {i + 1}", a) for i, a in enumerate(rec.get("alternatives", []))]
    ctx = state.get("advisor_ctx") or {}
    decision = state.get("advisor_step") or {}
    return [{"item": label, "recipe": _facts(p["recipe_id"], state, config, weak), "time_plan": rec.get("time_plan"),
             "start_time": rec.get("start_time"), "ready_time": rec.get("ready_time"),
             "time_available_minutes": decision.get("time_available_minutes"),
             "day_outline": ctx.get("day_outline")}
            for label, p in picks if p.get("recipe_id")]


def constraint_checker(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    settings = Settings.from_config(config)
    target = state.get("check_target") or "plan"
    weak = settings.has("INJECT_ALLERGEN_MISS")
    items = _plan_items(state, config, weak) if target == "plan" else _tonight_items(state, config, weak)
    check = structured(AGENT, f"check_{target}", ConstraintCheck, [
        system(_WEAK if weak else pick_prompt(PROMPTS, settings)),
        human(f"Profile: {dumps(profile_view(state))}\nREQUIRED_DIET_TAGS: {required_tags(state)}\n"
              f"Items to check: {dumps(items)}"),
    ], settings)
    retries = state.get("retries", 0)
    retry = (not check.passed) and retries < MAX_RETRIES[target]
    return {"constraint_check": check.model_dump(), "retries": retries + (1 if retry else 0),
            "retry_requested": retry}
