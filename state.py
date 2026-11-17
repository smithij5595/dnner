"""State + schema models for Dnner.

Sections:
  1. Static data records (recipes, ingredients) - validate data/*.json
  2. Conversation memory (profile + session context)
  3. Inter-agent structured outputs
  4. Graph state

Restaurant and calendar models live in dormant/ (features scoped out).

Python 3.9 note: use typing.Optional / List instead of `X | None` so Pydantic can
evaluate the annotations at runtime.
"""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# 1. Static data records
# --------------------------------------------------------------------------- #
Allergen = Literal["peanut", "tree_nut", "dairy", "egg", "gluten", "soy", "shellfish", "fish", "sesame"]
DietTag = Literal[
    "vegetarian", "vegan", "gluten_free", "dairy_free", "high_protein", "meal_prep_friendly",
    "freezer_friendly", "one_pot", "comfort_food", "light", "pantry_friendly",
]
Cuisine = Literal["Italian", "Mexican", "Indian", "Thai", "Japanese", "Mediterranean", "American comfort", "Chinese"]
IngredientCategory = Literal["produce", "protein", "dairy", "pantry", "frozen", "bakery", "spices"]


class Ingredient(BaseModel):
    name: str
    quantity: float
    unit: str
    category: IngredientCategory


class Recipe(BaseModel):
    id: str
    name: str
    cuisine: Cuisine
    meal_type: Literal["breakfast", "lunch", "dinner"]
    prep_minutes: int = Field(ge=0)
    cook_minutes: int = Field(ge=0)
    total_minutes: int = Field(ge=0)
    servings: int = Field(ge=1)
    difficulty: Literal["easy", "medium", "hard"]
    tags: List[DietTag]
    allergens: List[Allergen]
    calories_per_serving: int
    protein_g: int
    carbs_g: int
    fat_g: int
    estimated_cost_per_serving_usd: float
    ingredients: List[Ingredient]
    steps: List[str]
    leftovers_good_for_days: int = Field(ge=0)


class IngredientFact(BaseModel):
    """Ground-truth facts per ingredient (data/ingredients.json), ground truth for checking agent output."""
    category: IngredientCategory
    allergens: List[Allergen]
    animal_product: Literal["meat", "fish", "shellfish", "dairy", "egg", "honey", "none"]


Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYS: List[str] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# --------------------------------------------------------------------------- #
# 2. Conversation memory: progressive profile + transient session context
# --------------------------------------------------------------------------- #
# Stored in graph state as {field: {"value", "source", "last_updated_turn"}} (plain dicts so
# they checkpoint and serialize to run records cleanly).
PROFILE_FIELDS = ["allergies", "diet", "dislikes", "favorite_cuisines", "household_size", "budget",
                  "cooking_skill", "calorie_target", "equipment", "weeknight_effort", "meals_to_plan",
                  "leftovers_ok", "busy_nights", "nights_out"]
CONTEXT_FIELDS = ["pantry", "energy", "hunger", "eating_tonight", "already_ate", "mood", "craving",
                  "location", "time_limit_minutes"]
LIST_FIELDS = {"allergies", "diet", "dislikes", "favorite_cuisines", "equipment", "pantry", "already_ate",
               "meals_to_plan", "busy_nights", "nights_out"}


class ProfileField(BaseModel):
    value: object
    source: Literal["stated", "inferred", "manual"]  # manual = edited in the Preferences panel
    last_updated_turn: int


