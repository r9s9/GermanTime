"""P1 verification: schema creates cleanly and seed content loads with sane counts."""

from sqlalchemy import select

from app.models import Badge, GrammarTopic, VocabItem
from app.services import content


def test_grammar_topics_seeded(db_session):
    topics = db_session.scalars(select(GrammarTopic)).all()
    assert 55 <= len(topics) <= 70, f"expected ~60 grammar topics, got {len(topics)}"
    levels = {t.level for t in topics}
    assert levels == {"A1", "A2", "B1"}
    # every prereq must point at a real topic (no dangling edges)
    ids = {t.id for t in topics}
    for t in topics:
        for p in t.prereq_ids:
            assert p in ids, f"{t.id} has dangling prereq {p}"


def test_vocab_seeded_and_tagged(db_session):
    items = db_session.scalars(select(VocabItem)).all()
    assert len(items) >= 600, f"expected substantial vocab seed, got {len(items)}"
    by_level = {}
    for v in items:
        by_level.setdefault(v.level, 0)
        by_level[v.level] += 1
    assert by_level.get("A1", 0) >= 200
    assert by_level.get("A2", 0) >= 150
    assert by_level.get("B1", 0) >= 150
    # common nouns should carry an article; country/language names legitimately don't
    # (e.g. "Deutschland", "Englisch" are used bare in German)
    nouns = [v for v in items if v.pos == "noun" and "laender" not in v.tags]
    missing_article = [v.lemma for v in nouns if not v.article]
    assert not missing_article, f"nouns missing article: {missing_article[:10]}"
    # every item has at least one tag and a gloss
    assert all(v.tags for v in items)
    assert all(v.en_gloss for v in items)


def test_vocab_no_duplicate_lemma_pos(db_session):
    items = db_session.scalars(select(VocabItem)).all()
    keys = [(v.lemma, v.pos) for v in items]
    assert len(keys) == len(set(keys)), "duplicate (lemma, pos) rows found"


def test_badges_seeded(db_session):
    badges = db_session.scalars(select(Badge)).all()
    assert len(badges) >= 15
    assert all(b.criteria for b in badges)


def test_seeds_are_idempotent(db_session):
    from app.services.seeds import load_seeds

    before = {
        "grammar_topics": db_session.execute(select(GrammarTopic)).all(),
        "vocab_items": db_session.execute(select(VocabItem)).all(),
    }
    load_seeds()
    load_seeds()
    db_session.expire_all()
    after_grammar = db_session.scalars(select(GrammarTopic)).all()
    after_vocab = db_session.scalars(select(VocabItem)).all()
    assert len(after_grammar) == len(before["grammar_topics"])
    assert len(after_vocab) == len(before["vocab_items"])


def test_syllabus_covers_24_weeks():
    weeks = content.syllabus()
    assert [w["week"] for w in weeks] == list(range(1, 25))
    for w in weeks:
        assert w["cando"], f"week {w['week']} has no can-do statements"
        assert w["grammar"], f"week {w['week']} has no grammar refs"


def test_syllabus_grammar_refs_exist_in_tree(db_session):
    grammar_ids = {t.id for t in db_session.scalars(select(GrammarTopic)).all()}
    for w in content.syllabus():
        for gid in w["grammar"]:
            assert gid in grammar_ids, f"week {w['week']} references unknown topic {gid}"


def test_exam_blueprints_load():
    bps = content.exam_blueprints()
    assert set(bps) == {"a1", "a2", "b1"}
    for level, bp in bps.items():
        assert set(bp["modules"]) == {"lesen", "hoeren", "schreiben", "sprechen"}
        assert bp["pass_pct"] == 60


def test_phoneme_map_and_ui_strings_load():
    pm = content.phoneme_map()
    assert len(pm["groups"]) >= 5
    ui = content.ui_strings()
    assert "nav.today" in ui and ui["nav.today"]["de"]
