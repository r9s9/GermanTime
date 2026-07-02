"""German grapheme-to-phoneme via espeak, one word at a time so scoring can
track per-word/per-phone spans. Requires config.wire_espeak() to have run
first (Windows-only DLL data-path fix; see that function's docstring).
"""

import re

from ... import config

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def words_in(text: str) -> list[str]:
    """Extracts plain words from text, dropping punctuation/digits/whitespace."""
    return _WORD_RE.findall(text)


def phonemize_words(words: list[str], lang: str = "de") -> list[list[str]]:
    """Returns one espeak-IPA phone-symbol list per input word, in order.

    Symbols match facebook/wav2vec2-xlsr-53-espeak-cv-ft's vocabulary
    directly (verified: German diphthongs/long vowels like "aɪ", "oː",
    "ɔø" are already atomic tokens in both espeak's phone-separated output
    and the model vocab — no extra mapping table needed).
    """
    if not words:
        return []
    config.wire_espeak()
    from phonemizer import phonemize
    from phonemizer.separator import Separator

    sep = Separator(phone=" ", word="|", syllable="")
    out = phonemize(words, language=lang, backend="espeak", separator=sep, strip=True, with_stress=False)
    return [o.split() for o in out]
