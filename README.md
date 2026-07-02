# GermanTime

A personal, fully local German-learning app built around one goal: **Goethe B1 in 6 months**, with real conversational ability along the way.

Everything runs on your own machine — the tutor, the speech recognition, the text-to-speech, the pronunciation scoring — via [LM Studio](https://lmstudio.ai/) and a local FastAPI backend. No accounts, no cloud calls, no subscriptions. Your progress lives in one SQLite file.

## What it does

- **Adaptive daily plan** — a required ~20-minute core (spaced-repetition review, a grammar/vocab lesson, a speaking scenario) plus optional stretch blocks, re-ranked every day from what you're weak on.
- **Real-time voice conversation** — barge-in capable, sentence-chunked streaming TTS, sub-2-second turnaround. Talk to a tutor persona in 11 everyday scenarios (café, doctor, apartment viewing, ...), with the reply scaled to your level.
- **Pronunciation feedback** — every conversation turn gets scored in the background via forced alignment + Goodness-of-Pronunciation, with per-phoneme tracking and targeted drills for your weak sounds (ü, ö, ch, r, ...).
- **All four skills, text-side too** — six exercise types (multiple choice, cloze, ordering, matching, translation, dialogue-gap), LLM-generated on demand and cached ahead of time so practice never waits on a generation call.
- **Goethe mock exams** — full-format A1 (Start Deutsch 1), A2, and B1 mocks: Hören, Lesen, Schreiben, and a live Sprechen module with an examiner persona, timed and graded against the real point structure and 60% pass threshold.
- **Honest readiness projection** — a Theil-Sen slope over your actual practice pace projects a certificate-ready date, and tells you plainly if you're falling behind and what daily minutes it'd take to catch up.
- **Light gamification** — XP, levels, a daily streak (with earned freeze days), 20 milestone badges, and a weekly report with a short LLM-written summary in graded German.
- **German-first UI** — instructions and tutor speech are in simple graded German by default; hover any word for a translation, click through to English when you need it.

## Requirements

- Windows, NVIDIA GPU (developed and tuned against an RTX 5090 — Blackwell/sm_120; other CUDA GPUs should work but the pinned wheel versions target cu128).
- [LM Studio](https://lmstudio.ai/) installed, with at least one instruction-tuned chat model downloaded (a ~14B model is a good balance of speed and quality for the "fast" real-time-conversation role; a larger model works fine for the "tutor" role used for exercise/exam generation, which isn't latency-sensitive).
- Python 3.11, Node 18+, PowerShell.

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

This creates a venv, installs the pinned PyTorch/CUDA stack, Python dependencies, and (best-effort — the app degrades gracefully to Piper-only if this step fails) Chatterbox TTS; builds the frontend; downloads the speech models (Piper voices, faster-whisper, wav2vec2 phoneme model); and runs a smoke test.

Flags: `-SkipModels` (skip downloads, e.g. to re-run after a partial failure), `-SkipFrontend` (skip the npm build).

## Running it

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

Starts the LM Studio server (and preloads your chosen tutor model, if you've set one in Settings), starts the backend on port 8710, waits for it to report healthy, and opens it in an app-mode Edge window. `-NoWindow` starts the server without opening a browser window.

First launch: you'll land on a short adaptive placement test (~10-15 min) that sets your starting level per skill. After that, "Heute" (Today) is your daily plan.

## Architecture

```
backend/app/
  main.py, config.py, db.py, models.py   # FastAPI app, settings, ~35-table schema
  api/            REST endpoints + the /ws/voice WebSocket
  services/       learner model, planner, LLM client, exam engine, gamification, ...
    pron/         G2P, forced alignment, GOP scoring, pronunciation drills
    tts/          Piper (CPU, default) + Chatterbox (GPU, opt-in) engines
  voice/          the real-time conversation state machine (session.py) + WS protocol
  data/           seed content: syllabus, grammar tree, vocab lists, exam blueprints, badges
backend/tests/    pytest — service-layer tests, no server needed to run them
frontend/src/
  routes/         one file per page (Heute, Sprechen, Lernen, Prüfung, Fortschritt, Einstellungen)
  components/     shared UI (exercise players, voice UI, pronunciation caption, ...)
  lib/            typed API client, WebSocket client, mic capture (AudioWorklet), audio playback
```

**Backend**: FastAPI + SQLAlchemy/SQLite (WAL mode). All LLM calls go through LM Studio's OpenAI-compatible API with `json_schema` structured output, validated against pydantic models. Speech: faster-whisper (STT), Silero VAD (endpointing), Piper/Chatterbox (TTS), wav2vec2 + forced alignment (pronunciation scoring).

**Frontend**: Vite + React 19 + TypeScript + Tailwind 4, served as a static build by the backend — no separate dev server needed in normal use.

**Real-time voice**: the browser streams 20ms PCM16 frames over a WebSocket; the backend runs VAD endpointing, speculative STT decoding, streaming LLM generation with sentence-boundary TTS chunking, and barge-in detection, targeting well under 2 seconds from end-of-speech to first audio back.

## Development

```powershell
# backend tests
.venv\Scripts\python.exe -m pytest backend\tests -q

# frontend typecheck + build
cd frontend
npx tsc --noEmit
npm run build

# voice pipeline latency bench (no microphone needed — synthesizes its own test audio)
.venv\Scripts\python.exe -m app.voice.bench   # run from backend/, or with --app-dir

# GOP pronunciation-scoring calibration (one-time, only needed if you change the acoustic model)
.venv\Scripts\python.exe -m app.services.pron.calibrate
```

## Your data

Everything lives in `data/germantime.db` (gitignored). The backend takes an automatic backup (`data/backups/`, zipped, last 8 kept) once per day on startup, or on demand via Settings. Delete `data/` to start completely fresh — seed content (syllabus, vocab, grammar tree, exam blueprints) reloads automatically on next launch; your progress does not.

## Why local?

Speaking practice needs to happen constantly and casually — every hesitation, every accent slip is a data point. That only works if there's no per-minute cost and no round-trip to a cloud API standing between you and a natural pace of conversation. Everything here runs on hardware you already own.
