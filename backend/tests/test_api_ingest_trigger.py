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
