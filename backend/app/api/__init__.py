"""Router registry — each phase appends its router here."""

from . import (
    backup, conversations, exams, exercises, factory, gamification, placement, plan, progress,
    pron, reports, settings, srs, system, translate, tts, ws_voice,
)

all_routers = [
    system.router,
    settings.router,
    exercises.router,
    translate.router,
    factory.router,
    placement.router,
    plan.router,
    progress.router,
    srs.router,
    tts.router,
    conversations.router,
    ws_voice.router,
    pron.router,
    exams.router,
    gamification.router,
    reports.router,
    backup.router,
]