class ProfileExtraction(BaseModel):
    """profile_updater output. null = not mentioned. [] for allergies = 'no allergies' was stated."""
    allergies: Optional[List[Allergen]] = Field(None, description="Food allergies. [] if user says none.")
    diet: Optional[List[str]] = Field(None, description="e.g. vegetarian, vegan, gluten_free, dairy_free, pescatarian, high_protein. [] if no restrictions.")
    dislikes: Optional[List[str]] = None
    favorite_cuisines: Optional[List[str]] = None
    household_size: Optional[int] = None
    budget: Optional[str] = Field(None, description="e.g. '$5 per serving', '$120/week', 'tight'")
    cooking_skill: Optional[Literal["beginner", "intermediate", "advanced"]] = None
    calorie_target: Optional[int] = Field(None, description="per-meal or daily kcal target as stated")
    equipment: Optional[List[str]] = None
    weeknight_effort: Optional[Literal["minimal", "moderate", "happy_to_cook"]] = None
    meals_to_plan: Optional[List[Literal["breakfast", "lunch", "dinner"]]] = Field(None, description="which meals the weekly plan should cover")
    leftovers_ok: Optional[bool] = Field(None, description="happy to batch cook and eat leftovers? false if they say they hate leftovers")
    busy_nights: Optional[List[Day]] = Field(None, description="nights this week that are toughest to cook dinner. [] if none are")
    nights_out: Optional[List[Day]] = Field(None, description="nights the user is eating elsewhere this week (plans, special occasions)")
    pantry: Optional[List[str]] = Field(None, description="ingredients the user says they have on hand")
    energy: Optional[Literal["low", "medium", "high"]] = None
    hunger: Optional[Literal["low", "medium", "high"]] = None
    eating_tonight: Optional[str] = Field(None, description="who is eating, e.g. 'just me', 'me + partner'")
    already_ate: Optional[List[str]] = Field(None, description="meals already eaten today, e.g. ['lunch']")
    mood: Optional[str] = None
    craving: Optional[str] = None
    location: Optional[Literal["home", "office", "traveling"]] = None
    time_limit_minutes: Optional[int] = None
    inferred_fields: List[str] = Field(default_factory=list, description="names of fields above that were inferred, not explicitly stated")
    replace_fields: List[str] = Field(default_factory=list, description="list fields the user CHANGED (replace instead of add), e.g. diet when 'actually I eat fish now'")


# --------------------------------------------------------------------------- #
# 3. Inter-agent structured outputs
# --------------------------------------------------------------------------- #
Intent = Literal["tonight_decision", "weekly_plan", "replan", "plan_question", "update_preferences", "food_qa",
                 "recipe_request", "smalltalk_or_out_of_scope"]
# Home-cooking modes. skip = eating elsewhere (plans with friends, a special-occasion dinner out).
Mode = Literal["cook_from_scratch", "quick_meal", "leftovers", "skip"]


