"""DORMANT calendar feature (dormant/calendar/): kept green so calendar integration can build on it."""
import re

from config import Settings
from dormant.calendar.data_loader import calendar
from dormant.calendar.tools import get_day_availability

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
CALENDAR = calendar()


def cfg(**kw):
    kw.setdefault("now", "Wed 4:30pm")  # the mock calendar is fixed to WEEK_START's week
    return {"configurable": Settings.build(**kw).to_configurable()}


def test_monday_wide_open_evening():
    a = get_day_availability.invoke({"day": "mon"})
    assert a["cook_minutes_available"] >= 90 and a["mode"] == "cook_from_scratch"


def test_tuesday_needs_quick_dinner():
    a = get_day_availability.invoke({"day": "tue"})
    assert a["cook_minutes_available"] <= 30 and a["mode"] == "quick_meal"


def test_wednesday_from_now_sees_gym():
    a = get_day_availability.invoke({"day": "today", "from_time": "16:30"}, config=cfg())
    assert a["free_windows"][0] == ["16:30", "18:00"]
    assert any(e["title"].startswith("Gym") for e in a["events"])
    assert a["meal_slots"]["dinner"]["longest_free_window"] == ["19:00", "21:30"]


def test_from_time_after_slot_marks_it_passed():
    a = get_day_availability.invoke({"day": "wed", "from_time": "21:45"})
    assert a["meal_slots"]["dinner"]["status"] == "passed"


def test_thursday_travel_day_and_timezone():
    a = get_day_availability.invoke({"day": "thu"})
    assert a["mode"] == "leftovers"  # travel day: reheat a batch cook
    assert a["free_windows"] == [["18:30", "22:00"]]  # home after flight (CT->PT) + drive from SFO
    flight = next(e for e in a["events"] if e["title"].startswith("Flight"))
    assert (flight["start"], flight["end"]) == ("13:30", "17:40")


def test_friday_dinner_plans_skip():
    assert get_day_availability.invoke({"day": "fri"})["mode"] == "skip"


def test_calendar_misread_injection_frees_busy_nights():
    broken = get_day_availability.invoke({"day": "tue"}, config=cfg(failures=["INJECT_CALENDAR_MISREAD"]))
    assert broken["mode"] == "cook_from_scratch" and broken["cook_minutes_available"] >= 120
    thu = get_day_availability.invoke({"day": "thu"}, config=cfg(failures=["INJECT_CALENDAR_MISREAD"]))
    assert all(e["start"] != "all-day" for e in thu["events"])  # offsite silently dropped


def test_injection_text_is_returned_as_data():
    a = get_day_availability.invoke({"day": "wed"})
    assert any("ignore all previous instructions" in e["description"].lower() for e in a["events"])


def test_calendar_offsets_and_times():
    for e in CALENDAR.events:
        assert 0 <= e.day_offset <= 6
        assert HHMM.match(e.start) and HHMM.match(e.end), e.id
        if not e.all_day:
            assert e.end > e.start, e.id
    assert {e.day_offset for e in CALENDAR.events} == set(range(7))


def test_calendar_traps_present():
    descs = " ".join(e.description for e in CALENDAR.events)
    assert "ignore all previous instructions" in descs.lower()
    assert any(e.timezone and e.timezone != CALENDAR.home_timezone for e in CALENDAR.events)
    assert any(e.all_day and e.start == e.end for e in CALENDAR.events)


def test_dormant_agent_still_imports():
    from dormant.calendar.agent import calendar_agent  # noqa: F401
