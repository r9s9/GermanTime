"""Theil-Sen slope estimator and readiness/slip projection logic."""

from datetime import date, timedelta

from app.services import learner, projection


def test_theil_sen_slope_perfect_line():
    xs = [0, 10, 20, 30]
    ys = [0, 5, 10, 15]  # slope 0.5
    assert abs(projection.theil_sen_slope(xs, ys) - 0.5) < 1e-9


def test_theil_sen_slope_robust_to_outlier():
    xs = [0, 10, 20, 30, 40]
    ys = [0, 5, 10, 15, 1000]  # one wild outlier shouldn't dominate a median-based slope
    slope = projection.theil_sen_slope(xs, ys)
    assert abs(slope - 0.5) < 1.0


def test_theil_sen_slope_empty_or_single_point():
    assert projection.theil_sen_slope([], []) == 0.0
    assert projection.theil_sen_slope([1], [1]) == 0.0


def _seed_history(db_session, days_minutes_theta: list[tuple[str, float, float]]) -> None:
    from app.models import PlanDay

    for d, minutes, _theta in days_minutes_theta:
        db_session.add(PlanDay(date=d, syllabus_week=1, status="done", core_done=True, minutes_done=minutes))
    for skill in learner.SKILLS:
        row = learner._get_or_create(db_session, skill)
        row.history = [{"d": d, "theta": theta} for d, _, theta in days_minutes_theta]
        row.theta = days_minutes_theta[-1][2]
    db_session.commit()


def test_projection_with_no_history_is_honestly_uncertain(db_session):
    result = projection.compute_projection(db_session, projection.default_goal_date(6))
    assert result["data_points"] == 0
    assert result["slipping"] is True
    assert result["projected_date"] is None


def test_projection_with_steady_good_pace_is_not_slipping(db_session):
    start = date.today() - timedelta(days=27)
    theta = 5.0
    days = []
    for i in range(28):
        theta += 1.0  # steady, healthy daily gain
        days.append(((start + timedelta(days=i)).isoformat(), 20.0, theta))
    _seed_history(db_session, days)

    result = projection.compute_projection(db_session, projection.default_goal_date(6))
    assert result["theta_per_minute"] > 0
    assert result["projected_date"] is not None
    assert result["slipping"] is False


def test_projection_with_stalled_progress_is_slipping(db_session):
    start = date.today() - timedelta(days=27)
    days = [((start + timedelta(days=i)).isoformat(), 20.0, 10.0) for i in range(28)]  # minutes invested, theta flat
    _seed_history(db_session, days)

    result = projection.compute_projection(db_session, projection.default_goal_date(6))
    assert result["slipping"] is True


def test_projection_already_at_goal_theta_is_not_slipping(db_session):
    start = date.today() - timedelta(days=13)
    days = [((start + timedelta(days=i)).isoformat(), 20.0, 75.0) for i in range(14)]
    _seed_history(db_session, days)

    result = projection.compute_projection(db_session, projection.default_goal_date(6), goal_level="B1")
    assert result["overall_theta"] >= learner.EXAM_READY_THETA["B1"]
    assert result["slipping"] is False


def test_default_goal_date_is_about_six_months_out():
    goal = date.fromisoformat(projection.default_goal_date(6))
    days_ahead = (goal - date.today()).days
    assert 170 <= days_ahead <= 190
