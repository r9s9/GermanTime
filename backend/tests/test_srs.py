"""FSRS scheduling. review_card() takes an explicit `now`, so interval
growth is tested deterministically — no real waiting, no clock mocking."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import SrsCard, VocabItem
from app.services import errors, srs


def _first_vocab(db):
    return db.scalars(select(VocabItem)).first()


def test_create_vocab_card_is_idempotent_per_direction(db_session):
    vocab = _first_vocab(db_session)
    c1 = srs.create_vocab_card(db_session, vocab.id, "de_en")
    c2 = srs.create_vocab_card(db_session, vocab.id, "de_en")
    assert c1.id == c2.id

    c3 = srs.create_vocab_card(db_session, vocab.id, "en_de")
    assert c3.id != c1.id


def test_new_card_is_immediately_due(db_session):
    vocab = _first_vocab(db_session)
    card = srs.create_vocab_card(db_session, vocab.id)
    assert card.id in {c.id for c in srs.due_cards(db_session)}
    assert srs.due_count(db_session) >= 1


def test_review_card_advances_due_date_and_increments_reps(db_session):
    vocab = _first_vocab(db_session)
    card = srs.create_vocab_card(db_session, vocab.id)
    before_due = card.due

    reviewed = srs.review_card(db_session, card.id, rating=3)  # Good
    assert reviewed.due > before_due
    assert reviewed.reps == 1
    assert reviewed.lapses == 0


def test_again_rating_increments_lapses(db_session):
    vocab = _first_vocab(db_session)
    card = srs.create_vocab_card(db_session, vocab.id)
    reviewed = srs.review_card(db_session, card.id, rating=1)  # Again
    assert reviewed.lapses == 1


def test_review_card_raises_for_unknown_id(db_session):
    with pytest.raises(ValueError):
        srs.review_card(db_session, "nonexistent", rating=3)


def test_interval_grows_with_successive_good_reviews(db_session):
    vocab = _first_vocab(db_session)
    card = srs.create_vocab_card(db_session, vocab.id)

    now = datetime.now(timezone.utc)
    intervals = []
    for _ in range(4):
        reviewed = srs.review_card(db_session, card.id, rating=3, now=now)  # Good
        interval_s = (reviewed.due.replace(tzinfo=timezone.utc) - now).total_seconds()
        intervals.append(interval_s)
        now = reviewed.due.replace(tzinfo=timezone.utc) + timedelta(minutes=1)  # review right after it's due

    assert intervals == sorted(intervals)
    assert intervals[-1] > intervals[0]


def test_lapse_shrinks_the_next_interval(db_session):
    vocab = _first_vocab(db_session)
    card = srs.create_vocab_card(db_session, vocab.id)
    now = datetime.now(timezone.utc)

    good_interval_s = None
    for _ in range(3):  # build up a healthy interval first
        review_time = now
        reviewed = srs.review_card(db_session, card.id, rating=3, now=review_time)
        due = reviewed.due.replace(tzinfo=timezone.utc)
        good_interval_s = (due - review_time).total_seconds()
        now = due + timedelta(minutes=1)  # review right after it's due

    lapsed = srs.review_card(db_session, card.id, rating=1, now=now)  # forgot it
    lapse_interval_s = (lapsed.due.replace(tzinfo=timezone.utc) - now).total_seconds()
    assert lapse_interval_s < good_interval_s


def test_card_content_vocab_de_en_and_en_de(db_session):
    vocab = db_session.scalars(select(VocabItem).where(VocabItem.article.is_not(None))).first()

    card_de_en = srs.create_vocab_card(db_session, vocab.id, "de_en")
    content = srs.card_content(db_session, card_de_en)
    assert vocab.lemma in content["front"]
    assert content["back"] == vocab.en_gloss
    assert content["front_is_de"] is True and content["back_is_de"] is False

    card_en_de = srs.create_vocab_card(db_session, vocab.id, "en_de")
    content2 = srs.card_content(db_session, card_en_de)
    assert content2["front"] == vocab.en_gloss
    assert vocab.lemma in content2["back"]
    assert content2["front_is_de"] is False and content2["back_is_de"] is True


def test_card_content_error_card(db_session):
    note = errors.create_error_note(db_session, "grammar", "exercise", "Ich bin gut.", "Ich bin gute.",
                                     note_de="Adjektivendung fehlt")
    card = db_session.get(SrsCard, note.card_id)
    content = srs.card_content(db_session, card)
    assert content["front"] == "Ich bin gut."
    assert content["back"] == "Ich bin gute."
    assert content["note_de"] == "Adjektivendung fehlt"
