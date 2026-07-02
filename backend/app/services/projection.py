"""Pace projection and certificate-readiness prediction.

Honest-by-design: with too little history the projection returns
`slipping=True` and no promised date rather than a falsely confident number.
"""

import statistics
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import learner
from ..models import LearnerSkill, PlanDay

TRAILING_SLOPE_DAYS = 28
TRAILING_MINUTES_DAYS = 14
READINESS_BUFFER_DAYS = 14  # plan.md: warn if projected > goal - 14 days
MIN_POINTS_FOR_SLOPE = 4


def theil_sen_slope(xs: list[float], ys: list[float]) -> float:
    """Median of pairwise slopes — robust to outlier days, no scipy needed."""
    slopes = []
    n = len(xs)
    for i in range(n):
        for j in range(i + 1, n):
            if xs[j] != xs[i]:
                slopes.append((ys[j] - ys[i]) / (xs[j] - xs[i]))
    if not slopes:
        return 0.0
    slopes.sort()
    mid = len(slopes) // 2
    return slopes[mid] if len(slopes) % 2 else (slopes[mid - 1] + slopes[mid]) / 2


def theta_history_by_date(db: Session) -> dict[str, float]:
    """date -> average theta across all skills, forward-filling each skill
    from its most recent snapshot at or before that date."""
    rows = db.scalars(select(LearnerSkill)).all()
    all_dates = sorted({h["d"] for r in rows for h in (r.history or [])})
    last_known: dict[str, float | None] = {r.skill: None for r in rows}
    result = {}
    for d in all_dates:
        for r in rows:
            for h in (r.history or []):
                if h["d"] == d:
                    last_known[r.skill] = h["theta"]
        vals = [v for v in last_known.values() if v is not None]
        if vals:
            result[d] = sum(vals) / len(vals)
    return result


def _cumulative_minutes_by_date(db: Session) -> dict[str, float]:
    days = db.scalars(select(PlanDay).order_by(PlanDay.date)).all()
    result, running = {}, 0.0
    for d in days:
        running += d.minutes_done
        result[d.date] = running
    return result


def compute_projection(db: Session, goal_date_iso: str, goal_level: str = "B1") -> dict:
    thetas = learner.get_all_thetas(db)
    overall = learner.overall_theta(thetas)
    goal_date = date.fromisoformat(goal_date_iso)
    today = date.today()
    cutoff = (today - timedelta(days=TRAILING_SLOPE_DAYS)).isoformat()

    theta_hist = theta_history_by_date(db)
    cum_minutes = _cumulative_minutes_by_date(db)

    points = [(cum_minutes[d], theta_hist[d]) for d in theta_hist if d >= cutoff and d in cum_minutes]

    plan_days = db.scalars(
        select(PlanDay).where(PlanDay.date >= (today - timedelta(days=TRAILING_MINUTES_DAYS)).isoformat())
    ).all()
    median_daily_minutes = statistics.median([d.minutes_done for d in plan_days]) if plan_days else 0.0

    slope = theil_sen_slope([p[0] for p in points], [p[1] for p in points]) if len(points) >= MIN_POINTS_FOR_SLOPE else 0.0
    projected_gain_per_day = max(0.0, slope) * median_daily_minutes

    target = learner.EXAM_READY_THETA[goal_level]
    remaining = target - overall

    projected_date = None
    required_minutes_per_day = None
    if remaining <= 0:
        projected_date = today
    elif projected_gain_per_day > 0:
        days_needed = remaining / projected_gain_per_day
        if days_needed < 3650:  # sanity cap so we never serialize an absurd date
            projected_date = today + timedelta(days=round(days_needed))

    days_until_goal = (goal_date - today).days
    slipping = projected_date is None or (projected_date - goal_date).days > -READINESS_BUFFER_DAYS

    if slipping and days_until_goal > 0:
        required_minutes_per_day = round(remaining / days_until_goal / max(slope, 0.001), 1) if slope > 0 else None

    return {
        "overall_theta": round(overall, 1),
        "cefr": learner.cefr_label(overall),
        "target_theta": target,
        "median_daily_minutes": round(median_daily_minutes, 1),
        "theta_per_minute": round(slope, 4),
        "data_points": len(points),
        "projected_date": projected_date.isoformat() if projected_date else None,
        "goal_date": goal_date_iso,
        "days_until_goal": days_until_goal,
        "slipping": slipping,
        "required_minutes_per_day": required_minutes_per_day,
    }


def default_goal_date(months: int = 6) -> str:
    d = date.today()
    # naive month-add avoids a dependency; fine at day-level projection precision
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, 28)
    return date(year, month, day).isoformat()
