"""Configuration: env vars, model names, simulated "now", prompt version, failure flags.

Time: the app uses the REAL current time (HOME_TZ). A simulated "now" is only used when a caller passes
one explicitly, i.e. the scenario runner (`scenario["now"]`, `--now`, or NOW_OVERRIDE).

Per-turn settings (time, prompt version, failure flags, scenario id) travel
through LangGraph's `config["configurable"]`, so each Gradio session / scenario can use
different values without touching globals. Use `Settings.from_config(config)` anywhere
(nodes or tools) to read them; env vars only provide the defaults.
"""
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
load_dotenv(ROOT / ".env")

HOME_TZ = ZoneInfo(os.getenv("HOME_TZ", "America/Los_Angeles"))

# --------------------------------------------------------------------------- #
# Models (one env var per agent)
# --------------------------------------------------------------------------- #
DEFAULT_MODELS = {
    "orchestrator": "gpt-4o-mini",
    "profile_updater": "gpt-4o-mini",
    "grocery_agent": "gpt-4o-mini",
    "food_qa": "gpt-4o-mini",
    "intake_agent": "gpt-4o-mini",
    "response_composer": "gpt-4o-mini",
    "meal_advisor": "gpt-4o",
    "meal_planner": "gpt-4o",
    "constraint_checker": "gpt-4o",
}


def model_for(agent: str) -> str:
    """MODEL_MEAL_ADVISOR=gpt-4o etc. override the defaults."""
    return os.getenv(f"MODEL_{agent.upper()}", DEFAULT_MODELS.get(agent, "gpt-4o-mini"))


# --------------------------------------------------------------------------- #
# Time. Real clock for the app; simulated only for scripted scenarios.
# --------------------------------------------------------------------------- #
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def real_now() -> datetime:
    return datetime.now(HOME_TZ).replace(second=0, microsecond=0)


def plan_window(now: datetime) -> List[date]:
    """The 7 days a plan covers: today and the next 6 days."""
    return [now.date() + timedelta(days=i) for i in range(7)]


def day_order(now: datetime) -> List[str]:
    """Day keys in plan order, starting today (e.g. ['tue', 'wed', ..., 'mon'])."""
    return [DAY_KEYS[d.weekday()] for d in plan_window(now)]


def _default_week_start() -> date:
    """SCENARIOS ONLY: Monday used to resolve shorthand like 'Thu 8:15pm'. The upcoming Monday (today, if Monday)."""
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


WEEK_START: date = (date.fromisoformat(os.environ["WEEK_START"])
                    if os.getenv("WEEK_START") else _default_week_start())


def _default_now() -> datetime:
    """SCENARIOS ONLY: Wednesday of WEEK_START's week at 4:30pm."""
    return datetime.combine(WEEK_START + timedelta(days=2), time(16, 30), tzinfo=HOME_TZ)


def parse_now(value: Optional[str]) -> datetime:
    """Accepts ISO ('2026-11-11T16:30') or demo shorthand ('Tue 5:45pm', 'thu 20:15')."""
    if not value:
        return _default_now()
    value = value.strip()
    m = re.match(r"^(mon|tue|wed|thu|fri|sat|sun)\w*\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", value, re.I)
    if m:
        day, hh, mm, ampm = m.group(1).lower(), int(m.group(2)), int(m.group(3) or 0), (m.group(4) or "").lower()
        if ampm == "pm" and hh < 12:
            hh += 12
        if ampm == "am" and hh == 12:
            hh = 0
        d = WEEK_START + timedelta(days=DAY_KEYS.index(day))
        return datetime.combine(d, time(hh, mm), tzinfo=HOME_TZ)
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=HOME_TZ)


# SCENARIOS ONLY: default simulated time for scenarios that don't set "now" (never used by the app).
NOW_OVERRIDE: Optional[str] = os.getenv("NOW_OVERRIDE") or None


