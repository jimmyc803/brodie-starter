"""Checkpoint reconciler (CONTRACTS C6, C7 checkpoint rule, C7.k; SPEC section 4 failure handling).

    python -m scripts.reconcile_sessions [--once] [--dir data/tmp/sessions] [--stale-s 375] [--interval-s 60]

Commits the competition-call checkpoints the worker could not: every `<call_id>.challenge.json` with committed:false
that is replayable gets the missing `reps_committed` and then `call_ended` events, sent by the controller itself
(challenge.worker.controller.CompetitionCall adopts the checkpoint and runs its own end()), so the payload, the
liveness rule (C7.l: without a passed challenge every valid rep is committed liveness_fail) and the idem keys
(`<call_id>:<kind>`) are exactly the worker's.

Ownership (fencing): every call has a per-call lock, an exclusive flock on `<ckpt>.lock` (controller.CallLock). The
worker takes it non-blocking on accept/adopt and holds it until its final commit and save; the kernel drops it when
the worker dies. The reconciler takes the same lock non-blocking: busy -> an owner is alive, the call is skipped;
acquired -> nobody else works on the call, and the reconciler holds it across the read (JSON + fstat from one
descriptor), the replay (network included) and the write-back. A worker restarted into a call the reconciler holds
fails closed for that call only. Nobody else can write while the lock is held, so there is no compare-and-swap.
The lock is let go only once the replay's commit task has finished: a cancelled replay cancels that task and waits
for it (bounded); if it is still running the lock is released when it ends. The worker likewise releases only after
its final commit and save (or when its end task was cancelled or raised).

Legacy checkpoints (no "lock_protocol": 1, written by a worker from before the per-call lock, which never took it):
a free lock proves nothing, so one is replayed only when, in addition, the file has not been written for
RECONCILE_LEGACY_GRACE_S (default 900 s, far beyond count + reveal + commit) and the worker_pid it records is not
alive on this host. Deploy by restarting brodie-worker (no rolling overlap; docs/challenge/RUNBOOK.md).

--once runs under a hard deadline, RECONCILE_MAX_RUN_S (default 50 s, below the 60 s timer): on expiry a watchdog
thread logs, alerts reconciler_deadline and exits with code 3, so the kernel drops every call lock the run held (a
send that keeps suppressing cancellation cannot keep a call locked). The unit's TimeoutStartSec is the second backstop.

Which checkpoints are replayed (lock acquired):
  * committed:true -> never touched again (a duplicate run is a no-op).
  * sealed (no rep can arrive any more) and final (end() ran) -> replayed.
  * unsealed, or sealed without an end -> replayed once the call started more than --stale-s ago (call max length
    195 + 180; a worker redispatched onto the call may resume it before that). A call that never reached end() gets
    ended_at = its last rep's time (connected_at + count_s + reveal_s if none).
  * late_reps (a rep after the payload was sealed) are never amended: the missing events are sent from the sealed
    reps, the file stays committed:false, and a commit_pending alert goes out once for admin review.

`already` / duplicate (the dispatcher already stored a commit for the call, or for the idem key) is success only on
proof that the stored payload is this one: `<ckpt>.sent.json` holds the digest of every reps payload the worker or a
replay sent and got a fresh 2xx for ("acked", recorded only AFTER the answer). The rule lives in the controller, so
worker and replay apply the same one. Anything else (no acked digest, or a different one) is a payload conflict:
nothing is marked sent or committed, `<ckpt>.conflict.json` keeps the checkpoint and the ledger, one commit_conflict
alert goes out, and neither the reconciler nor an adopting worker touches the call again (admin review). (The dispatcher keeps no payload digest: ch_event_log stores only the result and ch_commit_reps
answers `already` with valid_reps/points, which /calls/event does not forward.)

A failed replay backs off exponentially (--backoff-s doubling up to --backoff-max-s); the state is kept in the
checkpoint's `reconcile` block, so it survives the systemd timer's one-shot runs. Files are never deleted or moved
(the controller has no done/ convention). One run at a time per directory (flock on `.reconcile.lock`).
Alerts: CRITICAL log plus POST /internal/alert (X-Brodie-Token) on the dispatcher. Logs carry call ids only, never
handles or media. Exit: 0 (pending calls are reported by alerts), 2 on bad usage / missing DISPATCHER_URL or TOKEN / bad
RECONCILE_* values, 3 when the --once deadline expired.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import glob
import json
import logging
import os
import sys
import threading
import time
from typing import Any, Callable

import httpx

from challenge.worker.client import DispatcherClient
from challenge.worker.controller import (COMMIT_DEADLINE_S, CONFLICT_SUFFIX, DEFAULT_COUNT_S, DEFAULT_REVEAL_S,
                                         LOCK_PROTOCOL, SENT_SUFFIX, CallLock, CompetitionCall, checkpoint_path,
                                         payload_digest, read_ledger, sessions_dir, write_json_atomic)

log = logging.getLogger("challenge.reconciler")

STALE_S = 375.0          # call max length (count 180 + reveal 15) + 180
BACKOFF_S = 60.0
BACKOFF_MAX_S = 3600.0
LEGACY_GRACE_S = 900.0   # a checkpoint without lock_protocol (pre-lock worker) waits this long after its last write
CANCEL_JOIN_S = 5.0      # a cancelled replay waits this long for its commit task to stop before letting go
MAX_RUN_S = 50.0         # --once: hard process deadline (below the 60 s timer); on expiry os._exit(3) drops every flock
EXIT_DEADLINE = 3
LOCK_NAME = ".reconcile.lock"
SUFFIX = ".challenge.json"
__all__ = ["Reconciler", "HttpAlert", "log_alert", "read_snapshot", "payload_digest", "read_ledger", "SENT_SUFFIX",
           "CONFLICT_SUFFIX", "LOCK_NAME", "SUFFIX"]


def _env_seconds(name: str, default: float, positive: bool = False) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        v = float("nan")
    if not (v > 0 if positive else v >= 0) or v == float("inf"):
        raise ValueError(f"{name}={raw!r}: expected seconds {'> 0' if positive else '>= 0'}")
    return v


def legacy_grace_from_env() -> float:
    return _env_seconds("RECONCILE_LEGACY_GRACE_S", LEGACY_GRACE_S)


def max_run_from_env() -> float:
    return _env_seconds("RECONCILE_MAX_RUN_S", MAX_RUN_S, positive=True)


def arm_deadline(seconds: float, alert: Callable[[str, str], Any]) -> threading.Timer:
    """--once backstop: a send that keeps suppressing cancellation would hold its call lock for ever. After `seconds`
    this thread (independent of the event loop) logs, alerts and ends the process with os._exit(EXIT_DEADLINE); the
    kernel then drops every flock it held. cancel() the returned timer when the run finishes in time."""
    def expire() -> None:
        msg = f"reconcile run still going after {seconds:g} s (RECONCILE_MAX_RUN_S); exiting so its call locks drop"
        try:
            log.critical("%s", msg)
            alert("reconciler_deadline", msg)
        except BaseException:                         # the exit must happen whatever the alert does
            pass
        finally:
            os._exit(EXIT_DEADLINE)

    t = threading.Timer(seconds, expire)
    t.daemon = True
    t.start()
    return t


def pid_alive(pid: Any) -> bool:
    """Whether a process with this pid exists on this host (unknown / permission denied -> alive: conservative)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


