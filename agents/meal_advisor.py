"""meal_advisor: the conversational "what should I eat tonight?" agent.

Per turn:
  1. Gather context silently with tools (current time, tonight's time budget from the week outline, planned meal).
  2. Decide: ask <=2 high-value questions, or commit to a mode (AdvisorDecision).
  3. Recommend: recipe search via tools -> TonightRecommendation (or leftovers / skip).
     The constraint checker can send it back once with violations to fix.
"""
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.runnables import RunnableConfig

from agents.common import (dietary_known, dumps, human, last_user_message, pick_prompt, profile_view,
                           recent_transcript, run_tool, structured, system, tool_loop, values)
from config import DAY_KEYS, Settings
from state import AdvisorDecision, TonightRecommendation
from tools import find_recipes_by_ingredients, get_current_time, get_recipe, get_week_outline, search_recipes
from tools.time_tools import resolve_day

AGENT = "meal_advisor"
MAX_CLARIFYING_TURNS = 2

_DECIDE_V1 = """
You are Dnner's meal advisor: a knowledgeable friend who helps the user cook at home more, even on busy days
(eating out is for special occasions). Decide what they should eat for ONE meal. CONTEXT has the current time,
the time budget for that day (from the nights they told you are toughest to cook / nights out) and any planned meal.

Decide between:
- action=ask: ask at most 2 SHORT questions, only for facts you cannot get from CONTEXT (profile, today's context,
  day outline, plan). Highest-value questions: "How much time do you have to cook?", "Feel like cooking or want
  something easy?", "Anything in the fridge to use up?", "Eating alone or cooking for others?", "Craving anything?".
- action=recommend: commit to a mode: cook_from_scratch | quick_meal | leftovers | skip (only if they are already
  eating elsewhere, e.g. the day is in nights_out).

Rules:
1. ALLERGY GATE: if CONTEXT says dietary_known=false, you MUST ask about allergies/dietary restrictions before
   recommending any food (you may pair it with one other question).
2. NEVER ask about anything already in profile or today's context (list targets in question_targets).
3. If clarifying_turns_so_far >= 2 you MUST recommend now and state assumptions.
4. Prefer committing early: if you know dietary needs and roughly how much effort they want, recommend.
   Low energy already tells you the effort level - don't ask whether they feel like cooking.
5. Revisions ("something lighter", "not Thai again", "only 20 minutes") -> action=recommend, revise the previous pick.
6. Fit the time: a stated time_limit_minutes wins; otherwise use day_outline cook_minutes (busy night -> ~20 min,
   leftovers or quick_meal). Low energy -> quick_meal or leftovers. A planned meal or leftovers for this slot
   should be the default if it still fits. If it's late (after ~8:30pm), keep it very quick.
7. "I don't want to cook" -> leftovers if a planned batch cook covers it, otherwise the lowest-effort quick_meal
   (<=15 minutes, pantry-friendly). Never suggest takeout or restaurants - Dnner only plans home meals.
Set target_meal/target_day and time_available_minutes (minutes they can spend cooking).
Always fill `reasoning` with 1 sentence citing the facts you used (it is shown to the user as context).
"""

_RECOMMEND_V1 = """
You pick a specific recipe for the user using the recipe tools. Use search_recipes with filters (meal_type,
max_total_minutes, exclude_allergens for EVERY user allergy, required_tags for their diet e.g. vegetarian),
or find_recipes_by_ingredients when they listed what they have. Then stop calling tools.
Respect dislikes and avoid repeating a cuisine the user just rejected.
"""

_FINAL_V1 = """
Write the TonightRecommendation with a primary pick and 1-2 alternatives (different from the primary).
primary.why MUST cite concrete facts: time available (busy night / stated limit), energy/mood, pantry, diet,
the planned meal. time_plan like "start at 7:15, eat by 7:40" (starting no earlier than the current time) and fill
start_time/ready_time (HH:MM) so the recipe's total_minutes fits time_available_minutes. Max 2 alternatives. List assumptions you made. Only use recipe_ids
that appeared in tool results.
"""

# --- FAILURE INJECTION: INJECT_HALLUCINATED_RECIPE ----------------------------------------
# No recipe tools: the model "remembers" a dish, inventing its id, timing and allergens.
_HALLUCINATE = """
You are a home-cooking expert. Recommend a dinner from your own knowledge (no tools available). Invent a plausible
recipe_id like 'rec_<dish_name>' and state confident cook times. Write the TonightRecommendation.
"""

