"""
The scheduled poll endpoint.

When polling is driven externally this endpoint is the only thing that makes
ingestion happen, and every call spends part of a capped monthly X quota. An
open POST would let anyone drain it.
"""
import pytest
from fastapi import HTTPException

import api.ingestion as ing


def test_open_when_no_token_is_configured(monkeypatch):
    """Keeps the dashboard's demo button working on a local run, and means an
    existing deployment is not broken by the token being introduced."""
    monkeypatch.setattr(ing, "INGEST_TOKEN", "")
    monkeypatch.setattr(ing, "run_pull", lambda: {"status": "ok"})
    assert ing.pull(x_ingest_token=None) == {"status": "ok"}


def test_correct_token_is_accepted(monkeypatch):
    monkeypatch.setattr(ing, "INGEST_TOKEN", "s3cret")
    monkeypatch.setattr(ing, "run_pull", lambda: {"status": "ok"})
    assert ing.pull(x_ingest_token="s3cret") == {"status": "ok"}


@pytest.mark.parametrize("supplied", [None, "", "wrong", "s3cre", "s3secret"])
def test_everything_else_is_rejected(monkeypatch, supplied):
    monkeypatch.setattr(ing, "INGEST_TOKEN", "s3cret")
    called = []
    monkeypatch.setattr(ing, "run_pull", lambda: called.append(1) or {})
    with pytest.raises(HTTPException) as e:
        ing.pull(x_ingest_token=supplied)
    assert e.value.status_code == 401
    assert called == []            # and no quota is spent on a rejected call


def test_status_says_who_is_driving_the_polling(monkeypatch):
    """Without this, 'last_poll was hours ago' is ambiguous between a broken
    scheduler and a tier whose in-process thread stopped when the container
    slept."""
    monkeypatch.setattr(ing, "get_status", lambda: {"configured": True})
    monkeypatch.setattr(ing, "INGEST_TRIGGER", "external")
    monkeypatch.setattr(ing, "INGEST_TOKEN", "s3cret")
    out = ing.status()
    assert out["trigger"] == "external"
    assert out["trigger_token_required"] is True


# ── Log noise vs. real failures ─────────────────────────────────────────────
# "ingest_state read failed" printed on every poll for as long as the table did
# not exist. It is not a failure — it is a one-time setup step with a one-line
# fix — and a line that cries wolf twice an hour trains the reader to skip it.

import db.supabase_client as sbc


class _MissingTable(Exception):
    code = "PGRST205"          # PostgREST's "no such table"


def test_a_missing_table_is_explained_once(monkeypatch, capsys):
    monkeypatch.setattr(sbc, "_missing_table_warned", False)
    for _ in range(4):
        sbc._explain_state_error(_MissingTable("nope"), "read")
    out = capsys.readouterr().out
    assert out.count("does not exist yet") == 1
    # and it says what to do about it, not just what went wrong
    assert "create_tables.sql" in out


def test_the_hint_warns_that_the_fallback_is_not_durable(monkeypatch, capsys):
    """The local file is a fallback, not a solution: it is lost on every
    container restart, which is the whole reason the table exists."""
    monkeypatch.setattr(sbc, "_missing_table_warned", False)
    sbc._explain_state_error(_MissingTable("nope"), "read")
    out = capsys.readouterr().out
    assert "lost whenever the container restarts" in out


def test_a_real_outage_is_reported_every_time(monkeypatch, capsys):
    """Suppression must apply only to the missing table. A database that has
    started refusing connections is news on every attempt."""
    monkeypatch.setattr(sbc, "_missing_table_warned", False)
    for _ in range(3):
        sbc._explain_state_error(ConnectionError("connection refused"), "write")
    out = capsys.readouterr().out
    assert out.count("write failed") == 3
    assert "does not exist yet" not in out


def test_the_missing_table_hint_does_not_suppress_other_errors(monkeypatch, capsys):
    monkeypatch.setattr(sbc, "_missing_table_warned", False)
    sbc._explain_state_error(_MissingTable("nope"), "read")
    sbc._explain_state_error(ConnectionError("refused"), "read")
    out = capsys.readouterr().out
    assert "does not exist yet" in out
    assert "read failed" in out
