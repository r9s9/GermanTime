"""One-time GOP sigmoid calibration — `python -m app.services.pron.calibrate`.

There's no real "mispronounced German" corpus available offline, so this
uses a cheap but effective proxy: synthesize clean reference audio for N
sentences with Piper ("good" examples — the audio genuinely matches its
own text), then re-score each clip against a *different* sentence's phone
sequence ("bad" examples — a stand-in for mispronunciation, since the
acoustics now genuinely don't match the target phones). Per-phone raw GOP
values are pooled from both groups and a sigmoid is moment-matched to
separate them: b = midpoint of the two cluster means, a = 4 / gap, so a
raw score one quarter-gap above/below the midpoint lands near the
80/20 points. Prints the fitted constants to paste into config.py.
"""

import sys

import numpy as np

from ... import config
from ...services.tts import piper_engine
from . import aligner, g2p, gop

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

SENTENCES = [
    "Ich lerne seit sechs Monaten Deutsch.",
    "Wo ist der nächste Bahnhof, bitte?",
    "Können Sie das bitte wiederholen?",
    "Das Wetter ist heute wirklich schön.",
    "Ich möchte gerne einen Kaffee bestellen.",
    "Wie viel kostet dieses Buch?",
    "Mein Bruder wohnt in Berlin.",
    "Wir treffen uns morgen um neun Uhr.",
    "Entschuldigung, ich habe das nicht verstanden.",
    "Die Küche ist sehr groß und hell.",
]


def _clip_16k(text: str) -> np.ndarray:
    import soxr

    result = piper_engine.synthesize(text)
    audio = np.frombuffer(result.pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    return soxr.resample(audio, result.sample_rate, config.SAMPLE_RATE).astype(np.float32)


def _raw_gop_values(audio: np.ndarray, text: str) -> list[float]:
    words = g2p.words_in(text)
    phone_lists = g2p.phonemize_words(words)
    flat_phones = [p for pl in phone_lists for p in pl]
    result = aligner.align(audio, flat_phones)
    if result is None:
        return []
    return [s.target_logprob - s.max_logprob for s in result.phones]


def main() -> None:
    clips = [(s, _clip_16k(s)) for s in SENTENCES]

    good, bad = [], []
    for i, (text, audio) in enumerate(clips):
        good.extend(_raw_gop_values(audio, text))
        mismatch_text = clips[(i + 1) % len(clips)][0]
        bad.extend(_raw_gop_values(audio, mismatch_text))

    if not good or not bad:
        print(f"insufficient data: good={len(good)} bad={len(bad)} — check espeak/model wiring")
        return

    good_arr, bad_arr = np.array(good), np.array(bad)
    mean_good, mean_bad = float(good_arr.mean()), float(bad_arr.mean())
    print(f"good: n={len(good)} mean={mean_good:.3f} std={good_arr.std():.3f} "
          f"p10={np.percentile(good_arr, 10):.3f} p90={np.percentile(good_arr, 90):.3f}")
    print(f"bad:  n={len(bad)} mean={mean_bad:.3f} std={bad_arr.std():.3f} "
          f"p10={np.percentile(bad_arr, 10):.3f} p90={np.percentile(bad_arr, 90):.3f}")

    if mean_good <= mean_bad:
        print("WARNING: good/bad clusters did not separate as expected — calibration unreliable")
        return

    b = (mean_good + mean_bad) / 2
    a = 4.0 / (mean_good - mean_bad)
    print(f"\nfitted: GOP_CALIBRATION_A = {a:.4f}   GOP_CALIBRATION_B = {b:.4f}")

    good_scores = [gop.calibrate(v, a, b) for v in good]
    bad_scores = [gop.calibrate(v, a, b) for v in bad]
    print(f"good calibrated: mean={np.mean(good_scores):.1f} p10={np.percentile(good_scores, 10):.1f}")
    print(f"bad calibrated:  mean={np.mean(bad_scores):.1f} p90={np.percentile(bad_scores, 90):.1f}")
    print(f"separation (good p10 - bad p90): {np.percentile(good_scores, 10) - np.percentile(bad_scores, 90):.1f} pts")


if __name__ == "__main__":
    main()