_V2_GUARD = """
GUARDRAILS (v2): Re-check allergies and diet before naming any food. If dietary_known=false you may not recommend.
"""

PROMPTS = {"v1": _DECIDE_V1, "v2": _DECIDE_V1 + _V2_GUARD}


# --------------------------------------------------------------------------- context
def _target_slot(message: str, task: Dict[str, Any]):
    m = message.lower()
    prior = (task or {}).get("decisions_so_far", {})
    meal = ("breakfast" if "breakfast" in m else "lunch" if "lunch" in m else
            "dinner" if any(w in m for w in ("dinner", "tonight")) else prior.get("target_meal", "dinner"))
    day = "tomorrow" if "tomorrow" in m else prior.get("target_day", "today")
    return meal, day


def _planned_meal(state: Dict[str, Any], day_key: str, meal: str) -> Optional[Dict[str, Any]]:
    plan = state.get("current_plan") or {}
    return next((m for m in plan.get("meals", []) if m["day"] == day_key and m["slot"] == meal), None)


def _gather(state: Dict[str, Any], settings: Settings, config: RunnableConfig) -> Dict[str, Any]:
    now = run_tool(get_current_time, {}, config)
    meal, day = _target_slot(last_user_message(state), state.get("active_task"))
    day_key = DAY_KEYS[resolve_day(day, settings.now).weekday()]
    p = values(state.get("profile"))
    week = run_tool(get_week_outline, {"busy_nights": p.get("busy_nights"), "nights_out": p.get("nights_out"),
                                       "weeknight_effort": p.get("weeknight_effort")}, config)
    day_info = week[day_key]
    outline = {"kind": day_info["kind"], **day_info[meal],
               "busy_nights_known": p.get("busy_nights") is not None}
    return {"now": now, "target_meal": meal, "target_day": day, "day_key": day_key,
            "day_outline": outline, "planned": _planned_meal(state, day_key, meal)}


def _memory(state: Dict[str, Any], settings: Settings) -> Dict[str, Any]:
    """What the advisor is allowed to remember this turn (failure flags trim it)."""
    forgetful = settings.has("INJECT_FORGETFUL_ADVISOR")
    # --- FAILURE INJECTION: INJECT_CONSTRAINT_DRIFT --------------------------------------
    # After a few turns the dietary profile silently falls out of the prompt.
    drift = settings.has("INJECT_CONSTRAINT_DRIFT") and state.get("turn_index", 0) >= 2
    # --- FAILURE INJECTION: INJECT_FORGETFUL_ADVISOR -------------------------------------
    # Profile, session context and history are dropped, so the advisor re-asks known facts.
    return {
        "profile": {} if forgetful else profile_view(state, include_dietary=not drift),
        "today_context": {} if forgetful else values(state.get("session_context")),
        "dietary_known": (True if drift else False if forgetful else dietary_known(state)),
        "transcript": last_user_message(state) if forgetful else recent_transcript(state, 8),
        "drift": drift,
    }


# --------------------------------------------------------------------------- steps
def _decide(state, ctx, mem, settings) -> AdvisorDecision:
    task = state.get("active_task") or {}
    same_task = task.get("intent") == "tonight_decision"
    prompt = pick_prompt(PROMPTS, settings)
    if mem["drift"]:
        prompt = prompt.replace("1. ALLERGY GATE", "1. (skip)")
    context = {
        "now": ctx["now"], "target_meal_guess": ctx["target_meal"], "target_day_guess": ctx["target_day"],
        "day_outline": ctx["day_outline"], "planned_meal_for_slot": ctx["planned"],
        "profile": mem["profile"], "today_context": mem["today_context"], "dietary_known": mem["dietary_known"],
        "clarifying_turns_so_far": task.get("clarifying_turns", 0) if same_task else 0,
        "decisions_so_far": task.get("decisions_so_far", {}) if same_task else {},
        "previous_recommendation": state.get("tonight_recommendation") if same_task else None,
    }
    return structured(AGENT, "decide", AdvisorDecision, [
        system(prompt),
        human(f"CONTEXT: {dumps(context)}\n\nCONVERSATION:\n{mem['transcript']}"),
    ], settings)


def _recipe_search(state, ctx, mem, decision, settings, config, violations=None):
    context = {"mode": decision.mode, "target_meal": decision.target_meal,
               "time_available_minutes": decision.time_available_minutes,
               "profile": mem["profile"], "today_context": mem["today_context"],
               "planned_meal_for_slot": ctx["planned"],
               "previous_recommendation": state.get("tonight_recommendation"),
               "violations_to_fix": violations}
    convo = tool_loop(AGENT, "recipe_search", [search_recipes, find_recipes_by_ingredients, get_recipe], [
        system(_RECOMMEND_V1),
        human(f"CONTEXT: {dumps(context)}\nUser said: {last_user_message(state)}"),
    ], settings, config)
    return convo


