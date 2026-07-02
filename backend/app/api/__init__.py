"""Router registry — each phase appends its router here."""

from . import system

all_routers = [
    system.router,
]
