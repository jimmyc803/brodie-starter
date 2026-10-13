"""Competition call controller (CONTRACTS C6, SPEC §2 Calls, §3 rows 1/3/9, §4 call sequence, §6 liveness).

One CompetitionCall per FaceTime call, driven on the worker's event loop (every method runs on that loop; the
perception thread hands frames and rep events over with call_soon_threadsafe):

    call = CompetitionCall(call_id, line_id, handle, dispatcher, judge_cfg, clock, say, leave=..., ...)
    if await call.start():          # gatekeeper: POST /calls/start; reject -> cue, leave <= 5 s, nothing recorded
        ... on_frame(FrameObs) / on_rep(event, t) as they come, tick(now) a few times a second (run() does it)
    await call.end(reason)          # local checkpoint first, then reps_committed and call_ended

Clock: `clock()` is wall time in epoch seconds (time.time in production, a fake in tests). Frames and reps carry
wall times too; the controller works on the call clock rel = wall - t0 (t0 = just before /calls/start, so the
worker never counts a rep the dispatcher would put after connected_at + call_count_s).

Timeline (call clock, numbers from the /calls/start `config` or the competition_config defaults): welcome at 0
(power_hour 4 s later when the dispatcher says power_hour_active); thirty_left at count_s - 30; time_up at count_s,
counting stops (later reps are ignored, not recorded); check_texts 1.5 s later (REVEAL_MODE audio_only; REVEAL_MODE=video
also publishes a card/fallback video track via the worker's `reveal` hook, C7.v; any failure stays audio_only); HANGUP_MODE
unverified plays hang_up HANG_UP_LEAD_S before count_s + reveal_s; at count_s + reveal_s end() commits and the
worker leaves the room (leave_room and unverified both leave; chert_api asks Chert to end the call first; delete_room:
the worker deletes the LiveKit room once the commit is in, which makes Chert end the FaceTime call, and leaves the room
if the delete fails).
Only the latest due cue of a tick is played (a stalled loop never stacks cues).

Liveness (judge/liveness.py LivenessChallenge, C7.l: schedule/due/start/poll/finish/on_frame/on_rep/windows):
scheduled once per call inside thr['liveness_window_s'], clamped so the first cue fires >= 2 attempts (FREEZE: timeout
+ latest go + go reaction) + the retry delay before count end. Cue keys from start()/poll() are played as given (incl.
challenge_go). After every start()/poll() each window that is new or whose deadline moved goes to
update_challenge_window (wall clock); windows also mark reps in_challenge here (a rep that raced the judge's window).
Every recorded rep goes to lc.on_rep (reps earned: the result can no longer be 'skipped'). poll 'skipped' (no rep
earned, nobody in frame) mid-count -> ONE reschedule in the remaining window. Without a pass every valid rep is
committed as liveness_fail; 'fail' goes to the payload as liveness_result (the DB voids the call).
Since j3 the challenge is OFF unless thr['liveness_enabled'] is true (competition_config.judge_thresholds): no
challenge is scheduled, no challenge cue or window, reps keep their judge verdict and liveness_result is 'skipped'.

Checkpoint: data/tmp/sessions/<call_id>.challenge.json (CHALLENGE_SESSIONS_DIR overrides), atomic (tmp + fsync +
os.replace), written on accept, after every rep and at every end step; `committed` turns true only after both
events were acknowledged; `sent` records which one already was (idem keys `<call_id>:<kind>`) so the reconciler
(task 32) replays exactly the missing ones. Rejected calls write nothing and send nothing beyond /calls/start.
Dispatcher failures never raise out of start()/end(): start fails closed (reject + ERROR log + alert), end keeps
the checkpoint with committed:false.
"""
from __future__ import annotations

import asyncio
import dataclasses
import fcntl
import hashlib
import json
import logging
import math
import os
import random
import re
import tempfile
import time
from typing import Any, Awaitable, Callable

from challenge.judge.cues import CUES
from challenge.judge.gates import JUDGE_VERSION, merged_thresholds
from challenge.worker.client import DispatcherError, idem_key, utc_iso

log = logging.getLogger("challenge.worker")

CHECKPOINT_VERSION = 2
LOCK_PROTOCOL = 1               # checkpoints written while holding the per-call lock carry "lock_protocol": 1
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
C2_METRIC_KEYS = ("min_elbow_deg_l", "min_elbow_deg_r", "top_elbow_deg", "max_hip_line_dev_deg", "min_knee_deg",
                  "knee_floor_contact", "shoulder_wrist_drop", "shoulder_elbow_gap", "min_keypoint_conf",
                  "frame_conf_frac", "persons_in_frame", "rep_duration_s", "torso_ok", "side", "classifier_labels")
DEFAULT_COUNT_S = 180          # competition_config call_count_s default (used only when the dispatcher sends none)
DEFAULT_REVEAL_S = 15          # competition_config call_reveal_s default
START_DEADLINE_S = 8.0         # the whole /calls/start retry loop (P1-2: a slow or lost answer is retried, same call id)
FAIL_CUE = "try_again"  # fail closed: the caller hears this instead of silence
FAIL_CUE_S = 3.0               # fail closed: let the cue play before the hang-up
FAIL_ENDED_S = 5.0             # fail closed: the best-effort call_ended is given this long
FAIL_ENDED_REASONS = frozenset({"dispatcher_unreachable", "accept_without_user", "call_setup_failed"})
NO_VIDEO_CUE = "camera_off"  # P0-3: an accepted call without a video track
REJECT_LEAVE_S = 3.5           # leave this long after t0 on a reject (+ <= 1.5 s cue tail in the worker = 5 s)
WELCOME_GAP_S = 4.0            # power_hour cue after the welcome
CHECK_TEXTS_AFTER_S = 1.5      # check_texts after time_up
HANG_UP_LEAD_S = 4.0           # hang_up this long before the leave (HANGUP_MODE unverified)
RESCHEDULE_MIN_S = 2.0         # earliest liveness reschedule after a skip
COMMIT_DEADLINE_S = 20.0       # end(): both events within this, else the checkpoint stays committed:false
DRAIN_MAX_S = 3.0              # end(): wait this long for the rep intake to seal (frame in flight finished, its events in)
DEFERRABLE_CUES = frozenset({"power_hour", "thirty_left"})   # held while a liveness challenge is open ...
DEFER_MAX_S = 10.0                                           # ... and dropped once this late
JUDGE_CUE_KEYS = frozenset({"knees_down", "too_shallow", "no_lockout", "not_in_frame", "hips", "multiple_people"})
HANGUP_MODES = ("leave_room", "unverified", "chert_api", "delete_room")
LIVEKIT_ENV = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")   # HANGUP_MODE=delete_room (the room service API)
REVEAL_MODES = ("audio_only", "video")
LIVENESS_RESULTS = ("pass", "fail", "skipped")


class UnsupportedMode(ValueError):
    """A flag value this worker cannot honour (fail loudly at startup)."""


