"""Pydantic models for the dormant restaurant feature (moved out of state.py)."""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from state import Day


class Restaurant(BaseModel):
    id: str
    name: str
    cuisine: str
    price_level: int = Field(ge=1, le=4)
    distance_miles_from_home: float
    distance_miles_from_office: float
    # "HH:MM" open/close; close < open means it closes after midnight.
    hours: Dict[Day, Optional[List[str]]]
    dietary_options: List[str]
    allergen_notes: str
    avg_wait_minutes: int
    good_for: List[Literal["quick_lunch", "sit_down_dinner", "takeout", "delivery"]]
    accepts_reservations: bool


class RestaurantRequest(BaseModel):
    purpose: Literal["tonight", "search", "weekly"]
    day: str = "today"
    meal: Literal["breakfast", "lunch", "dinner"] = "dinner"
    at_time: Optional[str] = Field(None, description="ISO datetime the user wants to eat")
    near: Literal["home", "office"] = "home"
    dietary: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    max_price_level: Optional[int] = None
    cuisine_prefs: List[str] = Field(default_factory=list)
    style: Optional[Literal["quick_lunch", "sit_down_dinner", "takeout", "delivery"]] = None
    notes: str = ""


class RestaurantPick(BaseModel):
    restaurant_id: str
    name: str
    why: str
    open_check: str = Field(description="e.g. 'open until 23:00 tonight (is_open checked)'")
    for_slot: Optional[str] = Field(None, description="weekly plan slot, e.g. 'thu dinner'")


class RestaurantPicks(BaseModel):
    picks: List[RestaurantPick]
    note: str = ""
