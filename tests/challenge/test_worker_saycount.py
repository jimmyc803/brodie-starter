"""Spoken running count on competition calls (owner request "make brodie count reps"): the controller hands every
counted rep's running total to the worker, which plays "One", "Two", ... on the cue player's count slot. Invalid reps
are not counted; a newer count replaces an unplayed older one; judge_thresholds say_count false silences it."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from facetime import cues_tts
from facetime.audio_out import CuePlayer
from tests.challenge.test_worker_controller import T0, Rig, rep_ev, run
from tests.challenge.test_worker_warm_room_e2e import make as make_harness


def _no_liveness(rng, thr):
    raise AssertionError("liveness is off in these calls")


def _call(tmp_path, judge_cfg=None, start_cfg=None, power_hour=False):
    counts = []
    start = {"decision": "accept", "user_id": "u1", "reason": "ok", "cue": None, "config": start_cfg or {},
             "power_hour_active": power_hour}
    r = Rig(tmp_path, liveness=_no_liveness, judge_cfg=judge_cfg or {}, start=start, count=counts.append)
    return r, counts


def test_valid_reps_are_counted_aloud_and_invalid_reps_are_not(tmp_path):
    async def go():
        r, counts = _call(tmp_path)
        assert await r.call.start() is True
        r.call.judge_applied()
        for i, (rel, valid) in enumerate(((10, True), (12, False), (14, True), (16, True)), 1):
            await r.advance(rel)
            r.call.on_rep(rep_ev(valid=valid, cue=None if valid else "too_shallow", n=i), t=T0 + rel)
        return r, counts
    r, counts = run(go())
    assert counts == [1, 2, 3]
    assert "too_shallow" in r.keys()                      # the invalid rep keeps its correction cue
    assert r.call.counted_reps() == 3


def test_power_hour_counts_reps_not_points(tmp_path):
    async def go():
        r, counts = _call(tmp_path, power_hour=True)
        assert await r.call.start() is True
        r.call.judge_applied()
        for i, rel in enumerate((10, 12), 1):
            await r.advance(rel)
            r.call.on_rep(rep_ev(n=i), t=T0 + rel)
        return r, counts
    r, counts = run(go())
    assert counts == [1, 2] and "power_hour" in r.keys()


def test_no_count_after_time_up_or_in_a_challenge(tmp_path):
    async def go():
        r, counts = _call(tmp_path)
        assert await r.call.start() is True
        r.call.judge_applied()
        await r.advance(10)
        r.call.on_rep(rep_ev(n=1), t=T0 + 10)
        r.call.on_rep(rep_ev(n=2, in_challenge=True), t=T0 + 10.5)      # challenge reps never count
        await r.advance(181)                                            # time up: counting stopped
        r.call.on_rep(rep_ev(n=3), t=T0 + 179.9)                        # fired before count end, delivered late
        return r, counts
    r, counts = run(go())
    assert counts == [1]
    assert len(r.call.reps) == 3                                        # still recorded; only the voice is off


@pytest.mark.parametrize("judge_cfg,start_cfg", [
    ({"say_count": False}, {}),
    ({}, {"judge_thresholds": {"say_count": False}}),                  # live competition_config, no deploy
])
def test_say_count_flag_off_is_silent(tmp_path, judge_cfg, start_cfg):
    async def go():
        r, counts = _call(tmp_path, judge_cfg=judge_cfg, start_cfg=start_cfg)
        assert await r.call.start() is True
        r.call.judge_applied()
        await r.advance(10)
        stored = r.call.on_rep(rep_ev(n=1), t=T0 + 10)
        return stored, counts
    stored, counts = run(go())
    assert stored["valid"] is True and counts == []


def test_count_hook_error_never_breaks_the_rep(tmp_path):
    def boom(n):
        raise RuntimeError("player gone")

    async def go():
        r = Rig(tmp_path, liveness=_no_liveness, judge_cfg={}, count=boom)
        assert await r.call.start() is True
        r.call.judge_applied()
        await r.advance(10)
        return r.call.on_rep(rep_ev(n=1), t=T0 + 10), r
    stored, r = run(go())
    assert stored is not None and len(r.call.reps) == 1


# ------------------------------------------------------------------ the bank text
def test_count_text_matches_the_bank_and_covers_1_to_100():
    assert [cues_tts.count_text(n) for n in (1, 2, 20, 21, 30, 31, 99, 100)] == \
        ["One", "Two", "Twenty", "21", "30", "31", "99", "100"]
    assert cues_tts.count_text(0) is None and cues_tts.count_text(101) is None
    vocab = set(cues_tts.vocabulary())
    assert {cues_tts.count_text(n) for n in range(1, 101)} <= vocab
    assert {cues_tts.count_text(n) for n in range(1, 101)} <= cues_tts.count_words()      # count trim (immediacy)


@pytest.mark.parametrize("text,heard,ok", [
    ("45", "Forty-five!", True), ("100", "One hundred.", True), ("71", "Seventy one", True),
    ("45", "Nice work, let's go", False),
])
def test_transcript_check_reads_counts_to_100(text, heard, ok):
    assert cues_tts.transcript_ok(text, heard) is ok


def test_number_word_unchanged_to_thirty():
    assert cues_tts.number_word(7) == "seven" and cues_tts.number_word(23) == "twenty three"
    assert cues_tts.number_word(30) == "thirty" and cues_tts.number_word(58) == "fifty eight"


# ------------------------------------------------------------------ the player's count slot
class Bank:
    def get(self, text):
        return np.ones(480, np.int16)


class Source:
    async def capture_frame(self, f):
        pass

    async def wait_for_playout(self):
        pass


def _player():
    recs = []
    return CuePlayer(bank=Bank(), source=Source(), on_record=recs.append), recs


def test_newer_count_replaces_an_unplayed_older_one():
    p, recs = _player()
    p.say("Knees off the floor! That one didn't count.", "correction")
    p.say("One", "count")                                 # jumps ahead; the correction plays right after it
    assert p.pending[0]["text"] == "One" and p.deferred[0]["intent"] == "correction"
    p.say("Two", "count")                                 # "One" is stale
    assert p.pending[0]["text"] == "Two" and p.deferred[0]["intent"] == "correction"
    assert [(r["text"], r["status"], r["why_dropped"]) for r in recs] == [("One", "dropped", "stale count")]


def test_count_never_cuts_an_urgent_cue():
    async def go():
        p, recs = _player()
        p.say_now("Time!", "challenge")
        p.say("Three", "count")
        task = asyncio.create_task(p.run())
        for _ in range(50):
            await asyncio.sleep(0.01)
            if len([r for r in recs if r["status"] == "played"]) == 2:
                break
        p.stop(); task.cancel()
        return recs
    recs = run(go())
    assert [(r["text"], r["status"]) for r in recs] == [("Time!", "played"), ("Three", "played")]


# ------------------------------------------------------------------ the worker
class FakePlayer:
    def __init__(self):
        self.said, self.now = [], []
        self.playing = self.pending = self.urgent = None

    def say(self, text, intent="other", meta=None):
        self.said.append((text, intent))

    def say_now(self, text, intent="probe", meta=None):
        self.now.append((text, intent))


def test_worker_speaks_counts_on_the_count_slot_and_stays_silent_past_the_bank(tmp_path, monkeypatch):
    h = make_harness(monkeypatch, tmp_path)
    job = h.job
    job.player = FakePlayer()
    job.say_count(1); job.say_count(21); job.say_count(101); job.say_count(0)
    assert job.player.said == [("One", "count"), ("21", "count")]


def test_worker_competition_call_counts_valid_reps_aloud(tmp_path, monkeypatch):
    h = make_harness(monkeypatch, tmp_path)
    job = h.job
    job.player = FakePlayer()

    async def go():
        job.loop = asyncio.get_running_loop()
        await h.settle()
        h.bind("chert-bridge-call-9")
        await h.settle()
        assert job.comp is not None and job.comp.decision == "accept"
        for i, (t, valid) in enumerate(((20.0, True), (22.0, False), (24.0, True)), 1):
            h.clock.t = T0 + t
            job._deliver({**rep_ev(valid=valid, n=i), "exercise": "pushups", "t": t})
        await h.settle()
        counts = [x for x in job.player.said if x[1] == "count"]
        job.end("test over")
        await job.close_competition()
        return counts
    assert run(go()) == [("One", "count"), ("Two", "count")]