def _final(ctx, mem, decision, settings, transcript=None, extra=None) -> TonightRecommendation:
    msgs = [system(_FINAL_V1), *(transcript or []),
            human(f"Decision: {decision.model_dump_json()}\nNow: {dumps(ctx['now'])}\n"
                  f"Day outline: {dumps(ctx['day_outline'])}\n"
                  f"Profile: {dumps(mem['profile'])}\nToday: {dumps(mem['today_context'])}\n"
                  + (f"Extra: {dumps(extra)}\n" if extra else "")
                  + "Write the TonightRecommendation now.")]
    return structured(AGENT, "finalize", TonightRecommendation, msgs, settings)


def _from_memory(ctx, mem, decision, settings) -> TonightRecommendation:
    return structured(AGENT, "recommend_from_memory", TonightRecommendation, [
        system(_HALLUCINATE),
        human(f"Decision: {decision.model_dump_json()}\nNow: {dumps(ctx['now'])}\n"
              f"Profile: {dumps(mem['profile'])}\nToday: {dumps(mem['today_context'])}"),
    ], settings)


def _recommend_recipe(state, ctx, mem, decision, settings, config, violations=None) -> Dict[str, Any]:
    if settings.has("INJECT_HALLUCINATED_RECIPE"):
        rec = _from_memory(ctx, mem, decision, settings)
    else:
        convo = _recipe_search(state, ctx, mem, decision, settings, config, violations)
        rec = _final(ctx, mem, decision, settings, transcript=convo[1:],
                     extra={"violations_to_fix": violations} if violations else None)
    return {"tonight_recommendation": rec.model_dump(),
            "check_target": "tonight" if rec.primary.recipe_id else None,
            "active_task": _task(state, decision, "recommended", 0)}


def _task(state, decision: AdvisorDecision, status: str, clarifying: int) -> Dict[str, Any]:
    prev = (state.get("active_task") or {})
    decisions = dict(prev.get("decisions_so_far", {})) if prev.get("intent") == "tonight_decision" else {}
    decisions.update({k: v for k, v in {"mode": decision.mode, "target_meal": decision.target_meal,
                                        "target_day": decision.target_day,
                                        "time_available": decision.time_available_minutes}.items() if v is not None})
    return {"intent": "tonight_decision", "agent": AGENT, "status": status,
            "pending_question": " ".join(decision.questions) if status == "asking" else None,
            "question_targets": decision.question_targets if status == "asking" else [],
            "clarifying_turns": clarifying, "decisions_so_far": decisions,
            "started_turn": prev.get("started_turn", state.get("turn_index", 0))
            if prev.get("intent") == "tonight_decision" else state.get("turn_index", 0)}


# --------------------------------------------------------------------------- node
def meal_advisor(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    settings = Settings.from_config(config)
    mem = _memory(state, settings)
    step, check = state.get("advisor_step"), state.get("constraint_check")

    # Re-entry: constraint_checker rejected the recipe -> one revision with the violations.
    if step and check and not check.get("passed"):
        ctx, decision = state["advisor_ctx"], AdvisorDecision(**step)
        return _recommend_recipe(state, ctx, mem, decision, settings, config, violations=check["violations"])

    # Fresh turn: gather context with tools, then ask or commit.
    ctx = _gather(state, settings, config)
    decision = _decide(state, ctx, mem, settings)
    decision.questions = decision.questions[:2]
    out: Dict[str, Any] = {"advisor_step": decision.model_dump(), "advisor_ctx": ctx}

    prev = state.get("active_task") or {}
    prior_q = prev.get("clarifying_turns", 0) if prev.get("intent") == "tonight_decision" else 0
    if decision.action == "ask" and decision.questions:
        out["active_task"] = _task(state, decision, "asking", prior_q + 1)
        return out

    if decision.mode == "skip":
        rec = TonightRecommendation(mode="skip", target_meal=decision.target_meal, target_day=decision.target_day,
                                    primary={"name": "No meal needed", "why": decision.reasoning}, time_plan="")
        out.update({"tonight_recommendation": rec.model_dump(), "check_target": None,
                    "active_task": _task(state, decision, "recommended", 0)})
        return out

    out.update(_recommend_recipe(state, ctx, mem, decision, settings, config))
    return out
