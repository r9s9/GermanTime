"""Central configuration: paths, ports, and every latency/behavior tunable."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # backend/app/ -> repo root
DATA_DIR = ROOT / "data"
AUDIO_DIR = DATA_DIR / "audio"
BACKUP_DIR = DATA_DIR / "backups"
TTS_CACHE_DIR = DATA_DIR / "tts_cache"
MODELS_DIR = ROOT / "models"
PIPER_DIR = MODELS_DIR / "piper"
WHISPER_DIR = MODELS_DIR / "whisper"
DB_PATH = DATA_DIR / "germantime.db"
FRONTEND_DIST = ROOT / "frontend" / "dist"
SEED_DIR = Path(__file__).resolve().parent / "data"

# Must be set before any HF-backed import downloads anything
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "hf"))

PORT = 8710
LMSTUDIO_BASE_URL = os.environ.get("GERMANTIME_LMSTUDIO", "http://localhost:1234/v1")

# ---- Voice pipeline tunables (all times in ms unless noted) ----
SAMPLE_RATE = 16000
FRAME_MS = 20                      # client PCM frame size
VAD_WINDOW = 512                   # samples per silero window (32 ms @ 16 kHz)
VAD_SPEECH_PROB = 0.5              # speech-start threshold
VAD_SILENCE_PROB = 0.35            # speech-end threshold
ENDPOINT_MS = 350                  # silence to finalize a turn
ENDPOINT_MS_SHORT_UTT = 500        # more patience if utterance < 600 ms so far
SPECULATIVE_FINAL_MS = 150         # start final STT decode this early into silence
PARTIAL_INTERVAL_MS = 480          # how often to refresh streaming partials
PREROLL_MS = 300                   # audio kept before detected speech start
MAX_UTTERANCE_S = 15
BARGE_IN_WINDOWS = 3               # consecutive speech windows to trigger barge-in
TTS_MIN_CHUNK_WORDS = 3
TTS_COMMA_SPLIT_AFTER_WORDS = 12
CONV_HISTORY_MESSAGES = 12          # rolling window of chat messages sent to the LLM

# ---- Models ----
WHISPER_MODEL = "large-v3-turbo"
WHISPER_COMPUTE = "float16"        # int8 is broken on Blackwell/sm_120
PIPER_VOICE_MAIN = "de_DE-thorsten-high"
PIPER_VOICES_EXTRA = ["de_DE-eva_k-x_low", "de_DE-kerstin-low", "de_DE-karlsson-low",
                      "de_DE-thorsten_emotional-medium"]
CHATTERBOX_ENABLED_DEFAULT = True
W2V2_PHONEME_MODEL = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"

# ---- Pronunciation (GOP) ----
FORCED_ALIGN_BACKEND = "torchaudio"  # torchaudio|viterbi — torchaudio.functional.forced_align
                                      # is deprecated (removal planned for torchaudio 2.9); "viterbi"
                                      # is the vendored pure-torch fallback in pron/aligner.py
# raw GOP (mean log P(target|frame) - log max P(*|frame)) -> 0..100 via
# 100/(1+exp(-a*(raw-b))). Fit by `python -m app.services.pron.calibrate`
# against good-vs-mismatched Piper recordings (see that module's docstring);
# gave clean utterance-level separation (good min - bad max = 59 pts).
GOP_CALIBRATION_A = 0.6407
GOP_CALIBRATION_B = -3.2099
PHONEME_EMA_ALPHA = 0.15
PHONEME_WEAK_THRESHOLD = 70.0
PHONEME_WEAK_MIN_N = 5

# ---- Planner ----
CORE_MINUTES = 20
GOAL_MONTHS = 6

_dlls_wired = False
_espeak_wired = False


def wire_dlls() -> None:
    """Expose torch's bundled cuDNN/cuBLAS DLLs to CTranslate2 (Windows).

    Must run before `import faster_whisper` / `import ctranslate2`.
    """
    global _dlls_wired
    if _dlls_wired or os.name != "nt":
        return
    torch_lib = ROOT / ".venv" / "Lib" / "site-packages" / "torch" / "lib"
    if torch_lib.exists():
        os.add_dll_directory(str(torch_lib))
    _dlls_wired = True


def wire_espeak() -> None:
    """Point phonemizer's espeak backend at the espeakng-loader wheel's
    bundled library instead of a system install (there isn't one).

    set_library() alone is not enough on Windows: the bundled DLL was
    compiled with a CI build path baked in as its default data directory
    (e.g. "D:/a/espeakng-loader/.../espeak-ng-data", which doesn't exist
    here), and phonemizer's wrapper always calls espeak_Initialize with a
    NULL path, so that bogus compiled-in default is what espeak-ng tries
    first. Found by scanning the DLL's strings for env-var names it
    references: ESPEAK_DATA_PATH overrides that default at init time.
    Must run before any phonemizer/Wav2Vec2Phoneme* import.
    """
    global _espeak_wired
    if _espeak_wired:
        return
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    os.environ["ESPEAK_DATA_PATH"] = espeakng_loader.get_data_path()
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    _espeak_wired = True


def ensure_dirs() -> None:
    for d in (DATA_DIR, AUDIO_DIR, BACKUP_DIR, TTS_CACHE_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