# ------------------------------------------------------------------ alerts
class HttpAlert:
    """controller-style alert(condition, detail): CRITICAL log, then POST /internal/alert (best effort, logged)."""

    def __init__(self, base_url: str, token: str, timeout: float = 3.0, transport: httpx.BaseTransport | None = None):
        self.base_url, self.token, self.timeout, self.transport = base_url.rstrip("/"), token, timeout, transport

    def __call__(self, condition: str, detail: str) -> None:
        log.critical("ALERT %s: %s", condition, detail)
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport,
                              headers={"X-Brodie-Token": self.token}) as c:
                r = c.post("/internal/alert", json={"kind": condition, "component": "reconciler",
                                                    "message": f"{condition}: {detail}"[:2000]})
            if r.status_code >= 300:
                log.error("alert %s not delivered: HTTP %d", condition, r.status_code)
        except httpx.HTTPError as e:
            log.error("alert %s not delivered: %s: %s", condition, type(e).__name__, e)


def log_alert(condition: str, detail: str) -> None:
    log.critical("ALERT %s: %s", condition, detail)


# ------------------------------------------------------------------ checkpoint reads
def read_snapshot(path: str) -> tuple[bytes, os.stat_result] | None:
    """The checkpoint's bytes and fstat metadata from ONE open file descriptor (never two versions); None if gone."""
    try:
        with open(path, "rb") as f:
            return f.read(), os.fstat(f.fileno())
    except FileNotFoundError:
        return None


# ------------------------------------------------------------------ reconciler
def _missing(d: dict) -> bool:
    sent = d.get("sent") or {}
    return not (sent.get("reps_committed") and sent.get("call_ended"))


