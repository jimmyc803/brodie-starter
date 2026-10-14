"""Command side effects and deduplicated, non-proactive replies."""
from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any

from challenge.config import Config, alert_handles
from challenge.dispatcher.alerts import health_report
from challenge.dispatcher.postcall import Outbox
from challenge.messaging.commands import parse, split_join_arg, validate_display_name
from challenge.messaging.providers import Inbound, normalize_handle
from challenge.scoring import eta_range, format_eta
from challenge.store import Store
from challenge.timeutil import ET, parse_ts


def handle_inbound(store: Store, cfg: Config, outbox: Outbox, inbound: Inbound,
                   now: datetime) -> None:
    command = parse(inbound.body)
    user = store.rpc("ch_user_by_handle", {"p_handle": inbound.handle})
    user_id = user.get("user_id")
    site = cfg.get("site_url").rstrip("/")
    ctx: dict[str, Any] = {"site_url": site, "rules_url": site + "/rules",
                           "_proactive": False}
    template = "unknown"

    def power_hour() -> str:
        power = store.rpc("ch_power_hour", {"p_now": now})
        if not power:
            return "not announced yet"
        start = parse_ts(power["starts_at"]).astimezone(ET).strftime("%I:%M %p")
        end = parse_ts(power["ends_at"]).astimezone(ET).strftime("%I:%M %p")
        return f"{start}–{end}"

    if command.kind == "LIFE":
        # Team-only (D-40): the same handles that already get the alert texts. Anyone else gets the ordinary
        # unknown-command reply, so a competitor can neither read infra internals nor learn the command exists.
        team = {normalize_handle(h) or h for h in alert_handles(cfg)}
        if (normalize_handle(inbound.handle) or inbound.handle) in team:
            ctx.update(health_report(store, cfg, now))
            template = "life"
    elif command.kind == "LINK":
        # D-25: proves the texter owns this handle; binds it to the web account that issued the code.
        ctx["me_url"] = site + "/me"
        result = store.rpc("ch_web_link", {"p_handle": inbound.handle, "p_code": command.arg, "p_now": now})
        if result["ok"]:
            user_id = result["user_id"]
            ctx["display_name"] = result["display_name"]
            template = "link_ok"
        else:
            template = {"expired": "link_expired", "handle_owned": "link_owned"}.get(result["reason"], "link_bad_code")
    elif command.kind == "HELP":
        template = "help"
    elif command.kind == "DELETE":
        # Request only (no automatic delete). Durable record: the queued 'delete_request' messages row,
        # keyed per handle per ET day so repeats add neither a second reply nor a second team alert.
        day = now.astimezone(ET).date().isoformat()
        digest = hashlib.sha256(inbound.handle.encode()).hexdigest()
        who = user.get("display_name") or (f"user {user_id}" if user_id else f"unjoined handle #{digest[:8]}")
        for team in cfg.get("team_alert_handles") or []:
            outbox.enqueue(handle=team, template="alert",
                           ctx={"condition": "delete_request",
                                "detail": f"Data deletion requested by {who}; delete within 30 days."},
                           dedupe_key=f"delete_alert:{digest}:{day}:{team}", proactive=False)
        outbox.enqueue(user_id=user_id, handle=inbound.handle, template="delete_request", ctx=ctx,
                       dedupe_key=f"delete_request:{digest}:{day}", proactive=False)
        return
    elif command.kind in ("STOP", "START"):
        if user_id:
            store.rpc("ch_set_opt", {"p_user_id": user_id,
                      "p_opted_out": command.kind == "STOP", "p_now": now})
        template = "stop_ack" if command.kind == "STOP" else "start_ack"
    elif command.kind == "JOIN":
        join = split_join_arg(command.arg)
        if (join.ref_code or join.source) and not user_id:
            # Recorded before the name check so the invite survives a retry with a corrected name.
            store.rpc("ch_join_attribution", {"p_handle": inbound.handle, "p_ref_code": join.ref_code,
                                              "p_source": join.source, "p_now": now})
        if not validate_display_name(join.name)[0]:
            template = "join_bad_name"
        else:
            result = store.rpc("ch_join_start", {"p_handle": inbound.handle,
                               "p_display_name": join.name, "p_now": now})
            template = {"ok": "join_confirm_prompt", "bad_name": "join_bad_name",
                        "taken": "join_taken"}.get(result["reason"], "help")
    elif command.kind == "YES":
        result = store.rpc("ch_join_confirm", {"p_handle": inbound.handle, "p_now": now})
        if result["ok"]:
            user = store.rpc("ch_user_by_handle", {"p_handle": inbound.handle})
            user_id = user["user_id"]
            ctx["display_name"] = user["display_name"]
            code = user.get("ref_code")
            ctx["invite_url"] = f"{site}/join?ref={code}" if code else site
            template = "welcome"
        else:
            template = "join_taken" if result["reason"] == "taken" else "not_registered"
    elif command.kind in ("QUEUE", "STATUS", "LEAVE"):
        if not user_id:
            template = "not_registered"
        elif command.kind == "LEAVE":
            store.rpc("ch_queue_leave", {"p_user_id": user_id, "p_reason": "left", "p_now": now})
            template = "left_queue"
        elif command.kind == "STATUS":
            ctx.update(store.rpc("ch_user_status", {"p_user_id": user_id, "p_now": now}))
            ctx.update(position=ctx.get("queue_position") or "not queued", power_hour=power_hour())
            template = "status"
        else:
            result = store.rpc("ch_queue_join", {"p_user_id": user_id, "p_now": now})
            ctx.update(result)
            if result.get("line_open"):
                template = "queue_line_open"
            elif result["reason"] in ("ok", "already", "opted_out_ok"):
                view = store.rpc("ch_queue_view", {"p_now": now})
                ctx["eta"] = format_eta(*eta_range(result["position"] or 1, view["avg_cycle_s"]))
                template = "queue_already" if result["reason"] == "already" else "queue_joined"
            else:
                template = {"at_cap": "queue_at_cap", "in_call": "queue_in_call",
                            "not_registered": "not_registered"}.get(result["reason"], "help")
    elif command.kind == "TOP":
        leaders = store.rpc("ch_leaderboard", {"p_limit": 5, "p_now": now})
        ctx["leaders"] = "; ".join(
            f"#{row['rank']} {row['display_name']} {row['points']} pts" for row in leaders
        ) or "no scores yet"
        template = "top"
    elif command.kind == "RULES":
        ctx["daily_call_cap"] = cfg.get("daily_call_cap")
        template = "rules"
    elif command.kind == "POWER":
        ctx["power_hour"] = power_hour()
        template = "power"
    outbox.enqueue(user_id=user_id, handle=inbound.handle, template=template, ctx=ctx,
                   dedupe_key=f"reply:{inbound.provider_message_id}", proactive=False)
