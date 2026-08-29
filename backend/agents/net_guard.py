"""
Shared offline circuit breaker.

Every outbound dependency here already fails safe — Gemini falls back to the
local classifier, Supabase logging is best-effort, the status board serves a
degraded snapshot. What none of them do is fail FAST. With no network a single
voice turn spent ~30 s waiting on three separate timeouts in series, which is
past the frontend's own 20 s limit: the feature appeared broken even though it
would eventually have answered.

So the first failure trips a breaker and the rest of the request skips its
network calls outright. This matters most for the case it was built for —
running the whole system offline, where local Whisper means voice genuinely
works without internet, and only these timeouts stood in the way.

Deliberately not a full health-check system: no background probing, no retry
schedule. It answers one question ("did the network just fail?") and forgets
after COOLDOWN so a reconnect is picked up without a restart.
"""
from __future__ import annotations

import socket
import time

# How long to keep skipping network calls after a failure. Long enough to spare
# the rest of a request and the next few, short enough that reconnecting does
# not need a restart.
COOLDOWN_SECONDS = 45.0

# Probe budget. A reachable host answers well inside this; an unreachable one
# fails immediately rather than waiting on a DNS or TCP timeout.
PROBE_TIMEOUT = 1.0
PROBE_HOSTS = (("8.8.8.8", 53), ("1.1.1.1", 53))

_offline_until: float = 0.0
_probed_at: float = 0.0
_probe_result: bool = True


def mark_offline() -> None:
    """Called by a dependency whose network call just failed."""
    global _offline_until
    _offline_until = time.monotonic() + COOLDOWN_SECONDS


def mark_online() -> None:
    """Called after a successful call — a working dependency clears the breaker
    even if another one is still failing for its own reasons."""
    global _offline_until, _probed_at
    _offline_until = 0.0
    _probed_at = 0.0


def is_offline() -> bool:
    """True when network calls should be skipped.

    Trusts a recent failure first; otherwise probes once and caches, so the
    FIRST request after losing connectivity is fast too rather than paying the
    full timeout to discover what a 1 s probe already knows.
    """
    global _probed_at, _probe_result
    now = time.monotonic()
    if now < _offline_until:
        return True
    if now - _probed_at < 5.0:
        return not _probe_result
    _probed_at = now
    _probe_result = _reachable()
    if not _probe_result:
        mark_offline()
    return not _probe_result


def _reachable() -> bool:
    for host, port in PROBE_HOSTS:
        try:
            with socket.create_connection((host, port), PROBE_TIMEOUT):
                return True
        except OSError:
            continue
    return False
