"""judge_eval harness: replay labeled clips (or synthetic categories) through the SAME code path as live and score the judge.

    python -m judge_eval.run [--labels judge_eval/labels.yaml] [--clips-dir judge_eval/clips] [--thresholds file.json]
                             [--bench] [--synthetic] [--pose full]

Real clips: rtcoach.video.read_frames -> facetime.pipeline.FramePipeline (judge on, num_poses=2, real MediaPipe, counter
v2, 10 fps frame clock exactly like facetime.replay_local) -> per-rep verdicts. --synthetic: challenge.judge.synth
categories fed through FramePipeline.process_landmarks (no video, no MediaPipe) - the identical judge/counter path.
Output: per-clip table (expected vs got), aggregate, SHIP GATE verdict, optional latency (--bench); writes
judge_eval/results/<ts>.json. Exit code: 0 gate passed, 1 gate failed/incomplete, 2 clips dir / labels missing.

SHIP GATE (SPEC section 6): 0 accepted reps over the cheat categories; >= 90% of clean reps accepted; per-clip clean count
error (|accepted - expected_valid|) <= 1. A cheat category with no clip is reported as needing footage (verdict INCOMPLETE).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent
CHEAT = ("knees", "half", "sag", "pike", "no_lockout", "replay", "two_people")
CLEAN_ACCEPT_MIN = 0.90
CLEAN_COUNT_ERR_MAX = 1
FPS = 10.0


class LabelsError(ValueError):
    pass


@dataclass
class ClipLabel:
    clip: str
    category: str
    camera: str = ""
    expected_valid: int = 0
    expected_rejected: dict[str, int] = field(default_factory=dict)


@dataclass
class ClipResult:
    label: ClipLabel
    reps: list[dict[str, Any]]                     # per rep: {n, t, valid, reasons, in_challenge}
    frame_ms: list[float] = field(default_factory=list)

    @property
    def got_valid(self) -> int:
        return sum(1 for r in self.reps if r["valid"])

    @property
    def got_rejected(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.reps:
            if not r["valid"]:
                for reason in r["reasons"] or ["(none)"]:
                    out[reason] = out.get(reason, 0) + 1
        return out

    @property
    def count_error(self) -> int:
        return abs(self.got_valid - self.label.expected_valid)

    @property
    def multiple_people_reps(self) -> int:
        return sum(1 for r in self.reps if "multiple_people" in r["reasons"])


# ---------------------------------------------------------------- labels

def parse_labels(text: str) -> list[ClipLabel]:
    doc = yaml.safe_load(text)
    items = doc.get("clips") if isinstance(doc, dict) else doc
    if not isinstance(items, list) or not items:
        raise LabelsError("labels: expected a non-empty `clips:` list")
    out: list[ClipLabel] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise LabelsError(f"labels[{i}]: expected a mapping")
        for k in ("clip", "category", "expected_valid"):
            if k not in it:
                raise LabelsError(f"labels[{i}]: missing `{k}`")
        ev = it["expected_valid"]
        if isinstance(ev, bool) or not isinstance(ev, int) or ev < 0:
            raise LabelsError(f"labels[{i}] ({it['clip']}): expected_valid must be an int >= 0")
        er = it.get("expected_rejected") or {}
        if not isinstance(er, dict) or any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in er.values()):
            raise LabelsError(f"labels[{i}] ({it['clip']}): expected_rejected must map reason -> int >= 0")
        if it["category"] in CHEAT and ev != 0:
            raise LabelsError(f"labels[{i}] ({it['clip']}): cheat category {it['category']!r} must have expected_valid 0")
        out.append(ClipLabel(clip=str(it["clip"]), category=str(it["category"]), camera=str(it.get("camera", "")),
                             expected_valid=ev, expected_rejected={str(k): int(v) for k, v in er.items()}))
    return out


# ---------------------------------------------------------------- aggregation + ship gate

def aggregate(results: list[ClipResult]) -> dict[str, Any]:
    cats: dict[str, dict[str, int]] = {}
    for r in results:
        c = cats.setdefault(r.label.category, {"clips": 0, "reps": 0, "accepted": 0, "expected_valid": 0})
        c["clips"] += 1
        c["reps"] += len(r.reps)
        c["accepted"] += r.got_valid
        c["expected_valid"] += r.label.expected_valid
    rejected: dict[str, int] = {}
    for r in results:
        for k, n in r.got_rejected.items():
            rejected[k] = rejected.get(k, 0) + n
    return {"categories": cats, "rejected_by_reason": rejected}


def ship_gate(results: list[ClipResult], required: tuple[str, ...] = CHEAT) -> dict[str, Any]:
    cheat_accepted = {c: sum(r.got_valid for r in results if r.label.category == c) for c in CHEAT
                      if any(r.label.category == c for r in results)}
    missing = [c for c in required if c not in cheat_accepted]
    clean = [r for r in results if r.label.category == "clean"]
    exp = sum(r.label.expected_valid for r in clean)
    acc = sum(min(r.got_valid, r.label.expected_valid) for r in clean)
    clean_rate = (acc / exp) if exp else None
    worst = max((r.count_error for r in clean), default=None)
    checks = {
        "cheat_accepted_zero": all(n == 0 for n in cheat_accepted.values()),
        "clean_accept_ge_90pct": clean_rate is not None and clean_rate >= CLEAN_ACCEPT_MIN,
        "clean_count_error_le_1": bool(clean) and worst is not None and worst <= CLEAN_COUNT_ERR_MAX,
    }
    failed = [k for k, v in checks.items() if not v]
    verdict = "FAIL" if failed else ("INCOMPLETE" if missing else "PASS")
    return {"verdict": verdict, "checks": checks, "cheat_accepted": cheat_accepted, "clean_accept_rate": clean_rate,
            "clean_worst_count_error": worst, "needs_footage": missing, "failed": failed}


def latency_stats(ms: list[float], fps: float = FPS) -> dict[str, float]:
    if not ms:
        return {}
    a = np.asarray(ms, float)
    p50, p95 = float(np.percentile(a, 50)), float(np.percentile(a, 95))
    budget = 1000.0 / fps
    return {"frames": len(ms), "p50_ms": round(p50, 2), "p95_ms": round(p95, 2), "budget_ms": budget,
            "headroom_x": round(budget / p95, 2) if p95 > 0 else float("inf"),
            "max_fps_at_p95": round(1000.0 / p95, 1) if p95 > 0 else float("inf")}


# ---------------------------------------------------------------- running

def _pipeline(thr: dict | None, pose_variant: str | None):
    from facetime.pipeline import COUNTERS, FramePipeline
    return FramePipeline(None, exercise="pushups", pose_variant=pose_variant, trigger="none", judge=True, judge_thr=thr,
                         rep_params=COUNTERS["v2"])


def _collect(r: dict, t_s: float, reps: list[dict]) -> None:
    for n, f in sorted((r.get("judge") or {}).items()):
        reps.append({"n": n, "t": round(t_s, 3), "valid": bool(f["valid"]), "reasons": list(f["reject_reasons"]),
                     "in_challenge": bool(f["in_challenge"]), "metrics": f["metrics"]})


def run_synth_clip(label: ClipLabel, clip, thr: dict | None) -> ClipResult:
    pipe = _pipeline(thr, None)
    reps: list[dict] = []
    ms: list[float] = []
    for f in clip.frames:
        t0 = time.perf_counter()
        r = pipe.process_landmarks(f.img.astype(np.float32), f.world.astype(np.float32), persons=f.persons,
                                   t_ms=round(f.t * 1000), aspect=f.aspect)
        ms.append((time.perf_counter() - t0) * 1000)
        _collect(r, f.t, reps)
    return ClipResult(label, reps, ms)


def run_video_clip(label: ClipLabel, path: Path, thr: dict | None, pose_variant: str = "full") -> ClipResult:
    from rtcoach.video import read_frames
    fr = read_frames(str(path))
    pipe = _pipeline(thr, pose_variant)
    reps: list[dict] = []
    ms: list[float] = []
    try:
        for i in range(len(fr)):
            t0 = time.perf_counter()
            r = pipe.process(fr[i], t_ms=i * 1000.0 / FPS)
            ms.append((time.perf_counter() - t0) * 1000)
            _collect(r, i / FPS, reps)
    finally:
        pipe.close()
    return ClipResult(label, reps, ms)


def synthetic_suite() -> list[tuple[ClipLabel, Any]]:
    from challenge.judge.synth import synth_pushups
    kw = dict(n_reps=6, lead_in_s=2.0, noise=0.002)
    out: list[tuple[ClipLabel, Any]] = []
    for i, (body, side) in enumerate([("short", "left"), ("average", "right"), ("tall", "left")]):
        out.append((ClipLabel(f"synth_clean_{body}_{side}", "clean", f"side-{side}", 6),
                    synth_pushups(body=body, side=side, seed=i, **kw)))
    out.append((ClipLabel("synth_knees", "knees", "side-left", 0, {"knees_down": 6, "hips_sag": 6}), synth_pushups(knees_down=True, **kw)))
    out.append((ClipLabel("synth_half", "half", "side-left", 0, {"too_shallow": 6}), synth_pushups(depth=125.0, **kw)))
    out.append((ClipLabel("synth_sag", "sag", "side-left", 0, {"hips_sag": 6}), synth_pushups(hip_offset=0.12, **kw)))
    out.append((ClipLabel("synth_pike", "pike", "side-left", 0, {"hips_pike": 6}), synth_pushups(hip_offset=-0.15, **kw)))
    out.append((ClipLabel("synth_no_lockout", "no_lockout", "side-left", 0, {"no_lockout": 6}),
                synth_pushups(lockout=140.0, **kw)))
    out.append((ClipLabel("synth_two_people", "two_people", "side-left", 0, {"multiple_people": 6}),
                synth_pushups(extra_person=True, **kw)))
    return out


# ---------------------------------------------------------------- report

def _fmt_rej(d: dict[str, int]) -> str:
    return ",".join(f"{k}:{v}" for k, v in sorted(d.items())) or "-"


def render(results: list[ClipResult], gate: dict, agg: dict, bench: dict | None) -> str:
    rows = [("clip", "category", "exp_valid", "got_valid", "err", "exp_rejected", "got_rejected")]
    for r in results:
        rows.append((r.label.clip, r.label.category, str(r.label.expected_valid), str(r.got_valid), str(r.count_error),
                     _fmt_rej(r.label.expected_rejected), _fmt_rej(r.got_rejected)))
    w = [max(len(x[i]) for x in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w[i]) for i, c in enumerate(row)) for row in rows]
    lines.insert(1, "  ".join("-" * x for x in w))
    lines.append("")
    lines.append("AGGREGATE")
    for c, v in sorted(agg["categories"].items()):
        lines.append(f"  {c:<14} clips={v['clips']} reps={v['reps']} accepted={v['accepted']} expected_valid={v['expected_valid']}")
    lines.append(f"  rejected by reason: {_fmt_rej(agg['rejected_by_reason'])}")
    cr = gate["clean_accept_rate"]
    lines.append("")
    lines.append("SHIP GATE")
    lines.append(f"  cheat accepted == 0 ........ {'ok' if gate['checks']['cheat_accepted_zero'] else 'FAIL'}  {gate['cheat_accepted']}")
    lines.append(f"  clean accepted >= 90% ...... {'ok' if gate['checks']['clean_accept_ge_90pct'] else 'FAIL'}  "
                 f"{'n/a' if cr is None else f'{cr:.1%}'}")
    lines.append(f"  clean count error <= 1 ..... {'ok' if gate['checks']['clean_count_error_le_1'] else 'FAIL'}  "
                 f"worst {gate['clean_worst_count_error']}")
    if gate["needs_footage"]:
        lines.append(f"  needs more footage: {', '.join(gate['needs_footage'])}")
    lines.append(f"VERDICT: {gate['verdict']}")
    if bench:
        lines.append("")
        lines.append(f"LATENCY per frame: p50 {bench['p50_ms']} ms  p95 {bench['p95_ms']} ms over {bench['frames']} frames; "
                     f"budget {bench['budget_ms']:.0f} ms at {FPS:.0f} fps -> headroom {bench['headroom_x']}x "
                     f"(max ~{bench['max_fps_at_p95']} fps at p95)")
    return "\n".join(lines)


def _result_json(results: list[ClipResult], gate: dict, agg: dict, bench: dict | None, mode: str, thr: dict | None) -> dict:
    return {"mode": mode, "thresholds": thr, "gate": gate, "aggregate": agg, "latency": bench,
            "clips": [{"clip": r.label.clip, "category": r.label.category, "camera": r.label.camera,
                       "expected_valid": r.label.expected_valid, "expected_rejected": r.label.expected_rejected,
                       "got_valid": r.got_valid, "got_rejected": r.got_rejected, "count_error": r.count_error,
                       "reps": [{k: v for k, v in x.items() if k != "metrics"} for x in r.reps]} for r in results]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", default=str(ROOT / "labels.yaml"))
    ap.add_argument("--clips-dir", default=str(ROOT / "clips"))
    ap.add_argument("--thresholds", default=None, help="JSON file of judge thresholds over DEFAULT_THRESHOLDS")
    ap.add_argument("--bench", action="store_true", help="report per-frame latency p50/p95 and fps headroom")
    ap.add_argument("--synthetic", action="store_true", help="run challenge.judge.synth categories (no video)")
    ap.add_argument("--pose", default="full")
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    a = ap.parse_args(argv)
    thr = json.loads(Path(a.thresholds).read_text()) if a.thresholds else None
    results: list[ClipResult] = []
    if a.synthetic:
        mode = "synthetic"
        required = tuple(c for c in CHEAT if c != "replay")    # a replayed screen has no synthetic equivalent
        for label, clip in synthetic_suite():
            results.append(run_synth_clip(label, clip, thr))
    else:
        mode = "video"
        required = CHEAT
        cdir, lpath = Path(a.clips_dir), Path(a.labels)
        if not cdir.is_dir():
            print(f"judge_eval: clips dir not found: {cdir} (record clips there, or use --synthetic)", file=sys.stderr)
            return 2
        if not lpath.is_file():
            print(f"judge_eval: labels file not found: {lpath} (copy judge_eval/labels.example.yaml)", file=sys.stderr)
            return 2
        try:
            labels = parse_labels(lpath.read_text())
        except (LabelsError, yaml.YAMLError) as e:
            print(f"judge_eval: bad labels: {e}", file=sys.stderr)
            return 2
        absent = [x.clip for x in labels if not (cdir / x.clip).is_file()]
        if absent:
            print(f"judge_eval: clips listed in labels but missing in {cdir}: {', '.join(absent)}", file=sys.stderr)
            return 2
        for x in labels:
            print(f"replaying {x.clip} ...", file=sys.stderr)
            results.append(run_video_clip(x, cdir / x.clip, thr, a.pose))
    agg = aggregate(results)
    gate = ship_gate(results, required)
    bench = latency_stats([m for r in results for m in r.frame_ms]) if a.bench else None
    print(render(results, gate, agg, bench))
    rdir = Path(a.results_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    out = rdir / (time.strftime("%Y%m%dT%H%M%S") + ".json")
    out.write_text(json.dumps(_result_json(results, gate, agg, bench, mode, thr), indent=1, default=float))
    print(f"wrote {out}")
    return 0 if gate["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
