"""aligner.py's DP logic, tested against hand-crafted log-prob tensors —
no model loading needed, so this stays fast. The vendored Viterbi fallback
was verified byte-for-byte identical to torchaudio.functional.forced_align
on real model output during development (same well-defined DP, different
implementations); these tests protect the DP itself from regressing.
"""

import torch

from app.services.pron.aligner import _spans_from_frames, _viterbi_align


def test_viterbi_align_finds_the_obviously_correct_path():
    # 5 frames, 3 classes (blank=0, A=1, B=2), each frame strongly peaked
    # so there's one unambiguous optimal alignment for target [A, B].
    log_probs = torch.log(torch.tensor([
        [0.9, 0.05, 0.05],   # blank
        [0.05, 0.9, 0.05],   # A
        [0.05, 0.9, 0.05],   # A (repeat)
        [0.9, 0.05, 0.05],   # blank
        [0.05, 0.05, 0.9],   # B
    ]))
    tokens, scores = _viterbi_align(log_probs, [1, 2], blank=0)
    assert tokens == [0, 1, 1, 0, 2]
    assert len(scores) == 5


def test_viterbi_align_inserts_blank_between_identical_adjacent_targets():
    # Target [A, A] — CTC requires a blank between two adjacent identical
    # symbols, or they'd collapse into one when decoded. 4 frames force it.
    log_probs = torch.log(torch.tensor([
        [0.05, 0.9, 0.05],
        [0.9, 0.05, 0.05],
        [0.05, 0.9, 0.05],
        [0.9, 0.05, 0.05],
    ]))
    tokens, _ = _viterbi_align(log_probs, [1, 1], blank=0)
    # two separate runs of "1", with at least one blank between them
    assert tokens[0] == 1
    first_run_end = tokens.index(0, 1) if 0 in tokens[1:] else None
    assert first_run_end is not None
    assert 1 in tokens[first_run_end:]


def test_spans_from_frames_matches_positions_not_just_values():
    # target [5, 5] (identical ids) — must produce TWO spans, matched by
    # position, not merged just because the token value repeats.
    frame_tokens = [5, 5, 0, 5]
    frame_scores = [-0.1, -0.1, -2.0, -0.2]
    frame_max = [-0.05, -0.05, -0.1, -0.05]
    spans = _spans_from_frames(frame_tokens, frame_scores, frame_max,
                                target_ids=[5, 5], phones=["x", "x"])
    assert spans is not None
    assert len(spans) == 2
    assert spans[0].start_frame == 0 and spans[0].end_frame == 2
    assert spans[1].start_frame == 3 and spans[1].end_frame == 4


def test_spans_from_frames_returns_none_when_a_target_is_never_reached():
    frame_tokens = [1, 1, 0]
    frame_scores = [-0.1, -0.1, -1.0]
    frame_max = [-0.05, -0.05, -0.1]
    spans = _spans_from_frames(frame_tokens, frame_scores, frame_max,
                                target_ids=[1, 2], phones=["a", "b"])
    assert spans is None
