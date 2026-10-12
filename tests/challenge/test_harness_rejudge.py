"""Task 14: judge_eval harness (labels, aggregation, ship gate, synthetic run) and scripts/rejudge.py (fake store + real DB)."""
from __future__ import annotations

import importlib.util
import sys
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from psycopg.types.json import Jsonb

from challenge.judge.gates import JUDGE_VERSION
from challenge.store import PgStore, StoreError
from judge_eval import run as ev
from rtcoach import pose as rp
from tests.challenge.test_dispatcher_api import T0, commit_ev, mkuser

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("rejudge", ROOT / "scripts" / "rejudge.py")
rj = importlib.util.module_from_spec(_spec)
sys.modules["rejudge"] = rj
_spec.loader.exec_module(rj)


# ---------------------------------------------------------------- labels

GOOD = """
clips:
  - {clip: a.mp4, category: clean, camera: side-left, expected_valid: 10}
  - {clip: b.mp4, category: knees, expected_valid: 0, expected_rejected: {knees_down: 8}}
"""


def test_parse_labels_ok():
    ls = ev.parse_labels(GOOD)
    assert [(x.clip, x.category, x.expected_valid) for x in ls] == [("a.mp4", "clean", 10), ("b.mp4", "knees", 0)]
    assert ls[1].expected_rejected == {"knees_down": 8} and ls[0].camera == "side-left"


def test_example_labels_file_parses():
    assert len(ev.parse_labels((ROOT / "judge_eval" / "labels.example.yaml").read_text())) >= 3


@pytest.mark.parametrize("text", [
    "clips: []", "[]", "clips: [{clip: a, category: clean}]",
    "clips: [{clip: a, category: clean, expected_valid: -1}]",
    "clips: [{clip: a, category: knees, expected_valid: 3}]",
    "clips: [{clip: a, category: clean, expected_valid: 1, expected_rejected: {x: -2}}]",
    "clips: [3]"])
def test_parse_labels_rejects(text):
    with pytest.raises(ev.LabelsError):
        ev.parse_labels(text)


# ---------------------------------------------------------------- aggregation + ship gate

def mk(category, valids, expected, reasons=(), cam=""):
    reps = [{"n": i + 1, "t": i, "valid": True, "reasons": [], "in_challenge": False} for i in range(valids)]
    reps += [{"n": 100 + i, "t": i, "valid": False, "reasons": list(r), "in_challenge": False} for i, r in enumerate(reasons)]
    return ev.ClipResult(ev.ClipLabel(f"{category}.mp4", category, cam, expected), reps)


def full(cheat_valid=0):
    return [mk("clean", 10, 10)] + [mk(c, cheat_valid if c == "sag" else 0, 0, [["x"]]) for c in ev.CHEAT]


def test_clip_result_counts():
    r = mk("clean", 8, 10, [["too_shallow"], ["too_shallow", "no_lockout"]])
    assert r.got_valid == 8 and r.count_error == 2
    assert r.got_rejected == {"too_shallow": 2, "no_lockout": 1}


def test_aggregate():
    agg = ev.aggregate([mk("clean", 9, 10, [["hips_sag"]]), mk("knees", 0, 0, [["knees_down"]] * 3)])
    assert agg["categories"]["clean"] == {"clips": 1, "reps": 10, "accepted": 9, "expected_valid": 10}
    assert agg["rejected_by_reason"] == {"hips_sag": 1, "knees_down": 3}


def test_gate_pass():
    g = ev.ship_gate(full())
    assert g["verdict"] == "PASS" and g["needs_footage"] == [] and g["clean_accept_rate"] == 1.0


def test_gate_fails_on_any_accepted_cheat_rep():
    g = ev.ship_gate(full(cheat_valid=1))
    assert g["verdict"] == "FAIL" and "cheat_accepted_zero" in g["failed"] and g["cheat_accepted"]["sag"] == 1


def test_gate_clean_rate_and_count_error():
    g = ev.ship_gate([mk("clean", 8, 10)] + full()[1:])
    assert g["verdict"] == "FAIL" and g["failed"] == ["clean_accept_ge_90pct", "clean_count_error_le_1"]
    g = ev.ship_gate([mk("clean", 9, 10), mk("clean", 10, 10)] + full()[1:])
    assert g["verdict"] == "PASS" and g["clean_accept_rate"] == 0.95
    g = ev.ship_gate([mk("clean", 10, 10), mk("clean", 8, 10)] + [mk("clean", 10, 10)] * 3 + full()[1:])
    assert g["failed"] == ["clean_count_error_le_1"]            # 48/50 = 96% accepted but one clip is off by 2


