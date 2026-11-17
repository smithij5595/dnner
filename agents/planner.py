"""meal_planner: builds (or minimally edits, for replan) a WeeklyPlan with batch cooks + leftovers."""
from typing import Any, Dict

from langchain_core.runnables import RunnableConfig

from agents.common import (dumps, human, last_user_message, pick_prompt, profile_view, run_tool, structured, system,
                           tool_loop, values)
from config import Settings, day_order
from state import WeeklyPlan
from tools import get_recipe, get_week_outline, search_recipes
from tools.data import recipes

AGENT = "meal_planner"

_V1 = """
You are Dnner's weekly meal planner for a home cook who wants to cook at home more and eat out only on special
occasions, but whose days get busy. Plan the next 7 days (plan_days, starting today) for each meal in meals_to_plan,
using the recipe tools.
- Fit the week: week_outline gives each day's kind (busy / out / weeknight / weekend) and per-slot cook_minutes +
  suggested_mode, built from the nights the user said are toughest to cook. Recipe total_minutes must fit cook_minutes.
- Batch cook on a regular night BEFORE each busy night (e.g. the night before it), with a
  meal_prep_friendly recipe that fits that night's cook_minutes: set is_batch_cook=true and
  servings_to_cook = household_size x number of meals it covers. Busy nights eat those leftovers
  (mode=leftovers, recipe_id of the batch recipe, leftovers_from='<day> <slot>').
  Leftovers must come LATER in plan_days order than the batch cook and no more than the recipe's
  leftovers_good_for_days after it.
  Every extra serving from a batch cook MUST be assigned to a later leftovers slot - and busy slots
  (suggested_mode quick_meal/leftovers) should be leftovers whenever a batch cook can cover them.
- Busy nights: follow suggested_mode. leftovers -> leftovers from an EARLIER batch cook; quick_meal -> a <=20-minute
  recipe. Days run in plan_days order (today first): leftovers_from must always be an EARLIER day in that order.
- suggested_mode=skip (a night out / special occasion the user mentioned) -> mode=skip. Never plan takeout or restaurants.
- If leftovers_ok is false, avoid batch cooks and leftovers slots: plan quick_meal on busy nights instead.
- Cooked slots: servings_to_cook = household_size (more if batch).
- HARD CONSTRAINTS: never use a recipe containing any of the user's allergens (use exclude_allergens), and honor
  diet tags (e.g. required_tags=['vegetarian']). Respect budget (cost_per_serving_usd), calorie target,
  cooking_skill (beginners: avoid 'hard'), dislikes. Vary cuisines.
- Search broadly before choosing: several search_recipes calls with different cuisine filters and/or
  required_tags (e.g. ['meal_prep_friendly']), limit 10+. Never cook the same recipe twice in a week; repeats
  only happen as leftovers.
- Only use recipe_ids returned by the tools.
"""
_REPLAN = """
REPLAN: the user changed something. Start from current_plan and change ONLY the affected slots (plus leftovers that
depended on them). Keep every other meal exactly the same.
"""
PROMPTS = {"v1": _V1, "v2": _V1 + "\nBefore finalizing, re-check each recipe's allergens against the profile.\n"}


def _outline(profile: Dict[str, Any], config: RunnableConfig, ignore_busy: bool = False) -> Dict[str, Any]:
    args = {"busy_nights": None if ignore_busy else profile.get("busy_nights"),
            "nights_out": None if ignore_busy else profile.get("nights_out"),
            "weeknight_effort": profile.get("weeknight_effort")}
    return run_tool(get_week_outline, args, config)


def annotate(plan: WeeklyPlan, outline: Dict[str, Any]) -> WeeklyPlan:
    """Fill cook_minutes / available_minutes from ground truth so the UI (and your traces) can compare."""
    for m in plan.meals:
        r = recipes().get(m.recipe_id or "")
        m.cook_minutes = r.total_minutes if r and m.mode in ("cook_from_scratch", "quick_meal") else 0
        m.available_minutes = (((outline or {}).get(m.day) or {}).get(m.slot) or {}).get("cook_minutes")
    return plan


def meal_planner(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    settings = Settings.from_config(config)
    # plan_question only reaches the planner under INJECT_ROUTER_OVERCALL; treat it as a (no-op) replan.
    replan = state.get("detected_intent") in ("replan", "plan_question") and bool(state.get("current_plan"))
    # --- FAILURE INJECTION: INJECT_CONSTRAINT_DRIFT --------------------------------------
    # On a replan (or turn 3+), the dietary profile is silently dropped from the prompt.
    drift = settings.has("INJECT_CONSTRAINT_DRIFT") and (replan or state.get("turn_index", 0) >= 2)
    profile = profile_view(state, include_dietary=not drift)
    # --- FAILURE INJECTION: INJECT_IGNORES_BUSY_NIGHTS -----------------------------------
    # The planner never sees which nights are busy / out, so long recipes land on the toughest nights.
    ignore_busy = settings.has("INJECT_IGNORES_BUSY_NIGHTS")
    if ignore_busy:
        profile = {k: v for k, v in profile.items() if k not in ("busy_nights", "nights_out")}
    truth = _outline(values(state.get("profile")), config)
    seen = _outline(values(state.get("profile")), config, ignore_busy=True) if ignore_busy else truth
    check = state.get("constraint_check")
    context = {
        "profile": profile,
        "plan_days": day_order(settings.now),
        "today": settings.now.strftime("%A %Y-%m-%d %H:%M"),
        "meals_to_plan": profile.get("meals_to_plan") or ["dinner"],
        "week_outline": {d: {"kind": v["kind"], **{s: v[s] for s in ("breakfast", "lunch", "dinner")}}
                         for d, v in seen.items()},
        "current_plan": state.get("current_plan") if replan else None,
        "user_request": None if ignore_busy else last_user_message(state),
        "violations_to_fix": check["violations"] if check and not check.get("passed") else None,
    }
    prompt = pick_prompt(PROMPTS, settings) + (_REPLAN if replan else "")
    convo = tool_loop(AGENT, "search", [search_recipes, get_recipe],
                      [system(prompt), human(f"CONTEXT: {dumps(context)}")], settings, config, max_rounds=6)
    plan = structured(AGENT, "write_plan", WeeklyPlan,
                      [system(prompt), *convo[1:], human("Write the complete WeeklyPlan now.")], settings)
    plan = annotate(plan, truth)
    out = {"current_plan": plan.model_dump(), "check_target": "plan", "week_outline": truth}
    if replan:
        out["plan_changes"] = plan_diff(state["current_plan"], out["current_plan"])
    return out


def _label(m: Dict[str, Any]) -> str:
    r = recipes().get(m.get("recipe_id") or "")
    return f"{r.name if r else '-'} ({m['mode']})"


def plan_diff(old: Dict[str, Any], new: Dict[str, Any]):
    """Human-readable list of slots that changed, e.g. 'sun dinner: Tacos (leftovers) -> Fried Rice (quick_meal)'."""
    before = {(m["day"], m["slot"]): m for m in old.get("meals", [])}
    changes = []
    for m in new.get("meals", []):
        o = before.get((m["day"], m["slot"]))
        if not o or (o.get("recipe_id"), o["mode"]) != (m.get("recipe_id"), m["mode"]):
            changes.append(f"{m['day']} {m['slot']}: {_label(o) if o else 'nothing'} -> {_label(m)}")
    return changes
