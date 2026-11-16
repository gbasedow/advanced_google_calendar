"""Fixtures for Advanced Google Calendar tests."""

from __future__ import annotations

from collections.abc import Generator
import copy
import time
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.advanced_google_calendar.api import (
    GoogleCalendarAuthError,
    GoogleCalendarInfo,
    GoogleCalendarNotFoundError,
)
from custom_components.advanced_google_calendar.const import (
    CONF_CALENDARS,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

ACCOUNT = "user@example.com"
CLIENT_ID = "client-id"
CLIENT_SECRET = "client-secret"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations."""


class FakeGoogleApi:
    """In-memory fake of GoogleCalendarApi recording all write calls."""

    def __init__(self) -> None:
        self.calendars = [
            GoogleCalendarInfo(ACCOUNT, "Privat", "owner", primary=True),
            GoogleCalendarInfo("family@group.calendar.google.com", "Familie", "writer"),
            GoogleCalendarInfo(
                "holidays@group.v.calendar.google.com", "Feiertage", "reader"
            ),
        ]
        # calendar id -> list of (expanded) event items returned by list_events
        self.listed: dict[str, list[dict[str, Any]]] = {}
        # calendar id -> event id -> event resource returned by get_event
        self.resources: dict[str, dict[str, dict[str, Any]]] = {}
        self.calls: list[tuple[str, str, str | None, dict[str, Any] | None]] = []
        self.fail_auth = False
        self._counter = 0

    async def async_list_calendars(self) -> list[GoogleCalendarInfo]:
        if self.fail_auth:
            raise GoogleCalendarAuthError("401")
        return list(self.calendars)

    async def async_list_events(
        self, calendar_id, time_min, time_max=None, max_results=None
    ):
        if self.fail_auth:
            raise GoogleCalendarAuthError("401")
        items = copy.deepcopy(self.listed.get(calendar_id, []))
        return items[:max_results] if max_results else items

    async def async_get_event(self, calendar_id, event_id):
        try:
            return copy.deepcopy(self.resources[calendar_id][event_id])
        except KeyError as err:
            raise GoogleCalendarNotFoundError("404") from err

    async def async_insert_event(self, calendar_id, body):
        self._counter += 1
        self.calls.append(("insert", calendar_id, None, copy.deepcopy(body)))
        return {**body, "id": f"new{self._counter}"}

    async def async_patch_event(self, calendar_id, event_id, body):
        self.calls.append(("patch", calendar_id, event_id, copy.deepcopy(body)))
        return {**body, "id": event_id}

    async def async_delete_event(self, calendar_id, event_id):
        self.calls.append(("delete", calendar_id, event_id, None))


@pytest.fixture
def fake_api() -> Generator[FakeGoogleApi]:
    """Patch the API client used by the integration."""
    api = FakeGoogleApi()
    with patch(
        "custom_components.advanced_google_calendar.GoogleCalendarApi",
        return_value=api,
    ):
        yield api


@pytest.fixture
async def setup_credentials(hass: HomeAssistant) -> None:
    """Register application credentials."""
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential(CLIENT_ID, CLIENT_SECRET), DOMAIN
    )


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for one Google account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=ACCOUNT,
        unique_id=ACCOUNT,
        data={
            "auth_implementation": DOMAIN,
            "token": {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": time.time() + 3600,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        },
        options={
            CONF_CALENDARS: [ACCOUNT, "holidays@group.v.calendar.google.com"],
            CONF_SCAN_INTERVAL: 5,
        },
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    setup_credentials: None,
    config_entry: MockConfigEntry,
    fake_api: FakeGoogleApi,
) -> MockConfigEntry:
    """Set up the integration with the fake API."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
