"""WS text-frame message shapes. Binary frames (mic input, TTS audio
output) travel outside this module — these are the `{t: ...}` JSON
messages sent/expected on the same connection.
"""


def vad_event(state: str) -> dict:
    return {"t": "vad", "state": state}  # "speech_start" | "speech_end"


def stt_partial(text: str) -> dict:
    return {"t": "stt_partial", "text": text}


def stt_final(text: str, turn_id: str) -> dict:
    return {"t": "stt_final", "text": text, "turn_id": turn_id}


def llm_delta(text: str) -> dict:
    return {"t": "llm_delta", "text": text}


def tts_begin(turn_id: str, sample_rate: int, chunk_idx: int, text: str) -> dict:
    return {"t": "tts_begin", "turn_id": turn_id, "sr": sample_rate, "chunk": chunk_idx, "text": text}


def tts_end(turn_id: str) -> dict:
    return {"t": "tts_end", "turn_id": turn_id}


def barge_in() -> dict:
    return {"t": "barge_in"}


def turn_stats(turn_id: str, latency: dict) -> dict:
    return {"t": "turn_stats", "turn_id": turn_id, "latency": latency}


def pron_result(turn_id: str, words: list) -> dict:
    return {"t": "pron_result", "turn_id": turn_id, "words": words}


def error(message: str) -> dict:
    return {"t": "error", "message": message}


def ready(conv_id: str) -> dict:
    return {"t": "ready", "conv_id": conv_id}
