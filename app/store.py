"""Persistent turn/profile store — the product backbone (no ADK dependency).

Replaces the deleted ``context_store.py`` AND the in-memory ``memory.py`` with
ONE durable thing: a SQLite file (default ``app/data/app.db``) holding

* ``turns``    — every answered question as a forum-style "topic": a deterministic
  ``seq`` (topic number) + readable ``slug`` + the stored panel, chained by
  ``parent_seq`` for follow-ups. Same question in the same context always maps to
  the same ``seq`` (``content_key`` UNIQUE), so links are deterministic/shareable
  and a reload never re-runs the LLM.
* ``profiles`` — the per-user interest profile (tickers/intents/terms) that
  ``memory.py`` used to hold in-process, now durable and usable on the default path.

Stdlib ``sqlite3`` only, WAL mode, schema auto-created on import. Thread-safe for
FastAPI's sync-endpoint threadpool via a single lock-guarded connection.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import secrets
import sqlite3
import threading
import time

# --------------------------------------------------------------------------- #
# Connection / schema
# --------------------------------------------------------------------------- #

_DEFAULT_PATH = pathlib.Path(__file__).parent / "data" / "app.db"
_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None
_CONN_PATH: str | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    content_key     TEXT NOT NULL UNIQUE,
    parent_seq      INTEGER,
    thread_id       TEXT,
    user_id         TEXT,
    query           TEXT NOT NULL,
    intent          TEXT,
    risk_profile    TEXT,
    slug            TEXT NOT NULL,
    tickers_json    TEXT NOT NULL DEFAULT '[]',
    panel_json      TEXT NOT NULL,
    tool_result_json TEXT,        -- M6: grounded tool numbers the LLM saw this turn
    context_prompt  TEXT,         -- M6: exact assembled context sent to the LLM (auditable)
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_thread ON turns(thread_id);
CREATE INDEX IF NOT EXISTS idx_turns_user ON turns(user_id);

CREATE TABLE IF NOT EXISTS profiles (
    user_id       TEXT PRIMARY KEY,
    tickers_json  TEXT NOT NULL DEFAULT '[]',
    intents_json  TEXT NOT NULL DEFAULT '[]',
    terms_json    TEXT NOT NULL DEFAULT '[]',
    updated_at    REAL NOT NULL
);

-- M8: bind a guest user_id to a recovery code so context follows the user to
-- another device. We store only the SHA-256 of the code (never the code itself)
-- and no email/name — zero PII, nothing to leak.
CREATE TABLE IF NOT EXISTS claims (
    code_hash   TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_user ON claims(user_id);
"""

_PROFILE_CAP = 20  # keep only the most-recent N per bucket (matches old memory.py)


def _db_path() -> str:
    return os.getenv("APP_DB_PATH") or str(_DEFAULT_PATH)


def _connect() -> sqlite3.Connection:
    """Return the process-wide connection, (re)opening if the path changed.

    Reopening on a path change keeps tests hermetic: a test can point
    ``APP_DB_PATH`` at a tmp file and get a fresh store.
    """
    global _CONN, _CONN_PATH
    path = _db_path()
    if _CONN is not None and _CONN_PATH == path:
        return _CONN
    if _CONN is not None:
        _CONN.close()
    if path != ":memory:":
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    _CONN, _CONN_PATH = conn, path
    return conn


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_WS_RE = re.compile(r"\s+")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_query(query: str) -> str:
    """Canonical form used for the content key (whitespace-collapsed, lowered)."""
    return _WS_RE.sub(" ", (query or "").strip().lower())


