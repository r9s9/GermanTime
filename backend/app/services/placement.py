"""Adaptive placement test: a text-only staircase (reused `mc` exercises,
which inherently test grammar+vocab+reading) that initializes all 7 skill
thetas. Listening and speaking calibration is deliberately deferred to real
conversation + pronunciation practice (P6/P7) rather than faked here —
skills untestable today are seeded at a conservative fraction of the
measured result and get corrected once real signal arrives.
"""

from sqlalchemy.orm import Session

from . import factory, grader, learner, projection
from ..models import Exercise, ExerciseAttempt, Placement, Setting, utcnow

# (label, level_for_generation, midpoint) — must align 1:1 with learner.CEFR_BANDS
RUNGS = [(label, ("A1" if label.startswith("A1") else "A2" if label.startswith("A2") else "B1"), (lo + hi) / 2)
         for label, lo, hi in learner.CEFR_BANDS]

ITEMS_PER_RUNG = 2
MAX_ITEMS = 25
MAX_CONSECUTIVE_FAILS = 3
PASS_THRESHOLD = 0.6
ACHIEVED_THRESHOLD = 0.5
UNTESTED_SKILL_FRACTION = 0.7  # conservative seed for listening/speaking/writing/pronunciation

SELF_REPORT_START_RUNG = {"none": 0, "some": 0, "a1": 1, "a2": 2, "b1": 4}


def _rung_bounds(idx: int) -> tuple[float, float]:
    _, lo, hi = learner.CEFR_BANDS[idx]
    return float(lo), float(hi)


async def start(db: Session, self_report: str) -> Placement:
    p = Placement(items=[], result={})
    db.add(p)
    db.commit()
    db.refresh(p)

    rung = SELF_REPORT_START_RUNG.get(self_report, 0)
    p.result = {"status": "active", "self_report": self_report, "rung": rung,
                "consecutive_fails": 0, "visited": []}
    db.commit()
    await _generate_rung_items(db, p, rung)
    return p


async def _generate_rung_items(db: Session, p: Placement, rung: int) -> None:
    _, level, _ = RUNGS[rung]
    item_ids = [(await factory.generate_one(db, "mc", level, topic_id=None)).id for _ in range(ITEMS_PER_RUNG)]
    p.result = {**p.result, "pending_rung": rung, "pending_items": item_ids, "pending_answers": {}}
    db.commit()


def _public_item(db: Session, exercise_id: str) -> dict:
    ex = db.get(Exercise, exercise_id)
    return {"id": ex.id, "type": ex.type, "payload": ex.payload}


def get_state(db: Session, placement_id: str) -> dict:
    p = db.get(Placement, placement_id)
    if p is None:
        return {}
    result = p.result
    if result.get("status") == "done":
        return result
    return {
        "status": result.get("status"),
        "rung": result.get("pending_rung"),
        "rung_label": RUNGS[result["pending_rung"]][0],
        "items": [_public_item(db, i) for i in result.get("pending_items", [])],
    }


async def answer(db: Session, placement_id: str, exercise_id: str, response: dict) -> dict:
    p = db.get(Placement, placement_id)
    ex = db.get(Exercise, exercise_id)
    result = grader.grade(ex.type, ex.answer_key, response)
    db.add(ExerciseAttempt(exercise_id=ex.id, response=response, score=result["score"],
                            detail=result["detail"], graded_by="auto", finished_at=utcnow()))

    answers = {**p.result.get("pending_answers", {}), exercise_id: result["score"]}
    p.result = {**p.result, "pending_answers": answers}
    p.items = [*p.items, {"exercise_id": exercise_id, "score": result["score"]}]
    db.commit()

    if len(answers) < len(p.result.get("pending_items", [])):
        return {"finished": False, "rung_complete": False}

    return await _complete_rung(db, p)


async def _complete_rung(db: Session, p: Placement) -> dict:
    scores = list(p.result["pending_answers"].values())
    avg = sum(scores) / len(scores)
    rung = p.result["pending_rung"]
    passed = avg >= PASS_THRESHOLD
    consecutive_fails = 0 if passed else p.result.get("consecutive_fails", 0) + 1
    visited = [*p.result.get("visited", []), {"rung": rung, "avg": avg}]

    finished, reason = False, None
    next_rung = rung
    if passed and rung == len(RUNGS) - 1:
        finished, reason = True, "top_rung_passed"
    elif consecutive_fails >= MAX_CONSECUTIVE_FAILS:
        finished, reason = True, "max_fails"
    elif len(p.items) >= MAX_ITEMS:
        finished, reason = True, "max_items"
    else:
        next_rung = min(len(RUNGS) - 1, rung + 1) if passed else max(0, rung - 1)
        if next_rung == rung:
            finished, reason = True, "edge"

    p.result = {**p.result, "visited": visited, "consecutive_fails": consecutive_fails}
    db.commit()

    if finished:
        summary = await finish(db, p, reason)
        return {"finished": True, "rung_complete": True, "summary": summary}

    await _generate_rung_items(db, p, next_rung)
    return {"finished": False, "rung_complete": True, "next_rung": next_rung}


async def finish(db: Session, p: Placement, reason: str) -> dict:
    visited = p.result.get("visited", [])
    achieved = [v for v in visited if v["avg"] >= ACHIEVED_THRESHOLD]
    best = achieved[-1] if achieved else (visited[0] if visited else {"rung": 0, "avg": 0.5})

    rung_idx = best["rung"]
    label = RUNGS[rung_idx][0]
    mid = RUNGS[rung_idx][2]
    lo, hi = _rung_bounds(rung_idx)
    placement_theta = max(0.0, min(100.0, mid + (best["avg"] - 0.5) * (hi - lo)))

    thetas = {
        "grammar": placement_theta, "vocab": placement_theta, "reading": placement_theta,
        "writing": placement_theta * UNTESTED_SKILL_FRACTION,
        "speaking": placement_theta * UNTESTED_SKILL_FRACTION,
        "listening": placement_theta * UNTESTED_SKILL_FRACTION,
        "pronunciation": placement_theta * UNTESTED_SKILL_FRACTION,
    }
    for skill, theta in thetas.items():
        learner.set_theta(db, skill, theta)

    week = learner.week_for_theta(placement_theta)
    learner.credit_prior_topics(db, week)

    if db.get(Setting, "goal_date_b1") is None:
        db.add(Setting(key="goal_date_b1", value=projection.default_goal_date(6)))

    p.finished_at = utcnow()
    p.result = {
        **p.result, "status": "done", "reason": reason,
        "placement_theta": round(placement_theta, 1), "cefr": label, "syllabus_week": week,
        "thetas": {k: round(v, 1) for k, v in thetas.items()},
        "untested_skills": ["writing", "speaking", "listening", "pronunciation"],
    }
    db.commit()
    return p.result
