"""End-to-end encrypted meetings: OfficeHub as the MLS delivery service (RFC 9420, like Webex).

The browsers in an encrypted meeting form an MLS group. Each one makes its own keys and publishes only a key
package (its public part); one of them – the leader, whoever has been in the group longest – adds newcomers and
removes people who left with a commit, and sends the newcomers a welcome. From the group's secrets every browser
derives the keys for audio, video and screen (SFrame) and encrypts chat, reactions and whiteboard strokes as MLS
messages. Here only public key packages, commits, welcomes and ciphertext pass; the keys never do.

The order of commits is what keeps everyone on the same epoch: a commit counts only when it is made on the epoch
the room is at, and then everyone gets it in the same order. Rooms live in memory, like the signalling (rtc.py).
"""

import asyncio
import secrets
import time
from dataclasses import dataclass, field

POLL_SECONDS = 20
GONE_SECONDS = POLL_SECONDS + 15
QUEUE_LIMIT = 500
MAX_BYTES = 200_000  # one commit with welcomes for many newcomers stays well below this


@dataclass
class Member:
    id: str
    who: str
    name: str
    in_group: bool = False
    key_package: str = ""  # base64, waiting to be added
    queue: list[tuple[int, dict]] = field(default_factory=list)
    seq: int = 0
    seen: float = field(default_factory=time.monotonic)
    wake: asyncio.Event = field(default_factory=asyncio.Event)

    def push(self, message: dict) -> None:
        self.seq += 1
        self.queue.append((self.seq, message))
        del self.queue[:-QUEUE_LIMIT]
        self.wake.set()


@dataclass
class Group:
    epoch: int | None = None  # None: nobody has made the group yet
    members: dict[str, Member] = field(default_factory=dict)  # in order of arrival
    gone: list[str] = field(default_factory=list)  # left while in the group: the leader removes them
    version: int = 0  # every change of the roster counts up, so a browser can ignore an older one

    def leader(self) -> Member | None:
        return next((m for m in self.members.values() if m.in_group), None)

    def roster(self) -> dict:
        leader = self.leader()
        return {
            "version": self.version,
            "epoch": self.epoch,
            "leader": leader.id if leader else None,
            "members": [
                {"id": m.id, "who": m.who, "name": m.name, "in_group": m.in_group, "key_package": m.key_package}
                for m in self.members.values()
            ],
            "gone": list(self.gone),
        }

    def announce(self) -> None:
        self.version += 1
        roster = self.roster()
        for member in self.members.values():
            member.push({"type": "roster", "data": roster})


groups: dict[str, Group] = {}


class Conflict(Exception):
    """The commit was made on an older epoch: process what came in, then try again."""


def sweep(room: str) -> None:
    group = groups.get(room)
    if group is None:
        return
    limit = time.monotonic() - GONE_SECONDS
    for member in [m for m in group.members.values() if m.seen < limit]:
        leave(room, member.id)


def join(room: str, who: str, name: str) -> tuple[Member, dict]:
    sweep(room)
    group = groups.setdefault(room, Group())
    member = Member(id=secrets.token_hex(8), who=who, name=name)
    group.members[member.id] = member
    group.announce()
    return member, group.roster()


def find(room: str, member_id: str, who: str) -> Member | None:
    member = groups.get(room, Group()).members.get(member_id)
    return member if member is not None and member.who == who else None


def create(room: str, member: Member) -> tuple[bool, int]:
    """The first one makes the group (epoch 0). False when someone else was quicker. Also the roster version."""
    group = groups[room]
    if group.epoch is not None:
        return False, group.version
    group.epoch = 0
    member.in_group = True
    member.key_package = ""
    group.announce()
    return True, group.version


def publish(room: str, member: Member, key_package: str) -> int:
    """A newcomer's public key package, for the leader to add. Returns the roster version."""
    member.key_package = key_package
    groups[room].announce()
    return groups[room].version


def commit(room: str, member: Member, epoch: int, message: str, welcome: str, added: list[str],
           removed: list[str]) -> tuple[int, int]:
    """The leader's commit on `epoch`: everyone in the group gets it, the added people the welcome. Returns the new
    epoch and the roster version."""
    group = groups[room]
    if not member.in_group or group.epoch is None or epoch != group.epoch:
        raise Conflict()
    group.epoch += 1
    receivers = [m for m in group.members.values() if m.in_group and m is not member and m.id not in removed]
    for m in receivers:
        m.push({"type": "commit", "from": member.id, "data": {"epoch": epoch, "message": message}})
    for member_id in added:
        newcomer = group.members.get(member_id)
        if newcomer is not None and not newcomer.in_group:
            newcomer.in_group = True
            newcomer.key_package = ""
            newcomer.push({"type": "welcome", "from": member.id, "data": {"epoch": group.epoch, "message": welcome}})
    for member_id in removed:
        if member_id in group.gone:
            group.gone.remove(member_id)
        still = group.members.get(member_id)
        if still is not None:
            still.in_group = False
    group.announce()
    return group.epoch, group.version


def relay(room: str, member: Member, data: dict) -> None:
    """An encrypted application message (chat, reaction, whiteboard) to everyone else in the group."""
    member.seen = time.monotonic()
    for m in groups[room].members.values():
        if m is not member and m.in_group:
            m.push({"type": "app", "from": member.id, "data": data})


def rejoin(room: str, member: Member) -> None:
    """A browser that lost track of the group asks to be removed and added anew."""
    group = groups[room]
    if member.in_group:
        member.in_group = False
        group.gone.append(member.id)
    member.key_package = ""
    group.announce()


async def poll(member: Member, after: int) -> list[dict]:
    member.seen = time.monotonic()
    member.queue = [(seq, m) for seq, m in member.queue if seq > after]
    if not member.queue:
        member.wake.clear()
        try:
            await asyncio.wait_for(member.wake.wait(), POLL_SECONDS)
        except TimeoutError:
            pass
    return [{"seq": seq, **m} for seq, m in member.queue if seq > after]


def leave_who(room: str, who: str) -> None:
    """Someone was removed from the meeting by a moderator: out of the group too."""
    for member in [m for m in groups.get(room, Group()).members.values() if m.who == who]:
        member.push({"type": "removed", "data": {}})
        leave(room, member.id)


def leave(room: str, member_id: str) -> None:
    group = groups.get(room)
    if group is None or member_id not in group.members:
        return
    gone = group.members.pop(member_id)
    gone.wake.set()
    if gone.in_group:
        group.gone.append(member_id)
    if not any(m.in_group for m in group.members.values()):
        # Nobody holds the group's secrets any more: the next one starts a new group.
        group.epoch = None
        group.gone.clear()
        for m in group.members.values():
            m.in_group = False
    if not group.members:
        groups.pop(room, None)
        return
    group.announce()
