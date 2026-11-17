"""Models for the dormant calendar feature (moved out of state.py)."""
from typing import List, Optional

from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    id: str
    title: str
    day_offset: int = Field(ge=0, le=6)
    start: str  # "HH:MM", local to `timezone` (defaults to home timezone)
    end: str
    location: str = ""
    all_day: bool = False
    description: str = ""  # UNTRUSTED free text
    timezone: Optional[str] = None


class CalendarWeek(BaseModel):
    home_timezone: str
    home_location: str
    office_location: str
    events: List[CalendarEvent]


class CalendarNotes(BaseModel):
    notes: List[str] = Field(description="one short planning note per day, e.g. 'tue: 30 free min before school event -> 15-min meal'")
