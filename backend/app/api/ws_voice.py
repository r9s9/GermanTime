"""The live voice WebSocket: binary PCM frames in, JSON events + binary TTS
audio out. See voice/protocol.py for the message shapes and voice/session.py
for the state machine.
"""

import json
import logging

from sqlalchemy import select

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..db import SessionLocal
from ..models import Conversation, ConvTurn, Setting
from ..services import personas
from ..voice import protocol
from ..voice.session import VoiceSession

logger = logging.getLogger(__name__)
router = APIRouter()


def _load_conversation_context(conv_id: str):
    with SessionLocal() as db:
        conv = db.get(Conversation, conv_id)
        if conv is None:
            return None

        turns = db.scalars(
            select(ConvTurn).where(ConvTurn.conv_id == conv_id).order_by(ConvTurn.idx)
        ).all()
        history = [{"role": t.role, "content": t.text_de} for t in turns if t.text_de]
        next_idx = (turns[-1].idx + 1) if turns else 0

        scenario_id = (conv.scenario or {}).get("id", "frei")
        system_prompt = personas.build_system_prompt(db, scenario_id, conv.level)
        opening_prompt = personas.opening_line_prompt(scenario_id)

        engine_row = db.get(Setting, "voice_engine")
        tts_engine = engine_row.value if engine_row and engine_row.value else "piper"

    return {
        "level": conv.level, "history": history, "next_idx": next_idx,
        "system_prompt": system_prompt, "opening_prompt": opening_prompt, "tts_engine": tts_engine,
    }


@router.websocket("/ws/voice/{conv_id}")
async def voice_ws(websocket: WebSocket, conv_id: str) -> None:
    await websocket.accept()

    ctx = _load_conversation_context(conv_id)
    if ctx is None:
        await websocket.send_json(protocol.error("conversation not found"))
        await websocket.close()
        return

    session = VoiceSession(
        conv_id=conv_id,
        send_json=websocket.send_json,
        send_bytes=websocket.send_bytes,
        system_prompt=ctx["system_prompt"],
        opening_prompt=ctx["opening_prompt"],
        level=ctx["level"],
        tts_engine=ctx["tts_engine"],
        initial_history=ctx["history"],
        next_turn_idx=ctx["next_idx"],
    )

    await websocket.send_json(protocol.ready(conv_id))
    if not ctx["history"]:  # fresh conversation — the tutor speaks first
        await session.start_greeting()

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is not None:
                await session.handle_frame(data)
                continue
            text = message.get("text")
            if text is not None:
                try:
                    await session.handle_control(json.loads(text))
                except json.JSONDecodeError:
                    logger.warning("voice_ws: dropped malformed control message")
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("voice_ws session error (conv_id=%s)", conv_id)
    finally:
        await session.close()
