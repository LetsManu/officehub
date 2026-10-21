"""Built-in meetings: OfficeHub introduces the browsers in a meeting to each other.

Each browser says hello, then keeps one request open (long polling) to receive messages from the
others: connection offers and answers (WebRTC), "muted" / "hand raised" states, chat lines and small app
messages (reactions, whiteboard strokes, and – only from people leading the meeting – moderation). Audio and
video never pass through here; they go directly between the browsers.

Rooms live in memory. That is enough for one backend process (the default); after a restart the pages
simply say hello again.
"""

import asyncio
import secrets
import time
from dataclasses import dataclass, field

POLL_SECONDS = 20  # one open request at most this long
GONE_SECONDS = POLL_SECONDS + 15  # no request for this long: the person has left
QUEUE_LIMIT = 500


@dataclass
class Peer:
    id: str
    who: str  # the user id or "guest-<id>" from the room token
    name: str
    host: bool
    mod: bool = False
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
        return {"id": self.id, "name": self.name, "host": self.host, "who": self.who, "mod": self.mod, "state": self.state}


rooms: dict[str, dict[str, Peer]] = {}
removed: dict[str, set[str]] = {}  # meeting -> people a moderator removed (they cannot come back today)


def _sweep(room: str) -> None:
    """Forget people whose page stopped asking (closed tab, lost network) and tell the others."""
    peers = rooms.get(room, {})
    limit = time.monotonic() - GONE_SECONDS
    for peer in [p for p in peers.values() if p.seen < limit]:
        leave(room, peer.id)


def join(room: str, who: str, name: str, host: bool, mod: bool = False) -> tuple[Peer, list[Peer]]:
    _sweep(room)
    peers = rooms.setdefault(room, {})
    peer = Peer(id=secrets.token_hex(8), who=who, name=name, host=host, mod=mod)
    others = list(peers.values())
    for other in others:
        other.push({"type": "join", "from": peer.id, "data": peer.public()})
    peers[peer.id] = peer
    return peer, others


def count(room: str) -> int:
    _sweep(room)
    return len(rooms.get(room, {}))


def find(room: str, peer_id: str, who: str) -> Peer | None:
    peer = rooms.get(room, {}).get(peer_id)
    return peer if peer is not None and peer.who == who else None


def send(room: str, sender: Peer, to: str | None, kind: str, data: dict) -> None:
    sender.seen = time.monotonic()
    if kind == "state":
        sender.state = data
    message = {"type": kind, "from": sender.id, "data": data}
    for peer in rooms.get(room, {}).values():
        if peer is not sender and (to is None or peer.id == to):
            peer.push(message)


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


def remove(main: str, room: str, peer_id: str) -> Peer | None:
    """A moderator removes someone: they are told, disconnected, and cannot join this meeting again."""
    peer = rooms.get(room, {}).get(peer_id)
    if peer is None:
        return None
    removed.setdefault(main, set()).add(peer.who)
    peer.push({"type": "removed", "from": "", "data": {}})
    leave(room, peer_id)
    return peer


def is_removed(main: str, who: str) -> bool:
    return who in removed.get(main, set())


def leave(room: str, peer_id: str) -> None:
    peers = rooms.get(room)
    if not peers or peer_id not in peers:
        return
    gone = peers.pop(peer_id)
    gone.wake.set()
    for peer in peers.values():
        peer.push({"type": "leave", "from": peer_id, "data": {}})
    if not peers:
        rooms.pop(room, None)
