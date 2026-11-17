"""Dnner - Gradio UI entrypoint.  Run:  python app.py

Layout: a centered chat (~70% of the window) plus a sidebar on the right (toggled from the top bar)
with This week / Shopping list / Preferences, and Demo Controls (failure flags, prompt version, agent
path) behind a button at the bottom of the sidebar.

The app always uses the real current time (HOME_TZ). Simulated time is only for scripts/run_scenarios.py.
"""
import os
import warnings
from typing import Any, Dict

import gradio as gr

from config import FAILURE_FLAGS, PROMPT_VERSION, PROMPT_VERSIONS, Settings
from graph import get_graph, get_values, invoke_turn, new_session_id, save_profile
from tracing import setup_tracing, trace_context
from ui import preferences as prefs
from ui.render import render_knows, render_shopping, render_turn, render_week
from ui.theme import CSS, ON_LOAD_JS, build_theme

from dotenv import load_dotenv

load_dotenv()  # Load environment variables from a .env file if present

ARIZE_API_KEY = os.getenv("ARIZE_API_KEY")
ARIZE_SPACE_ID = os.getenv("ARIZE_SPACE_ID")
PROJECT_NAME = os.getenv("PROJECT_NAME")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

warnings.filterwarnings("ignore", category=DeprecationWarning)
setup_tracing()
GRAPH = get_graph()

PLACEHOLDER = "What can I help you plan?"
EXAMPLES = ["Plan my week", "What should I make tonight?", "I have eggs, spinach and rice - ideas?",
            "Saturday's our anniversary, we're going out", "How long does cooked chicken last in the fridge?"]
WELCOME = ("### Let's get you cooking at home more.\n"
           "Tell me which nights are toughest and I'll plan the week around them: batch cooks when you have time, "
           "leftovers when you don't, and a shopping list to match.")


# --------------------------------------------------------------------------- helpers
def _settings(failures, pv) -> Settings:
    """Real current time; only failure flags + prompt version come from Demo Controls."""
    return Settings.build(prompt_version=pv, failures=failures or [], scenario_id="ui")


def _footer(session: Dict[str, Any]) -> str:
    return f"session `{session['session_id']}` · last run `{session.get('last_run_id') or '-'}`"


def _panels(state: Dict[str, Any], settings: Settings):
    """week, shopping, raw state."""
    return render_week(state, settings), render_shopping(state), render_knows(state)


# --------------------------------------------------------------------------- handlers
def add_user_message(message, history):
    if not message or not message.strip():
        return gr.update(), history
    return "", (history or []) + [{"role": "user", "content": message.strip()}]


def respond(history, session, failures, pv):
    settings = _settings(failures, pv)
    if not history or history[-1]["role"] != "user":
        state = get_values(GRAPH, session["session_id"])
        return (history, session, *_panels(state, settings), gr.update(), gr.update(), gr.update(),
                *[gr.update() for _ in prefs.FIELDS])
    message = history[-1]["content"]
    before = get_values(GRAPH, session["session_id"]).get("profile") or {}
    metadata = {"prompt_version": settings.prompt_version, "injected_failures": sorted(settings.failures),
                "scenario_id": settings.scenario_id, "detected_intent": None}
    with trace_context(session["session_id"], None, metadata):
        state, record = invoke_turn(GRAPH, session["session_id"], message, settings)
        metadata["detected_intent"] = record["detected_intent"]
    session = {**session, "last_run_id": record["run_id"]}
    reply = state.get("final_response") or "Sorry - something went wrong on my side. Try again?"
    history = history + [{"role": "assistant", "content": reply}]
    profile = state.get("profile") or {}
    # Only refresh the form when the agent changed the profile, so unsaved edits aren't clobbered.
    form = prefs.to_form(profile) if profile != before else [gr.update() for _ in prefs.FIELDS]
    note = prefs.provenance_note(profile) if profile != before else gr.update()
    return (history, session, *_panels(state, settings), render_turn(record), _footer(session), note, *form)


