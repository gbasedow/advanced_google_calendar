"""Tests for setup and the calendar entities."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.advanced_google_calendar.api import GoogleCalendarApiError
from custom_components.advanced_google_calendar.const import DOMAIN
from homeassistant.components.calendar import CalendarEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_SUPPORTED_FEATURES, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import ACCOUNT, FakeGoogleApi

PRIVATE = "calendar.privat"
HOLIDAYS = "calendar.feiertage"
FAMILY = "calendar.familie"
ALL_FEATURES = (
    CalendarEntityFeature.CREATE_EVENT
    | CalendarEntityFeature.DELETE_EVENT
    | CalendarEntityFeature.UPDATE_EVENT
)


def _timed(event_id: str, start, end, **extra: Any) -> dict[str, Any]:
    return {
        "id": event_id,
        "summary": extra.pop("summary", event_id),
        "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Berlin"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Berlin"},
        **extra,
    }


@pytest.fixture(autouse=True)
async def set_tz(hass: HomeAssistant) -> None:
    """Use a fixed time zone."""
    await hass.config.async_set_time_zone("Europe/Berlin")


@pytest.fixture
def series(fake_api: FakeGoogleApi) -> None:
    """A weekly series starting 2026-11-02 10:00 with one listed instance."""
    tz = dt_util.get_time_zone("Europe/Berlin")
    start = dt_util.parse_datetime("2026-11-02T10:00:00").replace(tzinfo=tz)
    master = _timed(
        "s1",
        start,
        start + timedelta(hours=1),
        summary="Rennrad",
        recurrence=[
            "RRULE:FREQ=WEEKLY;COUNT=20",
            "EXDATE;TZID=Europe/Berlin:20261109T100000",
        ],
        colorId="5",
    )
    inst_start = start + timedelta(days=14)
    instance = _timed(
        "s1_20261116T090000Z",
        inst_start,
        inst_start + timedelta(hours=1),
        summary="Rennrad",
        recurringEventId="s1",
        originalStartTime={
            "dateTime": inst_start.isoformat(),
            "timeZone": "Europe/Berlin",
        },
    )
    first = _timed(
        "s1_20261102T090000Z",
        start,
        start + timedelta(hours=1),
        summary="Rennrad",
        recurringEventId="s1",
        originalStartTime={"dateTime": start.isoformat(), "timeZone": "Europe/Berlin"},
    )
    fake_api.resources[ACCOUNT] = {
        "s1": master,
        instance["id"]: instance,
        first["id"]: first,
    }
    fake_api.listed[ACCOUNT] = [first, instance]


async def test_setup_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Only selected calendars become entities, read-only ones without features."""
    assert setup_integration.state is ConfigEntryState.LOADED
    private = hass.states.get(PRIVATE)
    holidays = hass.states.get(HOLIDAYS)
    assert private is not None
    assert holidays is not None
    assert hass.states.get(FAMILY) is None
    assert private.attributes[ATTR_SUPPORTED_FEATURES] == ALL_FEATURES
    assert holidays.attributes.get(ATTR_SUPPORTED_FEATURES, 0) == 0
    assert private.attributes["calendar_id"] == ACCOUNT

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert setup_integration.state is ConfigEntryState.NOT_LOADED


