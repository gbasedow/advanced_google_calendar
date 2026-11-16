"""Tests for the REST client."""

from __future__ import annotations

from datetime import datetime

from aiohttp import ClientResponseError, RequestInfo
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from yarl import URL

from custom_components.advanced_google_calendar.api import (
    GoogleCalendarApi,
    GoogleCalendarApiError,
    GoogleCalendarAuthError,
    GoogleCalendarNotFoundError,
)
from custom_components.advanced_google_calendar.const import API_BASE_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

CAL = "family#de@group.calendar.google.com"
CAL_URL = f"{API_BASE_URL}/calendars/family%23de%40group.calendar.google.com/events"


async def _token() -> str:
    return "token"


async def test_list_events_pagination_and_quoting(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Pages are followed, ids are quoted and the token is sent."""
    aioclient_mock.get(
        CAL_URL,
        params={"pageToken": "p2"},
        json={"items": [{"id": "b"}]},
    )
    aioclient_mock.get(CAL_URL, json={"items": [{"id": "a"}], "nextPageToken": "p2"})
    api = GoogleCalendarApi(async_get_clientsession(hass), _token)
    start = datetime(2026, 11, 1, tzinfo=dt_util.UTC)
    items = await api.async_list_events(CAL, start, start.replace(month=12))
    assert [i["id"] for i in items] == ["a", "b"]
    _, url, _, headers = aioclient_mock.mock_calls[0]
    assert url.query["singleEvents"] == "true"
    assert url.query["timeMin"] == "2026-11-01T00:00:00+00:00"
    assert headers["Authorization"] == "Bearer token"


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, GoogleCalendarAuthError),
        (404, GoogleCalendarNotFoundError),
        (410, GoogleCalendarNotFoundError),
        (403, GoogleCalendarApiError),
        (500, GoogleCalendarApiError),
    ],
)
async def test_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int, exc: type
) -> None:
    """HTTP errors are mapped to exceptions."""
    aioclient_mock.delete(
        f"{CAL_URL}/e1", status=status, json={"error": {"message": "nope"}}
    )
    api = GoogleCalendarApi(async_get_clientsession(hass), _token)
    with pytest.raises(exc, match="nope"):
        await api.async_delete_event(CAL, "e1")


async def test_delete_no_content(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """204 responses are handled."""
    aioclient_mock.delete(f"{CAL_URL}/e1", status=204)
    api = GoogleCalendarApi(async_get_clientsession(hass), _token)
    await api.async_delete_event(CAL, "e1")


async def test_refresh_token_rejected(hass: HomeAssistant) -> None:
    """A rejected refresh token is an auth error."""

    async def _bad() -> str:
        raise ClientResponseError(
            RequestInfo(URL("https://x"), "POST", {}, URL("https://x")),
            (),
            status=400,
            message="invalid_grant",
        )

    api = GoogleCalendarApi(async_get_clientsession(hass), _bad)
    with pytest.raises(GoogleCalendarAuthError):
        await api.async_list_calendars()
