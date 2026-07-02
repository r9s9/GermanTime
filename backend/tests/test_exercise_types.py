"""Generation-schema split() and structurally_valid() logic — no LLM involved."""

from app.services import exercise_types as et


def test_mc_split_hides_answer():
    item = et.GeneratedMC(prompt_de="Wie heißt du?", options=["a", "b", "c", "d"], correct_index=1,
                           explanation_de="d", explanation_en="e")
    payload, answer_key = et.split("mc", item)
    assert payload["options"] == ["a", "b", "c", "d"]
    assert "correct_index" not in payload
    assert answer_key["correct_index"] == 1


def test_cloze_split_shuffles_but_keeps_all_options():
    item = et.GeneratedCloze(text_de="Ich ___ Fußball.", correct_answer="spiele",
                              distractors=["spielst", "spielt"], explanation_de="d", explanation_en="e")
    payload, answer_key = et.split("cloze", item)
    assert set(payload["choices"]) == {"spiele", "spielst", "spielt"}
    assert answer_key["correct_answer"] == "spiele"


def test_ordering_split_shuffles_but_preserves_multiset():
    item = et.GeneratedOrdering(correct_sentence="Ich spiele gern Fußball", translation_en="I like playing football")
    payload, answer_key = et.split("ordering", item)
    assert sorted(payload["tokens"]) == sorted(answer_key["correct_tokens"])
    assert answer_key["correct_tokens"] == ["Ich", "spiele", "gern", "Fußball"]


def test_matching_split():
    item = et.GeneratedMatching(prompt_de="Ordne zu", pairs=[
        et.MatchPair(left="Hund", right="dog"), et.MatchPair(left="Katze", right="cat"),
        et.MatchPair(left="Vogel", right="bird"), et.MatchPair(left="Fisch", right="fish"),
    ])
    payload, answer_key = et.split("matching", item)
    assert set(payload["left"]) == {"Hund", "Katze", "Vogel", "Fisch"}
    assert set(payload["right"]) == {"dog", "cat", "bird", "fish"}
    assert len(answer_key["pairs"]) == 4


def test_translation_split_hides_answers():
    item = et.GeneratedTranslation(direction="de_en", source_text="Ich lerne Deutsch.",
                                    accepted_answers=["I am learning German.", "I'm learning German."],
                                    hint_de="lernen = to learn")
    payload, answer_key = et.split("translation", item)
    assert "accepted_answers" not in payload
    assert len(answer_key["accepted_answers"]) == 2


def test_dialogue_gap_split_hides_gap_text():
    item = et.GeneratedDialogueGap(turns=[
        et.DialogueTurn(speaker="A", text_de="Hallo!"),
        et.DialogueTurn(speaker="B", text_de="Guten Tag!"),
        et.DialogueTurn(speaker="A", text_de="Wie geht's?"),
        et.DialogueTurn(speaker="B", text_de="Gut, danke!"),
    ], gap_turn_index=1, options=["Guten Tag!", "Tschüss!", "Nein.", "Ja."], correct_index=0)
    payload, answer_key = et.split("dialogue_gap", item)
    assert payload["turns"][1]["text_de"] is None
    assert payload["turns"][0]["text_de"] == "Hallo!"
    assert answer_key["correct_text_de"] == "Guten Tag!"


def test_structurally_valid_catches_out_of_range_index():
    item = et.GeneratedMC(prompt_de="x", options=["a", "b", "c", "d"], correct_index=9,
                           explanation_de="d", explanation_en="e")
    assert et.structurally_valid("mc", item) is False


def test_structurally_valid_catches_cloze_answer_leaking_into_distractors():
    item = et.GeneratedCloze(text_de="x ___ y", correct_answer="spiele",
                              distractors=["spiele", "spielt"], explanation_de="d", explanation_en="e")
    assert et.structurally_valid("cloze", item) is False


def test_structurally_valid_accepts_good_items():
    item = et.GeneratedMC(prompt_de="x", options=["a", "b", "c", "d"], correct_index=2,
                           explanation_de="d", explanation_en="e")
    assert et.structurally_valid("mc", item) is True


def test_structurally_valid_catches_mc_echoing_the_instruction():
    # regression test: observed live against LM Studio + Qwen3.5 — the model
    # pasted the whole generation instruction into prompt_de instead of
    # writing a learner-facing question
    item = et.GeneratedMC(
        prompt_de='Erstelle eine Multiple-Choice-Aufgabe für Niveau A1 zum Grammatikthema "X".',
        options=["a", "b", "c", "d"], correct_index=0, explanation_de="d", explanation_en="e",
    )
    assert et.structurally_valid("mc", item) is False


def test_structurally_valid_catches_dialogue_gap_echoing_the_instruction():
    # regression test: observed live — echoed instruction landed in a turn's
    # text_de, paired with a bogus speaker name instead of a short name
    item = et.GeneratedDialogueGap(
        turns=[
            et.DialogueTurn(speaker="A1_Student_Learner",
                             text_de='Erstelle einen kurzen Dialog mit 4 Sprechbeiträgen zum Grammatikthema "X".'),
            et.DialogueTurn(speaker="B", text_de="Guten Tag!"),
            et.DialogueTurn(speaker="A", text_de="Wie geht's?"),
            et.DialogueTurn(speaker="B", text_de="Gut, danke!"),
        ],
        gap_turn_index=1, options=["o1", "o2", "o3", "o4"], correct_index=0,
    )
    assert et.structurally_valid("dialogue_gap", item) is False


def test_structurally_valid_accepts_good_dialogue_gap():
    item = et.GeneratedDialogueGap(
        turns=[
            et.DialogueTurn(speaker="Anna", text_de="Hallo! Wie heißt du?"),
            et.DialogueTurn(speaker="Tom", text_de="Ich heiße Tom."),
            et.DialogueTurn(speaker="Anna", text_de="Woher kommst du?"),
            et.DialogueTurn(speaker="Tom", text_de="Aus Berlin."),
        ],
        gap_turn_index=1, options=["Ich heiße Tom.", "o2", "o3", "o4"], correct_index=0,
    )
    assert et.structurally_valid("dialogue_gap", item) is True