async def test_state_follows_google(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeGoogleApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Changes in Google show up after the polling interval."""
    assert hass.states.get(PRIVATE).state == STATE_OFF
    now = dt_util.now()
    fake_api.listed[ACCOUNT] = [
        _timed(
            "e1", now - timedelta(minutes=5), now + timedelta(hours=1), summary="Jagd"
        )
    ]
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    state = hass.states.get(PRIVATE)
    assert state.state == STATE_ON
    assert state.attributes["message"] == "Jagd"


async def test_get_events_with_series_rrule(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    series: None,
) -> None:
    """Expanded instances carry uid, recurrence_id and the series rule."""
    entity = hass.data["entity_components"]["calendar"].get_entity(PRIVATE)
    events = await entity.async_get_events(
        hass, dt_util.now() - timedelta(days=60), dt_util.now() + timedelta(days=60)
    )
    assert [(e.uid, e.recurrence_id, e.rrule) for e in events] == [
        ("s1", "s1_20261102T090000Z", "FREQ=WEEKLY;COUNT=20"),
        ("s1", "s1_20261116T090000Z", "FREQ=WEEKLY;COUNT=20"),
    ]


async def test_create_event(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeGoogleApi
) -> None:
    """calendar.create_event creates the event in Google."""
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": PRIVATE,
            "summary": "MTB Tour",
            "start_date_time": "2026-11-21 09:00:00",
            "end_date_time": "2026-11-21 12:00:00",
            "location": "Harz",
        },
        blocking=True,
    )
    assert fake_api.calls == [
        (
            "insert",
            ACCOUNT,
            None,
            {
                "summary": "MTB Tour",
                "description": "",
                "location": "Harz",
                "start": {
                    "dateTime": "2026-11-21T09:00:00+01:00",
                    "timeZone": "Europe/Berlin",
                },
                "end": {
                    "dateTime": "2026-11-21T12:00:00+01:00",
                    "timeZone": "Europe/Berlin",
                },
            },
        )
    ]


async def test_create_on_read_only_calendar_fails(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Read-only calendars do not support creating events."""
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "calendar",
            "create_event",
            {
                "entity_id": HOLIDAYS,
                "summary": "x",
                "start_date": "2026-11-21",
                "end_date": "2026-11-22",
            },
            blocking=True,
        )


async def test_ws_update_single_event(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeGoogleApi,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Updating a single event from the UI patches it (all-day)."""
    fake_api.resources[ACCOUNT] = {"e1": {"id": "e1", "start": {"date": "2026-11-20"}}}
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "calendar/event/update",
            "entity_id": PRIVATE,
            "uid": "e1",
            "event": {
                "summary": "Ansitz",
                "dtstart": "2026-11-20",
                "dtend": "2026-11-21",
            },
        }
    )
    result = await client.receive_json()
    assert result["success"], result
    assert fake_api.calls == [
        (
            "patch",
            ACCOUNT,
            "e1",
            {
                "summary": "Ansitz",
                "start": {"date": "2026-11-20", "dateTime": None, "timeZone": None},
                "end": {"date": "2026-11-21", "dateTime": None, "timeZone": None},
            },
        )
    ]


async def test_ws_update_only_this_instance(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeGoogleApi,
    series: None,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Only this occurrence: the instance is patched without recurrence."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "calendar/event/update",
            "entity_id": PRIVATE,
            "uid": "s1",
            "recurrence_id": "s1_20261116T090000Z",
            "event": {
                "summary": "Rennrad (verschoben)",
                "dtstart": "2026-11-16T11:00:00+01:00",
                "dtend": "2026-11-16T12:00:00+01:00",
                "rrule": "FREQ=WEEKLY;COUNT=20",
            },
        }
    )
    result = await client.receive_json()
    assert result["success"], result
    assert len(fake_api.calls) == 1
    action, _, event_id, body = fake_api.calls[0]
    assert (action, event_id) == ("patch", "s1_20261116T090000Z")
    assert "recurrence" not in body
    assert body["summary"] == "Rennrad (verschoben)"


async def test_ws_update_this_and_future(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeGoogleApi,
    series: None,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """This and future: a new series is created and the old one shortened."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "calendar/event/update",
            "entity_id": PRIVATE,
            "uid": "s1",
            "recurrence_id": "s1_20261116T090000Z",
            "recurrence_range": "THISANDFUTURE",
            "event": {
                "summary": "Rennrad lang",
                "dtstart": "2026-11-16T10:00:00+01:00",
                "dtend": "2026-11-16T13:00:00+01:00",
                "rrule": "FREQ=WEEKLY",
            },
        }
    )
    result = await client.receive_json()
    assert result["success"], result
    (insert, patch_call) = fake_api.calls
    assert insert[0] == "insert"
    assert insert[3]["summary"] == "Rennrad lang"
    assert insert[3]["recurrence"] == ["RRULE:FREQ=WEEKLY"]
    assert insert[3]["colorId"] == "5"
    assert insert[3]["start"] == {
        "dateTime": "2026-11-16T10:00:00+01:00",
        "timeZone": "Europe/Berlin",
    }
    assert patch_call[:3] == ("patch", ACCOUNT, "s1")
    assert patch_call[3] == {
        "recurrence": [
            "RRULE:FREQ=WEEKLY;UNTIL=20261116T085959Z",
            "EXDATE;TZID=Europe/Berlin:20261109T100000",
        ]
    }


