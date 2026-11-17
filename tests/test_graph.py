"""Graph wiring and routing (no LLM calls)."""
from config import Settings
from graph import after_check, build_graph, route_intent


def cfg(*flags):
    return {"configurable": Settings.build(failures=list(flags)).to_configurable()}


def test_graph_compiles_without_dormant_agents():
    nodes = set(build_graph().get_graph().nodes)
    assert "restaurant_agent" not in nodes and "calendar_agent" not in nodes
    assert {"meal_planner", "grocery_agent", "meal_advisor", "response_composer"} <= nodes


def test_weekly_plan_goes_through_intake_until_busy_nights_known():
    profile = {k: {"value": v, "source": "stated", "last_updated_turn": 0} for k, v in
               {"allergies": [], "diet": [], "household_size": 2, "meals_to_plan": ["dinner"], "budget": "$6",
                "cooking_skill": "intermediate"}.items()}
    state = {"detected_intent": "weekly_plan", "profile": profile}
    assert route_intent(state, cfg()) == "intake_agent"
    profile["busy_nights"] = {"value": [], "source": "stated", "last_updated_turn": 0}
    assert route_intent(state, cfg()) == "meal_planner"


def test_plan_question_and_preferences_skip_planning():
    for intent in ("plan_question", "update_preferences", "smalltalk_or_out_of_scope"):
        assert route_intent({"detected_intent": intent}, cfg()) == "response_composer"


def test_router_overcall_reruns_planner_on_plan_questions():
    assert route_intent({"detected_intent": "plan_question"}, cfg("INJECT_ROUTER_OVERCALL")) == "meal_planner"


def test_after_check():
    assert after_check({"check_target": "plan"}) == "grocery_agent"
    assert after_check({"check_target": "plan", "retry_requested": True}) == "meal_planner"
    assert after_check({"check_target": "tonight"}) == "response_composer"
