"""The local harness must mirror Supabase where it has bitten us live (task 36)."""
from __future__ import annotations


def test_pgcrypto_lives_in_extensions_schema(conn):
    schema = conn.execute("select n.nspname from pg_extension e join pg_namespace n on n.oid = e.extnamespace "
                          "where e.extname = 'pgcrypto'").fetchone()[0]
    assert schema == "extensions"


def test_public_functions_do_not_call_pgcrypto_unqualified(conn):
    """Any public function body calling a pgcrypto function must schema-qualify it (extensions.<fn>)."""
    fns = ("gen_random_bytes", "digest", "hmac", "crypt", "gen_salt", "pgp_sym_encrypt", "pgp_sym_decrypt")
    rows = conn.execute("select p.proname, p.prosrc from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
                        "where n.nspname = 'public'").fetchall()
    import re
    bad = [name for name, src in rows for fn in fns
           if re.search(rf"(?<![\w.]){fn}\s*\(", src or "")]
    assert not bad, f"unqualified pgcrypto call in: {sorted(set(bad))}"


def test_new_share_token_works(conn):
    tok = conn.execute("select new_share_token()").fetchone()[0]
    assert isinstance(tok, str) and len(tok) >= 8