async def test_this_and_future_rollback(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeGoogleApi,
    series: None,
) -> None:
    """If shortening the old series fails the new series is removed again."""

    async def _fail(*args: Any) -> None:
        raise GoogleCalendarApiError("boom")

    fake_api.async_patch_event = _fail  # type: ignore[method-assign]
    entity = hass.data["entity_components"]["calendar"].get_entity(PRIVATE)
    with pytest.raises(HomeAssistantError):
        await entity.async_update_event(
            "s1",
            {"summary": "x"},
            recurrence_id="s1_20261116T090000Z",
            recurrence_range="THISANDFUTURE",
        )
    assert [c[0] for c in fake_api.calls] == ["insert", "delete"]
    assert fake_api.calls[1][2] == "new1"


@pytest.mark.parametrize(
    ("recurrence_id", "recurrence_range", "expected"),
    [
        (None, None, [("delete", ACCOUNT, "s1", None)]),
        ("s1_20261116T090000Z", "", [("delete", ACCOUNT, "s1_20261116T090000Z", None)]),
        (
            "s1_20261116T090000Z",
            "THISANDFUTURE",
            [
                (
                    "patch",
                    ACCOUNT,
                    "s1",
                    {
                        "recurrence": [
                            "RRULE:FREQ=WEEKLY;UNTIL=20261116T085959Z",
                            "EXDATE;TZID=Europe/Berlin:20261109T100000",
                        ]
                    },
                )
            ],
        ),
        # first occurrence + this and future = whole series
        ("s1_20261102T090000Z", "THISANDFUTURE", [("delete", ACCOUNT, "s1", None)]),
    ],
)
async def test_ws_delete(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeGoogleApi,
    series: None,
    hass_ws_client: WebSocketGenerator,
    recurrence_id: str | None,
    recurrence_range: str | None,
    expected: list,
) -> None:
    """Deleting events, occurrences and parts of series."""
    client = await hass_ws_client(hass)
    msg: dict[str, Any] = {
        "type": "calendar/event/delete",
        "entity_id": PRIVATE,
        "uid": "s1",
    }
    if recurrence_id is not None:
        msg["recurrence_id"] = recurrence_id
    if recurrence_range is not None:
        msg["recurrence_range"] = recurrence_range
    await client.send_json_auto_id(msg)
    result = await client.receive_json()
    assert result["success"], result
    assert fake_api.calls == expected


async def test_service_list_events(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    series: None,
) -> None:
    """list_events returns uid / recurrence_id."""
    response = await hass.services.async_call(
        DOMAIN,
        "list_events",
        {
            "entity_id": PRIVATE,
            "start_date_time": "2026-10-01 00:00:00",
            "duration": {"days": 90},
        },
        blocking=True,
        return_response=True,
    )
    events = response[PRIVATE]["events"]
    assert events[1]["uid"] == "s1"
    assert events[1]["recurrence_id"] == "s1_20261116T090000Z"
    assert events[1]["rrule"] == "FREQ=WEEKLY;COUNT=20"
    assert events[1]["start"] == "2026-11-16T10:00:00+01:00"


async def test_service_update_event_partial(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeGoogleApi,
    series: None,
) -> None:
    """update_event only changes the given fields; rrule keeps EXDATE."""
    await hass.services.async_call(
        DOMAIN,
        "update_event",
        {"entity_id": PRIVATE, "uid": "s1", "location": "Eifel", "rrule": "FREQ=DAILY"},
        blocking=True,
    )
    assert fake_api.calls == [
        (
            "patch",
            ACCOUNT,
            "s1",
            {
                "location": "Eifel",
                "recurrence": [
                    "RRULE:FREQ=DAILY",
                    "EXDATE;TZID=Europe/Berlin:20261109T100000",
                ],
            },
        )
    ]


