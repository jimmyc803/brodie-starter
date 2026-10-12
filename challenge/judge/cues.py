"""Challenge-mode cue phrases (SPEC section 6), pre-recorded and played with CueBank.say_now.

The exact text is part of the audio bank key: facetime.cues_tts.vocabulary() renders every value in CUES.
"""
CUES = {
    'knees_down': "Knees up — that one didn't count.",
    'too_shallow': 'Go lower — chest down.',
    'no_lockout': 'Lock out at the top.',
    'not_in_frame': 'Get your whole body in frame — side view.',
    'hips': 'Keep your hips in line.',
    'multiple_people': 'One person in frame only.',
    'challenge_tap_left': 'Tap your left shoulder',
    'challenge_tap_right': 'Tap your right shoulder',
    'challenge_lift_right': 'Lift your right hand',
    'challenge_passed': 'Challenge passed',
    'challenge_failed': 'Challenge failed — reps voided.',
    'not_your_turn': 'Not your turn — text QUEUE to Brodie to get in line.',
    'at_cap': "You've hit today's limit — come back tomorrow.",
    'not_signed_up': "You're not signed up yet — text JOIN and your name to Brodie.",
    'competition_over': 'The competition is over — thanks for playing.',
    'thirty_left': 'Thirty seconds left.',
    'time_up': 'Time!',
    'check_texts': 'Check your texts for your results.',
    'power_hour': 'Power hour — every rep counts double.',
    'hang_up': "Time's up — you can hang up now.",
    'welcome': "You're on — side view, whole body in frame. Go!",
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

def text_for_reason(reason):
    key = cue_for_reason(reason)
    return CUES[key] if key else None
