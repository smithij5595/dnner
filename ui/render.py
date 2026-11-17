"""HTML renderers for the sidebar (week, shopping list) and Demo Controls (last turn, raw state)."""
from collections import defaultdict
from html import escape
from typing import Any, Dict, List

from config import DAY_KEYS, DAY_NAMES, Settings, format_now, plan_window
from tools.data import recipes

MODE_LABEL = {"cook_from_scratch": "Cook", "quick_meal": "Quick", "leftovers": "Leftovers", "skip": "Out"}
SLOT_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2}


def _recipe_name(rid) -> str:
    r = recipes().get(rid or "")
    return r.name if r else (rid or "")


# --------------------------------------------------------------------------- this week
def _meal_line(m: Dict[str, Any]) -> str:
    mode = m.get("mode") or ""
    r = recipes().get(m.get("recipe_id") or "")
    if mode == "skip":
        what, details = "Night out", m.get("note") or ""
    else:
        what = r.name if r else (m.get("recipe_id") or "-")
        bits = [m["slot"]]
        if mode in ("cook_from_scratch", "quick_meal") and r:
            bits.append(f"{r.total_minutes} min")
        if m.get("is_batch_cook"):
            bits.append(f"batch cook x{m.get('servings_to_cook')}")
        if mode == "leftovers" and m.get("leftovers_from"):
            bits.append(f"from {m['leftovers_from']}")
        details = " · ".join(bits)
    return (f"<div class='wk-meal'><span class='pill {mode}'>{MODE_LABEL.get(mode, mode)}</span>"
            f"<div class='what'><b>{escape(what)}</b><small>{escape(details)}</small></div></div>")


def _tonight_line(rec: Dict[str, Any]) -> str:
    p = rec.get("primary") or {}
    r = recipes().get(p.get("recipe_id") or "")
    details = [rec.get("target_meal", "dinner")]
    if r:
        details.append(f"{r.total_minutes} min")
    if rec.get("time_plan"):
        details.append(rec["time_plan"])
    return (f"<div class='wk-meal'><span class='pill pick'>Tonight's pick</span>"
            f"<div class='what'><b>{escape(p.get('name', '-'))}</b><small>{escape(' · '.join(details))}</small></div></div>")


def _day_tags(state: Dict[str, Any]) -> Dict[str, str]:
    p = state.get("profile") or {}
    tags = {d: "busy night" for d in ((p.get("busy_nights") or {}).get("value") or [])}
    tags.update({d: "night out" for d in ((p.get("nights_out") or {}).get("value") or [])})
    return tags


def render_week(state: Dict[str, Any], settings: Settings) -> str:
    plan = (state.get("current_plan") or {}).get("meals", [])
    rec = state.get("tonight_recommendation")
    if not plan and not rec:
        return ("<div class='hint'>No meals planned yet.<br><br>Try <b>“Plan my week”</b> and Dnner will fit dinners "
                "around your busiest nights, batch cook when you have time and line up leftovers for the tough ones.</div>")
    by_day = defaultdict(list)
    for m in plan:
        by_day[m["day"]].append(m)
    today = settings.now.date()
    tags = _day_tags(state)
    rec_today = rec if rec and rec.get("target_day", "today") == "today" and rec.get("mode") != "skip" else None
    out = [f"<p class='sub'>Next 7 days · {format_now(settings.now)}</p><div class='wk'>"]
    for d in plan_window(settings.now):
        day = DAY_KEYS[d.weekday()]
        cls = "today" if d == today else ""
        meals = sorted(by_day.get(day, []), key=lambda m: SLOT_ORDER.get(m["slot"], 9))
        if not meals and not (rec_today and d == today):
            if not plan:
                continue  # only a tonight pick so far: show just today
            body = "<div class='wk-empty'>Nothing planned</div>"
        else:
            body = "".join(_meal_line(m) for m in meals)
        if rec_today and d == today:
            body += _tonight_line(rec_today)
        badge = "<span class='wk-today'>Today</span>" if d == today else ""
        tag = f"<span class='wk-tag'>{tags[day]}</span>" if day in tags else ""
        out.append(f"<div class='wk-day {cls}'><div class='wk-head'>{DAY_NAMES[d.weekday()]}"
                   f"<span class='wk-date'>{d:%b %-d}</span>{tag}{badge}</div>{body}</div>")
    out.append("</div>")
    return "".join(out)


