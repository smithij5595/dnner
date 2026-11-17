"""DORMANT restaurant feature (dormant/restaurants/): kept green so it can be wired back in."""
import json
import re

from config import Settings
from dormant.restaurants.data_loader import DATA_FILE
from dormant.restaurants.models import Restaurant
from dormant.restaurants.tools import is_open, search_restaurants
from state import DAYS

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
RESTAURANTS = [Restaurant(**r) for r in json.loads(DATA_FILE.read_text())]


def cfg(**kw):
    kw.setdefault("now", "Wed 4:30pm")
    return {"configurable": Settings.build(**kw).to_configurable()}


def test_restaurant_hours_format():
    for r in RESTAURANTS:
        assert set(r.hours) == set(DAYS), r.id
        for day, span in r.hours.items():
            if span is None:
                continue
            assert len(span) == 2 and all(HHMM.match(t) for t in span), (r.id, day)
            assert span[0] != span[1], (r.id, day)


def test_restaurant_variety_for_traps():
    closed_some_day = [r for r in RESTAURANTS if any(v is None for v in r.hours.values())]
    late = [r for r in RESTAURANTS
            if r.hours["thu"] and (r.hours["thu"][1] >= "22:30" or r.hours["thu"][1] < r.hours["thu"][0])]
    lunch_only = [r for r in RESTAURANTS if all(v is None or v[1] <= "15:00" for v in r.hours.values())]
    sunday_early = [r for r in RESTAURANTS
                    if r.hours["sun"] and r.hours["mon"] and r.hours["sun"][1] < r.hours["mon"][1]]
    assert len(closed_some_day) >= 4 and len(late) >= 3 and len(lunch_only) >= 3 and len(sunday_early) >= 2


def test_is_open_basic_and_closed_day():
    assert is_open.invoke({"restaurant_id": "r_lucias_trattoria", "at": "2026-11-11T19:00"})["open"]
    assert not is_open.invoke({"restaurant_id": "r_lucias_trattoria", "at": "2026-11-09T19:00"})["open"]  # Mon


def test_is_open_after_midnight_spillover():
    # Taqueria del Sol: Fri 10:00-01:00 -> open Sat 00:30, closed Sat 01:30
    assert is_open.invoke({"restaurant_id": "r_taqueria_sol", "at": "2026-11-14T00:30"})["open"]
    assert not is_open.invoke({"restaurant_id": "r_taqueria_sol", "at": "2026-11-14T01:30"})["open"]


def test_is_open_defaults_to_simulated_now():
    # Default now = Wed 16:30 -> lunch-only Greenline (10:30-15:00) is closed
    assert not is_open.invoke({"restaurant_id": "r_greenline_salads"}, config=cfg())["open"]


def test_search_restaurants_late_thursday():
    res = search_restaurants.invoke({"dietary": ["vegetarian"], "open_at_time": "now", "limit": 50},
                                    config=cfg(now="Thu 8:15pm"))
    names = {r["name"] for r in res}
    assert "Taqueria del Sol" in names and "Maple Street Diner" not in names


def test_dormant_agent_still_imports():
    from dormant.restaurants.agent import restaurant_agent  # noqa: F401
