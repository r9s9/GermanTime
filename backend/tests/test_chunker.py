"""SentenceChunker: incremental sentence-boundary detection for streaming
LLM text -> TTS chunks. Pure logic, no model/network involved."""

from app.voice.chunker import SentenceChunker


def _feed_all(chunker: SentenceChunker, text: str) -> list[str]:
    """Feeds character-by-character (like real streaming deltas) then
    flushes, matching how session.py actually drives this class: a real
    LLM stream just ends after its last token, with no guaranteed trailing
    whitespace, so the final sentence is always flush()'s job, not feed()'s.
    """
    out = []
    for ch in text:
        out.extend(chunker.feed(ch))
    tail = chunker.flush()
    if tail:
        out.append(tail)
    return out


def test_single_complete_sentence_emitted_once_punctuation_arrives():
    c = SentenceChunker()
    chunks = _feed_all(c, "Hallo, wie geht es dir?")
    assert chunks == ["Hallo, wie geht es dir?"]


def test_multiple_sentences_emitted_incrementally():
    c = SentenceChunker()
    chunks = _feed_all(c, "Ich bin müde! Wie geht es dir? Mir geht es gut.")
    assert chunks == ["Ich bin müde!", "Wie geht es dir?", "Mir geht es gut."]


def test_short_sentence_merges_forward_until_min_words_met():
    # "Hallo!" alone is only 1 word — held back and merged with what follows,
    # so it isn't spoken as an isolated, jarringly short utterance
    c = SentenceChunker()
    chunks = _feed_all(c, "Hallo! Wie geht es dir?")
    assert chunks == ["Hallo! Wie geht es dir?"]


def test_too_short_a_fragment_is_not_emitted_as_its_own_chunk():
    c = SentenceChunker(min_words=3)
    chunks = _feed_all(c, "Ja. Das ist ein Test.")
    # "Ja." alone is only 1 word — held back and merged into the next chunk
    assert chunks == ["Ja. Das ist ein Test."]


def test_abbreviations_do_not_trigger_a_false_sentence_boundary():
    c = SentenceChunker()
    chunks = _feed_all(c, "Das ist z.B. sehr gut. Und das auch.")
    assert chunks == ["Das ist z.B. sehr gut.", "Und das auch."]


def test_dr_abbreviation_does_not_split():
    c = SentenceChunker()
    chunks = _feed_all(c, "Dr. Müller ist mein Arzt.")
    assert chunks == ["Dr. Müller ist mein Arzt."]


def test_long_clause_soft_splits_on_comma_past_word_limit():
    c = SentenceChunker(comma_split_words=8)
    text = "Ich gehe heute Nachmittag in die Stadt, weil ich neue Schuhe kaufen möchte."
    chunks = _feed_all(c, text)
    assert len(chunks) >= 2
    assert chunks[0].endswith(",")


def test_flush_returns_remaining_partial_text():
    c = SentenceChunker()
    c.feed("Das ist unvollständig")
    assert c.flush() == "Das ist unvollständig"


def test_flush_returns_none_when_buffer_truly_empty():
    c = SentenceChunker()
    _feed_all(c, "Das ist ein vollständiger Satz. ")  # trailing space -> fully extracted by feed()
    assert c.flush() is None


def test_flush_returns_trailing_text_with_no_terminal_punctuation():
    c = SentenceChunker()
    for ch in "Fertig.":  # no trailing whitespace ever arrives — feed() can't confirm the boundary
        c.feed(ch)
    assert c.flush() == "Fertig."


def test_feed_can_be_called_with_multi_character_deltas():
    c = SentenceChunker()
    chunks = c.feed("Hallo Welt")
    chunks += c.feed(", wie geht's")
    chunks += c.feed("? Gut, danke.")
    tail = c.flush()  # "Gut, danke." (2 words) never gets a confirming trailing space — flush()'s job
    if tail:
        chunks.append(tail)
    assert chunks == ["Hallo Welt, wie geht's?", "Gut, danke."]


def test_ellipsis_counts_as_sentence_end():
    c = SentenceChunker()
    chunks = _feed_all(c, "Warte doch mal… Ich überlege noch.")
    assert chunks[0] == "Warte doch mal…"
