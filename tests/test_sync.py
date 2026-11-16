"""Tests for the one-way calendar sync action."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.advanced_google_calendar.api import GoogleCalendarApiError
from custom_components.advanced_google_calendar.const import DOMAIN
from homeassistant.components.calendar import (
    DATA_COMPONENT,
    CalendarEntity,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import ACCOUNT, FakeGoogleApi

TARGET = "calendar.user_example_com_privat"
READ_ONLY = "calendar.user_example_com_feiertage"
SOURCE = "calendar.quelle"
HOLIDAYS_ID = "holidays@group.v.calendar.google.com"


class FakeSource(CalendarEntity):
    """A calendar of another integration."""

    _attr_name = "Quelle"
    _attr_should_poll = False

    def __init__(self) -> None:
        """Initialize."""
        self.events: list[CalendarEvent] = []
        self.calls: list[tuple[datetime, datetime]] = []

    @property
    def event(self) -> CalendarEvent | None:
        """No current event."""
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the configured events."""
        self.calls.append((start_date, end_date))
        return list(self.events)


@pytest.fixture(autouse=True)
async def set_tz(hass: HomeAssistant) -> None:
    """Use a fixed time zone."""
    await hass.config.async_set_time_zone("Europe/Berlin")


@pytest.fixture
async def source(hass: HomeAssistant, setup_integration: MockConfigEntry) -> FakeSource:
    """Add a non-Google source calendar with two events."""
    entity = FakeSource()
    tz = dt_util.get_time_zone("Europe/Berlin")
    entity.events = [
        CalendarEvent(
            uid="t1",
            summary="Training MTB",
            description="Trails",
            location="Wald",
            start=datetime(2026, 11, 20, 18, 0, tzinfo=tz),
            end=datetime(2026, 11, 20, 20, 0, tzinfo=tz),
        ),
        CalendarEvent(
            uid="a1",
            summary="Drückjagd",
            description="Revier Nord",
            location="Hochsitz 3",
            start=date(2026, 11, 22),
            end=date(2026, 11, 23),
        ),
    ]
    await hass.data[DATA_COMPONENT].async_add_entities([entity])
    await hass.async_block_till_done()
    assert hass.states.get(SOURCE) is not None
    return entity


async def _sync(hass: HomeAssistant, **data: Any) -> dict[str, Any]:
    response = await hass.services.async_call(
        DOMAIN,
        "sync_calendar",
        {"entity_id": TARGET, "source_entity_id": SOURCE, **data},
        blocking=True,
        return_response=True,
    )
    return response[TARGET]


def _mirrors(api: FakeGoogleApi) -> dict[str, dict[str, Any]]:
    return {
        item["summary"]: item
        for item in api.listed.get(ACCOUNT, [])
        if "agcSource" in ((item.get("extendedProperties") or {}).get("private") or {})
    }


