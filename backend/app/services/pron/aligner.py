"""Forced alignment: audio + a target phone sequence -> per-phone frame
spans with the acoustic log-posteriors needed for GOP, via
facebook/wav2vec2-xlsr-53-espeak-cv-ft (same espeak phone label space as
g2p.py, so no lossy mapping between G2P output and model vocab).

torchaudio.functional.forced_align is deprecated (slated for removal in
2.9); we're pinned to 2.8 where it still works. _viterbi_align is a
vendored pure-torch fallback for when that goes away, selected via
config.FORCED_ALIGN_BACKEND.
"""

from dataclasses import dataclass

import numpy as np
import torch

from ... import config

_model = None
_processor = None


def _load():
    global _model, _processor
    if _model is None:
        config.wire_dlls()
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        _processor = Wav2Vec2Processor.from_pretrained(config.W2V2_PHONEME_MODEL)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = Wav2Vec2ForCTC.from_pretrained(config.W2V2_PHONEME_MODEL).to(device).eval()
        _model = model.half() if device == "cuda" else model
    return _model, _processor


def vocab() -> dict[str, int]:
    _, processor = _load()
    return processor.tokenizer.get_vocab()


@dataclass
class PhoneAlign:
    phone: str
    start_frame: int
    end_frame: int  # exclusive
    target_logprob: float  # mean log P(phone | frame) over the span
    max_logprob: float     # mean log max_q P(q | frame) over the span — GOP's reference term


@dataclass
class AlignResult:
    phones: list[PhoneAlign]
    frame_seconds: float  # duration of one acoustic frame, for future duration-weighted use


def _log_probs_for(audio_f32_16k: np.ndarray) -> torch.Tensor:
    model, processor = _load()
    device = next(model.parameters()).device
    inputs = processor(audio_f32_16k, sampling_rate=config.SAMPLE_RATE, return_tensors="pt")
    with torch.no_grad():
        input_values = inputs.input_values.to(device)
        if next(model.parameters()).dtype == torch.float16:
            input_values = input_values.half()
        logits = model(input_values).logits
        log_probs = torch.log_softmax(logits.float(), dim=-1)[0]  # (T, C)
    return log_probs.cpu()


def _viterbi_align(log_probs: torch.Tensor, target_ids: list[int], blank: int = 0) -> tuple[list[int], list[float]]:
    """Pure-torch/numpy CTC forced alignment: the standard blank-expanded
    DP (expand targets to [blank, t1, blank, t2, blank, ...], find the
    best monotonic path). Vectorized over alignment-lattice positions per
    timestep to keep the Python-level loop to O(T), not O(T*L).
    """
    lp = log_probs.numpy().astype(np.float64)
    t_total, _ = lp.shape
    ext = [blank]
    for tid in target_ids:
        ext.append(tid)
        ext.append(blank)
    ext = np.array(ext, dtype=np.int64)
    lane_count = len(ext)

    neg_inf = -1e9
    dp = np.full((t_total, lane_count), neg_inf)
    backptr = np.zeros((t_total, lane_count), dtype=np.int8)

    dp[0, 0] = lp[0, ext[0]]
    if lane_count > 1:
        dp[0, 1] = lp[0, ext[1]]

    can_skip = np.zeros(lane_count, dtype=bool)
    can_skip[2:] = (ext[2:] != blank) & (ext[2:] != ext[:-2])

    for t in range(1, t_total):
        stay = dp[t - 1]
        from_prev1 = np.concatenate(([neg_inf], dp[t - 1, :-1]))
        from_prev2 = np.concatenate(([neg_inf, neg_inf], dp[t - 1, :-2]))
        from_prev2 = np.where(can_skip, from_prev2, neg_inf)
        stacked = np.stack([stay, from_prev1, from_prev2], axis=0)
        best_lane = np.argmax(stacked, axis=0)
        best_val = np.take_along_axis(stacked, best_lane[None, :], axis=0)[0]
        dp[t] = best_val + lp[t, ext]
        backptr[t] = best_lane

    end_lane = lane_count - 1 if dp[-1, -1] >= dp[-1, -2] else lane_count - 2
    lane_path = np.zeros(t_total, dtype=np.int64)
    lane = end_lane
    for t in range(t_total - 1, -1, -1):
        lane_path[t] = lane
        if t > 0:
            lane = lane - backptr[t, lane]

    tokens = ext[lane_path]
    scores = lp[np.arange(t_total), tokens]
    return tokens.tolist(), scores.tolist()


