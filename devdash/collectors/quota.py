"""Quota/burn collector — aggregates token events already parsed by the
session collector; no file IO of its own.

Caps are config-supplied estimates (the real account limits aren't exposed
locally); the bars show burn *against your configured budget*, and the
weekly number undercounts anything older than the session files we parse —
both accepted by the spec.
"""

from __future__ import annotations

import time

from devdash.collectors.sessions import SessionCollector
from devdash.models import QuotaWindow


def collect(sessions: SessionCollector, cap_5h: int, cap_week: int,
            now: float | None = None) -> QuotaWindow:
    now = now or time.time()
    t5h, tweek, last_hr, prev_hr = 0, 0, 0, 0
    for st in sessions.files.values():
        for ts, out, inp in st.events:
            tok = out + inp
            age = now - ts
            if age < 0:
                continue
            if age <= 5 * 3600:
                t5h += tok
            if age <= 7 * 24 * 3600:
                tweek += tok
            if age <= 3600:
                last_hr += tok
            elif age <= 2 * 3600:
                prev_hr += tok
    if last_hr > prev_hr * 1.15:
        trend = "up"
    elif last_hr < prev_hr * 0.85:
        trend = "down"
    else:
        trend = "flat"
    return QuotaWindow(
        pct_5h=round(100.0 * t5h / cap_5h, 1) if cap_5h else 0.0,
        pct_week=round(100.0 * tweek / cap_week, 1) if cap_week else 0.0,
        burn_tokens_per_hr=last_hr,
        trend=trend,
        tokens_5h=t5h,
        tokens_week=tweek,
    )
