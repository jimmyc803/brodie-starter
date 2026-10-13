"""Re-judge stored reps under new thresholds (SPEC section 6 versioning). Dry run by default.

    python scripts/rejudge.py --thresholds file.json [--since 2026-10-15T00:00:00-04:00] [--limit N]
                              [--apply --actor email --reason text] [--judge-version j1.rejudge.20261015]

Loads every stored rep that has metrics (RPC ch_rejudge_fetch), recomputes valid / reject_reasons / points with
challenge.judge.gates.judge_rep over DEFAULT_THRESHOLDS overlaid by the --thresholds JSON, and prints a diff report:
reps whose verdict changes and, per user, points before -> after. Facts the judge does not decide are kept: reasons set
at commit by the clock/liveness rules (after_freeze, before_start, after_count, liveness_fail) and in_challenge reps stay
rejected; points = the rep's stored multiplier when valid, else 0. Reps whose judge_version family (the part before the
first '.') is not the current JUDGE_VERSION are kept as stored and reported as skipped (their metrics mean different
things, e.g. j1 shoulder_wrist_drop vs the j2 ratio). --apply writes the changed reps in ONE transaction via
ch_rejudge_apply (which also writes the audit_log row); --actor and --reason are required with --apply.
Needs ch_rejudge_fetch / ch_rejudge_apply from db/migrations/20261015_challenge_rejudge.sql (NEEDS-SQL is printed if absent).
Exit: 0 ok, 2 usage / missing RPC.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from challenge.judge.gates import JUDGE_VERSION, judge_rep, merged_thresholds  # noqa: E402
from challenge.judge.metrics import RepMetrics  # noqa: E402
from challenge.store import Store, StoreError  # noqa: E402

COMMIT_REASONS = ("after_freeze", "before_start", "after_count", "liveness_fail")
MIGRATION = "db/migrations/20261015_challenge_rejudge.sql"


@dataclass
class RepDiff:
    rep_id: str
    call_id: str
    user_id: str
    display_name: str | None
    rep_number: int
    old_valid: bool
    new_valid: bool
    old_reasons: list[str]
    new_reasons: list[str]
    old_points: int
    new_points: int
    skipped: str | None = None        # why the rep was not re-judged (verdict kept as stored)

    @property
    def changed(self) -> bool:
        return (self.old_valid, sorted(self.old_reasons), self.old_points) != (self.new_valid, sorted(self.new_reasons), self.new_points)


def metrics_from_row(row: dict[str, Any]) -> RepMetrics:
    return RepMetrics(
        min_elbow_deg_l=row.get("min_elbow_deg_l"), min_elbow_deg_r=row.get("min_elbow_deg_r"),
        top_elbow_deg=row.get("top_elbow_deg"), max_hip_line_dev_deg=row.get("max_hip_line_dev_deg"),
        min_knee_deg=row.get("min_knee_deg"), knee_floor_contact=row.get("knee_floor_contact"),
        shoulder_wrist_drop=row.get("shoulder_wrist_drop"),
        min_keypoint_conf=row.get("min_keypoint_conf") if row.get("min_keypoint_conf") is not None else 0.0,
        frame_conf_frac=row.get("frame_conf_frac"),
        persons_in_frame=int(row["persons_in_frame"]), rep_duration_s=row.get("rep_duration_s"),
        torso_ok=bool(row.get("torso_ok")), side=row.get("side") or "",
        classifier_labels=list(row.get("classifier_labels") or []), shoulder_elbow_gap=row.get("shoulder_elbow_gap"))


def judge_family(version: Any) -> str:
    """'j2' for 'j2' and 'j2.rejudge.20261020' (ch_rejudge_apply stamps <family>.rejudge.<date>)."""
    return str(version or "").split(".", 1)[0]


def rejudge_row(row: dict[str, Any], thr: dict) -> RepDiff:
    """Recompute one stored rep. Commit-time facts (window/liveness reasons, in_challenge) are preserved.
    Only reps whose metrics were computed by the current judge family are re-judged: j1 metrics mean different things
    (shoulder_wrist_drop was an absolute drop, not the j2 bottom/top ratio; different judged frames), so judging them
    with the current gates would invent verdicts. Those reps are kept as stored and reported as skipped."""
    old_reasons = list(row.get("reject_reasons") or [])
    if judge_family(row.get("judge_version")) != JUDGE_VERSION:
        old_valid, old_points = bool(row.get("valid")), int(row.get("points") or 0)
        return RepDiff(rep_id=str(row["rep_id"]), call_id=str(row["call_id"]), user_id=str(row["user_id"]),
                       display_name=row.get("display_name"), rep_number=int(row.get("rep_number") or 0),
                       old_valid=old_valid, new_valid=old_valid, old_reasons=old_reasons,
                       new_reasons=list(old_reasons), old_points=old_points, new_points=old_points,
                       skipped=f"judge_version {row.get('judge_version')!r} is not {JUDGE_VERSION}: metrics not comparable")
    valid, reasons = judge_rep(metrics_from_row(row), thr)
    extras = [r for r in old_reasons if r in COMMIT_REASONS]
    in_challenge = bool(row.get("in_challenge"))
    new_reasons = list(reasons) + [r for r in extras if r not in reasons]
    new_valid = valid and not in_challenge and not extras
    mult = int(row.get("multiplier") or 1)
    return RepDiff(rep_id=str(row["rep_id"]), call_id=str(row["call_id"]), user_id=str(row["user_id"]),
                   display_name=row.get("display_name"), rep_number=int(row.get("rep_number") or 0),
                   old_valid=bool(row.get("valid")), new_valid=new_valid, old_reasons=old_reasons,
                   new_reasons=new_reasons, old_points=int(row.get("points") or 0), new_points=mult if new_valid else 0)


def rejudge_rows(rows: list[dict[str, Any]], thr: dict | None) -> list[RepDiff]:
    t = merged_thresholds(thr)
    return [rejudge_row(r, t) for r in rows]


def user_deltas(diffs: list[RepDiff]) -> list[dict[str, Any]]:
    """Users whose points change: [{user_id, display_name, before, after, delta, reps_changed}] sorted by |delta|."""
    users: dict[str, dict[str, Any]] = {}
    for d in diffs:
        u = users.setdefault(d.user_id, {"user_id": d.user_id, "display_name": d.display_name, "before": 0, "after": 0,
                                         "reps_changed": 0})
        u["before"] += d.old_points
        u["after"] += d.new_points
        u["reps_changed"] += int(d.changed)
    out = [dict(u, delta=u["after"] - u["before"]) for u in users.values() if u["after"] != u["before"]]
    return sorted(out, key=lambda u: (-abs(u["delta"]), str(u["display_name"])))


def report(diffs: list[RepDiff]) -> str:
    changed = [d for d in diffs if d.changed]
    lines = [f"reps loaded: {len(diffs)}  verdict changed: {len(changed)}  "
             f"valid {sum(d.old_valid for d in diffs)} -> {sum(d.new_valid for d in diffs)}  "
             f"points {sum(d.old_points for d in diffs)} -> {sum(d.new_points for d in diffs)}"]
    flips: dict[str, int] = {}
    for d in changed:
        for r in set(d.new_reasons) - set(d.old_reasons):
            flips[f"+{r}"] = flips.get(f"+{r}", 0) + 1
        for r in set(d.old_reasons) - set(d.new_reasons):
            flips[f"-{r}"] = flips.get(f"-{r}", 0) + 1
    skipped: dict[str, int] = {}
    for d in diffs:
        if d.skipped:
            skipped[d.skipped] = skipped.get(d.skipped, 0) + 1
    for why, n in sorted(skipped.items()):
        lines.append(f"skipped (kept as stored): {n} reps, {why}")
    if flips:
        lines.append("reason changes: " + ", ".join(f"{k}:{v}" for k, v in sorted(flips.items())))
    users = user_deltas(diffs)
    lines.append(f"users whose points change: {len(users)}")
    for u in users:
        lines.append(f"  {u['display_name'] or u['user_id']}: {u['before']} -> {u['after']} ({u['delta']:+d}), "
                     f"{u['reps_changed']} reps changed")
    return "\n".join(lines)


def fetch_rows(store: Store, since: str | None, limit: int) -> list[dict[str, Any]]:
    return list(store.rpc("ch_rejudge_fetch", {"p_since": since, "p_limit": limit}) or [])


def apply_changes(store: Store, diffs: list[RepDiff], thr: dict, version: str, actor: str, reason: str,
                  now: datetime | None = None) -> dict[str, Any]:
    changes = [{"rep_id": d.rep_id, "valid": d.new_valid, "reject_reasons": d.new_reasons, "points": d.new_points}
               for d in diffs if d.changed]
    if not changes:
        return {"ok": True, "changed": 0}
    return store.rpc("ch_rejudge_apply", {"p_changes": changes, "p_judge_version": version, "p_thresholds": thr,
                                          "p_actor": actor, "p_reason": reason,
                                          "p_now": now or datetime.now(timezone.utc)})


def main(argv: list[str] | None = None, store: Store | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--thresholds", required=True, help="JSON file of judge thresholds over DEFAULT_THRESHOLDS")
    ap.add_argument("--since", default=None, help="only reps at/after this timestamp (ISO 8601)")
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--actor", default=None)
    ap.add_argument("--reason", default=None)
    ap.add_argument("--judge-version", default=None)
    a = ap.parse_args(argv)
    if a.apply and not (a.actor and a.reason and a.actor.strip() and a.reason.strip()):
        print("rejudge: --apply needs --actor and --reason", file=sys.stderr)
        return 2
    try:
        thr = merged_thresholds(json.loads(Path(a.thresholds).read_text()))
    except (OSError, ValueError) as e:
        print(f"rejudge: cannot read thresholds {a.thresholds}: {e}", file=sys.stderr)
        return 2
    if store is None:
        from challenge.store import store_from_env
        try:
            store = store_from_env()
        except StoreError as e:
            print(f"rejudge: {e}", file=sys.stderr)
            return 2
    try:
        diffs = rejudge_rows(fetch_rows(store, a.since, a.limit), thr)
    except StoreError as e:
        return _store_error(e)
    print(report(diffs))
    if not a.apply:
        print("dry run: nothing written (add --apply --actor <email> --reason <text>)")
        return 0
    version = a.judge_version or f"{JUDGE_VERSION}.rejudge.{datetime.now(timezone.utc):%Y%m%d}"
    try:
        res = apply_changes(store, diffs, thr, version, a.actor, a.reason)
    except StoreError as e:
        return _store_error(e)
    print(f"applied: {res} (judge_version {version}, audit_log action 'rejudge' by {a.actor})")
    return 0


def _store_error(e: StoreError) -> int:
    msg = str(e)
    if "ch_rejudge" in msg and ("does not exist" in msg or "Could not find" in msg or "404" in msg):
        print(f"NEEDS-SQL: apply {MIGRATION} (ch_rejudge_fetch / ch_rejudge_apply are REQUIRED): {msg}", file=sys.stderr)
    else:
        print(f"rejudge: {msg}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
