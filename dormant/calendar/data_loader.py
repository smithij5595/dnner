"""Cached loader for dormant/calendar/data/calendar_week.json."""
import json
from functools import lru_cache
from pathlib import Path

from dormant.calendar.models import CalendarWeek

DATA_FILE = Path(__file__).resolve().parent / "data" / "calendar_week.json"


@lru_cache(maxsize=None)
def calendar() -> CalendarWeek:
    return CalendarWeek(**json.loads(DATA_FILE.read_text()))
