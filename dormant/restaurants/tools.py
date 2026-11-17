"""DORMANT. Restaurant tools over dormant/restaurants/data/restaurants.json. `is_open` is checked against simulated time."""
from datetime import datetime, time, timedelta
from typing import List, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from config import DAY_KEYS, HOME_TZ, Settings
from dormant.restaurants.data_loader import restaurants
from dormant.restaurants.models import Restaurant


def _t(s: str) -> time:
    return time(*map(int, s.split(":")))


def open_at(r: Restaurant, at: datetime) -> bool:
    """Handles closing after midnight (close <= open), including spillover from the previous day."""
    day, prev = DAY_KEYS[at.weekday()], DAY_KEYS[(at.weekday() - 1) % 7]
    now_t = at.time()
    today = r.hours.get(day)
    if today:
        o, c = _t(today[0]), _t(today[1])
        if c > o and o <= now_t < c:
            return True
        if c <= o and now_t >= o:  # overnight: open until after midnight
            return True
    yesterday = r.hours.get(prev)
    if yesterday:
        o, c = _t(yesterday[0]), _t(yesterday[1])
        if c <= o and now_t < c:
            return True
    return False


def _parse_at(at: Optional[str], settings: Settings) -> datetime:
    if not at or at.lower() == "now":
        return settings.now
    dt = datetime.fromisoformat(at)
    return dt if dt.tzinfo else dt.replace(tzinfo=HOME_TZ)


def _summary(r: Restaurant, near: str) -> dict:
    return {"id": r.id, "name": r.name, "cuisine": r.cuisine, "price_level": r.price_level,
            "distance_miles": r.distance_miles_from_office if near == "office" else r.distance_miles_from_home,
            "dietary_options": r.dietary_options, "allergen_notes": r.allergen_notes,
            "avg_wait_minutes": r.avg_wait_minutes, "good_for": r.good_for,
            "accepts_reservations": r.accepts_reservations}


@tool
def search_restaurants(config: RunnableConfig, cuisine: Optional[str] = None, dietary: Optional[List[str]] = None,
                       near: str = "home", max_distance_miles: Optional[float] = None,
                       max_price_level: Optional[int] = None, good_for: Optional[str] = None,
                       open_at_time: Optional[str] = None, limit: int = 6) -> List[dict]:
    """Search nearby restaurants. near: 'home'|'office'. dietary: e.g. ['vegetarian','gluten_free'].
    good_for: quick_lunch|sit_down_dinner|takeout|delivery. open_at_time: ISO datetime or 'now' to keep only
    places open then (uses the simulated clock). Results sorted by distance."""
    settings = Settings.from_config(config)
    at = _parse_at(open_at_time, settings) if open_at_time else None
    out = []
    for r in restaurants().values():
        if cuisine and cuisine.lower() not in r.cuisine.lower():
            continue
        if dietary and not set(dietary) <= set(r.dietary_options):
            continue
        if max_price_level and r.price_level > max_price_level:
            continue
        if good_for and good_for not in r.good_for:
            continue
        if at and not open_at(r, at):
            continue
        s = _summary(r, near)
        if max_distance_miles and s["distance_miles"] > max_distance_miles:
            continue
        if at:
            s["open_at_requested_time"] = True
        out.append(s)
    out.sort(key=lambda s: s["distance_miles"])
    return out[:limit]


@tool
def get_restaurant(restaurant_id: str) -> dict:
    """Full restaurant record including weekly hours, by id."""
    r = restaurants().get(restaurant_id)
    return r.model_dump() if r else {"error": f"no restaurant with id '{restaurant_id}'"}


@tool
def is_open(restaurant_id: str, config: RunnableConfig, at: Optional[str] = None) -> dict:
    """Is the restaurant open at `at` (ISO datetime; default = current simulated time)?"""
    r = restaurants().get(restaurant_id)
    if not r:
        return {"error": f"no restaurant with id '{restaurant_id}'"}
    when = _parse_at(at, Settings.from_config(config))
    hours = r.hours.get(DAY_KEYS[when.weekday()])
    return {"restaurant_id": r.id, "name": r.name, "at": when.isoformat(), "open": open_at(r, when),
            "hours_that_day": hours or "closed"}
