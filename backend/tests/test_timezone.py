"""Every timestamp a human reads is Bangladesh time, and supplier timestamps
are converted rather than relabelled.

The bug these cover: VivaPe's eSIM endpoints return the upstream carrier's own
naive local strings, and the old parser sliced every value to its first 19
characters and stamped the result UTC. That threw away a real offset when
there was one, and assumed UTC when there wasn't — so an activation reported
as 18:47 was stored as 18:47 UTC and shown to a Dhaka customer as 00:47 the
next day.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.timeutil import DISPLAY_TZ, bd_datestamp, fmt_bd, now_bd, to_bd
from app.services.esim_telemetry_svc import _parse_ts


# --- the display timezone itself -------------------------------------------

def test_display_timezone_is_dhaka_and_six_hours_ahead():
    offset = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc).astimezone(DISPLAY_TZ).utcoffset()
    assert offset.total_seconds() == 6 * 3600


def test_dhaka_has_no_daylight_saving():
    """Checked in both hemisphapheric summers, because a DST assumption that
    only breaks for half the year is the worst kind to carry."""
    for month in (1, 7):
        at = datetime(2026, month, 15, 12, 0, tzinfo=timezone.utc).astimezone(DISPLAY_TZ)
        assert at.utcoffset().total_seconds() == 6 * 3600


def test_to_bd_treats_a_naive_datetime_as_utc():
    """Everything this codebase stores is UTC, so a value that arrives without
    tzinfo must not be read as server-local."""
    assert to_bd(datetime(2026, 9, 28, 10, 0)) == to_bd(
        datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
    )


def test_fmt_bd_renders_bangladesh_time_with_the_zone_named():
    text = fmt_bd(datetime(2026, 9, 28, 10, 7, tzinfo=timezone.utc))
    assert text == "28 Sep 2026, 16:07 (GMT+6)"


def test_fmt_bd_handles_a_missing_value():
    assert fmt_bd(None) == "—"


def test_order_reference_uses_the_bangladesh_date_not_the_utc_one():
    """02:30 in Dhaka is 20:30 the previous day in UTC. An order placed then
    must not carry yesterday's date in its reference."""
    late_evening_utc = datetime(2026, 9, 27, 20, 30, tzinfo=timezone.utc)
    assert bd_datestamp(late_evening_utc) == "20260928"


def test_now_bd_is_the_same_instant_as_now_utc():
    delta = abs((now_bd() - datetime.now(timezone.utc)).total_seconds())
    assert delta < 5


# --- supplier timestamps ----------------------------------------------------

def test_an_offset_in_the_supplier_string_is_honoured_not_discarded():
    """VivaPe's user/profile returns "+01:00". Slicing it off and calling the
    result UTC was an hour's error on every value that carried one."""
    parsed = _parse_ts("2026-09-26T18:47:19+01:00")
    assert parsed == datetime(2026, 9, 26, 17, 47, 19, tzinfo=timezone.utc)


def test_a_utc_z_suffix_is_honoured():
    assert _parse_ts("2026-09-26T18:47:19Z") == datetime(2026, 9, 26, 18, 47, 19, tzinfo=timezone.utc)


def test_fractional_seconds_parse():
    """The format in VivaPe's own published collection."""
    assert _parse_ts("2025-01-22T14:01:45.000Z") == datetime(2025, 1, 22, 14, 1, 45, tzinfo=timezone.utc)


@pytest.mark.parametrize("raw", ["2026-09-26 18:47:19", "2026-09-26T18:47:19"])
def test_a_naive_supplier_string_uses_the_configured_supplier_zone(raw, monkeypatch):
    """No offset means the string is local time somewhere upstream of VivaPe.
    Which zone that is belongs in configuration, not in this function."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPPLIER_TIMEZONE", "Asia/Hong_Kong", raising=False)
    parsed = _parse_ts(raw)
    # 18:47:19 at UTC+8 is 10:47:19 UTC
    assert parsed == datetime(2026, 9, 26, 10, 47, 19, tzinfo=timezone.utc)
    # which a Dhaka customer reads as the same afternoon, not the next morning
    assert fmt_bd(parsed) == "26 Sep 2026, 16:47 (GMT+6)"


def test_changing_the_supplier_zone_changes_only_naive_values(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPPLIER_TIMEZONE", "UTC", raising=False)
    assert _parse_ts("2026-09-26 18:47:19") == datetime(2026, 9, 26, 18, 47, 19, tzinfo=timezone.utc)
    # a value that carries its own offset is unaffected by the setting
    assert _parse_ts("2026-09-26T18:47:19+01:00") == datetime(2026, 9, 26, 17, 47, 19, tzinfo=timezone.utc)


def test_an_unknown_supplier_zone_falls_back_to_utc_rather_than_crashing(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPPLIER_TIMEZONE", "Mars/Olympus_Mons", raising=False)
    assert _parse_ts("2026-09-26 18:47:19") == datetime(2026, 9, 26, 18, 47, 19, tzinfo=timezone.utc)


@pytest.mark.parametrize("raw", [None, "", "not a date", 12345, "2026-13-45 99:99:99"])
def test_an_unparseable_value_is_none_rather_than_a_plausible_wrong_date(raw):
    """A missing activation date is honest. A wrong one gets argued with."""
    assert _parse_ts(raw) is None


def test_every_parsed_value_is_timezone_aware():
    """A naive datetime reaching the API would be serialised without an
    offset, and the browser would then read it as its own local time —
    reintroducing exactly the bug this module fixes, one layer further out."""
    for raw in ("2026-09-26 18:47:19", "2026-09-26T18:47:19Z", "2026-09-26T18:47:19+01:00"):
        parsed = _parse_ts(raw)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timezone.utc.utcoffset(None)


def test_validity_window_length_survives_the_conversion():
    """Converting both ends of a window must not change its duration."""
    start = _parse_ts("2026-09-26 18:47:19")
    end = _parse_ts("2026-09-29 18:46:59")
    assert (end - start).days == 2
    assert 259_000 < (end - start).total_seconds() < 260_000