async def test_service_update_event_validation(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Start without end is rejected."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "update_event",
            {"entity_id": PRIVATE, "uid": "e1", "start_date": "2026-11-20"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "update_event",
            {"entity_id": PRIVATE, "uid": "e1"},
            blocking=True,
        )


async def test_service_delete_event(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeGoogleApi
) -> None:
    """delete_event deletes in Google."""
    await hass.services.async_call(
        DOMAIN, "delete_event", {"entity_id": PRIVATE, "uid": "e9"}, blocking=True
    )
    assert fake_api.calls == [("delete", ACCOUNT, "e9", None)]


async def test_auth_error_starts_reauth(
    hass: HomeAssistant,
    setup_credentials: None,
    config_entry: MockConfigEntry,
    fake_api: FakeGoogleApi,
) -> None:
    """A revoked token leads to a reauth flow."""
    fake_api.fail_auth = True
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"


async def test_token_refresh_does_not_reload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Updating entry.data (token refresh) must not reload the entry."""
    entity_before = hass.data["entity_components"]["calendar"].get_entity(PRIVATE)
    hass.config_entries.async_update_entry(
        setup_integration,
        data={
            **setup_integration.data,
            "token": {**setup_integration.data["token"], "access_token": "new"},
        },
    )
    await hass.async_block_till_done()
    assert (
        hass.data["entity_components"]["calendar"].get_entity(PRIVATE) is entity_before
    )


async def test_options_change_removes_entity(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Deselecting a calendar in the options removes its entity."""
    registry = er.async_get(hass)
    assert registry.async_get(HOLIDAYS) is not None

    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "calendars": [ACCOUNT, "family@group.calendar.google.com"],
            "scan_interval": 10,
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    assert setup_integration.options == {
        "calendars": [ACCOUNT, "family@group.calendar.google.com"],
        "scan_interval": 10,
    }
    assert registry.async_get(HOLIDAYS) is None
    assert hass.states.get(HOLIDAYS) is None
    assert hass.states.get(FAMILY) is not None


async def test_options_require_one_calendar(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """At least one calendar must stay selected."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"calendars": [], "scan_interval": 5}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"calendars": "no_calendar_selected"}


async def test_friendly_name_is_calendar_name(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The calendar view shows only the calendar name (no account prefix)."""
    assert hass.states.get(PRIVATE).attributes["friendly_name"] == "Privat"
    assert hass.states.get(HOLIDAYS).attributes["friendly_name"] == "Feiertage"


async def test_existing_entity_id_is_kept(
    hass: HomeAssistant,
    setup_credentials: None,
    config_entry: MockConfigEntry,
    fake_api: FakeGoogleApi,
) -> None:
    """Entities created by older versions keep their entity_id."""
    config_entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "calendar",
        DOMAIN,
        f"{ACCOUNT}-{ACCOUNT}",
        suggested_object_id="user_example_com_privat",
        config_entry=config_entry,
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("calendar.user_example_com_privat")
    assert state is not None
    assert state.attributes["friendly_name"] == "Privat"
    assert hass.states.get(PRIVATE) is None


async def test_no_device_and_legacy_device_removed(
    hass: HomeAssistant,
    setup_credentials: None,
    config_entry: MockConfigEntry,
    fake_api: FakeGoogleApi,
) -> None:
    """Calendars belong directly to the entry; an old device is removed."""
    config_entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, ACCOUNT)},
        name="Advanced Google Calendar",
    )
    entity_registry.async_get_or_create(
        "calendar",
        DOMAIN,
        f"{ACCOUNT}-{ACCOUNT}",
        suggested_object_id="user_example_com_privat",
        config_entry=config_entry,
        device_id=device.id,
    )
    entity_registry.async_update_entity(
        "calendar.user_example_com_privat", name="Mein Kalender"
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert device_registry.async_get(device.id) is None
    assert (
        dr.async_entries_for_config_entry(device_registry, config_entry.entry_id) == []
    )
    entry = entity_registry.async_get("calendar.user_example_com_privat")
    assert entry is not None
    assert entry.device_id is None
    assert entry.name == "Mein Kalender"
    state = hass.states.get("calendar.user_example_com_privat")
    assert state.attributes["friendly_name"] == "Mein Kalender"
    holidays = entity_registry.async_get(HOLIDAYS)
    assert holidays is not None
    assert holidays.device_id is None