def test_gate_extra_accepted_reps_count_as_count_error():
    g = ev.ship_gate([mk("clean", 13, 10)] + full()[1:])
    assert "clean_count_error_le_1" in g["failed"] and g["clean_worst_count_error"] == 3


def test_gate_incomplete_when_cheat_category_missing_and_fail_without_clean():
    res = [r for r in full() if r.label.category != "replay"]
    assert ev.ship_gate(res)["verdict"] == "INCOMPLETE" and ev.ship_gate(res)["needs_footage"] == ["replay"]
    assert ev.ship_gate(res, tuple(c for c in ev.CHEAT if c != "replay"))["verdict"] == "PASS"
    assert ev.ship_gate([r for r in full() if r.label.category != "clean"])["verdict"] == "FAIL"


def test_latency_stats():
    s = ev.latency_stats([float(x) for x in range(1, 101)])
    assert s["p50_ms"] == 50.5 and s["p95_ms"] == 95.05 and s["budget_ms"] == 100.0
    assert s["headroom_x"] == round(100 / 95.05, 2)
    assert ev.latency_stats([]) == {}


# ---------------------------------------------------------------- CLI

def test_missing_clips_dir_exit_2(tmp_path, capsys):
    assert ev.main(["--clips-dir", str(tmp_path / "nope"), "--labels", str(tmp_path / "l.yaml")]) == 2
    assert "clips dir not found" in capsys.readouterr().err


def test_missing_labels_and_missing_clip_exit_2(tmp_path, capsys):
    assert ev.main(["--clips-dir", str(tmp_path), "--labels", str(tmp_path / "l.yaml")]) == 2
    (tmp_path / "l.yaml").write_text(GOOD)
    assert ev.main(["--clips-dir", str(tmp_path), "--labels", str(tmp_path / "l.yaml")]) == 2
    assert "a.mp4" in capsys.readouterr().err
    (tmp_path / "l.yaml").write_text("clips: []")
    assert ev.main(["--clips-dir", str(tmp_path), "--labels", str(tmp_path / "l.yaml")]) == 2


def test_synthetic_run_passes_and_writes_results(tmp_path, capsys):
    thr = tmp_path / "thr.json"
    thr.write_text("{}")
    assert ev.main(["--synthetic", "--bench", "--thresholds", str(thr), "--results-dir", str(tmp_path / "res")]) == 0
    out = capsys.readouterr().out
    assert "VERDICT: PASS" in out and "SHIP GATE" in out and "LATENCY per frame" in out
    (f,) = list((tmp_path / "res").glob("*.json"))
    doc = json.loads(f.read_text())
    assert doc["mode"] == "synthetic" and doc["gate"]["verdict"] == "PASS"
    assert {c["category"] for c in doc["clips"]} == {"clean", "knees", "half", "sag", "pike", "no_lockout", "two_people"}
    assert all(c["got_valid"] == 0 for c in doc["clips"] if c["category"] != "clean")


def test_synthetic_run_fails_with_loosened_thresholds(tmp_path):
    thr = tmp_path / "thr.json"
    thr.write_text(json.dumps({"depth_elbow_max_deg": 179, "depth_margin": 10, "hip_line_max_dev_deg": 90,
                               "knee_min_deg": 0, "knee_floor_margin": -1, "lockout_min_deg": 0,
                               "classifier_veto": [], "classifier_veto_substrings": []}))
    assert ev.main(["--synthetic", "--thresholds", str(thr), "--results-dir", str(tmp_path / "res")]) == 1


# ---------------------------------------------------------------- 2nd-person floor

def _pose(vis, pres, n_vis=33):
    a = np.zeros((33, 5), np.float32)
    a[:, 3] = 0.0
    a[:n_vis, 3] = vis
    a[:, 4] = pres
    for i in (11, 12, 23, 24):
        a[i, 3] = vis
    return a


def test_second_person_floor():
    assert rp.passes_floor(_pose(0.9, 0.9))
    assert not rp.passes_floor(_pose(0.9, 0.2))                              # low presence
    assert not rp.passes_floor(_pose(0.9, 0.9, n_vis=4))                      # fragment: < PERSON_MIN_LMS landmarks
    a, b = _pose(0.9, 0.9), _pose(0.9, 0.9, n_vis=4)
    a[:, 0] = np.linspace(0.1, 0.4, 33)
    a[:, 1] = np.linspace(0.1, 0.9, 33)
    b[:, 0] = np.linspace(0.6, 0.9, 33)
    b[:, 1] = np.linspace(0.1, 0.9, 33)
    assert rp.count_persons([a, b]) == 1                                      # fragment below the floor is not a person
    assert rp.count_persons([b, a], primary=0) == 2                           # the primary is exempt from the floor
    b2 = _pose(0.9, 0.9)
    b2[:, 0] = np.linspace(0.6, 0.9, 33)
    b2[:, 1] = np.linspace(0.1, 0.9, 33)
    assert rp.count_persons([a, b2]) == 2


