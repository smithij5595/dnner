# 🍽️ Dnner

A home-cooking meal planner, built as a **multi-agent LangGraph app to instrument with Arize AX**.

> *"I want to cook at home more and ideally eat out only on special occasions, but my days can get busy and it's
> hard to plan ahead for multiple days and multiple meals."*

Dnner asks which nights are toughest to cook. It then plans the week around them: batch cooks on the easier
nights, leftovers on the busy ones, and nights out marked as skip. It also writes the shopping list, helps
decide tonight's dinner, and answers cooking questions. The preferences it learns from chat are editable in
the sidebar.

It ships with **no tracing**: you add that in `tracing.py`. It's built to give you interesting traces:
- 9 agents as named graph nodes
- real tool calls and Pydantic hand-offs between agents
- multi-turn sessions
- stable metadata on every turn
- 9 **failure flags** that break specific behaviors on demand, so there's something to find in AX

---

## Setup

Requires **Python 3.9+**. It was built on 3.9.25; `.python-version` pins it for pyenv.

```bash
cd dnner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set OPENAI_API_KEY
pytest                      # data, tools, graph routing + dormant features; no API calls
```

> Make sure **this** project's venv is active (`python --version` → 3.9.25). If another project's venv is active
> you'll see `No module named 'gradio'`; run `deactivate` first.
>
> On macOS, if `pyenv install 3.9.x` fails with *"Could not build the ssl module"*, install OpenSSL 3 and run
> `PYTHON_BUILD_HOMEBREW_OPENSSL_FORMULA=openssl@3 pyenv install 3.9.25`.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | – | Required |
| `MODEL_<AGENT>` | `gpt-4o-mini`; `gpt-4o` for `MEAL_ADVISOR`, `MEAL_PLANNER`, `CONSTRAINT_CHECKER` | Model per agent |
| `WEEK_START` | upcoming Monday | **Scenarios only.** The Monday that scenario shorthand like `Thu 8:15pm` resolves against |
| `NOW_OVERRIDE` | `Wed 4:30pm` | **Scenarios only.** Default simulated time for scenarios without a `now` |
| `HOME_TZ` | `America/Los_Angeles` | Home timezone |
| `PROMPT_VERSION` | `v1` | `v1` is the baseline. `v2` adds explicit guardrail lines to each agent prompt (`PROMPTS["v2"]`) |
| `INJECT_*` | `false` | Failure flags (see below) |

## Run it

```bash
python app.py                                    # UI at http://127.0.0.1:7860
python scripts/run_scenarios.py --list           # 23 scripted personas
python scripts/run_scenarios.py                  # healthy traffic (scenarios run in parallel)
python scripts/run_scenarios.py --fail INJECT_HALLUCINATED_RECIPE INJECT_OVERCONFIDENT_FOOD_QA
python scripts/run_scenarios.py --all-failures   # everything broken at once
python scripts/run_scenarios.py --only sc_tonight_tired --now "Tue 5:45pm" --prompt-version v2
```

**UI:**
- **Chat** in the center (about 70% of the window). The input placeholder is "What can I help you plan?", with
  example chips below it.
- The app always uses the **real current time** (Pacific). Plans cover the next 7 days starting today. A simulated
  time is only used by `scripts/run_scenarios.py`, through each scenario's `now` or `--now`.
- **☰ My week & lists** opens a sidebar on the right with three tabs:
  - **This week:** the planned meals day by day, with busy nights and nights out tagged, plus tonight's pick.
  - **Shopping list:** grouped by aisle, quantities scaled for batch cooks, tick-off checkboxes.
  - **Preferences:** allergies, diet, household, meals to plan, toughest nights, nights out, budget, leftovers,
    skill, effort, equipment, calories and cuisines. Dnner fills these in from chat, and you can edit and save
    them. A note shows which fields it ✨ learned from chat and which were ✏️ edited by hand.
- **⚙ Demo Controls** at the bottom of the sidebar swaps it to:
  - the **last turn's agent path**: intent, node chain, tool calls, LLM calls, tokens and latency
  - failure toggles, prompt version and **New session**
  - the raw "what Dnner knows" state and the session id

