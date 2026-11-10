"""PWA-02 — the attendance / report day is the tenant's LOCAL day (Europe/Sofia), not UTC
(Krum, 09.11.2026); late = before today in that zone, or a phone clock off by > 10 min.
Pure tests (no database): midnight on both sides, and both DST changes of 2026."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.offline_sync import late_reason, local_day, zone

SOFIA = zone("Europe/Sofia")


def at(iso):
    return datetime.fromisoformat(iso).astimezone(timezone.utc)


@pytest.mark.parametrize("utc, day", [
    # winter (UTC+2): 22:30Z is already the next day in Sofia
    ("2026-01-15T21:59:59+00:00", "2026-01-15"),
    ("2026-01-15T22:00:00+00:00", "2026-01-16"),
    # summer (UTC+3): 21:00Z is midnight in Sofia
    ("2026-07-10T20:59:59+00:00", "2026-07-10"),
    ("2026-07-10T21:00:00+00:00", "2026-07-11"),
    # DST starts 29.03.2026 03:00 local (01:00Z): the local day is unbroken
    ("2026-03-28T21:59:59+00:00", "2026-03-28"),
    ("2026-03-28T22:00:00+00:00", "2026-03-29"),
    ("2026-03-29T00:59:59+00:00", "2026-03-29"),
    ("2026-03-29T01:00:00+00:00", "2026-03-29"),
    ("2026-03-29T20:59:59+00:00", "2026-03-29"),
    ("2026-03-29T21:00:00+00:00", "2026-03-30"),
    # DST ends 25.10.2026 04:00 local (01:00Z): the repeated hour stays on the 25th
    ("2026-10-24T20:59:59+00:00", "2026-10-24"),
    ("2026-10-24T21:00:00+00:00", "2026-10-25"),
    ("2026-10-25T00:30:00+00:00", "2026-10-25"),
    ("2026-10-25T01:30:00+00:00", "2026-10-25"),
    ("2026-10-25T21:59:59+00:00", "2026-10-25"),
    ("2026-10-25T22:00:00+00:00", "2026-10-26"),
])
def test_the_day_is_the_sofia_day(utc, day):
    assert local_day(at(utc), SOFIA) == day


def env(captured, offset_ms=0):
    return {"captured_dt": at(captured), "device_clock_offset_ms": offset_ms}


def test_captured_before_local_midnight_and_sent_after_it_is_late():
    # 23:50 Sofia (summer) captured, 00:10 Sofia received: different local days
    assert late_reason(env("2026-07-10T20:50:00+00:00"), at("2026-07-10T21:10:00+00:00"), SOFIA) == "previous_day"


def test_the_same_local_day_is_not_late_even_across_the_utc_midnight():
    # 01:30 and 02:30 Sofia (winter) are 23:30Z and 00:30Z — two UTC days, one Sofia day
    assert late_reason(env("2026-01-15T23:30:00+00:00"), at("2026-01-16T00:30:00+00:00"), SOFIA) is None


def test_the_utc_day_alone_would_be_wrong_here():
    captured, received = at("2026-01-15T21:30:00+00:00"), at("2026-01-15T22:30:00+00:00")
    assert captured.date() == received.date()                  # same UTC day …
    assert late_reason(env("2026-01-15T21:30:00+00:00"), received, SOFIA) == "previous_day"  # … but late


def test_across_the_dst_change_the_local_day_decides():
    # 03:30 local on 25.10 (00:30Z, before the change) and 03:30 local after it (01:30Z)
    assert late_reason(env("2026-10-25T00:30:00+00:00"), at("2026-10-25T01:30:00+00:00"), SOFIA) is None
    assert late_reason(env("2026-10-24T20:30:00+00:00"), at("2026-10-24T21:30:00+00:00"), SOFIA) == "previous_day"


@pytest.mark.parametrize("offset_min, late", [(9, None), (10, None), (11, "clock_skew"), (-11, "clock_skew")])
def test_a_phone_clock_more_than_ten_minutes_off_is_late(offset_min, late):
    now = at("2026-07-10T09:00:00+00:00")
    assert late_reason(env("2026-07-10T08:59:00+00:00", offset_min * 60 * 1000), now, SOFIA) == late


def test_a_record_from_the_future_is_late():
    now = at("2026-07-10T09:00:00+00:00")
    assert late_reason(env((now + timedelta(minutes=11)).isoformat()), now, SOFIA) == "clock_skew"
