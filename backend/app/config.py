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

# ---- Planner ----
CORE_MINUTES = 20
GOAL_MONTHS = 6

_dlls_wired = False


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


def ensure_dirs() -> None:
    for d in (DATA_DIR, AUDIO_DIR, BACKUP_DIR, TTS_CACHE_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
