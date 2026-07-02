"""Download all local speech/scoring models into the repo's models/ directory.

Standalone on purpose (no app imports) so it can run right after pip install.
Re-runnable: everything is cached, finished downloads are skipped.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
os.environ.setdefault("HF_HOME", str(MODELS / "hf"))

PIPER_VOICES = [
    "de_DE-thorsten-high",            # main male voice (drills, exam audio, fast conversation)
    "de_DE-thorsten_emotional-medium",
    "de_DE-eva_k-x_low",              # female voice for dialogue variety
    "de_DE-kerstin-low",
    "de_DE-karlsson-low",
]


def ok(msg: str) -> None:
    print(f"[ok]   {msg}", flush=True)


def fail(msg: str, err: Exception | str) -> None:
    print(f"[FAIL] {msg}: {err}", flush=True)


def download_piper_voices() -> None:
    piper_dir = MODELS / "piper"
    piper_dir.mkdir(parents=True, exist_ok=True)
    for voice in PIPER_VOICES:
        if (piper_dir / f"{voice}.onnx").exists():
            ok(f"piper voice {voice} (cached)")
            continue
        # Run with cwd=piper_dir: download_voices writes to the current directory,
        # which keeps us independent of its flag names across piper versions.
        res = subprocess.run(
            [sys.executable, "-m", "piper.download_voices", voice],
            cwd=piper_dir,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and (piper_dir / f"{voice}.onnx").exists():
            ok(f"piper voice {voice}")
        else:
            fail(f"piper voice {voice}", (res.stderr or res.stdout).strip()[-500:])


def download_whisper() -> None:
    try:
        try:
            from faster_whisper import download_model  # type: ignore
        except ImportError:
            from faster_whisper.utils import download_model  # type: ignore
        path = download_model("large-v3-turbo", cache_dir=str(MODELS / "whisper"))
        ok(f"faster-whisper large-v3-turbo -> {path}")
    except Exception as e:  # noqa: BLE001
        fail("faster-whisper large-v3-turbo", e)


def download_wav2vec2() -> None:
    try:
        from huggingface_hub import snapshot_download

        path = snapshot_download("facebook/wav2vec2-xlsr-53-espeak-cv-ft")
        ok(f"wav2vec2-xlsr-53-espeak-cv-ft -> {path}")
    except Exception as e:  # noqa: BLE001
        fail("wav2vec2 phoneme model", e)


def download_chatterbox() -> None:
    """Prefetch Chatterbox multilingual weights via from_pretrained on CPU.

    Slow but repo-id agnostic; skipped quickly on later runs (HF cache hit).
    """
    try:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        ChatterboxMultilingualTTS.from_pretrained(device="cpu")
        ok("chatterbox multilingual weights cached")
    except Exception as e:  # noqa: BLE001
        fail("chatterbox multilingual (app will fall back to Piper)", e)


if __name__ == "__main__":
    MODELS.mkdir(exist_ok=True)
    print(f"Downloading models into {MODELS}", flush=True)
    download_piper_voices()
    download_whisper()
    download_wav2vec2()
    download_chatterbox()
    print("Done.", flush=True)
