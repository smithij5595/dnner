"""Tool behavior: simulated time, week outline, ingredient search."""
from config import Settings
from tools import find_recipes_by_ingredients, get_current_time, get_recipe, get_week_outline, search_recipes


def cfg(**kw):
    return {"configurable": Settings.build(**kw).to_configurable()}


# ---------------------------------------------------------------- time
def test_default_now_is_the_real_clock():
    from datetime import datetime
    from config import HOME_TZ
    t = get_current_time.invoke({}, config=cfg())
    real = datetime.now(HOME_TZ)
    assert t["now"][:10] == real.date().isoformat() and abs(int(t["time"][:2]) - real.hour) <= 1


def test_scenario_shorthand_is_simulated():
    t = get_current_time.invoke({}, config=cfg(now="Wed 4:30pm"))
    assert t["day"] == "wed" and t["time"] == "16:30"


def test_now_override_shorthand():
    t = get_current_time.invoke({}, config=cfg(now="Thu 8:15pm"))
    assert t["day"] == "thu" and t["time"] == "20:15"


# ---------------------------------------------------------------- week outline
MON = cfg(now="Mon 6:00pm")  # plan window starts on a Monday


def test_week_outline_starts_today():
    w = get_week_outline.invoke({}, config=cfg(now="Thu 8:15pm"))
    assert list(w)[:3] == ["thu", "fri", "sat"] and len(w) == 7
def test_week_outline_defaults():
    w = get_week_outline.invoke({}, config=MON)
    assert w["tue"]["kind"] == "weeknight" and w["tue"]["dinner"]["cook_minutes"] == 60
    assert w["sat"]["kind"] == "weekend" and w["sat"]["dinner"]["suggested_mode"] == "cook_from_scratch"


def test_week_outline_busy_and_out_nights():
    w = get_week_outline.invoke({"busy_nights": ["Tuesday", "thu"], "nights_out": ["fri"], "weeknight_effort": "minimal"}, config=MON)
    assert w["tue"]["kind"] == "busy" and w["tue"]["dinner"]["cook_minutes"] == 20
    assert w["thu"]["dinner"]["suggested_mode"] == "leftovers"
    assert w["fri"]["dinner"] == {"cook_minutes": 0, "suggested_mode": "skip", "reason": "eating out / plans this night"}
    assert w["mon"]["dinner"]["cook_minutes"] == 30 and w["mon"]["dinner"]["suggested_mode"] == "quick_meal"


def test_busy_first_night_cannot_be_leftovers():
    w = get_week_outline.invoke({"busy_nights": ["mon", "tue", "wed"]}, config=MON)
    assert [w[d]["dinner"]["suggested_mode"] for d in ("mon", "tue", "wed")] == ["quick_meal"] * 3
    w = get_week_outline.invoke({"busy_nights": ["mon", "thu"]}, config=MON)
    assert (w["mon"]["dinner"]["suggested_mode"], w["thu"]["dinner"]["suggested_mode"]) == ("quick_meal", "leftovers")


# ---------------------------------------------------------------- recipes
def test_find_recipes_by_ingredients_pantry_case():
    hits = find_recipes_by_ingredients.invoke({"ingredients": ["eggs", "spinach", "rice"]})
    assert hits[0]["id"] == "lun_spinach_egg_rice_bowl"
    assert set(hits[0]["matched"]) == {"eggs", "spinach", "rice"}


def test_ingredient_matching_is_not_naive():
    hits = find_recipes_by_ingredients.invoke({"ingredients": ["rice"], "max_missing": 10, "limit": 100})
    ids = {h["id"] for h in hits}
    assert "chn_egg_fried_rice" in ids           # 'cooked rice'
    assert "lun_peanut_noodle_salad" not in ids  # 'rice noodles' is not rice


def test_search_recipes_filters():
    res = search_recipes.invoke({"meal_type": "dinner", "required_tags": ["vegetarian"],
                                 "exclude_allergens": ["tree_nut"], "max_total_minutes": 20, "limit": 50})
    assert res
    for r in res:
        assert "vegetarian" in r["tags"] and "tree_nut" not in r["allergens"] and r["total_minutes"] <= 20


def test_get_recipe_unknown_id():
    assert "error" in get_recipe.invoke({"recipe_id": "nope"})
