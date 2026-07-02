"""Idempotent seed loader: upserts grammar topics, vocab, and badges into the DB.

Safe to call on every startup. Vocab is upserted by (lemma, pos) so re-running
never duplicates, and scripts/parse_goethe_wordlists.py can later top up the
lists (e.g. with official Goethe wordlists) without wiping learner progress —
srs_cards reference vocab_items.id, so existing rows are updated in place, not
replaced.
"""

import csv
import json

from sqlalchemy import select

from .. import config
from ..db import SessionLocal
from ..models import Badge, GrammarTopic, VocabItem


def _load_grammar_topics(db) -> int:
    with open(config.SEED_DIR / "grammar_tree.json", encoding="utf-8") as f:
        topics = json.load(f)["topics"]

    existing = {t.id: t for t in db.scalars(select(GrammarTopic))}
    n = 0
    for i, t in enumerate(topics):
        row = existing.get(t["id"])
        if row is None:
            row = GrammarTopic(id=t["id"])
            db.add(row)
        row.level = t["level"]
        row.syllabus_week = t["week"]
        row.title_de = t["de"]
        row.title_en = t["en"]
        row.prereq_ids = t["prereq"]
        row.sort = i
        n += 1
    return n


_ARTICLES = ("der ", "die ", "das ")


def _load_vocab_csv(db, path, level: str, existing: dict) -> int:
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for rank, row in enumerate(csv.DictReader(f)):
            lemma = row["lemma"].strip()
            article = row["article"].strip() or None
            # Normalize away redundant "die Familie" style prefixes so lemma is
            # always bare and `article` is the single source of truth.
            for prefix in _ARTICLES:
                if lemma.startswith(prefix) and article == prefix.strip():
                    lemma = lemma[len(prefix):]
                    break
            pos = row["pos"].strip()
            key = (lemma, pos)
            item = existing.get(key)
            if item is None:
                item = VocabItem(lemma=lemma, pos=pos)
                db.add(item)
                existing[key] = item
            item.article = article
            item.plural = row["plural"].strip() or None
            item.level = level
            item.freq_rank = rank
            item.en_gloss = row["en_gloss"].strip()
            item.tags = [t.strip() for t in row["tags"].split(";") if t.strip()]
            n += 1
    return n


def _load_vocab(db) -> int:
    existing = {(v.lemma, v.pos): v for v in db.scalars(select(VocabItem))}
    n = 0
    for level in ("a1", "a2", "b1"):
        path = config.SEED_DIR / "vocab" / f"{level}.csv"
        if path.exists():
            n += _load_vocab_csv(db, path, level.upper(), existing)
    return n


def _load_badges(db) -> int:
    with open(config.SEED_DIR / "badges.json", encoding="utf-8") as f:
        badges = json.load(f)["badges"]

    existing = {b.id: b for b in db.scalars(select(Badge))}
    n = 0
    for i, b in enumerate(badges):
        row = existing.get(b["id"])
        if row is None:
            row = Badge(id=b["id"])
            db.add(row)
        row.name_de = b["de"]
        row.name_en = b["en"]
        row.desc_de = b["desc_de"]
        row.desc_en = b["desc_en"]
        row.icon = b["icon"]
        row.criteria = b["criteria"]
        row.sort = i
        n += 1
    return n


def load_seeds() -> dict:
    with SessionLocal() as db:
        counts = {
            "grammar_topics": _load_grammar_topics(db),
            "vocab_items": _load_vocab(db),
            "badges": _load_badges(db),
        }
        db.commit()
    return counts
