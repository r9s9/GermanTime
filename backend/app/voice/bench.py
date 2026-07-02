"""Voice pipeline latency bench — `python -m app.voice.bench`.

Self-contained: synthesizes German test sentences with Piper, feeds them
back through faster-whisper for a WER spot-check, and benchmarks every
stage (STT, VAD, both TTS engines) with p50/p95 over repeated runs. No
external audio corpus needed.
"""

import statistics
import sys
import time

import numpy as np

from .. import config
from ..services import stt, vad
from ..services.tts import chatterbox_engine, piper_engine

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

TEST_SENTENCES = [
    "Guten Tag, wie geht es Ihnen?",
    "Ich lerne seit sechs Monaten Deutsch.",
    "Können Sie das bitte wiederholen?",
    "Das Wetter ist heute wirklich schön.",
    "Wo ist der nächste Bahnhof, bitte?",
]

N_RUNS = 8


def _resample_22050_to_16000(pcm16: bytes) -> np.ndarray:
    import soxr

    audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    return soxr.resample(audio, 22050, config.SAMPLE_RATE).astype(np.float32)


def _percentiles(values: list[float]) -> tuple[float, float]:
    s = sorted(values)
    p50 = s[len(s) // 2]
    p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
    return p50, p95


def _word_match_ratio(expected: str, got: str) -> float:
    def norm(s: str) -> set[str]:
        return {w.strip(".,!?;:").lower() for w in s.split()}

    e, g = norm(expected), norm(got)
    return len(e & g) / len(e) if e else 0.0


def bench_stt() -> None:
    print("\n=== STT (faster-whisper) — synthesize-and-transcribe spot-check ===")
    stt.warmup()
    latencies, ratios = [], []
    for sentence in TEST_SENTENCES:
        piper_out = piper_engine.synthesize(sentence)
        audio16k = _resample_22050_to_16000(piper_out.pcm16)
        result = stt.transcribe(audio16k)
        ratio = _word_match_ratio(sentence, result.text)
        latencies.append(result.latency_ms)
        ratios.append(ratio)
        flag = "ok" if ratio >= 0.6 else "LOW"
        print(f"  [{flag}] {result.latency_ms:6.1f} ms  match={ratio:.0%}  '{sentence}' -> '{result.text}'")

    p50, p95 = _percentiles(latencies)
    print(f"  latency p50={p50:.1f} ms  p95={p95:.1f} ms   avg word-match={statistics.mean(ratios):.0%}")


def bench_tts_engine(name: str, synth_fn) -> None:
    print(f"\n=== TTS: {name} ===")
    try:
        synth_fn(TEST_SENTENCES[0])
    except Exception as e:  # noqa: BLE001
        print(f"  UNAVAILABLE: {e}")
        return

    latencies = []
    for _ in range(N_RUNS):
        sentence = TEST_SENTENCES[_ % len(TEST_SENTENCES)]
        result = synth_fn(sentence)
        latencies.append(result.latency_ms)
    p50, p95 = _percentiles(latencies)
    print(f"  {N_RUNS} runs — latency p50={p50:.1f} ms  p95={p95:.1f} ms")


def bench_vad() -> None:
    print("\n=== VAD (silero) ===")
    vad.warmup()

    sentence = TEST_SENTENCES[0]
    piper_out = piper_engine.synthesize(sentence)
    speech16k = _resample_22050_to_16000(piper_out.pcm16)
    silence = np.zeros(int(config.SAMPLE_RATE * 0.5), dtype=np.float32)
    stream = np.concatenate([silence, speech16k, silence])

    window = config.VAD_WINDOW
    probs, frame_latencies = [], []
    for i in range(0, len(stream) - window, window):
        frame = stream[i:i + window]
        t0 = time.perf_counter()
        p = vad.frame_prob(frame)
        frame_latencies.append((time.perf_counter() - t0) * 1000)
        probs.append(p)

    speech_frames = [i for i, p in enumerate(probs) if p >= config.VAD_SPEECH_PROB]
    p50, p95 = _percentiles(frame_latencies)
    expected_start_frame = len(silence) // window
    expected_end_frame = (len(silence) + len(speech16k)) // window
    # VADIterator debounces onset (hysteresis against brief blips), so some lag
    # after the true acoustic boundary is expected VAD behavior, not a defect —
    # it's exactly why the real pipeline design keeps a pre-roll buffer.
    detected_ok = bool(speech_frames) and abs(speech_frames[0] - expected_start_frame) < 20

    print(f"  {len(probs)} frames ({window} samples each) — per-frame latency p50={p50:.2f} ms  p95={p95:.2f} ms")
    print(f"  expected speech ~frames {expected_start_frame}-{expected_end_frame}, "
          f"detected {speech_frames[0] if speech_frames else '-'}-{speech_frames[-1] if speech_frames else '-'} "
          f"[{'ok' if detected_ok else 'CHECK'}]")


def main() -> None:
    print(f"GermanTime voice bench — {N_RUNS} runs per TTS engine")
    bench_stt()
    bench_tts_engine("Piper (de_DE-thorsten-high)", lambda t: piper_engine.synthesize(t))
    bench_tts_engine("Chatterbox (multilingual, de)", lambda t: chatterbox_engine.synthesize(t))
    bench_vad()
    print("\nDone.")


if __name__ == "__main__":
    main()
