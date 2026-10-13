"""Deterministic command parsing; no registration or opt-out side effects."""

from dataclasses import dataclass
import re
import string
from typing import Literal


CommandKind = Literal[
    "JOIN", "YES", "QUEUE", "STATUS", "TOP", "LEAVE", "RULES", "POWER",
    "HELP", "STOP", "START", "LINK", "UNKNOWN",
]


@dataclass(frozen=True)
class Command:
    kind: CommandKind
    arg: str = ""


_COMMANDS: dict[str, CommandKind] = {
    "JOIN": "JOIN", "YES": "YES", "QUEUE": "QUEUE", "STATUS": "STATUS",
    "TOP": "TOP", "LEAVE": "LEAVE", "RULES": "RULES", "POWER": "POWER",
    "HELP": "HELP", "STOP": "STOP", "START": "START",
    "LINK": "LINK",  # LINK <6-digit code>: verify a web account's FaceTime handle (D-25). Exact match only, never fuzzy.
}
_ALIASES: dict[str, CommandKind] = {
    "Q": "QUEUE", "LINE": "QUEUE", "S": "STATUS", "ME": "STATUS",
    "LEADERBOARD": "TOP", "LB": "TOP", "UNSTOP": "START",
}
_FUZZY_COMMANDS: tuple[CommandKind, ...] = (
    "QUEUE", "STATUS", "LEAVE", "RULES", "POWER", "HELP", "JOIN",
)
_STOP_WORDS = {"STOP", "STOPALL", "QUIT", "CANCEL", "UNSUBSCRIBE", "END"}
_EDGES = string.whitespace + string.punctuation.replace("_", "") + "“”‘’…—–"
_BLOCKED = ("fuck", "shit", "bitch", "cunt", "asshole", "motherfucker", "nigger", "nigga", "faggot", "fag", "kike", "chink", "tranny")


def _one_edit(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    shorter, longer = sorted((left, right), key=len)
    for index in range(len(shorter)):
        if shorter[index] != longer[index]:
            return shorter[index:] == longer[index + 1:]
    return True


def parse(body: str) -> Command:
    text = body.strip(_EDGES)
    if not text:
        return Command("UNKNOWN")
    parts = re.split(r"[\s:]+", text, maxsplit=1)
    word = parts[0].strip(_EDGES).upper()
    arg = parts[1].strip(_EDGES) if len(parts) > 1 else ""
    if word in _STOP_WORDS or re.search(r"\bstop\b", text, re.IGNORECASE):
        return Command("STOP", arg)
    kind = _COMMANDS.get(word) or _ALIASES.get(word)
    if kind is None and len(word) >= 4:
        candidates = {
            candidate for candidate in _FUZZY_COMMANDS
            if (candidate != "JOIN" or arg) and _one_edit(word, candidate)
        }
        if len(candidates) == 1:
            kind = candidates.pop()
    return Command(kind or "UNKNOWN", arg)


def validate_display_name(name: str) -> tuple[bool, str]:
    if not 3 <= len(name) <= 20:
        return False, "Use 3–20 characters."
    if re.fullmatch(r"[A-Za-z0-9_]+", name) is None:
        return False, "Use only letters, numbers, and underscores."
    if any(word in name.lower() for word in _BLOCKED):
        return False, "Pick a name without profanity or slurs."
    return True, ""
