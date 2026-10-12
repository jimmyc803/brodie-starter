"""Command side effects and deduplicated, non-proactive replies."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from challenge.config import Config
from challenge.dispatcher.postcall import Outbox
from challenge.messaging.commands import parse, validate_display_name
from challenge.messaging.providers import Inbound
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
    template = "help"

    def power_hour() -> str:
        power = store.rpc("ch_power_hour", {"p_now": now})
        if not power:
            return "not announced yet"
        start = parse_ts(power["starts_at"]).astimezone(ET).strftime("%I:%M %p")
        end = parse_ts(power["ends_at"]).astimezone(ET).strftime("%I:%M %p")
        return f"{start}–{end}"

    if command.kind in ("STOP", "START"):
        if user_id:
            store.rpc("ch_set_opt", {"p_user_id": user_id,
                      "p_opted_out": command.kind == "STOP", "p_now": now})
        template = "stop_ack" if command.kind == "STOP" else "start_ack"
    elif command.kind == "JOIN":
        if not validate_display_name(command.arg)[0]:
            template = "join_bad_name"
        else:
            result = store.rpc("ch_join_start", {"p_handle": inbound.handle,
                               "p_display_name": command.arg, "p_now": now})
            template = {"ok": "join_confirm_prompt", "bad_name": "join_bad_name",
                        "taken": "join_taken"}.get(result["reason"], "help")
    elif command.kind == "YES":
        result = store.rpc("ch_join_confirm", {"p_handle": inbound.handle, "p_now": now})
        if result["ok"]:
            user = store.rpc("ch_user_by_handle", {"p_handle": inbound.handle})
            user_id = user["user_id"]
            ctx["display_name"] = user["display_name"]
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
