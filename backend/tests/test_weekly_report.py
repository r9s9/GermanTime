"""Weekly report: stats/deltas computation, week-over-week comparison,
and caching by iso_week. The LLM summary call is faked (matching
test_factory.py's pattern) so these run with no server."""

import pytest

from app.services import weekly_report


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    async def fake_generate_structured(role, system, user, model_cls, schema_name, **kwargs):
        return model_cls(summary_de="Gut gemacht diese Woche!")

    monkeypatch.setattr(weekly_report.llm, "generate_structured", fake_generate_structured)


def test_iso_week_str_format():
    from datetime import date
    assert weekly_report.iso_week_str(date(2026, 7, 6)) == "2026-W28"


def test_prev_week_wraps_correctly():
    assert weekly_report._prev_week("2026-W01") == "2025-W52"


@pytest.mark.asyncio
async def test_generate_creates_and_caches_report(db_session):
    from app.models import DailyActivity

    db_session.add(DailyActivity(date="2026-01-05", minutes=20.0, xp=50, core_done=True, streak_after=1))
    db_session.commit()

    iso_week = weekly_report.iso_week_str(__import__("datetime").date(2026, 1, 5))
    payload = await weekly_report.generate(db_session, iso_week)

    assert payload["stats"]["minutes"] == 20.0
    assert payload["stats"]["xp"] == 50
    assert payload["summary_de"] == "Gut gemacht diese Woche!"

    from app.models import WeeklyReport
    row = db_session.get(WeeklyReport, iso_week)
    assert row is not None
    assert row.payload == payload


@pytest.mark.asyncio
async def test_generate_is_cached_unless_forced(db_session, monkeypatch):
    calls = []

    async def counting_generate(role, system, user, model_cls, schema_name, **kwargs):
        calls.append(1)
        return model_cls(summary_de="x")

    monkeypatch.setattr(weekly_report.llm, "generate_structured", counting_generate)

    iso_week = "2026-W10"
    await weekly_report.generate(db_session, iso_week)
    await weekly_report.generate(db_session, iso_week)  # cached, no new LLM call
    assert len(calls) == 1

    await weekly_report.generate(db_session, iso_week, force=True)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_generate_computes_deltas_against_previous_week(db_session):
    from app.models import DailyActivity

    db_session.add(DailyActivity(date="2026-01-05", minutes=10.0, xp=20, core_done=True, streak_after=1))
    db_session.commit()
    week1 = weekly_report.iso_week_str(__import__("datetime").date(2026, 1, 5))
    await weekly_report.generate(db_session, week1)

    db_session.add(DailyActivity(date="2026-01-12", minutes=30.0, xp=60, core_done=True, streak_after=1))
    db_session.commit()
    week2 = weekly_report.iso_week_str(__import__("datetime").date(2026, 1, 12))
    payload2 = await weekly_report.generate(db_session, week2)

    assert payload2["deltas"]["minutes"] == pytest.approx(20.0)
    assert payload2["deltas"]["xp"] == 40


@pytest.mark.asyncio
async def test_generate_survives_llm_failure(db_session, monkeypatch):
    async def boom(role, system, user, model_cls, schema_name, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(weekly_report.llm, "generate_structured", boom)

    payload = await weekly_report.generate(db_session, "2026-W15")
    assert payload["summary_de"] == ""  # empty, not a crash
    assert "stats" in payload
