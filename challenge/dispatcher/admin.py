"""Dispatcher admin API (CONTRACTS C4, SPEC §9) + internal alert endpoint (SPEC §10).

Routers read their collaborators from app.state (set by create_app): `get_store()`, `clock()`, `token`.

Auth for /admin/*: X-Brodie-Token (constant-time) AND X-Admin-Email on admin_allowlist (checked in the DB on every
request) AND, for mutations, a non-empty X-Admin-Reason (URL-encoded by the site, decoded here).
/internal/alert: X-Brodie-Token only (Caddy also 404s /internal/* from outside). Recipients = config
team_alert_handles (env ADMIN_ALERT_HANDLES overrides when set); quiet hours bypassed; deduped per kind per 10 min.

Raffle (SPEC §2): eligible = registered, non-banned users with >= raffle_min_valid_reps valid reps, sorted by user_id;
winner index = int(sha256(seed + ':' + ','.join(ids)), 16) % n. scripts/raffle.py uses the same functions.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from challenge.dispatcher.ratelimit import rate_limit
from challenge.judge.gates import DEFAULT_THRESHOLDS, JUDGE_VERSION, merged_thresholds
from challenge.messaging.templates import TEMPLATES, render
from challenge.store import Store, StoreError
from challenge.timeutil import next_quiet_end
from scripts import rejudge as rj

logger = logging.getLogger("challenge.dispatcher")

STOP_HINT = " Text STOP to opt out."
BROADCAST_MAX = 1000
REASON_MAX = 500
ALERT_DEDUPE_S = 600
_ALERT_KIND = re.compile(r"^[A-Za-z0-9_.:@/-]{1,64}$")


# ------------------------------------------------------------------ shared helpers

def _store(request: Request) -> Store:
    return request.app.state.get_store()


def _now(request: Request) -> datetime:
    return request.app.state.clock()


def _rpc(store: Store, fn: str, args: dict) -> Any:
    try:
        return store.rpc(fn, args)
    except StoreError as e:
        logger.error("admin store error: %s", e)
        raise HTTPException(503, "store unavailable") from e


def check_token(request: Request, given: str | None) -> None:
    token = getattr(request.app.state, "token", "") or ""
    if not token or given is None or not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(401, "bad token")


def worker_token(request: Request, x_brodie_token: str | None = Header(default=None)) -> None:
    check_token(request, x_brodie_token)


def admin_actor(request: Request, x_brodie_token: str | None = Header(default=None),
                x_admin_email: str | None = Header(default=None)) -> str:
    """Token, then allowlist membership (DB, every request). Returns the normalized admin email (audit actor)."""
    check_token(request, x_brodie_token)
    email = (x_admin_email or "").strip().lower()
    if not email or len(email) > 320 or "@" not in email:
        raise HTTPException(403, "admin email required")
    res = _rpc(_store(request), "ch_admin_allowed", {"p_email": email})
    if not (isinstance(res, dict) and res.get("allowed") is True):
        logger.warning("admin request from non-allowlisted email")
        raise HTTPException(403, "not an admin")
    return email


def admin_reason(x_admin_reason: str | None = Header(default=None)) -> str | None:
    if x_admin_reason is None:
        return None
    try:
        r = unquote(x_admin_reason, errors="strict").strip()
    except UnicodeDecodeError as e:
        raise HTTPException(400, "bad X-Admin-Reason encoding") from e
    return r or None


def require_reason(reason: str | None) -> str:
    if not reason:
        raise HTTPException(400, "X-Admin-Reason required")
    if len(reason) > REASON_MAX:
        raise HTTPException(400, "X-Admin-Reason too long")
    return reason


def _config(store: Store) -> dict[str, Any]:
    cfg = _rpc(store, "ch_config_get", {})
    return cfg if isinstance(cfg, dict) else {}


# ------------------------------------------------------------------ raffle (shared with scripts/raffle.py)

def raffle_index(seed: str, ids: list[str]) -> int:
    if not ids:
        raise ValueError("no eligible users")
    return int(hashlib.sha256((seed + ":" + ",".join(ids)).encode()).hexdigest(), 16) % len(ids)


def raffle_eligible(store: Store) -> tuple[int, list[dict[str, Any]]]:
    """(min_valid_reps, eligible sorted by user_id). Raises StoreError."""
    res = store.rpc("ch_raffle_eligible", {}) or {}
    eligible = sorted(({"user_id": str(e["user_id"]), "display_name": e.get("display_name"),
                        "valid_reps": int(e.get("valid_reps") or 0)} for e in res.get("eligible") or []),
                      key=lambda e: e["user_id"])
    return int(res.get("min_valid_reps")), eligible


def raffle_draw(seed: str, eligible: list[dict[str, Any]], min_valid_reps: int) -> dict[str, Any]:
    """Pure, deterministic draw over an eligible list (already sorted by user_id)."""
    ids = [e["user_id"] for e in eligible]
    joined = ",".join(ids)
    out: dict[str, Any] = {"seed": seed, "min_valid_reps": min_valid_reps, "eligible_count": len(ids),
                           "eligible_hash": hashlib.sha256(joined.encode()).hexdigest(), "index": None, "winner": None}
    if ids:
        i = raffle_index(seed, ids)
        w = eligible[i]
        out["index"] = i
        out["winner"] = {"user_id": w["user_id"], "display_name": w["display_name"], "valid_reps": w["valid_reps"]}
    return out


def validate_seed(seed: str) -> str:
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("seed required")
    if len(seed) > 200:
        raise ValueError("seed too long (max 200)")
    return seed


def run_raffle(store: Store, seed: str, *, dry_run: bool, actor: str | None, reason: str | None,
               now: datetime) -> dict[str, Any]:
    """Compute eligibility + winner; unless dry_run, write one audit_log row ('raffle') with the seed, the eligible
    user_ids and their hash, and the winner. Raises ValueError (bad input) / StoreError."""
    seed = validate_seed(seed)
    if not dry_run and not (actor and actor.strip() and reason and reason.strip()):
        raise ValueError("actor and reason required")
    min_reps, eligible = raffle_eligible(store)
    out = raffle_draw(seed, eligible, min_reps)
    out["dry_run"] = dry_run
    if not dry_run:
        after = {k: out[k] for k in ("seed", "min_valid_reps", "eligible_count", "eligible_hash", "index", "winner")}
        after["eligible_user_ids"] = [e["user_id"] for e in eligible]
        res = store.rpc("ch_admin_audit", {"p_actor": actor, "p_action": "raffle", "p_target": seed,
                                           "p_before": None, "p_after": after, "p_reason": reason, "p_now": now})
        out["audit_id"] = res.get("id") if isinstance(res, dict) else None
    return out


# ------------------------------------------------------------------ /admin router

router = APIRouter(prefix="/admin", dependencies=[Depends(rate_limit("admin"))])


class BroadcastIn(BaseModel):
    body: str | None = None
    template: str | None = None
    ctx: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True


def _broadcast_text(b: BroadcastIn, cfg: dict[str, Any]) -> str:
    if (b.body is None) == (b.template is None):
        raise HTTPException(400, "exactly one of body or template")
    if b.template is not None:
        if b.template not in TEMPLATES:
            raise HTTPException(400, "unknown template")
        try:
            text = render(b.template, {"site_url": cfg.get("site_url"), **b.ctx}, bool(cfg.get("swearing")))
        except (KeyError, ValueError, IndexError) as e:
            raise HTTPException(400, f"template render failed: {e}") from e
    else:
        text = b.body.strip()
        if not text:
            raise HTTPException(400, "body required")
        if len(text) > BROADCAST_MAX:
            raise HTTPException(400, f"body too long (max {BROADCAST_MAX})")
    if not text.endswith(STOP_HINT):  # broadcasts are proactive texts: always carry the opt-out hint
        text += STOP_HINT
    return text


@router.post("/broadcast")
def broadcast(b: BroadcastIn, request: Request, actor: str = Depends(admin_actor),
              reason: str | None = Depends(admin_reason)) -> dict:
    store = _store(request)
    cfg = _config(store)
    text = _broadcast_text(b, cfg)
    now = _now(request)
    if not b.dry_run:
        reason = require_reason(reason)
    quiet = cfg.get("quiet_hours") or [23, 9]
    not_before = next_quiet_end(now, quiet)  # proactive: held until quiet hours end
    res = _rpc(store, "ch_admin_broadcast", {"p_body": text, "p_not_before": not_before, "p_dry_run": b.dry_run,
                                             "p_actor": actor, "p_reason": reason, "p_now": now})
    out = {"recipients": int(res["recipients"]), "sample_body": text, "preview": text, "dry_run": b.dry_run,
           "digest": res.get("digest"), "not_before": not_before.isoformat()}
    if not b.dry_run:
        out.update(enqueued=int(res["enqueued"]), duplicates=int(res["duplicates"]))
        logger.info("broadcast by %s: %s recipients, %s enqueued", actor, out["recipients"], out["enqueued"])
    return out


class RejudgeIn(BaseModel):
    thresholds: dict[str, Any] | None = None
    since: datetime | None = None
    apply: bool = False
    limit: int = Field(default=100_000, ge=1, le=100_000)


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _check_thresholds(thr: dict[str, Any]) -> None:
    """Overrides must be known keys with the default's shape (number, or list of str / list of numbers)."""
    for k, v in thr.items():
        if k not in DEFAULT_THRESHOLDS:
            raise HTTPException(400, f"unknown threshold {k!r}")
        d = DEFAULT_THRESHOLDS[k]
        if isinstance(d, list):
            elem_ok = (lambda x: isinstance(x, str)) if all(isinstance(x, str) for x in d) else _num
            ok = isinstance(v, list) and all(elem_ok(x) for x in v)
        else:
            ok = _num(v)
        if not ok:
            raise HTTPException(400, f"bad value for threshold {k!r}")


