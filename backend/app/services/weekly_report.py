"""Weekly progress report: this-week-vs-last-week deltas (minutes, XP,
SRS retention, weak-phoneme movement, readiness-date drift) plus a short
LLM summary in graded German. Generated on demand and cached by ISO week
(iso_week is the primary key) rather than via a background scheduler —
there's no long-running process to host one, and "check if this week's
report exists, generate if not" is simpler and just as effective for a
single-user app.
"""

from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import llm, projection
from ..models import DailyActivity, PhonemeStat, ReviewLog, Setting, WeeklyReport, utcnow


class WeeklySummary(BaseModel):
    summary_de: str = Field(description="Kurze, ermutigende Zusammenfassung der Lernwoche auf Deutsch, "
                                         "2-4 einfache Sätze, wie eine Nachricht von einem freundlichen Tutor")


def iso_week_str(d: date | None = None) -> str:
    d = d or date.today()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _week_bounds(iso_week: str) -> tuple[date, date]:
    year_s, week_s = iso_week.split("-W")
    start = date.fromisocalendar(int(year_s), int(week_s), 1)
    return start, start + timedelta(days=6)


def _prev_week(iso_week: str) -> str:
    start, _ = _week_bounds(iso_week)
    return iso_week_str(start - timedelta(days=7))


def _week_activity(db: Session, iso_week: str) -> list[DailyActivity]:
    start, end = _week_bounds(iso_week)
    return list(db.scalars(
        select(DailyActivity).where(DailyActivity.date >= start.isoformat(), DailyActivity.date <= end.isoformat())
    ))


def _retention(db: Session, iso_week: str) -> float | None:
    start, end = _week_bounds(iso_week)
    logs = db.scalars(
        select(ReviewLog).where(ReviewLog.reviewed_at >= start.isoformat(), ReviewLog.reviewed_at < (end + timedelta(days=1)).isoformat())
    ).all()
    if not logs:
        return None
    return sum(1 for lg in logs if lg.rating >= 3) / len(logs)


def _weak_phoneme_snapshot(db: Session) -> dict[str, float]:
    return {s.phoneme: round(s.ema, 1) for s in db.scalars(select(PhonemeStat).where(PhonemeStat.n >= 3))}


def compute_stats(db: Session, iso_week: str) -> dict:
    rows = _week_activity(db, iso_week)
    minutes = round(sum(r.minutes for r in rows), 1)
    xp = sum(r.xp for r in rows)
    core_days = sum(1 for r in rows if r.core_done)
    retention = _retention(db, iso_week)
    return {"minutes": minutes, "xp": xp, "core_days": core_days, "retention": retention}


async def generate(db: Session, iso_week: str | None = None, force: bool = False) -> dict:
    iso_week = iso_week or iso_week_str()
    existing = db.get(WeeklyReport, iso_week)
    if existing and not force:
        return existing.payload

    stats = compute_stats(db, iso_week)
    prev_report = db.get(WeeklyReport, _prev_week(iso_week))
    prev_stats = prev_report.payload.get("stats") if prev_report else None

    phoneme_now = _weak_phoneme_snapshot(db)
    phoneme_prev = (prev_report.payload.get("phoneme_snapshot") if prev_report else None) or {}
    phoneme_deltas = {
        p: round(phoneme_now[p] - phoneme_prev[p], 1)
        for p in phoneme_now if p in phoneme_prev and abs(phoneme_now[p] - phoneme_prev[p]) >= 3
    }

    goal_row = db.get(Setting, "goal_date_b1")
    goal_date = goal_row.value if goal_row and goal_row.value else projection.default_goal_date()
    proj = projection.compute_projection(db, goal_date)
    prev_projected_date = prev_report.payload.get("projection", {}).get("projected_date") if prev_report else None
    readiness_delta_days = None
    if prev_projected_date and proj.get("projected_date"):
        readiness_delta_days = (date.fromisoformat(proj["projected_date"]) - date.fromisoformat(prev_projected_date)).days

    deltas = {
        "minutes": round(stats["minutes"] - prev_stats["minutes"], 1) if prev_stats else None,
        "xp": stats["xp"] - prev_stats["xp"] if prev_stats else None,
        "retention": round(stats["retention"] - prev_stats["retention"], 2)
        if prev_stats and stats["retention"] is not None and prev_stats.get("retention") is not None else None,
        "readiness_days": readiness_delta_days,
    }

    summary_de = await _generate_summary(stats, deltas, proj)

    payload = {
        "iso_week": iso_week, "stats": stats, "deltas": deltas, "phoneme_snapshot": phoneme_now,
        "phoneme_deltas": phoneme_deltas, "projection": proj, "summary_de": summary_de,
    }

    if existing:
        existing.payload = payload
        existing.generated_at = utcnow()
    else:
        db.add(WeeklyReport(iso_week=iso_week, payload=payload))
    db.commit()
    return payload


async def _generate_summary(stats: dict, deltas: dict, proj: dict) -> str:
    system = (
        "Du bist ein freundlicher Deutschlehrer. Schreibe eine kurze, ermutigende Wochenzusammenfassung "
        "für einen Lernenden, auf Einfachem Deutsch (Niveau A2). Sei konkret und positiv, auch wenn wenig "
        "Zeit investiert wurde — kein Tadel, nur Ermutigung und ein klarer nächster Schritt."
    )
    trend = "mehr" if (deltas.get("minutes") or 0) > 0 else "weniger" if (deltas.get("minutes") or 0) < 0 else "gleich viel"
    user = (
        f"Diese Woche: {stats['minutes']} Minuten gelernt, {stats['xp']} XP, {stats['core_days']} Tage mit "
        f"Tagesziel geschafft. Das ist {trend} als letzte Woche. Aktuelles Niveau: {proj.get('cefr')}. "
        f"Prognose fürs Ziel: {proj.get('projected_date') or 'noch unklar'}."
    )
    try:
        result = await llm.generate_structured("fast", system, user, WeeklySummary, "weekly_summary")
        return result.summary_de
    except Exception:  # noqa: BLE001 — the report itself (stats/deltas) is still useful without prose
        return ""
