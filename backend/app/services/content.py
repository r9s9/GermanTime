"""Cached raw loaders for static reference JSON that doesn't need DB tables
(syllabus, exam blueprints, phoneme map, UI strings). Grammar topics, vocab,
and badges DO live in the DB (they need FK relationships) — see seeds.py.
"""

import json
from functools import lru_cache

from .. import config


@lru_cache(maxsize=1)
def syllabus() -> list[dict]:
    with open(config.SEED_DIR / "syllabus.json", encoding="utf-8") as f:
        return json.load(f)["weeks"]


@lru_cache(maxsize=1)
def phoneme_map() -> dict:
    with open(config.SEED_DIR / "phoneme_map.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def ui_strings() -> dict:
    with open(config.SEED_DIR / "ui_strings.json", encoding="utf-8") as f:
        return json.load(f)["strings"]


@lru_cache(maxsize=1)
def scenarios() -> list[dict]:
    with open(config.SEED_DIR / "scenarios.json", encoding="utf-8") as f:
        return json.load(f)["scenarios"]


def scenario_by_id(scenario_id: str) -> dict | None:
    return next((s for s in scenarios() if s["id"] == scenario_id), None)


@lru_cache(maxsize=8)
def exam_blueprint(level: str) -> dict:
    with open(config.SEED_DIR / "exam_blueprints" / f"{level.lower()}.json", encoding="utf-8") as f:
        return json.load(f)


def exam_blueprints() -> dict[str, dict]:
    return {lvl: exam_blueprint(lvl) for lvl in ("a1", "a2", "b1")}
