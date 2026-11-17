"""Clock tools. "Now" ALWAYS comes from Settings (real time in the app, simulated in scenarios)."""
from datetime import date, datetime, timedelta

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from config import DAY_KEYS, DAY_NAMES, HOME_TZ, Settings


def resolve_day(day: str, now: datetime) -> date:
    """'today' | 'tonight' | 'tomorrow' | 'wed' | 'Wednesday' | '2026-11-11'. Day names mean the next
    occurrence within the 7-day plan window (today counts)."""
    d = (day or "today").strip().lower()
    if d in ("today", "tonight", "now"):
        return now.date()
    if d == "tomorrow":
        return now.date() + timedelta(days=1)
    if d[:3] in DAY_KEYS:
        return now.date() + timedelta(days=(DAY_KEYS.index(d[:3]) - now.weekday()) % 7)
    return date.fromisoformat(d)


def _hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


@tool
def get_current_time(config: RunnableConfig) -> dict:
    """Return the current date and time for the user. Always use this instead of guessing."""
    now = Settings.from_config(config).now
    return {"now": now.isoformat(), "day": DAY_KEYS[now.weekday()], "day_name": DAY_NAMES[now.weekday()],
            "time": _hhmm(now), "timezone": str(HOME_TZ)}
