"""Migration 20261026_challenge_names_with_spaces.sql: display names may hold single internal spaces (D-41).

"JOIN stan lee" registers "stan lee". One rule in one place, ch_valid_display_name, shared by ch_join_start,
ch_web_join, the clients CHECK and challenge/messaging/commands.py.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest

# rpc/tx/NOW come from the registration suite; `tx` is a fixture, so the "unused" import is load-bearing.
from tests.challenge.test_db_misc import NOW, make_user, rpc, tx  # noqa: F401

GOOD = ["stan lee", "Stan Lee", "a b", "Big Mike_2", "a" * 18 + " b", "one two three"]
BAD = ["ab", "a b ", " a b", "a  b", "a\tb", "a" * 19 + " b", "a-b", "a" * 21, ""]


@pytest.mark.parametrize("name", GOOD)
def test_valid_display_name_accepts_single_internal_spaces(tx, name):
    assert tx.execute("select ch_valid_display_name(%s)", (name,)).fetchone()[0] is True


@pytest.mark.parametrize("name", BAD)
def test_valid_display_name_refuses_edge_doubled_and_other_whitespace(tx, name):
    assert tx.execute("select ch_valid_display_name(%s)", (name,)).fetchone()[0] is False


def test_valid_display_name_is_null_safe(tx):
    assert tx.execute("select ch_valid_display_name(null)").fetchone()[0] is False


def test_join_start_registers_a_spaced_name_and_collapses_whitespace(tx):
    assert rpc(tx, "ch_join_start", p_handle="+15550003", p_display_name="  stan   lee  ",
               p_now=NOW) == {"ok": True, "reason": "ok", "display_name": "stan lee"}
    assert tx.execute("select display_name from join_pending").fetchone()[0] == "stan lee"
    assert rpc(tx, "ch_join_confirm", p_handle="+15550003", p_now=NOW)["ok"]
    assert tx.execute("select display_name from clients").fetchone()[0] == "stan lee"


def test_spaced_names_still_collide_case_insensitively(tx):
    make_user(tx, "Stan Lee")
    assert rpc(tx, "ch_join_start", p_handle="+1", p_display_name="stan lee", p_now=NOW)["reason"] == "taken"


def test_web_join_accepts_a_spaced_name(tx):
    r = rpc(tx, "ch_web_join", p_auth_user_id=str(uuid.uuid4()), p_display_name=" stan  lee ",
            p_handle=None, p_now=NOW)
    assert (r["ok"], r["reason"]) == (True, "ok")
    assert tx.execute("select display_name from clients where id=%s", (r["user_id"],)).fetchone()[0] == "stan lee"
    bad = rpc(tx, "ch_web_join", p_auth_user_id=str(uuid.uuid4()), p_display_name="a--b b",
              p_handle=None, p_now=NOW)
    assert bad["reason"] == "bad_name"


def test_the_clients_check_constraint_matches_the_function(tx):
    """The CHECK spells the rule out instead of calling the function, so it has to be kept honest."""
    uid = make_user(tx, "Good Name")
    assert tx.execute("select display_name from clients where id=%s", (uid,)).fetchone()[0] == "Good Name"
    for name in ("bad  name", " bad", "bad ", "ab", "a" * 21):
        with pytest.raises(psycopg.errors.CheckViolation):
            with tx.transaction():
                tx.execute("update clients set display_name=%s where id=%s", (name, uid))
