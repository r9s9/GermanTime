"""Incremental sentence-boundary detector: feed streaming LLM text deltas
in, get back complete chunks the instant they're ready to synthesize —
first sentence goes to TTS immediately, no need to wait for the full reply.
"""

import re

from .. import config

_ABBREVIATIONS = {"z.b", "d.h", "u.a", "dr", "prof", "usw", "bzw", "etc", "ca", "nr", "str", "min"}
# Requires actual trailing whitespace, NOT end-of-buffer ($): during
# incremental feed() a period at the current buffer's tail might just be an
# abbreviation ("z." before "B." arrives) or mid-sentence text whose next
# character hasn't streamed in yet. End-of-stream text is flush()'s job.
_SENTENCE_END = re.compile(r"([.!?…]+)(\s+)")


class SentenceChunker:
    def __init__(self, min_words: int = config.TTS_MIN_CHUNK_WORDS,
                 comma_split_words: int = config.TTS_COMMA_SPLIT_AFTER_WORDS):
        self.buffer = ""
        self.min_words = min_words
        self.comma_split_words = comma_split_words

    def feed(self, delta: str) -> list[str]:
        self.buffer += delta
        chunks = []
        while True:
            chunk = self._try_extract()
            if chunk is None:
                break
            chunks.append(chunk)
        return chunks

    def flush(self) -> str | None:
        text = self.buffer.strip()
        self.buffer = ""
        return text if text else None

    def _try_extract(self) -> str | None:
        for m in _SENTENCE_END.finditer(self.buffer):
            before = self.buffer[:m.start()]
            last_word = before.split()[-1].lower().rstrip(".") if before.split() else ""
            if last_word in _ABBREVIATIONS:
                continue
            candidate = self.buffer[:m.end()].strip()
            if len(candidate.split()) >= self.min_words:
                self.buffer = self.buffer[m.end():]
                return candidate

        words = self.buffer.split()
        if len(words) >= self.comma_split_words:
            comma_idx = self.buffer.find(",")
            if 0 < comma_idx < len(self.buffer) - 1:
                candidate = self.buffer[:comma_idx + 1].strip()
                if len(candidate.split()) >= self.min_words:
                    self.buffer = self.buffer[comma_idx + 1:]
                    return candidate
        return None
