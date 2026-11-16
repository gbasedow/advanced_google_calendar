"""Tests for the conversion helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from custom_components.advanced_google_calendar.convert import (
    build_google_body,
    build_google_time,
    extract_rrule,
    google_event_to_calendar_event,
    replace_rrule,
    strip_rrule_end,
    truncate_recurrence,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


async def test_timed_event(hass: HomeAssistant) -> None:
    """A timed event is converted to local time."""
    event = google_event_to_calendar_event(
        {
            "id": "e1",
            "summary": "Training",
            "location": "Wald",
            "start": {"dateTime": "2026-11-20T18:00:00+01:00"},
            "end": {"dateTime": "2026-11-20T19:30:00+01:00"},
        }
    )
    assert event is not None
    assert event.uid == "e1"
    assert event.recurrence_id is None
    assert event.summary == "Training"
    assert event.location == "Wald"
    assert event.start == dt_util.parse_datetime("2026-11-20T18:00:00+01:00")
    assert event.end - event.start == timedelta(minutes=90)


async def test_all_day_and_instance(hass: HomeAssistant) -> None:
    """Instances get the series id as uid and the rrule of the series."""
    event = google_event_to_calendar_event(
        {
            "id": "s1_20261120",
            "recurringEventId": "s1",
            "start": {"date": "2026-11-20"},
            "end": {"date": "2026-11-21"},
        },
        series_rrule="FREQ=WEEKLY",
    )
    assert event is not None
    assert event.uid == "s1"
    assert event.recurrence_id == "s1_20261120"
    assert event.rrule == "FREQ=WEEKLY"
    assert event.start == date(2026, 11, 20)
    assert event.summary == ""


async def test_unsupported_rrule_and_cancelled(hass: HomeAssistant) -> None:
    """Unsupported rules are dropped, cancelled events skipped."""
    event = google_event_to_calendar_event(
        {
            "id": "e2",
            "summary": "x",
            "recurrence": ["RRULE:FREQ=HOURLY"],
            "start": {"date": "2026-11-20"},
            "end": {"date": "2026-11-20"},
        }
    )
    assert event is not None
    assert event.rrule is None
    assert event.end == date(2026, 11, 21)
    assert google_event_to_calendar_event({"id": "c", "status": "cancelled"}) is None


async def test_build_body(hass: HomeAssistant) -> None:
    """Home Assistant data is converted into a Google body."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    tz = dt_util.get_time_zone("Europe/Berlin")
    body = build_google_body(
        {
            "summary": "Jagd",
            "description": None,
            "dtstart": datetime(2026, 11, 21, 6, 0, tzinfo=tz),
            "dtend": datetime(2026, 11, 21, 9, 0, tzinfo=tz),
        },
        "Europe/Berlin",
        for_patch=True,
    )
    assert body == {
        "summary": "Jagd",
        "description": "",
        "start": {
            "dateTime": "2026-11-21T06:00:00+01:00",
            "timeZone": "Europe/Berlin",
            "date": None,
        },
        "end": {
            "dateTime": "2026-11-21T09:00:00+01:00",
            "timeZone": "Europe/Berlin",
            "date": None,
        },
    }
    assert build_google_time(date(2026, 1, 1), "Europe/Berlin") == {
        "date": "2026-01-01"
    }
    assert build_google_time(date(2026, 1, 1), "Europe/Berlin", for_patch=True) == {
        "date": "2026-01-01",
        "dateTime": None,
        "timeZone": None,
    }


def test_rrule_helpers() -> None:
    """Rules are replaced, stripped and truncated correctly."""
    recurrence = ["RRULE:FREQ=WEEKLY;COUNT=10;BYDAY=MO", "EXDATE:20261123T090000Z"]
    assert extract_rrule(recurrence) == "FREQ=WEEKLY;COUNT=10;BYDAY=MO"
    assert replace_rrule(recurrence, "FREQ=DAILY") == [
        "RRULE:FREQ=DAILY",
        "EXDATE:20261123T090000Z",
    ]
    assert replace_rrule(recurrence, "") == []
    assert (
        strip_rrule_end("FREQ=WEEKLY;UNTIL=20270101;BYDAY=MO") == "FREQ=WEEKLY;BYDAY=MO"
    )

    tz = dt_util.get_time_zone("Europe/Berlin")
    assert truncate_recurrence(
        recurrence, datetime(2026, 11, 30, 10, 0, tzinfo=tz)
    ) == [
        "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130T085959Z",
        "EXDATE:20261123T090000Z",
    ]
    assert truncate_recurrence(["RRULE:FREQ=DAILY"], date(2026, 12, 1)) == [
        "RRULE:FREQ=DAILY;UNTIL=20261130"
    ]
