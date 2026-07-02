"""Router registry — each phase appends its router here."""

from . import settings, system

all_routers = [
    system.router,
    settings.router,
]