**Traffic:**
- **Scenarios** (`scenarios/scenarios.json`): 23 personas with scripted turns, the expected intent per turn, and
  expected outcomes. Each scenario is one session.
- **Food Q&A cases** (`scenarios/food_qa_cases.json`): 8 questions with reference answers and a
  `safety_critical` flag, ready to upload as an AX dataset.

## Adding instrumentation

Everything goes in **`tracing.py`**. No other module references tracing.

1. `setup_tracing()` runs once at startup (`app.py`, `scripts/run_scenarios.py`). Register the tracer provider
   and the LangChain instrumentor here.
2. `trace_context(session_id, user_id, metadata)` wraps every graph invocation. Wrap the session, user and
   metadata context managers here.
   - `metadata` carries `prompt_version`, `injected_failures`, `scenario_id` and `detected_intent`.
   - `detected_intent` is set just before the block exits, so read it on exit if you want it on the root span.

What you'll get on spans without any other changes:

- **Node spans:** `profile_updater`, `orchestrator`, `meal_advisor`, `food_qa`, `recipe_lookup`, `intake_agent`,
  `meal_planner`, `constraint_checker`, `grocery_agent`, `response_composer`.
- **LLM spans:** named `<agent>.<step>` (e.g. `meal_advisor.decide`, `meal_planner.search.round1`), tagged
  `agent:<name>` and `prompt:<version>`, with `prompt_version` in their metadata.
- **Tool spans:** `get_current_time`, `get_week_outline`, `search_recipes`, `get_recipe` and
  `find_recipes_by_ingredients`.
- **Structured outputs:** `ProfileExtraction`, `RoutingDecision`, `AdvisorDecision`, `TonightRecommendation`,
  `WeeklyPlan` and `ConstraintCheck`, so routing and agent decisions show up as inspectable JSON.
- **Root run:** named `dnner_turn`, with tags `prompt:<v>` and `failure:<FLAG>`, and metadata `session_id`,
  `turn_index` and `scenario_id`.

Saving the Preferences form writes straight to the checkpoint with no LLM call, so it creates no trace. The
next turn's `profile_updater` input shows the edited values, with `source: "manual"`.

`runs/` also gets a small local JSON summary per turn: the agent path, tool calls, and LLM calls with tokens.
That's for quick debugging and is no substitute for AX.

## Failure flags: what to look for in AX

Toggle these in **Demo Controls**, in `.env`, or with `--fail`. Each one is a small branch in the code marked
`# --- FAILURE INJECTION: <FLAG>`, written as a "prompt v1 → v2" regression. Filter traces by the `failure:<FLAG>`
tag or by `injected_failures` metadata to compare against healthy traffic.

| Flag | What breaks | Where to see it in a trace | Good AX eval to catch it |
|---|---|---|---|
| `INJECT_IGNORES_BUSY_NIGHTS` | Planner never sees the busy nights or nights out | `meal_planner.search` input has no `busy_nights` and the `week_outline` is all regular nights. The plan cooks from scratch on the toughest nights, with no batch cooks or leftovers lined up (try `sc_busy_nights_intake`) | Code eval: busy nights are `leftovers` or ≤20 min (`available_minutes` is ground truth) |
| `INJECT_CONSTRAINT_DRIFT` | From turn 3, or on a replan, the planner and advisor prompts lose the dietary profile | `meal_advisor.decide` / `meal_planner.search` inputs have no `diet` or `allergies`. On its own, extra `meal_planner → constraint_checker` loops show up as latency and cost | Session-level eval for constraint retention |
| `INJECT_ALLERGEN_MISS` | Checker prompt weakened and allergen facts stripped | `constraint_checker.check_*` input has no `allergen_overlap`. Pair it with drift to let violations through | Code eval against `data/ingredients.json` allergens |
| `INJECT_GROCERY_SCALING_BUG` | Batch cooks scaled for one household meal | `grocery_agent` output quantities are too small for `servings_to_cook` | Code eval comparing the list with the plan |
| `INJECT_HALLUCINATED_RECIPE` | Advisor names a recipe from memory | The span is `meal_advisor.recommend_from_memory`, with **no** `search_recipes` / `find_recipes_by_ingredients` spans. The `recipe_id` (e.g. `rec_spinach_egg_fried_rice`) isn't in `data/recipes.json`, and the checker's `get_recipe` returns an error | Tool-call-presence check, plus a check that the recipe exists |
| `INJECT_ROUTER_OVERCALL` | Read-only plan questions re-run the whole pipeline | "What's Tuesday's dinner?" shows `meal_planner → constraint_checker → grocery_agent` instead of going straight to the composer: wasted latency and tokens, and a risk of silently changing the plan | Agent-path / trajectory eval |
| `INJECT_ROUTER_MISCLASSIFY` | Router prompt weakened, active-task rule removed | The `orchestrator` `RoutingDecision` is wrong: a food question starts `intake_agent`, and "kinda tired" restarts the task | Compare intent with the scenario's `expected_intent` |
| `INJECT_FORGETFUL_ADVISOR` | Advisor ignores the profile and history | The `meal_advisor.decide` input has an empty profile, and it re-asks for allergies | LLM judge for redundant questions (session level) |
| `INJECT_OVERCONFIDENT_FOOD_QA` | Safety and uncertainty guidance removed | The `food_qa.answer` system prompt has no USDA block, and answers have no caveats | LLM judge for correctness and safety against `food_qa_cases.json` |

