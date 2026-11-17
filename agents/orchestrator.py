"""orchestrator: classifies intent (RoutingDecision) using active_task so follow-ups stay on task."""
from typing import Any, Dict

from langchain_core.runnables import RunnableConfig

from agents.common import dumps, human, last_assistant_message, last_user_message, pick_prompt, structured, system
from config import Settings
from state import RoutingDecision

AGENT = "orchestrator"

_V1 = """
You route messages for Dnner, a home-cooking meal planner.
Pick exactly one intent:

- tonight_decision: any single-meal "what should I eat" question (tonight, lunch, tomorrow's dinner, "I don't
  want to cook", "what can I make with X"), AND follow-ups revising a tonight recommendation
  ("something lighter", "not Thai again", "what if I only have 20 minutes?").
- weekly_plan: user wants a plan for the week / several days.
- replan: change an EXISTING plan ("I'm out Thursday", "swap Tuesday for something lighter").
- plan_question: read-only question about the existing plan or shopping list ("what's Thursday's dinner?").
- update_preferences: the user ONLY tells you about themselves, with no planning request ("I'm cooking for 3 now",
  "we're trying to go dairy-free", "I hate leftovers", "I just got an Instant Pot"). If they also ask to change the
  plan ("...please update the plan") -> replan.
- recipe_request: the user accepts a dish Dnner suggested or asks for the recipe / ingredients / steps of a
  specific dish (one just recommended, one in the plan, or a named recipe): "yes, the tacos please",
  "sounds good, how do I make it?", "what's the recipe for Thursday's dinner?".
- food_qa: general food/cooking knowledge (substitutions, techniques, storage, food-safety temps, nutrition facts).
- smalltalk_or_out_of_scope: greetings, thanks, unrelated requests (including finding restaurants - Dnner only
  plans home cooking), or medical questions beyond general nutrition.

Boundary examples:
- "I don't want to cook tonight" -> tonight_decision (the advisor finds leftovers or a minimal-effort meal).
- "What should I do for lunch tomorrow?" -> tonight_decision.
- "Where can I grab a quick vegetarian lunch near the office?" -> smalltalk_or_out_of_scope (restaurants are out of scope).
- "Saturday's our anniversary, we're going out" (plan exists) -> replan (Saturday dinner becomes skip).
- "I've gone vegetarian - please update the plan" -> replan (a preference change PLUS a request to change the plan).
- "We're trying to go dairy-free" (no request) -> update_preferences.
- "How long does cooked chicken last?" -> food_qa, even in the middle of planning.
- "Yes, I'd like the tacos. Please give me the recipe" (after a recommendation) -> recipe_request, NOT
  tonight_decision: the decision is made, they want the recipe.
- "Hmm, something lighter than the tacos?" -> tonight_decision (a revision, not an acceptance).
- "Can I use flour tortillas instead?" -> food_qa.

ACTIVE TASK RULE: if an active task has a pending question, a short reply that answers it ("kinda tired honestly",
"just me", "nope", "chicken and rice") belongs to that task's intent. Only switch if the user clearly starts
something new (e.g. asks a cooking question mid-planning -> food_qa).
"""

# --- FAILURE INJECTION: INJECT_ROUTER_MISCLASSIFY --------------------------------------
# "Prompt v1 -> v2 regression": the intent guide is shortened and the active-task rule is
# removed, so food questions drift to weekly_plan and short replies get reclassified.
_WEAK = """
You route messages for a meal-planning app. Intents: tonight_decision, weekly_plan, replan, plan_question,
update_preferences, food_qa, smalltalk_or_out_of_scope.
Most users want meal plans, so prefer weekly_plan for anything about food, cooking or meals.
Classify each message on its own.
"""

PROMPTS = {"v1": _V1, "v2": _V1 + """
When confidence is low between food_qa and a planning intent, prefer food_qa (cheaper, reversible).
"""}


def _rec_names(rec):
    if not rec:
        return None
    return {"primary": (rec.get("primary") or {}).get("name"),
            "alternatives": [a.get("name") for a in rec.get("alternatives") or []]}


def orchestrator(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    settings = Settings.from_config(config)
    weak = settings.has("INJECT_ROUTER_MISCLASSIFY")
    task = state.get("active_task")
    context = {
        "has_weekly_plan": bool(state.get("current_plan")),
        "last_recommendation": _rec_names(state.get("tonight_recommendation")),
        "active_task": None if weak else task,
        "assistant_previous_message": None if weak else last_assistant_message(state),
    }
    decision = structured(AGENT, "route", RoutingDecision, [
        system(_WEAK if weak else pick_prompt(PROMPTS, settings)),
        human(f"Context: {dumps(context)}\nUser message: {last_user_message(state)}"),
    ], settings)
    # Guard: replan / plan_question need a plan to exist.
    if decision.intent in ("replan", "plan_question") and not state.get("current_plan"):
        decision = RoutingDecision(intent="weekly_plan", confidence=decision.confidence,
                                   reason=decision.reason + " (no plan yet -> weekly_plan)")
    return {"routing": decision.model_dump(), "detected_intent": decision.intent}
