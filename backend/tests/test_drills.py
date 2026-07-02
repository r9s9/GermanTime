"""drills.py: LLM generation is faked (matching test_factory.py's pattern)
so these run with no server/network — G2P validation and vocab lookup run
for real since they're fast and are exactly the logic being protected.
"""

import pytest

from app.services.pron import drills


def test_phoneme_info_reads_group_label_and_tip():
    info = drills.phoneme_info("ç")
    assert info["label_de"] == "Ich- und Ach-Laut"
    assert "ich" in info["tip_de"].lower()
    assert info["tip_en"]


def test_phoneme_info_handles_a_phoneme_with_no_tip():
    # most consonants (e.g. "t") have a group but no dedicated tip text
    info = drills.phoneme_info("t")
    assert info["label_de"]
    assert info["tip_de"] is None


def test_count_target_counts_occurrences_across_words():
    assert drills._count_target("Ich mache nichts Wichtiges", "ç") == 3


def test_words_containing_finds_and_caches_vocab_matching_the_phoneme(db_session):
    from app.models import VocabItem

    words = drills._words_containing(db_session, "ç", "A2.1")
    assert isinstance(words, list)
    # whatever it found, VocabItem.ipa should now be populated for the
    # sampled rows (the lazy-cache side effect) rather than left None
    cached = db_session.query(VocabItem).filter(VocabItem.ipa.is_not(None)).count()
    assert cached > 0


@pytest.mark.asyncio
async def test_generate_retries_until_occurrence_threshold_met(db_session, monkeypatch):
    calls = []

    async def fake_generate_structured(role, system, user, model_cls, schema_name, **kwargs):
        calls.append(user)
        if len(calls) == 1:
            return drills.DrillSentence(text_de="Ja.", translation_en="Yes.")  # 0 occurrences of ç
        return drills.DrillSentence(text_de="Ich mache nichts Wichtiges.", translation_en="I do nothing important.")

    monkeypatch.setattr(drills.llm, "generate_structured", fake_generate_structured)

    result = await drills.generate(db_session, "ç", "A2.1")
    assert len(calls) == 2  # first attempt rejected, second accepted
    assert result["occurrences"] >= drills.MIN_TARGET_OCCURRENCES
    assert result["text_de"] == "Ich mache nichts Wichtiges."
    assert result["phoneme"] == "ç"


@pytest.mark.asyncio
async def test_generate_falls_back_when_llm_never_hits_the_threshold(db_session, monkeypatch):
    async def always_bad(role, system, user, model_cls, schema_name, **kwargs):
        return drills.DrillSentence(text_de="Ja.", translation_en="Yes.")

    monkeypatch.setattr(drills.llm, "generate_structured", always_bad)

    result = await drills.generate(db_session, "ç", "A2.1")
    assert result["text_de"]  # never empty, even in the worst case
    assert result["phoneme"] == "ç"
