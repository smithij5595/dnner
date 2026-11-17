"""profile_updater: entry node. Extracts preferences + transient context from the latest message."""
import re
from typing import Any, Dict

from langchain_core.runnables import RunnableConfig

from agents.common import dumps, human, last_assistant_message, last_user_message, pick_prompt, structured, system, values
from config import Settings
from state import CONTEXT_FIELDS, LIST_FIELDS, PROFILE_FIELDS, ProfileExtraction

AGENT = "profile_updater"

_V1 = """
You extract facts about the user from their LATEST message for a meal-planning assistant.
Return null for every field the LATEST message (or a direct answer to the assistant's question) does not mention.
NEVER invent facts and never repeat facts that are already known. Most messages only touch 0-2 fields.

- Use the assistant's previous message to interpret short answers (e.g. Q: "Any allergies?" A: "nope" -> allergies=[]).
- allergies: "no allergies" / "I eat everything" / "nope" (to an allergy question) -> allergies=[] (NOT null).
  Only true food allergies, normalized to: peanut, tree_nut (cashew, almond, walnut, pecan, pistachio...),
  dairy, egg, gluten, soy, shellfish, fish, sesame.
- diet: lifestyle/diet restrictions (vegetarian, vegan, pescatarian, gluten_free, dairy_free, keto, high_protein...).
  Return [] ONLY when the user explicitly says they have no restrictions, e.g. "no restrictions",
  "no diet restrictions", "no allergies or restrictions", "I eat everything" -> diet=[].
- household_size: count people the user cooks for ("me and my partner" -> 2, "family of 4" -> 4, "just me" -> 1).
  cooking_skill: "decent cook" -> intermediate. meals_to_plan: "dinners only" -> ["dinner"].
- busy_nights: days that are hardest to cook dinner ("Tuesdays and Thursdays are crazy" -> ["tue","thu"];
  "none really" -> []). nights_out: nights they eat elsewhere ("we're out Friday", "anniversary dinner Saturday"
  -> ["fri"] / ["sat"]). Use mon, tue, wed, thu, fri, sat, sun. A night that is no longer busy/out -> replace_fields.
- leftovers_ok: "I hate leftovers" -> false; "love batch cooking" / "maximize leftovers" -> true.
- Transient context (pantry, energy, hunger, who is eating tonight, meals already eaten, mood, craving, location,
  time limit) is about TODAY only. "I'm wiped/exhausted/kinda tired" -> energy=low.
- inferred_fields: list fields you INFERRED rather than the user stating directly (e.g. energy from "long day").
- replace_fields: list fields the user CHANGED (e.g. "actually I'm vegan now" -> diet replaces old diet).
"""
PROMPTS = {"v1": _V1, "v2": _V1 + """
- If unsure whether something is a stated fact, leave it null. Do not treat hypotheticals as facts.
"""}


def merge(existing: Dict[str, Any], extraction: ProfileExtraction, names, turn: int) -> Dict[str, Any]:
    out = dict(existing or {})
    data = extraction.model_dump()
    for name in names:
        new = data.get(name)
        if new is None:
            continue
        old = (out.get(name) or {}).get("value")
        if new == old:
            continue  # unchanged: keep the original turn/source
        if name in LIST_FIELDS and isinstance(old, list) and new and name not in extraction.replace_fields:
            new = sorted(set(old) | set(new))
            if new == sorted(old):
                continue
        out[name] = {"value": new, "source": "inferred" if name in extraction.inferred_fields else "stated",
                     "last_updated_turn": turn}
    return out


NO_ALLERGIES = re.compile(r"\bno (food )?allergies\b|\bnot allergic to anything\b|\bno allergies (or|and|,) (diet(ary)? )?restrictions\b", re.I)
NO_RESTRICTIONS = re.compile(r"\bno (diet(ary)? )?restrictions\b|\bno allergies (or|and|,) (diet(ary)? )?restrictions\b|"
                             r"\b(i )?eat (everything|anything)\b", re.I)


def profile_updater(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    settings = Settings.from_config(config)
    turn = state.get("turn_index", 0)
    known = {"profile": values(state.get("profile")), "session_context": values(state.get("session_context"))}
    extraction = structured(AGENT, "extract", ProfileExtraction, [
        system(pick_prompt(PROMPTS, settings)),
        human(f"Already known: {dumps(known)}\n"
              f"Assistant's previous message: {last_assistant_message(state) or '(none)'}\n"
              f"User's latest message: {last_user_message(state)}"),
    ], settings)
    # Safety net for a common miss: "no allergies or restrictions" -> diet = [] (stated).
    if extraction.diet is None and NO_RESTRICTIONS.search(last_user_message(state)):
        extraction.diet = []
    if extraction.allergies is None and NO_ALLERGIES.search(last_user_message(state)):
        extraction.allergies = []
    return {"profile": merge(state.get("profile"), extraction, PROFILE_FIELDS, turn),
            "session_context": merge(state.get("session_context"), extraction, CONTEXT_FIELDS, turn)}