async def test_create_and_idempotent(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """First run creates the mirrors, the second run changes nothing."""
    result = await _sync(hass)
    assert result == {
        "created": 2,
        "updated": 0,
        "deleted": 0,
        "unchanged": 0,
        "errors": [],
    }
    mirrors = _mirrors(fake_api)
    timed = mirrors["Training MTB"]
    assert timed["description"] == "Trails"
    assert timed["location"] == "Wald"
    assert timed["start"] == {
        "dateTime": "2026-11-20T18:00:00+01:00",
        "timeZone": "Europe/Berlin",
    }
    assert timed["reminders"] == {"useDefault": False, "overrides": []}
    assert timed["extendedProperties"]["private"]["agcSource"] == SOURCE
    assert "recurrence" not in timed
    assert mirrors["Drückjagd"]["start"] == {"date": "2026-11-22"}

    fake_api.calls.clear()
    result = await _sync(hass)
    assert result["unchanged"] == 2
    assert result["created"] == result["updated"] == result["deleted"] == 0
    assert fake_api.calls == []
    assert {
        c["private_extended_property"]
        for c in fake_api.list_calls
        if c["private_extended_property"]
    } == {f"agcSource={SOURCE}"}


async def test_source_changes_are_applied(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """Changed events are patched, removed events deleted."""
    await _sync(hass)
    tz = dt_util.get_time_zone("Europe/Berlin")
    source.events = [
        CalendarEvent(
            uid="t1",
            summary="Training Rennrad",
            start=datetime(2026, 11, 21, 9, 0, tzinfo=tz),
            end=datetime(2026, 11, 21, 12, 0, tzinfo=tz),
        )
    ]
    fake_api.calls.clear()
    result = await _sync(hass)
    assert (result["created"], result["updated"], result["deleted"]) == (0, 1, 1)
    mirrors = _mirrors(fake_api)
    assert set(mirrors) == {"Training Rennrad"}
    assert (
        mirrors["Training Rennrad"]["start"]["dateTime"] == "2026-11-21T09:00:00+01:00"
    )
    assert mirrors["Training Rennrad"]["description"] == ""


async def test_foreign_events_untouched(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """Own events and mirrors of other sources in the target are never touched."""
    fake_api.listed[ACCOUNT] = [
        {"id": "own", "summary": "Eigener Termin", "start": {"date": "2026-11-20"}},
        {
            "id": "other",
            "summary": "Andere Quelle",
            "start": {"date": "2026-11-20"},
            "extendedProperties": {
                "private": {"agcSource": "calendar.other", "agcKey": "x"}
            },
        },
    ]
    source.events = []
    result = await _sync(hass)
    assert result["deleted"] == 0
    assert fake_api.calls == []
    assert {item["id"] for item in fake_api.listed[ACCOUNT]} == {"own", "other"}


async def test_include_details_toggle(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """Switching include_details updates already mirrored events."""
    await _sync(hass)
    result = await _sync(hass, include_details=False)
    assert result["updated"] == 2
    for mirror in _mirrors(fake_api).values():
        assert mirror["description"] == ""
        assert mirror["location"] == ""

    result = await _sync(hass, include_details=False)
    assert result["unchanged"] == 2

    result = await _sync(hass, include_details=True)
    assert result["updated"] == 2
    assert _mirrors(fake_api)["Drückjagd"]["location"] == "Hochsitz 3"


async def test_include_all_day_toggle(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """Disabling all-day events removes their mirrors, enabling restores them."""
    await _sync(hass)
    result = await _sync(hass, include_all_day=False)
    assert (result["deleted"], result["unchanged"]) == (1, 1)
    assert set(_mirrors(fake_api)) == {"Training MTB"}

    result = await _sync(hass, include_all_day=True)
    assert (result["created"], result["unchanged"]) == (1, 1)
    assert set(_mirrors(fake_api)) == {"Training MTB", "Drückjagd"}


async def test_regex_filters(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """Include/exclude expressions select events by title."""
    result = await _sync(hass, include_regex="training")
    assert result["created"] == 1
    assert set(_mirrors(fake_api)) == {"Training MTB"}

    # Exclude wins over include
    result = await _sync(hass, include_regex="training|jagd", exclude_regex="MTB")
    assert (result["created"], result["deleted"]) == (1, 1)
    assert set(_mirrors(fake_api)) == {"Drückjagd"}

    # Regex removed: everything again
    result = await _sync(hass)
    assert (result["created"], result["unchanged"]) == (1, 1)


async def test_invalid_regex(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """An invalid expression fails before anything is written."""
    with pytest.raises(ServiceValidationError, match="include_regex"):
        await _sync(hass, include_regex="(")
    assert fake_api.calls == []


async def test_dry_run(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """A dry run only reports the changes."""
    result = await _sync(hass, dry_run=True)
    assert result["dry_run"] is True
    assert result["created"] == 2
    assert sorted(result["to_create"]) == ["Drückjagd", "Training MTB"]
    assert fake_api.calls == []


async def test_window(
    hass: HomeAssistant,
    fake_api: FakeGoogleApi,
    source: FakeSource,
    freezer: FrozenDateTimeFactory,
) -> None:
    """days_past / days_future define the synchronized range."""
    freezer.move_to("2026-11-16T10:30:00+01:00")
    await _sync(hass, days_past=3, days_future=10)
    tz = dt_util.get_time_zone("Europe/Berlin")
    expected = (
        datetime(2026, 11, 13, 0, 0, tzinfo=tz),
        datetime(2026, 11, 27, 0, 0, tzinfo=tz),
    )
    assert source.calls[-1] == expected
    sync_calls = [c for c in fake_api.list_calls if c["private_extended_property"]]
    assert len(sync_calls) == 1
    assert (sync_calls[0]["time_min"], sync_calls[0]["time_max"]) == expected


async def test_validation(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """Invalid combinations are rejected."""
    with pytest.raises(ServiceValidationError, match="different"):
        await _sync(hass, source_entity_id=TARGET)
    with pytest.raises(ServiceValidationError, match="not found"):
        await _sync(hass, source_entity_id="calendar.does_not_exist")
    with pytest.raises(ServiceValidationError, match="read-only"):
        await hass.services.async_call(
            DOMAIN,
            "sync_calendar",
            {"entity_id": READ_ONLY, "source_entity_id": SOURCE},
            blocking=True,
            return_response=True,
        )
    assert fake_api.calls == []


async def test_google_source_skips_mirrors(
    hass: HomeAssistant, fake_api: FakeGoogleApi, setup_integration: MockConfigEntry
) -> None:
    """Events that are mirrors themselves are not mirrored again."""
    fake_api.listed[HOLIDAYS_ID] = [
        {
            "id": "h1",
            "summary": "Feiertag",
            "start": {"date": "2026-12-25"},
            "end": {"date": "2026-12-26"},
        },
        {
            "id": "m1",
            "summary": "Abbild",
            "start": {"date": "2026-12-24"},
            "end": {"date": "2026-12-25"},
            "extendedProperties": {"private": {"agcSource": "x", "agcKey": "k"}},
        },
    ]
    result = await _sync(hass, source_entity_id=READ_ONLY, days_future=60)
    assert result["created"] == 1
    assert set(_mirrors(fake_api)) == {"Feiertag"}
    registry_id = er.async_get(hass).async_get(READ_ONLY).id
    assert (
        _mirrors(fake_api)["Feiertag"]["extendedProperties"]["private"]["agcSource"]
        == registry_id
    )


async def test_single_errors_are_collected(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """A failing event does not stop the other ones."""
    original = fake_api.async_insert_event

    async def _insert(calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if body["summary"] == "Drückjagd":
            raise GoogleCalendarApiError("quota")
        return await original(calendar_id, body)

    fake_api.async_insert_event = _insert  # type: ignore[method-assign]
    result = await _sync(hass)
    assert result["errors"] == ["create 'Drückjagd': quota"]
    assert set(_mirrors(fake_api)) == {"Training MTB"}


async def test_duplicate_uids_get_distinct_keys(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """Expanded series without recurrence_id (same uid) are mirrored separately."""
    tz = dt_util.get_time_zone("Europe/Berlin")
    start = datetime(2026, 11, 18, 7, 0, tzinfo=tz)
    source.events = [
        CalendarEvent(
            uid="series",
            summary="Pendeln",
            start=start + timedelta(days=offset),
            end=start + timedelta(days=offset, hours=1),
        )
        for offset in range(3)
    ]
    result = await _sync(hass)
    assert result["created"] == 3
    result = await _sync(hass)
    assert result["unchanged"] == 3


async def test_remove_mirror_with_never_matching_regex(
    hass: HomeAssistant, fake_api: FakeGoogleApi, source: FakeSource
) -> None:
    """The documented way to remove all mirrors of a source works."""
    await _sync(hass)
    result = await _sync(hass, include_regex="^$a")
    assert result["deleted"] == 2
    assert _mirrors(fake_api) == {}