## Ideas for the AX demo

**Tracing and sessions**
- Open a multi-turn **session**, such as `sc_busy_nights_intake`, `sc_tonight_tired` or `sc_mixed_conversation`.
- Follow `active_task` through the turns: a short reply ("kinda tired honestly") routes back to `meal_advisor`
  instead of being classified from scratch.
- Show the intake → plan hand-off: turn 1 asks "Which days this week are toughest to cook dinner?", and turn 2's
  `ProfileExtraction` captures `busy_nights` before `get_week_outline` turns them into time budgets.
- `sc_special_occasion` shows a minimal replan: only Saturday changes to skip, visible in `plan_changes`.

**Filter and compare**
- Filter by `scenario_id` or by `failure:*` tags, and compare latency and token cost between healthy and broken traffic.
- `INJECT_ROUTER_OVERCALL` and `INJECT_CONSTRAINT_DRIFT` show up as cost and latency, not as wrong answers.

**Evaluations in AX**
- The static data is ground truth:
  - `data/ingredients.json` gives each ingredient's allergens and animal-product class.
  - `data/recipes.json` gives real cook times, servings and leftover lifetimes.
  - Each planned meal carries `cook_minutes` vs. `available_minutes`, from the deterministic week outline.
- Code evals over spans are easy, and LLM judges fit tone, recommendation quality, question quality and "stays in
  scope" (`sc_misc_requests` asks for a restaurant, and Dnner should decline politely).

**Datasets and experiments**
- Upload `scenarios/food_qa_cases.json` as a dataset.
- Run the `food_qa` prompt under v1 and with `INJECT_OVERCONFIDENT_FOOD_QA` as an experiment, and grade the
  results against the reference answers.

**Prompt iteration**
- Pull a failing `meal_planner.write_plan` or `orchestrator.route` span into the prompt playground.
- Compare the `PROMPTS["v1"]` and `PROMPTS["v2"]` variants in each `agents/*.py`.

## 15-minute demo script: build, break, observe, fix, prove

**0. Prep.**
- Run `python scripts/run_scenarios.py` for healthy traffic.
- Run `python scripts/run_scenarios.py --fail INJECT_ALLERGEN_MISS INJECT_CONSTRAINT_DRIFT INJECT_HALLUCINATED_RECIPE INJECT_OVERCONFIDENT_FOOD_QA`
  for broken traffic.
- Start `python app.py`.

**1. Build (4 min).**
- Say **"Plan my week"**. Dnner asks one compact intake question, including *which days are toughest to cook*.
- Reply **"No allergies, just me, dinners only, $7 a serving, intermediate cook. Mondays and Wednesdays are the
  worst."** Open the sidebar: busy nights get leftovers from the night before, and the shopping list is ready.
- Open **Preferences**: everything was learned from chat. Change *Cooking for* to 3 and save; the next plan
  scales.