@router.post("/rejudge")
def rejudge(b: RejudgeIn, request: Request, actor: str = Depends(admin_actor),
            reason: str | None = Depends(admin_reason)) -> dict:
    if b.apply:
        reason = require_reason(reason)
    if b.since is not None and b.since.tzinfo is None:
        raise HTTPException(400, "since must include a timezone offset")
    overrides = b.thresholds or {}
    _check_thresholds(overrides)
    store = _store(request)
    base = _config(store).get("judge_thresholds")
    thr = merged_thresholds({**(base if isinstance(base, dict) else {}), **overrides})  # empty = current config
    now = _now(request)
    try:
        diffs = rj.rejudge_rows(rj.fetch_rows(store, b.since.isoformat() if b.since else None, b.limit), thr)
    except StoreError as e:
        logger.error("rejudge fetch failed: %s", e)
        raise HTTPException(503, "store unavailable") from e
    changed = [d for d in diffs if d.changed]
    out: dict[str, Any] = {
        "apply": b.apply, "thresholds": thr, "reps_loaded": len(diffs), "reps_changed": len(changed),
        "valid_before": sum(d.old_valid for d in diffs), "valid_after": sum(d.new_valid for d in diffs),
        "points_before": sum(d.old_points for d in diffs), "points_after": sum(d.new_points for d in diffs),
        "users": rj.user_deltas(diffs), "changes": [vars(d) for d in changed[:200]],
        "changes_truncated": len(changed) > 200, "report": rj.report(diffs)}
    if b.apply:
        version = f"{JUDGE_VERSION}.rejudge.{now:%Y%m%d}"
        try:
            out["applied"] = rj.apply_changes(store, diffs, thr, version, actor, reason, now=now)
        except StoreError as e:
            logger.error("rejudge apply failed: %s", e)
            raise HTTPException(503, "store unavailable") from e
        out["judge_version"] = version
        logger.info("rejudge applied by %s: %s reps changed", actor, len(changed))
    return out


