"""Breakout rooms: the people leading a meeting split it into small groups for a while, like in Teams.

Each group is a room of its own ("<meeting room>-b<n>") on the same way underneath (built in or Jitsi). Which
person belongs to which group lives here in memory: it only matters while the meeting runs.
"""

import time
from dataclasses import dataclass, field

MAX_ROOMS = 20


@dataclass
class Breakouts:
    rooms: list[str] = field(default_factory=list)  # the names of the groups
    assign: dict[str, int] = field(default_factory=dict)  # who -> group number (0-based)
    open: bool = False
    ends_at: float | None = None  # time.time() when everyone is called back

    def public(self, who: str) -> dict:
        if self.open and self.ends_at is not None and time.time() >= self.ends_at:
            self.open = False
        return {"open": self.open, "rooms": self.rooms, "mine": self.assign.get(who) if self.open else None,
                "ends_at": self.ends_at if self.open else None, "assign": self.assign}


meetings: dict[str, Breakouts] = {}


def get(main: str) -> Breakouts:
    return meetings.setdefault(main, Breakouts())


def room_name(main: str, number: int) -> str:
    return f"{main}-b{number + 1}"
