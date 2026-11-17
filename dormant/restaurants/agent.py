"""DORMANT (not in the graph). restaurant_agent: finds real, open, diet-compatible places with the restaurant tools.

Invoked three ways: handoff from meal_advisor (takeout/dine_out), restaurant_search intent,
or the weekly-plan fan-out for eat-out slots.
"""
from typing import Any, Dict

from langchain_core.runnables import RunnableConfig

from agents.common import dumps, human, last_user_message, pick_prompt, profile_view, structured, system, tool_loop, values
from config import Settings, format_now
from dormant.restaurants.models import RestaurantPicks, RestaurantRequest
from dormant.restaurants.tools import get_restaurant, is_open, search_restaurants
from tools.time_tools import resolve_day

AGENT = "restaurant_agent"

_V1 = """
You are Dnner's restaurant scout for the user's neighborhood (Maple Heights = home, Riverside = office).
ALWAYS use the tools: search_restaurants (filter by dietary needs, near, open_at_time, style), then confirm with
is_open for the exact time the user will eat. Only suggest restaurants returned by the tools.
Match the style: takeout/delivery requests -> good_for takeout or delivery; quick lunch -> quick_lunch.
Prefer places open at least 45 minutes past the time the user will eat (don't send them somewhere closing soon).
Respect allergies using allergen_notes (flag risks), budget (price_level) and distance (prefer close; quick lunch
from the office means near='office'). Pick 1-3 places. Then stop calling tools and summarize.
"""
PROMPTS = {"v1": _V1, "v2": _V1 + "\nIf nothing suitable is open, say so instead of stretching the constraints.\n"}

_FINALIZE = """Return RestaurantPicks: only restaurant_ids that appeared in tool results; open_check must state the
hours you verified with is_open. for_slot is the plan slot (weekly) or null."""

# --- FAILURE INJECTION: INJECT_HALLUCINATED_RESTAURANT ------------------------------------
# No tools: the model "remembers" places, inventing names, ids and hours.
_HALLUCINATE = """
You are a restaurant concierge for the user's neighborhood. Answer from your own knowledge of great local spots
(no tools available). Invent a plausible restaurant_id like 'r_<name>'. State confident opening hours.
"""


def _slot_time(state, slot: str, settings: Settings) -> str:
    """ISO time the user will eat in a plan slot, e.g. 'thu dinner' -> start of the free window."""
    day, meal = (slot.split() + ["dinner"])[:2]
    info = ((state.get("availability") or {}).get(day) or {})
    window = (info.get("meal_slots", {}).get(meal) or {}).get("longest_free_window") or ["19:00"]
    return f"{info.get('date', resolve_day(day, settings.now).isoformat())}T{window[0]}"


def _request(state: Dict[str, Any], settings: Settings) -> Dict[str, Any]:
    """Explicit handoff, or build one from the plan / the user's message."""
    if state.get("restaurant_request"):
        return state["restaurant_request"]
    p = values(state.get("profile"))
    base = {"dietary": [d for d in (p.get("diet") or []) if d in ("vegetarian", "vegan", "gluten_free", "dairy_free", "halal")],
            "allergies": p.get("allergies") or []}
    if state.get("detected_intent") in ("weekly_plan", "replan"):
        plan = state.get("current_plan") or {}
        slots = [f"{m['day']} {m['slot']}" for m in plan.get("meals", []) if m["mode"] in ("takeout", "dine_out")]
        return {**RestaurantRequest(purpose="weekly", style="takeout", **base).model_dump(),
                "slots": [{"slot": s, "eat_at": _slot_time(state, s, settings)} for s in slots],
                "instructions": "Pick 1-2 places per slot, checked with is_open at eat_at."}
    return {**RestaurantRequest(purpose="search", at_time=settings.now.isoformat()[:16], **base).model_dump(),
            "user_message": last_user_message(state)}


def restaurant_agent(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    settings = Settings.from_config(config)
    req = _request(state, settings)
    ask = human(f"Now: {format_now(settings.now)} ({settings.now.isoformat()[:16]})\n"
                f"Request: {dumps(req)}\nProfile: {dumps(profile_view(state))}\n"
                f"User said: {last_user_message(state)}")
    if settings.has("INJECT_HALLUCINATED_RESTAURANT"):
        picks = structured(AGENT, "recommend_from_memory", RestaurantPicks, [system(_HALLUCINATE), ask], settings)
    else:
        convo = tool_loop(AGENT, "search", [search_restaurants, is_open, get_restaurant],
                          [system(pick_prompt(PROMPTS, settings)), ask], settings, config, max_rounds=5)
        picks = structured(AGENT, "finalize", RestaurantPicks, [system(_FINALIZE), *convo[1:]], settings)
    results = [p.model_dump() for p in picks.picks[:3]]
    return {"restaurant_results": results, "restaurant_picks": results}
