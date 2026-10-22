"""Live co-editing in WordCraft and DeckCraft: OfficeHub passes the changes between the people in a file.

Everyone who opens a file in WordCraft or DeckCraft joins its room. The programs keep the document as a
shared (CRDT) document and send each change as a small binary update; OfficeHub hands every update to the
others and keeps them, so whoever joins later starts from all changes so far. The first person in an empty
room "seeds" it with the file as opened. Presence (who is in, where their cursor is) goes along but is not
kept. Like the built-in meetings, rooms live in memory and the browsers keep one request open (long polling).

When the log grows, OfficeHub asks one participant for the whole document as one update and keeps that
instead. When the last person leaves, the room is gone; the file itself is saved through the normal save.
"""

import asyncio
import secrets
import time
from dataclasses import dataclass, field

POLL_SECONDS = 20
GONE_SECONDS = POLL_SECONDS + 15
QUEUE_LIMIT = 2000
COMPACT_AFTER = 300  # updates in the log before one participant is asked for the whole document
SLOTS = 4096
COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#65a30d"]


@dataclass
class Peer:
    id: str
    user_id: int
    name: str
    slot: int
    color: str
    can_write: bool
    state: dict = field(default_factory=dict)
    queue: list[tuple[int, dict]] = field(default_factory=list)
    seq: int = 0
    seen: float = field(default_factory=time.monotonic)
    wake: asyncio.Event = field(default_factory=asyncio.Event)

    def push(self, message: dict) -> None:
        self.seq += 1
        self.queue.append((self.seq, message))
        del self.queue[:-QUEUE_LIMIT]
        self.wake.set()

    def public(self) -> dict:
        return {"id": self.id, "user_id": self.user_id, "name": self.name, "color": self.color, "slot": self.slot,
                "can_write": self.can_write, "state": self.state}


@dataclass
class Room:
    peers: dict[str, Peer] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)  # base64 updates, oldest first
    seeder: str | None = None  # who was asked to seed and has not yet
    compacting: str | None = None


rooms: dict[int, Room] = {}


def _sweep(file_id: int) -> None:
    room = rooms.get(file_id)
    if room is None:
        return
    limit = time.monotonic() - GONE_SECONDS
    for peer in [p for p in room.peers.values() if p.seen < limit]:
        leave(file_id, peer.id)


def join(file_id: int, user_id: int, name: str, can_write: bool) -> tuple[Peer, Room, bool]:
    """Enter the room; returns the new participant, the room and whether they must seed it."""
    _sweep(file_id)
    room = rooms.setdefault(file_id, Room())
    used = {p.slot for p in room.peers.values()}
    slot = next((s for s in range(SLOTS) if s not in used), 0)
    peer = Peer(id=secrets.token_hex(8), user_id=user_id, name=name, slot=slot, color=COLORS[slot % len(COLORS)],
                can_write=can_write)
    for other in room.peers.values():
        other.push({"type": "join", "from": peer.id, "data": peer.public()})
    room.peers[peer.id] = peer
    seed = not room.log and room.seeder is None and can_write
    if seed:
        room.seeder = peer.id
    return peer, room, seed


def find(file_id: int, peer_id: str, user_id: int) -> Peer | None:
    peer = rooms.get(file_id, Room()).peers.get(peer_id)
    return peer if peer is not None and peer.user_id == user_id else None


def update(file_id: int, sender: Peer, data: str) -> None:
    """A change: keep it and pass it on. The seed is the first update of the room."""
    room = rooms.get(file_id)
    if room is None:
        return
    sender.seen = time.monotonic()
    if room.seeder == sender.id:
        room.seeder = None
    room.log.append(data)
    for peer in room.peers.values():
        if peer is not sender:
            peer.push({"type": "update", "from": sender.id, "data": data})
    if len(room.log) > COMPACT_AFTER and room.compacting is None:
        room.compacting = sender.id
        sender.push({"type": "compact", "from": "", "data": {"upto": len(room.log)}})


def compact(file_id: int, sender: Peer, data: str, upto: int) -> None:
    """The whole document as one update, covering the first `upto` log entries."""
    room = rooms.get(file_id)
    if room is None or upto < 1 or upto > len(room.log):
        return
    room.log[:upto] = [data]
    room.compacting = None


def presence(file_id: int, sender: Peer, state: dict) -> None:
    room = rooms.get(file_id)
    if room is None:
        return
    sender.seen = time.monotonic()
    sender.state = state
    for peer in room.peers.values():
        if peer is not sender:
            peer.push({"type": "presence", "from": sender.id, "data": state})


async def poll(peer: Peer, after: int) -> list[dict]:
    peer.seen = time.monotonic()
    peer.queue = [(seq, m) for seq, m in peer.queue if seq > after]
    if not peer.queue:
        peer.wake.clear()
        try:
            await asyncio.wait_for(peer.wake.wait(), POLL_SECONDS)
        except TimeoutError:
            pass
    peer.seen = time.monotonic()
    return [{"seq": seq, **m} for seq, m in peer.queue if seq > after]


def leave(file_id: int, peer_id: str) -> None:
    room = rooms.get(file_id)
    if room is None or peer_id not in room.peers:
        return
    gone = room.peers.pop(peer_id)
    gone.wake.set()
    if room.compacting == peer_id:
        room.compacting = None
    for peer in room.peers.values():
        peer.push({"type": "leave", "from": peer_id, "data": {}})
    if not room.peers:
        rooms.pop(file_id, None)
        return
    if room.seeder == peer_id:
        # They left before seeding: someone else who can write seeds it from their copy of the file.
        room.seeder = next((p.id for p in room.peers.values() if p.can_write), None)
        if room.seeder:
            room.peers[room.seeder].push({"type": "seed", "from": "", "data": {}})


def count(file_id: int) -> int:
    _sweep(file_id)
    return len(rooms.get(file_id, Room()).peers)
