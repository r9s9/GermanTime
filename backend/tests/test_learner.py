"""Theta update math, idle decay, CEFR mapping, and grammar mastery/unlocking."""

from datetime import timedelta

from sqlalchemy import select

from app.models import GrammarMastery, GrammarTopic, LearnerSkill, utcnow
from app.services import learner


def test_update_skill_increases_theta_on_unexpected_success(db_session):
    theta = learner.update_skill(db_session, "grammar", score=1.0, difficulty=60.0, weight=1.0)
    assert theta > 0.0


def test_update_skill_decreases_theta_on_unexpected_failure(db_session):
    learner.set_theta(db_session, "grammar", 70.0, min_attempts=5)
    theta = learner.update_skill(db_session, "grammar", score=0.0, difficulty=30.0, weight=1.0)
    assert theta < 70.0


def test_theta_stays_within_0_100_bounds(db_session):
    for _ in range(30):
        learner.update_skill(db_session, "grammar", score=1.0, difficulty=95.0, weight=1.0)
    assert learner.get_theta(db_session, "grammar") <= 100.0

    learner.set_theta(db_session, "vocab", 5.0)
    for _ in range(30):
        learner.update_skill(db_session, "vocab", score=0.0, difficulty=5.0, weight=1.0)
    assert learner.get_theta(db_session, "vocab") >= 0.0


def test_update_magnitude_shrinks_as_attempts_accumulate(db_session):
    deltas = []
    prev = 0.0
    for _ in range(8):
        theta = learner.update_skill(db_session, "grammar", score=1.0, difficulty=50.0, weight=1.0)
        deltas.append(theta - prev)
        prev = theta
    assert deltas[-1] < deltas[0]


def test_cefr_label_boundaries():
    assert learner.cefr_label(0) == "Pre-A1"
    assert learner.cefr_label(15) == "A1.1"
    assert learner.cefr_label(25) == "A1.2"
    assert learner.cefr_label(40) == "A2.1"
    assert learner.cefr_label(50) == "A2.2"
    assert learner.cefr_label(65) == "B1.1"
    assert learner.cefr_label(80) == "B1.2"
    assert learner.cefr_label(90) == "B1.2+"


def test_week_for_theta_matches_syllabus_cefr():
    from app.services import content
    week1 = learner.week_for_theta(15)  # A1.1
    weeks = {w["week"]: w["cefr"] for w in content.syllabus()}
    assert weeks[week1] == "A1.1"


def test_no_decay_within_grace_period(db_session):
    learner.set_theta(db_session, "grammar", 50.0)
    row = db_session.get(LearnerSkill, "grammar")
    row.updated_at = utcnow() - timedelta(days=2)
    db_session.commit()
    assert learner.get_theta(db_session, "grammar") == 50.0


def test_idle_decay_reduces_theta_after_grace_period(db_session):
    learner.set_theta(db_session, "grammar", 50.0)
    row = db_session.get(LearnerSkill, "grammar")
    row.updated_at = utcnow() - timedelta(days=10)
    db_session.commit()
    theta = learner.get_theta(db_session, "grammar")
    # 10 idle days - 4 grace days = 6 decaying days * 0.3/day = 1.8
    assert abs(theta - (50.0 - 1.8)) < 0.01


def test_idle_decay_is_capped(db_session):
    learner.set_theta(db_session, "grammar", 50.0)
    row = db_session.get(LearnerSkill, "grammar")
    row.updated_at = utcnow() - timedelta(days=60)
    db_session.commit()
    theta = learner.get_theta(db_session, "grammar")
    assert abs(theta - (50.0 - 6.0)) < 0.01


def test_topic_not_mastered_with_too_few_attempts(db_session):
    topic = db_session.scalars(select(GrammarTopic)).first()
    for _ in range(3):
        learner.update_grammar_mastery(db_session, topic.id, 1.0)
    assert learner.is_topic_mastered(db_session, topic.id) is False


def test_topic_mastered_needs_high_score_and_time_span(db_session):
    topic = db_session.scalars(select(GrammarTopic)).first()
    for _ in range(6):
        learner.update_grammar_mastery(db_session, topic.id, 1.0)
    assert learner.is_topic_mastered(db_session, topic.id) is False  # span 0 days

    row = db_session.get(GrammarMastery, topic.id)
    row.first_seen = row.first_seen - timedelta(days=10)
    db_session.commit()
    assert learner.is_topic_mastered(db_session, topic.id) is True


def test_low_scores_prevent_mastery_even_with_many_attempts(db_session):
    topic = db_session.scalars(select(GrammarTopic)).first()
    for _ in range(10):
        learner.update_grammar_mastery(db_session, topic.id, 0.3)
    row = db_session.get(GrammarMastery, topic.id)
    row.first_seen = row.first_seen - timedelta(days=10)
    db_session.commit()
    assert learner.is_topic_mastered(db_session, topic.id) is False


def test_unlocked_topics_respects_prereqs(db_session):
    topics = db_session.scalars(select(GrammarTopic).order_by(GrammarTopic.sort)).all()
    has_prereqs = [t for t in topics if t.prereq_ids]
    assert has_prereqs, "expected seed data to include topics with prereqs"
    target = has_prereqs[0]

    unlocked_ids = {t.id for t in learner.unlocked_topics(db_session)}
    assert target.id not in unlocked_ids

    for pid in target.prereq_ids:
        for _ in range(6):
            learner.update_grammar_mastery(db_session, pid, 1.0)
        row = db_session.get(GrammarMastery, pid)
        row.first_seen = row.first_seen - timedelta(days=10)
    db_session.commit()

    unlocked_ids = {t.id for t in learner.unlocked_topics(db_session)}
    assert target.id in unlocked_ids


def test_topics_without_prereqs_always_unlocked(db_session):
    topics = db_session.scalars(select(GrammarTopic)).all()
    no_prereq = [t for t in topics if not t.prereq_ids]
    assert no_prereq
    unlocked_ids = {t.id for t in learner.unlocked_topics(db_session)}
    assert all(t.id in unlocked_ids for t in no_prereq)