class RoutingDecision(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    reason: str


class AdvisorDecision(BaseModel):
    """meal_advisor step 1: ask (max 2 short questions) or commit to a mode."""
    action: Literal["ask", "recommend"]
    questions: List[str] = Field(default_factory=list, description="0-2 short questions (only if action=ask)")
    question_targets: List[str] = Field(default_factory=list, description="fact each question is about: allergies|diet|energy|pantry|eating_tonight|craving|time_limit_minutes|location|mode")
    mode: Optional[Mode] = None
    target_meal: Literal["breakfast", "lunch", "dinner"] = "dinner"
    target_day: str = Field("today", description="'today', 'tomorrow' or mon..sun")
    time_available_minutes: Optional[int] = None
    reasoning: str = ""


class Pick(BaseModel):
    recipe_id: Optional[str] = None
    name: str
    why: str


class TonightRecommendation(BaseModel):
    mode: Mode
    target_meal: Literal["breakfast", "lunch", "dinner"] = "dinner"
    target_day: str = "today"
    primary: Pick
    alternatives: List[Pick] = Field(default_factory=list, max_length=2)
    time_plan: str = Field(description="e.g. 'start at 7:15, eat by 7:40'")
    start_time: Optional[str] = Field(None, description="HH:MM when cooking/leaving starts")
    ready_time: Optional[str] = Field(None, description="HH:MM when food is ready")
    assumptions: List[str] = Field(default_factory=list)


class FoodAnswer(BaseModel):
    answer: str
    safety_critical: bool = Field(description="food-safety temps/storage/allergen question")
    confidence: Literal["high", "medium", "low"]
    allergy_flags: List[str] = Field(default_factory=list, description="conflicts with the user's allergies/diet")
    medical_disclaimer: bool = False
    tie_back: Optional[str] = Field(None, description="optional ONE sentence tying back to the user's situation")


class IntakeResult(BaseModel):
    complete: bool
    missing_fields: List[str]
    question: str = Field("", description="one short friendly message asking ONLY for missing fields")


class PlannedMeal(BaseModel):
    day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    slot: Literal["breakfast", "lunch", "dinner"]
    mode: Mode
    recipe_id: Optional[str] = Field(None, description="required for cook_from_scratch / quick_meal; the recipe being eaten for leftovers")
    servings_to_cook: int = Field(0, description="servings to cook in this slot (0 for leftovers/skip). Batch cooks cook extra.")
    is_batch_cook: bool = False
    leftovers_from: Optional[str] = Field(None, description="'<day> <slot>' this leftover meal comes from")
    cook_minutes: int = 0
    available_minutes: Optional[int] = None
    note: str = ""


class WeeklyPlan(BaseModel):
    meals: List[PlannedMeal]
    summary: str


class Violation(BaseModel):
    item: str = Field(description="e.g. 'tue dinner: ita_pesto_gnocchi' or 'tonight primary'")
    rule: Literal["allergen", "diet", "calories", "budget", "time", "leftovers", "other"]
    detail: str


class ConstraintCheck(BaseModel):
    passed: bool
    violations: List[Violation] = Field(default_factory=list)


class ShoppingItem(BaseModel):
    name: str
    quantity: float
    unit: str
    category: str
    for_recipes: List[str] = Field(default_factory=list)


class ShoppingList(BaseModel):
    items: List[ShoppingItem]
    notes: str = ""


# --------------------------------------------------------------------------- #
# 4. Graph state (persists across turns via the LangGraph checkpointer)
# --------------------------------------------------------------------------- #
import warnings  # noqa: E402
from typing import Annotated, Any, TypedDict  # noqa: E402

warnings.filterwarnings("ignore", message=".*allowed_objects.*")  # noisy LangGraph pending-deprecation notice
from langgraph.graph.message import add_messages  # noqa: E402


class DnnerState(TypedDict, total=False):
    # --- persistent conversation state
    messages: Annotated[list, add_messages]
    session_id: str
    turn_index: int
    profile: Dict[str, Any]           # field -> ProfileField dict
    session_context: Dict[str, Any]   # field -> ProfileField dict
    active_task: Optional[Dict[str, Any]]  # {intent, agent, pending_question, question_targets, decisions_so_far, clarifying_turns, status}
    week_outline: Dict[str, Any]      # day -> {kind, cook_minutes, suggested_mode} (get_week_outline tool)
    current_plan: Optional[Dict[str, Any]]        # WeeklyPlan
    plan_changes: Optional[List[str]]             # replan diff for this turn
    shopping_list: Optional[Dict[str, Any]]       # ShoppingList
    tonight_recommendation: Optional[Dict[str, Any]]
    # --- per-turn scratch (reset at the start of every invocation)
    routing: Optional[Dict[str, Any]]             # RoutingDecision
    detected_intent: Optional[str]
    advisor_step: Optional[Dict[str, Any]]        # AdvisorDecision for this turn
    advisor_ctx: Optional[Dict[str, Any]]         # what meal_advisor gathered with tools this turn
    check_target: Optional[str]                   # "plan" | "tonight"
    constraint_check: Optional[Dict[str, Any]]
    retries: int
    retry_requested: bool
    food_answer: Optional[Dict[str, Any]]
    recipe_details: Optional[Dict[str, Any]]       # recipe_lookup: {resolved_by, recipe, allergen_conflicts, options}
    intake: Optional[Dict[str, Any]]
    final_response: str
