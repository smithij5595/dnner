"""recipe_lookup: resolving which recipe the user means (no LLM calls)."""
from agents.composer import build_payload
from agents.recipe_lookup import recipe_lookup, resolve
from config import Settings
from graph import build_graph, route_intent
from langchain_core.messages import AIMessage, HumanMessage

REC = {"mode": "quick_meal", "primary": {"recipe_id": "mex_black_bean_tacos", "name": "Smashed Black Bean Tacos",
                                         "why": "busy night"},
       "alternatives": [{"recipe_id": "mex_turkey_taco_skillet", "name": "Turkey Taco Rice Skillet", "why": "x"}],
       "time_plan": "start at 6:40"}


def cfg():
    return {"configurable": Settings.build().to_configurable()}


def state(msg, **extra):
    return {"messages": [AIMessage(content="How about tacos?"), HumanMessage(content=msg)],
            "tonight_recommendation": REC, **extra}


def test_route_and_graph_node():
    assert route_intent({"detected_intent": "recipe_request"}, cfg()) == "recipe_lookup"
    assert "recipe_lookup" in set(build_graph().get_graph().nodes)


def test_the_tacos_picks_recommended_primary():
    rid, how = resolve(state("Yes, I'd like the tacos. Please give me the recipe"), "Yes, I'd like the tacos. Please give me the recipe")
    assert rid == "mex_black_bean_tacos" and how.startswith("name_match:recommended")


def test_alternative_by_name():
    msg = "Actually the turkey skillet, recipe please"
    assert resolve(state(msg), msg)[0] == "mex_turkey_taco_skillet"


def test_plain_acceptance_uses_primary():
    msg = "yes! sounds good"
    assert resolve(state(msg), msg) == ("mex_black_bean_tacos", "accepted_primary")


def test_plan_day_reference():
    plan = {"meals": [{"day": "thu", "slot": "dinner", "recipe_id": "mex_turkey_taco_skillet", "mode": "quick_meal"}]}
    msg = "What's the recipe for Thursday's dinner?"
    assert resolve(state(msg, current_plan=plan), msg) == ("mex_turkey_taco_skillet", "plan:thu dinner")


def test_unknown_dish_not_found():
    msg = "give me the recipe for that thing"
    s = {"messages": [HumanMessage(content=msg)]}
    assert resolve(s, msg) == (None, "not_found")


def test_node_returns_full_recipe_and_composer_payload():
    msg = "Yes, I'd like the tacos. Please give me the recipe"
    s = state(msg, detected_intent="recipe_request",
              profile={"allergies": {"value": ["soy"], "source": "stated", "last_updated_turn": 0}})
    out = recipe_lookup(s, cfg())
    d = out["recipe_details"]
    assert d["recipe"]["id"] == "mex_black_bean_tacos" and d["recipe"]["steps"] and d["recipe"]["ingredients"]
    assert out["active_task"]["intent"] == "recipe_request"
    payload = build_payload({**s, **out}, Settings.build())
    assert payload["kind"] == "recipe" and payload["recipe"]["steps"] == d["recipe"]["steps"]
