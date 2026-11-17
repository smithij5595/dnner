"""Cached loader for dormant/restaurants/data/restaurants.json."""
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

from dormant.restaurants.models import Restaurant

DATA_FILE = Path(__file__).resolve().parent / "data" / "restaurants.json"


@lru_cache(maxsize=None)
def restaurants() -> Dict[str, Restaurant]:
    return {r["id"]: Restaurant(**r) for r in json.loads(DATA_FILE.read_text())}