def _spans_from_frames(frame_tokens: list[int], frame_scores: list[float], frame_max: list[float],
                        target_ids: list[int], phones: list[str], blank: int = 0) -> list[PhoneAlign] | None:
    """Collapse a per-frame (token, score) sequence into one span per
    target position, matching consecutive identical-id targets up
    positionally rather than by value (merge_tokens alone can't
    disambiguate "aa" as two spans since it collapses repeats).
    """
    spans: list[PhoneAlign] = []
    target_idx = 0
    frame_idx = 0
    t_total = len(frame_tokens)
    while target_idx < len(target_ids) and frame_idx < t_total:
        want = target_ids[target_idx]
        while frame_idx < t_total and frame_tokens[frame_idx] != want:
            frame_idx += 1
        if frame_idx >= t_total:
            break
        start = frame_idx
        while frame_idx < t_total and frame_tokens[frame_idx] == want:
            frame_idx += 1
        end = frame_idx
        target_lp = sum(frame_scores[start:end]) / (end - start)
        max_lp = sum(frame_max[start:end]) / (end - start)
        spans.append(PhoneAlign(phone=phones[target_idx], start_frame=start, end_frame=end,
                                 target_logprob=target_lp, max_logprob=max_lp))
        target_idx += 1
    if len(spans) != len(target_ids):
        return None
    return spans


def align(audio_f32_16k: np.ndarray, phones: list[str]) -> AlignResult | None:
    """audio: mono float32 PCM at 16 kHz. phones: flat target sequence
    (concatenated across words) from g2p.phonemize_words(). Returns None
    if alignment isn't possible (e.g. clip too short for the target, or
    an unmapped phone symbol) rather than raising — pronunciation scoring
    is a best-effort background feature, never a blocker.
    """
    if not phones or len(audio_f32_16k) < config.SAMPLE_RATE // 10:
        return None

    vocab_map = vocab()
    unk = vocab_map["<unk>"]
    target_ids = [vocab_map.get(p, unk) for p in phones]
    if unk in target_ids:
        return None

    log_probs = _log_probs_for(audio_f32_16k)
    t_total = log_probs.shape[0]
    frame_seconds = (len(audio_f32_16k) / config.SAMPLE_RATE) / t_total

    if t_total < len(target_ids) * 2 + 1:
        return None  # not enough frames for a valid CTC path

    if config.FORCED_ALIGN_BACKEND == "viterbi":
        frame_tokens, frame_scores = _viterbi_align(log_probs, target_ids)
    else:
        import torchaudio

        targets = torch.tensor([target_ids], dtype=torch.int32)
        try:
            aligned_tokens, scores = torchaudio.functional.forced_align(
                log_probs.unsqueeze(0), targets, blank=0
            )
        except RuntimeError:
            return None
        frame_tokens = aligned_tokens[0].tolist()
        frame_scores = scores[0].tolist()

    frame_max = torch.max(log_probs, dim=-1).values.tolist()
    spans = _spans_from_frames(frame_tokens, frame_scores, frame_max, target_ids, phones)
    if spans is None:
        return None
    return AlignResult(phones=spans, frame_seconds=frame_seconds)


def warmup() -> None:
    """Loading the model is cheap; torchaudio.functional.forced_align's
    first-ever call pays a ~6s one-time op-dispatch cost (measured — every
    call after the first is 10-45ms). Run a real dummy alignment here so
    that cost lands during startup, not a user's first scored utterance.
    """
    _load()
    silence = np.zeros(config.SAMPLE_RATE, dtype=np.float32)
    align(silence, ["n"])
