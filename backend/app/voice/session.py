"""The real-time voice pipeline: one VoiceSession per WebSocket connection.

State machine: listening -> (endpoint) -> thinking -> speaking -> listening,
with speaking + sustained incoming speech -> barge_in -> listening.
"""

import asyncio
import functools
import logging
import re
import time
from collections.abc import Awaitable, Callable

import numpy as np

from . import protocol
from .chunker import SentenceChunker
from .. import config
from ..db import SessionLocal
from ..models import ConvTurn, utcnow
from ..services import concurrency, llm, pron_hook, stt, vad
from ..services.tts import chatterbox_engine, piper_engine

logger = logging.getLogger(__name__)

SendJson = Callable[[dict], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]

# CJK/Hangul — observed failure mode where a small model (qwen2.5-14b) leaks
# non-German text mid-reply despite the persona prompt forbidding it. A
# German Piper/Chatterbox voice can't render it sensibly, so this chunk gets
# skipped rather than spoken as garbled audio (see _speak_chunk).
_NON_LATIN_SCRIPT = re.compile("[぀-ヿ㐀-鿿가-힯]")


def _pcm16_bytes_to_float(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


class VoiceSession:
    def __init__(
        self, conv_id: str, send_json: SendJson, send_bytes: SendBytes,
        system_prompt: str, opening_prompt: str, level: str, tts_engine: str = "piper",
        initial_history: list[dict] | None = None, next_turn_idx: int = 0,
    ):
        self.conv_id = conv_id
        self._ws_send_json = send_json
        self._ws_send_bytes = send_bytes
        self.system_prompt = system_prompt
        self.opening_prompt = opening_prompt
        self.level = level
        self.tts_engine = tts_engine
        self._send_lock = asyncio.Lock()

        self.state = "listening"  # listening | thinking | speaking
        self._pcm_buffer = bytearray()
        self._preroll = bytearray()
        self._vad_frame_buffer = bytearray()

        self._is_speech = False
        self._speech_run = 0
        self._silence_ms = 0.0
        self._speculative_task: asyncio.Future | None = None
        self._ptt_active = False

        # rebuilt from stored ConvTurns on reconnect, so a dropped connection
        # doesn't lose conversational context — only the in-memory session did
        self._turn_idx = next_turn_idx
        self._history: list[dict] = initial_history or []
        self._active_turn_task: asyncio.Task | None = None

    # ---- outbound helpers (serialized: a single WS connection can't
    # safely interleave concurrent sends from the frame loop and a turn task) ----

    async def _send_json(self, msg: dict) -> None:
        async with self._send_lock:
            await self._ws_send_json(msg)

    async def _send_bytes(self, data: bytes) -> None:
        async with self._send_lock:
            await self._ws_send_bytes(data)

    async def push_event(self, msg: dict) -> None:
        """Public send, for out-of-band pushes to this connection (e.g.
        pron_hook's detached scoring task delivering a pron_result once
        it finishes, well after the turn that triggered it has ended)."""
        await self._send_json(msg)

    # ---- lifecycle ----

    async def start_greeting(self) -> None:
        self._active_turn_task = asyncio.create_task(self._run_turn(None, time.perf_counter()))

    async def close(self) -> None:
        if self._active_turn_task and not self._active_turn_task.done():
            self._active_turn_task.cancel()

    async def handle_control(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "ptt":
            await self._handle_ptt(bool(msg.get("on")))

    async def _handle_ptt(self, on: bool) -> None:
        self._ptt_active = on
        if on and not self._is_speech and self.state == "listening":
            await self._start_utterance()
        elif not on and self._is_speech:
            await self._finalize_utterance()

    # ---- inbound audio ----

    async def handle_frame(self, pcm16: bytes) -> None:
        self._vad_frame_buffer += pcm16
        window_bytes = config.VAD_WINDOW * 2
        while len(self._vad_frame_buffer) >= window_bytes:
            frame_bytes = bytes(self._vad_frame_buffer[:window_bytes])
            del self._vad_frame_buffer[:window_bytes]
            await self._process_vad_frame(frame_bytes)

    async def _process_vad_frame(self, frame_bytes: bytes) -> None:
        frame = _pcm16_bytes_to_float(frame_bytes)
        prob = vad.frame_prob(frame)
        frame_ms = config.VAD_WINDOW / config.SAMPLE_RATE * 1000

        if self.state in ("speaking", "thinking"):
            await self._check_interruption(prob)
            return

        if self._ptt_active:
            return  # PTT mode: utterance boundaries are explicit, not VAD-driven

        if not self._is_speech:
            self._update_preroll(frame_bytes)
            if prob >= config.VAD_SPEECH_PROB:
                self._speech_run += 1
                if self._speech_run >= 2:
                    await self._start_utterance()
            else:
                self._speech_run = 0
            return

        self._pcm_buffer += frame_bytes
        if prob < config.VAD_SILENCE_PROB:
            self._silence_ms += frame_ms
        else:
            self._silence_ms = 0.0

        utterance_s = len(self._pcm_buffer) / 2 / config.SAMPLE_RATE
        endpoint_ms = config.ENDPOINT_MS if utterance_s >= 0.6 else config.ENDPOINT_MS_SHORT_UTT

        if self._silence_ms >= config.SPECULATIVE_FINAL_MS and self._speculative_task is None:
            self._kick_off_speculative_decode()

        if self._silence_ms >= endpoint_ms:
            await self._finalize_utterance()

    def _update_preroll(self, frame_bytes: bytes) -> None:
        self._preroll += frame_bytes
        max_bytes = int(config.PREROLL_MS / 1000 * config.SAMPLE_RATE) * 2
        if len(self._preroll) > max_bytes:
            del self._preroll[:len(self._preroll) - max_bytes]

    async def _start_utterance(self) -> None:
        self._is_speech = True
        self._speech_run = 0
        self._silence_ms = 0.0
        self._pcm_buffer = bytearray(self._preroll)
        await self._send_json(protocol.vad_event("speech_start"))

    def _kick_off_speculative_decode(self) -> None:
        audio = _pcm16_bytes_to_float(bytes(self._pcm_buffer))
        loop = asyncio.get_event_loop()
        self._speculative_task = loop.run_in_executor(None, functools.partial(stt.transcribe, audio))

    async def _check_interruption(self, prob: float) -> None:
        """Sustained incoming speech while state is "speaking" or "thinking".

        These are NOT the same thing: "speaking" means the assistant is
        actively producing audio — the user really is interrupting it, so
        this is a genuine barge-in (cancel, flush the client's player, mark
        the turn interrupted). "thinking" means nothing has been said yet
        (LLM hasn't produced a first sentence) — the far more common cause
        is the user just pausing mid-utterance (very common for language
        learners speaking hesitantly), not interrupting anything. Treating
        that as a barge-in would cancel a turn that never spoke and
        needlessly flag it "interrupted" client-side. Cancel and silently
        resume listening instead — same speech, same utterance.
        """
        if prob >= config.VAD_SPEECH_PROB:
            self._speech_run += 1
            if self._speech_run >= config.BARGE_IN_WINDOWS:
                if self.state == "speaking":
                    await self._trigger_barge_in()
                else:
                    await self._cancel_turn_and_resume_listening()
        else:
            self._speech_run = 0

    async def _trigger_barge_in(self) -> None:
        await self._cancel_turn_and_resume_listening()
        await self._send_json(protocol.barge_in())

    async def _cancel_turn_and_resume_listening(self) -> None:
        if self._active_turn_task and not self._active_turn_task.done():
            self._active_turn_task.cancel()
        self.state = "listening"
        self._speech_run = 0
        self._is_speech = True  # the interrupting speech IS the start of the next utterance
        self._silence_ms = 0.0
        self._pcm_buffer = bytearray()
        self._speculative_task = None
        await self._send_json(protocol.vad_event("speech_start"))

    async def _finalize_utterance(self) -> None:
        self._is_speech = False
        pcm_bytes = bytes(self._pcm_buffer)
        self._pcm_buffer = bytearray()
        self._preroll = bytearray()
        t_endpoint = time.perf_counter()
        await self._send_json(protocol.vad_event("speech_end"))

        speculative = self._speculative_task
        self._speculative_task = None
        if speculative is not None:
            result = await speculative
        else:
            loop = asyncio.get_event_loop()
            audio = _pcm16_bytes_to_float(pcm_bytes)
            async with concurrency.gpu_lock:
                result = await loop.run_in_executor(None, functools.partial(stt.transcribe, audio))

        text = result.text.strip()
        if not text:
            self.state = "listening"
            return

        latency = {"endpoint_to_stt_ms": round((time.perf_counter() - t_endpoint) * 1000, 1)}
        self._active_turn_task = asyncio.create_task(
            self._run_turn(text, t_endpoint, user_latency=latency, user_pcm=pcm_bytes)
        )

    # ---- turn execution (LLM streaming -> sentence-chunked TTS) ----

    async def _run_turn(
        self, user_text: str | None, t_ref: float,
        user_latency: dict | None = None, user_pcm: bytes | None = None,
    ) -> None:
        self.state = "thinking"
        interrupted = False

        with SessionLocal() as db:
            if user_text is not None:
                user_turn = ConvTurn(
                    conv_id=self.conv_id, idx=self._turn_idx, role="user", text_de=user_text,
                    latency=user_latency or {},
                )
                db.add(user_turn)
                db.commit()
                db.refresh(user_turn)
                self._turn_idx += 1
                self._history.append({"role": "user", "content": user_text})
                await self._send_json(protocol.stt_final(user_text, user_turn.id))
                if user_pcm:
                    asyncio.create_task(pron_hook.maybe_score_utterance(
                        self.conv_id, user_turn.id, user_pcm, config.SAMPLE_RATE, user_text
                    ))

            assistant_turn = ConvTurn(conv_id=self.conv_id, idx=self._turn_idx, role="assistant", text_de="")
            db.add(assistant_turn)
            db.commit()
            db.refresh(assistant_turn)
            self._turn_idx += 1
            assistant_turn_id = assistant_turn.id

        chunker = SentenceChunker()
        parts: list[str] = []
        latency = dict(user_latency or {})
        first_delta_t = first_audio_t = None
        chunk_idx = 0

        messages = [{"role": "system", "content": self.system_prompt},
                    *self._history[-config.CONV_HISTORY_MESSAGES:]]
        if user_text is None:
            messages.append({"role": "user", "content": self.opening_prompt})

        try:
            async with concurrency.gpu_lock:
                async for delta in llm.stream_chat("fast", messages):
                    if first_delta_t is None:
                        first_delta_t = time.perf_counter()
                        latency["ref_to_llm_first_ms"] = round((first_delta_t - t_ref) * 1000, 1)
                    parts.append(delta)
                    await self._send_json(protocol.llm_delta(delta))
                    for chunk_text in chunker.feed(delta):
                        self.state = "speaking"  # only now — real audio is about to go out
                        await self._speak_chunk(chunk_text, assistant_turn_id, chunk_idx)
                        if first_audio_t is None:
                            first_audio_t = time.perf_counter()
                            latency["ref_to_first_audio_ms"] = round((first_audio_t - t_ref) * 1000, 1)
                        chunk_idx += 1

                tail = chunker.flush()
                if tail:
                    self.state = "speaking"
                    await self._speak_chunk(tail, assistant_turn_id, chunk_idx)
                    if first_audio_t is None:
                        first_audio_t = time.perf_counter()
                        latency["ref_to_first_audio_ms"] = round((first_audio_t - t_ref) * 1000, 1)
        except asyncio.CancelledError:
            interrupted = True
        finally:
            if interrupted and first_audio_t is None:
                # Cancelled during "thinking", before any audio was ever
                # produced — this is the silent user-kept-talking merge
                # (see _check_interruption), not a real barge-in. The client
                # never saw a single tts_begin/audio byte for this turn, so
                # publishing tts_end/turn_stats now would look like "reply
                # complete" for a reply that never happened, and appending
                # an empty assistant message would corrupt the LLM history.
                # Roll back the stub row and say nothing.
                with SessionLocal() as db:
                    row = db.get(ConvTurn, assistant_turn_id)
                    if row:
                        db.delete(row)
                        db.commit()
            else:
                assistant_text = "".join(parts)
                self._history.append({"role": "assistant", "content": assistant_text})
                latency["total_ms"] = round((time.perf_counter() - t_ref) * 1000, 1)
                with SessionLocal() as db:
                    row = db.get(ConvTurn, assistant_turn_id)
                    if row:
                        row.text_de = assistant_text
                        row.latency = latency
                        row.interrupted = interrupted
                        db.commit()

                await self._send_json(protocol.tts_end(assistant_turn_id))
                await self._send_json(protocol.turn_stats(assistant_turn_id, latency))

            # Only the most recent turn task may hand control back to
            # "listening" — an old, cancelled task's finally block can run
            # after a newer turn has already started (interruption handling
            # doesn't await this task's completion before moving on).
            if asyncio.current_task() is self._active_turn_task and self.state in ("speaking", "thinking"):
                self.state = "listening"

    async def _speak_chunk(self, text: str, turn_id: str, chunk_idx: int) -> None:
        if _NON_LATIN_SCRIPT.search(text):
            logger.warning("dropping non-German TTS chunk turn=%s: %r", turn_id, text)
            return
        loop = asyncio.get_event_loop()
        engine = chatterbox_engine if self.tts_engine == "chatterbox" else piper_engine
        result = await loop.run_in_executor(None, functools.partial(engine.synthesize, text))
        await self._send_json(protocol.tts_begin(turn_id, result.sample_rate, chunk_idx, text))
        await self._send_bytes(result.pcm16)