def check_modes(hangup_mode: str, reveal_mode: str) -> list[str]:
    """Validate HANGUP_MODE / REVEAL_MODE for the worker. chert_api needs CHERT_FACETIME_TOKEN and CHERT_PROJECT_ID
    (C7.h), delete_room the LiveKit credentials; returns the notes to log."""
    if hangup_mode not in HANGUP_MODES:
        raise UnsupportedMode(f"HANGUP_MODE={hangup_mode!r}: expected one of {', '.join(HANGUP_MODES)}")
    if hangup_mode == "chert_api":
        from challenge.worker.chert import missing_env
        if missing_env():
            raise UnsupportedMode(f"HANGUP_MODE=chert_api needs {' and '.join(missing_env())} in the environment "
                                  "(C7.h); set them or use leave_room / unverified")
    if hangup_mode == "delete_room":
        missing = [k for k in LIVEKIT_ENV if not (os.environ.get(k) or "").strip()]
        if missing:
            raise UnsupportedMode(f"HANGUP_MODE=delete_room needs {' and '.join(missing)} in the environment "
                                  "(the LiveKit room service deletes the room); set them or use leave_room / unverified")
    if reveal_mode not in REVEAL_MODES:
        raise UnsupportedMode(f"REVEAL_MODE={reveal_mode!r}: expected one of {', '.join(REVEAL_MODES)}")
    notes = []
    if reveal_mode == "video":
        notes.append("REVEAL_MODE=video: reveal card/fallback video track (C7.v); any failure plays the audio_only "
                     "check_texts cue only (FALLBACK)")
    if hangup_mode == "delete_room":
        notes.append("HANGUP_MODE=delete_room: after the commit the worker deletes the LiveKit room of a call (never an "
                     "empty warm room) so Chert ends the FaceTime call; a failed delete falls back to leaving the room")
    if hangup_mode == "unverified":
        notes.append("HANGUP_MODE=unverified: hang_up cue before leaving; hang-up not verified (FALLBACK)")
    return notes


def sessions_dir() -> str:
    return os.environ.get("CHALLENGE_SESSIONS_DIR") or os.path.join(
        os.environ.get("RTCOACH_DATA", os.path.join(ROOT, "data")), "tmp", "sessions")


