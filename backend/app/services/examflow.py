"""Goethe mock exam lifecycle: module unlocking, content generation on
module start, grading on submit, readiness snapshot on finish. Same
mutable-JSON-blob-as-state-machine idiom as placement.py, extended for a
multi-module exam.

Sprechen is the one module handled differently: instead of a form
submission, it reuses the existing /ws/voice/{conv_id} pipeline (P6) as a
single continuous conversation with an exam-examiner persona spanning all
of that module's parts, and is graded from the resulting transcript + the
same GOP pronunciation scoring conversations already get (P7) — building a
parallel WS endpoint just for exams would duplicate a lot of hardened
real-time-pipeline code for no real benefit.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import content, exam_grading, examgen, gamification, grader, learner, personas, projection
from ..models import Conversation, ConvTurn, MockExam, MockSection, Setting, UtteranceScore, utcnow

MODULE_SKILL = {"lesen": "reading", "hoeren": "listening", "schreiben": "writing", "sprechen": "speaking"}
MODULE_WEIGHT = 2.0  # a full mock module is a much stronger signal than a single exercise (cf. TASK_WEIGHT ~0.6-1.0)


def _module_order(level: str) -> list[str]:
    return list(content.exam_blueprint(level)["modules"].keys())


def start(db: Session, level: str, mode: str = "full") -> MockExam:
    exam = MockExam(level=level, mode=mode, results={})
    db.add(exam)
    db.commit()
    db.refresh(exam)

    order = _module_order(level)
    exam.results = {
        "status": "active", "module_order": order,
        "modules": {m: {"status": "not_started", "section_ids": [], "score": None, "max_score": None} for m in order},
    }
    db.commit()
    return exam


def _public_section(db: Session, section_id: str) -> dict:
    s = db.get(MockSection, section_id)
    return {"id": s.id, "teil": s.payload.get("teil"), "kind": s.payload.get("kind"),
            "shape": examgen.shape_for(s.payload.get("kind", "")), "payload": s.payload, "status": s.status}


def get_state(db: Session, exam_id: str) -> dict:
    exam = db.get(MockExam, exam_id)
    if exam is None:
        return {}
    r = exam.results
    if r.get("status") == "done":
        return r

    modules = {}
    for i, name in enumerate(r["module_order"]):
        m = r["modules"][name]
        locked = any(r["modules"][prev]["status"] != "done" for prev in r["module_order"][:i])
        entry = {"status": "locked" if locked and m["status"] == "not_started" else m["status"],
                 "score": m["score"], "max_score": m["max_score"]}
        if m["status"] in ("active", "done") and m["section_ids"]:
            entry["sections"] = [_public_section(db, sid) for sid in m["section_ids"]]
        if name == "sprechen" and r.get("speaking_conv_id"):
            entry["conv_id"] = r["speaking_conv_id"]
        modules[name] = entry

    return {"id": exam.id, "level": exam.level, "status": r["status"], "module_order": r["module_order"], "modules": modules}


async def start_module(db: Session, exam_id: str, module_name: str) -> dict:
    exam = db.get(MockExam, exam_id)
    r = exam.results
    order = r["module_order"]
    idx = order.index(module_name)
    if any(r["modules"][prev]["status"] != "done" for prev in order[:idx]):
        raise ValueError("previous module not finished yet")

    if r["modules"][module_name]["status"] == "not_started":
        blueprint_module = content.exam_blueprint(exam.level)["modules"][module_name]
        if module_name == "sprechen":
            section_ids = await _start_speaking(db, exam, blueprint_module)
        else:
            parts = await examgen.generate_module(exam.level, module_name)
            section_ids = []
            for p in parts:
                # lesen/hoeren parts have no per-part "points" in the blueprint
                # (scoring is 1 raw point per item, scaled at module level) —
                # only schreiben/sprechen parts carry an explicit points value.
                max_score = p["points"] if p["points"] is not None else p["items"]
                sec = MockSection(exam_id=exam.id, module=module_name, status="active",
                                   payload={**p["payload"], "kind": p["kind"], "points": p["points"]},
                                   answers={}, max_score=max_score)
                sec.grader_detail = {"answer_key": p["answer_key"]}
                db.add(sec)
                db.flush()
                section_ids.append(sec.id)

        # Re-read fresh (not the `r` captured above, which _start_speaking
        # may already have updated) and build an entirely NEW nested dict —
        # never write into the old one first. SQLAlchemy's JSON-column
        # change tracking compares the reassigned value against its cached
        # current value; mutating any part of that cached structure in
        # place before reassigning makes the two look identical and the
        # write gets silently dropped (confirmed empirically — this exact
        # in-place-then-reassign pattern loses the write across sessions).
        current = exam.results
        new_module = {**current["modules"][module_name], "status": "active", "section_ids": section_ids}
        exam.results = {**current, "modules": {**current["modules"], module_name: new_module}}
        db.commit()

    return get_state(db, exam_id)


async def _start_speaking(db: Session, exam: MockExam, blueprint_module: dict) -> list[str]:
    parts = []
    for part in blueprint_module["parts"]:
        _, item = await examgen.generate_part(exam.level, part["kind"], part["spec"], part["items"])
        item_payload, _ = examgen.split_part(examgen.shape_for(part["kind"]), part["kind"], item)
        parts.append({"teil": part["teil"], "points": part.get("points", 0), **item_payload})

    system_prompt = personas.exam_speaking_system_prompt(exam.level, parts)
    conv = Conversation(scenario={"id": "exam", "title_de": "Prüfung: Sprechen"}, persona="exam", level=exam.level)
    db.add(conv)
    db.flush()

    total_points = sum(p["points"] for p in parts) or 1
    sec = MockSection(exam_id=exam.id, module="sprechen", status="active",
                       payload={"teil": 0, "kind": "conversation", "points": total_points, "parts": parts,
                                "conv_id": conv.id, "system_prompt": system_prompt},
                       answers={}, max_score=total_points)
    db.add(sec)
    db.flush()

    # ws_voice.py's context loader needs to find this section from the
    # Conversation row alone (it only has conv_id) to pull system_prompt.
    conv.scenario = {"id": "exam", "section_id": sec.id, "title_de": "Prüfung: Sprechen"}
    db.commit()

    exam.results = {**exam.results, "speaking_conv_id": conv.id, "speaking_section_id": sec.id}
    db.commit()
    return [sec.id]


async def submit_section(db: Session, exam_id: str, section_id: str, response: dict) -> dict:
    exam = db.get(MockExam, exam_id)
    sec = db.get(MockSection, section_id)
    kind = sec.payload.get("kind")
    shape = examgen.shape_for(kind)
    answer_key = sec.grader_detail.get("answer_key", {})

    if shape == "comprehension":
        result = grader.grade_comprehension(answer_key, response)
    elif shape == "matching":
        result = grader.grade_matching(answer_key, response)
    elif kind == "form":
        result = grader.grade_form(answer_key, response)
    else:  # "text" — free writing
        result = await exam_grading.grade_writing(
            db, exam.level, sec.payload.get("scenario_de", ""), sec.payload.get("content_points_de", []),
            _target_words(sec.payload), response.get("text", ""),
        )

    sec.answers = response
    sec.score = round(result["score"] * (sec.max_score or 1), 2)
    sec.grader_detail = {**sec.grader_detail, "result": result["detail"]}
    sec.status = "done"
    db.commit()

    return await _maybe_complete_module(db, exam, sec.module)


def _target_words(payload: dict) -> int:
    return payload.get("words") or 40


async def finish_speaking(db: Session, exam_id: str) -> dict:
    exam = db.get(MockExam, exam_id)
    r = exam.results
    sec = db.get(MockSection, r["speaking_section_id"])
    conv_id = r["speaking_conv_id"]

    turns = db.scalars(select(ConvTurn).where(ConvTurn.conv_id == conv_id).order_by(ConvTurn.idx)).all()
    transcript = [{"role": t.role, "text": t.text_de} for t in turns]
    instructions = " ".join(p["instructions_de"] for p in sec.payload["parts"])
    prompts = [pr for p in sec.payload["parts"] for pr in p.get("prompts_de", [])]

    result = await exam_grading.grade_speaking(instructions, prompts, transcript, exam.level)
    pron_scores = db.scalars(
        select(UtteranceScore.overall).join(ConvTurn, ConvTurn.id == UtteranceScore.turn_id)
        .where(ConvTurn.conv_id == conv_id)
    ).all()
    aussprache_pct = (sum(pron_scores) / len(pron_scores) / 100) if pron_scores else None

    blueprint_module = content.exam_blueprint(exam.level)["modules"]["sprechen"]
    extra = blueprint_module.get("extra_points", {})
    speaking_max = sec.max_score or 1
    if "aussprache" in extra and aussprache_pct is not None:
        content_max = speaking_max
        speaking_max += extra["aussprache"]
        total_score = result["score"] * content_max + aussprache_pct * extra["aussprache"]
    else:
        total_score = result["score"] * speaking_max

    sec.answers = {"transcript_turns": len(transcript)}
    sec.score = round(total_score, 2)
    sec.max_score = speaking_max
    sec.grader_detail = {**sec.grader_detail, "result": result["detail"], "aussprache_pct": aussprache_pct}
    sec.status = "done"
    db.commit()

    return await _maybe_complete_module(db, exam, "sprechen")


async def _maybe_complete_module(db: Session, exam: MockExam, module_name: str) -> dict:
    r = exam.results
    m = r["modules"][module_name]
    sections = db.scalars(select(MockSection).where(MockSection.id.in_(m["section_ids"]))).all()
    if any(s.status != "done" for s in sections):
        db.commit()
        return get_state(db, exam.id)

    raw_score = sum(s.score or 0 for s in sections)
    raw_max = sum(s.max_score or 0 for s in sections)
    blueprint_module = content.exam_blueprint(exam.level)["modules"][module_name]
    scaled_score = (raw_score / raw_max * blueprint_module["scale_to"]) if raw_max else 0.0

    # Build fresh dicts throughout (see start_module's comment) — never
    # write into `m`/`r` before reassigning exam.results.
    new_module = {**m, "status": "done", "score": round(scaled_score, 1), "max_score": blueprint_module["scale_to"]}
    new_modules = {**r["modules"], module_name: new_module}
    exam.results = {**r, "modules": new_modules}
    db.commit()

    skill = MODULE_SKILL.get(module_name)
    if skill:
        difficulty = learner.LEVEL_MIDPOINT.get(exam.level, 45.0)
        learner.update_skill(db, skill, scaled_score / blueprint_module["scale_to"], difficulty, weight=MODULE_WEIGHT)

    module_pct = scaled_score / blueprint_module["scale_to"] * 100
    module_xp = gamification.XP_MOCK_MODULE
    if module_pct >= content.exam_blueprint(exam.level)["pass_pct"]:
        module_xp += gamification.XP_MOCK_MODULE_PASS_BONUS
    gamification.award_xp(db, "mock_module", module_xp, ref={"exam_id": exam.id, "module": module_name})

    if all(new_modules[mm]["status"] == "done" for mm in r["module_order"]):
        return await finish(db, exam)
    gamification.evaluate_badges(db)
    return get_state(db, exam.id)


async def finish(db: Session, exam: MockExam) -> dict:
    r = exam.results
    blueprint = content.exam_blueprint(exam.level)
    per_module = {name: {"score": r["modules"][name]["score"], "max_score": r["modules"][name]["max_score"],
                          "pct": round(r["modules"][name]["score"] / r["modules"][name]["max_score"] * 100, 1)
                          if r["modules"][name]["max_score"] else 0.0}
                  for name in r["module_order"]}

    total_score = sum(v["score"] for v in per_module.values())
    total_max = sum(v["max_score"] for v in per_module.values())
    total_pct = round(total_score / total_max * 100, 1) if total_max else 0.0

    if blueprint["scoring"] == "modular":
        passed = all(v["pct"] >= blueprint["pass_pct"] for v in per_module.values())
    else:
        passed = total_pct >= blueprint["pass_pct"]

    exam.finished_at = utcnow()
    exam.results = {**r, "status": "done", "per_module": per_module, "total_pct": total_pct, "passed": passed}

    goal_row = db.get(Setting, "goal_date_b1")
    goal_date = goal_row.value if goal_row and goal_row.value else projection.default_goal_date()
    proj = projection.compute_projection(db, goal_date, exam.level)
    exam.readiness_snapshot = {
        "at": datetime.now(timezone.utc).isoformat(), "level": exam.level, "passed": passed,
        "total_pct": total_pct, "per_module_pct": {k: v["pct"] for k, v in per_module.items()},
        "projection": proj,
    }
    db.commit()

    if passed:
        gamification.award_xp(db, "mock_full_pass", gamification.XP_MOCK_FULL_PASS, ref={"exam_id": exam.id, "level": exam.level})
    gamification.evaluate_badges(db)

    return exam.results