# --------------------------------------------------------------------------- shopping list
def render_shopping(state: Dict[str, Any]) -> str:
    sl = state.get("shopping_list") or {}
    items = sl.get("items") or []
    if not items:
        return ("<div class='hint'>Your shopping list is empty.<br><br>It fills in automatically when Dnner plans "
                "your week, with quantities scaled for batch cooks.</div>")
    groups = defaultdict(list)
    for it in items:
        groups[it["category"]].append(it)
    n_recipes = len({r for it in items for r in it.get("for_recipes", [])})
    out = [f"<p class='sub'>{len(items)} items · for {n_recipes} recipes · tick things off as you shop</p>"]
    for cat in sorted(groups):
        rows = []
        for it in sorted(groups[cat], key=lambda x: x["name"]):
            used = ", ".join(_recipe_name(r) for r in it.get("for_recipes", []))
            rows.append(f"<label class='shop-item'><input type='checkbox'><span><b>{escape(it['name'])}</b> "
                        f"<span class='qty'>{it['quantity']:g} {escape(it['unit'])}</span></span>"
                        f"<small>{escape(used)}</small></label>")
        out.append(f"<div class='shop-cat'><h4>{escape(cat)}</h4>{''.join(rows)}</div>")
    if sl.get("notes"):
        out.append(f"<p class='sub'>{escape(sl['notes'])}</p>")
    return "".join(out)


# --------------------------------------------------------------------------- demo controls
def render_turn(record: Dict[str, Any]) -> str:
    if not record:
        return "<div class='turn'><span class='lbl'>Last turn</span><div class='row'>Send a message to see the agent path.</div></div>"
    path = "<span class='arrow'>→</span>".join(f"<span class='node'>{escape(n)}</span>" for n in record["agent_path"])
    llms = record["llm_calls"]
    tokens = sum(((c.get("tokens") or {}).get("total") or 0) for c in llms)
    latency = sum((c.get("latency_ms") or 0) for c in llms)
    tools = defaultdict(int)
    for t in record["tool_calls"]:
        tools[t["tool"]] += 1
    tool_txt = ", ".join(f"{k} x{v}" if v > 1 else k for k, v in tools.items()) or "none"
    err = f"<div class='row err'>Error: {escape(record['error'])}</div>" if record.get("error") else ""
    flags = ", ".join(record.get("injected_failures") or []) or "none"
    return (f"<div class='turn'><span class='lbl'>Last turn · intent</span>"
            f"<div class='row'><b>{escape(str(record['detected_intent']))}</b> · prompt {record['prompt_version']}</div>"
            f"<span class='lbl'>Agent path</span><div class='path'>{path}</div>"
            f"<div class='row'><b>{len(record['tool_calls'])}</b> tool calls: {escape(tool_txt)}</div>"
            f"<div class='row'><b>{len(llms)}</b> LLM calls · {tokens:,} tokens · {latency / 1000:.1f}s in LLMs</div>"
            f"<div class='row'>Failures injected: {escape(flags)}</div>{err}</div>")


def render_knows(state: Dict[str, Any]) -> List[List[Any]]:
    rows = []
    for scope in ("profile", "session_context"):
        for field, f in (state.get(scope) or {}).items():
            v = f["value"]
            shown = ", ".join(map(str, v)) if isinstance(v, list) and v else "(none)" if v == [] else str(v)
            rows.append([scope, field, shown, f["source"], f["last_updated_turn"]])
    task = state.get("active_task")
    if task:
        rows.append(["active_task", task.get("intent"), task.get("pending_question") or task.get("status"),
                     task.get("agent"), task.get("clarifying_turns")])
    return rows or [["-"] * 5]