def checkpoint_path(call_id: str, directory: str | None = None) -> str:
    """<dir>/<call_id>.challenge.json with the call id made path-safe (it comes from a participant identity)."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(call_id)).lstrip(".") or "_"
    return os.path.join(directory or sessions_dir(), f"{safe}.challenge.json")


def jsonable(x: Any) -> Any:
    """Plain JSON values: numpy scalars/arrays to Python, non-finite floats to None (Postgres jsonb rejects NaN)."""
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if hasattr(x, "tolist") and not isinstance(x, (str, bytes)):
        return jsonable(x.tolist())
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    return x


def write_json_atomic(path: str, data: dict) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ckpt-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, allow_nan=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


LOCK_SUFFIX = ".lock"                  # <ckpt>.lock: per-call ownership (flock), never deleted (no inode race)
SENT_SUFFIX = ".sent.json"             # <ckpt>.sent.json: digests of reps payloads that got a 2xx ("acked")
CONFLICT_SUFFIX = ".conflict.json"     # <ckpt>.conflict.json: a payload conflict kept for admin review
PERSIST_RETRY_S = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6)   # end(): retries of a checkpoint save that failed


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_ledger(path: str) -> list[dict]:
    """The entries of <ckpt>.sent.json ([] if none). Raises OSError/ValueError on an unreadable ledger."""
    try:
        with open(path + SENT_SUFFIX) as f:
            d = json.load(f)
    except FileNotFoundError:
        return []
    entries = d.get("entries") if isinstance(d, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"{path + SENT_SUFFIX}: no entries list")
    return entries


class CallLock:
    """Ownership of one call's checkpoint: an exclusive non-blocking flock on <ckpt>.lock. The worker holds it from
    accept/adopt until its final commit and save; the reconciler holds it across read, replay and write-back. The
    kernel drops it when the holding process dies, so a free lock means nobody is working on the call."""

    def __init__(self, f: Any):
        self._f = f

    @classmethod
    def try_acquire(cls, ckpt_path: str) -> "CallLock | None":
        """The lock, or None if another open file description holds it (an owner is alive). OSErrors propagate."""
        os.makedirs(os.path.dirname(ckpt_path) or ".", exist_ok=True)
        f = open(ckpt_path + LOCK_SUFFIX, "a")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            return None
        except BaseException:
            f.close()
            raise
        return cls(f)

    @property
    def held(self) -> bool:
        return not self._f.closed

    def release(self) -> None:
        if not self._f.closed:
            self._f.close()                             # closing the description releases the flock


def default_liveness_factory(rng: random.Random, thr: dict):
    from challenge.judge.liveness import LivenessChallenge
    return LivenessChallenge(rng, thr)


def _default_alert(condition: str, detail: str) -> None:
    log.critical("ALERT %s: %s", condition, detail)


def _windows(lc: Any) -> list[tuple[float, float]]:
    """(cue time, current deadline) of every attempt of a LivenessChallenge (C7.l windows(); a FREEZE deadline shrinks)."""
    return [(float(a), float(b)) for a, b in lc.windows()]


class CompetitionCall:
    def __init__(self, call_id: str, line_id: str, handle: str | None, dispatcher: Any, judge_cfg: dict | None = None,
                 clock: Callable[[], float] = time.time, say: Callable[[str, str, bool], Any] | None = None, *,
                 leave: Callable[[str], Any] | None = None,
                 update_challenge_window: Callable[[float, float], Any] | None = None,
                 on_config: Callable[[dict], Any] | None = None,
                 drain: Callable[[], Awaitable[Any]] | None = None,
                 count_s: float | None = None, reveal_s: float | None = None,
                 reveal_mode: str = "audio_only", hangup_mode: str = "unverified",
                 checkpoint_dir: str | None = None, rng: random.Random | None = None,
                 liveness_factory: Callable[[random.Random, dict], Any] | None = None,
                 alert: Callable[[str, str], Any] | None = None,
                 sleep: Callable[[float], Awaitable[Any]] | None = None,
                 commit_deadline_s: float = COMMIT_DEADLINE_S, drain_max_s: float = DRAIN_MAX_S,
                 chert_call_id: str | None = None, chert_end: Any = None,
                 reveal: Callable[[float, Callable[[], Awaitable[dict]]], Awaitable[Any]] | None = None):
        check_modes(hangup_mode, reveal_mode)
        self.call_id, self.line_id, self.handle = str(call_id), str(line_id), handle
        self.dispatcher = dispatcher
        self.judge_cfg = dict(judge_cfg or {})
        self.thr = merged_thresholds(self.judge_cfg)
        self.clock, self._say_fn, self._leave_fn = clock, say, leave
        self._update_window_fn, self._on_config, self._drain = update_challenge_window, on_config, drain
        self.count_s = float(count_s if count_s is not None else DEFAULT_COUNT_S)
        self.reveal_s = float(reveal_s if reveal_s is not None else DEFAULT_REVEAL_S)
        self.reveal_mode, self.hangup_mode = reveal_mode, hangup_mode
        self._reveal_fn = reveal                   # REVEAL_MODE=video (C7.v): async (seconds, wait_committed) -> published?
        self._reveal_task: asyncio.Future | None = None
        self._commit_evt = asyncio.Event()         # set once the dispatcher acknowledged reps_committed
        self.commit_result: dict = {}              # that response's authoritative points/rank, when it carries them
        self.chert_call_id, self._chert_end = chert_call_id, chert_end    # HANGUP_MODE=chert_api (C7.h)
        self.chert_hangup: str | None = None       # acknowledged | failed | no_call_id once the end-call was tried
        self.path = checkpoint_path(self.call_id, checkpoint_dir)
        self.rng = rng or random.SystemRandom()
        self.liveness_factory = liveness_factory or default_liveness_factory
        self.alert = alert or _default_alert
        self._sleep = sleep or asyncio.sleep
        self.commit_deadline_s = float(commit_deadline_s)
        self.drain_max_s = float(drain_max_s)
        self.t0: float | None = None
        self.decision: str | None = None          # accept | reject | error
        self.reason: str | None = None
        self.user_id: str | None = None
        self.power_hour = False
        self.adopted = False                       # continued from an existing checkpoint (worker restart / redispatch)
        self.judge_ready = True                    # False until the pipeline judge has the /calls/start thresholds
        self.reps: list[dict] = []
        self.late_reps: list[dict] = []            # in-window reps that arrived after the commit payload was built
        self.ignored_reps = 0                      # reps after count end, or before the judge had the live thresholds
        self.counting_stopped = False
        self.ended_at: float | None = None
        self.end_reason: str | None = None
        self._payload_built = False
        self.sealed = False                        # rep intake closed: no rep event can arrive any more (payload only then)
        self._commit_deferred = False              # end() found the intake unsealed: seal() + end() commits later
        self.committed = False
        self.sent = {"reps_committed": False, "call_ended": False}
        self.last_error: str | None = None
        self.cues: list[tuple[float, str]] = []   # (call clock, key) of every cue asked for
        self._due: list[tuple[float, str]] = []   # scheduled timeline cues (call clock, key), sorted
        self._last_judge_cue: float | None = None
        self.liveness_result: str | None = None
        self.liveness_first_fire_t: float | None = None
        self.liveness_fires: list[float] = []      # every scheduled fire time (call clock)
        self.lc: Any = None
        self._lc_windows: dict[int, list[tuple[float, float]]] = {}   # id(lc) -> its windows (deadlines can shrink)
        self._old_windows: list[tuple[float, float]] = []            # windows adopted from a checkpoint
        self._pushed: dict[int, list] = {}         # id(lc) -> windows as last passed to update_challenge_window
        self._rescheduled = False
        self._start_done = asyncio.Event()
        self._end_task: asyncio.Future | None = None
        self._bg: set[asyncio.Task] = set()
        self.last_tick_wall: float | None = None   # job health: the controller is ticking
        self.lock: CallLock | None = None          # per-call ownership, held from accept/adopt to the final save
        self.unsaved = False                       # the last checkpoint save failed (end() retries it)
        self.reconcile_meta: dict | None = None    # the reconciler's block of an adopted checkpoint (kept as is)
        self.disowned = False                      # the call lock was let go: this object never writes again
        self.conflict: dict | None = None          # a reps payload conflict found by this run (admin review)

    # ------------------------------------------------------------------ helpers
    def rel(self, wall: float) -> float:
        return float(wall) - float(self.t0)

    def _say(self, key: str | None, urgent: bool = True) -> None:
        if not key:
            return
        text = CUES.get(key)
        if text is None:
            log.warning("call %s: no cue text for key %r (not played)", self.call_id, key)
            return
        self.cues.append((round(self.rel(self.clock()), 3) if self.t0 is not None else 0.0, key))
        if self._say_fn is None:
            return
        try:
            self._say_fn(key, text, urgent)
        except Exception:
            log.exception("call %s: say(%r) failed", self.call_id, key)

    def _leave(self, why: str) -> None:
        log.info("call %s: leaving the room (%s)", self.call_id, why)
        self.cancel_reveal()
        if self._leave_fn is None:
            return
        try:
            self._leave_fn(why)
        except Exception:
            log.exception("call %s: leave failed", self.call_id)

    async def _hangup(self, why: str) -> None:
        """Complete the call: chert_api asks Chert to end it first (retry, then fall back); always leaves the room."""
        if self.hangup_mode == "chert_api" and self.chert_hangup is None:
            if not self.chert_call_id or self._chert_end is None:
                self.chert_hangup = "no_call_id"
                log.error("call %s: chert_api hangup without a Chert call id; leaving the room (unverified)", self.call_id)
            else:
                try:
                    ok = await self._chert_end.end_call(self.chert_call_id, self._sleep)
                except Exception as e:
                    ok = False
                    log.error("call %s: chert end-call error (%s)", self.call_id, type(e).__name__)
                self.chert_hangup = "acknowledged" if ok else "failed"
                if not ok:
                    log.error("call %s: chert end-call failed; falling back to leaving the room (unverified)", self.call_id)
        self._leave(why)

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task:
        t = asyncio.ensure_future(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)
        return t

    def windows(self) -> list[tuple[float, float]]:
        """Every liveness challenge window of this call (call clock)."""
        return list(self._old_windows) + [w for ws in self._lc_windows.values() for w in ws]

    def checkpoint(self) -> dict:
        count_end = self.t0 + self.count_s if self.ended_at is None else min(self.ended_at, self.t0 + self.count_s)
        return jsonable({
            "v": CHECKPOINT_VERSION, "call_id": self.call_id, "line_id": self.line_id, "user_id": self.user_id,
            "t0": self.t0, "started_at": utc_iso(self.t0), "count_s": self.count_s, "reveal_s": self.reveal_s,
            "count_end_at": utc_iso(count_end), "ended_at": utc_iso(self.ended_at) if self.ended_at is not None else None,
            "ended_t": self.ended_at, "end_reason": self.end_reason, "judge_version": JUDGE_VERSION,
            "liveness_enabled": self.liveness_enabled(),
            "liveness_result": self.liveness_result, "liveness_first_fire_s": self.liveness_first_fire_t,
            "liveness": {"result": self.liveness_result, "first_fire_s": self.liveness_first_fire_t,
                         "fires_s": self.liveness_fires, "windows_s": self.windows(), "rescheduled": self._rescheduled},
            "final": self.ended_at is not None, "sealed": self.sealed, "worker_pid": os.getpid(),
            "reps": self.final_reps() if self.ended_at is not None else self.reps,
            "late_reps": self.late_reps, "rep_count": len(self.reps), "ignored_reps": self.ignored_reps,
            "idem_keys": {k: idem_key(self.call_id, k) for k in self.sent},
            "sent": dict(self.sent), "committed": self.committed, "last_error": self.last_error,
            "updated_at": utc_iso(self.clock()), "lock_protocol": LOCK_PROTOCOL,
            **({"reconcile": self.reconcile_meta} if self.reconcile_meta is not None else {}),
        })

    def _write(self) -> bool:
        """Every write runs on the event loop (no awaits inside), so writes never interleave; only the holder of the
        call lock writes. A failure marks the state unsaved (alerted); end() retries it before releasing the lock.
        Once the lock was let go nothing is written (another owner may hold the call): refused, logged, alerted."""
        if self.disowned:
            log.error("call %s: checkpoint write after the call lock was released refused (%d reps, %d late)",
                      self.call_id, len(self.reps), len(self.late_reps))
            self.alert("checkpoint_write_refused", f"call {self.call_id}: state changed after the call lock was "
                                                   f"released; not written ({len(self.late_reps)} late reps)")
            return False
        try:
            write_json_atomic(self.path, self.checkpoint())
            self.unsaved = False
            return True
        except (OSError, ValueError, TypeError) as e:
            self.unsaved = True
            log.error("call %s: checkpoint write to %s failed: %r", self.call_id, self.path, e)
            self.alert("checkpoint_write_failed", f"call {self.call_id}: {e!r}")
            return False

    async def _persist(self) -> bool:
        """Before end() returns: retry a failed checkpoint save with backoff; alert if it still fails."""
        for delay in PERSIST_RETRY_S:
            if not self.unsaved:
                return True
            await self._sleep(delay)
            self._write()
        if self.unsaved:
            log.critical("call %s: checkpoint %s could not be saved; the newest state is only in memory", self.call_id,
                         self.path)
            self.alert("checkpoint_unsaved", f"call {self.call_id}: checkpoint {self.path} not saved after retries")
        return not self.unsaved

    def _late_after_release(self) -> None:
        """A late rep after this run let the call lock go: never written without the lock. Retake it (non-blocking);
        free -> add the late reps to the checkpoint as it is now (whoever wrote it last) and mark it committed:false
        for admin review, then let go again; busy -> another owner works on the call: refused (logged, alerted)."""
        try:
            lk = CallLock.try_acquire(self.path)
        except OSError as e:
            lk, why = None, repr(e)
        else:
            why = "another owner holds the call lock"
        if lk is not None:
            try:
                with open(self.path) as f:
                    d = json.load(f)
                if not isinstance(d, dict) or d.get("call_id") != self.call_id:
                    raise ValueError("the checkpoint is not this call's")
                late = list(d.get("late_reps") or [])
                have = {(r.get("n"), r.get("at")) for r in late if isinstance(r, dict)}
                late += [r for r in self.late_reps if (r["n"], r["at"]) not in have]
                d.update(late_reps=late, committed=False, last_error=self.last_error, updated_at=utc_iso(self.clock()))
                write_json_atomic(self.path, d)
                log.error("call %s: %d late rep(s) added to the checkpoint after the commit; committed:false",
                          self.call_id, len(self.late_reps))
                return
            except (OSError, ValueError, TypeError) as e:
                why = repr(e)
            finally:
                lk.release()
        log.error("call %s: late rep not written after the call lock was released (%s)", self.call_id, why)
        self.alert("checkpoint_write_refused", f"call {self.call_id}: late rep after the call lock was released not "
                                               f"written ({why}); {len(self.late_reps)} late reps in memory")

    def _release_lock(self) -> None:
        if self.lock is not None:
            self.disowned = True
            self.lock.release()
            self.lock = None

    def _load_existing(self) -> dict | None:
        """The checkpoint of this call from an earlier run (worker restart, redispatch), or None. A file that cannot be
        read, or belongs to another call id (path-safe name collision), is moved aside, never overwritten."""
        try:
            with open(self.path) as f:
                d = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            d = None
            why = f"unreadable ({e!r})"
        else:
            why = None if isinstance(d, dict) and d.get("call_id") == self.call_id and d.get("t0") is not None else \
                f"not this call's ({d.get('call_id') if isinstance(d, dict) else type(d).__name__})"
        if why is None:
            return d
        aside = f"{self.path}.aside-{int(self.clock())}"
        os.replace(self.path, aside)
        log.error("call %s: existing checkpoint %s; moved to %s", self.call_id, why, aside)
        self.alert("checkpoint_conflict", f"call {self.call_id}: {why}; moved to {aside}")
        return None

    def _adopt(self, d: dict) -> None:
        self.adopted = True
        self.t0 = float(d["t0"])
        self.user_id = d.get("user_id") or self.user_id
        self.count_s = float(d.get("count_s") or self.count_s)
        self.reveal_s = float(d.get("reveal_s") or self.reveal_s)
        self.reps = list(d.get("reps") or [])
        self.late_reps = list(d.get("late_reps") or [])
        self.ignored_reps = int(d.get("ignored_reps") or 0)
        self.sent.update({k: bool(v) for k, v in (d.get("sent") or {}).items() if k in self.sent})
        self.committed = bool(d.get("committed"))
        self.last_error = d.get("last_error")
        rc = d.get("reconcile")
        self.reconcile_meta = dict(rc) if isinstance(rc, dict) else None   # backoff/late/conflict state survives
        # the call keeps the liveness setting it ran with (a recovery must not void or un-void by today's config);
        # checkpoints from before the flag existed (judge j1/j2) always ran with the challenge on
        on = d.get("liveness_enabled", d.get("judge_version") in ("j1", "j2"))
        if isinstance(on, bool) and on != self.liveness_enabled():
            self.judge_cfg = {**self.judge_cfg, "liveness_enabled": on}
            self.thr = merged_thresholds(self.judge_cfg)
        lv = d.get("liveness") or {}
        self.liveness_result = lv.get("result", d.get("liveness_result"))
        self.liveness_first_fire_t = lv.get("first_fire_s", d.get("liveness_first_fire_s"))
        self.liveness_fires = [float(x) for x in lv.get("fires_s") or []]
        self._old_windows = [(float(a), float(b)) for a, b in lv.get("windows_s") or []]
        self._rescheduled = bool(lv.get("rescheduled"))
        if d.get("final") and d.get("ended_t") is not None:
            self.ended_at, self.end_reason = float(d["ended_t"]), d.get("end_reason")
            self.counting_stopped = self._payload_built = self.sealed = True   # the earlier process is gone
        log.warning("call %s: adopted the existing checkpoint (t0 %s, %d reps, liveness %s, final %s, sent %s)", self.call_id,
                    utc_iso(self.t0), len(self.reps), self.liveness_result, self.ended_at is not None, self.sent)

    # ------------------------------------------------------------------ gatekeeper
    async def start(self) -> bool:
        """POST /calls/start. accept -> welcome (+ power hour), checkpoint, call_started in the background; True.
        reject -> the dispatcher's cue, leave REJECT_LEAVE_S after t0, nothing recorded; False. Dispatcher
        unreachable, an accept without a user, or any error while setting up an accepted call -> fail closed
        (no unattributed or unchecked scoring): ERROR log + alert, leave, False. An existing checkpoint of this call is
        adopted (t0, reps, liveness); if it was already final, its missing events are resent and the worker leaves."""
        if self.decision is not None or self.t0 is not None:
            raise RuntimeError("CompetitionCall.start() called twice")
        self.t0 = self.clock()
        try:
            try:
                r = await self.dispatcher.start_call(self.call_id, self.line_id, self.handle, deadline_s=START_DEADLINE_S)
            except DispatcherError as e:
                self._fail_closed("dispatcher_unreachable", f"dispatcher unreachable at call start ({e})")
                return await self._fail_exit()
            if r.get("decision") != "accept":
                self.decision, self.reason = "reject", str(r.get("reason") or "rejected")
                log.info("call %s: rejected (%s, cue %s)", self.call_id, self.reason, r.get("cue"))
                self._say(r.get("cue"))
                wait = REJECT_LEAVE_S - self.rel(self.clock())
                if wait > 0:
                    await self._sleep(wait)
                self._leave(f"rejected: {self.reason}")
                return False
            if not r.get("user_id"):
                self._fail_closed("accept_without_user", "dispatcher accepted without a user_id")
                return await self._fail_exit()
            try:
                ok = self._accept(r)
            except Exception as e:
                log.exception("call %s: setting up the accepted call failed", self.call_id)
                self._fail_closed("call_setup_failed", f"setup failed after accept ({e!r})")
                ok = False
            if self.decision == "error":
                return await self._fail_exit()
            return ok
        finally:
            self._start_done.set()

    @property
    def start_done(self) -> bool:
        """start() has finished (accepted, rejected or failed closed, its cue and hang-up included)."""
        return self._start_done.is_set()

    def say(self, key: str) -> None:
        """The worker: an urgent cue of an accepted call that is still running (e.g. NO_VIDEO_CUE)."""
        if self.decision == "accept" and self.ended_at is None:
            self._say(key)

    def _fail_closed(self, reason: str, detail: str) -> bool:
        """Mark the call failed closed (logged + alerted); start() then runs _fail_exit (cue, best-effort end, leave)."""
        self._release_lock()
        self.decision, self.reason = "error", reason
        log.error("call %s: %s: not counting this call (fail closed)", self.call_id, detail)
        self.alert(reason, f"call {self.call_id} on {self.line_id}: {detail}")
        return False

    async def _fail_exit(self) -> bool:
        """Fail closed, the caller's side: FAIL_CUE instead of silence; when the dispatcher may hold the line in_call for
        this call (FAIL_ENDED_REASONS, not an adopted call another owner may hold), a best-effort call_ended with 0 reps
        (frees the line; under 30 s with no rep it is not counted toward the cap), bounded by FAIL_ENDED_S; both
        before the hang-up so the end is recorded first. Never raises. Returns False."""
        self._say(FAIL_CUE)
        jobs = [self._sleep(FAIL_CUE_S)]
        if self.reason in FAIL_ENDED_REASONS and not self.adopted:
            jobs.append(self._send_fail_ended())
        await asyncio.gather(*jobs, return_exceptions=True)
        self._leave(self.reason or "fail closed")
        return False

    async def _send_fail_ended(self) -> None:
        now = utc_iso(self.clock())
        body = {"ended_at": now, "count_end_at": now, "rep_count": 0}
        try:
            r = await asyncio.wait_for(self.dispatcher.event("call_ended", self.call_id, body, at=now), FAIL_ENDED_S)
        except asyncio.TimeoutError:
            log.error("call %s: fail closed: call_ended not delivered within %g s", self.call_id, FAIL_ENDED_S)
        except Exception as e:
            log.error("call %s: fail closed: call_ended not delivered (%s)", self.call_id, e)
        else:
            log.info("call %s: fail closed: call_ended sent (%s)", self.call_id, r)

    def _accept(self, r: dict) -> bool:
        self.user_id = r.get("user_id")
        cfg = r.get("config") or {}
        if cfg.get("call_count_s") is not None:
            self.count_s = float(cfg["call_count_s"])
        if cfg.get("call_reveal_s") is not None:
            self.reveal_s = float(cfg["call_reveal_s"])
        live_thr = cfg.get("judge_thresholds")
        if isinstance(live_thr, dict):
            self.judge_cfg = {**self.judge_cfg, **live_thr}     # the live competition_config wins
            self.thr = merged_thresholds(self.judge_cfg)
        self.power_hour = bool(r.get("power_hour_active"))
        # Own the call before reading or writing its checkpoint: a busy lock means the reconciler is committing an
        # earlier run of this call (a live worker would not be asked to start it again): fail closed for this call.
        self.lock = CallLock.try_acquire(self.path)
        if self.lock is None:
            return self._fail_closed("call_locked", "another process (the reconciler) owns this call's checkpoint")
        if os.path.exists(self.path + CONFLICT_SUFFIX):    # quarantined: the stored commit is under admin review
            return self._fail_closed("call_conflict", f"{os.path.basename(self.path)}{CONFLICT_SUFFIX} exists: "
                                                      "the call is under admin review, not resuming it")
        old = self._load_existing()
        if old is not None and isinstance(old.get("reconcile"), dict) and old["reconcile"].get("conflict"):
            return self._fail_closed("call_conflict", "the checkpoint records a payload conflict (reconcile.conflict): "
                                                      "the call is under admin review, not resuming it")
        t_req = self.t0
        if old is not None:
            self._adopt(old)
        self.decision, self.reason = "accept", str(r.get("reason") or "ok")
        if isinstance(live_thr, dict) and self._on_config is not None:
            self.judge_ready = False                        # reps wait until the pipeline judge has these thresholds
            self._on_config(dict(self.judge_cfg))
        if self.ended_at is not None:                       # an earlier run already finished this call
            self._write()
            self._spawn(self.end("resume"))
            self._leave("call already ended")
            return False
        rel = self.rel(t_req)
        log.info("call %s: accepted (user %s, count %gs + reveal %gs, power hour %s%s)", self.call_id, self.user_id,
                 self.count_s, self.reveal_s, self.power_hour, f", resumed at {rel:.1f} s" if self.adopted else "")
        if rel >= self.count_s + self.reveal_s:
            self._write()
            self._spawn(self.end("resume"))
            self._leave("call time already over")
            return False
        self._schedule_timeline(rel)
        self._schedule_liveness(rel)
        self._write()
        if not self.adopted:
            self._say("welcome")
            self._spawn(self._send_started())
        return True

    def judge_applied(self) -> None:
        """The worker: the pipeline judge now runs with the /calls/start thresholds; reps count from here on."""
        if not self.judge_ready:
            self.judge_ready = True
            log.info("call %s: judge thresholds applied; counting", self.call_id)

    async def _send_started(self) -> None:
        try:
            await self.dispatcher.event("call_started", self.call_id, {"line_id": self.line_id}, at=utc_iso(self.t0))
        except DispatcherError as e:
            log.error("call %s: call_started not delivered (%s); the call continues", self.call_id, e)

    def _schedule_timeline(self, rel: float = 0.0) -> None:
        c, rv = self.count_s, self.reveal_s
        due = []
        if self.power_hour:
            due.append((WELCOME_GAP_S, "power_hour"))
        if c > 30:
            due.append((c - 30, "thirty_left"))
        due.append((c, "time_up"))
        hang_t = c + rv - HANG_UP_LEAD_S
        if self.hangup_mode == "unverified":
            due.append((max(c + CHECK_TEXTS_AFTER_S, hang_t), "hang_up"))
        if rv > CHECK_TEXTS_AFTER_S and (self.hangup_mode != "unverified" or hang_t > c + CHECK_TEXTS_AFTER_S):
            due.append((c + CHECK_TEXTS_AFTER_S, "check_texts"))
        self._due = sorted(x for x in due if x[0] >= rel)

    # ------------------------------------------------------------------ liveness
    def _attempt_max(self) -> float:
        """Longest one attempt can run: timeout, plus (FREEZE) the latest go cue and the time to resume after it."""
        gd = self.thr.get("liveness_go_delay_s") or [0, 0]
        go_hi = float(gd[-1]) if isinstance(gd, (list, tuple)) else float(gd)
        return float(self.thr["liveness_timeout_s"]) + go_hi + float(self.thr.get("liveness_go_react_s") or 0)

    def _liveness_latest(self) -> float:
        """Latest first-cue time that leaves room for both attempts (and the retry delay) before the count ends."""
        rd = self.thr.get("liveness_retry_delay_s") or [0, 0]
        retry_hi = float(rd[-1]) if isinstance(rd, (list, tuple)) else float(rd)
        return self.count_s - 2 * self._attempt_max() - retry_hi

    def _new_lc(self, lo: float, hi: float, at: float) -> float:
        lc = self.liveness_factory(self.rng, {**self.judge_cfg, "liveness_window_s": [lo, hi]})
        fire = float(lc.schedule(at))
        self.lc = lc
        self._lc_windows[id(lc)] = []
        for r in self.reps:                         # reps already earned (before a reschedule or a restart) stay earned
            lc.on_rep(float(r["t"]))
        if not any(abs(fire - x) < 1e-6 for x in self.liveness_fires):
            self.liveness_fires.append(fire)
        return fire

    def liveness_enabled(self) -> bool:
        """thr['liveness_enabled'] (default False since j3): off = no challenge is ever scheduled, no challenge cue or
        window, every judged rep counts on its own verdict and the call commits liveness_result 'skipped'."""
        return self.thr.get("liveness_enabled") is True

    def _schedule_liveness(self, rel: float = 0.0) -> None:
        if not self.liveness_enabled():
            self.liveness_result, self.lc = "skipped", None    # also overrides a result adopted from a checkpoint
            return
        if self.liveness_result is not None:
            return
        latest = self._liveness_latest()
        try:
            if self.liveness_first_fire_t is None:
                w0, w1 = (float(x) for x in self.thr["liveness_window_s"])
                hi = min(w1, latest)
                if hi < 0:
                    raise ValueError(f"count_s {self.count_s} leaves no room for a liveness challenge (needs "
                                     f"{self.count_s - latest:.1f} s)")
                self.liveness_first_fire_t = self._new_lc(min(w0, hi), hi, 0.0)
                log.info("call %s: liveness challenge at %.1f s", self.call_id, self.liveness_first_fire_t)
            else:                                               # resumed: the original time if still ahead, else one reschedule
                ahead = self.liveness_first_fire_t - rel
                if ahead >= 0 and not self.liveness_fires[1:]:
                    self._new_lc(ahead, ahead, rel)
                elif not self._rescheduled and latest - rel >= RESCHEDULE_MIN_S:
                    self._rescheduled = True
                    self._new_lc(RESCHEDULE_MIN_S, latest - rel, rel)
                else:
                    self.liveness_result = self._no_pass_result()   # unresolved and no time left for a challenge
                log.info("call %s: liveness resumed (fires %s, result %s)", self.call_id, self.liveness_fires, self.liveness_result)
        except Exception as e:
            self._lc_fail("schedule", e)

    def _lc_fail(self, where: str, e: Exception) -> None:
        """Fail closed: a liveness error means no challenge can vouch for the reps -> liveness_result fail."""
        log.error("call %s: liveness %s failed (%r): liveness_result fail (fail closed)", self.call_id, where, e,
                  exc_info=(type(e), e, e.__traceback__))
        self.alert("liveness_error", f"call {self.call_id}: {where}: {e!r}")
        self.liveness_result, self.lc = "fail", None
        self._write()

    def _no_pass_result(self) -> str:
        """No challenge passed and none can run any more: 'skipped' only if no rep was earned, else 'fail' (C7.l)."""
        return "fail" if self.reps else "skipped"

    def _push_windows(self) -> bool:
        """After every start()/poll(): each window that is new or whose deadline moved (FREEZE go) goes to
        update_challenge_window (the judge replaces the window starting at that time). Returns True if any changed."""
        lc = self.lc
        wins = _windows(lc)
        self._lc_windows[id(lc)] = wins
        old = self._pushed.get(id(lc), [])
        changed = False
        for i, (a, b) in enumerate(wins):
            if i < len(old) and old[i] == (a, b):
                continue
            changed = True
            if self._update_window_fn is not None:
                try:
                    self._update_window_fn(self.t0 + a, self.t0 + b)
                except Exception:
                    log.exception("call %s: update_challenge_window failed", self.call_id)
        self._pushed[id(lc)] = list(wins)
        return changed

    def _in_window(self, rel: float) -> bool:
        return any(a <= rel <= b for a, b in self.windows())

    def _liveness_tick(self, rel: float) -> None:
        """Before count end: start when due, poll while open. After count end only an attempt already started is
        polled to its result (it runs into the reveal); one never started is settled at count end."""
        lc = self.lc
        if lc is None or self.liveness_result is not None:
            return
        try:
            if not lc.started:
                if rel < self.count_s and lc.due(rel):
                    self._say(lc.start(rel))
                    self._push_windows()
                    self._write()
                return
            status, cue = lc.poll(rel)
        except Exception as e:
            self._lc_fail("poll", e)
            return
        self._say(cue)                                          # incl. challenge_go (FREEZE go / release) and the retry cue
        changed = self._push_windows()
        if status in ("pass", "fail"):
            self.liveness_result = status
            log.info("call %s: liveness %s at %.1f s", self.call_id, status, rel)
            self._write()
        elif status == "skipped":
            self._on_skipped(rel)
        elif changed:
            self._write()                                       # a retry opened or a deadline moved

    def _on_skipped(self, rel: float) -> None:
        room = self._liveness_latest() - rel
        if not self._rescheduled and room >= RESCHEDULE_MIN_S:
            self._rescheduled = True
            try:
                fire = self._new_lc(RESCHEDULE_MIN_S, room, rel)
            except Exception as e:
                self._lc_fail("reschedule", e)
                return
            log.info("call %s: liveness skipped (nobody in frame) at %.1f s; rescheduled at %.1f s", self.call_id, rel, fire)
        else:
            self.liveness_result = self._no_pass_result()
            log.info("call %s: liveness skipped at %.1f s; no reschedule left (result %s)", self.call_id, rel, self.liveness_result)
        self._write()

    def _settle_liveness(self, rel_end: float) -> None:
        if self.liveness_result is not None:
            return
        lc = self.lc
        if lc is None:
            self.liveness_result = self._no_pass_result()
            self._write()
            return
        try:
            res = lc.finish(rel_end)
        except Exception as e:
            self._lc_fail("finish", e)
            return
        if res not in LIVENESS_RESULTS:
            self._lc_fail("finish", ValueError(f"finish() returned {res!r}"))
            return
        self.liveness_result = "fail" if res == "skipped" and self.reps else res   # reps recorded: never 'skipped'

        self._write()

    # ------------------------------------------------------------------ frames and reps
    def on_frame(self, f: Any) -> None:
        """A FrameObs with t = the frame's wall time (unmirrored landmarks) for the open liveness challenge."""
        if self.decision != "accept" or self.ended_at is not None or self.lc is None or self.liveness_result is not None:
            return
        try:
            self.lc.on_frame(dataclasses.replace(f, t=self.rel(f.t)))
        except Exception as e:
            self._lc_fail("on_frame", e)                   # its state can no longer be trusted: no later pass

    def on_rep(self, event: dict, t: float | None = None) -> dict | None:
        """A perception rep event (with the judge's valid/reject_reasons/metrics/cue/in_challenge) fired at wall time
        t (None = now). It counts by its own timestamp: fired before count end -> recorded, even when it is delivered
        after tick(count_s) or while end() drains; once the intake is sealed (cannot happen with a working drain) it goes to late_reps and the call
        stays committed:false. Must run on the event loop (the worker marshals it). Returns the stored rep."""
        if self.decision != "accept":
            return None
        wall = self.clock() if t is None else float(t)
        rel = self.rel(wall)
        if rel >= self.count_s or rel < 0 or (self.ended_at is not None and wall > self.ended_at):
            self.ignored_reps += 1
            log.info("call %s: rep at %.2f s outside the count window ignored", self.call_id, rel)
            return None
        if not self.judge_ready:
            self.ignored_reps += 1
            log.warning("call %s: rep at %.2f s judged before the live thresholds were applied; ignored", self.call_id, rel)
            return None
        judged = "valid" in event
        valid = event.get("valid") is True
        reasons = [str(x) for x in (event.get("reject_reasons") or [])]
        if not judged:
            reasons = ["not_judged"]
        in_ch = bool(event.get("in_challenge")) or self._in_window(rel)
        rep = {"n": len(self.reps) + len(self.late_reps) + 1, "t": round(rel, 3), "at": utc_iso(wall), "valid": valid,
               "reject_reasons": reasons, "faults": [], "in_challenge": in_ch,
               "judge_version": event.get("judge_version") or JUDGE_VERSION}
        metrics = event.get("metrics") or {}
        rep.update({k: metrics.get(k) for k in C2_METRIC_KEYS if k in metrics})
        rep = jsonable(rep)
        if self.sealed:                                 # cannot happen with a working drain(); kept, never dropped
            self.late_reps.append(rep)
            self.committed = False
            self.last_error = f"rep at {rel:.2f} s arrived after the commit payload was built"
            log.error("call %s: %s; committed:false", self.call_id, self.last_error)
            self.alert("late_rep", f"call {self.call_id}: {self.last_error}")
            if self.disowned:
                self._late_after_release()
            else:
                self._write()
            return rep
        self.reps.append(rep)
        if self.lc is not None and self.liveness_result is None:
            try:
                self.lc.on_rep(rel)                             # reps earned: the call can no longer end 'skipped'
            except Exception as e:
                self._lc_fail("on_rep", e)
        self._write()
        cue = event.get("cue")
        if cue and not valid and not in_ch and not self.counting_stopped:
            self._judge_cue(cue, rel)
        return rep

    def _judge_cue(self, key: str, rel: float) -> None:
        if key not in JUDGE_CUE_KEYS:
            log.warning("call %s: judge cue %r is not a corrective cue; not played", self.call_id, key)
            return
        if self._challenge_active():
            return                                       # the challenge cue has the floor
        gap = float(self.thr.get("cue_min_gap_s", 4))
        if self._last_judge_cue is not None and rel - self._last_judge_cue < gap:
            return
        self._last_judge_cue = rel
        self._say(key, urgent=False)

    def final_reps(self) -> list[dict]:
        """The reps as committed: in_challenge recomputed from the final windows (a FREEZE deadline that shrank after
        the judge flagged a rep no longer covers it); without a passed challenge every valid rep is marked
        liveness_fail (C7.l: earned reps never count without a pass)."""
        mark = self.liveness_enabled() and self.liveness_result != "pass"
        out = []
        for r in self.reps:
            r = dict(r, reject_reasons=list(r["reject_reasons"]))
            r["in_challenge"] = self._in_window(r["t"])
            if mark and r["valid"]:
                r["valid"] = False
                if "liveness_fail" not in r["reject_reasons"]:
                    r["reject_reasons"].append("liveness_fail")
            out.append(r)
        return out

    # ------------------------------------------------------------------ clock
    def tick(self, now: float | None = None) -> bool:
        """Timeline cues, counting stop and liveness at wall time `now`. Returns True once the call is due to end
        (count_s + reveal_s); run() then ends it."""
        if self.decision != "accept" or self.ended_at is not None:
            return False
        wall = self.clock() if now is None else now
        self.last_tick_wall = wall
        rel = self.rel(wall)
        self._liveness_tick(rel)
        if rel >= self.count_s and not self.counting_stopped:
            self.counting_stopped = True
            if self.lc is None or not self.lc.started:
                self._settle_liveness(self.count_s)
            log.info("call %s: count over (%d reps so far, liveness %s)", self.call_id, len(self.reps), self.liveness_result)
            self._start_reveal()
        due = [(t, k) for t, k in self._due if t <= rel]
        if due:
            t_last, key = due[-1]
            if key in DEFERRABLE_CUES and self._challenge_active() and rel - t_last <= DEFER_MAX_S:
                return False                             # the challenge has the floor; retried next tick
            self._due = [(t, k) for t, k in self._due if t > rel]
            if len(due) > 1:
                log.info("call %s: cues %s overdue; playing only %s", self.call_id, [k for _, k in due[:-1]], key)
            if key in DEFERRABLE_CUES and rel - t_last > DEFER_MAX_S:
                log.info("call %s: cue %s dropped (%.1f s late)", self.call_id, key, rel - t_last)
            else:
                self._say(key)
        return rel >= self.count_s + self.reveal_s

    def _start_reveal(self) -> None:
        """REVEAL_MODE=video: run the worker's reveal hook as a dedicated task (cancelled by cancel_reveal); an error
        never touches the timeline."""
        if self.reveal_mode != "video" or self._reveal_fn is None or self.reveal_s <= 0 or self._reveal_task is not None:
            return

        async def _wait() -> dict:
            await self._commit_evt.wait()
            return self.commit_result

        async def _go() -> None:
            try:
                await self._reveal_fn(self.reveal_s, _wait)
            except Exception as e:
                log.warning("call %s: reveal video failed (%r); audio_only", self.call_id, e)
        self._reveal_task = asyncio.ensure_future(_go())

    def cancel_reveal(self) -> None:
        """Cancel the reveal task (end, leave, room disconnect, worker shutdown); never awaits."""
        t, self._reveal_task = self._reveal_task, None
        if t is not None and not t.done():
            t.cancel()

    def _challenge_active(self) -> bool:
        lc = self.lc
        return lc is not None and self.liveness_result is None and bool(getattr(lc, "active", False))

    async def run(self, interval: float = 0.25) -> None:
        """Tick until the call is due to end; then start the commit in the background and leave at once (the room is
        left at count_s + reveal_s whatever the dispatcher does)."""
        while self.decision == "accept" and self.ended_at is None and self._end_task is None:
            if self.tick():
                self._spawn(self.end("complete"))
                await self._hangup("call complete")
                return
            await self._sleep(interval)

    # ------------------------------------------------------------------ end
    async def end(self, reason: str = "end") -> dict:
        """Idempotent; concurrent callers share one run, which is shielded from their cancellation. A run that found
        the rep intake unsealed sends nothing; once seal() was called the next end() commits."""
        self.cancel_reveal()
        if self._end_task is None or (self._end_task.done() and self._commit_deferred and self.sealed):
            self._commit_deferred = False
            self._end_task = asyncio.ensure_future(self._end(reason))
            self._end_task.add_done_callback(self._end_done)
        return await asyncio.shield(self._end_task)

    def _end_done(self, t: asyncio.Future) -> None:
        """The end task has finished. The normal path released the lock itself after its final save; a deferred
        commit keeps it for seal() + end(). One that was cancelled or raised (possibly mid-drain, intake still open)
        first seals the intake (a rep still queued becomes a late rep: kept, the call stays committed:false for admin
        review), then saves; only a saved, sealed state lets the lock go. Runs on the event loop in one step, so no
        rep can be written in between. A failed save keeps the lock until the process exits (the kernel drops it)."""
        if self.lock is None or not (t.cancelled() or t.exception() is not None):
            return
        if not self.sealed:
            self.sealed = True
            self.last_error = "end() stopped before the rep intake was drained: intake sealed, later reps are late"
            log.error("call %s: %s", self.call_id, self.last_error)
            self.alert("commit_pending", f"call {self.call_id}: {self.last_error}; checkpoint {self.path}")
        self._write()
        if self.unsaved:
            log.critical("call %s: end() stopped and the checkpoint could not be saved; the call lock stays held "
                         "until this process exits", self.call_id)
            self.alert("checkpoint_unsaved", f"call {self.call_id}: {self.path} not saved; call lock kept")
            return
        self._release_lock()

    def seal(self) -> None:
        """The worker: no rep event can arrive any more (the perception feed thread has exited)."""
        if not self.sealed:
            self.sealed = True
            log.info("call %s: rep intake sealed", self.call_id)
            if self.decision == "accept":
                self._write()

    @property
    def commit_deferred(self) -> bool:
        """end() ran but found the rep intake unsealed: nothing sent yet; seal() then end() commits."""
        return self._commit_deferred and not self.ending

    @property
    def ending(self) -> bool:
        """end() is running (the dispatcher client must stay open until it finishes)."""
        return self._end_task is not None and not self._end_task.done()

    def _proven(self, body: dict, r: dict) -> bool:
        """A 2xx for reps_committed. Fresh (not already/duplicate): this payload is stored; its digest goes to the
        ledger as acked. already/duplicate: the dispatcher kept an earlier commit, which counts only if the ledger
        holds an acked digest equal to this payload's; anything else is a payload conflict (admin review)."""
        dg = payload_digest(body)
        try:
            acked = [e for e in read_ledger(self.path) if isinstance(e, dict) and e.get("acked")]
        except (OSError, ValueError) as e:
            acked = None
            log.error("call %s: payload ledger unreadable: %r", self.call_id, e)
        if r.get("already") or r.get("duplicate"):
            if acked is not None and any(e.get("digest") == dg for e in acked):
                log.info("call %s: reps_committed already stored with this exact payload (acked earlier)", self.call_id)
                return True
            self._record_conflict("the dispatcher already had a commit this run cannot prove equal", body, r, acked)
            return False
        if acked and any(e.get("digest") != dg for e in acked):
            self._record_conflict("a fresh commit after a different acked payload", body, r, acked)
            return False
        if acked is not None:
            try:
                write_json_atomic(self.path + SENT_SUFFIX, {"call_id": self.call_id, "entries": acked + [
                    {"digest": dg, "acked": True, "rep_count": len(body.get("reps") or []), "at_t": self.clock()}]})
            except (OSError, ValueError, TypeError) as e:   # stored all the same: sent.reps_committed covers a resend
                log.error("call %s: acked digest not recorded in the ledger: %r", self.call_id, e)
                self.alert("checkpoint_write_failed", f"call {self.call_id}: payload ledger: {e!r}")
        return True

    def _record_conflict(self, reason: str, body: dict, r: dict, acked: list[dict] | None) -> None:
        """Nothing is marked sent or committed; <ckpt>.conflict.json keeps this run's checkpoint, the payload digest
        and the ledger; one commit_conflict alert. Adoption then refuses the call until an admin resolves it."""
        self.conflict = {"reason": reason, "digest": payload_digest(body), "rep_count": len(body.get("reps") or []),
                         "response": r, "ledger": acked if acked is not None else "unreadable"}
        self.last_error = f"reps_committed: payload conflict ({reason})"
        try:
            write_json_atomic(self.path + CONFLICT_SUFFIX, jsonable({
                "call_id": self.call_id, "at_t": self.clock(), "conflict": self.conflict,
                "ledger": self.conflict["ledger"], "replayed_checkpoint": self.checkpoint()}))
        except (OSError, ValueError, TypeError) as e:
            log.error("call %s: conflict record not written: %r", self.call_id, e)
        log.error("call %s: reps payload conflict (%s); left committed:false for admin review", self.call_id, reason)
        self.alert("commit_conflict", f"call {self.call_id}: {reason}; both versions kept "
                                      f"({os.path.basename(self.path)}{CONFLICT_SUFFIX})")

    async def _end(self, reason: str) -> dict:
        if self.t0 is not None and not self._start_done.is_set():
            try:
                await asyncio.wait_for(self._start_done.wait(), START_DEADLINE_S + max(REJECT_LEAVE_S, FAIL_CUE_S + FAIL_ENDED_S) + 1)
            except asyncio.TimeoutError:
                log.error("call %s: end(%s) while /calls/start is still pending; nothing recorded", self.call_id, reason)
        if self.decision != "accept":
            return {"recorded": False, "committed": False, "decision": self.decision}
        if self.ended_at is None:
            self.ended_at, self.end_reason = self.clock(), reason
            self.counting_stopped = True
            self._write()
        if not self.sealed:
            # Stop the feed, let the frame in flight finish and its rep events reach on_rep; only then is the payload
            # complete. drain() returns True once no rep event can arrive any more.
            ok = self._drain is None
            if not ok:
                try:
                    ok = await asyncio.wait_for(self._drain(), self.drain_max_s) is True
                except asyncio.TimeoutError:
                    log.error("call %s: rep intake not sealed within %g s", self.call_id, self.drain_max_s)
                except Exception as e:
                    log.exception("call %s: drain before commit failed: %r", self.call_id, e)
            self.sealed = self.sealed or ok
        self._settle_liveness(min(self.rel(self.ended_at), self.count_s + self.reveal_s))
        if not self.sealed:
            self._commit_deferred = True
            self.last_error = "rep intake not sealed (perception feed busy): commit deferred until seal()"
            self._write()
            log.error("call %s: %s; checkpoint %s kept with committed:false", self.call_id, self.last_error, self.path)
            self.alert("commit_pending", f"call {self.call_id}: {self.last_error}; checkpoint {self.path}")
            persisted = await self._persist()             # the lock stays held: seal() + end() commit later
            return {"recorded": True, "committed": False, "reps": len(self.reps), "liveness_result": self.liveness_result,
                    "persisted": persisted}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.commit_deadline_s
        rel_end = min(self.rel(self.ended_at), self.count_s)
        for kind in ("reps_committed", "call_ended"):
            if self.sent[kind]:
                continue
            if kind == "call_ended" and not self.sent["reps_committed"]:
                log.error("call %s: reps_committed not acknowledged; call_ended left to the reconciler", self.call_id)
                break
            if kind == "reps_committed":
                reps = self.final_reps()
                body = {"started_at": utc_iso(self.t0), "ended_at": utc_iso(self.ended_at),
                        "liveness_result": self.liveness_result, "judge_version": JUDGE_VERSION, "reps": reps}
                self._payload_built = True
            else:
                body = {"ended_at": utc_iso(self.ended_at), "count_end_at": utc_iso(self.t0 + rel_end),
                        "rep_count": len(self.reps)}
            self._write()                                     # local JSON first: the reconciler replays it if we die here
            left = deadline - loop.time()
            try:
                if left <= 0:
                    raise asyncio.TimeoutError()
                r = await asyncio.wait_for(self.dispatcher.event(kind, self.call_id, body, at=utc_iso(self.ended_at)), left)
            except asyncio.TimeoutError:
                self.last_error = f"{kind}: commit deadline ({self.commit_deadline_s:g} s) passed"
                log.error("call %s: %s; checkpoint %s kept with committed:false", self.call_id, self.last_error, self.path)
            except DispatcherError as e:
                self.last_error = f"{kind}: {e}"
                log.error("call %s: %s not delivered (%s); checkpoint %s kept with committed:false", self.call_id, kind, e, self.path)
            except Exception as e:
                self.last_error = f"{kind}: {e!r}"
                log.exception("call %s: %s failed; checkpoint %s kept with committed:false", self.call_id, kind, self.path)
            else:
                if isinstance(r, dict) and not r.get("ok") and r.get("reason") == "already":
                    r = dict(r, ok=True, already=True)       # ch_commit_reps' second answer
                if not isinstance(r, dict) or not r.get("ok"):
                    reason = r.get("reason") if isinstance(r, dict) else r
                    self.last_error = f"{kind}: refused ({reason})"
                    log.error("call %s: dispatcher refused %s (%s); checkpoint kept with committed:false", self.call_id, kind, reason)
                elif kind != "reps_committed" or self._proven(body, r):
                    self.sent[kind] = True
                    if kind == "reps_committed":
                        self.commit_result = {k: r.get(k) for k in ("points", "rank") if r.get(k) is not None}
                        self._commit_evt.set()
            self._write()
            if not self.sent[kind]:
                break
        self.committed = all(self.sent.values()) and not self.late_reps
        self._write()
        if not self.committed:
            self.alert("commit_pending", f"call {self.call_id}: {self.last_error}; checkpoint {self.path}")
        log.info("call %s: ended (%s): %d reps, liveness %s, committed %s", self.call_id, self.end_reason, len(self.reps),
                 self.liveness_result, self.committed)
        persisted = await self._persist()
        self._release_lock()                              # final commit and save done: the reconciler may take over
        return {"recorded": True, "committed": self.committed, "reps": len(self.reps), "liveness_result": self.liveness_result,
                "persisted": persisted}