# ---------------------------------------------------------------- rejudge, fake store

def row(i, user="u1", **kw):
    r = {"rep_id": f"r{i}", "call_id": "c1", "user_id": user, "display_name": user, "rep_number": i, "valid": True,
         "reject_reasons": [], "multiplier": 1, "points": 1, "in_challenge": False, "min_elbow_deg_l": 80.0,
         "min_elbow_deg_r": None, "top_elbow_deg": 175.0, "max_hip_line_dev_deg": 3.0, "min_knee_deg": 175.0,
         "knee_floor_contact": False, "shoulder_wrist_drop": 0.1, "shoulder_elbow_gap": 0.01, "min_keypoint_conf": 0.9,
         "frame_conf_frac": 0.99, "persons_in_frame": 1, "rep_duration_s": 2.0, "torso_ok": True, "side": "left",
         "classifier_labels": ["pushups - correct"]}
    r.update(kw)
    return r


class FakeStore:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def rpc(self, fn, args=None):
        self.calls.append((fn, args))
        if fn == "ch_rejudge_fetch":
            return self.rows
        if fn == "ch_rejudge_apply":
            return {"ok": True, "changed": len(args["p_changes"])}
        raise StoreError(f"{fn}: function does not exist")


def test_rejudge_row_unchanged_under_same_thresholds():
    d = rj.rejudge_rows([row(1)], {})[0]
    assert not d.changed and d.new_valid and d.new_points == 1


def test_rejudge_tightened_and_loosened():
    rows = [row(1, max_hip_line_dev_deg=12.0), row(2, valid=False, reject_reasons=["hips_sag"], points=0,
                                                   max_hip_line_dev_deg=17.0, multiplier=2)]
    tight = rj.rejudge_rows(rows, {"hip_line_max_dev_deg": 10})
    assert (tight[0].new_valid, tight[0].new_reasons, tight[0].new_points) == (False, ["hips_sag"], 0)
    loose = rj.rejudge_rows(rows, {"hip_line_max_dev_deg": 20})
    assert (loose[1].new_valid, loose[1].new_reasons, loose[1].new_points) == (True, [], 2)   # power-hour multiplier kept
    assert not loose[0].changed


def test_rejudge_keeps_commit_time_facts():
    rows = [row(1, valid=False, reject_reasons=["after_count"], points=0),
            row(2, valid=False, reject_reasons=["hips_sag", "liveness_fail"], points=0, max_hip_line_dev_deg=17.0),
            row(3, valid=False, in_challenge=True, points=0)]
    d = rj.rejudge_rows(rows, {"hip_line_max_dev_deg": 20})
    assert (d[0].new_valid, d[0].new_reasons, d[0].changed) == (False, ["after_count"], False)
    assert (d[1].new_valid, d[1].new_reasons, d[1].new_points) == (False, ["liveness_fail"], 0)
    assert (d[2].new_valid, d[2].changed) == (False, False)


def test_user_deltas_and_report():
    rows = [row(1, "ann", max_hip_line_dev_deg=12.0), row(2, "ann", max_hip_line_dev_deg=12.0), row(3, "bob"),
            row(4, "cy", valid=False, reject_reasons=["hips_sag"], points=0, max_hip_line_dev_deg=11.0)]
    diffs = rj.rejudge_rows(rows, {"hip_line_max_dev_deg": 10})
    u = rj.user_deltas(diffs)
    assert [(x["display_name"], x["before"], x["after"], x["delta"]) for x in u] == [("ann", 2, 0, -2)]
    rep_txt = rj.report(diffs)
    assert "verdict changed: 2" in rep_txt and "ann: 2 -> 0 (-2)" in rep_txt and "+hips_sag" in rep_txt
    assert "bob" not in rep_txt


def thr_file(tmp_path, d):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(d))
    return str(p)


def test_dry_run_writes_nothing(tmp_path, capsys):
    st = FakeStore([row(1, max_hip_line_dev_deg=12.0)])
    assert rj.main(["--thresholds", thr_file(tmp_path, {"hip_line_max_dev_deg": 10}), "--since", "2026-10-01"], st) == 0
    assert [c[0] for c in st.calls] == ["ch_rejudge_fetch"] and st.calls[0][1]["p_since"] == "2026-10-01"
    assert "dry run" in capsys.readouterr().out