def format_now(dt: datetime) -> str:
    return dt.strftime("%a %-I:%M%p").replace("AM", "am").replace("PM", "pm")


# --------------------------------------------------------------------------- #
# Prompt version + failure flags
# --------------------------------------------------------------------------- #
PROMPT_VERSIONS = ["v1", "v2"]
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v1")

# name -> what breaks (shown in the UI and README)
FAILURE_FLAGS: Dict[str, str] = {
    "INJECT_IGNORES_BUSY_NIGHTS": "Planner never sees the busy nights / nights out -> long recipes on the toughest nights",
    "INJECT_CONSTRAINT_DRIFT": "After a replan / turn 3+, planner + advisor prompts omit the dietary profile",
    "INJECT_GROCERY_SCALING_BUG": "Grocery agent ignores batch-cook multipliers when scaling quantities",
    "INJECT_HALLUCINATED_RECIPE": "Meal advisor names a recipe from memory without calling the recipe tools",
    "INJECT_ALLERGEN_MISS": "Constraint checker prompt weakened: allergens are not checked",
    "INJECT_ROUTER_OVERCALL": "Read-only plan questions re-run planner -> checker -> grocery instead of reading the plan",
    "INJECT_ROUTER_MISCLASSIFY": "Orchestrator prompt weakened: food questions + short follow-ups get misrouted",
    "INJECT_FORGETFUL_ADVISOR": "Meal advisor ignores profile/session context and re-asks known info",
    "INJECT_OVERCONFIDENT_FOOD_QA": "Food QA prompt drops safety/uncertainty guidance",
}


# Flags used only by code in dormant/ (not offered in the UI or scenario runner).
DORMANT_FLAGS: Dict[str, str] = {
    "INJECT_HALLUCINATED_RESTAURANT": "Restaurant agent answers from memory without calling its tools",
    "INJECT_CALENDAR_MISREAD": "Calendar tool shifts times (UTC bug) and drops all-day events",
    "INJECT_INJECTION_VULNERABLE": "Calendar text is concatenated as instructions instead of quoted data",
    "INJECT_SKIPS_SCHEDULE": "Meal advisor skips calendar tools and recommends without checking time",
}


def _env_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


ENV_FAILURES: FrozenSet[str] = frozenset(f for f in FAILURE_FLAGS if _env_flag(f))


@dataclass(frozen=True)
class Settings:
    """Per-invocation settings. Built by the UI/scenario runner, read by nodes + tools."""
    now: datetime = field(default_factory=real_now)
    prompt_version: str = PROMPT_VERSION
    failures: FrozenSet[str] = ENV_FAILURES
    scenario_id: Optional[str] = None

    def has(self, flag: str) -> bool:
        assert flag in FAILURE_FLAGS or flag in DORMANT_FLAGS, flag
        return flag in self.failures

    def to_configurable(self) -> Dict[str, Any]:
        return {"now": self.now.isoformat(), "prompt_version": self.prompt_version,
                "failures": sorted(self.failures), "scenario_id": self.scenario_id}

    @classmethod
    def build(cls, now: Optional[str] = None, prompt_version: Optional[str] = None,
              failures: Optional[Iterable[str]] = None, scenario_id: Optional[str] = None) -> "Settings":
        return cls(now=parse_now(now) if now else real_now(),
                   prompt_version=prompt_version or PROMPT_VERSION,
                   failures=frozenset(failures) if failures is not None else ENV_FAILURES,
                   scenario_id=scenario_id)

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]]) -> "Settings":
        c = (config or {}).get("configurable", {}) or {}
        if "now" not in c:
            return cls()
        return cls(now=parse_now(c["now"]), prompt_version=c.get("prompt_version", PROMPT_VERSION),
                   failures=frozenset(c.get("failures", [])), scenario_id=c.get("scenario_id"))


def flag_list(settings: Settings) -> List[str]:
    return sorted(settings.failures)
