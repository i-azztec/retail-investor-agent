"""Persistent turn/profile store: determinism, parent-chain context, profiles, forget."""

import json

import pytest

from app import store


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point the store at a throwaway DB file and reset its cached connection."""
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "test.db"))
    store._CONN = None  # force reopen against the tmp path
    store._CONN_PATH = None
    yield store
    if store._CONN is not None:
        store._CONN.close()
    store._CONN = None
    store._CONN_PATH = None


def _panel(headline="Is NVDA a safe buy?"):
    return json.dumps({"headline": headline, "intent": "forensic"})


def test_content_key_is_deterministic(db):
    a = db.content_key("Is NVDA a safe buy?", "cautious", "forensic", None)
    b = db.content_key("  is   nvda a SAFE buy? ", "cautious", "forensic", None)
    assert a == b  # whitespace/case-insensitive normalization
    assert a != db.content_key("Is NVDA a safe buy?", "aggressive", "forensic", None)  # profile matters
    assert a != db.content_key("Is NVDA a safe buy?", "cautious", "forensic", 5)  # parent matters


def test_save_turn_is_idempotent(db):
    seq1, slug1 = db.save_turn(query="Is NVDA a safe buy?", panel_json=_panel(), intent="forensic", risk_profile="cautious")
    seq2, slug2 = db.save_turn(query="is nvda a safe buy?", panel_json=_panel(), intent="forensic", risk_profile="cautious")
    assert (seq1, slug1) == (seq2, slug2)  # same topic → same number, no duplicate row
    assert slug1 == "is-nvda-a-safe-buy"


def test_different_profile_makes_a_new_topic(db):
    seq1, _ = db.save_turn(query="Is NVDA a safe buy?", panel_json=_panel(), intent="forensic", risk_profile="cautious")
    seq2, _ = db.save_turn(query="Is NVDA a safe buy?", panel_json=_panel(), intent="forensic", risk_profile="aggressive")
    assert seq1 != seq2


def test_get_turn_roundtrip(db):
    seq, slug = db.save_turn(query="q", panel_json=_panel("Head"), intent="forensic", tickers=["NVDA"])
    row = db.get_turn(seq)
    assert row is not None
    assert row["slug"] == slug
    assert json.loads(row["tickers_json"]) == ["NVDA"]
    assert db.get_turn(999999) is None


def test_thread_context_walks_parent_chain(db):
    s1, _ = db.save_turn(query="Tell me about NVDA", panel_json=_panel("NVDA overview"), tickers=["NVDA"])
    s2, _ = db.save_turn(query="Is it a safe buy?", panel_json=_panel("NVDA safety"), parent_seq=s1, tickers=["NVDA"])
    s3, _ = db.save_turn(query="Compare with AMD", panel_json=_panel("NVDA vs AMD"), parent_seq=s2, tickers=["AMD"])
    ctx = db.thread_context(s3, depth=4)
    assert [item["query"] for item in ctx["summary"]] == ["Tell me about NVDA", "Is it a safe buy?", "Compare with AMD"]
    assert ctx["tickers"] == ["NVDA", "AMD"]  # union, order-preserved


def test_thread_context_includes_tool_facts(db):
    s1, _ = db.save_turn(query="q1", panel_json=_panel(), intent="forensic", tool_result_json='{"altman_z":3.1}')
    s2, _ = db.save_turn(query="q2", panel_json=_panel(), parent_seq=s1, intent="generic")
    facts = db.thread_context(s2)["tool_facts"]
    assert len(facts) == 1 and facts[0]["intent"] == "forensic"
    assert "altman_z" in facts[0]["facts"]


def test_thread_context_none_seq(db):
    assert db.thread_context(None) == {"summary": [], "tickers": [], "tool_facts": []}


def test_profile_roundtrip_and_cap(db):
    db.update_profile("u1", tickers=["NVDA"], intent="forensic", term="pe-ratio")
    db.update_profile("u1", tickers=["AAPL"], intent="ticker_card")
    prof = db.get_profile("u1")
    assert prof["tickers"] == ["NVDA", "AAPL"]
    assert prof["intents"] == ["forensic", "ticker_card"]
    assert prof["terms"] == ["pe-ratio"]
    for i in range(40):
        db.update_profile("u1", tickers=[f"T{i}"])
    assert len(db.get_profile("u1")["tickers"]) <= 20


def test_profile_no_user_is_noop(db):
    db.update_profile(None, tickers=["NVDA"])
    assert db.get_profile(None) == {"tickers": [], "intents": [], "terms": []}


def test_forget_clears_user_data(db):
    seq, _ = db.save_turn(query="q", panel_json=_panel(), user_id="u2")
    db.update_profile("u2", tickers=["NVDA"])
    removed = db.forget("u2")
    assert removed >= 2
    assert db.get_turn(seq) is None
    assert db.get_profile("u2") == {"tickers": [], "intents": [], "terms": []}


# --------------------------------------------------------------------------- #
# M8 — recovery-code claims (multi-device, no PII)
# --------------------------------------------------------------------------- #


def test_claim_roundtrips_to_same_user(db):
    code = db.create_claim("guest-abc")
    assert code and "-" in code  # readable grouped code
    assert db.redeem_claim(code) == "guest-abc"


def test_redeem_is_separator_and_case_insensitive(db):
    code = db.create_claim("guest-xyz")
    assert db.redeem_claim(code.replace("-", "").lower()) == "guest-xyz"


def test_redeem_unknown_code_returns_none(db):
    assert db.redeem_claim("ZZZZ-ZZZZ-ZZZZ") is None
    assert db.redeem_claim("") is None


def test_store_persists_only_code_hash_not_plaintext(db):
    code = db.create_claim("guest-secret")
    conn = db._connect()
    rows = conn.execute("SELECT code_hash FROM claims").fetchall()
    canon = code.replace("-", "")
    assert all(canon not in r["code_hash"] for r in rows)  # plaintext never stored


def test_forget_also_removes_claims(db):
    code = db.create_claim("guest-gone")
    db.forget("guest-gone")
    assert db.redeem_claim(code) is None
