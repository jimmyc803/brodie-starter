"""Deterministic command parsing; no registration or opt-out side effects."""

from dataclasses import dataclass
import re
import string
from typing import Literal


CommandKind = Literal[
    "JOIN", "YES", "QUEUE", "STATUS", "TOP", "LEAVE", "RULES", "POWER",
    "HELP", "STOP", "START", "LINK", "LIFE", "DELETE", "UNKNOWN",
]


@dataclass(frozen=True)
class Command:
    kind: CommandKind
    arg: str = ""


_COMMANDS: dict[str, CommandKind] = {
    "JOIN": "JOIN", "YES": "YES", "QUEUE": "QUEUE", "STATUS": "STATUS",
    "TOP": "TOP", "LEAVE": "LEAVE", "RULES": "RULES", "POWER": "POWER",
    "HELP": "HELP", "STOP": "STOP", "START": "START",
    # LIFE: team-only health report (D-40). Exact match only, never fuzzy: it is one edit from LINE
    # (an alias for QUEUE) and from LIKE/LIVE, so a competitor's typo must not reach it.
    "LIFE": "LIFE", "HEALTH": "LIFE",
    "LINK": "LINK",  # LINK <6-digit code>: verify a web account's FaceTime handle (D-25). Exact match only, never fuzzy.
}
_ALIASES: dict[str, CommandKind] = {
    "Q": "QUEUE", "LINE": "QUEUE", "S": "STATUS", "ME": "STATUS",
    "LEADERBOARD": "TOP", "LB": "TOP", "UNSTOP": "START",
}
_FUZZY_COMMANDS: tuple[CommandKind, ...] = (
    "QUEUE", "STATUS", "LEAVE", "RULES", "POWER", "HELP", "JOIN",
)
# Data-deletion request: "delete", "delete my data", "delete data", "delete me" (exact; anything else is UNKNOWN).
_DELETE_ARGS = {"", "my data", "data", "me"}
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
    if word == "DELETE":
        if " ".join(arg.lower().split()) in _DELETE_ARGS:
            return Command("DELETE")
        return Command("UNKNOWN", arg)
    kind = _COMMANDS.get(word) or _ALIASES.get(word)
    if kind is None and len(word) >= 4:
        candidates = {
            candidate for candidate in _FUZZY_COMMANDS
            if (candidate != "JOIN" or arg) and _one_edit(word, candidate)
        }
        if len(candidates) == 1:
            kind = candidates.pop()
    return Command(kind or "UNKNOWN", arg)


# Attribution tags a JOIN may carry, in any position: "ref-K7X2QB" (a participant's invite code) and "src-tiktok" (the
# site link the texter came from). A '-', ':' or '=' follows the prefix, so a tag can never be a valid display name
# (names are [A-Za-z0-9_] only) and plain "JOIN name" parses exactly as before.
_JOIN_TAG = re.compile(r"(?i)^(ref|src)[-:=]([A-Za-z0-9_]{1,24})$")


@dataclass(frozen=True)
class JoinArg:
    name: str
    ref_code: str | None = None
    source: str | None = None


def split_join_arg(arg: str) -> JoinArg:
    """Split a JOIN argument into the display name and optional ref-/src- tags (first of each kind wins)."""
    ref: str | None = None
    src: str | None = None
    words: list[str] = []
    for token in arg.split():
        match = _JOIN_TAG.match(token.strip(_EDGES.replace("-", "").replace(":", "").replace("=", "")))
        if match is None:
            words.append(token)
            continue
        kind, value = match.group(1).lower(), match.group(2)
        if kind == "ref":
            ref = ref or value.upper()
        else:
            src = src or value.lower()
    # The leftover words are the display name, joined by single spaces: "JOIN stan lee" is "stan lee" (D-41).
    return JoinArg(" ".join(words).strip(_EDGES), ref, src)


def validate_display_name(name: str) -> tuple[bool, str]:
    """The same rule as ch_valid_display_name (D-41): 3-20 characters of letters, numbers and underscores in
    space-separated words, so "stan lee" is a name but " stan", "stan  lee" and "stan-lee" are not."""
    if not 3 <= len(name) <= 20:
        return False, "Use 3–20 characters."
    if re.fullmatch(r"[A-Za-z0-9_]+( [A-Za-z0-9_]+)*", name) is None:
        return False, "Use only letters, numbers, underscores, and single spaces."
    # Checked with the spaces removed too: since D-41 a name can hold spaces, and "f uck" would otherwise pass.
    flat = name.lower().replace(" ", "")
    if any(word in name.lower() or word in flat for word in _BLOCKED):
        return False, "Pick a name without profanity or slurs."
    return True, ""
