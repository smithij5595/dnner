"""Preferences panel <-> profile conversion.

The profile lives in graph state as {field: {"value", "source", "last_updated_turn"}}. The agent
(profile_updater) fills it from chat; this panel lets the user edit it directly (source="manual").
For list fields an explicit "none" choice means "I told you: none" (value []), while an empty
selection means "unknown" (field removed), so intake will still ask about it.
"""
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr

from config import DAY_KEYS, DAY_NAMES

NONE = "none"
ALLERGY_CHOICES = [("No allergies", NONE), ("Peanut", "peanut"), ("Tree nuts", "tree_nut"), ("Dairy", "dairy"),
                   ("Egg", "egg"), ("Gluten", "gluten"), ("Soy", "soy"), ("Shellfish", "shellfish"), ("Fish", "fish"),
                   ("Sesame", "sesame")]
DIET_CHOICES = [("No restrictions", NONE), ("Vegetarian", "vegetarian"), ("Vegan", "vegan"),
                ("Pescatarian", "pescatarian"), ("Gluten-free", "gluten_free"), ("Dairy-free", "dairy_free"),
                ("High protein", "high_protein")]
DAY_CHOICES = [(n[:3], d) for d, n in zip(DAY_KEYS, DAY_NAMES)]
BUSY_CHOICES = [("None", NONE)] + DAY_CHOICES
MEAL_CHOICES = [("Breakfast", "breakfast"), ("Lunch", "lunch"), ("Dinner", "dinner")]
CUISINE_CHOICES = ["Italian", "Mexican", "Indian", "Thai", "Japanese", "Mediterranean", "American comfort", "Chinese"]
SKILL_CHOICES = [("Beginner", "beginner"), ("Intermediate", "intermediate"), ("Advanced", "advanced")]
EFFORT_CHOICES = [("Minimal", "minimal"), ("Moderate", "moderate"), ("Happy to cook", "happy_to_cook")]
LEFTOVER_CHOICES = [("Love them", "yes"), ("Not for me", "no")]

# (field, kind) in the order the components are created in app.py
FIELDS: List[Tuple[str, str]] = [
    ("allergies", "multi_none"), ("diet", "multi_none"), ("dislikes", "text_list"),
    ("household_size", "int"), ("meals_to_plan", "multi"), ("busy_nights", "multi_none"), ("nights_out", "multi"),
    ("budget", "text"), ("leftovers_ok", "bool"),
    ("cooking_skill", "choice"), ("weeknight_effort", "choice"), ("equipment", "text_list"), ("calorie_target", "int"),
    ("favorite_cuisines", "multi"),
]
FIELD_LABELS = {"allergies": "allergies", "diet": "diet", "dislikes": "dislikes", "household_size": "household size",
                "meals_to_plan": "meals to plan", "busy_nights": "tough nights", "nights_out": "nights out",
                "budget": "budget", "leftovers_ok": "leftovers", "cooking_skill": "skill",
                "weeknight_effort": "weeknight effort", "equipment": "equipment", "calorie_target": "calorie target",
                "favorite_cuisines": "cuisines"}
DYNAMIC_CHOICES = {"diet": DIET_CHOICES, "favorite_cuisines": [(c, c) for c in CUISINE_CHOICES]}


def _value(profile: Dict[str, Any], field: str):
    f = (profile or {}).get(field)
    return None if not f else f.get("value")


def to_form(profile: Dict[str, Any]) -> List[Any]:
    """Profile -> list of gr.update(...) in FIELDS order."""
    out = []
    for field, kind in FIELDS:
        v = _value(profile, field)
        if kind in ("multi", "multi_none"):
            vals = [NONE] if (v == [] and kind == "multi_none") else list(v or [])
            if field in DYNAMIC_CHOICES:  # the agent may store values the checkboxes don't list (e.g. 'keto')
                base = DYNAMIC_CHOICES[field]
                known = {c[1] for c in base}
                extra = [(x.replace("_", " ").capitalize(), x) for x in vals if x not in known]
                out.append(gr.update(choices=base + extra, value=vals))
            else:
                out.append(gr.update(value=vals))
        elif kind == "text_list":
            out.append(gr.update(value=", ".join(v or [])))
        elif kind == "bool":
            out.append(gr.update(value=None if v is None else ("yes" if v else "no")))
        elif kind == "int":
            out.append(gr.update(value=v))
        else:
            out.append(gr.update(value=v if v is not None else ("" if kind == "text" else None)))
    return out


def _parse(kind: str, raw) -> Optional[Any]:
    """Form value -> profile value (None = unknown / remove)."""
    if kind == "multi_none":
        vals = [x for x in (raw or []) if x != NONE]
        return sorted(vals) if vals else ([] if NONE in (raw or []) else None)
    if kind == "multi":
        return sorted(raw) if raw else None
    if kind == "text_list":
        vals = [x.strip() for x in (raw or "").split(",") if x.strip()]
        return vals or None
    if kind == "int":
        return int(raw) if raw not in (None, "") and float(raw) > 0 else None
    if kind == "bool":
        return None if not raw else raw == "yes"
    if kind == "text":
        return (raw or "").strip() or None
    return raw or None


def from_form(profile: Dict[str, Any], raw_values: List[Any], turn: int) -> Tuple[Dict[str, Any], List[str]]:
    """Merge form values into the profile. Returns (new_profile, changed_field_names)."""
    out = dict(profile or {})
    changed = []
    for (field, kind), raw in zip(FIELDS, raw_values):
        new = _parse(kind, raw)
        old = _value(out, field)
        norm_old = sorted(old) if isinstance(old, list) and kind != "text_list" else old
        if new == norm_old:
            continue
        changed.append(field)
        if new is None:
            out.pop(field, None)
        else:
            out[field] = {"value": new, "source": "manual", "last_updated_turn": turn}
    return out, changed


def provenance_note(profile: Dict[str, Any], changed: Optional[List[str]] = None) -> str:
    """Small line showing what Dnner learned from chat vs. what was edited here."""
    from_chat = [FIELD_LABELS.get(k, k) for k, f in (profile or {}).items()
                 if k in FIELD_LABELS and f.get("source") in ("stated", "inferred")]
    manual = [FIELD_LABELS.get(k, k) for k, f in (profile or {}).items() if k in FIELD_LABELS and f.get("source") == "manual"]
    parts = []
    if changed is not None:
        parts.append(f"**Saved** {', '.join(FIELD_LABELS.get(c, c) for c in changed)}. Dnner uses these from your next message."
                     if changed else "No changes to save.")
    if from_chat:
        parts.append(f"✨ Learned from chat: {', '.join(from_chat)}")
    if manual:
        parts.append(f"✏️ Edited here: {', '.join(manual)}")
    if not parts:
        parts.append("Tell Dnner about yourself in chat, or fill these in. Dnner keeps them up to date as you talk.")
    return "  \n".join(parts)
