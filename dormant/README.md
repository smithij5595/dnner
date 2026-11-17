# Dormant features

Code that was scoped out of Dnner but kept intact. None of it is imported by `graph.py`, `app.py`, `agents/` or
`tools/`. Its tests (`tests/test_dormant_*.py`) still run, so it won't silently rot.

## restaurants/ (scoped out: Dnner is a home-cooking planner)

- `agent.py`: `restaurant_agent`, which searches places, checks `is_open` and returns `RestaurantPicks`. It
  includes the `INJECT_HALLUCINATED_RESTAURANT` branch.
- `tools.py`: `search_restaurants`, `get_restaurant` and `is_open`, with after-midnight closing handled.
- `models.py`: `Restaurant`, `RestaurantRequest`, `RestaurantPick` and `RestaurantPicks`.
- `data/restaurants.json`: 25 restaurants with opening hours and dietary notes.

To bring it back:
1. Add `takeout` / `dine_out` to `Mode` in `state.py`, and `restaurant_search` to `Intent`.
2. Add the node and its edges in `graph.py`: an advisor handoff and re-entry, and a weekly fan-out for eat-out slots.
3. Restore the composer's `restaurant_picks` payload kind, and the orchestrator and advisor prompt lines.

## calendar/ (deferred: calendar integration is a later feature)

- `agent.py`: `calendar_agent`, which summarizes the week into planning notes. It includes the
  `INJECT_INJECTION_VULNERABLE` branch.
- `tools.py`: `load_calendar` and `get_day_availability`, with free windows, meal-slot minutes and suggested
  modes. It includes the `INJECT_CALENDAR_MISREAD` branch: UTC parsing and dropped all-day events.
- `models.py`: `CalendarEvent`, `CalendarWeek` and `CalendarNotes`.
- `data/calendar_week.json`: a mock week with traps:
  - a gym session
  - a travel day with a Central-time flight
  - an all-day offsite stored as `00:00-00:00`
  - a prompt-injection event description

Today the busy-night signal comes from the user (`profile.busy_nights` / `nights_out`), through
`tools/week_tools.get_week_outline`. A real calendar integration would replace or enrich that outline. Each day's
`meal_slots[*].free_minutes` / `suggested_mode` from `get_day_availability` maps directly onto the outline's
`cook_minutes` / `suggested_mode`.

The flags these modules use are listed in `config.DORMANT_FLAGS`, so `Settings.has()` still accepts them. They
aren't offered in the UI or the scenario runner.
