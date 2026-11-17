"""intake_agent: weekly-plan only. Asks for missing required profile fields (allergies first)."""
from typing import Any, Dict, List

from langchain_core.runnables import RunnableConfig

from agents.common import dumps, human, pick_prompt, profile_view, structured, system
from config import Settings
from state import IntakeResult

AGENT = "intake_agent"
# Order matters: allergies/diet are always asked first.
REQUIRED_FIELDS = ["allergies", "diet", "household_size", "meals_to_plan", "busy_nights", "budget", "cooking_skill"]

_V1 = """
You help set up a weekly meal plan. Ask ONLY for the missing fields listed, in ONE short friendly message
(a compact list is fine). Allergies and dietary restrictions come first. Never ask for anything already known.
meals_to_plan means which meals to plan (e.g. dinners only, lunches + dinners). Offer a sensible default where
helpful (e.g. "dinners only?").
busy_nights: ask it as "Which days this week are toughest to cook dinner? (and any nights you're eating out?)"
"""
PROMPTS = {"v1": _V1, "v2": _V1}


def missing_fields(state: Dict[str, Any]) -> List[str]:
    p = state.get("profile") or {}
    return [f for f in REQUIRED_FIELDS if not p.get(f) or p[f].get("value") is None]


def intake_agent(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    settings = Settings.from_config(config)
    missing = missing_fields(state)
    if not missing:
        return {"intake": IntakeResult(complete=True, missing_fields=[]).model_dump()}
    result = structured(AGENT, "ask_missing", IntakeResult, [
        system(pick_prompt(PROMPTS, settings)),
        human(f"Known profile: {dumps(profile_view(state))}\nMissing fields: {missing}"),
    ], settings)
    result.complete, result.missing_fields = False, missing
    prev = state.get("active_task") or {}
    turns = prev.get("clarifying_turns", 0) + 1 if prev.get("agent") == AGENT else 1
    return {"intake": result.model_dump(),
            "active_task": {"intent": "weekly_plan", "agent": AGENT, "status": "asking",
                            "pending_question": result.question, "question_targets": missing,
                            "clarifying_turns": turns, "decisions_so_far": {},
                            "started_turn": prev.get("started_turn", state.get("turn_index", 0))
                            if prev.get("agent") == AGENT else state.get("turn_index", 0)}}