class RaffleIn(BaseModel):
    seed: str
    dry_run: bool = False


@router.post("/raffle")
def raffle(b: RaffleIn, request: Request, actor: str = Depends(admin_actor),
           reason: str | None = Depends(admin_reason)) -> dict:
    if not b.dry_run:
        reason = require_reason(reason)
    try:
        validate_seed(b.seed)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    try:
        out = run_raffle(_store(request), b.seed, dry_run=b.dry_run, actor=actor, reason=reason, now=_now(request))
    except StoreError as e:
        logger.error("raffle failed: %s", e)
        raise HTTPException(503, "store unavailable") from e
    logger.info("raffle by %s seed=%r eligible=%s winner=%s", actor, b.seed, out["eligible_count"],
                (out["winner"] or {}).get("user_id"))
    return out


# ------------------------------------------------------------------ /internal router

internal_router = APIRouter(prefix="/internal", dependencies=[Depends(rate_limit("internal"))])


class AlertIn(BaseModel):
    kind: str | None = None
    component: str | None = None  # infra/alert.sh sends {component, message}
    message: str = Field(min_length=1, max_length=2000)


def alert_handles(cfg: dict[str, Any]) -> list[str]:
    """competition_config.team_alert_handles; env ADMIN_ALERT_HANDLES (comma list), when set, overrides it."""
    env = os.environ.get("ADMIN_ALERT_HANDLES", "")
    raw = env.split(",") if env.strip() else cfg.get("team_alert_handles") or []
    if not isinstance(raw, list):
        raw = []
    out: list[str] = []
    for h in raw:
        if isinstance(h, str) and h.strip() and h.strip() not in out:
            out.append(h.strip())
    return out


@internal_router.post("/alert", dependencies=[Depends(worker_token)])
def internal_alert(a: AlertIn, request: Request) -> dict:
    kind = (a.kind or a.component or "").strip()
    if not _ALERT_KIND.match(kind):
        raise HTTPException(400, "kind required ([A-Za-z0-9_.:@/-], max 64)")
    store = _store(request)
    handles = alert_handles(_config(store))
    if not handles:  # non-2xx so alert.sh falls back to email
        logger.error("alert %s dropped: no team_alert_handles configured: %s", kind, a.message)
        raise HTTPException(503, "no alert handles configured")
    now = _now(request)
    bucket = int(now.timestamp() // ALERT_DEDUPE_S)
    body = f"Brodie alert [{kind}]: {a.message.strip()}"
    enqueued = 0
    for h in handles:
        res = _rpc(store, "ch_outbox_enqueue", {
            "p_handle": h, "p_user_id": None, "p_template": "alert", "p_body": body, "p_media_url": None,
            "p_dedupe_key": f"alert:{kind}:{bucket}:{h}", "p_not_before": now, "p_now": now, "p_ctx": None})
        enqueued += 0 if res.get("duplicate") else 1
    logger.warning("alert %s: %s (%d/%d enqueued)", kind, a.message, enqueued, len(handles))
    return {"ok": True, "recipients": len(handles), "enqueued": enqueued, "deduped": enqueued == 0}