class Reconciler:
    def __init__(self, client: Any, directory: str | None = None, *, stale_s: float = STALE_S,
                 backoff_s: float = BACKOFF_S, backoff_max_s: float = BACKOFF_MAX_S,
                 clock: Callable[[], float] = time.time, alert: Callable[[str, str], Any] = log_alert,
                 commit_deadline_s: float = COMMIT_DEADLINE_S, legacy_grace_s: float | None = None,
                 cancel_join_s: float = CANCEL_JOIN_S, wall: Callable[[], float] = time.time):
        self.client = client
        self.legacy_grace_s = legacy_grace_from_env() if legacy_grace_s is None else float(legacy_grace_s)
        self.cancel_join_s = float(cancel_join_s)
        self.wall = wall                                  # real time, for file mtimes
        self.dir = directory or sessions_dir()
        self.stale_s = float(stale_s)
        self.backoff_s, self.backoff_max_s = float(backoff_s), float(backoff_max_s)
        self.clock, self.alert = clock, alert
        self.commit_deadline_s = float(commit_deadline_s)
        self._stat: dict[str, os.stat_result] = {}

    # -------------------------------------------------- selection
    def _load(self, path: str) -> dict | None:
        """The checkpoint at `path` (one descriptor), validated; None if gone or not a call checkpoint of this name.
        The fstat of that same descriptor is kept in self._stat[path]."""
        try:
            snap = read_snapshot(path)
        except OSError as e:
            log.error("checkpoint %s unreadable (%r); left as is", path, e)
            return None
        if snap is None:
            return None
        try:
            d = json.loads(snap[0])
        except ValueError as e:
            log.error("checkpoint %s unreadable (%r); left as is", path, e)
            return None
        try:
            ok = isinstance(d, dict) and bool(d.get("call_id")) and bool(d.get("line_id")) and \
                isinstance(d.get("reps") or [], list) and float(d["t0"]) == float(d["t0"])
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            log.error("checkpoint %s is not a call checkpoint; left as is", path)
            return None
        if os.path.abspath(checkpoint_path(d["call_id"], self.dir)) != os.path.abspath(path):
            log.error("checkpoint %s names call %s, whose checkpoint lives elsewhere; left as is", path, d["call_id"])
            return None
        self._stat[path] = snap[1]
        return d

    def _settled(self, path: str, d: dict, now: float) -> str | None:
        """Reasons that need no lock (nothing to do, or admin review)."""
        if d.get("committed"):
            return "committed"
        rc = d.get("reconcile") or {}
        if rc.get("conflict") or os.path.exists(path + CONFLICT_SUFFIX):
            return "payload conflict (admin review)"
        if d.get("late_reps") and rc.get("late_alerted") and not _missing(d):
            return "late_reps (admin review)"
        if float(rc.get("next_try_t") or 0) > now:
            return "backoff"
        return None

    def _why_not(self, path: str, d: dict, now: float) -> str | None:
        """With the call lock held (no owner alive): None if this checkpoint is to be replayed now, else why not."""
        why = self._settled(path, d, now)
        if why is not None:
            return why
        if d.get("lock_protocol") != LOCK_PROTOCOL:
            # Written by a worker from before the per-call lock: a free lock proves nothing about it. Only once the
            # file has not changed for the legacy grace and its recorded pid is gone on this host.
            age = self.wall() - self._stat[path].st_mtime
            if age <= self.legacy_grace_s:
                return f"legacy checkpoint written {age:.0f} s ago (grace {self.legacy_grace_s:g} s)"
            if d.get("worker_pid") is not None and pid_alive(d.get("worker_pid")):
                return "legacy owner pid alive"
        if d.get("sealed") and d.get("final"):
            return None
        if now - float(d["t0"]) <= self.stale_s:
            return "not stale"
        return None

    # -------------------------------------------------- replay
    async def _replay(self, path: str, d: dict, now: float, box: list) -> dict:
        """With the call lock held: the controller adopts the checkpoint and runs its own end() on it (the digest
        rule for already/duplicate is the controller's). The call goes into `box`: the caller releases the lock
        only once its end task has finished."""
        call = CompetitionCall(d["call_id"], d["line_id"], None, self.client, checkpoint_dir=self.dir, clock=self.clock,
                               alert=self.alert, hangup_mode="leave_room", commit_deadline_s=self.commit_deadline_s,
                               count_s=d.get("count_s") or DEFAULT_COUNT_S, reveal_s=d.get("reveal_s") or DEFAULT_REVEAL_S)
        call._adopt(d)                                    # the controller's own reading of its checkpoint
        call.decision = "accept"                          # it was accepted: a checkpoint exists only for accepts
        call._start_done.set()
        box.append(call)
        if call.ended_at is None:                         # crash mid-call: ended at the last rep, else at the call's end
            last = max((float(r["t"]) for r in call.reps if r.get("t") is not None), default=None)
            call.ended_at = call.t0 + (last if last is not None else call.count_s + call.reveal_s)
            call.end_reason = "reconciled"
            call.counting_stopped = True
        # no drain: the owner is gone, so end() seals and settles liveness (C7.l)
        try:
            res = await call.end("reconciled")
        except asyncio.CancelledError:
            await self._stop(call)
            raise
        rc = dict(d.get("reconcile") or {})
        rc["attempts"] = int(rc.get("attempts") or 0) + 1
        rc["last_t"] = now
        if call.conflict is not None:                     # the controller wrote .conflict.json and alerted
            rc.pop("next_try_t", None)
            rc["conflict"] = call.conflict
            rc["last_error"] = f"payload conflict: {call.conflict['reason']}"
        elif res.get("committed"):
            rc.pop("next_try_t", None)
            rc["last_error"] = None
            log.info("call %s: reconciled (%d reps, liveness %s)", call.call_id, res.get("reps", 0), res.get("liveness_result"))
        elif all(call.sent.values()):                     # only late_reps keep it open: end() alerted commit_pending
            rc.pop("next_try_t", None)
            rc["late_alerted"] = True
            rc["last_error"] = call.last_error
            log.error("call %s: both events delivered but %d late rep(s) cannot be amended; left committed:false for "
                      "admin review", call.call_id, len(call.late_reps))
        else:
            self._backoff(rc, now, call.last_error)
            log.error("call %s: replay failed (%s); next try in %.0f s", call.call_id, call.last_error, rc["next_try_t"] - now)
        if call.late_reps and not rc.get("late_alerted"):
            rc["late_alerted"] = True                     # end() raised commit_pending for this attempt
        self._stamp(path, call.call_id, rc, fallback=None)
        out = {"call_id": call.call_id, "committed": bool(res.get("committed")) and call.conflict is None,
               "sent": dict(call.sent)}
        if call.conflict is not None:
            out["error"] = "conflict"
        return out

    def _stamp(self, path: str, call_id: str, rc: dict, fallback: dict | None) -> None:
        """Add the reconcile block to the checkpoint as it is now (the lock is held: nobody else writes)."""
        try:
            try:
                with open(path) as f:
                    doc = json.load(f)
            except (OSError, ValueError):
                if fallback is None:
                    raise
                doc = dict(fallback)
            doc["reconcile"] = rc
            write_json_atomic(path, doc)
        except (OSError, ValueError, TypeError) as e:
            log.error("call %s: could not record the reconcile state in %s: %r", call_id, path, e)
            self.alert("checkpoint_write_failed", f"call {call_id}: reconcile state: {e!r}")

    async def _stop(self, call: CompetitionCall) -> None:
        """This replay was cancelled while the shielded end task may still be sending or writing: cancel it and wait
        (bounded) for it to stop. The lock is released only when it has (see _release_after)."""
        t = call._end_task
        if t is None or t.done():
            return
        t.cancel()
        try:
            await asyncio.wait({t}, timeout=self.cancel_join_s)
        except asyncio.CancelledError:
            pass                                          # cancelled again: the original cancellation is re-raised
        if not t.done():
            log.error("call %s: cancelled replay still running after %g s; the call lock stays held until it ends",
                      call.call_id, self.cancel_join_s)

    @staticmethod
    def _release_after(lock: CallLock, call: CompetitionCall | None) -> None:
        """Release the call lock now if the replay's end task is finished (or never started), else when it finishes:
        no other owner may enter while it can still send or write."""
        t = call._end_task if call is not None else None
        if t is None or t.done():
            lock.release()
        else:
            t.add_done_callback(lambda _t: lock.release())

    def _backoff(self, rc: dict, now: float, error: str | None) -> None:
        fails = int(rc.get("failures") or 0) + 1
        rc["failures"] = fails
        rc["next_try_t"] = now + min(self.backoff_max_s, self.backoff_s * 2 ** (fails - 1))
        rc["last_error"] = error

    def _failed(self, path: str, d: dict, now: float, error: str) -> None:
        """A replay that raised: alert and back off (the reconcile block is added to the checkpoint as it is now)."""
        rc = dict(d.get("reconcile") or {})
        rc["attempts"] = int(rc.get("attempts") or 0) + 1
        rc["last_t"] = now
        self._backoff(rc, now, error)
        self.alert("commit_pending", f"call {d['call_id']}: {error}; checkpoint {path}")
        self._stamp(path, d["call_id"], rc, fallback=d)

    async def _one(self, path: str, out: dict) -> None:
        d = self._load(path)
        if d is None:
            out["skipped"][os.path.basename(path)] = "unreadable"
            return
        why = self._settled(path, d, self.clock())
        if why is not None:                               # cheap skip before touching the lock
            out["skipped"][d["call_id"]] = why
            return
        lock = CallLock.try_acquire(path)
        if lock is None:
            out["skipped"][d["call_id"]] = "owner alive"
            return
        box: list[CompetitionCall] = []
        try:
            d = self._load(path)                          # re-read as the owner: nobody can write it now
            if d is None:
                out["skipped"][os.path.basename(path)] = "unreadable"
                return
            now = self.clock()
            why = self._why_not(path, d, now)
            if why is not None:
                out["skipped"][d["call_id"]] = why
                return
            try:
                out["replayed"].append(await self._replay(path, d, now, box))
            except (KeyError, TypeError, ValueError) as e:     # a malformed checkpoint must not stop the others
                log.exception("call %s: replay failed on the checkpoint data", d["call_id"])
                self._failed(path, d, now, f"bad checkpoint data: {e!r}")
                out["replayed"].append({"call_id": d["call_id"], "committed": False, "error": repr(e)})
        finally:
            self._release_after(lock, box[0] if box else None)

    async def run_once(self) -> dict:
        out: dict[str, Any] = {"replayed": [], "skipped": {}, "locked": False}
        if not os.path.isdir(self.dir):
            log.info("no sessions directory %s; nothing to reconcile", self.dir)
            return out
        lock = open(os.path.join(self.dir, LOCK_NAME), "a")
        try:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                log.info("another reconciler holds %s; skipping this run", self.dir)
                out["locked"] = True
                return out
            for path in sorted(glob.glob(os.path.join(glob.escape(self.dir), "*" + SUFFIX))):
                await self._one(path, out)
        finally:
            lock.close()                                  # releases the flock
        if out["replayed"]:
            log.info("reconcile run: %d replayed (%d committed), %d skipped", len(out["replayed"]),
                     sum(r["committed"] for r in out["replayed"]), len(out["skipped"]))
        return out


