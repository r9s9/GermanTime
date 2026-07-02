"""Post-install smoke test: verifies the GPU stack, both TTS engines, G2P and STT.

Exit code 0 = all hard requirements pass (warnings allowed for optional parts).
"""

import os
import sys
import traceback
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
os.environ.setdefault("HF_HOME", str(MODELS / "hf"))

HARD_FAILURES: list[str] = []
WARNINGS: list[str] = []


def check(name: str, hard: bool = True):
    def deco(fn):
        def run():
            try:
                detail = fn()
                print(f"[ok]   {name}" + (f" — {detail}" if detail else ""), flush=True)
            except Exception as e:  # noqa: BLE001
                (HARD_FAILURES if hard else WARNINGS).append(f"{name}: {e}")
                tag = "FAIL" if hard else "warn"
                print(f"[{tag}] {name}: {e}", flush=True)
                traceback.print_exc()
        return run
    return deco


@check("torch CUDA + Blackwell (sm_120)")
def torch_cuda():
    import torch

    assert torch.cuda.is_available(), "CUDA not available"
    arch = torch.cuda.get_arch_list()
    assert "sm_120" in arch, f"sm_120 missing from arch list {arch} — wrong torch build?"
    return f"{torch.cuda.get_device_name(0)}, torch {torch.__version__}"


@check("faster-whisper loads + decodes on GPU")
def whisper_decode():
    import torch  # noqa: F401  (ensures torch DLLs importable first)

    torch_lib = ROOT / ".venv" / "Lib" / "site-packages" / "torch" / "lib"
    if torch_lib.exists():
        os.add_dll_directory(str(torch_lib))  # cuDNN/cuBLAS for CTranslate2

    import numpy as np
    from faster_whisper import WhisperModel

    model = WhisperModel(
        "large-v3-turbo",
        device="cuda",
        compute_type="float16",  # int8 is broken on sm_120
        download_root=str(MODELS / "whisper"),
    )
    audio = np.zeros(16000, dtype=np.float32)  # 1 s silence — exercises the full CUDA path
    segments, info = model.transcribe(audio, language="de", beam_size=1)
    list(segments)
    del model
    return "decoded 1s of audio"


@check("Piper German voice synthesizes")
def piper_synth():
    from piper import PiperVoice

    voice_path = MODELS / "piper" / "de_DE-thorsten-high.onnx"
    assert voice_path.exists(), f"voice not downloaded: {voice_path}"
    voice = PiperVoice.load(str(voice_path))
    chunks = list(voice.synthesize("Guten Tag! Willkommen bei GermanTime."))
    total = sum(len(c.audio_int16_bytes) for c in chunks)
    assert total > 10000, "suspiciously little audio"
    return f"{total} bytes of PCM"


@check("espeak-ng G2P (phonemizer + espeakng-loader)")
def g2p():
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    # espeak-ng resolves its data dir as $ESPEAK_DATA_PATH/espeak-ng-data,
    # so the env var must point at the PARENT of the bundled data directory.
    data = Path(espeakng_loader.get_data_path())
    os.environ["ESPEAK_DATA_PATH"] = str(data.parent)
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    if hasattr(EspeakWrapper, "set_data_path"):
        EspeakWrapper.set_data_path(str(data))
    from phonemizer import phonemize

    ipa = phonemize("schön über müde", language="de", backend="espeak", strip=True)
    assert "ø" in ipa or "y" in ipa, f"unexpected IPA: {ipa}"
    return ipa


@check("silero-vad loads", hard=True)
def vad():
    from silero_vad import load_silero_vad

    load_silero_vad()
    return "ok"


@check("fsrs v6 API", hard=True)
def fsrs_api():
    from fsrs import Card, Rating, Scheduler

    s = Scheduler()
    card, log = s.review_card(Card(), Rating.Good)
    assert card.due is not None
    return "ok"


@check("Chatterbox multilingual import + German synth (optional)", hard=False)
def chatterbox():
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    model = ChatterboxMultilingualTTS.from_pretrained(
        device="cuda" if torch.cuda.is_available() else "cpu"
    )
    wav = model.generate("Hallo, ich bin dein Deutschlehrer.", language_id="de")
    assert wav.numel() > 1000
    del model
    torch.cuda.empty_cache()
    return f"{wav.numel()} samples"


@check("wav2vec2 phoneme model loads (optional)", hard=False)
def wav2vec2():
    from transformers import AutoModelForCTC, AutoProcessor

    AutoProcessor.from_pretrained("facebook/wav2vec2-xlsr-53-espeak-cv-ft")
    AutoModelForCTC.from_pretrained("facebook/wav2vec2-xlsr-53-espeak-cv-ft")
    return "ok"


@check("LM Studio server reachable (optional)", hard=False)
def lmstudio():
    import httpx

    r = httpx.get("http://localhost:1234/v1/models", timeout=5)
    ids = [m["id"] for m in r.json().get("data", [])]
    return f"{len(ids)} models: {', '.join(ids[:4])}..."


if __name__ == "__main__":
    for fn in [torch_cuda, whisper_decode, piper_synth, g2p, vad, fsrs_api,
               chatterbox, wav2vec2, lmstudio]:
        fn()

    print(flush=True)
    if WARNINGS:
        print(f"{len(WARNINGS)} warning(s): " + "; ".join(WARNINGS), flush=True)
    if HARD_FAILURES:
        print(f"{len(HARD_FAILURES)} HARD FAILURE(S): " + "; ".join(HARD_FAILURES), flush=True)
        sys.exit(1)
    print("Smoke test PASSED.", flush=True)
