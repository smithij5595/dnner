"""LangGraph definition for Dnner.

profile_updater -> orchestrator -> (route by intent)
  tonight_decision   : meal_advisor [-> constraint_checker (1 retry)] -> composer
  weekly_plan        : [intake_agent ->] meal_planner -> constraint_checker (2 retries) -> grocery_agent -> composer
  replan             : meal_planner -> ... (same as weekly)
  food_qa            : food_qa -> composer
  recipe_request     : recipe_lookup -> composer   (deterministic: no LLM, no new search)
  plan_question / update_preferences / smalltalk_or_out_of_scope : composer

The restaurant and calendar agents were scoped out; they live in dormant/ and are not part of the graph.
Busy nights come from the user ("Which days this week are toughest to cook dinner?") via tools/week_tools.py.
"""
import uuid
from typing import Any, Dict, Optional, Tuple

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.composer import response_composer
from agents.constraint_checker import constraint_checker
from agents.food_qa import food_qa
from agents.grocery import grocery_agent
from agents.intake import intake_agent, missing_fields
from agents.meal_advisor import meal_advisor
from agents.orchestrator import orchestrator
from agents.planner import meal_planner
from agents.profile_updater import profile_updater
from agents.recipe_lookup import recipe_lookup
from config import Settings
from run_record import RunRecorder, build_record, save_record
from state import DnnerState


# --------------------------------------------------------------------------- routing
def route_intent(state: DnnerState, config=None) -> str:
    intent = state.get("detected_intent")
    if intent == "tonight_decision":
        return "meal_advisor"
    if intent == "weekly_plan":
        return "intake_agent" if missing_fields(state) else "meal_planner"
    if intent == "replan":
        return "meal_planner"
    if intent == "food_qa":
        return "food_qa"
    if intent == "recipe_request":
        return "recipe_lookup"
    # --- FAILURE INJECTION: INJECT_ROUTER_OVERCALL ---------------------------------------
    # Read-only plan questions re-run the whole planning pipeline instead of reading the saved plan.
    if intent == "plan_question" and Settings.from_config(config).has("INJECT_ROUTER_OVERCALL"):
        return "meal_planner"
    return "response_composer"  # plan_question, update_preferences, smalltalk_or_out_of_scope


def after_intake(state: DnnerState) -> str:
    return "meal_planner" if (state.get("intake") or {}).get("complete") else "response_composer"


def after_advisor(state: DnnerState) -> str:
    if (state.get("advisor_step") or {}).get("action") == "ask":
        return "response_composer"
    if state.get("check_target") == "tonight":
        return "constraint_checker"
    return "response_composer"


def after_check(state: DnnerState) -> str:
    target = state.get("check_target")
    if state.get("retry_requested"):
        return "meal_planner" if target == "plan" else "meal_advisor"
    return "grocery_agent" if target == "plan" else "response_composer"


# --------------------------------------------------------------------------- graph
def build_graph(checkpointer=None):
    g = StateGraph(DnnerState)
    for name, fn in [("profile_updater", profile_updater), ("orchestrator", orchestrator),
                     ("meal_advisor", meal_advisor), ("food_qa", food_qa), ("intake_agent", intake_agent),
                     ("meal_planner", meal_planner), ("recipe_lookup", recipe_lookup),
                     ("constraint_checker", constraint_checker), ("grocery_agent", grocery_agent),
                     ("response_composer", response_composer)]:
        g.add_node(name, fn)

    g.add_edge(START, "profile_updater")
    g.add_edge("profile_updater", "orchestrator")
    g.add_conditional_edges("orchestrator", route_intent,
                            ["meal_advisor", "intake_agent", "meal_planner", "food_qa", "recipe_lookup",
                             "response_composer"])
    g.add_conditional_edges("intake_agent", after_intake, ["meal_planner", "response_composer"])
    g.add_conditional_edges("meal_advisor", after_advisor, ["constraint_checker", "response_composer"])
    g.add_edge("meal_planner", "constraint_checker")
    g.add_conditional_edges("constraint_checker", after_check,
                            ["meal_planner", "meal_advisor", "grocery_agent", "response_composer"])
    g.add_edge("grocery_agent", "response_composer")
    g.add_edge("food_qa", "response_composer")
    g.add_edge("recipe_lookup", "response_composer")
    g.add_edge("response_composer", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


# --------------------------------------------------------------------------- one turn
PER_TURN_RESET = {"routing": None, "detected_intent": None, "advisor_step": None, "advisor_ctx": None,
                  "check_target": None,
                  "constraint_check": None, "retries": 0, "retry_requested": False, "food_answer": None, "recipe_details": None,
                  "intake": None, "plan_changes": None, "final_response": ""}


def new_session_id() -> str:
    return "s_" + uuid.uuid4().hex[:10]


def next_turn_index(graph, session_id: str) -> int:
    snapshot = graph.get_state({"configurable": {"thread_id": session_id}})
    return (snapshot.values.get("turn_index", -1) + 1) if snapshot and snapshot.values else 0


def invoke_turn(graph, session_id: str, user_message: str, settings: Settings,
                save: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run one user turn. Returns (final_state, run_record). Callers wrap this in trace_context()."""
    turn = next_turn_index(graph, session_id)
    recorder = RunRecorder()
    config = {"configurable": {"thread_id": session_id, **settings.to_configurable()},
              "callbacks": [recorder], "run_name": "dnner_turn",
              "tags": [f"prompt:{settings.prompt_version}"] + [f"failure:{f}" for f in sorted(settings.failures)],
              "metadata": {"session_id": session_id, "turn_index": turn, "scenario_id": settings.scenario_id},
              "recursion_limit": 40}
    inputs = {**PER_TURN_RESET, "messages": [HumanMessage(content=user_message)],
              "session_id": session_id, "turn_index": turn}
    error: Optional[str] = None
    try:
        graph.invoke(inputs, config=config)
    except Exception as exc:  # keep the demo alive; the record captures the failure
        error = f"{type(exc).__name__}: {exc}"
    state = graph.get_state({"configurable": {"thread_id": session_id}}).values
    record = build_record(recorder, state, session_id=session_id, turn_index=turn, settings=settings,
                          user_message=user_message, error=error)
    if save:
        save_record(record)
    return state, record


# --------------------------------------------------------------------------- preferences panel
def get_values(graph, session_id: str) -> Dict[str, Any]:
    snapshot = graph.get_state({"configurable": {"thread_id": session_id}})
    return (snapshot.values if snapshot else None) or {}


def save_profile(graph, session_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Write a profile edited in the UI straight into the checkpoint (no LLM call, no trace).

    Recorded as if the composer ran last, so the next invoke starts cleanly from START.
    """
    graph.update_state({"configurable": {"thread_id": session_id}}, {"profile": profile},
                       as_node="response_composer")
    return get_values(graph, session_id)
