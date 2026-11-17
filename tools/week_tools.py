"""Week outline: turns the user's answers ("which nights are toughest?", "any nights out?") into a
per-day time budget for the next 7 days (today first). Deterministic; it stands in for calendar
integration (see dormant/calendar/).
"""
from datetime import date
from typing import Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from config import DAY_KEYS, Settings, plan_window

WEEKEND = {"sat", "sun"}
DINNER_MINUTES = {"minimal": 30, "moderate": 60, "happy_to_cook": 90}
DEFAULT_DINNER_MINUTES = 60
BUSY_DINNER_MINUTES = 20


def _norm(days: Optional[List[str]]) -> List[str]:
    return [d.strip().lower()[:3] for d in (days or []) if d and d.strip().lower()[:3] in DAY_KEYS]


def week_outline(dates: List[date], busy_nights: Optional[List[str]] = None, nights_out: Optional[List[str]] = None,
                 weeknight_effort: Optional[str] = None) -> Dict[str, dict]:
    """{day_key: {...}} in plan order (dict order == dates order)."""
    busy, out = set(_norm(busy_nights)), set(_norm(nights_out))
    weeknight = DINNER_MINUTES.get(weeknight_effort or "", DEFAULT_DINNER_MINUTES)
    week = {}
    cook_night_seen = False  # is there an earlier regular night in the window to batch cook on?
    for dt in dates:
        d = DAY_KEYS[dt.weekday()]
        weekend = d in WEEKEND
        if d in out:
            dinner = {"cook_minutes": 0, "suggested_mode": "skip", "reason": "eating out / plans this night"}
            kind = "out"
        elif d in busy:
            if cook_night_seen:
                dinner = {"cook_minutes": BUSY_DINNER_MINUTES, "suggested_mode": "leftovers",
                          "reason": "one of the toughest nights - leftovers from an earlier batch cook"}
            else:
                dinner = {"cook_minutes": BUSY_DINNER_MINUTES, "suggested_mode": "quick_meal",
                          "reason": "one of the toughest nights, with no earlier night to batch cook on - <=20 min meal"}
            kind = "busy"
        elif weekend:
            dinner = {"cook_minutes": 90, "suggested_mode": "cook_from_scratch", "reason": "weekend - time for a bigger recipe"}
            kind = "weekend"
        else:
            dinner = {"cook_minutes": weeknight, "suggested_mode": "cook_from_scratch" if weeknight >= 45 else "quick_meal",
                      "reason": f"regular weeknight (~{weeknight} min)"}
            kind = "weeknight"
        cook_night_seen = cook_night_seen or kind in ("weeknight", "weekend")
        week[d] = {"day": d, "date": dt.isoformat(), "kind": kind, "dinner": dinner,
                   "lunch": {"cook_minutes": 30 if weekend else 15,
                             "suggested_mode": "cook_from_scratch" if weekend else "quick_meal",
                             "reason": "weekend lunch" if weekend else "workday lunch - quick or leftovers"},
                   "breakfast": {"cook_minutes": 30 if weekend else 10, "suggested_mode": "quick_meal",
                                 "reason": "weekend breakfast" if weekend else "weekday breakfast"}}
    return week


@tool
def get_week_outline(config: RunnableConfig, busy_nights: Optional[List[str]] = None,
                     nights_out: Optional[List[str]] = None, weeknight_effort: Optional[str] = None) -> Dict[str, dict]:
    """Per-day cooking time budget for the next 7 days (starting today), from the user's busy nights,
    nights out and weeknight effort.

    busy_nights / nights_out: day keys like ['tue', 'thu']. weeknight_effort: minimal|moderate|happy_to_cook.
    Returns {day: {date, kind, dinner: {cook_minutes, suggested_mode, reason}, lunch: {...}, breakfast: {...}}}
    in plan order."""
    dates = plan_window(Settings.from_config(config).now)
    return week_outline(dates, busy_nights, nights_out, weeknight_effort)
