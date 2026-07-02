"""Router registry — each phase appends its router here."""

from . import (
    conversations, exercises, factory, placement, plan, progress, settings,
    srs, system, translate, tts, ws_voice,
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
]
