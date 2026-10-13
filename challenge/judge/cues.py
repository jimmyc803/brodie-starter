"""Challenge-mode cue phrases (SPEC section 6), pre-recorded and played with CueBank.say_now.

The exact text is part of the audio bank key: facetime.cues_tts.vocabulary() renders every value in CUES.
"""
CUES = {
    'knees_down': "Knees off the floor! That one didn't count.",
    'too_shallow': 'Lower! Get that chest down.',
    'no_lockout': 'Lock those arms out up top!',
    'not_in_frame': 'Get your upper body and knees in frame!',
    'hips': 'Hips in line, straight body!',
    'multiple_people': 'Just you in frame! One person only.',
    'challenge_tap_left': 'Tap your left shoulder',
    'challenge_tap_right': 'Tap your right shoulder',
    'challenge_lift_right': 'Lift your right hand',
    'challenge_lift_hold': 'Hand up, and hold it!',
    'challenge_double_tap': 'Lift a hand twice, quick!',
    'challenge_freeze': 'Freeze!',
    'challenge_go': 'And go!',
    'challenge_passed': 'Challenge passed! Keep going!',
    'challenge_failed': "Challenge failed. Those reps don't count.",
    'not_your_turn': "Not your turn! Text this number JOIN, then QUEUE. I'll text you when you're up.",
    'queued': "Line's busy, but you're in line now! I'll text you when you're up.",
    'at_cap': "That's all your calls for today. Rest up, come back tomorrow!",
    'not_signed_up': "You're not signed up! Text this number JOIN and your name.",
    'competition_over': "The challenge isn't open right now. Watch your texts!",
    'thirty_left': 'Thirty seconds left! Empty the tank!',
    'time_up': 'Time!',
    'check_texts': 'Great work! Check your texts for your score.',
    'power_hour': "It's power hour! Every rep counts double!",
    'hang_up': "That's a wrap! You can hang up now.",
    'welcome': "You're on! Upper body and knees in frame. Let's go!",
    'camera_off': "I can't see you! Turn your camera on so I can count.",
    'try_again': "Something glitched on my end. Hang up and call back in a minute!",
}

# Reject reason -> cue key. None: no spoken cue for that reason.
REASON_CUE = {
    'knees_down': 'knees_down',
    'too_shallow': 'too_shallow',
    'no_lockout': 'no_lockout',
    'not_in_frame': 'not_in_frame',
    'multiple_people': 'multiple_people',
    'hips_sag': 'hips',
    'hips_pike': 'hips',
    'too_fast': None,
    'not_horizontal': 'not_in_frame',
}

def classifier_cue(label):
    """Cue key for a fault-classifier label: any knee label -> knees_down, any sag or hips label -> hips,
    shallow or insufficient depth -> too_shallow; anything else has no cue."""
    low = label.lower()
    if 'knee' in low or 'legs on the floor' in low:
        return 'knees_down'
    if 'sag' in low or 'hips' in low:
        return 'hips'
    if 'shallow' in low or 'insufficient' in low:
        return 'too_shallow'
    return None

def phrases():
    return sorted(set(CUES.values()))

def cue_for_reason(reason):
    """Cue key for a reject reason (None: say nothing). Unknown reasons and unmapped classifier labels give None."""
    if reason.startswith('classifier:'):
        return classifier_cue(reason.split(':', 1)[1])
    return REASON_CUE.get(reason)

# Which reject reason gets the spoken cue when a rep fails several gates (j4): the most useful correction, not the C5
# storage order. Depth is the most common real fault and the clearest fix ("Lower!"), so it outranks the hip line
# (whose angle is coarse and partly view-dependent) and lockout; not_horizontal (mostly the camera angle, or not a
# push-up at all) is last. Classifier labels and unknown reasons come after every listed reason.
CUE_PRIORITY = ('multiple_people', 'not_in_frame', 'knees_down', 'too_shallow', 'no_lockout', 'hips_sag', 'hips_pike',
                'not_horizontal')

def best_cue(reasons):
    """Cue key for a rejected rep: the reason first in CUE_PRIORITY (ties keep the given order) that has a cue."""
    rank = {r: i for i, r in enumerate(CUE_PRIORITY)}
    for r in sorted(reasons, key=lambda r: rank.get(r, len(rank))):
        key = cue_for_reason(r)
        if key:
            return key
    return None

def text_for_reason(reason):
    key = cue_for_reason(reason)
    return CUES[key] if key else None
