"""The weighted random drawing: one ticket per valid rep (SPEC section 6, prizes).

The draw has to be reproducible from a recorded seed, or a disputed result cannot be defended: same seed and
same entrants always pick the same winner, whatever order the rows arrive in.
"""
from __future__ import annotations

import pytest

from challenge.scoring import draw_winner, tickets, total_tickets, win_probability


def _e(pid, reps):
    return {"public_id": pid, "display_name": pid.title(), "valid_reps": reps}


def test_one_ticket_per_valid_rep():
    assert tickets(0) == 0
    assert tickets(1) == 1
    assert tickets(137) == 137


def test_reps_never_give_negative_or_fractional_tickets():
    assert tickets(-5) == 0
    assert tickets(None) == 0
    assert tickets(3.7) == 3


def test_power_hour_does_not_double_tickets():
    """Points double in power hour (rep_points); tickets are one per rep, so a 2x rep is still one ticket."""
    assert tickets(10) == 10


def test_total_and_odds():
    rows = [_e("ada", 30), _e("bo", 10), _e("cy", 0)]
    assert total_tickets(rows) == 40
    assert win_probability(30, 40) == pytest.approx(0.75)
    assert win_probability(10, 40) == pytest.approx(0.25)
    assert win_probability(0, 40) == 0.0
    assert win_probability(5, 0) == 0.0


def test_zero_rep_entrants_cannot_win():
    rows = [_e("ada", 0), _e("bo", 0), _e("cy", 1)]
    for s in range(50):
        assert draw_winner(rows, f"seed-{s}")["public_id"] == "cy"


def test_no_tickets_means_no_winner():
    assert draw_winner([], "seed") is None
    assert draw_winner([_e("ada", 0)], "seed") is None


def test_deterministic_for_a_given_seed():
    rows = [_e("ada", 30), _e("bo", 10), _e("cy", 60)]
    first = draw_winner(rows, "draw-2026-10-20")
    for _ in range(20):
        assert draw_winner(rows, "draw-2026-10-20") == first


def test_independent_of_row_order():
    rows = [_e("ada", 30), _e("bo", 10), _e("cy", 60)]
    rev = list(reversed(rows))
    for s in range(30):
        assert draw_winner(rows, f"s{s}") == draw_winner(rev, f"s{s}")


def test_more_reps_means_a_higher_chance():
    """90 tickets against 10 should win far more often across many seeds; the draw is weighted, not uniform."""
    rows = [_e("ada", 90), _e("bo", 10)]
    wins = {"ada": 0, "bo": 0}
    n = 3000
    for s in range(n):
        wins[draw_winner(rows, f"seed-{s}")["public_id"]] += 1
    assert wins["ada"] / n == pytest.approx(0.9, abs=0.03)
    assert wins["bo"] > 0, 'a 10-ticket entrant must still be able to win'


def test_winner_carries_its_odds_for_the_audit_record():
    rows = [_e("ada", 30), _e("bo", 10)]
    w = draw_winner(rows, "seed-1")
    assert w["tickets"] + sum(tickets(r["valid_reps"]) for r in rows if r["public_id"] != w["public_id"]) == 40
    assert w["total_tickets"] == 40
    assert w["probability"] == pytest.approx(w["tickets"] / 40)
    assert w["seed"] == "seed-1"