def save_preferences(session, failures, pv, *raw):
    sid = session["session_id"]
    current = get_values(GRAPH, sid)
    profile, changed = prefs.from_form(current.get("profile") or {}, list(raw), current.get("turn_index", 0))
    state = save_profile(GRAPH, sid, profile) if changed else current
    week, _, knows = _panels(state, _settings(failures, pv))
    return (prefs.provenance_note(profile, changed), week, knows, *prefs.to_form(profile))


def new_session(failures, pv):
    session = {"session_id": new_session_id(), "last_run_id": None}
    return ([], session, *_panels({}, _settings(failures, pv)), render_turn({}), _footer(session),
            prefs.provenance_note({}), *prefs.to_form({}))


def toggle_sidebar(is_open, session, failures, pv):
    """Open/close the sidebar (always back on the planner view). Re-renders the week so 'today' is current."""
    is_open = not is_open
    week = render_week(get_values(GRAPH, session["session_id"]), _settings(failures, pv))
    return (is_open, gr.update(visible=is_open), gr.update(visible=True), gr.update(visible=False),
            gr.update(value="✕  Close" if is_open else "☰  My week & lists"), week)


def show_demo(on: bool):
    return gr.update(visible=not on), gr.update(visible=on)


# --------------------------------------------------------------------------- layout
with gr.Blocks(title="Dnner", theme=build_theme(), css=CSS, js=ON_LOAD_JS, fill_width=True) as demo:
    session = gr.State({"session_id": new_session_id(), "last_run_id": None})
    sidebar_open = gr.State(False)

    # ---- top bar
    with gr.Row(elem_id="topbar", equal_height=True):
        gr.HTML("<div id='brand'><span class='name'>D<b>n</b>ner</span>"
                "<span class='tag'>Cook at home more, even on the busy nights.</span></div>")
        sidebar_toggle = gr.Button("☰  My week & lists", elem_id="sidebar-toggle", scale=0, min_width=190)

    with gr.Row(elem_id="main", equal_height=False):
        # ---- centered chat
        with gr.Column(elem_id="chat-col", scale=1):
            with gr.Column(elem_id="chat-inner"):
                chat = gr.Chatbot(type="messages", elem_id="chat", height="calc(100vh - 270px)", show_label=False,
                                  show_copy_button=True, placeholder=WELCOME)
                box = gr.Textbox(placeholder=PLACEHOLDER, show_label=False, autofocus=True, lines=1, max_lines=6,
                                 elem_id="composer")
                with gr.Row(elem_id="chips"):
                    chips = [gr.Button(e, size="sm", variant="secondary") for e in EXAMPLES]

        # ---- right sidebar (hidden until opened)
        with gr.Column(elem_id="sidebar", scale=0, min_width=400, visible=False) as sidebar:
            with gr.Column(elem_id="sidebar-views") as views:
                with gr.Tabs():
                    with gr.Tab("This week"):
                        week_html = gr.HTML(render_week({}, Settings()))
                    with gr.Tab("Shopping list"):
                        shop_html = gr.HTML(render_shopping({}))
                    with gr.Tab("Preferences", elem_id="prefs"):
                        prefs_note = gr.Markdown(prefs.provenance_note({}), elem_id="prefs-note")
                        with gr.Group():
                            p_allergies = gr.CheckboxGroup(prefs.ALLERGY_CHOICES, label="Allergies")
                            p_diet = gr.CheckboxGroup(prefs.DIET_CHOICES, label="Diet")
                            p_dislikes = gr.Textbox(label="Dislikes", placeholder="e.g. cilantro, mushrooms")
                        with gr.Group():
                            p_household = gr.Number(label="Cooking for (people)", precision=0, minimum=0)
                            p_meals = gr.CheckboxGroup(prefs.MEAL_CHOICES, label="Meals to plan")
                            p_busy = gr.CheckboxGroup(prefs.BUSY_CHOICES, label="Toughest nights to cook this week")
                            p_out = gr.CheckboxGroup(prefs.DAY_CHOICES, label="Nights out this week")
                            p_budget = gr.Textbox(label="Budget", placeholder="e.g. $6 per serving or $120/week")
                            p_leftovers = gr.Radio(prefs.LEFTOVER_CHOICES, label="Leftovers & batch cooking")
                        with gr.Group():
                            p_skill = gr.Radio(prefs.SKILL_CHOICES, label="Cooking skill")
                            p_effort = gr.Radio(prefs.EFFORT_CHOICES, label="Weeknight effort")
                            p_equipment = gr.Textbox(label="Kitchen equipment", placeholder="e.g. Instant Pot, sheet pans")
                            p_calories = gr.Number(label="Calorie target per meal (optional)", precision=0, minimum=0)
                        p_cuisines = gr.CheckboxGroup([(c, c) for c in prefs.CUISINE_CHOICES], label="Favorite cuisines")
                        save_btn = gr.Button("Save preferences", variant="primary", elem_id="prefs-save")
                demo_open = gr.Button("⚙  Demo Controls", elem_id="demo-open")

            with gr.Column(elem_id="sidebar-demo", visible=False) as demo_panel:
                demo_back = gr.Button("←  Back to my week", elem_id="demo-back", size="sm")
                gr.HTML("<h3 class='panel-title'>Demo Controls</h3>")
                turn_html = gr.HTML(render_turn({}))
                failures = gr.CheckboxGroup(choices=[(f"{k} - {v}", k) for k, v in FAILURE_FLAGS.items()],
                                            value=sorted(f for f in Settings().failures if f in FAILURE_FLAGS),
                                            label="Failure injection")
                pv = gr.Dropdown(PROMPT_VERSIONS, value=PROMPT_VERSION, label="Prompt version")
                reset = gr.Button("New session", variant="stop")
                with gr.Accordion("What Dnner knows (raw state)", open=False):
                    knows = gr.Dataframe(headers=["Scope", "Field", "Value", "Source", "Turn"], value=render_knows({}),
                                         interactive=False, wrap=True)
                foot = gr.Markdown(_footer(session.value), elem_id="session-foot")

    pref_inputs = [p_allergies, p_diet, p_dislikes, p_household, p_meals, p_busy, p_out, p_budget, p_leftovers,
                   p_skill, p_effort, p_equipment, p_calories, p_cuisines]
    assert len(pref_inputs) == len(prefs.FIELDS)
    controls = [failures, pv]

    # ---- events
    turn_outputs = [chat, session, week_html, shop_html, knows, turn_html, foot, prefs_note, *pref_inputs]
    # Chat auto-scroll is handled by a MutationObserver installed in ON_LOAD_JS.
    box.submit(add_user_message, [box, chat], [box, chat], queue=False).then(
        respond, [chat, session, *controls], turn_outputs)
    for chip, text_ in zip(chips, EXAMPLES):
        chip.click(lambda h, t=text_: add_user_message(t, h), [chat], [box, chat], queue=False).then(
            respond, [chat, session, *controls], turn_outputs)
    save_btn.click(save_preferences, [session, *controls, *pref_inputs], [prefs_note, week_html, knows, *pref_inputs])
    reset.click(new_session, controls,
                [chat, session, week_html, shop_html, knows, turn_html, foot, prefs_note, *pref_inputs])

    sidebar_toggle.click(toggle_sidebar, [sidebar_open, session, *controls],
                         [sidebar_open, sidebar, views, demo_panel, sidebar_toggle, week_html], queue=False)
    demo_open.click(lambda: show_demo(True), None, [views, demo_panel], queue=False)
    demo_back.click(lambda: show_demo(False), None, [views, demo_panel], queue=False)

if __name__ == "__main__":
    demo.queue().launch()
