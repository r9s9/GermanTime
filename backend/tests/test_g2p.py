"""g2p.py: real espeak calls (fast, no GPU/model loading needed)."""

from app.services.pron import g2p


def test_words_in_strips_punctuation_and_digits():
    assert g2p.words_in("Ich habe 3 Äpfel, oder?") == ["Ich", "habe", "Äpfel", "oder"]


def test_words_in_empty_text():
    assert g2p.words_in("") == []
    assert g2p.words_in("... !? 123") == []


def test_phonemize_words_matches_known_german_pronunciation():
    phones = g2p.phonemize_words(["ich", "Deutsch"])
    assert phones[0] == ["ɪ", "ç"]
    assert phones[1] == ["d", "ɔø", "t", "ʃ"]


def test_phonemize_words_diphthong_is_one_atomic_token():
    # German eu/äu ("neu") must come back as a single multi-codepoint
    # token ("ɔø"), not two separate phones — this is what makes it line
    # up with the acoustic model's vocab (see aligner.py's docstring).
    phones = g2p.phonemize_words(["neu"])
    assert phones[0] == ["n", "ɔø"]


def test_phonemize_words_empty_list():
    assert g2p.phonemize_words([]) == []


def test_phonemize_words_preserves_input_order():
    phones = g2p.phonemize_words(["ja", "nein"])
    assert phones[0] == ["j", "ɑː"]
    assert phones[1][0] in ("n",)  # "nein" starts with n regardless of diphthong transcription details
