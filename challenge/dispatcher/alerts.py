"""Stuck-state alerts (SPEC §10): line_state stuck, outbound failure spike, stale worker heartbeat.

Each condition alerts at most once per 30 minutes. Alerts go to team_alert_handles through the outbox
(template 'alert', non-proactive so quiet hours and opt-out do not apply) and are always logged."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from challenge.store import Json, Store
from challenge.timeutil import parse_ts

logger = logging.getLogger("challenge.alerts")

DEDUPE = timedelta(minutes=30)
HEARTBEAT_STALE = timedelta(minutes=3)
FAIL_RATE = 0.20
MIN_SAMPLE = 5  # a single failure out of two sends is noise, not a spike
WORKER = "worker"


class Alerts:
    def __init__(self, store: Store, cfg: Any, outbox: Any):
        self.store, self.cfg, self.outbox = store, cfg, outbox

    def conditions(self, now: datetime) -> dict[str, str]:
        """Currently-true alert conditions -> human detail."""
        start, end = parse_ts(self.cfg.get("window_start")), parse_ts(self.cfg.get("window_end"))
        if not (start <= now < end):
            return {}
        health = self.store.rpc("ch_jobs_health", {"p_now": now})
        found: dict[str, str] = {}
        thr = timedelta(seconds=int(self.cfg.get("call_count_s")) + int(self.cfg.get("call_reveal_s"))
                        + int(self.cfg.get("in_call_timeout_extra_s")) + int(self.cfg.get("line_offline_gap_s")) + 300)
        if health["queue_len"] > 0:
            for ln in health["lines"]:
                age = now - parse_ts(ln["updated_at"])
                if age > thr:
                    found["line_stuck"] = (f"{ln['line_id']} in '{ln['state']}' for {int(age.total_seconds() // 60)} min "
                                           f"with {health['queue_len']} waiting")
                    break
        sent, failed = int(health["out_sent"]), int(health["out_failed"])
        total = sent + failed
        if total >= MIN_SAMPLE and failed / total > FAIL_RATE:
            found["outbound_failures"] = f"{failed}/{total} outbound texts failed in the last 15 min"
        beat = health["heartbeats"].get(WORKER)
        if beat is None:
            found["worker_heartbeat"] = "no worker heartbeat recorded"
        elif now - parse_ts(beat) > HEARTBEAT_STALE:
            found["worker_heartbeat"] = f"worker heartbeat {int((now - parse_ts(beat)).total_seconds())}s old"
        return found

    def check(self, now: datetime) -> list[str]:
        """Send alerts for conditions not alerted in the last 30 minutes; returns the conditions sent."""
        fired: list[str] = []
        for cond, detail in self.conditions(now).items():
            key = f"alert_last:{cond}"
            last = self.store.rpc("ch_job_get", {"p_key": key})
            if last and now - parse_ts(last["at"]) < DEDUPE:
                continue
            logger.error("ALERT %s: %s", cond, detail)
            handles = self.cfg.get("team_alert_handles") or []
            stamp = int(now.timestamp())
            for h in handles:
                self.outbox.enqueue(handle=h, template="alert", ctx={"condition": cond, "detail": detail},
                                    dedupe_key=f"alert:{cond}:{stamp}:{h}", proactive=False)
            self.store.rpc("ch_job_set", {"p_key": key, "p_value": Json({"at": now.isoformat()}), "p_now": now})
            fired.append(cond)
        return fired
