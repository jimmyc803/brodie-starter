"""Short Brodie messages. Context keys are the named fields in TEMPLATES.

Link-bearing templates also require their LINK_FIELDS key. Quiet-hour scheduling
and opt-out enforcement belong to the outbox, not this pure renderer.
"""


TEMPLATES: dict[str, str] = {
    "welcome": "You're in, {display_name}! Let's stack clean reps. Text QUEUE to get in line, STATUS for your stats.",
    "join_confirm_prompt": "Clean push-ups earn points; power hour reps earn 2×. Daily call cap applies. One person, one account; 18+, US, iPhone. Reply YES to confirm you're 18+, in the US, and agree to the rules.",
    "join_bad_name": "Let's pick a clean name: 3–20 letters, numbers, or underscores. Text JOIN your_name.",
    "join_taken": "That name's already on the board. Pick another and text JOIN your_name. Your spot is waiting!",
    "queue_joined": "You're in line! Position #{position}, ETA {eta}. {calls_left} calls left today. Get warmed up!",
    "queue_line_open": "Line's open — FaceTime now! {calls_left} calls left today. Let's get clean reps!",
    "queue_at_cap": "You've hit today's call limit. Strong work showing up — come back tomorrow!",
    "queue_already": "You're already in line: #{position}, ETA {eta}. Stay ready!",
    "queue_in_call": "You're already in a call. Focus on those clean reps — you've got this!",
    "youre_up": "You're up! FaceTime now — you've got {claim_window_s}s to claim your turn. Let's go!",
    "missed_slot": "Missed your slot? No sweat. Text QUEUE when you're ready to jump back in.",
    "queue_update": "Moving up! You're #{position} in line, ETA {eta}. Stay loose, stay ready!",
    "left_queue": "You're out of the queue. Text QUEUE when you're ready for another round.",
    "status": "{points} points · {valid_reps} valid reps · rank #{rank}. Calls left: {calls_left}. Streak: {streak} days. Queue: {position}. Power hour: {power_hour} ET.",
    "top": "The top 5: {leaders}. Your next clean rep can move the board!",
    "rules": "Clean reps count. Power hour = 2×. Daily cap: {daily_call_cap} calls. One person, one account; alts give no advantage. 18+, US, iPhone. Full rules:",
    "power": "Today's power hour: {power_hour} ET. Every valid rep during the hour earns 2× points. Bring that energy!",
    "help": "JOIN name to sign up; YES to confirm. QUEUE (Q/LINE), STATUS (S/ME), TOP (LB), LEAVE, RULES, POWER. STOP pauses proactive texts; START resumes.",
    "stop_ack": "You're opted out of proactive texts and out of the queue. Text START to re-enable texts.",
    "start_ack": "Texts are back on! Text QUEUE when you're ready. Let's get after it!",
    "unknown": "Try JOIN name, QUEUE, STATUS, TOP, LEAVE, RULES, or POWER. HELP lists commands. STOP pauses proactive texts; START resumes.",
    "post_call": "Work logged! {valid_reps} valid, {rejected_reps} rejected. +{points_earned} points; total {points}. Rank #{rank}. Streak: {streak} days. Your results:",
    "rank_drop": "You dropped from #{old_rank} to #{rank}. #{next_rank} is {points_gap} points ahead. Clean reps can close that gap!",
    "streak_risk": "Your {streak}-day streak needs a rep today! Text QUEUE and keep it going. You've got this!",
    "ph_announce": "Power hour today: {power_hour} ET. Valid reps earn 2× during the hour. Set your sights and get ready!",
    "ph_warn": "Power hour starts in 15 minutes! Valid reps earn 2× during the hour. Text QUEUE to get ready!",
    "ph_start": "Power hour is LIVE! Every valid rep now earns 2× points. Text QUEUE — let's go!",
    "daily_recap": "Yesterday: +{yesterday_points} points. Total: {points}, rank #{rank}, streak {streak} days. Today's power hour: {power_hour} ET. Keep building!",
    "ending_soon": "The challenge ends {ends_at}! Time for one more strong finish. Text QUEUE and make those clean reps count!",
    "final_results": "That's a wrap! {points} points, rank #{rank}. You showed up and put in the work. Check the final board:",
    "alert": "BRODIE ALERT [{condition}] {detail}",
    "not_registered": "Let's get you on the board! Text JOIN your_name to sign up. Use 3–20 letters, numbers, or underscores.",
}

PROACTIVE_TEMPLATES = frozenset({
    "welcome", "youre_up", "missed_slot", "queue_update", "post_call", "rank_drop",
    "streak_risk", "ph_announce", "ph_warn", "ph_start", "daily_recap",
    "ending_soon", "final_results",
})
LINK_FIELDS = {
    "welcome": "site_url", "join_confirm_prompt": "rules_url", "top": "site_url",
    "rules": "rules_url", "post_call": "result_url", "daily_recap": "site_url",
    "final_results": "site_url",
}
_STOP_HINT = " Text STOP to opt out."


def render(template_key: str, ctx: dict, swearing: bool) -> str:
    """Render up to 320 characters, preserving links and the opt-out hint.

Missing context or unknown templates raise KeyError. Links exceeding the message
budget raise ValueError rather than silently delivering an unusable URL.
"""
    prose = TEMPLATES[template_key].format_map(ctx)
    if swearing:
        prose = "Hell yeah! " + prose
    suffix = ""
    if template_key in LINK_FIELDS:
        suffix += " " + str(ctx[LINK_FIELDS[template_key]])
    if template_key in PROACTIVE_TEMPLATES:
        suffix += _STOP_HINT
    budget = 320 - len(suffix)
    if budget < 32:
        raise ValueError("Message link is too long")
    if len(prose) > budget:
        prose = prose[:budget - 1].rstrip() + "…"
    return prose + suffix