- Show that trace in AX: the router decision, `ProfileExtraction`, `get_week_outline`, the planner's recipe
  searches, the constraint check and the grocery agent.
- *Food Q&A moment:* **"How long does cooked chicken last in the fridge?"** The intent switches while the plan stays put.

**2. Break (3 min).**
- In Demo Controls, turn on `INJECT_IGNORES_BUSY_NIGHTS` and `INJECT_HALLUCINATED_RECIPE`, then click New session.
- Plan the week again, then ask **"I have eggs, spinach and rice - what can I make tonight?"**
- Compare the traces: busy nights get full cooks, and tonight's recipe was invented without any search tools.

**3. Observe (4 min).**
- In AX, filter by `failure:*` tags and run your evals over healthy vs. broken traffic.
- Drill into a failing span. `INJECT_CONSTRAINT_DRIFT` on its own shows up only as extra checker loops; adding
  `INJECT_ALLERGEN_MISS` is what lets violations through.

**4. Fix (2 min).** Turn the flags off, which is the "revert the prompt change", or switch **Prompt version** to `v2`.

**5. Prove (2 min).** Rerun the same scenarios healthy and rerun the AX evals or experiment. The pass rates recover.

## Architecture

```
profile_updater ─▶ orchestrator ─┬─ tonight_decision ─▶ meal_advisor ─▶ constraint_checker ─(fail, 1 retry)─▶ meal_advisor
 (every turn)     (RoutingDecision)├─ weekly_plan ─▶ [intake_agent] ─▶ meal_planner ─▶ constraint_checker ─(fail, 2 retries)─▶ meal_planner
                                   │                                                    └─(pass)─▶ grocery_agent
                                   ├─ replan ─▶ meal_planner (edits the existing plan) ─▶ …
                                   ├─ food_qa ─▶ food_qa
                                   ├─ recipe_request ─▶ recipe_lookup ("yes, the tacos - recipe please"; get_recipe, no LLM)
                                   └─ plan_question / update_preferences / smalltalk_or_out_of_scope
                                                                     … all paths end in ─▶ response_composer
```

- **State** (`state.py`) persists across turns through LangGraph's `MemorySaver`, keyed by `session_id`. It holds:
  - `messages`
  - a progressive `profile` and transient `session_context`. Every field records `value`, `source` (stated,
    inferred or manual) and `last_updated_turn`
  - `active_task`
  - `week_outline`, `current_plan`, `shopping_list` and `tonight_recommendation`
- **Busy nights instead of a calendar:** intake asks *"Which days this week are toughest to cook dinner? (and any
  nights you're eating out?)"*. The answers become `profile.busy_nights` / `nights_out`. The deterministic
  `get_week_outline` tool turns them, plus `weeknight_effort`, into a time budget per night:
  - busy: 20 min, leftovers
  - out: skip
  - regular weeknight: about 60 min
  - weekend: 90 min
- **Time:** every tool reads `Settings.now` from `config["configurable"]`. The app fills it from the real clock on each
  turn, and scenarios pass a simulated time so traffic is reproducible.

## Dormant features

Restaurant scouting and calendar reading were scoped out. Their agents, tools, data and tests now live in
`dormant/`, untouched but unwired: the graph, the UI and the active agents never import them, and their tests still
pass. See [dormant/README.md](dormant/README.md) for how to bring either one back. Calendar integration is planned
as a later feature.

## Project layout

```
app.py              Gradio UI (layout + handlers)    tracing.py        no-op instrumentation hooks (fill these in)
ui/                 theme (palette), renderers, preferences form <-> profile
graph.py            LangGraph + invoke_turn + save_profile          run_record.py  local debug summary per turn
config.py           env, models, clock, flags        state.py          Pydantic + TypedDict models
agents/             one module per node (+ common.py helpers)
tools/              recipe / week-outline / clock @tools + cached data loaders
data/               recipes (73), ingredients (allergen ground truth)
scenarios/          scenarios.json (23 personas), food_qa_cases.json (reference answers)
scripts/            run_scenarios.py (traffic generator)
dormant/            restaurants/ and calendar/ (scoped out, kept for later)
tests/              data integrity, tools, graph routing, dormant features
```
