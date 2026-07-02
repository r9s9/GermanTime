"""Router registry — each phase appends its router here."""

from . import exercises, factory, settings, system, translate

all_routers = [
    system.router,
    settings.router,
    exercises.router,
    translate.router,
    factory.router,
]