def content_key(query: str, risk_profile: str | None, intent: str | None, parent_seq: int | None) -> str:
    """Deterministic topic key.

    Locked design: a topic is per (question + risk_profile + intent + parent),
    so the same question at a different risk profile is a different topic/number,
    and a follow-up is distinct from the same words asked standalone.
    """
    raw = "|".join(
        [
            normalize_query(query),
            (risk_profile or "").strip().lower(),
            (intent or "").strip().lower(),
            str(parent_seq if parent_seq is not None else ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def slugify(text: str, max_len: int = 60) -> str:
    """Kebab slug for the readable forum link (``#/t/<seq>/<slug>``)."""
    s = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "topic"


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _push_recent(seq: list, value, cap: int = _PROFILE_CAP) -> None:
    """Move-to-end de-duped append, capped to the most-recent ``cap`` (LRU)."""
    if not value:
        return
    if value in seq:
        seq.remove(value)
    seq.append(value)
    del seq[:-cap]


# --------------------------------------------------------------------------- #
# Turns
# --------------------------------------------------------------------------- #


def save_turn(
    *,
    query: str,
    panel_json: str,
    headline: str | None = None,
    intent: str | None = None,
    risk_profile: str | None = None,
    user_id: str | None = None,
    thread_id: str | None = None,
    parent_seq: int | None = None,
    tickers: list[str] | None = None,
    tool_result_json: str | None = None,
    context_prompt: str | None = None,
) -> tuple[int, str]:
    """Persist a turn (idempotent by content key) → ``(seq, slug)``.

    Same question in the same context returns the existing ``(seq, slug)`` without
    inserting a duplicate — this is the deterministic-link / durable-cache key.
    """
    key = content_key(query, risk_profile, intent, parent_seq)
    slug = slugify(headline or query)
    conn = _connect()
    with _LOCK:
        row = conn.execute("SELECT seq, slug FROM turns WHERE content_key = ?", (key,)).fetchone()
        if row is not None:
            return int(row["seq"]), row["slug"]
        cur = conn.execute(
            """
            INSERT INTO turns
                (content_key, parent_seq, thread_id, user_id, query, intent,
                 risk_profile, slug, tickers_json, panel_json, tool_result_json,
                 context_prompt, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                parent_seq,
                thread_id,
                user_id,
                query,
                intent,
                risk_profile,
                slug,
                _dumps(tickers or []),
                panel_json,
                tool_result_json,
                context_prompt,
                time.time(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid), slug


def get_turn(seq: int) -> dict | None:
    """Return a stored turn as a plain dict, or ``None`` if unknown."""
    conn = _connect()
    with _LOCK:
        row = conn.execute("SELECT * FROM turns WHERE seq = ?", (int(seq),)).fetchone()
    return dict(row) if row is not None else None


def update_turn(
    seq: int,
    *,
    panel_json: str,
    tickers: list[str] | None = None,
    tool_result_json: str | None = None,
    context_prompt: str | None = None,
) -> tuple[int, str] | None:
    """Overwrite an existing turn's panel in place, keeping its ``seq``/``slug``.

    Used to *upgrade* a previously LLM-degraded turn once the LLM is available:
    the deterministic ``#/t/<seq>`` link stays stable and shareable while its
    content is refreshed with the real LLM answer. Returns ``(seq, slug)`` or
    ``None`` if the seq is unknown.
    """
    conn = _connect()
    with _LOCK:
        row = conn.execute("SELECT slug FROM turns WHERE seq = ?", (int(seq),)).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE turns
               SET panel_json = ?, tickers_json = ?, tool_result_json = ?, context_prompt = ?
             WHERE seq = ?
            """,
            (panel_json, _dumps(tickers or []), tool_result_json, context_prompt, int(seq)),
        )
        conn.commit()
    return int(seq), row["slug"]


def get_by_content_key(query: str, risk_profile: str | None, intent: str | None, parent_seq: int | None) -> dict | None:
    """Durable-cache lookup: the stored turn for this exact question/context."""
    key = content_key(query, risk_profile, intent, parent_seq)
    conn = _connect()
    with _LOCK:
        row = conn.execute("SELECT * FROM turns WHERE content_key = ?", (key,)).fetchone()
    return dict(row) if row is not None else None


def thread_context(seq: int | None, depth: int = 4) -> dict:
    """Walk the ``parent_seq`` chain → compact context for re-injection into the LLM.

    Returns::

        {
          "summary":    [ {"query","headline"}, ... ]   # oldest→newest, excl. `seq`
          "tickers":    [ ... ]                          # union of focus tickers
          "tool_facts": [ {"seq","intent","facts"}, ... ] # last turns' tool numbers (M6)
        }
    """
    out: dict = {"summary": [], "tickers": [], "tool_facts": []}
    if seq is None:
        return out
    conn = _connect()
    chain: list[sqlite3.Row] = []
    with _LOCK:
        cur = int(seq)
        seen: set[int] = set()
        while cur is not None and cur not in seen and len(chain) < depth:
            seen.add(cur)
            row = conn.execute("SELECT * FROM turns WHERE seq = ?", (cur,)).fetchone()
            if row is None:
                break
            chain.append(row)
            cur = row["parent_seq"]
    chain.reverse()  # oldest → newest
    tickers: list[str] = []
    for row in chain:
        headline = _headline_of(row["panel_json"]) or row["query"]
        out["summary"].append({"query": row["query"], "headline": headline})
        for t in json.loads(row["tickers_json"] or "[]"):
            if t not in tickers:
                tickers.append(t)
        if row["tool_result_json"]:
            out["tool_facts"].append(
                {"seq": int(row["seq"]), "intent": row["intent"], "facts": row["tool_result_json"]}
            )
    out["tickers"] = tickers
    out["tool_facts"] = out["tool_facts"][-2:]  # last 1-2 turns of numbers only
    return out


def _headline_of(panel_json: str | None) -> str | None:
    if not panel_json:
        return None
    try:
        return json.loads(panel_json).get("headline")
    except (ValueError, AttributeError):
        return None


# --------------------------------------------------------------------------- #
# Profiles (durable interest memory)
# --------------------------------------------------------------------------- #


def get_profile(user_id: str | None) -> dict:
    """Return the accumulated interest profile for a user (empty if unknown)."""
    empty = {"tickers": [], "intents": [], "terms": []}
    if not user_id:
        return empty
    conn = _connect()
    with _LOCK:
        row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return empty
    return {
        "tickers": json.loads(row["tickers_json"] or "[]"),
        "intents": json.loads(row["intents_json"] or "[]"),
        "terms": json.loads(row["terms_json"] or "[]"),
    }


def update_profile(
    user_id: str | None,
    *,
    tickers: list[str] | None = None,
    intent: str | None = None,
    term: str | None = None,
) -> None:
    """Accumulate tickers/intent/term into the user's durable profile (LRU-capped)."""
    if not user_id:
        return
    conn = _connect()
    with _LOCK:
        row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
        prof = (
            {
                "tickers": json.loads(row["tickers_json"] or "[]"),
                "intents": json.loads(row["intents_json"] or "[]"),
                "terms": json.loads(row["terms_json"] or "[]"),
            }
            if row is not None
            else {"tickers": [], "intents": [], "terms": []}
        )
        for t in tickers or []:
            _push_recent(prof["tickers"], str(t).upper())
        _push_recent(prof["intents"], intent)
        _push_recent(prof["terms"], term)
        conn.execute(
            """
            INSERT INTO profiles (user_id, tickers_json, intents_json, terms_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                tickers_json=excluded.tickers_json,
                intents_json=excluded.intents_json,
                terms_json=excluded.terms_json,
                updated_at=excluded.updated_at
            """,
            (user_id, _dumps(prof["tickers"]), _dumps(prof["intents"]), _dumps(prof["terms"]), time.time()),
        )
        conn.commit()


def forget(user_id: str | None) -> int:
    """Delete all stored data for a user (privacy "clear my data"). Returns rows removed."""
    if not user_id:
        return 0
    conn = _connect()
    with _LOCK:
        n = conn.execute("DELETE FROM turns WHERE user_id = ?", (user_id,)).rowcount
        n += conn.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,)).rowcount
        n += conn.execute("DELETE FROM claims WHERE user_id = ?", (user_id,)).rowcount
        conn.commit()
    return n


# --------------------------------------------------------------------------- #
# Claims — recovery-code account seam (M8, no PII)
# --------------------------------------------------------------------------- #

# Unambiguous alphabet (no 0/O/1/I/L) → a code a human can retype without confusion.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _hash_code(code: str) -> str:
    """Canonicalize (strip separators/case) then SHA-256 — we store only this."""
    canon = re.sub(r"[^a-z0-9]", "", (code or "").lower())
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _new_code() -> str:
    """A readable 12-char recovery code grouped as XXXX-XXXX-XXXX."""
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


def create_claim(user_id: str | None) -> str | None:
    """Mint a recovery code bound to ``user_id`` and return it (shown once).

    Only the code's hash is persisted, so the plaintext exists solely in the
    response. A user may hold several codes; each maps back to the same user_id.
    """
    if not user_id:
        return None
    code = _new_code()
    conn = _connect()
    with _LOCK:
        conn.execute(
            "INSERT INTO claims (code_hash, user_id, created_at) VALUES (?, ?, ?)",
            (_hash_code(code), user_id, time.time()),
        )
        conn.commit()
    return code


def redeem_claim(code: str | None) -> str | None:
    """Resolve a recovery code back to its canonical ``user_id`` (or ``None``).

    The other device then adopts this ``user_id`` so its turns/profile map into
    the same space — the saved context follows the user across devices.
    """
    if not code or not code.strip():
        return None
    conn = _connect()
    with _LOCK:
        row = conn.execute(
            "SELECT user_id FROM claims WHERE code_hash = ?", (_hash_code(code),)
        ).fetchone()
    return row["user_id"] if row is not None else None
