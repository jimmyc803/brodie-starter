"""Roast mode handlers: Brodie trash-talks the form (never the person). Run with:

  .venv/bin/python -m facetime.worker --voice gemini --agent-name "" \
      --persona starter/examples/roast/persona.md --handlers starter/examples/roast/handlers.py dev

(or env PERSONA_FILE / HANDLERS_FILE with the same paths). Mid-set: a pre-rendered roast line (facetime/roast.py, in the cue
bank) after a correction, at most one per ROAST_GAP_S so the counts stay clean. Between sets and at the end: one roast from the
Gemini voice (starter/examples/roast/persona.md), which knows the set that just ended.
"""
import time

from facetime.roast import ROAST_START, roast_for

ROAST_GAP_S = 6.0
state = {'last': 0.0, 'n': 0, 'started': False}


def on_event(event, say_now, ask_voice):
    t = event['type']
    if t == 'session' and event.get('state') == 'wait' and not state['started']:
        state['started'] = True; say_now(ROAST_START, 'announce')
    elif t == 'fault' and time.monotonic() - state['last'] >= ROAST_GAP_S:
        state['last'] = time.monotonic()
        say_now(roast_for(event.get('label'), state['n'])); state['n'] += 1
    elif t == 'session' and event.get('state') == 'rest':
        ask_voice('The set just ended: roast it in ONE short sentence using the real numbers, then name what comes next.')
    elif t == 'session' and event.get('state') == 'done':
        ask_voice('The whole session is over: one last roast in one short sentence, then a sincere "proud of you".')