def test_apply_requires_actor_and_reason(tmp_path):
    st = FakeStore([row(1)])
    f = thr_file(tmp_path, {})
    assert rj.main(["--thresholds", f, "--apply"], st) == 2
    assert rj.main(["--thresholds", f, "--apply", "--actor", "a@b.c"], st) == 2
    assert rj.main(["--thresholds", f, "--apply", "--actor", "a@b.c", "--reason", "  "], st) == 2
    assert st.calls == []


def test_apply_sends_only_changed_reps(tmp_path, capsys):
    st = FakeStore([row(1, max_hip_line_dev_deg=12.0), row(2)])
    f = thr_file(tmp_path, {"hip_line_max_dev_deg": 10})
    assert rj.main(["--thresholds", f, "--apply", "--actor", "a@b.c", "--reason", "tighten"], st) == 0
    fn, args = st.calls[-1]
    assert fn == "ch_rejudge_apply" and args["p_actor"] == "a@b.c" and args["p_reason"] == "tighten"
    assert args["p_changes"] == [{"rep_id": "r1", "valid": False, "reject_reasons": ["hips_sag"], "points": 0}]
    assert args["p_thresholds"]["hip_line_max_dev_deg"] == 10 and args["p_judge_version"].startswith(JUDGE_VERSION)
    assert "applied" in capsys.readouterr().out


def test_apply_nothing_to_change_skips_rpc(tmp_path):
    st = FakeStore([row(1)])
    assert rj.main(["--thresholds", thr_file(tmp_path, {}), "--apply", "--actor", "a", "--reason", "r"], st) == 0
    assert [c[0] for c in st.calls] == ["ch_rejudge_fetch"]


def test_missing_rpc_prints_needs_sql(tmp_path, capsys):
    class NoRpc:
        def rpc(self, fn, args=None):
            raise StoreError(f"{fn}: function ch_rejudge_fetch does not exist")
    assert rj.main(["--thresholds", thr_file(tmp_path, {})], NoRpc()) == 2
    err = capsys.readouterr().err
    assert "NEEDS-SQL" in err and "20261015_challenge_rejudge.sql" in err


def test_bad_thresholds_file(tmp_path):
    assert rj.main(["--thresholds", str(tmp_path / "missing.json")], FakeStore([])) == 2


# ---------------------------------------------------------------- rejudge, real Postgres

MIGRATION = ROOT / "db" / "migrations" / "20261015_challenge_rejudge.sql"


@pytest.fixture
def st(db, conn):
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, version=0, updated_at=now()")
    return PgStore(db)


def metric_rep(n, at, **kw):
    base = {"n": n, "t": float(n), "at": at, "valid": True, "reject_reasons": [], "faults": [], "in_challenge": False,
            "min_elbow_deg_l": 80.0, "top_elbow_deg": 175.0, "max_hip_line_dev_deg": 3.0, "min_knee_deg": 175.0,
            "knee_floor_contact": False, "shoulder_wrist_drop": 0.1, "shoulder_elbow_gap": 0.01,
            "min_keypoint_conf": 0.9, "frame_conf_frac": 0.99, "persons_in_frame": 1, "rep_duration_s": 2.0,
            "torso_ok": True, "side": "left", "classifier_labels": ["pushups - correct"]}
    return {**base, **kw}


def commit(st, cid, handle, reps):
    r = st.rpc("ch_call_start", {"p_call_id": cid, "p_line_id": "line-1", "p_handle": handle, "p_mode": "chert_meta",
                                 "p_now": T0})
    assert r["decision"] == "accept", r
    ev_ = commit_ev(cid)
    ev_["payload"]["reps"] = reps
    assert st.rpc("ch_commit_reps", {"p_call_id": cid, "p_payload": ev_["payload"], "p_now": T0 + timedelta(seconds=200)})["ok"]


def test_rejudge_migration_applies_twice(pg_cluster, db, st):
    name = db.split("dbname=")[1].split()[0]
    pg_cluster.apply_file(name, MIGRATION)
    pg_cluster.apply_file(name, MIGRATION)


@pytest.mark.parametrize("sig", ["ch_rejudge_fetch(timestamptz,integer)",
                                 "ch_rejudge_apply(jsonb,text,jsonb,text,text,timestamptz)"])
def test_rejudge_rpc_grants(st, conn, sig):
    ok = conn.execute("select has_function_privilege('service_role', %s, 'execute'), "
                      "has_function_privilege('anon', %s, 'execute'), has_function_privilege('authenticated', %s, 'execute')",
                      (sig, sig, sig)).fetchone()
    assert ok == (True, False, False)


