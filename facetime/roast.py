"""Roast mode: Brodie trash-talks the form, never the person. Every line is a pre-rendered bank string (facetime/cues_tts.py
vocabulary() includes ROAST_LINES), so say_now plays it on the fast path. Used by starter/examples/roast/handlers.py on live
calls and by scripts/make_demo_video.py --roast.

Rules for new lines: short (under about 2 s spoken), about the rep, the effort or the excuse, never about body, weight, looks or
anything the person can't change, and no dashes (the bank refuses them).
"""
import zlib

# (substring of the fault label, lines); first match wins, so put the specific ones first
ROAST_FAULT = [
    ('chin over the bar', ["That's not a pull up, that's a hug", "The bar is up there, not a rumor", "Chin over the bar, not near it"]),
    ('full hang', ["Straighten those arms, no half credit", "Dead hang first, then we talk"]),
    ('shallow', ["That's a curtsy, not a rep", "Deeper. The floor won't bite", "Half reps, half results"]),
    ('insufficient', ["That's a curtsy, not a rep", "Deeper. The floor won't bite", "Half reps, half results"]),
    ('depth', ["Deeper. The floor won't bite", "Half reps, half results"]),
    ('rom=', ["Full range, not a preview", "Half reps, half results"]),
    ('hips', ["Your hips are freelancing", "Plank, not a tent"]),
    ('knees', ["Your knees are filing a complaint", "Knees, do your job"]),
    ('back', ["Your spine called, it's scared", "Flat back, not a question mark"]),
    ('leaning', ["Chest up, we're not reading the floor", "Your spine called, it's scared"]),
    ('stopping early', ["Quitting already? Bold", "The set isn't over just because you're tired"]),
    ('too fast', ["Slow down, it's not a race", "Speed is not a substitute for reps"]),
    ('too slow', ["My loading screen is faster", "Pick it up, we have places to be"]),
]
ROAST_GENERIC = ["I've seen better form on a folding chair", "Bold choice. Wrong, but bold", "Your coach is watching. So am I"]
ROAST_CLOSE = ["Not bad. Not good either. Same time tomorrow", "You survived. Barely. Proud of you", "That's the set. Your excuses can rest too"]
ROAST_START = "Roast mode on, let's see what you've got"

ROAST_LINES = sorted({ROAST_START, *ROAST_GENERIC, *ROAST_CLOSE, *(l for _, ls in ROAST_FAULT for l in ls)})


def roast_for(label, n=0):
    """A roast line for a fault label ('squats - shallow'); n rotates through the options (pass a counter)."""
    label = (label or '').lower()
    for key, lines in ROAST_FAULT:
        if key in label:
            return lines[n % len(lines)]
    return ROAST_GENERIC[(n + zlib.crc32(label.encode())) % len(ROAST_GENERIC)]


def close_line(n=0):
    return ROAST_CLOSE[n % len(ROAST_CLOSE)]
