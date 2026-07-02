"""SQLAlchemy ORM — the complete GermanTime schema."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from .db import Base


def new_id() -> str:
    return str(ULID())


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC everywhere


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class ModelRole(Base):
    __tablename__ = "model_roles"
    role: Mapped[str] = mapped_column(String, primary_key=True)  # tutor|fast|embed
    model_id: Mapped[str] = mapped_column(String)
    params: Mapped[dict] = mapped_column(JSON, default=dict)


class LearnerSkill(Base):
    __tablename__ = "learner_skills"
    # listening|reading|writing|speaking|grammar|vocab|pronunciation
    skill: Mapped[str] = mapped_column(String, primary_key=True)
    theta: Mapped[float] = mapped_column(Float, default=0.0)
    n_attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    history: Mapped[list] = mapped_column(JSON, default=list)  # [{d: iso, theta}] daily snapshots


class GrammarTopic(Base):
    __tablename__ = "grammar_topics"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "a1.praesens"
    level: Mapped[str] = mapped_column(String)  # A1|A2|B1
    syllabus_week: Mapped[int] = mapped_column(Integer)
    title_de: Mapped[str] = mapped_column(String)
    title_en: Mapped[str] = mapped_column(String)
    prereq_ids: Mapped[list] = mapped_column(JSON, default=list)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class GrammarMastery(Base):
    __tablename__ = "grammar_mastery"
    topic_id: Mapped[str] = mapped_column(ForeignKey("grammar_topics.id"), primary_key=True)
    m: Mapped[float] = mapped_column(Float, default=0.0)
    n: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime | None] = mapped_column(default=None)
    last_seen: Mapped[datetime | None] = mapped_column(default=None)


class VocabItem(Base):
    __tablename__ = "vocab_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lemma: Mapped[str] = mapped_column(String, index=True)
    article: Mapped[str | None] = mapped_column(String, default=None)  # der|die|das for nouns
    plural: Mapped[str | None] = mapped_column(String, default=None)  # full plural form for nouns
    pos: Mapped[str] = mapped_column(String)  # noun|verb|adj|adv|prep|conj|pron|num|phrase|other
    level: Mapped[str] = mapped_column(String, index=True)  # A1|A2|B1
    freq_rank: Mapped[int] = mapped_column(Integer, default=0)
    en_gloss: Mapped[str] = mapped_column(String)
    example_de: Mapped[str | None] = mapped_column(Text, default=None)  # filled by content factory
    ipa: Mapped[str | None] = mapped_column(String, default=None)  # filled lazily via G2P
    tags: Mapped[list] = mapped_column(JSON, default=list)


class SrsCard(Base):
    __tablename__ = "srs_cards"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String)  # vocab|error
    ref_id: Mapped[str] = mapped_column(String, index=True)  # vocab_items.id or error_notebook.id
    direction: Mapped[str] = mapped_column(String, default="de_en")  # de_en|en_de|listen
    fsrs: Mapped[dict] = mapped_column(JSON, default=dict)  # fsrs.Card.to_dict()
    due: Mapped[datetime] = mapped_column(default=utcnow, index=True)  # mirror for fast queries
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ReviewLog(Base):
    __tablename__ = "review_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("srs_cards.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1..4
    reviewed_at: Mapped[datetime] = mapped_column(default=utcnow)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    fsrs_log: Mapped[dict] = mapped_column(JSON, default=dict)


class ErrorNote(Base):
    __tablename__ = "error_notebook"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String)  # grammar|vocab|pron
    topic_id: Mapped[str | None] = mapped_column(String, default=None)
    source: Mapped[str] = mapped_column(String)  # conversation|exercise|exam|writing
    wrong_de: Mapped[str] = mapped_column(Text)
    right_de: Mapped[str] = mapped_column(Text)
    note_de: Mapped[str] = mapped_column(Text, default="")
    note_en: Mapped[str] = mapped_column(Text, default="")
    card_id: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PlanDay(Base):
    __tablename__ = "plan_days"
    date: Mapped[str] = mapped_column(String, primary_key=True)  # YYYY-MM-DD
    syllabus_week: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="open")  # open|done
    core_done: Mapped[bool] = mapped_column(Boolean, default=False)
    minutes_done: Mapped[float] = mapped_column(Float, default=0.0)
    rebuilt_at: Mapped[datetime] = mapped_column(default=utcnow)


class PlanBlock(Base):
    __tablename__ = "plan_blocks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    date: Mapped[str] = mapped_column(ForeignKey("plan_days.date"), index=True)
    slot: Mapped[str] = mapped_column(String)  # required|stretch
    # srs|lesson|speaking|listening|reading|writing|pron_drill|exam_part|mock|report
    type: Mapped[str] = mapped_column(String)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="open")  # open|active|done|skipped
    minutes_est: Mapped[float] = mapped_column(Float, default=10.0)
    minutes_actual: Mapped[float] = mapped_column(Float, default=0.0)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Exercise(Base):
    __tablename__ = "exercises"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    # mc|cloze|ordering|matching|translation|dialogue_gap|listening|reading|writing_prompt|drill
    type: Mapped[str] = mapped_column(String, index=True)
    level: Mapped[str] = mapped_column(String, index=True)  # CEFR sublevel e.g. "A1.2"
    topic_id: Mapped[str | None] = mapped_column(String, default=None, index=True)
    vocab_ids: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    answer_key: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String, default="factory")
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    used_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ExerciseAttempt(Base):
    __tablename__ = "exercise_attempts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id"), index=True)
    block_id: Mapped[str | None] = mapped_column(String, default=None)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    graded_by: Mapped[str] = mapped_column(String, default="auto")  # auto|llm
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    scenario: Mapped[dict] = mapped_column(JSON, default=dict)
    persona: Mapped[str] = mapped_column(String, default="tutor")
    level: Mapped[str] = mapped_column(String, default="A1.1")
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    minutes: Mapped[float] = mapped_column(Float, default=0.0)
    summary_de: Mapped[str] = mapped_column(Text, default="")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)


class ConvTurn(Base):
    __tablename__ = "conv_turns"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    conv_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String)  # user|assistant
    text_de: Mapped[str] = mapped_column(Text, default="")
    audio_path: Mapped[str | None] = mapped_column(String, default=None)
    stt: Mapped[dict] = mapped_column(JSON, default=dict)
    latency: Mapped[dict] = mapped_column(JSON, default=dict)  # per-stage ms
    score_id: Mapped[str | None] = mapped_column(String, default=None)
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class UtteranceScore(Base):
    __tablename__ = "utterance_scores"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    turn_id: Mapped[str | None] = mapped_column(String, default=None, index=True)
    attempt_id: Mapped[str | None] = mapped_column(String, default=None)
    audio_path: Mapped[str] = mapped_column(String)
    ref_text: Mapped[str] = mapped_column(Text)
    words: Mapped[list] = mapped_column(JSON, default=list)  # [{w, score, phones:[{p, score, t0, t1}]}]
    overall: Mapped[float] = mapped_column(Float, default=0.0)  # 0..100
    confidence: Mapped[float] = mapped_column(Float, default=1.0)  # 0.5 for conversation-sourced
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PhonemeStat(Base):
    __tablename__ = "phoneme_stats"
    phoneme: Mapped[str] = mapped_column(String, primary_key=True)
    ema: Mapped[float] = mapped_column(Float, default=0.0)
    n: Mapped[int] = mapped_column(Integer, default=0)
    last10: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class MockExam(Base):
    __tablename__ = "mock_exams"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    level: Mapped[str] = mapped_column(String)  # A1|A2|B1
    mode: Mapped[str] = mapped_column(String, default="full")  # full|module
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    readiness_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class MockSection(Base):
    __tablename__ = "mock_sections"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    exam_id: Mapped[str] = mapped_column(ForeignKey("mock_exams.id"), index=True)
    module: Mapped[str] = mapped_column(String)  # lesen|hoeren|schreiben|sprechen
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    grader_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    time_used_s: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="open")  # open|active|done


class Placement(Base):
    __tablename__ = "placements"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    items: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class XpEvent(Base):
    __tablename__ = "xp_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    ref: Mapped[dict] = mapped_column(JSON, default=dict)


class DailyActivity(Base):
    __tablename__ = "daily_activity"
    date: Mapped[str] = mapped_column(String, primary_key=True)  # YYYY-MM-DD (03:00 boundary)
    minutes: Mapped[float] = mapped_column(Float, default=0.0)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    core_done: Mapped[bool] = mapped_column(Boolean, default=False)
    streak_after: Mapped[int] = mapped_column(Integer, default=0)
    freeze_used: Mapped[bool] = mapped_column(Boolean, default=False)


class Badge(Base):
    __tablename__ = "badges"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name_de: Mapped[str] = mapped_column(String)
    name_en: Mapped[str] = mapped_column(String)
    desc_de: Mapped[str] = mapped_column(String)
    desc_en: Mapped[str] = mapped_column(String, default="")
    icon: Mapped[str] = mapped_column(String, default="sparkle")
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class BadgeAward(Base):
    __tablename__ = "badge_awards"
    badge_id: Mapped[str] = mapped_column(ForeignKey("badges.id"), primary_key=True)
    awarded_at: Mapped[datetime] = mapped_column(default=utcnow)
    context: Mapped[dict] = mapped_column(JSON, default=dict)


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"
    iso_week: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "2026-W27"
    generated_at: Mapped[datetime] = mapped_column(default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class ContentJob(Base):
    __tablename__ = "content_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class TranslationCache(Base):
    __tablename__ = "translation_cache"
    hash: Mapped[str] = mapped_column(String, primary_key=True)  # sha1(word|context)
    word: Mapped[str] = mapped_column(String, index=True)
    context: Mapped[str] = mapped_column(Text, default="")
    gloss: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TtsCache(Base):
    __tablename__ = "tts_cache"
    hash: Mapped[str] = mapped_column(String, primary_key=True)  # sha1(engine|voice|text)
    path: Mapped[str] = mapped_column(String)
    engine: Mapped[str] = mapped_column(String, default="piper")
    voice: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