def test_rejudge_end_to_end(st, conn, tmp_path, capsys):
    uid, h = mkuser(conn)
    at = (T0 + timedelta(seconds=10)).isoformat()
    commit(st, "rj1", h, [metric_rep(1, at, max_hip_line_dev_deg=12.0), metric_rep(2, at),
                          metric_rep(3, at, valid=False, reject_reasons=["hips_sag"], max_hip_line_dev_deg=17.0),
                          {k: v for k, v in metric_rep(4, at).items() if k != "persons_in_frame"}])   # no metrics -> never fetched
    rows = rj.fetch_rows(st, None, 1000)
    assert [r["rep_number"] for r in rows] == [1, 2, 3] and rows[0]["points"] == 1 and rows[2]["points"] == 0
    assert rj.fetch_rows(st, (T0 + timedelta(days=1)).isoformat(), 1000) == []
    f = thr_file(tmp_path, {"hip_line_max_dev_deg": 10})
    assert rj.main(["--thresholds", f], st) == 0                               # dry run: DB untouched
    assert conn.execute("select count(*) from reps where valid").fetchone()[0] == 3
    assert conn.execute("select count(*) from audit_log where action='rejudge'").fetchone()[0] == 0
    assert rj.main(["--thresholds", f, "--apply", "--actor", "admin@x.io", "--reason", "tighten sag"], st) == 0
    got = conn.execute("select rep_number, valid, reject_reasons, points, judge_version from reps order by rep_number").fetchall()
    assert [(g[0], g[1], g[2], g[3]) for g in got[:3]] == [(1, False, ["hips_sag"], 0), (2, True, [], 1), (3, False, ["hips_sag"], 0)]
    assert got[0][4].startswith(JUDGE_VERSION + ".rejudge.") and got[1][4] == "j1"
    (a,) = conn.execute("select actor, action, reason, before, after from audit_log where action='rejudge'").fetchall()
    assert a[0] == "admin@x.io" and a[2] == "tighten sag"
    assert a[4]["reps_changed"] == 1 and a[4]["thresholds"]["hip_line_max_dev_deg"] == 10
    assert a[3]["users_points"] == {uid: 1} and a[4]["users_points"] == {uid: 0}
    assert conn.execute("select ch_user_points(%s)", (uid,)).fetchone()[0] == 2      # reps 2 and 4 (4 had no metrics)
    # idempotent: a second apply changes nothing (still writes no rep updates)
    assert rj.main(["--thresholds", f, "--apply", "--actor", "admin@x.io", "--reason", "again"], st) == 0
    assert conn.execute("select count(*) from audit_log where action='rejudge'").fetchone()[0] == 1


def test_rejudge_loosening_restores_points_and_keeps_commit_reasons(st, conn, tmp_path):
    uid, h = mkuser(conn)
    at = (T0 + timedelta(seconds=10)).isoformat()
    late = (T0 + timedelta(seconds=500)).isoformat()                        # after the 180 s count window
    commit(st, "rj2", h, [metric_rep(1, at, valid=False, reject_reasons=["hips_sag"], max_hip_line_dev_deg=17.0),
                          metric_rep(2, late, max_hip_line_dev_deg=17.0)])
    f = thr_file(tmp_path, {"hip_line_max_dev_deg": 20})
    assert rj.main(["--thresholds", f, "--apply", "--actor", "a", "--reason", "loosen"], st) == 0
    got = conn.execute("select rep_number, valid, reject_reasons, points from reps order by rep_number").fetchall()
    assert got[0] == (1, True, [], 1)
    assert got[1][1] is False and got[1][2] == ["after_count"] and got[1][3] == 0
    assert conn.execute("select ch_user_points(%s)", (uid,)).fetchone()[0] == 1


def test_rejudge_skips_void_calls_and_requires_reason(st, conn):
    uid, h = mkuser(conn)
    at = (T0 + timedelta(seconds=10)).isoformat()
    commit(st, "rj3", h, [metric_rep(1, at)])
    st.rpc("ch_admin_void_call", {"p_call_id": "rj3", "p_reason": "x", "p_actor": "a"})
    assert rj.fetch_rows(st, None, 10) == []
    with pytest.raises(StoreError):
        st.rpc("ch_rejudge_apply", {"p_changes": [], "p_judge_version": "j2", "p_thresholds": {}, "p_actor": "a",
                                    "p_reason": " ", "p_now": T0})
    with pytest.raises(StoreError):
        st.rpc("ch_rejudge_apply", {"p_changes": {"x": 1}, "p_judge_version": "j2", "p_thresholds": {}, "p_actor": "a",
                                    "p_reason": "r", "p_now": T0})
