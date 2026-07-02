"""Extension point for P7: async post-turn pronunciation scoring.

session.py calls this after every finalized user utterance with the raw
audio + transcript. It's a genuine no-op today (P7 doesn't exist yet) —
P7 replaces the body with a GOP-scoring queue push; the call site and
signature are already final.
"""


async def maybe_score_utterance(conv_id: str, turn_id: str, pcm16: bytes, sample_rate: int, transcript: str) -> None:
    return None