async def amain(args: argparse.Namespace) -> int:
    url, token = os.environ.get("DISPATCHER_URL", "").strip(), os.environ.get("DISPATCHER_TOKEN", "").strip()
    if not url or not token:
        log.error("DISPATCHER_URL and DISPATCHER_TOKEN are required")
        return 2
    try:
        legacy_grace_from_env()
        max_run_s = max_run_from_env()
    except ValueError as e:
        log.error("%s", e)
        return 2
    alert = HttpAlert(url, token)
    deadline = arm_deadline(max_run_s, alert) if args.once else None
    try:
        client = DispatcherClient.from_env()
        try:
            rec = Reconciler(client, args.dir, stale_s=args.stale_s, backoff_s=args.backoff_s,
                             backoff_max_s=args.backoff_max_s, alert=alert)
            while True:
                await rec.run_once()
                if args.once:
                    return 0
                await asyncio.sleep(args.interval_s)
        finally:
            await client.aclose()
    finally:
        if deadline is not None:
            deadline.cancel()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Commit uncommitted competition-call checkpoints (idempotent).")
    p.add_argument("--once", action="store_true", help="one pass, then exit (the systemd timer runs it every minute)")
    p.add_argument("--dir", default=None, help="sessions directory (default: CHALLENGE_SESSIONS_DIR or data/tmp/sessions)")
    p.add_argument("--stale-s", type=float, default=STALE_S, help="an unsealed checkpoint is replayable this long after t0")
    p.add_argument("--backoff-s", type=float, default=BACKOFF_S)
    p.add_argument("--backoff-max-s", type=float, default=BACKOFF_MAX_S)
    p.add_argument("--interval-s", type=float, default=60.0, help="pause between passes without --once")
    a = p.parse_args(argv)
    for name in ("stale_s", "backoff_s", "backoff_max_s", "interval_s"):
        if getattr(a, name) < 0:
            p.error(f"--{name.replace('_', '-')} must be >= 0")
    return a


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(amain(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
